# Change Data Capture — Data Management and Database Pattern

## Pattern Name and Classification

**Name:** Change Data Capture (CDC)  
**Category:** Data Management · Database Integration · Event-Driven Data Synchronization · Data Pipeline Pattern

## Intent

Capture and propagate **data changes (inserts, updates, deletes)** from one system to another in **real-time or near real-time** without requiring full dataset scans or polling. The pattern allows downstream systems to react to and replicate only **incremental changes** instead of complete reloads.

## Also Known As

CDC · Incremental Data Synchronization · Transactional Change Stream · Database Change Feed

## Motivation (Forces)

-   **Efficiency:** Full table scans for sync or analytics are expensive and slow.
    
-   **Timeliness:** Systems often require near-real-time updates (dashboards, search indexes, caches).
    
-   **Decoupling:** Data producers and consumers should evolve independently.
    
-   **Event-driven architectures:** Need a consistent source of truth to emit domain events from DB changes.
    
-   **Auditability:** Each change provides a traceable log of data evolution.
    
-   **Trade-offs:** CDC introduces complexity in maintaining order, schema evolution, and handling idempotency.
    

## Applicability

Use Change Data Capture when:

-   Multiple systems or microservices depend on updates from a shared data source.
    
-   You need to replicate data from an OLTP system to OLAP, cache, or search index.
    
-   You want to build **event-driven microservices** from a legacy monolithic database.
    
-   Real-time synchronization or ETL pipelines are required (e.g., Kafka, Debezium, Flink).
    

Avoid or adapt when:

-   Data volume is small and periodic batch sync is sufficient.
    
-   The database does not expose change logs or binlogs (then use trigger-based CDC).
    
-   Strictly eventual consistency is unacceptable or legal compliance demands full ACID consistency.
    

## Structure

-   **Source Database:** The system of record where data changes occur.
    
-   **Change Stream / Log:** Captures all committed transactions (e.g., MySQL binlog, PostgreSQL WAL).
    
-   **CDC Connector/Agent:** Reads database logs and converts them into change events.
    
-   **Event Stream / Message Broker:** Transports change events (e.g., Kafka topic).
    
-   **Consumers / Subscribers:** React to or replicate changes downstream (e.g., data warehouse, search index).
    

```pgsql
Database → Transaction Log → CDC Connector → Event Stream → Consumers
```

## Participants

-   **Change Producer:** The source database generating change events.
    
-   **CDC Connector:** Reads and parses low-level log entries into logical change events.
    
-   **Event Stream:** Middleware distributing change events (e.g., Kafka, Pulsar).
    
-   **Consumers:** Target systems subscribing to events (analytics, caches, APIs).
    
-   **Schema Registry (optional):** Maintains versioned schema metadata for consumers.
    

## Collaboration

1.  Application commits data to the source database.
    
2.  The database writes the transaction to its **commit log**.
    
3.  The **CDC agent** reads these log entries continuously.
    
4.  CDC translates entries into structured change events (insert, update, delete).
    
5.  Events are published to a streaming platform.
    
6.  Downstream consumers process, store, or transform these events in real-time.
    

## Consequences

**Benefits**

-   Real-time data synchronization without polling.
    
-   Reduced load on source systems (reads happen from logs, not tables).
    
-   Enables reactive, event-driven architectures.
    
-   Supports audit trails and replay capabilities.
    
-   Foundation for data lake ingestion, analytics, and caching layers.
    

**Liabilities**

-   Requires access to database transaction logs.
    
-   Complexity in ordering, deduplication, and schema evolution.
    
-   Potential latency if log parsing or event publishing is delayed.
    
-   Security and compliance concerns around exposing raw change events.
    
-   Handling out-of-order events and transactional boundaries can be non-trivial.
    

## Implementation

**Guidelines**

1.  **Choose capture strategy:**
    
    -   *Log-based CDC* (preferred): Reads transaction logs (binlog/WAL/redo logs).
        
    -   *Trigger-based CDC:* Database triggers write to audit/change tables.
        
    -   *Query-based CDC:* Periodic queries for deltas (least efficient).
        
2.  **Use a connector framework:** Debezium, Maxwell, GoldenGate, or StreamSets.
    
3.  **Guarantee ordering and idempotency:** Use transaction IDs or LSNs (Log Sequence Numbers).
    
4.  **Version schemas:** Keep backward-compatible changes; use Avro or Protobuf for streaming payloads.
    
5.  **Implement backpressure handling:** Use buffering and commit offsets responsibly.
    
6.  **Replay and recovery:** Persist offsets for exactly-once or at-least-once processing.
    
7.  **Security:** Mask sensitive fields in CDC stream.
    
8.  **Monitoring:** Track lag between source and consumers to ensure freshness.
    

---

## Sample Code (Java — Simplified CDC Reader Using MySQL Binlog via Debezium Embedded)

```java
// build.gradle dependencies
// implementation 'io.debezium:debezium-embedded:2.5.0.Final'
// implementation 'io.debezium:debezium-connector-mysql:2.5.0.Final'
// implementation 'org.slf4j:slf4j-simple:2.0.9'
```

```java
// src/main/java/com/example/cdc/CdcApp.java
package com.example.cdc;

import io.debezium.config.Configuration;
import io.debezium.embedded.EmbeddedEngine;
import io.debezium.engine.ChangeEvent;
import io.debezium.engine.DebeziumEngine;

import java.util.Properties;
import java.util.concurrent.Executor;
import java.util.concurrent.Executors;

public class CdcApp {

    public static void main(String[] args) {
        Configuration config = Configuration.create()
                .with("name", "cdc-engine-mysql")
                .with("connector.class", "io.debezium.connector.mysql.MySqlConnector")
                .with("database.hostname", "localhost")
                .with("database.port", 3306)
                .with("database.user", "cdc_user")
                .with("database.password", "cdc_password")
                .with("database.server.id", 10101)
                .with("database.server.name", "mysql-server")
                .with("database.include.list", "appdb")
                .with("table.include.list", "appdb.customers")
                .with("database.history", "io.debezium.relational.history.MemoryDatabaseHistory")
                .with("include.schema.changes", false)
                .build();

        DebeziumEngine<ChangeEvent<String, String>> engine = DebeziumEngine.create(EmbeddedEngine.class)
                .using(config.asProperties())
                .notifying(record -> {
                    System.out.printf("CDC EVENT [%s]: %s%n", record.key(), record.value());
                })
                .build();

        Executor executor = Executors.newSingleThreadExecutor();
        executor.execute(engine);

        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            try {
                engine.close();
            } catch (Exception e) {
                e.printStackTrace();
            }
        }));
    }
}
```

**Explanation:**

-   The Debezium Embedded Engine runs inside a Java application.
    
-   It connects to MySQL and streams all data changes in real-time from the `customers` table.
    
-   Each event is emitted as a JSON payload containing before/after states.
    
-   The engine can push these events to Kafka, WebSocket, or REST endpoints.
    

**Sample output:**

```css
CDC EVENT [customers:123] : {"op":"u","before":{"name":"Alice"},"after":{"name":"Alicia"}}
CDC EVENT [customers:124] : {"op":"d","before":{"name":"Bob"}}
```

---

## Known Uses

-   **Debezium + Kafka Connect:** Open-source CDC pipeline for MySQL, PostgreSQL, MongoDB.
    
-   **AWS DMS / Google DataStream / Azure Data Factory:** Managed CDC pipelines for cloud migration.
    
-   **Oracle GoldenGate / SQL Server CDC:** Enterprise-grade CDC frameworks for replication.
    
-   **Snowflake + Kafka + Flink pipelines:** Near-real-time data lake ingestion.
    
-   **Elasticsearch sync:** Keeping search indices in sync with transactional databases.
    

## Related Patterns

-   **Event Sourcing:** Stores all changes as domain events; CDC extracts from DB logs instead.
    
-   **Transactional Outbox:** Ensures reliable event publishing by writing to an outbox table and using CDC.
    
-   **Materialized View / Read Model:** Downstream consumers build precomputed projections using CDC streams.
    
-   **Data Replication:** CDC forms the backbone of real-time replication strategies.
    
-   **Audit Trail:** CDC events can populate audit logs automatically.
    
-   **Event-Driven Microservices:** CDC bridges database state and event streams for reactive systems.
