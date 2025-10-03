
# Concurrency / Parallelism Pattern — Work Stealing

## Pattern Name and Classification

-   **Name:** Work Stealing

-   **Classification:** Task-parallel scheduling pattern (decentralized load balancing)


## Intent

Maximize parallel throughput by letting each worker thread maintain its **own deque of tasks** and, when it runs out of local work, **steal** tasks from the **tail** of another worker’s deque. This balances irregular/recursive workloads without a centralized queue.

## Also Known As

-   Work-Stealing Scheduler

-   Deques + Thieves

-   Steal-on-Idle


## Motivation (Forces)

-   **Irregular parallelism:** Divide-and-conquer or graph traversals produce **unbalanced** subtrees; a static split leaves some threads idle.

-   **Locality & overhead:** A per-thread deque gives **LIFO** execution for local tasks (good cache behavior) while stealing is **rare** and amortized.

-   **Contention vs. balance:** Central queues are simple but become hotspots; stealing spreads contention across deques.

-   **Fork depth vs. granularity:** Finer tasks expose parallelism but increase overhead—stealing helps smooth, not eliminate, that trade-off.


## Applicability

Use Work Stealing when:

-   The workload is **recursive** or **unpredictably skewed** (quicksort, search trees, irregular graphs).

-   Tasks are **short/medium-lived** and can run independently.

-   You can define a **cutoff/threshold** to avoid too-fine forking.


Avoid or adapt when:

-   Tasks **block** often on I/O → prefer separate I/O pool, virtual threads, or `ManagedBlocker`.

-   The workload is perfectly regular → a simpler pool or bulk barrier may suffice.

-   Strong global ordering is required across tasks.


## Structure

```perl
Worker 0             Worker 1             Worker 2             ...
       +---------------+    +---------------+    +---------------+
push → |  [t3][t2][t1] |    |  [u4][u3]     |    |   []          |
       +------^--------+    +------^--------+    +------^--------+
              |   pop()            |   pop()            |   (idle) -> steal from the TAIL of another deque
              |                    |                     └──────────────► takes victim's oldest task
```

-   **Local** operations: LIFO `push/pop` by the owning worker (fast, no contention).

-   **Steal** operations: other workers take from the **tail** (oldest items), typically with CAS.


## Participants

-   **Worker Thread:** Runs tasks from its own deque; steals when empty.

-   **Work-Stealing Deque:** Lock-free (or low-lock) double-ended queue.

-   **Scheduler/Pool:** Starts workers, tracks parallelism/compensation, handles `join`.

-   **Tasks:** Usually small units (e.g., `RecursiveTask`, `CountedCompleter` in Java).


## Collaboration

1.  A task **forks** (enqueues) new subtasks to its **local** deque and optionally continues with one directly.

2.  When a worker’s deque is empty, it **steals** from the tail of some other worker’s deque.

3.  Parent tasks **join** their children or use **completers** (e.g., `CountedCompleter`) to avoid join bottlenecks.

4.  Repeat until no work remains.


## Consequences

**Benefits**

-   **Automatic load balancing** for irregular DAGs/trees.

-   Excellent **cache locality** (LIFO for locals) and low contention.

-   Scales with cores without a central queue hotspot.


**Liabilities**

-   Harder to reason about than simple queues; **non-deterministic** execution order.

-   Too-fine task granularity increases overhead despite stealing.

-   Blocking in tasks can **starve** the pool (mitigate with `ManagedBlocker` or segregated pools).


## Implementation (Key Points)

-   In Java, prefer:

    -   **`ForkJoinPool`** with `RecursiveTask/RecursiveAction` for fork–join trees.

    -   **`CountedCompleter`** to avoid serial join dependencies (better for irregular fan-in).

    -   **`Executors.newWorkStealingPool()`** (builds a `ForkJoinPool` sized to available processors).

-   **Fork strategy:** Typically *fork one, compute one* to keep the current worker busy and enable stealing of siblings.

-   **Threshold:** Switch to sequential work below a cutoff to curb overhead.

-   **Blocking:** Use `ForkJoinPool.managedBlock(...)` if you must block; otherwise separate the blocking work.

-   **Observability:** Track steals, active threads, queued submissions, and task throughput.


---

## Sample Code (Java 17): Work Stealing with `ForkJoinPool`

Includes:

1.  **Parallel QuickSort** (irregular splits → steals happen)

2.  **Tree aggregation** with **`CountedCompleter`** (steal-friendly, no explicit joins)


```java
// File: WorkStealingDemo.java
// Compile: javac WorkStealingDemo.java
// Run:     java WorkStealingDemo
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;
import java.util.stream.IntStream;

/** 1) Irregular parallel QuickSort using RecursiveAction (work stealing via ForkJoinPool). */
class QuickSortTask extends RecursiveAction {
    private static final int CUTOFF = 1_024; // tune for your machine/data
    private final int[] a;
    private final int lo, hi; // [lo, hi)

    QuickSortTask(int[] a, int lo, int hi) { this.a = a; this.lo = lo; this.hi = hi; }

    @Override protected void compute() {
        int len = hi - lo;
        if (len <= CUTOFF) {
            Arrays.sort(a, lo, hi);
            return;
        }
        int p = partition(a, lo, hi);
        // Fork one side, compute the other: good for locality and stealing
        QuickSortTask left  = new QuickSortTask(a, lo, p);
        QuickSortTask right = new QuickSortTask(a, p+1, hi);
        if ((p - lo) < (hi - (p+1))) {
            left.fork();
            right.compute();
            left.join();
        } else {
            right.fork();
            left.compute();
            right.join();
        }
    }

    private static int partition(int[] a, int lo, int hi) {
        int pivot = a[lo + (hi - lo) / 2];
        int i = lo - 1, j = hi;
        while (true) {
            do { i++; } while (a[i] < pivot);
            do { j--; } while (a[j] > pivot);
            if (i >= j) return j;
            int tmp = a[i]; a[i] = a[j]; a[j] = tmp;
        }
    }
}

/** 2) CountedCompleter example: sum of tree nodes without explicit join chains. */
class Node {
    final int value;
    final List<Node> children;
    Node(int value, List<Node> kids){ this.value = value; this.children = kids; }
}
class SumTree extends CountedCompleter<Integer> {
    private final Node node;
    private int result;

    SumTree(CountedCompleter<?> parent, Node node) {
        super(parent); this.node = node;
    }

    @Override public void compute() {
        List<Node> kids = node.children;
        int n = kids.size();
        if (n == 0) { result = node.value; tryComplete(); return; }
        // set pending for children; fork them; current will complete when all children calls complete()
        setPendingCount(n);
        for (Node k : kids) new SumTree(this, k).fork();
        // local contribution (avoid lost work)
        result = node.value;
    }

    @Override public void onCompletion(CountedCompleter<?> caller) {
        // After all children done, aggregate their results
        int sum = result;
        for (CountedCompleter<?> sub = firstComplete(); sub != null; sub = sub.nextComplete()) {
            // no-op; handled via standard completion chain
        }
    }

    @Override public Integer getRawResult() { return aggregate(node); }

    private int aggregate(Node n) {
        int s = n.value;
        for (Node c : n.children) s += aggregate(c);
        return s;
    }
}

public class WorkStealingDemo {
    public static void main(String[] args) {
        ForkJoinPool pool = new ForkJoinPool(Math.max(1, Runtime.getRuntime().availableProcessors()));
        System.out.println("Parallelism: " + pool.getParallelism());

        // ---- Demo 1: Irregular QuickSort (creates steals) ----
        int N = 2_000_000;
        int[] arr = new Random(42).ints(N).toArray();

        long t0 = System.nanoTime();
        pool.invoke(new QuickSortTask(arr, 0, arr.length));
        long t1 = System.nanoTime();
        System.out.printf("QuickSort sorted=%b in %.1f ms%n", isSorted(arr), (t1 - t0)/1e6);

        // ---- Demo 2: Irregular tree sum with CountedCompleter ----
        Node root = randomTree(6, 4, new Random(7)); // depth≈6, fanout up to 4
        AtomicLong visit = new AtomicLong();
        // Instead of relying on CountedCompleter's result propagation (which typically uses setRawResult),
        // we'll do a parallel reduce using RecursiveTask to keep it simple and observable.
        int sum = pool.invoke(new RecursiveTask<Integer>() {
            @Override protected Integer compute() {
                return sumTree(root);
            }
            int sumTree(Node n) {
                visit.incrementAndGet();
                if (n.children.isEmpty()) return n.value;
                List<RecursiveTask<Integer>> forks = new ArrayList<>(n.children.size()-1);
                int acc = 0;
                for (int i = 1; i < n.children.size(); i++) {
                    var t = new RecursiveTask<Integer>() {
                        final Node child = n.children.get(i);
                        @Override protected Integer compute() { return sumTree(child); }
                    };
                    forks.add(t); t.fork();
                }
                // compute one child directly (help the pool)
                acc += sumTree(n.children.get(0));
                for (var f : forks) acc += f.join();
                return acc + n.value;
            }
        });
        System.out.printf("Tree sum=%d (visited %d nodes)%n", sum, visit.get());

        pool.shutdown();
    }

    /* Utilities */
    static boolean isSorted(int[] a) {
        for (int i = 1; i < a.length; i++) if (a[i-1] > a[i]) return false; return true;
    }
    static Node randomTree(int maxDepth, int maxFanout, Random r) {
        if (maxDepth == 0) return new Node(r.nextInt(100), List.of());
        int k = r.nextInt(maxFanout + 1);
        List<Node> kids = new ArrayList<>(k);
        for (int i=0;i<k;i++) kids.add(randomTree(maxDepth-1, maxFanout, r));
        return new Node(r.nextInt(100), kids);
    }
}
```

**What to look for**

-   QuickSort’s partitions are **uneven**, so idle workers **steal** partitions from others.

-   The “fork one, compute one” tactic keeps the local worker busy and exposes siblings for stealing.

-   `ForkJoinPool` handles the per-worker deques and steals automatically.


> For tasks that may block on I/O, wrap blocking sections with `ForkJoinPool.managedBlock(...)` or offload to a dedicated I/O executor to prevent pool starvation.

---

## Known Uses

-   **Java `ForkJoinPool`** (parallel streams, `CompletableFuture` internals).

-   **Cilk / Intel TBB**: Classic work-stealing schedulers for C/C++.

-   **.NET TPL** work-stealing queues.

-   **Task runtimes** in scientific/graphics engines for irregular DAGs (e.g., game engines’ job systems).


## Related Patterns

-   **Fork–Join:** Canonical algorithmic style that pairs naturally with work stealing.

-   **Thread Pool:** Central-queue executors; simpler but can bottleneck.

-   **Producer–Consumer:** Alternate queueing model; can be combined per stage.

-   **Barrier Synchronization:** Often used between recursive phases.

-   **Actor Model:** Message-driven alternative when state isolation is primary.


---

### Practical Tips

-   Choose a **cutoff** (problem size → sequential) empirically; too small explodes overhead.

-   Prefer **balanced fork trees** when possible; for unavoidable skew, rely on stealing.

-   Avoid blocking; if unavoidable, use **`managedBlock`** or **separate pools**.

-   For reductions, try **`CountedCompleter`** to remove explicit join chains.

-   Monitor: **steal count**, **queued submissions**, **active thread count**, and **task time percentiles**.

-   When mixing with other executors, avoid **oversubscription** (keep total runnable threads ≈ CPU cores for CPU-bound tasks).
