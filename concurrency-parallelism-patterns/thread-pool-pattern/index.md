
# Concurrency / Parallelism Pattern — Thread Pool

## Pattern Name and Classification

-   **Name:** Thread Pool

-   **Classification:** Execution & resource management pattern (task scheduling and reuse of worker threads)


## Intent

Maintain a **bounded set of reusable worker threads** and a **work queue** so you can submit short-lived tasks without paying thread-creation cost, while enforcing **concurrency limits**, **backpressure**, and **policies** (priority, fairness, rejection).

## Also Known As

-   Worker Pool

-   Executor / Dispatcher

-   Pool of Threads / Task Executor


## Motivation (Forces)

-   **Throughput vs. limits:** Maximize CPU utilization, but keep a hard ceiling on concurrency to protect the system.

-   **Latency vs. batching:** Larger queues smooth bursts but may add tail latency.

-   **Cost:** Creating/destroying threads is expensive; reuse them.

-   **Backpressure:** When producers outpace consumers, you need blocking, timeouts, or rejections.

-   **Heterogeneous work:** Tasks can be CPU-bound, I/O-bound, or misbehaving (blocking) — policy and sizing must reflect that.

-   **Fairness & priority:** Some tasks should run sooner; starvation must be avoided.


## Applicability

Use a thread pool when:

-   You have **many independent, short/medium-lived tasks** (RPC handlers, jobs, pipeline stages).

-   You need **resource caps** and **isolation** (per-tenant, per-endpoint executors).

-   You want **backpressure** and **rejection policies** under load.


Avoid / adapt when:

-   Tasks are **long-running** or **blocking** heavily → consider virtual threads, or separate pools per class of work.

-   The workload is **embarrassingly parallel & uniform** → `ForkJoinPool` might fit better.

-   Ordering/affinity per key matters → use **sharded** executors (one queue/worker per key).


## Structure

```pgsql
submit(task) ─▶ [ Work Queue ] ─▶ [ Worker Threads ]
                     ▲                   │
                 Rejection          Execute task
                 / backpressure     (run, record metrics, errors)
```

## Participants

-   **Task Producer(s):** Submit units of work (Runnables/Callables).

-   **Work Queue:** Bounded/unbounded; FIFO, priority, or delay.

-   **Worker Threads:** Pull from the queue, execute tasks, report completion.

-   **Scheduler / Executor:** Manages lifecycle, sizing, and policies.

-   **Rejection Policy:** What to do when the pool/queue is full.

-   **Metrics/Controller (optional):** Observes queue depth, utilization; may auto-tune.


## Collaboration

1.  Producer calls `executor.execute/submit`.

2.  Executor enqueues the task or spawns up to `maxThreads` when `coreThreads` are busy.

3.  Workers execute tasks; exceptions are captured and surfaced (via Future or handler).

4.  If saturated, **rejection** or **caller-runs** applies; producer can retry/back off.

5.  Shutdown waits for tasks to complete (graceful) or interrupts (immediate).


## Consequences

**Benefits**

-   Reuses threads → lower overhead and consistent latency.

-   **Backpressure & caps** prevent overload.

-   Encodes **policy** (priority, fairness, timeouts).

-   Clean **abstraction** for task submission vs. execution.


**Liabilities**

-   A single pool can become a **global bottleneck**; isolate by class of work.

-   Wrong sizing → either **underutilization** or **queue explosion**.

-   Blocking tasks in a CPU pool cause **thread starvation**.

-   Unbounded queues can **hide** overload until latency or OOM strikes.


## Implementation (Key Points)

-   **Sizing:**

    -   CPU-bound: ~ `#cores` (±) with small queue.

    -   I/O or blocking: larger pool or **virtual threads** (JDK 21+) + rate limits.

-   **Queue choice:** `ArrayBlockingQueue` (bounded, FIFO), `LinkedBlockingQueue` (optionally bounded), `SynchronousQueue` (direct handoff), `PriorityBlockingQueue` (unbounded priority).

-   **Rejection:** `AbortPolicy` (fail fast), `CallerRunsPolicy` (backpressure), `Discard`/`DiscardOldest` (lossy). Prefer **bounded** + `CallerRuns` for backpressure.

-   **Isolation:** Use **separate pools** per workload (e.g., RPC, background I/O).

-   **Timeouts:** Use `Future#get(timeout)` / `CompletableFuture.orTimeout`.

-   **Monitoring:** active count, queue size, completed tasks, rejections, task latency.

-   **Shutdown:** `shutdown()` (graceful) then `awaitTermination`, finally `shutdownNow()` if needed.

-   **Virtual threads:** For high *blocking* concurrency, `Executors.newVirtualThreadPerTaskExecutor()` simplifies sizing (still apply external rate limits).


---

## Sample Code (Java 17): Bounded Thread Pool with Backpressure, Metrics, and Graceful Shutdown

> What it demonstrates
>
> -   **Bounded** `ArrayBlockingQueue` to enforce backpressure
>
> -   `CallerRunsPolicy` so submitters slow down under load (no silent drop)
>
> -   Named threads, metrics logger, and graceful shutdown
>
> -   Mix of CPU-ish and blocking tasks to show impact
>

```java
// File: ThreadPoolDemo.java
// Compile: javac ThreadPoolDemo.java
// Run:     java ThreadPoolDemo
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;

public class ThreadPoolDemo {

  /** Build a pragmatic bounded thread pool. */
  static ThreadPoolExecutor buildExecutor(String name,
                                          int core,
                                          int max,
                                          int queueCapacity,
                                          Duration keepAlive) {
    var threadFactory = new ThreadFactory() {
      final ThreadFactory def = Executors.defaultThreadFactory();
      final AtomicLong seq = new AtomicLong();
      @Override public Thread newThread(Runnable r) {
        Thread t = def.newThread(r);
        t.setName(name + "-" + seq.incrementAndGet());
        t.setDaemon(true);
        return t;
      }
    };

    var queue = new ArrayBlockingQueue<Runnable>(queueCapacity);

    // Backpressure: when saturated, run in the caller thread (slows producers)
    RejectedExecutionHandler rejection = new ThreadPoolExecutor.CallerRunsPolicy();

    ThreadPoolExecutor ex = new ThreadPoolExecutor(
        core, max, keepAlive.toMillis(), TimeUnit.MILLISECONDS, queue, threadFactory, rejection);
    ex.allowCoreThreadTimeOut(true); // let core threads shrink when idle
    return ex;
  }

  public static void main(String[] args) throws Exception {
    int cores = Math.max(2, Runtime.getRuntime().availableProcessors());
    ThreadPoolExecutor pool = buildExecutor(
        "worker", cores, cores * 2, 10_000, Duration.ofSeconds(30));

    // Simple metrics reporter
    ScheduledExecutorService metrics = Executors.newSingleThreadScheduledExecutor(r -> {
      Thread t = new Thread(r, "metrics"); t.setDaemon(true); return t;
    });
    metrics.scheduleAtFixedRate(() -> {
      System.out.printf(Locale.ROOT,
          "active=%2d, pool=%2d, queued=%5d, completed=%d%n",
          pool.getActiveCount(), pool.getPoolSize(), pool.getQueue().size(), pool.getCompletedTaskCount());
    }, 500, 1000, TimeUnit.MILLISECONDS);

    // Simulated workload: bursty producers
    final int producers = 3;
    ExecutorService prod = Executors.newFixedThreadPool(producers);
    for (int p = 0; p < producers; p++) {
      final int pid = p;
      prod.submit(() -> {
        Random rnd = new Random(42 + pid);
        for (int i = 0; i < 20_000; i++) {
          // Mix of CPU-ish and blocking tasks
          Runnable task = (i % 10 == 0) ? blockingTask(rnd) : cpuishTask(rnd);
          pool.execute(task); // may run in caller if saturated
          if ((i & 0x3FF) == 0) Thread.sleep(1); // burstiness
        }
      });
    }

    // Let the demo run a bit
    prod.shutdown();
    prod.awaitTermination(10, TimeUnit.SECONDS);

    // Graceful shutdown of the pool
    pool.shutdown();
    if (!pool.awaitTermination(10, TimeUnit.SECONDS)) {
      pool.shutdownNow();
    }
    metrics.shutdownNow();
    System.out.println("Done.");
  }

  // ~ CPU-ish task: small compute loop
  static Runnable cpuishTask(Random rnd) {
    int n = 10_000 + rnd.nextInt(10_000);
    return () -> {
      long acc = 0;
      for (int k = 0; k < n; k++) acc += (k ^ 0x9E3779B97F4A7C15L);
      // do something with acc to avoid dead-code elimination
      if ((acc & 1) == 7) System.out.print(""); 
    };
  }

  // ~ Blocking task: sleeps a bit to emulate I/O; demonstrates risk of blocking in compute pool
  static Runnable blockingTask(Random rnd) {
    int ms = 5 + rnd.nextInt(20);
    return () -> {
      try { Thread.sleep(ms); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
    };
  }
}
```

**Why this design**

-   **Bounded queue** keeps memory under control;

-   **CallerRunsPolicy** propagates pressure back to producers;

-   **allowCoreThreadTimeOut(true)** reduces idle cost;

-   Metrics show saturation dynamics (active threads, queue, completed tasks).


> Variants:
>
> -   For **priority**, use a `PriorityBlockingQueue` (unbounded) and wrap tasks in `Comparable`—or implement bucketed executors per priority.
>
> -   For **blocking-heavy** jobs (I/O), either (a) use **virtual threads** (`Executors.newVirtualThreadPerTaskExecutor()`), or (b) separate a dedicated “I/O pool” with higher max and track concurrency at the client.
>

---

## Known Uses

-   **App servers / gateways:** request handling, filter chains, RPC execution.

-   **Background jobs:** email sending, thumbnail generation, compactions.

-   **Pipeline stages:** parse → validate → enrich → persist, each with its own pool.

-   **High-performance libraries:** Netty event-loop offload pools, gRPC server executors, HTTP client connection pools.


## Related Patterns

-   **Producer–Consumer:** A thread pool is a concrete realization (queue + workers).

-   **Work Stealing / Fork–Join:** Alternative scheduler tuned for recursive, CPU-bound tasks.

-   **Scheduler:** Time-based eligibility; can dispatch due tasks into a pool.

-   **Circuit Breaker / Rate Limiter:** Protect a pool from slow/failed dependencies.

-   **Bulkhead / Isolation:** Use **separate pools** to isolate failure domains.

-   **Leader–Follower / Reactor:** Event demux often hands work to a pool.


---

### Practical Tips

-   **Always bound** either the queue or the pool (or both). Unbounded queues hide trouble.

-   Keep **blocking** out of CPU pools; use virtual threads or separate I/O pools.

-   Prefer **`CallerRunsPolicy`** for backpressure in synchronous producers; for async producers, **fail-fast** and retry with jitter.

-   **Instrument**: queue depth, rejections, active threads, task latency (and percentiles).

-   Use **different executors** per tenant/work type to prevent noisy neighbors.

-   For **affinity**, create **sharded executors** keyed by ID (one thread/queue per shard) to preserve order.

-   Don’t forget **shutdown** on application stop—leaking pools prevents JVM exit.
