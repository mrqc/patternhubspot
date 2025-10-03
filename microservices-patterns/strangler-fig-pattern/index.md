# Strangler Fig — Microservice Pattern

## Pattern Name and Classification

-   **Name:** Strangler Fig
    
-   **Classification:** **Incremental Migration** & Modernization Pattern (from monolith/legacy to services)
    

## Intent

Migrate a legacy system **piece by piece** by placing a **strangling facade** in front of it. New or rebuilt capabilities are routed to **replacement services**, while untouched paths still go to the **legacy**. Over time the facade “strangles” the old system until it can be retired.

## Also Known As

-   Strangler
    
-   Branch by Abstraction (related idea)
    
-   Facade-Based Migration
    

## Motivation (Forces)

-   **Zero/low downtime:** Big-bang rewrites are risky; gradual migration reduces blast radius.
    
-   **Continuous value:** Ship new features in the new stack while legacy continues to serve existing ones.
    
-   **Risk isolation:** Roll back by flipping routes; keep user-facing contract stable.
    
-   **Data decoupling:** Peel data/domain slices toward **Database per Service** without cross-cutting breaks.
    

**Tensions**

-   **Double-running:** Temporarily run both legacy and new, raising cost and operational complexity.
    
-   **Routing complexity:** Edge logic (routing, auth, headers) must stay consistent.
    
-   **Data synchronization:** Double-writes, CDC, or backfills are needed during transition.
    
-   **Team coordination:** Clear ownership and migration plan per slice.
    

## Applicability

Use when:

-   You need to **modernize a monolith** or COTS without halting delivery.
    
-   You can segment the system by **routes, use cases, or bounded contexts**.
    
-   You require **safe rollback** and **progressive delivery** during migration.
    

Avoid or limit when:

-   The system is tiny (rewrite is cheaper).
    
-   There’s an unavoidable **global transaction** across all modules (re-model first).
    

## Structure

```bash
Clients
             │
        [Strangling Facade / Gateway]
             │     ├─────────► /orders/** → New Orders Service
             │     ├─────────► /catalog/** → New Catalog Service
             └─────┴─────────► (all other paths) → Legacy App
```

-   Optional **data plane**: CDC/outbox feeds projections in new services.
    
-   Optional **feature flags** / header-based canaries for gradual cutover.
    

## Participants

-   **Strangling Facade (Gateway/Proxy):** Single entry point; routes per path/header/version.
    
-   **New Services:** Replacement capabilities with **own data** and contracts.
    
-   **Legacy System:** Still serves non-migrated paths; gradually minimized.
    
-   **Data Sync Layer (optional):** CDC/outbox, backfills, dual-writes.
    
-   **Observability & Flags:** Telemetry, A/B canaries, kill switches.
    

## Collaboration

1.  Requests hit the **facade**.
    
2.  Facade applies **routing rules** (path, header, tenant, version): forward to **new** or **legacy**.
    
3.  During migration, optional **shadowing** duplicates traffic to new service (response ignored).
    
4.  Data moves via **CDC/backfill**; features flip **gradually** (canary → cohort → 100%).
    
5.  Decommission the legacy endpoint once new service meets SLOs.
    

## Consequences

**Benefits**

-   Safer, reversible migration with **small batches**.
    
-   Business continuity; ship improvements continuously.
    
-   Clear progress; each strangled slice is a win.
    

**Liabilities**

-   Temporary **duplication** of logic and data.
    
-   More moving parts (gateway rules, CDC pipelines).
    
-   Requires disciplined **API and data ownership** to avoid a distributed monolith.
    

## Implementation

1.  **Slice the domain** by bounded context/URL prefix (e.g., `/orders/**`).
    
2.  **Stand a facade** (API gateway, reverse proxy, edge service). Keep auth, headers, tracing consistent.
    
3.  **Build the replacement** service with **Database per Service**.
    
4.  **Establish data flows:**
    
    -   Prefer **Transactional Outbox + CDC** from legacy to new read models or vice versa.
        
    -   Use **backfills** for historical data.
        
5.  **Introduce traffic gradually:** header/flag, tenant cohort, percentage-based canary; add **shadowing** if useful.
    
6.  **Observe and enforce SLOs:** latency/error budgets, parity checks, idempotency, DLQs for pipelines.
    
7.  **Flip defaults** to new path; keep rollback one toggle away.
    
8.  **Retire** the legacy slice (remove route, decommission code/data).
    
9.  **Repeat** for the next slice.
    

---

## Sample Code (Java, Spring Boot) — Strangling Facade Proxy

Below is a small **gateway** that proxies requests to either the **legacy** app or a **new** service based on path and a simple rollout flag. It preserves method, path, headers, query, and body, and keeps timeouts explicit (retries live at the edge or mesh).

### `pom.xml` (snippets)

```xml
<dependencies>
  <dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-webflux</artifactId>
  </dependency>
  <dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-configuration-processor</artifactId>
    <optional>true</optional>
  </dependency>
</dependencies>
```

### Configuration

```yaml
# application.yml
strangler:
  legacyBaseUrl: http://legacy-app:8080
  routes:
    - prefix: /api/orders
      targetBaseUrl: http://orders-new:8080
      enabled: true          # flip to false to roll back this slice
    - prefix: /api/catalog
      targetBaseUrl: http://catalog-new:8080
      enabled: false         # not migrated yet → goes to legacy
server:
  port: 8080
```

### Routing Properties

```java
// StranglerProperties.java
package strangler;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;
import jakarta.validation.constraints.NotBlank;
import java.util.List;

@Validated
@ConfigurationProperties(prefix = "strangler")
public class StranglerProperties {
  @NotBlank private String legacyBaseUrl;
  private List<Route> routes;
  public String getLegacyBaseUrl() { return legacyBaseUrl; }
  public void setLegacyBaseUrl(String legacyBaseUrl) { this.legacyBaseUrl = legacyBaseUrl; }
  public List<Route> getRoutes() { return routes; }
  public void setRoutes(List<Route> routes) { this.routes = routes; }

  public static class Route {
    @NotBlank private String prefix;
    @NotBlank private String targetBaseUrl;
    private boolean enabled = false;
    public String getPrefix() { return prefix; }
    public void setPrefix(String prefix) { this.prefix = prefix; }
    public String getTargetBaseUrl() { return targetBaseUrl; }
    public void setTargetBaseUrl(String targetBaseUrl) { this.targetBaseUrl = targetBaseUrl; }
    public boolean isEnabled() { return enabled; }
    public void setEnabled(boolean enabled) { this.enabled = enabled; }
  }
}
```

### Facade (Reactive Proxy)

```java
// StranglerGateway.java
package strangler;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.reactive.function.BodyInserters;
import org.springframework.web.reactive.function.client.*;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.net.URI;
import java.time.Duration;

@Configuration
@EnableConfigurationProperties(StranglerProperties.class)
class StranglerConfig { }

@Component
@RestController
public class StranglerGateway {

  private final StranglerProperties cfg;
  private final WebClient http = WebClient.builder()
      .codecs(c -> c.defaultCodecs().maxInMemorySize(16 * 1024 * 1024))
      .build();

  public StranglerGateway(StranglerProperties cfg) { this.cfg = cfg; }

  @RequestMapping(path = "/**")
  public Mono<Void> proxy(ServerWebExchange exchange) {
    ServerHttpRequest in = exchange.getRequest();
    String path = in.getURI().getRawPath();

    // Decide target
    String base = cfg.getLegacyBaseUrl();
    if (cfg.getRoutes() != null) {
      for (var r : cfg.getRoutes()) {
        if (r.isEnabled() && path.startsWith(r.getPrefix())) {
          base = r.getTargetBaseUrl();
          break;
        }
      }
    }

    // Optional canary via header
    String canary = in.getHeaders().getFirst("X-Use-New");
    if ("orders".equalsIgnoreCase(canary)) {
      base = cfg.getRoutes().stream()
          .filter(r -> r.getPrefix().equals("/api/orders"))
          .findFirst().map(StranglerProperties.Route::getTargetBaseUrl)
          .orElse(base);
    }

    // Build target URI (preserve path + query)
    String qs = in.getURI().getRawQuery();
    URI target = URI.create(base + path + (qs == null ? "" : "?" + qs));

    WebClient.RequestBodySpec spec = http.method(HttpMethod.valueOf(in.getMethodValue()))
        .uri(target)
        .headers(h -> copyHeaders(in.getHeaders(), h));

    Mono<ClientResponse> respMono = (requiresBody(in.getMethod()) ?
        spec.body(BodyInserters.fromDataBuffers(in.getBody())) : spec)
        .exchangeToMono(Mono::just)
        .timeout(Duration.ofSeconds(10));

    return respMono.flatMap(resp -> {
      var out = exchange.getResponse();
      out.setStatusCode(resp.statusCode());
      resp.headers().asHttpHeaders().forEach((k, v) -> {
        if (!k.equalsIgnoreCase(HttpHeaders.TRANSFER_ENCODING)) out.getHeaders().put(k, v);
      });
      return out.writeWith(resp.bodyToFlux(org.springframework.core.io.buffer.DataBuffer.class));
    });
  }

  private static void copyHeaders(HttpHeaders in, HttpHeaders out) {
    in.forEach((k, v) -> {
      if (!k.equalsIgnoreCase(HttpHeaders.HOST)) out.put(k, v);
    });
    // Ensure correlation headers pass through
    out.computeIfAbsent("X-Request-ID", k -> java.util.List.of(java.util.UUID.randomUUID().toString()));
  }

  private static boolean requiresBody(HttpMethod m) {
    return m == HttpMethod.POST || m == HttpMethod.PUT || m == HttpMethod.PATCH;
  }
}
```

**How to use it**

-   Flip `routes[n].enabled=true` to cut a path over to the new service.

-   Add `X-Use-New: orders` to canary specific callers.

-   Roll back instantly by disabling the route.


**Notes**

-   Keep **authn/z** consistent (forward `Authorization`, user headers).

-   In production, put this behind your edge gateway or make it *the* edge, plus rate limits, TLS, WAF, etc.

-   If you run a mesh, you can still use it; the mesh handles mTLS/retries while this handles routing.


---

## Known Uses

-   Widely described in industry modernization efforts inspired by Martin Fowler’s write-up.

-   Enterprises migrating commerce, banking, and media platforms: route new checkout, catalog, search, or pricing slices through a facade while the rest remains on legacy; over time the legacy is decommissioned slice by slice.


## Related Patterns

-   **API Gateway / BFF:** Often implements the strangling facade.

-   **Database per Service:** Target state for data ownership as you peel slices off.

-   **Transactional Outbox & CDC:** Move data between legacy and new services safely.

-   **Anti-Corruption Layer:** Translate legacy models into clean domain models at the boundary.

-   **Canary / Blue-Green / Traffic Shadowing:** Techniques to shift and validate traffic.

-   **Sidecar / Service Mesh:** Provide mTLS, retries, and observability while you strangle.

-   **Saga:** Coordinate long-running workflows across old and new during migration.
