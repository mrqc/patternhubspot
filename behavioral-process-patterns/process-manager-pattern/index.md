# Process Manager — Behavioral / Process Pattern

## Pattern Name and Classification

**Process Manager** — *Behavioral / Process* pattern that **coordinates a long-running, multi-step workflow** across components (or services) by reacting to events and issuing commands, while tracking **state, timeouts, retries, and compensations**.

---

## Intent

Centralize **orchestration logic** for a business process (e.g., checkout, onboarding) so that steps run in the right order, with **sagas/compensations** on failure, without point-to-point coupling between participants.

---

## Also Known As

-   **Saga Orchestrator** (DDD / microservices)

-   **Workflow Coordinator**

-   **Process Orchestrator / Controller**


---

## Motivation (Forces)

-   Multi-step flows span **several bounded contexts** or subsystems (Payments, Inventory, Shipping).

-   Steps are **asynchronous** and can fail; we need **retries, timeouts, and compensations**.

-   Keep domain services **local and focused**; avoid embedding orchestration in every service.

-   Make flows **observable**, testable, and changeable in one place.


Trade-offs: A central coordinator adds a component to run/operate; done poorly, it can turn into a “god service.” Scope it **per use case**.

---

## Applicability

Use a Process Manager when:

-   A business process has **more than two** asynchronous steps or cross-service calls.

-   You need **saga** semantics (compensations instead of global transactions).

-   Time-based progress (deadlines, SLAs) matters.


Avoid when:

-   One service can perform the flow **atomically** in a single transaction.

-   The steps are trivially sequential and co-located (simple method calls suffice).


---

## Structure

```markdown
(events)                     (commands)
Payments  ───────────▶                  ▲
Inventory ───────────▶   ProcessManager ├──▶ Payments / Inventory / Shipping
Shipping  ───────────▶    (stateful)    │
                                       (timers / retries / compensation)
```

---

## Participants

-   **Process Manager**: Holds **per-instance state**, consumes **events**, emits **commands**, sets timers.

-   **Domain Services**: Do the actual work (charge, reserve, ship), publish events.

-   **Event Bus**: Delivers domain events to the manager.

-   **Command Bus**: Dispatches commands to services.

-   **State Store**: Persists process instance state & deduplication markers.

-   **Timer/Scheduler**: Triggers timeouts and reminders.


---

## Collaboration

1.  A **trigger event** (e.g., `OrderPlaced`) creates/loads a process instance.

2.  Manager issues **next command** (e.g., `CapturePayment`) and records awaiting state + **deadline**.

3.  On **success/failure events**, the manager transitions state, issues follow-ups or **compensations**.

4.  On **timeout**, the manager escalates (retry, cancel, compensate).

5.  Manager marks the instance **completed** (success or terminal failure).


---

## Consequences

**Benefits**

-   **Single place** for orchestration logic; easier to reason about and test.

-   Supports **retries**, **timeouts**, **compensations**, and **idempotency**.

-   Decouples services; each remains cohesive.


**Liabilities**

-   Another **stateful** component to scale/operate.

-   Risk of central “brain” becoming too big—split **per process**.

-   Requires **reliable messaging** and **exactly-once-ish** handling.


---

## Implementation (Key Points)

-   One **aggregate-like** state per business instance (ID), persisted.

-   Make handlers **idempotent** (keep a processed-message set).

-   Use **outbox** or transactional messaging to publish events/commands atomically with state updates.

-   Model a small **FSM** inside the process manager (states + awaited events).

-   Add **deadlines** via a scheduler; persist due times.

-   Keep compensations explicit (e.g., `ReleaseInventory`, `RefundPayment`).

-   Prefer **per-use-case** managers to avoid a monolith.


---

## Sample Code (Java 17) — Checkout Saga with Timeouts & Compensations

> In-memory “walking skeleton” that you can persist later.  
> Flow: `OrderPlaced` → reserve stock → capture payment → create shipment.  
> Timeouts trigger retries then compensation.

```java
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Consumer;

// ===== Contracts =====
sealed interface Command permits ReserveStock, ReleaseStock, CapturePayment, RefundPayment, CreateShipment {
  String orderId();
}
sealed interface DomainEvent permits OrderPlaced, StockReserved, StockReservationFailed, PaymentCaptured, PaymentFailed, ShipmentCreated, ShipmentFailed, DeadlineFired {
  String orderId();
  String eventId();
  Instant at();
}

record ReserveStock(String orderId, List<String> skus) implements Command {}
record ReleaseStock(String orderId, List<String> skus) implements Command {}
record CapturePayment(String orderId, int amountCents) implements Command {}
record RefundPayment(String orderId, String paymentId) implements Command {}
record CreateShipment(String orderId) implements Command {}

record OrderPlaced(String orderId, List<String> skus, int amountCents, String eventId, Instant at) implements DomainEvent {}
record StockReserved(String orderId, String eventId, Instant at) implements DomainEvent {}
record StockReservationFailed(String orderId, String reason, String eventId, Instant at) implements DomainEvent {}
record PaymentCaptured(String orderId, String paymentId, String eventId, Instant at) implements DomainEvent {}
record PaymentFailed(String orderId, String reason, String eventId, Instant at) implements DomainEvent {}
record ShipmentCreated(String orderId, String tracking, String eventId, Instant at) implements DomainEvent {}
record ShipmentFailed(String orderId, String reason, String eventId, Instant at) implements DomainEvent {}
record DeadlineFired(String orderId, String key, String eventId, Instant at) implements DomainEvent {}

// ===== Buses (very small in-memory stubs) =====
interface EventBus { void publish(DomainEvent e); <T extends DomainEvent> void subscribe(Class<T> type, Consumer<T> h); }
interface CommandBus { void send(Command c); }

final class SimpleEventBus implements EventBus {
  private final Map<Class<?>, List<Consumer<?>>> subs = new ConcurrentHashMap<>();
  @Override public <T extends DomainEvent> void subscribe(Class<T> type, Consumer<T> h) {
    subs.computeIfAbsent(type, k -> new CopyOnWriteArrayList<>()).add(h);
  }
  @SuppressWarnings("unchecked")
  @Override public void publish(DomainEvent e) {
    subs.getOrDefault(e.getClass(), List.of()).forEach(h -> ((Consumer<DomainEvent>)h).accept(e));
  }
}

// ===== Fake domain services (emit events) =====
final class InventoryService {
  private final EventBus events;
  InventoryService(EventBus events) { this.events = events; }
  void handle(ReserveStock cmd) {
    // Pretend to reserve; always succeed here
    events.publish(new StockReserved(cmd.orderId(), uuid(), Instant.now()));
  }
  void handle(ReleaseStock cmd) { /* side-effect only */ }
}

final class PaymentService {
  private final EventBus events;
  PaymentService(EventBus events) { this.events = events; }
  void handle(CapturePayment cmd) {
    // Simulate possible failure by amount rule:
    if (cmd.amountCents() <= 0) {
      events.publish(new PaymentFailed(cmd.orderId(), "invalid-amount", uuid(), Instant.now()));
    } else {
      events.publish(new PaymentCaptured(cmd.orderId(), "pay_"+cmd.amountCents(), uuid(), Instant.now()));
    }
  }
  void handle(RefundPayment cmd) { /* side-effect only */ }
}

final class ShippingService {
  private final EventBus events;
  ShippingService(EventBus events) { this.events = events; }
  void handle(CreateShipment cmd) {
    events.publish(new ShipmentCreated(cmd.orderId(), "trk_"+cmd.orderId().hashCode(), uuid(), Instant.now()));
  }
}

final class SimpleCommandBus implements CommandBus {
  private final InventoryService inv; private final PaymentService pay; private final ShippingService ship;
  SimpleCommandBus(InventoryService i, PaymentService p, ShippingService s) { this.inv=i; this.pay=p; this.ship=s; }
  @Override public void send(Command c) {
    switch (c) {
      case ReserveStock rs -> inv.handle(rs);
      case ReleaseStock rl -> inv.handle(rl);
      case CapturePayment cp -> pay.handle(cp);
      case RefundPayment rf -> pay.handle(rf);
      case CreateShipment cs -> ship.handle(cs);
      default -> throw new IllegalArgumentException("Unknown cmd: "+c);
    }
  }
}

// ===== State store (per process instance) =====
enum PState { STARTED, STOCK_RESERVED, PAYMENT_CAPTURED, SHIPPED, FAILED, COMPENSATED }

final class ProcInstance {
  final String orderId;
  PState state = PState.STARTED;
  List<String> skus = List.of();
  int amountCents;
  String paymentId;
  final Set<String> seen = ConcurrentHashMap.newKeySet(); // idempotency
  int paymentRetry = 0;
  ProcInstance(String orderId) { this.orderId = orderId; }
}

interface ProcStore { ProcInstance getOrCreate(String orderId); void save(ProcInstance p); }
final class InMemoryProcStore implements ProcStore {
  private final Map<String, ProcInstance> db = new ConcurrentHashMap<>();
  @Override public ProcInstance getOrCreate(String id){ return db.computeIfAbsent(id, ProcInstance::new); }
  @Override public void save(ProcInstance p) { db.put(p.orderId, p); }
}

// ===== Deadline Scheduler =====
final class Deadlines {
  private final ScheduledExecutorService ses = Executors.newScheduledThreadPool(1);
  private final EventBus events;
  Deadlines(EventBus events) { this.events = events; }
  void schedule(String orderId, String key, Duration d) {
    ses.schedule(() -> events.publish(new DeadlineFired(orderId, key, uuid(), Instant.now())), d.toMillis(), TimeUnit.MILLISECONDS);
  }
  void shutdown(){ ses.shutdownNow(); }
}

// ===== Process Manager (Checkout Orchestrator) =====
final class CheckoutProcessManager {
  private final ProcStore store; private final CommandBus commands; private final Deadlines deadlines;

  CheckoutProcessManager(EventBus events, ProcStore store, CommandBus commands, Deadlines deadlines) {
    this.store = store; this.commands = commands; this.deadlines = deadlines;

    events.subscribe(OrderPlaced.class, this::on);
    events.subscribe(StockReserved.class, this::on);
    events.subscribe(StockReservationFailed.class, this::on);
    events.subscribe(PaymentCaptured.class, this::on);
    events.subscribe(PaymentFailed.class, this::on);
    events.subscribe(ShipmentCreated.class, this::on);
    events.subscribe(ShipmentFailed.class, this::on);
    events.subscribe(DeadlineFired.class, this::on);
  }

  private void on(OrderPlaced e) {
    var p = load(e);
    if (!markSeen(p, e)) return;
    p.skus = e.skus(); p.amountCents = e.amountCents();
    commands.send(new ReserveStock(p.orderId, p.skus));
    // Stock should come quickly; set a soft deadline
    deadlines.schedule(p.orderId, "stock-timeout", Duration.ofSeconds(10));
    save(p);
  }

  private void on(StockReserved e) {
    var p = load(e); if (!markSeen(p, e)) return;
    if (p.state != PState.STARTED) return; // idempotent
    p.state = PState.STOCK_RESERVED;
    commands.send(new CapturePayment(p.orderId, p.amountCents));
    deadlines.schedule(p.orderId, "payment-timeout", Duration.ofSeconds(10));
    save(p);
  }

  private void on(StockReservationFailed e) {
    var p = load(e); if (!markSeen(p, e)) return;
    fail(p, "stock-failed: " + e.reason());
  }

  private void on(PaymentCaptured e) {
    var p = load(e); if (!markSeen(p, e)) return;
    if (p.state != PState.STOCK_RESERVED) return;
    p.state = PState.PAYMENT_CAPTURED; p.paymentId = e.paymentId();
    commands.send(new CreateShipment(p.orderId));
    deadlines.schedule(p.orderId, "shipment-timeout", Duration.ofSeconds(20));
    save(p);
  }

  private void on(PaymentFailed e) {
    var p = load(e); if (!markSeen(p, e)) return;
    if (p.paymentRetry < 2) {
      p.paymentRetry++;
      commands.send(new CapturePayment(p.orderId, p.amountCents)); // retry
      deadlines.schedule(p.orderId, "payment-timeout", Duration.ofSeconds(10));
    } else {
      // compensate reserved stock
      commands.send(new ReleaseStock(p.orderId, p.skus));
      fail(p, "payment-failed: " + e.reason());
    }
    save(p);
  }

  private void on(ShipmentCreated e) {
    var p = load(e); if (!markSeen(p, e)) return;
    p.state = PState.SHIPPED;
    complete(p, "ok: tracking="+e.tracking());
  }

  private void on(ShipmentFailed e) {
    var p = load(e); if (!markSeen(p, e)) return;
    // Compensate payment & stock
    if (p.paymentId != null) commands.send(new RefundPayment(p.orderId, p.paymentId));
    commands.send(new ReleaseStock(p.orderId, p.skus));
    fail(p, "shipment-failed: " + e.reason());
  }

  private void on(DeadlineFired e) {
    var p = load(e); if (!markSeen(p, e)) return;
    switch (e.key()) {
      case "stock-timeout" -> { if (p.state == PState.STARTED) fail(p, "stock-timeout"); }
      case "payment-timeout" -> {
        if (p.state == PState.STOCK_RESERVED) {
          // treat as payment failure to trigger retry flow
          on(new PaymentFailed(p.orderId, "timeout", uuid(), Instant.now()));
        }
      }
      case "shipment-timeout" -> {
        if (p.state == PState.PAYMENT_CAPTURED) {
          on(new ShipmentFailed(p.orderId, "timeout", uuid(), Instant.now()));
        }
      }
      default -> {}
    }
  }

  // ==== helpers ====
  private ProcInstance load(DomainEvent e) { return store.getOrCreate(e.orderId()); }
  private boolean markSeen(ProcInstance p, DomainEvent e) { return p.seen.add(e.eventId()); } // idempotent
  private void save(ProcInstance p){ store.save(p); }

  private void fail(ProcInstance p, String reason) {
    p.state = p.state == PState.SHIPPED ? PState.SHIPPED : PState.FAILED;
    System.err.println("[PROC " + p.orderId + "] FAILED: " + reason);
    save(p);
  }
  private void complete(ProcInstance p, String msg) {
    System.out.println("[PROC " + p.orderId + "] COMPLETED: " + msg);
    save(p);
  }
  private static String uuid(){ return UUID.randomUUID().toString(); }
}

// ===== Demo (wiring) =====
public class ProcessManagerDemo {
  public static void main(String[] args) throws Exception {
    var events = new SimpleEventBus();
    var deadlines = new Deadlines(events);

    var inventory = new InventoryService(events);
    var payments = new PaymentService(events);
    var shipping = new ShippingService(events);
    var commands = new SimpleCommandBus(inventory, payments, shipping);

    var store = new InMemoryProcStore();
    new CheckoutProcessManager(events, store, commands, deadlines);

    // Kick off a happy path
    var placed = new OrderPlaced("o-1001", List.of("sku-1","sku-2"), 2599, UUID.randomUUID().toString(), Instant.now());
    events.publish(placed);

    // Kick off a failure (payment invalid)
    var bad = new OrderPlaced("o-1002", List.of("sku-3"), 0, UUID.randomUUID().toString(), Instant.now());
    events.publish(bad);

    // Let the async deadlines and handlers run a bit
    Thread.sleep(500);
    deadlines.shutdown();
  }
}
```

### What to notice

-   The **process manager** keeps **per-order state** and an **idempotency set** to ignore duplicate events.

-   **Deadlines** are scheduled and delivered as synthetic events (timeouts).

-   **Retries** on payment, then **compensation** (release stock / refund) on failure.

-   All collaborators are **decoupled**: they only know commands/events, not each other.


---

## Known Uses

-   **E-commerce checkout**, **subscription lifecycle**, **KY C onboarding**, **loan origination**, **travel booking**.

-   Microservice sagas in platforms at scale (payments → inventory → fulfillment) coordinated by an **orchestrator** rather than pure choreography.


---

## Related Patterns

-   **Saga** — the process manager is the **orchestrator** form of sagas.

-   **Mediator** — similar “coordination” role but within a single app/module; a process manager adds **state + timers**.

-   **Finite State Machine** — often the internal model used by the process manager.

-   **Outbox / Transactional Messaging** — to publish events atomically with state updates.

-   **Retry / Circuit Breaker / Idempotency Key** — supporting patterns for reliable steps.
