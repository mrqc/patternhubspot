# Saga — Behavioral / Process Pattern / Cloud Distributed System Pattern

## Pattern Name and Classification

**Saga** — *Behavioral / Process* pattern for **long-running, distributed transactions** composed of a sequence of **local steps** with **compensating actions** on failure. Implemented as **Orchestration** (central coordinator) or **Choreography** (peer-to-peer event choreography).

---

## Intent

Maintain **business consistency** across multiple services **without** a global ACID transaction by chaining local transactions (**T1, T2, …**) and, on failure, running **compensations** (**C1, C2, …**) to semantically undo prior work.

---

## Also Known As

-   **Distributed Transaction with Compensations**

-   **Process Saga**

-   **Orchestrated Saga** / **Choreographed Saga**


---

## Motivation (Forces)

-   Cross-service operations (e.g., checkout: reserve stock → charge payment → ship) need **all-or-compensated** behavior, but 2PC is impractical.

-   Steps are **asynchronous**, **fallible**, and have different latencies/SLAs.

-   We need **retries, timeouts, deduplication**, and **observability**.


**Trade-offs**

-   Orchestration centralizes flow (easier to see/test) but risks a “brain” service if it grows.

-   Choreography avoids a central coordinator but can lead to **implicit coupling** and **event spaghetti** if not modeled clearly.


---

## Applicability

Use Sagas when:

-   A use case spans **multiple bounded contexts/services**.

-   The overall outcome must be **consistent**, not necessarily **instantaneously**.

-   You can define **compensations** for each step.


Avoid when:

-   A single service can complete the operation **atomically**.

-   There is **no meaningful compensation** (consider reservation/holding or escrow first).


---

## Structure

**Two common styles**

1.  **Orchestration** (central coordinator)


```perl
Process Manager (Orchestrator)
  ├─ send -> ReserveStock  ──> Inventory  ── emits ─> StockReserved/Failed
  ├─ send -> CapturePayment ─> Payments   ── emits ─> PaymentCaptured/Failed
  └─ send -> CreateShipment ─> Shipping   ── emits ─> ShipmentCreated/Failed
(compensation on failure: ReleaseStock, RefundPayment, etc.)
```

2.  **Choreography** (peer-to-peer)


```markdown
OrderPlaced ──► Inventory ──StockReserved──► Payments ──PaymentCaptured──► Shipping ──ShipmentCreated
      └───StockReservationFailed/PaymentFailed/ShipmentFailed trigger compensations upstream
```

---

## Participants

-   **Saga Instance**: the logical execution for one business case (e.g., `orderId`).

-   **Steps / Local Transactions**: service-specific actions with their own storage/locks.

-   **Compensations**: semantic undo for each step.

-   **Events**: signal step outcomes; carry **correlation ids**.

-   **Message Infrastructure**: reliable delivery, ordering (per key), and **outbox** support.


---

## Collaboration

1.  A **trigger** starts the saga (e.g., `OrderPlaced`).

2.  Each successful step publishes an **event** that triggers the **next** step.

3.  On failure/timeout, the saga runs **compensations** for previously completed steps in reverse order.

4.  The saga **completes** (success or terminal failure), emitting a final event.


---

## Consequences

**Benefits**

-   Achieves **business consistency** without 2PC.

-   Works with **autonomous services** and local databases.

-   Explicit **compensations** make failure handling first-class.


**Liabilities**

-   More moving parts: **idempotency**, **deduplication**, **timeouts/retries** required.

-   Choreography can become implicit and hard to trace; orchestration can centralize too much.

-   Requires **careful design** of compensations (not always perfect inverse).


---

## Implementation (Key Points)

-   Use **correlation IDs** (e.g., `orderId`) and **event IDs** for idempotency.

-   Persist outgoing events with the **Transactional Outbox** pattern; deliver via a message bus.

-   Define **compensation commands** for each step.

-   Add **deadlines/timeouts** and **retry** policies per step.

-   Model an **internal FSM** for each saga instance (states + awaited events).

-   Provide **observability**: trace each step, decision, and compensation.


---

## Sample Code (Java 17) — Choreography-based Saga with Compensations

> A small, in-memory example (no frameworks) showing event choreography.  
> Flow: `OrderPlaced` → **Inventory** reserves → **Payments** charges → **Shipping** ships.  
> On failure: `PaymentFailed` → Inventory **releases**; `ShipmentFailed` → Payments **refunds** + Inventory **releases**.  
> Each service is **idempotent** per event id.

```java
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Consumer;

// ---------- Events (carry correlation: orderId; and eventId for idempotency) ----------
sealed interface Event permits OrderPlaced, StockReserved, StockReservationFailed, PaymentCaptured, PaymentFailed, ShipmentCreated, ShipmentFailed {
  String orderId();
  String eventId();
  Instant at();
}
record OrderPlaced(String orderId, List<String> skus, int amountCents, String eventId, Instant at) implements Event {}
record StockReserved(String orderId, String eventId, Instant at) implements Event {}
record StockReservationFailed(String orderId, String reason, String eventId, Instant at) implements Event {}
record PaymentCaptured(String orderId, String paymentId, String eventId, Instant at) implements Event {}
record PaymentFailed(String orderId, String reason, String eventId, Instant at) implements Event {}
record ShipmentCreated(String orderId, String tracking, String eventId, Instant at) implements Event {}
record ShipmentFailed(String orderId, String reason, String eventId, Instant at) implements Event {}

// ---------- Simple Event Bus (in-memory) ----------
interface EventBus {
  <T extends Event> void subscribe(Class<T> type, Consumer<T> handler);
  void publish(Event e);
}
final class SimpleEventBus implements EventBus {
  private final Map<Class<?>, List<Consumer<?>>> subs = new ConcurrentHashMap<>();
  @Override public synchronized <T extends Event> void subscribe(Class<T> type, Consumer<T> h) {
    subs.computeIfAbsent(type, k -> new ArrayList<>()).add(h);
  }
  @SuppressWarnings("unchecked")
  @Override public void publish(Event e) {
    subs.getOrDefault(e.getClass(), List.of()).forEach(h -> ((Consumer<Event>)h).accept(e));
  }
}

// ---------- Inventory Service (step + compensation) ----------
final class InventoryService {
  private final EventBus bus;
  private final Set<String> processed = ConcurrentHashMap.newKeySet(); // idempotency on eventId
  private final Set<String> reservedOrders = ConcurrentHashMap.newKeySet();

  InventoryService(EventBus bus) {
    this.bus = bus;
    bus.subscribe(OrderPlaced.class, this::on);
    bus.subscribe(ShipmentFailed.class, e -> release(e.orderId())); // compensation on shipment failure
    bus.subscribe(PaymentFailed.class, e -> release(e.orderId()));  // compensation on payment failure
  }

  private void on(OrderPlaced e) {
    if (!processed.add(e.eventId())) return; // dedupe
    // pretend success; you could fail based on stock levels
    reservedOrders.add(e.orderId());
    bus.publish(new StockReserved(e.orderId(), uuid(), Instant.now()));
    System.out.println("[Inventory] Reserved for " + e.orderId());
  }

  private void release(String orderId) {
    if (reservedOrders.remove(orderId)) {
      System.out.println("[Inventory] Released reservation for " + orderId);
    }
  }
}

// ---------- Payments Service (step + compensation) ----------
final class PaymentService {
  private final EventBus bus;
  private final Set<String> processed = ConcurrentHashMap.newKeySet();
  private final Map<String,String> payments = new ConcurrentHashMap<>(); // orderId -> paymentId

  PaymentService(EventBus bus) {
    this.bus = bus;
    bus.subscribe(StockReserved.class, this::on);
    bus.subscribe(ShipmentFailed.class, this::compensate); // refund on shipment failure
  }

  private void on(StockReserved e) {
    if (!processed.add(e.eventId())) return;
    // simulate success unless we decide to fail by rule (e.g., odd hash for demo)
    boolean ok = Math.abs(e.orderId().hashCode()) % 5 != 0; // sometimes fail
    if (ok) {
      String pid = "pay_" + Math.abs(e.orderId().hashCode());
      payments.put(e.orderId(), pid);
      bus.publish(new PaymentCaptured(e.orderId(), pid, uuid(), Instant.now()));
      System.out.println("[Payments] Captured for " + e.orderId() + " (" + pid + ")");
    } else {
      bus.publish(new PaymentFailed(e.orderId(), "card-declined", uuid(), Instant.now()));
      System.out.println("[Payments] FAILED for " + e.orderId());
    }
  }

  private void compensate(ShipmentFailed e) {
    String pid = payments.remove(e.orderId());
    if (pid != null) System.out.println("[Payments] Refund " + pid + " for " + e.orderId());
  }
}

// ---------- Shipping Service (final step) ----------
final class ShippingService {
  private final EventBus bus;
  private final Set<String> processed = ConcurrentHashMap.newKeySet();

  ShippingService(EventBus bus) {
    this.bus = bus;
    bus.subscribe(PaymentCaptured.class, this::on);
  }

  private void on(PaymentCaptured e) {
    if (!processed.add(e.eventId())) return;
    boolean ok = true; // set to false to demo failure
    if (ok) {
      bus.publish(new ShipmentCreated(e.orderId(), "trk_" + e.orderId().hashCode(), uuid(), Instant.now()));
      System.out.println("[Shipping] Shipped " + e.orderId());
    } else {
      bus.publish(new ShipmentFailed(e.orderId(), "wms-down", uuid(), Instant.now()));
      System.out.println("[Shipping] FAILED " + e.orderId());
    }
  }
}

// ---------- Read Model / Projections for observability ----------
final class OrderProjection {
  static final class View { String status="NEW"; String paymentId; String tracking; }
  private final Map<String, View> views = new ConcurrentHashMap<>();

  OrderProjection(EventBus bus) {
    bus.subscribe(OrderPlaced.class, e -> views.computeIfAbsent(e.orderId(), k -> new View()));
    bus.subscribe(StockReserved.class, e -> views.computeIfPresent(e.orderId(), (k,v)->{ v.status="RESERVED"; return v; }));
    bus.subscribe(PaymentCaptured.class, e -> views.computeIfPresent(e.orderId(), (k,v)->{ v.status="PAID"; v.paymentId=e.paymentId(); return v; }));
    bus.subscribe(ShipmentCreated.class, e -> views.computeIfPresent(e.orderId(), (k,v)->{ v.status="SHIPPED"; v.tracking=e.tracking(); return v; }));
    bus.subscribe(PaymentFailed.class, e -> views.computeIfPresent(e.orderId(), (k,v)->{ v.status="FAILED_PAYMENT"; return v; }));
    bus.subscribe(ShipmentFailed.class, e -> views.computeIfPresent(e.orderId(), (k,v)->{ v.status="FAILED_SHIPMENT"; return v; }));
  }
  Optional<View> get(String id) { return Optional.ofNullable(views.get(id)); }
}

// ---------- Demo ----------
public class SagaChoreographyDemo {
  public static void main(String[] args) throws Exception {
    var bus = new SimpleEventBus();
    new InventoryService(bus);
    new PaymentService(bus);
    new ShippingService(bus);
    var read = new OrderProjection(bus);

    // Start two sagas: one likely OK, one may fail payment (hash rule)
    String ok = "o-1001";
    String maybeFail = "o-1005"; // may hit the "fail" hash branch
    bus.publish(new OrderPlaced(ok, List.of("sku-1","sku-2"), 2599, uuid(), Instant.now()));
    bus.publish(new OrderPlaced(maybeFail, List.of("sku-3"), 1999, uuid(), Instant.now()));

    Thread.sleep(100); // let handlers run

    read.get(ok).ifPresent(v -> System.out.println("Order " + ok + " -> " + v.status + " tracking=" + v.tracking));
    read.get(maybeFail).ifPresent(v -> System.out.println("Order " + maybeFail + " -> " + v.status));
  }
}

// ---------- Helpers ----------
static String uuid() { return java.util.UUID.randomUUID().toString(); }
```

**What this shows**

-   **Choreography**: services subscribe to events and emit the next step’s event.

-   **Compensations**: Inventory releases on `PaymentFailed`/`ShipmentFailed`; Payments refunds on `ShipmentFailed`.

-   **Idempotency**: each service de-dupes by `eventId`.

-   **Correlation**: all events carry `orderId`.

-   Easy to switch to **orchestration** by introducing a central coordinator that listens to events and sends commands.


---

## Known Uses

-   E-commerce checkout, travel booking (reserve seats/rooms, charge, ticketing), loan origination, user onboarding.

-   Microservice platforms at scale (e.g., retail, fintech) where global transactions are infeasible.


---

## Related Patterns

-   **Process Manager / Orchestrator** — the *orchestration* form of Saga (central coordinator with state/timeouts).

-   **Transactional Outbox / CDC** — reliably publish events with local DB commits.

-   **Idempotency Key** — deduplicate retried commands/requests.

-   **Finite State Machine** — model a saga instance’s internal states explicitly.

-   **Circuit Breaker / Retry / Timeouts** — resilience of each step.

-   **Compensating Transaction** — the core semantic undo building block.
