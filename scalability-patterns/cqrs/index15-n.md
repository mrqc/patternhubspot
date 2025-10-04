# CQRS — Scalability Pattern

## Pattern Name and Classification

**Name:** Command Query Responsibility Segregation (CQRS)  
**Classification:** Scalability / Performance / Data Architecture (Workload Partitioning & Read Optimisation)

---

## Intent

Separate **writes (commands)** from **reads (queries)**—often onto different code paths and data stores—so that each side can be **designed, scaled, and optimized independently** (e.g., transactional consistency on the write side, denormalized and highly scalable read models on the query side).

---

## Also Known As

-   Read/Write Segregation
    
-   Command–Query Split
    
-   Task-based UI (when paired with explicit commands)
    
-   Evented CQRS (when combined with events)
    

---

## Motivation (Forces)

-   **Asymmetric traffic:** Production systems commonly have **many more reads than writes**.
    
-   **Conflicting optimizations:** OLTP schemas favor **normalized, consistent** updates; read paths want **denormalized, indexed** views.
    
-   **Hot queries:** Reporting/search/aggregations need different storage (columnar, search engines) than the transactional store.
    
-   **Scalability & cost:** Reads can be scaled horizontally via replicas/caches/projections without impacting write latency.
    
-   **Evolution:** Read models can change frequently (new views) without risky migrations on the write model.
    
-   **Autonomy:** Teams can own read models fit-for-purpose while sharing a stable write model contract.
    

---

## Applicability

Use CQRS when:

-   Read load is **much higher** than write load, or read queries are **complex/expensive**.
    
-   The domain model for **updates** differs significantly from the **query** needs.
    
-   You want to serve **multiple read shapes** (e.g., full-text search + dashboards + mobile DTOs).
    
-   You can tolerate **eventual consistency** between writes and read models, or you can keep **strong consistency** for a subset of flows with same-store reads.
    

Avoid or scope carefully when:

-   The system is **small/simple**; split adds complexity with little benefit.
    
-   You require **strict read-after-write** across all readers and can’t design around it.
    
-   Operational maturity for **messaging, projections, and backfills** is lacking.
    

---

## Structure

-   **Command Side:** Validates intent, enforces invariants, performs state changes in the **write model** (OLTP DB).
    
-   **Query Side:** Serves requests from **read models** (caches, replicas, denormalized tables, search indexes).
    
-   **Events / Change Feed:** (Optional but common) Publish domain or change events to **projectors** that update read models.
    
-   **Projectors / Materializers:** Consume events/CDC and (re)build optimized read views.
    
-   **API Layer:** Exposes separate endpoints/handlers for commands and queries; can scale independently.
    

---

## Participants

-   **Command Handler:** Validates commands, loads aggregates, persists changes atomically.
    
-   **Write Store:** Transactional database (RDBMS/NoSQL) as the source of truth.
    
-   **Event Publisher / Outbox:** Ensures reliable emission of change notifications/events.
    
-   **Projector:** Transforms changes into read models (tables, caches, indexes).
    
-   **Read Store(s):** Optimized for query patterns (PostgreSQL read schema, Elasticsearch, Redis).
    
-   **Query Handler:** Executes queries against read stores, returns DTOs.
    
-   **Backfill/Rebuilder:** Recomputes read models from history (events/CDC/snapshots).
    

---

## Collaboration

1.  Client sends a **command** → Command Handler loads aggregate from the **write store**, validates invariants, persists changes.
    
2.  The same transaction writes to an **outbox** (or a CDC stream emits a change).
    
3.  A **projector** reads the outbox/CDC and **updates read models** accordingly.
    
4.  Clients issue **queries** to the **query side**; responses come from read models.
    
5.  On schema/view changes, **rebuilders** backfill read models from events/history without touching the write model.
    

---

## Consequences

**Benefits**

-   **Scale reads cheaply** (denormalized tables, caches, replicas) without impacting writes.
    
-   **Performance:** Queries tailored to use-cases; lower latency and cost.
    
-   **Flexibility:** Add new read views without risky write-model migrations.
    
-   **Isolation:** Write invariants remain tight and transactional.
    

**Liabilities**

-   **Eventual consistency**: readers may see stale data for a short period.
    
-   **Operational complexity:** events/outbox, projectors, backfills, monitoring.
    
-   **Dual models:** Keep DTOs and aggregate models in sync logically.
    
-   **Error handling:** Projection failures/poison messages must be managed (DLQ, retries).
    

---

## Implementation

### Key Decisions

-   **Change propagation:** Transactional Outbox vs. CDC vs. synchronous read refresh.
    
-   **Consistency envelope:** Where do you require **read-after-write**? For those flows, query the write store or use a local cache/“fast read” path.
    
-   **Read model design:** Denormalize for exact queries; prefer **append-only** projections for auditability and easy rebuilds.
    
-   **Idempotence:** Projectors must be **idempotent**; use natural keys and upserts.
    
-   **Backfill strategy:** Ability to **replay** from events/CDC to rebuild read models (snapshots + replays).
    
-   **Versioning:** Version events and read schemas; allow side-by-side projections during migration.
    

### Anti-Patterns

-   Single DB table used for both complex queries and transactional updates with many ad-hoc indexes → write contention.
    
-   Projectors that are **not idempotent** → duplicates on retries.
    
-   Tight coupling where queries depend on **write-side joins** again (negates benefits).
    
-   No monitoring for **projection lag** and **DLQ volume**.
    

---

## Sample Code (Java, Spring Boot)

*CQRS with a transactional outbox, a projector updating a denormalized read table, and separate query handler.*

```java
// build.gradle (snip)
// implementation 'org.springframework.boot:spring-boot-starter-web'
// implementation 'org.springframework.boot:spring-boot-starter-data-jdbc'
// implementation 'org.springframework:spring-tx'
// runtimeOnly 'org.postgresql:postgresql'
```

### 1) Write Side: Aggregate + Command Handler + Outbox

```java
package com.example.cqrs.command;

import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.util.Map;
import java.util.UUID;

@Service
public class CustomerCommandService {

  private final NamedParameterJdbcTemplate jdbc;

  public CustomerCommandService(NamedParameterJdbcTemplate jdbc) {
    this.jdbc = jdbc;
  }

  @Transactional
  public UUID registerCustomer(RegisterCustomer cmd) {
    // 1) enforce invariants (simplified)
    if (cmd.email() == null || !cmd.email().contains("@"))
      throw new IllegalArgumentException("invalid email");

    // 2) persist write model (source of truth)
    UUID id = UUID.randomUUID();
    jdbc.update("""
      insert into customer (id, name, email, created_at)
      values (:id, :name, :email, :ts)
    """, Map.of("id", id, "name", cmd.name(), "email", cmd.email(), "ts", OffsetDateTime.now()));

    // 3) write to OUTBOX in the SAME TX (transactional outbox)
    String payload = """
      {"eventType":"CustomerRegistered","id":"%s","name":"%s","email":"%s"}
      """.formatted(id, escape(cmd.name()), escape(cmd.email()));
    jdbc.update("""
      insert into outbox (id, aggregate_type, aggregate_id, event_type, payload, created_at)
      values (:oid, 'Customer', :aid, 'CustomerRegistered', :payload, :ts)
    """, Map.of("oid", UUID.randomUUID(), "aid", id, "payload", payload, "ts", OffsetDateTime.now()));

    return id;
  }

  private static String escape(String s) { return s.replace("\"","\\\""); }

  public record RegisterCustomer(String name, String email) {}
}
```

**Schema (write + outbox + read model):**

```sql
-- write model
create table if not exists customer (
  id uuid primary key,
  name text not null,
  email text not null unique,
  created_at timestamptz not null
);

-- transactional outbox (poll-based emitter)
create table if not exists outbox (
  id uuid primary key,
  aggregate_type text not null,
  aggregate_id uuid not null,
  event_type text not null,
  payload jsonb not null,
  created_at timestamptz not null,
  published boolean not null default false
);
create index on outbox (published, created_at);

-- read model (denormalized)
create table if not exists customer_view (
  id uuid primary key,
  name text not null,
  email text not null,
  registered_at timestamptz not null
);
```

### 2) Publisher: Poll Outbox → Publish to a Queue (or Hand to Projector)

*(In small systems you can skip the external queue and have the projector read the outbox directly.)*

```java
package com.example.cqrs.outbox;

import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;
import java.util.UUID;

@Component
public class OutboxPublisher {

  private final NamedParameterJdbcTemplate jdbc;
  private final SimpleBus bus;

  public OutboxPublisher(NamedParameterJdbcTemplate jdbc, SimpleBus bus) {
    this.jdbc = jdbc;
    this.bus = bus;
  }

  @Scheduled(fixedDelay = 300) // 300 ms poll
  public void publish() {
    List<Map<String,Object>> rows = jdbc.getJdbcTemplate().queryForList("""
      select id, event_type, payload::text as payload
      from outbox where published=false
      order by created_at asc
      limit 100
    """);
    for (Map<String,Object> r : rows) {
      UUID id = (UUID) r.get("id");
      String type = (String) r.get("event_type");
      String payload = (String) r.get("payload");
      try {
        bus.send(type, payload); // push to broker; here it's in-process
        jdbc.update("update outbox set published=true where id=:id", Map.of("id", id));
      } catch (Exception e) {
        // leave as unpublished for retry
      }
    }
  }
}

/** Extremely simplified event bus abstraction. Replace with Kafka/Rabbit/SQS. */
@Component
class SimpleBus {
  private final CustomerProjector projector;
  SimpleBus(CustomerProjector projector) { this.projector = projector; }
  public void send(String type, String payload) {
    projector.onEvent(type, payload);
  }
}
```

### 3) Projector: Update Read Model (Idempotent Upsert)

```java
package com.example.cqrs.read;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Component;

import java.time.OffsetDateTime;
import java.util.Map;
import java.util.UUID;

@Component
public class CustomerProjector {
  private final NamedParameterJdbcTemplate jdbc;
  private final ObjectMapper om = new ObjectMapper();

  public CustomerProjector(NamedParameterJdbcTemplate jdbc) {
    this.jdbc = jdbc;
  }

  public void onEvent(String eventType, String payload) {
    try {
      JsonNode j = om.readTree(payload);
      if ("CustomerRegistered".equals(eventType)) {
        UUID id = UUID.fromString(j.get("id").asText());
        String name = j.get("name").asText();
        String email = j.get("email").asText();
        jdbc.update("""
          insert into customer_view (id, name, email, registered_at)
          values (:id, :name, :email, :ts)
          on conflict (id) do update set
            name = excluded.name,
            email = excluded.email
        """, Map.of("id", id, "name", name, "email", email, "ts", OffsetDateTime.now()));
      }
      // other events update other read models
    } catch (Exception e) {
      // send to DLQ/log and retry later
      throw new RuntimeException(e);
    }
  }
}
```

### 4) Query Side: Separate Controller/Repository

```java
package com.example.cqrs.query;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/customers")
public class CustomerQueryController {

  private final JdbcTemplate jdbc;

  public CustomerQueryController(JdbcTemplate jdbc) {
    this.jdbc = jdbc;
  }

  @GetMapping("/{id}")
  public CustomerView get(@PathVariable UUID id) {
    return jdbc.query("""
        select id, name, email, registered_at from customer_view where id=?
      """, rs -> rs.next()
        ? new CustomerView(
            UUID.fromString(rs.getString("id")),
            rs.getString("name"),
            rs.getString("email"),
            rs.getString("registered_at"))
        : null, id);
  }

  @GetMapping
  public List<CustomerView> list() {
    return jdbc.query("""
      select id, name, email, registered_at from customer_view order by registered_at desc limit 100
    """, (rs, i) -> new CustomerView(
        UUID.fromString(rs.getString("id")),
        rs.getString("name"),
        rs.getString("email"),
        rs.getString("registered_at")));
  }

  public record CustomerView(UUID id, String name, String email, String registeredAt) {}
}
```

### 5) Command API (separate from Query API)

```java
package com.example.cqrs.command;

import org.springframework.web.bind.annotation.*;

import java.util.Map;
import java.util.UUID;

@RestController
@RequestMapping("/api/commands/customers")
public class CustomerCommandController {

  private final CustomerCommandService service;

  public CustomerCommandController(CustomerCommandService service) {
    this.service = service;
  }

  @PostMapping("/register")
  public Map<String,Object> register(@RequestBody CustomerCommandService.RegisterCustomer cmd) {
    UUID id = service.registerCustomer(cmd);
    return Map.of("id", id.toString(), "status", "accepted");
  }
}
```

**Properties of the sample:**

-   Writes are **transactional** in the write store and the **outbox**.
    
-   Projector is **idempotent** (upsert).
    
-   Queries hit a **denormalized** table for fast responses.
    
-   Eventual consistency window equals **outbox → projector lag**; monitor and bound it.
    

---

## Known Uses

-   **E-commerce**: orders/payments as write models; product and order dashboards as read models.
    
-   **Banking/ledger**: transactional writes with read models for statements and analytics.
    
-   **Social platforms**: timelines/feeds/materialized views derived from event streams.
    
-   **IoT/telemetry**: command plane for device control; read plane for time-series/aggregations.
    

---

## Related Patterns

-   **Transactional Outbox**: reliable change publication from the write DB.
    
-   **Event Sourcing**: store events as the write model; CQRS read models project from the event log.
    
-   **Materialized View / Read Model**: denormalized stores serving queries.
    
-   **Cache Aside**: cache read models with TTL/jitter; protect against stampedes.
    
-   **Idempotent Receiver**: make projectors safe against duplicate deliveries.
    
-   **Saga / Process Manager**: coordinate multi-aggregate workflows on the command side.
    

---

## Implementation Checklist

-   Define **separate APIs** for commands vs queries; decouple deployment and scaling.
    
-   Choose **propagation** (Outbox/CDC/Event Bus) and implement **idempotent** projectors.
    
-   Design **read models** for exact queries; denormalize and index accordingly.
    
-   Establish **consistency policy**: which flows need read-after-write? Route them appropriately.
    
-   Provide **rebuild** tooling (replay outbox/events) and **backfill** pipelines.
    
-   Monitor **projection lag**, **DLQ**, **throughput**, and **read SLOs**.
    
-   Version events and read schemas; support side-by-side projections during migrations.
    
-   Load-test both planes independently; plan capacity and failure modes (bus down, projector down).

