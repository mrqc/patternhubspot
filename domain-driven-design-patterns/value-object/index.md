# Value Object (Domain-Driven Design)

## Pattern Name and Classification

**Name:** Value Object  
**Classification:** DDD tactical building block (domain layer)

---

## Intent

Model a **concept defined solely by its attributes** and invariants—**no identity** and **no lifecycle**. Value Objects are **immutable**, **comparable by value**, and **side-effect free**, making domain logic safer, clearer, and easier to test.

---

## Also Known As

-   Immutable Object
    
-   Value Type
    
-   Data Value
    

---

## Motivation (Forces)

-   Many domain concepts are understood **by what they are** (value) rather than **which one** (identity): `Money`, `Email`, `DateRange`, `GeoPoint`.
    
-   **Immutability** reduces bugs (aliasing, thread-safety), simplifies reasoning, and enables safe reuse/caching.
    
-   **Equality by value** allows replacement and de-duplication (`Set<Money>`, `Map<Address, …>`).
    
-   Encapsulating **validation and invariants** at the type boundary avoids “stringly typed” code and scattered checks.
    
-   Keeps **Entities/Aggregates slim**, expressive, and intention-revealing.
    

Tensions to balance:

-   **Granularity:** Too coarse (God value) vs too fine (explosion of tiny types).
    
-   **Normalization:** Enforce canonical forms (case, timezone, units) without losing intent.
    
-   **Performance:** Object churn vs clarity; consider flyweight/caching only when measured.
    
-   **Persistence friction:** ORMs and serialization need mapping conventions.
    

---

## Applicability

Use a Value Object when:

-   The concept has **no meaningful identity** in your domain.
    
-   Instances are **interchangeable** if their attributes are equal.
    
-   You want **immutability and validation** baked into the type.
    
-   You need **safe composition** inside Entities, Domain Services, and other VOs.
    

Avoid or limit when:

-   You need to **track identity or lifecycle** over time → use an **Entity**.
    
-   The value must mutate **in place** for technical reasons (then prefer replacing with a new instance).
    
-   You’re modeling **large graphs** or persistence that strongly prefers identities—use a mix (Entity + VOs).
    

---

## Structure

-   **Value Object:** Immutable fields, constructor/Factory validates invariants; equality/hash based on fields.
    
-   **Normalization Policy:** Canonical representation (e.g., currency code uppercase, trimmed strings).
    
-   **Operations:** Pure functions returning **new** instances.
    
-   **Serialization/Mappings:** Optional `@Embeddable` (JPA) or DTO mappers; keep the VO domain-pure.
    

---

## Participants

-   **Value Object Type(s):** The types themselves (`Money`, `Email`).
    
-   **Entities/Aggregates:** Compose VOs for attributes and calculations.
    
-   **Factories/Builders (optional):** Provide intention-revealing creation and canonicalization.
    
-   **Repositories/DTOs:** Persist and transfer VOs without leaking infrastructure.
    

---

## Collaboration

1.  Application or domain code constructs a VO via **constructor/factory**.
    
2.  VO **validates** and **normalizes** inputs, ensuring invariants.
    
3.  VO participates in behaviors (**pure ops**); Entities **replace** old values with new instances.
    
4.  Persistence maps VO fields as columns/doc properties; serialization uses standard formats.
    

---

## Consequences

**Benefits**

-   **Correctness by construction:** Validation once, then trust the type.
    
-   **Immutability & thread-safety:** Fewer side effects; easier concurrency.
    
-   **Expressive code:** Method signatures encode meaning (`Email email` vs `String s`).
    
-   **Reusability & testing:** Small, deterministic, and easily unit-tested.
    

**Liabilities**

-   **Mapping overhead** with some ORMs/serializers.
    
-   **Over-fragmentation** if every primitive becomes a VO.
    
-   **Allocation cost** if created excessively in hot paths (optimize only with evidence).
    

---

## Implementation

**Guidelines**

-   Make **immutable**: `final` class or `record`, private fields, no setters.
    
-   Validate **in constructor/factory**; throw **domain-specific exceptions** when possible.
    
-   Implement **value equality**: `equals`/`hashCode` over significant fields; `compareTo` for ordered values.
    
-   Provide **pure operations** returning new instances; never mutate existing ones.
    
-   **Normalize** inputs (trim, lowercase/uppercase where appropriate, unit conversions).
    
-   Prefer **domain-rich methods** (`plus`, `within`, `overlaps`, `netOfTax`) over exposing raw primitives.
    
-   Keep VOs **framework-free**; map them in adapters (JPA `@Embeddable` as a pragmatic exception).
    
-   For money/measurements, include **unit/currency** and guard arithmetic.
    
-   For dates, prefer **timezone-safe** types (`Instant`, `LocalDate`) and clear semantics.
    

**Anti-patterns**

-   “Value Object” with an `id` field or mutable setters.
    
-   “Primitive obsession”: using `String`/`BigDecimal` everywhere instead of `Email`/`Money`.
    
-   Business rules leaking into controllers/repositories rather than into the VO.
    

---

## Sample Code (Java)

### 1) Core Value Objects

```java
// Money: currency-aware, immutable, value-equal
public final class Money implements Comparable<Money> {
    private final java.math.BigDecimal amount;
    private final String currency; // ISO-4217 (e.g., "EUR")

    public Money(java.math.BigDecimal amount, String currency) {
        if (amount == null || currency == null) throw new IllegalArgumentException("amount/currency required");
        if (amount.scale() > 2) throw new IllegalArgumentException("max 2 decimals");
        if (!currency.matches("^[A-Z]{3}$")) throw new IllegalArgumentException("ISO-4217 uppercase");
        this.amount = amount;
        this.currency = currency;
    }

    public static Money of(String amount, String currency) {
        return new Money(new java.math.BigDecimal(amount), currency.toUpperCase());
    }

    public java.math.BigDecimal amount() { return amount; }
    public String currency() { return currency; }

    public Money plus(Money other) { requireSameCurrency(other); return new Money(amount.add(other.amount), currency); }
    public Money minus(Money other) { requireSameCurrency(other); return new Money(amount.subtract(other.amount), currency); }
    public Money times(int factor)   { return new Money(amount.multiply(java.math.BigDecimal.valueOf(factor)), currency); }
    public boolean gte(Money other)  { requireSameCurrency(other); return amount.compareTo(other.amount) >= 0; }

    private void requireSameCurrency(Money other) {
        if (!currency.equals(other.currency)) throw new IllegalArgumentException("currency mismatch");
    }

    @Override public int compareTo(Money o) { requireSameCurrency(o); return amount.compareTo(o.amount); }
    @Override public boolean equals(Object o) {
        return (o instanceof Money m) && amount.compareTo(m.amount) == 0 && currency.equals(m.currency);
    }
    @Override public int hashCode() { return java.util.Objects.hash(amount.stripTrailingZeros(), currency); }
    @Override public String toString() { return amount + " " + currency; }
}
```

```java
// Email: normalized, validated, immutable
public final class Email {
    private final String value;

    private static final java.util.regex.Pattern RX =
            java.util.regex.Pattern.compile("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$");

    public Email(String value) {
        if (value == null) throw new IllegalArgumentException("email required");
        var v = value.trim().toLowerCase();
        if (!RX.matcher(v).matches()) throw new IllegalArgumentException("invalid email");
        this.value = v;
    }

    public String value() { return value; }

    @Override public boolean equals(Object o) { return (o instanceof Email e) && value.equals(e.value); }
    @Override public int hashCode() { return value.hashCode(); }
    @Override public String toString() { return value; }
}
```

```java
// DateRange: closed-open [start, end)
public final class DateRange {
    private final java.time.Instant startInclusive;
    private final java.time.Instant endExclusive;

    public DateRange(java.time.Instant startInclusive, java.time.Instant endExclusive) {
        if (startInclusive == null || endExclusive == null) throw new IllegalArgumentException("start/end required");
        if (!endExclusive.isAfter(startInclusive)) throw new IllegalArgumentException("end must be after start");
        this.startInclusive = startInclusive;
        this.endExclusive = endExclusive;
    }

    public java.time.Instant start() { return startInclusive; }
    public java.time.Instant end() { return endExclusive; }

    public boolean contains(java.time.Instant t) {
        return !t.isBefore(startInclusive) && t.isBefore(endExclusive);
    }

    public boolean overlaps(DateRange other) {
        return this.startInclusive.isBefore(other.endExclusive) && other.startInclusive.isBefore(this.endExclusive);
    }

    public DateRange shift(java.time.Duration d) {
        return new DateRange(startInclusive.plus(d), endExclusive.plus(d));
    }

    @Override public boolean equals(Object o) {
        return (o instanceof DateRange r) && startInclusive.equals(r.startInclusive) && endExclusive.equals(r.endExclusive);
    }
    @Override public int hashCode() { return java.util.Objects.hash(startInclusive, endExclusive); }
    @Override public String toString() { return "[" + startInclusive + "," + endExclusive + ")"; }
}
```

### 2) Example Usage inside an Entity

```java
public final class Customer { // Entity (has identity)
    private final String id;
    private String fullName;
    private Email email;            // Value Object
    private Money creditLimit;      // Value Object

    public Customer(String id, String fullName, Email email, Money creditLimit) {
        this.id = java.util.Objects.requireNonNull(id);
        renameTo(fullName);
        changeEmail(email);
        changeCreditLimit(creditLimit);
    }

    public void changeEmail(Email newEmail) { this.email = java.util.Objects.requireNonNull(newEmail); }
    public void renameTo(String name) {
        if (name == null || name.isBlank()) throw new IllegalArgumentException("name");
        this.fullName = name.trim();
    }
    public void changeCreditLimit(Money newLimit) {
        if (newLimit.amount().signum() < 0) throw new IllegalArgumentException("negative limit");
        this.creditLimit = newLimit;
    }

    public boolean canPurchase(Money amount) {
        return creditLimit.gte(amount);
    }
}
```

### 3) (Optional) Persistence Mapping (JPA `@Embeddable`)

> Pragmatic approach when you keep the domain model annotated. If you prefer clean architecture, map in an adapter layer.

```java
import jakarta.persistence.*;
import java.math.BigDecimal;

@Embeddable
public class MoneyEmbeddable {
    @Column(name = "amount", precision = 19, scale = 2) public BigDecimal amount;
    @Column(name = "currency", length = 3) public String currency;

    protected MoneyEmbeddable() {} // JPA
    public MoneyEmbeddable(Money vo) { this.amount = vo.amount(); this.currency = vo.currency(); }
    public Money toVo() { return new Money(amount, currency); }
}

@Entity @Table(name = "customer")
class CustomerJpa {
    @Id String id;
    String fullName;
    String email;
    @AttributeOverrides({
        @AttributeOverride(name = "amount", column = @Column(name = "credit_limit_amount")),
        @AttributeOverride(name = "currency", column = @Column(name = "credit_limit_currency"))
    })
    @Embedded MoneyEmbeddable creditLimit;
}
```

### 4) Collections and Value Semantics

```java
// Example: distinct currencies in a set
var s = new java.util.HashSet<Money>();
s.add(Money.of("10.00", "EUR"));
s.add(Money.of("10.000", "EUR"));   // equals after stripTrailingZeros() → considered same
s.add(Money.of("10.00", "USD"));
assert s.size() == 2;
```

---

## Known Uses

-   **Finance / Pricing:** `Money`, `TaxRate`, `ExchangeRate`, `IBAN`, `VatId`.
    
-   **Commerce:** `Sku`, `Quantity`, `Discount`, `Percentage`, `Address`.
    
-   **Identity:** `Email`, `PhoneNumber`, `UserName`, `TenantId`.
    
-   **Time/Geo:** `DateRange`, `BusinessHour`, `GeoPoint`, `Distance`.
    
-   **Compliance:** `DocumentNumber`, `CountryCode`, `LanguageCode`.
    

---

## Related Patterns

-   **Entity:** Use when identity/lifecycle matters; compose **Value Objects** inside.
    
-   **Aggregate:** Aggregates manage consistency; their attributes are typically VOs.
    
-   **Factory:** Encapsulates complex creation; returns VOs/Entities already valid.
    
-   **Domain Service:** Performs operations that don’t belong to a single Entity/VO.
    
-   **Repository:** Persists Entities; VOs are usually embedded/serialized within.
    
-   **Shared Kernel:** Common VOs (e.g., `Money`, `CustomerId`) can live in a jointly owned module across contexts.
    

---

