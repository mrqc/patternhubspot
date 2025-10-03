# Cloud Distributed Systems Pattern — Sharding

## Pattern Name and Classification

-   **Name:** Sharding

-   **Classification:** Structural / Data partitioning pattern for distributed systems and databases (scalability & multi-tenancy)


## Intent

Split a large dataset (and its workload) horizontally across **multiple independent partitions (shards)** so that each shard holds only a subset of the data, enabling:

-   near-linear **horizontal scaling** of storage and throughput,

-   operational isolation (blast-radius reduction),

-   tenant or key-space segregation (compliance, cost, locality).


## Also Known As

-   Horizontal Partitioning

-   Data Partitioning

-   Keyspace Partitioning

-   Region/Tablet/Split (vendor terminology: ranges, regions, tablets, partitions)


## Motivation (Forces)

-   **Scale:** Single node cannot meet storage or QPS needs → split data & traffic.

-   **Hotspots:** Skewed key distributions create hot shards → need balanced partitioning.

-   **Elasticity vs. Stability:** Rebalancing enables growth but moves data (costly).

-   **Locality & Compliance:** Keep data near users or within legal boundaries.

-   **Cross-Shard Work:** Some queries/transactions span shards → higher complexity.

-   **Global Consistency:** Global secondary indexes, unique constraints, and id generation are harder.

-   **Operational Isolation:** Faults or heavy tenants should not impact others.


## Applicability

Use sharding when you need:

-   Storage or throughput beyond a single machine/node/primary,

-   Tenant isolation (noisy neighbors, per-tenant SLOs, data residency),

-   Geo-local reads/writes (latency/cost).


Avoid/limit sharding when:

-   Data size and throughput comfortably fit on a single node with vertical scaling,

-   Your workload requires frequent **cross-entity** joins/scans over the whole dataset.


## Structure

-   **Shard Key / Partition Key:** Function of entity attributes that determines shard placement.

-   **Partitioning Function:** Range-based, hash-based, directory-based, or **consistent hashing** with virtual nodes.

-   **Shard Map / Routing Layer:** Maps shard key → shard id → physical endpoint (DB, node).

-   **Shards:** Independent storage units (tablespaces/DBs/indices) with their own replication/backup.

-   **Rebalancer:** Splits/merges/migrates shards while serving traffic.

-   **Scatter-Gather Layer (optional):** Executes fan-out queries and merges results.


## Participants

-   **Router:** Computes shard id from key and chooses a target shard.

-   **Shard Catalog / Directory:** Source of truth for shard boundaries and locations.

-   **Shard Storage:** Database/cluster node holding the partition.

-   **Rebalancing Service:** Moves/reshapes data; updates the catalog; throttles copy.

-   **ID Generator:** Produces globally unique, roughly ordered IDs without hot-sharding.

-   **Query Coordinator (optional):** Runs cross-shard queries/transactions.


## Collaboration

1.  **Client/DAO** computes shard id from the **shard key**.

2.  **Router** looks up the shard location in the **catalog** and forwards the request.

3.  **Shard** executes the operation; replication/backup are local to the shard.

4.  For **cross-shard** ops, the **coordinator** scatter-gathers or runs a saga/2PC.

5.  **Rebalancer** splits/merges shards and updates the catalog; routers pick up changes.


## Consequences

**Benefits**

-   Scales capacity and throughput horizontally.

-   Isolates failures/tenants; enables geo-locality & cost control.

-   Can yield lower tail latency by reducing per-shard working set.


**Liabilities / Trade-offs**

-   Cross-shard joins/transactions become complex and slower.

-   Operational complexity: rebalancing, metadata, backups, schema evolution per shard.

-   Hot partitions from poor key choice (monotonic IDs, skewed tenants).

-   Global uniqueness & secondary indexes are harder (often approximate or per-shard + reconciliation).


## Implementation (Key Points)

-   **Choose a partitioning scheme:**

    -   **Hash sharding:** Even distribution; poor range query locality.

    -   **Range sharding:** Great for range scans/time; risk of hotspots on monotonic keys (mitigate by key-salting or time-bucketing).

    -   **Directory sharding:** Catalog maps key→shard; flexible but adds metadata hop.

    -   **Consistent hashing + virtual nodes:** Smooth rebalancing; good for caches/queues, works well for DB routing too.

-   **Shard key design:** Prefer **high-cardinality**, evenly distributed keys (e.g., tenantId, userId). Avoid timestamp-only.

-   **Rebalancing strategies:** split/merge ranges, move virtual nodes, dual-write + backfill, change-data-capture (CDC).

-   **Schema & migrations:** Version the schema; roll forward per shard; use feature flags.

-   **Cross-shard operations:**

    -   **Queries:** scatter-gather with concurrency limits; partial results if allowed.

    -   **Transactions:** prefer **sagas/outbox**; if needed, **2PC** with careful timeouts and idempotency.

-   **IDs:** Use time+random/shard bits (e.g., Snowflake-style) to avoid single-shard hotspots.

-   **Observability:** Per-shard QPS/latency/hot-key detection; rebalancing progress; catalog health.

-   **Failure domains:** Keep shard replication within AZs; spread primaries across AZs; isolate tenants.

-   **Client routing:** Cache the shard map with TTL/watch; handle cache misses and catalog changes.


---

## Sample Code (Java 17): Consistent-Hash Router with Virtual Nodes + JDBC Routing

> Educational demo that:
>
> -   Builds a consistent-hash ring with **virtual nodes**
>
> -   Routes a key to a shard and picks a `DataSource`
>
> -   Shows **range** and **hash** strategies behind one interface
>
> -   Sketches a DAO that uses the router for reads/writes
>

```java
// File: ShardingDemo.java
// Compile: javac ShardingDemo.java
// Run:     java ShardingDemo
import java.nio.charset.StandardCharsets;
import java.sql.*;
import java.util.*;
import java.util.concurrent.ConcurrentSkipListMap;
import java.util.function.Function;

// ----- Abstractions -----
interface ShardingStrategy {
    String shardFor(byte[] shardKey);
}

final class ShardCatalog {
    // shardId -> JDBC URL (could also keep credentials/pool/DataSource)
    private final Map<String, String> shardToJdbcUrl = new HashMap<>();
    void put(String shardId, String jdbcUrl) { shardToJdbcUrl.put(shardId, jdbcUrl); }
    Optional<String> jdbcUrl(String shardId) { return Optional.ofNullable(shardToJdbcUrl.get(shardId)); }
    Set<String> shardIds() { return shardToJdbcUrl.keySet(); }
}

// ----- Consistent Hashing with Virtual Nodes -----
final class ConsistentHashStrategy implements ShardingStrategy {
    private final NavigableMap<Long, String> ring = new ConcurrentSkipListMap<>();
    private final int virtualNodes;
    ConsistentHashStrategy(Map<String, Integer> shardWeights, int virtualNodes) {
        this.virtualNodes = Math.max(1, virtualNodes);
        shardWeights.forEach((shardId, weight) -> addShard(shardId, weight));
    }
    public synchronized void addShard(String shardId, int weight) {
        for (int v = 0; v < virtualNodes * Math.max(1, weight); v++) {
            long h = hash64((shardId + "#VN" + v).getBytes(StandardCharsets.UTF_8));
            ring.put(h, shardId);
        }
    }
    public synchronized void removeShard(String shardId) {
        ring.entrySet().removeIf(e -> e.getValue().equals(shardId));
    }
    @Override public String shardFor(byte[] shardKey) {
        if (ring.isEmpty()) throw new IllegalStateException("empty ring");
        long h = hash64(shardKey);
        Map.Entry<Long, String> e = ring.ceilingEntry(h);
        return (e != null) ? e.getValue() : ring.firstEntry().getValue();
    }
    // simple 64-bit hash (SplitMix64-ish over Java's byte[]); for demo only
    static long hash64(byte[] data) {
        long x = 0x9E3779B97F4A7C15L;
        for (byte b : data) {
            x ^= (b & 0xff);
            x *= 0xBF58476D1CE4E5B9L;
            x ^= (x >>> 27);
            x *= 0x94D049BB133111EBL;
            x ^= (x >>> 31);
        }
        return x;
    }
}

// ----- Range Strategy (e.g., tenant ranges) -----
final class RangeShardingStrategy implements ShardingStrategy {
    // upperBound (inclusive) -> shardId, ordered
    private final NavigableMap<String,String> bounds = new TreeMap<>();
    RangeShardingStrategy(Map<String,String> upperBoundToShard) {
        bounds.putAll(upperBoundToShard); // e.g., {"m"->S1, "z"->S2}
    }
    @Override public String shardFor(byte[] key) {
        String k = new String(key, StandardCharsets.UTF_8);
        Map.Entry<String,String> e = bounds.ceilingEntry(k);
        if (e != null) return e.getValue();
        return bounds.lastEntry().getValue(); // wrap
    }
}

// ----- Router that picks a JDBC endpoint -----
final class ShardRouter {
    private final ShardingStrategy strategy;
    private final ShardCatalog catalog;
    ShardRouter(ShardingStrategy strategy, ShardCatalog catalog) {
        this.strategy = strategy; this.catalog = catalog;
    }
    public String shardIdFor(String key) { return strategy.shardFor(key.getBytes(StandardCharsets.UTF_8)); }
    public Connection openConnection(String key) throws Exception {
        String shardId = shardIdFor(key);
        String url = catalog.jdbcUrl(shardId).orElseThrow(() -> new IllegalStateException("no jdbc for " + shardId));
        // For demo we use DriverManager; in production use pooled DataSources (HikariCP)
        return DriverManager.getConnection(url);
    }
}

// ----- Example DAO using the router (pseudo schema: accounts(id PK, tenant_id, balance) ) -----
final class AccountDao {
    private final ShardRouter router;
    AccountDao(ShardRouter router) { this.router = router; }

    public void upsertAccount(String tenantId, String accountId, long balance) throws Exception {
        try (Connection c = router.openConnection(tenantId)) {
            c.setAutoCommit(true);
            try (PreparedStatement ps = c.prepareStatement(
                    "insert into accounts(id, tenant_id, balance) values(?,?,?) " +
                    "on conflict (id) do update set balance = excluded.balance")) {
                ps.setString(1, accountId);
                ps.setString(2, tenantId);
                ps.setLong(3, balance);
                ps.executeUpdate();
            }
        }
    }

    public OptionalLong getBalance(String tenantId, String accountId) throws Exception {
        try (Connection c = router.openConnection(tenantId);
             PreparedStatement ps = c.prepareStatement(
                     "select balance from accounts where id = ? and tenant_id = ?")) {
            ps.setString(1, accountId);
            ps.setString(2, tenantId);
            try (ResultSet rs = ps.executeQuery()) {
                return rs.next() ? OptionalLong.of(rs.getLong(1)) : OptionalLong.empty();
            }
        }
    }
}

// ----- Demo main (routing only; DBs would need to exist) -----
public class ShardingDemo {
    public static void main(String[] args) throws Exception {
        // 1) Build a shard catalog (normally from config/service discovery)
        var catalog = new ShardCatalog();
        catalog.put("shard-a", "jdbc:postgresql://db-a:5432/app");
        catalog.put("shard-b", "jdbc:postgresql://db-b:5432/app");
        catalog.put("shard-c", "jdbc:postgresql://db-c:5432/app");

        // 2) Choose a strategy — consistent hash with virtual nodes
        Map<String,Integer> weights = Map.of("shard-a",1, "shard-b",1, "shard-c",1);
        ShardingStrategy strategy = new ConsistentHashStrategy(weights, 128);

        // 3) Router & DAO
        var router = new ShardRouter(strategy, catalog);
        var dao = new AccountDao(router);

        // 4) Route some tenant IDs (no DB calls, just show shard mapping)
        String[] tenants = {"acme", "globex", "initech", "wayne", "stark", "umbrella"};
        for (String t : tenants) {
            System.out.printf("tenant=%s -> %s%n", t, router.shardIdFor(t));
        }

        // Example DAO usage (would require actual DBs/driver on classpath):
        // dao.upsertAccount("acme", "acc-001", 1000);
        // System.out.println(dao.getBalance("acme", "acc-001"));
    }
}
```

**What the example shows**

-   Pluggable **sharding strategy** (consistent-hash or range) behind the same `ShardingStrategy` API.

-   **Virtual nodes** (128 per shard) to smooth distribution and future rebalancing.

-   **Router** that picks a shard by key and resolves to a **JDBC endpoint** (swap for HTTP/gRPC endpoints just as easily).

-   A DAO that always uses **tenantId** as the shard key → all tenant rows land on the same shard (co-location for joins).


> Productionize by: pooling connections, hot-reloading the catalog, adding retries with backoff, and emitting per-shard metrics.

---

## Known Uses

-   **MySQL/Vitess**: keyspace+vindexes; transparent resharding.

-   **MongoDB**: range/hash sharding with mongos router.

-   **Elasticsearch/OpenSearch**: primary/replica **shards** with routing by document id.

-   **HBase/Bigtable**: **regions/tablets** split/merge based on key ranges.

-   **Apache Cassandra/Dynamo-style stores**: partitioners with **consistent hashing** and virtual nodes.

-   **Twitter Snowflake-style IDs**: time+shard bits for unique IDs without single-shard hotspots.

-   **Spanner/CockroachDB**: split/merge **ranges** with dynamic rebalancing and locality rules.


## Related Patterns

-   **Service Discovery:** Keep the shard catalog fresh (endpoints & ownership).

-   **Load Balancer:** Distribute requests **within** a shard’s replica set.

-   **Retry with Backoff:** Prefer retrying on **another replica** of the same shard.

-   **Saga / Outbox:** Manage cross-shard transactions and asynchronous workflows.

-   **Consistent Hashing:** A concrete partitioning function frequently used for sharding.

-   **CQRS / Materialized Views:** Reduce cross-shard joins by precomputing read models.

-   **Bulkhead / Pool Isolation:** Separate resource pools per shard to contain failures.


---

### Practical Tips

-   Start with **hash sharding by tenant/user id**; keep the key **immutable**.

-   Use **virtual nodes** and keep shard counts **higher** than nodes so you can rebalance by moving VNs.

-   Build **hot-key detection** (95/99th percentile per key); mitigate with key-salting or dedicated shards.

-   For time-series, use **time-bucketed** ranges (e.g., monthly) to avoid hot leaders.

-   Plan resharding: dual-read/dual-write + CDC backfill; flip traffic once lag≈0.

-   Keep a **global id service** (Snowflake) and avoid monotonic inserts mapping to one shard.

-   Instrument **per-shard** SLOs; imbalance often hides in the tails.
