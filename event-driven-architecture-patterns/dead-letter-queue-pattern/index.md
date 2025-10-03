# Dead Letter Queue — Event-Driven Architecture Pattern

## Pattern Name and Classification

**Name:** Dead Letter Queue (DLQ)  
**Classification:** Reliability / Error-Handling pattern for event-driven systems.

## Intent

Quarantine **messages that cannot be processed successfully** after one or more delivery attempts by routing them to a **separate queue/topic** for inspection, replay, or compensating action—**without blocking** the main flow.

## Also Known As

-   Dead Letter Channel (DLC)
    
-   Poison Message Queue
    
-   Parking Lot Queue
    
-   Error Queue
    

## Motivation (Forces)

-   At-least-once delivery and transient faults cause **retries**; some messages keep failing (“poison messages”).
    
-   We must **protect throughput** and avoid starving healthy work.
    
-   Operators need a **clear place** to analyze failure causes, preserve evidence, and choose between **fix & replay** or **discard**.
    

**Forces to balance**

-   How many **retries** and what **backoff** before DLQ?
    
-   Which **diagnostics** to capture (payload, headers, exception, stack, attempts, timestamp)?
    
-   Operational **SLA**: automatic replay vs. manual triage; retention limits and cost.
    

## Applicability

Use a DLQ when:

-   You run with **at-least-once** semantics and want to isolate irrecoverable messages.
    
-   You need **post-mortem** visibility and the ability to **reprocess** after fixes.
    
-   You want to prevent **poison-pill loops** from clogging the main queue.
    

Avoid or limit when:

-   You can guarantee strict input validation at the edge and prefer **fail-fast drop**.
    
-   Legal/PII constraints forbid storing sensitive payloads—use **redaction** or **hashing** instead.
    

## Structure

```lua
+-----------------+
Inbound Channel -->|  Consumer/Handler|--OK--> Ack/Commit
                   |  (retries, backoff)
                   +--------+--------+
                            |
                          FAIL (exceeded attempts / non-retriable)
                            v
                      +-----------+
                      |   DLQ     | --> Triage / Replay Tool / Archive
                      +-----------+
```

## Participants

-   **Producer:** Sends original messages.
    
-   **Consumer/Handler:** Processes with retry/backoff logic.
    
-   **Primary Queue/Topic:** Main work channel.
    
-   **Dead Letter Queue/Topic:** Quarantine destination.
    
-   **DLQ Publisher:** Moves failed messages with diagnostic metadata.
    
-   **Triage/Replay Tooling:** Operators and automation to inspect & re-drive.
    

## Collaboration

1.  Consumer receives a message and attempts processing with configured retry/backoff.
    
2.  If processing **succeeds**, commit/ack.
    
3.  If processing **continually fails** or is marked **non-retriable**, send the message (plus diagnostics) to the **DLQ** and optionally ack the original (or let broker move it).
    
4.  Operators (or automation) **inspect** DLQ messages and either **fix-and-replay**, **compensate**, or **discard**.
    

## Consequences

**Benefits**

-   Protects **throughput** and **stability** of the main flow.
    
-   Provides a **forensic trail** and a safe place for **manual recovery**.
    
-   Enables **targeted replay** after bug fixes or data corrections.
    

**Liabilities**

-   DLQ can become a **black hole** without ownership and SLAs.
    
-   Storing payloads may raise **security/PII** concerns.
    
-   Excessive reliance on DLQ may hide upstream **validation/modeling** issues.
    

## Implementation

-   **Retry policy:** max attempts, exponential backoff, jitter; classify **retriable vs. fatal** errors.
    
-   **DLQ envelope:** carry diagnostic headers: `originalTopic/Queue`, `originalPartition`, `offset/seq`, `firstSeenTs`, `lastError`, `attempts`, `stack`, `correlationId`, `messageId`, `schemaVersion`.
    
-   **Security/Compliance:** redact PII or store **pointer** (object storage key) instead of full payload. Encrypt at rest.
    
-   **Replay:** define **replay routes** (DLQ → original) with **de-dup** and **rate limits**; tag replays (`x-replayed=true`).
    
-   **Monitoring:** DLQ depth, arrival rate, top error causes, time-to-clear.
    
-   **Ownership:** assign DLQ to a team; set **retention** and alert thresholds.
    
-   **Broker support:**
    
    -   **RabbitMQ/SQS/Artemis:** native DLX/DLQ with TTL/max-retries.
        
    -   **Kafka:** use a **dead-letter topic**; publish failed records explicitly (or use framework DLT).
        

---

## Sample Code (Java)

### A) Spring Kafka — Error handling with Dead Letter **Topic** + retry backoff

```java
// build.gradle: implementation("org.springframework.kafka:spring-kafka"), implementation("com.fasterxml.jackson.core:jackson-databind")
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.springframework.context.annotation.*;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.kafka.core.*;
import org.springframework.kafka.listener.*;
import org.springframework.kafka.support.serializer.ErrorHandlingDeserializer;
import org.springframework.kafka.support.Acknowledgment;
import org.springframework.stereotype.Component;

@Configuration
class KafkaDlqConfig {

  // Error handler: 3 attempts with backoff, then publish to DLT
  @Bean
  DefaultErrorHandler errorHandler(KafkaTemplate<String, byte[]> template) {
    var backoff = new org.springframework.util.backoff.ExponentialBackOff(500, 2.0);
    backoff.setMaxInterval(5000);
    DefaultErrorHandler h = new DefaultErrorHandler(
        new org.springframework.kafka.listener.DeadLetterPublishingRecoverer(template,
          (rec, ex) -> new org.apache.kafka.common.TopicPartition(rec.topic() + ".DLT", rec.partition())),
        backoff);
    // classify certain exceptions as non-retriable
    h.addNotRetryableExceptions(IllegalArgumentException.class);
    return h;
  }
}

@Component
class WorkConsumer {

  private final ObjectMapper json = new ObjectMapper();

  // All app instances with the same groupId compete; failed records go to topic.DLT
  @KafkaListener(topics = "orders.events.v1", groupId = "orders-workers",
                 properties = {
                   "key.deserializer=org.apache.kafka.common.serialization.StringDeserializer",
                   "value.deserializer=org.apache.kafka.common.serialization.ByteArrayDeserializer",
                   // safe wrapper to avoid poison deserialization killing the thread
                   "value.deserializer.delegate.class=org.apache.kafka.common.serialization.ByteArrayDeserializer"
                 })
  public void onMessage(ConsumerRecord<String, byte[]> rec, Acknowledgment ack) throws Exception {
    OrderEvent evt = json.readValue(rec.value(), OrderEvent.class);

    // Example: treat impossible state as non-retriable
    if (evt.qty() < 0) throw new IllegalArgumentException("negative qty");

    // Your business logic may throw; handler above will retry then route to DLT
    handle(evt);
    ack.acknowledge();
  }

  private void handle(OrderEvent evt) {
    // do work; idempotent by evt.id()
  }

  public record OrderEvent(String id, String type, int qty) {}
}
```

**What gets written to `orders.events.v1.DLT`:** the original payload plus headers added by Spring Kafka such as `kafka_dlt-exception-fqcn`, `kafka_dlt-exception-message`, `kafka_dlt-original-topic`, `kafka_dlt-original-partition`, `kafka_dlt-original-offset`, and attempt count—ideal for triage and replay.

---

### B) RabbitMQ — DLX/DLQ with time-based retry (backoff via TTL)

```java
// build.gradle: implementation("org.springframework.boot:spring-boot-starter-amqp"), jackson
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.amqp.core.*;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.context.annotation.*;
import org.springframework.stereotype.Component;

@Configuration
class AmqpDlqConfig {

  // Primary queue bound to DLX
  @Bean Queue workQ() {
    return QueueBuilder.durable("work.q")
        .withArgument("x-dead-letter-exchange", "dlx.ex")
        .withArgument("x-dead-letter-routing-key", "work.dlq")
        .build();
  }

  // Retry queue with TTL; expired messages go back to primary (for backoff)
  @Bean Queue retryQ() {
    return QueueBuilder.durable("work.retry.q")
        .withArgument("x-message-ttl", 2000) // 2s delay; use multiple tiers for backoff
        .withArgument("x-dead-letter-exchange", "work.ex")
        .withArgument("x-dead-letter-routing-key", "work")
        .build();
  }

  @Bean Queue dlq() { return QueueBuilder.durable("work.dlq").build(); }

  @Bean DirectExchange workEx() { return new DirectExchange("work.ex"); }
  @Bean DirectExchange dlxEx()  { return new DirectExchange("dlx.ex"); }

  @Bean Binding workBind()  { return BindingBuilder.bind(workQ()).to(workEx()).with("work"); }
  @Bean Binding retryBind() { return BindingBuilder.bind(retryQ()).to(workEx()).with("work.retry"); }
  @Bean Binding dlqBind()   { return BindingBuilder.bind(dlq()).to(dlxEx()).with("work.dlq"); }
}

@Component
class AmqpHandler {
  private final ObjectMapper json = new ObjectMapper();
  private final RabbitTemplate amqp;

  AmqpHandler(RabbitTemplate amqp) { this.amqp = amqp; }

  @RabbitListener(queues = "work.q")
  public void handle(byte[] body, org.springframework.amqp.core.Message message) throws Exception {
    var evt = json.readValue(body, OrderEvent.class);
    try {
      if (evt.qty() < 0) throw new IllegalArgumentException("non-retriable");

      doWork(evt);
    } catch (IllegalArgumentException nonRetryable) {
      // send straight to DLQ with diagnostics
      var props = MessagePropertiesBuilder.newInstance()
          .setHeader("error", nonRetryable.getMessage())
          .setHeader("originalRoutingKey", message.getMessageProperties().getReceivedRoutingKey())
          .build();
      amqp.send("dlx.ex", "work.dlq", new Message(body, props));
    } catch (Exception retriable) {
      // route to retry queue (will TTL then return to main)
      amqp.convertAndSend("work.ex", "work.retry", evt);
    }
  }

  private void doWork(OrderEvent evt) { /* ... */ }
  record OrderEvent(String id, int qty) {}
}
```

**Flow:** main queue → (failure) → retry queue (delayed via TTL) → main queue (retries N times per policy) → **DLQ** via DLX when exhausted or non-retriable.

---

## Known Uses

-   **E-commerce ingestion:** malformed events routed to DLQ for data fixes and replay.
    
-   **Payments/ledger:** out-of-range or schema-mismatched transactions quarantined for manual review.
    
-   **IoT pipelines:** device outliers or corrupt payloads parked to DLQ while healthy telemetry flows.
    
-   **ETL/CDC:** schema evolution hiccups isolated; replay after connector update.
    

## Related Patterns

-   **Retry / Exponential Backoff:** Attempt recovery before quarantining.
    
-   **Idempotent Receiver:** Safe replay from DLQ without duplicate effects.
    
-   **Message Filter / Validator:** Reject early; reduce DLQ volume by validating at ingress.
    
-   **Message Store:** Persist diagnostics; DLQ may be backed by a store + index.
    
-   **Poison Message Handling:** Specialized handling for permanently failing messages.
    
-   **Compensating Transaction:** If a DLQ’d message had partial effects, compensate as part of recovery.
    
-   **Operational Dashboard:** Not a pattern, but essential—own the DLQ and set SLAs for triage & replay.

