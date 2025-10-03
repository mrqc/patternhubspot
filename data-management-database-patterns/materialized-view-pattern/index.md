
# Data Management & Database Pattern — Materialized View

## Pattern Name and Classification

-   **Name:** Materialized View (MV)

-   **Classification:** Read-optimization & caching pattern (precomputed query results persisted as a table-like object)


## Intent

Precompute and **persist** the result of an expensive query (joins, aggregations) so reads are **fast and predictable**. Keep the MV **fresh** via **refresh** strategies (on-demand, scheduled, incremental), trading freshness for performance.

## Also Known As

-   Summary Table / Snapshot Table

-   Indexed View (SQL Server)

-   Materialized Query Table (DB2)

-   Incremental Aggregation (in streaming systems)


## Motivation (Forces)

-   **Expensive queries** (multi-join, large scans, group-bys) are too slow to run ad hoc at user-facing latency.

-   **Hot dashboards** need **consistent low latency** results.

-   **Compute vs. freshness trade-off:** recomputing every request is wasteful; batching refresh (or incremental) is cheaper.

-   **Operational cost:** MVs occupy storage and must be refreshed without blocking writers/readers excessively.


## Applicability

Use a Materialized View when:

-   The same heavy query (or small family of them) is read frequently.

-   **Near-real-time** (seconds–minutes) freshness is acceptable, or the platform supports **incremental** refresh.

-   You can encode the query as a deterministic SELECT (or a pipeline producing a table).


Avoid/Adapt when:

-   Results must be **strictly up-to-the-millisecond** consistent with base tables (use normal views or query the base).

-   Underlying data changes constantly and refresh cost outweighs benefit.

-   Ad-hoc, diverse queries dominate (MV won’t serve many shapes).


## Structure

```scss
Base Tables (normalized, mutable)
          │
          │  SELECT ... (joins, filters, aggregates)
          ▼
  Materialized View (persisted result + indexes)
          ▲              │
          │ refresh      │ query (fast)
   Refresh Engine  ──────┘
  (manual, scheduled, incremental, streaming)
```

## Participants

-   **Base Tables:** Source relations whose changes affect the MV.

-   **Materialized View:** Persisted result set (often indexable; may support CONCURRENT/INCREMENTAL refresh).

-   **Refresh Mechanism:** `REFRESH MATERIALIZED VIEW`, `ALTER MATERIALIZED VIEW ...`, incremental maintenance, triggers/CDC, or streaming jobs.

-   **Scheduler / Orchestrator (optional):** Cron, Airflow, DB jobs to refresh.

-   **Consumers:** Dashboards, APIs, analysts.


## Collaboration

1.  Define MV from a **deterministic** SELECT (or from a stream/table).

2.  Query consumers read the MV like a table (often with additional **indexes**).

3.  A refresh process re-computes or **incrementally updates** the MV from base changes.

4.  Optionally **stagger/jitter** refreshes to avoid thundering herds.


## Consequences

**Benefits**

-   **Low-latency reads** for heavy analytics queries.

-   Decreases **compute** and **I/O** versus recomputing per request.

-   Can be **indexed/partitioned** independently of sources.

-   Enables **isolation**: expensive compute happens off the critical path.


**Liabilities**

-   **Staleness:** MV can lag sources (unless incrementally maintained with strict guarantees).

-   **Storage & maintenance** overhead; refresh adds load.

-   **Complexity:** Incremental maintenance needs keys, change capture, or platform support.

-   Some DBs have **limitations** (e.g., not all SQL features allowed in indexed/materialized views).


## Implementation (Key Points)

-   **Platform specifics**:

    -   **PostgreSQL**: `CREATE MATERIALIZED VIEW`, `REFRESH MATERIALIZED VIEW [CONCURRENTLY]`; no native incremental maintenance (use triggers/CDC or extensions).

    -   **Oracle**: Materialized views with **fast refresh** via materialized view logs (incremental).

    -   **SQL Server**: **Indexed views** (persisted) with constraints; automatically kept up to date.

    -   **BigQuery / Snowflake**: Server-managed materialized views with automatic incremental refresh.

-   **Design for incremental**: Ensure **stable keys** and monotonic measures; maintain **change logs** (MV logs / CDC) for fast refresh.

-   **Index the MV** for common filters/sorts; consider **partitioning** if source is partitioned.

-   **Refresh strategy**:

    -   **On-demand** (manual), **scheduled**, or **event-driven** (after ETL completes).

    -   **CONCURRENT** refresh (where available) to avoid long read locks.

-   **Validation & lineage**: track **last\_refresh\_at**, **source\_watermark**, row counts.

-   **Access control**: grant read-only to consumers; keep base tables protected.


---

## Sample Code (Java 17 + JDBC/PostgreSQL): Create, Index, Refresh, and Query a Materialized View

> Demonstrates:
>
> -   Base tables `orders` and `order_items`
>
> -   MV `mv_daily_revenue_by_product` aggregated by `order_date, product_id`
>
> -   **Concurrent** refresh (Postgres) and indexed MV for fast queries
>
> -   A small “staleness” check with `last_refresh_at`
>

```java
// File: MaterializedViewDemo.java
// Compile: javac MaterializedViewDemo.java
// Run:     java -cp .:postgresql.jar MaterializedViewDemo "jdbc:postgresql://localhost:5432/demo" "demo" "secret"
import java.sql.*;
import java.time.*;
import java.util.*;

public class MaterializedViewDemo {

  public static void main(String[] args) throws Exception {
    if (args.length < 3) {
      System.err.println("Usage: MaterializedViewDemo <jdbcUrl> <user> <password>");
      return;
    }
    try (Connection cx = DriverManager.getConnection(args[0], args[1], args[2])) {
      cx.setAutoCommit(false);
      dropIfExists(cx);
      createBaseSchema(cx);
      seedData(cx);
      createMaterializedView(cx);
      cx.commit();

      // First refresh (populate MV)
      refreshMaterializedView(cx, true); // try concurrent; falls back if unsupported

      // Query the MV
      queryDashboard(cx, LocalDate.now().minusDays(7), LocalDate.now());

      // Insert new data and demonstrate staleness then refresh
      insertOrder(cx, LocalDate.now(), 101, "EUR", new int[]{10, 20}, new int[]{2, 1}, new int[]{1299, 2599});
      cx.commit();

      System.out.println("\nAfter new data, MV is stale:");
      queryDashboard(cx, LocalDate.now().minusDays(7), LocalDate.now());

      System.out.println("\nRefreshing MV...");
      refreshMaterializedView(cx, true);
      queryDashboard(cx, LocalDate.now().minusDays(7), LocalDate.now());
    }
  }

  /* ---------- DDL ---------- */
  static void dropIfExists(Connection cx) throws SQLException {
    try (Statement st = cx.createStatement()) {
      st.execute("DROP MATERIALIZED VIEW IF EXISTS mv_daily_revenue_by_product CASCADE;");
      st.execute("DROP TABLE IF EXISTS order_items;");
      st.execute("DROP TABLE IF EXISTS orders;");
    }
  }

  static void createBaseSchema(Connection cx) throws SQLException {
    try (Statement st = cx.createStatement()) {
      st.execute("""
        CREATE TABLE orders (
          order_id     BIGSERIAL PRIMARY KEY,
          order_date   DATE NOT NULL,
          customer_id  BIGINT NOT NULL,
          currency     VARCHAR(3) NOT NULL DEFAULT 'EUR',
          created_at   TIMESTAMP NOT NULL DEFAULT now()
        );
      """);
      st.execute("""
        CREATE TABLE order_items (
          order_id     BIGINT NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
          product_id   BIGINT NOT NULL,
          quantity     INT NOT NULL,
          unit_price_cents INT NOT NULL,
          PRIMARY KEY(order_id, product_id)
        );
      """);
      st.execute("CREATE INDEX ix_orders_date ON orders(order_date);");
      st.execute("CREATE INDEX ix_items_product ON order_items(product_id);");
    }
  }

  static void createMaterializedView(Connection cx) throws SQLException {
    try (Statement st = cx.createStatement()) {
      // A helper table for metadata
      st.execute("""
        CREATE TABLE mv_metadata (
          name TEXT PRIMARY KEY,
          last_refresh_at TIMESTAMP NOT NULL
        );
      """);
      st.execute("INSERT INTO mv_metadata(name, last_refresh_at) VALUES('mv_daily_revenue_by_product', to_timestamp(0));");

      // The MV itself
      st.execute("""
        CREATE MATERIALIZED VIEW mv_daily_revenue_by_product AS
        SELECT
          o.order_date,
          i.product_id,
          SUM(i.quantity) AS units,
          SUM(i.quantity * i.unit_price_cents) AS revenue_cents
        FROM orders o
        JOIN order_items i USING(order_id)
        GROUP BY o.order_date, i.product_id
        WITH NO DATA; -- populated on first refresh
      """);

      // Indexes on MV for fast filters/sorts
      st.execute("CREATE INDEX ix_mv_dr_date ON mv_daily_revenue_by_product(order_date);");
      st.execute("CREATE INDEX ix_mv_dr_prod ON mv_daily_revenue_by_product(product_id);");
    }
  }

  /* ---------- Seed / Mutations ---------- */
  static void seedData(Connection cx) throws SQLException {
    // Orders for the last few days
    LocalDate today = LocalDate.now();
    insertOrder(cx, today.minusDays(2), 1, "EUR", new int[]{10, 20}, new int[]{1, 2}, new int[]{1299, 2599});
    insertOrder(cx, today.minusDays(1), 2, "EUR", new int[]{10}, new int[]{3}, new int[]{1199});
    insertOrder(cx, today.minusDays(1), 3, "EUR", new int[]{20}, new int[]{1}, new int[]{2599});
  }

  static void insertOrder(Connection cx, LocalDate date, long customerId, String currency,
                          int[] productIds, int[] qtys, int[] pricesCents) throws SQLException {
    long orderId;
    try (PreparedStatement ps = cx.prepareStatement(
      "INSERT INTO orders(order_date, customer_id, currency) VALUES(?,?,?)",
      Statement.RETURN_GENERATED_KEYS)) {
      ps.setDate(1, Date.valueOf(date));
      ps.setLong(2, customerId);
      ps.setString(3, currency);
      ps.executeUpdate();
      try (ResultSet rs = ps.getGeneratedKeys()) { rs.next(); orderId = rs.getLong(1); }
    }
    try (PreparedStatement ps = cx.prepareStatement(
      "INSERT INTO order_items(order_id, product_id, quantity, unit_price_cents) VALUES(?,?,?,?)")) {
      for (int i = 0; i < productIds.length; i++) {
        ps.setLong(1, orderId);
        ps.setInt(2, productIds[i]);
        ps.setInt(3, qtys[i]);
        ps.setInt(4, pricesCents[i]);
        ps.addBatch();
      }
      ps.executeBatch();
    }
  }

  /* ---------- Refresh & Query ---------- */
  static void refreshMaterializedView(Connection cx, boolean tryConcurrent) throws SQLException {
    cx.setAutoCommit(true); // Postgres requires autocommit for some DDL
    try (Statement st = cx.createStatement()) {
      if (tryConcurrent) {
        try {
          st.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_revenue_by_product;");
        } catch (SQLException e) {
          // Fallback if MV has no unique index or server doesn't support concurrent refresh
          System.out.println("Concurrent refresh not available; falling back. Reason: " + e.getMessage());
          st.execute("REFRESH MATERIALIZED VIEW mv_daily_revenue_by_product;");
        }
      } else {
        st.execute("REFRESH MATERIALIZED VIEW mv_daily_revenue_by_product;");
      }
      st.execute("UPDATE mv_metadata SET last_refresh_at = now() WHERE name = 'mv_daily_revenue_by_product';");
    } finally {
      cx.setAutoCommit(false);
    }
  }

  static void queryDashboard(Connection cx, LocalDate from, LocalDate to) throws SQLException {
    // Show staleness info
    try (PreparedStatement ps = cx.prepareStatement("SELECT last_refresh_at FROM mv_metadata WHERE name=?")) {
      ps.setString(1, "mv_daily_revenue_by_product");
      try (ResultSet rs = ps.executeQuery()) {
        if (rs.next()) System.out.println("MV last_refresh_at = " + rs.getTimestamp(1).toInstant());
      }
    }
    System.out.println("Revenue by product between " + from + " and " + to + ":");
    try (PreparedStatement ps = cx.prepareStatement("""
      SELECT order_date, product_id, units, revenue_cents/100.0 AS revenue_eur
      FROM mv_daily_revenue_by_product
      WHERE order_date BETWEEN ? AND ?
      ORDER BY order_date, product_id
    """)) {
      ps.setDate(1, Date.valueOf(from));
      ps.setDate(2, Date.valueOf(to));
      try (ResultSet rs = ps.executeQuery()) {
        while (rs.next()) {
          System.out.printf("%s | product=%d | units=%d | revenue=%.2f%n",
              rs.getDate(1).toLocalDate(), rs.getLong(2), rs.getInt(3), rs.getDouble(4));
        }
      }
    }
  }
}
```

**What this shows**

-   A persisted **MV** over `orders`×`order_items` with **indexes** for typical dashboard filters.

-   **Refresh workflow** (concurrent when possible) and **staleness metadata**.

-   Read path queries the MV at interactive speed instead of redoing joins/aggregations.


> For **incremental** refresh in PostgreSQL, maintain **change tables/logs** (e.g., triggers to append into `orders_log`/`order_items_log`) and implement a fast “merge into MV” procedure; Oracle/SQL Server/modern cloud warehouses provide built-in incremental options.

---

## Known Uses

-   BI dashboards: **daily/weekly KPIs**, revenue, cohort metrics.

-   Search & recommendation serving layers: **precomputed features**.

-   Geospatial tiles / summaries.

-   Data warehouses & lakehouses: **aggregate tables** refreshed by ELT tools (dbt/Airflow).

-   Streaming systems: **materialized state stores** (Kafka Streams, Flink) are the streaming analogue.


## Related Patterns

-   **Cache Aside / Read-Through Cache:** Ephemeral caches vs. persisted, queryable MV.

-   **Aggregate (Summary) Table:** MV materialized as a managed table with custom ETL (manual maintenance).

-   **CQRS / Read Models:** MVs are a form of read model; CQRS clarifies ownership and update flow.

-   **Index Partitioning:** Partition MVs for pruning/retention when data is time-partitioned.

-   **View (Logical):** Non-persisted; always fresh but recomputes on every read.


---

### Practical Tips

-   Add a **unique index** on MV keys to enable **CONCURRENTLY** refresh (Postgres) and faster lookups.

-   Track **freshness** explicitly (`last_refresh_at`, **source watermark**); expose it to users.

-   Size refresh windows and **schedule** them to avoid peak times; add **jitter** for fleets.

-   For incremental maintenance: ensure **stable keys**, capture **inserts/updates/deletes**, and **upsert** into the MV.

-   Consider **partitioned MVs** (or summary tables) for large, time-based data; refresh only the **latest** partition.

-   Secure MVs as **read-only** to consumers; restrict base tables.

-   Monitor: refresh duration, blocking/waits, MV size vs. base, and query hit rates.
