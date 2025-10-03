
# Cloud Distributed Systems Pattern — Write-Behind Cache

## Pattern Name and Classification

-   **Name:** Write-Behind Cache

-   **Classification:** Structural / Data management pattern (performance & throughput); also an asynchronous write buffering pattern.


## Intent

Improve perceived write latency and increase backend throughput by **accepting writes in the cache first** and **persisting them to the system of record asynchronously** (often in **coalesced/batched** form).

## Also Known As

-   Write-Back Cache

-   Asynchronous Write-Through

-   Deferred Persistence / Buffered Writes


## Motivation (Forces)

-   **Latency & Throughput:** Sync writes to a DB/remote store are slow; ack early to the caller and batch writes to increase IOPS and reduce contention.

-   **Cost Efficiency:** Batching reduces connection churn, lock contention, and transaction overhead.

-   **Workload Spikiness:** Absorb bursts in memory and smooth writes to downstream.

-   **Consistency vs. Durability:** Acknowledge early → **eventual** durability; risk of data loss on crash unless mitigated.

-   **Ordering & Coalescing:** Multiple updates to the same key can be coalesced; cross-key ordering is usually not required.

-   **Distributed Coherency:** Other nodes might hold stale cache entries; need invalidation or a single authoritative writer.


## Applicability

Use write-behind when:

-   You can tolerate **eventual durability** (milliseconds–seconds).

-   The business operation is **idempotent** or can be deduplicated (idempotency keys, upserts).

-   The store benefits from **batching/coalescing** (e.g., row updates, counters, time-series).

-   You experience **write bursts** or high write amplification (frequent rewrites of same key).


Avoid or adapt when:

-   You must guarantee **synchronicity** (e.g., funds transfer) or strict external side effects.

-   You can’t accept potential loss of the last N writes without a WAL.

-   Cross-entity transactions must be **atomic** with reads immediately elsewhere.


## Structure

-   **In-Memory Cache:** Latest values; read path hits cache.

-   **Write Queue / Buffer:** Records pending mutations (often coalesced per key).

-   **Flusher / Dispatcher:** Async workers that batch & persist to the backing store with retries.

-   **(Optional) Write-Ahead Log (WAL):** Durable log on local disk for crash recovery.

-   **Backend Store (System of Record):** Database, KV store, or service.


```scss
Client → Cache.put(k,v) ──► (enqueue op; update cache) ──► [Queue]
                                              ▲                 │
                                              └── Flusher (batch persist, retries) → Store
```

## Participants

-   **Cache API:** `get/put/delete` with immediate in-cache update.

-   **Coalescer:** Keeps only the **latest** mutation per key before flush.

-   **Batcher:** Groups ops (size/time) to reduce round-trips.

-   **Retry/Backoff:** Handles transient store failures.

-   **Backpressure:** Caps queue size; sheds or blocks when saturated.

-   **Metrics/Logging:** Queue depth, flush latency, error rate, dropped ops.

-   **(Optional) WAL Manager:** Appends operations durably before acking.


## Collaboration

1.  Client issues `put/delete`.

2.  Cache updates the in-memory value **synchronously** and enqueues a mutation (coalescing by key).

3.  Background flusher wakes on **batch size** or **flush interval**, persists mutations to the store, and clears them on success.

4.  On failure, flusher **retries with backoff** or parks the queue (circuit-break).

5.  Reads hit cache; misses may fall back to store (read-through) or return not found.


## Consequences

**Benefits**

-   Very low write latency perceived by callers.

-   Higher backend throughput via **batching** and **coalescing**.

-   Absorbs spikes; smooths downstream load.


**Liabilities / Trade-offs**

-   **Risk of data loss** on process crash unless a WAL is used.

-   **Eventual durability/consistency**: other readers (on other nodes) may not see updates yet.

-   Complexities: ordering, exactly-once, idempotency, backpressure, eviction, recovery.

-   Cache becomes **source of truth for a while** → careful with cache eviction policies.


## Implementation (Key Points)

-   **Coalescing:** Keep only the latest value per key (last-write-wins) before flush; collapse multiple updates to same key.

-   **Batching:** Flush when `batchSize` or `maxDelay` reached; use upserts if possible.

-   **Per-Key Ordering:** Ensure one key’s updates are persisted in order (single writer per key or sequence numbers).

-   **Durability:** If you must not lose data, write to a **WAL** (append-only file) **before** ack, and replay on startup.

-   **Backpressure:** Bounded queues; decide **block**, **drop latest**, or **drop oldest** under pressure (and surface a 503).

-   **Retries:** Jittered exponential backoff; dead-letter after N attempts.

-   **Eviction:** Don’t evict “dirty” entries; or mark dirty and pin until flush.

-   **Distributed:** Prefer a **single writer** per key (partition by key), or use a stream (Kafka) as the write-behind log.

-   **Observability:** Export queue depth, flush sizes, p50/p95/p99 flush latency, retry counts.


---

## Sample Code (Java 17): Write-Behind KV Cache with Coalescing, Batching, Retry

> Educational (single JVM). It shows:
>
> -   in-memory cache (`ConcurrentHashMap`)
>
> -   bounded queue of **unique keys** with **per-key latest mutation** (coalescing)
>
> -   background **flusher** with batch size & time-based triggers
>
> -   **retry with backoff**, graceful shutdown flush
>
> -   pluggable `KeyValueStore` (here: a simulated slow store)
>

```java
// File: WriteBehindCacheDemo.java
// Compile: javac WriteBehindCacheDemo.java
// Run:     java WriteBehindCacheDemo
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** Contract for the system of record. Prefer idempotent upserts. */
interface KeyValueStore<K,V> {
    void upsertBatch(Map<K,V> kvs) throws Exception;
    void deleteBatch(Set<K> keys) throws Exception;
    Optional<V> get(K key) throws Exception;
}

/** A simple slow store (simulates a DB). */
class SimulatedStore<K,V> implements KeyValueStore<K,V> {
    private final Map<K,V> db = new ConcurrentHashMap<>();
    private final int ioMillis;
    SimulatedStore(int ioMillis) { this.ioMillis = ioMillis; }
    @Override public void upsertBatch(Map<K,V> kvs) throws Exception {
        Thread.sleep(ioMillis);
        db.putAll(kvs);
    }
    @Override public void deleteBatch(Set<K> keys) throws Exception {
        Thread.sleep(ioMillis);
        keys.forEach(db::remove);
    }
    @Override public Optional<V> get(K key) { return Optional.ofNullable(db.get(key)); }
    Map<K,V> snapshot() { return Map.copyOf(db); }
}

/** Write-behind cache with coalescing, batching, retry, and backpressure. */
class WriteBehindCache<K,V> implements AutoCloseable {
    private static final class Mutation<V> {
        enum Kind { UPSERT, DELETE }
        final Kind kind;
        final V value; // null for delete
        Mutation(Kind kind, V v) { this.kind = kind; this.value = v; }
        static <V> Mutation<V> upsert(V v) { return new Mutation<>(Kind.UPSERT, v); }
        static <V> Mutation<V> delete() { return new Mutation<>(Kind.DELETE, null); }
    }

    private final KeyValueStore<K,V> store;
    private final ConcurrentHashMap<K,V> cache = new ConcurrentHashMap<>();

    // Coalescing state: latest pending mutation per key
    private final ConcurrentHashMap<K,Mutation<V>> pending = new ConcurrentHashMap<>();
    // Queue only holds keys to flush (each key appears at most once) -> lock-light backpressure
    private final BlockingQueue<K> queue;
    private final int batchSize;
    private final Duration flushInterval;
    private final ExecutorService flusherExecutor = Executors.newSingleThreadExecutor();
    private final AtomicBoolean running = new AtomicBoolean(true);

    // Retry params
    private final int maxRetries;
    private final Duration initialBackoff;
    private final Duration maxBackoff;

    WriteBehindCache(KeyValueStore<K,V> store,
                     int queueCapacity,
                     int batchSize,
                     Duration flushInterval,
                     int maxRetries,
                     Duration initialBackoff,
                     Duration maxBackoff) {
        this.store = store;
        this.queue = new ArrayBlockingQueue<>(queueCapacity);
        this.batchSize = Math.max(1, batchSize);
        this.flushInterval = flushInterval;
        this.maxRetries = maxRetries;
        this.initialBackoff = initialBackoff;
        this.maxBackoff = maxBackoff;
        startFlusher();
    }

    /** Read from cache first; on miss you might read-through (optional). */
    public Optional<V> get(K key) {
        V v = cache.get(key);
        return Optional.ofNullable(v);
    }

    /** Upsert: update cache, record latest mutation, and enqueue key. */
    public void put(K key, V value) {
        cache.put(key, value);
        enqueue(key, Mutation.upsert(value));
    }

    /** Delete: mark cache and enqueue key. */
    public void delete(K key) {
        cache.remove(key); // or mark tombstone; choice depends on read semantics
        enqueue(key, Mutation.delete());
    }

    private void enqueue(K key, Mutation<V> m) {
        pending.put(key, m);
        // ensure the key is present once in the queue; if full, apply backpressure strategy
        boolean offered = queue.offer(key);
        if (!offered) {
            // Backpressure: block briefly; in real systems consider drop-oldest or 503 upstream
            try { queue.put(key); } catch (InterruptedException ie) { Thread.currentThread().interrupt(); }
        }
    }

    private void startFlusher() {
        flusherExecutor.submit(() -> {
            List<K> batchKeys = new ArrayList<>(batchSize);
            long nextFlushAt = System.nanoTime() + flushInterval.toNanos();

            while (running.get() || !queue.isEmpty()) {
                try {
                    long waitNanos = Math.max(0, nextFlushAt - System.nanoTime());
                    K key = queue.poll(waitNanos, TimeUnit.NANOSECONDS);
                    if (key != null) {
                        // de-dup: key might have been coalesced again; just collect it
                        batchKeys.add(key);
                    }
                    if (batchKeys.size() >= batchSize || key == null) {
                        // time-based or size-based flush
                        if (!batchKeys.isEmpty()) flushBatch(batchKeys);
                        batchKeys.clear();
                        nextFlushAt = System.nanoTime() + flushInterval.toNanos();
                    }
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                } catch (Exception e) {
                    // last resort: log and continue; in prod use logging/metrics
                    System.err.println("flusher error: " + e);
                }
            }
            // final drain on shutdown
            if (!batchKeys.isEmpty()) {
                try { flushBatch(batchKeys); } catch (Exception e) { System.err.println("final flush error: " + e); }
            }
        });
    }

    private void flushBatch(List<K> batchKeys) throws Exception {
        // Build concrete batches from the latest pending mutations
        Map<K,V> upserts = new LinkedHashMap<>();
        Set<K> deletes = new LinkedHashSet<>();

        for (K k : batchKeys) {
            Mutation<V> m = pending.remove(k);
            if (m == null) continue; // already flushed or re-coalesced
            if (m.kind == Mutation.Kind.UPSERT) { upserts.put(k, m.value); deletes.remove(k); }
            else { deletes.add(k); upserts.remove(k); }
        }
        if (upserts.isEmpty() && deletes.isEmpty()) return;

        // Persist with retries
        int attempt = 1;
        Duration backoff = initialBackoff;
        while (true) {
            try {
                if (!upserts.isEmpty()) store.upsertBatch(upserts);
                if (!deletes.isEmpty()) store.deleteBatch(deletes);
                return;
            } catch (Exception ex) {
                if (attempt++ > maxRetries) {
                    // Dead-letter: re-enqueue or log; here we re-enqueue to try later
                    System.err.println("flush failed, re-enqueueing; last error: " + ex);
                    upserts.forEach((k, v) -> enqueue(k, Mutation.upsert(v)));
                    for (K k : deletes) enqueue(k, Mutation.delete());
                    return;
                }
                Thread.sleep(jitter(backoff).toMillis());
                backoff = backoff.multipliedBy(2);
                if (backoff.compareTo(maxBackoff) > 0) backoff = maxBackoff;
            }
        }
    }

    private static Duration jitter(Duration d) {
        long ms = d.toMillis();
        long j = ThreadLocalRandom.current().nextLong(0, ms + 1);
        return Duration.ofMillis(j);
    }

    @Override public void close() {
        running.set(false);
        flusherExecutor.shutdown();
        try { flusherExecutor.awaitTermination(5, TimeUnit.SECONDS); } catch (InterruptedException ignored) {}
    }

    // Expose a few metrics
    public int pendingSize() { return pending.size(); }
    public int queueSize() { return queue.size(); }
}

/** Demo */
public class WriteBehindCacheDemo {
    public static void main(String[] args) throws Exception {
        var store = new SimulatedStore<String, String>(100); // ~100ms/storage op
        try (var cache = new WriteBehindCache<String,String>(
                store,
                10_000,                          // queue capacity
                256,                             // batch size
                Duration.ofMillis(50),           // flush interval
                5,                                // max retries
                Duration.ofMillis(50),           // initial backoff
                Duration.ofSeconds(2))) {        // max backoff

            // Simulate many updates to same keys (coalescing will collapse)
            for (int i = 0; i < 1000; i++) {
                String key = "user:" + (i % 100); // 100 hot keys
                cache.put(key, "v" + i);
            }

            // Small pause to allow flushing
            Thread.sleep(1500);

            // Verify some data landed in the store
            System.out.println("Store snapshot size: " + store.snapshot().size());
            System.out.println("Pending queue: " + cache.queueSize() + ", pending map: " + cache.pendingSize());

            // Delete a few keys
            cache.delete("user:3");
            cache.delete("user:7");
            Thread.sleep(300);

            System.out.println("user:3 in store? " + store.snapshot().containsKey("user:3"));
        }
        System.out.println("Done.");
    }
}
```

**What this example demonstrates**

-   **Coalescing:** multiple `put` on the same key collapses into one batched upsert.

-   **Batching & timed flush:** either **size** or **time** triggers a flush.

-   **Retry with jittered backoff** and **re-enqueue** after max failures.

-   **Graceful shutdown:** final drain attempt on `close()`.


> Productionize with: a **WAL** for crash safety, pluggable serialization, observability (queue depth, flush p95/p99), and distributed partitioning (e.g., Kafka topic keyed by `K` so exactly one consumer writes a given key).

---

## Known Uses

-   **Ehcache / Terracotta write-behind:** asynchronous `CacheWriter` with coalescing and batching.

-   **Hazelcast MapStore (write-behind):** async persistence for `IMap` entries.

-   **Redis client-side write-behind patterns:** queue + Lua script batch upserts to Redis/RDBMS.

-   **CDNs / log pipelines:** buffers that acknowledge upstream and persist later (analogous pattern).

-   **Kafka Connect sinks:** de-facto write-behind from Kafka to DBs with batching and retries.


## Related Patterns

-   **Write-Through Cache:** Synchronous write to store on each cache write (safer, higher latency).

-   **Read-Through / Cache-Aside:** Read path patterns often paired with write-behind.

-   **Outbox / Transactional Outbox:** Durable, exactly-once handoff to async processors (stronger durability than in-memory queues).

-   **Event Sourcing:** Append events durably instead of write-behind state.

-   **Bulkhead & Backpressure:** Bound queue sizes and shed load under pressure.

-   **Retry with Backoff & Circuit Breaker:** Handle transient store failures without meltdown.

-   **Sharding / Single-Writer:** Partition keys so one writer flushes a given key to keep order.


---

### Practical Tips

-   If data loss is unacceptable, **append to a WAL** (fsync) **before** acking the client; replay on restart.

-   Keep a **bounded queue** and a clear policy under pressure (block vs. drop vs. 503).

-   Use **idempotent upserts** and **versioning** (ETag/row version) to avoid stale overwrites.

-   Pin or mark **dirty** entries; avoid evicting them before flush.

-   Export metrics and alert on **flush error rate** and **queue depth**; autoscale flusher threads conservatively.

-   In distributed systems, prefer a **partitioned stream** (e.g., Kafka) as the write-behind bus; consumers act as the flusher tier.
