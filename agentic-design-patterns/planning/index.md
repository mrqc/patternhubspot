
# Planning

## Pattern Name and Classification

Planning — coordination/behavioral pattern for agentic AI systems; derives a task-level plan (steps, ordering, budgets, tools) before or during execution.

## Intent

Turn a fuzzy goal into an explicit, executable sequence of steps with dependencies, success criteria, and budgets so the agent can act methodically instead of winging it.

## Also Known As

Task Decomposition; Deliberate Planning; Plan-and-Execute; Think-Act; ReAct-with-Plans.

## Motivation (Forces)

-   Complex tasks require multiple tools, intermediate artifacts, and validations.

-   Monolithic prompts drift, ignore constraints, or blow context limits.

-   Budgets exist: tokens, latency, money, API quotas.

-   Environments change mid-run; plans must adapt.  
    Planning provides a blueprint the system can monitor, revise, and explain.


## Applicability

Use when:

-   The task spans multiple phases (gather → analyze → verify → deliver).

-   There are dependencies or branching conditions.

-   You need traceability, checkpoints, or human review.

-   Cost/latency must be controlled with explicit budgets.

-   Multiple tools or agents must be orchestrated coherently.


## Structure

1.  **Goal/Constraints** → natural language or structured brief.

2.  **Planner** → produces a **Plan**: steps, dependencies, exit conditions, budgets.

3.  **Executor** → runs steps, tracks state, emits artifacts and metrics.

4.  **Monitor** → observes progress, failures, and budget consumption.

5.  **Replanner** → adjusts plan based on outcomes or new info.

6.  **Policies** → safety, compliance, and approval gates.


## Participants

-   **Planner**: turns goals into an ordered DAG of steps.

-   **Plan**: the artifact with steps, inputs/outputs, and acceptance criteria.

-   **Executor**: runs steps, handles retries/timeouts.

-   **Tools/Agents**: do the actual work inside steps.

-   **Monitor/Logger**: telemetry, budgets, and audit.

-   **Replanner**: edits plan when steps fail or context shifts.

-   **Reviewer**: optional human-in-the-loop at gates.


## Collaboration

Goal arrives → Planner drafts Plan → Executor runs next ready step(s) → Monitor records outcomes and budgets → If a step fails or context changes, Replanner modifies plan → Iterate until acceptance criteria are met or budgets exhausted.

## Consequences

**Benefits**

-   Predictability and transparency of multi-step work.

-   Better budget control and error localization.

-   Easier human oversight via explicit checkpoints.


**Liabilities**

-   Upfront overhead; plan quality depends on the planner.

-   Risk of stale plans if not adapted during execution.

-   More components to implement and test.


## Implementation (Key Points)

-   Represent plans as a typed structure (steps with ids, inputs, outputs, tool bindings, acceptance criteria, cost/latency budgets).

-   Keep the plan small and editable; support insert, delete, and reorder operations.

-   Validate step boundaries with schemas; attach preconditions and postconditions.

-   Support branches: conditional steps, parallel blocks, and join nodes.

-   Log plan versions and diffs; include rationale for each step.

-   Add stop conditions: max steps, max cost, max wall time.

-   Combine with Reflection to critique and refine the plan after each milestone; with Routing to pick specialized executors; with Parallelization for independent steps.


## Sample Code (Java)

```java
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Supplier;

/** ---------- Plan model ---------- */
class Plan {
    final String goal;
    final List<Step> steps = new ArrayList<>();
    final double maxCostUsd;
    final Duration maxWallTime;

    Plan(String goal, double maxCostUsd, Duration maxWallTime) {
        this.goal = goal;
        this.maxCostUsd = maxCostUsd;
        this.maxWallTime = maxWallTime;
    }
}

enum StepState { PENDING, RUNNING, SUCCEEDED, FAILED, SKIPPED }

class Step {
    final String id;
    final String description;
    final List<String> dependsOn = new ArrayList<>();
    final Supplier<StepResult> action;   // Bind to a tool/agent
    volatile StepState state = StepState.PENDING;
    volatile StepResult lastResult;

    Step(String id, String description, Supplier<StepResult> action) {
        this.id = id;
        this.description = description;
        this.action = action;
    }

    Step depends(String... ids) { dependsOn.addAll(Arrays.asList(ids)); return this; }
}

class StepResult {
    final boolean ok;
    final String output;     // Could be JSON or typed object
    final double costUsd;
    StepResult(boolean ok, String output, double costUsd) {
        this.ok = ok; this.output = output; this.costUsd = costUsd;
    }
}

/** ---------- Planner ---------- */
interface Planner {
    Plan makePlan(String goal, Map<String, Object> constraints);
}

class SimplePlanner implements Planner {
    public Plan makePlan(String goal, Map<String, Object> c) {
        double budget = (double) c.getOrDefault("budgetUsd", 0.50);
        Duration maxTime = (Duration) c.getOrDefault("maxWallTime", Duration.ofSeconds(10));
        Plan plan = new Plan(goal, budget, maxTime);

        // Example: summarize → retrieve → synthesize
        plan.steps.add(new Step("summarize", "Summarize requirements",
                Tools.mockLlm("Summarized: " + goal, 0.05)));

        plan.steps.add(new Step("retrieve", "Retrieve supporting facts",
                Tools.search("facts for: " + goal, 0.10)).depends("summarize"));

        plan.steps.add(new Step("synthesize", "Write final answer",
                Tools.mockLlm("Final answer for: " + goal, 0.20)).depends("retrieve"));

        return plan;
    }
}

/** ---------- Executor + Monitor + Replanner ---------- */
class PlanExecutor {
    private final ExecutorService pool = Executors.newFixedThreadPool(4);

    public String execute(Plan plan) throws Exception {
        long deadline = System.nanoTime() + plan.maxWallTime.toNanos();
        double spent = 0.0;
        Map<String, Step> byId = new HashMap<>();
        for (Step s : plan.steps) byId.put(s.id, s);

        while (true) {
            if (System.nanoTime() > deadline) throw new TimeoutException("Plan deadline reached");
            boolean progress = false;

            // Run any ready steps (all deps succeeded)
            for (Step s : plan.steps) {
                if (s.state == StepState.PENDING && depsOk(s, byId)) {
                    if (spent >= plan.maxCostUsd) throw new IllegalStateException("Budget exceeded");
                    s.state = StepState.RUNNING;
                    Future<StepResult> f = runAsync(s.action);
                    try {
                        StepResult r = f.get(3, TimeUnit.SECONDS);
                        s.lastResult = r;
                        spent += r.costUsd;
                        s.state = r.ok ? StepState.SUCCEEDED : StepState.FAILED;

                        // Simple replanning: if retrieve fails, skip synthesize
                        if (!r.ok && s.id.equals("retrieve")) {
                            Step synth = byId.get("synthesize");
                            if (synth != null && synth.state == StepState.PENDING) {
                                synth.state = StepState.SKIPPED;
                            }
                        }
                    } catch (TimeoutException te) {
                        s.state = StepState.FAILED;
                    }
                    progress = true;
                }
            }

            // Done when all steps are terminal
            if (plan.steps.stream().allMatch(PlanExecutor::terminal)) break;
            if (!progress) Thread.sleep(20);
        }

        Optional<Step> last = plan.steps.stream()
                .filter(s -> s.id.equals("synthesize") && s.state == StepState.SUCCEEDED).findFirst();
        return last.map(s -> s.lastResult.output).orElse("No final result.");
    }

    private static boolean depsOk(Step s, Map<String, Step> byId) {
        for (String dep : s.dependsOn) {
            Step d = byId.get(dep);
            if (d == null || d.state != StepState.SUCCEEDED) return false;
        }
        return true;
    }

    private static boolean terminal(Step s) {
        return s.state == StepState.SUCCEEDED || s.state == StepState.FAILED || s.state == StepState.SKIPPED;
    }

    private <T> Future<T> runAsync(Supplier<T> supplier) {
        return ((ExecutorService) pool).submit(supplier::get);
    }
}

/** ---------- Tools (stubs) ---------- */
class Tools {
    static Supplier<StepResult> mockLlm(String response, double cost) {
        return () -> new StepResult(true, response + " ✔", cost);
    }
    static Supplier<StepResult> search(String query, double cost) {
        return () -> new StepResult(true, "SearchResults(" + query + ")", cost);
    }
}

/** ---------- Demo ---------- */
public class PlanningDemo {
    public static void main(String[] args) throws Exception {
        Planner planner = new SimplePlanner();
        Map<String, Object> constraints = new HashMap<>();
        constraints.put("budgetUsd", 0.40);
        constraints.put("maxWallTime", Duration.ofSeconds(5));

        Plan plan = planner.makePlan("Explain EV market trends Q3 2025", constraints);
        PlanExecutor exec = new PlanExecutor();
        String result = exec.execute(plan);
        System.out.println(result);
    }
}
```

## Known Uses

-   Plan-and-execute agents decomposing research/writing tasks into discrete steps.

-   Data workflows: ingest → validate → enrich → aggregate → publish with gates.

-   Codegen with tests: outline → scaffold → implement → test → fix → package.

-   Retrieval pipelines: formulate queries → retrieve → rank → synthesize.

-   Customer support: triage → gather context → propose resolution → verify → send.


## Related Patterns

-   **Prompt Chaining:** executes the planned steps sequentially.

-   **Routing:** selects specialized agents/tools for each planned step.

-   **Parallelization:** runs independent plan branches concurrently.

-   **Tool Use:** plans specify which tools to call and with what arguments.

-   **Reflection:** critiques plan quality or step outputs and revises them.

-   **Memory Management:** stores plan state, artifacts, and rationales for reuse.
