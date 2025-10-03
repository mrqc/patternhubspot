# Bulkhead — Cloud / Distributed Systems Pattern

## Pattern Name and Classification

**Bulkhead** — *Cloud / Distributed Systems* **resilience** pattern that **isolates resources** (threads, queues, connections) per feature or dependency so failures or load spikes in one area **don’t capsize the whole service**.

---

## Intent

Partition a system into **independent compartments** with **strict capacity limits** to localize failure, bound contention, and preserve **partial availability** under stress.

---

## Also Known As

-   **Resource Pool Isolation**

-   **Compartmentalization**

-   **Per-Dependency Thread Pool** (Netflix/Hystrix-style)


---

## Motivation (Forces)

-   One slow or failing dependency can **exhaust threads** and saturate queues → cascading failures.

-   Traffic can be **uneven** across features/tenants; noisy neighbors must be contained.

-   Ops needs **predictable degradation** (fast rejects + fallbacks) instead of global timeouts.


Tensions: isolation vs. utilization (unused capacity in one bulkhead can’t help others), choosing the **right cut** (per dependency, feature, priority class).

---

## Applicability

Use Bulkheads when:

-   You call **multiple remote services** (payments, search, profile).

-   You serve **mixed-priority** traffic (user vs. batch) or **multi-tenant** workloads.

-   You’ve seen **thread starvation**, **connection pool exhaustion**, or **latency amplification**.


Avoid/limit when:

-   System is tiny and simple; operational overhead outweighs benefit.

-   Work is pure CPU-bound in one place (prefer separate processes/containers).


---

## Structure

```pgsql
┌─────────────── App ───────────────┐
request ──► Router│                                    │
                  │   Bulkhead: Search   ┌─────────┐   │
                  │  (threads=16, q=100) │ ThreadP │──►│ Search API
                  │   Bulkhead: Profile  ┌─────────┐   │
                  │  (threads=8,  q=50 ) │ ThreadP │──►│ Profile API
                  │   Bulkhead: Billing  ┌─────────┐   │
                  │  (threads=4,  q=20 ) │ ThreadP │──►│ Billing API
                  │                                    │
                  └────────────────────────────────────┘
Reject/fallback when a bulkhead is full; others keep working.
```

---

## Participants

-   **Caller / Application** — submits work to a **specific** bulkhead based on feature/dependency.

-   **Bulkhead** — owns isolated **capacity** (threads, queue, async slots or semaphores) plus **timeouts** and **rejection policy**.

-   **Dependency** — downstream system being called.

-   **Fallback** (optional) — fast alternative when a bulkhead **rejects or times out**.

-   **Metrics/Alarms** — visibility into saturation and rejects.


---

## Collaboration

1.  Caller classifies the operation (e.g., **Payments**) and submits to the **Payments bulkhead**.

2.  If capacity exists → task executes with **timeout**.

3.  If full → **immediate reject**, caller applies **fallback**.

4.  Other bulkheads remain unaffected.


---

## Consequences

**Benefits**

-   **Fail contained**: one dependency can’t starve others.

-   **Bounded latency**: fast fail on saturation; no queueing death spirals.

-   **Operational knobs** per dependency/feature (threads/queue/timeouts).


**Liabilities**

-   Possible **underutilization** if compartments are too strict.

-   More configuration & monitoring surface.

-   Picking the **partitioning** and right limits requires load testing.


---

## Implementation (Key Points)

-   Choose isolation primitive:

    -   **ThreadPool + bounded queue** (good for blocking I/O).

    -   **Semaphore** (good for async/non-blocking to cap concurrency).

    -   **Connection pools** (DBs/HTTP) separated per use.

-   Set **short timeouts**; combine with **retries** that respect bulkhead limits.

-   Provide **fallbacks** (cached data, defaults, “try later”).

-   Export **metrics**: utilization, queue depth, rejections, latency.

-   Consider **priority classes** (gold/silver/bronze) or **per-tenant** bulkheads.

-   Pair with **Circuit Breaker** to stop sending work to a failing dependency.


---

## Sample Code (Java 17) — Per-Dependency Bulkheads with Timeouts & Fallbacks

> A minimal library (`Bulkheads`) plus a demo service that calls three “dependencies”.  
> Each dependency has its **own thread pool & queue**. One is intentionally slow; its bulkhead saturates and **rejects fast** without affecting others.

```java
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.Supplier;

// === Bulkhead primitive: bounded threadpool with fast reject ===
final class Bulkhead {
  private final String name;
  private final ThreadPoolExecutor exec;
  private final Duration timeout;
  private final AtomicLong submitted = new AtomicLong();
  private final AtomicLong rejected = new AtomicLong();

  Bulkhead(String name, int threads, int queueCapacity, Duration timeout) {
    this.name = name; this.timeout = timeout;
    this.exec = new ThreadPoolExecutor(
        threads, threads, 0L, TimeUnit.MILLISECONDS,
        new ArrayBlockingQueue<>(queueCapacity),
        new ThreadFactory() {
          private final ThreadFactory df = Executors.defaultThreadFactory();
          public Thread newThread(Runnable r) {
            Thread t = df.newThread(r);
            t.setName("bulkhead-"+name+"-"+t.getId());
            t.setDaemon(true);
            return t;
          }
        },
        (r, e) -> { // fast reject policy
          rejected.incrementAndGet();
          throw new RejectedExecutionException("Bulkhead "+name+" full");
        });
    this.exec.prestartAllCoreThreads();
  }

  public <T> T call(Callable<T> task, Supplier<T> fallback) {
    submitted.incrementAndGet();
    Future<T> f = exec.submit(task);
    try {
      return f.get(timeout.toMillis(), TimeUnit.MILLISECONDS);
    } catch (RejectedExecutionException rex) {
      // queue full -> fallback
      return fallback.get();
    } catch (TimeoutException tex) {
      f.cancel(true);
      return fallback.get();
    } catch (InterruptedException ie) {
      Thread.currentThread().interrupt();
      return fallback.get();
    } catch (ExecutionException ee) {
      // downstream failed; let caller decide or fallback here
      return fallback.get();
    }
  }

  public Map<String, Object> metrics() {
    return Map.of(
        "name", name,
        "poolSize", exec.getPoolSize(),
        "active", exec.getActiveCount(),
        "queueSize", exec.getQueue().size(),
        "submitted", submitted.get(),
        "rejected", rejected.get(),
        "completed", exec.getCompletedTaskCount()
    );
  }

  public void shutdown() { exec.shutdownNow(); }
}

// === Demo downstreams (simulate latency/behavior) ===
final class Downstreams {
  static String search(String q) throws Exception {
    Thread.sleep(60); // normally fast
    return "search:" + q;
  }
  static String profile(String user) throws Exception {
    Thread.sleep(180); // moderate
    return "profile:" + user;
  }
  static String billing(String user) throws Exception {
    Thread.sleep(800); // often slow -> will saturate
    return "billing:" + user;
  }
}

// === App wiring: 3 bulkheads, one per dependency ===
public class BulkheadDemo {
  public static void main(String[] args) throws Exception {
    Bulkhead bhSearch  = new Bulkhead("search" , 16, 100, Duration.ofMillis(200));
    Bulkhead bhProfile = new Bulkhead("profile",  8,  50, Duration.ofMillis(300));
    Bulkhead bhBilling = new Bulkhead("billing",  4,  20, Duration.ofMillis(300)); // small on purpose

    // fire a mixed load
    ExecutorService load = Executors.newFixedThreadPool(32);

    Runnable userRequest = () -> {
      String user = "u" + ThreadLocalRandom.current().nextInt(1000);
      String q    = "q" + ThreadLocalRandom.current().nextInt(1000);

      // Each call is isolated in its own bulkhead; each has its own fallback.
      String s = bhSearch.call(() -> Downstreams.search(q),
          () -> "search:FALLBACK");

      String p = bhProfile.call(() -> Downstreams.profile(user),
          () -> "profile:CACHED");

      String b = bhBilling.call(() -> Downstreams.billing(user),
          () -> "billing:DEFERRED"); // immediate degrade when saturated/slow

      // Do something with results
      // System.out.println(s + " | " + p + " | " + b);
    };

    // Submit many concurrent requests to show isolation under stress
    long start = System.currentTimeMillis();
    int total = 600;
    CountDownLatch latch = new CountDownLatch(total);
    for (int i = 0; i < total; i++) {
      load.submit(() -> { try { userRequest.run(); } finally { latch.countDown(); } });
    }
    latch.await();
    long ms = System.currentTimeMillis() - start;

    // Print metrics (billing should show rejections; others should be healthy)
    System.out.println("Completed " + total + " requests in ~" + ms + " ms\n");
    for (Bulkhead bh : new Bulkhead[]{bhSearch, bhProfile, bhBilling}) {
      System.out.println(bh.metrics());
    }

    // Cleanup
    load.shutdownNow();
    bhSearch.shutdown(); bhProfile.shutdown(); bhBilling.shutdown();
  }
}
```

**What to observe in the demo**

-   `billing` has small capacity + long latency → its bulkhead **rejects** and returns `billing:DEFERRED` quickly.

-   `search` and `profile` keep serving normally — **no thread starvation** despite billing slowness.

-   Metrics show **queue sizes** and **rejected** counts per bulkhead.


> Swap the primitives to **Semaphore bulkheads** for non-blocking stacks:
>
> -   Replace the pool with `Semaphore permits=N`; run work on a shared executor; `tryAcquire()` → execute, else fallback.
>

---

## Known Uses

-   Netflix/Hystrix thread-pool isolation per dependency; successors in **Resilience4j** (semaphore/thread pool bulkheads).

-   High-traffic APIs separating **user** vs **batch** pools to protect interactive latency.

-   DB connection pools **per feature** to avoid starvation by background jobs.


---

## Related Patterns

-   **Circuit Breaker** — stop sending traffic to a failing dependency; combine with bulkheads.

-   **Timeouts & Retries** — must be **short and bounded** inside each bulkhead.

-   **Backpressure** — bulkhead rejections are a form of backpressure.

-   **Priority Queue / Load Shedding** — complement to prefer critical work.

-   **Ambassador (Sidecar)** — can enforce bulkhead-like limits at the proxy level.
