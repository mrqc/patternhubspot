
# Learning and Adaptation

## Pattern Name and Classification

Learning and Adaptation — optimization/feedback pattern for agentic systems; continuously updates policies, prompts, routing thresholds, or tool/model choices from signals and outcomes.

## Intent

Close the loop between results and behavior so the system improves over time, adapting to users, domains, costs, and drift without manual retuning for every change.

## Also Known As

Online Learning; Continual Learning; Self-Tuning; Bandits/Thompson Sampling; RL from Feedback (R(L)HF); Active Learning.

## Motivation (Forces)

-   Environments shift: user needs, data distributions, costs, rate limits, and tools change.

-   Static prompts/policies degrade and accumulate tech debt.

-   Good reward signals exist (task success, ratings, latency, cost, guardrail passes).

-   Exploration is necessary but risky; over-adaptation causes instability or bias.  
    Learning and Adaptation balances exploration vs exploitation to keep quality high while controlling cost and safety.


## Applicability

Use when:

-   You choose among multiple prompts/models/tools and can measure outcomes.

-   Personalization or per-segment policies matter.

-   There is measurable drift or seasonality.

-   You can define safe exploration and quick rollback.  
    Avoid when you cannot measure outcomes or must guarantee strict determinism.


## Structure

1.  **Telemetry**: capture features, decisions, outcomes.

2.  **Evaluator/Reward Shaper**: converts outcomes to a bounded reward.

3.  **Learner**: updates parameters (bandit, RL, Bayesian, gradient).

4.  **Policy/Config Store**: versioned, auditable decisions.

5.  **Executor**: runs the selected action (prompt/model/tool).

6.  **Guardrails**: safety checks on inputs, actions, and outputs.

7.  **Canary/Shadow**: safe rollout before full adoption.


## Participants

-   **Decision Policy**: maps context to an action (with exploration).

-   **Learner**: maintains estimates/posteriors and updates from rewards.

-   **Reward Shaper**: transforms success, quality, latency, cost into a single score.

-   **Policy Store**: persists versions and supports rollback.

-   **Monitor**: drift, fairness, regressions, budget consumption.

-   **Executor/Agent**: applies the chosen action in production.


## Collaboration

Request arrives → Policy selects action (with exploration) → Executor runs action → Telemetry captures signals → Reward Shaper computes reward → Learner updates estimates → Policy Store persists updated parameters → Canary/Monitor approve or roll back → Next decisions use improved policy.

## Consequences

**Benefits**

-   Continuous improvement without constant manual retuning.

-   Personalization and context-aware choices.

-   Cost/latency control via learned tradeoffs.


**Liabilities**

-   Instability if rewards are noisy or delayed.

-   Feedback loops and bias if signals are skewed.

-   Requires strong observability, guardrails, and rollback.

-   Privacy and compliance considerations for user-level learning.


## Implementation (Key Points)

-   Define a clear **reward** that mixes task success, quality, latency, and cost; normalize to \[0,1\].

-   Start with simple **bandits** (ε-greedy, UCB, Thompson) before complex RL.

-   Add **safe exploration**: caps per user/segment, canary routes, kill switches.

-   Use **decay** or sliding windows to track non-stationary environments.

-   Version prompts/policies; log context, decision, reward, and policy version.

-   Segment by user/task to avoid one-size-fits-none; share priors across segments when sparse.

-   Enforce guardrails on both chosen actions and produced outputs.

-   Offline replay tests and shadow traffic before enabling online updates.


## Sample Code (Java)

```java
import java.util.*;
import java.util.concurrent.ThreadLocalRandom;

/** --------- Signals and reward shaping --------- */
class Outcome {
    final boolean success;      // e.g., validator passed, user solved task
    final double quality;       // 0..1 from rubric or rating
    final long latencyMs;       // lower is better
    final double costUsd;       // lower is better
    Outcome(boolean success, double quality, long latencyMs, double costUsd) {
        this.success = success; this.quality = quality; this.latencyMs = latencyMs; this.costUsd = costUsd;
    }
}

class Reward {
    // Combine signals into a single 0..1 reward. Tune weights per domain.
    static double compute(Outcome o) {
        double base = (o.success ? 0.6 : 0.0) + 0.3 * clamp(o.quality, 0, 1);
        // Latency and cost penalties with soft bounds
        double latPenalty = sigmoidPenalty(o.latencyMs, 100, 1500);   // good before 100ms, bad after 1500ms
        double costPenalty = sigmoidPenalty(o.costUsd, 0.001, 0.05);  // adjust per system
        double r = base * latPenalty * costPenalty;
        return clamp(r, 0, 1);
    }
    private static double clamp(double v, double lo, double hi) { return Math.max(lo, Math.min(hi, v)); }
    private static double sigmoidPenalty(double x, double low, double high) {
        if (x <= low) return 1.0;
        if (x >= high) return 0.5; // floor penalty
        double t = (x - low) / (high - low);
        return 1.0 - 0.5 * t; // linear to keep it simple
    }
}

/** --------- Epsilon-Greedy bandit policy --------- */
class ArmStats {
    double value;  // estimated reward
    int pulls;
    ArmStats(double value, int pulls) { this.value = value; this.pulls = pulls; }
}

class EpsilonGreedyPolicy {
    private final Map<String, ArmStats> arms = new LinkedHashMap<>();
    private double epsilon;              // exploration probability
    private final double minEpsilon;
    private final double decay;          // multiplicative decay per update, e.g., 0.995
    private final double alpha;          // learning rate for value update (0 < alpha <= 1)

    EpsilonGreedyPolicy(Collection<String> armNames, double epsilon, double minEpsilon, double decay, double alpha) {
        for (String a : armNames) arms.put(a, new ArmStats(0.5, 0));  // optimistic prior
        this.epsilon = epsilon; this.minEpsilon = minEpsilon; this.decay = decay; this.alpha = alpha;
    }

    /** Choose an arm given optional context (not used in this simple policy). */
    public String choose(Map<String, Object> context) {
        if (ThreadLocalRandom.current().nextDouble() < epsilon) {
            return randomArm();
        }
        return arms.entrySet().stream().max(Comparator.comparingDouble(e -> e.getValue().value)).get().getKey();
    }

    /** Update value estimate for an arm. */
    public void update(String arm, double reward) {
        ArmStats s = arms.get(arm);
        s.pulls++;
        s.value = (1 - alpha) * s.value + alpha * reward;
        epsilon = Math.max(minEpsilon, epsilon * decay);
    }

    private String randomArm() {
        int idx = ThreadLocalRandom.current().nextInt(arms.size());
        return new ArrayList<>(arms.keySet()).get(idx);
    }

    public Map<String, ArmStats> snapshot() { return Collections.unmodifiableMap(arms); }
    public double getEpsilon() { return epsilon; }
}

/** --------- Adaptation manager: selects action and learns from outcomes --------- */
class AdaptationManager {
    private final EpsilonGreedyPolicy policy;
    private final Map<String, String> armToPrompt = new HashMap<>(); // map arms to prompts/models/tools

    AdaptationManager(List<String> arms) {
        this.policy = new EpsilonGreedyPolicy(arms, 0.20, 0.02, 0.995, 0.2);
        // Example: arms could represent prompts, models, or toolchains
        armToPrompt.put("promptA", "You are a concise analyst. Format answers in bullets.");
        armToPrompt.put("promptB", "You are a detailed researcher. Provide sources and caveats.");
        armToPrompt.put("modelSmall", "Use small/fast model with strict JSON output.");
        armToPrompt.put("modelLarge", "Use large/accurate model with chain-of-thought disabled.");
    }

    /** Decision: which arm to run for this request. */
    public String selectAction(Map<String, Object> context) {
        return policy.choose(context);
    }

    /** Learning: record the outcome and update policy. */
    public void recordOutcome(String arm, Outcome outcome) {
        double r = Reward.compute(outcome);
        policy.update(arm, r);
    }

    public String describeArm(String arm) { return armToPrompt.getOrDefault(arm, arm); }
    public double explorationRate() { return policy.getEpsilon(); }
    public Map<String, ArmStats> stats() { return policy.snapshot(); }
}

/** --------- Demo: simulate decisions and learning --------- */
public class LearningAndAdaptationDemo {
    public static void main(String[] args) {
        AdaptationManager mgr = new AdaptationManager(List.of("promptA", "promptB", "modelSmall", "modelLarge"));
        var rng = ThreadLocalRandom.current();

        // Simulate 100 requests with different “true” payoffs per arm (non-stationary)
        Map<String, Double> trueMean = new HashMap<>();
        trueMean.put("promptA", 0.70);
        trueMean.put("promptB", 0.78);
        trueMean.put("modelSmall", 0.60);
        trueMean.put("modelLarge", 0.82);

        for (int t = 1; t <= 100; t++) {
            // drift: modelLarge gets slightly worse after t=60 due to cost/latency pressure
            if (t == 60) trueMean.put("modelLarge", 0.72);

            String arm = mgr.selectAction(Map.of("userSegment", "pro", "task", "analysis"));
            // Stochastic outcome around the arm's true mean
            double base = trueMean.getOrDefault(arm, 0.6);
            boolean success = rng.nextDouble() < base;
            double quality = Math.min(1.0, Math.max(0.0, base + rng.nextGaussian() * 0.1));
            long latency = arm.equals("modelLarge") ? 900 + rng.nextInt(400) : 200 + rng.nextInt(200);
            double cost = arm.startsWith("model") ? (arm.equals("modelLarge") ? 0.04 : 0.008) : 0.005;

            Outcome outcome = new Outcome(success, quality, latency, cost);
            mgr.recordOutcome(arm, outcome);

            if (t % 20 == 0) {
                System.out.println("t=" + t + " eps=" + String.format(Locale.US, "%.3f", mgr.explorationRate()));
                mgr.stats().forEach((k, s) ->
                        System.out.println("  " + k + " pulls=" + s.pulls + " value=" + String.format(Locale.US, "%.3f", s.value)));
            }
        }

        // Final chosen action for a new request
        String chosen = mgr.selectAction(Map.of("userSegment", "pro", "task", "analysis"));
        System.out.println("\nChosen action: " + chosen + " => " + mgr.describeArm(chosen));
    }
}
```

## Known Uses

-   Auto-tuning prompt or tool selection via bandits with outcome-based rewards.

-   Dynamic model selection (small vs large) under cost and latency budgets.

-   Retrieval hyperparameter tuning (top-k, temperature, reranker choice) online.

-   Personalization of style, language, or safety thresholds per user/segment.

-   Adaptive retry/backoff policies and stop criteria in long chains.

-   Multi-agent role weights or vote thresholds adjusted from success metrics.


## Related Patterns

-   **Routing:** uses learned policies instead of static rules to choose destinations.

-   **Reflection:** provides critiques and scores that become rewards for learning.

-   **Memory Management:** stores outcomes, priors, and segment features for better learning.

-   **Planning:** plans adapt based on learned costs and success rates.

-   **Parallelization:** explores multiple candidates, then learns which ones to favor.

-   **Tool Use:** learns when tools are beneficial and which arguments perform best.

-   **Multi-Agent:** learns role assignments, turn-taking, and aggregation strategies.
