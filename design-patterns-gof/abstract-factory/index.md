
# GoF Design Pattern — Abstract Factory

## Pattern Name and Classification

-   **Name:** Abstract Factory

-   **Classification:** Creational pattern (object creation families)


## Intent

Provide an interface for **creating families of related or dependent objects** without specifying their **concrete classes**. Clients work against **abstract products** from a **factory** that can be swapped wholesale.

## Also Known As

-   Kit

-   Family of Products


## Motivation (Forces)

-   You need to support **multiple variants** (e.g., Windows vs. macOS UI, SQL vs. NoSQL persistence) where products must **match** within a family.

-   Avoid **scattered conditionals** (`if (os==WIN) new WinButton() else new MacButton()`) across the codebase.

-   Keep **construction responsibilities** centralized; allow switching product families at **configuration** time.

-   Promote **consistency** and **interoperability** among related objects (e.g., same look & feel).


## Applicability

Use Abstract Factory when:

-   The system must be **independent** of how its products are created/composed.

-   You want to enforce **compatible sets** of products.

-   You want to expose only **interfaces** for products, not concretes.

-   You need to **swap families** (A/B testing, theming, platform ports) at startup or runtime.


Avoid when:

-   There’s only **one product** or no coherent families—simple factory/builder may suffice.

-   You need fine-grained, parameterized construction of **a single complex object**—prefer **Builder**.


## Structure

```lua
+-------------------+           +------------------+
Client -->|  AbstractFactory  |<>-------> |  AbstractProductA|
          +---------+---------+ \         +------------------+
                    |           \-------> |  AbstractProductB|
         +----------+----------+          +------------------+
         |                     |
 +---------------+     +---------------+
 | ConcreteFactory1|    | ConcreteFactory2|
 +--+-----------+--+    +--+-----------+--+
    |           |          |           |
 +--v--+    +---v-+     +--v--+    +---v-+
 |ProdA1|   |ProdB1|    |ProdA2|   |ProdB2|
 +-----+    +-----+     +-----+    +-----+
```

## Participants

-   **AbstractFactory:** Declares creation methods for each abstract product.

-   **ConcreteFactory:** Implements creation methods to return a **consistent family** of products.

-   **AbstractProduct:** Interface(s) for product types.

-   **ConcreteProduct:** Concrete implementations for a particular family.

-   **Client:** Uses only **abstract** factory/product types.


## Collaboration

-   Client receives a **factory** (via DI/config) and requests products through it.

-   Concrete factory returns products that are **designed to work together**.

-   Client remains **agnostic** to concrete classes.


## Consequences

**Benefits**

-   **Isolates concrete classes**; client code depends on abstractions.

-   Ensures **product consistency** across a family.

-   Simplifies switching families (configuration toggles).

-   Centralizes construction logic (testability, single responsibility).


**Liabilities**

-   **Class explosion:** Many factories/products for many variants.

-   Harder to support a **new product type** (must change every factory) vs. Factory Method.

-   Overkill when there isn’t a real concept of **families**.


## Implementation (Key Points)

-   Represent each product type as its **own interface**.

-   Factories typically returned via **DI container** or a **factory provider/registry**.

-   Consider **factory of factories** if you have many families.

-   If families grow often but product types are stable → Abstract Factory works well. If **new product types** are added often, consider **Prototype/Service Locator** hybrids or **Factory Method** per product type.

-   Optionally make factories **immutable/singletons** when stateless.


---

## Sample Code (Java 17): Cross-platform UI Toolkit

> Families: **Windows** and **macOS**  
> Products: `Button`, `Checkbox`  
> Client uses only the abstract interfaces and the abstract factory.

```java
// File: AbstractFactoryDemo.java
// Compile: javac AbstractFactoryDemo.java
// Run:     java AbstractFactoryDemo

interface Button {
  void render();
}
interface Checkbox {
  void toggle();
  boolean checked();
}

/* ---------- Abstract Factory ---------- */
interface UiFactory {
  Button createButton();
  Checkbox createCheckbox();
}

/* ---------- Concrete Products: Windows ---------- */
class WinButton implements Button {
  public void render() { System.out.println("[Win] Rendering button with Fluent style"); }
}
class WinCheckbox implements Checkbox {
  private boolean state;
  public void toggle() { state = !state; System.out.println("[Win] Checkbox -> " + state); }
  public boolean checked() { return state; }
}

/* ---------- Concrete Products: macOS ---------- */
class MacButton implements Button {
  public void render() { System.out.println("[Mac] Rendering button with Aqua style"); }
}
class MacCheckbox implements Checkbox {
  private boolean state;
  public void toggle() { state = !state; System.out.println("[Mac] Checkbox -> " + state); }
  public boolean checked() { return state; }
}

/* ---------- Concrete Factories ---------- */
class WinUiFactory implements UiFactory {
  public Button createButton() { return new WinButton(); }
  public Checkbox createCheckbox() { return new WinCheckbox(); }
}
class MacUiFactory implements UiFactory {
  public Button createButton() { return new MacButton(); }
  public Checkbox createCheckbox() { return new MacCheckbox(); }
}

/* ---------- Client (depends only on abstractions) ---------- */
class SettingsScreen {
  private final Button btnSave;
  private final Checkbox cbAutosave;

  SettingsScreen(UiFactory factory) {
    this.btnSave = factory.createButton();
    this.cbAutosave = factory.createCheckbox();
  }

  void draw() {
    btnSave.render();
    cbAutosave.toggle();
  }
}

/* ---------- Bootstrap / Factory selection ---------- */
public class AbstractFactoryDemo {
  public static void main(String[] args) {
    UiFactory factory = selectFactory(System.getProperty("os.name", "generic"));
    SettingsScreen screen = new SettingsScreen(factory);
    screen.draw();
  }

  static UiFactory selectFactory(String osName) {
    String os = osName.toLowerCase();
    if (os.contains("win")) return new WinUiFactory();
    if (os.contains("mac")) return new MacUiFactory();
    // default / stub: could throw or return a themed factory
    return new WinUiFactory();
  }
}
```

**Notes**

-   To add a **new family** (e.g., Linux GTK): implement `GtkButton`, `GtkCheckbox`, and `GtkUiFactory`—no client changes.

-   To add a **new product type** (e.g., `Slider`), you must extend `UiFactory` and **all** concrete factories—typical Abstract Factory trade-off.


---

## Known Uses

-   GUI toolkits (AWT/Swing look-and-feel, Qt styles).

-   Database access layers (different SQL dialects/drivers with a unified API).

-   Cloud provider adapters (AWS/Azure/GCP families of services).

-   Theming/branding systems (light/dark/high-contrast component families).

-   Serialization stacks (JSON/XML/Proto families of readers/writers).


## Related Patterns

-   **Factory Method:** Often used **inside** Abstract Factory to create each product.

-   **Builder:** Constructs **one** complex object step-by-step (not families).

-   **Prototype:** Clone preconfigured instances instead of constructing new.

-   **Bridge:** Decouple abstraction from implementation; can combine with Abstract Factory to supply implementors.

-   **Service Locator / DI Container:** Practical ways to provide the factory to clients.


---

### Practical Tips

-   Keep factories **stateless**; inject configuration via constructor if needed.

-   Consider **enum-based** or **registry-based** factory selectors for runtime switching.

-   For testing, pass a **TestUiFactory** to create fakes/mocks.

-   If product families share cross-cutting concerns (logging/metrics), wrap creations with **decorators** inside the concrete factory.

-   Document **compatibility constraints** within a family to prevent mixing (e.g., Windows button must pair with Windows checkbox).
