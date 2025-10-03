# Facade — GoF Structural Pattern

## Pattern Name and Classification

**Name:** Facade  
**Category:** Structural design pattern

## Intent

Provide a **unified, high-level interface** to a set of interfaces in a subsystem, making the subsystem **easier to use**. The facade **simplifies** common tasks while keeping the underlying components available for advanced/edge cases.

## Also Known As

Wrapper (informally), Front-end, API Surface

## Motivation (Forces)

-   A subsystem exposes **many moving parts** (multiple classes, complex sequencing, error handling).

-   Clients only need a **typical scenario** (the “80% path”) without learning all internals.

-   You want to **reduce coupling**: clients depend on the facade, not on many subsystem types.

-   You want a **stable API** that can shield clients from subsystem churn (swapped vendors, refactors).


## Applicability

Use Facade when:

-   You have a **complex subsystem** that clients find hard to use correctly.

-   You want to **decouple** clients from subsystem details to lower compile-time/runtime dependencies.

-   You need a **default/typical workflow** (orchestrating calls, ordering, transactions, retries).

-   You plan to **evolve** or replace parts of the subsystem without breaking clients.


## Structure

-   **Facade** — provides a simple set of methods that implement common use cases by orchestrating subsystem objects.

-   **Subsystem Classes** — perform the actual work; remain accessible for advanced use.

-   **Clients** — use the Facade for most tasks; may still access subsystems directly if needed.


```lua
Client --> Facade --> [SubsystemA, SubsystemB, SubsystemC, ...]
             |               \        |         /
             |                \-- orchestrates --
```

## Participants

-   **Facade:** knows which subsystem classes are responsible for a request; sequences calls; handles glue logic.

-   **Subsystem Classes:** implement low-level operations; do not know about the Facade.

-   **Client:** calls the Facade for convenience and decoupling.


## Collaboration

-   Client calls a **coarse-grained** method on the Facade.

-   Facade **delegates** to multiple subsystem objects in the correct order, handling errors, conversions, logging, etc.

-   Subsystems **don’t depend** on the Facade (one-way coupling).


## Consequences

**Benefits**

-   **Simpler client code** and **reduced coupling** to internal classes.

-   A **stable API** surface that can remain constant while internals evolve.

-   Encourages **separation of concerns**: orchestration vs. domain logic.


**Liabilities**

-   Facade can become a **God object** if it grows without boundaries.

-   Over-simplification may **hide capabilities**; some clients still need to use subsystems directly.

-   If the facade is the only entry point, it can become a **bottleneck** or a single point of failure.


## Implementation

-   Keep the facade **thin**: orchestrate, don’t re-implement subsystem logic.

-   Expose **coarse-grained** methods that map to common workflows.

-   Keep subsystems **independent** of the facade (no back-references).

-   Consider **overloads** or **parameter objects** for complex inputs.

-   In DI frameworks, wire subsystems into the facade (constructor injection).

-   Version the facade **carefully**; deprecate old methods rather than breaking them.


---

## Sample Code (Java)

**Scenario:** Checkout in an e-commerce domain. Subsystems (inventory, payment, shipping, notification, fraud) are orchestrated by a `CheckoutFacade`. Clients just call one method.

```java
import java.util.*;
import java.util.concurrent.atomic.AtomicLong;

// ---------- Domain ----------
final class Money {
    private final long cents;
    private Money(long cents) { this.cents = cents; }
    public static Money of(double eur) { return new Money(Math.round(eur * 100)); }
    public Money plus(Money other) { return new Money(this.cents + other.cents); }
    public long cents() { return cents; }
    @Override public String toString() { return String.format("€%.2f", cents / 100.0); }
}

final class OrderItem {
    public final String sku;
    public final int qty;
    public final Money unitPrice;
    public OrderItem(String sku, int qty, Money unitPrice) {
        this.sku = sku; this.qty = qty; this.unitPrice = unitPrice;
    }
    public Money lineTotal() { return Money.of(unitPrice.cents() * qty / 100.0); }
}

final class Order {
    public final UUID id = UUID.randomUUID();
    public final List<OrderItem> items = new ArrayList<>();
    public final String customerEmail;
    public Order(String customerEmail, OrderItem... items) {
        this.customerEmail = customerEmail; this.items.addAll(Arrays.asList(items));
    }
    public Money total() {
        Money sum = Money.of(0);
        for (OrderItem it : items) sum = sum.plus(it.lineTotal());
        return sum;
    }
}

final class OrderConfirmation {
    public final UUID orderId;
    public final String paymentAuthId;
    public final String shipmentId;
    public final Money total;
    OrderConfirmation(UUID orderId, String paymentAuthId, String shipmentId, Money total) {
        this.orderId = orderId; this.paymentAuthId = paymentAuthId; this.shipmentId = shipmentId; this.total = total;
    }
    @Override public String toString() {
        return "OrderConfirmation{orderId=" + orderId + ", auth=" + paymentAuthId +
               ", shipment=" + shipmentId + ", total=" + total + "}";
    }
}

// ---------- Subsystems (low-level services) ----------
class InventoryService {
    private final Map<String, Integer> stock = new HashMap<>();
    public InventoryService() { stock.put("SKU-1", 10); stock.put("SKU-2", 5); stock.put("SKU-3", 0); }
    public boolean reserve(String sku, int qty) {
        int have = stock.getOrDefault(sku, 0);
        if (have < qty) return false;
        stock.put(sku, have - qty);
        return true;
    }
    public void release(String sku, int qty) { stock.put(sku, stock.getOrDefault(sku, 0) + qty); }
}

class PaymentGateway {
    private final AtomicLong seq = new AtomicLong(1000);
    public String authorize(String cardToken, Money amount) {
        if (amount.cents() <= 0) throw new IllegalArgumentException("amount <= 0");
        if (Objects.equals(cardToken, "DECLINE")) throw new RuntimeException("Payment declined");
        return "AUTH-" + seq.getAndIncrement();
    }
    public void capture(String authId) { /* capture funds */ }
    public void voidAuth(String authId) { /* void authorization */ }
}

class ShippingService {
    private final AtomicLong seq = new AtomicLong(2000);
    public String createShipment(UUID orderId, String address) {
        if (address == null || address.isBlank()) throw new IllegalArgumentException("address required");
        return "SHIP-" + seq.getAndIncrement();
    }
}

class NotificationService {
    public void sendEmail(String to, String subject, String body) {
        System.out.printf("Email to %s :: %s%n%s%n", to, subject, body);
    }
}

class FraudCheckService {
    public boolean isSuspicious(Order order) {
        return order.total().cents() > 50_000; // arbitrary rule: > €500
    }
}

// ---------- Facade ----------
class CheckoutFacade {
    private final InventoryService inventory;
    private final PaymentGateway payments;
    private final ShippingService shipping;
    private final NotificationService mailer;
    private final FraudCheckService fraud;

    public CheckoutFacade(InventoryService inventory, PaymentGateway payments,
                          ShippingService shipping, NotificationService mailer, FraudCheckService fraud) {
        this.inventory = inventory; this.payments = payments; this.shipping = shipping; this.mailer = mailer; this.fraud = fraud;
    }

    /**
     * High-level happy-path: reserve stock -> authorize payment -> create shipment -> capture & notify.
     * Facade ensures proper rollback on failure.
     */
    public OrderConfirmation placeOrder(Order order, String cardToken, String shippingAddress) {
        // 1) Fraud screen
        if (fraud.isSuspicious(order)) throw new IllegalStateException("Order flagged by fraud checks");

        // 2) Reserve all items
        List<OrderItem> reserved = new ArrayList<>();
        try {
            for (OrderItem it : order.items) {
                if (!inventory.reserve(it.sku, it.qty))
                    throw new IllegalStateException("Insufficient stock for " + it.sku);
                reserved.add(it);
            }

            // 3) Authorize payment
            String authId = payments.authorize(cardToken, order.total());

            // 4) Create shipment
            String shipmentId = shipping.createShipment(order.id, shippingAddress);

            // 5) Capture payment (commit)
            payments.capture(authId);

            // 6) Notify customer
            mailer.sendEmail(order.customerEmail, "Order confirmed " + order.id,
                    "Total: " + order.total() + "\nShipment: " + shipmentId);

            return new OrderConfirmation(order.id, authId, shipmentId, order.total());
        } catch (RuntimeException ex) {
            // best-effort rollback
            // release reservations
            for (OrderItem it : reserved) inventory.release(it.sku, it.qty);
            // if payment was authorized, void (this demo cannot know authId reliably if failure before capture)
            // In a real impl: track state across steps
            throw ex;
        }
    }
}

// ---------- Client / Demo ----------
public class FacadeDemo {
    public static void main(String[] args) {
        CheckoutFacade checkout = new CheckoutFacade(
                new InventoryService(),
                new PaymentGateway(),
                new ShippingService(),
                new NotificationService(),
                new FraudCheckService()
        );

        Order order = new Order("alice@example.com",
                new OrderItem("SKU-1", 2, Money.of(19.90)),
                new OrderItem("SKU-2", 1, Money.of(49.00)));

        OrderConfirmation conf = checkout.placeOrder(order, "CARD-OK", "Main Street 1, 1010 Vienna");
        System.out.println(conf);

        // Failure examples (the facade shields the client from subsystem details)
        try {
            Order bad = new Order("bob@example.com", new OrderItem("SKU-3", 1, Money.of(999.0))); // out of stock
            checkout.placeOrder(bad, "CARD-OK", "Somewhere 2");
        } catch (Exception e) {
            System.out.println("Expected failure: " + e.getMessage());
        }
    }
}
```

**What this shows**

-   `CheckoutFacade.placeOrder(...)` exposes a **single coarse-grained call**.

-   Internally it **sequences** calls to inventory, payments, shipping, notifications, and fraud checks.

-   Facade handles **error propagation** and **compensations** (stock release) so the client doesn’t need to.


## Known Uses

-   **JDBC helpers / ORM utilities** that wrap connection/transaction boilerplate.

-   **Media conversion** APIs that hide codec/container libraries behind a simple method.

-   **Cloud SDK aggregators** that hide multiple service calls (e.g., upload + permissions + CDN invalidation).

-   **Home-theater controllers** (classic GoF example): one button powering and configuring many devices.

-   **Complex build/deploy** steps exposed as one “deploy()” API.


## Related Patterns

-   **Adapter:** changes an interface to another; Facade **simplifies** without changing semantics.

-   **Mediator:** coordinates peer objects; differs in **intent** and often becomes the center of communication. Facade just **wraps a subsystem**.

-   **Singleton:** sometimes used to expose a single facade instance (not required).

-   **Abstract Factory:** a facade can **use** AF to obtain subsystem families.

-   **Decorator:** adds responsibilities by wrapping a single component; Facade **aggregates** many components.

-   **Proxy:** controls access to one object (remote/virtual/protection); Facade **combines** many calls into one.
