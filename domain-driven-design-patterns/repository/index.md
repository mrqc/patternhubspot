# Repository (Domain-Driven Design)

## Pattern Name and Classification

**Name:** Repository  
**Classification:** DDD tactical pattern (domain layer persistence abstraction)

---

## Intent

Provide a **collection-like abstraction** for **retrieving and persisting aggregates by identity**, isolating the domain model from persistence concerns and enabling testability, clean boundaries, and a consistent *unit-of-work* style.

---

## Also Known As

-   Aggregate Repository

-   Domain Repository

-   Persistence Facade (domain-facing)


---

## Motivation (Forces)

-   **Separation of concerns:** Keep domain logic free of SQL/ORM/broker calls.

-   **Ubiquitous language:** “Load `Order#123`”, “save customer” reads like the domain.

-   **Testability:** Substitute in-memory or fake implementations.

-   **Transaction boundaries:** Centralize consistency per aggregate.

-   **Portability:** Swap storage tech (JPA/JDBC/NoSQL/Event Store) without changing domain code.


Tensions to balance:

-   **Leaky abstractions:** Don’t turn repositories into query kitchens (avoid anemic “DAO soup”).

-   **Aggregate discipline:** Only roots get their own repository; child entities flow through the root.

-   **Query needs vs coupling:** Rich read queries may belong to **Query/Projection** (CQRS) instead of repository.

-   **Performance knobs:** Lazy vs eager, batching, N+1 avoidance—keep out of domain API while still observably efficient.


---

## Applicability

Use a Repository when:

-   You have **aggregates** accessed by identity with lifecycle operations (create, retrieve, delete).

-   You need **transactional consistency** within the aggregate boundary.

-   The domain must be **storage-agnostic**.


Prefer alternatives when:

-   You only need **read models** with arbitrary filters/joins → use dedicated **query services/projections**.

-   You’re **event-sourcing** the aggregate → use an **event-sourced repository** specialized for streams & snapshots.


---

## Structure

-   **Repository Interface (domain):** `findById`, `save`, and task-specific selectors that align with the aggregate’s invariants.

-   **Repository Implementation (infrastructure):** JPA/JDBC/NoSQL/Event Store details.

-   **Unit of Work / Transaction Manager:** Coordinates atomic commit.

-   **Mappers/Assemblers:** Convert persistence models ↔ domain models when using clean architecture.

-   **Specifications (optional):** Encapsulate complex selection criteria without leaking persistence details.


---

## Participants

-   **Aggregate Root:** The unit of persistence and consistency.

-   **Repository (Domain Port):** Contract used by application/domain services.

-   **Infrastructure Adapter:** Concrete repo (JPA/JDBC/…).

-   **Unit of Work / Transaction:** Ensures atomic changes within a use case.

-   **Specifications / Queries (optional):** Domain-friendly selectors.


---

## Collaboration

1.  **Application service** starts a use case/transaction.

2.  It **loads** an aggregate via `repository.findById(id)` (or factory for creation).

3.  It **invokes behavior** on the aggregate (domain methods).

4.  It **saves** via `repository.save(aggregate)`.

5.  Unit of work **commits** and publishes events (e.g., outbox).


---

## Consequences

**Benefits**

-   Domain **decoupled** from storage and frameworks.

-   Clear **transactional** and **lifecycle** semantics.

-   Easier **testing** with in-memory fakes.

-   Supports **evolution** of persistence without domain churn.


**Liabilities**

-   Over-abstracted repositories can hide necessary performance controls.

-   Putting **ad hoc queries** into repositories leads to bloat—prefer read models/CQRS.

-   Poor aggregate boundaries yield **chatty** repositories and N+1 issues.

-   Mapping layers add **boilerplate** (worth it for bigger systems).


---

## Implementation

**Guidelines**

-   **One repository per aggregate root.**

-   **Identity-based methods:** `findById`, `exists`, `save`, optionally `delete`. Avoid generic CRUD for non-roots.

-   Keep **method names intention-revealing** (`findByBusinessKey`, `findPendingForBilling`).

-   **Do not expose** persistence types (Entities, RowSets) in the domain API.

-   **Transactions** live in the application service; the repo performs work within that boundary.

-   For JPA: use **optimistic locking** (`@Version`) and **aggregate-level** fetch plans; avoid exposing lazy collections outward.

-   For JDBC: compose **mappers**; persist the entire aggregate as one unit (no partial saves across aggregates).

-   For ES: repository **appends and replays events**; snapshots are an optimization.

-   Consider **Outbox** to publish domain events after commit.


---

## Sample Code (Java)

### Domain Model (Aggregate Root)

```java
// Value Objects
public record OrderId(String value) {
    public OrderId {
        if (value == null || value.isBlank()) throw new IllegalArgumentException("orderId");
    }
    public static OrderId newId() { return new OrderId(java.util.UUID.randomUUID().toString()); }
}

public record Money(java.math.BigDecimal amount, String currency) {
    public Money {
        if (amount == null || currency == null) throw new IllegalArgumentException();
        if (amount.scale() > 2) throw new IllegalArgumentException("scale>2");
    }
    public Money add(Money other) {
        if (!currency.equals(other.currency)) throw new IllegalArgumentException("currency mismatch");
        return new Money(amount.add(other.amount), currency);
    }
}

// Aggregate Root
import java.time.Instant;
import java.util.*;

public final class Order {
    private final OrderId id;
    private final String customerId;
    private final List<Line> lines = new ArrayList<>();
    private String status; // "PLACED" | "PAID" | "CANCELLED"
    private long version;  // optimistic locking token (mapped in persistence)
    private Instant createdAt;
    private Instant updatedAt;

    public static Order newDraft(String customerId) {
        return new Order(OrderId.newId(), customerId, "PLACED", Instant.now());
    }

    public Order(OrderId id, String customerId, String status, Instant createdAt) {
        this.id = id; this.customerId = customerId; this.status = status;
        this.createdAt = createdAt; this.updatedAt = createdAt;
    }

    public void addLine(String sku, int qty, Money unitPrice) {
        if (qty <= 0) throw new IllegalArgumentException("qty>0");
        lines.add(new Line(sku, qty, unitPrice));
        touch();
    }
    public void markPaid() {
        if (!"PLACED".equals(status)) throw new IllegalStateException("wrong state");
        status = "PAID"; touch();
    }
    public java.math.BigDecimal total() {
        return lines.stream()
            .map(l -> l.unitPrice.amount().multiply(java.math.BigDecimal.valueOf(l.qty)))
            .reduce(java.math.BigDecimal.ZERO, java.math.BigDecimal::add);
    }
    private void touch() { updatedAt = Instant.now(); }

    public OrderId id() { return id; }
    public String customerId() { return customerId; }
    public String status() { return status; }
    public List<Line> lines() { return List.copyOf(lines); }
    public long version() { return version; }        // mapped by persistence
    void setVersion(long v) { this.version = v; }    // package-private for mapper

    public record Line(String sku, int qty, Money unitPrice) {}
}
```

### Domain Port (Repository Interface)

```java
import java.util.Optional;

public interface OrderRepository {
    Optional<Order> findById(OrderId id);
    void save(Order order);               // insert or update as one unit
    boolean exists(OrderId id);
    void delete(OrderId id);              // rarely used; consider soft delete
    // Task-focused selectors (keep few and intention-revealing)
    java.util.List<Order> findPlacedSince(java.time.Instant since, int limit);
}
```

---

### Infrastructure Option A: JPA Implementation (pragmatic mapping)

```java
// Persistence model (JPA entity) kept separate from domain type
import jakarta.persistence.*;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.*;

@Entity @Table(name = "orders")
class OrderJpa {
    @Id String id;
    String customerId;
    String status;
    Instant createdAt;
    Instant updatedAt;
    @Version long version;

    @OneToMany(mappedBy = "order", cascade = CascadeType.ALL, orphanRemoval = true, fetch = FetchType.EAGER)
    List<OrderLineJpa> lines = new ArrayList<>();
}

@Entity @Table(name = "order_line")
class OrderLineJpa {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    Long id;
    String sku;
    int qty;
    BigDecimal unitPrice;
    String currency;
    @ManyToOne(fetch = FetchType.LAZY) @JoinColumn(name = "order_id")
    OrderJpa order;
}
```

```java
// Mapper between domain and JPA entities
final class OrderMapper {
    static Order toDomain(OrderJpa e) {
        var o = new Order(new OrderId(e.id), e.customerId, e.status, e.createdAt);
        e.lines.forEach(l -> o.addLine(l.sku, l.qty, new Money(l.unitPrice, l.currency)));
        // restore version/timestamps
        o.setVersion(e.version);
        return o;
    }

    static OrderJpa toJpa(Order o, OrderJpa target) {
        var e = target != null ? target : new OrderJpa();
        e.id = o.id().value();
        e.customerId = o.customerId();
        e.status = o.status();
        if (e.createdAt == null) e.createdAt = java.time.Instant.now();
        e.updatedAt = java.time.Instant.now();
        e.version = o.version();
        // rewrite lines (simple approach)
        e.lines.clear();
        for (var l : o.lines()) {
            var jl = new OrderLineJpa();
            jl.sku = l.sku();
            jl.qty = l.qty();
            jl.unitPrice = l.unitPrice().amount();
            jl.currency = l.unitPrice().currency();
            jl.order = e;
            e.lines.add(jl);
        }
        return e;
    }
}
```

```java
// Spring/JPA-backed repository
import jakarta.persistence.EntityManager;
import jakarta.persistence.LockModeType;
import org.springframework.transaction.annotation.Transactional;

public class JpaOrderRepository implements OrderRepository {
    private final EntityManager em;
    public JpaOrderRepository(EntityManager em) { this.em = em; }

    @Override
    public Optional<Order> findById(OrderId id) {
        var e = em.find(OrderJpa.class, id.value());
        return Optional.ofNullable(e).map(OrderMapper::toDomain);
    }

    @Override @Transactional
    public void save(Order order) {
        var existing = em.find(OrderJpa.class, order.id().value(), LockModeType.OPTIMISTIC);
        var jpa = OrderMapper.toJpa(order, existing);
        if (existing == null) em.persist(jpa);
        // if existing, state already updated; JPA dirty checking will flush
        // optimistic locking via @Version protects concurrent writers
    }

    @Override
    public boolean exists(OrderId id) {
        return em.find(OrderJpa.class, id.value()) != null;
    }

    @Override @Transactional
    public void delete(OrderId id) {
        var e = em.find(OrderJpa.class, id.value());
        if (e != null) em.remove(e);
    }

    @Override
    public java.util.List<Order> findPlacedSince(java.time.Instant since, int limit) {
        var list = em.createQuery("""
            select o from OrderJpa o 
            where o.createdAt >= :since and o.status='PLACED' 
            order by o.createdAt asc
        """, OrderJpa.class)
        .setParameter("since", since)
        .setMaxResults(limit)
        .getResultList();
        return list.stream().map(OrderMapper::toDomain).toList();
    }
}
```

---

### Infrastructure Option B: Plain JDBC (explicit control)

```java
import java.sql.*;
import java.util.*;

public class JdbcOrderRepository implements OrderRepository {
    private final javax.sql.DataSource ds;

    public JdbcOrderRepository(javax.sql.DataSource ds) { this.ds = ds; }

    @Override
    public Optional<Order> findById(OrderId id) {
        try (var con = ds.getConnection()) {
            Order order = null;
            try (var ps = con.prepareStatement("""
                select id, customer_id, status, created_at, updated_at, version
                from orders where id=?
            """)) {
                ps.setString(1, id.value());
                try (var rs = ps.executeQuery()) {
                    if (rs.next()) {
                        order = new Order(new OrderId(rs.getString("id")),
                                          rs.getString("customer_id"),
                                          rs.getString("status"),
                                          rs.getTimestamp("created_at").toInstant());
                        order.setVersion(rs.getLong("version"));
                    }
                }
            }
            if (order == null) return Optional.empty();

            try (var ps = con.prepareStatement("""
                select sku, qty, unit_price, currency from order_line where order_id=? order by id
            """)) {
                ps.setString(1, id.value());
                try (var rs = ps.executeQuery()) {
                    while (rs.next()) {
                        order.addLine(rs.getString("sku"),
                                      rs.getInt("qty"),
                                      new Money(rs.getBigDecimal("unit_price"), rs.getString("currency")));
                    }
                }
            }
            return Optional.of(order);
        } catch (SQLException e) {
            throw new RuntimeException(e);
        }
    }

    @Override
    public void save(Order order) {
        try (var con = ds.getConnection()) {
            con.setAutoCommit(false);
            try {
                // upsert order (optimistic concurrency)
                int updated;
                try (var ps = con.prepareStatement("""
                    update orders set customer_id=?, status=?, updated_at=now(), version=version+1
                    where id=? and version=?
                """)) {
                    ps.setString(1, order.customerId());
                    ps.setString(2, order.status());
                    ps.setString(3, order.id().value());
                    ps.setLong(4, order.version());
                    updated = ps.executeUpdate();
                }
                if (updated == 0) {
                    try (var ps = con.prepareStatement("""
                        insert into orders(id, customer_id, status, created_at, updated_at, version)
                        values(?, ?, ?, now(), now(), 0)
                    """)) {
                        ps.setString(1, order.id().value());
                        ps.setString(2, order.customerId());
                        ps.setString(3, order.status());
                        ps.executeUpdate();
                    }
                }

                // rewrite lines (simple approach; use diffing if needed)
                try (var ps = con.prepareStatement("delete from order_line where order_id=?")) {
                    ps.setString(1, order.id().value());
                    ps.executeUpdate();
                }
                try (var ps = con.prepareStatement("""
                    insert into order_line(order_id, sku, qty, unit_price, currency)
                    values(?, ?, ?, ?, ?)
                """)) {
                    for (var l : order.lines()) {
                        ps.setString(1, order.id().value());
                        ps.setString(2, l.sku());
                        ps.setInt(3, l.qty());
                        ps.setBigDecimal(4, l.unitPrice().amount());
                        ps.setString(5, l.unitPrice().currency());
                        ps.addBatch();
                    }
                    ps.executeBatch();
                }

                con.commit();
            } catch (SQLException ex) {
                con.rollback();
                throw ex;
            } finally {
                con.setAutoCommit(true);
            }
        } catch (SQLException e) {
            throw new RuntimeException(e);
        }
    }

    @Override
    public boolean exists(OrderId id) {
        try (var con = ds.getConnection();
             var ps = con.prepareStatement("select 1 from orders where id=?")) {
            ps.setString(1, id.value());
            try (var rs = ps.executeQuery()) { return rs.next(); }
        } catch (SQLException e) { throw new RuntimeException(e); }
    }

    @Override
    public void delete(OrderId id) {
        try (var con = ds.getConnection();
             var ps = con.prepareStatement("delete from orders where id=?")) {
            ps.setString(1, id.value());
            ps.executeUpdate();
        } catch (SQLException e) { throw new RuntimeException(e); }
    }

    @Override
    public java.util.List<Order> findPlacedSince(java.time.Instant since, int limit) {
        try (var con = ds.getConnection();
             var ps = con.prepareStatement("""
                 select id from orders where created_at>=? and status='PLACED' order by created_at asc limit ?
             """)) {
            ps.setTimestamp(1, java.sql.Timestamp.from(since));
            ps.setInt(2, limit);
            try (var rs = ps.executeQuery()) {
                var list = new java.util.ArrayList<Order>();
                while (rs.next()) list.add(findById(new OrderId(rs.getString("id"))).orElseThrow());
                return list;
            }
        } catch (SQLException e) { throw new RuntimeException(e); }
    }
}
```

---

### Infrastructure Option C: Event-Sourced Repository (sketch)

```java
public final class EventSourcedOrderRepository implements OrderRepository {
    private final EventStore store; // append/read by stream
    private final SnapshotStore<Order> snapshots;
    private final EventSerializer serde;

    @Override
    public Optional<Order> findById(OrderId id) {
        var agg = EventSourcingSupport.rehydrateOrder(id.value(), store, snapshots, serde);
        return Optional.ofNullable(agg);
    }

    @Override
    public void save(Order order) {
        // append uncommitted events with expectedVersion; publish via outbox/relay
    }

    // exists, delete, findPlacedSince → via projections/read models, not by replay
}
```

---

## Known Uses

-   **E-commerce:** `OrderRepository`, `CartRepository`, `CatalogRepository`.

-   **Banking/Fintech:** `AccountRepository`, `LedgerRepository` with strong concurrency guarantees.

-   **Logistics:** `ShipmentRepository`, `WarehouseRepository`.

-   **IAM:** `UserRepository`, `RoleRepository`.

-   **Event-sourced systems:** Repositories wrap event stores with snapshots and projections.


---

## Related Patterns

-   **Aggregate / Aggregate Root:** The unit managed by a repository.

-   **Factory:** Creates aggregates; repository persists them.

-   **Unit of Work / Transaction Script (coordination only):** Coordinates atomic commits around repository calls.

-   **Specification / Query Object:** Encapsulate selection logic without leaking persistence.

-   **CQRS:** Complex reads via projections; repositories focus on aggregate writes/identity lookups.

-   **Transactional Outbox:** Publish domain/integration events reliably after repository save.
