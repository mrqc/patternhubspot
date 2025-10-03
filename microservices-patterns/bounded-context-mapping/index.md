# Bounded Context Mapping — Microservice Pattern

## Pattern Name and Classification

**Name:** Bounded Context Mapping  
**Classification:** Microservices / Domain-Driven Design (DDD) / Strategic Design & Integration Pattern

## Intent

Explicitly define **boundaries** around domain models (bounded contexts) and make their **relationships and translation mechanisms** deliberate (e.g., Customer–Supplier, Conformist, Anti-Corruption Layer, Shared Kernel, Published Language), so teams can evolve services independently without semantic drift.

## Also Known As

-   Context Map
    
-   Strategic Context Relationships
    
-   DDD Context Integration Map
    

## Motivation (Forces)

-   **Ubiquitous language diverges:** Different subdomains attach different meanings to “Order,” “Customer,” “Status.”
    
-   **Autonomy vs. integration:** Teams must move fast but still interoperate reliably.
    
-   **Evolution & versioning:** Models change; dependencies should not cascade breaking changes.
    
-   **Cognition & ownership:** Clear boundaries reduce accidental coupling and help assign accountability.
    
-   **Governance:** Regulated data (PII, payments) demands explicit contracts and data flow visibility.
    

## Applicability

Use **Bounded Context Mapping** when:

-   Multiple teams own distinct subdomains (Sales, Billing, Logistics) and integrate frequently.
    
-   Terminology is overloaded and causes bugs or miscommunication.
    
-   You plan or refactor microservices and need **explicit contracts** and **translation points**.
    

Avoid overuse when:

-   The system is small and one coherent model suffices (premature fragmentation).
    
-   You don’t have organizational capacity to maintain multiple models and contracts.
    

## Structure

-   **Bounded Contexts:** Autonomous models + Ubiquitous Language (e.g., *Sales Order*, *Invoice*).
    
-   **Context Relationships:**
    
    -   **Customer–Supplier:** Downstream depends on upstream’s contract; negotiation via SLAs.
        
    -   **Conformist:** Downstream adopts upstream’s model (no translation).
        
    -   **Anti-Corruption Layer (ACL):** Downstream protects its model with translators/adapters.
        
    -   **Shared Kernel:** Small shared model (with strict governance).
        
    -   **Published Language / Open Host Service:** Stable, documented contracts.
        
-   **Translation Mechanisms:** Mappers/Adapters, Message Schemas, API Gateways/BFFs.
    

*Textual mini-map (example):*

```css
[Sales BC] --Published Language--> [Billing BC]
     \------ACL------> [CRM BC]          [Inventory BC] <-Customer-Supplier- [Sales BC]
```

## Participants

-   **Upstream Context (Supplier):** Publishes language/contracts (events, APIs).
    
-   **Downstream Context (Customer):** Consumes and adapts.
    
-   **Translator/ACL:** Adapters that map concepts and isolate models.
    
-   **Contract Artifacts:** Schemas, OpenAPI, AsyncAPI, JSON Schema, Avro.
    
-   **Governance Roles:** Architects/owners reviewing relationship choices and change policies.
    

## Collaboration

1.  Teams identify bounded contexts and **name them** with clear scope and owners.
    
2.  For each pair, choose a **relationship type** (Customer–Supplier, ACL, etc.).
    
3.  Define **contracts** (Published Language) and **translation** at the boundary.
    
4.  Implement integration (REST/gRPC/events) with **mappers** and **versioning**.
    
5.  Monitor and evolve contracts; renegotiate relationships as org/domain changes.
    

## Consequences

**Benefits**

-   Reduces semantic bugs and accidental coupling.
    
-   Enables independent evolution and team autonomy.
    
-   Makes integration choices explicit and governable.
    
-   Clarifies ownership and interfaces; improves onboarding.
    

**Liabilities**

-   Additional moving parts (mappers, ACLs, contracts) to maintain.
    
-   Risk of divergence and duplication if governance is weak.
    
-   Shared Kernel can re-couple teams if not tightly controlled.
    
-   Conformist can slow downstream autonomy if upstream changes frequently.
    

## Implementation

**Key practices**

-   **Identify contexts** via subdomain analysis (core, supporting, generic).
    
-   **Pick relationships** deliberately; document rationale and SLAs.
    
-   **Published Language:** Use versioned schemas; prefer backward compatibility.
    
-   **ACL over fragile upstreams:** Translate to your model; isolate breaking changes.
    
-   **Contract tests & CI:** Provider/consumer tests; schema registry with compatibility rules.
    
-   **Evented integrations:** Prefer immutable events with IDs and versions for looser coupling.
    
-   **Security & compliance:** Mark data classification crossing boundaries (PII, PCI).
    

**Documentation example (YAML snippet)**

```yaml
contexts:
  sales:
    owner: Team-Sales
    language: SalesOrder, LineItem, CustomerRef
  billing:
    owner: Team-Billing
    language: Invoice, Charge, Debtor
relationships:
  - type: PublishedLanguage
    upstream: sales
    downstream: billing
    contract: asyncapi://events.sales.v1
  - type: AntiCorruptionLayer
    upstream: crm
    downstream: sales
    adapter: SalesCrmAcl
  - type: CustomerSupplier
    upstream: inventory
    downstream: sales
    sla: "99.9% / p95<150ms / versioned"
```

---

## Sample Code (Java) — Anti-Corruption Layer between **Sales** and **Billing**

> Scenario: *Sales* emits `SalesOrderPlaced` events (its language). *Billing* needs an `InvoiceRequest` (its language). We implement an **ACL** in the Billing context to translate and guard against upstream changes.

```java
// --- Upstream event (Published Language from Sales) ---
public record SalesOrderPlaced(
    String eventId,
    String orderId,
    String customerId,
    String currency,                // e.g., "EUR"
    List<SalesOrderLine> lines,     // price in minor units
    long placedAtEpochMs,
    int schemaVersion               // event versioning
) {}

public record SalesOrderLine(
    String sku,
    int quantity,
    long unitPriceMinor
) {}
```

```java
// --- Downstream (Billing) command model ---
public record InvoiceRequest(
    String invoiceId,
    String debtorId,
    String orderRef,
    String currency,
    long netAmountMinor,
    List<InvoiceItem> items
) {}

public record InvoiceItem(
    String sku,
    int quantity,
    long lineAmountMinor
) {}
```

```java
// --- ACL: translator + invariants + compatibility checks ---
import java.util.*;
import java.util.stream.Collectors;

public final class SalesToBillingAcl {

    // Accept only known event versions; upcast or reject unknowns.
    public static InvoiceRequest toInvoice(SalesOrderPlaced ev) {
        if (ev == null) throw new IllegalArgumentException("event null");
        if (ev.schemaVersion() < 1 || ev.schemaVersion() > 2) {
            throw new UnsupportedOperationException("Unsupported SalesOrderPlaced version: " + ev.schemaVersion());
        }

        String invoiceId = UUID.randomUUID().toString();
        long net = ev.lines().stream()
                .mapToLong(l -> Math.multiplyExact(l.quantity(), l.unitPriceMinor()))
                .sum();

        // Example invariant: currency must be ISO 4217 and lines non-empty
        if (ev.currency() == null || ev.currency().length() != 3) {
            throw new IllegalArgumentException("invalid currency");
        }
        if (ev.lines() == null || ev.lines().isEmpty()) {
            throw new IllegalArgumentException("empty order lines");
        }

        List<InvoiceItem> items = ev.lines().stream()
                .map(l -> new InvoiceItem(l.sku(), l.quantity(),
                        Math.multiplyExact(l.quantity(), l.unitPriceMinor())))
                .collect(Collectors.toList());

        return new InvoiceRequest(
                invoiceId,
                ev.customerId(),         // Sales.CustomerRef -> Billing.Debtor
                ev.orderId(),
                ev.currency(),
                net,
                items
        );
    }
}
```

```java
// --- Billing application service using the ACL ---
public interface InvoicingPort {
    void createInvoice(InvoiceRequest request);
}

public final class InvoicingService {
    private final InvoicingPort port;
    public InvoicingService(InvoicingPort port) { this.port = port; }

    public void onSalesOrderPlaced(SalesOrderPlaced ev) {
        // Translation is localized here; Billing model remains pure.
        InvoiceRequest req = SalesToBillingAcl.toInvoice(ev);
        port.createInvoice(req);
    }
}
```

```java
// --- Adapter for persistence / side effects (Billing's infrastructure) ---
public final class InMemoryInvoicingAdapter implements InvoicingPort {
    private final Map<String, InvoiceRequest> store = new HashMap<>();
    @Override
    public void createInvoice(InvoiceRequest request) {
        if (store.containsKey(request.invoiceId()))
            throw new IllegalStateException("duplicate invoice");
        store.put(request.invoiceId(), request);
        // In real code: persist, publish InvoiceCreated, etc.
    }
}
```

```java
// --- Minimal driver showing the mapping in action ---
import java.util.List;

public class Demo {
    public static void main(String[] args) {
        var service = new InvoicingService(new InMemoryInvoicingAdapter());

        var ev = new SalesOrderPlaced(
                "evt-1", "ORD-123", "CUST-9", "EUR",
                List.of(new SalesOrderLine("SKU-1", 2, 1999),
                        new SalesOrderLine("SKU-2", 1, 4999)),
                System.currentTimeMillis(), 1);

        service.onSalesOrderPlaced(ev);
        System.out.println("Invoice created from order " + ev.orderId());
    }
}
```

**Notes on the sample**

-   The **ACL** insulates Billing from Sales schema changes and enforces Billing invariants.
    
-   If Sales evolves (`schemaVersion=2`), the ACL becomes the *upcaster* or rejects with clear errors.
    
-   **Published Language** is the event (`SalesOrderPlaced`), independent of Billing’s internal model.
    
-   Replace `InMemoryInvoicingAdapter` with a real port (DB + outbox/event publication).
    

---

## Known Uses

-   **eCommerce:** Sales, Billing, Fulfillment, Catalog each with distinct models; explicit context maps with ACLs around Catalog and Payments.
    
-   **Financial services:** Risk, Pricing, Trading, and Settlements contexts with **Published Language** events and strict ACLs for regulatory boundaries.
    
-   **Mobility/Logistics:** Dispatch vs. Driver vs. Billing contexts; Conformist relationship for telemetry, ACL for pricing.
    
-   **Healthcare:** EMR vs. Billing vs. Scheduling with Shared Kernel for patient identifiers and Published Language for clinical events.
    

## Related Patterns

-   **Anti-Corruption Layer (ACL):** The concrete translation mechanism for protecting your model.
    
-   **Published Language / Open Host Service:** Stable, documented contracts between contexts.
    
-   **Customer–Supplier / Conformist / Shared Kernel:** Relationship types used in a context map.
    
-   **Event Sourcing & CQRS:** Often used within a context; mapping connects them across contexts.
    
-   **API Gateway / BFF:** Integration at the edge; context mapping governs *domain* boundaries behind the edge.

