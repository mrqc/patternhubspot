# Command — Behavioral / Process Pattern

## Pattern Name and Classification

**Command** — *Behavioral / Process* pattern that **encapsulates a request as an object**, letting you parameterize, queue, log, undo/redo, and compose operations decoupled from the caller.

---

## Intent

Turn an operation (method call) into a **first-class object** (`Command`) with `execute()` (and optionally `undo()`), so invokers can **schedule, queue, replay, audit, and reverse** actions without knowing receiver details.

---

## Also Known As

-   **Action**, **Transaction**

-   **Message / Task** (in command bus contexts)

-   **Operation**


---

## Motivation (Forces)

-   UI buttons/menus, schedulers, or workflow engines should **trigger actions** without hard-coding business logic.

-   Need **undo/redo**, **macro** operations, **audit trails**, or **retries**.

-   Asynchronous execution or **remote dispatch** (queue/bus) should be possible.

-   Avoids giant `switch` statements and keeps **open/closed** for new actions.


Trade-offs: more classes and lifecycle management for commands and history.

---

## Applicability

Use Command when you need:

-   **Undo/redo** (editor, e-commerce cart ops).

-   **Queueing / scheduling / retries** of tasks.

-   **Macro** commands (batch user actions).

-   Separation of **invoker** (button/controller) and **receiver** (domain).


Avoid when a simple direct call suffices and you don’t need history/queuing.

---

## Structure

```pgsql
Invoker ── executes ──> Command (execute, undo)
                           |
                        Receiver (does the work)
History (stacks) <─ tracks ──┘
CompositeCommand → executes many commands as one unit
```

---

## Participants

-   **Command**: interface with `execute()`; often `undo()`.

-   **ConcreteCommand**: wraps a receiver + parameters; implements execute/undo.

-   **Receiver**: domain object that performs the action.

-   **Invoker**: knows *when* to call `execute()` / `undo()`; keeps history.

-   **History**: stacks/queues for undo/redo, logging, retries.

-   **Composite/Macro** (optional): groups multiple commands.


---

## Collaboration

1.  Client configures a `ConcreteCommand` with a `Receiver` and parameters.

2.  Invoker calls `execute()`; the command delegates to the receiver.

3.  Invoker records the command in **undo stack**.

4.  `undo()` pops from undo → calls command’s `undo()`; optionally pushes to redo.

5.  Composite commands coordinate multiple child commands atomically (best-effort with inverse ops).


---

## Consequences

**Benefits**

-   Decouples **when/how** an action is triggered from **what** it does.

-   Enables **undo/redo**, **macro**, **queue/retry**, and **audit** easily.

-   Open/closed for new actions without changing invokers.


**Liabilities**

-   Extra classes/objects; must define **reversible semantics** for undo.

-   Undo for side-effectful operations may require **compensations** (not perfect inverse).


---

## Implementation (Key Points)

-   Keep commands **small & immutable** (capture parameters at creation).

-   For **undo**, store minimal inverse state (memento) or implement **compensation**.

-   Provide a **history** with two stacks: undo / redo.

-   Consider **CompositeCommand** for multi-step actions.

-   For async, commands can be **serializable** and executed by a **command bus** / queue.

-   Add **idempotency keys** if commands may be retried.


---

## Sample Code (Java 17) — Undo/Redo, Macro, Queue

```java
// ==== Command API ====
interface Command {
  String name();
  void execute();
  default void undo() { /* optional; no-op if not supported */ }
}

// ==== Domain (Receiver) ====
class OrderService {
  private final java.util.Map<String, String> orders = new java.util.concurrent.ConcurrentHashMap<>();
  void create(String id) { if (orders.putIfAbsent(id, "NEW") != null) throw new IllegalStateException("exists"); }
  void cancel(String id) { ensure(id); orders.put(id, "CANCELLED"); }
  void changeStatus(String id, String status) { ensure(id); orders.put(id, status); }
  String status(String id) { return orders.get(id); }
  private void ensure(String id) { if (!orders.containsKey(id)) throw new IllegalArgumentException("missing"); }
}

// ==== Concrete Commands (capture minimal inverse info for undo) ====
final class CreateOrder implements Command {
  private final OrderService svc; private final String id; private boolean executed;
  CreateOrder(OrderService svc, String id) { this.svc = svc; this.id = id; }
  public String name() { return "CreateOrder(" + id + ")"; }
  public void execute() { svc.create(id); executed = true; }
  public void undo() { if (executed) svc.changeStatus(id, "DELETED"); } // simplistic compensation
}

final class CancelOrder implements Command {
  private final OrderService svc; private final String id; private String prev;
  CancelOrder(OrderService svc, String id) { this.svc = svc; this.id = id; }
  public String name() { return "CancelOrder(" + id + ")"; }
  public void execute() { prev = svc.status(id); svc.cancel(id); }
  public void undo() { if (prev != null) svc.changeStatus(id, prev); }
}

final class ChangeStatus implements Command {
  private final OrderService svc; private final String id; private final String to;
  private String prev;
  ChangeStatus(OrderService svc, String id, String to) { this.svc = svc; this.id = id; this.to = to; }
  public String name() { return "ChangeStatus(" + id + " -> " + to + ")"; }
  public void execute() { prev = svc.status(id); svc.changeStatus(id, to); }
  public void undo() { if (prev != null) svc.changeStatus(id, prev); }
}

// ==== Composite (Macro) ====
final class Macro implements Command {
  private final java.util.List<Command> steps; private boolean executed;
  Macro(java.util.List<Command> steps) { this.steps = steps; }
  public String name() { return "Macro(" + steps.size() + " steps)"; }
  public void execute() {
    int i = 0;
    try {
      for (; i < steps.size(); i++) { steps.get(i).execute(); }
      executed = true;
    } catch (RuntimeException e) {
      // rollback already executed steps (reverse order)
      for (int j = i - 1; j >= 0; j--) try { steps.get(j).undo(); } catch (Exception ignore) {}
      throw e;
    }
  }
  public void undo() { if (executed) for (int i = steps.size()-1; i >= 0; i--) steps.get(i).undo(); }
}

// ==== Invoker with Undo/Redo and a simple async queue ====
final class CommandBus {
  private final java.util.Deque<Command> undo = new java.util.ArrayDeque<>();
  private final java.util.Deque<Command> redo = new java.util.ArrayDeque<>();
  private final java.util.concurrent.ExecutorService async = java.util.concurrent.Executors.newSingleThreadExecutor();

  public synchronized void execute(Command c) {
    c.execute();
    undo.push(c);
    redo.clear();
    System.out.println("EXEC: " + c.name());
  }

  public synchronized void undo() {
    if (undo.isEmpty()) { System.out.println("Nothing to undo"); return; }
    Command c = undo.pop();
    c.undo();
    redo.push(c);
    System.out.println("UNDO: " + c.name());
  }

  public synchronized void redo() {
    if (redo.isEmpty()) { System.out.println("Nothing to redo"); return; }
    Command c = redo.pop();
    c.execute();
    undo.push(c);
    System.out.println("REDO: " + c.name());
  }

  // Fire-and-forget async submit (no undo push; could extend with durable queue)
  public void submitAsync(Command c) {
    async.submit(() -> {
      try { execute(c); } catch (Exception e) { System.err.println("Async failed: " + c.name() + " -> " + e.getMessage()); }
    });
  }

  public void shutdown() { async.shutdownNow(); }
}

// ==== Demo ====
public class CommandDemo {
  public static void main(String[] args) {
    OrderService svc = new OrderService();
    CommandBus bus = new CommandBus();

    // 1) Simple commands
    bus.execute(new CreateOrder(svc, "o-1"));
    bus.execute(new ChangeStatus(svc, "o-1", "CONFIRMED"));
    bus.undo();         // back to previous status
    bus.redo();         // apply CONFIRMED again

    // 2) Macro (transaction-like batch with rollback on failure)
    Macro checkout = new Macro(java.util.List.of(
        new ChangeStatus(svc, "o-1", "PAID"),
        new ChangeStatus(svc, "o-1", "FULFILLING"),
        new ChangeStatus(svc, "o-1", "SHIPPED")
    ));
    bus.execute(checkout);
    bus.undo();         // undo macro → SHIPPED→FULFILLING→PAID undone in reverse

    // 3) Async submission
    bus.submitAsync(new CancelOrder(svc, "o-1"));

    // (wait a moment for async)
    try { Thread.sleep(100); } catch (InterruptedException ignored) {}
    bus.shutdown();
  }
}
```

**Notes**

-   `undo()` uses either **memento (previous state)** or **compensation** (best-effort inverse).

-   `Macro` ensures **all-or-nothing** semantics with rollback on failure.

-   `CommandBus` centralizes **history** and enables **async** execution.


---

## Known Uses

-   GUI frameworks (menu/toolbar actions with undo/redo).

-   **CQRS** command side; workflow engines/schedulers.

-   Editors/IDEs; transactional batches; macro automation; remote task queues.


---

## Related Patterns

-   **Memento** — capture prior state for undo.

-   **Composite** — macro commands (aggregate many commands).

-   **Invoker / Mediator** — command bus acting as mediator/router.

-   **Strategy** — interchangeable algorithms; often wrapped as commands to schedule.

-   **Observer/Event** — events may be emitted after command execution for read models.

-   **Saga / Compensation** — for multi-service undo (process-level, not local state).
