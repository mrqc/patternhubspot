# Replace Temp with Query — Refactoring Pattern

## Pattern Name and Classification

**Name:** Replace Temp with Query  
**Classification:** Refactoring Pattern (Expression Simplification / Enable Further Decomposition)

## Intent

Eliminate **temporary variables that store the result of an expression** by replacing them with **query methods** (small, side-effect-free methods). This clarifies intent, reduces local state, and unlocks further refactorings (e.g., *Extract Method*, *Introduce Parameter Object*).

## Also Known As

-   Replace Temporary Variable with Query
    
-   Turn Temp into Getter
    
-   Compute on Demand
    

## Motivation (Forces)

-   **Local state noise:** Temps increase cognitive load and hinder extraction of surrounding code.
    
-   **Duplication:** The same expression is computed and stored in different temps across methods.
    
-   **Encapsulation:** Placing the computation behind a named query communicates **what** over **how**.
    
-   **Testability:** A query is unit-testable; a temp is not directly addressable.
    
-   **Further refactorings:** Fewer temps make it easier to *Decompose Conditional* or move behavior to the right class.
    

Counter-forces:

-   **Performance fears:** Recomputing an expensive expression repeatedly. (Mitigate with caching/memoization if truly needed and measured.)
    
-   **Side effects:** Don’t extract into a query if the original expression has side effects—make it pure first.
    

## Applicability

Apply when:

-   A temp stores a **pure, derivable** value used multiple times in a method.
    
-   A temp blocks *Extract Method* because it ties many statements together.
    
-   The computation belongs conceptually to the **class** (or a collaborator) rather than the method.
    

Avoid when:

-   The expression is **impure** (has side effects) — refactor to purity first.
    
-   The value is **expensive** and used many times in tight loops (measure; then cache).
    
-   The temp is a **loop index** or trivial, hyper-local calculation that improves clarity in place.
    

## Structure

```typescript
Before:
method() {
  var basePrice = quantity * itemPrice;
  if (basePrice > 1000) applyDiscount();
  return basePrice + shipping(basePrice);
}

After:
method() {
  if (basePrice() > 1000) applyDiscount();
  return basePrice() + shipping(basePrice());
}

private int basePrice() { return quantity * itemPrice; }
```

## Participants

-   **Caller Method:** The original method holding temporary variables.
    
-   **Query Method(s):** Side-effect-free methods that compute derived values on demand.
    
-   **Owning Class or Collaborator:** Where the query naturally belongs (domain owner of the data).
    

## Collaboration

-   The caller **invokes queries** instead of reading temps.
    
-   Multiple methods can **reuse** the same query.
    
-   If queries rely on collaborators (e.g., repository, policy), pass those in or move the query to the collaborator (*Move Method*).
    

## Consequences

**Benefits**

-   Clearer intent and simpler methods; fewer locals.
    
-   Reuse across the class; one place to change the computation.
    
-   Enables further refactorings (extract/inline/move).
    
-   Improves testability via focused unit tests.
    

**Liabilities / Trade-offs**

-   Potential recomputation overhead (rarely significant; cache if needed).
    
-   Too many tiny queries can fragment code—favor meaningful names and cohesion.
    
-   If the query reaches across boundaries, you may increase coupling (consider *Move Method*).
    

## Implementation

1.  **Verify Purity**
    
    -   Ensure the temp’s expression is side-effect-free and deterministic for the method’s scope.
        
2.  **Create a Query**
    
    -   Extract a private method with an intention-revealing name; pass required inputs or use fields.
        
3.  **Replace Temp Uses**
    
    -   Substitute all references to the temp with the query call.
        
4.  **Remove the Temp**
    
    -   Delete the temporary variable. Compile and run tests.
        
5.  **Consider Placement**
    
    -   If the query conceptually belongs elsewhere, *Move Method* to that class.
        
6.  **Optimize When Proven**
    
    -   If profiling shows cost, add memoization (lazy field) or compute once and pass down explicitly.
        

---

## Sample Code (Java)

### 1) Basic replacement to clarify intent

**Before**

```java
public class Order {
  private final int quantity;
  private final BigDecimal itemPrice;

  public Order(int quantity, BigDecimal itemPrice) {
    this.quantity = quantity;
    this.itemPrice = itemPrice;
  }

  public BigDecimal total() {
    BigDecimal basePrice = itemPrice.multiply(BigDecimal.valueOf(quantity));
    BigDecimal discount = basePrice.compareTo(new BigDecimal("1000")) > 0
        ? basePrice.multiply(new BigDecimal("0.05"))
        : BigDecimal.ZERO;
    BigDecimal shipping = basePrice.compareTo(new BigDecimal("500")) > 0
        ? new BigDecimal("0")
        : new BigDecimal("20");
    return basePrice.subtract(discount).add(shipping);
  }
}
```

**After (Replace Temp with Query)**

```java
public class Order {
  private final int quantity;
  private final BigDecimal itemPrice;

  public Order(int quantity, BigDecimal itemPrice) {
    this.quantity = quantity;
    this.itemPrice = itemPrice;
  }

  public BigDecimal total() {
    return basePrice()
        .subtract(discount())
        .add(shipping());
  }

  /** Pure queries (no side effects) */
  private BigDecimal basePrice() {
    return itemPrice.multiply(BigDecimal.valueOf(quantity));
  }

  private BigDecimal discount() {
    return basePrice().compareTo(new BigDecimal("1000")) > 0
        ? basePrice().multiply(new BigDecimal("0.05"))
        : BigDecimal.ZERO;
  }

  private BigDecimal shipping() {
    return basePrice().compareTo(new BigDecimal("500")) > 0
        ? BigDecimal.ZERO
        : new BigDecimal("20");
  }
}
```

### 2) Avoid recomputation via a memoized query (only if measured)

```java
public class Order {
  private final int quantity;
  private final BigDecimal itemPrice;
  private BigDecimal cachedBasePrice; // lazily computed

  private BigDecimal basePrice() {
    if (cachedBasePrice == null) {
      cachedBasePrice = itemPrice.multiply(BigDecimal.valueOf(quantity));
    }
    return cachedBasePrice;
  }
}
```

### 3) Moving the query to the natural owner (*Move Method* synergy)

```java
public class ShoppingCart {
  private final List<CartLine> lines;

  public BigDecimal total() {
    return subtotal().add(tax());
  }

  private BigDecimal subtotal() {
    return lines.stream().map(CartLine::lineTotal).reduce(BigDecimal.ZERO, BigDecimal::add);
  }

  private BigDecimal tax() {
    return subtotal().multiply(new BigDecimal("0.20"));
  }
}

public record CartLine(BigDecimal unitPrice, int qty) {
  // replacing temps in callers with a query on the correct owner
  public BigDecimal lineTotal() { return unitPrice.multiply(BigDecimal.valueOf(qty)); }
}
```

### 4) Enabling further refactoring (Decompose Conditional)

```java
public class FareService {
  public BigDecimal price(Trip t) {
    if (isPeak(t)) return peakPrice(t.distanceKm());
    return offPeakPrice(t.distanceKm());
  }

  private boolean isPeak(Trip t) {
    return peakWindow().contains(t.departure());
  }

  private TimeWindow peakWindow() { /* replaces temps with a clear query */ return TimeWindow.weekdayRushHours(); }
  private BigDecimal peakPrice(int km) { /* ... */ return BigDecimal.TEN; }
  private BigDecimal offPeakPrice(int km) { /* ... */ return BigDecimal.ONE; }
}
```

---

## Known Uses

-   Replacing repeated local temps for **subtotal**, **base price**, **tax**, **discount**, **distance**, or **normalized strings** with named queries.
    
-   Cleaning up controller/service methods so queries live on **domain entities** or **value objects** instead of temporary locals.
    
-   Pre-step for **Replace Conditional with Polymorphism**—queries isolate branch predicates.
    

## Related Patterns

-   **Extract Method:** Often the mechanical step to create the query.
    
-   **Introduce Explaining Variable:** The opposite move when a short-lived, clearly named temp helps readability; choose case-by-case.
    
-   **Move Method:** After extraction, move the query to the class that owns the data.
    
-   **Inline Temp:** When a temp is truly trivial, inline it directly instead of extracting.
    
-   **Replace Method with Method Object:** For very long methods where many temps become fields of a helper object.
    
-   **Encapsulate Field / Value Object:** Strengthen queries by pushing them into richer types (e.g., `Money`, `DateRange`).

