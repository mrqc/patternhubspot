# CQRS — Microservice Pattern

## Pattern Name and Classification

**Name:** Command Query Responsibility Segregation (CQRS)  
**Classification:** Microservices / Architectural Style / Read–Write Separation (often combined with Event-Driven)

## Intent

Separate **commands** (state-changing operations) from **queries** (read-only views) into **distinct models and often distinct services**, so each side can be optimized independently for correctness, scalability, and performance—accepting **eventual consistency** between them.

## Also Known As

-   Read/Write Split
    
-   Command–Query Separation at Service Level
    
-   Write Model & Read Model
    

## Motivation (Forces)

-   **Conflicting optimizations:** Writes need strict invariants and transactional integrity; reads need denormalized, fast projections.
    
-   **Throughput and scale:** Read traffic dwarfs writes; read replicas and caches want different schemas.
    
-   **Evolving contracts:** View models for UI/API change frequently; the domain model should not be warped to fit them.
    
-   **Team ownership:** Different teams can own read experiences vs. core domain logic.
    
-   **Eventual consistency acceptable:** Many user experiences tolerate slight lag between write and read.
    

## Applicability

Use CQRS when:

-   Read workloads are **orders of magnitude** higher than writes.
    
-   You need **multiple tailored read models** (e.g., search, dashboards, mobile cards).
    
-   Complex domain rules on the write side must remain clean and intention-revealing.
    
-   You want to incorporate **event-driven projections** (with or without Event Sourcing).
    

Avoid or use lightly when:

-   The domain is simple CRUD with modest scale.
    
-   Strong **read-after-write** consistency is mandatory everywhere (unless you route reads to the write store for those paths).
    

## Structure

-   **Command Side (Write Model):** Aggregates, invariants, transactions. Emits **domain events** (or updates) after success.
    
-   **Message Transport:** Broker or reliable pipeline (e.g., Outbox→Kafka).
    
-   **Query Side (Read Model):** One or more projections/materialized views optimized for queries.
    
-   **API Edges:** Write API (commands) and one or more Read APIs (queries).
    
-   **Synchronization:** Eventually consistent via events/messages.
    

```less
[ Clients ]
   |  \ 
   |   \--(Queries)--> [Read API] -> [Read DB: projections]
   |
 (Commands)
   v
[Write API] -> [Domain/Aggregates] -> (publish events) -> [Projectors] -> update [Read DB]
```

## Participants

-   **Command API / Application Service** — validates intent and executes aggregates.
    
-   **Domain Model / Aggregates** — enforce invariants; produce **domain events**.
    
-   **Event Store / Transactional DB** — authoritative writes (optionally Event Sourcing).
    
-   **Publisher (Outbox/CDC)** — reliably emits events.
    
-   **Projectors / Consumers** — build and update read models.
    
-   **Read Stores** — SQL/NoSQL/search caches tailored to queries.
    

## Collaboration

1.  Client sends a **command** to the write API.
    
2.  Write side validates, persists changes, and **publishes events**.
    
3.  Read-side projectors consume events and **update projections**.
    
4.  Clients perform **queries** against the read API; results reflect **eventual consistency**.
    
5.  For strictly consistent reads, route to write store or use per-request consistency strategies.
    

## Consequences

**Benefits**

-   Read models are **fast and flexible**; write side remains **clean and intention-focused**.
    
-   Independent **scaling** and **storage choices** per side.
    
-   Enables **multiple views** (search indexes, cache, analytics) without contorting the domain model.
    
-   Pairs naturally with **event-driven architectures**.
    

**Liabilities**

-   **Eventual consistency** introduces complexity (staleness, ordering).
    
-   More moving parts: events, projectors, two data stores.
    
-   Requires **idempotent projections** and reliable delivery.
    
-   Debugging spans services; strong **observability** is essential.
    

## Implementation

**Key practices**

-   **Contracts:** Commands are imperative (“PlaceOrder”), events are declarative past-tense (“OrderPlaced”).
    
-   **Reliability:** Use **Transactional Outbox** or **CDC** to publish events atomically with writes.
    
-   **Projections:** Make projectors **idempotent** (upsert/delete by key); store last processed offset/version.
    
-   **Schema design:** Read models are *not* normalized—shape to query use-cases.
    
-   **Consistency choices:** For critical flows, support **read-your-own-writes** by routing to write DB or caching per request.
    
-   **Security:** Reads often have broader exposure; filter/denormalize to avoid over-sharing sensitive fields.
    
-   **Versioning:** Evolve events and read schemas with **backward-compatible** changes (upcasters if needed).
    
-   **Observability:** Correlation IDs, per-projection lag, DLQs, replay tooling.
    

---

## Sample Code (Java, dependency-light)

**Goal:** Show CQRS in a single JVM for clarity:

-   **Write side** with a tiny **event-sourced** `Order` aggregate (for clarity; CQRS does **not require** event sourcing).
    
-   **In-memory Event Store + Bus** (replace with DB + Outbox → Kafka).
    
-   **Read side** projection builds a denormalized `OrderView`.
    
-   **Query API** reads the projection; **Command API** changes state.
    

```java
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/* ========= Domain Events ========= */

sealed interface DomainEvent permits OrderPlaced, ItemAdded, OrderConfirmed {
  String orderId();
  long sequence();        // version for optimistic concurrency
  long ts();
}

record OrderPlaced(String orderId, String customerId, long sequence, long ts) implements DomainEvent {}
record ItemAdded(String orderId, String sku, int qty, long sequence, long ts) implements DomainEvent {}
record OrderConfirmed(String orderId, long sequence, long ts) implements DomainEvent {}

/* ========= Commands ========= */

sealed interface Command permits PlaceOrder, AddItem, ConfirmOrder {
  String orderId();
}
record PlaceOrder(String orderId, String customerId) implements Command {}
record AddItem(String orderId, String sku, int qty) implements Command {}
record ConfirmOrder(String orderId) implements Command {}

/* ========= Write Model (Aggregate) ========= */

final class OrderAggregate {
  private String orderId;
  private String customerId;
  private final Map<String, Integer> items = new LinkedHashMap<>();
  private boolean confirmed = false;
  private long version = -1; // -1 before first event

  static OrderAggregate rehydrate(List<DomainEvent> history) {
    OrderAggregate a = new OrderAggregate();
    for (DomainEvent e : history) a.apply(e);
    return a;
  }

  List<DomainEvent> handle(Command cmd, long nowEpochMs) {
    if (cmd instanceof PlaceOrder c) {
      if (orderId != null) throw new IllegalStateException("order exists");
      if (c.customerId() == null || c.customerId().isBlank()) throw new IllegalArgumentException("customerId required");
      return List.of(new OrderPlaced(c.orderId(), c.customerId(), version + 1, nowEpochMs));
    }
    if (cmd instanceof AddItem c) {
      if (orderId == null) throw new IllegalStateException("order missing");
      if (confirmed) throw new IllegalStateException("order confirmed");
      if (c.qty() <= 0) throw new IllegalArgumentException("qty>0");
      return List.of(new ItemAdded(orderId, c.sku(), c.qty(), version + 1, nowEpochMs));
    }
    if (cmd instanceof ConfirmOrder) {
      if (orderId == null) throw new IllegalStateException("order missing");
      if (items.isEmpty()) throw new IllegalStateException("empty order");
      if (confirmed) return List.of(); // idempotent confirm
      return List.of(new OrderConfirmed(orderId, version + 1, nowEpochMs));
    }
    throw new UnsupportedOperationException("unknown command " + cmd);
  }

  void apply(DomainEvent e) {
    if (e instanceof OrderPlaced ev) {
      this.orderId = ev.orderId(); this.customerId = ev.customerId(); this.version = ev.sequence();
    } else if (e instanceof ItemAdded ev) {
      this.items.merge(ev.sku(), ev.qty(), Integer::sum); this.version = ev.sequence();
    } else if (e instanceof OrderConfirmed ev) {
      this.confirmed = true; this.version = ev.sequence();
    }
  }

  long version() { return version; }
}

/* ========= Event Store + Bus (in-memory demo) ========= */

final class EventStore {
  private final Map<String, List<DomainEvent>> streams = new ConcurrentHashMap<>();

  synchronized List<DomainEvent> load(String orderId) {
    return new ArrayList<>(streams.getOrDefault(orderId, List.of()));
  }

  // optimistic append; throws if expected doesn't match
  synchronized void append(String orderId, long expectedVersion, List<DomainEvent> newEvents, EventBus bus) {
    List<DomainEvent> cur = streams.computeIfAbsent(orderId, k -> new ArrayList<>());
    long currentVersion = cur.isEmpty() ? -1 : cur.get(cur.size()-1).sequence();
    if (currentVersion != expectedVersion)
      throw new IllegalStateException("concurrency conflict: expected " + expectedVersion + " but was " + currentVersion);

    cur.addAll(newEvents);
    for (DomainEvent e : newEvents) bus.publish(e);
  }
}

final class EventBus {
  private final List<java.util.function.Consumer<DomainEvent>> subs = new ArrayList<>();
  void subscribe(java.util.function.Consumer<DomainEvent> c) { subs.add(c); }
  void publish(DomainEvent e) { subs.forEach(s -> s.accept(e)); }
}

/* ========= Application Services ========= */

final class CommandService {
  private final EventStore store;
  private final EventBus bus;

  CommandService(EventStore store, EventBus bus) { this.store = store; this.bus = bus; }

  void handle(Command cmd) {
    long now = Instant.now().toEpochMilli();
    var history = store.load(cmd.orderId());
    var agg = OrderAggregate.rehydrate(history);
    var events = agg.handle(cmd, now);
    if (!events.isEmpty()) store.append(cmd.orderId(), agg.version(), events, bus);
  }
}

/* ========= Read Model (Projection) ========= */

record OrderView(String orderId, String customerId, Map<String,Integer> items, String status, long updatedAt) {}

final class OrderProjection {
  private final Map<String, OrderView> views = new ConcurrentHashMap<>();

  OrderProjection(EventBus bus) {
    bus.subscribe(this::onEvent);
  }

  private void onEvent(DomainEvent e) {
    OrderView old = views.get(e.orderId());
    if (e instanceof OrderPlaced ev) {
      views.put(ev.orderId(), new OrderView(ev.orderId(), ev.customerId(), new LinkedHashMap<>(), "NEW", ev.ts()));
    } else if (e instanceof ItemAdded ev) {
      var items = old == null ? new LinkedHashMap<String,Integer>() : new LinkedHashMap<>(old.items());
      items.merge(ev.sku(), ev.qty(), Integer::sum);
      String status = old == null ? "NEW" : old.status();
      views.put(ev.orderId(), new OrderView(ev.orderId(), old == null ? null : old.customerId(), items, status, ev.ts()));
    } else if (e instanceof OrderConfirmed ev) {
      var items = old == null ? Map.<String,Integer>of() : old.items();
      views.put(ev.orderId(), new OrderView(ev.orderId(), old == null ? null : old.customerId(), items, "CONFIRMED", ev.ts()));
    }
  }

  Optional<OrderView> get(String orderId) { return Optional.ofNullable(views.get(orderId)); }
}

/* ========= Query API ========= */

final class QueryService {
  private final OrderProjection proj;
  QueryService(OrderProjection proj) { this.proj = proj; }
  Optional<OrderView> getOrder(String id) { return proj.get(id); }
}

/* ========= Demo ========= */

public class CqrsDemo {
  public static void main(String[] args) {
    EventBus bus = new EventBus();
    EventStore store = new EventStore();
    OrderProjection projection = new OrderProjection(bus);
    CommandService commands = new CommandService(store, bus);
    QueryService queries = new QueryService(projection);

    String orderId = "ORD-1001";

    // Commands (write side)
    commands.handle(new PlaceOrder(orderId, "CUST-9"));
    commands.handle(new AddItem(orderId, "SKU-ESP", 1));
    commands.handle(new AddItem(orderId, "SKU-MUG", 2));
    commands.handle(new ConfirmOrder(orderId));

    // Queries (read side — eventually consistent; here synchronous)
    var view = queries.getOrder(orderId).orElseThrow();
    System.out.println("OrderView: id=" + view.orderId() + ", customer=" + view.customerId()
        + ", items=" + view.items() + ", status=" + view.status());
  }
}
```

**Notes on the example**

-   **One JVM for clarity**; in production, the **write** and **read** sides are separate apps/services, usually with a broker (e.g., Kafka) between them.
    
-   The write side uses **event sourcing** to produce events; CQRS can also be implemented with a traditional write DB and an **Outbox** to publish change events.
    
-   The read projection is **idempotent** (upserts) and can be **replayed** from an event log to rebuild views.
    
-   Add **offset tracking** per projection, DLQ for poison events, and **schema evolution** (event versioning) in real systems.
    

## Known Uses

-   **E-commerce:** write-focused order service; read-optimized order history, carts, and product search.
    
-   **Banking/Fintech:** ledger writes vs. many tailored read views (balances, statements, dashboards).
    
-   **IoT/Telemetry:** event-heavy writes with time-series/materialized views for analytics.
    
-   **Collaboration tools:** commands for documents/tasks with denormalized read models for fast lists and feeds.
    

## Related Patterns

-   **Event Sourcing:** Often paired with CQRS; the write-side state is the **event log**.
    
-   **Transactional Outbox / CDC:** Reliable event publication from the write store to read-side projectors.
    
-   **Materialized View / Read Model:** The core technique on the query side.
    
-   **BFF / API Gateway:** Expose specialized read models to clients.
    
-   **Saga / Compensating Transaction:** Coordinate multi-service writes while read side remains independent.
    
-   **Anti-Corruption Layer:** Translate upstream events/models before projecting into your read stores.
