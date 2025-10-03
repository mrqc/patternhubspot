# Inline Method — Refactoring Pattern

## Pattern Name and Classification

**Name:** Inline Method  
**Classification:** Refactoring Pattern (Simplification / Remove Needless Indirection)

## Intent

Remove unnecessary abstraction by **replacing a method call with the method’s body**, simplifying control flow when the method **doesn’t add meaningful intent, abstraction, or reuse**.

## Also Known As

-   Inline Function / Inline Routine
    
-   Collapse Indirection
    
-   Undo Extract Method (when over-extracted)
    

## Motivation (Forces)

-   **Over-abstraction:** A tiny method just delegates without adding a domain name, validation, or reuse.
    
-   **Indirection tax:** Reading code requires extra jumps; stack traces and debugging are noisier.
    
-   **Performance hot paths:** Virtual dispatch or call overhead on extremely hot micro-paths (rare, but possible).
    
-   **Refactoring churn:** After earlier refactorings (Extract Method/Class), some helpers become trivial.
    

## Applicability

Apply when:

-   A method **only forwards** to another method or returns a simple expression.
    
-   The method **no longer reveals intent** better than the inlined code.
    
-   The method is **used in one/few places** and carries no API commitment.
    
-   Inlining **reduces cognitive load** (fewer hops to understand logic).
    

Avoid when:

-   The method **expresses intention** better than raw code (good name hides incidental complexity).
    
-   The method has **cross-cutting concerns** (validation, logging, caching, invariants).
    
-   It’s part of a **public API** where stability or polymorphism matters.
    
-   Tests rely on its **seam** (e.g., spy/mock points); consider keeping it or replacing with a different seam.
    

## Structure

```javascript
Before:
caller() {
  result = helper(x, y);      // tiny wrapper adds no value
}

helper(a, b) { return a + b; }

After:
caller() {
  result = x + y;              // direct logic; fewer hops
}
```

## Participants

-   **Caller:** Site(s) invoking the trivial method.
    
-   **Inlined Method:** Target method whose body will replace the call site.
    
-   **Collaborators:** Any dependencies referenced inside the method body.
    

## Collaboration

-   The **caller** absorbs the method’s logic, possibly introducing local variables for clarity.
    
-   If the inlined method called **another** method, consider inlining that as well (collapse delegation chain) or stop if intent would degrade.
    

## Consequences

**Benefits**

-   Simpler call graphs and **more readable** local logic.
    
-   Fewer files/methods to navigate; clearer stack traces.
    
-   Removes accidental abstraction and unlocks further refactorings (e.g., Decompose Conditional directly in the caller).
    

**Liabilities / Trade-offs**

-   **Duplication risk** if the method had multiple call sites—inline everywhere or keep a single source of truth.
    
-   May reduce **test seams**; tests might need to shift to higher-level behavior.
    
-   If overused, can **bloat** callers and hurt readability.
    

## Implementation

1.  **Preconditions & Safety**
    
    -   Ensure method is **simple**, has no significant side effects beyond what the caller already expects, and is not part of a **stable public API** (or version it).
        
    -   Run tests to capture current behavior.
        
2.  **Replace Calls with Body**
    
    -   For each call site, paste the body, **rename locals** to avoid clashes, and substitute parameters with arguments.
        
3.  **Handle Returns & Control Flow**
    
    -   If the method returns a value, assign directly or integrate expression.
        
    -   For void methods, inline statements preserving order and exceptions.
        
4.  **Remove the Original Method**
    
    -   Once all usages are replaced, delete the method.
        
    -   If some usages remain and you want one source, **stop**—don’t partially inline.
        
5.  **Clean Up**
    
    -   Simplify expressions, **introduce local variables** where naming helps.
        
    -   Re-run tests and static analysis.
        
6.  **Follow-ups**
    
    -   With indirection gone, consider **Extract Method** for genuinely cohesive substeps or **Decompose Conditional** on the now-local logic.
        

---

## Sample Code (Java)

### 1) Trivial Wrapper (best candidate)

**Before**

```java
public class PriceService {

  public BigDecimal totalWithVat(BigDecimal net) {
    return addVat(net); // needless hop
  }

  private BigDecimal addVat(BigDecimal net) {
    return net.multiply(new BigDecimal("1.20")).setScale(2, RoundingMode.HALF_EVEN);
  }
}
```

**After**

```java
public class PriceService {

  public BigDecimal totalWithVat(BigDecimal net) {
    return net.multiply(new BigDecimal("1.20")).setScale(2, RoundingMode.HALF_EVEN);
  }
  // addVat removed
}
```

### 2) Collapse Delegation Chain

**Before**

```java
class CustomerService {
  public boolean isVip(Customer c) { return hasVipStatus(c); }
  private boolean hasVipStatus(Customer c) { return "VIP".equalsIgnoreCase(c.tier()); }
}
```

**After**

```java
class CustomerService {
  public boolean isVip(Customer c) { return "VIP".equalsIgnoreCase(c.tier()); }
}
```

### 3) Hot Path Micro-Optimization (only if measured)

**Before**

```java
final class Vector2 {
  private final float x, y;
  public float dot(Vector2 other) { return dot(this.x, this.y, other.x, other.y); }
  private static float dot(float ax, float ay, float bx, float by) { return ax * bx + ay * by; }
}
```

**After**

```java
final class Vector2 {
  private final float x, y;
  public float dot(Vector2 other) { return this.x * other.x + this.y * other.y; }
}
```

*Note:* Only justify this when profiling shows call overhead matters.

### 4) Inline to Enable Further Refactoring

**Before**

```java
class DiscountService {
  public BigDecimal apply(Customer c, BigDecimal total) {
    return discounted(total, c.tier());
  }
  private BigDecimal discounted(BigDecimal amount, String tier) {
    return switch (tier) {
      case "GOLD" -> amount.multiply(new BigDecimal("0.85"));
      case "SILVER" -> amount.multiply(new BigDecimal("0.90"));
      default -> amount;
    };
  }
}
```

**After (then Decompose Conditional possible)**

```java
class DiscountService {
  public BigDecimal apply(Customer c, BigDecimal total) {
    return switch (c.tier()) {
      case "GOLD" -> total.multiply(new BigDecimal("0.85"));
      case "SILVER" -> total.multiply(new BigDecimal("0.90"));
      default -> total;
    };
  }
}
```

### 5) Guard Against Lost Invariants (don’t inline this)

**Before**

```java
class Account {
  private BigDecimal balance = BigDecimal.ZERO;
  public void deposit(BigDecimal amt) { applyDeposit(amt); }
  private void applyDeposit(BigDecimal amt) {
    if (amt == null || amt.signum() <= 0) throw new IllegalArgumentException();
    balance = balance.add(amt);
    audit("deposit", amt); // cross-cutting concern
  }
}
```

*This method carries validation + auditing; **do not** inline unless you keep those invariants at every call site or move them elsewhere first.*

---

## Known Uses

-   Cleaning up **over-extracted helpers** created during earlier refactorings.
    
-   Simplifying code in **builders**/**fluent APIs** where pass-through methods accumulated.
    
-   Reducing indirection in **delegation-heavy layers** after adopting a clearer architecture.
    
-   Tightening **private APIs** before publishing modules.
    

## Related Patterns

-   **Extract Method:** The inverse; use Inline when extraction no longer pays for itself.
    
-   **Inline Temp / Inline Variable:** Similar simplification for variables.
    
-   **Replace Temp with Query:** Sometimes inlining reveals an expression that should become a query.
    
-   **Inline Class / Collapse Hierarchy:** Higher-level analogs when entire types are redundant.
    
-   **Decompose Conditional:** Often becomes easier once logic is local.
    
-   **Encapsulate Field / Extract Class:** Keep invariants centralized before inlining methods that enforce them.

