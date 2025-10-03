# Load Balancer — Cloud Distributed Systems Pattern

## Pattern Name and Classification

-   **Name:** Load Balancer

-   **Classification:** Structural pattern for distributed systems; deployment/runtime infrastructure pattern. Often grouped under **Resilience & Scalability** patterns.


## Intent

Distribute incoming requests across a fleet of service instances to:

-   increase throughput and availability,

-   isolate and contain failures,

-   enable elastic scaling and maintenance without downtime.


## Also Known As

-   Reverse Proxy (Layer-7 flavor)

-   L4/L7 Load Balancing

-   Traffic Director / Front Door

-   Service Load Balancer


## Motivation (Forces)

-   **Throughput vs. Latency:** Evenly spread load to avoid hot spots while keeping tail latency low.

-   **Availability:** Route around failures and failing zones; support connection draining.

-   **Elasticity:** Seamlessly add/remove instances as capacity changes.

-   **Session Affinity:** Some workloads need stickiness; others must be stateless to scale freely.

-   **Heterogeneity:** Instances may differ (warm/cold, hardware, zones) → weighting helps.

-   **Network Layers:** L4 (faster, simpler) vs. L7 (smart routing, header/cookie logic, auth).

-   **Cost & Complexity:** Managed LB vs. self-hosted (HAProxy/Envoy) vs. client-side libraries.

-   **Observability & Control:** Need metrics, logs, outlier detection, circuit breaking.


## Applicability

Use a Load Balancer when you need:

-   horizontal scaling of stateless services,

-   zero/low-downtime deployments (blue-green, canary),

-   multi-AZ/region failover,

-   API gateway/reverse proxy features (TLS termination, path-based routing, auth),

-   service mesh ingress/egress.


## Structure

-   **Client:** Sends requests to a single entrypoint (VIP/DNS) or performs client-side balancing.

-   **Load Balancer:** Accepts connections, selects a healthy target instance using a policy (RR, least-connections, latency-aware, weighted, consistent hashing).

-   **Service Instances (Pool):** N interchangeable backends, health-checked & discoverable.

-   **Service Discovery (optional):** Registry (e.g., Consul, Eureka, DNS SRV) feeding the LB.

-   **Health Checker / Outlier Detector:** Probes and ejects unhealthy targets.


## Participants

-   **Dispatcher/Selector:** Implements the balancing algorithm.

-   **Health Monitor:** Periodically probes and updates instance state.

-   **Registry Adapter:** Pulls/pushes membership from discovery (or static list).

-   **Connection Manager:** Handles keep-alives, connection reuse, drain on shutdown.

-   **Metrics/Logger:** Emits success/latency/error codes; supports adaptive algorithms.


## Collaboration

1.  Health Monitor marks instances **healthy/unhealthy**.

2.  Client connects to LB (or uses client-side library).

3.  Selector chooses a **healthy** instance based on policy & weights.

4.  LB forwards request, streams back response; metrics recorded.

5.  On errors/timeouts, **retry** (respecting idempotency), apply **circuit breaker**, or **fail fast**.


## Consequences

**\+ Pros**

-   Improves availability, utilization, and tail latency.

-   Hides topology changes; supports gradual rollouts and draining.

-   Enables policy-based routing (L7).


**– Cons / Trade-offs**

-   Extra hop; can become a bottleneck or single point of failure (needs HA).

-   Sticky sessions limit elasticity; require externalizing session state.

-   Complex failure modes (retry storms, thundering herd) without backoff/budgeting.

-   Operational complexity (TLS, cert rotation, observability).


## Implementation (Key Points)

-   **Algorithms:** round-robin, weighted RR, least-connections, power-of-two choices, latency-aware EWMA, consistent-hashing (for affinity/sharding).

-   **Health:** active (HTTP/TCP probes) + passive (eject on 5xx/RTT spikes).

-   **Draining:** stop new picks, let in-flight finish; set short keep-alive timeouts.

-   **Affinity:** cookie-based, source-IP, or consistent hashing; prefer stateless services.

-   **Retries:** bounded (e.g., 1–2), jittered exponential backoff; only on idempotent ops.

-   **TLS:** terminate at LB; optionally re-encrypt to backends; automate certs/OCSP.

-   **Zonal Awareness:** prefer same-zone, fail across zones on saturation/failure.

-   **Observability:** p50/p95/p99, errors by code, per-target load, outlier rates.

-   **Scaling:** LB should be HA (active-active) with health-checked peers; use anycast/DNS.

-   **Config:** keep pool and weights hot-reloadable; integrate with discovery.


---

## Sample Code (Java 17): Minimal L7 Reverse Proxy with Round-Robin + Health Checks

> This is a compact educational example (not production-grade). It shows:
>
> -   round-robin selection with per-target health,
>
> -   active HTTP health checks,
>
> -   simple reverse proxying with `HttpServer` + `HttpClient`,
>
> -   graceful draining on shutdown.
>

```java
// File: SimpleLoadBalancerProxy.java
// javac SimpleLoadBalancerProxy.java && java SimpleLoadBalancerProxy 8080 http://localhost:9001 http://localhost:9002
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.*;
import java.net.http.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;

public class SimpleLoadBalancerProxy {

    static class Backend {
        final URI baseUri;
        volatile boolean healthy = true;
        volatile int weight = 1; // for weighted RR (not fully used in this small demo)

        Backend(URI baseUri) { this.baseUri = baseUri; }
        @Override public String toString() { return baseUri + " healthy=" + healthy; }
    }

    interface Selector {
        Optional<Backend> pick();
        void markFailure(Backend b);
        void markSuccess(Backend b, long rttMillis);
        List<Backend> snapshot();
        void setDraining(boolean draining);
    }

    static class RoundRobinSelector implements Selector {
        private final List<Backend> all;
        private final AtomicInteger idx = new AtomicInteger();
        private volatile boolean draining = false;

        RoundRobinSelector(List<Backend> backends) { this.all = backends; }

        public Optional<Backend> pick() {
            if (draining) return Optional.empty();
            List<Backend> healthy = all.stream().filter(b -> b.healthy).toList();
            if (healthy.isEmpty()) return Optional.empty();
            int i = Math.floorMod(idx.getAndIncrement(), healthy.size());
            return Optional.of(healthy.get(i));
        }
        public void markFailure(Backend b) { /* could track EWMA or penalize */ }
        public void markSuccess(Backend b, long rttMillis) { /* update EWMA */ }
        public List<Backend> snapshot() { return List.copyOf(all); }
        public void setDraining(boolean draining) { this.draining = draining; }
    }

    static class HealthChecker {
        private final HttpClient client;
        private final List<Backend> backends;
        private final ScheduledExecutorService ses = Executors.newSingleThreadScheduledExecutor();
        private final Duration timeout;
        private final String path;
        private final int healthyThreshold;
        private final int unhealthyThreshold;
        private final Map<Backend, Integer> successStreak = new ConcurrentHashMap<>();
        private final Map<Backend, Integer> failStreak = new ConcurrentHashMap<>();

        HealthChecker(List<Backend> backends, Duration timeout, String path,
                      int healthyThreshold, int unhealthyThreshold) {
            this.backends = backends;
            this.timeout = timeout;
            this.path = path;
            this.healthyThreshold = healthyThreshold;
            this.unhealthyThreshold = unhealthyThreshold;
            this.client = HttpClient.newBuilder().connectTimeout(timeout).build();
        }

        void start() {
            ses.scheduleAtFixedRate(this::probeAll, 0, 2, TimeUnit.SECONDS);
        }

        void stop() { ses.shutdownNow(); }

        private void probeAll() {
            for (Backend b : backends) {
                try {
                    URI u = b.baseUri.resolve(path);
                    HttpRequest req = HttpRequest.newBuilder(u)
                            .timeout(timeout)
                            .GET()
                            .build();
                    client.sendAsync(req, HttpResponse.BodyHandlers.discarding())
                          .orTimeout(timeout.toMillis(), TimeUnit.MILLISECONDS)
                          .whenComplete((resp, err) -> {
                              boolean ok = err == null && resp.statusCode() >= 200 && resp.statusCode() < 400;
                              if (ok) {
                                  failStreak.put(b, 0);
                                  int s = successStreak.merge(b, 1, Integer::sum);
                                  if (!b.healthy && s >= healthyThreshold) b.healthy = true;
                              } else {
                                  successStreak.put(b, 0);
                                  int f = failStreak.merge(b, 1, Integer::sum);
                                  if (b.healthy && f >= unhealthyThreshold) b.healthy = false;
                              }
                          });
                } catch (Exception ignored) { /* best-effort */ }
            }
        }
    }

    static class ProxyHandler implements HttpHandler {
        private final Selector selector;
        private final HttpClient client;

        ProxyHandler(Selector selector) {
            this.selector = selector;
            this.client = HttpClient.newBuilder()
                    .connectTimeout(Duration.ofSeconds(2))
                    .version(HttpClient.Version.HTTP_1_1)
                    .followRedirects(HttpClient.Redirect.NEVER)
                    .build();
        }

        @Override public void handle(HttpExchange exchange) throws IOException {
            long start = System.nanoTime();
            Optional<Backend> target = selector.pick();
            if (target.isEmpty()) {
                send(exchange, 503, "no healthy backends or draining");
                return;
            }
            Backend b = target.get();

            try (exchange) {
                URI incoming = exchange.getRequestURI();
                URI targetUri = b.baseUri.resolve(incoming.getPath() + (incoming.getQuery() != null ? "?" + incoming.getQuery() : ""));
                HttpRequest.Builder rb = HttpRequest.newBuilder(targetUri)
                        .timeout(Duration.ofSeconds(5))
                        .method(exchange.getRequestMethod(), requestBody(exchange));

                // pass-through selected headers (skip hop-by-hop)
                exchange.getRequestHeaders().forEach((k, v) -> {
                    String lk = k.toLowerCase(Locale.ROOT);
                    if (!List.of("connection","keep-alive","proxy-authenticate","proxy-authorization",
                            "te","trailers","transfer-encoding","upgrade","host").contains(lk)) {
                        rb.header(k, String.join(",", v));
                    }
                });
                rb.header("x-forwarded-for", exchange.getRemoteAddress().getAddress().getHostAddress());
                rb.header("x-forwarded-proto", "http");

                HttpResponse<InputStream> resp = client.send(rb.build(), HttpResponse.BodyHandlers.ofInputStream());
                selector.markSuccess(b, (System.nanoTime() - start) / 1_000_000);

                // relay response
                HeadersAdapter.copyResponseHeaders(resp, exchange);
                exchange.sendResponseHeaders(resp.statusCode(), resp.headers().firstValueAsLong("content-length").orElse(0));
                try (InputStream is = resp.body(); OutputStream os = exchange.getResponseBody()) {
                    is.transferTo(os);
                }
            } catch (Exception e) {
                selector.markFailure(b);
                send(exchange, 502, "bad gateway: " + e.getClass().getSimpleName());
            }
        }

        private static HttpRequest.BodyPublisher requestBody(HttpExchange ex) throws IOException {
            if (List.of("GET","DELETE","HEAD","OPTIONS","TRACE").contains(ex.getRequestMethod())) {
                return HttpRequest.BodyPublishers.noBody();
            }
            byte[] body = ex.getRequestBody().readAllBytes();
            return HttpRequest.BodyPublishers.ofByteArray(body);
        }

        private static void send(HttpExchange ex, int code, String msg) throws IOException {
            byte[] bytes = msg.getBytes();
            ex.getResponseHeaders().add("content-type", "text/plain; charset=utf-8");
            ex.sendResponseHeaders(code, bytes.length);
            try (OutputStream os = ex.getResponseBody()) { os.write(bytes); }
        }

        static class HeadersAdapter {
            static void copyResponseHeaders(HttpResponse<?> resp, HttpExchange exchange) {
                var excluded = Set.of("connection","keep-alive","proxy-authenticate","proxy-authorization",
                        "te","trailers","transfer-encoding","upgrade");
                resp.headers().map().forEach((k, v) -> {
                    if (!excluded.contains(k.toLowerCase(Locale.ROOT))) {
                        v.forEach(val -> exchange.getResponseHeaders().add(k, val));
                    }
                });
            }
        }
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.out.println("usage: java SimpleLoadBalancerProxy <listenPort> <backendUrl1> [backendUrl2 ...]");
            System.exit(1);
        }
        int port = Integer.parseInt(args[0]);
        List<Backend> pool = new ArrayList<>();
        for (int i = 1; i < args.length; i++) pool.add(new Backend(URI.create(args[i])));

        var selector = new RoundRobinSelector(pool);
        var health = new HealthChecker(pool, Duration.ofSeconds(1), "/health", 2, 2);
        health.start();

        HttpServer server = HttpServer.create(new InetSocketAddress(port), 0);
        server.createContext("/", new ProxyHandler(selector));
        server.setExecutor(Executors.newFixedThreadPool(Math.max(4, Runtime.getRuntime().availableProcessors())));
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            selector.setDraining(true);
            health.stop();
            server.stop(1);
        }));

        System.out.println("LB listening on http://localhost:" + port + " → " + pool);
        server.start();
    }
}
```

**How to try it quickly**

1.  Start two tiny backends (e.g., `python -m http.server 9001` and `python -m http.server 9002`) and serve a `/health` file returning 200.

2.  Run:  
    `javac SimpleLoadBalancerProxy.java && java SimpleLoadBalancerProxy 8080 http://localhost:9001 http://localhost:9002`

3.  Hit `http://localhost:8080/` repeatedly and observe alternating backends. Kill one backend to see health ejection.

4.  `Ctrl+C` triggers draining.


---

## Known Uses

-   **Cloud LB:** AWS ALB/NLB & Elastic Load Balancing; GCP External/Internal HTTP(S)/TCP/UDP LBs; Azure Front Door / Application Gateway.

-   **Proxies:** NGINX, HAProxy, Envoy, Traefik (edge and internal).

-   **Service Mesh / In-Cluster:** Kubernetes `Service` (ClusterIP/NodePort/LoadBalancer) with kube-proxy/ipvs; Istio/Linkerd data plane (Envoy) with locality-aware L7 balancing.

-   **Libraries (Client-Side):** Spring Cloud LoadBalancer, gRPC client-side LB (pick-first, round\_robin, xDS), Finagle, Ribbon (legacy).


## Related Patterns

-   **Service Discovery:** Keep the target list fresh (DNS SRV, Eureka, Consul).

-   **Circuit Breaker & Outlier Detection:** Eject bad instances quickly.

-   **Retry with Backoff & Jitter:** Handle transient failures safely.

-   **Bulkhead & Pool Isolation:** Prevent noisy neighbor effects.

-   **Rate Limiter / Token Bucket:** Protect backends from floods.

-   **API Gateway / Reverse Proxy:** Edge concerns (auth, WAF, routing).

-   **Blue-Green / Canary Deployments:** Safely shift subsets of traffic.

-   **Cache / CDN:** Offload repeated reads before they hit the LB.


---

### Notes for Production

-   Prefer a proven proxy (Envoy/HAProxy/NGINX) or a **managed** LB for real systems.

-   Run LBs in **pairs or fleets** (active-active), with health-checked VIP/DNS.

-   Instrument thoroughly; feed SLOs from LB metrics (availability & latency budgets).

-   Validate retry budgets and set **per-try** and **overall** timeouts to avoid retry storms.

-   For **stateful** affinity, choose consistent hashing or externalize session state (e.g., Redis).
