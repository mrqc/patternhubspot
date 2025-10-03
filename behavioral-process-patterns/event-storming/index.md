# Event Storming — Behavioral / Process Pattern

## Pattern Name and Classification

**Event Storming** — *Collaborative modeling & discovery* pattern/workshop for **rapidly exploring a domain** via **domain events** and visual flows that uncover aggregates, commands, policies, external systems, and bounded contexts.

---

## Intent

Enable cross-functional teams (business + dev + UX + ops) to **learn a domain fast**, map **how things actually happen**, surface **hotspots** and **ambiguities**, and derive a **shared language** and **initial architecture** (contexts, aggregates, workflows) by placing **events first**.

---

## Also Known As

-   **Big Picture Event Storming** (end-to-end)

-   **Process/Design Level Event Storming** (deep-dive into a flow)

-   **Value Stream/Event Modeling** (closely related practices)


---

## Motivation (Forces)

-   Specs are incomplete; tribal knowledge is scattered.

-   We need **alignment** and a **ubiquitous language** before committing to design.

-   Traditional requirements capture misses **exceptions**, **policies**, and **integration points**.

-   We must identify **bounded contexts** and **aggregates** that preserve **invariants**.


Tensions: keeping the workshop fast & visual vs. the urge to jump into solutions; balancing breadth (big picture) and depth (design level).

---

## Applicability

Use Event Storming when:

-   Starting a new product, re-platforming, or untangling a legacy process.

-   Defining **bounded contexts** for DDD and integration contracts.

-   Discovering **events, commands, policies, read models**, and **UX steps**.


Avoid/limit when:

-   The domain is trivial, or you already have a validated model and ubiquitous language.

-   Stakeholders cannot participate or give time—then you’ll miss the point.


---

## Structure

```mathematica
(Orange) Domain Events: "OrderPlaced", "PaymentCaptured", "ShipmentCreated"
(Blue)   Commands:      "PlaceOrder", "CapturePayment"
(Yellow) Policies:      "When OrderPlaced then CapturePayment"
(Pink)   Hotspots:      "Tax rules?", "SLA?"
(Purple) External Sys:  "PSP", "WMS"
(Green)  Read Models / UI: "Order Details View"

Timeline  ──────────────────────────────────────────▶
Contexts  [ Sales ]        [ Payments ]            [ Fulfillment ]
Aggregates    Order              Invoice/Charge         Shipment
```

---

## Participants

-   **Facilitator** – guides the workshop & notation.

-   **Domain Experts** – narrate reality, provide vocabulary and exceptions.

-   **Engineers/Analysts/UX** – challenge, capture rules, map systems.

-   **Artifacts** – sticky notes by color (events, commands, policies, hotspots, external systems, views).


---

## Collaboration

1.  Start with **events** (“What happened?”) and place them on a **timeline**.

2.  Insert **commands** that caused events, and connect to **aggregates** enforcing invariants.

3.  Add **policies** (“when X then Y”), **read models**, and **external systems**.

4.  Group notes into **bounded contexts**; name aggregates; capture **hotspots** to research.

5.  Derive **APIs, contracts, tests**, and a **walking skeleton** from the board.


---

## Consequences

**Benefits**

-   Rapid **shared understanding** and a **ubiquitous language**.

-   Exposes **edge cases**, **policies**, **SLAs**, and **integration points**.

-   Clear path to **bounded contexts** and **aggregate** boundaries.

-   Produces artifacts that map directly to **events, commands, and handlers** in code.


**Liabilities**

-   Requires focused facilitation and stakeholder time.

-   Can feel “unstructured” to teams new to visual modeling.

-   Outputs still need **formalization** (diagrams, specs, code, tests).


---

## Implementation (Key Points)

-   Run **Big Picture** first; follow with **Design Level** sessions for critical flows.

-   Keep notes **verb-noun past tense** for events (“PaymentCaptured”), **imperative** for commands (“CapturePayment”).

-   Use **colors consistently** and mark **hotspots** aggressively.

-   From the board, extract: **event types**, **commands**, **aggregates**, **policies (process managers)**, **read models**, **integration adapters**.

-   Turn events into **contracts** (schemas), back by a **testable event log**.

-   Validate flows with **example mapping** and **end-to-end tests**.


---

## Sample Code (Java 17) — From Board to Running Skeleton

> The code demonstrates how outputs of an Event Storming session become **events**, **commands**, **aggregates**, and a **policy (process manager)** that reacts to events and issues commands.  
> Scenario: *OrderPlaced → capture payment → on success → create shipment*.

```java
// ===== 1) Contracts: Commands & Events (from the wall) =====
sealed interface Command permits PlaceOrder, CapturePayment, CreateShipment {}
sealed interface DomainEvent permits OrderPlaced, PaymentCaptured, PaymentFailed, ShipmentCreated {}

record PlaceOrder(String orderId, String customerId, int amountCents) implements Command {}
record CapturePayment(String orderId, int amountCents) implements Command {}
record CreateShipment(String orderId) implements Command {}

record OrderPlaced(String orderId, String customerId, int amountCents) implements DomainEvent {}
record PaymentCaptured(String orderId, String paymentId) implements DomainEvent {}
record PaymentFailed(String orderId, String reason) implements DomainEvent {}
record ShipmentCreated(String orderId, String tracking) implements DomainEvent {}

// ===== 2) Simple Event Bus & Command Bus =====
interface EventBus { void publish(DomainEvent e); void subscribe(Class<? extends DomainEvent> type, java.util.function.Consumer<DomainEvent> h); }
interface CommandBus { void dispatch(Command c); }

final class SimpleEventBus implements EventBus {
  private final java.util.Map<Class<?>, java.util.List<java.util.function.Consumer<DomainEvent>>> map = new java.util.concurrent.ConcurrentHashMap<>();
  @Override public void publish(DomainEvent e) { map.getOrDefault(e.getClass(), java.util.List.of()).forEach(h -> h.accept(e)); }
  @Override public void subscribe(Class<? extends DomainEvent> type, java.util.function.Consumer<DomainEvent> h) {
    map.computeIfAbsent(type, k -> new java.util.concurrent.CopyOnWriteArrayList<>()).add(h);
  }
}

// ===== 3) Aggregates (enforce invariants) =====
final class OrderAggregate {
  enum Status { NEW, PAID, SHIPPED }
  private final EventBus events;
  OrderAggregate(EventBus events) { this.events = events; }

  void handle(PlaceOrder cmd) {
    // invariants: amount > 0, etc.
    if (cmd.amountCents() <= 0) throw new IllegalArgumentException("amount must be > 0");
    events.publish(new OrderPlaced(cmd.orderId(), cmd.customerId(), cmd.amountCents()));
  }
}

final class PaymentsAggregate {
  private final EventBus events;
  PaymentsAggregate(EventBus events) { this.events = events; }

  void handle(CapturePayment cmd) {
    // pretend to call PSP; guarantee idempotency in real life
    if (cmd.amountCents() >= 0) {
      String paymentId = "pay_" + Math.abs(cmd.orderId().hashCode());
      events.publish(new PaymentCaptured(cmd.orderId(), paymentId));
    } else {
      events.publish(new PaymentFailed(cmd.orderId(), "invalid amount"));
    }
  }
}

final class ShippingAggregate {
  private final EventBus events;
  ShippingAggregate(EventBus events) { this.events = events; }
  void handle(CreateShipment cmd) {
    String tracking = "trk_" + Math.abs(cmd.orderId().hashCode());
    events.publish(new ShipmentCreated(cmd.orderId(), tracking));
  }
}

// ===== 4) Policy / Process Manager (from yellow sticky notes) =====
// "When OrderPlaced then CapturePayment; When PaymentCaptured then CreateShipment;
//  When PaymentFailed then (notify / compensate)"
final class CheckoutPolicy {
  CheckoutPolicy(EventBus events, CommandBus commands) {
    events.subscribe(OrderPlaced.class, e -> {
      var ev = (OrderPlaced) e;
      commands.dispatch(new CapturePayment(ev.orderId(), ev.amountCents()));
    });
    events.subscribe(PaymentCaptured.class, e -> {
      var ev = (PaymentCaptured) e;
      commands.dispatch(new CreateShipment(ev.orderId()));
    });
    events.subscribe(PaymentFailed.class, e -> {
      var ev = (PaymentFailed) e;
      System.err.println("ALERT: Payment failed for " + ev.orderId() + " reason=" + ev.reason());
    });
  }
}

// ===== 5) A tiny in-memory CommandBus wiring aggregates =====
final class SimpleCommandBus implements CommandBus {
  private final OrderAggregate order;
  private final PaymentsAggregate payments;
  private final ShippingAggregate shipping;

  SimpleCommandBus(OrderAggregate o, PaymentsAggregate p, ShippingAggregate s) { this.order = o; this.payments = p; this.shipping = s; }

  @Override public void dispatch(Command c) {
    switch (c) {
      case PlaceOrder po -> order.handle(po);
      case CapturePayment cp -> payments.handle(cp);
      case CreateShipment cs -> shipping.handle(cs);
      default -> throw new IllegalArgumentException("Unknown command " + c);
    }
  }
}

// ===== 6) Read Model / Projection (green notes) =====
final class OrderProjection {
  static final class View { final String id; String status="NEW"; String paymentId=null; String tracking=null; View(String id){this.id=id;} }
  private final java.util.Map<String, View> store = new java.util.concurrent.ConcurrentHashMap<>();
  OrderProjection(EventBus events) {
    events.subscribe(OrderPlaced.class, e -> store.put(((OrderPlaced)e).orderId(), new View(((OrderPlaced)e).orderId())));
    events.subscribe(PaymentCaptured.class, e -> store.computeIfPresent(((PaymentCaptured)e).orderId(), (k,v) -> { v.status="PAID"; v.paymentId=((PaymentCaptured)e).paymentId(); return v; }));
    events.subscribe(ShipmentCreated.class, e -> store.computeIfPresent(((ShipmentCreated)e).orderId(), (k,v) -> { v.status="SHIPPED"; v.tracking=((ShipmentCreated)e).tracking(); return v; }));
  }
  java.util.Optional<View> get(String id) { return java.util.Optional.ofNullable(store.get(id)); }
}

// ===== 7) Demo: the "walking skeleton" derived from the workshop =====
public class EventStormingDemo {
  public static void main(String[] args) {
    var eventBus = new SimpleEventBus();
    var orderAgg = new OrderAggregate(eventBus);
    var paymentsAgg = new PaymentsAggregate(eventBus);
    var shippingAgg = new ShippingAggregate(eventBus);
    var commandBus = new SimpleCommandBus(orderAgg, paymentsAgg, shippingAgg);

    // policies & projections
    new CheckoutPolicy(eventBus, commandBus);
    var readModel = new OrderProjection(eventBus);

    // start the flow
    String orderId = "o-1001";
    commandBus.dispatch(new PlaceOrder(orderId, "c-42", 2599));

    // observe the read model
    readModel.get(orderId).ifPresent(v ->
      System.out.println("Order " + v.id + " status=" + v.status + " paymentId=" + v.paymentId + " tracking=" + v.tracking)
    );
  }
}
```

**What this shows**

-   Orange notes → **events**; blue notes → **commands**; yellow notes → **policy**; green notes → **read model**.

-   Aggregates encapsulate rules; the policy coordinates cross-aggregate flow exactly as discovered in the workshop.

-   This “walking skeleton” can be expanded with persistence, messaging, idempotency, and real integrations.


---

## Known Uses

-   Popularized by **Alberto Brandolini**; used by teams at startups and enterprises to kick-off products, split **bounded contexts**, and design **event-driven** or DDD systems.

-   Frequently paired with **example mapping**, **DDD tactical patterns**, and **event-first** documentation.


---

## Related Patterns

-   **Domain Events** — the primary artifacts you model first.

-   **Saga / Process Manager** — policies that coordinate long-running flows.

-   **CQRS** — natural separation into write (commands/aggregates) and read (projections).

-   **Event Sourcing** — persist events as the source of truth.

-   **Context Mapping (DDD)** — derive bounded contexts and integrations from the big picture workshop.
