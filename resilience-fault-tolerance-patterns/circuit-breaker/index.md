# Circuit Breaker — Resilience & Fault-Tolerance Pattern

## Pattern Name and Classification

**Name:** Circuit Breaker  
**Classification:** Resilience / Fault-Tolerance Pattern (Failure Detection & Isolation)

## Intent

Protect a caller from repeatedly invoking a **failing or slow dependency** by **short-circuiting** calls after failures cross a threshold. The breaker transitions among **Closed → Open → Half-Open** to allow recovery probes while preventing cascades.

## Also Known As

-   Automatic Fault Tripper
    
-   Fail-Fast Guard
    
-   Trip/Reset Switch
    

## Motivation (Forces)

-   **Fail fast vs. pile-ups:** Persistent timeouts stack up and saturate threads and connection pools.
    
-   **Backpressure:** We need a clear “stop calling” signal to avoid amplifying downstream outages.
    
-   **Self-healing:** After a cooldown, send limited probes to see if the dependency recovered.
    
-   **Observability:** Centralize failure accounting and expose **clear metrics** to operators.
    

## Applicability

Use Circuit Breaker when:

-   A client calls **remote services** (HTTP/DB/MQ) that can become unavailable or slow.
    
-   You’ve seen **retry storms**, thread starvation, or long tail latencies during incidents.
    
-   You can provide **fallbacks** (cached/partial data) or user-visible degradation.
    

Avoid or be cautious when:

-   Calls are **idempotent and ultra-cheap** and failures are rare—overhead may not pay off.
    
-   There’s **no acceptable fallback** and failing fast is worse than waiting (batch one-offs).
    
-   Errors are **client-side** and should be fixed at source (e.g., invalid request schema).
    

## Structure

```pgsql
┌───────────────┐  success/failure  ┌───────────────┐
            │   CLOSED      │ ─────────────────► │   OPEN        │
  calls go  │ count errors  │  threshold met     │ fail fast     │
  through   │ pass traffic  │  -> trip           │ cooldown timer│
            └──────▲────────┘                    └───────┬───────┘
                   │                                     │ cooldown elapsed
                   │                                     ▼
                   │                              ┌───────────────┐
                   └──────────────────────────────│  HALF-OPEN    │
                                  limited probes  │ allow N probes│
                                                  └───────▲───────┘
                                                          │
                                         success probes -> │ reset to CLOSED
                                         failure probe  -> │ trip to OPEN
```

## Participants

-   **Circuit Breaker:** Tracks state, counts failures/successes, decides to pass/short-circuit calls.
    
-   **Caller:** Wraps dependency calls with the breaker.
    
-   **Dependency:** Remote service or component that may fail/timeout.
    
-   **Fallback / Degrader:** Optional path when breaker blocks calls.
    
-   **Timers & Metrics:** Measure cooldowns, error rates, and state transitions.
    

## Collaboration

-   Caller executes `breaker.call(task, fallback)` (or similar).
    
-   Breaker **rejects** calls immediately in **OPEN**; allows limited **HALF-OPEN** probes.
    
-   Outcome of probes **drives state**; metrics/alerts inform autoscaling and SRE response.
    
-   Often combined with **Bulkhead** (isolation), **Timeout** (don’t hold capacity), and **Retry with backoff** (but only when breaker is allowing traffic).
    

## Consequences

**Benefits**

-   **Containment:** Prevents cascades and thread/connection exhaustion.
    
-   **Predictability:** Fails fast with clear errors during downstream outages.
    
-   **Recovery:** Automatic probing avoids manual intervention.
    
-   **Operability:** Centralized metrics and state transitions.
    

**Liabilities / Trade-offs**

-   **Tuning required:** Poor thresholds can flap or trip too eagerly.
    
-   **Statefulness:** Requires clock/time coordination in distributed systems.
    
-   **False positives:** Client-side bugs can trip breakers; root cause must be addressed.
    
-   **Overhead:** Small latency/complexity per call (usually negligible compared to network I/O).
    

## Implementation

1.  **Choose trigger logic:** Count-based (N failures in window) or **error-rate** over sliding window; include **timeouts** as failures.
    
2.  **Define windows & limits:** e.g., 50% failures over 20 calls; cooldown (open) duration; **half-open probe quota**.
    
3.  **Decide trip causes:** Exceptions, HTTP 5xx, timeouts; optionally **slow-call** thresholds.
    
4.  **Implement states:** Closed (pass), Open (reject), Half-Open (limited probes).
    
5.  **Add fallbacks:** Stale cache, defaults, or user-facing “degraded mode.”
    
6.  **Expose metrics & events:** State, failure rate, rejections, probe outcomes, latency.
    
7.  **Compose with other guards:** Generally: **Bulkhead → Timeout → CircuitBreaker → Retry** (retry only if breaker lets the call through).
    
8.  **Tune & test chaos:** Load test, inject faults, verify rejection rates and recovery behavior.
    

---

## Sample Code (Java)

*A compact, thread-safe, count-based circuit breaker with cooldown and half-open probes.*

```java
import java.time.Duration;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Supplier;

public class CircuitBreaker {

  public enum State { CLOSED, OPEN, HALF_OPEN }

  // Config
  private final int failureThreshold;          // e.g., 5 consecutive failures
  private final Duration openCooldown;         // e.g., 10s
  private final int halfOpenMaxCalls;          // e.g., 3 probes

  // State
  private final AtomicReference<State> state = new AtomicReference<>(State.CLOSED);
  private final AtomicInteger consecutiveFailures = new AtomicInteger(0);
  private final AtomicLong openedAt = new AtomicLong(0);
  private final AtomicInteger halfOpenInFlight = new AtomicInteger(0);

  public CircuitBreaker(int failureThreshold, Duration openCooldown, int halfOpenMaxCalls) {
    this.failureThreshold = failureThreshold;
    this.openCooldown = openCooldown;
    this.halfOpenMaxCalls = halfOpenMaxCalls;
  }

  public <T> T call(CheckedSupplier<T> supplier, Supplier<T> fallback) throws Exception {
    State s = currentState();
    if (s == State.OPEN) {
      if (cooldownExpired()) {
        // Try to move to HALF_OPEN once per thread race safely
        if (state.compareAndSet(State.OPEN, State.HALF_OPEN)) {
          halfOpenInFlight.set(0);
        }
      } else {
        return fallback.get(); // fail fast
      }
    }

    s = state.get();
    if (s == State.HALF_OPEN && halfOpenInFlight.incrementAndGet() > halfOpenMaxCalls) {
      halfOpenInFlight.decrementAndGet();
      return fallback.get(); // limit probes
    }

    try {
      T result = supplier.get();
      onSuccess();
      return result;
    } catch (Exception e) {
      onFailure(e);
      return fallback.get();
    } finally {
      if (state.get() == State.HALF_OPEN) {
        halfOpenInFlight.decrementAndGet();
      }
    }
  }

  private void onSuccess() {
    if (state.get() == State.HALF_OPEN) {
      // Success in HALF_OPEN resets breaker
      consecutiveFailures.set(0);
      state.set(State.CLOSED);
      return;
    }
    consecutiveFailures.set(0);
  }

  private void onFailure(Exception e) {
    if (state.get() == State.HALF_OPEN) {
      tripOpen();
      return;
    }
    int fails = consecutiveFailures.incrementAndGet();
    if (fails >= failureThreshold || isTimeout(e)) {
      tripOpen();
    }
  }

  private boolean isTimeout(Exception e) {
    return e instanceof TimeoutException;
  }

  private void tripOpen() {
    state.set(State.OPEN);
    openedAt.set(System.nanoTime());
  }

  private boolean cooldownExpired() {
    long nanos = System.nanoTime() - openedAt.get();
    return nanos >= openCooldown.toNanos();
  }

  private State currentState() { return state.get(); }

  public State state() { return state.get(); }

  @FunctionalInterface public interface CheckedSupplier<T> { T get() throws Exception; }
}
```

**Usage Example**

```java
public class CustomerClient {
  private final CircuitBreaker breaker =
      new CircuitBreaker(5, Duration.ofSeconds(10), 3); // 5 fails → OPEN 10s; 3 probes

  private final HttpClient http; // your adapter; ensure timeouts are set!

  public CustomerClient(HttpClient http) { this.http = http; }

  public String fetchById(String id) throws Exception {
    return breaker.call(
        () -> http.get("/customers/" + id),   // protected operation
        () -> "{}"                             // fallback (stale cache or minimal object)
    );
  }
}

// Example HttpClient adapter (simplified)
interface HttpClient { String get(String path) throws Exception; }
```

**Notes**

-   Treat **timeouts and slow calls** as failures; always set client timeouts.
    
-   For error-rate-based breakers, track a rolling window and compute failure %, not just consecutive fails.
    
-   In production, prefer a library (e.g., Resilience4j) for advanced policies, metrics, and integration.
    

---

## Known Uses

-   **API gateways / edge services:** Trip per upstream to protect the edge.
    
-   **Microservices:** Wrapping calls to payment, catalog, auth, or recommendation services.
    
-   **Database / cache drivers:** Short-circuit to read replicas or in-memory cache when primaries fail.
    
-   **Third-party integrations:** Prevent SLAs from being hostage to external outages.
    

## Related Patterns

-   **Bulkhead:** Isolate resources so a failing dependency can’t starve others; use together.
    
-   **Timeouts:** Bound call duration so failures are observable quickly.
    
-   **Retry with Exponential Backoff & Jitter:** Retry only **inside** a closed/half-open window; stop when open.
    
-   **Fallback / Graceful Degradation:** Provide alternates when breaker rejects.
    
-   **Rate Limiting / Load Shedding:** Upstream admission control to avoid overload during partial outages.
    
-   **Health Checks & Adaptive Routing:** Steer traffic away from unhealthy instances while breaker protects callers.
    

**Rule of thumb:** **Fail fast, recover safe.** Use circuit breakers to turn chaotic failure patterns into predictable, observable states that you can operate and scale.

