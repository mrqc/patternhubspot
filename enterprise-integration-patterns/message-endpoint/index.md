# Message Endpoint — Enterprise Integration Pattern

## Pattern Name and Classification

**Name:** Message Endpoint  
**Classification:** Endpoint pattern (EIP); the **application-side boundary** that connects business code to a **Message Channel**.

## Intent

Isolate business logic from the messaging infrastructure by placing a dedicated endpoint component that **sends to** or **receives from** channels and performs translation, validation, error mapping, and policy (retry, timeout) so the core application remains messaging-agnostic.

## Also Known As

-   Service Activator (receive-side, command handler)
    
-   Inbound/Outbound Adapter (technology-specific endpoint)
    
-   Consumer/Producer Endpoint
    
-   Listener / Handler
    

## Motivation (Forces)

-   Keep application code clean of transport concerns (JMS/AMQP/Kafka APIs, headers, acks).
    
-   Provide a **single place** to enforce cross-cutting concerns (auth, validation, tracing, retries).
    
-   Support **multiple transports** without changing the domain logic.
    
-   Enable **testability**: mock the endpoint or the channel, unit-test the handler.
    

## Applicability

Use a Message Endpoint when:

-   Your service must interact with a **Message Channel** (queue/topic/stream).
    
-   You want to **separate** message plumbing from business handlers.
    
-   You need consistent **error handling** (DLQ, retries) and **observability** at the boundary.
    
-   You must **translate** between wire payloads and domain objects.
    

Avoid when:

-   Everything happens in-process with simple method calls and you don’t require messaging semantics.
    

## Structure

```pgsql
+-------------------+
Channel --> | Inbound Endpoint  | --> Business Handler
            |  - deserialization|
            |  - validation     |
            |  - acks/retries   |
            +-------------------+

            +-------------------+
Handler --> | Outbound Endpoint | --> Channel
            |  - map to message |
            |  - headers/qos    |
            |  - publish/send   |
            +-------------------+
```

## Participants

-   **Message Endpoint:** Encapsulates the messaging API and boundary policies.
    
-   **Message Channel:** Destination/source (queue, topic, stream).
    
-   **Business Handler:** Pure domain logic (commands/events).
    
-   **Translators/Validators:** Convert and validate payloads.
    
-   **Error Handler / DLQ:** Deals with poison messages.
    
-   **Infrastructure (Broker/Client):** JMS/AMQP/Kafka, etc.
    

## Collaboration

1.  **Inbound:** Endpoint reads a message, **ack-resiliently** converts to a domain type, validates, invokes the handler, and emits a reply/event if needed.
    
2.  **Outbound:** Handler returns a domain object; endpoint maps it to a message (payload + headers) and publishes to the configured channel.
    
3.  Failures are retried according to policy; unhandled failures are routed to DLQ with context.
    

## Consequences

**Benefits**

-   Clean separation of concerns; simpler business code.
    
-   Consistent boundary behavior (retries, metrics, tracing).
    
-   Transport independence and easier substitution.
    
-   Easier unit/integration testing.
    

**Liabilities**

-   Another abstraction to maintain; misconfiguration can hide back-pressure or failure signals.
    
-   If endpoints become too “smart,” they can accumulate orchestration logic better placed elsewhere.
    
-   Latency/overhead from serialization and policy layers.
    

## Implementation

-   **Endpoint roles:** Distinguish **inbound** (message → domain) and **outbound** (domain → message).
    
-   **Mapping:** Use explicit DTOs; centralize serialization (Avro/JSON/Protobuf).
    
-   **Error policy:** Redelivery with backoff; circuit breaker; DLQ with diagnostic headers (stack, timestamp, attempts, cause).
    
-   **Idempotency:** For at-least-once transports, guard handlers with **Idempotent Receiver**.
    
-   **Tracing & metrics:** Propagate `traceparent`/correlation IDs; record latency, success/error counts, redeliveries.
    
-   **Configuration as code:** Declare bindings, topics/queues, and policies via code or IaC (e.g., Spring config, Camel routes, Terraform/Helm).
    
-   **Security:** Validate/authenticate at the endpoint; verify signatures where applicable.
    
-   **Back-pressure:** Tune concurrency, prefetch, and commit/ack strategy.
    

## Sample Code (Java)

### A) Spring Integration — Inbound Service Activator (JMS)

```java
// build.gradle: spring-boot-starter-integration, spring-jms, jackson
@Configuration
@EnableIntegration
public class OrderInboundEndpoint {

  @Bean
  public IntegrationFlow jmsInbound(ConnectionFactory cf, ObjectMapper mapper, OrderHandler handler) {
    return IntegrationFlows
      .from(Jms.messageDrivenChannelAdapter(cf).destination("orders.command.create")
            .configureListenerContainer(c -> c.sessionTransacted(true)))
      .transform(Transformers.fromJson(OrderCreateCommand.class))
      .handle(Message.class, (msg, headers) -> {
          OrderCreateCommand cmd = (OrderCreateCommand) msg.getPayload();
          // Idempotency check (e.g., by cmd.requestId())
          return handler.handle(cmd); // pure domain code
      })
      .get();
  }
}

public record OrderCreateCommand(String requestId, String orderId, String sku, int qty) {}
@Component
class OrderHandler {
  public OrderConfirmation handle(OrderCreateCommand cmd) {
    // business logic: persist, publish events, etc.
    return new OrderConfirmation(cmd.orderId(), "CREATED");
  }
}
public record OrderConfirmation(String orderId, String status) {}
```

### B) Spring Kafka — Listener Endpoint with Retry/DLQ

```java
// build.gradle: spring-kafka, spring-retry
@Component
public class OrderEventEndpoint {

  private final ObjectMapper mapper = new ObjectMapper();

  @KafkaListener(topics = "orders.created.v1", groupId = "billing")
  @RetryableTopic(attempts = "5", backoff = @Backoff(delay = 500, multiplier = 2.0),
                  dltTopicSuffix = ".DLT", autoCreateTopics = "true")
  public void onMessage(ConsumerRecord<String, byte[]> record) throws Exception {
    OrderCreated evt = mapper.readValue(record.value(), OrderCreated.class);
    // validate + handle
    charge(evt);
  }

  private void charge(OrderCreated evt) {
    // business logic; design to be idempotent by evt.orderId()
  }
}

public record OrderCreated(String orderId, String sku, int qty) {}
```

### C) Apache Camel — Endpoint URIs with Bean Handler

```java
// build.gradle: camel-core, camel-kafka, camel-jms (choose transports)
public class EndpointRoutes extends RouteBuilder {
  @Override
  public void configure() {
    errorHandler(deadLetterChannel("kafka:orders.created.v1.DLT")
        .maximumRedeliveries(4).redeliveryDelay(1000).useOriginalMessage());

    from("kafka:orders.created.v1?groupId=shipping")
      .routeId("shipping-endpoint")
      .unmarshal().json(JsonLibrary.Jackson, OrderCreated.class)
      .bean(ShippingHandler.class, "allocate");
  }
}

public class ShippingHandler {
  public void allocate(OrderCreated evt) {
    // business logic; can publish outbound via another Camel endpoint
  }
}
```

### D) Outbound Endpoint (Spring AMQP) — Domain → Message Channel

```java
// build.gradle: spring-boot-starter-amqp, jackson
@Service
public class OutboundEndpoint {
  private final RabbitTemplate rabbit;
  private final ObjectMapper mapper;

  public OutboundEndpoint(RabbitTemplate rabbit, ObjectMapper mapper) {
    this.rabbit = rabbit; this.mapper = mapper;
  }

  public void publishOrderCreated(OrderCreated evt, String correlationId) {
    MessageProperties props = new MessageProperties();
    props.setHeader("eventType", "orders.order.created");
    props.setHeader("correlationId", correlationId);
    props.setContentType(MessageProperties.CONTENT_TYPE_JSON);
    Message msg = new Message(toJson(evt), props);
    rabbit.send("orders-ex", "orders.created.eu", msg);
  }

  private byte[] toJson(Object o) {
    try { return mapper.writeValueAsBytes(o); }
    catch (Exception e) { throw new IllegalStateException(e); }
  }
}
```

## Known Uses

-   **Spring Integration** `@ServiceActivator`, JMS/AMQP/Kafka adapters mapping messages to POJOs.
    
-   **Spring Kafka/SQS/SNS** annotated listeners as inbound endpoints with DLT integration.
    
-   **Apache Camel** routes using `from(uri)` / `to(uri)` as endpoints across protocols.
    
-   **JMS MDBs / Message-Driven POJOs** acting as classic message endpoints in Java EE/Jakarta EE.
    
-   **Cloud runtimes** (AWS Lambda triggers from SQS/SNS/Kinesis; GCP Pub/Sub push) serving as endpoints that invoke application code.
    

## Related Patterns

-   **Message Channel:** Endpoints connect to channels.
    
-   **Messaging Gateway / Channel Adapter:** Client-facing gateway vs. technology-specific adapter endpoints.
    
-   **Service Activator:** Concrete receive-side endpoint variant that invokes application services.
    
-   **Message Translator / Content Enricher / Filter:** Often composed inside endpoints.
    
-   **Idempotent Receiver / Dead Letter Channel / Retry:** Reliability companions.
    
-   **Request–Reply / Correlation Identifier:** For endpoints that implement synchronous semantics over messaging.

