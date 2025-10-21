
# Tool Use

## Pattern Name and Classification

Tool Use — behavioral/interaction pattern for agentic AI systems; lets an agent invoke external tools, APIs, and functions to augment its limited internal capabilities with reliable operations.

## Intent

Enable an agent to decide when and how to call deterministic tools (calculators, retrievers, APIs, databases) and to integrate their outputs into its reasoning and final answer.

## Also Known As

Function Calling, Toolformer, Plugins, External Actions, Act Phase (in Think-Act loops).

## Motivation (Forces)

-   LLMs are probabilistic and weak at precise computation, structured retrieval, and side-effects.

-   Tools are deterministic, auditable, and can access fresh data and systems.

-   The agent must choose tools safely and pass well-formed arguments, then interpret results.

-   Risks: malformed calls, tool misuse, prompt injection, unbounded side-effects, latency/cost.


## Applicability

Use when:

-   The task needs facts, calculations, structured data, transactions, or system integration.

-   Outputs must be trustworthy or auditable.

-   You can define explicit contracts (schemas, types, auth) for tool calls.

-   You need to separate “thinking” from “acting,” with logs for compliance.


## Structure

1.  **Policy/Guard**: decides whether a tool is allowed for this request and user.

2.  **Tool Registry**: catalog of callable tools and their argument schemas.

3.  **Planner/Router**: picks a tool and prepares arguments.

4.  **Executor**: validates arguments, invokes the tool, enforces timeouts and retries.

5.  **Interpreter**: reads tool results, updates context, and continues reasoning.

6.  **Auditor**: logs calls, parameters (sanitized), results, and errors.


## Participants

-   **Agent**: proposes tool calls and consumes results.

-   **Tool**: a deterministic capability with a typed contract.

-   **Registry**: resolves tool names and schemas.

-   **Validator**: enforces argument shape and policy.

-   **Executor**: runs the tool with isolation, timeouts, and error handling.

-   **Logger/Monitor**: observability, rate limits, anomaly detection.


## Collaboration

User query → Agent plans → proposes `{toolName, args}` → Validator checks policy and schema → Executor runs the tool → result returned to Agent → Agent integrates result (may chain more calls) → Final answer.

## Consequences

**Benefits**

-   Accuracy and freshness via deterministic systems.

-   Explainability: every call and parameter is logged.

-   Modularity: add tools without retraining the model.


**Liabilities**

-   Security surface expands (prompt injection, SSRF, exfiltration).

-   Latency and failure handling across networks.

-   Requires schema discipline, auth, quotas, and monitoring.


## Implementation (Key Points)

-   Define each tool with: name, description, typed argument schema, return type, auth scope, timeout, idempotency.

-   Validate strictly before execution; reject on schema or policy violations.

-   Sanitize inputs; never pass raw model text to dangerous tools.

-   Impose timeouts, retries with jitter, and circuit breakers.

-   Redact secrets from logs; store structured traces of calls and results.

-   Consider “read” vs “write” segregation and dry-run modes.

-   Combine with Routing (choose which tool) and Reflection (check results before using).


## Sample Code (Java)

```java
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

// ---------- Tool Contracts ----------
interface Tool<A, R> {
    String name();
    Class<A> argsClass();
    R execute(A args) throws Exception;
}

// Example 1: Calculator (deterministic, safe)
class CalcArgs {
    @JsonProperty("expr") public String expr; // e.g., "12*(7+2)"
}
class CalcResult {
    @JsonProperty("value") public double value;
    CalcResult(double v) { this.value = v; }
}
class CalculatorTool implements Tool<CalcArgs, CalcResult> {
    public String name() { return "calculator.eval"; }
    public Class<CalcArgs> argsClass() { return CalcArgs.class; }
    public CalcResult execute(CalcArgs args) {
        // Tiny expression evaluator (only digits and +-*/().)
        String expr = args.expr.replaceAll("[^0-9+\\-*/().]", "");
        try {
            var eng = new javax.script.ScriptEngineManager().getEngineByName("JavaScript");
            double v = Double.parseDouble(eng.eval(expr).toString());
            return new CalcResult(v);
        } catch (Exception e) {
            throw new IllegalArgumentException("Bad expression");
        }
    }
}

// Example 2: HTTP GET (read-only; guarded)
class HttpGetArgs {
    @JsonProperty("url") public String url;
    @JsonProperty("timeoutMs") public Integer timeoutMs = 2000;
}
class HttpGetResult {
    @JsonProperty("status") public int status;
    @JsonProperty("body") public String body;
    HttpGetResult(int status, String body) { this.status = status; this.body = body; }
}
class HttpGetTool implements Tool<HttpGetArgs, HttpGetResult> {
    public String name() { return "http.get"; }
    public Class<HttpGetArgs> argsClass() { return HttpGetArgs.class; }
    public HttpGetResult execute(HttpGetArgs args) throws Exception {
        // Simple allowlist guard
        if (!args.url.startsWith("https://api.example.com/")) {
            throw new SecurityException("URL not permitted");
        }
        HttpClient client = HttpClient.newBuilder()
                .connectTimeout(Duration.ofMillis(args.timeoutMs))
                .build();
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(args.url))
                .timeout(Duration.ofMillis(args.timeoutMs))
                .GET().build();
        HttpResponse<String> resp = client.send(req, HttpResponse.BodyHandlers.ofString());
        return new HttpGetResult(resp.statusCode(), resp.body());
    }
}

// ---------- Registry, Validator, Executor ----------
class ToolRegistry {
    private final Map<String, Tool<?, ?>> tools = new ConcurrentHashMap<>();
    public void register(Tool<?, ?> tool) { tools.put(tool.name(), tool); }
    public Optional<Tool<?, ?>> get(String name) { return Optional.ofNullable(tools.get(name)); }
    public Set<String> list() { return tools.keySet(); }
}

class ToolExecutor {
    private final ObjectMapper mapper = new ObjectMapper();
    private final ToolRegistry registry;
    public ToolExecutor(ToolRegistry registry) { this.registry = registry; }

    /** Execute a tool call from JSON args; returns JSON result. */
    public String call(String toolName, String argsJson) throws Exception {
        Tool<?, ?> t = registry.get(toolName).orElseThrow(() -> new NoSuchElementException("Unknown tool"));
        // Deserialize args to the tool's args class
        Object args = mapper.readValue(argsJson, t.argsClass());
        // Policy: deny list, rate limits, etc. could go here
        Object result = executeUnchecked(t, args);
        return mapper.writeValueAsString(result);
    }

    @SuppressWarnings("unchecked")
    private <A, R> R executeUnchecked(Tool<?, ?> t, Object a) throws Exception {
        return ((Tool<A, R>) t).execute((A) a);
    }
}

// ---------- Simple “Agent” that decides to use tools ----------
class Agent {
    private final ToolExecutor executor;

    Agent(ToolExecutor executor) { this.executor = executor; }

    public String answer(String user) {
        try {
            if (user.matches(".*\\d+\\s*[+\\-*/()].*")) {
                String args = "{\"expr\":\"" + user.replace("\"","") + "\"}";
                String out = executor.call("calculator.eval", args);
                return "Calculation: " + out;
            }
            if (user.toLowerCase().contains("fetch example data")) {
                String args = "{\"url\":\"https://api.example.com/data\",\"timeoutMs\":1500}";
                String out = executor.call("http.get", args);
                return "Fetched: " + out;
            }
            return "No tool needed. " + user;
        } catch (SecurityException se) {
            return "Blocked by policy: " + se.getMessage();
        } catch (Exception e) {
            return "Tool error: " + e.getMessage();
        }
    }
}

// ---------- Demo wiring ----------
public class ToolUseDemo {
    public static void main(String[] args) {
        ToolRegistry registry = new ToolRegistry();
        registry.register(new CalculatorTool());
        registry.register(new HttpGetTool());

        ToolExecutor executor = new ToolExecutor(registry);
        Agent agent = new Agent(executor);

        System.out.println(agent.answer("12*(7+2)"));
        System.out.println(agent.answer("fetch example data"));
        System.out.println(agent.answer("Tell me something nice."));
    }
}
```

## Known Uses

-   Code assistants calling linters, compilers, unit tests, formatters.

-   Retrieval-augmented generation that calls search, vector DBs, or SQL.

-   Calculators, finance APIs, and date math for precise outputs.

-   Content workflows invoking translation, summarization, OCR, or speech tools.

-   Operations agents triggering tickets, notifications, or runbooks with strict policies.


## Related Patterns

-   **Routing:** selects which tool to call based on intent and policy.

-   **Prompt Chaining:** tool calls can appear between chain stages.

-   **Parallelization:** run multiple tools concurrently and merge results.

-   **Reflection:** validate tool outputs and revise the plan.

-   **Planning:** decide the sequence and budgets for tool calls.

-   **Memory Management:** cache prior tool results and credentials metadata.
