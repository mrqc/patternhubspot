# Event Carried State Transfer — Event-Driven Architecture Pattern

## Pattern Name and Classification

**Name:** Event Carried State Transfer (ECST)  
**Classification:** Event-driven integration / data replication pattern; pushes **current state** (or state deltas + version) inside events so other services can maintain their own **local read models**.

## Intent

Avoid synchronous calls to a remote service by **publishing enough state in events** for subscribers to keep a **local, query-optimized copy** of another service’s data, updated asynchronously.

## Also Known As

-   Event-Carried Data
    
-   State Transfer via Events
    
-   Push-Based Replication / Materialized View via Events
    

## Motivation (Forces)

-   Querying another service on the critical path adds **latency**, **coupling**, and **failure propagation**.
    
-   Many read scenarios need only a **subset** of another service’s data.
    
-   **Asynchronous replication** via events keeps services **autonomous**, improves **performance**, and tolerates brief outages.
    

**Forces to balance**

-   **Freshness vs. decoupling:** eventual consistency is acceptable?
    
-   **Payload size vs. completeness:** full snapshot vs. minimal delta.
    
-   **PII spread & governance** when copying data into multiple services.
    
-   **Ordering & idempotency** across partitions and retries.
    

## Applicability

Use ECST when:

-   A service frequently needs **read access** to data it doesn’t own.
    
-   **Eventual consistency** (seconds) is acceptable.
    
-   You can publish **stable identifiers**, **versions**, and (optionally) **tombstones** for deletes.
    
-   Consumers can maintain **materialized views** (DB tables, caches, KTables).
    

Avoid or limit when:

-   You need **strong consistency** across services or cross-entity invariants.
    
-   Data is **highly sensitive** and cannot be replicated broadly.
    
-   State is **too large** to move in events without compaction/segmentation.
    

## Structure

```lua
+--------------------+         +--------------------------+        +-------------------------+
| Owning Service     |  ---->  | Event Channel (Topic)    |  --->  | Subscribing Service(s)  |
| (source of truth)  |         | - compacted (optional)   |        | - local read model      |
| emits state events |         | - partition by aggregate |        | - upsert by id+version  |
+--------------------+         +--------------------------+        +-------------------------+

Event payload = { aggregateId, version, state {...}, deleted? }
```

## Participants

-   **Owning Service (Producer):** Publishes **state-carrying** events at create/update/delete.
    
-   **Event Channel (Topic/Queue):** Transports events; often **compacted** (Kafka) to keep latest state.
    
-   **Subscribers/Consumers:** Maintain **local projections** (tables/caches) via upsert/tombstone.
    
-   **Schema/Contract Registry:** Manages versioned schemas.
    
-   **Outbox/Inbox & Idempotency Store:** For reliable publish/consume.
    

## Collaboration

1.  Owning service changes state and **records** a state event (ideally via **Transactional Outbox**).
    
2.  Event is emitted with **aggregateId**, **version**, **state (full or partial)**, and **delete flag/tombstone** if removed.
    
3.  Consumers **upsert** their local copy keyed by `aggregateId` after verifying **monotonic version**; deletes remove or mark rows.
    
4.  Consumers use the local view to answer queries or enrich downstream events.
    

## Consequences

**Benefits**

-   Low-latency reads; no runtime dependency on the owner for queries.
    
-   Failure isolation; producers and consumers scale independently.
    
-   Enables **join-less** enrichment and local **CQRS** read models.
    

**Liabilities**

-   **Eventual consistency**; clients may see stale data.
    
-   **Data duplication** and **PII proliferation** → governance burden.
    
-   Requires **ordering** (per aggregate) and **version checks** to avoid reordering bugs.
    
-   Large events can increase broker/storage costs; may need **compaction** and **snapshots**.
    

## Implementation

-   **Event design:**
    
    -   Include `aggregateId`, `version` (monotonic), `occurredAt`, and `state` (full document or patch).
        
    -   For deletes, either publish a **tombstone** (null value, compacted topics) or `deleted=true`.
        
    -   Keep **idempotency** headers: `messageId`, `correlationId`, `causationId`.
        
-   **Transport:**
    
    -   Prefer **Kafka compacted topics** for “latest-state” streams; partition by `aggregateId` for per-key order.
        
    -   For AMQP/JMS, emulate compaction with **upsert semantics** in the consumer store.
        
-   **Consumer upsert policy:**
    
    -   Only apply an event if `event.version > stored.version` for that `aggregateId`.
        
    -   Maintain a **processed message set** (or unique constraint) to dedupe retries.
        
-   **Backfill / bootstrap:**
    
    -   Provide an initial **snapshot** topic/dump; then switch to delta events.
        
    -   Or run a **replay** from the compacted topic to reconstruct the latest state.
        
-   **Security:**
    
    -   Minimize fields; **redact** PII not needed by subscribers; encrypt at rest.
        
-   **Observability:**
    
    -   Lag of consumers, projection staleness, invalid version rate, tombstone rate.
        

---

## Sample Code (Java)

### A) Kafka Streams — Materialize a **Customer** ECST topic as a KTable and enrich an orders stream

```java
// build.gradle: implementation("org.apache.kafka:kafka-streams:3.7.0"), implementation("com.fasterxml.jackson.core:jackson-databind")
import org.apache.kafka.streams.*;
import org.apache.kafka.streams.kstream.*;
import org.apache.kafka.common.serialization.Serdes;
import com.fasterxml.jackson.databind.*;

import java.util.Properties;

public class CustomerEcstMaterializer {

  public static void main(String[] args) {
    Properties p = new Properties();
    p.put(StreamsConfig.APPLICATION_ID_CONFIG, "customer-ecst-materializer");
    p.put(StreamsConfig.BOOTSTRAP_SERVERS_CONFIG, "localhost:9092");

    StreamsBuilder b = new StreamsBuilder();
    ObjectMapper json = new ObjectMapper();

    // Compacted topic with latest customer state (value JSON: full customer doc)
    KTable<String, String> customers = b.table(
        "customers.state.v1", // compacted
        Consumed.with(Serdes.String(), Serdes.String()),
        Materialized.<String, String>as("customers-store"));

    // Orders stream (events referencing customerId)
    KStream<String, String> orders = b.stream("orders.placed.v1",
        Consumed.with(Serdes.String(), Serdes.String()));

    // Enrich orders with customer tier/email from the local KTable
    KStream<String, String> enriched = orders
      .selectKey((k, v) -> extractCustomerId(json, v)) // join key = customerId
      .leftJoin(customers, (orderJson, custJson) -> enrich(json, orderJson, custJson));

    enriched.to("orders.placed.enriched.v1", Produced.with(Serdes.String(), Serdes.String()));

    new KafkaStreams(b.build(), p).start();
  }

  private static String extractCustomerId(ObjectMapper m, String orderJson) {
    try { return m.readTree(orderJson).get("customerId").asText(); }
    catch (Exception e) { return "unknown"; }
  }

  private static String enrich(ObjectMapper m, String orderJson, String customerJson) {
    try {
      var order = m.readTree(orderJson);
      var root  = m.createObjectNode().setAll((com.fasterxml.jackson.databind.node.ObjectNode) order);
      if (customerJson != null) {
        var cust = m.readTree(customerJson);
        root.putObject("customer")
            .put("id", cust.get("id").asText())
            .put("tier", cust.path("tier").asText(null))
            .put("email", cust.path("email").asText(null))
            .put("version", cust.path("version").asLong(0));
      }
      return m.writeValueAsString(root);
    } catch (Exception e) { throw new RuntimeException(e); }
  }
}
```

**Notes:**

-   `customers.state.v1` is a **compacted** topic keyed by `customerId`; values are **full current documents** with a `version` field.
    
-   `customers-store` becomes a **local RocksDB** view; joins don’t call the customer service at runtime.
    

---

### B) Spring Kafka Consumer — **Upsert** a local projection using `version` checks

```java
// build.gradle: implementation("org.springframework.kafka:spring-kafka"),
//               implementation("org.springframework.boot:spring-boot-starter-data-jpa"),
//               implementation("com.fasterxml.jackson.core:jackson-databind")
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.persistence.*;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

@Entity
@Table(name = "customer_view")
class CustomerView {
  @Id String id;
  long version;
  String email;
  String tier;
  boolean deleted;
}

interface CustomerViewRepo extends org.springframework.data.jpa.repository.JpaRepository<CustomerView, String> {}

@Component
public class CustomerStateConsumer {

  private final ObjectMapper json = new ObjectMapper();
  private final CustomerViewRepo repo;

  public CustomerStateConsumer(CustomerViewRepo repo) { this.repo = repo; }

  @KafkaListener(topics = "customers.state.v1", groupId = "customer-projection")
  @Transactional
  public void onState(byte[] bytes) throws Exception {
    var n = json.readTree(bytes);
    String id = n.get("id").asText();
    long ver = n.get("version").asLong();
    boolean deleted = n.path("deleted").asBoolean(false);

    CustomerView current = repo.findById(id).orElse(null);
    if (current != null && ver <= current.version) {
      return; // stale or duplicate event
    }

    if (deleted) {
      // hard delete or flag tombstone
      if (current != null) { repo.delete(current); }
      return;
    }

    CustomerView v = (current == null) ? new CustomerView() : current;
    v.id = id;
    v.version = ver;
    v.email = n.path("email").asText(null);
    v.tier = n.path("tier").asText(null);
    v.deleted = false;
    repo.save(v); // upsert
  }
}
```

**Notes:**

-   Applies **only** newer versions; protects against out-of-order or duplicated deliveries.
    
-   For Kafka tombstones (null values), handle at the listener by removing from the projection.
    

---

## Known Uses

-   **Customer/Account projections** in order or billing services (reduce cross-service GETs).
    
-   **Catalog/Price** replication to checkout and search services for fast queries.
    
-   **Reference data** (country, VAT tables) pushed to many services.
    
-   **Profile & permissions** replicated to edge services/APIs for authorization decisions.
    
-   **IoT device registry** replicated to processing workers for local enrichment.
    

## Related Patterns

-   **Transactional Outbox:** Reliable production of state events from the source service.
    
-   **Materialized View / CQRS:** ECST is a mechanism to build read models in other services.
    
-   **Publish–Subscribe Channel:** Transport for broadcasting state updates.
    
-   **Idempotent Receiver / Inbox:** Required on consumers to handle duplicates and retries.
    
-   **Change Data Capture (CDC):** Alternative data-driven stream; use **Domain Events** when semantic intent matters, or CDC + transformer to synthesize state events.
    
-   **Schema Registry / Message Translator:** Govern versions and adapt schemas between teams.
    
-   **Compacted Topics / Snapshots:** Operational techniques to keep only the latest state.
    

> **Rule of thumb:** Publish **just enough** immutable, versioned state per aggregate; partition by id; let consumers **upsert** guarded by version checks; and govern **PII** carefully.

