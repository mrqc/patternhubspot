# Golden Master — Testing Pattern

## Pattern Name and Classification

-   **Name:** Golden Master (a.k.a. Characterization / Snapshot testing)
    
-   **Classification:** Regression Testing / Approval Testing / Behavior Preservation Pattern
    

## Intent

Capture the **current, externally visible output** of a system for a representative set of inputs and **treat it as the master (“golden”) result**. Future changes are validated by **diffing new outputs** against the golden master to detect unintended regressions—especially useful when the internal design is hard to understand or refactor safely.

## Also Known As

-   Characterization Tests (Michael Feathers)
    
-   Approval Tests / Snapshot Tests
    
-   Baseline / Oracle Files
    

## Motivation (Forces)

-   **Legacy or complex code:** You must refactor or optimize but lack reliable unit tests or a precise spec.
    
-   **Wide surface area:** The behavior spans complex formatting, rendering, or orchestration; writing assert-by-assert tests is prohibitive.
    
-   **Fast safety net:** You want **broad regression coverage** quickly before refactoring.  
    Tensions to balance:
    
-   **Signal vs. noise:** Avoid flaky masters (timestamps, nondeterminism).
    
-   **Granularity:** Big snapshots are easy to create but hard to interpret when they fail; too small and they miss regressions.
    
-   **Maintenance:** Updating masters must be easy but **intentional**.
    

## Applicability

Use Golden Master when:

-   You need to **lock in** existing behavior before refactoring (even if “weird”) to avoid altering live outcomes.
    
-   Outputs are **serializations, reports, HTML/JSON**, or other text artifacts where **diffs are meaningful**.
    
-   The system is **hard to isolate** with unit tests but can be driven end-to-end with deterministic inputs.
    

Be cautious when:

-   Outputs include **sensitive data** (apply masking/anonymization).
    
-   Outputs are **nondeterministic** (introduce normalization or fakes).
    
-   The change is expected to **legitimately** alter outputs—ensure a clear process to update masters.
    

## Structure

-   **Input Corpus:** curated or generated set of representative inputs.
    
-   **System Under Test (SUT):** produces externally observable output.
    
-   **Normalizer:** removes or stabilizes nondeterminism (timestamps, GUIDs, ordering).
    
-   **Golden Store:** version-controlled baseline files (masters).
    
-   **Comparator & Reporter:** diffs current vs. golden, produces actionable failure artifacts.
    
-   **Updater (guarded):** intentionally refreshes masters when behavior changes by design.
    

```css
[Inputs] → [SUT] → [Raw Output] → [Normalizer] → [Current Snapshot]
                                         │
                                         ├── compare ───► [Golden Snapshot] ──► pass/fail + diff
                                         └── (guarded) update golden
```

## Participants

-   **Test Harness / Runner** – orchestrates corpus generation, normalization, comparison.
    
-   **SUT Adapter** – invokes the actual production code deterministically.
    
-   **Golden Repository** – stores masters under source control.
    
-   **Diff Reporter** – writes “received” files and human-friendly diffs.
    

## Collaboration

1.  Build or load the **input corpus**.
    
2.  Run the **SUT** to produce outputs.
    
3.  **Normalize** outputs (mask nondeterminism, sort keys/lines if needed).
    
4.  Compare normalized output to the **golden** file.
    
5.  On mismatch, fail the test, write a **received** artifact, and show a **diff**.
    
6.  When a change is **intended**, consciously **update** the golden file.
    

## Consequences

**Benefits**

-   Rapid creation of broad regression coverage for **legacy code**.
    
-   Encourages **safe refactoring**: you can change internals while preserving observable behavior.
    
-   Diffs give **high signal** on rendering/serialization changes.
    

**Liabilities**

-   **Overly large snapshots** produce noisy diffs; small changes can cause big failures.
    
-   **Flakiness** if normalization is insufficient (time, randomness, ordering).
    
-   Temptation to **rubber-stamp updates** erodes test value—enforce review hygiene.
    
-   Not a substitute for **specification tests** (asserting specific rules).
    

## Implementation

### Practical Guidelines

-   **Determinize**: fix random seeds, inject a **fake clock**, or **normalize** timestamps/UUIDs.
    
-   **Normalize**: canonicalize JSON (sorted keys), collapse whitespace, mask ephemeral fields.
    
-   **Segment**: store one master per scenario or domain area; prefer many small files over one giant file.
    
-   **Guard updates**: require a flag (`-Dgolden.update=true`) or approval step to refresh masters.
    
-   **Artifacts**: on failure, write `*.received.*` alongside `*.golden.*` and print a clear path + mini-diff.
    
-   **Review**: treat golden updates like code changes; reviewers must verify the behavior shift is intended.
    

### Choosing the Corpus

-   Include **happy paths**, **edge cases**, **bad inputs**, and **realistic samples** (after anonymization).
    
-   Consider **property-generated** inputs (seeded RNG) to broaden coverage while remaining reproducible.
    
-   Keep total runtime acceptable; shard corpuses if needed.
    

---

## Sample Code (Java 17, JUnit 5)

A small **invoice renderer** acts as SUT. The Golden Master test:

-   Generates **deterministic orders** (seeded RNG).
    
-   Renders invoices, **normalizes** timestamps/UUIDs, aggregates into a single snapshot.
    
-   Compares with a versioned master file.
    
-   Supports **guarded updates** via `-Dgolden.update=true` (or `GOLDEN_UPDATE=1`).
    
-   On mismatch, writes a `*.received.txt` and prints a short diff.
    

> Directory layout (tests read/write under `src/test/resources/golden/`):

```bash
src/
 └─ test/
    ├─ java/
    │   └─ example/golden/GoldenMasterTest.java
    └─ resources/
        └─ golden/invoice_master.txt  (checked into VCS)
```

```java
// src/test/java/example/golden/InvoiceService.java
package example.golden;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.*;
import java.util.*;

public class InvoiceService {

  public record Line(String sku, String name, int qty, BigDecimal unitPrice) {}

  public static class Invoice {
    public final UUID id;
    public final String customerEmail;
    public final Instant createdAt;
    public final List<Line> lines = new ArrayList<>();
    public Invoice(String customerEmail, Instant createdAt) {
      this.id = UUID.randomUUID();
      this.customerEmail = customerEmail;
      this.createdAt = createdAt;
    }
    public BigDecimal subtotal() {
      return lines.stream()
          .map(l -> l.unitPrice.multiply(BigDecimal.valueOf(l.qty)))
          .reduce(BigDecimal.ZERO, BigDecimal::add)
          .setScale(2, RoundingMode.HALF_UP);
    }
  }

  private final BigDecimal vatRate; // e.g., 0.20
  public InvoiceService(BigDecimal vatRate) { this.vatRate = vatRate; }

  /** Renders a simple text invoice (stable ordering by SKU). */
  public String render(Invoice inv) {
    var sb = new StringBuilder();
    sb.append("INVOICE ").append(inv.id).append("\n");
    sb.append("Customer: ").append(inv.customerEmail).append("\n");
    sb.append("Created: ").append(inv.createdAt).append("\n");
    sb.append("Lines:\n");
    inv.lines.stream().sorted(Comparator.comparing(l -> l.sku))
        .forEach(l -> sb.append("  - ").append(l.sku).append(" ")
            .append(l.name).append(" x").append(l.qty)
            .append(" @ ").append(l.unitPrice).append("\n"));
    var subtotal = inv.subtotal();
    var vat = subtotal.multiply(vatRate).setScale(2, RoundingMode.HALF_UP);
    var total = subtotal.add(vat).setScale(2, RoundingMode.HALF_UP);
    sb.append("Subtotal: ").append(subtotal).append("\n");
    sb.append("VAT(").append(vatRate).append("): ").append(vat).append("\n");
    sb.append("TOTAL: ").append(total).append("\n");
    return sb.toString();
  }
}
```

```java
// src/test/java/example/golden/GoldenMasterTest.java
package example.golden;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.math.BigDecimal;
import java.net.URISyntaxException;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * Golden Master test for InvoiceService rendering.
 */
public class GoldenMasterTest {

  private static final Path GOLDEN_PATH = Path.of("src/test/resources/golden/invoice_master.txt");
  private static final Path RECEIVED_PATH = Path.of("target/golden/invoice_master.received.txt");

  @Test
  void rendering_matches_golden_master() throws Exception {
    // 1) Build deterministic corpus
    String snapshot = buildSnapshot(/*seed*/ 424242L, /*count*/ 25);

    // 2) Normalize nondeterminism
    String normalized = normalize(snapshot);

    // 3) Compare vs. golden (guarded update)
    ensureDirs();
    if (shouldUpdateMaster()) {
      Files.writeString(GOLDEN_PATH, normalized, StandardCharsets.UTF_8);
      System.out.println("[Golden] Master UPDATED at: " + GOLDEN_PATH.toAbsolutePath());
    }

    String golden = readGolden();
    if (!normalized.equals(golden)) {
      Files.createDirectories(RECEIVED_PATH.getParent());
      Files.writeString(RECEIVED_PATH, normalized, StandardCharsets.UTF_8);
      String diff = diffLines(golden, normalized, 80);
      fail("""
          Golden master mismatch.
          Golden : %s
          Received: %s
          --- Diff (golden vs received) ---
          %s
          """.formatted(GOLDEN_PATH.toAbsolutePath(), RECEIVED_PATH.toAbsolutePath(), diff));
    }
  }

  /* ===== Snapshot construction ===== */

  private String buildSnapshot(long seed, int count) {
    var rnd = new Random(seed);
    var svc = new InvoiceService(new BigDecimal("0.20"));
    var baseTime = Instant.parse("2025-01-01T00:00:00Z"); // anchor for determinism

    List<String> blocks = new ArrayList<>();
    for (int i = 0; i < count; i++) {
      var inv = new InvoiceService.Invoice(
          "user" + (i % 7) + "@example.com",
          baseTime.plusSeconds(3600L * i + (rnd.nextInt(300)))
      );
      int lines = 1 + rnd.nextInt(4);
      for (int j = 0; j < lines; j++) {
        String sku = "SKU-" + (100 + rnd.nextInt(20));
        String name = switch (sku.hashCode() % 4) {
          case 0 -> "Coffee Beans";
          case 1 -> "Espresso Machine";
          case 2 -> "Mug";
          default -> "Grinder";
        };
        int qty = 1 + rnd.nextInt(3);
        BigDecimal price = new BigDecimal(String.format(java.util.Locale.ROOT, "%.2f", 2 + rnd.nextDouble(298)));
        inv.lines.add(new InvoiceService.Line(sku, name, qty, price));
      }
      blocks.add("""
          ===== CASE %02d =====
          %s
          """.formatted(i + 1, new String(svc.render(inv))));
    }
    return blocks.stream().collect(Collectors.joining("\n"));
  }

  /* ===== Normalization: mask UUIDs & timestamps, normalize line endings ===== */

  private static final Pattern UUID_RE = Pattern.compile(
      "\\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\\b");
  private static final Pattern ISO_INSTANT_RE = Pattern.compile("\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}Z");

  private String normalize(String s) {
    String eol = s.replace("\r\n", "\n").replace("\r", "\n");
    String masked = UUID_RE.matcher(eol).replaceAll("<UUID>");
    masked = ISO_INSTANT_RE.matcher(masked).replaceAll("<INSTANT>");
    return masked.trim() + "\n";
  }

  /* ===== Utilities ===== */

  private String readGolden() throws IOException, URISyntaxException {
    if (!Files.exists(GOLDEN_PATH)) {
      throw new AssertionError("Golden file missing: " + GOLDEN_PATH.toAbsolutePath()
          + " (run with -Dgolden.update=true to create)");
    }
    return Files.readString(GOLDEN_PATH, StandardCharsets.UTF_8);
  }

  private boolean shouldUpdateMaster() {
    String sys = System.getProperty("golden.update", "false");
    String env = System.getenv().getOrDefault("GOLDEN_UPDATE", "0");
    return "true".equalsIgnoreCase(sys) || "1".equals(env);
    // Example: mvn -Dtest=GoldenMasterTest -Dgolden.update=true test
  }

  private void ensureDirs() throws IOException {
    Files.createDirectories(GOLDEN_PATH.getParent());
    Files.createDirectories(RECEIVED_PATH.getParent());
  }

  /** Tiny line-by-line diff (context omitted for brevity). */
  private String diffLines(String a, String b, int maxLines) {
    List<String> al = a.lines().toList();
    List<String> bl = b.lines().toList();
    int n = Math.min(Math.max(al.size(), bl.size()), maxLines);
    var sb = new StringBuilder();
    for (int i = 0; i < n; i++) {
      String left = i < al.size() ? al.get(i) : "<EOF>";
      String right = i < bl.size() ? bl.get(i) : "<EOF>";
      if (!Objects.equals(left, right)) {
        sb.append(String.format("-%3d | %s%n", i + 1, left));
        sb.append(String.format("+%3d | %s%n", i + 1, right));
      }
    }
    if (al.size() != bl.size()) sb.append("(length differs: ").append(al.size()).append(" vs ").append(bl.size()).append(")\n");
    return sb.toString();
  }
}
```

**What this demonstrates**

-   **Deterministic corpus** (seeded RNG + anchored time).
    
-   **Normalization** masks UUIDs/timestamps to avoid flaky diffs.
    
-   **Guarded updates**: explicit flag to refresh masters.
    
-   **Actionable failure**: writes a `.received` file and prints a compact diff.
    

> In larger systems, store one master per scenario (e.g., `invoice_vip_case1.txt`, `invoice_edge_zero.txt`) and use proper diff tooling (unified diff, JSON canonicalization).

## Known Uses

-   Rendering layers (HTML, emails, PDFs), statement/report generators.
    
-   Serializers & formatters (JSON/XML/YAML) where **field order and formatting** matter.
    
-   Legacy billing/rating/pricing engines to **freeze behavior** before refactors.
    
-   Code formatters/linters (snapshot formatting of representative files).
    
-   Compilers/transpilers: snapshot of **error messages** and generated code.
    

## Related Patterns

-   **Approval Tests / Snapshot Testing** (Jest, ApprovalTests): tooling specialized for golden comparisons.
    
-   **Characterization Tests**: broader concept; Golden Master is the artifact.
    
-   **Data-Driven Testing**: feeds many inputs; can combine with Golden Master outputs.
    
-   **Contract Testing**: focuses on **interface compatibility** between services, not whole-output snapshots.
    
-   **End-to-End Testing**: drives full journeys; its assertions can lean on golden snapshots (e.g., HTML).
    
-   **Fake Object**: helps determinize outputs by replacing nondeterministic collaborators.
    

---

## Implementation Tips

-   **Keep masters small & focused**: snapshot the **relevant** slice (e.g., normalized JSON), not entire pages unless necessary.
    
-   **Mask secrets/PII** in snapshots; commit only safe artifacts.
    
-   **Stabilize order** (sort keys/lines) to reduce diff noise.
    
-   **Automate review**: PRs should show diffs of changed masters; require human approval.
    
-   **Version snapshots** alongside code; tie them to feature versions if needed.
    
-   For binary outputs (PDF/images), snapshot **derived text** (PDF-to-text) or **hashes** plus a visual diff artifact.
    
-   Periodically **curate the corpus** to reflect current real-world cases without bloating run time.

