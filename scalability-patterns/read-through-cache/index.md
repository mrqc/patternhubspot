# Read-Through Cache — Scalability Pattern

## Pattern Name and Classification

**Name:** Read-Through Cache  
**Classification:** Scalability / Performance / Data Access (Inline cache with automatic population)

---

## Intent

Place a cache **in front of** the data source so that **reads go to the cache first**; on a miss, the cache **loads and stores** the data from the backing store **transparently**, then returns it. This reduces latency and offloads the primary store **without changing callers**.

---

## Also Known As

-   Read-Through
    
-   Inline Loading Cache
    
-   Auto-Populating Cache
    

---

## Motivation (Forces)

-   **Hot reads dominate** many systems; repeatedly hitting the database/service is costly.
    
-   **Developers want simplicity:** callers should just “get(key)” and not hand-roll cache-aside logic.
    
-   **Consistency vs. freshness:** accept **bounded staleness** (TTL/refresh) for speed.
    
-   **Stampede risk:** popular keys can cause thundering herds on miss; the cache loader can centralize protection.
    

---

## Applicability

Use Read-Through when:

-   You control the **cache layer** (library or proxy) and want **transparent** population for clients.
    
-   The **working set fits** (or mostly fits) in memory of the cache tier.
    
-   **Bounded staleness** is acceptable; you can define TTL/refresh semantics.
    
-   You need to **standardize** loading, serialization, negative caching, and metrics in one place.
    

Avoid or adapt when:

-   You need **strong read-after-write** for all reads (consider write-through/invalidate).
    
-   Data changes are **very frequent** vs reads (cache churn wastes resources).
    
-   The cache is **remote** and adds notable network hop on every read; consider near-cache or cache-aside for selective paths.
    

---

## Structure

-   **Cache Client / API:** `get(key)` returns value or triggers loader on miss.
    
-   **Loader:** authoritative load function for a key; handles serialization, errors, negative caching.
    
-   **Back-end Store:** DB, service, filesystem—the source of truth.
    
-   **Policies:** TTL, maximum size, refresh-after-write (SWR), admission/eviction, negative-cache TTL.
    
-   **Observability:** hit/miss, load latency, evictions, load failures.
    

---

## Participants

-   **Application Code:** uses the cache as if it were the store.
    
-   **Read-Through Cache:** maintains entries and knows how to load on miss.
    
-   **Data Source Adapter:** executes queries or RPCs to fetch the value on cache miss.
    
-   **Metrics/Tracing:** records cache behavior and loader performance.
    

---

## Collaboration

1.  Caller invokes `cache.get(key)`.
    
2.  **Hit?** return cached value.
    
3.  **Miss?** cache invokes **Loader** → Loader fetches from **Store**, returns value.
    
4.  Cache **stores** value (with TTL/size policy) and returns it.
    
5.  Optional **refresh-after-write** keeps hot keys fresh in the background.
    

---

## Consequences

**Benefits**

-   **Simple call sites**: no duplicate cache-aside code sprinkled across services.
    
-   **Centralized policy**: TTL, serialization, negative caching, and stampede protection in one place.
    
-   **Lower latency & DB offload** on repeated reads.
    

**Liabilities**

-   Cache becomes a **runtime dependency** on reads; if remote and down, requests may fail unless you **fail open**.
    
-   **Stale reads** within TTL or during refresh.
    
-   Poor loader/backing-store behavior can surface as **global latency spikes**.
    
-   If used blindly for **non-reusable** data, you waste memory.
    

---

## Implementation

### Key Decisions

-   **Where it lives:** in-process (Caffeine/Guava) for microsecond access, or **distributed** (Redis/Hazelcast) for sharing across nodes (often with a **near-cache**).
    
-   **TTL & refresh:** choose `expireAfterWrite` and optionally `refreshAfterWrite` for **stale-while-revalidate** behavior. Add **jitter** to avoid herd refresh.
    
-   **Negative caching:** cache “not found” briefly to avoid penetration.
    
-   **Single-flight / stampede control:** only one loader per key; others wait/serve stale.
    
-   **Serialization:** compact and deterministic (JSON/Proto/Kryo).
    
-   **Failure policy:** fail-closed vs **serve stale on loader error**, with circuit breaker/timeout budgets.
    
-   **Sizing:** maximum entries/weight; protect memory with weigher and eviction.
    

### Anti-Patterns

-   Letting the loader perform **unbounded** calls (no timeouts/backoff).
    
-   No **size limits** → memory pressure and GC issues.
    
-   Refreshing all keys **in sync** (no jitter) → stampede on every TTL boundary.
    
-   Treating the cache as **authoritative** (it’s not).
    
-   Using read-through for **write-heavy** entities with little reuse.
    

---

## Sample Code (Java — Caffeine Read-Through with SWR, Negative Cache, and Single-Flight)

> Dependencies:
> 
> -   `com.github.ben-manes.caffeine:caffeine:3.1.8`
>     
> -   (optional) Spring JDBC or your data client for the backing store
>     

The example shows:

-   In-process read-through with **Caffeine** `AsyncLoadingCache`.
    
-   **expireAfterWrite** + **refreshAfterWrite** (SWR).
    
-   **Negative caching** for missing rows.
    
-   **Single-flight** loads (built-in) and **serve stale on loader failure**.
    

```java
// build.gradle (snip)
// implementation 'com.github.ben-manes.caffeine:caffeine:3.1.8'
// implementation 'org.springframework.boot:spring-boot-starter-jdbc' // or your store client
// runtimeOnly 'org.postgresql:postgresql'

package com.example.readthrough;

import com.github.benmanes.caffeine.cache.*;
import org.springframework.jdbc.core.JdbcTemplate;

import java.time.Duration;
import java.util.Optional;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executor;
import java.util.concurrent.Executors;

public class ProductReadThroughCache {

  private static final Product MISSING = new Product(-1L, "<missing>", 0L); // negative cache token

  private final AsyncLoadingCache<Long, Product> cache;
  private final JdbcTemplate jdbc;
  private final Executor loaderPool = Executors.newFixedThreadPool(8);

  public ProductReadThroughCache(JdbcTemplate jdbc) {
    this.jdbc = jdbc;
    this.cache = Caffeine.newBuilder()
        .maximumSize(100_000)                                 // size bound
        .expireAfterWrite(Duration.ofMinutes(10))             // TTL
        .refreshAfterWrite(Duration.ofMinutes(2))             // SWR: background refresh
        .ticker(Ticker.systemTicker())
        .recordStats()                                        // metrics
        .buildAsync(key -> loadFromDb(key));                  // single-flight loader
  }

  /** Public API: read-through get. Always returns Optional.empty() for missing rows. */
  public CompletableFuture<Optional<Product>> get(long id) {
    return cache.get(id).thenApply(p ->
        (p == null || p == MISSING) ? Optional.empty() : Optional.of(p));
  }

  /** Optional: explicit invalidation after writes. */
  public void invalidate(long id) {
    cache.synchronous().invalidate(id);
  }

  // --------------- internals ---------------

  private CompletableFuture<Product> loadFromDb(long id) {
    return CompletableFuture.supplyAsync(() -> {
      try {
        Product p = jdbc.query("""
            select id, name, price_cents from product where id=?
            """, rs -> rs.next()
                ? new Product(rs.getLong("id"), rs.getString("name"), rs.getLong("price_cents"))
                : MISSING, id);
        return p != null ? p : MISSING;
      } catch (Exception e) {
        // On loader error: serve stale if present by throwing—Caffeine keeps old value.
        throw new RuntimeException("DB load failed for id " + id, e);
      }
    }, loaderPool);
  }

  /** Simple DTO (replace with your model). */
  public record Product(long id, String name, long priceCents) {}
}
```

**Usage (service/controller):**

```java
// Somewhere in your service
var cache = new ProductReadThroughCache(jdbcTemplate);

// Read path: callers just ask the cache
cache.get(42L).thenAccept(opt -> {
  if (opt.isPresent()) { /* use product */ }
  else { /* 404 or fallback */ }
});

// After a write: update DB first, then invalidate to avoid serving stale
jdbcTemplate.update("update product set price_cents=? where id=?", 1999L, 42L);
cache.invalidate(42L);
```

**Notes**

-   `refreshAfterWrite` enables **stale-while-revalidate**: Caffeine serves the old value while refreshing in background.
    
-   On exceptions in the loader, Caffeine **keeps the previous value** (if any) by default—ideal for transient issues.
    
-   For **distributed** sharing (many app nodes), combine a **distributed cache** (e.g., Redis read-through via a repository wrapper) with a **near-cache** like the above for microsecond lookups.
    

---

## Known Uses

-   **Product/catalog/profile** reads with high reuse.
    
-   **Configuration/feature flags** (with short TTL & background refresh).
    
-   **Service-to-service response caching** for expensive, deterministic calls.
    
-   **Search result snippets** or **denormalized DTOs** derived from primary data.
    

---

## Related Patterns

-   **Cache Aside (Look-Aside):** Caller manages misses; more control, more call-site code.
    
-   **Write-Through / Write-Behind:** Synchronize cache on writes; different consistency/cost profiles.
    
-   **Distributed Cache / Near-Cache:** Read-through can be layered (near + remote).
    
-   **Materialized View:** Durable, queryable precomputation (coarser-grained than key/value caching).
    
-   **Stale-While-Revalidate / Request Coalescing:** Operational techniques often bundled into read-through loaders.
    

---

## Implementation Checklist

-   Choose location: **in-process** (Caffeine) vs **distributed** (Redis/Hazelcast) and consider a **near-cache**.
    
-   Define **TTL**, **refresh**, **size limits**, and add **jitter** to refresh scheduling if you roll your own.
    
-   Implement a **bounded, timeout-enforced** loader with retries/backoff; classify errors (serve stale vs fail).
    
-   Add **negative caching** TTL for “not found”.
    
-   Emit **metrics**: hit/miss ratio, load time, refresh counts, evictions; alert on **miss spikes**.
    
-   After **writes**, **invalidate or write-back** to shrink the stale window.
    
-   Guard hot keys with **single-flight** (per-key lock) if your cache library doesn’t already.
    
-   Test failure modes: cache down (fail open?), DB/backing store slow, stampedes, coordinated refreshes.

