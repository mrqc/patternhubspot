# Transactional Outbox — Event-Driven Architecture Pattern

## Pattern Name and Classification

**Name:** Transactional Outbox  
**Classification:** Event-Driven Architecture (EDA) / Reliability & Delivery Assurance / Producer-Side Guarantee

## Intent

Guarantee that domain state changes and their corresponding **integration events** are persisted **atomically** so that no event is ever lost (or emitted without the corresponding state). Publish those events reliably to a broker via a relay (or CDC), enabling at-least-once delivery end-to-end.

## Also Known As

-   Outbox Pattern
    
-   Reliable Publish (Producer-Side)
    
-   Dual-Write Avoidance
    
-   DB-as-Queue (for the producer edge)
    

## Motivation (Forces)

-   **Dual-write problem:** Updating a DB and publishing to a broker are two separate systems; one can succeed while the other fails.
    
-   **Crash windows:** Producer may crash between DB commit and broker send (or vice versa).
    
-   **Operational resilience:** Brokers/clients can be temporarily unavailable; events must be buffered durably.
    
-   **Exactly-once effects:** Downstream can dedupe; but we must **never lose** the fact that “something happened.”
    

## Applicability

Use **Transactional Outbox** when:

-   A service persists domain data in a database and must emit events for other services/search/indexers/analytics.
    
-   You need **no lost events** and can tolerate **eventual** publication to the broker.
    
-   You own the producer DB (RDBMS or document store) and can extend its schema.
    

Be cautious when:

-   Producer has **no database** (purely stateless) — consider idempotent producer or broker transactions.
    
-   Ultra-low latency from write to publish is required (evaluate CDC latency and relay cadence).
    
-   Storage/ops cannot handle the additional outbox table and relay process.
    

## Structure

-   **Domain DB + Outbox table:** Outbox rows are inserted **in the same transaction** as domain state changes.
    
-   **Outbox Relay:** Background workers (or CDC connector) read new outbox records, publish to broker, mark as sent.
    
-   **Broker/Event Bus:** Kafka, RabbitMQ, Pulsar, SNS/SQS, etc.
    
-   **(Optional) Inbox/Dedupe in consumers:** For effectively-once effects.
    
-   **Observability:** Relay backlog, errors, publish latency.
    

*Text diagram*

```scss
[Command] → (DB Tx) → [Domain Tables] + [Outbox]
                                │
                                └──(async relay / CDC)──► [Broker Topic]
                                                         ├─► [Consumer A]
                                                         └─► [Consumer B]
```

## Participants

-   **Producer Service** — handles commands, writes domain + outbox atomically.
    
-   **Outbox Relay / CDC** — publishes outbox entries to the broker and updates status/offsets.
    
-   **Broker** — durable messaging substrate.
    
-   **Consumers** — subscribe, process, and (optionally) dedupe via an **Inbox**.
    
-   **Ops/Monitoring** — observe backlog, retries, DLQ.
    

## Collaboration

1.  Service executes a command and opens a DB transaction.
    
2.  Writes domain rows (**and**) an **outbox** row describing the event.
    
3.  Commits the transaction — both domain and outbox persist atomically.
    
4.  Relay scans `NEW` outbox rows, publishes to broker with confirmations/idempotence, marks as `SENT`.
    
5.  Consumers receive (possibly duplicate) events; dedupe and process idempotently.
    

## Consequences

**Benefits**

-   Eliminates dual-write inconsistency windows; **no lost events**.
    
-   Works with commodity at-least-once brokers.
    
-   Simple, auditable, replayable pipeline (outbox is a forensic trail).
    

**Liabilities**

-   Extra table + background relay management (or CDC infra).
    
-   Publication is asynchronous (eventual consistency).
    
-   Requires cleanup/archival policy for the outbox.
    

## Implementation

**Design choices**

-   **Schema:** `outbox(event_id, aggregate_id, type, payload, created_at, status, attempts, last_error, headers)` with unique `event_id`.
    
-   **Write path:** Always create outbox entry within the same DB transaction as domain change.
    
-   **Relay:**
    
    -   Use `SELECT … FOR UPDATE SKIP LOCKED` to shard work across multiple workers.
        
    -   Publish with `acks=all` (Kafka) or publisher confirms (RabbitMQ).
        
    -   Enable **idempotent producer** (Kafka) and retries with backoff & jitter.
        
    -   Mark rows `SENT` only after confirmation.
        
-   **Error handling:** Keep `attempts`, exponential backoff, and move to `ERROR` after max attempts; surface to alerts.
    
-   **Cleanup:** TTL-based purge or archival table/partitioning.
    
-   **CDC alternative:** Debezium (MySQL/Postgres), SQL Server CDC, or built-in logical decoding — avoids writing your own relay.
    
-   **Security & PII:** Prefer headers/metadata for routing; encrypt sensitive payload fields if required.
    

**Operational tips**

-   **Batching:** Publish in batches to amortize round-trips; bound batch size to avoid large tx times.
    
-   **Ordering:** Use `aggregate_id` as partition key to maintain per-aggregate order.
    
-   **Backpressure:** Throttle relay when broker is slow; track backlog size SLO.
    
-   **Observability:** Metrics for backlog, publish\_latency, publish\_error\_rate, attempts, and oldest\_created\_at.
    

---

## Sample Code (Java, Spring Boot + JPA + Kafka)

> This compact example shows: domain write + outbox in one transaction, a relay that publishes to Kafka with idempotence, and state transitions (`NEW` → `SENT`/`ERROR`). Replace with your frameworks as needed.

```java
// ====== Domain + Outbox entities ======
import jakarta.persistence.*;
import org.springframework.data.jpa.repository.*;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Entity
@Table(name = "orders")
class OrderEntity {
  @Id String id;
  String status;
  protected OrderEntity() {}
  OrderEntity(String id, String status) { this.id = id; this.status = status; }
}

interface OrderRepo extends org.springframework.data.repository.CrudRepository<OrderEntity, String> {}

@Entity
@Table(name = "outbox",
  uniqueConstraints = @UniqueConstraint(columnNames = "eventId"))
class OutboxEntity {
  @Id @GeneratedValue(strategy = GenerationType.IDENTITY) Long id;
  @Column(nullable=false, unique=true) String eventId;
  @Column(nullable=false) String aggregateId;
  @Column(nullable=false) String type;
  @Lob @Column(nullable=false) String payloadJson;
  @Column(nullable=false) String status; // NEW, SENT, ERROR
  @Column(nullable=false) int attempts = 0;
  @Column(nullable=false) long createdAt = System.currentTimeMillis();
  String lastError;

  protected OutboxEntity(){}
  OutboxEntity(String eventId, String aggregateId, String type, String payloadJson) {
    this.eventId = eventId; this.aggregateId = aggregateId; this.type = type; this.payloadJson = payloadJson;
    this.status = "NEW";
  }
}

interface OutboxRepo extends org.springframework.data.repository.CrudRepository<OutboxEntity, Long> {

  @Query(value = """
      select * from outbox
      where status = 'NEW'
      order by id
      limit :lim
      for update skip locked
      """, nativeQuery = true)
  java.util.List<OutboxEntity> lockBatch(@Param("lim") int limit);
}

// ====== Application service: write domain + outbox in one transaction ======
record OrderPlaced(String eventId, String orderId, String status) {}

@Service
class OrderService {
  private final OrderRepo orderRepo;
  private final OutboxRepo outboxRepo;

  OrderService(OrderRepo orderRepo, OutboxRepo outboxRepo) {
    this.orderRepo = orderRepo; this.outboxRepo = outboxRepo;
  }

  @Transactional
  public void placeOrder(String orderId) {
    // 1) domain state
    orderRepo.save(new OrderEntity(orderId, "PLACED"));
    // 2) outbox event in same transaction
    var evtId = java.util.UUID.randomUUID().toString();
    var evt = new OrderPlaced(evtId, orderId, "PLACED");
    var json = """
      {"eventId":"%s","orderId":"%s","status":"%s"}
      """.formatted(evt.eventId(), evt.orderId(), evt.status());
    outboxRepo.save(new OutboxEntity(evt.eventId(), orderId, "OrderPlaced", json));
    // commit of this method guarantees atomicity of both writes
  }
}
```

```java
// ====== Outbox Relay: publish to Kafka reliably ======
import org.apache.kafka.clients.producer.*;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
class OutboxRelay {
  private final OutboxRepo outboxRepo;
  private final KafkaProducer<String, String> producer;

  OutboxRelay(OutboxRepo outboxRepo) {
    this.outboxRepo = outboxRepo;
    var props = new java.util.Properties();
    props.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, "localhost:9092");
    props.put(ProducerConfig.ACKS_CONFIG, "all");
    props.put(ProducerConfig.ENABLE_IDEMPOTENCE_CONFIG, "true");
    props.put(ProducerConfig.RETRIES_CONFIG, Integer.toString(Integer.MAX_VALUE));
    props.put(ProducerConfig.MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION, "5"); // safe with idempotence
    producer = new KafkaProducer<>(props,
      new org.apache.kafka.common.serialization.StringSerializer(),
      new org.apache.kafka.common.serialization.StringSerializer());
  }

  @Scheduled(fixedDelay = 300) // run continuously; tune for your SLO
  public void publishBatch() {
    // Use a short transaction to lock a small batch
    var batch = outboxRepo.lockBatch(200);
    for (var row : batch) {
      try {
        var record = new ProducerRecord<String,String>("orders.events", row.aggregateId, row.payloadJson);
        record.headers().add("eventId", row.eventId.getBytes());
        record.headers().add("type", row.type.getBytes());
        // Synchronous confirm (or add callback + async metrics)
        producer.send(record).get();

        row.status = "SENT";
        row.attempts++;
      } catch (Exception e) {
        row.attempts++;
        row.lastError = e.getClass().getSimpleName() + ": " + (e.getMessage() == null ? "" : e.getMessage());
        if (row.attempts > 20) row.status = "ERROR";
      } finally {
        outboxRepo.save(row);
      }
    }
  }
}
```

```java
// ====== (Optional) Consumer-side Inbox for effectively-once effects ======
import jakarta.persistence.*;

@Entity
@Table(name="inbox", uniqueConstraints=@UniqueConstraint(columnNames={"consumer","eventId"}))
class InboxEntity {
  @Id @GeneratedValue(strategy=GenerationType.IDENTITY) Long id;
  @Column(nullable=false) String consumer;
  @Column(nullable=false) String eventId;
  @Column(nullable=false) long processedAt = System.currentTimeMillis();
  protected InboxEntity(){}
  InboxEntity(String consumer, String eventId){ this.consumer=consumer; this.eventId=eventId; }
}
interface InboxRepo extends org.springframework.data.repository.CrudRepository<InboxEntity, Long> {
  boolean existsByConsumerAndEventId(String consumer, String eventId);
}
```

**Notes on the sample**

-   **Idempotent publish:** Kafka producer is configured with idempotence and `acks=all` to prevent duplicates on the broker from causing inconsistency in the outbox state.
    
-   **Work stealing:** `for update skip locked` enables multiple relay instances to process different rows concurrently.
    
-   **Backoff:** For brevity, the relay increments `attempts`; add exponential backoff + jitter and DLQ escalation for robust ops.
    
-   **CDC option:** You can replace the relay with **Debezium** reading the outbox table and publishing to topics, which often simplifies application code and improves throughput.
    

## Known Uses

-   **eCommerce:** Order service writes outbox events that feed payments, inventory, shipping, and read models.
    
-   **Search indexing:** Product updates → outbox → Kafka → Elasticsearch projector.
    
-   **Data warehousing:** Operational DB → outbox → Kafka → Snowflake/BigQuery ingest with DLQ.
    
-   **Fintech:** Ledger updates publish reliably to accounting and notifications.
    

## Related Patterns

-   **Inbox / Idempotent Receiver:** Consumer-side dedupe for exactly-once effects.
    
-   **Reliable Publisher–Subscriber:** Combines outbox (producer) and inbox (consumer) for end-to-end guarantees.
    
-   **Event Replay & Snapshotting:** Rebuild downstream read models from durable topics.
    
-   **Change Data Capture (CDC):** Alternative transport for outbox rows via binlog/replication stream.
    
-   **Event Router / Content-Based Router:** Route published events to appropriate topics/queues.
    
-   **Retry / DLQ / Circuit Breaker:** Operational guardrails for both relay and consumers.

