# Context Map — Domain-Driven Design Pattern

---

## Pattern Name and Classification

-   **Name:** Context Map

-   **Category:** DDD / Strategic Design / Integration Governance

-   **Level:** System-of-systems documentation + contract pattern


---

## Intent

Create a **single explicit artifact** that captures all **bounded contexts** in a system and the **relationships between them** (integration styles, power dynamics, contracts, translation points), so teams share the same map of the terrain and can **coordinate evolution** safely.

---

## Also Known As

-   Context Relationship Map

-   System Ubiquitous Language Map

-   Integration Topology


---

## Motivation (Forces)

-   Large systems evolve many bounded contexts with **different ubiquitous languages**.

-   Without an explicit map, teams integrate ad-hoc, causing **model leakage**, **hidden coupling**, and **coordination failures**.

-   A Context Map makes **relationships, ownership, and contracts** visible and testable.


**Forces / Trade-offs**

-   **Pros:** shared understanding, clear ownership, explicit integration style, faster onboarding, risk visibility.

-   **Cons:** needs discipline to **keep current**; can devolve into stale documentation; may expose organizational tensions (useful but uncomfortable).


---

## Applicability

Use a Context Map when:

-   More than one bounded context exists (microservices or modular monolith).

-   You need to govern **inter-team integrations** and **domain language boundaries**.

-   You’re planning a migration (strangler, carve-outs) or aligning a program increment.


Avoid over-engineering when:

-   There is effectively **one context** and no near-term split.

-   The map can’t be maintained (no single owner, no CI checks) — start lightweight.


---

## Structure

A Context Map lists:

1.  **Bounded Contexts** (name, purpose, team, language, data).

2.  **Relationships** between pairs/groups of contexts, chosen from a **Context Map vocabulary**, e.g.:

    -   **Conformist** (consumer adopts provider’s model)

    -   **Anti-Corruption Layer (ACL)** (consumer shields model)

    -   **Customer–Supplier** (power dynamic + expectations)

    -   **Partnership** (peer teams evolve together)

    -   **Shared Kernel** (carefully shared subset)

    -   **Published Language / Open Host Service** (provider publishes contracts)

    -   **Separate Ways** (no direct integration)

3.  **Contracts & Interfaces** (API specs, schemas, events).

4.  **Operational agreements** (SLAs, versioning, deprecation timelines).


```scss
[Sales] --(Published Language + Customer–Supplier)--> [Billing]
   │                          ▲
   ├──(ACL)───────────────────┘
   └──(Partnership)↔[Catalog]
[Identity] ←(Conformist)— [Notifications]
```

---

## Participants

-   **Context Owners (Teams)** — accountable for a context and its contracts.

-   **Map Steward** — curates/merges changes; keeps it versioned.

-   **Integrators / Architects** — define relationship types and contract tests.

-   **Tooling** — schema registries, contract-test pipelines, doc generators.


---

## Collaboration

-   Works with **Bounded Context** (defines the nodes).

-   Drives decisions between **Conformist** vs **ACL** and **Customer–Supplier** vs **Partnership**.

-   Pairs with **Published Language / Open Host Service** for provider contracts.

-   Feeds **Sagas/Process Managers** that span contexts.

-   Integrates with **GitOps**: map and contracts live in version control.


---

## Consequences

**Benefits**

-   Explicit **integration topology** and power dynamics.

-   Reduces accidental coupling/model leakage.

-   Enables **contract-first development** and consumer–provider testing.

-   Aligns organizational boundaries with technical ones.


**Liabilities**

-   Needs **continuous upkeep**; otherwise becomes misleading.

-   Can oversimplify nuanced relationships if treated as static.

-   Political friction when exposing real ownership/gaps.


Mitigations:

-   Store map **as code** (YAML/JSON + CI checks).

-   Connect to **contract tests** and schema registries; fail builds on drift.

-   Review at every PI/quarter; treat changes as ADRs.


---

## Implementation

1.  **Inventory contexts**: name, purpose, team, language, data, uptime SLO.

2.  **Identify relationships**: for each integration, select a context-map type (ACL, Conformist, etc.) and document **directionality** and **power**.

3.  **Attach contracts**: link OpenAPI/Avro/gRPC schemas, event types, versioning policy.

4.  **Decide reliability pattern**: outbox, idempotency keys, retries, SLAs.

5.  **Automate**: keep the map in Git; generate a diagram from machine-readable spec; validate with contract tests.

6.  **Govern**: nominate a steward; changes go through PR + lightweight ADR.

7.  **Evolve**: when relationships change (e.g., Conformist → ACL), record the transition on the map and plan migration.


---

## Sample Code (Java) — Minimal Context Map “DSL” + Validation

> A tiny in-memory model to **declare bounded contexts and relationships**, validate common mistakes, and (optionally) render to JSON/YAML for your “Architects Pocket Guide”.

```java
// Context Map Vocabulary
enum RelationType {
    CONFORMIST,            // consumer adopts provider model
    ANTI_CORRUPTION_LAYER, // consumer shields model with ACL
    CUSTOMER_SUPPLIER,     // provider serves consumer expectations
    PARTNERSHIP,           // peers evolve together
    SHARED_KERNEL,         // shared subset of model/code
    PUBLISHED_LANGUAGE,    // provider publishes schemas/events
    SEPARATE_WAYS          // no integration
}

final class BoundedContext {
    final String name;
    final String team;
    final String language; // short description of its ubiquitous language
    BoundedContext(String name, String team, String language) {
        if (name == null || name.isBlank()) throw new IllegalArgumentException("name");
        this.name = name; this.team = team; this.language = language;
    }
}

final class Relationship {
    final String from;            // source context
    final String to;              // target context
    final RelationType type;
    final String contractRef;     // link to OpenAPI/Avro/etc (optional)
    final String notes;           // free-form policy/SLAs

    Relationship(String from, String to, RelationType type, String contractRef, String notes) {
        if (from.equals(to)) throw new IllegalArgumentException("self relation not allowed");
        this.from = from; this.to = to; this.type = type;
        this.contractRef = contractRef; this.notes = notes;
    }
}

import java.util.*;
final class ContextMap {
    private final Map<String, BoundedContext> contexts = new LinkedHashMap<>();
    private final List<Relationship> relations = new ArrayList<>();

    public ContextMap addContext(BoundedContext c) {
        if (contexts.containsKey(c.name)) throw new IllegalArgumentException("duplicate context: " + c.name);
        contexts.put(c.name, c);
        return this;
    }

    public ContextMap relate(String from, String to, RelationType type, String contractRef, String notes) {
        if (!contexts.containsKey(from) || !contexts.containsKey(to))
            throw new IllegalArgumentException("unknown context in relation " + from + "->" + to);
        relations.add(new Relationship(from, to, type, contractRef, notes));
        return this;
    }

    // Simple validations illustrating helpful governance checks
    public List<String> validate() {
        List<String> problems = new ArrayList<>();
        // 1) SHARED_KERNEL should be symmetric
        for (Relationship r : relations) {
            if (r.type == RelationType.SHARED_KERNEL) {
                boolean symmetric = relations.stream().anyMatch(x ->
                    x.type == RelationType.SHARED_KERNEL && x.from.equals(r.to) && x.to.equals(r.from));
                if (!symmetric) problems.add("Shared Kernel must be symmetric between " + r.from + " and " + r.to);
            }
        }
        // 2) CONFORMIST + ACL between same pair is suspicious
        for (Relationship a : relations) {
            for (Relationship b : relations) {
                if (!a.equals(b) && a.from.equals(b.from) && a.to.equals(b.to)) {
                    if ((a.type == RelationType.CONFORMIST && b.type == RelationType.ANTI_CORRUPTION_LAYER) ||
                        (b.type == RelationType.CONFORMIST && a.type == RelationType.ANTI_CORRUPTION_LAYER)) {
                        problems.add("Conflicting relation types (Conformist vs ACL) for " + a.from + " -> " + a.to);
                    }
                }
            }
        }
        // 3) CUSTOMER_SUPPLIER should have a published contract
        for (Relationship r : relations) {
            if (r.type == RelationType.CUSTOMER_SUPPLIER && (r.contractRef == null || r.contractRef.isBlank())) {
                problems.add("Customer–Supplier " + r.from + "->" + r.to + " requires contractRef");
            }
        }
        return problems;
    }

    // Minimal export (pseudo-JSON) for demonstration
    public String toJson() {
        StringBuilder sb = new StringBuilder("{\n  \"contexts\": [\n");
        var it = contexts.values().iterator();
        while (it.hasNext()) {
            var c = it.next();
            sb.append("    {\"name\":\"").append(c.name).append("\",\"team\":\"").append(c.team)
              .append("\",\"language\":\"").append(c.language).append("\"}");
            if (it.hasNext()) sb.append(","); sb.append("\n");
        }
        sb.append("  ],\n  \"relationships\": [\n");
        for (int i = 0; i < relations.size(); i++) {
            var r = relations.get(i);
            sb.append("    {\"from\":\"").append(r.from).append("\",\"to\":\"").append(r.to)
              .append("\",\"type\":\"").append(r.type).append("\",\"contractRef\":\"")
              .append(r.contractRef == null ? "" : r.contractRef).append("\",\"notes\":\"")
              .append(r.notes == null ? "" : r.notes.replace("\"","\\\"")).append("\"}");
            if (i < relations.size()-1) sb.append(",");
            sb.append("\n");
        }
        sb.append("  ]\n}");
        return sb.toString();
    }
}
```

```java
// Example usage (e.g., a unit test or a CLI command)
public class ContextMapExample {
    public static void main(String[] args) {
        ContextMap map = new ContextMap()
            .addContext(new BoundedContext("Sales", "Team Aurora", "orders, line items, confirmation"))
            .addContext(new BoundedContext("Billing", "Team Ledger", "invoices, charges"))
            .addContext(new BoundedContext("Catalog", "Team Atlas", "products, SKUs, pricing"))
            .addContext(new BoundedContext("Identity", "Team Keys", "users, roles, tokens"))

            // Relationships
            .relate("Sales", "Billing", RelationType.CUSTOMER_SUPPLIER,
                    "openapi://billing/v1/invoice.yaml", "SLA P99<200ms; deprecations 90 days")
            .relate("Billing", "Sales", RelationType.PUBLISHED_LANGUAGE,
                    "event://billing.v1.invoice-issued", "Avro schema v1; schema registry")
            .relate("Sales", "Catalog", RelationType.PARTNERSHIP, null, "Joint release for price rules")
            .relate("Sales", "Identity", RelationType.ANTI_CORRUPTION_LAYER,
                    null, "Translate claims to domain roles")
            .relate("Notifications", "Identity", RelationType.CONFORMIST, null, "Uses provider tokens") // if Notifications existed
            .relate("Catalog", "Sales", RelationType.SHARED_KERNEL, "git://shared-kernel/pricing", "Shared Price VO")
            .relate("Sales", "Catalog", RelationType.SHARED_KERNEL, "git://shared-kernel/pricing", "Symmetric");

        var problems = map.validate();
        if (!problems.isEmpty()) {
            System.out.println("Validation issues:");
            problems.forEach(p -> System.out.println(" - " + p));
        } else {
            System.out.println(map.toJson());
        }
    }
}
```

**Notes**

-   The tiny “DSL” demonstrates **relationship vocabulary**, **directionality**, and **validation** (e.g., Shared Kernel must be symmetric; Conformist vs ACL conflict).

-   In your app, back this with YAML/JSON and generate PlantUML/Graphviz diagrams in CI.


---

## Known Uses

-   **E-commerce platforms** mapping `Catalog`, `Pricing`, `Ordering`, `Billing`, `Fulfillment`, `Identity` with mixed **ACL / Conformist / Published Language** relationships.

-   **Banking** splitting `Risk`, `Accounts`, `Payments`, `Ledger` with strict ACLs to core ledger.

-   **Automotive retail** separating `Leads`, `Agreements`, `Market Areas`, `Inventory` with ACLs around legacy DMS/ERP.


---

## Related Patterns

-   **Bounded Context** — the nodes on the map.

-   **Anti-Corruption Layer / Conformist / Customer–Supplier / Partnership / Shared Kernel** — the relationship types on edges.

-   **Published Language / Open Host Service** — provider contract styles.

-   **Saga / Process Manager** — spans steps across contexts.

-   **Contextual Cohesion / Modular Monolith** — internal enforcement of boundaries.
