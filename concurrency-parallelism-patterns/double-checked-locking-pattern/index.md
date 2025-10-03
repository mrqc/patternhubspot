
# Concurrency / Parallelism Pattern — Double-Checked Locking (DCL)

## Pattern Name and Classification

-   **Name:** Double-Checked Locking

-   **Classification:** Synchronization & lazy-initialization optimization pattern.


## Intent

Provide **lazy initialization** of a shared object while avoiding the cost of acquiring a lock on **every** access:

1.  **Fast path:** read the reference **without** a lock; if already initialized, return it.

2.  **Slow path:** if `null`, acquire a lock and **check again** (second check) before creating and publishing the instance.


## Also Known As

-   DCL, Double-Checked Idiom, Lazy Init with Fast Path


## Motivation (Forces)

-   **Performance vs. safety:** `synchronized` on every accessor is simple but can be costly on hot paths.

-   **Publication hazards:** Without proper memory semantics, a thread may observe a **partially constructed** object due to reordering.

-   **Contention profile:** Initialization happens once; steady-state reads should be **lock-free**.

-   **Simplicity of use:** Callers want a cheap `get()` that “just returns the singleton/resource.”


## Applicability

Use DCL when all are true:

-   You need **lazy** creation of a **shared** object (singleton, cache entry, heavy parser/connection factory).

-   After initialization the object is **effectively immutable** (or safely published).

-   You can rely on a language/runtime memory model that supports safe DCL (in Java: **Java 5+** with `volatile`).


Prefer alternatives when:

-   The object is cheap to create → initialize eagerly.

-   You can use **Initialization-on-Demand Holder** or an **enum singleton** (simpler & faster).

-   You maintain entries in a map → use `ConcurrentHashMap.computeIfAbsent` (built-in once-per-key).


## Structure

```javascript
if (instance == null) {              // 1st check (no lock)
  synchronized(lock) {
    if (instance == null) {          // 2nd check (with lock)
      instance = new Object(...);    // publish once
    }
  }
}
return instance;
```

## Participants

-   **Guarded Reference:** The field holding the lazily built object (must be `volatile` in Java).

-   **Lock/Monitor:** Ensures only one initializer runs and provides a happens-before edge.

-   **Factory/Initializer:** Code that constructs the object exactly once.


## Collaboration

1.  Reader thread calls `get()`.

2.  If reference is non-null, return it **without locking**.

3.  If null, enter the critical section, check again, then construct and **publish**.

4.  Subsequent readers observe the **published** value due to `volatile`’s visibility guarantees.


## Consequences

**Benefits**

-   Near-zero overhead in the steady state (no lock after initialization).

-   Bounded contention (only during first initialization).


**Liabilities / Pitfalls**

-   **Incorrect without `volatile`** (pre-Java 5 or missing `volatile`) → may see a partially constructed object.

-   Easy to misuse if the constructed object mutates shared state after publication.

-   More complex than simpler alternatives (holder idiom, enums).


## Implementation (Key Points)

-   In Java, mark the reference **`private static volatile`** (or instance field if not static).

-   Ensure the created object is **immutable** or safely publishes all its state before exposing references.

-   Keep the **critical section small**—only the construction & assignment.

-   Prefer **holder idiom** when possible; DCL is mainly for APIs that require a method-level lazy getter.


---

## Sample Code (Java 17): Safe DCL + Alternatives

```java
// File: DoubleCheckedLockingDemo.java
// Compile: javac DoubleCheckedLockingDemo.java
// Run:     java DoubleCheckedLockingDemo

import java.util.Map;
import java.util.Objects;
import java.util.concurrent.*;
import java.util.function.Function;

/** 1) SAFE DCL Singleton (Java 5+): volatile is mandatory. */
final class ConfigSingleton {
    private static volatile ConfigSingleton INSTANCE; // safe publication
    private ConfigSingleton() {
        // simulate expensive init
        try { Thread.sleep(50); } catch (InterruptedException ignored) {}
        // initialize immutable state here
    }
    public static ConfigSingleton getInstance() {
        ConfigSingleton ref = INSTANCE;              // first read (no lock)
        if (ref == null) {
            synchronized (ConfigSingleton.class) {
                ref = INSTANCE;                      // second read (with lock)
                if (ref == null) {
                    ref = new ConfigSingleton();     // construct once
                    INSTANCE = ref;                  // publish
                }
            }
        }
        return ref;
    }
}

/** 2) Alternative (preferred): Initialization-on-Demand Holder. */
final class HolderSingleton {
    private HolderSingleton() {}
    private static class Holder {
        static final HolderSingleton INSTANCE = new HolderSingleton();
    }
    public static HolderSingleton getInstance() { return Holder.INSTANCE; }
}

/** 3) Per-key lazy init without bespoke DCL: computeIfAbsent is once-per-key. */
final class Memoizer<K, V> {
    private final ConcurrentHashMap<K, CompletableFuture<V>> map = new ConcurrentHashMap<>();
    private final Function<K, V> compute;

    public Memoizer(Function<K, V> compute) { this.compute = Objects.requireNonNull(compute); }

    public V get(K key) {
        try {
            // One future per key; first creator runs compute, others await
            CompletableFuture<V> f = map.computeIfAbsent(key, k ->
                CompletableFuture.supplyAsync(() -> compute.apply(k))
            );
            return f.get(); // propagate exception if compute failed
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
            throw new RuntimeException(ie);
        } catch (ExecutionException ee) {
            throw new RuntimeException(ee.getCause());
        }
    }
}

/** 4) Demo / micro-check of correctness under contention. */
public class DoubleCheckedLockingDemo {
    public static void main(String[] args) {
        // Stress the DCL singleton from many threads
        ExecutorService pool = Executors.newFixedThreadPool(8);
        Callable<Integer> task = () -> System.identityHashCode(ConfigSingleton.getInstance());
        try {
            var futures = pool.invokeAll(java.util.stream.Stream.generate(() -> task).limit(64).toList());
            var ids = futures.stream().map(f -> {
                try { return f.get(); } catch (Exception e) { throw new RuntimeException(e); }
            }).collect(java.util.stream.Collectors.toSet());
            System.out.println("Unique singleton identities: " + ids.size() + " -> " + ids);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } finally {
            pool.shutdown();
        }

        // Use the memoizer (per-key lazy init)
        Memoizer<String, String> memo = new Memoizer<>(DoubleCheckedLockingDemo::expensive);
        System.out.println("A=" + memo.get("A"));
        System.out.println("A again=" + memo.get("A"));
        System.out.println("B=" + memo.get("B"));
    }

    static String expensive(String k) {
        try { Thread.sleep(40); } catch (InterruptedException ignored) {}
        return "val:" + k + ":" + System.nanoTime();
    }
}
```

**Notes**

-   `volatile` on the shared reference is what makes Java DCL correct since JSR-133 (Java 5).

-   The **holder** idiom (class-loader lazy init) is simpler and typically faster than DCL.

-   For **per-key** laziness, use `ConcurrentHashMap.computeIfAbsent` (or a `FutureTask`\-based memoizer).


---

## Known Uses

-   **Singletons** and **lazy factories** in high-throughput services.

-   **Lazily built parsers/regex/patterns**, configuration snapshots, heavy caches.

-   **Connection/provider initialization** where cost shouldn’t hit startup time.


## Related Patterns

-   **Initialization-on-Demand Holder** (preferred alternative in Java).

-   **Enum Singleton** (simple, serialization-safe).

-   **Memoization / `computeIfAbsent`** (per-key “once”).

-   **Read-Write Lock** (when you must guard a mutable structure, not just a reference).

-   **Immutable Object / Safe Publication** (guaranteeing visibility).

-   **Once / Call-Once** (in C/C++; `java.util.concurrent` lacks direct “once” but holder idiom fills the gap).


---

### Practical Tips

-   Make the published object **immutable** (or safely publish all mutable fields).

-   Keep the **constructor side-effect free** (no leaking `this`).

-   Do not “optimize further” (e.g., remove the local `ref` temp) unless you understand JIT effects; the shown pattern is standard.

-   If initialization can fail, decide whether to **cache the failure** (and rethrow) or allow **retry**—document semantics.

-   Measure before using DCL; the **holder** idiom or plain eager init is often simpler and just as fast.
