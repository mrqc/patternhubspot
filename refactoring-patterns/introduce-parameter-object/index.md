# Introduce Parameter Object — Refactoring Pattern

## Pattern Name and Classification

**Name:** Introduce Parameter Object  
**Classification:** Refactoring Pattern (API Simplification / Cohesion & Encapsulation)

## Intent

Replace **long or repetitive parameter lists** with a **single object** that groups related values (context), improving readability, cohesion, validation, and evolution of method signatures.

## Also Known As

-   Introduce *Context* Object
    
-   Group Parameters
    
-   Aggregate Parameters
    
-   Request Object / Command Object (when carrying intent)
    

## Motivation (Forces)

-   **Long parameter lists** are hard to read and call correctly; call sites become noisy.
    
-   **Duplication:** The same parameter clusters recur across multiple methods.
    
-   **Validation scattering:** Constraints get rechecked at each call site or method.
    
-   **Evolution pain:** Adding/removing parameters breaks many callers.
    
-   **Semantic grouping:** Certain values belong together temporally or domain-wise (e.g., date range, pagination, payment details).
    

## Applicability

Apply when:

-   A method accepts **3+ parameters**, often passed together elsewhere.
    
-   The same **tuple** shows up across many methods or classes.
    
-   There are **invariants across parameters** (e.g., `start <= end`, currency alignment).
    
-   You anticipate **API evolution** (adding options/flags) and want to avoid signature churn.
    

Avoid or defer when:

-   The parameters are **truly independent** and used only once.
    
-   You would create a **weak “bag-of-data”** with no meaningful invariants or behavior.
    
-   You are on a hot path and object allocation overhead is proven significant (rare in typical business systems).
    

## Structure

```css
Before:
report(fromDate, toDate, timezone, locale, currency, includeTax)

After:
report(ReportRequest request)

ReportRequest {
  DateRange range;
  Locale locale;
  ZoneId timezone;
  Currency currency;
  boolean includeTax;
}
```

## Participants

-   **Parameter Object (Context/Request):** Aggregates related values and invariants.
    
-   **Caller:** Builds the parameter object (builder/factory) and passes it.
    
-   **Callee:** Consumes the object, often delegating validation to it.
    
-   **Value Objects inside:** E.g., `DateRange`, `Money`, `PageRequest`.
    

## Collaboration

-   The **caller** constructs a valid parameter object (possibly via builder).
    
-   The **callee** receives a single argument, accesses strongly typed fields/methods, and can rely on **centralized validation**.
    
-   Parameter objects may carry **behavior** (e.g., `range.overlaps(other)`), not just data.
    

## Consequences

**Benefits**

-   **Readable signatures** and clearer intent at call sites.
    
-   **Centralized validation** and invariants; less duplication.
    
-   **Easier evolution** (add a field without changing method signatures).
    
-   Encourages **domain modeling** (value objects like `DateRange`, `Money`).
    
-   Better **testability**: create one object once and reuse across tests.
    

**Liabilities / Trade-offs**

-   Risk of **anemic “bags”** if no invariants/behavior are modeled.
    
-   Might **hide unnecessary parameters**—keep the object cohesive.
    
-   Additional type + construction code (mitigate with records/builders).
    

## Implementation

1.  **Spot Parameter Clusters**
    
    -   Search for repeated groups and long signatures.
        
2.  **Create a Parameter Object**
    
    -   Start with fields; encode **invariants in constructor** (or builder `.build()`). Prefer **immutable** objects.
        
3.  **Migrate the Callee**
    
    -   Replace the old parameter list with the new object; update internal usage.
        
4.  **Update Call Sites**
    
    -   Construct the object where values originate; remove duplicate validations.
        
5.  **Enrich with Behavior**
    
    -   Move related logic into the parameter object (e.g., `range.duration()`).
        
6.  **Iterate & Split**
    
    -   If the object grows unrelated concerns, **split** into cohesive sub-objects (ISP at object level).
        
7.  **Deprecate Old API** (if public)
    
    -   Provide an adapter overload temporarily; remove later.
        

---

## Sample Code (Java)

### 1) Before → After (basic grouping)

**Before**

```java
public class ReportService {
  public Report generate(LocalDate from, LocalDate to,
                         ZoneId zone, Locale locale,
                         Currency currency, boolean includeTax) {
    if (from.isAfter(to)) throw new IllegalArgumentException("from > to");
    // ... compute using all parameters ...
    return new Report();
  }
}
```

**After (Introduce Parameter Object)**

```java
public class ReportService {
  public Report generate(ReportRequest req) {
    // invariants already checked inside ReportRequest
    // ... compute using req.range(), req.zone(), req.locale(), ...
    return new Report();
  }
}
```

```java
public final class ReportRequest {
  private final DateRange range;
  private final ZoneId zone;
  private final Locale locale;
  private final Currency currency;
  private final boolean includeTax;

  private ReportRequest(DateRange range, ZoneId zone, Locale locale, Currency currency, boolean includeTax) {
    this.range = Objects.requireNonNull(range);
    this.zone = Objects.requireNonNull(zone);
    this.locale = Objects.requireNonNull(locale);
    this.currency = Objects.requireNonNull(currency);
    this.includeTax = includeTax;
  }

  public static Builder builder() { return new Builder(); }

  public DateRange range() { return range; }
  public ZoneId zone() { return zone; }
  public Locale locale() { return locale; }
  public Currency currency() { return currency; }
  public boolean includeTax() { return includeTax; }

  public static final class Builder {
    private LocalDate from, to;
    private ZoneId zone = ZoneId.of("UTC");
    private Locale locale = Locale.US;
    private Currency currency = Currency.getInstance("USD");
    private boolean includeTax = true;

    public Builder from(LocalDate v){ this.from = v; return this; }
    public Builder to(LocalDate v){ this.to = v; return this; }
    public Builder zone(ZoneId v){ this.zone = v; return this; }
    public Builder locale(Locale v){ this.locale = v; return this; }
    public Builder currency(Currency v){ this.currency = v; return this; }
    public Builder includeTax(boolean v){ this.includeTax = v; return this; }

    public ReportRequest build() {
      var range = new DateRange(from, to); // validates order
      return new ReportRequest(range, zone, locale, currency, includeTax);
    }
  }
}
```

```java
/** Value object with invariant */
public record DateRange(LocalDate from, LocalDate to) {
  public DateRange {
    Objects.requireNonNull(from); Objects.requireNonNull(to);
    if (from.isAfter(to)) throw new IllegalArgumentException("from must be <= to");
  }
  public long days() { return java.time.temporal.ChronoUnit.DAYS.between(from, to) + 1; }
}
```

**Usage**

```java
ReportRequest req = ReportRequest.builder()
    .from(LocalDate.of(2025, 1, 1))
    .to(LocalDate.of(2025, 1, 31))
    .zone(ZoneId.of("Europe/Vienna"))
    .locale(Locale.GERMANY)
    .currency(Currency.getInstance("EUR"))
    .includeTax(true)
    .build();

Report report = new ReportService().generate(req);
```

### 2) Evolving APIs without signature churn

```java
// Later you add pagination and export format without changing ReportService signature
public enum ExportFormat { PDF, CSV, XLSX }

public final class ReportRequest {
  // ... previous fields ...
  private final Integer page;
  private final Integer pageSize;
  private final ExportFormat format;

  // extend builder with sensible defaults
  // existing call sites remain source-compatible
}
```

### 3) Behavior inside the parameter object (not a bag of data)

```java
public final class PaymentCommand {
  private final Money amount;
  private final String creditorIban;
  private final String remittanceInfo;

  public PaymentCommand(Money amount, String creditorIban, String remittanceInfo) {
    this.amount = Objects.requireNonNull(amount);
    this.creditorIban = validateIban(creditorIban);
    this.remittanceInfo = sanitize(remittanceInfo);
  }

  public boolean isHighValue() { return amount.isGreaterThan(new Money("10000.00", "EUR")); }
  public String maskedIban() { return "****" + creditorIban.substring(credItorIban.length() - 4); }

  private String validateIban(String iban) {
    // domain validation...
    return iban.replace(" ", "");
  }
}
```

### 4) Test Example

```java
class ReportRequestTest {
  @org.junit.jupiter.api.Test
  void rangeValidation() {
    var b = ReportRequest.builder().from(LocalDate.of(2025,2,1)).to(LocalDate.of(2025,1,1));
    org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, b::build);
  }
}
```

---

## Known Uses

-   **Pagination** objects: `PageRequest(page, size, sort)` across repositories/APIs.
    
-   **Date/time windows**: `DateRange`, `TimeWindow`, `Schedule` in reporting or billing.
    
-   **Search filters**: `SearchCriteria` (keywords, tags, facets) in services/controllers.
    
-   **Money & Currency** grouped into `Money` value object rather than primitive pairs.
    
-   **Configuration bundles**: `RetryPolicy`, `HttpClientOptions`, `ExecutionContext`.
    
-   **Command/Query DTOs** in CQRS and hexagonal architectures.
    

## Related Patterns

-   **Extract Method / Extract Class:** Often precede/follow this refactoring to clarify responsibilities.
    
-   **Replace Parameter with Method Call:** When a parameter can be derived from an object already available.
    
-   **Introduce Parameter Map** (temporary step): Replace many optional parameters with a map—usually superseded by a typed object.
    
-   **Value Object / Record:** Use immutable, behavior-rich objects for grouped data.
    
-   **Builder Pattern:** Construct complex parameter objects safely and fluently.
    
-   **Encapsulate Field / Encapsulate Collection:** Guard state within the parameter object itself.
    
-   **Method Object (Replace Method with Method Object):** For very long methods where locals become fields of a temporary object (a heavier variant).

