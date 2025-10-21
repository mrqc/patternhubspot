
# Prioritization

## Pattern Name and Classification

Prioritization — coordination/scheduling pattern for agentic systems; orders tasks, messages, or tool calls by utility and constraints so the most valuable work is executed first under budget and SLA limits.

## Intent

Continuously rank and schedule competing work items based on urgency, value, risk, dependency readiness, and resource constraints to maximize outcome per unit cost and time.

## Also Known As

Ranking and Scheduling; Utility-Driven Queueing; Weighted Priorities; Work Triage; Task Arbitration.

## Motivation (Forces)

-   Agents face more candidate actions than they can do within token, cost, and latency budgets.

-   Some items are time-sensitive or user-critical; others are optional or exploratory.

-   Value signals conflict: business impact vs risk vs fairness vs freshness.

-   Without an explicit policy, first-come-first-served quietly burns budget on low-value work.  
    Prioritization converts messy signals into a stable ordering with predictable behavior.


## Applicability

Use when:

-   The system queues heterogeneous tasks (research vs generation vs tool calls) with different SLAs.

-   Resources are limited (rate limits, concurrency, budget).

-   You need fairness across users or tenants while still honoring high-value items.

-   Work has dependencies or must wait for prerequisites (retrieval, approval).


## Structure

1.  **Work Item** with attributes: deadline, value, effort, risk, user tier, dependencies, age.

2.  **Policy** defining a scoring function and tie-break rules.

3.  **Priority Queue** ordered by score and readiness.

4.  **Budget/SLA Guard** admitting tasks that fit current tokens, cost, and time.

5.  **Scheduler/Executor** pulling top-ready items, executing, and emitting telemetry.

6.  **Aging & Re-scoring** to prevent starvation and adapt to drift.


## Participants

-   **Producer(s)**: create tasks with metadata.

-   **Policy Engine**: computes priority scores and enforces fairness/guardrails.

-   **Priority Queue**: maintains ordered, deduplicated tasks.

-   **Budget Manager**: checks remaining cost/tokens/concurrency.

-   **Executor**: performs the task or routes it to a tool/agent.

-   **Monitor**: tracks wait time, preemption, and SLA attainment.


## Collaboration

Producers submit tasks → Policy computes initial scores and inserts them into the priority queue → Scheduler repeatedly re-scores stale items, admits those that fit budgets, and dispatches the best-ready task → Executor runs and reports metrics → Monitor and policy adjust weights or caps.

## Consequences

**Benefits**

-   Makes tradeoffs explicit; maximizes value under constraints.

-   Reduces missed deadlines and waste from low-ROI work.

-   Supports fairness and starvation resistance via aging and quotas.


**Liabilities**

-   Requires good signals and ongoing calibration.

-   Complex policies can be brittle or gameable.

-   Re-scoring adds overhead; poorly chosen aging can thrash order.


## Implementation (Key Points)

-   Model priority as a **bounded score** (e.g., 0–1) from normalized features: `urgency`, `business value`, `risk`, `effort`, `age`, `tier`.

-   Include **readiness** gates: all dependencies met and payload validated before admission.

-   Add **aging/boost** over wait time to avoid starvation; cap the boost.

-   Enforce **budgets and quotas**: per-tenant concurrency, tokens, cost per minute.

-   Make scoring **transparent and auditable**; log decision factors per dispatch.

-   Recompute scores on key events (new data, nearing deadlines, budget changes).

-   Provide **preemption hooks** for emergency tasks without destabilizing the queue.

-   Version policies and evaluate with offline replays before deploying.


## Sample Code (Java)

```java
import java.time.*;
import java.util.*;
import java.util.concurrent.PriorityBlockingQueue;

/** ---------- Domain ---------- */
enum Tier { FREE, STANDARD, PREMIUM }

class Task {
    final String id;
    final String kind;                     // e.g., "retrieval", "generation"
    final double value;                    // business impact 0..1
    final double risk;                     // risk 0..1 (higher => more review cost)
    final double effort;                   // estimated tokens/cost normalized 0..1
    final Tier tier;                       // tenant tier
    final Instant createdAt = Instant.now();
    final Instant deadline;                // may be null
    final Set<String> deps;                // unmet dependencies
    volatile double lastScore = 0.0;

    Task(String id, String kind, double value, double risk, double effort, Tier tier,
         Instant deadline, Set<String> deps) {
        this.id = id; this.kind = kind; this.value = value; this.risk = risk;
        this.effort = effort; this.tier = tier; this.deadline = deadline;
        this.deps = deps == null ? Set.of() : deps;
    }

    long ageSeconds() { return Duration.between(createdAt, Instant.now()).getSeconds(); }
    boolean ready() { return deps.isEmpty(); }
}

/** ---------- Budgets/SLA ---------- */
class Budget {
    double usdRemaining;
    long tokensRemaining;
    int concurrencyRemaining;

    Budget(double usd, long tokens, int conc) {
        this.usdRemaining = usd; this.tokensRemaining = tokens; this.concurrencyRemaining = conc;
    }
    boolean admit(Task t) {
        // toy admission using effort as proxy for cost/tokens
        double estUsd = 0.02 * t.effort * 10;  // placeholder
        long estTok = (long)(800 * t.effort * 10);
        return usdRemaining >= estUsd && tokensRemaining >= estTok && concurrencyRemaining > 0;
    }
    void charge(Task t) {
        double estUsd = 0.02 * t.effort * 10;
        long estTok = (long)(800 * t.effort * 10);
        usdRemaining -= estUsd; tokensRemaining -= estTok; concurrencyRemaining -= 1;
    }
    void release() { concurrencyRemaining += 1; }
}

/** ---------- Policy ---------- */
class PriorityPolicy {
    // Weights: tune per domain
    final double wValue = 0.45;
    final double wUrgency = 0.25;
    final double wTier = 0.15;
    final double wRiskPenalty = 0.10;
    final double wEffortPenalty = 0.05;

    final double agingHalfLifeSec = 120.0; // increases priority over time (starvation control)
    final double deadlineShockSec = 60.0;  // extra boost near deadline
    final Map<Tier, Double> tierBoost = Map.of(
            Tier.FREE, 0.85, Tier.STANDARD, 1.0, Tier.PREMIUM, 1.15);

    double score(Task t) {
        double urgency = computeUrgency(t);
        double tierFactor = tierBoost.getOrDefault(t.tier, 1.0) - 1.0; // map to roughly -0.15..+0.15 range
        double penalties = wRiskPenalty * t.risk + wEffortPenalty * t.effort;
        double s = wValue * clamp01(t.value)
                 + wUrgency * urgency
                 + wTier * (0.5 + tierFactor)   // normalize to 0..1-ish
                 - penalties;
        return clamp01(s);
    }

    private double computeUrgency(Task t) {
        double ageBoost = 1.0 - Math.exp(-Math.log(2) * t.ageSeconds() / agingHalfLifeSec); // 0..1
        double deadlineBoost = 0.0;
        if (t.deadline != null) {
            long sec = Duration.between(Instant.now(), t.deadline).getSeconds();
            if (sec <= 0) deadlineBoost = 1.0;
            else if (sec < deadlineShockSec) deadlineBoost = 1.0 - (sec / deadlineShockSec);
        }
        return clamp01(0.5 * ageBoost + 0.5 * deadlineBoost);
    }

    private double clamp01(double x) { return Math.max(0.0, Math.min(1.0, x)); }
}

/** ---------- Scheduler ---------- */
class PrioritizationScheduler {
    private final PriorityBlockingQueue<Task> queue;
    private final PriorityPolicy policy = new PriorityPolicy();
    private final Budget budget;

    PrioritizationScheduler(Budget budget) {
        this.budget = budget;
        this.queue = new PriorityBlockingQueue<>(64, Comparator.<Task>comparingDouble(t -> t.lastScore).reversed());
    }

    void submit(Task t) {
        t.lastScore = policy.score(t);
        queue.offer(t);
    }

    Optional<Task> dispatch() {
        // Re-score a sample to reduce staleness (cheap aging)
        List<Task> sample = new ArrayList<>();
        queue.drainTo(sample, Math.min(queue.size(), 8));
        for (Task t : sample) {
            t.lastScore = policy.score(t);
        }
        queue.addAll(sample);

        while (true) {
            Task t = queue.poll();
            if (t == null) return Optional.empty();
            if (!t.ready()) { t.lastScore *= 0.8; queue.offer(t); continue; }
            if (!budget.admit(t)) { t.lastScore *= 0.9; queue.offer(t); return Optional.empty(); }
            budget.charge(t);
            return Optional.of(t);
        }
    }

    void complete(Task t) { budget.release(); }
}

/** ---------- Executor (stub) ---------- */
class Executor {
    String run(Task t) {
        // pretend to do the work
        try { Thread.sleep(Math.max(20, (int)(t.effort * 200))); } catch (InterruptedException ignored) {}
        return "OK:" + t.id + ":" + t.kind;
    }
}

/** ---------- Demo ---------- */
public class PrioritizationDemo {
    public static void main(String[] args) {
        Budget budget = new Budget(0.50, 20000, 2);
        PrioritizationScheduler sched = new PrioritizationScheduler(budget);
        Executor exec = new Executor();

        // Create mixed tasks
        sched.submit(new Task("T1","generation", 0.9, 0.2, 0.6, Tier.PREMIUM,
                Instant.now().plusSeconds(40), Set.of()));
        sched.submit(new Task("T2","retrieval", 0.6, 0.1, 0.2, Tier.FREE,
                Instant.now().plusSeconds(180), Set.of()));
        sched.submit(new Task("T3","tool_call", 0.7, 0.6, 0.8, Tier.STANDARD,
                null, Set.of())); // risky and heavy
        sched.submit(new Task("T4","generation", 0.5, 0.1, 0.3, Tier.PREMIUM,
                Instant.now().plusSeconds(10), Set.of()));
        sched.submit(new Task("T5","research", 0.8, 0.2, 0.4, Tier.STANDARD,
                Instant.now().plusSeconds(300), Set.of()));

        // Simple dispatch loop
        for (int i = 0; i < 5; i++) {
            sched.dispatch().ifPresent(task -> {
                String res = exec.run(task);
                System.out.println("Dispatched " + task.id + " score=" + String.format(Locale.US,"%.2f", task.lastScore) + " -> " + res);
                sched.complete(task);
            });
            try { Thread.sleep(50); } catch (InterruptedException ignored) {}
        }
    }
}
```

## Known Uses

-   Multi-tool or multi-agent orchestrators triaging user requests by urgency, value, and tier.

-   Customer support copilots prioritizing active conversations over batch summarization.

-   Retrieval pipelines scheduling hot queries and deferring low-impact re-indexing.

-   Code assistants ranking fixes that unblock tests before style refactors.

-   Research/write agents promoting time-critical updates before background enrichment.


## Related Patterns

-   **Planning:** supplies the task DAG; prioritization chooses execution order among ready nodes.

-   **Routing:** after picking which task to run, route it to the best tool/agent.

-   **Resource-Aware Optimization:** enforces cost, latency, and token ceilings during admission.

-   **Parallelization:** selects which subset to run concurrently under concurrency caps.

-   **Goal Setting and Monitoring:** aligns priority weights with KRs and SLAs; alerts on starvation.

-   **Evaluation and Monitoring:** checks that prioritization improves outcomes and doesn’t violate fairness.

-   **Exception Handling and Recovery:** de-prioritizes or quarantines repeatedly failing tasks.
