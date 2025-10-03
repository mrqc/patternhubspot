# API Gateway — Microservice Pattern

## Pattern Name and Classification

**Name:** API Gateway  
**Classification:** Microservices / Edge & Integration / Reverse Proxy, Aggregation, and Policy Enforcement

## Intent

Provide a **single entry point** for clients that **routes, aggregates, transforms, and governs** traffic to many backend services (north–south). Centralize cross-cutting concerns—**auth, TLS, rate limiting, request/response shaping, caching, observability**—so teams can evolve services independently and clients remain simple.

## Also Known As

-   Edge Service
    
-   Backend for Frontend (BFF) *(a specialization)*
    
-   Reverse Proxy with Policies
    
-   API Façade
    

## Motivation (Forces)

-   **Client simplicity:** Mobile/web clients would otherwise juggle many service endpoints, auth schemes, and payloads.
    
-   **Cross-cutting governance:** mTLS, OAuth/JWT, quotas, CORS, schema evolution, versioning, deprecation.
    
-   **Performance & UX:** Aggregate multiple service calls, cache hot resources, compress/transform payloads.
    
-   **Security:** Central choke point for WAF rules, bot mitigation, allow/deny lists, PII redaction.
    
-   **Change isolation:** Backends can refactor or split/merge without breaking clients.
    

**Tensions**

-   **Coupling at the edge:** Gateway can accumulate business logic—avoid becoming a “god service.”
    
-   **Latency:** Extra hop; aggregations can add tail latency if not designed carefully.
    
-   **Blast radius:** Misconfiguration affects all clients—needs robust testing and rollout controls.
    

## Applicability

Use an **API Gateway** when:

-   You expose **multiple microservices** to external clients.
    
-   You need **uniform policies** (authN/Z, TLS, throttling) and **consistent error handling**.
    
-   You want **aggregation** (one client call → multiple backend calls) or **protocol bridging** (HTTP ↔ gRPC, WebSocket, GraphQL).
    

Be cautious when:

-   All consumers are internal and a **service mesh** + **internal gateway** already covers your needs.
    
-   Ultra-low latency paths (e.g., trading) can’t afford the extra hop—consider fast-path bypass.
    

## Structure

-   **Edge (Gateway) Process:** Reverse proxy/router with filter chain (auth, rate limit, transform, obs).
    
-   **Policy Store / Control Plane:** Versioned route and policy config with progressive rollout.
    
-   **Backend Services:** Auth-agnostic, speak simple protocols to the gateway.
    
-   **Observability Stack:** Traces, metrics, logs, audit.
    
-   **(Optional) Aggregators/BFFs:** Gateway endpoints that call multiple services and compose responses.
    

```scss
[ Clients ] -> [ API Gateway: TLS + Auth + RL + CB + Routing + Xform ] -> [ Services A/B/C ]
                                      \----(Aggregate)----> [A] + [B] -> merged response
```

## Participants

-   **Client Applications** — mobile, web, partner systems.
    
-   **API Gateway** — central request/response pipeline.
    
-   **Policy/Config Source** — DB/files/CRDs delivering route & filter config.
    
-   **Backend Services** — domain microservices.
    
-   **Security/Observability** — IDP (OAuth/OIDC), metrics, tracing, SIEM.
    

## Collaboration

1.  Client sends request to the **Gateway** (TLS).
    
2.  Gateway **authenticates** (e.g., JWT, mTLS), **authorizes**, **rates limits**, and **routes**.
    
3.  Optional **transform/aggregate**: call multiple services, map versions, redact fields.
    
4.  Gateway **returns** a normalized response; emits **metrics/traces/logs**.
    
5.  Config changes propagate via **hot-reload/rollout** with health checks and canaries.
    

## Consequences

**Benefits**

-   Single, secure, well-governed ingress.
    
-   Faster client development via aggregation and stable contracts.
    
-   Centralized cross-cutting concerns; consistent errors/telemetry.
    
-   Easier versioning, deprecation, and A/B experiments.
    

**Liabilities**

-   Edge bottleneck and single point of failure if not **HA and horizontally scaled**.
    
-   Risk of business logic creep—keep orchestration thin; push domain logic to services or a BFF.
    
-   Requires disciplined **config/testing/policy** lifecycle and rollback.
    

## Implementation

**Key practices**

-   **Stateless & scalable:** Multi-instance gateway behind anycast/LB; externalize state (tokens, counters).
    
-   **Defense-in-depth:** mTLS, JWT validation, scopes/claims, WAF, IP allow/deny, schema validation.
    
-   **Resilience:** Timeouts, **exponential backoff + jitter** retries (where safe), circuit breakers, request hedging.
    
-   **Rate limiting & quotas:** Token bucket per API key/tenant; per-route concurrency caps.
    
-   **Transform & versioning:** Header/content negotiation, path rewrite, response shaping, deprecation headers.
    
-   **Observability:** Correlation IDs, OpenTelemetry spans, RED metrics, structured logs.
    
-   **Progressive delivery:** Blue/green or canary routing by % hash or header, shadow traffic.
    
-   **Caching:** Respect cache semantics; edge cache for GETs; ETags and gzip/brotli.
    
-   **Security hygiene:** Strip hop-by-hop headers; validate content length; limit payload size; sanitize error messages.
    

---

## Sample Code (Java, Spring Boot + Spring Cloud Gateway)

> Shows:
> 
> -   **Route config** with path predicates and filters (rewrite, circuit breaker, rate limiter).
>     
> -   **JWT auth** as a `GlobalFilter`.
>     
> -   A simple **aggregation endpoint** using `WebClient` to fan-out and compose a response.
>     
> -   Wire Redis (or in-memory) for rate limiting; replace placeholders in production.
>     

```java
// build.gradle (essentials)
// implementation 'org.springframework.boot:spring-boot-starter-webflux'
// implementation 'org.springframework.cloud:spring-cloud-starter-gateway'
// implementation 'io.github.resilience4j:resilience4j-spring-boot3'
// implementation 'org.springframework.boot:spring-boot-starter-actuator'
// implementation 'com.nimbusds:nimbus-jose-jwt:9.37'
// implementation 'org.springframework.boot:spring-boot-starter-data-redis-reactive'
```

```java
// Application.java
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class ApiGatewayApp {
  public static void main(String[] args) { SpringApplication.run(ApiGatewayApp.class, args); }
}
```

```java
// GatewayConfig.java
import org.springframework.cloud.gateway.route.*;
import org.springframework.cloud.gateway.route.builder.*;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.cloud.gateway.filter.ratelimit.RedisRateLimiter;

@Configuration
public class GatewayConfig {

  @Bean
  public RouteLocator routes(RouteLocatorBuilder rlb) {
    return rlb.routes()

      // v1 Catalog — rewrite and circuit break
      .route("catalog", r -> r.path("/api/v1/catalog/**")
        .and().method(HttpMethod.GET)
        .filters(f -> f.rewritePath("/api/v1/catalog/(?<segment>.*)", "/$\\{segment}")
                       .circuitBreaker(c -> c.setName("catalog-cb").setFallbackUri("forward:/__fallback/catalog")))
        .uri("http://catalog:8080"))

      // v1 Orders — rate limit per API key
      .route("orders", r -> r.path("/api/v1/orders/**")
        .filters(f -> f.rewritePath("/api/v1/orders/(?<segment>.*)", "/$\\{segment}")
                       .requestRateLimiter(c -> c.setRateLimiter(redisRateLimiter())
                                                 .setKeyResolver(new ApiKeyResolver())))
        .uri("http://orders:8080"))

      // Pass-through for inventory (POST with timeouts defined elsewhere)
      .route("inventory", r -> r.path("/api/v1/inventory/**")
        .uri("http://inventory:8080"))

      .build();
  }

  @Bean
  public RedisRateLimiter redisRateLimiter() {
    // replenishRate=10 req/s, burstCapacity=20
    return new RedisRateLimiter(10, 20);
  }
}
```

```java
// ApiKeyResolver.java — choose tenant key for rate limiting
import org.springframework.cloud.gateway.filter.ratelimit.KeyResolver;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

public class ApiKeyResolver implements KeyResolver {
  @Override public Mono<String> resolve(ServerWebExchange exchange) {
    String key = exchange.getRequest().getHeaders().getFirst("X-API-Key");
    if (key == null) key = exchange.getRequest().getRemoteAddress() == null ? "anon" :
            exchange.getRequest().getRemoteAddress().getAddress().getHostAddress();
    return Mono.just(key);
  }
}
```

```java
// JwtAuthFilter.java — lightweight JWT validation as a GlobalFilter
import com.nimbusds.jose.JWSObject;
import com.nimbusds.jose.crypto.MACVerifier;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

@Component
public class JwtAuthFilter implements GlobalFilter, Ordered {
  private static final String SECRET = System.getenv().getOrDefault("JWT_HS256_SECRET", "dev-secret-change-me");
  private static final String[] PUBLIC_PATHS = { "/actuator", "/__fallback", "/public" };

  @Override
  public Mono<Void> filter(ServerWebExchange exchange, org.springframework.cloud.gateway.filter.GatewayFilterChain chain) {
    String path = exchange.getRequest().getURI().getPath();
    for (String p : PUBLIC_PATHS) if (path.startsWith(p)) return chain.filter(exchange);

    String auth = exchange.getRequest().getHeaders().getFirst("Authorization");
    if (auth == null || !auth.startsWith("Bearer ")) {
      exchange.getResponse().setStatusCode(HttpStatus.UNAUTHORIZED);
      return exchange.getResponse().setComplete();
    }
    String jwt = auth.substring(7);
    try {
      JWSObject jws = JWSObject.parse(jwt);
      if (!jws.verify(new MACVerifier(SECRET.getBytes()))) throw new IllegalArgumentException("bad sig");
      // Example scope check
      String payload = jws.getPayload().toString();
      if (!payload.contains("\"scope\":\"api:read\"") && !path.startsWith("/api/v1/orders")) {
        exchange.getResponse().setStatusCode(HttpStatus.FORBIDDEN);
        return exchange.getResponse().setComplete();
      }
      // add user context header downstream
      return chain.filter(exchange.mutate(m -> m.request(
          exchange.getRequest().mutate().header("X-User", jws.getPayload().toJSONObject().getAsString("sub")).build()
      ).build()));
    } catch (Exception e) {
      exchange.getResponse().setStatusCode(HttpStatus.UNAUTHORIZED);
      return exchange.getResponse().setComplete();
    }
  }
  @Override public int getOrder() { return -100; } // run early
}
```

```java
// FallbackController.java — circuit breaker fallback
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import reactor.core.publisher.Mono;
import java.util.Map;

@RestController
class FallbackController {
  @GetMapping(value="/__fallback/catalog", produces=MediaType.APPLICATION_JSON_VALUE)
  Mono<Map<String,Object>> catalogFallback() {
    return Mono.just(Map.of("items", java.util.List.of(), "fallback", true));
  }
}
```

```java
// AggregationController.java — simple fan-out aggregation endpoint (BFF-like)
import org.springframework.web.bind.annotation.*;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;
import reactor.util.function.Tuple2;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/aggregate")
class AggregationController {
  private final WebClient catalog = WebClient.builder().baseUrl("http://catalog:8080").build();
  private final WebClient inventory = WebClient.builder().baseUrl("http://inventory:8080").build();

  @GetMapping("/product/{id}")
  Mono<Map<String, Object>> product(@PathVariable String id) {
    Mono<Map> p = catalog.get().uri("/products/{id}", id).retrieve().bodyToMono(Map.class);
    Mono<Map> s = inventory.get().uri("/stock/{id}", id).retrieve().bodyToMono(Map.class);
    return Mono.zip(p, s).map(t -> merge(t));
  }

  private Map<String,Object> merge(Tuple2<Map,Map> t) {
    Map prod = t.getT1(); Map stock = t.getT2();
    return Map.of(
      "id", prod.get("id"),
      "name", prod.get("name"),
      "price", prod.get("price"),
      "stock", stock.getOrDefault("available", 0),
      "vendor", prod.get("vendor")
    );
  }
}
```

```yaml
# application.yml — (snippet) sensible defaults
spring:
  main:
    web-application-type: reactive
  cloud:
    gateway:
      httpclient:
        connect-timeout: 2000
        response-timeout: 3s
management:
  endpoints:
    web:
      exposure:
        include: health,info,prometheus
server:
  error:
    include-message: never
```

**Notes on the sample**

-   **Routing & filters:** path rewrite, circuit breaker fallback, Redis-backed rate limiting (swap to in-memory for dev).

-   **JWT:** Minimal HS256 check via Nimbus; in production use OIDC discovery, RS256/ES256, key rotation, and scopes/claims mapping.

-   **Aggregation:** Non-blocking fan-out via WebClient; add timeouts, fallbacks, and partial responses as needed.

-   **Hardening:** Enable gzip/brotli, set max payload size, strict CORS, request size limits, and structured logging with correlation IDs.


## Known Uses

-   **Public APIs** for e-commerce, fintech, and media platforms consolidating dozens of microservices.

-   **Partner/affiliate portals** with per-tenant routing, quotas, and transformations.

-   **BFFs** for mobile/web splitting heavy backend composition from clients.

-   **Protocol bridging** (HTTP ↔ gRPC, WebSocket, GraphQL) and **canary**/A-B traffic shifting.


## Related Patterns

-   **Backend for Frontend (BFF):** Gateway specialized per client (web vs. mobile) with tailored aggregation.

-   **Service Mesh:** East–west policies; complements the gateway’s north–south role.

-   **Ambassador (Sidecar):** Per-service egress proxy; often used together with an edge gateway.

-   **Circuit Breaker / Retry / Bulkhead / Rate Limiter:** Resilience primitives implemented in or enforced by the gateway.

-   **API Composition / Aggregator Microservice:** When aggregation becomes complex, factor it out.

-   **Strangler Fig / Canary Release:** Use gateway routing to incrementally migrate or experiment with new services.
