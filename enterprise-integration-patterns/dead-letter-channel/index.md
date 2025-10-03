# Dead Letter Channel (Enterprise Integration Pattern)

## Pattern Name and Classification

**Name:** Dead Letter Channel (DLC)  
**Classification:** Enterprise Integration Pattern (Reliability / Error Handling / Message Routing)

---

## Intent

When a message **cannot be processed successfully** after configured retries (or is malformed), **route it to a special channel**—the **Dead Letter Channel**—so normal traffic continues, the error is **tracked** and **remediated** later (inspect, fix, redrive, or discard).

---

## Also Known As

-   Dead Letter Queue (DLQ)
    
-   Poison Message Channel
    
-   Parking Lot Queue
    

---

## Motivation (Forces)

-   Some messages will **never** succeed (malformed schema, missing reference, business rule violation).
    
-   Endless retries or crashes **block** the pipeline and amplify incidents.
    
-   Operators need a **safe place** to store failed messages for **diagnosis** and **manual or automated redrive**.
    
-   Compliance often requires **auditability** of failures.
    

**Forces to balance**

-   **Detection**: distinguish **transient** vs **permanent** failures.
    
-   **Retry policy**: max attempts, backoff, jitter.
    
-   **Observability**: retain enough context (headers, stack, attempt count).
    
-   **Privacy**: PII in failure payloads ↔ retention limits and encryption.
    
-   **Redrive safety**: avoid replay storms and duplicate side-effects.
    

---

## Applicability

Use a Dead Letter Channel when:

-   Processing is **at-least-once** and some messages may be **poison**.
    
-   You must **isolate** bad messages to protect throughput.
    
-   You need **operational workflows** to inspect and redrive with fixes.
    

Avoid or limit when:

-   The failure must **fail the whole transaction** (strong consistency) and no isolation is acceptable.
    
-   **Lossy** flows where dropping on floor is allowed (then use a **Discard Channel** with metrics).
    

---

## Structure

-   **Input Channel** → **Consumer/Processor** → (**Retry(s)**) → **Success Output**  
    ↘ **Dead Letter Channel (DLQ)**
    
-   **DLQ Topic/Queue:** Retains failed message + metadata.
    
-   **DLQ Consumer/Tooling:** Explorer, notifier, redriver.
    
-   **Metadata:** failure reason, stack trace/summary, attempt count, first/last failure timestamps, original topic/partition/offset.
    

---

## Participants

-   **Producer(s)**: publish original messages.
    
-   **Primary Consumer/Processor**: attempts work, applies retry policy.
    
-   **Retry Mechanism**: time-based or topic-based backoff.
    
-   **Dead Letter Publisher**: writes to DLQ with context.
    
-   **Ops/Redrive Tool**: inspects DLQ, fixes root cause, republishes to original channel or alternate route.
    

---

## Collaboration

1.  Message arrives; processor handles it.
    
2.  On failure, **retry** with exponential backoff up to **maxAttempts**.
    
3.  If all attempts fail or failure is **non-retriable**, publish the **original message** plus **error metadata** to the **DLQ**.
    
4.  Alerts/metrics fire; operators inspect DLQ entries.
    
5.  After fix (code/data), a **redriver** republishes messages from DLQ back to the original topic (or a **quarantine** topic), often with **idempotency** guards.
    

---

## Consequences

**Benefits**

-   **Protects throughput** by quarantining poison messages.
    
-   Provides **audit trail** and **operational handle** for failures.
    
-   Enables controlled **redrive** after remediation.
    

**Liabilities**

-   **Operational overhead**: retention, dashboards, redrive procedures.
    
-   Risk of **data leaks** if sensitive payloads land in DLQ; need masking/encryption.
    
-   **Duplicate effects** possible on redrive—consumers must be **idempotent**.
    
-   Misclassification of transient vs permanent failures can either **flood DLQ** or **block pipelines**.
    

---

## Implementation

**Guidelines**

-   **Classify errors**:
    
    -   *Transient* → retry with **exponential backoff + jitter**.
        
    -   *Permanent* (validation, schema, missing required reference) → **DLQ immediately**.
        
-   **Propagate context**: include original topic/partition/offset, headers, attempt count, error code, stack (or hash), processing node, timestamps.
    
-   **Security/Privacy**: mask PII in error details; consider encrypting DLQ payloads; set **retention**.
    
-   **Observability**: metrics for retry counts, DLQ rate, age of oldest DLQ message; alerts on thresholds.
    
-   **Redrive**: implement a separate, rate-limited tool; mark redriven messages (e.g., `X-Redrive-Count`) to avoid loops.
    
-   **Idempotency**: business handler must dedupe (e.g., by `messageId` or business key + version).
    
-   **Naming**: `<topic>.dlq` or `<queue>.DLQ` and optionally staged retry topics: `<topic>.retry.5s`, `.1m`, `.10m`.
    

---

## Sample Code (Java – Kafka: consumer with retries + DLQ publisher + redriver)

> The same ideas map to RabbitMQ (dead-letter exchange with `x-dead-letter-exchange`) or SQS (DLQ with redrive policy).

### 1) Processor with retry & DLQ

```java
import org.apache.kafka.clients.consumer.*;
import org.apache.kafka.clients.producer.*;
import org.apache.kafka.common.header.internals.RecordHeader;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.apache.kafka.common.serialization.StringSerializer;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.ThreadLocalRandom;

public final class OrdersProcessorWithDlq {

    private final Consumer<String, String> consumer;
    private final Producer<String, String> producer;
    private final String topic;
    private final String dlqTopic;

    private final int maxAttempts = 5;
    private final long baseBackoffMs = 200; // exponential base

    public OrdersProcessorWithDlq(String bootstrap, String groupId, String topic) {
        this.topic = topic;
        this.dlqTopic = topic + ".dlq";

        Properties cp = new Properties();
        cp.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, bootstrap);
        cp.put(ConsumerConfig.GROUP_ID_CONFIG, groupId);
        cp.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class.getName());
        cp.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class.getName());
        cp.put(ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, "false");
        cp.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest");
        this.consumer = new KafkaConsumer<>(cp);

        Properties pp = new Properties();
        pp.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, bootstrap);
        pp.put(ProducerConfig.ACKS_CONFIG, "all");
        pp.put(ProducerConfig.RETRIES_CONFIG, 3);
        this.producer = new KafkaProducer<>(pp, new StringSerializer(), new StringSerializer());
    }

    public void run() {
        consumer.subscribe(List.of(topic));
        while (true) {
            ConsumerRecords<String, String> records = consumer.poll(Duration.ofSeconds(1));
            Map<TopicPartition, OffsetAndMetadata> toCommit = new HashMap<>();

            for (TopicPartition tp : records.partitions()) {
                for (ConsumerRecord<String, String> rec : records.records(tp)) {
                    boolean success = processWithRetry(rec);
                    // commit offset (advance) whether success or DLQ’d, to prevent blocking
                    toCommit.put(tp, new OffsetAndMetadata(rec.offset() + 1));
                }
            }
            if (!toCommit.isEmpty()) consumer.commitSync(toCommit);
        }
    }

    private boolean processWithRetry(ConsumerRecord<String, String> rec) {
        int attempt = 0;
        while (true) {
            try {
                handleBusiness(rec.key(), rec.value());
                return true;
            } catch (TransientException te) {
                attempt++;
                if (attempt >= maxAttempts) {
                    publishToDlq(rec, "transient_max_retries", te);
                    return false;
                }
                sleepBackoff(attempt);
            } catch (PermanentException pe) {
                publishToDlq(rec, "permanent_error", pe);
                return false;
            } catch (Exception unknown) {
                attempt++;
                if (attempt >= maxAttempts) {
                    publishToDlq(rec, "unknown_max_retries", unknown);
                    return false;
                }
                sleepBackoff(attempt);
            }
        }
    }

    private void handleBusiness(String key, String value) throws Exception {
        // Replace with real logic. Throw PermanentException on validation/business rule failures.
        if (value.contains("bad-schema")) throw new PermanentException("invalid schema");
        if (value.contains("flaky") && ThreadLocalRandom.current().nextInt(4) != 0)
            throw new TransientException("upstream timeout");
        // success path...
        System.out.printf("OK key=%s val=%s%n", key, value);
    }

    private void publishToDlq(ConsumerRecord<String, String> rec, String reason, Exception e) {
        var headers = new HeadersBuilder()
                .add("x-original-topic", rec.topic())
                .add("x-original-partition", String.valueOf(rec.partition()))
                .add("x-original-offset", String.valueOf(rec.offset()))
                .add("x-failure-reason", reason)
                .add("x-exception", e.getClass().getSimpleName())
                .add("x-message-key", rec.key() == null ? "" : rec.key())
                .build();

        var record = new ProducerRecord<>(dlqTopic, null, rec.key(), rec.value(), headers);
        producer.send(record, (md, ex) -> {
            if (ex != null) ex.printStackTrace();
        });
        System.err.printf("DLQ reason=%s key=%s offset=%d%n", reason, rec.key(), rec.offset());
    }

    private void sleepBackoff(int attempt) {
        long jitter = ThreadLocalRandom.current().nextLong(20, 50);
        long delay = Math.min(10_000, (long) (baseBackoffMs * Math.pow(2, attempt))) + jitter;
        try { Thread.sleep(delay); } catch (InterruptedException ignored) {}
    }

    // --- helpers & exceptions ---
    static final class HeadersBuilder {
        private final Iterable<org.apache.kafka.common.header.Header> list = new ArrayList<>();
        HeadersBuilder add(String k, String v) {
            ((ArrayList<org.apache.kafka.common.header.Header>) list)
                    .add(new RecordHeader(k, v.getBytes(StandardCharsets.UTF_8)));
            return this;
        }
        Iterable<org.apache.kafka.common.header.Header> build() { return list; }
    }
    static final class TransientException extends RuntimeException { TransientException(String m){super(m);} }
    static final class PermanentException extends RuntimeException { PermanentException(String m){super(m);} }
}
```

### 2) Redrive tool (read DLQ → republish to original topic safely)

```java
import org.apache.kafka.clients.consumer.*;
import org.apache.kafka.clients.producer.*;
import org.apache.kafka.common.header.Header;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.apache.kafka.common.serialization.StringSerializer;

import java.time.Duration;
import java.util.*;
import java.util.concurrent.TimeUnit;

public final class DlqRedriver {

    private final Consumer<String, String> dlqConsumer;
    private final Producer<String, String> producer;
    private final String dlqTopic;
    private final int maxToRedrive;
    private final long throttleMs;

    public DlqRedriver(String bootstrap, String dlqTopic, int maxToRedrive, long throttleMs) {
        this.dlqTopic = dlqTopic;
        this.maxToRedrive = maxToRedrive;
        this.throttleMs = throttleMs;

        Properties cp = new Properties();
        cp.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, bootstrap);
        cp.put(ConsumerConfig.GROUP_ID_CONFIG, "dlq-redriver-" + UUID.randomUUID());
        cp.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class.getName());
        cp.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class.getName());
        cp.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest");
        cp.put(ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, "false");
        this.dlqConsumer = new KafkaConsumer<>(cp);
        dlqConsumer.subscribe(List.of(dlqTopic));

        Properties pp = new Properties();
        pp.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, bootstrap);
        pp.put(ProducerConfig.ACKS_CONFIG, "all");
        this.producer = new KafkaProducer<>(pp, new StringSerializer(), new StringSerializer());
    }

    public void run() {
        int redriven = 0;
        while (redriven < maxToRedrive) {
            ConsumerRecords<String, String> recs = dlqConsumer.poll(Duration.ofSeconds(1));
            if (recs.isEmpty()) break;

            for (ConsumerRecord<String, String> rec : recs) {
                String originalTopic = header(rec, "x-original-topic").orElseThrow();
                // Optionally: skip certain reasons, or rewrite payload/headers here
                var headers = rec.headers();
                headers.add(new org.apache.kafka.common.header.internals.RecordHeader("x-redrive-count",
                        String.valueOf(incrementRedriveCount(headers)).getBytes()));
                headers.add(new org.apache.kafka.common.header.internals.RecordHeader("x-redriven-at",
                        String.valueOf(System.currentTimeMillis()).getBytes()));

                producer.send(new ProducerRecord<>(originalTopic, null, rec.key(), rec.value(), headers));
                redriven++;
                if (redriven % 100 == 0) producer.flush();
                try { TimeUnit.MILLISECONDS.sleep(throttleMs); } catch (InterruptedException ignored) {}
            }
            dlqConsumer.commitSync(); // mark consumed from DLQ
        }
        producer.flush();
    }

    private static Optional<String> header(ConsumerRecord<String,String> rec, String name) {
        for (Header h : rec.headers()) if (h.key().equals(name)) return Optional.of(new String(h.value()));
        return Optional.empty();
    }

    private static int incrementRedriveCount(Iterable<Header> headers) {
        for (Header h : headers) if (h.key().equals("x-redrive-count")) {
            try { return Integer.parseInt(new String(h.value())) + 1; } catch (Exception ignore) { return 1; }
        }
        return 1;
    }
}
```

**Notes on the sample**

-   Processor classifies exceptions into **transient** vs **permanent** and publishes to **`<topic>.dlq`** with rich headers.
    
-   Offsets are committed **after** either success **or DLQ publish**, so the pipeline keeps flowing.
    
-   Redriver throttles output and increments a `x-redrive-count` to avoid infinite loops.
    

---

## Known Uses

-   **Payment/Order pipelines:** malformed events, validation errors, or missing references.
    
-   **ETL/Data ingestion:** schema mismatch or unexpected data types during parsing.
    
-   **Notification services:** invalid addresses/blocked recipients.
    
-   **Search indexers:** documents failing mapping constraints.
    
-   **IoT:** corrupted device payloads quarantined for analysis.
    

---

## Related Patterns

-   **Retry / Delayer / Exponential Backoff:** Attempt recovery before sending to DLQ.
    
-   **Poison Message / Exception Handling:** Taxonomy and handling of unrecoverable messages.
    
-   **Competing Consumers:** DLQ works alongside consumer pools; each instance must publish failures consistently.
    
-   **Idempotent Receiver:** Essential when **redriving** to avoid duplicate side-effects.
    
-   **Message Store / Audit Log:** Persist failure and remediation metadata.
    
-   **Message Filter / Content Filter:** Optionally sanitize before DLQ to protect PII.
    
-   **Circuit Breaker:** If enrichment/lookups fail systemically, open circuit to reduce DLQ flood.
    

---

