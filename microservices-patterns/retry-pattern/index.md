# Retry — Microservice Pattern

## Pattern Name and Classification

-   **Name:** Retry
    
-   **Classification:** Resilience & Fault-Tolerance Pattern for Microservices (client-side & consumer-side)
    

## Intent

Automatically **re-attempt a failed operation** under controlled policies (limits, backoff, jitter, classification) to mask transient faults **without** overwhelming dependencies or breaking correctness.

## Also Known As

-   Exponential Backoff (with Jitter)
    
-   Bounded Retries / Redelivery
    
-   Client-side Retries
    

## Motivation (Forces)

-   **Transient failures happen:** timeouts, 5xx, connection resets, throttling (429), leader elections, cold caches.
    
-   **Availability vs. Safety:** Retrying can hide flakiness, but **duplicates** and **retry storms** can harm idempotency and SLOs.
    
-   **Latency budgets:** More attempts raise tail latency; cap attempts and use deadlines.
    
-   **Fairness:** Herding on the same schedule causes synchronized traffic spikes; **jitter** randomizes backoff.
    
-   **Backpressure:** Combine with circuit breakers to stop hammering a sick dependency.
    

## Applicability

Use when:

-   Failures are often **transient** and **idempotent** or can be made idempotent (tokens, dedup).
    
-   You can **bound retries** with time/attempt budgets.
    
-   The callee provides **Retry-After** hints or is tolerant to duplicates.
    

Avoid or constrain when:

-   Operations are **non-idempotent** (e.g., charge card) without an **idempotency key**.
    
-   The dependency is already overloaded (retry might worsen an outage).
    
-   Calls are **long-running**; prefer async workflow (queue + DLQ) instead of synchronous retries.
    

## Structure

```scss
Caller → Retry Policy → Attempt Executor → (Timeout) → Dependency
                 ▲            │
                 │            └─► Classify outcome (retryable / not)
                 └─ Backoff + Jitter (bounded), Budget (attempts/deadline)
        [Circuit Breaker guards the whole call]
```

## Participants

-   **Caller/Client:** Initiates operation; owns latency budget.
    
-   **Retry Policy:** Max attempts, backoff strategy, jitter, deadline, retriable classifiers.
    
-   **Backoff/Jitter:** Exponential/linear with randomization to avoid sync.
    
-   **Classifier:** Maps exceptions/status codes to retryable/non-retryable.
    
-   **Circuit Breaker:** Trips open on sustained failures to prevent storms.
    
-   **Idempotency Manager:** Keys/semantics to deduplicate effects.
    
-   **Telemetry:** Emits metrics (attempts, outcome), logs, and tracing attributes.
    

## Collaboration

1.  Caller starts with a **deadline** and creates attempt 1.
    
2.  Outcome is **classified**. If success or non-retryable → return.
    
3.  If retryable and budget remains → **sleep(backoff+jitter)**; else → give up.
    
4.  Circuit breaker observes failures; if **open**, short-circuit quickly.
    
5.  Each attempt is **timed** (per-try timeout) and **traced** with `retry.attempt`.
    

## Consequences

**Benefits**

-   Hides transient blips; improves request success rate and perceived availability.
    
-   With jitter, reduces **thundering herds**.
    
-   Combined with CB/timeout, yields stable failure modes.
    

**Liabilities**

-   Increases latency and **cost**; misconfigured retries cause **retry storms**.
    
-   Requires **idempotency** to avoid duplicate side effects.
    
-   Complex heuristics (which errors to retry, how long) need tuning & observability.
    

## Implementation

1.  **Time bounds first:** set **overall deadline** and **per-attempt timeout**; never infinite retries.
    
2.  **Classify retryable outcomes:** typically `408/429/5xx`, `IOException`, `SocketTimeoutException`, connection resets; ignore `4xx` like `400/401/403/404`.
    
3.  **Backoff with jitter:**
    
    -   **Exponential + full jitter:** `sleep = random(0, min(cap, base * 2^n))`.
        
    -   Respect **Retry-After** when present.
        
4.  **Limit attempts:** e.g., 3–5 tries, or **retry budget** (e.g., ≤ 30% extra requests per second).
    
5.  **Idempotency:** for non-idempotent operations, use **Idempotency-Key** and dedup store server-side.
    
6.  **Guard with Circuit Breaker:** stop retries when downstream is known unhealthy.
    
7.  **Telemetry:** counters (retries, successes), histograms (backoff delay), traces (`retry.attempt`, `retry.last`).
    
8.  **Async consumers:** prefer broker redelivery policies with backoff and **DLQ** after N attempts.
    
9.  **Testing:** chaos inject timeouts; verify caps, CB interplay, and idempotency.
    

---

## Sample Code (Java) — Minimal, Library-Free Retry Utility + HTTP Example

> Implements **bounded exponential backoff with full jitter**, deadline, classification, and **Retry-After** support. Shows adding an **Idempotency-Key** for safe retries.

### Retry Utility

```java
package retry.pattern;

import java.net.http.HttpHeaders;
import java.time.*;
import java.util.Objects;
import java.util.Optional;
import java.util.concurrent.Callable;
import java.util.concurrent.ThreadLocalRandom;
import java.util.function.Predicate;

public class Retryer {

  public record Config(
      int maxAttempts,
      Duration baseDelay,
      Duration maxDelay,
      double multiplier,
      Duration deadline,
      Predicate<Throwable> retryOnThrowable,
      Predicate<Integer> retryOnStatus // HTTP-only convenience (nullable)
  ) {
    public Config {
      Objects.requireNonNull(baseDelay); Objects.requireNonNull(maxDelay);
      Objects.requireNonNull(deadline); Objects.requireNonNull(retryOnThrowable);
      if (maxAttempts < 1) throw new IllegalArgumentException("maxAttempts >= 1");
      if (multiplier < 1.0) throw new IllegalArgumentException("multiplier >= 1.0");
    }
  }

  private final Config cfg;
  public Retryer(Config cfg) { this.cfg = cfg; }

  public <T> T call(Callable<T> op) throws Exception {
    Instant endsAt = Instant.now().plus(cfg.deadline());
    int attempt = 1;
    Throwable last = null;

    while (true) {
      try {
        return op.call();
      } catch (Throwable t) {
        last = t;
        if (!cfg.retryOnThrowable().test(t)) throw t instanceof Exception ? (Exception) t : new RuntimeException(t);
        if (attempt >= cfg.maxAttempts() || Instant.now().isAfter(endsAt)) {
          throw t instanceof Exception ? (Exception) t : new RuntimeException(t);
        }
        Duration sleep = nextBackoff(attempt);
        sleep = remainingOrZero(sleep, endsAt);
        if (!sleep.isZero() && !sleep.isNegative()) Thread.sleep(sleep.toMillis());
        attempt++;
      }
    }
  }

  /** Exponential backoff with FULL JITTER: random(0, min(cap, base * 2^n)). */
  private Duration nextBackoff(int attempt) {
    long base = cfg.baseDelay().toMillis();
    long cap = cfg.maxDelay().toMillis();
    double exp = Math.pow(cfg.multiplier(), attempt - 1);
    long max = Math.min(cap, (long) (base * exp));
    long jitter = ThreadLocalRandom.current().nextLong(0, Math.max(1, max + 1));
    return Duration.ofMillis(jitter);
  }

  private static Duration remainingOrZero(Duration want, Instant endsAt) {
    long msLeft = Duration.between(Instant.now(), endsAt).toMillis();
    return Duration.ofMillis(Math.max(0, Math.min(msLeft, want.toMillis())));
  }

  /** Helper to honor Retry-After if the exception exposes headers (optional). */
  public static Optional<Duration> retryAfter(HttpHeaders headers, Clock clock) {
    if (headers == null) return Optional.empty();
    Optional<Duration> d1 = headers.firstValue("Retry-After").flatMap(v -> {
      try { return Optional.of(Duration.ofSeconds(Long.parseLong(v.trim()))); }
      catch (NumberFormatException nfe) {
        try { return Optional.of(Duration.between(Instant.now(clock), ZonedDateTime.parse(v).toInstant())); }
        catch (Exception ignore) { return Optional.empty(); }
      }
    });
    return d1.filter(d -> !d.isNegative());
  }
}
```

### HTTP Client Example (JDK 11 `HttpClient`)

```java
package retry.pattern;

import java.net.URI;
import java.net.http.*;
import java.time.*;
import java.util.Set;
import java.util.UUID;
import java.util.function.Predicate;

public class HttpWithRetry {

  private static final HttpClient CLIENT = HttpClient.newBuilder()
      .connectTimeout(Duration.ofSeconds(3))
      .build();

  // Retry classification
  private static final Set<Integer> RETRY_STATUS = Set.of(408, 429, 500, 502, 503, 504);
  private static final Predicate<Throwable> RETRYABLE_THROWABLES = t ->
      t instanceof java.net.ConnectException ||
      t instanceof java.net.http.HttpTimeoutException ||
      t instanceof java.io.InterruptedIOException;

  public static String postOrder(String baseUrl, String bodyJson) throws Exception {
    String idempotencyKey = UUID.randomUUID().toString(); // persist if you need cross-process dedup

    Retryer.Config cfg = new Retryer.Config(
        5,                            // max attempts
        Duration.ofMillis(200),       // base
        Duration.ofSeconds(3),        // cap
        2.0,                          // multiplier
        Duration.ofSeconds(8),        // overall deadline
        RETRYABLE_THROWABLES,         // which throwables to retry
        RETRY_STATUS::contains        // which HTTP statuses to retry
    );
    Retryer retryer = new Retryer(cfg);

    return retryer.call(() -> {
      HttpRequest req = HttpRequest.newBuilder()
          .uri(URI.create(baseUrl + "/orders"))
          .timeout(Duration.ofSeconds(2)) // per-attempt timeout
          .header("Content-Type", "application/json")
          .header("Idempotency-Key", idempotencyKey) // enables safe duplicates server-side
          .POST(HttpRequest.BodyPublishers.ofString(bodyJson))
          .build();

      HttpResponse<String> resp;
      try {
        resp = CLIENT.send(req, HttpResponse.BodyHandlers.ofString());
      } catch (Exception e) {
        if (RETRYABLE_THROWABLES.test(e)) throw e;
        throw e;
      }

      int sc = resp.statusCode();
      if (RETRY_STATUS.contains(sc)) {
        // Honor Retry-After header when present
        Retryer.retryAfter(resp.headers(), Clock.systemUTC())
            .ifPresent(d -> {
              try { Thread.sleep(Math.min(d.toMillis(), 3000)); } catch (InterruptedException ignored) {}
            });
        throw new TransientStatus(sc, "retryable http status " + sc);
      }
      if (sc >= 200 && sc < 300) return resp.body();
      throw new RuntimeException("non-retryable http status " + sc + ": " + resp.body());
    });
  }

  static class TransientStatus extends RuntimeException {
    final int status;
    TransientStatus(int status, String msg) { super(msg); this.status = status; }
  }
}
```

**Notes:**

-   **Idempotency-Key** must be **understood by the server** (store request key → response mapping for a retention window).
    
-   Replace `Thread.sleep` with scheduled executors/reactive delay in non-blocking stacks.
    
-   Add **circuit breaker** (e.g., Resilience4j) around `postOrder` for fast-fail when downstream is unhealthy.
    

---

## Optional: Spring Kafka Consumer Retries → DLQ (consumer-side pattern)

```java
// Bounded retries with exponential backoff then dead-letter topic.
import org.springframework.kafka.listener.DefaultErrorHandler;
import org.springframework.util.backoff.ExponentialBackOffWithMaxRetries;

@Bean
DefaultErrorHandler errorHandler(org.springframework.kafka.core.KafkaTemplate<Object,Object> tpl) {
  var backoff = new ExponentialBackOffWithMaxRetries(3);
  backoff.setInitialInterval(500);
  backoff.setMultiplier(2.0);
  backoff.setMaxInterval(5000);
  var recoverer = new org.springframework.kafka.listener.DeadLetterPublishingRecoverer(tpl);
  var handler = new DefaultErrorHandler(recoverer, backoff);
  handler.addNotRetryableExceptions(IllegalArgumentException.class); // classify
  return handler;
}
```

---

## Known Uses

-   **Cloud SDKs** (AWS, GCP, Azure) implement **exponential backoff with jitter** by default for API calls.
    
-   **HTTP clients** and **datastore drivers** (e.g., Postgres, Mongo) commonly include configurable retry policies.
    
-   **Stream processors** (Kafka, Pub/Sub, SQS) provide **redelivery with backoff** and **DLQ** after capped attempts.
    

## Related Patterns

-   **Timeouts** and **Deadlines:** Bound each attempt and total work.
    
-   **Circuit Breaker & Bulkhead:** Prevent cascades and isolate failures while retrying.
    
-   **Idempotent Consumer / Idempotency Key:** Make retries safe.
    
-   **Rate Limiting & Token Bucket:** Coordinate with backpressure to avoid storms.
    
-   **Dead Letter Queue:** Final parking when retries are exhausted.
    
-   **Fallback & Cache-Aside:** Alternatives when retries keep failing.

