# Fail Fast — Resilience & Fault-Tolerance Pattern

## Pattern Name and Classification

**Name:** Fail Fast  
**Classification:** Resilience / Fault-Tolerance Pattern (Fast Rejection & Early Error Detection)

## Intent

Detect invalid states, unavailable dependencies, or capacity exhaustion **as early as possible** and return an error immediately instead of waiting (e.g., on long timeouts or unbounded queues). This preserves resources, prevents cascades, and keeps latency predictable.

## Also Known As

-   Fast Rejection
    
-   Guard Clauses / Early Return (at method level)
    
-   Quick Fail Admission Control
    

## Motivation (Forces)

-   **Latency budgets:** Slow timeouts pile up, saturating threads and connections.
    
-   **Predictability:** It’s better to return a clear “can’t serve now” quickly than to stall.
    
-   **Backpressure:** Upstream can shed or reroute load when it receives immediate rejections.
    
-   **Simplicity:** Early, explicit checks make intent obvious and reduce error-handling complexity later.
    

Counter-forces:

-   Over-eager rejections can degrade availability if thresholds are tuned too aggressively.
    
-   Some workflows prefer “eventual” success over immediate failure (e.g., batch jobs).
    

## Applicability

Use Fail Fast when:

-   Requests exceed **capacity**, queues are full, or concurrency limits are hit.
    
-   **Preconditions** or **input validation** can be checked upfront.
    
-   A **dependency** is known unhealthy (e.g., circuit breaker is OPEN).
    
-   **Timeouts** should be strict and short; waiting offers no benefit.
    

Avoid or tune carefully when:

-   Work is rare/cheap and transient glitches would self-heal if you waited a bit.
    
-   You must guarantee in-line retries instead of surfacing errors to callers.
    

## Structure

```java
Client ──► Admission Guards (capacity / health / validation)
            ├─ pass ─► Do Work (short, bounded)
            └─ reject fast ─► Error / Fallback / Queue for later
```

## Participants

-   **Admission Guard(s):** Checks capacity, health, and preconditions; may include rate limiters, semaphores, and circuit breakers.
    
-   **Work Executor:** Performs the actual task under strict timeouts.
    
-   **Fallback / Degrader (optional):** Returns cached/partial results on fast rejection.
    
-   **Metrics/Alarms:** Counters for rejections/timeouts to inform tuning and autoscaling.
    

## Collaboration

-   The caller first hits **guards**; if any guard rejects, it returns immediately (possibly with a fallback).
    
-   If accepted, the executor runs the task **with a short timeout**.
    
-   Fail Fast composes with **Bulkheads** (isolation), **Circuit Breakers** (health gating), and **Retries** (but only when allowed).
    

## Consequences

**Benefits**

-   Prevents queues/threads from **filling with hopeless work**.
    
-   Keeps tail latency under control; protects SLOs for healthy requests.
    
-   Produces clearer failure signals for autoscaling and routing.
    

**Liabilities / Trade-offs**

-   Requires **tuning** of limits and timeouts; misconfiguration causes flapping or excessive errors.
    
-   Pushes complexity to **callers**, who must handle fast failures and retry or degrade.
    

## Implementation

1.  **Identify guard points**: validation, auth, dependency health, capacity (concurrency/queue).
    
2.  **Set strict limits**: use **bounded** queues and **short, deterministic timeouts**.
    
3.  **Compose guards**: order checks from cheapest to most expensive (validation → capacity → health).
    
4.  **Provide fallbacks**: cached data, defaults, “try again later.”
    
5.  **Instrument**: expose metrics for rejections, timeouts, and success; alert on spikes.
    
6.  **Tune with data**: load test; adjust limits/timeout budgets based on p95/p99.
    

---

## Sample Code (Java)

### A) A minimal Fail-Fast guard with capacity, health, and timeout

```java
import java.time.Duration;
import java.util.Objects;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Supplier;

/** Simple fail-fast wrapper for calls to a downstream or expensive task. */
public class FailFastGuard {

  private final Semaphore capacity;                // concurrency bulkhead
  private final AtomicBoolean dependencyHealthy;   // e.g., from a circuit breaker
  private final Duration timeout;                  // strict per-call timeout
  private final ExecutorService executor;          // short-lived workers or a shared pool

  public FailFastGuard(int maxConcurrent, Duration timeout, Supplier<Boolean> healthSupplier) {
    this.capacity = new Semaphore(maxConcurrent);
    this.timeout = Objects.requireNonNull(timeout);
    this.dependencyHealthy = new AtomicBoolean(true);
    // Optionally wire healthSupplier to update dependencyHealthy asynchronously
    this.executor = Executors.newFixedThreadPool(Math.max(2, maxConcurrent));
    // A very simple poller (optional)
    Executors.newSingleThreadScheduledExecutor().scheduleAtFixedRate(
        () -> dependencyHealthy.set(Boolean.TRUE.equals(healthSupplier.get())), 0, 500, TimeUnit.MILLISECONDS);
  }

  /** Execute the task if guards pass; otherwise fast-fail or return fallback. */
  public <T> T call(Callable<T> task, Supplier<T> fallback) throws Exception {
    // 1) Validate health first (cheap)
    if (!dependencyHealthy.get()) {
      return fallback.get(); // fast reject
    }
    // 2) Capacity check (no queue growth)
    if (!capacity.tryAcquire()) {
      return fallback.get(); // fast reject on overload
    }
    try {
      Future<T> f = executor.submit(task);
      return f.get(timeout.toMillis(), TimeUnit.MILLISECONDS); // 3) strict timeout
    } catch (TimeoutException te) {
      return fallback.get(); // treat timeout as fast failure; cancel work
    } finally {
      capacity.release();
    }
  }

  public void shutdown() { executor.shutdownNow(); }
}
```

**Usage example**

```java
public class ProfileClient {
  private final FailFastGuard guard = new FailFastGuard(
      32, Duration.ofMillis(300), this::isUpstreamHealthy);

  private final HttpClient http; // your adapter with its own short timeouts

  public ProfileClient(HttpClient http) { this.http = http; }

  public String getProfile(String userId) throws Exception {
    return guard.call(
        () -> http.get("/profiles/" + userId),             // protected operation
        () -> "{\"status\":\"degraded\",\"userId\":\"" + userId + "\"}" // fallback
    );
  }

  private Boolean isUpstreamHealthy() {
    // Use circuit breaker state, health endpoint ping, or last success timestamp
    return http.isHealthy();
  }

  interface HttpClient {
    String get(String path) throws Exception;
    boolean isHealthy();
  }
}
```

### B) Fail-Fast at method level with guard clauses (validation + quick exits)

```java
public class BookingService {
  public Reservation book(BookingRequest req, User user) {
    // Guard: input validation
    if (req == null) return Reservation.rejected("Missing request");
    if (user == null) return Reservation.rejected("Missing user");
    if (!user.hasPermission("BOOK")) return Reservation.rejected("Not authorized");
    if (req.date().isBefore(java.time.LocalDate.now())) return Reservation.rejected("Date in the past");

    // Happy path (short and bounded)
    return reserve(req).orElse(Reservation.rejected("No availability"));
  }

  private java.util.Optional<Reservation> reserve(BookingRequest req) {
    // call into inventory with its own small timeout; no unbounded waits
    return java.util.Optional.of(new Reservation(/* ... */));
  }
}
```

### C) Fast-rejecting queue (bounded) for work intake

```java
public class IngressQueue<T> {
  private final BlockingQueue<T> q = new ArrayBlockingQueue<>(1000); // bounded

  /** Returns false immediately when full (fail fast). */
  public boolean offer(T item) {
    return q.offer(item); // no waiting; caller decides to drop/fallback/shed load
  }

  public T take() throws InterruptedException {
    return q.take();
  }
}
```

---

## Known Uses

-   **API gateways:** Immediate 429/503 when rate limits or concurrency caps are exceeded.
    
-   **Microservices:** Quick rejection when a **circuit breaker is OPEN** or a **bulkhead** is saturated.
    
-   **Datastores/HTTP clients:** Small client timeouts (100–500 ms) for interactive paths rather than multi-second waits.
    
-   **Job schedulers:** Bounded queues that reject new jobs during surge, pushing to a retry queue instead.
    
-   **Validation layers:** Guard clauses at the top of handlers/services to stop bad requests early.
    

## Related Patterns

-   **Bulkhead:** Provides the concurrency limit that triggers fast rejection.
    
-   **Circuit Breaker:** Signals unhealthy downstreams so calls are rejected immediately.
    
-   **Timeouts:** Enforce strict upper bounds on work duration.
    
-   **Rate Limiting / Load Shedding:** Admission control that often implements fail-fast behavior.
    
-   **Fallback / Graceful Degradation:** What you return when you reject quickly.
    
-   **Retry with Backoff & Jitter:** Retrying should respect fast-fail signals and capacity caps.
    
-   **Guard Clauses / Simplify Nested Conditional:** Coding technique for early returns at method level.
    

**Rule of thumb:** If a request **can’t** be served within the latency budget or violates preconditions, **say so immediately**—don’t make the system suffer in silence.

