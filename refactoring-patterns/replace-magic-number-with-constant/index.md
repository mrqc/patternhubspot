# Replace Magic Number with Constant — Refactoring Pattern

## Pattern Name and Classification

**Name:** Replace Magic Number with Constant  
**Classification:** Refactoring Pattern (Readability & Maintainability / Expressive Naming)

## Intent

Replace unexplained numeric literals (e.g., `0.07`, `-1`, `86400`) with **named constants** (or stronger domain types) to make intent explicit, centralize change, and prevent defects.

## Also Known As

-   Replace Literal with Named Constant
    
-   Explain Numeric Literal
    
-   Symbolic Constant
    

## Motivation (Forces)

-   **Readability:** `price * 1.07` vs. `price * (1 + SALES_TAX_RATE)`—the latter explains *why*.
    
-   **Single source of truth:** Changing a rate/threshold in one place, not hunting literals across the codebase.
    
-   **Avoid “coincidental equality”:** Two identical numbers might represent different concepts.
    
-   **Type safety & units:** Seconds vs. milliseconds, percentages vs. multipliers—literals invite unit mistakes.
    
-   **Testing & configuration:** Constants can be overridden in tests/config safely, literals can’t.
    

## Applicability

Apply when you see:

-   **Unexplained numeric literals** used directly in logic or conditions.
    
-   Repeated numbers that **encode a rule** (e.g., min password length, retry limit).
    
-   **Sentinel values** like `-1` for “not found” or “unbounded” (consider `Optional`/null or dedicated type first).
    
-   **Unit-sensitive values** (timeouts, sizes) that should be clear (`Duration.ofSeconds(30)` not `30000`).
    

Avoid or postpone when:

-   The number is **self-evident** and localized (e.g., `i = i + 1` in a loop).
    
-   The concept is still **volatile** and unclear—introduce a name once meaning stabilizes.
    
-   You risk **over-constanting** trivial literals, hurting readability.
    

## Structure

```scss
Before:
total = subtotal * 1.07;             // why 1.07?
if (retries > 3) backoff(5000);      // 5000 ms?

After:
total = subtotal * (1 + SALES_TAX_RATE);
if (retries > MAX_RETRIES) backoff(DEFAULT_BACKOFF.toMillis());
```

## Participants

-   **Named Constant:** `static final` field or enum constant giving semantic meaning and a single definition.
    
-   **Domain Types (optional):** `Duration`, `BigDecimal`, `DataSize`, `Money` that encode unit/scale.
    
-   **Call Sites:** Replace raw literals with the named constant or type.
    

## Collaboration

-   Constants live close to their **domain owner** (class/module) or in a **configuration** component.
    
-   Call sites refer to the constant; tests can **override via DI/config** when appropriate.
    
-   Enums may carry **per-constant parameters** (e.g., regional VAT rates).
    

## Consequences

**Benefits**

-   Self-documenting code; lower cognitive load.
    
-   Centralized change point; less risk of inconsistent updates.
    
-   Fewer unit mistakes (ms vs. s); easier testing.
    

**Liabilities / Trade-offs**

-   Too many constants can clutter namespaces.
    
-   Premature constants for trivial numbers reduce readability.
    
-   Misplaced constants (global “Constants.java”) can create **god modules**; prefer proximity to usage.
    

## Implementation

1.  **Identify Magic Numbers**
    
    -   Search for numeric literals in business logic and conditionals; classify by meaning.
        
2.  **Name the Concept**
    
    -   Choose a **domain name** (e.g., `MAX_RETRIES`, `SALES_TAX_RATE`, `FREE_SHIPPING_THRESHOLD`).
        
3.  **Choose Representation**
    
    -   `static final` for compile-time constants; `Duration`/`BigDecimal`/`DataSize` for units; or **config** for environment-specific values.
        
4.  **Introduce Constant Near Owner**
    
    -   Put it in the class that enforces the rule; avoid catch-all “Constants” dumping ground.
        
5.  **Replace Usages**
    
    -   Update all call sites; ensure no unrelated literals get replaced by accident.
        
6.  **Consider Tests & Config**
    
    -   If the value varies by environment, surface it via configuration/constructor parameters; default constant remains.
        
7.  **Remove Dead Duplication**
    
    -   Delete duplicated literals; keep one authoritative definition.
        

---

## Sample Code (Java)

### 1) Basic replacement: tax rate, retries, and timeouts

**Before**

```java
public class CheckoutService {

  public BigDecimal total(BigDecimal subtotal) {
    return subtotal.multiply(new BigDecimal("1.07")); // 7% tax?
  }

  public void callWithRetry(Runnable op) {
    int attempts = 0;
    while (attempts <= 3) { // why 3?
      try { op.run(); return; }
      catch (Exception e) {
        attempts++;
        try { Thread.sleep(5000); } catch (InterruptedException ignored) {} // ms or s?
      }
    }
    throw new IllegalStateException("failed");
  }
}
```

**After**

```java
public class CheckoutService {

  // Domain-expressive names
  private static final BigDecimal SALES_TAX_RATE = new BigDecimal("0.07");
  private static final int MAX_RETRIES = 3;
  private static final java.time.Duration DEFAULT_BACKOFF = java.time.Duration.ofSeconds(5);

  public BigDecimal total(BigDecimal subtotal) {
    return subtotal.multiply(BigDecimal.ONE.add(SALES_TAX_RATE));
  }

  public void callWithRetry(Runnable op) {
    int attempts = 0;
    while (attempts <= MAX_RETRIES) {
      try { op.run(); return; }
      catch (Exception e) {
        attempts++;
        try { Thread.sleep(DEFAULT_BACKOFF.toMillis()); } catch (InterruptedException ignored) {}
      }
    }
    throw new IllegalStateException("failed");
  }
}
```

### 2) Units & domain types prevent mistakes

**Before**

```java
public class SessionConfig {
  public long ttl = 86400; // seconds? ms? days?
}
```

**After**

```java
public class SessionConfig {
  public static final java.time.Duration DEFAULT_TTL = java.time.Duration.ofDays(1);
}
```

### 3) Sentinel values: replace with constants or better types

**Before**

```java
int findIndex(String s, String[] arr) {
  for (int i = 0; i < arr.length; i++) if (arr[i].equals(s)) return i;
  return -1; // sentinel "not found"
}
```

**After (constant)**

```java
private static final int NOT_FOUND = -1;
int findIndex(String s, String[] arr) {
  for (int i = 0; i < arr.length; i++) if (arr[i].equals(s)) return i;
  return NOT_FOUND;
}
```

**Better (Optional)**

```java
OptionalInt findIndex(String s, String[] arr) {
  for (int i = 0; i < arr.length; i++) if (arr[i].equals(s)) return OptionalInt.of(i);
  return OptionalInt.empty();
}
```

### 4) Regionalized constants via enum (per-constant parameters)

```java
public enum VatRegion {
  AT(new BigDecimal("0.20")),
  DE(new BigDecimal("0.19")),
  CH(new BigDecimal("0.077"));

  public final BigDecimal rate;
  VatRegion(BigDecimal rate) { this.rate = rate; }
}

public class VatCalculator {
  public BigDecimal addVat(BigDecimal net, VatRegion region) {
    return net.multiply(BigDecimal.ONE.add(region.rate));
  }
}
```

### 5) Configuration-backed constants (overridable)

```java
public class PricingConfig {
  private final BigDecimal loyaltyDiscount; // injected

  public static final BigDecimal DEFAULT_LOYALTY_DISCOUNT = new BigDecimal("0.05");

  public PricingConfig(BigDecimal loyaltyDiscount) {
    this.loyaltyDiscount = loyaltyDiscount != null ? loyaltyDiscount : DEFAULT_LOYALTY_DISCOUNT;
  }

  public BigDecimal loyaltyDiscount() { return loyaltyDiscount; }
}
```

---

## Known Uses

-   Replacing `60 * 60 * 24` with `Duration.ofDays(1)` in schedulers and caches.
    
-   Thresholds and limits (e.g., `MAX_UPLOAD_MB`, `PASSWORD_MIN_LENGTH`, `MAX_RETRIES`) across services.
    
-   Monetary rules (VAT, rounding scale) expressed as `BigDecimal` constants in a **Money/Tax** module.
    
-   Bit masks and protocol constants centralized in protocol classes/enums.
    
-   UI layout metrics (spacing, animation durations) in style/theme constants.
    

## Related Patterns

-   **Introduce Parameter Object:** When many related constants travel together per call.
    
-   **Encapsulate Field / Value Object:** Replace primitive constants with rich types (`Money`, `DateRange`).
    
-   **Replace Conditional with Polymorphism:** When constants drive switches; move behavior into variants.
    
-   **Extract Class:** If constants and related behavior suggest a new cohesive module.
    
-   **Replace Type Code with Class/Enum:** When a numeric code represents a category or state.
    
-   **Rename Variable / Self-Documenting Code:** Complements this by naming non-constant locals clearly.
    

**Guideline:** Replace literals that **communicate policy or units**. Keep local arithmetic literals (e.g., `+ 1`, loop increments) inline unless they hide domain meaning.

