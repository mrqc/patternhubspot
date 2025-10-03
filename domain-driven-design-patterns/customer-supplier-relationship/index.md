
# Customer–Supplier Relationship — Domain-Driven Design Pattern

---

## Pattern Name and Classification

-   **Name:** Customer–Supplier Relationship

-   **Category:** DDD / Strategic Design / Context Mapping

-   **Level:** Inter-context governance + integration relationship


---

## Intent

Define an explicit **power and responsibility relationship** between two bounded contexts where:

-   the **Customer** depends on capabilities from the **Supplier**, and

-   the **Supplier** agrees to **prioritize and evolve** its Published Language and contracts to satisfy the Customer’s needs (within agreed constraints).


This creates a **predictable collaboration model** (expectations, SLAs, change process) rather than ad-hoc integration.

---

## Also Known As

-   Provider–Consumer with Influence

-   Contract-First / Producer aligned to Consumer

-   “Customer-Driven Supplier” (in contrast to *Conformist* or purely *Open Host Service*)


---

## Motivation (Forces)

-   Cross-team dependencies often stall delivery due to **unclear priorities** and **opaque contracts**.

-   A dominant platform (Supplier) can still succeed only if it **responds to specific downstream needs**.

-   Customers require **predictability**: SLAs, versioning, change windows, deprecation policy.

-   Suppliers need **bounded obligations** to avoid becoming a bottleneck.


**Forces / Trade-offs**

-   ✅ Clear expectations, faster alignment, fewer breaking changes, shared roadmaps.

-   ⚠️ Coordination overhead, risk of Supplier bottleneck, governance cost, potential politics over priorities.


---

## Applicability

Use this relationship when:

-   A bounded context (Customer) **cannot progress** without timely Supplier changes.

-   The Supplier **owns the canonical model** (e.g., Billing, Identity) but is willing/able to adapt.

-   You want **contract-first development** with consumer input (e.g., consumer-driven contracts, API review boards).


Prefer other relationships when:

-   The Supplier is **non-negotiable** → consider **Conformist**.

-   You must protect a divergent model → use **Anti-Corruption Layer (ACL)**.

-   Two teams evolve as peers → **Partnership**.

-   No integration needed → **Separate Ways**.


---

## Structure

-   **Customer Context**: specifies needs (use cases, acceptance criteria, example messages).

-   **Supplier Context**: owns Published Language (APIs/events), implements changes.

-   **Contract Artifacts**: OpenAPI/Avro/gRPC schemas, event specs, consumer-driven tests.

-   **Governance**: SLAs, versioning policy, deprecation rules, escalation path.


```scss
[Customer Context]  ──(requirements + CDC tests)──▶  [Supplier Context]
       ▲                                                     │
       └──────────────(published contracts + versions)───────┘
```

---

## Participants

-   **Customer Product & Tech Leads** – express needs as examples and tests.

-   **Supplier Product & API Owners** – maintain contracts, roadmaps, and SLAs.

-   **Contract Repo / Schema Registry** – single source of truth for APIs/events.

-   **CI Pipelines** – run consumer-driven contract tests (CDC) against supplier stubs.

-   **Architecture/Governance** – mediates priorities, reviews breaking changes.


---

## Collaboration

-   Works with **Published Language / Open Host Service** (supplier publishes stable contracts).

-   Complements **ACL** (customer can still translate internally, but supplier semantics align).

-   Often combined with **Outbox & Idempotency** for reliability.

-   Coordinates with **Sagas/Process Managers** across contexts.


---

## Consequences

**Benefits**

-   Predictable delivery via **explicit contracts and SLAs**.

-   Reduced breaking changes; **consumer examples** drive supplier design.

-   Faster feedback loops through **automated contract tests**.

-   Clear escalation when obligations aren’t met.


**Liabilities**

-   Supplier roadmap pressure; risk of **central bottleneck**.

-   Negotiation overhead (backlog triage, API councils).

-   If mismanaged, may drift toward **Conformist** (customer just adapts).


**Mitigations**

-   Time-boxed service levels (e.g., “minor change ≤ 2 sprints”).

-   **Versioning discipline**: additive first, deprecate with horizon.

-   **Multiple contract tracks**: “core” vs “customer-specific extensions”.

-   **Consumer quotas** to avoid “snowflake” overload.


---

## Implementation

1.  **Establish a Contract Repo** (Git): schemas, examples, CDC tests, changelog, deprecation calendar.

2.  **Define SLAs & Policy**: response times, versioning (SemVer), rollout windows, support period (e.g., N-2).

3.  **Consumer-Driven Contracts (CDC)**: customers submit example requests/responses; supplier runs them in CI.

4.  **Decouple runtime**: even with alignment, use **idempotency**, **retries**, **outbox**, **dead-letter** queues.

5.  **Change Process**: RFC/ADR for breaking changes; migration guides; canary endpoints.

6.  **Monitoring**: contract coverage (which endpoints have CDC), schema drift alerts, deprecation usage dashboards.

7.  **Fallbacks**: feature flags, dual-write/dual-read windows during migrations.


---

## Sample Code (Java) — Minimal CDC style + Published Language

*Scenario:* **Sales (Customer)** needs an **Invoice API** from **Billing (Supplier)**.  
The Customer contributes a **contract test** (example) that the Supplier must satisfy.  
In practice you’d use tools like Pact or Spring Cloud Contract; here’s a self-contained sketch.

```java
// === Supplier's Published Language (contract DTOs) ==========================
package contracts.billing.v1;

// Published request/response; evolve via additive fields + SemVer
public class CreateInvoiceRequest {
    public String orderId;      // required
    public long amountCents;    // required
    public String currency = "EUR"; // defaulted
    public String customerEmail;    // optional
}

public class CreateInvoiceResponse {
    public String invoiceId;
    public String status; // "ISSUED" | "REJECTED" | "PENDING"
}
```

```java
// === Supplier API interface (Open Host Service) =============================
package billing.api;

import contracts.billing.v1.CreateInvoiceRequest;
import contracts.billing.v1.CreateInvoiceResponse;

public interface InvoiceApi {
    CreateInvoiceResponse create(CreateInvoiceRequest req);
}
```

```java
// === Customer-provided CDC example (executable test) ========================
package sales.cdc;

import billing.api.InvoiceApi;
import contracts.billing.v1.CreateInvoiceRequest;
import contracts.billing.v1.CreateInvoiceResponse;

import static org.junit.jupiter.api.Assertions.*;

// In real life this runs in a shared CI pipeline against the supplier's stub
public class InvoiceContractTest {

    // A stub or testcontainer provided by Supplier CI; here a tiny fake:
    private final InvoiceApi supplierStub = new InvoiceApi() {
        @Override public CreateInvoiceResponse create(CreateInvoiceRequest req) {
            var resp = new CreateInvoiceResponse();
            if (req.orderId == null || req.orderId.isBlank() || req.amountCents <= 0) {
                resp.status = "REJECTED";
            } else {
                resp.invoiceId = "INV-" + req.orderId;
                resp.status = "ISSUED";
            }
            return resp;
        }
    };

    @org.junit.jupiter.api.Test
    void create_invoice_success_example() {
        var req = new CreateInvoiceRequest();
        req.orderId = "ORD-123";
        req.amountCents = 12_500;
        req.currency = "EUR";

        CreateInvoiceResponse resp = supplierStub.create(req);

        assertNotNull(resp.invoiceId);
        assertEquals("ISSUED", resp.status);
    }

    @org.junit.jupiter.api.Test
    void create_invoice_validation_example() {
        var req = new CreateInvoiceRequest();
        req.orderId = "";    // invalid
        req.amountCents = 0; // invalid

        CreateInvoiceResponse resp = supplierStub.create(req);

        assertEquals("REJECTED", resp.status);
    }
}
```

```java
// === Supplier implementation conforms to CDC and adds internal domain =======
package billing.app;

import billing.api.InvoiceApi;
import contracts.billing.v1.CreateInvoiceRequest;
import contracts.billing.v1.CreateInvoiceResponse;

import java.util.UUID;

public class InvoiceApiImpl implements InvoiceApi {
    private final InvoiceDomainService domain;

    public InvoiceApiImpl(InvoiceDomainService domain) { this.domain = domain; }

    @Override
    public CreateInvoiceResponse create(CreateInvoiceRequest req) {
        var result = domain.issue(req.orderId, req.amountCents, req.currency, req.customerEmail);
        var resp = new CreateInvoiceResponse();
        if (result.success()) {
            resp.invoiceId = result.invoiceId();
            resp.status = "ISSUED";
        } else {
            resp.status = "REJECTED";
        }
        return resp;
    }
}

record IssueResult(boolean success, String invoiceId) {}
class InvoiceDomainService {
    IssueResult issue(String orderId, long amount, String currency, String email) {
        if (orderId == null || orderId.isBlank() || amount <= 0) return new IssueResult(false, null);
        // … domain rules, persistence, outbox event …
        return new IssueResult(true, "INV-" + UUID.randomUUID());
    }
}
```

```java
// === Customer Application Service uses the Published Language directly ======
package sales.app;

import billing.api.InvoiceApi;
import contracts.billing.v1.CreateInvoiceRequest;
import contracts.billing.v1.CreateInvoiceResponse;

public class BillingClient {
    private final InvoiceApi api; // could be HTTP client proxy

    public BillingClient(InvoiceApi api) { this.api = api; }

    public String invoiceForOrder(String orderId, long totalCents) {
        var req = new CreateInvoiceRequest();
        req.orderId = orderId;
        req.amountCents = totalCents;
        CreateInvoiceResponse resp = api.create(req);
        if (!"ISSUED".equals(resp.status)) throw new IllegalStateException("Invoice failed");
        return resp.invoiceId;
    }
}
```

**Notes**

-   The **CDC tests** are authored by the **Customer** and executed by the **Supplier** in CI.

-   Supplier’s API **implements** the Published Language and must keep tests green.

-   Breaking changes require **new major version** and migration window.


---

## Known Uses

-   **Payments/Billing**: product teams (Customers) drive new fields or flows; platform (Supplier) publishes contract and timelines.

-   **Identity/Access**: product apps request claims/scopes; identity platform evolves tokens & endpoints accordingly.

-   **Catalog/Pricing**: Sales requires price rules; Pricing (Supplier) adds events/fields per roadmap agreement.

-   **Logistics**: Fulfillment (Customer) asks Shipping (Supplier) to add tracking events and SLAs.


---

## Related Patterns

-   **Published Language / Open Host Service** — how the Supplier exposes stable contracts.

-   **Conformist** — when Customer has little/no influence (contrast).

-   **Anti-Corruption Layer** — Customer shields its model even if Supplier accommodates.

-   **Partnership** — peers co-own evolution (symmetric).

-   **Context Map** — documents this relationship system-wide.

-   **Transactional Outbox / Idempotency** — reliability patterns frequently paired.
