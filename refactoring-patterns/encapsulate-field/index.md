# Encapsulate Field — Refactoring Pattern

## Pattern Name and Classification

**Name:** Encapsulate Field  
**Classification:** Refactoring Pattern (Information Hiding / Data Integrity)

## Intent

Prevent external code from directly reading or writing object state by **hiding fields behind accessors** (getters/setters or specialized methods). This enables validation, invariants, lazy computation, thread safety, notifications, and future evolution without breaking callers.

## Also Known As

-   Hide Field
    
-   Accessor Methods
    
-   Information Hiding (Parnas)
    
-   Data Hiding
    

## Motivation (Forces)

-   **Invariants & validation:** Direct writes can violate constraints (e.g., negative prices, invalid states).
    
-   **Binary compatibility:** Public fields lock ABI; accessors allow evolution (derived values, caching, logging).
    
-   **Thread safety:** Coordinated access (synchronization, atomics) is impossible with public fields.
    
-   **Observability:** Need to trigger side effects (events, dirty flags) when state changes.
    
-   **API clarity:** Distinguish *intention-revealing* operations from raw mutation.
    

## Applicability

Apply when:

-   Classes expose `public` or `package-private` fields used by external code.
    
-   Invariants are implicit or repeatedly checked at call sites.
    
-   You need to add validation, lazy init, caching, or notify observers on change.
    
-   Collections are exposed directly (risk of uncontrolled mutation).
    

Avoid or defer when:

-   You’re in a **data-only DTO boundary** specifically intended for serialization with clear stability guarantees (still prefer records).
    
-   Performance-critical hot paths where accessor overhead matters (rare; consider `final` + records/immutability).
    

## Structure

```csharp
Before:                          After:
+---------------------+          +---------------------+
|  public int age;    |   --->   |  private int age;   |
|                     |          |  public int age(){  |
|                     |          |    return age; }    |
|                     |          |  public void setAge(int v){ 
|                     |          |    require(v>=0);   |
|                     |          |    this.age=v; }    |
+---------------------+          +---------------------+
```

## Participants

-   **Field Owner (Class):** Declares private state and enforces invariants.
    
-   **Accessors / Mutators:** Methods that reveal intent (e.g., `renameTo`, `increaseStockBy`), not just generic setters.
    
-   **Clients:** Use accessors; no direct state manipulation.
    
-   **Observers / Domain Events (optional):** React to state changes.
    

## Collaboration

-   Clients call **queries** (getters) and **commands** (setters/intent methods).
    
-   The class centralizes validation, logging, and notifications.
    
-   If multiple fields change together, provide aggregate operations to preserve invariants.
    

## Consequences

**Benefits**

-   Preserves invariants and integrity; easier debugging and logging.
    
-   Allows internal representation changes without breaking API.
    
-   Enables thread-safety, caching, lazy loading, and events.
    
-   Prevents representation exposure (defensive copies for collections).
    

**Liabilities / Trade-offs**

-   Slight verbosity and indirection.
    
-   Poorly named generic setters can hide domain intent.
    
-   Over-encapsulation can complicate simple data transfer scenarios.
    

## Implementation

1.  **Change Field Visibility** to `private` (or least possible).
    
2.  **Add Accessors**: start with getters; replace writes with set/command methods.
    
3.  **Enforce Invariants** inside mutators (validation, normalization).
    
4.  **Prefer Intent-Revealing Methods** (`renameTo`, `deactivate`, `increaseBy`) over raw `setX`.
    
5.  **Defensive Copies** for mutable aggregates (e.g., `List`, `Date`). Return unmodifiable views.
    
6.  **Thread Safety** if needed (synchronization/atomics).
    
7.  **Deprecate and Migrate**: replace direct field references gradually; keep backward compatibility where required.
    
8.  **Tests**: add unit tests for invariants and side effects.
    

## Sample Code (Java)

### 1) Before → After (simple validation and intent-revealing operations)

```java
// Before
public class Product {
  public String name;
  public BigDecimal price;
}

// After
public class Product {
  private String name;
  private BigDecimal price;

  public Product(String name, BigDecimal price) {
    renameTo(name);
    changePriceTo(price);
  }

  public String name() { return name; }
  public BigDecimal price() { return price; }

  /** Intent-revealing command with validation */
  public void renameTo(String newName) {
    if (newName == null || newName.isBlank()) {
      throw new IllegalArgumentException("name must not be blank");
    }
    this.name = newName.strip();
  }

  /** Centralized invariant enforcement */
  public void changePriceTo(BigDecimal newPrice) {
    if (newPrice == null || newPrice.signum() < 0) {
      throw new IllegalArgumentException("price must be >= 0");
    }
    this.price = newPrice.setScale(2, java.math.RoundingMode.HALF_EVEN);
  }
}
```

### 2) Encapsulate a collection (defensive copies and unmodifiable view)

```java
public class Order {
  private final List<OrderLine> lines = new ArrayList<>();

  /** Query returns an unmodifiable view to avoid representation exposure */
  public List<OrderLine> lines() {
    return java.util.Collections.unmodifiableList(lines);
  }

  /** Intent-revealing command ensures invariants per addition */
  public void addLine(OrderLine line) {
    Objects.requireNonNull(line, "line");
    if (line.quantity() <= 0) throw new IllegalArgumentException("qty > 0");
    this.lines.add(line);
  }

  /** Aggregate update preserves invariants atomically */
  public void replaceLines(List<OrderLine> newLines) {
    Objects.requireNonNull(newLines, "newLines");
    if (newLines.stream().anyMatch(l -> l.quantity() <= 0))
      throw new IllegalArgumentException("all qty > 0");
    this.lines.clear();
    this.lines.addAll(new ArrayList<>(newLines)); // defensive copy
  }
}
```

### 3) Thread-safe field encapsulation with `AtomicReference`

```java
public class FeatureFlag {
  private final java.util.concurrent.atomic.AtomicReference<Boolean> enabled =
      new java.util.concurrent.atomic.AtomicReference<>(false);

  public boolean isEnabled() { return enabled.get(); }

  public void enable()  { enabled.set(true); }
  public void disable() { enabled.set(false); }

  /** CAS style for racing updates */
  public boolean compareAndSet(boolean expect, boolean update) {
    return enabled.compareAndSet(expect, update);
  }
}
```

### 4) Domain events on mutation (observability hook)

```java
public class Account {
  private BigDecimal balance = BigDecimal.ZERO;
  private final List<Consumer<BigDecimal>> listeners = new ArrayList<>();

  public BigDecimal balance() { return balance; }

  public void deposit(BigDecimal amount) {
    requirePositive(amount);
    var old = balance;
    balance = balance.add(amount);
    notifyChanged(old, balance);
  }

  public void withdraw(BigDecimal amount) {
    requirePositive(amount);
    if (balance.compareTo(amount) < 0) throw new IllegalStateException("insufficient funds");
    var old = balance;
    balance = balance.subtract(amount);
    notifyChanged(old, balance);
  }

  public void onBalanceChanged(Consumer<BigDecimal> listener) { listeners.add(listener); }

  private void requirePositive(BigDecimal v) {
    if (v == null || v.signum() <= 0) throw new IllegalArgumentException("amount > 0");
  }

  private void notifyChanged(BigDecimal oldVal, BigDecimal newVal) {
    listeners.forEach(l -> l.accept(newVal));
  }
}
```

### 5) Immutability as a stronger form of encapsulation (Java Record)

```java
public record Money(BigDecimal amount, String currency) {
  public Money {
    Objects.requireNonNull(amount); Objects.requireNonNull(currency);
    if (amount.signum() < 0) throw new IllegalArgumentException("amount >= 0");
  }
  public Money add(Money other) {
    if (!currency.equals(other.currency())) throw new IllegalArgumentException("currency mismatch");
    return new Money(amount.add(other.amount()), currency);
  }
}
```

## Known Uses

-   Replacing `public` fields in legacy POJOs with accessors to add validation and logging.
    
-   Wrapping configuration flags in accessors to support dynamic reload and audit.
    
-   Encapsulating mutable collections in domain models to prevent accidental external mutation.
    
-   Migrating DTOs to **records** or immutable value objects for safer APIs.
    
-   Introducing domain events/observers where changes must be tracked (audit trails).
    

## Related Patterns

-   **Encapsulate Collection:** Specialized variant focusing on aggregates.
    
-   **Introduce Parameter Object / Value Object:** Strengthen invariants and readability.
    
-   **Replace Data Value with Object:** Turn primitive fields into rich types.
    
-   **Immutable Object:** Maximize safety by eliminating setters.
    
-   **Move Method / Move Field:** Align behavior with its true owner.
    
-   **Observer / Domain Event:** React to encapsulated state changes.

