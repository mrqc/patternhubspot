# Hexagonal Architecture — Software Architecture Pattern

## Pattern Name and Classification

-   **Name:** Hexagonal Architecture
    
-   **Classification:** Architectural Style / Ports & Adapters / Dependency-Inversion–centric
    

## Intent

Isolate **domain and application logic** from technical details (UI, DB, messaging) by defining **ports** (interfaces) owned by the inside and implementing them with **adapters** on the outside. All dependencies point **inward** so details can change without touching core logic.

## Also Known As

-   Ports & Adapters
    
-   Onion Architecture (closely related)
    
-   Clean Architecture (family)
    

## Motivation (Forces)

-   **Volatile details vs. stable policy:** frameworks, drivers, and storage change faster than business rules.
    
-   **Testability:** core logic should run in memory without network/DB.
    
-   **Multiple I/O styles:** REST, CLI, batch, messaging—without duplicating business rules.
    
-   **Evolvability:** swap databases, brokers, UIs with minimal blast radius.  
    Hexagonal addresses these by letting the **domain own the interfaces** and pushing technical code to the edges as adapters.
    

## Applicability

Use when:

-   You need **framework/database independence** and high testability.
    
-   Multiple input/output channels must serve the **same use cases**.
    
-   You anticipate **tech churn** (ORM, API gateway, broker, search engine).
    
-   You want clearer **boundaries** in a microservice or a well-structured monolith.
    

## Structure

Layers (logical, not necessarily packages):

-   **Domain (Entities/Value Objects/Domain Services)**
    
-   **Application (Use Cases, Orchestrations, Ports)**
    
-   **Adapters**
    
    -   **Inbound adapters** (drive the app): REST controllers, CLI, jobs, message listeners → call use cases via input ports.
        
    -   **Outbound adapters** (driven by the app): DB repositories, email/SMS, payment, message brokers → implement output ports.
        
-   **Bootstrap/Wiring** (composition root/DI)
    

```pgsql
Inbound Adapters            Outbound Adapters
     (controllers, handlers)        (db, broker, http)
                │                            ▲
                ▼                            │
        +-----------------+   ports   +-----------------+
        |   Application   | <-------> |  Implementations|
        |  (Use Cases)    |           |   (Adapters)    |
        +--------+--------+           +--------+--------+
                 │                              ▲
                 ▼                              │
             +-------- Domain (entities, rules) --------+
                         (no fw/tech deps)
```

## Participants

-   **Entities/Value Objects** — business state + invariants.
    
-   **Use Case (Application Service)** — orchestrates entities; **owns ports**.
    
-   **Ports** — interfaces defined by the inside:
    
    -   **Input ports** — called by inbound adapters.
        
    -   **Output ports** — implemented by outbound adapters.
        
-   **Adapters** — translate and connect the outside world to ports (DTO mapping, protocol/driver code).
    
-   **Wiring** — builds the object graph (manual DI or framework).
    

## Collaboration

1.  An **inbound adapter** (e.g., REST controller) maps a request → **input port** call.
    
2.  The **use case** enforces rules, asks the domain to change state, and calls **output ports** to persist or integrate.
    
3.  **Outbound adapters** fulfill the port contracts (DB, HTTP, MQ).
    
4.  The use case returns an **output DTO** to the inbound adapter, which serializes it.
    

## Consequences

**Benefits**

-   **Independence from frameworks** and drivers; easy to test.
    
-   **Multiple interfaces** (HTTP/CLI/MQ) for the same core.
    
-   Safer **technology swaps** and upgrades.
    
-   Clear **dependency direction** and boundaries.
    

**Liabilities**

-   More classes and interfaces (initial overhead).
    
-   Requires discipline in mapping and boundaries.
    
-   Poorly designed ports can leak technology concerns inward.
    

## Implementation

### Guidelines

-   Define **ports** next to use cases; **domain never depends** on adapters.
    
-   Use **plain DTOs** for cross-boundary data (no framework types).
    
-   Keep **transactions** and **mapping** in adapters or thin application coordinators.
    
-   Prefer **package-by-feature** (e.g., `order`) over horizontal layering.
    
-   Enforce direction with tools (e.g., ArchUnit).
    
-   Tests: **unit** (use cases with fakes) + **contract** (adapters vs. ports) + **e2e** (happy paths).
    

---

## Sample Code (Java)

> Java 17, framework-agnostic (can be wired into Spring/Micronaut/Quarkus later).  
> Domain: simple **Order** with add-item & pay.  
> Ports: `OrderRepository` (DB) and `PaymentGateway` (external).  
> Inbound adapter: a minimal HTTP-like controller (plain methods).  
> Outbound adapters: in-memory repo and fake payment.

### 1) Domain (entities & values)

```java
// domain/Money.java
package domain;
import java.math.BigDecimal;
import java.util.Objects;

public record Money(BigDecimal amount, String currency) {
  public Money {
    Objects.requireNonNull(amount); Objects.requireNonNull(currency);
    if (amount.signum() < 0) throw new IllegalArgumentException("negative");
  }
  public Money add(Money other) {
    requireSameCurrency(other);
    return new Money(amount.add(other.amount), currency);
  }
  public Money multiply(int qty) {
    return new Money(amount.multiply(BigDecimal.valueOf(qty)), currency);
  }
  private void requireSameCurrency(Money other) {
    if (!currency.equals(other.currency))
      throw new IllegalArgumentException("currency mismatch");
  }
  @Override public String toString() { return amount.toPlainString() + " " + currency; }
}
```

```java
// domain/Order.java
package domain;
import java.time.Instant;
import java.util.*;

public class Order {
  public enum Status { NEW, PAID }

  private final UUID id;
  private final List<Line> lines = new ArrayList<>();
  private Status status = Status.NEW;
  private final Instant createdAt = Instant.now();

  public record Line(String sku, int qty, Money unitPrice) {}

  public Order(UUID id) { this.id = id; }

  public void addLine(String sku, int qty, Money unitPrice) {
    if (status != Status.NEW) throw new IllegalStateException("cannot modify after payment");
    if (qty <= 0) throw new IllegalArgumentException("qty>0");
    lines.add(new Line(sku, qty, unitPrice));
  }

  public Money total() {
    return lines.stream()
      .map(l -> l.unitPrice().multiply(l.qty()))
      .reduce((a,b) -> a.add(b)).orElse(new Money(java.math.BigDecimal.ZERO, "EUR"));
  }

  public void markPaid() {
    if (lines.isEmpty()) throw new IllegalStateException("empty order");
    if (status == Status.PAID) throw new IllegalStateException("already paid");
    status = Status.PAID;
  }

  public UUID id() { return id; }
  public Status status() { return status; }
  public List<Line> lines() { return List.copyOf(lines); }
  public Instant createdAt() { return createdAt; }
}
```

### 2) Application (ports & use cases)

```java
// app/ports/OrderRepository.java
package app.ports;
import domain.Order;
import java.util.*;

public interface OrderRepository {
  Optional<Order> byId(UUID id);
  void save(Order order);
}
```

```java
// app/ports/PaymentGateway.java
package app.ports;
import domain.Money;
import java.util.UUID;

public interface PaymentGateway {
  // returns authorization id or throws on failure
  String charge(UUID orderId, Money amount, String paymentMethodToken);
}
```

```java
// app/usecase/CreateOrder.java
package app.usecase;
import app.ports.OrderRepository;
import domain.Order;
import java.util.UUID;

public class CreateOrder {
  private final OrderRepository repo;
  public CreateOrder(OrderRepository repo) { this.repo = repo; }

  public record Output(UUID orderId) {}

  public Output handle() {
    var order = new Order(UUID.randomUUID());
    repo.save(order);
    return new Output(order.id());
  }
}
```

```java
// app/usecase/AddItemToOrder.java
package app.usecase;
import app.ports.OrderRepository;
import domain.Money;
import domain.Order;
import java.util.UUID;

public class AddItemToOrder {
  private final OrderRepository repo;
  public AddItemToOrder(OrderRepository repo) { this.repo = repo; }

  public record Input(UUID orderId, String sku, int qty, String price) {}
  public record Output(UUID orderId, String newTotal) {}

  public Output handle(Input in) {
    Order order = repo.byId(in.orderId()).orElseThrow(() -> new IllegalArgumentException("order not found"));
    order.addLine(in.sku(), in.qty(), new Money(new java.math.BigDecimal(in.price()), "EUR"));
    repo.save(order);
    return new Output(order.id(), order.total().toString());
  }
}
```

```java
// app/usecase/PayOrder.java
package app.usecase;
import app.ports.OrderRepository;
import app.ports.PaymentGateway;
import domain.Order;
import java.util.UUID;

public class PayOrder {
  private final OrderRepository repo;
  private final PaymentGateway payments;

  public PayOrder(OrderRepository repo, PaymentGateway payments) {
    this.repo = repo; this.payments = payments;
  }

  public record Input(UUID orderId, String paymentToken) {}
  public record Output(UUID orderId, String status, String authId, String total) {}

  public Output handle(Input in) {
    Order order = repo.byId(in.orderId()).orElseThrow(() -> new IllegalArgumentException("order not found"));
    var amount = order.total();
    String auth = payments.charge(order.id(), amount, in.paymentToken());
    order.markPaid();
    repo.save(order);
    return new Output(order.id(), order.status().name(), auth, amount.toString());
  }
}
```

### 3) Outbound Adapters (implement output ports)

```java
// adapters/outbound/InMemoryOrderRepository.java
package adapters.outbound;
import app.ports.OrderRepository;
import domain.Order;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

public class InMemoryOrderRepository implements OrderRepository {
  private final Map<UUID, Order> store = new ConcurrentHashMap<>();
  @Override public Optional<Order> byId(UUID id) { return Optional.ofNullable(store.get(id)); }
  @Override public void save(Order order) { store.put(order.id(), order); }
}
```

```java
// adapters/outbound/FakePaymentGateway.java
package adapters.outbound;
import app.ports.PaymentGateway;
import domain.Money;
import java.util.UUID;

public class FakePaymentGateway implements PaymentGateway {
  @Override public String charge(UUID orderId, Money amount, String token) {
    if (token == null || token.isBlank()) throw new IllegalArgumentException("invalid payment token");
    // pretend to call an external PSP
    return "AUTH-" + orderId.toString().substring(0,8);
  }
}
```

*(Replace these with JPA/JDBC and an HTTP client adapter in real deployments.)*

### 4) Inbound Adapter (controller)

```java
// adapters/inbound/OrderController.java
package adapters.inbound;
import app.usecase.*;
import java.util.Map;
import java.util.UUID;

public class OrderController {
  private final CreateOrder create;
  private final AddItemToOrder addItem;
  private final PayOrder pay;

  public OrderController(CreateOrder c, AddItemToOrder a, PayOrder p) {
    this.create = c; this.addItem = a; this.pay = p;
  }

  // Simulated endpoints (would be mapped to HTTP routes in a web framework)
  public Map<String,Object> postCreate() {
    var out = create.handle();
    return Map.of("orderId", out.orderId().toString());
  }

  public Map<String,Object> postAddItem(String orderId, String sku, int qty, String price) {
    var out = addItem.handle(new AddItemToOrder.Input(UUID.fromString(orderId), sku, qty, price));
    return Map.of("orderId", out.orderId().toString(), "total", out.newTotal());
  }

  public Map<String,Object> postPay(String orderId, String paymentToken) {
    var out = pay.handle(new PayOrder.Input(UUID.fromString(orderId), paymentToken));
    return Map.of("orderId", out.orderId().toString(), "status", out.status(), "authId", out.authId(), "total", out.total());
  }
}
```

### 5) Bootstrap (wiring / composition root)

```java
// bootstrap/App.java
package bootstrap;
import adapters.inbound.OrderController;
import adapters.outbound.FakePaymentGateway;
import adapters.outbound.InMemoryOrderRepository;
import app.usecase.*;

public class App {
  public static void main(String[] args) {
    // Outbound adapters
    var repo = new InMemoryOrderRepository();
    var payments = new FakePaymentGateway();

    // Application services (use cases)
    var create = new CreateOrder(repo);
    var addItem = new AddItemToOrder(repo);
    var pay = new PayOrder(repo, payments);

    // Inbound adapter
    var controller = new OrderController(create, addItem, pay);

    // Simulate requests
    var created = controller.postCreate();
    var id = (String) created.get("orderId");
    System.out.println("Create -> " + created);

    System.out.println("Add 1 -> " + controller.postAddItem(id, "SKU-1", 2, "19.90"));
    System.out.println("Add 2 -> " + controller.postAddItem(id, "SKU-2", 1, "49.00"));
    System.out.println("Pay   -> " + controller.postPay(id, "tok_visa"));
  }
}
```

**What this demonstrates**

-   **Ports owned by the core** (`OrderRepository`, `PaymentGateway`).
    
-   **Adapters** implement ports (outbound) or call use cases (inbound).
    
-   No framework types in the **domain/app** code—only DTOs and primitives.
    
-   Easy to unit-test use cases with **in-memory fakes**.
    

---

## Known Uses

-   **Domain-centric microservices** where tech choices evolve (JPA → JDBC, REST → gRPC) without touching core.
    
-   **Android/iOS + Web** sharing the same use cases with different UI adapters.
    
-   **Legacy strangler** migrations: wrap old systems in outbound adapters while moving business logic inward.
    
-   **Payment/checkout** systems needing PSP swaps with zero impact on domain code.
    

## Related Patterns

-   **Clean Architecture / Onion Architecture** — concentric layers with inward dependencies.
    
-   **CQRS** — can live inside the application layer for read/write separation.
    
-   **Adapter / Facade** — at the edges to isolate protocols and APIs.
    
-   **Dependency Inversion Principle (DIP)** — foundational principle.
    
-   **Microkernel** — stable core with plug-in adapters.
    

---

## Implementation Tips

-   Keep **ports technology-agnostic** (no JPA annotations or HTTP types).
    
-   Place **mapping** (DTO ↔ entity) in adapters or dedicated mappers.
    
-   Manage **transactions** at adapter boundaries (e.g., Spring `@Transactional` around use case calls).
    
-   Write **unit tests** for use cases with fake repositories/gateways; write **contract tests** for adapters.
    
-   Document ports as **contracts**; use ArchUnit to prevent adapters leaking inward.
    
-   Add **observability** (logging/tracing) in adapters; keep the core silent about infrastructure.
    
-   Organize **packages by feature** (`order`, `catalog`) to keep cohesive modules.

