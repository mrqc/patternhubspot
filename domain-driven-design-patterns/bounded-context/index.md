
# Bounded Context — Domain-Driven Design Pattern

---

## Pattern Name and Classification

-   **Name:** Bounded Context

-   **Category:** DDD / Strategic Design / Context Mapping

-   **Level:** System and organization boundary pattern


> (You wrote “Boundex Context”; this pattern is **Bounded Context**.)

---

## Intent

Partition a large domain into **explicitly delimited models**—each with its own **ubiquitous language, model, and team ownership**—to keep concepts consistent **within** the boundary and to integrate **between** boundaries via well-defined contracts.

---

## Also Known As

-   Context Boundary

-   Model Boundary

-   Business Capability Context


---

## Motivation (Forces)

-   Large systems accumulate **multiple meanings** for the same term (“Customer”, “Order”).

-   Trying to keep **one global model** leads to ambiguity, coupling, and slow delivery.

-   Teams need **autonomy** to evolve models independently; integration should be explicit.


**Forces / Trade-offs**

-   -   Clear language & model per context; faster change, fewer clashes.

-   -   Enables team autonomy, independent deployment and scaling.

-   − Requires **context mapping** and integration (ACL, translation).

-   − Extra coordination across contexts; duplication where concepts overlap (by design).


---

## Applicability

Use Bounded Contexts when:

-   The domain is broad with **conflicting definitions** of key terms.

-   Multiple teams need **independent velocity** and different data lifecycles.

-   You plan to adopt **microservices** or modular monolith with strict boundaries.


Avoid or defer when:

-   The product is tiny and one model suffices (premature partitioning adds cost).

-   The language and data are genuinely uniform across all use cases.


---

## Structure

-   **Bounded Context**: a runtime + code + data boundary for a coherent model and language.

-   **Context Map**: relationships **between** contexts (Partnership, Customer/Supplier, ACL, Conformist, Published Language, etc.).

-   **Translation Layer** at boundaries (Anti-Corruption Layer, messaging contracts).


```sql
[Context A: Sales] <──(Published Language / Events)──> [Context B: Billing]
        |                                                      |
     Ubiquitous language A                                 Ubiquitous language B
     Model A (entities/VOs)                                Model B (entities/VOs)
```

---

## Participants

-   **Context Owner Team** – owns model, language, deployment.

-   **Context Map** – artifact describing relationships & contracts.

-   **Integration Components** – ACLs, translators, event subscribers.

-   **Shared Kernel (optional)** – carefully agreed common subset of model/code.


---

## Collaboration

-   **Anti-Corruption Layer** to protect models at boundaries.

-   **Domain Events / Published Language** for async, low-coupling integration.

-   **Customer–Supplier / Conformist** relationships define power dynamics.

-   **Sagas/Process Managers** span steps across contexts without leaking models.


---

## Consequences

**Benefits**

-   Conceptual **clarity**: each term has one meaning per context.

-   **Autonomy** and independent scaling/deployment.

-   Limits blast radius of change; reduces cross-team contention.

-   Enables **polyglot** persistence/tech by context.


**Liabilities**

-   Integration cost: translation, duplication of similar concepts.

-   Requires **discipline** to prevent accidental leaks across boundaries.

-   Potential reporting/query complexity across contexts.


Mitigations:

-   Maintain an up-to-date **Context Map** and contracts.

-   Prefer **event-driven** integration and contracts tested with consumer/provider tests.

-   Use **IDs** across contexts, not direct object refs.


---

## Implementation

1.  **Discover subdomains** (core, supporting, generic) and **capabilities**.

2.  **Define context boundaries** aligned to subdomains/teams. Name each language explicitly.

3.  **Model inside the boundary**: entities, value objects, aggregates, invariants.

4.  **Seal the boundary**: repositories, APIs, schemas are **internal**; expose **contracts** (REST/gRPC/events) in your language.

5.  **Map relationships** with a **Context Map** and choose patterns (ACL, Published Language, Conformist, etc.).

6.  **Automate contracts**: consumer-driven contracts, schema registry, versioning.

7.  **Enforce in code**: separate packages/modules, build boundaries (module systems), database per context (or per schema).

8.  **Operate**: independent pipelines, versioning, and SLOs per context.


---

## Sample Code (Java — Two Bounded Contexts with an ACL)

> Example shows **Sales** (places orders) and **Billing** (invoices). Each has its own model. Integration uses **events + ACL** so models don’t leak.

```java
// === Context: Sales (language: "Order", "LineItem") ==========================
package sales.domain;

public record ProductId(String value) {}
public record Money(long cents) { public Money add(Money o){ return new Money(cents+o.cents);} }

final class LineItem {
    private final ProductId productId;
    private final int qty;
    private final Money unitPrice;
    LineItem(ProductId id, int qty, Money price) {
        if (qty <= 0) throw new IllegalArgumentException("qty>0");
        this.productId = id; this.qty = qty; this.unitPrice = price;
    }
    Money subtotal() { return new Money(unitPrice.cents() * qty); }
}

public final class Order {
    private final java.util.UUID id = java.util.UUID.randomUUID();
    private final java.util.List<LineItem> items = new java.util.ArrayList<>();
    private boolean confirmed;

    public void add(ProductId p, int qty, Money price){ ensureOpen(); items.add(new LineItem(p, qty, price)); }
    public void confirm(){ ensureOpen(); if(items.isEmpty()) throw new IllegalStateException("empty"); confirmed = true; }
    public Money total(){ return items.stream().map(LineItem::subtotal).reduce(new Money(0), Money::add); }
    public java.util.UUID id(){ return id; }
    private void ensureOpen(){ if(confirmed) throw new IllegalStateException("confirmed"); }
}

// Event published by Sales (Published Language)
package sales.events;
public record OrderConfirmed(java.util.UUID orderId, long totalCents) {}
```

```java
// === Context: Billing (language: "Invoice", "Amount") ========================
package billing.domain;

public record Amount(long cents) {}
public final class Invoice {
    private final java.util.UUID id = java.util.UUID.randomUUID();
    private final java.util.UUID orderId;
    private final Amount amount;
    private boolean issued;

    public Invoice(java.util.UUID orderId, Amount amount) {
        this.orderId = orderId; this.amount = amount;
    }
    public void issue(){ if(issued) throw new IllegalStateException("already"); issued = true; }
    public java.util.UUID id(){ return id; }
}
```

```java
// === Integration / ACL (keeps models separate) ===============================
package integration.sales2billing;

import sales.events.OrderConfirmed;
import billing.domain.Invoice;
import billing.domain.Amount;

// Translator applies mapping/policy; note: no Sales types leak into Billing domain
public final class SalesToBillingAcl {

    public Invoice translate(OrderConfirmed evt) {
        // Policy: 1:1 mapping from order confirmation to invoice draft
        return new Invoice(evt.orderId(), new Amount(evt.totalCents()));
    }
}
```

```java
// === Application wire-up (subscriber in Billing context) =====================
package billing.app;

import integration.sales2billing.SalesToBillingAcl;
import sales.events.OrderConfirmed;
import billing.domain.Invoice;

public class BillingEventHandler {
    private final SalesToBillingAcl acl = new SalesToBillingAcl();
    private final InvoiceRepository repo; // Billing-owned repository

    public BillingEventHandler(InvoiceRepository repo) { this.repo = repo; }

    // Called by message listener in Billing context
    public void on(OrderConfirmed evt) {
        Invoice inv = acl.translate(evt);
        inv.issue();
        repo.save(inv);
    }
}

interface InvoiceRepository {
    void save(Invoice invoice);
}
```

**Notes**

-   Different **packages** (or modules) per context; separate repositories and data stores are typical.

-   Integration uses **events plus an ACL translator**; each context preserves its own language.

-   Teams can release each context independently.


---

## Known Uses

-   **E-commerce platforms**: `Catalog`, `Pricing`, `Ordering`, `Billing`, `Fulfillment`.

-   **Banking**: `Accounts`, `Payments`, `Risk`, `Ledger`.

-   **Automotive retail**: `Leads`, `Agreements`, `Market Areas`, `Inventory`.

-   **Large SaaS**: split by business capability (e.g., `Identity`, `Billing`, `Analytics`).


---

## Related Patterns

-   **Context Map** – documents relationships between contexts.

-   **Anti-Corruption Layer** – protects a context from external models.

-   **Shared Kernel** – carefully shared subset across contexts.

-   **Customer–Supplier / Conformist** – integration power dynamics.

-   **Domain Events / Published Language** – async contracts between contexts.

-   **Saga / Process Manager** – orchestrates workflows spanning contexts.

-   **Hexagonal Architecture** – each context exposes ports and adapters internally.
