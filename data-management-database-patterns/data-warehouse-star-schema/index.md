
# Data Management & Database Pattern — Data Warehouse Star Schema

## Pattern Name and Classification

-   **Name:** Data Warehouse Star (Star Schema)

-   **Classification:** Dimensional modeling pattern for analytical databases (schema-on-write, denormalized reads)


## Intent

Organize analytical data around a central **Fact** table of numeric, additive **measures** and multiple surrounding **Dimension** tables with descriptive **attributes**. The star layout simplifies querying, encourages fast scans, and maps naturally to business questions (who/what/when/where/how).

## Also Known As

-   Star Schema

-   Dimensional Model (Kimball)

-   Facts and Dimensions


## Motivation (Forces)

-   **Analysts ask questions** that slice and dice the same core facts by many descriptors (e.g., sales by product, by customer, by month).

-   **Query simplicity & speed:** Denormalized dimensions reduce joins depth; columnar engines compress repeated attributes well.

-   **History handling:** Dimensions may **slowly change** (SCD types), while facts are append-only.

-   **Trade-offs:** Star favors read performance and clarity over write normalization; ETL must maintain surrogate keys, SCDs, and data quality.


## Applicability

Use a star schema when:

-   You need **OLAP**\-style reporting, dashboards, and ad-hoc analytics.

-   Facts are **additive/semi-additive** and queried across multiple contexts.

-   You want **stable** query patterns (BI tools, cubes, SQL).


Avoid/Adapt when:

-   Highly normalized **OLTP** with many small updates/transactions.

-   Complex **many-to-many** relationships dominate (often use bridge tables or snowflake selectively).

-   Data is small and agility trumps structure (then start in the lake, materialize stars later).


## Structure

```lua
+--------------------+
                 |    DimDate         |
                 |  (date_key PK)     |
                 +--------------------+
                         ▲
+--------------------+   │   +--------------------+     +--------------------+
|  DimCustomer       |   │   |   FactSales        |     |   DimProduct       |
| (customer_key PK)  ◄───┼──►| (date_key  FK)     |◄────| (product_key PK)   |
|  attributes...     |   │   | (customer_key FK)  |     |  attributes...     |
+--------------------+   │   | (product_key  FK)  |     +--------------------+
                         │   | measures: qty, amt |
                         │   +--------------------+
```

## Participants

-   **Fact Table:** Grain = one event at a chosen level (e.g., one order line). Columns: foreign keys to dimensions + **measures** (numeric, additive).

-   **Dimension Tables:** Surrogate **keys** + textual attributes (hierarchies, categories, dates, etc.).

-   **Surrogate Keys:** Integer keys insulating facts from natural-key drift and enabling SCDs.

-   **ETL/ELT Pipelines:** Populate dimensions (incl. SCD) and facts; enforce grain and referential integrity.

-   **BI/Query Layer:** SQL, cubes, semantic models (e.g., LookML/semantic layer).


## Collaboration

1.  **Stage/land** source data.

2.  **Load/merge dimensions:** look up by natural key, assign **surrogate keys**, handle SCD (Type 1/2).

3.  **Load facts:** at defined **grain**, join staged facts to dimension surrogate keys, compute measures, insert.

4.  **Query:** analysts aggregate facts grouped by dimension attributes.


## Consequences

**Benefits**

-   Simple, readable SQL; predictable joins.

-   Excellent compression & scan speeds in columnar stores; great for **aggregation**.

-   Clear **grain** and **business alignment** reduce ambiguity.


**Liabilities**

-   ETL complexity (keys, SCD, conformance).

-   Potential **duplication** of descriptive data across dimensions.

-   Changes to grain or dimensions can require **backfills**.


## Implementation (Key Points)

-   **Choose the grain first** (e.g., “one row per order line”). Everything else follows.

-   **Surrogate keys** are integers; keep natural keys as attributes for lineage & dedupe.

-   **Dates**: use a **Date dimension** (or generated calendar) for flexible calendars, holidays, fiscal periods.

-   **SCD policy**:

    -   Type 1 (overwrite) for corrections;

    -   Type 2 (history) for analysis across time (add `valid_from`, `valid_to`, `is_current`).

-   **Conformed dimensions** shared across facts for cross-domain analysis.

-   **Performance**: partition facts by date, sort by frequently filtered keys, use columnar formats and summary aggregates where needed.

-   **Quality**: enforce referential integrity (as constraints or during load), dedupe Stage → Dim, validate grain.


---

## Sample Code (Java 17): Mini Star Schema with JDBC (H2), ETL & Query

> Demonstrates:
>
> -   Creating **DimProduct**, **DimCustomer**, **DimDate**, and **FactSales**
>
> -   **Type 1** dimension upsert with surrogate keys
>
> -   Loading facts at “order line” grain
>
> -   A star **query**: revenue by month & product category  
      >     *(Use any JDBC DB; this example uses H2 in-memory for simplicity.)*
>

```java
// File: StarSchemaDemo.java
// Compile: javac -cp h2.jar StarSchemaDemo.java
// Run:     java -cp .:h2.jar StarSchemaDemo
import java.sql.*;
import java.time.LocalDate;
import java.util.*;

public class StarSchemaDemo {

  public static void main(String[] args) throws Exception {
    try (Connection cx = DriverManager.getConnection("jdbc:h2:mem:dw;DB_CLOSE_DELAY=-1")) {
      cx.setAutoCommit(false);
      createSchema(cx);
      seedDimDate(cx, 2025, 2026);
      // Upsert some dimension members (Type 1)
      int prodA = upsertDimProduct(cx, "P-100", "Gizmo", "Gadgets");
      int prodB = upsertDimProduct(cx, "P-200", "Widget", "Widgets");
      int cust1 = upsertDimCustomer(cx, "CUST-1", "Alice", "AT");
      int cust2 = upsertDimCustomer(cx, "CUST-2", "Bob",   "DE");

      // Load a few facts (order lines)
      insertFactSale(cx, LocalDate.of(2025, 9, 30), cust1, prodA, 2, 1299); // €12.99 each
      insertFactSale(cx, LocalDate.of(2025,10, 1), cust1, prodB, 1, 2599);
      insertFactSale(cx, LocalDate.of(2025,10, 1), cust2, prodA, 3, 1099);
      insertFactSale(cx, LocalDate.of(2025,10, 2), cust2, prodB, 5,  899);
      cx.commit();

      // Example star query: revenue by month & product category
      try (PreparedStatement ps = cx.prepareStatement("""
        SELECT d.year || '-' || LPAD(CAST(d.month AS VARCHAR),2,'0') AS year_month,
               p.category,
               SUM(f.quantity) AS units,
               SUM(f.quantity * f.unit_price_cents)/100.0 AS revenue_eur
        FROM FactSales f
        JOIN DimDate d     ON f.date_key = d.date_key
        JOIN DimProduct p  ON f.product_key = p.product_key
        GROUP BY 1, 2
        ORDER BY 1, 2
      """)) {
        ResultSet rs = ps.executeQuery();
        System.out.println("year_month | category | units | revenue_eur");
        while (rs.next()) {
          System.out.printf("%-10s | %-8s | %5d | %10.2f%n",
              rs.getString(1), rs.getString(2), rs.getInt(3), rs.getDouble(4));
        }
      }
    }
  }

  /* ---------- Schema ---------- */
  static void createSchema(Connection cx) throws SQLException {
    try (Statement st = cx.createStatement()) {
      st.execute("""
        CREATE TABLE DimDate (
          date_key     INT PRIMARY KEY,        -- yyyymmdd
          full_date    DATE NOT NULL,
          year         INT NOT NULL,
          quarter      INT NOT NULL,
          month        INT NOT NULL,
          day_of_month INT NOT NULL,
          day_of_week  INT NOT NULL,
          is_weekend   BOOLEAN NOT NULL
        );
      """);
      st.execute("""
        CREATE TABLE DimProduct (
          product_key   INT AUTO_INCREMENT PRIMARY KEY,
          product_code  VARCHAR(64) UNIQUE NOT NULL,   -- natural key
          product_name  VARCHAR(255) NOT NULL,
          category      VARCHAR(64) NOT NULL
        );
      """);
      st.execute("""
        CREATE TABLE DimCustomer (
          customer_key  INT AUTO_INCREMENT PRIMARY KEY,
          customer_code VARCHAR(64) UNIQUE NOT NULL,   -- natural key
          customer_name VARCHAR(255) NOT NULL,
          country_code  VARCHAR(2) NOT NULL
        );
      """);
      st.execute("""
        CREATE TABLE FactSales (
          date_key     INT NOT NULL,
          customer_key INT NOT NULL,
          product_key  INT NOT NULL,
          quantity     INT NOT NULL,
          unit_price_cents INT NOT NULL,
          -- optional degenerate fields: order_id, etc.
          CONSTRAINT fk_sales_date     FOREIGN KEY (date_key)     REFERENCES DimDate(date_key),
          CONSTRAINT fk_sales_customer FOREIGN KEY (customer_key) REFERENCES DimCustomer(customer_key),
          CONSTRAINT fk_sales_product  FOREIGN KEY (product_key)  REFERENCES DimProduct(product_key)
        );
      """);
      st.execute("CREATE INDEX ix_sales_date ON FactSales(date_key);");
      st.execute("CREATE INDEX ix_sales_prod ON FactSales(product_key);");
      st.execute("CREATE INDEX ix_sales_cust ON FactSales(customer_key);");
    }
  }

  /* ---------- Dim loaders (Type 1 upsert) ---------- */
  static int upsertDimProduct(Connection cx, String code, String name, String cat) throws SQLException {
    Integer key = lookupKey(cx, "SELECT product_key FROM DimProduct WHERE product_code = ?", code);
    if (key != null) {
      try (PreparedStatement ps = cx.prepareStatement(
          "UPDATE DimProduct SET product_name=?, category=? WHERE product_key=?")) {
        ps.setString(1, name); ps.setString(2, cat); ps.setInt(3, key); ps.executeUpdate();
      }
      return key;
    } else {
      try (PreparedStatement ps = cx.prepareStatement(
          "INSERT INTO DimProduct(product_code, product_name, category) VALUES(?,?,?)",
          Statement.RETURN_GENERATED_KEYS)) {
        ps.setString(1, code); ps.setString(2, name); ps.setString(3, cat); ps.executeUpdate();
        try (ResultSet rs = ps.getGeneratedKeys()) { rs.next(); return rs.getInt(1); }
      }
    }
  }

  static int upsertDimCustomer(Connection cx, String code, String name, String country) throws SQLException {
    Integer key = lookupKey(cx, "SELECT customer_key FROM DimCustomer WHERE customer_code = ?", code);
    if (key != null) {
      try (PreparedStatement ps = cx.prepareStatement(
          "UPDATE DimCustomer SET customer_name=?, country_code=? WHERE customer_key=?")) {
        ps.setString(1, name); ps.setString(2, country); ps.setInt(3, key); ps.executeUpdate();
      }
      return key;
    } else {
      try (PreparedStatement ps = cx.prepareStatement(
          "INSERT INTO DimCustomer(customer_code, customer_name, country_code) VALUES(?,?,?)",
          Statement.RETURN_GENERATED_KEYS)) {
        ps.setString(1, code); ps.setString(2, name); ps.setString(3, country); ps.executeUpdate();
        try (ResultSet rs = ps.getGeneratedKeys()) { rs.next(); return rs.getInt(1); }
      }
    }
  }

  static Integer lookupKey(Connection cx, String sql, String code) throws SQLException {
    try (PreparedStatement ps = cx.prepareStatement(sql)) {
      ps.setString(1, code);
      ResultSet rs = ps.executeQuery();
      return rs.next() ? rs.getInt(1) : null;
    }
  }

  /* ---------- Date dimension (pre-populate) ---------- */
  static void seedDimDate(Connection cx, int startYear, int endYear) throws SQLException {
    try (PreparedStatement ps = cx.prepareStatement("""
      INSERT INTO DimDate(date_key, full_date, year, quarter, month, day_of_month, day_of_week, is_weekend)
      VALUES(?,?,?,?,?,?,?,?)
    """)) {
      LocalDate d = LocalDate.of(startYear, 1, 1);
      LocalDate end = LocalDate.of(endYear, 12, 31);
      while (!d.isAfter(end)) {
        int dateKey = d.getYear()*10000 + d.getMonthValue()*100 + d.getDayOfMonth();
        ps.setInt(1, dateKey);
        ps.setDate(2, Date.valueOf(d));
        ps.setInt(3, d.getYear());
        ps.setInt(4, (d.getMonthValue()-1)/3 + 1);
        ps.setInt(5, d.getMonthValue());
        ps.setInt(6, d.getDayOfMonth());
        ps.setInt(7, d.getDayOfWeek().getValue());
        ps.setBoolean(8, d.getDayOfWeek().getValue() >= 6);
        ps.addBatch();
        // flush periodically
        if (dateKey % 200 == 0) ps.executeBatch();
        d = d.plusDays(1);
      }
      ps.executeBatch();
    }
  }

  /* ---------- Fact loader ---------- */
  static void insertFactSale(Connection cx, LocalDate date, int customerKey, int productKey,
                             int qty, int unitPriceCents) throws SQLException {
    int dateKey = date.getYear()*10000 + date.getMonthValue()*100 + date.getDayOfMonth();
    try (PreparedStatement ps = cx.prepareStatement("""
      INSERT INTO FactSales(date_key, customer_key, product_key, quantity, unit_price_cents)
      VALUES(?,?,?,?,?)
    """)) {
      ps.setInt(1, dateKey);
      ps.setInt(2, customerKey);
      ps.setInt(3, productKey);
      ps.setInt(4, qty);
      ps.setInt(5, unitPriceCents);
      ps.executeUpdate();
    }
  }
}
```

**Notes about the example**

-   Uses a **Date dimension** with integer `date_key` = `yyyymmdd`.

-   **Dim loaders** implement **SCD Type 1** (overwrite) for brevity; switch to **Type 2** by adding `valid_from/valid_to/is_current` and joining on `date_key ∈ [valid_from, valid_to)`.

-   Facts record **quantities** and **unit prices** (in cents); revenue is `qty * unit_price_cents`.


---

## Known Uses

-   Most enterprise BI warehouses (Snowflake, BigQuery, Redshift, Synapse, Vertica).

-   Retail: **Sales** facts with **Product**, **Customer**, **Store**, **Date** dimensions.

-   Finance: **Transactions** or **Positions** with **Account**, **Instrument**, **Calendar**.

-   Web analytics: **Page Views** with **User**, **Device**, **Channel**, **Date**.


## Related Patterns

-   **Snowflake Schema:** Normalize some dimensions to reduce duplication (at cost of extra joins).

-   **Aggregate (Summary) Facts:** Pre-computed rollups at coarser grain (daily product sales).

-   **Conformed Dimensions:** Shared dimensions across stars for cross-domain analysis.

-   **Data Vault:** Modeling pattern better for ingestion agility; stars are often **published** from vaults.

-   **Slowly Changing Dimensions (SCD):** Techniques for recording dimension history.

-   **Lakehouse Tables:** Store star tables on a data lake with ACID table formats (Delta/Iceberg/Hudi).


---

### Practical Tips

-   **Define the grain first** and never mix grains in one fact.

-   Prefer **surrogate integer keys**; keep natural keys for lineage.

-   Add **degenerate dimensions** (e.g., `order_id`) to the fact when useful for drill-through.

-   Use **columnar storage & clustering** on common filters (date, product).

-   Implement **SCD** deliberately: pick Type 1 vs. Type 2 per attribute.

-   Keep **conformed dimensions** consistent across stars to enable cross-fact analysis.

-   For performance, consider **summary tables/materialized views** for top BI queries.
