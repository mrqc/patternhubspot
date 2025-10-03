# Data Management & Database Pattern — Sharding

## Pattern Name and Classification

-   **Name:** Sharding (Horizontal Partitioning)

-   **Classification:** Physical data distribution & scalability pattern (scale-out by splitting data across independent partitions)


## Intent

Distribute rows/objects **horizontally** across multiple independent **shards** (databases or partitions) according to a **sharding key** so that each shard holds a subset of data. This enables **scale-out** for storage and throughput, and isolates failures.

## Also Known As

-   Horizontal Partitioning

-   Keyspace Partitioning

-   Data Federation (when combined behind a router)


## Motivation (Forces)

-   **Single-node limits:** CPU, IOPS, RAM, and storage cap out on large datasets or high QPS.

-   **Throughput & isolation:** Spread load; noisy tenants/keys shouldn’t degrade others.

-   **Latency & locality:** Place shards closer to users/regions.

-   **Trade-offs:** Cross-shard queries/transactions are expensive; rebalancing is operationally tricky; hot keys cause skew.


## Applicability

Use sharding when:

-   Dataset and/or throughput **exceeds** a single node’s capabilities.

-   Access patterns have a **natural partitioning key** (tenant/user/region/id).

-   You need **incremental scale-out** by adding hardware/shards.


Be cautious when:

-   Queries frequently require **multi-shard joins/aggregations**.

-   **Strict ACID** across entities with different shard keys is required.

-   The domain has **no obvious key** and heavy cross-entity relationships.


## Structure

```sql
+--------------------------+
Client / DAL --->|     Shard Router         |---+
 (hash/range)    +--------------------------+   |
            key ─────────────► shardId          |           (scatter/gather)
                                              +--▼------+     +--▼------+
                                              | Shard 0 | ... | Shard N |
                                              |  (DB)   |     |  (DB)   |
                                              +---------+     +---------+
```

-   **Router** maps sharding keys to shard IDs (hash, range, directory, consistent hashing).

-   **Shards** are independent DBs/partitions with their own replicas and maintenance.

-   **Scatter/Gather** executes multi-shard reads by fanning out and merging.


## Participants

-   **Sharding Key:** Field(s) that determine placement (e.g., `tenant_id`, `user_id`, `order_id`).

-   **Shard Router:** Deterministic mapping from key → shard; may use **virtual nodes** for balance.

-   **Shard Catalog/Directory (optional):** Metadata store for dynamic mapping and resharding plans.

-   **Shard (Data Store):** Independent database instance/partition, often with its own **read replicas**.

-   **Balancers/Tools:** Rebalancing movers, backfills, dual-writes during migrations.


## Collaboration

1.  Client/DAL computes `shardId = route(key)` and issues the operation to that shard.

2.  Reads/writes that involve many keys fan out to **multiple shards** and **merge** results.

3.  When adding/removing shards, the router/catal og updates mapping; **movers** shift only affected keys (esp. with **consistent hashing**).

4.  Each shard can independently **replicate** and be maintained.


## Consequences

**Benefits**

-   **Linear-ish scale-out** of capacity and QPS.

-   **Fault isolation**: a sick shard doesn’t take down the fleet.

-   **Operational flexibility**: per-shard upgrades, geo-placement.


**Liabilities**

-   **Cross-shard ops** (joins, transactions, constraints) are hard/slow; need **application orchestration**, **Sagas**, or **TCC**.

-   **Skew & hot keys** create hotspots; require mitigation (salting, sub-sharding, caching).

-   **Complexity**: routing, resharding, backfills, global IDs, and observability.

-   **Secondary indexes** and **uniqueness** across shards require extra design (directory or global index).


## Implementation (Key Points)

-   **Strategy**

    -   **Hash** (e.g., Murmur/xxHash on key): uniform distribution; bad for range scans.

    -   **Range** (time, user ID ranges): great for locality and time-window queries; risk of hot ranges.

    -   **Directory** (lookup table): flexible, supports tenant moves; adds a lookup hop.

    -   **Consistent hashing with virtual nodes**: smooth resharding with minimal key movement.

-   **Key choice:** Must appear in **most predicates** to avoid scatter. Multi-tenant apps often use `(tenant_id, ...)`.

-   **IDs:** Use **globally unique IDs** that encode shard or time (Snowflake/K-Sortable) to avoid central sequences.

-   **Rebalancing:** Dual-write or **copy-then-cutover** with backfill + change capture; validate with checksums.

-   **Cross-shard workflows:** Use **Sagas** (compensations) or **TCC** instead of XA.

-   **Observability:** Record shardId in logs/metrics; track skew, tail latencies, error rates per shard.

-   **Security:** Per-shard credentials/IAM; tenant isolation checks at the app layer.


---

## Sample Code (Java 17): Consistent-Hash Router with Virtual Nodes + Scatter/Gather

> Single-JVM demo using in-memory shards.
>
> -   **ConsistentHashRing** with virtual nodes → smooth rebalancing
>
> -   **ShardedDao** routes CRUD by key; supports **scatter/gather** read
>
> -   Shows **adding a shard** and the **limited key movement** property
>

```java
// File: ShardingDemo.java
// Compile: javac ShardingDemo.java
// Run:     java ShardingDemo
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Function;

/* ---------- Simple KV shard (backed by a concurrent map) ---------- */
interface Shard {
  String name();
  void put(String key, String value);
  Optional<String> get(String key);
  List<Map.Entry<String,String>> scanPrefix(String prefix, int limit);
  int size();
}

final class InMemoryShard implements Shard {
  private final String name;
  private final Map<String,String> data = new ConcurrentHashMap<>();
  InMemoryShard(String name){ this.name = name; }
  public String name(){ return name; }
  public void put(String key, String value){ data.put(key, value); }
  public Optional<String> get(String key){ return Optional.ofNullable(data.get(key)); }
  public List<Map.Entry<String,String>> scanPrefix(String prefix, int limit){
    List<Map.Entry<String,String>> out = new ArrayList<>();
    for (var e : data.entrySet()) {
      if (e.getKey().startsWith(prefix)) { out.add(e); if (out.size()>=limit) break; }
    }
    return out;
  }
  public int size(){ return data.size(); }
}

/* ---------- Consistent hashing ring with virtual nodes ---------- */
final class ConsistentHashRing<T> {
  private final NavigableMap<Long, T> ring = new TreeMap<>();
  private final int virtualNodes;
  private final Function<T, String> nameFn;

  ConsistentHashRing(int virtualNodes, Function<T,String> nameFn) {
    this.virtualNodes = Math.max(1, virtualNodes);
    this.nameFn = nameFn;
  }

  public synchronized void addNode(T node) {
    for (int i=0;i<virtualNodes;i++) {
      long h = hash(nameFn.apply(node) + "#" + i);
      ring.put(h, node);
    }
  }

  public synchronized void removeNode(T node) {
    for (int i=0;i<virtualNodes;i++) {
      long h = hash(nameFn.apply(node) + "#" + i);
      ring.remove(h);
    }
  }

  public T route(String key) {
    long h = hash(key);
    Map.Entry<Long,T> e = ring.ceilingEntry(h);
    if (e == null) e = ring.firstEntry();
    return e.getValue();
  }

  private static long hash(String s) {
    try {
      // Use a stable 64-bit hash (sha-256 truncated here; xxhash/murmur preferred in prod)
      MessageDigest md = MessageDigest.getInstance("SHA-256");
      byte[] b = md.digest(s.getBytes(StandardCharsets.UTF_8));
      // take first 8 bytes as unsigned long
      long v=0; for (int i=0;i<8;i++) v = (v<<8) | (b[i] & 0xff);
      return v ^ (v>>>33);
    } catch (Exception e) { throw new RuntimeException(e); }
  }
}

/* ---------- Sharded DAO (router + shards) ---------- */
final class ShardedDao {
  private final ConsistentHashRing<Shard> ring;
  private final List<Shard> shards = new ArrayList<>();

  ShardedDao(int virtualNodes) {
    this.ring = new ConsistentHashRing<>(virtualNodes, Shard::name);
  }

  public synchronized void addShard(Shard s) {
    shards.add(s);
    ring.addNode(s);
  }

  public synchronized void removeShard(String name) {
    Shard s = shards.stream().filter(x -> x.name().equals(name)).findFirst().orElseThrow();
    ring.removeNode(s);
    shards.remove(s);
  }

  public void put(String key, String value) {
    Shard s = ring.route(key);
    s.put(key, value);
  }

  public Optional<String> get(String key) {
    return ring.route(key).get(key);
  }

  /** Scatter/gather example: prefix search across all shards (fan-out + merge). */
  public List<Map.Entry<String,String>> scanPrefix(String prefix, int perShardLimit) {
    List<Map.Entry<String,String>> out = new ArrayList<>();
    for (Shard s : shards) out.addAll(s.scanPrefix(prefix, perShardLimit));
    // caller may sort/limit globally
    return out;
  }

  public Map<String,Integer> sizes() {
    Map<String,Integer> m = new LinkedHashMap<>();
    for (Shard s : shards) m.put(s.name(), s.size());
    return m;
  }
}

/* ---------- Demo ---------- */
public class ShardingDemo {
  public static void main(String[] args) {
    ShardedDao dao = new ShardedDao(virtualNodes = 64);

    // Initial shards
    dao.addShard(new InMemoryShard("shard-a"));
    dao.addShard(new InMemoryShard("shard-b"));
    dao.addShard(new InMemoryShard("shard-c"));

    // Write some tenant/user keys
    for (int t=1; t<=3; t++) {
      for (int u=1; u<=2000; u++) {
        String key = "tenant:"+t+":user:"+u;
        dao.put(key, "profile{u="+u+", t="+t+", ts="+Instant.now()+"}");
      }
    }
    System.out.println("Sizes before scale-out: " + dao.sizes());

    // Read a few keys
    System.out.println(dao.get("tenant:2:user:42").orElse("not found"));
    System.out.println(dao.get("tenant:3:user:1999").orElse("not found"));

    // Scatter/gather: find all users of tenant:1 with small limit per shard
    var results = dao.scanPrefix("tenant:1:", 10);
    System.out.println("Sample scan across shards: " + results.size() + " rows (merged)");

    // Scale out: add a new shard; only a fraction of keys remap (due to consistent hashing)
    dao.addShard(new InMemoryShard("shard-d"));
    System.out.println("Sizes after adding shard-d (before rebalancing move): " + dao.sizes());

    // In a real system you'd MOVE the remapped keys from old->new shard in background
    // This demo omits copy/move because data is only written at routing time.
  }
}
```

**What the demo shows**

-   A **consistent-hash ring** with 64 virtual nodes smooths distribution and limits key movement when adding `shard-d`.

-   **Routing** by key is deterministic; **scatter/gather** demonstrates multi-shard reads.

-   In production you’d implement **movers** to copy the small subset of keys that remap to the new shard during scale-out, then cut over.


---

## Known Uses

-   **Large SaaS**: customers/tenants spread across shards keyed by `tenant_id`.

-   **Social networks**: users or timelines sharded by `user_id`.

-   **Time-series/logging**: time-range or hash-by-series sharding (often combined with partitioning inside shards).

-   **Gaming**: players/worlds/regions mapped to shards for locality & isolation.

-   **Payments/ledgers**: accounts sharded by `account_id` with read replicas per shard.


## Related Patterns

-   **Index/Table Partitioning:** Partition **within a shard** (e.g., by month), often combined with sharding.

-   **Read Replica:** Scale reads of each shard.

-   **CQRS & Materialized Views:** Avoid cross-shard joins by building per-use read models.

-   **Database per Service:** Organizational cousin; each service may also shard internally.

-   **Saga / TCC:** For cross-shard workflows & compensating transactions.

-   **Consistent Hashing:** Core technique for dynamic shard membership.


---

### Practical Tips

-   Pick a **hot-key-resistant** sharding key (include tenant/user, maybe **salt** with a small random to spread hotspots).

-   Use **virtual nodes** and **consistent hashing** to minimize data movement when changing shard count.

-   Keep **routing logic** in a thin, well-tested library (or a proxy) and version it carefully.

-   Maintain a **shard catalog** (mapping, capacities, placement) and expose **routing metrics** (skew, QPS, P99).

-   Plan **resharding playbooks**: copy, verify (checksums), dual-write, cutover, cleanup.

-   Treat shards as **independent failure domains** (backups, replicas, throttles, error budgets).

-   Prefer **per-tenant scatter** (bounded) over global scatter; cap fan-out and degrade gracefully.

-   Leverage **globally unique, sortable IDs** to avoid central sequences and to aid pagination.
