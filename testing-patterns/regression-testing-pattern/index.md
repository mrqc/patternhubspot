# Regression Testing — Testing Pattern

## Pattern Name and Classification

-   **Name:** Regression Testing
    
-   **Classification:** Maintenance & Verification Testing / Release Safety Net / Automation Pattern
    

## Intent

Detect **unintended behavior changes** after code, configuration, dependency, or infrastructure updates by **re-running representative tests** (and targeted additions for fixed bugs) so teams can **ship safely** with high confidence.

## Also Known As

-   Non-Regression Testing (NRT)
    
-   Re-test / Safety Net
    
-   Release/Smoke Regression (subset)
    
-   Bug-Fix Tests (per-defect additions to the suite)
    

## Motivation (Forces)

-   **Change is constant:** refactors, feature toggles, library upgrades, infra moves.
    
-   **Hidden coupling:** small changes ripple across layers (serialization, time zones, rounding, i18n).
    
-   **Confidence vs. cost:** broad suites increase confidence but consume time/compute.
    
-   **Reliability:** flaky tests erode trust; deterministic data/clocking is essential.  
    Regression testing balances **breadth** (cover critical paths) with **focus** (prioritize changed/risky areas).
    

## Applicability

Use regression testing when:

-   Merging PRs, cutting releases, performing hotfixes or refactors.
    
-   Upgrading **frameworks/SDKs/DBs/JDK** or toggling features.
    
-   Fixing a defect—add a **targeted test** to prevent re-occurrence.
    

Be cautious when:

-   Suites become **bloated or slow**; adopt **risk-based selection** and **test impact analysis (TIA)**.
    
-   Tests depend on **shared, mutable environments**; prefer ephemeral, isolated setups.
    

## Structure

-   **Regression Suite:** curated set across layers (unit → integration → E2E) with **tags**/“buckets” (smoke, critical, extended).
    
-   **Bug-Fix Tests:** one test per defect reproducing the issue and asserting the fix.
    
-   **Provisioner:** ephemeral infra for integration/system tests (containers/emulators).
    
-   **Selector/Prioritizer:** TIA/past-failure data to pick and order tests.
    
-   **Pipeline:** CI/CD stages (pre-merge fast smoke, pre-release full regression).
    
-   **Artifacts:** reports, logs, diffs, screenshots.
    

```css
[Change] → [Selector/TIA] → [Run: Smoke/Critical] → pass? → [Run: Extended/Full]
                                   │                              │
                              [Bug-fix tests]               [Artifacts & Reports]
```

## Participants

-   **Developers/QA** — write/curate tests, triage failures.
    
-   **CI Orchestrator** — runs buckets with caching/parallelism.
    
-   **Provisioner** — Testcontainers/Docker/k8s namespaces.
    
-   **Observability** — logs/traces/snapshots for fast diagnosis.
    
-   **Test Data Layer** — factories/fixtures, golden files.
    

## Collaboration

1.  A change lands (code/config/deps).
    
2.  **Selector** chooses tests (changed files, critical journeys, last-failed first).
    
3.  Pipeline provisions required deps, seeds data, **fixes clocks**, and runs suites.
    
4.  Failures yield **actionable artifacts**; fixes add/adjust tests (especially **bug-fix tests**).
    
5.  On green, promote build; on red, block and triage.
    

## Consequences

**Benefits**

-   Prevents **bug re-introductions** and side-effect regressions.
    
-   Builds **confidence** to refactor and upgrade dependencies.
    
-   Documents **fixed defects** via executable examples.
    

**Liabilities**

-   Suite **bloat** and **runtime** if unmanaged.
    
-   **Flakiness** from shared envs or nondeterminism.
    
-   **False confidence** if tests assert too little (pair with **mutation testing**).
    

## Implementation

### Practices

-   **Tagging & tiers:** `@Tag("smoke")`, `@Tag("regression")`, `@Tag("e2e")`; run smart subsets in PRs, full pre-release.
    
-   **Determinism:** fake clock, fixed RNG seeds, canonicalized snapshots; avoid sleeps → wait on conditions.
    
-   **Per-defect tests:** add a test that reproduces the bug and asserts the fix; name with an issue ID.
    
-   **Infrastructure isolation:** ephemeral DBs/brokers/files via Testcontainers/LocalStack.
    
-   **Prioritization:** order by risk, coverage, and past failures; apply **test impact analysis**.
    
-   **Flake management:** quarantine & deflake; fail builds on new flakiness.
    
-   **Dashboards:** time-to-green, slowest tests, failure clusters.
    

### What to include

-   **Critical user journeys** (checkout, auth).
    
-   **Cross-cutting concerns** (i18n, rounding, time zones, permissions).
    
-   **Known-bad edges** (boundaries, leap years, DST changes).
    
-   **Bug-fix cases** captured permanently.
    

---

## Sample Code (Java 17, JUnit 5)

A tiny commerce service where prior regressions occurred:

1.  **BUG-1234:** Free shipping threshold must be **inclusive** (`>=`), not `>`.
    
2.  **BUG-2288:** Prices must round **HALF\_UP** to two decimals (midpoint rounding).
    
3.  **BUG-3091:** Voucher codes are **case-insensitive**.
    

We add **tagged regression tests** that lock behavior. These live alongside broader tests and can be selected in CI with `-Dgroups=regression` (Surefire) or JUnit tags.

```java
// src/main/java/example/CommerceService.java
package example;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Locale;
import java.util.Objects;

public class CommerceService {

  /** Free shipping when total >= threshold (inclusive). */
  public boolean freeShipping(BigDecimal total, BigDecimal threshold) {
    Objects.requireNonNull(total); Objects.requireNonNull(threshold);
    if (total.signum() < 0 || threshold.signum() < 0) throw new IllegalArgumentException("negative");
    // Fix for BUG-1234: inclusive comparison
    return total.compareTo(threshold) >= 0;
  }

  /** Final price after discount then VAT; round HALF_UP to 2 decimals (BUG-2288). */
  public BigDecimal finalPrice(BigDecimal net, int discountPercent, int vatPercent) {
    Objects.requireNonNull(net);
    if (net.signum() < 0) throw new IllegalArgumentException("negative");
    if (discountPercent < 0 || discountPercent > 100) throw new IllegalArgumentException("discount 0..100");
    if (vatPercent < 0 || vatPercent > 100) throw new IllegalArgumentException("vat 0..100");

    BigDecimal discounted = net.multiply(BigDecimal.valueOf(100 - discountPercent).movePointLeft(2));
    BigDecimal withVat = discounted.multiply(BigDecimal.valueOf(100 + vatPercent).movePointLeft(2));
    return withVat.setScale(2, RoundingMode.HALF_UP);
  }

  /** Apply 10% voucher SAVE10 (case-insensitive); unknown codes are ignored (BUG-3091). */
  public BigDecimal applyVoucher(BigDecimal price, String code) {
    Objects.requireNonNull(price);
    if (code != null && "SAVE10".equalsIgnoreCase(code.trim())) {
      return price.multiply(new BigDecimal("0.90")).setScale(2, RoundingMode.HALF_UP);
    }
    return price.setScale(2, RoundingMode.HALF_UP);
  }
}
```

```java
// src/test/java/example/CommerceServiceRegressionTest.java
package example;

import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

/**
 * Regression tests: each method documents a previously observed defect.
 * Use `@Tag("regression")` to run these as a focused safety net in CI.
 */
@Tag("regression")
class CommerceServiceRegressionTest {

  CommerceService svc = new CommerceService();

  @Test
  void bug_1234_free_shipping_is_inclusive_at_threshold() {
    // Previously '>' excluded boundary; must be inclusive (>=)
    assertTrue(svc.freeShipping(new BigDecimal("100.00"), new BigDecimal("100.00")));
    assertFalse(svc.freeShipping(new BigDecimal("99.99"), new BigDecimal("100.00")));
  }

  @Test
  void bug_2288_half_up_rounding_on_midpoints() {
    // Midpoint: 10.005 with no VAT/discount must round to 10.01 (HALF_UP)
    assertEquals(new BigDecimal("10.01"),
        svc.finalPrice(new BigDecimal("10.005"), 0, 0));
    // With VAT and discount, still HALF_UP after all math
    assertEquals(new BigDecimal("10.79"),
        svc.finalPrice(new BigDecimal("9.99"), 0, 8)); // 9.99 * 1.08 = 10.7892 → 10.79
  }

  @Test
  void bug_3091_voucher_codes_are_case_insensitive_and_trimmed() {
    assertEquals(new BigDecimal("9.00"),
        svc.applyVoucher(new BigDecimal("10.00"), "save10"));
    assertEquals(new BigDecimal("9.00"),
        svc.applyVoucher(new BigDecimal("10.00"), "  SaVe10  "));
    // Unknown codes leave price unchanged
    assertEquals(new BigDecimal("10.00"),
        svc.applyVoucher(new BigDecimal("10.00"), "BOGUS"));
  }
}
```

**How to run only regression tests in Maven (JUnit 5 tags)**

```xml
<!-- pom.xml -->
<build>
  <plugins>
    <plugin>
      <groupId>org.apache.maven.plugins</groupId>
      <artifactId>maven-surefire-plugin</artifactId>
      <version>3.2.5</version>
      <configuration>
        <groups>regression</groups> <!-- run only @Tag("regression") -->
      </configuration>
    </plugin>
  </plugins>
</build>
```

Run full suite (no tag filter) in nightly builds; keep **smoke+regression** for PRs.

## Known Uses

-   **Release gates** in CI/CD: smoke (minutes) then extended regression (tens of minutes).
    
-   **Bug-fix hardening:** each resolved ticket adds a dedicated regression test.
    
-   **Library/framework upgrades:** targeted regression buckets for serialization, security, and persistence.
    
-   **Refactor shields:** lock behavior with golden masters + unit/integration tests before large refactors.
    

## Related Patterns

-   **Golden Master / Snapshot Testing:** freeze observable outputs to detect diffs.
    
-   **Contract Testing:** ensures cross-service compatibility; part of regression safety nets.
    
-   **Integration Testing:** verifies real adapters (DB/HTTP); many regression tests live here.
    
-   **End-to-End Testing:** validates critical journeys; a thin but high-value regression subset.
    
-   **Mutation Testing:** measures test **strength** so regression suites catch meaningful changes.
    
-   **Data-Driven Testing:** sweep many inputs to prevent regressions across variants.
    
-   **Mocking / Fakes:** help create deterministic, fast regression tests at unit/service level.
    

---

## Implementation Tips

-   Keep suites **lean & layered**: fast **smoke+critical** on PR, **full regression** pre-release, **extended** nightly.
    
-   Add a **test per bug** with the ticket ID in the name and commit message; never delete without rationale.
    
-   Make tests **hermetic**: fixed clocks, seeded RNGs, isolated data stores.
    
-   Use **Testcontainers**/emulators for infra-dependent regressions; avoid shared envs.
    
-   Track and **deflake**: quarantine flaky tests, fix root causes, and prevent flake debt.
    
-   Pair with **coverage & mutation** metrics to avoid false confidence from shallow assertions.
    
-   Regularly **prune/optimize**: merge redundant tests, parallelize slow ones, and monitor runtime trends.

