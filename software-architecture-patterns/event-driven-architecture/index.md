# Event-Driven Architecture — Software Architecture Pattern

## Pattern Name and Classification

-   **Name:** Event-Driven Architecture (EDA)
    
-   **Classification:** Distributed Systems / Integration & Reactive / Structural + Behavioral
    

## Intent

Loosely couple components by communicating **facts that happened** (“events”). Producers emit events asynchronously; consumers react to them to update state, trigger workflows, or fan out processing. This enables **scalable**, **resilient**, and **extensible** systems.

## Also Known As

-   Eventing / Event-based Architecture
    
-   Publish–Subscribe (pub/sub)
    
-   Reactive/Event Streaming (stream-variant)
    

## Motivation (Forces)

-   **Decoupling vs. coordination:** Producers shouldn’t know consumers, yet business flows must progress.
    
-   **Scalability:** Spiky workloads require buffering, fan-out, and independent scaling.
    
-   **Resilience:** Async messaging absorbs partial failures; retries and DLQs isolate poison messages.
    
-   **Evolvability:** New consumers should subscribe without changing producers.
    
-   **Consistency:** You may accept **eventual consistency** for autonomy, or need transactional guarantees.  
    EDA balances these forces using **async message brokers/streams** with **at-least-once delivery**, idempotent consumers, and well-governed **event contracts**.
    

## Applicability

Use EDA when:

-   Multiple services must react to domain changes independently.
    
-   You need **fan-out** processing (indexing, notifications, analytics).
    
-   Spiky traffic necessitates **buffering/backpressure**.
    
-   You want pluggable integrations (add a new consumer → deploy, subscribe).
    
-   Cross-service workflows benefit from **sagas/process managers**.
    

Avoid when:

-   You require **strong, immediate consistency** across many aggregates.
    
-   The domain is simple CRUD with no reactive flows.
    

## Structure

**Core elements**

-   **Event Producer** — emits immutable events.
    
-   **Event** — fact with schema, key, timestamp, and unique ID.
    
-   **Broker / Stream** — transports and stores events (Kafka, RabbitMQ, Pulsar, SNS/SQS, NATS).
    
-   **Event Consumer** — handles events (idempotently), updates state, triggers side effects.
    
-   **DLQ/Retry** — safety nets for poison events.
    
-   **Schema Registry** (optional) — governs event contracts.
    
-   **Outbox / Transactional Publisher** — ensures events are published reliably with DB changes.
    

```scss
[Producer Service] --(event)--> [Broker/Stream] --+--> [Consumer A]
                                                  +--> [Consumer B]
                                                  +--> [Consumer C]
```

## Participants

-   **Domain Service / Producer:** makes state changes; writes to outbox and/or emits events.
    
-   **Outbox Publisher / Connector:** moves DB outbox rows to the broker atomically.
    
-   **Broker / Stream:** durable transport, ordering (per key/partition), consumer groups.
    
-   **Consumers / Projectors:** perform side effects, build read models, kick off workflows.
    
-   **Process Manager / Saga:** coordinates multi-step flows across services.
    
-   **Observability:** logs, metrics, traces, lag dashboards.
    

## Collaboration

1.  Producer executes a business command and persists changes.
    
2.  Producer writes a corresponding **event** to an **outbox** in the same transaction.
    
3.  Outbox publisher (or CDC connector) delivers the event to the **broker**.
    
4.  Consumers receive events (pull or push), **process idempotently**, and update their stores or call other services.
    
5.  Failures trigger **retries**, exponential backoff, or **DLQ**.
    
6.  Monitoring tracks **lag**, **throughput**, and **error rate**.
    

## Consequences

**Benefits**

-   Strong **decoupling** and independent scaling.
    
-   **Elasticity** with buffering; natural fit for streaming analytics.
    
-   Easy **extensibility**: add consumers without touching producers.
    
-   Good **resilience** with retries and DLQs.
    

**Liabilities**

-   **Eventual consistency** complicates UX and invariants.
    
-   **At-least-once** delivery demands **idempotency** and deduplication.
    
-   Requires **schema governance** and **contract versioning**.
    
-   Tracing and debugging distributed flows is more complex.
    

## Implementation

### Design Guidelines

-   **Event shape:** immutable, minimal fact; include `eventId`, `occurredAt`, `aggregateId`, `version`.
    
-   **Keys & ordering:** partition by aggregate ID to preserve per-entity order.
    
-   **Idempotency:** consumers store processed `eventId` or version; use upserts.
    
-   **Reliability:** implement **Transactional Outbox** or CDC; avoid dual-writes.
    
-   **Error handling:** bounded retries, exponential backoff, **DLQ** with reprocessing tools.
    
-   **Schema evolution:** backward-compatible changes; use JSON Schema/Avro + registry.
    
-   **Observability:** log correlation IDs, measure consumer lag, expose health endpoints.
    
-   **Security:** authenticate producers/consumers; authorize topics; encrypt in transit/at rest.
    

### Patterns that pair well

-   **CQRS** for read models/projections.
    
-   **Saga/Process Manager** for long-running workflows.
    
-   **Event Sourcing** (events as system of record).
    
-   **Outbox** or **Change Data Capture (CDC)** for reliable publish.
    

---

## Sample Code (Java)

Below is a **framework-agnostic** example that demonstrates:

-   A **Transactional Outbox** (in-memory for demo)
    
-   An **Event Bus** delivering to subscribers
    
-   A **Producer** service emitting `OrderCreated`/`ItemAdded` events
    
-   A **Consumer** that builds a **read model** idempotently
    
-   A **Background dispatcher** with retry & DLQ
    

> Java 17+, no external dependencies (swap the in-memory pieces with Kafka/RabbitMQ/Pulsar in production).

```java
// === Domain Events ===
import java.math.BigDecimal;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

interface Event {
  UUID eventId();
  String type();
  UUID aggregateId();
  long version();
  Instant occurredAt();
}

record OrderCreated(UUID eventId, UUID aggregateId, long version, Instant occurredAt, String customerEmail) implements Event {
  public String type() { return "OrderCreated"; }
}
record ItemAdded(UUID eventId, UUID aggregateId, long version, Instant occurredAt, String sku, int qty, BigDecimal unitPrice) implements Event {
  public String type() { return "ItemAdded"; }
}
```

```java
// === Transactional Outbox (demo store) ===
class Outbox {
  static record Row(UUID id, String type, UUID aggregateId, long version, Instant ts, Map<String,Object> payload, int attempts) {}
  private final BlockingQueue<Row> queue = new LinkedBlockingQueue<>();
  public void save(Event e, Map<String,Object> payload) {
    queue.add(new Row(e.eventId(), e.type(), e.aggregateId(), e.version(), e.occurredAt(), Map.copyOf(payload), 0));
  }
  public Row take() throws InterruptedException { return queue.take(); }
  public void requeue(Row r){ queue.add(new Row(r.id(), r.type(), r.aggregateId(), r.version(), r.ts(), r.payload(), r.attempts()+1)); }
  public boolean isEmpty(){ return queue.isEmpty(); }
}
```

```java
// === Broker (in-memory) & DLQ ===
interface Broker {
  void publish(Event e);
  void subscribe(String topic, java.util.function.Consumer<Event> handler);
}
class InMemoryBroker implements Broker {
  private final List<java.util.function.Consumer<Event>> subs = new CopyOnWriteArrayList<>();
  public void publish(Event e){ subs.forEach(s -> s.accept(e)); }
  public void subscribe(String topic, java.util.function.Consumer<Event> handler){ subs.add(handler); }
}
class DeadLetterQueue {
  private final List<Outbox.Row> rows = new CopyOnWriteArrayList<>();
  public void put(Outbox.Row r, String reason){ rows.add(r); System.err.println("DLQ: " + r.id() + " reason=" + reason); }
  public List<Outbox.Row> rows(){ return rows; }
}
```

```java
// === Outbox Dispatcher (background) ===
class OutboxDispatcher implements AutoCloseable {
  private final Outbox outbox; private final Broker broker; private final DeadLetterQueue dlq;
  private final ExecutorService exec = Executors.newSingleThreadExecutor();
  private final AtomicBoolean running = new AtomicBoolean(true);
  private final int maxAttempts = 5;

  public OutboxDispatcher(Outbox outbox, Broker broker, DeadLetterQueue dlq) {
    this.outbox = outbox; this.broker = broker; this.dlq = dlq;
    exec.submit(this::run);
  }

  private void run() {
    while (running.get()) {
      try {
        var row = outbox.take(); // blocks
        Event e = materialize(row);
        try {
          broker.publish(e);
        } catch (Exception ex) {
          if (row.attempts() >= maxAttempts) dlq.put(row, ex.getMessage());
          else { sleepBackoff(row.attempts()); outbox.requeue(row); }
        }
      } catch (InterruptedException ie) {
        Thread.currentThread().interrupt();
      }
    }
  }

  private Event materialize(Outbox.Row r){
    if ("OrderCreated".equals(r.type()))
      return new OrderCreated(r.id(), r.aggregateId(), r.version(), r.ts(), (String) r.payload().get("customerEmail"));
    if ("ItemAdded".equals(r.type()))
      return new ItemAdded(r.id(), r.aggregateId(), r.version(), r.ts(),
              (String) r.payload().get("sku"),
              (Integer) r.payload().get("qty"),
              new BigDecimal((String) r.payload().get("unitPrice")));
    throw new IllegalArgumentException("Unknown type " + r.type());
  }

  private void sleepBackoff(int attempts){
    try { Thread.sleep(Math.min(1000, 100 * (attempts + 1))); } catch (InterruptedException ignored) {}
  }

  @Override public void close() { running.set(false); exec.shutdownNow(); }
}
```

```java
// === Producer Service (domain + outbox write in one "transaction") ===
class OrderService {
  static class Order {
    final UUID id; long version = 0; String email; final List<String> lines = new ArrayList<>();
    Order(UUID id){ this.id = id; }
  }
  private final Map<UUID, Order> store = new ConcurrentHashMap<>();
  private final Outbox outbox;

  public OrderService(Outbox outbox){ this.outbox = outbox; }

  public UUID createOrder(String email){
    UUID id = UUID.randomUUID();
    Order o = new Order(id); o.version = 1; o.email = email; store.put(id, o);
    Event e = new OrderCreated(UUID.randomUUID(), id, o.version, Instant.now(), email);
    outbox.save(e, Map.of("customerEmail", email));
    return id;
  }

  public void addItem(UUID orderId, String sku, int qty, BigDecimal unitPrice){
    Order o = store.get(orderId); if (o == null) throw new IllegalArgumentException("not found");
    o.version++;
    o.lines.add(sku + "x" + qty);
    Event e = new ItemAdded(UUID.randomUUID(), orderId, o.version, Instant.now(), sku, qty, unitPrice);
    outbox.save(e, Map.of("sku", sku, "qty", qty, "unitPrice", unitPrice.toPlainString()));
  }
}
```

```java
// === Consumer (read model projection with idempotency) ===
class OrderProjection {
  static record Summary(UUID orderId, String customerEmail, String status, BigDecimal total, long lastVersion) {}
  private final Map<UUID, Summary> view = new ConcurrentHashMap<>();
  private final Set<UUID> processedEvents = ConcurrentHashMap.newKeySet(); // idempotency by eventId

  public OrderProjection(Broker broker){ broker.subscribe("orders", this::onEvent); }

  private void onEvent(Event e){
    if (!processedEvents.add(e.eventId())) return; // duplicate -> ignore

    if (e instanceof OrderCreated oc) {
      view.put(oc.aggregateId(), new Summary(oc.aggregateId(), oc.customerEmail(), "NEW", BigDecimal.ZERO, oc.version()));
    } else if (e instanceof ItemAdded ia) {
      view.compute(ia.aggregateId(), (id, cur) -> {
        if (cur == null || ia.version() <= cur.lastVersion()) return cur; // out-of-order or unknown
        BigDecimal line = ia.unitPrice().multiply(BigDecimal.valueOf(ia.qty()));
        return new Summary(id, cur.customerEmail(), cur.status(), cur.total().add(line), ia.version());
      });
    }
  }

  public Optional<Summary> byId(UUID id){ return Optional.ofNullable(view.get(id)); }
  public List<Summary> all(){ return new ArrayList<>(view.values()); }
}
```

```java
// === Demo wiring ===
public class EdaDemo {
  public static void main(String[] args) throws Exception {
    Outbox outbox = new Outbox();
    InMemoryBroker broker = new InMemoryBroker();
    DeadLetterQueue dlq = new DeadLetterQueue();
    try (OutboxDispatcher dispatcher = new OutboxDispatcher(outbox, e -> broker.publish(e), dlq)) {
      // Bridge: publish on a logical topic; here we just reuse the single broker
      Broker topicBroker = new Broker() {
        public void publish(Event e){ broker.publish(e); }
        public void subscribe(String topic, java.util.function.Consumer<Event> handler){ broker.subscribe(topic, handler); }
      };

      OrderProjection projection = new OrderProjection(topicBroker);
      OrderService svc = new OrderService(outbox);

      UUID id = svc.createOrder("alice@example.com");
      svc.addItem(id, "SKU-1", 2, new BigDecimal("19.90"));
      svc.addItem(id, "SKU-2", 1, new BigDecimal("49.00"));

      // Give dispatcher a moment to deliver
      Thread.sleep(200);

      System.out.println("Read model: " + projection.byId(id).orElseThrow());
      System.out.println("DLQ size: " + dlq.rows().size());
    }
  }
}
```

**What this demonstrates**

-   **Outbox** → reliable publication (simulated).
    
-   **Broker & subscribers** → decoupled fan-out.
    
-   **Idempotent projection** with `eventId` and **version guarding**.
    
-   Clear split between **producer** and **consumer** concerns.
    

> Productionize with: Kafka/RabbitMQ/Pulsar (partitions, consumer groups), CDC or Debezium outbox, schema registry, OpenTelemetry tracing, retries + DLQ tooling, and authz on topics.

## Known Uses

-   **E-commerce**: order events drive notifications, inventory, billing, and search indexing.
    
-   **Fintech/Banking**: ledger postings emit events to risk engines and statements.
    
-   **IoT/Telemetry**: device events stream to processing/alerting and storage tiers.
    
-   **Streaming analytics**: clickstreams → real-time dashboards and ML features.
    
-   **Microservices**: inter-service comms via domain events and sagas.
    

## Related Patterns

-   **CQRS** — build read models from events.
    
-   **Event Sourcing** — events as the source of truth.
    
-   **Transactional Outbox / CDC** — reliable event publication.
    
-   **Saga / Process Manager** — orchestrate multi-step flows.
    
-   **Publish–Subscribe / Message Broker** — underlying communication style.
    
-   **Secure Logger / Tamper Detection** — integrity & audit trail of event flows.
    

---

## Implementation Tips

-   Treat **event schemas as contracts**; automate compatibility checks.
    
-   Choose **delivery semantics** explicitly (at-least-once is common) and design for **idempotency**.
    
-   Partition topics by **aggregate ID** to maintain per-entity ordering.
    
-   Measure and alert on **consumer lag** and **throughput**.
    
-   Provide **replay** tooling to rebuild projections.
    
-   Plan for **versioning and upcasting** of older events.
    
-   Keep events **business-centric** (e.g., `PaymentCaptured`) rather than CRUD-y (`OrderUpdated`).

