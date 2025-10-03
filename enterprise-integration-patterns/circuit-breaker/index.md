# Circuit Breaker (Enterprise Integration Pattern)

## Pattern Name and Classification

**Name:** Circuit Breaker  
**Classification:** Enterprise Integration Pattern (Reliability / Fault-Tolerance / Stability)

---

## Intent

Prevent a **cascading failure** by **monitoring calls to a remote dependency** and **failing fast** when the dependency is unhealthy. Automatically attempt recovery after a cool-down, and provide **fallbacks** so the system degrades gracefully instead of timing out or collapsing.

---

## Also Known As

-   Fail-Fast Switch
    
-   Service Fuse
    
-   Protective Proxy (reliability-focused)
    

---

## Motivation (Forces)

Distributed systems are vulnerable to:

-   **Slow failures** (timeouts, retries) that exhaust threads, connections, and queues.
    
-   **Thundering herds** that make a degraded dependency collapse completely.
    
-   **Retry storms** that magnify small incidents.
    

A Circuit Breaker:

-   Detects failure patterns (error rate, slow calls).
    
-   **Opens** to stop traffic and return fast failures/fallbacks.
    
-   **Half-opens** to probe if the dependency has recovered.
    
-   **Closes** when success resumes—protecting resources and keeping latencies predictable.
    

Trade-offs:

-   Choosing **sensible thresholds** vs. false trips.
    
-   Balancing **freshness** (no cache/fallback) vs **availability** (serve stale/approximate data).
    
-   Getting **metrics windows** and **probing** right for uneven traffic.
    

---

## Applicability

Use a Circuit Breaker when:

-   A call crosses **process/network** boundaries (HTTP/gRPC/JDBC/message broker).
    
-   The dependency can **degrade or throttle** under load.
    
-   You must meet **SLAs** and keep **tail latencies** bounded.
    
-   You have **fallbacks** (cached data, default responses, queued work, alternative providers).
    

Avoid or limit when:

-   Calls are **purely in-process** and cheap (prefer plain exceptions/backpressure).
    
-   Correctness absolutely requires **strong consistency** and no fallback is acceptable (use time-boxed retries and propagate errors instead).
    

---

## Structure

-   **Caller / Client:** Invokes a remote operation through the breaker.
    
-   **Circuit Breaker:** Tracks outcomes and **state**:
    
    -   **Closed:** Calls flow; count successes/failures in a rolling/sliding window.
        
    -   **Open:** Short-circuit; immediately fail or use fallback for a **cool-down window**.
        
    -   **Half-Open:** Allow limited **probe** calls; if they succeed → **Close**, else → **Open**.
        
-   **Fallback / Degradation Path:** Cache, defaults, queue, alternate route.
    
-   **Metrics & Policy:** Window size, failure-rate threshold, slow-call threshold, open duration, max concurrent probes.
    

---

## Participants

-   **Policy:** Thresholds (failure %, slow %), sampling window, durations.
    
-   **State Store:** In-memory (per instance) or centralized (cluster/coordinator).
    
-   **Timer/Scheduler:** Drives open-duration expiry and half-open probes.
    
-   **Metrics/Tracing:** Emits state changes and call outcomes.
    

---

## Collaboration

1.  Caller executes `breaker.call(supplier, fallback)`.
    
2.  **Closed:** Execution proceeds. Breaker records **success/failure/slow**.
    
3.  If error or slow-call rate crosses threshold → **Open** and start cool-down timer.
    
4.  While **Open**: short-circuit to **fallback** (or error) immediately.
    
5.  After cool-down: **Half-Open**. Allow N probe calls.
    
    -   If probe successes exceed policy, transition to **Closed** and reset stats.
        
    -   If a probe fails/slow ⇒ **Open** again (longer backoff is common).
        
6.  All transitions and stats are **observable** (metrics/logs).
    

---

## Consequences

**Benefits**

-   **Fail-fast** protects threads and connection pools.
    
-   **Graceful degradation** via fallbacks.
    
-   **Self-healing** through half-open probing.
    
-   **Predictable latency** and improved upstream stability.
    

**Liabilities**

-   **Tuning complexity:** thresholds, windows, open durations.
    
-   **False positives** on sparse traffic or bursty errors.
    
-   **State locality:** per-instance breakers may flap differently; centralized coordination adds complexity.
    
-   **Masking real failures** if fallbacks hide persistent outages.
    

---

## Implementation

**Design guidelines**

-   Track **both failures and slow calls** (e.g., > p95 budget) in a **rolling/sliding window**.
    
-   Use **time-boxed execution** (timeouts) *before* breaker accounting.
    
-   Prefer **idempotent operations** to allow retries/probes safely.
    
-   **Bulkhead** the client (separate thread/connection pools) to isolate failures.
    
-   Emit **metrics**: state, failure rate, slow rate, calls permitted/denied.
    
-   Use **exponential backoff** for successive open durations (jittered).
    
-   Provide **clear fallbacks**: cached response, default, enqueue, or alternate provider.
    

**Operational tips**

-   Start conservative: e.g., window=50 calls, failureRate≥50%, slowRate≥60% with slowCallDuration=1s, openDuration=30s, halfOpenPermits=5.
    
-   Instrument with tracing tags: `breaker.state`, `remote.service`, `reason=open_threshold_exceeded`.
    
-   Load test with dependency fault injection (latency spikes, 5xx, connection resets).
    

---

## Sample Code (Java, minimal dependency-free breaker + usage)

### 1) A lightweight Circuit Breaker

```java
import java.time.*;
import java.util.Objects;
import java.util.concurrent.Callable;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Supplier;

public final class CircuitBreaker {

    public enum State { CLOSED, OPEN, HALF_OPEN }

    public static final class Policy {
        public final int windowSize;                 // number of recent calls to consider
        public final double failureRateThreshold;    // 0.0..1.0
        public final double slowRateThreshold;       // 0.0..1.0
        public final Duration slowCallDuration;      // calls slower than this count as "slow"
        public final Duration openDuration;          // how long to stay OPEN before HALF_OPEN
        public final int halfOpenMaxCalls;           // concurrent probes permitted in HALF_OPEN

        public Policy(int windowSize, double failureRateThreshold, double slowRateThreshold,
                      Duration slowCallDuration, Duration openDuration, int halfOpenMaxCalls) {
            if (windowSize <= 0) throw new IllegalArgumentException("windowSize>0");
            this.windowSize = windowSize;
            this.failureRateThreshold = failureRateThreshold;
            this.slowRateThreshold = slowRateThreshold;
            this.slowCallDuration = Objects.requireNonNull(slowCallDuration);
            this.openDuration = Objects.requireNonNull(openDuration);
            this.halfOpenMaxCalls = halfOpenMaxCalls;
        }
        public static Policy sensibleDefaults() {
            return new Policy(50, 0.5, 0.6,
                    Duration.ofMillis(1000), Duration.ofSeconds(30), 5);
        }
    }

    private final String name;
    private final Policy policy;

    // ring buffer of last outcomes (success/failure/slow)
    private final Outcome[] ring;
    private int ringIdx = 0;
    private int ringCount = 0;

    private volatile State state = State.CLOSED;
    private Instant openUntil = Instant.MIN;
    private final AtomicInteger halfOpenInFlight = new AtomicInteger();

    private enum Outcome { SUCCESS_FAST, SUCCESS_SLOW, FAILURE }

    public CircuitBreaker(String name, Policy policy) {
        this.name = name;
        this.policy = policy;
        this.ring = new Outcome[policy.windowSize];
    }

    public State state() { return state; }

    public <T> T call(Callable<T> supplier, Supplier<T> fallback, Duration timeout) throws Exception {
        if (!allowCall()) {
            return fallbackOrThrow(fallback, new IllegalStateException("breaker open: " + name));
        }
        long start = System.nanoTime();
        try {
            T result = runWithTimeout(supplier, timeout);
            recordOutcome(durationMs(start) > policy.slowCallDuration.toMillis() ? Outcome.SUCCESS_SLOW : Outcome.SUCCESS_FAST);
            onSuccessAfterCall();
            return result;
        } catch (Exception e) {
            recordOutcome(Outcome.FAILURE);
            onFailureAfterCall();
            return fallbackOrThrow(fallback, e);
        }
    }

    private boolean allowCall() {
        switch (state) {
            case CLOSED: return true;
            case OPEN:
                if (Instant.now().isAfter(openUntil)) {
                    transitionTo(State.HALF_OPEN);
                } else {
                    return false;
                }
                // fallthrough
            case HALF_OPEN:
                int inFlight = halfOpenInFlight.incrementAndGet();
                if (inFlight <= policy.halfOpenMaxCalls) return true;
                halfOpenInFlight.decrementAndGet();
                return false;
            default: return false;
        }
    }

    private <T> T fallbackOrThrow(Supplier<T> fallback, Exception cause) throws Exception {
        if (fallback != null) return fallback.get();
        if (cause instanceof Exception ex) throw ex;
        throw new RuntimeException(cause);
    }

    private void onSuccessAfterCall() {
        if (state == State.HALF_OPEN) {
            if (successRatio() >= (1.0 - policy.failureRateThreshold)) {
                transitionTo(State.CLOSED);
            }
            halfOpenInFlight.decrementAndGet();
        } // CLOSED remains CLOSED unless thresholds exceeded
        evaluateThresholds();
    }

    private void onFailureAfterCall() {
        if (state == State.HALF_OPEN) {
            // Any failure while probing flips back to OPEN immediately
            open();
            halfOpenInFlight.decrementAndGet();
        } else {
            evaluateThresholds();
        }
    }

    private void evaluateThresholds() {
        if (ringCount < policy.windowSize) return;
        double failureRate = rate(Outcome.FAILURE);
        double slowRate = rate(Outcome.SUCCESS_SLOW);
        if (failureRate >= policy.failureRateThreshold || slowRate >= policy.slowRateThreshold) {
            open();
        }
    }

    private void open() {
        transitionTo(State.OPEN);
        openUntil = Instant.now().plus(policy.openDuration);
    }

    private void transitionTo(State newState) {
        this.state = newState;
        if (newState == State.CLOSED) {
            // reset counters
            ringIdx = 0; ringCount = 0;
        }
        if (newState != State.HALF_OPEN) {
            halfOpenInFlight.set(0);
        }
        // hook: emit metrics/logs if desired
        // System.out.println("breaker " + name + " -> " + newState);
    }

    private void recordOutcome(Outcome o) {
        ring[ringIdx] = o;
        ringIdx = (ringIdx + 1) % policy.windowSize;
        if (ringCount < policy.windowSize) ringCount++;
    }

    private double rate(Outcome x) {
        if (ringCount == 0) return 0.0;
        int c = 0;
        for (int i = 0; i < ringCount; i++) if (ring[i] == x) c++;
        return (double) c / ringCount;
    }

    private long durationMs(long startNs) {
        return (System.nanoTime() - startNs) / 1_000_000L;
    }

    private <T> T runWithTimeout(Callable<T> task, Duration timeout) throws Exception {
        // Minimal timebox without extra thread pools: rely on dependency client timeouts.
        // For strict timeouts, wrap with Future & Executor; omitted for brevity.
        return task.call();
    }
}
```

### 2) Example usage with a remote HTTP client

```java
import java.net.http.*;
import java.net.URI;
import java.time.Duration;

public final class ProductCatalogClient {

    private final HttpClient http = HttpClient.newBuilder()
            .connectTimeout(Duration.ofMillis(300))
            .build();

    private final CircuitBreaker breaker = new CircuitBreaker(
            "catalog",
            CircuitBreaker.Policy.sensibleDefaults()
    );

    // Fallback returns a cached summary if live call is failing/open
    private volatile String lastKnownGood = "{\"items\":[]}";

    public String getProducts() {
        try {
            return breaker.call(
                () -> fetchLive(),
                () -> lastKnownGood,                // fallback (fast, local)
                Duration.ofMillis(800)              // desired total budget
            );
        } catch (Exception e) {
            // if no fallback, you can translate to 503 upstream
            throw new RuntimeException("catalog unavailable", e);
        }
    }

    private String fetchLive() throws Exception {
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create("https://catalog.example.com/api/products"))
                .timeout(Duration.ofMillis(700))    // client-level timeout
                .GET().build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() >= 500) throw new IllegalStateException("upstream 5xx");
        String body = resp.body();
        lastKnownGood = body;                      // refresh cache on success
        return body;
    }
}
```

### 3) (Optional) Using a production library (Resilience4j) — concise example

```java
// Resilience4j example (add io.github.resilience4j:resilience4j-circuitbreaker + timers/metrics deps)
import io.github.resilience4j.circuitbreaker.*;
import io.github.resilience4j.decorators.Decorators;

CircuitBreakerConfig cfg = CircuitBreakerConfig.custom()
        .failureRateThreshold(50.0f)
        .slowCallRateThreshold(60.0f)
        .slowCallDurationThreshold(Duration.ofMillis(1000))
        .slidingWindowType(CircuitBreakerConfig.SlidingWindowType.COUNT_BASED)
        .slidingWindowSize(50)
        .minimumNumberOfCalls(20)
        .waitDurationInOpenState(Duration.ofSeconds(30))
        .permittedNumberOfCallsInHalfOpenState(5)
        .build();

CircuitBreaker cb = CircuitBreaker.of("catalog", cfg);

String result = Decorators.ofSupplier(() -> fetchLive())
        .withCircuitBreaker(cb)
        .withFallback(ex -> cacheOrDefault())
        .get();
```

---

## Known Uses

-   **API Gateways / Edge services:** Protect upstreams; serve cached/placeholder content on outage.
    
-   **Payment / Risk engines:** Fall back to conservative decisions or queue for later processing.
    
-   **Search / Recommendation:** Serve stale results when personalization is down.
    
-   **Inventory / Pricing:** Use snapshot/last-known values during partial outages.
    
-   **DB/Broker clients:** Wrap JDBC, Redis, or MQ operations to avoid thread starvation.
    

---

## Related Patterns

-   **Timeouts & Retries:** Always combine with timeouts and **bounded** retries (jittered backoff).
    
-   **Bulkhead (Isolation):** Separate pools/limits to prevent resource exhaustion.
    
-   **Fallback / Graceful Degradation:** What you return when the breaker is open.
    
-   **Rate Limiter & Load Shedding:** Proactively reduce load under pressure.
    
-   **Health Check / Adaptive Probing:** Inform breaker decisions and adjust policies.
    
-   **Cache-Aside / Stale-While-Revalidate:** Typical fallback strategies.
    

---

