# Circuit Breaker — Microservice Pattern

## Pattern Name and Classification

**Name:** Circuit Breaker  
**Classification:** Microservices / Resilience & Fault Tolerance / Stability Pattern

## Intent

Protect callers from repeatedly invoking an **unhealthy dependency** by **failing fast**. The breaker observes failures/latency, **opens** after a threshold (rejecting calls), and later **half-opens** to probe if recovery occurred, returning to **closed** on success.

## Also Known As

-   Fail-Fast Guard
    
-   Stability Switch
    
-   Trip Switch
    

## Motivation (Forces)

-   **Cascading failures:** Slow or erroring dependencies cause thread/connection exhaustion and retry storms.
    
-   **Unbounded waits:** Without timeouts + fast failure, end-to-end latency explodes.
    
-   **Self-healing:** Dependencies often recover; probes should test health without full load.
    
-   **Backpressure:** When the callee is down, the caller must shed load and degrade gracefully.
    

## Applicability

Use a **Circuit Breaker** when:

-   A request path depends on **remote services or resources** (HTTP/gRPC, DB, cache).
    
-   **Timeouts** are in place but still cause saturation under sustained failures.
    
-   You need **graceful degradation** (fallbacks) and predictable tail latency.
    

Be careful when:

-   Operations are **non-idempotent** and retries can cause side-effects.
    
-   Small traffic volumes make statistics noisy—use sensible **minimum sample sizes**.
    
-   You wrap **short local calls** where a breaker adds little value (use timeouts instead).
    

## Structure

-   **Breaker State Machine:** `CLOSED → OPEN → HALF_OPEN → CLOSED`
    
-   **Metrics Window:** Sliding window (count/time) tracking failures & “slow” calls.
    
-   **Thresholds & Durations:** Failure-rate %, slow-call %, open duration, probe count.
    
-   **Fallback/Degradation:** What to return when **OPEN** or **HALF\_OPEN without permit**.
    
-   **Observability:** Events (state changes), counters, and timings.
    

```lua
Caller --(execute)--> [CircuitBreaker] --(if CLOSED)--> Dependency
                         |   ^   \
                         |   |    \--(OPEN)--> Fast fail (fallback)
                         |   |
                         '---' (HALF_OPEN allows limited probes)
```

## Participants

-   **Caller (Service/Endpoint)** — initiates work.
    
-   **Circuit Breaker** — wraps the call and enforces the state machine.
    
-   **Dependency** — remote service/resource being protected.
    
-   **Fallback/Degrader** — optional alternate behavior.
    
-   **Metrics/Tracing** — visibility and alerting.
    

## Collaboration

1.  Caller executes through the breaker.
    
2.  **Closed:** Calls flow; breaker records outcomes and durations.
    
3.  When failure/slow rates breach thresholds (and minimum samples met), breaker **opens** for a hold period, rejecting calls quickly.
    
4.  After the hold period, breaker **half-opens** and allows a small number of **probe** calls.
    
5.  If probes succeed within thresholds → **close**; else **re-open**.
    

## Consequences

**Benefits**

-   Stops cascades; protects threads and connection pools.
    
-   Stabilizes p95/p99 latency via **fast failures**.
    
-   Provides automatic **self-healing** via probes.
    

**Liabilities**

-   Adds complexity and state to operations.
    
-   Misconfigured thresholds can flap (open/close frequently) or mask incidents.
    
-   Requires solid **timeout** and **error classification** to work well.
    

## Implementation

**Key practices**

-   **Pair with timeouts:** No breaker can help without aggressive timeouts per hop.
    
-   **Classify errors:** Count only **retryable**/system errors and **slow calls** toward tripping.
    
-   **Choose windows wisely:** Sliding **count** (e.g., last 100 calls) or **time** (last 30s), with **minimum number of calls**.
    
-   **Half-open permits:** Allow a small number (e.g., 5) of concurrent probes.
    
-   **Fallbacks:** Return cached/partial data or a clear, fast failure.
    
-   **Integration:** Combine with **bulkheads** (separate pools), **jittered retries**, and **rate limits**.
    
-   **Observability:** Emit state-change events and metrics: `state`, `failure_rate`, `slow_rate`, `rejected_total`.
    

---

## Sample Code (Java, dependency-light)

A compact, production-leaning **circuit breaker** with:

-   Failure-rate and slow-call thresholds over a sliding window
    
-   `CLOSED/OPEN/HALF_OPEN` states with half-open probe permits
    
-   Fast-fail exceptions while **OPEN**
    
-   An example wrapper around `java.net.http.HttpClient`
    

```java
import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Objects;
import java.util.concurrent.Callable;
import java.util.concurrent.Semaphore;
import java.util.function.Supplier;

public class CircuitBreaker {

    public enum State { CLOSED, OPEN, HALF_OPEN }

    public static final class Config {
        public final int slidingWindowSize;            // e.g., 100 calls
        public final int minCallsToEvaluate;           // e.g., 50
        public final double failureRateThreshold;      // 0..1 (e.g., 0.5 => 50%)
        public final double slowCallRateThreshold;     // 0..1
        public final Duration slowCallDuration;        // e.g., 300ms
        public final Duration openStateDuration;       // how long to stay OPEN
        public final int halfOpenMaxCalls;             // concurrent probes allowed

        public Config(int window, int min, double failTh, double slowTh, Duration slowDur, Duration openDur, int halfOpenMax) {
            this.slidingWindowSize = window;
            this.minCallsToEvaluate = min;
            this.failureRateThreshold = failTh;
            this.slowCallRateThreshold = slowTh;
            this.slowCallDuration = slowDur;
            this.openStateDuration = openDur;
            this.halfOpenMaxCalls = halfOpenMax;
        }
    }

    private static final class Sample {
        final boolean success;
        final long durationMs;
        Sample(boolean success, long durationMs) { this.success = success; this.durationMs = durationMs; }
    }

    private final Config cfg;
    private final Deque<Sample> window;
    private State state = State.CLOSED;
    private long openedAtMillis = 0L;
    private final Semaphore halfOpenPermits;
    private final Object lock = new Object();

    public CircuitBreaker(Config cfg) {
        this.cfg = Objects.requireNonNull(cfg);
        this.window = new ArrayDeque<>(cfg.slidingWindowSize);
        this.halfOpenPermits = new Semaphore(cfg.halfOpenMaxCalls, true);
    }

    public State state() { synchronized (lock) { return state; } }

    public <T> T execute(Callable<T> task) throws Exception {
        // Fast path: state decision
        State s;
        synchronized (lock) {
            s = state;
            if (s == State.OPEN) {
                if (System.currentTimeMillis() - openedAtMillis >= cfg.openStateDuration.toMillis()) {
                    // transition to HALF_OPEN
                    transitionTo(State.HALF_OPEN);
                } else {
                    throw new CircuitOpenException("circuit open");
                }
            }
        }

        if (state() == State.HALF_OPEN) {
            if (!halfOpenPermits.tryAcquire()) throw new CircuitOpenException("half-open probes exhausted");
        }

        long start = System.nanoTime();
        boolean ok = false;
        try {
            T result = task.call();
            ok = true;
            return result;
        } catch (Exception ex) {
            record(ok, start);
            // rethrow original
            throw ex;
        } finally {
            if (ok) record(true, start);
            if (state() == State.HALF_OPEN) halfOpenPermits.release();
        }
    }

    private void record(boolean success, long startNano) {
        long durMs = Duration.ofNanos(System.nanoTime() - startNano).toMillis();
        synchronized (lock) {
            // push to window
            if (window.size() == cfg.slidingWindowSize) window.removeFirst();
            window.addLast(new Sample(success, durMs));
            evaluate();
        }
    }

    private void evaluate() {
        int size = window.size();
        if (size < cfg.minCallsToEvaluate) {
            // In HALF_OPEN with insufficient samples, stay there
            return;
        }
        int failures = 0, slow = 0;
        for (Sample s : window) {
            if (!s.success) failures++;
            if (s.durationMs > cfg.slowCallDuration.toMillis()) slow++;
        }
        double failRate = (double) failures / size;
        double slowRate = (double) slow / size;
        switch (state) {
            case CLOSED -> {
                if (failRate >= cfg.failureRateThreshold || slowRate >= cfg.slowCallRateThreshold) {
                    transitionTo(State.OPEN);
                }
            }
            case HALF_OPEN -> {
                // In HALF_OPEN we use stricter rule: any failure -> OPEN
                if (failRate > 0.0 || slowRate >= cfg.slowCallRateThreshold) {
                    transitionTo(State.OPEN);
                } else if (size >= cfg.minCallsToEvaluate) {
                    // Healthy samples → back to CLOSED
                    transitionTo(State.CLOSED);
                }
            }
            case OPEN -> { /* handled by time passage in execute() */ }
        }
    }

    private void transitionTo(State target) {
        if (state == target) return;
        state = target;
        if (target == State.OPEN) {
            openedAtMillis = System.currentTimeMillis();
            window.clear();
        } else if (target == State.HALF_OPEN) {
            window.clear();
            halfOpenPermits.drainPermits();
            halfOpenPermits.release(cfg.halfOpenMaxCalls);
        } else if (target == State.CLOSED) {
            window.clear();
        }
        // hook: emit event/metric here if desired
        // e.g., System.out.println("CB -> " + target);
    }

    // --- Exception used to signal fast-fail ---
    public static final class CircuitOpenException extends RuntimeException {
        public CircuitOpenException(String msg) { super(msg); }
    }

    // --- Tiny demo against HttpClient ---
    public static void main(String[] args) throws Exception {
        CircuitBreaker cb = new CircuitBreaker(new Config(
            50,              // sliding window size
            20,              // min calls to evaluate
            0.5,             // 50% failure threshold
            0.5,             // 50% slow-call threshold
            Duration.ofMillis(300),
            Duration.ofSeconds(10),
            5                // half-open probes
        ));

        HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofMillis(200)).build();

        Callable<String> call = () -> {
            HttpRequest req = HttpRequest.newBuilder(URI.create("http://localhost:9999/slow")) // make it fail/slow to see trips
                    .timeout(Duration.ofMillis(250))
                    .GET().build();
            HttpResponse<String> res = http.send(req, HttpResponse.BodyHandlers.ofString());
            if (res.statusCode() >= 500) throw new RuntimeException("server error");
            return res.body();
        };

        for (int i = 0; i < 200; i++) {
            try {
                String body = cb.execute(call);
                System.out.println("OK len=" + body.length());
            } catch (CircuitOpenException e) {
                System.out.println("FAST-FAIL (" + cb.state() + ")");
                Thread.sleep(200); // back off
            } catch (Exception ex) {
                System.out.println("Error: " + ex.getClass().getSimpleName());
            }
            Thread.sleep(50);
        }
    }
}
```

**Notes on the sample**

-   Wrap *any* `Callable<T>`; it measures duration and updates the state machine.
    
-   `CircuitOpenException` signals callers to **fallback** quickly.
    
-   The demo loops against a likely failing/slow URL to show the breaker tripping and probing.
    

> Prefer a mature library (e.g., **Resilience4j**) in production, which already provides circuit breakers with sliding windows, slow-call detection, metrics, and integration with Spring, Reactor, and Micrometer.

---

## Known Uses

-   **Netflix / Hystrix heritage**: Protecting per-dependency calls in large call graphs.
    
-   **Payment/checkout flows**: Failing fast on recommendation/email services while keeping core purchase path alive.
    
-   **Search/indexing**: Shielding optional personalization from impacting critical queries.
    
-   **Third-party APIs**: Preventing costly rate-limit spirals and timeouts from cascading.
    

## Related Patterns

-   **Bulkhead:** Partition concurrency so one dependency can’t starve others—often paired with breakers.
    
-   **Timeouts & Retries (with Jitter):** Bound latency and avoid synchronized retries during incidents.
    
-   **Rate Limiter / Token Bucket:** Throttle traffic before it hits the breaker.
    
-   **Fallback / Degradation:** Provide cached or partial responses during outages.
    
-   **Canary / Blue-Green:** Safer releases reduce breaker trips during deploys.
    
-   **Outlier Detection / Load Balancing:** Eject bad endpoints to reduce failure rates.

