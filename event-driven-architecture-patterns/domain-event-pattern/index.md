# Domain Event — Event-Driven Architecture Pattern

## Pattern Name and Classification

**Name:** Domain Event  
**Classification:** Event design & messaging pattern (EDA/DDD); immutable **fact** emitted by a bounded context to signal a **meaningful business occurrence**.

## Intent

Explicitly publish **business-significant facts** (e.g., *OrderPlaced*, *PaymentAuthorized*) as immutable, time-ordered messages so other services can **react** asynchronously without tight coupling to the writer’s data or workflow.

## Also Known As

-   Business Event
    
-   Integration Event (when tailored for external consumers)
    
-   Fact (in event-sourcing literature)
    

## Motivation (Forces)

-   **Decoupling:** Consumers subscribe to *what happened*, not to CRUD operations or sync APIs.
    
-   **Clarity of intent:** Distinguish **why** a change occurred from low-level row changes (CDC).
    
-   **Evolution:** Schemas and consumers evolve independently via **versioned event contracts**.
    
-   **Scalability & resilience:** Asynchronous fan-out; producers aren’t blocked by slow consumers.
    

**Forces to balance**

-   Choosing the **right granularity** (events too fine → chatter; too coarse → ambiguous).
    
-   **Schema evolution** and compatibility guarantees.
    
-   **Truth vs. derivatives:** Events are facts, not commands; avoid hiding corrections.
    
-   **Ordering and idempotency** constraints across partitions.
    

## Applicability

Use Domain Events when:

-   Multiple services (billing, fulfillment, analytics) must **react** to the same business fact.
    
-   You want **auditability** and reproducible state transitions.
    
-   You aim to avoid **dual-writes** (use Transactional Outbox) while building reactive integrations.
    

Avoid or limit when:

-   The only need is raw data replication → consider **Change Data Capture**.
    
-   A synchronous response is mandatory → consider **Request–Reply** or direct API.
    

## Structure

```pgsql
+------------------+      +------------------+      +-------------------+
|  Producer (BC)   | ---> |  Event Channel   | ---> |  Subscribers ...  |
|  emits Domain    |      |  (topic/queue)   |      |  react & update   |
|  Events          |      |                  |      |  their state      |
+------------------+      +------------------+      +-------------------+

Event = { type, version, id, occurredAt, aggregateId, payload, headers }
```

## Participants

-   **Producer (bounded context):** Emits events at key state transitions.
    
-   **Domain Event:** Immutable message (type + version + payload + metadata).
    
-   **Event Channel:** Topic/queue/stream transporting events to many consumers.
    
-   **Consumers/Subscribers:** Services reacting (side effects, read models, workflows).
    
-   **Schema Registry (optional):** Controls compatibility and discovery.
    
-   **Outbox/Inbox Stores:** Ensure reliable publish/consume and idempotency.
    

## Collaboration

1.  Producer executes a local transaction that changes domain state and **records** a domain event (often to an **outbox**).
    
2.  A publisher **ships** the event to the event channel.
    
3.  Subscribers **consume** the event, enforce **idempotency**, and apply local side effects.
    
4.  Further events may be emitted (choreography saga, projections, etc.).
    

## Consequences

**Benefits**

-   Clean **contract of intent**; avoids leaking internal schemas.
    
-   Natural **pub/sub** fan-out; easier integrations and analytics.
    
-   Supports **event sourcing** and temporal analysis.
    
-   Fosters **loosely coupled** services and independent deployments.
    

**Liabilities**

-   Requires **discipline** in naming, versioning, and backward compatibility.
    
-   **Eventual consistency**: consumers see facts after a delay.
    
-   Once published, events are **immutable** (use compensating events, not edits).
    
-   **Ordering** is typically per key/partition; cross-aggregate ordering is not guaranteed.
    

## Implementation

-   **Design events first:** Name by business past-tense (*OrderPlaced*), include **aggregateId**, **occurredAt** (UTC), and minimal, well-defined **payload**.
    
-   **Envelope & headers:**
    
    -   `eventType`, `eventVersion`, `messageId` (UUID), `occurredAt`, `aggregateType`, `aggregateId`, `correlationId`, `causationId`, `producer`, `schemaVersion`.
        
-   **Serialization:** JSON/Avro/Protobuf; prefer registry-backed schemas with compatibility rules.
    
-   **Reliability:**
    
    -   **Transactional Outbox** to atomically persist domain change + event record.
        
    -   Consumers implement **Idempotent Receiver** (dedupe by `messageId` or natural key).
        
-   **Topic design:** Version in the **type**, not (necessarily) the topic name; e.g., topic `orders.events` with event `orders.order.placed.v1`, or topic-per-event `orders.order.placed.v1`.
    
-   **Versioning:** Backward compatible (`v1` → `v2`) where possible; document **deprecation** windows.
    
-   **Security:** Redact PII; sign or authenticate messages; use per-topic ACLs.
    
-   **Observability:** Trace headers (`traceparent`), metrics for publish latency, consumer lag, error rates.
    

---

## Sample Code (Java)

### A) Event Model & Envelope

```java
public record EventEnvelope<T>(
    String eventType, String eventVersion,
    String aggregateType, String aggregateId,
    String messageId, long occurredAt,
    String correlationId, String causationId,
    T payload
) {
  public static <T> EventEnvelope<T> of(String type, String version, String aggType, String aggId,
                                        String correlationId, String causationId, T payload) {
    return new EventEnvelope<>(
        type, version, aggType, aggId,
        java.util.UUID.randomUUID().toString(),
        java.time.Instant.now().toEpochMilli(),
        correlationId, causationId, payload);
  }
}

// A concrete domain event payload
public record OrderPlaced(String orderId, String customerId, java.util.List<Line> lines, long totalCents, String currency) {
  public record Line(String sku, int qty, long priceCents) {}
}
```

### B) Producer with Transactional Outbox (Spring/JPA + Kafka)

```java
// build.gradle: spring-boot-starter-data-jpa, spring-kafka, jackson
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.persistence.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Entity
@Table(name = "outbox_events")
class OutboxEvent {
  @Id String id;
  String topic; @Lob String payloadJson; String key; java.time.Instant occurredAt;
  String eventType; String eventVersion; String aggregateType; String aggregateId;
  boolean dispatched;
}

interface OutboxRepo extends org.springframework.data.jpa.repository.JpaRepository<OutboxEvent, String> {
  java.util.List<OutboxEvent> findTop100ByDispatchedFalseOrderByOccurredAtAsc();
}

@Service
public class OrderCommandHandler {
  private final EntityManager em;
  private final OutboxRepo outbox;
  private final ObjectMapper json = new ObjectMapper();

  public OrderCommandHandler(EntityManager em, OutboxRepo outbox) { this.em = em; this.outbox = outbox; }

  @Transactional
  public void placeOrder(String orderId, String customerId, java.util.List<OrderPlaced.Line> lines) {
    // 1) Domain write
    em.persist(new OrderEntity(orderId, "PLACED", customerId, lines));

    // 2) Create Domain Event (v1)
    long total = lines.stream().mapToLong(l -> l.qty() * l.priceCents()).sum();
    var evt = new OrderPlaced(orderId, customerId, lines, total, "EUR");
    var env = EventEnvelope.of("orders.order.placed", "v1", "Order", orderId, orderId, orderId, evt);

    // 3) Stage to Outbox within same TX
    OutboxEvent ob = new OutboxEvent();
    ob.id = env.messageId();
    ob.topic = "orders.events.v1";
    ob.key = orderId;
    ob.payloadJson = write(env);
    ob.occurredAt = java.time.Instant.ofEpochMilli(env.occurredAt());
    ob.eventType = env.eventType(); ob.eventVersion = env.eventVersion();
    ob.aggregateType = env.aggregateType(); ob.aggregateId = env.aggregateId();
    ob.dispatched = false;
    outbox.save(ob);
  }

  private String write(Object o) { try { return json.writeValueAsString(o); } catch (Exception e) { throw new RuntimeException(e);} }

  @Entity static class OrderEntity { @Id String id; String status; String customerId; @Transient java.util.List<OrderPlaced.Line> lines;
    OrderEntity(){} OrderEntity(String id,String st,String c,java.util.List<OrderPlaced.Line> ls){this.id=id;this.status=st;this.customerId=c;this.lines=ls;} }
}
```

```java
// Publisher: ships outbox rows to Kafka (idempotent)
import org.apache.kafka.clients.producer.ProducerRecord;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
class OutboxPublisher {
  private final OutboxRepo repo;
  private final KafkaTemplate<String, byte[]> kafka;

  OutboxPublisher(OutboxRepo repo, KafkaTemplate<String, byte[]> kafka){ this.repo=repo; this.kafka=kafka; }

  @Scheduled(fixedDelay = 300)
  public void publish() {
    var batch = repo.findTop100ByDispatchedFalseOrderByOccurredAtAsc();
    for (var e : batch) {
      try {
        var rec = new ProducerRecord<>(e.topic, e.key, e.payloadJson.getBytes(java.nio.charset.StandardCharsets.UTF_8));
        kafka.send(rec).get(); // sync for brevity
        e.dispatched = true; repo.save(e);
      } catch (Exception ex) { /* leave undispatched to retry; add attempts/backoff in prod */ }
    }
  }
}
```

### C) Consumer (Idempotent Receiver)

```java
// build.gradle: spring-kafka, jackson, spring-data-redis (or DB) for idempotency
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

@Component
public class OrderProjectionConsumer {

  private final ObjectMapper json = new ObjectMapper();
  private final StringRedisTemplate redis;

  public OrderProjectionConsumer(StringRedisTemplate redis) { this.redis = redis; }

  @KafkaListener(topics = "orders.events.v1", groupId = "orders-projection")
  public void onEvent(byte[] bytes) throws Exception {
    var env = json.readValue(bytes, new com.fasterxml.jackson.core.type.TypeReference<EventEnvelope<OrderPlaced>>(){});

    // Idempotency: skip if messageId already processed
    String key = "dedupe:" + env.messageId();
    Boolean first = redis.opsForValue().setIfAbsent(key, "1");
    if (first == null || !first) return; // already processed
    redis.expire(key, java.time.Duration.ofHours(6)); // TTL

    if (env.eventType().equals("orders.order.placed")) {
      // Update a read model, send emails, etc.
      project(env.payload());
    }
  }

  private void project(OrderPlaced evt) { /* persist projection */ }
}
```

---

## Known Uses

-   **E-commerce:** `OrderPlaced`, `OrderPaid`, `OrderShipped` feed billing, fulfillment, CRM, analytics.
    
-   **FinTech:** `TransferInitiated`, `FundsReserved`, `SettlementCompleted` coordinate ledger and notifications.
    
-   **Logistics:** `ParcelScanned`, `RouteAssigned`, `DeliveryCompleted` drive tracking UIs and SLA monitors.
    
-   **SaaS:** `UserRegistered`, `SubscriptionRenewed`, `FeatureToggled` power growth, billing, and audit trails.
    

## Related Patterns

-   **Transactional Outbox:** Atomically persist state + event; recommended for producers.
    
-   **Inbox / Idempotent Receiver:** Ensure exactly-once **effects** for consumers.
    
-   **Publish–Subscribe Channel:** Transport for fan-out of domain events.
    
-   **Choreography Saga:** Domain events chain steps across services.
    
-   **Message Translator / Canonical Data Model:** Normalize and evolve event contracts.
    
-   **Change Data Capture (CDC):** Alternative for data-shaped streams; use Domain Events for **intent**.
    
-   **Event Sourcing:** Domain events become the **source of truth**; this pattern also applies when events are derived but not the primary store.
    

> **Rule of thumb:** emit **meaningful business facts**, version them, publish reliably, and design consumers to be idempotent.

