# Event Replay — Event-Driven Architecture Pattern

## Pattern Name and Classification

**Name:** Event Replay  
**Classification:** Event-Driven Architecture (EDA) / Event Sourcing auxiliary pattern / Operational pattern for rebuilding state and reprocessing

## Intent

Enable (re)processing of historical events to rebuild system state, regenerate projections/read models, fix downstream bugs, audit, or derive new insights—without altering the immutable event log.

## Also Known As

-   Reprocessing
    
-   Rewind & Rehydrate
    
-   Projection Rebuild
    
-   Log Rewind
    

## Motivation (Forces)

-   **Immutability & auditability:** Event-sourced systems treat the event log as the source of truth; replay must preserve ordering and causality.
    
-   **Evolving read models:** Schemas, business rules, and projections change; you need to rebuild them from the event history.
    
-   **Defect remediation:** A faulty projector or ETL can be corrected by fixing code and replaying past events.
    
-   **New consumers:** New bounded contexts join later and need the whole history to catch up.
    
-   **Scale & safety:** Replays can overwhelm downstream systems if not throttled or idempotent.
    
-   **Selectivity:** Sometimes you want full rebuilds; other times, targeted slices (time-window, aggregate, partition).
    
-   **Operational windows:** Production replay must not jeopardize SLAs; needs isolation, backpressure, and observability.
    

## Applicability

Use Event Replay when:

-   You use event sourcing or keep durable, ordered event logs (e.g., Kafka, Kinesis, Pulsar, EventStoreDB).
    
-   You need to rebuild projections/read models after schema or code changes.
    
-   You need to backfill a new consumer/feature with historical data.
    
-   You must recover from projection corruption or lost caches.
    
-   You run data science/analytics on past events without touching production paths.
    

Avoid or limit if:

-   Events are not self-contained enough to deterministically reconstruct state.
    
-   Side-effects (emails, payments) cannot be safely deduplicated during replays.
    
-   Your storage cannot guarantee order or stable retention for the required horizon.
    

## Structure

-   **Event Log (immutable):** Append-only, ordered by partition/stream and offset/sequence.
    
-   **Replay Controller:** Orchestrates selection (what to replay), speed (throttle), and safety (isolation, dry-run).
    
-   **Projectors / Consumers:** Idempotent handlers that transform events into read models, caches, or side-effects.
    
-   **Snapshots (optional):** Checkpoints to accelerate replay by skipping early history.
    
-   **Offsets/Checkpoints:** Track progress for each consumer during replay.
    
-   **Guards:** Deduplication keys, effect suppressors, feature flags to disable external calls.
    

*Textual diagram*

```less
[Event Log] --ordered--> [Replay Controller] --throttled--> [Projectors]
                                    |                           |
                             [Snapshots/Offsets]          [Read Models]
```

## Participants

-   **Producer (existing):** Emits domain events.
    
-   **Event Store / Log:** Kafka topic, EventStore stream, DB table.
    
-   **Replay Controller/Service:** Selects range, coordinates parallelism, and handles backpressure.
    
-   **Projector/Handler:** Idempotent consumer that builds materialized views or triggers internal side-effects.
    
-   **Snapshot Manager:** Creates/loads snapshots; trims replays.
    
-   **Metrics/Observability:** Emits lag, throughput, error rates, retries.
    

## Collaboration

1.  Operator/dev initiates a replay (full or partial) with parameters (streams, time range, aggregate IDs).
    
2.  Replay controller resolves the start point (snapshot or offset) and streams events.
    
3.  Projectors handle events with idempotency keys and version checks, updating read models.
    
4.  Checkpoints are written; metrics updated; optional dry-run compares expected vs. actual without writes.
    

## Consequences

**Benefits**

-   Deterministic rebuild of state and projections.
    
-   Faster recovery from projector bugs.
    
-   Enables new derived views and analytics without producer changes.
    
-   Strong audit trail; supports what-if simulations.
    

**Liabilities**

-   Risk of **duplicate side-effects** if handlers aren’t idempotent or effects aren’t suppressed.
    
-   **Operational load**: large CPU/IO spikes; may contend with live traffic.
    
-   **Clock & ordering assumptions** can break if events were not truly self-contained.
    
-   **Long runtimes** without snapshots or adequate parallelism.
    
-   **Data drift** if upstream schemas evolved and old events no longer validate.
    

## Implementation

**Key practices**

-   **Idempotency:** Use event id + handler version as a dedupe key; implement upserts with optimistic locking.
    
-   **Side-effect suppression:** During replay, disable emails, webhooks, payments—or route them to a sandbox.
    
-   **Isolation:** Separate replay workers or environments; use distinct consumer groups/offsets.
    
-   **Selective replay:** Filter by aggregate, partition(s), or time window. Support dry-run.
    
-   **Backpressure & throttling:** Rate-limit; bound batch size; respect downstream DB capacity.
    
-   **Snapshots:** Periodically persist aggregate/projection snapshots to reduce replay horizon.
    
-   **Schema evolution:** Version event contracts; maintain upcasters to transform old payloads on the fly.
    
-   **Observability:** Track throughput, lag, error counts, handler time, and checkpoint positions.
    
-   **Safety rails:** Feature flags, circuit breakers, and automatic pause on error thresholds.
    

### Steps

1.  **Design events** to be self-contained, versioned.
    
2.  **Add projector idempotency** via processed\_event table or natural keys.
    
3.  **Implement upcasters** for legacy events.
    
4.  **Expose replay API/CLI** accepting selectors (aggregate IDs, partitions, time span).
    
5.  **Guard side-effects** behind interfaces with a “mute” strategy during replay.
    
6.  **Run in batches**, checkpoint progress, and expose metrics.
    
7.  **Validate results** (counts, checksums) before swapping read models.
    

## Sample Code (Java, Spring Boot + Kafka + JPA)

Below is a compact, production-leaning example showing:

-   An idempotent projector for a `CustomerRegistered` event.
    
-   A replay controller that assigns partitions and seeks to a start offset or timestamp.
    
-   A snapshot-aware aggregate rebuild path (optional).
    
-   Side-effect suppression via a `Mode` flag.
    

```java
// Domain event
public record CustomerRegistered(
    String eventId,        // globally unique
    String aggregateId,    // customerId
    long   sequence,       // per-aggregate version
    long   timestamp,      // epoch millis
    String email,
    String name
) {}

// Upcaster example (no-op for brevity)
interface Upcaster<E> {
    E upcast(byte[] raw);
}

// Idempotency tracking
import jakarta.persistence.*;
@Entity
@Table(name = "processed_event",
       uniqueConstraints = @UniqueConstraint(columnNames = {"handler", "event_id"}))
class ProcessedEvent {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    Long id;
    @Column(nullable=false) String handler;
    @Column(name="event_id", nullable=false) String eventId;
    @Column(nullable=false) Long processedAt;
    protected ProcessedEvent() {}
    public ProcessedEvent(String handler, String eventId, long processedAt) {
        this.handler = handler; this.eventId = eventId; this.processedAt = processedAt;
    }
}

interface ProcessedEventRepo extends org.springframework.data.repository.CrudRepository<ProcessedEvent, Long> {
    boolean existsByHandlerAndEventId(String handler, String eventId);
}

// Read model (projection)
@Entity
@Table(name = "customer_view")
class CustomerView {
    @Id String customerId;
    @Version Long optLock;
    String email;
    String name;
    long version; // aggregate sequence
    protected CustomerView() {}
    public CustomerView(String customerId, String email, String name, long version) {
        this.customerId = customerId; this.email = email; this.name = name; this.version = version;
    }
}

interface CustomerViewRepo extends org.springframework.data.repository.CrudRepository<CustomerView, String> {}

// Side-effect gateway (mute during replay)
interface NotificationService {
    void welcomeEmail(String email, String name);
    static NotificationService muted() { return (e,n) -> {}; }
}

// Projector with idempotency and version guard
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
class CustomerProjector {
    private static final String HANDLER = "CustomerProjector.v1";
    private final CustomerViewRepo viewRepo;
    private final ProcessedEventRepo processed;
    private final NotificationService notifications;
    public enum Mode { LIVE, REPLAY }

    CustomerProjector(CustomerViewRepo viewRepo, ProcessedEventRepo processed, NotificationService notifications) {
        this.viewRepo = viewRepo; this.processed = processed; this.notifications = notifications;
    }

    @Transactional
    public void on(CustomerRegistered ev, Mode mode) {
        if (processed.existsByHandlerAndEventId(HANDLER, ev.eventId())) return; // idempotent

        CustomerView view = viewRepo.findById(ev.aggregateId()).orElse(null);
        if (view == null) {
            view = new CustomerView(ev.aggregateId(), ev.email(), ev.name(), ev.sequence());
        } else if (ev.sequence() <= view.version) {
            // Older or duplicate; ignore
            processed.save(new ProcessedEvent(HANDLER, ev.eventId(), System.currentTimeMillis()));
            return;
        } else {
            view.email = ev.email();
            view.name  = ev.name();
            view.version = ev.sequence();
        }
        viewRepo.save(view);

        if (mode == Mode.LIVE) {
            notifications.welcomeEmail(ev.email(), ev.name()); // suppressed during replay
        }
        processed.save(new ProcessedEvent(HANDLER, ev.eventId(), System.currentTimeMillis()));
    }
}

// Kafka replay controller (topic-level). For brevity, JSON parsing is simplified.
import org.apache.kafka.clients.consumer.*;
import org.apache.kafka.common.TopicPartition;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.*;

@Component
class ReplayController {
    private final CustomerProjector projector;
    private final Upcaster<CustomerRegistered> upcaster;

    ReplayController(CustomerProjector projector, Upcaster<CustomerRegistered> upcaster) {
        this.projector = projector; this.upcaster = upcaster;
    }

    public void replay(String bootstrap, String topic, Optional<Long> fromTimestampMs, Optional<Set<Integer>> partitions) {
        Properties props = new Properties();
        props.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, bootstrap);
        props.put(ConsumerConfig.GROUP_ID_CONFIG, "replay-"+UUID.randomUUID()); // isolate from live
        props.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, "org.apache.kafka.common.serialization.StringDeserializer");
        props.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, "org.apache.kafka.common.serialization.ByteArrayDeserializer");
        props.put(ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, "false");
        props.put(ConsumerConfig.MAX_POLL_RECORDS_CONFIG, "500"); // throttle knob

        try (KafkaConsumer<String, byte[]> consumer = new KafkaConsumer<>(props)) {
            List<PartitionInfo> infos = consumer.partitionsFor(topic);
            List<TopicPartition> tps = new ArrayList<>();
            for (PartitionInfo info : infos) {
                if (partitions.isPresent() && !partitions.get().contains(info.partition())) continue;
                tps.add(new TopicPartition(topic, info.partition()));
            }
            consumer.assign(tps);

            if (fromTimestampMs.isPresent()) {
                Map<TopicPartition, Long> ts = new HashMap<>();
                for (TopicPartition tp : tps) ts.put(tp, fromTimestampMs.get());
                Map<TopicPartition, OffsetAndTimestamp> offsets = consumer.offsetsForTimes(ts);
                for (TopicPartition tp : tps) {
                    OffsetAndTimestamp oat = offsets.get(tp);
                    if (oat != null) consumer.seek(tp, oat.offset());
                    else consumer.seekToBeginning(Collections.singletonList(tp));
                }
            } else {
                consumer.seekToBeginning(tps);
            }

            boolean more = true;
            while (more) {
                ConsumerRecords<String, byte[]> records = consumer.poll(Duration.ofSeconds(1));
                if (records.isEmpty()) { more = false; continue; }
                for (ConsumerRecord<String, byte[]> rec : records) {
                    // deserialize + upcast (pseudo)
                    CustomerRegistered ev = upcaster.upcast(rec.value());
                    projector.on(ev, CustomerProjector.Mode.REPLAY);
                }
            }
        }
    }
}
```

### Notes on the example

-   Uses a **separate consumer group** to avoid disturbing live offsets.
    
-   **Idempotency** is enforced per handler via `processed_event` unique constraint.
    
-   **Version checks** ensure only forward progress for the projection.
    
-   **Side-effects muted** in replay mode.
    
-   **Throttling** via `max.poll.records`; extend with sleep, rate limiters, or token buckets.
    
-   For **partial replays**, pass a timestamp or filter to target aggregates/partitions.
    

## Known Uses

-   **EventStoreDB / Axon / Lagom**: built-in projection rebuild and snapshotting.
    
-   **Kafka ecosystems**: reprocessing via consumer repositioning or Kafka Streams application-reset; common for backfilling lakes and rebuilding materialized views (ksqlDB, Kafka Streams).
    
-   **Cassandra/Elastic projections** in CQRS systems: rebuild read models after mapper/schema changes.
    
-   **Analytics backfills**: replaying logs into warehouse pipelines (e.g., Debezium → Kafka → Snowflake/BigQuery).
    
-   **Payment/ledger systems**: deterministic replays to reconcile balances from transaction events.
    

## Related Patterns

-   **Event Sourcing:** Event Replay depends on a durable event stream.
    
-   **CQRS:** Replay rebuilds read models/materialized views.
    
-   **Snapshotting:** Optimizes replay by shortening the history.
    
-   **Transactional Outbox:** Ensures events reliably reach the log to be replayable.
    
-   **Idempotent Receiver / Exactly-Once Semantics:** Guardrails for safe reprocessing.
    
-   **Event Upcasting (Schema Evolution):** Enables replays across changing event versions.
    
-   **Dead Letter Queue:** For isolating poison events during replay.

