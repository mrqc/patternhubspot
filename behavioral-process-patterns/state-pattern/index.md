# State — Behavioral / Process Pattern

## Pattern Name and Classification

**State** — *Behavioral / Process* pattern that lets an object **alter its behavior when its internal state changes**; the object appears to change its class.

---

## Intent

Represent **state-dependent behavior** as separate **State objects**. The **Context** forwards requests to the current State, which can **handle** them and **transition** the Context to a new State.

---

## Also Known As

-   **Objects for States**

-   **State Objects**

-   (Related but different from) **Finite State Machine** — FSM is the model; State is an OO realization.


---

## Motivation (Forces)

-   Conditional logic like `if (status == PAID) { … } else if (status == …)` spreads across the codebase and becomes fragile.

-   Behavior varies **by state**, not just data (e.g., what “cancel” means in `NEW` vs `PAID`).

-   We want to add a new state without changing many `switch`/`if` statements (**Open/Closed Principle**).


**Trade-offs**

-   More classes (one per state) and indirection.

-   Transitions must be explicit to avoid “state explosion” or hidden coupling.


---

## Applicability

Use State when:

-   An object’s behavior depends on **current state**, and it must **change at runtime**.

-   There are **well-defined** states and **allowed transitions**.

-   You want to **localize** state-specific code and avoid repeated conditionals.


Avoid when:

-   There are only 2–3 trivial states and a single place that branches; a simple conditional is clearer.

-   State changes are purely data flags without behavior differences.


---

## Structure

```pgsql
+----------------------+
                     |      Context         |
                     |  - state: State     |
requests ───────────▶|  + setState(s)      |
                     |  + operation() ─────┼─────► delegates to current State
                     +----------------------+
                                 ▲
                                 │ has-a
                         +-------+--------+
                         |    State       |  (interface/abstract)
                         | + handleA()    |
                         | + handleB()    |
                         +-------+--------+
                                 ▲
                    ┌────────────┴────────────┐
               ConcreteState1           ConcreteState2
             (defines behavior &       (defines behavior &
              transitions to next)      transitions to next)
```

---

## Participants

-   **Context** — holds a reference to the **current State** and delegates requests.

-   **State** — interface/abstract type declaring state-dependent operations.

-   **Concrete States** — implement behavior for that state and decide **transitions** by calling `context.setState(...)`.

-   (Optional) **Entry/Exit hooks** — actions when entering/leaving a state.


---

## Collaboration

1.  Client calls a **Context** method (e.g., `cancel()` on an Order).

2.  Context **delegates** to its current **State**.

3.  The State performs state-specific work and may **transition** the Context to a new State.

4.  Client code stays **unchanged** as behavior evolves.


---

## Consequences

**Benefits**

-   Removes large conditional blocks; **state logic is localized**.

-   **Open/Closed**: add a new state by adding a class, not editing all callers.

-   Transitions are **explicit** and testable.


**Liabilities**

-   **More classes/objects** to manage.

-   Transitions scattered across states can be hard to get a **global view** (consider a diagram/tests).


---

## Implementation (Key Points)

-   Keep the **Context** small; it only delegates and holds shared data.

-   Let **States own transitions** (they know what comes next).

-   Represent **illegal operations** explicitly (exception) or as no-ops, but be consistent.

-   Consider **entry/exit** callbacks for side effects.

-   If you need a summary view and validations, combine with an **FSM diagram** or tests that verify legal transitions.


---

## Sample Code (Java 17) — Order workflow with explicit State objects

> States: `NEW → PAID → FULFILLING → SHIPPED`, with `CANCELLED` as a terminal alternative.  
> Operations: `pay()`, `allocateStock()`, `ship()`, `cancel()`.  
> Each state defines what’s legal and where to go next.

```java
// ===== Shared domain model carried by the Context =====
final class OrderData {
  final String orderId;
  int amountCents;
  boolean stockAllocated;
  boolean refundIssued;
  String tracking;

  OrderData(String orderId, int amountCents) {
    this.orderId = orderId; this.amountCents = amountCents;
  }
}

// ===== State SPI =====
interface OrderState {
  String name();
  void onEnter(Order ctx);                      // optional hook

  void pay(Order ctx);
  void allocateStock(Order ctx);
  void ship(Order ctx);
  void cancel(Order ctx);

  default RuntimeException illegal(String op) {
    return new IllegalStateException("Operation '" + op + "' is illegal in state " + name());
  }
}

// ===== Context =====
final class Order {
  private OrderState state;
  final OrderData data;

  Order(String id, int amountCents) {
    this.data = new OrderData(id, amountCents);
    setState(new NewState());                   // initial state
  }

  void setState(OrderState next) {
    this.state = next;
    next.onEnter(this);
  }

  String state() { return state.name(); }

  // API exposed to clients; delegate to current state
  public void pay()            { state.pay(this); }
  public void allocateStock()  { state.allocateStock(this); }
  public void ship()           { state.ship(this); }
  public void cancel()         { state.cancel(this); }

  // helpers for side effects (logging, integrations)
  void log(String msg){ System.out.println("[Order " + data.orderId + "] " + msg); }
}

// ===== Concrete States =====

final class NewState implements OrderState {
  @Override public String name() { return "NEW"; }
  @Override public void onEnter(Order ctx) { ctx.log("entered NEW"); }

  @Override public void pay(Order ctx) {
    if (ctx.data.amountCents <= 0) throw new IllegalStateException("amount must be > 0");
    ctx.log("payment captured");
    ctx.setState(new PaidState());
  }
  @Override public void allocateStock(Order ctx) { throw illegal("allocateStock"); }
  @Override public void ship(Order ctx)          { throw illegal("ship"); }

  @Override public void cancel(Order ctx) {
    ctx.log("cancelled before payment");
    ctx.setState(new CancelledState());
  }
}

final class PaidState implements OrderState {
  @Override public String name() { return "PAID"; }
  @Override public void onEnter(Order ctx) { ctx.log("entered PAID"); }

  @Override public void pay(Order ctx)            { throw illegal("pay"); }
  @Override public void allocateStock(Order ctx)  {
    ctx.data.stockAllocated = true;
    ctx.log("stock allocated");
    ctx.setState(new FulfillingState());
  }
  @Override public void ship(Order ctx)           { throw illegal("ship"); }

  @Override public void cancel(Order ctx) {
    if (ctx.data.stockAllocated) throw illegal("cancel after allocation");
    ctx.data.refundIssued = true;
    ctx.log("refunded and cancelled");
    ctx.setState(new CancelledState());
  }
}

final class FulfillingState implements OrderState {
  @Override public String name() { return "FULFILLING"; }
  @Override public void onEnter(Order ctx) { ctx.log("entered FULFILLING"); }

  @Override public void pay(Order ctx)            { throw illegal("pay"); }
  @Override public void allocateStock(Order ctx)  { throw illegal("allocateStock"); }
  @Override public void ship(Order ctx) {
    if (!ctx.data.stockAllocated) throw new IllegalStateException("no stock");
    ctx.data.tracking = "trk_" + Math.abs(ctx.data.orderId.hashCode());
    ctx.log("shipped with tracking " + ctx.data.tracking);
    ctx.setState(new ShippedState());
  }
  @Override public void cancel(Order ctx)         { throw illegal("cancel"); }
}

final class ShippedState implements OrderState {
  @Override public String name() { return "SHIPPED"; }
  @Override public void onEnter(Order ctx) { ctx.log("entered SHIPPED (terminal)"); }

  @Override public void pay(Order ctx)            { throw illegal("pay"); }
  @Override public void allocateStock(Order ctx)  { throw illegal("allocateStock"); }
  @Override public void ship(Order ctx)           { throw illegal("ship"); }
  @Override public void cancel(Order ctx)         { throw illegal("cancel"); }
}

final class CancelledState implements OrderState {
  @Override public String name() { return "CANCELLED"; }
  @Override public void onEnter(Order ctx) { ctx.log("entered CANCELLED (terminal)"); }

  @Override public void pay(Order ctx)            { throw illegal("pay"); }
  @Override public void allocateStock(Order ctx)  { throw illegal("allocateStock"); }
  @Override public void ship(Order ctx)           { throw illegal("ship"); }
  @Override public void cancel(Order ctx)         { /* idempotent no-op */ }
}

// ===== Demo =====
public class StatePatternDemo {
  public static void main(String[] args) {
    Order o = new Order("o-1001", 2599);
    System.out.println("State: " + o.state()); // NEW

    o.pay();                                   // NEW -> PAID
    System.out.println("State: " + o.state());

    o.allocateStock();                         // PAID -> FULFILLING
    System.out.println("State: " + o.state());

    o.ship();                                  // FULFILLING -> SHIPPED
    System.out.println("State: " + o.state());

    // Illegal operation example:
    try { o.cancel(); } catch (Exception e) {
      System.out.println("Expected: " + e.getMessage());
    }
  }
}
```

**Why this illustrates State**

-   All state-specific logic lives in **Concrete State classes**; the `Order` context contains **no conditionals** about state.

-   **Transitions** are explicit (`ctx.setState(new PaidState())`).

-   Adding a new state (e.g., `ON_HOLD`) means adding a class and wiring transitions—clients remain unchanged.


---

## Known Uses

-   UI widgets (buttons, text fields) with modes (`enabled/disabled/hover/focused`).

-   Protocol handlers and parsers (e.g., HTTP request parsing phases).

-   Workflow/status objects (documents, orders, tickets).

-   Game entities (idle, walking, attacking) with state-driven behavior.


---

## Related Patterns

-   **Finite State Machine** — complementary; use an FSM for a **global view/validation** and State objects for **OO encapsulation**.

-   **Strategy** — interchangeable algorithms; State is like Strategy + **internal transition** logic.

-   **Mediator / Process Manager** — coordinate multiple objects; State focuses on **one object’s** behavior.

-   **Observer** — notify others of state changes from `onEnter`/`onExit`.

-   **Memento** — capture/restore state snapshots (e.g., undo).
