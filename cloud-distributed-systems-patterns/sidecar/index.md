# Cloud Distributed Systems Pattern — Sidecar

## Pattern Name and Classification

-   **Name:** Sidecar

-   **Classification:** Structural / Deployment pattern for distributed systems (platform & infrastructure capability at the process/pod level)


## Intent

Attach a **separate helper process** to an application instance to provide cross-cutting capabilities (e.g., **mTLS, retries, timeouts, metrics, rate limiting, service discovery, config**, etc.) **without changing the app code**. The app talks to the sidecar (usually over `localhost`) and the sidecar talks to the world.

## Also Known As

-   Per-Pod Proxy / Data Plane (in service meshes)

-   Ambassador / Helper / Companion Process

-   Out-of-Process Agent


## Motivation (Forces)

-   **Cross-cutting concerns everywhere:** TLS, authN/Z, retries, backoff, circuit breaking, observability, configuration.

-   **Consistency vs. autonomy:** Teams want language freedom; platforms want uniform **reliability & security**.

-   **Separation of responsibilities:** App teams own business logic; platform team owns infra policies.

-   **Upgrades & policy rollout:** Update the sidecar to change behavior **without touching app binaries**.

-   **Resource isolation:** Limit noisy cross-cutting code inside the app; isolate via a separate process.

-   **Trade-off:** More processes per node/pod, more moving parts, need lifecycle coordination.


## Applicability

Use the Sidecar pattern when you need:

-   Uniform network policies (mTLS, authZ, rate limiting) across polyglot services.

-   **Transparent** client features (discovery, load balancing, retries) without changing app code.

-   **Observability**: consistent metrics/tracing/logging emission.

-   Gradual enablement of **mesh features** (traffic splitting, A/B, canary) per service.


Avoid or adapt when:

-   Extremely latency-sensitive services (extra hop may be too costly).

-   Very simple deployments (overhead not justified).

-   Strict environments where multiple processes per unit are disallowed.


## Structure

-   **Application Container/Process:** Business logic; calls sidecar on `localhost`.

-   **Sidecar Container/Process:** Local proxy/agent providing infra features.

-   **Control Plane (optional):** Distributes policy/config to sidecars (e.g., xDS in Envoy).

-   **Upstream Services:** Real targets the sidecar communicates with.


```arduino
Client ↔ App (localhost) ↔ Sidecar (localhost:15001) ↔ mTLS/Discovery/Retry ↔ Upstream Service(s)
```

## Participants

-   **App:** Issues HTTP/gRPC calls to the sidecar or accepts inbound traffic through it.

-   **Sidecar Proxy/Agent:** Enforces policy (mTLS, retries, RBAC), emits telemetry.

-   **Control Plane (optional):** Central config, certificates, service discovery data.

-   **Secrets/Identity Provider:** Issues workload identities/certs.

-   **Observability Stack:** Receives metrics/traces/logs from sidecars.


## Collaboration

1.  App sends a request to `localhost:<sidecar-port>`.

2.  Sidecar applies **policies** (routing, discovery, mTLS, timeouts, retries, circuit breaking).

3.  Sidecar forwards to upstream and streams back the response.

4.  Sidecar exports **metrics/traces**; optionally receives dynamic config from control plane.

5.  On failures, sidecar **retries** or **fails fast** per policy; app code remains unchanged.


## Consequences

**Benefits**

-   Uniform, centralized control of networking, security, and reliability.

-   Polyglot support: same features regardless of app language/stack.

-   Faster infra rollouts (update sidecar image/policy, not app code).

-   Cleaner app code (business logic only).


**Liabilities / Trade-offs**

-   Extra hop and CPU/RAM overhead per instance/pod.

-   Lifecycle coordination (startup/shutdown ordering, health).

-   Debuggability moves to the proxy/mesh domain.

-   Potential blast radius if a buggy sidecar is rolled out broadly.


## Implementation (Key Points)

-   **Traffic mode:** inbound (sidecar intercepts requests to the app), outbound (app calls sidecar), or both.

-   **Communication:** `localhost` over TCP/UDS; prefer **HTTP/2** or gRPC for efficiency.

-   **Policy sources:** static config, dynamic control plane (xDS), or environment variables.

-   **Security:** mTLS between sidecars; rotate certs; enforce SPIFFE-like identities.

-   **Reliability:** retries with jittered backoff, timeouts, outlier detection, connection pools.

-   **Observability:** Prometheus metrics, OpenTelemetry traces, structured logs.

-   **Kubernetes:** two containers in one pod; sidecar readiness/health probes; init-container for certs.

-   **Failure handling:** app should **fail closed** or degrade gracefully if sidecar is down; provide **circuit breakers**.

-   **Config hot-reload:** SIGHUP or watch files; avoid restarts for routine policy changes.


---

## Sample Code (Java 17): Minimal Sidecar Proxy + App (localhost)

Educational example showing:

-   Sidecar listening on `localhost:15001`

-   Outbound proxy to an **upstream** (set via `UPSTREAM_URL`)

-   **Retries with exponential backoff + jitter**, **timeouts**, and **Prometheus-style metrics** endpoint `/metrics`

-   App calls `http://localhost:15001/hello?name=…` and never talks to upstream directly


> Run two processes: one for `Sidecar`, one for `App`. For a quick upstream, use `python -m http.server` or any echo server.

```java
// File: SidecarAndApp.java
// Compile: javac SidecarAndApp.java
// Run sidecar:  UPSTREAM_URL=http://localhost:9001 java SidecarAndApp sidecar 15001
// Run app:      java SidecarAndApp app 8080
// Try:          curl "http://localhost:8080/hello?name=Erhard"

import com.sun.net.httpserver.*;
import java.io.*;
import java.net.*;
import java.net.http.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;

public class SidecarAndApp {

  // -------------------- SIDE CAR --------------------
  static class Sidecar {
    private final HttpClient client;
    private final URI upstreamBase;
    private final int listenPort;

    // Simple metrics
    private final AtomicLong total = new AtomicLong();
    private final AtomicLong success = new AtomicLong();
    private final AtomicLong errors = new AtomicLong();
    private final AtomicLong retries = new AtomicLong();

    Sidecar(URI upstreamBase, int listenPort) {
      this.upstreamBase = upstreamBase;
      this.listenPort = listenPort;
      this.client = HttpClient.newBuilder()
          .version(HttpClient.Version.HTTP_1_1)
          .connectTimeout(Duration.ofSeconds(1))
          .build();
    }

    void start() throws IOException {
      HttpServer s = HttpServer.create(new InetSocketAddress("127.0.0.1", listenPort), 0);
      s.createContext("/metrics", ex -> {
        String body = "# HELP sidecar_requests_total Total requests seen\n" +
            "# TYPE sidecar_requests_total counter\n" +
            "sidecar_requests_total " + total.get() + "\n" +
            "# HELP sidecar_requests_success Successful responses\n" +
            "# TYPE sidecar_requests_success counter\n" +
            "sidecar_requests_success " + success.get() + "\n" +
            "# HELP sidecar_requests_errors Error responses\n" +
            "# TYPE sidecar_requests_errors counter\n" +
            "sidecar_requests_errors " + errors.get() + "\n" +
            "# HELP sidecar_retries_total Retries performed\n" +
            "# TYPE sidecar_retries_total counter\n" +
            "sidecar_retries_total " + retries.get() + "\n";
        byte[] b = body.getBytes();
        ex.getResponseHeaders().set("content-type", "text/plain; version=0.0.4");
        ex.sendResponseHeaders(200, b.length);
        try (var os = ex.getResponseBody()) { os.write(b); }
      });

      // all other paths are proxied to upstream
      s.createContext("/", ex -> {
        total.incrementAndGet();
        try (ex) {
          proxyWithRetry(ex);
        } catch (Exception e) {
          errors.incrementAndGet();
          byte[] b = ("sidecar error: " + e.getClass().getSimpleName()).getBytes();
          ex.getResponseHeaders().set("content-type","text/plain; charset=utf-8");
          ex.sendResponseHeaders(502, b.length);
          try (var os = ex.getResponseBody()) { os.write(b); }
        }
      });

      s.setExecutor(Executors.newFixedThreadPool(Math.max(4, Runtime.getRuntime().availableProcessors())));
      System.out.println("Sidecar listening on http://127.0.0.1:" + listenPort + " → upstream " + upstreamBase);
      s.start();
    }

    private void proxyWithRetry(HttpExchange ex) throws Exception {
      int maxAttempts = 4;
      Duration initial = Duration.ofMillis(120);
      Duration maxDelay = Duration.ofSeconds(1);

      int attempt = 1;
      while (true) {
        try {
          forwardOnce(ex);
          success.incrementAndGet();
          return;
        } catch (IOException | InterruptedException e) {
          if (attempt >= maxAttempts) throw e;
          retries.incrementAndGet();
          long sleep = jitteredBackoff(initial, maxDelay, attempt);
          Thread.sleep(sleep);
          attempt++;
        }
      }
    }

    private long jitteredBackoff(Duration initial, Duration max, int attempt) {
      long base = Math.min(max.toMillis(), (long) (initial.toMillis() * Math.pow(2, attempt - 1)));
      return ThreadLocalRandom.current().nextLong(0, base + 1); // full jitter
    }

    private void forwardOnce(HttpExchange ex) throws IOException, InterruptedException {
      URI incoming = ex.getRequestURI();
      URI target = upstreamBase.resolve(incoming.getPath() + (incoming.getQuery() != null ? "?" + incoming.getQuery() : ""));
      HttpRequest.Builder rb = HttpRequest.newBuilder(target)
          .timeout(Duration.ofSeconds(2))
          .method(ex.getRequestMethod(), requestBody(ex));

      ex.getRequestHeaders().forEach((k, v) -> {
        String lk = k.toLowerCase(Locale.ROOT);
        if (!Set.of("host", "connection", "keep-alive", "proxy-authorization", "proxy-authenticate",
            "te", "trailers", "transfer-encoding", "upgrade").contains(lk)) {
          rb.header(k, String.join(",", v));
        }
      });
      rb.header("x-forwarded-for", ex.getRemoteAddress().getAddress().getHostAddress());
      rb.header("x-sidecar", "true");

      HttpResponse<InputStream> resp = client.send(rb.build(), HttpResponse.BodyHandlers.ofInputStream());

      // Relay
      for (var e : resp.headers().map().entrySet()) {
        if (!e.getKey().equalsIgnoreCase("transfer-encoding")) {
          for (var v : e.getValue()) ex.getResponseHeaders().add(e.getKey(), v);
        }
      }
      ex.sendResponseHeaders(resp.statusCode(), resp.headers().firstValueAsLong("content-length").orElse(0));
      try (var in = resp.body(); var out = ex.getResponseBody()) { in.transferTo(out); }
    }

    private static HttpRequest.BodyPublisher requestBody(HttpExchange ex) throws IOException {
      if (Set.of("GET","HEAD","DELETE","OPTIONS","TRACE").contains(ex.getRequestMethod())) {
        return HttpRequest.BodyPublishers.noBody();
      }
      byte[] body = ex.getRequestBody().readAllBytes();
      return HttpRequest.BodyPublishers.ofByteArray(body);
    }
  }

  // -------------------- APP (uses sidecar on localhost) --------------------
  static class App {
    private final int listenPort;
    private final HttpClient client = HttpClient.newHttpClient();
    private final URI sidecarBase;

    App(int listenPort, URI sidecarBase) { this.listenPort = listenPort; this.sidecarBase = sidecarBase; }

    void start() throws IOException {
      HttpServer s = HttpServer.create(new InetSocketAddress("127.0.0.1", listenPort), 0);
      s.createContext("/hello", ex -> {
        String name = Optional.ofNullable(queryParam(ex.getRequestURI().getRawQuery(), "name")).orElse("world");
        // business logic: call our *dependency* THROUGH the sidecar
        URI dep = sidecarBase.resolve("/echo?msg=Hello%20" + URLEncoder.encode(name, "UTF-8"));
        HttpRequest req = HttpRequest.newBuilder(dep).GET().timeout(Duration.ofSeconds(1)).build();
        String upstream = client.send(req, HttpResponse.BodyHandlers.ofString()).body();
        String body = "App says: " + upstream + "\n";
        ex.getResponseHeaders().set("content-type","text/plain; charset=utf-8");
        ex.sendResponseHeaders(200, body.getBytes().length);
        try (var os = ex.getResponseBody()) { os.write(body.getBytes()); }
      });
      // health
      s.createContext("/health", ex -> {
        byte[] b = "ok".getBytes();
        ex.sendResponseHeaders(200, b.length); try (var os = ex.getResponseBody()) { os.write(b); }
      });

      s.setExecutor(Executors.newFixedThreadPool(4));
      System.out.println("App listening on http://127.0.0.1:" + listenPort + " (uses sidecar at " + sidecarBase + ")");
      s.start();
    }

    private static String queryParam(String raw, String key) throws UnsupportedEncodingException {
      if (raw == null) return null;
      for (String kv : raw.split("&")) {
        int i = kv.indexOf('=');
        String k = URLDecoder.decode(i < 0 ? kv : kv.substring(0, i), "UTF-8");
        String v = i < 0 ? "" : URLDecoder.decode(kv.substring(i + 1), "UTF-8");
        if (k.equals(key)) return v;
      }
      return null;
    }
  }

  public static void main(String[] args) throws Exception {
    if (args.length == 0) {
      System.out.println("""
        usage:
          sidecar <listenPort>            (requires env UPSTREAM_URL)
          app <listenPort>                (sidecar assumed at http://127.0.0.1:15001)
        """);
      return;
    }
    switch (args[0]) {
      case "sidecar" -> {
        int port = Integer.parseInt(args[1]);
        String up = System.getenv("UPSTREAM_URL");
        if (up == null || up.isBlank()) {
          System.err.println("Set UPSTREAM_URL (e.g., http://localhost:9001)"); System.exit(2);
        }
        new Sidecar(URI.create(up), port).start();
      }
      case "app" -> {
        int port = Integer.parseInt(args[1]);
        new App(port, URI.create("http://127.0.0.1:15001")).start();
      }
    }
  }
}
```

**How to try quickly**

1.  Start a toy upstream service that echoes `msg` (for example using Python):

    -   `python -m http.server 9001` won’t do echo; instead use any small echo server, or spin up a second tiny Java/Node server that returns `you said: <msg>` at `/echo`.

    -   For a super quick demo, you can point `UPSTREAM_URL` to a public HTTP echo during local tests.

2.  Start the **sidecar** (talking to upstream):  
    `UPSTREAM_URL=http://localhost:9001 java SidecarAndApp sidecar 15001`

3.  Start the **app**:  
    `java SidecarAndApp app 8080`

4.  Call: `curl "http://127.0.0.1:8080/hello?name=Erhard"`  
    Check **metrics** at: `curl "http://127.0.0.1:15001/metrics"`


> In production you’d replace this DIY proxy with Envoy/Linkerd/Dapr, add **mTLS**, richer routing, rate limits, and OpenTelemetry.

---

## Known Uses

-   **Istio / Envoy**: Sidecar data plane with xDS control plane (mTLS, retries, RBAC, traffic shaping).

-   **Linkerd**: Lightweight Rust proxy as sidecar for transparent mTLS and golden-signal metrics.

-   **AWS App Mesh / Consul Connect**: Managed meshes orchestrating sidecar proxies.

-   **Dapr**: Sidecar building blocks (pub/sub, bindings, state, secrets) exposed via HTTP/gRPC.

-   **Datadog/Fluent Bit/Vector/OTel Collector**: Telemetry sidecars shipping logs/metrics/traces.


## Related Patterns

-   **Service Mesh:** A fleet of sidecars + control plane = mesh.

-   **Ambassador (Gateway) / API Gateway:** Edge equivalent of sidecar for ingress.

-   **Circuit Breaker, Retry with Backoff, Rate Limiter:** Policies often implemented **in** the sidecar.

-   **Service Discovery & Load Balancer:** Sidecar can resolve and balance to healthy instances.

-   **Bulkhead / Pool Isolation:** Sidecar connections & pools isolate app from dependency failures.

-   **Adapter / Anti-Corruption Layer:** Sidecar can translate protocols without touching the app.


---

### Practical Tips

-   Make the sidecar **optional** in dev (bypass mode) to ease local debugging.

-   Treat sidecar config as **code**; version, validate, and rollout safely (canary).

-   Set **sane defaults**: global timeouts, 1–2 retries with jitter, p95/p99 histograms.

-   Ensure **graceful shutdown** ordering (drain proxy first, then stop app).

-   Rotate certs and validate identities automatically; avoid manual secrets in app code.

-   Ship **golden signals** (RPS, error rate, latency, saturation) per route to your metrics stack.
