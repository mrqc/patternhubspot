
# Parallelization

## Pattern Name and Classification

Parallelization — behavioral/concurrency pattern for agentic systems; fan-out/fan-in execution where multiple independent steps or candidates run concurrently and are merged into a single outcome.

## Intent

Reduce latency and increase robustness by executing independent subtasks at the same time and aggregating their results with a deterministic merge policy.

## Also Known As

Scatter–Gather, Fan-out/Fan-in, Map–Reduce (conceptual), Ensembles, Hedged Requests (variant).

## Motivation (Forces)

-   **Tail latency hurts UX.** Single long steps dominate total response time.

-   **Specialization varies.** Different prompts/tools/models excel on different inputs.

-   **Stochastic outputs.** Multiple samples can improve quality via selection/consensus.

-   **Unreliable components.** Running backups/hedges reduces failure risk.

-   **Budgets exist.** Concurrency competes with cost, rate limits, and context limits.  
    Parallelization addresses latency and variance by exploring several paths at once and then merging them under a clear policy.


## Applicability

Use when:

-   Subtasks are independent or share-nothing after a split (retrieval across shards, multi-tool probing, multi-prompt candidates).

-   You need multiple candidates for selection (best-of-N, self-consistency).

-   Hedging improves reliability (race identical requests with small stagger).

-   You can bound concurrency within cost/rate limits.  
    Avoid when subtasks are tightly coupled or require strict global ordering.


## Structure

1.  **Splitter:** partitions work into independent units or candidate prompts.

2.  **Workers:** execute units concurrently (tools, models, agents).

3.  **Budget/Rate Governor:** enforces max concurrency and cost ceilings.

4.  **Merger:** deterministically combines outputs (rank, vote, stitch).

5.  **Timeout/Cancel Manager:** cancels stragglers after quorum or deadline.


## Participants

-   **Orchestrator:** owns lifecycle, telemetry, and error handling.

-   **Workers/Tools/Models:** perform actual subtasks.

-   **Merge Policy:** best-score, majority vote, quorum, or structured stitching.

-   **Guardrails:** validators, schema checkers.

-   **Observability:** traces timing, cost, and win rates per worker.


## Collaboration

Input arrives → Splitter produces K tasks/candidates → Workers run concurrently within budget → Results stream back → Merger applies policy (e.g., first-wins after quality threshold, or highest score) → Orchestrator cancels remaining tasks and returns the merged result.

## Consequences

**Benefits**

-   Lower end-to-end latency; hides stragglers.

-   Higher quality via best-of-N or consensus.

-   Greater resilience against flaky tools.


**Liabilities**

-   Higher cost and rate-limit pressure.

-   Nontrivial merging logic; risk of inconsistent stitching.

-   More moving parts to monitor and tune.


## Implementation (Key Points)

-   Keep tasks **idempotent** and side-effect free; otherwise parallel runs fight each other.

-   Enforce **bounded concurrency**; prefer a token bucket or fixed pool.

-   Set **timeouts** and **or-cancel** remaining tasks once a quorum/threshold is reached.

-   Choose a **merge policy** up front: first-wins, highest score, majority, weighted blend, RRF for retrieval.

-   Validate outputs at fan-in boundaries; reject or repair malformed results.

-   Record per-worker latency, error rate, and win rate to guide pruning.

-   For hedged requests: send a backup after a small delay to cut tail latency; cancel losers.


## Sample Code (Java)

```java
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Function;

/** Result object with a simple quality score. */
class Result {
    final String source;
    final String content;
    final double score; // higher is better
    Result(String source, String content, double score) {
        this.source = source; this.content = content; this.score = score;
    }
    @Override public String toString() {
        return "[from=" + source + ", score=" + score + "] " + content;
    }
}

/** Worker abstraction: run a task and produce a Result. */
interface Worker extends Callable<Result> {
    String name();
}

/** Example workers simulating different tools/models. */
class FastButNoisy implements Worker {
    private final String input;
    FastButNoisy(String input) { this.input = input; }
    public String name() { return "fast_noisy"; }
    @Override public Result call() throws Exception {
        Thread.sleep(80); // fast
        return new Result(name(), "Draft: " + input.toUpperCase(), Math.random() * 0.7 + 0.1);
    }
}
class AccurateButSlow implements Worker {
    private final String input;
    AccurateButSlow(String input) { this.input = input; }
    public String name() { return "accurate_slow"; }
    @Override public Result call() throws Exception {
        Thread.sleep(250); // slow
        return new Result(name(), "Refined: " + input + " ✔", 0.85 + Math.random() * 0.1);
    }
}
class RetrieverShard implements Worker {
    private final String input; private final int shardId;
    RetrieverShard(String input, int shardId) { this.input = input; this.shardId = shardId; }
    public String name() { return "retriever_shard_" + shardId; }
    @Override public Result call() throws Exception {
        Thread.sleep(100 + shardId * 30);
        return new Result(name(), "Snippet@" + shardId + " for " + input, 0.6 + Math.random() * 0.3);
    }
}

/** Merge policies. */
class MergePolicies {
    static Function<List<Result>, Result> highestScore() {
        return results -> results.stream().max(Comparator.comparingDouble(r -> r.score)).orElse(null);
    }
    static Function<List<Result>, Result> firstAbove(double threshold) {
        return results -> results.stream().filter(r -> r.score >= threshold).findFirst().orElse(null);
    }
}

/** Parallelizer with bounded concurrency, timeout, and early cancel after quorum. */
class Parallelizer implements AutoCloseable {
    private final ExecutorService pool;
    Parallelizer(int maxConcurrency) { this.pool = Executors.newFixedThreadPool(maxConcurrency); }

    public Result run(List<Worker> workers,
                      Duration timeout,
                      Function<List<Result>, Result> merger,
                      Optional<Double> earlyThreshold) throws InterruptedException {

        List<Future<Result>> futures = new ArrayList<>();
        List<Result> received = Collections.synchronizedList(new ArrayList<>());

        try {
            // Fan-out
            for (Worker w : workers) {
                futures.add(pool.submit(() -> {
                    Result r = w.call();
                    received.add(r);
                    return r;
                }));
            }

            long deadline = System.nanoTime() + timeout.toNanos();

            // Poll futures until timeout, with optional early stop when a good result appears
            while (System.nanoTime() < deadline) {
                boolean allDone = true;
                for (Future<Result> f : futures) {
                    if (!f.isDone()) { allDone = false; continue; }
                }
                // Early stop: as soon as someone beats the threshold
                if (earlyThreshold.isPresent()) {
                    Result early = received.stream()
                            .filter(r -> r.score >= earlyThreshold.get())
                            .findFirst().orElse(null);
                    if (early != null) {
                        cancelAll(futures);
                        return early;
                    }
                }
                if (allDone) break;
                Thread.sleep(10);
            }

            // Timeout reached; cancel stragglers
            cancelAll(futures);

            // Fan-in with chosen merge policy
            if (received.isEmpty()) throw new TimeoutException("No results before deadline");
            Result merged = merger.apply(received);
            if (merged == null) throw new IllegalStateException("Merge produced null");
            return merged;

        } catch (Exception e) {
            cancelAll(futures);
            throw new RuntimeException("Parallelization failed: " + e.getMessage(), e);
        }
    }

    private void cancelAll(List<Future<Result>> futures) {
        for (Future<Result> f : futures) { if (!f.isDone()) f.cancel(true); }
    }

    @Override public void close() { pool.shutdownNow(); }
}

/** Demo */
public class ParallelizationDemo {
    public static void main(String[] args) throws Exception {
        String task = "summarize quarterly report on EV sales";
        List<Worker> workers = Arrays.asList(
                new FastButNoisy(task),
                new AccurateButSlow(task),
                new RetrieverShard(task, 1),
                new RetrieverShard(task, 2)
        );

        try (Parallelizer p = new Parallelizer(4)) {
            // Option A: early return when any result exceeds 0.9
            Result early = p.run(workers, Duration.ofMillis(600),
                    MergePolicies.highestScore(),
                    Optional.of(0.90));
            System.out.println("EARLY or BEST: " + early);

            // Option B: strict highest-score within 400 ms, no early threshold
            Result best = p.run(workers, Duration.ofMillis(400),
                    MergePolicies.highestScore(),
                    Optional.empty());
            System.out.println("BEST WITHIN BUDGET: " + best);
        }
    }
}
```

## Known Uses

-   Best-of-N prompting and self-consistency decoding.

-   Retrieval over sharded indexes with reciprocal rank fusion at merge.

-   Multi-tool probing (calculator, code interpreter, web search) and picking the best.

-   Hedged requests to reduce tail latency in flaky networks.

-   Ensemble inferencing across small/large models with rank-and-select.


## Related Patterns

-   **Routing:** chooses which branches to run; can fan out to multiple destinations.

-   **Prompt Chaining:** runs sequential steps that may include parallel substeps.

-   **Tool Use:** workers are concrete tools invoked concurrently.

-   **Planning:** planner decides when and how much to fan out.

-   **Reflection:** evaluates multiple candidates and feeds back improvements.

-   **Memory Management:** prior successes can bias which workers are included.
