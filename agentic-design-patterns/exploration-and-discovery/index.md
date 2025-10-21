
# Exploration and Discovery

## Pattern Name and Classification

Exploration and Discovery — search/optimization pattern for agentic systems; systematically probes alternative prompts, tools, parameters, and data sources to uncover higher-quality solutions or information spaces.

## Intent

Broaden the search beyond the first plausible path by generating, sampling, and scoring diverse candidates, then narrowing to the most promising directions.

## Also Known As

Divergent Search; Hypothesis Generation; Space Exploration; Parameter Sweep; Active Search.

## Motivation (Forces)

-   First ideas are often mediocre; local optima trap agents.

-   Information is incomplete or scattered across sources.

-   Model outputs are stochastic; diversity improves odds of success.

-   Exploration costs tokens, time, and money; naïve brute force is wasteful.  
    This pattern balances breadth vs depth with budgets, de-duplication, and stop rules.


## Applicability

Use when:

-   You need novel approaches, sources, or prompts rather than a single “best guess.”

-   The solution space is large, multi-modal, or poorly understood.

-   You can define a proxy score (rubric, validator, retrieval quality).

-   There’s room to trade a bit of latency/cost for higher reliability or coverage.


## Structure

1.  **Seed**: initial goal, query, or draft.

2.  **Generators**: create candidate variations (prompt rewrites, tool combos, parameter sweeps).

3.  **Sampler**: selects a subset to try (random, UCB, Latin hypercube, MMR).

4.  **Evaluator**: scores candidates (tests, rubrics, hit-rate, diversity).

5.  **Frontier/Archive**: priority queue of promising candidates and a de-dup store.

6.  **Budgeter**: enforces iteration, cost, and time caps.

7.  **Selector**: returns the best candidate(s) or a fused result.


## Participants

-   **Explorer/Orchestrator**: runs the loop and tracks budgets.

-   **Strategy**: a concrete exploration method (query expansion, parameter sweep, tool mix).

-   **Scorer/Verifier**: produces a numeric utility.

-   **Diversity Filter**: prevents near-duplicates flooding the frontier.

-   **Result Selector**: picks top-k or best-score.


## Collaboration

Seed enters → Strategies propose candidates → Sampler picks a batch → Evaluator scores them → Frontier keeps the top diverse set → Budgeter checks limits → Iterate until threshold or budget → Selector returns winner and evidence.

## Consequences

**Benefits**

-   Higher chance of finding strong solutions or sources.

-   Resilient to noise and local optima.

-   Reusable: same loop works for prompts, tools, hyperparameters, and queries.


**Liabilities**

-   Extra cost/latency.

-   Requires a good scoring signal; bad proxies mislead.

-   Needs de-dup/diversity control to avoid mode collapse.


## Implementation (Key Points)

-   Combine **breadth** (diverse generators) with **focus** (bandit/UCB to allocate trials).

-   Use **diversity metrics** (MMR, Jaccard, embedding distance) to keep the frontier varied.

-   Make budgets explicit: max trials, max tokens, max wall time.

-   Score with deterministic checks where possible; avoid circular self-judgment.

-   Log proposals, scores, and winners for learning and replay.

-   Early-stop when score crosses threshold or when improvement stalls.


## Sample Code (Java)

```java
import java.util.*;
import java.util.concurrent.ThreadLocalRandom;
import java.util.stream.Collectors;

/** ------------ Candidate + Scoring ------------ */
class Candidate {
    final String text;          // prompt/query/tool-plan variant
    final Map<String, Object> meta = new HashMap<>();
    double score;               // utility 0..1
    Candidate(String text) { this.text = text; }
}

interface Scorer {
    /** Return 0..1 utility for a candidate. Replace with real rubric/validator. */
    double score(Candidate c, String task);
}

/** A toy scorer: rewards presence of keywords, brevity, and novelty. */
class HeuristicScorer implements Scorer {
    public double score(Candidate c, String task) {
        String t = c.text.toLowerCase();
        double kw = 0;
        for (String k : List.of("why", "evidence", "steps", "sources", "check")) {
            if (t.contains(k)) kw += 0.12;
        }
        double brev = Math.max(0, 0.4 - (t.length() / 400.0)); // shorter is better up to a point
        double spice = ThreadLocalRandom.current().nextDouble(0.0, 0.1); // stochastic tie-break
        return Math.min(1.0, 0.35 + kw + brev + spice);
    }
}

/** ------------ Exploration Strategies ------------ */
interface ExplorationStrategy {
    String name();
    List<Candidate> propose(String task, Candidate seed, int count);
}

/** Random perturbation of wording and structure. */
class RandomRewrite implements ExplorationStrategy {
    public String name() { return "random_rewrite"; }
    public List<Candidate> propose(String task, Candidate seed, int count) {
        List<String> templates = List.of(
                "Explain step-by-step: %s. Include evidence and risks.",
                "Summarize then drill down: %s. Provide 3 sources and a check step.",
                "Pose sub-questions for: %s. Outline plan and verification.",
                "Give hypotheses for: %s. Rank by plausibility and list what to test."
        );
        List<Candidate> out = new ArrayList<>();
        for (int i = 0; i < count; i++) {
            String tpl = templates.get(ThreadLocalRandom.current().nextInt(templates.size()));
            out.add(new Candidate(String.format(tpl, task)));
        }
        return out;
    }
}

/** Query expansion: adds synonyms and facets to improve retrieval prompts. */
class QueryExpansion implements ExplorationStrategy {
    public String name() { return "query_expansion"; }
    public List<Candidate> propose(String task, Candidate seed, int count) {
        List<String> facets = List.of("trends", "benchmarks", "counterexamples", "methodology", "limitations");
        List<Candidate> out = new ArrayList<>();
        for (int i = 0; i < count; i++) {
            Collections.shuffle(facets);
            String q = task + " | facets: " + String.join(", ", facets.subList(0, Math.min(3, facets.size())));
            out.add(new Candidate(q));
        }
        return out;
    }
}

/** Parameter sweep: toggles knobs (k, temperature, tool mix) encoded in meta. */
class ParamSweep implements ExplorationStrategy {
    public String name() { return "param_sweep"; }
    public List<Candidate> propose(String task, Candidate seed, int count) {
        int[] topk = {3, 5, 8};
        double[] temp = {0.2, 0.5, 0.8};
        String[] tools = {"calc", "web", "none", "calc+web"};
        List<Candidate> out = new ArrayList<>();
        for (int i = 0; i < count; i++) {
            Candidate c = new Candidate("Plan: " + task);
            c.meta.put("topK", topk[ThreadLocalRandom.current().nextInt(topk.length)]);
            c.meta.put("temp", temp[ThreadLocalRandom.current().nextInt(temp.length)]);
            c.meta.put("tools", tools[ThreadLocalRandom.current().nextInt(tools.length)]);
            out.add(c);
        }
        return out;
    }
}

/** ------------ Diversity filter (Jaccard on tokens) ------------ */
class DiversityFilter {
    private final double minDistance;
    DiversityFilter(double minDistance) { this.minDistance = minDistance; }

    boolean isNovel(Candidate c, Collection<Candidate> archive) {
        for (Candidate seen : archive) {
            if (similarity(tokens(c.text), tokens(seen.text)) > (1.0 - minDistance)) return false;
        }
        return true;
    }
    private Set<String> tokens(String s) {
        return Arrays.stream(s.toLowerCase().split("[^a-z0-9]+"))
                .filter(t -> t.length() > 2).collect(Collectors.toSet());
    }
    private double similarity(Set<String> a, Set<String> b) {
        if (a.isEmpty() && b.isEmpty()) return 1.0;
        Set<String> inter = new HashSet<>(a); inter.retainAll(b);
        Set<String> uni = new HashSet<>(a); uni.addAll(b);
        return uni.isEmpty() ? 0.0 : (double) inter.size() / uni.size();
    }
}

/** ------------ Bandit allocator (UCB1) across strategies ------------ */
class UcbBandit {
    private final Map<String, Integer> pulls = new HashMap<>();
    private final Map<String, Double> reward = new HashMap<>();
    double ucb(String arm) {
        int n = pulls.values().stream().mapToInt(i -> i).sum();
        int k = pulls.getOrDefault(arm, 0);
        double mean = reward.getOrDefault(arm, 0.0) / Math.max(1, k);
        double bonus = k == 0 ? 1.0 : Math.sqrt(2 * Math.log(Math.max(1, n)) / k);
        return mean + bonus;
    }
    void update(String arm, double r) {
        pulls.put(arm, pulls.getOrDefault(arm, 0) + 1);
        reward.put(arm, reward.getOrDefault(arm, 0.0) + r);
    }
}

/** ------------ Explorer orchestrator ------------ */
class Explorer {
    private final List<ExplorationStrategy> strategies;
    private final Scorer scorer;
    private final DiversityFilter diversity;
    private final UcbBandit bandit = new UcbBandit();

    // Budgets
    private final int maxIterations;
    private final int batchSize;
    private final int frontierSize;
    private final double targetScore;

    Explorer(List<ExplorationStrategy> strategies, Scorer scorer, DiversityFilter diversity,
             int maxIterations, int batchSize, int frontierSize, double targetScore) {
        this.strategies = strategies; this.scorer = scorer; this.diversity = diversity;
        this.maxIterations = maxIterations; this.batchSize = batchSize;
        this.frontierSize = frontierSize; this.targetScore = targetScore;
    }

    Candidate run(String task, Candidate seed) {
        PriorityQueue<Candidate> frontier =
                new PriorityQueue<>(Comparator.comparingDouble(c -> c.score)); // min-heap
        List<Candidate> archive = new ArrayList<>();
        seed.score = scorer.score(seed, task);
        frontier.offer(seed); archive.add(seed);

        for (int it = 0; it < maxIterations; it++) {
            // Pick a strategy by UCB
            ExplorationStrategy chosen = strategies.stream()
                    .max(Comparator.comparingDouble(s -> bandit.ucb(s.name())))
                    .orElse(strategies.get(0));

            List<Candidate> proposals = chosen.propose(task, seed, batchSize);
            double bestBatch = 0.0;

            for (Candidate c : proposals) {
                if (!diversity.isNovel(c, archive)) continue;
                c.score = scorer.score(c, task);
                archive.add(c);
                if (frontier.size() < frontierSize) frontier.offer(c);
                else if (c.score > frontier.peek().score) { frontier.poll(); frontier.offer(c); }
                bestBatch = Math.max(bestBatch, c.score);
            }
            bandit.update(chosen.name(), bestBatch);

            Candidate best = frontier.stream().max(Comparator.comparingDouble(x -> x.score)).orElse(seed);
            if (best.score >= targetScore) return best;
        }
        return frontier.stream().max(Comparator.comparingDouble(x -> x.score)).orElse(seed);
    }
}

/** ------------ Demo ------------ */
public class ExplorationAndDiscoveryDemo {
    public static void main(String[] args) {
        String task = "Explain why EV sales rose last quarter in the EU and list sources to verify.";

        Explorer explorer = new Explorer(
                List.of(new RandomRewrite(), new QueryExpansion(), new ParamSweep()),
                new HeuristicScorer(),
                new DiversityFilter(0.30),   // require at least 30% token-level novelty
                10,                          // max iterations
                4,                           // proposals per iteration
                8,                           // frontier size
                0.85                         // target score threshold
        );

        Candidate seed = new Candidate("Describe " + task + " Include steps and verification.");
        Candidate winner = explorer.run(task, seed);

        System.out.println("WINNER SCORE: " + String.format(Locale.US, "%.3f", winner.score));
        System.out.println("WINNER TEXT: " + winner.text);
        System.out.println("WINNER META: " + winner.meta);
    }
}
```

## Known Uses

-   Prompt discovery for new tasks or domains before locking a production prompt.

-   Query expansion and facet exploration in retrieval workflows.

-   Toolchain exploration: try calculator vs web vs code-exec mixes and keep the best.

-   Hyperparameter search for generation settings (temperature, top-k, context size).

-   Research and writing agents that branch into alternative outlines and pick the strongest.


## Related Patterns

-   **Reasoning Techniques:** supplies multi-path search and verification used during exploration.

-   **Planning:** seeds exploration with step lists and integrates winners back into the plan.

-   **Routing:** after exploration, route traffic toward the best tactic.

-   **Parallelization:** try multiple candidates concurrently and merge or select.

-   **Learning and Adaptation:** learn which strategies win and bias future exploration.

-   **Evaluation and Monitoring:** measure exploration ROI and guard against regressions.

-   **Resource-Aware Optimization:** cap breadth/depth based on budgets and SLAs.
