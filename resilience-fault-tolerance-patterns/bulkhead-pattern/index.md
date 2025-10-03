# Bulkhead — Resilience & Fault-Tolerance Pattern

## Pattern Name and Classification

**Name:** Bulkhead  
**Classification:** Resilience / Fault-Tolerance Pattern (Isolation & Containment)

## Intent

Prevent a failure or resource spike in one part of the system from **cascading** into others by **partitioning resources** (threads, connection pools, queues, rate budgets) into isolated compartments (“bulkheads”).

## Also Known As

-   Resource Partitioning
    
-   Isolation Pools
    
-   Compartmentalization
    
-   Concurrency Limits per Dependency
    

## Motivation (Forces)

-   **Noisy neighbor risk:** One slow or failing dependency can exhaust shared resources (threads, sockets) and stall unrelated work.
    
-   **Backpressure & fairness:** High-priority flows need guarantees even when low-priority traffic spikes.
    
-   **Predictability:** SLOs require caps on concurrency and clear failure modes instead of queue pile-ups.
    
-   **Graceful degradation:** Prefer “fail fast here” over “everything times out everywhere.”
    

## Applicability

Use Bulkheads when:

-   A service calls **multiple downstreams** with different criticality levels.
    
-   Workloads have **distinct priorities** (e.g., user-facing vs. batch).
    
-   You observed **thread/connection starvation**, queue build-ups, or GC pressure during partial outages.
    
-   You run **multi-tenant** workloads that must not affect each other.
    

Avoid or use lightly when:

-   System is **tiny** with a single dependency and over-isolation adds operational overhead.
    
-   Strict isolation would **waste scarce resources** (tiny instances); consider dynamic partitioning.
    

## Structure

```sql
┌───────────────────────────── Service ─────────────────────────────┐
                 │                                                                    │
   User APIs ───►│ Pool A (32 threads) ──► Downstream X                               │
 Batch Jobs ───► │ Pool B (8 threads)  ──► Downstream Y                               │
  Admin Ops ───► │ Pool C (4 threads)  ──► Local CPU task                             │
                 │   ^  timeouts, fallback, metrics                                   │
                 └───┴────────────────────────────────────────────────────────────────┘

Alternative: semaphore bulkheads per call-site (limit in-flight calls per dependency).
```

## Participants

-   **Caller / Orchestrator:** Routes work to the correct bulkhead.
    
-   **Bulkhead:** The isolation mechanism (thread pool / executor, semaphore, queue, connection pool).
    
-   **Downstream / Task:** The work that may fail or stall.
    
-   **Fallback / Degrader:** Optional path when the bulkhead is saturated (defaults, cached data).
    

## Collaboration

-   Caller chooses bulkhead based on **priority or dependency**.
    
-   Bulkhead **accepts or rejects** work (fast failure) and enforces concurrency and queue limits.
    
-   Fallback provides **graceful degradation** when bulkhead rejects.
    

## Consequences

**Benefits**

-   Containment of faults; **no cascade** from one dependency to all traffic.
    
-   **Predictable latency** for critical flows.
    
-   Enforced backpressure; easier capacity planning and SLOs.
    
-   Clear signals (rejections) that trigger autoscaling or shed load.
    

**Liabilities / Trade-offs**

-   Potential **under-utilization** if partitions are too small or static.
    
-   More **operational tuning** (pool sizes, queue lengths).
    
-   Wrong routing/partitioning can still starve important work.
    
-   Added complexity coordinating with **timeouts, retries, circuit breakers**.
    

## Implementation

1.  **Segment workloads/dependencies.** Decide isolation keys (dependency, priority, tenant).
    
2.  **Choose a mechanism.**
    
    -   **Thread-pool bulkhead:** Fixed (or bounded) pool + bounded queue.
        
    -   **Semaphore bulkhead:** Limit in-flight calls without dedicated threads.
        
    -   **Connection pool partitioning:** Separate pools per dependency/tenant.
        
3.  **Set limits & queues.** Prefer **bounded queues**; avoid unbounded growth.
    
4.  **Integrate with timeouts & retries.** Use short timeouts; retries must respect bulkhead capacity and jitter.
    
5.  **Provide fallbacks.** Cached data, default responses, partial rendering.
    
6.  **Observe & tune.** Export metrics: in-flight, queue depth, rejections, latency percentiles.
    
7.  **Automate scaling/shift.** Adjust partitions by config; support surge modes if needed.
    

---

## Sample Code (Java)

### A) Semaphore Bulkhead per Dependency (lightweight, no extra threads)

```java
import java.time.Duration;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.CompletableFuture;

public class Bulkheads {
  private final Semaphore customerApiSlots = new Semaphore(20); // max in-flight
  private final Semaphore paymentApiSlots  = new Semaphore(8);

  public <T> T withSemaphore(Semaphore sem, Duration timeout, CheckedSupplier<T> task, CheckedSupplier<T> fallback) throws Exception {
    if (!sem.tryAcquire()) return fallback.get(); // fast-fail/fallback when saturated
    try {
      // Run on caller's thread; add explicit timeout
      CompletableFuture<T> f = CompletableFuture.supplyAsync(() -> {
        try { return task.get(); } catch (Exception e) { throw new RuntimeException(e); }
      });
      return f.orTimeout(timeout.toMillis(), java.util.concurrent.TimeUnit.MILLISECONDS).join();
    } catch (java.util.concurrent.CompletionException ce) {
      if (ce.getCause() instanceof java.util.concurrent.TimeoutException) throw new TimeoutException();
      throw (ce.getCause() instanceof Exception e) ? e : new RuntimeException(ce.getCause());
    } finally {
      sem.release();
    }
  }

  public String fetchCustomer(String id, HttpClientAdapter client) throws Exception {
    return withSemaphore(customerApiSlots, Duration.ofMillis(500),
        () -> client.get("/customers/" + id),
        () -> "{}" // minimal fallback
    );
  }

  public String charge(String payload, HttpClientAdapter client) throws Exception {
    return withSemaphore(paymentApiSlots, Duration.ofMillis(800),
        () -> client.post("/payments", payload),
        () -> { throw new IllegalStateException("payment unavailable"); }
    );
  }

  @FunctionalInterface interface CheckedSupplier<T> { T get() throws Exception; }
  interface HttpClientAdapter { String get(String path) throws Exception; String post(String path, String body) throws Exception; }
}
```

### B) Thread-Pool Bulkheads (per-route isolation with bounded queues)

```java
import java.util.concurrent.*;

public class IsolatedExecutors {
  // Distinct pools with bounded queues; saturation triggers RejectedExecutionException
  private final ExecutorService userPool  = new ThreadPoolExecutor(32, 32, 0, TimeUnit.SECONDS,
      new ArrayBlockingQueue<>(64), new ThreadPoolExecutor.AbortPolicy()); // fail fast
  private final ExecutorService batchPool = new ThreadPoolExecutor(8, 8, 0, TimeUnit.SECONDS,
      new ArrayBlockingQueue<>(16), new ThreadPoolExecutor.CallerRunsPolicy()); // natural backpressure

  public <T> T runUserTask(Callable<T> c, long timeoutMs) throws Exception {
    Future<T> f = userPool.submit(c);
    try { return f.get(timeoutMs, TimeUnit.MILLISECONDS); }
    catch (TimeoutException te) { f.cancel(true); throw te; }
  }

  public <T> T runBatchTask(Callable<T> c, long timeoutMs) throws Exception {
    Future<T> f = batchPool.submit(c);
    try { return f.get(timeoutMs, TimeUnit.MILLISECONDS); }
    catch (TimeoutException te) { f.cancel(true); throw te; }
  }

  public void shutdown() { userPool.shutdown(); batchPool.shutdown(); }
}
```

### C) Combining with Circuit Breaker & Retry (outline)

-   **Order of operations at call-site:** `Bulkhead ➜ Timeout ➜ CircuitBreaker ➜ Retry`.
    
-   Retries must **not** exceed bulkhead capacity; add jitter and caps.
    

---

## Known Uses

-   **Isolation per downstream** in microservices (e.g., separate pools for Auth, Payments, Catalog).
    
-   **Priority lanes**: interactive user traffic vs. analytics/batch.
    
-   **Tenant isolation** in multi-tenant SaaS (per-tenant semaphores/quotas).
    
-   **Cloud platform guidance**: bulkheads referenced alongside circuit breakers, retries, and timeouts in many production architectures.
    

## Related Patterns

-   **Circuit Breaker:** Trip when a dependency is failing; bulkhead prevents resource exhaustion while the breaker opens.
    
-   **Timeouts:** Ensure stuck calls don’t hold capacity indefinitely.
    
-   **Retry with Backoff & Jitter:** Retry responsibly; respect bulkhead limits.
    
-   **Load Shedding / Rate Limiting:** Complementary admission control before work reaches bulkheads.
    
-   **Queue-based Load Leveling:** Buffer and decouple producers from consumers (another isolation form).
    
-   **Fallback / Graceful Degradation:** What to do when the bulkhead rejects.
    

**Practical tip:** Start simple with **semaphore bulkheads per dependency**, measure rejections/latency, then introduce specialized thread pools only where you need strict isolation or CPU-bound parallelism.

