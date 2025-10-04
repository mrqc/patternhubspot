# Partitioning — Scalability Pattern

## Pattern Name and Classification

**Name:** Partitioning (a.k.a. Sharding)  
**Classification:** Scalability / Data Architecture / Throughput & Storage Scale-Out (Stateful Tier)

---

## Intent

Split a large dataset or workload into **independent partitions (shards)** so that **reads, writes, and storage** are distributed across multiple nodes. Each partition is small enough to fit capacity/SLOs, and operations are routed by a **partitioning key**.

---

## Also Known As

-   Sharding
    
-   Horizontal Partitioning
    
-   Keyed Routing / Consistent Hashing
    
-   Range/Hash/Directory Partitioning
    

---

## Motivation (Forces)

-   **Write bottlenecks**: a single database/node can’t keep up with write IOPS.
    
-   **Storage growth**: one volume/table can’t store everything comfortably.
    
-   **Hotspots**: skewed tenants/keys dominate resources.
    
-   **Latency & locality**: keep related data and compute close together.
    
-   **Change tolerance**: need to add capacity without disruptive rearchitecture.
    

Trade-offs include **cross-shard queries/transactions** and **operational complexity** (rebalancing, routing, backups per shard).

---

## Applicability

Use Partitioning when:

-   Traffic or data volume **exceeds** a single node’s limits.
    
-   Access patterns can be **keyed** (e.g., by `tenantId`, `userId`, `orderId`).
    
-   You can tolerate **eventual** or **coordinated** semantics for cross-partition workflows.
    
-   You want independent **failure domains** and **rolling maintenance** per shard.
    

Avoid or adapt when:

-   You require **global transactions** across most entities (hard with sharding).
    
-   Queries are primarily **ad-hoc cross-entity joins** without a clear key.
    
-   Dataset is small enough that replication/read replicas solve the problem.
    

---

## Structure

-   **Partitioning Function**: maps a key → `shardId` (hash, range, directory, consistent hash, jump hash).
    
-   **Routing Layer**: converts requests into the correct shard target (DB/queue/cache).
    
-   **Shard Nodes**: each holds a subset of data; often replicated for HA.
    
-   **Metadata/Directory (optional)**: central map of ranges or tenant→shard assignments.
    
-   **Rebalancer**: adds/removes shards and migrates keys with minimal movement.
    
-   **Coordinator**: applies schema changes, backups, and deployments per shard.
    

---

## Participants

-   **Client/App**: issues operations with a **partition key**.
    
-   **Router/Client Library**: computes `shardId` and selects a **DataSource/endpoint**.
    
-   **Shard Storage**: database instances or tables for that shard.
    
-   **Replicas**: read scale and HA within a shard.
    
-   **Control Plane**: manages shard map, migrations, and monitoring.
    

---

## Collaboration

1.  App identifies the **partition key** for the operation.
    
2.  Router uses the **partitioning function** to compute the target shard.
    
3.  Operation executes on the shard’s primary/replica (writes on primary, reads as policy).
    
4.  Rebalancer can **move** a range/tenant to another shard; directory/metadata is updated; traffic follows.
    

---

## Consequences

**Benefits**

-   **Write throughput** scales with number of shards.
    
-   **Storage** scales horizontally; smaller indexes per shard.
    
-   **Isolation**: noisy tenants can be isolated; blast radius reduced.
    
-   **Locality**: cache/warm indexes per shard; lower tail latency.
    

**Liabilities**

-   **Cross-shard queries/transactions** are complex (fan-out, 2PC, saga).
    
-   **Rebalancing** must be planned to avoid hotspots and downtime.
    
-   **Hot keys** defeat even hashing; require additional tactics.
    
-   **Operational overhead**: backups, schema migrations, and monitoring per shard.
    

---

## Implementation

### Key Decisions

-   **Partitioning Strategy**
    
    -   **Hash** (great default): uniform distribution; poor for range scans.
        
    -   **Range** (by time/id): good for time-series and archival; watch hotspots.
        
    -   **Directory / Lookup**: flexible tenant→shard mapping; central state to manage.
        
    -   **Consistent/Jump Hash**: minimal key movement on resize, simple client-side.
        
-   **Key Choice**: stable, high-cardinality, evenly distributed (consider salting for skew).
    
-   **Routing Location**: in app (client-side), in a gateway/proxy, or via service discovery.
    
-   **Rebalancing**: planned expansions (N→N+k shards), virtual nodes (vnodes), or tenant moves.
    
-   **Secondary Indexes**: keep indexes shard-local; for global queries use search/MV.
    
-   **Cross-Shard Ops**: prefer **sagas**, **outbox**, or **idempotent** workflows over 2PC.
    
-   **Observability**: per-shard dashboards (QPS, p95, errors, lag), hot-key detection.
    

### Anti-Patterns

-   Picking a **skewed key** (e.g., country or creation date) → hotspots.
    
-   Global **auto-increment IDs** as key for hash sharding → acceptable, but range queries suffer; for range shards they overload newest shard.
    
-   **Ad-hoc cross-shard joins** on hot paths.
    
-   Rebalancing without **fencing** or dual-writes → lost/duplicated data.
    
-   Embedding shard id into the **business** identifier too early (limits future moves).
    

---

## Sample Code (Java)

Below:  
**A)** Jump Consistent Hash partitioner and JDBC routing to N shards.  
**B)** Hot-key mitigation via **salting** and **request coalescing** for read-heavy keys.

### A) Jump Consistent Hash + Sharded Repository (Spring/JDBC)

```java
// build.gradle (snip)
// implementation 'org.springframework.boot:spring-boot-starter-jdbc'
// runtimeOnly 'org.postgresql:postgresql'

package com.example.partitioning;

import org.springframework.jdbc.core.JdbcTemplate;

import javax.sql.DataSource;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

public final class JumpHash {

  /** Jump Consistent Hash: minimal key movement when shard count changes. */
  public static int shardFor(long key, int numShards) {
    long b = -1, j = 0;
    while (j < numShards) {
      b = j;
      key = key * 2862933555777941757L + 1;
      j = (long) ((b + 1) * (1L << 31) / (double) ((key >>> 33) + 1));
    }
    return (int) b;
  }

  public static int shardFor(String key, int numShards) {
    return shardFor(murmur64(key.getBytes(StandardCharsets.UTF_8)), numShards);
  }

  private static long murmur64(byte[] data) {
    // Very small 64-bit hash; replace with real Murmur3_128 if needed
    long h = 1125899906842597L; // prime
    for (byte b : data) h = 31*h + b;
    return h;
  }
}

class ShardRouter {
  private final List<JdbcTemplate> shards; // index = shardId
  private final Map<UUID, Integer> tenantOverride = new ConcurrentHashMap<>(); // optional directory

  ShardRouter(List<DataSource> ds) {
    this.shards = ds.stream().map(JdbcTemplate::new).toList();
  }

  /** Optional directory mapping for specific tenants (moves/rebalances). */
  public void assignTenant(UUID tenantId, int shardId) {
    tenantOverride.put(tenantId, shardId);
  }

  public JdbcTemplate forTenant(UUID tenantId) {
    Integer forced = tenantOverride.get(tenantId);
    if (forced != null) return shards.get(forced);
    int sid = JumpHash.shardFor(tenantId.getMostSignificantBits() ^ tenantId.getLeastSignificantBits(), shards.size());
    return shards.get(sid);
  }

  public JdbcTemplate forKey(String key) {
    int sid = JumpHash.shardFor(key, shards.size());
    return shards.get(sid);
  }

  public int shardCount() { return shards.size(); }
}

/** Example domain repository sharded by tenantId. */
class OrderRepository {
  private final ShardRouter router;

  public OrderRepository(ShardRouter router) { this.router = router; }

  public void createOrder(UUID tenantId, UUID orderId, long amountCents) {
    var jdbc = router.forTenant(tenantId);
    jdbc.update("insert into orders (tenant_id, order_id, amount_cents, created_at) values (?,?,?, now())",
        tenantId, orderId, amountCents);
  }

  public Map<String,Object> getOrder(UUID tenantId, UUID orderId) {
    var jdbc = router.forTenant(tenantId);
    return jdbc.queryForMap("select tenant_id, order_id, amount_cents, created_at from orders where order_id=?",
        orderId);
  }
}
```

**Notes**

-   **Jump Consistent Hash** minimizes remapped keys when `numShards` changes.
    
-   Add a small **directory** (optional) for targeted tenant moves or skewed tenants.
    

---

### B) Hot-Key Mitigation: Salting & Read Coalescing

```java
package com.example.partitioning;

import java.util.Optional;
import java.util.concurrent.*;

public final class HotKeyGuard {

  private final int saltSpace; // e.g., 8—16 salts for very hot keys
  private final ConcurrentHashMap<String, CompletableFuture<Optional<byte[]>>> inflight = new ConcurrentHashMap<>();

  public HotKeyGuard(int saltSpace) { this.saltSpace = Math.max(1, saltSpace); }

  /** Add a short salt to spread a single hot key across multiple shards. */
  public String saltedKey(String baseKey) {
    int salt = ThreadLocalRandom.current().nextInt(saltSpace);
    return baseKey + "#s" + salt;
  }

  /** Coalesce concurrent loads for the same key to a single loader future. */
  public Optional<byte[]> loadOnce(String key, Callable<Optional<byte[]>> loader) {
    CompletableFuture<Optional<byte[]>> fut = inflight.computeIfAbsent(key, k ->
        CompletableFuture.supplyAsync(() -> {
          try { return loader.call(); }
          catch (Exception e) { throw new CompletionException(e); }
        }).whenComplete((r, t) -> inflight.remove(k)));

    try {
      return fut.get(500, TimeUnit.MILLISECONDS); // bound wait
    } catch (Exception e) {
      fut.cancel(true);
      return Optional.empty();
    }
  }
}
```

**Usage sketch**

```java
// Given: router.forKey(salted) to pick shard; guard.saltedKey(baseKey) to spread load
HotKeyGuard guard = new HotKeyGuard(8);
String base = "product:12345";
String salted = guard.saltedKey(base);

// Read path with coalescing
Optional<byte[]> bytes = guard.loadOnce(base, () -> {
  // This lambda runs once for a burst of the same key
  var jdbc = router.forKey(salted);
  return Optional.ofNullable(jdbc.queryForObject("select payload from product where id=?", byte[].class, 12345));
});
```

---

## Known Uses

-   **Large OLTP platforms** (e-commerce, payments) sharding by **tenantId** or **userId**.
    
-   **Time-series** systems (metrics/logs) with **time/range sharding**.
    
-   **Streaming** platforms (Kafka) partition by **key**; consumers scale via groups.
    
-   **Search/NoSQL** (Elasticsearch/Cassandra) with hash/range shards and rebalancing.
    
-   **Gaming/social** backends: sharded friend graphs/inventories by user.
    

---

## Related Patterns

-   **Database Replication**: read scale *within* each shard.
    
-   **CQRS / Materialized Views**: avoid cross-shard joins by projecting view tables.
    
-   **Distributed Cache / Cache Aside**: reduce hot read pressure per shard.
    
-   **Consistent Hashing**: concrete routing technique for partitioning.
    
-   **Saga / Outbox**: reliable cross-shard workflows.
    
-   **Multi-Region Deployment**: shards per region or geo-partitioning.
    

---

## Implementation Checklist

-   Choose a **key** and **partitioning strategy**; validate distribution with real data.
    
-   Implement a **routing library** (hash/jump/consistent) and a **directory** for exceptions.
    
-   Plan **rebalancing** (vnodes, tenant moves) with **fencing** and backfill tooling.
    
-   Define **cross-shard semantics**: idempotency, sagas, or batch jobs—not ad-hoc joins.
    
-   Add **hot-key** safeguards (salting, per-tenant rate limits, caches).
    
-   Instrument **per-shard** SLOs and **skew dashboards**; alert on outliers.
    
-   Automate **schema changes** and **backups** shard-by-shard; test restores.
    
-   Document **consistency** and **routing** rules for all teams and clients.

