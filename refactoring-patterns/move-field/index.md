# Move Field — Refactoring Pattern

## Pattern Name and Classification

**Name:** Move Field  
**Classification:** Refactoring Pattern (Data Localization / Encapsulation & Cohesion)

## Intent

Relocate a field to the class where it **logically belongs and is primarily used**, improving cohesion, making invariants enforceable, and reducing feature envy and scattered knowledge.

## Also Known As

-   Move Data
    
-   Move Attribute / Relocate Member
    
-   Normalize Ownership of State
    

## Motivation (Forces)

-   **Feature envy:** Methods in another class keep reading/writing a field that sits “far away.”
    
-   **Weak invariants:** Validation and rules for a field can’t be enforced where the field lives.
    
-   **Tangled responsibilities:** A class holds configuration/state for a concept it doesn’t own.
    
-   **Change amplification:** Every change requires touching multiple classes because the data is elsewhere.
    
-   **Discoverability:** Developers look for a concept in its natural home; scattered fields slow understanding.
    

## Applicability

Apply when:

-   Most references/logic for a field occur in **another class** (or value object) than where it is declared.
    
-   The field’s **invariants** are best expressed/validated by another type.
    
-   A **new abstraction** emerged (e.g., `Money`, `PostalAddress`, `RetryPolicy`) that should own the state.
    
-   You’re preparing for **Extract Class** or **Replace Data Value with Object** and need to consolidate ownership.
    

Avoid or postpone when:

-   The field truly belongs to the current aggregate root for **transactional consistency**.
    
-   Moving the field would create **cross-aggregate coupling** or break persistence boundaries without a plan.
    
-   The field is **public API/serialization contract** you cannot change yet (introduce adapters first).
    

## Structure

```sql
Before:
+------------------+                 +-----------------------+
| Order            |  uses heavily   | ShippingPolicy        |
| - express : bool |---------------> | cost(..., express)    |
+------------------+                 +-----------------------+

After (moved field):
+------------------+                 +-----------------------+
| Order            |                 | ShippingPolicy        |
|                  |                 | - express : bool      |
|                  |                 | cost(...)             |
+------------------+                 +-----------------------+
```

## Participants

-   **Source Class:** Currently declares the field but doesn’t truly own its behavior.
    
-   **Target Class:** The class that owns the rules/behavior for the field.
    
-   **Clients:** Callers that read/write the field through methods; they must be migrated.
    
-   **Transitional Delegates (optional):** Temporary getters/setters left on the source class to preserve API during migration.
    

## Collaboration

-   The **target class** takes responsibility for invariants, defaulting, and mutation.
    
-   The **source class** delegates (temporarily) to the target or exposes intent-revealing operations.
    
-   Clients gradually switch to the target’s API or to new intent methods on the source.
    

## Consequences

**Benefits**

-   Higher cohesion; rules live next to the data.
    
-   Stronger invariants and simpler validation.
    
-   Clearer ownership and easier reuse/testing of the owning class.
    
-   Often reduces parameter/argument lists (less data shuttling).
    

**Liabilities / Trade-offs**

-   Short-term churn: migrations, serialization schema changes, database migrations.
    
-   Risk of **chatty interactions** if boundaries are drawn poorly.
    
-   Requires careful handling of **backward compatibility** (public APIs, events, JSON).
    

## Implementation

1.  **Identify the True Owner**
    
    -   Measure references: which class’s methods read/write the field most?
        
    -   Map invariants and who enforces them today.
        
2.  **Create/Choose Target Class**
    
    -   If missing, introduce a value object or policy class that naturally owns the field.
        
3.  **Add the Field to Target with Invariants**
    
    -   Initialize with safe defaults; add validation and intent-revealing accessors.
        
4.  **Redirect Behavior**
    
    -   Move methods using the field to the target (or delegate from source to target).
        
5.  **Migrate Call Sites**
    
    -   Update clients to use the target’s API (or new intent methods on the source).
        
    -   Keep **temporary delegating accessors** on the source (deprecated) to avoid big-bang changes.
        
6.  **Remove the Original Field**
    
    -   After all call sites migrate, delete the field from the source class.
        
    -   Update persistence/serialization and database schema if needed.
        
7.  **Regression Tests**
    
    -   Add/adjust tests for invariants now enforced by the target; keep integration tests green.
        

---

## Sample Code (Java)

### Scenario

An `Order` held an `express` flag used almost exclusively by `ShippingPolicy`. We move the field into `ShippingPolicy`, strengthen invariants, and give `Order` an intention-revealing API.

#### Before

```java
public class Order {
  private final List<OrderLine> lines = new ArrayList<>();
  private PostalAddress address;
  private boolean express; // <-- lives here but logic is in ShippingPolicy

  public void setExpress(boolean express) { this.express = express; }
  public boolean isExpress() { return express; }

  public BigDecimal shippingCost(ShippingPolicy policy) {
    return policy.cost(address, lines.size(), express);
  }

  // ...
}

public class ShippingPolicy {
  public BigDecimal cost(PostalAddress address, int itemCount, boolean express) {
    BigDecimal base = new BigDecimal("4.90");
    BigDecimal weightFee = BigDecimal.valueOf(itemCount).multiply(new BigDecimal("0.50"));
    BigDecimal expressFee = express ? new BigDecimal("6.00") : BigDecimal.ZERO;

    if ("US".equals(address.country()) && address.postalCode().startsWith("9")) {
      expressFee = expressFee.add(new BigDecimal("2.00"));
    }
    return base.add(weightFee).add(expressFee);
  }
}
```

#### After — Field moved; `Order` delegates intention, not state

```java
public class ShippingPolicy {

  private boolean express; // <-- moved field now owned here

  public ShippingPolicy express(boolean value) {
    this.express = value;
    return this;
  }

  public boolean isExpress() { return express; }

  public BigDecimal cost(PostalAddress address, int itemCount) {
    BigDecimal base = new BigDecimal("4.90");
    BigDecimal weightFee = BigDecimal.valueOf(itemCount).multiply(new BigDecimal("0.50"));
    BigDecimal expressFee = express ? new BigDecimal("6.00") : BigDecimal.ZERO;

    if ("US".equals(address.country()) && address.postalCode().startsWith("9")) {
      expressFee = expressFee.add(new BigDecimal("2.00"));
    }
    return base.add(weightFee).add(expressFee);
  }
}

public class Order {
  private final List<OrderLine> lines = new ArrayList<>();
  private PostalAddress address;
  private ShippingPolicy shipping = new ShippingPolicy();

  /** Intention-revealing behavior; no 'express' field here anymore */
  public Order withExpressShipping() { this.shipping.express(true); return this; }
  public Order withStandardShipping() { this.shipping.express(false); return this; }

  public BigDecimal shippingCost() {
    if (address == null) throw new IllegalStateException("address required");
    return shipping.cost(address, lines.size());
  }

  // Transitional delegators (optional, deprecate/remove later)
  /** @deprecated moved to ShippingPolicy */
  @Deprecated public void setExpress(boolean express) { this.shipping.express(express); }
  /** @deprecated moved to ShippingPolicy */
  @Deprecated public boolean isExpress() { return this.shipping.isExpress(); }
}
```

#### Variant — Moving a field into a Value Object to enforce invariants

```java
// Before: scattered fields
public class Event {
  public LocalDate start;
  public LocalDate end;
  public boolean overlaps(Event other) {
    return !start.isAfter(other.end) && !end.isBefore(other.start);
  }
}

// After: move fields into a cohesive value object with invariant
public class Event {
  private DateRange range; // moved ownership
  public boolean overlaps(Event other) { return range.overlaps(other.range); }
}

public record DateRange(LocalDate start, LocalDate end) {
  public DateRange {
    if (start.isAfter(end)) throw new IllegalArgumentException("start <= end");
  }
  public boolean overlaps(DateRange other) {
    return !start.isAfter(other.end) && !end.isBefore(other.start);
  }
}
```

---

## Known Uses

-   Moving **money/currency** fields into a `Money` value object to centralize rounding and currency rules.
    
-   Moving **timezone/locale** fields into a `UserPreferences` or request `Context` object.
    
-   Moving **rate/threshold** fields from services into **policy objects** to enable A/B testing/configuration.
    
-   Moving **connection**/**retry** fields from various HTTP clients into a shared `HttpClientOptions`.
    

## Related Patterns

-   **Move Method / Move Function:** Often accompanies Move Field to keep behavior with data.
    
-   **Extract Class / Replace Data Value with Object:** Create a new home that owns the field and its rules.
    
-   **Encapsulate Field / Encapsulate Collection:** After moving, protect the field properly.
    
-   **Introduce Parameter Object:** If multiple fields belong together across calls, bundle them.
    
-   **Inline Class / Collapse Hierarchy:** The inverse when the current home adds no value.
    
-   **Change Bidirectional Association to Unidirectional:** Revisit associations after moving fields to reduce coupling.

