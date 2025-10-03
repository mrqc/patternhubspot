
# GoF Design Pattern — Adapter

## Pattern Name and Classification

-   **Name:** Adapter

-   **Classification:** Structural pattern (interface conversion / compatibility)


## Intent

Convert the **interface of a class** into another **interface clients expect**. Adapter lets classes work together that **couldn’t otherwise** because of incompatible interfaces—**without** changing the adaptee.

## Also Known As

-   Wrapper

-   Translator


## Motivation (Forces)

-   You want to **reuse existing code** (a library, legacy service) but its API doesn’t match your **Target** interface.

-   You can’t (or don’t want to) modify the adaptee (closed-source, shared library, stability rules).

-   Your system must be **decoupled** from third-party specifics (easier testing, swap vendors).


Trade-offs:

-   **Where to put the translation?** Centralized in an adapter vs. spread across client code.

-   **Inheritance vs. composition:** “Class adapter” uses inheritance; “object adapter” uses composition (more flexible in Java).


## Applicability

Use Adapter when:

-   You have an existing class whose interface **does not** match what you need.

-   You want to create a **drop-in replacement** for a Target while delegating to one or more Adaptees.

-   You need to **bridge old and new** APIs during migrations.


Avoid when:

-   A simple **facade** over a subsystem (not shape conversion) suffices.

-   You control both sides—prefer changing one interface over adding indirection.


## Structure

```pgsql
+------------------+       adapts       +------------------+
Client --------->|      Target      |<-------------------|     Adapter      |
   uses          +------------------+   delegates to     +---------+--------+
                         ^                                     has-a
                         |                                     |
                         |                                 +---v---+
                         |                                 |Adaptee|
                         |                                 +-------+
             (Object Adapter — via composition)

(Class Adapter — via inheritance: Adapter extends Adaptee and implements Target)
```

## Participants

-   **Target:** The interface clients expect.

-   **Adapter:** Implements Target; **translates** calls to the Adaptee.

-   **Adaptee:** Existing/legacy/3rd-party component with a different interface.

-   **Client:** Works only with Target; unaware of the Adaptee.


## Collaboration

1.  Client calls **Target** operations.

2.  **Adapter** receives the call, **converts parameters**, **delegates** to Adaptee, possibly **adapts results/exceptions**.

3.  Client stays decoupled from Adaptee details.


## Consequences

**Benefits**

-   Reuse existing components without modifying them.

-   Keeps translation **localized**; clients remain clean and stable.

-   Enables **interface normalization** (multiple adapters plug into the same Target).


**Liabilities**

-   Extra indirection; a small runtime overhead.

-   Complex translation logic can leak domain concepts into the adapter.

-   Many adapters can proliferate—document and name clearly.


## Implementation (Key Points)

-   **Object Adapter (composition):** Preferred in Java (single inheritance); can wrap **multiple** adaptees.

-   **Class Adapter (inheritance):** `Adapter extends Adaptee implements Target`; limited by single inheritance; good when you want to **override** parts of Adaptee.

-   **Two-Way Adapter:** Implement **both** interfaces when you need each side to see the other as native.

-   **Default/Pluggable Adapter:** Provide a base class with no-op methods to simplify partial implementations.

-   **Error mapping:** Normalize exceptions/retry semantics when crossing libraries.

-   **Type & unit conversion:** Names, units, nullability, threading—do the mapping **here**, not in clients.


---

## Sample Code (Java 17): Adapting a Legacy Payment Gateway to a New `PaymentProcessor` API

**Scenario**

-   New app expects a `PaymentProcessor` with `charge(Money, PaymentMethod)`.

-   Legacy library exposes `LegacyGateway.chargeCents(String cardNumber, int cents)` and throws `LegacyError`.


```java
// File: AdapterDemo.java
// Compile: javac AdapterDemo.java
// Run:     java AdapterDemo

import java.time.YearMonth;

/* ===== Target API (what clients expect) ===== */
interface PaymentProcessor {
  ChargeResult charge(Money amount, PaymentMethod method) throws PaymentException;
}

record Money(String currency, long minorUnits) { // 12.34 EUR -> ("EUR", 1234)
  static Money of(String currency, long minorUnits) { return new Money(currency, minorUnits); }
}

sealed interface PaymentMethod permits Card {
  String masked();
}
record Card(String number, YearMonth expiry, String cvc) implements PaymentMethod {
  public String masked() { return "**** **** **** " + number.substring(Math.max(0, number.length()-4)); }
}

record ChargeResult(String id, boolean approved, String message) {}

class PaymentException extends Exception {
  PaymentException(String msg, Throwable cause) { super(msg, cause); }
  PaymentException(String msg) { super(msg); }
}

/* ===== Adaptee (legacy library we cannot change) ===== */
class LegacyGateway {
  static class LegacyError extends Exception { LegacyError(String m){ super(m);} }

  // Accepts only cents and raw PAN; only supports EUR.
  public String chargeCents(String pan, int cents) throws LegacyError {
    if (!pan.matches("\\d{12,19}")) throw new LegacyError("invalid-pan");
    if (cents <= 0) throw new LegacyError("amount-must-be-positive");
    if (cents > 20_000) return "DECLINED:LIMIT"; // 200 EUR limit
    return "APPROVED:" + System.nanoTime();
  }
}

/* ===== Adapter (object adapter via composition) ===== */
class LegacyGatewayAdapter implements PaymentProcessor {
  private final LegacyGateway gateway;

  LegacyGatewayAdapter(LegacyGateway gateway) { this.gateway = gateway; }

  @Override
  public ChargeResult charge(Money amount, PaymentMethod method) throws PaymentException {
    // 1) Validate/normalize currency and method
    if (!"EUR".equals(amount.currency())) {
      throw new PaymentException("Legacy gateway supports only EUR, got " + amount.currency());
    }
    if (!(method instanceof Card card)) {
      throw new PaymentException("Legacy gateway supports only card payments");
    }

    // 2) Unit conversion: long -> int (with bounds check)
    long cents = amount.minorUnits();
    if (cents > Integer.MAX_VALUE) throw new PaymentException("amount too large for legacy API");

    // 3) Delegate & map results/errors
    try {
      String res = gateway.chargeCents(card.number(), (int)cents);
      if (res.startsWith("APPROVED:")) {
        String id = res.substring("APPROVED:".length());
        return new ChargeResult(id, true, "ok");
      } else if (res.startsWith("DECLINED:")) {
        return new ChargeResult(null, false, res.substring("DECLINED:".length()));
      } else {
        return new ChargeResult(null, false, "unknown-response");
      }
    } catch (LegacyGateway.LegacyError e) {
      // translate to domain exception
      throw new PaymentException("legacy-failure: " + e.getMessage(), e);
    }
  }
}

/* ===== Client code (talks only to PaymentProcessor) ===== */
public class AdapterDemo {
  public static void main(String[] args) throws Exception {
    PaymentProcessor processor = new LegacyGatewayAdapter(new LegacyGateway());

    var ok = processor.charge(Money.of("EUR", 12_34), new Card("4111111111111111", YearMonth.of(2027, 12), "123"));
    System.out.println("[OK] approved=" + ok.approved() + " id=" + ok.id());

    var declined = processor.charge(Money.of("EUR", 25_000), new Card("4111111111111111", YearMonth.of(2027, 12), "123"));
    System.out.println("[DECLINED] approved=" + declined.approved() + " msg=" + declined.message());

    try {
      processor.charge(Money.of("USD", 500), new Card("4111111111111111", YearMonth.of(2027, 12), "123"));
    } catch (PaymentException ex) {
      System.out.println("[ERROR] " + ex.getMessage());
    }
  }
}
```

**What to notice**

-   Client depends only on **Target** (`PaymentProcessor`).

-   The **Adapter** centralizes translation: currency check, unit conversion, exception mapping, response parsing.

-   Swapping gateways later only requires another adapter that implements `PaymentProcessor`.


> **Class Adapter variant (illustrative):**  
> `class LegacyGatewayClassAdapter extends LegacyGateway implements PaymentProcessor { ... }` — possible in Java but you **lose** the ability to extend anything else and to switch adaptees at runtime.

---

## Known Uses

-   Java I/O bridges: `InputStreamReader` (adapts `InputStream` → `Reader`), `OutputStreamWriter`.

-   Collections: `Arrays.asList(T...)` adapts array to `List`; `Collections.list(Enumeration)` adapts to `List`.

-   Logging bridges: SLF4J adapters (e.g., `jul-to-slf4j`).

-   JDBC drivers: vendor drivers adapt DB protocols to JDBC interfaces.

-   Reactive ↔ blocking bridges in frameworks (adapters between `Publisher` and callback APIs).


## Related Patterns

-   **Facade:** Simplifies a subsystem; Adapter **converts interfaces**.

-   **Bridge:** Separates abstraction from implementation; both sides evolve—Adapter is about **compatibility**.

-   **Decorator:** Adds behavior without changing interface; Adapter **changes** the interface.

-   **Proxy:** Same interface, controlled access; Adapter **different** interface.

-   **Strategy:** Interchangeable behaviors—often the **Target** role can be a strategy, with adapters supplying strategies for incompatible libraries.


---

### Practical Tips

-   Keep adapters **thin** and deterministic; no business logic.

-   **Name adapters** clearly (`XyzToAbcAdapter`) and group them by Target.

-   Map **errors & timeouts** carefully; don’t leak vendor exceptions into domain code.

-   If multiple third-party libs map to the same Target, create a **contract test** suite for adapters.

-   Consider **configuration-driven** adapter selection (DI container, service loader).
