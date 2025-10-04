# Modular Architecture — Software Architecture Pattern

## Pattern Name and Classification

-   **Name:** Modular Architecture
    
-   **Classification:** Structural Architectural Style / Modularity & Encapsulation / “Modular Monolith” (when in one deployable) or Multi-Module System
    

## Intent

Decompose a system into **independent, cohesive modules** with **explicit contracts** and **hidden internals** so teams can develop, test, deploy (optionally), and evolve features **in isolation** while composing them into a coherent whole.

## Also Known As

-   Modular Monolith (single process)
    
-   Component-Based Architecture
    
-   Package-by-Feature (at code level)
    
-   Feature Modules / Business Capabilities
    

## Motivation (Forces)

-   **Change isolation:** Reduce blast radius of changes and regressions.
    
-   **Parallel work:** Multiple teams iterate without stepping on each other.
    
-   **Replaceability:** Swap or version modules without touching others.
    
-   **Governance:** Prevent “spaghetti” dependencies with explicit APIs and boundaries.
    
-   **Performance/Simplicity:** Keep single-process performance but with microservice-like boundaries.
    

Tension points:

-   **Granularity:** Too small → overhead; too large → coupling returns.
    
-   **Shared data:** Encapsulation vs. cross-module queries.
    
-   **Runtime composition:** Static linking vs. dynamic discovery/loading.
    

## Applicability

Use when:

-   A single deployable is preferred (latency, ops), but you need **strong internal boundaries**.
    
-   Product is organized around **business capabilities** (Orders, Billing, Catalog, Users).
    
-   Teams require **independent delivery** inside a monolith (feature toggles, module versions).
    
-   You plan to **strangle** legacy parts gradually behind module contracts.
    

Avoid or adapt when:

-   You need **independent scaling/failure isolation** across network boundaries → consider microservices.
    
-   Domain is tiny (modularity overhead not worth it).
    

## Structure

-   **Module:** Cohesive code + data + configuration with a **public API** and **private internals**.
    
-   **Contract (Port/SPI):** Interfaces owned by a module; other modules depend on them, not internals.
    
-   **Module Facade:** Stable entry point for the module’s public operations.
    
-   **Module Registry/Container:** Wires modules together, enforces allowed dependencies.
    
-   **Optional Runtime Plugin Loader:** Allows dynamic module discovery (e.g., ServiceLoader/OSGi/JPMS).
    

```sql
+-----------------+       +-----------------+
        |   Order Module  | <---> |  Payment Module |
        |  (uses Catalog) |       |   (uses Bank)   |
        +--------+--------+       +--------+--------+
                 |                         ^
                 v                         |
           +-----+------+           +------+-----+
           |  Catalog   |  <------  |  Bank Port | (SPI)
           |   API      |           +------------+
           +------------+
```

**Rules**

-   Dependencies are **acyclic** and **declared**.
    
-   Each module owns its **data schema**; others access through its API/events.
    
-   Cross-cutting concerns via **shared libraries** or **interceptors**, not ad-hoc calls.
    

## Participants

-   **Module** — a unit with public API (facade/ports), private domain logic, and persistence.
    
-   **Contracts/Ports** — interfaces exposed for others (and SPIs for pluggable implementations).
    
-   **Adapters** — implementations for external things (DB, HTTP, MQ) hidden behind ports.
    
-   **Module Registry** — composes modules, checks dependency rules, provides lookup.
    
-   **Configuration/Feature Flags** — enable/disable or version modules.
    

## Collaboration

1.  **Bootstrap** builds the module graph (or discovers modules dynamically).
    
2.  A **caller module** invokes another **via its public API** (synchronous call) or subscribes to **domain events** (asynchronous).
    
3.  Modules persist **their own state**; shared reads happen via **queries/DTOs** or **read models** (no foreign table writes).
    
4.  Cross-cutting policy (logging, auth) is enforced at **module boundaries**.
    

## Consequences

**Benefits**

-   Clear **team ownership** and **change isolation**.
    
-   **Replaceable** implementations behind stable contracts.
    
-   **Testability**: unit + contract tests per module; fast integration inside a process.
    
-   **Evolution path** to microservices (lift a module out when needed).
    

**Liabilities**

-   Requires **discipline** (enforce boundaries with tooling).
    
-   Data sharing needs **APIs or events**, not direct joins → may add queries/projections.
    
-   Versioning and **binary compatibility** of contracts must be managed.
    
-   If over-modularized, you pay a **ceremony tax**.
    

## Implementation

### Design Guidelines

-   **Package by feature** (`order`, `catalog`, `billing`) rather than by technical layer.
    
-   Each module exposes a **facade** and **ports**; keep domain private.
    
-   Use **compile-time boundaries** (multi-module build, JPMS `module-info.java`, ArchUnit rules).
    
-   Keep a **Module Registry** that wires dependencies explicitly (constructor injection).
    
-   Prefer **events** for cross-module notifications; use **queries** or **read models** for reporting.
    
-   **No shared mutable state** across modules; only value DTOs at the boundary.
    
-   Cross-cutting policies via **interceptors/decorators** on module facades.
    

### Enforcement Tools

-   Build graph (Gradle/Maven submodules)
    
-   Java Platform Module System (JPMS) exports/opens per module
    
-   ArchUnit rules to forbid package access across modules
    
-   Contract tests (provider/consumer)
    

---

## Sample Code (Java 17, framework-agnostic)

Small **modular monolith** demonstrating:

-   `Catalog` module exposes `CatalogApi`
    
-   `Order` module depends only on `CatalogApi` (not internals)
    
-   `ModuleRegistry` wires everything; a simple policy decorator adds logging
    
-   Modules keep their **own state** (in-memory here)
    

> For brevity, multiple classes appear in one file; in real projects, place them in separate packages/modules.

```java
import java.math.BigDecimal;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/* ========== Shared Contracts (published APIs) ========== */
interface CatalogApi {
  Optional<ProductView> findBySku(String sku);
  record ProductView(String sku, String name, BigDecimal price) {}
}

interface OrderApi {
  UUID placeOrder(String customerEmail, List<OrderLine> lines);
  record OrderLine(String sku, int qty) {}
}

/* ========== Catalog Module (owns products) ========== */
final class CatalogModule implements CatalogApi {
  private final Map<String, Product> products = new ConcurrentHashMap<>();

  /* public API */
  @Override public Optional<ProductView> findBySku(String sku) {
    var p = products.get(sku);
    return Optional.ofNullable(p).map(x -> new ProductView(x.sku, x.name, x.price));
  }

  /* module-internal domain (hidden) */
  static final class Product {
    final String sku; final String name; final BigDecimal price;
    Product(String sku, String name, BigDecimal price) {
      if (sku == null || sku.isBlank()) throw new IllegalArgumentException("sku");
      this.sku = sku; this.name = name; this.price = price;
    }
  }

  /* module-private API for seeding */
  void seed(Product p) { products.put(p.sku, p); }
}

/* ========== Order Module (uses CatalogApi; owns orders) ========== */
final class OrderModule implements OrderApi {
  private final CatalogApi catalog; // depends only on contract
  private final Map<UUID, Order> orders = new ConcurrentHashMap<>();

  OrderModule(CatalogApi catalog) { this.catalog = catalog; }

  @Override public UUID placeOrder(String customerEmail, List<OrderLine> lines) {
    if (lines == null || lines.isEmpty()) throw new IllegalArgumentException("no lines");
    UUID id = UUID.randomUUID();
    Order o = new Order(id, customerEmail);
    for (OrderLine l : lines) {
      var p = catalog.findBySku(l.sku()).orElseThrow(() -> new IllegalArgumentException("unknown sku " + l.sku()));
      o.addLine(p.sku(), p.name(), l.qty(), p.price());
    }
    o.confirm();
    orders.put(id, o);
    return id;
  }

  /* module-internal domain */
  static final class Order {
    enum Status { NEW, CONFIRMED }
    final UUID id; final String customerEmail; final Instant createdAt = Instant.now();
    Status status = Status.NEW; final List<Line> lines = new ArrayList<>();
    record Line(String sku, String name, int qty, BigDecimal pricePerUnit) {}
    Order(UUID id, String customerEmail){ this.id = id; this.customerEmail = customerEmail; }
    void addLine(String sku, String name, int qty, BigDecimal p) {
      if (qty <= 0) throw new IllegalArgumentException("qty>0");
      lines.add(new Line(sku, name, qty, p));
    }
    void confirm() {
      if (lines.isEmpty()) throw new IllegalStateException("empty");
      status = Status.CONFIRMED;
    }
    BigDecimal total() {
      return lines.stream()
        .map(l -> l.pricePerUnit().multiply(BigDecimal.valueOf(l.qty())))
        .reduce(BigDecimal.ZERO, BigDecimal::add);
    }
  }
}

/* ========== Decorators / Cross-cutting at module boundaries ========== */
final class LoggingOrderApi implements OrderApi {
  private final OrderApi delegate;
  LoggingOrderApi(OrderApi d) { this.delegate = d; }
  @Override public UUID placeOrder(String customerEmail, List<OrderLine> lines) {
    long t0 = System.nanoTime();
    UUID id = delegate.placeOrder(customerEmail, lines);
    long dt = (System.nanoTime() - t0) / 1_000_000;
    System.out.println("[OrderApi] placed order " + id + " in " + dt + " ms");
    return id;
  }
}

/* ========== Module Registry (composition root) ========== */
final class ModuleRegistry {
  private final Map<Class<?>, Object> registry = new HashMap<>();

  public <T> void provide(Class<T> api, T impl) { registry.put(api, impl); }
  @SuppressWarnings("unchecked")
  public <T> T require(Class<T> api) { return (T) registry.get(api); }

  static ModuleRegistry boot() {
    ModuleRegistry r = new ModuleRegistry();

    // build Catalog module and seed data
    CatalogModule catalog = new CatalogModule();
    catalog.seed(new CatalogModule.Product("SKU-1", "Coffee Beans", new BigDecimal("9.90")));
    catalog.seed(new CatalogModule.Product("SKU-2", "Espresso Machine", new BigDecimal("199.00")));
    r.provide(CatalogApi.class, catalog);

    // build Order module and wrap with logging decorator
    OrderModule orderCore = new OrderModule(r.require(CatalogApi.class));
    OrderApi orderApi = new LoggingOrderApi(orderCore);
    r.provide(OrderApi.class, orderApi);

    return r;
  }
}

/* ========== Demo ========== */
public class ModularArchitectureDemo {
  public static void main(String[] args) {
    ModuleRegistry registry = ModuleRegistry.boot();

    OrderApi orders = registry.require(OrderApi.class);
    UUID id = orders.placeOrder("alice@example.com", List.of(
        new OrderApi.OrderLine("SKU-1", 2),
        new OrderApi.OrderLine("SKU-2", 1)
    ));
    System.out.println("Order placed: " + id);

    CatalogApi catalog = registry.require(CatalogApi.class);
    System.out.println("Lookup SKU-1 -> " + catalog.findBySku("SKU-1").orElseThrow());
  }
}
```

**What this illustrates**

-   **Public contracts** (`CatalogApi`, `OrderApi`) and **hidden internals**.
    
-   **No direct access** to another module’s data—only via API.
    
-   **Composition root** (`ModuleRegistry`) to wire modules and apply cross-cutting decorators.
    
-   Easy to **swap** an implementation (e.g., remote Catalog) by changing only the registry wiring.
    

> Productionizing ideas: make each module its own Gradle/Maven submodule or JPMS module with `module-info.java`, enforce boundaries with ArchUnit, introduce an **event bus** for async collaboration, and add **feature flags** to toggle modules.

## Known Uses

-   **Modular monoliths** in large enterprise backends (Orders, Billing, Users as modules).
    
-   **IDEs/build tools** (Gradle/Maven subprojects) using explicit module graphs.
    
-   **ERP/CRM platforms** where customers enable different capability modules.
    
-   **E-commerce** platforms: payments, catalog, promotions as separate modules within one deployment.
    

## Related Patterns

-   **Hexagonal / Clean Architecture:** modules expose ports and keep adapters at the edges.
    
-   **Microkernel:** a small kernel with pluggable modules; modular architecture is a broader umbrella.
    
-   **Microservices:** splits modules into separate processes; modular architecture is often a precursor.
    
-   **CQRS:** can be applied inside modules to split read/write models.
    
-   **Event-Driven Architecture:** modules communicate via events for loose coupling.
    

---

## Implementation Tips

-   Start with **capability-oriented modules** (bounded contexts).
    
-   Put a **facade** at each module boundary; never expose entities.
    
-   Use **contracts** (interfaces + DTOs) and **contract tests** for consumers/providers.
    
-   Enforce **compile-time** and **runtime** boundaries (JPMS, ArchUnit, composition root).
    
-   Prefer **events** for cross-module notifications; avoid direct DB access across modules.
    
-   Maintain a **dependency graph** and keep it acyclic; automate checks in CI.
    
-   Document **versioning policy** for contracts and deprecation windows.

