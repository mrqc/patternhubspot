# Prompt Chaining

## Pattern Name and Classification

Prompt Chaining — Behavioral/process pattern for Agentic AI systems; a sequential decomposition technique where each step’s output becomes the next step’s input.

Agentic Design Patterns - Googl…

## Intent

Split a complex task into a series of focused prompts and deterministic checks so the system advances step by step with higher reliability and control.

Agentic Design Patterns - Googl…

## Also Known As

Pipeline; Sequential Decomposition; Stepwise Refinement.

Agentic Design Patterns - Googl…

## Motivation (Forces)

Single, monolithic prompts often fail under cognitive load: instruction neglect, context drift, long-context limits, error propagation, and hallucinations. Breaking the task into smaller stages reduces ambiguity, improves debuggability, and allows structured outputs and tool calls between steps.

Agentic Design Patterns - Googl…

## Applicability

Use when:

-   A task has multiple distinct phases (extract → analyze → synthesize → format).

-   You need structured handoffs (e.g., JSON) between stages.

-   External tools or validations must be interleaved with model calls.

-   You want auditable traces and fine-grained error handling.

    Agentic Design Patterns - Googl…


## Structure

1.  Step N prompt: narrowly scoped instruction.

2.  Validator/transformer: check format, coerce types, enrich context.

3.  Next step consumes the validated output.  
    This repeats until a final synthesis/formatting step produces the deliverable.

    Agentic Design Patterns - Googl…


## Participants

-   **Orchestrator**: runs the chain, routes outputs to the next step, manages retries.

-   **Prompted Steps**: focused LLM calls with minimal context.

-   **Guards/Validators**: schema checks, business rules, tool outputs.

-   **State Store**: carries intermediate artifacts and metadata.

-   **External Tools/APIs**: calculators, search, RAG, etc., called between prompts.

    Agentic Design Patterns - Googl…


## Collaboration

Each step emits structured data for deterministic parsing; validators fix or reject malformed outputs; the orchestrator advances only on valid handoffs. Role prompts can shift per step (e.g., “Analyst,” then “Writer”).

Agentic Design Patterns - Googl…

## Consequences

**Benefits**

-   Higher reliability, modularity, and explainability.

-   Easier debugging and targeted retries.

-   Clean integration points for tools and guards.


**Liabilities**

-   More latency and cost across multiple calls.

-   Interface brittleness if schemas aren’t enforced.

-   Residual error propagation if validation is weak.

    Agentic Design Patterns - Googl…


## Implementation (Key Points)

-   Decompose by capabilities, not paragraphs. Keep each step’s prompt short and role-specific.

-   Enforce output schemas (JSON/XML) and reject free-form text at boundaries.

-   Insert deterministic code between steps for validation, normalization, and tool use.

-   Add retries with backoff and step-local guardrails; log every handoff for traceability.

-   Combine with **Parallelization** for independent subtasks and **Routing** for conditional branches.

-   Version steps and prompts; keep a contract (schema) for each handoff.

    Agentic Design Patterns - Googl…


## Sample Code (Java)

```java
import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.*;

// Minimal LLM client abstraction.
interface LlmClient {
    String complete(String systemPrompt, String userPrompt);
}

// DTOs for structured handoffs.
class TrendsRequest {
    @JsonProperty("summary")
    public String summary;
}
class TrendItem {
    @JsonProperty("trend_name") public String trendName;
    @JsonProperty("supporting_data") public String supportingData;
}
class TrendsResponse {
    @JsonProperty("trends") public List<TrendItem> trends = new ArrayList<>();
}

public class PromptChainingPipeline {
    private final LlmClient llm;
    private final ObjectMapper mapper = new ObjectMapper();

    public PromptChainingPipeline(LlmClient llm) { this.llm = llm; }

    public String run(String reportText) throws Exception {
        // Step 1: Summarization
        String summary = summarize(reportText);

        // Step 2: Trend identification -> JSON
        TrendsResponse trends = extractTrends(summary);

        // Step 3: Compose email from structured trends
        return composeEmail(trends);
    }

    private String summarize(String report) {
        String system = "You are a precise market analyst. Output a concise summary.";
        String user = "Summarize the key findings of this report:\n\n" + report;
        String out = llm.complete(system, user).trim();
        // Basic guardrail
        if (out.length() < 40) throw new IllegalStateException("Summary too short");
        return out;
    }

    private TrendsResponse extractTrends(String summary) throws Exception {
        String system = "You extract trends. Output STRICT JSON with keys: trends:[{trend_name, supporting_data}]";
        String user = "From this summary, list the top 3 trends with supporting data. JSON only:\n" + summary;
        String json = llm.complete(system, user).trim();

        // Validation: parse JSON and ensure at least one trend
        TrendsResponse resp = mapper.readValue(json, TrendsResponse.class);
        if (resp.trends == null || resp.trends.isEmpty()) {
            throw new IllegalStateException("No trends extracted");
        }
        // Optional: sanitize fields, enforce length limits, etc.
        return resp;
    }

    private String composeEmail(TrendsResponse trends) {
        StringBuilder sb = new StringBuilder();
        sb.append("Subject: Market Trends Summary\n\n");
        sb.append("Team,\n\nHere are the key trends:\n");
        for (TrendItem t : trends.trends) {
            sb.append("- ").append(t.trendName).append(": ").append(t.supportingData).append("\n");
        }
        sb.append("\nBest,\nAnalytics");
        return sb.toString();
    }
}
```

*Notes:* this illustrates strict handoffs: unstructured → summary text → validated JSON → final prose. Insert real schema validation or JSON Schema as needed; add retries/backoffs around `complete`. The same skeleton adapts to extraction, OCR post-processing, code-gen pipelines, etc.

Agentic Design Patterns - Googl…

## Known Uses

-   Information processing pipelines: extract → summarize → entity pick → search → report.

-   Complex question answering with staged retrieval and synthesis.

-   Data extraction from invoices/forms with iterative fixes and external calculators.

-   Content generation workflows: ideate → outline → draft → review.

-   Conversational agents maintaining state over turns.

-   Code generation and refinement with static analysis and tests between steps.

    Agentic Design Patterns - Googl…


## Related Patterns

Routing; Parallelization; Tool Use; Planning; Reflection; Memory Management; Model Context Protocol (MCP). Chaining often coexists with routing for conditional branches and with parallelization for independent subtasks.

Agentic Design Patterns - Googl…
