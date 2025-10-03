# Service Mesh — Microservice Pattern

## Pattern Name and Classification

-   **Name:** Service Mesh
    
-   **Classification:** Platform/Infrastructure Pattern for **service-to-service networking** (traffic management, security, and observability)
    

## Intent

Shift **cross-cutting runtime concerns** (mTLS, retries, timeouts, circuit breaking, traffic shifting, authz, telemetry) **out of the application code** and into a dedicated **data plane** (sidecar proxies) governed by a **control plane**, so teams get **uniform policies** without changing each service.

## Also Known As

-   Sidecar Mesh
    
-   L7 Data Plane / mTLS Fabric
    
-   Zero-Trust Service Networking
    

## Motivation (Forces)

-   **Heterogeneous stacks:** Polyglot microservices need consistent security & traffic policies.
    
-   **Zero-trust:** Encrypt service-to-service by default with **mutual TLS** and strong identity.
    
-   **Operational control:** SREs need to **shift traffic**, do **canaries**, **A/B**, **fault injection**, and rate limits **without redeploying code**.
    
-   **Uniform telemetry:** Standardized **traces/metrics/logs** per request hop.
    
-   **Developer focus:** Keep business code free from boilerplate resilience/security libraries.
    

**Tensions**

-   **Overhead:** Added **latency (~hundreds of µs–few ms)** and **resource cost** per pod.
    
-   **Complexity:** New moving parts (control plane, sidecars), version skew, policy sprawl.
    
-   **Failure modes:** Proxy/iptables misconfig, certificate rotation issues, policy misfits for exotic protocols.
    

## Applicability

Use a mesh when:

-   Many services across languages/teams and you need **uniform** L7 policy.
    
-   You require **mTLS everywhere**, **fine-grained authZ**, and **dynamic traffic shaping**.
    
-   You want **no-code** (or low-code) resiliency: retries, timeouts, outlier detection.
    

Consider alternatives when:

-   Small system or monolith; a gateway + library (e.g., Resilience4j) may suffice.
    
-   Ultra-low-latency (< sub-ms budgets) or proprietary protocols not supported by your mesh.
    
-   Platform maturity (ops/Observability) is insufficient to operate a mesh reliably.
    

## Structure

-   **Data Plane:** One proxy (e.g., **Envoy**, linkerd-proxy) per workload (sidecar) intercepts inbound/outbound traffic.
    
-   **Control Plane:** Central brain (e.g., **Istio (istiod)**, **Linkerd control plane**, **Consul**, **Kuma**) distributes config, certs, and policies.
    
-   **Ingress/Egress Gateways:** Managed edges for north-south and controlled egress.
    
-   **Policy/Telemetry:** CRDs or configs for routing, resiliency, security, and metrics.
    

```scss
[Client] → Ingress GW → (Sidecar) Service A ↔ (Sidecar) Service B ↔ (Sidecar) Service C
                           ▲ mTLS + Policy + Telemetry via Control Plane ▼
```

## Participants

-   **Workload/Service:** Your application container.
    
-   **Sidecar Proxy:** Local L7 proxy enforcing policy, doing mTLS, retries, CB, metrics.
    
-   **Control Plane:** Issues workload identities/certs; pushes xDS config (routes, clusters, policies).
    
-   **Gateways:** Mesh-managed egress/ingress.
    
-   **Policy Objects:** Routes, DestinationRules, AuthorizationPolicies, PeerAuthentication, RateLimit, etc.
    
-   **Observability Backends:** Prometheus, Grafana, tracing (Jaeger/Tempo/Zipkin), log sinks.
    

## Collaboration

1.  **Provisioning:** Sidecar is injected; receives **identity cert** and config from control plane.
    
2.  **Call flow:** App issues a normal HTTP/gRPC call → sidecar intercepts → enforces **mTLS**, **authZ**, **circuit breaker**, **timeouts**, **retries**, **traffic split** → forwards to peer’s sidecar → target app.
    
3.  **Telemetry:** Proxies emit **standard metrics/traces/logs** per hop.
    
4.  **Changes:** Operators adjust routing/limits/policies centrally; sidecars update live.
    

## Consequences

**Benefits**

-   **No-code**, consistent **security** (mTLS by default), **resilience**, **traffic control**, and **telemetry**.
    
-   Enables progressive delivery (**canary**, **blue/green**, **shadowing**) and chaos/fault injection.
    
-   Clear separation of concerns: platform owns networking; services own business logic.
    

**Liabilities**

-   **Runtime overhead** (CPU/memory, latency), extra hops.
    
-   Operational complexity (cert rotation, upgrades, config drift).
    
-   Requires good **governance** to avoid policy conflicts and “mesh sprawl”.
    
-   Some protocols/features may need bypass or special handling.
    

## Implementation

1.  **Pick a mesh:** Istio, Linkerd, Consul, Kuma (Envoy).
    
2.  **Identity & mTLS:** Enable strict **PeerAuthentication** (Istio) or global mTLS (Linkerd).
    
3.  **Sidecar injection:** Auto-inject per namespace; standardize labels/annotations.
    
4.  **Traffic policy:** Define **timeouts**, **retries**, **outlier detection**, **circuit breaking**, **connection pools** at the mesh.
    
5.  **Traffic shifting:** Use **VirtualService/DestinationRule** (Istio) or ServiceProfiles (Linkerd) for canaries, header-based routing, mirroring.
    
6.  **AuthZ:** AuthorizationPolicy/Intentions (RBAC), least privilege between workloads.
    
7.  **Observability:** Scrape proxy metrics, enable access logs, tracing headers propagation (app should pass them).
    
8.  **Governance:** Version config via GitOps, lint policies, establish SLOs (p50/p95/p99, error rate), and guardrails (e.g., retry caps).
    
9.  **Failure planning:** Golden paths to **bypass mesh** if needed, clear runbooks for cert/sidecar outages.
    
10.  **Multi-cluster/tenant:** Use gateways or mesh expansion; unify identities and trust domains.
    

### Example (Istio CRDs, abbreviated)

```yaml
# Enforce STRICT mTLS in namespace
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata: { name: default, namespace: shop }
spec:
  mtls: { mode: STRICT }

---
# Resilience and TLS policy to 'catalog' service
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata: { name: catalog, namespace: shop }
spec:
  host: catalog.shop.svc.cluster.local
  trafficPolicy:
    tls: { mode: ISTIO_MUTUAL }
    connectionPool:
      http: { http1MaxPendingRequests: 1000, maxRequestsPerConnection: 100 }
      tcp:  { maxConnections: 200 }
    outlierDetection:
      consecutive5xxErrors: 5
      interval: 5s
      baseEjectionTime: 1m
      maxEjectionPercent: 50
    retries:
      attempts: 3
      perTryTimeout: 800ms
      retryOn: 5xx,connect-failure,gateway-error

---
# Canary 90/10 and header-based stickiness
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata: { name: catalog, namespace: shop }
spec:
  hosts: [ "catalog" ]
  http:
    - match:
        - headers:
            x-sticky-user:
              exact: "beta"
      route:
        - destination: { host: catalog, subset: v2 } # direct beta users to v2
    - route:
        - destination: { host: catalog, subset: v1, port: { number: 8080 } }
          weight: 90
        - destination: { host: catalog, subset: v2, port: { number: 8080 } }
          weight: 10
      timeout: 3s

---
# RBAC: only 'orders' may call 'payment'
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata: { name: payment-allow-orders, namespace: shop }
spec:
  selector: { matchLabels: { app: payment } }
  rules:
    - from:
        - source:
            principals: [ "spiffe://mesh.local/ns/shop/sa/orders-sa" ]
```

> Tip: keep **client-side retries minimal** if the mesh already retries; double-retries cause storms. Prefer **deadlines** in code and **retries in mesh**.

## Sample Code (Java) — “Mesh-friendly” HTTP client

The mesh handles **mTLS**, **retries**, **CB**, and **routing**; your code should:

-   set **short, explicit timeouts/deadlines**

-   propagate **correlation headers** (`X-Request-ID`, `traceparent` if using tracing)

-   **avoid client retries** when mesh retries are configured


```java
// JDK 11+ HttpClient, single-attempt with deadline; rely on mesh for retries/CB/mTLS.
package mesh.sample;

import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.UUID;

public class CatalogClient {
  private final HttpClient http = HttpClient.newBuilder()
      .connectTimeout(Duration.ofSeconds(1))
      .build();

  // K8s service DNS; mesh sidecars intercept transparently.
  private final String base = "http://catalog.shop.svc.cluster.local:8080";

  public String getProduct(String sku) throws Exception {
    String requestId = UUID.randomUUID().toString();
    HttpRequest req = HttpRequest.newBuilder()
        .uri(URI.create(base + "/products/" + sku))
        .timeout(Duration.ofSeconds(2))           // per-try timeout (single try)
        .header("X-Request-ID", requestId)        // correlation
        // if your app uses tracing, add 'traceparent' via your tracer; omitted here
        .GET()
        .build();

    // No client-side retry; if it fails, bubble up and let callers decide.
    HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
    int sc = resp.statusCode();
    if (sc >= 200 && sc < 300) return resp.body();
    if (sc == 503 || sc == 429) {
      // Mesh may be shedding load; caller can choose a fallback or queue.
      throw new RuntimeException("temporary unavailability: " + sc);
    }
    throw new RuntimeException("error " + sc + ": " + resp.body());
  }
}
```

> If you use **OpenTelemetry**, add a filter/interceptor to inject `traceparent` so the mesh (and downstream) can correlate traces; keep retries off in code when mesh manages them.

## Known Uses

-   **Istio/Envoy** widely adopted for enterprise meshes enabling **mTLS by default**, traffic shifting, and rich telemetry.

-   **Linkerd** emphasizes simplicity and low overhead for Kubernetes-only workloads.

-   **Consul Service Mesh** integrates with Consul KV/Intentions for multi-platform environments.

-   **Kuma** (Envoy) provides CRDs and multi-zone meshes with a simple UX.


## Related Patterns

-   **Sidecar** (structural pattern enabling the mesh data plane)

-   **API Gateway / BFF** (edge composition; complements mesh’s east-west control)

-   **Circuit Breaker / Retry / Timeout** (implemented uniformly by the mesh)

-   **Zero-Trust Networking / mTLS** (security foundation the mesh automates)

-   **Blue-Green / Canary / Traffic Shadowing** (progressive delivery via routing rules)

-   **Distributed Tracing & Log Enrichment** (proxies propagate/emit IDs; apps should pass them)

-   **Database per Service / Polyglot Persistence** (mesh isolates network, not data; used together)


---

**Practical notes**

-   Start with **mTLS STRICT**, **basic retries**, **timeouts**, **outlier detection**, and **RBAC**.

-   Add **progressive delivery** (canary) and **rate limits** once baselines are stable.

-   Keep a **bypass path** and clear **runbooks** for cert/sidecar issues.
