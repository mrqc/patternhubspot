# Distributed Cache — Scalability Pattern

## Pattern Name and Classification

**Name:** Distributed Cache  
**Classification:** Scalability / Performance / Data Access (Shared, network-accessible cache tier)

---

## Intent

Provide a **shared, horizontally scalable, low-latency** key–value store to **offload hot reads** from primary data stores/services and **reduce end-to-end latency** across multiple application instances and services.

---

## Also Known As

-   Remote Cache / Network Cache
    
-   Cache Cluster / In-Memory Data Grid
    
-   IMDG (e.g., Hazelcast, Ignite)
    
-   Data Cache Tier (e.g., Redis, Memcached)
    

---

## Motivation (Forces)

-   **Read amplification:** many more reads than writes on hot entities.
    
-   **Multi-instance apps:** local in-process caches don’t share state and miss frequently after deployments/scale-out.
    
-   **Latency & cost:** memory-resident KV is orders faster/cheaper per read than OLTP/remote APIs.
    
-   **Operational realities:** cache must withstand node failures, scale elastically, and remain consistent enough for the use-case.
    
-   **Coherence vs simplicity:** stronger coherence (invalidation, pub/sub) adds complexity; looser consistency increases staleness risk.
    

---

## Applicability

Use a Distributed Cache when:

-   The **working set fits** (or mostly fits) in memory across the cluster.
    
-   Multiple app instances must **share** cached results.
    
-   **Bounded staleness** is acceptable (TTL or explicit invalidation).
    
-   You need **cross-service** caching (e.g., API response cache).
    

Avoid or adapt when:

-   **Strict linearizable reads** are required everywhere (prefer read-through to primary or synchronous invalidations with strong guarantees).
    
-   Payloads are **huge** or **write-heavy** (consider partial caching, compression, or a different pattern).
    
-   Data is **highly personalized** with low reuse (edge/local caches might be better).
    

---

## Structure

-   **Clients:** app nodes using cache get/set/del APIs.
    
-   **Cache Cluster:** Redis/Memcached/Hazelcast/Ignite; provides partitioning, replication, eviction.
    
-   **Keyspace & Serialization:** versioned keys, compact binary (Kryo/Smile/Proto).
    
-   **Policies:** TTL, eviction (LRU/LFU), size/entry limits, compression.
    
-   **Coherence Mechanisms:** pub/sub invalidation, key tagging, version tokens, near-cache.
    
-   **Operational Plane:** sharding, failover, monitoring, backup.
    

---

## Participants

-   **Application Layer / Repository:** orchestrates reads/writes & invalidation.
    
-   **Distributed Cache:** authoritative for *cached* copies only.
    
-   **Source of Truth:** DB/service holding durable state.
    
-   **Invalidation Bus:** pub/sub channel to fan out cache clears.
    
-   **Metrics/Alerting:** hit rate, evictions, latency, memory, misses, stampedes.
    

---

## Collaboration

1.  **Read path:** client `GET k` → hit? return; **miss** → load from source → `SET k` with TTL → return.
    
2.  **Write path:** mutating op → commit to source → publish **invalidation** for keys/tags → optionally write-back refreshed value.
    
3.  **Eviction/TTL:** cluster evicts; next read repopulates.
    
4.  **Coherence:** subscribers drop local/near entries on invalidation events.
    

---

## Consequences

**Benefits**

-   Significant **latency** reduction and **DB offload**.
    
-   **Shared** across many app instances; warm once, benefit everywhere.
    
-   **Elastic**: scale nodes/partitions independently of app.
    

**Liabilities**

-   **Stale data** without precise invalidation.
    
-   **Cache stampedes** on popular keys after expiry.
    
-   Additional **moving parts** (network hops, cluster health).
    
-   **Cold start** after deploys or cache flush.
    

---

## Implementation

### Key Decisions

-   **Technology & topology:** Redis (clustered, replica-backed), Memcached (simple, slab-based), or IMDG (Hazelcast/Ignite with compute & near-cache).
    
-   **Key design:** `prefix:entity:id:v{schema}` (+ tenant/locale). Bump version on format changes.
    
-   **TTL & jitter:** avoid coordinated expiry (±20% randomization).
    
-   **Stampede protection:** single-flight locks, request coalescing, **SWR** (stale-while-revalidate).
    
-   **Invalidation:**
    
    -   **Write-invalidate:** publish key/tag; subscribers evict.
        
    -   **Write-back:** update cache after commit (reduces stale window, increases write path cost).
        
-   **Consistency level:** accept eventual consistency; for strict flows, read from source or conditional reads with **version tokens/ETags**.
    
-   **Compression:** for large values; balance CPU vs bandwidth.
    
-   **Observability:** track hit/miss/evict, P95 get/set latency, memory, key cardinality.
    

### Anti-Patterns

-   **Cache-then-DB write** (wrong order) → phantom values.
    
-   No **jitter** → thundering herd at TTL boundary.
    
-   Storing **unbounded** blobs → eviction storms and OOM risk.
    
-   Treating cache as **source of truth**.
    
-   **Cross-region** cache round-trips for every call (use region-local caches; async fill).
    

---

## Sample Code (Java, Redis + Redisson)

*Distributed cache with: cache-aside reads, stampede protection via per-key locks, TTL+jitter, pub/sub invalidation, and optional stale-while-revalidate.*

```java
// build.gradle (snip)
// implementation 'org.redisson:redisson:3.27.2'
// implementation 'com.fasterxml.jackson.core:jackson-databind:2.17.1'

package com.example.distcache;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.redisson.api.*;
import org.redisson.config.Config;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Optional;
import java.util.concurrent.ThreadLocalRandom;

public class DistributedCache<K,V> {

  private static final String INVALIDATE_CHANNEL = "cache:invalidate";
  private final RedissonClient redisson;
  private final ObjectMapper om = new ObjectMapper();
  private final String namespace;
  private final Duration baseTtl;
  private final Duration staleGrace; // SWR window

  public DistributedCache(String redisUrl, String namespace, Duration baseTtl, Duration staleGrace) {
    Config cfg = new Config();
    cfg.useSingleServer().setAddress(redisUrl); // swap to cluster() for Redis Cluster
    this.redisson = Redisson.create(cfg);
    this.namespace = namespace.endsWith(":") ? namespace : namespace + ":";
    this.baseTtl = baseTtl;
    this.staleGrace = staleGrace;

    // Subscribe to invalidations (key or tag)
    redisson.getTopic(INVALIDATE_CHANNEL).addListener(String.class, (ch, msg) -> {
      RBucket<byte[]> b = redisson.getBucket(msg);
      b.delete();
    });
  }

  /** Get using cache-aside with stampede protection and SWR. */
  public Optional<V> get(String key, Class<V> type, Loader<V> loader) {
    String k = ns(key);
    CacheRecord<V> rec = read(k, type);
    if (rec != null && !rec.expired()) return Optional.of(rec.value);

    if (rec != null && rec.withinGrace(staleGrace)) {
      // Serve stale and refresh asynchronously
      refreshAsync(k, type, loader);
      return Optional.of(rec.value);
    }

    String lockKey = k + ":lock";
    RLock lock = redisson.getLock(lockKey);
    boolean acquired = false;
    try {
      acquired = lock.tryLock(); // best-effort single-flight
      if (!acquired) {
        // Another thread is loading; brief wait-and-check
        sleep(30);
        CacheRecord<V> again = read(k, type);
        if (again != null && !again.expired()) return Optional.of(again.value);
      }
      // Load from source
      Optional<V> loaded = loader.load();
      if (loaded.isPresent()) {
        write(k, loaded.get());
      } else {
        delete(k); // avoid stale leftovers
      }
      return loaded;
    } finally {
      if (acquired && lock.isHeldByCurrentThread()) lock.unlock();
    }
  }

  /** Invalidate specific key and optionally publish to other nodes. */
  public void invalidate(String key) {
    String k = ns(key);
    delete(k);
    redisson.getTopic(INVALIDATE_CHANNEL).publish(k);
  }

  /** Optional: write-back to reduce stale windows after writes. */
  public void put(String key, V value) {
    write(ns(key), value);
  }

  // -------- internals --------

  private String ns(String key) { return namespace + key; }

  private void write(String key, V value) {
    try {
      long ttlMs = jitter(baseTtl).toMillis();
      byte[] wire = om.writeValueAsBytes(new Wire<>(System.currentTimeMillis(), ttlMs, value));
      redisson.getBucket(key).set(wire, ttlMs, java.util.concurrent.TimeUnit.MILLISECONDS);
    } catch (Exception e) {
      // log and continue
    }
  }

  private CacheRecord<V> read(String key, Class<V> type) {
    try {
      byte[] raw = redisson.getBucket(key).get();
      if (raw == null) return null;
      Wire<V> w = om.readValue(raw, om.getTypeFactory().constructParametricType(Wire.class, type));
      long age = System.currentTimeMillis() - w.cachedAtMs;
      boolean expired = age >= w.ttlMs;
      long remaining = Math.max(0, w.ttlMs - age);
      return new CacheRecord<>(w.value, expired, remaining);
    } catch (Exception e) {
      return null;
    }
  }

  private void delete(String key) {
    redisson.getBucket(key).delete();
  }

  private void refreshAsync(String key, Class<V> type, Loader<V> loader) {
    redisson.getExecutorService().execute(() -> {
      String lockKey = key + ":lock";
      RLock lock = redisson.getLock(lockKey);
      if (lock.tryLock()) {
        try {
          loader.load().ifPresent(v -> write(key, v));
        } finally {
          if (lock.isHeldByCurrentThread()) lock.unlock();
        }
      }
    });
  }

  private static Duration jitter(Duration base) {
    long ms = base.toMillis();
    long jitter = ThreadLocalRandom.current().nextLong(ms / 5 + 1); // ±20%
    return Duration.ofMillis(Math.max(1000, ms + (ThreadLocalRandom.current().nextBoolean() ? jitter : -jitter)));
  }

  private static void sleep(long ms) { try { Thread.sleep(ms); } catch (InterruptedException ignored) { Thread.currentThread().interrupt(); } }

  // wire + types
  public interface Loader<V> { Optional<V> load(); }
  private record Wire<V>(long cachedAtMs, long ttlMs, V value) {}
  private record CacheRecord<V>(V value, boolean expired, long remainingMs) {
    boolean withinGrace(Duration g) { return expired && remainingMs + g.toMillis() > 0; }
  }
}
```

**Usage (cache-aside around a repository):**

```java
// ProductCacheRepository.java
package com.example.distcache;

import java.time.Duration;
import java.util.Optional;

public class ProductCacheRepository {

  private final DistributedCache<Long, Product> cache;
  private final ProductRepository db;

  public ProductCacheRepository(ProductRepository db) {
    this.db = db;
    this.cache = new DistributedCache<>("redis://localhost:6379",
        "product:v1", Duration.ofMinutes(10), Duration.ofSeconds(3));
  }

  public Optional<Product> findById(long id) {
    return cache.get(String.valueOf(id), Product.class, () -> db.selectById(id));
  }

  public void upsert(Product p) {
    db.upsert(p);                    // 1) write source of truth
    cache.invalidate(String.valueOf(p.id()));  // 2) invalidate (or cache.put(...) for write-back)
  }

  public void delete(long id) {
    db.delete(id);
    cache.invalidate(String.valueOf(id));
  }

  public record Product(long id, String name, long priceCents) {}
}
```

---

## Known Uses

-   **Redis** / **Memcached** clusters as shared caches for web/API tiers.
    
-   **Hazelcast / Apache Ignite** IMDG with **near-cache** + **backup** for low-latency distributed maps.
    
-   **CDN edge + regional caches** layered with a shared mid-tier cache.
    
-   **Feature flag / configuration** caches fanned out via pub/sub invalidation.
    

---

## Related Patterns

-   **Cache Aside**: the most common client-managed interaction with a distributed cache.
    
-   **Read-Through / Write-Through / Write-Behind**: alternative integration styles.
    
-   **Stale-While-Revalidate** & **Request Coalescing**: mitigate stampedes.
    
-   **Database Replication**: complements caches for broader read scaling.
    
-   **CQRS / Read Models**: denormalized stores reduce cache pressure.
    
-   **Bloom Filter / Negative Cache**: stop penetration on non-existent keys.
    

---

## Implementation Checklist

-   Choose **store & topology** (clustered Redis, replicas, persistence needs).
    
-   Design **keys**, **namespaces**, **TTL + jitter**, **max value size**, **serialization**.
    
-   Implement **cache-aside** with **stampede protection** and **SWR** where useful.
    
-   Define **invalidation strategy** (events, tags) tied to write paths and deployments.
    
-   Enforce **limits**: memory, entry TTL, eviction policy; monitor evictions.
    
-   Add **metrics** & **alerts** (hit rate, get/set P95, errors, memory, pub/sub lag).
    
-   Plan **failure modes**: cache down (graceful fallback), partial partitions, warm-up tooling.
    
-   Security & compliance: **auth/TLS**, PII **redaction** or avoid caching sensitive data.

