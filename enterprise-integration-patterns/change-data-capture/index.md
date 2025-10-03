# Change Data Capture (Enterprise Integration Pattern)

## Pattern Name and Classification

**Name:** Change Data Capture (CDC)  
**Classification:** Enterprise Integration Pattern (Data Integration / Eventing)

---

## Intent

Continuously **observe and publish changes** (inserts/updates/deletes) from a datastore as **ordered change events**, so other systems can react, replicate, cache, audit, or build projections **without coupling** to the writer’s application logic.

---

## Also Known As

-   Database Change Stream
    
-   Log-Based Replication for Integration
    
-   Data Capture / Change Feed
    

---

## Motivation (Forces)

-   **Decoupling:** Downstream consumers (search indices, caches, analytics, other services) need fresh data without synchronous calls to the source.
    
-   **Low impact:** Polling source tables causes load and misses deletes; CDC hooks the **database’s write-ahead/change logs** (binlog/WAL/redo).
    
-   **Timeliness:** Near real-time propagation instead of nightly batches.
    
-   **Completeness:** Emits **before/after** images or deltas, including deletes and key changes.
    
-   **Auditability:** Durable history of what changed and when.
    

Trade-offs to balance:

-   **Exactly-once illusions:** Most CDCs are at-least-once → consumers must be **idempotent**.
    
-   **Ordering & keys:** Global vs per-table/partition ordering; primary key changes are tricky.
    
-   **Schema evolution:** Add columns, type changes → **event versioning/upcasting** required.
    
-   **Security & PII:** Replicating sensitive columns may violate policy; **column masking**/filtering is needed.
    
-   **Operational surface:** Connectors, offsets, reprocessing, backfills.
    

---

## Applicability

Use CDC when:

-   You want **event-driven propagation** from a RDBMS/NoSQL to caches/search/analytics.
    
-   You need **event-carried state transfer** to other bounded contexts.
    
-   You must build **read models** (CQRS) without touching the write path.
    
-   Legacy systems cannot be modified to emit domain events.
    

Avoid or limit when:

-   The source system disallows log access and triggers are prohibitive.
    
-   You need **business-domain events**, not just row changes → consider **Transactional Outbox** or publish domain events directly.
    
-   Hard real-time/strict transactions across services are required.
    

---

## Structure

-   **Source Database:** MySQL/PostgreSQL/Oracle/SQL Server, MongoDB, etc.
    
-   **Change Log / Replication Stream:** Binlog (MySQL), WAL (Postgres), redo (Oracle), oplog (MongoDB).
    
-   **CDC Connector/Agent:** Reads the log, converts to change events, tracks **offsets**.
    
-   **Broker / Sink (optional):** Kafka/SQS/PubSub; or direct push to HTTP, files, or another DB.
    
-   **Consumers:** Downstream services that build projections/caches, trigger workflows, or replicate.
    
-   **Offset Store:** Stores CDC read position for **resume** and **exactly-once per partition** semantics.
    

---

## Participants

-   **CDC Connector:** Debezium/Kafka Connect, database-native change feed, or custom agent.
    
-   **Offset Storage:** Kafka internal topic, database table, or local file.
    
-   **Schema/Converter:** Translates DB types to event schema (JSON/Avro/Protobuf).
    
-   **Consumers:** Idempotent processors, updaters, search indexers, ETL jobs.
    
-   **Operations:** Manage connector lifecycle, schema changes, backfills, reprocessing.
    

---

## Collaboration

1.  **Connector** subscribes to the database’s change log from a starting offset (initial snapshot optional).
    
2.  For each committed transaction, the connector emits **ordered change events** (per table/partition) with metadata (op type, LSN/position, tx id, ts).
    
3.  Events are **serialized** and delivered (e.g., Kafka topic per table).
    
4.  **Consumers** process events idempotently, update views/caches, or trigger workflows.
    
5.  Offsets advance; on restart, the connector resumes from the last committed offset.
    

---

## Consequences

**Benefits**

-   Minimal load on source (log-based), near real-time propagation.
    
-   Captures **all** changes (including deletes), with **ordering** and metadata.
    
-   Enables **polyglot read models**, zero-touch on application code.
    
-   Ideal for **audit trails** and **rebuilds**.
    

**Liabilities**

-   **Operational complexity:** connectors, offsets, backfills, failure handling.
    
-   **At-least-once delivery:** duplicates → require idempotent consumers.
    
-   **Schema drift & column transforms** to protect PII.
    
-   **Mismatch to domain:** Row changes ≠ domain events; may require translation/enrichment downstream.
    

---

## Implementation

### Techniques

-   **Log-based CDC (preferred):** Read binlog/WAL/oplog. High fidelity, low impact.
    
-   **Trigger-based CDC:** DB triggers write into change tables. Easier to adopt but adds write overhead and risk.
    
-   **Timestamp diffing:** Poll by `updated_at`. Simple but misses deletes and can be inaccurate under clock issues.
    

### Design guidelines

-   **Event shape:** Include `op` (`c/u/d`), `source` (db/table/lsn), `ts_ms`, **primary key**, **before/after** images.
    
-   **Partitioning:** Partition topics by **primary key** for per-entity ordering.
    
-   **Idempotency:** Use `(table, pk, lsn|ts, op)` to deduplicate; maintain **applied offset** per consumer.
    
-   **Reprocessing:** Support **replay** from offset for rebuilds; keep events immutable.
    
-   **Schema evolution:** Version event schemas; add new optional fields; use **upcasters** for older payloads.
    
-   **Security:** Column whitelists/blacklists, masking/crypt, separate topics for sensitive data.
    
-   **Outbox integration:** Prefer **Transactional Outbox** when you need **domain events** (CDC reads the outbox table to publish).
    

---

## Sample Code (Java)

Two pragmatic samples:

### A) Embedded Debezium Engine (log-based CDC → your handler)

```java
// Maven deps (conceptual): io.debezium:debezium-embedded + connector (e.g., debezium-connector-postgres)
// This example streams Postgres WAL changes to a Java callback.
import io.debezium.config.Configuration;
import io.debezium.engine.*;
import io.debezium.engine.format.Json;

import java.util.Properties;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class PostgresCdcRunner {

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private Engine engine;

    public void start() {
        Configuration cfg = Configuration.create()
            .with("name", "orders-cdc")
            .with("connector.class", "io.debezium.connector.postgresql.PostgresConnector")
            .with("database.hostname", "localhost")
            .with("database.port", "5432")
            .with("database.user", "cdc_user")
            .with("database.password", "secret")
            .with("database.dbname", "appdb")
            // Slot & publication (created automatically if permissions allow)
            .with("plugin.name", "pgoutput")
            .with("publication.autocreate.mode", "filtered")
            .with("slot.name", "orders_cdc_slot")
            // What to capture
            .with("table.include.list", "public.orders,public.order_line,public.outbox_event")
            .with("tombstones.on.delete", "false")
            .with("provide.transaction.metadata", "true")
            // Offset store (file-based for demo; use Kafka topic or durable store in prod)
            .with("offset.storage", "org.apache.kafka.connect.storage.FileOffsetBackingStore")
            .with("offset.storage.file.filename", "/tmp/debezium-offsets.dat")
            .with("offset.flush.interval.ms", "1000")
            // Initial snapshot? 'initial' once; then 'never'
            .with("snapshot.mode", "initial") // or 'never' for pure streaming
            .build();

        DebeziumEngine<org.apache.kafka.connect.source.SourceRecord> engine =
            DebeziumEngine.create(Json.class)
                .using(cfg.asProperties())
                .notifying(record -> {
                    // record.value() is JSON with 'payload' (before/after/op/ts_ms/source) depending on connector version
                    String json = record.value().toString();
                    // Route by topic (e.g., "appdb.public.orders")
                    String topic = record.topic();
                    ChangeRouter.route(topic, json);
                })
                .using((success, message, error) -> {
                    if (!success) error.printStackTrace();
                })
                .build();

        this.engine = engine;
        executor.submit(engine);
    }

    public void stop() throws Exception {
        if (engine != null) engine.close();
        executor.shutdownNow();
    }

    /** Example downstream handler that you would implement for idempotent apply */
    static final class ChangeRouter {
        static void route(String topic, String json) {
            // parse JSON, inspect "op": "c"=create, "u"=update, "d"=delete
            // apply to projection/cache or publish to Kafka/SQS with your schema
            // ensure idempotency using (topic, primaryKey, source.lsn or ts_ms)
            System.out.printf("CDC %s -> %s%n", topic, json);
        }
    }
}
```

**Notes**

-   Debezium Embedded runs inside your JVM (no Kafka Connect required).
    
-   For production, prefer **Kafka Connect** with Debezium and a Kafka broker for offset storage, scaling, HA.
    

---

### B) Consuming CDC from Kafka topic and updating a projection (idempotent)

```java
// Consume JSON CDC events from Kafka and update a read model idempotently.
import org.apache.kafka.clients.consumer.*;
import org.apache.kafka.common.serialization.StringDeserializer;
import java.time.Duration;
import java.util.*;

public final class OrdersProjectionConsumer {

    private final Consumer<String, String> consumer;
    private final ProjectionStore store; // your DAO with upsert & dedup by (pk, lsn)

    public OrdersProjectionConsumer(String bootstrap, String groupId, ProjectionStore store) {
        Properties p = new Properties();
        p.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, bootstrap);
        p.put(ConsumerConfig.GROUP_ID_CONFIG, groupId);
        p.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class.getName());
        p.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class.getName());
        p.put(ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, "false");
        p.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest");
        this.consumer = new KafkaConsumer<>(p);
        this.store = store;
        consumer.subscribe(List.of("appdb.public.orders")); // topic per table
    }

    public void run() {
        while (true) {
            ConsumerRecords<String, String> records = consumer.poll(Duration.ofSeconds(1));
            for (ConsumerRecord<String,String> rec : records) {
                // Parse CDC JSON (Debezium 'payload' contains after/before/op/source.lsn)
                var evt = DebeziumEnvelope.parse(rec.value());
                String pk = evt.primaryKey();        // derive from 'after' or key struct
                long lsn = evt.sourceLsnOrTs();      // monotonic per source
                switch (evt.op()) {
                    case CREATE, UPDATE -> store.upsertIfNewer(pk, lsn, evt.after()); // idempotent
                    case DELETE          -> store.deleteIfNewer(pk, lsn);
                }
            }
            consumer.commitSync();
        }
    }

    // Sketch helpers
    static final class DebeziumEnvelope {
        enum Op { CREATE, UPDATE, DELETE }
        final Op op; final String after; final String before; final long lsn; final String pk;
        DebeziumEnvelope(Op op, String after, String before, long lsn, String pk) {
            this.op = op; this.after = after; this.before = before; this.lsn = lsn; this.pk = pk;
        }
        static DebeziumEnvelope parse(String json) {
            // parse with Jackson; extract op/source.lsn/ts_ms, after/before struct and PK
            throw new UnsupportedOperationException("parsing omitted for brevity");
        }
        Op op() { return op; }
        String after() { return after; }
        long sourceLsnOrTs() { return lsn; }
        String primaryKey() { return pk; }
    }

    public interface ProjectionStore {
        void upsertIfNewer(String pk, long lsn, String afterJson);
        void deleteIfNewer(String pk, long lsn);
    }
}
```

**Notes**

-   **Idempotency** ensured by comparing stored **last applied LSN/offset** per primary key.
    
-   If you need cross-table joins, **project independently** and join in a query layer or use a stream processor.
    

---

## Known Uses

-   **Search indexing:** Stream DB changes to Elasticsearch/OpenSearch.
    
-   **Caches & read models:** Update Redis/materialized views in CQRS architectures.
    
-   **Data lakes/warehouses:** Land immutable change events into S3/GCS/ADLS → Lakehouse ingestion.
    
-   **Microservice sync:** Share reference data across services without synchronous calls.
    
-   **Audit/compliance trails:** Immutable append-only topics of changes.
    
-   **Legacy modernization:** Add events to a system you cannot change.
    

---

## Related Patterns

-   **Transactional Outbox:** Model domain events in a table; CDC the outbox to publish **business events** reliably.
    
-   **Event Sourcing:** Persist events as the system of record (different write model); CDC propagates **row changes**, not domain intent.
    
-   **Event-Carried State Transfer:** CDC events are a concrete mechanism to carry state to consumers.
    
-   **Data Lake Ingest / Streaming ETL:** CDC is a primary ingest source.
    
-   **Idempotent Receiver / Retry:** Consumer-side discipline for at-least-once delivery.
    
-   **Schema Registry / Contract:** Manage event schemas and evolution for CDC payloads.
    

---

## Extra Implementation Tips (quick checklist)

-    Choose **log-based** CDC where possible; fall back to triggers only if necessary.
    
-    Partition topics by **primary key**; ensure **ordering** per key.
    
-    Include **op**, **before/after**, **source position**, **ts**, **transaction metadata**.
    
-    Enforce **column filtering/masking** and **topic ACLs** for PII.
    
-    Handle **restarts**: durable offset storage, replay to rebuild projections.
    
-    Bake in **dead-letter** handling for malformed events.
    
-    Test **schema changes** with staging connectors and consumer contract tests.
    

---

