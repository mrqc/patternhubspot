# Extract Class — Refactoring Pattern

## Pattern Name and Classification

**Name:** Extract Class  
**Classification:** Refactoring Pattern (Divide-and-Conquer / Separation of Concerns)

## Intent

Split a **bloated class** that holds multiple responsibilities into **two (or more) cohesive classes**, each with a clear purpose and API. This reduces coupling, improves readability/testability, and unlocks independent evolution.

## Also Known As

-   Class Decomposition
    
-   Separate Responsibilities
    
-   Cohesion Increase
    

## Motivation (Forces)

-   **Feature envy & shotgun surgery:** Unrelated changes require touching one god class.
    
-   **Low cohesion, high cognitive load:** Fields and methods cluster into distinct concerns.
    
-   **Testing friction:** Hard to isolate behaviors (e.g., shipping rules vs. order math).
    
-   **Growth pressure:** Adding features to an already huge class increases risk.
    
-   **API clarity:** Consumers can depend on the subset they actually need.
    

## Applicability

Apply when you see:

-   A class with **\>300–500 LOC**, many fields, or long method list.
    
-   Methods and fields forming **natural clusters** (e.g., “address/contacts,” “pricing/discounts,” “IO/persistence”).
    
-   Multiple **reasons to change** (violates Single Responsibility Principle).
    
-   Repeated parameter groups hinting at a missing abstraction.
    

Avoid or defer when:

-   The class is a **small, stable value object**.
    
-   Splitting would create **anemic, chatty objects** with high call overhead without real cohesion gain.
    

## Structure

```pgsql
Before (God Class):
+------------------------------+
| Order                        |
| - id                         |
| - items, totals              |
| - customer fields            |
| - address parsing/validation |
| - shipping price rules       |
| - payment/credit checks      |
| - printing/export            |
+------------------------------+

After (Extracted Classes):
+------------+     uses      +-------------------+
| Order      |-------------->| ShippingPolicy    |
| (domain)   |               | (rates & rules)   |
+------------+               +-------------------+
        |
        | has-a
        v
+----------------+
| PostalAddress  |
| (value object) |
+----------------+
```

## Participants

-   **Original Class:** The bloated owner of mixed concerns.
    
-   **Extracted Class(es):** New cohesive abstractions (e.g., `ShippingPolicy`, `PostalAddress`).
    
-   **Clients:** Callers that now depend on a smaller, clearer surface.
    
-   **Tests:** Guard behavior during extraction and prevent regressions.
    

## Collaboration

-   The original class **delegates** to the extracted class.
    
-   Extracted class exposes **intention-revealing methods**; data sharing via constructor/setters or dedicated DTOs/VOs.
    
-   Prefer **one-way dependencies** (domain → policy), avoiding cycles.
    

## Consequences

**Benefits**

-   Higher cohesion, smaller surface area, simpler tests.
    
-   Independent evolution and reuse of extracted parts.
    
-   Clearer ownership and boundaries; easier onboarding.
    

**Liabilities / Trade-offs**

-   Short-term churn (moving code, updating imports).
    
-   Potential **chatty interfaces** if boundaries are wrong.
    
-   Might reveal the need for **further refactorings** (e.g., Extract Interface, Move Method).
    

## Implementation

1.  **Identify Responsibility Clusters**
    
    -   Group fields/methods by topic (e.g., shipping rules, address handling).
        
2.  **Create the Extracted Class**
    
    -   Move the **tightest cohesive cluster first**; give it a clear name and API.
        
3.  **Move Fields & Methods**
    
    -   Start with data + private methods that only touch that data.
        
    -   Replace original code with **delegation** calls.
        
4.  **Resolve Data Flow**
    
    -   Pass required state via constructor or intent methods (avoid wide setters).
        
    -   Consider **value objects** for grouped data (e.g., `PostalAddress`).
        
5.  **Run Tests After Each Move**
    
    -   Keep behavior constant; add missing unit tests if needed.
        
6.  **Tighten the Boundary**
    
    -   Remove dead code; minimize getters/setters that leak internals.
        
7.  **Repeat** for the next cluster (e.g., payment, printing).
    

---

## Sample Code (Java)

### Before — One class doing too much

```java
public class Order {
  private final List<OrderLine> lines = new ArrayList<>();
  private String street, city, postalCode, country;
  private boolean express;

  public void addLine(String sku, int qty, BigDecimal unitPrice) {
    lines.add(new OrderLine(sku, qty, unitPrice));
  }

  public BigDecimal total() {
    return lines.stream()
        .map(l -> l.unitPrice().multiply(BigDecimal.valueOf(l.qty())))
        .reduce(BigDecimal.ZERO, BigDecimal::add);
  }

  // address validation & normalization (unrelated to order math)
  public void setAddress(String street, String city, String postalCode, String country) {
    if (street == null || street.isBlank()) throw new IllegalArgumentException("street");
    if (postalCode == null || !postalCode.matches("\\w[\\w- ]+")) throw new IllegalArgumentException("postal");
    this.street = street.strip();
    this.city = city.strip();
    this.postalCode = postalCode.toUpperCase();
    this.country = country.toUpperCase();
  }

  // shipping rules (unrelated to order math)
  public BigDecimal shippingCost() {
    BigDecimal base = new BigDecimal("4.90");
    BigDecimal weightFee = BigDecimal.valueOf(lines.size()).multiply(new BigDecimal("0.50"));
    BigDecimal expressFee = express ? new BigDecimal("6.00") : BigDecimal.ZERO;
    if ("US".equals(country) && postalCode.startsWith("9")) {
      expressFee = expressFee.add(new BigDecimal("2.00")); // remote surcharge
    }
    return base.add(weightFee).add(expressFee);
  }

  public void setExpress(boolean express) { this.express = express; }

  // nested record for brevity
  private record OrderLine(String sku, int qty, BigDecimal unitPrice) {}
}
```

### After — Extract `PostalAddress` and `ShippingPolicy`

```java
// Value Object: PostalAddress (encapsulates validation/normalization)
public final class PostalAddress {
  private final String street, city, postalCode, country;

  public PostalAddress(String street, String city, String postalCode, String country) {
    if (street == null || street.isBlank()) throw new IllegalArgumentException("street");
    if (postalCode == null || !postalCode.matches("\\w[\\w- ]+")) throw new IllegalArgumentException("postal");
    this.street = street.strip();
    this.city = city.strip();
    this.postalCode = postalCode.toUpperCase();
    this.country = country.toUpperCase();
  }

  public String street() { return street; }
  public String city() { return city; }
  public String postalCode() { return postalCode; }
  public String country() { return country; }
}

// Policy: all shipping logic lives here
public class ShippingPolicy {
  private final boolean express;

  public ShippingPolicy(boolean express) { this.express = express; }

  public BigDecimal cost(PostalAddress address, int itemCount) {
    BigDecimal base = new BigDecimal("4.90");
    BigDecimal weightFee = BigDecimal.valueOf(itemCount).multiply(new BigDecimal("0.50"));
    BigDecimal expressFee = express ? new BigDecimal("6.00") : BigDecimal.ZERO;

    if ("US".equals(address.country()) && address.postalCode().startsWith("9")) {
      expressFee = expressFee.add(new BigDecimal("2.00")); // remote surcharge
    }
    return base.add(weightFee).add(expressFee);
  }
}

// Order now delegates; it’s smaller and cohesive
public class Order {
  private final List<OrderLine> lines = new ArrayList<>();
  private PostalAddress shippingAddress;
  private ShippingPolicy shipping; // injected or set by builder

  public Order withShippingPolicy(ShippingPolicy policy) {
    this.shipping = policy;
    return this;
  }

  public void setShippingAddress(PostalAddress address) { this.shippingAddress = address; }

  public void addLine(String sku, int qty, BigDecimal unitPrice) {
    lines.add(new OrderLine(sku, qty, unitPrice));
  }

  public BigDecimal total() {
    return lines.stream()
        .map(l -> l.unitPrice().multiply(BigDecimal.valueOf(l.qty())))
        .reduce(BigDecimal.ZERO, BigDecimal::add);
  }

  public BigDecimal shippingCost() {
    if (shipping == null || shippingAddress == null)
      throw new IllegalStateException("shipping policy/address not set");
    return shipping.cost(shippingAddress, lines.size());
  }

  private record OrderLine(String sku, int qty, BigDecimal unitPrice) {}
}
```

### Unit Test Sketch (guards behavior during extraction)

```java
class ShippingPolicyTest {

  @org.junit.jupiter.api.Test
  void usWestExpressSurchargeApplied() {
    var address = new PostalAddress("1 Main", "SF", "94107", "US");
    var policy  = new ShippingPolicy(true);

    var cost = policy.cost(address, 3);

    org.assertj.core.api.Assertions.assertThat(cost).isEqualByComparingTo("4.90"  // base
        .concat("+") // just a visual note; compute exact BigDecimal in real tests
    );
  }
}
```

> **Why this helps:**
> 
> -   `Order` now focuses on **order math and orchestration**.
>     
> -   `PostalAddress` owns **validation/normalization**.
>     
> -   `ShippingPolicy` holds **rules**; it’s reusable across contexts and easy to test in isolation.
>     

## Known Uses

-   Splitting **UI controllers** into controller + presenter/view model.
    
-   Extracting **pricing/discount** or **tax** policies from `Invoice/Order`.
    
-   Moving **persistence** concerns into repositories from domain objects.
    
-   Isolating **validation** into value objects (Email, Money, Address).
    
-   Decomposing **God services** into focused domain services.
    

## Related Patterns

-   **Extract Method / Move Method / Move Field:** Micro-steps often used during extraction.
    
-   **Extract Interface:** Publish a narrow contract for the new class.
    
-   **Introduce Parameter Object / Value Object:** Group related data passed across methods.
    
-   **Encapsulate Field / Encapsulate Collection:** Protect state on both sides of the split.
    
-   **Facade:** If clients need a single entry point while the internals are split.
    
-   **Strategy / Policy:** When extracted behavior varies by rules and should be swappable.

