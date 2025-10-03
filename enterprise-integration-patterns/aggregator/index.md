# Aggregator (Enterprise Integration Pattern)

## Pattern Name and Classification

**Name:** Aggregator  
**Classification:** Enterprise Integration Pattern (Message Routing / Stateful Endpoint)

---

## Intent

Collect **related messages** (by a **correlation key**) and **combine** them into a single, meaningful message once a **completion condition** is met (e.g., count, timeout, predicate), then forward the aggregated result downstream.

---

## Also Known As

-   Message Aggregator
    
-   Correlation Aggregator
    
-   Join / Barrier (informal)
    

---

## Motivation (Forces)

-   Upstream systems often emit **partial information** or **fragments** at different times.
    
-   Consumers need a **single, coherent message** (e.g., a complete order assembled from item, payment, shipment events).
    
-   Real-world constraints introduce **duplicates, out-of-order delivery, and stragglers**.
    
-   We must balance **freshness** (timely output) vs **completeness** (wait for all parts) and control **memory growth**.
    

Forces to balance:

-   **Correlation** (how to group)
    
-   **Completion** (when to stop waiting)
    
-   **Idempotency & duplicates**
    
-   **Ordering & late arrivals**
    
-   **Back-pressure & resource limits**
    
-   **Fault tolerance & persistence of in-flight state**
    

---

## Applicability

Use an Aggregator when:

-   A downstream step requires **all** or **enough** parts to proceed (N-of-M).
    
-   Messages are **sharded** across producers and must be **reassembled**.
    
-   You must **enrich** or **summarize** a stream (e.g., rolling window totals).
    
-   You need **time-windowed** analytics or **request-reply fan-out/fan-in**.
    

Avoid or limit when:

-   A single message already carries all required data (no fan-out).
    
-   You need **streaming join semantics** at very high volume—consider **stream processors** (Kafka Streams, Flink) instead of an in-memory aggregator.
    
-   Hard real-time systems where waiting jeopardizes SLAs and partial results are unacceptable.
    

---

## Structure

-   **Input Channel(s):** Incoming fragments.
    
-   **Aggregator:**
    
    -   **Correlation Strategy:** Derives `correlationId` from headers/payload.
        
    -   **Release Strategy:** Completion rules (size/time/predicate).
        
    -   **Aggregation Strategy:** Combines fragments deterministically.
        
    -   **State Store:** Keeps groups, timers, dedup sets, and metadata.
        
-   **Output Channel:** Emits the aggregated message.
    
-   **Dead Letter Channel (optional):** Late or poison messages.
    

---

## Participants

-   **Producers:** Emit fragments with a **Correlation ID** and **Message ID**.
    
-   **Aggregator Endpoint:** Stateful processor with completion & aggregation policies.
    
-   **State Store:** In-memory or durable (DB/Redis/KV topic).
    
-   **Timer Service:** Triggers timeouts for stuck groups.
    
-   **Consumers:** Receive the aggregated result.
    

---

## Collaboration

1.  Fragment arrives → **Correlation Strategy** computes `correlationId`.
    
2.  Aggregator stores the fragment in the **group** and updates metadata (count, seen message IDs, deadlines).
    
3.  **Release Strategy** checks completion (e.g., “received 5 parts” OR “10s elapsed” OR “all required types seen”).
    
4.  When complete, **Aggregation Strategy** combines fragments → **result** is emitted.
    
5.  Group state is **evicted** (or archived) and late fragments are handled (discard, re-open window, or send to DLQ).
    

---

## Consequences

**Benefits**

-   Decouples producers from synchronous coordination.
    
-   Produces **coherent, deduplicated** outputs.
    
-   Encodes **business completion** logic explicitly.
    
-   Enables **windowed** or **N-of-M** processing patterns.
    

**Liabilities**

-   **Stateful** ⇒ needs memory/durable storage, eviction.
    
-   Sensitive to **skew** (many fragments for one key).
    
-   **Timeout tuning** and **late data** policies add complexity.
    
-   Requires **idempotency** and **exactly-once** illusions are costly—design for at-least-once.
    

---

## Implementation

**Key guidelines**

-   **Correlation:** Deterministic key (header like `X-Correlation-Id`, or payload fields).
    
-   **Completion:** Combine multiple strategies:
    
    -   **Count-based** (M parts), **Type-based** (all required types), **Time-based** (idle or absolute TTL), **Predicate-based** (e.g., sum of weights ≥ target).
        
-   **Idempotency:** Track `messageId` per group to drop duplicates.
    
-   **Ordering:** Don’t assume order; aggregation must be **commutative/associative** where possible.
    
-   **State store:** Start in-memory; move to **durable** (RDBMS/Redis/Kafka compacted topic) for HA.
    
-   **Back-pressure:** Limit groups & parts per key; shed load or spill to disk.
    
-   **Late events:** Policy: drop, log to DLQ, or open a **new window** with versioned aggregation.
    
-   **Observability:** Metrics per group count, lag, time to completion, expiries, DLQ rates.
    
-   **Recovery:** Persist state & timers (or reconstruct timers from deadlines on restart).
    

---

## Sample Code (Java, framework-agnostic Aggregator)

This is a lightweight, production-shaped sketch supporting **count** and **timeout** completion, **idempotency**, and a pluggable **aggregation function**.

```java
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.*;
import java.util.stream.Collectors;

/** Simple message envelope */
public final class Message<T> {
    private final String id;              // unique per message (for dedup)
    private final Map<String, String> headers;
    private final T payload;

    public Message(String id, Map<String, String> headers, T payload) {
        this.id = Objects.requireNonNull(id);
        this.headers = Map.copyOf(headers);
        this.payload = payload;
    }
    public String id() { return id; }
    public Map<String, String> headers() { return headers; }
    public T payload() { return payload; }
}

/** Aggregated output message */
public final class AggregatedMessage<R> extends Message<R> {
    public AggregatedMessage(String id, Map<String, String> headers, R payload) {
        super(id, headers, payload);
    }
}

/** Completion policy: determines if a group is ready */
interface CompletionPolicy<T> {
    boolean isComplete(GroupState<T> group);
}

/** Aggregation logic: folds fragments into a result */
interface AggregationStrategy<T, R> {
    R aggregate(List<Message<T>> messages);
}

/** Correlation function */
interface Correlation<T> {
    String correlationId(Message<T> msg);
}

/** Output sink */
interface Sink<R> {
    void emit(AggregatedMessage<R> message);
}

/** In-flight group state */
final class GroupState<T> {
    final String key;
    final List<Message<T>> messages = new ArrayList<>();
    final Set<String> seenMsgIds = new HashSet<>();
    Instant deadline;
    int expectedCount = -1; // optional target

    GroupState(String key) { this.key = key; }
}

/** Count-based completion */
final class CountCompletion<T> implements CompletionPolicy<T> {
    @Override public boolean isComplete(GroupState<T> g) {
        return g.expectedCount > 0 && g.messages.size() >= g.expectedCount;
    }
}

/** Time-based (deadline) completion */
final class DeadlineCompletion<T> implements CompletionPolicy<T> {
    @Override public boolean isComplete(GroupState<T> g) {
        return g.deadline != null && Instant.now().isAfter(g.deadline);
    }
}

/** Composite policy (OR semantics) */
final class AnyOfCompletion<T> implements CompletionPolicy<T> {
    private final List<CompletionPolicy<T>> policies;
    AnyOfCompletion(List<CompletionPolicy<T>> policies) { this.policies = policies; }
    @Override public boolean isComplete(GroupState<T> g) {
        for (var p : policies) if (p.isComplete(g)) return true;
        return false;
    }
}

/** The Aggregator */
public final class Aggregator<T, R> {

    private final Correlation<T> correlation;
    private final AggregationStrategy<T, R> strategy;
    private final CompletionPolicy<T> completion;
    private final Sink<R> sink;
    private final Duration groupTtl;                  // max lifetime
    private final ScheduledExecutorService timers = Executors.newSingleThreadScheduledExecutor();
    private final ConcurrentHashMap<String, GroupState<T>> groups = new ConcurrentHashMap<>();
    private final int maxMessagesPerGroup;

    public Aggregator(Correlation<T> correlation,
                      AggregationStrategy<T, R> strategy,
                      CompletionPolicy<T> completion,
                      Sink<R> sink,
                      Duration groupTtl,
                      int maxMessagesPerGroup) {
        this.correlation = correlation;
        this.strategy = strategy;
        this.completion = completion;
        this.sink = sink;
        this.groupTtl = groupTtl;
        this.maxMessagesPerGroup = maxMessagesPerGroup;
        // periodic sweep for timeouts
        timers.scheduleAtFixedRate(this::sweep, 1, 1, TimeUnit.SECONDS);
    }

    public void accept(Message<T> msg) {
        final String key = correlation.correlationId(msg);
        var g = groups.computeIfAbsent(key, GroupState::new);

        synchronized (g) {
            // dedup
            if (!g.seenMsgIds.add(msg.id())) return;

            // (optional) set expected count from header if present
            if (g.expectedCount < 0) {
                var ec = msg.headers().get("X-Expected-Count");
                if (ec != null) g.expectedCount = Integer.parseInt(ec);
            }

            // deadline
            if (g.deadline == null) {
                var ttlHeader = msg.headers().getOrDefault("X-Group-TTL-Seconds", String.valueOf(groupTtl.toSeconds()));
                g.deadline = Instant.now().plusSeconds(Long.parseLong(ttlHeader));
            }

            // guard memory
            if (g.messages.size() >= maxMessagesPerGroup) {
                // emit early to prevent unbounded growth
                completeAndEmit(g, "early-evict");
                return;
            }

            g.messages.add(msg);

            if (completion.isComplete(g)) {
                completeAndEmit(g, "complete");
            }
        }
    }

    private void completeAndEmit(GroupState<T> g, String reason) {
        var list = List.copyOf(g.messages);
        var result = strategy.aggregate(list);
        var headers = new HashMap<String, String>();
        headers.put("X-Correlation-Id", g.key);
        headers.put("X-Completion-Reason", reason);
        headers.put("X-Group-Size", String.valueOf(list.size()));
        sink.emit(new AggregatedMessage<>(UUID.randomUUID().toString(), headers, result));
        groups.remove(g.key); // evict
    }

    private void sweep() {
        var now = Instant.now();
        for (var e : groups.entrySet()) {
            var g = e.getValue();
            synchronized (g) {
                if (g.deadline != null && now.isAfter(g.deadline)) {
                    completeAndEmit(g, "deadline");
                }
            }
        }
    }

    public void shutdown() {
        timers.shutdownNow();
    }
}
```

### Example wiring

```java
// Correlate by header; aggregate payloads into a single list; complete by count OR deadline
Correlation<String> corr = m -> m.headers().get("X-Correlation-Id");
AggregationStrategy<String, List<String>> strat = parts ->
        parts.stream().map(Message::payload).collect(Collectors.toList());
CompletionPolicy<String> policy = new AnyOfCompletion<>(List.of(new CountCompletion<>(), new DeadlineCompletion<>()));

Sink<List<String>> sink = msg -> {
    System.out.println("Aggregated key=" + msg.headers().get("X-Correlation-Id")
            + " size=" + msg.headers().get("X-Group-Size") + " -> " + msg.payload());
};

var agg = new Aggregator<>(
        corr, strat, policy, sink,
        Duration.ofSeconds(10), // default TTL per group
        10_000                  // max messages per group
);

// Send fragments
for (int i = 1; i <= 3; i++) {
    var headers = Map.of("X-Correlation-Id", "order-42", "X-Expected-Count", "3");
    agg.accept(new Message<>(UUID.randomUUID().toString(), headers, "part-" + i));
}
// emits once 3 parts are seen (or deadline fires)
```

**Notes**

-   The sample demonstrates **dedup**, **count-based completion**, **deadline**, and **idempotent aggregation**.
    
-   In production, back this with a **durable store** and restore timers from persisted deadlines on restart.
    

---

## Known Uses

-   **Request fan-out / reply fan-in:** Query multiple services and return a single response.
    
-   **Document assembly:** Merge line items, taxes, and discounts into an invoice.
    
-   **Event collation:** Build a “complete order” from item, payment, shipment events.
    
-   **Stream windows:** Fixed/rolling time windows for KPIs (e.g., 1-min sum per key).
    
-   **IoT:** Combine sensor readings across devices into a scene snapshot.
    

---

## Related Patterns

-   **Splitter:** Opposite direction—break a message into parts.
    
-   **Resequencer:** Reorder out-of-order messages before aggregation if order matters.
    
-   **Composed Message Processor:** Split → process → aggregate pipeline.
    
-   **Content Enricher / Filter:** Modify or drop fragments prior to aggregation.
    
-   **Claim Check:** Store large payloads externally; aggregate using references.
    
-   **Barrier / Join Router:** Logical cousin when waiting for multiple paths to complete.
    

---

