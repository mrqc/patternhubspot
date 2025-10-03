# Event Retry — Event-Driven Architecture Pattern

## Pattern Name and Classification

**Name:** Event Retry  
**Classification:** Event-Driven Architecture (EDA) / Reliability & Delivery Assurance pattern

## Intent

Increase delivery success and processing robustness by automatically re-attempting event handling when transient faults occur, while preventing duplicate side-effects and avoiding overload through backoff, jitter, and bounded retry policies.

## Also Known As

-   Redelivery
    
-   Backoff & Retry
    
-   At-least-once Delivery Guard
    
-   Consumer Retry with Dead Letter
    

## Motivation (Forces)

-   **Transient failures happen:** network blips, brief DB outages, timeouts, temporary resource saturation.
    
-   **At-least-once semantics:** many logs/brokers (Kafka, SQS, Pulsar, RabbitMQ) favor redelivery over loss; consumers must be safe to retry.
    
-   **Throughput vs. safety:** immediate re-attempts can create retry storms and thundering herds; backoff + jitter is required.
    
-   **Idempotency & deduplication:** retries can re-trigger side-effects; handlers must be idempotent or guarded.
    
-   **Poison messages:** permanent failures shouldn’t block partitions/queues; isolate to DLQ with rich diagnostics.
    
-   **Observability & ops:** operators need visibility (attempt count, next retry time) and controls (pause, skip, reroute).
    

## Applicability

Use **Event Retry** when:

-   Your delivery guarantee is at-least-once or unknown.
    
-   You integrate with flaky downstreams (HTTP APIs, DBs, search clusters).
    
-   You want automated recovery from transient faults without human intervention.
    

Be cautious when:

-   Side-effects are non-idempotent and cannot be made idempotent (e.g., charging cards without idempotency keys).
    
-   Reprocessing is extremely expensive or slow (consider circuit breakers or partial retries).
    
-   Ordering is strict per key and a long-lived poison event would block the stream (use DLQ, parking lot, or reordering windows).
    

## Structure

-   **Event Log/Broker:** durable store that (re)delivers events.
    
-   **Consumer/Handler:** business logic; **idempotent**.
    
-   **Retry Policy:** max attempts, backoff strategy (exponential/linear), jitter, per-error classification.
    
-   **Scheduler/Delay Mechanism:** delayed topics/queues, visibility timeout, or timer-wheel.
    
-   **Dead Letter Queue (DLQ) / Parking Lot:** terminal sink after retries are exhausted.
    
-   **Metadata:** attempt counter, first-seen timestamp, last error, correlation and idempotency keys.
    
-   **Observability:** metrics, logs, traces, dashboards, alerting.
    

*Textual diagram*

```less
[Event Log] -> [Consumer] --(transient error)--> [Retry Scheduler]
                                   |                     |
                                   | (maxed / fatal)     v (later)
                                   +------------------> [Retry Topic(s)]
                                                         |
                                                         v
                                                       [Consumer]
                                                         |
                                                         v (exhausted)
                                                       [DLQ]
```

## Participants

-   **Producer** – emits events (often with correlation/idempotency keys).
    
-   **Broker/Event Store** – Kafka, Pulsar, RabbitMQ, SQS, etc.
    
-   **Retry Controller/Policy** – computes next delay, limits attempts.
    
-   **Consumer/Projector** – processes events idempotently.
    
-   **DLQ Handler** – triage & remediation (manual or automated).
    
-   **Observability Stack** – logs/metrics/traces; SLOs, dashboards.
    

## Collaboration

1.  Consumer receives event and tries to handle it.
    
2.  On **success**, it commits/acks and advances offset.
    
3.  On **retryable failure** (e.g., 5xx, timeout, connection error), it schedules re-delivery using backoff + jitter; increments attempt metadata.
    
4.  On **non-retryable failure** (e.g., validation error), it routes the event immediately to **DLQ** (parking lot).
    
5.  Once **max attempts** reached, route to DLQ with error context.
    
6.  DLQ handler supports inspection, fix-forward, targeted replay, or discard per policy.
    

## Consequences

**Benefits**

-   Dramatically improved resilience to transient faults.
    
-   Reduced operational toil; auto-healing behavior.
    
-   Protects downstreams using backoff, jitter, and concurrency limits.
    
-   Clear separation of transient vs. terminal errors via DLQ.
    

**Liabilities**

-   Increased latency for affected events.
    
-   Potential duplication unless handlers are idempotent.
    
-   Retry storms if misconfigured (no jitter; too-aggressive backoff).
    
-   Ordering may be affected when using separate retry topics/queues.
    
-   Requires strong observability to avoid “silent flapping”.
    

## Implementation

**Key practices**

-   **Classify errors:** retryable vs. fatal; consider HTTP codes, SQLState, exception types.
    
-   **Idempotency:** store processed event ids or dedupe keys; use optimistic locking; make side-effects idempotent (e.g., payment idempotency keys).
    
-   **Backoff & jitter:** exponential backoff with full jitter is a solid default.
    
-   **Bounded attempts:** hard cap attempts; escalate to DLQ.
    
-   **Delay mechanics:**
    
    -   Kafka: tiered retry topics (e.g., `.retry.5s`, `.retry.1m`, `.retry.5m`) or a delay queue processor.
        
    -   RabbitMQ: per-queue TTL + DLX or delayed exchange.
        
    -   SQS: visibility timeout + redrive policy; per-message delay.
        
-   **Isolation:** use separate consumer groups for retry flows to avoid blocking hot partitions.
    
-   **Poison pill handling:** validate early; short-circuit to DLQ for non-retryable issues.
    
-   **Observability:** metrics (retry\_attempts, dlq\_rate, success\_after\_retry), structured logs including attempt, reason, next\_delay\_ms.
    
-   **Ops controls:** pause/resume retry processors; “quarantine” tenants/keys; bulk requeue from DLQ after fix-forward.
    

### Steps

1.  Define **RetryPolicy** (maxAttempts, base/backoff, jitter, classifier).
    
2.  Implement **idempotent handler** with dedupe/optimistic locks.
    
3.  Add **error classifier** to tag exceptions retryable vs. fatal.
    
4.  Wire a **retry scheduler** (publish to delay topic/queue with attempt headers).
    
5.  Implement **DLQ publisher** and **DLQ triage** tooling.
    
6.  Instrument with **metrics/logs/traces** and set SLOs & alerts.
    

## Sample Code (Java, Spring Boot + Kafka)

-   Idempotent projector
    
-   Exponential backoff with full jitter
    
-   Tiered retry topics (`orders`, `orders.retry.10s`, `orders.retry.1m`)
    
-   DLQ (`orders.dlq`)
    
-   Error classification
    

```java
// RetryPolicy with exponential backoff + full jitter
public final class RetryPolicy {
    private final int maxAttempts;
    private final long baseDelayMillis; // e.g., 500
    private final double multiplier;    // e.g., 2.0
    private final long maxDelayMillis;  // cap
    private final java.util.Random rnd = new java.util.Random();

    public RetryPolicy(int maxAttempts, long baseDelayMillis, double multiplier, long maxDelayMillis) {
        this.maxAttempts = maxAttempts;
        this.baseDelayMillis = baseDelayMillis;
        this.multiplier = multiplier;
        this.maxDelayMillis = maxDelayMillis;
    }
    public int maxAttempts() { return maxAttempts; }

    public long nextDelayMillis(int attempt) {
        double exp = Math.pow(multiplier, Math.max(0, attempt - 1));
        long nominal = (long) Math.min(baseDelayMillis * exp, maxDelayMillis);
        // Full jitter: random between 0 and nominal
        return (long) (rnd.nextDouble() * nominal);
    }
}

// Error classification
class RetryClassifier {
    boolean isRetryable(Throwable t) {
        if (t instanceof java.net.SocketTimeoutException) return true;
        if (t instanceof java.sql.SQLTransientException) return true;
        if (t instanceof org.springframework.web.client.HttpServerErrorException) return true; // 5xx
        // Non-retryable examples
        if (t instanceof IllegalArgumentException) return false; // validation
        if (t instanceof org.springframework.web.client.HttpClientErrorException.BadRequest) return false; // 400
        return false; // default conservative
    }
}

// Idempotency store
import jakarta.persistence.*;

@Entity
@Table(name = "processed_event",
       uniqueConstraints = @UniqueConstraint(columnNames = {"handler", "event_id"}))
class ProcessedEvent {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) Long id;
    @Column(nullable=false) String handler;
    @Column(name="event_id", nullable=false) String eventId;
    @Column(nullable=false) long processedAt;
    protected ProcessedEvent() {}
    public ProcessedEvent(String handler, String eventId, long processedAt) {
        this.handler = handler; this.eventId = eventId; this.processedAt = processedAt;
    }
}
interface ProcessedEventRepo extends org.springframework.data.repository.CrudRepository<ProcessedEvent, Long> {
    boolean existsByHandlerAndEventId(String handler, String eventId);
}

// Domain + projection (simplified)
@Entity
@Table(name = "order_view")
class OrderView {
    @Id String orderId;
    @Version Long optLock;
    String status;
    protected OrderView() {}
    public OrderView(String orderId, String status) { this.orderId = orderId; this.status = status; }
}
interface OrderViewRepo extends org.springframework.data.repository.CrudRepository<OrderView, String> {}

// Kafka topic names
final class Topics {
    static final String ORDERS = "orders";
    static final String ORDERS_RETRY_10S = "orders.retry.10s";
    static final String ORDERS_RETRY_1M  = "orders.retry.1m";
    static final String ORDERS_DLQ       = "orders.dlq";
}

// Event model
public record OrderCreated(String eventId, String orderId, String status) {}


// === Consumer/Projector with retry scheduling ===
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.header.Header;
import org.apache.kafka.common.header.internals.RecordHeader;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.messaging.handler.annotation.Header as SHeader;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
class OrderProjector {
    private static final String HANDLER = "OrderProjector.v1";

    private final OrderViewRepo views;
    private final ProcessedEventRepo processed;
    private final KafkaTemplate<String, OrderCreated> kafka;
    private final RetryPolicy policy = new RetryPolicy(6, 500, 2.0, 60_000); // up to ~1m
    private final RetryClassifier classifier = new RetryClassifier();

    OrderProjector(OrderViewRepo views, ProcessedEventRepo processed, KafkaTemplate<String, OrderCreated> kafka) {
        this.views = views; this.processed = processed; this.kafka = kafka;
    }

    // Primary listener (live topic)
    @KafkaListener(topics = Topics.ORDERS, groupId = "orders-consumer")
    public void onOrders(ConsumerRecord<String, OrderCreated> rec) {
        handleWithRetry(rec, Topics.ORDERS);
    }

    // Retry listeners (tiered delays: wire these topics to delayed consumption by broker or scheduler)
    @KafkaListener(topics = {Topics.ORDERS_RETRY_10S, Topics.ORDERS_RETRY_1M}, groupId = "orders-retry-consumer")
    public void onOrdersRetry(ConsumerRecord<String, OrderCreated> rec) {
        handleWithRetry(rec, rec.topic());
    }

    private void handleWithRetry(ConsumerRecord<String, OrderCreated> rec, String sourceTopic) {
        OrderCreated ev = rec.value();
        int attempt = getAttempt(rec) + 1;
        try {
            project(ev); // business logic (idempotent)
            markProcessed(ev);
        } catch (Exception ex) {
            if (!classifier.isRetryable(ex)) {
                publishDlq(rec, ex, attempt);
                return;
            }
            if (attempt >= policy.maxAttempts()) {
                publishDlq(rec, ex, attempt);
                return;
            }
            scheduleRetry(rec, attempt);
        }
    }

    @Transactional
    protected void project(OrderCreated ev) {
        if (processed.existsByHandlerAndEventId(HANDLER, ev.eventId())) return; // idempotent
        OrderView v = views.findById(ev.orderId()).orElse(new OrderView(ev.orderId(), ev.status()));
        v.status = ev.status();
        views.save(v);
        // (Side effects like emails should be idempotent or behind a "mode" flag)
    }

    @Transactional
    protected void markProcessed(OrderCreated ev) {
        processed.save(new ProcessedEvent(HANDLER, ev.eventId(), System.currentTimeMillis()));
    }

    private int getAttempt(ConsumerRecord<String, OrderCreated> rec) {
        Header h = rec.headers().lastHeader("retry-attempt");
        if (h == null) return 0;
        try { return Integer.parseInt(new String(h.value())); } catch (Exception ignored) { return 0; }
    }

    private void scheduleRetry(ConsumerRecord<String, OrderCreated> rec, int nextAttempt) {
        long delayMs = policy.nextDelayMillis(nextAttempt);
        String targetTopic = pickRetryTopic(delayMs); // coarse bucket to reduce topics

        var headers = new org.apache.kafka.common.header.internals.RecordHeaders();
        headers.add(new RecordHeader("retry-attempt", Integer.toString(nextAttempt).getBytes()));
        headers.add(new RecordHeader("first-seen-ts", Long.toString(System.currentTimeMillis()).getBytes()));
        headers.add(new RecordHeader("origin-topic", rec.topic().getBytes()));
        headers.add(new RecordHeader("next-delay-ms", Long.toString(delayMs).getBytes()));

        // In many setups, actual delay is enforced by the broker (delayed topics) or a scheduler component.
        ProducerRecord<String, OrderCreated> pr =
            new ProducerRecord<>(targetTopic, null, null, rec.key(), rec.value(), headers);

        kafka.send(pr); // fire-and-forget; add callbacks/metrics in production
    }

    private String pickRetryTopic(long delayMs) {
        if (delayMs <= 10_000) return Topics.ORDERS_RETRY_10S;
        return Topics.ORDERS_RETRY_1M;
    }

    private void publishDlq(ConsumerRecord<String, OrderCreated> rec, Exception ex, int attempt) {
        var headers = new org.apache.kafka.common.header.internals.RecordHeaders();
        headers.add(new RecordHeader("dlq-reason", ex.getClass().getName().getBytes()));
        headers.add(new RecordHeader("dlq-message", truncate(ex.getMessage(), 512).getBytes()));
        headers.add(new RecordHeader("final-attempt", Integer.toString(attempt).getBytes()));
        headers.add(new RecordHeader("origin-topic", rec.topic().getBytes()));
        kafka.send(new ProducerRecord<>(Topics.ORDERS_DLQ, rec.key(), rec.value(), headers));
    }

    private static String truncate(String s, int max) {
        if (s == null) return "";
        return s.length() <= max ? s : s.substring(0, max);
    }
}
```

**Notes on the example**

-   Uses **tiered retry topics** for coarse delays; in real systems you may combine with a scheduler/delay plugin.
    
-   **Idempotency** enforced via `processed_event` unique constraint (per handler).
    
-   **Retry attempts** tracked in headers; DLQ event enriched with context for triage.
    
-   **Backoff + jitter** prevents retry storms.
    
-   Wire broker features accordingly (e.g., RabbitMQ DLX/TTL; SQS visibility timeout; Kafka delayed delivery via external scheduler or plugins).
    

## Known Uses

-   **Kafka + DLQ** patterns in microservices to isolate poison messages and auto-recover transient errors.
    
-   **SQS redrive policy** with visibility timeout extension and DLQ for terminal failures.
    
-   **RabbitMQ delayed exchange** or TTL + dead-letter exchange to implement backoff tiers.
    
-   **Kafka Streams / Flink** built-in retry/backoff + DLQ side outputs for failed records.
    
-   **Payments & ledgers**: retries with strict idempotency keys to avoid double-charging.
    

## Related Patterns

-   **Idempotent Receiver / Exactly-Once Effects:** foundational for safe retries.
    
-   **Dead Letter Queue (DLQ):** terminal sink when retries exhaust or failure is non-retryable.
    
-   **Circuit Breaker & Bulkhead:** limit blast radius and fast-fail when dependencies are unhealthy.
    
-   **Transactional Outbox:** guarantees event publication so that retries are meaningful.
    
-   **Event Replay:** rebuilding projections/read models after fixes (retry is short-term; replay is bulk reprocessing).
    
-   **Backpressure / Rate Limiting:** complements retries to protect dependencies.

