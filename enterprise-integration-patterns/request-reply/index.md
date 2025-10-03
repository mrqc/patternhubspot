# Request–Reply — Enterprise Integration Pattern

## Pattern Name and Classification

**Name:** Request–Reply  
**Classification:** Messaging interaction pattern (EIP); synchronous-seeming exchange built on asynchronous messaging.

## Intent

Enable a **requestor** to send a message and receive a **correlated reply** from a replier over messaging, providing method-call semantics (result or error) while preserving loose coupling and reliability of message channels.

## Also Known As

-   Request/Response
    
-   Synchronous Exchange over Messaging
    
-   RPC over Messages (conceptually related, but Request–Reply need not be tightly coupled or blocking)
    

## Motivation (Forces)

-   Business operations sometimes need a **direct answer** (order quote, availability check, authorization).
    
-   Pure RPC couples clients to transport and availability; **messaging** provides durability, routing, and decoupling.
    
-   Retries, timeouts, and **correlation** must be explicit to avoid orphaned replies and ambiguity.
    
-   Producers/repliers evolve independently; **headers** and **return address** patterns keep topology flexible.
    

## Applicability

Use Request–Reply when:

-   A client requires a **specific result** (data or acknowledgment) from a remote service.
    
-   You want **at-least-once** delivery and buffering but still need a response.
    
-   Services sit behind a **broker** (JMS/AMQP/Kafka) and you don’t want to expose them via synchronous HTTP.
    

Avoid or limit when:

-   The interaction is naturally **event-driven** (fire-and-forget) or can be **eventually consistent**.
    
-   Strict low-latency RPC is required (then consider gRPC/HTTP) and messaging adds avoidable hops.
    

## Structure

```lua
+----------------+                       +----------------+
          |   Requestor    | -- request (correlId) |    Replier     |
          |  (Client App)  | --------------------> | (Service/Handler)
          +----------------+                       +----------------+
                 |                                          |
                 |  <- reply (same correlId)  <-------------|
                 v
          +----------------+
          |  Reply Handler |
          +----------------+

Channels:
  requestChannel (queue/topic) --> replier
  replyChannel   (temp queue / private queue / reply topic) --> requestor
```

## Participants

-   **Requestor:** Sends request, waits for reply (blocking or async).
    
-   **Replier:** Processes request and posts reply.
    
-   **Request Channel:** Where requests arrive.
    
-   **Reply Channel:** Address where the reply is sent (temporary, per-client, or shared).
    
-   **Correlation Identifier:** Uniquely ties reply to request.
    
-   **Timeout/Retry Policy:** Governs waiting and redelivery behavior.
    
-   **Error Mapping:** Conveys failures (headers, error payload, or DLQ).
    

## Collaboration

1.  Requestor creates a message with **Correlation ID** and **Reply-To** address; sends to **Request Channel**.
    
2.  Replier consumes request, performs work, sends reply to **Reply Channel**, copying the **Correlation ID**.
    
3.  Requestor receives from its reply destination, matching on **Correlation ID** (or uses a template that matches internally).
    
4.  On timeout, requestor raises an error; replier errors can appear as fault messages or exceptions.
    

## Consequences

**Benefits**

-   Combines robustness of messaging with familiar request semantics.
    
-   Decouples topology; repliers can scale behind queues and be restarted.
    
-   Works across transports (JMS, AMQP, Kafka).
    

**Liabilities**

-   Adds complexity (reply routes, correlation, timeouts).
    
-   Blocking callers on a message bus can waste resources; prefer **async APIs** when possible.
    
-   Handling retries carefully is required to avoid **duplicate effects** (use **Idempotent Receiver**).
    

## Implementation

-   **Reply destination choices:**
    
    -   **Temporary reply queue** (per-call or per-session, JMS).
        
    -   **Per-service reply queue** (shared, client filters by correlation).
        
    -   **Reply topic** (Kafka with consumer groups and keys).
        
-   **Correlation:**
    
    -   Use **globally unique IDs** (UUID).
        
    -   Mirror to transport-specific headers (e.g., `JMSCorrelationID`, AMQP headers) and keep in your envelope headers too.
        
-   **Timeouts & retries:**
    
    -   Client-side timeout must be < broker redelivery window to avoid late surprises.
        
    -   Use **exponential backoff** on the requestor; replier should be **idempotent**.
        
-   **Error semantics:**
    
    -   Reply with fault payload (error code/message) or use a **DLQ** and notify the client via timeout/compensation.
        
-   **Observability:**
    
    -   Log correlation ID at both sides; emit metrics for latency, timeouts, and error rate; propagate `traceparent`.
        
-   **Security:**
    
    -   Authorize both request and reply channels; scrub sensitive data in replies.
        
-   **Throughput:**
    
    -   Prefer **async APIs** (CompletableFuture, reactive) and bounded concurrency on listeners.
        

---

## Sample Code (Java)

### A) Classic JMS (Jakarta) — Temporary Reply Queue with Correlation

```java
// Maven: jakarta.jms-api, activemq-artemis-jakarta-client
import jakarta.jms.*;
import org.apache.activemq.artemis.jms.client.ActiveMQConnectionFactory;
import java.util.UUID;

public class JmsRequestReplyDemo {

  public static void main(String[] args) throws Exception {
    try (ConnectionFactory cf = new ActiveMQConnectionFactory("tcp://localhost:61616");
         Connection connection = cf.createConnection()) {

      Session session = connection.createSession(false, Session.AUTO_ACKNOWLEDGE);
      Queue requestQ = session.createQueue("pricing.request");
      MessageProducer requestProducer = session.createProducer(requestQ);

      // Replier (service) — normally runs in another process
      MessageConsumer serviceConsumer = session.createConsumer(requestQ);
      serviceConsumer.setMessageListener(msg -> {
        try {
          TextMessage req = (TextMessage) msg;
          String correlationId = req.getJMSCorrelationID();
          Destination replyTo = req.getJMSReplyTo();

          // do work
          String sku = req.getStringProperty("sku");
          String region = req.getStringProperty("region");
          String price = computePrice(sku, region);

          TextMessage reply = session.createTextMessage(price);
          reply.setJMSCorrelationID(correlationId);
          MessageProducer replier = session.createProducer(replyTo);
          replier.send(reply);
        } catch (Exception e) { e.printStackTrace(); }
      });

      connection.start();

      // Requestor
      TemporaryQueue tempReply = session.createTemporaryQueue();
      MessageConsumer replyConsumer = session.createConsumer(tempReply);

      String correlationId = UUID.randomUUID().toString();
      TextMessage request = session.createTextMessage("price-request");
      request.setJMSCorrelationID(correlationId);
      request.setJMSReplyTo(tempReply);
      request.setStringProperty("sku", "ABC-123");
      request.setStringProperty("region", "EU");
      requestProducer.send(request);

      Message reply = replyConsumer.receive(5000); // timeout 5s
      if (reply == null) throw new RuntimeException("timeout");
      if (!correlationId.equals(reply.getJMSCorrelationID()))
        throw new RuntimeException("correlation mismatch");

      System.out.println("Price: " + ((TextMessage) reply).getText());
    }
  }

  private static String computePrice(String sku, String region) { return "19.99"; }
}
```

### B) Spring Kafka — Request–Reply with `ReplyingKafkaTemplate`

```java
// build.gradle: implementation("org.springframework.kafka:spring-kafka"), jackson
@Configuration
class KafkaReqRepConfig {

  @Bean
  public ReplyingKafkaTemplate<String, PriceRequest, PriceReply> replyingKafkaTemplate(
      ProducerFactory<String, PriceRequest> pf,
      ConcurrentMessageListenerContainer<String, PriceReply> repliesContainer) {
    return new ReplyingKafkaTemplate<>(pf, repliesContainer);
  }

  @Bean
  public ConcurrentMessageListenerContainer<String, PriceReply> repliesContainer(
      ConsumerFactory<String, PriceReply> cf) {
    var container = new ConcurrentMessageListenerContainer<>(
        cf, new ContainerProperties("pricing.replies.v1"));
    container.getContainerProperties().setGroupId("price-client");
    return container;
  }
}

@Service
class PriceClient {
  private final ReplyingKafkaTemplate<String, PriceRequest, PriceReply> template;

  PriceClient(ReplyingKafkaTemplate<String, PriceRequest, PriceReply> template) {
    this.template = template;
  }

  public PriceReply getPrice(String sku, String region) throws Exception {
    var req = new PriceRequest(sku, region);
    var record = new ProducerRecord<>("pricing.requests.v1", sku, req);
    record.headers().add("correlationId", UUID.randomUUID().toString().getBytes());
    RequestReplyFuture<String, PriceRequest, PriceReply> fut = template.sendAndReceive(record);
    return fut.get(5, java.util.concurrent.TimeUnit.SECONDS).value(); // timeout
  }
}

@Component
class PriceReplier {
  @KafkaListener(topics = "pricing.requests.v1", groupId = "pricing-service")
  @SendTo("pricing.replies.v1")
  public PriceReply onReq(PriceRequest req, @Header(KafkaHeaders.CORRELATION_ID) byte[] corr) {
    // compute price; ensure idempotency by key (sku+region)
    return new PriceReply(req.sku(), req.region(), java.math.BigDecimal.valueOf(19.99));
  }
}

record PriceRequest(String sku, String region) {}
record PriceReply(String sku, String region, java.math.BigDecimal price) {}
```

### C) Spring Integration `@MessagingGateway` — Method-call facade over Request–Reply

```java
// build.gradle: spring-boot-starter-integration, spring-amqp (or jms), jackson
import org.springframework.integration.annotation.Gateway;
import org.springframework.integration.annotation.MessagingGateway;

@MessagingGateway
public interface PricingGateway {
  @Gateway(requestChannel = "pricing.req", replyChannel = "pricing.rep",
           requestTimeout = 3000, replyTimeout = 5000)
  PriceReply quote(PriceRequest req);
}

@Configuration
@EnableIntegration
class PricingFlowConfig {

  @Bean
  public IntegrationFlow outboundToAmqp(org.springframework.amqp.rabbit.core.RabbitTemplate rabbit) {
    return IntegrationFlows.from("pricing.req")
      .transform(Transformers.toJson())
      .handle(Amqp.outboundGateway(rabbit)
          .routingKey("pricing.request")
          .exchangeName("pricing-ex")
          .replyTimeout(5000))
      .transform(Transformers.fromJson(PriceReply.class))
      .channel("pricing.rep")
      .get();
  }
}
```

---

## Known Uses

-   **Synchronous pricing/quoting** services behind JMS/AMQP in trading and retail.
    
-   **Authorizations** (payment auth, fraud checks) via request–reply over Kafka or RabbitMQ.
    
-   **Back-end orchestration** where a workflow engine requests a step result from a microservice.
    
-   **Mainframe offload**: queues bridge to legacy CICS/IMS services with replies.
    

## Related Patterns

-   **Correlation Identifier:** Mandatory to match replies to requests.
    
-   **Return Address:** Reply destination carried with the request.
    
-   **Messaging Gateway:** Presents a method-like API over Request–Reply.
    
-   **Service Activator / Message Endpoint:** Receive-side handler of requests.
    
-   **Dead Letter Channel / Retry:** Error handling for failed replies/timeouts.
    
-   **Idempotent Receiver:** Guard repliers against duplicate requests.
    
-   **Request–Reply over HTTP:** Sister approach when using synchronous transports.

