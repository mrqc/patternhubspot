# Bulkhead — Microservice Pattern

## Pattern Name and Classification

**Name:** Bulkhead  
**Classification:** Microservices / Resilience & Fault Isolation / Resource Partitioning

## Intent

Prevent failures and latency spikes in one part of a system from **cascading** into others by **partitioning resources** (threads, connections, queues) per dependency, workload, or tenant—so each “compartment” can fail independently.

## Also Known As

-   Compartmentalization
    
-   Concurrency Isolation
    
-   Semaphore/Thread-Pool Isolation
    

## Motivation (Forces)

-   **Noisy neighbors:** One slow or failing downstream (DB, HTTP API) can exhaust shared threads/connections.
    
-   **Latency amplification:** Backpressure and queue buildup trigger timeouts and retries across the fleet.
    
-   **Multi-tenancy:** A single tenant’s burst should not degrade others.
    
-   **Predictability:** Fixed concurrency budgets per dependency yield stable tail latencies.
    

## Applicability

Use **Bulkhead** when:

-   Your service calls **multiple downstreams** with different SLOs/latency profiles.
    
-   You run **multi-tenant** or mixed-priority workloads.
    
-   You’ve seen thread/connection pool exhaustion or retry storms.
    

Avoid over-partitioning when:

-   Traffic is tiny and static (the complexity may not pay off).
    
-   Pools are too small to be efficient (context-switching/queueing overhead dominates).
    

## Structure

-   **Bulkhead Units:** Independent concurrency pools (threads or semaphores) per dependency/work type.
    
-   **Schedulers/Queues:** Optional bounded queues in front of each pool.
    
-   **Timeouts & Circuit Breakers:** Combine to fail fast instead of piling up.
    
-   **Backpressure Policy:** What to do when a bulkhead is saturated (reject, shed, degrade).
    

```less
[Incoming Requests]
                    |
         +----------+-----------+
         |                      |
 [Bulkhead: Payments]   [Bulkhead: Search]
  max 16 threads             max 8 threads
   + timeout + cb            + timeout + cb
         |                         |
   [Payments API]             [Search API]
```

## Participants

-   **Caller/Controller** — initiates work.
    
-   **Bulkhead** — concurrency guard (semaphore or thread-pool).
    
-   **Downstream Dependency** — service, DB, cache, external API.
    
-   **Fallback/Degrader** — optional alternate path on saturation.
    
-   **Metrics/Alerts** — saturation %, queue length, rejections.
    

## Collaboration

1.  Caller submits work tagged with a **bulkhead key** (e.g., `payments`).
    
2.  Bulkhead checks capacity:
    
    -   **Admit** if tokens/threads available → call downstream.
        
    -   **Else** apply policy (queue briefly, reject fast, or fallback).
        
3.  Completion releases capacity; metrics are recorded.
    
4.  Circuit breaker/timeouts trip if downstream misbehaves, reducing pressure further.
    

## Consequences

**Benefits**

-   Fault isolation; a failing dependency doesn't take down the whole service.
    
-   Controlled concurrency → stable p95/p99 latencies.
    
-   Clear SLO budgeting per dependency/tenant.
    

**Liabilities**

-   More pools/queues to size, monitor, and tune.
    
-   Potential under-utilization if partitions are too fine.
    
-   Added complexity in routing/fallback logic.
    

## Implementation

**Key practices**

-   **Pick isolation primitive:**
    
    -   *Semaphore*: cheap, in-caller-thread; rejects when saturated.
        
    -   *Thread pool*: isolates execution time and stack; can bound queue.
        
-   **Right-size pools:** Base on downstream parallelism and SLOs; use load tests.
    
-   **Bound everything:** Queue length, in-flight calls, timeouts, retries.
    
-   **Per-dependency pools:** e.g., `payments`, `search`, `email`; avoid one shared client pool.
    
-   **Combine with CB/Timeouts:** Fail fast under distress; avoid retry storms.
    
-   **Telemetry:** Expose `maxConcurrent`, `availablePermits`, `queueDepth`, `rejectedCount`, latency.
    

---

## Sample Code (Java)

Two approaches: **(A) Resilience4j Bulkhead (semaphore & thread-pool)** and **(B) lightweight custom semaphore bulkhead** around an HTTP client.

### A) Resilience4j — Programmatic setup (Spring Boot/WebClient)

```java
// build.gradle (or pom.xml):
// implementation 'org.springframework.boot:spring-boot-starter-webflux'
// implementation 'io.github.resilience4j:resilience4j-bulkhead'
// implementation 'io.github.resilience4j:resilience4j-timelimiter'
// implementation 'io.github.resilience4j:resilience4j-circuitbreaker'

import io.github.resilience4j.bulkhead.*;
import io.github.resilience4j.timelimiter.*;
import io.github.resilience4j.decorators.Decorators;
import reactor.core.publisher.Mono;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
import java.util.concurrent.*;

@Service
public class PaymentsClient {

    private final WebClient http = WebClient.builder().baseUrl("https://payments.example.com").build();

    // Semaphore-style bulkhead: limits concurrent in-flight calls, rejects excess immediately
    private final Bulkhead paymentsBh = Bulkhead.of("payments-bh",
            BulkheadConfig.custom()
                    .maxConcurrentCalls(16)
                    .maxWaitDuration(Duration.ofMillis(0)) // reject fast; or allow small wait
                    .fairCallHandlingStrategyEnabled(true)
                    .build());

    // Thread-pool bulkhead: isolates execution & latency with a bounded queue
    private final ThreadPoolBulkhead searchBh = ThreadPoolBulkhead.of("search-bh",
            ThreadPoolBulkheadConfig.custom()
                    .coreThreadPoolSize(8)
                    .maxThreadPoolSize(8)
                    .queueCapacity(32) // bounded
                    .build());

    private final TimeLimiter timeLimiter = TimeLimiter.of(
            TimeLimiterConfig.custom().timeoutDuration(Duration.ofSeconds(2)).build());

    public Mono<String> charge(String orderId, int cents) {
        // Compose policies: semaphore bulkhead + timeout
        Callable<String> task = () -> http.post()
                .uri("/v1/charge")
                .bodyValue("{\"orderId\":\""+orderId+"\",\"amount\":"+cents+"}")
                .retrieve()
                .bodyToMono(String.class)
                .timeout(Duration.ofSeconds(2))
                .block();

        Callable<String> guarded = Decorators.ofCallable(task)
                .withBulkhead(paymentsBh)
                .withTimeLimiter(timeLimiter, Executors.newSingleThreadExecutor())
                .decorate();

        return Mono.fromCallable(guarded)
                   .onErrorResume(BulkheadFullException.class, ex -> Mono.just("{\"status\":\"degraded\",\"reason\":\"bulkhead\"}"));
    }

    public Mono<String> search(String q) {
        Supplier<CompletionStage<String>> stage = () -> CompletableFuture.supplyAsync(() ->
                http.get().uri(uri -> uri.path("/v1/search").queryParam("q", q).build())
                    .retrieve().bodyToMono(String.class)
                    .timeout(Duration.ofSeconds(1))
                    .block()
        );

        Supplier<CompletionStage<String>> guarded = io.github.resilience4j.decorators.Decorators
                .ofSupplier(stage)
                .withThreadPoolBulkhead(searchBh)
                .decorate();

        return Mono.fromCompletionStage(guarded.get())
                   .onErrorResume(ex -> Mono.just("{\"items\":[],\"fallback\":true}"));
    }
}
```

**Notes**

-   `Bulkhead` (semaphore) caps **concurrent** calls; `ThreadPoolBulkhead` provides isolation with a **bounded queue**.
    
-   Combine with `TimeLimiter` and a circuit breaker for robust failure handling.
    
-   Use **different bulkheads per dependency** (`payments-bh`, `search-bh`, …).
    

### B) Lightweight Semaphore Bulkhead (framework-free)

```java
import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.concurrent.Semaphore;

public class SimpleBulkheadedHttp {
    private final HttpClient client = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(1)).build();

    // e.g., only 10 concurrent calls to the pricing API, no waiting
    private final Semaphore pricingSem = new Semaphore(10, true);

    public String getPrice(String sku) throws Exception {
        if (!pricingSem.tryAcquire()) {
            // fast fail on saturation
            return "{\"price\":null,\"fallback\":true,\"reason\":\"bulkhead\"}";
        }
        try {
            HttpRequest req = HttpRequest.newBuilder(
                    URI.create("https://pricing.example.com/v1/price?sku=" + sku))
                    .timeout(Duration.ofMillis(800))
                    .GET().build();
            HttpResponse<String> resp = client.send(req, HttpResponse.BodyHandlers.ofString());
            return resp.body();
        } finally {
            pricingSem.release();
        }
    }
}
```

**Tuning tips**

-   Start with **max concurrent = downstream parallelism** (cores/connections) and refine by load tests.
    
-   Prefer **reject-fast** over long waits to protect p99.
    
-   Expose metrics (permits available, rejections, queue depth) and alert on saturation > N% for M minutes.
    

---

## Known Uses

-   **Netflix / Hystrix heritage**: thread‐pool isolation per dependency to stop cascading failures.
    
-   **Payment gateways**: separate pools for bank APIs vs. internal ledgers.
    
-   **Search & recommendations**: isolate optional features so core checkout stays healthy.
    
-   **Multi-tenant SaaS**: per-tenant or per-plan bulkheads to enforce fair use.
    

## Related Patterns

-   **Circuit Breaker:** Trip on failure to reduce pressure; often wrapped around bulkheads.
    
-   **Timeouts & Retries (with jitter):** Bound latency and avoid retry storms.
    
-   **Rate Limiting / Token Bucket:** Control ingress before bulkheads.
    
-   **Backpressure / Queueing:** Pair with bounded queues and shed load.
    
-   **Fallback / Degradation:** Serve partial results when compartments saturate.
    
-   **Ambassador (Sidecar) & Service Mesh:** Enforce bulkhead-like limits at the proxy layer too.

