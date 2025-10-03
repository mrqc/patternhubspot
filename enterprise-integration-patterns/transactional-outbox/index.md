# Transactional Outbox — Enterprise Integration Pattern

## Pattern Name and Classification

**Name:** Transactional Outbox  
**Classification:** Reliability / Data Integration pattern; ensures **atomic persistence + message publication** via an outbox table and asynchronous delivery.

## Intent

Guarantee that **domain state changes** and the **messages/events** describing them are persisted **atomically**, then deliver those messages reliably to a message broker **after** commit—achieving exactly-once **effects** without distributed 2PC.

## Also Known As

-   Outbox Pattern
    
-   Event Outbox / Reliable Publication
    
-   Insert-then-Publish
    
-   Transactional Log Tailing (when paired with CDC)
    

## Motivation (Forces)

-   Writing to a database **and** publishing to a broker are two resources; a crash between them causes **lost or phantom events**.
    
-   Distributed transactions (XA/2PC) hurt availability and performance; many brokers/cloud services don’t support them.
    
-   We want: **(1)** atomic commit of domain change + message record, **(2)** **at-least-once** delivery to the broker, and **(3)** **idempotent**/deduplicated consumption downstream.
    

**Tensions**

-   Simplicity (poll-publish) vs. low-latency CDC (Debezium).
    
-   Throughput vs. outbox table growth (retention/compaction).
    
-   Message ordering guarantees vs. concurrency/sharding.
    

## Applicability

Use Transactional Outbox when:

-   A service updates its **own database** and must emit events/commands reliably.
    
-   You need to avoid distributed transactions while keeping **strong write-side consistency**.
    
-   The message broker or downstream transport is **at-least-once** and consumers are (or can be) **idempotent**.
    
-   You can tolerate **asynchronous** publication (milliseconds–seconds).
    

Avoid or limit when:

-   You require **synchronous** response from downstream as part of the same user transaction.
    
-   The service doesn’t have a database or cannot persist an outbox record.
    

## Structure

```rust
Client  -->  Service  --(local ACID tx)--> [Domain Tables]
                               \----> [OUTBOX table]  --commit-->
                                                           |
                                           Publisher / CDC reads outbox
                                                           |
                                                   Message Broker (topic/queue)
```

## Participants

-   **Domain Model / Repository:** Performs local ACID changes.
    
-   **Outbox Table:** Holds messages to publish (payload + headers + destination + status).
    
-   **Publisher:** Polls/streams outbox records and publishes to broker, then marks **dispatched**.
    
-   **CDC Connector (optional):** Streams outbox rows via change data capture instead of polling.
    
-   **Message Broker:** Final destination (Kafka, RabbitMQ, etc.).
    
-   **Retention Job:** Deletes or archives dispatched rows.
    

## Collaboration

1.  Inside a **single DB transaction**, persist domain changes **and** insert an **outbox row**.
    
2.  Transaction commits → data and outbox row are durable together.
    
3.  A separate **publisher** process/thread reads **undispatched** rows, publishes them, and marks them **dispatched** (idempotently).
    
4.  On failures, the publisher retries; duplicates are safe because consumers are (or should be) **idempotent**.
    

## Consequences

**Benefits**

-   Eliminates the “**saved-but-not-published** / **published-but-not-saved**” race without 2PC.
    
-   Local, simple transactional boundary; scales independently.
    
-   Works with any broker/transport; resilient to temporary broker outages.
    

**Liabilities**

-   Requires additional table, background job/connector, and retention management.
    
-   Delivery is **async**; consumers may observe changes slightly later than writers.
    
-   Ordering across **multiple aggregates** is not guaranteed unless carefully sharded and sequenced.
    
-   If the publisher fails after publish but before marking dispatched, **duplicate** publishes can occur → require **idempotent consumers** or broker idempotency.
    

## Implementation

-   **Outbox schema (typical):**
    
    -   `id` (UUID), `aggregate_type`, `aggregate_id`, `event_type`, `payload_json` (or bytes),  
        `headers_json`, `destination` (topic/queue), `occurred_at`, `dispatched_at NULLABLE`, `shard_key`, `attempts`, `last_error`.
        
    -   Indices on `(dispatched_at, shard_key)` and `(occurred_at)`.
        
-   **Write path:** Within the domain TX, call `outbox.stage(event)`.
    
-   **Publish path:**
    
    -   **Polling**: every N ms, select a batch of rows where `dispatched_at IS NULL`, publish, then mark dispatched (in a separate small TX).
        
    -   **CDC** (Debezium): stream `INSERT`s from the outbox and publish; no polling.
        
-   **Idempotency:**
    
    -   Carry a stable `message_id` in headers; consumers dedupe using Redis/DB (Idempotent Receiver).
        
    -   Some brokers (Kafka) + producer configs can help (idempotent producers, keys).
        
-   **Ordering:**
    
    -   For Kafka, publish with **key = aggregate\_id** to preserve per-aggregate order.
        
    -   Use `shard_key` to partition scanning if needed.
        
-   **Failures & backoff:** Exponential backoff, `attempts` limit, move poison rows to a **parking lot** column/status.
    
-   **Retention:** Delete dispatched rows older than X days or archive to cold storage.
    
-   **Observability:** Metrics for backlog size, publish latency, attempts, error rates.
    

---

## Sample Code (Java)

Below is a pragmatic Spring/JPA + Kafka example using **polling publisher**. Swap the broker layer as you wish.

### 1) Outbox Entity & Repository

```java
// build.gradle: spring-boot-starter-data-jpa, spring-kafka, jackson-databind
import jakarta.persistence.*;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "outbox",
  indexes = {
    @Index(name="ix_outbox_dispatch", columnList = "dispatchedAt"),
    @Index(name="ix_outbox_occurred", columnList = "occurredAt"),
    @Index(name="ix_outbox_shard", columnList = "shardKey,dispatchedAt")
  })
public class OutboxRecord {

  @Id
  @Column(columnDefinition = "uuid")
  private UUID id;

  @Column(nullable=false, length=80)
  private String destination; // e.g., Kafka topic

  @Column(nullable=false, length=80)
  private String eventType;

  @Column(nullable=false, length=80)
  private String aggregateType;

  @Column(nullable=false, length=120)
  private String aggregateId;

  @Lob @Column(nullable=false)
  private String payloadJson;

  @Lob
  private String headersJson;

  @Column(nullable=false)
  private Instant occurredAt;

  private Instant dispatchedAt;

  @Column(length=64)
  private String shardKey;

  @Column(nullable=false)
  private int attempts = 0;

  @Column(length=500)
  private String lastError;

  // getters/setters/constructors omitted for brevity

  public static OutboxRecord of(String destination, String eventType, String aggregateType,
                                String aggregateId, String payloadJson, String headersJson, String shardKey) {
    OutboxRecord r = new OutboxRecord();
    r.id = UUID.randomUUID();
    r.destination = destination;
    r.eventType = eventType;
    r.aggregateType = aggregateType;
    r.aggregateId = aggregateId;
    r.payloadJson = payloadJson;
    r.headersJson = headersJson;
    r.occurredAt = Instant.now();
    r.shardKey = shardKey;
    return r;
  }
}
```

```java
import org.springframework.data.jpa.repository.*;
import org.springframework.data.repository.query.Param;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

public interface OutboxRepository extends JpaRepository<OutboxRecord, UUID> {

  @Query("""
     select o from OutboxRecord o
      where o.dispatchedAt is null
      order by o.occurredAt asc
  """)
  List<OutboxRecord> findBatch(org.springframework.data.domain.Pageable pageable);

  @Modifying
  @Query("update OutboxRecord o set o.dispatchedAt = :ts, o.attempts = :attempts where o.id = :id")
  void markDispatched(@Param("id") UUID id, @Param("ts") Instant ts, @Param("attempts") int attempts);

  @Modifying
  @Query("update OutboxRecord o set o.attempts = :attempts, o.lastError = :err where o.id = :id")
  void markAttempt(@Param("id") UUID id, @Param("attempts") int attempts, @Param("err") String err);

  @Modifying
  @Query("delete from OutboxRecord o where o.dispatchedAt < :before")
  int deleteOlderThan(@Param("before") Instant before);
}
```

### 2) Staging the Outbox Inside a Domain Transaction

```java
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class OrderService {

  private final OutboxRepository outbox;
  private final ObjectMapper json;
  private final jakarta.persistence.EntityManager em;

  public OrderService(OutboxRepository outbox, ObjectMapper json, jakarta.persistence.EntityManager em) {
    this.outbox = outbox; this.json = json; this.em = em;
  }

  @Transactional
  public void createOrder(CreateOrderCommand cmd) {
    // 1) Local domain write
    OrderEntity order = new OrderEntity(cmd.orderId(), cmd.sku(), cmd.qty());
    em.persist(order);

    // 2) Stage event in the same TX
    try {
      OrderCreated evt = new OrderCreated(cmd.orderId(), cmd.sku(), cmd.qty());
      String payload = json.writeValueAsString(evt);
      String headers = json.writeValueAsString(java.util.Map.of(
          "messageId", java.util.UUID.randomUUID().toString(),
          "eventType", "orders.order.created",
          "eventVersion", "v1",
          "correlationId", cmd.correlationId()
      ));
      OutboxRecord rec = OutboxRecord.of(
          "orders.created.v1", "OrderCreated", "Order", cmd.orderId(), payload, headers, cmd.orderId());
      outbox.save(rec);
    } catch (Exception e) {
      throw new IllegalStateException("failed to stage outbox", e);
    }
  }

  public record CreateOrderCommand(String orderId, String sku, int qty, String correlationId) {}
  public record OrderCreated(String orderId, String sku, int qty) {}
}
```

### 3) Publisher (Polling) with Kafka

```java
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;
import java.time.Instant;
import java.util.List;

@Component
public class OutboxPublisher {

  private final OutboxRepository repo;
  private final KafkaTemplate<String, byte[]> kafka;

  public OutboxPublisher(OutboxRepository repo, KafkaTemplate<String, byte[]> kafka) {
    this.repo = repo; this.kafka = kafka;
  }

  // Small, frequent batches reduce lock times and latency
  @Scheduled(fixedDelay = 300) // every 300ms
  @Transactional(readOnly = true)
  public void publishBatch() {
    List<OutboxRecord> batch = repo.findBatch(org.springframework.data.domain.PageRequest.of(0, 100));
    for (OutboxRecord rec : batch) {
      try {
        var record = new org.apache.kafka.clients.producer.ProducerRecord<String, byte[]>(
            rec.getDestination(), rec.getAggregateId(), rec.getPayloadJson().getBytes(java.nio.charset.StandardCharsets.UTF_8));

        // propagate headers (optional)
        if (rec.getHeadersJson() != null && !rec.getHeadersJson().isBlank()) {
          var map = new com.fasterxml.jackson.databind.ObjectMapper()
              .readValue(rec.getHeadersJson(), java.util.Map.class);
          map.forEach((k, v) -> record.headers().add(k.toString(),
              v == null ? new byte[0] : v.toString().getBytes()));
        }

        kafka.send(record).get(); // sync to simplify marking dispatched; in prod, handle async + callbacks
        // Mark dispatched (separate small TX not required if we open a new one per loop)
        repo.markDispatched(rec.getId(), Instant.now(), rec.getAttempts() + 1);
      } catch (Exception ex) {
        repo.markAttempt(rec.getId(), rec.getAttempts() + 1, shorten(ex.getMessage()));
        // leave undispatched -> will retry on next tick
      }
    }
  }

  private String shorten(String s) { return s == null ? null : s.substring(0, Math.min(480, s.length())); }
}
```

### 4) Optional: Retention/Purge

```java
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import java.time.Instant;

@Component
public class OutboxRetention {
  private final OutboxRepository repo;
  public OutboxRetention(OutboxRepository repo) { this.repo = repo; }

  @Scheduled(cron = "0 0 * * * *") // hourly
  public void purge() {
    Instant before = Instant.now().minus(java.time.Duration.ofDays(7));
    repo.deleteOlderThan(before);
  }
}
```

### 5) CDC Variant (Conceptual)

-   Instead of polling, configure **Debezium** (MySQL/Postgres) to capture `INSERT` into `outbox`.
    
-   A Debezium consumer publishes to the broker; no marking is necessary (or mark via separate job if you still want “dispatched\_at”).
    
-   Keep the same **write-side** TX; only the **read/ship** mechanism changes.
    

---

## Known Uses

-   **Microservice architectures** ensuring reliable domain events after DB writes.
    
-   **E-commerce** order/payment services emitting `order.created`, `payment.completed`.
    
-   **FinTech** ledgers publishing booking events to analytics/ETL safely.
    
-   **CDC pipelines** using Debezium’s outbox pattern to stream change events cleanly from OLTP DBs.
    

## Related Patterns

-   **Inbox Pattern:** Mirror on the **consume** side to ensure exactly-once processing.
    
-   **Idempotent Receiver:** Downstream deduplication of potentially duplicated publishes.
    
-   **Message Store:** The outbox is a specialized message store.
    
-   **Request–Reply:** Not a replacement; combine when replies must be reliable.
    
-   **Saga / Process Manager:** Outbox emits saga step events reliably.
    
-   **Message Router / Translator:** Applied after publication on the broker side.
    

> **Key takeaway:** The Transactional Outbox turns a distributed “save + publish” problem into a **single local transaction**, followed by a **reliable async shipper**, delivering exactly-once **effects** without 2PC.

