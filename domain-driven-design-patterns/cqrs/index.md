
# CQRS — Domain-Driven Design Pattern

---

## Pattern Name and Classification

-   **Name:** Command–Query Responsibility Segregation (CQRS)

-   **Category:** DDD / Architectural Pattern / Read–Write Separation

-   **Level:** System/module architecture


---

## Intent

Separate **commands** (state-changing operations) from **queries** (read-only operations) into distinct models, APIs, and often data stores, to optimize each independently for correctness, scalability, and performance.

---

## Also Known As

-   Read/Write Split

-   Command–Query Separation (in the large; distinct from Meyer’s method-level CQS)


---

## Motivation (Forces)

-   A single “one-size-fits-all” model often compromises:

    -   **Writes** need invariants, transactions, and rich behavior.

    -   **Reads** need fast, denormalized views and different access patterns.

-   Different SLAs and scaling profiles: reads are ~90–99% of traffic.

-   Teams want to evolve **UI/reporting** independently of **domain rules**.


**Forces / Trade-offs**

-   ✅ Faster queries, simpler UIs, independent scaling, clearer domain invariants.

-   ⚠️ **Eventual consistency** between write and read models, extra infrastructure (projection, messaging/outbox), more moving parts.


---

## Applicability

Use CQRS when:

-   Read and write workloads have **very different** performance/shape requirements.

-   The domain demands **rich invariants** (complex command model).

-   You want **tailored read models** per screen/report (multiple views).

-   You plan **event sourcing** (CQRS pairs naturally, but it’s optional).


Avoid or defer when:

-   Domain is simple CRUD; overhead outweighs benefits.

-   Strong **read-after-write** guarantees are mandatory and projections can’t keep up.

-   Team cannot operate messaging/projection reliably yet.


---

## Structure

-   **Command Side (Write Model):** Aggregates, invariants, transactions, domain events.

-   **Query Side (Read Model):** Denormalized views optimized for queries (SQL/NoSQL/search).

-   **Propagation:** Outbox + message bus; projectors update read models asynchronously.


```scss
[API: Commands] ──> [Write Model/Aggregates] ──(events/outbox)──▶ [Projector] ──> [Read Models]
                                             ▲                                         │
[API: Queries] <─────────────────────────────┴──────────────────────────────────────────┘
```

---

## Participants

-   **Application Services (Command/Query)** — orchestrate use cases and IO.

-   **Aggregates** — enforce invariants on the write side.

-   **Outbox / Event Publisher** — reliable event handoff after commit.

-   **Projectors (Consumers)** — transform events into read views.

-   **Read Models** — denormalized DTOs/tables/indexes per use case.

-   **Message Bus** — Kafka/SQS/Rabbit (or transactional log tailing).


---

## Collaboration

-   Works with **Aggregate / Aggregate Root**, **Repository** (write side).

-   Uses **Transactional Outbox** for reliable propagation.

-   Complements **Event Sourcing** (events are the write truth).

-   Cooperates with **Saga/Process Manager** for cross-aggregate workflows.

-   Fits **API Gateway** patterns: separate `/commands` and `/queries`.


---

## Consequences

**Benefits**

-   Read models are **fast and flexible**; tailor per UI/report.

-   Write model stays **clean**, focused on invariants.

-   **Independent scaling** (many read replicas; few strong write nodes).

-   Enables **polyglot persistence** (e.g., write: PostgreSQL; read: Elastic).


**Liabilities**

-   **Eventual consistency** (stale reads, need UI strategies).

-   More components (bus, projectors, two schemas).

-   Operational complexity (monitoring lag, retries, idempotency).

-   Query joins across aggregates must be **precomposed** in projections.


Mitigations:

-   Show **pending state**/optimistic UI; **read-your-own-writes** via session cache.

-   **Idempotent** projectors; poison-queue handling.

-   **Lag SLOs** and dashboards (age of last applied event).


---

## Implementation

1.  **Split API surface**: `/commands/**` vs `/queries/**`.

2.  **Model the write side** with aggregates; persist atomically; emit domain events to an **outbox**.

3.  **Publish** outbox records to a bus reliably (poller/CDC).

4.  **Projectors** consume events, update **read models** (SQL tables, caches, search indexes).

5.  **Queries** read directly from read models (no domain aggregation needed).

6.  **Consistency UX**: design for eventual consistency (ack patterns, status endpoints).

7.  **Ops**: monitor projection lag; implement replay/rebuild of read models.


---

## Sample Code (Java, Spring) — Orders with CQRS

> Write side uses an `Order` aggregate and stores an outbox event. A projector consumes the event and updates a read table `order_view`. Queries read from the view.

```java
// ==== Domain (Write Model) ======================================
public record Money(long cents) {
    public Money { if (cents < 0) throw new IllegalArgumentException("negative"); }
    public Money add(Money other){ return new Money(this.cents + other.cents); }
}

final class OrderItem {
    private final String productId;
    private int qty;
    private final Money unitPrice;
    OrderItem(String productId, int qty, Money price){
        if (qty <= 0) throw new IllegalArgumentException("qty>0");
        this.productId = productId; this.qty = qty; this.unitPrice = price;
    }
    Money subtotal(){ return new Money(unitPrice.cents() * qty); }
    String productId(){ return productId; }
    void increase(int delta){ if (delta <= 0) throw new IllegalArgumentException("delta>0"); qty += delta; }
}

@jakarta.persistence.Entity
@jakarta.persistence.Table(name="orders")
public class Order {
    @jakarta.persistence.Id
    private java.util.UUID id;
    private boolean confirmed;
    @jakarta.persistence.Version
    private long version;
    @jakarta.persistence.Transient
    private final java.util.List<Object> events = new java.util.ArrayList<>();
    @jakarta.persistence.Transient
    private final java.util.Map<String,OrderItem> items = new java.util.LinkedHashMap<>();

    protected Order() {}
    private Order(java.util.UUID id){ this.id = id; }
    public static Order create(){ return new Order(java.util.UUID.randomUUID()); }
    public java.util.UUID id(){ return id; }

    public void addItem(String productId, int qty, long unitPriceCents){
        assertOpen();
        items.compute(productId, (k, v) -> {
            if (v == null) return new OrderItem(productId, qty, new Money(unitPriceCents));
            v.increase(qty); return v;
        });
    }
    public void confirm(){
        assertOpen();
        if (items.isEmpty()) throw new IllegalStateException("empty order");
        confirmed = true;
        long total = items.values().stream().mapToLong(i -> i.subtotal().cents()).sum();
        events.add(new OrderConfirmedEvent(id, total));
    }
    public java.util.List<Object> pullEvents(){
        var copy = java.util.List.copyOf(events); events.clear(); return copy;
    }
    private void assertOpen(){ if (confirmed) throw new IllegalStateException("already confirmed"); }
}

public record OrderConfirmedEvent(java.util.UUID orderId, long totalCents) {}
```

```java
// ==== Repositories & Outbox ====================================
public interface OrderRepository {
    java.util.Optional<Order> findById(java.util.UUID id);
    void save(Order order);
}

@jakarta.persistence.Entity
@jakarta.persistence.Table(name="outbox")
class OutboxRecord {
    @jakarta.persistence.Id
    @jakarta.persistence.GeneratedValue
    Long id;
    String type;          // e.g., "OrderConfirmedEvent"
    String payloadJson;   // serialized event
    java.time.Instant createdAt;
    boolean published;
}

public interface OutboxRepository {
    void save(OutboxRecord rec);
    java.util.List<OutboxRecord> findUnpublished(int batch);
    void markPublished(java.util.List<Long> ids);
}
```

```java
// ==== Application Service (Commands) ============================
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import com.fasterxml.jackson.databind.ObjectMapper;

@Service
public class OrderCommandService {
    private final OrderRepository orders;
    private final OutboxRepository outbox;
    private final ObjectMapper om = new ObjectMapper();

    public OrderCommandService(OrderRepository orders, OutboxRepository outbox) {
        this.orders = orders; this.outbox = outbox;
    }

    @Transactional
    public java.util.UUID placeAndConfirm(java.util.Map<String, Long> items) {
        Order o = Order.create();
        items.forEach((pid, cents) -> o.addItem(pid, 1, cents));
        o.confirm();               // emits domain event

        orders.save(o);            // commit aggregate
        for (Object evt : o.pullEvents()) {
            var rec = new OutboxRecord();
            rec.type = evt.getClass().getSimpleName();
            try { rec.payloadJson = om.writeValueAsString(evt); } catch (Exception e) { throw new RuntimeException(e); }
            rec.createdAt = java.time.Instant.now();
            rec.published = false;
            outbox.save(rec);      // stored in same TX: reliable
        }
        return o.id();
    }
}
```

```java
// ==== Publisher (Outbox -> Bus) & Projector (Bus -> Read Model) ============
public interface Bus {
    void publish(String type, String payload);
}

@org.springframework.scheduling.annotation.Scheduled(fixedDelay = 500)
public class OutboxPublisher {
    private final OutboxRepository outbox; private final Bus bus;
    public OutboxPublisher(OutboxRepository outbox, Bus bus) { this.outbox = outbox; this.bus = bus; }

    public void tick() {
        var batch = outbox.findUnpublished(200);
        var ids = new java.util.ArrayList<Long>();
        for (var rec : batch) {
            bus.publish(rec.type, rec.payloadJson);
            ids.add(rec.id);
        }
        outbox.markPublished(ids);
    }
}

@jakarta.persistence.Entity
@jakarta.persistence.Table(name="order_view") // denormalized read model
class OrderView {
    @jakarta.persistence.Id
    java.util.UUID orderId;
    long totalCents;
    String status; // "CONFIRMED"
}

public interface OrderViewRepository {
    void upsert(OrderView v);
    java.util.Optional<OrderView> findById(java.util.UUID id);
}

// Projector (idempotent)
public class OrderProjector {
    private final OrderViewRepository views;
    private final com.fasterxml.jackson.databind.ObjectMapper om = new com.fasterxml.jackson.databind.ObjectMapper();
    public OrderProjector(OrderViewRepository views) { this.views = views; }

    // invoked by bus subscriber
    public void onMessage(String type, String json) {
        if (!"OrderConfirmedEvent".equals(type)) return;
        try {
            var evt = om.readValue(json, OrderConfirmedEvent.class);
            OrderView v = new OrderView();
            v.orderId = evt.orderId();
            v.totalCents = evt.totalCents();
            v.status = "CONFIRMED";
            views.upsert(v);
        } catch (Exception e) { throw new RuntimeException(e); }
    }
}
```

```java
// ==== Query API (reads from read model only) ====================
@org.springframework.web.bind.annotation.RestController
@org.springframework.web.bind.annotation.RequestMapping("/api/orders")
class OrderQueryController {
    private final OrderViewRepository views;
    public OrderQueryController(OrderViewRepository views) { this.views = views; }

    @org.springframework.web.bind.annotation.GetMapping("/{id}")
    public OrderViewDTO get(@org.springframework.web.bind.annotation.PathVariable String id) {
        return views.findById(java.util.UUID.fromString(id))
                .map(v -> new OrderViewDTO(v.orderId.toString(), v.totalCents, v.status))
                .orElseThrow(() -> new org.springframework.web.server.ResponseStatusException(
                        org.springframework.http.HttpStatus.NOT_FOUND));
    }
}

record OrderViewDTO(String orderId, long totalCents, String status) {}
```

**Notes**

-   Command path writes aggregate and outbox **atomically**.

-   Publisher converts outbox rows to bus messages.

-   Projector consumes and **upserts** read model (idempotent).

-   Query controller **never** touches write-side aggregates.


---

## Known Uses

-   **High-traffic e-commerce**: separate product/price catalogs (read) from inventory commands.

-   **Banking/ledger UIs**: queries backed by views/search; commands enforce strict invariants.

-   **IoT/telemetry**: denormalized time-series queries vs command pipelines.

-   **Event-sourced platforms**: CQRS as the standard façade for commands/queries.


---

## Related Patterns

-   **Aggregate / Aggregate Root** — command-side invariants.

-   **Event Sourcing** — natural pair; events feed read models.

-   **Transactional Outbox** — reliable projection.

-   **Saga / Process Manager** — long-running, multi-aggregate commands.

-   **Materialized View / Read Model** — query-side structures.

-   **API Composition** — alternative for ad-hoc cross-service reads.

-   **Eventual Consistency** — consequence to design for in UX and ops.
