# Canary Deployment — Microservice Pattern

## Pattern Name and Classification

**Name:** Canary Deployment  
**Classification:** Microservices / Release Engineering & Progressive Delivery / Risk-Mitigation Rollout

## Intent

Release a new version to a **small, carefully selected slice of traffic** (e.g., 1–5%), observe **real production signals** (errors, latency, business KPIs), and **progressively increase** traffic to the canary if healthy—or **instantly roll back** if not.

## Also Known As

-   Progressive Delivery
    
-   Incremental Rollout
    
-   Traffic Shifting
    
-   Dark Launch *(when responses are discarded / shadowed)*
    

## Motivation (Forces)

-   **Reduce blast radius:** Catch regressions with minimal customer impact.
    
-   **Measure what matters:** Validate *user-visible* behavior and business metrics in production.
    
-   **Roll back fast:** Traffic switches are reversible; no long rollouts to unwind.
    
-   **Heterogeneous users/regions:** Target cohorts (internal, beta users, region, tenant) for better signal.
    

**Forces & Challenges**

-   **Routing & stickiness:** Users should consistently hit the same version during a session.
    
-   **Observability:** Must compare canary vs. baseline—error rate, p95 latency, saturation, KPIs.
    
-   **Data & schema:** New/old versions must coexist; prefer backward-compatible migrations.
    
-   **Automated judgments:** Guardrails (SLOs, error budgets) should gate promotion automatically.
    

## Applicability

Use **Canary Deployment** when:

-   You can route traffic by **percentage, header, user/tenant, region**, or feature flag.
    
-   You have **telemetry** and service health SLOs to evaluate the canary.
    
-   You want **fast rollback** without redeploying the old version.
    

Be cautious when:

-   Stateful changes (DB migrations) are not **backward compatible**; canary may corrupt state.
    
-   Ultra-low latency paths cannot tolerate extra routing hops (consider on-host canaries or shadowing).
    
-   You lack observability—flying blind defeats the purpose.
    

## Structure

-   **Baseline (Stable) Version:** Receives most traffic.
    
-   **Canary Version:** New build; receives a small, sticky slice.
    
-   **Traffic Router:** LB/ingress/mesh/gateway/sidecar (or app-level) that assigns requests to baseline/canary.
    
-   **Observability & Analysis:** Metrics, logs, traces, and business KPIs split by version/cohort.
    
-   **Controller (human or automated):** Changes weights, pauses, promotes, or rolls back.
    

```pgsql
[ Clients ]
     |
     v
[Traffic Router] --%--> [Service vNext (Canary)]
           \---- rest --> [Service vStable (Baseline)]
           (sticky by user/tenant/session)
```

## Participants

-   **Deployment Pipeline / Controller** — adjusts weights, triggers rollout/rollback.
    
-   **Traffic Router** — enforces weights, stickiness, cohort targeting.
    
-   **Service vStable / vNext** — old/new versions in parallel.
    
-   **Observability Stack** — per-version SLOs, ratios, and dashboards.
    
-   **Release Manager / SRE** — supervises and approves promotion.
    

## Collaboration

1.  Deploy **vNext** alongside **vStable**.
    
2.  Route **canary cohort** (e.g., 1%) to vNext using sticky assignment.
    
3.  Observe **error rate, latency, resource usage, and KPIs** for a bake window.
    
4.  If healthy, **increase weight** (5% → 10% → 25% → 50% → 100%).
    
5.  If unhealthy, **set weight to 0%** (rollback) and investigate.
    
6.  After 100%, retire vStable (or keep briefly for emergency rollback).
    

## Consequences

**Benefits**

-   Minimal blast radius; *real* production validation.
    
-   Reversible at the speed of a config flip.
    
-   Enables experimentation (A/B, beta cohorts) using the same plumbing.
    

**Liabilities**

-   Requires robust routing, **stickiness**, and per-version telemetry.
    
-   More moving parts in deployment (two versions live).
    
-   DB/schema incompatible changes can block canaries—needs **expand/contract** migrations.
    
-   Business metrics can lag—set bake times wisely.
    

## Implementation

**Key practices**

-   **Routing & Stickiness:** Use consistent hashing on a user/session/tenant key; avoid flapping between versions.
    
-   **Cohorts:** Start with employees/beta users or non-critical regions; then percentage-based global rollout.
    
-   **Observability:** Break down metrics by version/cohort—HTTP 5xx/4xx, p95/p99 latency, CPU/memory, GC, business KPIs.
    
-   **Automated gates:** SLOs with error budgets; abort if canary deviates beyond thresholds.
    
-   **DB migrations:** Use *expand/contract* (add columns → dual-write/read → remove old) to keep versions compatible.
    
-   **Config as code:** Canary weights managed via config or control plane; audit changes.
    
-   **Fast rollback:** Make “weight=0%” a one-click (or automatic) action.
    
-   **Security & privacy:** Ensure both versions meet the same security baselines before exposure.
    

---

## Sample Code (Java, Spring Boot WebFlux) — **Sticky Percentage Router / Reverse Proxy**

> A tiny reverse proxy you can run as an **edge gateway** or **sidecar** for a service.
> 
> -   Sticky assignment based on a cookie or header → consistent user routing
>     
> -   Percentage-based canary weight with **atomic live updates**
>     
> -   Health toggle and simple counters (replace with Micrometer in prod)
>     
> -   Proxies any path/method to vStable or vCanary
>     

```java
// build.gradle (or pom.xml equivalents)
// implementation 'org.springframework.boot:spring-boot-starter-webflux'

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.stereotype.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.net.URI;
import java.time.Duration;
import java.util.Map;
import java.util.Objects;
import java.util.Random;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

@SpringBootApplication
public class CanaryRouterApp {
  public static void main(String[] args) { SpringApplication.run(CanaryRouterApp.class, args); }
}

// --- Live config (hot-changeable via admin endpoints) ---
@Component
class CanaryConfig {
  // Base URLs (point these at your stable/canary deployments or Kubernetes services)
  volatile URI stableBase = URI.create(System.getenv().getOrDefault("STABLE_BASE", "http://stable:8080"));
  volatile URI canaryBase = URI.create(System.getenv().getOrDefault("CANARY_BASE", "http://canary:8080"));
  // Percentage of traffic to canary (0..100)
  final AtomicInteger canaryPercent = new AtomicInteger(Integer.parseInt(System.getenv().getOrDefault("CANARY_PERCENT", "5")));
  // Enable/disable canary quickly
  volatile boolean canaryEnabled = true;

  // Simple counters (replace with Micrometer/Prometheus)
  final Map<String, Long> counters = new ConcurrentHashMap<>();
  void inc(String k){ counters.merge(k, 1L, Long::sum); }
}

// --- Admin API to inspect & adjust routing live ---
@RestController
@RequestMapping("/__canary")
class CanaryAdminController {
  private final CanaryConfig cfg;
  CanaryAdminController(CanaryConfig cfg) { this.cfg = cfg; }

  @GetMapping("/status")
  Map<String,Object> status() {
    return Map.of("stableBase", cfg.stableBase.toString(),
                  "canaryBase", cfg.canaryBase.toString(),
                  "canaryPercent", cfg.canaryPercent.get(),
                  "canaryEnabled", cfg.canaryEnabled,
                  "counters", cfg.counters);
  }

  @PostMapping("/percent/{p}")
  Map<String,Object> setPercent(@PathVariable int p) {
    if (p < 0 || p > 100) throw new IllegalArgumentException("0..100");
    cfg.canaryPercent.set(p);
    return status();
  }

  @PostMapping("/toggle/{enabled}")
  Map<String,Object> toggle(@PathVariable boolean enabled) { cfg.canaryEnabled = enabled; return status(); }

  @PostMapping("/bases")
  Map<String,Object> setBases(@RequestParam String stable, @RequestParam String canary) {
    cfg.stableBase = URI.create(stable); cfg.canaryBase = URI.create(canary); return status();
  }
}

// --- Reverse proxy with sticky hashing & percentage routing ---
@RestController
class ProxyController {
  private final CanaryConfig cfg;
  private final WebClient client = WebClient.builder()
          .clientConnector(new reactor.netty.http.client.HttpClientConnector(
                  reactor.netty.http.client.HttpClient.create().responseTimeout(Duration.ofSeconds(3))
          ))
          .build();
  private final Random rnd = new Random();

  ProxyController(CanaryConfig cfg) { this.cfg = cfg; }

  // Proxy everything except the admin paths
  @RequestMapping("/{path:^(?!__canary/).*$}/**")
  public Mono<org.springframework.http.ResponseEntity<byte[]>> proxy(
          @PathVariable String path,
          ServerWebExchange exchange
  ) {
    var req = exchange.getRequest();
    String sticky = stickyKey(exchange); // cookie -> header -> remote addr
    boolean toCanary = chooseCanary(sticky);

    URI base = (toCanary && cfg.canaryEnabled) ? cfg.canaryBase : cfg.stableBase;
    cfg.inc(toCanary ? "routed_canary" : "routed_stable");

    // Rebuild target URI: base + original path + query
    String suffix = req.getPath().pathWithinApplication().value();
    String query = req.getURI().getRawQuery();
    URI target = URI.create(base + suffix + (query == null ? "" : "?" + query));

    WebClient.RequestBodySpec out = client.method(req.getMethod()).uri(target)
            .headers(h -> {
              h.addAll(safeHeaders(req.getHeaders()));
              h.set("X-Canary-Routed", Boolean.toString(toCanary));
              h.set("X-Canary-Sticky", sticky);
            });

    Mono<byte[]> bodyMono = req.getBody().aggregate().map(dataBuffer -> {
      byte[] bytes = new byte[dataBuffer.readableByteCount()];
      dataBuffer.read(bytes);
      return bytes;
    }).defaultIfEmpty(new byte[0]);

    return bodyMono.flatMap(bytes ->
            out.bodyValue(bytes)
               .exchangeToMono(resp -> resp.toEntity(byte[].class))
    ).map(resp -> {
      // Ensure stickiness cookie is set (if we created one)
      if (exchange.getRequest().getCookies().getFirst("canary-sticky") == null) {
        exchange.getResponse().addCookie(ResponseCookie.from("canary-sticky", sticky)
                .httpOnly(true).path("/").maxAge(Duration.ofDays(30)).build());
      }
      return resp;
    });
  }

  private HttpHeaders safeHeaders(HttpHeaders in) {
    HttpHeaders h = new HttpHeaders();
    in.forEach((k, v) -> {
      // drop hop-by-hop headers; keep others
      if (Objects.equals(k, HttpHeaders.HOST) || Objects.equals(k, "Content-Length") || Objects.equals(k, "Connection")) return;
      h.put(k, v);
    });
    return h;
  }

  private String stickyKey(ServerWebExchange ex) {
    var cookie = ex.getRequest().getCookies().getFirst("canary-sticky");
    if (cookie != null) return cookie.getValue();
    String hdr = ex.getRequest().getHeaders().getFirst("X-User-Id");
    if (hdr != null) return hdr;
    String remote = ex.getRequest().getRemoteAddress() == null ? "" : ex.getRequest().getRemoteAddress().getAddress().getHostAddress();
    return remote.isBlank() ? Integer.toHexString(rnd.nextInt()) : remote;
  }

  private boolean chooseCanary(String stickyKey) {
    int pct = cfg.canaryPercent.get();
    if (pct <= 0) return false;
    if (pct >= 100) return true;
    int h = stickyKey.hashCode() & 0x7fffffff; // stable non-negative
    int bucket = h % 100;
    return bucket < pct;
  }
}
```

**How to use the sample**

-   Run the router with env vars `STABLE_BASE=http://stable:8080`, `CANARY_BASE=http://canary:8080`.
    
-   Start with `CANARY_PERCENT=1` (1% traffic).
    
-   Send requests with a consistent `X-User-Id` header and confirm stickiness via `X-Canary-Routed` response header.
    
-   Adjust weight live:
    
    -   `POST /__canary/percent/5` → 5%
        
    -   `POST /__canary/toggle/false` → emergency disable
        
    -   `GET  /__canary/status` → inspect counters and config
        

> In production, replace counters with Micrometer/Prometheus, add TLS/mTLS, request limits, structured logging, and health checks. Most teams implement traffic shifting at a **gateway/mesh** (NGINX, Envoy, Istio, AWS ALB/NGW) and keep app code agnostic; this sample shows the logic in Java when you *do* need it in-process.

## Known Uses

-   **Netflix / Spinnaker:** Red/black + canaries with automated judgments on metrics.
    
-   **Google, AWS, Microsoft:** Managed canary/traffic-shifting in Cloud Run, App Engine, App Mesh, ALB, API Gateway.
    
-   **E-commerce & fintech:** Regional or tenant-based canaries before global rollout; KPI-gated promotion.
    

## Related Patterns

-   **Blue-Green Deployment:** Two full environments with an *atomic* switch; canary is *gradual*.
    
-   **Feature Toggle / Flag:** Enable features for cohorts inside a version; complementary to canaries.
    
-   **Shadow Deployment:** Duplicate traffic to vNext but do not serve responses from it.
    
-   **Circuit Breaker / Bulkhead / Rate Limiting:** Guardrails while the canary bakes.
    
-   **Rollback / Automated Judgments:** Controllers that revert on SLO breaches.

