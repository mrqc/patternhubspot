# Data Management & Database Pattern — Database per Service

## Pattern Name and Classification

-   **Name:** Database per Service

-   **Classification:** Microservice data ownership & isolation pattern (service-local persistence, decentralized data)


## Intent

Give **each service exclusive ownership** of its **own database** (schema and runtime). Services **never** share tables or perform cross-service joins. They communicate via **APIs/events**, keeping coupling low and autonomy high.

## Also Known As

-   Service-Local Database

-   Private Persistence per Microservice

-   Polyglot Persistence per Service


## Motivation (Forces)

-   **Autonomy & deployability:** Services evolve and deploy independently when data changes don’t ripple across teams.

-   **Decoupling:** No shared DB means no “hidden” cross-team coupling through tables/foreign keys.

-   **Polyglot persistence:** Pick the best store per problem (relational for orders, key-value for sessions, search index for catalog).

-   **Data ownership:** One team is accountable for invariants and schema.


Tensions:

-   **Consistency across services:** No distributed ACID; use **sagas** and **eventual consistency**.

-   **Reporting/joins:** Cross-service queries require **API composition**, **data products**, or **replicated read models**.

-   **Duplication:** Some reference data will be copied or cached; must manage freshness.

-   **Ops overhead:** More databases to provision, secure, back up, and observe.


## Applicability

Use when:

-   You’re building **independent microservices** with clear bounded contexts.

-   Teams need to **deploy independently** with separate change cadences.

-   You can tolerate **eventual consistency** for cross-service workflows.


Be cautious when:

-   You need **global, strongly consistent** transactions across services.

-   The domain is small and a **modular monolith** suffices.

-   Org/ops maturity for **messaging, schema versioning, and observability** is low.


## Structure

```pgsql
+--------------+       API / Events       +----------------+
|  Service A   | <-----------------------> |   Service B    |
| (DB_A owned) |                           |  (DB_B owned)  |
+--------------+                           +----------------+
   ▲     |                                      ▲      |
   |     └── owns schema/tables                  |      └── owns schema/tables
   |                                             |
[ Clients ] -------------------- compose --------------------> [ Aggregated views ]
```

## Participants

-   **Service:** Implements behavior and owns one database (schema, tables, indexes).

-   **Database:** Private to the service; other services access only via **public APIs or events**.

-   **Messaging / Outbox (optional):** Guarantees reliable event publication about internal state changes.

-   **Saga / Process Manager (optional):** Coordinates multi-service workflows via messages.


## Collaboration

1.  A request hits **Service A**; it changes **DB\_A** transactionally.

2.  A’s change is announced via **events** (often through an **Outbox** table with CDC or a relay).

3.  **Service B** consumes the event and updates **DB\_B** accordingly.

4.  Cross-service read models are built by **subscribing** to upstream events.


## Consequences

**Benefits**

-   True **service autonomy** (schema changes don’t break neighbors).

-   Ability to **choose the right database** per service (relational, document, time series…).

-   Clear **ownership & boundaries** (maps to DDD bounded contexts).


**Liabilities**

-   **No cross-DB joins/transactions** → design for **eventual consistency**.

-   **Reporting** across services requires separate **analytical stores** or materialized views.

-   **Data duplication** and **schema evolution** via events must be managed carefully.

-   Operational **surface area** increases (backups, security, IAM, costs).


## Implementation (Key Points)

-   **Hard rule:** Only the owning service accesses its DB. No shared schemas or foreign keys across services.

-   **Reliability:** Use **Outbox pattern** + CDC (or transactional relays) so events aren’t lost.

-   **Sagas:** Model long-running, multi-service transactions with compensations.

-   **Idempotency & versioning:** Events carry IDs and versions; consumers must be idempotent.

-   **Data products / query side:** Build consolidated read models for cross-service analytics.

-   **Security:** Separate credentials, network policies, encryption keys per service.

-   **Observability:** Per-service DB metrics, slow query logs, replication/CDC health.


---

## Sample Code (Java 17): Two Services, Two Databases, Event-Driven Consistency (H2, no frameworks)

> What it demonstrates
>
> -   **OrderService** with its **Orders DB** + **Outbox** (transactional append)
>
> -   **InventoryService** with its **Inventory DB**
>
> -   A tiny **EventBus** & **OutboxRelay** simulating reliable publication
>
> -   **Saga-ish flow:** Place order → reserve stock → confirm/reject order
>
> -   No cross-DB joins; each service touches **only its own** database
>

```java
// File: DatabasePerServiceDemo.java
// Compile: javac -cp h2.jar DatabasePerServiceDemo.java
// Run:     java  -cp .:h2.jar DatabasePerServiceDemo
import java.sql.*;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentLinkedQueue;

/* -------------------------- Infra: Event Bus -------------------------- */
interface Event {}
record OrderPlaced(UUID orderId, String sku, int qty, Instant at) implements Event {}
record InventoryReserved(UUID orderId, String sku, int qty, Instant at) implements Event {}
record InventoryRejected(UUID orderId, String sku, int qty, String reason, Instant at) implements Event {}

interface EventHandler<E extends Event> { void on(E e) throws Exception; }

final class SimpleBus {
  private final Map<Class<?>, List<EventHandler<?>>> subs = new HashMap<>();
  public synchronized <E extends Event> void subscribe(Class<E> type, EventHandler<E> h) {
    subs.computeIfAbsent(type, __ -> new ArrayList<>()).add(h);
  }
  @SuppressWarnings("unchecked")
  public void publish(Event e) {
    for (var h : subs.getOrDefault(e.getClass(), List.of())) {
      try { ((EventHandler<Event>) h).on(e); } catch (Exception ex) { ex.printStackTrace(); }
    }
  }
}

/* -------------------------- Order Service (DB_ORDERS) -------------------------- */
final class OrderService implements AutoCloseable {
  private final Connection cx;          // owns its DB
  private final SimpleBus bus;          // publishes via Outbox relay
  private final Queue<Long> outboxToSend = new ConcurrentLinkedQueue<>();

  OrderService(SimpleBus bus) throws Exception {
    this.bus = bus;
    this.cx = DriverManager.getConnection("jdbc:h2:mem:orders;DB_CLOSE_DELAY=-1");
    cx.setAutoCommit(false);
    try (Statement st = cx.createStatement()) {
      st.execute("""
        CREATE TABLE orders(
          order_id UUID PRIMARY KEY,
          sku VARCHAR(64) NOT NULL,
          qty INT NOT NULL,
          status VARCHAR(16) NOT NULL
        )""");
      st.execute("""
        CREATE TABLE outbox(
          id IDENTITY PRIMARY KEY,
          type VARCHAR(64) NOT NULL,
          payload VARCHAR(1024) NOT NULL,
          created_at TIMESTAMP NOT NULL
        )""");
    }
    cx.commit();

    // Subscribe to inventory outcomes (events published by InventoryService)
    bus.subscribe(InventoryReserved.class,  this::onInventoryReserved);
    bus.subscribe(InventoryRejected.class,  this::onInventoryRejected);
  }

  /** Transaction: insert order + outbox atomically (no cross-service DB touch). */
  public void placeOrder(UUID orderId, String sku, int qty) throws Exception {
    try (PreparedStatement ins = cx.prepareStatement(
           "INSERT INTO orders(order_id, sku, qty, status) VALUES(?,?,?,?)");
         PreparedStatement ob  = cx.prepareStatement(
           "INSERT INTO outbox(type,payload,created_at) VALUES(?,?,?)", Statement.RETURN_GENERATED_KEYS)) {
      ins.setObject(1, orderId); ins.setString(2, sku); ins.setInt(3, qty); ins.setString(4, "PENDING");
      ins.executeUpdate();
      String payload = "%s|%s|%d".formatted(orderId, sku, qty);
      ob.setString(1, "OrderPlaced"); ob.setString(2, payload); ob.setTimestamp(3, Timestamp.from(Instant.now()));
      ob.executeUpdate();
      try (ResultSet rs = ob.getGeneratedKeys()) { if (rs.next()) outboxToSend.add(rs.getLong(1)); }
      cx.commit();
      // separate relay (below) will publish to the bus
    } catch (Exception ex) {
      cx.rollback(); throw ex;
    }
  }

  /** Outbox relay: read unsent rows and publish to the bus (simulating CDC). */
  public void flushOutbox() throws Exception {
    while (true) {
      Long id = outboxToSend.poll();
      if (id == null) break;
      try (PreparedStatement ps = cx.prepareStatement("SELECT type,payload FROM outbox WHERE id=?")) {
        ps.setLong(1, id);
        try (ResultSet rs = ps.executeQuery()) {
          if (!rs.next()) continue;
          String type = rs.getString(1), pl = rs.getString(2);
          String[] a = pl.split("\\|", -1);
          UUID orderId = UUID.fromString(a[0]);
          String sku = a[1]; int qty = Integer.parseInt(a[2]);
          if ("OrderPlaced".equals(type)) {
            bus.publish(new OrderPlaced(orderId, sku, qty, Instant.now()));
          }
        }
      }
      // In a real system, mark "sent" with a watermark; here outbox rows are kept for audit.
    }
  }

  private void onInventoryReserved(InventoryReserved e) throws Exception {
    try (PreparedStatement ps = cx.prepareStatement("UPDATE orders SET status=? WHERE order_id=?")) {
      ps.setString(1, "CONFIRMED"); ps.setObject(2, e.orderId()); ps.executeUpdate(); cx.commit();
    } catch (Exception ex) { cx.rollback(); throw ex; }
  }

  private void onInventoryRejected(InventoryRejected e) throws Exception {
    try (PreparedStatement ps = cx.prepareStatement("UPDATE orders SET status=? WHERE order_id=?")) {
      ps.setString(1, "REJECTED"); ps.setObject(2, e.orderId()); ps.executeUpdate(); cx.commit();
    } catch (Exception ex) { cx.rollback(); throw ex; }
  }

  public String getOrderStatus(UUID orderId) throws Exception {
    try (PreparedStatement ps = cx.prepareStatement("SELECT status FROM orders WHERE order_id=?")) {
      ps.setObject(1, orderId);
      try (ResultSet rs = ps.executeQuery()) { return rs.next() ? rs.getString(1) : "NOT_FOUND"; }
    }
  }

  @Override public void close() throws Exception { cx.close(); }
}

/* -------------------------- Inventory Service (DB_INVENTORY) -------------------------- */
final class InventoryService implements AutoCloseable {
  private final Connection cx;     // owns its DB
  private final SimpleBus bus;

  InventoryService(SimpleBus bus) throws Exception {
    this.bus = bus;
    this.cx = DriverManager.getConnection("jdbc:h2:mem:inventory;DB_CLOSE_DELAY=-1");
    cx.setAutoCommit(false);
    try (Statement st = cx.createStatement()) {
      st.execute("""
        CREATE TABLE stock(
          sku VARCHAR(64) PRIMARY KEY,
          available INT NOT NULL
        )""");
    }
    cx.commit();

    // React to orders
    bus.subscribe(OrderPlaced.class, this::onOrderPlaced);
  }

  public void seed(String sku, int available) throws Exception {
    try (PreparedStatement up = cx.prepareStatement(
          "MERGE INTO stock(sku,available) KEY(sku) VALUES(?,?)")) {
      up.setString(1, sku); up.setInt(2, available); up.executeUpdate(); cx.commit();
    }
  }

  private void onOrderPlaced(OrderPlaced e) throws Exception {
    try {
      int available;
      try (PreparedStatement ps = cx.prepareStatement("SELECT available FROM stock WHERE sku=? FOR UPDATE")) {
        ps.setString(1, e.sku());
        try (ResultSet rs = ps.executeQuery()) { available = rs.next() ? rs.getInt(1) : 0; }
      }
      if (available >= e.qty()) {
        try (PreparedStatement upd = cx.prepareStatement("UPDATE stock SET available=available-? WHERE sku=?")) {
          upd.setInt(1, e.qty()); upd.setString(2, e.sku()); upd.executeUpdate();
        }
        cx.commit();
        bus.publish(new InventoryReserved(e.orderId(), e.sku(), e.qty(), Instant.now()));
      } else {
        cx.rollback(); // nothing changed
        bus.publish(new InventoryRejected(e.orderId(), e.sku(), e.qty(), "INSUFFICIENT_STOCK", Instant.now()));
      }
    } catch (Exception ex) {
      cx.rollback();
      bus.publish(new InventoryRejected(e.orderId(), e.sku(), e.qty(), "ERROR:" + ex.getMessage(), Instant.now()));
    }
  }

  public int available(String sku) throws Exception {
    try (PreparedStatement ps = cx.prepareStatement("SELECT available FROM stock WHERE sku=?")) {
      ps.setString(1, sku); try (ResultSet rs = ps.executeQuery()) { return rs.next() ? rs.getInt(1) : 0; }
    }
  }

  @Override public void close() throws Exception { cx.close(); }
}

/* -------------------------- Demo / Composition Layer -------------------------- */
public class DatabasePerServiceDemo {
  public static void main(String[] args) throws Exception {
    SimpleBus bus = new SimpleBus();
    try (OrderService orders = new OrderService(bus);
         InventoryService inventory = new InventoryService(bus)) {

      // Each service owns its DB; we seed inventory without touching orders DB
      inventory.seed("SKU-1", 3);

      UUID o1 = UUID.randomUUID();
      orders.placeOrder(o1, "SKU-1", 2);  // should succeed
      orders.flushOutbox();                // relay OrderPlaced -> inventory

      Thread.sleep(50); // simulate async

      System.out.println("Order " + o1 + " status: " + orders.getOrderStatus(o1));
      System.out.println("SKU-1 available: " + inventory.available("SKU-1"));

      UUID o2 = UUID.randomUUID();
      orders.placeOrder(o2, "SKU-1", 2);  // should fail (only 1 left)
      orders.flushOutbox();

      Thread.sleep(50);

      System.out.println("Order " + o2 + " status: " + orders.getOrderStatus(o2));
      System.out.println("SKU-1 available: " + inventory.available("SKU-1"));
    }
  }
}
```

**Why this is “database per service”**

-   `OrderService` and `InventoryService` each have their **own H2 database** and **never** read/write the other’s tables.

-   Cross-service consistency is achieved with **events** (via an outbox relay), not with cross-DB transactions or joins.

-   The order state transitions **PENDING → CONFIRMED/REJECTED** depend on events from the inventory service.


> In production you’d replace `SimpleBus` with Kafka/RabbitMQ (or outbox+CDC), add retries, idempotency keys, dead-letter queues, and structured payloads (Avro/JSON Schema).

---

## Known Uses

-   Most microservice platforms (e-commerce: **orders**, **payments**, **inventory**; ride-hailing: **trips**, **drivers**, **billing**).

-   SaaS multi-tenant systems partitioned by bounded contexts (auth, billing, usage).

-   Event-sourced microservices with private stores and **published events** for integration.


## Related Patterns

-   **Outbox Pattern / Transactional Messaging:** Ensure state change + event publish is atomic.

-   **Saga / Process Manager:** Coordinate multi-service workflows with compensations.

-   **CQRS:** Each service may expose commands/queries; read models can be built from events.

-   **API Composition / Backend-for-Frontend:** Build cross-service views without cross-DB joins.

-   **Data Lake / Warehouse:** Consolidate data from multiple services for analytics.

-   **Strangler Fig / Anti-Corruption Layer:** Gradually peel off services with their own databases.


---

### Practical Tips

-   Treat another service’s database as **forbidden**. Integrate only via **APIs/events**.

-   Choose storage per service by access pattern; it’s fine to mix Postgres, Redis, Elastic, etc.

-   Implement **idempotent consumers** and **schema versioning** for events (backward compatible).

-   Use **correlation IDs** and **trace context** across messages for observability.

-   Build **consolidated read models** (or data products) for cross-service reporting instead of ad-hoc joins.

-   Plan for **PII governance** & retention per service; deletion flows may require cross-service orchestration.
