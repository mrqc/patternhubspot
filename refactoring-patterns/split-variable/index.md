# Split Variable — Refactoring Pattern

## Pattern Name and Classification

**Name:** Split Variable  
**Classification:** Refactoring Pattern (State Clarification / Readability & Correctness)

## Intent

Replace a **single variable that represents multiple concepts over time** (reassigned to different meanings) with **separate, well-named variables**—ideally `final`—so each variable has exactly **one responsibility** and a minimal scope.

## Also Known As

-   Single-Assignment Variables
    
-   One Variable, One Meaning
    
-   Eliminate Temporal Coupling in Locals
    

## Motivation (Forces)

-   **Temporal coupling:** A variable is reassigned to hold different concepts (e.g., first “circumference,” later “area”).
    
-   **Bugs from reuse:** Later code accidentally uses an earlier value (or vice versa).
    
-   **Readability:** Future readers must keep a timeline in their head to know what a variable “currently” means.
    
-   **Optimization temptation:** Reuse “to save memory” is pointless noise in modern languages and hurts clarity.
    
-   **Refactoring friction:** Mixed meanings block *Extract Method*, *Introduce Explaining Variable*, and testing.
    

## Applicability

Apply when:

-   A local variable is **assigned more than once** and those assignments **represent different concepts**.
    
-   A loop variable is reused as an **accumulator** or vice versa.
    
-   A method uses the same name for **input normalization** and later **computation results**.
    
-   A try block assigns to a variable and a catch/finally block **reuses it for another purpose**.
    

Avoid or postpone when:

-   Reassignments are truly **iterative updates of the same concept** (e.g., an accumulator inside a fold).
    
-   The variable’s meaning is stable and renaming suffices (use *Rename Variable*).
    
-   Extremely tight, performance-critical code where extra locals measurably hurt (rare; measure first).
    

## Structure

```cpp
Before:
double temp = 2 * PI * r;   // circumference
...
temp = PI * r * r;          // area (same variable, new meaning)

After:
final double circumference = 2 * PI * r;
...
final double area = PI * r * r;
```

## Participants

-   **Confused Local:** The original multi-purpose variable.
    
-   **Meaningful Locals:** New variables, each bound to one concept, preferably `final` and minimally scoped.
    
-   **Callers/Readers:** Benefit from explicit names and stable meanings.
    

## Collaboration

-   Each meaning is **named and isolated**, enabling further refactorings (e.g., extracting `area()` and `circumference()` queries).
    
-   Tests and reviewers reason about values **without tracking temporal state**.
    

## Consequences

**Benefits**

-   Eliminates a class of subtle bugs from **stale or overwritten values**.
    
-   Improves readability and intent; simplifies extraction and testing.
    
-   Encourages **single-assignment**, functional style and smaller scopes.
    

**Liabilities / Trade-offs**

-   Slight increase in the number of locals.
    
-   Overzealous splitting can add noise—use **good names and minimal scope**.
    

## Implementation

1.  **Identify distinct meanings** of the reassigned variable.
    
2.  **Introduce a new variable per meaning**; name by domain concept.
    
3.  **Make them `final`** where possible; **narrow scope** to the smallest block that uses them.
    
4.  **Replace each use** of the old variable with the appropriate new one.
    
5.  **Re-run tests**; then consider *Extract Method* or *Replace Temp with Query* for derived values.
    
6.  **Clean up loops**: if a variable serves as both index and accumulator, **separate** them (or use stream/fold).
    

---

## Sample Code (Java)

### 1) Business logic: totals vs. shipping (before → after)

**Before (one variable, multiple meanings)**

```java
public BigDecimal checkoutTotal(Order order) {
  BigDecimal value = order.items().stream()
      .map(li -> li.unitPrice().multiply(BigDecimal.valueOf(li.qty())))
      .reduce(BigDecimal.ZERO, BigDecimal::add); // value = subtotal

  if (order.hasCoupon()) {
    value = value.multiply(new BigDecimal("0.90")); // now value = discounted total
  }

  // Reusing the same variable for shipping cost (different concept!)
  value = order.weightKg().compareTo(new BigDecimal("5")) > 0
      ? new BigDecimal("12.00")
      : new BigDecimal("4.90"); // now value = shipping

  // Oops—what are we adding here?
  return order.subtotal() // stale API call; developer confusion starts
      .add(value);
}
```

**After (split variables, single meaning each)**

```java
public BigDecimal checkoutTotal(Order order) {
  final BigDecimal subtotal = order.items().stream()
      .map(li -> li.unitPrice().multiply(BigDecimal.valueOf(li.qty())))
      .reduce(BigDecimal.ZERO, BigDecimal::add);

  final BigDecimal discountedTotal = order.hasCoupon()
      ? subtotal.multiply(new BigDecimal("0.90"))
      : subtotal;

  final BigDecimal shipping = order.weightKg().compareTo(new BigDecimal("5")) > 0
      ? new BigDecimal("12.00")
      : new BigDecimal("4.90");

  return discountedTotal.add(shipping);
}
```

### 2) Geometry example (classic)

**Before**

```java
double temp = 2 * Math.PI * radius;  // circumference
log(temp);
temp = Math.PI * radius * radius;    // area
return temp;
```

**After**

```java
final double circumference = 2 * Math.PI * radius;
log(circumference);
final double area = Math.PI * radius * radius;
return area;
```

### 3) Loop index vs. accumulator

**Before**

```java
int i = 0;
for (i = 0; i < lines.size(); i++) {
  i += lines.get(i).cost(); // mixing index and accumulator!
}
return i;
```

**After**

```java
int totalCost = 0;
for (int idx = 0; idx < lines.size(); idx++) {
  totalCost += lines.get(idx).cost();
}
return totalCost;
```

### 4) With streams, temps often become queries (bonus synergy)

```java
public BigDecimal invoiceTotal(List<Line> lines) {
  final BigDecimal subtotal = lines.stream()
      .map(l -> l.price().multiply(BigDecimal.valueOf(l.qty())))
      .reduce(BigDecimal.ZERO, BigDecimal::add);

  final BigDecimal tax = subtotal.multiply(new BigDecimal("0.20"));
  return subtotal.add(tax);
}
```

---

## Known Uses

-   Financial computations where a “`result`” variable flips between **subtotal**, **discounted**, and **shipping**.
    
-   Parsing/validation code that reuses `str` for both **raw input** and **sanitized/normalized** form.
    
-   Algorithmic code reusing a single variable as **loop index** and **accumulator**.
    
-   Scientific/graphics computations where `t` stands for **time** then gets reused as **temporary**.
    

## Related Patterns

-   **Replace Temp with Query:** Turn derived values into side-effect-free methods.
    
-   **Introduce Explaining Variable:** Add a named local for a complex expression (when one meaning).
    
-   **Rename Variable:** If meaning is consistent but unclear.
    
-   **Extract Method:** After splitting, extract cohesive computations.
    
-   **Split Loop:** If a loop performs two different tasks, separate loops for clarity and correctness.
    
-   **Encapsulate Variable / Encapsulate Field:** When the “variable” is a field shared across methods; move and protect it.

