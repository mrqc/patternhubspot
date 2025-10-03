
# Concurrency / Parallelism Pattern — Immutability

## Pattern Name and Classification

-   **Name:** Immutability

-   **Classification:** Data & state management pattern for concurrent systems (share-safe values)


## Intent

Represent data as **values that never change after construction**. Once created, an immutable object’s state is fixed; any “update” produces a **new instance**. This eliminates read/write races and makes sharing across threads safe **without locks**.

## Also Known As

-   Persistent Data (when structural sharing is used)

-   Value Object (DDD)

-   Read-Only Data / Pure Data


## Motivation (Forces)

-   **Safety:** No mutation → no data races; safe publication is trivial (final fields).

-   **Simplicity:** Readers don’t coordinate; references can be freely shared & cached.

-   **Reasoning & testing:** Referential transparency (same input → same output).

-   **Parallelism:** Values can be processed in parallel without coordination.


Tensions:

-   **Allocation cost:** New object per “update” (mitigate with **structural sharing**).

-   **Copy hazards:** Shallow vs. deep immutability (defensive copying may be needed).

-   **Large graphs:** Snapshotting huge structures can be expensive without sharing.


## Applicability

Use immutability when:

-   You pass data between threads/tasks (actors, futures, pipelines).

-   You cache or memoize results.

-   You need reproducibility (event sourcing, snapshots).

-   Your domain entities are mostly read-heavy.


Use caution when:

-   Objects are extremely large and updated frequently (consider persistent structures or hybrid designs).

-   You must interact with mutable/legacy APIs (wrap & copy).


## Structure

-   **Immutable Value Object:** All fields set in constructor; **no setters**.

-   **Withers:** Methods that return a **new** object with one field changed.

-   **Builders/factories:** Validate & assemble complex instances safely.

-   **Persistent Collections (optional):** Efficient “copy-on-write” via structural sharing.


```nginx
oldValue --withX(newX)--> newValue
   ^                       |
   |  (remains valid)      v
  shared safely across threads
```

## Participants

-   **Value Type:** Class or `record` with final fields.

-   **Builder/Factory:** Validates and creates instances; hides representation.

-   **Persistent Collection:** Underlying structure enabling cheap “updates.”

-   **Adapters:** Defensive copies / unmodifiable wrappers for external collections.


## Collaboration

1.  A thread constructs a value object (validation inside).

2.  The value object is **freely shared** among threads (no locks).

3.  An “update” request is handled by creating a **new** value (often sharing internal structure).

4.  Users switch to the new reference; the old one can remain in use (snapshots).


## Consequences

**Benefits**

-   Thread safety by construction; no synchronization needed for reads.

-   Easier caching, memoization, and reasoning about program state.

-   Works well with functional style, actors, and parallel streams.


**Liabilities / Trade-offs**

-   More allocations & GC pressure if values are large and frequently changed.

-   Must avoid leaking references to mutable internals (deep immutability).

-   Interop with mutable APIs requires copying.


## Implementation (Key Points)

-   Make class **final** (or ensure no mutable exposure through inheritance).

-   All fields **private final**; set exactly once in the constructor.

-   **Defensive copies** of arrays/collections on input & output; expose **unmodifiable views** or `List.copyOf`.

-   For large structures, prefer **persistent collections** (e.g., Vavr/Clojure/Scala) or custom **copy-on-write** with structural sharing.

-   Consider Java \*\*`record`\*\*s for concise immutable carriers.

-   Rely on Java Memory Model: writes to `final` fields become visible after construction (safe publication).

-   Provide **withers** & **builders** for ergonomic updates.

-   Ensure equals/hashCode/toString are consistent (records auto-generate them).


---

## Sample Code (Java 17): Immutable Domain with Withers, Builder & Concurrent Updates

> Demonstrates:
>
> -   Deep immutability (defensive copies)
>
> -   Withers that return new instances
>
> -   Builder for validation
>
> -   Concurrent, lock-free reads and atomic “updates” via `compute`
>
> -   Safe publication through `final` fields and records
>

```java
// File: ImmutabilityDemo.java
// Compile: javac ImmutabilityDemo.java
// Run:     java ImmutabilityDemo
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;
import java.util.stream.Collectors;

/** Immutable value: an order line. Using record => auto equals/hashCode/toString, final components. */
record LineItem(String sku, int qty, long centsPerUnit) {
    public LineItem {
        if (sku == null || sku.isBlank()) throw new IllegalArgumentException("sku");
        if (qty <= 0) throw new IllegalArgumentException("qty");
        if (centsPerUnit < 0) throw new IllegalArgumentException("price");
    }
    long lineTotal() { return qty * centsPerUnit; }
}

/** Immutable value: an order with deep immutability for the items list. */
final class Order {
    private final UUID id;
    private final String customer;
    private final Instant createdAt;
    private final List<LineItem> items; // immutable snapshot
    private final long totalCents;      // derived, cached

    private Order(UUID id, String customer, Instant createdAt, List<LineItem> items) {
        this.id = Objects.requireNonNull(id);
        this.customer = Objects.requireNonNull(customer);
        this.createdAt = Objects.requireNonNull(createdAt);
        // defensive copy + unmodifiable to ensure deep immutability
        this.items = List.copyOf(items);
        this.totalCents = this.items.stream().mapToLong(LineItem::lineTotal).sum();
    }

    /** Builder for ergonomic construction + validation. */
    public static final class Builder {
        private UUID id = UUID.randomUUID();
        private String customer;
        private Instant createdAt = Instant.now();
        private final List<LineItem> items = new ArrayList<>();

        public Builder id(UUID id) { this.id = Objects.requireNonNull(id); return this; }
        public Builder customer(String c) { this.customer = Objects.requireNonNull(c); return this; }
        public Builder createdAt(Instant t) { this.createdAt = Objects.requireNonNull(t); return this; }
        public Builder addItem(LineItem li) { items.add(Objects.requireNonNull(li)); return this; }

        public Order build() {
            if (customer == null || customer.isBlank()) throw new IllegalStateException("customer required");
            if (items.isEmpty()) throw new IllegalStateException("at least one item");
            return new Order(id, customer, createdAt, items);
        }
    }

    // ---- Withers (return NEW Order with one field altered) ----
    public Order withAddedItem(LineItem li) {
        ArrayList<LineItem> next = new ArrayList<>(items.size()+1);
        next.addAll(items);
        next.add(Objects.requireNonNull(li));
        return new Order(id, customer, createdAt, next);
    }
    public Order withCustomer(String newCustomer) {
        return new Order(id, Objects.requireNonNull(newCustomer), createdAt, items);
    }

    // ---- Accessors (safe: values are immutable; list is unmodifiable) ----
    public UUID id() { return id; }
    public String customer() { return customer; }
    public Instant createdAt() { return createdAt; }
    public List<LineItem> items() { return items; }
    public long totalCents() { return totalCents; }

    @Override public String toString() {
        String lines = items.stream().map(Object::toString).collect(Collectors.joining(", "));
        return "Order{id=%s, customer=%s, total=%d, items=[%s]}".formatted(id, customer, totalCents, lines);
    }
}

/** Demo: many threads read the same Order safely; updates create NEW Orders atomically. */
public class ImmutabilityDemo {
    public static void main(String[] args) throws Exception {
        Order initial = new Order.Builder()
                .customer("ACME")
                .addItem(new LineItem("A-123", 2, 499))
                .addItem(new LineItem("B-999", 1, 1299))
                .build();

        // Shared, lock-free reads of the same instance:
        var cache = new ConcurrentHashMap<UUID, Order>();
        cache.put(initial.id(), initial);

        // Writer: atomically "update" by replacing the value (compute returns NEW immutable object)
        Runnable writer = () -> {
            cache.compute(initial.id(), (k, old) -> {
                // may be null in theory; handle both
                Order cur = (old == null) ? initial : old;
                return cur.withAddedItem(new LineItem("C-777", 1, 899));
            });
        };

        // Readers: safe dereference from multiple threads; no synchronization required
        Runnable reader = () -> {
            Order o = cache.get(initial.id());
            // snapshot semantics: even if writer runs concurrently, this reference is stable and safe
            long cents = o.totalCents();
            if (cents < 0) throw new AssertionError("impossible");
        };

        // Run a small race
        ExecutorService pool = Executors.newFixedThreadPool(8);
        List<Callable<Void>> tasks = new ArrayList<>();
        for (int i = 0; i < 50; i++) tasks.add(() -> { reader.run(); return null; });
        for (int i = 0; i < 10; i++) tasks.add(() -> { writer.run(); return null; });

        pool.invokeAll(tasks);
        pool.shutdown();

        System.out.println("Final order: " + cache.get(initial.id()));
        System.out.println("Items count: " + cache.get(initial.id()).items().size());
    }
}
```

**What this shows**

-   `Order` and `LineItem` are **immutable**; lists are **defensively copied** and exposed as unmodifiable snapshots.

-   Updates use **withers** to create a *new* `Order`; concurrent readers keep using their snapshot safely.

-   The concurrent map holds the **current** version; `compute` swaps in a new instance atomically.

-   No locks around reads; no data races.


---

## Known Uses

-   **Java standard types:** `String`, `Integer`/boxed primitives, `java.time` (e.g., `Instant`, `LocalDate`).

-   **Libraries:** Guava `ImmutableList/Map`, Vavr persistent collections, Clojure/Scala default collections.

-   **Frameworks:** Akka messages (recommend immutability), event sourcing snapshots/log records, config objects.

-   **Systems:** Content-addressable storage, functional compilers/ASTs, caches & memoization tables.


## Related Patterns

-   **Copy-on-Write / Persistent Data Structures:** Efficient “updates” via structural sharing.

-   **Actor Model / Message Passing:** Immutable messages eliminate coordination.

-   **Future/Promise & Streams:** Immutable results simplify async composition.

-   **Flyweight:** Share read-only state across many objects.

-   **Thread Confinement:** Alternative approach (mutability kept within a single thread).

-   **Snapshot / Memento:** Capturing state as immutable values.


---

### Practical Tips

-   Prefer **records** for simple carriers; for aggregates, combine **builder + withers**.

-   Always ensure **deep immutability**: copy arrays/collections in & out; never expose internals.

-   For hot paths with high update rates on big structures, adopt **persistent collections** or domain-specific structural sharing.

-   Cache derived fields (like `totalCents`) inside the immutable object to avoid recomputation.

-   Leverage the JMM: `final` fields provide **safe publication**—don’t leak `this` from constructors.

-   Measure: immutability often **reduces contention** enough to offset allocation overhead in parallel programs.
