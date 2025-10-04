# Snapshot Testing — Testing Pattern

## Pattern Name and Classification

-   **Name:** Snapshot Testing
    
-   **Classification:** Regression/Approval Testing / Output-Comparison Pattern
    

## Intent

Capture an **authoritative snapshot** of an output (HTML, JSON, text, SQL, email, config), keep it under version control, and on every test run **diff the current output against the stored snapshot** to detect unintended changes.

## Also Known As

-   Approval Testing
    
-   Snapshot/Expect File Testing
    
-   Baseline Testing
    
-   Golden/Snapshot Files (closely related to Golden Master)
    

## Motivation (Forces)

-   **Wide-surface outputs** (rendered UI, templated emails, API payloads) are tedious to assert field-by-field.
    
-   **Fast safety net** needed during refactors/visual tweaks/formatting changes.
    
-   **Human review loop:** easy to inspect diffs in PRs.  
    Tensions:
    
-   **Flakiness** from timestamps/IDs/order → requires normalization.
    
-   **Noise vs. signal:** snapshots that are too big/unstable cause churn and “approve-all” habits.
    
-   **Intentional changes:** need a safe, explicit update flow.
    

## Applicability

Use snapshot tests when:

-   Outputs are **textual/serializable** and meaningful to diff (HTML/JSON/Markdown/SQL).
    
-   You change **templates**, **serializers**, or **formatters** frequently.
    
-   You want **refactor confidence** without writing many granular assertions.
    

Avoid or adapt when:

-   Outputs are **nondeterministic** and cannot be normalized.
    
-   Behavior is best asserted with **precise rules** (e.g., business math) — use targeted assertions and/or property tests.
    
-   You need **timing/perf** validation (use performance tests).
    

## Structure

-   **SUT Adapter:** renders/serializes output deterministically from inputs.
    
-   **Normalizer:** removes nondeterminism (EOLs, timestamps, UUIDs, ordering).
    
-   **Snapshot Store:** versioned baseline files `*.snap`.
    
-   **Comparator & Reporter:** compares normalized current output vs. snapshot; writes `*.received` on failure; prints a diff.
    
-   **Updater:** explicitly refreshes snapshots when changes are intended (flag/env/IDE task).
    

```css
[Inputs] → [SUT] → [Output] → [Normalize] → compare ↔ [Snapshot File]
                                              │
                                              └─ if different → write *.received + fail
```

## Participants

-   **Test Harness** — orchestrates generation, normalization, comparison.
    
-   **Snapshot Repository** — filesystem under VCS.
    
-   **Developer/Reviewer** — inspects diffs; approves updates intentionally.
    

## Collaboration

1.  Test builds a **deterministic input** and generates the **output**.
    
2.  Output is **normalized** (mask time/IDs, canonicalize).
    
3.  Compare to the stored snapshot.
    
4.  If different, store a `*.received` file and **fail**.
    
5.  If the change is expected, rerun with **update flag** to refresh the snapshot; reviewer verifies in PR.
    

## Consequences

**Benefits**

-   Rapid coverage for complex outputs; **clear diffs** in PRs.
    
-   Great for **templates and serializers**.
    
-   Encourages **determinism** and normalization discipline.
    

**Liabilities**

-   Large snapshots can be noisy; small tweaks create churn.
    
-   Risk of **rubber-stamping** updates if process is lax.
    
-   Requires careful **masking** of nondeterministic fields.
    

## Implementation

### Guidelines

-   **Keep snapshots small & scoped** (one scenario per file).
    
-   **Normalize aggressively:** EOLs, timestamps, UUIDs, dynamic IDs, map ordering.
    
-   **Name snapshots** by scenario (`order_confirm_basic.snap`).
    
-   **Guard updates** behind a flag (`-Dsnap.update=true` or `SNAP_UPDATE=1`).
    
-   **Review diffs** like code; forbid blind mass updates.
    
-   **Combine with focused assertions** for critical invariants (status codes, key headers).
    
-   **Binary outputs:** compare derived text (PDF-to-text) or hashes + artifact diffs.
    

### Typical Normalizations

-   Replace ISO timestamps `2025-10-04T12:34:56Z` → `<INSTANT>`.
    
-   Replace UUIDs → `<UUID>`.
    
-   Canonicalize JSON: sort keys, pretty-print.
    
-   Normalize whitespace/EOLs; trim trailing spaces.
    

---

## Sample Code (Java 17, JUnit 5) — Minimal Snapshot Harness

**What it shows**

-   A tiny **snapshot utility** with normalization, update guard, and diff.
    
-   A small **renderer** (HTML email) used as SUT.
    
-   A **snapshot test** that compares current rendering to a `*.snap` file.
    

> Layout:

```bash
src/
 ├─ main/java/example/EmailRenderer.java
 └─ test/
    ├─ java/example/Snapshot.java
    └─ java/example/EmailRendererSnapshotTest.java
    └─ resources/snapshots/order_confirm_basic.snap      (checked in)
```

### SUT: simple HTML renderer

```java
// src/main/java/example/EmailRenderer.java
package example;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.*;

public class EmailRenderer {

  public static final class Line {
    public final String sku, name; public final int qty; public final BigDecimal price;
    public Line(String sku, String name, int qty, BigDecimal price) { this.sku=sku; this.name=name; this.qty=qty; this.price=price; }
  }

  public static final class Order {
    public final String id, customerEmail; public final Instant createdAt; public final List<Line> lines = new ArrayList<>();
    public Order(String id, String customerEmail, Instant createdAt) { this.id=id; this.customerEmail=customerEmail; this.createdAt=createdAt; }
    public BigDecimal total() {
      return lines.stream().map(l -> l.price.multiply(new BigDecimal(l.qty)))
          .reduce(BigDecimal.ZERO, BigDecimal::add);
    }
  }

  /** Very small HTML template (stable ordering by SKU). */
  public String renderOrderConfirmation(Order o) {
    StringBuilder sb = new StringBuilder();
    sb.append("<!doctype html><html><body>");
    sb.append("<h1>Order ").append(o.id).append("</h1>");
    sb.append("<p>Customer: ").append(o.customerEmail).append("</p>");
    sb.append("<p>Created: ").append(o.createdAt).append("</p>");
    sb.append("<ul>");
    o.lines.stream().sorted(Comparator.comparing(l -> l.sku))
        .forEach(l -> sb.append("<li>").append(l.sku).append(" ")
            .append(l.name).append(" x").append(l.qty)
            .append(" @ ").append(l.price).append("</li>"));
    sb.append("</ul>");
    sb.append("<p>Total: ").append(o.total()).append("</p>");
    sb.append("</body></html>");
    return sb.toString();
  }
}
```

### Snapshot Utility

```java
// src/test/java/example/Snapshot.java
package example;

import static org.junit.jupiter.api.Assertions.fail;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.Objects;
import java.util.regex.Pattern;

public final class Snapshot {
  private static final Path SNAP_DIR = Path.of("src/test/resources/snapshots");
  private static final Path RECEIVED_DIR = Path.of("target/snapshots");

  private static final Pattern UUID_RE = Pattern.compile("\\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\\b");
  private static final Pattern INSTANT_RE = Pattern.compile("\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}Z");

  private Snapshot() {}

  public static void assertMatches(String name, String rawContent) {
    try {
      Files.createDirectories(SNAP_DIR); Files.createDirectories(RECEIVED_DIR);
      String normalized = normalize(rawContent);
      Path golden = SNAP_DIR.resolve(name + ".snap");
      Path received = RECEIVED_DIR.resolve(name + ".received.snap");

      if (!Files.exists(golden) || shouldUpdate()) {
        Files.writeString(golden, normalized, StandardCharsets.UTF_8);
        System.out.println("[Snapshot] " + (Files.exists(golden) ? "UPDATED " : "CREATED ") + golden.toAbsolutePath());
        return;
      }

      String expected = Files.readString(golden, StandardCharsets.UTF_8);
      if (!Objects.equals(expected, normalized)) {
        Files.writeString(received, normalized, StandardCharsets.UTF_8);
        String diff = diffLines(expected, normalized, 120);
        fail("""
            Snapshot mismatch for '%s'
            golden  : %s
            received: %s
            --- diff (golden vs received) ---
            %s
            """.formatted(name, golden.toAbsolutePath(), received.toAbsolutePath(), diff));
      }
    } catch (IOException e) {
      throw new RuntimeException("Snapshot IO error: " + e.getMessage(), e);
    }
  }

  private static String normalize(String s) {
    String eol = s.replace("\r\n", "\n").replace("\r", "\n").trim() + "\n";
    String masked = UUID_RE.matcher(eol).replaceAll("<UUID>");
    masked = INSTANT_RE.matcher(masked).replaceAll("<INSTANT>");
    return masked;
  }

  private static boolean shouldUpdate() {
    return "true".equalsIgnoreCase(System.getProperty("snap.update"))
        || "1".equals(System.getenv().getOrDefault("SNAP_UPDATE", "0"));
  }

  private static String diffLines(String a, String b, int max) {
    String[] al = a.split("\n", -1), bl = b.split("\n", -1);
    int n = Math.min(Math.max(al.length, bl.length), max);
    StringBuilder sb = new StringBuilder();
    for (int i = 0; i < n; i++) {
      String L = i < al.length ? al[i] : "<EOF>";
      String R = i < bl.length ? bl[i] : "<EOF>";
      if (!Objects.equals(L, R)) {
        sb.append(String.format("-%3d | %s%n", i+1, L));
        sb.append(String.format("+%3d | %s%n", i+1, R));
      }
    }
    if (al.length != bl.length) sb.append("(length differs: ").append(al.length).append(" vs ").append(bl.length).append(")\n");
    return sb.toString();
  }
}
```

### Snapshot Test

```java
// src/test/java/example/EmailRendererSnapshotTest.java
package example;

import static example.Snapshot.assertMatches;

import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.Instant;

class EmailRendererSnapshotTest {

  @Test
  void order_confirm_basic_snapshot() {
    var renderer = new EmailRenderer();
    var order = new EmailRenderer.Order("ORD-1234-5678-90", "alice@example.com",
        Instant.parse("2025-01-01T12:00:00Z")); // deterministic

    order.lines.add(new EmailRenderer.Line("SKU-100", "Coffee Beans", 2, new BigDecimal("9.90")));
    order.lines.add(new EmailRenderer.Line("SKU-200", "Mug", 1, new BigDecimal("4.50")));

    String html = renderer.renderOrderConfirmation(order);

    // Compare against src/test/resources/snapshots/order_confirm_basic.snap
    assertMatches("order_confirm_basic", html);
  }
}
```

**Run & update**

```bash
# First run creates the snapshot:
mvn -Dtest=example.EmailRendererSnapshotTest test
# After intentional template change, update snapshot explicitly:
mvn -Dtest=example.EmailRendererSnapshotTest -Dsnap.update=true test
# or: SNAP_UPDATE=1 mvn test
```

---

## Known Uses

-   **UI/component rendering** (server-side HTML, emails, PDF-to-text).

-   **API serializers** (JSON/XML/YAML) — pin field order/formatting.

-   **Code generators/linters/formatters** — verify emitted text.

-   **SQL/query builders** — snapshot generated SQL for complex ORMs.

-   **Config-as-code** (K8s manifests, Terraform plans) — snapshot normalized manifests.


## Related Patterns

-   **Golden Master:** broader concept of locking behavior via stored outputs; snapshot testing is a pragmatic test-level incarnation.

-   **Regression Testing:** snapshot files serve as precise regression oracles.

-   **Contract Testing:** asserts cross-service expectations; can use snapshots for payload examples.

-   **Data-Driven Testing:** feed many rows into the same snapshot assertion.

-   **Mutation Testing:** ensures your tests (including snapshots) actually fail on meaningful changes.

-   **End-to-End Testing:** can use snapshots for page fragments or API responses within flows.


---

## Implementation Tips

-   Keep snapshots **reviewable**: prefer **pretty, compact** formats with stable ordering.

-   **Mask secrets/PII** and nondeterministic fields.

-   Store **one scenario per file**; avoid mega-snapshots.

-   Integrate with CI to **fail on diffs** and show `*.received` as artifacts.

-   Pair snapshots with **targeted assertions** for critical rules (status codes, required headers).

-   Periodically **curate** snapshots: delete obsolete ones, split overly large cases, and ensure they reflect real scenarios.
