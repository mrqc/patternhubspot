# Backend for Frontend (BFF) — Microservice Pattern

## Pattern Name and Classification

**Name:** Backend for Frontend (BFF)  
**Classification:** Microservices / API Composition / Client-Specific Gateway

## Intent

Provide a **dedicated backend service tailored to a specific frontend client** (e.g., mobile app, web app, IoT device). The BFF aggregates and transforms data from underlying microservices into **client-optimized responses**, encapsulating client-specific logic, minimizing round-trips, and simplifying frontend development.

## Also Known As

-   Client-Specific API Gateway
    
-   Façade per Frontend
    
-   Client Adapter Service
    

## Motivation (Forces)

-   **Frontend diversity:** Different clients (web, iOS, Android, smartwatch, IoT) need **different data shapes, frequencies, and optimizations**.
    
-   **Minimize round-trips:** Especially important for mobile with high-latency or unreliable networks.
    
-   **Separation of concerns:** Keep client-specific aggregation and orchestration logic out of shared services.
    
-   **Rapid iteration:** Frontend and BFF teams can evolve independently without disrupting core backend services.
    
-   **Security:** BFFs can enforce tailored authentication/authorization per client and apply request shaping.
    

**Tensions**

-   Risk of duplicating logic across multiple BFFs.
    
-   Potential sprawl if each new client spins up another BFF.
    
-   Must ensure consistent policies across BFFs (auth, rate limiting).
    

## Applicability

Use BFF when:

-   You serve multiple **distinct client types** with different UX and data needs.
    
-   The frontend requires **aggregation** from multiple services and payload shaping.
    
-   Mobile apps need **optimized payloads** and reduced latency.
    
-   You want to isolate **client-specific features** from core services.
    

Avoid BFF if:

-   You only have one frontend and a general-purpose **API Gateway** suffices.
    
-   Aggregation is minimal, and direct-to-microservice calls are acceptable.
    
-   Too many BFFs would cause fragmentation and duplication without governance.
    

## Structure

-   **Frontend Clients:** Mobile, web, desktop, IoT, etc.
    
-   **BFF Layer:** Client-specific microservice acting as a backend for that frontend, handling composition, transformation, caching, and security.
    
-   **Core Microservices:** Business-domain microservices with clean APIs.
    
-   **API Gateway (optional):** Can coexist with BFFs for common cross-cutting concerns.
    

```css
[Mobile App] ---> [Mobile BFF] ---> [Services A, B, C]
[Web App]    ---> [Web BFF]    ---> [Services A, B, D]
[IoT Device] ---> [IoT BFF]    ---> [Services C, E]
```

## Participants

-   **Frontend Application** — consumes BFF endpoints designed for its UI/UX needs.
    
-   **BFF Service** — tailors API contracts, aggregates data, optimizes payloads, enforces client-specific auth.
    
-   **Backend Services** — provide raw domain functionality and data.
    
-   **Optional API Gateway** — handles global cross-cutting concerns (TLS, WAF, quotas).
    

## Collaboration

1.  Client sends a request to its dedicated **BFF**.
    
2.  BFF authenticates the request, enforces client-specific policies.
    
3.  BFF **aggregates** data from multiple backend services (calls A, B, C).
    
4.  BFF transforms and optimizes response into the format expected by the client (e.g., JSON tailored for mobile UI).
    
5.  BFF returns response; may cache results or push updates via WebSockets/GraphQL subscriptions.
    

## Consequences

**Benefits**

-   Simplified frontend code; backend complexity hidden in BFF.
    
-   Optimized responses per client, reducing network overhead.
    
-   Faster frontend iterations without destabilizing backend services.
    
-   Security and policy enforcement close to the client context.
    

**Liabilities**

-   Possible duplication of logic across multiple BFFs.
    
-   Maintenance overhead (one BFF per frontend).
    
-   Requires strong governance to avoid inconsistencies.
    
-   Extra network hop may add slight latency (offset by reduced round-trips).
    

## Implementation

**Key practices**

-   **Client-specific endpoints:** Design BFF APIs to reflect UI use-cases.
    
-   **Aggregation:** Use async/non-blocking calls to aggregate multiple services.
    
-   **Caching:** Implement local or distributed cache for frequently used client data.
    
-   **Security:** Apply per-client auth flows (OAuth, JWT, mTLS).
    
-   **Resilience:** Timeouts, retries, fallbacks for backend calls.
    
-   **Observability:** Correlation IDs, logging, tracing, per-client metrics.
    
-   **Deployment:** Co-locate BFF and frontend team ownership; version APIs independently.
    

---

## Sample Code (Java — Spring Boot WebFlux BFF Example)

> Example BFF for a **mobile client** that aggregates user profile, orders, and recommendations from different microservices and shapes the response.

```java
// build.gradle dependencies
// implementation 'org.springframework.boot:spring-boot-starter-webflux'
// implementation 'org.springframework.boot:spring-boot-starter-security'
// implementation 'org.springframework.boot:spring-boot-starter-actuator'

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;
import reactor.util.function.Tuple3;

import java.util.Map;

@SpringBootApplication
public class MobileBffApp {
    public static void main(String[] args) {
        SpringApplication.run(MobileBffApp.class, args);
    }
}

@RestController
@RequestMapping("/mobile")
class MobileBffController {
    private final WebClient userService = WebClient.create("http://user-service:8080");
    private final WebClient orderService = WebClient.create("http://order-service:8080");
    private final WebClient recService   = WebClient.create("http://rec-service:8080");

    @GetMapping("/dashboard/{userId}")
    public Mono<Map<String, Object>> getDashboard(@PathVariable String userId) {
        Mono<Map> profile = userService.get().uri("/users/{id}", userId).retrieve().bodyToMono(Map.class);
        Mono<Map> orders  = orderService.get().uri("/orders/by-user/{id}", userId).retrieve().bodyToMono(Map.class);
        Mono<Map> recs    = recService.get().uri("/recommendations/{id}", userId).retrieve().bodyToMono(Map.class);

        return Mono.zip(profile, orders, recs)
            .map(tuple -> shapeDashboard(tuple));
    }

    private Map<String, Object> shapeDashboard(Tuple3<Map, Map, Map> t) {
        Map profile = t.getT1();
        Map orders  = t.getT2();
        Map recs    = t.getT3();
        return Map.of(
            "user", Map.of(
                "id", profile.get("id"),
                "name", profile.get("name"),
                "loyaltyPoints", profile.get("loyaltyPoints")
            ),
            "recentOrders", orders.get("items"),
            "recommendations", recs.get("products")
        );
    }
}
```

**Notes on sample**

-   Uses **WebFlux/WebClient** for non-blocking parallel calls.
    
-   BFF aggregates data into a **mobile-optimized dashboard response**.
    
-   Auth (e.g., JWT filter) can be added with `spring-boot-starter-security`.
    
-   Extend with caching (`@Cacheable`) or fallback logic (`onErrorResume`).
    

---

## Known Uses

-   **Netflix:** BFF pattern for different client platforms (web, TV, mobile).
    
-   **Spotify:** Separate APIs for mobile and web with tailored payloads.
    
-   **E-commerce:** Mobile BFFs aggregate product, cart, and inventory info for reduced round-trips.
    
-   **Banking apps:** Mobile BFFs handle composite data (balances, transactions, offers) securely.
    

## Related Patterns

-   **API Gateway:** Centralized ingress for all clients; BFF is per-client specialization.
    
-   **Aggregator Microservice / API Composition:** Generic aggregation across services.
    
-   **Ambassador (Sidecar):** Handles egress for services; complementary to BFF’s ingress role.
    
-   **Strangler Fig:** Use BFF to migrate monolith UIs gradually.
    
-   **Façade:** General design pattern for simplifying interfaces; BFF is its microservice application.

