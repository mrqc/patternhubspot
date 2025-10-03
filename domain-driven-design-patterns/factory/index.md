# Factory (Domain-Driven Design)

## Pattern Name and Classification

**Name:** Factory  
**Classification:** DDD tactical pattern (domain layer creation pattern). Often realized via *Factory Method*, *Abstract Factory*, or *Domain Factory* objects.

---

## Intent

Encapsulate **complex creation logic** for Entities/Aggregates/Value Objects so that:

-   invariants hold **at the moment of creation**,

-   required collaborators and policies are enforced, and

-   clients obtain **valid, fully-initialized** domain objects via intention-revealing APIs.


---

## Also Known As

-   Domain Factory

-   Aggregate Factory

-   Creation Service (domain)

-   Factory Method / Abstract Factory (GoF forms)


---

## Motivation (Forces)

-   **Validity at birth:** Aggregates must be created in a consistent state (e.g., Order must contain at least one line; currency must match).

-   **Ubiquitous language:** Creation should read like the business (“registerCustomer”, “openAccount”, “createOffer”).

-   **Hide technical choices:** ID generation, timestamps, default policies, number rounding, and event emission are not clients’ concern.

-   **Avoid anemic constructors:** Large, error-prone constructors with flags and optional parameters hinder readability and correctness.

-   **Separate concerns:** Keep creation rules in the domain layer, away from application/UI plumbing.


Tensions:

-   **Where to place validation?** Some checks belong inside aggregates; factories orchestrate but shouldn’t bypass invariants.

-   **Dependencies:** Factories must stay domain-centric; avoid direct infrastructure (DB, HTTP).

-   **Variations:** Product variants and market rules may require different factory implementations.


---

## Applicability

Use a Factory when:

-   Construction requires **multiple steps**, **policies**, or **derived values**.

-   You must **generate identity** at creation (e.g., UUIDs, nano time sequences).

-   Different **variants** of an aggregate exist (e.g., “trial vs paid subscription”).

-   The aggregate must **emit domain events** upon creation.

-   You want to **stabilize API** against constructor changes.


Prefer simple constructors or static factories when:

-   Creation is trivial and **cannot be invalid** (e.g., small Value Objects with local validation).

-   No external policies or variants are involved.


---

## Structure

-   **Factory (Interface / Class):** Intention-revealing creation operations returning domain types.

-   **Aggregate / Entity:** Receives validated inputs; enforces invariants internally.

-   **Value Objects:** Inputs/outputs; support readability and correctness.

-   **Policies/Domain Services:** Consulted during creation (e.g., pricing, risk rules).

-   **ID/Timestamp Providers:** Domain-facing abstractions for technical concerns (clock, idGenerator) to keep code deterministic.


---

## Participants

-   **Factory:** Centralizes creation logic; constructs valid aggregates/entities.

-   **Aggregate/Entity:** Owns invariants; provides private/package constructors and/or factory methods.

-   **Domain Services/Policies:** Encapsulate calculations and cross-aggregate checks used by the factory.

-   **Repositories (optional as ports):** Only for **existence checks** or uniqueness rules via domain interfaces—no persistence orchestration.

-   **IDGenerator/Clock (ports):** Provide deterministic IDs/times.


---

## Collaboration

1.  Application Service invokes **Factory** with intention-revealing parameters.

2.  Factory consults **policies/services** and **derives** needed values.

3.  Factory calls **aggregate private constructor** or **aggregate factory method** to enforce invariants and raise initial events.

4.  Application Service persists the new aggregate via **Repository** and continues the use case.


---

## Consequences

**Benefits**

-   Single, expressive entry point for complex creation.

-   Aggregates start life **valid**; fewer scattered checks.

-   Reduces coupling to constructors; **easier evolution** of creation rules.

-   Supports **variants** via different factory implementations.


**Liabilities**

-   Can become a **god-constructor** dumping ground—keep it cohesive.

-   Risk of **leaking infrastructure**; keep factories pure domain.

-   Over-abstracting simple creation adds ceremony.


---

## Implementation

**Guidelines**

-   Prefer **intention-revealing names**: `createOrder`, `openAccount`, `issueInvoice`.

-   Keep the aggregate’s constructor **package-private or private**; expose factory methods (`Order.create(...)`) or external factory class.

-   Inject **domain-facing ports** (e.g., `IdGenerator`, `Clock`, `PricingPolicy`, `UniquenessChecker`).

-   Validate **preconditions** in the factory; **invariants** in the aggregate (double safety net).

-   If the aggregate emits **Domain Events** at birth, record them inside the aggregate.

-   For multiple variants, use **Abstract Factory** or **Strategy** inside a single factory.

-   Keep factories **stateless**; they compute and delegate, not store state.


**Anti-patterns to avoid**

-   Factories that **persist** objects themselves (that’s the Repository’s job).

-   Passing raw primitives everywhere (use **Value Objects**).

-   Constructors with boolean toggles / long parameter lists.


---

## Sample Code (Java)

### Domain Ports and Value Objects

```java
public interface IdGenerator {
    String nextId();
}

public interface DomainClock {
    java.time.Instant now();
}

public record CustomerId(String value) {
    public CustomerId {
        if (value == null || value.isBlank()) throw new IllegalArgumentException("id");
    }
}

public record Money(java.math.BigDecimal amount, String currency) {
    public Money {
        if (amount == null || currency == null) throw new IllegalArgumentException();
        if (amount.scale() > 2) throw new IllegalArgumentException("scale>2");
    }
    public boolean isPositive() { return amount.signum() > 0; }
}

public record Sku(String value) {
    public Sku {
        if (value == null || value.isBlank()) throw new IllegalArgumentException("sku");
    }
}
```

### Aggregate Root (Order)

```java
import java.time.Instant;
import java.util.*;

public final class Order {
    private final String id;
    private final CustomerId customerId;
    private final List<OrderLine> lines = new ArrayList<>();
    private boolean placed;
    private Instant createdAt;
    private final List<Object> pendingEvents = new ArrayList<>();

    // ctor deliberately package-private: creation via factory only
    Order(String id, CustomerId customerId, Instant createdAt) {
        this.id = Objects.requireNonNull(id);
        this.customerId = Objects.requireNonNull(customerId);
        this.createdAt = Objects.requireNonNull(createdAt);
    }

    // invariant-guarded operation used by factory
    void addLine(Sku sku, int qty, Money unitPrice) {
        if (qty <= 0) throw new IllegalArgumentException("qty>0");
        if (!unitPrice.isPositive()) throw new IllegalArgumentException("price>0");
        lines.add(new OrderLine(sku, qty, unitPrice));
    }

    void place() {
        if (placed) throw new IllegalStateException("already placed");
        if (lines.isEmpty()) throw new IllegalStateException("no lines");
        placed = true;
        pendingEvents.add(new OrderPlaced(id, customerId.value(), totalAmount(), "EUR"));
    }

    public String id() { return id; }
    public boolean isPlaced() { return placed; }
    public List<Object> pullEvents() {
        var copy = List.copyOf(pendingEvents);
        pendingEvents.clear();
        return copy;
    }

    private java.math.BigDecimal totalAmount() {
        return lines.stream()
            .map(l -> l.unitPrice.amount().multiply(java.math.BigDecimal.valueOf(l.qty)))
            .reduce(java.math.BigDecimal.ZERO, java.math.BigDecimal::add);
    }

    static final class OrderLine {
        final Sku sku; final int qty; final Money unitPrice;
        OrderLine(Sku sku, int qty, Money unitPrice) {
            this.sku = sku; this.qty = qty; this.unitPrice = unitPrice;
        }
    }

    // Domain event emitted on creation/placement
    public record OrderPlaced(String orderId, String customerId, java.math.BigDecimal total, String currency) {}
}
```

### Factory Interface and Implementation

```java
import java.util.List;

public interface OrderFactory {
    Order createDraft(CustomerId customerId, List<LineRequest> lines);
    Order createAndPlace(CustomerId customerId, List<LineRequest> lines);
    record LineRequest(Sku sku, int qty, Money unitPrice) {}
}

public final class DefaultOrderFactory implements OrderFactory {
    private final IdGenerator ids;
    private final DomainClock clock;
    private final PricingPolicy pricing; // domain service (e.g., discount rules)

    public DefaultOrderFactory(IdGenerator ids, DomainClock clock, PricingPolicy pricing) {
        this.ids = ids; this.clock = clock; this.pricing = pricing;
    }

    @Override
    public Order createDraft(CustomerId customerId, List<LineRequest> requests) {
        validate(customerId, requests);
        var order = new Order(ids.nextId(), customerId, clock.now());
        for (var r : requests) {
            var priced = pricing.apply(r.sku(), r.qty(), r.unitPrice()); // e.g., discount rounding, min price
            order.addLine(r.sku(), r.qty(), priced);
        }
        return order; // not yet placed
    }

    @Override
    public Order createAndPlace(CustomerId customerId, List<LineRequest> requests) {
        var order = createDraft(customerId, requests);
        order.place(); // emits OrderPlaced event
        return order;
    }

    private void validate(CustomerId customerId, List<LineRequest> reqs) {
        if (customerId == null) throw new IllegalArgumentException("customerId");
        if (reqs == null || reqs.isEmpty()) throw new IllegalArgumentException("at least one line");
    }
}

// Example domain policy used by the factory
interface PricingPolicy {
    Money apply(Sku sku, int qty, Money unitPrice);
}

final class NoDiscountPolicy implements PricingPolicy {
    @Override public Money apply(Sku sku, int qty, Money unitPrice) { return unitPrice; }
}
```

### Application Service (Orchestration)

```java
public interface OrderRepository {
    void save(Order order);
}

public final class OrderApplicationService {
    private final OrderFactory factory;
    private final OrderRepository orders;

    public OrderApplicationService(OrderFactory factory, OrderRepository orders) {
        this.factory = factory; this.orders = orders;
    }

    // @Transactional
    public String placeOrder(CustomerId customerId, java.util.List<OrderFactory.LineRequest> lines) {
        var order = factory.createAndPlace(customerId, lines);
        orders.save(order);
        // publish domain events from order.pullEvents() via Outbox, etc.
        return order.id();
    }
}
```

### Alternative Forms

-   **Factory Method (on aggregate):**

    ```java
    public static Order create(CustomerId customerId, List<LineRequest> lines, IdGenerator ids, DomainClock clock, PricingPolicy pricing) { ... }
    ```

    Keeps creation close to the aggregate; still injects domain ports.

-   **Abstract Factory (for variants):**

    ```java
    interface SubscriptionFactory { Subscription createTrial(...); Subscription createPaid(...); }
    class EUSubscriptionFactory implements SubscriptionFactory { ... }
    class USSubscriptionFactory implements SubscriptionFactory { ... }
    ```


---

## Known Uses

-   **E-commerce:** Order creation with tax/discount/rules, SKU validation, promotional pricing.

-   **Banking:** Account opening with KYC policy and initial limits.

-   **Insurance:** Policy issuance with underwriting rules and effective dates.

-   **Identity/Access:** User registration with password policy and uniqueness checks (via domain port).

-   **Subscriptions/SaaS:** Trial vs. paid plan factories, regional variants.


---

## Related Patterns

-   **Entity / Aggregate:** Factories create them in valid states; aggregates still enforce invariants.

-   **Value Object:** Ideal for factory parameters and computed results.

-   **Domain Service / Policy / Specification:** Factories compose these to evaluate rules during creation.

-   **Repository:** Persists created aggregates; separation from creation concerns.

-   **Domain Event:** Emitted during/after creation for downstream reactions.

-   **Builder:** Useful for assembling complex value objects; combine with factory for readability.
