
# Resource-Aware Optimization

## Pattern Name and Classification

Resource-Aware Optimization — performance/cost governance pattern for agentic systems; dynamically shapes plans, model choices, tool usage, and parallelism to respect budgets (tokens, cost, latency, rate limits) while maintaining quality.

## Intent

Continuously optimize decisions (which steps to run, with which models/tools, how much context, how much parallelism) to maximize task quality under explicit resource constraints.

## Also Known As

Budget-Aware Execution; Cost- and Latency-Aware Orchestration; SLA-Constrained Planning; Adaptive Quality Control.

## Motivation (Forces)

-   Token windows, rate limits, and dollar budgets are finite.

-   Tasks have variable difficulty; not every request deserves the “largest model + everything.”

-   Quality, cost, and latency trade off. Parallelism reduces tail latency but increases spend.

-   Real systems must degrade gracefully: fast path for easy items, stronger path when justified, never exceed caps.


## Applicability

Use when:

-   You must meet SLAs (p95 latency, cost ceilings, token caps, API quotas).

-   Multiple interchangeable tactics exist (small vs large model, retrieval vs open-book, single vs multi-pass).

-   Workloads are heterogeneous in difficulty and value.

-   You need predictable spend with best-effort quality improvement.


## Structure

1.  **Budgets & SLAs**: per-request and rolling caps (cost, tokens, time, concurrency).

2.  **Policy Engine**: maps context, risk, and value to target quality level and ceilings.

3.  **Options Catalog**: candidate tactics with estimated cost/latency/quality.

4.  **Optimizer**: selects or schedules options to maximize expected utility under constraints.

5.  **Executor**: runs chosen options, tracks actuals, and cancels stragglers.

6.  **Telemetry**: measures drift between estimates and actuals; feeds learning.

7.  **Degradation Paths**: fallbacks when budgets or SLAs are threatened.


## Participants

-   **Budget Manager**: tracks spend and time; exposes “canSpend?” decisions.

-   **Rate Limiter**: enforces quotas and backoff.

-   **Optimizer**: chooses models/tools/parallelism based on utility per unit cost.

-   **Executor**: applies timeouts, hedging, and early-exit rules.

-   **Evaluator**: scores outputs to inform future estimates.

-   **Policy/Config Store**: versioned thresholds and target SLAs.


## Collaboration

Input arrives → Policy sets ceilings and target quality → Optimizer scores candidate tactics → Budget Manager authorizes a plan → Executor runs with timeouts and early stop → Telemetry records actual cost/latency/quality → Evaluator updates estimates and policy nudges for next runs.

## Consequences

**Benefits**

-   Predictable spend and latency with competitive quality.

-   Graceful degradation instead of failure or runaway costs.

-   Clear levers to tune tradeoffs by segment, user, or task.


**Liabilities**

-   Requires good estimates and ongoing calibration.

-   Added complexity in planning and observability.

-   Risk of under-serving high-value tasks if policy is too conservative.


## Implementation (Key Points)

-   Define per-request and rolling **budgets** (USD, tokens, milliseconds).

-   Maintain **estimates** per tactic: expected quality, cost, latency; update from telemetry.

-   Use **utility scoring** (e.g., `u = wq*quality − wc*cost − wl*latency`) and pick the best plan under constraints.

-   Support **early-exit**: stop when acceptable quality is reached or SLA is near.

-   Apply **bounded parallelism** and **hedged requests** where variance is high.

-   Enforce **rate limits** and **circuit breakers** per provider.

-   Log planned vs actual; adjust estimates and thresholds automatically.


## Sample Code (Java)

```java
import java.time.Duration;
import java.util.*;
import java.util.concurrent.ThreadLocalRandom;

/** ------- Budgets & SLAs ------- */
class Budget {
    double maxUsd;
    long maxTokens;
    long maxMs;

    double spentUsd = 0;
    long spentTokens = 0;
    long startedAt = System.currentTimeMillis();

    Budget(double maxUsd, long maxTokens, long maxMs) {
        this.maxUsd = maxUsd; this.maxTokens = maxTokens; this.maxMs = maxMs;
    }
    boolean canSpend(double usd, long tokens, long ms) {
        long elapsed = System.currentTimeMillis() - startedAt;
        return spentUsd + usd <= maxUsd &&
               spentTokens + tokens <= maxTokens &&
               elapsed + ms <= maxMs;
    }
    void spend(double usd, long tokens) {
        spentUsd += usd; spentTokens += tokens;
    }
    boolean timeLeft() {
        return System.currentTimeMillis() - startedAt < maxMs;
    }
}

/** ------- Tactics (options the optimizer can choose) ------- */
interface Tactic {
    String name();
    // Estimates; in production these are learned online
    double estQuality();           // 0..1
    double estUsd();
    long estTokens();
    long estMs();
    // Execute and return actual quality plus artifact
    Result run(String input);
}
class Result {
    final String artifact;
    final double quality;
    final double usd;
    final long tokens;
    final long ms;
    Result(String artifact, double quality, double usd, long tokens, long ms) {
        this.artifact = artifact; this.quality = quality; this.usd = usd; this.tokens = tokens; this.ms = ms;
    }
}

/** Example tactics */
class SmallModel implements Tactic {
    public String name(){ return "sm_model"; }
    public double estQuality(){ return 0.70; }
    public double estUsd(){ return 0.004; }
    public long estTokens(){ return 900; }
    public long estMs(){ return 180; }
    public Result run(String input) {
        long ms = 150 + ThreadLocalRandom.current().nextInt(60);
        double q = 0.68 + ThreadLocalRandom.current().nextDouble() * 0.06;
        return new Result("Draft(SM): " + input, q, 0.004, 850, ms);
    }
}
class RAGBoost implements Tactic {
    public String name(){ return "rag_boost"; }
    public double estQuality(){ return 0.80; }
    public double estUsd(){ return 0.006; }
    public long estTokens(){ return 700; }
    public long estMs(){ return 220; }
    public Result run(String input) {
        long ms = 200 + ThreadLocalRandom.current().nextInt(80);
        double q = 0.78 + ThreadLocalRandom.current().nextDouble() * 0.06;
        return new Result("Draft(RAG): " + input, q, 0.006, 700, ms);
    }
}
class LargeModel implements Tactic {
    public String name(){ return "lg_model"; }
    public double estQuality(){ return 0.88; }
    public double estUsd(){ return 0.028; }
    public long estTokens(){ return 2600; }
    public long estMs(){ return 420; }
    public Result run(String input) {
        long ms = 380 + ThreadLocalRandom.current().nextInt(120);
        double q = 0.86 + ThreadLocalRandom.current().nextDouble() * 0.06;
        return new Result("Draft(LG): " + input + " ✔", q, 0.028, 2500, ms);
    }
}
class ReflectPass implements Tactic {
    public String name(){ return "reflect"; }
    public double estQuality(){ return 0.05; } // incremental uplift
    public double estUsd(){ return 0.003; }
    public long estTokens(){ return 500; }
    public long estMs(){ return 120; }
    public Result run(String input) {
        long ms = 100 + ThreadLocalRandom.current().nextInt(60);
        double q = 0.04 + ThreadLocalRandom.current().nextDouble() * 0.03;
        return new Result("Refined: " + input, q, 0.003, 450, ms);
    }
}

/** ------- Optimizer ------- */
class Optimizer {
    // Utility weights (tune per use case)
    private final double wQ, wC, wL;
    private final double targetQuality; // early-exit threshold

    Optimizer(double wQ, double wC, double wL, double targetQuality) {
        this.wQ = wQ; this.wC = wC; this.wL = wL; this.targetQuality = targetQuality;
    }

    /** Greedy selection by utility per (normalized) cost, under budget constraints. */
    List<Tactic> selectPlan(List<Tactic> candidates, Budget b) {
        List<Tactic> plan = new ArrayList<>();
        // Normalize cost components to comparable scales
        double maxUsd = candidates.stream().mapToDouble(Tactic::estUsd).max().orElse(1);
        long maxMs = candidates.stream().mapToLong(Tactic::estMs).max().orElse(1);

        candidates.sort((a, c) -> {
            double ua = wQ * a.estQuality() - wC * (a.estUsd() / maxUsd) - wL * (a.estMs() / (double)maxMs);
            double uc = wQ * c.estQuality() - wC * (c.estUsd() / maxUsd) - wL * (c.estMs() / (double)maxMs);
            return Double.compare(uc, ua);
        });

        double projectedQ = 0.0;
        for (Tactic t : candidates) {
            if (!b.canSpend(t.estUsd(), t.estTokens(), t.estMs())) continue;
            plan.add(t);
            projectedQ = Math.min(1.0, projectedQ + t.estQuality()); // assume additive uplift for demo
            if (projectedQ >= targetQuality) break;
        }
        return plan;
    }
}

/** ------- Orchestrator ------- */
class ResourceAwareOrchestrator {
    private final Optimizer opt;

    ResourceAwareOrchestrator(Optimizer opt) { this.opt = opt; }

    public Result execute(String task, Budget budget, List<Tactic> pool) {
        String artifact = "";
        double quality = 0.0;
        long totalMs = 0;

        for (Tactic t : opt.selectPlan(pool, budget)) {
            if (!budget.canSpend(t.estUsd(), t.estTokens(), t.estMs())) continue;
            Result r = t.run(artifact.isEmpty() ? task : artifact);
            budget.spend(r.usd, r.tokens);
            artifact = r.artifact;
            quality = Math.min(1.0, quality + r.quality);
            totalMs += r.ms;

            // Early exit if quality threshold or time budget nearly hit
            if (quality >= 0.85 || !budget.timeLeft()) break;
        }
        return new Result(artifact, quality, budget.spentUsd, budget.spentTokens, totalMs);
    }
}

/** ------- Demo ------- */
public class ResourceAwareOptimizationDemo {
    public static void main(String[] args) {
        // SLA: <= 800 ms, <= $0.03, <= 4000 tokens
        Budget budget = new Budget(0.03, 4000, Duration.ofMillis(800).toMillis());

        List<Tactic> pool = List.of(new SmallModel(), new RAGBoost(), new LargeModel(), new ReflectPass());

        // Prefer quality but penalize cost/latency. Early-exit at 0.85 quality.
        Optimizer optimizer = new Optimizer(
                1.0,   // weight for quality
                0.6,   // weight for cost
                0.3,   // weight for latency
                0.85   // target quality
        );

        ResourceAwareOrchestrator orch = new ResourceAwareOrchestrator(optimizer);
        Result res = orch.execute("Summarize Q3 EV market drivers for executives.", budget, pool);

        System.out.println("ARTIFACT: " + res.artifact);
        System.out.println(String.format(Locale.US, "quality=%.2f cost=$%.3f tokens=%d time=%dms",
                res.quality, res.usd, res.tokens, res.ms));
    }
}
```

## Known Uses

-   Dynamic model selection: small model by default, escalate to large model only when uncertainty or value is high.

-   RAG depth control: adjust top-k, reranker, and chunk budget to hit latency caps.

-   Parallel exploration with early stop: race two prompts or providers, cancel losers when a good answer arrives.

-   Tiered generation: draft with cheaper path, refine with reflection only if metrics are below threshold.

-   Request shaping by segment: stricter caps for low-value traffic, expanded budgets for VIP or safety-critical flows.


## Related Patterns

-   **Planning:** expresses steps and checkpoints that the optimizer can prune or expand.

-   **Routing:** chooses tools/models; resource-aware policy constrains the choices.

-   **Parallelization:** bounded fan-out with early cancel based on budget and SLA.

-   **Reflection:** conditional improvement passes when quality is below target.

-   **Tool Use:** costed tool calls with timeouts, retries, and circuit breakers.

-   **Goal Setting and Monitoring:** ties optimization targets to explicit KRs and SLA alerts.

-   **Exception Handling and Recovery:** defines fallback behavior when budgets or rate limits are exceeded.
