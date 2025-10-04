# A/B Testing — Testing Pattern

## Pattern Name and Classification

-   **Name:** A/B Testing
    
-   **Classification:** Experimentation / Controlled Online Experiment / Statistical Testing Pattern
    

## Intent

Validate product or system changes by **randomly assigning** traffic (or users) to variants (A = control, B = treatment(s)), **measuring causal impact** on predefined metrics, and making a **data-informed ship/rollback decision** with quantified uncertainty.

## Also Known As

-   Split Testing
    
-   Online Controlled Experiment (OCE)
    
-   Randomized Controlled Experiment (RCE)
    
-   Bucket Testing
    

## Motivation (Forces)

-   **Uncertainty vs. speed:** we want to move fast without blindly shipping regressions.
    
-   **Causality:** observational metrics are confounded; randomized assignment removes selection bias.
    
-   **Risk management:** limit blast radius and use **guardrail metrics** (latency, errors) to catch harm.
    
-   **Multiple goals:** balance primary success metric (e.g., conversion) with secondary/guardrail metrics.
    
-   **Ethics & privacy:** experimentation should respect user consent, data minimization, and regulations.
    

## Applicability

Use A/B testing when:

-   You can **randomize** at a unit (user, session, tenant, request) and **isolate** the treatment.
    
-   Outcomes can be measured in a **reasonable time** (minutes → weeks).
    
-   The expected effect size is not tiny relative to noise (or you can afford sufficient sample size).
    

Avoid or adapt when:

-   Network effects or interference across units violate independence (consider cluster randomization).
    
-   You need **instantaneous correctness** (security patches, critical bugfixes → use canary/feature flag with monitors).
    
-   The change is not measurable (no reliable metrics) or ethically unsuitable for randomization.
    

## Structure

-   **Experiment Definition:** name, hypothesis, unit of assignment, variants, traffic splits, duration, metrics, success criteria.
    
-   **Randomization & Assignment:** deterministic bucketing (hash-based) for **sticky** assignment.
    
-   **Exposure Logging:** record each exposure (experiment, variant, unit, timestamp).
    
-   **Event Collection:** telemetry for outcomes and guardrails.
    
-   **Metrics & Stats Engine:** aggregates by variant; hypothesis testing (p-values) or Bayesian posteriors; **SRM** checks.
    
-   **Decision & Rollout:** automate ship/rollback, optionally ramp traffic gradually.
    

```css
Client → Assignment → (A or B)
   ↓         │
Exposure ----┘
   ↓
Events/Outcomes ──► Metrics & Statistical Analysis ──► Decision (Ship/Rollback/Rerun)
```

## Participants

-   **Experiment Owner / Product** — defines hypothesis, metrics, success criteria.
    
-   **Experiment Service** — performs assignment and logs exposures.
    
-   **Telemetry Pipeline** — collects outcome events.
    
-   **Metrics/Stats Service** — computes aggregates and significance/intervals; monitors SRM & guardrails.
    
-   **Release/Feature-Flag System** — gates rollout based on decision rules.
    
-   **Data Scientist/Analyst** — validates design, power, and interpretation.
    

## Collaboration

1.  Owner registers **experiment config** (variants + splits + metrics).
    
2.  Client asks **Assignment** with a stable unit key → gets variant deterministically.
    
3.  Client logs **exposure** and emits outcome events as the user interacts.
    
4.  Metrics service aggregates by variant, runs **statistical tests/intervals** and **guardrail checks** (latency, errors, churn).
    
5.  When criteria are met (power, duration, p-value/credible interval), the system **ships** the winner or **rolls back**.
    

## Consequences

**Benefits**

-   Causal measurement; reduces risk of harmful changes.
    
-   Focus on **business outcomes** vs. proxy metrics.
    
-   Enables **continuous, incremental improvement** and safe exploration.
    

**Liabilities**

-   **Sample size & duration** costs; small effects can take long.
    
-   **Peeking & p-hacking** risk; requires pre-registered stopping rules (or sequential methods).
    
-   **Interference & spillover** can bias results (network effects, shared caches).
    
-   **SRM** (sample ratio mismatch) indicates broken randomization or logging.
    
-   **Ethical considerations**: user impact, fairness, and privacy.
    

## Implementation

### Design Guidelines

-   **Unit of randomization:** prefer user/tenant for stickiness; use cluster randomization if interference exists.
    
-   **Deterministic hashing:** stable assignment across sessions/devices (include a salt/seed).
    
-   **Mutual exclusion:** incompatible experiments should not collide; use namespaces or exclusivity groups.
    
-   **Exposure semantics:** log **first eligible exposure** only; de-duplicate.
    
-   **Metrics:** define primary, secondary, and **guardrails** (errors, latency, revenue neutrality).
    
-   **Power analysis:** estimate sample size/stop time before launch; avoid underpowered tests.
    
-   **Stopping rules:** fixed horizon or sequential rules (e.g., SPRT, group sequential, Bayesian).
    
-   **SRM monitor:** chi-square test to detect allocation mismatch early.
    
-   **Ramp strategy:** 1% → 5% → 25% → 50% → 100% with guardrail checks between ramps.
    
-   **Privacy:** minimize PII; hash unit IDs; document purpose and retention.
    

### Operational Checklist

-   Feature flag integrated with assignment service.
    
-   Idempotent logging; at-least-once ingestion; late event handling.
    
-   Timezone/seasonality controls (start/stop times, stratification).
    
-   Predefine fail-safe rollback conditions.
    
-   Post-experiment analysis doc (effect sizes, intervals, learnings).
    

---

## Sample Code (Java 17)

Minimal, framework-free utilities for **deterministic assignment**, **exposure logging**, and a simple **z-test for proportions** (for post-hoc analysis). This is educational; production systems add persistence, SRM checks, ramping, and mutual exclusion.

```java
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/** Experiment configuration */
final class Experiment {
  final String name;
  final String seed; // salt for hashing to avoid cross-experiment correlation
  // allocations in basis points (sum = 10_000). Example: A=5000, B=5000
  final LinkedHashMap<String, Integer> allocations;
  final Instant startsAt;
  final Instant endsAt;

  Experiment(String name, String seed, Map<String,Integer> allocations, Instant startsAt, Instant endsAt) {
    this.name = name;
    this.seed = seed;
    this.allocations = new LinkedHashMap<>(allocations);
    int sum = this.allocations.values().stream().mapToInt(Integer::intValue).sum();
    if (sum != 10_000) throw new IllegalArgumentException("allocations must sum to 10000 (basis points)");
    this.startsAt = startsAt;
    this.endsAt = endsAt;
  }

  boolean activeNow() {
    Instant now = Instant.now();
    return (startsAt == null || !now.isBefore(startsAt)) && (endsAt == null || !now.isAfter(endsAt));
  }
}

/** Deterministic assignment using MD5 hash → bucket [0, 9999] */
final class Assigner {
  static int bucket(String seed, String unitId) {
    try {
      MessageDigest md = MessageDigest.getInstance("MD5");
      byte[] d = md.digest((seed + ":" + unitId).getBytes(StandardCharsets.UTF_8));
      // take first 4 bytes as unsigned int
      int v = ((d[0] & 0xff) << 24) | ((d[1] & 0xff) << 16) | ((d[2] & 0xff) << 8) | (d[3] & 0xff);
      long u = v & 0xffffffffL;
      return (int) (u % 10_000L);
    } catch (Exception e) {
      throw new RuntimeException(e);
    }
  }

  static String assign(Experiment exp, String unitId) {
    if (!exp.activeNow()) return "OFF";
    int b = bucket(exp.seed, unitId);
    int acc = 0;
    for (var e : exp.allocations.entrySet()) {
      acc += e.getValue();
      if (b < acc) return e.getKey();
    }
    // should never happen if allocations sum to 10000
    return exp.allocations.keySet().iterator().next();
  }
}

/** Exposure logging (console demo; replace with a real telemetry sink) */
record Exposure(String experiment, String variant, String unitId, Instant at, Map<String,String> attrs) {}
interface ExposureLogger { void log(Exposure e); }
final class ConsoleExposureLogger implements ExposureLogger {
  public void log(Exposure e) { System.out.println("[Exposure] " + e); }
}

/** Simple stats: two-proportion z-test (conversion rates) */
final class Stats {
  static record ZTestResult(double z, double p) {}
  // H0: pA == pB, Ha: pA != pB (two-sided). Returns z and p-value (approx, normal).
  static ZTestResult twoProportionZ(long succA, long nA, long succB, long nB) {
    if (nA <= 0 || nB <= 0) throw new IllegalArgumentException("nA,nB > 0");
    double pA = (double) succA / nA;
    double pB = (double) succB / nB;
    double pPool = (double) (succA + succB) / (nA + nB);
    double se = Math.sqrt(pPool * (1 - pPool) * (1.0 / nA + 1.0 / nB));
    if (se == 0) return new ZTestResult(0, 1);
    double z = (pA - pB) / se;
    double p = 2 * (1 - cdfStandardNormal(Math.abs(z)));
    return new ZTestResult(z, p);
  }
  // Standard normal CDF (Abramowitz & Stegun approximation)
  private static double cdfStandardNormal(double x) {
    double t = 1 / (1 + 0.2316419 * x);
    double d = Math.exp(-x * x / 2) / Math.sqrt(2 * Math.PI);
    double prob = 1 - d * (0.319381530 * t - 0.356563782 * Math.pow(t,2) + 1.781477937 * Math.pow(t,3)
                           - 1.821255978 * Math.pow(t,4) + 1.330274429 * Math.pow(t,5));
    return prob;
  }
}

/** In-memory counter demo to simulate conversions */
final class Counter {
  private final Map<String, long[]> byVariant = new ConcurrentHashMap<>(); // [conversions, exposures]
  void exposed(String variant) { byVariant.computeIfAbsent(variant, k -> new long[2])[1]++; }
  void converted(String variant) { byVariant.computeIfAbsent(variant, k -> new long[2])[0]++; }
  long exposures(String v){ return byVariant.getOrDefault(v, new long[]{0,0})[1]; }
  long conversions(String v){ return byVariant.getOrDefault(v, new long[]{0,0})[0]; }
}

/** Demo usage */
public class ABTestingDemo {
  public static void main(String[] args) {
    Experiment exp = new Experiment(
        "PriceBadgeExperiment",
        "seed-v1",
        Map.of("A", 5000, "B", 5000), // 50/50 split
        Instant.now().minusSeconds(60),
        null
    );
    ExposureLogger logger = new ConsoleExposureLogger();
    Counter counter = new Counter();

    // Simulate traffic
    Random rnd = new Random(42);
    for (int i = 0; i < 20_000; i++) {
      String userId = "user-" + i;
      String variant = Assigner.assign(exp, userId);
      if (!variant.equals("OFF")) {
        logger.log(new Exposure(exp.name, variant, userId, Instant.now(), Map.of("country","AT")));
        counter.exposed(variant);
        // Simulated conversion: B is slightly better
        double p = variant.equals("A") ? 0.050 : 0.055;
        if (rnd.nextDouble() < p) counter.converted(variant);
      }
    }

    long nA = counter.exposures("A"), nB = counter.exposures("B");
    long cA = counter.conversions("A"), cB = counter.conversions("B");
    var res = Stats.twoProportionZ(cA, nA, cB, nB);

    System.out.printf(Locale.ROOT,
        "A: %d/%d (%.3f%%)  B: %d/%d (%.3f%%)  z=%.3f  p=%.4f%n",
        cA, nA, 100.0 * cA / nA, cB, nB, 100.0 * cB / nB, res.z(), res.p());

    // Extremely naive decision rule (for demo): p < 0.05
    if (res.p() < 0.05) {
      System.out.println("Decision: Ship winner = " + (cB * nA > cA * nB ? "B" : "A"));
    } else {
      System.out.println("Decision: No significant difference yet.");
    }
  }
}
```

**What the code shows**

-   Deterministic, **sticky** assignment via salted hashing.
    
-   **Exposure logging** and simple in-memory counting.
    
-   A **two-proportion z-test** to compare conversion rates for A vs. B (demo only).
    
-   Clear place to integrate SRM checks, ramping, and guardrails.
    

## Known Uses

-   Web and mobile product teams across major tech companies run thousands of concurrent A/B tests (UI, ranking, pricing, performance).
    
-   Backend systems: rollout of recommendation models, caching strategies, throttling rules.
    
-   Growth & marketing: email subject lines, onboarding flows, paywalls.
    
-   Infra changes: new JVM flags, GC settings, or DB drivers gated and measured via experiments.
    

## Related Patterns

-   **Feature Flags / Toggles** — runtime gating; often the *mechanism* to run experiments.
    
-   **Canary Release / Progressive Delivery** — traffic ramping with health metrics (not necessarily randomized).
    
-   **Multivariate Testing (MVT)** — multiple factors/levels; combinatorial experiments.
    
-   **Bandit Algorithms** — adaptive allocation instead of fixed splits.
    
-   **Cohort/Segment Experimentation** — stratified or targeted experiments.
    
-   **Blue–Green / Dark Launch** — deployment patterns that pair well with guardrail monitoring.
    

---

## Implementation Tips

-   Pre-register **hypothesis, metrics, and stopping rules** to avoid p-hacking.
    
-   Run **SRM** checks continuously; abort on mismatch.
    
-   Prefer **sequential analysis** (e.g., SPRT or Bayesian) if you need frequent looks.
    
-   Guard against **novelty/day-of-week** effects; run through full business cycles.
    
-   Document **ethics & privacy**: data purpose, retention, and opt-out mechanisms.
    
-   Build a **self-serve platform** with templates, power calculators, and automated reports to scale experimentation safely.

