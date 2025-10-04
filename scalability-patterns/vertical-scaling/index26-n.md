# Vertical Scaling — Scalability Pattern

## Pattern Name and Classification

**Name:** Vertical Scaling  
**Classification:** Scalability / Capacity Management (Scale-up: larger single node)

---

## Intent

Increase throughput, reduce latency, or expand working-set capacity by **upgrading a single node’s resources**—CPU cores, clock speed, RAM, storage IOPS/throughput, NIC bandwidth—**without changing the application topology**.

---

## Also Known As

-   Scale-Up
    
-   Bigger Box / Larger Instance Type
    
-   SMP Scaling (for multi-core CPUs)
    

---

## Motivation (Forces)

-   **Fastest path to capacity:** One change to infra, zero distributed complexity.
    
-   **Licensing / operational constraints:** Software licensed per node; fewer nodes are cheaper to run or certify.
    
-   **Stateful monoliths:** Hard to partition or shard immediately.
    
-   **Latency-sensitive workloads:** In-memory datasets fit after adding RAM → fewer cache misses, fewer calls to slower tiers.
    

Trade-offs: diminishing returns due to **contention** (locks, cache lines), **Amdahl’s Law**, and **single-node blast radius**.

---

## Applicability

Use Vertical Scaling when:

-   You can’t (yet) partition the workload or externalize state.
    
-   Bottlenecks are **on one host** (CPU, GC, RAM, disk, NIC) and profiling shows headroom with more resources.
    
-   **SLA/SLO** requires micro-latency improvements (L3/L1 hits, NUMA locality) more than horizontal elasticity.
    

Avoid or limit when:

-   You need **fault tolerance** via multi-node redundancy.
    
-   Throughput is fundamentally **I/O-bound on remote services** (bigger CPU won’t help).
    
-   You’re close to the **largest instance** already (no more headroom).
    

---

## Structure

-   **Scaled Node:** the single upgraded server/VM/container host.
    
-   **Resource Managers:** OS scheduler, JVM/GC, thread pools, DB pools.
    
-   **Hot Paths:** CPU-bound loops, memory lookups, disk or network I/O.
    
-   **Telemetry:** CPU utilization, run-queue length, GC times, page faults, IOPS, NIC drops.
    

---

## Participants

-   **Application Runtime (JVM):** threads, GC, heap sizing, JIT.
    
-   **Operating System:** CPU scheduling, NUMA, IO scheduler, huge pages.
    
-   **Storage/NIC:** higher IOPS/throughput; kernel and driver settings.
    
-   **Database/Cache Clients:** connection pools tuned to bigger node.
    
-   **Observability Stack:** measures before/after effects and saturation.
    

---

## Collaboration

1.  **Profile** and identify the local bottleneck (CPU, memory, I/O).
    
2.  **Upgrade** resources (bigger instance, faster disk/NVMe, more RAM, 25/100GbE).
    
3.  **Tune runtime** (thread pools, GC, heap, file descriptors, DB pool) to exploit new headroom.
    
4.  **Measure**: verify throughput/latency gains and watch for new bottlenecks (lock contention, GC, cache misses).
    
5.  **Guardrails**: set limits (ulimits, cgroups) to avoid noisy-neighbor or runaway memory.
    

---

## Consequences

**Benefits**

-   Minimal architecture change; **fastest** way to buy capacity.
    
-   Can deliver **lower latency** by fitting working set in memory / CPU cache.
    
-   Reduces **operational complexity** (fewer nodes, simpler deploy).
    

**Liabilities**

-   **Single point of failure** unless paired with replicas.
    
-   **Diminishing returns** due to contention and serial fractions (Amdahl’s Law).
    
-   **Cost step-functions** at larger instance tiers; potential **vendor lock-in**.
    
-   Requires **careful tuning** (GC, threads, NUMA) to realize gains.
    

---

## Implementation

### Key Decisions

-   **Which resource to scale?**
    
    -   **CPU:** more cores for parallel work; higher frequency for single-threaded hot paths.
        
    -   **RAM:** fit larger caches/heaps; reduce GC/page faults.
        
    -   **Storage:** NVMe/SSD with higher IOPS/throughput; tune IO scheduler.
        
    -   **Network:** 25/100GbE; enable multi-queue NIC, RSS, RFS.
        
-   **Runtime tuning:**
    
    -   **Thread pools:** right-size CPU-bound vs I/O-bound executors.
        
    -   **JVM GC:** choose collector (G1/ZGC/Shenandoah) and size heap/regions to new RAM.
        
    -   **NUMA awareness:** pin threads or use `-XX:+UseNUMA` for very large machines.
        
    -   **FD/epoll limits:** raise `ulimit -n`, tune server accept/backlog queues.
        
-   **Back-pressure & safety:** cap concurrency to protect downstreams; honor DB pool and rate limits.
    

### Anti-Patterns

-   “Bigger box fixes all”: scaling CPU for I/O-bound or remote-bound code.
    
-   Letting **thread pools scale unbounded** → context switching and cache thrash.
    
-   Over-allocating heap **without** adjusting GC → long pauses.
    
-   Ignoring **NUMA** on >2 socket systems → cross-node memory penalties.
    
-   No load tests → regressions from hidden contention (locks, allocator).
    

---

## Sample Code (Java)

Below: a small **scale-up aware runtime** that (1) sizes thread pools by cores, (2) separates CPU-bound and I/O-bound work, (3) sizes DB pool conservatively relative to CPU & downstream, and (4) exposes knobs for quick tuning when you move to a larger instance.

```java
// build.gradle (snip)
// implementation 'com.zaxxer:HikariCP:5.1.0'
// implementation 'org.postgresql:postgresql:42.7.4'

package com.example.verticalscale;

import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;

import javax.sql.DataSource;
import java.time.Duration;
import java.util.concurrent.*;
import java.util.function.Supplier;

public class ScaleUpRuntime {

  /** Detect cores and set sane defaults for CPU vs IO pools. */
  public static final int CORES = Math.max(1, Runtime.getRuntime().availableProcessors());

  // CPU-bound: parallelism ~= cores (maybe cores-1 to leave room for GC)
  public static ExecutorService cpuPool(int parallelism) {
    int p = Math.max(1, parallelism > 0 ? parallelism : Math.max(1, CORES - 1));
    return new ThreadPoolExecutor(
        p, p,
        0L, TimeUnit.MILLISECONDS,
        new LinkedBlockingQueue<>(p * 1024), // bounded; prevents unbounded queue growth
        new NamedFactory("cpu"),
        new ThreadPoolExecutor.CallerRunsPolicy() // back-pressure under load
    );
  }

  // IO-bound: more concurrency but still bounded; tune per downstream capacity
  public static ExecutorService ioPool(int maxThreads) {
    int p = Math.max(4, maxThreads > 0 ? maxThreads : Math.min(CORES * 4, 256));
    return new ThreadPoolExecutor(
        p, p,
        30L, TimeUnit.SECONDS,
        new LinkedBlockingQueue<>(p * 2048),
        new NamedFactory("io"),
        new ThreadPoolExecutor.CallerRunsPolicy()
    );
  }

  // DB pool sized to downstream capacity; do NOT exceed DB/connection limits just because box is bigger
  public static DataSource hikari(String url, String user, String pass, int maxPool) {
    HikariConfig cfg = new HikariConfig();
    cfg.setJdbcUrl(url);
    cfg.setUsername(user);
    cfg.setPassword(pass);
    cfg.setMaximumPoolSize(maxPool > 0 ? maxPool : Math.min(32, CORES * 2)); // conservative default
    cfg.setMinimumIdle(Math.max(2, cfg.getMaximumPoolSize() / 4));
    cfg.setConnectionTimeout(Duration.ofSeconds(2).toMillis());
    cfg.setValidationTimeout(Duration.ofMillis(800).toMillis());
    cfg.setIdleTimeout(Duration.ofMinutes(2).toMillis());
    cfg.setMaxLifetime(Duration.ofMinutes(30).toMillis());
    // For high-IOPS NVMe, consider tcp keepalive / pg socket settings outside this snippet
    return new HikariDataSource(cfg);
  }

  /** Utility for timed tasks with budgeted timeouts (prevents GC or downstream hiccups from stalling everything). */
  public static <T> T callWithTimeout(Callable<T> task, Duration timeout, ExecutorService pool) throws Exception {
    Future<T> f = pool.submit(task);
    try {
      return f.get(timeout.toMillis(), TimeUnit.MILLISECONDS);
    } catch (TimeoutException te) {
      f.cancel(true);
      throw te;
    }
  }

  private static final class NamedFactory implements ThreadFactory {
    private final String prefix;
    private final ThreadFactory delegate = Executors.defaultThreadFactory();
    private final ThreadLocal<Integer> count = ThreadLocal.withInitial(() -> 0);
    private volatile int idx = 0;
    NamedFactory(String prefix) { this.prefix = prefix; }
    @Override public Thread newThread(Runnable r) {
      Thread t = delegate.newThread(r);
      t.setName("pool-" + prefix + "-" + (++idx));
      t.setDaemon(false);
      return t;
    }
  }

  // Example usage
  public static void main(String[] args) throws Exception {
    System.out.println("Detected cores = " + CORES);

    ExecutorService cpu = cpuPool(0);      // auto = cores-1
    ExecutorService io  = ioPool(0);       // auto = min(cores*4, 256)
    DataSource ds       = hikari("jdbc:postgresql://db/app", "app", "secret", 0);

    // CPU-bound task (e.g., JSON transform)
    String result = callWithTimeout(() -> heavyCompute("payload"), Duration.ofMillis(120), cpu);
    System.out.println(result);

    // IO-bound task (DB call; wrap with timeout to keep tail latency bounded)
    String fromDb = callWithTimeout(() -> queryUser(ds, "u123"), Duration.ofMillis(300), io);
    System.out.println(fromDb);

    // shutdown gracefully
    cpu.shutdown();
    io.shutdown();
  }

  // ----- demo stubs -----
  private static String heavyCompute(String s) {
    // pretend to do CPU work
    double x = 0;
    for (int i = 0; i < 2_000_000; i++) x += Math.sin(i);
    return s + ":" + (int)x;
  }

  private static String queryUser(DataSource ds, String id) throws Exception {
    try (var conn = ds.getConnection();
         var ps = conn.prepareStatement("select name from users where id=?")) {
      ps.setString(1, id);
      try (var rs = ps.executeQuery()) {
        return rs.next() ? rs.getString(1) : "<missing>";
      }
    }
  }
}
```

**How this helps on a bigger box**

-   **CPU pool** scales with cores (leaves headroom for GC/JIT/OS).
    
-   **I/O pool** is bounded and **not** blindly tied to cores—protects downstreams.
    
-   **DB pool** respects database limits; scale-up won’t create connection storms.
    
-   **Timeouts** bound tail latency, crucial when a single fat node carries more traffic.
    

> JVM flags you’ll typically revisit when scaling up (illustrative):  
> `-XX:+UseG1GC -Xms16g -Xmx16g -XX:MaxGCPauseMillis=200` (heap sized to RAM)  
> `-XX:+UseNUMA` on multi-socket boxes; consider ZGC/Shenandoah for very large heaps.

---

## Known Uses

-   Monolithic applications or single-tenant databases that must run on **certified hardware**.
    
-   **In-memory analytics** engines where more RAM dramatically reduces I/O.
    
-   **Low-latency trading / HFT** stacks that rely on CPU cache locality and pinned threads.
    
-   Legacy systems where horizontal refactor is not yet feasible.
    

---

## Related Patterns

-   **Horizontal Scaling:** complementary; start with vertical to buy time, then scale out.
    
-   **Auto Scaling Group:** even scaled-up nodes can be multiplied; use both.
    
-   **Database Replication / Read Replicas:** scale reads while write node is vertically scaled.
    
-   **Partitioning / Sharding:** long-term strategy once a single node’s limits are reached.
    
-   **Circuit Breaker / Throttling / Timeouts:** needed to protect a big node under transient overloads.
    

---

## Implementation Checklist

-   **Profile first**: confirm bottleneck (CPU, memory, storage, NIC).
    
-   Pick **instance type** (cores, clock, RAM, NVMe, NIC) matched to the bottleneck.
    
-   Tune **JVM/GC**, **thread pools**, **DB pools**, **ulimits**, **epoll/backlogs**, **FDs**.
    
-   Validate **NUMA** and memory bandwidth; avoid cross-socket traffic where possible.
    
-   Load-test with production-like data; watch for **lock contention**, **GC**, **page faults**, **run-queue length**.
    
-   Set **back-pressure**: bounded queues, caller-runs policies, rate limits to downstreams.
    
-   Keep **redundancy**: even with scale-up, run ≥2 nodes behind a load balancer for HA.
    
-   Document **capacity curves** and **upgrade playbooks** (how to move N→N+1 size safely).

