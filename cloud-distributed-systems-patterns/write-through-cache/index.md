
# Cloud Distributed Systems Pattern — Write-Through Cache

## Pattern Name and Classification

-   **Name:** Write-Through Cache

-   **Classification:** Structural / Data-management pattern (consistency & performance). Often grouped under **caching** patterns for read/write paths.


## Intent

Execute **writes synchronously** against the **system of record** and **update the cache in the same operation** so that **reads immediately see the new value** and the cache never contains data that wasn’t first persisted.

## Also Known As

-   Synchronous Write Cache

-   Cache-on-Write

-   Store-First Cache (emphasizing write-ordering)


## Motivation (Forces)

-   **Fresh reads:** Immediately reflect successful writes on subsequent reads via cache.

-   **Simplicity of reasoning:** Cache is never “ahead” of the database (unlike write-behind).

-   **Operational safety:** If the database rejects the write, the cache is **not** updated → avoids phantom/dirty values.

-   **Trade-off:** Higher write latency (must hit the store **and** cache) and more write amplification.


## Applicability

Use write-through when you need:

-   **Strong read-after-write** visibility through the cache.

-   Straightforward failure semantics (atomic **store→cache** ordering).

-   Moderate write rates where extra cache work on writes is acceptable.

-   A simple, reliable baseline before considering more advanced patterns.


Avoid or adapt when:

-   You need **very low write latency** or must absorb spikes → consider **Write-Behind** (with WAL) or **CQRS**.

-   You can tolerate **eventual** cache updates → consider **Cache-Aside** with explicit invalidation.

-   Workloads are write-heavy and cache locality is poor (write-through may just add cost).


## Structure

-   **Client** calls `put/delete` on the cache façade.

-   **Write-Through Cache** writes to the **Store** (DB/KV) **first**; on success, it **updates/invalidates** the cache atomically.

-   **Read Path** can be **read-through** (populate on miss) or **cache-aside** (caller loads and sets).


```scss
Client ── put(k,v) ──► WriteThroughCache ──► Store (commit) ──► Cache.set(k,v)
Client ── del(k)   ──► WriteThroughCache ──► Store (delete) ──► Cache.del(k)
Client ── get(k)   ──► Cache.get(k) ──(miss)─► Store.get(k) ──► Cache.set(k, v)
```

## Participants

-   **Cache API (Facade):** `get/put/delete` with write-through semantics.

-   **Cache Store:** In-memory (local) or remote (Redis, Memcached); may support TTL.

-   **System of Record (Store):** Database / KV with transactions and versioning.

-   **Serializer/Codec (optional):** Converts values to/from cache bytes.

-   **Metrics/Logger:** Emits hit rate, write latency, failures, evictions.


## Collaboration

1.  **put(k,v):** Cache façade writes to **Store**. If **OK**, it **sets** cache (optionally with TTL).

2.  **delete(k):** Delete in **Store** first; if **OK**, **evict** cache key.

3.  **get(k):** Return cache hit; on miss, load from **Store** and **populate** cache (read-through).

4.  **Failures:** If the **Store** write fails → **do not** update cache; propagate error. If cache set fails after store success → consider retry/log; **store remains authoritative**.


## Consequences

**Benefits**

-   **Read-after-write** consistency through the cache (for the same key).

-   No “dirty cache” risk (cache never has uncommitted data).

-   Conceptually simple; easy rollback story (fail before cache update).


**Liabilities / Trade-offs**

-   **Higher write latency** (store + cache).

-   **Write amplification** (every write touches two tiers).

-   **Multi-node coherency:** Other nodes’ local caches may still be stale unless you use **shared cache**, **pub/sub invalidation**, or a **single cache tier**.

-   **Transactions:** With multi-key atomicity you may need transactions or idempotency for cache update retries.


## Implementation (Key Points)

-   **Ordering:** **Store → Cache**. Never the other way around.

-   **Atomicity:** Treat cache update as a **best-effort** side effect—store holds truth. If cache set fails, retry asynchronously or accept temporary miss penalties.

-   **TTL / Staleness:** Even with write-through, set sensible TTLs to self-heal rare incoherencies.

-   **Versioning / ETags (optional):** Include version in cache value to detect stale overwrites.

-   **Deletes:** Delete in store first, then **evict** cache (not set null); many caches treat `null` poorly.

-   **Concurrency:** Use **per-key** locks or CAS (compare-and-set) if your read-through loader must avoid dog-piles.

-   **Multi-node setups:** Prefer a **central cache** (Redis/Memcached) or broadcast invalidations (Redis Pub/Sub) so all app nodes see the update.

-   **Observability:** Track hit ratio, `p95/p99` latencies for write & read paths, and cache error rate.


---

## Sample Code (Java 17): Write-Through Cache (read-through on miss)

> Educational single-JVM example:
>
> -   `WriteThroughCache<K,V>` ensures **store-first** writes and delete-then-evict.
>
> -   Optional **TTL** on cache entries.
>
> -   Simple **read-through** population on misses.
>
> -   Pluggable `KeyValueStore` (simulated DB) and `CacheBackend` (in-JVM map).
>

```java
// File: WriteThroughCacheDemo.java
// Compile: javac WriteThroughCacheDemo.java
// Run:     java WriteThroughCacheDemo
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Function;

/* ---------- Abstractions ---------- */
interface KeyValueStore<K,V> {
    void upsert(K key, V value) throws Exception;
    void delete(K key) throws Exception;
    Optional<V> get(K key) throws Exception;
}

interface CacheBackend<K,V> {
    Optional<V> get(K key);
    void set(K key, V value, Duration ttl);
    void evict(K key);
}

/* ---------- Simple implementations ---------- */
class SimulatedStore<K,V> implements KeyValueStore<K,V> {
    private final Map<K,V> db = new ConcurrentHashMap<>();
    private final int latencyMs;
    SimulatedStore(int latencyMs) { this.latencyMs = latencyMs; }
    @Override public void upsert(K k, V v) throws Exception { Thread.sleep(latencyMs); db.put(k, v); }
    @Override public void delete(K k) throws Exception { Thread.sleep(latencyMs); db.remove(k); }
    @Override public Optional<V> get(K k) throws Exception { Thread.sleep(latencyMs); return Optional.ofNullable(db.get(k)); }
}

class LocalTtlCache<K,V> implements CacheBackend<K,V> {
    private static final class Entry<V> { final V v; final long exp; Entry(V v, long exp){this.v=v;this.exp=exp;} }
    private final ConcurrentHashMap<K, Entry<V>> map = new ConcurrentHashMap<>();
    @Override public Optional<V> get(K key) {
        Entry<V> e = map.get(key);
        if (e == null) return Optional.empty();
        if (e.exp > 0 && System.nanoTime() > e.exp) { map.remove(key, e); return Optional.empty(); }
        return Optional.of(e.v);
    }
    @Override public void set(K key, V value, Duration ttl) {
        long exp = (ttl == null || ttl.isZero() || ttl.isNegative()) ? 0 : System.nanoTime() + ttl.toNanos();
        map.put(key, new Entry<>(value, exp));
    }
    @Override public void evict(K key) { map.remove(key); }
}

/* ---------- Write-Through Cache Facade ---------- */
class WriteThroughCache<K,V> {
    private final KeyValueStore<K,V> store;
    private final CacheBackend<K,V> cache;
    private final Duration ttl;
    private final Function<K, Optional<V>> loader; // read-through, may call store

    public WriteThroughCache(KeyValueStore<K,V> store,
                             CacheBackend<K,V> cache,
                             Duration ttl,
                             Function<K, Optional<V>> loader) {
        this.store = store;
        this.cache = cache;
        this.ttl = ttl == null ? Duration.ZERO : ttl;
        this.loader = loader;
    }

    /** Read: hit cache; on miss use loader (usually store.get) and populate. */
    public Optional<V> get(K key) throws Exception {
        Optional<V> c = cache.get(key);
        if (c.isPresent()) return c;
        Optional<V> v = loader.apply(key);
        v.ifPresent(val -> cache.set(key, val, ttl));
        return v;
    }

    /** Write-through: Store first; if success, cache it. */
    public void put(K key, V value) throws Exception {
        store.upsert(key, value);        // authoritative write
        try {
            cache.set(key, value, ttl);  // make reads immediately fresh
        } catch (RuntimeException ce) {
            // Cache is best-effort; log & continue. Optionally schedule an async retry.
            System.err.println("cache.set failed for " + key + ": " + ce);
        }
    }

    /** Delete: Store first; if success, evict from cache. */
    public void delete(K key) throws Exception {
        store.delete(key);
        try {
            cache.evict(key);
        } catch (RuntimeException ce) {
            System.err.println("cache.evict failed for " + key + ": " + ce);
        }
    }
}

/* ---------- Demo ---------- */
public class WriteThroughCacheDemo {
    public static void main(String[] args) throws Exception {
        // Simulate a 40ms DB and a local in-JVM cache (TTL 5s)
        KeyValueStore<String, String> store = new SimulatedStore<>(40);
        CacheBackend<String, String> cache = new LocalTtlCache<>();

        WriteThroughCache<String,String> wtc = new WriteThroughCache<>(
                store,
                cache,
                Duration.ofSeconds(5),               // cache TTL
                key -> {                              // read-through loader
                    try { return store.get(key); } catch (Exception e) { throw new RuntimeException(e); }
                }
        );

        // 1) Write-through put
        long t0 = System.nanoTime();
        wtc.put("user:42", "Alice");
        long t1 = System.nanoTime();
        System.out.println("put latency (store+cache): " + Duration.ofNanos(t1 - t0).toMillis() + " ms");

        // 2) Read: first should be cache hit (fast)
        System.out.println("get user:42 = " + wtc.get("user:42").orElse("<none>"));

        // 3) Update and read again (fresh via cache)
        wtc.put("user:42", "Alice v2");
        System.out.println("get user:42 = " + wtc.get("user:42").orElse("<none>"));

        // 4) Delete then verify miss
        wtc.delete("user:42");
        System.out.println("after delete, get = " + wtc.get("user:42").orElse("<none>"));

        // 5) Miss path: first call loads from store (none), set a value, then hit
        System.out.println("miss get user:7 = " + wtc.get("user:7").orElse("<none>"));
        wtc.put("user:7", "Bob");
        System.out.println("hit get user:7 = " + wtc.get("user:7").orElse("<none>"));
    }
}
```

**What the example shows**

-   `put/delete` go **to the store first**; cache is updated/evicted **after** a successful store operation.

-   `get` is **read-through**: on cache miss, it consults the store and populates cache with a configurable TTL.

-   Cache errors don’t corrupt the store; at worst you suffer a temporary miss until the next load.


> Productionize with: distributed cache (Redis/Memcached), JSON/Proto serialization, retries with backoff for cache ops, per-key locks to avoid thundering herds, and cross-node invalidation (e.g., Redis Pub/Sub).

---

## Known Uses

-   **CDNs / API gateways:** Often use write-through for configuration/admin objects so control-plane writes immediately reflect in hot caches.

-   **User/session/profile stores:** When read-after-write experience is critical and writes are moderate.

-   **E-commerce catalogs / pricing snapshots:** Control writes via back office; read scale through cache with strong freshness after updates.

-   **Config/feature-flag services:** Writes propagate into cache tiers synchronously for instant effect.


## Related Patterns

-   **Write-Behind Cache:** Opposite durability ordering (cache first, async persist) to reduce write latency at the cost of temporary risk; often paired with a WAL.

-   **Cache-Aside (Lazy Loading):** Application reads/writes the store and manages cache explicitly (set/evict); simpler but can miss read-after-write through the cache.

-   **Read-Through Cache:** Complementary to write-through; loader populates cache on miss (featured in the sample).

-   **Event-Driven Invalidation:** Pub/Sub or CDC to evict or update other nodes’ caches after writes.

-   **CQRS / Materialized Views:** Offload heavy reads; write-through may refresh views synchronously.

-   **Idempotency & Versioning:** Use ETags/row versions to guard against stale overwrites when multiple writers exist.


---

### Practical Tips

-   Keep **ordering invariant**: **store → cache** for upserts, **store → evict** for deletes.

-   Use **short, non-zero TTLs** to let the system self-heal after rare cache anomalies.

-   In multi-node systems, prefer a **shared cache** (Redis) or **broadcast invalidations** so every node sees fresh data.

-   Measure: **hit ratio**, **write latency**, **error rate** (cache and store), and **eviction churn**.

-   For hot keys and high write rates, consider mixing patterns: write-through for critical keys; write-behind or queue-based pipelines for bulk updates.
