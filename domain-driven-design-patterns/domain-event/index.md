# Domain Event (Domain-Driven Design)

## Pattern Name and Classification

**Name:** Domain Event  
**Classification:** DDD tactical pattern (cross-cutting), often used with messaging/integration patterns (Outbox, Event Bus, Event Sourcing)

---

## Intent

Capture and publish something that **happened** in the domain—an immutable, meaningful fact—so other parts of the system (same bounded context or others) can react **after** the state change, without tight coupling to the initiator.

---

## Also Known As

-   Business Event

-   Domain Fact

-   Event Notification (when focused on signaling)


---

## Motivation (Forces)

-   **Explicit business language.** Domain experts talk in events (“Order placed”, “Payment captured”). Modeling these clarifies ubiquitous language.

-   **Decoupling.** Producers shouldn’t know who reacts or how.

-   **Asynchrony & scalability.** Downstream work can happen off the critical path.

-   **Auditability.** Events form an immutable trail of what happened.

-   **Consistency boundaries.** In distributed systems, side effects across contexts are eventual, not transactional.

-   **Change resilience.** New consumers can subscribe later without changing the producer.


Tensions to balance:

-   **Delivery guarantees** (at-least-once vs exactly-once)

-   **Ordering** (per aggregate vs global)

-   **Idempotency** for handlers

-   **Schema evolution** of events

-   **When to publish** (inside vs after transaction)


---

## Applicability

Use Domain Events when:

-   A state change is **significant** to the business (not mere CRUD noise).

-   Multiple independent reactions may occur (email, analytics, projections, integrations).

-   Cross-bounded-context communication is required.

-   You need an **audit** or timeline of facts.

-   You want to keep transactional work minimal and push non-critical reactions out of band.


Avoid or limit when:

-   Changes are trivial/internal and won’t be consumed.

-   Strong synchrony or immediate consistency across contexts is required.

-   The domain language does not naturally describe “things that happened.”


---

## Structure

-   **Domain Event (immutable):** A value object with a clear name in past tense, timestamp, aggregate identity, minimal business data, and a version.

-   **Event Publisher (inside the same transaction):** Collects events raised by aggregates and persists them (often via an Outbox) or enqueues them for dispatch after commit.

-   **Event Bus / Dispatcher:** Delivers events to handlers (in-process or via messaging).

-   **Event Handler / Subscriber:** Reacts to events (side effects, projections, integration calls).

-   **Outbox (optional but common):** Durable persistence of events atomically with state changes, later relayed to external brokers.


---

## Participants

-   **Aggregate / Entity:** Detects domain occurrence and raises the corresponding event.

-   **Domain Event:** The fact payload.

-   **Event Publisher / Collector:** Stores events during the transaction (often on a ThreadLocal or Unit of Work) and publishes after commit.

-   **Event Bus:** Abstraction over synchronous callbacks or async brokers (e.g., SQS/Kafka/RabbitMQ).

-   **Handlers:** Stateless components that process events; must be idempotent.

-   **Outbox Relay (optional):** Background process to push events from DB to broker.


---

## Collaboration

1.  Application service invokes aggregate method.

2.  Aggregate changes state and **records** a Domain Event.

3.  The transaction commits both the new state and (optionally) the event to an outbox.

4.  After commit, the event is **published** to the bus.

5.  Handlers subscribe and **react** (update read models, send emails, call external systems).

6.  Handlers use **idempotency** keys and retries to handle at-least-once delivery.


---

## Consequences

**Benefits**

-   Decoupled, extensible reactions

-   Clear audit trail and domain language alignment

-   Enables CQRS/read models and integrations

-   Helps performance by moving work off the critical path


**Liabilities**

-   Extra plumbing (publisher, bus, handler lifecycle)

-   Eventual consistency and coordination complexity

-   Delivery, ordering, and dedup concerns

-   Versioning and schema evolution overhead

-   Risk of over-eventing (noise)


---

## Implementation

**Key guidelines**

-   **Name events in past tense** and keep them **immutable**.

-   Include **eventId**, **occurredAt**, **aggregateId**, **version**, and **a minimal, stable payload** (avoid leaking internal state).

-   Publish **after successful commit**; use a **Transactional Outbox** to avoid dual-write issues.

-   Handlers must be **idempotent** and **retry-safe**.

-   Manage **ordering** per aggregate where needed (sequence, partitioning key).

-   Use **schema versioning** (eventType + version) and contract tests.

-   Log/trace with **correlation ids** for observability.

-   Distinguish **domain events** (business facts) from **integration events** (externalized, compatible across contexts). Sometimes they’re separate types.


**Delivery patterns**

-   **In-process sync** (simple, same JVM) – good inside a monolith.

-   **Async broker** (Kafka/SQS/RabbitMQ) – good for scale and cross-service.

-   **Outbox + Relay** – to guarantee publish after commit.


---

## Sample Code (Java, plain + Spring-friendly style)

```java
// Domain Event base type
public interface DomainEvent {
    String eventId();          // UUID
    String aggregateId();      // e.g., orderId
    String eventType();        // e.g., "order.placed"
    int version();             // schema version
    java.time.Instant occurredAt();
}

// A concrete domain event
public final class OrderPlaced implements DomainEvent {
    private final String eventId;
    private final String orderId;
    private final java.time.Instant occurredAt;
    private final int version = 1;

    // minimal, stable payload
    private final String customerId;
    private final java.math.BigDecimal totalAmount;
    private final String currency;

    public OrderPlaced(String orderId, String customerId,
                       java.math.BigDecimal totalAmount, String currency) {
        this.eventId = java.util.UUID.randomUUID().toString();
        this.orderId = orderId;
        this.customerId = customerId;
        this.totalAmount = totalAmount;
        this.currency = currency;
        this.occurredAt = java.time.Instant.now();
    }

    @Override public String eventId() { return eventId; }
    @Override public String aggregateId() { return orderId; }
    @Override public String eventType() { return "order.placed"; }
    @Override public int version() { return version; }
    @Override public java.time.Instant occurredAt() { return occurredAt; }

    public String orderId() { return orderId; }
    public String customerId() { return customerId; }
    public java.math.BigDecimal totalAmount() { return totalAmount; }
    public String currency() { return currency; }
}

// Aggregate root capturing events
public class Order {
    private final String id;
    private String customerId;
    private java.util.List<OrderLine> lines = new java.util.ArrayList<>();
    private final java.util.List<DomainEvent> pendingEvents = new java.util.ArrayList<>();
    private boolean placed;

    public Order(String id, String customerId) {
        this.id = id;
        this.customerId = customerId;
    }

    public void addLine(String sku, int qty, java.math.BigDecimal price) {
        if (placed) throw new IllegalStateException("order already placed");
        lines.add(new OrderLine(sku, qty, price));
    }

    public void place(java.util.function.Supplier<String> currencySupplier) {
        if (placed) throw new IllegalStateException("already placed");
        if (lines.isEmpty()) throw new IllegalStateException("empty order");
        this.placed = true;
        var total = lines.stream()
            .map(l -> l.price.multiply(java.math.BigDecimal.valueOf(l.qty)))
            .reduce(java.math.BigDecimal.ZERO, java.math.BigDecimal::add);
        var evt = new OrderPlaced(id, customerId, total, currencySupplier.get());
        pendingEvents.add(evt);
    }

    public java.util.List<DomainEvent> pullEvents() {
        var copy = java.util.List.copyOf(pendingEvents);
        pendingEvents.clear();
        return copy;
    }

    public String id() { return id; }

    private static final class OrderLine {
        final String sku; final int qty; final java.math.BigDecimal price;
        OrderLine(String sku, int qty, java.math.BigDecimal price) {
            this.sku = sku; this.qty = qty; this.price = price;
        }
    }
}

// EventBus abstraction
public interface EventBus {
    void publish(java.util.Collection<? extends DomainEvent> events);
    void subscribe(String eventType, EventHandler handler);
}

@FunctionalInterface
public interface EventHandler {
    void handle(DomainEvent event) throws Exception; // handlers must be idempotent
}

// Simple in-memory synchronous bus (for monoliths/tests)
public class InMemoryEventBus implements EventBus {
    private final java.util.Map<String, java.util.List<EventHandler>> subscribers = new java.util.HashMap<>();

    @Override
    public void publish(java.util.Collection<? extends DomainEvent> events) {
        for (var e : events) {
            var handlers = subscribers.getOrDefault(e.eventType(), java.util.List.of());
            for (var h : handlers) {
                try { h.handle(e); } catch (Exception ex) {
                    // choose: retry, log, or escalate; here we just log
                    System.err.println("Handler error for " + e.eventType() + ": " + ex.getMessage());
                }
            }
        }
    }

    @Override
    public void subscribe(String eventType, EventHandler handler) {
        subscribers.computeIfAbsent(eventType, k -> new java.util.ArrayList<>()).add(handler);
    }
}

// Outbox entity (JPA-friendly shape) to avoid dual writes
// (Schema and mapping elided for brevity; serialize event as JSON)
public class OutboxMessage {
    public String id;               // UUID
    public String aggregateId;
    public String type;             // eventType
    public int version;
    public java.time.Instant occurredAt;
    public String payload;          // JSON
    public java.time.Instant nextAttemptAt;
    public int attempts;
}

// Application service: commit state + outbox inside one transaction
public class PlaceOrderService {
    private final OrderRepository orders;
    private final OutboxRepository outbox;
    private final EventSerializer serializer;
    private final EventBus bus; // for in-process publish after commit (optional)

    public PlaceOrderService(OrderRepository orders, OutboxRepository outbox,
                             EventSerializer serializer, EventBus bus) {
        this.orders = orders; this.outbox = outbox; this.serializer = serializer; this.bus = bus;
    }

    // Pseudocode; annotate @Transactional if using Spring
    public void place(String orderId, String customerId) {
        Order order = new Order(orderId, customerId);
        // ... add lines ...
        order.place(() -> "EUR");

        // persist aggregate + outbox atomically
        orders.save(order);
        for (var e : order.pullEvents()) {
            outbox.save(toOutbox(e));  // single DB transaction with order state
        }
        // After commit hook (framework-dependent):
        // 1) either publish synchronously to an in-memory bus for local handlers
        // 2) or rely on an Outbox Relay to push to a broker asynchronously
        // bus.publish(events);
    }

    private OutboxMessage toOutbox(DomainEvent e) {
        var msg = new OutboxMessage();
        msg.id = e.eventId();
        msg.aggregateId = e.aggregateId();
        msg.type = e.eventType();
        msg.version = e.version();
        msg.occurredAt = e.occurredAt();
        msg.payload = serializer.toJson(e);
        msg.nextAttemptAt = java.time.Instant.now();
        msg.attempts = 0;
        return msg;
    }
}

// Example handler (idempotent)
public class SendOrderConfirmationHandler implements EventHandler {

    private final EmailGateway email;
    private final ProcessedEventStore processed; // for idempotency

    public SendOrderConfirmationHandler(EmailGateway email, ProcessedEventStore processed) {
        this.email = email; this.processed = processed;
    }

    @Override
    public void handle(DomainEvent event) {
        if (!"order.placed".equals(event.eventType())) return;
        if (processed.alreadyProcessed(event.eventId())) return;

        var op = (OrderPlaced) event;
        email.sendOrderConfirmation(op.customerId(), op.orderId(), op.totalAmount(), op.currency());
        processed.markProcessed(event.eventId());
    }
}
```

**Notes for Spring users**

-   Use `@DomainEvents`/`AbstractAggregateRoot` (Spring Data) for simple in-process publication.

-   For robust distribution, favor **Outbox + Relay** (e.g., a scheduled component that reads unsent outbox rows and publishes to Kafka/SQS), then delete/mark sent.

-   Wrap handler side effects in retries; use a **dedup table** keyed by `eventId`.


---

## Known Uses

-   E-commerce (“OrderPlaced”, “PaymentCaptured”, “ShipmentDispatched”)

-   Finance (“TransferSettled”, “LimitExceeded”)

-   SaaS analytics/auditing (“UserSignedUp”, “FeatureToggled”)

-   Any CQRS-style read model updates and cross-service integrations


---

## Related Patterns

-   **Transactional Outbox:** Ensures events are published after commit without dual writes.

-   **Event Bus / Messaging:** Infrastructure for delivery.

-   **Event Sourcing:** Persists events as the source of truth (a different storage strategy; domain events are compatible but not identical).

-   **CQRS:** Handlers often project domain events into read models.

-   **Saga / Process Manager:** Coordinates long-running workflows using events.

-   **Pub/Sub:** Generic communication style underlying distribution of events.

-   **Idempotent Receiver:** Handler design to tolerate duplicates.


---
