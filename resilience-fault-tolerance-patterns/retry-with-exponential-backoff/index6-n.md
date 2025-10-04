# Retry With Exponential Backoff — Resilience & Fault Tolerance Pattern

## Pattern Name and Classification

**Name:** Retry With Exponential Backoff  
**Classification:** Resilience / Fault Tolerance / Latency Control (Client-Side)

---

## Intent

Automatically re-attempt a failed operation using **increasing wait intervals** between attempts to reduce load, avoid thundering herds, and give transient faults time to clear—while **bounding total time** and **preserving correctness**.

---

## Also Known As

-   Exponential Retry
    
-   Backoff + Jitter
    
-   Progressive Retry
    
-   Exponential Delay
    

---

## Motivation (Forces)

-   **Transient failures** (timeouts, 5xx, connection resets, rate limits) often succeed shortly after.
    
-   **Immediate retries** amplify load spikes and contention.
    
-   **Coordinated clients** retrying at fixed steps can synchronize, causing bursts (**correlated retries**).
    
-   **User-facing latency** must be bounded—retries shouldn’t wait “forever.”
    
-   **Idempotency** of operations matters; repeated side effects can be harmful if not safe.
    
-   **Budgeting** is needed so retries don’t starve other work.
    

---

## Applicability

Use when:

-   Failures are **likely transient** (network, ephemeral dependency overload, leader re-elections).
    
-   The called operation is **idempotent** or made safe via **Idempotency Keys**.
    
-   The dependency **signals overload** (HTTP 429) or **retryable** errors (HTTP 503, gRPC UNAVAILABLE).
    
-   You can tolerate **increased latency** up to a bounded maximum.
    

Avoid when:

-   Operations are **non-idempotent** and cannot be guarded.
    
-   Errors are **permanent** (4xx like 400/404/401) or semantic failures.
    
-   Deadlines are so tight that retry cannot help.
    

---

## Structure

-   **Retry Policy:** max attempts, base delay, multiplier, max/backoff cap, jitter type, retryable error list, overall deadline.
    
-   **Timer/Scheduler:** sleeps between attempts (non-blocking if async).
    
-   **Error Classifier:** maps errors/status to retry/abort.
    
-   **Jitter:** randomization around the backoff to avoid synchronization.
    
-   **Metrics:** attempts, success-after-retry, aborted, total time.
    

---

## Participants

-   **Caller/Client:** wraps the operation with the retry policy.
    
-   **Operation:** the function/HTTP call/DB query to re-attempt.
    
-   **Policy Engine:** computes next delay and stop conditions.
    
-   **Clock/Scheduler:** executes waits; may be virtual in tests.
    
-   **Observability:** logs/metrics/tracing for retry spans.
    

---

## Collaboration

1.  Caller invokes operation with **attempt = 1**.
    
2.  On **retryable failure**, compute next delay:
    
    -   `delay = min(cap, base * multiplier^(attempt-1))`
        
    -   apply **jitter** (e.g., full or decorrelated).
        
3.  Sleep/await the delay (respect **deadline**).
    
4.  Re-invoke until success or **stop condition** (max attempts/budget/deadline).
    
5.  Emit metrics and propagate the terminal outcome.
    

---

## Consequences

**Benefits**

-   Smooths load; reduces **retry storms**.
    
-   Improves success rate under transient faults.
    
-   Easy to reason about and implement; widely supported by libraries.
    

**Liabilities**

-   Adds latency; can violate **SLOs** if budgets/deadlines are weak.
    
-   If operation isn’t idempotent, can cause **duplicate side effects**.
    
-   Poor error classification → **retrying the unretryable** (wasted time/cost).
    
-   Misconfigured backoff (too aggressive) can still overload dependencies.
    

---

## Implementation

### Key Decisions

-   **Error classification:** Only retry on transient signals (e.g., network I/O exceptions, HTTP 429/503, gRPC `UNAVAILABLE`, `DEADLINE_EXCEEDED` with remaining budget).
    
-   **Backoff function:**
    
    -   Exponential with **multiplier** 1.5–2.0; **base** 50–200 ms; **cap** 2–10 s typical.
        
-   **Jitter:**
    
    -   **Full jitter:** `sleep = rand(0, backoff)` (good default).
        
    -   **Decorrelated jitter:** `sleep = min(cap, rand(base, prev*3))` (AWS “stable” backoff).
        
-   **Budgets:**
    
    -   **Max attempts** (e.g., 5) **and** an **overall deadline** (e.g., 2–5 s client-side).
        
    -   Optionally a **retry budget rate** (percentage of successful requests allowed for retries).
        
-   **Idempotency:**
    
    -   Guard side effects (idempotency keys) or make operation naturally safe.
        
-   **Circuit breaker integration:**
    
    -   Short-circuit when dependency is open/failing fast.
        
-   **Observability:**
    
    -   Tag spans with attempt count, delay, reason, and final outcome.
        

### Anti-Patterns

-   Retrying **synchronously** on the hot request path with huge sleeps → thread starvation.
    
-   Retrying on **client errors** (e.g., 400/401/403/404).
    
-   **No jitter** → synchronized herd effects.
    
-   Ignoring **call deadlines** and **cancellation** signals.
    
-   Exponential backoff **without a cap** → unbounded waits.
    

---

## Sample Code (Java)

### A) Plain Java (sync) with Full Jitter and Deadline

```java
import java.time.Duration;
import java.time.Instant;
import java.util.Random;
import java.util.function.Supplier;

public class ExponentialBackoffRetry {

  public static class Policy {
    public final int maxAttempts;
    public final Duration baseDelay;
    public final double multiplier;
    public final Duration maxDelay;
    public final Duration overallDeadline;

    public Policy(int maxAttempts, Duration baseDelay, double multiplier,
                  Duration maxDelay, Duration overallDeadline) {
      this.maxAttempts = maxAttempts;
      this.baseDelay = baseDelay;
      this.multiplier = multiplier;
      this.maxDelay = maxDelay;
      this.overallDeadline = overallDeadline;
    }
  }

  private static final Random RNG = new Random();

  public static <T> T callWithRetry(Supplier<T> op, Policy p, RetryableClassifier classifier) throws Exception {
    Instant deadline = Instant.now().plus(p.overallDeadline);
    long backoffMs = p.baseDelay.toMillis();
    Exception last = null;

    for (int attempt = 1; attempt <= p.maxAttempts; attempt++) {
      try {
        return op.get();
      } catch (Exception e) {
        last = e;
        if (!classifier.isRetryable(e)) break;

        // compute backoff with cap
        backoffMs = Math.min((long)(backoffMs * (attempt == 1 ? 1 : p.multiplier)), p.maxDelay.toMillis());
        // full jitter
        long sleep = RNG.nextLong(backoffMs + 1);
        long remaining = Duration.between(Instant.now(), deadline).toMillis();

        if (remaining <= 0 || sleep > remaining) {
          break; // deadline exceeded
        }
        try {
          Thread.sleep(sleep);
        } catch (InterruptedException ie) {
          Thread.currentThread().interrupt();
          throw ie;
        }
      }
    }
    throw last != null ? last : new RuntimeException("retry failed without throwable");
  }

  @FunctionalInterface
  public interface RetryableClassifier {
    boolean isRetryable(Exception e);
  }
}
```

**Usage:**

```java
var policy = new ExponentialBackoffRetry.Policy(
    5, Duration.ofMillis(100), 2.0, Duration.ofSeconds(2), Duration.ofSeconds(5));

String result = ExponentialBackoffRetry.callWithRetry(
    () -> httpClient.get("https://api.example.com/resource"), 
    policy,
    ex -> isTransient(ex) // implement: timeouts, connection reset, 429/503 mapped to exceptions
);
```

### B) Resilience4j (recommended) — Exponential Backoff + Jitter + Circuit Breaker

```java
// build.gradle
// implementation 'io.github.resilience4j:resilience4j-retry:2.2.0'
// implementation 'io.github.resilience4j:resilience4j-circuitbreaker:2.2.0'

import io.github.resilience4j.retry.*;
import io.github.resilience4j.circuitbreaker.*;
import java.time.Duration;
import java.util.concurrent.ThreadLocalRandom;
import java.util.function.Supplier;

public class R4JExample {
  public static <T> T callWithPolicies(Supplier<T> op) {
    CircuitBreaker cb = CircuitBreaker.ofDefaults("downstream");

    IntervalFunction backoffWithJitter = IntervalFunction
        .ofExponentialBackoff(100, 2.0)           // base=100ms, multiplier=2
        .withJitter(0.5);                          // ±50% jitter

    RetryConfig retryConfig = RetryConfig.<Object>custom()
        .maxAttempts(5)
        .intervalFunction(backoffWithJitter)
        .retryOnException(R4JExample::isRetryable)
        .failAfterMaxAttempts(true)
        .build();

    Retry retry = Retry.of("downstream-retry", retryConfig);

    Supplier<T> guarded = CircuitBreaker
        .decorateSupplier(cb, op);
    guarded = Retry.decorateSupplier(retry, guarded);

    return guarded.get();
  }

  private static boolean isRetryable(Throwable t) {
    // Map your HTTP/gRPC errors and IOExceptions here
    return t instanceof java.io.IOException
        || t.getMessage() != null && t.getMessage().contains("HTTP_503")
        || t.getMessage() != null && t.getMessage().contains("HTTP_429");
  }
}
```

### C) Spring Retry (annotation style)

```java
// build.gradle
// implementation 'org.springframework.retry:spring-retry:2.0.8'
// implementation 'org.springframework:spring-aspects:6.1.12'

import org.springframework.retry.annotation.Backoff;
import org.springframework.retry.annotation.Retryable;
import org.springframework.stereotype.Service;

@Service
public class ExternalClient {

  @Retryable(
    include = {java.net.SocketTimeoutException.class, java.io.IOException.class},
    maxAttempts = 5,
    backoff = @Backoff(delay = 100, multiplier = 2.0, maxDelay = 2000, random = true)
  )
  public String fetch() throws Exception {
    // do HTTP call; throw IOException/Timeout on failure
    return "...";
  }
}
```

**Notes for all samples**

-   Always combine with **timeouts** on the operation itself and pass a **deadline/cancellation** signal downstream.
    
-   Use **async/non-blocking** backoff on reactive paths to avoid thread blocking.
    
-   Record **attempt count** and **wait time** in logs/traces for debugging.
    

---

## Known Uses

-   **AWS SDKs**, **Google Cloud client libraries**, **Kubernetes** clients: all employ backoff with jitter.
    
-   **HTTP APIs** that return **429 Too Many Requests** or **503 Service Unavailable** with `Retry-After`.
    
-   **Message producers/consumers** reconnect loops to brokers (Kafka, RabbitMQ, NATS).
    
-   **DB connection pools** retrying transient connection establishment.
    

---

## Related Patterns

-   **Timeouts and Budgets:** Bound each attempt and the overall call.
    
-   **Circuit Breaker:** Prevents retries into a black hole; opens during brownouts.
    
-   **Bulkhead:** Limits concurrent retries so they don’t exhaust resources.
    
-   **Idempotent Receiver / Idempotency Keys:** Safeguards side effects when retries happen.
    
-   **Rate Limiting / Token Bucket:** Coordinates client load; complements server signals.
    
-   **Dead Letter / Compensation:** When retries exhaust, escalate or trigger compensating action.
    

---

## Implementation Checklist

-   Define **retryable vs non-retryable** conditions explicitly.
    
-   Choose **base delay**, **multiplier**, **cap**, and **jitter**; verify with load tests.
    
-   Enforce **max attempts** and an **overall deadline** (cancel on timeout).
    
-   Ensure **idempotency** or guard with keys to avoid duplicate side effects.
    
-   Instrument **metrics** (retry count, success-after-retry, abandon rate).
    
-   Integrate with **circuit breaker** and **bulkheads** to protect the system.
    
-   Validate behavior under chaos: packet loss, latency injection, and dependency overload.

