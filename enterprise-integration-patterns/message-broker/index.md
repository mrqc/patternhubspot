# Message Broker — Enterprise Integration Pattern

## Pattern Name and Classification

**Name:** Message Broker  
**Classification:** Architectural / Topology pattern (EIP); hub-and-spoke mediator for messaging with optional routing, transformation, and orchestration capabilities.

## Intent

Decouple producers and consumers by introducing a **broker** that accepts messages, **routes** them to interested parties, and optionally **transforms**, **enriches**, or **orchestrates** interactions—so that endpoints remain simpler and loosely coupled.

## Also Known As

-   Broker (Hub-and-Spoke)
    
-   Enterprise Service Bus (ESB) *(broader, often tooling-laden superset)*
    
-   Event Bus / Event Hub *(when used primarily for pub/sub events)*
    

## Motivation (Forces)

-   **Decoupling:** Producers shouldn’t need to know consumer addresses, protocols, or availability.
    
-   **Routing logic:** Decisions belong in a centralized, observable place (content-based routing, multicast, topic-based).
    
-   **Heterogeneity:** Bridge different transports/data formats between systems.
    
-   **Operational control:** Centralize security, throttling, DLQs, retries, and metrics.
    
-   **Scalability & resilience:** Buffer bursts, smooth load, and isolate failures.
    

**Tensions**

-   Centralization vs. single-point bottlenecks.
    
-   Flexibility vs. complexity and vendor lock-in.
    
-   Smart broker vs. smart endpoints (who owns transformation/orchestration).
    

## Applicability

Use a Message Broker when:

-   Multiple producers/consumers must communicate without tight coupling.
    
-   You need **content-based**, **topic-based**, or **rules-based** routing.
    
-   Systems speak different formats/transports (HTTP/JMS/AMQP/MQTT).
    
-   You require **reliable delivery** with buffering, retries, and DLQ.
    
-   Teams want governance and observability for cross-system flows.
    

Avoid or limit when:

-   Ultra-low latency, point-to-point links suffice (broker adds hops).
    
-   You favor **smart endpoints, dumb pipes** (microservices) and only need lightweight pub/sub (then prefer simple transports or a log like Kafka).
    

## Structure

```rust
+-----------+          +---------------------+
Producer|  Producer |--msg---->|     Message Broker  |-----> Queue/Topic A --> Consumer A
   P1   +-----------+          |  - accept           |-----> Queue/Topic B --> Consumer B
        +-----------+          |  - route            |-----> ...             --> ...
Producer|  Producer |--msg---->|  - transform (opt)  |
   P2   +-----------+          |  - persist (opt)    |
                               +---------------------+
```

## Participants

-   **Producers:** Publish messages (commands, events).
    
-   **Message Broker:** Accepts, validates, persists (optional), routes, transforms, and applies policies.
    
-   **Channels:** Queues/Topics/Exchanges (AMQP), Destinations (JMS), Streams (log-based).
    
-   **Consumers:** Competing or subscribing receivers.
    
-   **Admin/Policy Layer (optional):** AuthN/Z, quotas, schemas, observability.
    
-   **DLQ/Retry Handlers:** For poison messages and redelivery policy.
    

## Collaboration

1.  Producer sends a message to a broker destination (exchange/topic/queue).
    
2.  Broker **routes** based on destination, headers, content, or bindings.
    
3.  Consumers receive according to semantics: **competing** (queue) or **broadcast** (topic).
    
4.  Acknowledge/commit semantics ensure at-least-once delivery; failures go to retries/DLQ.
    
5.  Optional **transforms/enrichers** occur within the broker or at edges.
    

## Consequences

**Benefits**

-   Strong decoupling (location, time, and rate).
    
-   Central, consistent **routing and policies**.
    
-   Back-pressure via queues; **burst smoothing**.
    
-   Easier onboarding of new consumers (subscribe to topics).
    

**Liabilities**

-   **Operational gravity:** a new critical system to scale, secure, and monitor.
    
-   Potential **bottleneck/SPOF** without clustering and partitioning.
    
-   Complex routing/transforms can drift into “mini-ESB monolith.”
    
-   **Latency** overhead of extra hop; **ordering** and **exactly-once** are hard.
    
-   **Vendor lock-in** via proprietary models or broker-specific features.
    

## Implementation

-   **Choose model:**
    
    -   Classic broker (AMQP/RabbitMQ, JMS/ActiveMQ/Artemis, IBM MQ) for queues/topics & flexible routing.
        
    -   Log-based broker (Kafka/Pulsar) for high-throughput pub/sub, replay, and retention-first design.
        
-   **Destinations:** Design **narrow, purpose-driven** topics/queues (avoid “god topics”). Prefer **event type per topic** or **routing key** patterns.
    
-   **Routing:** Use **direct**, **topic**, **headers**, or **content-based** routing; define bindings declaratively (infra-as-code).
    
-   **Delivery semantics:** At-least-once by default. Pair with **Idempotent Receiver** and **Transactional Outbox**.
    
-   **Schema management:** Avro/JSON Schema/Protobuf with **schema registry** and compatibility rules.
    
-   **Retries/DLQ:** Exponential backoff, max-attempts, parking lot queues; ensure visibility & alerting.
    
-   **Security:** mTLS, SASL/OAuth2, per-destination ACLs, tenant isolation.
    
-   **Observability:** Per-destination metrics (lag, depth, throughput, redeliveries), trace propagation, structured logs.
    
-   **Scalability:** Sharding/partitions, consumer groups, prefetch/credit tuning.
    
-   **Disaster recovery:** Cross-AZ clusters, mirrored queues, geo-replication; plan for **exactly-once effect**, not delivery.
    

## Sample Code (Java)

### A) JMS (ActiveMQ Artemis) — Producer & Consumer

```java
// Maven: jakarta.jms-api, activemq-artemis-jakarta-client
import jakarta.jms.*;
import org.apache.activemq.artemis.jms.client.ActiveMQConnectionFactory;

public class JmsExample {
  public static void main(String[] args) throws Exception {
    try (ConnectionFactory cf = new ActiveMQConnectionFactory("tcp://localhost:61616");
         Connection conn = cf.createConnection()) {
      Session session = conn.createSession(Session.AUTO_ACKNOWLEDGE);

      // Queue for commands, Topic for events
      Queue queue = session.createQueue("orders.command.create");
      Topic topic = session.createTopic("orders.event");

      // Producer (command)
      MessageProducer producer = session.createProducer(queue);
      TextMessage msg = session.createTextMessage("{\"orderId\":\"O-123\",\"sku\":\"ABC\",\"qty\":2}");
      msg.setStringProperty("messageType", "CreateOrder");
      producer.send(msg);

      // Consumer (event subscription)
      MessageConsumer consumer = session.createConsumer(topic);
      conn.start();
      Message m = consumer.receive(2000);
      if (m != null) {
        System.out.println("event: " + ((TextMessage)m).getText());
      }
    }
  }
}
```

### B) RabbitMQ (AMQP) — Topic Routing with Spring AMQP

```java
// Gradle: spring-boot-starter-amqp
@Configuration
class RabbitConfig {
  @Bean TopicExchange ordersExchange() { return new TopicExchange("orders-ex"); }
  @Bean Queue billingQ() { return new Queue("billing.q", true); }
  @Bean Queue shippingQ() { return new Queue("shipping.q", true); }
  @Bean Binding b1() { return BindingBuilder.bind(billingQ()).to(ordersExchange()).with("order.*.created"); }
  @Bean Binding b2() { return BindingBuilder.bind(shippingQ()).to(ordersExchange()).with("order.eu.created"); }
}

@Service
class OrderPublisher {
  private final AmqpTemplate template;
  OrderPublisher(AmqpTemplate template) { this.template = template; }
  public void publishCreated(OrderCreated evt) {
    String key = "order.eu.created"; // routes to both bindings above
    template.convertAndSend("orders-ex", key, evt);
  }
}

@Component
class BillingListener {
  @RabbitListener(queues = "billing.q")
  public void bill(OrderCreated evt) { /* handle billing */ }
}
```

### C) Kafka — High-throughput Pub/Sub with Consumer Group

```java
// Gradle: spring-kafka
@Component
class OrderProducer {
  private final KafkaTemplate<String, OrderCreated> template;
  OrderProducer(KafkaTemplate<String, OrderCreated> template) { this.template = template; }
  public void publish(OrderCreated evt) {
    template.send("orders.created.v1", evt.orderId(), evt);
  }
}

@Component
class OrderConsumer {
  @KafkaListener(topics = "orders.created.v1", groupId = "shipping-service")
  public void onEvent(OrderCreated evt) {
    // Idempotent Receiver recommended (e.g., check Redis/DB with evt.orderId())
    // perform shipping allocation
  }
}
```

### D) Apache Camel — Declarative Routing (Content-Based + DLQ)

```java
// Gradle: camel-core, camel-jms, camel-rabbitmq, camel-kafka (pick transports as needed)
public class Routes extends RouteBuilder {
  @Override
  public void configure() {
    errorHandler(deadLetterChannel("jms:queue:orders.DLQ").maximumRedeliveries(5).redeliveryDelay(1000));

    from("jms:queue:orders.command.create")
      .routeId("orders-create")
      .choice()
        .when().jsonpath("$.region", true).isEqualTo("EU")
          .to("rabbitmq:orders-ex?exchangeType=topic&routingKey=order.eu.created")
        .otherwise()
          .to("rabbitmq:orders-ex?exchangeType=topic&routingKey=order.other.created")
      .end()
      .to("kafka:orders.created.v1"); // fan-out to Kafka for analytics/replay
  }
}
```

> In all cases, pair producer reliability with **Transactional Outbox** and consumer safety with **Idempotent Receiver**. Use **schema registry** for evolution.

## Known Uses

-   **RabbitMQ / AMQP** in fintech and e-commerce for routing commands/events via topic exchanges and DLQs.
    
-   **ActiveMQ Artemis / IBM MQ (JMS)** for reliable enterprise queues, request–reply, and mainframe offload.
    
-   **Apache Kafka / Confluent Platform** as a high-throughput event broker for pub/sub, CDC, and stream processing (with replay and retention).
    
-   **Azure Service Bus / AWS SQS & SNS / Google Pub/Sub** managed broker services with DLQ, topics, and IAM integration.
    
-   **Apache Camel / Spring Integration** acting as broker-adjacent mediation/routing layers across protocols.
    

## Related Patterns

-   **Content-Based Router / Message Filter / Recipient List:** Canonical routing strategies often realized inside or around the broker.
    
-   **Channel Adapter / Messaging Gateway:** Typed edges to the broker from code or external systems.
    
-   **Publish–Subscribe Channel / Point-to-Point Channel:** Delivery semantics implemented by brokers.
    
-   **Dead Letter Channel / Retry:** Error-handling companions.
    
-   **Transactional Outbox / Idempotent Receiver:** Achieve exactly-once *effects* over at-least-once delivery.
    
-   **Message Translator / Content Enricher:** Transformation/enrichment often colocated with broker or edge.

