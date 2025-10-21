
# Evaluation and Monitoring

## Pattern Name and Classification

Evaluation and Monitoring — quality/governance pattern for agentic systems; measures performance continuously with offline tests and online telemetry to detect regressions, drift, cost overruns, and safety violations.

## Intent

Make quality visible and controllable by defining metrics, tests, and runtime monitors so you can catch problems early, compare alternatives, and ship changes safely.

## Also Known As

Quality Gates; Observability; Guarded Deployment; Canary/Shadow Testing; Continuous Evaluation (CEval); Post-Deployment Monitoring.

## Motivation (Forces)

-   Stochastic models drift and regress silently.

-   Prompt, policy, and tool changes ripple through systems in surprising ways.

-   Offline evals miss real traffic; online metrics without ground truth miss correctness.

-   Budgets and SLAs (latency, cost, tokens) matter as much as accuracy.  
    Evaluation and Monitoring ties together offline truth-based checks and online telemetry to keep systems trustworthy.


## Applicability

Use when:

-   You deploy changes to prompts, policies, tools, or models.

-   You need to compare variants (A/B, bandits) or gate releases.

-   Failures are costly and require quick detection and rollback.

-   Data distributions shift (seasonality, new products, regions).


## Structure

1.  **Metric Definitions**: task quality, coverage, faithfulness, citation accuracy, cost, tokens, latency, safety.

2.  **Offline Suite**: golden sets, rubrics, unit tests, adversarial sets.

3.  **Online Monitors**: SLAs/SLOs, anomaly detection, drift detectors, error budgets.

4.  **Deployment Controls**: canary, shadow, rollback, feature flags.

5.  **Telemetry Pipeline**: tracing, logs, counters, histograms, exemplars.

6.  **Dashboards & Alerts**: queries and thresholds wired to paging.

7.  **Feedback Loop**: issues feed into prompts/policies/tools for fixes.


## Participants

-   **Evaluator**: computes quality metrics offline/online.

-   **Monitor/Watcher**: tracks SLAs and raises alerts.

-   **Telemetry Collector**: emits structured traces and metrics.

-   **Variant Manager**: flags, canaries, experiment buckets.

-   **Owner/Oncall**: receives alerts, decides rollback.

-   **Data Store**: holds golden sets, logs, and metric time series.


## Collaboration

Change proposed → run offline suite → if pass, ship to shadow or canary → online monitors watch quality, safety, latency, and cost → if healthy, ramp to 100%; if not, alert and roll back → logs and samples are reviewed; prompts/policies/tools are updated and re-evaluated.

## Consequences

**Benefits**

-   Early detection of regressions and drift.

-   Safer releases with evidence-based promotion.

-   Clear tradeoff visibility among quality, cost, and latency.

-   Reusable golden sets accelerate iteration.


**Liabilities**

-   Building and curating test sets takes time.

-   Some tasks lack crisp ground truth; scoring can be noisy.

-   Extra infra cost for telemetry and alerting.

-   Over-alerting can cause fatigue; thresholds need tuning.


## Implementation (Key Points)

-   Define **task-specific metrics**: exact-match/F1 for QA, rubric scores for writing, pass rate for validators/tests, faithfulness/citation accuracy for RAG.

-   Track **operational metrics**: p50/p95 latency, error rate, tokens, cost per request, tool-call failure rate.

-   Maintain **golden sets** and **adversarial sets**; refresh regularly to avoid overfitting.

-   Use **shadow traffic** for no-risk comparison; promote via **canary** with guardrails.

-   Instrument with **structured traces**: request id, variant, inputs, chosen tools, outcomes, scores.

-   Add **drift checks**: input distribution stats, embedding centroid drift, win-rate shifts.

-   Alert on **SLO violations** and **quality deltas** vs control; include auto-rollback hooks.

-   Keep **evaluation code versioned** with prompts/policies; store results with artifact hashes.

-   Sample **human ratings** for gray areas; calibrate rubric scorers with inter-rater agreement.

-   Close the loop: failed tests create issues; fixes must add new test cases.


## Sample Code (Java)

```java
import java.time.Duration;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ThreadLocalRandom;

/** --------- Telemetry primitives --------- */
class Span implements AutoCloseable {
    final String id = UUID.randomUUID().toString();
    final String name;
    final Instant start = Instant.now();
    final Map<String, Object> attrs = new LinkedHashMap<>();
    Span(String name) { this.name = name; }
    public Span attr(String k, Object v) { attrs.put(k, v); return this; }
    @Override public void close() {
        long ms = Duration.between(start, Instant.now()).toMillis();
        System.out.println("SPAN " + name + " id=" + id + " ms=" + ms + " attrs=" + attrs);
    }
}

class Metrics {
    double costUsd = 0;
    long tokens = 0;
    long latencyMs = 0;
    boolean safetyViolation = false;
    Map<String, Double> quality = new LinkedHashMap<>();
}

/** --------- Offline evaluation suite --------- */
class Example {
    final String input;
    final String expected;   // ground truth if available
    Example(String input, String expected) { this.input = input; this.expected = expected; }
}

interface Evaluator {
    /** Returns a 0..1 score for the given (prediction, example). */
    double score(String prediction, Example ex);
}

class ExactMatchEvaluator implements Evaluator {
    public double score(String prediction, Example ex) {
        return prediction.trim().equalsIgnoreCase(ex.expected.trim()) ? 1.0 : 0.0;
    }
}

class RubricEvaluator implements Evaluator {
    public double score(String prediction, Example ex) {
        // Toy rubric: reward length and presence of keywords
        int len = prediction.length();
        double keyword = prediction.toLowerCase().contains("because") ? 0.2 : 0.0;
        return Math.min(1.0, (len > 40 ? 0.6 : 0.4) + keyword);
    }
}

class OfflineSuite {
    final List<Example> golden;
    final Evaluator evaluator;
    OfflineSuite(List<Example> golden, Evaluator evaluator) { this.golden = golden; this.evaluator = evaluator; }

    double run(Variant v) {
        double sum = 0;
        try (Span span = new Span("offline_evaluation").attr("variant", v.name)) {
            for (Example ex : golden) {
                String pred = v.answer(ex.input);
                double s = evaluator.score(pred, ex);
                sum += s;
            }
        }
        return sum / Math.max(1, golden.size());
    }
}

/** --------- Variant under test --------- */
interface Variant {
    String name = "base";
    String answer(String input);
}

class CheapVariant implements Variant {
    public String name = "cheap";
    public String answer(String input) {
        // Simulate a faster, cheaper but weaker model
        return "Answer: " + input.split("\\.")[0];
    }
}

class StrongVariant implements Variant {
    public String name = "strong";
    public String answer(String input) {
        // Simulate a slower, costlier but stronger model
        return "Because the main driver was demand growth, the result is 42.";
    }
}

/** --------- Online monitors & canary --------- */
class OnlineMonitor {
    final double maxCostUsd;
    final long p95LatencyMs;
    final double minQuality; // rolling average vs golden/rubric

    double rollingQuality = 1.0;
    final Deque<Double> window = new ArrayDeque<>();
    final int windowSize = 50;

    OnlineMonitor(double maxCostUsd, long p95LatencyMs, double minQuality) {
        this.maxCostUsd = maxCostUsd; this.p95LatencyMs = p95LatencyMs; this.minQuality = minQuality;
    }

    void observe(Metrics m, double qualityScore) {
        rollingQuality = updateRolling(qualityScore);
        if (m.costUsd > maxCostUsd) alert("cost_budget_exceeded", m);
        if (m.latencyMs > p95LatencyMs) alert("latency_exceeded", m);
        if (rollingQuality < minQuality) alert("quality_drop", m);
        if (m.safetyViolation) alert("safety_violation", m);
    }

    private double updateRolling(double s) {
        window.addLast(s);
        if (window.size() > windowSize) window.removeFirst();
        return window.stream().mapToDouble(x -> x).average().orElse(1.0);
    }

    private void alert(String type, Metrics m) {
        System.err.println("ALERT type=" + type + " p95=" + p95LatencyMs
                + " rollQ=" + String.format(Locale.US, "%.2f", rollingQuality)
                + " cost=" + m.costUsd + " tokens=" + m.tokens + " latency=" + m.latencyMs);
    }
}

class CanaryDeployer {
    final Variant control;
    final Variant candidate;
    final OnlineMonitor monitor;
    double trafficSplit = 0.1; // 10% to candidate

    CanaryDeployer(Variant control, Variant candidate, OnlineMonitor monitor) {
        this.control = control; this.candidate = candidate; this.monitor = monitor;
    }

    String routeAndRecord(String input) {
        boolean toCandidate = ThreadLocalRandom.current().nextDouble() < trafficSplit;
        Variant v = toCandidate ? candidate : control;

        Metrics m = new Metrics();
        try (Span span = new Span("inference").attr("variant", v instanceof StrongVariant ? "strong" : "cheap")) {
            long t0 = System.currentTimeMillis();
            String out = v.answer(input);
            m.latencyMs = System.currentTimeMillis() - t0;
            m.costUsd = v instanceof StrongVariant ? 0.02 : 0.004;
            m.tokens = v instanceof StrongVariant ? 2200 : 600;
            m.quality.put("rubric", new RubricEvaluator().score(out, new Example(input, "")));
            monitor.observe(m, m.quality.get("rubric"));
            return out;
        }
    }

    void promoteIfHealthy() {
        if (monitor.rollingQuality >= monitor.minQuality) {
            trafficSplit = Math.min(1.0, trafficSplit + 0.2);
            System.out.println("PROMOTE candidate to split=" + trafficSplit);
        } else {
            trafficSplit = Math.max(0.0, trafficSplit - 0.2);
            System.out.println("DEMOTE candidate to split=" + trafficSplit);
        }
    }
}

/** --------- Demo --------- */
public class EvaluationAndMonitoringDemo {
    public static void main(String[] args) {
        // 1) Offline evaluation
        List<Example> golden = List.of(
                new Example("What caused growth?", "demand growth"),
                new Example("Compute final result.", "42")
        );
        OfflineSuite offlineCheap = new OfflineSuite(golden, new ExactMatchEvaluator());
        OfflineSuite offlineStrong = new OfflineSuite(golden, new ExactMatchEvaluator());

        double cheapScore = offlineCheap.run(new CheapVariant());
        double strongScore = offlineStrong.run(new StrongVariant());
        System.out.println(String.format(Locale.US, "Offline: cheap=%.2f strong=%.2f", cheapScore, strongScore));

        // Gate: require at least parity before canary
        if (strongScore < cheapScore) {
            System.out.println("Abort deploy: candidate worse than control offline.");
            return;
        }

        // 2) Online canary with monitors
        OnlineMonitor monitor = new OnlineMonitor(
                0.03,   // max cost per request
                800,    // p95 target
                0.65    // min rolling quality
        );
        CanaryDeployer canary = new CanaryDeployer(new CheapVariant(), new StrongVariant(), monitor);

        for (int i = 0; i < 20; i++) {
            String input = i % 2 == 0 ? "What caused growth?" : "Compute final result.";
            String out = canary.routeAndRecord(input);
            System.out.println("OUT: " + out);
            if ((i+1) % 5 == 0) canary.promoteIfHealthy();
        }
    }
}
```

## Known Uses

-   Pre-merge and pre-release gates for prompts, tools, or models using golden/adversarial sets.

-   Canary and shadow deployments with automatic rollback on SLO or quality violations.

-   Continuous evaluation of RAG faithfulness and citation accuracy on sampled traffic.

-   Post-deployment monitoring of token/cost budgets, tool-call failures, and safety events.

-   Weekly scorecards tracking win rate vs control and drift in input distribution.


## Related Patterns

-   **Guardrails/Safety Patterns:** safety checks and policy violations feed alerts and block promotion.

-   **Goal Setting and Monitoring:** SLOs and KRs define thresholds and dashboards.

-   **Learning and Adaptation:** online metrics become rewards for bandits/RL or policy tuning.

-   **Routing:** monitors compare routed paths and inform policy thresholds.

-   **Resource-Aware Optimization:** watch cost and latency to adjust tactics.

-   **Reflection:** evaluator feedback drives targeted revisions.

-   **Planning:** milestones serve as evaluation checkpoints before advancing.
