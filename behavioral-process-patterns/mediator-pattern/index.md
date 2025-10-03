# Mediator — Behavioral / Process Pattern

## Pattern Name and Classification

**Mediator** — *Behavioral / Process* pattern that **centralizes communication** between collaborating objects (colleagues) so they don’t reference each other directly.

---

## Intent

Encapsulate object interactions in a **mediator** to reduce **coupling**, simplify **dependencies**, and make collaboration **easier to reason about, extend, and test**.

---

## Also Known As

-   **Controller** (in the sense of coordinating collaborators)

-   **Hub-and-Spoke**

-   **Dialog/Widget Mediator** (classic UI case)


---

## Motivation (Forces)

-   Many objects need to **coordinate**, but direct references create a **mesh** of dependencies (spaghetti).

-   Changes to one component ripple across others; testing in isolation becomes hard.

-   You want to **add/replace** participants without editing every other participant.


**Trade-offs**

-   Central mediator can become a **god object** if it accumulates too much logic—factor by feature or domain flow.

-   Slight indirection vs. direct calls; keep mediator **cohesive** and **focused**.


---

## Applicability

Use the Mediator when:

-   Multiple components interact in **non-trivial** ways (e.g., UI widgets, workflow steps, domain services in a use case).

-   You want **loose coupling** and **single place** to encode collaboration rules.

-   Interactions change more often than the components themselves.


Avoid when:

-   Interactions are **simple** and stable; direct calls or **Observer** suffice.

-   You already use an **event bus** for broadcast-style decoupling (different trade-off).


---

## Structure

```css
Colleague A ─┐
 Colleague B ─┼──>  Mediator  ─── coordinates → invokes colleagues
 Colleague C ─┘        ^
                       └──── receives notifications from colleagues
```

-   Colleagues only know the **Mediator**.

-   Mediator decides **who talks to whom, when, and how**.


---

## Participants

-   **Mediator**: Interface/abstract type that defines collaboration operations.

-   **ConcreteMediator**: Implements coordination logic.

-   **Colleagues**: Components that send **notifications** to the mediator and receive **commands** from it.

-   (Optional) **Events/DTOs**: Messages to keep boundaries clean.


---

## Collaboration

1.  A colleague raises an **event/notification** to the mediator.

2.  Mediator applies **rules** and calls other colleagues’ methods; may update state or trigger sequences.

3.  Colleagues remain **ignorant** of each other; only the mediator encodes coupling.


---

## Consequences

**Benefits**

-   **Loose coupling**; colleagues don’t depend on each other.

-   Collaboration rules live in **one place** → easier to change/test.

-   Enables **swapping colleagues** (test doubles, different implementations).


**Liabilities**

-   Risk of **overgrown mediator** (split by feature/use case).

-   Indirection may obscure simple flows if overused.


---

## Implementation (Key Points)

-   Keep colleagues **dumb** about others; expose **intents** to the mediator (e.g., `userRequestedCheckout()` rather than `callXThenY`).

-   Provide a **clear mediator API** (imperative methods) or use **typed notifications** (small event objects).

-   **Unit test** mediator logic in isolation with fake colleagues.

-   Consider **MediatR-style** request/response for backends; for broadcast needs, consider **Observer/Event Bus** (complementary, not identical).

-   Split mediators **per feature/use case** to avoid god objects.


---

## Sample Code (Java 17) — Checkout Flow Mediator

Scenario: A checkout involves **Cart**, **Payment**, and **Inventory**. The **CheckoutMediator** coordinates:

-   When user clicks “Pay”, mediator validates cart → reserves stock → charges payment → confirms order or rolls back.


```java
// ===== Mediator API =====
interface CheckoutMediator {
  void onUserPressedPay();
  void onCartChanged();               // e.g., item added/removed
  void cancelOrder(String reason);
}

// ===== Colleague APIs =====
interface CartService {
  boolean isValid();
  int totalCents();
  java.util.List<String> items();     // SKUs
}

interface InventoryService {
  boolean reserve(java.util.List<String> skus);
  void release(java.util.List<String> skus);
}

record ChargeResult(boolean ok, String paymentId, String failureReason) {}

interface PaymentService {
  ChargeResult charge(int amountCents);
  void refund(String paymentId);
}

interface OrderService {
  String create(java.util.List<String> skus, int totalCents, String paymentId);
}

// ===== Concrete Colleagues (toy impls) =====
class InMemoryCart implements CartService {
  private final java.util.List<String> skus = new java.util.ArrayList<>();
  void add(String sku) { skus.add(sku); }
  @Override public boolean isValid() { return !skus.isEmpty(); }
  @Override public int totalCents() { return 2599; } // pretend
  @Override public java.util.List<String> items() { return java.util.List.copyOf(skus); }
}

class FakeInventory implements InventoryService {
  private final java.util.Set<String> reserved = new java.util.HashSet<>();
  @Override public boolean reserve(java.util.List<String> skus) {
    if (skus.isEmpty()) return false;
    reserved.addAll(skus); return true;
  }
  @Override public void release(java.util.List<String> skus) { reserved.removeAll(skus); }
}

class FakePayment implements PaymentService {
  @Override public ChargeResult charge(int amountCents) {
    if (amountCents <= 0) return new ChargeResult(false, null, "invalid-amount");
    return new ChargeResult(true, "pay_"+amountCents, null);
  }
  @Override public void refund(String paymentId) { System.out.println("Refunded " + paymentId); }
}

class FakeOrders implements OrderService {
  @Override public String create(java.util.List<String> skus, int totalCents, String paymentId) {
    return "ord_" + Math.abs((skus.toString()+paymentId).hashCode());
  }
}

// ===== Concrete Mediator =====
class CheckoutMediatorImpl implements CheckoutMediator {
  private final CartService cart;
  private final InventoryService inventory;
  private final PaymentService payment;
  private final OrderService orders;

  CheckoutMediatorImpl(CartService cart, InventoryService inventory, PaymentService payment, OrderService orders) {
    this.cart = cart; this.inventory = inventory; this.payment = payment; this.orders = orders;
  }

  @Override
  public void onUserPressedPay() {
    System.out.println("[Mediator] Pay clicked");
    if (!cart.isValid()) { cancelOrder("cart-invalid"); return; }

    var items = cart.items();
    boolean reserved = inventory.reserve(items);
    if (!reserved) { cancelOrder("stock-unavailable"); return; }

    ChargeResult charge = payment.charge(cart.totalCents());
    if (!charge.ok()) {
      inventory.release(items);
      cancelOrder("payment-failed:"+charge.failureReason());
      return;
    }

    String orderId = orders.create(items, cart.totalCents(), charge.paymentId());
    System.out.println("[Mediator] Order confirmed: " + orderId + " (payment="+charge.paymentId()+")");
  }

  @Override public void onCartChanged() {
    System.out.println("[Mediator] Cart changed; could re-validate totals, enable/disable Pay, etc.");
  }

  @Override public void cancelOrder(String reason) {
    System.out.println("[Mediator] Checkout cancelled: " + reason);
  }
}

// ===== Demo =====
public class MediatorDemo {
  public static void main(String[] args) {
    var cart = new InMemoryCart();
    cart.add("sku-1"); cart.add("sku-2");

    var mediator = new CheckoutMediatorImpl(
        cart, new FakeInventory(), new FakePayment(), new FakeOrders()
    );

    mediator.onCartChanged();
    mediator.onUserPressedPay(); // orchestrates reserve → charge → create order
  }
}
```

### Notes & Variations

-   You can make the mediator **asynchronous** (return `CompletionStage<Void>`), add **retries**, and emit **domain events** after success/failure.

-   For larger systems, use **one mediator per use case** (e.g., `CheckoutMediator`, `RefundMediator`) to keep them cohesive.

-   Contrast with **Observer/Event Bus**: Mediator is **targeted coordination**; Event Bus is **broadcast**. They can coexist (mediator emits events).


---

## Known Uses

-   GUI frameworks: coordinating **dialog widgets** (enabling/disabling, validation).

-   **Application services** in DDD acting as mediators among domain services.

-   Libraries like **MediatR** (.NET) / *mediator pipelines* in backends.

-   Integrations where a **use-case orchestrator** calls multiple subsystems (payments, inventory, notifications).


---

## Related Patterns

-   **Facade** — simplifies a subsystem; Mediator **coordinates peers**.

-   **Observer** — broadcast notifications; Mediator **directs** specific interactions.

-   **Command** — commands can be sent to a mediator to drive flows.

-   **Chain of Responsibility** — sequential processing vs. mediator’s directed coordination.

-   **Saga / Process Manager** — cross-service mediator for long-running workflows (with persistence and compensations).
