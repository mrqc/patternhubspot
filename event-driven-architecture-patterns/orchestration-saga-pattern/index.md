# Orchestration Saga — Event-Driven Architecture Pattern

## Pattern Name and Classification

**Name:** Orchestration Saga  
**Classification:** Event-Driven Architecture (EDA) / Distributed Transaction & Process Manager / DDD Tactical Pattern

## Intent

Coordinate a **long-lived, multi-step business transaction** across multiple services by using a **central orchestrator** that issues commands, awaits events, and triggers **compensating actions** on failure—achieving consistency without two-phase commit.

## Also Known As

-   Process Manager
    
-   Saga Orchestrator
    
-   Command/Reaction Workflow
    
-   Distributed Transaction Coordinator (logical—not XA/2PC)
    

## Motivation (Forces)

-   **Service autonomy vs. consistency:** Each service owns its data; global ACID is unavailable.
    
-   **Partial failures & time:** Steps span networks and time (seconds/minutes); any step may fail or time out.
    
-   **Business correctness:** Must either complete all steps or roll back effects via **compensation**.
    
-   **Observability & control:** Operators need visibility into saga status and the ability to retry/cancel.
    
-   **Idempotency:** Messages can duplicate; compensations may run more than once.
    
-   **Scalability:** Orchestrations should be stateless between steps except for persisted saga state.
    

## Applicability

Use **Orchestration Saga** when:

-   A business process touches **3+ services** (e.g., Order, Payment, Inventory, Shipping).
    
-   You need **deterministic flows** with branching, deadlines, and compensations.
    
-   Business rules are centralized and must evolve without changing all participants.
    

Prefer **Choreography** when:

-   The flow is simple, few steps, and natural event fan-out suffices.
    
-   You want maximum decoupling and each service already emits rich domain events.
    

## Structure

-   **Orchestrator (Process Manager):** Stateful controller that decides **what command to send next** based on the saga state and incoming events.
    
-   **Participants (Services):** Execute commands and emit **domain events** (success/failure).
    
-   **Saga State Store:** Durable state of each saga instance (status, step, context, timers).
    
-   **Outbox / Inbox:** Reliable message publication & idempotent consumption.
    
-   **Compensation Handlers:** Undo or counteract previously completed steps.
    

*Textual diagram*

```pgsql
[Client Command] → [Orchestrator] --cmd--> [Service A]
                                   ←evt---           |
                          --cmd--------------------> [Service B]
                                   ←evt-------------|
                          --cmd--------------------> [Service C]
                                   ←evt-------------|
                                   (on failure) --comp--> [A/B] (compensations)
                         [Saga State + Timers + Outbox/Inbox]
```

## Participants

-   **Orchestrator Service** — drives the saga, persists state, sets deadlines, issues commands.
    
-   **Domain Services** — Order, Payment, Inventory, Shipping, etc.
    
-   **Message Broker/Event Bus** — Kafka/Pulsar/Rabbit/SNS+SQS, etc.
    
-   **Saga Store** — DB table(s) for saga instances, steps, timeouts.
    
-   **Outbox/Inbox** — exactly-once publication and idempotent handling.
    
-   **Operators** — inspect, retry, cancel via admin endpoints.
    

## Collaboration

1.  **Start:** Orchestrator receives a **Start** trigger (e.g., `PlaceOrder` command). Creates a **SagaInstance** in `PENDING`.
    
2.  **Step 1:** Sends `ReserveCredit` to Payment.
    
    -   On `CreditReserved` → Step 2.
        
    -   On `CreditRejected` or timeout → **Compensate** and **Fail**.
        
3.  **Step 2:** Sends `ReserveInventory` to Inventory.
    
    -   On `InventoryReserved` → Step 3.
        
    -   On `InventoryRejected` or timeout → **ReleaseCredit** and **Fail**.
        
4.  **Step 3:** Sends `CreateOrder` to Order service.
    
    -   On `OrderCreated` → **Complete**.
        
    -   On failure → **CancelInventory** & **ReleaseCredit** then **Fail**.
        
5.  Any step may **timeout**; orchestrator decides to retry, skip, or compensate based on policy.
    

## Consequences

**Benefits**

-   Centralized control flow, explicit business logic, predictable compensations.
    
-   Easier evolution of process rules and **observability** (one place to inspect).
    
-   Natural fit for **deadlines**, **retries**, **branching**.
    

**Liabilities**

-   Orchestrator can become a **god service** if it accumulates domain logic.
    
-   Increased coupling to the orchestrator’s API and schema.
    
-   Requires robust **idempotency**, **outbox**, and **timeouts** to be production-grade.
    
-   If misdesigned, can become a throughput bottleneck (scale horizontally, partition by saga key).
    

## Implementation

**Key practices**

-   **State machine:** Explicit statuses (PENDING, RUNNING, COMPENSATING, FAILED, COMPLETED) and step transitions.
    
-   **Idempotency:** Per-handler `(sagaId, messageId)` dedupe; side-effect idempotency in participants.
    
-   **Outbox pattern:** Persist commands/events in the same transaction as saga state writes; background relay publishes to broker.
    
-   **Inbox pattern:** Each participant stores processed message IDs; ignore duplicates.
    
-   **Deadlines & retries:** Persist next-attempt time; use a scheduler/worker to fire timeouts.
    
-   **Compensations:** Design domain-level undo (e.g., **release hold**, not “delete row”).
    
-   **Partitioning:** Shard orchestrator instances by `sagaId` hash to keep ordering and scale.
    
-   **Observability:** Correlation IDs, metrics (per step success/failure/latency), traces.
    

---

## Sample Code (Java, Spring Boot style, dependency-light)

> Demonstrates a **credit → inventory → order** saga with compensations, outbox, idempotency, and deadlines. Uses simple repositories to keep the example self-contained.

```java
// ---------- Messages (Commands & Events) ----------
sealed interface Msg permits Cmd, Evt {
    String messageId();
    String correlationId(); // sagaId
}

sealed interface Cmd extends Msg permits ReserveCredit, ReleaseCredit, ReserveInventory, CancelInventory, CreateOrder, CancelOrder { }
sealed interface Evt extends Msg permits CreditReserved, CreditRejected, InventoryReserved, InventoryRejected, OrderCreated, OrderRejected { }

record ReserveCredit(String messageId, String correlationId, String customerId, long amount) implements Cmd {}
record ReleaseCredit(String messageId, String correlationId, String customerId, long amount) implements Cmd {}
record ReserveInventory(String messageId, String correlationId, String sku, int qty) implements Cmd {}
record CancelInventory(String messageId, String correlationId, String sku, int qty) implements Cmd {}
record CreateOrder(String messageId, String correlationId, String orderId) implements Cmd {}
record CancelOrder(String messageId, String correlationId, String orderId) implements Cmd {}

record CreditReserved(String messageId, String correlationId) implements Evt {}
record CreditRejected(String messageId, String correlationId, String reason) implements Evt {}
record InventoryReserved(String messageId, String correlationId) implements Evt {}
record InventoryRejected(String messageId, String correlationId, String reason) implements Evt {}
record OrderCreated(String messageId, String correlationId) implements Evt {}
record OrderRejected(String messageId, String correlationId, String reason) implements Evt {}

// ---------- Saga State ----------
enum SagaStatus { PENDING, RUNNING, COMPENSATING, FAILED, COMPLETED }
enum SagaStep   { NONE, CREDIT_RESERVED, INVENTORY_RESERVED, ORDER_CREATED }

final class OrderSagaData {
    final String sagaId;
    final String orderId;
    final String customerId;
    final String sku;
    final int qty;
    final long amount;
    SagaStatus status = SagaStatus.PENDING;
    SagaStep step = SagaStep.NONE;
    int version = 0; // optimistic lock
    long nextDeadlineEpochMs = 0L;
    OrderSagaData(String sagaId, String orderId, String customerId, String sku, int qty, long amount) {
        this.sagaId = sagaId; this.orderId = orderId; this.customerId = customerId; this.sku = sku; this.qty = qty; this.amount = amount;
    }
}

// ---------- Repositories (in-memory demo) ----------
interface SagaRepo {
    Optional<OrderSagaData> find(String sagaId);
    void save(OrderSagaData s);
}

final class InMemSagaRepo implements SagaRepo {
    private final java.util.concurrent.ConcurrentHashMap<String, OrderSagaData> map = new java.util.concurrent.ConcurrentHashMap<>();
    public Optional<OrderSagaData> find(String id) { return Optional.ofNullable(map.get(id)); }
    public void save(OrderSagaData s) { map.put(s.sagaId, s); }
}

// Dedup store for idempotent event handling
interface Inbox {
    boolean seen(String handler, String messageId);
}
final class InMemInbox implements Inbox {
    private final java.util.Set<String> seen = java.util.concurrent.ConcurrentHashMap.newKeySet();
    public boolean seen(String handler, String messageId) { return !seen.add(handler + "|" + messageId); }
}

// Outbox for reliable send (relay publishes to broker; here we just collect)
record OutboxMessage(String id, String topic, Msg payload) {}
final class InMemOutbox {
    private final java.util.Queue<OutboxMessage> queue = new java.util.concurrent.ConcurrentLinkedQueue<>();
    void add(OutboxMessage m) { queue.add(m); }
    java.util.List<OutboxMessage> drain() { var list = new java.util.ArrayList<OutboxMessage>(); queue.drainTo(list); return list; }
}

// ---------- Orchestrator ----------
final class OrderSagaOrchestrator {
    private static final String HANDLER = "OrderSagaOrchestrator.v1";
    private final SagaRepo repo;
    private final Inbox inbox;
    private final InMemOutbox outbox;

    OrderSagaOrchestrator(SagaRepo repo, Inbox inbox, InMemOutbox outbox) {
        this.repo = repo; this.inbox = inbox; this.outbox = outbox;
    }

    // Start saga
    public void start(String orderId, String customerId, String sku, int qty, long amount) {
        String sagaId = java.util.UUID.randomUUID().toString();
        var s = new OrderSagaData(sagaId, orderId, customerId, sku, qty, amount);
        s.status = SagaStatus.RUNNING;
        s.nextDeadlineEpochMs = System.currentTimeMillis() + 10_000; // 10s deadline for first step
        repo.save(s);

        send(new ReserveCredit(newMsgId(), s.sagaId, customerId, amount), "payment.commands");
    }

    // Event handlers (idempotent)
    public void on(Evt evt) {
        if (inbox.seen(HANDLER, evt.messageId())) return; // already processed

        var s = repo.find(evt.correlationId()).orElseThrow(() -> new IllegalStateException("saga not found"));
        switch (evt) {
            case CreditReserved e -> {
                if (s.status != SagaStatus.RUNNING || s.step != SagaStep.NONE) break;
                s.step = SagaStep.CREDIT_RESERVED;
                s.nextDeadlineEpochMs = System.currentTimeMillis() + 10_000;
                repo.save(s);
                send(new ReserveInventory(newMsgId(), s.sagaId, s.sku, s.qty), "inventory.commands");
            }
            case CreditRejected e -> failAndStop(s, () -> { /* nothing reserved yet */ });
            case InventoryReserved e -> {
                if (s.status != SagaStatus.RUNNING || s.step != SagaStep.CREDIT_RESERVED) break;
                s.step = SagaStep.INVENTORY_RESERVED;
                s.nextDeadlineEpochMs = System.currentTimeMillis() + 10_000;
                repo.save(s);
                send(new CreateOrder(newMsgId(), s.sagaId, s.orderId), "order.commands");
            }
            case InventoryRejected e -> failAndStop(s, () -> {
                // compensate credit
                send(new ReleaseCredit(newMsgId(), s.sagaId, s.customerId, s.amount), "payment.commands");
            });
            case OrderCreated e -> {
                if (s.status != SagaStatus.RUNNING || s.step != SagaStep.INVENTORY_RESERVED) break;
                s.step = SagaStep.ORDER_CREATED;
                s.status = SagaStatus.COMPLETED;
                s.nextDeadlineEpochMs = 0;
                repo.save(s);
            }
            case OrderRejected e -> failAndStop(s, () -> {
                // compensate inventory and credit
                send(new CancelInventory(newMsgId(), s.sagaId, s.sku, s.qty), "inventory.commands");
                send(new ReleaseCredit(newMsgId(), s.sagaId, s.customerId, s.amount), "payment.commands");
            });
            default -> { /* ignore */ }
        }
    }

    // Deadline/timeout tick—call periodically
    public void tickDeadlines() {
        long now = System.currentTimeMillis();
        // In a real repo, query by nextDeadline <= now
        repo.findAll().forEachRemaining(s -> { /* not implemented for brevity */ });
    }

    private void failAndStop(OrderSagaData s, Runnable compensation) {
        if (s.status == SagaStatus.COMPLETED || s.status == SagaStatus.FAILED) return;
        s.status = SagaStatus.COMPENSATING;
        repo.save(s);
        compensation.run();
        s.status = SagaStatus.FAILED;
        s.nextDeadlineEpochMs = 0;
        repo.save(s);
    }

    private void send(Cmd cmd, String topic) {
        outbox.add(new OutboxMessage(newMsgId(), topic, cmd));
    }

    private static String newMsgId() { return java.util.UUID.randomUUID().toString(); }
}

// ---------- Demo driver ----------
public class Demo {
    public static void main(String[] args) {
        var repo = new InMemSagaRepo();
        var inbox = new InMemInbox();
        var outbox = new InMemOutbox();
        var orch = new OrderSagaOrchestrator(repo, inbox, outbox);

        // Start the saga
        orch.start("ORD-123", "CUST-9", "SKU-1", 2, 199_00);

        // Payment service replies success
        var pending = outbox.drain(); // would be published; here we simulate the flow
        pending.forEach(System.out::println);
        orch.on(new CreditReserved(java.util.UUID.randomUUID().toString(), pending.get(0).payload().correlationId()));

        // Inventory success
        var afterCredit = outbox.drain();
        afterCredit.forEach(System.out::println);
        orch.on(new InventoryReserved(java.util.UUID.randomUUID().toString(), afterCredit.get(0).payload().correlationId()));

        // Order success → saga completes
        var afterInventory = outbox.drain();
        afterInventory.forEach(System.out::println);
        orch.on(new OrderCreated(java.util.UUID.randomUUID().toString(), afterInventory.get(0).payload().correlationId()));

        System.out.println("Saga completed.");
    }
}
```

**Notes on the example**

-   Replace the in-memory repo/outbox with a database **(saga table + outbox table)**. A background relay publishes outbox rows to the broker.
    
-   Each participant must implement **idempotent handlers** (Inbox) and their **compensation commands** (`ReleaseCredit`, `CancelInventory`, etc.).
    
-   Add **deadlines** by storing `nextDeadlineEpochMs` and running a scheduler to emit timeout events (e.g., `CreditReserveTimedOut`).
    

## Known Uses

-   **eCommerce checkout:** Reserve credit → reserve inventory → create order; compensate on failures.
    
-   **Travel booking:** Reserve flight → hotel → car; cancel previous reservations on any rejection.
    
-   **Banking:** Open account → KYC verification → initial funding; compensate by reverting holds.
    
-   **Telecom onboarding:** Provision SIM → activate plan → notify CRM; roll back on provisioning failure.
    

## Related Patterns

-   **Choreography Saga:** Distributed decision-making by events (no central orchestrator).
    
-   **Transactional Outbox / Inbox:** Reliable publish and idempotent consume.
    
-   **Process Manager (EIP):** Generic name for orchestration logic.
    
-   **Compensating Transaction:** Undo action for eventual consistency.
    
-   **Retry / Circuit Breaker / Timeouts:** Operational guardrails inside each step.
    
-   **Event Sourcing & Event Replay:** Durable history and rebuild of projections/state for audits and recovery.

