# Strategy — Behavioral / Process Pattern

## Pattern Name and Classification

**Strategy** — *Behavioral / Process* pattern for selecting one of several **interchangeable algorithms/behaviors** at runtime.

---

## Intent

Define a family of algorithms, **encapsulate** each one, and make them **interchangeable** so the **Context** can vary its behavior **without conditionals** or code changes.

---

## Also Known As

-   **Policy**

-   **Algorithm Family**

-   **Pluggable Behavior**


---

## Motivation (Forces)

-   You have multiple ways to perform a task (pricing rules, routing, compression, sorting).

-   You want to **avoid `if/else` ladders** that hard-code algorithm choices.

-   You need to **swap/compose** behaviors per feature flag, tenant, environment, or input.


Trade-offs: more objects to wire; too many micro-strategies can fragment logic—keep them meaningful.

---

## Applicability

Use Strategy when:

-   There are **several algorithms** with the same goal but different trade-offs.

-   You need **runtime selection** (config/flags/DI) or **A/B testing**.

-   You want to **unit-test** algorithms in isolation.


Avoid when:

-   There’s only one stable algorithm, or switching is purely data-driven inside the algorithm.


---

## Structure

```arduino
Client → Context ── delegates → Strategy (interface)
                      ▲                 ▲
                      └───── ConcreteStrategyA / ConcreteStrategyB / ...
```

---

## Participants

-   **Strategy** — common interface for the algorithm.

-   **Concrete Strategies** — implementations of the algorithm.

-   **Context** — holds a `Strategy` and delegates the work.

-   **Client/Factory** — chooses which strategy to use (DI, config, registry).


---

## Collaboration

1.  Client selects a `Strategy` and gives it to the `Context`.

2.  Context calls strategy methods instead of branching.

3.  Behavior changes by **swapping** the strategy object.


---

## Consequences

**Benefits**

-   Eliminates branching; **Open/Closed** for new algorithms.

-   Promotes **testability** and **reuse**.

-   Enables runtime selection and feature flags.


**Liabilities**

-   More types to manage.

-   Context must expose a consistent **Strategy** interface (lowest common denominator).


---

## Implementation (Key Points)

-   Make `Strategy` a **functional interface** to allow **lambdas**.

-   Provide a **registry/factory** to map names → strategies.

-   Keep **state** out of strategies when possible; pass a **Context/DTO**.

-   For combos, either chain strategies (Decorator) or define a **Composite Strategy** deliberately.


---

## Sample Code (Java 17) — Pricing strategies (swap at runtime)

> We model a checkout **final price** calculation with interchangeable pricing policies.

```java
import java.util.*;
import java.util.function.Function;

// ----- Domain -----
enum Tier { BASIC, SILVER, GOLD }

record Quote(int subtotalCents, Tier tier, String country, boolean hasPromoCode) {}

// ----- Strategy SPI (functional interface) -----
@FunctionalInterface
interface PricingStrategy {
  int finalPriceCents(Quote q); // returns final price in cents (non-negative)
}

// ----- Concrete strategies -----

// 1) No discounts, just return subtotal
final class FlatPricing implements PricingStrategy {
  @Override public int finalPriceCents(Quote q) { return Math.max(0, q.subtotalCents()); }
}

// 2) Loyalty discount: SILVER 5%, GOLD 10%
final class LoyaltyDiscount implements PricingStrategy {
  @Override public int finalPriceCents(Quote q) {
    double rate = switch (q.tier()) { case GOLD -> 0.10; case SILVER -> 0.05; default -> 0.0; };
    return Math.max(0, (int)Math.round(q.subtotalCents() * (1.0 - rate)));
  }
}

// 3) Promo code: flat 5€ off if present
final class PromoDiscount implements PricingStrategy {
  @Override public int finalPriceCents(Quote q) {
    int discount = q.hasPromoCode() ? 500 : 0;
    return Math.max(0, q.subtotalCents() - discount);
  }
}

// 4) Regional VAT-inclusive “price builder”: add 20% VAT for AT, 10% for US (demo)
final class VatInclusive implements PricingStrategy {
  @Override public int finalPriceCents(Quote q) {
    double vat = switch (q.country()) { case "AT" -> 0.20; case "US" -> 0.10; default -> 0.15; };
    return Math.max(0, (int)Math.round(q.subtotalCents() * (1.0 + vat)));
  }
}

// 5) Composite strategy example: apply BEST OF (min price) across given strategies
final class BestOfPricing implements PricingStrategy {
  private final List<PricingStrategy> candidates;
  BestOfPricing(List<PricingStrategy> candidates) { this.candidates = List.copyOf(candidates); }
  @Override public int finalPriceCents(Quote q) {
    return candidates.stream().mapToInt(s -> s.finalPriceCents(q)).min().orElse(q.subtotalCents());
  }
}

// ----- Context -----
final class PriceCalculator {
  private PricingStrategy strategy;
  PriceCalculator(PricingStrategy strategy) { this.strategy = strategy; }
  void setStrategy(PricingStrategy strategy) { this.strategy = strategy; }
  int calculate(Quote q) { return strategy.finalPriceCents(q); }
}

// ----- Registry / Factory (name → strategy) -----
final class PricingRegistry {
  private final Map<String, PricingStrategy> map = new HashMap<>();
  PricingRegistry register(String name, PricingStrategy s) { map.put(name, s); return this; }
  PricingStrategy byName(String name) {
    var s = map.get(name);
    if (s == null) throw new IllegalArgumentException("Unknown strategy: " + name);
    return s;
  }
}

// ----- Demo -----
public class StrategyDemo {
  public static void main(String[] args) {
    Quote q = new Quote(25_99, Tier.GOLD, "AT", true); // €25.99, GOLD, Austria, has promo

    // Build registry with both class-based and lambda strategies
    PricingRegistry reg = new PricingRegistry()
        .register("flat", new FlatPricing())
        .register("loyalty", new LoyaltyDiscount())
        .register("promo", new PromoDiscount())
        .register("vat", new VatInclusive())
        // Lambda strategy: “loyalty then promo” (compose explicitly)
        .register("loyalty_then_promo", (Quote x) -> {
          int afterLoyalty = new LoyaltyDiscount().finalPriceCents(x);
          return Math.max(0, afterLoyalty - (x.hasPromoCode() ? 500 : 0));
        })
        // Best-of: pick the lowest of loyalty vs promo
        .register("best_of", new BestOfPricing(List.of(new LoyaltyDiscount(), new PromoDiscount())));

    PriceCalculator calc = new PriceCalculator(reg.byName("flat"));

    // Swap strategies at runtime (feature flag, tenant config, A/B, etc.)
    print("flat", calc, q, reg);
    print("loyalty", calc, q, reg);
    print("promo", calc, q, reg);
    print("loyalty_then_promo", calc, q, reg);
    print("best_of", calc, q, reg);

    // Different market: VAT-inclusive (illustrates a completely different policy)
    print("vat", calc, new Quote(25_99, Tier.BASIC, "AT", false), reg);
  }

  private static void print(String name, PriceCalculator calc, Quote q, PricingRegistry reg) {
    calc.setStrategy(reg.byName(name));
    int cents = calc.calculate(q);
    System.out.printf("%-18s -> %s%n", name, money(cents));
  }
  private static String money(int cents) { return "€" + (cents / 100) + "." + String.format("%02d", cents % 100); }
}
```

**What to notice**

-   The `PriceCalculator` never branches — it **delegates** to the injected `PricingStrategy`.

-   We switch behavior by **swapping strategies** (registry lookup).

-   Strategies are **unit-testable**. You could wire them via DI (Spring) or configuration.


---

## Known Uses

-   Sorting (QuickSort/MergeSort/HeapSort).

-   Caching eviction (LRU/LFU/ARC).

-   Compression/serialization algorithms.

-   Payment/routing/tax/pricing rules by market/tenant.

-   Retry/backoff policies (exponential, fixed, jitter).

-   Pathfinding (Dijkstra vs A\*).


---

## Related Patterns

-   **State** — Strategy varies *how*; State varies *behavior by internal lifecycle* and performs transitions.

-   **Template Method** — fixed skeleton with overridable steps; Strategy replaces inheritance with composition.

-   **Decorator** — adds behavior by **wrapping**; Strategy **replaces** behavior.

-   **Factory / Abstract Factory** — chooses/creates the appropriate Strategy.

-   **Policy (DDD)** — Strategy is a concrete way to implement policies.
