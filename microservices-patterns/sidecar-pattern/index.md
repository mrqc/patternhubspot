# Sidecar — Microservice Pattern

## Pattern Name and Classification

-   **Name:** Sidecar
    
-   **Classification:** Deployment & Runtime Composition Pattern (process-per-pod helper)
    

## Intent

Co-locate a **helper process** with a service (usually in the same pod/host) to offload **cross-cutting concerns**—mTLS, retries, circuit breaking, auth token exchange, config reload, telemetry shipping—**without changing business code** or libraries.

## Also Known As

-   **Sidecar Container / Helper**
    
-   **Per-Pod Agent**
    
-   **Co-process** (single VM/host)
    

## Motivation (Forces)

-   **Polyglot stacks:** Consistent security/traffic/telemetry across Java, Node, Go, etc.
    
-   **Separation of concerns:** Keep business code minimal; move infra logic to a standard component.
    
-   **Runtime uniformity:** Enforce org-wide policies (mTLS, RBAC, retries) centrally.
    
-   **Operational safety:** Hot-swap/upgrade the helper independently of the app.
    

**Tensions**

-   **Overhead:** Extra container/process, CPU/RAM, small latency.
    
-   **Complexity:** More moving parts; life-cycle coordination (startup/shutdown).
    
-   **Observability:** Two places to debug.
    
-   **Coupling-by-assumption:** Apps must speak to the sidecar (ports/paths), which is a form of local contract.
    

## Applicability

Use when:

-   You need **uniform** L7 networking/security/observability across heterogeneous services.
    
-   Teams shouldn’t embed infra libraries (or can’t, due to language/runtime constraints).
    
-   Concerns evolve **faster** than your services (e.g., rotate crypto/mTLS, change retry policy).
    

Reconsider when:

-   Ultra-low latency budgets (sub-ms) and every hop matters.
    
-   Very small system where a shared library is simpler.
    
-   Platform already provides the concern elsewhere (e.g., service mesh sidecars—then you already *have* a sidecar).
    

## Structure

```pgsql
+----------------------+        localhost                +----------------------+
 |   App Container      |  <--------------------------->  |   Sidecar Container  |
 |  (business logic)    |        HTTP/gRPC/UNIX sock      | (proxy/agent/helper) |
 |  :8080               |                                  | :15000 / :9090       |
 +----------^-----------+                                  +----------^-----------+
            |                                                          |
            | outbound to localhost                                    | outbound to remote
            |                                                          | (mTLS, retries, auth)
            v                                                          v
                           +------------------ network --------------------+
```

## Participants

-   **Application**: Your service code; talks to the sidecar over localhost/loopback.
    
-   **Sidecar**: Proxy/agent providing cross-cutting capability (Envoy/linkerd-proxy, OTel collector, Vault agent, OAuth/ST S token broker, log shipper, config reloader).
    
-   **Control/Config Plane (optional)**: Manages sidecar config/certs (e.g., mesh control plane, Vault, GitOps).
    

## Collaboration

1.  Pod/host starts both containers/processes; sidecar becomes **ready** first.
    
2.  App uses **localhost** to:
    
    -   send outbound traffic **through** the sidecar (which does mTLS, retries, LB), or
        
    -   **ask** the sidecar for things (e.g., `GET /token`, `GET /config`).
        
3.  Sidecar enforces policy, emits telemetry, rotates secrets; app remains untouched.
    
4.  On shutdown, drain traffic and terminate sidecar after the app (or vice-versa, per design).
    

## Consequences

**Benefits**

-   **No-code** adoption of infra features across all services.
    
-   **Safer upgrades**: update proxy/agent without changing the app.
    
-   **Consistency**: one place to tune retries, TLS, policies, and telemetry.
    

**Liabilities**

-   **Extra resources & latency** per pod/host.
    
-   **Coordination risk** (readiness ordering, port clashes).
    
-   **Local contract** to the sidecar API must be versioned and documented.
    

## Implementation

1.  **Define the concern** to externalize (e.g., outbound mTLS+retries, token exchange, log shipping).
    
2.  **Pick the sidecar** (Envoy/Linkerd proxy, OTel Collector, Vault Agent, OAuth token sidecar, Fluent Bit, config reloader).
    
3.  **Co-locate**: run alongside the app (Kubernetes pod with two containers; on VMs, two systemd units sharing loopback/IPC).
    
4.  **Ports & contracts**: reserve local ports (e.g., `:15000` proxy, `:9090` token API).
    
5.  **Readiness & lifecycle**: make sidecar ready **before** app accepts traffic; graceful drain on shutdown.
    
6.  **Security**: least-privilege for sidecar (e.g., only outbound egress), mount only its secrets, separate user/UID.
    
7.  **Observability**: expose sidecar metrics; label by owning service/pod.
    
8.  **Governance**: version sidecar image/config; roll with canaries; document the app↔sidecar API.
    

---

## Sample Code (Java) — “Sidecar-aware” client patterns

Below are two minimal patterns that keep business code simple while leveraging a sidecar:

### A) Use a **local HTTP proxy sidecar** for outbound calls (retries, mTLS, outlier detection handled by proxy)

```java
// HttpViaLocalProxy.java
package sidecar.sample;

import java.net.*;
import java.net.http.*;
import java.time.Duration;
import java.util.List;

public class HttpViaLocalProxy {

  // Route ALL HTTP(S) through the sidecar proxy running on localhost:15000 (e.g., Envoy)
  private static final ProxySelector LOCAL_PROXY = new ProxySelector() {
    private final List<Proxy> proxies = List.of(new Proxy(Proxy.Type.HTTP, new InetSocketAddress("127.0.0.1", 15000)));
    @Override public List<Proxy> select(URI uri) { return proxies; }
    @Override public void connectFailed(URI uri, SocketAddress sa, IOException ioe) { /* log if desired */ }
  };

  private final HttpClient http = HttpClient.newBuilder()
      .proxy(LOCAL_PROXY)
      .connectTimeout(Duration.ofSeconds(2))
      .build();

  public String getProduct(String baseUrl, String sku) throws Exception {
    var req = HttpRequest.newBuilder()
        .uri(URI.create(baseUrl + "/products/" + sku))
        .timeout(Duration.ofSeconds(3)) // keep app timeouts short; sidecar does retries/CB
        .header("X-Request-ID", java.util.UUID.randomUUID().toString())
        .GET()
        .build();

    var resp = http.send(req, HttpResponse.BodyHandlers.ofString());
    if (resp.statusCode() / 100 == 2) return resp.body();
    throw new RuntimeException("upstream error " + resp.statusCode());
  }
}
```

**How it helps:** the app does *one* attempt with a clear deadline; the sidecar proxy handles **mTLS, retries, timeouts, circuit breaking, traffic policies** centrally.

---

### B) Use a **local token sidecar** to obtain OAuth/JWT and call upstream with `Authorization: Bearer …`

```java
// TokenSidecarClient.java
package sidecar.sample;

import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.Map;

public class TokenSidecarClient {
  private final HttpClient http = HttpClient.newBuilder()
      .connectTimeout(Duration.ofSeconds(1))
      .build();

  /** Ask the sidecar (localhost:9090) for a token bound to an audience/scope; sidecar handles refresh/rotation. */
  public String getToken(String audience) throws Exception {
    var req = HttpRequest.newBuilder()
        .uri(URI.create("http://127.0.0.1:9090/token?aud=" + URLEncoder.encode(audience, java.nio.charset.StandardCharsets.UTF_8)))
        .timeout(Duration.ofSeconds(2))
        .GET().build();

    var resp = http.send(req, HttpResponse.BodyHandlers.ofString());
    if (resp.statusCode() != 200) throw new RuntimeException("token sidecar error: " + resp.statusCode());
    // assume JSON: {"access_token":"...","expires_in":3600}
    var json = new com.fasterxml.jackson.databind.ObjectMapper().readValue(resp.body(), Map.class);
    return (String) json.get("access_token");
  }

  /** Example: call upstream API using the token from sidecar. */
  public String callUpstream(String apiBase, String path, String audience) throws Exception {
    String token = getToken(audience);
    var req = HttpRequest.newBuilder()
        .uri(URI.create(apiBase + path))
        .timeout(Duration.ofSeconds(3))
        .header("Authorization", "Bearer " + token)
        .GET().build();
    var resp = http.send(req, HttpResponse.BodyHandlers.ofString());
    if (resp.statusCode() / 100 == 2) return resp.body();
    throw new RuntimeException("upstream error " + resp.statusCode() + ": " + resp.body());
  }
}
```

**How it helps:** business code **never** implements OAuth dance/refresh; the sidecar caches/rotates tokens, can swap providers (Auth0, Keycloak, STS) transparently.

> In both patterns, the sidecar can be upgraded/retuned independently (retry policy, mTLS certs, token lifetimes), while app code remains unchanged.

---

## Known Uses

-   **Envoy/Linkerd sidecars** for per-pod L7 proxying (also the basis of **service meshes**).
    
-   **Vault Agent** sidecar for secret/template rendering and auto-renewal.
    
-   **OpenTelemetry Collector** sidecar for exporting traces/metrics/logs.
    
-   **Fluent Bit/Vector** sidecars for log shipping.
    
-   **OAuth/STS brokers** (custom or vendor) that issue per-request tokens locally.
    

## Related Patterns

-   **Service Mesh:** A fleet-wide application of the sidecar pattern for networking.
    
-   **Ambassador (Out-of-process Proxy):** Similar idea at process boundary for legacy apps.
    
-   **Externalized Configuration:** Sidecars can fetch/refresh config and expose it to the app.
    
-   **Circuit Breaker / Retry / Timeout:** Often implemented inside networking sidecars.
    
-   **Database per Service / Polyglot Persistence:** Sidecars can provide adapters (e.g., connection pooling, TLS).
    
-   **Adapter / Strangler Fig:** Sidecar can wrap legacy binaries, adding modern capabilities at the edge.
    

---

### (Optional) Kubernetes Deployment sketch (how it’s wired)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata: { name: orders, namespace: shop }
spec:
  replicas: 2
  selector: { matchLabels: { app: orders } }
  template:
    metadata: { labels: { app: orders } }
    spec:
      containers:
        - name: app
          image: ghcr.io/acme/orders:1.2.3
          ports: [ { containerPort: 8080 } ]
          env:
            - name: HTTP_PROXY    # App can also honor standard proxy envs
              value: http://127.0.0.1:15000
        - name: proxy-sidecar
          image: envoyproxy/envoy:v1.30.0
          args: [ "-c", "/etc/envoy/envoy.yaml" ]
          ports:
            - containerPort: 15000 # outbound proxy
          volumeMounts:
            - name: envoy-config
              mountPath: /etc/envoy
      volumes:
        - name: envoy-config
          configMap:
            name: envoy-config
```

This shows the basic wiring; your Java app just talks to **localhost** while the sidecar handles the heavy lifting.

