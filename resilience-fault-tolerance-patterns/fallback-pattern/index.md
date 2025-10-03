# Fallback — Resilience & Fault-Tolerance Pattern

## Pattern Name and Classification

**Name:** Fallback  
**Classification:** Resilience / Fault-Tolerance Pattern (Graceful Degradation & Alternate Path)

## Intent

When the primary operation **fails, times out, or is unavailable**, return a **safe alternative**—such as cached/stale data, a default result, a reduced-quality response, or a different provider—so the system degrades gracefully instead of failing catastrophically.

## Also Known As

-   Graceful Degradation
    
-   Default Response / Safe Default
    
-   Substitute / Alternative Path
    
-   Degraded Mode
    

## Motivation (Forces)

-   **Availability over perfection:** Users prefer partial results to hard errors during incidents.
    
-   **Dependency fragility:** Remote services, data stores, or models can fail or slow down.
    
-   **User experience:** Keeping core journeys working (even with reduced fidelity) preserves trust and revenue.
    
-   **Operational clarity:** Predictable degraded responses are easier to monitor than sporadic timeouts.
    

Counter-forces:

-   **Staleness and correctness risks:** Old or approximate data may mislead.
    
-   **Hidden failures:** Overuse can mask real problems if not instrumented.
    

## Applicability

Use Fallback when:

-   There is a **meaningful substitute** (default value, last-known good, subset, synthetic answer).
    
-   The cost of failure is high and **SLAs favor availability**.
    
-   You can **bound staleness** and communicate degradation.
    
-   Combined with **Circuit Breaker/Bulkhead/Timeouts** to decide when to invoke the fallback.
    

Avoid or tune carefully when:

-   Domain requires **strong consistency or correctness** (e.g., payments, legal compliance).
    
-   Returning stale/approximate data causes harm or security issues.
    
-   Fallback could trigger **feedback loops** (e.g., caching errors).
    

## Structure

```sql
Client ──► Primary Operation (may fail/timeout)
             │ success
             └──────────────► Return primary result
             │ failure/timeout/rejection
             ▼
          Fallback Strategy (cache/default/alt provider/partial)
             │
             └──────────────► Return degraded result (+ signal/metrics)
```

## Participants

-   **Caller / Orchestrator:** Wraps the primary call and applies fallback on failure.
    
-   **Primary Operation:** The preferred dependency or algorithm.
    
-   **Fallback Strategy:** Defines how to produce an alternative (cache, default, stub, alt provider).
    
-   **Policy / Guard:** Circuit breaker, timeout, bulkhead, or error classifier that triggers fallback.
    
-   **Telemetry:** Metrics, logs, and headers/tags indicating degraded responses.
    

## Collaboration

-   Caller invokes **primary → guard**; on failure or rejection, selects and executes **fallback**.
    
-   Fallback may consult **caches**, **read replicas**, or **precomputed summaries**.
    
-   The response is **tagged** (e.g., header `X-Degraded: true`) and metrics are emitted to avoid masking incidents.
    

## Consequences

**Benefits**

-   Maintains availability under partial failures.
    
-   Protects latency budgets (fast degraded responses).
    
-   Reduces cascade effects and support load.
    

**Liabilities / Trade-offs**

-   Possible **stale/approximate** data.
    
-   Risk of **overuse** hiding systemic issues—must alert on fallback usage.
    
-   Extra code paths to maintain and test.
    

## Implementation

1.  **Define failure classes:** timeouts, connection errors, 5xx, circuit-open, validation errors.
    
2.  **Choose fallback type(s):**
    
    -   **Static default:** constant or empty structure.
        
    -   **Stale cache / last-known good (LKG):** bounded by TTL or version.
        
    -   **Alternative provider:** secondary service/region/read-replica.
        
    -   **Partial result:** subset without expensive parts.
        
3.  **Order of operations:** Typically **Bulkhead → Timeout → Circuit Breaker → (on failure) Fallback**.
    
4.  **Bound staleness:** TTL for cache; attach freshness metadata.
    
5.  **Signal degradation:** Add logs/metrics/headers; surface to UX if appropriate.
    
6.  **Test:** Chaos/fault injection; verify correctness, staleness bounds, and usability.
    
7.  **Govern:** Decide which endpoints may degrade; document user-visible effects.
    

---

## Sample Code (Java)

### A) Lightweight fallback wrapper with cache/LKG and alternative provider

```java
import java.time.*;
import java.util.Optional;
import java.util.concurrent.*;
import java.util.function.Supplier;

/** A simple fallback orchestrator: primary → alt → last-known-good → default. */
public class Fallbacks<T> {

  private final ExecutorService pool = Executors.newCachedThreadPool();

  // Last-Known-Good cache with timestamp
  private volatile T lastKnownGood;
  private volatile Instant lastUpdate = Instant.EPOCH;
  private final Duration lkgTtl;

  public Fallbacks(Duration lkgTtl) {
    this.lkgTtl = lkgTtl;
  }

  public void updateLkg(T value) {
    lastKnownGood = value;
    lastUpdate = Instant.now();
  }

  /** Executes primary with timeout; falls back to alternative, then LKG (if fresh), then default. */
  public T call(
      Callable<T> primary,
      Duration timeout,
      Optional<Supplier<T>> alternative,
      Optional<Supplier<T>> defaultValue) throws Exception {

    try {
      Future<T> f = pool.submit(primary);
      T result = f.get(timeout.toMillis(), TimeUnit.MILLISECONDS);
      updateLkg(result); // refresh LKG on success
      return result;
    } catch (Exception primaryFailure) {

      // 1) Alternative provider
      if (alternative.isPresent()) {
        try {
          T alt = alternative.get().get();
          updateLkg(alt);
          return alt;
        } catch (Exception ignore) {
          // fall through
        }
      }

      // 2) Last-known-good if fresh enough
      if (lastKnownGood != null && Duration.between(lastUpdate, Instant.now()).compareTo(lkgTtl) <= 0) {
        return lastKnownGood;
      }

      // 3) Static default (final safety net)
      if (defaultValue.isPresent()) {
        return defaultValue.get().get();
      }

      // 4) Rethrow if no fallback possible
      throw primaryFailure;
    }
  }

  public void shutdown() { pool.shutdownNow(); }
}
```

**Example usage (HTTP with alt provider and LKG):**

```java
public class ProductClient {

  private final Fallbacks<String> fb = new Fallbacks<>(Duration.ofSeconds(30));
  private final Http httpPrimary;  // e.g., https://api-primary
  private final Http httpAlt;      // e.g., https://api-secondary

  public ProductClient(Http primary, Http alt) {
    this.httpPrimary = primary; this.httpAlt = alt;
  }

  public String getProduct(String id) throws Exception {
    return fb.call(
        () -> httpPrimary.get("/products/" + id),           // primary
        Duration.ofMillis(300),                              // strict timeout
        Optional.of(() -> httpAlt.get("/products/" + id)),   // alternative region
        Optional.of(() -> "{\"id\":\"" + id + "\",\"status\":\"degraded\"}") // default
    );
  }

  interface Http { String get(String path) throws Exception; }
}
```

### B) Fallback combined with a Circuit Breaker (sketch)

```java
public class SafeClient {
  private final CircuitBreaker breaker; // from your implementation or library
  private final Fallbacks<String> fallbacks = new Fallbacks<>(Duration.ofSeconds(60));
  private final Http http;

  public SafeClient(CircuitBreaker breaker, Http http) {
    this.breaker = breaker; this.http = http;
  }

  public String fetch(String path) throws Exception {
    return breaker.call(
        () -> fallbacks.call(
              () -> http.get(path),
              Duration.ofMillis(250),
              Optional.empty(),
              Optional.of(() -> "{\"status\":\"degraded\"}")
        ),
        () -> "{\"status\":\"circuit-open\"}" // breaker-level fallback
    );
  }

  interface Http { String get(String path) throws Exception; }
}
```

### C) Returning partial results (degraded computation)

```java
public class RecommendationsService {

  public Recommendations getHomeRecommendations(String userId) {
    try {
      // Full model (might be slow)
      return computeWithHeavyModel(userId);
    } catch (Exception e) {
      // Fallback: popularity-only, no personalization
      return topPopularFallback();
    }
  }

  private Recommendations computeWithHeavyModel(String userId) { /* ... */ return new Recommendations(/* ... */); }
  private Recommendations topPopularFallback() { /* ... */ return new Recommendations(/* popular only */); }

  static class Recommendations { /* fields omitted */ }
}
```

---

## Known Uses

-   **E-commerce:** If pricing service is down, show product info without dynamic discounts; if recommendations fail, show popular items.
    
-   **Content feeds:** Serve cached timeline when personalization backend is unavailable.
    
-   **Maps/Geo:** Fall back to coarse geolocation or static tiles when live routing fails.
    
-   **ML/AI features:** Use a simpler heuristic/model when the main model is unavailable.
    
-   **Payments (carefully):** Switch to **read-only** mode (show balances, disable transfers) when write path is unhealthy.
    

## Related Patterns

-   **Circuit Breaker:** Decides when to stop calling the primary and **immediately** use fallback.
    
-   **Timeouts:** Bound primary latency; trigger fallback predictably.
    
-   **Bulkhead:** Keep capacity for serving fallbacks and healthy traffic.
    
-   **Fail Fast:** Reject quickly and return fallback/default instead of waiting.
    
-   **Cache-Aside / LKG (Last-Known-Good):** Common fallback source; ensure TTLs and invalidation.
    
-   **Retry with Backoff & Jitter:** Try a few times before falling back—**but** not indefinitely.
    
-   **Feature Flags / Degraded Mode Switch:** Toggle fallbacks system-wide during incidents.
    

**Practical tip:** Decide **per endpoint** what “good enough” means, **bound staleness**, and **measure fallback rates**—if they spike, raise an alert and investigate the primary path.

