# Change Data Capture (CDC) — Event-Driven Architecture Pattern

## Pattern Name and Classification

**Name:** Change Data Capture (CDC)  
**Classification:** Data Integration / Event Sourcing–adjacent pattern for Event-Driven Architecture (EDA)

## Intent

Continuously **observe committed changes** in one or more operational databases (inserts, updates, deletes, DDL) and **emit events** that reflect those changes to downstream consumers, **without modifying application write paths**.

## Also Known As

-   Database Change Stream
    
-   Log-based CDC
    
-   Data Replication Stream
    
-   Change Feed
    

## Motivation (Forces)

-   Many systems already write truth into OLTP databases; we want **events** without rewriting all services.
    
-   Polling tables is wasteful and misses ordering; ad-hoc triggers couple logic to the DB.
    
-   Need **low-latency, ordered, durable** change streams for caches, search indexes, analytics, audit, and integration.
    
-   Application teams want to **avoid dual-writes** (DB + broker) and still have **near-real-time** data propagation.
    

**Forces to balance**

-   **Fidelity & ordering** (per key/partition) vs. throughput and retention.
    
-   **Initial backfill/snapshot** vs. continuous streaming.
    
-   **Schema evolution** and mapping from DB rows to domain events.
    
-   **Operational complexity** (connectors, security, failover) vs. simplicity of polling.
    

## Applicability

Use CDC when:

-   Source of truth is a **relational/NoSQL** database and multiple systems must react to changes.
    
-   You need to feed **search indexes, caches, data lakes**, or **materialized views** in real time.
    
-   You want to generate **domain events** from data changes with minimal application changes.
    
-   You must **audit** data modifications (who/what/when).
    

Avoid or limit when:

-   The write model is already event-sourced and emits first-class events.
    
-   The DB does not expose change logs and only crude polling is possible, or you need cross-entity **transactional semantics** best handled by a **Transactional Outbox**.
    

## Structure

```rust
+-------------+           +-------------------------+          +-----------------+
Writes -> Operational |  WAL/binlog/Changefeed  ->  CDC Connector/Engine  ->  Event/Log Bus  -> Consumers
        |   Database  |---------->| (reads log, snapshots) |--------->| (Kafka, etc.)   |-> (indexes, caches,
        +-------------+           +-------------------------+          +-----------------+   ETL, services)
                                         | offsets/checkpoints
                                         v
                                   Offset/State Store
```

## Participants

-   **Source Database:** e.g., Postgres (WAL), MySQL (binlog), SQL Server (CDC tables), MongoDB (oplog).
    
-   **CDC Connector/Engine:** Reads the DB change stream (log-based is preferred), optionally performs initial snapshot, and emits records.
    
-   **Offsets/State Store:** Tracks last processed position for **exactly-once** *publication* semantics per connector instance.
    
-   **Event/Log Bus:** Kafka/Pulsar/etc. transporting CDC events.
    
-   **Schema Registry (optional):** Manages change record schemas (Avro/JSON/Protobuf).
    
-   **Downstream Consumers:** Services, stream processors, ETL, search/indexers, caches.
    
-   **Transformation Layer (optional):** Converts change records to **domain events** (e.g., with Kafka Streams).
    

## Collaboration

1.  Connector starts, **snapshots** selected tables (optional/once) and then tail-follows the DB log.
    
2.  For each committed change, connector emits a **change record** containing **before/after** images, source metadata, and operation type (`c/u/d`).
    
3.  Records are keyed (usually by primary key) and written to **per-table topics/streams**.
    
4.  Consumers read change events to update views, trigger workflows, or derive **domain events**.
    
5.  Offsets and **resumption** points ensure resilience across restarts; **idempotent consumers** deal with at-least-once delivery.
    

## Consequences

**Benefits**

-   Non-intrusive: no changes to application write code.
    
-   Preserves **ordering** per key (within a partition) and captures **all** changes.
    
-   Enables **near-real-time** propagation and decoupled integration.
    
-   Facilitates **auditing** and **replay** (with a log bus).
    

**Liabilities**

-   Emits **data-shaped** events, not necessarily **business/domain** events; translation may be needed.
    
-   **Schema drift** must be managed; downstream breakage is possible without governance.
    
-   Operational overhead: connectors, security, **log retention**, backpressure handling.
    
-   Multi-table transactional semantics require care (compose/join or use **Outbox** for intent).
    

## Implementation

-   **Capture style:**
    
    -   **Log-based (preferred):** tail WAL/binlog/oplog → ordered, minimal overhead, no triggers.
        
    -   **Trigger/table capture:** easy to start, but adds write-path overhead; use only when log access is impossible.
        
    -   **Polling:** simplest but least timely; use only for low-frequency cases.
        
-   **Topic design:** `db.schema.table` → `orders.public.orders` or mapped to `orders.rowchange.v1`; key = **primary key**.
    
-   **Payload:** Include `op` (`c/u/d`), `before`, `after`, `ts_ms`, transaction id, source metadata; optionally a **flattened** record for convenience.
    
-   **Ordering & keys:** Partition by primary key to maintain **per-row order**.
    
-   **Initial snapshot:** Choose **blocking**, **incremental**, or **none** based on size/SLAs.
    
-   **Transform to domain events:** Use stream processors to map row changes → `OrderCreated`, `OrderUpdated`, etc., filtering noise and enforcing semantics.
    
-   **PII/security:** Mask fields at the connector or transform layer; ensure encrypted transport and fine-grained ACLs.
    
-   **Error handling:** Parking-lot topics for malformed records; backpressure with bounded retries.
    
-   **Observability:** Lag, snapshot progress, commit latency, error rate, per-table throughput.
    

---

## Sample Code (Java)

### A) Debezium Embedded Engine — Stream DB changes and publish to Kafka

> This shows a lightweight Java process reading PostgreSQL WAL via Debezium Embedded and forwarding to Kafka. (Swap Postgres for MySQL/Mongo by changing connector config.)

```java
// build.gradle (snippets):
// implementation("io.debezium:debezium-embedded:2.6.0.Final")
// implementation("io.debezium:debezium-connector-postgres:2.6.0.Final")
// implementation("org.apache.kafka:kafka-clients:3.7.0")
// implementation("com.fasterxml.jackson.core:jackson-databind:2.17.1")

import io.debezium.engine.*;
import io.debezium.engine.format.Json;
import org.apache.kafka.clients.producer.*;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Properties;

public class EmbeddedCdcToKafka {

  public static void main(String[] args) throws Exception {
    // Kafka producer
    Properties kp = new Properties();
    kp.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, "localhost:9092");
    kp.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, "org.apache.kafka.common.serialization.StringSerializer");
    kp.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, "org.apache.kafka.common.serialization.ByteArraySerializer");
    kp.put(ProducerConfig.ACKS_CONFIG, "all");
    kp.put(ProducerConfig.ENABLE_IDEMPOTENCE_CONFIG, "true");
    final KafkaProducer<String, byte[]> producer = new KafkaProducer<>(kp);

    // Debezium configuration
    Properties cfg = new Properties();
    cfg.setProperty("name", "orders-cdc");
    cfg.setProperty("connector.class", "io.debezium.connector.postgresql.PostgresConnector");
    cfg.setProperty("topic.prefix", "cdc");                       // e.g., cdc.public.orders
    cfg.setProperty("database.hostname", "localhost");
    cfg.setProperty("database.port", "5432");
    cfg.setProperty("database.user", "debezium");
    cfg.setProperty("database.password", "dbz");
    cfg.setProperty("database.dbname", "orders");
    cfg.setProperty("schema.include.list", "public");
    cfg.setProperty("table.include.list", "public.orders,public.order_items");
    cfg.setProperty("slot.name", "orders_slot");
    cfg.setProperty("publication.autocreate.mode", "filtered");
    cfg.setProperty("tombstones.on.delete", "false");             // optional
    cfg.setProperty("include.schema.changes", "false");           // DDL off for simplicity
    cfg.setProperty("snapshot.mode", "initial");                  // or 'initial_only', 'never'
    cfg.setProperty("max.batch.size", "2048");
    cfg.setProperty("max.queue.size", "8192");

    try (DebeziumEngine<ChangeEvent<String, String>> engine =
         DebeziumEngine.create(Json.class)
            .using(cfg)
            .notifying(record -> {
              // record.key(): primary-key JSON; record.value(): change payload JSON
              String topic = mapTopic(record.destination()); // passthrough or rename
              String key = record.key();                     // could extract a concrete PK
              byte[] value = record.value().getBytes(StandardCharsets.UTF_8);
              ProducerRecord<String, byte[]> pr =
                  new ProducerRecord<>(topic, key, value);
              producer.send(pr);
            })
            .using((success, message, error) -> {
              if (!success) error.printStackTrace();
            })
            .build()) {

      engine.run(); // blocks; run under a supervisor in production
    } finally {
      producer.flush();
      producer.close(Duration.ofSeconds(5));
    }
  }

  private static String mapTopic(String debeziumTopic) {
    // e.g., "cdc.public.orders" -> "orders.rowchange.v1"
    if (debeziumTopic.endsWith("public.orders")) return "orders.rowchange.v1";
    if (debeziumTopic.endsWith("public.order_items")) return "order_items.rowchange.v1";
    return debeziumTopic.replace("cdc.", "");
  }
}
```

**What you get:** JSON change events like:

```json
{
  "op":"c", "ts_ms":1719930000000,
  "source":{"db":"orders","schema":"public","table":"orders","txId":42},
  "before":null,
  "after":{"id":"O-123","status":"CREATED","total":1999}
}
```

### B) Kafka Streams — Derive **domain events** from CDC row changes

> Transform row-level changes into semantic events (e.g., `OrderCreated`, `OrderStatusChanged`).

```java
// build.gradle: implementation("org.apache.kafka:kafka-streams:3.7.0"), jackson
import org.apache.kafka.streams.*;
import org.apache.kafka.streams.kstream.*;
import org.apache.kafka.common.serialization.Serdes;
import com.fasterxml.jackson.databind.*;

import java.util.Properties;

public class CdcToDomainEvents {
  public static void main(String[] args) {
    Properties p = new Properties();
    p.put(StreamsConfig.APPLICATION_ID_CONFIG, "orders-cdc-transform");
    p.put(StreamsConfig.BOOTSTRAP_SERVERS_CONFIG, "localhost:9092");

    StreamsBuilder b = new StreamsBuilder();
    ObjectMapper json = new ObjectMapper();

    KStream<String, String> cdc = b.stream("orders.rowchange.v1",
        Consumed.with(Serdes.String(), Serdes.String()));

    KStream<String, String> domain = cdc.flatMapValues(value -> {
      try {
        var n = json.readTree(value);
        String op = n.get("op").asText(); // c,u,d
        var after = n.get("after");
        var before = n.get("before");
        if ("c".equals(op) && after != null) {
          var evt = new DomainEvent("OrderCreated", after.get("id").asText(), after);
          return java.util.List.of(json.writeValueAsString(evt));
        } else if ("u".equals(op) && after != null && before != null) {
          // example: emit only if status changed
          var oldStatus = before.get("status").asText();
          var newStatus = after.get("status").asText();
          if (!oldStatus.equals(newStatus)) {
            var payload = new ObjectNode(json.getNodeFactory());
            payload.set("before", before);
            payload.set("after", after);
            var evt = new DomainEvent("OrderStatusChanged", after.get("id").asText(), payload);
            return java.util.List.of(json.writeValueAsString(evt));
          }
        } else if ("d".equals(op) && before != null) {
          var evt = new DomainEvent("OrderDeleted", before.get("id").asText(), before);
          return java.util.List.of(json.writeValueAsString(evt));
        }
        return java.util.List.of(); // ignore other updates
      } catch (Exception e) {
        // Optionally send to a dead-letter topic
        return java.util.List.of();
      }
    });

    domain.to("orders.events.v1", Produced.with(Serdes.String(), Serdes.String()));
    new KafkaStreams(b.build(), p).start();
  }

  static class DomainEvent {
    public String type; public String aggregateId; public JsonNode payload;
    public String version = "v1"; public long occurredAt = System.currentTimeMillis();
    DomainEvent(String t, String id, JsonNode p){ type=t; aggregateId=id; payload=p; }
  }
}
```

---

## Known Uses

-   **Search indexing:** Stream DB changes to **Elasticsearch/OpenSearch** to keep indexes in sync.
    
-   **Caching/materialized views:** Feed **Redis** or service-owned read models from change streams.
    
-   **Data lakes/warehouses:** Land CDC into **S3/GCS/ADLS** (e.g., through Kafka → Spark/Flink → Parquet) for analytics.
    
-   **Microservices integration:** Legacy monolith DB → CDC → Kafka topics → new services consume.
    
-   **Audit & forensics:** Immutable record of who changed what and when.
    
-   **Multi-region sync:** Controlled replication and conflict detection via change streams.
    

## Related Patterns

-   **Transactional Outbox:** Preferred for **business events** authored by services; CDC can complement it to propagate **data** changes.
    
-   **Event Sourcing:** CDC is *derived* from DB changes; event sourcing stores **events as truth**.
    
-   **Materialized View / CQRS:** CDC populates read models separate from write models.
    
-   **Idempotent Receiver / Resequencer:** Downstream consumers handle at-least-once delivery and per-key ordering.
    
-   **Message Translator / Canonical Data Model:** Convert row change format to domain event schemas.
    
-   **Saga / Process Manager:** Domain events derived from CDC can trigger orchestrations (with caution around semantics).
    

---

### Practical tips

-   Prefer **log-based CDC** for fidelity; use **schema registry** and enforce compatibility.
    
-   Start with **snapshots + streaming**, then backfill historic data from the lake if needed.
    
-   Treat **CDC events as data events**; when you need explicit intent, emit a **domain event** (often via Outbox) and optionally join with CDC.
    
-   Keep **PII redaction** and **column-level filtering** in the connector or transformation layer.

