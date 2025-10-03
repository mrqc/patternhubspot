# Domain Service (Domain-Driven Design)

## Pattern Name and Classification

**Name:** Domain Service  
**Classification:** DDD tactical pattern (domain layer abstraction)

---

## Intent

Model a **domain operation** that:

-   embodies **business logic**, policy, or calculation,

-   **does not naturally belong** to a single Entity/Aggregate (no clear owner), and

-   must remain **pure, testable, and free of infrastructure concerns**.


---

## Also Known As

-   Domain Operation

-   Policy Service / Policy Object

-   Calculation Service


---

## Motivation (Forces)

-   Some business rules span **multiple aggregates** (e.g., transfer between accounts, pricing across catalogs) or depend purely on **domain concepts** without a natural home in a single entity.

-   Placing such logic in an Application Service leads to **anemic domain** and duplication.

-   Forcing it into an Aggregate bloats the model and **violates aggregate boundaries** and invariants.

-   A Domain Service preserves a **rich domain model**, expressing ubiquitous language in a focused, stateless abstraction.


Tensions to balance:

-   Keep the service **stateless & deterministic** vs. needing references to repositories.

-   Ensure it holds **pure domain logic**, not orchestration or I/O.

-   Avoid “**service dumping ground**” anti-pattern by applying strict inclusion criteria.


---

## Applicability

Use a Domain Service when:

-   A rule **uses multiple aggregates** or **cross-aggregate checks** (e.g., “mayTransfer?” across two accounts and a risk policy).

-   The logic is **not** a responsibility of one entity/value object and **is not** an application-level workflow.

-   The operation is **domain-significant** (“CalculatePremium”, “DeterminePrice”, “AuthorizeTransfer”).


Avoid when:

-   Logic **belongs to a single aggregate** → keep it in the aggregate.

-   It’s **workflow/orchestration** (calling external systems, sending emails) → Application Service or Saga.

-   It’s **infrastructure** (persistence, messaging) → Infrastructure layer.


---

## Structure

-   **Domain Service (Interface):** Named in ubiquitous language, exposes domain operation(s). Stateless, side-effect-free (ideally).

-   **Implementation:** Uses domain objects and repositories to fetch data required for the computation/decision.

-   **Entities/Aggregates/Value Objects:** Consumed or produced by the service.

-   **Repositories (as ports):** Passed in or injected to supply domain objects—no infrastructure leakage.


---

## Participants

-   **Domain Service:** Encapsulates a business capability across aggregates.

-   **Aggregates / Entities:** Provide invariants and behaviors; used by the service.

-   **Value Objects:** Inputs/outputs to keep operations explicit and pure.

-   **Repositories (Domain-facing):** Supply aggregates needed for the decision.

-   **Application Service:** Orchestrates use of domain services within transactions.


---

## Collaboration

1.  Application Service starts a use case (transaction boundary).

2.  It loads necessary aggregates (via repositories).

3.  It invokes the **Domain Service** to compute/decide (e.g., “authorizeTransfer”).

4.  Based on the result, the Application Service calls **aggregate methods** to change state and persists them.

5.  Domain Events may be raised; further reactions occur elsewhere.


---

## Consequences

**Benefits**

-   Keeps domain logic **centralized, expressive, testable**.

-   **Prevents bloated aggregates** and anemic application services.

-   Encourages **pure functions** and clear domain APIs.


**Liabilities**

-   Risk of becoming a **catch-all** for arbitrary code—guard scope tightly.

-   Overuse can **hide behavior** that should live on aggregates.

-   If not careful, may **depend on infrastructure** and break purity.


---

## Implementation

**Guidelines**

-   **Name** with domain language and verbs: `AuthorizeTransfer`, `CalculatePremium`, `DeterminePrice`.

-   Prefer **stateless**, **side-effect-free** operations returning Value Objects or booleans/decisions.

-   Accept **domain types**, not primitives (e.g., `Money`, `AccountId`).

-   If data is needed, depend on **repository abstractions** (domain interfaces).

-   Keep **I/O, messaging, transactions** out of Domain Services (they live in the Application layer).

-   **Unit test** in isolation with in-memory fakes for repositories.

-   Keep logic **cohesive**; split services by capability, not technical layer.


**Anti-patterns to avoid**

-   “HelperUtils” dumping ground.

-   Injecting HTTP clients, message brokers, or ORMs directly.

-   Large multi-purpose services (`FooDomainService` with 30 unrelated methods).


---

## Sample Code (Java)

### Domain Types

```java
// Value objects
public record AccountId(String value) {
    public AccountId {
        if (value == null || value.isBlank()) throw new IllegalArgumentException("accountId");
    }
}

public record Money(java.math.BigDecimal amount, String currency) {
    public Money {
        if (amount == null || currency == null) throw new IllegalArgumentException();
        if (amount.scale() > 2) throw new IllegalArgumentException("max 2 decimal places");
    }
    public Money add(Money other) {
        requireSameCurrency(other);
        return new Money(amount.add(other.amount), currency);
    }
    public Money subtract(Money other) {
        requireSameCurrency(other);
        return new Money(amount.subtract(other.amount), currency);
    }
    public boolean gte(Money other) { requireSameCurrency(other); return amount.compareTo(other.amount) >= 0; }
    private void requireSameCurrency(Money other) {
        if (!currency.equals(other.currency)) throw new IllegalArgumentException("currency mismatch");
    }
}
```

### Aggregates

```java
import java.time.Instant;

public class Account {
    private final AccountId id;
    private Money balance;
    private boolean frozen;
    private Instant openedAt;

    public Account(AccountId id, Money openingBalance) {
        this.id = id;
        this.balance = openingBalance;
        this.openedAt = Instant.now();
        this.frozen = false;
    }

    public AccountId id() { return id; }
    public Money balance() { return balance; }
    public boolean isFrozen() { return frozen; }

    public void debit(Money amount) {
        if (frozen) throw new IllegalStateException("account frozen");
        if (!balance.gte(amount)) throw new IllegalStateException("insufficient funds");
        this.balance = balance.subtract(amount);
    }

    public void credit(Money amount) {
        if (frozen) throw new IllegalStateException("account frozen");
        this.balance = balance.add(amount);
    }

    public void freeze() { this.frozen = true; }
}
```

### Repository (Domain Port)

```java
public interface AccountRepository {
    Account findById(AccountId id);                 // throws if not found (or return Optional)
    void save(Account account);                     // unit-of-work handles transactions
}
```

### Domain Service (Decision/Policy)

```java
import java.time.Clock;

public interface TransferAuthorizationService {
    AuthorizationResult authorize(Account source, Account destination, Money amount);
}

public record AuthorizationResult(boolean allowed, String reason) {
    public static AuthorizationResult allowed() { return new AuthorizationResult(true, "OK"); }
    public static AuthorizationResult denied(String reason) { return new AuthorizationResult(false, reason); }
}

// Implementation encapsulates cross-aggregate rules and policy
public final class DefaultTransferAuthorizationService implements TransferAuthorizationService {
    private final RiskPolicy policy;
    private final Clock clock;

    public DefaultTransferAuthorizationService(RiskPolicy policy, Clock clock) {
        this.policy = policy;
        this.clock = clock;
    }

    @Override
    public AuthorizationResult authorize(Account source, Account destination, Money amount) {
        if (amount.amount().signum() <= 0) return AuthorizationResult.denied("non-positive amount");
        if (source.isFrozen()) return AuthorizationResult.denied("source frozen");
        if (destination.isFrozen()) return AuthorizationResult.denied("destination frozen");
        if (!source.balance().gte(amount)) return AuthorizationResult.denied("insufficient funds");
        if (!policy.permits(clock.instant(), source, destination, amount))
            return AuthorizationResult.denied("risk policy violation");
        return AuthorizationResult.allowed();
    }
}

// A domain policy abstraction (can be backed by rules, tiers, etc.)
public interface RiskPolicy {
    boolean permits(java.time.Instant when, Account src, Account dst, Money amount);
}
```

### Application Service (Orchestration Using Domain Service)

```java
// This is NOT a domain service; it coordinates repositories, transactions, and domain calls.
public class TransferFundsApplicationService {
    private final AccountRepository accounts;
    private final TransferAuthorizationService auth;

    public TransferFundsApplicationService(AccountRepository accounts,
                                           TransferAuthorizationService auth) {
        this.accounts = accounts;
        this.auth = auth;
    }

    // Annotate @Transactional in Spring or manage Tx in your framework
    public void transfer(AccountId sourceId, AccountId destinationId, Money amount) {
        var src = accounts.findById(sourceId);
        var dst = accounts.findById(destinationId);

        var decision = auth.authorize(src, dst, amount);
        if (!decision.allowed()) throw new IllegalStateException("transfer denied: " + decision.reason());

        src.debit(amount);
        dst.credit(amount);

        accounts.save(src);
        accounts.save(dst);
        // Optionally raise a Domain Event (e.g., TransferCompleted) here
    }
}
```

**Notes**

-   `TransferAuthorizationService` is pure domain logic and **stateless**.

-   `TransferFundsApplicationService` handles **orchestration & transactions**.

-   Repositories are **domain interfaces**; the infrastructure provides implementations.

-   Policies can be swapped for testing or different market rules.


---

## Known Uses

-   **Pricing/Quoting:** `DeterminePrice`, `CalculateDiscount` using catalog & customer tiers.

-   **Payments/Banking:** `AuthorizeTransfer`, `AssessCreditLimit`, `CalculateFees`.

-   **Insurance:** `CalculatePremium`, `AssessRisk`.

-   **Logistics:** `RoutePlanner`, `AllocateInventory` across warehouses.

-   **Compliance:** `ValidateKycPolicy`, `CheckSanctions`.


---

## Related Patterns

-   **Entity/Aggregate:** Keep invariants local; use Domain Service only when logic is cross-aggregate or ownerless.

-   **Value Object:** Ideal inputs/outputs to keep operations pure.

-   **Repository:** Supplies aggregates without leaking infrastructure.

-   **Application Service:** Orchestrates workflows, transactions, and I/O around domain logic.

-   **Policy / Specification:** Domain Service often implements or composes these.

-   **Domain Event:** Emitted after successful operations for decoupled reactions.
