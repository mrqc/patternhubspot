# Simplify Nested Conditional — Refactoring Pattern

## Pattern Name and Classification

**Name:** Simplify Nested Conditional  
**Classification:** Refactoring Pattern (Control-Flow Simplification / Readability & Maintainability)

## Intent

Flatten deeply nested `if/else` blocks to make the **happy path obvious** and exceptional or edge cases explicit. Use **guard clauses**, **early returns**, and **extracted predicates** so the method reads as a straightforward decision narrative.

## Also Known As

-   Replace Nested Conditional with Guard Clauses
    
-   Flatten Conditionals
    
-   Early Return / Fail Fast
    
-   De-nest Conditionals
    

## Motivation (Forces)

-   **Cognitive load:** Deep indentation hides the main intent and interleaves concerns.
    
-   **Error-proneness:** It’s easy to miss an `else` branch or invert logic by mistake.
    
-   **Testing friction:** Hard to isolate edge cases when the happy path is buried.
    
-   **Change amplification:** Adding a new rule requires threading through multiple nested levels.
    
-   **Readability:** Linear, guard-first methods are easier to scan and maintain.
    

## Applicability

Apply when you see:

-   Multiple levels of nested `if/else` guarding preconditions, errors, or special cases.
    
-   Early error checks hidden *inside* the main logic instead of up front.
    
-   Compound predicates in-line that could be **named** and reused (e.g., `isBlackout(date)`).
    
-   A method that “pyramids of doom” (ever-increasing indentation).
    

Avoid or defer when:

-   You must perform **mandatory cleanup** before returning (use `try-with-resources` / `finally`).
    
-   The logic is **truly sequential** and early returns would obscure required steps.
    
-   You’re in a **public API** that mandates a single exit for tracing—still possible, but use local helpers to clarify.
    

## Structure

```scss
Before (pyramid):
method() {
  if (preconditionA) {
    if (preconditionB) {
      // happy path buried
      doMainWork();
    } else {
      handleBFailure();
    }
  } else {
    handleAFailure();
  }
}

After (flat with guards):
method() {
  if (!preconditionA) return handleAFailure();
  if (!preconditionB) return handleBFailure();
  return doMainWork();
}
```

## Participants

-   **Orchestrating Method:** Hosts the decision flow.
    
-   **Guard Clauses:** Early checks that exit on invalid/edge scenarios.
    
-   **Predicate Methods:** Small, pure boolean queries expressing business rules.
    
-   **Action Methods:** Intention-revealing methods for each outcome.
    

## Collaboration

-   Predicates expose **domain language** (e.g., `isVip`, `isPeak`), which the orchestrator composes.
    
-   Guard clauses **short-circuit** edge cases, keeping the happy path linear.
    
-   Extracted actions encapsulate side effects and enable reuse.
    

## Consequences

**Benefits**

-   Flatter, more readable code; the **happy path is obvious**.
    
-   Fewer branches to reason about; lower bug surface.
    
-   Easier unit testing of predicates and actions in isolation.
    
-   Enables further refactorings (Replace Conditional with Polymorphism, Strategy, Specification).
    

**Liabilities / Trade-offs**

-   Multiple return points can complicate debugging in some contexts (usually outweighed by clarity).
    
-   Overuse of early returns without naming can still be cryptic—**good names matter**.
    
-   If cleanup is required, must ensure it always runs (use structured resources).
    

## Implementation

1.  **Identify Guard Candidates**
    
    -   Preconditions, null checks, authorization failures, unsupported states → move to **top** as early exits.
        
2.  **Extract Predicates**
    
    -   Convert complex boolean expressions into **well-named methods** (pure).
        
3.  **Introduce Guard Clauses**
    
    -   Replace outer `if (ok) { … } else { fail }` with `if (!ok) return fail;`.
        
4.  **Extract Actions**
    
    -   Pull branch bodies into methods with intention-revealing names.
        
5.  **Flatten Remaining Conditionals**
    
    -   Repeat until the main flow is linear.
        
6.  **Consider Strategy/Polymorphism**
    
    -   If the remaining conditional varies by type/state, move to polymorphism.
        
7.  **Test Thoroughly**
    
    -   Unit-test predicates and each guard; keep an integration test for the orchestrator.
        

---

## Sample Code (Java)

### Before — Deeply nested conditionals

```java
public class BookingService {

  public Reservation book(BookingRequest req, User user, Inventory inventory) {
    if (req != null) {
      if (user != null) {
        if (user.hasPermission("BOOK")) {
          if (!inventory.isSoldOut(req.date(), req.roomType())) {
            if (!req.date().isBefore(java.time.LocalDate.now())) {
              // happy path buried deep
              Reservation r = inventory.reserve(req.roomType(), req.date(), req.nights());
              if (r != null) {
                return r;
              } else {
                return Reservation.rejected("Reservation failed");
              }
            } else {
              return Reservation.rejected("Date in the past");
            }
          } else {
            return Reservation.rejected("Sold out");
          }
        } else {
          return Reservation.rejected("Not authorized");
        }
      } else {
        return Reservation.rejected("Missing user");
      }
    } else {
      return Reservation.rejected("Missing request");
    }
  }
}
```

### After — Guard clauses, extracted predicates, linear happy path

```java
public class BookingService {

  public Reservation book(BookingRequest req, User user, Inventory inventory) {
    if (req == null)              return reject("Missing request");
    if (user == null)             return reject("Missing user");
    if (!user.hasPermission("BOOK")) return reject("Not authorized");
    if (isPast(req.date()))       return reject("Date in the past");
    if (isSoldOut(inventory, req)) return reject("Sold out");

    return tryReserve(inventory, req);
  }

  // --- predicates (pure, intention-revealing) ---
  private boolean isPast(LocalDate date) {
    return date.isBefore(LocalDate.now());
  }

  private boolean isSoldOut(Inventory inv, BookingRequest req) {
    return inv.isSoldOut(req.date(), req.roomType());
  }

  // --- actions ---
  private Reservation tryReserve(Inventory inv, BookingRequest req) {
    Reservation r = inv.reserve(req.roomType(), req.date(), req.nights());
    return (r != null) ? r : reject("Reservation failed");
  }

  private Reservation reject(String reason) {
    return Reservation.rejected(reason);
  }
}
```

### Variant — Guard clauses with mandatory cleanup (try-with-resources)

```java
public class ReportService {

  public byte[] generate(ReportSpec spec, DataSource ds) throws IOException {
    if (spec == null) throw new IllegalArgumentException("spec");
    if (!spec.isValid()) return fail("Invalid spec");

    try (var conn = ds.getConnection();
         var out = new java.io.ByteArrayOutputStream()) {

      if (!hasAccess(spec)) return fail("Forbidden");
      writeReport(spec, conn, out);     // happy path
      return out.toByteArray();
    }
  }

  private byte[] fail(String msg) { throw new IllegalStateException(msg); }
}
```

### Variant — Decompose nested conditions, then polymorphism

```java
public class ShippingCostService {

  public BigDecimal cost(Order order) {
    if (!order.isDomestic()) return internationalPricing().price(order);
    if (order.weightKg() > 20) return heavyDomesticPricing().price(order);
    return standardDomesticPricing().price(order);
  }

  private PricingStrategy internationalPricing() { return new InternationalPricing(); }
  private PricingStrategy heavyDomesticPricing() { return new HeavyDomesticPricing(); }
  private PricingStrategy standardDomesticPricing() { return new StandardDomesticPricing(); }
}
```

---

## Known Uses

-   Authorization and validation at the **top** of controller/service methods (“fail fast”).
    
-   Pricing, shipping, or eligibility rules where many exceptions collapse into **named predicates**.
    
-   Legacy “pyramid” methods as a **first step** before introducing Strategy/State.
    
-   Handling **null/optional** inputs upfront, returning early or throwing with clear messages.
    

## Related Patterns

-   **Guard Clauses:** Core technique to exit early and flatten nesting.
    
-   **Decompose Conditional / Extract Method:** Used to separate predicates and actions.
    
-   **Replace Conditional with Polymorphism:** When a single axis (type/state) drives branching after flattening.
    
-   **Introduce Parameter Object:** Bundle inputs that travel through many predicates.
    
-   **Replace Temp with Query:** Remove temps to enable extraction of predicates.
    
-   **Strategy / Specification:** Model rule sets or composable business predicates once simplified.
    

**Guideline:** Put **error/edge checks first**, name your **predicates**, keep the **happy path straight**.

