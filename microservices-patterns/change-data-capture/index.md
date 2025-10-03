# Change Data Capture — Microservice Pattern

## Pattern Name and Classification

**Name:** Change Data Capture (CDC)  
**Classification:** Microservices / Data Integration & Eventing / Log-based Replication

## Intent

Continuously **capture committed data changes** from a system of record (database/write store) and **publish them as events/records** to downstream consumers—without changing application code—so read models, caches, search indexes, analytics, and other services stay in sync **near-real-time**.

## Also Known As

-   Database Log Tail / Binlog Streaming
    
-   Logical Replication
    
-   Eventing from the Database
    
-   Streaming ETL
    

## Motivation (Forces)

-   **Avoid dual writes:** Updating a DB *and* emitting an event from the app can drift (crash windows, retries).
    
-   **Low-touch integration:** You can’t (or don’t want to) modify legacy apps to publish events.
    
-   **Timeliness:** Batch ETL is too slow; you need seconds, not hours.
    
-   **Scalability:** Derived stores (search, cache, read models, data lake) must track source changes efficiently.
    
-   **Auditability:** Transaction logs provide an authoritative, ordered history of changes.
    

**Tensions**

-   **Leakage of internal schema:** Raw CDC mirrors tables/columns that are *not* stable domain contracts.
    
-   **Privacy/PII:** Replicating sensitive columns to many consumers increases risk.
    
-   **Schema evolution:** Source schema changes ripple unless mediated.
    
-   **Exactly-once:** Brokers are at-least-once; duplicates and reordering must be handled.
    

## Applicability

Use CDC when:

-   You need **near real-time** propagation of DB changes to other services/stores.
    
-   You cannot easily add an application-level outbox/emitter (legacy monolith, 3rd-party).
    
-   You want to **decouple** read models/analytics from transactional workload.
    

Be cautious when:

-   The source DB is under heavy write load and CDC would contend for IO or retention.
    
-   You need **domain events** (behavioral) rather than **data-change** events; add a translator layer.
    
-   Cross-aggregate invariants matter; raw row events don’t encode business intent.
    

## Structure

-   **Source Database**: Emits a **transaction log** (WAL/binlog/redo).
    
-   **CDC Connector**: Reads the log, converts to a change envelope (create/update/delete, before/after, metadata).
    
-   **Transport / Broker**: Publishes change events (Kafka/Pulsar/SQS, etc.).
    
-   **Schema Registry (optional)**: Manages Avro/Protobuf/JSON schemas & compatibility.
    
-   **Processors/Consumers**: Transform, filter, and project into caches/search/read models/data lake.
    
-   **Offsets/Checkpoints**: Allow resume from the correct log position.
    
-   **DLQ/Quarantine**: For malformed or failing records.
    

```css
[App + DB Tx] -> [DB WAL/binlog] -> [CDC Connector] -> [Broker Topics] -> [Consumers/Projections]
```

## Participants

-   **Source DB** (PostgreSQL WAL, MySQL binlog, Oracle redo, SQL Server CDC).
    
-   **CDC Connector/Engine** (e.g., Debezium, native logical replication, GoldenGate, DMS).
    
-   **Broker** (Kafka, Pulsar, etc.).
    
-   **Schema Registry** (optional but recommended).
    
-   **Transformer/ACL** (maps raw rows to domain contracts, redacts PII).
    
-   **Consumers** (materialized views, search indexers, caches, analytics).
    
-   **Observability** (lag, commit latency, error rates).
    

## Collaboration

1.  Application commits a transaction → DB appends to its **log**.
    
2.  CDC connector tails the log, **parses changes**, and emits a structured **envelope** (`op`, `before`, `after`, `ts_ms`, source).
    
3.  Events are published to topics/streams (often one per table or aggregate).
    
4.  Consumers process events idempotently, update derived stores, or **translate** to domain events.
    
5.  Offsets are persisted; on restart the connector resumes exactly at last processed position.
    

## Consequences

**Benefits**

-   **Near-real-time** propagation with **no app code changes**.
    
-   Eliminates dual-write hazards; source of truth remains the DB.
    
-   Replayable history for backfills and audits.
    
-   Scales read workloads by moving them to specialized stores.
    

**Liabilities**

-   Emits **data-centric** events (row diffs), not domain semantics—usually needs a mapping layer.
    
-   Careful handling of **PII/security** and **schema evolution** is mandatory.
    
-   Infrastructure complexity (connectors, offsets, registry, monitoring).
    
-   Potential **load** on the source DB (replication slots, retention, snapshots).
    

## Implementation

**Key practices**

-   **Prefer log-based CDC** (WAL/binlog/redo) over polling or triggers (lower overhead, exact ordering).
    
-   **Snapshot policy:** initial full snapshot, then streaming. Plan for re-snapshotting large tables.
    
-   **Topic & partitioning:** typically per table; key by primary key to preserve per-row ordering.
    
-   **Envelope mapping:** `op` in {`c` create, `u` update, `d` delete, `r` snapshot}; include `before`/`after`.
    
-   **Schema evolution:** Use Schema Registry; enforce backward-compatible changes.
    
-   **Transform/ACL:** Don’t leak internal schemas. Redact or hash PII at the **connector** or first hop.
    
-   **Idempotency:** Consumers should upsert by key/version; de-duplicate using `(table, pk, lsn/commit_ts)`.
    
-   **Backpressure:** Tune batch sizes, fetch intervals, heartbeat intervals.
    
-   **Ops:** Monitor replication **lag**, connector **errors**, and oldest unreplicated **LSN/binlog**.
    
-   **DB migrations:** Use **expand/contract** so both old and new schemas work during rollout.
    

---

## Sample Code (Java) — **Debezium Embedded** (PostgreSQL) → **Kafka**

> This compact example runs a Debezium **embedded engine** inside your JVM to capture Postgres changes and forward a **sanitized JSON envelope** to Kafka.  
> In production, most teams run Debezium on **Kafka Connect**; using the embedded engine is handy for custom routing or lightweight deployments.

```java
// build.gradle (essentials)
// implementation 'io.debezium:debezium-embedded:2.6.1.Final'   // version example
// implementation 'io.debezium:debezium-connector-postgres:2.6.1.Final'
// implementation 'org.apache.kafka:kafka-clients:3.7.0'
// implementation 'com.fasterxml.jackson.core:jackson-databind:2.17.1'

import io.debezium.engine.DebeziumEngine;
import io.debezium.engine.format.ChangeEventFormat;
import io.debezium.engine.ChangeEvent;
import org.apache.kafka.clients.producer.*;
import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.util.Properties;
import java.util.concurrent.Executors;

public class CdcToKafkaBridge {

  public static void main(String[] args) throws Exception {
    // ----- Debezium connector properties (PostgreSQL) -----
    Properties cfg = new Properties();
    cfg.setProperty("name", "inventory-connector");
    cfg.setProperty("connector.class", "io.debezium.connector.postgresql.PostgresConnector");
    cfg.setProperty("database.hostname", env("PG_HOST", "localhost"));
    cfg.setProperty("database.port", env("PG_PORT", "5432"));
    cfg.setProperty("database.user", env("PG_USER", "cdc_user"));
    cfg.setProperty("database.password", env("PG_PASSWORD", "cdc_pass"));
    cfg.setProperty("database.dbname", env("PG_DB", "inventory"));
    cfg.setProperty("plugin.name", env("PG_PLUGIN", "pgoutput")); // wal2json also possible
    cfg.setProperty("slot.name", env("PG_SLOT", "debezium_slot"));
    cfg.setProperty("publication.autocreate.mode", "filtered");
    cfg.setProperty("slot.drop.on.stop", "false");
    // What to capture
    cfg.setProperty("table.include.list", env("CDC_TABLES", "public.products,public.orders"));
    // Snapshot: initial load then stream
    cfg.setProperty("snapshot.mode", env("CDC_SNAPSHOT", "initial"));
    // Produce JSON
    cfg.setProperty("topic.prefix", env("CDC_PREFIX", "db.inventory"));
    // Optional: masking/redaction at source
    cfg.setProperty("transforms", "mask");
    cfg.setProperty("transforms.mask.type", "org.apache.kafka.connect.transforms.MaskField$Value");
    cfg.setProperty("transforms.mask.fields", "public.customers.email");

    // ----- Kafka producer -----
    Properties kp = new Properties();
    kp.setProperty(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, env("KAFKA_BOOT", "localhost:9092"));
    kp.setProperty(ProducerConfig.ACKS_CONFIG, "all");
    kp.setProperty(ProducerConfig.ENABLE_IDEMPOTENCE_CONFIG, "true");
    kp.setProperty(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, "org.apache.kafka.common.serialization.StringSerializer");
    kp.setProperty(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, "org.apache.kafka.common.serialization.StringSerializer");
    KafkaProducer<String, String> producer = new KafkaProducer<>(kp);

    ObjectMapper mapper = new ObjectMapper();

    // ----- Debezium Engine (JSON ChangeEvent<String key, String value>) -----
    DebeziumEngine<ChangeEvent<String, String>> engine =
      DebeziumEngine.create(ChangeEventFormat.of(io.debezium.engine.format.Json.class))
        .using(cfg)
        .notifying(event -> {
          // event.key() - PK as JSON, event.value() - Debezium envelope JSON (before/after/op/source/ts_ms)
          String rawKey = event.key();
          String raw = event.value();
          if (raw == null) return; // tombstone for deletes (compaction)
          // Minimal sanitize: keep table, op, ts_ms, after (and optionally before for deletes)
          ObjectNode root = (ObjectNode) mapper.readTree(raw);
          String op = root.path("op").asText();
          ObjectNode src = (ObjectNode) root.path("source");
          String table = src.path("schema").asText("") + "." + src.path("table").asText("");
          ObjectNode out = mapper.createObjectNode()
              .put("table", table)
              .put("op", op)
              .put("ts_ms", root.path("ts_ms").asLong())
              .set("after", root.path("after").isMissingNode() ? null : root.path("after"));
          if ("d".equals(op)) out.set("before", root.path("before")); // useful for deletes

          String topic = "cdc." + table.replace('"','_'); // e.g., cdc.public.products
          ProducerRecord<String,String> rec = new ProducerRecord<>(topic, rawKey, mapper.writeValueAsString(out));
          rec.headers().add("debezium-op", op.getBytes());
          producer.send(rec, (md, ex) -> {
            if (ex != null) ex.printStackTrace();
          });
        })
        .build();

    var exec = Executors.newSingleThreadExecutor(r -> new Thread(r, "debezium-engine"));
    exec.execute(engine);

    // Shutdown hook
    Runtime.getRuntime().addShutdownHook(new Thread(() -> {
      try { engine.close(); } catch (Exception ignored) {}
      producer.flush(); producer.close();
      exec.shutdown();
    }));
  }

  private static String env(String k, String def) { String v = System.getenv(k); return v == null ? def : v; }
}
```

**What the example shows**

-   **Log-based CDC** via Debezium Embedded for **PostgreSQL**.
    
-   Produces **sanitized JSON** to per-table Kafka topics (`cdc.public.products`).
    
-   Keeps enough fields (`op`, `after`, `before`, `ts_ms`, `table`) for consumers to upsert/delete.
    
-   Adds a transform hook to **mask sensitive fields** at source.
    

> In production: prefer Debezium on **Kafka Connect**, Avro/Protobuf + **Schema Registry**, proper **DLQ**, metrics (lag, error rate), and ACLs. Many teams add a **translator service** that subscribes to CDC topics and emits **domain events** (e.g., `ProductPriceChanged`) so downstreams don’t depend on table schemas.

---

## Known Uses

-   **Search indexing:** DB changes → CDC → Kafka → Elasticsearch upserts with delete handling.
    
-   **Analytics streaming:** OLTP → CDC → Kafka → Flink/Spark → lakehouse/warehouse.
    
-   **Cache/materialized views:** CDC updates Redis/DynamoDB read models for low-latency APIs.
    
-   **Monolith → microservices**: Strangler migrations where new services consume CDC from the legacy DB.
    
-   **Cross-region replication**: Controlled mirroring of subsets of data via CDC pipelines.
    

## Related Patterns

-   **Transactional Outbox:** Producer-side guarantee; complement or alternative when you *can* change the app.
    
-   **Reliable Publisher–Subscriber:** End-to-end delivery + idempotent consumption around CDC topics.
    
-   **Anti-Corruption Layer (ACL):** Translate raw CDC rows into **domain** events/contracts.
    
-   **Event Sourcing:** Persist domain events directly; CDC is data-change oriented.
    
-   **Event Replay / Snapshotting:** Rebuild projections from durable CDC topics.
    
-   **API Composition / BFF:** Downstreams may read CDC-projected views instead of chaining many calls.
    

---

**Implementation checklist (quick-hit)**

-    Choose capture: **log-based CDC** (preferred).
    
-    Define **tables & columns** to include; **mask** PII.
    
-    Pick **topics/keys**; decide compaction/retention.
    
-    Use **Schema Registry**; enforce compatibility.
    
-    Stand up **translator** to domain events (optional but recommended).
    
-    Make consumers **idempotent** (upsert/delete by key) with retries + DLQ.
    
-    Monitor **replication lag** and **connector health**; plan **backfills**.
    
-    Align DB **migrations** with CDC (expand/contract, nullable fields, default values).

