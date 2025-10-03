# Extract Interface — Refactoring Pattern

## Pattern Name and Classification

**Name:** Extract Interface  
**Classification:** Refactoring Pattern (Abstraction & Decoupling / Dependency Inversion)

## Intent

Introduce a **stable, minimal contract** that captures a client’s required behavior from an existing concrete class. Consumers then depend on the interface instead of the concrete type, enabling **substitution, testing with doubles, parallel implementations,** and safer evolution.

## Also Known As

-   Introduce Interface
    
-   Publish Contract
    
-   Dependency Inversion by Interface
    

## Motivation (Forces)

-   **Tight coupling:** Clients depend on a concrete class, making substitution and testing hard.
    
-   **Large surface area:** Consumers only need a subset of methods but are exposed to all of them.
    
-   **Parallel implementations:** Need to support multiple backends (e.g., in-memory, SQL, S3).
    
-   **Testability:** Mocking/stubbing is clumsy without a seam.
    
-   **Evolution:** Concrete class must change but you want to **stabilize a contract** for clients.
    

## Applicability

Apply when:

-   A class is used by many clients and you want to **freeze a minimal contract**.
    
-   You need alternate implementations (e.g., synchronous vs. async, local vs. remote).
    
-   You want to **mock** the dependency in unit tests without heavy frameworks.
    
-   Clients only use a **cohesive subset** of a class’s methods.
    

Avoid or defer when:

-   The class is internal, rarely reused, and unlikely to change.
    
-   You would create an interface with **a single method used once** (YAGNI).
    
-   Behavior is unstable and still being discovered—premature abstraction can ossify mistakes.
    

## Structure

```lua
Before:
+-------------------------+
| ConcreteService         |
| + save() + find() + ...|
+-----------▲-------------+
            |
         Clients (hard-coupled)

After:
+-------------------------+       +------------------------+
|       ServicePort       |<------|       Clients          |
|  (extracted interface)  |       +------------------------+
+-----------▲-------------+
            |
  +---------+---------+
  |                   |
+-----------+   +-------------+
| SqlService |   | InMemService|
+-----------+   +-------------+
```

## Participants

-   **Interface (Port):** The extracted, minimal contract used by clients.
    
-   **Concrete Implementation(s):** One or more classes implementing the interface.
    
-   **Clients:** Depend only on the interface; receive implementation via DI/factory.
    
-   **Composition Root:** Wires concrete implementations to interfaces (app startup, tests).
    

## Collaboration

-   Clients **program to the interface**, not the implementation.
    
-   Implementations can vary (e.g., different storage backends) without changing clients.
    
-   Tests provide **fakes/mocks** implementing the same interface.
    

## Consequences

**Benefits**

-   Reduced coupling; **substitutability** and parallel implementations.
    
-   **Improved testability** (lightweight stubs/mocks).
    
-   Supports clean architecture (ports & adapters), DIP, and SRP.
    
-   Enables incremental migration (keep old impl while introducing a new one).
    

**Liabilities / Trade-offs**

-   More types to maintain; risk of **anemic interfaces** if designed without care.
    
-   An interface that’s too broad becomes sticky and hard to evolve.
    
-   Binary compatibility concerns if you modify published interfaces (use versioning).
    

## Implementation

1.  **Identify the Client Usage Surface**
    
    -   Search references to the concrete class; record the methods actually used.
        
2.  **Define a Minimal Interface**
    
    -   Extract only the **cohesive** operations clients need (ISP). Name it by role, not technology (`CustomerRepository`, not `JdbcCustomerDao`).
        
3.  **Make the Concrete Class Implement It**
    
    -   Add `implements Interface` and ensure signatures match.
        
4.  **Replace Client Types**
    
    -   Change variables/params/fields from concrete type to the new interface.
        
5.  **Introduce Alternate Implementations** (optional)
    
    -   E.g., an in-memory or remote implementation for tests or new backends.
        
6.  **Wire via DI/Factories**
    
    -   Provide the concrete at composition root; avoid service locator antipatterns.
        
7.  **Harden with Tests & Contracts**
    
    -   Add **contract tests** shared by all implementations to guarantee behavioral parity.
        
8.  **Iterate**
    
    -   Split oversized interfaces (ISP), keep the contract stable, version if needed.
        

---

## Sample Code (Java)

### Before — Clients depend on a concrete repository

```java
public class SqlCustomerRepository { // concrete type leaks to clients
  private final DataSource ds;

  public SqlCustomerRepository(DataSource ds) { this.ds = ds; }

  public Optional<Customer> findById(String id) {
    // JDBC code...
    return Optional.empty();
  }

  public Customer save(Customer c) {
    // JDBC insert/update...
    return c;
  }

  public void delete(String id) {
    // JDBC delete...
  }
}

public class LoyaltyService {
  private final SqlCustomerRepository repo; // hard-coupled

  public LoyaltyService(SqlCustomerRepository repo) { this.repo = repo; }

  public int customerPoints(String id) {
    return repo.findById(id).map(Customer::points).orElse(0);
  }
}
```

### After — Extract an interface and program to it

```java
// 1) The extracted interface (minimal contract used by clients)
public interface CustomerRepository {
  Optional<Customer> findById(String id);
  Customer save(Customer c);
  void delete(String id);
}

// 2) Existing implementation now implements the interface
public class SqlCustomerRepository implements CustomerRepository {
  private final DataSource ds;
  public SqlCustomerRepository(DataSource ds) { this.ds = ds; }

  @Override
  public Optional<Customer> findById(String id) { /* JDBC */ return Optional.empty(); }

  @Override
  public Customer save(Customer c) { /* JDBC */ return c; }

  @Override
  public void delete(String id) { /* JDBC */ }
}

// 3) Client depends on interface, not concrete
public class LoyaltyService {
  private final CustomerRepository repo; // decoupled

  public LoyaltyService(CustomerRepository repo) { this.repo = repo; }

  public int customerPoints(String id) {
    return repo.findById(id).map(Customer::points).orElse(0);
  }
}

// 4) Alternate implementation for tests or another backend
public class InMemoryCustomerRepository implements CustomerRepository {
  private final Map<String, Customer> db = new java.util.concurrent.ConcurrentHashMap<>();

  @Override
  public Optional<Customer> findById(String id) { return Optional.ofNullable(db.get(id)); }

  @Override
  public Customer save(Customer c) { db.put(c.id(), c); return c; }

  @Override
  public void delete(String id) { db.remove(id); }
}

// 5) Composition root (example wiring)
public class App {
  public static void main(String[] args) {
    DataSource ds = /* ... */;
    CustomerRepository repo = new SqlCustomerRepository(ds);
    LoyaltyService service = new LoyaltyService(repo);
    // run app...
  }
}

// 6) Contract test to ensure all impls behave the same
abstract class CustomerRepositoryContractTest {

  protected abstract CustomerRepository repo();

  @org.junit.jupiter.api.Test
  void saveAndFindRoundTrip() {
    var input = new Customer("42", "Ada", 120);
    repo().save(input);
    var out = repo().findById("42");
    org.assertj.core.api.Assertions.assertThat(out).contains(input);
  }
}

class InMemoryCustomerRepositoryTest extends CustomerRepositoryContractTest {
  @Override protected CustomerRepository repo() { return new InMemoryCustomerRepository(); }
}

// simple value object for demo
public record Customer(String id, String name, int points) {}
```

**Notes:**

-   The **interface is minimal** and named by domain role (`CustomerRepository`).
    
-   Clients can now receive **Sql**, **InMemory**, or future **Remote** implementations without code changes.
    
-   The **contract test** prevents behavior drift between implementations.
    

## Known Uses

-   Hexagonal / Ports & Adapters: Define domain ports as interfaces; adapters implement them (DB, HTTP, MQ).
    
-   Swapping infrastructure providers (JDBC → JPA → HTTP service) while keeping domain intact.
    
-   Testing with **in-memory** or **fake** implementations to avoid heavy test fixtures.
    
-   Gradual strangler migration: Old and new adapters both implement the same interface during cutover.
    

## Related Patterns

-   **Dependency Inversion Principle (DIP):** Core rationale for extracting interfaces.
    
-   **Interface Segregation Principle (ISP):** Keep interfaces small and role-focused.
    
-   **Extract Class / Extract Module:** Often performed before or after to improve cohesion.
    
-   **Adapter / Bridge:** Provide alternate implementations behind a stable interface.
    
-   **Strategy:** When the interface represents swappable algorithms/policies.
    
-   **Facade:** Present a simplified interface on top of complex subsystems.

