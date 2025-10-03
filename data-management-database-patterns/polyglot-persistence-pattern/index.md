
# Data Management & Database Pattern — Polyglot Persistence

## Pattern Name and Classification

-   **Name:** Polyglot Persistence

-   **Classification:** Architectural data pattern (using multiple data stores/technologies within a system, each chosen for a specific workload)


## Intent

Use **different storage technologies**—relational, document, key-value, time-series, search, graph, etc.—**side by side**, picking the **best fit** for each bounded context or access pattern, while keeping ownership and synchronization explicit.

## Also Known As

-   Polyglot Storage

-   Multimodel-by-Design (not the same as a single multimodel DB)


## Motivation (Forces)

-   **One size doesn’t fit all:** OLTP integrity ≠ full-text search ≠ analytics ≠ high-throughput caching.

-   **Performance & ergonomics:** Use **SQL** for joins/constraints, **search engines** for text relevance, **KV** for low-latency reads, **columnar** for scans, **time-series** for TS workloads, etc.

-   **Team autonomy:** Each service can optimize its own store and evolution.

-   **Trade-offs:** More moving parts, distributed consistency, skills & ops per tech, data duplication.


## Applicability

Use when:

-   Workloads are **heterogeneous** (OLTP, search, cache, analytics, events).

-   You can define **clear bounded contexts** and **data ownership**.

-   Eventual consistency across models is acceptable (or you can orchestrate consistency).


Avoid/Adapt when:

-   Team/ops cannot manage multiple technologies; start simple.

-   Strong global transactions across stores are required (consider carefully, or use sagas/TCC).


## Structure

```pgsql
+-----------------+         +-------------------+         +-------------------+
Commands  |  Write Model    |  outbox |  Projections /    |  push   |  Read Models       |
---------->  (Relational)   |-------->|  CDC/ETL/Streams  |-------->|  Cache, Search,    |
          +-----------------+         +-------------------+         |  Analytics, TSDB   |
                         ^                                         +-------------------+
                         |                 Queries hit the best-fit read model
                         +-------------------- API / BFF ----------------------------->
```

## Participants

-   **Bounded Context / Service:** Owns a domain and its primary store.

-   **Primary Store (System of Record):** Typically relational or document DB.

-   **Read Models:** Cache (KV), search index, OLAP table, feature store, etc.

-   **Integration Mechanism:** Outbox + CDC, event bus/stream, scheduled ETL, or dual-write with safeguards.

-   **Consumers:** APIs, dashboards, ML, search.


## Collaboration

1.  A service persists changes in its **system of record** (SoR).

2.  The same transaction appends to an **outbox**.

3.  A **relay/CDC** publishes change events.

4.  **Projectors** update **polyglot read models** (cache, search, warehouse).

5.  Reads go to the **best-fit** store; cache aside/refresh policies keep latency low.


## Consequences

**Benefits**

-   Each workload uses the **right tool**, improving performance and developer experience.

-   **Scalability** and **resilience** via decoupled models and stores.

-   Enables specialized features (relevance ranking, vector search, time-window queries).


**Liabilities**

-   **Consistency management** between stores; eventual consistency and replays.

-   **Operational complexity** (backups, upgrades, security, observability) for multiple systems.

-   **Data modeling duplication** and **schema evolution** across models.


## Implementation (Key Points)

-   **Ownership:** One and only one **system of record** per entity. Others are **derived**.

-   **Reliability:** Use **Outbox + CDC** (or transactional relays) to publish changes; consumers must be **idempotent**.

-   **Schema evolution:** Version events/payloads; upcasters for old data; migrations for read models.

-   **Backfills & rebuilds:** Make read models **replayable** from a log.

-   **Security:** Per-store IAM, encryption, masking of PII across copies.

-   **Observability:** Correlate across stores with trace/ids; monitor **lag**, **hit rates**, **rebuild times**.

-   **Cost control:** Tier storage, compact/expire read models, and size caches prudently.


---

## Sample Code (Java 17): One SoR (H2 / relational) + Cache (KV) + Search (in-JVM inverted index) with Outbox Relay

> Demonstrates:
>
> -   **ProductService** writes to **H2** (system of record) and an **Outbox** in the same transaction
>
> -   A background **Relay** publishes events to **Cache** (KV) and **Search Index** (inverted index)
>
> -   **Reads** use cache/search; **rebuild** by replaying outbox  
      >     *(No external search/redis dependency—cache and index are in-memory for clarity. Replace with Redis/Elasticsearch in production.)*
>

```java
// File: PolyglotPersistenceDemo.java
// Compile: javac -cp h2.jar PolyglotPersistenceDemo.java
// Run:     java  -cp .:h2.jar PolyglotPersistenceDemo
import java.sql.*;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;
import java.util.stream.Collectors;

/* ------------- Domain ------------- */
record Product(long id, String sku, String name, String description, int priceCents) {}

sealed interface DomainEvent permits ProductUpserted, ProductDeleted {
  String type();
  String key(); // sku
}
record ProductUpserted(String sku, String name, String description, int priceCents) implements DomainEvent {
  public String type() { return "ProductUpserted"; }
  public String key() { return sku; }
}
record ProductDeleted(String sku) implements DomainEvent {
  public String type() { return "ProductDeleted"; }
  public String key() { return sku; }
}

/* ------------- System of Record (H2) + Outbox ------------- */
final class ProductRepository implements AutoCloseable {
  private final Connection cx;
  ProductRepository() throws Exception {
    cx = DriverManager.getConnection("jdbc:h2:mem:prod;DB_CLOSE_DELAY=-1");
    cx.setAutoCommit(false);
    try (Statement st = cx.createStatement()) {
      st.execute("""
        CREATE TABLE products(
          id IDENTITY PRIMARY KEY,
          sku VARCHAR(64) UNIQUE NOT NULL,
          name VARCHAR(255) NOT NULL,
          description CLOB,
          price_cents INT NOT NULL
        );
      """);
      st.execute("""
        CREATE TABLE outbox(
          id IDENTITY PRIMARY KEY,
          event_type VARCHAR(64) NOT NULL,
          payload CLOB NOT NULL,
          created_at TIMESTAMP NOT NULL
        );
      """);
    }
    cx.commit();
  }

  public void upsert(ProductUpserted e) throws Exception {
    try (PreparedStatement ps = cx.prepareStatement("""
        MERGE INTO products(sku,name,description,price_cents)
        KEY(sku) VALUES(?,?,?,?)
      """);
         PreparedStatement ob = cx.prepareStatement("""
        INSERT INTO outbox(event_type,payload,created_at) VALUES(?,?,?)
      """)) {
      ps.setString(1, e.sku()); ps.setString(2, e.name());
      ps.setString(3, e.description()); ps.setInt(4, e.priceCents()); ps.executeUpdate();
      ob.setString(1, e.type());
      ob.setString(2, "%s|%s|%s|%d".formatted(e.sku(), esc(e.name()), esc(e.description()), e.priceCents()));
      ob.setTimestamp(3, Timestamp.from(Instant.now()));
      ob.executeUpdate();
      cx.commit();
    } catch (Exception ex) { cx.rollback(); throw ex; }
  }

  public void delete(ProductDeleted e) throws Exception {
    try (PreparedStatement del = cx.prepareStatement("DELETE FROM products WHERE sku=?");
         PreparedStatement ob  = cx.prepareStatement(
             "INSERT INTO outbox(event_type,payload,created_at) VALUES(?,?,?)")) {
      del.setString(1, e.sku()); del.executeUpdate();
      ob.setString(1, e.type());
      ob.setString(2, e.sku());
      ob.setTimestamp(3, Timestamp.from(Instant.now()));
      ob.executeUpdate();
      cx.commit();
    } catch (Exception ex) { cx.rollback(); throw ex; }
  }

  public List<Map<String,Object>> readOutboxBatch(long lastId, int limit) throws Exception {
    try (PreparedStatement ps = cx.prepareStatement("""
      SELECT id, event_type, payload FROM outbox WHERE id > ? ORDER BY id ASC LIMIT ?
    """)) {
      ps.setLong(1, lastId); ps.setInt(2, limit);
      try (ResultSet rs = ps.executeQuery()) {
        List<Map<String,Object>> out = new ArrayList<>();
        while (rs.next()) {
          Map<String,Object> row = new HashMap<>();
          row.put("id", rs.getLong(1));
          row.put("type", rs.getString(2));
          row.put("payload", rs.getString(3));
          out.add(row);
        }
        return out;
      }
    }
  }

  private static String esc(String s){ return s.replace("|", "\\|"); }

  @Override public void close() throws Exception { cx.close(); }
}

/* ------------- Polyglot Read Models: Cache (KV) + Search (inverted index) ------------- */
final class ProductCache {
  private final Map<String, Product> map = new ConcurrentHashMap<>();
  public void put(Product p) { map.put(p.sku(), p); }
  public void remove(String sku) { map.remove(sku); }
  public Optional<Product> get(String sku) { return Optional.ofNullable(map.get(sku)); }
}

final class SearchIndex {
  // trivial inverted index: token -> set of SKUs
  private final Map<String, Set<String>> idx = new ConcurrentHashMap<>();
  private final Map<String, Product> bySku = new ConcurrentHashMap<>();

  public void upsert(Product p) {
    remove(p.sku());
    bySku.put(p.sku(), p);
    for (String tok : tokenize(p.name() + " " + p.description())) {
      idx.computeIfAbsent(tok, __ -> ConcurrentHashMap.newKeySet()).add(p.sku());
    }
  }
  public void remove(String sku) {
    Product old = bySku.remove(sku);
    if (old == null) return;
    for (String tok : tokenize(old.name() + " " + old.description())) {
      Set<String> s = idx.get(tok);
      if (s != null) { s.remove(sku); if (s.isEmpty()) idx.remove(tok); }
    }
  }
  public List<Product> search(String query, int limit) {
    Set<String> skus = Arrays.stream(tokenize(query))
        .map(tok -> idx.getOrDefault(tok, Set.of()))
        .flatMap(Set::stream)
        .collect(Collectors.toCollection(LinkedHashSet::new));
    return skus.stream().limit(limit).map(bySku::get).filter(Objects::nonNull).toList();
  }
  private static String[] tokenize(String s) {
    return s.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9 ]"," ").split("\\s+");
  }
}

/* ------------- Outbox Relay -> projects SoR changes into read models ------------- */
final class OutboxRelay implements AutoCloseable {
  private final ProductRepository repo;
  private final ProductCache cache;
  private final SearchIndex search;
  private volatile boolean running = true;
  private long lastId = 0;
  private final Thread thread;

  OutboxRelay(ProductRepository repo, ProductCache cache, SearchIndex search) {
    this.repo = repo; this.cache = cache; this.search = search;
    this.thread = new Thread(this::run, "outbox-relay"); thread.setDaemon(true); thread.start();
  }

  private void run() {
    while (running) {
      try {
        var batch = repo.readOutboxBatch(lastId, 100);
        for (var row : batch) {
          long id = (Long) row.get("id");
          String type = (String) row.get("type");
          String payload = (String) row.get("payload");
          if ("ProductUpserted".equals(type)) {
            String[] a = payload.split("(?<!\\\\)\\|", -1);
            String sku = a[0];
            String name = a[1].replace("\\|", "|");
            String desc = a[2].replace("\\|", "|");
            int price = Integer.parseInt(a[3]);
            Product p = new Product(0, sku, name, desc, price);
            cache.put(p);
            search.upsert(p);
          } else if ("ProductDeleted".equals(type)) {
            String sku = payload;
            cache.remove(sku);
            search.remove(sku);
          }
          lastId = id;
        }
        Thread.sleep(100); // simple polling
      } catch (Exception e) {
        e.printStackTrace();
        try { Thread.sleep(500); } catch (InterruptedException ignored) {}
      }
    }
  }

  @Override public void close() {
    running = false;
    try { thread.join(1000); } catch (InterruptedException ignored) {}
  }
}

/* ------------- Facade/API ------------- */
final class ProductService implements AutoCloseable {
  private final ProductRepository repo;
  private final ProductCache cache;
  private final SearchIndex search;
  private final OutboxRelay relay;

  ProductService() throws Exception {
    this.repo = new ProductRepository();
    this.cache = new ProductCache();
    this.search = new SearchIndex();
    this.relay = new OutboxRelay(repo, cache, search);
  }

  public void upsert(String sku, String name, String desc, int priceCents) throws Exception {
    repo.upsert(new ProductUpserted(sku, name, desc, priceCents));
  }
  public void delete(String sku) throws Exception {
    repo.delete(new ProductDeleted(sku));
  }
  public Optional<Product> getFast(String sku) {
    return cache.get(sku); // best-effort low latency
  }
  public List<Product> search(String q, int k) { return search.search(q, k); }

  @Override public void close() throws Exception { relay.close(); repo.close(); }
}

/* ------------- Demo ------------- */
public class PolyglotPersistenceDemo {
  public static void main(String[] args) throws Exception {
    try (ProductService svc = new ProductService()) {
      svc.upsert("SKU-1", "Noise Cancelling Headphones", "Over-ear ANC, BT 5.3", 19999);
      svc.upsert("SKU-2", "Wireless Mouse", "Ergonomic 6-button, 2.4G", 2999);
      svc.upsert("SKU-3", "Mechanical Keyboard", "Hot-swap switches, RGB", 8999);
      Thread.sleep(200); // allow relay to project

      System.out.println("FAST GET (cache): " + svc.getFast("SKU-2").orElse(null));
      System.out.println("SEARCH 'wireless': " + svc.search("wireless", 10));
      System.out.println("SEARCH 'rgb keyboard': " + svc.search("rgb keyboard", 10));

      svc.delete("SKU-2");
      Thread.sleep(200);
      System.out.println("After delete, FAST GET SKU-2: " + svc.getFast("SKU-2"));
      System.out.println("Search 'wireless': " + svc.search("wireless", 10));
    }
  }
}
```

**What this illustrates**

-   **Relational SoR** (H2) persists products and emits **Outbox events** atomically.

-   A **Relay** projects changes into **two different read models**: an in-memory **KV cache** and a **search index**—a miniature polyglot setup.

-   Reads hit **best-fit** models (cache/search) while writes remain authoritative in the SoR.

-   Swap the cache for **Redis** and the index for **Elasticsearch/OpenSearch** without changing the write flow.


---

## Known Uses

-   **E-commerce:** Orders in RDBMS; catalog in **search index**; sessions in **KV cache**; recommendations in **feature store**.

-   **Fintech:** Ledger in RDBMS; balances cached; fraud features in time-series DB; analytics in warehouse.

-   **IoT:** Device registry (document DB), telemetry (time-series), alerting (search), analytics (lake/warehouse).

-   **Social / Content:** User graph (graph DB), posts (document store), search (Lucene/ES), counters (KV).


## Related Patterns

-   **Database per Service:** Each service owns its store; polyglot across services.

-   **CQRS:** Natural pairing—writes in SoR; multiple **read models** for queries.

-   **Outbox / CDC:** Reliable event propagation from SoR to other stores.

-   **Saga / TCC:** Cross-store workflow consistency without XA.

-   **Materialized View / Summary Tables:** Read models in analytical stores.

-   **Cache Aside / Read-Through:** Caching policy for low-latency reads.


---

### Practical Tips

-   Pick a **single SoR** per entity; treat others as **derivations**.

-   Use **idempotent** projectors and keep **offsets** to replay/rebuild read models.

-   Document **SLAs** and **freshness** per model (cache TTLs, search lag, analytics load windows).

-   Centralize **schema registry** & **event versioning**; use contracts/tests for downstream consumers.

-   Automate **backfills** and **disaster recovery**: from snapshots + event logs.

-   Invest in **observability**: track outbox lag, projector errors, cache hit rate, and search latency.
