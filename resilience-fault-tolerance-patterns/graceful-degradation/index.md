# Graceful Degradation — Resilience & Fault-Tolerance Pattern

## Pattern Name and Classification

**Name:** Graceful Degradation  
**Classification:** Resilience / Fault-Tolerance Pattern (Progressive Feature Reduction & UX Preservation)

## Intent

When portions of a system are **unavailable, slow, or overloaded**, keep core journeys working by **reducing quality or scope** (e.g., omit non-critical features, serve cached/stale data, downscale fidelity) instead of failing the whole request.

## Also Known As

-   Progressive Degradation
    
-   Degraded Mode
    
-   Best-Effort Service
    
-   Tiered Quality of Service (QoS)
    

## Motivation (Forces)

-   **Availability over completeness:** Users often prefer timely, partial results to errors or timeouts.
    
-   **Complex dependencies:** Modern apps rely on multiple downstreams (search, personalization, payments, media). Some can fail without blocking the core path.
    
-   **Latency budgets/SLOs:** It’s better to skip optional work than to blow p95/p99.
    
-   **Cost control:** During surges, purposefully shed non-essential work to protect critical capacity.
    

Counter-forces:

-   **Correctness/consistency:** Some domains can’t tolerate approximation.
    
-   **Hidden incidents:** If not instrumented, degradation can mask failures.
    

## Applicability

Use Graceful Degradation when:

-   You can **rank features** by criticality (must-have vs. nice-to-have).
    
-   There are **safe substitutes** (cached data, placeholders, defaults).
    
-   The UI/API can **signal partial results** to consumers.
    
-   You have **signals** (circuit state, error rates, queue depth) to trigger mode changes.
    

Avoid or limit when:

-   Regulatory or financial correctness requires full fidelity.
    
-   Partial output could be misleading or unsafe.
    

## Structure

```sql
Request
  ├── Guard/Health checks (bulkhead, timeout, circuit)
  ├── Execute essential path (must not degrade)
  ├── Try optional features in priority order with small budgets
  │     ├── if slow/failing → skip/replace with cached/default
  │     └── record degradation
  └── Respond with result + metadata (e.g., X-Degraded: true; components omitted)
```

## Participants

-   **Degradation Controller/Policy:** Decides which features to drop by priority and current health/load.
    
-   **Essential Components:** Must run; otherwise the request fails.
    
-   **Optional Components:** Added when healthy; skipped or approximated when not.
    
-   **Fallback Providers:** Cache/LKG, secondary providers, placeholders.
    
-   **Telemetry:** Counters, traces, and headers that indicate degradation.
    

## Collaboration

-   Guards (timeouts, bulkheads, circuit breakers) provide **signals** and enforce budgets.
    
-   The controller **orchestrates** calls to optional components with tiny timeboxes; on failure it uses a fallback and marks the response as degraded.
    
-   The client (UI/API consumer) **honors metadata** to adjust presentation (e.g., hide widgets).
    

## Consequences

**Benefits**

-   Preserves core UX/SLOs under partial failure or load spikes.
    
-   Reduces cascading failures by not waiting on non-critical paths.
    
-   Produces **measurable** degrade events that drive autoscaling and incident response.
    

**Liabilities / Trade-offs**

-   Stale or incomplete data; must communicate clearly.
    
-   Additional code paths and testing matrix.
    
-   Poor observability can normalize degraded state.
    

## Implementation

1.  **Classify features:** must-have, important, nice-to-have.
    
2.  **Define budgets:** small timeouts for optional features (e.g., 50–150 ms each).
    
3.  **Add fallbacks:** cache/LKG, placeholders, simpler algorithms or secondary regions.
    
4.  **Centralize policy:** a controller that applies the same degrade rules everywhere.
    
5.  **Propagate signals:** response headers/flags (e.g., `X-Degraded: true`, `X-Degraded-Parts: recs,ratings`).
    
6.  **Instrument:** counters for degraded responses by reason, feature, and endpoint.
    
7.  **Chaos test:** inject failures/latency to verify UX and metrics.
    
8.  **Govern:** document which endpoints may degrade and how UX should adapt.
    

---

## Sample Code (Java)

**Scenario:** Product page renders even if recommendations/ratings are down. We protect the essential product fetch and degrade optional features with time-boxed calls, fallbacks, and response flags.

```java
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Supplier;

public class ProductFacade {

  private final ExecutorService pool = Executors.newFixedThreadPool(64);

  private final ProductApi productApi;           // essential
  private final RecommendationsApi recsApi;      // optional
  private final RatingsApi ratingsApi;           // optional

  // tiny budgets for optional features
  private static final Duration RECS_BUDGET   = Duration.ofMillis(120);
  private static final Duration RATINGS_BUDGET= Duration.ofMillis(80);

  public ProductFacade(ProductApi productApi, RecommendationsApi recsApi, RatingsApi ratingsApi) {
    this.productApi = productApi;
    this.recsApi = recsApi;
    this.ratingsApi = ratingsApi;
  }

  public ProductResponse getProductPage(String id) throws Exception {
    // 1) Essential path (fail if unavailable)
    Product core = timebox(() -> productApi.getProduct(id), Duration.ofMillis(300))
        .orElseThrow(() -> new IllegalStateException("Product unavailable"));

    // 2) Optional features (best effort)
    List<Product> recs = timebox(() -> recsApi.topFor(id), RECS_BUDGET)
        .orElseGet(List::of); // degrade to empty list

    OptionalDouble rating = timebox(() -> ratingsApi.averageFor(id), RATINGS_BUDGET)
        .map(OptionalDouble::of).orElse(OptionalDouble.empty()); // degrade to missing

    // 3) Compose response + signal degradation
    boolean degraded = recs.isEmpty() || rating.isEmpty();
    Set<String> parts = new HashSet<>();
    if (recs.isEmpty()) parts.add("recs");
    if (rating.isEmpty()) parts.add("ratings");

    return new ProductResponse(core, recs, rating, degraded, parts);
  }

  // Helper: run task with timeout, treat exceptions/timeouts as empty
  private <T> Optional<T> timebox(Callable<T> task, Duration budget) {
    Future<T> f = pool.submit(task);
    try {
      return Optional.ofNullable(f.get(budget.toMillis(), TimeUnit.MILLISECONDS));
    } catch (Exception e) {
      f.cancel(true);
      return Optional.empty();
    }
  }

  // --- APIs & DTOs ---

  public interface ProductApi { Product getProduct(String id) throws Exception; }
  public interface RecommendationsApi { List<Product> topFor(String productId) throws Exception; }
  public interface RatingsApi { double averageFor(String productId) throws Exception; }

  public static final class Product {
    public final String id; public final String name;
    public Product(String id, String name) { this.id = id; this.name = name; }
  }

  public static final class ProductResponse {
    public final Product product;
    public final List<Product> recommendations;
    public final OptionalDouble rating;
    public final boolean degraded;
    public final Set<String> degradedParts;

    public ProductResponse(Product product, List<Product> recommendations, OptionalDouble rating,
                           boolean degraded, Set<String> degradedParts) {
      this.product = product;
      this.recommendations = recommendations;
      this.rating = rating;
      this.degraded = degraded;
      this.degradedParts = Collections.unmodifiableSet(degradedParts);
    }

    /** Example of surfacing metadata as headers (for a web framework/controller). */
    public Map<String, String> headers() {
      Map<String, String> h = new HashMap<>();
      h.put("X-Degraded", String.valueOf(degraded));
      if (degraded && !degradedParts.isEmpty()) {
        h.put("X-Degraded-Parts", String.join(",", degradedParts));
      }
      return h;
    }
  }
}
```

**Notes**

-   Protect optional components with **tiny timeouts**. Do **not** block the page for them.
    
-   Pair with **circuit breakers**; if a dependency is OPEN, skip calling it and mark degraded.
    
-   Cache successful optional results (LKG) to improve perceived quality while the dependency heals.
    

---

## Known Uses

-   **E-commerce PDP/checkout:** Show product + price even if recommendations, reviews, or dynamic promos fail; disable coupon validation if promo engine is down (read-only mode).
    
-   **News/feeds:** Serve cached timeline and omit live counts or personalization when signals degrade.
    
-   **Maps/geo:** Show static tiles without traffic overlays when live routing is down.
    
-   **Video/ML services:** Reduce bitrate/model size or switch to a heuristic model under load.
    
-   **Enterprise portals:** Render shell/navigation and lazy-load widgets; hide non-critical widgets if sources fail.
    

## Related Patterns

-   **Fallback:** The concrete alternate result used within degraded mode.
    
-   **Fail Fast:** Quickly decide to degrade instead of waiting on optional paths.
    
-   **Bulkhead:** Reserve capacity for essentials while limiting optional features.
    
-   **Circuit Breaker:** Skip unhealthy dependencies and enter degraded mode.
    
-   **Timeouts:** Enforce strict budgets per optional feature.
    
-   **Feature Flags:** Flip system-wide to “degraded mode” during incidents.
    
-   **Cache-Aside / Last-Known-Good:** Common sources of data for degraded responses.
    

**Guideline:** Decide **in advance** what’s essential vs. optional, **budget tightly** for optional features, and **signal degradation** so users and operators know what happened.
