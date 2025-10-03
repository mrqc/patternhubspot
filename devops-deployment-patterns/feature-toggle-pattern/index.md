# Feature Toggle Pattern — DevOps Deployment Pattern

## Pattern Name and Classification

-   **Name:** Feature Toggle (Feature Flag)

-   **Category:** DevOps / Release Engineering / Progressive Delivery

-   **Level:** Application + Delivery process pattern (implementation + operational governance)


---

## Intent

Enable switching features **on/off** (or selecting variants) at runtime without redeploying. This **decouples deploy from release**, supports progressive rollout, experimentation, kill-switch safety, and operational control.

---

## Also Known As

-   Feature Flags / Switches

-   Conditional Features

-   Runtime Configuration Gates

-   Release Toggles / Experiment Toggles / Ops Toggles (toggle taxonomy)


---

## Motivation (Forces)

-   **Separate deployment from exposure:** Ship code continuously; reveal when ready.

-   **Risk reduction:** Flip off (kill switch) on incidents instead of hotfixing.

-   **Progressive rollout:** Gradual exposure by %/cohort/geo/device.

-   **Experimentation:** A/B tests and multivariate experiments.

-   **Entitlement & plans:** Enable features per customer/plan/region.


**Forces / Trade-offs**

-   Toggle sprawl ⇒ tech debt if not lifecycle-managed.

-   Higher **testing matrix** (combinations of flags).

-   Need **fast, consistent** evaluation (server, edge, client).

-   Requires **auditability**, RBAC, and observability per flag.


---

## Applicability

Use when:

-   You need **dark launches**, **canary releases**, or staged rollouts.

-   Compliance/marketing timing dictates **release control** separate from deploy.

-   You run **experiments** or **beta programs**.

-   You need **tenant/plan**\-based entitlements.


Avoid or limit when:

-   Change is **schema-incompatible** and cannot be safely guarded.

-   The organization cannot commit to **toggle lifecycle** (expiry/cleanup).

-   Security/privacy constraints forbid client-side gating for sensitive logic.


---

## Structure

-   **Flag Definition:** name, owner, type (boolean, multivariant), expiry, description.

-   **Evaluation Engine:** deterministic bucketing/cohorting.

-   **Distribution/Config:** centralized store (self-hosted or SaaS).

-   **Instrumentation:** metrics/logs/traces tagged with `feature=<name> variant=<v>`.

-   **Governance:** RBAC, audit logs, flag TTL policy, cleanup workflow.


```less
[Flag Store / Control Plane]
            │ pull/push
            ▼
     [SDK / Evaluator] ──(context: user, tenant, env)──▶ decision
            │
            ├─ true  → [New Path / Variant B]
            └─ false → [Fallback / Variant A]
```

---

## Participants

-   **Product/Feature Owner:** owns purpose, success criteria, expiry date.

-   **Engineering Team:** implements guarded code paths and tests.

-   **Release/SRE:** operates rollout, guardrails, rollback.

-   **Flag Service:** control plane + SDKs (Unleash, LaunchDarkly, Togglz, etc.).

-   **Analytics/Observability:** collects feature-scoped telemetry.

-   **Security/Compliance:** reviews governance and access.


---

## Collaboration

-   **Dark Launch / Canary Release:** flags govern exposure steps.

-   **Blue/Green:** use flags for final switch or partial routing.

-   **Shadow Traffic:** compare results behind a flag before exposure.

-   **Circuit Breakers/Rate Limits:** guard flagged paths.

-   **Schema Evolution (Expand-Migrate-Contract):** enables safe toggling across versions.


---

## Consequences

**Benefits**

-   Rapid rollback, safer experiments, business-driven releases.

-   Enables continuous delivery with **reduced blast radius**.

-   Fine-grained **tenant/plan** control.


**Liabilities**

-   **Flag debt:** lingering dead code; readability erosion.

-   **Observability needs:** per-flag metrics to detect small regressions.

-   **Complexity in testing:** need strategy for combinations.

-   **Consistency concerns:** client vs server evaluation drift.


Mitigations:

-   Enforce **flag TTL and owners**; auto-reminders.

-   **Contract tests** for both paths; synthetic checks.

-   Store decisions in logs for **auditability**.


---

## Implementation

1.  **Define Flag Taxonomy & Lifecycle**

    -   Types: **Release**, **Experiment**, **Ops**, **Permissioning**.

    -   Each flag has: owner, description, expiry, environments, rollout rules.

2.  **Choose a Flag Platform**

    -   Self-hosted (Unleash, OpenFeature + provider, Togglz) or SaaS.

    -   Requirements: low-latency eval, offline cache, SDK for your stack, RBAC, audit.

3.  **Guard Code Paths**

    -   Keep **fallback path** correct and performant.

    -   Keep flag checks **near decision boundaries** (avoid scattering).

4.  **Deterministic Cohorting**

    -   Use stable identifiers: `hash(userId|tenantId) % 100 < rollout%`.

    -   Support allow/deny lists for staff/early adopters.

5.  **Observability**

    -   Tag logs/metrics/traces with `feature`, `variant`, `cohort`.

    -   Establish **SLO guardrails** and auto-rollback policies.

6.  **Progressive Rollout Playbook**

    -   0% → 0.5% → 1% → 5% → 10% → 25% → 50% → 100%, evaluating KPIs at each step.

7.  **Security & Governance**

    -   RBAC for flag changes; approvals for high-risk flags; audit logs.

8.  **Cleanup**

    -   When feature reaches 100% (or is abandoned), **remove flag & dead code** promptly.


---

## Sample Code (Java, Spring Boot)

*(minimal example; replace the in-memory store with Unleash/Togglz/OpenFeature/LaunchDarkly in production)*

```java
// Feature metadata
public record FeatureRule(
        String name,
        boolean enabled,
        int rolloutPercent,     // 0..100
        String owner,
        String expiresOn        // ISO date for governance (optional)
) {}
```

```java
// Simple flag service (thread-safe); swap with real provider
import java.util.concurrent.ConcurrentHashMap;
import java.util.Map;

public class FlagService {
    private final Map<String, FeatureRule> rules = new ConcurrentHashMap<>();

    public void upsert(FeatureRule rule) {
        rules.put(rule.name(), normalize(rule));
    }

    public FeatureRule get(String name) {
        return rules.getOrDefault(name, new FeatureRule(name, false, 0, "unknown", null));
    }

    public boolean isEnabledFor(String name, String stableId) {
        FeatureRule r = get(name);
        if (!r.enabled()) return false;
        int bucket = Math.floorMod(stableId.hashCode(), 100);
        return bucket < r.rolloutPercent();
    }

    private FeatureRule normalize(FeatureRule r) {
        int p = Math.max(0, Math.min(100, r.rolloutPercent()));
        return new FeatureRule(r.name(), r.enabled(), p, r.owner(), r.expiresOn());
    }
}
```

```java
// Cohort helper
public final class Cohort {
    private Cohort() {}
    public static String stableId(String userId, String tenantId, String sessionId) {
        if (userId != null && !userId.isBlank()) return "u:" + userId;
        if (tenantId != null && !tenantId.isBlank()) return "t:" + tenantId;
        if (sessionId != null && !sessionId.isBlank()) return "s:" + sessionId;
        return "anon";
    }
}
```

```java
// Spring configuration
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class FlagsConfig {
    @Bean
    public FlagService flagService() {
        FlagService svc = new FlagService();
        svc.upsert(new FeatureRule("checkout.v2", true, 0, "payments-team", "2025-12-31")); // dark by default
        return svc;
    }
}
```

```java
// Business services (fallback and new path)
import java.util.Map;

public interface Checkout {
    Map<String, Object> run(String user);
}

@org.springframework.stereotype.Service
class CheckoutV1 implements Checkout {
    public Map<String, Object> run(String user) {
        return Map.of("variant", "v1", "status", "OK", "total", 100);
    }
}

@org.springframework.stereotype.Service
class CheckoutV2 implements Checkout {
    public Map<String, Object> run(String user) {
        // New logic; potentially more expensive or external deps
        return Map.of("variant", "v2", "status", "OK", "total", 95, "discount", true);
    }
}
```

```java
// Controller with feature toggle & telemetry
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.bind.annotation.*;
import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;

@RestController
@RequestMapping("/api/checkout")
public class CheckoutController {
    private static final Logger log = LoggerFactory.getLogger(CheckoutController.class);

    private final FlagService flags;
    private final CheckoutV1 v1;
    private final CheckoutV2 v2;

    public CheckoutController(FlagService flags, CheckoutV1 v1, CheckoutV2 v2) {
        this.flags = flags; this.v1 = v1; this.v2 = v2;
    }

    @GetMapping
    public Map<String, Object> checkout(@RequestHeader(value = "X-User-Id", required = false) String userId,
                                        @RequestHeader(value = "X-Tenant-Id", required = false) String tenantId,
                                        @CookieValue(value = "SESSION", required = false) String sessionId,
                                        HttpServletRequest req) {

        String stableId = Cohort.stableId(userId, tenantId, sessionId);
        boolean v2on = flags.isEnabledFor("checkout.v2", stableId);

        long t0 = System.nanoTime();
        try {
            Map<String, Object> result = v2on ? v2.run(stableId) : v1.run(stableId);
            log.info("feature=checkout.v2 variant={} user={} httpClient={} status={}",
                     v2on ? "v2" : "v1", stableId, req.getHeader("User-Agent"), result.get("status"));
            return result;
        } catch (Exception e) {
            if (v2on) {
                log.warn("feature=checkout.v2 error='{}' fallback=v1", e.toString());
                return v1.run(stableId);
            }
            throw e;
        } finally {
            long durMs = (System.nanoTime() - t0) / 1_000_000;
            log.info("metric=latency_ms feature=checkout.v2 variant={} value={}", v2on ? "v2" : "v1", durMs);
        }
    }
}
```

```java
// Minimal ops endpoint to change rollout (secure with RBAC in real systems)
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/ops/flags")
class FlagOpsController {
    private final FlagService flags;
    FlagOpsController(FlagService flags) { this.flags = flags; }

    @PostMapping("/{name}")
    public String set(@PathVariable String name,
                      @RequestParam boolean enabled,
                      @RequestParam int percent,
                      @RequestParam(defaultValue = "unknown") String owner,
                      @RequestParam(required = false) String expiresOn) {
        flags.upsert(new FeatureRule(name, enabled, percent, owner, expiresOn));
        return "ok";
    }
}
```

**Production Notes**

-   Replace the sample `FlagService` with **OpenFeature** (standardized API) + provider, or platforms like **Unleash**, **LaunchDarkly**, **Togglz**.

-   Add **Micrometer** metrics and **OpenTelemetry** traces with attributes `feature` and `variant`.

-   Secure `/ops/flags/**` with RBAC and keep **audit logs**.

-   Implement **flag TTLs**: if `expiresOn` passed, alert on/after that date to remove the flag and dead code.


---

## Known Uses

-   **Large web platforms** (Google, Facebook, Netflix) for ranking/UX changes and operational safety switches.

-   **SaaS products** for **plan/tenant entitlements** and private betas.

-   **Mobile apps** to remotely disable unstable flows without an app store redeploy.

-   **Payments/checkout systems** to progressively enable risk-sensitive logic.


---

## Related Patterns

-   **Dark Launch** — run in prod with no/limited visibility, flip on gradually (often implemented by flags).

-   **Canary Release** — percentage-based rollout with auto rollback.

-   **Blue/Green Deployment** — environment switch; flags give finer granularity post-cutover.

-   **A/B Testing** — experiments controlled via multivariate flags.

-   **Circuit Breaker** — operational kill switch for dependencies.

-   **Schema Evolution (Expand–Migrate–Contract)** — enables safe toggling across versions.

-   **Strangler Fig** — route gradually to a new implementation using flags/routers.
