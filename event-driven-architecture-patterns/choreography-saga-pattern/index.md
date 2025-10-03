# Choreography Saga — Event-Driven Architecture Pattern

## Pattern Name and Classification

**Name:** Choreography Saga  
**Classification:** Long-running transaction / Process Coordination pattern (EDA); **event-chained saga** where participating services react to and emit domain events—no central coordinator.

## Intent

Coordinate a multi-step business transaction across autonomous services by letting each service **listen to events**, execute its **local transaction**, and publish a **follow-up event** (or a **compensation event** on failure). The saga completes when a terminal event is observed or compensations settle.

## Also Known As

-   Event-Chained Saga
    
-   Decentralized Saga
    
-   Peer-to-Peer Saga
    

## Motivation (Forces)

-   Avoid brittle, slow **distributed ACID** or 2PC across services.
    
-   Preserve **autonomy and decoupling**: each service owns its data and reacts to events.
    
-   Improve **resilience**: steps can retry or compensate independently; no single orchestration brain.
    
-   Deliver **scalability** with loose coupling and asynchronous processing.
    

**Forces to balance**

-   Global visibility is weaker; flows can become **implicit** and hard to reason about.
    
-   Compensation semantics can be **domain-specific** and imperfect (refund vs. delete).
    
-   Requires **idempotency**, **correlation**, and **observability** discipline.
    

## Applicability

Use Choreography Saga when:

-   Steps are **loosely coupled** and can publish/subscribe to domain events.
    
-   Each step has a clear **compensating action** (reserve→release, charge→refund).
    
-   You favor **autonomy** and wish to avoid a central coordinator or BPM engine.
    
-   The business tolerates **eventual consistency**.
    

Avoid when:

-   You need **global control**, human approvals, or complex branching—prefer an **Orchestrated Saga**.
    
-   Compensations are impossible or legally risky, and **atomicity** is required—keep steps in one service/DB.
    

## Structure

```sql
Order Service --(OrderCreated)--> Inventory Service --(InventoryReserved | InventoryRejected)-->
     |                                                                                |
     |                                                                                v
     |<--(OrderRejected)   Payment Service <--(InventoryReserved)-- (PaymentAuthorized | PaymentFailed)
     |                                                                                |
     v                                                                                v
Shipping Service <--(PaymentAuthorized)-- ... --(ShipmentCreated | ShipmentFailed)--> Compensation Events
```

## Participants

-   **Domain Services** (Order, Inventory, Payment, Shipping…): handle local transactions; emit follow-up/compensation events.
    
-   **Message Bus / Topics:** carry domain events (pub/sub).
    
-   **Outbox/Inbox (optional but recommended):** reliable publish/consume.
    
-   **Idempotency Store:** prevents duplicate side effects.
    
-   **Observability Stack:** tracing, logs, metrics, and a saga view built from events.
    

## Collaboration

1.  A **trigger event** (e.g., `OrderCreated`) is published.
    
2.  Each interested service **consumes** it, performs a local ACID change, and **emits** either a success event (continue) or a compensation/negative event (rollback chain).
    
3.  Downstream services **react** accordingly until a terminal event (`OrderCompleted` or `OrderCanceled`) occurs.
    
4.  Late/duplicate events are ignored via **idempotent receivers**. DLQs capture poison messages.
    

## Consequences

**Benefits**

-   High **autonomy** and **scalability**; no central orchestrator SPOF.
    
-   Natural fit for **event-driven** systems; easy to add new reactions.
    
-   Localizes failures; each service owns its compensations.
    

**Liabilities**

-   Harder **global reasoning** and monitoring; risk of “spaghetti events.”
    
-   Compensation logic can be complex and **not perfectly reversible**.
    
-   Requires discipline for **schemas, correlation, idempotency, and SLAs**.
    
-   Race conditions possible without careful modeling (e.g., concurrent compensations).
    

## Implementation

-   **Contracts:** Versioned event types (`orders.order.created.v1`). Use envelope headers: `messageId`, `correlationId` (sagaId/orderId), `causationId`, `eventType`, `eventVersion`, `occurredAt`.
    
-   **Reliability:**
    
    -   **Transactional Outbox** for write side (save state + stage event atomically).
        
    -   **Inbox/Idempotent Receiver** for read side (dedupe by `messageId`/`orderId#eventType`).
        
-   **Compensation:** Define explicit reverse actions; ensure they’re **idempotent**.
    
-   **Timeouts:** Services may publish **timeout events** (e.g., `PaymentTimedOut`) and trigger compensation.
    
-   **Observability:** Correlate with `correlationId` across services; aggregate saga timelines from logs/events.
    
-   **Security & Governance:** ACLs per topic, schema registry with compatibility rules, PII redaction.
    
-   **Testing:** Contract tests for events; end-to-end tests that simulate failures at any step.
    

---

## Sample Code (Java)

> The following shows a **choreographed checkout** across four services using **Spring Kafka**. Each service is a minimal slice; in real systems, split into separate deployables. For brevity, outbox/inbox are noted where they would be placed.

### Common: Event Envelope & Headers

```java
public record Envelope<T>(
    String eventType, String eventVersion, String correlationId, String causationId,
    String messageId, long occurredAt, T payload
) {
  public static <T> Envelope<T> of(String type, String ver, String corr, String cause, T p) {
    return new Envelope<>(type, ver, corr, cause,
        java.util.UUID.randomUUID().toString(),
        System.currentTimeMillis(), p);
  }
}
```

### Order Service (start + react to terminal events)

```java
// build.gradle deps (snippets): spring-boot-starter, spring-kafka, spring-data-jpa, jackson
@Service
public class OrderService {
  private final KafkaTemplate<String, byte[]> kafka;
  private final ObjectMapper json = new ObjectMapper();
  private final EntityManager em;

  public OrderService(KafkaTemplate<String, byte[]> kafka, EntityManager em) {
    this.kafka = kafka; this.em = em;
  }

  @Transactional
  public void createOrder(String orderId, String sku, int qty) {
    // Local ACID
    em.persist(new OrderEntity(orderId, "PENDING", sku, qty));
    // Outbox (conceptual): stage event rows here in same TX, then ship. For brevity we publish directly.
    publish("orders.order.created.v1", orderId,
        new OrderCreated(orderId, sku, qty));
  }

  @KafkaListener(topics = {"shipping.shipment.created.v1", "orders.order.canceled.v1"}, groupId = "order")
  @Transactional
  public void onTerminalEvents(byte[] bytes) throws Exception {
    var env = json.readValue(bytes, new com.fasterxml.jackson.core.type.TypeReference<Envelope<Map<String,Object>>>(){});
    String orderId = (String) env.payload().get("orderId");
    OrderEntity o = em.find(OrderEntity.class, orderId);
    if (o == null) return;
    if (env.eventType().equals("shipping.shipment.created")) o.status = "COMPLETED";
    if (env.eventType().equals("orders.order.canceled")) o.status = "CANCELED";
    em.merge(o);
  }

  private void publish(String type, String orderId, Object payload) {
    try {
      String base = type.substring(0, type.lastIndexOf("."));
      String version = type.substring(type.lastIndexOf(".")+1);
      Envelope<Object> env = Envelope.of(base, version, orderId, orderId, payload);
      byte[] b = json.writeValueAsBytes(env);
      kafka.send(type, orderId, b); // key by correlationId to keep order per saga
    } catch (Exception e) { throw new RuntimeException(e); }
  }

  public record OrderCreated(String orderId, String sku, int qty) {}
  @Entity static class OrderEntity { @Id String id; String status; String sku; int qty;
    OrderEntity(){} OrderEntity(String id,String st,String sku,int qty){this.id=id;this.status=st;this.sku=sku;this.qty=qty;}
  }
}
```

### Inventory Service (reserve or reject; compensate on payment failure)

```java
@Service
public class InventoryService {
  private final KafkaTemplate<String, byte[]> kafka;
  private final ObjectMapper json = new ObjectMapper();
  private final EntityManager em;

  public InventoryService(KafkaTemplate<String, byte[]> kafka, EntityManager em) { this.kafka = kafka; this.em = em; }

  // Idempotent Inbox (conceptual): table processed(messageId)
  private boolean seen(String messageId) { return false; }

  @KafkaListener(topics = "orders.order.created.v1", groupId = "inventory")
  @Transactional
  public void onOrderCreated(byte[] bytes) throws Exception {
    var env = json.readValue(bytes, new com.fasterxml.jackson.core.type.TypeReference<Envelope<OrderCreated>>(){});
    if (seen(env.messageId())) return;
    String orderId = env.payload().orderId();
    var stock = em.find(Stock.class, env.payload().sku());
    if (stock == null || stock.available < env.payload().qty()) {
      publish("inventory.reservation.rejected.v1", env.correlationId(),
          Map.of("orderId", orderId, "reason", "INSUFFICIENT_STOCK"));
      return;
    }
    stock.available -= env.payload().qty(); em.merge(stock);
    publish("inventory.reserved.v1", env.correlationId(), Map.of("orderId", orderId));
  }

  @KafkaListener(topics = "payment.authorization.failed.v1", groupId = "inventory")
  @Transactional
  public void onPaymentFailed(byte[] bytes) throws Exception {
    var env = json.readValue(bytes, new com.fasterxml.jackson.core.type.TypeReference<Envelope<Map<String,Object>>>(){});
    String orderId = (String) env.payload().get("orderId");
    // release reservation (idempotent)
    releaseReservation(orderId);
    publish("inventory.released.v1", env.correlationId(), Map.of("orderId", orderId));
  }

  private void releaseReservation(String orderId) {/* look up reserved items and add back */ }

  private void publish(String type, String corr, Object payload) {
    try {
      String base = type.substring(0, type.lastIndexOf("."));
      String version = type.substring(type.lastIndexOf(".")+1);
      Envelope<Object> env = Envelope.of(base, version, corr, corr, payload);
      byte[] b = json.writeValueAsBytes(env);
      kafka.send(type, corr, b);
    } catch (Exception e) { throw new RuntimeException(e); }
  }

  public record OrderCreated(String orderId, String sku, int qty) {}
  @Entity static class Stock { @Id String sku; int available; }
}
```

### Payment Service (authorize or fail; compensates via refund if needed)

```java
@Service
public class PaymentService {
  private final KafkaTemplate<String, byte[]> kafka;
  private final ObjectMapper json = new ObjectMapper();

  public PaymentService(KafkaTemplate<String, byte[]> kafka) { this.kafka = kafka; }

  @KafkaListener(topics = {"inventory.reserved.v1"}, groupId = "payment")
  public void onInventoryReserved(byte[] bytes) throws Exception {
    var env = json.readValue(bytes, new com.fasterxml.jackson.core.type.TypeReference<Envelope<Map<String,Object>>>(){});
    String orderId = (String) env.payload().get("orderId");
    // call PSP (idempotent using orderId as idempotency key)
    boolean ok = charge(orderId);
    if (ok)
      publish("payment.authorization.succeeded.v1", env.correlationId(), Map.of("orderId", orderId, "authCode", "OK123"));
    else
      publish("payment.authorization.failed.v1", env.correlationId(), Map.of("orderId", orderId, "reason", "DECLINED"));
  }

  @KafkaListener(topics = {"shipping.shipment.failed.v1"}, groupId = "payment")
  public void onShipmentFailed(byte[] bytes) throws Exception {
    var env = json.readValue(bytes, new com.fasterxml.jackson.core.type.TypeReference<Envelope<Map<String,Object>>>(){});
    refund((String) env.payload().get("orderId")); // idempotent refund
    publish("payment.refunded.v1", env.correlationId(), Map.of("orderId", env.payload().get("orderId")));
  }

  private boolean charge(String orderId) { return true; }
  private void refund(String orderId) { /* no-op if already refunded */ }

  private void publish(String type, String corr, Object payload) {
    try {
      String base = type.substring(0, type.lastIndexOf("."));
      String version = type.substring(type.lastIndexOf(".")+1);
      Envelope<Object> env = Envelope.of(base, version, corr, corr, payload);
      byte[] b = json.writeValueAsBytes(env);
      kafka.send(type, corr, b);
    } catch (Exception e) { throw new RuntimeException(e); }
  }
}
```

### Shipping Service (create shipment or fail; completes saga or triggers refunds)

```java
@Service
public class ShippingService {
  private final KafkaTemplate<String, byte[]> kafka;
  private final ObjectMapper json = new ObjectMapper();

  public ShippingService(KafkaTemplate<String, byte[]> kafka) { this.kafka = kafka; }

  @KafkaListener(topics = "payment.authorization.succeeded.v1", groupId = "shipping")
  public void onPaid(byte[] bytes) throws Exception {
    var env = json.readValue(bytes, new com.fasterxml.jackson.core.type.TypeReference<Envelope<Map<String,Object>>>(){});
    String orderId = (String) env.payload().get("orderId");
    boolean ok = createShipment(orderId);
    if (ok)
      publish("shipping.shipment.created.v1", env.correlationId(), Map.of("orderId", orderId, "tracking", "TRK123"));
    else
      publish("shipping.shipment.failed.v1", env.correlationId(), Map.of("orderId", orderId, "reason", "NO_CARRIER"));
  }

  private boolean createShipment(String orderId) { return true; }

  private void publish(String type, String corr, Object payload) {
    try {
      String base = type.substring(0, type.lastIndexOf("."));
      String version = type.substring(type.lastIndexOf(".")+1);
      Envelope<Object> env = Envelope.of(base, version, corr, corr, payload);
      byte[] b = json.writeValueAsBytes(env);
      kafka.send(type, corr, b);
    } catch (Exception e) { throw new RuntimeException(e); }
  }
}
```

### Order Cancellation on Early Failure (e.g., stock rejection)

```java
@Service
public class OrderCancellation {
  private final KafkaTemplate<String, byte[]> kafka;
  private final ObjectMapper json = new ObjectMapper();

  public OrderCancellation(KafkaTemplate<String, byte[]> kafka) { this.kafka = kafka; }

  @KafkaListener(topics = "inventory.reservation.rejected.v1", groupId = "order-cancel")
  public void onReject(byte[] bytes) throws Exception {
    var env = json.readValue(bytes, new com.fasterxml.jackson.core.type.TypeReference<Envelope<Map<String,Object>>>(){});
    String orderId = (String) env.payload().get("orderId");
    publish("orders.order.canceled.v1", env.correlationId(), Map.of("orderId", orderId, "reason", "INVENTORY"));
  }

  private void publish(String type, String corr, Object payload) {
    String base = type.substring(0, type.lastIndexOf("."));
    String version = type.substring(type.lastIndexOf(".")+1);
    try {
      Envelope<Object> env = Envelope.of(base, version, corr, corr, payload);
      kafka.send(type, corr, new ObjectMapper().writeValueAsBytes(env));
    } catch (Exception e) { throw new RuntimeException(e); }
  }
}
```

> Production hardening: use **Transactional Outbox** to write events, **Inbox + Idempotent Receiver** for consumers (e.g., Redis `SETNX` or DB unique constraint on `messageId`), retry/DLQ policies, and **schema registry**.

---

## Known Uses

-   **E-commerce checkout:** inventory reservation → payment authorization → shipment; cancel/refund on failures.
    
-   **Travel booking:** seat/room hold → payment → ticket/confirmation; release hold or refund if a step fails.
    
-   **Telecom provisioning:** allocate number → configure network → activate plan; rollback via de-provisioning.
    
-   **FinTech flows:** multi-step KYC or transfer pipelines with reversal events.
    

## Related Patterns

-   **Orchestrated Saga / Process Manager:** Central coordinator alternative when you need explicit control/visibility.
    
-   **Transactional Outbox & Inbox:** Reliable publication/consumption foundations for saga events.
    
-   **Idempotent Receiver:** Required for exactly-once **effects** amid at-least-once delivery.
    
-   **Correlation Identifier:** Tie all saga events to the same `correlationId` (often the `orderId`).
    
-   **Compensating Transaction:** Define reversible actions for each step.
    
-   **Message Router / Publish–Subscribe Channel:** Transport/flow building blocks for event fan-out.
    
-   **Change Data Capture (CDC):** Sometimes used to generate events from DB changes; prefer Outbox for **intent** events.
    

> **Punchline:** Choreography Saga embraces autonomy—each service dances to domain events, advancing or compensating the flow. The cost is discipline in contracts, idempotency, and observability.

