# Resequencer — Enterprise Integration Pattern

## Pattern Name and Classification

**Name:** Resequencer  
**Classification:** State Management / Routing pattern (EIP); restores **intended order** of related messages that arrive **out of order**.

## Intent

Buffer and reorder messages that share a **correlation key** (e.g., `orderId`, `streamId`) based on a **sequence number** (or timestamp/ordering key) so that downstream consumers observe them in the **correct sequence**.

## Also Known As

-   Message Reordering
    
-   Sequence Enforcer
    
-   Ordered Delivery Restorer
    

## Motivation (Forces)

-   Many transports provide only per-partition or best-effort ordering; retries and parallelism cause **out-of-order delivery**.
    
-   Some operations require **monotonic application** (state transitions, versioned updates, ledger entries).
    
-   We need to balance **correctness** against **latency/memory** by buffering, detecting **gaps**, and timing out late messages.
    

**Forces to balance**

-   Strict ordering vs. throughput/latency.
    
-   Memory usage vs. gap window size.
    
-   Handling **duplicates** and **missing** messages.
    
-   Per-key ordering across **shards/partitions**.
    

## Applicability

Use a Resequencer when:

-   Messages include (or can be derived to include) a **sequence** (e.g., `version`, `offset`, `eventNumber`, Lamport time).
    
-   Downstream logic **depends** on order (billing adjustments, inventory deltas, workflow steps).
    
-   Transport may redeliver, reorder, or parallelize consumption.
    

Avoid or limit when:

-   Order is irrelevant or can be enforced via **idempotent state** (e.g., full snapshots).
    
-   Broker can natively guarantee the order you need (e.g., single partition keyed correctly) and you can rely on it.
    

## Structure

```rust
+--------------------+
Inbound Channel ->   Resequencer      -> Outbound Channel (ordered per key)
                 |  - buffer by key   |
                 |  - detect gaps     |
                 |  - emit in order   |
                 +--------------------+

State:
  per key: nextExpected, buffer{seqNo -> message}, watermark/timeout
```

## Participants

-   **Resequencer:** Component that buffers, detects gaps, and emits in order per key.
    
-   **Correlation Key Extractor:** Derives the stream key (e.g., `orderId`).
    
-   **Sequence Extractor:** Reads sequence (e.g., `version`, `seqNo`, logical clock).
    
-   **Message Store:** Durable state for buffers and `nextExpected` (DB, Redis, state store).
    
-   **Timeout/Watermark Policy:** Determines when to **skip** gaps or **flush** partial sequences.
    
-   **Downstream Consumer:** Receives ordered messages.
    

## Collaboration

1.  Message arrives → extract **key** and **sequence**.
    
2.  If `seq == nextExpected`, **emit** and increment; then drain buffered contiguous successors.
    
3.  Else buffer and wait for missing numbers up to **timeout/window**.
    
4.  On **timeout**, either **emit surviving sequence** (skipping gaps with a marker) or route late/missing to **DLQ**.
    
5.  Persist resequencer state to survive crashes and avoid re-disordering.
    

## Consequences

**Benefits**

-   Restores domain-required ordering; downstream logic remains simple.
    
-   Localizes buffering and gap handling policy.
    
-   Works with at-least-once delivery if paired with **Idempotent Receiver**.
    

**Liabilities**

-   Requires additional **state, memory, and latency**.
    
-   Poorly chosen windows lead to either **stalls** (too strict) or **reordered leakage** (too lax).
    
-   Needs careful **timeout** and **duplicate** strategies.
    
-   Per-key hotspots can create uneven resource usage.
    

## Implementation

-   **Keys & sequences:**
    
    -   Prefer **monotonic integers** or **vector/lamport** clocks; timestamps are weaker (use with watermarks).
        
    -   Partition upstream by key to confine resequencing to a partition where possible.
        
-   **State storage:**
    
    -   In-memory + periodic **checkpoint** (for low risk).
        
    -   **Relational/Redis** (durable) using a `message_store` table keyed by `(key, seq)`.
        
    -   **Stream state stores** (Kafka Streams, Pulsar Functions) for embedded durability.
        
-   **Gap handling:**
    
    -   **Time-based watermark** per key (e.g., 5s or p99 interarrival).
        
    -   **Count-based** (max out-of-order distance).
        
    -   Policy for late arrivals: **drop**, **send to DLQ**, or **emit correction** event.
        
-   **Duplicates:** Keep a **processed set** or rely on **Idempotent Receiver** downstream; dedupe in buffer.
    
-   **Throughput:** Bound buffer size per key; evict with metrics and alarms.
    
-   **Observability:** Track `buffer_size`, `late_events`, `timeouts`, `skipped_sequences`.
    
-   **Recovery:** Persist `nextExpected` and buffered entries; drain in-order on restart.
    

---

## Sample Code (Java)

### A) Spring Integration — Built-in Resequencer with JDBC Message Store

```java
// build.gradle: spring-boot-starter-integration, spring-jdbc, jackson
@Configuration
@EnableIntegration
public class ResequencerFlow {

  @Bean
  public MessageChannel in() { return new DirectChannel(); }

  @Bean
  public MessageChannel orderedOut() { return new DirectChannel(); }

  // Persist groups (per correlation key) so we survive restarts
  @Bean
  public org.springframework.integration.store.MessageGroupStore messageGroupStore(DataSource ds) {
    return new org.springframework.integration.jdbc.JdbcMessageStore(ds);
  }

  @Bean
  public IntegrationFlow resequence() {
    return IntegrationFlows.from("in")
      .transform(Transformers.fromJson(OrderEvent.class))
      // correlate by orderId; sequenceNumber from event.version
      .enrich(e -> e
        .headerFunction(IntegrationMessageHeaderAccessor.CORRELATION_ID,
            m -> ((OrderEvent) m.getPayload()).orderId())
        .headerFunction(IntegrationMessageHeaderAccessor.SEQUENCE_NUMBER,
            m -> ((OrderEvent) m.getPayload()).version())
        .headerFunction(IntegrationMessageHeaderAccessor.SEQUENCE_SIZE, m -> -1)) // unknown size
      .resequence(r -> r
        .correlationStrategy(m -> m.getHeaders().getCorrelationId())
        .releaseStrategy(group -> {
          // release when next expected is present; SI handles contiguous drain
          // fallback to timeout
          return false; // default contiguous-release
        })
        .messageStore(messageGroupStore(null))
        .expireGroupsUponCompletion(true)
        .sendPartialResultOnExpiry(true)
        .groupTimeout(5_000)) // watermark/timeout per group
      .channel("orderedOut")
      .handle((payload, headers) -> {
        // ordered processing here
        return null;
      })
      .get();
  }
}

public record OrderEvent(String orderId, long version, String type, String data) {}
```

### B) Apache Camel — Resequencer EIP (Streaming Mode)

```java
// build.gradle: camel-core, camel-jackson, camel-kafka
public class ResequencerRoutes extends org.apache.camel.builder.RouteBuilder {
  @Override
  public void configure() {
    from("kafka:orders.v1?groupId=reseq")
      .routeId("orders-resequencer")
      .unmarshal().json(org.apache.camel.model.dataformat.JsonLibrary.Jackson, OrderEvent.class)
      // camel's resequencer can work in batch or stream mode
      .resequence().simple("${body.orderId}:${body.version}")
        .stream()
        .timeout(5000)          // release after 5s if gaps persist
        .capacity(1000)         // buffer size bound
        .to("kafka:orders.ordered.v1");
  }
}

public record OrderEvent(String orderId, long version, String type, String payload) {}
```

### C) Kafka Streams — Per-key Resequencing with State Store (strict contiguous policy)

```java
// build.gradle: kafka-streams, jackson-databind
public class StreamsResequencerApp {
  public static void main(String[] args) {
    var props = new java.util.Properties();
    props.put(org.apache.kafka.streams.StreamsConfig.APPLICATION_ID_CONFIG, "orders-resequencer");
    props.put(org.apache.kafka.streams.StreamsConfig.BOOTSTRAP_SERVERS_CONFIG, "localhost:9092");
    var builder = new org.apache.kafka.streams.StreamsBuilder();

    var serde = JsonSerdes.serdeFor(OrderEvent.class);
    var in = builder.stream("orders.v1",
        org.apache.kafka.streams.Consumed.with(org.apache.kafka.common.serialization.Serdes.String(), serde));

    // Processor API for fine control
    in.process(() -> new ResequencerProcessor(), "reseq-store");

    var topo = builder.build();
    var streams = new org.apache.kafka.streams.KafkaStreams(topo, props);
    streams.start();
  }

  // POJO
  public record OrderEvent(String orderId, long version, String type, String data) {}

  // Serde helper (implement your serde or use a JSON serde lib)
  static final class JsonSerdes {
    static <T> org.apache.kafka.common.serialization.Serde<T> serdeFor(Class<T> cls) {
      var mapper = new com.fasterxml.jackson.databind.ObjectMapper();
      var ser = new org.apache.kafka.common.serialization.Serializer<T>() {
        public byte[] serialize(String t, T obj) { try { return mapper.writeValueAsBytes(obj); } catch (Exception e) { throw new RuntimeException(e);} }
      };
      var de = new org.apache.kafka.common.serialization.Deserializer<T>() {
        public T deserialize(String t, byte[] bytes) { try { return mapper.readValue(bytes, cls); } catch (Exception e) { throw new RuntimeException(e);} }
      };
      return org.apache.kafka.common.serialization.Serdes.serdeFrom(ser, de);
    }
  }

  static final class ResequencerProcessor implements org.apache.kafka.streams.processor.api.Processor<String, OrderEvent, String, OrderEvent> {
    private org.apache.kafka.streams.processor.api.ProcessorContext<String, OrderEvent> ctx;
    private org.apache.kafka.streams.state.KeyValueStore<String, byte[]> bufStore;   // version->payload map (JSON)
    private org.apache.kafka.streams.state.KeyValueStore<String, Long> nextStore;    // nextExpected per key
    private static final long TIMEOUT_MS = 5000;

    @Override
    public void init(org.apache.kafka.streams.processor.api.ProcessorContext<String, OrderEvent> context) {
      this.ctx = context;
      var storeCtx = (org.apache.kafka.streams.processor.api.RecordMetadata) null;
      this.bufStore = context.getStateStore("reseq-store-buf");
      this.nextStore = context.getStateStore("reseq-store-next");
      // schedule punctuation to enforce timeouts
      context.schedule(java.time.Duration.ofMillis(1000),
          org.apache.kafka.streams.processor.PunctuationType.WALL_CLOCK_TIME, ts -> flushTimedOut(ts));
    }

    @Override
    public void process(org.apache.kafka.streams.processor.api.Record<String, OrderEvent> rec) {
      var key = rec.key(); // must be orderId
      var evt = rec.value();
      long next = nextStore.get(key) == null ? 1L : nextStore.get(key); // assume sequence starts at 1
      // Duplicate?
      if (evt.version() < next) return;

      // If it's the next expected, emit and drain
      if (evt.version() == next) {
        emit(rec.withValue(evt));
        nextStore.put(key, next + 1);
        drain(key, next + 1);
        return;
      }

      // Otherwise buffer with arrival time
      var mapper = new com.fasterxml.jackson.databind.ObjectMapper();
      var bufKey = bufKey(key, evt.version());
      var wrapped = new Buffered(mapper.writeValueAsBytes(evt), System.currentTimeMillis());
      bufStore.put(bufKey, mapper.writeValueAsBytes(wrapped));
    }

    private void drain(String key, long start) {
      long cur = start;
      for (;;) {
        var bytes = bufStore.get(bufKey(key, cur));
        if (bytes == null) break;
        var mapper = new com.fasterxml.jackson.databind.ObjectMapper();
        try {
          var wrapped = mapper.readValue(bytes, Buffered.class);
          var evt = mapper.readValue(wrapped.payload, OrderEvent.class);
          emit(new org.apache.kafka.streams.processor.api.Record<>(key, evt, ctx.currentSystemTimeMs()));
        } catch (Exception e) { throw new RuntimeException(e); }
        bufStore.delete(bufKey(key, cur));
        cur++;
        nextStore.put(key, cur);
      }
    }

    private void flushTimedOut(long now) {
      // For simplicity, skip implementing full scan; in production keep a per-key index of oldest buffered
      // and emit partial sequences or move late events to a DLQ topic when now - arrival > TIMEOUT_MS
    }

    private void emit(org.apache.kafka.streams.processor.api.Record<String, OrderEvent> r) {
      ctx.forward(r.withTopic("orders.ordered.v1"));
    }

    private String bufKey(String key, long ver) { return key + "#" + ver; }

    static final class Buffered {
      public byte[] payload; public long arrivalMs;
      Buffered() {}
      Buffered(byte[] p, long a) { this.payload = p; this.arrivalMs = a; }
    }
  }

  // Register state stores via topology builder (omitted for brevity). In practice, define:
  // Stores.keyValueStoreBuilder(...).withLoggingEnabled(...) for both nextStore and bufStore.
}
```

### D) DIY In-Memory Resequencer (library component for small services)

```java
public class InMemoryResequencer<K, V> {

  private static class Entry<V> { final V v; final long ts; Entry(V v, long ts){ this.v=v; this.ts=ts; } }
  private final java.util.concurrent.ConcurrentMap<K, java.util.concurrent.ConcurrentSkipListMap<Long, Entry<V>>> buffers = new java.util.concurrent.ConcurrentHashMap<>();
  private final java.util.concurrent.ConcurrentMap<K, Long> nextExpected = new java.util.concurrent.ConcurrentHashMap<>();
  private final long timeoutMs;
  private final java.util.function.BiConsumer<K, V> emitter;

  public InMemoryResequencer(long timeoutMs, java.util.function.BiConsumer<K, V> emitter) {
    this.timeoutMs = timeoutMs; this.emitter = emitter;
  }

  public void onMessage(K key, long seq, V value) {
    long next = nextExpected.getOrDefault(key, 1L);
    if (seq < next) return; // duplicate/late
    if (seq == next) {
      emit(key, value);
      nextExpected.put(key, next + 1);
      drain(key);
      return;
    }
    buffers.computeIfAbsent(key, k -> new java.util.concurrent.ConcurrentSkipListMap<>())
           .put(seq, new Entry<>(value, System.currentTimeMillis()));
  }

  public void tick() { // call periodically
    long now = System.currentTimeMillis();
    buffers.forEach((k, map) -> {
      var first = map.firstEntry();
      if (first == null) return;
      if (now - first.getValue().ts > timeoutMs) {
        // skip gap: advance nextExpected to the first buffered seq and emit it
        long next = nextExpected.getOrDefault(k, 1L);
        long seq = first.getKey();
        nextExpected.put(k, seq);
        drain(k);
      }
    });
  }

  private void drain(K key) {
    long next = nextExpected.getOrDefault(key, 1L);
    var map = buffers.getOrDefault(key, new java.util.concurrent.ConcurrentSkipListMap<>());
    for (;;) {
      var e = map.remove(next);
      if (e == null) break;
      emit(key, e.v);
      next++;
      nextExpected.put(key, next);
    }
  }

  private void emit(K key, V v) { emitter.accept(key, v); }
}
```

---

## Known Uses

-   **Order/state change streams** where updates must apply in version order (e-commerce, CRM).
    
-   **Financial postings** and **ledger** updates that require monotonic event numbers.
    
-   **IoT telemetry** where sensor batches can arrive late or out-of-order; resequenced by device ID.
    
-   **Workflow engines** aggregating steps that may complete out of order.
    

## Related Patterns

-   **Message Store:** Persists buffers and `nextExpected` state.
    
-   **Aggregator:** Often used together to collect complete sets before emission.
    
-   **Idempotent Receiver:** Prevents duplicate effects once resequenced.
    
-   **Competing Consumers / Consumer Groups:** Upstream scaling—ensure proper **keying**.
    
-   **Message Router:** Route to per-key resequencers (shard by key).
    
-   **Dead Letter Channel:** Late/invalid messages or gap timeouts can be parked here.

