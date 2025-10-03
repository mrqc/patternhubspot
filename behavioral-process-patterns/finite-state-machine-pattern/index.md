# Finite State Machine — Behavioral / Process Pattern

## Pattern Name and Classification

**Finite State Machine (FSM)** — *Behavioral / Process* pattern for modeling a system with a **finite set of states**, **events**, **transitions** (optionally with **guards** and **actions**), and **deterministic behavior**.

---

## Intent

Represent business processes and protocol flows as **explicit states** and **event-driven transitions** so logic becomes **predictable, verifiable, and testable**, with clear rules for **what can happen next**.

---

## Also Known As

-   **State Machine**

-   **State Transition System**

-   **Automaton**


---

## Motivation (Forces)

-   Complex “if/else” or flag-based flows become brittle and ambiguous.

-   Business rules often depend on **current status** (e.g., `NEW → PAID → SHIPPED`).

-   Need **determinism**, **auditability**, and **easy visualization** (state diagrams).

-   Require **guards** (preconditions) and **actions** (effects) bound to transitions.


Trade-offs:

-   Over-modeling trivial flows adds ceremony; poor partitioning can cause state explosion.

-   Evolution requires **careful migration** of persisted state.


---

## Applicability

Use an FSM when:

-   The domain has **clearly defined statuses** and **allowed steps**.

-   You must **validate transitions** and **enforce invariants**.

-   You need **time-based** or **event-based** transitions (timeouts, external events).


Avoid when:

-   Behavior is purely combinatorial (no concept of evolving state), or a simple strategy/policy suffices.


---

## Structure

```css
States:      S = { NEW, PAID, FULFILLING, SHIPPED, CANCELLED }
Events:      E = { Pay, AllocateStock, Ship, Cancel }
Transition:  (state, event) --[guard]/action--> nextState
```

-   **Guard**: boolean predicate that must hold for the transition.

-   **Action**: side-effect executed atomically with state change.

-   **Entry/Exit hooks**: optional actions on entering/leaving a state.


---

## Participants

-   **State** — enumerated statuses.

-   **Event** — external trigger or internal timer.

-   **Transition Table** — mapping `(state, event) → (guard, action, nextState)`.

-   **Context** — data required by guards/actions (order totals, roles, timestamps).

-   **Engine** — evaluates guards, executes actions, updates state atomically.


---

## Collaboration

1.  An **event** arrives while the machine is in `currentState`.

2.  Engine finds a matching **transition**, evaluates **guard** with **context**.

3.  If guard passes → run **action** → move to **nextState**; else reject.

4.  Emits **domain events/logs**; subsequent events see the **new state**.


---

## Consequences

**Benefits**

-   **Clarity**: legal/illegal transitions are explicit.

-   **Safety**: guards enforce invariants; fewer impossible states.

-   **Testability**: transition table can be unit-tested exhaustively.

-   **Observability**: easy to audit and visualize.


**Liabilities**

-   Potential **state explosion** if states encode orthogonal concerns (split into sub-machines).

-   Requires **migration**/compatibility when states change in production.

-   Extra plumbing compared to ad-hoc `if/else`.


---

## Implementation (Key Points)

-   Represent states/events with **enums**; keep **context** separate.

-   Use a **transition table** (map) or a declarative **builder DSL**.

-   Support **guards** (Predicates) and **actions** (Consumers).

-   Ensure **atomicity** (persist state and side effects together, or use outbox).

-   Add **timeouts** with scheduled events.

-   Emit **domain events** after successful transitions; log rejections with reasons.

-   Prefer **orthogonal sub-machines** over giant monoliths (e.g., Payment FSM, Shipping FSM).


---

## Sample Code (Java 17) — Minimal, Table-Driven FSM with Guards & Actions

> Scenario: Order lifecycle: `NEW → PAID → FULFILLING → SHIPPED` or `CANCELLED`.  
> Guards prevent cancelling after shipment; actions simulate side effects.

```java
import java.util.*;
import java.util.function.*;

// --- Domain enums ---
enum OrderState { NEW, PAID, FULFILLING, SHIPPED, CANCELLED }
enum OrderEvent { PAY, ALLOCATE_STOCK, SHIP, CANCEL }

// --- Context passed to guards/actions ---
final class OrderCtx {
  final String orderId;
  int amountCents;
  boolean stockAllocated;
  boolean refundIssued;

  OrderCtx(String orderId, int amountCents) {
    this.orderId = orderId; this.amountCents = amountCents;
  }
}

// --- Transition model ---
record Transition<S,E,C>(
    S from, E on,
    Predicate<C> guard,
    BiConsumer<C, S> action,
    S to
) {}

// --- FSM Engine ---
final class StateMachine<S,E,C> {
  private final Map<S, Map<E, Transition<S,E,C>>> table = new EnumMap<>(OrderState.class);
  private S state;

  StateMachine(S initial) { this.state = initial; }

  public StateMachine<S,E,C> add(Transition<S,E,C> t) {
    table.computeIfAbsent(t.from(), k -> new EnumMap<>(OrderEvent.class)).put(t.on(), t);
    return this;
  }

  public synchronized S fire(E event, C ctx) {
    var byEvent = Optional.ofNullable(table.get(state))
        .orElseThrow(() -> new IllegalStateException("No transitions from " + state));
    var t = Optional.ofNullable(byEvent.get(event))
        .orElseThrow(() -> new IllegalStateException("Illegal event " + event + " from " + state));
    if (!t.guard().test(ctx))
      throw new IllegalStateException("Guard blocked: " + event + " from " + state);
    // action + state change (here atomic in-memory; persist together in real life)
    t.action().accept(ctx, state);
    state = t.to();
    return state;
  }

  public S state() { return state; }
}

// --- Wiring the order FSM ---
final class OrderFsmFactory {

  static StateMachine<OrderState,OrderEvent,OrderCtx> build() {
    var fsm = new StateMachine<OrderState,OrderEvent,OrderCtx>(OrderState.NEW);

    // Helpers
    Predicate<OrderCtx> always = c -> true;
    BiConsumer<OrderCtx, OrderState> noop = (c, s) -> {};

    // Transitions
    fsm.add(new Transition<>(OrderState.NEW, OrderEvent.PAY,
        c -> c.amountCents > 0,
        (c, s) -> log("Payment captured for " + c.orderId),
        OrderState.PAID));

    fsm.add(new Transition<>(OrderState.PAID, OrderEvent.ALLOCATE_STOCK,
        c -> !c.stockAllocated,
        (c, s) -> { c.stockAllocated = true; log("Stock allocated for " + c.orderId); },
        OrderState.FULFILLING));

    fsm.add(new Transition<>(OrderState.FULFILLING, OrderEvent.SHIP,
        c -> c.stockAllocated,
        (c, s) -> log("Shipment created for " + c.orderId),
        OrderState.SHIPPED));

    // Cancellation rules
    fsm.add(new Transition<>(OrderState.NEW, OrderEvent.CANCEL,
        always,
        (c, s) -> log("Order " + c.orderId + " cancelled before payment"),
        OrderState.CANCELLED));

    fsm.add(new Transition<>(OrderState.PAID, OrderEvent.CANCEL,
        c -> !c.stockAllocated,
        (c, s) -> { c.refundIssued = true; log("Refund issued for " + c.orderId); },
        OrderState.CANCELLED));

    // Disallow cancel after fulfillment/shipment by omitting transitions

    return fsm;
  }

  private static void log(String msg) { System.out.println("[FSM] " + msg); }
}

// --- Demo ---
public class FsmDemo {
  public static void main(String[] args) {
    var ctx = new OrderCtx("o-1001", 2599);
    var fsm = OrderFsmFactory.build();

    System.out.println("Start: " + fsm.state());                 // NEW
    fsm.fire(OrderEvent.PAY, ctx);                               // → PAID
    System.out.println("Now: " + fsm.state());

    fsm.fire(OrderEvent.ALLOCATE_STOCK, ctx);                    // → FULFILLING
    fsm.fire(OrderEvent.SHIP, ctx);                              // → SHIPPED
    System.out.println("End: " + fsm.state());

    // Illegal transition example (throws):
    try {
      fsm.fire(OrderEvent.CANCEL, ctx);                          // no transition from SHIPPED
    } catch (IllegalStateException ex) {
      System.out.println("Rejected: " + ex.getMessage());
    }
  }
}
```

### Notes & Extensions

-   Add **entry/exit** hooks by wrapping transitions or by a `StateListener`.

-   Persist state + side effects **atomically** (DB tx + outbox for events).

-   For **timeouts**, schedule synthetic events (e.g., `PAYMENT_TIMEOUT`).

-   For **reactive** systems, return `Mono<S>` from `fire` and make actions async.

-   Split concerns into **sub-machines** (Payment FSM, Shipment FSM) and coordinate via events (Saga/Process Manager).


---

## Known Uses

-   Order/fulfillment workflows; approval processes; user onboarding; subscription renewals.

-   Protocols: **TCP**, **HTTP parsers**, **OAuth** flows, **SIP**/telecom signaling.

-   UI wizards and device control systems (IoT, embedded).


---

## Related Patterns

-   **State (GoF)** — object-per-state variant; FSM is the abstract model (often realized with State objects).

-   **Saga / Process Manager** — coordinates multiple FSMs across services via events.

-   **Workflow / BPMN** — higher-level orchestration; FSM can be the execution core.

-   **Guard / Policy** — guard predicates encapsulate policy checks.

-   **Event Sourcing** — persist transitions as events; rebuild state by replay.
