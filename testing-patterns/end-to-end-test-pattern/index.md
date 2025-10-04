# End-to-End (E2E) Testing — Testing Pattern

## Pattern Name and Classification

-   **Name:** End-to-End (E2E) Testing
    
-   **Classification:** System/Acceptance Testing Pattern / Black-box Validation / Production-like Verification
    

## Intent

Validate **real user journeys** by exercising the **entire system across process and network boundaries**—UI/API, services, databases, queues, and third-party integrations—so you can catch **integration, configuration, data, and orchestration issues** that unit/integration tests miss.

## Also Known As

-   System Tests
    
-   Acceptance Tests (ATs)
    
-   Full-stack Tests
    
-   Journey/Flow Tests
    

## Motivation (Forces)

-   **Confidence vs. Cost:** You need a high-confidence signal before releasing, but full-stack tests are slower and more brittle.
    
-   **Environment parity:** Many failures only occur with real configs, load balancers, auth, TLS, schemas, and data.
    
-   **Cross-service orchestration:** Success depends on choreography (sagas, events, retries), not just single APIs.
    
-   **Data realism:** Realistic fixtures (time zones, encodings, migrations) flush out production-only bugs.  
    Tensions include **flakiness**, **test data management**, **long runtimes**, and **maintenance overhead**.
    

## Applicability

Use E2E tests when:

-   You must verify **critical user journeys** (signup, checkout, money transfer).
    
-   You changed **cross-cutting** concerns (authN/Z, routing, caching, config).
    
-   You need a **release gate** (smoke/regression) in CI/CD or pre-prod.
    

Be cautious when:

-   You’re tempted to test **every** permutation—prefer a **thin slice** of high-value journeys.
    
-   Your envs are not automatable or are highly shared (flake risk).
    
-   Data changes are **irreversible** without backout (coordinate carefully).
    

## Structure

-   **Runner/Orchestrator:** executes scenarios, manages environments, retries with policy.
    
-   **Environment:** production-like stack (containers/VMs), seeded data, secrets, configs.
    
-   **Drivers:** UI (WebDriver/Playwright) and/or API clients (HTTP/gRPC).
    
-   **Observability Hooks:** logs, traces, metrics, screenshots/artifacts on failure.
    
-   **Test Data Layer:** factories/fixtures, idempotent cleanup, synthetic datasets.
    
-   **Stubs/Sandboxes (optional):** for third-party dependencies when real ones are impractical.
    

```css
[Scenario Runner] → [UI/API Driver] → [Gateway] → [Services] → [DB/Cache/Queue]
                                    ↘ (optional) [3rd-party sandbox]
                 ← assertions via API/UI + logs/traces/DB views
```

## Participants

-   **Tester/Owner:** chooses journeys, expected outcomes, and SLOs for flake.
    
-   **Environment Provisioner:** IaC/Testcontainers/k8s manifests to stand up the stack.
    
-   **Drivers:** headless browser, HTTP clients, gRPC stubs.
    
-   **Data Seeder:** creates deterministic fixtures, IDs, time control.
    
-   **Reporters:** artifact collectors, dashboards, JUnit XML.
    

## Collaboration

1.  **Provision** environment (ephemeral if possible), **seed** data, and **configure** secrets.
    
2.  **Execute** scenario through external interfaces (UI/API).
    
3.  **Observe** effects (responses, side effects, persisted state, emitted events).
    
4.  **Collect** logs/traces/screenshots on failure.
    
5.  **Tear down** or **reset** the environment; keep artifacts.
    

## Consequences

**Benefits**

-   Catches **real-world integration issues** (timeouts, TLS, auth, schema drift).
    
-   Validates **orchestration** across services and infrastructure.
    
-   Offers **executive-level confidence** as a release gate.
    

**Liabilities**

-   **Flakiness** from timing, shared envs, network jitter.
    
-   **Slow** → limited feedback frequency.
    
-   **Maintenance**: fixtures, selectors, and flows drift with the product.
    
-   Risk of **overuse**—E2E should be the pyramid’s tip, not the base.
    

## Implementation

### Design Guidelines

-   **Pick the right journeys**: 5–20 happy-path + a few key sad-paths that cover the backbone.
    
-   **Make tests deterministic**: control clocks, random seeds, and IDs; wait on **conditions**, not sleeps.
    
-   **Isolate data**: unique namespaces/tenants per run; idempotent setup/teardown.
    
-   **Observe and fail fast**: assert key outcomes and guardrails (errors, latency).
    
-   **Parallelize safely**: shard tests and allocate isolated resources.
    
-   **Automate environments**: ephemeral containers (Testcontainers/k8s namespaces), not long-lived shared envs.
    
-   **Gate by value**: use E2E for smoke/regression; rely on unit/contract/integration tests for breadth.
    

### Tooling Hints

-   **Web/UI:** Playwright, Selenium.
    
-   **API:** REST-Assured, Java HttpClient, gRPC.
    
-   **Env:** Testcontainers, Docker Compose, Kubernetes (kind), WireMock/Prism for 3rd-party sandboxes.
    
-   **Obs:** OpenTelemetry, JUnit reports, screenshots, log capture.
    
-   **Data:** factories, migrations (Flyway/Liquibase), snapshots.
    

---

## Sample Code (Java 17, single-file demo)

**What it shows**

-   A tiny **System Under Test (SUT)** exposing `/api/order` and `/api/status`.
    
-   A separate **Fake Payment Gateway** (third-party) the SUT calls over HTTP.
    
-   An **E2E scenario** that starts both servers, runs the **checkout** journey via HTTP like a real client, and asserts:
    
    -   the order is **PAID**
        
    -   the payment gateway got the expected **charge request**
        

> This is a minimal sketch using `com.sun.net.httpserver.HttpServer` and Java `HttpClient`. In real projects, start your stack via Testcontainers and drive the UI/API with Playwright/REST-Assured.

```java
// EndToEndTestingDemo.java
import com.sun.net.httpserver.*;
import java.io.*;
import java.net.*;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.math.BigDecimal;
import java.util.*;
import java.util.concurrent.*;
import java.util.stream.Collectors;

/* ---------- Minimal JSON helpers (flat JSON only) ---------- */
class MiniJson {
  static Map<String,Object> parse(String json) {
    Map<String,Object> m = new HashMap<>();
    String s = json.trim();
    if (s.startsWith("{") && s.endsWith("}")) s = s.substring(1, s.length()-1);
    if (s.isBlank()) return m;
    boolean inStr=false; StringBuilder cur=new StringBuilder(); List<String> parts=new ArrayList<>();
    for (int i=0;i<s.length();i++){ char c=s.charAt(i);
      if (c=='"' && (i==0 || s.charAt(i-1)!='\\')) inStr=!inStr;
      if (c==',' && !inStr){ parts.add(cur.toString()); cur.setLength(0); } else cur.append(c);
    } parts.add(cur.toString());
    for (String p : parts) {
      String[] kv = p.split(":",2); if (kv.length<2) continue;
      String k = strip(kv[0]); String v = kv[1].trim();
      Object val;
      if (v.startsWith("\"")) val = strip(v);
      else if ("true".equals(v) || "false".equals(v)) val = Boolean.parseBoolean(v);
      else val = new BigDecimal(v);
      m.put(k, val);
    }
    return m;
  }
  static String obj(Map<String,?> m){
    return "{"+m.entrySet().stream().map(e->"\""+e.getKey()+"\":"+val(e.getValue())).collect(Collectors.joining(","))+"}";
  }
  private static String val(Object o){
    if (o instanceof String s) return "\""+s.replace("\"","\\\"")+"\"";
    if (o instanceof Boolean b) return b.toString();
    return String.valueOf(o);
  }
  private static String strip(String s){ s=s.trim(); if (s.startsWith("\"")&&s.endsWith("\"")) s=s.substring(1,s.length()-1); return s.replace("\\\"","\""); }
}

/* ---------- Fake third-party Payment Gateway ---------- */
class FakePaymentGateway {
  static record Charge(String orderId, String amount) {}
  private HttpServer server;
  private final List<Charge> charges = Collections.synchronizedList(new ArrayList<>());

  void start(int port) throws IOException {
    server = HttpServer.create(new InetSocketAddress(port), 0);
    server.createContext("/charge", this::handleCharge);
    server.setExecutor(Executors.newFixedThreadPool(4));
    server.start();
    System.out.println("[Gateway] http://localhost:"+port+"/charge");
  }
  void stop(){ if (server!=null) server.stop(0); }
  List<Charge> charges(){ return charges; }

  private void handleCharge(HttpExchange ex) throws IOException {
    if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) { ex.sendResponseHeaders(405, -1); return; }
    var body = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
    var json = MiniJson.parse(body);
    String orderId = (String) json.getOrDefault("orderId", "");
    String amount  = String.valueOf(json.getOrDefault("amount", "0.00"));
    charges.add(new Charge(orderId, amount));
    var resp = MiniJson.obj(Map.of("authId", "AUTH-"+orderId.substring(0, Math.min(8, orderId.length()))));
    sendJson(ex, 200, resp);
  }
  private static void sendJson(HttpExchange ex, int status, String body) throws IOException {
    ex.getResponseHeaders().add("Content-Type","application/json");
    byte[] b = body.getBytes(StandardCharsets.UTF_8);
    ex.sendResponseHeaders(status, b.length); try (OutputStream os = ex.getResponseBody()) { os.write(b); }
  }
}

/* ---------- System Under Test (SUT): order + payment ---------- */
class SUT {
  /* Domain */
  static final class Product { final String sku,name; final BigDecimal price; Product(String s,String n,BigDecimal p){sku=s;name=n;price=p;} }
  static final class Order {
    enum Status { NEW, PAID }
    final String id,email; final List<Line> lines=new ArrayList<>(); Status status=Status.NEW;
    static final class Line { final String sku; final int qty; final BigDecimal price; Line(String s,int q,BigDecimal p){sku=s;qty=q;price=p;} }
    Order(String id,String email){this.id=id;this.email=email;}
    BigDecimal total(){ return lines.stream().map(l->l.price.multiply(BigDecimal.valueOf(l.qty))).reduce(BigDecimal.ZERO, BigDecimal::add); }
  }

  /* In-memory stores */
  private final Map<String, Product> catalog = new ConcurrentHashMap<>();
  private final Map<String, Order> orders = new ConcurrentHashMap<>();

  /* External dependency */
  private final URI paymentBase;

  SUT(URI paymentBase){
    this.paymentBase = paymentBase;
    catalog.put("SKU-1", new Product("SKU-1","Coffee Beans", new BigDecimal("9.90")));
    catalog.put("SKU-2", new Product("SKU-2","Espresso Machine", new BigDecimal("199.00")));
  }

  private HttpServer server;

  void start(int port) throws IOException {
    server = HttpServer.create(new InetSocketAddress(port), 0);
    server.createContext("/api/order", this::createOrder);
    server.createContext("/api/status", this::status);
    server.setExecutor(Executors.newFixedThreadPool(8));
    server.start();
    System.out.println("[SUT] http://localhost:"+port+"/api/order");
  }
  void stop(){ if (server!=null) server.stop(0); }

  private void createOrder(HttpExchange ex) throws IOException {
    if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) { ex.sendResponseHeaders(405, -1); return; }
    var form = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
    var p = parseForm(form);
    String id = UUID.randomUUID().toString();
    Order o = new Order(id, p.getOrDefault("email","user@example.com"));
    for (String pair : p.getOrDefault("items","").split(",")) {
      if (pair.isBlank()) continue;
      var kv = pair.split(":"); var prod = catalog.get(kv[0]);
      int qty = Integer.parseInt(kv[1]);
      if (prod==null) { sendJson(ex, 400, "{\"error\":\"unknown_sku\"}"); return; }
      o.lines.add(new Order.Line(prod.sku, qty, prod.price));
    }
    // Charge via external gateway
    var total = o.total().setScale(2);
    try {
      var reqJson = MiniJson.obj(Map.of("orderId", o.id, "amount", total.toPlainString()));
      var req = HttpRequest.newBuilder(paymentBase.resolve("/charge"))
          .header("Content-Type","application/json").POST(HttpRequest.BodyPublishers.ofString(reqJson)).build();
      var resp = HttpClient.newHttpClient().send(req, HttpResponse.BodyHandlers.ofString());
      if (resp.statusCode()!=200) { sendJson(ex, 502, "{\"error\":\"payment_failed\"}"); return; }
    } catch (Exception e) { sendJson(ex, 502, "{\"error\":\"payment_unreachable\"}"); return; }

    o.status = Order.Status.PAID; orders.put(o.id, o);
    sendJson(ex, 200, MiniJson.obj(Map.of("orderId", o.id, "status", "PAID", "total", total.toPlainString())));
  }

  private void status(HttpExchange ex) throws IOException {
    var q = Optional.ofNullable(ex.getRequestURI().getQuery()).orElse("");
    var p = parseForm(q);
    var id = p.get("id");
    var o = orders.get(id);
    if (o==null) { sendJson(ex, 404, "{\"error\":\"not_found\"}"); return; }
    sendJson(ex, 200, MiniJson.obj(Map.of("id", o.id, "status", o.status.toString(), "total", o.total().setScale(2).toPlainString())));
  }

  private static Map<String,String> parseForm(String s){
    Map<String,String> m = new HashMap<>(); if (s==null) return m;
    for (String p : s.split("&")) { if (p.isBlank()) continue; var kv = p.split("=",2);
      m.put(URLDecoder.decode(kv[0], StandardCharsets.UTF_8), kv.length>1?URLDecoder.decode(kv[1], StandardCharsets.UTF_8):""); }
    return m;
  }
  private static void sendJson(HttpExchange ex, int code, String json) throws IOException {
    ex.getResponseHeaders().add("Content-Type","application/json");
    var bytes = json.getBytes(StandardCharsets.UTF_8);
    ex.sendResponseHeaders(code, bytes.length); try (OutputStream os = ex.getResponseBody()) { os.write(bytes); }
  }
}

/* ---------- End-to-End Scenario ---------- */
public class EndToEndTestingDemo {
  public static void main(String[] args) throws Exception {
    // 1) Bring up dependencies (fake third-party) and the SUT
    FakePaymentGateway gateway = new FakePaymentGateway(); gateway.start(8090);
    SUT sut = new SUT(URI.create("http://localhost:8090")); sut.start(8088);

    try {
      // 2) Drive the system through its public API like a real client
      HttpClient http = HttpClient.newHttpClient();
      String form = "email=" + URLEncoder.encode("alice@example.com", StandardCharsets.UTF_8)
                  + "&items=" + URLEncoder.encode("SKU-1:2,SKU-2:1", StandardCharsets.UTF_8);

      HttpRequest place = HttpRequest.newBuilder(URI.create("http://localhost:8088/api/order"))
          .header("Content-Type","application/x-www-form-urlencoded")
          .POST(HttpRequest.BodyPublishers.ofString(form)).build();

      HttpResponse<String> placed = http.send(place, HttpResponse.BodyHandlers.ofString());
      assertStatus(200, placed);
      var placedJson = MiniJson.parse(placed.body());
      String orderId = (String) placedJson.get("orderId");
      System.out.println("Created order " + orderId + " total=" + placedJson.get("total"));

      // 3) Assert the system state via its API (black-box)
      HttpRequest get = HttpRequest.newBuilder(URI.create("http://localhost:8088/api/status?id="+URLEncoder.encode(orderId, StandardCharsets.UTF_8))).GET().build();
      HttpResponse<String> status = http.send(get, HttpResponse.BodyHandlers.ofString());
      assertStatus(200, status);
      var statusJson = MiniJson.parse(status.body());
      assertEquals("PAID", (String) statusJson.get("status"), "Order should be PAID");

      // 4) Assert side-effects against the external dependency (white-box to sandbox)
      boolean seen = gateway.charges().stream().anyMatch(c -> c.orderId().equals(orderId) && c.amount().equals(String.valueOf(placedJson.get("total"))));
      if (!seen) throw new AssertionError("Payment gateway did not receive expected charge for " + orderId);

      System.out.println("E2E: ✅ checkout flow passed");
    } finally {
      sut.stop(); gateway.stop();
    }
  }

  private static void assertStatus(int exp, HttpResponse<?> r){
    if (r.statusCode()!=exp) throw new AssertionError("HTTP expected "+exp+" got "+r.statusCode()+" body="+r.body());
  }
  private static void assertEquals(Object exp, Object act, String msg){
    if (!Objects.equals(exp, act)) throw new AssertionError(msg+" (expected="+exp+", actual="+act+")");
  }
}
```

**How to extend this in real life**

-   Replace the fake gateway with **Testcontainers** for actual dependencies (PostgreSQL, Kafka, S3 via LocalStack).
    
-   Start your app via **Docker Compose** or **k8s namespace** and drive it with REST-Assured/Playwright.
    
-   Emit **traces** (OpenTelemetry) and attach traces/logs/screenshots to CI artifacts on failure.
    

## Known Uses

-   **Release gates** (smoke & regression) before production deploys.
    
-   **Critical journeys** in commerce (search → add-to-cart → pay → fulfill).
    
-   **Banking flows** (KYC → account open → transfer).
    
-   **B2B integrations** (webhooks, SSO, SFTP pipelines) validated with sandboxes.
    
-   **Mobile/web**: cross-browser/device happy paths with Playwright/Selenium.
    

## Related Patterns

-   **Contract Testing** — verifies *interface compatibility* without standing up the whole world.
    
-   **Integration Testing** — focuses on a few components; E2E covers the entire journey.
    
-   **Canary Testing / Progressive Delivery** — validates changes with live traffic after E2E passes.
    
-   **Synthetic Monitoring** — runs E2E probes continuously in production.
    
-   **Data-Driven Testing** — parameterize E2E scenarios with many datasets.
    
-   **Chaos/Resilience Testing** — injects faults during E2E to validate fallback paths.
    

---

## Implementation Tips

-   Keep E2E **few and focused** (critical paths, high-risk areas).
    
-   Build a **fixture factory** and **clock control** to eliminate flakiness.
    
-   Prefer **ephemeral, isolated** environments with IaC; avoid shared pre-prod when possible.
    
-   Make failures **actionable**: attach logs/traces/screenshots and clear step names.
    
-   Run a **fast smoke** E2E suite on each PR, and a broader suite on nightly/merge.
    
-   Pair E2E with **unit/contract** tests to keep the pyramid healthy and CI fast.

