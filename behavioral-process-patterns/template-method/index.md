# Template Method — Behavioral / Process Pattern

## Pattern Name and Classification

**Template Method** — *Behavioral / Process* pattern that defines the **skeleton of an algorithm** in a base class and lets subclasses **override specific steps** without changing the overall structure.

---

## Intent

Capture an algorithm’s **invariant sequence** in a single place and allow **variation points** (steps) to be customized by subclasses via **primitive operations** and **hooks**.

---

## Also Known As

-   **Template**

-   **Abstract Recipe**

-   **Invariant Skeleton with Primitive Operations**


---

## Motivation (Forces)

-   Many workflows share the **same high-level steps** (e.g., import → validate → transform → persist → notify) but differ in **how** a step is performed.

-   Duplicating the sequence across implementations causes **drift** and **bugs** when the flow changes.

-   We want to enforce **ordering, error handling, and logging** once, while enabling **specialization** per variant.


Trade-offs: favors **inheritance** (tight coupling to base class) over pure composition; too many hooks can lead to fragile hierarchies.

---

## Applicability

Use Template Method when:

-   Several classes perform the **same algorithmic outline** with **step-level variation**.

-   You must **enforce an order** or shared cross-cutting concerns (transactions, metrics, retries).

-   You want a **single place** to change the process.


Avoid when:

-   Variations are orthogonal and better served by **Strategy** (composition over inheritance).

-   Steps need to be swapped at runtime (prefer Strategy / Pipeline).


---

## Structure

```csharp
AbstractTemplate
  + final run()                            ← defines invariant sequence
    ├─ preHook()            (optional hook)
    ├─ stepA()              (abstract/overridable)
    ├─ stepB()              (abstract/overridable)
    ├─ stepC()              (default/overridable)
    └─ postHook()           (optional hook)

ConcreteTemplateX overrides stepA/stepB/stepC/postHook as needed
ConcreteTemplateY ...
```

---

## Participants

-   **AbstractTemplate** — defines `final` template method (the algorithm skeleton) and declares primitive operations + hooks.

-   **Concrete Implementations** — provide step-specific behavior by overriding primitive operations and (optionally) hooks.

-   **Client** — calls the template method; does not orchestrate steps itself.


---

## Collaboration

1.  Client invokes **`run()`** on an `AbstractTemplate`.

2.  The template executes the **fixed sequence**, delegating to step methods provided by the subclass.

3.  Hooks allow subclasses to **augment** behavior before/after the core steps.


---

## Consequences

**Benefits**

-   **Single source of truth** for process ordering, error handling, logging.

-   Encourages **code reuse**; variations are localized.

-   Easier to apply **cross-cutting** concerns once (metrics, tracing).


**Liabilities**

-   Uses **inheritance**; subclasses are tightly coupled to base class lifecycle.

-   Hard to vary steps **at runtime** (requires different subclass instances).

-   Large hierarchies may become brittle; combine with **Strategy** for complex variability.


---

## Implementation (Key Points)

-   Make the template method **`final`** to prevent reordering.

-   Provide **abstract primitive operations** for required steps and **hooks** (default no-op) for optional steps.

-   Centralize **transaction boundaries**, **retry**, **timers**, **logging** in the template.

-   Prefer **small, intent-revealing** primitive methods over monolithic overrides.

-   Mix with **Strategy** if some steps should be pluggable at runtime.


---

## Sample Code (Java 17) — Data Import Pipeline (CSV vs. JSON)

> One invariant pipeline: **load → validate → transform → persist**, with built-in logging, timing, and error handling.  
> Two concrete importers specialize the *load* and *transform* steps.

```java
import java.time.Duration;
import java.time.Instant;
import java.util.*;
import java.util.stream.*;

// ===== Template base class =====
abstract class DataImportTemplate<I, R> {

  // The invariant algorithm: do not allow subclasses to change ordering.
  public final List<R> run(String source) {
    Instant start = Instant.now();
    preHook(source);

    try {
      List<I> raw = load(source);
      List<I> valid = validate(raw);
      List<R> mapped = transform(valid);
      persist(mapped);
      postHook(mapped);
      return mapped;
    } catch (Exception ex) {
      onError(ex, source);
      throw ex; // rethrow or map to domain error
    } finally {
      onFinally(Duration.between(start, Instant.now()));
    }
  }

  // ---- Primitive operations (to override) ----
  protected abstract List<I> load(String source);
  protected List<I> validate(List<I> input) { return input; } // default: no-op
  protected abstract List<R> transform(List<I> valid);
  protected void persist(List<R> records) { /* default: no-op (e.g., injected repo later) */ }

  // ---- Hooks (optional) ----
  protected void preHook(String source)  { log("Starting import from " + source); }
  protected void postHook(List<R> out)   { log("Imported " + out.size() + " records"); }
  protected void onError(Exception ex, String source) { log("ERROR importing from " + source + ": " + ex.getMessage()); }
  protected void onFinally(Duration d)   { log("Finished in " + d.toMillis() + " ms"); }

  protected void log(String msg) { System.out.println("[Template] " + msg); }
}

// ===== Domain model for the example =====
record Person(String firstName, String lastName, String email) {}

// ===== Concrete Template #1: CSV importer =====
class CsvPersonImport extends DataImportTemplate<String[], Person> {

  @Override
  protected List<String[]> load(String csv) {
    // Very small CSV split (no quotes/escapes for brevity)
    return csv.lines()
              .filter(l -> !l.isBlank())
              .map(l -> l.split(","))
              .toList();
  }

  @Override
  protected List<String[]> validate(List<String[]> rows) {
    return rows.stream()
      .peek(r -> {
        if (r.length != 3) throw new IllegalArgumentException("Bad row length: " + Arrays.toString(r));
        if (!r[2].contains("@")) throw new IllegalArgumentException("Invalid email: " + r[2]);
      })
      .toList();
  }

  @Override
  protected List<Person> transform(List<String[]> rows) {
    return rows.stream()
      .map(r -> new Person(r[0].trim(), r[1].trim(), r[2].trim()))
      .toList();
  }

  @Override
  protected void persist(List<Person> people) {
    // Imagine saving to a repository; here we just log
    people.forEach(p -> log("Saved " + p.email()));
  }

  @Override
  protected void postHook(List<Person> out) {
    log("CSV: created/updated " + out.size() + " people");
  }
}

// ===== Concrete Template #2: JSON importer =====
class JsonPersonImport extends DataImportTemplate<Map<String,Object>, Person> {

  @Override
  protected List<Map<String,Object>> load(String json) {
    // Tiny, naive parser for demo: expects [{"firstName":"...","lastName":"...","email":"..."}]
    // In real code use Jackson/Gson.
    String body = json.trim();
    if (!body.startsWith("[") || !body.endsWith("]")) throw new IllegalArgumentException("Not a JSON array");
    body = body.substring(1, body.length()-1).trim();
    if (body.isBlank()) return List.of();

    // Split simplistic objects
    List<String> items = new ArrayList<>();
    int depth=0, start=0;
    for (int i=0;i<body.length();i++) {
      char c = body.charAt(i);
      if (c=='{') depth++;
      if (c=='}') depth--;
      if (c==',' && depth==0) { items.add(body.substring(start, i)); start=i+1; }
    }
    items.add(body.substring(start));

    return items.stream().map(this::parseObject).toList();
  }

  private Map<String,Object> parseObject(String obj) {
    String s = obj.trim();
    if (!s.startsWith("{") || !s.endsWith("}")) throw new IllegalArgumentException("Bad JSON object");
    s = s.substring(1, s.length()-1).trim();
    Map<String,Object> map = new HashMap<>();
    for (String part : s.split(",")) {
      String[] kv = part.split(":");
      String k = kv[0].trim().replaceAll("^\"|\"$", "");
      String v = kv[1].trim().replaceAll("^\"|\"$", "");
      map.put(k, v);
    }
    return map;
  }

  @Override
  protected List<Map<String,Object>> validate(List<Map<String,Object>> rows) {
    return rows.stream()
      .peek(m -> {
        if (!m.containsKey("email")) throw new IllegalArgumentException("Email missing");
        if (!((String)m.get("email")).contains("@")) throw new IllegalArgumentException("Invalid email");
      })
      .toList();
  }

  @Override
  protected List<Person> transform(List<Map<String,Object>> rows) {
    return rows.stream()
      .map(m -> new Person(
          (String)m.getOrDefault("firstName",""),
          (String)m.getOrDefault("lastName",""),
          (String)m.get("email")))
      .toList();
  }

  @Override
  protected void persist(List<Person> people) {
    // Different persistence policy (e.g., batching)
    log("JSON batch save: " + people.size());
  }

  @Override
  protected void preHook(String source) {
    log("JSON import starting; source length=" + source.length());
  }
}

// ===== Demo =====
public class TemplateMethodDemo {
  public static void main(String[] args) {
    String csv = """
      Ada,Lovelace,ada@history.org
      Alan,Turing,alan@computing.org
    """;

    String json = """
      [
        {"firstName":"Grace","lastName":"Hopper","email":"grace@navy.mil"},
        {"firstName":"Edsger","lastName":"Dijkstra","email":"edsger@algo.net"}
      ]
    """;

    var csvImporter = new CsvPersonImport();
    var jsonImporter = new JsonPersonImport();

    var a = csvImporter.run(csv);
    var b = jsonImporter.run(json);

    System.out.println("CSV persons:  " + a);
    System.out.println("JSON persons: " + b);
  }
}
```

**Why this illustrates Template Method**

-   `DataImportTemplate.run()` is the **final, invariant** workflow.

-   Concrete classes override **primitive operations** (`load`, `transform`, `persist`) and **hooks** (`preHook`, `postHook`).

-   Cross-cutting concerns (logging, timing, error handling) are **centralized** in the template.


---

## Known Uses

-   Framework lifecycles (JUnit, Servlet `service()`, Spring `Abstract*` templates).

-   Build tools and pipelines (compile → test → package → publish).

-   File/data import/export routines; document parsers; job processors.

-   Games (game loop phases), rendering pipelines.


---

## Related Patterns

-   **Strategy** — swaps algorithms via composition; Template fixes the **sequence** and varies steps via inheritance.

-   **Hook Method** — a specific kind of Template “optional step”.

-   **Factory Method** — often a primitive operation inside a Template to create parts.

-   **Template + Strategy** — combine: keep the skeleton in Template, inject pluggable sub-steps as Strategies.

-   **Chain of Responsibility** — alternative for pipelines where **order is fixed but handlers may short-circuit**.
