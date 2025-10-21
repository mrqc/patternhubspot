
# Model Context Protocol (MCP)

## Pattern Name and Classification

Model Context Protocol (MCP) — integration/coordination pattern for agentic systems; a capability-discovery and messaging protocol that lets models securely access tools, prompts, resources, and data via standard interfaces.

## Intent

Standardize how an agent discovers, negotiates, and uses external capabilities (tools, resources, prompts) so integrations are portable, auditable, and decoupled from any single runtime.

## Also Known As

Capability Discovery Protocol; Tool/Resource Bus; Model–Tool Interface; Context Bridge.

## Motivation (Forces)

-   Agents need fresh data and side effects, but ad-hoc tool wiring is brittle.

-   Each provider exposes different shapes, auth, and transports.

-   Safety and audit requirements demand negotiated capabilities, typed I/O, and logs.

-   Developers want portable skills that work across runtimes without rewriting glue code.  
    MCP provides a handshake, schemas, and request/response semantics so agents can discover what’s available and call it safely.


## Applicability

Use when:

-   Multiple tools/resources must be attached to an agent in a uniform way.

-   Capabilities change at runtime and must be discovered and versioned.

-   You need isolation, permissions, and audit for external actions.

-   The same capability should serve multiple agents or models without bespoke adapters.


## Structure

1.  **Transport**: a bidirectional channel (e.g., WebSocket) carrying messages.

2.  **Session Handshake**: client and server exchange identity, versions, and capabilities.

3.  **Capabilities**: typed sets such as `tools`, `resources`, `prompts`, `sampling`.

4.  **Schema Contracts**: JSON-serializable request/response shapes for each tool/resource.

5.  **Invocation**: client sends calls; server executes and streams results/status.

6.  **Observability**: logs, tracing ids, and error codes for audit and retries.


## Participants

-   **Client (Agent/Orchestrator)**: opens the session, lists capabilities, invokes calls.

-   **MCP Server(s)**: advertise capabilities, validate input, perform work, return results.

-   **Tools**: callable functions with argument schemas and side-effect policies.

-   **Resources**: readable artifacts (files, docs, vectors) with selectors/filters.

-   **Prompts**: reusable templates parameterized by variables.

-   **Policy/Guardrail Layer**: permissions, rate limits, redaction, allow/deny lists.

-   **Logger/Monitor**: structured telemetry per call.


## Collaboration

Client connects → handshake advertises capabilities → client lists tools/resources/prompts → selects a capability → sends typed request → server executes with policy checks → streams progress and result → client integrates output or chains further calls.

## Consequences

**Benefits**

-   Decoupled integrations: one protocol for many tools and data backends.

-   Safer execution via explicit capability discovery and typed arguments.

-   Better portability and reuse of capabilities across agents and apps.

-   Built-in observability for debugging and compliance.


**Liabilities**

-   Additional infrastructure and version management.

-   Latency overhead from indirection and policy checks.

-   Requires careful auth, tenancy, and sandboxing.

-   Backwards compatibility pressure on capability schemas.


## Implementation (Key Points)

-   Perform a **versioned handshake**; fail fast on incompatible capabilities.

-   Treat each capability as a **contract**: name, description, input schema, output schema, side-effect class, timeout, idempotency.

-   Enforce **policy** before execution: scope, auth, rate limits, and resource allowlists.

-   Support **streaming** results and **cancellation** for long-running calls.

-   Include **tracing ids** and structured errors for audit and retries.

-   Keep transports pluggable; message format should be stable and language-agnostic.

-   Validate all inputs server-side; never trust model-generated arguments blindly.

-   Version capability definitions; add compatibility shims and deprecation windows.


## Sample Code (Java)

```java
import java.net.http.*;
import java.net.URI;
import java.net.http.WebSocket;
import java.nio.ByteBuffer;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;

// Minimal JSON helper (replace with Jackson/Gson in production)
class Json {
    static String obj(Map<String, Object> m) {
        StringBuilder sb = new StringBuilder("{");
        boolean first = true;
        for (var e : m.entrySet()) {
            if (!first) sb.append(",");
            first = false;
            sb.append("\"").append(e.getKey()).append("\":");
            Object v = e.getValue();
            if (v == null) sb.append("null");
            else if (v instanceof Number || v instanceof Boolean) sb.append(v.toString());
            else if (v instanceof Map) sb.append(obj((Map<String, Object>) v));
            else sb.append("\"").append(v.toString().replace("\"", "\\\"")).append("\"");
        }
        sb.append("}");
        return sb.toString();
    }
}

// Simple MCP client skeleton over WebSocket with request/response correlation.
class McpClient implements WebSocket.Listener, AutoCloseable {
    private final CompletableFuture<WebSocket> wsFut;
    private final Map<String, CompletableFuture<String>> pending = new ConcurrentHashMap<>();
    private final AtomicReference<String> sessionId = new AtomicReference<>("unknown");

    McpClient(URI uri) {
        wsFut = HttpClient.newHttpClient().newWebSocketBuilder().buildAsync(uri, this);
    }

    public CompletableFuture<Void> handshake(String clientName, String version) {
        String id = UUID.randomUUID().toString();
        Map<String, Object> payload = Map.of(
            "type", "session/handshake",
            "id", id,
            "client", clientName,
            "version", version
        );
        pending.put(id, new CompletableFuture<>());
        return wsFut.thenCompose(ws -> ws.sendText(Json.obj(payload), true))
                    .thenCompose(v -> pending.get(id))
                    .thenAccept(resp -> {
                        // naive parse just to capture session id
                        sessionId.set(resp.contains("\"session\":\"") ?
                                resp.split("\"session\":\"")[1].split("\"")[0] : "unknown");
                    });
    }

    public CompletableFuture<String> listTools() { return call("tools/list", Map.of()); }

    public CompletableFuture<String> callTool(String name, Map<String, Object> args) {
        return call("tools/call", Map.of("tool", name, "args", Json.obj(args)));
    }

    public CompletableFuture<String> listResources() { return call("resources/list", Map.of()); }

    private CompletableFuture<String> call(String type, Map<String, Object> body) {
        String id = UUID.randomUUID().toString();
        Map<String, Object> env = new HashMap<>(body);
        env.put("type", type);
        env.put("id", id);
        env.put("session", sessionId.get());
        String msg = Json.obj(env);
        CompletableFuture<String> fut = new CompletableFuture<>();
        pending.put(id, fut);
        return wsFut.thenCompose(ws -> ws.sendText(msg, true)).thenCompose(v -> fut);
    }

    // --- WebSocket.Listener ---
    public void onOpen(WebSocket ws) { ws.request(1); }
    public CompletionStage<?> onText(WebSocket ws, CharSequence data, boolean last) {
        String s = data.toString();
        // Expect response with "id":"..." correlating to request
        String[] parts = s.split("\"id\":\"");
        if (parts.length > 1) {
            String id = parts[1].split("\"")[0];
            CompletableFuture<String> fut = pending.remove(id);
            if (fut != null) fut.complete(s);
        }
        ws.request(1);
        return CompletableFuture.completedFuture(null);
    }
    public CompletionStage<?> onBinary(WebSocket ws, ByteBuffer bb, boolean l) { ws.request(1); return null; }
    public CompletionStage<?> onPing(WebSocket ws, ByteBuffer bb) { ws.request(1); return null; }
    public CompletionStage<?> onPong(WebSocket ws, ByteBuffer bb) { ws.request(1); return null; }
    public CompletionStage<?> onClose(WebSocket ws, int code, String reason) { return null; }
    public void onError(WebSocket ws, Throwable error) { error.printStackTrace(); }

    public void close() { closeAsync().join(); }
    public CompletableFuture<Void> closeAsync() {
        return wsFut.thenCompose(ws -> ws.sendClose(WebSocket.NORMAL_CLOSURE, "bye")).thenAccept(v -> {});
    }

    @Override public void close() { closeAsync().join(); }
}

// Demo: connect, handshake, list capabilities, call a tool.
public class McpDemo {
    public static void main(String[] args) throws Exception {
        URI server = URI.create("ws://localhost:8765/mcp"); // replace with your MCP server
        try (McpClient mcp = new McpClient(server)) {

            mcp.handshake("example-java-client", "1.0").join();

            String tools = mcp.listTools().get(2, TimeUnit.SECONDS);
            System.out.println("TOOLS: " + tools);

            // Example tool call (calculator-like)
            String result = mcp.callTool("calculator.eval", Map.of("expr", "12*(7+2)"))
                               .get(2, TimeUnit.SECONDS);
            System.out.println("CALL RESULT: " + result);

            String resources = mcp.listResources().get(2, TimeUnit.SECONDS);
            System.out.println("RESOURCES: " + resources);
        }
    }
}
```

## Known Uses

-   Connecting agents to local or remote resources: files, databases, search, vector stores.

-   Uniform access to domain tools in IDEs, notebooks, or assistants.

-   Enterprise integrations where capabilities, auth scopes, and audit must be negotiated.

-   Multi-agent systems sharing the same catalog of tools and prompts.

-   BYO-tool ecosystems where third parties expose reusable capabilities.


## Related Patterns

-   **Tool Use:** MCP operationalizes tool invocation with discovery and schemas.

-   **Routing:** pick which capability to call based on intent or policy.

-   **Planning:** plans specify which MCP capabilities to invoke at each step.

-   **Memory Management:** treat resources and summaries as MCP-addressable artifacts.

-   **Parallelization:** invoke multiple capabilities concurrently and merge results.

-   **Reflection:** validate capability outputs and feed fixes back into the loop.

-   **Multi-Agent:** several agents coordinate over a shared MCP catalog.
