# Entity (Domain-Driven Design)

## Pattern Name and Classification

**Name:** Entity  
**Classification:** DDD tactical building block (domain layer)

---

## Intent

Represent a **domain object defined by its identity** and **continuous lifecycle**—not merely by the values of its attributes. An Entity’s identity is stable across time and state changes, enabling mutation while preserving conceptual sameness.

---

## Also Known As

-   Reference Object
    
-   Identity Object
    

---

## Motivation (Forces)

-   Many domain concepts persist **over time** while their attributes change (Customer changes address, Order changes status).
    
-   We need a **stable identity** to track the same conceptual thing across transactions, processes, and integrations.
    
-   Without explicit identity, mutable objects become indistinguishable from copies or replacements; auditability suffers.
    
-   Persistence frameworks, caches, and distributed systems require **identity semantics** for deduplication, joins, and reconciliation.
    

Tensions:

-   **Identity choice** (natural key vs surrogate UUID)
    
-   **Equality semantics** (by identity vs by business key)
    
-   **Mutability control** (expose behavior, not setters)
    
-   **Concurrency** (optimistic/pessimistic locking, versioning)
    
-   **Aggregate boundaries** (root entity vs inner entities)
    

---

## Applicability

Use Entities when a concept:

-   Must be **uniquely tracked** across transactions and time.
    
-   Has **business rules** that evolve its state (lifecycle).
    
-   Appears in **relationships** where identity matters (references, ownership).
    
-   Needs **auditing** and long-term traceability.
    

Prefer Value Objects when:

-   The object is defined solely by its **values** and is **immutable** (e.g., Money, Address).
    
-   Identity is irrelevant and replacement-by-value is acceptable.
    

---

## Structure

-   **Entity (with identity):** Mutable domain object with a unique identifier.
    
-   **Identity Type (Value Object):** Strongly typed ID (e.g., `CustomerId`).
    
-   **Value Objects:** Attributes with no identity.
    
-   **Aggregate Root (optional role):** A special Entity that enforces invariants and owns other Entities/Value Objects.
    
-   **Repository (per Aggregate Root):** Access to Entities by identity.
    
-   **Version (optional):** Concurrency token for optimistic locking.
    

---

## Participants

-   **Entity:** Holds identity and behavior; encapsulates invariants local to itself.
    
-   **Identity Value Object:** Encapsulates the identifier semantics.
    
-   **Value Objects:** Used by the Entity to model attributes.
    
-   **Aggregate Root:** Coordinates changes and enforces consistency boundaries.
    
-   **Repository:** Retrieves/persists Entities by identity.
    

---

## Collaboration

1.  Application service loads an **Aggregate Root** from a **Repository** using identity.
    
2.  The root **invokes behavior** on itself or its child Entities to enforce invariants.
    
3.  State changes happen; the same identity persists.
    
4.  The unit of work persists changes, using the identity for merges and the **version** for concurrency checks.
    
5.  References between Aggregates use **identities**, not direct object links (in distributed systems).
    

---

## Consequences

**Benefits**

-   Stable identity enables **mutation with continuity**.
    
-   Clear semantics for **equality** and **object references**.
    
-   Works naturally with **persistence, caching, messaging, and integration**.
    
-   Enables **auditing** and lifecycle tracking.
    

**Liabilities**

-   Designing identity and equality incorrectly causes **subtle bugs** (e.g., transient IDs, mutable keys).
    
-   Overusing Entities where Value Objects suffice increases **complexity** and **coupling**.
    
-   Concurrency control adds **versioning/locking** overhead.
    
-   Entities can **bloat** if they absorb unrelated behavior (violating SRP/aggregate boundaries).
    

---

## Implementation

**Guidelines**

-   **Define identity explicitly** and early. Prefer a **surrogate, immutable ID** (e.g., UUID) generated at creation time. Wrap it in a **typed ID** (`CustomerId`) to avoid primitive obsession.
    
-   **Equality & hashCode by identity only.** Avoid using mutable fields or database-generated IDs that are unset in memory (JPA pitfalls).
    
-   **Encapsulate state changes** behind intention-revealing methods. Avoid public setters; enforce invariants inside the entity.
    
-   **Minimize bidirectional associations;** reference other aggregates by ID to prevent large object graphs.
    
-   **Use Value Objects** for attributes to keep Entities lean and expressive.
    
-   **Concurrency:** add a `version` for optimistic locking.
    
-   **Aggregate discipline:** Only the **Aggregate Root** is loaded and saved by repositories; inner Entities are managed through the root.
    

**Identity choices**

-   **Surrogate UUID (recommended):** stable, globally unique, independent of data shape.
    
-   **Natural key:** only when truly immutable and business-mandated (e.g., ISO codes).
    
-   **Database auto IDs:** acceptable, but generate a provisional ID at construction to keep equality stable in memory, or delay equals/hashCode until persisted.
    

**Persistence notes (JPA/Hibernate)**

-   Prefer `@Id` with assigned UUID (string/byte).
    
-   Implement `equals/hashCode` based on ID and ensure ID is non-null from construction.
    
-   Use `@Version` for optimistic locking.
    
-   Keep mapping concerns out of domain logic if using **clean architecture** (map via separate persistence model or annotations if pragmatic).
    

---

## Sample Code (Java)

### Identity and Value Objects

```java
// Strongly typed ID for safety in APIs, logs, and equality
public record CustomerId(String value) {
    public CustomerId {
        if (value == null || value.isBlank()) throw new IllegalArgumentException("id required");
    }
    public static CustomerId newId() { return new CustomerId(java.util.UUID.randomUUID().toString()); }
}

// Value Object example
public record Email(String value) {
    public Email {
        if (value == null || !value.matches("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$"))
            throw new IllegalArgumentException("invalid email");
    }
}
```

### Entity (Aggregate Root) with Behavior and Versioning

```java
import java.time.Instant;
import java.util.Objects;

public class Customer {
    private final CustomerId id;      // immutable identity
    private String fullName;          // mutable attributes behind behavior
    private Email email;
    private boolean active;
    private long version;             // optimistic locking token (if using JPA: @Version)

    private Instant createdAt;
    private Instant updatedAt;

    // Factory method to enforce invariants at creation
    public static Customer register(String fullName, Email email) {
        var c = new Customer(CustomerId.newId(), fullName, email, true);
        c.createdAt = Instant.now();
        c.updatedAt = c.createdAt;
        return c;
    }

    // Reconstitution constructor (from persistence)
    public Customer(CustomerId id, String fullName, Email email, boolean active) {
        if (id == null) throw new IllegalArgumentException("id required");
        setName(fullName);
        setEmail(email);
        this.id = id;
        this.active = active;
    }

    // Intention-revealing behavior
    public void changeEmail(Email newEmail) {
        ensureActive();
        setEmail(newEmail);
        touch();
    }

    public void renameTo(String newFullName) {
        ensureActive();
        setName(newFullName);
        touch();
    }

    public void deactivate() {
        this.active = false;
        touch();
    }

    private void ensureActive() {
        if (!active) throw new IllegalStateException("customer inactive");
    }

    private void setEmail(Email email) {
        if (email == null) throw new IllegalArgumentException("email required");
        this.email = email;
    }

    private void setName(String name) {
        if (name == null || name.isBlank()) throw new IllegalArgumentException("name required");
        this.fullName = name.trim();
    }

    private void touch() { this.updatedAt = Instant.now(); }

    // Identity-based equality
    @Override public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof Customer other)) return false;
        return id.equals(other.id);
    }
    @Override public int hashCode() { return Objects.hash(id); }

    // Getters expose state in a controlled way (no public setters)
    public CustomerId id() { return id; }
    public String fullName() { return fullName; }
    public Email email() { return email; }
    public boolean isActive() { return active; }
    public long version() { return version; } // if using JPA, annotate with @Version
    public Instant createdAt() { return createdAt; }
    public Instant updatedAt() { return updatedAt; }
}
```

### Repository (Domain-Facing)

```java
import java.util.Optional;

public interface CustomerRepository {
    Optional<Customer> findById(CustomerId id);
    void save(Customer customer);   // unit of work manages flush/commit
    boolean existsByEmail(Email email);
}
```

### Application Service Using the Entity

```java
public class CustomerApplicationService {
    private final CustomerRepository customers;

    public CustomerApplicationService(CustomerRepository customers) {
        this.customers = customers;
    }

    // @Transactional in your framework
    public CustomerId registerCustomer(String fullName, String email) {
        var candidateEmail = new Email(email);
        if (customers.existsByEmail(candidateEmail))
            throw new IllegalStateException("email already in use");

        var customer = Customer.register(fullName, candidateEmail);
        customers.save(customer);
        return customer.id();
    }

    public void changeCustomerEmail(CustomerId id, String newEmail) {
        var customer = customers.findById(id).orElseThrow();
        customer.changeEmail(new Email(newEmail));
        customers.save(customer);
    }
}
```

### (Optional) JPA Mapping Hints

If you map directly with JPA (pragmatic approach), maintain identity and equality discipline:

```java
import jakarta.persistence.*;

@Entity
@Table(name = "customer")
public class CustomerEntity {
    @Id
    private String id; // UUID from domain CustomerId
    private String fullName;
    private String email;
    private boolean active;

    @Version
    private long version;

    // timestamps, etc.
    // convert between domain Customer and persistence CustomerEntity in a mapper
}
```

> Tip: Keep **domain model free of JPA** if you follow clean architecture; use mappers. If you opt for annotations in the domain for pragmatism, still **generate ID at construction** and keep `equals/hashCode` strictly by ID.

---

## Known Uses

-   **Orders/Customers/Invoices** in commerce platforms
    
-   **Accounts/Contracts/Policies** in finance/insurance
    
-   **Shipments/Warehouses** in logistics
    
-   **Users/Projects/Issues** in project management systems
    

---

## Related Patterns

-   **Value Object:** Use for immutable attributes; compose inside Entities.
    
-   **Aggregate / Aggregate Root:** Cluster Entities/Value Objects under a root to enforce invariants.
    
-   **Repository:** Access Entities by identity; one per Aggregate Root.
    
-   **Factory:** Encapsulate complex creation logic and ID assignment.
    
-   **Domain Event:** Emit facts from Entities when significant state changes occur.
    
-   **Domain Service:** For cross-entity/domain operations with no natural home.
