# Monolithic Architecture — Software Architecture Pattern

## Pattern Name and Classification

-   **Name:** Monolithic Architecture
    
-   **Classification:** Deployment/Structural Style (single executable / single process, often single database)
    

## Intent

Deliver an entire application—UI, application logic, domain logic, and data access—**as a single deployable unit**. All modules run **in-process**, share the same runtime and often a single database, enabling **simple operations, low latency in-call execution, and ACID transactions** across the whole app.

## Also Known As

-   Single Deployable
    
-   Classic Monolith
    
-   (Variant) Modular Monolith — a monolith with **strong internal module boundaries** but still one deployable
    

## Motivation (Forces)

-   **Operational simplicity:** one build, one deployment, one set of configs/logs.
    
-   **Performance:** in-process calls are faster than RPC; easy to keep **ACID** across features.
    
-   **Coherent versioning:** no cross-service version drift.
    
-   **Cost & speed:** ideal for early product stages and small teams.
    

**Tensions**

-   **Team scaling:** a large codebase can slow builds and increase merge conflicts.
    
-   **Blast radius:** any change requires redeploying the whole system.
    
-   **Technology lock-in:** a single runtime for all parts.
    
-   **Scaling limits:** scale is mostly **vertical**; horizontal scaling needs statelessness and externalization of state.
    

## Applicability

Use a monolith when:

-   A small/medium team needs to **ship fast** with minimal ops overhead.
    
-   The domain fits well into **one codebase** and **one schema**.
    
-   You need **cross-feature ACID transactions** and tight consistency.
    
-   Latency-sensitive flows benefit from **in-process composition**.
    

Reconsider if:

-   Teams require **independent deployments** and tech diversity.
    
-   Workload and organization demand **separate scaling/failure domains**.
    
-   You foresee rapid product-line diversification (plugins, tenants) that benefit from modular/microkernel boundaries.
    

## Structure

All layers live inside one process and usually one repository:

```pgsql
+-----------------------------------------------------------+
|                    Monolithic Application                 |
|  +------------------+    +------------------+             |
|  |   Presentation   | -> |   Application    |             |
|  | (HTTP, CLI, UI)  |    |  Services/UseCases|            |
|  +------------------+    +---------+--------+             |
|                                  |                       |
|                         +-------- v --------+            |
|                         |      Domain       |            |
|                         | Entities/Policy   |            |
|                         +--------+---------+             |
|                                  |                       |
|                         +-------- v --------+            |
|                         |  Data Access/DB   |            |
|                         +-------------------+            |
+-----------------------------------------------------------+
(Everything built, tested, deployed together)
```

## Participants

-   **Controllers/Handlers (Presentation)** – accept requests, map to use cases.
    
-   **Application Services** – orchestrate workflows and transactions.
    
-   **Domain Entities/Services** – enforce business rules.
    
-   **Repositories/DAOs** – abstract persistence to the shared DB.
    
-   **Cross-cutting** – logging, metrics, auth, caching, transactions.
    

## Collaboration

1.  Request hits **Controller** → validates input.
    
2.  Controller calls **Application Service**.
    
3.  Application Service manipulates **Domain** objects and **Repositories** inside a **single transaction**.
    
4.  Return DTO to Controller → render response.
    
5.  Internal collaborations are **method calls** (no network).
    

## Consequences

**Benefits**

-   Minimal ops complexity and **fast iteration** early on.
    
-   **Low latency** internal calls.
    
-   Easy **ACID** across features with a single DB/transaction manager.
    
-   One place to **observe/debug** (logs, traces).
    

**Liabilities**

-   Codebase grows into a **big ball of mud** without strong boundaries.
    
-   **Whole-app redeploy** for small changes.
    
-   **Scaling teams** and modules becomes harder; long build/test times.
    
-   Risk of **coupling** (UI directly to DB if discipline is weak).
    

## Implementation

### Guidelines

-   Use **package-by-feature** (e.g., `orders`, `billing`) to avoid layer-spaghetti.
    
-   Keep **domain logic pure**; adapters (web/DB) at the edges.
    
-   Centralize **transactions** in application services.
    
-   Externalize **stateful concerns** (session, cache) to scale horizontally.
    
-   Establish **architecture rules** (ArchUnit/JPMS) even in a monolith.
    
-   Prepare an **evolution path**: internal modules with clear APIs → extract later if needed.
    
-   Add **observability** early (structured logs, metrics, health).
    

### Operational Tips

-   **Blue/green or rolling** deployments to mitigate blast radius.
    
-   **Feature flags** to decouple deploy from release.
    
-   **Database migrations** (Liquibase/Flyway) with backward-compatible steps.
    
-   Keep the monolith **12-factor** to scale out when needed.
    

---

## Sample Code (Java 17, framework-free, single process)

A tiny monolith with:

-   HTTP endpoint
    
-   Controllers → Services → Repositories
    
-   In-process calls and one “transaction boundary” (simulated)
    

```java
// MonolithDemo.java
import com.sun.net.httpserver.HttpServer;
import com.sun.net.httpserver.HttpExchange;
import java.io.*;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.math.BigDecimal;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/* ====== Domain ====== */
final class Money {
  final BigDecimal amount; final String currency;
  Money(String amt, String cur) { this.amount = new BigDecimal(amt); this.currency = cur; }
  Money(BigDecimal amt, String cur) { this.amount = amt; this.currency = cur; }
  Money add(Money other) {
    if (!currency.equals(other.currency)) throw new IllegalArgumentException("currency mismatch");
    return new Money(amount.add(other.amount), currency);
  }
  public String toString(){ return amount.toPlainString() + " " + currency; }
}

final class Product {
  final String sku; final String name; final Money price;
  Product(String sku, String name, Money price){ this.sku = sku; this.name = name; this.price = price; }
}

final class Order {
  enum Status { NEW, PAID }
  final UUID id; final String email; final List<Line> lines = new ArrayList<>();
  Status status = Status.NEW;
  record Line(String sku, int qty, Money price){}
  Order(UUID id, String email){ this.id = id; this.email = email; }
  void addLine(Product p, int qty) {
    if (qty <= 0) throw new IllegalArgumentException("qty>0");
    lines.add(new Line(p.sku, qty, p.price));
  }
  Money total(){
    return lines.stream()
        .map(l -> new Money(l.price().amount().multiply(BigDecimal.valueOf(l.qty())), l.price().currency()))
        .reduce((a,b) -> a.add(b)).orElse(new Money("0", "EUR"));
  }
  void markPaid(){ if (lines.isEmpty()) throw new IllegalStateException("empty"); status = Status.PAID; }
}

/* ====== Repositories (in-memory for demo) ====== */
interface ProductRepository { Optional<Product> bySku(String sku); void save(Product p); }
interface OrderRepository { void save(Order o); Optional<Order> byId(UUID id); }

final class InMemoryProductRepo implements ProductRepository {
  private final Map<String, Product> store = new ConcurrentHashMap<>();
  public Optional<Product> bySku(String sku){ return Optional.ofNullable(store.get(sku)); }
  public void save(Product p){ store.put(p.sku, p); }
}

final class InMemoryOrderRepo implements OrderRepository {
  private final Map<UUID, Order> store = new ConcurrentHashMap<>();
  public void save(Order o){ store.put(o.id, o); }
  public Optional<Order> byId(UUID id){ return Optional.ofNullable(store.get(id)); }
}

/* ====== Application Services ====== */
final class CatalogService {
  private final ProductRepository products;
  CatalogService(ProductRepository p){ this.products = p; }
  void seed() {
    products.save(new Product("SKU-1", "Coffee Beans", new Money("9.90","EUR")));
    products.save(new Product("SKU-2", "Espresso Machine", new Money("199.00","EUR")));
  }
  Product requireProduct(String sku){
    return products.bySku(sku).orElseThrow(() -> new IllegalArgumentException("Unknown SKU "+sku));
  }
}

final class PaymentService {
  // In a monolith this is an in-process call; replace with PSP adapter later if needed.
  String charge(UUID orderId, Money amount, String token) {
    if (token == null || token.isBlank()) throw new IllegalArgumentException("bad token");
    // pretend to call PSP; always succeeds
    return "AUTH-" + orderId.toString().substring(0,8);
  }
}

final class OrderService {
  private final OrderRepository orders; private final CatalogService catalog; private final PaymentService payments;
  OrderService(OrderRepository o, CatalogService c, PaymentService p){ this.orders = o; this.catalog = c; this.payments = p; }

  UUID createAndPay(String email, Map<String,Integer> items, String paymentToken){
    // Begin transaction (DB tx in real life)
    Order order = new Order(UUID.randomUUID(), email);
    for (var e : items.entrySet()) {
      var product = catalog.requireProduct(e.getKey());
      order.addLine(product, e.getValue());
    }
    String auth = payments.charge(order.id, order.total(), paymentToken); // in-process call
    order.markPaid();
    orders.save(order);
    // Commit transaction
    System.out.println("[payment] " + auth + " for " + order.total());
    return order.id;
  }

  Optional<Order> get(UUID id){ return orders.byId(id); }
}

/* ====== Presentation (HTTP) ====== */
public class MonolithDemo {
  public static void main(String[] args) throws Exception {
    var productRepo = new InMemoryProductRepo();
    var orderRepo   = new InMemoryOrderRepo();
    var catalog     = new CatalogService(productRepo); catalog.seed();
    var payments    = new PaymentService();
    var orders      = new OrderService(orderRepo, catalog, payments);

    HttpServer server = HttpServer.create(new InetSocketAddress(8080), 0);
    server.createContext("/order", ex -> handleOrder(ex, orders));
    server.createContext("/status", ex -> handleStatus(ex, orders));
    server.setExecutor(java.util.concurrent.Executors.newFixedThreadPool(8));
    server.start();
    System.out.println("Monolith listening on http://localhost:8080");
  }

  static void handleOrder(HttpExchange ex, OrderService orders) throws IOException {
    if (!"POST".equalsIgnoreCase(ex.getRequestMethod())) { ex.sendResponseHeaders(405, -1); return; }
    // Very naive parsing: body like "email=a@b.com&token=tok&items=SKU-1:2,SKU-2:1"
    var body = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
    var params = parse(body);
    Map<String,Integer> items = new LinkedHashMap<>();
    for (String pair : params.getOrDefault("items","").split(",")) {
      if (pair.isBlank()) continue;
      var kv = pair.split(":"); items.put(kv[0], Integer.parseInt(kv[1]));
    }
    try {
      var id = orders.createAndPay(params.get("email"), items, params.get("token"));
      sendJson(ex, 200, "{\"orderId\":\""+id+"\"}");
    } catch (Exception e) {
      sendJson(ex, 400, "{\"error\":\""+e.getMessage().replace("\"","'")+"\"}");
    }
  }

  static void handleStatus(HttpExchange ex, OrderService orders) throws IOException {
    var q = ex.getRequestURI().getQuery();
    var params = parse(q == null ? "" : q);
    try {
      var id = UUID.fromString(params.get("id"));
      var o = orders.get(id).orElseThrow();
      sendJson(ex, 200, "{\"id\":\""+o.id+"\",\"status\":\""+o.status+"\",\"total\":\""+o.total()+"\"}");
    } catch (Exception e) {
      sendJson(ex, 404, "{\"error\":\"not_found\"}");
    }
  }

  static Map<String,String> parse(String s){
    Map<String,String> m = new HashMap<>(); if (s==null) return m;
    for (String p : s.split("&")) {
      if (p.isBlank()) continue;
      var kv = p.split("=",2);
      m.put(kv[0], kv.length>1 ? kv[1] : "");
    }
    return m;
  }
  static void sendJson(HttpExchange ex, int code, String json) throws IOException {
    ex.getResponseHeaders().add("Content-Type","application/json");
    var bytes = json.getBytes(StandardCharsets.UTF_8);
    ex.sendResponseHeaders(code, bytes.length);
    try (OutputStream os = ex.getResponseBody()) { os.write(bytes); }
  }
}
```

**What the sample shows**

-   Everything (controllers, services, domain, repos) lives in **one process**.
    
-   **In-process** service composition (`OrderService` → `PaymentService`).
    
-   A single place to introduce **transactions, logging, metrics**.
    
-   Clear starting point for evolving to a **modular monolith** (stronger internal boundaries) or later extraction.
    

## Known Uses

-   Early versions of many products (e-commerce shops, SaaS backends).
    
-   Enterprise apps deployed as a **single WAR/JAR** (Spring Boot/Jakarta EE).
    
-   Heavy **transactional systems** where global ACID is essential and throughput fits on a single scalable tier.
    

## Related Patterns

-   **Layered Architecture** — common internal structure of monoliths.
    
-   **Modular Architecture / Modular Monolith** — strong internal boundaries inside a single deployable.
    
-   **Microkernel** — small core with plug-ins, still a monolith deployable.
    
-   **Microservices** — decomposed deployables; often an evolution path from monolith.
    
-   **Hexagonal/Clean Architecture** — adapter isolation within a monolith.
    

---

## Implementation Tips

-   Keep **module boundaries** even in a monolith (ports/facades), so extraction later is feasible.
    
-   Make the monolith **stateless** at the web tier (sessions in cookies/redis) to allow horizontal scaling.
    
-   Instrument with **metrics/tracing** from day one; central logs make debugging easy.
    
-   Use **feature flags** to decouple deploy from release and reduce blast radius.
    
-   Apply **migrations** carefully (expand/contract) to avoid downtime.
    
-   Periodically **architecture review** dependency graphs to prevent erosion.

