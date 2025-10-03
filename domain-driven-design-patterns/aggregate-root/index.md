
# Aggregate Root — Domain-Driven Design Pattern

---

## Pattern Name and Classification

-   **Name:** Aggregate Root

-   **Category:** Domain-Driven Design (DDD) / Tactical Modeling

-   **Level:** Object modeling + Transaction boundary


---

## Intent

Define a **single authoritative entry point** to an aggregate that:

-   Enforces **invariants** for all contained entities/value objects,

-   Controls **lifecycle and access** to internal objects,

-   Serves as the **transactional consistency boundary** and **persistence unit**.


---

## Also Known As

-   Root Entity

-   Consistency Gatekeeper


---

## Motivation (Forces)

-   Complex domains have clusters of objects that **must change together** to preserve rules (invariants).

-   Unrestricted references between entities cause **data corruption** and **transactional leaks**.

-   The Aggregate Root centralizes business operations so:

    -   External code **talks to the root only**.

    -   The root **validates commands** and applies changes atomically.

    -   Persistence and concurrency are handled at **aggregate granularity**.


**Forces / Trade-offs**

-   Roots **too large** → contention, slow transactions.

-   Roots **too small** → invariants span multiple aggregates; need sagas/process managers.

-   Strict encapsulation can feel “heavy” vs. direct repository access to sub-entities.


---

## Applicability

Use an Aggregate Root when:

-   Multiple entities/values form a **cohesive whole** with **strong consistency** needs.

-   There are **business rules** that must be true after every transaction.

-   You need a clear **unit of concurrency** and **persistence**.


Avoid or split roots when:

-   Entities can evolve **independently** (only eventual consistency needed between them).

-   Cross-aggregate references and workflows dominate (favor domain services / sagas).


---

## Structure

-   **Aggregate Root (Entity):** Public API for commands; owns identity; enforces invariants.

-   **Internal Entities:** Identities scoped to the root; not referenced externally.

-   **Value Objects:** Immutable; validate themselves; replace over mutate.

-   **Repository:** Loads/saves **the root** (and its cluster) as one unit.

-   **Domain Events (optional):** Emitted by the root to inform other parts of the model.


```scss
[Client/App Service]
        │  calls methods
        ▼
 [Aggregate Root] ── manages ──> [Entity]*, [ValueObject]*
        │
        ├─ raises ──> [Domain Events]
        ▼
   [Repository] (persists root & children)
```

---

## Participants

-   **Aggregate Root:** Gatekeeper; executes commands; ensures invariants.

-   **Entities / Value Objects (inside):** State modeled under root control.

-   **Repository (per aggregate type):** Persistence boundary.

-   **Domain Service (optional):** Coordinates multiple aggregates without breaking encapsulation.

-   **Application Service:** Orchestrates use cases, transactions, and repositories.


---

## Collaboration

-   **Application Service** loads the root from a **Repository**, invokes root methods, then saves it.

-   **Domain Services / Sagas** coordinate across roots via **domain events** or commands.

-   **Factories** create valid aggregate instances (enforcing initial invariants).


---

## Consequences

**Benefits**

-   Strong encapsulation and **invariant safety**.

-   Clear **transactional scope** and **locking** unit.

-   Simplifies persistence mapping and caching (aggregate = unit).

-   Encourages rich domain behavior (methods, not anemic setters).


**Liabilities**

-   Boundary design is **hard**; wrong size harms performance or integrity.

-   Requires discipline: **no external references** to internals.

-   Potential verbosity vs. “quick” CRUD.


---

## Implementation

1.  **Identify invariants** that must hold after each transaction → define root around them.

2.  **Model the root** with behavior-rich methods (commands) that validate inputs and enforce rules.

3.  **Hide internals** (package-private/protected); expose read-only views if needed.

4.  **One repository per aggregate type**; prohibit repositories for internal entities.

5.  **Handle concurrency** at aggregate level (optimistic version).

6.  **Raise domain events** inside the root when state changes matter to others.

7.  **Keep roots small**; prefer references by **ID** across aggregates; integrate via events/sagas.


---

## Sample Code (Java, Order as Aggregate Root)

```java
// Value Object: immutable, self-validating
public record Money(long cents) {
    public Money {
        if (cents < 0) throw new IllegalArgumentException("negative money");
    }
    public Money add(Money other) { return new Money(this.cents + other.cents); }
    public boolean gte(Money other) { return this.cents >= other.cents; }
}

// Value Object
public record ProductId(String value) {
    public ProductId {
        if (value == null || value.isBlank()) throw new IllegalArgumentException("product id");
    }
}

// Entity within aggregate (no public setters; identity scoped by root)
final class OrderItem {
    private final ProductId productId;
    private int quantity;
    private final Money unitPrice;

    OrderItem(ProductId productId, int quantity, Money unitPrice) {
        if (quantity <= 0) throw new IllegalArgumentException("qty>0");
        this.productId = productId;
        this.quantity = quantity;
        this.unitPrice = unitPrice;
    }

    Money subtotal() { return new Money(unitPrice.cents() * quantity); }
    ProductId productId() { return productId; }

    void increase(int delta) {
        if (delta <= 0) throw new IllegalArgumentException("delta>0");
        this.quantity += delta;
    }
}

// Domain Event (simple POJO)
public record OrderConfirmedEvent(java.util.UUID orderId, long totalCents) {}
```

```java
import java.util.*;
import java.util.concurrent.CopyOnWriteArrayList;

// Aggregate Root
public class Order {
    private final UUID id;
    private final Map<String, OrderItem> items = new LinkedHashMap<>();
    private boolean confirmed = false;
    private long version; // optimistic locking
    private final List<Object> domainEvents = new CopyOnWriteArrayList<>();

    private Order(UUID id) { this.id = id; }

    // Factory to ensure valid creation
    public static Order createNew() { return new Order(UUID.randomUUID()); }

    public UUID id() { return id; }
    public boolean isConfirmed() { return confirmed; }
    public long version() { return version; }
    public List<Object> pullEvents() { // outbox pattern helper
        var copy = List.copyOf(domainEvents);
        domainEvents.clear();
        return copy;
    }

    // Command methods (enforce invariants)
    public void addItem(ProductId pid, int qty, Money price) {
        assertNotConfirmed();
        items.compute(pid.value(), (k, existing) -> {
            if (existing == null) return new OrderItem(pid, qty, price);
            existing.increase(qty);
            return existing;
        });
    }

    public void confirm() {
        assertNotConfirmed();
        if (items.isEmpty()) throw new IllegalStateException("order must have items");
        confirmed = true;
        domainEvents.add(new OrderConfirmedEvent(id, total().cents()));
    }

    public Money total() {
        long cents = items.values().stream().mapToLong(i -> i.subtotal().cents()).sum();
        return new Money(cents);
    }

    private void assertNotConfirmed() {
        if (confirmed) throw new IllegalStateException("order already confirmed");
    }
}
```

```java
// Repository boundary (only for aggregate root)
public interface OrderRepository {
    Optional<Order> findById(UUID id);
    void save(Order order);
}
```

```java
// Application Service orchestrating a use case (transactional boundary)
public class CheckoutApplicationService {
    private final OrderRepository orders;
    private final DomainEventPublisher publisher; // e.g., outbox -> Kafka

    public CheckoutApplicationService(OrderRepository orders, DomainEventPublisher publisher) {
        this.orders = orders; this.publisher = publisher;
    }

    public UUID createAndConfirm(Map<ProductId, Money> itemsWithPrice) {
        Order order = Order.createNew();
        itemsWithPrice.forEach((pid, price) -> order.addItem(pid, 1, price));
        order.confirm();

        orders.save(order);                   // persist aggregate atomically
        order.pullEvents().forEach(publisher::publish); // publish after commit
        return order.id();
    }
}

interface DomainEventPublisher {
    void publish(Object event);
}
```

**Notes**

-   Only the `Order` root is accessible externally; `OrderItem` is package-private and managed by the root.

-   Invariants: non-empty order at confirmation; no modifications after confirmation.

-   Optimistic locking via `version` (e.g., JPA `@Version`) should be added in persistence mapping.

-   Cross-aggregate references should be by **ID**; communication via **events**.


---

## Known Uses

-   **E-commerce:** `Order` root encapsulating items, addresses, payments.

-   **Banking:** `Account` root enforcing balance and overdraft rules.

-   **Inventory:** `Shipment` or `StockItem` roots ensuring allocation invariants.

-   **Event-sourced systems:** Each root corresponds to an **event stream**.


---

## Related Patterns

-   **Aggregate:** The cluster that the root governs.

-   **Repository:** Persistence interface at aggregate granularity.

-   **Domain Event:** Emitted by roots to integrate across boundaries.

-   **Factory:** Builds valid root instances.

-   **Saga / Process Manager:** Coordinates workflows spanning multiple roots.

-   **Value Object / Entity:** Building blocks inside the aggregate.
