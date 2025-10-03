# Database Sharding — Cloud / Distributed Systems Pattern

## Pattern Name and Classification

**Database Sharding** — *Cloud / Distributed Systems* **data partitioning** pattern that splits a logical dataset across multiple independent **shards** (databases/instances) to scale **throughput, storage, and isolation**.

---

## Intent

Distribute data and queries across many databases so that **no single node** is a bottleneck; keep each shard **smaller, faster, and cheaper** while preserving a **single logical view** at the application level.

---

## Also Known As

-   **Horizontal Partitioning**

-   **Federation** (older SQL term)

-   **Shared-Nothing Partitioning**


---

## Motivation (Forces)

-   A single database hits limits: CPU/IO saturation, storage growth, long maintenance windows, noisy neighbors.

-   Teams need **independent failure domains** and **operational blast-radius reduction**.

-   Hot partitions/tenants/users dominate load; we want to **spread** or **pin** them.


**Tensions:**

-   Correct **routing** and **rebalancing** vs. operational complexity.

-   **Cross-shard queries/transactions** are hard (joins, counts, unique constraints).

-   Choosing a **shard key** that fits current and future access patterns.


---

## Applicability

Use Sharding when:

-   Dataset/traffic would exceed a single DB’s performance or storage envelope.

-   Workload has a **natural partition key** (tenant ID, user ID, region).

-   You can accept **limited cross-shard operations** or implement aggregations async.


Avoid when:

-   Data is small/moderate; a single vertically scaled DB is simpler.

-   Workload is dominated by **ad-hoc cross-entity joins/analytics** (consider OLAP replicas, lakehouse, or search index).


---

## Structure

```graphql
+------------------+
Client/App  ──────▶|  Shard Router    |───┐
(query key)        +---------┬--------+   │
                             │            │
           ┌─────────────────┴───────┐ ┌──┴────────────────┐
           │  Shard 0 (users 0..A)  │ │  Shard 1 (users B..F)  │ ...
           │  DB instance + schema  │ │  DB instance + schema  │
           └─────────────────────────┘ └───────────────────────┘
```

-   Router maps **shard key → shard id → datasource**.

-   Shards are **autonomous** (shared-nothing).


---

## Participants

-   **Shard Router** — computes shard from a shard key (hash/range/consistent hash/lookup).

-   **Shard Map / Directory** — metadata describing shards and their ranges (static or dynamic).

-   **Shard** — a DB instance/cluster holding a **subset** of rows.

-   **Rebalancer/Migrator** — moves data when adding/removing shards.

-   **Application/DAO** — uses the router for reads/writes; issues **fan-out** for cross-shard queries if needed.


---

## Collaboration

1.  App extracts a **shard key** from the request (e.g., `userId`).

2.  Router selects the **target shard** and executes the SQL against that shard’s datasource.

3.  For cross-shard operations, app **fans out** and **aggregates** (or uses pre-computed/materialized views).

4.  When topology changes, router reads updated shard map; a **migrator** moves affected keys.


---

## Consequences

**Benefits**

-   **Horizontal scale** of R/W throughput and storage.

-   **Fault isolation**: shard incidents don’t take the whole system down.

-   **Operational parallelism**: backups, maintenance, schema changes per shard.


**Liabilities**

-   Complex **routing**, **migrations**, and **cross-shard** semantics.

-   **Global constraints** (unique index across all users) need new designs.

-   **Hot keys** can still skew load; may need **sub-sharding** or **pinning**.

-   Application-aware logic (DAOs/services) must respect sharding invariants.


---

## Implementation (Key Points)

-   Choose a **shard key** aligned with 90%+ of read/write paths. Prefer **immutable** keys.

-   Strategy options:

    -   **Hash**: even spread; poor range queries.

    -   **Range**: good locality/range scans; risk of hot ranges.

    -   **Directory/Lookup**: flexible placement; needs a highly available map.

    -   **Consistent Hashing** + **virtual nodes**: smoother rebalancing on resize.

-   Keep **shard map** externalized (config/DB/etcd) and **hot-reload** in apps.

-   Provide **fan-out** utilities and **idempotent** multi-shard writes (use outbox/transactions per shard + saga for cross-shard workflows).

-   Bake in **tenant-level** backups/restore, **per-shard** metrics/alerts, and **rate limits**.

-   For resharding, use **dual-writes** + **read-cutover** or a **move-and-shadow** strategy.


---

## Sample Code (Java 17) — Shard Router + Hash/Range Strategies + DAO Fan-out

> Minimal skeleton showing:
>
> -   **ShardRouter** with hash and range strategies
>
> -   **ShardMap** with dynamic updates
>
> -   **UserDao** that routes single-key ops and fans out for cross-shard counts  
      >     Replace `DataSource` calls with your JDBC pool (Hikari) or a repository.
>

```java
import java.sql.*;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Function;

// --- Abstractions ---
interface ShardStrategy<K> {
  int shardId(K key, int numShards);
}

final class HashStrategy<K> implements ShardStrategy<K> {
  @Override public int shardId(K key, int n) {
    return Math.floorMod(Objects.requireNonNull(key).hashCode(), n);
  }
}

// Range: map key (e.g., userId prefix or numeric) to explicit ranges
final class RangeStrategy implements ShardStrategy<Long> {
  private final NavigableMap<Long,Integer> boundaries; // startInclusive -> shardId
  RangeStrategy(NavigableMap<Long,Integer> boundaries) { this.boundaries = boundaries; }
  @Override public int shardId(Long key, int n) {
    var e = boundaries.floorEntry(key);
    if (e == null) throw new IllegalArgumentException("key out of range");
    return e.getValue();
  }
}

final class ShardMap {
  private volatile List<String> jdbcUrls; // one URL per shardId (size == numShards)
  ShardMap(List<String> urls) { this.jdbcUrls = List.copyOf(urls); }
  int numShards() { return jdbcUrls.size(); }
  String urlOf(int shardId) { return jdbcUrls.get(shardId); }
  void update(List<String> newUrls) { this.jdbcUrls = List.copyOf(newUrls); } // hot-reload
}

final class ShardRouter<K> {
  private final ShardMap map;
  private final ShardStrategy<K> strategy;
  ShardRouter(ShardMap map, ShardStrategy<K> strategy) { this.map = map; this.strategy = strategy; }
  int shardId(K key) { return strategy.shardId(key, map.numShards()); }
  String jdbcUrlFor(K key) { return map.urlOf(shardId(key)); }
}

// --- Very small DataSource wrapper (for demo only) ---
interface ConnProvider { Connection get(String jdbcUrl) throws SQLException; }

final class DriverManagerProvider implements ConnProvider {
  @Override public Connection get(String jdbcUrl) throws SQLException {
    return DriverManager.getConnection(jdbcUrl); // assumes user/pass in URL or driver defaults
  }
}

// --- Domain DAO: single-key routing + cross-shard fan-out ---
record User(String userId, String name, long createdAt) {}

final class UserDao {
  private final ShardRouter<String> router;
  private final ConnProvider cp;

  UserDao(ShardRouter<String> router, ConnProvider cp) { this.router = router; this.cp = cp; }

  public Optional<User> findById(String userId) throws SQLException {
    String url = router.jdbcUrlFor(userId);
    try (Connection c = cp.get(url);
         PreparedStatement ps = c.prepareStatement("SELECT user_id,name,created_at FROM users WHERE user_id=?")) {
      ps.setString(1, userId);
      try (ResultSet rs = ps.executeQuery()) {
        if (!rs.next()) return Optional.empty();
        return Optional.of(new User(rs.getString(1), rs.getString(2), rs.getLong(3)));
      }
    }
  }

  public void upsert(User u) throws SQLException {
    String url = router.jdbcUrlFor(u.userId());
    try (Connection c = cp.get(url);
         PreparedStatement ps = c.prepareStatement("""
            INSERT INTO users(user_id,name,created_at) VALUES (?,?,?)
            ON CONFLICT (user_id) DO UPDATE SET name=EXCLUDED.name
         """)) {
      ps.setString(1, u.userId()); ps.setString(2, u.name()); ps.setLong(3, u.createdAt());
      ps.executeUpdate();
    }
  }

  // Cross-shard aggregation by fan-out (simple, synchronous)
  public long countAllUsers(List<String> shardUrls) throws SQLException {
    long total = 0;
    for (String url : shardUrls) {
      try (Connection c = cp.get(url);
           Statement st = c.createStatement();
           ResultSet rs = st.executeQuery("SELECT COUNT(*) FROM users")) {
        rs.next(); total += rs.getLong(1);
      }
    }
    return total;
  }
}

// --- Demo wiring ---
public class ShardingDemo {
  public static void main(String[] args) throws Exception {
    // For demo, imagine 3 shard JDBC URLs (could be Postgres instances):
    var shardUrls = List.of(
        "jdbc:postgresql://db-shard-0/mydb?user=app&password=secret",
        "jdbc:postgresql://db-shard-1/mydb?user=app&password=secret",
        "jdbc:postgresql://db-shard-2/mydb?user=app&password=secret"
    );

    ShardMap shardMap = new ShardMap(shardUrls);

    // Choose a strategy: hash by userId (typical for even spread)
    var router = new ShardRouter<>(shardMap, new HashStrategy<String>());

    // Alternative: range by numeric userId (example boundaries)
    // var boundaries = new java.util.TreeMap<Long,Integer>();
    // boundaries.put(0L, 0); boundaries.put(1_000_000L, 1); boundaries.put(2_000_000L, 2);
    // var router = new ShardRouter<>(shardMap, new RangeStrategy(boundaries).<String> // would need parse to Long

    var dao = new UserDao(router, new DriverManagerProvider());

    // Example logical operations (pseudo; requires real DBs behind URLs):
    // dao.upsert(new User("user-123", "Alice", System.currentTimeMillis()));
    // Optional<User> u = dao.findById("user-123");
    // long total = dao.countAllUsers(shardUrls);

    // Dynamic resharding: add a 4th shard and hot-reload the map (requires migration)
    // shardMap.update(List.of(shardUrls.get(0), shardUrls.get(1), shardUrls.get(2), "jdbc:...-3"));
    // Note: after resizing, hash→shard mapping changes; use **consistent hashing** or migrate keys first.
  }
}
```

### Notes & Variations

-   **Consistent hashing + virtual nodes** mitigate massive remaps when the shard count changes.

-   For **tenant sharding**, use a **directory map**: `tenantId → shardId` stored in a highly available KV (etcd/Consul/DB); allows targeted moves.

-   Implement **dual reads/writes** during re-shard: write both old/new shard; read from new-first-then-old until cutover.

-   For **global uniqueness** (e.g., emails), maintain a **global index service** or partition the keyspace for uniqueness checks.

-   Provide **per-shard migrations** & **schema drift control** (version table + orchestration).

-   Cross-shard transactions use **Sagas** or **two-phase commit** (rarely recommended at scale).


---

## Known Uses

-   **Twitter** (user/tweet sharding), **Facebook/Meta** (TAO/region sharding), **Shopify** (tenant-per-db), **YouTube** (video metadata sharding).

-   Managed systems: **CockroachDB/Spanner** auto-rebalancing ranges (transparent sharding), **Cassandra/DynamoDB** partitioning by key.


---

## Related Patterns

-   **Partitioning (Functional/Vertical)** — split by table/domain vs by rows.

-   **Read Replicas** — scale reads *within* a shard; complements sharding.

-   **Consistent Hashing** — smooth key→shard mapping; easier resize.

-   **Saga / Outbox** — coordinate cross-shard workflows & messaging.

-   **CQRS / Materialized Views** — avoid cross-shard joins by projecting read models.

-   **Cache Aside** — keep hot keys near the app; reduces cross-shard fan-outs.
