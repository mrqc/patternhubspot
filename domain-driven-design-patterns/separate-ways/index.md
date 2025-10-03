# Separate Ways (Domain-Driven Design)

## Pattern Name and Classification

**Name:** Separate Ways  
**Classification:** DDD strategic Context-Mapping pattern (organizational/integration strategy)

---

## Intent

Acknowledge that **integrating two bounded contexts is not worth the cost**—for now or permanently—and let each context **evolve independently**. Coordination happens via **humans, documents, or occasional batch transfers**, not tight, runtime coupling.

---

## Also Known As

-   Deliberate Non-Integration

-   Strategic Segregation

-   “Don’t Integrate” Decision


---

## Motivation (Forces)

-   **High integration cost vs. low business value.** Building/maintaining APIs, data contracts, SLAs, security, and monitoring can exceed the benefit.

-   **Mismatched pace or governance.** Different release cadences, compliance regimes, or power dynamics block clean contracts.

-   **Thin overlap.** Domains share little; coupling would leak models and slow both teams.

-   **Stability priorities.** A legacy system is stable; change risk is unacceptable.

-   **Timing.** Early product stage: shipping value beats building a platform.


Tensions to balance:

-   **Autonomy vs. duplication** (you may re-enter data or replicate parts).

-   **Local optimization vs. global coherence** (reports may diverge).

-   **Short-term speed vs. long-term consolidation** (technical debt if never revisited).


---

## Applicability

Choose Separate Ways when:

-   Interaction is **infrequent/one-directional** (e.g., monthly audit file).

-   **Semantics don’t align** and creating a Published Language would distort both domains.

-   A partner is **unreliable** or **politically separate**; contracts can’t be honored.

-   **Deadlines** require focus on core value, not integrations.

-   There is a **temporary** intent to revisit once value is proven.


Avoid when:

-   The workflow **requires** near-real-time consistency or a **single source of truth**.

-   Compliance demands **automated, traceable** interfaces.

-   You repeatedly move data manually—cost/risks start to outweigh savings.


---

## Structure

-   **Context A / Context B:** Each has its own model, language, and cadence.

-   **Human/Document Boundary:** Shared spreadsheets, PDFs, CSVs, or emailed reports mediate occasional coordination.

-   **Optional Batch Export/Import:** Fire-and-forget files; no synchronous contracts or shared runtime APIs.

-   **Governance Artifact:** An ADR (Architecture Decision Record) documenting why and when to revisit.


---

## Participants

-   **Owning Teams (A & B):** Independent roadmaps and ubiquitous languages.

-   **Operations/Business Users:** Perform manual steps (upload/download/reconcile).

-   **Compliance/Finance (optional):** Define artifacts needed (e.g., monthly ledger export).

-   **Tooling:** Shared folders/buckets, job schedulers, checksum validators.


---

## Collaboration

1.  Teams **agree not to integrate** (ADR + context map).

2.  If needed, Context A **produces a boundary document** (e.g., CSV).

3.  Context B **optionally** ingests it **asynchronously**, or users read it manually.

4.  Each side retains **independent semantics** and versioning.

5.  Periodically **reassess** whether integration now makes sense.


---

## Consequences

**Benefits**

-   **Max autonomy & speed.** No negotiation over contracts or runtime SLAs.

-   **Lower operational risk.** Failures in B don’t break A (and vice versa).

-   **Focus on core value.** Avoid premature platform building.


**Liabilities**

-   **Manual work & latency.** Humans fill the gap; data may be stale.

-   **Duplication & drift.** Divergent reports/definitions across contexts.

-   **Future migration cost.** Later integration may require data cleanup and re-modeling.

-   **Audit gaps** if manual processes aren’t controlled.


---

## Implementation

**Guidelines**

-   **Make it explicit.** Record the decision (ADR), the scope, and the **review date**.

-   **Guard the boundary.** No “sneaky” dependencies (no shared libraries, no direct DB reads).

-   **Lightweight artifacts.** If you must exchange data, use **append-only**, well-documented files (CSV/Parquet) with checksums and schema docs.

-   **Operational checklists.** Define who runs exports/imports, where files live, and retention policies.

-   **Observability for manual flows.** Track delivered files, row counts, and reconciliation checks.

-   **Exit strategy.** Criteria that would trigger moving to OHS/Published Language or ACL.


**Anti-patterns**

-   Creeping integration via **shared tables** or **internal endpoints**.

-   Hidden coupling via **shared “common” model libraries**.

-   Treating Separate Ways as neglect; it’s a **conscious trade-off**, not abandonment.


---

## Sample Code (Java)

A pragmatic example showing **no runtime coupling**. The *Sales* context exports a monthly CSV. The *Marketing* context optionally imports it later. There is **no shared code or DTOs** across contexts—only a documented file format.

### Context A: Sales (export only)

```java
// sales-context module (no dependencies on marketing)

package com.acme.sales.export;

import java.io.*;
import java.math.BigDecimal;
import java.nio.file.*;
import java.time.*;
import java.util.List;

public final class MonthlyOrdersExporter {

    public record OrderRow(String orderId, String customerId, BigDecimal total, String currency, LocalDate orderDate) {}

    private final OrdersReportProvider provider;

    public MonthlyOrdersExporter(OrdersReportProvider provider) { this.provider = provider; }

    /** Exports a simple, append-only CSV with a deterministic header and ISO formats. */
    public Path exportMonth(YearMonth month, Path outDir) throws IOException {
        Files.createDirectories(outDir);
        var file = outDir.resolve("orders-" + month + ".csv"); // e.g., orders-2025-09.csv
        try (BufferedWriter w = Files.newBufferedWriter(file)) {
            w.write("order_id,customer_id,total,currency,order_date\n");
            for (OrderRow r : provider.listFor(month)) {
                w.write(String.format("%s,%s,%s,%s,%s%n",
                        r.orderId(),
                        r.customerId(),
                        r.total().toPlainString(),
                        r.currency(),
                        r.orderDate())); // ISO-8601 yyyy-MM-dd
            }
        }
        // Write checksum sidecar
        var checksum = Sha256.of(file);
        Files.writeString(outDir.resolve(file.getFileName() + ".sha256"), checksum);
        return file;
    }

    public interface OrdersReportProvider {
        List<OrderRow> listFor(YearMonth month);
    }

    // Minimal SHA-256 helper (keep simple; or use Guava/Apache Commons in real code)
    static final class Sha256 {
        static String of(Path file) {
            try (var is = Files.newInputStream(file)) {
                var md = java.security.MessageDigest.getInstance("SHA-256");
                is.transferTo(new DigestOutputStream(md));
                return bytesToHex(md.digest());
            } catch (Exception e) { throw new RuntimeException(e); }
        }
        private static String bytesToHex(byte[] bytes) {
            var sb = new StringBuilder(bytes.length * 2);
            for (byte b : bytes) sb.append(String.format("%02x", b));
            return sb.toString();
        }
        private static class DigestOutputStream extends OutputStream {
            private final java.security.MessageDigest md;
            DigestOutputStream(java.security.MessageDigest md) { this.md = md; }
            @Override public void write(int b) { md.update((byte) b); }
            @Override public void write(byte[] b, int off, int len) { md.update(b, off, len); }
        }
    }
}
```

### Context B: Marketing (optional import)

```java
// marketing-context module (no dependencies on sales)

package com.acme.marketing.imports;

import java.io.*;
import java.math.BigDecimal;
import java.nio.file.*;
import java.time.LocalDate;
import java.util.*;

public final class SalesOrdersCsvImporter {

    public record ImportedOrder(String orderId, String customerId, BigDecimal total, String currency, LocalDate orderDate) {}

    public List<ImportedOrder> importFile(Path csvPath) throws IOException {
        var lines = Files.readAllLines(csvPath);
        if (lines.isEmpty() || !lines.get(0).equals("order_id,customer_id,total,currency,order_date")) {
            throw new IllegalArgumentException("Unexpected header in " + csvPath.getFileName());
        }
        var result = new ArrayList<ImportedOrder>();
        for (int i = 1; i < lines.size(); i++) {
            var cols = lines.get(i).split(",", -1);
            if (cols.length != 5) continue; // skip malformed
            result.add(new ImportedOrder(
                    cols[0], cols[1],
                    new BigDecimal(cols[2]), cols[3],
                    LocalDate.parse(cols[4])
            ));
        }
        return result;
    }
}
```

*Notes*

-   There is **no shared library**. The only coupling is a **documented CSV** (a boundary document).

-   Either side can change internally without breaking the other, as long as the CSV remains stable (or versioned with a new filename/header).

-   In reality you’d add: write-once storage (S3 bucket), retention, access controls, and a simple **runbook** for who exports/imports when.


---

## Known Uses

-   **Finance & Audit:** Monthly ledger exports from ERP to a data warehouse managed by a different org.

-   **Regulatory Reporting:** Periodic submissions to authorities with strict file formats.

-   **M&A / Holding structures:** Separate subsidiaries with incompatible systems.

-   **Early-stage products:** Keep Marketing & Product Analytics separate until signal justifies integration.

-   **Vendor/Partner boundaries:** When partner APIs are unstable or contracts can’t be enforced.


---

## Related Patterns

-   **Open Host Service & Published Language:** If/when you later choose to integrate, these provide a stable, public contract.

-   **Anti-Corruption Layer (ACL):** If you must consume another model but protect your own, use ACL instead of merging.

-   **Customer–Supplier / Conformist (Context Map):** Alternative relationships when you do integrate.

-   **Shared Kernel:** The opposite end—**high coupling** by sharing a model; avoid if you’re choosing Separate Ways.

-   **Event-Carried State Transfer / Batch Data Exchange:** Lightweight alternatives for asynchronous sharing without tight coupling.

-   **Partnership:** Tight collaborative integration—only when teams and incentives are aligned.


---
