# Cache Aside — Cloud / Distributed Systems Pattern

## Pattern Name and Classification

**Cache Aside (a.k.a. Cache-Aside / Lazy Loading)** — *Cloud / Distributed Systems* **performance & scalability** pattern for **application-managed** read/write caching next to a primary data store.

---

## Intent

Keep a **hot working set** in a fast cache by letting the **application**:

1.  **read**: try cache → on miss **load from store** and **populate cache**;

2.  **write**: **update store** and **invalidate** (or update) the cache.


---

## Also Known As

-   **Lazy Loading Cache**

-   **Read-Through (app-managed)** *(not a managed/read-through cache appliance)*

-   **Cache-Aside with Write-Invalidate**


---

## Motivation (Forces)

-   Databases are costly for **read-heavy** or **hot key** workloads.

-   You want **control** over cache keys, TTLs, serialization, and invalidation.

-   Managed read-through/write-through caches may be **too opaque** or heavy.


**Tensions:** data **staleness** vs. freshness; **cache stampedes** on popular keys; **consistency** across writers; **cold start** latency.

---

## Applicability

Use Cache Aside when:

-   Reads dominate and tolerate **bounded staleness**.

-   You can tolerate **eventual** cache consistency on writes.

-   You control the app code path (can implement the pattern).


Avoid when:

-   You require strict **read-your-writes** or **serializable** semantics across nodes (consider **write-through** or **second-level caches with coherence**).

-   Data changes too frequently relative to TTL (cache churn).


---

## Structure

```scss
Client ──► Repository (app code)
             │
     get(id) │
             ├─► Cache.get(k) ── hit? ──► return
             │
             ├─ miss ─► DB.load(id) ─► Cache.put(k, value, TTL) ─► return
             │
     update  └─► DB.save(v) ─► Cache.invalidate(k)  (or Cache.put with new value)
```

---

## Participants

-   **Cache** — fast KV store (Redis, Memcached, in-memory) holding serialized values with **TTL**.

-   **Primary Store** — source of truth (SQL/NoSQL).

-   **Repository / DAO** — implements the **cache-aside discipline** (miss fill, invalidation).

-   **Stampede Guard** *(optional)* — per-key lock or **single-flight** to prevent dogpiling.


---

## Collaboration

1.  **Read path:** app checks cache → on miss, a **single** loader fetches from DB, populates cache, returns.

2.  **Write path:** app commits to DB then **invalidates** the cache (or updates it).

3.  **Eviction/TTL**: cache entries expire; next read repopulates.


---

## Consequences

**Benefits**

-   Significant **latency reduction** and **DB offload**.

-   **Explicit control** over keys, TTLs, serialization, stampede handling.

-   Works with many caches and languages.


**Liabilities**

-   **Stale reads** during TTL.

-   Requires careful **invalidation** and **coherency** discipline.

-   Risk of **stampedes** on popular keys; must add guards.

-   Extra **operational surface** (cache tuning, eviction, warmup).


---

## Implementation (Key Points)

-   Choose **key schema**: include version/tenant to avoid collisions.

-   Set **TTL** based on freshness needs; consider **jitter** to avoid herd expiry.

-   Implement **single-flight** per key (mutex/semaphore) to avoid stampedes.

-   Consider **negative caching** (cache `null` for short TTL) to cushion hot 404s.

-   On **writes**: *update DB first*, then **invalidate** cache (or update atomically if feasible).

-   For multi-node producers, consider **pub/sub invalidation** to fan out deletes.

-   Add **metrics**: hit/miss, fill time, stampede count, key hotness.

-   Serialization: JSON/Proto; keep payloads small; compress if large.

-   Pair with **Circuit Breaker/Timeouts** for cache outages (fall back to DB).


---

## Sample Code (Java 17) — Cache-Aside with TTL, Negative Caching, and Stampede Guard

> In-memory cache for clarity (replace with Redis). Shows:
>
> -   `getById`: cache → DB on miss → populate.
>
> -   **Double-checked locking** per key to avoid dogpiles.
>
> -   **Negative caching** for not-found.
>
> -   `update`: DB write then **invalidate**.
>
> -   Simple TTL with jitter and minimal metrics.
>

```java
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Supplier;

// --------- Simple TTL cache (replace with Redis/Memcached client) ---------
final class TtlCache<K, V> {
  private static final Object NULL = new Object(); // negative caching marker

  static final class Entry {
    final Object value;           // V or NULL
    final Instant expiresAt;
    Entry(Object value, Instant expiresAt) { this.value = value; this.expiresAt = expiresAt; }
    boolean expired() { return Instant.now().isAfter(expiresAt); }
  }

  private final ConcurrentHashMap<K, Entry> map = new ConcurrentHashMap<>();

  public Optional<V> get(K key) {
    Entry e = map.get(key);
    if (e == null || e.expired()) return Optional.empty();
    @SuppressWarnings("unchecked")
    V v = (V) (e.value == NULL ? null : e.value);
    return Optional.ofNullable(v);
  }

  public void put(K key, V value, Duration ttl) {
    map.put(key, new Entry(value == null ? NULL : value, Instant.now().plus(ttl)));
  }

  public void invalidate(K key) { map.remove(key); }
  public void clear() { map.clear(); }
}

// --------- Per-key single-flight to avoid stampede ---------
final class KeyMutex<K> {
  private final ConcurrentHashMap<K, Object> locks = new ConcurrentHashMap<>();
  Object lockFor(K k) { return locks.computeIfAbsent(k, kk -> new Object()); }
}

// --------- Domain & persistence (fake DB) ---------
record Product(String id, String name, int priceCents, long version) {}

interface ProductDb {
  Optional<Product> findById(String id);
  void upsert(Product p);
}

final class InMemoryProductDb implements ProductDb {
  private final ConcurrentHashMap<String, Product> db = new ConcurrentHashMap<>();
  @Override public Optional<Product> findById(String id) { return Optional.ofNullable(db.get(id)); }
  @Override public void upsert(Product p) { db.put(p.id(), p); }
}

// --------- Repository implementing Cache-Aside ---------
final class ProductRepository {
  private final ProductDb db;
  private final TtlCache<String, Product> cache;
  private final KeyMutex<String> mutex = new KeyMutex<>();
  private final Random jitter = new Random();

  // base TTLs
  private final Duration hitTtl = Duration.ofSeconds(60);
  private final Duration negativeTtl = Duration.ofSeconds(10);

  // metrics
  private final AtomicLong hits = new AtomicLong();
  private final AtomicLong misses = new AtomicLong();
  private final AtomicLong loads = new AtomicLong();
  private final AtomicLong stampedesAvoided = new AtomicLong();

  ProductRepository(ProductDb db, TtlCache<String, Product> cache) {
    this.db = db; this.cache = cache;
  }

  public Optional<Product> getById(String id) {
    String key = key(id);

    // 1) fast path: cache
    Optional<Product> cached = cache.get(key);
    if (cached.isPresent()) { hits.incrementAndGet(); return cached; }
    misses.incrementAndGet();

    // 2) single-flight per key to avoid dogpile
    synchronized (mutex.lockFor(key)) {
      // 2a) re-check after acquiring lock (double-checked)
      cached = cache.get(key);
      if (cached.isPresent()) { stampedesAvoided.incrementAndGet(); return cached; }

      // 3) load from DB
      loads.incrementAndGet();
      Optional<Product> p = db.findById(id);

      // 4) populate cache with TTL (use jitter to avoid herd expiry)
      Duration ttl = (p.isPresent() ? withJitter(hitTtl) : withJitter(negativeTtl));
      cache.put(key, p.orElse(null), ttl);
      return p;
    }
  }

  // Write path: write DB first, then invalidate cache (or set new value)
  public void upsert(Product p) {
    db.upsert(p);                 // commit source of truth
    cache.invalidate(key(p.id())); // write-invalidate
    // Optional: cache.put(key(p.id()), p, withJitter(hitTtl)); // write-update
  }

  private String key(String id) { return "product:v1:" + id; } // include version in key schema
  private Duration withJitter(Duration d) {
    long ms = d.toMillis();
    long delta = (long)(ms * (jitter.nextDouble() * 0.10 - 0.05)); // ±5%
    return Duration.ofMillis(Math.max(1000, ms + delta));
  }

  // basic metrics
  public Map<String, Long> metrics() {
    return Map.of("hits", hits.get(), "misses", misses.get(), "loads", loads.get(), "stampedesAvoided", stampedesAvoided.get());
  }
}

// --------- Demo ---------
public class CacheAsideDemo {
  public static void main(String[] args) {
    var db = new InMemoryProductDb();
    var cache = new TtlCache<String, Product>();
    var repo = new ProductRepository(db, cache);

    // Seed DB
    db.upsert(new Product("p-1", "Guitar", 129_00, 1));

    // First read -> miss -> DB -> cache
    System.out.println("1: " + repo.getById("p-1"));

    // Second read -> hit
    System.out.println("2: " + repo.getById("p-1"));

    // Not found path -> negative caching
    System.out.println("3: " + repo.getById("nope")); // miss+neg cache
    System.out.println("4: " + repo.getById("nope")); // hit (negative)

    // Update -> write DB then invalidate -> next read refills
    repo.upsert(new Product("p-1", "Guitar Pro", 149_00, 2));
    System.out.println("5: " + repo.getById("p-1")); // miss (invalidated) -> new value

    System.out.println("metrics: " + repo.metrics());
  }
}
```

**Notes on replacing the in-memory cache with Redis**

-   Use a Redis client (e.g., Lettuce/Jedis): `GET key` → hit; `SETEX key ttl value` on fill; `DEL key` on invalidate.

-   Use **per-key locks** to prevent stampede:

    -   Redis `SETNX lock:key <id> PX 2000` + `DEL` in finally, or

    -   Ratelimit with **single-flight** in-process if traffic is sticky per instance.

-   Consider **logical versioning** in keys (e.g., `product:v2:`) to invalidate classes of data on deployment.

-   For pub/sub invalidation across nodes, publish `DEL key` messages to a channel, or rely on **keyspace notifications**.


---

## Known Uses

-   **Read-heavy microservices** caching product/catalog/profile lookups next to SQL/NoSQL.

-   API gateways caching **token introspection** or **configuration**.

-   Feature flag & configuration clients with **short TTL** refresh.


---

## Related Patterns

-   **Read-Through / Write-Through** — cache appliance handles loads/writes automatically (less control).

-   **Write-Behind** — cache buffers writes to the store (higher risk/throughput).

-   **Refresh-Ahead** — proactively refresh entries before TTL expiry.

-   **Cache Invalidation with Pub/Sub** — cross-node coherence for write fan-out.

-   **Circuit Breaker / Bulkhead / Timeout** — protect cache/DB calls.

-   **Idempotency Key** — for safe re-population on retries.
