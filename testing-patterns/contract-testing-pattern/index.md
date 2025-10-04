# Contract Testing — Testing Pattern

## Pattern Name and Classification

-   **Name:** Contract Testing
    
-   **Classification:** Online/Integration Testing Pattern / Compatibility Assurance / Consumer–Provider Verification
    

## Intent

Verify that **consumers and providers agree on the interface** (HTTP, RPC, or event/message schemas) by testing each side **against a shared, versioned contract**. This prevents breaking changes and enables **independent releases** without costly full end-to-end environments.

## Also Known As

-   Consumer-Driven Contracts (CDC)
    
-   Provider Contract Verification
    
-   API Contract Tests / Message Contract Tests
    

## Motivation (Forces)

-   **Coupling vs. autonomy:** Microservices and external APIs should evolve independently without breaking clients.
    
-   **Flaky E2E tests:** Full-stack environments are expensive, fragile, and slow to diagnose.
    
-   **Backward compatibility:** Providers must add features without breaking existing consumers.
    
-   **Multiple consumers:** Each may rely on different subsets of the API; over-general tests miss real usage.
    
-   **Speed:** Contracts run fast in CI and catch regressions before staging.
    

Contract testing addresses these by letting **consumers define expectations as executable tests**, publish resulting **contracts**, and letting **providers verify** against them continuously.

## Applicability

Use when:

-   Services communicate via **public APIs** (HTTP/gRPC), **events** (Kafka/Pulsar), or **RPC**.
    
-   You need **independent deployability** and **backward-compatible evolution**.
    
-   Many consumers depend on the same provider.
    

Be cautious when:

-   Interfaces are unstable prototypes (consider feature flags + A/B instead).
    
-   Heavy cross-service workflows require true **system tests** for orchestration logic (contract tests complement, not replace, E2E).
    

## Structure

-   **Consumer Contract Tests:** Drive a mock/stub provider and **capture a contract** (request/response or message schema) representing **what the consumer needs**.
    
-   **Contract Broker/Registry (optional):** Stores versioned contracts, tags (prod, staging), and coordinates verification.
    
-   **Provider Verification:** Replays each contract against the provider implementation (or adapter) and asserts **compatibility**.
    
-   **Pipelines & Gates:** CI steps fail on incompatibilities; releases are blocked until all relevant contracts pass.
    

```mathematica
Consumer Tests ──generate──► Contract ──publish──► Broker ──notify──► Provider CI ──verify──► OK/Fail
```

## Participants

-   **Consumer:** The client of an API/message. Writes CDC tests.
    
-   **Provider:** The service that implements the API/message. Runs provider verification.
    
-   **Contract:** Machine-readable specification (HTTP interaction + schema, protobuf/Avro schema, JSON Schema, etc.).
    
-   **Broker/Registry (optional):** Stores contracts & verification results.
    
-   **Stubs/Mocks:** Provider doubles generated from contracts for consumer tests and local development.
    
-   **CI/CD Orchestrator:** Enforces gates based on verification status.
    

## Collaboration

1.  The **consumer** writes a test describing how it calls the provider and what it expects.
    
2.  The test produces a **contract** artifact and (optionally) publishes it.
    
3.  The **provider** fetches the contract(s) and runs **verification** against its implementation.
    
4.  If all contracts pass, the provider may release; otherwise it fixes or negotiates a new version/contract.
    

## Consequences

**Benefits**

-   Early detection of breaking changes; fewer staging surprises.
    
-   Faster pipelines than full E2E; easier root-cause isolation.
    
-   Works with **events** and **HTTP** alike (schemas instead of environments).
    
-   Encourages **minimal, consumer-focused APIs** (don’t overspecify).
    

**Liabilities**

-   Poorly scoped contracts become brittle (overspecify headers/order/exact formatting).
    
-   Requires **versioning discipline** and a process for deprecations.
    
-   Does not validate **cross-service orchestration** or **performance**—you still need system tests and SLO monitors.
    
-   Provider **state management** for verification (fixtures) adds setup effort.
    

## Implementation

### Guidelines

-   **Contract scope:** specify only what consumers require (fields, types, error semantics). Mark **optional** vs **required**.
    
-   **Compatibility rules:** additive non-breaking changes (add optional fields, tolerate order). Avoid removing/renaming without a version strategy.
    
-   **Deterministic tests:** stable IDs and fixtures; separate **provider states** (“user exists”).
    
-   **Negative cases:** include representative 4xx/5xx and validation errors.
    
-   **Broker & tags:** tag contracts by environment (prod/staging) and consumer version.
    
-   **For events:** manage schemas in a **registry** (subject/version), run compat checks (backward/forward/full).
    
-   **Pipelines:** on provider PRs, **verify against all relevant contracts**; on consumer PRs, generate/publish updated contracts and run stubbed tests.
    
-   **Tooling (examples):** Pact, Spring Cloud Contract, OpenAPI + validators, protobuf/Avro with schema registry.
    

### Versioning & deprecation

-   Use **semantic versioning** for APIs/schemas.
    
-   Support a **deprecation window**; maintain compatibility with the last N consumer major versions.
    
-   Automate **compat checks** in CI (e.g., backward compatibility for messages).
    

---

## Sample Code (Java 17, framework-free)

A minimal, library-agnostic sketch of **consumer-driven HTTP contract testing**:

-   A **contract** declares the method, path template, expected status, and a tiny **JSON schema** (required fields + types).
    
-   A **provider** HTTP server implements `GET /users/{id}`.
    
-   A **verifier** runs the contract against the provider and validates the JSON response.
    

> This is educational; in production, use Pact or Spring Cloud Contract and real JSON Schema.

```java
// ContractTestingDemo.java
import com.sun.net.httpserver.HttpServer;
import com.sun.net.httpserver.HttpExchange;
import java.io.*;
import java.net.*;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;

/* ---------- Contract Model ---------- */

enum JsonType { STRING, NUMBER, BOOLEAN, OBJECT }

record FieldSpec(String name, JsonType type, boolean required) { }

record HttpContract(
    String name,
    String method,                 // e.g., "GET"
    String pathTemplate,           // e.g., "/users/{id}"
    Map<String,String> pathParams, // sample values for verification, e.g., id -> "42"
    int expectedStatus,
    List<FieldSpec> responseFields // minimal "schema"
) {
  String resolvedPath() {
    String p = pathTemplate;
    for (var e : pathParams.entrySet()) {
      p = p.replace("{"+e.getKey()+"}", urlEncode(e.getValue()));
    }
    return p;
  }
  private static String urlEncode(String s) { return URLEncoder.encode(s, StandardCharsets.UTF_8); }
}

/* ---------- Tiny JSON utils (flat objects for demo) ---------- */

class MiniJson {
  // very small parser for flat {"k":"v","n":123,"b":true}
  static Map<String,Object> parse(String json) {
    Map<String,Object> m = new HashMap<>();
    String s = json.trim();
    if (s.startsWith("{") && s.endsWith("}")) s = s.substring(1, s.length()-1);
    if (s.isBlank()) return m;
    for (String part : splitTopLevel(s)) {
      String[] kv = part.split(":", 2);
      if (kv.length < 2) continue;
      String key = strip(kv[0]);
      String val = kv[1].trim();
      Object v;
      if (val.startsWith("\"") && val.endsWith("\"")) {
        v = unescape(val.substring(1, val.length()-1));
      } else if ("true".equals(val) || "false".equals(val)) {
        v = Boolean.parseBoolean(val);
      } else {
        try { v = Double.valueOf(val); }
        catch (NumberFormatException e) { v = val; }
      }
      m.put(key, v);
    }
    return m;
  }
  private static List<String> splitTopLevel(String s) {
    List<String> parts = new ArrayList<>();
    StringBuilder cur = new StringBuilder();
    boolean inStr = false;
    for (int i=0;i<s.length();i++) {
      char c = s.charAt(i);
      if (c=='"' && (i==0 || s.charAt(i-1)!='\\')) inStr = !inStr;
      if (c==',' && !inStr) { parts.add(cur.toString()); cur.setLength(0); }
      else cur.append(c);
    }
    parts.add(cur.toString());
    return parts;
  }
  private static String strip(String s) {
    s = s.trim();
    if (s.startsWith("\"") && s.endsWith("\"")) s = s.substring(1, s.length()-1);
    return unescape(s);
  }
  private static String unescape(String s) { return s.replace("\\\"", "\""); }
}

/* ---------- Contract Verifier ---------- */

class ContractVerifier {
  static VerificationResult verify(URI baseUri, HttpContract c) throws Exception {
    HttpClient client = HttpClient.newHttpClient();

    HttpRequest req = HttpRequest.newBuilder(baseUri.resolve(c.resolvedPath()))
        .method(c.method(), HttpRequest.BodyPublishers.noBody())
        .header("Accept", "application/json")
        .build();

    HttpResponse<String> resp = client.send(req, HttpResponse.BodyHandlers.ofString());
    List<String> failures = new ArrayList<>();

    if (resp.statusCode() != c.expectedStatus) {
      failures.add("Expected status " + c.expectedStatus + " but got " + resp.statusCode());
      return new VerificationResult(false, failures);
    }

    Map<String,Object> json = MiniJson.parse(resp.body());
    for (FieldSpec f : c.responseFields()) {
      if (f.required() && !json.containsKey(f.name())) {
        failures.add("Missing required field: " + f.name());
        continue;
      }
      if (!json.containsKey(f.name())) continue; // optional and absent
      Object v = json.get(f.name());
      switch (f.type()) {
        case STRING  -> { if (!(v instanceof String)) failures.add("Field " + f.name() + " should be STRING"); }
        case NUMBER  -> { if (!(v instanceof Number)) failures.add("Field " + f.name() + " should be NUMBER"); }
        case BOOLEAN -> { if (!(v instanceof Boolean)) failures.add("Field " + f.name() + " should be BOOLEAN"); }
        case OBJECT  -> { /* omitted in demo */ }
      }
    }
    return new VerificationResult(failures.isEmpty(), failures);
  }

  record VerificationResult(boolean ok, List<String> failures) { }
}

/* ---------- Provider (HTTP server) ---------- */

class UserProvider {
  private HttpServer server;

  void start(int port) throws IOException {
    server = HttpServer.create(new InetSocketAddress(port), 0);
    server.createContext("/users", this::handleUser);
    server.setExecutor(Executors.newFixedThreadPool(8));
    server.start();
    System.out.println("[Provider] Listening on http://localhost:" + port);
  }
  void stop() { server.stop(0); }

  private void handleUser(HttpExchange ex) throws IOException {
    String path = ex.getRequestURI().getPath();      // /users/42
    if (!"GET".equals(ex.getRequestMethod())) {
      ex.sendResponseHeaders(405, -1); return;
    }
    String[] parts = path.split("/");
    if (parts.length != 3) { sendJson(ex, 404, "{\"error\":\"not_found\"}"); return; }
    String idStr = parts[2];
    long id;
    try { id = Long.parseLong(idStr); } catch (NumberFormatException e) { sendJson(ex, 400, "{\"error\":\"bad_id\"}"); return; }

    // Domain logic: return a user payload. Extra fields are OK, but must at least satisfy the contract.
    String json = """
      {
        "id": %d,
        "email": "user%1$d@example.com",
        "active": true,
        "createdAt": "%s"
      }""".formatted(id, Instant.now().toString());

    sendJson(ex, 200, json);
  }

  private static void sendJson(HttpExchange ex, int status, String body) throws IOException {
    ex.getResponseHeaders().add("Content-Type","application/json");
    byte[] b = body.getBytes(StandardCharsets.UTF_8);
    ex.sendResponseHeaders(status, b.length);
    try (OutputStream os = ex.getResponseBody()) { os.write(b); }
  }
}

/* ---------- Demo: "consumer-generated" contract + provider verification ---------- */

public class ContractTestingDemo {
  public static void main(String[] args) throws Exception {
    // Imagine this block runs in the CONSUMER repo/test to produce a contract:
    HttpContract contract = new HttpContract(
        "GetUser_v1",
        "GET",
        "/users/{id}",
        Map.of("id", "42"),
        200,
        List.of(
            new FieldSpec("id",     JsonType.NUMBER,  true),
            new FieldSpec("email",  JsonType.STRING,  true),
            new FieldSpec("active", JsonType.BOOLEAN, false) // optional: consumer doesn't rely on it
        )
    );

    // Now pretend we switch to the PROVIDER pipeline that verifies the above contract:
    UserProvider provider = new UserProvider();
    provider.start(8089);
    try {
      var result = ContractVerifier.verify(URI.create("http://localhost:8089"), contract);
      if (result.ok()) {
        System.out.println("[Verify] Contract " + contract.name() + " PASSED");
      } else {
        System.out.println("[Verify] Contract " + contract.name() + " FAILED:");
        result.failures().forEach(s -> System.out.println("  - " + s));
        System.exit(1);
      }
    } finally {
      provider.stop();
    }
  }
}
```

**How to read this demo**

-   The **consumer** expresses what it needs (`id` number, `email` string) and treats `active` as optional.
    
-   The **provider** serves `/users/{id}` and may return **extra fields** (allowed).
    
-   The **verifier** calls the provider and validates **type + presence** only for required fields—this avoids overspecification.
    
-   Replace this toy harness with a proper tool (e.g., Pact or Spring Cloud Contract) and a contract broker in CI.
    

## Known Uses

-   **HTTP APIs:** CDC with Pact or Spring Cloud Contract for REST and GraphQL.
    
-   **Event pipelines:** Avro/Protobuf schemas in a **schema registry**; producers/consumers verified for **backward/forward** compatibility.
    
-   **Large microservice estates:** contract gates in CI/CD to enable **independent deploys** (retail, fintech, streaming platforms).
    
-   **3rd-party integrations:** vendor APIs validated against a pinned contract to detect upstream changes early.
    

## Related Patterns

-   **API Schema Validation (OpenAPI/JSON Schema):** source of truth for HTTP contracts.
    
-   **Schema Registry & Compatibility (Avro/Protobuf):** contracts for event streams.
    
-   **Service Virtualization / Stubbing:** run consumer with provider doubles generated from contracts.
    
-   **Integration Tests (E2E):** complement for workflow/infra validation (not a replacement).
    
-   **Feature Flags / Canary Testing:** mitigate risk during rollout once contracts verify.
    

---

## Implementation Tips

-   Keep contracts **minimal and semantic** (don’t assert header order, whitespace, or timestamp formats unless required).
    
-   Separate **provider states** for verification (“user 42 exists”).
    
-   Automate **compatibility checks** on every PR; block releases on failures.
    
-   For events, pick a **compat mode** (backward, forward, full) and enforce in CI.
    
-   Track **which consumers** depend on which parts of the provider to retire fields safely.
    
-   Document **deprecation timelines** and provide **lint rules** to prevent overspecification.
    
-   Add **negative contracts** (e.g., 404 for unknown id) to verify error semantics, too.

