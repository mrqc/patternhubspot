# Multi-Region Deployment — Scalability Pattern

## Pattern Name and Classification

**Name:** Multi-Region Deployment  
**Classification:** Scalability / Availability / Geo-Distribution (Global Footprint & Disaster Tolerance)

---

## Intent

Deploy and operate your application **in two or more geographic regions** to reduce user latency, increase availability, and tolerate regional failures. Traffic is **routed to the nearest healthy region**; data is **replicated or partitioned** per a defined consistency and recovery policy.

---

## Also Known As

-   Geo-Redundant Architecture
    
-   Active–Active / Active–Passive (per traffic & write topology)
    
-   Multi-AZ/Region DR (Disaster Recovery)
    
-   GSLB (Global Server Load Balancing)
    

---

## Motivation (Forces)

-   **Latency:** Round-trip time dominates user experience; serving from the nearest region cuts p95/p99.
    
-   **Availability & DR:** A region can fail (power, fiber cuts, control plane incidents). We need **RTO/RPO** that meet business goals.
    
-   **Regulatory/Data Residency:** Some data must remain in-region (e.g., EU).
    
-   **Traffic surges:** Regional events (marketing, holidays) need elastic, local capacity.
    
-   **Trade-offs:** Strong consistency across oceans is slow and brittle; relaxed or scoped consistency is often required.
    

---

## Applicability

Use Multi-Region Deployment when:

-   Your users are **globally distributed** or have strict **uptime** requirements.
    
-   You can **externalize or partition** state to avoid global locks.
    
-   The business accepts a stated **consistency model** (RPO/RTO) and **staleness envelope** where needed.
    

Avoid or adapt when:

-   You require **linearizable, cross-region** writes on the hot path (consider single write-leader per partition, or specialized databases with global consensus and accept the latency).
    
-   Data **cannot leave a jurisdiction** yet you need cross-region features without per-region isolation—design for **data residency boundaries** first.
    

---

## Structure

-   **Global Traffic Layer:** DNS/GSLB/Anycast or client-side routing selects a region by **latency/health/geo** (and possibly **weighted** for canaries).
    
-   **Regional Stacks:** Full app + data dependencies in each region (compute, cache, DB, object store).
    
-   **Data Strategy:**
    
    -   **Read-local, write-leader:** Per-partition leader in one region; replicas elsewhere.
        
    -   **Active–Active writes:** Conflict-free types (CRDTs) or deterministic conflict resolution.
        
    -   **Asynchronous replication:** Tunable RPO for DR and read fan-out.
        
-   **Control Plane:** Automation for deployments, config, secrets, and **failover runbooks**.
    
-   **Observability:** Global view of SLOs, replication lag, health, and error budgets.
    

---

## Participants

-   **GSLB / DNS / Edge:** Routes users to the nearest/healthy region.
    
-   **Regional Ingress / LB:** Distributes load across local instances.
    
-   **App Instances:** Stateless services per region.
    
-   **Data Stores:** Regional primaries/replicas, or global databases.
    
-   **Replication/Change Streams:** Move data/events between regions.
    
-   **Orchestrator/Runbooks:** Promote/demote leaders, flip traffic, test DR.
    

---

## Collaboration

1.  Client resolves the **global endpoint** → GSLB selects **Region A** (nearest & healthy).
    
2.  Request is served by Region A’s **load balancer** → **stateless** compute uses **regional** caches and **data replicas**.
    
3.  Writes follow the **data strategy** (e.g., routed to partition leader in Region A; asynchronously replicated to Region B).
    
4.  If Region A degrades, **GSLB** shifts traffic to Region B (active–active) or promotes Region B (active–passive).
    
5.  Replication catches up; **RPO/RTO** targets are met; traffic returns to steady-state when healthy.
    

---

## Consequences

**Benefits**

-   **Lower latency** via geo-proximity.
    
-   **High availability** and **disaster tolerance** with regional isolation.
    
-   **Operational flexibility**: maintenance per region, canaries per geography.
    

**Liabilities**

-   **Consistency complexity:** cross-region writes introduce lag and/or conflicts.
    
-   **Cost:** duplicate infrastructure and data egress.
    
-   **Operational complexity:** coordinated deploys, schema changes, failover drills.
    
-   **Stateful services** require partitioning and careful ownership/fencing.
    

---

## Implementation

### Key Decisions

-   **Traffic policy:**
    
    -   **Geo/latency-based** routing with health checks and **failover**.
        
    -   **Weighted** routing for canary/gradual rollouts across regions.
        
-   **Topology:**
    
    -   **Active–Active**: all regions serve reads; writes are partitioned or conflict-free.
        
    -   **Active–Passive**: secondary is warm, receives replication, promotes on failure.
        
-   **Data model:**
    
    -   **Per-tenant/partition leaders** (hash by tenantId) with **read-local** replicas.
        
    -   **Global DB** (e.g., Spanner/CosmosDB) when you accept global consensus latency.
        
    -   **Event-driven** replication (outbox/CDC → stream) for derived read models.
        
-   **Consistency envelopes:** Define **RPO** (data loss tolerance) and **RTO** (time to recover) per domain.
    
-   **State movement & fencing:** On promotion, **fence off** old leaders; use epochs/terms to prevent split brain.
    
-   **Data residency:** Regionally scoped datasets and **routing constraints** for resident users.
    
-   **Operational drills:** Regular **game days** for regional blackholes, partial partitions, and data-plane brownouts.
    

### Anti-Patterns

-   Global **sticky sessions** or stateful in-memory caches shared across regions.
    
-   Assuming **replication = consistency**; not planning for **read-your-writes** semantics.
    
-   DNS-only failover with **long TTLs** and no health checks.
    
-   “Flip the switch” promotions without **fencing** the old primary.
    
-   Uncoordinated schema changes that replicate poorly across versions.
    

---

## Sample Code (Java)

### Region-Aware HTTP Client with Failover, Hedged Reads, and Data-Residency Hints

*Client-side routing across regional endpoints, with:*

-   **Preferred region** (by residency or proximity) and **fallback list**
    
-   **Health + latency awareness** (simple EWMA)
    
-   **Hedged reads** (duplicate a slow read to a backup region to cut tail)
    
-   **Safe retries** only for **idempotent** methods
    
-   **Region/context propagation** headers for observability and server-side policy
    

```java
// build.gradle (snip)
// implementation 'com.squareup.okhttp3:okhttp:4.12.0'

package com.example.multiregion;

import okhttp3.*;

import java.io.IOException;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;
import java.util.stream.Collectors;

public class RegionAwareHttpClient {

  public static final class RegionEndpoint {
    final String region;        // e.g., "eu-central-1", "us-east-1"
    final HttpUrl baseUrl;      // e.g., https://eu.example.com
    final AtomicLong ewmaMicros = new AtomicLong(200_000); // start at 200ms
    volatile boolean healthy = true;

    public RegionEndpoint(String region, String baseUrl) {
      this.region = region;
      this.baseUrl = HttpUrl.get(baseUrl);
    }
  }

  private final List<RegionEndpoint> endpoints;       // ordered by preference
  private final OkHttpClient client;
  private final Duration perAttemptTimeout = Duration.ofMillis(600);
  private final Duration hedgeDelay = Duration.ofMillis(120); // start backup read if primary is slow
  private final int maxIdempotentRetries = 1;

  public RegionAwareHttpClient(List<RegionEndpoint> endpoints) {
    if (endpoints.isEmpty()) throw new IllegalArgumentException("endpoints required");
    this.endpoints = endpoints;
    this.client = new OkHttpClient.Builder()
        .connectTimeout(Duration.ofMillis(200))
        .readTimeout(perAttemptTimeout)
        .callTimeout(perAttemptTimeout.plusMillis(100))
        .build();
    // background health checks
    Thread t = new Thread(this::probeLoop, "region-health");
    t.setDaemon(true); t.start();
  }

  /** GET with hedging across regions to reduce tail latency. */
  public Response get(String path, Map<String,String> headers) throws IOException {
    // fire primary in preferred region; if slow, hedge to next healthy
    RegionEndpoint primary = pickPreferred();
    Callable<Response> primaryCall = () -> doCall(primary, "GET", path, headers, null);

    List<RegionEndpoint> backups = healthyBackups(primary);
    if (backups.isEmpty()) return exec(primaryCall);

    RegionEndpoint hedge = backups.get(0);
    CompletableFuture<Response> p = CompletableFuture.supplyAsync(() -> execUnchecked(primaryCall));
    CompletableFuture<Response> h = p.applyToEither(timeout(hedgeDelay), x -> x) // if not done by hedgeDelay, start hedge
        .thenApply(r -> r) // no-op; just chaining
        .exceptionally(ex -> null)
        .thenCompose(ignored -> CompletableFuture.supplyAsync(() ->
            execUnchecked(() -> doCall(hedge, "GET", path, headers, null))));

    // whichever completes first
    try {
      Response winner = CompletableFuture.anyOf(p, h).thenApply(r -> (Response) r).get();
      // close the loser to free sockets
      (winner == p.getNow(null) ? h : p).thenAccept(this::closeQuietly);
      return winner;
    } catch (Exception e) {
      throw unwrap(e);
    }
  }

  /** Idempotent write (PUT/DELETE) with regional failover if needed. */
  public Response put(String path, byte[] body, Map<String,String> headers) throws IOException {
    return idempotentWithFailover("PUT", path, headers, body);
  }
  public Response delete(String path, Map<String,String> headers) throws IOException {
    return idempotentWithFailover("DELETE", path, headers, null);
  }

  // -------------- internals --------------

  private Response idempotentWithFailover(String method, String path, Map<String,String> headers, byte[] body) throws IOException {
    IOException last = null;
    int attempts = 0;
    for (RegionEndpoint ep : healthyByPreference()) {
      try {
        attempts++;
        return doCall(ep, method, path, headers, body);
      } catch (IOException ioe) {
        last = ioe;
        if (attempts > maxIdempotentRetries + 1) break;
      }
    }
    throw last != null ? last : new IOException("all regions failed");
  }

  private Response doCall(RegionEndpoint ep, String method, String path, Map<String,String> headers, byte[] body) throws IOException {
    long start = System.nanoTime();
    Request.Builder rb = new Request.Builder()
        .url(ep.baseUrl.newBuilder().addPathSegments(strip(path)).build())
        .header("X-Region-Preferred", endpoints.get(0).region)
        .header("X-Region-Attempt", ep.region);
    headers.forEach(rb::header);
    if (Objects.equals(method, "GET")) rb = rb.get();
    else if (Objects.equals(method, "DELETE")) rb = rb.delete();
    else rb = rb.method(method, RequestBody.create(body != null ? body : new byte[0]));

    try {
      Response resp = client.newCall(rb.build()).execute();
      observe(ep, start);
      return resp;
    } catch (IOException ioe) {
      observe(ep, start);
      ep.healthy = false; // pessimistic; health loop will restore
      throw ioe;
    }
  }

  private void observe(RegionEndpoint ep, long startNs) {
    long micros = Math.max(1000, (System.nanoTime() - startNs) / 1_000);
    long old = ep.ewmaMicros.get();
    long updated = (long)(0.2 * micros + 0.8 * old);
    ep.ewmaMicros.set(updated);
  }

  private RegionEndpoint pickPreferred() {
    return healthyByPreference().get(0);
    // could do P2C/latency-aware here if multiple “preferreds”
  }

  private List<RegionEndpoint> healthyByPreference() {
    List<RegionEndpoint> hs = endpoints.stream().filter(e -> e.healthy).collect(Collectors.toList());
    return hs.isEmpty() ? List.of(endpoints.get(0)) : hs;
  }
  private List<RegionEndpoint> healthyBackups(RegionEndpoint exclude) {
    return endpoints.stream().filter(e -> e != exclude && e.healthy).toList();
  }

  private static String strip(String p) { return p.startsWith("/") ? p.substring(1) : p; }
  private static <T> CompletableFuture<T> timeout(Duration d) {
    var cf = new CompletableFuture<T>();
    Executors.newSingleThreadScheduledExecutor(r -> { var t = new Thread(r); t.setDaemon(true); return t; })
        .schedule(() -> cf.completeExceptionally(new TimeoutException()), d.toMillis(), TimeUnit.MILLISECONDS);
    return cf;
  }
  private static Response exec(Callable<Response> c) throws IOException { try { return c.call(); } catch (Exception e) { throw unwrap(e); } }
  private static Response execUnchecked(Callable<Response> c) { try { return c.call(); } catch (Exception e) { throw new CompletionException(e); } }
  private static IOException unwrap(Exception e) { return e instanceof IOException io ? io : new IOException(e); }
  private void probeLoop() {
    OkHttpClient hc = client.newBuilder().readTimeout(Duration.ofMillis(250)).callTimeout(Duration.ofMillis(300)).build();
    while (true) {
      for (RegionEndpoint ep : endpoints) {
        try {
          Request req = new Request.Builder().url(ep.baseUrl.newBuilder().addPathSegment("health").build()).build();
          try (Response r = hc.newCall(req).execute()) { ep.healthy = r.isSuccessful(); }
        } catch (Exception ex) { ep.healthy = false; }
      }
      try { Thread.sleep(2_000); } catch (InterruptedException ignored) { Thread.currentThread().interrupt(); }
    }
  }
  private void closeQuietly(Response r) { try { if (r != null) r.close(); } catch (Exception ignored) {} }

  // Example
  public static void main(String[] args) throws Exception {
    RegionAwareHttpClient client = new RegionAwareHttpClient(List.of(
        new RegionEndpoint("eu-central-1", "https://eu.example.com/"),
        new RegionEndpoint("us-east-1", "https://us.example.com/")
    ));
    try (Response r = client.get("/api/v1/profile", Map.of("Accept","application/json"))) {
      System.out.println(r.code() + " " + Objects.requireNonNull(r.body()).string());
    }
  }
}
```

**What this demonstrates**

-   Client-side multi-region routing that plays well with server-side GSLB.
    
-   **Hedged reads** mitigate long tails when a single region is briefly slow.
    
-   Safe **failover** for idempotent operations.
    
-   **Region headers** expose the decision to servers and logs.
    

> Server-side you would complement this with **region-local caches**, data residency enforcement, and **read-after-write** rules (e.g., sticky-to-leader after a write, or LSN/GTID waits before reading from a replica in another region).

---

## Known Uses

-   **Global consumer apps** (video, social, e-commerce) serving from multiple continents.
    
-   **B2B SaaS** with **data residency** (EU/US) and customer-pinned regions.
    
-   **Financial trading** with **active–active** risk engines across metro regions.
    
-   **Public clouds’ managed services** (multi-region databases, object stores) underpinning app DR.
    

---

## Related Patterns

-   **Load Balancer / GSLB:** Front-door traffic steering and health-based failover.
    
-   **Horizontal Scaling & Auto Scaling Group:** Regional elasticity.
    
-   **Database Replication & Sharding:** Per-region read scale and partitioned writes.
    
-   **CQRS / Materialized Views:** Region-local read models fed by cross-region events.
    
-   **Idempotent Receiver / Retry with Backoff / Timeouts:** Make cross-region retries safe.
    
-   **Leader Election & Fencing:** Clean promotions during regional failover.
    
-   **Distributed Cache:** Region-local caching; avoid cross-region chattiness.
    

---

## Implementation Checklist

-   Define **RTO/RPO** per domain; choose **active–active** or **active–passive** accordingly.
    
-   Pick **traffic steering** (DNS/GSLB/Anycast) with **health checks** and **low TTLs**.
    
-   Make services **stateless** or **partition** state; externalize sessions, files, and caches **per region**.
    
-   Choose a **data strategy**: per-partition leaders, global DB, or evented read models; document **read-after-write** policy.
    
-   Implement **fencing tokens/epochs** for safe promotion; test regional blackholes and rollbacks.
    
-   Enforce **data residency** (routing + storage boundaries).
    
-   Add **observability** with region tags: request counts/latency, replication lag, failover events.
    
-   Automate **deploys** and **schema changes** per region; support **side-by-side** migrations.
    
-   Run **regular DR drills** (game days): DNS failover, partial brownouts, replica promotion, and back pressure.
    
-   Control **costs** (egress, duplicate capacity); use **weighted traffic** and **right-sizing** per region.

