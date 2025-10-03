
# Concurrency / Parallelism Pattern — Future / Promise

## Pattern Name and Classification

-   **Name:** Future / Promise

-   **Classification:** Concurrency coordination pattern (asynchronous result, synchronization & composition)


## Intent

Represent the **eventual result** of an asynchronous computation with a **Future**, and provide a **Promise** (a write-end) that can be **completed later**—successfully or exceptionally. Callers can **wait**, **poll**, or **compose** on futures without blocking threads unnecessarily.

## Also Known As

-   *Promise/Future*, *Deferred* (JS/Scala), *Task* (C#), *CompletableFuture* (Java), *Promise/Future pair*


## Motivation (Forces)

-   **Decouple production & consumption:** Producer may finish later (I/O, remote call); consumer wants a handle now.

-   **Avoid blocking:** Compose continuations instead of tying up threads.

-   **Uniform error handling:** Exceptions travel with the result.

-   **Cancellation & timeouts:** Callers need a way to stop waiting.

-   **Interoperability:** Wrap legacy callback APIs into futures.

-   **Composability:** Zip, race, and pipeline multiple async results.


## Applicability

Use Future/Promise when:

-   You call asynchronous services (HTTP, DB, RPC, message bus).

-   You need **pipelines** (then/map/compose) or **fan-in/fan-out** (all, any).

-   Work may **fail** or **timeout**, and that must propagate to dependents.


Avoid or adapt when:

-   You require **streaming** or backpressure → consider Reactive Streams/Flow.

-   Work is **CPU-bound** and simple → a fixed thread pool + `Callable` may suffice.

-   You need **distributed** await/trigger semantics → look at workflows (SAGA, Durable Functions).


## Structure

```bash
Producer                        Consumer
--------                        --------
Promise<T> p = new Promise();   Future<T> f = p.future();
doAsync(work,
  ok  -> p.success(ok),         f.thenApply/thenCompose(...)
  err -> p.fail(err));          f.whenComplete(...)
                                f.get()/orTimeout()/cancel()
```

## Participants

-   **Future<T>:** Read-only handle of an eventual `T`. Supports completion callbacks, composition, blocking waits, cancellation.

-   **Promise<T>:** Write-end; completes the associated Future (success or failure).

-   **Executor/Dispatcher:** Runs async tasks and continuations.

-   **Combinators:** `thenCompose`, `thenCombine`, `allOf`, `anyOf`, `handle`, etc.

-   **Timeout/Cancellation policy:** Cancels upstream work or just the wait.


## Collaboration

1.  Producer creates a **Promise**, kicks off async work.

2.  Consumer gets the **Future** immediately, attaches continuations or waits.

3.  Producer completes the Promise → the Future **settles** (success/failure).

4.  Registered continuations run (often on an Executor), propagating outcomes.


## Consequences

**Benefits**

-   Clean separation of concerns, natural async composition.

-   No thread blocked while waiting; easy fan-in/fan-out.

-   Exceptions and cancellations propagate consistently.


**Liabilities**

-   Overuse creates **callback pyramids** (less severe than raw callbacks, but still complex).

-   Leaking executors or forgetting `exceptionally/handle` causes **silent failures**.

-   Chaining across thread-pools can cause **context loss** unless propagated.

-   Futures represent **one value**; not suitable for streams.


## Implementation (Key Points)

-   In Java, use **`CompletableFuture`** (JDK 8+)—it’s both Future **and** Promise.

-   Prefer **non-blocking** composition (`then*`) to `get()`.

-   Establish **timeouts** (`orTimeout`, `completeOnTimeout`) and **cancellation**.

-   Wrap legacy callbacks: create a `CompletableFuture`, complete it in the callback.

-   Choose an **Executor** for continuations (`thenApplyAsync(..., executor)`) to control threads.

-   For per-request isolation, use **time budgets** and **retry with backoff** at the edges.

-   Add **tracing context** to continuations if needed (MDC / OpenTelemetry).


---

## Sample Code (Java 17): Futures in Practice (+ tiny Promise wrapper)

> Demonstrates:
>
> -   composing async calls (`thenCompose`, `thenCombine`)
>
> -   wrapping a callback-style API into a `CompletableFuture`
>
> -   timeout, cancellation, error handling
>
> -   a minimal `Promise<T>` facade over `CompletableFuture<T>`
>

```java
// File: FuturePromiseDemo.java
// Compile: javac FuturePromiseDemo.java
// Run:     java FuturePromiseDemo
import java.time.Duration;
import java.util.Random;
import java.util.concurrent.*;
import java.util.function.Function;

/** --- Minimal Promise facade (write-end) backed by CompletableFuture --- */
final class Promise<T> {
    private final CompletableFuture<T> cf = new CompletableFuture<>();
    public CompletableFuture<T> future() { return cf; }
    public boolean success(T value) { return cf.complete(value); }
    public boolean fail(Throwable t) { return cf.completeExceptionally(t); }
    public boolean cancel(boolean mayInterrupt) { return cf.cancel(mayInterrupt); }
}

/** --- A legacy callback-style async API we cannot change --- */
interface Callback<T> { void onSuccess(T v); void onError(Throwable t); }
final class LegacyAsyncApi {
    private final ScheduledExecutorService io = Executors.newScheduledThreadPool(2);
    private final Random rnd = new Random(42);

    public void get(String resource, Callback<String> cb) {
        // simulate network I/O with jitter and sporadic errors
        long delayMs = 80 + rnd.nextInt(120);
        io.schedule(() -> {
            if (rnd.nextDouble() < 0.15) { cb.onError(new RuntimeException("503 from " + resource)); }
            else cb.onSuccess("OK(" + resource + ")");
        }, delayMs, TimeUnit.MILLISECONDS);
    }
    public void shutdown() { io.shutdown(); }
}

/** --- Utilities to bridge to CompletableFuture --- */
final class Futures {
    public static <T> CompletableFuture<T> fromCallback(
            ConsumerWithCallback<T> fn, Duration timeout) {
        CompletableFuture<T> cf = new CompletableFuture<>();
        ScheduledExecutorService timer = Executors.newSingleThreadScheduledExecutor();
        // timeout
        if (timeout != null && !timeout.isZero() && !timeout.isNegative()) {
            timer.schedule(() -> cf.completeExceptionally(new TimeoutException("timeout " + timeout)), timeout.toMillis(), TimeUnit.MILLISECONDS);
        }
        fn.apply(new Callback<>() {
            @Override public void onSuccess(T v) { cf.complete(v); timer.shutdown(); }
            @Override public void onError(Throwable t) { cf.completeExceptionally(t); timer.shutdown(); }
        });
        return cf;
    }
    @FunctionalInterface interface ConsumerWithCallback<T> { void apply(Callback<T> cb); }
}

/** --- An async service built with CompletableFuture composition --- */
final class AsyncService {
    private final ExecutorService exec = Executors.newFixedThreadPool(Math.max(2, Runtime.getRuntime().availableProcessors()));

    public CompletableFuture<String> fetchUser(String userId) {
        return CompletableFuture.supplyAsync(() -> {
            sleep(60);
            return "User(" + userId + ")";
        }, exec);
    }

    public CompletableFuture<String> fetchOrders(String user) {
        return CompletableFuture.supplyAsync(() -> {
            sleep(100);
            return "Orders[" + user + "]";
        }, exec);
    }

    public CompletableFuture<String> renderPage(String user, String orders) {
        return CompletableFuture.supplyAsync(() -> "Page{" + user + "," + orders + "}", exec);
    }

    public void shutdown() { exec.shutdown(); }

    private static void sleep(long ms) { try { Thread.sleep(ms); } catch (InterruptedException ie) { Thread.currentThread().interrupt(); } }
}

public class FuturePromiseDemo {
    public static void main(String[] args) {
        AsyncService svc = new AsyncService();
        LegacyAsyncApi legacy = new LegacyAsyncApi();

        // 1) Promise/Future pair created by our code
        Promise<String> p = new Promise<>();
        // Produce later:
        CompletableFuture.runAsync(() -> {
            try { Thread.sleep(50); p.success("value-from-promise"); }
            catch (InterruptedException e) { Thread.currentThread().interrupt(); p.fail(e); }
        });
        // Consume now:
        p.future().thenAccept(v -> System.out.println("[promise] " + v));

        // 2) Compose async pipeline (fetch user -> orders -> render), with timeout & exception handling
        CompletableFuture<String> page =
            svc.fetchUser("42")
               .orTimeout(500, TimeUnit.MILLISECONDS)
               .thenCompose(svc::fetchOrders)                   // uses previous result
               .thenCombine(svc.fetchUser("support"), (orders, support) -> orders + " + helper=" + support)
               .thenCompose(combined -> svc.renderPage("User(42)", combined))
               .exceptionally(ex -> "fallback-page: " + ex.getClass().getSimpleName());

        // 3) Wrap a legacy callback into a Future and race two calls (anyOf)
        CompletableFuture<String> a =
            Futures.fromCallback(cb -> legacy.get("/inventory", cb), Duration.ofMillis(250))
                   .exceptionally(ex -> "inventory:ERR");
        CompletableFuture<String> b =
            Futures.fromCallback(cb -> legacy.get("/pricing", cb), Duration.ofMillis(250))
                   .exceptionally(ex -> "pricing:ERR");

        CompletableFuture<Object> fastest = CompletableFuture.anyOf(a, b);

        // 4) Cancellation demo: start a slow task and cancel if first finishes earlier
        CompletableFuture<String> slow =
            CompletableFuture.supplyAsync(() -> { sleep(1_000); return "slow-done"; });
        fastest.thenRun(() -> slow.cancel(true));  // cancel wait for slow task (best-effort)

        // 5) Gather all with allOf (fan-in)
        CompletableFuture<Void> all =
            CompletableFuture.allOf(page, a, b)
                             .orTimeout(1, TimeUnit.SECONDS)
                             .whenComplete((__, ex) -> {
                                 if (ex != null) System.out.println("[all] failed: " + ex);
                             });

        all.join(); // wait for demo

        System.out.println("page  = " + page.join());
        System.out.println("a     = " + a.join());
        System.out.println("b     = " + b.join());
        System.out.println("race  = " + fastest.join());
        System.out.println("slow  = " + slow.isCancelled());

        // cleanup
        svc.shutdown();
        legacy.shutdown();
    }

    private static void sleep(long ms) { try { Thread.sleep(ms); } catch (InterruptedException ie) { Thread.currentThread().interrupt(); } }
}
```

**What the demo shows**

-   A tiny **`Promise<T>`** that writes to a `CompletableFuture<T>`.

-   **Pipeline**: `thenCompose` and `thenCombine` to build a page from async parts.

-   **Bridging callbacks**: convert legacy `Callback` into a `CompletableFuture`.

-   **Timeouts** (`orTimeout`) and **fallbacks** (`exceptionally`).

-   **Fan-in/out**: `anyOf` (race) and `allOf` (join).

-   **Cancellation**: best-effort cancel of a no-longer-needed task.


---

## Known Uses

-   **JDK `CompletableFuture`** (HTTP clients, async DB drivers, parallel pipelines).

-   **Akka / Scala** `Future` and **JS Promises** (`Promise.then`, `Promise.all`).

-   **.NET** `Task`/`TaskCompletionSource` (same Future/Promise split).

-   **RPC/SDKs**: gRPC, AWS/GCP SDKs expose Futures/Promises for async calls.


## Related Patterns

-   **Active Object:** Returns a Future from queued method requests.

-   **Actor Model:** Messages often reply via Future/Promise.

-   **Reactor/Proactor:** Event demultiplexing; Futures capture the result of event-driven ops.

-   **Fork–Join:** Produces Futures (or uses `CompletableFuture`) for compute tasks.

-   **Circuit Breaker / Retry with Backoff:** Compose around Futures for resilient remote calls.

-   **Barrier Synchronization:** Can await **multiple** futures as a barrier (`allOf`).


---

### Practical Tips

-   Prefer **non-blocking** continuations; avoid `get()` on hot paths.

-   Always add **timeouts** and **exception handling**; otherwise failures may hide.

-   Control where continuations run (`thenApplyAsync(fn, executor)`) to prevent thread starvation or deadlocks.

-   Propagate **context** (trace IDs, MDC) into async stages.

-   For **streams** or push-based data, step up to Reactive Streams (`Flow`, Project Reactor, RxJava).

-   Keep Futures **single-assignment**; once completed, never mutate the result.
