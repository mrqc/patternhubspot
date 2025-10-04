# Clean Architecture — Software Architecture Pattern

## Pattern Name and Classification

-   **Name:** Clean Architecture
    
-   **Classification:** Architectural Style / Layered + Hexagonal / Dependency Inversion–centric
    

## Intent

Create systems that are **independent of frameworks, UI, databases, and external agencies** by organizing code into concentric layers with **inward-pointing dependencies**. Business rules sit at the center; outer details can be swapped without changing core logic.

## Also Known As

-   Onion Architecture (closely related)
    
-   Hexagonal Architecture (Ports & Adapters)
    
-   Screaming Architecture (features drive structure)
    

## Motivation (Forces)

-   **Volatile details** (web frameworks, ORMs, DBs, UIs, message brokers) change faster than business rules.
    
-   **Testability** suffers when core logic depends on heavy infrastructure.
    
-   **Maintainability & evolvability** require stable boundaries and explicit interfaces.
    
-   **Separation of concerns** avoids transaction, transport, and UI leaking into domain logic.  
    Clean Architecture addresses these by **inverting dependencies**: inner layers define interfaces (ports); outer layers implement them (adapters).
    

## Applicability

Use when:

-   Business rules must remain stable while interfaces (DB/UI/transport) may change.
    
-   You need **high test coverage** of domain/use cases with fast, isolated tests.
    
-   Systems span multiple interfaces (REST + CLI + batch + messaging).
    
-   You anticipate switching persistence or frameworks with minimal friction.
    

## Structure

Concentric layers (dependencies always point inward):

1.  **Entities (Domain Model)** — enterprise-wide business rules.
    
2.  **Use Cases (Application)** — application-specific rules orchestrating entities; define **input/output models** and **ports**.
    
3.  **Interface Adapters** — translate between outer world and use-case ports (controllers, presenters, gateways/repositories).
    
4.  **Frameworks & Drivers** — DB, UI, HTTP, messaging, FS, third-party.
    

```pgsql
+------------------------+  outer: details (replaceable)
| Frameworks & Drivers   |  (Web, DB, UI, MQ, CLI)
+------------+-----------+
             |
+------------v-----------+  adapters (controllers, presenters, repos)
|   Interface Adapters   |
+------------+-----------+
             |
+------------v-----------+  application rules (ports, use cases)
|        Use Cases       |
+------------+-----------+
             |
+------------v-----------+  inner: enterprise rules
|        Entities        |
+------------------------+
(deps point inward only)
```

## Participants

-   **Entity** — rich domain object or aggregate with invariants.
    
-   **Use Case Interactor** — application service implementing a port; coordinates entities and repositories.
    
-   **Input/Output Models** — data structures crossing boundaries (no framework types).
    
-   **Ports (Interfaces)** — `Repository`, `Clock`, `EmailGateway`, etc., defined inward.
    
-   **Adapters (Implementations)** — `JpaOrderRepository`, `SpringMvcController`, `KafkaEmailGateway`.
    
-   **Presenter/ViewModel** — prepares data for a specific UI.
    
-   **Controllers** — map transport (HTTP, CLI) to input models.
    

## Collaboration

1.  Controller adapts an external request to a **Use Case Input Model**.
    
2.  Use case calls **ports** it owns (repositories/gateways).
    
3.  Entities enforce invariants; use case produces **Output Model**.
    
4.  Presenter converts output to **ViewModel/DTO**; adapter serializes to transport.
    
5.  Infrastructure (DB, web) is **plugged in** by implementing ports; no inward dependency.
    

## Consequences

**Benefits**

-   **Framework-agnostic**, **database-agnostic**; easy to swap details.
    
-   High **testability** (mock ports, test use cases in isolation).
    
-   **Screaming structure** by use-case packages instead of technical layers.
    
-   Separation of business logic from infrastructure enables longevity.
    

**Liabilities**

-   **More classes/interfaces** and initial ceremony.
    
-   Poorly chosen boundaries or anemic entities reduce benefits.
    
-   Requires discipline to keep dependencies pointing inward.
    

## Implementation

### Principles & Guidelines

-   **Dependency Rule:** Source code dependencies must point **inward**.
    
-   **Policy vs. Details:** Inner layers are **policy**; outer layers are **details**.
    
-   **DTOs across boundaries:** Never leak framework types (e.g., `HttpServletRequest`) into use cases.
    
-   **Persistence-ignorant domain:** No JPA annotations in core (or keep via separate mapping layer).
    
-   **Package by feature/use case** instead of horizontal technical layers.
    
-   **Pure functions where possible; side effects via ports.**
    
-   **Explicit transactions** in adapters (or coordinators) around use-case calls.
    

### Typical Gradle Modules

-   `domain` (entities, value objects)
    
-   `application` (use cases, ports, input/output models)
    
-   `adapters`
    
    -   `web` (controllers, presenters)
        
    -   `persistence` (JPA/JDBC/NoSQL impls)
        
    -   `messaging` (Kafka/SQS)
        
-   `bootstrap` (wiring, DI, Spring Boot main)
    

---

## Sample Code (Java)

Example use case: **Register a Customer** and **place an Order**. This shows entities, ports, interactors, and adapters. (Java 17+; Spring optional—kept minimal.)

### 1) Domain (Entities & Value Objects) — module `domain`

```java
// domain/Email.java
package domain;
import java.util.Objects;
public record Email(String value) {
  public Email {
    if (value == null || !value.matches("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$"))
      throw new IllegalArgumentException("invalid email");
  }
}

// domain/Money.java
package domain;
import java.math.BigDecimal;
import java.util.Objects;
public record Money(BigDecimal amount, String currency) {
  public Money {
    Objects.requireNonNull(amount); Objects.requireNonNull(currency);
    if (amount.signum() < 0) throw new IllegalArgumentException("negative");
  }
  public Money add(Money other){
    if (!currency.equals(other.currency)) throw new IllegalArgumentException("currency mismatch");
    return new Money(amount.add(other.amount), currency);
  }
}

// domain/Customer.java
package domain;
import java.util.UUID;
public class Customer {
  private final UUID id;
  private final Email email;
  private String name;
  public Customer(UUID id, Email email, String name) {
    this.id = id; this.email = email; this.name = name;
  }
  public UUID id(){ return id; }
  public Email email(){ return email; }
  public String name(){ return name; }
  public void rename(String newName){ if (newName == null || newName.isBlank()) throw new IllegalArgumentException("name"); this.name = newName; }
}

// domain/Order.java
package domain;
import java.time.Instant;
import java.util.*;
public class Order {
  private final UUID id;
  private final UUID customerId;
  private final List<Line> lines = new ArrayList<>();
  private Instant createdAt;
  public record Line(String sku, int qty, Money pricePerUnit){}
  public Order(UUID id, UUID customerId){
    this.id = id; this.customerId = customerId; this.createdAt = Instant.now();
  }
  public void addLine(String sku, int qty, Money price){
    if (qty <= 0) throw new IllegalArgumentException("qty");
    lines.add(new Line(sku, qty, price));
  }
  public Money total() {
    return lines.stream().map(l -> new Money(l.pricePerUnit().amount().multiply(java.math.BigDecimal.valueOf(l.qty())), l.pricePerUnit().currency()))
      .reduce((a,b) -> a.add(b)).orElse(new Money(java.math.BigDecimal.ZERO, "EUR"));
  }
  public UUID id(){ return id; }
  public UUID customerId(){ return customerId; }
  public List<Line> lines(){ return List.copyOf(lines); }
  public Instant createdAt(){ return createdAt; }
}
```

### 2) Application (Ports & Use Cases) — module `application`

```java
// application/ports/CustomerRepository.java
package application.ports;
import domain.Customer;
import java.util.*;
public interface CustomerRepository {
  Optional<Customer> byEmail(String email);
  Customer save(Customer c);
  Optional<Customer> byId(UUID id);
}

// application/ports/OrderRepository.java
package application.ports;
import domain.Order;
import java.util.Optional;
import java.util.UUID;
public interface OrderRepository {
  Order save(Order o);
  Optional<Order> byId(UUID id);
}

// application/ports/Clock.java
package application.ports;
import java.time.Instant;
public interface Clock { Instant now(); }

// application/usecases/RegisterCustomer.java
package application.usecases;
import application.ports.CustomerRepository;
import domain.Customer;
import domain.Email;
import java.util.UUID;

public final class RegisterCustomer {
  public record Input(String email, String name) {}
  public record Output(UUID customerId, String email, String name) {}
  private final CustomerRepository customers;
  public RegisterCustomer(CustomerRepository customers){ this.customers = customers; }

  public Output handle(Input in){
    customers.byEmail(in.email()).ifPresent(c -> { throw new IllegalStateException("email already registered"); });
    Customer c = new Customer(UUID.randomUUID(), new Email(in.email()), in.name());
    customers.save(c);
    return new Output(c.id(), c.email().value(), c.name());
  }
}

// application/usecases/PlaceOrder.java
package application.usecases;
import application.ports.CustomerRepository;
import application.ports.OrderRepository;
import domain.Money;
import domain.Order;
import java.util.UUID;

public final class PlaceOrder {
  public record Line(String sku, int qty, String currency, String amount) {}
  public record Input(UUID customerId, java.util.List<Line> lines){}
  public record Output(UUID orderId, String total) {}

  private final OrderRepository orders;
  private final CustomerRepository customers;

  public PlaceOrder(OrderRepository orders, CustomerRepository customers){
    this.orders = orders; this.customers = customers;
  }

  public Output handle(Input in){
    customers.byId(in.customerId()).orElseThrow(() -> new IllegalArgumentException("customer not found"));
    Order o = new Order(UUID.randomUUID(), in.customerId());
    for (Line l : in.lines()){
      o.addLine(l.sku(), l.qty(), new Money(new java.math.BigDecimal(l.amount()), l.currency()));
    }
    orders.save(o);
    return new Output(o.id(), o.total().amount().toPlainString() + " " + o.total().currency());
  }
}
```

### 3) Interface Adapters — `adapters` (Web Controller & Persistence)

```java
// adapters/web/CustomerController.java (plain Servlet-style or Spring; kept minimal)
package adapters.web;
import application.usecases.RegisterCustomer;
import application.usecases.PlaceOrder;
import jakarta.servlet.http.*;
import java.io.IOException;
import java.util.List;
import java.util.UUID;

public class CustomerController extends HttpServlet {
  private final RegisterCustomer registerCustomer;
  private final PlaceOrder placeOrder;
  public CustomerController(RegisterCustomer rc, PlaceOrder po){ this.registerCustomer = rc; this.placeOrder = po; }

  @Override protected void doPost(HttpServletRequest req, HttpServletResponse resp) throws IOException {
    String path = req.getPathInfo();
    resp.setContentType("application/json");
    if ("/register".equals(path)) {
      var out = registerCustomer.handle(new RegisterCustomer.Input(req.getParameter("email"), req.getParameter("name")));
      resp.getWriter().write("{\"id\":\""+out.customerId()+"\",\"email\":\""+out.email()+"\",\"name\":\""+out.name()+"\"}");
    } else if ("/order".equals(path)) {
      UUID cid = UUID.fromString(req.getParameter("customerId"));
      var line = new PlaceOrder.Line(req.getParameter("sku"), Integer.parseInt(req.getParameter("qty")), "EUR", req.getParameter("amount"));
      var out = placeOrder.handle(new PlaceOrder.Input(cid, List.of(line)));
      resp.getWriter().write("{\"orderId\":\""+out.orderId()+"\",\"total\":\""+out.total()+"\"}");
    } else {
      resp.setStatus(404);
    }
  }
}
```

```java
// adapters/persistence/InMemoryRepos.java
package adapters.persistence;
import application.ports.CustomerRepository;
import application.ports.OrderRepository;
import domain.Customer;
import domain.Order;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

public class InMemoryCustomerRepository implements CustomerRepository {
  private final Map<UUID, Customer> byId = new ConcurrentHashMap<>();
  private final Map<String, UUID> byEmail = new ConcurrentHashMap<>();
  public Optional<Customer> byEmail(String email){ return Optional.ofNullable(byEmail.get(email)).map(byId::get); }
  public Customer save(Customer c){ byId.put(c.id(), c); byEmail.put(c.email().value(), c.id()); return c; }
  public Optional<Customer> byId(UUID id){ return Optional.ofNullable(byId.get(id)); }
}

public class InMemoryOrderRepository implements OrderRepository {
  private final Map<UUID, Order> store = new ConcurrentHashMap<>();
  public Order save(Order o){ store.put(o.id(), o); return o; }
  public Optional<Order> byId(UUID id){ return Optional.ofNullable(store.get(id)); }
}
```

### 4) Bootstrap (Wiring / DI) — `bootstrap`

```java
// bootstrap/App.java
package bootstrap;
import adapters.persistence.InMemoryCustomerRepository;
import adapters.persistence.InMemoryOrderRepository;
import adapters.web.CustomerController;
import application.usecases.PlaceOrder;
import application.usecases.RegisterCustomer;

public class App {
  public static void main(String[] args) {
    var customerRepo = new InMemoryCustomerRepository();
    var orderRepo = new InMemoryOrderRepository();

    var registerCustomer = new RegisterCustomer(customerRepo);
    var placeOrder = new PlaceOrder(orderRepo, customerRepo);

    // Wire into your preferred web framework / DI container.
    // Example: register `new CustomerController(registerCustomer, placeOrder)` in your servlet container or Spring Boot config.
  }
}
```

**Notes**

-   The **application** module depends on **domain** only.
    
-   **Adapters** depend on **application** (to access ports) and implement them.
    
-   **Bootstrap** depends on all to wire implementations.
    
-   Replace in-memory repos with **JPA/JDBC adapters** without touching use cases.
    

---

## Known Uses

-   **Enterprise backends** that start with Spring Boot but keep core independent to later move to Micronaut/Quarkus.
    
-   **Android apps** adopting Clean Architecture to isolate UI (Jetpack) from business logic.
    
-   **Microservices** where domain and application modules are framework-free and adapters implement REST, messaging, and persistence.
    
-   **PCI/GxP systems** needing strong testability and technology isolation.
    

## Related Patterns

-   **Hexagonal (Ports & Adapters)** — emphasizes ports and environment isolation.
    
-   **Onion Architecture** — similar concentric layering with domain at center.
    
-   **CQRS** — can live inside the use-case layer to separate read/write models.
    
-   **Domain-Driven Design (DDD)** — strategic & tactical patterns for rich domains.
    
-   **Microkernel** — stable core with pluggable adapters.
    

---

## Implementation Tips

-   Make **use cases the unit of organization** (package-by-feature).
    
-   Keep **use-case input/output models** simple, serializable POJOs.
    
-   Apply **transaction management** at adapter/entry boundaries (e.g., AOP around use cases).
    
-   Write **contract tests** for adapters against ports; **unit tests** for use cases; minimal **e2e** for wiring.
    
-   Keep mapping between entities and persistence DTOs explicit (MapStruct or manual).
    
-   Enforce dependency direction with build tooling (ArchUnit, module boundaries).
    
-   Let the repo interfaces express domain language; hide query specifics behind ports.

