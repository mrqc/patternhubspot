# Consolidate Duplicate Code — Refactoring Pattern

## Pattern Name and Classification

**Name:** Consolidate Duplicate Code  
**Classification:** Refactoring Pattern (Code Smell Remediation / DRY Enforcement)

## Intent

Eliminate copy-pasted or near-duplicate logic by extracting it into a single, well-named abstraction (function, class, module, or template) so behavior lives in exactly one place, reducing defects and maintenance cost.

## Also Known As

-   DRY (Don’t Repeat Yourself)
    
-   Extract Method/Class/Module
    
-   Unify Algorithms / Pull Up Method (OO hierarchies)
    
-   Replace Conditional with Polymorphism (when duplicates come from branching)
    

## Motivation (Forces)

-   **Readability vs. speed:** Copy-paste is fast now but expensive later.
    
-   **Divergence risk:** Bug fixes land in one copy and not the others.
    
-   **Cognitive load:** Multiple places to understand before safely changing behavior.
    
-   **Coupling constraints:** Teams duplicate code to avoid awkward dependencies or poor module boundaries.
    
-   **Performance & correctness:** Inconsistent implementations (e.g., rounding, time zones) subtly diverge.
    

## Applicability

Apply when you find:

-   **Exact duplicates** across modules, services, or layers.
    
-   **Near duplicates** with minor parameter differences or superficial variations.
    
-   **Parallel inheritance hierarchies** with identical methods.
    
-   **Repetitive setup/teardown** logic in tests or pipelines.
    
-   **Repeated algorithms** (e.g., tax, currency, pagination, retry logic, validation).
    

Avoid or postpone when:

-   The duplicates are **intentionally divergent** for latency, compliance, or rollout safety.
    
-   The shared dependency would **introduce an undesirable coupling**; first fix the boundary (e.g., via an internal library or service).
    

## Structure

```css
Before:                           After:
A.foo()  ──┐                      A.foo() ─┐
B.foo()  ──┤  (duplicate)   ──►   B.foo()  ├──► Shared Abstraction (Function/Class/Module/Service)
C.foo()  ──┘                      C.foo() ─┘
```

## Participants

-   **Callers:** Components currently hosting duplicate logic.
    
-   **Shared Abstraction:** The new single source of truth (utility function, domain service, base class, strategy).
    
-   **Tests:** Executable specification that locks in behavior and prevents regression.
    
-   **Build/Repo Owners:** Ensure the shared abstraction is accessible (module, package, service).
    

## Collaboration

-   Identify duplicates with tooling (clone detectors, PMD/SpotBugs, IDE inspections) and code reviews.
    
-   Agree on **ownership** of the extracted abstraction (team, repo, versioning).
    
-   Provide a **migration plan** for consumers (deprecation window, semantic versioning).
    
-   Use **feature flags** or shadow calls if consolidating behavior with production risk.
    

## Consequences

**Benefits**

-   Single place to fix bugs and evolve logic.
    
-   Smaller codebase; lower cognitive load.
    
-   Consistent behavior across the system; easier onboarding.
    

**Liabilities / Trade-offs**

-   Introduces a new dependency surface; potential coupling.
    
-   If designed too generically, may become **anemic “god” utility** or leaky abstraction.
    
-   Migration effort and short-term churn (PRs across many repos).
    

## Implementation

1.  **Find & Cluster Duplicates**
    
    -   Use tooling + grep + code review. Group by intent (e.g., “discount calc”, “JWT parsing”).
        
2.  **Lock Behavior with Tests**
    
    -   Golden-master or approval tests for each duplicate to capture current quirks.
        
3.  **Design the Abstraction**
    
    -   Prefer **simple function** first; escalate to class/strategy only if needed.
        
    -   Keep domain language; avoid “Utils” unless truly generic.
        
4.  **Extract & Inline**
    
    -   Create the shared API; switch one caller at a time; run tests; repeat.
        
5.  **Remove Dead Code**
    
    -   Delete old implementations; add deprecation notices until fully migrated.
        
6.  **Publish & Govern**
    
    -   Version the library; document usage; add CI checks to prevent regressions and re-duplication (e.g., clone-detection in CI).
        

## Sample Code (Java)

### Before (duplication across services)

```java
// In BillingService
public BigDecimal computeDiscount(BigDecimal subtotal, CustomerTier tier) {
  BigDecimal rate = switch (tier) {
    case GOLD -> new BigDecimal("0.15");
    case SILVER -> new BigDecimal("0.10");
    default -> BigDecimal.ZERO;
  };
  BigDecimal discounted = subtotal.multiply(BigDecimal.ONE.subtract(rate));
  return discounted.setScale(2, RoundingMode.HALF_UP);
}

// In PromotionService (nearly identical, different rounding)
public BigDecimal applyPromo(BigDecimal subtotal, CustomerTier tier) {
  BigDecimal rate = switch (tier) {
    case GOLD -> new BigDecimal("0.15");
    case SILVER -> new BigDecimal("0.10");
    default -> BigDecimal.ZERO;
  };
  BigDecimal discounted = subtotal.multiply(BigDecimal.ONE.subtract(rate));
  return discounted.setScale(2, RoundingMode.HALF_EVEN); // subtle divergence!
}
```

### After (consolidated abstraction with strategy hook)

```java
// Shared library: domain-oriented, not "Util"
package com.acme.pricing;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Objects;

public final class DiscountCalculator {

  public enum RoundingPolicy {
    RETAIL(RoundingMode.HALF_UP),
    FINANCE(RoundingMode.HALF_EVEN);
    final RoundingMode mode;
    RoundingPolicy(RoundingMode mode){ this.mode = mode; }
  }

  private final RoundingPolicy roundingPolicy;

  private DiscountCalculator(RoundingPolicy roundingPolicy) {
    this.roundingPolicy = Objects.requireNonNull(roundingPolicy);
  }

  public static DiscountCalculator retail()  { return new DiscountCalculator(RoundingPolicy.RETAIL); }
  public static DiscountCalculator finance() { return new DiscountCalculator(RoundingPolicy.FINANCE); }

  public BigDecimal priceAfterDiscount(BigDecimal subtotal, CustomerTier tier) {
    Objects.requireNonNull(subtotal); Objects.requireNonNull(tier);
    BigDecimal rate = switch (tier) {
      case GOLD -> new BigDecimal("0.15");
      case SILVER -> new BigDecimal("0.10");
      default -> BigDecimal.ZERO;
    };
    BigDecimal discounted = subtotal.multiply(BigDecimal.ONE.subtract(rate));
    return discounted.setScale(2, roundingPolicy.mode);
  }

  public enum CustomerTier { GOLD, SILVER, STANDARD }
}
```

```java
// BillingService uses the shared abstraction
import com.acme.pricing.DiscountCalculator;
import com.acme.pricing.DiscountCalculator.CustomerTier;

public class BillingService {
  private final DiscountCalculator calc = DiscountCalculator.retail();

  public Amount bill(Amount subtotal, CustomerTier tier) {
    var after = calc.priceAfterDiscount(subtotal.value(), tier);
    return new Amount(after);
  }
}

// PromotionService uses the same abstraction with a different policy if required
import com.acme.pricing.DiscountCalculator;
import com.acme.pricing.DiscountCalculator.CustomerTier;

public class PromotionService {
  private final DiscountCalculator calc = DiscountCalculator.finance();

  public Amount apply(Amount subtotal, CustomerTier tier) {
    var after = calc.priceAfterDiscount(subtotal.value(), tier);
    return new Amount(after);
  }
}

// Tiny value object
import java.math.BigDecimal;
public record Amount(BigDecimal value) {}
```

### Test (golden-master behavior preserved)

```java
class DiscountCalculatorTest {
  @org.junit.jupiter.api.Test
  void retailRoundingMatchesLegacy() {
    var calc = DiscountCalculator.retail();
    var out = calc.priceAfterDiscount(new BigDecimal("123.456"), DiscountCalculator.CustomerTier.GOLD);
    org.assertj.core.api.Assertions.assertThat(out.toPlainString()).isEqualTo("104.94");
  }
}
```

## Known Uses

-   Consolidation of **date/time** and **money** handling into shared libraries to avoid locale/rounding bugs.
    
-   Centralized **HTTP client wrappers** with retries/timeouts/trace propagation.
    
-   Unifying **validation** (email, VAT, IBAN) rules across services.
    
-   Replacing duplicated **SQL pagination** or **cursor** logic with a common repository helper.
    
-   Pull Up Method in OO hierarchies where subclasses repeated identical logic.
    

## Related Patterns

-   **Extract Method / Extract Class:** Micro-refactorings used to consolidate.
    
-   **Pull Up Method / Template Method / Strategy:** OO techniques to remove duplication across classes.
    
-   **Replace Conditional with Polymorphism:** When duplication stems from branching on types.
    
-   **Introduce Parameter Object:** When duplicates differ only in long parameter lists.
    
-   **Move Method / Move Field:** Align behavior with owning class to reduce scattered copies.
    
-   **Facade:** Expose a unified API to replace repeated integration glue.

