# Circuit Breaker — Security Pattern

## Pattern Name and Classification

**Name:** Circuit Breaker  
**Classification:** Security / Resilience / Fault-Containment (Runtime risk control for untrusted/unstable dependencies)

> Although commonly listed under resiliency, Circuit Breaker is also a **security** control: it limits the *blast radius* of failing or malicious upstreams/downstreams (e.g., slowloris backends, credential-stuffing proxies, abusive tenants), protects scarce resources, and enforces **fail-closed** behavior under uncertainty.

---

## Intent

Detect failure or pathological latency in a dependency and **short-circuit** further calls until it recovers. While open, **fast-fail** or serve a **safe fallback**, preventing resource exhaustion, data exfiltration through timing side channels, and cascading failure.

---

## Also Known As

-   Fuse
    
-   Trip Switch
    
-   Fast-Fail Guard
    
-   Service Breaker
    

---

## Motivation (Forces)

-   **Cascading failure risk:** Timeouts and retries against a degraded dependency amplify load (“retry storms”).
    
-   **Resource exhaustion:** Thread pools, DB connections, and queues can be drained by slow calls.
    
-   **Abuse & anomaly:** Attackers can force pathological code paths (e.g., expensive search queries) or trigger throttling evasion via jittering.
    
-   **Observability gaps:** In partial outages it’s unclear when to give up vs. keep trying.
    
-   **User experience:** Better to fail fast with a **bounded** error than hang indefinitely.
    

*Trade-offs:* False trips vs. slow recovery; balancing **safety** (deny by default) against **availability**.

---

## Applicability

Use a Circuit Breaker when:

-   A downstream (DB, payment gateway, third-party API) is **slow**, **failing**, or **rate-limiting** you.
    
-   You need **tenant-scoped** protection so one bad tenant does not impact others.
    
-   You must implement **security guardrails**: fail safely on suspicious conditions (e.g., request storms, error spikes).
    

Avoid or adapt when:

-   The operation is **non-idempotent** and you cannot provide a safe fallback—consider **queue-based decoupling**.
    
-   The caller can tolerate **long waits** and you have robust back-pressure elsewhere.
    
-   The dependency performs **critical writes** with strict consistency; use **fine-grained, scoped** breakers and compensations.
    

---

## Structure

-   **Policy & State:** `Closed` → normal; `Open` → short-circuit; `Half-Open` → limited probes.
    
-   **Metrics Window:** rolling counts of failures, timeouts, and slow calls.
    
-   **Trip Conditions:** error rate ≥ threshold, **consecutive** failures, or p95 latency above SLO.
    
-   **Cooldown Timer:** minimum time breaker stays **Open** before trial.
    
-   **Probe Controller:** number of trial calls allowed in **Half-Open**.
    
-   **Fallback Handler:** returns cached/partial data, static response, or a safe error.
    
-   **Scopes:** global, per-endpoint, **per-tenant**, or **per-credential**.
    

---

## Participants

-   **Caller / Client Library** — wraps the call with breaker logic.
    
-   **Circuit Breaker** — tracks stats, decides to allow/deny, exposes events.
    
-   **Dependency** — service/database being called.
    
-   **Telemetry** — emits state changes, failure reasons, and slow-call histograms.
    
-   **Policy Store** (optional) — dynamic thresholds per environment/tenant.
    

---

## Collaboration

1.  Caller executes an operation via the **breaker**.
    
2.  **Closed:** call proceeds; outcomes recorded.
    
3.  If failure/latency exceeds policy → breaker **trips Open** for a cooldown.
    
4.  **Open:** requests are **short-circuited** to **fallback** (or denied) without touching dependency.
    
5.  After cooldown → **Half-Open:** only **N** probes pass through.
    
6.  If probes succeed under thresholds → **Closed**; else back to **Open**.
    

---

## Consequences

**Benefits**

-   Prevents **resource saturation** and **retry storms**; bounds tail latency.
    
-   Provides **fail-safe defaults** (security posture: deny or limited data).
    
-   Clear **operational signal** via state transitions.
    

**Liabilities**

-   **False positives** can block healthy services (mitigate with adaptive thresholds and manual override).
    
-   **State divergence** if breakers are not partitioned correctly (e.g., by tenant).
    
-   Fallback paths can inadvertently **leak stale/partial data** if not vetted.
    

---

## Implementation

### Key Decisions

-   **Trip policy:**
    
    -   Error-rate over rolling window;
        
    -   Consecutive failures;
        
    -   **Slow-call rate** (e.g., > SLO for ≥ X% of calls).
        
-   **Scope & isolation:** per endpoint, **per tenant/API key**, or per host.
    
-   **Timeouts & budgets:** pair with **timeouts** and **retry budgets** (not infinite retries).
    
-   **Fallback strategy:** static response, cached data, alternate region, or **explicit 503** with safe messaging.
    
-   **Security posture:** during Open, return **constant-time** failure to reduce timing side-channels; redact details.
    
-   **Telemetry:** emit **state changes**, **trip reason**, slow-call histograms, and **tenant labels**.
    
-   **Manual controls:** admin API to **force Open/Closed**, adjust thresholds, or drain probes.
    

### Anti-Patterns

-   Breaker without **timeouts** (calls can still hang).
    
-   **Global** breaker for heterogeneous traffic (trip due to one noisy tenant).
    
-   Blind **automatic retries** behind the breaker (amplifies load when Half-Open).
    
-   Fallbacks that violate **authorization** or **data classification**.
    

---

## Sample Code (Java) — Lightweight Circuit Breaker with Timeouts & Slow-Call Trip

Features:

-   Rolling window with **error rate** and **slow-call rate**.
    
-   States: Closed → Open → Half-Open.
    
-   **Per-key scope** (e.g., tenant or API key).
    
-   **Timeout** on the protected call.
    
-   Pluggable **fallback**.
    

> Dependencies: none (JDK 17+). Replace with Resilience4j for production features.

```java
package com.example.security.cb;

import java.time.Clock;
import java.time.Duration;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Function;
import java.util.function.Supplier;

public class CircuitBreaker {

  public enum State { CLOSED, OPEN, HALF_OPEN }

  public static final class Config {
    public Duration callTimeout = Duration.ofMillis(800);
    public Duration window = Duration.ofSeconds(30);
    public int windowBuckets = 10;
    public double maxErrorRate = 0.5;           // 50%
    public double maxSlowRate = 0.5;            // 50%
    public Duration slowCallThreshold = Duration.ofMillis(500);
    public Duration openCooldown = Duration.ofSeconds(10);
    public int halfOpenMaxProbes = 5;
  }

  private final Config cfg;
  private final Clock clock;
  private volatile State state = State.CLOSED;
  private volatile long openedAt = 0L;
  private final AtomicInteger halfOpenProbesLeft = new AtomicInteger();
  private final ExecutorService timeoutPool = Executors.newCachedThreadPool();
  private final Bucket[] buckets;
  private volatile int idx = 0;
  private volatile long bucketStart;
  private final Object lock = new Object();

  private static final class Bucket {
    volatile int total, errors, slow;
    void reset() { total=errors=slow=0; }
  }

  public CircuitBreaker(Config cfg) {
    this(cfg, Clock.systemUTC());
  }
  public CircuitBreaker(Config cfg, Clock clock) {
    this.cfg = cfg; this.clock = clock;
    this.buckets = new Bucket[cfg.windowBuckets];
    for (int i=0;i<buckets.length;i++) buckets[i]=new Bucket();
    this.bucketStart = clock.millis();
  }

  /** Execute protected call with optional fallback. */
  public <T> T execute(Supplier<T> call, Supplier<T> fallback) {
    long now = clock.millis();
    rotateBucketsIfNeeded(now);

    // Fast-path decision
    if (state == State.OPEN) {
      if (now - openedAt < cfg.openCooldown.toMillis()) {
        return fallback != null ? fallback.get() : failFast();
      } else {
        transitionToHalfOpen();
      }
    }
    if (state == State.HALF_OPEN) {
      if (halfOpenProbesLeft.get() <= 0) {
        return fallback != null ? fallback.get() : failFast();
      }
    }

    // Try the call with timeout
    long start = now;
    boolean success = false;
    boolean slow = false;
    try {
      T result = callWithTimeout(call, cfg.callTimeout);
      success = true;
      slow = (clock.millis() - start) > cfg.slowCallThreshold.toMillis();
      onResult(success, slow);
      return result;
    } catch (Exception e) {
      onResult(false, false);
      if (fallback != null) return fallback.get();
      throw new RuntimeException("circuit-breaker: call failed", e);
    }
  }

  private <T> T callWithTimeout(Supplier<T> call, Duration timeout) throws Exception {
    Future<T> f = timeoutPool.submit(call::get);
    try {
      return f.get(timeout.toMillis(), TimeUnit.MILLISECONDS);
    } catch (TimeoutException te) {
      f.cancel(true);
      throw te;
    }
  }

  private void onResult(boolean ok, boolean slow) {
    Bucket b = buckets[idx];
    synchronized (lock) {
      b.total++;
      if (!ok) b.errors++;
      if (slow) b.slow++;
    }

    if (state == State.HALF_OPEN) {
      if (!ok || isTripConditionMet()) {
        transitionToOpen();
      } else if (halfOpenProbesLeft.decrementAndGet() <= 0) {
        transitionToClosed();
      }
      return;
    }

    if (!ok || slow) {
      if (isTripConditionMet()) transitionToOpen();
    }
  }

  private boolean isTripConditionMet() {
    int tot=0, err=0, slw=0;
    synchronized (lock) {
      for (Bucket b : buckets) { tot+=b.total; err+=b.errors; slw+=b.slow; }
    }
    if (tot == 0) return false;
    double er = err / (double) tot;
    double sr = slw / (double) tot;
    return er >= cfg.maxErrorRate || sr >= cfg.maxSlowRate;
  }

  private void rotateBucketsIfNeeded(long now) {
    long bucketLen = cfg.window.toMillis() / cfg.windowBuckets;
    synchronized (lock) {
      while (now - bucketStart >= bucketLen) {
        idx = (idx + 1) % buckets.length;
        buckets[idx].reset();
        bucketStart += bucketLen;
      }
    }
  }

  private void transitionToOpen() {
    state = State.OPEN;
    openedAt = clock.millis();
  }
  private void transitionToHalfOpen() {
    state = State.HALF_OPEN;
    halfOpenProbesLeft.set(cfg.halfOpenMaxProbes);
  }
  private void transitionToClosed() {
    state = State.CLOSED;
    for (Bucket b : buckets) b.reset();
  }

  public State state() { return state; }

  private static <T> T failFast() {
    throw new RuntimeException("circuit-breaker: open");
  }

  // --------- Per-key (tenant) registry helper ---------
  public static final class Registry {
    private final Map<String, CircuitBreaker> byKey = new ConcurrentHashMap<>();
    private final Config cfg;
    public Registry(Config cfg) { this.cfg = cfg; }
    public CircuitBreaker forKey(String key) {
      return byKey.computeIfAbsent(key, k -> new CircuitBreaker(cfg));
    }
  }
}
```

**Usage example**

```java
// Example usage (e.g., inside a service class)
var cfg = new CircuitBreaker.Config();
cfg.maxErrorRate = 0.4;           // trip if >= 40% errors
cfg.maxSlowRate  = 0.5;           // or >= 50% slow calls
cfg.openCooldown = Duration.ofSeconds(15);
cfg.callTimeout  = Duration.ofMillis(700);

var registry = new CircuitBreaker.Registry(cfg);

// Suppose we scope by tenant
String tenant = "tenantA";
CircuitBreaker cb = registry.forKey(tenant);

String data = cb.execute(
    () -> httpGet("https://api.example.com/expensive"),     // protected call
    () -> "{ \"status\": \"degraded\" }"                     // safe fallback
);
```

---

## Known Uses

-   **API gateways / WAFs:** break on upstream saturation; return controlled 5xx/503 with retry-after.
    
-   **Microservices:** per-endpoint breakers backed by **Resilience4j**/Envoy outlier detection.
    
-   **Payment & identity providers:** fast-fail during third-party brownouts to preserve checkout/auth capacity.
    
-   **Multi-tenant SaaS:** **per-tenant breakers** to isolate abusive or buggy tenants.
    
-   **Data pipelines:** break on sink timeouts to trigger buffering/queueing instead of blocking producers.
    

---

## Related Patterns

-   **Timeouts & Retry with Backoff:** define budgets; the breaker reacts to their outcomes.
    
-   **Bulkhead / Thread-Pool Isolation:** limit concurrency to failing dependencies.
    
-   **Rate Limiting / Throttling:** proactive control; combine with breakers for reactive control.
    
-   **Health Check & Outlier Ejection:** feed breaker signals and remove bad instances.
    
-   **Fallback / Graceful Degradation:** what you return when the breaker is open.
    
-   **Idempotent Receiver / Sagas:** safe recovery when retries occur.
    

---

## Implementation Checklist

-   Choose **trip criteria** (error rate, slow-call rate, consecutive failures) and **windows**.
    
-   Pair with **timeouts** and **retry budgets** (never infinite retries).
    
-   Select **scope** (global, per endpoint, per tenant) and enforce **isolation**.
    
-   Define **fallbacks** that are **authorized** and data-classification safe.
    
-   Emit **state-change events** with reasons; add **alerts** on frequent trips.
    
-   Provide **manual overrides** (force open/close) for operators.
    
-   Validate behavior with **failure injection** (latency/error) and **game days**.
    
-   Document client behavior (e.g., `Retry-After`) and user messaging during Open state.

