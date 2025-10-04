# Data-Driven Testing — Testing Pattern

## Pattern Name and Classification

-   **Name:** Data-Driven Testing (DDT)
    
-   **Classification:** Automated Testing Pattern / Parameterized & Fixture-Externalized Tests
    

## Intent

Separate **test logic** from **test data** so the same test procedure can be executed repeatedly against **multiple datasets** (positive, negative, edge cases). This increases coverage, reduces duplication, and makes it easy to add scenarios by editing data rather than code.

## Also Known As

-   Table-Driven Tests
    
-   Parameterized Tests
    
-   Example-Based Testing (with external fixtures)
    

## Motivation (Forces)

-   **Coverage vs. effort:** many permutations (locales, currencies, formats) are tedious to encode as individual tests.
    
-   **Change frequency:** business rules or catalogs change more often than the test algorithm; data-only updates are cheaper.
    
-   **Readability:** domain experts can contribute examples in **CSV/JSON** without Java changes.
    
-   **Repeatability:** reproduce production bugs by appending rows to datasets.  
    Tensions: keeping data **valid and versioned**, avoiding **brittle overspecification**, keeping suites **fast** with large datasets.
    

## Applicability

Use DDT when:

-   The **procedure is stable** but inputs vary widely.
    
-   You need to **sweep many boundary cases** (min/max, null/empty, locale variants).
    
-   Test data can be maintained **outside code** (files, spreadsheets, DB snapshots).
    

Be careful when:

-   The logic under test is highly stateful or interactive (scenarios may need orchestration, not just rows).
    
-   Datasets are huge → consider **sampling** or **stratification** to keep runtime acceptable.
    

## Structure

-   **Test Procedure:** reusable test body that accepts parameters.
    
-   **Data Source:** CSV/JSON/Excel, database query, API, or generated data.
    
-   **Data Loader/Mapper:** converts raw data rows to typed parameters/DTOs.
    
-   **Runner/Framework Support:** parameterized test runner, dynamic tests, or data providers.
    
-   **Reporting:** includes which **row** failed (row id, case name) for quick diagnosis.
    

```pgsql
+----------------+      +-------------+      +------------------+
| Test Procedure |  <-- | Data Loader |  <-- | Data Source(s)   |
| (assertions)   |      | + Mapping   |      | CSV, JSON, DB    |
+----------------+      +-------------+      +------------------+
          ^                      |
          +---- Framework executes for each row (parameterization)
```

## Participants

-   **Test Author** — writes the reusable procedure and mapping rules.
    
-   **Data Curator** — maintains datasets (often QA/analyst/domain expert).
    
-   **Data Source** — files or queries containing inputs + expected outcomes.
    
-   **Test Runner** — JUnit/TestNG engine invoking the procedure per row.
    
-   **SUT (System Under Test)** — code being exercised (pure function or service).
    

## Collaboration

1.  Runner enumerates rows from **data source(s)**.
    
2.  For each row, loader maps fields → **typed parameters**.
    
3.  The test procedure executes SUT and **asserts** expectations.
    
4.  Failures are reported with **row identifiers** for fast triage.
    

## Consequences

**Benefits**

-   High **coverage** with little code duplication.
    
-   **Editable** by non-developers (data-only PRs).
    
-   Easy **regression capture**: add a row reproducing the bug.
    
-   Encourages **boundary-focused** thinking.
    

**Liabilities**

-   Poorly validated data → **false negatives/positives**.
    
-   Large datasets can **slow** builds; needs sharding/caching.
    
-   Risk of **fixture rot** if data stops reflecting production reality.
    
-   Logic hidden in data transformations can reduce **test clarity**.
    

## Implementation

### Design Guidelines

-   Keep test procedures **pure and small**; move IO/mocking to setup.
    
-   Give each row a **caseId / description**; include it in assertion messages.
    
-   Validate datasets with a **schema** (headers, types, required columns).
    
-   Mix **broad CSV sweeps** with a few **readable unit tests** for intent.
    
-   Separate **golden data** (expected outputs) from **input-only** data when outputs are computed.
    
-   For performance, support **subset runs** (tags, filters) and **parallelization**.
    
-   Version datasets alongside code; treat as **first-class artifacts**.
    
-   Complement with **property-based testing** for randomized exploration.
    

### Typical Data Sources

-   **CSV/TSV** for tabular cases.
    
-   **JSON** for hierarchical inputs (APIs).
    
-   **Database fixtures** (readonly queries/snapshots).
    
-   **Generated** (combinatorial or property-based).
    

---

## Sample Code (Java 17, JUnit 5)

**Scenario:** verify a VAT calculator for multiple countries and amounts.  
We’ll show:

1.  `@CsvFileSource` reading external data,
    
2.  `@MethodSource` for programmatic cases,
    
3.  Clear failure messages using a **caseId** column.
    

> Directory layout (resources live on the test classpath):

```bash
src/
 └─ test/
    ├─ java/
    │   ├─ example/VatCalculator.java
    │   └─ example/VatCalculatorTest.java
    └─ resources/
        └─ datasets/vat_cases.csv
```

### `VatCalculator.java` (SUT)

```java
package example;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Map;

public class VatCalculator {
  // Simplified example rates (illustrative only)
  private static final Map<String, BigDecimal> RATES = Map.of(
      "AT", new BigDecimal("0.20"),  // Austria
      "DE", new BigDecimal("0.19"),
      "FR", new BigDecimal("0.20"),
      "GB", new BigDecimal("0.20"),
      "CH", new BigDecimal("0.077")
  );

  public BigDecimal vatFor(String country, BigDecimal netAmount) {
    if (country == null || netAmount == null) throw new IllegalArgumentException("null");
    if (netAmount.signum() < 0) throw new IllegalArgumentException("negative amount");
    BigDecimal rate = RATES.get(country);
    if (rate == null) throw new IllegalArgumentException("unknown country: " + country);
    // Financial rounding to 2 decimals
    return netAmount.multiply(rate).setScale(2, RoundingMode.HALF_UP);
  }

  public BigDecimal grossFor(String country, BigDecimal netAmount) {
    return netAmount.add(vatFor(country, netAmount));
  }
}
```

### `vat_cases.csv` (dataset in `src/test/resources/datasets/`)

```csv
# caseId, country, net, expectedVat, expectedGross
simple_at_10,AT,10.00,2.00,12.00
edge_zero,AT,0.00,0.00,0.00
rounding_ch,CH,10.00,0.77,10.77
de_large,DE,1234.56,234.57,1469.13
fr_round,FR,19.99,4.00,23.99
gb_penny,GB,0.01,0.00,0.01
```

### `VatCalculatorTest.java` (JUnit 5)

```java
package example;

import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.params.*;
import org.junit.jupiter.params.provider.*;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.stream.*;

/**
 * Data-Driven tests for VatCalculator.
 */
public class VatCalculatorTest {

  private final VatCalculator calc = new VatCalculator();

  // 1) CSV file source: clean separation of data and logic
  @ParameterizedTest(name = "[{index}] {0} country={1} net={2}")
  @CsvFileSource(resources = "/datasets/vat_cases.csv", numLinesToSkip = 1)
  void vat_cases_from_csv(String caseId, String country, String net, String expectedVat, String expectedGross) {
    BigDecimal netAmt = new BigDecimal(net);
    BigDecimal vat = calc.vatFor(country, netAmt);
    BigDecimal gross = calc.grossFor(country, netAmt);

    assertEquals(new BigDecimal(expectedVat), vat, () -> "VAT mismatch for " + caseId);
    assertEquals(new BigDecimal(expectedGross), gross, () -> "Gross mismatch for " + caseId);
  }

  // 2) Method source: generate additional boundary cases programmatically
  static Stream<Arguments> boundaryCases() {
    return Stream.of(
        Arguments.of("min_unit_at", "AT", "0.01", "0.00", "0.01"),
        Arguments.of("big_amount_de", "DE", "1000000.00", "190000.00", "1190000.00")
    );
  }

  @ParameterizedTest(name = "[{index}] {0}")
  @MethodSource("boundaryCases")
  void vat_boundary_cases(String caseId, String country, String net, String expectedVat, String expectedGross) {
    BigDecimal netAmt = new BigDecimal(net);
    assertEquals(new BigDecimal(expectedVat), calc.vatFor(country, netAmt), () -> "VAT mismatch for " + caseId);
    assertEquals(new BigDecimal(expectedGross), calc.grossFor(country, netAmt), () -> "Gross mismatch for " + caseId);
  }

  // 3) Negative data: invalid rows (kept inline for readability)
  @ParameterizedTest(name = "invalid input #{index}: country={0}, net={1}")
  @CsvSource({
      "ZZ, 10.00",    // unknown country
      "AT, -1.00",    // negative amount
      "'',  5.00"     // empty country
  })
  void invalid_inputs_throw(String country, String net) {
    BigDecimal netAmt = new BigDecimal(net);
    assertThrows(IllegalArgumentException.class, () -> calc.vatFor(country, netAmt));
  }

  // 4) (Optional) Validate dataset headers quickly to avoid silent drift
  @Test
  void dataset_has_expected_headers() throws Exception {
    var uri = Objects.requireNonNull(getClass().getResource("/datasets/vat_cases.csv")).toURI();
    var first = Files.readAllLines(Path.of(uri), StandardCharsets.UTF_8).get(0).trim();
    assertTrue(first.startsWith("# caseId, country, net, expectedVat, expectedGross"),
        "CSV header changed; update loader/test if intentional.");
  }
}
```

**Why this illustrates DDT**

-   The **procedure** (compute VAT, assert) is constant; **data** changes.

-   Datasets are **external** (CSV) and **programmatic** (`@MethodSource`) for special edges.

-   Failures cite a **caseId** for quick triage.

-   A lightweight **header check** guards against accidental CSV mutations.


> Tooling equivalents: JUnit 5 `@ParameterizedTest`, TestNG `@DataProvider`, Spock `where:` tables, Cucumber `Examples`, property-based generators (jqwik/QuickTheories).

## Known Uses

-   **Pricing/Tax/Discount engines** with many locale rules.

-   **ETL/Validation pipelines** (many malformed vs. valid inputs).

-   **API compatibility** across versions/locales (same contract, varied fixtures).

-   **Search/relevance**: query–expected top-K datasets.

-   **Format converters/parsers**: dozens of edge-case strings (dates, numbers, encodings).


## Related Patterns

-   **Parameterized Tests** — framework feature often used to implement DDT.

-   **Property-Based Testing** — generates data stochastically to complement curated tables.

-   **Golden Master / Snapshot Testing** — compare full outputs against stored baselines.

-   **Contract Testing** — verifies **interfaces**; can use DDT to cover many contract examples.

-   **Combinatorial / Pairwise Testing** — systematic selection of parameter combinations.


---

## Implementation Tips

-   Keep datasets **small but representative**; use **stratified sampling** for large spaces.

-   Include **boundary & negative** rows; label with **caseId** and **category** (e.g., `edge`, `locale`, `bugfix-1234`).

-   Validate data with a **schema** (header + type checks); fail fast if malformed.

-   Track dataset **lineage** (source, date, environment snapshot).

-   Parallelize parameterized tests and **shard** long-running suites in CI.

-   When outputs are large, store **expected hashes** or key assertions rather than entire payloads.

-   Make it easy for non-devs to contribute: CSV lints, pre-commit validation, and docs.
