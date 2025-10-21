
# Reflection

## Pattern Name and Classification

Reflection — behavioral/feedback pattern for agentic AI systems; a critique-and-revise loop where an evaluator reviews an artifact and the generator improves it iteratively.

## Intent

Improve solution quality and reliability by inserting structured self-evaluation or external critique between generation rounds, then revising based on concrete feedback.

## Also Known As

Self-critique; Critic–Editor; Review–Revise; Deliberate Feedback; ReAct-style “critic phase.”

## Motivation (Forces)

-   Single-shot generations often contain errors, weak reasoning, or poor formatting.

-   Longer prompts don’t guarantee adherence; feedback targeted to the artifact works better.

-   Some defects are detectable with rules or secondary models.

-   Iteration raises quality but costs tokens and time; without stop criteria it spirals.


## Applicability

Use when:

-   Outputs must meet explicit requirements (schemas, policies, acceptance tests).

-   Tasks benefit from multi-pass reasoning (math proofs, code, longform writing).

-   You can formalize checks (unit tests, validators, rubrics) that produce actionable feedback.

-   Latency/cost budgets permit 1–N refinement rounds.


## Structure

1.  **Generator** creates a draft artifact from requirements.

2.  **Evaluator** scores the draft against rules/rubrics and lists issues.

3.  **Reviser** applies fixes using evaluator feedback and requirements.

4.  **Stopper** terminates on pass/score threshold or max iterations.

5.  **Logger** records drafts, critiques, and decisions for audit and learning.


## Participants

-   **Orchestrator**: runs the loop and enforces budgets.

-   **Generator**: LLM or tool that produces the artifact.

-   **Evaluator**: rule set or LLM rubric producing scores and issues.

-   **Reviser**: same model as Generator or a specialized “editor.”

-   **Validators**: hard checks (schema, unit tests, policy).

-   **Store**: keeps drafts, critiques, metrics.


## Collaboration

Requirements → Generator (draft) → Evaluator (scores, issues) → Reviser (new draft) → Validators (pass/fail) → Stopper decides: return result or loop again.

## Consequences

**Benefits**

-   Higher accuracy and adherence to constraints.

-   Explainable improvements via explicit critiques.

-   Modular: plug in unit tests, linters, policy checks.


**Liabilities**

-   Extra latency and cost.

-   Risk of oscillation or over-editing without clear rules.

-   If the evaluator is weak or misaligned, it can entrench errors.


## Implementation (Key Points)

-   Make feedback **actionable**: numbered issues with locations and fixes.

-   Separate roles: “Evaluator” prompt differs from “Generator/Reviser” prompt.

-   Use **hard gates**: schema validation, tests, policy checks before another loop.

-   Define **stop criteria**: max rounds, score threshold, “no new issues.”

-   Keep **diff-aware** revisions (ask for minimal edits).

-   Log everything; measure “passes per round,” defect types, and time per loop.

-   Combine with **Parallelization** for best-of-N drafts before reflection, and with **Routing** to pick evaluators.


## Sample Code (Java)

```java
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.ArrayList;
import java.util.List;

// --- Abstractions ---
interface LlmClient {
    String complete(String systemPrompt, String userPrompt);
}

// Evaluator output schema
class Review {
    @JsonProperty("score") public double score;                 // 0..1
    @JsonProperty("passed") public boolean passed;              // true if acceptable
    @JsonProperty("issues") public List<String> issues = new ArrayList<>();  // actionable messages
}

// Orchestrator for Reflection
public class ReflectionLoop {
    private final LlmClient llm;
    private final ObjectMapper mapper = new ObjectMapper();

    private final double requiredScore;
    private final int maxRounds;

    public ReflectionLoop(LlmClient llm, double requiredScore, int maxRounds) {
        this.llm = llm;
        this.requiredScore = requiredScore;
        this.maxRounds = maxRounds;
    }

    public String run(String requirements) {
        String draft = generate(requirements);

        for (int round = 1; round <= maxRounds; round++) {
            Review review = evaluate(requirements, draft);

            if (review.passed || review.score >= requiredScore) {
                return draft; // Success
            }

            draft = revise(requirements, draft, review);
            // Optional: apply hard validators here (schema, tests) and fail fast if necessary
        }
        return draft; // Best effort after budget
    }

    private String generate(String req) {
        String system = "You are a precise generator that writes to spec.";
        String user = "Produce a DRAFT that satisfies these requirements:\n" + req;
        return llm.complete(system, user).trim();
    }

    private Review evaluate(String req, String draft) {
        String system = "You are an evaluator. Output STRICT JSON: "
                + "{ \"score\":0..1, \"passed\":true|false, \"issues\":[\"...\"] }. "
                + "Score quality, factuality, structure, and adherence to requirements.";
        String user = "Requirements:\n" + req + "\n\nDRAFT:\n" + draft
                + "\n\nEvaluate with actionable issues (numbered, specific). JSON only.";
        try {
            String json = llm.complete(system, user).trim();
            return mapper.readValue(json, Review.class);
        } catch (Exception e) {
            // If parsing fails, force a revise with a generic issue
            Review r = new Review();
            r.score = 0.0;
            r.passed = false;
            r.issues.add("Evaluator JSON parse error: " + e.getMessage());
            return r;
        }
    }

    private String revise(String req, String draft, Review review) {
        String system = "You are a careful reviser. Apply only necessary edits.";
        StringBuilder user = new StringBuilder();
        user.append("Requirements:\n").append(req)
            .append("\n\nCurrent DRAFT:\n").append(draft)
            .append("\n\nIssues to fix (handle all):\n");
        for (int i = 0; i < review.issues.size(); i++) {
            user.append(i + 1).append(". ").append(review.issues.get(i)).append("\n");
        }
        user.append("\nReturn a REVISED draft that fully addresses the issues. No commentary.");
        return llm.complete(system, user.toString()).trim();
    }
}

// --- Example Mock Client for local testing ---
class MockLlm implements LlmClient {
    public String complete(String systemPrompt, String userPrompt) {
        if (systemPrompt.contains("evaluator")) {
            // Toy evaluator: pass if draft contains "✔"
            boolean pass = userPrompt.contains("✔");
            return "{\"score\":" + (pass ? "0.92" : "0.55") + ",\"passed\":" + pass + ",\"issues\":"
                    + (pass ? "[]" : "[\"Add a concrete example\",\"Tighten summary\"]") + "}";
        }
        // Generator/Reviser: append a checkmark when asked to revise
        if (userPrompt.contains("Issues to fix")) {
            return "Revised draft with fixes ✔";
        }
        return "Initial draft that needs work";
    }
}

// --- Demo ---
class ReflectionDemo {
    public static void main(String[] args) {
        LlmClient llm = new MockLlm();
        ReflectionLoop loop = new ReflectionLoop(llm, 0.9, 3);
        String requirements = "Write a concise FAQ entry with one example and clear summary.";
        String result = loop.run(requirements);
        System.out.println(result);
    }
}
```

## Known Uses

-   Code generation with unit tests or static analysis between rounds.

-   Math/logic tasks using rubric-based self-consistency checks.

-   Longform writing with checklist-driven editing.

-   Data extraction refined until schema validators pass.

-   Policy-sensitive outputs audited by compliance rubrics.


## Related Patterns

-   **Prompt Chaining:** reflection steps can appear between chain stages.

-   **Parallelization:** generate multiple candidates, reflect, then select or fuse.

-   **Routing:** choose specialized evaluators for different domains.

-   **Tool Use:** couple reflection with tests, linters, schema validators.

-   **Planning:** allocate iterations and budgets per task difficulty.

-   **Memory Management:** store past critiques to bias future drafts.
