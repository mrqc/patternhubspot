# Onion Architecture — Software Architecture Pattern

## Pattern Name and Classification

-   **Name:** Onion Architecture
    
-   **Classification:** Architectural Style / Dependency-Inversion–centric / Domain-first
    

## Intent

Place **domain rules at the center** and force all dependencies to point **inward**. The core defines **domain models and interfaces (ports)**; outer rings provide **application flow** and **infrastructure adapters** (DB, web, messaging). This makes business code independent from frameworks and replaceable details.

## Also Known As

-   Ports & Adapters (close cousin)
    
-   Clean Architecture (family)
    
-   Domain-Centric / Inward Dependencies
    

## Motivation (Forces)

-   **Stability vs. change:** Frameworks, DBs, and UIs churn faster than business rules.
    
-   **Testability:** Domain and use cases should run in memory without external systems.
    
-   **Multiple I/O:** Same use cases via HTTP, CLI, messaging, batch.
    
-   **Longevity:** Keep critical rules portable across tech shifts.
    

Onion Architecture answers this with **concentric rings**: **Domain** (center) → **Application** → **Adapters** (outer). Contracts live inward; details live outward.

## Applicability

Use when:

-   You need framework/DB independence and high testability.
    
-   The same core logic must serve multiple delivery mechanisms.
    
-   You want a clean path to evolve a monolith, a modular monolith, or microservices.
    

Avoid when:

-   The domain is tiny and a simple layered CRUD suffices (ceremony may not pay off).
    

## Structure

Rings (dependencies only point inward):

1.  **Domain (Core):** Entities, Value Objects, Domain Services, Repository Interfaces (ports).
    
2.  **Application (Use Cases):** Orchestrates tasks, enforces app policy, owns input/output models.
    
3.  **Adapters (Infrastructure):** Implement repositories, gateways, frameworks (DB, HTTP, MQ, file).
    
4.  **Presentation / Composition Root:** Wires everything (DI), controllers, CLI, jobs.
    

```pgsql
(outside)            Adapters / Frameworks
   +-----------------------------------------------+
   |  Web / CLI / Schedulers / DB / Message Broker |
   +--------------------+--------------------------+
                        |
                 +------v-------+   implements ports
                 |  Application |-------------------------+
                 |  (Use Cases) |                         |
                 +------+-------+                         |
                        | uses ports                      |
               +--------v---------+                       |
               |      Domain      |<----------------------+
               | Entities, VOs,   |   (ports = interfaces)
               | Domain Services  |   (no outward deps)
               +------------------+
                   (innermost)
```

## Participants

-   **Entity / Value Object:** domain state + invariants.
    
-   **Domain Service:** pure domain operations spanning multiple entities.
    
-   **Repository Interface (Port):** defined in Domain; hides persistence.
    
-   **Use Case (Application Service):** coordinates repositories and domain services; returns DTOs.
    
-   **Adapter (Infrastructure):** concrete implementation of repositories/gateways.
    
-   **Presenter/Controller:** maps transport to use-case requests/responses.
    
-   **Composition Root:** wiring/DI.
    

## Collaboration

1.  A controller (outer ring) converts a request into a **use-case input**.
    
2.  The **use case** loads entities via **domain-defined repositories**, invokes **domain services**, persists changes, and returns an **output DTO**.
    
3.  Adapters implement repository ports and handle I/O concerns.
    
4.  No domain code depends on frameworks, DBs, or controllers.
    

## Consequences

**Benefits**

-   Business rules are **independent** of frameworks and IO.
    
-   **Replaceable** infrastructure (DB/web) with minimal impact.
    
-   **Testable**: core runs as pure Java with fakes.
    
-   **Versatile** delivery (REST, CLI, MQ) without duplicating rules.
    

**Liabilities**

-   More classes/interfaces (initial ceremony).
    
-   Requires discipline to keep dependencies pointing inward.
    
-   Mapping between layers (DTOs ↔ entities) adds boilerplate.
    

## Implementation

**Guidelines**

-   Define repository/gateway **interfaces in the Domain**.
    
-   Keep **use-case input/output models** free of transport types.
    
-   Transactions belong at **application boundaries** (decorator/AOP).
    
-   Adapters are the only place for frameworks (JPA, HTTP clients, drivers).
    
-   Use **package-by-feature** (e.g., `account`, `order`) to keep cohesion.
    
-   Enforce direction with tools (ArchUnit, JPMS modules).
    

---

## Sample Code (Java 17, framework-agnostic)

> Scenario: **Transfer money between accounts**.  
> Rings: **domain** (entities, domain service, repository port) → **application** (use case) → **infrastructure** (in-memory repo) → **presentation** (CLI-like main).  
> In a real project these would be separate packages/modules.

```java
import java.math.BigDecimal;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/* ========== DOMAIN (innermost ring) ========== */
final class Money {
  private final BigDecimal amount;
  private final String currency;
  public Money(BigDecimal amount, String currency) {
    if (amount == null || currency == null) throw new IllegalArgumentException();
    if (amount.scale() > 2) this.amount = amount.setScale(2, BigDecimal.ROUND_HALF_UP);
    else this.amount = amount;
    this.currency = currency;
    if (this.amount.compareTo(BigDecimal.ZERO) < 0) throw new IllegalArgumentException("negative");
  }
  public Money add(Money other){ requireSame(other); return new Money(amount.add(other.amount), currency); }
  public Money subtract(Money other){
    requireSame(other);
    var res = amount.subtract(other.amount);
    if (res.compareTo(BigDecimal.ZERO) < 0) throw new IllegalStateException("insufficient funds");
    return new Money(res, currency);
  }
  private void requireSame(Money other){ if (!currency.equals(other.currency)) throw new IllegalArgumentException("currency mismatch"); }
  public BigDecimal amount(){ return amount; }
  public String currency(){ return currency; }
  @Override public String toString(){ return amount.toPlainString() + " " + currency; }
}

final class AccountId {
  private final UUID id;
  public AccountId(UUID id){ this.id = Objects.requireNonNull(id); }
  public UUID value(){ return id; }
  @Override public boolean equals(Object o){ return (o instanceof AccountId a) && a.id.equals(id); }
  @Override public int hashCode(){ return id.hashCode(); }
  @Override public String toString(){ return id.toString(); }
}

final class Account {
  private final AccountId id;
  private Money balance;
  public Account(AccountId id, Money opening){ this.id = id; this.balance = opening; }
  public AccountId id(){ return id; }
  public Money balance(){ return balance; }
  public void debit(Money amount){ balance = balance.subtract(amount); }
  public void credit(Money amount){ balance = balance.add(amount); }
}

/** Repository PORT lives in the Domain (Onion rule) */
interface AccountRepository {
  Optional<Account> findById(AccountId id);
  void save(Account account);
}

/** Pure Domain Service (no infrastructure) */
final class TransferDomainService {
  public void transfer(Account from, Account to, Money amount) {
    if (!from.balance().currency().equals(to.balance().currency()))
      throw new IllegalArgumentException("cross-currency not allowed");
    from.debit(amount);
    to.credit(amount);
  }
}

/* ========== APPLICATION (use cases) ========== */
final class TransferFunds {
  public record Input(AccountId from, AccountId to, BigDecimal amount, String currency) {}
  public record Output(AccountId from, String fromBalance, AccountId to, String toBalance) {}
  private final AccountRepository accounts;
  private final TransferDomainService domain;

  public TransferFunds(AccountRepository accounts, TransferDomainService domain) {
    this.accounts = accounts; this.domain = domain;
  }

  public Output handle(Input in) {
    var src = accounts.findById(in.from()).orElseThrow(() -> new IllegalArgumentException("from not found"));
    var dst = accounts.findById(in.to()).orElseThrow(() -> new IllegalArgumentException("to not found"));
    var money = new Money(in.amount(), in.currency());
    // (Transaction boundary would be here in real life)
    domain.transfer(src, dst, money);
    accounts.save(src); accounts.save(dst);
    return new Output(src.id(), src.balance().toString(), dst.id(), dst.balance().toString());
  }
}

/* ========== INFRASTRUCTURE (outer ring, adapters) ========== */
final class InMemoryAccountRepository implements AccountRepository {
  private final Map<AccountId, Account> store = new ConcurrentHashMap<>();
  @Override public Optional<Account> findById(AccountId id){ return Optional.ofNullable(store.get(id)); }
  @Override public void save(Account account){ store.put(account.id(), account); }
  public void seed(Account a){ save(a); }
}

/* ========== PRESENTATION / COMPOSITION ROOT (wiring) ========== */
public class OnionArchitectureDemo {
  public static void main(String[] args) {
    // Infrastructure
    InMemoryAccountRepository repo = new InMemoryAccountRepository();

    // Seed data
    AccountId a = new AccountId(UUID.randomUUID());
    AccountId b = new AccountId(UUID.randomUUID());
    repo.seed(new Account(a, new Money(new BigDecimal("100.00"), "EUR")));
    repo.seed(new Account(b, new Money(new BigDecimal("20.00"), "EUR")));

    // Application + Domain
    TransferFunds useCase = new TransferFunds(repo, new TransferDomainService());

    // Simulated controller call
    var out = useCase.handle(new TransferFunds.Input(a, b, new BigDecimal("15.50"), "EUR"));
    System.out.println("From " + out.from() + " -> " + out.fromBalance());
    System.out.println("To   " + out.to()   + " -> " + out.toBalance());
  }
}
```

**Why this is “Onion”:**

-   **Domain** (entities, VOs, domain service, repository **interfaces**) is the innermost ring.
    
-   **Application** depends only on the **domain**.
    
-   **Infrastructure** implements domain ports and depends inward.
    
-   **Presentation/Composition** wires everything; the domain knows nothing about it.
    

## Known Uses

-   **Business-critical backends** seeking long-lived domain cores independent of frameworks.
    
-   **E-commerce & banking systems** that must swap DBs, queues, or web frameworks over time.
    
-   **Modular monoliths / microservices** that share the same inward dependency rule.
    

## Related Patterns

-   **Hexagonal / Ports & Adapters:** very close; Hexagonal stresses runtime ports/adapters, Onion stresses concentric rings.
    
-   **Clean Architecture:** another member of the family with similar rules and terminology.
    
-   **Layered Architecture:** often used inside rings; Onion enforces dependency direction more strictly.
    
-   **CQRS:** can be applied inside the application layer.
    
-   **Microkernel:** plugin-style extensions can sit at the outer rings.
    

---

## Implementation Tips

-   Keep **domain pure**: no JPA annotations or framework types; map in adapters.
    
-   Put **ports** (repositories/gateways) in the domain, not infrastructure.
    
-   Use **DTOs** for use-case I/O; never leak transport types inward.
    
-   Add **transactional decorators** around use cases in the outer ring.
    
-   Enforce rules with **ArchUnit** or **JPMS** (exports only contracts).
    
-   Write **unit tests** for domain and use cases with in-memory fakes; **contract tests** for adapters.
    
-   Treat frameworks as **details**: integrate at the edges, not the core.

