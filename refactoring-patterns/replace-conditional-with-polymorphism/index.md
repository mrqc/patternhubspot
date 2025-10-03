# Replace Conditional with Polymorphism — Refactoring Pattern

## Pattern Name and Classification

**Name:** Replace Conditional with Polymorphism  
**Classification:** Refactoring Pattern (Behavioral Decomposition / Strategy via Subtype Dispatch)

## Intent

Eliminate complex `if/else` or `switch` statements that select behavior by a **type code** (status, kind, role) by moving each branch into a **polymorphic implementation**. Call sites then invoke a single operation on an abstract type; the runtime subtype selects the correct behavior.

## Also Known As

-   Replace Type Code with Subclasses
    
-   Replace Conditional with Strategy
    
-   Polymorphic Dispatch / Dynamic Dispatch
    
-   Table-Driven Polymorphism (variant)
    

## Motivation (Forces)

-   **Brittle decision blobs:** Long conditionals grow as rules evolve; every change touches the same hotspot.
    
-   **Scattered knowledge:** Branch-specific data, validation, and computations are tangled.
    
-   **Closed for extension:** Adding a new variant means editing central switch statements (“open/closed” violation).
    
-   **Testing friction:** Each branch needs separate setup; unit tests can’t target behavior cleanly.
    
-   **Duplication:** The same switch appears in multiple places for the same axis of variation.
    

## Applicability

Apply when:

-   A **stable axis of variation** (e.g., `VehicleType`, `CustomerTier`, `DocumentState`) drives branching.
    
-   The same conditional appears in **multiple methods/places**.
    
-   Branches operate on **the same conceptual operation** but differ in details.
    
-   You want **extensibility** (add new variants without changing existing callers).
    

Avoid or postpone when:

-   Branches perform **completely unrelated tasks** (split first with *Extract Method* or *Extract Class*).
    
-   The axis of variation is **transient/experimental** and likely to collapse soon.
    
-   There are only **two trivial branches** and they won’t grow.
    

## Structure

```java
Before:
+------------------+
| PricingService   |
|  price(o) {      |
|    switch (o.tier) {  // GOLD/SILVER/STANDARD
|      case GOLD: ...   |
|      case SILVER: ... |
|      default: ...     |
|    }                  |
|  }                    |
+------------------+

After:
+--------------------+   +------------------+  +-------------------+
| interface Tier     |   | GoldTier         |  | SilverTier        |
|  BigDecimal price(...) | BigDecimal price |  | BigDecimal price  |
+---------▲----------+   +---------▲--------+  +---------▲---------+
          |                            (other variants)
          |
   +------┴-------+
   | StandardTier |
   +--------------+

Caller:
   BigDecimal p = order.tier().price(order);
```

## Participants

-   **Abstract Type / Interface:** Declares the operation formerly guarded by conditionals.
    
-   **Concrete Variants (Subclasses/Strategies):** Implement branch-specific logic and invariants.
    
-   **Context/Caller:** Holds or is associated with the variant and calls the abstract operation.
    
-   **Factory/Mapper:** Constructs the proper variant from a code or configuration (during migration).
    

## Collaboration

-   The **caller** delegates: `variant.behavior(args)`—no switches.
    
-   New variants plug in by **adding a class** and wiring it; existing code remains unchanged.
    
-   Shared behavior can live in an **abstract base** with template methods or default hooks.
    

## Consequences

**Benefits**

-   Removes repetitive switches and central hotspots; **open for extension**.
    
-   Localizes rules and **strengthens invariants** per variant.
    
-   Improves **testability** (test each subtype independently).
    
-   Encourages **cohesive models** (variant-specific data sits with behavior).
    

**Liabilities / Trade-offs**

-   **More classes**/types; can feel heavyweight for small systems.
    
-   If the axis of variation changes, you may need to revisit the hierarchy.
    
-   Risk of **over-engineering** if there are few stable variants.
    

## Implementation

1.  **Identify the Axis of Variation**
    
    -   Confirm the switch/if is selecting by “kind”: status/type/tier/role.
        
2.  **Define the Polymorphic Contract**
    
    -   Create an interface/abstract class with the operation(s) replacing the conditional.
        
3.  **Create Concrete Variants**
    
    -   Move each branch’s logic (and data/invariants) into its own implementation.
        
4.  **Construct or Map Variants**
    
    -   Introduce a factory/mapper converting the old code (enum/int) to the new type.
        
5.  **Redirect Callers**
    
    -   Replace conditional sites with `variant.operation(…)`. Remove duplicated switches elsewhere.
        
6.  **Consolidate Shared Code**
    
    -   Move common parts to the base class or helpers; keep differences overridden.
        
7.  **Test & Remove Legacy Paths**
    
    -   Add subtype-specific tests and contract tests; delete the original conditional.
        

---

## Sample Code (Java)

### Before — Pricing by tier with a `switch`

```java
public class PricingService {

  public BigDecimal priceFor(Order order) {
    BigDecimal total = order.items().stream()
        .map(li -> li.unitPrice().multiply(BigDecimal.valueOf(li.qty())))
        .reduce(BigDecimal.ZERO, BigDecimal::add);

    switch (order.tier()) {
      case GOLD:
        return total.multiply(new BigDecimal("0.85")).setScale(2, RoundingMode.HALF_EVEN);
      case SILVER:
        return total.multiply(new BigDecimal("0.90")).setScale(2, RoundingMode.HALF_EVEN);
      default:
        return total.setScale(2, RoundingMode.HALF_EVEN);
    }
  }
}

enum CustomerTier { GOLD, SILVER, STANDARD; }

record Order(List<LineItem> items, CustomerTier tier) {}
record LineItem(String sku, int qty, BigDecimal unitPrice) {}
```

### After — Polymorphism (subtypes/strategies)

```java
public interface TierPricing {
  BigDecimal priceFor(Order order);
}

public abstract class BaseTierPricing implements TierPricing {
  protected BigDecimal subtotal(Order order) {
    return order.items().stream()
        .map(li -> li.unitPrice().multiply(BigDecimal.valueOf(li.qty())))
        .reduce(BigDecimal.ZERO, BigDecimal::add);
  }
  protected BigDecimal scale(BigDecimal v) { return v.setScale(2, RoundingMode.HALF_EVEN); }
}

public final class GoldPricing extends BaseTierPricing {
  public BigDecimal priceFor(Order order) {
    return scale(subtotal(order).multiply(new BigDecimal("0.85")));
  }
}
public final class SilverPricing extends BaseTierPricing {
  public BigDecimal priceFor(Order order) {
    return scale(subtotal(order).multiply(new BigDecimal("0.90")));
  }
}
public final class StandardPricing extends BaseTierPricing {
  public BigDecimal priceFor(Order order) {
    return scale(subtotal(order));
  }
}

public class TierPricingFactory {
  public static TierPricing of(CustomerTier tier) {
    return switch (tier) {
      case GOLD -> new GoldPricing();
      case SILVER -> new SilverPricing();
      case STANDARD -> new StandardPricing();
    };
  }
}

public class PricingService {

  public BigDecimal priceFor(Order order) {
    TierPricing pricing = TierPricingFactory.of(order.tier());
    return pricing.priceFor(order); // no switch here
  }
}
```

### Variant — Strategy chosen once and cached (no factory at each call)

```java
public final class Customer {
  private final TierPricing pricing; // chosen at creation or login
  public Customer(TierPricing pricing) { this.pricing = pricing; }
  public BigDecimal price(Order order) { return pricing.priceFor(order); }
}
```

### Variant — Table-driven polymorphism without subclasses

```java
public final class MapPricing implements TierPricing {
  private final Function<BigDecimal, BigDecimal> rule;

  private MapPricing(Function<BigDecimal, BigDecimal> rule) { this.rule = rule; }

  public static Map<CustomerTier, TierPricing> rules() {
    return Map.of(
      CustomerTier.GOLD,    new MapPricing(s -> s.multiply(new BigDecimal("0.85"))),
      CustomerTier.SILVER,  new MapPricing(s -> s.multiply(new BigDecimal("0.90"))),
      CustomerTier.STANDARD,new MapPricing(s -> s)
    );
  }

  @Override public BigDecimal priceFor(Order order) {
    BigDecimal subtotal = order.items().stream()
        .map(li -> li.unitPrice().multiply(BigDecimal.valueOf(li.qty())))
        .reduce(BigDecimal.ZERO, BigDecimal::add);
    return subtotal.setScale(2, RoundingMode.HALF_EVEN)
                   .multiply(rule.apply(BigDecimal.ONE)) // apply factor
                   .setScale(2, RoundingMode.HALF_EVEN);
  }
}
```

---

## Known Uses

-   **State-dependent behavior:** Order/Document **state machines** where actions vary by state (`submit`, `cancel`, `approve`).
    
-   **Pricing/Discount engines:** Different discount rules by tier/segment/market.
    
-   **Tax/VAT rules by jurisdiction:** Each region encapsulates its calculation.
    
-   **Shipping rules by carrier:** Labeling, cost, and constraints per carrier strategy.
    
-   **Rendering/output formats:** PDF/CSV/JSON writers behind a `ReportRenderer` interface.
    
-   **Game development:** Entity behaviors per class (enemy AI strategies).
    

## Related Patterns

-   **Strategy:** The usual implementation vehicle; select algorithm at runtime.
    
-   **State:** When the variant is a **mutable lifecycle state** that transitions (the object holds a current state).
    
-   **Template Method:** Shared steps in base class with variant hooks.
    
-   **Factory / Abstract Factory:** To build the right variant from codes/config.
    
-   **Replace Type Code with Subclasses:** Close cousin when a field holds a type code.
    
-   **Decompose Conditional / Extract Method:** Often preparatory steps before introducing polymorphism.
    
-   **Introduce Parameter Object:** If branches pass the same long tuple, group it for cleaner variant APIs.

