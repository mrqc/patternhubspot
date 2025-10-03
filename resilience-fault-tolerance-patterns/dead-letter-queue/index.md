# Dead Letter Queue — Resilience & Fault-Tolerance Pattern

## Pattern Name and Classification

**Name:** Dead Letter Queue (DLQ)  
**Classification:** Resilience / Fault-Tolerance Pattern (Message Handling & Recovery)

## Intent

Prevent **poison messages** (malformed, unprocessable, or permanently failing) from blocking normal processing by **diverting them to a dedicated queue/topic** after a finite number of attempts, so the main flow stays healthy and failures are **quarantined for later analysis or remediation**.

## Also Known As

-   Dead Letter Channel
    
-   Poison Message Queue
    
-   Error Queue / Parking Lot Queue (variant)
    

## Motivation (Forces)

-   **Non-blocking throughput:** A single bad message must not stall a consumer or starve a partition.
    
-   **Operational clarity:** Distinguish transient failures (retry) from permanent ones (route to DLQ).
    
-   **Forensics:** Preserve the **original payload + failure context** for debugging/replay.
    
-   **Compliance:** Some domains require an audit trail of dropped/failed events.
    
-   **Cost control:** Infinite retries or stuck redelivery loops waste compute and I/O.
    

## Applicability

Use a DLQ when:

-   You process messages/events asynchronously (MQ, Kafka, SQS, Pub/Sub).
    
-   Producers/consumers are independent and you can’t guarantee schema compatibility at all times.
    
-   Retries are bounded; after N attempts you must **fail safely**.
    
-   You need to **inspect & replay** failures without impacting the hot path.
    

Avoid / tune differently when:

-   Message loss is unacceptable **and** you can always fix and reprocess inline (rare).
    
-   All failures are transient (network only) and backoff+retry already suffices.
    
-   The platform provides a better **parking lot** pattern (manual triage with delayed retry) that you intend to use.
    

## Structure

```pgsql
┌──────────────┐     success        ┌──────────────┐
Producer │  Main Topic  │ ─────────────────► │   Consumer   │
         └──────┬───────┘                    └──────┬───────┘
                │  on permanent failure              │
                │  (after N retries)                 │
                ▼                                     ▼
         ┌──────────────┐    copy of msg +     ┌──────────────┐
         │   DLQ Topic  │◄── error metadata ───│  DLQ Handler │
         └──────────────┘                        (ops/repair/replay)
```

## Participants

-   **Main Queue/Topic:** Primary stream of work.
    
-   **Consumer:** Processes messages, applies retry policy, and ultimately decides to dead-letter.
    
-   **Dead Letter Queue/Topic:** Quarantine for failed messages (immutable storage).
    
-   **DLQ Handler / Ops Tools:** Dashboards, alerts, triage jobs, replay utilities.
    
-   **Metadata/Headers:** Carry failure cause, stack, retry count, timestamps, schema version, etc.
    

## Collaboration

1.  **Consume → Process → Ack/Commit** on success.
    
2.  **Retry** transient failures with bounded attempts and backoff.
    
3.  **Dead-letter** after limit: publish the original message plus failure metadata to the DLQ; **commit/ack** the failed offset to unblock the main stream.
    
4.  **Observe & Act:** Alert on DLQ rate; ops investigate, fix upstream, or **replay** from DLQ to a **retry topic** or back to main after correction.
    

## Consequences

**Benefits**

-   **Isolation:** Poison messages no longer clog partitions or threads.
    
-   **Operability:** Clear backlog of problematic events for later remediation.
    
-   **Auditability:** Durable trail of failures with rich context.
    
-   **SLO protection:** Keeps latency/throughput of healthy traffic predictable.
    

**Liabilities / Trade-offs**

-   **Operational pipeline required:** Someone must own triage+replay.
    
-   **Storage growth:** DLQ can accumulate; needs retention & governance.
    
-   **Risk of re-poisoning:** Blind replay can reintroduce bad events—require fixes or quarantine staging.
    
-   **Duplication semantics:** Reprocessing must be **idempotent** to avoid side effects.
    

## Implementation

1.  **Define failure policy:** max attempts, which exceptions are **non-retryable**, backoff (exponential + jitter).
    
2.  **Carry context:** When dead-lettering, include headers: `x-retry-count`, `x-exception-class`, `x-exception-msg`, `x-stack`, `x-original-topic`, `x-original-partition`, `x-offset`, `x-timestamp`, `x-schema-version`.
    
3.  **Commit wisely:** After publishing to DLQ, **commit/ack** the original message to prevent endless loops.
    
4.  **Observe:** Emit metrics on retries, DLQ publishes, and per-cause counts; alert on spikes.
    
5.  **Retention & access:** Size DLQ retention; protect PII; consider encryption at rest.
    
6.  **Replay tooling:** Build a **controlled replay** path (rate-limited, idempotent) from DLQ to a *retry topic* or back to main after fixes.
    
7.  **Governance:** Document who owns DLQ triage, SLAs for cleanup, and a runbook.
    

---

## Sample Code (Java)

### Example: Spring for Apache Kafka — Bounded retries + DeadLetterPublishingRecoverer

```java
// build.gradle (relevant dependencies)
// implementation 'org.springframework.kafka:spring-kafka'

import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.common.TopicPartition;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.config.ConcurrentKafkaListenerContainerFactory;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.listener.DefaultErrorHandler;
import org.springframework.kafka.listener.DeadLetterPublishingRecoverer;
import org.springframework.util.backoff.ExponentialBackOffWithMaxRetries;

@Configuration
public class KafkaDlqConfig {

  public static final String MAIN_TOPIC = "orders.v1";
  public static final String DLQ_SUFFIX = ".DLT"; // Dead Letter Topic naming convention

  @Bean
  public DeadLetterPublishingRecoverer dlqRecoverer(KafkaTemplate<Object, Object> template) {
    return new DeadLetterPublishingRecoverer(template, (record, ex) -> {
      // route to "<original-topic>.DLT" with same partition by default
      String dlqTopic = record.topic() + DLQ_SUFFIX;
      return new TopicPartition(dlqTopic, record.partition());
    });
  }

  @Bean
  public DefaultErrorHandler errorHandler(DeadLetterPublishingRecoverer recoverer) {
    var backoff = new ExponentialBackOffWithMaxRetries(3); // 3 retries
    backoff.setInitialInterval(200L);
    backoff.setMultiplier(2.0);
    backoff.setMaxInterval(2_000L);

    var handler = new DefaultErrorHandler(recoverer, backoff);

    // Mark specific exceptions as non-retryable -> immediate DLQ
    handler.addNotRetryableExceptions(
        javax.validation.ConstraintViolationException.class,
        com.fasterxml.jackson.core.JsonParseException.class
    );

    // Optionally enrich headers on DLQ publication
    handler.setRecoverer((record, ex) -> {
      record.headers()
            .add("x-exception-class", ex.getClass().getName().getBytes())
            .add("x-exception-message", String.valueOf(ex.getMessage()).getBytes())
            .add("x-original-topic", record.topic().getBytes());
      // delegate to publisher
      dlqRecoverer(template()).accept(record, ex);
    });

    return handler;
  }

  // Wire the container factory to use our error handler
  @Bean
  public ConcurrentKafkaListenerContainerFactory<String, String> kafkaListenerContainerFactory(
      org.springframework.kafka.core.ConsumerFactory<String, String> consumerFactory,
      DefaultErrorHandler errorHandler) {

    var factory = new ConcurrentKafkaListenerContainerFactory<String, String>();
    factory.setConsumerFactory(consumerFactory);
    factory.setCommonErrorHandler(errorHandler);
    factory.setAckDiscarded(true); // commit offsets when discarded to DLQ
    return factory;
  }

  // Provide KafkaTemplate bean
  @Bean
  public KafkaTemplate<Object, Object> template() {
    return new KafkaTemplate<>(/* producerFactory bean here */);
  }
}
```

```java
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Service;

@Service
public class OrderConsumer {

  @KafkaListener(topics = KafkaDlqConfig.MAIN_TOPIC, groupId = "orders-processor")
  public void onMessage(ConsumerRecord<String, String> record) {
    var payload = record.value();

    // Example validation that might throw
    if (!payload.contains("\"orderId\"")) {
      throw new IllegalArgumentException("Missing orderId");
    }

    // Process business logic here...
  }
}
```

**What this gives you**

-   Up to **3 retries** with exponential backoff on transient errors.
    
-   Immediate **dead-lettering** for non-retryable exceptions (e.g., schema/validation).
    
-   DLQ messages land in `<originalTopic>.DLT` with original headers + error context; the failed offset is **committed**, unblocking the partition.
    
-   You can add a separate **DLQ consumer** to alert, store, or **replay** after fixes.
    

---

## Known Uses

-   **Kafka / Pulsar:** `<topic>.DLT` or dedicated DLQ topics managed by consumer frameworks (Spring Kafka, Debezium, Kafka Connect DLQ).
    
-   **RabbitMQ:** Queue bound to an exchange with `x-dead-letter-exchange` / `x-dead-letter-routing-key`.
    
-   **AWS SQS/SNS:** Native redrive policy to a DLQ after `maxReceiveCount`.
    
-   **Azure Service Bus / GCP Pub/Sub:** Built-in dead-lettering with reason & description maintained in metadata.
    
-   **ETL pipelines:** Malformed rows/events routed to an **error stream** for investigation.
    

## Related Patterns

-   **Retry with Exponential Backoff & Jitter:** Attempts before dead-lettering; ensure bounded retries.
    
-   **Circuit Breaker:** Protects the **caller**; DLQ protects the **stream** from poison data.
    
-   **Bulkhead:** Isolate processing pools so spikes or poison messages don’t starve unrelated work.
    
-   **Idempotent Consumer / Exactly-Once Effects:** Make replay safe.
    
-   **Schema Evolution / Consumer-Driven Contracts:** Reduce DLQ volume by preventing breaking changes.
    
-   **Parking Lot Queue:** Manual triage queue for later reprocessing with human approval.
    
-   **Competing Consumers / Queue-based Load Leveling:** Complementary to keep throughput stable despite DLQ detours.
    

**Practical tip:** **Dead-letter early, debug offline.** Keep hot paths fast and predictable; invest in DLQ observability and safe replay to close the loop.

