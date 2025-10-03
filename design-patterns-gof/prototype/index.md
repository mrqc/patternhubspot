# Prototype — Creational Pattern

## Pattern Name and Classification

**Prototype (Creational):** Create new objects by cloning existing exemplar (“prototype”) instances instead of instantiating classes directly.

## Intent

Specify the kinds of objects to create using a prototypical instance, and create new objects by copying this prototype.

## Also Known As

-   Clone

-   Copy Constructor pattern (related technique, not the GoF name)


## Motivation (Forces)

-   Constructing objects is **expensive** (I/O, DB, complex graphs, validation), but **copying** an initialized instance is cheap.

-   The **exact concrete type** might be unknown at runtime (plugins, dynamically loaded types).

-   You need to **avoid coupling** to concrete classes and the `new` operator sprinkled across the codebase.

-   You want to **preserve configuration/state** while creating similar-but-independent instances.


## Applicability

Use Prototype when:

-   System should be **independent of how its products are created** and represented.

-   Classes to instantiate are specified at run time (e.g., a registry).

-   Avoiding subclass explosion in **Factories** by registering instances instead of classes.

-   You need **deep copies** of complex composites (trees, graphs).


## Structure

-   **Prototype**: declares an interface for cloning itself.

-   **ConcretePrototype**: implements cloning (shallow or deep).

-   **Client**: creates new objects by asking a prototype to clone itself.

-   **Prototype Registry (optional)**: maps keys → prototype instances for discovery at runtime.


```arduino
Client → PrototypeRegistry → Prototype (interface)
                              ↑
                    ConcretePrototypeA/B/…
```

## Participants

-   **Prototype**: `Prototype<T> { T copy(); }`

-   **ConcretePrototype**: classes providing correct copy semantics.

-   **Client**: code that requests `copy()` rather than `new`.

-   **Registry** (optional): central place to look up available prototypes.


## Collaboration

-   Client looks up a prototype (maybe via a registry) and asks it to `copy()`.

-   Each concrete prototype knows how to duplicate itself (deep or shallow as required).


## Consequences

**Pros**

-   Decouples clients from concrete classes and constructors.

-   Enables runtime addition/removal of product types (register new prototypes).

-   Efficient creation when initialization is costly.

-   Can clone **partially configured** objects for fast templating.


**Cons / Pitfalls**

-   **Cloning complexity**: deep vs shallow; object graphs; cycles.

-   Requires discipline to keep `copy()` correct as classes evolve.

-   Mutable shared state may leak if shallow copied inadvertently.

-   Can be **less clear** than explicit constructors/factories.

-   In Java, `Object.clone()` has quirky semantics (protected, `Cloneable` marker, no default deep copy).


## Implementation (Guidelines)

1.  **Prefer an explicit `copy()` method** (or copy constructors) over `Object.clone()` for clarity.

2.  Define **copy depth**: shallow vs deep. Document it!

3.  For **deep copy**, duplicate mutable fields (lists, maps, contained entities). Consider identity maps for cyclic graphs.

4.  Provide a **Prototype Registry** if types are discovered/configured at runtime.

5.  If objects are **immutable**, you may not need Prototype; reuse instances.

6.  Consider **serialization-based** copy only for tooling/tests (slower, brittle).

7.  Ensure **invariants** hold post-copy (recompute derived fields, new IDs).

8.  If prototypes are shared, they should be **thread-safe** (immutable prototype, copies mutable).

9.  For **composites**, delegate copying to children (`copy()` cascades).


---

## Sample Code (Java)

### 1) Clean `copy()` API + Registry + Deep Copy of Aggregates

```java
import java.util.*;
import java.util.function.Supplier;

interface Prototype<T> {
    T copy(); // define copy semantics explicitly
}

// Value object used inside our prototypes (mutable!)
final class Feature {
    private String name;
    private Map<String, String> attributes = new HashMap<>();

    public Feature(String name) { this.name = name; }
    public Feature(Feature other) {
        this.name = other.name;
        this.attributes = new HashMap<>(other.attributes); // deep copy map
    }
    public String getName() { return name; }
    public Map<String, String> getAttributes() { return attributes; }
}

// Concrete prototype with nested mutable state
class Product implements Prototype<Product> {
    private String sku;
    private String displayName;
    private List<Feature> features = new ArrayList<>();
    private UUID technicalId; // identity distinct per instance

    public Product(String sku, String displayName) {
        this.sku = sku;
        this.displayName = displayName;
        this.technicalId = UUID.randomUUID();
    }

    // Copy constructor (preferred for clarity)
    public Product(Product other) {
        this.sku = other.sku;
        this.displayName = other.displayName;
        this.technicalId = UUID.randomUUID(); // new identity
        this.features = new ArrayList<>(other.features.size());
        for (Feature f : other.features) {
            this.features.add(new Feature(f)); // deep copy each Feature
        }
    }

    @Override public Product copy() { return new Product(this); }

    // Fluent helpers
    public Product addFeature(Feature f) { features.add(f); return this; }
    public Product withDisplayName(String dn) { this.displayName = dn; return this; }

    // Getters
    public String getSku() { return sku; }
    public String getDisplayName() { return displayName; }
    public List<Feature> getFeatures() { return features; }
    public UUID getTechnicalId() { return technicalId; }

    @Override public String toString() {
        return "Product{" + sku + ", " + displayName + ", id=" + technicalId + ", features=" + features.size() + "}";
    }
}

// Simple runtime registry
class PrototypeRegistry<T extends Prototype<T>> {
    private final Map<String, T> prototypes = new HashMap<>();

    public void register(String key, T prototype) { prototypes.put(key, prototype); }
    public Optional<T> get(String key) { return Optional.ofNullable(prototypes.get(key)); }
    public Set<String> keys() { return prototypes.keySet(); }
}

public class PrototypeDemo {
    public static void main(String[] args) {
        // Build an exemplar
        Product baseLaptop = new Product("LAP-13", "Base 13\" Laptop")
                .addFeature(new Feature("cpu")).addFeature(new Feature("ram"));
        baseLaptop.getFeatures().get(0).getAttributes().put("model", "i7-1260P");
        baseLaptop.getFeatures().get(1).getAttributes().put("size", "16GB");

        // Registry
        PrototypeRegistry<Product> registry = new PrototypeRegistry<>();
        registry.register("laptop.base", baseLaptop);

        // Client clones and tweaks
        Product devLaptop = registry.get("laptop.base").orElseThrow().copy()
                .withDisplayName("Dev 13\" Laptop");
        devLaptop.getFeatures().get(1).getAttributes().put("size", "32GB"); // independent copy

        System.out.println(baseLaptop);
        System.out.println(devLaptop);
        // baseLaptop RAM remains 16GB -> deep copy confirmed
    }
}
```

### 2) Interop with `Cloneable` (when required)

If you must use `clone()`, encapsulate it and still expose `copy()`:

```java
class LegacyThing implements Cloneable, Prototype<LegacyThing> {
    int[] buffer;

    LegacyThing(int size) { this.buffer = new int[size]; }

    @Override protected LegacyThing clone() {
        try {
            LegacyThing c = (LegacyThing) super.clone();
            c.buffer = this.buffer.clone(); // deep copy array
            return c;
        } catch (CloneNotSupportedException e) {
            throw new AssertionError("Should not happen", e);
        }
    }

    @Override public LegacyThing copy() { return clone(); }
}
```

### 3) Serialization-based Copy (testing/tooling only)

```java
// Not for hot paths: slow, brittle to transient fields
// new ObjectMapper().readValue(objectMapper.writeValueAsBytes(obj), Obj.class);
```

---

## Known Uses

-   **Java itself**: `Object.clone()` and the `Cloneable` marker interface (though widely criticized).

-   **UI component templates**: duplicate configured widgets and tweak properties.

-   **Game engines**: spawn entities (NPCs, bullets, particle systems) from tuned prototypes.

-   **Document editors**: duplicate styled elements/frames.

-   **DI/IoC**: some containers let you register **instances** as providers (conceptually prototype-like), though Spring’s *prototype scope* is about lifecycle, not cloning.


## Related Patterns

-   **Abstract Factory / Factory Method**: create new instances via constructors; Prototype creates via copying. Registries can be used by factories to return `copy()` results.

-   **Builder**: constructs complex objects step-by-step; a prototype can serve as a **template** that a builder tweaks.

-   **Memento**: snapshots state; prototypes can restore by cloning a memento.

-   **Flyweight**: shares intrinsic state to save memory; Prototype creates **distinct** objects, often copying extrinsic/intrinsic state.


---

## Notes on Deep vs. Shallow Copy (Java)

-   **Shallow**: fields are copied by reference; mutable internals are shared → dangerous.

-   **Deep**: recursively copy **mutable** members; reuse **immutable** objects (`String`, `LocalDate`, `BigDecimal`).

-   For **graphs with cycles**, use an **identity map** during copy to avoid infinite recursion.


## Testing Your Prototype

-   Verify **independence**: mutating a copy must not affect the original.

-   Verify **invariants**: IDs, timestamps, derived caches are reset/recomputed.

-   Performance-test: ensure cloning is **cheaper** than construction on your path.
