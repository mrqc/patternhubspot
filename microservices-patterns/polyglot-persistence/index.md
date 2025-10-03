# Polyglot Persistence — Microservice Pattern

## Pattern Name and Classification

-   **Name:** Polyglot Persistence
    
-   **Classification:** Data Architecture & Storage Selection Pattern for Microservices
    

## Intent

Use **different storage technologies for different data/usage needs**—within a system or per service—so each workload leverages the **best-fit database** (relational, document, key-value, search, time-series, graph, columnar, etc.) for performance, scalability, developer productivity, and operational safety.

## Also Known As

-   Best-Fit Datastore
    
-   Multi-Store Architecture
    
-   Fit-for-Purpose Storage
    

## Motivation (Forces)

-   **Varied access patterns:** OLTP transactions, full-text search, analytics, time-series metrics, graph traversals—no single database excels at all.
    
-   **Performance & cost:** Tail latency and TCO improve when the store matches the workload: e.g., search in Elasticsearch, cart/session in Redis, orders in Postgres.
    
-   **Team autonomy:** Microservices can evolve independently and choose their own persistence.
    
-   **Resilience & blast radius:** Isolating datastores limits failures and resource contention.
    
-   **Data product thinking:** Purpose-built stores expose data in the most useful shape for consumers.
    

**Tensions**

-   **Consistency:** Multiple datastores increase eventual consistency, duplication, and synchronization complexity.
    
-   **Operations:** More engines → more backups, upgrades, security models, observability.
    
-   **Governance:** Schema/versioning across heterogeneous tech stacks needs discipline.
    
-   **Skills/tooling:** Teams must understand each database’s strengths and pitfalls.
    

## Applicability

Use when:

-   Distinct read/write patterns exist (e.g., transactional orders + search + recommendations).
    
-   A single database can’t meet latency/scale requirements economically.
    
-   Teams are ready for **event-driven synchronization** and **observability** across stores.
    

De-prioritize when:

-   Small product/monolith; one relational DB is sufficient.
    
-   Ops maturity is low (no CDC/outbox, weak backups/monitoring).
    
-   You require **strict distributed ACID** across stores (consider redesign or specialized DBs).
    

## Structure

-   **Service A (Orders):** Relational DB for transactions.
    
-   **Service B (Catalog):** Document store for flexible product shapes.
    
-   **Service C (Search):** Search index denormalized from events/CDC.
    
-   **Optional caches / time-series / graph** per need.
    
-   **Integration plane:** Outbox + CDC + event bus to keep read models and indices up-to-date.
    

```scss
[Event Bus / CDC]
                 ▲      │
                 │      ▼
[Orders Svc] → Postgres ——► (Outbox→) Search Index (ES/Opensearch)
       │
       └──► emits events
[Catalog Svc] → MongoDB (system of record for product docs)
[Edge/BFF] → composes data across services; no cross-DB joins
```

## Participants

-   **Owning Service(s):** Each service owns its datastore(s) and schema/collection/indexes.
    
-   **Primary Store:** System-of-record per aggregate (e.g., orders in Postgres).
    
-   **Secondary Store(s):** Derived views for search, reporting, caching.
    
-   **Outbox/CDC:** Reliable change publication to keep other stores in sync.
    
-   **Projectors/Indexers:** Consumers that maintain derived datastores.
    
-   **Ops Stack:** Backups, DR, monitoring, schema governance for each engine.
    

## Collaboration

1.  A command hits the owning service → **write transaction** in the primary store.
    
2.  Change is recorded in an **outbox** (same transaction) or captured via **CDC**.
    
3.  Projectors/indexers consume changes and **update secondary stores** (search index, cache, analytics).
    
4.  Queries are routed to the **fit-for-purpose** store (e.g., search to ES, details to Postgres).
    
5.  The UI/BFF composes results from multiple services—never cross-joins databases directly.
    

## Consequences

**Benefits**

-   Lower latency and better scalability by using **purpose-built** stores.
    
-   Independent evolution per service (aligns with **Database per Service**).
    
-   Cleaner separation of **system-of-record** vs **derived data**.
    

**Liabilities**

-   More moving parts and **operational overhead**.
    
-   **Eventual consistency** and replay logic required; duplicates possible.
    
-   Security/compliance must be **uniform** across heterogeneous backends.
    
-   Data lineage and governance become more complex.
    

## Implementation

1.  **Declare data ownership:** one **system-of-record** per domain aggregate.
    
2.  **Pick stores by access pattern:**
    
    -   OLTP → Postgres/MySQL
        
    -   Search → Elasticsearch/OpenSearch
        
    -   Catalog/docs → MongoDB
        
    -   Caching/session → Redis
        
    -   Time-series → Prometheus/TimescaleDB/ClickHouse
        
    -   Graph → Neo4j
        
3.  **Synchronize via events:** transactional **outbox** or **CDC** to feed projectors/indices; avoid 2PC.
    
4.  **Model consistency:** idempotent consumers, versioned events, retries, DLQ + replay.
    
5.  **Routing:** send each query to the **appropriate store**; avoid remote joins.
    
6.  **Ops:** per-store backup/restore, retention, encryption, RBAC, dashboards.
    
7.  **Testing:** contract tests for projections; chaos tests for lag/partial outages.
    
8.  **Governance:** schema catalogs, key naming conventions, PII policies across stores.
    

---

## Sample Code (Java, Spring Boot): Postgres (orders) + MongoDB (catalog) + Outbox to Kafka

> Demonstrates **polyglot** read/write: read product from MongoDB (catalog), write order to Postgres (system-of-record), and persist an **outbox** row in the same Postgres transaction for reliable publication to Kafka.  
> (Omit 2PC; treat Mongo read + Postgres write as a standard request with validation. Indexing/search can subscribe to `OrderPlaced` later.)

### `pom.xml` (snippets)

```xml
<dependencies>
  <dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-web</artifactId>
  </dependency>

  <!-- Postgres + JPA for transactional orders -->
  <dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-data-jpa</artifactId>
  </dependency>
  <dependency>
    <groupId>org.postgresql</groupId>
    <artifactId>postgresql</artifactId>
  </dependency>

  <!-- MongoDB for flexible product catalog -->
  <dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-data-mongodb</artifactId>
  </dependency>

  <!-- Kafka for async propagation to other stores -->
  <dependency>
    <groupId>org.springframework.kafka</groupId>
    <artifactId>spring-kafka</artifactId>
  </dependency>

  <dependency>
    <groupId>com.fasterxml.jackson.core</groupId>
    <artifactId>jackson-databind</artifactId>
  </dependency>
</dependencies>
```

### `application.properties` (minimal)

```properties
spring.datasource.url=jdbc:postgresql://orders-db:5432/orders
spring.datasource.username=orders_svc
spring.datasource.password=secret
spring.jpa.hibernate.ddl-auto=validate
spring.jpa.open-in-view=false

spring.data.mongodb.uri=mongodb://catalog-db:27017/catalog

spring.kafka.bootstrap-servers=kafka:9092
app.topic.orderPlaced=orders.placed.v1
```

### SQL migration (Postgres)

```sql
-- db/changelog/001_init.sql
create table if not exists customer_order (
  id uuid primary key,
  customer_id uuid not null,
  total_cents bigint not null,
  created_at timestamptz not null default now()
);

create table if not exists order_line (
  order_id uuid not null references customer_order(id) on delete cascade,
  sku varchar(64) not null,
  qty int not null check (qty > 0),
  price_cents bigint not null,
  primary key (order_id, sku)
);

create table if not exists outbox_event (
  id bigserial primary key,
  aggregate_type varchar(64) not null,
  aggregate_id uuid not null,
  event_type varchar(64) not null,
  payload jsonb not null,
  occurred_at timestamptz not null default now(),
  published boolean not null default false
);

create index if not exists idx_outbox_pub on outbox_event(published, occurred_at);
```

### Mongo document (catalog)

```java
// Product.java
package polyglot.catalog;

import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.mapping.Document;

@Document("products")
public class Product {
  @Id private String id;      // e.g., SKU
  private String name;
  private long priceCents;    // authoritative price in catalog
  private long version;       // for optimistic reads (optional)
  // getters/setters
}
```

```java
// ProductRepository.java
package polyglot.catalog;

import org.springframework.data.mongodb.repository.MongoRepository;

public interface ProductRepository extends MongoRepository<Product, String> {}
```

### JPA entities (orders)

```java
// Order.java
package polyglot.orders;

import jakarta.persistence.*;
import java.time.OffsetDateTime;
import java.util.*;

@Entity @Table(name = "customer_order")
public class Order {
  @Id private UUID id;
  @Column(nullable=false) private UUID customerId;
  @Column(nullable=false) private long totalCents;
  @Column(nullable=false) private OffsetDateTime createdAt = OffsetDateTime.now();

  @OneToMany(mappedBy = "order", cascade = CascadeType.ALL, orphanRemoval = true)
  private List<OrderLine> lines = new ArrayList<>();

  public static Order create(UUID customerId) {
    Order o = new Order();
    o.id = UUID.randomUUID(); o.customerId = customerId; return o;
  }
  public void addLine(String sku, int qty, long priceCents) {
    OrderLine l = new OrderLine(this, sku, qty, priceCents);
    lines.add(l);
    totalCents += priceCents * qty;
  }
  // getters
}
```

```java
// OrderLine.java
package polyglot.orders;

import jakarta.persistence.*;

@Entity @Table(name = "order_line")
public class OrderLine {
  @EmbeddedId private Pk pk = new Pk();
  @MapsId("orderId") @ManyToOne(fetch = FetchType.LAZY) @JoinColumn(name="order_id")
  private Order order;
  @Column(nullable=false) private String sku;
  @Column(nullable=false) private int qty;
  @Column(nullable=false) private long priceCents;

  protected OrderLine() {}
  public OrderLine(Order order, String sku, int qty, long priceCents) {
    this.order = order; this.sku = sku; this.qty = qty; this.priceCents = priceCents; this.pk.orderId = order.getId();
  }

  @Embeddable
  public static class Pk implements java.io.Serializable { public java.util.UUID orderId; public String sku; }
}
```

```java
// OutboxEvent.java
package polyglot.outbox;

import jakarta.persistence.*;

@Entity @Table(name="outbox_event")
public class OutboxEvent {
  @Id @GeneratedValue(strategy=GenerationType.IDENTITY) private Long id;
  private String aggregateType;
  private java.util.UUID aggregateId;
  private String eventType;
  @Lob @Column(columnDefinition="jsonb") private String payload;
  private boolean published = false;
  // constructors/getters/setters
  public OutboxEvent(String aggType, java.util.UUID aggId, String eventType, String payload) {
    this.aggregateType = aggType; this.aggregateId = aggId; this.eventType = eventType; this.payload = payload;
  }
  protected OutboxEvent() {}
}
```

```java
// Repositories
package polyglot.orders;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.UUID;
public interface OrderRepository extends JpaRepository<Order, UUID> {}

package polyglot.outbox;
import org.springframework.data.jpa.repository.JpaRepository;
public interface OutboxRepository extends JpaRepository<OutboxEvent, Long> {
  java.util.List<OutboxEvent> findTop100ByPublishedFalseOrderByIdAsc();
}
```

### Application service (read from Mongo, write to Postgres, enqueue outbox)

```java
// PlaceOrderService.java
package polyglot.app;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import polyglot.catalog.ProductRepository;
import polyglot.orders.Order;
import polyglot.orders.OrderRepository;
import polyglot.outbox.OutboxEvent;

import java.util.Map;
import java.util.UUID;

@Service
public class PlaceOrderService {
  private final ProductRepository products;
  private final OrderRepository orders;
  private final polyglot.outbox.OutboxRepository outbox;
  private final ObjectMapper mapper;

  public PlaceOrderService(ProductRepository products, OrderRepository orders,
                           polyglot.outbox.OutboxRepository outbox, ObjectMapper mapper) {
    this.products = products; this.orders = orders; this.outbox = outbox; this.mapper = mapper;
  }

  @Transactional
  public UUID placeOrder(UUID customerId, String sku, int qty) {
    var product = products.findById(sku)
        .orElseThrow(() -> new IllegalArgumentException("unknown sku " + sku));

    // write to Postgres (system of record)
    var order = Order.create(customerId);
    order.addLine(product.getId(), qty, product.getPriceCents());
    orders.save(order);

    // transactional outbox (same Postgres TX)
    try {
      var payload = mapper.writeValueAsString(Map.of(
          "orderId", order.getId().toString(),
          "customerId", customerId.toString(),
          "lines", java.util.List.of(Map.of("sku", sku, "qty", qty, "priceCents", product.getPriceCents())),
          "totalCents", order.getTotalCents()
      ));
      outbox.save(new OutboxEvent("Order", order.getId(), "OrderPlaced", payload));
    } catch (Exception e) {
      throw new RuntimeException("serialize event failed", e);
    }

    return order.getId();
  }
}
```

### Publisher (read outbox, publish to Kafka → indexers/search/analytics)

```java
// OutboxPublisher.java
package polyglot.outbox;

import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
public class OutboxPublisher {
  private final OutboxRepository repo;
  private final KafkaTemplate<String, String> kafka;
  private final String topic = "orders.placed.v1";

  public OutboxPublisher(OutboxRepository repo, KafkaTemplate<String, String> kafka) {
    this.repo = repo; this.kafka = kafka;
  }

  @Scheduled(fixedDelay = 1000)
  public void publish() {
    var batch = repo.findTop100ByPublishedFalseOrderByIdAsc();
    for (var e : batch) {
      kafka.send(topic, e.getAggregateId().toString(), e.getPayload());
      e.setPublished(true);
      repo.save(e);
    }
  }
}
```

### API (edge)

```java
// OrdersController.java
package polyglot.api;

import org.springframework.web.bind.annotation.*;
import polyglot.app.PlaceOrderService;

import java.util.Map;
import java.util.UUID;

@RestController
@RequestMapping("/orders")
public class OrdersController {
  private final PlaceOrderService service;

  public OrdersController(PlaceOrderService service) { this.service = service; }

  @PostMapping
  public Map<String, Object> place(@RequestBody Map<String, Object> req) {
    var orderId = service.placeOrder(
        UUID.fromString((String) req.get("customerId")),
        (String) req.get("sku"),
        ((Number) req.get("qty")).intValue()
    );
    return Map.of("orderId", orderId.toString(), "status", "CREATED");
  }
}
```

**Notes**

-   **Polyglot usage** in this sample:
    
    -   MongoDB holds **catalog** (flexible product schema).
        
    -   Postgres is **system-of-record** for orders with ACID guarantees.
        
    -   Kafka event enables **secondary stores** (e.g., Elasticsearch indexer) to sync asynchronously.
        
-   No 2PC between Mongo and Postgres; the write is committed in Postgres only. If the product changed between read and write, detect via product **version** or re-price downstream.
    
-   For search, run an **indexer** that subscribes to `orders.placed.v1` and writes to Elasticsearch (omitted for brevity).
    
-   Add **DLQ + replay** for robust outbox publishing.
    

---

## Known Uses

-   **Amazon/Netflix/Uber/Spotify** publicly discuss using multiple storage engines: relational for core transactions, NoSQL for scale/flexibility, **search indices** for discovery, **caches** for latency.
    
-   **E-commerce**: relational orders/payments, document catalog, search index, Redis cart/session, analytics warehouse.
    
-   **IoT/Monitoring**: time-series DB for metrics, object store for blobs, relational metadata.
    

## Related Patterns

-   **Database per Service:** Ownership boundary that enables polyglot choices per service.
    
-   **CQRS & Read Models:** Derived projections in specialized stores for query performance.
    
-   **Transactional Outbox & CDC:** Reliable propagation from system-of-record to secondary stores.
    
-   **Event Sourcing:** Uses an event store as primary; projections may live in other databases.
    
-   **API Composition / BFF:** Compose results across services instead of cross-DB joins.
    
-   **Cache-Aside / Materialized View:** Common read optimizations layered on polyglot stores.

