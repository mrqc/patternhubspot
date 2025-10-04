# Throttling — Resilience & Fault Tolerance Pattern

## Pattern Name and Classification

**Name:** Throttling  
**Classification:** Resilience / Fault Tolerance / Load-Shedding & Flow Control (Client- and Server-Side)

---

## Intent

Control the **rate and/or concurrency** of requests so that systems **stay within safe capacity**, avoiding overload, cascading failures, and tail latency explosions—while communicating back-pressure to callers.

---

## Also Known As

-   Rate Limiting
    
-   Load Shedding
    
-   Flow Control
    
-   Back-Pressure
    
-   Concurrency Limiter
    

---

## Motivation (Forces)

-   **Unbounded demand** vs **bounded capacity** (CPU, DB connections, queues).
    
-   **Bursty traffic** (retries, spikes, bots) can push latency into timeouts and trip breakers.
    
-   **Fairness** across tenants/APIs/endpoints is needed; the “noisy neighbor” must not dominate.
    
-   **Cost control**—limit expensive operations and external calls.
    
-   **Self-protection** during incidents or deployments.
    
-   **Predictability**: keeping systems within their **operating envelope** yields stable p95/p99.
    

---

## Applicability

Use Throttling when:

-   A service (or dependency) shows **degraded performance** under high QPS/concurrency.
    
-   You expose public APIs and need **per-tenant** fairness.
    
-   You depend on third-party APIs with strict quotas.
    
-   You run **autoscaling** but need a guardrail while scale-out catches up.
    

Avoid when:

-   The operation is already **queue-based** with strict capacity and acceptable waiting policy.
    
-   End-to-end **latency SLOs** are tighter than any meaningful wait or retry budget.
    

---

## Structure

-   **Policy:** limits by **rate** (permits/sec), **burst** (bucket capacity), and/or **concurrency** (in-flight caps).
    
-   **Keying strategy:** global, per-endpoint, per-tenant, per-token, per-IP.
    
-   **Algorithm:** Token Bucket, Leaky Bucket, Fixed/Sliding Window, AIMD Concurrency Limiter.
    
-   **Metering:** counters, moving windows, EWMA.
    
-   **Decision:** allow, delay (for a bounded time), or reject.
    
-   **Signaling:** status codes/headers (e.g., `429 Too Many Requests`, `Retry-After`, `RateLimit-*`).
    
-   **Observation:** metrics (grants/denies/queue length), logs, traces.
    

---

## Participants

-   **Throttler** (rate/concurrency limiter)
    
-   **Classifier/Key Extractor** (maps request → limit key)
    
-   **Clock/Scheduler** (for refill and optional wait)
    
-   **Caller** (client library or upstream service)
    
-   **Policy Store** (static config or dynamic from control plane)
    
-   **Observer** (metrics/alerting dashboards)
    

---

## Collaboration

1.  **Request arrives** → Key is computed (e.g., `tenantId:endpoint`).
    
2.  **Throttler** checks permits or concurrent slots.
    
3.  If **available**, admit and decrement permits; else either **queue briefly** or **reject** with back-pressure signal.
    
4.  **Refill** happens over time (rate) or upon completion (concurrency).
    
5.  **Metrics** emitted for grants, waits, rejects; clients can adapt (backoff, jitter).
    

---

## Consequences

**Benefits**

-   Protects services from overload; stabilizes tail latency and error rates.
    
-   Enables **fairness** and multi-tenant isolation.
    
-   Clear contract to clients via **back-pressure signaling**.
    

**Liabilities**

-   **Request drops** (expected) under pressure.
    
-   Poor keying or limits can cause **starvation** or under-utilization.
    
-   **Distributed counters** (e.g., Redis) add latency and failure modes.
    
-   If clients ignore signals, retries can still cause storms—pair with retry/backoff policies.
    

---

## Implementation

### Key Decisions

-   **What to limit:** rate (QPS), concurrency (in-flight), or both.
    
-   **Where to enforce:** client, gateway/edge, service ingress, or per-dependency egress.
    
-   **Algorithm:**
    
    -   **Token Bucket:** burst-friendly QPS cap (great default).
        
    -   **Leaky Bucket:** smooths bursts to steady drain.
        
    -   **Fixed/Sliding Window:** simpler accounting, more variance.
        
    -   **Concurrency Limiter (AIMD):** adapts concurrent requests to latency/errs.
        
-   **Policy granularity:** global vs per-tenant/per-endpoint.
    
-   **Action on exceed:** reject (429), or **bounded wait** (e.g., ≤100ms), never unbounded.
    
-   **Headers:** return `Retry-After` and `RateLimit-Limit/Remaining/Reset` (or equivalent) for transparency.
    
-   **Storage:** in-proc (single node), **Redis** for distributed, or provider features (API gateway, service mesh).
    
-   **Observability:** export metrics and percentiles; alert on sustained rejects.
    

### Anti-Patterns

-   Sleeping **synchronously** on servlet threads for long waits → thread starvation.
    
-   Global single bucket for all tenants → **noisy neighbor** issues.
    
-   Missing jitter/backoff client-side → retry storms.
    
-   “Silent throttling” (no headers/status) → poor client adaptation.
    
-   Per-node in-memory only when you need **cluster-wide** limits.
    

---

## Sample Code (Java)

### A) Server-Side Token Bucket (Spring Boot Servlet Filter, per-API-key)

*In-memory single-node demo; swap the bucket map to a distributed store (e.g., Redis) for cluster limits.*

```java
// build.gradle (snip)
// implementation 'org.springframework.boot:spring-boot-starter-web'

package com.example.throttle;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.time.Instant;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ThreadLocalRandom;

@Component
public class ThrottlingFilter extends OncePerRequestFilter {

  private final Map<String, TokenBucket> buckets = new ConcurrentHashMap<>();

  // Example static policy; in prod load from config/control plane
  private final int defaultRps = 50;         // permits per second
  private final int defaultBurst = 100;      // bucket capacity

  @Override
  protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain)
      throws ServletException, IOException {

    String apiKey = req.getHeader("X-Api-Key");
    String path = req.getRequestURI();
    String key = (apiKey != null ? apiKey : "anon") + ":" + path; // per-tenant+endpoint

    TokenBucket bucket = buckets.computeIfAbsent(key,
        k -> new TokenBucket(defaultRps, defaultBurst));

    if (bucket.tryConsume(1)) {
      chain.doFilter(req, res);
      return;
    }

    // Throttled: respond with back-pressure signals
    res.setStatus(HttpStatus.TOO_MANY_REQUESTS.value()); // 429
    long resetMs = bucket.millisUntilNextToken();
    res.setHeader("Retry-After", String.valueOf(Math.max(1, resetMs / 1000))); // seconds
    res.setHeader("RateLimit-Limit", String.valueOf(defaultRps));
    res.setHeader("RateLimit-Remaining", String.valueOf(bucket.estimatedRemaining()));
    res.setHeader("RateLimit-Reset", String.valueOf(Instant.now().toEpochMilli() + resetMs));
    res.getWriter().write("{\"error\":\"throttled\"}");
  }

  /** Simple token bucket with monotonic nanos clock. */
  static final class TokenBucket {
    private final long capacity;
    private final double refillPerNanos; // tokens per nanosecond
    private double tokens;
    private long lastRefillNanos;

    TokenBucket(int ratePerSec, int burstCapacity) {
      this.capacity = burstCapacity;
      this.refillPerNanos = ratePerSec / 1_000_000_000.0;
      this.tokens = burstCapacity;
      this.lastRefillNanos = System.nanoTime();
    }

    synchronized boolean tryConsume(int permits) {
      refill();
      if (tokens >= permits) {
        tokens -= permits;
        return true;
      }
      return false;
    }

    synchronized long millisUntilNextToken() {
      refill();
      if (tokens >= 1.0) return 0;
      double deficit = 1.0 - tokens;
      long nanos = (long) Math.ceil(deficit / refillPerNanos);
      return Math.max(1, nanos / 1_000_000);
    }

    synchronized int estimatedRemaining() {
      refill();
      return (int) Math.floor(tokens);
    }

    private void refill() {
      long now = System.nanoTime();
      long delta = now - lastRefillNanos;
      if (delta <= 0) return;
      tokens = Math.min(capacity, tokens + delta * refillPerNanos);
      lastRefillNanos = now;
    }
  }
}
```

**Notes**

-   This filter rejects immediately when empty. If you prefer a **tiny wait**, use non-blocking async APIs (e.g., WebFlux) and cap wait ≤ 100 ms.
    
-   For **cluster-wide** limits, keep counters in **Redis** (e.g., Lua script implementing token bucket atomically).
    

---

### B) Client-Side Throttling for an Outbound Dependency (Resilience4j)

```java
// build.gradle (snip)
// implementation 'io.github.resilience4j:resilience4j-ratelimiter:2.2.0'
// implementation 'io.github.resilience4j:resilience4j-timelimiter:2.2.0'

import io.github.resilience4j.ratelimiter.*;
import io.github.resilience4j.timelimiter.*;
import java.time.Duration;
import java.util.concurrent.*;

public class OutboundClient {

  private final RateLimiter limiter;
  private final TimeLimiter timeLimiter;

  public OutboundClient() {
    RateLimiterConfig cfg = RateLimiterConfig.custom()
        .limitRefreshPeriod(Duration.ofSeconds(1))
        .limitForPeriod(100)        // 100 requests/sec
        .timeoutDuration(Duration.ofMillis(50)) // wait up to 50ms for a permit
        .build();
    limiter = RateLimiter.of("downstream-api", cfg);

    timeLimiter = TimeLimiter.of(Duration.ofSeconds(2)); // per-call deadline
  }

  public String get(Supplier<String> httpCall) throws Exception {
    Callable<String> guarded =
        TimeLimiter.decorateFutureSupplier(timeLimiter, () -> CompletableFuture.supplyAsync(httpCall));
    Callable<String> withRateLimit = RateLimiter.decorateCallable(limiter, guarded);
    try {
      return withRateLimit.call();
    } catch (RequestNotPermitted e) {
      // Local throttling: map to retry/backoff or surface 429 upstream
      throw e;
    }
  }
}
```

---

### C) Adaptive Concurrency Limiter (AIMD) Sketch

Caps **in-flight** requests instead of rate; adjusts limit based on observed latency/errors.

```java
public final class AimdConcurrencyLimiter {
  private volatile int limit = 50;   // start
  private final int max = 500, min = 1;
  private volatile int inFlight = 0;

  public synchronized boolean tryAcquire() {
    if (inFlight >= limit) return false;
    inFlight++;
    return true;
  }

  public synchronized void onComplete(boolean success, long latencyMillis) {
    inFlight--;
    if (!success || latencyMillis > 500) {
      // multiplicative decrease on error or high latency
      limit = Math.max(min, (int) Math.floor(limit * 0.7));
    } else {
      // additive increase
      limit = Math.min(max, limit + 1);
    }
  }
}
```

Attach to a servlet filter or client wrapper; admit only when `tryAcquire()` succeeds; call `onComplete()` after response to adapt.

---

## Known Uses

-   **API Gateways / CDNs** (NGINX/Envoy/Istio) with per-route and per-client rate limits.
    
-   **Cloud SDKs** throttle outbound calls to provider APIs to respect quotas.
    
-   **Payment/Email/SMS** providers enforce per-merchant limits to prevent abuse.
    
-   **Databases / Pools**: max connections / max in-flight queries act as concurrency throttles.
    
-   **Search/Recommendation** systems cap QPS to model services to stabilize p99.
    

---

## Related Patterns

-   **Retry with Exponential Backoff:** Works in tandem; throttling signals when to back off.
    
-   **Circuit Breaker:** When downstream is failing, shed load quickly.
    
-   **Bulkhead:** Partition capacity per tenant/pool to limit blast radius.
    
-   **Queue-Based Load Leveling:** Buffer work when latency SLO allows.
    
-   **Shedder / Priority Load Shedding:** Drop low-priority traffic first during overload.
    
-   **Token Bucket / Leaky Bucket (Algorithms):** Concrete throttling strategies.
    

---

## Implementation Checklist

-   Choose **keying** (tenant, endpoint) and **policy** (rate, burst, concurrency).
    
-   Decide **action** on exceed (reject vs short wait) and **signals** (429 + headers).
    
-   Place throttlers at **egress** (protect dependencies) and/or **ingress** (protect self).
    
-   For distributed enforcement, use **atomic** centralized counters (Redis/Lua) or gateway features.
    
-   Integrate with **retry/backoff** and **timeouts**; never allow unbounded waiting.
    
-   Instrument **grants/denies/latency**; alert on sustained high deny rates.
    
-   Validate under **load tests** and chaos (retry storms, tenant bursts).

