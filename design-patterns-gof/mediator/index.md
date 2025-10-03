
# Mediator — GoF Behavioral Pattern

## Pattern Name and Classification

**Name:** Mediator  
**Category:** Behavioral design pattern

## Intent

Define an object that **encapsulates how a set of objects interact**, promoting **loose coupling** by keeping objects from referring to each other explicitly and letting you vary their interaction independently.

## Also Known As

Controller (in some UI contexts), Intermediary, Hub

## Motivation (Forces)

-   Many objects (widgets, services, modules) need to **coordinate**; letting them call each other directly creates a **spaghetti of dependencies**.

-   You want each object to focus on its **local responsibility**, not the choreography of others.

-   Interaction rules change more often than the objects themselves; you want to **modify behavior in one place**.

-   You need **runtime configuration** of who talks to whom (feature flags, A/B tests) without rewriting components.


## Applicability

Use Mediator when:

-   A set of objects communicates in **complex, well-defined but changing ways**.

-   Reusing an object is hard because it **knows too much** about its peers.

-   You want to **centralize** interaction logic (validation, enable/disable, visibility, orchestration).

-   You need **independent testing** of components by mocking the mediator.


## Structure

-   **Mediator** — defines the protocol for colleague communication (`changed(...)`, `notify(...)`, etc.).

-   **ConcreteMediator** — implements coordination logic and holds references to colleagues.

-   **Colleague** — base or interface for participants; **delegates** interaction to the mediator and stays decoupled from other colleagues.

-   **ConcreteColleague** — concrete participants (widgets/modules) that notify the mediator of state changes.


```lua
+-------------------+
          |     Mediator      |  orchestrates interactions
          +---------+---------+
                    ^
                    |
         +----------+-----------+
         |   ConcreteMediator   |
         +----------+-----------+
                    ^
        +-----------+-----------+------------------+
        |           |           |                  |
+---------------+ +---------------+         +--------------+
| Colleague A   | | Colleague B   |  ...    | Colleague N  |
+---------------+ +---------------+         +--------------+
     |   ^              |   ^                       |   ^
     +---+  (notify)    +---+         (no direct refs to each other)
```

## Participants

-   **Mediator**: common interface for coordination.

-   **ConcreteMediator**: knows and manages colleagues, applies rules, sequences actions.

-   **Colleague**: base contract to attach a mediator and to notify it on changes.

-   **ConcreteColleague**: domain-specific components; on change, they **call the mediator** instead of other colleagues.


## Collaboration

-   A colleague changes state → **notifies mediator**.

-   Mediator inspects current state and **issues commands** to colleagues to keep the system consistent.

-   Colleagues **do not** call each other; they only call the mediator and expose local setters/getters.


## Consequences

**Benefits**

-   **Reduced coupling** among colleagues; easier reuse and testing.

-   **Centralized interaction logic**; changes localized to the mediator.

-   Enables **different policies** via alternative mediators.


**Liabilities**

-   Mediator can become a **God object** if it grows unchecked.

-   Debugging might shift complexity to the mediator’s logic.

-   Overuse can **over-abstract** simple interactions.


## Implementation

-   Keep colleagues **dumb**: they report events (`changed(this)`) and expose minimal setters/getters.

-   Decide on a notification style:

    -   **Pull**: `changed(sender)`; mediator queries sender and others.

    -   **Push**: `notify(event, payload)`; sender includes event data.

-   Use **small, specialized mediators** per dialog/feature instead of one global mediator.

-   For extensibility, use **interfaces** for colleagues; the mediator can work with any implementation.

-   In concurrent settings, keep mediation **stateless** or synchronize access; avoid long-running work inside the mediator.

-   Don’t confuse Mediator with **Observer/Event Bus**:

    -   Observer is broadcast with **no central policy**.

    -   Mediator **owns the policy** and often does targeted coordination.


---

## Sample Code (Java)

**Scenario:** A checkout form’s widgets coordinate via a mediator.  
Rules:

-   Toggling **“Ship to billing address”** disables shipping fields and mirrors billing values.

-   Selecting **payment method** toggles card fields.

-   **Place Order** is enabled only when the combination of inputs is valid.


```java
import java.util.*;
import java.util.regex.Pattern;

/* ===== Contracts ===== */

interface Mediator {
    void changed(Component c);
}

interface Component {
    void setMediator(Mediator m);
    String name();
}

/* ===== Concrete Components (no direct coupling among them) ===== */

class TextField implements Component {
    private Mediator mediator;
    private final String name;
    private String text = "";
    private boolean enabled = true;

    TextField(String name) { this.name = name; }

    public void setText(String t) { this.text = t != null ? t : ""; if (mediator != null) mediator.changed(this); }
    public String getText() { return text; }

    public void setEnabled(boolean e) { this.enabled = e; }
    public boolean isEnabled() { return enabled; }

    @Override public void setMediator(Mediator m) { this.mediator = m; }
    @Override public String name() { return name; }

    @Override public String toString() { return name + "='" + text + "' " + (enabled ? "[EN]" : "[DIS]"); }
}

class Checkbox implements Component {
    private Mediator mediator;
    private final String name;
    private boolean checked;

    Checkbox(String name) { this.name = name; }

    public void toggle() { this.checked = !this.checked; if (mediator != null) mediator.changed(this); }
    public void setChecked(boolean c) { this.checked = c; if (mediator != null) mediator.changed(this); }
    public boolean isChecked() { return checked; }

    @Override public void setMediator(Mediator m) { this.mediator = m; }
    @Override public String name() { return name; }

    @Override public String toString() { return name + "=" + checked; }
}

enum PaymentMethod { CARD, PAYPAL }

class Select implements Component {
    private Mediator mediator;
    private final String name;
    private PaymentMethod value = PaymentMethod.CARD;

    Select(String name) { this.name = name; }

    public void set(PaymentMethod v) { this.value = v; if (mediator != null) mediator.changed(this); }
    public PaymentMethod get() { return value; }

    @Override public void setMediator(Mediator m) { this.mediator = m; }
    @Override public String name() { return name; }

    @Override public String toString() { return name + "=" + value; }
}

class Button implements Component {
    private Mediator mediator;
    private final String name;
    private boolean enabled = false;

    Button(String name) { this.name = name; }

    public void click() {
        if (!enabled) { System.out.println(name + ": disabled"); return; }
        System.out.println(name + ": submit!");
        if (mediator != null) mediator.changed(this); // optional
    }

    public void setEnabled(boolean e) { this.enabled = e; }
    public boolean isEnabled() { return enabled; }

    @Override public void setMediator(Mediator m) { this.mediator = m; }
    @Override public String name() { return name; }

    @Override public String toString() { return name + (enabled ? "[EN]" : "[DIS]"); }
}

/* ===== Concrete Mediator: orchestrates rules ===== */

class CheckoutMediator implements Mediator {

    // Colleagues (wired once; could also be injected via constructor)
    final TextField billingStreet = new TextField("billingStreet");
    final TextField billingCity   = new TextField("billingCity");
    final TextField shippingStreet = new TextField("shippingStreet");
    final TextField shippingCity   = new TextField("shippingCity");

    final Checkbox shipToBilling = new Checkbox("shipToBilling");
    final TextField email = new TextField("email");

    final Select payment = new Select("payment");
    final TextField cardNumber = new TextField("cardNumber");
    final TextField cardCvv    = new TextField("cardCvv");

    final Button placeOrder = new Button("placeOrder");

    CheckoutMediator() {
        // attach mediator
        for (Component c : List.of(billingStreet, billingCity, shippingStreet, shippingCity,
                                   shipToBilling, email, payment, cardNumber, cardCvv, placeOrder)) {
            c.setMediator(this);
        }
        // initial policy application
        applyShippingPolicy();
        applyPaymentPolicy();
        validateForm();
    }

    @Override
    public void changed(Component c) {
        switch (c.name()) {
            case "shipToBilling" -> applyShippingPolicy();
            case "payment"       -> applyPaymentPolicy();
            case "billingStreet", "billingCity" -> {
                if (shipToBilling.isChecked()) mirrorBillingToShipping();
            }
            // any change might impact overall validity
            default -> { /* fallthrough */ }
        }
        validateForm();
        debugState(c);
    }

    /* --- Policies --- */

    private void applyShippingPolicy() {
        if (shipToBilling.isChecked()) {
            mirrorBillingToShipping();
            shippingStreet.setEnabled(false);
            shippingCity.setEnabled(false);
        } else {
            shippingStreet.setEnabled(true);
            shippingCity.setEnabled(true);
        }
    }

    private void mirrorBillingToShipping() {
        shippingStreet.setText(billingStreet.getText());
        shippingCity.setText(billingCity.getText());
    }

    private void applyPaymentPolicy() {
        boolean card = payment.get() == PaymentMethod.CARD;
        cardNumber.setEnabled(card);
        cardCvv.setEnabled(card);
        if (!card) { cardNumber.setText(""); cardCvv.setText(""); }
    }

    private void validateForm() {
        boolean emailOk = isValidEmail(email.getText());
        boolean billingOk = !billingStreet.getText().isBlank() && !billingCity.getText().isBlank();
        boolean shippingOk = shipToBilling.isChecked()
                || (!shippingStreet.getText().isBlank() && !shippingCity.getText().isBlank());
        boolean paymentOk = switch (payment.get()) {
            case PAYPAL -> true;
            case CARD -> isValidCard(cardNumber.getText()) && isValidCvv(cardCvv.getText());
        };
        placeOrder.setEnabled(emailOk && billingOk && shippingOk && paymentOk);
    }

    /* --- Tiny validators (demo) --- */

    private static final Pattern EMAIL = Pattern.compile("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$");
    private boolean isValidEmail(String s) { return EMAIL.matcher(s).matches(); }
    private boolean isValidCard(String s) { return s.replaceAll("\\s","").length() >= 12; }
    private boolean isValidCvv(String s)  { return s.chars().allMatch(Character::isDigit) && s.length() >= 3; }

    /* --- Debug helper --- */
    private void debugState(Component trigger) {
        System.out.println("Changed: " + trigger.name());
        System.out.println("  " + billingStreet);
        System.out.println("  " + billingCity);
        System.out.println("  " + shippingStreet);
        System.out.println("  " + shippingCity);
        System.out.println("  " + shipToBilling);
        System.out.println("  " + email);
        System.out.println("  " + payment);
        System.out.println("  " + cardNumber);
        System.out.println("  " + cardCvv);
        System.out.println("  " + placeOrder);
        System.out.println();
    }
}

/* ===== Demo ===== */

public class MediatorDemo {
    public static void main(String[] args) {
        CheckoutMediator ui = new CheckoutMediator();

        ui.email.setText("alice@example.com");
        ui.billingStreet.setText("Main St 1");
        ui.billingCity.setText("Wien");

        // user chooses to ship to billing -> mediator mirrors & disables shipping fields
        ui.shipToBilling.setChecked(true);

        // choose payment: CARD -> card fields enabled and required
        ui.payment.set(PaymentMethod.CARD);
        ui.cardNumber.setText("4111 1111 1111 1111");
        ui.cardCvv.setText("123");

        // try to place order
        ui.placeOrder.click();

        // switch to PayPal -> card fields disabled/cleared; still valid
        ui.payment.set(PaymentMethod.PAYPAL);
        ui.placeOrder.click();
    }
}
```

**What this demonstrates**

-   Widgets (**colleagues**) never call each other; they **notify the mediator**.

-   The **mediator** holds and applies the cross-field rules (mirroring, enabling/disabling, validation).

-   Swapping policies (e.g., different checkout rules) means replacing the **ConcreteMediator**, not the widgets.


## Known Uses

-   **UI dialogs/forms**: enabling/disabling controls, validation, visibility toggles (Swing/JavaFX/Android patterns).

-   **Air traffic control** simulators: planes (colleagues) coordinate via a tower (mediator).

-   **Chat rooms**: users send messages via a room mediator that applies filters/routing.

-   **Workflow/orchestration** inside a module: steps coordinate via a central coordinator (distinct from microservice orchestration tools but conceptually similar).

-   **Game entities**: central “director” coordinates AI/physics triggers among actors.


## Related Patterns

-   **Observer**: broadcast notifications to many listeners; Mediator **owns orchestration/policy** and targets specific colleagues.

-   **Facade**: simplifies a subsystem for clients; Mediator **coordinates peers** within a subsystem.

-   **Colleague hierarchy + Strategy**: mediator can use strategies to vary policies without changing colleagues.

-   **Command**: mediator can issue commands to colleagues; commands may carry undo/redo.

-   **State**: mediator behavior can vary with a dialog/application state machine.

-   **MVC/MVP**: a Presenter/Controller often acts as a specialized mediator for view widgets.
