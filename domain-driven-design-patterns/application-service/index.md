
# Application Service — Domain-Driven Design Pattern

---

## Pattern Name and Classification

-   **Name:** Application Service

-   **Category:** DDD / Layered Architecture / Orchestration Pattern

-   **Level:** Use-case layer (transaction + workflow boundary)


---

## Intent

Coordinate a **use case** by orchestrating domain objects and external resources:

-   **Invoke domain model** (Aggregates, Domain Services) to enforce business rules,

-   Handle **transactions, security, idempotency, and mapping**,

-   Interact with **infrastructure ports** (messaging, gateways) and return DTOs.


> Application Services contain **workflow**, not core business rules—the latter live in the domain model.

---

## Also Known As

-   Use-Case Service

-   Orchestration Service

-   Application Layer / Service Layer (DDD sense, not anemic “god service”)


---

## Motivation (Forces)

-   Keep **domain model pure** and technology-agnostic.

-   Provide a **single transactional boundary** per use case.

-   Centralize **cross-cutting concerns**: validation, authorization, idempotency, retries, outbox, mapping.

-   Prevent **anemic domain models** by letting the model do the business logic while the app service coordinates.


**Forces / Trade-offs**

-   Too much logic here → “fat” application layer; risks bypassing the domain.

-   Too thin → scattered orchestration (controllers doing too much).

-   Requires discipline around **what belongs where**.


---

## Applicability

Use Application Services when:

-   You expose domain capabilities via **APIs/CLI/Jobs**.

-   A use case touches **multiple aggregates or ports** (payments, notifications, inventory).

-   You need **transaction demarcation** and **outbox/event publishing**.


Avoid misusing when:

-   You’re tempted to place **business rules** here (keep them in aggregates/domain services).

-   A use case is **pure query** → consider a **Query/Read Model** (CQRS).


---

## Structure

-   **Controller/Adapter**: accepts transport concerns (HTTP/REST/RPC), converts to command.

-   **Application Service**: validates, authorizes, opens transaction, loads aggregates, invokes domain methods, persists, publishes events, maps to DTO.

-   **Domain Layer**: Aggregates, Value Objects, Domain Services (pure business logic).

-   **Ports (Outbound)**: PaymentGateway, NotificationPort, etc. (implemented by adapters).

-   **Repository**: Loads/saves aggregates atomically.


```css
[Controller] → [Application Service] → (Repositories → Aggregates/Domain Services)
                          │
                          ├─ Outbox/Events → Message Bus
                          └─ Ports (Payment, Email, ACL)
```

---

## Participants

-   **Application Service** – Orchestrates the use case and transaction.

-   **Aggregates** – Enforce invariants, execute business rules.

-   **Domain Services** – Domain logic spanning multiple aggregates when needed.

-   **Repositories** – Persist aggregates.

-   **Ports/Adapters** – External systems.

-   **DTOs/Mappers** – Transport ↔ domain conversion.

-   **Unit of Work / Transaction Manager** – Ensures atomicity.


---

## Collaboration

-   With **Aggregates** (command methods) and **Repositories** (load/save).

-   With **Domain Events**/**Outbox** to integrate asynchronously after commit.

-   With **Saga/Process Manager** for long-running, multi-step workflows.

-   With **ACL** when crossing bounded contexts.

-   With **CQRS** (commands here; queries in separate read services).


---

## Consequences

**Benefits**

-   Clear **use-case boundary** and **transaction scope**.

-   Keeps controllers thin and domain pure.

-   Central place for **authorization, idempotency, validation, retries**.

-   Improves testability (mock ports, repo; assert interactions).


**Liabilities**

-   Risk of becoming a **god object** if business rules leak in.

-   Requires strict layering and mapping discipline.

-   More classes (DTOs, commands, mappers) → ceremony.


Mitigations:

-   Enforce “**orchestrate, don’t calculate**” in app layer.

-   Architecture linting / code reviews to keep rules in the domain.


---

## Implementation

1.  **Define Commands/DTOs** for inputs and outputs (transport-neutral).

2.  **Authorize & Validate** early (roles, invariants that don’t need I/O).

3.  **Start Transaction** (usually per command/use case).

4.  **Load Aggregate(s)**, call **behavioral methods** (no setters), handle domain events.

5.  **Persist** and **publish events** (outbox or post-commit hooks).

6.  **Call Ports** for side effects that must happen after commit (or via event handlers).

7.  **Return DTO**; **map** domain objects to output.


Guidelines:

-   One **Repository per Aggregate**; no repo for inner entities.

-   Use **optimistic locking** (`@Version`) for concurrency.

-   Prefer **idempotency keys** for external calls / retried commands.

-   Keep app service **stateless**; no cached domain state.


---

## Sample Code (Java, Spring Boot)

**Scenario:** Place an order. The application service orchestrates: validate → load `Order` aggregate → add items → confirm → save → enqueue domain events (outbox) → optionally call payment port after commit.

```java
// === 1) Transport DTOs / Commands ===
public record PlaceOrderCommand(
        String customerId,
        java.util.List<OrderItemRequest> items,
        String idempotencyKey // to guard against retries
) {}

public record OrderItemRequest(String productId, int quantity, long unitPriceCents) {}

public record OrderSummaryDTO(String orderId, long totalCents, String status) {}
```

```java
// === 2) Domain primitives ===
public record Money(long cents) {
    public Money {
        if (cents < 0) throw new IllegalArgumentException("negative money");
    }
    public Money add(Money other) { return new Money(this.cents + other.cents); }
}

public record ProductId(String value) {
    public ProductId {
        if (value == null || value.isBlank()) throw new IllegalArgumentException("product id");
    }
}
```

```java
// === 3) Aggregate (simplified) ===
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
    void increase(int delta) { if (delta <= 0) throw new IllegalArgumentException("delta>0"); this.quantity += delta; }
}

public final class Order {
    private final java.util.UUID id;
    private final java.util.Map<String, OrderItem> items = new java.util.LinkedHashMap<>();
    private boolean confirmed = false;
    @jakarta.persistence.Version
    private long version;

    private Order(java.util.UUID id) { this.id = id; }

    public static Order createNew() { return new Order(java.util.UUID.randomUUID()); }
    public java.util.UUID id() { return id; }
    public boolean isConfirmed() { return confirmed; }

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
        if (items.isEmpty()) throw new IllegalStateException("empty order");
        confirmed = true;
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
// === 4) Repository & Ports ===
public interface OrderRepository {
    java.util.Optional<Order> findById(java.util.UUID id);
    void save(Order order);
    boolean existsByIdempotencyKey(String key); // stored in a small ledger table
    void rememberIdempotency(String key, java.util.UUID orderId);
}

public interface PaymentGateway { // outbound port
    void authorize(java.util.UUID orderId, long amountCents, String idempotencyKey);
}

public interface DomainEventPublisher { // outbox or message bus
    void publish(Object event);
}
```

```java
// === 5) Application Service (the pattern) ===
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class OrderingApplicationService {

    private final OrderRepository orders;
    private final PaymentGateway payments;
    private final DomainEventPublisher events;

    public OrderingApplicationService(OrderRepository orders, PaymentGateway payments, DomainEventPublisher events) {
        this.orders = orders; this.payments = payments; this.events = events;
    }

    @Transactional
    public OrderSummaryDTO placeOrder(PlaceOrderCommand cmd, String callerRole) {
        // Authorization
        if (!"CUSTOMER".equals(callerRole)) {
            throw new SecurityException("forbidden");
        }

        // Idempotency (guard replays)
        if (orders.existsByIdempotencyKey(cmd.idempotencyKey())) {
            // fetch previously created order id and return its summary, or 409/200 idempotent response
            // omitted for brevity
        }

        // Orchestrate domain behavior
        Order order = Order.createNew();
        for (OrderItemRequest r : cmd.items()) {
            order.addItem(new ProductId(r.productId()), r.quantity(), new Money(r.unitPriceCents()));
        }
        order.confirm();

        // Persist aggregate atomically
        orders.save(order);
        orders.rememberIdempotency(cmd.idempotencyKey(), order.id());

        // Publish a domain event (via outbox) post-commit in real systems
        events.publish(new OrderPlacedEvent(order.id(), order.total().cents()));

        // External side-effect (often triggered by an event handler after commit)
        payments.authorize(order.id(), order.total().cents(), cmd.idempotencyKey());

        return new OrderSummaryDTO(order.id().toString(), order.total().cents(), "CONFIRMED");
    }
}

// Example domain event
record OrderPlacedEvent(java.util.UUID orderId, long totalCents) {}
```

```java
// === 6) Controller (thin adapter) ===
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/orders")
class OrderController {

    private final OrderingApplicationService app;

    OrderController(OrderingApplicationService app) { this.app = app; }

    @PostMapping
    public OrderSummaryDTO place(@RequestBody PlaceOrderCommand cmd,
                                 @RequestHeader(value = "X-Idempotency-Key") String key) {
        // adapter fills command and delegates; role would typically come from security context
        var enriched = new PlaceOrderCommand(cmd.customerId(), cmd.items(), key);
        return app.placeOrder(enriched, "CUSTOMER");
    }
}
```

**Notes**

-   The application service is **transactional**, orchestrates the **domain** and **ports**, and maintains **idempotency**.

-   Business rules (e.g., “cannot confirm empty order”) live in the **Aggregate**.

-   Payment call could be **event-driven** (recommended): publish `OrderPlacedEvent` to an outbox; a separate handler authorizes payment after commit.


---

## Known Uses

-   **E-commerce**: checkout, payment authorization, shipment booking.

-   **Banking**: money transfer command handling with outbox + events.

-   **Insurance**: policy issuance orchestration across underwriting & billing.

-   **Mobility/ride-hailing**: ride request orchestration across pricing, dispatch, notifications.


---

## Related Patterns

-   **Aggregate / Aggregate Root** – business rules & invariants.

-   **Repository** – persistence at aggregate granularity.

-   **Domain Service** – pure domain logic spanning multiple aggregates.

-   **Saga / Process Manager** – long-running, multi-step orchestration.

-   **Ports & Adapters (Hexagonal)** – isolate infrastructure.

-   **Anti-Corruption Layer** – protect the domain at external boundaries.

-   **CQRS** – split command handling (here) from queries/read models.

-   **Transactional Outbox / Event Sourcing** – reliable integration and state change capture.
