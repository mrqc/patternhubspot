# Cloud Distributed Systems Pattern — Retry with Backoff

## Pattern Name and Classification

-   **Name:** Retry with Backoff

-   **Classification:** Behavioral/Resilience pattern for distributed systems (client-side reliability control). Often part of **fault tolerance** and **latency control** toolkits.


## Intent

Automatically re-attempt transiently failing operations while **increasing the wait time** between attempts (backoff) to:

-   absorb brief outages and network glitches,

-   reduce retry storms,

-   improve end-to-end success rate without overwhelming dependencies.


## Also Known As

-   Exponential Backoff (with/without Jitter)

-   Progressive Retry

-   Decorrelated Jitter Backoff


## Motivation (Forces)

-   **Transient vs. persistent failures:** DNS blips, brief network partitions, pod restarts, cold caches → recover if we wait a bit; hard faults won’t.

-   **Load amplification risk:** Synchronous immediate retries can create **retry storms** that worsen an outage.

-   **Tail latency budgets:** Retrying helps success rate but increases latency; you need caps/deadlines.

-   **Idempotency:** Safe retries require idempotent operations (or idempotency keys).

-   **Heterogeneous errors:** Some errors are safe to retry (timeouts, 5xx); others are not (4xx like 400/401/403, validation).

-   **Fairness & contention:** Coordinated clients retrying in lockstep cause thundering herds; **jitter** randomizes spacing.

-   **System goals:** Balance **SLO** (availability) with **cost** (extra work) and **user experience** (latency).


## Applicability

Use when:

-   Operations fail **transiently** (timeouts, connection resets, 429/503/5xx with `Retry-After`).

-   Dependencies can recover within seconds.

-   You can ensure **idempotency** or attach **idempotency tokens**.

-   You can bound total latency with **max attempts** and/or **overall deadline**.


Avoid or adapt when:

-   Operations are **non-idempotent** (e.g., charges) and lack idempotency keys.

-   Failures are clearly **permanent** (e.g., 400 Bad Request).

-   Retries would **overload** a struggling dependency (apply budgets/rate limiting or circuit breakers).


## Structure

-   **Caller (Client):** Wraps an operation with a retry policy.

-   **Retry Policy:** Max attempts, backoff algorithm, jitter, retryable conditions, per-try/overall timeouts.

-   **Backoff Strategy:** Fixed, exponential, exponential with jitter, decorrelated jitter, Fibonacci, etc.

-   **Stop Strategy:** Max attempts and/or deadline reached.

-   **Telemetry:** Records attempts, reasons, delays.

-   **(Optional) Circuit Breaker / Token Bucket:** Coordinates with retries to avoid overload.


## Participants

-   **Operation:** The callable action (e.g., HTTP request, RPC, DB query).

-   **Retry Orchestrator:** Executes, inspects failures, chooses next delay, sleeps/schedules.

-   **Classifier:** Determines if a result/exception is retryable.

-   **Clock/Random:** Provides time and randomness for jitter.

-   **Budget/Breaker (optional):** Enforces retry budgets, interacts with system health.


## Collaboration

1.  Client calls Operation via Retry Orchestrator.

2.  If result is success → return.

3.  If failure → Classifier decides **retryable?**

    -   If not retryable or budget exceeded → propagate error.

    -   If retryable → Backoff Strategy computes next delay (+ jitter).

4.  Orchestrator waits (respecting overall deadline), then tries again.

5.  Telemetry logs each attempt; optional Circuit Breaker updates state.


## Consequences

**Benefits**

-   Masks brief failures, dramatically improves success rate.

-   Reduces coordinated hammering when using jitter.

-   Simple to implement; easy policy control.


**Liabilities**

-   Increases latency and resource use.

-   If misconfigured, may create **excess load** or mask real bugs.

-   Requires idempotency or safeguards to avoid duplicate side effects.

-   Needs integration with **timeouts**, **budgets**, and **circuit breakers**.


## Implementation (Key Points)

-   **Choose backoff:** Prefer **exponential with jitter** (e.g., full jitter or decorrelated) to avoid synchronization.

-   **Set bounds:** `maxAttempts`, `maxDelay`, **overallDeadline** (e.g., 2–10s for user requests).

-   **Per-try timeout:** Each attempt should have its own timeout shorter than the overall deadline.

-   **Retry conditions:** Exceptions like `IOException`, `HttpTimeoutException`, status codes 408/429/5xx (but not 501/505 depending on context). Respect `Retry-After`.

-   **Idempotency:** Use GET/PUT/DELETE or an **idempotency key** for POSTs.

-   **Budgets & breaker:** Cap retries per request; integrate with a **circuit breaker** to fail fast under sustained faults.

-   **Observability:** Emit attempt count, delays, outcome, and classify by error type.


---

## Sample Code (Java 17): Exponential Backoff with Jitter, Deadline, and Retry Classification

> Compact, production-leaning example showing:
>
> -   exponential backoff with **full jitter**,
>
> -   **overall deadline** and **max attempts**,
>
> -   per-try timeout,
>
> -   retryable **HTTP** status classification,
>
> -   generic `call(CheckedSupplier<T>)` API.
>

```java
// File: RetryWithBackoff.java
// javac RetryWithBackoff.java && java Demo (see Demo class at bottom)
import java.net.URI;
import java.net.http.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Predicate;

public final class RetryWithBackoff {
    public static final class Policy {
        public final int maxAttempts;
        public final Duration initialDelay;
        public final double multiplier;
        public final Duration maxDelay;
        public final Duration overallDeadline; // total time budget
        public final double jitterFactor; // 0.0..1.0 (full jitter = 1.0)
        public final Predicate<Throwable> retryOnException;
        public final Predicate<HttpResponse<?>> retryOnResponse;

        private Policy(Builder b) {
            this.maxAttempts = b.maxAttempts;
            this.initialDelay = b.initialDelay;
            this.multiplier = b.multiplier;
            this.maxDelay = b.maxDelay;
            this.overallDeadline = b.overallDeadline;
            this.jitterFactor = b.jitterFactor;
            this.retryOnException = b.retryOnException;
            this.retryOnResponse = b.retryOnResponse;
        }

        public static Builder builder() { return new Builder(); }
        public static final class Builder {
            private int maxAttempts = 4;
            private Duration initialDelay = Duration.ofMillis(100);
            private double multiplier = 2.0;
            private Duration maxDelay = Duration.ofSeconds(2);
            private Duration overallDeadline = Duration.ofSeconds(5);
            private double jitterFactor = 1.0;
            private Predicate<Throwable> retryOnException = t ->
                    (t instanceof java.net.http.HttpTimeoutException) ||
                    (t instanceof java.io.IOException);
            private Predicate<HttpResponse<?>> retryOnResponse = r -> {
                int sc = r.statusCode();
                return sc == 408 || sc == 429 || (sc >= 500 && sc != 501 && sc != 505);
            };

            public Builder maxAttempts(int n) { this.maxAttempts = n; return this; }
            public Builder initialDelay(Duration d) { this.initialDelay = d; return this; }
            public Builder multiplier(double m) { this.multiplier = m; return this; }
            public Builder maxDelay(Duration d) { this.maxDelay = d; return this; }
            public Builder overallDeadline(Duration d) { this.overallDeadline = d; return this; }
            public Builder jitterFactor(double f) { this.jitterFactor = Math.max(0.0, Math.min(1.0, f)); return this; }
            public Builder retryOnException(Predicate<Throwable> p) { this.retryOnException = p; return this; }
            public Builder retryOnResponse(Predicate<HttpResponse<?>> p) { this.retryOnResponse = p; return this; }
            public Policy build() { return new Policy(this); }
        }
    }

    @FunctionalInterface
    public interface CheckedSupplier<T> {
        T get() throws Exception;
    }

    private final Policy policy;
    private final Clock clock;
    private final Random random;

    public RetryWithBackoff(Policy policy) {
        this(policy, Clock.systemUTC(), ThreadLocalRandom.current());
    }
    public RetryWithBackoff(Policy policy, Clock clock, Random random) {
        this.policy = policy;
        this.clock = clock;
        this.random = random;
    }

    public <T> T call(CheckedSupplier<T> op) throws Exception {
        final Instant endBy = Instant.now(clock).plus(policy.overallDeadline);
        int attempt = 1;
        Duration delay = policy.initialDelay;

        Exception lastEx = null;

        while (true) {
            try {
                return op.get();
            } catch (Exception ex) {
                lastEx = ex;
                boolean retryable = policy.retryOnException.test(ex);
                if (!retryable || attempt >= policy.maxAttempts || Instant.now(clock).isAfter(endBy)) {
                    throw ex;
                }
            }

            // sleep with exponential backoff + full jitter
            Duration capped = delay.compareTo(policy.maxDelay) < 0 ? delay : policy.maxDelay;
            long sleepMillis = jitterMillis(capped, policy.jitterFactor);
            // Ensure we don't exceed the overall deadline
            long remaining = Duration.between(Instant.now(clock), endBy).toMillis();
            if (remaining <= 0) throw lastEx;
            sleepMillis = Math.min(sleepMillis, Math.max(0, remaining));

            sleepQuietly(sleepMillis);
            attempt++;
            delay = Duration.ofMillis(Math.min(
                    (long)(delay.toMillis() * policy.multiplier),
                    policy.maxDelay.toMillis()));
        }
    }

    public <T> T callHttp(HttpClient client, HttpRequest request, HttpResponse.BodyHandler<T> handler) throws Exception {
        return call(() -> {
            // Apply a per-try timeout shorter than overall budget
            Duration perTry = perTryTimeout(policy.overallDeadline, policy.maxAttempts);
            HttpRequest req = HttpRequest.newBuilder(request.uri())
                    .method(request.method(), request.bodyPublisher().orElse(HttpRequest.BodyPublishers.noBody()))
                    .timeout(perTry)
                    .headers(flattenHeaders(request))
                    .build();

            HttpResponse<T> resp = client.send(req, handler);

            if (policy.retryOnResponse.test(resp)) {
                // Respect Retry-After if present (simple parse of seconds)
                Optional<String> ra = resp.headers().firstValue("Retry-After");
                if (ra.isPresent()) {
                    try {
                        long sec = Long.parseLong(ra.get().trim());
                        sleepQuietly(Math.min(sec * 1000L, policy.maxDelay.toMillis()));
                    } catch (NumberFormatException ignored) { /* HTTP-date not handled here */ }
                }
                throw new RetriableStatusException(resp.statusCode());
            }
            return resp.body();
        });
    }

    private static String[] flattenHeaders(HttpRequest req) {
        List<String> h = new ArrayList<>();
        req.headers().map().forEach((k, vList) -> vList.forEach(v -> { h.add(k); h.add(v); }));
        return h.toArray(new String[0]);
    }

    private static long jitterMillis(Duration base, double jitterFactor) {
        long max = base.toMillis();
        if (jitterFactor <= 0.0) return max;
        long jitter = (long) (max * jitterFactor);
        long low = Math.max(0, max - jitter);
        long high = max + (long)(jitter * 0); // full jitter picks in [0, max]; here use [0, max]
        return ThreadLocalRandom.current().nextLong(0, max + 1);
    }

    private static Duration perTryTimeout(Duration overall, int attempts) {
        // Simple split: keep some headroom; you could be smarter (e.g., geometric)
        long ms = Math.max(100, (overall.toMillis() / attempts) - 50);
        return Duration.ofMillis(ms);
    }

    private static void sleepQuietly(long millis) {
        try { Thread.sleep(millis); } catch (InterruptedException ie) { Thread.currentThread().interrupt(); }
    }

    public static final class RetriableStatusException extends Exception {
        public final int status;
        public RetriableStatusException(int status) { super("HTTP status " + status + " is retryable"); this.status = status; }
    }

    // ---- Demo ----
    public static final class Demo {
        public static void main(String[] args) throws Exception {
            HttpClient client = HttpClient.newBuilder()
                    .connectTimeout(Duration.ofSeconds(1))
                    .version(HttpClient.Version.HTTP_1_1)
                    .build();

            var policy = Policy.builder()
                    .maxAttempts(5)
                    .initialDelay(Duration.ofMillis(150))
                    .multiplier(2.0)
                    .maxDelay(Duration.ofSeconds(2))
                    .overallDeadline(Duration.ofSeconds(6))
                    .jitterFactor(1.0) // full jitter
                    .build();

            var retry = new RetryWithBackoff(policy);

            HttpRequest req = HttpRequest.newBuilder(URI.create("http://localhost:8080/api"))
                    .timeout(Duration.ofSeconds(1)) // initial; per-try overrides
                    .GET()
                    .build();

            try {
                String body = retry.callHttp(client, req, HttpResponse.BodyHandlers.ofString());
                System.out.println("Success: " + body);
            } catch (Exception e) {
                System.err.println("Failed after retries: " + e);
            }
        }
    }
}
```

**Notes on the example**

-   Uses **full jitter**: each delay is `Uniform(0, backoff)` which strongly de-synchronizes clients.

-   Sets **per-try timeout** derived from the overall deadline.

-   Treats 408/429/5xx as retryable; consult your API’s contract.

-   For **non-idempotent** POSTs, add an **Idempotency-Key** header and server-side dedup.


---

## Known Uses

-   **Public cloud SDKs:** Most AWS/GCP/Azure SDK clients ship with exponential backoff + jitter.

-   **gRPC clients:** Built-in retry policies with backoff for idempotent methods.

-   **Service meshes and proxies:** Envoy/Istio have per-route retries with backoff and budgets.

-   **HTTP clients:** Many production wrappers around `HttpClient`/OkHttp/Apache HttpClient implement similar policies.


## Related Patterns

-   **Circuit Breaker:** Stop retrying when a dependency is likely down; fail fast.

-   **Bulkheads & Pool Isolation:** Keep one noisy dependency from exhausting shared resources.

-   **Timeouts & Deadlines:** Bound each try and the overall operation.

-   **Rate Limiting / Token Bucket:** Control inbound/outbound traffic; combine with retries to avoid overload.

-   **Load Balancer:** Combine with retries across instances (prefer **retry different host**).

-   **Idempotency Key / Exactly-Once Delivery (semantic):** Ensure safe duplication handling.


---

### Practical configuration tips

-   Start with `maxAttempts=3–5`, `initialDelay=100–200ms`, `multiplier≈2`, `maxDelay≈1–2s`, **full jitter**, **overall deadline ≤ user-facing SLO**.

-   Prefer **retry on different instance/connection** when possible.

-   Track **retry rate** and **success-after-retry** to prove value and tune safely.
