# Routing

## Pattern Name and Classification

**Routing** — a behavioral coordination pattern for agentic AI systems that dynamically directs an input, query, or task to the most appropriate agent, model, or tool based on content, intent, or context.

---

## Intent

Determine *where* to send a request among multiple possible agents or processes so that each input is handled by the most capable or cost-efficient resource.

---

## Also Known As

Intent Routing, Dispatching, Skill Selection, Dynamic Delegation.

---

## Motivation (Forces)

In complex AI systems, one model or prompt rarely fits all. Some models reason better, others retrieve facts faster, and some tools are task-specific. Without routing, every request goes through the same pipeline, wasting resources or producing nonsense when an input doesn’t fit the expected domain.  
Key forces include:

-   **Diversity of skills:** different agents specialize in tasks (math, code, writing, search).

-   **Efficiency vs accuracy:** large models are costly but precise; small ones are cheap but narrow.

-   **Safety and compliance:** sensitive inputs may require guarded paths.

-   **Context length and latency constraints.**


Routing balances these factors by deciding which “path” each request takes.

---

## Applicability

Use Routing when:

-   Multiple agents or tools exist with distinct capabilities or modalities.

-   Inputs differ by intent or type (question, code, command, text, image).

-   Performance, cost, or latency must be optimized dynamically.

-   You need guardrails (content filters, policy rules) before delegation.

-   The system evolves, and you want to plug in new tools without rewriting core logic.


---

## Structure

1.  **Classifier** — inspects or labels input (intent detection, topic classification).

2.  **Policy Engine** — applies deterministic or probabilistic rules to decide destination.

3.  **Router** — central coordinator executing the decision logic.

4.  **Destinations** — the agents, models, or APIs handling the work.

5.  **Fallbacks** — default route when confidence is too low or classification fails.


---

## Participants

-   **Router:** Orchestrates classification, routing, and fallback.

-   **Classifier:** Evaluates the request and predicts its intent or type.

-   **Policy Engine:** Encapsulates routing rules and thresholds.

-   **Destination Agents:** Specialized executors or tools.

-   **Fallback Handler:** Safe default for unknown or failed routes.

-   **Monitor:** Logs routing decisions for auditing and feedback learning.


---

## Collaboration

1.  The **Classifier** analyzes the input and assigns an intent label with a confidence score.

2.  The **Policy Engine** evaluates the label and confidence against routing rules.

3.  The **Router** dispatches the input to the selected **Destination Agent**.

4.  The **Destination Agent** executes the task and returns the result.

5.  The **Monitor** records the routing outcome for continuous refinement.


---

## Consequences

**Benefits**

-   Enables modular, extensible system design.

-   Increases efficiency and accuracy by matching inputs to expertise.

-   Facilitates scaling with new tools or models.

-   Improves safety by isolating risky or ambiguous inputs.


**Liabilities**

-   Added architectural complexity and latency.

-   Misclassification risk can route tasks incorrectly.

-   Requires monitoring, logging, and retraining of classifier models.

-   Difficult to test fully when routing space grows.


---

## Implementation (Key Points)

-   Begin with a small set of routes and expand incrementally.

-   Use confidence thresholds and abstain logic to trigger fallbacks.

-   Keep routing logic deterministic and auditable (rules before heuristics).

-   Incorporate feedback loops to retrain classification models.

-   Log every routing decision (input, intent, destination, confidence).

-   Implement circuit breakers to avoid cascading errors.

-   Combine static rules (regex, keyword) with learned models (embeddings, fine-tuned classifiers).


---

## Sample Code (Java)

```java
import java.util.*;
import java.util.function.Predicate;

// --- Core abstractions ---
interface Agent {
    String name();
    String handle(String input);
}

class Router {
    private final List<RouteRule> rules;
    private final Agent fallback;

    Router(List<RouteRule> rules, Agent fallback) {
        this.rules = rules;
        this.fallback = fallback;
    }

    public String route(String input) {
        for (RouteRule rule : rules) {
            if (rule.matches(input)) {
                return rule.destination().handle(input);
            }
        }
        return fallback.handle(input);
    }
}

class RouteRule {
    private final Predicate<String> condition;
    private final Agent destination;

    RouteRule(Predicate<String> condition, Agent destination) {
        this.condition = condition;
        this.destination = destination;
    }

    public boolean matches(String input) {
        return condition.test(input);
    }

    public Agent destination() {
        return destination;
    }
}

// --- Example agents ---
class MathAgent implements Agent {
    public String name() { return "MathAgent"; }
    public String handle(String input) {
        try {
            String expr = input.replaceAll("[^0-9+\\-*/.]", "");
            double result = (double) new javax.script.ScriptEngineManager()
                    .getEngineByName("JavaScript")
                    .eval(expr);
            return "Result: " + result;
        } catch (Exception e) {
            return "Math error: " + e.getMessage();
        }
    }
}

class CodeAgent implements Agent {
    public String name() { return "CodeAgent"; }
    public String handle(String input) {
        return "Analyzing code issue: " + input;
    }
}

class SearchAgent implements Agent {
    public String name() { return "SearchAgent"; }
    public String handle(String input) {
        return "Searching web for: " + input;
    }
}

class FallbackAgent implements Agent {
    public String name() { return "FallbackAgent"; }
    public String handle(String input) {
        return "Fallback: unable to classify \"" + input + "\"";
    }
}

// --- Demo ---
public class RoutingDemo {
    public static void main(String[] args) {
        Agent math = new MathAgent();
        Agent code = new CodeAgent();
        Agent search = new SearchAgent();
        Agent fallback = new FallbackAgent();

        List<RouteRule> rules = Arrays.asList(
                new RouteRule(s -> s.matches(".*\\d+.*[+\\-*/].*\\d+.*"), math),
                new RouteRule(s -> s.toLowerCase().contains("java")
                               || s.toLowerCase().contains("python"), code),
                new RouteRule(s -> s.toLowerCase().contains("who is")
                               || s.toLowerCase().contains("find"), search)
        );

        Router router = new Router(rules, fallback);

        List<String> inputs = Arrays.asList(
                "What is 15 * 3?",
                "How to fix NullPointerException in Java?",
                "Who is the founder of OpenAI?",
                "Tell me a joke"
        );

        for (String input : inputs) {
            System.out.println("> " + input);
            System.out.println(router.route(input));
            System.out.println();
        }
    }
}
```

---

## Known Uses

-   Tool selection in LLM orchestration frameworks (e.g., calculator, search, code agent).

-   Customer service systems routing tickets by intent or sentiment.

-   Hybrid retrieval systems switching between local and external data sources.

-   Model ensembles where tasks are dispatched to different LLMs based on complexity.

-   Safety layers selecting “safe” execution contexts for untrusted inputs.


---

## Related Patterns

-   **Prompt Chaining:** routing often precedes chaining to select which chain to run.

-   **Parallelization:** explore multiple routes simultaneously and aggregate results.

-   **Tool Use:** routing decides which tool is invoked.

-   **Planning:** high-level coordination that may include routing as a subtask.

-   **Reflection:** feedback loop that can re-route tasks when previous routes fail.

-   **Memory Management:** can influence routing based on conversation history.
