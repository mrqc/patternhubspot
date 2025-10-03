# Singleton — GoF Creational Pattern

## Pattern Name and Classification

**Name:** Singleton  
**Category:** Creational design pattern

## Intent

Ensure a class has **only one instance** and provide a **global access point** to it.

## Also Known As

Single Instance, Monostate (related variant), Registry (anti-pattern if misused)

## Motivation (Forces)

-   A resource must be **centralized**: configuration, caches, logging, ID generation, connection pools.

-   You need **exactly one** coordinator of a concept (e.g., system clock adapter, metrics registry).

-   You want a **single access point** and possibly **lazy initialization** and **lifecycle control**.


## Applicability

Use Singleton when:

-   There must be **exactly one** instance and it must be **accessible globally**.

-   The instance encapsulates **shared, process-wide state** or an expensive, shareable resource.

-   Construction should be **controlled** (lazy/eager, guarded, instrumented).


> If consumers can instead **receive a dependency** (constructor/DI), prefer that over a hard global; it’s easier to test and swap.

## Structure

```arduino
Client ───▶ Singleton.getInstance() ───▶ the single instance
                 ▲
                 │ (private ctor; static accessor; possibly lazy/eager; thread-safe)
```

## Participants

-   **Singleton** — the class that restricts instantiation and provides a `getInstance()` (or enum instance).

-   **Client** — calls the access point; never invokes `new`.


## Collaboration

-   Clients call the **accessor** to obtain the only instance and then use it like any other object.

-   The singleton may internally manage resources (open/close), caches, registries, etc.


## Consequences

**Benefits**

-   **Single point of truth** for a resource/service.

-   Can implement **lazy init** and **lifecycle hooks** centrally.

-   Avoids duplicated heavy objects (memory/CPU).


**Liabilities**

-   **Global state** increases coupling; makes reasoning, testing, and parallelism harder.

-   Hidden dependencies (no explicit parameters/DI).

-   **Order-of-init** problems; tricky teardown across tests.

-   Multiple class loaders may create **more than one** “singleton.”

-   Serialization/reflection can **break single-instance** unless handled.

-   Harder to **mock**; requires seams or indirection.


## Implementation

-   Make the **constructor private**.

-   Choose an initialization strategy:

    -   **Eager**: simple & thread-safe; may waste resources if unused.

    -   **Lazy Holder (IoDH)**: lazy & thread-safe via class initialization.

    -   **Double-Checked Locking (DCL)**: lazy; requires `volatile`.

    -   **Enum**: simplest, **serialization-safe** and **reflection-resistant** (recommended in Java).

-   Consider **serialization** (`readResolve`) and **reflection** hardening.

-   For tests, provide a **reset hook** (only in test builds) or hide behind a **Service** that can be swapped.

-   Be wary of **shutdown hooks** for resource cleanup.


---

## Sample Code (Java)

### Three production-quality Singleton variants

```java
import java.io.ObjectStreamException;
import java.io.Serial;
import java.io.Serializable;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;
import java.util.concurrent.LongAdder;
import java.util.concurrent.atomic.AtomicLong;

/* 1) Initialization-on-Demand Holder (lazy, thread-safe, serialization-safe via readResolve) */
final class AppConfig implements Serializable {
    private final Map<String, String> values = Map.of(
        "env", "prod",
        "region", "eu-central-1"
    );

    private AppConfig() { /* load/validate */ }

    private static class Holder {                      // loaded on first getInstance()
        static final AppConfig INSTANCE = new AppConfig();
    }

    public static AppConfig getInstance() {            // lazy and thread-safe
        return Holder.INSTANCE;
    }

    public String get(String key) { return values.get(key); }

    /* keep singleton on deserialization */
    @Serial
    private Object readResolve() throws ObjectStreamException {
        return Holder.INSTANCE;
    }
}

/* 2) Enum Singleton (simple, serialization & reflection safe) */
enum IdGenerator {
    INSTANCE;

    private final AtomicLong seq = new AtomicLong(1_000L);

    public long nextId() { return seq.incrementAndGet(); }
}

/* 3) Double-Checked Locking (lazy; requires volatile; example with a metrics registry) */
final class MetricsRegistry {
    private static volatile MetricsRegistry instance;  // volatile is crucial for DCL
    private final ConcurrentMap<String, LongAdder> counters = new ConcurrentHashMap<>();

    private MetricsRegistry() {}

    public static MetricsRegistry getInstance() {
        MetricsRegistry result = instance;             // local read
        if (result == null) {
            synchronized (MetricsRegistry.class) {
                result = instance;
                if (result == null) instance = result = new MetricsRegistry();
            }
        }
        return result;
    }

    public void increment(String name) {
        counters.computeIfAbsent(name, k -> new LongAdder()).increment();
    }

    public long value(String name) {
        LongAdder a = counters.get(name);
        return a == null ? 0L : a.sum();
    }
}

/* ---- Demo ---- */
public class SingletonDemo {
    public static void main(String[] args) {
        // AppConfig via Lazy Holder
        AppConfig cfgA = AppConfig.getInstance();
        AppConfig cfgB = AppConfig.getInstance();
        System.out.println("Same AppConfig? " + (cfgA == cfgB) + " env=" + cfgA.get("env"));

        // Enum Singleton for IDs
        long id1 = IdGenerator.INSTANCE.nextId();
        long id2 = IdGenerator.INSTANCE.nextId();
        System.out.println("IDs: " + id1 + ", " + id2);

        // MetricsRegistry via DCL
        MetricsRegistry m = MetricsRegistry.getInstance();
        m.increment("requests"); m.increment("requests");
        System.out.println("requests=" + m.value("requests"));
    }
}
```

### Notes

-   **Enum singleton** is the simplest and safest in Java; it resists multiple instantiation via serialization & reflection.

-   **Lazy Holder** is ideal when you need a class, not an enum, and want lazy initialization without synchronization overhead.

-   **DCL** is correct **only** with `volatile`; prefer Holder or enum unless you really need DCL.


## Known Uses

-   `java.lang.Runtime` (historical singleton-like access).

-   Logging frameworks’ central log manager (varies by impl).

-   `java.util.concurrent.ForkJoinPool.commonPool()` (shared pool—singleton-like accessor).

-   Application-wide **metrics/telemetry** registries, **feature-flag** clients, **configuration** snapshots.


## Related Patterns

-   **Factory Method / Abstract Factory:** Singletons often *are* factories (e.g., central registries) or are created by factories.

-   **Facade:** A singleton can serve as a global facade to a subsystem.

-   **Monostate:** All instances share the same static state (clients can still `new`, but behavior is global).

-   **Service Locator / DI Container:** Alternative ways to access shared services; DI avoids hard globals and improves testability.

-   **Memento:** Combine with Singleton for global undo stacks or checkpoints.

-   **Proxy/Decorator:** Wrap a singleton service to add cross-cutting concerns (caching, security) without changing clients.


---

### Practical guidance (when to prefer/avoid)

-   Prefer **enum** or **Holder**; avoid ad-hoc synchronization or lazy fields without `volatile`.

-   Avoid singletons for **mutable domain state**; they invite hidden coupling and test flakiness.

-   If a class is “singleton by nature” (system clock adapter, process-wide config snapshot), Singleton is justified; otherwise, **inject** a normal instance.
