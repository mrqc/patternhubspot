# Self-Contained Systems (SCS) — Software Architecture Pattern

## Pattern Name and Classification

-   **Name:** Self-Contained Systems (SCS)
    
-   **Classification:** Macro-architecture / Distributed Systems / Vertical Decomposition
    

## Intent

Split a large product into several **independent, end-to-end vertical systems**. Each SCS owns its **UI, backend logic, and data**. Systems integrate **loosely**, favoring **asynchronous collaboration and hyperlinks** over chatty synchronous APIs, so teams can **develop, deploy, and scale** independently.

## Also Known As

-   Vertical Slice Architecture
    
-   Fractal/Mini-product Architecture
    
-   (Related) Micro-frontends + Microservices (but SCS emphasizes full verticals with their own UI)
    

## Motivation (Forces)

-   **Autonomy vs. Coordination:** Teams need autonomy to release quickly; coupling through shared UIs/DBs slows everyone down.
    
-   **Consistency vs. Availability:** Strong, cross-system consistency is costly; most flows tolerate **eventual consistency**.
    
-   **Frontend ownership:** Central UI teams become bottlenecks; features should ship UI + backend together.
    
-   **Operational blast radius:** Outages and deployments should be isolated.
    
-   **Heterogeneity:** Different domains benefit from different tech stacks—without a central “one stack to rule them all.”
    

SCS addresses these by carving the product into **vertical, business-aligned systems** that communicate rarely and loosely.

## Applicability

Use SCS when:

-   Multiple domains (catalog, checkout, content, search) evolve at **different speeds**.
    
-   You want **independent deployment pipelines** and **team autonomy** end-to-end.
    
-   **UI integration** through links/edge composition is acceptable.
    
-   Cross-system flows can be redesigned for **eventual consistency**.
    

Avoid or adapt when:

-   You need **strong, synchronous consistency** across many domains.
    
-   A unified, highly interactive **single-page UI** must combine many domains on one page (edge composition still possible, but harder).
    
-   Organization is not ready to own **run-what-you-build** per vertical.
    

## Structure

Each SCS is a **mini product**:

```yaml
+---------------------+          +---------------------+          +---------------------+
|   SCS: Catalog      |          |   SCS: Orders       |          |   SCS: Shipping     |
|  - Own UI           |          |  - Own UI           |          |  - Own UI           |
|  - App/Domain       |   <--->  |  - App/Domain       |   <--->  |  - App/Domain       |
|  - Data store       |  (links) |  - Data store       | (events) |  - Data store       |
+---------------------+          +---------------------+          +---------------------+
          ^                               ^                                 ^
          |                               |                                 |
        Users                         Team Orders                        Team Shipping
```

**Integration styles**

-   **Hyperlinks/URL navigation** between UIs (“View order details” opens Orders SCS).
    
-   **Asynchronous events** (e.g., `OrderPlaced`) for downstream reactions (Shipping, Billing).
    
-   **Minimal synchronous calls** (only where necessary; with timeouts/fallbacks).
    

## Participants

-   **SCS (vertical slice):** UI, application/domain services, persistence, ops.
    
-   **Team:** cross-functional, owns the SCS end-to-end.
    
-   **Edge/UI integrator (optional):** reverse proxy/edge rendering/composition shell.
    
-   **Event Broker (optional):** decoupled integration (Kafka, SNS/SQS, Pulsar).
    
-   **Link Registry/Router (optional):** stable URLs for cross-SCS navigation.
    

## Collaboration

1.  A user navigates to an SCS UI; all functionality for that domain is served **within** that SCS.
    
2.  If a flow crosses systems, the first SCS either **links** to the next or **emits an event** that triggers downstream processing.
    
3.  Data remains **local** to each SCS; inter-SCS reads happen via **published views/APIs** or **event-driven projections**—never through foreign table joins.
    
4.  Each SCS is **deployed independently**; changes to one do not require coordinated releases.
    

## Consequences

**Benefits**

-   **Independent delivery & scaling** per vertical.
    
-   **Resilience & containment:** faults don’t cascade easily.
    
-   **Tech freedom:** choose frameworks/stacks per SCS.
    
-   **Clear ownership** and faster lead time (team controls UI→DB).
    

**Liabilities**

-   **Cross-system UX** can feel fragmented without careful navigation/edge composition.
    
-   **Eventual consistency** requires new UX patterns (spinners, status pages).
    
-   **Ops/tooling duplication** (build, monitoring, auth) across systems.
    
-   **Global features** (search across domains, unified reporting) need extra integration work.
    

## Implementation

### Principles

-   **Vertical Bounded Contexts:** 1 SCS ≈ 1 business capability.
    
-   **Own your data:** separate schemas/storage per SCS; share via events/replicated views.
    
-   **Prefer async:** events over RPC; links over embedded remote widgets.
    
-   **Stable URLs as contracts:** cross-SCS navigation is part of the API.
    
-   **Edge integration:** compose UI at the edge (reverse proxy, SSI, fragments) if a page must show data from several SCSs.
    
-   **Operational guardrails:** per-SCS CI/CD, dashboards, alerts, error budgets.
    

### Technical checklist

-   Authentication/authorization strategy across SCS (SSO/OIDC; propagate identity).
    
-   **Observability:** trace IDs propagate through links and events; per-SCS SLOs.
    
-   **Backwards-compatible events** (schema registry/versioning).
    
-   **Consumer-owned projections** (each SCS builds what it needs).
    
-   **Degrade gracefully:** if another SCS is down, show links/status—not hard failures.
    

---

## Sample Code (Java 17, two tiny SCSs)

> Two independent programs (build and run separately).  
> **OrdersSCS** exposes a UI/API to place orders and asynchronously notifies **ShippingSCS** via an HTTP webhook (simulating events).  
> **ShippingSCS** owns its own data and UI to list shipments. No shared database.

### 1) OrdersSCS.java (port 8080)

```java
// OrdersSCS.java
import com.sun.net.httpserver.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

public class OrdersSCS {
  static class Order { final String id; final String email; final String sku; Order(String id, String email, String sku){ this.id=id; this.email=email; this.sku=sku; } }
  private static final Map<String, Order> orders = new ConcurrentHashMap<>();

  public static void main(String[] args) throws Exception {
    HttpServer http = HttpServer.create(new InetSocketAddress(8080), 0);
    http.createContext("/ui", OrdersSCS::ui);
    http.createContext("/api/orders", OrdersSCS::createOrder);
    http.setExecutor(java.util.concurrent.Executors.newFixedThreadPool(8));
    http.start();
    System.out.println("Orders SCS at http://localhost:8080/ui");
  }

  // Minimal HTML UI for demo
  static void ui(HttpExchange ex) throws IOException {
    String body = """
      <html><body>
        <h1>Orders (Self-Contained)</h1>
        <form method='post' action='/api/orders'>
          Email: <input name='email'/><br/>
          SKU: <input name='sku' value='SKU-1'/><br/>
          <button type='submit'>Place order</button>
        </form>
        <hr/>
        <ul>
    """;
    for (var o : orders.values()) {
      String link = "http://localhost:8081/ui?orderId=" + URLEncoder.encode(o.id, StandardCharsets.UTF_8);
      body += "<li>Order " + o.id + " for " + o.email + " / " + o.sku + " — " +
              "<a href='" + link + "'>Track shipment</a></li>";
    }
    body += "</ul></body></html>";
    respond(ex, 200, "text/html", body);
  }

  static void createOrder(HttpExchange ex) throws IOException {
    if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) { ex.sendResponseHeaders(405, -1); return; }
    String form = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
    Map<String,String> p = parseForm(form);
    String id = UUID.randomUUID().toString();
    Order o = new Order(id, p.getOrDefault("email","unknown@local"), p.getOrDefault("sku","SKU-1"));
    orders.put(id, o);

    // Asynchronous integration: send an HTTP "event" to ShippingSCS (webhook)
    try {
      String payload = "{\"type\":\"OrderPlaced\",\"orderId\":\""+o.id+"\",\"email\":\""+o.email+"\",\"sku\":\""+o.sku+"\"}";
      HttpRequest req = HttpRequest.newBuilder(URI.create("http://localhost:8081/events/order-placed"))
        .header("Content-Type","application/json")
        .POST(HttpRequest.BodyPublishers.ofString(payload))
        .build();
      HttpClient.newHttpClient().sendAsync(req, HttpResponse.BodyHandlers.ofString())
        .thenAccept(r -> System.out.println("[Orders] notified shipping: " + r.statusCode()))
        .exceptionally(e -> { e.printStackTrace(); return null; });
    } catch (Exception e) { e.printStackTrace(); /* best-effort; do not fail the order */ }

    ex.getResponseHeaders().add("Location", "/ui");
    ex.sendResponseHeaders(303, -1); // redirect back to UI
  }

  static Map<String,String> parseForm(String s){
    Map<String,String> m = new HashMap<>();
    for (String kv : s.split("&")) {
      if (kv.isBlank()) continue;
      String[] p = kv.split("=",2);
      String k = URLDecoder.decode(p[0], StandardCharsets.UTF_8);
      String v = p.length>1 ? URLDecoder.decode(p[1], StandardCharsets.UTF_8) : "";
      m.put(k, v);
    }
    return m;
  }
  static void respond(HttpExchange ex, int code, String ct, String body) throws IOException {
    ex.getResponseHeaders().add("Content-Type", ct);
    byte[] b = body.getBytes(StandardCharsets.UTF_8);
    ex.sendResponseHeaders(code, b.length);
    try (OutputStream os = ex.getResponseBody()) { os.write(b); }
  }
}
```

### 2) ShippingSCS.java (port 8081)

```java
// ShippingSCS.java
import com.sun.net.httpserver.*;
import java.io.*;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

public class ShippingSCS {
  static class Shipment { final String id; final String orderId; final String email; final String sku; final String status;
    Shipment(String id, String orderId, String email, String sku, String status){ this.id=id; this.orderId=orderId; this.email=email; this.sku=sku; this.status=status; } }
  private static final Map<String, Shipment> shipments = new ConcurrentHashMap<>();

  public static void main(String[] args) throws Exception {
    HttpServer http = HttpServer.create(new InetSocketAddress(8081), 0);
    http.createContext("/ui", ShippingSCS::ui);
    http.createContext("/events/order-placed", ShippingSCS::onOrderPlaced); // webhook endpoint
    http.setExecutor(java.util.concurrent.Executors.newFixedThreadPool(8));
    http.start();
    System.out.println("Shipping SCS at http://localhost:8081/ui");
  }

  static void ui(HttpExchange ex) throws IOException {
    String orderId = Optional.ofNullable(ex.getRequestURI().getQuery()).orElse("").replace("orderId=","");
    StringBuilder body = new StringBuilder("""
      <html><body>
        <h1>Shipping (Self-Contained)</h1>
        <ul>
    """);
    shipments.values().stream()
      .filter(s -> orderId.isBlank() || s.orderId.equals(orderId))
      .forEach(s -> body.append("<li>Shipment ").append(s.id)
        .append(" for order ").append(s.orderId)
        .append(" [").append(s.status).append("]</li>"));
    body.append("</ul></body></html>");
    respond(ex, 200, "text/html", body.toString());
  }

  // Receive async event from OrdersSCS
  static void onOrderPlaced(HttpExchange ex) throws IOException {
    if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) { ex.sendResponseHeaders(405, -1); return; }
    String json = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
    Map<String,String> evt = parseJson(json);
    String orderId = evt.get("orderId");
    String email   = evt.get("email");
    String sku     = evt.get("sku");
    String sid = UUID.randomUUID().toString();

    // Local write to this SCS's own data store
    shipments.put(sid, new Shipment(sid, orderId, email, sku, "CREATED"));
    System.out.println("[Shipping] created shipment " + sid + " for order " + orderId);

    respond(ex, 202, "application/json", "{\"status\":\"accepted\"}");
  }

  // naive JSON parser for flat objects like {"k":"v"}
  static Map<String,String> parseJson(String s){
    Map<String,String> m = new HashMap<>();
    s = s.trim().replaceAll("[{}\"]","");
    if (s.isBlank()) return m;
    for (String kv : s.split(",")) {
      String[] p = kv.split(":",2);
      if (p.length==2) m.put(p[0].trim(), p[1].trim());
    }
    return m;
  }
  static void respond(HttpExchange ex, int code, String ct, String body) throws IOException {
    ex.getResponseHeaders().add("Content-Type", ct);
    byte[] b = body.getBytes(StandardCharsets.UTF_8);
    ex.sendResponseHeaders(code, b.length);
    try (OutputStream os = ex.getResponseBody()) { os.write(b); }
  }
}
```

**What the example demonstrates**

-   Two **separate programs** (two SCSs), each with its **own UI, logic, and data**.
    
-   **Loose coupling** via a webhook (simulating events). Orders never writes Shipping’s DB.
    
-   **UI integration via links**: Orders UI links to Shipping’s UI to track a shipment.
    
-   You can replace the webhook with a **message broker** in production.
    

---

## Known Uses

-   Large e-commerce sites: product discovery (search/catalog), order/checkout, account, content all as separate SCSs with deep links between UIs.
    
-   Media portals: article management, recommendation, comments as separate verticals.
    
-   B2B platforms: pricing, quoting, fulfillment each as its own SCS, coordinated via events.
    

## Related Patterns

-   **Microservices:** SCS can be implemented with one or more microservices, but **always includes the UI** per vertical.
    
-   **Micro-frontends:** the UI facet of SCS; SCS extends it to include backend + data.
    
-   **Bounded Context (DDD):** typical cut for an SCS.
    
-   **Event-Driven Architecture:** preferred integration style between SCSs.
    
-   **Modular Monolith:** internal precursor; SCS is the distributed, independently deployable form.
    

---

## Implementation Tips

-   Start from **business capabilities**; give each SCS a **clear URL space** and **data ownership**.
    
-   Standardize **SSO/OIDC**, **observability**, and **event contracts** across SCSs; avoid standardizing runtime stacks unnecessarily.
    
-   Prefer **links and events**; keep synchronous calls rare, well-bounded, and resilient (timeouts, fallbacks).
    
-   Use **edge composition** (reverse proxy, fragments) to unify UX where needed—without breaking SCS autonomy.
    
-   Provide **SDKs/design system** for a consistent look & feel while keeping independent UIs.
    
-   Track **end-to-end business KPIs** across SCSs with shared tracing IDs (propagate via headers and event metadata).

