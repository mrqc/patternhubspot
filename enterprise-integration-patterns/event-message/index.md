# Event Message (Enterprise Integration Pattern)

## Pattern Name and Classification

**Name:** Event Message  
**Classification:** Enterprise Integration Pattern (Messaging / Notification / Pub-Sub)

---

## Intent

Broadcast a **statement of fact**—that **something already happened**—so interested parties can **react asynchronously** without coupling to the producer’s control flow.

---

## Also Known As

-   Domain Event (when expressed in domain language)
    
-   Notification Message
    
-   Event Notification
    

---

## Motivation (Forces)

-   Producers want to **announce** changes (e.g., *OrderPlaced*, *PaymentAuthorized*) without dictating who must react.
    
-   Consumers need **loose coupling**, **scalability**, and **independent evolution**.
    
-   Messaging infrastructures deliver **at-least-once**, so consumers must be **idempotent**.
    
-   Events are **immutable** history; they enable **audit**, **analytics**, **projections**, and **integration**.
    

Tensions to balance:

-   **Event granularity** (coarse lifecycle vs fine-grained changes).
    
-   **Schema evolution** vs long-lived consumers.
    
-   **Ordering**: global ordering rarely exists—usually only per key/partition.
    
-   **Event vs Command**: events are descriptive (“happened”), not imperative (“do X”).
    

---

## Applicability

Use Event Messages when:

-   Multiple downstream systems must **react** to the same fact (fan-out).
    
-   You build **read models/projections** (CQRS), trigger workflows, or integrate external partners.
    
-   You need **temporal history** for audit or time-travel analytics.
    

Avoid or limit when:

-   You need to **instruct** a specific receiver → use a **Command Message**.
    
-   A consumer needs **strong consistency** in the request path → use synchronous RPC with timeouts/circuit breakers.
    
-   You’re leaking **internal, unstable** data—publish a stable **Published Language** instead.
    

---

## Structure

-   **Event Envelope:** headers (type, version, id, timestamp, correlation/causation, partition key, tenant, producer), payload.
    
-   **Event Bus/Topic:** Kafka, RabbitMQ, SNS/SQS, NATS, Pulsar, etc.
    
-   **Producers:** Publish immutable events after committing business state.
    
-   **Consumers:** Subscribe and process idempotently; may update projections or trigger actions.
    
-   **Schema Registry (optional):** Manage versions (Avro/Protobuf/JSON Schema).
    

---

## Participants

-   **Event Producer (Owner of the fact)**
    
-   **Event Broker / Channel**
    
-   **Event Consumer(s)**
    
-   **Schema/Contract Artifacts** (OpenAPI/AsyncAPI/Avro/Protobuf/JSON Schema)
    
-   **Outbox (optional)** to avoid dual-writes when using a database
    

---

## Collaboration

1.  Producer completes state change and **emits an event** (often via **Transactional Outbox**).
    
2.  Broker delivers the event to all **subscribed consumers** (at-least-once).
    
3.  Consumers **process idempotently** and update their state/read models or invoke further actions.
    
4.  Failures are retried; poison messages go to **DLQ**.
    
5.  New consumers can **replay** from retained history to (re)build projections.
    

---

## Consequences

**Benefits**

-   **Loose coupling & scalability** with one-to-many fan-out.
    
-   **Auditable history** of what happened.
    
-   Enables **flexible projections** and analytics without touching writers.
    
-   New consumers can be added **without changing producers**.
    

**Liabilities**

-   **Eventual consistency** (no immediate coordination).
    
-   **Duplication** requires idempotent consumers.
    
-   **Schema/versioning** governance is essential.
    
-   **Semantic drift** if events mirror internal tables instead of domain facts.
    

---

## Implementation

**Design guidelines**

-   Name events in **past tense** (`OrderPlaced`, `InvoiceIssued`).
    
-   Include **minimal, stable facts**; avoid internal IDs that leak non-authoritative models.
    
-   Envelope fields to include:
    
    -   `eventId` (UUID), `eventType` (string), `version` (int), `occurredAt` (UTC),
        
    -   `aggregateId` / `partitionKey`, `correlationId`, `causationId`, `producer`.
        
-   **Schema evolution:** additive fields within major; breaking changes → new event type or major version.
    
-   **Partitioning:** by `aggregateId` to preserve per-entity order.
    
-   **Idempotency:** consumers track `(aggregateId, sequence)` or `eventId`.
    
-   **Outbox pattern:** write event to outbox in the same DB tx; a relay/CDC publishes to the bus.
    
-   **Security/PII:** only include allowed fields; consider hashing/pseudonyms.
    
-   **Observability:** metrics (produce/consume lag), tracing with correlation/causation IDs.
    

---

## Sample Code (Java – event envelope, producer, idempotent consumer)

The code is transport-agnostic; wire `EventBus` to Kafka/SNS/etc.

```java
import java.time.Instant;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

// -------- Envelope & Event DTOs --------
public final class EventEnvelope<T> {
    public final String eventId;        // UUID v4
    public final String eventType;      // e.g., "orders.order_placed"
    public final int version;           // schema version
    public final Instant occurredAt;    // UTC
    public final String aggregateId;    // partition key
    public final String correlationId;  // trace
    public final String causationId;    // parent event or command
    public final Map<String, String> headers;
    public final T payload;

    private EventEnvelope(String eventId, String eventType, int version,
                          Instant occurredAt, String aggregateId,
                          String correlationId, String causationId,
                          Map<String, String> headers, T payload) {
        this.eventId = eventId;
        this.eventType = eventType;
        this.version = version;
        this.occurredAt = occurredAt;
        this.aggregateId = aggregateId;
        this.correlationId = correlationId;
        this.causationId = causationId;
        this.headers = headers == null ? Map.of() : Map.copyOf(headers);
        this.payload = Objects.requireNonNull(payload);
    }

    public static <T> EventEnvelope<T> of(String eventType, int version, String aggregateId, T payload) {
        return new EventEnvelope<>(
            UUID.randomUUID().toString(),
            eventType,
            version,
            Instant.now(),
            aggregateId,
            UUID.randomUUID().toString(),
            null,
            Map.of(),
            payload
        );
    }

    public EventEnvelope<T> withCorrelation(String correlationId, String causationId) {
        return new EventEnvelope<>(eventId, eventType, version, occurredAt, aggregateId,
                correlationId, causationId, headers, payload);
    }
}

// Domain event payload (Published Language)
public record OrderPlacedV1(String orderId, String customerId, java.math.BigDecimal total, String currency) {}
```

```java
// -------- Event Bus ports --------
public interface EventBus {
    <T> void publish(EventEnvelope<T> event);  // serialize & send to topic by eventType or aggregate
}

public interface EventHandler<T> {
    void onEvent(EventEnvelope<T> event) throws Exception;
}
```

```java
// -------- Producer example (after domain change committed) --------
public final class OrdersEventPublisher {
    private final EventBus bus;
    public OrdersEventPublisher(EventBus bus) { this.bus = bus; }

    public void orderPlaced(String orderId, String customerId, java.math.BigDecimal total, String currency,
                            String correlationId, String causationId) {
        var payload = new OrderPlacedV1(orderId, customerId, total, currency);
        var evt = EventEnvelope.of("orders.order_placed", 1, orderId, payload)
                .withCorrelation(correlationId, causationId);
        bus.publish(evt);
    }
}
```

```java
// -------- Idempotent consumer (projection) --------
import java.util.concurrent.ConcurrentHashMap;

public final class OrdersProjectionHandler implements EventHandler<OrderPlacedV1> {
    // tracks last processed event per aggregate to ensure idempotency
    private final ConcurrentHashMap<String, String> lastEventForAggregate = new ConcurrentHashMap<>();
    private final OrdersReadModelDao dao;

    public OrdersProjectionHandler(OrdersReadModelDao dao) { this.dao = dao; }

    @Override
    public void onEvent(EventEnvelope<OrderPlacedV1> e) {
        // idempotency: same eventId processed already?
        String key = e.aggregateId();
        String prev = lastEventForAggregate.putIfAbsent(key, e.eventId());
        if (prev != null && prev.equals(e.eventId())) {
            return; // duplicate delivery
        }

        var p = e.payload();
        dao.upsertOrder(p.orderId(), p.customerId(), p.total(), p.currency, e.occurredAt());
        // note: in production you should persist idempotency in the same tx as the upsert
    }

    public interface OrdersReadModelDao {
        void upsertOrder(String orderId, String customerId, java.math.BigDecimal total, String currency, java.time.Instant placedAt);
    }
}
```

```java
// -------- Minimal Kafka adapter (illustrative) --------
// (Assumes you have serializers; error handling omitted for brevity)
import org.apache.kafka.clients.producer.*;
import org.apache.kafka.common.serialization.StringSerializer;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.Properties;

public final class KafkaEventBus implements EventBus {
    private final Producer<String, String> producer;
    private final ObjectMapper json = new ObjectMapper();
    private final String topic; // e.g., "orders.events"

    public KafkaEventBus(String bootstrap, String topic) {
        Properties pp = new Properties();
        pp.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, bootstrap);
        pp.put(ProducerConfig.ACKS_CONFIG, "all");
        this.producer = new KafkaProducer<>(pp, new StringSerializer(), new StringSerializer());
        this.topic = topic;
    }

    @Override
    public <T> void publish(EventEnvelope<T> event) {
        try {
            String payload = json.writeValueAsString(event);
            ProducerRecord<String, String> rec =
                    new ProducerRecord<>(topic, event.aggregateId(), payload);
            rec.headers().add("event-type", event.eventType().getBytes());
            rec.headers().add("event-version", String.valueOf(event.version()).getBytes());
            rec.headers().add("event-id", event.eventId().getBytes());
            rec.headers().add("occurred-at", event.occurredAt().toString().getBytes());
            producer.send(rec);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }
}
```

**Notes**

-   Use a **schema registry** (Avro/Protobuf) for stronger contracts.
    
-   For **exactly-once** illusions, combine idempotent producer, transactional writes, and consumer-side dedup—but design for **at-least-once**.
    

---

## Known Uses

-   **E-commerce:** `OrderPlaced`, `OrderShipped`, `InventoryReserved` events to drive fulfillment and notifications.
    
-   **Payments:** `PaymentAuthorized`, `PaymentCaptured` for ledgers, receipts, and risk analytics.
    
-   **User/IAM:** `UserRegistered`, `RoleAssigned` to sync directories and audit logs.
    
-   **Data/Analytics:** Event streams feed data lakes/warehouses for real-time dashboards.
    
-   **IoT:** Device telemetry as events for alerting and ML features.
    

---

## Related Patterns

-   **Command Message:** Imperative request; often precedes a resulting Event Message.
    
-   **Transactional Outbox:** Reliable publishing of events after DB commit.
    
-   **Event-Carried State Transfer:** Events carry enough state to update read models.
    
-   **Event Sourcing:** Persist events as the source of truth (different write model).
    
-   **Message Broker / Pub-Sub Channel:** Transport underpinning event distribution.
    
-   **Idempotent Receiver / Dead Letter Channel:** Robust consumption and failure handling.
    
-   **Content Enricher / Content-Based Router:** Downstream patterns acting on events.
    

---
