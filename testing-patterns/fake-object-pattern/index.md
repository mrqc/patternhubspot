# Fake Object — Testing Pattern

## Pattern Name and Classification

-   **Name:** Fake Object
    
-   **Classification:** Test Double Pattern (xUnit family) / Behavioral Isolation
    

## Intent

Replace a heavyweight or hard-to-control collaborator with a **lightweight working implementation** that behaves like the real thing **at the interface level** (often simplified and in-memory) so tests run **fast, deterministically, and without external dependencies**.

## Also Known As

-   Fake
    
-   In-Memory Implementation
    
-   Lightweight Test Implementation
    
-   “Realish” Stub
    

## Motivation (Forces)

-   **Speed & determinism:** Hitting a real DB, queue, or third-party API makes tests slow, flaky, and environment-dependent.
    
-   **Isolation:** You want to test domain logic, not the behavior/availability of infrastructure.
    
-   **Observability:** It’s easier to introspect a fake (captured messages, internal state) than a real system.
    
-   **Safety & cost:** Avoid charges, rate limits, and side effects (emails, payments) during tests.
    

Tensions:

-   **Fidelity vs. simplicity:** Too simple → diverges from real behavior; too faithful → as complex as the real thing.
    
-   **Scope creep:** Fakes can grow features and become a second system to maintain.
    

## Applicability

Use a Fake Object when:

-   The collaborator is **slow, nondeterministic, or external** (DB, message broker, email/SMS, payment, clock).
    
-   Tests primarily exercise **business rules** where infrastructure details are irrelevant.
    
-   You can define a **clear contract/port** for the collaborator.
    

Avoid or complement with other strategies when:

-   You must validate **integration details** (SQL, TLS, auth) → use integration/contract tests.
    
-   You need to check **interaction order/expectations** → use a **Mock** or **Spy**.
    
-   You need **production parity** (performance, concurrency) → use staging/E2E.
    

## Structure

-   **Port/Interface:** Stable contract used by the SUT (e.g., `UserRepository`, `EmailSender`).
    
-   **Real Adapter:** Production implementation (JPA, SMTP, HTTP).
    
-   **Fake Adapter:** In-memory or simplified implementation honoring the port’s semantics.
    
-   **SUT (System Under Test):** Business logic using the port.
    
-   **Test:** Injects fakes, seeds state, runs scenario, asserts outcomes.
    

```css
[Test] ──constructs──► [SUT]
                       │
                       ├── calls ► [Port: UserRepository] ─► [FakeUserRepository (test)]
                       └── calls ► [Port: EmailSender]     ─► [FakeEmailSender (test)]
```

## Participants

-   **SUT:** Code under test.
    
-   **Port/Contract:** Interface boundary that hides infrastructure.
    
-   **Fake Implementation:** Simple, deterministic stand-in honoring the contract.
    
-   **Real Implementation (out of scope in unit tests):** Used in integration/E2E suites.
    
-   **Test Fixture:** Seeds data, configures fake failure modes, asserts results.
    

## Collaboration

1.  Test **creates fakes** and injects them into the SUT.
    
2.  Test **seeds** fake state if needed (e.g., an existing user).
    
3.  SUT executes logic, interacting with fakes through the **same contract** it uses in production.
    
4.  Test **asserts** on returned values and, if useful, **observes fake internals** (e.g., captured emails).
    

## Consequences

**Benefits**

-   **Fast, reliable** tests independent of environment.
    
-   **Readable** tests focused on business rules.
    
-   **Introspectable:** capture side effects (emails sent, events published).
    
-   **Supports TDD**: build the domain while infrastructure lags behind.
    

**Liabilities**

-   **Behavior drift:** Fake may not match real edge cases (uniqueness, transactions, serialization).
    
-   **Overuse risk:** Replacing *everything* with fakes hides integration problems.
    
-   **Maintenance:** Fakes must evolve with the port and invariants.
    

## Implementation

### Guidelines

-   Define a **clear port/contract** first (Hexagonal/Clean Architecture helps).
    
-   The fake must uphold **critical semantics**: uniqueness, validation, idempotency, basic error modes.
    
-   Provide **hooks** for tests: seeding, resetting, simulating failures, and time control.
    
-   Keep fakes **small & deterministic**; avoid threads and IO unless you’re testing them.
    
-   **Contract tests**: verify both fake and real implementations against the same specification.
    
-   Make fakes **stateless or easily resettable** between tests.
    

### What to simulate (choose pragmatically)

-   **Persistence rules:** uniqueness, auto-IDs, simple transactions.
    
-   **External side effects:** capture payloads (emails, webhooks).
    
-   **Failures:** toggle to throw on next call / after N calls (timeouts, 5xx).
    
-   **Time:** a fake clock to fix timestamps.
    

---

## Sample Code (Java 17, JUnit 5)

> Scenario: user registration sends a welcome email and forbids duplicate emails.  
> We define ports (`UserRepository`, `EmailSender`), production-agnostic `RegistrationService`, and **fakes** used in tests.

```java
// ==== Domain & Ports ====
package example;

import java.time.Instant;
import java.util.*;

public record User(UUID id, String email, Instant createdAt) {
  public User { Objects.requireNonNull(id); Objects.requireNonNull(email); Objects.requireNonNull(createdAt); }
}

interface UserRepository {
  Optional<User> findByEmail(String email);
  User save(User user); // returns persisted user (id may be assigned) 
  void deleteAll();     // test convenience
}

record Email(String to, String subject, String body) {}

interface EmailSender {
  void send(Email email);
  void reset(); // test convenience
}

// ==== SUT ====
class RegistrationService {
  private final UserRepository users;
  private final EmailSender emails;
  private final java.time.Clock clock;

  RegistrationService(UserRepository users, EmailSender emails, java.time.Clock clock) {
    this.users = users; this.emails = emails; this.clock = clock;
  }

  public User register(String email) {
    if (email == null || email.isBlank()) throw new IllegalArgumentException("empty email");
    if (users.findByEmail(email).isPresent()) throw new IllegalStateException("duplicate email");
    User created = new User(UUID.randomUUID(), email, Instant.now(clock));
    User saved = users.save(created);
    emails.send(new Email(saved.email(), "Welcome", "Hello " + saved.email() + "!"));
    return saved;
  }
}
```

```java
// ==== Fakes ====
package example;

import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

class FakeUserRepository implements UserRepository {
  private final Map<UUID, User> byId = new ConcurrentHashMap<>();
  private final Map<String, UUID> byEmail = new ConcurrentHashMap<>();
  private volatile boolean failNext = false;

  /** Optional: simulate a transient failure on next call to save */
  public void failNextSave() { this.failNext = true; }

  @Override public Optional<User> findByEmail(String email) {
    UUID id = byEmail.get(email);
    return id == null ? Optional.empty() : Optional.of(byId.get(id));
  }

  @Override public User save(User user) {
    if (failNext) { failNext = false; throw new RuntimeException("DB down (simulated)"); }
    // enforce uniqueness by email
    if (byEmail.containsKey(user.email())) throw new IllegalStateException("unique(email) violated");
    User stored = new User(
        user.id() == null ? UUID.randomUUID() : user.id(),
        user.email(),
        user.createdAt() == null ? Instant.now() : user.createdAt()
    );
    byId.put(stored.id(), stored);
    byEmail.put(stored.email(), stored.id());
    return stored;
  }

  @Override public void deleteAll() {
    byId.clear(); byEmail.clear(); failNext = false;
  }
}

class FakeEmailSender implements EmailSender {
  private final List<Email> sent = Collections.synchronizedList(new ArrayList<>());
  private volatile boolean failNext = false;

  public void failNextSend() { failNext = true; }
  public List<Email> sentEmails() { return List.copyOf(sent); }

  @Override public void send(Email email) {
    if (failNext) { failNext = false; throw new RuntimeException("SMTP failure (simulated)"); }
    sent.add(email);
  }

  @Override public void reset() { sent.clear(); failNext = false; }
}
```

```java
// ==== Tests (JUnit 5) ====
package example;

import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.*;

import java.time.*;

public class RegistrationServiceTest {

  FakeUserRepository users;
  FakeEmailSender emails;
  RegistrationService service;
  Clock fixedClock;

  @BeforeEach
  void setUp() {
    users = new FakeUserRepository();
    emails = new FakeEmailSender();
    fixedClock = Clock.fixed(Instant.parse("2025-01-01T12:00:00Z"), ZoneOffset.UTC);
    service = new RegistrationService(users, emails, fixedClock);
  }

  @AfterEach
  void tearDown() {
    users.deleteAll();
    emails.reset();
  }

  @Test
  void registers_new_user_and_sends_email() {
    User u = service.register("alice@example.com");

    assertNotNull(u.id());
    assertEquals(Instant.parse("2025-01-01T12:00:00Z"), u.createdAt());
    assertEquals("alice@example.com", u.email());

    assertEquals(1, emails.sentEmails().size());
    Email mail = emails.sentEmails().get(0);
    assertEquals("alice@example.com", mail.to());
    assertTrue(mail.body().contains("Hello alice@example.com"));
  }

  @Test
  void prevents_duplicate_email() {
    service.register("bob@example.com");
    IllegalStateException ex = assertThrows(IllegalStateException.class, () -> service.register("bob@example.com"));
    assertTrue(ex.getMessage().contains("duplicate"));
    assertEquals(1, emails.sentEmails().size(), "no second email should be sent");
  }

  @Test
  void can_simulate_transient_repo_failure() {
    users.failNextSave();
    RuntimeException ex = assertThrows(RuntimeException.class, () -> service.register("fail@example.com"));
    assertTrue(ex.getMessage().contains("DB down"));
    assertTrue(users.findByEmail("fail@example.com").isEmpty(), "failed writes should not persist");
  }

  @Test
  void can_simulate_email_failure() {
    emails.failNextSend();
    RuntimeException ex = assertThrows(RuntimeException.class, () -> service.register("carol@example.com"));
    assertTrue(ex.getMessage().contains("SMTP"));
    // Depending on transactional requirements, you might assert rollback semantics here.
  }
}
```

**Why this is a “Fake Object”**

-   `FakeUserRepository` and `FakeEmailSender` are **working implementations** (not mere stubs/mocks) that honor the **same ports** and basic invariants (unique email), yet are **in-memory, deterministic, and fast**.
    
-   Tests configure **failure modes** and **inspect** effects without real infrastructure.
    

## Known Uses

-   **In-memory repositories** (Maps instead of DB) for domain/service tests.
    
-   **Fake mail/SMS/payment gateways** that capture outbound messages or charges.
    
-   **Fake clock** (fixed/controllable time) to make time-dependent logic deterministic.
    
-   **Fake object stores** (local temp dirs/in-mem byte arrays) instead of S3/GCS.
    
-   **Fake message brokers** (in-process queues) for simple pub/sub flows.
    

## Related Patterns

-   **Dummy Object:** passed but never used (placeholder).
    
-   **Stub:** returns canned answers; no behavior beyond what tests ask for.
    
-   **Mock:** verifies interaction/expectations (behavior verification).
    
-   **Spy:** like a stub but records calls for assertions.
    
-   **Test-Specific Subclass:** override behavior via inheritance for testing.
    
-   **Contract Testing:** ensure both **fake and real** implementations honor the same API schema/semantics.
    
-   **Hexagonal/Ports & Adapters:** architectural style that makes using fakes trivial.
    

---

## Implementation Tips

-   Put fakes in a **test scope** module/package; keep API identical to the port.
    
-   **Reset/seed** APIs help avoid test interference.
    
-   Mirror **critical invariants** (uniqueness, validation, idempotency) and **basic error cases**.
    
-   Add **contract tests** that run against both fake and real adapters.
    
-   Don’t recreate production complexity—**simulate, don’t emulate**.
    
-   Periodically review fakes for **drift** when real behavior changes (migrations, new constraints).

