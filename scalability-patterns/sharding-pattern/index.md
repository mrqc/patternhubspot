# Sharding — Scalability Pattern

## Pattern Name and Classification

**Name:** Sharding  
**Classification:** Scalability / Data Architecture / Stateful Scale-Out (Horizontal partitioning of data and workload)

---

## Intent

Split a large dataset and its traffic across **multiple independent shards** so that **writes, reads, and storage** scale horizontally. Each shard owns a disjoint subset of the keyspace and can be scaled, maintained, and recovered **independently**.

---

## Also Known As

-   Horizontal Partitioning
    
-   Key-Based Routing
    
-   Consistent-Hashing Ring (when using hashing with virtual nodes)
    
-   Range/Hash/Directory Sharding
    

---

## Motivation (Forces)

-   **Write throughput ceilings** on a single database/cluster.
    
-   **Storage growth** beyond what one node can handle efficiently (index bloat, vacuum pressure).
    
-   **Isolation** to contain noisy tenants and reduce blast radius.
    
-   **Latency** & cache locality: keep related data together.
    
-   **Elasticity**: add shards to grow capacity without forklift upgrades.
    

Trade-offs: **cross-shard queries/transactions**, **rebalancing** complexity, **hot-key** skew, and a **routing layer** you must operate.

---

## Applicability

Use sharding when:

-   Work can be addressed with a **stable partition key** (e.g., `tenantId`, `userId`, `orderId`).
    
-   You’ve exhausted vertical scaling, replication, and caching for writes.
    
-   You can accept **eventual** or **coordinated** semantics for cross-shard workflows.
    

Avoid or adapt when:

-   Most queries are **ad-hoc cross-entity joins** without a clear key.
    
-   You need **global ACID transactions** frequently (prefer single shard per workflow, or a different storage model).
    
-   The dataset is still small enough that **replication** + **read caches** suffice.
    

---

## Structure

-   **Partitioning Function** → `key → shardId` (hash, range, directory, **consistent hash** / **jump hash**).
    
-   **Routing Layer** (client, gateway, or driver) → maps requests to shard endpoints.
    
-   **Shard Groups** → each shard has a **primary** and **replicas** for HA/reads.
    
-   **Directory/Metadata** (optional) → explicit map (tenant → shard) and migration state.
    
-   **Rebalancer** → add/remove shards, move ranges/tenants, track progress & fencing.
    
-   **Global Services** → schema manager, backup/restore, observability per shard.
    

---

## Participants

-   **Client / Service** → emits operations with a partition key.
    
-   **Router** → chooses target shard deterministically.
    
-   **Shard Storage** → database or table set for that shard (plus replicas).
    
-   **Coordinator** → manages shard map changes & migrations.
    
-   **Observability** → per-shard metrics, hot-key detection, backlog.
    

---

## Collaboration

1.  Client identifies **partition key**.
    
2.  Router computes **shardId** (or looks it up in the directory).
    
3.  Request goes to the shard’s **primary** (writes) or **replica** (reads, policy-dependent).
    
4.  Rebalancing moves a subset (range/tenants) to a new shard; directory or ring is updated; traffic follows.
    

---

## Consequences

**Benefits**

-   **Writes & storage** scale with number of shards.
    
-   **Fault isolation**: issues stay within a shard.
    
-   **Operational agility**: per-shard maintenance, rolling schema changes.
    

**Liabilities**

-   **Cross-shard joins/transactions** are hard (fan-out, 2PC, sagas).
    
-   **Skew / hot keys** can overload one shard.
    
-   **Rebalancing** is non-trivial (data copy, dual-writes, fencing, cutover).
    
-   More **moving parts**: router, directory, migrations, per-shard backups.
    

---

## Implementation

### Key Decisions

-   **Strategy**
    
    -   **Hash sharding** (good default): uniform distribution; poor for range scans.
        
    -   **Range sharding** (time/ID): good for time-series; beware “latest range” hotspot.
        
    -   **Directory sharding**: flexible tenant→shard mapping; central metadata.
        
    -   **Consistent/Jump hashing**: minimal key movement on resizing, fewer metadata updates.
        
-   **Key Choice**: high-cardinality, stable, evenly distributed; use **salts** for known hot keys.
    
-   **Routing Location**: client-side library (no extra hop), gateway/proxy, or driver-native.
    
-   **Cross-shard semantics**: prefer **sagas/outbox** over 2PC; design APIs around shard-local operations.
    
-   **Rebalancing plan**: virtual nodes (vnodes) vs. explicit tenant moves; **dual-read/dual-write** window; cutover with **fencing tokens**.
    
-   **Observability**: per-shard p95/p99, QPS, errors, queue depths, **skew dashboards**.
    
-   **Backups/DR**: shard-scoped snapshots and restore drills.
    

### Anti-Patterns

-   Picking a **skewed key** (country, timestamp) without mitigation.
    
-   “Global” unique constraints spanning shards (implement **application-level** uniqueness).
    
-   Ad-hoc fan-out queries on hot paths.
    
-   Rebalancing without **idempotency** or fencing → duplicates/loss.
    
-   Baking `shardId` into business IDs too early (blocks future moves).
    

---

## Sample Code (Java)

Below you’ll find a practical **consistent-hash router with virtual nodes**, a **sharded JDBC repository**, and a small **migration helper** for tenant moves. Replace JDBC with your driver of choice.

### A) Consistent-Hash Router (virtual nodes)

*TreeMap ring; each physical shard contributes many vnodes → smooth distribution; add/remove shards with minimal key movement.*

```java
// build.gradle (snip)
// implementation 'org.springframework.boot:spring-boot-starter-jdbc'
// runtimeOnly 'org.postgresql:postgresql'

package com.example.sharding;

import javax.sql.DataSource;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Function;

public final class ConsistentHashRouter<T> {

  private final SortedMap<Long, T> ring = new TreeMap<>();
  private final Map<T, Integer> vnodeCounts = new ConcurrentHashMap<>();
  private final Function<byte[], Long> hashFn;

  public ConsistentHashRouter(Function<byte[], Long> hashFn) {
    this.hashFn = hashFn != null ? hashFn : ConsistentHashRouter::murmur64;
  }

  /** Add a physical node with N virtual nodes. */
  public synchronized void addNode(T node, int vnodes) {
    vnodeCounts.put(node, vnodes);
    for (int i = 0; i < vnodes; i++) {
      long h = hashFn.apply((node.toString() + "#" + i).getBytes(StandardCharsets.UTF_8));
      ring.put(h, node);
    }
  }

  /** Remove a physical node from the ring. */
  public synchronized void removeNode(T node) {
    Integer v = vnodeCounts.remove(node);
    if (v == null) return;
    for (int i = 0; i < v; i++) {
      long h = hashFn.apply((node.toString() + "#" + i).getBytes(StandardCharsets.UTF_8));
      ring.remove(h);
    }
  }

  /** Resolve node for a key. */
  public T routeForKey(String key) {
    if (ring.isEmpty()) throw new IllegalStateException("empty ring");
    long kh = hashFn.apply(key.getBytes(StandardCharsets.UTF_8));
    SortedMap<Long, T> tail = ring.tailMap(kh);
    Long nodeHash = tail.isEmpty() ? ring.firstKey() : tail.firstKey();
    return ring.get(nodeHash);
  }

  // Simple 64-bit hash (replace with Murmur3_128/FarmHash for production)
  public static long murmur64(byte[] data) {
    try {
      MessageDigest md = MessageDigest.getInstance("SHA-256");
      byte[] d = md.digest(data);
      return ByteBuffer.wrap(Arrays.copyOf(d, 8)).getLong();
    } catch (Exception e) { throw new RuntimeException(e); }
  }
}
```

### B) Sharded Repository (tenant-scoped operations)

```java
package com.example.sharding;

import org.springframework.jdbc.core.JdbcTemplate;

import javax.sql.DataSource;
import java.util.*;

public class ShardSet {
  private final Map<String, DataSource> shardMap; // name -> DS
  private final ConsistentHashRouter<String> router;

  public ShardSet(Map<String, DataSource> shardMap, int vnodes) {
    this.shardMap = Map.copyOf(shardMap);
    this.router = new ConsistentHashRouter<>(null);
    shardMap.keySet().forEach(name -> router.addNode(name, vnodes));
  }

  public JdbcTemplate forKey(String key) {
    String shardName = router.routeForKey(key);
    return new JdbcTemplate(shardMap.get(shardName));
  }

  public Set<String> shards() { return shardMap.keySet(); }

  // for rebalancing ops
  public ConsistentHashRouter<String> router() { return router; }
}

class CustomerRepository {
  private final ShardSet shards;
  public CustomerRepository(ShardSet shards) { this.shards = shards; }

  /** Shard by tenantId; all tenant data lives on one shard. */
  public void createCustomer(String tenantId, String customerId, String name) {
    JdbcTemplate jdbc = shards.forKey(tenantId);
    jdbc.update("""
      insert into customer(tenant_id, customer_id, name, created_at)
      values (?,?,?, now())
    """, tenantId, customerId, name);
  }

  public Optional<Map<String,Object>> getCustomer(String tenantId, String customerId) {
    JdbcTemplate jdbc = shards.forKey(tenantId);
    List<Map<String,Object>> rows = jdbc.queryForList("""
      select tenant_id, customer_id, name, created_at
      from customer where tenant_id=? and customer_id=?
    """, tenantId, customerId);
    return rows.isEmpty() ? Optional.empty() : Optional.of(rows.get(0));
  }
}
```

### C) Hot-Key Mitigation (salting) & Coalesced Reads (optional)

```java
package com.example.sharding;

import java.util.concurrent.*;

public final class HotKeyMitigation {
  private final int saltSpace;
  private final ConcurrentHashMap<String, CompletableFuture<?>> inflight = new ConcurrentHashMap<>();
  public HotKeyMitigation(int saltSpace) { this.saltSpace = Math.max(1, saltSpace); }

  public String salt(String baseKey) {
    int s = ThreadLocalRandom.current().nextInt(saltSpace);
    return baseKey + "|s" + s;
  }

  @SuppressWarnings("unchecked")
  public <T> CompletableFuture<T> singleFlight(String key, Callable<T> loader) {
    return (CompletableFuture<T>) inflight.computeIfAbsent(key, k ->
      CompletableFuture.supplyAsync(() -> {
        try { return loader.call(); }
        catch (Exception e) { throw new CompletionException(e); }
      }).whenComplete((r, t) -> inflight.remove(k)));
  }
}
```

### D) Simple Tenant Move (directory override)

*When you must rebalance a single tenant, you can override routing temporarily and copy data with fencing. (Sketch)*

```java
package com.example.sharding;

import org.springframework.jdbc.core.JdbcTemplate;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

public class DirectoryRouter {
  private final ShardSet shards;
  private final Map<String, String> tenantToShard = new ConcurrentHashMap<>(); // overrides

  public DirectoryRouter(ShardSet shards) { this.shards = shards; }

  public JdbcTemplate forTenant(String tenantId) {
    String override = tenantToShard.get(tenantId);
    if (override != null) return new JdbcTemplate(((Map<String, javax.sql.DataSource>)shards.getClass()
        .getDeclaredFields()[0]).get(tenantId)); // illustrative; wire cleanly in real code
    return shards.forKey(tenantId);
  }

  /** Migration sketch (pseudo-atomic with fencing in real impl). */
  public void moveTenant(String tenantId, String destShardName) {
    tenantToShard.put(tenantId, destShardName); // pin new writes to destination
    // 1) copy historical data from old shard to dest (bulk copy by tenant_id)
    // 2) dual-read or validate counts/checksums
    // 3) cut over reads; remove from old; keep old read-only for a window
  }
}
```

*Notes*

-   In production, maintain a **proper directory table** (tenant → shard, version, fenced epoch).
    
-   A safe move uses **copy → dual-write (or write-redirect) → cutover → decommission** with idempotent operations and **epochs** to prevent split brain.
    

---

## Known Uses

-   **SaaS multi-tenant** apps sharded by `tenantId`.
    
-   **Social/gaming** by `userId` for timelines, inventories, friends.
    
-   **Time-series** by time range (monthly/day buckets) or device id.
    
-   **Search/NoSQL** engines (Elasticsearch, Cassandra) with hash/range shards and rebalancing.
    
-   **Kafka** partitions (conceptual sharding) for scalable streams & consumers.
    

---

## Related Patterns

-   **Partitioning** (umbrella concept) — sharding is its database-oriented form.
    
-   **Database Replication** — read scale within each shard.
    
-   **Consistent Hashing** — concrete routing mechanism for hash sharding.
    
-   **CQRS / Materialized Views** — avoid cross-shard joins by projecting read models.
    
-   **Queue-Based Load Leveling** — pair with sharded consumers (one group per partition).
    
-   **Idempotent Receiver / Saga / Outbox** — safe cross-shard workflows and retries.
    
-   **Multi-Region Deployment** — geo-shard tenants or ranges per region.
    

---

## Implementation Checklist

-   Pick a **partition key** and validate its **distribution** on real data (simulate).
    
-   Choose **hash/range/directory** and a **routing** approach (client, proxy, driver).
    
-   Plan **rebalancing**: vnodes or directory moves; implement **fencing/epochs** and **idempotent** copy.
    
-   Define **cross-shard** rules: avoid hot-path joins; use **sagas/outbox** for workflows.
    
-   Mitigate **hot keys**: salting, per-tenant rate limits, cache, or split heavy tenants.
    
-   Build **per-shard** dashboards & alerts; monitor **skew** and **p99**.
    
-   Automate **schema** and **backup/restore** per shard; run **restore drills**.
    
-   Document **consistency expectations** (e.g., read-your-writes scope) and **routing invariants** for all teams.

