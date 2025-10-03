# Message Bus — Enterprise Integration Pattern

## Pattern Name and Classification

**Name:** Message Bus  
**Classification:** Architectural / Topology pattern (EIP); a logical **publish–subscribe backbone** providing a common contract for events/commands across multiple applications.

## Intent

Provide a **shared communication backbone** with **uniform contracts** (message format, semantics, governance) so distributed applications can publish and subscribe without point-to-point integrations. The bus emphasizes **loose coupling**, **discoverability**, and **evolution** of event flows.

## Also Known As

-   Enterprise Message Bus (EMB)
    
-   Event Bus / Event Backbone
    
-   Service Bus *(overlaps; “ESB” historically implies richer mediation/orchestration)*
    

## Motivation (Forces)

-   **Decoupling:** Avoid N×M connections; producers broadcast once, consumers subscribe.
    
-   **Consistency:** Shared message model (envelope + canonical payload + metadata) across teams.
    
-   **Scalability:** Horizontal fan-out, buffering, and independent scaling of producers/consumers.
    
-   **Evolution:** Schemas versioned centrally; new consumers join without changing producers.
    
-   **Governance/Observability:** Traceability, quotas, contracts, ACLs, SLAs at the bus boundary.
    

**Forces to balance**

-   **Uniformity vs. flexibility:** Canonical models vs. domain autonomy.
    
-   **Smart bus vs. smart endpoints:** Where to place transforms and policies.
    
-   **Delivery guarantees vs. throughput:** At-least-once is typical; exactly-once effects require endpoint design.
    
-   **Schema evolution vs. backward compatibility:** Semver, feature flags, deprecation windows.
    

## Applicability

Use a Message Bus when:

-   Many services/apps must react to **domain events** or **commands** without tight coupling.
    
-   You want **publish once, consume many** with independent lifecycles.
    
-   You need **organization-wide** contracts (naming, schema, headers, retention, DLQ policies).
    
-   New consumers should be onboarded with minimal producer changes.
    
-   You need **auditability** and **replay** (often via a log-based bus).
    

Avoid or limit when:

-   Only a few endpoints interact and a simpler channel suffices.
    
-   Ultra-low latency and tight control favor direct RPC.
    
-   Organizational maturity for **governance** is lacking (risks “topic sprawl”).
    

## Structure

```lua
+-----------+         +-----------------------+         +-----------+
 | Producer1 |  --->   |                       |   --->  | ConsumerA |
 +-----------+         |      MESSAGE BUS       |         +-----------+
 +-----------+         |  - topics/streams      |   --->  +-----------+
 | Producer2 |  --->   |  - contracts & ACLs    |   --->  | ConsumerB |
 +-----------+         |  - schema registry     |         +-----------+
                       |  - metrics & tracing   |
                       +-----------------------+
```

## Participants

-   **Producers:** Publish events/commands to bus topics/streams.
    
-   **Consumers:** Subscribe to topics; use consumer groups for scaling.
    
-   **Bus Core:** Transport (broker/log), security, quotas, retention, DLQ.
    
-   **Contract Layer:** Canonical envelope, schema registry, naming, versioning.
    
-   **Observability:** Metrics (throughput, lag), traces, audit logs.
    
-   **Admin/Governance:** Approvals, topic lifecycle, compatibility checks.
    

## Collaboration

1.  Producer emits a message conforming to the **bus envelope** and **schema** onto a topic (e.g., `orders.created.v1`).
    
2.  Bus persists/replicates the message according to retention/availability policies.
    
3.  Multiple consumers receive it asynchronously (fan-out); competing consumers share a group for scaling.
    
4.  Failures trigger redeliveries, retries, or DLQ per policy.
    
5.  Schemas evolve with compatibility rules; new consumers can replay retained history if needed.
    

## Consequences

**Benefits**

-   Strong temporal and location decoupling; easy to add consumers.
    
-   Centralized **contracts, governance, and observability**.
    
-   Natural support for **event-driven architecture** and **analytics replay** (log-based buses).
    
-   Reduces integration proliferation and cycle time for new use cases.
    

**Liabilities**

-   Requires **organizational discipline** (naming, schema ownership, versioning).
    
-   The bus becomes **critical infrastructure** (operations, cost, capacity planning).
    
-   Risk of “**accidental ESB**” if too much logic is centralized.
    
-   **Ordering** and **exactly-once delivery** remain hard; endpoints must ensure **exactly-once effects** (idempotency).
    
-   Potential **vendor lock-in** if bus-specific features leak into contracts.
    

## Implementation

-   **Choose transport model:**
    
    -   **Log-based** (Apache Kafka, Pulsar): high throughput, partitions, retention + replay, compaction.
        
    -   **Broker-based** (RabbitMQ/AMQP, JMS/Artemis, IBM MQ): classic queues/topics with flexible routing.
        
    -   **Lightweight event buses** (NATS, Redis Streams) for simpler needs.
        
-   **Define bus contracts:**
    
    -   **Topic naming:** `<domain>.<entity>.<event>.<version>` (e.g., `orders.order.created.v1`).
        
    -   **Envelope headers:** `messageId`, `eventType`, `eventVersion`, `occurredAt`, `correlationId`, `causationId`, `producer`, `tenant`, `schemaRef`.
        
    -   **Payload:** Avro/Protobuf/JSON with a **schema registry** and compatibility rules (BACKWARD by default).
        
-   **Delivery semantics:** Assume **at-least-once**; implement **Idempotent Receiver** and **Transactional Outbox**.
    
-   **Retry/DLQ:** Exponential backoff; parking-lot topics; dead-letter with failure metadata.
    
-   **Security:** mTLS/OAuth2, per-topic ACLs, encryption at rest, multi-tenant isolation.
    
-   **Observability:** Lag, consumer health, end-to-end tracing (propagate `traceparent`).
    
-   **Data retention:** Hot retention for nearline consumers; compacted topics for latest state.
    
-   **Compatibility & versioning:** Introduce `v{n+1}` topics for breaking changes; deprecate old versions with clear migration windows.
    
-   **Multi-region/DR:** Mirror/replicate topics; consider write locality & conflict strategy.
    

## Sample Code (Java)

### A) Canonical Bus API (library-level facade) + Kafka-based implementation

```java
// API visible to services (transport-agnostic)
public interface MessageBus {
    void publish(BusMessage message);
    void publish(String topic, String key, Object payload, BusHeaders headers);
}

public record BusHeaders(
        String messageId,
        String eventType,
        String eventVersion,
        String occurredAt,     // ISO-8601
        String correlationId,
        String causationId,
        String producer,
        String schemaRef,
        Map<String,String> extra
) {
    public static BusHeaders of(String eventType, String version, String correlationId, String producer) {
        return new BusHeaders(
            java.util.UUID.randomUUID().toString(),
            eventType,
            version,
            java.time.Instant.now().toString(),
            correlationId,
            correlationId, // or a specific causation id
            producer,
            eventType + ":" + version,
            Map.of()
        );
    }
}

public record BusMessage(String topic, String key, Object payload, BusHeaders headers) { }
```

```java
// Kafka implementation (Spring Kafka)
import org.springframework.kafka.core.KafkaTemplate;
import com.fasterxml.jackson.databind.ObjectMapper;

public class KafkaMessageBus implements MessageBus {
    private final KafkaTemplate<String, byte[]> template;
    private final ObjectMapper mapper;

    public KafkaMessageBus(KafkaTemplate<String, byte[]> template, ObjectMapper mapper) {
        this.template = template;
        this.mapper = mapper;
    }

    @Override
    public void publish(BusMessage message) {
        publish(message.topic(), message.key(), message.payload(), message.headers());
    }

    @Override
    public void publish(String topic, String key, Object payload, BusHeaders headers) {
        try {
            byte[] envelope = mapper.writeValueAsBytes(Map.of(
                "headers", headers,
                "payload", payload
            ));
            template.send(topic, key, envelope);
        } catch (Exception e) {
            throw new RuntimeException("bus publish failed: " + topic, e);
        }
    }
}
```

```java
// Producer usage
public class OrderService {
    private final MessageBus bus;

    public OrderService(MessageBus bus) { this.bus = bus; }

    public void createOrder(CreateOrder cmd) {
        // ... validate, persist (Transactional Outbox recommended) ...
        OrderCreated evt = new OrderCreated(cmd.orderId(), cmd.sku(), cmd.quantity(), "CREATED");

        bus.publish(
            "orders.created.v1",
            evt.orderId(),
            evt,
            BusHeaders.of("orders.order.created", "v1", cmd.correlationId(), "order-service")
        );
    }
}

public record CreateOrder(String orderId, String sku, int quantity, String correlationId) {}
public record OrderCreated(String orderId, String sku, int quantity, String status) {}
```

```java
// Consumer with Idempotent Receiver (Redis SETNX) and tracing propagation
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.data.redis.core.StringRedisTemplate;

public class ShippingConsumer {
    private final StringRedisTemplate redis;

    public ShippingConsumer(StringRedisTemplate redis) { this.redis = redis; }

    @KafkaListener(topics = "orders.created.v1", groupId = "shipping")
    public void onEvent(byte[] envelopeBytes) {
        Map<String,Object> env = parse(envelopeBytes);
        Map<String,Object> headers = (Map<String,Object>) env.get("headers");
        Map<String,Object> payload = (Map<String,Object>) env.get("payload");

        String messageId = (String) headers.get("messageId");
        boolean reserved = Boolean.TRUE.equals(
            redis.opsForValue().setIfAbsent("idem:orders:" + messageId, "1")
        );
        if (!reserved) return; // duplicate

        // do work (idempotent with orderId)
        String orderId = (String) payload.get("orderId");
        allocateShipment(orderId);
    }

    private Map<String,Object> parse(byte[] bytes) { /* Jackson */ return Map.of(); }
    private void allocateShipment(String orderId) { /* ... */ }
}
```

### B) Spring Cloud Stream (binder abstraction) — transport-agnostic

```java
// build.gradle: spring-cloud-stream, spring-cloud-stream-binder-kafka (or rabbit)
@EnableBinding(Processor.class) // legacy; or functional style shown below
@SpringBootApplication
public class BusApp { public static void main(String[] args) { SpringApplication.run(BusApp.class, args); } }

// Functional style beans
@Configuration
class BusFunctions {
    // Producer: publish OrderCreated
    @Bean
    public Supplier<Message<OrderCreated>> orderCreatedSupplier() {
        return () -> MessageBuilder
            .withPayload(new OrderCreated("O-" + System.currentTimeMillis(), "SKU1", 1, "CREATED"))
            .setHeader("eventType", "orders.order.created")
            .setHeader("eventVersion", "v1")
            .build();
    }

    // Consumer: react to OrderCreated
    @Bean
    public Consumer<Message<OrderCreated>> orderCreatedConsumer() {
        return msg -> {
            OrderCreated evt = msg.getPayload();
            // handle event...
        };
    }
}
```

> In both approaches, keep the **envelope contract** stable and version payloads cautiously. For write-side reliability, pair with a **Transactional Outbox**; for read-side safety, use an **Idempotent Receiver**.

## Known Uses

-   **Apache Kafka** as an enterprise event backbone with schema registry and data governance.
    
-   **Apache Pulsar** for multi-tenant, geo-replicated message bus with tiered storage.
    
-   **RabbitMQ** as an organization-wide bus via topic exchanges and consistent naming.
    
-   **Cloud-native buses:** Azure Event Hubs/Service Bus, AWS MSK + Glue Schema Registry, Google Pub/Sub.
    
-   **Large enterprises** implementing business domains as event streams (`customer.created`, `order.fulfilled`) consumed by analytics, search indexing, notifications, and downstream services.
    

## Related Patterns

-   **Publish–Subscribe Channel / Event Message:** Foundational delivery and message style.
    
-   **Message Broker:** Often the physical substrate on which the logical bus runs.
    
-   **Channel Adapter / Messaging Gateway:** Typed edges from applications to the bus.
    
-   **Content-Based Router / Message Filter / Recipient List:** Routing patterns expressed on/around the bus.
    
-   **Transactional Outbox / Idempotent Receiver / Dead Letter Channel:** Reliability companions.
    
-   **Canonical Data Model / Message Translator:** Schema strategy and transformation discipline.

