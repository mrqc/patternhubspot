# Replace Inheritance with Delegation — Refactoring Pattern

## Pattern Name and Classification

**Name:** Replace Inheritance with Delegation  
**Classification:** Refactoring Pattern (Decoupling / Composition over Inheritance)

## Intent

Remove an inappropriate “is-a” relationship by **stopping subclassing** a framework/base class and instead **wrapping** it as an internal field. Forward only the operations you truly need and add behavior in the wrapper, reducing coupling to fragile superclasses and enabling safer evolution and composition.

## Also Known As

-   Prefer Composition over Inheritance
    
-   Replace Subclassing with Wrapper / Adapter
    
-   Deinherit / Decouple from Base Class
    

## Motivation (Forces)

-   **Fragile base class:** Superclass changes break subclasses; protected internals tempt tight coupling.
    
-   **Leaky inheritance:** Subclass inherits unwanted API surface and semantics (equals/hashCode, serialization, mutability).
    
-   **Multiple behaviors:** Need to combine concerns (logging + caching) — single inheritance can’t compose.
    
-   **Testability & substitutability:** You want to inject a different provider at runtime (e.g., `List` to `CopyOnWriteArrayList`).
    
-   **Security/invariants:** You must enforce pre/postconditions; inheritance can bypass the intended seams.
    

## Applicability

Apply when:

-   Your subclass **overrides few methods** and mostly reuses base behavior.
    
-   You need to **stack behaviors** (decorator-style) or swap the underlying implementation.
    
-   The superclass is **not designed for extension** (final methods, undocumented hooks).
    
-   Inheritance exposes **too much API** or violates domain rules (wrong equality, iteration order, lifecycle).
    

Avoid or defer when:

-   The superclass is **explicitly designed for inheritance** with stable hooks and you need most of its API.
    
-   Performance constraints make extra indirection unacceptable (rare; measure first).
    
-   You must be **recognized as the base type** for third-party APIs without adapter seams.
    

## Structure

```typescript
Before (Inheritance):
+--------------------------+
| NotifyingArrayList<E>    |  extends ArrayList<E>
|  + add(...) { ... }      |
|  + remove(...) { ... }   |
|  // inherits all API     |
+--------------------------+

After (Delegation / Wrapper):
+----------------------------+
| NotifyingList<E>           | implements List<E>
|  - List<E> inner           |  (Any List impl)
|  + add(...) { ...; inner } |
|  + remove(...) { ...; }    |
|  + of(…) factory           |
+----------------------------+
```

## Participants

-   **Wrapper / Delegate Owner:** New class that holds a reference to the real worker and exposes only the needed API.
    
-   **Delegate:** The composed object (e.g., `List<E>`, `HttpClient`) providing core functionality.
    
-   **Clients:** Use the wrapper’s narrower, intention-revealing API (optionally still the same interface).
    
-   **Optional Listeners/Policies:** Plug-in behaviors that the wrapper coordinates.
    

## Collaboration

-   Wrapper validates/augments calls, then **delegates** to the inner object.
    
-   The underlying implementation can be **swapped** (factories/DI) without touching clients.
    
-   Multiple wrappers can **compose** (metrics → caching → retry).
    

## Consequences

**Benefits**

-   **Reduced coupling** to framework internals; safer upgrades.
    
-   **Smaller surface area** (expose only what you need).
    
-   **Composable** behaviors (decorator chains).
    
-   Improved **testability** (inject fakes/mocks of the delegate).
    
-   Stronger **invariants** (central validation/logging/retry).
    

**Liabilities / Trade-offs**

-   A bit of **boilerplate** to forward methods (tools can generate).
    
-   Potential **indirection overhead** (usually negligible).
    
-   If you still need the full interface (e.g., `List`), you may end up forwarding many methods—prefer narrower ports when possible.
    

## Implementation

1.  **Identify the leakage:** List all places where inheritance forces you to inherit/override more than needed.
    
2.  **Create the Wrapper:** Add a field of the former superclass type (ideally an **interface** like `List`, `Map`, `HttpClient`).
    
3.  **Expose a Minimal API:** Implement exactly the methods clients need (or the same interface if required).
    
4.  **Forward Intentionally:** Delegate to the inner object; add validation, logging, retries, metrics as needed.
    
5.  **Construct via Factory/DI:** Provide constructors/factories to choose the inner implementation.
    
6.  **Migrate Call Sites:** Replace `new Subclass()` with wrapper factories; fix types if you narrowed the surface.
    
7.  **Remove Subclass:** Delete the old inheritance; re-run tests and contract tests.
    
8.  **Compose Further:** If more behaviors are needed, layer wrappers (decorators) or inject policies.
    

---

## Sample Code (Java)

### Before — Inheriting from a concrete collection

```java
// Inherits a huge API and is tightly coupled to ArrayList internals.
public class NotifyingArrayList<E> extends ArrayList<E> {

  private final Consumer<E> onAdd;

  public NotifyingArrayList(Consumer<E> onAdd) {
    this.onAdd = onAdd;
  }

  @Override
  public boolean add(E e) {
    boolean ok = super.add(e);
    if (ok) onAdd.accept(e);
    return ok;
  }

  @Override
  public void add(int index, E element) {
    super.add(index, element);
    onAdd.accept(element);
  }
  // inherits everything else whether we want it or not
}
```

### After — Delegate to any `List<E>` (composition)

```java
import java.util.*;
import java.util.function.Consumer;

public class NotifyingList<E> implements List<E> {

  private final List<E> inner;
  private final Consumer<E> onAdd;

  private NotifyingList(List<E> inner, Consumer<E> onAdd) {
    this.inner = Objects.requireNonNull(inner);
    this.onAdd = Objects.requireNonNull(onAdd);
  }

  /** Factory: choose underlying impl without changing clients */
  public static <E> NotifyingList<E> of(List<E> inner, Consumer<E> onAdd) {
    return new NotifyingList<>(inner, onAdd);
  }

  @Override
  public boolean add(E e) {
    boolean ok = inner.add(e);
    if (ok) onAdd.accept(e);
    return ok;
    // You could also forbid nulls or enforce domain invariants here.
  }

  @Override
  public void add(int index, E element) {
    inner.add(index, element);
    onAdd.accept(element);
  }

  @Override public E remove(int index) { return inner.remove(index); }
  @Override public boolean remove(Object o) { return inner.remove(o); }
  @Override public int size() { return inner.size(); }
  @Override public boolean isEmpty() { return inner.isEmpty(); }
  @Override public E get(int index) { return inner.get(index); }
  @Override public Iterator<E> iterator() { return inner.iterator(); }
  @Override public boolean contains(Object o) { return inner.contains(o); }
  @Override public Object[] toArray() { return inner.toArray(); }
  @Override public <T> T[] toArray(T[] a) { return inner.toArray(a); }
  @Override public boolean containsAll(Collection<?> c) { return inner.containsAll(c); }
  @Override public boolean addAll(Collection<? extends E> c) {
    boolean changed = false;
    for (E e : c) changed |= add(e); // ensures notifications per element
    return changed;
  }
  @Override public boolean addAll(int index, Collection<? extends E> c) {
    int i = index; boolean changed = false;
    for (E e : c) { add(i++, e); changed = true; }
    return changed;
  }
  @Override public void clear() { inner.clear(); }
  @Override public E set(int index, E element) { return inner.set(index, element); }
  @Override public int indexOf(Object o) { return inner.indexOf(o); }
  @Override public int lastIndexOf(Object o) { return inner.lastIndexOf(o); }
  @Override public ListIterator<E> listIterator() { return inner.listIterator(); }
  @Override public ListIterator<E> listIterator(int index) { return inner.listIterator(index); }
  @Override public List<E> subList(int fromIndex, int toIndex) { return inner.subList(fromIndex, toIndex); }
  @Override public boolean retainAll(Collection<?> c) { return inner.retainAll(c); }
  @Override public boolean removeAll(Collection<?> c) { return inner.removeAll(c); }
  @Override public boolean addAll(int index, Collection<? extends E> c, boolean dummy) { return addAll(index, c); } // optional

  // equals/hashCode/toString can delegate intentionally:
  @Override public String toString() { return "Notifying" + inner.toString(); }
}
```

**Usage**

```java
List<String> base = new ArrayList<>();
NotifyingList<String> names = NotifyingList.of(base, s -> System.out.println("Added: " + s));
names.add("Ada");
names.add("Grace");
// Can swap base to LinkedList, CopyOnWriteArrayList, etc., without changing clients.
```

### Variant — Narrow the surface (preferred)

Instead of implementing `List<E>` (which forces many forwarders), publish a **smaller port** that fits your domain.

```java
public interface AppendOnlyLog<E> {
  void append(E e);
  int size();
  Iterable<E> readAll();
}

public final class NotifyingLog<E> implements AppendOnlyLog<E> {
  private final List<E> inner;
  private final Consumer<E> onAppend;

  public NotifyingLog(List<E> inner, Consumer<E> onAppend) {
    this.inner = inner; this.onAppend = onAppend;
  }

  @Override public void append(E e) { inner.add(e); onAppend.accept(e); }
  @Override public int size() { return inner.size(); }
  @Override public Iterable<E> readAll() { return Collections.unmodifiableList(inner); }
}
```

*This avoids forwarding the entire `List` API and models the domain explicitly.*

---

## Known Uses

-   Replacing `extends Thread` with a class that **delegates to** a `Runnable` and is scheduled by an `ExecutorService`.
    
-   Wrapping HTTP clients (e.g., `HttpClient`) to add **retries, tracing, metrics**, without inheriting internal behavior.
    
-   Using **decorators** for caching/logging/authorization around repositories or services (Hexagonal Architecture).
    
-   GUI frameworks: wrap widgets instead of subclassing fragile concrete components.
    

## Related Patterns

-   **Replace Delegation with Inheritance:** The inverse; use sparingly when base types are explicitly extensible.
    
-   **Decorator:** Canonical composition for stackable behaviors.
    
-   **Adapter:** Change interface to match client expectations (often coexists with delegation).
    
-   **Facade:** Expose a smaller API over a complex delegate set.
    
-   **Strategy:** Inject swappable behaviors into the wrapper.
    
-   **Extract Interface / Ports & Adapters:** Publish a narrow contract to avoid forwarding huge frameworks.
    

**Rule of thumb:** If you hear “We subclassed X just to tweak Y,” it’s a strong signal to **replace inheritance with delegation**.

