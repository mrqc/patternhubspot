
# Goal Setting and Monitoring

## Pattern Name and Classification

Goal Setting and Monitoring — coordination/oversight pattern for agentic systems; defines explicit objectives, success metrics, and checkpoints, then continuously tracks progress and triggers course corrections.

## Intent

Turn vague objectives into measurable goals with clear acceptance criteria, then instrument the workflow so the agent can monitor progress, detect drift, and adapt before failure.

## Also Known As

Objectives and Key Results (OKRs) for Agents; Targeting and Telemetry; KPI-Driven Execution; Watchdog Goals.

## Motivation (Forces)

-   Agents easily wander without crisp objectives and measurable criteria.

-   Long tasks span multiple steps, models, and tools where failures hide.

-   Budgets matter: tokens, latency, money, rate limits.

-   Requirements change; monitoring must surface when goals become obsolete.

-   Humans often need checkpoints for review and accountability.


## Applicability

Use when:

-   The task has a clear outcome that can be expressed as measurable Key Results.

-   Work spans multiple steps/agents/tools and needs mid-course correction.

-   There are budgets or SLAs to respect.

-   Human approval is required at milestones.  
    Avoid when success is inherently unmeasurable and no proxy signal exists.


## Structure

1.  **Goal**: textual objective plus measurable Key Results (KRs).

2.  **Budget & SLA**: ceilings for cost, time, tokens, retries.

3.  **Plan/Milestones**: ordered steps with intermediate acceptance checks.

4.  **Telemetry**: metrics, events, and artifacts emitted during execution.

5.  **Monitor**: rules to evaluate progress vs KRs and budgets.

6.  **Adaptation Hooks**: replanning, escalation, human review, or abort.

7.  **Audit Log**: decisions, metric snapshots, and outcomes.


## Participants

-   **Owner/Coordinator**: creates the goal, defines KRs, budgets, and checkpoints.

-   **Agent/Executor**: performs steps and emits telemetry.

-   **Monitor/Watchdog**: compares telemetry to thresholds; raises events.

-   **Replanner**: updates plan when KRs or budgets are off-track.

-   **Reviewer**: optional human approver at gates.

-   **Store/Logger**: persists metrics and decisions.


## Collaboration

Owner defines Goal + KRs + budgets → Coordinator attaches plan and checkpoints → Agent executes and emits telemetry → Monitor evaluates progress and budget consumption → If off-track, Replanner edits plan or escalates to Reviewer → When all KRs meet thresholds within budgets, Goal is marked achieved.

## Consequences

**Benefits**

-   Clarity: explicit objectives and measurable success.

-   Early warning: drift and over-budget detected before final failure.

-   Accountability: audit trail of decisions and progress.

-   Better human collaboration via planned checkpoints.


**Liabilities**

-   Overhead to define metrics and instrumentation.

-   Bad KRs incentivize the wrong behavior.

-   Monitoring noise if thresholds are too tight.

-   Extra complexity for data collection and storage.


## Implementation (Key Points)

-   Represent goals as typed objects with: objective, KRs, budgets, milestones, and stop conditions.

-   Make KRs measurable: numeric target, comparator, window, and required confidence.

-   Emit structured telemetry from each step; avoid scraping free text.

-   Define alerting rules: warn, soft fail, hard fail; include cool-downs and debouncing.

-   Support replanning on threshold breaches; record diffs and rationale.

-   Expose a compact dashboard snapshot for humans: current KR values, trend, ETA, risks.

-   Gate risky steps behind human review or policy checks.

-   Archive final metrics and artifacts for learning and future priors.


## Sample Code (Java)

```java
import java.time.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.DoubleSupplier;

/** ---- Goal model ---- */
enum ComparatorOp { GTE, LTE, EQ }

class KeyResult {
    final String name;
    final ComparatorOp op;
    final double target;
    final Duration window; // how long the target should be sustained
    final AtomicReference<Double> current = new AtomicReference<>(0.0);
    final AtomicReference<Instant> lastUpdated = new AtomicReference<>(Instant.EPOCH);

    KeyResult(String name, ComparatorOp op, double target, Duration window) {
        this.name = name; this.op = op; this.target = target; this.window = window;
    }

    void update(double value) {
        current.set(value);
        lastUpdated.set(Instant.now());
    }

    boolean meetsTarget() {
        double v = current.get();
        return switch (op) {
            case GTE -> v >= target;
            case LTE -> v <= target;
            case EQ  -> Math.abs(v - target) < 1e-9;
        };
    }
}

class Budget {
    final double maxCostUsd;
    final long maxTokens;
    final Duration maxWallTime;
    double spentUsd = 0.0;
    long usedTokens = 0;
    final Instant started = Instant.now();

    Budget(double maxCostUsd, long maxTokens, Duration maxWallTime) {
        this.maxCostUsd = maxCostUsd; this.maxTokens = maxTokens; this.maxWallTime = maxWallTime;
    }

    void addCost(double usd, long tokens) {
        spentUsd += usd; usedTokens += tokens;
    }

    boolean withinLimits() {
        boolean timeOk = Duration.between(started, Instant.now()).compareTo(maxWallTime) <= 0;
        return spentUsd <= maxCostUsd && usedTokens <= maxTokens && timeOk;
    }
}

class Goal {
    final String objective;
    final List<KeyResult> krs = new ArrayList<>();
    final Budget budget;
    final List<String> milestones = new ArrayList<>();
    boolean achieved = false;

    Goal(String objective, Budget budget) {
        this.objective = objective; this.budget = budget;
    }

    Goal addKR(KeyResult kr) { krs.add(kr); return this; }
    Goal addMilestone(String m) { milestones.add(m); return this; }

    boolean allKRsGreen() { return krs.stream().allMatch(KeyResult::meetsTarget); }
}

/** ---- Monitoring and adaptation ---- */
interface Action {
    String name();
    double costUsd();           // estimated cost for accounting
    long tokens();              // estimated tokens for accounting
    String run();               // returns telemetry or artifact id
}

class Monitor {
    enum State { ON_TRACK, WARNING, OFF_TRACK, BUDGET_EXCEEDED, DONE }

    static State evaluate(Goal goal) {
        if (!goal.budget.withinLimits()) return State.BUDGET_EXCEEDED;
        if (goal.allKRsGreen()) return State.DONE;

        // Simple warning when any KR is near target (within 10%) but not met
        boolean near = goal.krs.stream().anyMatch(kr -> {
            double v = kr.current.get();
            return switch (kr.op) {
                case GTE -> v >= 0.9 * kr.target && v < kr.target;
                case LTE -> v <= 1.1 * kr.target && v > kr.target;
                case EQ  -> Math.abs(v - kr.target) <= 0.1 * Math.max(1.0, kr.target);
            };
        });
        return near ? State.WARNING : State.OFF_TRACK;
    }
}

class Replanner {
    /** Example: if off-track, schedule a higher-accuracy action; if warning, run a cheap booster. */
    static List<Action> proposeNext(Goal goal, Monitor.State state) {
        List<Action> plan = new ArrayList<>();
        switch (state) {
            case OFF_TRACK -> plan.add(new HighAccuracyAction());
            case WARNING   -> plan.add(new CheapBoosterAction());
            default -> {}
        }
        return plan;
    }
}

/** ---- Example actions (stubs) ---- */
class CheapBoosterAction implements Action {
    public String name() { return "cheap_booster"; }
    public double costUsd() { return 0.002; }
    public long tokens() { return 500; }
    public String run() { return "booster:light_rerank"; }
}
class HighAccuracyAction implements Action {
    public String name() { return "high_accuracy"; }
    public double costUsd() { return 0.03; }
    public long tokens() { return 4000; }
    public String run() { return "synthesis:high_confidence"; }
}

/** ---- Orchestrator demonstrating goal-driven loop ---- */
public class GoalSettingAndMonitoringDemo {
    public static void main(String[] args) {
        // Define goal
        Goal goal = new Goal(
                "Produce an executive brief on Q3 EV trends with high quality under tight budget",
                new Budget(0.10, 12000, Duration.ofSeconds(5))
        )
        .addKR(new KeyResult("quality_score", ComparatorOp.GTE, 0.85, Duration.ofSeconds(0)))
        .addKR(new KeyResult("coverage_ratio", ComparatorOp.GTE, 0.90, Duration.ofSeconds(0)))
        .addMilestone("retrieve")
        .addMilestone("draft")
        .addMilestone("review")
        .addMilestone("finalize");

        // Initial KR readings from a first cheap pass
        goal.krs.get(0).update(0.78); // quality
        goal.krs.get(1).update(0.88); // coverage
        goal.budget.addCost(0.01, 1500);

        // Monitoring loop
        for (int round = 1; round <= 4; round++) {
            Monitor.State state = Monitor.evaluate(goal);
            System.out.println("Round " + round + " | state=" + state
                    + " | budget=$" + String.format(Locale.US, "%.3f", goal.budget.spentUsd)
                    + " tokens=" + goal.budget.usedTokens
                    + " | KR quality=" + goal.krs.get(0).current.get()
                    + " coverage=" + goal.krs.get(1).current.get());

            if (state == Monitor.State.DONE) { goal.achieved = true; break; }
            if (state == Monitor.State.BUDGET_EXCEEDED) { break; }

            for (Action a : Replanner.proposeNext(goal, state)) {
                // Execute and update telemetry (simulate improvement)
                a.run();
                goal.budget.addCost(a.costUsd(), a.tokens());
                // naive improvement model
                goal.krs.get(0).update(Math.min(1.0, goal.krs.get(0).current.get() + 0.06));
                goal.krs.get(1).update(Math.min(1.0, goal.krs.get(1).current.get() + 0.05));
            }
        }

        System.out.println("Result: achieved=" + goal.achieved);
    }
}
```

## Known Uses

-   Research/writing agents with explicit quality and coverage thresholds before publishing.

-   Customer support copilots that must hit first-response and resolution SLAs.

-   Data pipelines with schema-pass rates and freshness KRs before release.

-   Codegen agents that must pass unit tests, linting, and bundle size budgets.

-   Retrieval-augmented systems that target citation rate and hallucination bounds.


## Related Patterns

-   **Planning:** transforms goals into a plan with milestones and budgets.

-   **Prompt Chaining:** goals attach success checks to each stage.

-   **Reflection:** monitors feed critiques that drive corrective revisions.

-   **Parallelization:** run multiple paths to reach KR targets faster.

-   **Routing:** choose cheaper or stronger paths depending on KR status.

-   **Tool Use:** monitoring triggers specific tools to improve metrics.

-   **Memory Management:** persist goals, KR histories, and budget traces for future runs.
