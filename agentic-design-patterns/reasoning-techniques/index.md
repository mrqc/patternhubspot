
# Reasoning Techniques

## Pattern Name and Classification

Reasoning Techniques — inference/decision pattern for agentic systems; applies structured thinking strategies (e.g., step decomposition, sampling, search, verification) to improve reliability and problem-solving.

## Intent

Increase correctness and robustness on complex tasks by guiding how an agent thinks before answering: split problems, explore alternatives, verify candidates, and only then present a final result.

## Also Known As

Chain-of-Thought (CoT); Self-Consistency; Tree-/Graph-of-Thought; Structured Scratchpad; ReAct-style Think-Act; Deliberate Sampling; Verifier-Ranked Decoding.

## Motivation (Forces)

-   Hard queries fail with single-shot generation.

-   Stochastic models vary; multiple candidate paths help.

-   Long prompts cause drift; structured scaffolds constrain reasoning.

-   Verifiers and tests can filter wrong paths, at a cost of latency and tokens.  
    The pattern trades a bit of time and budget for a significant jump in accuracy and debuggability.


## Applicability

Use when:

-   Tasks require multi-step logic, math, code, or multi-hop retrieval.

-   You can score intermediate or final candidates (tests, rules, verifiers).

-   The cost of a wrong answer is higher than modest extra compute.  
    Avoid when problems are trivial or you cannot evaluate correctness at all.


## Structure

1.  **Decomposition/Scratchpad**: plan steps or reserve a structured workspace.

2.  **Exploration**: sample N candidates or expand a search tree/graph.

3.  **Tool Use (optional)**: call calculators, retrieval, or simulators during reasoning.

4.  **Verification**: score candidates via rules, tests, or a critic model.

5.  **Selection/Aggregation**: pick best, vote, or fuse consistent parts.

6.  **Finalization**: format a clean answer for the user.


## Participants

-   **Reasoner**: produces candidates via a specific technique (CoT, ToT, etc.).

-   **Explorer**: manages branching and sampling.

-   **Verifier/Judge**: checks candidates against tests or rubrics.

-   **Selector**: ranks and chooses a winner; may do majority voting.

-   **Tooling Layer**: deterministic helpers during reasoning.

-   **Budget Manager**: enforces limits on tokens, time, and calls.


## Collaboration

Task arrives → Reasoner creates a plan or scratchpad → Explorer generates multiple trajectories (and optionally uses tools) → Verifier scores each → Selector picks or aggregates → Finalizer returns a concise answer; traces are logged for analysis.

## Consequences

**Benefits**

-   Higher accuracy via exploration plus verification.

-   Better transparency and debuggability from structured steps.

-   Flexibility: swap techniques per domain and budget.


**Liabilities**

-   More latency and cost.

-   Risk of overthinking without strong stop criteria.

-   Requires verifiers or rules to avoid voting wrong answers to the top.


## Implementation (Key Points)

-   Provide multiple strategies: CoT (single path), Self-Consistency (N paths + vote), Tree-of-Thought (beam search), and Verifier-Ranked decoding.

-   Keep **reasoning private**; show only the final answer to end users, not internal scratchpads.

-   Add **stop rules**: max steps, depth, tokens, and early-exit when a candidate passes tests.

-   Use **diversity controls**: temperature/top-p, different seeds/prompts, or beam branching.

-   Plug in **deterministic checks**: unit tests for code/math, schema validation for outputs.

-   Log candidates, scores, and chosen path for offline tuning (not to end users).

-   Combine with Planning (create step lists), Tool Use (calculators, RAG), and Reflection (post-hoc critique).


## Sample Code (Java)

```java
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Function;

/** ---------- Contracts ---------- */
interface LlmClient {
    /** Return a model completion given a role/system and a user prompt. */
    String complete(String system, String user);
}

class Candidate {
    final String answer;   // user-facing answer (no private chain-of-thought)
    final double score;    // verifier score 0..1
    Candidate(String answer, double score) { this.answer = answer; this.score = score; }
}

/** ---------- Reasoning strategies ---------- */
interface ReasoningStrategy {
    String name();
    List<Candidate> solve(String task, int budgetN, LlmClient llm, Function<String, Double> verifier);
}

/** Strategy 1: Chain-of-Thought single pass with verification */
class CoTStrategy implements ReasoningStrategy {
    public String name() { return "cot"; }
    public List<Candidate> solve(String task, int budgetN, LlmClient llm, Function<String, Double> verifier) {
        String system = "You solve problems by outlining steps privately, then provide ONLY the final answer.";
        String user = "Task: " + task + "\nReturn just the final result.";
        String finalAns = llm.complete(system, user);
        return List.of(new Candidate(finalAns, verifier.apply(finalAns)));
    }
}

/** Strategy 2: Self-Consistency — sample N answers and vote/score */
class SelfConsistencyStrategy implements ReasoningStrategy {
    public String name() { return "self_consistency"; }
    public List<Candidate> solve(String task, int budgetN, LlmClient llm, Function<String, Double> verifier) {
        List<Candidate> out = new ArrayList<>();
        String system = "Generate ONLY the final result. No intermediate notes.";
        for (int i = 0; i < budgetN; i++) {
            String user = "Task: " + task + "\nCandidate #" + (i+1) + " — output final answer only.";
            String ans = llm.complete(system, user);
            out.add(new Candidate(ans, verifier.apply(ans)));
        }
        return out;
    }
}

/** Strategy 3: Tree-of-Thought (beam search over intermediate proposals) */
class TreeOfThoughtStrategy implements ReasoningStrategy {
    private final int beamWidth;
    private final int maxDepth;
    public TreeOfThoughtStrategy(int beamWidth, int maxDepth) { this.beamWidth = beamWidth; this.maxDepth = maxDepth; }
    public String name() { return "tree_of_thought"; }

    public List<Candidate> solve(String task, int budgetN, LlmClient llm, Function<String, Double> verifier) {
        record Node(String text, double heuristic) {}
        List<Node> beam = new ArrayList<>();
        beam.add(new Node("Start: " + task, 0));

        for (int depth = 0; depth < maxDepth; depth++) {
            List<Node> expanded = new ArrayList<>();
            for (Node n : beam) {
                // Ask model for k next proposals (lightweight hints, not user-facing)
                for (int k = 0; k < Math.max(1, budgetN / beamWidth); k++) {
                    String system = "Propose the next step (one sentence).";
                    String user = n.text + "\nNext step:";
                    String step = llm.complete(system, user);
                    expanded.add(new Node(n.text + " -> " + step, heuristic(step)));
                }
            }
            expanded.sort((a,b) -> Double.compare(b.heuristic, a.heuristic));
            beam = expanded.subList(0, Math.min(beamWidth, expanded.size()));
        }

        // Finalization: turn top beam items into final answers and score
        List<Candidate> finals = new ArrayList<>();
        for (Node n : beam) {
            String system = "Given the internal plan, produce ONLY the final answer.";
            String user = "Plan (internal): " + n.text + "\nFinal answer:";
            String ans = llm.complete(system, user);
            finals.add(new Candidate(ans, verifier.apply(ans)));
        }
        return finals;
    }

    private double heuristic(String step) {
        // Toy heuristic: longer steps are mildly better (placeholder)
        return Math.min(1.0, Math.log(1 + step.length()) / 5.0);
    }
}

/** ---------- Orchestrator with budgets and selection ---------- */
class ReasoningOrchestrator {
    private final List<ReasoningStrategy> strategies;
    private final int parallelism;

    ReasoningOrchestrator(List<ReasoningStrategy> strategies, int parallelism) {
        this.strategies = strategies; this.parallelism = parallelism;
    }

    public Candidate solve(String task, int budgetN, LlmClient llm, Function<String, Double> verifier) {
        ExecutorService pool = Executors.newFixedThreadPool(parallelism);
        List<Future<List<Candidate>>> futures = new ArrayList<>();

        for (ReasoningStrategy s : strategies) {
            futures.add(pool.submit(() -> s.solve(task, Math.max(1, budgetN / strategies.size()), llm, verifier)));
        }

        List<Candidate> all = new ArrayList<>();
        for (Future<List<Candidate>> f : futures) {
            try { all.addAll(f.get()); } catch (Exception ignored) {}
        }
        pool.shutdownNow();

        // Pick by highest verifier score; tiebreak by shortest answer
        return all.stream()
                  .max(Comparator.<Candidate>comparingDouble(c -> c.score)
                       .thenComparingInt(c -> c.answer.length() * -1))
                  .orElse(new Candidate("No solution found.", 0));
    }
}

/** ---------- Mock LLM and Verifier for demo ---------- */
class MockLlm implements LlmClient {
    public String complete(String system, String user) {
        // Extremely naive: echoes a deterministic transform as the "final answer"
        if (user.toLowerCase().contains("final answer")) return "42";
        if (user.toLowerCase().contains("candidate")) return "42";
        if (system.toLowerCase().contains("final result")) return "42";
        return "consider steps -> compute -> 42";
    }
}

class SimpleVerifier implements Function<String, Double> {
    public Double apply(String ans) {
        // Reward exact numeric answers "42"; degrade others
        return "42".equals(ans.trim()) ? 0.95 : 0.2;
    }
}

/** ---------- Demo ---------- */
public class ReasoningTechniquesDemo {
    public static void main(String[] args) {
        LlmClient llm = new MockLlm();
        Function<String, Double> verifier = new SimpleVerifier();

        List<ReasoningStrategy> strategies = List.of(
                new CoTStrategy(),
                new SelfConsistencyStrategy(),
                new TreeOfThoughtStrategy(beamWidth = 2, maxDepth = 2)
        );

        ReasoningOrchestrator orch = new ReasoningOrchestrator(strategies, 3);
        Candidate best = orch.solve("Find the result of the hidden puzzle.", 6, llm, verifier);

        System.out.println("BEST ANSWER: " + best.answer + " (score " + best.score + ")");
    }
}
```

## Known Uses

-   Math and logic problems with unit tests or numeric verifiers.

-   Code synthesis validated by compilation, tests, and static analysis.

-   Multi-hop question answering with retrieval and factuality judges.

-   Scheduling, planning, and constraint solving with incremental search.

-   Safety-critical drafting where a critic model or rubric filters outputs.


## Related Patterns

-   **Planning:** produces step lists that reasoning strategies execute.

-   **Tool Use:** calculators and retrievers are invoked during reasoning.

-   **Parallelization:** explores multiple candidate paths concurrently.

-   **Reflection:** critiques and revises candidates before selection.

-   **Knowledge Retrieval (RAG):** supplies factual grounding for reasoning.

-   **Resource-Aware Optimization:** adapts breadth/depth of search to budgets.

-   **Human-in-the-Loop:** escalates ambiguous cases for review.
