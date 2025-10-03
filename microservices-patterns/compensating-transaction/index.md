# Compensating Transaction — Microservice Pattern

## Pattern Name and Classification

**Name:** Compensating Transaction  
**Classification:** Microservices / Distributed Consistency / Failure Recovery & Undo

## Intent

When a multi-step business operation spans multiple services and **atomic ACID** is impossible, complete each step **safely**, and if any later step fails, execute **compensating actions** to **undo or counteract** the already-completed steps so the system returns to a consistent business state.

## Also Known As

-   Semantic Undo
    
-   Business Rollback
    
-   Saga Compensation (the “C” in Saga)
    
-   TCC Cancel (Try–Confirm/Cancel variant)
    

## Motivation (Forces)

-   **No 2PC:** Microservices own their data; global XA is fragile or unavailable.
    
-   **Partial failure is normal:** A later step may timeout/fail after earlier steps succeeded.
    
-   **Business truth, not bytes:** “Undo” must respect domain rules (refund, release hold), not raw row deletes.
    
-   **User experience:** Prefer automated recovery over manual ops; if not possible, isolate and notify.
    
-   **Idempotency & retries:** Distributed systems deliver duplicates and reorder messages.
    

**Tensions**

-   **Irreversible side effects:** Emails sent, webhooks delivered, third-party posts—some actions can’t be truly undone.
    
-   **Time windows:** Compensation may need to occur within SLAs (e.g., void vs. refund windows for cards).
    
-   **Model drift:** Downstream contracts evolve; compensation must remain valid across versions.
    

## Applicability

Use **Compensating Transaction** when:

-   A business flow spans **3+ services** and must be **all-or-nothing at the business level**.
    
-   Steps are **individually committed**, but you can define valid inverse operations (release, refund, cancel).
    
-   You orchestrate a **Saga** or implement **TCC** semantics.
    

Avoid/limit when:

-   You can use a **single-aggregate transaction** instead.
    
-   “Undo” is impossible or legally restricted (e.g., cash withdrawal); prefer **human-in-the-loop** exception handling.
    

## Structure

-   **Coordinator (Orchestrator or Process Manager):** Drives the flow and decides when to compensate.
    
-   **Participants:** Services that perform forward actions and expose **compensation endpoints**.
    
-   **Compensation Log:** Durable record of completed steps and their compensating actions/ids (for crash recovery).
    
-   **Policies:** Idempotency keys, retry/backoff, timeouts, DLQ, and human escalation.
    

```rust
[Start] -> Step A -> Step B -> Step C (fails)
                 \        \
                  \        --> Compensation for B
                   --> Compensation for A
   (based on durable compensation log; reverse order)
```

## Participants

-   **Orchestrator / Saga Engine** — stores state, runs forward/compensation.
    
-   **Domain Services** — implement *business* operations and their compensations.
    
-   **Compensation Store** — DB table or event stream tracking progress.
    
-   **DLQ / Incident Queue** — unresolved compensations for manual handling.
    
-   **Observability** — metrics and audit of forward/compensate actions.
    

## Collaboration

1.  Orchestrator executes **Step₁…Stepₙ**, persisting each success to the **compensation log** with the matching **undo** action and idempotency key.
    
2.  If Stepₖ fails (or times out), the orchestrator reads the log and invokes compensations **in reverse order** for completed steps: Stepₖ₋₁, Stepₖ₋₂, …
    
3.  Each compensation is **idempotent** and retried with backoff; unrecoverable cases go to **DLQ**.
    
4.  The saga ends **COMPLETED** (all forward steps done) or **COMPENSATED** (all undone) or **NEEDS\_ATTENTION**.
    

## Consequences

**Benefits**

-   Business-level **consistency without XA**.
    
-   Clear audit of what happened and how it was undone.
    
-   Decouples services; each owns forward and inverse operations.
    

**Liabilities**

-   Requires carefully designed **inverse semantics**; some actions are only *mitigations* (refund vs. “un-charge”).
    
-   Complexity in **idempotency**, retries, and partial compensation.
    
-   Requires **governance**: every forward API must specify its compensating contract.
    

## Implementation

**Key practices**

-   **Design inverses:** Reserve ↔ Release, Create ↔ Cancel, Capture ↔ Refund/Void. Document SLAs and legal/financial nuances.
    
-   **Make it idempotent:** Both forward and compensate accept an **idempotency key**; dedupe by `(op, key)`.
    
-   **Persist first:** Write saga/compensation state *before* invoking remote side effects; or use an **outbox**.
    
-   **Reverse order, bounded retries:** Compensate back through completed steps with **exponential backoff + jitter**.
    
-   **Timeouts & deadlines:** Define when compensation becomes impossible (e.g., settlement). Fall back to manual.
    
-   **Isolation:** Use **bulkheads + circuit breakers** to avoid compensation storms.
    
-   **Observability:** Emit events for step completed/compensated; include correlation ids.
    

**TCC vs. Orchestrated Sagas**

-   **TCC:** `Try` reserves resources, `Confirm` commits, `Cancel` releases. Good for short windows.
    
-   **Orchestrated Saga:** Arbitrary steps with compensations; better for long-lived flows, branching, deadlines.
    

---

## Sample Code (Java, dependency-light)

A minimal **compensation engine** that executes steps, records them to a **durable log**, and on failure performs **reverse-order compensation**. It includes **idempotency**, **retry with backoff**, and **crash recovery** via `resume()`.

```java
import java.time.Duration;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Supplier;

// ====== Compensation Log (durable store) ======
enum StepStatus { PENDING, DONE, COMPENSATED }

final class StepRecord {
    final String sagaId; final String stepId; final String forwardKey; final String compensateKey;
    StepStatus status = StepStatus.PENDING;
    StepRecord(String sagaId, String stepId, String forwardKey, String compensateKey) {
        this.sagaId = sagaId; this.stepId = stepId; this.forwardKey = forwardKey; this.compensateKey = compensateKey;
    }
}

interface CompensationLog {
    void append(StepRecord rec);
    void markDone(String sagaId, String stepId);
    void markCompensated(String sagaId, String stepId);
    List<StepRecord> load(String sagaId);
}

// In-memory demo; swap with a DB table in production
final class InMemoryCompLog implements CompensationLog {
    private final Map<String, List<StepRecord>> map = new ConcurrentHashMap<>();
    public synchronized void append(StepRecord r){ map.computeIfAbsent(r.sagaId, k->new ArrayList<>()).add(r); }
    public synchronized void markDone(String s, String step){ find(s, step).status = StepStatus.DONE; }
    public synchronized void markCompensated(String s, String step){ find(s, step).status = StepStatus.COMPENSATED; }
    public synchronized List<StepRecord> load(String s){ return new ArrayList<>(map.getOrDefault(s, List.of())); }
    private StepRecord find(String s, String step){
        return map.get(s).stream().filter(r -> r.stepId.equals(step)).findFirst().orElseThrow();
    }
}

// ====== Compensation Engine ======
final class CompStep {
    final String stepId;
    final String forwardIdemKey;
    final String compensateIdemKey;
    final Runnable forward;      // should be idempotent based on forwardIdemKey
    final Runnable compensate;   // idempotent based on compensateIdemKey
    CompStep(String stepId, String fKey, String cKey, Runnable forward, Runnable compensate) {
        this.stepId = stepId; this.forwardIdemKey = fKey; this.compensateIdemKey = cKey;
        this.forward = forward; this.compensate = compensate;
    }
}

final class CompensationEngine {
    private final CompensationLog log;
    private final int maxRetries;
    private final Duration baseBackoff;

    CompensationEngine(CompensationLog log, int maxRetries, Duration baseBackoff) {
        this.log = log; this.maxRetries = maxRetries; this.baseBackoff = baseBackoff;
    }

    public void execute(String sagaId, List<CompStep> steps) {
        try {
            for (CompStep s : steps) {
                log.append(new StepRecord(sagaId, s.stepId, s.forwardIdemKey, s.compensateIdemKey));
                retry(s.forward, "forward:" + s.stepId);
                log.markDone(sagaId, s.stepId);
            }
        } catch (Exception ex) {
            // reverse compensate completed steps
            compensateAll(sagaId);
            throw new RuntimeException("Saga " + sagaId + " compensated due to: " + ex.getMessage(), ex);
        }
    }

    public void resume(String sagaId) {
        // If the process crashed mid-saga, finish compensation of DONE steps
        compensateAll(sagaId);
    }

    private void compensateAll(String sagaId) {
        List<StepRecord> recs = log.load(sagaId);
        ListIterator<StepRecord> it = recs.listIterator(recs.size());
        while (it.hasPrevious()) {
            StepRecord r = it.previous();
            if (r.status == StepStatus.DONE) {
                // lookup the step functions through some registry in real code; here we kept keys only
                // In this demo, we simulate with a noop; in real orchestrator, carry a map stepId->CompStep
            }
        }
        // In a real system, you'd supply the CompStep list again; here we expose another API:
    }

    // Execute forward/compensate with retries and backoff+jitter
    static void retry(Runnable op, String name) throws Exception {
        int attempts = 0;
        long sleep = 50;
        Random rnd = new Random();
        while (true) {
            try { op.run(); return; }
            catch (RuntimeException e) {
                attempts++;
                if (attempts > 5) throw e;
                Thread.sleep((long)(sleep * Math.pow(2, attempts-1) * (0.5 + rnd.nextDouble())));
            }
        }
    }
}
```

```java
// ====== Demo domain adapters (idempotent by key) ======
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

final class PaymentGateway {
    private final Set<String> captured = ConcurrentHashMap.newKeySet();
    private final Set<String> refunded = ConcurrentHashMap.newKeySet();

    void capture(String idemKey, String orderId, long cents){
        if (captured.add(idemKey)) {
            System.out.println("CAPTURE " + orderId + " = " + cents);
            // call PSP… might throw
        } else {
            System.out.println("CAPTURE (idem) " + orderId);
        }
    }
    void refund(String idemKey, String orderId, long cents){
        if (refunded.add(idemKey)) {
            System.out.println("REFUND " + orderId + " = " + cents);
        } else {
            System.out.println("REFUND (idem) " + orderId);
        }
    }
}

final class InventoryService {
    private final Set<String> reserved = ConcurrentHashMap.newKeySet();
    private final Set<String> released = ConcurrentHashMap.newKeySet();

    void reserve(String idemKey, String sku, int qty){
        if (reserved.add(idemKey)) {
            System.out.println("RESERVE " + sku + " x" + qty);
        }
    }
    void release(String idemKey, String sku, int qty){
        if (released.add(idemKey)) System.out.println("RELEASE " + sku + " x" + qty);
    }
}

final class ShippingService {
    private final Set<String> labels = ConcurrentHashMap.newKeySet();
    void createLabel(String idemKey, String orderId){
        if (labels.add(idemKey)) {
            System.out.println("CREATE LABEL " + orderId);
            // simulate failure to trigger compensation
            if (orderId.endsWith("FAIL")) throw new RuntimeException("Carrier error");
        }
    }
    void cancelLabel(String idemKey, String orderId){
        System.out.println("CANCEL LABEL " + orderId);
    }
}
```

```java
// ====== Wiring it together ======
import java.time.Duration;
import java.util.List;
import java.util.UUID;

public class Demo {
    public static void main(String[] args) {
        var log = new InMemoryCompLog();
        var engine = new CompensationEngine(log, 5, Duration.ofMillis(50));

        var payments = new PaymentGateway();
        var inventory = new InventoryService();
        var shipping = new ShippingService();

        String sagaId = UUID.randomUUID().toString();
        String orderId = "ORD-123-FAIL"; // end with FAIL to simulate a problem at shipping

        // Build steps with idempotency keys for forward/compensate
        var steps = List.of(
            new CompStep("reserve-inventory",
                "inv-res-" + orderId, "inv-rel-" + orderId,
                () -> inventory.reserve("inv-res-" + orderId, "SKU-1", 2),
                () -> inventory.release("inv-rel-" + orderId, "SKU-1", 2)),
            new CompStep("capture-payment",
                "pay-cap-" + orderId, "pay-ref-" + orderId,
                () -> payments.capture("pay-cap-" + orderId, orderId, 199_00),
                () -> payments.refund("pay-ref-" + orderId, orderId, 199_00)),
            new CompStep("create-shipping-label",
                "ship-mk-" + orderId, "ship-cancel-" + orderId,
                () -> shipping.createLabel("ship-mk-" + orderId, orderId),
                () -> shipping.cancelLabel("ship-cancel-" + orderId, orderId))
        );

        try {
            engine.execute(sagaId, steps);
            System.out.println("SAGA COMPLETED: " + sagaId);
        } catch (Exception e) {
            System.out.println("SAGA COMPENSATED: " + sagaId + " reason=" + e.getMessage());
            // If process crashed, we could call engine.resume(sagaId) to ensure compensations finish.
        }
    }
}
```

**What the demo illustrates**

-   Each forward step has a matching **compensation** and **idempotency key**.
    
-   A failure in the last step triggers **reverse-order** compensations (refund then release).
    
-   Swapping `InMemoryCompLog` with a DB gives crash recovery (call `resume(sagaId)`).
    
-   In real systems you’d also: persist **saga status**, expose **admin retry**, use **outbox**, and integrate **metrics/tracing**.
    

> Design compensations at the **domain level**: *release hold*, *cancel order*, *refund payment*. Avoid row deletes or hacks that violate invariants.

---

## Known Uses

-   **E-commerce checkout:** Reserve inventory → capture payment → create shipment; on failure, **refund** and **release**.
    
-   **Travel booking:** Reserve flight → hotel → car; any failure triggers **cancel reservations** already made.
    
-   **Banking:** Open account → KYC → fund; on KYC fail, **revert funding and close**.
    
-   **Telecom provisioning:** Allocate number → create subscriber → activate plan; on plan failure, **deallocate number**.
    

## Related Patterns

-   **Saga (Orchestration/Choreography):** The broader pattern coordinating forward & compensation.
    
-   **TCC (Try-Confirm/Cancel):** A specialization with explicit *try* reservations and *confirm/cancel*.
    
-   **Transactional Outbox:** Persist saga state and reliably publish step/compensation commands.
    
-   **Circuit Breaker / Bulkhead / Timeout / Retry:** Guardrails to prevent cascades during both forward and compensation.
    
-   **Dead Letter Queue (DLQ):** For irrecoverable compensations requiring manual action.
    
-   **Idempotent Receiver / Exactly-Once Effects:** Ensure compensations don’t double-apply.

