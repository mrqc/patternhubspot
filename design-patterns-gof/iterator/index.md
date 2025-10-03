
# Iterator — GoF Behavioral Pattern

## Pattern Name and Classification

**Name:** Iterator  
**Category:** Behavioral design pattern

## Intent

Provide a way to **access the elements of an aggregate** object **sequentially** without exposing its internal representation. Support **multiple traversal strategies** and **independent cursors**.

## Also Known As

Cursor, Enumerator

## Motivation (Forces)

-   You want clients to traverse a collection **without** knowing how it’s stored (array, list, tree, ring buffer, graph).

-   You need **more than one** traversal policy (forward/reverse, breadth/depth, filtered).

-   You want **multiple concurrent traversals** over the same aggregate.

-   You want to **minimize coupling** and keep the aggregate free from traversal state/logic.


## Applicability

Use Iterator when:

-   An aggregate has a **rich internal structure** or storage you don’t want to expose.

-   You need **different iteration orders** or **filtered views**.

-   You want **uniform traversal** across different container types.

-   You want to allow **several iterators** to operate at once, each with its own state.


## Structure

-   **Iterator** — interface with `first/next/isDone/currentItem` (GoF) or `hasNext/next` (Java).

-   **ConcreteIterator** — keeps traversal state; implements the iterator protocol.

-   **Aggregate** — interface with a factory method to create iterators.

-   **ConcreteAggregate** — returns appropriate ConcreteIterator(s).


```vbnet
Client ──uses──> Iterator <──created by── Aggregate
                     │
             (keeps traversal state; hides collection internals)
```

## Participants

-   **Iterator**: defines operations to access/traverse elements.

-   **ConcreteIterator**: maintains the current position; implements traversal order.

-   **Aggregate**: declares `createIterator()` (and possibly others like `reverseIterator()`).

-   **ConcreteAggregate**: stores elements; builds iterators that know how to traverse it.


## Collaboration

-   Client asks the **Aggregate** for an **Iterator** and uses it to traverse.

-   ConcreteIterator accesses the aggregate’s internals via a **well-defined interface** or friendship/package access.

-   Multiple iterators may traverse the same aggregate **independently**.


## Consequences

**Benefits**

-   **Encapsulation:** clients don’t depend on internal structure.

-   **Single Responsibility:** traversal concerns live in iterators, not in the aggregate.

-   **Flexibility:** add new traversal strategies by adding new iterator classes.

-   **Multiple simultaneous traversals** are easy.


**Liabilities**

-   **Extra objects/classes** for each traversal strategy.

-   If the language lacks generators/yield, iterators can be **verbose** to write.

-   **Concurrent modification** semantics (fail-fast vs snapshot) require careful design.


## Implementation

-   Decide **external** (pull-based; client calls `next`) vs **internal** (push-based; aggregate calls a callback) iteration.

-   For **fail-fast** behavior, capture a `modCount` on iterator creation and compare on each access.

-   For **snapshot** iteration, copy the current view (memory trade-off).

-   Expose factory methods for different iterators (e.g., `iterator()`, `reverseIterator()`, `filter(Predicate)`).

-   If you support **remove**, define clear semantics (last-returned element) and modCount updates.

-   Consider **Spliterator** (Java 8+) for parallel iteration and bulk ops, or expose `stream()`.


---

## Sample Code (Java)

**Scenario:** A fixed-capacity **RingBuffer** with multiple iterators:

-   forward **fail-fast** iterator

-   reverse **fail-fast** iterator

-   **filtered** iterator (composes any base iterator)

-   **snapshot** iterator immune to concurrent modifications


```java
import java.util.*;
import java.util.function.Predicate;

/**
 * A fixed-capacity ring buffer with multiple iterator strategies.
 * Demonstrates: external iteration, reverse iteration, filtering, fail-fast and snapshot semantics.
 */
class RingBuffer<T> implements Iterable<T> {
    private final Object[] data;
    private int head = 0;     // index of the logical first element
    private int size = 0;     // number of elements actually stored
    private int modCount = 0; // structural modifications counter (for fail-fast)

    public RingBuffer(int capacity) {
        if (capacity <= 0) throw new IllegalArgumentException("capacity must be > 0");
        this.data = new Object[capacity];
    }

    public int capacity() { return data.length; }
    public int size() { return size; }
    public boolean isEmpty() { return size == 0; }

    /** Adds to the tail; evicts the oldest if full (for demo simplicity). */
    public void add(T elem) {
        int tailIndex = (head + size) % data.length;
        if (size < data.length) {
            data[tailIndex] = elem;
            size++;
        } else { // full: overwrite oldest and advance head
            data[tailIndex] = elem;
            head = (head + 1) % data.length;
        }
        modCount++;
    }

    /** Retrieves logical element at index (0..size-1) without removal. */
    @SuppressWarnings("unchecked")
    public T get(int logicalIndex) {
        if (logicalIndex < 0 || logicalIndex >= size) throw new IndexOutOfBoundsException();
        return (T) data[(head + logicalIndex) % data.length];
    }

    /** Removes and returns logical element at index; shifts subsequent elements logically. */
    @SuppressWarnings("unchecked")
    public T removeAt(int logicalIndex) {
        if (logicalIndex < 0 || logicalIndex >= size) throw new IndexOutOfBoundsException();
        int phys = (head + logicalIndex) % data.length;
        T removed = (T) data[phys];
        // Shift elements by moving head or tail depending on shorter distance (simplified for demo: slide head forward)
        for (int i = logicalIndex; i > 0; i--) {
            int from = (head + i - 1) % data.length;
            int to   = (head + i) % data.length;
            data[to] = data[from];
        }
        data[head] = null;
        head = (head + 1) % data.length;
        size--;
        modCount++;
        return removed;
    }

    /** Standard forward iterator (fail-fast). */
    @Override public Iterator<T> iterator() {
        return new ForwardIterator();
    }

    /** Reverse iterator (fail-fast). */
    public Iterator<T> reverseIterator() {
        return new ReverseIterator();
    }

    /** Filtered view wrapping a base iterator. */
    public Iterable<T> filter(Predicate<? super T> p, boolean reverse) {
        Iterator<T> base = reverse ? reverseIterator() : iterator();
        return () -> new FilteringIterator<>(base, p);
    }

    /** Snapshot iterator: safe against concurrent modifications after creation. */
    public Iterator<T> snapshotIterator() {
        Object[] snapshot = new Object[size];
        for (int i = 0; i < size; i++) snapshot[i] = data[(head + i) % data.length];
        return new Iterator<T>() {
            int i = 0;
            @Override public boolean hasNext() { return i < snapshot.length; }
            @SuppressWarnings("unchecked")
            @Override public T next() {
                if (!hasNext()) throw new NoSuchElementException();
                return (T) snapshot[i++];
            }
        };
    }

    // ====== concrete iterators ======
    private abstract class BaseIterator implements Iterator<T> {
        final int expectedModCount = modCount; // capture for fail-fast
        int idx;   // logical index within [0, size)
        int left;  // how many remain

        BaseIterator(int start, int count) { this.idx = start; this.left = count; }

        final void checkForComodification() {
            if (expectedModCount != modCount) throw new ConcurrentModificationException();
        }

        @Override public boolean hasNext() {
            checkForComodification();
            return left > 0;
        }
    }

    private final class ForwardIterator extends BaseIterator {
        ForwardIterator() { super(0, size); }
        @SuppressWarnings("unchecked")
        @Override public T next() {
            checkForComodification();
            if (left <= 0) throw new NoSuchElementException();
            T val = (T) data[(head + idx) % data.length];
            idx++; left--;
            return val;
        }
    }

    private final class ReverseIterator extends BaseIterator {
        ReverseIterator() { super(size - 1, size); }
        @SuppressWarnings("unchecked")
        @Override public T next() {
            checkForComodification();
            if (left <= 0) throw new NoSuchElementException();
            T val = (T) data[(head + idx + data.length) % data.length];
            idx--; left--;
            return val;
        }
    }

    private static final class FilteringIterator<T> implements Iterator<T> {
        private final Iterator<T> base;
        private final Predicate<? super T> predicate;
        private T next;
        private boolean hasBuffered;

        FilteringIterator(Iterator<T> base, Predicate<? super T> predicate) {
            this.base = base; this.predicate = predicate;
        }
        @Override public boolean hasNext() {
            if (hasBuffered) return true;
            while (base.hasNext()) {
                T cand = base.next();
                if (predicate.test(cand)) { next = cand; hasBuffered = true; return true; }
            }
            return false;
        }
        @Override public T next() {
            if (!hasNext()) throw new NoSuchElementException();
            hasBuffered = false;
            return next;
        }
    }
}

// ===== Demo =====
public class IteratorDemo {
    public static void main(String[] args) {
        RingBuffer<Integer> buf = new RingBuffer<>(5);
        for (int i = 1; i <= 7; i++) buf.add(i); // will end up holding [3,4,5,6,7]

        // Forward iteration (fail-fast)
        System.out.print("forward : ");
        for (int x : buf) System.out.print(x + " ");
        System.out.println();

        // Reverse iteration (fail-fast)
        System.out.print("reverse : ");
        Iterator<Integer> rev = buf.reverseIterator();
        while (rev.hasNext()) System.out.print(rev.next() + " ");
        System.out.println();

        // Filtered view (even numbers)
        System.out.print("filtered (even, forward): ");
        for (int x : buf.filter(n -> n % 2 == 0, false)) System.out.print(x + " ");
        System.out.println();

        // Snapshot iteration vs fail-fast
        Iterator<Integer> snap = buf.snapshotIterator();
        Iterator<Integer> ff   = buf.iterator();

        buf.add(8); // structural modification AFTER creating iterators

        System.out.print("snapshot: ");
        while (snap.hasNext()) System.out.print(snap.next() + " ");
        System.out.println();

        try {
            ff.hasNext(); // triggers ConcurrentModificationException
        } catch (ConcurrentModificationException ex) {
            System.out.println("fail-fast iterator detected modification: " + ex.getClass().getSimpleName());
        }
    }
}
```

**What this shows**

-   `RingBuffer` is the **Aggregate**; its nested iterator classes are **ConcreteIterators**.

-   Different traversal strategies: forward, reverse, filtered, and snapshot.

-   **Fail-fast** behavior via `modCount`, and a **snapshot** iterator that’s stable.


## Known Uses

-   **Java Collections Framework** (`Iterator`, `Iterable`, `ListIterator`, `Spliterator`, `Enumeration` legacy).

-   **Streams** (conceptually related; built atop iterators/spliterators).

-   **ResultSet**\-like cursors in database drivers (iterate rows).

-   **XML/JSON parsers** exposing event streams (StAX `XMLStreamReader`—pull iteration).

-   **GUI frameworks** iterating widgets, layout children, or event queues.


## Related Patterns

-   **Composite**: iterate over trees uniformly (DFS/BFS iterators).

-   **Visitor**: externalize operations while an iterator drives traversal.

-   **Factory Method**: aggregates often use it to **create** the appropriate iterator.

-   **Memento**: snapshot iterators may capture state to survive modifications.

-   **Decorator**: build **filtering** or **mapping** iterators by wrapping another iterator.

-   **Strategy**: traversal order (forward/reverse/DFS/BFS) can be injected as a strategy.
