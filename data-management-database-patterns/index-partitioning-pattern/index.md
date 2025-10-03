# Data Management & Database Pattern — Index Partitioning

## Pattern Name and Classification

-   **Name:** Index Partitioning

-   **Classification:** Physical data design & performance pattern (storage layout, query pruning)


## Intent

Split a **large index** into multiple **smaller partitions**—by **range**, **hash**, or **list**—so the optimizer can **prune** irrelevant partitions, reduce I/O and memory footprint, and speed up maintenance (build, rebuild, vacuum) by working on smaller units.

## Also Known As

-   Partitioned Index / Local Index

-   Sharded Index (when implemented across nodes)

-   Sub-Indexing / Segmenting an Index


## Motivation (Forces)

-   **Very large tables** make single monolithic indexes huge → slow scans, large memory pressure, and long rebuilds.

-   **Temporal access patterns** (e.g., “last 7 days”) usually touch only *hot* time windows.

-   **Tenant/key skew** often concentrates traffic on specific value ranges or keys.

-   **Operations cost:** reindexing, vacuuming, and backups for a giant index are expensive and risky.

-   **Availability:** Smaller partitions enable online, rolling maintenance.


## Applicability

Use index partitioning when:

-   Fact/append-only tables grow fast (logs, events, orders) and queries filter on **time** or **tenant**.

-   You need **rolling retention** (drop old partitions fast).

-   You experience **hot partitions** (recent data) and want targeted, smaller **local indexes**.


Be cautious when:

-   Workload is mostly **full-table scans** without selective predicates (partitioning helps less).

-   Predicates don’t align with the partition key → limited pruning.

-   You require heavy **cross-partition** unique constraints (DB support varies).


## Structure

```sql
Partitioned Table: events
                          │
        ┌─────────────────┼──────────────────┐
        ▼                 ▼                  ▼
  p_2025_08 (range)  p_2025_09 (range)  p_2025_10 (range)
     │  local idx       │  local idx         │  local idx
     └── idx_ev_ts_tenant└── idx_ev_ts_tenant └── idx_ev_ts_tenant
```

-   **Local/partitioned indexes**: separate index per partition.

-   **Global indexes** (DB-specific): one logical index across partitions (useful for global uniqueness; higher maintenance).


## Participants

-   **Partitioning Key:** Column(s) used to split data (e.g., `event_ts`, `(tenant_id, hash(user_id))`).

-   **Partitioned Table:** Parent table with child partitions.

-   **Local Indexes:** One per partition, often composite (e.g., `(tenant_id, event_ts, user_id)`).

-   **Optimizer/Planner:** Performs **partition pruning** using predicates and stats.


## Collaboration

1.  **DML** routes new rows to the correct partition based on the partitioning key.

2.  **Queries** with predicates on the key allow the optimizer to **scan only relevant partitions**, and within them to use the **local index**.

3.  **Maintenance** (rebuild, analyze, vacuum) is performed **per-partition**, sometimes online and in parallel.

4.  **Lifecycle**: Old partitions (data + index) are **dropped** in O(1) metadata time.


## Consequences

**Benefits**

-   **Pruning** reduces scanned data → lower latency & I/O.

-   **Smaller indexes** fit cache; better branch/paging behavior.

-   **Faster maintenance** (reindex just the hot partition).

-   **Operational agility**: quick drop/archival per partition.


**Liabilities**

-   **Design coupling:** Queries must use predicates aligned with the partition key (or functions with immutable semantics usable for pruning).

-   **Cross-partition uniqueness** is limited/harder (DB-specific global indexes or application-enforced).

-   **More objects** to manage (more `ANALYZE`, `REINDEX`, privileges).

-   Bad **granularity** (too fine/too coarse) hurts either metadata or pruning.


## Implementation (Key Points)

-   **Choose the partition key** by the most common and selective predicate (time, tenant, geo).

-   Prefer **range partitions** for temporal data; **hash** for even distribution by high-cardinality keys; **list** for small enumerations (regions/tenants).

-   Create **composite local indexes** that start with the partitioning column(s) then the commonly filtered/sorted columns.

-   Consider **sub-partitioning** (e.g., range by month, then hash by tenant) if your DB supports it.

-   Size partitions so that **each index** fits comfortably in memory (rule of thumb: a few GBs each, not hundreds).

-   Use **partial indexes** inside partitions for sparse predicates.

-   Automate **partition creation/rotation** (e.g., create next month ahead of time).

-   Monitor **pruning effectiveness** (explain plans), **hot partitions**, and **bloat**; reindex only where needed.


---

## Sample Code (Java 17, JDBC + PostgreSQL): Range-Partitioned Table with Local Indexes

> What it does
>
> -   Creates an `events` parent table partitioned **by month** on `event_ts`
>
> -   Attaches three monthly partitions (`2025-08`, `2025-09`, `2025-10`)
>
> -   Creates **local composite indexes** per partition: `(tenant_id, event_ts DESC, user_id)`
>
> -   Inserts sample rows across months
>
> -   Runs a **pruned** query (last 7 days for one tenant) and prints results
>
> -   Fetches the **EXPLAIN** plan text so you can see partition pruning
>

```java
// File: IndexPartitioningDemo.java
// Compile: javac IndexPartitioningDemo.java
// Run:     java -cp .:postgresql.jar IndexPartitioningDemo "jdbc:postgresql://localhost:5432/demo" "demo" "secret"
import java.sql.*;
import java.time.*;
import java.util.*;

public class IndexPartitioningDemo {

  public static void main(String[] args) throws Exception {
    if (args.length < 3) {
      System.err.println("Usage: IndexPartitioningDemo <jdbcUrl> <user> <password>");
      return;
    }
    try (Connection cx = DriverManager.getConnection(args[0], args[1], args[2])) {
      cx.setAutoCommit(false);
      dropIfExists(cx);
      createPartitionedSchema(cx);
      seedData(cx);
      cx.commit();

      // Query: last 7 days for tenant 42 (should prune to p_2025_10)
      LocalDate today = LocalDate.of(2025, 10, 2); // example anchor
      LocalDate from = today.minusDays(7);
      System.out.println("\n--- EXPLAIN (pruning expected) ---");
      explain(cx, """
        SELECT tenant_id, user_id, event_ts, payload
        FROM events
        WHERE tenant_id = ?
          AND event_ts >= ?::timestamp
        ORDER BY event_ts DESC
        LIMIT 20
      """, ps -> {
        try {
          ps.setInt(1, 42);
          ps.setTimestamp(2, Timestamp.valueOf(from.atStartOfDay()));
        } catch (SQLException e) { throw new RuntimeException(e); }
      });

      System.out.println("\n--- Results ---");
      try (PreparedStatement ps = cx.prepareStatement("""
        SELECT tenant_id, user_id, event_ts, payload
        FROM events
        WHERE tenant_id = ?
          AND event_ts >= ?::timestamp
        ORDER BY event_ts DESC
        LIMIT 20
      """)) {
        ps.setInt(1, 42);
        ps.setTimestamp(2, Timestamp.valueOf(from.atStartOfDay()));
        try (ResultSet rs = ps.executeQuery()) {
          while (rs.next()) {
            System.out.printf("tenant=%d user=%d ts=%s payload=%s%n",
                rs.getInt(1), rs.getInt(2), rs.getTimestamp(3).toInstant(), rs.getString(4));
          }
        }
      }
    }
  }

  static void dropIfExists(Connection cx) throws SQLException {
    try (Statement st = cx.createStatement()) {
      st.execute("DROP TABLE IF EXISTS events_2025_08 CASCADE;");
      st.execute("DROP TABLE IF EXISTS events_2025_09 CASCADE;");
      st.execute("DROP TABLE IF EXISTS events_2025_10 CASCADE;");
      st.execute("DROP TABLE IF EXISTS events CASCADE;");
    }
  }

  static void createPartitionedSchema(Connection cx) throws SQLException {
    try (Statement st = cx.createStatement()) {
      // Parent partitioned table
      st.execute("""
        CREATE TABLE events (
          tenant_id  INT       NOT NULL,
          user_id    INT       NOT NULL,
          event_ts   TIMESTAMP NOT NULL,
          payload    TEXT,
          PRIMARY KEY (tenant_id, event_ts, user_id)  -- PK aligned to partition key
        ) PARTITION BY RANGE (event_ts);
      """);

      // Monthly partitions (2025-08, 2025-09, 2025-10)
      st.execute("""
        CREATE TABLE events_2025_08 PARTITION OF events
        FOR VALUES FROM ('2025-08-01') TO ('2025-09-01');
      """);
      st.execute("""
        CREATE TABLE events_2025_09 PARTITION OF events
        FOR VALUES FROM ('2025-09-01') TO ('2025-10-01');
      """);
      st.execute("""
        CREATE TABLE events_2025_10 PARTITION OF events
        FOR VALUES FROM ('2025-10-01') TO ('2025-11-01');
      """);

      // Local composite indexes for common predicate and sort
      st.execute("CREATE INDEX ON events_2025_08 (tenant_id, event_ts DESC, user_id);");
      st.execute("CREATE INDEX ON events_2025_09 (tenant_id, event_ts DESC, user_id);");
      st.execute("CREATE INDEX ON events_2025_10 (tenant_id, event_ts DESC, user_id);");

      // Optional: partial index per partition (example: only tenant 42)
      st.execute("""
        CREATE INDEX ON events_2025_10 (event_ts DESC)
        WHERE tenant_id = 42;
      """);
    }
  }

  static void seedData(Connection cx) throws SQLException {
    String sql = "INSERT INTO events(tenant_id, user_id, event_ts, payload) VALUES(?,?,?,?)";
    try (PreparedStatement ps = cx.prepareStatement(sql)) {
      Random rnd = new Random(42);

      // Old data (Aug)
      insertRange(ps, 7, LocalDateTime.of(2025,8,15,10,0), 1000, () -> 1 + rnd.nextInt(50), () -> 1 + rnd.nextInt(100));

      // September data
      insertRange(ps, 7, LocalDateTime.of(2025,9,15,10,0), 2000, () -> 1 + rnd.nextInt(50), () -> 1 + rnd.nextInt(100));

      // October data (hot), including tenant 42
      for (int d = 1; d <= 2; d++) {
        for (int i = 0; i < 200; i++) {
          int tenant = (i % 3 == 0) ? 42 : 7 + rnd.nextInt(20);
          int user = 1 + rnd.nextInt(1000);
          LocalDateTime ts = LocalDateTime.of(2025,10,d, 8 + rnd.nextInt(12), rnd.nextInt(60));
          ps.setInt(1, tenant);
          ps.setInt(2, user);
          ps.setTimestamp(3, Timestamp.valueOf(ts));
          ps.setString(4, "e-" + tenant + "-" + user + "-" + ts);
          ps.addBatch();
        }
        ps.executeBatch();
      }
    }
  }

  static void insertRange(PreparedStatement ps, int days, LocalDateTime base, int rowsPerDay,
                          IntSupplier tenantGen, IntSupplier userGen) throws SQLException {
    for (int d = 0; d < days; d++) {
      for (int i = 0; i < rowsPerDay; i++) {
        int tenant = tenantGen.getAsInt();
        int user = userGen.getAsInt();
        LocalDateTime ts = base.plusDays(d).plusMinutes(i % 120);
        ps.setInt(1, tenant);
        ps.setInt(2, user);
        ps.setTimestamp(3, Timestamp.valueOf(ts));
        ps.setString(4, "e-" + tenant + "-" + user + "-" + ts);
        ps.addBatch();
      }
      ps.executeBatch();
    }
  }

  static void explain(Connection cx, String sql, SqlConfigurer cfg) throws SQLException {
    try (PreparedStatement ps = cx.prepareStatement("EXPLAIN " + sql)) {
      cfg.apply(ps);
      try (ResultSet rs = ps.executeQuery()) {
        while (rs.next()) System.out.println(rs.getString(1));
      }
    }
  }

  @FunctionalInterface interface SqlConfigurer { void apply(PreparedStatement ps) throws SQLException; }
}
```

**Notes**

-   The **primary key** starts with the **partitioning column** (`event_ts`) to keep B-tree locality and enable pruning with index usage.

-   We create **local composite indexes** that match common filters and ordering.

-   The **partial index** (“tenant 42”) shows how to optimize for a hot tenant without bloating others.

-   Change the JDBC URL to your PostgreSQL; for other RDBMS (Oracle, MySQL 8, SQL Server), adjust partition DDL accordingly.


---

## Known Uses

-   **Time-series/event tables** (application logs, clickstreams, telemetry) partitioned by **day/week/month** with local indexes on `(tenant, ts)` or `(device, ts)`.

-   **Financial trades/orders** partitioned by **business date**; local indexes on `(account, ts)` or `(symbol, ts)`.

-   **Multi-tenant SaaS**: list/hash partitions per **tenant\_id**, with per-partition indexes to isolate hotspots.


## Related Patterns

-   **Table Partitioning:** The base pattern; index partitioning often accompanies it (local indexes).

-   **Sharding (Horizontal Partitioning):** Distribute partitions across nodes; each shard maintains its own local index.

-   **Covering Index / Composite Index:** Design local indexes to cover common queries.

-   **Materialized Views:** Alternative/compliment for accelerating specific queries.

-   **Data Archival / ILM:** Drop or move old partitions (data + index) on a schedule.


---

### Practical Tips

-   Pick a **partition size** that balances pruning with object count (e.g., **daily** or **monthly** for time-series).

-   Ensure **predicates** use the partitioning key (and immutable functions like `DATE_TRUNC`) to keep pruning effective.

-   Align **index prefix** with the most selective/filtering columns.

-   Automate **future partition creation** and **rolling retention** (drop/attach).

-   Track: **pruning ratio** (partitions scanned / total), **index size per partition**, **reindex time**, **bloat**, and **hot-partition latency**.

-   Consider **BRIN** (PostgreSQL) for very large, naturally ordered tables to complement or replace B-tree in cold partitions.
