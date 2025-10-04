# Canary Testing — Testing Pattern

## Pattern Name and Classification

-   **Name:** Canary Testing
    
-   **Classification:** Online Testing / Progressive Delivery / Risk-Mitigation Deployment Pattern
    

## Intent

Release a new version to a **small, controlled slice of traffic** first, **observe guardrail metrics** (errors, latency, saturation, business KPIs), and **auto-promote or roll back** based on evidence. The goal is to **detect regressions early** with minimal blast radius.

## Also Known As

-   Canary Release / Canary Deployment
    
-   Progressive Rollout
    
-   Dark Launch (closely related; traffic may be mirrored rather than user-visible)
    
-   One-Box / One-Shard Test (variant at host/shard granularity)
    

## Motivation (Forces)

-   **Speed vs. safety:** ship often without risking all users.
    
-   **Heterogeneity:** production is the only environment with real traffic patterns.
    
-   **Observability:** need real-user signals (SLOs, KPIs) to validate changes.
    
-   **Isolation:** keep failures localized; prefer reversible steps.
    
-   **Ethics & UX:** avoid widespread exposure to broken features.
    

Canary testing balances these by gating exposure (1% → 5% → 25% → 50% → 100%) while continuously checking **guardrails** and **error budgets**.

## Applicability

Use when:

-   You can route traffic by **percentage** or **key affinity** (user, tenant, shard).
    
-   Telemetry for guardrails is available in near-real time.
    
-   Rollback is possible (blue/green, feature flag, fast redeploy).
    

Avoid or adapt when:

-   Changes are **data-migrating or irreversible** without backout.
    
-   Safety fixes must go **all-at-once** (security patches—use fast deploy + broad monitors).
    
-   Strong network effects/interference make partial rollout misleading.
    

## Structure

-   **Traffic Manager:** routes a fraction of requests to canary (sticky by key).
    
-   **Canary Population:** instances/shards running the new version.
    
-   **Control Population:** stable version serving the rest.
    
-   **Metrics Pipeline:** collects latency, error rate, saturation, and business KPIs.
    
-   **Analyzer / Policy Engine:** compares canary vs. control; triggers promote/rollback.
    
-   **Release Controller:** automates ramps and reverts.
    

```java
Clients ──► Router/Proxy ──┬──► Control v1 (95%)
                           └──► Canary  v2 (5%)
                           ↑            │
                   (sticky by userId)   └─► Metrics → Analyzer → Promote/Rollback
```

## Participants

-   **Release Engineer / SRE / Team** — defines ramp plan and guardrails.
    
-   **Router / Gateway** — implements percentage or key-based routing and stickiness.
    
-   **Telemetry** — traces, logs, metrics, business events.
    
-   **Analyzer** — statistical/heuristic comparison (SLO, error budget burn).
    
-   **Deployment System / Flag Service** — adjusts traffic splits and rollbacks.
    

## Collaboration

1.  Deploy **v2** alongside **v1**; mark v2 as *canary*.
    
2.  Router assigns a small, **sticky** slice of users/requests to v2.
    
3.  Collect guardrail and business metrics for both populations.
    
4.  Analyzer checks **SLO deltas** (e.g., p95 latency + error rate).
    
5.  If healthy → **increase** canary share; if unhealthy → **rollback** (route 0% to v2 and/or undeploy).
    

## Consequences

**Benefits**

-   Limits blast radius; **fast detection** of regressions.
    
-   Uses **real production** traffic; less simulation gap.
    
-   Enables **automatic** promote/rollback policies.
    

**Liabilities**

-   Requires mature **observability** and fast rollback paths.
    
-   Partial rollouts can hide **rare bugs** until later ramps.
    
-   **Stateful** changes and **schema migrations** complicate backouts.
    
-   Coordination across **dependent services** is non-trivial.
    

## Implementation

### Design Guidelines

-   **Stickiness:** assign by a stable key (userId, session, tenant) using deterministic hashing.
    
-   **Guardrails:** define thresholds before rollout (e.g., error rate ≤ +0.2%, p95 latency ≤ +10%, CPU < 80%).
    
-   **Windows:** evaluate over rolling windows (e.g., last 5–15 minutes) to avoid noise.
    
-   **Promotion policy:** gated ramps (1%→5%→25%…) only if all guardrails pass; require **minimum sample size**.
    
-   **Rollback policy:** immediate revert if hard thresholds exceed or **SR (success rate)** drops sharply.
    
-   **Separation of concerns:** keep routing in gateway/flag service; keep analysis in control plane.
    
-   **Data changes:** use **expand/contract** migrations; make writes **backward compatible**.
    

### Operational Checklist

-   Blue/green or **feature flag** in front of the new path.
    
-   **Dashboards & alerts** split by *canary vs. control*.
    
-   **Error budget** accounting for the canary.
    
-   **Kill switch** to 0% canary in one action.
    
-   Automated **post-canary report** before 100% rollout.
    

---

## Sample Code (Java 17)

A framework-free sketch that:

-   Implements **sticky assignment** by hashing `userId` against a **canary share**.
    
-   Routes to `v1` or `v2` service implementations.
    
-   Tracks per-variant metrics in a rolling window and **auto-rolls back** if canary error rate exceeds a threshold after a minimum exposure.
    

```java
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ThreadLocalRandom;

/** Request/Response model */
record Request(String userId, String path) { }
record Response(int status, String body, long latencyMillis) { }

/** Service contract with two versions */
interface Service { Response handle(Request r); }

class ServiceV1 implements Service {
  public Response handle(Request r) {
    // stable baseline
    long t0 = System.nanoTime();
    busyWait(2, 8);
    return new Response(200, "v1 OK", (System.nanoTime()-t0)/1_000_000);
  }
  static void busyWait(int minMs, int maxMs) {
    try { Thread.sleep(ThreadLocalRandom.current().nextInt(minMs, maxMs)); } catch (InterruptedException ignored) {}
  }
}

class ServiceV2 implements Service {
  private final double errorRate;     // simulate regression risk
  private final int extraLatencyMs;   // simulate latency regression
  ServiceV2(double errorRate, int extraLatencyMs){ this.errorRate = errorRate; this.extraLatencyMs = extraLatencyMs; }
  public Response handle(Request r) {
    long t0 = System.nanoTime();
    ServiceV1.busyWait(2 + extraLatencyMs, 8 + extraLatencyMs);
    if (ThreadLocalRandom.current().nextDouble() < errorRate) {
      return new Response(500, "v2 ERROR", (System.nanoTime()-t0)/1_000_000);
    }
    return new Response(200, "v2 OK", (System.nanoTime()-t0)/1_000_000);
  }
}

/** Sticky percentage assignment using salted MD5 → bucket [0, 9999] */
class CanaryGate {
  private final String seed;
  private volatile int shareBp; // basis points (0..10000)

  CanaryGate(String seed, int initialShareBp) { this.seed = seed; this.shareBp = initialShareBp; }
  void setShareBp(int bp) { this.shareBp = Math.max(0, Math.min(10_000, bp)); }
  int getShareBp() { return shareBp; }

  boolean routeToCanary(String userId) {
    int bucket = bucket(seed, userId);
    return bucket < shareBp;
  }
  static int bucket(String seed, String key) {
    try {
      MessageDigest md = MessageDigest.getInstance("MD5");
      byte[] d = md.digest((seed + ":" + key).getBytes(StandardCharsets.UTF_8));
      int v = ((d[0] & 0xff) << 24) | ((d[1] & 0xff) << 16) | ((d[2] & 0xff) << 8) | (d[3] & 0xff);
      long u = v & 0xffffffffL;
      return (int) (u % 10_000L);
    } catch (Exception e) { throw new RuntimeException(e); }
  }
}

/** Rolling window metrics per variant (very small, approximate) */
class RollingMetrics {
  static class Point { final boolean error; final long latency; final Instant at;
    Point(boolean error, long latency){ this.error = error; this.latency = latency; this.at = Instant.now(); } }
  private final Deque<Point> points = new ArrayDeque<>();
  private final Duration window = Duration.ofSeconds(60);

  synchronized void record(boolean error, long latency) {
    points.addLast(new Point(error, latency)); trim();
  }
  synchronized long samples() { trim(); return points.size(); }
  synchronized double errorRate() {
    trim(); if (points.isEmpty()) return 0.0;
    long err = points.stream().filter(p -> p.error).count();
    return (double) err / points.size();
  }
  synchronized double p95Latency() {
    trim(); if (points.isEmpty()) return 0.0;
    return points.stream().mapToLong(p -> p.latency).sorted().skip((long)Math.ceil(points.size()*0.95)-1).findFirst().orElse(0);
    // NOTE: rough p95; production uses HDRHistograms or similar
  }
  private void trim() {
    Instant cut = Instant.now().minus(window);
    while (!points.isEmpty() && points.peekFirst().at.isBefore(cut)) points.removeFirst();
  }
}

/** Router with auto-promotion/rollback policy */
class CanaryRouter {
  private final Service control;
  private final Service canary;
  private final CanaryGate gate;
  private final RollingMetrics mControl = new RollingMetrics();
  private final RollingMetrics mCanary  = new RollingMetrics();

  // Guardrail policy
  private final double maxErrorDelta = 0.003;     // canary error <= control error + 0.3%
  private final int maxP95DeltaMs    = 50;        // canary p95 <= control p95 + 50ms
  private final long minCanarySamples = 2_000;    // need some signal before actions

  CanaryRouter(Service control, Service canary, CanaryGate gate) {
    this.control = control; this.canary = canary; this.gate = gate;
  }

  public Response handle(Request r) {
    boolean toCanary = gate.routeToCanary(r.userId());
    Response res = toCanary ? canary.handle(r) : control.handle(r);
    if (toCanary) mCanary.record(res.status() >= 500, res.latencyMillis());
    else          mControl.record(res.status() >= 500, res.latencyMillis());
    maybeAct();
    return res;
  }

  /** Adjust traffic if guardrails fail/pass (demo heuristic). */
  private void maybeAct() {
    if (mCanary.samples() < minCanarySamples || mControl.samples() < 1_000) return;

    double errCtl = mControl.errorRate(), errCan = mCanary.errorRate();
    double p95Ctl = mControl.p95Latency(), p95Can = mCanary.p95Latency();

    boolean unhealthy = (errCan > errCtl + maxErrorDelta) || (p95Can > p95Ctl + maxP95DeltaMs);

    if (unhealthy && gate.getShareBp() > 0) {
      // Roll back aggressively
      gate.setShareBp(0);
      System.out.printf(Locale.ROOT,
        "[ROLLBACK] canaryShare->0%%  err ctl=%.3f%% can=%.3f%%  p95 ctl=%.0fms can=%.0fms%n",
        100*errCtl, 100*errCan, p95Ctl, p95Can);
    } else if (!unhealthy && gate.getShareBp() < 10_000) {
      // Promote gradually (e.g., double until 50%, then +10%)
      int next = gate.getShareBp() < 5_000 ? Math.min(5_000, Math.max(100, gate.getShareBp()*2))
                                           : Math.min(10_000, gate.getShareBp() + 1_000);
      if (next != gate.getShareBp()) {
        gate.setShareBp(next);
        System.out.printf(Locale.ROOT,
          "[PROMOTE] canaryShare->%.1f%%  err ctl=%.3f%% can=%.3f%%  p95 ctl=%.0fms can=%.0fms%n",
          next/100.0, 100*errCtl, 100*errCan, p95Ctl, p95Can);
      }
    }
  }
}

/** Demo main: simulate load with a slightly worse v2 to trigger rollback/promotion logic */
public class CanaryTestingDemo {
  public static void main(String[] args) {
    Service v1 = new ServiceV1();
    Service v2 = new ServiceV2(/*errorRate*/0.01, /*extraLatencyMs*/10); // tweak to test behavior
    CanaryGate gate = new CanaryGate("price-service", /*initial 1%*/100);
    CanaryRouter router = new CanaryRouter(v1, v2, gate);

    // Simulate requests
    for (int i = 0; i < 200_000; i++) {
      String user = "user-" + (i % 50_000);                 // sticky assignment
      router.handle(new Request(user, "/price?id=" + (i%1000)));
      if (i % 10_000 == 0) {
        System.out.printf("Progress: %,d reqs  canary=%.1f%%%n", i, gate.getShareBp()/100.0);
      }
    }
    System.out.println("Done. Final canary share: " + gate.getShareBp()/100.0 + "%");
  }
}
```

**What this demonstrates**

-   **Sticky canary assignment** by user via salted hashing.
    
-   **Per-variant rolling metrics** (error rate & p95 latency).
    
-   A tiny **policy engine** that **promotes** or **rolls back** automatically.
    
-   Change `ServiceV2`’s `errorRate`/`extraLatencyMs` to observe different outcomes.
    

> In production, you would run this logic in (or next to) your API gateway or service mesh, and use real metrics (e.g., Prometheus/HDRHistogram), proper significance tests, error budgets, and safe database migration patterns.

## Known Uses

-   **Web/API platforms**: gradually rolling out new code paths behind flags.
    
-   **Mobile backends**: server-side changes canary with client feature switch.
    
-   **Data pipelines / stream processors**: canary instances process a slice of partitions/topics.
    
-   **Config changes**: JVM/GC flags, cache TTL, retry policies canaried behind control planes.
    
-   **ML models**: online scoring services canary a new model and compare live metrics.
    

## Related Patterns

-   **A/B Testing:** randomized experiments to measure *causal* impact; can be combined with canaries but different goals.
    
-   **Blue–Green Deployment:** two full environments; canary often runs on the *green* before full cutover.
    
-   **Feature Flags / Toggles:** the mechanism to switch traffic on/off at runtime.
    
-   **Circuit Breaker & Bulkhead:** guard calling paths during canary to prevent cascading failures.
    
-   **Shadow (Dark) Traffic:** mirror requests to new version without serving results; pre-canary safety net.
    

---

