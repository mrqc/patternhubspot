# Transactional Outbox — Microservice Pattern

## Pattern Name and Classification

-   **Name:** Transactional Outbox
    
-   **Classification:** Reliability & Integration Pattern (data-to-event consistency)
    

## Intent

Guarantee that **a state change and its corresponding message/event are recorded atomically** by writing both to the **same database transaction**. A background **relay** (or CDC) later publishes the outbox record to a message broker. This prevents the “updated DB but lost the event” failure mode.

## Also Known As

-   Outbox Pattern
    
-   Reliable Event Publishing
    
-   DB as Source of Events (with CDC)
    

## Motivation (Forces)

-   **Dual-write dilemma:** Updating OLTP DB and publishing to Kafka/Rabbit/SNS cannot be made atomic without 2PC.
    
-   **At-least-once delivery:** Brokers and networks can fail; you need safe **retries** without double–applying effects.
    
-   **Operational simplicity:** Keep domain write ACID; push integration complexity to a controlled relay/CDC.
    
-   **Ordering:** Preserve **per-aggregate** ordering by keying events and relaying in order.
    

## Applicability

Use when:

-   Services have **Database per Service** and must emit events/commands after local commits.
    
-   2PC is unavailable or undesirable.
    
-   You can tolerate **at-least-once** delivery to the broker and design **idempotent** consumers.
    

Avoid or modify when:

-   You truly need atomic, synchronous cross-system updates (rare; consider redesign or a specialized store).
    
-   Ultra-low-latency event publication where an outbox relay would be the bottleneck (then consider CDC with minimal lag).
    

## Structure

```pgsql
(Tx boundary)
Client → Command Handler → Domain DB write
                             │
                             └── Append Outbox row (same Tx)
                                    │
                          ┌─────────▼─────────┐
                          │   Outbox Table    │  (durable)
                          └─────────┬─────────┘
                                    │   poll / stream
                          ┌─────────▼─────────┐
                          │  Outbox Relay     │→ publish to broker (Kafka/Rabbit/…)
                          └─────────┬─────────┘
                                    │
                             (offset/ack & mark sent)
```

## Participants

-   **Command Handler / Service Logic:** Executes local transaction.
    
-   **Domain DB:** System-of-record tables.
    
-   **Outbox Table:** Append-only (or statused) table for events/messages.
    
-   **Outbox Relay / Publisher:** Polls/locks rows, publishes to broker, marks sent (or lets CDC handle).
    
-   **Message Broker:** Kafka/Rabbit/SNS/etc.
    
-   **Consumers:** Downstream services, designed to be **idempotent**.
    

## Collaboration

1.  In a **single DB transaction**, write domain change **and** an **outbox record**.
    
2.  Commit → both persisted or none.
    
3.  Relay (or **CDC** like Debezium) reads new outbox records.
    
4.  Publish to broker with **partition key** (e.g., aggregateId).
    
5.  Mark outbox as **SENT** (or rely on CDC offsets).
    
6.  Consumers process; duplicates are possible → use **idempotency keys**.
    

## Consequences

**Benefits**

-   Eliminates lost-messages-after-commit.
    
-   Preserves per-aggregate ordering (by key).
    
-   Works with any DB/broker; no 2PC.
    
-   Clear operational surface (monitor, replay, DLQ).
    

**Liabilities**

-   Extra moving piece (relay/CDC) and a table that needs **retention**.
    
-   **At-least-once** semantics → duplicates downstream.
    
-   Requires **backpressure** control (batching, rate, lag).
    
-   Careful handling of **large payloads** and PII in outbox rows.
    

## Implementation

1.  **Schema**
    
    -   Columns: `event_id (UUID)`, `aggregate_type`, `aggregate_id`, `event_type`, `payload (JSON)`, `occurred_at`, `status (PENDING|SENT|FAILED)`, `attempts`, `available_at`, optional `headers`, `sequence`.
        
    -   Index by `(status, available_at, id)` and `(aggregate_id)`.
        
2.  **Write path**
    
    -   In the **same transaction** as domain write, insert an outbox row.
        
    -   Keep payload compact & versioned (e.g., `{ "type":"OrderPlaced", "v":1, ... }`).
        
3.  **Relay**
    
    -   Poll `PENDING AND available_at <= now()` with `FOR UPDATE SKIP LOCKED`.
        
    -   Publish synchronously or with callbacks; on success mark `SENT`.
        
    -   On failure, increment `attempts`, set `available_at = now()+backoff`, optionally write `last_error`.
        
    -   Partition by `aggregate_id` to keep order per entity.
        
4.  **CDC Alternative**
    
    -   Use **Debezium** (or logical replication) to stream outbox inserts to Kafka; no in-app poller.
        
    -   Keep outbox **append-only** and handle retention with TTL/partitioning.
        
5.  **Retention & Replay**
    
    -   Periodically purge/archive **SENT** rows beyond retention window.
        
    -   Provide a small **replayer** (by time range/event type) for ops.
        
6.  **Idempotency & Ordering**
    
    -   Include `event_id` (UUID). Consumers store processed IDs (or use transactional consume/process).
        
    -   Choose keys to ensure causal order (aggregate or saga ID).
        
7.  **Observability & Ops**
    
    -   Metrics: queue depth (pending count), lag (oldest pending age), attempts, publish rate, failure rate.
        
    -   Alerts on age/size thresholds.
        
    -   DLQ for poison events after N attempts.
        

---

## Sample Code (Java, Spring Boot 3 + JPA + Kafka)

> Minimal, production-leaning implementation using **poller** style. Replace the poller with **CDC** if preferred.

### `pom.xml` (snippets)

```xml
<dependencies>
  <dependency>
    <groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-web</artifactId>
  </dependency>
  <dependency>
    <groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-data-jpa</artifactId>
  </dependency>
  <dependency>
    <groupId>org.postgresql</groupId><artifactId>postgresql</artifactId>
  </dependency>
  <dependency>
    <groupId>org.springframework.kafka</groupId><artifactId>spring-kafka</artifactId>
  </dependency>
  <dependency>
    <groupId>com.fasterxml.jackson.core</groupId><artifactId>jackson-databind</artifactId>
  </dependency>
</dependencies>
```

### `application.properties`

```properties
spring.datasource.url=jdbc:postgresql://orders-db:5432/orders
spring.datasource.username=orders_svc
spring.datasource.password=secret
spring.jpa.hibernate.ddl-auto=validate
spring.jpa.open-in-view=false

spring.kafka.bootstrap-servers=kafka:9092
app.topic.orders.placed=orders.placed.v1
```

### SQL migration (Postgres)

```sql
-- outbox table
create table if not exists outbox_event (
  event_id uuid primary key,
  aggregate_type varchar(64) not null,
  aggregate_id uuid not null,
  event_type varchar(64) not null,
  payload jsonb not null,
  headers jsonb not null default '{}'::jsonb,
  sequence bigint not null default 0,
  status varchar(16) not null default 'PENDING',
  attempts int not null default 0,
  available_at timestamptz not null default now(),
  occurred_at timestamptz not null default now()
);

create index if not exists idx_outbox_pending on outbox_event(status, available_at, event_id);
create index if not exists idx_outbox_agg on outbox_event(aggregate_id);

-- domain tables (example)
create table if not exists customer_order (
  id uuid primary key,
  customer_id uuid not null,
  total_cents bigint not null,
  created_at timestamptz not null default now()
);
```

### Domain & Outbox entities

```java
// Order.java
package outbox.sample.domain;

import jakarta.persistence.*;
import java.time.OffsetDateTime;
import java.util.UUID;

@Entity @Table(name="customer_order")
public class Order {
  @Id private UUID id;
  @Column(nullable=false) private UUID customerId;
  @Column(nullable=false) private long totalCents;
  @Column(nullable=false) private OffsetDateTime createdAt = OffsetDateTime.now();

  protected Order() {}
  public static Order create(UUID customerId, long totalCents) {
    Order o = new Order(); o.id = UUID.randomUUID();
    o.customerId = customerId; o.totalCents = totalCents; return o;
  }
  public UUID getId() { return id; }
  public UUID getCustomerId() { return customerId; }
  public long getTotalCents() { return totalCents; }
}
```

```java
// OutboxEvent.java
package outbox.sample.outbox;

import jakarta.persistence.*;
import java.time.OffsetDateTime;
import java.util.UUID;

@Entity @Table(name="outbox_event")
public class OutboxEvent {
  @Id @Column(name="event_id") private UUID eventId;
  private String aggregateType;
  private UUID aggregateId;
  private String eventType;
  @Lob @Column(columnDefinition="jsonb") private String payload;
  @Lob @Column(columnDefinition="jsonb") private String headers = "{}";
  private long sequence;
  private String status = "PENDING"; // PENDING,SENT,FAILED
  private int attempts = 0;
  private OffsetDateTime availableAt = OffsetDateTime.now();
  private OffsetDateTime occurredAt = OffsetDateTime.now();
  @Version private long version; // optimistic lock

  protected OutboxEvent() {}
  public OutboxEvent(UUID id, String aggType, UUID aggId, String type, String payload, long sequence) {
    this.eventId = id; this.aggregateType = aggType; this.aggregateId = aggId;
    this.eventType = type; this.payload = payload; this.sequence = sequence;
  }
  // getters/setters...
  public void markSent(){ this.status="SENT"; }
  public void backoff(java.time.Duration d){ this.status="PENDING"; this.attempts++; this.availableAt = OffsetDateTime.now().plus(d); }
}
```

### Repositories

```java
// OrderRepository.java
package outbox.sample.domain;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.UUID;
public interface OrderRepository extends JpaRepository<Order, UUID> {}
```

```java
// OutboxRepository.java
package outbox.sample.outbox;

import org.springframework.data.jpa.repository.*;
import org.springframework.data.repository.query.Param;
import java.util.List;

public interface OutboxRepository extends JpaRepository<OutboxEvent, java.util.UUID> {

  // Claim next batch using SKIP LOCKED to avoid duplicate publishers
  @Query(value = """
      select * from outbox_event
      where status = 'PENDING' and available_at <= now()
      order by occurred_at asc
      limit :batch
      for update skip locked
      """, nativeQuery = true)
  List<OutboxEvent> lockNextBatch(@Param("batch") int batch);
}
```

### Application service (write domain + outbox in one Tx)

```java
// PlaceOrderService.java
package outbox.sample.app;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import outbox.sample.domain.*;
import outbox.sample.outbox.OutboxEvent;

import java.util.Map;
import java.util.UUID;

@Service
public class PlaceOrderService {
  private final OrderRepository orders;
  private final outbox.sample.outbox.OutboxRepository outbox;
  private final ObjectMapper json;

  public PlaceOrderService(OrderRepository orders, outbox.sample.outbox.OutboxRepository outbox, ObjectMapper json) {
    this.orders = orders; this.outbox = outbox; this.json = json;
  }

  @Transactional
  public UUID place(UUID customerId, long totalCents) {
    var order = Order.create(customerId, totalCents);
    orders.save(order);

    // outbox in SAME transaction
    try {
      var payload = json.writeValueAsString(Map.of(
          "orderId", order.getId().toString(),
          "customerId", customerId.toString(),
          "totalCents", totalCents,
          "v", 1
      ));
      var evt = new OutboxEvent(UUID.randomUUID(), "Order", order.getId(), "OrderPlaced", payload, 0L);
      outbox.save(evt);
    } catch (Exception e) {
      throw new RuntimeException("serialize event failed", e);
    }
    return order.getId();
  }
}
```

### Outbox relay/publisher (Kafka)

```java
// OutboxPublisher.java
package outbox.sample.outbox;

import org.apache.kafka.clients.producer.RecordMetadata;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.List;

@Component
public class OutboxPublisher {

  private final OutboxRepository repo;
  private final KafkaTemplate<String, String> kafka;
  private final String topic = "orders.placed.v1";

  public OutboxPublisher(OutboxRepository repo, KafkaTemplate<String, String> kafka) {
    this.repo = repo; this.kafka = kafka;
  }

  @Scheduled(fixedDelay = 300) // tune to your throughput
  public void publish() {
    List<OutboxEvent> batch = repo.lockNextBatch(200); // in a Tx due to @Transactional proxy on query
    for (OutboxEvent e : batch) {
      try {
        // Partition by aggregateId to preserve per-order ordering
        RecordMetadata md = kafka.send(topic, e.getAggregateId().toString(), e.getPayload()).get();
        e.markSent();
      } catch (Exception ex) {
        // Exponential backoff with cap
        e.backoff(Duration.ofSeconds(Math.min(60, (long)Math.pow(2, Math.min(10, e.getAttempts()+1)))));
        // Optionally set last error message in headers
      }
      repo.save(e);
    }
  }
}
```

### Consumer-side idempotency sketch (downstream service)

```sql
create table if not exists processed_event (
  event_id uuid primary key,
  processed_at timestamptz not null default now()
);
```

```java
// IdempotentConsumer.java
package downstream;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

@Component
public class IdempotentConsumer {
  private final JdbcTemplate jdbc;
  public IdempotentConsumer(JdbcTemplate jdbc){ this.jdbc = jdbc; }

  @KafkaListener(topics = "orders.placed.v1", groupId = "billing")
  public void onMessage(String payload, org.apache.kafka.clients.consumer.ConsumerRecord<String,String> rec) {
    java.util.UUID eventId = java.util.UUID.fromString(
        new com.fasterxml.jackson.databind.ObjectMapper().readTree(payload).path("eventId").asText(null)
    );
    if (eventId != null) {
      int inserted = jdbc.update("insert into processed_event(event_id) values (?) on conflict do nothing", eventId);
      if (inserted == 0) return; // duplicate → already processed
    }
    // proceed with handling; ensure local transaction boundaries
  }
}
```

> Notes
> 
> -   For **CDC**: make the outbox **append-only**, let **Debezium** stream it to Kafka, and drop the poller.
>     
> -   Make sure **payloads** contain an `eventId` for downstream de-dup. If not embedded, use headers.
>     

---

## Known Uses

-   Common across e-commerce, payments, logistics where state changes must reliably emit events.
    
-   Popularized by community write-ups and frameworks; widely used with **Debezium + Kafka** or **Eventuate** variants in Java ecosystems.
    

## Related Patterns

-   **Change Data Capture (CDC):** Alternative transport for outbox rows.
    
-   **Idempotent Consumer:** Safe processing under at-least-once delivery.
    
-   **Database per Service:** Enables local atomic write + outbox.
    
-   **Saga:** Use outbox events to drive long-running workflows.
    
-   **Dead Letter Queue:** Park poison events after retry exhaustion.
    
-   **CQRS / Read Models:** Downstream projections built from outbox events.

