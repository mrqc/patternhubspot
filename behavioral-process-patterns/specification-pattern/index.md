# Specification — Behavioral / Process Pattern

## Pattern Name and Classification

**Specification** — *Behavioral / Process* (also used as a *Domain/Query* pattern) for expressing **business rules and selection criteria** as **composable objects** (predicates) that can be evaluated in-memory or translated into queries.

---

## Intent

Encapsulate a **business rule** (e.g., “Premium customer with unpaid invoices older than 30 days”) as a **first-class object** that can be **reused, combined (AND/OR/NOT), tested, and applied** consistently across the domain and persistence layers.

---

## Also Known As

-   **Predicate Object**

-   **Rule Object**

-   **Query Specification** (when focused on persistence translation)


---

## Motivation (Forces)

-   Rules appear in many places (validation, selection, authorization). Copy-pasting conditions causes **drift**.

-   You want **readable, testable** rules in the *ubiquitous language*.

-   Repositories need **declarative filters** that can be **composed** instead of exposing bespoke methods for each combination (`findByAAndBOrC…`).

-   Same rule should run **in-memory** (aggregates, domain services) and, when possible, be **translated** to DB queries.


**Tensions**

-   Bridging domain rules to the DB requires **translation** (e.g., JPA Criteria); not all rules are translatable.

-   Overusing tiny specs can make code noisy—prefer meaningful, **domain-level** specifications.


---

## Applicability

Use Specification when:

-   You have **rich selection rules** that evolve and combine.

-   The same rule is required in **multiple contexts** (validation, authorization, queries).

-   You need to **unit test** business rules in isolation.

-   Your repository must support **composable querying**.


Avoid when:

-   Rules are trivial or used once.

-   You cannot feasibly translate rules to persistence and only need DB-side filtering (then write targeted queries).


---

## Structure

```sql
Specification<T>
  ├─ isSatisfiedBy(T candidate): boolean (domain evaluation)
  ├─ toPredicate(Root<T>, CriteriaQuery<?>, CB): Predicate (optional DB translation)
Combinators:
  AndSpecification(left, right)
  OrSpecification(left, right)
  NotSpecification(inner)
```

---

## Participants

-   **Specification<T>** — interface for a rule; may offer **domain evaluation** and **query translation**.

-   **Concrete Specifications** — domain concepts (“Overdue”, “PremiumCustomer”).

-   **Combinators** — AND / OR / NOT specs to compose complex criteria.

-   **Repository** — accepts a specification to fetch entities that satisfy it.

-   **Aggregate/Service** — uses specs for decisions (e.g., canShip?).


---

## Collaboration

1.  Client builds a spec (or composes many).

2.  Domain code calls `isSatisfiedBy` for in-memory decisions.

3.  Repository receives the same spec and, if supported, calls `toPredicate` to build a DB query.

4.  One authoritative rule, two executions (memory or DB), same semantics.


---

## Consequences

**Benefits**

-   **Single source of truth** for rules; **reusability**; **composability**.

-   Clean repositories (no method explosion).

-   **Testable** rules with nominal domain fixtures.

-   Supports **authorization/validation** without leaking persistence concerns.


**Liabilities**

-   Dual execution paths (in-memory vs DB) must be kept **semantically aligned**.

-   Some rules (complex functions) are **not translatable** to SQL/Criteria cleanly.

-   Over-composition can reduce readability—prefer **intent-revealing** specs.


---

## Implementation (Key Points)

-   Provide a tiny SPI with `isSatisfiedBy` and **optional** JPA translation (`toPredicate`).

-   Offer static **combinators** (`and`, `or`, `not`).

-   Keep **domain language** in spec names (e.g., `OverdueInvoice`) rather than low-level fields.

-   When a rule can’t be translated to SQL, either **filter post-DB** or mark it **memory-only**.

-   Add **unit tests** per spec and a few **integration tests** for translation.


---

## Sample Code (Java 17) — Domain + JPA-friendly Specifications

> Example domain: `Customer` with `Orders` and `Invoices`.  
> We define specs like **PremiumCustomer**, **HasUnpaidInvoiceOlderThan** and compose them.

```java
// ===== Domain Model (simplified POJOs) =====
import java.time.LocalDate;
import java.util.List;

enum InvoiceStatus { PAID, UNPAID }

class Invoice {
  String id;
  LocalDate issuedOn;
  InvoiceStatus status;
  int amountCents;
}

class Order {
  String id;
  LocalDate placedOn;
  boolean shipped;
  int totalCents;
}

class Customer {
  String id;
  String tier; // "BASIC", "PREMIUM", ...
  LocalDate registeredOn;
  List<Order> orders;
  List<Invoice> invoices;

  boolean isPremium() { return "PREMIUM".equals(tier); }
}

// ===== Specification SPI =====
import jakarta.persistence.criteria.*;

@FunctionalInterface
interface Spec<T> {
  // Domain evaluation (in-memory)
  boolean isSatisfiedBy(T t);

  // Default JPA translation hook: return null if not supported
  default Predicate toPredicate(Root<T> root, CriteriaQuery<?> query, CriteriaBuilder cb) {
    throw new UnsupportedOperationException("No JPA translation for " + this.getClass().getSimpleName());
  }

  // Combinators
  default Spec<T> and(Spec<T> other) {
    var self = this;
    return new Spec<>() {
      @Override public boolean isSatisfiedBy(T t) { return self.isSatisfiedBy(t) && other.isSatisfiedBy(t); }
      @Override public Predicate toPredicate(Root<T> r, CriteriaQuery<?> q, CriteriaBuilder cb) {
        return cb.and(self.toPredicate(r, q, cb), other.toPredicate(r, q, cb));
      }
    };
  }
  default Spec<T> or(Spec<T> other) {
    var self = this;
    return new Spec<>() {
      @Override public boolean isSatisfiedBy(T t) { return self.isSatisfiedBy(t) || other.isSatisfiedBy(t); }
      @Override public Predicate toPredicate(Root<T> r, CriteriaQuery<?> q, CriteriaBuilder cb) {
        return cb.or(self.toPredicate(r, q, cb), other.toPredicate(r, q, cb));
      }
    };
  }
  static <T> Spec<T> not(Spec<T> inner) {
    return new Spec<>() {
      @Override public boolean isSatisfiedBy(T t) { return !inner.isSatisfiedBy(t); }
      @Override public Predicate toPredicate(Root<T> r, CriteriaQuery<?> q, CriteriaBuilder cb) {
        return cb.not(inner.toPredicate(r, q, cb));
      }
    };
  }
}

// ===== Concrete Specifications =====
final class PremiumCustomer implements Spec<Customer> {
  @Override public boolean isSatisfiedBy(Customer c) { return c != null && c.isPremium(); }
  @Override public Predicate toPredicate(Root<Customer> root, CriteriaQuery<?> q, CriteriaBuilder cb) {
    return cb.equal(root.get("tier"), "PREMIUM");
  }
}

final class RegisteredBefore implements Spec<Customer> {
  private final LocalDate date;
  RegisteredBefore(LocalDate date) { this.date = date; }
  @Override public boolean isSatisfiedBy(Customer c) { return c.registeredOn != null && c.registeredOn.isBefore(date); }
  @Override public Predicate toPredicate(Root<Customer> r, CriteriaQuery<?> q, CriteriaBuilder cb) {
    return cb.lessThan(r.get("registeredOn"), date);
  }
}

final class HasUnpaidInvoiceOlderThan implements Spec<Customer> {
  private final int days;
  HasUnpaidInvoiceOlderThan(int days) { this.days = days; }

  @Override public boolean isSatisfiedBy(Customer c) {
    if (c.invoices == null) return false;
    LocalDate cutoff = LocalDate.now().minusDays(days);
    return c.invoices.stream().anyMatch(inv -> inv.status == InvoiceStatus.UNPAID && inv.issuedOn.isBefore(cutoff));
  }

  @Override public Predicate toPredicate(Root<Customer> root, CriteriaQuery<?> query, CriteriaBuilder cb) {
    // Join invoices and check UNPAID & issuedOn < cutoff
    LocalDate cutoff = LocalDate.now().minusDays(days);
    Join<Customer, Invoice> inv = root.join("invoices", JoinType.LEFT);
    Predicate unpaid = cb.equal(inv.get("status"), InvoiceStatus.UNPAID);
    Predicate older = cb.lessThan(inv.get("issuedOn"), cutoff);
    // exists subquery to avoid duplicates:
    Subquery<String> sub = query.subquery(String.class);
    Root<Customer> c2 = sub.from(Customer.class);
    Join<Customer, Invoice> i2 = c2.join("invoices", JoinType.INNER);
    sub.select(c2.get("id"))
       .where(cb.and(cb.equal(c2.get("id"), root.get("id")),
                     cb.equal(i2.get("status"), InvoiceStatus.UNPAID),
                     cb.lessThan(i2.get("issuedOn"), cutoff)));
    return cb.exists(sub);
  }
}

// Derived/composed example:
final class RiskyCustomer {
  static Spec<Customer> rule() {
    return new PremiumCustomer()
        .and(new RegisteredBefore(LocalDate.now().minusYears(1)))
        .and(new HasUnpaidInvoiceOlderThan(30));
  }
}

// ===== Repository (JPA + in-memory fallback) =====
interface CustomerRepository {
  List<Customer> findAll(Spec<Customer> spec);
}

class JpaCustomerRepository implements CustomerRepository {
  private final jakarta.persistence.EntityManager em;
  JpaCustomerRepository(jakarta.persistence.EntityManager em) { this.em = em; }

  @Override public List<Customer> findAll(Spec<Customer> spec) {
    CriteriaBuilder cb = em.getCriteriaBuilder();
    CriteriaQuery<Customer> cq = cb.createQuery(Customer.class);
    Root<Customer> root = cq.from(Customer.class);
    Predicate p = spec.toPredicate(root, cq, cb); // may throw if unsupported
    cq.select(root).where(p).distinct(true);
    return em.createQuery(cq).getResultList();
  }
}

// In-memory repository for tests or simple scenarios
class InMemoryCustomerRepository implements CustomerRepository {
  private final List<Customer> data;
  InMemoryCustomerRepository(List<Customer> data) { this.data = data; }
  @Override public List<Customer> findAll(Spec<Customer> spec) {
    return data.stream().filter(spec::isSatisfiedBy).toList();
  }
}

// ===== Usage =====
class SpecDemo {
  public static void main(String[] args) {
    // Build a composed domain rule
    Spec<Customer> risky = RiskyCustomer.rule();

    // In-memory demo set
    Customer a = new Customer();
    a.id = "c1"; a.tier = "PREMIUM"; a.registeredOn = LocalDate.now().minusYears(2);
    a.invoices = List.of(new Invoice(){{
      id="i1"; issuedOn=LocalDate.now().minusDays(45); status=InvoiceStatus.UNPAID; amountCents=5000;
    }});

    Customer b = new Customer();
    b.id = "c2"; b.tier = "BASIC"; b.registeredOn = LocalDate.now().minusYears(3);
    b.invoices = List.of();

    var repo = new InMemoryCustomerRepository(List.of(a,b));
    var result = repo.findAll(risky);
    System.out.println("Risky customers: " + result.stream().map(c -> c.id).toList());

    // For JPA, pass risky spec to JpaCustomerRepository to generate a single SQL query.
  }
}
```

**Notes on the example**

-   A **single rule** (`RiskyCustomer.rule()`) is used both **in-memory** and (if supported) **translated** to a DB query.

-   `HasUnpaidInvoiceOlderThan` shows how to express a **subquery/exists** for correct SQL semantics.

-   You can mark some specs **memory-only** by leaving `toPredicate` unimplemented and handling that in the repo (e.g., fetch broader set then filter in memory when translation isn’t possible).


---

## Known Uses

-   **DDD repositories** to avoid “finder method explosion”.

-   **Authorization policies** (e.g., “user can modify order if editor AND same tenant”).

-   **Validation/business rules** (shipping eligibility, discount applicability).

-   Search/filter layers in admin portals and back offices.


---

## Related Patterns

-   **Strategy** — interchangeable algorithms; Specification is a *predicate* strategy with composability.

-   **Composite** — specifications naturally compose via AND/OR/NOT.

-   **Query Object / Criteria** — Specification often delegates to these for DB translation.

-   **Policy** — business policy can be expressed as a specification.

-   **Decorator** — less apt; composition is usually via logical operators rather than wrapping side-effects.
