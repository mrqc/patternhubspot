# Event Sourcing (Domain-Driven Design)

## Pattern Name and Classification

**Name:** Event Sourcing  
**Classification:** DDD architectural/tactical pattern (persistence strategy; often paired with CQRS)

---

## Intent

Persist the **sequence of domain events** that changed an aggregate’s state rather than persisting only the current state. Rebuild (“rehydrate”) the aggregate by replaying its events; derive current state and read models from this immutable history.

---

## Also Known As

-   Event Store / Event-Sourced Aggregates

-   Source of Truth as Events


---

## Motivation (Forces)

-   **Auditability & Traceability:** Business cares about *what* happened and *why*, not only the latest snapshot.

-   **Temporal Queries:** “What was the balance on 2025-09-01?” becomes natural by replaying up to a time/sequence.

-   **Decoupled Projections:** Build many read models from the same event stream, each optimized for a use case.

-   **Integration:** Publishing events is inherent; they can drive workflows and external systems.


Trade-offs and tensions:

-   **Complexity:** Event stores, upcasters, projections, replay, and versioning add moving parts.

-   **Schema Evolution:** Event definitions change over time; migrations or upcasters are needed.

-   **Queries:** Rich queries require projections; there is no one “current-state” table to join.

-   **Consistency:** Projections are eventually consistent; consumers must tolerate lag.

-   **Concurrency:** Append must be guarded (optimistic concurrency via expected version).


---

## Applicability

Use Event Sourcing when:

-   The domain is **highly collaborative**, requires **audit trails**, or **temporal reasoning**.

-   You need **multiple read models** (analytics, search, dashboards) updated by events.

-   Invariants are naturally expressed as **event-driven state transitions**.

-   You plan to support **time travel**, **rebuilds**, or **retroactive fixes** via compensating events.


Avoid or limit when:

-   The domain is CRUD-heavy with minimal behavioral complexity and no audit demands.

-   Your team cannot invest in **operational maturity** (projections, upcasting, tooling).

-   Compliance forbids storing historical personal data (unless events are carefully minimized/pseudonymized).


---

## Structure

-   **Aggregate (Event-Sourced):** Applies commands by validating invariants and **emitting new events** (not mutating state directly). State is updated by **applying** those events.

-   **Domain Events:** Immutable, versioned, past-tense facts belonging to a single aggregate stream.

-   **Event Store:** Append-only storage of ordered events per aggregate stream; supports **append with expectedVersion** and **read by stream range**.

-   **Snapshot (optional):** Periodic materialization of aggregate state to reduce replay cost.

-   **Projections/Read Models:** Consumers that build query-optimized views by subscribing to events.

-   **Event Bus/Outbox (optional):** Relays committed events to subscribers or external brokers.

-   **Upcaster/Transformer (optional):** Upgrades old event schemas during load.


---

## Participants

-   **Command Handler / Application Service:** Loads aggregate, sends command, persists resulting events.

-   **Aggregate:** Validates command; **produces events** if allowed; **applies** events to mutate internal state.

-   **Event Store:** Durably appends and streams events.

-   **Snapshot Store (optional):** Saves/loads snapshots with last sequence.

-   **Projectors / Subscribers:** Build read models and integrations from committed events.

-   **Upcasters:** Handle event version changes.


---

## Collaboration

1.  **Load:** Repository fetches snapshot (if any) and subsequent events; replays to reconstruct aggregate.

2.  **Handle Command:** Aggregate validates invariants and emits **uncommitted events**.

3.  **Persist:** Repository appends events to the stream using **expectedVersion** for optimistic concurrency; optionally stores a new snapshot.

4.  **Publish:** After commit, events are published to projectors/integrations.

5.  **Project:** Read models update asynchronously; queries hit projections.


---

## Consequences

**Benefits**

-   Perfect **audit log**; easy debugging and compliance.

-   **Temporal features** (time travel, retroactive projections).

-   **Evolvable read models**; add new projections without changing writers.

-   Natural integration via **event propagation**.


**Liabilities**

-   Higher **operational complexity** (store, projections, replays).

-   **Event design discipline** and **schema evolution** required.

-   **Eventual consistency** between writes and queries.

-   **Data growth** and storage management (compaction, archiving).

-   Hard deletes/PII removal require **careful event design** (tokens, encryption, separate stores).


---

## Implementation

**Design guidelines**

-   Events are **immutable**, **past tense**, **minimal**, and **self-describing** (`type`, `version`, `occurredAt`, `aggregateId`, `sequence`).

-   Aggregate **only** changes state by applying events (same methods used for replay and for new events).

-   Use **optimistic concurrency**: append with `expectedVersion = lastKnownSequence`.

-   Introduce **snapshots** by size/frequency thresholds; snapshot includes last sequence.

-   Keep **event payloads stable**; introduce new versions rather than mutating old events. Use **upcasters**.

-   Build **idempotent projectors** keyed by `(streamId, sequence)`; track projection positions.

-   Separation of **Domain Events** (internal facts) and **Integration Events** (external contracts) can help compatibility.

-   Consider **Outbox** if your event store and message broker are different systems.


**Event evolution**

-   Version in the event header; upcast old payloads on read.

-   Avoid removing fields; add optional ones with defaults.


**PII/Compliance**

-   Prefer referencing PII via resolvable keys; or encrypt sensitive fields with a key you can rotate/destroy.


---

## Sample Code (Java, minimal but production-shaped)

```java
// ---------- Event Infrastructure ----------

public interface DomainEvent {
    String type();                // e.g., "order.placed"
    int version();                // schema version
    String aggregateId();         // stream id
    long sequence();              // per-stream, strictly increasing
    java.time.Instant occurredAt();
}

public record EventEnvelope(
        String aggregateId,
        long sequence,
        String type,
        int version,
        java.time.Instant occurredAt,
        String payloadJson // serialized specific event
) {}

public interface EventStore {
    // Append must be atomic; expectedVersion = last known sequence (or 0 if none).
    void append(String aggregateId, long expectedVersion, java.util.List<EventEnvelope> newEvents);

    // Read from (inclusive) to end
    java.util.List<EventEnvelope> readStream(String aggregateId, long fromSequenceInclusive);

    // Global subscription (optional)
    java.util.stream.Stream<EventEnvelope> readAllFrom(long globalPosition);
}

public interface SnapshotStore<S> {
    java.util.Optional<Snapshot<S>> load(String aggregateId);
    void save(Snapshot<S> snapshot);
}
public record Snapshot<S>(String aggregateId, long lastSequence, S state) {}
```

```java
// ---------- Domain: Order Aggregate (Event-Sourced) ----------

// Concrete events (payloads). Keep them small and stable.
public record OrderPlaced(String orderId, String customerId, java.math.BigDecimal amount, String currency) {}
public record OrderCancelled(String orderId, String reason) {}
public record OrderPaid(String orderId, String paymentId) {}

// Aggregate state reconstructed from events
public final class Order {
    private final String id;
    private boolean placed;
    private boolean cancelled;
    private boolean paid;
    private String customerId;
    private java.math.BigDecimal amount;
    private String currency;

    // Uncommitted events created by commands
    private final java.util.List<Object> pending = new java.util.ArrayList<>();
    private long version; // last applied sequence

    private Order(String id) { this.id = id; }

    public static Order createEmpty(String id) { return new Order(id); }

    public long version() { return version; }
    public String id() { return id; }
    public java.util.List<Object> pullPendingEvents() {
        var copy = java.util.List.copyOf(pending);
        pending.clear();
        return copy;
    }

    // ---------- Commands ----------
    public void place(String customerId, java.math.BigDecimal amount, String currency) {
        if (placed) throw new IllegalStateException("already placed");
        if (amount == null || amount.signum() <= 0) throw new IllegalArgumentException("amount > 0");
        applyNew(new OrderPlaced(id, customerId, amount, currency));
    }

    public void cancel(String reason) {
        if (!placed) throw new IllegalStateException("not placed");
        if (paid) throw new IllegalStateException("already paid");
        if (cancelled) return; // idempotent
        applyNew(new OrderCancelled(id, reason == null ? "unspecified" : reason));
    }

    public void markPaid(String paymentId) {
        if (!placed) throw new IllegalStateException("not placed");
        if (cancelled) throw new IllegalStateException("cancelled");
        if (paid) return; // idempotent
        applyNew(new OrderPaid(id, paymentId));
    }

    // ---------- Event application ----------
    public void apply(Object evt) {
        if (evt instanceof OrderPlaced e) {
            this.placed = true;
            this.customerId = e.customerId();
            this.amount = e.amount();
            this.currency = e.currency();
        } else if (evt instanceof OrderCancelled e) {
            this.cancelled = true;
        } else if (evt instanceof OrderPaid e) {
            this.paid = true;
        } else {
            throw new IllegalArgumentException("Unknown event " + evt.getClass());
        }
    }

    private void applyNew(Object evt) {
        apply(evt);
        pending.add(evt);
    }

    // Used during replay to bump version (sequence) without creating pending events
    public void markReplayedUpTo(long sequence) { this.version = sequence; }
}
```

```java
// ---------- Repository: load (replay) & save (append) ----------

public interface EventSerializer {
    String typeOf(Object event);       // e.g., "order.placed"
    int versionOf(Object event);       // e.g., 1
    String toJson(Object event);
    Object fromJson(String type, int version, String json); // supports upcasting
}

public final class EventSourcedOrderRepository {
    private final EventStore store;
    private final SnapshotStore<Order> snapshots;
    private final EventSerializer serde;
    private final java.time.Clock clock;

    public EventSourcedOrderRepository(EventStore store,
                                       SnapshotStore<Order> snapshots,
                                       EventSerializer serde,
                                       java.time.Clock clock) {
        this.store = store; this.snapshots = snapshots; this.serde = serde; this.clock = clock;
    }

    public Order load(String orderId) {
        long from = 1;
        Order agg = Order.createEmpty(orderId);

        var snap = snapshots.load(orderId);
        if (snap.isPresent()) {
            agg = snap.get().state();
            from = snap.get().lastSequence() + 1;
            agg.markReplayedUpTo(snap.get().lastSequence());
        }

        var events = store.readStream(orderId, from);
        for (var env : events) {
            var evt = serde.fromJson(env.type(), env.version(), env.payloadJson());
            agg.apply(evt);
            agg.markReplayedUpTo(env.sequence());
        }
        return agg;
    }

    public void save(Order agg) {
        var toAppend = new java.util.ArrayList<EventEnvelope>();
        long seq = agg.version();

        for (var evt : agg.pullPendingEvents()) {
            seq += 1;
            var type = serde.typeOf(evt);
            var ver  = serde.versionOf(evt);
            var env = new EventEnvelope(
                    agg.id(),
                    seq,
                    type,
                    ver,
                    java.time.Instant.now(clock),
                    serde.toJson(evt)
            );
            toAppend.add(env);
        }
        if (!toAppend.isEmpty()) {
            store.append(agg.id(), /* expectedVersion */ agg.version(), toAppend);
            // optional snapshotting policy
            if (seq % 100 == 0) {
                snapshots.save(new Snapshot<>(agg.id(), seq, agg));
            }
        }
    }
}
```

```java
// ---------- Application Service (Command Handler) ----------

public final class OrderApplicationService {
    private final EventSourcedOrderRepository orders;

    public OrderApplicationService(EventSourcedOrderRepository orders) { this.orders = orders; }

    // @Transactional boundary if EventStore is transactional
    public void placeOrder(String orderId, String customerId, java.math.BigDecimal amount, String currency) {
        var order = orders.load(orderId);
        order.place(customerId, amount, currency);
        orders.save(order);
    }

    public void cancelOrder(String orderId, String reason) {
        var order = orders.load(orderId);
        order.cancel(reason);
        orders.save(order);
    }

    public void markOrderPaid(String orderId, String paymentId) {
        var order = orders.load(orderId);
        order.markPaid(paymentId);
        orders.save(order);
    }
}
```

```java
// ---------- Projection (Read Model) Example ----------

public interface OrdersProjection {
    // persist denormalized state; ensure idempotency by tracking (aggregateId, sequence)
    void apply(EventEnvelope e);
}

public final class OrdersListProjector implements OrdersProjection {
    private final EventSerializer serde;
    private final ProcessedPositions positionStore; // remembers last applied (stream, sequence)

    public OrdersListProjector(EventSerializer serde, ProcessedPositions positionStore) {
        this.serde = serde; this.positionStore = positionStore;
    }

    @Override
    public void apply(EventEnvelope e) {
        if (positionStore.alreadyApplied(e.aggregateId(), e.sequence())) return; // idempotent

        var evt = serde.fromJson(e.type(), e.version(), e.payloadJson());
        // update a read model table: orders(order_id, status, amount, currency, updated_at)
        // (left as an exercise; use your DAO)
        positionStore.markApplied(e.aggregateId(), e.sequence());
    }
}

public interface ProcessedPositions {
    boolean alreadyApplied(String streamId, long seq);
    void markApplied(String streamId, long seq);
}
```

**Notes**

-   **Optimistic concurrency:** `append(expectedVersion)` fails if another writer appended first; caller retries after reloading.

-   **Idempotency:** Projections track `(streamId, sequence)` to avoid double-apply.

-   **Upcasting:** `EventSerializer.fromJson` can transform old → new versions on load.

-   **Snapshots:** Use carefully; they are an optimization, not a source of truth.


---

## Known Uses

-   **Banking/Ledgers:** balances derived from transactions (events).

-   **E-commerce Orders & Fulfillment:** full lifecycle auditing, SLA analytics.

-   **IoT/Telemetry:** device state reconstructed from signals.

-   **Logistics:** shipments, location updates, exception handling.

-   **Gaming:** player inventory/progress timelines.

-   **Compliance-sensitive domains:** where immutable audit trails are mandatory.


---

## Related Patterns

-   **CQRS:** Naturally complements event sourcing; commands write events, read side projects them.

-   **Domain Event:** The event messages produced by aggregates; Event Sourcing *stores* them as truth.

-   **Transactional Outbox:** For publishing committed events to brokers reliably when store ≠ broker.

-   **Saga / Process Manager:** Orchestrates long-running workflows with events.

-   **Snapshot:** Optimization to reduce replay time.

-   **Idempotent Receiver / At-Least-Once Delivery:** Essential on projection side.

-   **Event Upcasting / Schema Versioning:** Evolves event definitions safely.
