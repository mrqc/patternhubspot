# Move Method — Refactoring Pattern

## Pattern Name and Classification

**Name:** Move Method  
**Classification:** Refactoring Pattern (Behavior Localization / Cohesion & Encapsulation)

## Intent

Relocate a method to the class or module where it **logically belongs and primarily uses data/behavior**, improving cohesion, reducing feature envy, and clarifying ownership and APIs.

## Also Known As

-   Relocate Method
    
-   Move Operation
    
-   Normalize Ownership of Behavior
    

## Motivation (Forces)

-   **Feature envy:** A method heavily uses fields of another class more than its own.
    
-   **Scattered rules:** Domain rules live far from the data they govern, weakening invariants.
    
-   **Change amplification:** Modifying a rule requires edits across multiple classes.
    
-   **Discoverability:** Developers expect to find behavior next to the data it acts upon.
    
-   **Encapsulation & reuse:** The natural owner can enforce validation and expose a tighter API.
    

## Applicability

Apply when:

-   A method reads/writes **more state of another class** than its own.
    
-   The method’s **responsibility aligns** with another type (policy, value object, aggregate).
    
-   You plan to **Extract Class** and clustering behavior in the new class is the next step.
    
-   A service method is anemic and should live with the **rich domain object**.
    

Avoid or postpone when:

-   Moving would break **transaction boundaries** or invariants (e.g., across aggregates) without a plan.
    
-   The method intentionally **coordinates multiple collaborators** (orchestration)—keep it as an application/service method.
    
-   The target class becomes **overloaded** or introduces tight cyclic dependencies.
    

## Structure

```lua
Before:
+------------------+          +----------------------+
| OrderService     |          | Money                |
| - calcTotal(o)   | ----->   | (fields, rules)      |
+------------------+          +----------------------+

After:
+------------------+          +----------------------+
| OrderService     |          | Money                |
| (delegates)      |          | + plus(...)          |
| calcTotal -> o.total()      |                      |
+------------------+          +----------------------+
```

## Participants

-   **Source Class:** Current home of the method (often orchestration or anemic class).
    
-   **Target Class:** Natural owner of data/rules referenced by the method.
    
-   **Clients:** Callers that must be redirected to the new location.
    
-   **Transitional Delegator (optional):** Temporary method kept on source to preserve API while callers migrate.
    

## Collaboration

-   The **target** class implements the moved method and enforces invariants.
    
-   The **source** optionally delegates to the new method during migration.
    
-   Clients progressively switch to calling the target directly or via **intent-revealing** methods on the source.
    

## Consequences

**Benefits**

-   Higher cohesion; rules live with the data they govern.
    
-   Stronger, centralized invariants and fewer leaks.
    
-   Clearer ownership and simpler APIs; improved reuse and testability.
    

**Liabilities / Trade-offs**

-   Short-term churn (call-site changes, imports, visibility adjustments).
    
-   Potential for **chatty interactions** if boundaries are chosen poorly.
    
-   Requires careful handling of **public APIs** and serialization/evolution concerns.
    

## Implementation

1.  **Identify True Ownership**
    
    -   Inspect field usage; if a method touches another class’s state predominantly, that class likely owns the behavior.
        
2.  **Create Method on Target**
    
    -   Move logic; adapt parameters to use target’s own fields where possible. Encode **invariants** here.
        
3.  **Preserve Behavior**
    
    -   Keep a delegating method on the source (temporarily). Add tests if missing.
        
4.  **Migrate Call Sites**
    
    -   Replace calls to the source with calls to the target or with an **intent method** on the source that forwards.
        
5.  **Remove Delegator**
    
    -   After all callers are migrated, delete the old method.
        
6.  **Tighten Boundaries**
    
    -   Reduce visibility and remove now-unused getters/setters. Consider **Move Field** or **Extract Class** follow-ups.
        
7.  **Retest & Review**
    
    -   Run unit and integration tests; watch for cycles and over-exposure.
        

---

## Sample Code (Java)

### 1) Move calculation from service to domain (classic feature envy)

**Before**

```java
public class InvoiceService {
  public BigDecimal computeTotal(Invoice inv) {
    BigDecimal subtotal = inv.getLines().stream()
        .map(li -> li.unitPrice().multiply(BigDecimal.valueOf(li.quantity())))
        .reduce(BigDecimal.ZERO, BigDecimal::add);

    BigDecimal tax = subtotal.multiply(inv.getTaxRate());
    return subtotal.add(tax).setScale(2, RoundingMode.HALF_EVEN);
  }
}

public class Invoice {
  private final List<LineItem> lines;
  private final BigDecimal taxRate;
  // getters...
}
```

**After**

```java
public class Invoice {
  private final List<LineItem> lines;
  private final BigDecimal taxRate;

  /** Behavior moved here; rules live with data */
  public BigDecimal total() {
    BigDecimal subtotal = lines.stream()
        .map(li -> li.unitPrice().multiply(BigDecimal.valueOf(li.quantity())))
        .reduce(BigDecimal.ZERO, BigDecimal::add);
    BigDecimal tax = subtotal.multiply(taxRate);
    return subtotal.add(tax).setScale(2, RoundingMode.HALF_EVEN);
  }
}

public class InvoiceService {
  /** Transitional delegator (can be removed once callers use inv.total()) */
  @Deprecated
  public BigDecimal computeTotal(Invoice inv) {
    return inv.total();
  }
}
```

### 2) Move method into Value Object to enforce invariants

**Before**

```java
public class PriceCalculator {
  public BigDecimal convert(BigDecimal amount, String from, String to, BigDecimal rate) {
    if (from.equals(to)) return amount;
    if (rate == null || rate.signum() <= 0) throw new IllegalArgumentException("rate");
    return amount.multiply(rate).setScale(2, RoundingMode.HALF_UP);
  }
}
```

**After**

```java
public record Money(BigDecimal amount, String currency) {
  public Money {
    Objects.requireNonNull(amount); Objects.requireNonNull(currency);
    if (amount.scale() > 2) amount = amount.setScale(2, RoundingMode.HALF_UP);
  }
  public Money convertTo(String targetCurrency, BigDecimal rate) {
    Objects.requireNonNull(targetCurrency); Objects.requireNonNull(rate);
    if (currency.equals(targetCurrency)) return this;
    if (rate.signum() <= 0) throw new IllegalArgumentException("rate");
    return new Money(amount.multiply(rate).setScale(2, RoundingMode.HALF_UP), targetCurrency);
  }
}
```

### 3) Move method from consumer to provider (reduce data shuttling)

**Before**

```java
public class CartService {
  public boolean qualifiesForFreeShipping(Cart cart, ShippingPolicy policy) {
    return cart.itemsTotal().compareTo(policy.getFreeShippingThreshold()) >= 0
        && !policy.isBlackoutZip(cart.shippingAddress().postalCode());
  }
}
```

**After**

```java
public class ShippingPolicy {
  private final BigDecimal freeShippingThreshold;
  private final Set<String> blackoutPrefixes;

  public boolean qualifies(Cart cart) {
    return cart.itemsTotal().compareTo(freeShippingThreshold) >= 0
        && !isBlackoutZip(cart.shippingAddress().postalCode());
  }

  boolean isBlackoutZip(String postal) {
    return blackoutPrefixes.stream().anyMatch(postal::startsWith);
  }
}

public class CartService {
  public boolean qualifiesForFreeShipping(Cart cart, ShippingPolicy policy) {
    return policy.qualifies(cart); // delegate to owner of rules
  }
}
```

### 4) Move method into Policy/Strategy to enable swappability

**Before**

```java
public class DiscountService {
  public BigDecimal apply(BigDecimal total, Customer c) {
    if (c.isVip()) return total.multiply(new BigDecimal("0.85"));
    if (c.isEmployee()) return total.multiply(new BigDecimal("0.70"));
    return total;
  }
}
```

**After**

```java
public interface DiscountPolicy {
  BigDecimal apply(BigDecimal total, Customer c);
}

public class VipDiscount implements DiscountPolicy {
  public BigDecimal apply(BigDecimal total, Customer c) {
    return c.isVip() ? total.multiply(new BigDecimal("0.85")) : total;
  }
}

public class EmployeeDiscount implements DiscountPolicy {
  public BigDecimal apply(BigDecimal total, Customer c) {
    return c.isEmployee() ? total.multiply(new BigDecimal("0.70")) : total;
  }
}

public class DiscountService {
  private final List<DiscountPolicy> policies;
  public DiscountService(List<DiscountPolicy> policies) { this.policies = policies; }

  public BigDecimal applyAll(BigDecimal total, Customer c) {
    BigDecimal result = total;
    for (DiscountPolicy p : policies) result = p.apply(result, c);
    return result;
  }
}
```

---

## Known Uses

-   Shifting **domain calculations** from services/controllers into aggregates or value objects.
    
-   Moving **validation/normalization** into the owning type (e.g., `Email`, `PostalAddress`, `Money`).
    
-   Extracting **pricing/tax/shipping rules** into policy classes for configurability.
    
-   Relocating **integration glue** into adapters to follow Ports & Adapters/Hexagonal architecture.
    
-   Consolidating **time/date** logic into dedicated types to avoid duplication.
    

## Related Patterns

-   **Move Field:** Often accompanies Move Method so data and behavior co-reside.
    
-   **Extract Class:** Create a new home (policy/value object) before moving multiple methods.
    
-   **Extract Interface:** After moving, publish a narrow contract for swappable implementations.
    
-   **Encapsulate Field / Encapsulate Collection:** Protect state in the target after migration.
    
-   **Inline Method:** If, after moving, an old delegator adds no value, inline/remove it.
    
-   **Strategy / Policy:** Target for methods that vary by rule and need runtime selection.
    
-   **Introduce Parameter Object:** If moved methods still pass long tuples, group them.

