# Mocking — Testing Pattern

## Pattern Name and Classification

-   **Name:** Mocking
    
-   **Classification:** xUnit Test Double Pattern / Behavior Verification / Isolation Testing
    

## Intent

Isolate the **System Under Test (SUT)** by replacing its collaborators with **mocks** that:

1.  **simulate behavior** (stubbing), and
    
2.  **verify interactions** (calls, arguments, order, counts).  
    This lets you specify and check **observable collaboration** without relying on real infrastructure or complex setups.
    

## Also Known As

-   Mock Objects
    
-   Interaction Testing
    
-   Test Doubles (mock is one kind; others are stub, fake, spy, dummy)
    

## Motivation (Forces)

-   **Fast, deterministic feedback** without external systems (DB, mail, payments).
    
-   **Design pressure**: mocking pushes you to define **clear ports/interfaces** and small, cohesive SUTs.
    
-   **Specification by example**: tests define *how* the SUT collaborates (messages sent) rather than internal state.  
    Tensions:
    
-   **Over-specification** (verifying incidental calls) makes tests brittle.
    
-   **Coupling** to method names and call order can reduce refactoring freedom.
    
-   **Behavior vs. state**: some behaviors are easier to assert via **state outcomes** than via interaction checks.
    

## Applicability

Use mocking when:

-   The SUT depends on **unreliable, slow, or costly** collaborators.
    
-   You want to assert that **specific messages** are sent (e.g., “charge customer”, “emit event”).
    
-   The collaborator has **complex error modes** you need to simulate.
    

Prefer other patterns when:

-   You need realistic adapter behavior → **Integration Test**.
    
-   You mainly check outputs/state → a **Fake** or **stub** may suffice.
    
-   You need broad regression coverage of serialized output → **Golden Master**.
    

## Structure

-   **SUT** uses collaborators through **ports/interfaces**.
    
-   **Mock objects** implement those ports and are programmed with **expectations** (stubs) and **verifications** (assertions).
    
-   **Test** orchestrates Given/When/Then and inspects mock interactions.
    

```less
[Test] → constructs → [SUT]
                       │
                       ├─ calls → [Mock A]  (verify: method, args, times, order)
                       └─ calls → [Mock B]  (stub: return values / throw)
```

## Participants

-   **System Under Test (SUT)** — code you’re validating.
    
-   **Collaborators/Ports** — interfaces the SUT depends on.
    
-   **Mocks** — programmable doubles with interaction verification.
    
-   **Test Runner/Framework** — JUnit/TestNG + mocking library (Mockito, MockK, etc.).
    

## Collaboration

1.  **Given**: create mocks; program stubs for expected paths/errors.
    
2.  **When**: execute SUT behavior.
    
3.  **Then**: verify **interactions** (methods/arguments/times/order) and possibly returned state.
    

## Consequences

**Benefits**

-   Fast, isolated tests; no networks/databases.
    
-   Encourages **ports & adapters** boundaries.
    
-   Precise checks for **side effects** (email sent, event published).
    

**Liabilities**

-   **Brittleness** if you verify incidental calls or call order too strictly.
    
-   Can mask **integration issues** if overused.
    
-   Over-mocking makes tests read like **implementation scripts** rather than specifications.
    

## Implementation

### Guidelines

-   Mock only **out-of-process** or **side-effecting** collaborators (gateways, repos, senders).
    
-   Prefer **verifying effects that matter**; don’t assert every getter/setter call.
    
-   Combine **state assertions** with **essential interaction** checks.
    
-   Keep **one reason to fail** per test (one main behavior).
    
-   Use **argument captors** to validate payload contents.
    
-   Avoid **deep stubs**; pass real value objects; keep interactions shallow.
    
-   Consider **spies** for partial verification of simple in-memory helpers.
    

### Interaction Styles

-   **Classic**: `when(...).thenReturn(...)` then `verify(mock).method(...)`.
    
-   **BDD**: `given(...).willReturn(...)` then `then(mock).should().method(...)`.
    
-   **Order**: `InOrder` to assert sequencing when it **matters**.
    
-   **Timing**: `timeout()` for async callbacks (sparingly).
    

### Anti-Patterns

-   Verifying **every** call or **exact order** without business need.
    
-   Mocking **value objects** (use real data classes).
    
-   Stubbing **what you don’t use** (test noise).
    
-   Using mocks where a **fake** would model domain rules better.
    

---

## Sample Code (Java 17, JUnit 5 + Mockito)

> Scenario: `OrderService` charges a payment gateway and sends a confirmation email.  
> We mock `PaymentGateway` and `EmailSender`, verify interactions, capture arguments, and check negative paths.

### Production code (SUT + ports)

```java
// src/main/java/example/OrderService.java
package example;

import java.math.BigDecimal;
import java.util.Objects;

public class OrderService {

  public record Order(String id, String customerEmail, BigDecimal amount, String currency) {
    public Order {
      Objects.requireNonNull(id); Objects.requireNonNull(customerEmail);
      Objects.requireNonNull(amount); Objects.requireNonNull(currency);
    }
  }

  public interface PaymentGateway {
    PaymentReceipt charge(String orderId, BigDecimal amount, String currency) throws PaymentException;
  }
  public record PaymentReceipt(String authId) { }
  public static class PaymentException extends Exception {
    public PaymentException(String msg){ super(msg); }
  }

  public interface EmailSender {
    void send(String to, String subject, String body);
  }

  private final PaymentGateway payments;
  private final EmailSender emails;

  public OrderService(PaymentGateway payments, EmailSender emails) {
    this.payments = payments; this.emails = emails;
  }

  /** Happy path: charge then email. If payment fails, throw and do not email. */
  public String placeOrder(Order order) throws PaymentException {
    var receipt = payments.charge(order.id(), order.amount(), order.currency());
    String subject = "Order " + order.id() + " confirmed";
    String body = "Thanks! Charged " + order.amount() + " " + order.currency()
                + " (auth " + receipt.authId() + ")";
    emails.send(order.customerEmail(), subject, body);
    return receipt.authId();
  }
}
```

### Tests (Mockito)

```java
// src/test/java/example/OrderServiceTest.java
package example;

import example.OrderService.*;
import org.junit.jupiter.api.*;
import org.mockito.*;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.mockito.BDDMockito.*;

class OrderServiceTest {

  @Mock PaymentGateway payments;
  @Mock EmailSender emails;

  OrderService service;

  @BeforeEach
  void init() {
    MockitoAnnotations.openMocks(this);
    service = new OrderService(payments, emails);
  }

  @Test
  void charges_gateway_and_sends_confirmation_email() throws Exception {
    // Given
    Order o = new Order("ORD-1", "alice@example.com", new BigDecimal("19.90"), "EUR");
    given(payments.charge(o.id(), o.amount(), o.currency()))
        .willReturn(new PaymentReceipt("AUTH-123456"));

    // When
    String authId = service.placeOrder(o);

    // Then (interaction verification)
    then(payments).should(times(1)).charge(o.id(), o.amount(), "EUR");
    ArgumentCaptor<String> to = ArgumentCaptor.forClass(String.class);
    ArgumentCaptor<String> subject = ArgumentCaptor.forClass(String.class);
    ArgumentCaptor<String> body = ArgumentCaptor.forClass(String.class);
    then(emails).should().send(to.capture(), subject.capture(), body.capture());
    then(emails).shouldHaveNoMoreInteractions();

    assertEquals("alice@example.com", to.getValue());
    assertTrue(subject.getValue().contains("ORD-1"));
    assertTrue(body.getValue().contains("AUTH-123456"));
    assertEquals("AUTH-123456", authId);
  }

  @Test
  void does_not_send_email_if_payment_fails() throws Exception {
    // Given
    Order o = new Order("ORD-2", "bob@example.com", new BigDecimal("49.99"), "EUR");
    willThrow(new PaymentException("card declined"))
        .given(payments).charge(o.id(), o.amount(), o.currency());

    // When
    PaymentException ex = assertThrows(PaymentException.class, () -> service.placeOrder(o));

    // Then
    assertTrue(ex.getMessage().contains("declined"));
    // verify no email sent on failure
    then(emails).shouldHaveNoInteractions();
  }

  @Test
  void verifies_call_order_when_it_matters() throws Exception {
    // Given
    Order o = new Order("ORD-3", "carol@example.com", new BigDecimal("5.00"), "EUR");
    given(payments.charge(any(), any(), any()))
        .willReturn(new PaymentReceipt("AUTH-XYZ"));

    // When
    service.placeOrder(o);

    // Then: ensure payment happens BEFORE email (business-critical sequencing)
    InOrder inOrder = inOrder(payments, emails);
    inOrder.verify(payments).charge(eq("ORD-3"), eq(new BigDecimal("5.00")), eq("EUR"));
    inOrder.verify(emails).send(eq("carol@example.com"), contains("ORD-3"), contains("AUTH-XYZ"));
    inOrder.verifyNoMoreInteractions();
  }
}
```

### Optional: Manual “mock” (hand-rolled) when avoiding frameworks

```java
// A minimal hand-rolled mock with recording & programmable response.
class RecordingPaymentGateway implements OrderService.PaymentGateway {
  static final class Call { final String orderId; final BigDecimal amount; final String currency;
    Call(String id, BigDecimal amt, String cur){ orderId=id; amount=amt; currency=cur; } }
  final java.util.List<Call> calls = new java.util.ArrayList<>();
  String nextAuthId = "AUTH-DEFAULT";
  OrderService.PaymentException toThrow = null;

  @Override public OrderService.PaymentReceipt charge(String orderId, BigDecimal amount, String currency)
      throws OrderService.PaymentException {
    calls.add(new Call(orderId, amount, currency));
    if (toThrow != null) throw toThrow;
    return new OrderService.PaymentReceipt(nextAuthId);
  }
}
```

Use it in a test to assert the same behaviors without Mockito; this helps in environments where external libs are undesirable.

---

## Known Uses

-   Service layer tests: ensure **gateways** (payments, shipping, email, SMS) are invoked correctly.
    
-   Domain workflows: assert that **events** are published with correct payloads.
    
-   Retry/fallback logic: mock collaborator to **fail first, succeed later**, verifying retry policy.
    
-   UI/API controllers: verify they call **application services** with translated arguments.
    

## Related Patterns

-   **Stub:** returns canned data but **no interaction verification**.
    
-   **Fake:** simplified working implementation (e.g., in-memory repo).
    
-   **Spy:** partial mock/real object that **records** calls (verify plus real behavior).
    
-   **Contract Testing:** verifies **provider vs. consumer** schema/behavior across repos.
    
-   **Integration Test:** uses **real adapters** (DB/HTTP) instead of mocks.
    
-   **Given–When–Then:** structural style often used with mocks to keep tests readable.
    

---

## Implementation Tips

-   Mock **outbound** dependencies (email, HTTP clients, repos), not your **domain model**.
    
-   Verify **what matters**: key method(s), argument content, and essential order—avoid incidental details.
    
-   Prefer **argument captors** for payload assertions over fragile string equals.
    
-   Keep **one When** per test; split scenarios rather than stacking verifications.
    
-   Resist **deep stubs** and **partial mocks** unless necessary; they often signal design smells.
    
-   Balance your suite: unit tests with mocks for **logic**, plus integration/E2E tests for **real adapters** and flows.

