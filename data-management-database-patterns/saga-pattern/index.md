# Data Management & Database Pattern — Saga

## Pattern Name and Classification

-   **Name:** Saga

-   **Classification:** Distributed data consistency & workflow pattern (long-lived, multi-step transactions coordinated via **local transactions + compensations**)


## Intent

Coordinate a **business transaction spanning multiple services/datastores** without a global ACID transaction. Model the process as a **sequence of steps** (each a **local, atomic transaction**) with **compensating actions** to undo prior steps if later ones fail.

## Also Known As

-   Compensating Transaction

-   Process Manager (orchestration flavor)

-   Choreographed Workflow (event-driven flavor)


## Motivation (Forces)

-   **No global XA/2PC:** Microservices often own their own databases; distributed ACID is costly/unavailable.

-   **Business reality:** Many workflows are **long-running** (seconds to days) and cross multiple bounded contexts.

-   **Failure is normal:** Any step may fail or time out; you must **retry**, **compensate**, or **escalate**.

-   **Observability & audit:** Need to track progress, decisions, and compensations for support/regulatory reasons.


Trade-offs:

-   **Eventual consistency** replaces instantaneous atomicity.

-   You must design **compensations** and handle **out-of-order / duplicate** messages.


## Applicability

Use Sagas when:

-   A transaction spans **multiple services** each with its **own datastore**.

-   You can tolerate **eventual consistency** for the overall outcome.

-   Each step can be **compensated** (or you can design alternative “forward recovery” paths).


Avoid / adapt when:

-   You truly need **strong atomicity** across resources → consider 2PC/XA (still rare in microservices).

-   Compensations are **impossible** or legally/financially unacceptable.

-   The workflow is very simple or contained → a single service & local transaction suffices.


## Structure

```pgsql
ORCHESTRATED SAGA
+-------------+        cmd/reply         +-----------+   local tx   +-----------+
| Orchestrator| ─────────────────────────►| Service A |──────────────►| DB_A      |
| (state mngr)| ◄─────────reply────────── | (Reserve) |              +-----------+
+-------------+                            +-----------+
       │                                         │
       ├──────── cmd/reply ──────────────────────┤
       ▼                                         ▼
+-----------+   local tx   +-----------+   local tx   +-----------+
| Service B |──────────────►| DB_B      |──────────────►| Service C |
| (Pay)     |               +-----------+               | (Ship)    |
+-----------+                                         +-----------+
       ▲                                                  │
       └──── on failure: issue compensations ─────────────┘

CHOREOGRAPHED SAGA
Services emit/consume domain events; no central orchestrator.
```

## Participants

-   **Saga Instance:** The running workflow with **correlation ID**, **state**, and **step pointer**.

-   **Steps:** Each step executes a **local transaction** in a service.

-   **Compensations:** Inverse actions that semantically undo steps (not always perfect inversion).

-   **Orchestrator (optional):** Drives the saga via commands and awaits replies/timeouts.

-   **Event Bus / Messages:** Transport for commands, replies, and domain events.

-   **Saga Log/Store:** Durable record of saga state and decisions (for recovery & idempotency).


## Collaboration

1.  A client starts a saga (e.g., **PlaceOrder**).

2.  Saga executes **Step 1** (Reserve inventory). On success, proceed; on failure, **complete with failure**.

3.  Saga executes **Step 2** (Authorize payment). If it fails, **compensate Step 1** (Release inventory).

4.  Saga executes **Step 3** (Create shipment). If it fails, compensate Steps 2 then 1.

5.  Saga **completes** with success or failure; emit outcome events.


**Orchestration** centralizes the logic; **choreography** distributes it via events and local policies.

## Consequences

**Benefits**

-   Works with **service-local transactions**; no distributed locks.

-   **Resilient** to partial failures with well-defined compensations.

-   Clear, auditable **process state** and transitions.


**Liabilities**

-   **Complexity**: must design compensations, retries, and timeouts.

-   **Not truly atomic**: compensations may be approximate (refunds, reversal events).

-   **Operational discipline**: idempotency, deduplication, and recovery are mandatory.


## Implementation (Key Points)

-   **Idempotency:** All commands/compensations must be safe to **retry** (use request IDs and **upsert** semantics).

-   **Durable saga log:** Persist **state & last completed step** before sending each next command.

-   **Timeouts & retries:** Backoff + jitter; circuit-break to avoid cascading failures.

-   **Compensation order:** Reverse of execution order (**LIFO**).

-   **Message delivery:** Assume **at-least-once**; consumers must de-duplicate (store processed IDs).

-   **Orchestration vs. Choreography:**

    -   Orchestration = centralized clarity, simpler testing.

    -   Choreography = decentralized, less coupling; can drift into “event spaghetti” if not well designed.

-   **Observability:** Correlation IDs in logs/traces; metrics on step latencies, retries, compensation counts.


---

## Sample Code (Java 17): Lightweight Orchestrated Saga with Compensations & Idempotency

> Single-file demo.
>
> -   **OrderSagaOrchestrator** drives three steps: **reserve inventory → authorize payment → create shipment**
>
> -   Each service performs a **local transaction** into its private store (maps) and supports **compensation**
>
> -   Includes **idempotency keys**, **retry with backoff**, and **durable saga log** (in-memory for brevity)
>

```java
// File: SagaDemo.java
// Compile: javac SagaDemo.java
// Run:     java SagaDemo
import java.time.Duration;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/* === Messages & DTOs === */
record Command(String sagaId, String requestId, Map<String, Object> payload) {}
record Reply(boolean success, String message, Map<String, Object> payload) {}

enum SagaStatus { RUNNING, COMPLETED, FAILED }

/* === Saga Log (durable store; here in-memory) === */
final class SagaLog {
  static final class Entry {
    final String sagaId; final int step; final String name; final boolean done; final boolean compensated;
    Entry(String sagaId, int step, String name, boolean done, boolean compensated) {
      this.sagaId = sagaId; this.step = step; this.name = name; this.done = done; this.compensated = compensated;
    }
  }
  private final Map<String, List<Entry>> log = new ConcurrentHashMap<>();
  private final Map<String, SagaStatus> status = new ConcurrentHashMap<>();
  void init(String sagaId){ log.putIfAbsent(sagaId, new ArrayList<>()); status.put(sagaId, SagaStatus.RUNNING); }
  void recordDone(String sagaId, int step, String name){ log.get(sagaId).add(new Entry(sagaId, step, name, true, false)); }
  void recordCompensated(String sagaId, int step, String name){ log.get(sagaId).add(new Entry(sagaId, step, name, false, true)); }
  void setStatus(String sagaId, SagaStatus s){ status.put(sagaId, s); }
  SagaStatus getStatus(String sagaId){ return status.getOrDefault(sagaId, SagaStatus.RUNNING); }
  List<Entry> entries(String sagaId){ return log.getOrDefault(sagaId, List.of()); }
}

/* === Step interface === */
interface SagaStep {
  String name();
  Reply perform(Command c) throws Exception;
  Reply compensate(Command c) throws Exception; // inverse action
}

/* === Services (local transactions + idempotency) === */
final class InventoryService {
  private final Map<String, Integer> stock = new ConcurrentHashMap<>(Map.of("SKU-1", 5, "SKU-2", 1));
  private final Set<String> processed = ConcurrentHashMap.newKeySet(); // idempotency
  Reply reserve(String reqId, String sku, int qty) {
    if (!processed.add("reserve:"+reqId)) return new Reply(true, "dup", Map.of());
    int have = stock.getOrDefault(sku, 0);
    if (have < qty) return new Reply(false, "insufficient stock", Map.of("available", have));
    stock.put(sku, have - qty);
    return new Reply(true, "reserved", Map.of());
  }
  Reply release(String reqId, String sku, int qty) {
    if (!processed.add("release:"+reqId)) return new Reply(true, "dup", Map.of());
    stock.merge(sku, qty, Integer::sum);
    return new Reply(true, "released", Map.of());
  }
}

final class PaymentService {
  private final Map<String, Integer> holds = new ConcurrentHashMap<>();
  private final Set<String> processed = ConcurrentHashMap.newKeySet();
  Reply authorize(String reqId, String userId, int cents) {
    if (!processed.add("auth:"+reqId)) return new Reply(true, "dup", Map.of());
    if (cents > 20_000) return new Reply(false, "limit exceeded", Map.of()); // simulate failure
    holds.put(reqId, cents);
    return new Reply(true, "authorized", Map.of("authId", reqId));
  }
  Reply capture(String reqId) {
    if (!processed.add("cap:"+reqId)) return new Reply(true, "dup", Map.of());
    holds.remove(reqId);
    return new Reply(true, "captured", Map.of());
  }
  Reply reverse(String reqId) {
    if (!processed.add("rev:"+reqId)) return new Reply(true, "dup", Map.of());
    holds.remove(reqId);
    return new Reply(true, "reversed", Map.of());
  }
}

final class ShippingService {
  private final Map<String, String> shipments = new ConcurrentHashMap<>();
  private final Set<String> processed = ConcurrentHashMap.newKeySet();
  Reply create(String reqId, String orderId, String sku, int qty, String address) {
    if (!processed.add("ship:"+reqId)) return new Reply(true, "dup", Map.of("shipmentId", shipments.get(reqId)));
    if (address == null || address.isBlank()) return new Reply(false, "no address", Map.of());
    String shipmentId = "SHP-" + orderId;
    shipments.put(reqId, shipmentId);
    return new Reply(true, "created", Map.of("shipmentId", shipmentId));
  }
  Reply cancel(String reqId) {
    if (!processed.add("cancel:"+reqId)) return new Reply(true, "dup", Map.of());
    shipments.remove(reqId);
    return new Reply(true, "cancelled", Map.of());
  }
}

/* === Concrete Saga Steps (reserve → authorize → ship) === */
final class ReserveInventoryStep implements SagaStep {
  private final InventoryService inv;
  ReserveInventoryStep(InventoryService inv){ this.inv = inv; }
  public String name(){ return "ReserveInventory"; }
  public Reply perform(Command c) { return inv.reserve(c.requestId(), (String)c.payload().get("sku"), (int)c.payload().get("qty")); }
  public Reply compensate(Command c) { return inv.release(c.requestId(), (String)c.payload().get("sku"), (int)c.payload().get("qty")); }
}
final class AuthorizePaymentStep implements SagaStep {
  private final PaymentService pay;
  AuthorizePaymentStep(PaymentService pay){ this.pay = pay; }
  public String name(){ return "AuthorizePayment"; }
  public Reply perform(Command c) { return pay.authorize(c.requestId(), (String)c.payload().get("userId"), (int)c.payload().get("amountCents")); }
  public Reply compensate(Command c) { return pay.reverse(c.requestId()); }
}
final class CreateShipmentStep implements SagaStep {
  private final ShippingService ship;
  CreateShipmentStep(ShippingService ship){ this.ship = ship; }
  public String name(){ return "CreateShipment"; }
  public Reply perform(Command c) {
    return ship.create(c.requestId(), (String)c.payload().get("orderId"), (String)c.payload().get("sku"),
                       (int)c.payload().get("qty"), (String)c.payload().get("address"));
  }
  public Reply compensate(Command c) { return ship.cancel(c.requestId()); }
}

/* === Orchestrator with retry + backoff and compensation === */
final class OrderSagaOrchestrator {
  private final List<SagaStep> steps;
  private final SagaLog log;
  private final int maxRetries;
  private final Duration baseBackoff;

  OrderSagaOrchestrator(List<SagaStep> steps, SagaLog log, int maxRetries, Duration baseBackoff) {
    this.steps = steps; this.log = log; this.maxRetries = maxRetries; this.baseBackoff = baseBackoff;
  }

  public SagaStatus run(String sagaId, Map<String,Object> data) {
    log.init(sagaId);
    try {
      for (int i = 0; i < steps.size(); i++) {
        SagaStep step = steps.get(i);
        String reqId = sagaId + ":" + step.name(); // idempotency per step
        Command cmd = new Command(sagaId, reqId, data);

        boolean ok = attempt(() -> step.perform(cmd), step.name());
        if (!ok) {
          // compensate prior successful steps in reverse order
          for (int j = i - 1; j >= 0; j--) {
            SagaStep s = steps.get(j);
            String r = sagaId + ":" + s.name();
            attempt(() -> s.compensate(new Command(sagaId, r, data)), "Compensate(" + s.name() + ")");
            log.recordCompensated(sagaId, j, s.name());
          }
          log.setStatus(sagaId, SagaStatus.FAILED);
          return SagaStatus.FAILED;
        }
        log.recordDone(sagaId, i, step.name());
      }
      log.setStatus(sagaId, SagaStatus.COMPLETED);
      return SagaStatus.COMPLETED;
    } catch (Exception e) {
      log.setStatus(sagaId, SagaStatus.FAILED);
      return SagaStatus.FAILED;
    }
  }

  private boolean attempt(SupplierWithException<Reply> call, String label) {
    int tries = 0;
    while (true) {
      tries++;
      try {
        Reply r = call.get();
        if (r.success()) return true;
        System.out.println(label + " failed: " + r.message());
      } catch (Exception ex) {
        System.out.println(label + " error: " + ex.getMessage());
      }
      if (tries > maxRetries) return false;
      sleepWithJitter(tries);
    }
  }

  private void sleepWithJitter(int attempt) {
    long backoff = (long)(baseBackoff.toMillis() * Math.pow(2, attempt - 1));
    long jitter = new Random().nextLong(backoff / 2 + 1);
    try { Thread.sleep(Math.min(3000, backoff + jitter)); } catch (InterruptedException ignored) {}
  }

  interface SupplierWithException<T> { T get() throws Exception; }
}

/* === Demo === */
public class SagaDemo {
  public static void main(String[] args) {
    InventoryService inv = new InventoryService();
    PaymentService pay = new PaymentService();
    ShippingService ship = new ShippingService();

    List<SagaStep> steps = List.of(
        new ReserveInventoryStep(inv),
        new AuthorizePaymentStep(pay),
        new CreateShipmentStep(ship)
    );

    SagaLog log = new SagaLog();
    OrderSagaOrchestrator orch = new OrderSagaOrchestrator(steps, log, 3, Duration.ofMillis(100));

    Map<String,Object> dataOk = new HashMap<>();
    dataOk.put("orderId","ORD-1"); dataOk.put("userId","U-1");
    dataOk.put("sku","SKU-1"); dataOk.put("qty",2);
    dataOk.put("amountCents", 1299 * 2);
    dataOk.put("address","Main St 1, Vienna");

    Map<String,Object> dataFailPay = new HashMap<>(dataOk);
    dataFailPay.put("orderId","ORD-2");
    dataFailPay.put("amountCents", 50_000); // will exceed limit -> triggers compensation

    runSaga("saga-OK", orch, log, dataOk);
    runSaga("saga-FailPayment", orch, log, dataFailPay);
  }

  static void runSaga(String sagaId, OrderSagaOrchestrator orch, SagaLog log, Map<String,Object> data) {
    System.out.println("\n=== Start " + sagaId + " @ " + Instant.now() + " ===");
    SagaStatus st = orch.run(sagaId, data);
    System.out.println("Result: " + st);
    for (SagaLog.Entry e : log.entries(sagaId)) {
      System.out.printf(" - step=%d name=%s done=%s compensated=%s%n", e.step, e.name, e.done, e.compensated);
    }
  }
}
```

**What to notice**

-   **Idempotency:** Each step/compensation uses a **deterministic `requestId`** derived from the saga ID + step name.

-   **Retry with backoff + jitter** for transient failures.

-   **Compensation order** is **reverse** of the success path.

-   **Durable state** (here in memory) records completed and compensated steps; in production, persist it (DB, event store).


---

## Known Uses

-   **E-commerce checkout:** reserve stock → authorize/capture payment → create shipment; compensations: release, refund/reverse, cancel shipment.

-   **Travel booking:** reserve seat → book hotel → charge card; if hotel fails, release seat and cancel payment hold.

-   **Onboarding/KYC:** create account → verify identity → allocate limits; compensations revoke or roll back resource allocations.

-   **Telecom provisioning:** allocate number → configure network → activate SIM; compensations de-provision resources.


## Related Patterns

-   **Outbox / Transactional Messaging:** Guarantees reliable publication of saga commands/events.

-   **CQRS & Event Sourcing:** Persist saga state as events; rebuild and audit easily.

-   **TCC (Try-Confirm/Cancel):** A saga style where each service exposes reservation/confirm/cancel APIs.

-   **Read Replica / Database per Service:** Typical environment where Sagas run (no shared DB).

-   **Circuit Breaker / Retry with Backoff:** Protects steps from cascading failures.


---

### Practical Tips

-   Start with **orchestration** if the flow is complex or has many conditions; graduate to **choreography** where coupling must be minimized.

-   Define **clear compensations**—sometimes business-correct is to **add another event** (e.g., refund) rather than literal rollback.

-   Store **saga state** durably (status, step pointer, payload, timestamps). Use a **separate table/topic** per saga type.

-   Use **correlation IDs** everywhere; emit metrics for **step latency**, **retry counts**, **compensation rates**.

-   Make steps **idempotent** and **commutative** where possible; de-duplicate with **request IDs**.

-   Protect downstreams with **timeouts**, **retry policies**, and **circuit breakers**; design for **partial availability**.

-   Document **SLAs** for eventual consistency and user-visible states (e.g., “order pending payment”).
