# Dead Letter Queue — Microservice Pattern

## Pattern Name and Classification

-   **Name:** Dead Letter Queue (DLQ)
    
-   **Classification:** Reliability & Resilience Pattern for event-driven/messaging systems
    

## Intent

Provide a **quarantine channel** for messages that cannot be processed successfully after configured retries, so the main flow stays healthy while failed messages can be **inspected, corrected, and replayed** without data loss.

## Also Known As

-   Dead Letter Channel
    
-   Poison Message Queue / Topic
    
-   Error Queue / Parking Lot Queue
    

## Motivation (Forces)

-   **Reliability vs. Throughput:** Poison messages can repeatedly fail and throttle consumers; isolating them preserves throughput.
    
-   **Diagnosis:** Operators need a **forensic trail** (payload + headers + error metadata) to debug downstream.
    
-   **Backpressure:** Infinite retries cause hot loops and cost spikes; bounded retries + DLQ cap blast radius.
    
-   **Data Integrity:** Prefer to **not drop** messages; keep them until explicitly handled (replay or manual fix).
    
-   **Regulatory/SLAs:** Prove that unprocessed events are retained and handled with auditable procedures.
    

## Applicability

Use when:

-   You have asynchronous communication (Kafka, RabbitMQ, SQS, Pub/Sub, NATS, etc.).
    
-   Failures may be **non-transient** (bad schema, missing reference, validation errors) or **long-lived transient** (downstream outage exceeding retry window).
    
-   You need operational isolation and **post-failure workflows** (alerting, triage, replay).
    

Avoid or de-prioritize when:

-   Messages are ephemeral and can be safely dropped on failure (e.g., best-effort telemetry).
    
-   The system is simple enough that **on-error drop** or synchronous compensation is acceptable.
    

## Structure

-   **Primary Queue/Topic:** Production stream for normal processing.
    
-   **Consumer(s):** Process messages; apply **retry policy** (in-memory or via dedicated retry topics/queues).
    
-   **DLQ:** Separate queue/topic for permanently failed messages.
    
-   **Metadata:** Failure reason, stack trace, source partition/offset or delivery tag, first/last attempt time.
    
-   **Ops Tools:** Alerts, dashboards, triage UI, replay tool to move messages back to primary or a retry topic.
    

```sql
┌───────────────┐
Producer →│ Primary Topic │→ Consumer → Success
          └───────┬───────┘
                  │ (exhausted retries / non-retryable)
                  ▼
             ┌────────┐
             │  DLQ   │ → Triage/Alert → Fix → Replay → Primary/Retry Topic
             └────────┘
```

## Participants

-   **Producer:** Publishes domain events/commands.
    
-   **Consumer:** Attempts processing, applies retry/backoff/idempotency.
    
-   **Retry Mechanism:** In-memory retry, retry topics, or broker-level redelivery.
    
-   **Dead Letter Queue/Topic:** Final holding area for failed messages.
    
-   **Ops/Triage Service:** Observes DLQ, surfaces errors, supports repair & replay.
    
-   **Storage/Registry (optional):** Schema registry or payload validation aiding root-cause analysis.
    

## Collaboration

1.  Consumer reads from **Primary**.
    
2.  On failure, it retries (bounded attempts with backoff; optional retry topics).
    
3.  If retries are exhausted or error is non-retryable (e.g., validation), the message is **published to DLQ** with diagnostic headers.
    
4.  Ops monitors DLQ, **triages** items, corrects data or fixes code, and **replays** messages (to primary or a dedicated replay topic) once safe.
    

## Consequences

**Benefits**

-   Maintains **throughput & availability** of primary flow.
    
-   Ensures **no data loss** and enables forensic debugging.
    
-   Supports **safe, controlled replay** after hotfixes or data repair.
    

**Liabilities**

-   Added **operational complexity** (separate queues, dashboards, replay tooling).
    
-   Risk of **DLQ accumulation** (“graveyard”) without strict SLOs and ownership.
    
-   **Ordering semantics** can be impacted on replay; must design idempotency.
    
-   Sensitive data may land in DLQ; requires **access controls & retention policies**.
    

## Implementation

1.  **Define Failure Policy**
    
    -   Classify exceptions: **retryable** (e.g., timeouts) vs **non-retryable** (validation, deserialization).
        
    -   Set **max attempts**, **backoff**, and **circuit breakers**.
        
2.  **Design DLQ Schema**
    
    -   Include **original payload**, headers/attributes, source (topic/partition/offset or queue/deliveryTag), timestamps, **error kind**, and stack trace (bounded).
        
3.  **Broker-Specific Setup**
    
    -   **Kafka:** Use a **dead-letter topic** (`<topic>.DLQ`); publish via error handler.
        
    -   **RabbitMQ:** Configure **DLX** (dead-letter exchange) and DLQ with routing key.
        
    -   **AWS SQS:** Configure **Redrive policy** to DLQ with `maxReceiveCount`.
        
    -   **GCP Pub/Sub:** Assign **dead-letter topic** with `maxDeliveryAttempts`.
        
4.  **Observability**
    
    -   Metrics: DLQ rate, retry counts, age of oldest DLQ message, replay success ratio.
        
    -   Alerts on thresholds (e.g., > N messages or oldest > X minutes).
        
5.  **Replay Strategy**
    
    -   Build a **replayer** service/CLI that reads from DLQ, optionally **sanitizes/transforms**, and publishes to a retry/primary topic.
        
    -   Enforce **idempotency keys** to avoid duplicates on downstream.
        
6.  **Governance**
    
    -   Ownership & SLO for DLQ emptying, **retention windows**, PII handling (encrypt at rest, scrub fields).
        

## Sample Code (Java, Spring Boot, Spring for Apache Kafka)

> Shows a consumer with bounded retries and a **DeadLetterPublishingRecoverer** that routes to `<topic>.DLQ`. Also includes a simple replay endpoint.

```xml
<!-- pom.xml (snippets) -->
<dependencies>
  <dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter</artifactId>
  </dependency>
  <dependency>
    <groupId>org.springframework.kafka</groupId>
    <artifactId>spring-kafka</artifactId>
  </dependency>
  <dependency>
    <groupId>com.fasterxml.jackson.core</groupId>
    <artifactId>jackson-databind</artifactId>
  </dependency>
</dependencies>
```

```properties
# application.properties
spring.kafka.bootstrap-servers=PLAINTEXT://kafka:9092
spring.kafka.consumer.group-id=orders-consumer
spring.kafka.consumer.auto-offset-reset=earliest
spring.kafka.consumer.properties.spring.json.trusted.packages=*
app.topics.orders=orders.v1
app.topics.orders.dlq=orders.v1.DLQ
```

```java
// KafkaConfig.java
package com.example.dlq;

import org.apache.kafka.clients.admin.NewTopic;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.TopicPartition;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.annotation.EnableKafka;
import org.springframework.kafka.config.TopicBuilder;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.listener.DeadLetterPublishingRecoverer;
import org.springframework.kafka.listener.DefaultErrorHandler;
import org.springframework.util.backoff.ExponentialBackOffWithMaxRetries;

@Configuration
@EnableKafka
public class KafkaConfig {

  @Bean
  NewTopic orders(@Value("${app.topics.orders}") String topic) {
    return TopicBuilder.name(topic).partitions(6).replicas(1).build();
  }

  @Bean
  NewTopic ordersDlq(@Value("${app.topics.orders.dlq}") String topic) {
    return TopicBuilder.name(topic).partitions(6).replicas(1).build();
  }

  @Bean
  DefaultErrorHandler errorHandler(KafkaTemplate<Object, Object> template,
                                   @Value("${app.topics.orders.dlq}") String dlq) {
    DeadLetterPublishingRecoverer recoverer = new DeadLetterPublishingRecoverer(template,
        (record, ex) -> {
          // route all failures to the DLQ topic, preserve partition for locality
          TopicPartition tp = new TopicPartition(dlq, record.partition());
          return tp;
        }) {
      @Override
      public void accept(ProducerRecord<Object, Object> out, Exception ex) {
        // Enrich headers for forensics
        out.headers()
           .add("x-exception-class", ex.getClass().getName().getBytes())
           .add("x-exception-message", String.valueOf(ex.getMessage()).getBytes());
      }
    };
    ExponentialBackOffWithMaxRetries backoff = new ExponentialBackOffWithMaxRetries(3);
    backoff.setInitialInterval(500);
    backoff.setMultiplier(2.0);
    backoff.setMaxInterval(5_000);
    DefaultErrorHandler handler = new DefaultErrorHandler(recoverer, backoff);

    // classify non-retryable exceptions
    handler.addNotRetryableExceptions(IllegalArgumentException.class);
    return handler;
  }
}
```

```java
// OrderEvent.java
package com.example.dlq;

public record OrderEvent(String orderId, String status, long amountCents) { }
```

```java
// OrderConsumer.java
package com.example.dlq;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

@Component
public class OrderConsumer {
  private final ObjectMapper mapper = new ObjectMapper();

  @KafkaListener(topics = "${app.topics.orders}", containerFactory = "kafkaListenerContainerFactory")
  public void onMessage(ConsumerRecord<String, String> record) throws Exception {
    OrderEvent evt = mapper.readValue(record.value(), OrderEvent.class);

    // Example business validation
    if (evt.amountCents() <= 0) {
      throw new IllegalArgumentException("amountCents must be > 0");
    }

    // Simulate transient error
    if ("PAYMENT_PENDING".equals(evt.status()) && Math.random() < 0.2) {
      throw new RuntimeException("Transient downstream error");
    }

    // Process successfully...
    // e.g., update local DB, emit domain events, etc.
  }
}
```

```java
// DlqReplayController.java
package com.example.dlq;

import java.time.Duration;
import java.util.List;

import org.apache.kafka.clients.consumer.*;
import org.apache.kafka.common.TopicPartition;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.kafka.core.DefaultKafkaConsumerFactory;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/admin/replay")
public class DlqReplayController {

  private final KafkaTemplate<String, String> template;
  private final DefaultKafkaConsumerFactory<String, String> consumerFactory;
  private final String sourceDlq;
  private final String targetTopic;

  public DlqReplayController(KafkaTemplate<String, String> template,
                             DefaultKafkaConsumerFactory<String, String> consumerFactory,
                             @Value("${app.topics.orders.dlq}") String dlq,
                             @Value("${app.topics.orders}") String primary) {
    this.template = template;
    this.consumerFactory = consumerFactory;
    this.sourceDlq = dlq;
    this.targetTopic = primary;
  }

  @PostMapping
  public String replay(@RequestParam(defaultValue = "100") int max) {
    try (Consumer<String, String> cons = consumerFactory.createConsumer("dlq-replayer", "dlq-replayer")) {
      cons.subscribe(List.of(sourceDlq));
      int sent = 0;
      while (sent < max) {
        ConsumerRecords<String, String> records = cons.poll(Duration.ofSeconds(1));
        if (records.isEmpty()) break;
        for (ConsumerRecord<String, String> r : records) {
          // Optionally sanitize/transform before replay
          template.send(targetTopic, r.key(), r.value());
          sent++;
          if (sent >= max) break;
        }
        cons.commitSync();
      }
      return "Replayed " + sent + " message(s) from " + sourceDlq + " to " + targetTopic;
    }
  }
}
```

```java
// ListenerContainerFactoryConfig.java
package com.example.dlq;

import org.apache.kafka.common.serialization.StringDeserializer;
import org.apache.kafka.common.serialization.StringSerializer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.config.ConcurrentKafkaListenerContainerFactory;
import org.springframework.kafka.core.*;

import java.util.Map;

@Configuration
public class ListenerContainerFactoryConfig {

  @Bean
  public ProducerFactory<Object, Object> producerFactory() {
    return new DefaultKafkaProducerFactory<>(Map.of(
      org.apache.kafka.clients.producer.ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class,
      org.apache.kafka.clients.producer.ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, StringSerializer.class,
      org.apache.kafka.clients.producer.ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, "kafka:9092"
    ));
  }

  @Bean
  public KafkaTemplate<Object, Object> kafkaTemplate() {
    return new KafkaTemplate<>(producerFactory());
  }

  @Bean
  public DefaultKafkaConsumerFactory<String, String> consumerFactory() {
    return new DefaultKafkaConsumerFactory<>(Map.of(
      org.apache.kafka.clients.consumer.ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class,
      org.apache.kafka.clients.consumer.ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class,
      org.apache.kafka.clients.consumer.ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, "kafka:9092",
      org.apache.kafka.clients.consumer.ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest",
      org.springframework.kafka.support.serializer.JsonDeserializer.TRUSTED_PACKAGES, "*"
    ));
  }

  @Bean
  public ConcurrentKafkaListenerContainerFactory<String, String> kafkaListenerContainerFactory(
      DefaultKafkaConsumerFactory<String, String> consumerFactory,
      org.springframework.kafka.listener.DefaultErrorHandler errorHandler) {
    ConcurrentKafkaListenerContainerFactory<String, String> factory = new ConcurrentKafkaListenerContainerFactory<>();
    factory.setConsumerFactory(consumerFactory);
    factory.setCommonErrorHandler(errorHandler);
    factory.setConcurrency(3);
    return factory;
  }
}
```

> **Notes:**
>
> -   `DefaultErrorHandler` (Spring Kafka) retries transient errors, routes unrecoverable ones to `<topic>.DLQ`.
>
> -   The replay controller is a minimal example; in production, guard with authn/z, apply **rate limiting**, and support **filtering by error type/time window**.
>
> -   Ensure **idempotency** on downstream handlers to avoid duplicates on replay.
>

### Alternative Broker Config Snippets (non-Java, for completeness)

-   **RabbitMQ (DLX):** declare queue with args: `x-dead-letter-exchange=dlx`, `x-dead-letter-routing-key=orders.v1.DLQ`.

-   **AWS SQS:** set RedrivePolicy `{ "deadLetterTargetArn": "...:queue:orders-dlq", "maxReceiveCount": 5 }`.


## Known Uses

-   **AWS SQS/SNS**, **GCP Pub/Sub**, **Azure Service Bus**: native dead-lettering with redrive options.

-   **Kafka** ecosystems: DLQ topics with Spring Kafka, Kafka Streams, or Connect error-handling (e.g., DeadLetterQueueReporter).

-   **RabbitMQ**: DLX pattern widely adopted for microservices with Spring AMQP or MassTransit.


## Related Patterns

-   **Retry (Exponential Backoff, Jitter):** First line of defense before DLQ.

-   **Poison Message Handling:** Detection and classification of non-retryable failures.

-   **Idempotent Consumer:** Safe reprocessing after replay.

-   **Transactional Outbox & CDC:** Ensure producer → broker delivery reliability to avoid “lost before DLQ” cases.

-   **Circuit Breaker/Bulkhead:** Prevent cascading failures that would flood DLQ.

-   **Saga:** Coordinates recovery/compensation when failed commands/events impact business workflows.
