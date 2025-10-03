# Multi-Region Deployment - Cloud Distributed Systems Pattern

## Pattern Name and Classification

-   **Name:** Multi-Region Deployment

-   **Classification:** Architectural pattern for **resilience, scalability, and geo-distribution** (deployment/runtime topology)


## Intent

Run independent but cooperating stacks in multiple geographic regions to:

-   survive regional outages (very high availability, low RTO/RPO),

-   serve users with **lower latency** close to where they are,

-   satisfy **data residency** and compliance constraints,

-   scale elastically across the globe.


## Also Known As

-   Multi-DC / Geo-Redundant Architecture

-   Active-Active (A/A), Active-Passive (A/P)

-   Region Sharding / Geo-Partitioning

-   Multi-Primary / Multi-Master (for data)


## Motivation (Forces)

-   **Availability vs. Consistency:** Cross-region links are slower/unreliable. Strong consistency hurts latency; async replication risks conflicts and data loss (RPO>0).

-   **Latency:** Users expect p95 sub-second responses. Serving from the closest region plus caching reduces tail latency.

-   **Blast Radius:** Regional isolation limits failure scope; need **fault containment** and failover.

-   **Data Residency & Sovereignty:** Some data must **not** leave a jurisdiction; impacts routing/replication.

-   **Operational Complexity & Cost:** More moving parts: traffic steering, replication, keys, encryption, observability, release orchestration, chaos testing.

-   **Schema & Versioning:** Cross-region upgrades require **backwards-compatible, rolling** changes.

-   **Traffic Patterns:** Hotspots, seasonal shifts; need weighted steering and surge protection.


## Applicability

Use when you need:

-   **mission-critical SLAs** (e.g., >99.95%) and DR beyond a single region,

-   **global audience** or strict **data-residency** requirements,

-   **business continuity** during regional maintenance/incidents,

-   **blue/green & canary at regional granularity**.


## Structure

-   **Global Traffic Manager (GTM):** Anycast + BGP, Geo/Latency-based DNS, or application-level router.

-   **Regional Stacks:** Independent copies (ingress, services, data stores, queues).

-   **Replication Layer:** DB multi-region (single-leader, multi-leader, or CRDT), log shipping, CDC → stream.

-   **Control Plane:** Config, feature flags, deployment orchestrator, secret mgmt.

-   **Observability Plane:** Global SLOs, region health, error budgets, synthetic probes.

-   **Compliance Guardrails:** Residency policies, encryption, key scoping, DLP.


```mathematica
Client ──► GTM/DNS/Anycast ──► Region A  ──┐
                         └──► Region B  ──┼──► Async/Bi-dir Replication (DB/Log)
                         └──► Region C  ──┘
```

## Participants

-   **Global Router:** Decides which region gets a request (geo/latency/weights/affinity).

-   **Regional Ingress/Gateway:** Terminates TLS, enforces auth/WAF, routes to services.

-   **Replication/CDC:** Moves data/events across regions; handles conflict resolution.

-   **Service Instances:** Stateless services per region.

-   **Regional Datastores:** Partitioned or replicated data.

-   **Health/Prober:** Synthetic checks and SLO monitoring.

-   **Failover Controller:** Adjusts routing weights, drains broken regions.

-   **Config/Flag Service:** Coordinates rollout waves and behavior.


## Collaboration

1.  Client resolves a global endpoint; GTM picks **closest healthy** region.

2.  Request hits a regional gateway → services → datastore.

3.  Writes: (a) go to **local leader** and replicate async, or (b) go to per-key leader (partitioned), or (c) use globally consistent DB (Spanner-like).

4.  On failures, router **fails over** to next best region; clients may retry with **idempotency keys**.

5.  Observability and health checks feed GTM and automation to adjust weights or trigger **evacuation**.


## Consequences

**Benefits**

-   Survives full-region outages; reduces user latency; enables jurisdictional data control; supports progressive, **regional canaries**.


**Liabilities / Trade-offs**

-   Complexity (routing, data semantics, conflicts, schema mgmt).

-   Cost: duplicate infra + data egress.

-   Consistency limits: async replication → RPO>0; strong global consistency → latency & availability penalties.

-   Operational pitfalls: retry storms, split-brain, partial data visibility, clock skew.


## Implementation (Key Points)

-   **Topology:** Choose **A/A** (serve everywhere) vs **A/P** (one hot, others warm).

-   **Routing:** Anycast/GeoDNS/latency-based; support region stickiness + **safe failover**.

-   **Data Strategies:**

    -   **Single-leader per key/tenant** via consistent hashing.

    -   **Multi-leader** with conflict resolution (LWW, vector clocks, CRDTs).

    -   **Globally consistent DBs** (Spanner, CockroachDB) for strong invariants.

-   **Idempotency:** Idempotency keys on writes; dedupe across regions.

-   **Schema:** Expand-then-contract migrations; **read-old/write-new**; dual-write only with guards.

-   **Resiliency Controls:** Circuit breakers, outlier detection, budgets, hedged requests (limited & bounded).

-   **Observability:** Global SLOs, per-region error/latency, replication lag, **RPO trackers**.

-   **Compliance:** Tag/route PII to allowed regions; key management per region.

-   **Testing:** Fault injection (region blackhole), game days, DS runbooks; **chaos** at region level.


---

## Sample Code (Java 17): Region-Aware HTTP Client with Per-Key Home-Region + Failover

> Educational (no external libs). Demonstrates:
>
> -   Consistent hashing to pick a **home region per tenant/key**
>
> -   Region health & simple circuit breaker
>
> -   **Idempotency-Key** header, **bounded retries** with backoff & jitter
>
> -   Failover to secondary region when primary is down/slow
>

```java
// File: RegionAwareClient.java
// Usage (demo endpoints): adapt BASE URLs to your regional gateways.
import java.io.IOException;
import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ThreadLocalRandom;

public class RegionAwareClient {

    // ---- Region definition ----
    public static final class Region {
        public final String name;      // e.g., "eu-central-1"
        public final URI baseUri;      // e.g., "https://eu.example.com/"
        public Region(String name, String base) { this.name = name; this.baseUri = URI.create(base); }
        @Override public String toString() { return name + "(" + baseUri + ")"; }
    }

    // ---- Simple circuit breaker per region ----
    public static final class CircuitBreaker {
        private final int failureThreshold;
        private final Duration openDuration;
        private int consecutiveFailures = 0;
        private long openUntilMillis = 0L;
        public CircuitBreaker(int failureThreshold, Duration openDuration) {
            this.failureThreshold = failureThreshold; this.openDuration = openDuration;
        }
        public synchronized boolean canPass() {
            long now = System.currentTimeMillis();
            if (now < openUntilMillis) return false;
            return true;
        }
        public synchronized void onSuccess() { consecutiveFailures = 0; }
        public synchronized void onFailure() {
            consecutiveFailures++;
            if (consecutiveFailures >= failureThreshold) {
                openUntilMillis = System.currentTimeMillis() + openDuration.toMillis();
                consecutiveFailures = 0; // half-open after timeout
            }
        }
    }

    // ---- Rendezvous (HRW) hashing for stable home-region selection ----
    public interface RegionPicker { Region pickHomeRegion(String key); List<Region> ranked(String key); }
    public static final class RendezvousPicker implements RegionPicker {
        private final List<Region> regions;
        public RendezvousPicker(List<Region> regions) { this.regions = List.copyOf(regions); }
        private long score(String key, Region r) {
            return Objects.hash(key, r.name) ^ (long)r.name.hashCode() << 32;
        }
        public Region pickHomeRegion(String key) {
            return regions.stream().max(Comparator.comparingLong(r -> score(key, r))).orElseThrow();
        }
        public List<Region> ranked(String key) {
            return regions.stream()
                    .sorted(Comparator.comparingLong((Region r) -> score(key, r)).reversed())
                    .toList();
        }
    }

    // ---- Client config ----
    public static final class Config {
        public final int maxRetries;                  // total tries across regions
        public final Duration reqTimeout;             // per-try timeout
        public final Duration baseBackoff;            // for retry with jitter
        public final boolean sendIdempotencyKey;      // attach header
        public Config(int maxRetries, Duration reqTimeout, Duration baseBackoff, boolean sendIdempotencyKey) {
            this.maxRetries = maxRetries; this.reqTimeout = reqTimeout; this.baseBackoff = baseBackoff;
            this.sendIdempotencyKey = sendIdempotencyKey;
        }
    }

    private final HttpClient http;
    private final RegionPicker picker;
    private final Map<String, CircuitBreaker> breakers = new ConcurrentHashMap<>();
    private final Config cfg;

    public RegionAwareClient(List<Region> regions, Config cfg) {
        this.http = HttpClient.newBuilder().connectTimeout(cfg.reqTimeout).version(HttpClient.Version.HTTP_1_1).build();
        this.picker = new RendezvousPicker(regions);
        this.cfg = cfg;
        regions.forEach(r -> breakers.put(r.name, new CircuitBreaker(3, Duration.ofSeconds(10))));
    }

    // ---- Public API: region-aware POST with failover ----
    public HttpResponse<String> postJson(String tenantKey, String path, String jsonBody) throws IOException, InterruptedException {
        String idempotencyKey = cfg.sendIdempotencyKey ? UUID.randomUUID().toString() : null;

        List<Region> candidates = picker.ranked(tenantKey);
        int attempts = 0;

        for (Region region : candidates) {
            CircuitBreaker cb = breakers.get(region.name);
            if (!cb.canPass()) continue; // region temporarily ejected

            try {
                HttpRequest req = HttpRequest.newBuilder(region.baseUri.resolve(path))
                        .timeout(cfg.reqTimeout)
                        .header("content-type", "application/json")
                        .header("x-tenant-key", tenantKey)
                        .method("POST", HttpRequest.BodyPublishers.ofString(jsonBody))
                        .build();

                HttpRequest.Builder rb = HttpRequest.newBuilder(req.uri())
                        .timeout(cfg.reqTimeout)
                        .header("content-type", "application/json")
                        .header("x-tenant-key", tenantKey)
                        .POST(HttpRequest.BodyPublishers.ofString(jsonBody));

                if (idempotencyKey != null) rb.header("idempotency-key", idempotencyKey);

                HttpResponse<String> resp = http.send(rb.build(), HttpResponse.BodyHandlers.ofString());
                int sc = resp.statusCode();
                if (sc >= 200 && sc < 300) { cb.onSuccess(); return resp; }

                // Treat certain 5xx as retryable
                if (isRetryable(sc) && attempts < cfg.maxRetries) {
                    cb.onFailure();
                    sleepBackoff(attempts++);
                    continue; // try next region
                }
                // Non-retryable or attempts exhausted
                cb.onFailure();
                return resp;
            } catch (IOException | InterruptedException ex) {
                cb.onFailure();
                if (attempts++ >= cfg.maxRetries) throw ex;
                sleepBackoff(attempts);
                // try next region in the ranked list
            }
        }
        throw new IOException("no healthy regions available after failover attempts");
    }

    private static boolean isRetryable(int status) { return status == 502 || status == 503 || status == 504; }

    private void sleepBackoff(int attempt) {
        long base = Math.max(1, cfg.baseBackoff.toMillis());
        long maxJitter = base / 2;
        long sleep = (long)Math.min(10_000, base * Math.pow(2, Math.max(0, attempt - 1))) +
                     ThreadLocalRandom.current().nextLong(maxJitter);
        try { Thread.sleep(sleep); } catch (InterruptedException ignored) { Thread.currentThread().interrupt(); }
    }

    // ---- Demo main (replace endpoints with real regional gateways) ----
    public static void main(String[] args) throws Exception {
        List<Region> regions = List.of(
                new Region("eu-central-1", "https://eu.example.com/"),
                new Region("us-east-1",   "https://us.example.com/"),
                new Region("ap-southeast-1", "https://ap.example.com/")
        );

        RegionAwareClient client = new RegionAwareClient(
                regions,
                new Config(2, Duration.ofSeconds(3), Duration.ofMillis(200), true)
        );

        String tenant = "acme-co"; // home region chosen via rendezvous hashing
        String payload = "{\"orderId\":\"123\",\"amount\":49.9}";

        try {
            HttpResponse<String> resp = client.postJson(tenant, "/orders", payload);
            System.out.println("HTTP " + resp.statusCode() + " from " + resp.uri() + " body=" + resp.body());
        } catch (IOException | InterruptedException e) {
            System.err.println("request failed across all regions: " + e.getMessage());
        }
    }
}
```

**Notes on making this production-grade**

-   Replace `https://*.example.com/` with real per-region gateways (or a single anycast VIP that exposes a `X-Region` header).

-   Persist and reuse **Idempotency-Key** per logical operation (e.g., order create) so cross-region retries cannot double-book.

-   Bound total request budget (overall timeout) and set per-try budgets.

-   Add **hedged requests** only for safe, idempotent reads; cap concurrency and cancel on first success.

-   Integrate with a **global config/flag** system to dynamically eject/weight regions.


---

## Known Uses

-   **Netflix**: active-active regions with regional failover and traffic steering.

-   **Cloudflare / Fastly**: global anycast with regional isolation.

-   **AWS, Azure, GCP**: multi-region reference architectures (Route 53/Traffic Manager/Cloud DNS; ALB/AGW/HTTP(S) LB; global databases like DynamoDB Global Tables, Spanner, Cosmos DB).

-   **Banks & Payments**: per-tenant regional homes, idempotency keys, and ledger replication.

-   **Git providers / SaaS**: geo-partitioned data + regional read replicas for latency.


## Related Patterns

-   **Load Balancer (L7/L4)** – per-region and global front doors

-   **Service Discovery** – find healthy targets per region

-   **Circuit Breaker / Bulkhead / Rate Limiter** – avoid cascading failures

-   **Saga / Outbox / Event Sourcing** – reconcile async, cross-region workflows

-   **Geo-Partitioning / Sharding** – per-tenant/home-region ownership

-   **CDN / Edge Cache** – move reads to the edge

-   **Blue-Green / Canary** – region-by-region rollouts

-   **Leader Election / Quorum** – when using strongly consistent, multi-region data stores


---

### Implementation Checklist (quick)

-   Choose **A/A vs A/P**, and **data strategy** (per-key leader, multi-leader w/ CRDT, or global DB).

-   Establish **idempotency** and **dedup** keys for writes.

-   Define **routing rules** (geo/latency/weights/residency).

-   Instrument **replication lag** & **RPO monitors**; alert on SLOs.

-   Practice **region evacuation** runbooks & chaos experiments.

-   Enforce **schema compatibility** and **feature flags** across waves.
