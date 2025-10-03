# Replace Delegation with Inheritance — Refactoring Pattern

## Pattern Name and Classification

**Name:** Replace Delegation with Inheritance  
**Classification:** Refactoring Pattern (API Simplification / Remove Boilerplate)

## Intent

When a class delegates **most** of its behavior to a single field of another class (the *delegate*), replace that delegation with **subclassing the delegate’s type** so that forwarding methods disappear and the subclass can override or extend behavior directly.

## Also Known As

-   Collapse Wrapper to Subclass
    
-   Remove Forwarding Layer
    
-   Inherit Instead of Delegate (the inverse of “Replace Inheritance with Delegation”)
    

## Motivation (Forces)

-   **Delegation boilerplate:** The wrapper forwards dozens of methods to one object, adding maintenance cost and noise.
    
-   **Performance & clarity:** Layers of forwarding complicate stack traces and may add tiny overhead.
    
-   **Customization points:** You want to override a few operations while keeping all others as-is—subclassing offers protected hooks.
    
-   **Discoverability:** Consumers can use the subclass **as the base type**, avoiding wrapper-specific APIs.
    

Counter-forces:

-   **Fragile base class:** Inheritance tightly couples subclass to superclass internals.
    
-   **Binary compatibility & evolution:** Superclass changes can break subclasses.
    
-   **Encapsulation:** Delegation can enforce invariants or mediate access; inheritance bypasses that mediation.
    

## Applicability

Use when **all (or nearly all)** of these hold:

-   The class exists mainly to **wrap a single delegate** and forward most methods.
    
-   The delegate’s type is **meant to be extended** (non-final, protected hooks, documented extension points).
    
-   You need to **override/extend** a small subset of operations while keeping default behavior for the rest.
    
-   You can accept tighter coupling to the superclass and its evolution.
    

Avoid when:

-   The delegate type is **final** or not designed for inheritance (no hooks, unstable internals).
    
-   You need to **compose** multiple delegates (inheritance can’t model multiple sources).
    
-   The wrapper enforces **critical invariants**, security checks, or caching—inheritance could bypass them.
    
-   You’re crossing **module/service boundaries** where composition is safer (“prefer composition over inheritance”).
    

## Structure

```mathematica
Before (Delegation):
+-------------------+        delegates to        +-------------------+
| LoggingList<E>    |--------------------------->| ArrayList<E>      |
| - List<E> inner   |  add(), get(), size() ... |                   |
| + add(...) { inner.add(...) }                 |                   |
+-------------------+                            +-------------------+

After (Inheritance):
+---------------------------+
| LoggingArrayList<E>       |
| extends ArrayList<E>      |
| + add(...) { super.add... |
|   log(...) }              |
+---------------------------+
```

## Participants

-   **Subclass (New Class):** Replaces the wrapper; extends the former delegate’s type.
    
-   **Superclass (Former Delegate Type):** Provides default behavior and overridable hooks.
    
-   **Clients:** Now depend directly on the superclass type via polymorphism (the subclass *is-a* the superclass).
    

## Collaboration

-   Clients can pass the subclass anywhere the superclass is expected.
    
-   Overridden methods add behavior (logging, validation) and call `super` for the default.
    
-   Non-overridden behavior is inherited automatically—no forwarding needed.
    

## Consequences

**Benefits**

-   Eliminates forwarding **boilerplate**; smaller surface.
    
-   Natural **polymorphism**: subclass can be used wherever the base type is expected.
    
-   Simpler stack traces and potential micro-optimizations (no extra call layer).
    

**Liabilities / Trade-offs**

-   **Tight coupling** to superclass representation and lifecycle (fragile base class).
    
-   **Inheritance leaks**: public/protected members expose more than composition.
    
-   **Reduced flexibility**: only one inheritance line; hard to combine behaviors.
    
-   **LSP risks**: Overriding must preserve base class contracts.
    

## Implementation

1.  **Check Extensibility**
    
    -   Ensure the delegate’s class is not `final`, has a stable API, and is intended for extension.
        
2.  **Create Subclass**
    
    -   Make the new class extend the delegate’s type.
        
3.  **Move Enhancements**
    
    -   Copy the wrapper’s added logic into **overrides** (e.g., `add`, `remove`, `get`). Call `super` as appropriate.
        
4.  **Delete Forwarders**
    
    -   Remove delegation field and forwarding methods; rely on inherited behavior.
        
5.  **Migrate Clients**
    
    -   Replace wrapper type with the new subclass wherever constructed or referenced.
        
6.  **Re-test & Guard Contracts**
    
    -   Verify invariants and side-effects remain correct; write tests for overridden methods.
        
7.  **Document Constraints**
    
    -   Note any superclass expectations (thread-safety, mutation semantics).
        

---

## Sample Code (Java)

### Before — Delegation with boilerplate

```java
public class LoggingList<E> implements List<E> {

  private final List<E> inner;

  public LoggingList(List<E> inner) {
    this.inner = Objects.requireNonNull(inner);
  }

  @Override public boolean add(E e) {
    System.out.println("[add] " + e);
    return inner.add(e);
  }

  @Override public E get(int index) { return inner.get(index); }
  @Override public int size() { return inner.size(); }
  @Override public void clear() { inner.clear(); }
  @Override public boolean remove(Object o) { return inner.remove(o); }
  // ... dozens more forwarders ...
}
```

### After — Inheritance; override only what you customize

```java
public class LoggingArrayList<E> extends ArrayList<E> {

  public LoggingArrayList() { super(); }
  public LoggingArrayList(Collection<? extends E> c) { super(c); }
  public LoggingArrayList(int initialCapacity) { super(initialCapacity); }

  @Override
  public boolean add(E e) {
    System.out.println("[add] " + e);
    return super.add(e);
  }

  @Override
  public void add(int index, E element) {
    System.out.println("[add@" + index + "] " + element);
    super.add(index, element);
  }

  @Override
  public E remove(int index) {
    E removed = super.remove(index);
    System.out.println("[remove@" + index + "] " + removed);
    return removed;
  }
}
```

**Usage**

```java
List<String> names = new LoggingArrayList<>();
names.add("Ada");
names.add("Grace");
System.out.println(names.size()); // inherited, no forwarding layer
```

### Variant — Prefer extending an abstract base designed for inheritance

```java
public class LoggingList2<E> extends java.util.AbstractList<E> {
  private final List<E> inner = new ArrayList<>();

  @Override public E get(int index) { return inner.get(index); }
  @Override public int size() { return inner.size(); }

  @Override
  public boolean add(E e) {
    System.out.println("[add] " + e);
    return inner.add(e);
  }
}
```

*Why:* `AbstractList` exposes a **narrower** contract and fewer override points than `ArrayList`, reducing coupling.

---

## Known Uses

-   Custom collections that need small cross-cutting behavior (logging, metrics, access checks) without maintaining dozens of forwarders.
    
-   Framework extension points designed for inheritance (e.g., Spring’s `OncePerRequestFilter`, Servlet `HttpServlet`).
    
-   GUI toolkits (Swing/JavaFX) where components are commonly subclassed to tweak behavior.
    

## Related Patterns

-   **Replace Inheritance with Delegation:** The inverse; use when inheritance causes fragility or you need composition.
    
-   **Decorator:** If you want to stack behaviors at runtime, prefer composition over inheritance.
    
-   **Template Method:** Provide hooks in a base class to customize steps safely.
    
-   **Strategy:** Encapsulate the variable behavior instead of subclassing.
    
-   **Extract Superclass / Extract Interface:** If multiple classes share behavior, refactor toward shared abstractions first.
    

**Note:** Use this pattern **sparingly**. Favor **composition** by default; adopt inheritance only when the base class is explicitly designed to be extended and the benefits clearly outweigh the coupling.

