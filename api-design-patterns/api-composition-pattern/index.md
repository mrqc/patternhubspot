# API Composite — Design Pattern

## Pattern Name and Classification

**API Composition** — *Integration / Query-side aggregation* pattern for microservices and distributed systems.

---

## Intent

Aggregate data from multiple services into a single response by orchestrating calls in a **composition layer**, keeping clients simple and avoiding chatty, cross-service calls from the UI.

---

## Also Known As

-   **Aggregator / Composite View**
    
-   **Query Aggregator**
    
-   (Often implemented inside an **API Gateway** or **BFF**)
    

---

## Motivation (Forces)

-   Data is **owned by different services** (Orders, Payments, Shipping).
    
-   UI needs a **single view** (e.g., “Order Details”) with **low latency**.
    
-   Clients should **not** know internal service topology.
    
-   Need to handle **partial failures**, **timeouts**, **retries**, **versioning**, **caching**, and **back-pressure**.
    

---

## Applicability

Use when:

-   A request requires **read-only** data from **multiple bounded contexts**.
    
-   You want to **reduce client chattiness** and avoid tight coupling to service topology.
    
-   Composition logic changes **more often** than domain services (keep it outside domains).
    
-   You can tolerate **eventual consistency** for the composed view.
    

Avoid when:

-   You need **strong, cross-service transactions** for writes (consider Saga).
    
-   The composition layer would become a **hotspot** and bottleneck and you can move aggregation to the **client** or **precompute** materialized views.
    

---

## Structure

```less
[ Client ]
    |
    v
[ API Composition Layer ]  --parallel--> [ Order Service ]
            |                             [ Payment Service ]
            |                             [ Shipping Service ]
            +--concatenate / map / join--> [ ... more services ]
                       |
                       v
                Unified DTO
```

---

## Participants

-   **Client**: Calls the composite endpoint.
    
-   **Composition Layer**: Orchestrates downstream calls, merges results, enforces SLAs, caching, fallbacks.
    
-   **Downstream Services**: Own their data (e.g., Orders, Payments, Shipping).
    
-   **Cross-cutting**: Circuit breaker, retry, timeout, metrics, tracing.
    

---

## Collaboration

1.  Client calls `/orders/{id}/details`.
    
2.  Composition layer issues **parallel** requests to downstream services.
    
3.  Applies **joins/mapping** to produce a single DTO.
    
4.  Handles **partial failures** (fallbacks, null sections, degraded info).
    
5.  Returns **single response** to the client.
    

---

## Consequences

**Pros**

-   Simplifies clients; **one endpoint** per view.
    
-   Can **optimize** with parallelism, caching, shaping.
    
-   Encapsulates topology; supports **evolution** of backends.
    

**Cons**

-   Possible **single point of failure / bottleneck**.
    
-   Adds **operational complexity** (deploy, scale, observability).
    
-   Must carefully manage **timeouts**, **retries**, **fan-out**, **N+1** risks.
    
-   Risk of **business logic leakage** into the composition layer (keep it query/representation-focused).
    

---

## Implementation

**Key points**

-   Use **parallel requests** (e.g., `CompletableFuture`, Reactor).
    
-   Enforce **timeouts** per downstream call.
    
-   Add **resilience** (circuit breaker, retry with jitter, bulkheads).
    
-   Consider **caching** (per-view or per-fragment).
    
-   **Schema control**: version composite DTOs; avoid leaking internal models.
    
-   **Observability**: distributed tracing, metrics, logs with correlation IDs.
    

---

## Sample Code (Java, Spring Boot + WebClient + CompletableFuture)

> Minimal example showing a composition endpoint that aggregates **Order**, **Payment**, and **Shipment**.

```java
// build.gradle (snippets)
// implementation "org.springframework.boot:spring-boot-starter-webflux"
// implementation "io.github.resilience4j:resilience4j-spring-boot3"
// implementation "com.fasterxml.jackson.core:jackson-databind"
```

```java
// DTOs
record OrderDto(String orderId, String status, List<String> items) {}
record PaymentDto(String orderId, String state, String method) {}
record ShipmentDto(String orderId, String carrier, String tracking) {}

record OrderDetailsView(
        String orderId,
        String status,
        List<String> items,
        String paymentState,
        String paymentMethod,
        String carrier,
        String tracking
) {}
```

```java
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.netty.http.client.HttpClient;

import java.time.Duration;
import java.util.List;
import java.util.concurrent.*;

@Component
class DownstreamClients {

    private final WebClient orders;
    private final WebClient payments;
    private final WebClient shipping;
    private final ExecutorService pool =
            Executors.newFixedThreadPool(Math.max(4, Runtime.getRuntime().availableProcessors()));

    DownstreamClients() {
        HttpClient http = HttpClient.create().responseTimeout(Duration.ofSeconds(2));
        this.orders = WebClient.builder()
                .baseUrl("http://orders:8080")
                .clientConnector(new ReactorClientHttpConnector(http))
                .build();
        this.payments = WebClient.builder()
                .baseUrl("http://payments:8080")
                .clientConnector(new ReactorClientHttpConnector(http))
                .build();
        this.shipping = WebClient.builder()
                .baseUrl("http://shipping:8080")
                .clientConnector(new ReactorClientHttpConnector(http))
                .build();
    }

    CompletableFuture<OrderDto> getOrder(String id) {
        return CompletableFuture.supplyAsync(() ->
                orders.get().uri("/orders/{id}", id)
                        .retrieve().bodyToMono(OrderDto.class)
                        .block(Duration.ofSeconds(2)), pool);
    }

    CompletableFuture<PaymentDto> getPayment(String id) {
        return CompletableFuture.supplyAsync(() ->
                payments.get().uri("/payments/by-order/{id}", id)
                        .retrieve().bodyToMono(PaymentDto.class)
                        .block(Duration.ofSeconds(2)), pool);
    }

    CompletableFuture<ShipmentDto> getShipment(String id) {
        return CompletableFuture.supplyAsync(() ->
                shipping.get().uri("/shipments/by-order/{id}", id)
                        .retrieve().bodyToMono(ShipmentDto.class)
                        .block(Duration.ofSeconds(2)), pool);
    }
}
```

```java
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import org.springframework.stereotype.Service;

import java.util.concurrent.CompletableFuture;

@Service
class OrderDetailsCompositionService {

    private final DownstreamClients clients;

    OrderDetailsCompositionService(DownstreamClients clients) {
        this.clients = clients;
    }

    @CircuitBreaker(name = "composition", fallbackMethod = "fallback")
    public OrderDetailsView compose(String orderId) {
        CompletableFuture<?> all = CompletableFuture.allOf(
                clients.getOrder(orderId),
                clients.getPayment(orderId),
                clients.getShipment(orderId)
        );

        try {
            all.orTimeout(3, java.util.concurrent.TimeUnit.SECONDS).join();

            OrderDto o = clients.getOrder(orderId).join();
            PaymentDto p = clients.getPayment(orderId).join();
            ShipmentDto s = clients.getShipment(orderId).join();

            return new OrderDetailsView(
                    o.orderId(), o.status(), o.items(),
                    p != null ? p.state()   : "UNKNOWN",
                    p != null ? p.method()  : null,
                    s != null ? s.carrier() : null,
                    s != null ? s.tracking(): null
            );
        } catch (Exception e) {
            // escalate to fallback
            throw new RuntimeException("composition failure", e);
        }
    }

    // Fallback returns a degraded but still useful view
    OrderDetailsView fallback(String orderId, Throwable t) {
        return new OrderDetailsView(orderId, "UNKNOWN", List.of(),
                "UNKNOWN", null, null, null);
    }
}
```

```java
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api")
class CompositionController {

    private final OrderDetailsCompositionService service;

    CompositionController(OrderDetailsCompositionService service) {
        this.service = service;
    }

    @GetMapping("/orders/{id}/details")
    public OrderDetailsView get(@PathVariable String id) {
        return service.compose(id);
    }
}
```

**Notes**

-   Calls are executed **in parallel** using `CompletableFuture`.
    
-   Per-call timeouts and a **circuit breaker** guard the fan-out.
    
-   The fallback returns a **degraded** view if dependencies fail.
    
-   In production add **request hedging**, **bulkheads** (separate pools), **caching**, and **tracing** headers.
    

---

## Known Uses

-   **BFFs** aggregating microservice data for a specific UI.
    
-   **API Gateways** providing “view endpoints” (e.g., `/profile`, `/order-details`).
    
-   **GraphQL** resolvers composing fields from multiple backends.
    
-   Marketplaces, travel portals, retail apps that build **composite product views**.
    

---

## Related Patterns

-   **API Gateway / BFF** — often the host for composition.
    
-   **CQRS** — composition commonly used on the **query** side; complements **materialized views**.
    
-   **Event Sourcing / Event-Carried State Transfer** — alternative: precompute views rather than compose on request.
    
-   **Aggregator Microservice vs. In-Gateway Composition** — placement decision.
    
-   **Circuit Breaker, Bulkhead, Retry, Timeout** — resilience companions.
    
-   **Transactional Outbox / CDC** — ensure upstream data changes reliably propagate to projections you might cache.
