# API Orchestration — Design Pattern

## Pattern Name and Classification

**API Orchestration** — *Process/Workflow coordination* pattern for microservices and distributed systems (command-side).

---

## Intent

Centralize **control flow** for a multi-step business process by using a dedicated **orchestrator** that invokes APIs of participating services in a defined order, handles **retries**, **timeouts**, and **compensations**, and maintains **process state**.

---

## Also Known As

-   **Process Manager**

-   **Workflow Orchestrator**

-   (When involving compensations) **Saga Orchestrator**


---

## Motivation (Forces)

-   A business transaction spans **multiple services** (e.g., Order → Payment → Inventory → Shipping).

-   Steps require **strict ordering**, **branching**, and **error handling**.

-   Need **observability and auditability** of process state.

-   Avoid pushing complex workflow logic into clients or each service (**choreography sprawl**).


Tensions:

-   Central control vs. autonomy of services

-   Robustness (retries/compensations) vs. simplicity

-   Avoiding the **“orchestrator monolith”** at the edge


---

## Applicability

Use when:

-   You must **coordinate** multiple APIs with **business rules** (if/else, loops, timeouts).

-   You need **compensating actions** for partial failures.

-   Stakeholders require **visibility** into transaction state and SLAs.


Avoid when:

-   Steps are loosely coupled, event-driven, and simple → prefer **choreography**.

-   Ultra-low-latency straight-through paths with minimal branching → direct calls may suffice.


---

## Structure

```rust
+--------------------+
Client->|  Orchestrator API  |---> calls --> [ Payment Service ]
        |  (Process Manager) |---> calls --> [ Inventory Service ]
        +--------------------+---> calls --> [ Shipping Service ]
                  |                     ^
                  v                     |
           [ State Store ] <--- emits events / audit logs
```

---

## Participants

-   **Client** – initiates the workflow (e.g., place order).

-   **Orchestrator** – coordinates steps, persists state, applies retries/timeouts, triggers compensations.

-   **Participant Services** – perform domain actions (charge, reserve, ship) and offer **idempotent** APIs.

-   **State/Audit Store** – persists saga/workflow instance, steps, results, errors, timestamps.

-   **Resilience Services** – circuit breaker, rate limiter, scheduler/timers.


---

## Collaboration

1.  Client calls `POST /orders/{id}/orchestrate`.

2.  Orchestrator records **state = STARTED**.

3.  Calls **Payment** → if ok, record; else retry/compensate/abort.

4.  Calls **Inventory** → if fail after retries, **compensate Payment** (refund).

5.  Calls **Shipping** → on success mark **COMPLETED**; on failure, compensate prior steps.

6.  Emits audit events and returns final status.


---

## Consequences

**Benefits**

-   **Clear control flow** and single place for policies (retries, timeouts, backoff).

-   **Observability** of long-running transactions.

-   Supports **compensation** and **idempotency** systematically.


**Liabilities**

-   Risk of a **central bottleneck** if it accumulates business logic.

-   Extra component to operate (state store, timers, DLQs).

-   Requires **careful versioning** of workflows and compensation semantics.


---

## Implementation (Key Points)

-   Make participants’ APIs **idempotent** (idempotency keys).

-   Use **timeouts + retries with jitter**, **circuit breakers**, **bulkheads**.

-   Persist **workflow state** after each step (transactional if possible).

-   Design **compensations** that semantically undo effects (refund, release stock).

-   Correlate requests with a **workflowId** and propagate trace headers.

-   Consider a durable engine (Temporal, Conductor, Step Functions, Camunda) for production.


---

## Sample Code (Java, Spring Boot; WebClient + Resilience4j; in-memory state for brevity)

> Orchestrates: **Payment → Inventory → Shipping** with compensations. In production, persist state in a DB and run the orchestrator as a durable worker.

**Gradle deps (snippets)**

```gradle
implementation "org.springframework.boot:spring-boot-starter-webflux"
implementation "io.github.resilience4j:resilience4j-spring-boot3"
implementation "com.fasterxml.jackson.core:jackson-databind"
```

**DTOs**

```java
record ChargeCmd(String orderId, int cents, String idempotencyKey) {}
record ChargeRes(String orderId, String paymentId, String status) {}
record ReserveCmd(String orderId, List<String> skus, String idempotencyKey) {}
record ReserveRes(String reservationId, String status) {}
record ShipCmd(String orderId, String address, String idempotencyKey) {}
record ShipRes(String shipmentId, String status) {}

enum Step { START, CHARGED, RESERVED, SHIPPED, COMPENSATED, FAILED, COMPLETED }
record OrchestrationState(String workflowId, String orderId, Step step, String note) {}
```

**Clients**

```java
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

@Component
class PaymentClient {
  private final WebClient http = WebClient.create("http://payments:8080");
  Mono<ChargeRes> charge(ChargeCmd cmd) {
    return http.post().uri("/payments/charge")
      .header("Idempotency-Key", cmd.idempotencyKey())
      .bodyValue(cmd).retrieve().bodyToMono(ChargeRes.class);
  }
  Mono<Void> refund(String paymentId, String reason) {
    return http.post().uri("/payments/{id}/refund?reason={r}", paymentId, reason)
      .retrieve().bodyToMono(Void.class);
  }
}

@Component
class InventoryClient {
  private final WebClient http = WebClient.create("http://inventory:8080");
  Mono<ReserveRes> reserve(ReserveCmd cmd) {
    return http.post().uri("/inventory/reservations")
      .header("Idempotency-Key", cmd.idempotencyKey())
      .bodyValue(cmd).retrieve().bodyToMono(ReserveRes.class);
  }
  Mono<Void> release(String reservationId) {
    return http.post().uri("/inventory/reservations/{id}/release", reservationId)
      .retrieve().bodyToMono(Void.class);
  }
}

@Component
class ShippingClient {
  private final WebClient http = WebClient.create("http://shipping:8080");
  Mono<ShipRes> ship(ShipCmd cmd) {
    return http.post().uri("/shipments")
      .header("Idempotency-Key", cmd.idempotencyKey())
      .bodyValue(cmd).retrieve().bodyToMono(ShipRes.class);
  }
  Mono<Void> cancel(String shipmentId) {
    return http.post().uri("/shipments/{id}/cancel", shipmentId)
      .retrieve().bodyToMono(Void.class);
  }
}
```

**In-Memory State Store (demo)**

```java
import org.springframework.stereotype.Repository;
import java.util.concurrent.ConcurrentHashMap;

@Repository
class StateStore {
  private final ConcurrentHashMap<String, OrchestrationState> db = new ConcurrentHashMap<>();
  OrchestrationState put(OrchestrationState s) { db.put(s.workflowId(), s); return s; }
  OrchestrationState get(String id) { return db.get(id); }
}
```

**Orchestrator Service**

```java
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import io.github.resilience4j.retry.annotation.Retry;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;
import java.util.List;
import java.util.UUID;

@Service
class OrderOrchestrator {

  private final PaymentClient payment;
  private final InventoryClient inventory;
  private final ShippingClient shipping;
  private final StateStore store;

  OrderOrchestrator(PaymentClient p, InventoryClient i, ShippingClient s, StateStore st) {
    this.payment = p; this.inventory = i; this.shipping = s; this.store = st;
  }

  @CircuitBreaker(name="orchestrator")
  @Retry(name="orchestrator") // backoff configured in application.yml
  public Mono<OrchestrationState> placeOrder(String orderId, int cents, List<String> skus, String address) {
    final String wf = UUID.randomUUID().toString();
    store.put(new OrchestrationState(wf, orderId, Step.START, "init"));

    final String key = wf; // reuse as idempotency key

    // 1) Charge
    return payment.charge(new ChargeCmd(orderId, cents, key)).flatMap(payRes -> {
      store.put(new OrchestrationState(wf, orderId, Step.CHARGED, payRes.paymentId()));
      // 2) Reserve
      return inventory.reserve(new ReserveCmd(orderId, skus, key)).flatMap(res -> {
        store.put(new OrchestrationState(wf, orderId, Step.RESERVED, res.reservationId()));
        // 3) Ship
        return shipping.ship(new ShipCmd(orderId, address, key)).map(shipRes -> {
          store.put(new OrchestrationState(wf, orderId, Step.SHIPPED, shipRes.shipmentId()));
          store.put(new OrchestrationState(wf, orderId, Step.COMPLETED, "ok"));
          return store.get(wf);
        });
      })
      // Compensation for reserve failure
      .onErrorResume(invErr -> payment.refund(store.get(wf).note(), "reserve-failed")
        .then(Mono.fromSupplier(() -> {
          store.put(new OrchestrationState(wf, orderId, Step.COMPENSATED, "refund after reserve fail"));
          store.put(new OrchestrationState(wf, orderId, Step.FAILED, invErr.getMessage()));
          return store.get(wf);
        })));
    })
    // Compensation for payment failure (nothing to undo)
    .onErrorResume(payErr -> Mono.fromSupplier(() -> {
      store.put(new OrchestrationState(wf, orderId, Step.FAILED, payErr.getMessage()));
      return store.get(wf);
    }));
  }

  // Cancel shipment compensation example (if ship succeeded but later step fails)
  public Mono<Void> compensateShipment(String shipmentId) { return shipping.cancel(shipmentId); }
}
```

**Controller**

```java
import org.springframework.web.bind.annotation.*;
import reactor.core.publisher.Mono;
import java.util.List;

@RestController
@RequestMapping("/orchestration")
class OrchestrationController {
  private final OrderOrchestrator orchestrator;

  OrchestrationController(OrderOrchestrator o) { this.orchestrator = o; }

  @PostMapping("/orders/{id}")
  Mono<OrchestrationState> place(@PathVariable String id,
                                 @RequestParam int cents,
                                 @RequestParam String address,
                                 @RequestBody List<String> skus) {
    return orchestrator.placeOrder(id, cents, skus, address);
  }

  @GetMapping("/state/{workflowId}")
  OrchestrationState get(@PathVariable String workflowId) {
    return orchestrator.stateStore().get(workflowId);
  }
}
```

**application.yml (resilience outline)**

```yaml
resilience4j:
  retry:
    instances:
      orchestrator:
        max-attempts: 3
        wait-duration: 200ms
        enable-exponential-backoff: true
        exponential-backoff-multiplier: 2
  circuitbreaker:
    instances:
      orchestrator:
        sliding-window-size: 50
        failure-rate-threshold: 50
        wait-duration-in-open-state: 10s
```

*Notes*:

-   Each downstream call uses an **Idempotency-Key** to allow safe retries.

-   Persist `OrchestrationState` in a database (e.g., Postgres) with an **outbox** to emit audit events.

-   Add **timeouts**, **bulkheads** (separate connection pools), and **DLQ** for async steps.


---

## Known Uses

-   **Temporal**, **Netflix Conductor**, **AWS Step Functions**, **Azure Durable Functions**, **Camunda**, **Zeebe** used as orchestrators for order fulfillment, payments, KYC onboarding, and ML pipelines.


---

## Related Patterns

-   **Saga** (orchestration vs. choreography variants)

-   **API Composition** (read-side aggregation; orchestration is usually command-side/business flow)

-   **Process Manager / Workflow Engine**

-   **Circuit Breaker, Retry, Timeout, Bulkhead** (resilience for fan-out calls)

-   **Transactional Outbox / CDC** (reliable state transitions and audit stream)

-   **BFF / API Gateway** (edge; may delegate to an internal orchestrator)
