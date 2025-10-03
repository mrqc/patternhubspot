# Extract Method — Refactoring Pattern

## Pattern Name and Classification

**Name:** Extract Method  
**Classification:** Refactoring Pattern (Control-Flow Simplification / Separation of Concerns)

## Intent

Improve readability, reuse, and testability by **moving a coherent fragment of code** (a block, loop, or conditional branch) into a **separately named method** with a clear purpose and parameters, replacing the original fragment with a call.

## Also Known As

-   Extract Function (general)
    
-   Introduce Subroutine
    
-   Decompose Method
    

## Motivation (Forces)

-   **Long methods hide intent:** Mixed calculations, validation, I/O, and branching blur the “story.”
    
-   **Change amplification:** Touching one concern risks breaking others co-located nearby.
    
-   **Duplicated fragments:** Similar code appears in multiple places.
    
-   **Poor testability:** Internal logic is hard to unit-test without heavy fixtures.
    
-   **Cognitive load:** Developers must track many local variables at once.
    

## Applicability

Apply when you see:

-   A method doing **more than one thing** (formatting + validation + persistence).
    
-   **Comment-labeled sections**—comments often hint at extractable intent.
    
-   **Deep nesting**, long loops, or complex predicates that would benefit from names.
    
-   **Repeated code** across methods or classes.
    

Avoid or postpone when:

-   The fragment is **truly trivial** and extraction would hurt clarity.
    
-   Extraction would create **leaky abstractions** (excessive parameters, awkward state coupling).
    
-   You are in a **hot path** where call overhead is measurable (rare; inline later if needed).
    

## Structure

```javascript
Before:
caller() {
  // [A] setup
  // [B] complex block worth naming
  // [C] wrap-up
}

After:
caller() {
  // [A] setup
  doComplexThing(args);       // named intention
  // [C] wrap-up
}

doComplexThing(params) { ... }   // extracted method
```

## Participants

-   **Original Method (Caller):** Orchestrates the high-level flow.
    
-   **Extracted Method(s):** Own one concern with a clear name and parameters.
    
-   **Collaborators:** Objects whose state/behavior the new method may use via parameters or fields.
    
-   **Tests:** Verify behavior before/after; new unit tests target the extracted method.
    

## Collaboration

-   The caller **delegates** to extracted methods by passing only the data they need (minimize coupling).
    
-   Extracted methods can become **reusable utilities** or move to more appropriate classes later (follow-up refactorings: *Move Method*, *Extract Class*).
    

## Consequences

**Benefits**

-   Methods read like **narratives** (“what” over “how”).
    
-   Enables reuse, isolated testing, and further refactorings.
    
-   Reduces duplication and local variable sprawl.
    

**Liabilities / Trade-offs**

-   Too many tiny methods can fragment the flow.
    
-   Poorly chosen boundaries lead to **chatty** parameter lists.
    
-   If extraction crosses wrong ownership, can **increase coupling**.
    

## Implementation

1.  **Identify a Cohesive Fragment**
    
    -   Look for code that reads like a single intention; keep side effects together.
        
2.  **Analyze Variables**
    
    -   Determine **inputs** (read-only), **modified values** (outputs), and **locals** you can recompute.
        
3.  **Create the Method**
    
    -   Name it by intention (`calculateTax`, `renderSummary`, `validateOrder`).
        
    -   Pass only necessary data; return a value if needed.
        
4.  **Replace the Original Code with a Call**
    
    -   Compile and run tests.
        
5.  **Adjust Visibility and Placement**
    
    -   Keep private initially; later consider moving to a better home (class/module).
        
6.  **Iterate**
    
    -   Repeat to flatten nesting (introduce **guard clauses**), and cluster extracted methods for later *Extract Class*.
        

---

## Sample Code (Java)

### 1) Before → After (basic extraction and naming)

**Before**

```java
public class InvoiceService {

  public String renderInvoice(Invoice invoice) {
    StringBuilder sb = new StringBuilder();

    // header
    sb.append("INVOICE ").append(invoice.id()).append("\n");
    sb.append("Customer: ").append(invoice.customerName()).append("\n");

    // lines + totals (complex, mixed concerns)
    BigDecimal total = BigDecimal.ZERO;
    for (LineItem li : invoice.items()) {
      BigDecimal lineTotal = li.unitPrice().multiply(BigDecimal.valueOf(li.quantity()));
      sb.append(li.sku()).append(" x").append(li.quantity())
        .append(" = ").append(lineTotal).append("\n");
      total = total.add(lineTotal);
    }
    BigDecimal tax = total.multiply(new BigDecimal("0.20"));
    BigDecimal grand = total.add(tax);

    // footer
    sb.append("Subtotal: ").append(total).append("\n");
    sb.append("Tax(20%): ").append(tax).append("\n");
    sb.append("Total: ").append(grand).append("\n");

    return sb.toString();
  }
}
```

**After**

```java
public class InvoiceService {

  public String renderInvoice(Invoice invoice) {
    StringBuilder sb = new StringBuilder();
    appendHeader(sb, invoice);
    BigDecimal subtotal = appendLinesAndComputeSubtotal(sb, invoice);
    appendTotals(sb, subtotal);
    return sb.toString();
  }

  private void appendHeader(StringBuilder sb, Invoice invoice) {
    sb.append("INVOICE ").append(invoice.id()).append("\n");
    sb.append("Customer: ").append(invoice.customerName()).append("\n");
  }

  private BigDecimal appendLinesAndComputeSubtotal(StringBuilder sb, Invoice invoice) {
    BigDecimal total = BigDecimal.ZERO;
    for (LineItem li : invoice.items()) {
      BigDecimal lineTotal = li.unitPrice().multiply(BigDecimal.valueOf(li.quantity()));
      sb.append(li.sku()).append(" x").append(li.quantity())
        .append(" = ").append(lineTotal).append("\n");
      total = total.add(lineTotal);
    }
    return total;
  }

  private void appendTotals(StringBuilder sb, BigDecimal subtotal) {
    BigDecimal tax = subtotal.multiply(new BigDecimal("0.20"));
    BigDecimal grand = subtotal.add(tax);
    sb.append("Subtotal: ").append(subtotal).append("\n");
    sb.append("Tax(20%): ").append(tax).append("\n");
    sb.append("Total: ").append(grand).append("\n");
  }
}
```

### 2) Deeper extraction with guard clauses and pure predicates

```java
public class BookingService {

  public Reservation book(BookingRequest req, Clock clock) {
    requireNonNull(req);
    if (isBlackout(req.date(), clock)) {
      throw new IllegalStateException("Blackout date");
    }
    if (!hasCapacity(req.roomType(), req.date())) {
      return Reservation.rejected("No capacity");
    }
    Money price = priceFor(req);
    return confirm(req, price);
  }

  // --- extracted pure predicates
  private boolean isBlackout(LocalDate date, Clock clock) {
    LocalDate today = LocalDate.now(clock);
    return date.isBefore(today) || isHoliday(date);
  }

  private boolean hasCapacity(RoomType type, LocalDate date) {
    // query cache or DB...
    return true;
  }

  // --- extracted actions
  private Money priceFor(BookingRequest req) {
    Money base = tariff(req.roomType(), req.date());
    return applyDiscounts(base, req.customerId());
  }

  private Reservation confirm(BookingRequest req, Money price) {
    // persist and emit event...
    return Reservation.confirmed(req.id(), price);
  }
}
```

### 3) Extract Method as a stepping stone to Extract Class

```java
public class ReportGenerator {

  public byte[] generateMonthlyReport(YearMonth ym) {
    List<Record> data = fetchData(ym);
    List<Record> cleaned = clean(data);
    String csv = toCsv(cleaned);     // extracted method
    return compress(csv);            // extracted method
  }

  // later these can move to a new CsvReport class
  private String toCsv(List<Record> rows) { /* ... */ return ""; }
  private byte[] compress(String payload) { /* ... */ return new byte[0]; }
}
```

### 4) Handling local variables (inputs/outputs) cleanly

```java
// Fragment computes a derived value used later: return it instead of mutating outer locals.
private BigDecimal computeGrandTotal(List<LineItem> items) {
  BigDecimal subtotal = items.stream()
      .map(li -> li.unitPrice().multiply(BigDecimal.valueOf(li.quantity())))
      .reduce(BigDecimal.ZERO, BigDecimal::add);
  BigDecimal tax = subtotal.multiply(new BigDecimal("0.20"));
  return subtotal.add(tax);
}
```

---

## Known Uses

-   Breaking down legacy “god methods” in controllers/services into **validation**, **calculation**, **persistence**, and **rendering** methods.
    
-   Extracting **predicate methods** (e.g., `isVipCustomer`, `isPeakTime`) for reuse across services.
    
-   Creating **self-documenting orchestration** in pipelines: `load()`, `transform()`, `save()`.
    
-   First step before **Extract Class**, **Extract Interface**, or moving logic into **policies/strategies**.
    

## Related Patterns

-   **Extract Class / Move Method:** Natural follow-ups when extracted groups form cohesive responsibilities.
    
-   **Introduce Parameter Object / Value Object:** Reduce long parameter lists after extraction.
    
-   **Decompose Conditional / Replace Conditional with Polymorphism:** Once branches are isolated, elevate to strategies.
    
-   **Consolidate Duplicate Code:** Replace repeated fragments with the extracted method.
    
-   **Guard Clauses:** Use early returns to flatten the caller after extraction.

