# Saga — Microservice Pattern

## Pattern Name and Classification

-   **Name:** Saga
    
-   **Classification:** Distributed Transaction & Process Coordination Pattern (microservices, event-driven)
    

## Intent

Coordinate a **long-lived, multi-service business transaction** as a **sequence of local transactions** with **compensating actions** instead of a global ACID transaction.

## Also Known As

-   Long-Lived Transactions (LLT)
    
-   Process Manager (orchestrator variant)
    
-   Choreography (event-driven variant)
    

## Motivation (Forces)

-   **No 2PC across services:** Independent databases and datastores preclude traditional distributed ACID.
    
-   **Business workflows are multi-step:** E.g., order → reserve inventory → charge payment → ship.
    
-   **Partial failure is normal:** A step may fail or time out; you must **undo** previous steps.
    
-   **Autonomy vs. coupling:** You want autonomous services, yet require **reliable end-to-end outcomes**.
    

**Tensions**

-   **Consistency vs. availability:** Outcomes are **eventually consistent**, not instantaneous.
    
-   **Operational complexity:** Orchestration state, retries, timeouts, duplicate handling, and compensations.
    
-   **Coupling style:** Orchestration centralizes flow logic; choreography distributes it (can cause “event spaghetti”).
    

## Applicability

Use Saga when:

-   A business flow updates **multiple services/databases** and must either **complete** or **compensate** to a valid state.
    
-   Steps can be expressed as **local transactions** with **inverse operations**.
    
-   The domain tolerates **eventual consistency** and **idempotent** effects.
    

De-prioritize when:

-   You truly need **atomic cross-aggregate** invariants (consider re-modeling boundaries or specialized stores).
    
-   Compensations are **illegal or impossible** (e.g., irreversible external side effects).
    
-   A **single service** can safely own the whole transaction (simpler).
    

## Structure

Two principal styles:

**Orchestration (central brain)**

```csharp
[Orchestrator / Process Manager]
   ├─ send Command: ReserveInventory → [Inventory Svc]
   ├─ on InventoryReserved → Command: AuthorizePayment → [Payment Svc]
   ├─ on PaymentAuthorized → Command: ArrangeShipping → [Shipping Svc]
   └─ on any failure → send compensations (ReleaseInventory, RefundPayment, CancelShipment)
```

**Choreography (event-driven rules)**

```vbnet
[Order Created] event
  └─ Inventory Svc reacts → ReserveInventory → emits InventoryReserved/Failed
        └─ Payment Svc reacts to InventoryReserved → AuthorizePayment → emits PaymentAuthorized/Failed
             └─ Shipping Svc reacts to PaymentAuthorized → ArrangeShipping → emits ShippingArranged/Failed
                  └─ Order Svc reacts → mark Completed/Cancelled (+ compensations on failures)
```

## Participants

-   **Saga Initiator:** Starts the process (e.g., Order service).
    
-   **Saga Orchestrator (or Process Manager):** Holds state, sends commands, reacts to events (orchestration only).
    
-   **Participating Services:** Inventory, Payment, Shipping, etc.; each executes a **local transaction** and emits an event.
    
-   **Compensators:** Inverse actions (e.g., ReleaseInventory, RefundPayment, CancelShipment).
    
-   **Message Broker:** Transports commands/events (Kafka, RabbitMQ, etc.).
    
-   **Saga Log / Store:** Durable state of saga instances and steps.
    
-   **DLQ & Retry Engine:** Reliability for transient failures.
    

## Collaboration

1.  **Start:** Initiator emits `OrderCreated` or calls Orchestrator.
    
2.  **Step Execution:** Each step is a **local ACID transaction**; on success, emit event; on failure, emit failure event.
    
3.  **Decision:** Orchestrator (or rule listeners in choreography) decides next step or compensation.
    
4.  **Compensation:** If any step fails, **undo** prior successful steps via compensating commands.
    
5.  **Completion:** Mark Saga as `COMPLETED` or `COMPENSATED/FAILED`; publish terminal event.
    

## Consequences

**Benefits**

-   Enables **reliable multi-service workflows** without 2PC.
    
-   Keeps services **locally ACID**; failures do not lock global resources.
    
-   **Auditable history** of steps and compensations.
    

**Liabilities**

-   **Complexity:** Modeling compensations and timeouts is non-trivial.
    
-   **Visibility:** Choreography can become hard to reason about; orchestration adds a central dependency.
    
-   **Edge cases:** Duplicates, out-of-order events, and partial compensations require **idempotency** and **retries**.
    
-   **User experience:** Clients see **eventual** rather than immediate final state.
    

## Implementation

1.  **Choose style:**
    
    -   **Orchestration** when flows are complex, change often, or need centralized control and timeouts.
        
    -   **Choreography** when flows are simple with minimal coupling and teams own clear reactions.
        
2.  **Define steps and compensations:** Each action must have an inverse (or a business-acceptable alternative).
    
3.  **Idempotency:** Commands and compensations are **idempotent** (keys, versions). Keep **sagaId** and **stepId**.
    
4.  **State & persistence:** Store saga state (`id`, `status`, `currentStep`, `data`, `timeouts`, `history`).
    
5.  **Timeouts & retries:** Per-step timeouts, bounded retries with **exponential backoff + jitter**; on expiry → compensate.
    
6.  **Outbox/CDC:** Use **transactional outbox** in participants to publish events reliably.
    
7.  **DLQ & replay:** Poison messages go to DLQ; provide replay tooling.
    
8.  **Tracing & logs:** Propagate **traceparent** and `sagaId`; correlate logs/traces.
    
9.  **Access patterns:** Read final status via **query model** or direct orchestrator API.
    
10.  **Testing:** Given–When–Then event tests; chaos inject timeouts and network partitions.
    

---

## Sample Code (Java, Spring Boot) — Orchestration with Kafka + JPA (Postgres)

> Minimal but production-leaning snippets: an **Orchestrator** coordinates `ReserveInventory → AuthorizePayment → ArrangeShipping` with compensations on failure. Includes a **transactional outbox** for reliable event publication from the orchestrator itself. Participants are sketched to show command/event shapes.

### `pom.xml` (snippets)

```xml
<dependencies>
  <dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-web</artifactId>
  </dependency>
  <dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-data-jpa</artifactId>
  </dependency>
  <dependency>
    <groupId>org.postgresql</groupId>
    <artifactId>postgresql</artifactId>
  </dependency>
  <dependency>
    <groupId>org.springframework.kafka</groupId>
    <artifactId>spring-kafka</artifactId>
  </dependency>
  <dependency>
    <groupId>com.fasterxml.jackson.core</groupId>
    <artifactId>jackson-databind</artifactId>
  </dependency>
</dependencies>
```

### Topics (example)

```matlab
commands.inventory.reserve
commands.inventory.release
commands.payment.authorize
commands.payment.refund
commands.shipping.arrange
commands.shipping.cancel
events.inventory.reserved / events.inventory.reservation_failed
events.payment.authorized / events.payment.authorization_failed
events.shipping.arranged / events.shipping.arrangement_failed
events.order.completed / events.order.compensated
```

### SQL (Postgres) — saga + outbox

```sql
-- db/changelog/001_saga.sql
create table if not exists saga_instance (
  id uuid primary key,
  order_id uuid not null,
  status varchar(32) not null,               -- NEW, RUNNING, COMPLETED, COMPENSATING, COMPENSATED, FAILED
  step varchar(64) not null,                 -- e.g., RESERVE_INV, AUTHORIZE_PAY, ARRANGE_SHIP
  data jsonb not null default '{}'::jsonb,   -- correlated data (sku, qty, amounts, etc.)
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create table if not exists outbox_event (
  id bigserial primary key,
  aggregate_type varchar(64) not null,
  aggregate_id uuid not null,
  event_type varchar(96) not null,
  payload jsonb not null,
  headers jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null default now(),
  published boolean not null default false
);

create index if not exists idx_outbox_pub on outbox_event(published, occurred_at);
```

### Configuration

```properties
spring.datasource.url=jdbc:postgresql://db:5432/saga
spring.datasource.username=saga
spring.datasource.password=secret
spring.jpa.hibernate.ddl-auto=validate
spring.jpa.open-in-view=false
spring.kafka.bootstrap-servers=kafka:9092
```

### Domain DTOs (commands/events)

```java
// dto/CommandsEvents.java
package saga.dto;

import java.util.UUID;

public record ReserveInventoryCmd(UUID sagaId, String sku, int qty) {}
public record ReleaseInventoryCmd(UUID sagaId, String sku, int qty) {}
public record InventoryReservedEvt(UUID sagaId) {}
public record InventoryReservationFailedEvt(UUID sagaId, String reason) {}

public record AuthorizePaymentCmd(UUID sagaId, String paymentRef, long amountCents) {}
public record RefundPaymentCmd(UUID sagaId, String paymentRef, long amountCents) {}
public record PaymentAuthorizedEvt(UUID sagaId, String authCode) {}
public record PaymentAuthorizationFailedEvt(UUID sagaId, String reason) {}

public record ArrangeShippingCmd(UUID sagaId, String address) {}
public record CancelShippingCmd(UUID sagaId) {}
public record ShippingArrangedEvt(UUID sagaId, String trackingNo) {}
public record ShippingArrangementFailedEvt(UUID sagaId, String reason) {}

public record OrderCompletedEvt(UUID sagaId, UUID orderId) {}
public record OrderCompensatedEvt(UUID sagaId, UUID orderId, String reason) {}
```

### JPA Entities

```java
// store/SagaInstance.java
package saga.store;

import jakarta.persistence.*;
import java.time.OffsetDateTime;
import java.util.UUID;

@Entity @Table(name="saga_instance")
public class SagaInstance {
  @Id private UUID id;
  @Column(nullable=false) private UUID orderId;
  @Column(nullable=false) private String status; // NEW,RUNNING,COMPLETED,COMPENSATING,COMPENSATED,FAILED
  @Column(nullable=false) private String step;   // RESERVE_INV, AUTHORIZE_PAY, ARRANGE_SHIP
  @Lob @Column(columnDefinition="jsonb") private String data;
  @Column(nullable=false) private OffsetDateTime updatedAt = OffsetDateTime.now();
  @Column(nullable=false) private OffsetDateTime createdAt = OffsetDateTime.now();

  protected SagaInstance() {}
  public SagaInstance(UUID id, UUID orderId, String status, String step, String data) {
    this.id=id; this.orderId=orderId; this.status=status; this.step=step; this.data=data;
  }
  // getters/setters...
}
```

```java
// store/OutboxEvent.java
package saga.store;

import jakarta.persistence.*;

@Entity @Table(name="outbox_event")
public class OutboxEvent {
  @Id @GeneratedValue(strategy=GenerationType.IDENTITY) private Long id;
  private String aggregateType;
  private java.util.UUID aggregateId;
  private String eventType;
  @Lob @Column(columnDefinition="jsonb") private String payload;
  @Lob @Column(columnDefinition="jsonb") private String headers = "{}";
  private boolean published = false;

  protected OutboxEvent() {}
  public OutboxEvent(String aggType, java.util.UUID aggId, String eventType, String payload) {
    this.aggregateType=aggType; this.aggregateId=aggId; this.eventType=eventType; this.payload=payload;
  }
  // getters/setters...
}
```

```java
// store/Repos.java
package saga.store;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.*;

public interface SagaRepo extends JpaRepository<SagaInstance, UUID> {}
public interface OutboxRepo extends JpaRepository<OutboxEvent, Long> {
  List<OutboxEvent> findTop100ByPublishedFalseOrderByIdAsc();
}
```

### Orchestrator

```java
// core/SagaOrchestrator.java
package saga.core;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import saga.dto.*;
import saga.store.*;

import java.util.Map;
import java.util.UUID;

@Service
public class SagaOrchestrator {

  private final SagaRepo sagaRepo;
  private final OutboxRepo outbox;
  private final KafkaTemplate<String, String> kafka;
  private final ObjectMapper json;

  // topics (could be externalized config)
  private static final String T_RESERVE = "commands.inventory.reserve";
  private static final String T_RELEASE = "commands.inventory.release";
  private static final String T_AUTH    = "commands.payment.authorize";
  private static final String T_REFUND  = "commands.payment.refund";
  private static final String T_SHIP    = "commands.shipping.arrange";
  private static final String T_CANCEL  = "commands.shipping.cancel";

  public SagaOrchestrator(SagaRepo sagaRepo, OutboxRepo outbox,
                          KafkaTemplate<String,String> kafka, ObjectMapper json) {
    this.sagaRepo = sagaRepo; this.outbox = outbox; this.kafka = kafka; this.json = json;
  }

  @Transactional
  public UUID start(UUID orderId, String sku, int qty, long amountCents, String paymentRef, String address) {
    UUID sagaId = UUID.randomUUID();
    var data = Map.of("sku", sku, "qty", qty, "amountCents", amountCents, "paymentRef", paymentRef, "address", address);
    try {
      sagaRepo.save(new SagaInstance(sagaId, orderId, "RUNNING", "RESERVE_INV", json.writeValueAsString(data)));
      send(new ReserveInventoryCmd(sagaId, sku, qty), T_RESERVE);
    } catch (Exception e) {
      throw new RuntimeException(e);
    }
    return sagaId;
  }

  // --- Event handlers ---

  @Transactional
  public void on(InventoryReservedEvt evt) throws Exception {
    var s = sagaRepo.findById(evt.sagaId()).orElseThrow();
    if (!s.getStep().equals("RESERVE_INV")) return; // idempotent check
    s.setStep("AUTHORIZE_PAY");
    var data = json.readTree(s.getData());
    send(new AuthorizePaymentCmd(s.getId(), data.get("paymentRef").asText(), data.get("amountCents").asLong()), T_AUTH);
  }

  @Transactional
  public void on(InventoryReservationFailedEvt evt) throws Exception {
    failAndCompensate(evt.sagaId(), "Inventory reservation failed: " + evt.reason());
  }

  @Transactional
  public void on(PaymentAuthorizedEvt evt) throws Exception {
    var s = sagaRepo.findById(evt.sagaId()).orElseThrow();
    if (!s.getStep().equals("AUTHORIZE_PAY")) return;
    s.setStep("ARRANGE_SHIP");
    var data = json.readTree(s.getData());
    send(new ArrangeShippingCmd(s.getId(), data.get("address").asText()), T_SHIP);
  }

  @Transactional
  public void on(PaymentAuthorizationFailedEvt evt) throws Exception {
    var s = sagaRepo.findById(evt.sagaId()).orElseThrow();
    s.setStatus("COMPENSATING"); s.setStep("REFUND_AND_RELEASE");
    var data = json.readTree(s.getData());
    // payment failed; only release inventory (no refund necessary if not captured)
    send(new ReleaseInventoryCmd(s.getId(), data.get("sku").asText(), data.get("qty").asInt()), T_RELEASE);
    publish("events.order.compensated", new OrderCompensatedEvt(s.getId(), s.getOrderId(), evt.reason()));
    s.setStatus("COMPENSATED");
  }

  @Transactional
  public void on(ShippingArrangedEvt evt) throws Exception {
    var s = sagaRepo.findById(evt.sagaId()).orElseThrow();
    if (!s.getStep().equals("ARRANGE_SHIP")) return;
    s.setStatus("COMPLETED"); s.setStep("DONE");
    publish("events.order.completed", new OrderCompletedEvt(s.getId(), s.getOrderId()));
  }

  @Transactional
  public void on(ShippingArrangementFailedEvt evt) throws Exception {
    // Ship failed → compensate: refund payment + release inventory + cancel shipment (noop)
    var s = sagaRepo.findById(evt.sagaId()).orElseThrow();
    s.setStatus("COMPENSATING"); s.setStep("REFUND_AND_RELEASE");
    var data = json.readTree(s.getData());
    send(new RefundPaymentCmd(s.getId(), data.get("paymentRef").asText(), data.get("amountCents").asLong()), T_REFUND);
    send(new ReleaseInventoryCmd(s.getId(), data.get("sku").asText(), data.get("qty").asInt()), T_RELEASE);
    send(new CancelShippingCmd(s.getId()), T_CANCEL);
    publish("events.order.compensated", new OrderCompensatedEvt(s.getId(), s.getOrderId(), evt.reason()));
    s.setStatus("COMPENSATED");
  }

  // --- helpers ---
  private void send(Object command, String topic) throws Exception {
    var payload = json.writeValueAsString(command);
    kafka.send(topic, payload); // fire-and-forget (retry at KafkaTemplate level recommended)
  }

  private void publish(String topic, Object event) throws Exception {
    var payload = json.writeValueAsString(event);
    outbox.save(new OutboxEvent("Saga", (java.util.UUID) event.getClass().getDeclaredMethod("sagaId").invoke(event),
      event.getClass().getSimpleName(), payload));
    // outbox publisher below will ship to broker
  }

  private void failAndCompensate(UUID sagaId, String reason) throws Exception {
    var s = sagaRepo.findById(sagaId).orElseThrow();
    s.setStatus("COMPENSATING"); s.setStep("RELEASE_ONLY");
    var data = json.readTree(s.getData());
    send(new ReleaseInventoryCmd(s.getId(), data.get("sku").asText(), data.get("qty").asInt()), T_RELEASE);
    publish("events.order.compensated", new OrderCompensatedEvt(s.getId(), s.getOrderId(), reason));
    s.setStatus("COMPENSATED");
  }
}
```

### Kafka Listeners (wire events to orchestrator)

```java
// core/OrchestratorListeners.java
package saga.core;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;
import saga.dto.*;

@Component
public class OrchestratorListeners {
  private final SagaOrchestrator orchestrator;
  private final ObjectMapper json;

  public OrchestratorListeners(SagaOrchestrator orchestrator, ObjectMapper json) {
    this.orchestrator = orchestrator; this.json = json;
  }

  @KafkaListener(topics = "events.inventory.reserved", groupId = "saga-orch")
  public void onInventoryReserved(String payload) throws Exception {
    orchestrator.on(json.readValue(payload, InventoryReservedEvt.class));
  }

  @KafkaListener(topics = "events.inventory.reservation_failed", groupId = "saga-orch")
  public void onInventoryFailed(String payload) throws Exception {
    orchestrator.on(json.readValue(payload, InventoryReservationFailedEvt.class));
  }

  @KafkaListener(topics = "events.payment.authorized", groupId = "saga-orch")
  public void onPaymentAuthorized(String payload) throws Exception {
    orchestrator.on(json.readValue(payload, PaymentAuthorizedEvt.class));
  }

  @KafkaListener(topics = "events.payment.authorization_failed", groupId = "saga-orch")
  public void onPaymentFailed(String payload) throws Exception {
    orchestrator.on(json.readValue(payload, PaymentAuthorizationFailedEvt.class));
  }

  @KafkaListener(topics = "events.shipping.arranged", groupId = "saga-orch")
  public void onShippingArranged(String payload) throws Exception {
    orchestrator.on(json.readValue(payload, ShippingArrangedEvt.class));
  }

  @KafkaListener(topics = "events.shipping.arrangement_failed", groupId = "saga-orch")
  public void onShippingFailed(String payload) throws Exception {
    orchestrator.on(json.readValue(payload, ShippingArrangementFailedEvt.class));
  }
}
```

### Outbox Publisher (Orchestrator → Events)

```java
// core/OutboxPublisher.java
package saga.core;

import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import saga.store.OutboxEvent;
import saga.store.OutboxRepo;

@Component
public class OutboxPublisher {
  private final OutboxRepo repo;
  private final KafkaTemplate<String,String> kafka;

  public OutboxPublisher(OutboxRepo repo, KafkaTemplate<String,String> kafka) {
    this.repo = repo; this.kafka = kafka;
  }

  @Scheduled(fixedDelay=500)
  public void publish() {
    var batch = repo.findTop100ByPublishedFalseOrderByIdAsc();
    for (OutboxEvent e : batch) {
      // route by event type; here we use topic name prefix
      String topic = e.getEventType().equals("OrderCompletedEvt") ? "events.order.completed" : "events.order.compensated";
      kafka.send(topic, e.getPayload());
      e.setPublished(true);
      repo.save(e);
    }
  }
}
```

### Start API

```java
// api/SagaController.java
package saga.api;

import org.springframework.web.bind.annotation.*;
import saga.core.SagaOrchestrator;

import java.util.Map;
import java.util.UUID;

@RestController
@RequestMapping("/sagas")
public class SagaController {
  private final SagaOrchestrator orch;
  public SagaController(SagaOrchestrator orch) { this.orch = orch; }

  @PostMapping("/orders")
  public Map<String,Object> start(@RequestBody Map<String,Object> req) {
    UUID orderId = UUID.fromString((String) req.get("orderId"));
    String sku = (String) req.get("sku");
    int qty = ((Number) req.get("qty")).intValue();
    long amount = ((Number) req.get("amountCents")).longValue();
    String paymentRef = (String) req.get("paymentRef");
    String address = (String) req.get("address");
    var sagaId = orch.start(orderId, sku, qty, amount, paymentRef, address);
    return Map.of("sagaId", sagaId.toString(), "status", "RUNNING");
  }
}
```

### Participant Sketch (Inventory Service)

```java
// inventory/InventoryHandlers.java  (in the Inventory service)
@org.springframework.stereotype.Component
class InventoryHandlers {
  private final org.springframework.kafka.core.KafkaTemplate<String,String> kafka;
  private final com.fasterxml.jackson.databind.ObjectMapper json;

  InventoryHandlers(org.springframework.kafka.core.KafkaTemplate<String,String> kafka,
                    com.fasterxml.jackson.databind.ObjectMapper json) {
    this.kafka = kafka; this.json = json;
  }

  @org.springframework.kafka.annotation.KafkaListener(topics="commands.inventory.reserve", groupId="inventory")
  public void onReserve(String payload) throws Exception {
    var cmd = json.readValue(payload, saga.dto.ReserveInventoryCmd.class);
    // try local transaction: decrement stock
    boolean ok = true; // implement actual logic
    if (ok) kafka.send("events.inventory.reserved", json.writeValueAsString(new saga.dto.InventoryReservedEvt(cmd.sagaId())));
    else    kafka.send("events.inventory.reservation_failed", json.writeValueAsString(new saga.dto.InventoryReservationFailedEvt(cmd.sagaId(), "no stock")));
  }

  @org.springframework.kafka.annotation.KafkaListener(topics="commands.inventory.release", groupId="inventory")
  public void onRelease(String payload) throws Exception {
    var cmd = json.readValue(payload, saga.dto.ReleaseInventoryCmd.class);
    // local transaction: increase stock; be idempotent on (sagaId, sku)
  }
}
```

> **Notes for production:**
> 
> -   Add **retry policies** (Resilience4j) around producer sends and listener handlers; classify retryable vs. non-retryable exceptions; route to **DLQ** on exhaust.
>     
> -   Participants should use **transactional outbox** to emit events after their local commit.
>     
> -   Protect against duplicates by persisting `(sagaId, action)` as processed keys.
>     
> -   Use **timeouts**: if the next event doesn’t arrive in T seconds, trigger compensation.
>     

---

## Known Uses

-   **E-commerce orders** (inventory → payment → shipping) with compensations for stock release and refunds.
    
-   **Travel booking** (flight, hotel, car): failure in one reservation triggers cancels of others.
    
-   **Telecom provisioning** and **account onboarding**: multi-system steps with rollback rules.
    
-   Frameworks and platforms: **Axon Framework**, **Eventuate Tram**, **Camunda / Zeebe**, **Temporal / Cadence** (workflow-as-code supports saga semantics).
    

## Related Patterns

-   **Transactional Outbox & CDC:** Reliable event publication from local transactions.
    
-   **Compensating Transaction:** The inverse operations saga depends on.
    
-   **Retry + Circuit Breaker + Timeout:** Stability for each step.
    
-   **Idempotent Consumer:** Safe replays and duplicate handling.
    
-   **CQRS & Read Models:** Build user-facing status views of saga progress.
    
-   **Distributed Tracing:** Correlate `sagaId` across hops and visualize the critical path.
    
-   **Dead Letter Queue:** Park poison messages for triage when compensations repeatedly fail.

