
# Command — GoF Behavioral Pattern

## Pattern Name and Classification

**Name:** Command  
**Category:** Behavioral design pattern

## Intent

Encapsulate a request as an object, thereby letting you parameterize clients with different requests, **queue** or **log** requests, support **undo/redo**, and compose macro operations.

## Also Known As

Action, Transaction, Message, Operation, Task

## Motivation (Forces)

-   You want to **decouple** the invoker (UI, scheduler, queue) from the receiver (domain object) and the action details.

-   You need **undo/redo** or **auditing**: each action and its inverse can be stored and replayed.

-   You want to **queue**, **defer**, **retry**, or **distribute** work (e.g., job queues).

-   You need to **compose** multiple actions into a single macro (batch).

-   You want a uniform way to **log** operations (event sourcing style) or **secure**/**authorize** them.


## Applicability

Use Command when:

-   The set of requests is open-ended and you want to add new operations without changing existing invokers.

-   You need **parameterizable** actions (data and behavior in one object).

-   You require **transactional behavior** (all-or-nothing via macro commands).

-   You plan to **queue**, **schedule**, or **remote** requests.

-   You must support **undo/redo** stacks.


## Structure

-   **Command** — interface with `execute()`; often `undo()` and metadata.

-   **ConcreteCommand** — binds a receiver and parameters; implements `execute()/undo()`.

-   **Receiver** — knows how to perform the work.

-   **Invoker** — triggers commands; may keep history for undo/redo.

-   **Client** — creates and wires commands (or a factory does).


```nginx
Client --> [Command] --> Receiver
             ^
             |
         Invoker (calls execute/undo; may queue)
```

## Participants

-   **Command**: declares the operation (and optionally inverse).

-   **ConcreteCommand**: implements `execute()` and `undo()` by calling the Receiver.

-   **Receiver**: contains business logic to carry out the request.

-   **Invoker**: asks the command to execute; may push to history/redo stacks.

-   **Client**: configures and injects receivers/parameters into commands.


## Collaboration

-   The Invoker holds a `Command` and calls `execute()`.

-   The Command delegates to the **Receiver**.

-   For undoable commands, the Invoker stores them in a **history**. `undo()` on the last command reverses the effect; `redo()` re-executes or replays a saved command.


## Consequences

**Benefits**

-   **Decoupling**: invokers don’t know receiver details.

-   **Open/Closed**: new commands without touching invokers.

-   **Undo/Redo** and **logging** become natural.

-   **Queuing/scheduling/remote** dispatch is straightforward.

-   Enables **macro** (composite) commands.


**Liabilities**

-   **More classes** (each action = one class/object).

-   **State capture** for undo can be non-trivial (may need Mementos or snapshots).

-   Poorly designed commands can **leak receiver details** or grow too chatty.


## Implementation

-   Decide the **inverse** strategy: explicit `undo()`, memento snapshot, or compensating action.

-   Keep commands **immutable** w.r.t. parameters where possible; store minimal state required for undo.

-   Consider **Composite** for macro commands; ensure atomic undo by reversing order.

-   Invoker manages **history** and **redo** stacks (LIFO).

-   For async/remote, commands should be **serializable** (e.g., JSON) and **idempotent** (for retries).

-   Add **metadata**: id, timestamp, user, correlation id for auditing.

-   For security, commands can support `authorize(principal)` before `execute()`.


---

## Sample Code (Java)

**Scenario:** A tiny text editor supports insert and delete with full **undo/redo** and **macro commands**. Also shows a simple **queue-based invoker**.

```java
// ===== Command SPI =====
public interface Command {
    void execute();
    default void undo() { /* optional */ }
    default boolean isUndoable() { return true; }
    default String name() { return getClass().getSimpleName(); }
}

// ===== Receiver =====
public class TextDocument {
    private final StringBuilder buf = new StringBuilder();

    public void insert(int pos, String text) {
        if (pos < 0 || pos > buf.length()) throw new IndexOutOfBoundsException();
        buf.insert(pos, text);
    }

    public String delete(int start, int len) {
        if (start < 0 || start + len > buf.length()) throw new IndexOutOfBoundsException();
        String removed = buf.substring(start, start + len);
        buf.delete(start, start + len);
        return removed;
    }

    public int length() { return buf.length(); }
    @Override public String toString() { return buf.toString(); }
}

// ===== Concrete Commands =====
public class InsertText implements Command {
    private final TextDocument doc;
    private final int position;
    private final String text;

    public InsertText(TextDocument doc, int position, String text) {
        this.doc = doc; this.position = position; this.text = text;
    }

    @Override public void execute() { doc.insert(position, text); }

    @Override public void undo() {
        doc.delete(position, text.length());
    }
}

public class DeleteRange implements Command {
    private final TextDocument doc;
    private final int start, length;
    private String backup = "";

    public DeleteRange(TextDocument doc, int start, int length) {
        this.doc = doc; this.start = start; this.length = length;
    }

    @Override public void execute() {
        backup = doc.delete(start, length); // capture for undo
    }

    @Override public void undo() {
        doc.insert(start, backup);
    }
}

// Composite/Macro command (executes in order, undoes in reverse)
public class MacroCommand implements Command {
    private final List<Command> steps;

    public MacroCommand(List<Command> steps) { this.steps = List.copyOf(steps); }

    @Override public void execute() { steps.forEach(Command::execute); }

    @Override public void undo() {
        ListIterator<Command> it = steps.listIterator(steps.size());
        while (it.hasPrevious()) it.previous().undo();
    }

    @Override public String name() { return "Macro(" + steps.size() + ")"; }
}

// ===== Invokers =====

// Interactive invoker with undo/redo stacks
public class EditorInvoker {
    private final Deque<Command> history = new ArrayDeque<>();
    private final Deque<Command> redo = new ArrayDeque<>();

    public void invoke(Command c) {
        c.execute();
        if (c.isUndoable()) {
            history.push(c);
            redo.clear();
        }
    }

    public boolean undo() {
        if (history.isEmpty()) return false;
        Command c = history.pop();
        c.undo();
        redo.push(c);
        return true;
    }

    public boolean redo() {
        if (redo.isEmpty()) return false;
        Command c = redo.pop();
        c.execute();
        history.push(c);
        return true;
    }
}

// Simple queued invoker (e.g., for background processing)
public class QueueInvoker {
    private final BlockingQueue<Command> queue = new LinkedBlockingQueue<>();
    private final ExecutorService workers = Executors.newFixedThreadPool(2);

    public QueueInvoker() {
        workers.submit(() -> {
            while (!Thread.currentThread().isInterrupted()) {
                Command c = queue.take();
                try { c.execute(); } catch (Exception e) { /* retry/log */ }
            }
        });
    }

    public void submit(Command c) { queue.offer(c); }
    public void shutdown() { workers.shutdownNow(); }
}

// ===== Demo =====
public class CommandDemo {
    public static void main(String[] args) {
        TextDocument doc = new TextDocument();
        EditorInvoker editor = new EditorInvoker();

        editor.invoke(new InsertText(doc, 0, "Hello"));
        editor.invoke(new InsertText(doc, 5, " World"));
        System.out.println(doc); // Hello World

        editor.undo();
        System.out.println(doc); // Hello
        editor.redo();
        System.out.println(doc); // Hello World

        // Macro: surround with brackets
        Command macro = new MacroCommand(List.of(
            new InsertText(doc, 0, "["),
            new InsertText(doc, doc.length(), "]")
        ));
        editor.invoke(macro);
        System.out.println(doc); // [Hello World]

        editor.undo(); // undoes macro (removes trailing ']' then leading '[')
        System.out.println(doc); // Hello World

        // Queue example (asynchronous)
        QueueInvoker queue = new QueueInvoker();
        queue.submit(new InsertText(doc, doc.length(), " !!!"));
        try { Thread.sleep(50); } catch (InterruptedException ignored) {}
        System.out.println(doc); // Hello World !!!
        queue.shutdown();
    }
}
```

### Notes on the example

-   `InsertText` computes its inverse from parameters; `DeleteRange` captures a **backup** (memento-like) during `execute()` to support undo.

-   `MacroCommand` demonstrates **transactional** semantics (execute in order, undo in reverse).

-   `EditorInvoker` manages **undo/redo** stacks; `QueueInvoker` shows a **deferred/async** invoker.


## Known Uses

-   **GUI frameworks**: menu/toolbar actions, keyboard shortcuts, and undo/redo stacks.

-   **Job queues / task schedulers**: encapsulated jobs for retry and persistence.

-   **Transactional scripting** in editors/IDEs (refactorings as commands).

-   **Event sourcing / audit logs**: persisting commands or resulting events for replay.

-   **Remote commands** (RPC): serialize/execute on a server (careful with security & idempotency).


## Related Patterns

-   **Memento**: capture receiver state for robust undo; often used by commands.

-   **Composite**: macro commands combine multiple commands.

-   **Invoker** can be a **Mediator** in complex UIs orchestrating many commands.

-   **Strategy**: encapsulates algorithms; Command encapsulates **invocations** (often with parameters and undo).

-   **Chain of Responsibility**: route commands through handlers; CoR can pick which command to execute.

-   **Prototype**: clone configured commands for reuse.

-   **Observer**: commands can notify observers after execution for UI updates/logging.
