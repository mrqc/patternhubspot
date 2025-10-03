
# Composite — GoF Structural Pattern

## Pattern Name and Classification

**Name:** Composite  
**Category:** Structural design pattern

## Intent

Compose objects into **tree** structures to represent **part–whole hierarchies**. Composite lets clients treat **individual objects** and **compositions of objects** **uniformly**.

## Also Known As

Part–Whole, Object Tree, Container–Contents

## Motivation (Forces)

-   You model a hierarchy where **leaves** and **containers** should be used with the **same API** (e.g., files vs. folders, shapes vs. groups).

-   Clients shouldn’t need to `instanceof` or branch: **“just call `operation()`”** whether it’s a leaf or a composite.

-   You need to **add/remove/move** subtrees at runtime.

-   You want **recursive behavior** (e.g., computing size/price/bounds) to “just work” on any node.


## Applicability

Use Composite when:

-   Your domain is naturally a **tree** or DAG of objects.

-   Clients should **ignore differences** between single objects and compositions.

-   You need to **aggregate** results across children (sum, min/max, transform).

-   You want to **reconfigure** the structure dynamically (add/remove/reparent).


## Structure

-   **Component** — common interface for **Leaf** and **Composite**; declares operations and (optionally) child-management.

-   **Leaf** — atomic element; implements operations with no children.

-   **Composite** — node that **stores children** and implements operations by delegating/aggregating over them.

-   **Client** — uses Components uniformly.


```lua
+--------------------+
                 |     Component      |<--------------------+
                 | operation()        |                     |
                 | add()/remove()/... | (optional)          |
                 +----------+---------+                     |
                            ^                               |
                 +----------+----------+          +---------+---------+
                 |        Leaf         |          |      Composite    |
                 | operation(): base   |          | children: List<C> |
                 +---------------------+          | operation(): fold |
                                                  +-------------------+
```

## Participants

-   **Component**: defines the common protocol (business ops; possibly child ops).

-   **Leaf**: represents terminal objects; no children.

-   **Composite**: maintains children and implements operations that **iterate/aggregate** over them.

-   **Client**: manipulates the tree through `Component`.


## Collaboration

-   Clients call `operation()` on **any** `Component`.

-   For a **Leaf**, it performs its atomic behavior.

-   For a **Composite**, it typically **iterates** children and **combines** results (sum/concat/transform/short-circuit).


## Consequences

**Benefits**

-   **Uniformity**: leaves and composites share one interface → simpler client code.

-   **Extensibility**: easy to add new `Leaf` types or new `Composite` variants.

-   Enables **recursive algorithms** and **structural reconfiguration**.


**Liabilities**

-   If the Component interface includes child ops (**transparent** style), **leaves may support meaningless methods** (often throwing `UnsupportedOperationException`).

-   If you hide child ops (**safe** style), clients must **downcast** to manipulate structure.

-   **Over-generalization** can bloat the Component API; performance can suffer on very deep trees without care (stack depth, repeated traversals).


## Implementation

-   Choose **transparent** (child ops on `Component`) vs. **safe** (child ops only on `Composite`):

    -   *Transparent:* simpler client, but leafs may throw on `add/remove`.

    -   *Safe:* cleaner types, but client must know when a node is composite.

-   Prefer **composition-friendly** collections (`List`) and define **iteration order**.

-   Guard against **cycles** if your graph can be reparented (or explicitly allow DAGs and deduplicate in algorithms).

-   Consider **internal caching** (e.g., memoized totals) and **invalidations** on structural change.

-   Provide an **Iterator** or **Visitor** for complex traversals.

-   Concurrency: keep nodes **immutable** or synchronize mutations at composite level.


---

## Sample Code (Java)

**Scenario:** A product catalog where single products and bundles are priced uniformly. Bundles can contain products or other bundles and may apply a discount.

```java
// ===== Component =====
public interface CatalogComponent {
    String name();
    Money price();                // business operation
    default void print(String indent) { System.out.println(indent + name() + " = " + price()); }

    // Transparent child-management (optional)
    default void add(CatalogComponent child) { throw new UnsupportedOperationException(); }
    default void remove(CatalogComponent child) { throw new UnsupportedOperationException(); }
    default List<CatalogComponent> children() { return List.of(); }
}

// Simple Money type (value object)
final class Money {
    private final long cents;
    public Money(long cents) { this.cents = cents; }
    public static Money of(double eur) { return new Money(Math.round(eur * 100)); }
    public Money plus(Money other) { return new Money(this.cents + other.cents); }
    public Money minus(Money other) { return new Money(this.cents - other.cents); }
    public Money times(double factor) { return new Money(Math.round(cents * factor)); }
    @Override public String toString() { return String.format("€%.2f", cents / 100.0); }
}

// ===== Leaf =====
public final class Product implements CatalogComponent {
    private final String name;
    private final Money price;
    public Product(String name, Money price) { this.name = name; this.price = price; }
    @Override public String name() { return name; }
    @Override public Money price() { return price; }
}

// ===== Composite =====
public class Bundle implements CatalogComponent {
    private final String name;
    private final List<CatalogComponent> children = new ArrayList<>();
    private double discountPercent = 0.0; // e.g., 10.0 = 10%

    public Bundle(String name) { this.name = name; }

    public Bundle discount(double percent) { this.discountPercent = percent; return this; }

    @Override public String name() { return name; }

    @Override public Money price() {
        Money sum = new Money(0);
        for (CatalogComponent c : children) {
            sum = sum.plus(c.price());
        }
        if (discountPercent <= 0) return sum;
        Money discount = sum.times(discountPercent / 100.0);
        return sum.minus(discount);
    }

    @Override public void add(CatalogComponent child) { children.add(child); }

    @Override public void remove(CatalogComponent child) { children.remove(child); }

    @Override public List<CatalogComponent> children() { return Collections.unmodifiableList(children); }

    @Override public void print(String indent) {
        System.out.println(indent + name() + " (bundle, -" + discountPercent + "%) = " + price());
        for (CatalogComponent c : children) {
            c.print(indent + "  ");
        }
    }
}

// ===== Client / Demo =====
public class CompositeDemo {
    public static void main(String[] args) {
        CatalogComponent mouse = new Product("Mouse", Money.of(19.90));
        CatalogComponent keyboard = new Product("Keyboard", Money.of(49.00));
        CatalogComponent monitor = new Product("Monitor 27\"", Money.of(289.00));
        CatalogComponent warranty = new Product("Warranty 2y", Money.of(39.00));

        Bundle desktopSet = new Bundle("Desktop Set").discount(10.0);
        desktopSet.add(mouse);
        desktopSet.add(keyboard);
        desktopSet.add(monitor);

        Bundle proPack = new Bundle("Pro Pack").discount(5.0);
        proPack.add(desktopSet);
        proPack.add(warranty);

        proPack.print(""); // pretty tree print

        // Uniform use:
        List<CatalogComponent> items = List.of(mouse, desktopSet, proPack);
        Money cartTotal = items.stream().map(CatalogComponent::price)
                               .reduce(new Money(0), Money::plus);
        System.out.println("Cart total = " + cartTotal);
    }
}
```

**What the example shows**

-   `CatalogComponent` gives a **uniform** API: `price()` works for both `Product` (Leaf) and `Bundle` (Composite).

-   `Bundle` aggregates children and applies a **discount** once.

-   The **transparent** style exposes `add/remove` on the `Component`; `Product` throws `UnsupportedOperationException` by default, while `Bundle` overrides them.


### Optional: Safe Interface Variant

If you prefer not to expose child ops on `Component`, move `add/remove/children` to `Composite` only, at the cost of downcasting when building trees.

### Optional: Iteration & Visitor

For complex operations (exporting, validation), add an `accept(Visitor v)` on `Component`. The visitor centralizes algorithms without bloating `Component`.

## Known Uses

-   **GUI frameworks**: containers vs. widgets (`JComponent` trees, JavaFX `Parent`/`Node`).

-   **File systems**: directories (composite) and files (leaf) with uniform operations (size, delete).

-   **Graphics editors**: groups of shapes vs. single shapes (move/resize/paint).

-   **Scene graphs** in game engines and renderers.

-   **Organization charts**: departments (composite) and employees (leaf).

-   **ASTs** (abstract syntax trees) in compilers/interpreters.


## Related Patterns

-   **Iterator**: traverse composites uniformly.

-   **Visitor**: externalize operations over the tree without polluting `Component`.

-   **Decorator**: adds responsibilities to a single object; Composite **contains** children instead.

-   **Flyweight**: share intrinsic state among many leaves in large trees.

-   **Builder**: assemble complex composite structures step-by-step.

-   **Prototype**: clone subtrees.
