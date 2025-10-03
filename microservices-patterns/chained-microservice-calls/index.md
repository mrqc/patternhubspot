# Chained Microservice Calls — Microservice Pattern

## Pattern Name and Classification

**Name:** Chained Microservice Calls  
**Classification:** Microservices / API Composition & Integration / Synchronous Orchestration (request–response)

## Intent

Fulfill a client request by **sequentially (and optionally partially in parallel) invoking multiple microservices**, passing intermediate results along the chain until a final response is produced—while controlling **latency, failures, and coupling**.

## Also Known As

-   Synchronous Service Composition
    
-   Request Chain / Call Chain
    
-   API Composition (sync)
    
-   In-Process Orchestration
    

## Motivation (Forces)

-   **Reuse** existing capabilities across services to build richer endpoints without exposing internal topology to clients.
    
-   **Low-latency UX** when the caller needs an immediate combined result (checkout, detail page).
    
-   **Keep clients simple** (mobile/web) by moving orchestration server-side.
    

**Forces & trade-offs**

-   **Latency multiplication:** end-to-end p95 ≈ sum of hop budgets (+ variance).
    
-   **Fragility:** each hop adds a failure mode; retries can amplify load.
    
-   **Tight coupling & hidden dependencies:** deep chains become hard to reason about and evolve.
    
-   **Fan-out explosion:** N items × M downstreams → N×M calls (beware N+1).
    
-   **Observability & stickiness:** must propagate correlation IDs and stick to one version/region where needed.
    

## Applicability

Use **Chained Microservice Calls** when:

-   You need a **synchronous** composite response within an SLA (e.g., ≤300–800 ms).
    
-   The chain is **short and intentional** (typically 2–3 hops), with well-known dependencies.
    
-   Intermediate results are needed to form downstream requests (true “chain,” not pure fan-out).
    

Prefer alternatives when:

-   Flows are long-running or span minutes → **Sagas / orchestration** with asynchronous events.
    
-   Composition is broad fan-out with caching/denormalization → **Read models / materialized views**.
    
-   Many client-specific views → **BFF** (Backend for Frontend) or **API Gateway** aggregation.
    

## Structure

-   **Entry Service (Composer):** Receives the request, owns the end-to-end budget.
    
-   **Downstream Services:** Provide steps in the chain (A → B → C). Some branches can run **in parallel** and later **join**.
    
-   **Resilience Layer:** Timeouts, retries with jitter, bulkheads, circuit breakers.
    
-   **Observability:** Correlation/trace IDs, per-hop metrics, logs.
    

```bash
Client → [Service X: Entry]
              │
              ├─▶ calls A (auth/profile) ──▶
              │            │
              │            └─▶ calls B (pricing) ──▶
              │
              └─▶ (in parallel) calls C (inventory)
                         │
                     join/compose ──▶ Response
```

## Participants

-   **Caller / Client** – initiates the composite request.
    
-   **Entry/Composing Service** – orchestrates the chain; enforces budgets/policies.
    
-   **Downstream Services (A, B, C)** – provide specialized capabilities.
    
-   **Resilience/Networking Layer** – HTTP/gRPC clients with limits, retries, CBs.
    
-   **Telemetry Stack** – tracing, metrics, logs with correlation IDs.
    

## Collaboration

1.  Entry service receives a request and **creates/propagates** a correlation ID.
    
2.  It calls **Service A**; its result is used to call **Service B** (true chaining).
    
3.  In parallel, it may call **Service C** (branch) and later **join** results.
    
4.  Each hop uses **timeouts, limited retries with jitter**, and **bulkheads** to avoid cascades.
    
5.  The entry service **composes** a final DTO and returns it.
    

## Consequences

**Benefits**

-   Hides internal topology from clients; supports reuse.
    
-   Enables **server-side** optimization and caching.
    
-   Predictable **synchronous** UX when latencies are controlled.
    

**Liabilities**

-   **Higher tail latency** and more failure modes; needs strong guardrails.
    
-   Can become a **distributed monolith** if chains grow deep or implicit.
    
-   Increases **operational coupling** (versioning, contract drift).
    
-   Risk of **retry storms** and **N+1** patterns without batching/caching.
    

## Implementation

**Key practices**

-   **Keep chains shallow** (≤3 hops); prefer parallel fan-out + join to long serial chains.
    
-   **Budget per hop:** e.g., 300 ms total → A:100 ms, B:120 ms, C:80 ms. Enforce with **timeouts**.
    
-   **Retries:** only for transient errors, with **exponential backoff + jitter**; cap attempts.
    
-   **Bulkheads:** separate concurrency pools per dependency; bound queues.
    
-   **Circuit breakers:** trip fast on persistent faults; provide fallbacks/partial responses.
    
-   **Batch & cache:** avoid N+1; coalesce requests, use read-through caches where legal.
    
-   **Propagate context:** `X-Correlation-Id`, auth, locale/tenant; standardize headers.
    
-   **Idempotency:** especially if chaining includes writes (prefer GET/side-effect-free).
    
-   **Observability:** per-hop metrics (success, latency, error), distributed tracing, logs with IDs.
    
-   **Data contracts:** use versioned DTOs; avoid leaking one BC’s model into another (consider ACLs).
    

---

## Sample Code (Java, Spring Boot WebFlux)

**Goal:** `/api/order-view/{orderId}` composes an order view by *chaining* calls:

1.  **Auth/Profile** → identifies user & tier
    
2.  **Pricing** → price items (needs user tier)
    
3.  **Inventory** (parallel) → availability
    
4.  Compose response; include **timeouts, backoff+jitter retries**, **simple semaphore bulkheads**, and **correlation ID propagation**
    

> Dependencies (Gradle/Maven equivalents)
> 
> -   `spring-boot-starter-webflux`
>     

```java
// Application.java
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class ChainedCallsApp {
  public static void main(String[] args) { SpringApplication.run(ChainedCallsApp.class, args); }
}
```

```java
// CorrelationFilter.java — ensure every request has an X-Correlation-Id and make it available
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.WebFilter;
import org.springframework.web.server.WebFilterChain;
import reactor.core.publisher.Mono;

import java.util.UUID;

@Component
class CorrelationFilter implements WebFilter {
  static final String HDR = "X-Correlation-Id";

  @Override public Mono<Void> filter(ServerWebExchange ex, WebFilterChain chain) {
    String cid = ex.getRequest().getHeaders().getFirst(HDR);
    if (cid == null || cid.isBlank()) cid = UUID.randomUUID().toString();
    ServerHttpRequest mutated = ex.getRequest().mutate().header(HDR, cid).build();
    return chain.filter(ex.mutate().request(mutated).build());
  }
}
```

```java
// Http.java — shared WebClient with correlation propagation + small helpers
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.*;
import reactor.core.publisher.Mono;
import reactor.util.retry.Retry;

import java.time.Duration;
import java.util.Random;
import java.util.concurrent.Semaphore;

@Component
class Http {
  private final WebClient client;
  private final Random rnd = new Random();

  Http(WebClient.Builder b) {
    this.client = b.filter((req, next) -> {
          // propagate correlation header if present
          ClientRequest cr = ClientRequest.from(req)
              .headers(h -> {
                if (!h.containsKey(CorrelationFilter.HDR) && req.headers().asHttpHeaders().containsKey(CorrelationFilter.HDR)) {
                  h.set(CorrelationFilter.HDR, req.headers().asHttpHeaders().getFirst(CorrelationFilter.HDR));
                }
              }).build();
          return next.exchange(cr);
        })
        .build();
  }

  // Basic transient-retry policy: backoff with jitter, capped attempts
  Retry retryBackoff(int attempts, Duration base, Duration max) {
    return Retry.backoff(attempts, base)
        .maxBackoff(max)
        .jitter(0.5)
        .filter(this::isTransient);
  }
  private boolean isTransient(Throwable t) {
    return t instanceof WebClientResponseException.ServiceUnavailable
        || t instanceof WebClientRequestException
        || t instanceof java.net.SocketTimeoutException;
  }

  WebClient client() { return client; }

  // Tiny semaphore bulkhead wrapper for a Mono
  <T> Mono<T> bulkhead(Mono<T> mono, Semaphore sem) {
    return Mono.defer(() -> {
      if (!sem.tryAcquire()) return Mono.error(new BulkheadFull("bulkhead full"));
      return mono.doFinally(s -> sem.release());
    });
  }

  static class BulkheadFull extends RuntimeException { BulkheadFull(String m){ super(m);} }
}
```

```java
// DTOs (records for brevity)
import java.util.List;

record OrderItem(String sku, int qty) {}
record Order(String orderId, String userId, List<OrderItem> items) {}
record UserProfile(String userId, String tier) {}
record PricedItem(String sku, int qty, long unitMinor, long lineMinor, String currency) {}
record PricingResult(List<PricedItem> items, long totalMinor, String currency) {}
record Stock(String sku, boolean available, int availableQty) {}
record InventoryResult(List<Stock> items) {}
record OrderView(String orderId, String userId, String tier,
                 List<PricedItem> priced, long totalMinor, String currency,
                 InventoryResult inventory, boolean degraded) {}
```

```java
// Downstream clients (A: Profile, B: Pricing, C: Inventory)
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.List;
import java.util.concurrent.Semaphore;

@Component
class ProfileClient {
  private final WebClient http;
  private final Http helper;
  private final Semaphore sem = new Semaphore(32, true); // bulkhead

  ProfileClient(@Value("${svc.profile:http://profile:8080}") String base, Http helper) {
    this.http = helper.client().mutate().baseUrl(base).build(); this.helper = helper;
  }

  Mono<UserProfile> getProfile(String userId) {
    Mono<UserProfile> call = http.get().uri("/api/users/{id}", userId)
        .retrieve().bodyToMono(UserProfile.class)
        .timeout(Duration.ofMillis(120));
    return helper.bulkhead(call, sem).retryWhen(helper.retryBackoff(2, Duration.ofMillis(50), Duration.ofMillis(200)));
  }
}

@Component
class PricingClient {
  private final WebClient http;
  private final Http helper;
  private final Semaphore sem = new Semaphore(64, true);

  PricingClient(@Value("${svc.pricing:http://pricing:8080}") String base, Http helper) {
    this.http = helper.client().mutate().baseUrl(base).build(); this.helper = helper;
  }

  Mono<PricingResult> price(String userTier, List<OrderItem> items) {
    Mono<PricingResult> call = http.post().uri("/api/price?tier={t}", userTier)
        .bodyValue(items).retrieve().bodyToMono(PricingResult.class)
        .timeout(Duration.ofMillis(150));
    return helper.bulkhead(call, sem).retryWhen(helper.retryBackoff(2, Duration.ofMillis(50), Duration.ofMillis(250)));
  }
}

@Component
class InventoryClient {
  private final WebClient http;
  private final Http helper;
  private final Semaphore sem = new Semaphore(32, true);

  InventoryClient(@Value("${svc.inventory:http://inventory:8080}") String base, Http helper) {
    this.http = helper.client().mutate().baseUrl(base).build(); this.helper = helper;
  }

  Mono<InventoryResult> check(List<OrderItem> items) {
    Mono<InventoryResult> call = http.post().uri("/api/availability")
        .bodyValue(items).retrieve().bodyToMono(InventoryResult.class)
        .timeout(Duration.ofMillis(100));
    return helper.bulkhead(call, sem).retryWhen(helper.retryBackoff(2, Duration.ofMillis(30), Duration.ofMillis(150)));
  }
}
```

```java
// OrderService — entry that CHAINs calls: Profile -> Pricing, and in parallel Inventory
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.concurrent.Semaphore;

@Service
class OrderComposer {
  private final WebClient orders;
  private final Http helper;
  private final ProfileClient profile;
  private final PricingClient pricing;
  private final InventoryClient inventory;
  private final Semaphore ordersSem = new Semaphore(32, true);

  OrderComposer(@Value("${svc.orders:http://orders:8080}") String base,
                Http helper, ProfileClient profile, PricingClient pricing, InventoryClient inventory) {
    this.orders = helper.client().mutate().baseUrl(base).build();
    this.helper = helper; this.profile = profile; this.pricing = pricing; this.inventory = inventory;
  }

  Mono<OrderView> compose(String orderId) {
    // Step 0: load order (entry point)
    Mono<Order> orderMono = helper.bulkhead(
        orders.get().uri("/api/orders/{id}", orderId)
            .retrieve().bodyToMono(Order.class)
            .timeout(Duration.ofMillis(120)),
        ordersSem
    ).retryWhen(helper.retryBackoff(2, Duration.ofMillis(50), Duration.ofMillis(200)));

    return orderMono.flatMap(ord ->
        // Step 1 (A): profile (needed for Step 2)
        profile.getProfile(ord.userId())
          // Step 2 (B): pricing depends on profile.tier => true chain
          .flatMap(up -> pricing.price(up.tier(), ord.items())
              // Step 3 (C): inventory can run in parallel; start it earlier and zip when pricing done
              .zipWith(inventory.check(ord.items())
                        .onErrorReturn(new InventoryResult(ord.items().stream()
                                               .map(i -> new Stock(i.sku(), false, 0)).toList())))
              .map(tuple -> {
                PricingResult pr = tuple.getT1();
                InventoryResult inv = tuple.getT2();
                return new OrderView(
                    ord.orderId(), ord.userId(), up.tier(),
                    pr.items(), pr.totalMinor(), pr.currency(),
                    inv,
                    false
                );
              })
          )
    ).timeout(Duration.ofMillis(350))  // total budget
     .onErrorResume(ex ->
         // Degraded but useful response (e.g., cached/placeholder inventory)
         orderMono.map(ord -> new OrderView(ord.orderId(), ord.userId(), "unknown",
                 List.of(), 0, "EUR",
                 new InventoryResult(ord.items().stream().map(i -> new Stock(i.sku(), false, 0)).toList()),
                 true))
     );
  }
}
```

```java
// ApiController.java — expose the composed endpoint
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import reactor.core.publisher.Mono;

@RestController
@RequestMapping("/api")
class ApiController {
  private final OrderComposer composer;
  ApiController(OrderComposer composer) { this.composer = composer; }

  @GetMapping(value="/order-view/{orderId}", produces= MediaType.APPLICATION_JSON_VALUE)
  Mono<OrderView> get(@PathVariable String orderId) {
    return composer.compose(orderId);
  }
}
```

**What this demonstrates**

-   **True chain:** `Profile → Pricing` (pricing needs the profile tier).
    
-   **Branch & join:** `Inventory` runs in parallel and is joined before responding.
    
-   **Guardrails:** hop timeouts, **bounded retries with jitter**, **semaphore bulkheads**, end-to-end timeout, and a **degraded fallback**.
    
-   **Context propagation:** `X-Correlation-Id` added/forwarded automatically.
    

> In production, add: distributed tracing (OpenTelemetry), metrics (Micrometer), circuit breakers (e.g., Resilience4j), request collapsing/batching, caching, and stricter error classification.

---

## Known Uses

-   **Product detail / checkout** pages: user profile → personalized pricing → inventory → shipping quote.
    
-   **Travel search**: availability lookup → pricing → ancillaries; parts run in parallel, others chain.
    
-   **Payments**: risk score → 3-DS challenge → authorization (short, strict SLO chain).
    
-   **Streaming/media**: entitlement → catalog → popularity/ads personalization.
    

## Related Patterns

-   **Backend for Frontend (BFF):** Client-specific aggregation; often the *entry point* that performs chaining.
    
-   **API Gateway:** Edge routing & policy; may do light composition but should avoid deep chains.
    
-   **Saga / Orchestration:** Asynchronous, long-running multi-step processes (compensations).
    
-   **Bulkhead / Circuit Breaker / Timeout / Retry:** Resilience primitives essential for safe chaining.
    
-   **Caching / Read Models / CQRS:** Reduce synchronous fan-out by pre-composing data.
    
-   **Anti-Corruption Layer (ACL):** Prevent leaking one bounded context’s model across chains.

