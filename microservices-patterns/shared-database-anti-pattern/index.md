# Shared Database Antipattern — Microservice Pattern

## Pattern Name and Classification

-   **Name:** Shared Database Antipattern
    
-   **Classification:** Architectural **anti-pattern** for Microservices (data coupling / integration-by-database)
    

## Intent

Describe why letting **multiple services read/write the same database (and schema)** is tempting but harmful: it **re-couples** services, forces **lockstep deployments**, and undermines autonomy, scalability, and reliability. Provide guidance to **detect, contain, and migrate away** from it.

## Also Known As

-   Integration Database (anti-pattern)
    
-   Shared Schema / Cross-Service DB Access
    
-   Database as an Integration Layer
    

## Motivation (Forces)

-   **Short-term speed:** “We already have the data, just join it.”
    
-   **Reporting pressure:** Ad-hoc cross-domain SQL is easy in one DB.
    
-   **Strong consistency desire:** One ACID transaction across domains feels safe.
    
-   **Operational habit:** Existing DBA processes, single backup/HA strategy.
    
-   **Cost & tooling bias:** One cluster to run, one set of utilities.
    

**Counterforces (why it bites later)**

-   **Tight coupling:** Any schema change breaks others; deploys must be coordinated.
    
-   **Hidden dependencies:** Views, triggers, and stored procedures create invisible runtime coupling.
    
-   **Ownership ambiguity:** Who owns the table and its SLAs?
    
-   **Security & blast radius:** One compromised credential accesses everything.
    
-   **Scaling contention:** Mixed workloads fight for locks, I/O, buffers.
    
-   **Innovation tax:** Teams can’t choose the best-fit datastore (no polyglot persistence).
    

## Applicability

-   **Common in migrations** from a monolith to services when the monolith’s DB lingers.
    
-   **Sometimes unavoidable temporarily** (e.g., legacy COTS systems). If you must do it, treat as **containment**, not a target state.
    

**Avoid when**

-   You want **independent deployability**, **bounded contexts**, and **team autonomy**—i.e., most microservice programs.
    

## Structure

```pgsql
┌──────────────────────┐
Service A  ───────▶│                      │◀───────  Service B
(Orders)           │   Shared RDBMS/Schema│
 - joins billing_* │   tables, views, SPs │  joins orders_*
 - writes invoice  │                      │  triggers on orders_*
                   └──────────────────────┘
        ▲                 ▲        ▲
        │                 │        │
   Lockstep deploys  Hidden coupling  Wide blast radius
```

## Participants

-   **Multiple Services** (Orders, Billing, Inventory, …)
    
-   **Shared RDBMS** (single schema or multiple with cross-grants)
    
-   **DB-Level Integrations** (views, foreign keys across domains, triggers, SPs)
    
-   **Operators/DBAs** (own backups/patching but not domain semantics)
    

## Collaboration

1.  Services **register** the same JDBC URL/credentials.
    
2.  Reads/writes and **cross-service joins** occur directly.
    
3.  One team changes a column/constraint → others **break**.
    
4.  Incidents propagate through the shared DB (lock contention, hotspot tables).
    
5.  Deployments require **coordination** and lengthy freezes.
    

## Consequences

**Benefits (short-term)**

-   Fast to integrate; no messaging infra needed.
    
-   Simpler **ad-hoc reporting** in one place.
    
-   “One transaction” across domains (illusory safety).
    

**Liabilities (dominant long-term)**

-   **Coupling & lockstep deploys** → reduced throughput of change.
    
-   **Distributed Monolith:** services in name only.
    
-   **Security risk:** broad privileges, difficult least-privilege.
    
-   **Performance pathologies:** cross-domain FKs/joins, long transactions, deadlocks.
    
-   **Impossible refactors:** can’t evolve schemas independently.
    
-   **Regulatory risk:** unclear ownership of PII and retention rules.
    

## Implementation

**Don’t implement—avoid. If stuck temporarily, contain and migrate.**

### If you **must** operate in the antipattern (containment)

-   **Read-Only for others:** Only the owning service gets write; consumers read via **stable views** with **strict grants**.
    
-   **Publish interfaces:** Replace ad-hoc joins with **database views** that emulate APIs; deprecate direct table access.
    
-   **Kill cross-domain triggers/FKs:** Replace with **application-level invariants** and **asynchronous checks**.
    
-   **Observability:** Detect cross-schema queries, long transactions, lock waits.
    
-   **Access control:** Separate DB roles per service; rotate secrets; enable row-level security when possible.
    

### Migration to target state

1.  **Declare Data Ownership:** One service = system-of-record for a set of tables.
    
2.  **Introduce Outbox/CDC:** Emit domain events on every committed change.
    
3.  **Create Read Models/Indexes:** Build per-consumer projections (e.g., Elasticsearch, replicas, materialized views) instead of joins.
    
4.  **Extract Contracts:** Replace SQL coupling with **APIs/Async events**; add **consumer-driven contracts** and **SLOs**.
    
5.  **Strangler Strategy:** Gradually move consumers from tables to APIs/events; block table access; split schema.
    
6.  **Guardrails:** ArchUnit rules, SQL allow-lists, and DB grants that **forbid cross-domain access**.
    
7.  **Decommission:** After traffic moves, physically **split the database** (schema → DB), or at least cut grants.
    

---

## Sample Code (Java) — Detecting the Smell and a Safe Refactor

### A) **Antipattern Smell**: Cross-service join & write in the Orders service

> Single datasource pointing to a **shared** DB; Orders service queries **Billing** tables and writes invoices.

```java
// application.properties (anti-pattern)
spring.datasource.url=jdbc:postgresql://shared-db:5432/prod
spring.datasource.username=shared_app
spring.datasource.password=verybad
spring.jpa.hibernate.ddl-auto=none
```

```java
// AntiPatternRepository.java (Orders service reaching into Billing)
package antipattern;

import org.springframework.data.jpa.repository.*;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

@Repository
public interface AntiPatternRepository extends JpaRepository<OrderEntity, java.util.UUID> {

  // CROSS-DOMAIN NATIVE JOIN: orders_order ↔ billing_invoice
  @Query(value = """
      select o.id as order_id, o.status as order_status, b.status as invoice_status
      from orders_order o
      join billing_invoice b on b.order_id = o.id
      where o.id = :id
      """, nativeQuery = true)
  Object findOrderWithInvoice(@Param("id") java.util.UUID id);
}
```

```java
// AntiPatternService.java (one transaction updates two domains)
package antipattern;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AntiPatternService {
  private final JdbcTemplate jdbc;

  public AntiPatternService(JdbcTemplate jdbc) { this.jdbc = jdbc; }

  @Transactional // looks safe, actually couples domains & causes deadlocks
  public void placeOrderAndCreateInvoice(java.util.UUID orderId, long amountCents) {
    jdbc.update("insert into orders_order(id,status,total_cents) values (?,?,?)",
        orderId, "CREATED", amountCents);

    // Cross-domain WRITE into Billing's table (!!)
    jdbc.update("insert into billing_invoice(id,order_id,status,amount_cents) values (?,?,?,?)",
        java.util.UUID.randomUUID(), orderId, "OPEN", amountCents);
  }
}
```

### B) **Refactor**: Split ownership + Outbox event → Billing API / projector

**Step 1 — Separate credentials and **forbid** cross-domain writes**

```properties
# orders-service application.properties (good)
spring.datasource.url=jdbc:postgresql://orders-db:5432/orders
spring.datasource.username=orders_service
spring.datasource.password=secret
# DB grants: orders_service has USAGE/SELECT/INSERT/UPDATE on orders_* ONLY
```

**Step 2 — Transactional Outbox in Orders**

```sql
-- orders db migration
create table if not exists outbox_event (
  id bigserial primary key,
  aggregate_type varchar(64) not null,
  aggregate_id uuid not null,
  event_type varchar(64) not null,
  payload jsonb not null,
  occurred_at timestamptz not null default now(),
  published boolean not null default false
);
```

```java
// OrderService.java (emit event; no billing table writes)
package refactor;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class OrderService {
  private final OrderRepo orders;
  private final OutboxRepo outbox;
  private final ObjectMapper json;

  public OrderService(OrderRepo orders, OutboxRepo outbox, ObjectMapper json) {
    this.orders = orders; this.outbox = outbox; this.json = json;
  }

  @Transactional
  public java.util.UUID place(java.util.UUID customerId, long totalCents) {
    var order = Order.create(customerId, totalCents);
    orders.save(order);

    // publish OrderPlaced event in SAME transaction
    try {
      var payload = json.writeValueAsString(java.util.Map.of(
          "orderId", order.getId().toString(),
          "customerId", customerId.toString(),
          "totalCents", totalCents));
      outbox.save(new OutboxEvent("Order", order.getId(), "OrderPlaced", payload));
    } catch (Exception e) { throw new RuntimeException(e); }

    return order.getId();
  }
}
```

**Step 3 — Asynchronous integration (choose one):**

**3a) Call Billing **API** (synchronous command boundary)**

```java
// BillingClient.java (Orders → Billing over HTTP; no DB reach-through)
package refactor;

import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.stereotype.Component;

@Component
public class BillingClient {
  private final WebClient http = WebClient.builder().build();

  public void createInvoice(java.util.UUID orderId, long amountCents) {
    http.post().uri("http://billing.svc.cluster.local:8080/invoices")
        .bodyValue(java.util.Map.of("orderId", orderId.toString(), "amountCents", amountCents))
        .retrieve().toBodilessEntity().block();
  }
}
```

**3b) Or publish to Kafka from Outbox (async)**  
*(publisher runs out-of-band; Billing subscribes and writes its own DB)*

```java
// OutboxPublisher.java
package refactor;

import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
public class OutboxPublisher {
  private final OutboxRepo repo;
  private final KafkaTemplate<String, String> kafka;

  public OutboxPublisher(OutboxRepo repo, KafkaTemplate<String, String> kafka) {
    this.repo = repo; this.kafka = kafka;
  }

  @Scheduled(fixedDelay = 500)
  public void pump() {
    var batch = repo.findTop100ByPublishedFalseOrderByIdAsc();
    for (var e : batch) {
      kafka.send("orders.placed.v1", e.getAggregateId().toString(), e.getPayload());
      e.setPublished(true);
      repo.save(e);
    }
  }
}
```

**Step 4 — Optional read model for queries that used to JOIN**

```sql
-- in a reporting/readonly DB (not Billing’s OLTP)
create materialized view order_invoice_view as
select o.id as order_id, o.status as order_status, i.status as invoice_status
from orders_snapshot o
left join billing_snapshot i on i.order_id = o.id;
```

*Built from CDC streams or ETL; **no cross-domain OLTP join** required.*

---

## Known Uses

-   Common **organizational smell** in early microservice migrations; widely cited as **Integration Database (anti-pattern)** in microservices literature.

-   Enterprises routinely move away from it using **Database per Service**, **Outbox/CDC**, and **read models/warehouses**.


## Related Patterns

-   **Database per Service** (target state for ownership and autonomy)

-   **Transactional Outbox & Change Data Capture** (reliable propagation)

-   **CQRS & Read Models** (serve cross-domain queries without joins)

-   **Saga / Compensating Transaction** (coordinate multi-service workflows)

-   **API Composition / BFF** (compose at the edge, not in the DB)

-   **Polyglot Persistence** (fit-for-purpose stores once decoupled)

-   **Strangler Fig** (incremental migration off the shared DB)
