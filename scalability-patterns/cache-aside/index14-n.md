# Cache Aside — Scalability Pattern

## Pattern Name and Classification

**Name:** Cache Aside (a.k.a. Lazy Loading Cache)  
**Classification:** Scalability / Performance / Data Access (Client-managed caching)

---

## Intent

Reduce latency and database load by **reading from a cache first** and, on miss, **loading from the source of truth**, **storing** the result in the cache, and then **returning** it. Writes update the database and **invalidate/refresh** the cache.

---

## Also Known As

-   Lazy Cache / Read-Through (client-implemented)
    
-   Cache-As-Sovereign’s **“aside”** (opposed to *cache-through* where the cache sits inline)
    
-   Look-aside Cache
    

---

## Motivation (Forces)

-   **Hot reads** dominate cost; most entities are read many times between writes.
    
-   **Datastores** (SQL/NoSQL) are durable but slower/expensive; in-memory caches (Redis/Memcached) are fast but volatile.
    
-   **Consistency vs freshness:** Many read paths can tolerate **eventual consistency** if staleness is bounded.
    
-   **Operational control:** Teams want explicit, application-level control over keys, TTLs, serialization, and invalidation.
    

---

## Applicability

Use Cache Aside when:

-   Read traffic has **temporal locality** (working set fits in cache).
    
-   You control the application layer and can implement cache policy explicitly.
    
-   Occasional **stale reads** are acceptable (bounded by TTL or versioning).
    
-   The source of truth is external (DB, service) and relatively slower/expensive.
    

Avoid or adapt when:

-   **Strong read-after-write** consistency is mandatory for all clients.
    
-   Data changes are **very frequent** compared to reads (cache churn > benefit).
    
-   You need transparent caching across many services (consider **read-through** proxies instead).
    

---

## Structure

-   **Cache Client:** get/set/del with TTL and optional tags.
    
-   **Key Builder:** stable, versioned keys (`prefix:entity:id:v{schema}`) and optional **tenant** dimension.
    
-   **Read Path (miss flow):** cache → DB → populate cache → return.
    
-   **Write Path:** DB write → **invalidate** (or **write-back** refresh) cache keys.
    
-   **Policies:** TTL + **jitter**, negative caching, stampede protection, stale-while-revalidate, max object size.
    

---

## Participants

-   **Application/Repository:** Implements cache-aside logic.
    
-   **Cache Store:** Redis/Memcached (fast, volatile).
    
-   **Data Store:** RDBMS/NoSQL (durable, slower).
    
-   **Serializer:** JSON/Kryo/Proto for object <-> bytes.
    
-   **Metrics/Tracer:** Hit/miss ratio, load time, stampede events.
    

---

## Collaboration

1.  **Read:** `get(key)` → **cache hit?** return; else **load from DB**, **set TTL**, return.
    
2.  **Write:** update DB → **delete/refresh** relevant keys → (optionally) publish an **invalidation event**.
    
3.  **Eviction/TTL:** cache evicts or TTL expires → next read repopulates.
    
4.  **Hot keys:** apply **single-flight** (mutex) or **request coalescing** to stop dogpiles under misses.
    

---

## Consequences

**Benefits**

-   Large **latency** and **cost** reduction for hot data.
    
-   Fine-grained control over caching policy; no black-box layer.
    
-   Straightforward to reason about; easy to roll out per-entity.
    

**Liabilities**

-   **Dual-write complexity:** DB + cache invalidation must be correct.
    
-   **Stale reads** possible between DB write and cache refresh.
    
-   **Cache stampede** on popular keys after TTL/eviction.
    
-   **Cold-start** misses until warmed.
    

---

## Implementation

### Key Decisions

-   **Key design:** include type + id + optional version (`user:123:v2`). Changing schema? **bump version** to avoid mixed formats.
    
-   **TTL & jitter:** `ttl = base ± rand(0..jitter)` to avoid synchronized expiry (thundering herd).
    
-   **Negative caching:** cache *“not found”* briefly to prevent penetration on non-existent ids.
    
-   **Stampede protection:**
    
    -   **Mutex/Single-flight**: only one loader populates; others wait or serve stale.
        
    -   **Stale-While-Revalidate (SWR):** serve expired value briefly while a background refresh runs.
        
-   **Write policy:**
    
    -   **Invalidate (delete) after DB commit** (simple, brief stale window on concurrent readers).
        
    -   **Write-back (set) after DB commit** (fewer stale reads, more write path cost).
        
-   **Serialization:** compact and deterministic; guard against payload bloat.
    
-   **Observability:** expose hit rate, miss latency, stampede count, object sizes.
    

### Anti-Patterns

-   **Set then DB write** (wrong order) → readers may observe a value that never committed.
    
-   **No jitter** on TTL → mass expires → load spike.
    
-   **Cache on write-only paths** (wasteful churn).
    
-   **Global “clear all”** on every write → defeats the cache.
    
-   Assuming cache is **authoritative** (it isn’t).
    

---

## Sample Code (Java, Redis + Postgres, Cache-Aside with SWR & Stampede Protection)

> Dependencies: Jedis (or Lettuce), Jackson, JDBC template (or JPA). Code shows: read with cache-first, negative caching, TTL + jitter, single-flight loader, SWR, and write-invalidate.

```java
// build.gradle (snip)
// implementation 'redis.clients:jedis:5.1.2'
// implementation 'com.fasterxml.jackson.core:jackson-databind:2.17.1'
// implementation 'org.postgresql:postgresql:42.7.4'
// implementation 'org.springframework:spring-jdbc:6.1.6'
```

```java
package com.example.cacheaside;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import redis.clients.jedis.JedisPooled;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.concurrent.*;
import java.util.function.Supplier;

/** Generic cache-aside repository for Product entities. */
public class ProductRepository {

  private static final String KEY_PREFIX = "product:v2:";      // bump vN on format change
  private static final String NEG_PREFIX = "product:neg:";     // negative cache
  private static final Duration BASE_TTL = Duration.ofMinutes(10);
  private static final Duration NEG_TTL = Duration.ofSeconds(30);
  private static final Duration STALE_GRACE = Duration.ofSeconds(3); // SWR window

  private final JedisPooled redis;
  private final JdbcTemplate jdbc;
  private final ObjectMapper om = new ObjectMapper();

  // Single-flight map to prevent stampede per key (coarse but effective)
  private final ConcurrentHashMap<String, CompletableFuture<Optional<Product>>> loaders = new ConcurrentHashMap<>();

  public ProductRepository(JedisPooled redis, JdbcTemplate jdbc) {
    this.redis = redis;
    this.jdbc = jdbc;
  }

  /** Read with cache-aside + negative caching + single-flight + stale-while-revalidate. */
  public Optional<Product> getById(long id) {
    String key = KEY_PREFIX + id;

    // 1) Check fresh (or within grace) cached value
    CacheEntry cached = getCacheEntry(key);
    if (cached != null) {
      if (!cached.isExpired()) {
        return Optional.of(cached.value);
      }
      // Expired but within grace? serve stale and trigger background refresh
      if (cached.isWithinGrace(STALE_GRACE)) {
        refreshAsync(key, id);
        return Optional.of(cached.value);
      }
      // fully expired -> fall through to single-flight load
    }

    // 2) Negative cache (avoid DB hits for non-existing ids)
    if (redis.exists(NEG_PREFIX + id)) return Optional.empty();

    // 3) Single-flight loader prevents thundering herd
    CompletableFuture<Optional<Product>> future = loaders.computeIfAbsent(key, k ->
        CompletableFuture.supplyAsync(() -> loadAndPopulate(id, key))
            .whenComplete((r, t) -> loaders.remove(k))
    );

    try {
      return future.get(800, TimeUnit.MILLISECONDS); // bound waiting; callers still have their own timeouts
    } catch (TimeoutException te) {
      // Too slow -> optional: serve stale if available
      if (cached != null) return Optional.of(cached.value);
      throw new RuntimeException("db load timeout", te);
    } catch (ExecutionException | InterruptedException e) {
      Thread.currentThread().interrupt();
      throw new RuntimeException("db load failed", e);
    }
  }

  /** DB write then cache invalidate (or refresh). */
  public void upsert(Product p) {
    Objects.requireNonNull(p);
    // 1) write DB (source of truth)
    int updated = jdbc.update("""
      insert into product (id, name, price_cents, version)
      values (?, ?, ?, ?)
      on conflict (id) do update
        set name=excluded.name, price_cents=excluded.price_cents, version=product.version+1
      """, p.id(), p.name(), p.priceCents(), p.version());

    if (updated <= 0) throw new RuntimeException("upsert failed");

    // 2) invalidate or write-back cache atomically *after* successful commit
    String key = KEY_PREFIX + p.id();
    redis.del(key);
    redis.del(NEG_PREFIX + p.id()); // clear negative if existed
    // Optional write-back to reduce staleness:
    setCacheEntry(key, p, randomTtl(BASE_TTL));
  }

  /** Delete entity and invalidate caches (with negative cache). */
  public void delete(long id) {
    jdbc.update("delete from product where id = ?", id);
    redis.del(KEY_PREFIX + id);
    redis.setEx(NEG_PREFIX + id, NEG_TTL.toSeconds(), "1");
  }

  // -------------------- internals --------------------

  private Optional<Product> loadAndPopulate(long id, String key) {
    Optional<Product> fromDb = jdbc.query("""
        select id, name, price_cents, version from product where id = ?
        """,
        rs -> rs.next()
            ? Optional.of(new Product(
              rs.getLong("id"),
              rs.getString("name"),
              rs.getLong("price_cents"),
              rs.getInt("version")))
            : Optional.empty(),
        id);

    if (fromDb.isPresent()) {
      setCacheEntry(key, fromDb.get(), randomTtl(BASE_TTL));
      redis.del(NEG_PREFIX + id);
    } else {
      redis.setEx(NEG_PREFIX + id, NEG_TTL.toSeconds(), "1");
      redis.del(key);
    }
    return fromDb;
  }

  private void refreshAsync(String key, long id) {
    loaders.computeIfAbsent(key, k ->
        CompletableFuture.supplyAsync(() -> loadAndPopulate(id, key))
            .whenComplete((r, t) -> loaders.remove(k)));
  }

  private void setCacheEntry(String key, Product p, Duration ttl) {
    try {
      byte[] data = om.writeValueAsBytes(new Wire(p, System.currentTimeMillis(), ttl.toMillis()));
      redis.setEx(key.getBytes(StandardCharsets.UTF_8), ttl.toSeconds(), data);
    } catch (Exception e) { /* log & continue */ }
  }

  private CacheEntry getCacheEntry(String key) {
    try {
      byte[] raw = redis.get(key.getBytes(StandardCharsets.UTF_8));
      if (raw == null) return null;
      Wire w = om.readValue(raw, Wire.class);
      Product p = new Product(w.id, w.name, w.priceCents, w.version);
      long ageMs = System.currentTimeMillis() - w.cachedAtMs;
      boolean expired = ageMs >= w.ttlMs;
      return new CacheEntry(p, expired, Math.max(0, w.ttlMs - ageMs));
    } catch (Exception e) { return null; }
  }

  private static Duration randomTtl(Duration base) {
    long jitter = ThreadLocalRandom.current().nextLong(base.toMillis() / 5 + 1); // ±20%
    long sign = ThreadLocalRandom.current().nextBoolean() ? 1 : -1;
    long ms = Math.max(1000, base.toMillis() + sign * jitter);
    return Duration.ofMillis(ms);
  }

  // POJOs / wire
  public record Product(long id, String name, long priceCents, int version) {}
  private record Wire(long id, String name, long priceCents, int version, long cachedAtMs, long ttlMs) {
    Wire(Product p, long cachedAtMs, long ttlMs) { this(p.id(), p.name(), p.priceCents(), p.version(), cachedAtMs, ttlMs); }
  }
  private record CacheEntry(Product value, boolean expired, long remainingMs) {
    boolean isExpired() { return expired; }
    boolean isWithinGrace(Duration grace) { return expired && remainingMs + grace.toMillis() > 0; }
  }
}
```

**Notes**

-   **Order matters on writes:** *DB → invalidate (or write-back)*; never set cache before DB commit.
    
-   **SWR** lets you serve a slightly stale value while refreshing asynchronously, smoothing spikes.
    
-   Scale out? For global stampede protection, move single-flight to **Redis locks** or use a small **distributed mutex** (e.g., Redisson with a short lease).
    

---

## Known Uses

-   **Web product catalogs**, **user profiles**, **feature flags**: heavy read, light write.
    
-   **Pricing/availability** snapshots with bounded staleness.
    
-   **Service response caching** at the edge or per-service to offload downstreams.
    

---

## Related Patterns

-   **Read-Through / Write-Through:** Cache/provider handles loading/writing; less app control, more transparency.
    
-   **Write-Behind (Write-Back):** Buffer writes and asynchronously update the DB; higher freshness risk but fast writes.
    
-   **Materialized View / CQRS Read Models:** Precomputed, cache-like stores for query speed.
    
-   **Request Coalescing / Single-Flight:** Stampede protection, often paired with Cache Aside.
    
-   **Bloom Filter / Negative Cache:** Prevents cache penetration for non-existent keys.
    
-   **TTL + Jitter / Stale-While-Revalidate:** Operational policies to avoid herds and smooth expirations.
    

---

## Implementation Checklist

-   Define **keys**, **TTL (+ jitter)**, and **serialization**; version your keys/schema.
    
-   Implement **read path** (hit → return; miss → load → set → return).
    
-   Implement **write path** (DB commit → invalidate or refresh) and **delete path** (DB delete → invalidate + negative cache).
    
-   Add **stampede protection** (single-flight, mutex, SWR) and **negative caching**.
    
-   Instrument **hit/miss**, **load latency**, **object size**, **error rate**; alert on dramatic hit-rate drops.
    
-   Validate under **load** (warmup, coordinated TTL expiry) and **failure** (cache down, DB slow).
    
-   Document **consistency expectations** (stale window) and **fallback** if cache is unavailable.

