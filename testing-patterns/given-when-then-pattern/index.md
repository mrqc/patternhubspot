# Given–When–Then — Testing Pattern

## Pattern Name and Classification

-   **Name:** Given–When–Then (GWT)
    
-   **Classification:** xUnit/BDD Testing Pattern / Test Structure & Readability
    

## Intent

Structure tests as **Given** (preconditions/context), **When** (action under test), and **Then** (observable outcomes) to make intent **obvious**, reduce noise, and align tests with **business language** and **user behavior**.

## Also Known As

-   BDD Scenario Format
    
-   Arrange–Act–Assert (AAA) — closely related; GWT uses more domain language
    
-   Story Tests (when paired with feature files)
    

## Motivation (Forces)

-   **Clarity vs. detail:** Tests should explain *why* a behavior matters without burying readers in setup code.
    
-   **Communication:** Product/QA/devs need a shared vocabulary for examples.
    
-   **Maintainability:** A consistent structure prevents “god tests” with tangled setup and assertions.
    
-   **Traceability:** Clear mapping from requirement → scenario → assertions.
    

## Applicability

Use GWT when:

-   Describing **user journeys** or domain rules (“Given a VIP… When they check out… Then shipping is free”).
    
-   Tests tend to mix heavy fixtures with multiple assertions; you want one **behavior** per test.
    
-   You practice **BDD** (with or without Cucumber).
    

Avoid or adapt when:

-   Micro unit tests with trivial setup; AAA naming might be shorter.
    
-   Property-based tests (no single “When”).
    
-   Performance/load tests where outcomes aren’t simple assertions.
    

## Structure

-   **Given:** Build context, data, and doubles. Keep it **deterministic** and focused.
    
-   **When:** Execute a **single** action/trigger (method call, HTTP request, button click).
    
-   **Then:** Assert **observable** results and side effects (state, calls, events, responses).
    
-   **And / But:** Optional conjuncts to add more conditions or expectations.
    

```typescript
@Test
void scenario_name() {
  // Given ...
  // And ...
  // When ...
  // Then ...
  // And ...
}
```

## Participants

-   **System Under Test (SUT):** object/service/UI under examination.
    
-   **Collaborators:** repositories, gateways, clocks (often faked).
    
-   **Fixture/Builder:** helpers to create Given contexts.
    
-   **Assertions:** matchers verifying Then outcomes.
    

## Collaboration

1.  The test composes **Given** data and doubles.
    
2.  It triggers **When** (exactly one main action).
    
3.  It verifies **Then** outcomes (status, state, side effects).
    
4.  Optional hooks capture artifacts (logs/screenshots) when Then fails.
    

## Consequences

**Benefits**

-   **Readable** tests that serve as living documentation.
    
-   Encourages **single responsibility per test** (one When).
    
-   Works from **unit** to **E2E** level; easy to review with non-devs.
    
-   Pairs naturally with **feature files** and BDD tools.
    

**Liabilities**

-   Overzealous GWT can add **ceremony** for simple cases.
    
-   Multiple Thens may hide **multiple behaviors** in one test.
    
-   Poorly factored “Given” can become **brittle**/expensive.
    

## Implementation

### Guidelines

-   **One When per test.** If you need two actions, consider two tests (or “When… And when…” only if truly atomic).
    
-   **Name scenarios** in domain terms: `checkout_applies_free_shipping_for_vip()`.
    
-   **Keep Given thin:** use builders/factories; don’t test setup code.
    
-   **Assert outcomes, not internals:** prefer public APIs over peeking private state.
    
-   **Use clocks & fakes** to make Given deterministic.
    
-   **Tag data** with case IDs for debugging.
    
-   **Make failure messages speak domain,** not just numbers.
    

### Variants

-   **AAA (Arrange–Act–Assert):** same shape with technical phrasing.
    
-   **Cucumber/Gherkin:** external feature files; Java step definitions call your SUT.
    
-   **Fluent DSL:** small helpers like `given(...).when(...).then(...)` to standardize style.
    

---

## Sample Code (Java 17, JUnit 5, framework-free)

> Scenario: **Checkout** applies **free shipping** for VIP customers if basket total ≥ 100 EUR; otherwise 4.90 EUR.  
> We show:
> 
> 1.  A tiny SUT (`CheckoutService`)
>     
> 2.  A test class in clear **Given–When–Then** style
>     
> 3.  An optional micro-DSL to reduce ceremony
>     

```java
// ======= SUT (production code) =============================================
package example;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Objects;

public class CheckoutService {
  public record Customer(String id, boolean vip) {}
  public record Cart(BigDecimal itemsTotal) {
    public Cart { Objects.requireNonNull(itemsTotal); }
  }
  public record Quote(BigDecimal itemsTotal, BigDecimal shipping, BigDecimal grandTotal) {}

  private static final BigDecimal FREE_SHIPPING_THRESHOLD = new BigDecimal("100.00");
  private static final BigDecimal STANDARD_SHIPPING = new BigDecimal("4.90");

  public Quote quote(Customer customer, Cart cart) {
    Objects.requireNonNull(customer); Objects.requireNonNull(cart);
    BigDecimal ship = shippingFor(customer, cart.itemsTotal);
    BigDecimal grand = cart.itemsTotal.add(ship).setScale(2, RoundingMode.HALF_UP);
    return new Quote(cart.itemsTotal.setScale(2), ship.setScale(2), grand);
  }

  private BigDecimal shippingFor(Customer c, BigDecimal itemsTotal) {
    if (c.vip && itemsTotal.compareTo(FREE_SHIPPING_THRESHOLD) >= 0) return BigDecimal.ZERO;
    return STANDARD_SHIPPING;
  }
}
```

```java
// ======= Tests (Given–When–Then with JUnit 5) ===============================
package example;

import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

public class CheckoutServiceTest {

  final CheckoutService checkout = new CheckoutService();

  @Test
  void given_vip_customer_and_total_over_threshold_when_quote_then_shipping_is_free() {
    // Given a VIP customer and a cart totaling 120.00 EUR
    var customer = new CheckoutService.Customer("vip-1", true);
    var cart     = new CheckoutService.Cart(new BigDecimal("120.00"));

    // When I request a quote
    var quote = checkout.quote(customer, cart);

    // Then shipping is 0.00 and grand total equals items total
    assertEquals(new BigDecimal("0.00"), quote.shipping(), "VIPs over threshold get free shipping");
    assertEquals(new BigDecimal("120.00"), quote.grandTotal());
  }

  @Test
  void given_vip_below_threshold_when_quote_then_standard_shipping_applies() {
    // Given a VIP with small cart (99.99)
    var customer = new CheckoutService.Customer("vip-2", true);
    var cart     = new CheckoutService.Cart(new BigDecimal("99.99"));

    // When
    var quote = checkout.quote(customer, cart);

    // Then
    assertEquals(new BigDecimal("4.90"), quote.shipping());
    assertEquals(new BigDecimal("104.89"), quote.grandTotal());
  }

  @Test
  void given_regular_customer_when_quote_then_standard_shipping_always_applies() {
    // Given a regular customer (non-VIP) with a big cart
    var customer = new CheckoutService.Customer("user-1", false);
    var cart     = new CheckoutService.Cart(new BigDecimal("250.00"));

    // When
    var quote = checkout.quote(customer, cart);

    // Then
    assertEquals(new BigDecimal("4.90"), quote.shipping());
    assertEquals(new BigDecimal("254.90"), quote.grandTotal());
  }
}
```

```java
// ======= Optional: tiny GWT DSL for consistency (tests call this) ===========
package example;

import java.util.function.Supplier;
import static org.junit.jupiter.api.Assertions.*;

public final class Gwt {
  public static <T> When<T> Given(String description, Supplier<T> context) {
    // could log/annotate the Given step if desired
    return new When<>(context.get());
  }
  public static final class When<T> {
    private final T ctx;
    private When(T ctx) { this.ctx = ctx; }
    public <R> Then<T,R> When(String description, java.util.function.Function<T,R> action) {
      return new Then<>(ctx, action.apply(ctx));
    }
  }
  public static final class Then<T,R> {
    public final T ctx; public final R result;
    private Then(T ctx, R result) { this.ctx = ctx; this.result = result; }
    public Then<T,R> Then(String description, java.util.function.Consumer<Then<T,R>> assertions) {
      assertions.accept(this); return this;
    }
  }
}
```

```java
// ======= Example using the micro-DSL (optional) =============================
package example;

import static example.Gwt.Given;
import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

public class CheckoutServiceDslTest {
  static final class Ctx { CheckoutService svc = new CheckoutService(); CheckoutService.Customer cust; CheckoutService.Cart cart; }
  @Test
  void vip_over_threshold_with_dsl() {
    Given("a VIP and 120 EUR in cart", () -> {
      var c = new Ctx();
      c.cust = new CheckoutService.Customer("vip-3", true);
      c.cart = new CheckoutService.Cart(new BigDecimal("120.00"));
      return c;
    }).When("quoting", c -> c.svc.quote(c.cust, c.cart))
      .Then("shipping is free and totals match", t -> {
        assertEquals(new BigDecimal("0.00"), t.result.shipping());
        assertEquals(t.ctx.cart.itemsTotal(), t.result.grandTotal());
      });
  }
}
```

**Notes on the sample**

-   Tests read **left-to-right** in domain language; there’s exactly **one When** per test.
    
-   The optional DSL keeps step labels consistent without external dependencies.
    
-   Swap the SUT for your service/UI; the structure stays the same.
    

## Known Uses

-   Unit and service tests adopting **BDD style** without Cucumber.
    
-   API tests: “Given an authenticated user… When POST /orders… Then 201 + Location header.”
    
-   UI tests: “Given a logged-in user… When they add to cart… Then the badge increments.”
    
-   Risk/price/eligibility engines expressed as **concrete examples**.
    

## Related Patterns

-   **Arrange–Act–Assert (AAA):** the classic xUnit form; GWT is the domain-friendly variant.
    
-   **Cucumber/Feature Files (BDD):** externalize scenarios as Gherkin; Java step defs call the SUT.
    
-   **Data-Driven Testing:** parameterize the **Given** with tables or CSV.
    
-   **Contract Testing:** the **Then** asserts interface contracts for provider/consumer compatibility.
    
-   **End-to-End Testing:** same GWT structure at system scale (UI/API + infra).
    
-   **Fake Object / Test Doubles:** simplify **Given** by swapping heavy collaborators.
    

---

## Implementation Tips

-   Keep **setup helpers** close to tests (builders/factories) to avoid noisy Givens.
    
-   Prefer **one behavior per test**; if you need many Thens, split the scenario.
    
-   Make failure messages **speak the domain** (e.g., “VIPs over 100 EUR get free shipping”).
    
-   Centralize **common preconditions** with DSL/builders, not with shared mutable fixtures.
    
-   Use **parameterized tests** to sweep variations of the Given while keeping a single When/Then body.
    
-   Pair with **naming conventions**: `given_<context>_when_<action>_then_<outcome>()` for greppable, self-documenting tests.

