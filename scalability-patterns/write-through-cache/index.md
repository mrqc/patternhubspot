# Write-Through Cache — Scalability Pattern

## Pattern Name and Classification

**Name:** Write-Through Cache  
**Classification:** Scalability / Performance / Data Access (Synchronous cache + store writes)

---

## Intent

Guarantee **durable writes** while keeping the cache **authoritative for reads** by writing **through** the cache: a write **only succeeds when both the cache and the backing store** are updated (atomically from the caller’s perspective). Reads consult the cache first; on miss, the cache loads and stores from the source of truth.

---

## Also Known As

-   Synchronous Write-Back
    
-   Inline Write-Through
    
-   Read/Write-Through Cache (when read-through is also enabled)
    

---

## Motivation (Forces)

-   **Freshness on reads:** callers should see the latest value in cache immediately after a write.
    
-   **Correctness:** unlike write-behind, the application must not acknowledge a write unless it’s **persisted** to the database.
    
-   **Simplicity for callers:** one API for read + write that handles cache population and invalidation.
    
-   **Operational clarity:** centralized place for TTLs, serialization, stampede protection, and negative caching.
    

**Trade-off:** higher write latency than write-behind (two systems in the critical path) and tighter coupling between cache and store availability.

---

## Applicability

Use write-through when:

-   You require **strong write durability** at acknowledgment time.
    
-   **Read-after-write** consistency via the cache is important for most clients.
    
-   The domain tolerates the extra write latency (cache + store round-trips).
    

Avoid or adapt when:

-   You need the **lowest possible write latency** and can accept eventual persistence → consider **write-behind**.
    
-   Readers outside the cache require **strict cross-system ordering** (use DB reads or version tokens).
    
-   Cache or store **availability** is intermittent (write-through makes writes depend on both).
    

---

## Structure

-   **Write-Through Cache Service**: public API `get/put/delete`.
    
-   **Loader**: on cache miss, fetches from store and populates cache (read-through).
    
-   **Backing Store Adapter**: transactional DB/service operations.
    
-   **Serializer/Key Builder**: deterministic encoding and namespacing (`type:id:v{n}`).
    
-   **Policies**: TTL + jitter, negative cache TTL, size limits, stampede protection.
    
-   **Observability**: hit/miss, load & write latency, error classes, stampede/lock metrics.
    

---

## Participants

-   **Caller / Repository**: uses the cache service instead of talking to DB directly.
    
-   **Cache**: Redis/Memcached/Hazelcast; may also implement local near-cache.
    
-   **Store**: RDBMS/NoSQL/service (source of truth).
    
-   **Transaction/Unit of Work**: ensures store commit and cache update occur in the correct order.
    
-   **Metrics/Tracing**: visibility across both paths.
    

---

## Collaboration

1.  **Read path**: `get(k)` → cache hit? return; else loader queries store, **sets cache**, returns.
    
2.  **Write path**: `put(k,v)` → **write to store** (commit) → **update cache** (same value & version) → return success.
    
3.  **Delete path**: delete in store → **evict** cache keys (and negative-cache the miss briefly).
    
4.  **Failures**: on store failure → no write acknowledged; on cache failure after store commit → treat as partial failure and **retry** cache set (or evict to force next read-through).
    

---

## Consequences

**Benefits**

-   **Strong durability at write time**; cache and store are aligned immediately after success.
    
-   **Fresh reads** from cache with **read-after-write** consistency for cache users.
    
-   Centralized **policy** and **stampede control** reduce duplicated logic.
    

**Liabilities**

-   **Higher write latency** (cache + store).
    
-   **Availability coupling**: write requires both subsystems (unless you design fallback).
    
-   Need careful **ordering** to avoid exposing uncommitted values in cache.
    

---

## Implementation

### Key Decisions

-   **Ordering:** To avoid exposing uncommitted data, do **Store → Cache** (not Cache → Store). If your cache is the “actor,” it still should **write the store first**, then populate.
    
-   **Atomicity semantics:** From the caller’s perspective, write succeeds iff both operations succeed. If store succeeds but cache set fails, either **retry** the set or **evict** to force read-through later.
    
-   **TTL + jitter:** avoid synchronized expirations (thundering herd).
    
-   **Versioning:** store and propagate a **version/ETag** in the cache value; helps detect stale updates.
    
-   **Negative caching:** cache “miss” results briefly to avoid penetration.
    
-   **Stampede protection:** single-flight per key; stale-while-revalidate for hot keys.
    
-   **Fallback strategy:** if cache is down on write, **don’t fail the user** if the store committed—**evict later** or enqueue an async repair, but document that cache may be cold.
    

### Anti-Patterns

-   Writing cache **before** DB commit (readers can see data that never committed).
    
-   No retry/evict on cache set failure after store commit → long miss storms.
    
-   Unbounded cache entries or **no TTL** on volatile datasets.
    
-   Treating cache as **source of truth** (it isn’t).
    

---

## Sample Code (Java, Spring JDBC + Redis/Lettuce)

**Features**

-   Read-through on misses.
    
-   Write-through: **DB commit first, then cache set** (idempotent), with retry & fallback eviction.
    
-   Negative caching for “not found”.
    
-   TTL with jitter, per-key single-flight using `ConcurrentHashMap` futures.
    

> Dependencies (snip):  
> `org.springframework.boot:spring-boot-starter-jdbc`  
> `io.lettuce:lettuce-core:6.3.2.RELEASE`  
> `org.postgresql:postgresql`

```java
package com.example.writethrough;

import io.lettuce.core.api.sync.RedisCommands;
import io.lettuce.core.RedisClient;
import io.lettuce.core.api.StatefulRedisConnection;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Transactional;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Optional;
import java.util.concurrent.*;

public class ProductWriteThroughRepository {

  private static final String KEY_PREFIX = "product:v1:";
  private static final String NEG_PREFIX = "product:neg:";
  private static final Duration TTL = Duration.ofMinutes(10);
  private static final Duration NEG_TTL = Duration.ofSeconds(30);

  private final JdbcTemplate jdbc;
  private final RedisCommands<String, String> redis;
  private final ConcurrentHashMap<Long, CompletableFuture<Optional<Product>>> singleFlight = new ConcurrentHashMap<>();

  public ProductWriteThroughRepository(JdbcTemplate jdbc, String redisUrl) {
    this.jdbc = jdbc;
    RedisClient client = RedisClient.create(redisUrl);
    StatefulRedisConnection<String, String> conn = client.connect();
    this.redis = conn.sync();
  }

  /* ------------------- READ-THROUGH ------------------- */

  public Optional<Product> get(long id) {
    String key = KEY_PREFIX + id;

    // Cache hit?
    String json = redis.get(key);
    if (json != null) return Optional.of(JsonSerde.fromJson(json));

    // Negative cache?
    if (Boolean.TRUE.equals(redis.exists(NEG_PREFIX + id) > 0)) return Optional.empty();

    // Single-flight: coalesce parallel loads
    CompletableFuture<Optional<Product>> fut = singleFlight.computeIfAbsent(id, k ->
      CompletableFuture.supplyAsync(() -> loadAndCache(id))
          .whenComplete((r, t) -> singleFlight.remove(k))
    );

    try { return fut.get(800, TimeUnit.MILLISECONDS); }
    catch (Exception e) { throw new RuntimeException("read-through load failed", e); }
  }

  private Optional<Product> loadAndCache(long id) {
    Optional<Product> fromDb = jdbc.query("""
        select id, name, price_cents, version from product where id = ?
      """,
      rs -> rs.next()
        ? Optional.of(new Product(rs.getLong("id"), rs.getString("name"),
                                  rs.getLong("price_cents"), rs.getInt("version")))
        : Optional.empty(), id);

    if (fromDb.isPresent()) {
      setCache(fromDb.get()); // best-effort
      redis.del(NEG_PREFIX + id);
    } else {
      redis.setex(NEG_PREFIX + id, (int) NEG_TTL.toSeconds(), "1");
      redis.del(KEY_PREFIX + id);
    }
    return fromDb;
  }

  /* ------------------- WRITE-THROUGH ------------------- */

  /**
   * Upsert with write-through semantics:
   * 1) Persist to DB (transactional).
   * 2) If DB succeeds, update cache to the same value (retry a few times).
   * From caller's perspective, success requires step (1); cache repair is retried/evicted.
   */
  @Transactional
  public void upsert(Product p) {
    // 1) DB write (source of truth)
    jdbc.update("""
      insert into product(id, name, price_cents, version)
      values (?, ?, ?, ?)
      on conflict (id) do update set
        name=excluded.name,
        price_cents=excluded.price_cents,
        version=product.version + 1
      """, p.id(), p.name(), p.priceCents(), p.version());

    // Refresh version if DB increments it (optional: reload version)
    Integer ver = jdbc.queryForObject("select version from product where id=?", Integer.class, p.id());
    Product persisted = new Product(p.id(), p.name(), p.priceCents(), ver == null ? p.version() : ver);

    // 2) Cache set (same value), with small retry then fallback evict
    if (!setCacheWithRetry(persisted, 3)) {
      // Fallback: evict & negative cache cleared; next read will read-through
      redis.del(KEY_PREFIX + persisted.id());
    }
    redis.del(NEG_PREFIX + persisted.id());
  }

  /** Delete with write-through semantics: delete store then evict cache. */
  @Transactional
  public void delete(long id) {
    jdbc.update("delete from product where id = ?", id);
    redis.del(KEY_PREFIX + id);
    redis.setex(NEG_PREFIX + id, (int) NEG_TTL.toSeconds(), "1");
  }

  /* ------------------- cache helpers ------------------- */

  private boolean setCacheWithRetry(Product p, int attempts) {
    for (int i = 0; i < attempts; i++) {
      try { setCache(p); return true; }
      catch (Exception e) { sleep(jitter(i)); }
    }
    return false;
  }

  private void setCache(Product p) {
    String key = KEY_PREFIX + p.id();
    String json = JsonSerde.toJson(p);
    int ttl = (int) (TTL.toSeconds() + ThreadLocalRandom.current().nextInt(0, 60)); // +jitter
    redis.setex(key, ttl, json);
  }

  private static void sleep(long ms) { try { Thread.sleep(ms); } catch (InterruptedException ie) { Thread.currentThread().interrupt(); } }
  private static long jitter(int attempt) {
    long base = (long) (100 * Math.pow(2, Math.min(4, attempt)));
    return ThreadLocalRandom.current().nextLong(0, base + 1);
  }

  /* ------------------- model & serde ------------------- */

  public record Product(long id, String name, long priceCents, int version) {}

  static final class JsonSerde {
    // Minimal JSON (replace with Jackson/Gson)
    static String toJson(Product p) {
      return "{\"id\":" + p.id() + ",\"name\":\"" + esc(p.name()) + "\"," +
             "\"price_cents\":" + p.priceCents() + ",\"version\":" + p.version() + "}";
    }
    static Product fromJson(String s) {
      // naive parse for brevity; use a real library in production
      var parts = s.replaceAll("[\\{\\}\"]","").split(",");
      long id=0, price=0; int ver=0; String name="";
      for (String part : parts) {
        var kv = part.split(":",2);
        switch (kv[0]) {
          case "id" -> id = Long.parseLong(kv[1]);
          case "name" -> name = kv[1];
          case "price_cents" -> price = Long.parseLong(kv[1]);
          case "version" -> ver = Integer.parseInt(kv[1]);
        }
      }
      return new Product(id,name,price,ver);
    }
    private static String esc(String s){ return s.replace("\"","\\\""); }
  }
}
```

**Notes on the sample**

-   **Store → Cache** ordering prevents exposing uncommitted values.
    
-   If the **cache set fails** after a successful DB write, we **evict** so the next reader will read-through; a background “repair” job can also be added.
    
-   **Negative caching** avoids DB hits for absent IDs.
    
-   `version` enables clients to detect stale writes (e.g., optimistic concurrency).
    

---

## Known Uses

-   Product/profile data where **fresh reads** are critical and writes must be **durable at ack**.
    
-   Feature/configuration stores served primarily from cache but **authoritatively persisted**.
    
-   Payment or order states where clients must immediately read back the just-written state via cache.
    

---

## Related Patterns

-   **Write-Behind Cache:** lower write latency via async persistence; trades durability at ack.
    
-   **Read-Through / Cache-Aside:** complementary read strategies; cache-aside gives more caller control.
    
-   **Database Replication:** combine with replicas to offload read misses.
    
-   **Materialized View / CQRS Read Models:** denormalized stores that further reduce read pressure.
    
-   **Idempotent Receiver / Retry with Backoff:** required for safe retries in the write path.
    

---

## Implementation Checklist

-   Enforce **Store → Cache** ordering (and define fallback on cache failure).
    
-   Decide **TTL + jitter**, **negative cache TTL**, and **serialization** format.
    
-   Add **single-flight** and **SWR** for hot keys; protect against stampedes.
    
-   Carry **version/ETag** end-to-end; support optimistic concurrency if needed.
    
-   Instrument **hit/miss**, **get/set/DB latency**, **retry counts**, and **error classes**; alert on miss spikes.
    
-   Document **consistency expectations**: cache gives read-after-write for participants using it; external DB readers may see different timing.
    
-   Load test write latency under partial failures (cache down, DB slow); confirm fallback behavior and error surfaces.

