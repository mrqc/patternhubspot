
# Memento — GoF Behavioral Pattern

## Pattern Name and Classification

**Name:** Memento  
**Category:** Behavioral design pattern

## Intent

Without violating encapsulation, capture and externalize an object’s **internal state** so that the object can be **restored** to that state later (e.g., undo/redo, checkpoints).

## Also Known As

Snapshot, Token

## Motivation (Forces)

-   You need **undo/redo** or **checkpoint** semantics for complex domain objects.

-   The object’s internal state is **encapsulated** (private, complex invariants). Exposing getters for all internals would **break encapsulation**.

-   The history should be **managed externally** (by a caretaker) while the object itself defines **what** constitutes a valid snapshot and how to **restore** it.


## Applicability

Use Memento when:

-   You want to implement **undo/redo**, **rollback**, **time-travel debugging**, or **draft/commit** behavior.

-   The object’s state is **opaque** to clients and must remain so; only the originator should know how to (de)serialize its state.

-   The state snapshots are **finite and manageable** (or you can bound/compact them).


## Structure

-   **Originator** — the object whose state you want to save/restore. It creates mementos and knows how to restore from them.

-   **Memento** — the **opaque** capsule of state. Exposes a **narrow interface** to outsiders and a **wide interface** only to the originator.

-   **Caretaker** — stores and manages mementos (stacks/queues), never inspecting their content.


```vbnet
Client
  │
  └─> Caretaker ── stores ── Memento (opaque to Caretaker)
                     ▲
                     │
                Originator ── creates/restores ── Memento (wide interface)
```

## Participants

-   **Originator**: defines what to save and how to restore; ensures invariants.

-   **Memento**: immutable snapshot of originator state; opaque to the caretaker.

-   **Caretaker**: keeps history (undo/redo stacks), triggers save/restore.


## Collaboration

1.  Client asks **Caretaker** to back up the **Originator** (Caretaker asks Originator to create a **Memento**).

2.  On undo, Caretaker gives the stored **Memento** back to the **Originator** to restore.

3.  Caretaker never reads or mutates the memento’s internals.


## Consequences

**Benefits**

-   Preserves **encapsulation**; only the Originator sees internal state.

-   Provides a clean foundation for **undo/redo**, **checkpointing**, **time travel**.

-   Mementos can be **immutable**, simplifying concurrency.


**Liabilities**

-   **Memory/time cost**: snapshots can be large; naive per-step mementos may explode.

-   Managing **history size**, **compression**, or **diffs** might be necessary.

-   Beware of capturing **external resources** (sockets, file handles); prefer logical state.


## Implementation

-   Keep mementos **immutable** (`final` fields).

-   Use a **narrow interface**: in Java, expose a **public nested marker interface** and keep the concrete memento class **private** inside the Originator; Caretaker only handles the marker type.

-   History management:

    -   **Undo/redo stacks** (two deques).

    -   **Capacity bounds** (LRU-style trimming).

    -   **Coalescing** edits (e.g., merge keystrokes).

    -   **Diff mementos** (store deltas) or **copy-on-write** for large graphs.

-   Persistence: optionally serialize mementos (encrypt if sensitive).

-   Thread-safety: mementos immutable; synchronize restore/apply operations on the Originator.


---

## Sample Code (Java)

**Scenario:** A tiny text editor (originator) with cursor/selection. A caretaker manages **undo/redo** with bounded history. The memento is **opaque** to the caretaker via a nested interface.

```java
import java.util.ArrayDeque;
import java.util.Deque;

/** ===== Originator ===== */
class TextEditor {
    // Internal state (encapsulated)
    private final StringBuilder text = new StringBuilder();
    private int cursor = 0;                 // index 0..length
    private int selStart = 0, selEnd = 0;   // selection range [start,end)

    /** Narrow memento type exposed to the outside (opaque marker). */
    public interface Memento {}

    /** Wide memento implementation, hidden from caretakers. */
    private static final class Snapshot implements Memento {
        private final String text;
        private final int cursor, selStart, selEnd;
        private Snapshot(String text, int cursor, int selStart, int selEnd) {
            this.text = text;
            this.cursor = cursor;
            this.selStart = selStart;
            this.selEnd = selEnd;
        }
    }

    /** Create an immutable snapshot of the internal state. */
    public Memento save() {
        return new Snapshot(text.toString(), cursor, selStart, selEnd);
    }

    /** Restore from a previously captured snapshot. */
    public void restore(Memento m) {
        Snapshot s = (Snapshot) m; // safe: only our save() can create mementos
        text.setLength(0);
        text.append(s.text);
        cursor = s.cursor;
        selStart = s.selStart;
        selEnd = s.selEnd;
        clamp();
    }

    /* ===== Editing API (example) ===== */

    public String getText() { return text.toString(); }
    public int length() { return text.length(); }
    public int getCursor() { return cursor; }

    public void moveCursor(int pos) { cursor = clamp(pos, 0, length()); clearSelection(); }
    public void select(int start, int end) {
        selStart = clamp(Math.min(start, end), 0, length());
        selEnd   = clamp(Math.max(start, end), 0, length());
    }
    public void clearSelection() { selStart = selEnd = cursor; }

    public void type(String s) {
        deleteSelection();
        text.insert(cursor, s);
        cursor += s.length();
        clearSelection();
    }

    public void backspace() {
        if (hasSelection()) { deleteSelection(); return; }
        if (cursor > 0) {
            text.deleteCharAt(cursor - 1);
            cursor--;
        }
    }

    public void replaceSelection(String s) {
        deleteSelection();
        type(s);
    }

    private void deleteSelection() {
        if (!hasSelection()) return;
        text.delete(selStart, selEnd);
        cursor = selStart;
        clearSelection();
    }

    private boolean hasSelection() { return selEnd > selStart; }

    private void clamp() {
        cursor = clamp(cursor, 0, length());
        selStart = clamp(selStart, 0, length());
        selEnd   = clamp(selEnd, 0, length());
    }

    private static int clamp(int v, int lo, int hi) { return Math.max(lo, Math.min(hi, v)); }

    @Override public String toString() {
        String t = text.toString();
        String sel = hasSelection() ? (" [" + selStart + "," + selEnd + ")") : "";
        return "TextEditor{text=\"" + t + "\", cursor=" + cursor + sel + "}";
    }
}

/** ===== Caretaker (history manager) ===== */
class History {
    private final TextEditor editor;
    private final Deque<TextEditor.Memento> undo = new ArrayDeque<>();
    private final Deque<TextEditor.Memento> redo = new ArrayDeque<>();
    private final int capacity;

    public History(TextEditor editor, int capacity) {
        this.editor = editor;
        this.capacity = Math.max(1, capacity);
    }

    /** Capture a checkpoint BEFORE mutating operations. */
    public void backup() {
        undo.push(editor.save());
        redo.clear();
        trim();
    }

    public boolean undo() {
        if (undo.isEmpty()) return false;
        redo.push(editor.save());
        editor.restore(undo.pop());
        return true;
    }

    public boolean redo() {
        if (redo.isEmpty()) return false;
        undo.push(editor.save());
        editor.restore(redo.pop());
        return true;
    }

    private void trim() {
        while (undo.size() > capacity) undo.removeLast();
    }

    public int undoSize() { return undo.size(); }
    public int redoSize() { return redo.size(); }
}

/** ===== Demo ===== */
public class MementoDemo {
    public static void main(String[] args) {
        TextEditor ed = new TextEditor();
        History hist = new History(ed, 10);

        hist.backup();          // checkpoint 0
        ed.type("Hello");
        hist.backup();          // checkpoint 1
        ed.type(" World");
        hist.backup();          // checkpoint 2
        ed.moveCursor(5);
        ed.type(",");           // insert comma after "Hello"

        System.out.println(ed); // TextEditor{text="Hello, World", cursor=6}

        hist.undo();            // undo comma insertion
        System.out.println("undo -> " + ed.getText()); // "Hello World"

        hist.undo();            // undo " World"
        System.out.println("undo -> " + ed.getText()); // "Hello"

        hist.redo();            // redo " World"
        System.out.println("redo -> " + ed.getText()); // "Hello World"

        // Selection replace (with backup)
        hist.backup();
        ed.select(6, ed.length());
        ed.replaceSelection("Wien");
        System.out.println(ed); // "Hello Wien"

        hist.undo();
        System.out.println("undo -> " + ed.getText()); // "Hello World"
    }
}
```

**Notes on the example**

-   `TextEditor.save()` returns a **narrow** `TextEditor.Memento`. The concrete `Snapshot` is **private**, keeping the snapshot’s internals hidden from the caretaker.

-   `History` (caretaker) manages **undo/redo** with bounded capacity.

-   Mementos are **immutable**; Originator alone knows how to **restore**.


## Known Uses

-   **Editors/IDEs**: text buffer states, refactoring previews.

-   **Graphics/CAD**: canvas/object states with multi-step undo.

-   **Games**: quicksave/quickload; turn-based move replays.

-   **Transactions in memory**: tentative changes with the ability to roll back.

-   **Debugging/time travel**: snapshot program state for step-back debugging.


## Related Patterns

-   **Command**: pairs naturally with Memento for **undo/redo** (command stores a memento before execute).

-   **Prototype**: cloning is an alternative when full deep copies are cheap/acceptable.

-   **Caretaker** (role): the history manager in Memento.

-   **Observer**: can publish “checkpoint created/restored” events.

-   **State**: mementos can capture state machine snapshots, but **State** focuses on behavior objects.

-   **Snapshot Iterators (Iterator + Memento)**: iterators that survive modifications capture collection state.
