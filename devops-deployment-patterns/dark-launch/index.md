
# Dark Launch — DevOps Deployment Pattern

## Pattern Name and Classification

-   **Name:** Dark Launch

-   **Category:** DevOps / Release Engineering / Progressive Delivery Pattern

-   **Level:** System/Process pattern (spans app, infrastructure, and observability)


---

## Intent

Release new functionality to production **without exposing it to all (or any) end-users** at first, in order to validate performance, compatibility, and operational behavior under real workloads. Gradually increase exposure (cohorts, % rollout, geos) while measuring impact and keeping an instant rollback path.

---

## Also Known As

-   Feature Flags / Feature Toggles (as a key enabling technique)

-   Controlled Rollout / Progressive Exposure

-   Shadow Release (when combined with shadow traffic)

-   Pre-visibility Launch


---

## Motivation (Forces)

-   **Reduce blast radius:** New code runs in prod but is invisible or limited to small cohorts.

-   **Observe under real conditions:** Staging rarely mirrors real traffic, data skew, or integration timing.

-   **Separate deploy from release:** Ship continuously; “turn on” when business is ready.

-   **Fast rollback:** Turn off a flag vs. redeploying.

-   **Compliance/UX timing:** Coordinate marketing/UX/comms while the code bakes in prod.


**Forces & trade-offs**

-   Need **strong observability** (SLOs, traces, feature-level metrics).

-   **Config drift** risk: flags proliferate, dead code accrues.

-   **Ethical/privacy** concerns when using real user data for dark features—must be transparent internally and respect policies.

-   Beware **capacity overcommitment** if the hidden path is expensive.


---

## Applicability

Use Dark Launch when:

-   You want to vet **performance/latency** of a feature at production scale.

-   You need **canary-like** safety but with business gating (visibility off).

-   **Back-end changes** are substantial (new DB index, new cache tier) and you want confidence before UI release.

-   You are performing **schema-first** / **backward-compatible** rollouts.

-   You run **experiments** (A/B) or **gradual rollouts** (0.1% → 1% → 10% → 50% → 100%).


Avoid or adapt when:

-   Regulatory rules require explicit user consent for any processing.

-   The change is **destructive/incompatible** and cannot be safely toggled.


---

## Structure

-   **Code path guarded** by a **feature flag** (server or client).

-   **Cohort resolver** decides eligibility (user ID hash buckets, group memberships, geos, headers).

-   **Observability** is feature-scoped (logs/metrics/traces keyed by `feature=…`).

-   **Control plane** to flip flags and set rollout % (config service, GitOps, SaaS like Unleash/Togglz/LaunchDarkly, etc.).

-   **Safe fallback** path remains available.


```scss
[Config Store/Flag Service]
         │
         ▼
  [App Server] --(feature on?)--> [New Path] --┐
         │                                     │
         └--------------------> [Old Path] <---┘
             (fallback)           (compare, degrade)
```

---

## Participants

-   **Feature Owner** – defines cohorts and success criteria.

-   **Flag Service / Config Store** – central control of toggles and rollout % (with audit).

-   **Application Code** – checks flags, routes to new/old code paths.

-   **Observability Stack** – metrics, logs, traces, SLOs, anomaly detection.

-   **Release Engineer/SRE** – executes progressive exposure, rollback, and post-analysis.

-   **Data/Privacy Officer** – validates data handling where required.


---

## Collaboration

-   Often combined with **Canary Releases** (small % of traffic + auto rollback).

-   Works with **Blue/Green** (deploy dark on green, switch DNS when ready).

-   Complements **Shadow Traffic** (mirror requests to new path but discard responses).

-   Uses **Circuit Breakers & Rate Limits** for guardrails.

-   Tied to **Schema Evolution** patterns (expand-migrate-contract).


---

## Consequences

**Benefits**

-   Lower risk, faster recovery, empirical validation in production.

-   Decouples deploy/release for **business agility**.

-   Enables experimentation and **gradual adoption**.


**Liabilities**

-   **Operational complexity:** flag hygiene, config versioning, testing matrix explosion.

-   **Observability requirement:** must detect regressions at low traffic volumes.

-   **Tech debt:** stale flags create dead code; requires cleanup policy.

-   **Behavior drift:** dark and visible paths may diverge if not continuously tested.


---

## Implementation

1.  **Design for toggling**

    -   Make changes **backward compatible** (DB: additive columns/tables; APIs: additive fields).

    -   Define a **fallback** behavior that is always safe.

2.  **Introduce a Feature Flag**

    -   Store in central config with metadata: owner, expiry date, kill-switch, rollout policy (by %/cohort/geo).

    -   Enforce **flag TTLs** and automated reminders for cleanup.

3.  **Cohorting & Deterministic Bucketing**

    -   Compute a bucket from stable identifiers (e.g., `hash(userId) % 100`).

    -   Support allow/deny lists for internal testers.

4.  **Observability & SLOs**

    -   Tag all telemetry with `feature`, `variant`, `cohort`.

    -   Define **guardrail alerts** (latency p95, error rate, saturation).

    -   Add **synthetic checks** hitting both paths.

5.  **Progressive Exposure Workflow**

    -   0% (dark, internal only) → 0.1% → 1% → 5% → 10% → 25% → 50% → 100%.

    -   Hold at each step; compare KPIs vs control; **auto-rollback** if thresholds breached.

6.  **Rollback Plan**

    -   Global **kill switch** flips to fallback instantly.

    -   Keep deployment immutable; avoid hotfixing under pressure.

7.  **Operational Controls**

    -   RBAC on flag changes; audit logs.

    -   Pre-prod rehearsals of flag flips and rollbacks.

8.  **Cleanup**

    -   After 100% rollout and stability, **remove flag & dark path** in the next release.


---

## Sample Code (Java, Spring Boot)

**Goal:** Dark-launch a recommendation endpoint guarded by a feature flag with % rollout and cohorting.  
*(Uses a simple in-memory flag service for illustration; swap with Togglz/Unleash/LaunchDarkly in production.)*

```java
// 1) Feature Flag model
public record FeatureRule(String name, boolean enabled, int rolloutPercent) {}

// 2) Simple Flag Service (replace with real provider)
import java.util.concurrent.ConcurrentHashMap;
import java.util.Map;

public class FlagService {
    private final Map<String, FeatureRule> rules = new ConcurrentHashMap<>();

    public FlagService() {
        // default: dark (enabled=true but 0% rollout)
        rules.put("reco.v2", new FeatureRule("reco.v2", true, 0));
    }

    public FeatureRule get(String name) {
        return rules.getOrDefault(name, new FeatureRule(name, false, 0));
    }

    public void set(String name, boolean enabled, int percent) {
        rules.put(name, new FeatureRule(name, enabled, Math.max(0, Math.min(100, percent))));
    }

    public boolean isEnabledFor(String name, String stableId) {
        FeatureRule r = get(name);
        if (!r.enabled()) return false;
        int bucket = Math.floorMod(stableId.hashCode(), 100);
        return bucket < r.rolloutPercent();
    }
}
```

```java
// 3) Cohort utility
public final class Cohorts {
    private Cohorts() {}
    public static String stableId(String userId, String sessionId, String ip) {
        if (userId != null && !userId.isBlank()) return userId;
        if (sessionId != null && !sessionId.isBlank()) return sessionId;
        return ip == null ? "anonymous" : ip;
    }
}
```

```java
// 4) Spring configuration bean
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class FeatureConfig {
    @Bean
    public FlagService flagService() {
        return new FlagService();
    }
}
```

```java
// 5) Controller with dark/visible paths
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.bind.annotation.*;
import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;

@RestController
@RequestMapping("/api/recommendations")
public class RecommendationController {
    private static final Logger log = LoggerFactory.getLogger(RecommendationController.class);
    private final FlagService flags;
    private final RecoV1Service v1;
    private final RecoV2Service v2;

    public RecommendationController(FlagService flags, RecoV1Service v1, RecoV2Service v2) {
        this.flags = flags; this.v1 = v1; this.v2 = v2;
    }

    @GetMapping
    public Map<String, Object> get(@RequestHeader(value = "X-User-Id", required = false) String userId,
                                   @CookieValue(value = "SESSION", required = false) String sessionId,
                                   HttpServletRequest request) {

        String stableId = Cohorts.stableId(userId, sessionId, request.getRemoteAddr());
        boolean useV2 = flags.isEnabledFor("reco.v2", stableId);

        long start = System.nanoTime();
        try {
            Map<String, Object> payload = useV2 ? v2.recommend(stableId) : v1.recommend(stableId);
            log.info("feature=reco variant={} user={} size={}",
                     useV2 ? "v2" : "v1", stableId, payload.getOrDefault("count", 0));
            return payload;
        } catch (Exception e) {
            // Guardrail: fallback if v2 fails
            if (useV2) {
                log.warn("feature=reco variant=v2 error={}, falling back to v1", e.toString());
                return v1.recommend(stableId);
            }
            throw e;
        } finally {
            long durMs = (System.nanoTime() - start) / 1_000_000;
            log.info("feature=reco latency_ms={} variant={}", durMs, useV2 ? "v2" : "v1");
        }
    }
}
```

```java
// 6) Example services
import java.util.List;
import java.util.Map;

public interface RecoService {
    Map<String, Object> recommend(String stableId);
}

@org.springframework.stereotype.Service
class RecoV1Service implements RecoService {
    public Map<String, Object> recommend(String stableId) {
        return Map.of("variant", "v1", "count", 3, "items", List.of("A", "B", "C"));
    }
}

@org.springframework.stereotype.Service
class RecoV2Service implements RecoService {
    public Map<String, Object> recommend(String stableId) {
        // New algo, more expensive
        return Map.of("variant", "v2", "count", 4, "items", List.of("A", "B", "C", "D"));
    }
}
```

```java
// 7) Ops endpoint to change rollout (would be secured/RBAC in real life)
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/ops/flags")
class FlagAdminController {
    private final FlagService flags;
    FlagAdminController(FlagService flags) { this.flags = flags; }

    @PostMapping("/{name}")
    public String update(@PathVariable String name,
                         @RequestParam boolean enabled,
                         @RequestParam int percent) {
        flags.set(name, enabled, percent);
        return "Updated " + name + " enabled=" + enabled + " rollout=" + percent + "%";
    }
}
```

**Notes**

-   Replace `FlagService` with an actual provider (e.g., Togglz, Unleash).

-   Add **metrics** (Micrometer) and **traces** (OpenTelemetry) with `feature` and `variant` attributes.

-   Secure `/ops/flags/**` and audit changes.

-   Add a **kill switch** (set `enabled=false`) to instantly darken the feature.


---

## Known Uses

-   **Facebook** dark-launched significant News Feed changes before broad release.

-   **Google** and **Netflix** commonly use progressive exposure with flags and cohorting to validate performance and UX changes.

-   Many large SaaS companies employ dark launches for **search/ranking** changes, **recommenders**, and **billing** logic where correctness and latency are critical.


*(Concrete implementations vary; the concept is ubiquitous across progressive delivery platforms.)*

---

## Related Patterns

-   **Feature Flags / Toggles** – Mechanism enabling dark launches.

-   **Canary Release** – Traffic-percentage rollout with automated SLO guardrails.

-   **Blue/Green Deployment** – Environment switch; dark launch can happen on green before cutover.

-   **Shadow Traffic / Mirroring** – Send prod traffic to new path invisibly to compare results/perf.

-   **A/B Testing** – Experimental evaluation once the feature becomes visible.

-   **Strangler Fig** – Gradual replacement of legacy functionality behind routing rules.

-   **Schema Evolution (Expand–Migrate–Contract)** – Enables safe toggling across DB versions.
