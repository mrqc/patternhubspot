# Service Activator — Enterprise Integration Pattern

## Pattern Name and Classification

**Name:** Service Activator  
**Classification:** Endpoint pattern (EIP); receive-side **message endpoint** that invokes an application **service method** when a message arrives.

## Intent

Connect a **Message Channel** to a **plain business service** by adapting incoming messages to method parameters (and optional replies to messages). Keeps messaging details out of the domain layer.

## Also Known As

-   Message-Driven POJO (MDP)
    
-   Inbound Endpoint / Inbound Adapter
    
-   Message Listener → Service
    

## Motivation (Forces)

-   Keep domain services **messaging-agnostic** (no JMS/AMQP/Kafka APIs in business code).
    
-   Provide a single place to handle **deserialization, validation, acks, retries, DLQ, tracing**.
    
-   Enable **testable** business services (mock the service; test message flow separately).
    
-   Support heterogeneous transports (HTTP, JMS, AMQP, Kafka) with the same service signature.
    

## Applicability

Use a Service Activator when:

-   A service should be triggered by **incoming messages** (commands/events).
    
-   You want to **translate** message → domain types and apply **boundary policies** (idempotency, auth, rate limit).
    
-   Replies (optional) should be sent back (Request–Reply) **without** RPC in the service.
    

Avoid when:

-   Everything is in-process and synchronous; a direct method call is simpler.
    
-   Orchestration logic belongs elsewhere (Process Manager/Saga), not inside the activator.
    

## Structure

```pgsql
+--------------------+       +---------------------+
Channel->| Service Activator  |-----> |   Business Service  |
         | - deserialize      |       |  (pure domain code) |
         | - validate         |<----- | (optional reply)    |
         | - acks/retries     |       +---------------------+
         +--------------------+
```

## Participants

-   **Message Channel:** Source of commands/events.
    
-   **Service Activator (Endpoint):** Messaging-facing adapter; maps, validates, invokes.
    
-   **Business Service:** Plain class with domain methods; no transport code.
    
-   **Serializer/Validator:** JSON/Avro/Protobuf, bean validation, schema checks.
    
-   **Error/DLQ Policy:** Retry, backoff, dead-letter.
    
-   **Reply Channel (optional):** For Request–Reply.
    

## Collaboration

1.  Message arrives on the channel.
    
2.  Activator **converts** payload/headers → method parameters; validates.
    
3.  Activator **invokes** the service method (local transaction as needed).
    
4.  On success, optionally **publish reply/event**; on failure, apply retry/DLQ policy.
    
5.  Observability: emit metrics and traces with correlation IDs.
    

## Consequences

**Benefits**

-   Clear separation of concerns; domain code is simple and portable.
    
-   Standard place for reliability policies and **idempotency**.
    
-   Improves **testability** and transport independence.
    

**Liabilities**

-   Another hop and layer to maintain.
    
-   If overloaded with orchestration/translation, can turn into a “mini-ESB” inside the service.
    
-   Misconfigured retries can amplify failures.
    

## Implementation

-   **Mapping:** DTOs at the boundary; map to domain objects (MapStruct or manual).
    
-   **Idempotency:** Use keys (messageId/business key) and a **Message Store** when transport is at-least-once.
    
-   **Transactions:** Wrap handler in a local TX if updating a DB; use **Transactional Outbox** for further events.
    
-   **Error handling:** Exponential backoff, max attempts, DLQ with diagnostics.
    
-   **Security:** Authenticate/authorize at endpoint; validate signatures/classification headers.
    
-   **Observability:** Correlation/causation IDs, `traceparent`, metrics for throughput/latency/failures.
    
-   **Performance:** Tune concurrency/prefetch; keep the handler fast; offload heavy work to async steps.
    

---

## Sample Code (Java)

### A) Spring Integration — Service Activator wired to a queue/topic

```java
// build.gradle: implementation("org.springframework.boot:spring-boot-starter-integration"),
//               implementation("org.springframework.kafka:spring-kafka"),
//               implementation("com.fasterxml.jackson.core:jackson-databind")
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.context.annotation.*;
import org.springframework.integration.annotation.ServiceActivator;
import org.springframework.integration.channel.DirectChannel;
import org.springframework.integration.core.MessageSelector;
import org.springframework.integration.dsl.*;
import org.springframework.kafka.support.converter.StringJsonMessageConverter;
import org.springframework.messaging.*;

@Configuration
@EnableIntegration
public class OrderActivatorConfig {

  @Bean public MessageChannel ordersIn()  { return new DirectChannel(); }
  @Bean public MessageChannel repliesOut(){ return new DirectChannel(); }

  // Example: inbound from Kafka adapter → logical channel (simplified)
  @Bean
  IntegrationFlow kafkaInbound() {
    return IntegrationFlows
      .from(Kafka.messageDrivenChannelAdapter(consumerFactory(), "orders.create.cmd"))
      .channel("ordersIn")
      .get();
  }

  @Bean
  @ServiceActivator(inputChannel = "ordersIn", outputChannel = "repliesOut", adviceChain = "retryAdvice")
  public MessageHandler orderServiceActivator(OrderService orderService, ObjectMapper json) {
    return msg -> {
      OrderCreateCommand cmd = toCmd(json, msg.getPayload());
      OrderConfirmation conf = orderService.createOrder(cmd); // pure domain logic
      Message<OrderConfirmation> reply = MessageBuilder.withPayload(conf)
          .copyHeaders(msg.getHeaders())
          .setHeaderIfAbsent("eventType", "orders.order.created")
          .build();
      // emit reply to outputChannel (e.g., another flow publishes it)
      repliesOut().send(reply);
    };
  }

  private OrderCreateCommand toCmd(ObjectMapper json, Object payload) {
    try {
      if (payload instanceof byte[] b) return json.readValue(b, OrderCreateCommand.class);
      if (payload instanceof String s)  return json.readValue(s, OrderCreateCommand.class);
      return (OrderCreateCommand) payload;
    } catch (Exception e) { throw new IllegalArgumentException("bad payload", e); }
  }

  // --- domain service (no messaging code) ---
  @Component
  public static class OrderService {
    public OrderConfirmation createOrder(OrderCreateCommand cmd) {
      // validate, persist, publish domain events via outbox, etc.
      return new OrderConfirmation(cmd.orderId(), "CREATED");
    }
  }

  public record OrderCreateCommand(String requestId, String orderId, String sku, int qty) {}
  public record OrderConfirmation(String orderId, String status) {}

  // Beans for Kafka consumerFactory(), retryAdvice, etc. omitted for brevity
}
```

### B) Apache Camel — Service Activator via `bean()` on inbound route

```java
// build.gradle: implementation("org.apache.camel:camel-core"), camel-kafka or camel-jms, camel-jackson
public class OrderRoutes extends org.apache.camel.builder.RouteBuilder {
  @Override
  public void configure() {
    errorHandler(deadLetterChannel("kafka:orders.DLQ")
      .maximumRedeliveries(5).redeliveryDelay(500).useExponentialBackOff());

    from("kafka:orders.create.cmd?groupId=order-handler")
      .routeId("order-activator")
      .unmarshal().json(org.apache.camel.model.dataformat.JsonLibrary.Jackson, OrderCreateCommand.class)
      .bean(OrderService.class, "create") // Service Activator call
      .marshal().json(org.apache.camel.model.dataformat.JsonLibrary.Jackson)
      .to("kafka:orders.created.evt");
  }

  public static class OrderService {
    public OrderConfirmation create(OrderCreateCommand cmd) {
      // domain logic only
      return new OrderConfirmation(cmd.orderId(), "CREATED");
    }
  }

  public record OrderCreateCommand(String orderId, String sku, int qty) {}
  public record OrderConfirmation(String orderId, String status) {}
}
```

### C) Jakarta JMS — Message-Driven POJO as a Service Activator (minimal)

```java
// Maven: jakarta.jms-api, activemq-artemis-jakarta-client, jackson-databind
import jakarta.jms.*;
import com.fasterxml.jackson.databind.ObjectMapper;

public class OrderJmsActivator implements MessageListener {
  private final ObjectMapper json = new ObjectMapper();
  private final OrderService service = new OrderService();

  @Override
  public void onMessage(Message message) {
    try {
      String body = ((TextMessage) message).getText();
      OrderCreateCommand cmd = json.readValue(body, OrderCreateCommand.class);
      OrderConfirmation conf = service.create(cmd);
      // optional request-reply
      Destination replyTo = message.getJMSReplyTo();
      if (replyTo != null) {
        Session session = /* obtain session */;
        MessageProducer prod = session.createProducer(replyTo);
        TextMessage reply = session.createTextMessage(json.writeValueAsString(conf));
        reply.setJMSCorrelationID(message.getJMSCorrelationID());
        prod.send(reply);
      }
      message.acknowledge();
    } catch (Exception e) {
      // let container/broker handle redelivery/DLQ per config
      throw new RuntimeException(e);
    }
  }

  static class OrderService {
    OrderConfirmation create(OrderCreateCommand cmd) { return new OrderConfirmation(cmd.orderId(), "CREATED"); }
  }
  public record OrderCreateCommand(String orderId, String sku, int qty) {}
  public record OrderConfirmation(String orderId, String status) {}
}
```

---

## Known Uses

-   **Spring Integration** `@ServiceActivator` endpoints mapping messages to POJO service methods.
    
-   **Apache Camel** routes invoking business beans via `bean()`/`processor`.
    
-   **JMS MDB/MDP** in Jakarta EE apps listening on queues/topics and calling EJB/POJO services.
    
-   **Cloud triggers**: AWS SQS/SNS/Lambda or GCP Pub/Sub functions activating service code.
    

## Related Patterns

-   **Message Endpoint:** The broader category—Service Activator is the receive-side variant.
    
-   **Messaging Gateway / Channel Adapter:** Gateways expose method APIs; adapters connect specific transports.
    
-   **Request–Reply:** Often used when the activator returns a response.
    
-   **Idempotent Receiver:** Pair with activator for at-least-once delivery.
    
-   **Transactional Outbox / Inbox:** Reliable publication/consumption around the activator.
    
-   **Message Filter / Translator / Content Enricher:** Common pre/post steps inside the activator flow.

