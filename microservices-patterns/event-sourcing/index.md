# Event Sourcing — Microservice Pattern

## Pattern Name and Classification

-   **Name:** Event Sourcing
    
-   **Classification:** State Management & Persistence Pattern for Microservices / DDD
    

## Intent

Persist **all changes to application state as an ordered sequence of immutable domain events**. Reconstruct current state by **replaying** these events (optionally using **snapshots**), enabling perfect auditability, time travel, and reliable integration.

## Also Known As

-   Event Journal / Event Log
    
-   Append-Only Store
    
-   Event Stream Persistence
    

## Motivation (Forces)

-   **Auditability & Compliance:** Every change is recorded as a first-class fact.
    
-   **Rebuildability:** Corrupted projections/read models can be rebuilt by replaying events.
    
-   **Integration-Friendly:** Events are a natural source for **CDC**, **stream processing**, and **read model** generation.
    
-   **Temporal Queries:** “As of time T” becomes straightforward.
    
-   **Complex Aggregates:** Business invariants can be enforced in a single place (aggregate) with optimistic concurrency.
    

**Tensions**

-   **Querying Current State:** Requires replay/snapshots/projections.
    
-   **Schema Evolution:** Events are immutable; versioning and upcasting needed.
    
-   **Eventual Consistency:** Read models and other services catch up asynchronously.
    
-   **Operational Maturity:** Tooling, storage layout, and replay controls are essential.
    

## Applicability

Use when:

-   You need **full history**, reproducibility, and audit.
    
-   Your domain has **rich, evolving behavior** with complex invariants.
    
-   You plan for **CQRS** and multiple read models with differing query shapes.
    
-   Integrations benefit from **event streams** (e.g., analytics, ML features, notifications).
    

Avoid or de-prioritize when:

-   Domain is CRUD-simple; history is unnecessary and storage budget is tight.
    
-   Strict, synchronous multi-aggregate transactions are the norm (may still work with sagas, but complexity rises).
    
-   Team lacks operational capacity for event versioning, projections, and replay governance.
    

## Structure

-   **Aggregate:** Encapsulates invariants and decision logic; **does not** talk to the DB directly.
    
-   **Event Store:** Append-only persisted stream per aggregate (`Order-<uuid>`) or category (`Order`).
    
-   **Repository:** Loads aggregate by `replay(events)` (optionally from a **snapshot**) and **appends** new events with expected version.
    
-   **Projections / Read Models:** Subscribe to events and build query-optimized views (SQL/NoSQL/cache/search).
    
-   **Publisher (optional):** Forwards committed events to a broker (Kafka/Rabbit/River) for other services.
    

```pgsql
Command → [Aggregate] --emits--> [Uncommitted Events]
                ▲                        |
                |                        v (append with expected version)
            [Repository] <---load--- [Event Store] ---> [Projectors] → Read Models
```

## Participants

-   **Command Handler / Application Service**: Coordinates intents, loads aggregate, persists events.
    
-   **Aggregate Root**: Validates commands, emits domain events, applies them to its state.
    
-   **Domain Events**: Immutable facts with type, version, metadata, and timestamp.
    
-   **Event Store**: Durable append-only storage with **optimistic concurrency** (`expectedVersion`).
    
-   **Snapshot Store (optional)**: Stores periodic materialized state for faster loads.
    
-   **Projectors / Subscribers**: Build and maintain read models.
    
-   **Upcasters / Migrations**: Transform old event versions at read time.
    

## Collaboration

1.  Client sends a **command** (e.g., `PlaceOrder`).
    
2.  App service loads `Order` aggregate (from snapshot + tail events).
    
3.  Aggregate validates invariants and **emits one or more events** (e.g., `OrderPlaced`).
    
4.  Repository **appends** events with `expectedVersion = currentVersion` (fail → concurrency exception).
    
5.  Event store **persists** and optionally **publishes** to subscribers.
    
6.  Projectors update read models; other services react asynchronously.
    

## Consequences

**Benefits**

-   Complete history, audit, and **time travel**.
    
-   Easy to create **new read models** without changing write path.
    
-   Natural integration via event streams; **rebuild** read models at any time.
    
-   Encourages strong domain modeling and **explicit state transitions**.
    

**Liabilities**

-   More moving parts: store, projections, snapshots, upcasters, replay tooling.
    
-   **Event schema evolution** and versioning are unavoidable.
    
-   Repairs require **compensation events** (no destructive “fix in place”).
    
-   Debugging cross-aggregate flows may need **sagas** and **distributed tracing**.
    

## Implementation

1.  **Define Aggregates & Invariants**
    
    -   Identify aggregate boundaries (DDD) to keep transactions local.
        
2.  **Model Events First**
    
    -   Stable names, clear intent, minimal payload; include `eventVersion`, `occurredAt`, `aggregateId`, `sequence`.
        
3.  **Event Store Contract**
    
    -   `append(streamId, expectedVersion, List<Event>)`
        
    -   `readFrom(streamId, fromVersion)`
        
    -   Category queries (by type) for projecting.
        
4.  **Optimistic Concurrency**
    
    -   Fail fast on version mismatch → retry load/reapply or return conflict to caller.
        
5.  **Snapshots**
    
    -   Snapshot every *N* events or when load time exceeds threshold; store `(aggregateId, version, stateBlob)`.
        
6.  **Projections**
    
    -   **Idempotent**, **at-least-once** consumers; store **last processed position** per projector.
        
7.  **Event Versioning / Upcasting**
    
    -   Keep old events immutable; add new versions; supply **upcasters** or **polyglot deserializers**.
        
8.  **Publishing**
    
    -   If external subscribers exist, use **outbox** (same DB) or event store’s **commit hooks** to publish to a broker.
        
9.  **Governance & Ops**
    
    -   Replay controls (time window, filters), backfills, poison event handling, PII strategy (don’t store secrets).
        
10.  **Testing**
    

-   Given-When-Then specs at aggregate level: **given(events) when(command) then(expect events or error)**.
    

---

## Sample Code (Java, minimal dependencies)

> Illustrative, framework-light implementation with in-memory store; replace storage with Postgres/EventStoreDB/Kafka-backed store in production.

### 1) Domain Events

```java
// DomainEvent.java
package es.sample;

import java.time.Instant;
import java.util.UUID;

public interface DomainEvent {
  String type();             // e.g., "OrderPlaced"
  int version();             // schema version for this event type
  UUID aggregateId();
  long sequence();           // aggregate-local version (1..N)
  Instant occurredAt();
}
```

```java
// OrderEvents.java
package es.sample;

import java.time.Instant;
import java.util.UUID;

public sealed interface OrderEvent extends DomainEvent permits OrderPlaced, ItemAdded, OrderConfirmed {}

record OrderPlaced(UUID aggregateId, long sequence, Instant occurredAt, String customerId)
    implements OrderEvent {
  @Override public String type() { return "OrderPlaced"; }
  @Override public int version() { return 1; }
}

record ItemAdded(UUID aggregateId, long sequence, Instant occurredAt, String sku, int qty)
    implements OrderEvent {
  @Override public String type() { return "ItemAdded"; }
  @Override public int version() { return 1; }
}

record OrderConfirmed(UUID aggregateId, long sequence, Instant occurredAt)
    implements OrderEvent {
  @Override public String type() { return "OrderConfirmed"; }
  @Override public int version() { return 1; }
}
```

### 2) Aggregate

```java
// OrderAggregate.java
package es.sample;

import java.time.Instant;
import java.util.*;

public class OrderAggregate {

  public enum Status { NEW, CONFIRMED }
  private UUID id;
  private Status status = Status.NEW;
  private Map<String,Integer> items = new HashMap<>();
  private long version = 0; // last applied sequence

  public static OrderAggregate empty() { return new OrderAggregate(); }

  // Command handlers (return new events)
  public List<OrderEvent> place(UUID id, String customerId) {
    if (this.id != null) throw new IllegalStateException("order already exists");
    return List.of(new OrderPlaced(id, version + 1, Instant.now(), customerId));
  }

  public List<OrderEvent> addItem(String sku, int qty) {
    ensureExists();
    if (status == Status.CONFIRMED) throw new IllegalStateException("confirmed orders immutable");
    if (qty <= 0) throw new IllegalArgumentException("qty>0 required");
    return List.of(new ItemAdded(id, version + 1, Instant.now(), sku, qty));
  }

  public List<OrderEvent> confirm() {
    ensureExists();
    if (items.isEmpty()) throw new IllegalStateException("cannot confirm empty order");
    if (status == Status.CONFIRMED) return List.of(); // idempotent
    return List.of(new OrderConfirmed(id, version + 1, Instant.now()));
  }

  // Event appliers (pure state transition)
  public void apply(OrderEvent e) {
    switch (e) {
      case OrderPlaced ev -> this.id = ev.aggregateId();
      case ItemAdded ev -> this.items.merge(ev.sku(), ev.qty(), Integer::sum);
      case OrderConfirmed ev -> this.status = Status.CONFIRMED;
      default -> throw new IllegalArgumentException("unknown event: " + e);
    }
    this.version = e.sequence();
  }

  public long version() { return version; }
  public UUID id() { return id; }
  public Status status() { return status; }
  public Map<String,Integer> items() { return Map.copyOf(items); }

  private void ensureExists() { if (id == null) throw new IllegalStateException("order not created"); }
}
```

### 3) Event Store & Repository

```java
// EventStore.java
package es.sample;

import java.util.List;

public interface EventStore {
  List<DomainEvent> loadStream(String streamId);                   // full stream
  void appendToStream(String streamId, long expectedVersion, List<? extends DomainEvent> events);
}
```

```java
// InMemoryEventStore.java
package es.sample;

import java.util.*;

public class InMemoryEventStore implements EventStore {
  private final Map<String, List<DomainEvent>> store = new HashMap<>();

  @Override
  public synchronized List<DomainEvent> loadStream(String streamId) {
    return new ArrayList<>(store.getOrDefault(streamId, List.of()));
  }

  @Override
  public synchronized void appendToStream(String streamId, long expectedVersion, List<? extends DomainEvent> events) {
    var list = store.computeIfAbsent(streamId, k -> new ArrayList<>());
    long current = list.isEmpty() ? 0 : list.get(list.size()-1).sequence();
    if (current != expectedVersion) throw new ConcurrentModificationException("expected " + expectedVersion + " but was " + current);
    list.addAll(events);
  }
}
```

```java
// OrderRepository.java
package es.sample;

import java.util.List;
import java.util.UUID;

public class OrderRepository {
  private final EventStore store;

  public OrderRepository(EventStore store) { this.store = store; }

  public OrderAggregate load(UUID id) {
    var agg = OrderAggregate.empty();
    for (var e : store.loadStream(streamId(id))) {
      agg.apply((OrderEvent) e);
    }
    return agg;
  }

  public void save(UUID id, long expectedVersion, List<OrderEvent> newEvents) {
    store.appendToStream(streamId(id), expectedVersion, newEvents);
  }

  private String streamId(UUID id) { return "Order-" + id; }
}
```

### 4) Application Service (Command Handling)

```java
// OrderService.java
package es.sample;

import java.util.List;
import java.util.UUID;

public class OrderService {
  private final OrderRepository repo;

  public OrderService(OrderRepository repo) { this.repo = repo; }

  public UUID place(String customerId) {
    UUID id = UUID.randomUUID();
    var agg = OrderAggregate.empty();
    List<OrderEvent> events = agg.place(id, customerId);
    events.forEach(agg::apply);
    repo.save(id, 0, events);
    return id;
  }

  public void addItem(UUID id, String sku, int qty) {
    var agg = repo.load(id);
    var events = agg.addItem(sku, qty);
    events.forEach(agg::apply);
    repo.save(id, agg.version(), events);
  }

  public void confirm(UUID id) {
    var agg = repo.load(id);
    var events = agg.confirm();
    if (events.isEmpty()) return; // idempotent
    events.forEach(agg::apply);
    repo.save(id, agg.version(), events);
  }
}
```

### 5) Projection (Read Model)

```java
// OrderSummaryProjection.java
package es.sample;

import java.util.*;

public class OrderSummaryProjection {
  private static class Summary { String customerId; int totalItems; boolean confirmed; }
  private final Map<UUID, Summary> view = new HashMap<>();

  public void apply(OrderEvent e) {
    switch (e) {
      case OrderPlaced ev -> {
        var s = new Summary();
        s.customerId = ev.customerId();
        view.put(ev.aggregateId(), s);
      }
      case ItemAdded ev -> {
        var s = view.get(ev.aggregateId());
        s.totalItems += ev.qty();
      }
      case OrderConfirmed ev -> {
        var s = view.get(ev.aggregateId());
        s.confirmed = true;
      }
      default -> {}
    }
  }

  public Optional<Map<String,Object>> get(UUID id) {
    var s = view.get(id);
    if (s == null) return Optional.empty();
    return Optional.of(Map.of("customerId", s.customerId, "totalItems", s.totalItems, "confirmed", s.confirmed));
  }
}
```

> Replace `InMemoryEventStore` with:
> 
> -   **Relational:** append-only table with `(stream_id, sequence, type, version, payload, metadata, occurred_at)` and unique `(stream_id, sequence)` + index by `(type)`.
>     
> -   **EventStoreDB:** native streams with optimistic concurrency.
>     
> -   **Kafka + compacted topic per stream** (more advanced; typically pair with a DB for indexing).
>     

---

## Known Uses

-   **EventStoreDB** ecosystems in finance, logistics, and gaming for strong audit and replay.
    
-   **Axon Framework**, **Lagom**, **Akka Persistence** in enterprise Java.
    
-   Tech talks/blogs from **CQRS pioneer communities** (Greg Young et al.), **GitHub Issues** event logs, **Ledger-style** systems.
    

## Related Patterns

-   **CQRS & Read Models:** Naturally paired—events drive projections optimized for queries.
    
-   **Snapshotting:** Periodic state captures to speed aggregate loading.
    
-   **Saga / Process Manager:** Coordinate multi-aggregate workflows with event choreography/orchestration.
    
-   **Transactional Outbox / CDC:** To publish events reliably to external brokers if the event store is not the broker.
    
-   **Idempotent Consumer & Dead Letter Queue:** Robust projections and recovery.
    
-   **Event Carried State Transfer:** When consumers need just enough state in the event payload.

