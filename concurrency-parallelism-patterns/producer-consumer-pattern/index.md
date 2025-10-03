
# Concurrency / Parallelism Pattern — Producer–Consumer

## Pattern Name and Classification

-   **Name:** Producer–Consumer

-   **Classification:** Concurrency coordination & buffering pattern (decouples work production from work consumption with a queue)


## Intent

Decouple **producers** that create work from **consumers** that process it using a **buffer/queue**. This smooths bursts, enables **backpressure**, and lets both sides scale independently.

## Also Known As

-   Bounded Buffer

-   Work Queue / Task Queue

-   Pipeline Stage (when chained)


## Motivation (Forces)

-   **Rate mismatch:** Producers may be bursty; consumers have steady capacity. A queue absorbs bursts.

-   **Isolation:** Failures or slowness on one side shouldn’t immediately stall the other; with a **bounded** queue it does so *gracefully*.

-   **Throughput vs. latency:** Bigger batches increase throughput; small batches reduce latency.

-   **Backpressure:** Bounded queues force producers to block/reject when downstream is overwhelmed.

-   **Coordination cost:** Need efficient synchronization, shutdown semantics, and error propagation.


## Applicability

Use Producer–Consumer when:

-   Work arrives **asynchronously** (events, network, files) and processing is **independent** per item.

-   You need to **smooth bursts**, tolerate variable processing time, or **parallelize** consumers.

-   You want **backpressure** instead of dropping data silently.


Avoid/Adapt when:

-   Each item depends on the previous one (strong ordering/causality) and reordering is unacceptable.

-   Work is extremely small and the queue overhead dominates → consider batching or lock-free designs.

-   You need exactly-once semantics across processes → look at durable queues/streams.


## Structure

```rust
Producers ---> [ Bounded Queue ] ---> Consumers
                  ^       |
               backpressure (block/timeout/reject)
```

## Participants

-   **Producer(s):** Create items (tasks/messages) and `offer/put` them into the queue.

-   **Buffer/Queue:** Thread-safe bounded buffer (e.g., `ArrayBlockingQueue`, ring buffer).

-   **Consumer(s):** Take items (`take/poll`), process, optionally emit results downstream.

-   **Coordinator (optional):** Starts/stops pools, handles errors and shutdown signals.


## Collaboration

1.  Producers `offer/put` items; if the queue is full, policy decides: **block**, **timeout**, or **drop/fail**.

2.  Consumers `take/poll` items and process them; if the queue is empty, they block or wait with timeout.

3.  Shutdown via **sentinel (“poison pill”)**, **cancellation flag**, or closing the queue abstraction.

4.  Errors are handled per item; severe faults can trigger draining and stop.


## Consequences

**Benefits**

-   Smooths traffic; **backpressure** protects downstream.

-   Simple way to **parallelize** (N consumers).

-   Decouples rates and failure domains.


**Liabilities / Trade-offs**

-   Adds **latency** and extra memory (buffer).

-   Requires careful **shutdown** to avoid lost or duplicated work.

-   Potential **head-of-line blocking** if items vary a lot in cost; consider sharding or work-stealing.


## Implementation (Key Points)

-   Prefer **bounded** queues; choose a **rejection/backpressure** policy (block, timeout, drop, shed).

-   Use `ArrayBlockingQueue` or `LinkedBlockingQueue` (bounded). `SynchronousQueue` for direct handoff.

-   For very high throughput & low latency, consider **single-producer/single-consumer** ring buffers or frameworks (LMAX Disruptor).

-   Handle **poison pill** or **cancellation** cleanly; ensure consumers exit.

-   Instrument: queue size, producer block time, consumer throughput, error rate.

-   If items are heterogeneous, add **priorities** (`PriorityBlockingQueue`) or **multiple queues** per class of work.

-   Preserve ordering if needed by **key-based sharding** (route same key to the same consumer).


---

## Sample Code (Java 17): Bounded Queue with Backpressure, Multiple Producers/Consumers, Graceful Shutdown

> Features:
>
> -   `ArrayBlockingQueue` (bounded) → natural backpressure
>
> -   Producers block with timeout (avoid deadlock, observe overload)
>
> -   Consumers process with retries & metrics
>
> -   **Poison pills** to stop consumers cleanly
>
> -   Optional **batching** for better throughput
>

```java
// File: ProducerConsumerDemo.java
// Compile: javac ProducerConsumerDemo.java
// Run:     java ProducerConsumerDemo  (then Ctrl+C to stop early if you like)
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

public class ProducerConsumerDemo {

  // ---- Work item ----
  static final class Job {
    final long id;
    final String payload;
    Job(long id, String payload) { this.id = id; this.payload = payload; }
    @Override public String toString() { return "Job(" + id + "," + payload + ")"; }
  }

  // A special sentinel to signal shutdown
  static final Job POISON = new Job(-1, "<poison>");

  public static void main(String[] args) throws Exception {
    final int queueCapacity = 10_000;
    final int producers = 3;
    final int consumers = Math.max(2, Runtime.getRuntime().availableProcessors());
    final ArrayBlockingQueue<Job> queue = new ArrayBlockingQueue<>(queueCapacity);

    final AtomicBoolean running = new AtomicBoolean(true);
    final AtomicLong produced = new AtomicLong();
    final AtomicLong consumed = new AtomicLong();
    final AtomicLong dropped  = new AtomicLong();
    final AtomicLong retried  = new AtomicLong();

    // --- Producer pool ---
    ExecutorService prodPool = Executors.newFixedThreadPool(producers, named("producer"));
    for (int p = 0; p < producers; p++) {
      final int pid = p;
      prodPool.submit(() -> {
        long seq = 0;
        Random rnd = new Random(42 + pid);
        try {
          while (running.get()) {
            Job j = new Job(((long)pid<<48) | seq++, "data-" + rnd.nextInt(1_000_000));
            // backpressure policy: try to offer with timeout; if fails, drop and count
            boolean ok = queue.offer(j, 100, TimeUnit.MILLISECONDS);
            if (ok) produced.incrementAndGet();
            else dropped.incrementAndGet(); // could also block indefinitely or shed load upstream
            // optional pacing to simulate burstiness
            if ((seq & 0xff) == 0) Thread.sleep(1);
          }
        } catch (InterruptedException ie) {
          Thread.currentThread().interrupt();
        }
      });
    }

    // --- Consumer pool ---
    ExecutorService consPool = Executors.newFixedThreadPool(consumers, named("consumer"));
    for (int c = 0; c < consumers; c++) {
      consPool.submit(() -> {
        try {
          List<Job> batch = new ArrayList<>(256);
          while (true) {
            Job j = queue.take(); // blocks
            if (j == POISON) break;

            // Optional small batch for better throughput
            batch.clear();
            batch.add(j);
            queue.drainTo(batch, 255); // up to 256 per batch (1 + 255)
            // process batch
            for (Job job : batch) {
              if (!process(job)) {
                // simple retry once with small backoff
                retried.incrementAndGet();
                Thread.sleep(5);
                process(job); // ignore second failure for demo
              }
              consumed.incrementAndGet();
            }
          }
        } catch (InterruptedException ie) {
          Thread.currentThread().interrupt();
        }
      });
    }

    // --- Metrics / lifecycle ---
    ScheduledExecutorService metrics = Executors.newSingleThreadScheduledExecutor(named("metrics"));
    metrics.scheduleAtFixedRate(() -> {
      System.out.printf(Locale.ROOT,
          "q=%5d | produced=%d consumed=%d dropped=%d retried=%d%n",
          queue.size(), produced.get(), consumed.get(), dropped.get(), retried.get());
    }, 500, 1000, TimeUnit.MILLISECONDS);

    // Let it run for a few seconds
    Thread.sleep(Duration.ofSeconds(5).toMillis());

    // --- Graceful shutdown: stop producers, then send poison pills for each consumer ---
    running.set(false);
    prodPool.shutdownNow();
    prodPool.awaitTermination(2, TimeUnit.SECONDS);

    for (int i = 0; i < consumers; i++) queue.put(POISON);
    consPool.shutdown();
    consPool.awaitTermination(5, TimeUnit.SECONDS);

    metrics.shutdownNow();
    System.out.println("Done.");
  }

  // Simulated processing; occasionally slow / fails
  static boolean process(Job j) throws InterruptedException {
    // variable cost
    long h = j.id ^ j.payload.hashCode();
    int work = (int)((h & 0x3F) + 1); // 1..64 "units"
    // pretend each unit ~0.1ms
    Thread.sleep(work / 10);
    // random failure ~1%
    return (h & 0xFF) != 0;
  }

  static ThreadFactory named(String prefix) {
    AtomicInteger n = new AtomicInteger(1);
    return r -> { Thread t = new Thread(r, prefix + "-" + n.getAndIncrement()); t.setDaemon(true); return t; };
  }
}
```

**What this shows**

-   **Bounded** `ArrayBlockingQueue` enforces **backpressure**; producers block (with timeout) and count drops.

-   Multiple **producers** and **consumers** with natural parallelism.

-   **Batching** with `drainTo` improves throughput when load is high.

-   **Graceful shutdown** via a **poison pill** per consumer.


---

## Known Uses

-   **Logging pipelines:** Appenders enqueue events; background threads write to disk/network.

-   **ETL / ingestion:** Network readers produce messages; workers parse/transform.

-   **Web servers:** Acceptors enqueue sockets/requests; worker pool processes them.

-   **Telemetry/metrics:** Producers emit points; aggregators consume and batch-send.

-   **Video/image processing:** Decoder produces frames; filters/encoders consume.


## Related Patterns

-   **Pipeline:** Chain multiple producer–consumer stages.

-   **Leader–Follower / Reactor:** Upstream event demux feeding a consumer pool.

-   **Work Stealing:** Alternative load balancing between consumers.

-   **Circuit Breaker / Rate Limiter:** Complementary controls for overload before enqueue.

-   **Backpressure (Reactive Streams):** Protocol-level producer throttling vs. queue-based.

-   **Map–Reduce:** Consumers may themselves be mappers/reducers in a larger dataflow.


---

### Practical Tips

-   **Always bound** queues in servers. Decide: block, timeout, or shed. Surface pressure via metrics.

-   If items vary greatly in cost, **shard by key** (one queue per shard) or use **work stealing**.

-   Use **batching** when downstream supports it; it can cut synchronization and I/O overhead.

-   For at-least-once processing, place the queue on a **durable** substrate (e.g., Kafka/RabbitMQ) and make consumers **idempotent**.

-   Keep handlers **idempotent** and with **timeouts**; isolate failures to items, not threads.

-   Measure: queue depth, producer block time, consumer throughput/latency, and error counts.
