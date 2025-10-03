# Ambassador — Microservice Pattern

## Pattern Name and Classification

**Name:** Ambassador  
**Classification:** Microservices / Networking & Resilience / Sidecar Proxy

## Intent

Run a **co-located proxy** (sidecar) next to a service that **owns all communication concerns** to external systems—TLS, retries, timeouts, circuit breaking, auth tokens, rate limiting, telemetry—so application code stays clean and portable.

## Also Known As

-   Sidecar Proxy
    
-   Outbound Proxy / Outgoing Gateway
    
-   Service Mesh Sidecar (when managed by a mesh)
    
-   Per-Pod/Per-Instance Proxy
    

## Motivation (Forces)

-   **Separation of concerns:** Business code shouldn’t implement networking cross-cutting concerns.
    
-   **Uniform policy enforcement:** Centralize mTLS, auth, retries, timeouts, and backoff.
    
-   **Observability:** Standardize metrics/tracing/logging for all egress.
    
-   **Heterogeneous clients:** Different languages/frameworks still get consistent behavior via the same sidecar.
    
-   **Backward compatibility:** Wrap legacy services or brittle SDKs behind a robust proxy.
    
-   **Operational safety:** Feature flags, canaries, traffic shaping without redeploying the app.
    

## Applicability

Use Ambassador when:

-   Each service calls **external dependencies** (third-party APIs, shared internal APIs, databases via HTTP gRPC gateways) and you need **consistent** network behavior.
    
-   You are migrating to a **service mesh** or need mesh-like benefits without adopting a full mesh yet.
    
-   You want to wrap **legacy libraries** or **non-idempotent** clients with idempotency keys, retries, and circuit breakers.
    

Avoid or limit when:

-   Latency budgets are ultra-tight and an extra hop is unacceptable.
    
-   A centralized egress gateway already enforces all policies and per-pod proxies add little value.
    

## Structure

-   **Application Container:** Pure business logic; speaks plain HTTP/gRPC to localhost.
    
-   **Ambassador Sidecar:** Local proxy handling egress: TLS, retry/backoff, circuit breaker, token injection, request hedging, caching (optional), metrics/traces, rate limiting.
    
-   **Control/Config:** Rules pushed via config maps, env vars, or a control plane.
    
-   **Upstreams:** External/internal services.
    

```bash
[App Process] --http://localhost:15001--> [Ambassador Sidecar] ==mTLS/auth==> [Upstream Service(s)]
                                              | metrics/traces | retries | CB | RL |
```

## Participants

-   **Application** — calls `http://localhost:<sidecar-port>`.
    
-   **Ambassador** — terminates TLS, enriches headers, enforces policies, forwards to upstreams.
    
-   **Control Plane / Config** — provides destinations, tokens, limits, and timeouts.
    
-   **Upstream Services** — real targets (internal APIs, SaaS providers).
    
-   **Observability Stack** — collects logs/metrics/traces emitted by the sidecar.
    

## Collaboration

1.  App issues a request to the **local sidecar** (e.g., `/pay/charge?…`).
    
2.  Ambassador resolves routing, adds **auth headers**, **correlation IDs**, and enforces **rate limits**.
    
3.  Ambassador performs the remote call with **timeouts, retries with jitter**, and **circuit breaker**.
    
4.  Responses (or errors) return to the app with standardized error shapes and **trace IDs**.
    
5.  Metrics and spans are emitted for each hop.
    

## Consequences

**Benefits**

-   Clean application code; consistent, centrally governed network behavior.
    
-   Polyglot friendliness; every language benefits equally.
    
-   Safer rollouts (flagged retries, gradual timeouts, staged policies).
    
-   Drop-in **mTLS** and **zero-trust** posture without app changes.
    

**Liabilities**

-   Extra hop adds latency (usually a few ms).
    
-   More moving parts (process, config, health checks).
    
-   Risk of the sidecar becoming a **bottleneck** if under-provisioned.
    
-   Requires careful **policy versioning** and **backward compatibility**.
    

## Implementation

**Key practices**

-   **Local endpoint:** App talks to `localhost` to avoid DNS/egress issues.
    
-   **Policy first:** Default timeouts, capped retries with **exponential backoff + jitter**, and **idempotency** where safe.
    
-   **Circuit breaker:** Half-open probe windows; fast-fail when upstream is unhealthy.
    
-   **Auth/Tokens:** Inject OAuth2/JWT/API keys; refresh tokens in the sidecar.
    
-   **mTLS:** Terminate/originate TLS from the sidecar; manage cert rotation.
    
-   **Rate limiting & QoS:** Token bucket or leaky bucket per upstream/tenant.
    
-   **Observability:** Prometheus counters, histograms, OpenTelemetry spans; structured logs with correlation IDs.
    
-   **Config hot-reload:** Watch files or config service; validate before activation.
    
-   **Failure modes:** Return canonical errors to the app; expose readiness/liveness; implement egress deny-lists.
    

---

## Sample Code (Java — lightweight sidecar proxy)

> A minimal HTTP sidecar that:
> 
> -   Listens on localhost, forwards to configured upstream,
>     
> -   Adds `Authorization` and correlation headers,
>     
> -   Enforces timeout, **exponential backoff with jitter** retries,
>     
> -   Implements a small **circuit breaker**,
>     
> -   Emits simple metrics.  
>     For brevity, this uses the JDK HTTP server and `java.net.http.HttpClient`. Replace with Netty/Vert.x, add TLS keystores, Prometheus, and OpenTelemetry in production.
>     

```java
import com.sun.net.httpserver.*;
import java.io.*;
import java.net.*;
import java.net.http.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Supplier;

// ---------- Config ----------
final class AmbassadorConfig {
    final URI upstreamBase;               // e.g., https://payments.example.com
    final Duration requestTimeout = Duration.ofSeconds(3);
    final int maxRetries = 3;
    final Duration baseBackoff = Duration.ofMillis(200);
    final Duration maxBackoff = Duration.ofSeconds(2);
    final String authTokenEnv = "AMBASSADOR_TOKEN"; // injected via secret
    final String routePrefix;             // e.g., /pay -> /v1

    AmbassadorConfig(URI upstreamBase, String routePrefix) {
        this.upstreamBase = upstreamBase; this.routePrefix = routePrefix;
    }
}

// ---------- Circuit Breaker ----------
final class CircuitBreaker {
    enum State { CLOSED, OPEN, HALF_OPEN }
    private volatile State state = State.CLOSED;
    private final int failureThreshold;
    private final Duration openDuration;
    private int failures = 0;
    private long openedAt = 0L;

    CircuitBreaker(int failureThreshold, Duration openDuration) {
        this.failureThreshold = failureThreshold;
        this.openDuration = openDuration;
    }

    synchronized boolean allowRequest() {
        if (state == State.OPEN) {
            if (System.currentTimeMillis() - openedAt > openDuration.toMillis()) {
                state = State.HALF_OPEN; // allow one trial
                return true;
            }
            return false;
        }
        return true;
    }
    synchronized void onSuccess() {
        failures = 0;
        state = State.CLOSED;
    }
    synchronized void onFailure() {
        failures++;
        if (state == State.HALF_OPEN || failures >= failureThreshold) {
            state = State.OPEN; openedAt = System.currentTimeMillis();
        }
    }
    State state() { return state; }
}

// ---------- Simple Metrics ----------
final class Metrics {
    final ConcurrentHashMap<String, LongAdder> counters = new ConcurrentHashMap<>();
    void inc(String name) { counters.computeIfAbsent(name, k -> new LongAdder()).increment(); }
    String toText() {
        StringBuilder sb = new StringBuilder();
        counters.forEach((k,v) -> sb.append(k).append(" ").append(v.sum()).append("\n"));
        return sb.toString();
    }
}

// ---------- Ambassador Sidecar ----------
public class AmbassadorSidecar {
    private final AmbassadorConfig cfg;
    private final HttpClient client;
    private final CircuitBreaker cb = new CircuitBreaker(5, Duration.ofSeconds(10));
    private final Metrics metrics = new Metrics();
    private final Random rnd = new Random();

    public AmbassadorSidecar(AmbassadorConfig cfg) {
        this.cfg = cfg;
        this.client = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(2))
                .version(HttpClient.Version.HTTP_1_1)
                .build();
    }

    public void start(int port) throws IOException {
        HttpServer server = HttpServer.create(new InetSocketAddress("0.0.0.0", port), 0);
        server.createContext("/metrics", this::handleMetrics);
        server.createContext("/", this::handleProxy);
        server.setExecutor(Executors.newCachedThreadPool());
        server.start();
        System.out.println("Ambassador listening on http://localhost:" + port + " -> " + cfg.upstreamBase);
    }

    private void handleMetrics(HttpExchange ex) throws IOException {
        byte[] body = metrics.toText().getBytes();
        ex.getResponseHeaders().add("Content-Type", "text/plain");
        ex.sendResponseHeaders(200, body.length);
        try (OutputStream os = ex.getResponseBody()) { os.write(body); }
    }

    private void handleProxy(HttpExchange ex) throws IOException {
        String incomingPath = ex.getRequestURI().getPath();
        if (!incomingPath.startsWith(cfg.routePrefix)) {
            respond(ex, 404, "route not found");
            return;
        }
        if (!cb.allowRequest()) {
            metrics.inc("cb_open_drops");
            respond(ex, 503, "upstream unavailable (circuit open)");
            return;
        }

        String outboundPath = incomingPath.substring(cfg.routePrefix.length());
        if (outboundPath.isEmpty()) outboundPath = "/";
        URI target = cfg.upstreamBase.resolve(outboundPath + (ex.getRequestURI().getQuery() == null ? "" : "?" + ex.getRequestURI().getQuery()));

        // Build outbound request
        HttpRequest.Builder b = HttpRequest.newBuilder(target)
                .timeout(cfg.requestTimeout)
                .header("X-Correlation-Id", correlationId(ex))
                .header("User-Agent", "ambassador-sidecar/1.0");

        // Propagate method & body
        String method = ex.getRequestMethod();
        byte[] reqBody = ex.getRequestBody().readAllBytes();
        if (method.equalsIgnoreCase("GET") || method.equalsIgnoreCase("DELETE")) {
            b.method(method, HttpRequest.BodyPublishers.noBody());
        } else {
            b.method(method, HttpRequest.BodyPublishers.ofByteArray(reqBody));
        }

        // Inject auth if configured
        String token = System.getenv(cfg.authTokenEnv);
        if (token != null && !token.isBlank()) {
            b.header("Authorization", "Bearer " + token.trim());
        }

        // Copy selected headers (avoid hop-by-hop)
        for (var e : ex.getRequestHeaders().entrySet()) {
            String k = e.getKey();
            if (List.of("Host","Connection","Content-Length","Authorization").contains(k)) continue;
            for (String v : e.getValue()) b.header(k, v);
        }

        // Execute with retries + jitter
        try {
            HttpResponse<byte[]> resp = withRetries(() -> client.send(b.build(), HttpResponse.BodyHandlers.ofByteArray()));
            cb.onSuccess();
            metrics.inc("requests_ok");
            // Map response back
            for (var h : resp.headers().map().entrySet()) {
                for (String v : h.getValue()) ex.getResponseHeaders().add(h.getKey(), v);
            }
            ex.sendResponseHeaders(resp.statusCode(), resp.body().length);
            try (OutputStream os = ex.getResponseBody()) { os.write(resp.body()); }
        } catch (Exception e) {
            cb.onFailure();
            metrics.inc("requests_error");
            respond(ex, 502, "bad gateway: " + e.getClass().getSimpleName());
        }
    }

    private <T> T withRetries(Supplier<T> call) throws Exception {
        int attempt = 0;
        List<Class<?>> retryable = List.of(
                java.net.SocketTimeoutException.class,
                java.net.ConnectException.class,
                java.net.http.HttpTimeoutException.class
        );
        while (true) {
            attempt++;
            try {
                return call.get();
            } catch (Exception ex) {
                if (attempt > cfg.maxRetries || !isRetryable(ex, retryable)) throw ex;
                long delay = backoffWithJitter(attempt);
                metrics.inc("retries");
                Thread.sleep(delay);
            }
        }
    }

    private boolean isRetryable(Throwable ex, List<Class<?>> retryable) {
        for (Class<?> c : retryable) if (c.isInstance(ex)) return true;
        return false;
    }

    private long backoffWithJitter(int attempt) {
        long cap = Math.min(cfg.maxBackoff.toMillis(), (long)(cfg.baseBackoff.toMillis() * Math.pow(2, attempt-1)));
        return (long)(rnd.nextDouble() * cap); // full jitter
    }

    private String correlationId(HttpExchange ex) {
        var hdr = ex.getRequestHeaders().getFirst("X-Correlation-Id");
        return hdr != null ? hdr : UUID.randomUUID().toString();
    }

    private void respond(HttpExchange ex, int code, String msg) throws IOException {
        byte[] body = msg.getBytes();
        ex.getResponseHeaders().add("Content-Type", "text/plain");
        ex.sendResponseHeaders(code, body.length);
        try (OutputStream os = ex.getResponseBody()) { os.write(body); }
    }

    // ---- Bootstrap ----
    public static void main(String[] args) throws Exception {
        URI upstream = URI.create(System.getenv().getOrDefault("UPSTREAM_BASE", "https://httpbin.org"));
        String prefix = System.getenv().getOrDefault("ROUTE_PREFIX", "/api");
        var cfg = new AmbassadorConfig(upstream, prefix);
        new AmbassadorSidecar(cfg).start(Integer.parseInt(System.getenv().getOrDefault("SIDECAR_PORT", "15001")));
    }
}
```

**How to use the sample**

-   Run your app and call `http://localhost:15001/api/anything` → sidecar forwards to `UPSTREAM_BASE` (default `https://httpbin.org/anything`).
    
-   Export `AMBASSADOR_TOKEN` to inject `Authorization: Bearer <token>`.
    
-   Observe `/metrics` (very simple text metrics).
    
-   Tune `SIDECAR_PORT`, `UPSTREAM_BASE`, `ROUTE_PREFIX`.
    

> Production hardening: swap `HttpServer` for Netty/Undertow; add **mTLS** (keystore/truststore), **rate limiter** (token bucket), **Prometheus** histogram, **OpenTelemetry** spans, **config hot-reload**, and **per-upstream** policy tables.

## Known Uses

-   **Language-agnostic per-pod proxies** in Kubernetes before/without a full mesh (Envoy-based sidecars, NGINX sidecars).
    
-   **SaaS egress hardening:** wrapping fragile third-party APIs with retries, circuit break, token refresh.
    
-   **Zero-trust rollouts:** enforcing mTLS and egress policies locally before organization-wide adoption.
    
-   **Legacy client shielding:** apps using old HTTP stacks offload TLS 1.2+, SNI, and header normalization to the sidecar.
    

## Related Patterns

-   **Sidecar** (microservices decomposition): general pattern for co-processes.
    
-   **Service Mesh** (Istio/Linkerd/Consul): centralized control plane managing many ambassadors.
    
-   **API Gateway**: north-south edge; Ambassador is east-west egress per service.
    
-   **Circuit Breaker / Retry / Timeout / Bulkhead**: resilience primitives often implemented inside the Ambassador.
    
-   **Ambassador + Outbox/Inbox**: combine to get reliable external calls and delivery guarantees.

