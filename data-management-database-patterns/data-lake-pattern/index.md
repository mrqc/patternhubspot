
# Data Management & Database Pattern — Data Lake

## Pattern Name and Classification

-   **Name:** Data Lake

-   **Classification:** Storage & analytics architecture (schema-on-read, multi-format, multi-tenant data platform)


## Intent

Centralize **raw and refined data**—structured, semi-structured, and unstructured—on **cheap, scalable object storage**, keep it **immutable** by default, and let **many engines** read/process it using **schema-on-read** (optionally adding table formats for ACID). Optimize for **ingest first**, discover & govern later.

## Also Known As

-   Raw Zone + Curated Zone (Bronze/Silver/Gold)

-   Data Lakehouse (when combined with ACID table formats)

-   Landing Zone (for just the raw layer)


## Motivation (Forces)

-   **Heterogeneity:** Sources arrive as CSV/JSON/Avro/Parquet, logs, images, binaries.

-   **Scale & cost:** Object stores (S3/ADLS/GCS) scale elastically and are inexpensive.

-   **Decoupling:** Storage is decoupled from compute; pick Spark, Presto/Trino, Flink, Snowflake, etc.

-   **Evolvability:** Use **schema-on-read** to avoid upfront rigid modeling; add/merge schemas later.

-   **Governance vs. agility:** Need discoverability, lineage, PII controls; avoid becoming a “data swamp”.


## Applicability

Use a Data Lake when:

-   You ingest **many sources** at different cadences (batch + streaming).

-   Your analytics/ML needs **historical** and **raw** detail, not just curated warehouses.

-   You want **multiple query engines** (SQL, notebooks, ML pipelines) over the same data.


Avoid / adapt when:

-   You only need **curated BI** on stable schemas → a warehouse alone may suffice.

-   You require **strict OLTP semantics** (row-level transactions, millisecond latency).

-   Governance maturity is low—without metadata & policies, lakes degrade into swamps.


## Structure

```pgsql
+--------------------+                 +--------------------------+
Ingestion| Batch  | Streams   |----> Bronze --->|  Immutable raw landing   |
         +--------------------+                 +--------------------------+
                   |                                  |
                   v                                  v
             Transform/Validate                 Enrich/Normalize
                   |                                  |
                   v                                  v
               Silver (clean,                      Gold (serving-ready,
               conformed)                          denormalized, KPIs)
                   \                                   /
                    \                                 /
                     +------------ Catalog -----------+
                                  (schemas, partitions, table/column metadata)
                                      |
                         +------------+-------------+
                         |                          |
                Compute Engines               Governance/Observability
           (Spark, Trino, Flink, …)       (policies, lineage, quality)
```

## Participants

-   **Object Store:** Durable files/objects; versioning & lifecycle policies.

-   **Zones:**

    -   **Bronze (raw):** Append-only, immutable copies.

    -   **Silver (refined):** Cleaned/conformed data (e.g., Parquet with partitions).

    -   **Gold (serving):** Aggregated/denormalized for BI/ML features.

-   **Catalog/Metastore:** Schemas, partitions, locations (Hive Metastore, Glue, Unity/Schema Registry).

-   **Table Format (optional but popular):** Delta Lake / Apache Iceberg / Apache Hudi for ACID, schema evolution, time travel.

-   **Ingestion:** Batch loaders, CDC, streaming connectors (Kafka, Debezium, NiFi).

-   **Processing Engines:** Spark, Flink, Trino/Presto, Hive, Dask, DuckDB, etc.

-   **Governance:** Data quality, lineage, access controls (row/column-level), retention.


## Collaboration

1.  **Ingest** copies raw data into **Bronze** (partitioned, immutable).

2.  **Transform/clean** into **Silver** (columnar formats, partitioned by date/keys).

3.  **Aggregate/serve** into **Gold** (subject-oriented marts, features).

4.  **Catalog** registers tables/partitions so engines can discover them.

5.  **Query engines** perform schema-on-read; **governance** enforces policies.

6.  **Optimization** (compaction, clustering, Z-order) runs as background jobs.


## Consequences

**Benefits**

-   **Cheap, scalable storage** decoupled from compute.

-   **Flexibility:** Multiple formats and engines; schema evolves over time.

-   **Reusability:** Same raw data powers analytics, ML, and ad hoc exploration.

-   **Time travel & ACID** (with modern table formats).


**Liabilities**

-   Risk of **data swamp** without curation & metadata.

-   **Eventual consistency** in object stores; careful with multi-writer jobs.

-   **Small files** & fragmentation hurt performance; needs compaction.

-   **Security/compliance** complexity due to broad access and duplication.


## Implementation (Key Points)

-   **File formats:** Prefer **columnar** (Parquet/ORC) for analytics; JSON/CSV only at the edge.

-   **Partitioning:** Date (ingest/transaction date) + high-cardinality keys (country, tenant). Avoid over-partitioning.

-   **ACID tables:** Use **Delta/Iceberg/Hudi** for merges, deletes, schema evolution, snapshots.

-   **Catalog:** Hive/Glue/Unity; keep schemas and partition metadata authoritative.

-   **Quality/lineage:** Great Expectations, Deequ, OpenLineage; capture data contracts.

-   **Optimization:** Compact small files, sort/cluster, bloom filters, column stats.

-   **Security:** Bucket-level + table/column-level ACLs, tokenized PII, encryption (KMS), row filters.

-   **Streaming:** Upsert/merge with CDC; watermarking & late-arriving handling.

-   **Lifecycle:** Retention/archival tiers, versioning, reproducible rebuilds from Bronze.


---

## Sample Code (Java 17): Mini Data Lake on Local FS (Bronze→Silver→Gold)

> Educational, zero-dependency demo that:
>
> -   Ingests **CSV** orders into **Bronze** with date partitions
>
> -   Transforms to **Silver** (cleaned CSV) and writes a simple **manifest** (a stand-in for a catalog)
>
> -   Runs a basic **query** over partition predicates to produce a **Gold** daily revenue table
>

```java
// File: MiniDataLake.java
// Compile: javac MiniDataLake.java
// Run:     java MiniDataLake
import java.io.*;
import java.nio.file.*;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.stream.*;

public class MiniDataLake {

  /* --------- Lake layout --------- */
  static class Lake {
    final Path root, bronze, silver, gold, manifest;
    Lake(Path root) throws IOException {
      this.root = root;
      this.bronze = root.resolve("bronze");
      this.silver = root.resolve("silver");
      this.gold   = root.resolve("gold");
      this.manifest = root.resolve("_manifest");
      Files.createDirectories(bronze);
      Files.createDirectories(silver);
      Files.createDirectories(gold);
      Files.createDirectories(manifest);
    }
  }

  /* --------- Simple record model --------- */
  // CSV schema: order_id, ts_iso8601, country, amount_cents
  record Order(String id, LocalDateTime ts, String country, long amountCents) {}

  /* --------- Bronze ingestion (append-only) --------- */
  static Path ingestToBronze(Lake lake, List<Order> orders) throws IOException {
    // Partition by date=YYYY-MM-DD
    Map<LocalDate, List<Order>> byDate = orders.stream()
      .collect(Collectors.groupingBy(o -> o.ts().toLocalDate()));

    DateTimeFormatter df = DateTimeFormatter.ISO_DATE;
    Path lastFile = null;
    for (var e : byDate.entrySet()) {
      LocalDate d = e.getKey();
      Path dir = lake.bronze.resolve("date=" + df.format(d));
      Files.createDirectories(dir);
      Path file = dir.resolve("orders_" + System.nanoTime() + ".csv");
      try (BufferedWriter w = Files.newBufferedWriter(file)) {
        for (Order o : e.getValue()) {
          w.write("%s,%s,%s,%d%n".formatted(o.id(), o.ts(), o.country(), o.amountCents()));
        }
      }
      lastFile = file;
    }
    return lastFile;
  }

  /* --------- Silver transform (clean + normalize) --------- */
  static void bronzeToSilver(Lake lake) throws IOException {
    // For demo: copy CSV → CSV while filtering negatives and normalizing country to upper-case.
    // Also create a tiny manifest listing partitions/files (simulating a catalog).
    List<String> entries = new ArrayList<>();

    try (Stream<Path> parts = Files.walk(lake.bronze)) {
      for (Path p : parts.filter(Files::isRegularFile).filter(f -> f.toString().endsWith(".csv")).toList()) {
        String partition = p.getParent().getFileName().toString(); // e.g., "date=2025-09-20"
        Path outDir = lake.silver.resolve(partition);
        Files.createDirectories(outDir);
        Path out = outDir.resolve(p.getFileName().toString().replace("orders_", "orders_clean_"));

        try (BufferedReader r = Files.newBufferedReader(p);
             BufferedWriter w = Files.newBufferedWriter(out)) {
          String line;
          while ((line = r.readLine()) != null) {
            String[] a = line.split(",", -1);
            if (a.length != 4) continue; // drop bad rows
            String id = a[0].trim();
            String ts = a[1].trim();
            String country = a[2].trim().toUpperCase(Locale.ROOT);
            long cents = Long.parseLong(a[3].trim());
            if (cents < 0) continue; // basic quality gate
            w.write("%s,%s,%s,%d%n".formatted(id, ts, country, cents));
          }
        }
        entries.add(partition + "/" + out.getFileName());
      }
    }

    // Write manifest per table (orders)
    Path manifest = lake.manifest.resolve("orders_silver_manifest.txt");
    try (BufferedWriter w = Files.newBufferedWriter(manifest)) {
      w.write("# table=orders_silver format=csv columns=order_id,ts,country,amount_cents\n");
      for (String e : entries) w.write(e + "\n");
    }
  }

  /* --------- Query engine (very small) producing Gold daily revenue by country --------- */
  static void buildGoldDailyRevenue(Lake lake, LocalDate from, LocalDate to) throws IOException {
    DateTimeFormatter df = DateTimeFormatter.ISO_DATE;
    Map<String, Long> agg = new HashMap<>(); // key: date|country

    // Pushdown: only scan partitions within [from, to]
    try (Stream<Path> parts = Files.list(lake.silver)) {
      for (Path partDir : parts.filter(Files::isDirectory).toList()) {
        String partName = partDir.getFileName().toString(); // "date=YYYY-MM-DD"
        if (!partName.startsWith("date=")) continue;
        LocalDate d = LocalDate.parse(partName.substring(5));
        if (d.isBefore(from) || d.isAfter(to)) continue;

        try (Stream<Path> files = Files.list(partDir)) {
          for (Path f : files.filter(Files::isRegularFile).filter(x -> x.toString().endsWith(".csv")).toList()) {
            try (BufferedReader r = Files.newBufferedReader(f)) {
              String line;
              while ((line = r.readLine()) != null) {
                String[] a = line.split(",", -1);
                if (a.length != 4) continue;
                String ts = a[1];
                String country = a[2];
                long cents = Long.parseLong(a[3]);
                // derive date from partition (faster) instead of parsing ts
                String key = df.format(d) + "|" + country;
                agg.merge(key, cents, Long::sum);
              }
            }
          }
        }
      }
    }

    // Write a Gold table as CSV
    Path out = lake.gold.resolve("daily_revenue_by_country.csv");
    try (BufferedWriter w = Files.newBufferedWriter(out)) {
      w.write("date,country,revenue_cents\n");
      agg.entrySet().stream()
         .sorted(Map.Entry.comparingByKey())
         .forEach(e -> {
           String[] k = e.getKey().split("\\|");
           try {
             w.write("%s,%s,%d%n".formatted(k[0], k[1], e.getValue()));
           } catch (IOException ex) { throw new UncheckedIOException(ex); }
         });
    }
    System.out.println("Gold written: " + out.toAbsolutePath());
  }

  /* --------- Demo --------- */
  public static void main(String[] args) throws Exception {
    Path root = Paths.get("lake_demo");
    Lake lake = new Lake(root);

    // 1) Ingest bronze
    LocalDate today = LocalDate.now();
    List<Order> sample = List.of(
      new Order("o1", LocalDateTime.of(today.minusDays(1), LocalTime.of(10, 15)), "at", 1299),
      new Order("o2", LocalDateTime.of(today.minusDays(1), LocalTime.of(11, 5)),  "de", 2599),
      new Order("o3", LocalDateTime.of(today,            LocalTime.of(9, 45)),   "at",  999),
      new Order("o4", LocalDateTime.of(today,            LocalTime.of(12, 30)),  "us", 4599),
      new Order("o5", LocalDateTime.of(today,            LocalTime.of(13, 00)),  "de", -50) // filtered
    );
    ingestToBronze(lake, sample);

    // 2) Transform to silver with a tiny manifest
    bronzeToSilver(lake);

    // 3) Build a gold aggregate (last 2 days)
    buildGoldDailyRevenue(lake, today.minusDays(1), today);

    // 4) Show where things landed
    System.out.println("Lake root: " + root.toAbsolutePath());
    try (Stream<Path> s = Files.walk(root)) {
      s.forEach(p -> System.out.println(" - " + root.relativize(p)));
    }
  }
}
```

**What this illustrates**

-   **Partitioned layout** by date (`date=YYYY-MM-DD`).

-   A **Bronze→Silver→Gold** flow with cleaning and a tiny **manifest** (catalog stand-in).

-   A very small **query engine** that **pushes down** partition predicates and writes a Gold aggregate.


> Production swaps CSV & manual manifests for **Parquet/ORC** and a real **catalog** + **table format** (Delta/Iceberg/Hudi), with Spark/Trino/Flink doing the heavy lifting.

---

## Known Uses

-   **AWS:** S3 + Glue Catalog + Athena/EMR (Spark) + Lake Formation.

-   **Azure:** ADLS Gen2 + Synapse/Databricks + Purview (governance).

-   **GCP:** GCS + BigQuery external tables + Dataproc/Dataplex.

-   **Open-source “lakehouse”:** Delta Lake / Apache Iceberg / Apache Hudi with Spark/Trino/Flint.

-   **Analytics/ML platforms:** Store raw events (Bronze), features & training sets (Silver/Gold).


## Related Patterns

-   **Data Warehouse:** Curated, schema-on-write; often complements the lake (Gold → DW).

-   **Lakehouse (ACID on lakes):** Adds table transactions/time travel (Delta/Iceberg/Hudi).

-   **CDC / Outbox:** Feed changes from OLTP into the lake.

-   **Materialized Views:** Gold tables exposed for BI.

-   **Data Mesh:** Federated governance/product thinking atop a shared lake platform.

-   **Event Sourcing:** Event logs as durable Bronze; projections build Silver/Gold.


---

### Practical Tips

-   Treat **Bronze as immutable**; rebuild downstream when rules change.

-   Prefer **columnar** + **compression**; keep **row groups** large enough for scan efficiency.

-   Watch for **small files**; schedule **compaction**.

-   **Partition carefully**: date + low-to-medium cardinality keys; avoid deep directories.

-   Adopt an **ACID table format** early if you need **MERGE/DELETE** and **schema evolution**.

-   Invest in **catalog + lineage + quality** to avoid a swamp (profiling, tests, contracts).

-   Security first: **PII tagging**, **tokenization**, and **governed access** per zone and table.
