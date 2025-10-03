# Saga — Enterprise Integration Pattern

## Pattern Name and Classification

**Name:** Saga  
**Classification:** Long-running transaction / Process Coordination pattern (EIP); coordinates a sequence of distributed actions with **compensating** steps instead of a global ACID transaction.

## Intent

Maintain **overall consistency** across multiple services by splitting a business transaction into a series of **local transactions**. If any step fails or times out, previously completed steps are **compensated** in reverse order, restoring a consistent outcome.

## Also Known As

-   Long-Running Action (LRA)
    
-   Process Manager (orchestrated saga)
    
-   Choreographed Saga (event-chained saga)
    
-   Compensating Transaction
    

## Motivation (Forces)

-   **No distributed ACID:** Cross-service two-phase commit is brittle and harms availability/latency.
    
-   **Business invariants still matter:** E.g., “reserve inventory, charge payment, create shipment” must converge.
    
-   **Failures are normal:** partial failures, timeouts, retries, out-of-order events.
    
-   **Operational needs:** observability, retries with backoff, dedup/idempotency, human intervention windows.
    

**Tensions**

-   Orchestration (central brain) **vs.** choreography (peer-to-peer events).
    
-   **Compensation semantics** can be complex (true undo vs. semantic reversal).
    
-   Exactly-once **effects** are achieved via idempotency, not exactly-once delivery.
    

## Applicability

Use a Saga when:

-   A business workflow spans **multiple services/datastores** and cannot use a single ACID transaction.
    
-   Each step can be made **locally atomic** with a well-defined **compensating action**.
    
-   The process can tolerate **eventual consistency** (seconds/minutes).
    
-   You need **timeouts**, **retries**, and **manual resolution** hooks.
    

Avoid or limit when:

-   You truly need **atomic** all-or-nothing semantics within milliseconds (keep the boundary within one service/DB).
    
-   There’s **no sensible compensation** and the business requires strict isolation.
    

## Structure

```rust
Orchestrated Saga (central coordinator)
--------------------------------------
          +---------------------+
Events -->|  Saga Coordinator   |--Commands--> Service A (local tx)
          |  (state machine)    |--Commands--> Service B (local tx)
          +---------------------+--Commands--> Service C (local tx)
                   ^                   ^                ^
                   |                   |                |
               Events               Events           Events
                   |                   |                |
             +-----------+       +----------+     +-----------+
             |  Store    |<----->|  Bus     |<--->|  DLQ/Audit|

Choreographed Saga (event chain)
--------------------------------
Service A -(Event)-> Service B -(Event)-> Service C -(Event)-> (done/compensate)
```

## Participants

-   **Saga Coordinator / Process Manager (optional):** Drives steps, tracks state, decides compensation.
    
-   **Services (A/B/C…):** Execute **local transactions** and publish events.
    
-   **Compensating Handlers:** Undo/mitigate prior local effects.
    
-   **Message Bus/Channels:** Carry commands/events, retries, DLQ.
    
-   **Saga Store:** Persists saga instance state, steps, timeouts, correlation IDs.
    
-   **Timeout/Retry Policy:** Backoff, max attempts, circuit breaks.
    
-   **Operators/Human tasks (optional):** Manual resolution queue.
    

## Collaboration

1.  **Start:** A “saga started” trigger (command/event) creates a **saga instance** with a **correlationId**.
    
2.  **Step i:** Coordinator (or next service in choreography) issues command `DoStep_i`.
    
3.  **Acknowledge:** Service performs a **local ACID tx**, emits `Step_i_Succeeded` (or `Failed`).
    
4.  **Advance:** On success, proceed to `i+1`; on failure/timeout, the coordinator issues **compensation commands** `UndoStep_{i-1} ... UndoStep_1`.
    
5.  **Complete:** Mark saga `COMPLETED` or `COMPENSATED` (or `FAILED_REQUIRES_ATTENTION`).
    

## Consequences

**Benefits**

-   Achieves **consistency** without distributed locks/2PC.
    
-   Explicit **recovery paths** and observability for long-running workflows.
    
-   Localizes failure handling, idempotency, and retries per step.
    

**Liabilities**

-   **Complexity:** define compensations and state transitions; handle timeouts and races.
    
-   **Business semantics:** some effects aren’t perfectly reversible; compensation may be “semantic” (refund).
    
-   **Eventual consistency:** clients must tolerate temporary anomalies.
    
-   **Operational overhead:** saga store, DLQs, dashboards.
    

## Implementation

-   **Coordination style**
    
    -   **Orchestration:** single coordinator (service or state machine) commands services; simpler to reason about, centralizes policy.
        
    -   **Choreography:** services react to each other’s events; fewer central bottlenecks, risk of implicit flows and spaghetti events.
        
-   **State model**
    
    -   Per-saga record with `id`, `state`, `step`, `history`, `timeouts`, `attempts`, `context`.
        
    -   Persist before/after each transition (write-ahead to **saga store**).
        
-   **Reliability**
    
    -   **Transactional Outbox** for emitting commands/events from local transactions.
        
    -   **Idempotent Receiver** for all consumers (dedup by `messageId`/`sagaId#step`).
        
    -   Use **correlationId** + **causationId** headers and propagate `traceparent`.
        
-   **Compensation**
    
    -   Define **deterministic** compensations (reserve→release, charge→refund, ship→cancel shipment).
        
    -   If true undo is impossible, publish **corrective** events and reconcile externally.
        
-   **Timeouts**
    
    -   Per step: if `Step_i_Succeeded` not observed within `T`, either retry `DoStep_i` or compensate.
        
    -   Use **scheduler** or **time-wheel**; store next wake-up time in the saga record.
        
-   **Observability**
    
    -   Metrics: active sagas, step latencies, compensations, timeouts, DLQ counts.
        
    -   Audit: append-only saga history; redaction policies for PII.
        

---

## Sample Code (Java)

Below is a minimal **orchestrated saga** using Spring (JPA + Kafka), showing: coordinator, saga store, commands/events, idempotency, compensation. Replace Kafka with your transport of choice.

### 1) Messages & Headers

```java
public record Headers(String sagaId, String correlationId, String causationId, String type, String version) {}

public record CreateOrderCommand(String orderId, int qty, String sku, Headers h) {}
public record ReserveInventoryCommand(String orderId, int qty, String sku, Headers h) {}
public record ChargePaymentCommand(String orderId, String paymentRef, Headers h) {}
public record CreateShipmentCommand(String orderId, Headers h) {}

public record InventoryReserved(String orderId, Headers h) {}
public record InventoryDenied(String orderId, String reason, Headers h) {}
public record PaymentCharged(String orderId, String authCode, Headers h) {}
public record PaymentFailed(String orderId, String reason, Headers h) {}
public record ShipmentCreated(String orderId, String tracking, Headers h) {}

// Compensations
public record ReleaseInventoryCommand(String orderId, Headers h) {}
public record RefundPaymentCommand(String orderId, Headers h) {}
```

### 2) Saga Store (JPA)

```java
import jakarta.persistence.*;
import java.time.Instant;

@Entity
@Table(name = "saga_order",
  indexes = {@Index(name="ix_saga_id", columnList="sagaId", unique=true)})
public class OrderSagaEntity {
  @Id @GeneratedValue Long id;
  @Column(nullable=false, length=40) String sagaId;
  @Column(nullable=false, length=20) String state; // NEW, INV_RESERVED, PAID, SHIPPED, COMPENSATING, COMPLETED, FAILED
  @Column(nullable=false) Instant updatedAt = Instant.now();
  @Column(length=40) String orderId;
  @Column(length=2000) String historyJson; // append-only; or separate table
  @Column(length=40) String lastMessageId;
}

public interface OrderSagaRepo extends org.springframework.data.jpa.repository.JpaRepository<OrderSagaEntity, Long> {
  java.util.Optional<OrderSagaEntity> findBySagaId(String sagaId);
}
```

### 3) Coordinator (Process Manager)

```java
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.messaging.handler.annotation.Header;
import org.springframework.stereotype.Component;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Instant;
import java.util.UUID;

@Component
public class OrderSagaCoordinator {

  private final OrderSagaRepo repo;
  private final KafkaTemplate<String, byte[]> kafka;
  private final ObjectMapper json = new ObjectMapper();

  public OrderSagaCoordinator(OrderSagaRepo repo, KafkaTemplate<String, byte[]> kafka) {
    this.repo = repo; this.kafka = kafka;
  }

  // Start saga
  public String start(String orderId, int qty, String sku) {
    String sagaId = UUID.randomUUID().toString();
    var e = new OrderSagaEntity();
    e.sagaId = sagaId; e.orderId = orderId; e.state = "NEW";
    repo.save(e);
    send("inventory.reserve.cmd", orderId, new ReserveInventoryCommand(orderId, qty, sku, hdr(sagaId, "ReserveInventoryCommand")));
    return sagaId;
  }

  // Handle InventoryReserved
  @KafkaListener(topics = "inventory.reserved.evt", groupId = "saga-coord")
  public void onInventoryReserved(byte[] bytes, @Header("sagaId") String sagaId) throws Exception {
    var e = mustLoad(sagaId);
    if (!advance(e, "INV_RESERVED", "InventoryReserved", bytes)) return;
    send("payment.charge.cmd", e.orderId, new ChargePaymentCommand(e.orderId, "CARD", hdr(sagaId, "ChargePaymentCommand")));
  }

  // Handle InventoryDenied => compensate and fail
  @KafkaListener(topics = "inventory.denied.evt", groupId = "saga-coord")
  public void onInventoryDenied(byte[] bytes, @Header("sagaId") String sagaId) throws Exception {
    var e = mustLoad(sagaId);
    if (!advance(e, "FAILED", "InventoryDenied", bytes)) return;
    // nothing to compensate (we failed at first step)
  }

  // Handle PaymentCharged
  @KafkaListener(topics = "payment.charged.evt", groupId = "saga-coord")
  public void onPaymentCharged(byte[] bytes, @Header("sagaId") String sagaId) throws Exception {
    var e = mustLoad(sagaId);
    if (!advance(e, "PAID", "PaymentCharged", bytes)) return;
    send("shipping.create.cmd", e.orderId, new CreateShipmentCommand(e.orderId, hdr(sagaId, "CreateShipmentCommand")));
  }

  // Handle PaymentFailed => compensate inventory
  @KafkaListener(topics = "payment.failed.evt", groupId = "saga-coord")
  public void onPaymentFailed(byte[] bytes, @Header("sagaId") String sagaId) throws Exception {
    var e = mustLoad(sagaId);
    if (!advance(e, "COMPENSATING", "PaymentFailed", bytes)) return;
    send("inventory.release.cmd", e.orderId, new ReleaseInventoryCommand(e.orderId, hdr(sagaId, "ReleaseInventoryCommand")));
    e.state = "FAILED"; e.updatedAt = Instant.now(); repo.save(e);
  }

  // Handle ShipmentCreated => done
  @KafkaListener(topics = "shipping.created.evt", groupId = "saga-coord")
  public void onShipmentCreated(byte[] bytes, @Header("sagaId") String sagaId) {
    var e = mustLoad(sagaId);
    if (!advance(e, "SHIPPED", "ShipmentCreated", bytes)) return;
    e.state = "COMPLETED"; e.updatedAt = Instant.now(); repo.save(e);
  }

  // Compensation acknowledgements (e.g., InventoryReleased) could be handled similarly

  // --- Helpers ---

  private Headers hdr(String sagaId, String type) {
    String corr = sagaId;
    return new Headers(sagaId, corr, corr, type, "v1");
  }

  private OrderSagaEntity mustLoad(String sagaId) {
    return repo.findBySagaId(sagaId).orElseThrow(() -> new IllegalStateException("saga not found " + sagaId));
  }

  // Idempotent advance; lastMessageId can hold a messageId/correlation to skip duplicates
  private boolean advance(OrderSagaEntity e, String newState, String label, byte[] bytes) {
    // parse headers if you carry messageId; omitted for brevity
    e.state = newState; e.updatedAt = Instant.now();
    e.historyJson = appendHistory(e.historyJson, label);
    repo.save(e);
    return true;
  }

  private void send(String topic, String key, Object payload) {
    try {
      byte[] bytes = json.writeValueAsBytes(payload);
      var rec = new org.apache.kafka.clients.producer.ProducerRecord<String, byte[]>(topic, key, bytes);
      // propagate saga headers (at least sagaId/correlationId)
      rec.headers().add("sagaId", payload.getClass().getMethod("h").invoke(payload).toString().getBytes());
      kafka.send(rec);
    } catch (Exception ex) {
      throw new RuntimeException(ex);
    }
  }

  private String appendHistory(String h, String ev) {
    String entry = Instant.now() + " " + ev;
    return (h == null || h.isBlank()) ? entry : h + " | " + entry;
    }
}
```

### 4) Example Step Service (Inventory) — Local TX + Outbox

```java
@Service
public class InventoryService {
  private final EntityManager em;
  private final OutboxPublisher outbox; // reads DB table and publishes to Kafka

  @Transactional
  public void reserve(ReserveInventoryCommand cmd) {
    // local ACID reservation (throw if insufficient)
    var stock = em.find(Stock.class, cmd.sku());
    if (stock.getAvailable() < cmd.qty()) {
      outbox.stage("inventory.denied.evt", cmd.h().sagaId(), new InventoryDenied(cmd.orderId(), "INSUFFICIENT", cmd.h()));
      return;
    }
    stock.reserve(cmd.qty());
    em.persist(stock);
    outbox.stage("inventory.reserved.evt", cmd.h().sagaId(), new InventoryReserved(cmd.orderId(), cmd.h()));
  }

  @Transactional
  public void release(ReleaseInventoryCommand cmd) {
    var stock = em.find(Stock.class, /* sku known via order map */ cmd.orderId());
    stock.release(/* qty */);
    outbox.stage("inventory.released.evt", cmd.h().sagaId(), /* your event */ null);
  }
}
```

> The **OutboxPublisher** writes an outbox row in the same DB transaction and a background job publishes to Kafka, ensuring “saved then sent” with exactly-once **effects**.

### 5) Lightweight Choreography Example (no central coordinator)

```java
// Order service publishes OrderCreated -> Inventory service reserves and publishes InventoryReserved
// Payment service listens for InventoryReserved -> charge -> PaymentCharged or PaymentFailed
// Shipping listens for PaymentCharged -> create shipment -> ShipmentCreated
// Compensation: on PaymentFailed, Inventory service listens and performs ReleaseInventory
```

---

## Known Uses

-   **E-commerce checkout:** reserve inventory → charge payment → create shipment; compensate on payment failure.
    
-   **Travel booking:** hold seat/room → take payment → issue ticket; release holds or refund on failure.
    
-   **Financial ops:** multi-leg transfers and settlements with reversal events.
    
-   **Telecom provisioning:** allocate number → configure network → activate plan; rollback steps on error.
    

## Related Patterns

-   **Process Manager / Orchestration vs. Choreography:** Two coordination styles of sagas.
    
-   **Compensating Transaction:** The core technique for undo/mitigation.
    
-   **Transactional Outbox & Inbox:** Reliable message publication/consumption for saga steps.
    
-   **Idempotent Receiver:** Exactly-once **effects** for commands/events and compensations.
    
-   **Correlation Identifier / Message Store:** Track saga instances and history.
    
-   **Timeout / Dead Letter Channel / Retry:** Failure handling and operator escalation.
    
-   **Message Router / Splitter / Aggregator:** Often used around sagas for routing and assembling step data.

