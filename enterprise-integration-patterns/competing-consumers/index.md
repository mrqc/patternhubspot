# Competing Consumers (Enterprise Integration Pattern)

## Pattern Name and Classification

**Name:** Competing Consumers  
**Classification:** Enterprise Integration Pattern (Scalability / Message Consumption / Load Balancing)

---

## Intent

Increase throughput and resilience by having **multiple consumer instances** read from the **same queue/topic** so that **only one** consumer processes a given message, distributing load and enabling horizontal scaling.

---

## Also Known As

-   Consumer Pool
    
-   Worker Queue
    
-   Message Fan-In with Competing Workers
    

---

## Motivation (Forces)

-   A single consumer becomes a **bottleneck** or **single point of failure**.
    
-   Workload is **bursty** or **variable**; we want **elastic throughput**.
    
-   We need **isolation**: if one consumer fails or is slow, others continue.
    
-   We must preserve **at-least-once** delivery with **exclusive** processing per message.
    

Tensions to balance:

-   **Ordering vs parallelism** (partition/queue semantics).
    
-   **At-least-once** delivery vs **idempotency** at the handler.
    
-   **Fairness** under skewed keys (hot partitions).
    
-   **Visibility timeouts** and **redelivery** for slow/failed workers.
    

---

## Applicability

Use Competing Consumers when:

-   Tasks are **independent** and can be processed in parallel.
    
-   The broker or queue supports **exclusive delivery** per message (e.g., SQS, RabbitMQ, Kafka consumer groups).
    
-   You want to **scale out** by simply adding more instances/threads.
    

Avoid or limit when:

-   Strong **global ordering** is required (consider partitioning by key and a single consumer per partition).
    
-   Tasks must be **serialized** for a given entity without proper partitioning.
    
-   Processing includes **long, blocking** operations without visibility-timeout management.
    

---

## Structure

-   **Input Channel / Queue / Topic:** Holds messages to be processed.
    
-   **Consumer Group (Pool):** Multiple consumer instances competing on the same stream/queue.
    
-   **Work Handler:** The business logic per message.
    
-   **Idempotency Store / Dedup:** Ensures safe reprocessing on retries.
    
-   **DLQ / Retry Queue:** For poison messages.
    
-   **Autoscaler (optional):** Adjusts pool size based on backlog/lag.
    

---

## Participants

-   **Producers:** Publish messages to the queue/topic.
    
-   **Broker:** Delivers each message to **exactly one** consumer in the group (at-least-once).
    
-   **Consumers:** Independent processes or threads in the same group.
    
-   **Coordinator (broker-side):** Assigns partitions/queues to consumers (e.g., Kafka group coordinator).
    
-   **Ops/Autoscaler:** Observes lag and scales workers.
    

---

## Collaboration

1.  Producer publishes messages.
    
2.  Consumers join the **same group**; the broker assigns work (partitions or un-acked messages).
    
3.  Each message is delivered to **one** consumer; processing occurs.
    
4.  On success, the consumer **acknowledges/commits**.
    
5.  On failure/timeout, the broker **redelivers** (same or different consumer).
    
6.  Adding/removing consumers triggers **rebalancing** of assignments.
    

---

## Consequences

**Benefits**

-   **Horizontal scalability**: add consumers to increase throughput.
    
-   **Fault isolation**: one failed consumer doesn’t halt progress.
    
-   **Operational simplicity**: scale is mostly a deployment concern.
    

**Liabilities**

-   **At-least-once** → duplicates possible; handlers must be **idempotent**.
    
-   **Ordering** only within a **partition/queue shard**; adding consumers may change assignment.
    
-   **Hot keys/partitions** can cap throughput despite many consumers.
    
-   **Rebalancing pauses** during membership changes.
    

---

## Implementation

**Guidelines**

-   **Partition by key** to preserve ordering where needed (e.g., entityId).
    
-   Keep **one consumer per thread** (Kafka), and prefer **one thread per partition** for predictable ordering.
    
-   Use **manual acks/commits** *after* successful processing to ensure at-least-once.
    
-   Implement **idempotency** (dedup by messageId or business key + version).
    
-   Apply **backoff + retry**; send to **DLQ** after max attempts.
    
-   Set **visibility timeout / max.poll.interval** to exceed worst-case processing time.
    
-   **Autoscale** on lag/backlog metrics; cap concurrency to protect downstreams (*bulkheads*, rate limits).
    
-   Add **Poison message detection** (schema errors, permanent business failures).
    
-   Ensure **observability**: per-partition lag, processing latency, failure counts, DLQ rate.
    

**Tuning examples**

-   Kafka: `max.poll.records`, `max.poll.interval.ms`, `enable.auto.commit=false`, `heartbeat.interval.ms`, `fetch.max.bytes`.
    
-   RabbitMQ: `basic.qos(prefetch=N)` to limit in-flight messages per consumer.
    
-   SQS: `visibilityTimeout`, `maxNumberOfMessages`, `ReceiveMessageWaitTimeSeconds` (long polling).
    

---

## Sample Code (Java – Kafka consumer group with N competing consumers)

This example starts **N consumer threads**, all in the **same group**. Each thread runs a `KafkaConsumer`, processes records idempotently, and commits offsets after success. Replace the storage and parsing with real implementations.

```java
import org.apache.kafka.clients.consumer.*;
import org.apache.kafka.common.serialization.StringDeserializer;

import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

// --------- Idempotency store (sketch) ----------
interface IdempotencyStore {
    /** @return true if messageId already processed */
    boolean seen(String messageId);
    void markProcessed(String messageId);
}

final class InMemoryIdempotency implements IdempotencyStore {
    private final Set<String> set = ConcurrentHashMap.newKeySet();
    public boolean seen(String id) { return !set.add(id); }
    public void markProcessed(String id) { set.add(id); }
}

// --------- Business handler (replace with real logic) ----------
interface Handler {
    void process(String key, String value) throws Exception; // may throw retriable exception
}

final class PrintHandler implements Handler {
    @Override public void process(String key, String value) {
        // emulate work
        System.out.printf("Processed key=%s value=%s%n", key, value);
    }
}

// --------- Consumer worker ----------
final class ConsumerWorker implements Runnable {
    private final String topic;
    private final Properties props;
    private final Handler handler;
    private final IdempotencyStore idempotency;
    private final AtomicBoolean running = new AtomicBoolean(true);

    ConsumerWorker(String bootstrap, String groupId, String topic, Handler handler, IdempotencyStore idem) {
        this.topic = topic; this.handler = handler; this.idempotency = idem;
        this.props = new Properties();
        props.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, bootstrap);
        props.put(ConsumerConfig.GROUP_ID_CONFIG, groupId);
        props.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class.getName());
        props.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class.getName());
        props.put(ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, "false");         // manual commit = at-least-once
        props.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest");
        props.put(ConsumerConfig.MAX_POLL_RECORDS_CONFIG, "200");
        props.put(ConsumerConfig.MAX_POLL_INTERVAL_MS_CONFIG, "300000");       // > worst-case processing
        props.put(ConsumerConfig.HEARTBEAT_INTERVAL_MS_CONFIG, "1000");
        props.put(ConsumerConfig.SESSION_TIMEOUT_MS_CONFIG, "10000");
    }

    @Override public void run() {
        try (var consumer = new KafkaConsumer<String, String>(props)) {
            consumer.subscribe(List.of(topic));
            while (running.get()) {
                ConsumerRecords<String, String> records = consumer.poll(Duration.ofSeconds(1));
                Map<TopicPartition, OffsetAndMetadata> toCommit = new HashMap<>();

                for (TopicPartition tp : records.partitions()) {
                    List<ConsumerRecord<String, String>> partitionRecords = records.records(tp);
                    long lastProcessedOffset = -1L;

                    for (ConsumerRecord<String, String> rec : partitionRecords) {
                        // Use a stable message id (e.g., header or business key). Here we build one from topic/partition/offset for demo
                        String messageId = rec.topic() + "/" + rec.partition() + "/" + rec.offset();

                        if (idempotency.seen(messageId)) {
                            lastProcessedOffset = rec.offset();
                            continue; // drop duplicate
                        }

                        try {
                            handler.process(rec.key(), rec.value());
                            idempotency.markProcessed(messageId);
                            lastProcessedOffset = rec.offset();
                        } catch (TransientException te) {
                            // retriable: stop processing this partition batch; re-poll later (keeps offset)
                            System.err.printf("Transient failure at %s, will retry: %s%n", messageId, te.getMessage());
                            break;
                        } catch (Exception permanent) {
                            // poison: send to DLQ and advance offset
                            System.err.printf("Poison message at %s, sending to DLQ: %s%n", messageId, permanent.getMessage());
                            DeadLetter.publish(rec, permanent);
                            lastProcessedOffset = rec.offset();
                        }
                    }
                    if (lastProcessedOffset >= 0) {
                        toCommit.put(tp, new OffsetAndMetadata(lastProcessedOffset + 1)); // commit next offset
                    }
                }

                if (!toCommit.isEmpty()) {
                    consumer.commitSync(toCommit);
                }
            }
        }
    }

    public void shutdown() { running.set(false); }
}

// --------- Exceptions & DLQ ---------
final class TransientException extends RuntimeException {
    public TransientException(String msg) { super(msg); }
}

final class DeadLetter {
    public static void publish(ConsumerRecord<String,String> rec, Exception e) {
        // Implement: send to DLQ topic with headers including error info and original key/value
    }
}

// --------- Bootstrap a pool of competing consumers ---------
public final class CompetingConsumersApp {
    public static void main(String[] args) throws Exception {
        String bootstrap = "localhost:9092";
        String groupId = "orders-workers";
        String topic = "orders-to-process";
        int concurrency = Math.max(2, Runtime.getRuntime().availableProcessors() / 2);

        var executor = Executors.newFixedThreadPool(concurrency);
        var idempotency = new InMemoryIdempotency();
        var handler = new PrintHandler();

        List<ConsumerWorker> workers = new ArrayList<>();
        for (int i = 0; i < concurrency; i++) {
            var w = new ConsumerWorker(bootstrap, groupId, topic, handler, idempotency);
            workers.add(w);
            executor.submit(w);
        }

        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            workers.forEach(ConsumerWorker::shutdown);
            executor.shutdown();
        }));
    }
}
```

**Notes**

-   Start **multiple JVM instances** of this app with the **same `group.id`** to scale horizontally; Kafka will rebalance partitions across them.
    
-   Ordering is guaranteed **per partition**; choose partition key wisely (e.g., `orderId`).
    
-   Replace `InMemoryIdempotency` with a **durable store** (DB/Redis) in production.
    

---

## Known Uses

-   **Order processing pipelines:** multiple workers picking orders from a queue.
    
-   **ETL / ingestion:** parallel consumers loading and transforming data.
    
-   **Email/SMS dispatchers:** worker fleet sends notifications at scale.
    
-   **Image/ML processing:** farm of workers processing jobs from a topic.
    
-   **IoT telemetry:** sharded processing per device/tenant.
    

---

## Related Patterns

-   **Message Queue / Point-to-Point Channel:** The delivery mechanism that enables competition.
    
-   **Competing Consumers + Partitioning:** Preserve per-entity ordering by key.
    
-   **Idempotent Receiver:** Mandatory with at-least-once delivery.
    
-   **Dead Letter Channel / Retry:** Handle poison messages and backoff.
    
-   **Throttler / Delayer / Rate Limiter:** Protect downstreams while scaling out.
    
-   **Circuit Breaker & Bulkhead:** Complementary patterns for synchronous calls inside the handler.
    

---

