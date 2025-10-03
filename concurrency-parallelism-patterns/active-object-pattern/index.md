
# Concurrency / Parallelism Pattern — Active Object

## Pattern Name and Classification

-   **Name:** Active Object

-   **Classification:** Concurrency pattern (asynchronous method invocation + scheduling)


## Intent

Decouple method invocation from method execution to let callers **invoke operations asynchronously** on an object while a **scheduler thread** executes those operations **serially (per object)** on a real implementation (“servant”), returning **futures** to the caller.

## Also Known As

-   Asynchronous Method Invocation (AMI)

-   Active Object Proxy

-   Method Request / Activation Queue pattern


## Motivation (Forces)

-   **Thread safety vs. throughput:** Keep object’s internal state single-threaded (no fine-grained locks) while still allowing many concurrent callers.

-   **Latency hiding:** Callers proceed immediately with a **Future** without blocking.

-   **Back-pressure & ordering:** A queue regulates load; requests can preserve order or be prioritized.

-   **Fairness vs. specialization:** One scheduler per object keeps state simple; multiple workers increase parallelism but need partitioning.

-   **Exception propagation:** Failures must surface on the returned Future.

-   **Cancellation & shutdown:** In-flight requests may need cancellation; the queue needs a graceful drain.


## Applicability

Use Active Object when:

-   You want an **asynchronous facade** around a stateful component that must be accessed **sequentially**.

-   You’d like to **bound contention** with a queue and a single servant thread (or a small pool).

-   Your API is naturally **request/response** (future-based), or **fire-and-forget**.


Avoid or adapt when:

-   You need **strong ordering across multiple objects** (distributed ordering is tricky).

-   The servant’s methods are **CPU heavy** and parallelizable; prefer a compute pool instead.

-   Ultra-low latency is required and the extra hop/queueing is unacceptable.


## Structure

```javascript
Caller ──(async call)──► Proxy ──► MethodRequest ──► ActivationQueue ─► Scheduler Thread ─► Servant
         ◄────────────── Future/CompletionStage ◄───────────────────────────────────────────────────
```

## Participants

-   **Proxy (Facade):** Exposes the public API; builds `MethodRequest`s and returns `Future`s.

-   **MethodRequest:** Command object carrying operation + arguments + a `CompletableFuture` to complete. May include **guard** logic (e.g., preconditions).

-   **ActivationQueue:** Thread-safe queue that buffers requests (often bounded).

-   **Scheduler (a.k.a. Dispatcher):** Dedicated thread (or small pool) that takes requests from the queue and invokes them on the **Servant**; completes futures (success/failure).

-   **Servant:** The real implementation with single-threaded state/logic.

-   **Future/Promise:** Result handle returned to callers.


## Collaboration

1.  Caller invokes a Proxy method; Proxy packages it into a `MethodRequest` with a `CompletableFuture`.

2.  Request enqueues into the ActivationQueue (may block or reject if full).

3.  Scheduler loop takes requests, checks guards, invokes servant, completes future.

4.  Exceptions are captured and complete the future exceptionally.

5.  Shutdown: scheduler stops after draining or on sentinel request.


## Consequences

**Benefits**

-   Simplifies servant state (single thread, no fine-grained locking).

-   Naturally **asynchronous** caller API via futures.

-   Built-in **back-pressure** and **ordering** per active object.

-   Clear separation of concerns (proxy, queue, scheduler, servant).


**Liabilities / Trade-offs**

-   **Extra hop** and queueing latency.

-   Risk of **unbounded queues** if not sized/guarded.

-   Cross-object workflows need additional coordination (sagas, 2-phase, etc.).

-   Debuggability shifts to queue/scheduler instrumentation.


## Implementation (Key Points)

-   Prefer **bounded** queues; define behavior when full (block, drop, or fail fast).

-   Use `CompletableFuture` to propagate results, exceptions, and support cancellation.

-   If some methods are **read-only** and frequent, consider a **separate AO** or a **read pool**.

-   Add **priorities** by using a `PriorityBlockingQueue` and a `priority()` on requests.

-   Provide **shutdown** hooks (drain vs. abort).

-   For CPU-bound work, consider **one scheduler per core** and **shard** servants across schedulers.

-   Expose metrics: queue depth, throughput, p95 latency, rejection count.


---

## Sample Code (Java 17): Minimal Active Object (Proxy + Scheduler + Servant)

> Features:
>
> -   Asynchronous methods returning `CompletableFuture`
>
> -   Bounded activation queue with back-pressure
>
> -   Exception propagation, cancellation, graceful shutdown
>
> -   Demonstrates both **request/response** and **fire-and-forget**
>

```java
// File: ActiveObjectDemo.java
// Compile: javac ActiveObjectDemo.java
// Run:     java ActiveObjectDemo
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/* ---------- Public API exposed to callers ---------- */
interface AsyncKeyValueService {
    CompletableFuture<Void> put(String key, String value);          // fire-and-forget (returns when enqueued; completes when persisted)
    CompletableFuture<Optional<String>> get(String key);            // async read
    CompletableFuture<Integer> add(String counterKey, int delta);   // returns new value
    void shutdownGracefully(Duration timeout) throws InterruptedException;
}

/* ---------- Servant: real implementation (single-threaded by scheduler) ---------- */
final class KeyValueServant {
    private final Map<String, String> kv = new HashMap<>();
    private final Map<String, Integer> counters = new HashMap<>();

    Optional<String> get(String k) {
        simulateIO(15); // emulate small latency
        return Optional.ofNullable(kv.get(k));
    }
    void put(String k, String v) {
        simulateIO(20);
        kv.put(k, v);
    }
    int add(String k, int delta) {
        simulateIO(25);
        int v = counters.getOrDefault(k, 0) + delta;
        counters.put(k, v);
        return v;
    }
    private static void simulateIO(int ms) {
        try { Thread.sleep(ms); } catch (InterruptedException ie) { Thread.currentThread().interrupt(); }
    }
}

/* ---------- Infrastructure: MethodRequest, Queue, Scheduler ---------- */
abstract class MethodRequest<T> implements Comparable<MethodRequest<?>> {
    final CompletableFuture<T> promise;
    final int priority; // lower value = higher priority
    MethodRequest(CompletableFuture<T> p, int priority) { this.promise = p; this.priority = priority; }
    /** Optional guard to skip/park request if preconditions aren't met (not used in this demo). */
    boolean guard() { return true; }
    /** Execute on servant; may throw (will be captured to complete promise exceptionally). */
    abstract void call(KeyValueServant servant) throws Exception;
    @Override public int compareTo(MethodRequest<?> o) { return Integer.compare(this.priority, o.priority); }
}

/* ---------- Active Object core ---------- */
final class ActiveObject implements AsyncKeyValueService {
    private final KeyValueServant servant = new KeyValueServant();
    private final BlockingQueue<MethodRequest<?>> queue;
    private final Thread scheduler;
    private final AtomicBoolean running = new AtomicBoolean(true);

    public ActiveObject(int queueCapacity, String name) {
        // Use a priority queue if you want priorities; plain ArrayBlockingQueue for FIFO.
        this.queue = new PriorityBlockingQueue<>(queueCapacity);
        this.scheduler = new Thread(this::runLoop, name);
        this.scheduler.start();
    }

    private void runLoop() {
        while (running.get() || !queue.isEmpty()) {
            try {
                MethodRequest<?> req = queue.poll(100, TimeUnit.MILLISECONDS);
                if (req == null) continue;
                if (!req.guard()) { // simple guard support
                    // Requeue or park; in this demo we requeue at the end.
                    queue.offer(req);
                    continue;
                }
                try {
                    req.call(servant);
                } catch (Throwable t) {
                    req.promise.completeExceptionally(t);
                }
            } catch (InterruptedException ie) {
                // exit if shutting down; else continue
                if (!running.get()) break;
                Thread.currentThread().interrupt();
            }
        }
    }

    private <T> CompletableFuture<T> submit(MethodRequest<T> req) {
        if (!running.get()) {
            req.promise.completeExceptionally(new RejectedExecutionException("AO shutting down"));
            return req.promise;
        }
        // Bounded back-pressure: block briefly; callers can also compose timeouts on returned future
        try {
            // If queue is full, this will block; tweak to offer() with rejection as needed.
            queue.put(req);
            return req.promise;
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
            req.promise.completeExceptionally(ie);
            return req.promise;
        }
    }

    /* ---------- Proxy methods (create requests, return futures) ---------- */
    @Override
    public CompletableFuture<Void> put(String key, String value) {
        CompletableFuture<Void> p = new CompletableFuture<>();
        return submit(new MethodRequest<>(p, /*priority*/10) {
            @Override public void call(KeyValueServant s) {
                s.put(key, value);
                promise.complete(null);
            }
            @Override public String toString() { return "put(" + key + ")"; }
        });
    }

    @Override
    public CompletableFuture<Optional<String>> get(String key) {
        CompletableFuture<Optional<String>> p = new CompletableFuture<>();
        return submit(new MethodRequest<>(p, /*priority*/20) {
            @Override public void call(KeyValueServant s) {
                promise.complete(s.get(key));
            }
            @Override public String toString() { return "get(" + key + ")"; }
        });
    }

    @Override
    public CompletableFuture<Integer> add(String counterKey, int delta) {
        CompletableFuture<Integer> p = new CompletableFuture<>();
        return submit(new MethodRequest<>(p, /*priority*/10) {
            @Override public void call(KeyValueServant s) {
                promise.complete(s.add(counterKey, delta));
            }
            @Override public String toString() { return "add(" + counterKey + "," + delta + ")"; }
        });
    }

    @Override
    public void shutdownGracefully(Duration timeout) throws InterruptedException {
        running.set(false);
        scheduler.interrupt();
        scheduler.join(timeout.toMillis());
        // Fail any leftover requests to unblock waiters
        MethodRequest<?> r;
        while ((r = queue.poll()) != null) {
            r.promise.completeExceptionally(new CancellationException("shutting down"));
        }
    }
}

/* ---------- Demo ---------- */
public class ActiveObjectDemo {
    public static void main(String[] args) throws Exception {
        AsyncKeyValueService service = new ActiveObject(1024, "ao-scheduler");

        // Fire a bunch of async calls
        CompletableFuture<Void> w1 = service.put("user:1", "Alice");
        CompletableFuture<Void> w2 = service.put("user:2", "Bob");

        // Compose futures without blocking the scheduler
        CompletableFuture<Optional<String>> r1 =
                w1.thenCompose(v -> service.get("user:1"));
        CompletableFuture<Integer> c1 =
                service.add("counter:login", 1)
                       .thenCompose(v -> service.add("counter:login", 2));

        // Wait for results (demo)
        System.out.println("user:1 = " + r1.get(1, TimeUnit.SECONDS).orElse("<none>"));
        System.out.println("counter:login = " + c1.get(1, TimeUnit.SECONDS));

        // Fan-out several requests
        List<CompletableFuture<?>> ops = new ArrayList<>();
        for (int i = 0; i < 10; i++) {
            String k = "user:" + i;
            ops.add(service.put(k, "val-" + i));
        }
        CompletableFuture.allOf(ops.toArray(new CompletableFuture[0])).join();

        // Read a few back
        System.out.println(service.get("user:5").get(1, TimeUnit.SECONDS).orElse("<none>"));

        // Shutdown
        ((ActiveObject) service).shutdownGracefully(Duration.ofSeconds(2));
        System.out.println("Done.");
    }
}
```

**Notes on the example**

-   The **Proxy** is the `ActiveObject` class; it accepts calls and returns `CompletableFuture`s.

-   Each call becomes a `MethodRequest` and is serialized through the **Scheduler** thread, which invokes the **Servant**.

-   The queue is **bounded**; change `submit` to non-blocking `offer` if you want **fail-fast** on saturation.

-   Priorities are supported via `PriorityBlockingQueue` (smaller number = higher priority).


---

## Known Uses

-   **CORBA** Active Object (AMI) pattern (original literature).

-   **Android Handler/Looper** (single-threaded UI/worker with message queue).

-   **Akka / Actors**: Actor model is a close cousin (mailbox + single-threaded processing).

-   **GUI frameworks** (Swing EDT, JavaFX Application Thread): serialized access to UI state via event queue.

-   **Game loops / simulation cores**: single-threaded world state with async request queues.


## Related Patterns

-   **Future/Promise:** Result handle returned by asynchronous calls.

-   **Proxy & Command:** AO’s proxy builds command-like `MethodRequest`s.

-   **Producer–Consumer:** Queue decouples producers (callers) from consumer (servant thread).

-   **Monitor Object:** Alternative for synchronized access (blocking rather than async).

-   **Half-Sync/Half-Async:** AO is a specialized instance with a single sync executor.

-   **Reactor / Proactor:** Event-driven I/O; AO can be layered on top for method-level asynchrony.

-   **Actor Model:** Conceptually similar but typically emphasizes location transparency and supervision trees.


---

### Practical Tips

-   Instrument **queue depth**, **wait time**, and **service time**; alert when depth grows.

-   Add **timeouts**/**cancellation** on returned futures to avoid unbounded waits in callers.

-   If you need more throughput, **shard** state across multiple AOs (e.g., key-based hashing).

-   For persistence or cross-process AO, put the **ActivationQueue** on a broker (e.g., Kafka) and run a **consumer** as the scheduler.

-   Ensure **back-pressure**: callers should see fast failure or blocking when the queue is full.

-   Propagate **context** (trace IDs, auth) inside `MethodRequest` objects if needed.
