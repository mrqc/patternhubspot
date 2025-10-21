
# Multi-Agent

## Pattern Name and Classification

Multi-Agent — coordination/organizational pattern for agentic systems; multiple specialized agents collaborate (often asynchronously) via a common protocol or shared workspace to solve complex tasks.

## Intent

Divide a complex problem among specialized agents, enabling cooperation, critique, and negotiation to produce higher quality results than a single generalist agent.

## Also Known As

Society of Mind; Team of Experts; Blackboard Architecture (variant); Debate/Deliberation; Roles-and-Tools Ensemble.

## Motivation (Forces)

-   Different skills excel at different subtasks (retrieval, reasoning, coding, critique, formatting).

-   A single prompt often mixes concerns and degrades quality.

-   Collaboration and cross-checking catch errors and reduce hallucinations.

-   Coordination adds latency, cost, and failure modes if protocols are vague.


## Applicability

Use when:

-   The task is decomposable into role-specific responsibilities.

-   Independent perspectives or cross-validation improve quality (e.g., research + critique + synthesis).

-   You need resilience through redundancy (e.g., a second agent verifies or repairs outputs).

-   You can define a shared protocol or workspace (messages, schemas, blackboard).


## Structure

1.  **Coordinator/Orchestrator** manages goals, budgets, and turn-taking.

2.  **Agents (Roles)** perform domain-specific work (Researcher, Planner, Coder, Critic, Writer).

3.  **Shared Medium** for communication: message bus or blackboard with typed artifacts.

4.  **Policies** define who can publish/consume which artifacts and when to stop.

5.  **Validators** enforce schemas, guardrails, and acceptance criteria.


## Participants

-   **Coordinator**: schedules agents, enforces rules and budgets, aggregates outputs.

-   **Agents**: autonomous workers with clear capabilities and prompts/tools.

-   **Blackboard/Inbox**: shared store of artifacts, messages, and metadata.

-   **Evaluator**: optional quality gate or voting mechanism.

-   **Observer/Logger**: telemetry for traceability and improvement.


## Collaboration

Goal arrives → Coordinator posts tasks to the blackboard → Agents read relevant items, produce artifacts, and post updates → Evaluator critiques or votes → Coordinator decides next actions (spawn more tasks, request fixes, or finalize) → Final result returned.

## Consequences

**Benefits**

-   Higher quality via specialization, critique, and consensus.

-   Modular and extensible: add/remove agents without redesigning the whole system.

-   Better fault isolation: failing agents can be retried or replaced.


**Liabilities**

-   Coordination overhead and potential deadlocks or chatter.

-   Nontrivial protocols; unclear contracts create circular work or conflicts.

-   More cost and latency than a single-pass pipeline.

-   Requires observability and conflict resolution policies.


## Implementation (Key Points)

-   Define explicit **roles**, **inputs/outputs**, and **message schemas**.

-   Use a **blackboard** or **topic-based bus** with filtering to reduce noise.

-   Establish **turn-taking** or **token-based concurrency** to avoid thrashing.

-   Add **stop conditions** (score threshold, max rounds, budget caps).

-   Include **disagreement resolution**: voting, tie-breaker agent, or coordinator rules.

-   Combine with **Reflection** for critique loops and **Routing** to pick which agents run.

-   Log agent actions, rationale, and artifacts for audit and learning.


## Sample Code (Java)

```java
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Predicate;

/** ---- Messaging primitives ---- */
class Message {
    final String type;           // e.g., "TASK", "FACTS", "DRAFT", "CRITIQUE", "FINAL"
    final String from;           // agent name
    final String content;        // simple payload; use JSON in real systems
    final Instant ts = Instant.now();
    Message(String type, String from, String content) { this.type = type; this.from = from; this.content = content; }
}

class Blackboard {
    private final List<Message> messages = new CopyOnWriteArrayList<>();
    void post(Message m) { messages.add(m); }
    List<Message> query(Predicate<Message> p) { 
        List<Message> out = new ArrayList<>();
        for (Message m : messages) if (p.test(m)) out.add(m);
        return out;
    }
    Optional<Message> latest(String type) {
        return messages.stream().filter(m -> m.type.equals(type)).reduce((a,b) -> b);
    }
}

/** ---- Agent abstraction ---- */
interface Agent extends Callable<Optional<Message>> {
    String name();
}

/** ---- Concrete agents (stubs) ---- */

// Researcher: collects supporting facts for the task
class ResearchAgent implements Agent {
    private final Blackboard bb;
    ResearchAgent(Blackboard bb) { this.bb = bb; }
    public String name() { return "researcher"; }
    public Optional<Message> call() {
        Optional<Message> task = bb.latest("TASK");
        if (task.isEmpty()) return Optional.empty();
        // Pretend retrieval with a deterministic summary
        String facts = "Facts: {trend: 'EV sales up', source: 'Q3 report', risk: 'supply chain'}";
        return Optional.of(new Message("FACTS", name(), facts));
    }
}

// Writer: synthesizes a draft using facts
class WriterAgent implements Agent {
    private final Blackboard bb;
    WriterAgent(Blackboard bb) { this.bb = bb; }
    public String name() { return "writer"; }
    public Optional<Message> call() {
        Optional<Message> facts = bb.latest("FACTS");
        if (facts.isEmpty()) return Optional.empty();
        String draft = "Draft report: " + facts.get().content + " → concise narrative ✔";
        return Optional.of(new Message("DRAFT", name(), draft));
    }
}

// Critic: reviews the draft and emits issues or approval
class CriticAgent implements Agent {
    private final Blackboard bb;
    CriticAgent(Blackboard bb) { this.bb = bb; }
    public String name() { return "critic"; }
    public Optional<Message> call() {
        Optional<Message> draft = bb.latest("DRAFT");
        if (draft.isEmpty()) return Optional.empty();
        String critique = draft.get().content.contains("concise")
                ? "OK: clear summary; Add numeric figures."
                : "Issues: structure unclear; add summary.";
        return Optional.of(new Message("CRITIQUE", name(), critique));
    }
}

// Editor: applies critique to produce final
class EditorAgent implements Agent {
    private final Blackboard bb;
    EditorAgent(Blackboard bb) { this.bb = bb; }
    public String name() { return "editor"; }
    public Optional<Message> call() {
        Optional<Message> draft = bb.latest("DRAFT");
        Optional<Message> critique = bb.latest("CRITIQUE");
        if (draft.isEmpty() || critique.isEmpty()) return Optional.empty();
        String finalText = draft.get().content + " Added figures: EV +18% YoY. (" + critique.get().content + ")";
        return Optional.of(new Message("FINAL", name(), finalText));
    }
}

/** ---- Coordinator ---- */
class Coordinator {
    private final ExecutorService pool = Executors.newFixedThreadPool(4);
    private final Blackboard bb;
    private final List<Agent> agents;
    private final int maxRounds;

    Coordinator(Blackboard bb, List<Agent> agents, int maxRounds) {
        this.bb = bb; this.agents = agents; this.maxRounds = maxRounds;
    }

    public String run(String goal) throws Exception {
        bb.post(new Message("TASK", "user", goal));

        for (int round = 1; round <= maxRounds; round++) {
            List<Future<Optional<Message>>> futures = new ArrayList<>();
            for (Agent a : agents) futures.add(pool.submit(a));

            // Collect results this round
            for (Future<Optional<Message>> f : futures) {
                try {
                    Optional<Message> m = f.get(500, TimeUnit.MILLISECONDS);
                    m.ifPresent(bb::post);
                } catch (TimeoutException te) {
                    // agent missed its slot; skip
                }
            }
            // Stop if final exists
            Optional<Message> fin = bb.latest("FINAL");
            if (fin.isPresent()) return fin.get().content;
        }
        return bb.latest("DRAFT").map(m -> m.content).orElse("No result");
    }
}

/** ---- Demo ---- */
public class MultiAgentDemo {
    public static void main(String[] args) throws Exception {
        Blackboard bb = new Blackboard();
        List<Agent> agents = List.of(
            new ResearchAgent(bb),
            new WriterAgent(bb),
            new CriticAgent(bb),
            new EditorAgent(bb)
        );
        Coordinator coord = new Coordinator(bb, agents, 5);
        String result = coord.run("Create a short Q3 EV market summary for executives.");
        System.out.println(result);
    }
}
```

## Known Uses

-   Research-and-write workflows: researcher → writer → critic → editor → final.

-   Code generation: planner → coder → tester → fixer → packager.

-   Retrieval ensembles: multiple retrievers vote, then a synthesizer fuses results.

-   Debate/Deliberation agents that argue pros/cons and a judge selects the winner.

-   Customer support: triage agent, policy agent, resolution agent, supervisor.


## Related Patterns

-   **Planning:** defines the task-level DAG that multiple agents execute.

-   **Routing:** dispatches tasks to the right agent or subset of agents.

-   **Parallelization:** runs agents concurrently when independent.

-   **Reflection:** uses critic/judge agents to evaluate artifacts and request fixes.

-   **Tool Use:** each agent may invoke external tools within its role.

-   **Prompt Chaining:** agents themselves can chain internal steps before publishing.
