# Decompose Conditional — Refactoring Pattern

## Pattern Name and Classification

**Name:** Decompose Conditional  
**Classification:** Refactoring Pattern (Control Flow Simplification / Readability & Maintainability)

## Intent

Improve readability and maintainability by **extracting complex conditional logic** (long `if/else` or `switch` statements with compound predicates and mixed responsibilities) into **well-named methods, guard clauses, and dedicated strategies** so that the branching intent becomes explicit and testable.

## Also Known As

-   Split Conditional
    
-   Extract Condition / Extract Branch
    
-   Guard Clauses
    
-   Replace Conditional with Strategy (when pushing to polymorphism)
    

## Motivation (Forces)

-   **Mixed concerns:** Condition checks, data gathering, and effects are interleaved.
    
-   **Cognitive load:** Large boolean expressions obscure business intent.
    
-   **Change risk:** Subtle edits to predicates cause bugs (e.g., precedence, null handling).
    
-   **Limited testability:** Hard to test tiny variations inside a monolithic conditional.
    
-   **Evolving rules:** Business rules accumulate exceptions that elongate branching.
    

## Applicability

Apply when you see:

-   Compound predicates like `if (a && (b || c) && !d)` mingled with side effects.
    
-   Repeated *similar* condition groups across the codebase.
    
-   Condition blocks performing **multiple responsibilities** (validation, pricing, authorization).
    
-   Long `switch`/`if-else if-else` chains driven by a domain concept (“product type”, “tier”, “status”).
    

Avoid or defer when:

-   The conditional is tiny, obvious, and will not grow.
    
-   Performance-critical hot paths where extra calls would be measurable (rare; can still inline after clarity).
    

## Structure

```kotlin
Before:
+-----------------------------------------+
| method()                                |
|   if (complex && (nested || chains)) {  |
|     // do A + B + C                     |
|   } else if (...) {                      |
|     // do D                             |
|   } else {                               |
|     // do E                             |
|   }                                      |
+-----------------------------------------+

After (decomposed):
+-----------------------------------------+
| method()                                |
|   if (isExceptional()) return handleX();|
|   if (isEligible())     return doEligiblePath(); 
|   return doDefaultPath();               |
+-----------------------------------------+
            |                |
      predicate methods   extracted actions
            |
   (or) Strategy/Policy object selected by context
```

## Participants

-   **Caller / Orchestrator:** High-level method that reads like a decision narrative.
    
-   **Predicate Methods:** Small, pure functions expressing intent (e.g., `isVipCustomer`, `isBlackoutPeriod`).
    
-   **Action Methods / Strategies:** Encapsulate branch behavior (e.g., `applyVipDiscount`, `denyBooking`).
    
-   **Policy/Strategy Objects (optional):** When branching follows a stable axis (type/status).
    

## Collaboration

-   Predicates expose *business vocabulary*; actions encapsulate side effects.
    
-   Orchestrator composes predicates and actions using **guard clauses** (fail/return early).
    
-   Strategies can be composed/injected for testability; predicates are unit-tested in isolation.
    

## Consequences

**Benefits**

-   Readable “story” in the orchestrator; easier onboarding.
    
-   Localized changes: modify a predicate or strategy without touching the others.
    
-   Higher testability and reuse of predicates across features.
    
-   Enables further refactorings (Strategy, Specification, Rule Engine) if rules grow.
    

**Liabilities / Trade-offs**

-   More methods/classes; slight indirection overhead.
    
-   Poorly named predicates can *increase* confusion—naming matters.
    
-   Over-engineering risk if rules are simple or transient.
    

## Implementation

1.  **Identify the Decision Points**
    
    -   Mark complex boolean expressions and long chains.
        
2.  **Extract Predicates**
    
    -   Create small, side-effect-free methods with domain names.
        
    -   Normalize null/empty checks inside predicates.
        
3.  **Introduce Guard Clauses**
    
    -   Replace nested `if`s with early returns for exceptional/fast-fail cases.
        
4.  **Extract Branch Actions**
    
    -   Pull effectful code into intention-revealing methods.
        
5.  **Consider Strategy/Policy**
    
    -   If branching is driven by one axis (type/status/tier), create a `Map<Axis, Strategy>`.
        
6.  **Add Tests**
    
    -   Unit-test predicates and actions independently; keep an integration test for the orchestrator.
        
7.  **Simplify and Inline Where Appropriate**
    
    -   If a predicate becomes trivial, you may inline it—but keep clarity.
        
8.  **Document Invariants**
    
    -   Javadoc/preconditions clarify assumptions (currency, time zone, permissions).
        

## Sample Code (Java)

### Before — Tangled Conditional

```java
public class FareService {

  public BigDecimal calculateFare(Trip trip, Customer customer, LocalDate date) {
    // giant, intertwined conditional logic
    if (trip == null || customer == null || date == null) {
      throw new IllegalArgumentException("missing data");
    }

    boolean peak = (date.getDayOfWeek().getValue() >= 1 && date.getDayOfWeek().getValue() <= 5)
        && (trip.getDepartureTime().getHour() >= 7 && trip.getDepartureTime().getHour() <= 9
        || trip.getDepartureTime().getHour() >= 16 && trip.getDepartureTime().getHour() <= 18);

    BigDecimal base = trip.getBaseFare();
    if (customer.isBlacklisted()) {
      return base.multiply(new BigDecimal("2.00")); // punitive
    } else if (customer.isVip() && !peak && trip.getDistanceKm() > 10) {
      BigDecimal d = base.multiply(new BigDecimal("0.85"));
      if (trip.isEcoVehicle()) {
        d = d.multiply(new BigDecimal("0.98"));
      }
      return d.setScale(2, RoundingMode.HALF_EVEN);
    } else if (peak && trip.getDistanceKm() < 3) {
      return base.add(new BigDecimal("2.50")).setScale(2, RoundingMode.HALF_EVEN);
    } else {
      return base.setScale(2, RoundingMode.HALF_EVEN);
    }
  }
}
```

### After — Decomposed with Predicates, Guard Clauses, and Strategy Hook

```java
public class FareService {

  private final RoundingMode rounding = RoundingMode.HALF_EVEN;

  public BigDecimal calculateFare(Trip trip, Customer customer, LocalDate date) {
    requireArgs(trip, customer, date);

    if (isPunitiveCase(customer)) {
      return punitiveFare(trip.getBaseFare());
    }
    if (isVipOffPeakLongTrip(customer, date, trip)) {
      return vipFare(trip);
    }
    if (isShortTripAtPeak(date, trip)) {
      return shortPeakFare(trip.getBaseFare());
    }
    return standardFare(trip.getBaseFare());
  }

  // ----- Predicates -----
  boolean isPunitiveCase(Customer c) { return c.isBlacklisted(); }

  boolean isVipOffPeakLongTrip(Customer c, LocalDate d, Trip t) {
    return c.isVip() && !isPeak(d, t) && t.getDistanceKm() > 10;
  }

  boolean isShortTripAtPeak(LocalDate d, Trip t) {
    return isPeak(d, t) && t.getDistanceKm() < 3;
  }

  boolean isPeak(LocalDate d, Trip t) {
    int dow = d.getDayOfWeek().getValue(); // 1=Mon..7=Sun
    int hour = t.getDepartureTime().getHour();
    boolean weekday = dow >= 1 && dow <= 5;
    boolean morning = hour >= 7 && hour <= 9;
    boolean evening = hour >= 16 && hour <= 18;
    return weekday && (morning || evening);
  }

  // ----- Actions -----
  BigDecimal punitiveFare(BigDecimal base) {
    return base.multiply(new BigDecimal("2.00")).setScale(2, rounding);
  }

  BigDecimal vipFare(Trip t) {
    BigDecimal d = t.getBaseFare().multiply(new BigDecimal("0.85"));
    if (t.isEcoVehicle()) d = d.multiply(new BigDecimal("0.98"));
    return d.setScale(2, rounding);
  }

  BigDecimal shortPeakFare(BigDecimal base) {
    return base.add(new BigDecimal("2.50")).setScale(2, rounding);
  }

  BigDecimal standardFare(BigDecimal base) {
    return base.setScale(2, rounding);
  }

  void requireArgs(Trip trip, Customer customer, LocalDate date) {
    if (trip == null || customer == null || date == null) {
      throw new IllegalArgumentException("missing data");
    }
  }
}
```

### Variant — Replace Conditional with Strategy (when axis is stable)

```java
public interface FarePolicy {
  BigDecimal price(Trip trip, Customer customer, LocalDate date);
}

public class PeakShortTripPolicy implements FarePolicy { /* ... */ }
public class VipOffPeakLongTripPolicy implements FarePolicy { /* ... */ }
public class PunitivePolicy implements FarePolicy { /* ... */ }
public class StandardPolicy implements FarePolicy { /* ... */ }

public class FareEngine {
  private final List<FarePolicy> policies;

  public FareEngine(List<FarePolicy> policies) { this.policies = List.copyOf(policies); }

  public BigDecimal calculate(Trip t, Customer c, LocalDate d) {
    return policies.stream()
        .map(p -> p.price(t, c, d))
        .filter(Objects::nonNull)
        .findFirst()
        .orElseThrow(); // or default
  }
}
```

## Known Uses

-   **Pricing/Discount engines:** Extracting predicates like `isBlackFriday`, `isVip`, `isBundleEligible`.
    
-   **Authorization/Feature flags:** Guard clauses and policy objects per permission/flag.
    
-   **Validation pipelines:** Predicates per constraint (Specification pattern).
    
-   **Workflow routing:** Strategy selection by status/type to avoid `switch` bloat.
    
-   **Legacy monoliths:** First step before migrating rules to a rules engine.
    

## Related Patterns

-   **Extract Method / Extract Function:** Primary micro-refactoring used here.
    
-   **Guard Clauses:** Early returns replacing deep nesting.
    
-   **Replace Conditional with Polymorphism (Strategy/State):** When branching follows a stable axis.
    
-   **Specification Pattern:** Compose business predicates declaratively.
    
-   **Consolidate Duplicate Conditional Fragments:** Remove repeated setup inside branches.
    
-   **Decompose Switch:** Special case targeting large `switch` statements.
    
-   **Introduce Parameter Object:** Simplify long parameter lists that feed predicates.

