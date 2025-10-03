# Eventual Consistency — Cloud / Distributed Systems Pattern

## Pattern Name and Classification

**Eventual Consistency** — *Cloud / Distributed Systems* **consistency** pattern in which distributed replicas or read models **converge** to the same value **without requiring synchronous coordination** on each update.

---

## Intent

Allow **high availability and low latency** by accepting **temporarily divergent** views of data that **converge** via asynchronous replication, events, or background repair.

---

## Also Known As

-   **AP Consistency (under CAP)**

-   **Optimistic Replication**

-   **Convergent Consistency** (when using CRDTs)


---

## Motivation (Forces)

-   Cross-region or partition-prone systems can’t wait for **global consensus** on every write.

-   Some operations prefer **availability** (accept the write) and **fast local reads**, then **reconcile**.

-   Many user experiences tolerate brief staleness (feeds, counters, search indexes, analytics).


**Tensions:**

-   **Staleness windows** vs. user expectations (read-your-writes).

-   **Conflict resolution** when concurrent updates occur.

-   **Visibility** (surfacing lags) and **repair** (read-repair/anti-entropy).


---

## Applicability

Use Eventual Consistency when:

-   You need to keep serving during **partitions** or cross-region network slowness.

-   Read models or indexes can be **asynchronously** updated.

-   You can define **merging rules** (LWW, CRDTs, domain-specific reconciliation).


Avoid when:

-   The domain requires **strong invariants** at read time (e.g., double-spend prevention) — use **CP**/transactions or compensating processes.


---

## Structure

```pgsql
Command (write)                      Async propagation
Client ────────────────▶ Write Model ── emits domain event ──▶ Event Bus ──▶ Projector(s)
                               │                                                   │
                               └──────────── eventual convergence ────────────────▶ Read Model(s)

Reads hit Read Models which may lag; they converge as projectors process events.
```

---

## Participants

-   **Write Model / Source of Truth** — accepts commands; persists authoritative changes.

-   **Event Bus / Change Feed** — transports changes asynchronously (outbox/CDC/stream).

-   **Projector / Replicator** — consumes events, updates **read models/replicas**.

-   **Read Model / Replica** — optimized for queries; may be stale; eventually converges.

-   **Reconciler** *(optional)* — resolves conflicts or performs read-repair/anti-entropy.


---

## Collaboration

1.  Client issues a **command**; write model applies it and **emits an event** (transactional outbox or CDC).

2.  **Projectors** asynchronously process events and update **read models/replicas**.

3.  Clients **read** from read models; if stale, they see earlier data until propagation completes.

4.  Background **repair** or **merge rules** ensure convergence across replicas.


---

## Consequences

**Benefits**

-   **High availability** and **low latency** across regions.

-   Scales read/write throughput independently (CQRS-friendly).

-   Enables specialized **read models** (search index, cache, analytics).


**Liabilities**

-   **Stale reads**; clients may not observe **read-your-writes**.

-   Requires **conflict resolution** for concurrent updates.

-   Operational complexity: **lag monitoring**, **idempotency**, **replay**.


---

## Implementation (Key Points)

-   Use **transactional outbox** or **CDC** to publish events reliably.

-   Make projectors **idempotent**; store **last processed offset/version**.

-   Expose **consistency metadata** to clients (e.g., `X-Event-Offset`, vector clock, or “last-updated-at”).

-   Provide user-level strategies: **read-after-write** by temporarily hitting the write model, **write-through cache**, or **session stickiness**.

-   For multi-writer replication, pick a **merge policy** (LWW timestamps, **CRDTs**, or domain-specific rules).

-   Add **repair**: read-repair on access or periodic anti-entropy jobs.


---

## Sample Code (Java 17) — CQRS-style eventual consistency with an async projector

> This toy shows a **Profile** write model emitting events to an in-memory bus.  
> A **Projector** updates a **ReadModel** with a delay, demonstrating temporary staleness and eventual convergence.  
> Includes **outbox idempotency**, **versioning**, and an optional *read-your-writes* escape hatch.

```java
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;

// ===== Domain & Events =====
record Profile(String userId, String bio, Instant updatedAt, long version) {}

sealed interface DomainEvent permits ProfileUpdated {
  String userId();
  long version();
  Instant at();
}
record ProfileUpdated(String userId, String bio, long version, Instant at) implements DomainEvent {}

// ===== Write Model (authoritative) + Outbox =====
final class ProfileWriteModel {
  private final Map<String, Profile> store = new ConcurrentHashMap<>();
  private final Outbox outbox;

  ProfileWriteModel(Outbox outbox) { this.outbox = outbox; }

  public Profile upsert(String userId, String bio) {
    var now = Instant.now();
    var current = store.get(userId);
    long nextVer = (current == null ? 1 : current.version() + 1);
    var p = new Profile(userId, bio, now, nextVer);
    store.put(userId, p);
    // transactional outbox (same tx as store in real life)
    outbox.enqueue(new ProfileUpdated(userId, bio, nextVer, now));
    return p;
  }

  // escape hatch for read-after-write
  public Optional<Profile> getAuthoritative(String userId) {
    return Optional.ofNullable(store.get(userId));
  }
}

// ===== Outbox + Event Bus =====
interface EventBus { void publish(DomainEvent e); }

final class SimpleEventBus implements EventBus {
  private final List<Listener> listeners = new CopyOnWriteArrayList<>();
  interface Listener { void on(DomainEvent e); }
  public void subscribe(Listener l) { listeners.add(l); }
  @Override public void publish(DomainEvent e) { listeners.forEach(l -> l.on(e)); }
}

final class Outbox {
  private final Queue<DomainEvent> queue = new ConcurrentLinkedQueue<>();
  private final EventBus bus;
  Outbox(EventBus bus) { this.bus = bus; }
  void enqueue(DomainEvent e) { queue.add(e); }
  // background dispatcher
  void flushAll() { DomainEvent e; while ((e = queue.poll()) != null) bus.publish(e); }
}

// ===== Read Model (eventually consistent projection) =====
record ProfileView(String userId, String bio, Instant lastUpdated, long version) {}

final class ProfileReadModel {
  private final Map<String, ProfileView> views = new ConcurrentHashMap<>();
  // idempotency: remember highest processed version per user
  private final Map<String, Long> processedVersion = new ConcurrentHashMap<>();

  public void apply(ProfileUpdated e) {
    long seen = processedVersion.getOrDefault(e.userId(), 0L);
    if (e.version() <= seen) return; // idempotent / out-of-order safe (LWW by version)
    views.put(e.userId(), new ProfileView(e.userId(), e.bio(), e.at(), e.version()));
    processedVersion.put(e.userId(), e.version());
  }

  public Optional<ProfileView> get(String userId) {
    return Optional.ofNullable(views.get(userId));
  }
}

// ===== Projector (async, with artificial lag) =====
final class ProfileProjector {
  private final ProfileReadModel readModel;
  private final ScheduledExecutorService ses = Executors.newSingleThreadScheduledExecutor(r -> {
    Thread t = new Thread(r, "projector"); t.setDaemon(true); return t;
  });
  private final long artificialLagMs;

  ProfileProjector(SimpleEventBus bus, ProfileReadModel readModel, long lagMs) {
    this.readModel = readModel; this.artificialLagMs = lagMs;
    bus.subscribe(this::onEvent);
  }

  private void onEvent(DomainEvent e) {
    // simulate laggy async processing
    ses.schedule(() -> {
      if (e instanceof ProfileUpdated pu) readModel.apply(pu);
    }, artificialLagMs, TimeUnit.MILLISECONDS);
  }

  void shutdown() { ses.shutdownNow(); }
}

// ===== API Facade (showing eventual read & read-your-writes option) =====
final class ProfileService {
  private final ProfileWriteModel write;
  private final ProfileReadModel read;
  ProfileService(ProfileWriteModel write, ProfileReadModel read) { this.write = write; this.read = read; }

  // standard read (may be stale)
  Optional<ProfileView> getEventuallyConsistent(String userId) {
    return read.get(userId);
  }

  // read-your-writes by falling back to write model if versions differ or view missing
  Optional<ProfileView> getReadYourWrites(String userId) {
    var view = read.get(userId);
    var auth = write.getAuthoritative(userId);
    if (auth.isEmpty()) return view;               // nothing known
    if (view.isEmpty() || view.get().version() < auth.get().version()) {
      var p = auth.get();
      return Optional.of(new ProfileView(p.userId(), p.bio(), p.updatedAt(), p.version()));
    }
    return view;
  }

  Profile updateBio(String userId, String bio) {
    return write.upsert(userId, bio);
  }
}

// ===== Demo =====
public class EventualConsistencyDemo {
  public static void main(String[] args) throws Exception {
    var bus = new SimpleEventBus();
    var outbox = new Outbox(bus);
    var write = new ProfileWriteModel(outbox);
    var read = new ProfileReadModel();
    var projector = new ProfileProjector(bus, read, /*lag*/ 500); // 500ms lag
    var svc = new ProfileService(write, read);

    // 1) Update profile (write happens immediately)
    var p1 = svc.updateBio("u-1", "Hello world!");

    // 2) Immediately try to read from the read model (likely stale or missing)
    System.out.println("Immediately eventual read: " + svc.getEventuallyConsistent("u-1"));

    // 3) Flush outbox to publish events; projector will apply after lag
    outbox.flushAll();

    // 4) Provide read-your-writes view for the updating session
    System.out.println("Read-your-writes: " + svc.getReadYourWrites("u-1"));

    // 5) Wait for projector lag to elapse; eventual read converges
    Thread.sleep(700);
    System.out.println("Eventually consistent read: " + svc.getEventuallyConsistent("u-1"));

    // 6) Concurrent update demo (version ensures monotonic apply)
    var p2 = svc.updateBio("u-1", "New bio");
    outbox.flushAll();
    Thread.sleep(700);
    System.out.println("After second update: " + svc.getEventuallyConsistent("u-1"));

    projector.shutdown();
  }
}
```

**What to notice**

-   Writes succeed immediately; **events** are queued in an **outbox** and **projected asynchronously**.

-   Reads from the read model can be **stale** until the projector catches up.

-   **Idempotency & ordering** via a per-user **version** prevents out-of-order regression.

-   **Read-your-writes** is implemented by falling back to the **authoritative** model when necessary.


---

## Known Uses

-   **CQRS** read models and **search indexes** (Elasticsearch/Solr) built from transaction logs.

-   **Dynamo/Cassandra** replication with **read-repair** and **hinted handoff**.

-   **Notification & feed systems**, **counters**, **analytics** pipelines.

-   **Geo-replicated** services that accept writes locally and reconcile later.


---

## Related Patterns

-   **CAP / AP Systems** — conceptual backdrop; eventual consistency is the AP side.

-   **CRDTs** — data types that **converge** automatically under concurrent updates.

-   **Read Repair / Anti-Entropy** — background reconciliation.

-   **Transactional Outbox & CDC** — reliable event emission from writes.

-   **Saga** — process-level compensation when stale reads cause anomalies.

-   **Cache Aside** — caches that may be stale, refilled asynchronously.
