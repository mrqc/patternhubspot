# API Gateway — Design Pattern

## Pattern Name and Classification

**API Gateway** — *Edge / Integration / Façade* pattern for microservices and distributed systems.

---

## Intent

Provide a **single entry point** for clients that **routes, aggregates, transforms, secures, and governs** traffic to many backend services. It hides service topology, centralizes cross-cutting concerns, and shapes APIs for different clients.

---

## Also Known As

-   **Edge Server**

-   **API Façade**

-   **Reverse Proxy for Microservices**

-   (When tailored to one UI) **Backend-for-Frontend (BFF)**


---

## Motivation (Forces)

-   Clients shouldn’t know or track **service discovery**, ports, or versions.

-   Need to **enforce policies**: authn/z, TLS termination, rate limits, quotas.

-   Desire to **aggregate**/compose responses to reduce chattiness.

-   Need for **observability** (tracing, correlation IDs) and **resilience** (circuit breakers).

-   Mobile/web clients may need **protocol translation** (HTTP ↔ gRPC), **payload shaping**, **compression**.


---

## Applicability

Use when:

-   You have **multiple microservices** and want a **single, stable endpoint**.

-   Cross-cutting concerns (auth, throttling, caching) must be **uniform**.

-   You need **request/response transformation** or **aggregation** at the edge.

-   You require **per-client** APIs (BFFs).


Avoid or minimize when:

-   A gateway risks becoming a **bottleneck/monolith at the edge**.

-   Ultra-low latency paths are needed (consider **service mesh + direct calls**).

-   The gateway begins to host **domain logic** (smell).


---

## Structure

```lua
+-----------+
Client --->| API Gateway|---(route)----> Service A
           +-----------+---(route)----> Service B
                 |  \----(compose)----> Service C + D
                 |-- auth, rate limit, transform, cache, tracing
```

---

## Participants

-   **Client**: Mobile, web, partner, machine client.

-   **API Gateway**: Routes, filters, aggregates, enforces policies, exposes products/versions.

-   **Service Registry** (optional): Eureka/Consul for discovery.

-   **Policy Backends**: Identity Provider (OIDC/OAuth2), rate limiting store (Redis), cache (CDN/Redis).

-   **Downstream Services**: Independently deployed microservices.


---

## Collaboration

1.  Client sends request to **Gateway**.

2.  Gateway authenticates (JWT/OIDC), authorizes (scopes/roles), applies **filters** (transform, validate).

3.  Gateway resolves **route** (by path/host/header), optionally calls multiple services, aggregates results.

4.  Gateway enforces **resilience** (CB/timeout/retry), **rate limits**, **observability**.

5.  Gateway returns response to client.


---

## Consequences

**Pros**

-   Single, stable endpoint; **hides topology**.

-   Centralized **security**, **governance**, **SLA** enforcement.

-   **Performance**: caching, compression, request coalescing, aggregation.

-   **Evolution**: versioning and canary at the edge.


**Cons**

-   Possible **single point of failure** / **scaling hotspot**.

-   Risk of **edge monolith** if it accumulates business logic.

-   Additional **operational** component; must scale horizontally.

-   Needs careful **policy/version** management to avoid churn.


---

## Implementation

**Key Practices**

-   **Stateless** gateway replicas; externalize state (tokens, counters, cache).

-   **Zero trust**: validate JWT, enforce scopes/claims per route.

-   **Resilience**: per-route **timeouts**, **retries with jitter**, **circuit breakers**, **bulkheads**.

-   **Rate limiting**: token bucket in Redis; per API key/client.

-   **Observability**: correlation ID propagation (`X-Request-ID`), OpenTelemetry tracing.

-   **Transformations**: header/body rewrite, protocol bridging (HTTP↔gRPC), response shaping.

-   **Blue/green & canary**: route weights or header-based routing.

-   Keep **domain logic out**; only orchestration/edge policies.


---

## Sample Code (Java, Spring Cloud Gateway)

> Shows routes, JWT validation, circuit breaker, rate limiting, header propagation, and a tiny composition endpoint for an “order-details” view.

**Dependencies (Gradle snippets)**

```gradle
implementation "org.springframework.boot:spring-boot-starter-webflux"
implementation "org.springframework.cloud:spring-cloud-starter-gateway"
implementation "org.springframework.cloud:spring-cloud-starter-circuitbreaker-reactor-resilience4j"
implementation "org.springframework.boot:spring-boot-starter-oauth2-resource-server"
implementation "org.springframework.boot:spring-boot-starter-actuator"
implementation "org.springframework.boot:spring-boot-starter-data-redis-reactive"
```

**application.yml**

```yaml
spring:
  cloud:
    gateway:
      default-filters:
        - RemoveRequestHeader=Cookie
        - SaveSession
        - AddResponseHeader=X-Gateway, api-gw
      routes:
        - id: orders
          uri: http://orders:8080
          predicates:
            - Path=/api/orders/** 
          filters:
            - StripPrefix=1
            - CircuitBreaker=name=ordersCB, fallbackUri=forward:/__fallback/orders
            - RequestRateLimiter=redis-rate-limiter(10,20) # replenish=10/s, burst=20
            - Retry=5,series=SERVER_ERROR,methods=GET,backoff=firstBackoff=50ms,maxBackoff=1s
        - id: payments
          uri: http://payments:8080
          predicates:
            - Path=/api/payments/**
          filters:
            - StripPrefix=1
            - CircuitBreaker=name=paymentsCB, fallbackUri=forward:/__fallback/payments
        - id: shipping
          uri: http://shipping:8081
          predicates:
            - Path=/api/shipping/**
          filters:
            - StripPrefix=1
        # Composition/BFF route exposed by a small handler inside the gateway:
        - id: order-details-composite
          uri: http://localhost:8085   # will be handled internally via forward
          predicates:
            - Path=/api/orders/*/details
          filters:
            - PreserveHostHeader
            - RemoveResponseHeader=Server
            - SetPath=/__compose/orderDetails
  security:
    oauth2:
      resourceserver:
        jwt:
          jwk-set-uri: https://idp.example.com/.well-known/jwks.json

# Redis for rate limiter
spring:
  data:
    redis:
      host: redis
      port: 6379
```

**JWT + Correlation Filter**

```java
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import reactor.core.publisher.Mono;
import java.util.UUID;

@Component
class CorrelationAndAuthFilter implements GlobalFilter, Ordered {
    @Override public int getOrder() { return -10; } // early

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, org.springframework.cloud.gateway.filter.GatewayFilterChain chain) {
        ServerHttpRequest req = exchange.getRequest();
        String cid = req.getHeaders().getFirst("X-Request-Id");
        if (cid == null || cid.isBlank()) {
            cid = UUID.randomUUID().toString();
            exchange.getResponse().getHeaders().add("X-Request-Id", cid);
            exchange.mutate().request(req.mutate().header("X-Request-Id", cid).build()).build();
        }
        // JWT validation is handled by Spring Security (resource server); scopes checked per route via config or WebFlux Security.
        return chain.filter(exchange);
    }
}
```

**Route Config in Java (alternative to YAML)**

```java
import org.springframework.cloud.gateway.route.RouteLocator;
import org.springframework.cloud.gateway.route.builder.RouteLocatorBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
class GatewayRoutes {
    @Bean
    RouteLocator customRoutes(RouteLocatorBuilder rlb) {
        return rlb.routes()
            .route("orders", r -> r.path("/api/orders/**")
                .filters(f -> f.stripPrefix(1)
                               .circuitBreaker(c -> c.setName("ordersCB").setFallbackUri("forward:/__fallback/orders"))
                               .requestRateLimiter(rl -> rl.setRateLimiter(redis -> {})))
                .uri("http://orders:8080"))
            .build();
    }
}
```

**Simple Fallback + Composition Handler (inside gateway)**

```java
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.server.*;
import reactor.core.publisher.Mono;

record OrderDto(String orderId, String status) {}
record PaymentDto(String orderId, String state) {}
record ShipmentDto(String orderId, String tracking) {}
record OrderDetailsView(String orderId, String status, String payment, String tracking) {}

@Component
class CompositionHandler {

    private final WebClient orders = WebClient.create("http://orders:8080");
    private final WebClient payments = WebClient.create("http://payments:8080");
    private final WebClient shipping = WebClient.create("http://shipping:8081");

    public RouterFunction<ServerResponse> routes() {
        return RouterFunctions
            .route(RequestPredicates.GET("/__compose/orderDetails"), this::orderDetails)
            .andRoute(RequestPredicates.GET("/__fallback/{svc}"), this::fallback);
    }

    Mono<ServerResponse> orderDetails(ServerRequest req) {
        String path = req.exchange().getRequest().getPath().value(); // /api/orders/{id}/details → routed to here
        String id = path.split("/")[3];

        Mono<OrderDto> o = orders.get().uri("/orders/{id}", id).retrieve().bodyToMono(OrderDto.class);
        Mono<PaymentDto> p = payments.get().uri("/payments/by-order/{id}", id).retrieve().bodyToMono(PaymentDto.class)
                .onErrorResume(e -> Mono.just(new PaymentDto(id, "UNKNOWN")));
        Mono<ShipmentDto> s = shipping.get().uri("/shipments/by-order/{id}", id).retrieve().bodyToMono(ShipmentDto.class)
                .onErrorResume(e -> Mono.just(new ShipmentDto(id, null)));

        return Mono.zip(o, p, s)
            .map(t -> new OrderDetailsView(t.getT1().orderId(), t.getT1().status(), t.getT2().state(), t.getT3().tracking()))
            .flatMap(v -> ServerResponse.ok().contentType(MediaType.APPLICATION_JSON).bodyValue(v));
    }

    Mono<ServerResponse> fallback(ServerRequest req) {
        String svc = req.pathVariable("svc");
        return ServerResponse.ok().contentType(MediaType.APPLICATION_JSON)
                .bodyValue("{\"service\":\"" + svc + "\",\"status\":\"degraded\"}");
    }
}
```

**Security (WebFlux)**

```java
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.web.server.ServerHttpSecurity;
import org.springframework.security.web.server.SecurityWebFilterChain;

@Configuration
class SecurityConfig {
    @Bean
    SecurityWebFilterChain springSecurityFilterChain(ServerHttpSecurity http) {
        return http
            .csrf(ServerHttpSecurity.CsrfSpec::disable)
            .authorizeExchange(ex -> ex
                .pathMatchers("/actuator/**").permitAll()
                .pathMatchers("/api/**").hasAuthority("SCOPE_read")
                .anyExchange().authenticated())
            .oauth2ResourceServer(oauth -> oauth.jwt())
            .build();
    }
}
```

**Notes**

-   Run multiple gateway instances behind a load balancer; enable **sticky-less** stateless scaling.

-   Use **Redis** for rate limits and **OpenTelemetry** for traces.

-   For high-throughput, prefer **Netty** (WebFlux) with **connection pooling** and **timeouts**.


---

## Known Uses

-   **Netflix Zuul / Spring Cloud Gateway** at many enterprises.

-   **Kong**, **NGINX**, **Apigee**, **AWS API Gateway**, **Azure API Management**, **Kubernetes Ingress** controllers serving as API gateways.

-   **BFFs** per channel (mobile/web) at companies like Spotify, Airbnb, etc.


---

## Related Patterns

-   **Backend-for-Frontend (BFF)** — per-client gateway with tailored APIs.

-   **API Composition** — often implemented inside the gateway for read views.

-   **Circuit Breaker, Bulkhead, Retry, Timeout** — resilience at the edge.

-   **Service Registry / Discovery** — dynamic routing to services.

-   **Service Mesh** — complementary; mesh manages **service-to-service** concerns while the gateway manages **client-to-edge**.

-   **Canary / Blue-Green Deployments** — routing strategies often configured in gateways.
