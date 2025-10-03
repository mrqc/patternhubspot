# Reliable Publisher–Subscriber — Event-Driven Architecture Pattern

## Pattern Name and Classification

**Name:** Reliable Publisher–Subscriber  
**Classification:** Event-Driven Architecture (EDA) / Delivery Assurance & Integration / Enterprise Integration Pattern

## Intent

Ensure that **published events are durably recorded and eventually delivered** to **all intended subscribers** exactly-once (or effectively-once) at the **effects level**, despite crashes, retries, network partitions, or consumer restarts.

## Also Known As

-   Exactly-Once *Effects* (EOE)
    
-   Guaranteed Delivery Pub/Sub
    
-   Outbox–Inbox Pub/Sub
    
-   Idempotent Publisher & Subscriber
    

## Motivation (Forces)

-   **No lost events:** Producers may crash after committing DB state but before sending to the broker—or vice versa.
    
-   **At-least-once brokers:** Kafka, RabbitMQ, SQS, Pulsar default to at-least-once; duplicates happen.
    
-   **End-to-end reliability:** Need durable publish + deduped, idempotent consumption + observable retries.
    
-   **Operational realities:** Rebalances, batch processing, poison messages, partial failures, schema evolution.
    
-   **Throughput vs. guarantees:** Strong guarantees must not throttle the system excessively.
    

## Applicability

Use **Reliable Pub/Sub** when:

-   Domain state changes must **always** emit events (integration contracts, audit, read models).
    
-   Consumers trigger **side-effects** (emails, payments, search indexing) and must avoid duplicates.
    
-   Multiple consumers with different SLAs need independent progress and replay.
    

Be cautious when:

-   The domain doesn’t need cross-service integration or audit (simple CRUD).
    
-   Latency constraints preclude durable writes and relay steps (consider async + eventual consistency).
    

## Structure

-   **Transactional Outbox (Producer side):** Persist event records in producer’s DB **in the same transaction** as domain changes.
    
-   **Outbox Relay:** Background process that reads outbox rows, publishes to broker with **idempotent producer** settings, and marks rows sent.
    
-   **Broker:** Durable, partitioned log/queue with replication and retention.
    
-   **Subscriber Inbox / Dedupe Store:** Per consumer, persists processed message IDs to ensure idempotent effects.
    
-   **Idempotent Handlers:** Apply changes using natural keys/optimistic locks; commit after effect succeeds.
    
-   **DLQ / Parking Lot:** Quarantine poison messages after bounded retries.
    
-   **Observability:** Metrics, tracing, lag, DLQ rate, relay backlog.
    

*Textual diagram*

```less
[App Service Tx]
       |  (same tx)
       v
 [Domain Tables] + [Outbox]  --relay-->  [Broker Topic]
                                         /     |     \
                                   [Subscriber A] [Subscriber B] ...
                                      |  (Inbox/Dedupe)
                                      v
                                   [Effects/DB]
```

## Participants

-   **Producer Service** — executes business transaction and writes outbox rows atomically.
    
-   **Outbox Relay** — reliably publishes outbox events to the broker.
    
-   **Broker** — Kafka/RabbitMQ/Pulsar/SNS/SQS, provides persistence and fan-out.
    
-   **Subscriber Service(s)** — consume and perform idempotent effects, maintain **Inbox**.
    
-   **DLQ Handler** — triage and repair failed messages.
    
-   **Metrics/Tracing** — monitors relay backlog, consumer lag, retries, DLQ.
    

## Collaboration

1.  Producer handles a command and **commits** both domain changes **and outbox record** within one DB transaction.
    
2.  Relay scans the outbox (status=`NEW`), publishes to broker with producer idempotency/acks, marks as `SENT`.
    
3.  Broker delivers records (possibly duplicates) to each subscriber’s consumer group.
    
4.  Subscriber reads a record, checks **Inbox** (messageId seen?):
    
    -   If new → run handler → write effect + **insert inbox row** atomically → commit → ack.
        
    -   If seen → **skip** effect → ack.
        
5.  On failures, retry with backoff; after max attempts route to DLQ (with context).
    

## Consequences

**Benefits**

-   **No lost events** (outbox tx) + **no duplicate effects** (inbox/dedupe).
    
-   Works with commodity at-least-once brokers.
    
-   Decoupled consumers, independent retries, replayable history.
    
-   Strong audit trail via outbox and inbox.
    

**Liabilities**

-   Extra storage + background relay complexity.
    
-   Consumer latency increases due to dedupe and transactions.
    
-   Requires careful **idempotent effect design** (natural keys, upserts).
    
-   Operational plumbing (DLQ, backoff, dashboards) is non-trivial.
    

## Implementation

**Producer side**

-   **Transactional Outbox table** with `(event_id, aggregate_id, type, payload, created_at, status, last_error)`.
    
-   Write domain state and outbox row **in the same transaction**.
    
-   Relay: pull `NEW` rows in batches, publish with **acks=all** (Kafka) or **publisher confirms** (RabbitMQ), enable **idempotent producer** (Kafka) and stable `transactional.id` if using transactions.
    

**Consumer side**

-   **Inbox table** `(consumer, event_id, processed_at, handler_version)` with unique `(consumer, event_id)`.
    
-   Handler does **“effect then insert inbox row”** (or vice-versa) **atomically**; use **optimistic locking** for upserts.
    
-   Classify errors: retryable vs. fatal → DLQ.
    
-   Use **backoff + jitter**, bounded attempts, and circuit breakers.
    
-   Preserve per-key ordering via partition key selection (e.g., aggregateId).
    

**Schema & evolution**

-   Version event contracts; use upcasters/transformers on the consumer.
    

**Observability**

-   Relay backlog, publish latency/error, consumer lag, retry counts, DLQ reasons, exactly-once success after retry.
    

---

## Sample Code (Java, Spring Boot style; Outbox + Relay + Inbox + Kafka)

> Compact sketch showing: transactional outbox, relay publisher, idempotent subscriber with inbox dedupe, and DLQ. Replace in-memory broker bits with your messaging platform.

```java
// ---------- Domain + Outbox (Producer) ----------
import jakarta.persistence.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Entity
@Table(name = "outbox",
    uniqueConstraints = @UniqueConstraint(columnNames = "eventId"))
class Outbox {
  @Id @GeneratedValue(strategy = GenerationType.IDENTITY) Long id;
  @Column(nullable=false, unique=true) String eventId;
  @Column(nullable=false) String aggregateId;
  @Column(nullable=false) String type;
  @Lob @Column(nullable=false) String payloadJson;
  @Column(nullable=false) String status; // NEW, SENT, ERROR
  @Column(nullable=false) long createdAt;
  @Column(nullable=false) int attempts;
  String lastError;

  protected Outbox() {}
  Outbox(String eventId, String aggregateId, String type, String payloadJson) {
    this.eventId = eventId; this.aggregateId = aggregateId; this.type = type;
    this.payloadJson = payloadJson; this.status = "NEW"; this.createdAt = System.currentTimeMillis();
  }
}
interface OutboxRepo extends org.springframework.data.repository.CrudRepository<Outbox, Long> {
  @Query(value = "select * from outbox where status = 'NEW' order by id limit :lim for update skip locked",
         nativeQuery = true)
  java.util.List<Outbox> lockBatch(@Param("lim") int lim);
}

@Entity
@Table(name="order_hdr")
class OrderHdr {
  @Id String orderId;
  String status;
  protected OrderHdr() {}
  OrderHdr(String orderId, String status) { this.orderId = orderId; this.status = status; }
}
interface OrderRepo extends org.springframework.data.repository.CrudRepository<OrderHdr, String> {}

record OrderPlacedEvt(String eventId, String orderId, String status) {}

@Service
class OrderService {
  private final OrderRepo orders; private final OutboxRepo outbox;
  OrderService(OrderRepo orders, OutboxRepo outbox){ this.orders=orders; this.outbox=outbox; }

  @Transactional
  public void placeOrder(String orderId) {
    orders.save(new OrderHdr(orderId, "PLACED"));
    var evt = new OrderPlacedEvt(java.util.UUID.randomUUID().toString(), orderId, "PLACED");
    var json = "{\"eventId\":\""+evt.eventId()+"\",\"orderId\":\""+evt.orderId()+"\",\"status\":\"PLACED\"}";
    outbox.save(new Outbox(evt.eventId(), orderId, "OrderPlaced", json));
    // Tx ensures either both domain row and outbox row are committed, or none.
  }
}
```

```java
// ---------- Outbox Relay (Publisher) ----------
import org.apache.kafka.clients.producer.*;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
class OutboxRelay {
  private final OutboxRepo repo;
  private final KafkaProducer<String, String> producer;

  OutboxRelay(OutboxRepo repo) {
    this.repo = repo;
    var props = new java.util.Properties();
    props.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, "localhost:9092");
    props.put(ProducerConfig.ACKS_CONFIG, "all");
    props.put(ProducerConfig.ENABLE_IDEMPOTENCE_CONFIG, "true");
    props.put(ProducerConfig.MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION, "5");
    this.producer = new KafkaProducer<>(props,
        new org.apache.kafka.common.serialization.StringSerializer(),
        new org.apache.kafka.common.serialization.StringSerializer());
  }

  @Scheduled(fixedDelay = 500) // poll every 500ms
  public void publishBatch() {
    var batch = repo.lockBatch(100);
    for (var row : batch) {
      try {
        var rec = new ProducerRecord<String,String>("orders.events", row.aggregateId, row.payloadJson);
        rec.headers().add("eventId", row.eventId.getBytes());
        rec.headers().add("type", row.type.getBytes());
        producer.send(rec).get(); // confirm publish
        row.status = "SENT"; row.attempts++;
      } catch (Exception ex) {
        row.attempts++; row.lastError = ex.getClass().getSimpleName()+": "+ex.getMessage();
        if (row.attempts > 10) row.status = "ERROR";
      } finally {
        repo.save(row);
      }
    }
  }
}
```

```java
// ---------- Subscriber (Inbox + Idempotent Effect + DLQ) ----------
import org.apache.kafka.clients.consumer.*;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Entity
@Table(name="inbox",
    uniqueConstraints=@UniqueConstraint(columnNames={"consumer","eventId"}))
class InboxRow {
  @Id @GeneratedValue(strategy=GenerationType.IDENTITY) Long id;
  @Column(nullable=false) String consumer;
  @Column(nullable=false) String eventId;
  @Column(nullable=false) long processedAt;
  protected InboxRow(){}
  InboxRow(String consumer, String eventId){ this.consumer=consumer; this.eventId=eventId; this.processedAt=System.currentTimeMillis(); }
}
interface InboxRepo extends org.springframework.data.repository.CrudRepository<InboxRow, Long> {
  boolean existsByConsumerAndEventId(String consumer, String eventId);
}

@Entity
@Table(name="order_view")
class OrderView {
  @Id String orderId;
  String status;
  @Version Long optLock;
  protected OrderView(){}
  OrderView(String id, String st){ this.orderId=id; this.status=st; }
}
interface OrderViewRepo extends org.springframework.data.repository.CrudRepository<OrderView, String> {}

@Service
class OrdersSubscriber {
  private static final String CONSUMER = "orders-view.v1";
  private final OrderViewRepo viewRepo; private final InboxRepo inbox;
  private final KafkaConsumer<String,String> consumer; private final KafkaProducer<String,String> dlqProducer;

  OrdersSubscriber(OrderViewRepo viewRepo, InboxRepo inbox) {
    this.viewRepo = viewRepo; this.inbox = inbox;

    var props = new java.util.Properties();
    props.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, "localhost:9092");
    props.put(ConsumerConfig.GROUP_ID_CONFIG, CONSUMER);
    props.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest");
    props.put(ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, "false");
    this.consumer = new KafkaConsumer<>(props, new StringDeserializer(), new StringDeserializer());

    var pp = new java.util.Properties();
    pp.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, "localhost:9092");
    this.dlqProducer = new KafkaProducer<>(pp, new org.apache.kafka.common.serialization.StringSerializer(),
                                              new org.apache.kafka.common.serialization.StringSerializer());
    consumer.subscribe(java.util.List.of("orders.events"));
    new Thread(this::loop, "orders-subscriber").start();
  }

  private void loop() {
    while (true) {
      var records = consumer.poll(java.time.Duration.ofSeconds(1));
      for (var rec : records) {
        var eventId = header(rec, "eventId");
        try {
          handleOne(eventId, rec.value());
          consumer.commitSync();
        } catch (Retryable ex) {
          // let it be redelivered; consider seek + backoff
        } catch (Exception ex) {
          // DLQ with context
          var pr = new ProducerRecord<String,String>("orders.events.dlq", rec.key(), rec.value());
          pr.headers().add("eventId", (eventId==null?"":eventId).getBytes());
          pr.headers().add("reason", ex.getClass().getSimpleName().getBytes());
          dlqProducer.send(pr);
          consumer.commitSync();
        }
      }
    }
  }

  @Transactional
  void handleOne(String eventId, String json) {
    if (eventId != null && inbox.existsByConsumerAndEventId(CONSUMER, eventId)) return; // dedupe

    // naive parse
    String orderId = jsonValue(json, "orderId");
    String status  = jsonValue(json, "status");

    OrderView v = viewRepo.findById(orderId).orElse(new OrderView(orderId, status));
    v.status = status;
    viewRepo.save(v); // idempotent upsert guarded by PK + optimistic lock

    if (eventId != null) inbox.save(new InboxRow(CONSUMER, eventId));
  }

  private static String header(ConsumerRecord<String,String> rec, String k) {
    var h = rec.headers().lastHeader(k);
    return h == null ? null : new String(h.value());
  }
  private static String jsonValue(String json, String key) {
    int i = json.indexOf("\""+key+"\"");
    if (i<0) return null;
    int c = json.indexOf(":", i);
    int q1 = json.indexOf("\"", c+1); int q2 = json.indexOf("\"", q1+1);
    return (q1<0||q2<0) ? null : json.substring(q1+1, q2);
  }

  static class Retryable extends RuntimeException { Retryable(String m){ super(m);} }
}
```

**Notes on the example**

-   **Outbox:** uses `FOR UPDATE SKIP LOCKED` to distribute batches across relay workers without contention.
    
-   **Producer reliability:** `acks=all`, **idempotent producer**; in Kafka you may add transactions (`transactional.id`) if you also need atomic write to multiple topics/partitions.
    
-   **Subscriber:** **Inbox** unique constraint `(consumer, eventId)` ensures **effectively-once** processing.
    
-   **DLQ:** carries headers for triage; you can later **repair & replay**.
    
-   Replace JSON parsing with Jackson/Serde; wire Spring Kafka or your broker client in production.
    

## Known Uses

-   **Order → Payment → Inventory** e-commerce flows with reliable fan-out and projection updates.
    
-   **Search indexing:** DB change → outbox → Kafka → Elasticsearch projector (idempotent upsert).
    
-   **Notification pipelines:** Business events → broker → email/SMS pushers with inbox dedupe.
    
-   **Data replication:** Operational DB → outbox → Kafka → data lake/Warehouse ingestion with DLQ.
    
-   **Ledger posting:** Transactions emitted once, consumers apply idempotent postings.
    

## Related Patterns

-   **Transactional Outbox / Change Data Capture (CDC):** Producer-side durability; CDC can replace relay by tailing binlog.
    
-   **Inbox / Idempotent Receiver:** Consumer-side dedupe and exactly-once effects.
    
-   **Dead Letter Queue:** Quarantine failed messages after retries.
    
-   **Event Replay:** Rebuild projections from the log.
    
-   **Event Router / Content-Based Router:** Selective fan-out to destinations.
    
-   **Circuit Breaker / Retry / Backpressure:** Operational guardrails alongside pub/sub.

