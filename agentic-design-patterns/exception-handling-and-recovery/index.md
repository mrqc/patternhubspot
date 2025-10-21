
# Exception Handling and Recovery

## Pattern Name and Classification

Exception Handling and Recovery — reliability/resilience pattern for agentic systems; classifies failures and applies targeted recovery tactics (retry, fallback, compensation, quarantine) to keep progress without corrupting state.

## Intent

Detect, classify, and recover from errors in agent workflows and tool calls so that failures are contained, work is retried safely, and side effects remain consistent.

## Also Known As

Resilience; Fault Tolerance; Graceful Degradation; Compensation; Dead-Lettering.

## Motivation (Forces)

-   Agentic systems span flaky networks, rate limits, non-idempotent tools, and stochastic models.

-   A naive retry can double-charge users or create duplicate side effects.

-   Some errors are transient (retryable), others are permanent (validation, policy), and some are unknown.

-   We need to preserve auditability, avoid cascading failures, and provide useful partial results.


## Applicability

Use when:

-   Tools/APIs may time out, throttle, or intermittently fail.

-   Steps cause side effects (tickets, emails, DB writes) that must not duplicate.

-   You must provide partial progress or a fallback answer under failure budgets.

-   Compliance requires tracing and safe aborts.  
    Avoid when operations are strictly all-or-nothing with external atomicity guarantees you already rely on.


## Structure

1.  **Detector** captures exceptions and error statuses.

2.  **Classifier** labels errors: `TRANSIENT`, `PERMANENT`, `UNKNOWN`, `POLICY`, `TIMEOUT`, etc.

3.  **Policy** maps class → tactic (retry/backoff, circuit break, fallback, compensate, quarantine).

4.  **Executor** applies tactic with budgets (max tries, cost/time caps).

5.  **Idempotency Guard** deduplicates side effects via tokens.

6.  **Compensator** undoes or mitigates partial side effects.

7.  **DLQ/Quarantine** stores irrecoverable tasks for manual review.

8.  **Telemetry** logs decisions, attempts, and outcomes.


## Participants

-   **Recovery Orchestrator**: central engine executing policies.

-   **Classifier**: rules or model that maps exceptions to classes.

-   **Retry Policy**: backoff, jitter, and limits per error/tool.

-   **Circuit Breaker**: halts a failing dependency for a cooldown.

-   **Fallback Provider**: degraded response or cached result.

-   **Compensation Handler**: issues undo actions for Sagas.

-   **Dead-Letter Queue**: persistent store for unrecoverables.

-   **Logger/Tracer**: observability and audit.


## Collaboration

Step/tool call throws → Detector catches → Classifier labels → Policy chooses tactic → Executor retries or falls back; if side effects occurred, Compensator runs → On repeated failure, Circuit Breaker opens and task moves to DLQ → Orchestrator returns best-effort result plus trace.

## Consequences

**Benefits**

-   Higher reliability and graceful degradation instead of hard failure.

-   Controlled duplicates via idempotency and compensation.

-   Clear audit trail and safer interaction with flaky tools.


**Liabilities**

-   More complexity and moving parts.

-   Bad classification can either spam retries or give up too early.

-   Compensation is domain-specific and can be partial or costly.

-   Requires rigorous testing of failure paths.


## Implementation (Key Points)

-   Define **error taxonomy** and map to tactics; keep per-tool overrides.

-   Use **exponential backoff with jitter**, plus **timeouts** and **budgets**.

-   Ensure **idempotency** for any write by passing an idempotency key and storing outcomes.

-   Add a **circuit breaker** per dependency; expose health metrics.

-   Log every attempt with correlation ids; emit structured error details.

-   For multi-step workflows, model compensation as a **Saga** with reverse steps.

-   Quarantine unrecoverable items to a **DLQ** with enough context for replay.

-   Test chaos scenarios: timeouts, partial writes, rate limits, malformed outputs.


## Sample Code (Java)

```java
import java.time.Duration;
import java.util.*;
import java.util.concurrent.ThreadLocalRandom;

// ---- Error taxonomy ----
enum ErrorClass { TRANSIENT, PERMANENT, POLICY, TIMEOUT, UNKNOWN }

// ---- Exception types (examples) ----
class RateLimitException extends RuntimeException { RateLimitException(String m) { super(m); } }
class PolicyViolationException extends RuntimeException { PolicyViolationException(String m) { super(m); } }
class PermanentValidationException extends RuntimeException { PermanentValidationException(String m) { super(m); } }

// ---- Classifier ----
class ErrorClassifier {
    static ErrorClass classify(Throwable t) {
        if (t instanceof RateLimitException) return ErrorClass.TRANSIENT;
        if (t instanceof java.net.SocketTimeoutException) return ErrorClass.TIMEOUT;
        if (t instanceof PolicyViolationException) return ErrorClass.POLICY;
        if (t instanceof PermanentValidationException) return ErrorClass.PERMANENT;
        return ErrorClass.UNKNOWN;
    }
}

// ---- Retry policy with backoff & jitter ----
class RetryPolicy {
    final int maxAttempts;
    final Duration baseDelay;
    final Duration maxDelay;
    RetryPolicy(int maxAttempts, Duration baseDelay, Duration maxDelay) {
        this.maxAttempts = maxAttempts; this.baseDelay = baseDelay; this.maxDelay = maxDelay;
    }
    Duration nextBackoff(int attempt) {
        long pow = 1L << Math.min(attempt - 1, 10);
        long millis = Math.min(baseDelay.toMillis() * pow, maxDelay.toMillis());
        long jitter = ThreadLocalRandom.current().nextLong(50, 250);
        return Duration.ofMillis(millis + jitter);
    }
}

// ---- Circuit breaker ----
class CircuitBreaker {
    enum State { CLOSED, OPEN, HALF_OPEN }
    private State state = State.CLOSED;
    private long openedAt = 0;
    private final Duration resetTimeout;

    CircuitBreaker(Duration resetTimeout) { this.resetTimeout = resetTimeout; }

    boolean allow() {
        if (state == State.CLOSED) return true;
        if (state == State.OPEN && System.currentTimeMillis() - openedAt > resetTimeout.toMillis()) {
            state = State.HALF_OPEN; return true;
        }
        return state == State.HALF_OPEN;
    }
    void recordSuccess() { state = State.CLOSED; }
    void recordFailure() {
        if (state == State.HALF_OPEN || state == State.CLOSED) {
            state = State.OPEN; openedAt = System.currentTimeMillis();
        }
    }
    State state() { return state; }
}

// ---- Idempotency registry (toy) ----
class IdempotencyStore {
    private final Map<String, String> outcomes = new HashMap<>();
    synchronized boolean has(String key) { return outcomes.containsKey(key); }
    synchronized void put(String key, String result) { outcomes.put(key, result); }
    synchronized String get(String key) { return outcomes.get(key); }
}

// ---- Fallback provider (cache or degraded response) ----
interface FallbackProvider {
    Optional<String> fallback(String input, Throwable cause);
}
class StaticFallback implements FallbackProvider {
    public Optional<String> fallback(String input, Throwable cause) {
        return Optional.of("Degraded response for: " + input + " (reason: " + cause.getClass().getSimpleName() + ")");
    }
}

// ---- Compensator (Saga) ----
interface Compensator {
    void compensate(String idemKey, String context);
}
class LogOnlyCompensator implements Compensator {
    public void compensate(String idemKey, String context) {
        System.err.println("Compensation queued for " + idemKey + " context=" + context);
    }
}

// ---- Tool client (simulated flaky dependency) ----
class ExternalTool {
    String call(String input, String idempotencyKey) {
        // Simulate failures
        int r = ThreadLocalRandom.current().nextInt(100);
        if (r < 15) throw new RateLimitException("429 Too Many Requests");
        if (r < 25) throw new java.net.SocketTimeoutException("timeout");
        if (r < 30) throw new PolicyViolationException("blocked content");
        if (input.length() < 3) throw new PermanentValidationException("too short");
        return "OK:" + input + ":" + idempotencyKey;
    }
}

// ---- Recovery Orchestrator ----
class RecoveryOrchestrator {
    private final RetryPolicy retry;
    private final CircuitBreaker breaker;
    private final IdempotencyStore idem;
    private final FallbackProvider fallback;
    private final Compensator compensator;
    private final ExternalTool tool;

    RecoveryOrchestrator(RetryPolicy r, CircuitBreaker b, IdempotencyStore i,
                         FallbackProvider f, Compensator c, ExternalTool t) {
        this.retry = r; this.breaker = b; this.idem = i; this.fallback = f; this.compensator = c; this.tool = t;
    }

    public String safeCall(String input, String idemKey) {
        // Idempotency short-circuit
        if (idem.has(idemKey)) return idem.get(idemKey);
        if (!breaker.allow()) return fallback.orElse("circuit-open");

        int attempt = 0;
        while (true) {
            attempt++;
            try {
                String result = tool.call(input, idemKey);
                idem.put(idemKey, result);
                breaker.recordSuccess();
                return result;
            } catch (Throwable t) {
                ErrorClass cls = ErrorClassifier.classify(t);
                System.err.println("attempt=" + attempt + " class=" + cls + " err=" + t.getMessage());
                switch (cls) {
                    case TRANSIENT, TIMEOUT, UNKNOWN -> {
                        if (attempt >= retry.maxAttempts) {
                            breaker.recordFailure();
                            return fallbackOrDLQ(input, t, idemKey);
                        }
                        sleep(retry.nextBackoff(attempt));
                        continue;
                    }
                    case POLICY, PERMANENT -> {
                        // Compensate if any partial side effects might exist
                        compensator.compensate(idemKey, "policy/permanent failure");
                        return fallbackOrDLQ(input, t, idemKey);
                    }
                }
            }
        }
    }

    private String fallbackOrDLQ(String input, Throwable cause, String idemKey) {
        return fallback.fallback(input, cause).orElseGet(() -> {
            // Dead-letter (here: log only)
            System.err.println("DLQ enqueue: key=" + idemKey + " input=" + input + " cause=" + cause);
            return "FAILED:" + cause.getClass().getSimpleName();
        });
    }

    private static void sleep(Duration d) {
        try { Thread.sleep(d.toMillis()); } catch (InterruptedException ignored) { Thread.currentThread().interrupt(); }
    }
}

// ---- Demo ----
public class ExceptionHandlingAndRecoveryDemo {
    public static void main(String[] args) {
        RecoveryOrchestrator orch = new RecoveryOrchestrator(
                new RetryPolicy(4, Duration.ofMillis(120), Duration.ofMillis(1200)),
                new CircuitBreaker(Duration.ofSeconds(2)),
                new IdempotencyStore(),
                new StaticFallback(),
                new LogOnlyCompensator(),
                new ExternalTool()
        );

        for (int i = 0; i < 8; i++) {
            String key = "idem-" + (i < 6 ? "A" : "B"); // first 6 share the same idempotency key to show dedupe
            String input = i % 3 == 0 ? "ok-input" : "okish";
            String out = orch.safeCall(input, key);
            System.out.println("result=" + out);
        }
    }
}
```

## Known Uses

-   Retrying LLM tool calls with backoff and circuit breaking for flaky services.

-   Compensating transactions in multi-step workflows (e.g., booking: hold seat → pay → issue ticket; on failure, release hold).

-   Dead-lettering unfixable tasks for manual review.

-   Graceful degradation: cached answers or partial results when a dependency is down.

-   Idempotent write APIs preventing duplicate orders, emails, or ticket creation.


## Related Patterns

-   **Planning:** defines compensating steps and stop conditions.

-   **Prompt Chaining:** recovery logic can wrap each stage boundary.

-   **Routing:** on failure, route to safer or cheaper alternatives.

-   **Parallelization:** hedge requests and race backups to reduce tail latency.

-   **Tool Use:** enforce idempotency and policy checks around external actions.

-   **Reflection:** evaluate failures and feed fixes back into prompts and policies.
