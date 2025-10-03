# Builder — GoF Structural Pattern

## Pattern Name and Classification

**Name:** Builder  
**Category:** Creational design pattern

## Intent

Separate the construction of a complex object from its representation so that the same construction process can create different representations. Provide a step-wise, controlled way to assemble an object (often immutable) and make the creation readable and safe.

## Also Known As

Stepwise Construction, Fluent Builder (idiomatic name), Staged Builder (typed step builder)

## Motivation (Forces)

-   **Telescoping constructors** (many optional params) reduce readability and are error-prone.

-   Need for **controlled, incremental assembly** (validation, defaults, invariants).

-   Want to **reuse a construction algorithm** to create different products (e.g., text vs. HTML report).

-   Object should be **immutable** after creation, yet **configurable** during building.

-   Some parts may be **computed/validated** late (e.g., derived values).


## Applicability

Use Builder when:

-   Construction involves **multiple steps**, optional parts, or constraints.

-   You must **vary the internal representation** or product type produced by the same steps.

-   You want **immutability** with many optional fields.

-   You wish to **decouple** parsing/reading/assembling logic from the final product.


## Structure

-   **Builder** — declares step methods for constructing parts and a `build()`/`getResult()`.

-   **ConcreteBuilder** — implements steps; tracks intermediate state; returns the product.

-   **Director** (optional) — encapsulates a construction algorithm by calling builder steps in a fixed order.

-   **Product** — the complex object being created.


```rust
Client -> Director -> Builder (setPartA, setPartB, ...)
                     |
                     v
                  Product
```

## Participants

-   **Product**: target object with possibly many optional/variant parts.

-   **Builder**: fluent API for setting parts; may enforce order and validation.

-   **ConcreteBuilder**: builds a particular representation; returns the product.

-   **Director** (optional): reusable recipes; hides step sequences from the client.


## Collaboration

-   Client selects a **ConcreteBuilder** and optionally a **Director**.

-   Director invokes builder steps to produce a product variant.

-   Builder accumulates state and finally returns the **Product** (often immutable).


## Consequences

**Benefits**

-   Clear, **readable construction**; avoids telescoping constructors.

-   Can **validate** and **enforce invariants** before `build()`.

-   **Different representations** from the same build sequence.

-   Works well with **immutability** and **method chaining**.


**Liabilities**

-   **More classes**/boilerplate than simple constructors/factories.

-   If overused for trivial objects, adds **unnecessary indirection**.

-   Director abstraction is sometimes **superfluous** in modern use.


## Implementation

-   Make **Product** immutable; have the builder be the only mutator.

-   Use **fluent API** returning `this` for chaining.

-   Validate in `build()` (and/or per-step for staged builders).

-   Consider **staged builder** (typed steps) when order is critical.

-   For families of products, use **Abstract Builder** hierarchy; a **Director** can codify recipes.

-   Thread safety: Builders are typically **not** thread-safe; the resulting Product can be.


---

## Sample Code (Java)

**Scenario:** Building an immutable `Report` with optional sections and two representations (PlainText, HTML). We show both a **Director-driven classic Builder** and a **modern fluent builder** on the product.

```java
// ----- Product -----
public final class Report {
    private final String title;
    private final String header;
    private final String body;
    private final String footer;
    private final String rendered; // computed representation

    private Report(String title, String header, String body, String footer, String rendered) {
        this.title = title;
        this.header = header;
        this.body = body;
        this.footer = footer;
        this.rendered = rendered;
    }

    public String title() { return title; }
    public String header() { return header; }
    public String body() { return body; }
    public String footer() { return footer; }
    public String rendered() { return rendered; }

    // Modern "product-local" fluent builder
    public static class Builder {
        private String title;
        private String header = "";
        private String body = "";
        private String footer = "";
        private Renderer renderer = new PlainTextRenderer(); // default strategy

        public Builder title(String t) { this.title = t; return this; }
        public Builder header(String h) { this.header = h; return this; }
        public Builder body(String b)   { this.body = b; return this; }
        public Builder footer(String f) { this.footer = f; return this; }
        public Builder renderer(Renderer r) { this.renderer = r; return this; }

        public Report build() {
            if (title == null || title.isBlank())
                throw new IllegalStateException("title is required");
            String rendered = renderer.render(title, header, body, footer);
            return new Report(title, header, body, footer, rendered);
        }
    }
}

// ----- Implementor-like strategy for representation -----
interface Renderer {
    String render(String title, String header, String body, String footer);
}

class PlainTextRenderer implements Renderer {
    @Override public String render(String title, String header, String body, String footer) {
        StringBuilder sb = new StringBuilder();
        sb.append("# ").append(title).append("\n\n");
        if (!header.isBlank()) sb.append(header).append("\n\n");
        if (!body.isBlank())   sb.append(body).append("\n\n");
        if (!footer.isBlank()) sb.append("-- ").append(footer).append("\n");
        return sb.toString();
    }
}

class HtmlRenderer implements Renderer {
    @Override public String render(String title, String header, String body, String footer) {
        return """
               <article>
                 <h1>%s</h1>
                 %s
                 <section>%s</section>
                 %s
               </article>
               """.formatted(
                esc(title),
                header.isBlank() ? "" : "<header>" + esc(header) + "</header>",
                esc(body),
                footer.isBlank() ? "" : "<footer>" + esc(footer) + "</footer>"
        );
    }
    private static String esc(String s) {
        return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;");
    }
}

// ----- Classic GoF-style Builder with Director (optional) -----
interface ReportBuilder {
    void reset();
    void setTitle(String title);
    void setHeader(String header);
    void setBody(String body);
    void setFooter(String footer);
    Report getResult();
}

class PlainTextReportBuilder implements ReportBuilder {
    private Report.Builder inner;

    @Override public void reset() { inner = new Report.Builder().renderer(new PlainTextRenderer()); }
    @Override public void setTitle(String title) { inner.title(title); }
    @Override public void setHeader(String header) { inner.header(header); }
    @Override public void setBody(String body) { inner.body(body); }
    @Override public void setFooter(String footer) { inner.footer(footer); }
    @Override public Report getResult() { return inner.build(); }
}

class HtmlReportBuilder implements ReportBuilder {
    private Report.Builder inner;
    @Override public void reset() { inner = new Report.Builder().renderer(new HtmlRenderer()); }
    @Override public void setTitle(String title) { inner.title(title); }
    @Override public void setHeader(String header) { inner.header(header); }
    @Override public void setBody(String body) { inner.body(body); }
    @Override public void setFooter(String footer) { inner.footer(footer); }
    @Override public Report getResult() { return inner.build(); }
}

// Director encodes reusable "recipes"
class ReportDirector {
    public void buildSimple(ReportBuilder b, String title, String body) {
        b.reset();
        b.setTitle(title);
        b.setBody(body);
    }
    public void buildFull(ReportBuilder b, String title, String header, String body, String footer) {
        b.reset();
        b.setTitle(title);
        b.setHeader(header);
        b.setBody(body);
        b.setFooter(footer);
    }
}

// ----- Demo -----
public class BuilderDemo {
    public static void main(String[] args) {
        // Modern fluent builder (no director)
        Report r1 = new Report.Builder()
                .title("Weekly Status")
                .header("Team Alpha")
                .body("All systems green.")
                .footer("PM: Jane Doe")
                .renderer(new PlainTextRenderer())
                .build();
        System.out.println(r1.rendered());

        // Classic GoF builder with director
        ReportDirector director = new ReportDirector();

        ReportBuilder htmlBuilder = new HtmlReportBuilder();
        director.buildFull(htmlBuilder,
                "Release Notes",
                "Version 2.1.0",
                "• Feature A\n• Fix B",
                "© 2025 ACME Inc.");
        Report r2 = htmlBuilder.getResult();
        System.out.println(r2.rendered());
    }
}
```

### Notes

-   The **modern fluent** builder lives inside the Product for convenience, favors readability, and enforces invariants at `build()`.

-   The **classic GoF** variant shows the **Director** reusing a sequence to produce different representations (PlainText vs. HTML).

-   Swap `Renderer` to change the final representation **without** changing the construction steps.


## Known Uses

-   **`StringBuilder` / `StringBuffer`**: incremental string assembly.

-   **`java.nio.ByteBuffer`** and **`Uri.Builder`**: stepwise configuration before producing a value.

-   **`java.time.format.DateTimeFormatterBuilder`**: complex formatter assembly.

-   **HTTP clients** (e.g., `HttpRequest.newBuilder()`): fluent configuration, immutable result.

-   **Builders generated by Lombok/Immutables/AutoValue** for immutable domain objects.


## Related Patterns

-   **Abstract Factory**: creates families of products in one call; Builder creates **one** product step-by-step.

-   **Prototype**: clone a preconfigured instance; can work with Builder to produce a baseline then tweak.

-   **Composite**: builders often assemble composite structures (trees) safely.

-   **Director** + **Strategy**: when the build **algorithm** itself varies, a Director may apply a Strategy to choose sequences.

-   **Facade**: can wrap a verbose builder API to expose a simpler preset recipe.
