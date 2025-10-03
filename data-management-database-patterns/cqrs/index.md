
# Data Management & Database Pattern — CQRS (Command Query Responsibility Segregation)

## Pattern Name and Classification

-   **Name:** CQRS — Command Query Responsibility Segregation

-   **Classification:** Architectural pattern for **read/write separation** (data access & consistency)


## Intent

Split the model and pathways that **change state (commands)** from those that **read state (queries)**. Each side is optimized independently (write model for invariants & transactions; read model(s) for fast, tailored queries), often with **asynchronous propagation** from writes to queries.

## Also Known As

-   Command/Query Split

-   Read/Write Segregation

-   Task-based UIs (when paired with explicit commands)


## Motivation (Forces)

-   **Different access patterns:** Reads typically dominate and have varied shapes; writes need invariants and validation.

-   **Scalability:** Scale reads horizontally (caches, replicas, denormalized views) without burdening the write path.

-   **Velocity of change:** UI/reporting can evolve independently of domain logic.

-   **Performance:** Read models can be **denormalized** and indexed per use case.

-   **Complexity trade:** Propagating changes to read models introduces **eventual consistency** and failure modes.


## Applicability

Use CQRS when:

-   The domain is non-trivial: rich invariants, workflows, or collaboration.

-   Read and write workloads have **different SLAs** (e.g., 100k rps reads, modest writes).

-   You need multiple **tailored read models** (dashboards, search, mobile).

-   You aim to pair with **Event Sourcing** (not required but common).


Avoid/Adapt when:

-   The system is simple CRUD; one relational model suffices.

-   Strong **read-your-write** guarantees are required through the same store (unless you read from the write model).

-   Operational maturity for **asynchronous messaging** is lacking.


## Structure

```pgsql
+----------+        +----------------------+         +------------------+
|  Client  |---Cmd->|  Command API/Handlers|--Events->|   Projectors     |
+----------+        +----------------------+         +--------+---------+
                         |  invariants, agg.                  |
                         v                                    v
                  [Write Model / Store]                [Read Model(s)/Stores]
                         ^                                    ^
                         |                                    |
                     (optional)                         Query API/Handlers
                   Event Store/Bus                      (fast, denormalized)
```

## Participants

-   **Commands:** Intent to change state; *imperative* (“RegisterUser”, “PlaceOrder”).

-   **Command Handlers / Write Model:** Validate invariants, load aggregates, apply changes.

-   **Events (optional but typical):** Facts emitted after successful commands.

-   **Event Store / Bus (optional):** Persists & publishes events.

-   **Projectors / View Updaters:** Consume events and update **read models**.

-   **Read Models:** Query-optimized, denormalized views (RDBMS tables, caches, indices).

-   **Queries / Query Handlers:** Read-only access paths.


## Collaboration

1.  Client sends a **Command** → Command Handler validates invariants and commits to the **write store**.

2.  Handler emits **Domain Events**; they are persisted and **published**.

3.  **Projectors** consume events and update **read models** asynchronously (often idempotently).

4.  Client executes **Queries** against read models. (For strict read-your-write, query the write side or use a read-your-write strategy.)


## Consequences

**Benefits**

-   Independent **scaling** and **optimization** of reads vs. writes.

-   Clear separation of concerns; models stay focused.

-   Easy to add **new read models** without touching the write model.

-   Works well with **event-driven** systems, auditability (with Event Sourcing).


**Liabilities**

-   **Eventual consistency**: reads may lag writes.

-   More moving parts: messaging, retries, idempotency, out-of-order delivery.

-   **Data duplication** across read models; need rebuild strategies.

-   Transactions across write + read models are **distributed** (avoid, or use sagas).


## Implementation (Key Points)

-   **Boundaries:** Treat commands as **task-based** (user intent), not setters.

-   **Idempotency:** Include command IDs; make projectors idempotent (store last processed sequence).

-   **Versioning & concurrency:** Use **optimistic concurrency** on aggregates (event/store version).

-   **Messaging:** Durable event log or bus; guarantee *at-least-once* to projectors.

-   **Rebuilds:** Allow read models to be **replayed** from the event store.

-   **Consistency options:**

    -   *Eventual*: default; surface freshness to clients.

    -   *Read-your-write*: read from write model or fence with version tokens.

-   **Testing:** Unit-test aggregate behavior with **Given–When–Then** (events in → command → new events out).


---

## Sample Code (Java 17): Minimal CQRS with Evented Write Model & Read Model Projector

> Educational, single-JVM demo (no external frameworks).
>
> -   Write side: event-sourced `UserAccount` aggregate, optimistic concurrency.
>
> -   Event Bus + Projector update an in-memory read model (`UserProfileView`).
>
> -   Query side: fast lookups by ID and by email.
>
> -   All synchronous for simplicity (swap EventBus for async in production).
>

```java
// File: CqrsDemo.java
// Compile: javac CqrsDemo.java
// Run:     java CqrsDemo
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/* ======== Messages ======== */
sealed interface Command permits RegisterUser, ChangeEmail { UUID aggregateId(); UUID commandId(); }
record RegisterUser(UUID aggregateId, UUID commandId, String email, String displayName) implements Command {}
record ChangeEmail(UUID aggregateId, UUID commandId, String newEmail) implements Command {}

sealed interface Event permits UserRegistered, EmailChanged {
  UUID aggregateId(); long version(); Instant occurredAt();
}
record UserRegistered(UUID aggregateId, long version, Instant occurredAt, String email, String displayName) implements Event {}
record EmailChanged(UUID aggregateId, long version, Instant occurredAt, String newEmail) implements Event {}

/* ======== Write side: Event Store + Aggregate ======== */
final class EventStore {
  // append-only per aggregate
  private final Map<UUID, List<Event>> streams = new ConcurrentHashMap<>();

  public synchronized List<Event> load(UUID id) {
    return new ArrayList<>(streams.getOrDefault(id, List.of()));
  }

  public synchronized void append(UUID id, long expectedVersion, List<Event> newEvents) {
    var cur = streams.getOrDefault(id, new ArrayList<>());
    long actual = cur.isEmpty() ? 0 : cur.get(cur.size()-1).version();
    if (actual != expectedVersion) throw new ConcurrentModificationException("expected v="+expectedVersion+" but was "+actual);
    cur = new ArrayList<>(cur); cur.addAll(newEvents);
    streams.put(id, cur);
  }

  public long currentVersion(UUID id) {
    var cur = streams.get(id); return (cur==null || cur.isEmpty())?0:cur.get(cur.size()-1).version();
  }

  public void visitAll(java.util.function.Consumer<Event> visitor) {
    streams.values().forEach(list -> list.forEach(visitor));
  }
}

final class UserAccount {
  private UUID id;
  private String email;
  private String displayName;
  private long version;

  static UserAccount rehydrate(List<Event> history) {
    var agg = new UserAccount();
    history.forEach(agg::apply);
    return agg;
  }

  /* Decision methods -> events */
  List<Event> handle(RegisterUser cmd) {
    if (id != null) throw new IllegalStateException("already registered");
    if (cmd.email() == null || cmd.email().isBlank()) throw new IllegalArgumentException("email required");
    return List.of(new UserRegistered(cmd.aggregateId(), version+1, Instant.now(), cmd.email(), cmd.displayName()));
  }
  List<Event> handle(ChangeEmail cmd) {
    if (id == null) throw new IllegalStateException("not registered");
    if (Objects.equals(email, cmd.newEmail())) return List.of(); // idempotent no-op
    if (cmd.newEmail() == null || cmd.newEmail().isBlank()) throw new IllegalArgumentException("new email required");
    return List.of(new EmailChanged(id, version+1, Instant.now(), cmd.newEmail()));
  }

  /* Mutation by events */
  private void apply(Event e) {
    if (e instanceof UserRegistered ev) {
      this.id = ev.aggregateId();
      this.email = ev.email();
      this.displayName = ev.displayName();
      this.version = ev.version();
    } else if (e instanceof EmailChanged ev) {
      this.email = ev.newEmail();
      this.version = ev.version();
    }
  }

  /* Persist & publish helper */
  static List<Event> decideAndApply(UserAccount agg, Command cmd) {
    List<Event> events = switch (cmd) {
      case RegisterUser r -> agg.handle(r);
      case ChangeEmail c -> agg.handle(c);
    };
    events.forEach(agg::apply);
    return events;
  }

  public long version() { return version; }
}

/* ======== Infrastructure: EventBus & Projector ======== */
interface EventSubscriber { void handle(Event e); }

final class EventBus {
  private final List<EventSubscriber> subscribers = new ArrayList<>();
  void publish(List<Event> events) { events.forEach(e -> subscribers.forEach(s -> s.handle(e))); }
  void subscribe(EventSubscriber s) { subscribers.add(s); }
}

/* ======== Read side: denormalized view & projector ======== */
record UserProfileView(UUID id, String email, String displayName, long version) {}

final class UserProfileReadModel implements EventSubscriber {
  private final Map<UUID, UserProfileView> byId = new ConcurrentHashMap<>();
  private final Map<String, UUID> idByEmail = new ConcurrentHashMap<>();

  @Override public void handle(Event e) {
    if (e instanceof UserRegistered ev) {
      byId.put(ev.aggregateId(), new UserProfileView(ev.aggregateId(), ev.email(), ev.displayName(), ev.version()));
      idByEmail.put(ev.email(), ev.aggregateId());
    } else if (e instanceof EmailChanged ev) {
      var cur = byId.get(ev.aggregateId());
      if (cur == null || ev.version() <= cur.version()) return; // idempotent / out-of-order guard
      idByEmail.remove(cur.email());
      var next = new UserProfileView(ev.aggregateId(), ev.newEmail(), cur.displayName(), ev.version());
      byId.put(ev.aggregateId(), next);
      idByEmail.put(ev.newEmail(), ev.aggregateId());
    }
  }

  // Query API
  public Optional<UserProfileView> byId(UUID id) { return Optional.ofNullable(byId.get(id)); }
  public Optional<UserProfileView> byEmail(String email) {
    var id = idByEmail.get(email); return id == null ? Optional.empty() : byId(id);
  }
}

/* ======== Application Services (Command + Query) ======== */
final class UserCommandService {
  private final EventStore store;
  private final EventBus bus;

  UserCommandService(EventStore store, EventBus bus) { this.store = store; this.bus = bus; }

  public long handle(Command cmd) {
    var history = store.load(cmd.aggregateId());
    var agg = UserAccount.rehydrate(history);
    long expected = history.isEmpty()?0:history.get(history.size()-1).version();
    var newEvents = UserAccount.decideAndApply(agg, cmd);
    if (!newEvents.isEmpty()) {
      store.append(cmd.aggregateId(), expected, newEvents);
      bus.publish(newEvents);
    }
    return agg.version();
  }
}

final class UserQueryService {
  private final UserProfileReadModel view;
  UserQueryService(UserProfileReadModel view) { this.view = view; }
  public Optional<UserProfileView> get(UUID id) { return view.byId(id); }
  public Optional<UserProfileView> findByEmail(String email) { return view.byEmail(email); }
}

/* ======== Demo ======== */
public class CqrsDemo {
  public static void main(String[] args) {
    var store = new EventStore();
    var bus = new EventBus();
    var view = new UserProfileReadModel();
    bus.subscribe(view);

    var cmdSvc = new UserCommandService(store, bus);
    var qrySvc = new UserQueryService(view);

    UUID userId = UUID.randomUUID();

    // 1) Register user (write) → event → projector updates read model
    cmdSvc.handle(new RegisterUser(userId, UUID.randomUUID(), "alice@example.com", "Alice"));

    // 2) Query read model
    System.out.println("By email: " + qrySvc.findByEmail("alice@example.com").orElseThrow());

    // 3) Change email
    cmdSvc.handle(new ChangeEmail(userId, UUID.randomUUID(), "a.smith@example.com"));

    // 4) Query again (read-your-write here is synchronous for demo)
    System.out.println("By id:    " + qrySvc.get(userId).orElseThrow());
    System.out.println("By email: " + qrySvc.findByEmail("a.smith@example.com").orElseThrow());

    // 5) Rebuild capability: wipe view & replay (simulating projector rebuild)
    var rebuild = new UserProfileReadModel();
    store.visitAll(rebuild::handle);
    System.out.println("After replay: " + new UserQueryService(rebuild).get(userId).orElseThrow());
  }
}
```

**What this shows**

-   **Commands** mutate only the write model; **queries** hit a denormalized read model.

-   **Events** are appended and published; **projector** updates views idempotently and in order.

-   **Optimistic concurrency** on append to guard against lost updates.

-   Read model can be **rebuilt** by replaying stored events.


> Productionize with: persistent event log, asynchronous durable bus (Kafka/RabbitMQ), projector offsets, idempotency keys, retries, and multiple read models (e.g., search index + cache).

---

## Known Uses

-   **eCommerce / order management:** commands for checkout & payment; read models for catalog/search/order history.

-   **Financial ledgers:** event-sourced accounts and many read views (balances, statements, risk).

-   **Collaboration tools:** command side enforces permissions; read side powers timelines & search.

-   **IoT / telemetry:** device commands vs. analytics dashboards and rollups.

-   **Microservices:** write service emits events; downstream services maintain their own query stores.


## Related Patterns

-   **Event Sourcing:** Natural companion—store events, rebuild state and views.

-   **Materialized View / Read-Optimized Index:** The read side in CQRS.

-   **Saga / Process Manager:** Coordinates multi-aggregate workflows across events/commands.

-   **Outbox / Transactional Messaging:** Guarantees that events are published when state changes.

-   **API Gateway / BFF:** Often fronts multiple read models tailor-made for clients.

-   **Domain-Driven Design (DDD):** Commands/Aggregates/Events vocabulary fits the write side.


---

### Practical Tips

-   Start **simple**: a single read model and synchronous projection; evolve to async when needed.

-   Expose **freshness** (sequence/version) with query responses; let clients choose stale-OK vs. strong-consistency path.

-   Make projectors **idempotent & replayable** (store last processed offset per projector).

-   Use **optimistic concurrency** on the write side (aggregate version).

-   For *hot* read paths, put the read model in a **cache** or a **specialized index** (e.g., Elastic).

-   Guard privacy/compliance: read models duplicate data—plan **redactions** and **GDPR** erasure workflows.
