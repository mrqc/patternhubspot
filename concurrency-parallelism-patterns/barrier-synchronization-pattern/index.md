
# Concurrency / Parallelism Pattern — Barrier Synchronization

## Pattern Name and Classification

-   **Name:** Barrier Synchronization

-   **Classification:** Coordination & synchronization pattern (bulk‐synchronous parallel / phase barrier)


## Intent

Make a **group of concurrent tasks** periodically **wait** until **all** tasks reach the same execution point (a *barrier*), then **release them together** into the next phase.

## Also Known As

-   Phase Barrier

-   Rendezvous Point

-   Bulk-Synchronous Step (BSP “superstep” barrier)


## Motivation (Forces)

-   **Deterministic phase changes:** Some algorithms proceed in well-defined rounds (e.g., compute → exchange → reduce).

-   **Safety:** Next phase must not start until *everyone* finished the current one (avoid using partial results).

-   **Throughput vs. wait:** Too many barriers increase idle time; too few risk data races.

-   **Faults & stragglers:** One slow/broken participant stalls the group; need timeouts/broken-barrier recovery.

-   **Dynamic groups:** Number of participants may change (joins/leaves) across phases.


## Applicability

Use when:

-   Work naturally occurs in **rounds** (graph algorithms, Jacobi iteration, cellular automata, stencil codes).

-   You need **consistent cut** semantics between phases (e.g., snapshotting, checkpoint).

-   You coordinate **pipelines** where stages must align at boundaries.


Avoid/Adapt when:

-   Tasks are largely independent or streaming; prefer lock-free queues / backpressure.

-   You need **fine-grained** coordination; a barrier is too coarse.

-   Straggler risk is high; consider timeouts + dynamic rebalancing.


## Structure

```sql
Workers:  [ Phase k work ] ──► wait at Barrier ──► [ Phase k+1 work ] ──► ...
                                 (all arrive → release together)
```

## Participants

-   **Participants/Workers:** N concurrent tasks that meet at the barrier.

-   **Barrier:** Synchronizer that tracks arrivals; when count reaches N, it trips and optionally runs a **barrier action**.

-   **Coordinator (optional):** Adjusts participant count, handles timeouts/cancellation, logs skew.


## Collaboration

1.  Each worker performs its phase-k work.

2.  Each calls `barrier.await()` (optionally with timeout).

3.  When all N arrive, the barrier optionally runs a **barrier action** (e.g., swap buffers, aggregate metrics) and releases all workers to phase k+1.

4.  On timeout/interruption/error, the barrier becomes **broken**; participants handle recovery (abort/retry/reshape).


## Consequences

**Benefits**

-   Clear, simple phase boundaries; easy mental model.

-   Avoids using **incomplete** data from lagging peers.

-   Supports global actions at phase transitions (swap, reduce, snapshot).


**Liabilities**

-   **Head-of-line blocking:** slowest task dictates progress.

-   **Deadlock risk** if someone never arrives.

-   **Over-synchronization:** too many barriers waste parallelism.

-   Requires **robust error handling** (timeouts, “broken” state).


## Implementation (Key Points)

-   **Java primitives:**

    -   `CyclicBarrier` – reusable fixed-N barriers with optional action.

    -   `Phaser` – dynamic parties, multi-phase, hierarchical registration.

-   **Timeouts & recovery:** Use `await(timeout)`; on `BrokenBarrierException`/`TimeoutException` decide to cancel, retry, or reduce N.

-   **Barrier action:** Keep it fast; otherwise it becomes a global bottleneck.

-   **Sense-reversing barrier:** Classic lock-free design for tight loops (educational/low-level).

-   **Metrics:** Measure **phase skew** (max–min arrival times) to detect stragglers.

-   **Cancellation:** Propagate interrupts; call `barrier.reset()` or `phaser.forceTermination()` as needed.

-   **Memory visibility:** Barrier acts as a happens-before edge; safe to read peers’ phase-k results after the barrier.


---

## Sample Code (Java 17): CyclicBarrier & Phaser in a 3-phase BSP loop

> Shows:
>
> -   `CyclicBarrier` with **barrier action** and **timeout**
>
> -   `Phaser` to **add/remove** participants across iterations
>
> -   Clean shutdown on error
>

```java
// File: BarrierSynchronizationDemo.java
// Compile: javac BarrierSynchronizationDemo.java
// Run:     java BarrierSynchronizationDemo
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;

public class BarrierSynchronizationDemo {

  // Simulated shared state per worker (e.g., a slice of an array/graph partition)
  static final class Partition {
    final int id;
    int value;             // computed each phase
    int nextValue;         // write-next buffer (double buffering)
    Partition(int id) { this.id = id; }
  }

  public static void main(String[] args) throws Exception {
    final int workers = 4;
    final int maxPhases = 5;
    final long awaitMs = 1000;

    List<Partition> parts = new ArrayList<>();
    for (int i = 0; i < workers; i++) parts.add(new Partition(i));

    // Barrier action: swap buffers + report phase completion
    AtomicInteger phase = new AtomicInteger(0);
    Runnable onBarrier = () -> {
      for (Partition p : parts) { p.value = p.nextValue; }
      System.out.printf("== phase %d committed ==%n", phase.get());
      phase.incrementAndGet();
    };

    CyclicBarrier barrier = new CyclicBarrier(workers, onBarrier);

    ExecutorService pool = Executors.newFixedThreadPool(workers);
    List<Future<?>> futures = new ArrayList<>();

    for (int i = 0; i < workers; i++) {
      final int idx = i;
      futures.add(pool.submit(() -> {
        Partition me = parts.get(idx);
        try {
          for (int k = 0; k < maxPhases; k++) {
            // ----- Phase work (read others' stable state; write to nextValue) -----
            int neighborSum = 0;
            for (Partition p : parts) neighborSum += p.value; // pretend local + halo read
            me.nextValue = neighborSum + me.id;                // new state for next phase

            // Optional jitter to simulate skew
            if (idx == 0 && k == 2) Thread.sleep(150); // straggler demo

            // ----- Barrier: wait for all to finish phase k -----
            try {
              barrier.await(awaitMs, TimeUnit.MILLISECONDS);
            } catch (TimeoutException te) {
              System.err.println("timeout at phase " + k + " in worker " + idx);
              barrier.reset(); // fail-fast: break the barrier for everyone
              return;
            }
            // After barrier: safe to read others' committed value (onBarrier swapped)
          }
        } catch (InterruptedException e) {
          Thread.currentThread().interrupt();
        } catch (BrokenBarrierException e) {
          // barrier was reset/broken: stop gracefully
        }
      }));
    }

    // (Optional) demonstrate dynamic parties via Phaser for an extra phase:
    Phaser phaser = new Phaser(workers);
    // wait for previous tasks to complete
    for (Future<?> f : futures) f.get();
    pool.shutdown();

    // Register a temporary extra worker for a final clean-up phase
    phaser.register(); // main thread as an extra party
    parts.forEach(p -> p.nextValue = p.value * 2); // prepare
    // arrive from main and wait for imaginary others (no-op here)
    phaser.arriveAndAwaitAdvance();
    System.out.println("Final values: " + parts.stream().map(p -> p.value).toList());
    phaser.forceTermination();
  }
}
```

**How it works**

-   Each worker computes into `nextValue`, then **awaits** the barrier.

-   The **barrier action** swaps `nextValue → value` for all partitions and increments `phase`.

-   A deliberate straggler shows timeout handling; we `reset()` to break others out.

-   `Phaser` snippet hints how to handle **varying participation** (e.g., an extra cleanup phase).


---

## Known Uses

-   **Scientific computing / HPC:** Bulk-synchronous iterations (Jacobi/Gauss-Seidel variants with double buffering), stencil codes.

-   **Graph processing frameworks:** Pregel/Giraph/Gelly supersteps separated by barriers.

-   **MapReduce family:** Map → Shuffle → Reduce stage boundaries.

-   **Iterative ML/optimization:** Synchronous SGD steps; parameter server sync points.

-   **Game engines & simulation:** Frame ticks with world/physics/AI barriers.


## Related Patterns

-   **Fork/Join:** Task decomposition; may insert barriers between stages.

-   **Latch (CountDownLatch):** One-shot synchronization (vs. reusable barrier).

-   **Phaser:** Generalized barrier with dynamic parties and multiple phases.

-   **Reader/Writer Phases:** Alternate read-stable / write-next cycles with barriers.

-   **Actor Model / Active Object:** Avoids shared state; barriers sometimes used for global epochs.

-   **Pipeline / Producer–Consumer:** Streaming alternative; no global stop-the-world.


---

### Practical Tips

-   **Bounded wait:** Always use timeouts; log **phase skew** to find stragglers.

-   Keep **barrier actions short**; do heavy work elsewhere.

-   Prefer `Phaser` when party counts change, or when composing **hierarchical** barriers.

-   Consider **sense-reversing** barriers for ultra-tight loops (CPU-bound kernels).

-   On failure: **break/reset** the barrier, cancel participants, and fail fast—don’t leave threads stuck.

-   Combine with **double buffering** to separate *read stable* vs. *write next* memory and avoid races.
