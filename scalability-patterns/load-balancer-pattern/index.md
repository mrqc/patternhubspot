# Load Balancer — Scalability Pattern

## Pattern Name and Classification

**Name:** Load Balancer  
**Classification:** Scalability / Traffic Management / Availability (Ingress & Service-to-Service)

---

## Intent

Distribute incoming requests **across multiple instances** to increase throughput, reduce tail latency, and improve availability, while optionally providing **health checks, retries, timeouts, outlier detection, TLS termination, and routing**.

---

## Also Known As

-   Reverse Proxy (L7)
    
-   Layer-4/Layer-7 Balancer
    
-   Application Gateway / API Gateway (when enriched with auth/rate limits)
    
-   Client-side Load Balancing (when the caller picks the target)
    
-   Service Mesh Data Plane (sidecar doing LB per hop)
    

---

## Motivation (Forces)

-   **Hot spots & single-node limits:** One instance cannot keep up with throughput or spikes.
    
-   **Failure isolation:** Some instances are unhealthy; traffic must avoid them.
    
-   **Latency variance:** Even healthy nodes exhibit variable p99 latency; smart picking reduces tails.
    
-   **Flexibility:** Different endpoints/tenants may require different routing and stickiness.
    
-   **Operational extras:** TLS offload, header normalization, observability, and gradual rollouts (canary).
    

---

## Applicability

Use a Load Balancer when:

-   You run **multiple interchangeable replicas** of a service.
    
-   You need **elastic capacity** and rolling deployments without downtime.
    
-   You want policy-driven routing (weighted, canary, A/B, geo).
    
-   You need **simple failover** across zones/regions.
    

Avoid or adapt when:

-   Work is **stateful and sticky** to one node without externalizing state (LB can’t help).
    
-   Strong **ordering** or **affinity** is required (use consistent hashing or partition-aware routers).
    
-   Intra-node communication is ultra-low-latency shared-memory (LB hop may be overkill).
    

---

## Structure

-   **Load Balancer (LB):** Decides target instance for each request.
    
-   **Target Pool:** Set of healthy instances (dynamic: service discovery).
    
-   **Health Prober:** Periodically checks targets (active) and/or observes failures (passive).
    
-   **Routing Policy:** Round-robin, least-connections, least outstanding requests, EWMA latency, **P2C** (power-of-two-choices), consistent hashing, weighted.
    
-   **Resiliency:** Timeouts, retries with backoff/jitter, outlier ejection/circuit breaking.
    
-   **Session Affinity (optional):** Cookie/IP hash for stickiness.
    
-   **Termination/Proxying (optional):** TLS offload, header rewrite, observability.
    

---

## Participants

-   **Client / Upstream**: Emits requests (browser, service).
    
-   **Load Balancer**: Edge (L7), L4 (NLB), sidecar (mesh), or client library (caller-side).
    
-   **Service Instances**: Interchangeable replicas behind LB.
    
-   **Service Discovery**: Registry/DNS providing live instances.
    
-   **Observability**: Metrics/tracing/logs around picks, health, and errors.
    

---

## Collaboration

1.  **Discovery** provides a list of candidate instances (with weights/metadata).
    
2.  **LB** applies **health state** and **routing policy** to select a target.
    
3.  **Request** is forwarded; **timeouts** and **retries** may occur on failure (policy-bound).
    
4.  **Passive signals** (errors/latency) update **outlier detection**; **active probes** update health.
    
5.  **Autoscaling / Deployments** change the pool; LB adapts without client impact.
    

---

## Consequences

**Benefits**

-   Near-linear **scale-out** for stateless tiers.
    
-   **Availability**: unhealthy instances are bypassed automatically.
    
-   **Latency**: smart algorithms (least outstanding, P2C, EWMA) reduce tail latency.
    
-   Central place for **TLS**, **observability**, and **gradual rollouts**.
    

**Liabilities**

-   Becomes a **critical component**; misconfiguration can cause global outages.
    
-   **Stateful** services need affinity/partition-aware routing to avoid contention.
    
-   **Retries** can amplify traffic (retry storms) if not budgeted.
    
-   Additional **hop** may add small latency; ensure it’s bounded.
    

---

## Implementation

### Key Decisions

-   **Where to balance:**
    
    -   **Edge (L7/L4)**: NGINX/Envoy/ALB—unified ingress, TLS, WAF.
        
    -   **Client-side**: Library chooses target (no extra hop, per-request intelligence).
        
    -   **Sidecar (mesh)**: Envoy per pod—fine-grained control and mTLS.
        
-   **Policy:**
    
    -   **Round-Robin** (simple), **Least-Connections**, **Least Outstanding Requests**, **P2C** (fast, robust), **EWMA** (latency-aware), **Consistent Hash** (affinity/partitioning), **Weighted** (canaries).
        
-   **Health:** Active HTTP/TCP probes + passive outlier detection (eject on 5xx, timeouts).
    
-   **Resilience:** Per-hop **timeouts**, **retries with exponential backoff + jitter**, **retry budgets**, and **circuit breaking**.
    
-   **Stickiness:** Cookie/IP hash when session affinity is required—prefer externalize state instead.
    
-   **Observability:** Request IDs, `X-Forwarded-For`, metrics (success/latency per target), distributed tracing.
    

### Anti-Patterns

-   **Retrying everything** (including non-idempotent operations) or without budgets.
    
-   Ignoring **slow start/warmup**—new instances receive full traffic immediately and thrash.
    
-   Using **round-robin only** under highly variable latency—leads to high p99.
    
-   Not fencing **outliers**—bad instances keep degrading fleet performance.
    
-   Overusing **sticky sessions**—prevents even distribution and graceful deployments.
    

---

## Sample Code (Java)

**Goal:** Client-side HTTP load balancer with **Power-of-Two-Choices** (P2C) + **EWMA latency**, **active health checks**, **outlier ejection**, **timeouts**, and **bounded retries** using OkHttp.

> Dependencies: OkHttp (HTTP client)  
> This is a *client-side* LB; put it inside a service that calls another service replicated behind, e.g., `/orders`.

```java
// build.gradle (snip)
// implementation 'com.squareup.okhttp3:okhttp:4.12.0'

package com.example.loadbalancer;

import okhttp3.*;

import java.io.IOException;
import java.net.URI;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.atomic.AtomicLong;
import java.util.stream.Collectors;

/** Models one upstream instance with EWMA latency and health/outlier state. */
final class Upstream {
  final HttpUrl baseUrl;
  final AtomicLong ewmaMicros = new AtomicLong(200_000); // start at 200ms
  volatile boolean healthy = true;
  volatile long ejectedUntilMillis = 0L;
  volatile int inFlight = 0;

  Upstream(String url) { this.baseUrl = HttpUrl.get(url); }

  boolean availableNow() {
    long now = System.currentTimeMillis();
    return healthy && now >= ejectedUntilMillis;
  }

  void observeLatency(long micros, double alpha) {
    long old = ewmaMicros.get();
    long updated = (long) (alpha * micros + (1.0 - alpha) * old);
    ewmaMicros.set(Math.max(1000, updated));
  }

  void outlierEject(long millis) { ejectedUntilMillis = System.currentTimeMillis() + millis; }
}

/** Power-of-two-choices with EWMA + in-flight tie-breaker. */
final class Picker {
  private final List<Upstream> pool;

  Picker(List<Upstream> pool) { this.pool = pool; }

  Upstream pick() {
    List<Upstream> candidates = pool.stream().filter(Upstream::availableNow).toList();
    if (candidates.isEmpty()) throw new IllegalStateException("no healthy upstreams");
    if (candidates.size() == 1) return candidates.get(0);
    Upstream a = candidates.get(ThreadLocalRandom.current().nextInt(candidates.size()));
    Upstream b = candidates.get(ThreadLocalRandom.current().nextInt(candidates.size()));
    if (a == b) return a;

    long sa = a.ewmaMicros.get();
    long sb = b.ewmaMicros.get();
    if (sa == sb) return (a.inFlight <= b.inFlight) ? a : b;
    return sa < sb ? a : b;
  }
}

/** Health checker (active) + client-side LB with retries, backoff, and timeouts. */
public final class HttpLoadBalancer {

  private final List<Upstream> upstreams;
  private final OkHttpClient client;

  // Tuning knobs
  private final int maxRetries = 2; // total attempts = 1 + maxRetries
  private final Duration perAttemptTimeout = Duration.ofMillis(400);
  private final Duration healthInterval = Duration.ofSeconds(5);
  private final double ewmaAlpha = 0.2; // latency smoothing
  private final long outlierEjectMs = 10_000;

  public HttpLoadBalancer(List<String> baseUrls) {
    this.upstreams = baseUrls.stream().map(Upstream::new).collect(Collectors.toList());
    this.client = new OkHttpClient.Builder()
        .connectTimeout(Duration.ofMillis(150))
        .readTimeout(perAttemptTimeout)
        .callTimeout(perAttemptTimeout.plusMillis(50))
        .build();

    // Start active health checks
    Thread hc = new Thread(this::healthLoop, "lb-health");
    hc.setDaemon(true); hc.start();
  }

  /** Perform a GET to path against the best upstream; retries on retryable errors. */
  public Response get(String path, Map<String,String> headers) throws IOException {
    IOException last = null;
    for (int attempt = 0; attempt <= maxRetries; attempt++) {
      Upstream u = new Picker(upstreams).pick();
      u.inFlight++;
      long start = System.nanoTime();
      try {
        Request.Builder rb = new Request.Builder()
            .url(u.baseUrl.newBuilder().addPathSegments(strip(path)).build())
            .header("X-Forwarded-Proto", "http")
            .header("X-Retry-Attempt", String.valueOf(attempt));
        headers.forEach(rb::header);

        Response resp = client.newCall(rb.build()).execute();
        long latMicros = (System.nanoTime() - start) / 1_000;
        u.observeLatency(latMicros, ewmaAlpha);

        if (isRetryableStatus(resp.code()) && attempt < maxRetries) {
          // passive outlier: count consecutive 5xx/timeout to eject (simplified)
          u.outlierEject(outlierEjectMs / 2);
          resp.close();
          sleepBackoff(attempt);
          continue;
        }
        return resp; // caller must close Response
      } catch (IOException ioe) {
        long latMicros = (System.nanoTime() - start) / 1_000;
        u.observeLatency(latMicros, ewmaAlpha);
        last = ioe;
        // passive outlier eject on network errors
        u.outlierEject(outlierEjectMs);
        if (attempt < maxRetries) { sleepBackoff(attempt); continue; }
        throw ioe;
      } finally {
        u.inFlight--;
      }
    }
    throw last != null ? last : new IOException("request failed without cause");
  }

  private void healthLoop() {
    OkHttpClient hc = client.newBuilder()
        .readTimeout(Duration.ofMillis(200))
        .callTimeout(Duration.ofMillis(300)).build();
    while (true) {
      for (Upstream u : upstreams) {
        try {
          Request req = new Request.Builder()
              .url(u.baseUrl.newBuilder().addPathSegment("health").build())
              .header("X-Probe", "true").build();
          try (Response r = hc.newCall(req).execute()) {
            u.healthy = r.isSuccessful();
          }
        } catch (Exception e) {
          u.healthy = false;
        }
      }
      sleep(healthInterval.toMillis());
    }
  }

  private static boolean isRetryableStatus(int code) {
    return code == 429 || code == 502 || code == 503 || code == 504;
  }

  private static String strip(String p) { return p.startsWith("/") ? p.substring(1) : p; }

  private static void sleepBackoff(int attempt) {
    long cap = Math.min(1000, (long) (100 * Math.pow(2, attempt)));
    long jitter = ThreadLocalRandom.current().nextLong(0, cap + 1);
    sleep(jitter);
  }
  private static void sleep(long ms) { try { Thread.sleep(ms); } catch (InterruptedException ie) { Thread.currentThread().interrupt(); } }

  // Example usage
  public static void main(String[] args) throws Exception {
    HttpLoadBalancer lb = new HttpLoadBalancer(List.of(
        "http://svc-a-1:8080/", "http://svc-a-2:8080/", "http://svc-a-3:8080/"));

    try (Response r = lb.get("/api/v1/orders/123", Map.of())) {
      System.out.println(r.code() + " " + Objects.requireNonNull(r.body()).string());
    }
  }
}
```

**What the sample demonstrates**

-   **Client-side LB** (no extra hop) using **P2C** + **EWMA** for latency-aware picking.
    
-   **Active health checks** on `/health` and **passive outlier ejection** on failures.
    
-   **Retries with jittered exponential backoff** and **per-attempt timeouts**.
    
-   Pluggable—wrap any HTTP call; the same principles apply for gRPC (pick channel/subchannel).
    

---

## Known Uses

-   **Edge LBs**: NGINX/Envoy/HAProxy, cloud ALB/ELB/NLB, Cloudflare, Fastly.
    
-   **Service meshes**: Envoy sidecars (Istio/Linkerd) provide per-hop LB with mTLS and outlier detection.
    
-   **Client libraries**: gRPC pick-first/round-robin, Spring Cloud LoadBalancer, Ribbon/Feign (legacy), Finagle.
    
-   **Database drivers**: read/write splitting and replica picking for clusters.
    

---

## Related Patterns

-   **Horizontal Scaling / Auto Scaling Group**: LB makes more instances useful; ASG adjusts fleet size.
    
-   **Health Check**: Inputs for removing bad targets and re-adding healthy ones.
    
-   **Circuit Breaker & Timeouts**: Prevent retry storms and bound latency.
    
-   **Throttling / Rate Limiting**: Back-pressure at the edge to protect the fleet.
    
-   **Canary / Weighted Routing**: Gradual rollouts by weight shifting.
    
-   **Consistent Hashing / Sharding**: Affinity/partition-aware routing when state is sticky.
    

---

## Implementation Checklist

-   Choose **LB location** (edge, sidecar, client) and **policy** (RR, least, P2C, EWMA, hashing).
    
-   Configure **health checks** (active + passive) and **outlier ejection** thresholds.
    
-   Define **timeouts, retry policy, and budgets**; make non-idempotent ops safe or **don’t retry**.
    
-   Decide on **session stickiness** vs **statelessness**; prefer externalizing state.
    
-   Enable **observability**: per-target success/latency, error classes, request IDs, traces.
    
-   Plan **slow start/warm-up** and **connection pooling** for new instances.
    
-   Validate under load: deployment ramp, failover drills, partial brownouts, and DNS/discovery churn.
    
-   Document **routing invariants** and **consistency expectations** (e.g., “hash by tenant”).

