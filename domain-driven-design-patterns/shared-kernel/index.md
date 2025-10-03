# Shared Kernel (Domain-Driven Design)

## Pattern Name and Classification

**Name:** Shared Kernel  
**Classification:** DDD strategic Context-Mapping pattern (collaboration/integration through a jointly owned subset of the model)

---

## Intent

Define and co-own a **small, carefully curated subset** of the domain model—**types, rules, and contracts**—that multiple bounded contexts rely on. The Shared Kernel minimizes translation and drift where concepts are truly identical, while enforcing **joint ownership, versioning, and change discipline**.

---

## Also Known As

-   Common Subdomain Model

-   Joint Model Module

-   Co-owned Library


---

## Motivation (Forces)

-   Some concepts are **genuinely the same** across contexts (e.g., `Money`, `CustomerId`, policy enums, calendar rules).

-   Re-implementing them in each context yields **duplication, subtle incompatibilities, and bugs**.

-   Exchanging them via ad-hoc mappings or “copy-paste” drifts over time.

-   A **tiny, high-quality** shared module with joint ownership improves consistency and communication.


**Tensions to balance**

-   Keep the kernel **small and stable** vs. the temptation to dump everything into it.

-   **Coupling risk:** changes ripple across teams—governance, semantic versioning, and deprecation are mandatory.

-   **Ownership:** true co-ownership vs. one team de facto controlling the shared code.


---

## Applicability

Use a Shared Kernel when:

-   Two (or more) contexts share **immutable truths** (identifiers, value objects, units, universal policies).

-   **Exact semantic alignment** exists and must stay aligned (e.g., legal or accounting definitions).

-   Teams can commit to **joint governance**: code reviews across teams, semantic versioning, release notes, deprecation windows.


Avoid or limit when:

-   Concepts **diverge** semantically (similar name, different meaning) → prefer **Anti-Corruption Layer**.

-   You can publish an **Open Host Service + Published Language** instead (looser coupling).

-   The “kernel” would grow beyond a few core elements (“**Shared Big Ball of Mud**” risk).


---

## Structure

-   **Shared Kernel Module:** Versioned artifact (e.g., `shared-kernel-v1.x`), usually **domain-pure** (no framework).

-   **Context A / Context B:** Depend on the shared artifact; internal models stay private.

-   **Governance:** Joint ownership, semantic versioning, deprecation policy, changelog, and compatibility tests.


---

## Participants

-   **Kernel Maintainers (joint):** Representatives from each consuming context.

-   **Consumers (contexts):** Import and use kernel types; upgrade within policy windows.

-   **Release Manager / CI:** Enforces versioning, runs contract/compatibility tests.

-   **Architectural Decision Records (ADR):** Document scope and evolution rules.


---

## Collaboration

1.  Teams agree on **scope**: which types and semantics belong in the kernel.

2.  Kernel is **published** as a versioned artifact; contexts import it.

3.  Changes follow **joint review**; additive changes → minor version, breaking → major.

4.  Consumers upgrade on a **planned cadence**, aided by deprecation warnings and migration notes.

5.  Periodically **re-evaluate** scope; remove items that started to diverge.


---

## Consequences

**Benefits**

-   **Consistency:** One definition for truly shared concepts.

-   **Reduced translation:** Less mapping and fewer bugs across contexts.

-   **Communication:** Shared language improves cross-team clarity.

-   **Reuse quality:** High-quality, well-tested core types.


**Liabilities**

-   **Coupling:** Changes ripple; release coordination needed.

-   **Scope creep:** The kernel can bloat if governance slips.

-   **Power dynamics:** If one team dominates, others become “conformists” unwillingly.

-   **Hidden framework bleed:** Accidental imports of tech concerns (JPA, Spring) constrain other contexts.


---

## Implementation

**Guidelines**

-   **Keep it domain-pure:** Only deterministic code and simple utilities. Avoid framework annotations, I/O, persistence, HTTP, logging.

-   **Versioning:** Semantic versioning; **no breaking changes** in minor/patch. Use deprecation annotations + migration guides.

-   **Packaging:** Use **versioned namespace** (e.g., `com.acme.shared.v1`) to allow parallel major versions.

-   **Surface area:** Prefer **Value Objects**, **Identifiers**, tiny **policies/enums**, **domain exceptions**, and **lightweight interfaces** (e.g., `DomainEvent`).

-   **Binary compatibility:** Stable constructors, avoid setters; provide factory methods; avoid sealed hierarchies unless deliberate.

-   **Tests:** Golden tests (equals/hashCode, serialization, invariant checks) and **consumer contract tests** in CI.

-   **Governance:** Required cross-team code review, ADRs for breaking changes, upgrade playbooks, deprecation windows.


**Anti-patterns**

-   Putting **repositories, entities, controllers**, or **ORM annotations** into the kernel.

-   Kernel depending on **Spring/JPA/Jackson** (force tech choices on all). Prefer optional adapters in consumers.

-   Using the kernel as a dumping ground for **utils** not tied to shared domain semantics.


---

## Sample Code (Java)

### 1) Shared Kernel module (`shared-kernel`)

```java
// file: com/acme/shared/v1/Identifier.java
package com.acme.shared.v1;

import java.util.Objects;
import java.util.UUID;

/** Typed identity base; stable equals/hashCode and toString. */
public abstract class Identifier {
    private final String value;

    protected Identifier(String value) {
        if (value == null || value.isBlank()) throw new IllegalArgumentException("id required");
        this.value = value;
    }
    public String value() { return value; }

    @Override public boolean equals(Object o) {
        if (this == o) return true;
        if (o == null || o.getClass() != this.getClass()) return false;
        return value.equals(((Identifier) o).value);
    }
    @Override public int hashCode() { return Objects.hash(getClass(), value); }
    @Override public String toString() { return getClass().getSimpleName() + "(" + value + ")"; }

    protected static String newUuid() { return UUID.randomUUID().toString(); }
}
```

```java
// file: com/acme/shared/v1/CustomerId.java
package com.acme.shared.v1;

public final class CustomerId extends Identifier {
    private CustomerId(String value) { super(value); }
    public static CustomerId of(String value) { return new CustomerId(value); }
    public static CustomerId newId() { return new CustomerId(newUuid()); }
}
```

```java
// file: com/acme/shared/v1/Money.java
package com.acme.shared.v1;

import java.math.BigDecimal;
import java.util.Objects;

/** Immutable money with ISO currency; arithmetic guarded by currency equality. */
public final class Money implements Comparable<Money> {
    private final BigDecimal amount;
    private final String currency; // ISO-4217

    public Money(BigDecimal amount, String currency) {
        if (amount == null || currency == null) throw new IllegalArgumentException();
        if (amount.scale() > 2) throw new IllegalArgumentException("scale > 2");
        this.amount = amount;
        this.currency = currency;
    }
    public static Money of(String amount, String currency) { return new Money(new BigDecimal(amount), currency); }
    public BigDecimal amount() { return amount; }
    public String currency() { return currency; }

    public Money add(Money other) { requireSameCurrency(other); return new Money(amount.add(other.amount), currency); }
    public Money subtract(Money other) { requireSameCurrency(other); return new Money(amount.subtract(other.amount), currency); }
    public Money multiply(int factor) { return new Money(amount.multiply(BigDecimal.valueOf(factor)), currency); }
    public boolean gte(Money other) { requireSameCurrency(other); return amount.compareTo(other.amount) >= 0; }

    @Override public int compareTo(Money o) { requireSameCurrency(o); return amount.compareTo(o.amount); }
    @Override public boolean equals(Object o) { return (o instanceof Money m) && amount.equals(m.amount) && currency.equals(m.currency); }
    @Override public int hashCode() { return Objects.hash(amount, currency); }
    @Override public String toString() { return amount + " " + currency; }

    private void requireSameCurrency(Money other) {
        if (!currency.equals(other.currency)) throw new IllegalArgumentException("currency mismatch");
    }
}
```

```java
// file: com/acme/shared/v1/TimePeriod.java
package com.acme.shared.v1;

import java.time.Instant;
import java.util.Objects;

/** Closed-open interval [start, end) with validation. */
public final class TimePeriod {
    private final Instant startInclusive;
    private final Instant endExclusive;

    public TimePeriod(Instant startInclusive, Instant endExclusive) {
        if (startInclusive == null || endExclusive == null) throw new IllegalArgumentException();
        if (!endExclusive.isAfter(startInclusive)) throw new IllegalArgumentException("end must be after start");
        this.startInclusive = startInclusive;
        this.endExclusive = endExclusive;
    }
    public Instant start() { return startInclusive; }
    public Instant end() { return endExclusive; }
    public boolean contains(Instant t) { return !t.isBefore(startInclusive) && t.isBefore(endExclusive); }

    @Override public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof TimePeriod p)) return false;
        return startInclusive.equals(p.startInclusive) && endExclusive.equals(p.endExclusive);
    }
    @Override public int hashCode() { return Objects.hash(startInclusive, endExclusive); }
}
```

```java
// file: com/acme/shared/v1/DomainEvent.java
package com.acme.shared.v1;

import java.time.Instant;

/** Minimal event contract usable across contexts without transport/framework coupling. */
public interface DomainEvent {
    String eventType();      // e.g., "customer.registered"
    int version();           // schema version
    String aggregateId();    // source id
    Instant occurredAt();    // UTC
}
```

```java
// file: com/acme/shared/v1/annotations/DeprecatedSince.java
package com.acme.shared.v1.annotations;

import java.lang.annotation.*;

/** Marks API elements slated for removal in the next major version. */
@Documented @Retention(RetentionPolicy.SOURCE) @Target({ElementType.TYPE, ElementType.METHOD, ElementType.CONSTRUCTOR, ElementType.FIELD})
public @interface DeprecatedSince {
    String value();          // e.g., "1.7"
    String replacement() default "";
}
```

> The kernel has **no** Spring/JPA/Jackson dependencies. Consumers can add adapters if needed.

---

### 2) Usage in two bounded contexts (compile-time sharing, runtime independence)

```java
// orders-context module
package com.acme.orders.domain;

import com.acme.shared.v1.CustomerId;
import com.acme.shared.v1.Money;

public final class OrderLine {
    private final String sku;
    private final int quantity;
    private final Money unitPrice;

    public OrderLine(String sku, int quantity, Money unitPrice) {
        if (quantity <= 0) throw new IllegalArgumentException("qty>0");
        this.sku = sku; this.quantity = quantity; this.unitPrice = unitPrice;
    }
    public Money lineTotal() { return unitPrice.multiply(quantity); }
}

public final class Order {
    private final String id;
    private final CustomerId customerId;
    private Money total;

    public Order(String id, CustomerId customerId) {
        this.id = id; this.customerId = customerId; this.total = new Money(java.math.BigDecimal.ZERO, "EUR");
    }

    public void addLine(OrderLine l) { this.total = this.total.add(l.lineTotal()); }
    public Money total() { return total; }
}
```

```java
// billing-context module
package com.acme.billing.domain;

import com.acme.shared.v1.CustomerId;
import com.acme.shared.v1.Money;

public final class Invoice {
    private final String invoiceNo;
    private final CustomerId customerId;
    private final Money amount;

    public Invoice(String invoiceNo, CustomerId customerId, Money amount) {
        this.invoiceNo = invoiceNo; this.customerId = customerId; this.amount = amount;
    }
    public Money amount() { return amount; }
}
```

**Notes**

-   Both contexts import **the same `Money` and `CustomerId`** semantics—no mapping layer needed.

-   Runtime coupling is **only through compiled types**, not shared databases, not shared frameworks.


---

### 3) Governance example (semantic versioning & deprecation)

```java
// file in kernel: com/acme/shared/v1/Money.java (adding a method without breaking)
    /** @since 1.6 */
    public boolean isPositive() { return amount.signum() > 0; }

// deprecate with migration hint
import com.acme.shared.v1.annotations.DeprecatedSince;

    @Deprecated
    @DeprecatedSince(value = "1.7", replacement = "isPositive")
    public boolean gtZero() { return isPositive(); }
```

**Release policy (informal outline)**

-   **Additive** changes → minor version (`1.5` → `1.6`).

-   **Breaking** changes → new **major** + new package root (`com.acme.shared.v2`) to allow side-by-side migration.

-   Publish **CHANGELOG** with rationale, migration steps, and deprecation removals per major.


---

## Known Uses

-   **Payments & Billing:** Shared `Money`, `Currency`, `TaxRate`, `CountryCode` across Checkout, Billing, and Accounting contexts.

-   **Identity:** Shared `UserId`, `TenantId`, `Role` enums used by IAM and downstream services.

-   **Scheduling:** Shared `TimePeriod`, `BusinessCalendar` across booking and pricing contexts.

-   **Compliance:** Shared `VatId`, `LegalEntityId`, `DocumentType` where legal definitions must match.


---

## Related Patterns

-   **Anti-Corruption Layer (ACL):** Use when concepts **look** similar but **aren’t** identical; do not force them into the kernel.

-   **Published Language & Open Host Service:** For **looser coupling** across org/team boundaries via explicit contracts.

-   **Conformist / Customer–Supplier:** Context-mapping relationships that affect who sets shared semantics.

-   **Separate Ways:** If the coordination cost outweighs benefit, don’t share—keep contexts independent.

-   **Shared Library (technical):** Not the same; Shared Kernel is **domain-semantic**, not a bag of utils/framework code.


---

## Sample “Ready-to-Use” Checklist

-    Kernel scope is **≤ 10–20** small types (start tiny).

-    **No framework dependencies**; pure Java.

-    **Versioned package** (e.g., `com.acme.shared.v1`).

-    **Semantic versioning** enforced in CI; deprecations carry replacements and dates.

-    **Cross-team code review** required for kernel changes.

-    **Contract tests** in consumers to catch accidental breaks.


---
