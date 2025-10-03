# Cloud Distributed Systems Pattern — Read-Through Cache

## Pattern Name and Classification

-   **Name:** Read-Through Cache

-   **Classification:** Data access & performance pattern; caching/acceleration layer in distributed systems.


## Intent

Serve reads from a fast cache. On a cache miss, **the cache itself** loads the value from the authoritative data source, stores it, and returns it to the caller—so callers always read **through** the cache.

## Also Known As

-   Cache-Aside *with loader embedded in cache component*

-   Self-populating cache

-   Read-behind (sometimes used loosely; strict “read-behind” can imply async fill)


## Motivation (Forces)

-   **Latency & Throughput:** Hot keys should be retrieved in micro-/millisecond time from memory instead of hitting a slower DB or API.

-   **Load Shedding:** Offload repetitive reads from primary stores.

-   **Consistency vs. Freshness:** Data can be slightly stale (TTL/refresh).

-   **Thundering Herd:** Popular cold keys can trigger many simultaneous loads.

-   **Failure Modes:** What to return if backend is slow/down?

-   **Distribution:** Local per-process cache vs. shared distributed cache (e.g., Redis, Memcached).

-   **Cost:** Memory footprint, serialization overhead, and cache warmup.


## Applicability

Use when:

-   Most reads are **repeat reads** of a working set smaller than available cache memory.

-   You can tolerate **bounded staleness** (seconds/minutes) or support explicit invalidation.

-   You need to **hide** backend outages/latency spikes for a short time with TTLs, stale-while-revalidate, or fallbacks.


Avoid when:

-   Strong read-after-write consistency is mandatory and you cannot invalidate precisely.

-   Data is large, low locality, or mostly one-time reads (cache becomes a pass-through tax).

-   Writes are extremely frequent relative to reads.


## Structure

-   **Client** → **Read-Through Cache** → **Loader** → **Authoritative Store**

    -   Cache holds entries with **value + metadata** (TTL, write time, version, negative flag).

    -   Optional **single-flight**/request collapsing to prevent duplicate loads.

    -   Optional **stale-while-revalidate** background refresh.


## Participants

-   **Cache:** Exposes `get(key)`; owns eviction/expiry policies.

-   **Loader:** Function to obtain a value for a key from the source; called on miss/expiry.

-   **Authoritative Store:** Database, API, filesystem, etc.

-   **Invalidator (optional):** Pub/Sub listener or write path hook to evict/update keys.


## Collaboration

1.  Client calls `cache.get(k)`.

2.  If entry is present and **not expired** → return.

3.  Otherwise the cache **invokes Loader** (ensuring only one active load per key), stores the result (including “not found” as a negative cache entry if desired), then returns it.

4.  Eviction/expiry periodically removes old items.

5.  Optional: write path emits invalidation events to keep cache fresh.


## Consequences

**Benefits**

-   Big latency reduction and backend offload.

-   Simple calling code (cache abstracts loading).

-   Can gracefully handle short backend blips with TTL/stale-on-error.


**Liabilities**

-   Potential staleness; requires invalidation or short TTLs.

-   Memory pressure; need sizing & eviction (LRU/LFU/Window-TinyLFU).

-   Cache stampedes if single-flight isn’t implemented.

-   Distributed caches add network hops and serialization costs.

-   Negative caching can mask new data for TTL duration if misused.


## Implementation (Key Points)

-   **Expiry:** TTL (time-to-live) and/or TTI (idle). Consider jitter to avoid synchronized expiry.

-   **Eviction:** LRU/LFU/size-based caps; guard against unbounded maps.

-   **Stampede Control:** Per-key **single-flight** via `CompletableFuture` or striped locks; optionally **request coalescing** and **bounded concurrency**.

-   **Negative Caching:** Represent “not found” distinctly, with shorter TTL.

-   **Stale-While-Revalidate:** Serve slightly stale data and refresh asynchronously.

-   **Metrics & Tracing:** hit rate, load time, evictions, error rate; tag by key prefix.

-   **Consistency:** For strong needs, integrate **write-through** or **write-behind** plus **invalidation events** (e.g., Kafka/Redis pubsub).

-   **Topology:**

    -   *Local cache* (in-process): lowest latency, per-instance memory, potential duplication.

    -   *Remote cache* (Redis/Memcached): shared, larger, needs network; keep client-side microcache for extra speed.


---

## Sample Code (Java 17): Minimal Read-Through Cache with TTL, Single-Flight, Negative Caching

> Educational, dependency-free. For production, prefer a proven cache (Caffeine/Redis) and add metrics.

```java
import java.time.Clock;
import java.time.Duration;
import java.util.Objects;
import java.util.Optional;
import java.util.concurrent.*;
import java.util.function.Function;

public class ReadThroughCache<K, V> {

    public interface Loader<K, V> {
        Optional<V> load(K key) throws Exception; // empty = "not found"
    }

    private static final Object NULL_SENTINEL = new Object();

    static final class Entry<V> {
        final Object valueOrNull;        // V or NULL_SENTINEL
        final long expiresAtNanos;
        Entry(Object valueOrNull, long expiresAtNanos) {
            this.valueOrNull = valueOrNull;
            this.expiresAtNanos = expiresAtNanos;
        }
        boolean isExpired(long nowNanos) { return nowNanos >= expiresAtNanos; }
        Optional<V> value() {
            if (valueOrNull == NULL_SENTINEL) return Optional.empty();
            @SuppressWarnings("unchecked") V v = (V) valueOrNull;
            return Optional.of(v);
        }
    }

    private final ConcurrentHashMap<K, Entry<V>> store = new ConcurrentHashMap<>();
    private final ConcurrentHashMap<K, CompletableFuture<Entry<V>>> inFlight = new ConcurrentHashMap<>();
    private final Loader<K, V> loader;
    private final Duration ttl;
    private final Duration negativeTtl;
    private final Clock clock;
    private final int maxSize;
    private final ConcurrentLinkedQueue<K> accessQueue = new ConcurrentLinkedQueue<>();

    public ReadThroughCache(Loader<K, V> loader,
                            Duration ttl,
                            Duration negativeTtl,
                            int maxSize) {
        this(loader, ttl, negativeTtl, maxSize, Clock.systemUTC());
    }

    public ReadThroughCache(Loader<K, V> loader,
                            Duration ttl,
                            Duration negativeTtl,
                            int maxSize,
                            Clock clock) {
        this.loader = Objects.requireNonNull(loader);
        this.ttl = ttl == null ? Duration.ofSeconds(60) : ttl;
        this.negativeTtl = negativeTtl == null ? Duration.ofSeconds(5) : negativeTtl;
        this.maxSize = Math.max(16, maxSize);
        this.clock = clock;
    }

    /** Read-through get: returns cached or loads once per key on miss/expiry. */
    public Optional<V> get(K key) {
        long now = System.nanoTime();
        Entry<V> e = store.get(key);
        if (e != null && !e.isExpired(now)) {
            touch(key);
            return e.value();
        }
        return loadSingleFlight(key).join().value();
    }

    /** Manually invalidate a key (e.g., after a write). */
    public void invalidate(K key) {
        store.remove(key);
    }

    /** Clear all entries. */
    public void clear() {
        store.clear();
    }

    private CompletableFuture<Entry<V>> loadSingleFlight(K key) {
        // Coalesce concurrent loads for the same key.
        CompletableFuture<Entry<V>> f = inFlight.computeIfAbsent(key, k ->
            CompletableFuture.supplyAsync(() -> {
                try {
                    Optional<V> loaded = loader.load(k);
                    Entry<V> entry = toEntry(loaded);
                    // publish to cache
                    putAndEvictIfNeeded(k, entry);
                    return entry;
                } catch (Throwable t) {
                    // Soft failure strategy: if stale exists, serve it; else propagate error.
                    Entry<V> stale = store.get(k);
                    if (stale != null) return stale; // may be expired, caller accepts staleness
                    throw new CompletionException(t);
                } finally {
                    inFlight.remove(k);
                }
            })
        );
        return f;
    }

    private Entry<V> toEntry(Optional<V> val) {
        long now = System.nanoTime();
        long ttlNanos = val.isPresent() ? jitter(ttl).toNanos() : jitter(negativeTtl).toNanos();
        Object payload = val.isPresent() ? val.get() : NULL_SENTINEL;
        return new Entry<>(payload, now + ttlNanos);
    }

    private void putAndEvictIfNeeded(K key, Entry<V> entry) {
        store.put(key, entry);
        touch(key);
        // Simple size cap with FIFO-ish trimming (demo); replace with real LRU/LFU for prod.
        while (store.size() > maxSize) {
            K victim = accessQueue.poll();
            if (victim == null) break;
            store.remove(victim);
        }
    }

    private void touch(K key) { accessQueue.offer(key); }

    private static Duration jitter(Duration d) {
        // ±10% jitter to avoid synchronized expiry
        double base = d.toMillis();
        double factor = 0.9 + ThreadLocalRandom.current().nextDouble() * 0.2;
        return Duration.ofMillis((long) (base * factor));
    }

    // --- Demo main ---
    public static void main(String[] args) {
        // Simulated backend (sleep + absent for odd keys)
        Loader<Integer, String> backend = k -> {
            sleep(50);
            if (k % 5 == 0) return Optional.empty();          // negative cache
            return Optional.of("value:" + k + "@" + System.currentTimeMillis());
        };

        ReadThroughCache<Integer, String> cache =
                new ReadThroughCache<>(backend, Duration.ofSeconds(2), Duration.ofMillis(500), 10);

        // Warm & demonstrate single-flight: many threads reading the same key
        ExecutorService es = Executors.newFixedThreadPool(8);
        for (int i = 0; i < 16; i++) {
            int key = 42;
            es.submit(() -> System.out.println(Thread.currentThread().getName() + " -> " + cache.get(key)));
        }
        sleep(3000);
        // After TTL, next read triggers reload
        System.out.println("After TTL reload -> " + cache.get(42));
        es.shutdown();
    }

    private static void sleep(long ms) { try { Thread.sleep(ms); } catch (InterruptedException ignored) {} }
}
```

### Notes on the example

-   **Single-flight**: `inFlight` map ensures only one concurrent load per key; others await the same `CompletableFuture`.

-   **Negative caching**: `Optional.empty()` is stored with a shorter TTL to avoid hammering the backend.

-   **Jittered TTL**: reduces herd effects at expiry boundaries.

-   **Eviction**: demo uses a simple size cap; swap for a real policy in production.


---

## Known Uses

-   **CDNs & KV stores:** Redis/Memcached in front of DBs; edge caches in front of origin services.

-   **Search & Catalogs:** Product detail/price caches with short TTL + invalidate on price change.

-   **Profile & Permission reads:** User/session/profile objects cached with event-based invalidation.

-   **API Aggregators:** Backend-for-frontend (BFF) services with per-route in-process caches.


## Related Patterns

-   **Cache-Aside (Lazy Load):** Caller fetches from cache; on miss the caller loads the store and puts into cache. Read-through moves that logic into the cache.

-   **Write-Through / Write-Behind:** Ensure cache coherence on writes.

-   **Stale-While-Revalidate:** Serve stale data briefly while refreshing in background.

-   **Circuit Breaker & Bulkhead:** Protect the loader from overload; bound in-flight loads.

-   **Rate Limiter / Token Bucket:** Guard the backend when cache misses spike.

-   **Content-Based Invalidation / Event-Driven Invalidation:** Pub/Sub or CDC to evict/update keys.

-   **Two-Tier Caching:** Local in-process cache in front of a remote distributed cache.


---

## Production Tips (quick)

-   Prefer **Caffeine** for local caches (W-TinyLFU, async refresh, per-entry TTL).

-   For **distributed caching**, use Redis with a client that supports **per-key locking** (e.g., Redisson) to implement single-flight across nodes.

-   Instrument **hit ratio**, **load latency**, **expired vs. evicted counts**, and **error rates**.

-   Keep TTLs short unless you have reliable invalidation; combine with **event-based** cache busting where possible.
