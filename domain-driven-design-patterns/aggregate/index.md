
# Aggregate — Domain Driven Design Pattern

---

## Pattern Name and Classification

-   **Name:** Aggregate

-   **Category:** Domain-Driven Design (DDD) / Tactical Modeling Pattern

-   **Level:** Domain Model Integrity Pattern


---

## Intent

Define a **cluster of domain objects** that are treated as a single unit for data changes.  
Each aggregate has a **root entity** (Aggregate Root) which enforces invariants and guarantees consistency across the whole aggregate.

---

## Also Known As

-   Aggregate Root Pattern

-   Consistency Boundary Pattern


---

## Motivation (Forces)

-   Complex domains contain many entities and value objects that are related.

-   Without boundaries, **invariants can be violated** when multiple entities are changed independently.

-   Aggregates create **transactional consistency boundaries**, simplifying reasoning about correctness.

-   Aggregates ensure that:

    -   External objects can only reference the root.

    -   Invariants are preserved inside aggregate.

    -   Persistence and transactions are scoped.


**Forces & trade-offs:**

-   Aggregates too large → performance issues and lock contention.

-   Aggregates too small → invariants spread across multiple transactions.

-   Correct balance is needed to align **consistency requirements vs scalability**.


---

## Applicability

Use Aggregates when:

-   Entities and value objects form **a cohesive whole** with rules.

-   You need to ensure **strong invariants** across related objects.

-   You want to clearly define **transactional boundaries** in the domain model.

-   Using **event sourcing**, aggregates are natural sources of events.


Avoid when:

-   Entities are loosely coupled and don’t need strong consistency.

-   Invariants span multiple aggregates (may require domain services or sagas).


---

## Structure

1.  **Aggregate Root (Entity):** The only entry point from outside.

2.  **Internal Entities / Value Objects:** Contained and managed inside aggregate.

3.  **Repository:** Accesses and persists aggregates as a whole.


```css
[Repository]
        │
        ▼
 [Aggregate Root]───┐
     │              │
  [Entity]     [Value Object]
     │
  [Entity]
```

---

## Participants

-   **Aggregate Root (Entity):** Controls access, enforces invariants.

-   **Entities (inside aggregate):** Have identity but only accessible via root.

-   **Value Objects:** Part of aggregate, immutable.

-   **Repository:** Provides persistence for the whole aggregate.

-   **Domain Services:** Sometimes orchestrate multiple aggregates.


---

## Collaboration

-   Aggregates collaborate via **domain services** and **application services**.

-   Aggregates raise **domain events** for inter-aggregate communication.

-   Repositories return **whole aggregates**, not individual entities.

-   Aggregates are often consumed by **application services** in DDD layered architecture.


---

## Consequences

**Benefits**

-   Enforces **consistency** within transactional boundaries.

-   Simplifies **domain logic** by scoping invariants.

-   Reduces complexity by limiting references between objects.

-   Natural unit of persistence (aggregate = one repository).


**Liabilities**

-   Choosing wrong aggregate boundaries leads to inefficiency.

-   Requires careful balance between **consistency and scalability**.

-   Potential performance issues if aggregates are too “chatty” with each other.

-   Sometimes leads to “anemic” aggregates if invariants aren’t well defined.


---

## Implementation

1.  **Identify Aggregate Boundaries:** Group entities/values that change together.

2.  **Define Root Entity:** All external references go through the root.

3.  **Enforce Invariants in Root:** Business rules applied in methods of the root.

4.  **Design Repositories:** Provide access only to root-level aggregates.

5.  **Persist Aggregates:** Persist as a single unit (using ORM, event sourcing, or document DB).

6.  **Raise Domain Events:** When aggregates change, publish events for other aggregates.


---

## Sample Code (Java Example — Order Aggregate)

```java
// Value Object
public record Product(String productId, String name, int price) {}

// Entity inside Aggregate
public class OrderItem {
    private final Product product;
    private int quantity;

    public OrderItem(Product product, int quantity) {
        this.product = product;
        this.quantity = quantity;
    }

    public int subtotal() {
        return product.price() * quantity;
    }
}

// Aggregate Root
import java.util.*;

public class Order {
    private final UUID orderId;
    private final List<OrderItem> items = new ArrayList<>();
    private boolean confirmed = false;

    public Order(UUID orderId) {
        this.orderId = orderId;
    }

    // Business rule: Only aggregate root can add items
    public void addItem(Product product, int quantity) {
        if (confirmed) {
            throw new IllegalStateException("Cannot add items after confirmation");
        }
        items.add(new OrderItem(product, quantity));
    }

    // Business rule: Invariant enforcement
    public void confirm() {
        if (items.isEmpty()) {
            throw new IllegalStateException("Order must contain at least one item");
        }
        this.confirmed = true;
    }

    public int totalPrice() {
        return items.stream().mapToInt(OrderItem::subtotal).sum();
    }

    public UUID getOrderId() {
        return orderId;
    }
}

// Repository interface
public interface OrderRepository {
    void save(Order order);
    Optional<Order> findById(UUID orderId);
}
```

**Notes**:

-   Only `Order` (aggregate root) is referenced externally.

-   Invariants (cannot confirm empty order, cannot modify after confirmation) enforced in root.

-   `OrderRepository` persists the whole aggregate, not individual items.


---

## Known Uses

-   **E-commerce:** Order aggregate with items and shipping info.

-   **Banking:** Account aggregate with transactions.

-   **Insurance:** Policy aggregate with coverage and claims.

-   **Event Sourcing systems:** Each aggregate is event-sourced as a single stream.


---

## Related Patterns

-   **Entity (DDD):** Aggregates are clusters of entities.

-   **Value Object (DDD):** Often part of an aggregate.

-   **Repository (DDD):** Works at aggregate granularity.

-   **Domain Event:** Aggregates publish events for external communication.

-   **Aggregate Factory:** Creates new aggregates consistently.

-   **Saga / Process Manager:** Coordinate across multiple aggregates.
