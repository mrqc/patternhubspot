# Mutation Testing — Testing Pattern

## Pattern Name and Classification

-   **Name:** Mutation Testing
    
-   **Classification:** Test Quality Assessment / Fault Injection / Meta-Testing Pattern
    

## Intent

Assess the **effectiveness of your tests** by introducing small, systematic **code mutations** (“mutants”) and checking whether the test suite **fails**. If a mutant is detected (tests fail), it’s **killed**; if tests still pass, it **survives**, revealing **gaps** in assertions, coverage, or scenario design.

## Also Known As

-   Mutant Testing
    
-   Fault Injection for Tests
    
-   PIT / PITest (popular JVM tool)
    

## Motivation (Forces)

-   **Coverage is not enough:** 100% line coverage can still miss bugs if assertions are weak.
    
-   **Specification pressure:** Good tests should fail when behavior changes meaningfully.
    
-   **Refactoring safety:** Before refactors, ensure tests would catch accidental behavior drift.
    
-   **Signal vs. cost:** Mutation testing is compute-intensive; you want high signal with manageable runtime.
    

## Applicability

Use mutation testing when:

-   You want a **quantitative measure** of test quality beyond coverage.
    
-   You are working on **business-critical** modules (pricing, auth, money flows).
    
-   You suspect **weak assertions** or “happy-path only” tests.
    

Be cautious when:

-   Build time budgets are strict (large codebases).
    
-   Code has many **side effects** or uses non-determinism (flaky tests → noise).
    
-   There are many **equivalent mutants** (semantic no-ops) that tools cannot detect automatically.
    

## Structure

-   **Mutator Set:** Operators like *negate conditionals*, *replace arithmetic*, *return default*, *remove calls*.
    
-   **Mutation Engine:** Applies operators to bytecode/source to produce **mutants** (one change at a time).
    
-   **Test Runner:** Executes the existing tests per mutant.
    
-   **Oracle:** The test outcomes; failure = mutant **killed**, success = **survived**.
    
-   **Report:** Mutation score, surviving mutants, killed mutants, timeouts.
    

```scss
[Source/Bytecode] --(mutator)--> [Mutant #1]
                          └─run tests→ killed?
                 --(mutator)--> [Mutant #2]
                          └─run tests→ survived?  → highlight gap
...
Report: mutation score = killed / total
```

## Participants

-   **System Under Test (SUT)** — your production code.
    
-   **Test Suite** — existing unit/integration tests.
    
-   **Mutation Tool** — e.g., PIT for JVM, Stryker (JS), MutPy (Python).
    
-   **Developer/Reviewer** — inspects survivors, strengthens tests or marks equivalence.
    

## Collaboration

1.  Tool selects a class/method and a **mutation operator**.
    
2.  Produces a **single mutant** and runs the **relevant tests** (often via coverage-guided test picking).
    
3.  If any test fails → **kill**; else **survive** and report location + operator.
    
4.  Developer either **improves tests** (preferred) or **justifies/filters** an equivalent mutant.
    
5.  Repeat across mutants; summarize **mutation score**.
    

## Consequences

**Benefits**

-   Directly measures **assertion strength** (not just execution).
    
-   Uncovers **missing edge cases** and **over-mocking**.
    
-   Improves **refactoring confidence**.
    
-   Encourages **clear specifications** in tests.
    

**Liabilities**

-   **Runtime cost** (many test runs).
    
-   **Equivalent mutants** waste time to analyze.
    
-   Can reveal **brittle tests** (which is good) but adds triage work.
    
-   Requires **tooling discipline** (filters, thresholds, CI strategy).
    

## Implementation

### Practical Guidelines

-   **Scope selectively:** start with critical packages; exclude DTOs, configs, generated code.
    
-   **Budget runtime:** use **coverage data** to target only tests that hit a mutant; run with multiple threads.
    
-   **Stabilize tests:** eliminate flakiness (fake clocks, deterministic RNG).
    
-   **Treat survivors as TODOs:** add assertions or tests; if equivalent, add filters/exclusions with a note.
    
-   **Set thresholds:** e.g., mutation score ≥ 70% to fail CI on new/changed code.
    
-   **Use strong mutators** sparingly at first (e.g., “STRONGER” in PIT) and grow over time.
    
-   **Run in stages:** PRs run on changed modules; nightly runs full suite.
    

### Common Mutators (examples)

-   **Conditionals:** `>` ↔ `>=`, `==` ↔ `!=`, negate `if` guards.
    
-   **Math:** `+ - * / %` replacements; increment/decrement changes.
    
-   **Returns:** replace return with default/constant.
    
-   **Void methods:** remove calls (no-op).
    
-   **Negate conditionals / remove conditionals** entirely.
    
-   **Switch case** replacement/fallthrough.
    

---

## Sample Code (Java 17 + JUnit 5 + PIT)

### 1) Production code (SUT)

```java
// src/main/java/com/example/DiscountCalculator.java
package com.example;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Objects;

public class DiscountCalculator {

  /**
   * Apply a percentage discount to a positive price.
   * @param price   gross price >= 0
   * @param percent 0..100 (integer percent)
   * @return discounted price rounded HALF_UP to 2 decimals
   */
  public BigDecimal apply(BigDecimal price, int percent) {
    Objects.requireNonNull(price);
    if (price.signum() < 0) throw new IllegalArgumentException("negative price");
    if (percent < 0 || percent > 100) throw new IllegalArgumentException("percent 0..100");
    BigDecimal p = price.setScale(2, RoundingMode.HALF_UP);
    BigDecimal factor = BigDecimal.valueOf(100 - percent).movePointLeft(2); // (100 - p)/100
    return p.multiply(factor).setScale(2, RoundingMode.HALF_UP);
  }

  /** Free shipping if VIP and items total >= threshold. */
  public boolean freeShipping(boolean vip, BigDecimal itemsTotal, BigDecimal threshold) {
    Objects.requireNonNull(itemsTotal); Objects.requireNonNull(threshold);
    if (itemsTotal.signum() < 0) throw new IllegalArgumentException("negative total");
    return vip && itemsTotal.compareTo(threshold) >= 0;
  }
}
```

### 2) Tests (some intentionally weak at first)

```java
// src/test/java/com/example/DiscountCalculatorTest.java
package com.example;

import org.junit.jupiter.api.Test;
import java.math.BigDecimal;
import static org.junit.jupiter.api.Assertions.*;

class DiscountCalculatorTest {
  DiscountCalculator dc = new DiscountCalculator();

  @Test
  void apply_zero_percent_returns_same_price() {
    assertEquals(new BigDecimal("19.90"),
        dc.apply(new BigDecimal("19.90"), 0));
  }

  @Test
  void apply_full_discount_returns_zero() {
    assertEquals(new BigDecimal("0.00"),
        dc.apply(new BigDecimal("19.90"), 100));
  }

  @Test
  void rejects_invalid_percent() {
    assertThrows(IllegalArgumentException.class,
        () -> dc.apply(new BigDecimal("10.00"), -1));
    assertThrows(IllegalArgumentException.class,
        () -> dc.apply(new BigDecimal("10.00"), 101));
  }

  // Intentionally WEAK: doesn’t check rounding nuance or boundary on freeShipping
  @Test
  void free_shipping_for_vips_over_threshold() {
    assertTrue(dc.freeShipping(true, new BigDecimal("100.00"), new BigDecimal("100.00")));
    assertFalse(dc.freeShipping(false, new BigDecimal("100.00"), new BigDecimal("100.00")));
  }
}
```

**What will happen initially**

-   Mutator like “negate condition” on `freeShipping` may change `>=` to `>` → the weak test still passes for strictly over-threshold cases but might **let a mutant survive** at equality.
    
-   Arithmetic mutator on `factor` or return value could survive if we don’t test **rounding** or **midpoint** values.
    

### 3) Strengthen tests to **kill** likely mutants

```java
// src/test/java/com/example/DiscountCalculatorStrongTest.java
package com.example;

import org.junit.jupiter.api.Test;
import java.math.BigDecimal;
import static org.junit.jupiter.api.Assertions.*;

class DiscountCalculatorStrongTest {
  DiscountCalculator dc = new DiscountCalculator();

  @Test
  void rounding_half_up_is_enforced() {
    // 5% of 0.03 = 0.0015 → round HALF_UP at 2 decimals on the final price
    assertEquals(new BigDecimal("0.03"), dc.apply(new BigDecimal("0.03"), 0));
    assertEquals(new BigDecimal("0.03"), dc.apply(new BigDecimal("0.03"), 1)); // 0.03 * 0.99 = 0.0297 → 0.03
  }

  @Test
  void boundary_condition_on_free_shipping_includes_threshold() {
    assertTrue(dc.freeShipping(true, new BigDecimal("100.00"), new BigDecimal("100.00")));
    assertFalse(dc.freeShipping(true, new BigDecimal("99.99"), new BigDecimal("100.00")));
  }

  @Test
  void negative_price_is_rejected() {
    assertThrows(IllegalArgumentException.class,
        () -> dc.apply(new BigDecimal("-0.01"), 10));
  }
}
```

### 4) Configure PIT (Maven)

```xml
<!-- pom.xml -->
<build>
  <plugins>
    <plugin>
      <groupId>org.pitest</groupId>
      <artifactId>pitest-maven</artifactId>
      <version>1.15.8</version>
      <configuration>
        <targetClasses>
          <param>com.example.*</param>
        </targetClasses>
        <targetTests>
          <param>com.example.*</param>
        </targetTests>
        <!-- Start modest; grow mutator strength over time -->
        <mutators>
          <mutator>DEFAULTS</mutator>
        </mutators>
        <threads>4</threads>
        <outputFormats>
          <param>HTML</param>
          <param>XML</param>
        </outputFormats>
        <timestampedReports>false</timestampedReports>
        <!-- Optional: thresholds to fail the build -->
        <mutationThreshold>70</mutationThreshold>
        <coverageThreshold>70</coverageThreshold>
        <!-- Exclusions reduce noise -->
        <excludedClasses>
          <param>com.example.*Config*</param>
          <param>com.example.*Dto*</param>
        </excludedClasses>
      </configuration>
      <executions>
        <execution>
          <id>pit-report</id>
          <goals><goal>mutationCoverage</goal></goals>
        </execution>
      </executions>
    </plugin>
  </plugins>
</build>
```

**Run:**

```nginx
mvn -DskipTests=false org.pitest:pitest-maven:mutationCoverage
```

PIT will generate an HTML report (e.g., `target/pit-reports/index.html`) with **killed/survived mutants** and line highlights.

### 5) (Optional) Gradle (Kotlin DSL) snippet

```kotlin
plugins { id("info.solidsoft.pitest") version "1.15.0" }
pitest {
  pitestVersion.set("1.15.8")
  targetClasses.set(listOf("com.example.*"))
  mutators.set(listOf("DEFAULTS"))
  threads.set(4)
  mutationThreshold.set(70)
}
```

---

## Known Uses

-   **Financial calculations / pricing engines** (rounding, thresholds, tax).
    
-   **Input validation & auth** (boundary/negation mistakes).
    
-   **Serialization/formatting** logic where small changes can be harmful.
    
-   **Safety-critical code** (where tests must be demonstrably strong).
    

## Related Patterns

-   **Code Coverage** — measures execution, not assertion strength; mutation complements it.
    
-   **Property-Based Testing** — generates diverse inputs; mutation ensures assertions are meaningful.
    
-   **Golden Master** — protects overall output; mutation focuses on **assertion sensitivity**.
    
-   **Contract Testing** — checks cross-service compatibility; mutation tests the **consumer/provider tests** themselves.
    
-   **Integration & E2E Tests** — broader scope; mutation is usually applied to **unit/service** level for speed.
    

---

## Implementation Tips

-   Start **small and focused**: one module, DEFAULT mutators, critical classes.
    
-   **Stabilize** randomness/time (fake clock, fixed seeds) to prevent flaky survivors.
    
-   **Triaging survivors:** first improve tests; if a mutant is truly **equivalent**, document and exclude it.
    
-   Use **incremental runs** in CI (only changed modules) and **full runs nightly**.
    
-   Prefer **fewer, stronger assertions** over many brittle ones.
    
-   Watch for **over-mocking**: if interaction-heavy tests let state-mutating mutants survive, consider adding **state assertions** or using **fakes**.
    

With the above setup, your mutation score will become a **trustworthy signal** that tests actually *protect behavior*, not just execute lines.

