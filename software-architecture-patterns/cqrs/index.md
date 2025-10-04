# CQRS — Software Architecture Pattern

## Pattern Name and Classification

-   **Name:** Command Query Responsibility Segregation (CQRS)
    
-   **Classification:** Architectural Pattern / Data & Interaction / Behavioral + Structural
    

## Intent

Separate the **write** side (commands that change state) from the **read** side (queries that return state) to optimize each independently for **scalability, performance, and security**, and to enable **task-based UIs, simpler models, and clear transactional boundaries**.

## Also Known As

-   Command–Query Segregation
    
-   Split Write/Read Models
    
-   (Commonly paired with) Event Sourcing
    

## Motivation (Forces)

-   **Different workloads:** Reads often dominate writes and need denormalized, query-optimized views; writes need invariants and transactional integrity.
    
-   **Complex domains:** A single “one-size-fits-all” model gets bloated; task-based command models are simpler.
    
-   **Performance & scale:** Independent read and write scaling (replicas, caches, different storage engines).
    
-   **Security:** Easier to **deny queries on write endpoints** and vice versa.
    
-   **Evolution:** Read models can be rebuilt/reshaped without risking write invariants.
    
-   **Eventual consistency vs. UX:** Users expect fresh data; you must handle **staleness** and **read-your-writes** strategies.
    

CQRS addresses these by **separating concerns**: the write side focuses on **intent and invariants**; the read side focuses on **query shape and speed**.

## Applicability

Use CQRS when:

-   You have **high read/write asymmetry** or extremely complex query patterns.
    
-   The domain has **rich invariants** and task-based commands benefit from explicit intent.
    
-   You need to **scale reads** separately (e.g., search, analytics) or serve multiple read shapes.
    
-   You plan to support **multiple UIs/consumers** with different projections.
    
-   You want to pair with **Event Sourcing** (optional) for auditability and rebuildable views.
    

Avoid or defer when:

-   Domain is simple, CRUD fits well, and you don’t have performance or complexity pressures.
    
-   Team can’t support **eventual consistency** operationally and in UX.
    

## Structure

-   **Command side (Write Model):**
    
    -   **Commands**: intent to change state (CreateOrder, AddItem, ConfirmOrder).
        
    -   **Command Handlers / Aggregates**: validate business rules, apply changes.
        
    -   **State Storage**: transactional store; optionally **Event Store**.
        
    -   **Events (Domain/Integration)**: emitted after successful commands.
        
-   **Query side (Read Model):**
    
    -   **Projections/Views**: denormalized, query-optimized representations.
        
    -   **Query Handlers**: return DTOs; no side effects.
        
    -   **Read Storage**: purpose-fit (RDBMS, cache, search index).
        
-   **Message/Transport:**
    
    -   Event bus/stream (e.g., Kafka) or outbox → subscriber projections.
        
    -   API layer exposes separate **/commands** and **/queries** (or separate services).
        

```pgsql
[ Client/UI ]
     |                  EVENT BUS/OUTBOX
     | commands              │          queries
     v                       v            ^
+------------+       +--------------+     |
|  Command   |  -->  |  Event(s)    | --> |  Query
|  Handler   |       +--------------+     |  Handler
| (Aggregate)|              │             |
+------------+              v             |
      |                +----------+       |
      |                | Projection|       |
      v                +----------+       |
  Write Store            Read Store  <----+
```

## Participants

-   **Command**: an explicit intent (`ConfirmOrder`).
    
-   **Aggregate/Write Model**: enforces invariants and state transitions.
    
-   **Command Handler**: orchestrates aggregate loading, validation, persistence, event emission.
    
-   **Domain Event**: immutable fact produced by a successful command.
    
-   **Projection (Read Model Builder)**: subscribes to events, updates read views.
    
-   **Query Handler**: executes optimized queries and returns DTOs.
    
-   **Outbox/Bus**: reliable propagation from write to read side.
    

## Collaboration

1.  Client sends **Command** → Command Handler loads Aggregate → validates → persists new state (and emits **Events**).
    
2.  Events are **published** (transactional outbox or event store stream).
    
3.  **Projections** consume events and **update read models** (idempotent).
    
4.  Client issues **Query** against read model → fast, denormalized result.
    
5.  **Eventual consistency**: read model may lag; system can employ read-your-writes strategies (session stickiness, versioned queries, or wait-for-projection).
    

## Consequences

**Benefits**

-   Simplified **write** logic with explicit intent; **read** side scales independently.
    
-   Specialized **read stores** (search, cache) without contaminating write invariants.
    
-   Clear **audit trail** (especially with Event Sourcing).
    
-   Easier **evolution**: add/reshape projections without changing write model.
    

**Liabilities**

-   **Complexity**: two models, asynchronous projections, eventual consistency.
    
-   Requires **idempotency** and **replay-safe** projections.
    
-   Harder **transactional guarantees** across read/write sides (design compensations).
    
-   Operational overhead (outbox/bus, retries, monitoring).
    

## Implementation

### Design Guidelines

-   **Command model**: task-based APIs (`ShipOrder`, not `UpdateOrder`).
    
-   **Validation**: protect invariants in the aggregate.
    
-   **Events**: carry **minimal, necessary facts**; include `aggregateId`, `version`, `occurredAt`.
    
-   **Projection**: **idempotent** (check event version/sequence), **replayable** (can rebuild).
    
-   **Reliability**: **Transactional Outbox** or native **Event Store**; avoid dual-write.
    
-   **Consistency**: UX techniques—**UI hints**, spinner until projection version ≥ write version; or query write store for critical confirmations.
    
-   **Authorization**: commands and queries often have different auth policies.
    
-   **Testing**: given–when–then (events) for write; contract & performance tests for read.
    

### Operational Notes

-   **Schema versioning** for events & views (upcasters or multi-version consumers).
    
-   **Backpressure & retries** for projections; DLQ for poison events.
    
-   **Observability**: log event lag, projection latency, handler error rates.
    
-   **Data lifecycle**: rebuild projections on demand; snapshot long-lived aggregates.
    

---

## Sample Code (Java)

Self-contained example (Java 17) that demonstrates:

-   Command side with an **Order** aggregate
    
-   Domain **events**
    
-   An **in-memory event bus** (simulating an outbox/stream)
    
-   A **projection** building a denormalized read model
    
-   Simple **query handler**
    

> This is framework-agnostic for clarity; swap the in-memory bus with Kafka/RabbitMQ and persistence with JPA/JDBC or an event store.

```java
// ---------- Shared ----------
import java.math.BigDecimal;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;

interface Event {
    UUID aggregateId();
    long version();
    Instant occurredAt();
    String type();
}

record OrderCreated(UUID aggregateId, long version, Instant occurredAt, String customerEmail) implements Event {
    public String type() { return "OrderCreated"; }
}
record ItemAdded(UUID aggregateId, long version, Instant occurredAt, String sku, int qty, BigDecimal unitPrice) implements Event {
    public String type() { return "ItemAdded"; }
}
record OrderConfirmed(UUID aggregateId, long version, Instant occurredAt) implements Event {
    public String type() { return "OrderConfirmed"; }
}

interface EventBus {
    void publish(List<Event> events);
    void subscribe(String subscriberId, java.util.function.Consumer<Event> handler);
}

class InMemoryEventBus implements EventBus {
    private final List<java.util.function.Consumer<Event>> subs = new CopyOnWriteArrayList<>();
    public void publish(List<Event> events){ events.forEach(e -> subs.forEach(s -> s.accept(e))); }
    public void subscribe(String id, java.util.function.Consumer<Event> h){ subs.add(h); }
}
```

### Write Side (Commands, Aggregate, Repository, Handler)

```java
// ---------- Write Model ----------
enum OrderStatus { NEW, CONFIRMED }

final class OrderAggregate {
    private UUID id;
    private long version = 0;
    private OrderStatus status = OrderStatus.NEW;
    private final List<Line> lines = new ArrayList<>();
    record Line(String sku, int qty, BigDecimal unitPrice){}

    // Rehydrate from events (if using event sourcing)
    public static OrderAggregate rehydrate(List<Event> history){
        OrderAggregate a = new OrderAggregate();
        history.forEach(a::apply);
        return a;
    }

    // Decision methods (command handling)
    public List<Event> handleCreate(UUID id, String email){
        if (this.id != null) throw new IllegalStateException("order exists");
        return List.of(new OrderCreated(id, version + 1, Instant.now(), email));
    }

    public List<Event> handleAddItem(String sku, int qty, BigDecimal price){
        requireNotConfirmed();
        if (qty <= 0) throw new IllegalArgumentException("qty>0");
        return List.of(new ItemAdded(id, version + 1, Instant.now(), sku, qty, price));
    }

    public List<Event> handleConfirm(){
        requireNotConfirmed();
        if (lines.isEmpty()) throw new IllegalStateException("empty order");
        return List.of(new OrderConfirmed(id, version + 1, Instant.now()));
    }

    // Event application (state transitions)
    public void apply(Event e){
        if (e instanceof OrderCreated oc){ this.id = oc.aggregateId(); this.version = oc.version(); this.status = OrderStatus.NEW; }
        else if (e instanceof ItemAdded ia){ this.version = ia.version(); this.lines.add(new Line(ia.sku(), ia.qty(), ia.unitPrice())); }
        else if (e instanceof OrderConfirmed oc){ this.version = oc.version(); this.status = OrderStatus.CONFIRMED; }
    }

    private void requireNotConfirmed(){
        if (status == OrderStatus.CONFIRMED) throw new IllegalStateException("already confirmed");
    }
    public UUID id(){ return id; }
    public long version(){ return version; }
}

// Simple event-sourced repository (in-memory)
class OrderRepository {
    private final Map<UUID, List<Event>> store = new ConcurrentHashMap<>();
    public List<Event> history(UUID id){ return store.getOrDefault(id, List.of()); }
    public void append(UUID id, List<Event> events){
        store.compute(id, (k, v) -> {
            List<Event> current = v == null ? new ArrayList<>() : new ArrayList<>(v);
            current.addAll(events);
            return current;
        });
    }
}

// Commands
record CreateOrder(UUID orderId, String customerEmail) {}
record AddItem(UUID orderId, String sku, int qty, BigDecimal unitPrice) {}
record ConfirmOrder(UUID orderId) {}

class CommandHandler {
    private final OrderRepository repo;
    private final EventBus bus;

    CommandHandler(OrderRepository repo, EventBus bus){ this.repo = repo; this.bus = bus; }

    public void handle(CreateOrder c){
        var history = repo.history(c.orderId());
        var agg = OrderAggregate.rehydrate(history);
        var events = agg.handleCreate(c.orderId(), c.customerEmail());
        // Apply & persist atomically (simulate)
        events.forEach(agg::apply);
        repo.append(c.orderId(), events);
        bus.publish(events);
    }

    public void handle(AddItem c){
        var history = repo.history(c.orderId());
        var agg = OrderAggregate.rehydrate(history);
        var events = agg.handleAddItem(c.sku(), c.qty(), c.unitPrice());
        events.forEach(agg::apply);
        repo.append(c.orderId(), events);
        bus.publish(events);
    }

    public void handle(ConfirmOrder c){
        var history = repo.history(c.orderId());
        var agg = OrderAggregate.rehydrate(history);
        var events = agg.handleConfirm();
        events.forEach(agg::apply);
        repo.append(c.orderId(), events);
        bus.publish(events);
    }
}
```

### Read Side (Projection + Query Handler)

```java
// ---------- Read Model ----------
record OrderSummaryDTO(UUID orderId, String customerEmail, String status, BigDecimal total) {}

class OrderProjection {
    // denormalized view: orderId -> summary
    private final Map<UUID, OrderSummaryDTO> view = new ConcurrentHashMap<>();

    public OrderProjection(EventBus bus){
        bus.subscribe("order-projection", this::onEvent);
    }

    private void onEvent(Event e){
        if (e instanceof OrderCreated oc){
            view.put(oc.aggregateId(), new OrderSummaryDTO(oc.aggregateId(), oc.customerEmail(), "NEW", BigDecimal.ZERO));
        } else if (e instanceof ItemAdded ia){
            view.compute(ia.aggregateId(), (id, cur) -> {
                if (cur == null) return null; // late event; in real life you might upsert
                BigDecimal line = ia.unitPrice().multiply(BigDecimal.valueOf(ia.qty()));
                return new OrderSummaryDTO(cur.orderId(), cur.customerEmail(), cur.status(), cur.total().add(line));
            });
        } else if (e instanceof OrderConfirmed oc){
            view.compute(oc.aggregateId(), (id, cur) -> cur == null ? null :
                new OrderSummaryDTO(cur.orderId(), cur.customerEmail(), "CONFIRMED", cur.total()));
        }
    }

    public Optional<OrderSummaryDTO> byId(UUID id){ return Optional.ofNullable(view.get(id)); }
    public List<OrderSummaryDTO> all(){ return new ArrayList<>(view.values()); }
}

// Queries
record GetOrder(UUID orderId) {}
record ListOrders() {}

class QueryHandler {
    private final OrderProjection projection;
    QueryHandler(OrderProjection p){ this.projection = p; }

    public Optional<OrderSummaryDTO> handle(GetOrder q){ return projection.byId(q.orderId()); }
    public List<OrderSummaryDTO> handle(ListOrders q){ return projection.all(); }
}
```

### Demo / Wiring

```java
// ---------- Demo ----------
public class CqrsDemo {
    public static void main(String[] args) {
        EventBus bus = new InMemoryEventBus();
        OrderRepository repo = new OrderRepository();
        CommandHandler commands = new CommandHandler(repo, bus);
        OrderProjection projection = new OrderProjection(bus);
        QueryHandler queries = new QueryHandler(projection);

        UUID id = UUID.randomUUID();

        commands.handle(new CreateOrder(id, "alice@example.com"));
        commands.handle(new AddItem(id, "SKU-001", 2, new BigDecimal("19.90")));
        commands.handle(new AddItem(id, "SKU-777", 1, new BigDecimal("199.00")));
        commands.handle(new ConfirmOrder(id));

        // Eventually consistent: in-memory bus is synchronous here for demo
        System.out.println("Order: " + queries.handle(new GetOrder(id)).orElseThrow());
        System.out.println("All:   " + queries.handle(new ListOrders()));
    }
}
```

**What this shows**

-   **Commands** mutate state and produce **events**; queries never mutate.
    
-   **Aggregate** holds invariants; **projection** builds a read-optimized view.
    
-   The **bus** mimics outbox/stream; projections are **idempotent** and **replayable**.
    

> Productionize with:
> 
> -   Persistence (e.g., **JPA** for write store or an **Event Store**),
>     
> -   **Transactional Outbox** to publish events reliably,
>     
> -   **Kafka/RabbitMQ** projections (consumer groups, offsets),
>     
> -   Snapshotting for big aggregates,
>     
> -   **OpenAPI** for queries; **task-based command endpoints**;
>     
> -   Versioned events and **upcasters**.
>     

## Known Uses

-   **E-commerce & ordering** systems: fast order lookups and dashboards while enforcing strong write invariants.
    
-   **Banking/ledger**\-like domains: paired with Event Sourcing for audit trails and rebuildable read models.
    
-   **IoT/telemetry portals**: massive read scale with denormalized time-series/projected views.
    
-   **Collaboration apps**: feeds/activity projections rebuilt from event streams.
    
-   **Healthcare**: strict write-side validations with many specialized read views.
    

## Related Patterns

-   **Event Sourcing** — store events as the source of truth; CQRS consumes them naturally.
    
-   **Transactional Outbox** — ensures reliable event publication from write DB.
    
-   **Materialized View / Projection** — the read side.
    
-   **Saga / Process Manager** — orchestrate long-running, cross-aggregate workflows.
    
-   **API Gateway** — expose separate command/query endpoints cleanly.
    
-   **Domain-Driven Design** — aggregates, ubiquitous language for the write model.
    

---

## Implementation Tips

-   Start **simple CQRS (no Event Sourcing)**: commands write to OLTP; outbox publishes events; projections build read views. Add ES later if you need rebuilds/audit.
    
-   Keep **commands intentful and small**; avoid generic “update” commands.
    
-   Ensure **idempotency** in projections (check `version`/sequence).
    
-   Provide **read-your-writes** UX (sticky read replica, version wait, or hybrid read-on-write fallback).
    
-   Monitor **projection lag** and **event DLQs**; add dashboards.
    
-   Use **schema governance** for events (Avro/JSON Schema) and contract tests for queries.
    
-   Prefer **bulk projection** rebuild jobs for new read shapes; keep handlers replay-safe.

