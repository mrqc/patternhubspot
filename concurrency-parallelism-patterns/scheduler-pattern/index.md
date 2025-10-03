
# Concurrency / Parallelism Pattern — Scheduler

## Pattern Name and Classification

-   **Name:** Scheduler

-   **Classification:** Coordination & orchestration pattern (time- and policy-based execution of tasks)


## Intent

Select **what** runs **when** (and possibly **where**) based on time, priority, and resource policies. A scheduler accepts jobs, decides ordering and timing, and dispatches them to executors/workers while honoring constraints like periodicity, deadlines, fairness, and limits.

## Also Known As

-   Dispatcher / Orchestrator

-   Job / Task / Timer Scheduler

-   Timer Wheel (data-structure specific)

-   Executor (when tightly coupled with a thread pool)


## Motivation (Forces)

-   **Timing:** Run things later, at fixed delay/rate, or by calendar.

-   **Throughput vs. fairness:** Keep workers busy while preventing starvation.

-   **Priorities & deadlines:** Some jobs are more urgent; some have SLAs.

-   **Isolation & QoS:** Per-tenant quotas; rate-limits.

-   **Scalability:** Efficiently manage large numbers of timers and jobs.

-   **Fault tolerance:** Recover after crashes; deduplicate; avoid double-run.

-   **Cost:** Timer data-structures and wakeups vs. precision and power.


## Applicability

Use a Scheduler when you need to:

-   Run **deferred** or **periodic** jobs (maintenance, cache refresh, analytics).

-   Control **concurrency** and **ordering** (priority queues, FIFO per key, deadlines).

-   Enforce **fair sharing** or **rate limits** across tenants/queues.

-   Centralize orchestration for pipelines (cron-like plans, DAGs).


Avoid/Adapt when:

-   Work is best driven by **event arrival** rather than time (use Reactor/Proactor).

-   You only need a handful of timers → a simple `ScheduledExecutorService` suffices.

-   Strict hard real-time guarantees are required (use an RTOS / specialized schedulers).


## Structure

```bash
Client  ─►  Job API ─►  Run Queue(s) (time-ordered &/or priority-ordered)
                              │
                        Dispatcher (polls next-eligible jobs)
                              │
                         Worker Pool / Executor  ─►  Job Execution
                              │
                       Feedback (success/failure, reschedule, backoff)
```

## Participants

-   **Job API:** `scheduleOnce`, `scheduleAtFixedRate`, `scheduleWithFixedDelay`, `scheduleNext(Trigger)`, `cancel`.

-   **Clock/Time Source:** Monotonic + wall clock (for absolute triggers).

-   **Run Queue:** Data structure that orders jobs by **next run time** (min-heap), possibly secondarily by **priority**.

-   **Dispatcher:** Takes due jobs from the run queue, hands them to workers, updates next run time or removes them.

-   **Workers / Executor:** Thread pool or remote agents that execute job runnables/callables.

-   **Policy Modules (optional):** Rate limiter, fairness (per-key queues), backoff, deadlines.

-   **Persistence (optional):** Durable store for at-least-once scheduling.


## Collaboration

1.  Client submits a job with a trigger (time or rule) and optional priority.

2.  Scheduler enqueues it ordered by **nextRunAt**.

3.  Dispatcher wakes when *head* is due, promotes job(s) to the executor respecting concurrency limits.

4.  Worker executes the task; result & error feed back to the scheduler:

    -   one-shot → remove

    -   periodic/fixed-delay → compute next run and re-enqueue

    -   error → apply backoff / retry policy

5.  Cancellation removes or tombstones the job.


## Consequences

**Benefits**

-   Centralized timing and policy; decouples *when* from *what*.

-   Smooths load (jitter, backoff) and improves fairness.

-   Enables deadlines and priority handling.


**Liabilities**

-   Requires careful **time handling** (clock drift, DST, leap seconds).

-   **Starvation** if priorities are naive; need aging/fairness.

-   **Thundering herd** if many jobs share the same instant; use jitter/batching.

-   If persistent, must address **exactly-once vs. at-least-once** semantics.


## Implementation (Key Points)

-   **Data structures:**

    -   Few timers: `DelayQueue` or min-heap (priority queue).

    -   Many timers: **Hierarchical timing wheel** (near O(1) enqueue/expire).

-   **Policies:** FIFO, priority, Weighted Fair Queuing, Earliest Deadline First (EDF), Rate limiting.

-   **Jitter:** Randomize next fire time for periodic fleets to avoid spikes.

-   **Backoff:** Exponential + jitter on failures.

-   **Calendar vs. interval:** Model both; “fixed-rate” vs “fixed-delay” semantics.

-   **Threading:** A single dispatcher thread is common; workers from a pool.

-   **Java choices:**

    -   `ScheduledThreadPoolExecutor` (pragmatic default).

    -   Custom `DelayQueue` for more control (priority, fairness).

    -   Virtual threads (JDK 21+) if jobs block on I/O.

-   **Durability:** For crash safety, store jobs in a log/DB and rehydrate on startup.


---

## Sample Code (Java 17): Minimal Pluggable Scheduler

Features:

-   One-shot, **fixed-rate**, **fixed-delay**, and **custom trigger** scheduling

-   Priority & cancellation

-   Backoff on failure with jitter

-   Backed by `DelayQueue` + worker `ExecutorService`


```java
// File: SchedulerDemo.java
// Compile: javac SchedulerDemo.java
// Run:     java SchedulerDemo
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.function.Supplier;

/** Public API returned to caller to cancel jobs. */
interface ScheduledHandle {
  boolean cancel();
  boolean isCancelled();
}

/** Trigger computes the next run time after a given instant (or empty to stop). */
@FunctionalInterface
interface Trigger {
  Optional<Instant> nextAfter(Instant lastRunEnd);
  static Trigger onceAt(Instant when) {
    return last -> (last == null) ? Optional.of(when) : Optional.empty();
  }
  static Trigger fixedRate(Duration period, Instant start) {
    return lastEnd -> Optional.of((lastEnd == null ? start : lastEnd.plus(period)));
  }
  static Trigger fixedDelay(Duration delay, Instant start) {
    return lastEnd -> Optional.of((lastEnd == null ? start : Instant.now().plus(delay)));
  }
}

/** A scheduled job with timing and priority, implements Delayed for DelayQueue. */
final class ScheduledJob implements Delayed, ScheduledHandle {
  private static final AtomicLong SEQ = new AtomicLong();
  final long id = SEQ.incrementAndGet();
  final Runnable task;
  final int priority; // lower = more important
  final Trigger trigger;
  volatile Instant nextRunAt;   // wall time of next execution
  volatile boolean cancelled = false;

  // backoff state
  int attempts = 0;

  ScheduledJob(Runnable task, int priority, Trigger trigger, Instant first) {
    this.task = task; this.priority = priority; this.trigger = trigger; this.nextRunAt = first;
  }

  @Override public long getDelay(TimeUnit unit) {
    long nanos = Duration.between(Instant.now(), nextRunAt).toNanos();
    return unit.convert(nanos, TimeUnit.NANOSECONDS);
  }
  @Override public int compareTo(Delayed o) {
    ScheduledJob other = (ScheduledJob) o;
    int cmp = this.nextRunAt.compareTo(other.nextRunAt);
    if (cmp != 0) return cmp;
    cmp = Integer.compare(this.priority, other.priority);
    if (cmp != 0) return cmp;
    return Long.compare(this.id, other.id);
  }
  @Override public boolean cancel() { return cancelled = true; }
  @Override public boolean isCancelled() { return cancelled; }
}

/** The Scheduler engine. */
final class Scheduler implements AutoCloseable {
  private final DelayQueue<ScheduledJob> queue = new DelayQueue<>();
  private final ExecutorService workers;
  private final Thread dispatcher;
  private final AtomicBoolean running = new AtomicBoolean(true);

  Scheduler(int workerThreads) {
    this.workers = Executors.newFixedThreadPool(workerThreads, r -> {
      Thread t = new Thread(r, "sched-worker"); t.setDaemon(true); return t;
    });
    this.dispatcher = new Thread(this::loop, "sched-dispatcher");
    this.dispatcher.setDaemon(true);
    this.dispatcher.start();
  }

  public ScheduledHandle schedule(Runnable task, int priority, Trigger trigger) {
    Instant first = trigger.nextAfter(null).orElseThrow(() -> new IllegalArgumentException("no first fire"));
    ScheduledJob job = new ScheduledJob(wrap(task), priority, trigger, first);
    queue.offer(job);
    return job;
  }

  /** Wrap job to add default backoff-on-failure policy. */
  private Runnable wrap(Runnable task) {
    return () -> {
      try {
        task.run();
      } catch (Throwable t) {
        // Log & rethrow to let the dispatcher schedule backoff
        System.err.println("[job] error: " + t);
        throw t;
      }
    };
  }

  private void loop() {
    while (running.get()) {
      try {
        ScheduledJob job = queue.poll(500, TimeUnit.MILLISECONDS);
        if (job == null) continue;
        if (job.cancelled) continue;

        // Dispatch to worker
        workers.submit(() -> {
          Instant end = Instant.now();
          boolean ok = true;
          try {
            job.task.run();
            job.attempts = 0; // reset on success
          } catch (Throwable t) {
            ok = false;
          } finally {
            reschedule(job, ok, end);
          }
        });
      } catch (InterruptedException ie) {
        Thread.currentThread().interrupt();
      }
    }
  }

  /** Compute next execution time (trigger or backoff). */
  private void reschedule(ScheduledJob job, boolean ok, Instant lastRunEnd) {
    if (job.cancelled) return;
    Optional<Instant> next = job.trigger.nextAfter(lastRunEnd);
    if (next.isEmpty()) return; // one-shot completed

    Instant when = next.get();
    if (!ok) {
      // exponential backoff with jitter, capped to 1 minute
      int a = Math.min(6, ++job.attempts);
      long baseMs = (1L << a) * 100L; // 100ms, 200, 400, ...
      long jitter = ThreadLocalRandom.current().nextLong(0, baseMs / 2 + 1);
      when = Instant.now().plusMillis(Math.min(60_000, baseMs + jitter));
    }
    job.nextRunAt = when;
    queue.offer(job);
  }

  @Override public void close() {
    running.set(false);
    dispatcher.interrupt();
    workers.shutdownNow();
  }
}

/** Demo */
public class SchedulerDemo {
  public static void main(String[] args) throws Exception {
    try (Scheduler scheduler = new Scheduler(Math.max(2, Runtime.getRuntime().availableProcessors() - 1))) {
      // One-shot in 500ms
      scheduler.schedule(() -> System.out.println(ts() + " one-shot!"), 5,
          Trigger.onceAt(Instant.now().plusMillis(500)));

      // Fixed rate every 300ms starting now
      scheduler.schedule(() -> System.out.println(ts() + " rate A"),
          10, Trigger.fixedRate(Duration.ofMillis(300), Instant.now()));

      // Fixed delay of 700ms after each run
      scheduler.schedule(() -> {
        System.out.println(ts() + " delay B (work ~200ms)");
        sleep(200);
      }, 10, Trigger.fixedDelay(Duration.ofMillis(700), Instant.now()));

      // Priority demo: higher priority (smaller number) wins on ties
      scheduler.schedule(() -> System.out.println(ts() + " HIGH prio tick"),
          0, Trigger.fixedRate(Duration.ofSeconds(1), Instant.now()));

      // Failure + backoff demo
      AtomicInteger n = new AtomicInteger();
      scheduler.schedule(() -> {
        int k = n.incrementAndGet();
        System.out.println(ts() + " flaky " + k);
        if (k % 3 != 0) throw new RuntimeException("simulated");
      }, 5, Trigger.fixedRate(Duration.ofMillis(250), Instant.now()));

      // Run the demo for ~5 seconds
      Thread.sleep(5000);
    }
    System.out.println("done.");
  }

  static String ts() { return ZonedDateTime.now().toLocalTime().toString(); }
  static void sleep(long ms){ try{ Thread.sleep(ms);}catch(InterruptedException e){ Thread.currentThread().interrupt(); } }
}
```

**What the sample shows**

-   Time-ordered **`DelayQueue`** drives eligibility; secondary ordering by **priority**.

-   API supports **once**, **fixed-rate**, **fixed-delay**, and **custom triggers**.

-   **Backoff with jitter** on failures; successful runs reset attempts.

-   **Cancellation** via `ScheduledHandle` (already supported by the `ScheduledJob`).


> For production: add persistence (WAL), idempotency keys, tenant-aware fairness, metrics, and a multi-dispatcher / multi-partition layout.

---

## Known Uses

-   **JDK `ScheduledThreadPoolExecutor` / Quartz / Spring Scheduling**—general-purpose in-process scheduling.

-   **Distributed orchestrators**—Airflow, Argo, Kubernetes CronJobs (calendar-based batch).

-   **Stream processors**—event-time/timer services (Flink/Kafka Streams) schedule per-key timers.

-   **Databases & caches**—TTL expiry wheels, background compaction, checkpointing.

-   **OS/process schedulers**—CFS, EDF (same principles at a different layer).


## Related Patterns

-   **Producer–Consumer:** Scheduler produces ready tasks; workers consume.

-   **Rate Limiter / Backoff:** Often embedded as policies.

-   **Reactor / Leader–Follower:** Event-loop based schedulers are specialized Reactors.

-   **Work Stealing / Fork–Join:** Policies for *how* to assign work post-eligibility.

-   **Circuit Breaker:** Combined with backoff to schedule health checks and retries.

-   **Cron / Trigger:** Rule describing the time dimension of scheduling.


---

### Practical Tips

-   Prefer **fixed-rate** for *cadence* (attempt to keep period); **fixed-delay** for *spacing*.

-   Add **jitter** for fleets of periodic tasks to avoid synchronized spikes.

-   Separate **eligibility** (time) from **dispatch policy** (priority, fairness, quotas).

-   For large timer counts, use a **hierarchical timing wheel**; heaps `O(log n)` may become costly.

-   Persist schedule state if you must survive restarts; **at-least-once** is easier than **exactly-once**.

-   Monitor **due-lag** (now − nextRunAt), queue length, task latency, failure rate, and backoff levels.
