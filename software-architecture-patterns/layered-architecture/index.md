# Layered Architecture — Software Architecture Pattern

## Pattern Name and Classification

-   **Name:** Layered Architecture
    
-   **Classification:** Structural Architectural Style / “n-tier” (Presentation–Application–Domain–Data)
    

## Intent

Organize a system into **horizontal layers** with clear responsibilities and **one-directional dependencies** (top → down). Each higher layer uses services of the layer below but remains **independent of its implementation details**, improving separation of concerns, testability, and replaceability.

## Also Known As

-   N-Tier Architecture
    
-   3-Tier / 4-Tier (e.g., Presentation, Application/Service, Domain, Data)
    
-   Traditional Enterprise Layering
    

## Motivation (Forces)

-   **Change isolation:** UI, business rules, and data access evolve at different speeds.
    
-   **Team specialization:** Different teams own UI, services, and persistence.
    
-   **Testability:** Business logic should be testable without UI or DB.
    
-   **Governance:** Enforce rules (no UI → DB shortcuts; all access via services).
    
-   **Simplicity vs. Flexibility:** Provide a simple default structure for most enterprise apps while avoiding tight coupling across concerns.
    

## Applicability

Use when:

-   Building information systems with **CRUD-heavy workflows** and stable, well-known boundaries.
    
-   You need a **straightforward structure** that scales to multiple teams.
    
-   The system exposes multiple UIs (web, mobile) on the same application services.
    
-   You rely on **relational/transactional persistence** and classic business rules.
    

Avoid or refine when:

-   You require **high autonomy** of components or frequent technology swaps → consider **Hexagonal/Clean**.
    
-   Cross-layer orchestration is complex or you need **event-driven** interactions → consider **EDA/CQRS**.
    
-   Too many layers introduce latency and ceremony for simple apps.
    

## Structure

Common 4-layer variant (top to bottom):

1.  **Presentation (UI)** — controllers, views; maps requests to application services.
    
2.  **Application (Service)** — orchestration/use cases; coordinates domain operations; no infrastructure details.
    
3.  **Domain (Model)** — entities, value objects, domain services, invariants.
    
4.  **Data Access (Infrastructure)** — repositories/DAOs, mappers, external systems (DB, MQ).
    

**Dependency rule:** Presentation → Application → Domain → Data Access (no back calls upward; no skips).

```pgsql
+------------------+   HTTP/CLI/Jobs
|  Presentation    |   (Controllers, Views, DTOs)
+------------------+   uses
          |
          v
+------------------+   Application / Services (Use-case orchestration)
|   Application    |   transactions, security, validation
+------------------+
          |
          v
+------------------+   Domain (Entities, Value Objects, Domain Services)
|      Domain      |   business rules & invariants
+------------------+
          |
          v
+------------------+   Data Access / Infrastructure (Repositories, DB, External APIs)
|   Data Access    |
+------------------+
```

## Participants

-   **Controller / Presenter (Presentation)** — converts requests to service calls; prepares view models.
    
-   **Application Service** — coordinates use cases, transactions, security checks.
    
-   **Domain Entity / Value Object / Domain Service** — encapsulate business rules and invariants.
    
-   **Repository/DAO (Data Access)** — abstracts persistence; maps between domain and storage.
    
-   **Mappers/DTOs** — isolate layer data shapes; avoid leaking framework types inward.
    

## Collaboration

1.  **Controller** receives request, validates input, converts to a **DTO**, calls an **Application Service**.
    
2.  **Application Service** uses **Domain** entities/services to enforce rules, then calls **Repositories** to persist/fetch.
    
3.  **Repository** performs DB operations and returns domain objects.
    
4.  **Application Service** returns an **Output DTO**; **Controller** renders the response.
    

## Consequences

**Benefits**

-   **Separation of concerns**; easier team ownership and onboarding.
    
-   **Testability:** Domain/Application layers testable without UI/DB.
    
-   **Replaceability:** Swap UI or DB with limited impact (if boundaries are respected).
    
-   **Simplicity:** Familiar pattern; good default for enterprise systems.
    

**Liabilities**

-   Risk of **anemic domain** if all logic sits in services.
    
-   **Over-layering** can add ceremony/latency.
    
-   Temptation to **bypass rules** (UI calling DAOs); requires discipline/tooling.
    
-   Harder to reflect **complex cross-cutting flows** than hexagonal/event-driven styles.
    

## Implementation

### Design Guidelines

-   Enforce dependency direction (use **ArchUnit**, module boundaries).
    
-   Keep **domain pure** (no framework annotations if possible).
    
-   Use **DTOs at boundaries**; do not leak transport or JPA entities across layers.
    
-   **Transactions** at Application layer boundaries; repositories do not open/close them.
    
-   Centralize **validation and authorization** near the Application layer.
    
-   Prefer **interfaces** for repositories; inject concrete implementations from Data layer.
    
-   Logging/metrics at boundaries; domain remains infrastructure-agnostic.
    

### Layer Mapping (example modules)

-   `web` (presentation), `application`, `domain`, `persistence` (data access), `bootstrap` (wiring).
    

---

## Sample Code (Java 17, framework-agnostic)

> Minimal 4-layer example for **Customer & Order**. Replace in-memory persistence with JPA/JDBC adapters without changing Application/Domain.

### Domain Layer (`domain`)

```java
// domain/Email.java
package domain;
public record Email(String value) {
  public Email {
    if (value == null || !value.matches("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$"))
      throw new IllegalArgumentException("invalid email");
  }
}
```

```java
// domain/Customer.java
package domain;
import java.util.UUID;

public class Customer {
  private final UUID id;
  private final Email email;
  private String name;

  public Customer(UUID id, Email email, String name) {
    this.id = id; this.email = email; rename(name);
  }
  public void rename(String newName) {
    if (newName == null || newName.isBlank()) throw new IllegalArgumentException("name");
    this.name = newName;
  }
  public UUID id() { return id; }
  public Email email() { return email; }
  public String name() { return name; }
}
```

```java
// domain/Order.java
package domain;
import java.math.BigDecimal;
import java.util.*;

public class Order {
  public enum Status { NEW, CONFIRMED }
  private final UUID id;
  private final UUID customerId;
  private final List<Line> lines = new ArrayList<>();
  private Status status = Status.NEW;

  public record Line(String sku, int qty, BigDecimal pricePerUnit) {}

  public Order(UUID id, UUID customerId) { this.id = id; this.customerId = customerId; }

  public void addLine(String sku, int qty, BigDecimal price) {
    if (status != Status.NEW) throw new IllegalStateException("order not modifiable");
    if (qty <= 0) throw new IllegalArgumentException("qty>0");
    lines.add(new Line(sku, qty, price));
  }
  public void confirm() {
    if (lines.isEmpty()) throw new IllegalStateException("empty order");
    status = Status.CONFIRMED;
  }
  public BigDecimal total() {
    return lines.stream()
      .map(l -> l.pricePerUnit().multiply(BigDecimal.valueOf(l.qty())))
      .reduce(BigDecimal.ZERO, BigDecimal::add);
  }
  public UUID id(){ return id; }
  public UUID customerId(){ return customerId; }
  public Status status(){ return status; }
  public List<Line> lines(){ return List.copyOf(lines); }
}
```

### Data Access Layer (`persistence`)

```java
// persistence/CustomerRepository.java
package persistence;
import domain.Customer;
import java.util.*;

public interface CustomerRepository {
  Optional<Customer> byEmail(String email);
  Optional<Customer> byId(UUID id);
  Customer save(Customer c);
}
```

```java
// persistence/OrderRepository.java
package persistence;
import domain.Order;
import java.util.*;

public interface OrderRepository {
  Optional<Order> byId(UUID id);
  Order save(Order o);
}
```

```java
// persistence/inmemory/InMemoryRepositories.java
package persistence.inmemory;
import persistence.*;
import domain.*;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

public class InMemoryCustomerRepository implements CustomerRepository {
  private final Map<UUID, Customer> byId = new ConcurrentHashMap<>();
  private final Map<String, UUID> byEmail = new ConcurrentHashMap<>();

  public Optional<Customer> byEmail(String email){ return Optional.ofNullable(byEmail.get(email)).map(byId::get); }
  public Optional<Customer> byId(UUID id){ return Optional.ofNullable(byId.get(id)); }
  public Customer save(Customer c){ byId.put(c.id(), c); byEmail.put(c.email().value(), c.id()); return c; }
}

public class InMemoryOrderRepository implements OrderRepository {
  private final Map<UUID, Order> store = new ConcurrentHashMap<>();
  public Optional<Order> byId(UUID id){ return Optional.ofNullable(store.get(id)); }
  public Order save(Order o){ store.put(o.id(), o); return o; }
}
```

### Application Layer (`application`)

```java
// application/dto/CustomerDTOs.java
package application.dto;
import java.util.UUID;

public record RegisterCustomerRequest(String email, String name) {}
public record RegisterCustomerResponse(UUID customerId, String email, String name) {}
```

```java
// application/dto/OrderDTOs.java
package application.dto;
import java.math.BigDecimal;
import java.util.*;

public record AddItemRequest(String sku, int qty, BigDecimal unitPrice) {}
public record CreateOrderRequest(java.util.UUID customerId, List<AddItemRequest> lines) {}
public record OrderResponse(java.util.UUID orderId, String status, BigDecimal total) {}
```

```java
// application/CustomerService.java
package application;
import application.dto.*;
import persistence.CustomerRepository;
import domain.Customer;
import domain.Email;
import java.util.UUID;

public class CustomerService {
  private final CustomerRepository customers;
  public CustomerService(CustomerRepository customers){ this.customers = customers; }

  public RegisterCustomerResponse register(RegisterCustomerRequest req){
    customers.byEmail(req.email()).ifPresent(c -> { throw new IllegalStateException("email exists"); });
    var c = new Customer(UUID.randomUUID(), new Email(req.email()), req.name());
    customers.save(c);
    return new RegisterCustomerResponse(c.id(), c.email().value(), c.name());
  }
}
```

```java
// application/OrderService.java
package application;
import application.dto.*;
import persistence.*;
import domain.Order;
import java.util.UUID;

public class OrderService {
  private final OrderRepository orders;
  private final CustomerRepository customers;

  public OrderService(OrderRepository orders, CustomerRepository customers){
    this.orders = orders; this.customers = customers;
  }

  public OrderResponse createAndConfirm(CreateOrderRequest req){
    customers.byId(req.customerId()).orElseThrow(() -> new IllegalArgumentException("customer not found"));
    Order o = new Order(UUID.randomUUID(), req.customerId());
    for (var line : req.lines()) o.addLine(line.sku(), line.qty(), line.unitPrice());
    o.confirm();
    orders.save(o);
    return new OrderResponse(o.id(), o.status().name(), o.total());
  }
}
```

### Presentation Layer (`web`) – a tiny controller facade

```java
// web/ApiController.java
package web;
import application.CustomerService;
import application.OrderService;
import application.dto.*;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import java.util.UUID;

public class ApiController {
  private final CustomerService customerService;
  private final OrderService orderService;

  public ApiController(CustomerService c, OrderService o){ this.customerService = c; this.orderService = o; }

  public Map<String,Object> postRegister(String email, String name){
    var res = customerService.register(new RegisterCustomerRequest(email, name));
    return Map.of("customerId", res.customerId().toString(), "email", res.email(), "name", res.name());
    // In a real server, serialize to JSON and set status codes.
  }

  public Map<String,Object> postCreateOrder(String customerId){
    var req = new CreateOrderRequest(UUID.fromString(customerId),
      List.of(new AddItemRequest("SKU-1", 2, new BigDecimal("19.90")),
              new AddItemRequest("SKU-9", 1, new BigDecimal("49.00"))));
    var res = orderService.createAndConfirm(req);
    return Map.of("orderId", res.orderId().toString(), "status", res.status(), "total", res.total().toPlainString());
  }
}
```

### Bootstrap (`bootstrap`)

```java
// bootstrap/App.java
package bootstrap;
import web.ApiController;
import application.*;
import persistence.inmemory.*;
import persistence.*;

public class App {
  public static void main(String[] args) {
    CustomerRepository customerRepo = new InMemoryCustomerRepository();
    OrderRepository orderRepo = new InMemoryOrderRepository();

    var customerService = new CustomerService(customerRepo);
    var orderService = new OrderService(orderRepo, customerRepo);

    var api = new ApiController(customerService, orderService);

    // Simulate requests
    var reg = api.postRegister("alice@example.com", "Alice");
    System.out.println("REGISTER -> " + reg);
    var ord = api.postCreateOrder((String) reg.get("customerId"));
    System.out.println("ORDER    -> " + ord);
  }
}
```

**What this shows**

-   Clear, **one-way dependencies**: `web → application → domain → persistence`.
    
-   **Domain** is framework-free; **Application** orchestrates use cases; **Persistence** is swappable; **Presentation** holds transport concerns.
    
-   Easy to replace `InMemory` with JPA/JDBC without touching `application` or `domain`.
    

---

## Known Uses

-   Classic enterprise systems: **Java EE/.NET** n-tier apps, **Spring MVC + Service + Repository**, **Jakarta EE** (JSF/Servlets + EJB/Spring services + JPA).
    
-   Web frameworks (Django/Rails/.NET MVC) conceptually follow layered separation (views/controllers vs. models vs. data access).
    
-   Internal business apps with stable CRUD and transaction boundaries.
    

## Related Patterns

-   **Hexagonal / Ports & Adapters, Clean/Onion** — emphasize inward dependencies and adapter isolation (a stricter take on layering).
    
-   **CQRS** — splits reads/writes; can be applied inside Application/Data layers.
    
-   **Client–Server** — macro distribution style; layering refines the server internals.
    
-   **Microkernel** — plugin-oriented core (alternative structuring).
    
-   **Broker / EDA** — integration styles that can appear at the infrastructure boundary.
    

---

## Implementation Tips

-   Keep **business rules in Domain**, not in controllers or repositories.
    
-   Use **DTOs** to cross presentation/application boundaries; map explicitly.
    
-   Apply **transactions** around application service methods; keep repositories simple.
    
-   Enforce **no skipping layers** (e.g., controllers must not access repositories directly).
    
-   Add **cross-cutting concerns** (auth, logging, metrics, validation) at layer edges via interceptors/aspects/middleware.
    
-   Use **package-by-feature** inside layers (e.g., `customer`, `order`) to keep cohesion.
    
-   Validate with **ArchUnit** or build-module rules to prevent dependency drift.

