
# Concurrency / Parallelism Pattern — Read–Write Lock

## Pattern Name and Classification

-   **Name:** Read–Write Lock

-   **Classification:** Synchronization & coordination pattern (multi-reader/single-writer)


## Intent

Allow **multiple concurrent readers** to access shared data when there is **no writer**, but **exclusive access** when a writer updates it. This improves throughput for **read-mostly** workloads while preserving correctness.

## Also Known As

-   Shared/Exclusive Lock

-   Multi-Reader/Single-Writer (MR/SW) Lock


## Motivation (Forces)

-   **Read-heavy access:** A single mutual-exclusion lock serializes readers unnecessarily.

-   **Correctness:** Writers must see and publish a consistent view; readers must not observe partial updates.

-   **Fairness vs. throughput:** Reader preference can starve writers; writer preference can throttle readers.

-   **Contention vs. complexity:** RW locks add state & transitions (upgrade/downgrade) and may be slower than a plain mutex under low contention.


## Applicability

Use a Read–Write Lock when:

-   The protected data structure is **read far more often than written**.

-   Reads **don’t mutate** shared state and can run in parallel.

-   Writers are relatively **short** and infrequent.


Avoid or adapt when:

-   Writes are frequent or long; a simple mutex may be faster.

-   Your read operations actually mutate (e.g., cache fills) → consider read-through with **lock downgrading** or a separate path.

-   You can **partition** the data and use **lock striping** (often better scalability).


## Structure

```scss
acquireRead()   ───────────────►  many readers proceed (shared)
Clients ──►
             acquireWrite()  ───────────────►  single writer proceeds (exclusive)
```

-   **Shared (read) lock:** Many may hold simultaneously if no writer holds or is waiting (policy dependent).

-   **Exclusive (write) lock:** Only one; excludes all readers/writers.


## Participants

-   **Read Lock:** Shared mode; non-mutating operations.

-   **Write Lock:** Exclusive mode; mutating operations.

-   **Lock Policy:** Reader-bias, writer-bias, or fair (FIFO).

-   **Protected Resource:** The data (map, index, cache, snapshot).


## Collaboration

1.  Readers call `readLock.lock()`; proceed concurrently unless a writer holds the write lock (or is favored by policy).

2.  Writers call `writeLock.lock()`; block until all readers exit, then update exclusively.

3.  Optional **downgrade**: writer acquires read lock *before* releasing write lock to publish a new snapshot atomically.

4.  (Discouraged) Upgrade from read→write can deadlock unless supported atomically (Java’s `ReentrantReadWriteLock` does **not** support upgrade).


## Consequences

**Benefits**

-   Higher throughput under read-dominated workloads.

-   Simple programming model: reads vs. writes.


**Liabilities**

-   **Starvation risk:** With reader preference, writers may wait indefinitely. With writer preference, readers may suffer latency spikes.

-   **Higher overhead** than a plain mutex under light contention.

-   **Upgrade pitfalls:** Naive read→write upgrade can deadlock.

-   **Coarse granularity:** Still a single lock; may limit scalability vs. partitioned/lock-free designs.


## Implementation (Key Points)

-   **Java choices:**

    -   `ReentrantReadWriteLock` (RRWL): shared/exclusive; reentrancy; optional fairness. No optimistic reads. No upgrade. Supports **downgrade** (write→read).

    -   `StampedLock`: modes **write**, **read**, and **optimistic read**; not reentrant; supports validate-and-retry; downgrading supported. Faster under contention but trickier to use.

-   **Fairness:** `new ReentrantReadWriteLock(true)` reduces starvation (at some throughput cost).

-   **Downgrading pattern:** acquire read lock while holding write, then release write—ensures readers see a fully published state.

-   **Time-bounded waits:** Prefer `tryLock(timeout)` for responsiveness.

-   **Granularity:** Consider **lock striping** (per-bucket locks) or **copy-on-write** for very read-heavy immutable structures.

-   **Metrics:** Track contention (queue length), time to acquire write, time spent under write, and read concurrency.


---

## Sample Code (Java 17)

### 1) Read-Mostly Cache with `ReentrantReadWriteLock`, Downgrading, and Fairness

```java
// File: ReadWriteLockDemo.java
// Compile: javac ReadWriteLockDemo.java
// Run:     java ReadWriteLockDemo
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Function;

public class ReadWriteLockDemo {

  /** A read-mostly cache that computes missing values with writer downgrading. */
  static final class ReadMostlyCache<K,V> {
    private final Map<K,V> map = new HashMap<>();
    private final ReentrantReadWriteLock rw = new ReentrantReadWriteLock(true); // fair policy
    private final Lock r = rw.readLock();
    private final Lock w = rw.writeLock();
    private final Function<K,V> loader;

    public ReadMostlyCache(Function<K,V> loader) {
      this.loader = Objects.requireNonNull(loader);
    }

    /** Get-or-load with double-check and lock **downgrading** to publish snapshot safely. */
    public V get(K key) {
      V v;

      // Fast path: readers run concurrently
      r.lock();
      try {
        v = map.get(key);
        if (v != null) return v;
      } finally {
        r.unlock();
      }

      // Miss: take write lock to compute once
      w.lock();
      try {
        // Re-check under write (another writer may have populated)
        v = map.get(key);
        if (v == null) {
          v = loader.apply(key);
          map.put(key, v);
        }

        // ---- Downgrade: acquire read before releasing write ----
        r.lock();
      } finally {
        w.unlock();
      }
      try {
        // Now holding read lock; callers can continue to read snapshot safely
        return v;
      } finally {
        r.unlock();
      }
    }

    /** Clear all entries (exclusive). */
    public void clear() {
      w.lock();
      try { map.clear(); }
      finally { w.unlock(); }
    }

    public int size() {
      r.lock();
      try { return map.size(); }
      finally { r.unlock(); }
    }
  }

  public static void main(String[] args) throws Exception {
    ReadMostlyCache<String,String> cache =
        new ReadMostlyCache<>(k -> {
          sleep(20); // simulate expensive load
          return "val:" + k;
        });

    // Simulate many readers and occasional writers
    ExecutorService pool = Executors.newFixedThreadPool(Math.max(4, Runtime.getRuntime().availableProcessors()));
    List<Callable<Void>> tasks = new ArrayList<>();

    for (int i = 0; i < 16; i++) {
      final int id = i;
      tasks.add(() -> {
        Random rnd = new Random(42 + id);
        for (int j = 0; j < 200; j++) {
          String k = "k" + rnd.nextInt(8); // hot set → high read concurrency
          cache.get(k);
        }
        return null;
      });
    }

    // Occasional writer clearing cache (exclusive)
    tasks.add(() -> { for (int i=0;i<5;i++){ sleep(200); cache.clear(); } return null; });

    long t0 = System.nanoTime();
    pool.invokeAll(tasks);
    pool.shutdown();
    pool.awaitTermination(5, TimeUnit.SECONDS);
    long t1 = System.nanoTime();
    System.out.printf("done; size=%d; elapsed=%.1fms%n", cache.size(), (t1 - t0)/1e6);
  }

  static void sleep(long ms){ try{ Thread.sleep(ms);}catch(InterruptedException e){ Thread.currentThread().interrupt(); } }
}
```

**What this shows**

-   **Concurrent reads** via the read lock.

-   **Double-checked** load under write lock to avoid duplicate work.

-   **Downgrading** (write→read) to publish and then continue in read mode without opening a race.

-   **Fair** RW lock to reduce writer starvation.


---

### 2) High-throughput reads with `StampedLock` and **Optimistic Read**

```java
// File: StampedLockCounter.java
// Compile: javac StampedLockCounter.java
// Run:     java StampedLockCounter
import java.util.concurrent.*;
import java.util.concurrent.locks.*;

public class StampedLockCounter {
  private final StampedLock sl = new StampedLock();
  private long value;

  public long get() {
    long stamp = sl.tryOptimisticRead();    // non-blocking, returns stamp
    long v = value;                         // read state
    if (!sl.validate(stamp)) {              // somebody wrote? fall back to read lock
      stamp = sl.readLock();
      try { v = value; }
      finally { sl.unlockRead(stamp); }
    }
    return v;
  }

  public void add(long delta) {
    long stamp = sl.writeLock();
    try { value += delta; }
    finally { sl.unlockWrite(stamp); }
  }

  public static void main(String[] args) throws Exception {
    StampedLockCounter c = new StampedLockCounter();
    ExecutorService pool = Executors.newFixedThreadPool(8);

    // Writers
    for (int i=0;i<2;i++) pool.submit(() -> { for (int k=0;k<100_000;k++) c.add(1); });

    // Readers
    for (int i=0;i<6;i++) pool.submit(() -> { long s=0; for (int k=0;k<200_000;k++) s+=c.get(); });

    pool.shutdown();
    pool.awaitTermination(5, TimeUnit.SECONDS);
    System.out.println("value=" + c.get());
  }
}
```

**What this shows**

-   **Optimistic read** path is lock-free when uncontended; validated cheaply.

-   Falls back to **pessimistic** read lock on conflict.

-   `StampedLock` is **not reentrant**; avoid reentrancy and be careful with `try/finally`.


---

## Known Uses

-   In-memory **indexes/caches** where reads dominate.

-   **Routing tables**, configuration snapshots, metrics registries.

-   **Text/AST** read pipelines with rare structural edits.

-   JVM libraries: `ReentrantReadWriteLock` (JUC), `StampedLock` used in high-throughput structures.


## Related Patterns

-   **Mutex (Monitor Lock):** Simpler alternative when contention is low or writes are frequent.

-   **Copy-On-Write / Immutability:** Alternative for very read-heavy data; writers replace the whole snapshot.

-   **Lock Striping / Sharding:** Partitioned locks to increase parallelism.

-   **RCU (Read-Copy-Update):** Userspace read-mostly technique with versioned pointers and deferred reclamation.

-   **Actor / Single-Writer:** Serialize mutation to one thread to avoid shared locks.


---

### Practical Tips

-   Measure before adopting RW locks; under low contention, a **plain `synchronized`** or `ReentrantLock` can be faster.

-   Choose **fairness** when writer starvation is unacceptable; otherwise stick to default (unfair) for throughput.

-   **Never upgrade** from read→write with `ReentrantReadWriteLock`; release read and try write (or redesign).

-   Use **downgrading** (write→read) to publish atomically.

-   Prefer **lock striping** if operations target independent keys (e.g., bucketized maps).

-   With `StampedLock`, **always** `unlock` with the exact mode’s stamp; use `try/finally`.

-   Keep write sections **short**; consider batching updates to amortize exclusive time.
