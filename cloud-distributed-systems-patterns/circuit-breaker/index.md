# Circuit Breaker — Cloud / Distributed Systems Pattern

## Pattern Name and Classification

**Circuit Breaker** — *Cloud / Distributed Systems* **resilience** pattern that prevents a client from repeatedly invoking a **failing or slow dependency** by “opening the circuit” after failures, then **probing** later (half-open) before resuming normal traffic.

---

## Intent

Fail **fast** and **protect** resources when a downstream is unhealthy, avoiding thread/connection starvation, cascading failures, and noisy retries. Recover automatically when the dependency shows signs of health.

---

## Also Known As

-   **Breaker**

-   **Fail-Fast Guard**

-   **Trip/Probe/Reset** (Closed → Open → Half-Open → Closed)


---

## Motivation (Forces)

-   Repeated timeouts to a sick dependency consume **threads**, **sockets**, and **CPU**.

-   Unbounded retries amplify **latency** and **error storms**.

-   We need a **feedback loop** that trips quickly on failure and cautiously restores traffic.


**Tensions:** trip sensitivity vs. false positives, per-endpoint vs. shared breakers, global vs. per-instance state.

---

## Applicability

Use a circuit breaker when:

-   Calls are **remote** (or otherwise fallible/slow).

-   You have evidence of **intermittent outages** or **tail-latency spikes**.

-   You can provide **fallbacks** (cached defaults, degrade, queue).


Avoid when:

-   Calls are **in-process** and cheap; better fix the root cause.

-   You need **exactly-once** semantics that a fallback would violate (then break + surface failure cleanly).


---

## Structure

```pgsql
+--------------------+
request ───▶|  CircuitBreaker    |───▶ dependency()
            |  state: CLOSED     |
            |  counters/timers   |
            +---------┬----------+
                      │
   CLOSED: allow & count failures     OPEN: short-circuit fast
   HALF-OPEN: allow few probes; decide to close or open again
```

---

## Participants

-   **Caller / Client** — wraps dependency calls through the breaker.

-   **Circuit Breaker** — tracks **state**, **failures/timeouts**, **open duration**, **probe quota**.

-   **Dependency** — downstream service or resource.

-   **Fallback** — alternate logic when breaker rejects (optional but recommended).


---

## Collaboration

1.  In **Closed**, calls flow normally; the breaker records outcomes.

2.  When failures/timeouts exceed a threshold → **Open** (reject fast).

3.  After a cool-down → **Half-Open**; allow limited **trial requests**.

4.  If trials succeed → **Closed** (reset). Any trial fails → **Open** again.


---

## Consequences

**Benefits**

-   Preserves **threads/queues**; reduces cascading failure.

-   **Fast feedback** under incidents; automatic, cautious recovery.

-   Clear **operational signals** (trip counts, current state).


**Liabilities**

-   Added **failure mode** (rejections) that upstream must handle.

-   Misconfigured thresholds can cause **flapping** or **over-eager trips**.

-   Per-endpoint tuning and **metrics** are required.


---

## Implementation (Key Points)

-   Measure both **failures** and **slow calls** (timeouts count as failures).

-   Start simple with **consecutive-failures threshold** + **open duration** + **half-open probes**; add sliding-window failure-rate if needed.

-   Keep breaker **per remote** (host:port + operation); avoid one global breaker that couples unrelated dependencies.

-   Always provide **fallbacks** (even if it’s “fail fast with a clear error”).

-   Export **metrics** (state, trips, rejections, RTT, slow-call rate).

-   Combine with **Bulkheads** (capacity isolation) and **Timeouts/Retry** (bounded).

-   In distributed systems, keep breaker state **local**; share only signals (metrics/alerts).


---

## Sample Code (Java 17) — Small, Production-friendly Circuit Breaker

Features:

-   States: **CLOSED → OPEN → HALF\_OPEN**

-   Configurable **consecutive failure** threshold, **timeout**, **open duration**, and **half-open probe quota**

-   Synchronous API with timeout using a small executor (can adapt to async easily)

-   Optional **fallback** supplier

-   Minimal **metrics**


```java
import java.time.Duration;
import java.util.Objects;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Supplier;
import java.util.concurrent.Callable;

enum CBState { CLOSED, OPEN, HALF_OPEN }

final class CircuitBreaker {

  // ---- Configuration ----
  static final class Config {
    final int    maxConsecutiveFailures;
    final Duration callTimeout;
    final Duration openStateDuration;   // how long to stay OPEN before probing
    final int    halfOpenMaxTrials;     // allowed probes while HALF_OPEN

    Config(int maxConsecutiveFailures, Duration callTimeout,
           Duration openStateDuration, int halfOpenMaxTrials) {
      if (maxConsecutiveFailures < 1) throw new IllegalArgumentException("maxConsecutiveFailures >= 1");
      if (halfOpenMaxTrials < 1) throw new IllegalArgumentException("halfOpenMaxTrials >= 1");
      this.maxConsecutiveFailures = maxConsecutiveFailures;
      this.callTimeout = callTimeout;
      this.openStateDuration = openStateDuration;
      this.halfOpenMaxTrials = halfOpenMaxTrials;
    }
    static Config of(int fails, Duration timeout, Duration openFor, int probes) {
      return new Config(fails, timeout, openFor, probes);
    }
  }

  // ---- State ----
  private volatile CBState state = CBState.CLOSED;
  private final AtomicInteger consecutiveFailures = new AtomicInteger(0);
  private final AtomicInteger halfOpenInFlight = new AtomicInteger(0);
  private volatile long openedAtMillis = 0L;

  // ---- Infra ----
  private final Config cfg;
  private final ExecutorService pool;

  // ---- Metrics ----
  private final AtomicInteger totalCalls = new AtomicInteger(0);
  private final AtomicInteger rejectedCalls = new AtomicInteger(0);
  private final AtomicInteger trips = new AtomicInteger(0);

  CircuitBreaker(Config cfg) {
    this(cfg, Executors.newCachedThreadPool(r -> {
      Thread t = new Thread(r, "cb-worker-" + System.nanoTime());
      t.setDaemon(true);
      return t;
    }));
  }

  CircuitBreaker(Config cfg, ExecutorService pool) {
    this.cfg = Objects.requireNonNull(cfg);
    this.pool = Objects.requireNonNull(pool);
  }

  public CBState state() { return state; }

  // Core API: execute protected call with optional fallback
  public <T> T call(Callable<T> primary, Supplier<T> fallback) {
    Objects.requireNonNull(primary, "primary");
    totalCalls.incrementAndGet();

    // Gate by state
    if (!permitCall()) {
      rejectedCalls.incrementAndGet();
      if (fallback != null) return fallback.get();
      throw new RejectedExecutionException("Circuit is OPEN");
    }

    boolean trial = (state == CBState.HALF_OPEN);
    try {
      T result = executeWithTimeout(primary, cfg.callTimeout);
      onSuccess(trial);
      return result;
    } catch (Exception ex) {
      onFailure(trial);
      if (fallback != null) return fallback.get();
      if (ex instanceof CompletionException ce && ce.getCause() != null) throw new RuntimeException(ce.getCause());
      throw new RuntimeException(ex);
    } finally {
      if (trial) halfOpenInFlight.decrementAndGet();
    }
  }

  private boolean permitCall() {
    CBState s = state;
    if (s == CBState.CLOSED) return true;

    if (s == CBState.OPEN) {
      // Cool-down over? move to HALF_OPEN and allow limited probes
      if (System.currentTimeMillis() - openedAtMillis >= cfg.openStateDuration.toMillis()) {
        transitionTo(CBState.HALF_OPEN);
        halfOpenInFlight.set(0);
      } else {
        return false; // still OPEN
      }
    }
    // HALF_OPEN: allow limited concurrent probes
    return halfOpenInFlight.incrementAndGet() <= cfg.halfOpenMaxTrials;
  }

  private <T> T executeWithTimeout(Callable<T> c, Duration timeout) throws Exception {
    Future<T> f = pool.submit(c);
    try {
      return f.get(timeout.toMillis(), TimeUnit.MILLISECONDS);
    } catch (TimeoutException te) {
      f.cancel(true);
      throw te;
    }
  }

  private synchronized void onSuccess(boolean trial) {
    consecutiveFailures.set(0);
    if (trial) transitionTo(CBState.CLOSED);
    // else remain CLOSED
  }

  private synchronized void onFailure(boolean trial) {
    if (trial) {
      openNow(); // any failure while HALF_OPEN re-opens
      return;
    }
    int fails = consecutiveFailures.incrementAndGet();
    if (fails >= cfg.maxConsecutiveFailures) openNow();
  }

  private void openNow() {
    trips.incrementAndGet();
    transitionTo(CBState.OPEN);
    openedAtMillis = System.currentTimeMillis();
  }

  private synchronized void transitionTo(CBState next) {
    if (state != next) state = next;
  }

  public String metrics() {
    return "state=" + state +
        " fails=" + consecutiveFailures.get() +
        " trips=" + trips.get() +
        " total=" + totalCalls.get() +
        " rejected=" + rejectedCalls.get();
  }

  public void shutdown() { pool.shutdownNow(); }
}

// -------- Demo dependency that sometimes fails / sleeps --------
final class UnstableService {
  private final double failRate;     // 0..1
  private final int minLatencyMs;
  private final int maxLatencyMs;
  private final ThreadLocalRandom rnd = ThreadLocalRandom.current();

  UnstableService(double failRate, int minLatencyMs, int maxLatencyMs) {
    this.failRate = failRate; this.minLatencyMs = minLatencyMs; this.maxLatencyMs = maxLatencyMs;
  }

  String get(String key) throws Exception {
    int d = rnd.nextInt(minLatencyMs, maxLatencyMs + 1);
    Thread.sleep(d);
    if (rnd.nextDouble() < failRate) throw new RuntimeException("downstream-500");
    return "value(" + key + ") latency=" + d + "ms";
  }
}

// -------- Demo --------
public class CircuitBreakerDemo {
  public static void main(String[] args) throws Exception {
    var cfg = CircuitBreaker.Config.of(
        /*maxConsecutiveFailures*/ 3,
        /*callTimeout*/ Duration.ofMillis(200),
        /*openStateDuration*/ Duration.ofSeconds(2),
        /*halfOpenMaxTrials*/ 2
    );
    var cb = new CircuitBreaker(cfg);
    var svc = new UnstableService(/*failRate*/ 0.35, /*min*/ 50, /*max*/ 400);

    for (int i = 1; i <= 30; i++) {
      String key = "k-" + i;
      try {
        String result = cb.call(
            () -> svc.get(key),
            () -> "FALLBACK(" + key + ")" // degrade gracefully
        );
        System.out.printf("%02d  %-8s  %s%n", i, cb.state(), result);
      } catch (Exception e) {
        System.out.printf("%02d  %-8s  ERROR %s%n", i, cb.state(), e.getMessage());
      }
      // small pacing so we can watch state transitions
      Thread.sleep(150);
      if (i % 5 == 0) System.out.println("  metrics: " + cb.metrics());
    }

    cb.shutdown();
  }
}
```

**What the demo shows**

-   Normal calls succeed in **CLOSED**.

-   A streak of **timeouts/failures** (≥ 3) trips to **OPEN** → fast fallbacks.

-   After `openStateDuration` the breaker moves to **HALF\_OPEN** and allows limited **probes**; success closes it, a failure re-opens it.

-   Metrics expose **state, trips, rejections**.


---

## Known Uses

-   Netflix Hystrix (legacy) → **Resilience4j** circuit breaker/bulkhead/ratelimiter.

-   gRPC/HTTP clients in large microservice estates.

-   DB/Cache client wrappers to avoid connection storms during incidents.


---

## Related Patterns

-   **Timeouts & Retries** — breakers should wrap calls that already use **bounded** timeouts/retries.

-   **Bulkhead** — isolate capacity so failures in one dependency don’t starve others.

-   **Fallback / Graceful Degradation** — recommended with breakers.

-   **Rate Limiter** — control request rate; orthogonal to failure-based tripping.

-   **Health Check / Load Shedder** — complementary signals that can influence breaker behavior.
