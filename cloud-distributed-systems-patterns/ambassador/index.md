# Ambassador — Cloud / Distributed Systems Pattern

## Pattern Name and Classification

**Ambassador** — *Cloud / Distributed Systems* pattern. A **sidecar/neighbor process** that handles cross-cutting **service-to-service communication concerns** (timeouts, TLS/mTLS, retries, circuit breaking, auth, telemetry, discovery), so the application stays simple.

---

## Intent

Offload complex and evolving **outbound connectivity logic** from an application into a **co-located “ambassador”** (same host, pod, or VM). The app talks to the ambassador over loopback/IPC; the ambassador talks to remote services reliably and observably.

---

## Also Known As

-   **Sidecar (Outbound)**

-   **Out-of-Process Proxy**

-   **Client Proxy / Service Mesh Sidecar** (e.g., Envoy/Linkerd for egress)


---

## Motivation (Forces)

-   Client libraries for retries/TLS/circuit breakers differ per language and version.

-   Security teams want **centralized control** (cert rotation, mTLS, token minting).

-   SREs need **uniform telemetry** and policy enforcement.

-   Product teams want to avoid **re-implementing** connectivity in every service.


**Tensions:** Library vs proxy; performance vs isolation; per-team control vs platform guardrails.

---

## Applicability

Use the Ambassador when:

-   You run many services and want **consistent** outbound behavior and **policy**.

-   You need to add features (mTLS, OAuth2, egress allow-lists, retries) **without touching app code**.

-   You’re moving toward a **service mesh** but want a lighter step first.


Avoid when:

-   You already standardized on **mesh sidecars** that cover your needs.

-   Ultra-low latency in-process calls matter more than isolation/configurability.


---

## Structure

```pgsql
+--------------------+        loopback        +--------------------+       secure network       +------------------+
|  Application       | ───────── HTTP ──────▶ |  Ambassador/Proxy  | ───────── HTTPS ─────────▶ |  Upstream Service |
| (simple client)    |                        | (sidecar)          |                            |  (cluster)        |
| - speaks plain     |◀── metrics/logs/traces | - retries, CB, TLS | ◀── responses             |                  |
+--------------------+                        +--------------------+                            +------------------+
```

---

## Participants

-   **Application** — issues local requests (localhost or Unix socket).

-   **Ambassador (Proxy/Sidecar)** — performs **auth, mTLS, retries, timeouts, circuit breaking, load balancing, telemetry, egress policy**.

-   **Upstream Service** — remote target(s), often discovered via DNS/registry.

-   **Control Plane (optional)** — pushes policy/certs to ambassadors.


---

## Collaboration

1.  App sends a **simple HTTP** request to `http://127.0.0.1:9000/...`.

2.  Ambassador **enriches** the request (headers/tokens), enforces **policy**, applies **timeout/retry/CB**, and forwards to an **upstream**.

3.  Ambassador emits **metrics/traces/logs** and returns the response to the app.


---

## Consequences

**Benefits**

-   Consistent, centrally managed **resilience & security** for outbound traffic.

-   **Polyglot friendly**: app logic stays clean; no heavy client libs.

-   Enables **progressive delivery** of connectivity features (flip via config).


**Liabilities**

-   Extra **hop** and a **process** to manage.

-   Needs careful **resource limits** and **observability** to avoid being a bottleneck.

-   Local proxy must be **highly reliable**; failures impact the app.


---

## Implementation (Key Points)

-   Run ambassador **co-located** (sidecar container, systemd unit, or process) and expose a **local port**.

-   Use **short, bounded timeouts**, **limited retries with backoff**, and a **simple circuit breaker**.

-   Support **mTLS** (client certs), **token acquisition/refresh**, and **header signing** if needed.

-   Emit **metrics** (success/latency/retries/Circuit state) and **trace context** propagation.

-   Keep config dynamic (env vars, hot reload).

-   Validate **egress allow-lists** / destination policies.


---

## Sample Code (Java 17) — Minimal Local Ambassador Proxy

> A tiny HTTP proxy process (run next to your app) that:  
> • Listens on `localhost:9000`  
> • Forwards to `UPSTREAM_BASE` (e.g., `https://orders.internal`)  
> • Adds an `Authorization` header from `TOKEN` (or mints one)  
> • Enforces **timeouts**, **retries with exponential backoff**, and a **circuit breaker**  
> • Exposes `/__health` and `/__metrics`

```java
import com.sun.net.httpserver.HttpServer;
import com.sun.net.httpserver.HttpExchange;

import java.io.*;
import java.net.*;
import java.net.http.*;
import java.time.*;
import java.util.Map;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

public class AmbassadorProxy {

  // --- Config via env ---
  static final String UPSTREAM_BASE = env("UPSTREAM_BASE", "https://httpbin.org");
  static final String TOKEN = env("TOKEN", "");
  static final int LISTEN_PORT = Integer.parseInt(env("LISTEN_PORT", "9000"));
  static final int CONNECT_TIMEOUT_MS = Integer.parseInt(env("CONNECT_TIMEOUT_MS", "1000"));
  static final int READ_TIMEOUT_MS = Integer.parseInt(env("READ_TIMEOUT_MS", "2000"));
  static final int MAX_RETRIES = Integer.parseInt(env("MAX_RETRIES", "2"));

  // --- Simple circuit breaker ---
  static final int CB_FAILURE_THRESHOLD = Integer.parseInt(env("CB_FAILURE_THRESHOLD", "5"));
  static final long CB_OPEN_MS = Long.parseLong(env("CB_OPEN_MS", "10000"));
  enum CBState { CLOSED, OPEN, HALF_OPEN }
  static volatile CBState cbState = CBState.CLOSED;
  static final AtomicInteger cbFailures = new AtomicInteger(0);
  static volatile long cbOpenedAt = 0;

  // --- Metrics ---
  static final AtomicLong total = new AtomicLong();
  static final AtomicLong success = new AtomicLong();
  static final AtomicLong retried = new AtomicLong();
  static final AtomicLong failed = new AtomicLong();
  static final AtomicLong cbOpenRejects = new AtomicLong();

  static final HttpClient client = HttpClient.newBuilder()
      .connectTimeout(Duration.ofMillis(CONNECT_TIMEOUT_MS))
      .version(HttpClient.Version.HTTP_1_1)
      .build();

  public static void main(String[] args) throws Exception {
    HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", LISTEN_PORT), 0);
    server.createContext("/__health", ex -> respond(ex, 200, "OK\n"));
    server.createContext("/__metrics", AmbassadorProxy::metrics);
    server.createContext("/", AmbassadorProxy::handle);
    server.setExecutor(Executors.newCachedThreadPool());
    System.out.println("[Ambassador] listening on http://127.0.0.1:" + LISTEN_PORT + " -> " + UPSTREAM_BASE);
    server.start();
  }

  static void handle(HttpExchange ex) throws IOException {
    total.incrementAndGet();

    // Circuit breaker check
    if (isCircuitOpen()) {
      cbOpenRejects.incrementAndGet();
      respond(ex, 503, "CircuitOpen\n");
      return;
    }

    String pathAndQuery = ex.getRequestURI().toString(); // includes path + query
    if (pathAndQuery.startsWith("/__")) { respond(ex, 404, "Not Found\n"); return; }

    // Build upstream request
    String target = joinUrl(UPSTREAM_BASE, pathAndQuery);
    HttpRequest.Builder b = HttpRequest.newBuilder(URI.create(target))
        .timeout(Duration.ofMillis(READ_TIMEOUT_MS))
        .method(ex.getRequestMethod(), bodyPublisher(ex.getRequestBody()));

    // Copy selected headers and inject auth/trace
    ex.getRequestHeaders().forEach((k, v) -> {
      if (hopByHop(k)) return;
      v.forEach(val -> b.header(k, val));
    });
    if (!TOKEN.isBlank()) b.header("Authorization", "Bearer " + TOKEN);

    // Propagate a minimal trace header if missing
    if (!ex.getRequestHeaders().containsKey("X-Request-Id")) {
      b.header("X-Request-Id", java.util.UUID.randomUUID().toString());
    }

    // Try with retries + backoff
    int attempt = 0;
    while (true) {
      attempt++;
      try {
        HttpResponse<byte[]> resp = client.send(b.build(), HttpResponse.BodyHandlers.ofByteArray());
        // Success path
        if (resp.statusCode() >= 200 && resp.statusCode() < 500) {
          onSuccess();
          mirrorResponse(ex, resp);
          return;
        }
        // Retry on selected 5xx
        if (attempt <= MAX_RETRIES && isRetryable(resp.statusCode())) {
          retried.incrementAndGet();
          sleepBackoff(attempt);
          continue;
        }
        // Non-retryable or exhausted
        onFailure();
        mirrorResponse(ex, resp);
        return;
      } catch (IOException | InterruptedException e) {
        if (attempt <= MAX_RETRIES) {
          retried.incrementAndGet();
          sleepBackoff(attempt);
          continue;
        } else {
          onFailure();
          respond(ex, 502, "UpstreamError: " + e.getClass().getSimpleName() + "\n");
          return;
        }
      }
    }
  }

  // --- Helpers ---

  static void onSuccess() {
    success.incrementAndGet();
    if (cbState != CBState.CLOSED) {
      // close/reset breaker on success while half-open
      cbState = CBState.CLOSED;
      cbFailures.set(0);
    }
  }

  static void onFailure() {
    failed.incrementAndGet();
    int f = cbFailures.incrementAndGet();
    if (cbState == CBState.CLOSED && f >= CB_FAILURE_THRESHOLD) {
      cbState = CBState.OPEN; cbOpenedAt = System.currentTimeMillis();
    } else if (cbState == CBState.HALF_OPEN) {
      cbState = CBState.OPEN; cbOpenedAt = System.currentTimeMillis();
    }
  }

  static boolean isCircuitOpen() {
    if (cbState == CBState.OPEN) {
      if (System.currentTimeMillis() - cbOpenedAt > CB_OPEN_MS) {
        cbState = CBState.HALF_OPEN; // allow a trial request
        return false;
      }
      return true;
    }
    return false;
  }

  static boolean isRetryable(int code) {
    return code == 502 || code == 503 || code == 504;
  }

  static void sleepBackoff(int attempt) {
    long ms = Math.min(1000L * (1L << (attempt - 1)), 4000L); // 1s,2s,4s cap
    try { Thread.sleep(ms); } catch (InterruptedException ignored) {}
  }

  static HttpRequest.BodyPublisher bodyPublisher(InputStream is) throws IOException {
    byte[] body = is.readAllBytes();
    return (body.length == 0) ? HttpRequest.BodyPublishers.noBody()
                              : HttpRequest.BodyPublishers.ofByteArray(body);
  }

  static void mirrorResponse(HttpExchange ex, HttpResponse<byte[]> resp) throws IOException {
    var headers = ex.getResponseHeaders();
    resp.headers().map().forEach((k, vals) -> {
      if (hopByHop(k)) return;
      headers.put(k, vals);
    });
    ex.sendResponseHeaders(resp.statusCode(), resp.body().length);
    try (OutputStream os = ex.getResponseBody()) { os.write(resp.body()); }
  }

  static void respond(HttpExchange ex, int status, String body) throws IOException {
    byte[] bytes = body.getBytes();
    ex.getResponseHeaders().add("Content-Type", "text/plain; charset=utf-8");
    ex.sendResponseHeaders(status, bytes.length);
    try (OutputStream os = ex.getResponseBody()) { os.write(bytes); }
  }

  static void metrics(HttpExchange ex) throws IOException {
    String m = ""
        + "ambassador_total " + total.get() + "\n"
        + "ambassador_success " + success.get() + "\n"
        + "ambassador_retried " + retried.get() + "\n"
        + "ambassador_failed " + failed.get() + "\n"
        + "ambassador_cb_state " + cbState + "\n"
        + "ambassador_cb_open_rejects " + cbOpenRejects.get() + "\n";
    respond(ex, 200, m);
  }

  static String joinUrl(String base, String pathAndQuery) {
    if (base.endsWith("/") && pathAndQuery.startsWith("/")) return base.substring(0, base.length()-1) + pathAndQuery;
    if (!base.endsWith("/") && !pathAndQuery.startsWith("/")) return base + "/" + pathAndQuery;
    return base + pathAndQuery;
  }

  static boolean hopByHop(String h) {
    String k = h.toLowerCase();
    return k.equals("connection") || k.equals("keep-alive") || k.equals("proxy-authenticate") ||
           k.equals("proxy-authorization") || k.equals("te") || k.equals("trailers") ||
           k.equals("transfer-encoding") || k.equals("upgrade");
  }

  static String env(String k, String def) {
    String v = System.getenv(k);
    return v == null || v.isBlank() ? def : v;
  }
}
```

**How to try it (locally)**

1.  Run the proxy:  
    `UPSTREAM_BASE=https://httpbin.org LISTEN_PORT=9000 java AmbassadorProxy.java`

2.  From your app or curl:  
    `curl -v http://127.0.0.1:9000/get?x=1`

3.  See health/metrics:  
    `curl http://127.0.0.1:9000/__health` and `http://127.0.0.1:9000/__metrics`


> In Kubernetes, this would run as a **sidecar container** within the same Pod. Your app calls `http://localhost:9000` instead of the remote address; the sidecar enforces policy and resilience.

---

## Known Uses

-   **Service meshes** (Envoy/Linkerd/istio-proxy) acting as ambassadors for **mTLS, retries, traffic shaping**.

-   **API gateways as egress proxies** for outbound calls from legacy apps.

-   Platform teams providing **language-agnostic** outbound policies (headers, tokens, allow-lists) via sidecars.


---

## Related Patterns

-   **Sidecar** — general co-process pattern; Ambassador is the **outbound connectivity** flavored sidecar.

-   **API Gateway** — edge-facing front door; Ambassador is **client-side** for service egress.

-   **Circuit Breaker / Retry / Timeouts / Bulkhead** — resilience policies typically implemented by the ambassador.

-   **Proxy** — structural base; this is a specialized runtime proxy.

-   **Service Mesh** — large-scale realization; Ambassadors are the **data plane** proxies.
