# Publish–Subscribe Channel — Enterprise Integration Pattern

## Pattern Name and Classification

**Name:** Publish–Subscribe Channel  
**Classification:** Messaging channel pattern (EIP); broadcast-style channel where each published message is **delivered to all interested subscribers**.

## Intent

Allow a sender to **publish once** and have the message **fan out** to multiple independent consumers, without the publisher knowing who they are or how many exist.

## Also Known As

-   Topic (JMS/AMQP)
    
-   Event Stream / Stream (Kafka/Pulsar)
    
-   Fan-Out Channel / Broadcast Channel
    

## Motivation (Forces)

-   **Decoupling:** Producers shouldn’t track consumer addresses or lifecycles.
    
-   **Fan-out:** Multiple services can react to the same event (billing, shipping, analytics).
    
-   **Independent evolution:** New subscribers can join without changing publishers.
    
-   **Scalability:** Each subscriber scales independently.
    

**Tensions**

-   Ordering and delivery guarantees differ by tech (e.g., per-partition order).
    
-   Back-pressure: slow subscribers can lag; buffer/retention must be tuned.
    
-   “One size fits all” topics can become overloaded or semantically vague.
    

## Applicability

Use a Publish–Subscribe Channel when:

-   You need **one-to-many** delivery for domain events/notifications.
    
-   Subscribers are **loosely coupled** and may appear/disappear over time.
    
-   You want **replay** or **late-joiner** behavior (log-based streams).
    
-   You need **tenant/region** segregation via topic names or filters.
    

Avoid or limit when:

-   Only a single consumer should process the message → use **Point-to-Point Channel**.
    
-   Hard request–reply semantics are needed → use **Request–Reply** over channels.
    

## Structure

```lua
+---------------------------+
Publisher -->|   Publish–Subscribe Topic |--> Subscriber A
             |        / Stream           |--> Subscriber B
             +---------------------------+--> Subscriber C ...
```

## Participants

-   **Publisher (Producer):** Writes messages to the topic/stream.
    
-   **Publish–Subscribe Channel:** Topic/stream that fans out messages.
    
-   **Subscribers (Consumers):** Each gets its own copy; scale via consumer groups (log-based) or individual subscriptions (broker-based).
    
-   **Broker/Cluster:** Transport that manages persistence, retention, and delivery.
    
-   **Admin/Policy:** ACLs, retention, filters, DLQ/subscription rules.
    

## Collaboration

1.  Publisher emits a message to the topic.
    
2.  Broker persists/replicates per policy and delivers a copy to **each subscription**.
    
3.  Each subscriber consumes and acknowledges/commits independently.
    
4.  Failures/redeliveries are isolated per subscriber (DLQ or retries).
    

## Consequences

**Benefits**

-   Strong decoupling and extensibility (add consumers without touching producers).
    
-   Natural fit for **event-driven architecture** and analytics.
    
-   Independent scaling and failure isolation per subscriber.
    

**Liabilities**

-   Potential **ordering** complexities across subscribers.
    
-   Managing **lag** and **retention** for slow/paused subscribers.
    
-   Risk of **topic sprawl** or “god topics” without governance.
    
-   Exactly-once **delivery** is rare; design for exactly-once **effects**.
    

## Implementation

-   **Choose substrate:**
    
    -   **JMS/AMQP topics** (ActiveMQ, Artemis, RabbitMQ exchange + bound queues) for classic pub/sub.
        
    -   **Log-based streams** (Kafka, Pulsar): retention + replay, consumer groups, partitions.
        
-   **Topic design:** Meaningful, versioned names (e.g., `orders.created.v1`).
    
-   **Headers & envelope:** `messageId`, `eventType`, `eventVersion`, `occurredAt`, `correlationId`.
    
-   **Schema management:** Avro/Protobuf/JSON with a registry and compatibility rules.
    
-   **Reliability:** At-least-once by default; pair with **Idempotent Receiver**.
    
-   **Retention & DLQ:** Size/time-based retention; per-subscriber DLQ (broker or app-level).
    
-   **Security:** mTLS/OAuth2; per-topic ACLs; tenant isolation by namespace.
    
-   **Observability:** Topic throughput, consumer lag, redeliveries; trace propagation (`traceparent`).
    
-   **Multi-region:** Replication/mirroring; write locality considerations.
    

---

## Sample Code (Java)

### A) Kafka — Publish once, multiple subscribers (consumer groups)

```java
// build.gradle: implementation("org.springframework.kafka:spring-kafka"), implementation("com.fasterxml.jackson.core:jackson-databind")

// Producer
@Component
class OrderProducer {
  private final KafkaTemplate<String, byte[]> template;
  private final ObjectMapper mapper = new ObjectMapper();
  OrderProducer(KafkaTemplate<String, byte[]> template) { this.template = template; }

  public void publish(OrderCreated evt) {
    try {
      byte[] payload = mapper.writeValueAsBytes(evt);
      template.send("orders.created.v1", evt.orderId(), payload);
    } catch (Exception e) { throw new RuntimeException(e); }
  }
}

record OrderCreated(String orderId, String sku, int qty, String region) {}

// Subscriber #1 (Billing)
@Component
class BillingSubscriber {
  private final ObjectMapper mapper = new ObjectMapper();

  @KafkaListener(topics = "orders.created.v1", groupId = "billing")
  public void onEvent(ConsumerRecord<String, byte[]> rec) throws Exception {
    OrderCreated evt = mapper.readValue(rec.value(), OrderCreated.class);
    // idempotent billing by orderId
  }
}

// Subscriber #2 (Shipping)
@Component
class ShippingSubscriber {
  private final ObjectMapper mapper = new ObjectMapper();

  @KafkaListener(topics = "orders.created.v1", groupId = "shipping")
  public void onEvent(ConsumerRecord<String, byte[]> rec) throws Exception {
    OrderCreated evt = mapper.readValue(rec.value(), OrderCreated.class);
    // allocate shipment; guard with Idempotent Receiver
  }
}
```

### B) RabbitMQ (AMQP) — Topic exchange with bound queues (fan-out-by-key)

```java
// build.gradle: implementation("org.springframework.boot:spring-boot-starter-amqp")
@Configuration
class RabbitPubSubConfig {
  @Bean TopicExchange ordersEx() { return new TopicExchange("orders-ex"); }

  // Per-subscriber durable queues
  @Bean Queue billingQ() { return new Queue("orders.created.billing.q", true); }
  @Bean Queue shippingQ() { return new Queue("orders.created.shipping.q", true); }

  // Bindings: both get "orders.created.*"
  @Bean Binding billingBinding() {
    return BindingBuilder.bind(billingQ()).to(ordersEx()).with("orders.created.*");
  }
  @Bean Binding shippingBinding() {
    return BindingBuilder.bind(shippingQ()).to(ordersEx()).with("orders.created.*");
  }
}

@Service
class RabbitPublisher {
  private final AmqpTemplate amqp;
  RabbitPublisher(AmqpTemplate amqp) { this.amqp = amqp; }
  public void publish(OrderCreated evt) { amqp.convertAndSend("orders-ex", "orders.created.eu", evt); }
}

@Component
class BillingListener {
  @RabbitListener(queues = "orders.created.billing.q")
  public void bill(OrderCreated evt) { /* ... */ }
}
@Component
class ShippingListener {
  @RabbitListener(queues = "orders.created.shipping.q")
  public void ship(OrderCreated evt) { /* ... */ }
}
```

### C) JMS (Jakarta) — Durable topic subscribers

```java
// Maven: jakarta.jms-api, activemq-artemis-jakarta-client
try (var cf = new org.apache.activemq.artemis.jms.client.ActiveMQConnectionFactory("tcp://localhost:61616");
     var connection = cf.createConnection()) {

  connection.setClientID("billing-app"); // needed for durable subscription
  Session session = connection.createSession(Session.AUTO_ACKNOWLEDGE);
  Topic topic = session.createTopic("orders.created");

  // Publisher
  MessageProducer producer = session.createProducer(topic);
  TextMessage msg = session.createTextMessage("{\"orderId\":\"O-1\",\"sku\":\"A\",\"qty\":2}");
  producer.send(msg);

  // Durable Subscriber
  TopicSubscriber billing = session.createDurableSubscriber(topic, "billing-sub");
  connection.start();
  Message received = billing.receive(2000);
  if (received != null) {
    System.out.println(((TextMessage) received).getText());
  }
}
```

### D) Spring Cloud Stream — Transport-agnostic pub/sub

```java
// build.gradle: implementation("org.springframework.cloud:spring-cloud-stream"), binder dep: kafka or rabbit
@EnableBinding // for functional: use spring.cloud.function.definition
@SpringBootApplication
public class PubSubApp { public static void main(String[] args){ SpringApplication.run(PubSubApp.class,args);} }

@Configuration
class Functions {
  @Bean
  public Supplier<OrderCreated> publishOrders() {
    return () -> new OrderCreated("O-" + System.currentTimeMillis(), "SKU1", 1, "EU");
  }
  @Bean
  public Consumer<OrderCreated> billing() {
    return evt -> { /* bill */ };
  }
  @Bean
  public Consumer<OrderCreated> shipping() {
    return evt -> { /* ship */ };
  }
}
```

---

## Known Uses

-   **Business events** (`customer.created`, `order.fulfilled`) consumed by billing, shipping, CRM, and analytics simultaneously.
    
-   **Audit/monitoring** taps where the same event feeds security monitoring and observability pipelines.
    
-   **CDC/event sourcing** streams with many downstream projections/read models.
    
-   **Cloud services**: AWS SNS → multiple SQS queues/Lambdas; Azure Service Bus topics with multiple subscriptions.
    

## Related Patterns

-   **Point-to-Point Channel:** Single-consumer alternative.
    
-   **Message Channel:** The general abstraction that pub/sub specializes.
    
-   **Message Router / Recipient List:** Upstream routing to specialized topics.
    
-   **Message Filter:** Subscriber-side selective consumption.
    
-   **Idempotent Receiver:** Ensures exactly-once **effects** for at-least-once delivery.
    
-   **Transactional Outbox:** Reliable publication to the channel from a database transaction.
    
-   **Message Translator / Canonical Data Model:** Normalize payloads for wide reuse across subscribers.

