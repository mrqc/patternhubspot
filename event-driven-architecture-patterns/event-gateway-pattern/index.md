# Event Gateway — Event-Driven Architecture Pattern

## Pattern Name and Classification

**Name:** Event Gateway  
**Classification:** Edge & Integration pattern (EDA/EIP); an **event ingress/egress boundary** that terminates external protocols, enforces policy, **translates** envelopes, and **routes** events into/out of the event backbone.

## Intent

Provide a single, policy-rich entry/exit point for events: **ingest** events from heterogeneous producers (HTTP/webhooks, MQTT, AMQP, gRPC, files), **validate/authenticate/shape** them, and **publish** to internal topics; in the opposite direction, **fan out** selected internal events to external consumers (SSE/WebSocket/webhooks/MQTT), all without coupling producers/consumers to internal transports.

## Also Known As

-   Event API Gateway / Event Ingress
    
-   Event Mesh Edge / Event Bridge
    
-   Webhook Ingress / Egress Relay
    
-   Messaging Gateway (event-focused)
    

## Motivation (Forces)

-   Producers/consumers speak different **protocols and contracts** (HTTP JSON, CloudEvents, MQTT).
    
-   Need centralized **security, quotas, schema validation**, **PII scrubbing**, and **tenancy** at the edge.
    
-   Internal backbone (Kafka/Pulsar/NATS) should remain **private** and stable; external integrations should not leak internal topology.
    
-   Outbound notifications need **delivery policies** (retries, backoff, DLQ) and **transformations**.
    

**Forces to balance**

-   Rich features vs. **latency** at the edge.
    
-   Flexibility of dynamic routing vs. **governance** of event contracts.
    
-   **Backpressure** when external senders/receivers are slow.
    
-   **At-least-once** delivery with duplicates vs. pushing toward exactly-once **effects**.
    

## Applicability

Use an Event Gateway when:

-   You must onboard **partners or SaaS** via webhooks/MQTT while your core uses Kafka/AMQP.
    
-   Teams want a **self-serve Event API**: publish/subscribe without direct broker access.
    
-   You need **cross-cutting policy** (authN/Z, quotas, schema checks, data masking) on event ingress/egress.
    
-   You want **protocol bridging** (HTTP↔Kafka, MQTT↔Kafka, AMQP↔Pulsar) and **cloud neutrality**.
    

Avoid or limit when:

-   All participants are **internal** and share the same broker/protocol and policy surface.
    
-   Ultra-low latency microseconds are required; a gateway hop can be too costly.
    

## Structure

```pgsql
External Producers                          Internal Backbone                      External Consumers
   +-----------------------------+                  +------------------+                 +---------------------------+
   | HTTP Webhooks | MQTT | AMQP | --ingress-->     | Kafka / Pulsar   | --egress-->     | Webhooks | SSE | WebSocket |
   +-----------------------------+                   +------------------+                  +---------------------------+
             \               ^                               ^    ^
              \              |                               |    |                      (policy: auth, quotas, schema,
               \             |                         +-----+    +-----+                 masking, routing, retries)
                v            |                         | Event Gateway |
           +------------------------+                   +-------------+
           |  Auth | Schema | PII   | --route/translate--> topics (namespaces, versions)
           |  Map  | Map    | Mask  |
           +------------------------+
```

## Participants

-   **Event Gateway:** Edge service implementing ingress/egress, routing, transformation, and policy.
    
-   **External Producers/Consumers:** Partners, mobile apps, SaaS via HTTP(S), MQTT, AMQP, gRPC.
    
-   **Internal Event Backbone:** Kafka/Pulsar/NATS/AMQP topics/queues.
    
-   **Policy/Registry:** Auth (OIDC/API keys), **schema registry**, routing tables, tenant catalogs.
    
-   **DLQ/Replay Store:** For failed deliveries and controlled re-drives.
    

## Collaboration

1.  **Ingress:** External sender calls the gateway (e.g., webhook). Gateway authenticates, validates schema, normalizes envelope (often **CloudEvents**), enriches headers (correlation/tenant), and **publishes** to the appropriate internal topic/namespace.
    
2.  **Internal Processing:** Services consume events from backbone.
    
3.  **Egress (optional):** Gateway subscribes to selected topics, **filters/transforms**, and pushes out via SSE/WebSocket/webhooks/MQTT with **retries** and **backoff**.
    
4.  **Observability:** The gateway emits metrics/traces/logs and supports audit & replay.
    

## Consequences

**Benefits**

-   One consistent **edge** for events; simpler onboarding and governance.
    
-   Strong **decoupling**: external protocols hidden from the core.
    
-   Centralized **security, quotas, schema checks**, **masking**, and **tenancy**.
    
-   Facilitates **protocol bridging** and **versioning**.
    

**Liabilities**

-   Becomes a **critical path**; needs horizontal scale and HA.
    
-   Can devolve into a “mini ESB” if overloaded with business logic—keep it **thin**.
    
-   Requires careful **backpressure** and **DLQ** strategies.
    
-   Additional hop adds **latency** and operational cost.
    

## Implementation

-   **Contracts & Formats:** Prefer **CloudEvents** envelope (id, source, type, subject, time) with JSON/Avro payloads.
    
-   **Routing:** Map `{tenant}/{domain}/{eventType}/{version}` to internal topics (e.g., `tnt1.orders.order.placed.v1`).
    
-   **AuthN/Z:** OIDC/JWT or API keys; authorize per **tenant + event type + direction (ingress/egress)**.
    
-   **Schema Validation:** Validate against **schema registry** before publishing; reject or route invalid to **DLQ**.
    
-   **PII/Security:** Field-level redaction/tokenization; encrypt at rest; allow-list headers.
    
-   **QoS:** Rate limit per key; dedupe using `messageId`; idempotent publication (producer idempotency for Kafka).
    
-   **Resiliency:** Retries with jitter; DLQ for bad events; **circuit breakers** for outbound webhooks.
    
-   **Backpressure:** Bounded queues; async I/O; shed excess load with 429; store-and-forward when downstream is down.
    
-   **Observability:** Correlation (`traceparent`, `correlationId`), metrics (ingress rate, reject rate, publish latency), structured logs.
    
-   **Operations:** Blue/green deploys, config-driven routing, per-tenant namespaces, audit & replay tooling.
    

---

## Sample Code (Java)

Below is a compact **Spring Boot (WebFlux + Spring Kafka)** Event Gateway that:

-   accepts **HTTP webhook** ingress, validates a minimal CloudEvents-like envelope, and publishes to Kafka, and
    
-   exposes **SSE** egress that streams from a Kafka topic to HTTP clients.
    

> Dependencies (Gradle):

```gradle
implementation "org.springframework.boot:spring-boot-starter-webflux"
implementation "org.springframework.kafka:spring-kafka"
implementation "com.fasterxml.jackson.core:jackson-databind:2.17.1"
```

### 1) Model (CloudEvents-ish) & Utilities

```java
// Event envelope kept minimal; extend with spec-compliant fields as needed.
public record IngressEvent(
    String id,         // messageId (UUID)
    String type,       // e.g., "orders.order.placed.v1"
    String source,     // producer id/uri
    String subject,    // optional: aggregate id
    String time,       // ISO-8601
    String tenant,     // multi-tenant routing
    Object data        // arbitrary JSON payload
) {
  public void validate() {
    if (id == null || id.isBlank()) throw new IllegalArgumentException("id required");
    if (type == null || !type.matches("[a-z0-9_.-]+\\.v\\d+")) throw new IllegalArgumentException("type invalid");
    if (tenant == null || tenant.isBlank()) throw new IllegalArgumentException("tenant required");
  }
}
```

### 2) Ingress Controller → Kafka

```java
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.springframework.http.HttpStatus;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Component;
import org.springframework.web.bind.annotation.*;
import reactor.core.publisher.Mono;

@RestController
@RequestMapping("/ingress")
class IngressController {
  private final KafkaTemplate<String, byte[]> kafka;
  private final ObjectMapper json = new ObjectMapper();
  private final TopicMapper mapper;

  IngressController(KafkaTemplate<String, byte[]> kafka, TopicMapper mapper) {
    this.kafka = kafka; this.mapper = mapper;
  }

  // Example: POST /ingress/event  (Content-Type: application/json)
  @PostMapping("/event")
  public Mono<Void> post(@RequestBody Mono<IngressEvent> body,
                         @RequestHeader(name = "Authorization", required = false) String auth) {
    // TODO: verify auth -> tenant/permissions; omitted for brevity
    return body.flatMap(evt -> {
      evt.validate();

      // (Optional) schema/PII validation step here

      String topic = mapper.resolveTopic(evt.tenant(), evt.type()); // e.g., t1.orders.order.placed.v1
      byte[] payload;
      try { payload = json.writeValueAsBytes(evt); }
      catch (Exception e) { return Mono.error(new IllegalArgumentException("invalid payload")); }

      var rec = new ProducerRecord<>(topic, evt.subject(), payload); // key=subject for per-aggregate order
      // propagate edge metadata
      rec.headers().add("ce_id", bytes(evt.id()));
      rec.headers().add("ce_type", bytes(evt.type()));
      rec.headers().add("ce_source", bytes(evt.source() == null ? "" : evt.source()));
      rec.headers().add("tenant", bytes(evt.tenant()));

      // at-least-once; consider producer idempotence for Kafka
      return Mono.fromFuture(kafka.send(rec).completable()).then();
    }).onErrorResume(IllegalArgumentException.class, ex ->
        Mono.error(new org.springframework.web.server.ResponseStatusException(HttpStatus.BAD_REQUEST, ex.getMessage())));
  }

  private static byte[] bytes(String s) { return s == null ? new byte[0] : s.getBytes(java.nio.charset.StandardCharsets.UTF_8); }
}

@Component
class TopicMapper {
  // Map tenant + event type to a Kafka topic; central place to enforce naming/version policy
  public String resolveTopic(String tenant, String type) {
    // Example result: tenant "t1", type "orders.order.placed.v1" -> "t1.orders.order.placed.v1"
    return tenant + "." + type;
  }
}
```

### 3) Egress (SSE) — Stream internal topic to HTTP clients

```java
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.springframework.context.annotation.Bean;
import org.springframework.http.MediaType;
import org.springframework.kafka.core.DefaultKafkaConsumerFactory;
import org.springframework.kafka.listener.*;
import org.springframework.stereotype.Component;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Sinks;

import java.time.Duration;
import java.util.Map;

@Component
class ReactiveTopicBridge {
  private final Map<String, Sinks.Many<String>> sinks = new java.util.concurrent.ConcurrentHashMap<>();
  Sinks.Many<String> sinkFor(String topic) {
    return sinks.computeIfAbsent(topic, t -> Sinks.many().multicast().onBackpressureBuffer());
  }
}

@Component
class TopicListenerFactory {

  private final org.springframework.kafka.core.ConsumerFactory<String, String> cf;
  private final ReactiveTopicBridge bridge;

  TopicListenerFactory(org.springframework.kafka.core.ConsumerFactory<String, String> cf, ReactiveTopicBridge bridge) {
    this.cf = cf; this.bridge = bridge;
  }

  // Start a listener for a given topic if not already started
  public synchronized void ensureListener(String topic) {
    String id = "egress-" + topic;
    if (running.containsKey(id)) return;

    var containerProps = new ContainerProperties(topic);
    var container = new KafkaMessageListenerContainer<>(cf, containerProps);
    container.setupMessageListener((MessageListener<String, String>) record -> {
      bridge.sinkFor(topic).tryEmitNext(record.value());
    });
    container.start();
    running.put(id, container);
  }

  private final Map<String, KafkaMessageListenerContainer<String, String>> running = new java.util.concurrent.ConcurrentHashMap<>();
}

@Configuration
class ConsumerConfigBeans {
  @Bean
  org.springframework.kafka.core.ConsumerFactory<String, String> consumerFactory() {
    var props = Map.<String, Object>of(
        ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, "localhost:9092",
        ConsumerConfig.GROUP_ID_CONFIG, "event-gateway-egress",
        ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class,
        ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class,
        ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "latest"
    );
    return new DefaultKafkaConsumerFactory<>(props);
  }
}

@RestController
class EgressController {
  private final TopicMapper mapper;
  private final TopicListenerFactory factory;
  private final ReactiveTopicBridge bridge;

  EgressController(TopicMapper mapper, TopicListenerFactory factory, ReactiveTopicBridge bridge) {
    this.mapper = mapper; this.factory = factory; this.bridge = bridge;
  }

  // Client subscribes to SSE: GET /egress/sse/{tenant}/{type}
  @GetMapping(path="/egress/sse/{tenant}/{type}", produces=MediaType.TEXT_EVENT_STREAM_VALUE)
  public Flux<String> stream(@PathVariable String tenant, @PathVariable String type) {
    String topic = mapper.resolveTopic(tenant, type);
    factory.ensureListener(topic);

    return bridge.sinkFor(topic)
      .asFlux()
      .onBackpressureBuffer(10_000)
      .timeout(Duration.ofMinutes(30))       // idle timeout
      .map(value -> "data:" + value + "\n\n"); // SSE framing handled by Spring via content-type
  }
}
```

**Notes & hardening**

-   Add **auth** on both ingress and egress; authorize per tenant/topic.
    
-   Validate against a **schema registry** before publishing.
    
-   For egress reliability beyond best effort SSE, implement **webhook push with retries + DLQ** (store last attempt, exponential backoff).
    
-   Consider **CloudEvents** SDKs for strict compliance, and **producer idempotence** for Kafka.
    

---

## Known Uses

-   **Webhook ingress** for SaaS (payments, billing, CRM) into Kafka/Pulsar with unified contracts.
    
-   **Mobile/IoT** MQTT ingress → normalize → publish to backbone; egress SSE/WebSocket to dashboards.
    
-   **Multi-tenant event APIs** where partners publish/subscribe without direct broker credentials.
    
-   **Cloud event bridges** (e.g., bridging AWS services to a shared Kafka bus, or vice versa).
    
-   **Legacy interop**: AMQP/HTTP edge in front of a modern event backbone.
    

## Related Patterns

-   **Messaging Gateway / Channel Adapter:** Lower-level analogs for protocol bridging.
    
-   **Publish–Subscribe Channel:** The backbone that the gateway feeds.
    
-   **Message Translator / Event Enrichment:** Common transformations applied at the gateway.
    
-   **Schema Registry / Canonical Data Model:** Governs event shapes at the edge.
    
-   **Dead Letter Queue:** For invalid events and failed outbound deliveries.
    
-   **Transactional Outbox:** For producers inside your services; the gateway is for **external** producers/consumers.
    
-   **Event Carried State Transfer (ECST):** Gateway may enforce publishing of state-rich events for downstream autonomy.
    

> **Takeaway:** an Event Gateway is the **policy and protocol guardrail** for your event platform—ingress, egress, and translation in one highly-available, thin edge that protects the core and simplifies integrations.

