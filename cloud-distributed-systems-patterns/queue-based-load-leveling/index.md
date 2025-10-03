# Cloud Distributed Systems Pattern — Queue-Based Load Leveling

## Pattern Name and Classification

-   **Name:** Queue-Based Load Leveling

-   **Classification:** Integration & Scalability pattern for distributed/cloud systems; messaging & workload-smoothing.


## Intent

Decouple producers from consumers via a durable queue so bursts are absorbed and downstream services are leveled to a steady processing rate, improving resilience, throughput utilization, and overall latency predictability.

## Also Known As

-   Message Buffering

-   Work Queue / Task Queue

-   Asynchronous Command Processing


## Motivation (Forces)

-   **Traffic burstiness vs. steady capacity:** Frontend traffic arrives in spikes; backends (DBs, third-party APIs) have a steady—and often lower—throughput ceiling.

-   **Availability isolation:** If a downstream is slow/out, producers shouldn’t fail immediately; they should enqueue work and continue.

-   **Latency budgets:** End-user operations may complete fast by enqueuing work and acknowledging early (eventual completion).

-   **Cost efficiency:** Right-size consumers to average load and scale them elastically instead of peak-provisioning all components.

-   **Ordering & idempotency:** Some workloads need ordered processing; most need dedupe/idempotency to handle retries.

-   **At-least-once semantics:** Most queues deliver at-least-once → consumers must be idempotent and handle duplicates.

-   **Poison messages:** Bad inputs must not block the queue; move to a DLQ after limited retries for later inspection.


## Applicability

Use when:

-   Incoming load is spiky but consumers are resource-bounded (DB writes, report generation, media processing, email/SMS, webhooks).

-   You need to **shed** or **smooth** load and tolerate temporary downstream failures.

-   You want to return responses quickly while finishing work asynchronously.

-   Work can be processed **out of band** and is either order-agnostic or can be partition-ordered (by key).


Avoid when:

-   Strict end-to-end synchronous semantics/transactions are required.

-   User experience or business rules require immediate, strongly consistent effects.


## Structure

-   **Producers:** Accept requests; validate and enqueue **commands/jobs**.

-   **Queue/Broker:** Durable buffer (SQS, RabbitMQ, Kafka, Azure Queue, Google Pub/Sub). Supports visibility timeouts, dead-lettering, delays, ordering/partitioning.

-   **Consumers/Workers:** Pull, process, acknowledge; scale horizontally; handle retries and idempotency.

-   **DLQ/Poison Queue:** Stores messages that exceeded the retry policy.

-   **Observability:** Metrics, tracing, and logs for enqueue rate, depth, age, success/failure.


## Participants

-   **Enqueuer:** Serializes + publishes messages; may assign a **dedupe/idempotency key**.

-   **Broker/Queue:** Persists messages; manages delivery/visibility; routes to DLQ.

-   **Worker:** Business logic; idempotent execution; acks or requeues on failure.

-   **Retry/Backoff Policy:** Governs per-message retry attempts and timing.

-   **Dead-Letter Handler:** Triages DLQ items (reprocess, fix, or discard).

-   **Metrics/Alarmer:** Watches queue depth/age; triggers autoscaling of workers or alerts.


## Collaboration

1.  Producer validates the request, persists any authoritative state if needed, and enqueues a **command** with an idempotency key.

2.  Queue stores it durably and delivers to a worker when available.

3.  Worker executes idempotently; on success → **ack**; on transient failure → **nack/retry with backoff**; on permanent failure after N tries → **dead-letter**.

4.  Monitoring reacts to queue depth/age to scale workers up/down and alerts on DLQ growth.


## Consequences

**Pros**

-   Smooths bursty load; protects downstreams from overload.

-   Increases availability via temporal decoupling and retries.

-   Enables elastic consumption and simpler zero-downtime maintenance.

-   Improves cost efficiency (match consumers to average load).


**Cons / Trade-offs**

-   Additional infrastructure and operational complexity (brokers, DLQs, observability).

-   Eventual consistency; extra care for UX and business process design.

-   At-least-once delivery → must handle duplicates; exactly-once is rare/costly.

-   Ordering is limited; usually per-partition/key only.


## Implementation (Key Points)

-   **Message design:** Include a type, schema/version, **idempotency key**, created-at, and optional partition key.

-   **Idempotency:** Use a **dedupe store** (e.g., DB with unique key, cache with TTL) to skip duplicates.

-   **Retries:** Exponential backoff + jitter; cap attempts; use visibility timeouts (SQS) or requeue with delay (RabbitMQ).

-   **DLQ:** Route after max attempts; include failure metadata.

-   **Backpressure/autoscaling:** Scale workers based on **queue depth** and **oldest message age**.

-   **Ordering:** If needed, choose FIFO/partitioned queues and key messages consistently.

-   **Observability:** Emit enqueue/dequeue rates, processing latency, success %, queue depth/age, DLQ inflow.

-   **Security:** Encrypt at rest/in transit, signed payloads, authN/Z on producers/consumers.


---

## Sample Code (Java 17): Minimal In-Process Queue Leveler (Educational)

> Demonstrates: producer→queue→consumers, retry with exponential backoff + jitter, idempotency, DLQ, graceful shutdown.  
> Replace the in-memory queue with SQS/RabbitMQ/Kafka in production.

```java
// File: QueueBasedLoadLevelingDemo.java
// Compile/Run: javac QueueBasedLoadLevelingDemo.java && java QueueBasedLoadLevelingDemo
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;

public class QueueBasedLoadLevelingDemo {

    // ---------- Message & DLQ ----------
    static final class Job {
        final String id;           // idempotency key
        final String type;         // e.g., "email.send"
        final String payload;      // JSON string for simplicity
        final Instant createdAt = Instant.now();
        int attempts = 0;
        Job(String id, String type, String payload) { this.id = id; this.type = type; this.payload = payload; }
        public String toString() { return "Job{id=%s, type=%s, attempts=%d}".formatted(id, type, attempts); }
    }

    // ---------- Broker (in-memory) ----------
    static final BlockingQueue<Job> QUEUE = new LinkedBlockingQueue<>(10_000);
    static final BlockingQueue<Job> DLQ   = new LinkedBlockingQueue<>(10_000);

    // ---------- Idempotency store (simulate persistent unique key) ----------
    static final Set<String> IDEMPOTENCY_STORE = ConcurrentHashMap.newKeySet();

    // ---------- Producer ----------
    static void enqueue(Job job) {
        // simulate dedupe on enqueue (can also dedupe at consumer)
        if (!IDEMPOTENCY_STORE.add("enq:" + job.id)) {
            System.out.println("DEDUPED (already enqueued) " + job.id);
            return;
        }
        if (!QUEUE.offer(job)) throw new RuntimeException("queue full");
    }

    // ---------- Consumer Worker ----------
    static final class Worker implements Runnable {
        private final int id;
        private volatile boolean running = true;
        private final int maxAttempts = 5;

        Worker(int id) { this.id = id; }

        @Override public void run() {
            Thread.currentThread().setName("worker-" + id);
            while (running) {
                try {
                    Job job = QUEUE.poll(500, TimeUnit.MILLISECONDS);
                    if (job == null) continue;

                    // visibility timeout analogue: we "own" the job until we decide to ack or dead-letter
                    process(job);
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    break;
                }
            }
        }

        private void process(Job job) {
            job.attempts++;
            try {
                // Idempotency at consumer side: skip if already processed
                if (!IDEMPOTENCY_STORE.add("proc:" + job.id)) {
                    System.out.println(ts() + " [worker-" + id + "] DUPLICATE -> ack " + job);
                    return;
                }

                // ---- Business logic (simulate) ----
                if (job.type.equals("email.send")) {
                    // simulate transient failure for demonstration
                    if (job.attempts < 3 && Math.random() < 0.6) {
                        throw new RuntimeException("smtp transient error");
                    }
                    Thread.sleep(50 + (int)(Math.random() * 100)); // simulate work
                    System.out.println(ts() + " [worker-" + id + "] OK " + job);
                } else {
                    throw new IllegalArgumentException("unknown job type " + job.type);
                }
                // ack: nothing to do (we consumed it)

            } catch (Exception e) {
                if (job.attempts >= maxAttempts || e instanceof IllegalArgumentException) {
                    // dead-letter
                    DLQ.offer(job);
                    System.out.println(ts() + " [worker-" + id + "] DLQ (" + e.getMessage() + ") -> " + job);
                } else {
                    // retry with backoff + jitter
                    long delayMs = backoffDelay(job.attempts);
                    System.out.println(ts() + " [worker-" + id + "] RETRY in " + delayMs + "ms (" + e.getMessage() + ") -> " + job);
                    scheduleRetry(job, delayMs);
                }
            }
        }

        private static long backoffDelay(int attempts) {
            long base = (long) Math.min(30_000, 100 * Math.pow(2, attempts)); // 100ms, 200ms, 400ms, ...
            long jitter = ThreadLocalRandom.current().nextLong(0, base / 2 + 1);
            return base + jitter;
        }

        private static void scheduleRetry(Job job, long delayMs) {
            RETRY_SCHEDULER.schedule(() -> {
                try { QUEUE.put(job); } catch (InterruptedException ignored) { Thread.currentThread().interrupt(); }
            }, delayMs, TimeUnit.MILLISECONDS);
        }

        public void shutdown() { running = false; }
    }

    // ---------- Infra (workers + scheduler) ----------
    static final ScheduledExecutorService RETRY_SCHEDULER = Executors.newScheduledThreadPool(2);
    static ExecutorService workerPool;

    // ---------- Metrics ----------
    static final AtomicInteger ENQUEUED = new AtomicInteger();
    static final AtomicInteger PROCESSED = new AtomicInteger();

    public static void main(String[] args) throws Exception {
        int workers = Math.max(2, Runtime.getRuntime().availableProcessors() / 2);
        workerPool = Executors.newFixedThreadPool(workers);
        List<Worker> workerRefs = new ArrayList<>();
        for (int i = 0; i < workers; i++) {
            Worker w = new Worker(i + 1);
            workerRefs.add(w);
            workerPool.submit(w);
        }

        // Simulate bursty producers
        for (int i = 0; i < 50; i++) {
            String id = "email-" + i;
            enqueue(new Job(id, "email.send", "{\"to\":\"user"+i+"@example.com\",\"body\":\"hi\"}"));
            ENQUEUED.incrementAndGet();
            if (i % 10 == 0) Thread.sleep(300); // small burst gap
        }

        // Wait a bit, then graceful shutdown
        Thread.sleep(8000);
        workerRefs.forEach(Worker::shutdown);
        workerPool.shutdown();
        workerPool.awaitTermination(5, TimeUnit.SECONDS);
        RETRY_SCHEDULER.shutdownNow();

        System.out.println("\n==== STATS ====");
        System.out.println("Enqueued: " + ENQUEUED.get());
        System.out.println("Queue depth: " + QUEUE.size());
        System.out.println("DLQ size: " + DLQ.size());
        System.out.println("Idempotency keys: " + IDEMPOTENCY_STORE.size());
    }

    private static String ts() { return OffsetDateTime.now().toString(); }
}
```

### Notes

-   Replace the **in-memory** queue with a managed broker. The control-flow (retry → DLQ, idempotency, backoff) stays the same.

-   Persist idempotency state in a durable store (e.g., DB unique index on `(idempotency_key)` with TTL, or Redis set with TTL).


---

## (Optional) AWS SQS Integration Sketch (Java 17, AWS SDK v2)

```java
// Pseudocode (omit error handling for brevity)
SqsClient sqs = SqsClient.builder().build();
String queueUrl = sqs.getQueueUrl(GetQueueUrlRequest.builder().queueName("jobs").build()).queueUrl();

void enqueueSqs(String body, String idempotencyKey) {
    sqs.sendMessage(SendMessageRequest.builder()
        .queueUrl(queueUrl)
        .messageBody(body)
        .messageGroupId("email")                 // for FIFO queues (ordering by group)
        .messageDeduplicationId(idempotencyKey)  // FIFO dedupe window
        .build());
}

void pollLoop() {
    while (true) {
        var resp = sqs.receiveMessage(ReceiveMessageRequest.builder()
                .queueUrl(queueUrl)
                .maxNumberOfMessages(10)
                .visibilityTimeout(30)       // seconds
                .waitTimeSeconds(10)         // long polling
                .build());
        for (var m : resp.messages()) {
            boolean ok = process(m.body());  // your idempotent logic
            if (ok) {
                sqs.deleteMessage(DeleteMessageRequest.builder()
                        .queueUrl(queueUrl).receiptHandle(m.receiptHandle()).build());
            } else {
                // Let visibility timeout expire → message becomes visible for retry
                // Consider changing visibility for backoff or send to DLQ after N tries
            }
        }
    }
}
```

---

## Known Uses

-   **Azure:** “Queue-Based Load Leveling” (official cloud design pattern), Azure Storage Queues / Service Bus.

-   **AWS:** SQS (Standard/FIFO) for webhook fan-in, email/SMS pipelines, image/video processing.

-   **GCP:** Pub/Sub for background jobs, export/import pipelines.

-   **Open Source:** RabbitMQ task queues; Kafka with consumer groups for command/event processing; Celery-like systems.


## Related Patterns

-   **Competing Consumers:** Multiple workers pull from the same queue to scale out.

-   **Priority Queue / Delayed Queue:** Different service levels or scheduled work.

-   **Retry with Backoff & Jitter:** Handle transient errors safely.

-   **Circuit Breaker / Bulkhead:** Protect external dependencies from overload.

-   **Transactional Outbox:** Reliably publish to the queue when updating a DB.

-   **Saga / Process Manager:** Coordinate multi-step workflows across services.

-   **Throttling/Rate Limiting:** Bound producer rate; shape ingress before enqueue.


---

### Production Checklist (quick)

-   Choose delivery semantics and ordering model (Standard vs FIFO, partitioning).

-   Implement **idempotency** (dedupe key + side-effect guards).

-   Tune **visibility timeout**, **max receive count**, and **DLQ** policy.

-   Autoscale consumers on **queue depth** and **oldest message age**.

-   Emit SLOs and alerts for **backlog age** and **DLQ growth**.

-   Secure endpoints/keys; encrypt messages; redact PII in logs.
