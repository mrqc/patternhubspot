# Stub — Testing Pattern

## Pattern Name and Classification

-   **Name:** Stub
    
-   **Classification:** xUnit Test Double Pattern / State-based Testing Aid
    

## Intent

Provide a **minimal, canned-behavior substitute** for a collaborator so that a test can drive the SUT (System Under Test) down specific code paths and **assert state/output**, without verifying interactions or standing up real infrastructure.

## Also Known As

-   Test Stub
    
-   Canned Responder
    
-   Passive Double (in contrast to active “mocks”)
    

## Motivation (Forces)

-   **Determinism:** Real collaborators (DBs, HTTP APIs) add latency and nondeterminism.
    
-   **Focus:** Tests should assert **what** the SUT produces, not **how** it talks to collaborators.
    
-   **Cost:** Standing up infra just to return a simple value is wasteful.  
    Tensions:
    
-   **Fidelity vs. simplicity:** Too-simple stubs can hide integration problems.
    
-   **Scope creep:** Adding logic to a stub morphs it into a **fake**; be intentional.
    

## Applicability

Use stubs when:

-   The SUT needs **data** from a collaborator, but the actual behavior of that collaborator isn’t under test.
    
-   You want to **force branches** (e.g., collaborator returns null/error/special value).
    
-   You prefer **state/output assertions** over verifying message sequences.
    

Avoid or complement with other patterns when:

-   You must verify calls/arguments/order → **Mock** or **Spy**.
    
-   You need a working in-memory alternative with invariants → **Fake**.
    
-   You need cross-service compatibility checks → **Contract Testing**.
    
-   You want broad output regression protection → **Snapshot / Golden Master**.
    

## Structure

-   **Port/Interface** abstracts the collaborator.
    
-   **Stub Implementation** returns **pre-programmed values** (or throws) for given inputs.
    
-   **SUT** consumes the port and produces outputs that tests assert on.
    

```csharp
[Test] → constructs SUT with → [Stub]
                    SUT ──calls──► Stub (returns canned value)
                    │
                    └─ asserts on SUT’s returned value / state (not interactions)
```

## Participants

-   **SUT (System Under Test):** production code you’re validating.
    
-   **Port / Collaborator Interface:** contract used by the SUT.
    
-   **Stub:** minimal implementation returning canned responses.
    
-   **Test:** arranges the stub’s outputs and asserts on the SUT’s results.
    

## Collaboration

1.  Test **arranges** the stub to return specific data (or errors).
    
2.  SUT calls the port; the stub responds deterministically.
    
3.  Test **asserts state/output** from the SUT—no interaction verification.
    

## Consequences

**Benefits**

-   **Fast, deterministic** tests with minimal setup.
    
-   Encourages **port abstractions** and clean boundaries.
    
-   Ideal for **branch forcing** (success/error/edge conditions).
    

**Liabilities**

-   Can **mask integration bugs** (serialization, auth, SQL).
    
-   If it accrues behavior, it becomes a **fake** (harder to maintain).
    
-   Overuse may bias suites toward **unit-only** confidence; keep integration/E2E in balance.
    

## Implementation

### Guidelines

-   Keep stubs **dumb and explicit**: return fixed values keyed by inputs.
    
-   Provide **small knobs** to trigger branches (e.g., “next call throws”).
    
-   Don’t verify calls on stubs; if you need that, use a **mock** or **spy**.
    
-   Prefer **value objects** and **pure functions** around stubs to simplify assertions.
    
-   Pair with a few **integration tests** using real adapters.
    

### What to make configurable

-   **Return-by-key** (e.g., value per country/SKU).
    
-   **Default** when no key present (null/Optional/exception).
    
-   **One-shot failure** to drive error paths.
    

---

## Sample Code (Java 17, JUnit 5)

**Scenario:** `InvoiceService` calculates a total from a net amount using a `TaxService`.  
We stub `TaxService` to return controlled values (and to throw) so we can test **normal**, **boundary**, and **error** cases using **state-based assertions** only.

```java
// src/main/java/example/stub/InvoiceService.java
package example.stub;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Objects;

public class InvoiceService {
  public interface TaxService {
    /** Returns tax amount for the given country and net price. */
    BigDecimal taxFor(String countryCode, BigDecimal net);
  }

  private final TaxService taxService;

  public InvoiceService(TaxService taxService) {
    this.taxService = Objects.requireNonNull(taxService);
  }

  /** Total = net + tax, rounded HALF_UP to 2 decimals. */
  public BigDecimal total(String country, BigDecimal net) {
    Objects.requireNonNull(country); Objects.requireNonNull(net);
    if (net.signum() < 0) throw new IllegalArgumentException("negative net");
    BigDecimal tax = taxService.taxFor(country, net);
    return net.add(tax).setScale(2, RoundingMode.HALF_UP);
  }
}
```

```java
// src/test/java/example/stub/TaxServiceStub.java
package example.stub;

import java.math.BigDecimal;
import java.util.HashMap;
import java.util.Map;
import java.util.Objects;

/** Minimal STUB: canned responses keyed by (country, net rounding to cents). */
class TaxServiceStub implements InvoiceService.TaxService {
  private final Map<String, BigDecimal> byCountry = new HashMap<>();
  private boolean failNext = false;

  /** Configure fixed tax for a country. */
  TaxServiceStub withTax(String country, BigDecimal tax) {
    byCountry.put(Objects.requireNonNull(country), Objects.requireNonNull(tax));
    return this;
  }

  /** Next call throws to simulate upstream failure (one-shot). */
  TaxServiceStub failNextCall() { this.failNext = true; return this; }

  @Override
  public BigDecimal taxFor(String country, BigDecimal net) {
    if (failNext) { failNext = false; throw new RuntimeException("Tax service unavailable"); }
    BigDecimal tax = byCountry.get(country);
    if (tax == null) throw new IllegalArgumentException("Unknown country: " + country);
    return tax;
  }
}
```

```java
// src/test/java/example/stub/InvoiceServiceTest.java
package example.stub;

import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.*;

class InvoiceServiceTest {

  @Test
  void computes_total_with_canned_tax() {
    var stub = new TaxServiceStub().withTax("AT", new BigDecimal("2.00"));
    var svc = new InvoiceService(stub);

    var total = svc.total("AT", new BigDecimal("10.00"));

    assertEquals(new BigDecimal("12.00"), total);
  }

  @Test
  void boundary_rounding_half_up() {
    var stub = new TaxServiceStub().withTax("DE", new BigDecimal("0.01"));
    var svc = new InvoiceService(stub);

    // 0.00 + 0.01 → 0.01 (rounding happens on total; trivial here but illustrates control)
    assertEquals(new BigDecimal("0.01"), svc.total("DE", new BigDecimal("0.00")));
  }

  @Test
  void drives_error_path_when_stub_throws() {
    var stub = new TaxServiceStub().withTax("AT", new BigDecimal("2.00")).failNextCall();
    var svc = new InvoiceService(stub);

    var ex = assertThrows(RuntimeException.class, () -> svc.total("AT", new BigDecimal("10.00")));
    assertTrue(ex.getMessage().contains("unavailable"));
    // NOTE: no interaction verification — we assert on SUT behavior (exception) only.
  }

  @Test
  void unknown_country_is_rejected() {
    var stub = new TaxServiceStub(); // no config
    var svc = new InvoiceService(stub);
    assertThrows(IllegalArgumentException.class, () -> svc.total("XX", new BigDecimal("10.00")));
  }
}
```

**Why this is a stub (not a mock)**

-   It **returns predefined values** (or throws) to steer the SUT.
    
-   The tests **do not verify** that a method was called a certain number of times or with specific arguments—only the **outcome** is asserted.
    
-   There is **no behavior recording** beyond minimal configuration (no spying).
    

## Known Uses

-   Returning **fixture data** from repositories/clients in service/unit tests.
    
-   Forcing **error branches** (timeouts, 5xx) without full mocking frameworks.
    
-   Driving **edge conditions** (empty lists, nulls, thresholds) cheaply.
    
-   Stabilizing tests for **formatters/serializers** by supplying deterministic inputs.
    

## Related Patterns

-   **Dummy:** passed but never used; only to satisfy signatures.
    
-   **Stub (this pattern):** canned responses; no interaction checks.
    
-   **Fake:** working in-memory implementation honoring invariants (e.g., unique constraints).
    
-   **Mock:** programmable double with **interaction verification** (calls/args/order).
    
-   **Spy:** a test double that **records** calls while often delegating to real behavior.
    
-   **Contract Testing:** ensures consumer–provider compatibility; complements stub-based unit tests.
    
-   **Integration Test:** uses **real adapters**; validates mapping/config behaves for real.
    

---

## Implementation Tips

-   Keep stubs **local to tests** (test sources or test fixtures module).
    
-   Name by intent, e.g., `TaxServiceReturningFixedValuesStub`.
    
-   Prefer **immutable setup** per test; reset/instantiate anew to avoid leakage.
    
-   Avoid adding domain logic; if you need invariants, create a **fake** instead.
    
-   Combine with **parameterized tests** to sweep many inputs using the same stub.
    
-   Maintain a small library of **common stubs** (HTTP client stub, clock stub) for reuse.

