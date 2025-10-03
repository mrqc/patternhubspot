# Circuit Breaker — Design Pattern

## Pattern Name and Classification

**Circuit Breaker** — *Resilience / Fault-tolerance* pattern for remote calls in distributed systems.

---

## Intent

Prevent a failing or slow downstream dependency from repeatedly harming the caller (cascading failures) by **monitoring errors/latency**, **short-circuiting** calls when a failure threshold is reached, and **probing** recovery with limited test requests.

---

## Also Known As

-   **Fuse**
    
-   **Service Breaker**
    
-   (Historically via library) **Hystrix-style breaker**
    

---

## Motivation (Forces)

-   Downstream slowness/errors propagate **thread/connection exhaustion** upstream.
    
-   Retries without bounds amplify load (**retry storms**).
    
-   Need fast **fail-fast** behavior with **bounded latency** and **automatic recovery**.
    

Trade-offs:

-   False opens vs. protecting the system
    
-   Global vs. per-route/per-client breakers
    
-   Error rate vs. slow call rate as trip criteria
    

---

## Applicability

Use when:

-   Calling remote services (HTTP/gRPC/DB) with **variable reliability or latency**.
    
-   You need **SLA/SLO** protection and graceful degradation.
    
-   You already have **timeouts** and **retries** (a breaker coordinates them).
    

Avoid when:

-   Calls are **purely local** and cheap (use simple retries/timeouts).
    
-   Very short-lived spikes would frequently flip the breaker (tune thresholds first).
    

---

## Structure

```less
Caller -> [ Timeout ] -> [ Retry (bounded, jitter) ] -> [ Circuit Breaker ]
                                                      |  (CLOSED ↔ OPEN ↔ HALF_OPEN)
                                                      v
                                                Downstream Service
```

**States**

-   **CLOSED**: Pass traffic; count failures/slow calls.
    
-   **OPEN**: Short-circuit immediately; use fallback.
    
-   **HALF\_OPEN**: Allow a few trial calls; close on success(es) or re-open on failure(s).
    

---

## Participants

-   **Caller**: Makes protected calls.
    
-   **Circuit Breaker**: Tracks outcomes and state; decides pass/deny.
    
-   **Downstream**: The remote dependency.
    
-   **Fallback/Degrader**: Alternative path or cached/partial response.
    

---

## Collaboration

1.  Caller invokes operation through the breaker.
    
2.  Breaker in **CLOSED** counts errors/slow calls in a sliding window.
    
3.  Threshold exceeded → **OPEN** for a cool-down. Calls fail fast.
    
4.  After wait duration, **HALF\_OPEN** allows limited probe calls.
    
5.  Success → **CLOSED** (reset); failure → **OPEN** again.
    

---

## Consequences

**Benefits**

-   Prevents **cascading failures** and **resource exhaustion**.
    
-   Enforces **predictable latency** (fail fast).
    
-   Enables **graceful degradation** and **auto-recovery**.
    

**Liabilities**

-   **Tuning complexity** (thresholds, windows).
    
-   Possible **false trips** (opens during transient blips).
    
-   Adds **operational metrics** to manage (but that’s usually a plus).
    

---

## Implementation (Key Points)

-   Always combine **timeouts** (per call) and **bounded retries with jitter**.
    
-   Choose trip strategy: **failure rate**, **slow call rate**, or both.
    
-   Use **sliding window** (count/time-based) + **minimum calls** to avoid noise.
    
-   Set **open-state wait** and **half-open permitted calls**.
    
-   Emit metrics/traces, propagate **correlation IDs**.
    
-   Prefer **per-route** breakers over one global breaker.
    
-   Provide **fallbacks** appropriate to the use case (cache, stale, default).
    

---

## Sample Code (Java, Spring WebFlux + Resilience4j)

> A controller calls a downstream service with **timeout, retry, circuit breaker**, and a **fallback**.  
> Replace the downstream base URL for your environment.

**Gradle (snippets)**

```gradle
implementation "org.springframework.boot:spring-boot-starter-webflux"
implementation "io.github.resilience4j:resilience4j-spring-boot3"
implementation "io.github.resilience4j:resilience4j-reactor"
implementation "org.springframework.boot:spring-boot-starter-actuator"
```

**application.yml (breaker, retry, timeouts)**

```yaml
resilience4j:
  circuitbreaker:
    instances:
      productClient:
        sliding-window-type: COUNT_BASED
        sliding-window-size: 50
        minimum-number-of-calls: 20
        failure-rate-threshold: 50
        slow-call-rate-threshold: 50
        slow-call-duration-threshold: 2s
        permitted-number-of-calls-in-half-open-state: 5
        wait-duration-in-open-state: 10s
        automatic-transition-from-open-to-half-open-enabled: true
  retry:
    instances:
      productClient:
        max-attempts: 3
        wait-duration: 100ms
        enable-exponential-backoff: true
        exponential-backoff-multiplier: 2
spring:
  webflux:
    codecs:
      max-in-memory-size: 4MB
```

**Downstream client with timeout**

```java
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;
import java.time.Duration;

record Product(String id, String name) {}

@Component
class ProductClient {
  private final WebClient http = WebClient.builder()
      .baseUrl("http://product-service:8080")
      .build();

  Mono<Product> getProduct(String id) {
    return http.get().uri("/products/{id}", id)
        .retrieve()
        .bodyToMono(Product.class)
        .timeout(Duration.ofSeconds(2)); // per-call timeout
  }
}
```

**Service with Circuit Breaker + Retry + Fallback**

```java
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import io.github.resilience4j.retry.annotation.Retry;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;

@Service
class CatalogService {
  private final ProductClient client;

  CatalogService(ProductClient client) { this.client = client; }

  @CircuitBreaker(name = "productClient", fallbackMethod = "fallbackProduct")
  @Retry(name = "productClient")
  Mono<Product> find(String id) {
    return client.getProduct(id);
  }

  // Fallback signature must match + Throwable at end
  Mono<Product> fallbackProduct(String id, Throwable cause) {
    // Degraded response (stale cache would be better in real life)
    return Mono.just(new Product(id, "Unavailable"));
  }
}
```

**Controller**

```java
import org.springframework.web.bind.annotation.*;
import reactor.core.publisher.Mono;

@RestController
@RequestMapping("/api")
class CatalogController {

  private final CatalogService svc;
  CatalogController(CatalogService svc) { this.svc = svc; }

  @GetMapping("/products/{id}")
  Mono<Product> get(@PathVariable String id) {
    return svc.find(id);
  }
}
```

**Optional: programmatic configuration (if you prefer Java over YAML)**

```java
import io.github.resilience4j.circuitbreaker.*;
import io.github.resilience4j.timelimiter.*;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import java.time.Duration;

@Configuration
class ResilienceConfig {

  @Bean
  CircuitBreaker productCircuitBreaker() {
    CircuitBreakerConfig cfg = CircuitBreakerConfig.custom()
        .failureRateThreshold(50f)
        .slowCallRateThreshold(50f)
        .slowCallDurationThreshold(Duration.ofSeconds(2))
        .slidingWindowType(CircuitBreakerConfig.SlidingWindowType.COUNT_BASED)
        .slidingWindowSize(50)
        .minimumNumberOfCalls(20)
        .waitDurationInOpenState(Duration.ofSeconds(10))
        .permittedNumberOfCallsInHalfOpenState(5)
        .build();
    return CircuitBreaker.of("productClient", cfg);
  }

  @Bean
  TimeLimiterConfig timeLimiterConfig() {
    return TimeLimiterConfig.custom().timeoutDuration(Duration.ofSeconds(2)).build();
  }
}
```

> **Notes**
> 
> -   Add **bulkheads** (separate connection pools or semaphore-isolated concurrency) to avoid thread starvation.
>     
> -   Emit metrics to Prometheus/OTel; track **state transitions** and **rejections**.
>     
> -   Prefer **idempotent** operations so retries are safe.
>     
> -   Apply breakers **per downstream/route**; tune thresholds by traffic patterns.
>     

---

## Known Uses

-   **Netflix Hystrix** (now retired) popularized the pattern.
    
-   **Resilience4j**, **Spring Cloud Circuit Breaker**, **Envoy/Nginx** filters, **Istio** (outlier detection) implement breaker behavior widely in production.
    

---

## Related Patterns

-   **Timeout**, **Retry with Exponential Backoff**, **Bulkhead** — typically combined with the breaker.
    
-   **Fallback / Graceful Degradation** — what to return when open.
    
-   **Rate Limiting** — complementary protection from abusive load.
    
-   **API Gateway / BFF** — common place to enforce breakers at the edge.
    
-   **Load Shedding / Queue-based Load Leveling** — upstream protection strategies.
