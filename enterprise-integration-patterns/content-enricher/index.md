# Content Enricher (Enterprise Integration Pattern)

## Pattern Name and Classification

**Name:** Content Enricher  
**Classification:** Enterprise Integration Pattern (Message Transformation / Enrichment)

---

## Intent

Augment an incoming message with **additional data** required by downstream consumers—by **looking up**, **deriving**, or **computing** fields—while keeping the original message intact.

---

## Also Known As

-   Message Enricher
    
-   Enrichment Filter (informal)
    
-   Reference Data Lookup
    

---

## Motivation (Forces)

-   Upstream producers often emit **minimal** messages (privacy, performance, ownership).
    
-   Downstream steps need **context** (names, addresses, product attributes, risk scores) that lives in other systems.
    
-   Centralize enrichment instead of pushing consumers to each do their own lookups → reduces duplication and drift.
    

Tensions to balance:

-   **Latency** (extra calls) vs **completeness** (richer message).
    
-   **Freshness** (live lookups) vs **cost** (caching/pre-join).
    
-   **Availability** (fallbacks when sources fail) vs **correctness** (must-have vs nice-to-have fields).
    
-   **Ownership** (don’t smuggle foreign domain rules into the message).
    

---

## Applicability

Use Content Enricher when:

-   The pipeline needs **reference/master data** (catalog, CRM, geocoding, currency, feature flags).
    
-   Enrichment can be **computed or fetched** without changing the message’s semantic owner.
    
-   You want **uniform messages** so later stages avoid repeated lookups.
    

Avoid or limit when:

-   Enrichment **changes ownership** or **business meaning**—that’s an upstream responsibility.
    
-   Enrichment requires **transactional consistency** with the source write (consider synchronous composition/OHS).
    
-   The downstream can retrieve data more efficiently **on demand** (e.g., read model with good locality).
    

---

## Structure

-   **Input Channel** → **Content Enricher** → **Output Channel**
    
-   **Lookup Sources:** caches, DBs, HTTP/gRPC services, feature stores.
    
-   **Policies:** required vs optional fields, TTLs, fallbacks, timeouts, circuit breaker.
    
-   **Cache (optional):** to absorb repeated lookups (L1 in-memory, L2 distributed).
    

---

## Participants

-   **Producer:** Sends the base message.
    
-   **Content Enricher:** Stateless/stateful component that augments the payload.
    
-   **Reference/Enrichment Services:** Systems of record for supplemental data.
    
-   **Consumers:** Receive enriched messages.
    
-   **DLQ/Retry:** For messages that cannot be enriched according to policy.
    

---

## Collaboration

1.  Message arrives with a **correlation key** (e.g., `customerId`, `sku`).
    
2.  Enricher **fetches/derives** missing fields (possibly in parallel).
    
3.  If **required** fields cannot be fetched within budget → **retry** or route to **DLQ**.
    
4.  If **optional** enrichment fails → continue with **partial** enrichment and mark reason in headers/metadata.
    
5.  Emit enriched message to output channel.
    

---

## Consequences

**Benefits**

-   **Consistent** and **simplified** downstream processing.
    
-   Encapsulates **integration logic** and **reference data** access in one place.
    
-   Enables **caching** and **bulk lookups** to reduce cost.
    

**Liabilities**

-   Extra **latency** and **failure modes** from external lookups.
    
-   Risk of **over-enrichment** (ballooning payloads).
    
-   Potential **staleness** if cached too aggressively.
    
-   Requires **resilience** (timeouts, circuit breaker, fallbacks).
    

---

## Implementation

**Guidelines**

-   Treat enrichment as a **pure function** of input + reference state; avoid mutating global state.
    
-   **Classify fields**: *required* (fail or retry) vs *optional* (best-effort).
    
-   Apply **timeouts**, **retries with backoff**, and **bulkheads** per dependency.
    
-   Use **parallel lookups** when independent; **short-circuit** when required lookup fails.
    
-   **Cache** results with TTL aligned to data volatility; cache by key (`customerId`, `sku`).
    
-   Attach **provenance** (headers like `X-Enriched-By`, `X-Enrichment-Miss`) and **version** of reference data.
    
-   Redact or **mask PII** according to policy; only enrich what’s permitted.
    
-   Keep payload size reasonable; consider **Claim Check** (store large blobs externally and pass references).
    
-   Observe: metrics for hit rate, latency per source, failure rate, payload growth.
    

**Synchronous vs Asynchronous**

-   **Sync** (in-process): when enrichment is small and critical to proceed.
    
-   **Async** (separate step): for heavier/multiple lookups; emit enriched message to next stage.
    
-   **Precompute** (materialize read model) when enrichment is frequently reused.
    

---

## Sample Code (Java – framework-agnostic enricher with caching, parallel lookups, timeouts)

Scenario: Enrich `OrderPlaced` with `CustomerProfile` and `ProductSnapshot` lines.  
Required: customer profile. Optional: product attributes (fallback to minimal).

```java
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Function;

// ---------- Messages ----------
record OrderPlaced(String orderId, String customerId, List<Line> lines, String currency) {
    record Line(String sku, int qty) {}
}
record EnrichedOrder(String orderId, CustomerProfile customer, List<Line> lines, String currency, Map<String,String> meta) {
    record Line(String sku, int qty, ProductSnapshot product) {}
}
record CustomerProfile(String customerId, String name, String tier) {}
record ProductSnapshot(String sku, String title, String category) {}

// ---------- Reference ports ----------
interface CustomerLookup { Optional<CustomerProfile> get(String customerId) throws Exception; }
interface ProductLookup  { Optional<ProductSnapshot> get(String sku) throws Exception; }

// ---------- Simple cache with TTL ----------
final class TtlCache<K,V> {
    private static final class Entry<V> { final V v; final long exp; Entry(V v,long exp){this.v=v;this.exp=exp;} }
    private final ConcurrentHashMap<K, Entry<V>> map = new ConcurrentHashMap<>();
    private final long ttlMillis;
    TtlCache(Duration ttl){ this.ttlMillis = ttl.toMillis(); }
    Optional<V> get(K k) {
        var e = map.get(k);
        if (e == null || e.exp < System.currentTimeMillis()) { map.remove(k); return Optional.empty(); }
        return Optional.of(e.v);
    }
    void put(K k, V v) { map.put(k, new Entry<>(v, System.currentTimeMillis()+ttlMillis)); }
}

// ---------- Enricher ----------
final class ContentEnricher {
    private final CustomerLookup customers;
    private final ProductLookup products;
    private final ExecutorService pool;
    private final Duration timeoutCustomer;
    private final Duration timeoutProduct;
    private final TtlCache<String, CustomerProfile> customerCache;
    private final TtlCache<String, ProductSnapshot> productCache;

    ContentEnricher(CustomerLookup customers, ProductLookup products,
                    Duration timeoutCustomer, Duration timeoutProduct,
                    Duration cacheTtl, int threads) {
        this.customers = customers;
        this.products = products;
        this.timeoutCustomer = timeoutCustomer;
        this.timeoutProduct = timeoutProduct;
        this.pool = Executors.newFixedThreadPool(threads);
        this.customerCache = new TtlCache<>(cacheTtl);
        this.productCache  = new TtlCache<>(cacheTtl);
    }

    public EnrichedOrder enrich(OrderPlaced in) throws Exception {
        Map<String,String> meta = new HashMap<>();
        meta.put("X-Enriched-By", "ContentEnricher/1.0");

        // --- Required: customer profile (fail if absent or timeout) ---
        CustomerProfile customer = fetchWithCache(
                in.customerId(),
                customerCache,
                customers::get,
                timeoutCustomer,
                "customer"
        ).orElseThrow(() -> new IllegalStateException("customer not found: " + in.customerId()));

        // --- Optional: product snapshots (parallel, best-effort) ---
        List<CompletableFuture<EnrichedOrder.Line>> futures = new ArrayList<>();
        for (OrderPlaced.Line line : in.lines()) {
            futures.add(CompletableFuture.supplyAsync(() -> {
                try {
                    ProductSnapshot p = fetchWithCache(
                            line.sku(),
                            productCache,
                            products::get,
                            timeoutProduct,
                            "product"
                    ).orElseGet(() -> {
                        // fallback minimal snapshot
                        meta.put("X-Enrichment-Miss-" + line.sku(), "product_lookup_failed");
                        return new ProductSnapshot(line.sku(), "(unknown)", "(unknown)");
                    });
                    return new EnrichedOrder.Line(line.sku(), line.qty(), p);
                } catch (Exception e) {
                    meta.put("X-Enrichment-Error-" + line.sku(), e.getClass().getSimpleName());
                    return new EnrichedOrder.Line(line.sku(), line.qty(), new ProductSnapshot(line.sku(), "(error)", "(error)"));
                }
            }, pool));
        }
        List<EnrichedOrder.Line> enrichedLines = new ArrayList<>();
        for (var f : futures) enrichedLines.add(f.get(timeoutProduct.toMillis(), TimeUnit.MILLISECONDS));

        return new EnrichedOrder(in.orderId(), customer, enrichedLines, in.currency(), meta);
    }

    private <K,V> Optional<V> fetchWithCache(K key,
                                             TtlCache<K,V> cache,
                                             CheckedFunction<K,Optional<V>> fetcher,
                                             Duration timeout,
                                             String sourceName) throws Exception {
        var cached = cache.get(key);
        if (cached.isPresent()) return cached;

        CompletableFuture<Optional<V>> fut = CompletableFuture.supplyAsync(() -> {
            try { return fetcher.apply(key); }
            catch (Exception e) { throw new CompletionException(e); }
        }, pool);

        try {
            Optional<V> v = fut.get(timeout.toMillis(), TimeUnit.MILLISECONDS);
            v.ifPresent(val -> cache.put(key, val));
            return v;
        } catch (TimeoutException te) {
            fut.cancel(true);
            return Optional.empty(); // treat timeout as miss; caller decides required/optional
        }
    }

    interface CheckedFunction<K,V> { V apply(K k) throws Exception; }

    public void shutdown() { pool.shutdownNow(); }
}
```

### Example wiring (dummy lookups)

```java
// Stub lookups (replace with HTTP/DB/gRPC clients with circuit breaker/timeouts)
CustomerLookup customers = id -> Optional.of(new CustomerProfile(id, "Alice Example", "GOLD"));
ProductLookup products  = sku -> Optional.of(new ProductSnapshot(sku, "Fancy "+sku, "ACCESSORIES"));

var enricher = new ContentEnricher(customers, products,
        Duration.ofMillis(300), Duration.ofMillis(200),
        Duration.ofSeconds(30), 8);

var msg = new OrderPlaced("o-123", "c-999", List.of(new OrderPlaced.Line("SKU-1", 2),
                                                    new OrderPlaced.Line("SKU-2", 1)), "EUR");
EnrichedOrder out = enricher.enrich(msg);
// forward `out` to next stage (serializer omitted)
```

**Notes**

-   The code demonstrates: required vs optional enrichment, **TTL cache**, **parallel lookups**, and **timeouts**.
    
-   In production: add **circuit breaker**, **retry with backoff**, structured **metrics**, and **PII controls**.
    

---

## Known Uses

-   **E-commerce:** Add product names, images, tax rates to order/cart events.
    
-   **Marketing/CRM:** Attach customer segment, consent status, locale to events.
    
-   **Logistics:** Enrich shipments with carrier SLAs, route metadata, geocodes.
    
-   **Payments:** Append BIN/risk scores, currency decimals.
    
-   **Analytics pipelines:** Map IDs to dimensions via dictionary/feature store.
    

---

## Related Patterns

-   **Content Filter:** Remove or mask fields after enrichment when forwarding to constrained consumers.
    
-   **Content-Based Router:** Route based on enriched attributes (e.g., premium tier).
    
-   **Normalizer / Canonical Data Model:** Transform enriched fields to a canonical representation.
    
-   **Cache-Aside / Read-Through Cache:** Techniques commonly used inside an enricher.
    
-   **Circuit Breaker / Bulkhead / Timeout:** Resilience patterns for external lookups.
    
-   **Claim Check:** Externalize large blobs referenced by enrichment to keep messages small.
    
-   **Message Translator:** If enrichment requires format conversion in addition to lookup.
    

---

