
# Data Management & Database Pattern — Event Sourcing

## Pattern Name and Classification

-   **Name:** Event Sourcing

-   **Classification:** Data storage & consistency pattern (append-only log of domain events; state = fold over events)


## Intent

Persist the **sequence of domain events** that happened to an aggregate as the system’s **source of truth**. Recreate current state by **replaying** events (and optionally snapshots). This yields an immutable audit trail, natural integration via streams, and flexible read models.

## Also Known As

-   Event Log / Event Store

-   Append-Only Domain Journal

-   Source of Truth as Events


## Motivation (Forces)

-   **Auditability & traceability:** “What happened” beats “what is.”

-   **Complex invariants & evolution:** You can recompute new projections from the same facts.

-   **Integration:** Downstream services can subscribe to the event stream.

-   **Temporal queries:** Answer “as of” questions by replaying up to a point.


Tensions:

-   **Modeling discipline:** Events must be **meaningful facts**, not CRUD deltas.

-   **Operational complexity:** Rebuilds, projections, idempotency, ordering, and versioning.

-   **Querying:** Reads need **projections** (materialized views) rather than ad-hoc joins.


## Applicability

Use Event Sourcing when:

-   You need a **complete history**, audit, or time-travel.

-   Your domain emits natural **business events** (orders, payments, transfers).

-   You have multiple heterogeneous **read models** (CQRS) or integration subscribers.


Be cautious when:

-   The domain is simple CRUD with few invariants.

-   Strict global read-your-write across many aggregates is mandatory.

-   Ops maturity for streaming & projections is low.


## Structure

```pgsql
Client Commands ──► Aggregate (decision logic)
                         │ emits
                         ▼
                  Event Store (append-only per aggregate stream)
                         │ publish
                         ▼
                Projectors / Read Models (materialized views)
                         ▲
                Snapshots (optional checkpoints to speed replays)
```

## Participants

-   **Aggregate:** Encapsulates invariants; handles commands, emits events; applies events to mutate internal state.

-   **Event:** An immutable, versioned fact (e.g., `OrderPlaced`, `FundsWithdrawn`).

-   **Event Store:** Per-aggregate append-only streams; ensures optimistic concurrency with expected version.

-   **Snapshot Store (optional):** Periodic state checkpoints (`state@version`) to reduce replay time.

-   **Projector / Read Model:** Consumes events to maintain query-optimized views.

-   **Publisher / Bus (optional):** For streaming events to other services.


## Collaboration

1.  Client sends **command**.

2.  Aggregate validates invariants, **produces events** (0..n).

3.  Event Store **appends** with `expectedVersion` to enforce **optimistic concurrency**.

4.  Aggregate **applies** events to state; Store **publishes** to projectors.

5.  Projectors update **read models**; snapshots may be taken every N events.


## Consequences

**Benefits**

-   Immutability & **perfect audit**.

-   **Replayability** for new projections/bugs fixes/temporal analytics.

-   Natural **CQRS** and streaming integration.

-   Easier retroactive fixes via compensating events (no in-place edits).


**Liabilities**

-   **Event design** and **versioning** are hard; events are forever.

-   Requires **projections** for most queries.

-   **Rebuild** procedures and exactly-once-ish delivery concerns.

-   Large streams need **snapshots/compaction** to keep latencies low.


## Implementation (Key Points)

-   **Event identity:** `(aggregateId, version, timestamp, type, payload)`.

-   **Concurrency:** `append(streamId, expectedVersion, events)` — fail if versions diverge.

-   **Idempotency:** Use event IDs; consumers store offsets/checkpoints.

-   **Schema evolution:** Versioned payloads; upcasters or compatibility rules.

-   **Snapshots:** Save `S@v` after K events; on load, start from latest snapshot then replay `>v`.

-   **Publishing:** Outbox/CDC or native stream to deliver events to read-side reliably.

-   **Testing:** Given–When–Then: given events → when command → expect new events.


---

## Sample Code (Java 17): Minimal Event Store + Aggregate + Snapshot + Projection

> Single-file, in-memory example of a **BankAccount** aggregate with events  
> `AccountOpened`, `MoneyDeposited`, `MoneyWithdrawn`.
>
> -   Event store with **optimistic concurrency**
>
> -   Aggregate that **decides** and **applies** events
>
> -   **Snapshot** every N events
>
> -   **Projection** for a balance view  
      >     *(For brevity, serialization, upcasting, and persistence are elided.)*
>

```java
// File: EventSourcingDemo.java
// Compile: javac EventSourcingDemo.java
// Run:     java EventSourcingDemo
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/* ========== Event Model ========== */
sealed interface Event permits AccountOpened, MoneyDeposited, MoneyWithdrawn {
  UUID aggregateId();
  long version();          // 1..n within the aggregate stream
  Instant occurredAt();
}

record AccountOpened(UUID aggregateId, long version, Instant occurredAt, String owner, long openingCents) implements Event {}
record MoneyDeposited(UUID aggregateId, long version, Instant occurredAt, long cents) implements Event {}
record MoneyWithdrawn(UUID aggregateId, long version, Instant occurredAt, long cents) implements Event {}

/* ========== Event Store with optimistic concurrency and snapshots ========== */
final class EventStore {
  private final Map<UUID, List<Event>> streams = new ConcurrentHashMap<>();

  public synchronized List<Event> load(UUID id) {
    return new ArrayList<>(streams.getOrDefault(id, List.of()));
  }

  public synchronized long append(UUID id, long expectedVersion, List<Event> newEvents) {
    var cur = streams.getOrDefault(id, new ArrayList<>());
    long actual = cur.isEmpty() ? 0 : cur.get(cur.size()-1).version();
    if (actual != expectedVersion)
      throw new ConcurrentModificationException("expected v="+expectedVersion+" but was v="+actual);
    var copy = new ArrayList<>(cur);
    copy.addAll(newEvents);
    streams.put(id, copy);
    return copy.get(copy.size()-1).version();
  }
}

/* Optional snapshots for faster loads */
record Snapshot(UUID aggregateId, long version, long balanceCents, String owner, boolean opened) {}
final class SnapshotStore {
  private final Map<UUID, Snapshot> snaps = new ConcurrentHashMap<>();
  public Optional<Snapshot> load(UUID id) { return Optional.ofNullable(snaps.get(id)); }
  public void save(Snapshot s) { snaps.put(s.aggregateId(), s); }
}

/* ========== Aggregate (BankAccount) ========== */
final class BankAccount {
  private UUID id;
  private String owner;
  private long balanceCents;
  private boolean opened;
  private long version;

  /* --- Apply events (state transitions) --- */
  public void apply(Event e) {
    if (e instanceof AccountOpened ev) {
      this.id = ev.aggregateId();
      this.owner = ev.owner();
      this.balanceCents = ev.openingCents();
      this.opened = true;
      this.version = ev.version();
    } else if (e instanceof MoneyDeposited ev) {
      this.balanceCents += ev.cents();
      this.version = ev.version();
    } else if (e instanceof MoneyWithdrawn ev) {
      this.balanceCents -= ev.cents();
      this.version = ev.version();
    }
  }

  /* --- Command handlers (decision logic -> events) --- */
  public List<Event> open(UUID id, String owner, long openingCents) {
    if (opened) throw new IllegalStateException("already opened");
    if (openingCents < 0) throw new IllegalArgumentException("negative opening");
    return List.of(new AccountOpened(id, version + 1, Instant.now(), owner, openingCents));
  }

  public List<Event> deposit(long cents) {
    requireOpen();
    if (cents <= 0) throw new IllegalArgumentException("deposit must be positive");
    return List.of(new MoneyDeposited(id, version + 1, Instant.now(), cents));
  }

  public List<Event> withdraw(long cents) {
    requireOpen();
    if (cents <= 0) throw new IllegalArgumentException("withdraw must be positive");
    if (balanceCents - cents < 0) throw new IllegalStateException("insufficient funds");
    return List.of(new MoneyWithdrawn(id, version + 1, Instant.now(), cents));
  }

  private void requireOpen() { if (!opened) throw new IllegalStateException("not opened"); }

  /* --- Utilities --- */
  public long version() { return version; }
  public long balanceCents() { return balanceCents; }
  public String owner() { return owner; }
  public UUID id() { return id; }

  public Snapshot snapshot() { return new Snapshot(id, version, balanceCents, owner, opened); }

  /* Rehydrate from history/snapshot */
  public static BankAccount rehydrate(Optional<Snapshot> snap, List<Event> history) {
    BankAccount a = new BankAccount();
    snap.ifPresent(s -> {
      a.id = s.aggregateId();
      a.owner = s.owner();
      a.balanceCents = s.balanceCents();
      a.opened = s.opened();
      a.version = s.version();
    });
    for (Event e : history) {
      if (snap.isPresent() && e.version() <= snap.get().version()) continue;
      a.apply(e);
    }
    return a;
  }
}

/* ========== Projection (read model) ========== */
final class BalanceProjection {
  private final Map<UUID, Long> balances = new ConcurrentHashMap<>();
  public void handle(Event e) {
    if (e instanceof AccountOpened ev) balances.put(ev.aggregateId(), ev.openingCents());
    else if (e instanceof MoneyDeposited ev) balances.merge(ev.aggregateId(), ev.cents(), Long::sum);
    else if (e instanceof MoneyWithdrawn ev) balances.merge(ev.aggregateId(), -ev.cents(), Long::sum);
  }
  public long balanceOf(UUID id) { return balances.getOrDefault(id, 0L); }
}

/* ========== Application service / Repository ========== */
final class AccountService {
  private final EventStore store;
  private final SnapshotStore snaps;
  private final BalanceProjection balanceView;
  private final int snapshotEvery;

  AccountService(EventStore store, SnapshotStore snaps, BalanceProjection view, int snapshotEvery) {
    this.store = store; this.snaps = snaps; this.balanceView = view; this.snapshotEvery = snapshotEvery;
  }

  public long handleOpen(UUID id, String owner, long openingCents) {
    var agg = BankAccount.rehydrate(snaps.load(id), store.load(id));
    var newEvents = agg.open(id, owner, openingCents);
    appendAndPublish(id, agg.version(), newEvents, agg);
    return agg.version();
  }

  public long handleDeposit(UUID id, long cents) {
    var agg = BankAccount.rehydrate(snaps.load(id), store.load(id));
    var newEvents = agg.deposit(cents);
    appendAndPublish(id, agg.version(), newEvents, agg);
    return agg.version();
  }

  public long handleWithdraw(UUID id, long cents) {
    var agg = BankAccount.rehydrate(snaps.load(id), store.load(id));
    var newEvents = agg.withdraw(cents);
    appendAndPublish(id, agg.version(), newEvents, agg);
    return agg.version();
  }

  private void appendAndPublish(UUID id, long expectedVersion, List<Event> events, BankAccount aggAfterApply) {
    // append (assigns versions already set in events)
    long newVersion = store.append(id, expectedVersion, events);
    // publish to projection (synchronously for demo)
    events.forEach(balanceView::handle);
    // snapshot policy
    if (newVersion % snapshotEvery == 0) {
      snaps.save(aggAfterApply.snapshot());
    }
  }

  public long queryBalance(UUID id) { return balanceView.balanceOf(id); }
}

/* ========== Demo ========== */
public class EventSourcingDemo {
  public static void main(String[] args) {
    EventStore store = new EventStore();
    SnapshotStore snaps = new SnapshotStore();
    BalanceProjection view = new BalanceProjection();
    AccountService svc = new AccountService(store, snaps, view, 3); // snapshot every 3 events

    UUID acc = UUID.randomUUID();

    // 1) Open account + a few operations
    svc.handleOpen(acc, "Alice", 1_000);     // €10.00
    svc.handleDeposit(acc, 500);             // +€5.00
    svc.handleWithdraw(acc, 300);            // -€3.00

    System.out.printf("Balance now: €%.2f%n", svc.queryBalance(acc)/100.0);

    // 2) Rehydrate from snapshot + remaining events (simulate new service instance)
    var rehydrated = BankAccount.rehydrate(snaps.load(acc), store.load(acc));
    System.out.printf("Rehydrated state: owner=%s, version=%d, balance=€%.2f%n",
        rehydrated.owner(), rehydrated.version(), rehydrated.balanceCents()/100.0);

    // 3) Optimistic concurrency demo: racing write with stale expectedVersion
    try {
      // First, make a legit change to bump version
      svc.handleDeposit(acc, 100); // +€1
      // Now try appending as if someone cached version before the deposit
      var aggStale = BankAccount.rehydrate(snaps.load(acc), store.load(acc));
      var staleEvents = aggStale.withdraw(100); // would be ok logically
      // Falsify expected version (simulate stale client)
      store.append(acc, aggStale.version() - 1, staleEvents); // boom
    } catch (Exception ex) {
      System.out.println("Optimistic concurrency blocked stale write: " + ex);
    }

    System.out.printf("Final balance: €%.2f%n", svc.queryBalance(acc)/100.0);
  }
}
```

**What this demonstrates**

-   **Append-only** event store with **expectedVersion** to prevent lost updates.

-   Aggregate applying **domain events**; **commands** yield events (no direct state mutation).

-   **Snapshotting** every N events to speed up rehydration.

-   A simple **projection** (balance view) that consumes events to answer reads quickly.


---

## Known Uses

-   **Finance/ledgering:** balances and postings from transactions.

-   **Ordering & fulfillment:** orders evolve through event states; rebuildable timelines.

-   **IoT / telemetry:** device events feed projections & analytics.

-   **Collaboration & workflow:** immutable activity streams; rollups for views.


## Related Patterns

-   **CQRS:** Natural companion—write via commands/events; read via projections.

-   **Outbox / CDC:** Reliable event publication from the write side to downstream consumers.

-   **Saga / Process Manager:** Long-running, multi-aggregate workflows triggered by events.

-   **Snapshot / Memento:** Optimizes rehydration by persisting state checkpoints.

-   **Audit Log / Change Data Capture:** Alternative sources of events (from DB logs instead of domain logic).


---

### Practical Tips

-   Design **business-level** events (“FundsWithdrawn”) not technical deltas (“balanceChanged”).

-   Treat events as **immutable, append-only**; fix bugs via **new events** or upcasters, not edits.

-   Enforce **idempotency** and **ordering** in projectors (store last processed offset).

-   Start with an **in-process** projection; evolve to async streaming when needed.

-   Plan **evolution**: version fields, prefer additive changes, and maintain upcasters for old payloads.

-   Monitor: per-stream **length**, load/replay latency, projector **lag**, and append contention.
