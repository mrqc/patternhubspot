
# Concurrency / Parallelism Pattern — Fork–Join

## Pattern Name and Classification

-   **Name:** Fork–Join

-   **Classification:** Task-parallel decomposition pattern (divide-and-conquer with work stealing)


## Intent

Recursively **split** a problem into independent sub-problems (**fork**), solve sub-problems in parallel, and **join** their results to form the final answer. A work-stealing scheduler balances load across worker threads.

## Also Known As

-   Divide and Conquer Parallelism

-   Recursive Task Parallelism

-   Work-Stealing Pool pattern


## Motivation (Forces)

-   **Parallelism vs. overhead:** Finer splits expose more parallelism but raise scheduling & merge overhead.

-   **Load balancing:** Subproblems can be irregular; **work stealing** keeps workers busy without centralized coordination.

-   **Blocking hazards:** Fork–Join pools assume mostly compute; blocking I/O can starve the pool unless mitigated.

-   **Determinism vs. speed:** Execution order is nondeterministic; algorithm must be associative (or otherwise safe) for joins.


## Applicability

Use Fork–Join when:

-   The problem fits **divide-and-conquer** (e.g., sort, search, reductions, image/FFT, tree/graph traversals).

-   Subproblems can run **mostly independently** with modest shared state.

-   You can define a sensible **cut-off threshold** for switching to sequential work.


Avoid or adapt when:

-   Work is I/O-bound or frequently blocks (use a different pool or `ManagedBlocker`).

-   Strong ordering/transactions across tasks are required.

-   The computation is tiny (scheduling overhead dominates).


## Structure

```sql
Task(problem):
  if problem small → solve sequentially
  else:
     split into p1, p2, ... pk
     for each pi: fork Task(pi)
     result = join all subresults (combine)
     return result
```

**Runtime:** a **ForkJoinPool** with N worker threads; each thread owns a deque. Workers pop from the head; idle workers **steal** from the tail of others.

## Participants

-   **Recursive Task/Action:** Unit of work; `RecursiveTask<R>` returns a value; `RecursiveAction` is void.

-   **Fork–Join Pool:** Work-stealing scheduler and worker threads.

-   **Join/Combine step:** Merges subresults (must be safe & efficient).

-   **Threshold policy:** Decides when to stop splitting.


## Collaboration

1.  Root task is **submitted** to the pool.

2.  The task tests the **threshold**; if large, it **forks** child tasks.

3.  Workers execute tasks; idle workers **steal** work.

4.  Parent **joins** children, combines results, and completes.


## Consequences

**Benefits**

-   Scales well on multi-core via work stealing (low contention, good cache locality).

-   Simple mental model for divide-and-conquer.

-   Automatic load balancing for irregular workloads.


**Liabilities**

-   Poor performance if threshold is wrong (too fine → overhead; too coarse → underutilization).

-   Blocking ops can stall the pool; need `ManagedBlocker` or a dedicated executor.

-   Non-associative or order-dependent combines can lead to subtle bugs.


## Implementation (Key Points)

-   **Threshold:** Pick empirically (e.g., 1–10k elements for array ops) and parameterize.

-   **Use `invokeAll` / `fork()`+`join()`:** Prefer helping strategies (e.g., compute one subtask directly and `fork()` the other).

-   **Immutability / locality:** Pass indices instead of slicing/allocating.

-   **Avoid I/O:** If unavoidable, wrap with `ForkJoinPool.managedBlock(...)`.

-   **Sizing the pool:** Usually `parallelism = cores` for CPU-bound work; avoid oversubscription with other executors.

-   **Combine efficiently:** For reductions, prefer primitives to avoid boxing.

-   **Observability:** Track steals, task counts, and queue sizes in perf tests.


---

## Sample Code (Java 17): Parallel Sum (RecursiveTask) + Parallel Merge Sort (RecursiveAction)

```java
// File: ForkJoinDemo.java
// Compile: javac ForkJoinDemo.java
// Run:     java ForkJoinDemo
import java.util.*;
import java.util.concurrent.*;
import java.util.stream.LongStream;

/** Parallel sum using RecursiveTask<Long>. */
class SumTask extends RecursiveTask<Long> {
    private static final int THRESHOLD = 10_000; // tune for your workload
    private final long[] arr;
    private final int lo, hi; // [lo, hi)

    SumTask(long[] arr, int lo, int hi) { this.arr = arr; this.lo = lo; this.hi = hi; }

    @Override protected Long compute() {
        int len = hi - lo;
        if (len <= THRESHOLD) {
            long s = 0L;
            for (int i = lo; i < hi; i++) s += arr[i];
            return s;
        }
        int mid = lo + len/2;
        SumTask left = new SumTask(arr, lo, mid);
        SumTask right = new SumTask(arr, mid, hi);
        left.fork();                // fork left
        long r = right.compute();   // compute right directly (help the pool)
        long l = left.join();       // join left
        return l + r;
    }
}

/** Parallel merge sort using RecursiveAction. */
class MergeSortTask extends RecursiveAction {
    private static final int THRESHOLD = 1 << 13; // ~8K
    private final int[] a, buf;
    private final int lo, hi; // [lo, hi)

    MergeSortTask(int[] a, int[] buf, int lo, int hi) { this.a = a; this.buf = buf; this.lo = lo; this.hi = hi; }

    @Override protected void compute() {
        int len = hi - lo;
        if (len <= THRESHOLD) {
            Arrays.sort(a, lo, hi);
            return;
        }
        int mid = lo + len/2;
        var left = new MergeSortTask(a, buf, lo, mid);
        var right = new MergeSortTask(a, buf, mid, hi);
        invokeAll(left, right); // fork both and wait
        merge(lo, mid, hi);
    }

    private void merge(int lo, int mid, int hi) {
        int i = lo, j = mid, k = lo;
        while (i < mid && j < hi) buf[k++] = (a[i] <= a[j]) ? a[i++] : a[j++];
        while (i < mid) buf[k++] = a[i++];
        while (j < hi)  buf[k++] = a[j++];
        System.arraycopy(buf, lo, a, lo, hi - lo);
    }
}

public class ForkJoinDemo {
    public static void main(String[] args) {
        ForkJoinPool pool = new ForkJoinPool(Math.max(1, Runtime.getRuntime().availableProcessors()));

        // ----- Demo 1: Parallel sum -----
        long[] data = LongStream.range(0, 5_000_000).toArray();
        long t0 = System.nanoTime();
        long sum = pool.invoke(new SumTask(data, 0, data.length));
        long t1 = System.nanoTime();
        System.out.printf("Parallel sum=%d in %.1f ms%n", sum, (t1 - t0)/1e6);

        // ----- Demo 2: Parallel merge sort -----
        Random rnd = new Random(42);
        int[] a = rnd.ints(2_000_000).toArray();
        int[] buf = new int[a.length];
        long s0 = System.nanoTime();
        pool.invoke(new MergeSortTask(a, buf, 0, a.length));
        long s1 = System.nanoTime();
        System.out.printf("Parallel sort ok=%b in %.1f ms%n", isSorted(a), (s1 - s0)/1e6);

        pool.shutdown();
    }

    private static boolean isSorted(int[] a) {
        for (int i = 1; i < a.length; i++) if (a[i-1] > a[i]) return false;
        return true;
    }
}
```

**What the code shows**

-   `RecursiveTask` for value-returning reductions and `RecursiveAction` for in-place algorithms.

-   **Thresholds** to switch to sequential work.

-   **Work-stealing** via `ForkJoinPool.invoke(...)`; one branch is computed directly to reduce task overhead.


---

## Known Uses

-   **Java `ForkJoinPool` / `java.util.concurrent`:** Parallel streams, `CompletableFuture` internals, and custom `RecursiveTask/Action`.

-   **Cilk / Intel TBB:** Classic fork–join work-stealing runtimes.

-   **OpenMP tasks:** `#pragma omp task` + `taskwait` realize fork–join DAGs.

-   **Algorithms:** Parallel quick/merge sort, parallel prefix/reduction/scan, N-body tree builds, image processing, game tree search.


## Related Patterns

-   **Map–Reduce:** Also splits & combines, but typically via bulk dataflow with shuffle; fork–join is in-memory recursive.

-   **Pipeline:** Stage parallelism vs. recursive task parallelism.

-   **Barrier Synchronization:** Often used between fork–join **phases**.

-   **Work Stealing Deque:** The scheduling primitive behind fork–join.

-   **Actor Model / Active Object:** Message-driven alternatives; good when tasks are stateful or long-lived.


---

### Practical Tips

-   Start with a **coarse threshold**; lower it until you stop gaining speed (Amdahl’s law + overhead).

-   Keep **combine** steps O(n) with good cache behavior; avoid excessive temporary allocations.

-   Don’t block in a Fork–Join task; if you must, use `ForkJoinPool.managedBlock(...)` or separate executors.

-   For simple reductions/sorts, consider **parallel streams** (`array.parallelSort`, `Arrays.parallelPrefix`) which already tune thresholds well.

-   Measure with realistic data; parallelism helps only when work ≫ overhead.
