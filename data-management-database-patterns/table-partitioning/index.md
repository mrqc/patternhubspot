
# Data Management & Database Pattern — Table Partitioning

## Pattern Name and Classification

-   **Name:** Table Partitioning

-   **Classification:** Physical data design & performance pattern (storage layout, lifecycle, and query pruning)


## Intent

Split a **large logical table** into multiple **smaller physical partitions** (by **RANGE**, **LIST**, or **HASH**) so the optimizer can **prune** irrelevant partitions, speed up scans/maintenance, and enable **rolling retention** and **parallelism**.

## Also Known As

-   Horizontal Partitioning (table-level)

-   Partitioned Tables

-   Range/List/Hash Partitioning

-   Sub-partitioning (hierarchical partitioning)


## Motivation (Forces)

-   **VLDB growth:** monolithic tables become slow to scan, index, vacuum, or reindex.

-   **Temporal workloads:** queries often hit **recent time windows** (e.g., last 7 days).

-   **Hot/cold data:** recent partitions are hot; old ones can be compressed or dropped.

-   **Operational needs:** online maintenance, **fast drop**/**attach** per partition, smaller recovery units.


Trade-offs:

-   Queries that don’t filter on the partition key won’t benefit.

-   Extra objects to manage, and some DB features behave differently on partitioned tables.

-   Global constraints/unique keys across partitions are DB-specific.


## Applicability

Use when:

-   Tables are **append-heavy** (events, orders, logs, telemetry).

-   You need **retention** (drop/archive old slices quickly).

-   Queries filter on a **predictable dimension** (date, tenant, region).


Be cautious when:

-   Workload is mostly **point lookups** on columns unrelated to the partition key.

-   You require **global uniqueness** not natively supported (may need global indexes or application checks).


## Structure

```sql
Logical table: events
        │  PARTITION BY RANGE(event_ts)
        ├───────────────────────────────────────────────┐
        ▼                                               ▼
  p_2025_08 (Aug)   p_2025_09 (Sep)   p_2025_10 (Oct, hot)   ... (rolling)
     └─ local indexes    └─ local indexes    └─ local indexes
       (cover common predicates/sorts inside each partition)
```

## Participants

-   **Partitioned Table (Parent):** Defines schema and partitioning method/key.

-   **Partitions (Children):** Physical tables for specific key ranges/lists/buckets.

-   **Partitioning Key:** Column(s) by which rows are routed (e.g., `event_ts`, `(tenant_id, event_ts)`).

-   **Indexes & Constraints:** Often **local** (per partition). Some engines support **global** variants.

-   **Lifecycle Jobs:** Create-next, analyze, compress, detach/archive, drop-old.


## Collaboration

1.  **Writes** are routed by the engine (or application) to the correct partition.

2.  **Queries** with predicates on the partition key enable **partition pruning** → fewer blocks to scan.

3.  **Maintenance** runs per partition (reindex, vacuum, compression).

4.  **Retention** is a fast **`DROP PARTITION`** instead of massive deletes.

5.  Optional **sub-partitioning** (e.g., RANGE by month → HASH by tenant) refines distribution.


## Consequences

**Benefits**

-   Lower latency via **pruning** and better cache locality.

-   **Operational agility:** fast drop/attach, parallel maintenance, smaller vacuum windows.

-   **Scalability:** partitions kept to manageable sizes; can mix storage options (compression).


**Liabilities**

-   Requires **aligned predicates** to prune effectively.

-   **More objects** and DDL to orchestrate (automation recommended).

-   **Global uniqueness/foreign keys** may be limited by the RDBMS.

-   Poor partition granularity (too fine/too coarse) hurts either performance or operability.


## Implementation (Key Points)

-   **Choose the key** that dominates filters & lifecycle (time/tenant/region).

-   **Granularity:** daily/weekly/monthly for time; keep each partition a few GB–tens of GB (rule of thumb).

-   **Indexes:** create **local composite indexes** starting with the partition key (or with columns used for pruning + ordering).

-   **Sub-partitioning:** combine **RANGE(time)** with **HASH(tenant)** to spread hotspots.

-   **Retention:** rotate—**create future partitions ahead**, **detach/drop old**; avoid `DELETE` of old rows.

-   **Stats:** analyze partitions; some engines don’t propagate stats globally.

-   **Check plans:** verify **pruning** with `EXPLAIN`; ensure predicates are sargable (avoid non-immutable wrappers).


---

## Sample Code (Java 17 + JDBC/PostgreSQL): Monthly RANGE partitions with retention & pruning

> What it demonstrates
>
> -   Create a parent `events` table **PARTITION BY RANGE(event\_ts)**
>
> -   Attach **Aug/Sep/Oct 2025** partitions
>
> -   Insert sample data across months (with `tenant_id`)
>
> -   Show **partition pruning** via `EXPLAIN`
>
> -   Implement a tiny **retention** step (drop old partition)  
      >     *(Adjust DDL for other RDBMS—Oracle, SQL Server, MySQL 8 have analogous features.)*
>

```java
// File: TablePartitioningDemo.java
// Compile: javac TablePartitioningDemo.java
// Run:     java -cp .:postgresql.jar TablePartitioningDemo "jdbc:postgresql://localhost:5432/demo" "demo" "secret"
import java.sql.*;
import java.time.*;
import java.util.*;

public class TablePartitioningDemo {

  public static void main(String[] args) throws Exception {
    if (args.length < 3) {
      System.err.println("Usage: TablePartitioningDemo <jdbcUrl> <user> <password>");
      return;
    }
    try (Connection cx = DriverManager.getConnection(args[0], args[1], args[2])) {
      cx.setAutoCommit(false);

      dropIfExists(cx);
      createPartitionedSchema(cx);
      attachMonthlyPartitions(cx, YearMonth.of(2025,8), YearMonth.of(2025,10));
      seedEvents(cx);
      cx.commit();

      // Query: last 7 days from a given 'today' => should hit only October partition
      LocalDate today = LocalDate.of(2025, 10, 2);
      LocalDate from = today.minusDays(7);
      System.out.println("\n--- EXPLAIN (expect pruning to p_2025_10) ---");
      explain(cx, """
        SELECT tenant_id, COUNT(*) AS n
        FROM events
        WHERE event_ts >= ?::timestamp
        GROUP BY tenant_id
        ORDER BY tenant_id
      """, ps -> ps.setTimestamp(1, Timestamp.valueOf(from.atStartOfDay())));

      // Execute the same query
      System.out.println("\n--- Results ---");
      try (PreparedStatement ps = cx.prepareStatement("""
        SELECT tenant_id, COUNT(*) FROM events
        WHERE event_ts >= ?::timestamp
        GROUP BY tenant_id ORDER BY tenant_id
      """)) {
        ps.setTimestamp(1, Timestamp.valueOf(from.atStartOfDay()));
        try (ResultSet rs = ps.executeQuery()) {
          while (rs.next()) {
            System.out.printf("tenant=%d count=%d%n", rs.getInt(1), rs.getLong(2));
          }
        }
      }

      // Retention: drop August partition quickly (metadata operation)
      System.out.println("\n--- Dropping old partition p_2025_08 ---");
      try (Statement st = cx.createStatement()) {
        st.execute("DROP TABLE IF EXISTS events_2025_08;");
      }
      cx.commit();

      // Show remaining partitions
      listPartitions(cx);
    }
  }

  /* ---------- DDL ---------- */

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
      st.execute("""
        CREATE TABLE events (
          tenant_id  INT       NOT NULL,
          user_id    INT       NOT NULL,
          event_ts   TIMESTAMP NOT NULL,
          payload    TEXT
        ) PARTITION BY RANGE (event_ts);
      """);
      // Optional: a global index is not supported in vanilla Postgres; we use local indexes per partition below.
    }
  }

  static void attachMonthlyPartitions(Connection cx, YearMonth from, YearMonth to) throws SQLException {
    YearMonth cur = from;
    while (!cur.isAfter(to)) {
      YearMonth next = cur.plusMonths(1);
      String pName = "events_%d_%02d".formatted(cur.getYear(), cur.getMonthValue());
      String ddl = """
        CREATE TABLE %s PARTITION OF events
        FOR VALUES FROM ('%s-01') TO ('%s-01');
      """.formatted(pName, cur, next);
      try (Statement st = cx.createStatement()) { st.execute(ddl); }
      // Local composite index common for queries
      try (Statement st = cx.createStatement()) {
        st.execute("CREATE INDEX ON " + pName + " (event_ts DESC, tenant_id, user_id);");
      }
      cur = next;
    }
  }

  /* ---------- Data ---------- */

  static void seedEvents(Connection cx) throws SQLException {
    String sql = "INSERT INTO events(tenant_id, user_id, event_ts, payload) VALUES(?,?,?,?)";
    Random rnd = new Random(42);
    try (PreparedStatement ps = cx.prepareStatement(sql)) {
      // August (older)
      bulkMonth(ps, YearMonth.of(2025,8), 4, () -> 1 + rnd.nextInt(50), () -> 1 + rnd.nextInt(1000));
      // September
      bulkMonth(ps, YearMonth.of(2025,9), 8, () -> 1 + rnd.nextInt(50), () -> 1 + rnd.nextInt(1000));
      // October (hot)
      bulkMonth(ps, YearMonth.of(2025,10), 2, () -> (rnd.nextInt(3)==0?42:7 + rnd.nextInt(20)),
                () -> 1 + rnd.nextInt(1000));
    }
  }

  static void bulkMonth(PreparedStatement ps, YearMonth ym, int days, IntSupplier tenantFn, IntSupplier userFn)
      throws SQLException {
    for (int d=1; d<=days; d++) {
      for (int i=0; i<500; i++) {
        ps.setInt(1, tenantFn.getAsInt());
        ps.setInt(2, userFn.getAsInt());
        ps.setTimestamp(3, Timestamp.valueOf(LocalDateTime.of(ym.getYear(), ym.getMonth(), d,
                                                              8 + (i%10), (i*7)%60)));
        ps.setString(4, "e:" + ym + ":" + d + ":" + i);
        ps.addBatch();
      }
      ps.executeBatch();
    }
  }

  /* ---------- Utils ---------- */

  static void explain(Connection cx, String sql, SqlConfigurer cfg) throws SQLException {
    try (PreparedStatement ps = cx.prepareStatement("EXPLAIN " + sql)) {
      cfg.apply(ps);
      try (ResultSet rs = ps.executeQuery()) {
        while (rs.next()) System.out.println(rs.getString(1));
      }
    }
  }

  static void listPartitions(Connection cx) throws SQLException {
    System.out.println("\n--- Remaining partitions ---");
    try (PreparedStatement ps = cx.prepareStatement("""
      SELECT inhrelid::regclass AS partition_name
      FROM pg_inherits
      JOIN pg_class parent ON pg_inherits.inhparent = parent.oid
      WHERE parent.relname = 'events'
      ORDER BY 1
    """)) {
      try (ResultSet rs = ps.executeQuery()) {
        while (rs.next()) System.out.println(rs.getString(1));
      }
    }
  }

  @FunctionalInterface interface SqlConfigurer { void apply(PreparedStatement ps) throws SQLException; }
}
```

**Notes**

-   Keeps **local indexes per partition**; Postgres doesn’t have global indexes (some engines do).

-   **Pruning** is visible in `EXPLAIN` (should reference only `events_2025_10` for the “last 7 days” query).

-   **Retention** is a quick `DROP TABLE events_YYYY_MM`.


---

## Known Uses

-   Time-series/observability: logs, metrics, traces partitioned by **day/week/month**.

-   E-commerce orders & payments by **business date** (with archival of older partitions).

-   Multi-tenant SaaS partitioned by **tenant\_id** (LIST) or **hash**, sometimes sub-partitioned by time.

-   Data warehouses: stage and fact tables partitioned by **date** and/or **region**.


## Related Patterns

-   **Index Partitioning:** Partition the **indexes** alongside tables for better pruning & maintenance.

-   **Sharding:** Spread partitions across **nodes**; each shard can contain many table partitions.

-   **Materialized Views:** Precompute aggregates per partition or maintain per-partition refresh.

-   **Read Replica:** Serve heavy reads; replicas often built from partition-friendly backups.

-   **Soft Delete & Retention:** Combine with partition drops to keep tables slim.

-   **Snapshot / Backup:** Snapshot per-partition for faster recovery/clone.


---

### Practical Tips

-   Align **predicates with the key** (`WHERE event_ts >= ?`) and avoid wrapping the key in functions that block pruning.

-   Decide **granularity** from QPS and lifecycle needs; **too many** partitions increase metadata overhead.

-   Automate: create next partitions ahead of time; **monitor pruning ratio** and **hot-partition latency**.

-   Keep **partitions small enough** to reindex quickly (and to fit in buffer cache).

-   Consider **sub-partitioning** for hotspot mitigation (e.g., RANGE(time) → HASH(tenant)).

-   Validate **constraints/uniqueness** requirements early; some engines need workarounds for cross-partition uniqueness.

-   For **retention**, prefer **drop/detach** over `DELETE ... WHERE event_ts < cutoff` to avoid table bloat.
