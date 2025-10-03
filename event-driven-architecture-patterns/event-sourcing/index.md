# Event Sourcing — Event-Driven Architecture Pattern

## Pattern Name and Classification

**Name:** Event Sourcing  
**Classification:** Event-Driven Architecture (EDA) / State Management & Persistence / Domain-Driven Design (DDD) tactical pattern

## Intent

Persist the **sequence of domain events** that change an aggregate’s state rather than persisting only the current state. Reconstitute the current state by **replaying** those events (optionally from a snapshot), enabling perfect auditability, temporal queries, and deterministic rebuilds.

## Also Known As

-   Event Log as Source of Truth
    
-   Append-Only Domain Log
    
-   Evented Persistence
    

## Motivation (Forces)

-   **Audit & traceability:** Regulations, forensics, and debugging need “how we got here,” not just “what it is now.”
    
-   **Temporal queries:** “As-of” views, simulations, and time-travel analytics.
    
-   **Decoupling write/read:** Events are a natural interface for CQRS projections and integrations.
    
-   **Model purity:** Aggregates enforce invariants; events capture meaningful domain changes.
    
-   **Evolution:** New read models can be generated from history without touching producers.
    

**Tensions**

-   **Complexity:** More moving parts (event store, snapshots, upcasters, projections).
    
-   **Performance:** Rebuild latency without snapshots or long-lived aggregates.
    
-   **Schema evolution:** Historical events must remain interpretable.
    
-   **Idempotency & ordering:** Consumers must handle at-least-once delivery and strict per-aggregate order.
    

## Applicability

Use Event Sourcing when:

-   Your domain has rich, auditable business behavior with evolving read models.
    
-   You need reliable **integration** via events and **temporal** insights.
    
-   Concurrency conflicts must be explicit (optimistic locking via versions).
    

Be cautious when:

-   State is simple CRUD with no need for audit/time-travel.
    
-   Side effects aren’t idempotent and can’t be guarded.
    
-   Long-lived aggregates could accumulate millions of events without snapshotting/compaction.
    

## Structure

-   **Aggregate (DDD):** Contains behavior; applies events to mutate internal state.
    
-   **Domain Events:** Immutable facts with type, aggregateId, sequence/version, timestamp, payload.
    
-   **Event Store:** Append-only, ordered per aggregate; supports optimistic concurrency and streams.
    
-   **Snapshot Store (optional):** Periodically stores materialized state + last version for fast loads.
    
-   **Upcasters:** Transform old event versions on read.
    
-   **Projections/Read Models:** Derived stores updated by subscribing to event streams.
    
-   **Replay/Repair Tools:** Rebuild read models; fix-forward after projector bugs.
    

*Textual diagram*

```css
[Command] -> [Aggregate] --emits--> [Events] --append--> [Event Store]
                                   \--(optional)--> [Snapshot Store]
[Query]   <- [Projections] <--subscribe/replay-- [Event Store]
```

## Participants

-   **Command Handler / Application Service** — validates intent, loads aggregate, invokes behavior.
    
-   **Aggregate Root** — holds invariants; emits events; applies them to state.
    
-   **Event Store** — durable, ordered, per-aggregate streams; concurrency checks.
    
-   **Snapshot Manager** — create/load snapshots.
    
-   **Upcaster** — schema evolution for historic events.
    
-   **Projector / Subscriber** — builds read models and external integrations.
    

## Collaboration

1.  A command targets an aggregate (by id).
    
2.  Repository loads the aggregate: fetch snapshot (if any) → fetch subsequent events → apply in order.
    
3.  Aggregate executes behavior; on success it **emits new events** (uncommitted).
    
4.  Repository appends events with expected version; failures surface as concurrency exceptions.
    
5.  Projectors consume the appended events to update read models.
    
6.  Snapshots are periodically written to reduce future load latency.
    

## Consequences

**Benefits**

-   Full audit trail & temporal analytics.
    
-   Natural integration via events; supports CQRS cleanly.
    
-   Deterministic rebuilds, what-if simulations, backfills.
    
-   Clear aggregate boundaries and invariants.
    

**Liabilities**

-   Higher operational & conceptual complexity.
    
-   Requires robust schema evolution (upcasters).
    
-   Eventual consistency for read models.
    
-   Storage growth (mitigated by snapshots/compaction/archival).
    

## Implementation

**Key practices**

-   **Per-aggregate ordering:** Events carry a monotonically increasing **version** (or sequence).
    
-   **Optimistic concurrency:** Append with expected version; detect conflicting writes.
    
-   **Idempotency:** Replay-safe apply methods; consumers dedupe by `(aggregateId, version)` or event id.
    
-   **Schema evolution:** Version events; maintain upcasters.
    
-   **Snapshots:** Time- or count-based snapshot policies; store `(aggregateState, version)`.
    
-   **Testing:** Given-When-Then on aggregates (events-in → command → events-out).
    

**Typical storage choices**

-   Purpose-built event stores (EventStoreDB, Axon Server)
    
-   Relational (append-only table per stream or partitioned by aggregateId)
    
-   Kafka/Pulsar for distribution + a DB for per-aggregate transactional append
    

---

## Sample Code (Java, dependency-light, compile-ready sketch)

The example shows:

-   A `BankAccount` aggregate (open, deposit, withdraw with invariant).
    
-   An in-memory **event store** with optimistic concurrency.
    
-   **Repository** with snapshotting (every N events).
    
-   **Upcaster** stub for schema evolution.
    
-   A **projector** building a read model.
    

```java
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

// ==== Event infrastructure ====

interface DomainEvent {
    String aggregateId();
    int version(); // 1..n per aggregate stream
    String type();
    Instant timestamp();
}

abstract class BaseEvent implements DomainEvent {
    private final String aggregateId;
    private final int version;
    private final Instant ts = Instant.now();
    protected BaseEvent(String aggregateId, int version) {
        this.aggregateId = aggregateId; this.version = version;
    }
    public String aggregateId() { return aggregateId; }
    public int version() { return version; }
    public Instant timestamp() { return ts; }
}

final class AccountOpened extends BaseEvent {
    final String owner;
    final String currency;
    AccountOpened(String id, int v, String owner, String currency) { super(id, v); this.owner = owner; this.currency = currency; }
    public String type() { return "AccountOpened"; }
}
final class MoneyDeposited extends BaseEvent {
    final long amountMinor; // e.g., cents
    MoneyDeposited(String id, int v, long amountMinor) { super(id, v); this.amountMinor = amountMinor; }
    public String type() { return "MoneyDeposited"; }
}
final class MoneyWithdrawn extends BaseEvent {
    final long amountMinor;
    MoneyWithdrawn(String id, int v, long amountMinor) { super(id, v); this.amountMinor = amountMinor; }
    public String type() { return "MoneyWithdrawn"; }
}

// ==== Upcaster (schema evolution hook) ====
interface Upcaster {
    DomainEvent upcast(DomainEvent e); // no-op here; evolve payloads/types as schemas change
}
final class NoopUpcaster implements Upcaster {
    public DomainEvent upcast(DomainEvent e) { return e; }
}

// ==== Event Store with optimistic concurrency ====
interface EventStore {
    List<DomainEvent> loadStream(String aggregateId, int fromVersionExclusive);
    void appendToStream(String aggregateId, int expectedVersion, List<DomainEvent> newEvents);
}

final class InMemoryEventStore implements EventStore {
    private final Map<String, List<DomainEvent>> streams = new ConcurrentHashMap<>();
    private final Upcaster upcaster;
    InMemoryEventStore(Upcaster upcaster) { this.upcaster = upcaster; }

    public List<DomainEvent> loadStream(String aggregateId, int fromVersionExclusive) {
        List<DomainEvent> list = streams.getOrDefault(aggregateId, List.of());
        List<DomainEvent> out = new ArrayList<>();
        for (DomainEvent e : list) {
            if (e.version() > fromVersionExclusive) out.add(upcaster.upcast(e));
        }
        return out;
    }

    public synchronized void appendToStream(String aggregateId, int expectedVersion, List<DomainEvent> newEvents) {
        List<DomainEvent> list = new ArrayList<>(streams.getOrDefault(aggregateId, new ArrayList<>()));
        int actualVersion = list.isEmpty() ? 0 : list.get(list.size() - 1).version();
        if (actualVersion != expectedVersion) {
            throw new ConcurrentModificationException("Expected v" + expectedVersion + " but was v" + actualVersion);
        }
        list.addAll(newEvents);
        streams.put(aggregateId, List.copyOf(list));
    }
}

// ==== Snapshotting (optional) ====
final class Snapshot<T> {
    final String aggregateId;
    final int version;
    final T state;
    Snapshot(String id, int version, T state) { this.aggregateId = id; this.version = version; this.state = state; }
}

interface SnapshotStore<T> {
    Snapshot<T> load(String aggregateId);
    void save(Snapshot<T> snapshot);
}

final class InMemorySnapshotStore<T> implements SnapshotStore<T> {
    private final Map<String, Snapshot<T>> map = new ConcurrentHashMap<>();
    public Snapshot<T> load(String id) { return map.get(id); }
    public void save(Snapshot<T> s) { map.put(s.aggregateId, s); }
}

// ==== Aggregate Root ====

final class BankAccount {
    // state
    private String id;
    private String owner;
    private String currency;
    private long balanceMinor = 0;
    private int version = 0;
    private boolean opened = false;

    // emitted (uncommitted) events
    private final List<DomainEvent> changes = new ArrayList<>();

    private BankAccount() { }

    public static BankAccount open(String id, String owner, String currency) {
        BankAccount a = new BankAccount();
        a.applyChange(new AccountOpened(id, 1, owner, currency));
        return a;
    }

    public void deposit(long amountMinor) {
        requireOpened();
        if (amountMinor <= 0) throw new IllegalArgumentException("amount must be > 0");
        applyChange(new MoneyDeposited(id, version + 1, amountMinor));
    }

    public void withdraw(long amountMinor) {
        requireOpened();
        if (amountMinor <= 0) throw new IllegalArgumentException("amount must be > 0");
        if (balanceMinor - amountMinor < 0) throw new IllegalStateException("insufficient funds");
        applyChange(new MoneyWithdrawn(id, version + 1, amountMinor));
    }

    private void requireOpened() { if (!opened) throw new IllegalStateException("account not opened"); }

    // Apply & mutate state deterministically
    private void apply(DomainEvent e) {
        if (e instanceof AccountOpened ev) {
            this.id = ev.aggregateId();
            this.owner = ev.owner;
            this.currency = ev.currency;
            this.balanceMinor = 0;
            this.opened = true;
            this.version = ev.version();
        } else if (e instanceof MoneyDeposited ev) {
            this.balanceMinor += ev.amountMinor;
            this.version = ev.version();
        } else if (e instanceof MoneyWithdrawn ev) {
            this.balanceMinor -= ev.amountMinor;
            this.version = ev.version();
        } else {
            throw new IllegalArgumentException("Unknown event " + e.type());
        }
    }

    private void applyChange(DomainEvent e) {
        apply(e);
        changes.add(e);
    }

    public void loadFromHistory(Iterable<DomainEvent> history) {
        for (DomainEvent e : history) apply(e); // no recording
        changes.clear();
    }

    public List<DomainEvent> getUncommittedChanges() { return List.copyOf(changes); }
    public void markCommitted() { changes.clear(); }

    // getters for snapshot/state
    public String id() { return id; }
    public int version() { return version; }
    public long balanceMinor() { return balanceMinor; }
    public String currency() { return currency; }
    public String owner() { return owner; }
}

// ==== Repository with snapshotting ====

final class BankAccountRepository {
    private final EventStore store;
    private final SnapshotStore<BankAccountMemento> snapshots;
    private final int snapshotEvery;

    BankAccountRepository(EventStore store, SnapshotStore<BankAccountMemento> snapshots, int snapshotEvery) {
        this.store = store; this.snapshots = snapshots; this.snapshotEvery = snapshotEvery;
    }

    public BankAccount load(String id) {
        BankAccount agg = new BankAccount();
        int fromVersion = 0;

        Snapshot<BankAccountMemento> s = snapshots.load(id);
        if (s != null) {
            agg = s.state.restore();
            fromVersion = s.version;
        }
        List<DomainEvent> events = store.loadStream(id, fromVersion);
        agg.loadFromHistory(events);
        return agg;
    }

    public void save(BankAccount agg) {
        List<DomainEvent> changes = agg.getUncommittedChanges();
        if (changes.isEmpty()) return;

        int expectedVersion = agg.version() - changes.size();
        store.appendToStream(agg.id(), expectedVersion, changes);
        agg.markCommitted();

        // snapshot policy
        if (agg.version() % snapshotEvery == 0) {
            snapshots.save(new Snapshot<>(agg.id(), agg.version(), BankAccountMemento.from(agg)));
        }
    }
}

// Snapshot memento (immutable)
final class BankAccountMemento {
    final String id; final String owner; final String currency; final long balanceMinor; final int version; final boolean opened;
    private BankAccountMemento(String id, String owner, String currency, long balanceMinor, int version, boolean opened) {
        this.id = id; this.owner = owner; this.currency = currency; this.balanceMinor = balanceMinor; this.version = version; this.opened = opened;
    }
    static BankAccountMemento from(BankAccount a) {
        return new BankAccountMemento(a.id(), a.owner(), a.currency(), a.balanceMinor(), a.version(), true);
    }
    BankAccount restore() {
        BankAccount a = new BankAccount();
        // rebuild via synthetic events for simplicity
        a.loadFromHistory(List.of(new AccountOpened(id, 1, owner, currency)));
        if (balanceMinor > 0) a.loadFromHistory(List.of(new MoneyDeposited(id, version, balanceMinor))); // rough; real systems snapshot exact state
        return a; // for demo only; production snapshots should set fields directly
    }
}

// ==== Projection example (read model) ====

final class BalanceProjection {
    private final Map<String, Long> balances = new ConcurrentHashMap<>();
    public void handle(DomainEvent e) {
        if (e instanceof AccountOpened ao) {
            balances.put(ao.aggregateId(), 0L);
        } else if (e instanceof MoneyDeposited md) {
            balances.compute(md.aggregateId(), (k, v) -> (v == null ? 0L : v) + md.amountMinor);
        } else if (e instanceof MoneyWithdrawn mw) {
            balances.compute(mw.aggregateId(), (k, v) -> (v == null ? 0L : v) - mw.amountMinor);
        }
    }
    public long balance(String accountId) { return balances.getOrDefault(accountId, 0L); }
}

// ==== Demo ====
class Demo {
    public static void main(String[] args) {
        EventStore store = new InMemoryEventStore(new NoopUpcaster());
        SnapshotStore<BankAccountMemento> snap = new InMemorySnapshotStore<>();
        BankAccountRepository repo = new BankAccountRepository(store, snap, 50);

        String id = UUID.randomUUID().toString();

        // Create and persist
        BankAccount a = BankAccount.open(id, "Alice", "EUR");
        a.deposit(10_00);
        a.deposit(25_00);
        a.withdraw(5_00);
        repo.save(a);

        // Load and continue
        BankAccount b = repo.load(id);
        b.deposit(15_00);
        repo.save(b);

        // Project
        BalanceProjection proj = new BalanceProjection();
        for (DomainEvent e : store.loadStream(id, 0)) proj.handle(e);

        System.out.println("Projected balance (minor units): " + proj.balance(id));
    }
}
```

> Notes:
> 
> -   The snapshot’s `restore()` is simplified for brevity. In production, store exact fields and **hydrate state directly** (not via fake events), and persist the last applied version.
>     
> -   Replace `InMemoryEventStore` with a transactional store (RDBMS append table or EventStoreDB) and wire optimistic concurrency using a unique `(aggregate_id, version)` constraint.
>     

## Known Uses

-   **EventStoreDB / Axon / Lagom**: Native event sourcing with snapshots and upcasters.
    
-   **Financial ledgers**: Immutable transaction streams reconstruct balances precisely.
    
-   **Identity & access**: Auditable history of grants/revocations.
    
-   **eCommerce orders**: Order lifecycle reconstructed from domain events.
    
-   **IoT telemetry**: Device state derived from event streams with temporal analytics.
    

## Related Patterns

-   **CQRS:** Event Sourcing pairs naturally; commands produce events, projections serve queries.
    
-   **Event Replay:** Rebuild projections/read models from the log.
    
-   **Snapshotting:** Optimization to shorten replay horizons.
    
-   **Transactional Outbox:** Ensures events are reliably published alongside state transitions.
    
-   **Idempotent Receiver / Exactly-Once Effects:** Safe downstream processing.
    
-   **Event Upcasting (Schema Evolution):** Keep historical events readable as contracts evolve.

