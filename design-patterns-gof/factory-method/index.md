
# Factory Method — GoF Creational Pattern

## Pattern Name and Classification

**Name:** Factory Method  
**Category:** Creational design pattern

## Intent

Define an interface for creating an object, but let **subclasses decide** which class to instantiate. Factory Method lets a class **defer instantiation** to subclasses and keeps the **construction logic** in one overridable place.

## Also Known As

Virtual Constructor

## Motivation (Forces)

-   You have a **general algorithm** (template) that needs a **pluggable product** at one step (e.g., parsing, rendering, storage).

-   You want to **decouple** the high-level workflow from **concrete product types**.

-   You foresee **family growth** of products and want to add new ones without modifying existing client code.

-   You need to **centralize invariants** around object creation (defaults, validation) while allowing variants.


## Applicability

Use Factory Method when:

-   A class **cannot anticipate** which class of objects it must create.

-   A class wants its **subclasses to specify** the objects it creates.

-   You want to **localize creation logic** to make the rest of the algorithm independent from product classes.

-   You want **testability** by substituting products with stubs or fakes.


## Structure

-   **Product** — interface/abstract class for created objects.

-   **ConcreteProduct** — specific implementations.

-   **Creator** — defines the **factory method** (`createProduct`) and often a **template method** that uses it.

-   **ConcreteCreator** — overrides the factory method to return a `ConcreteProduct`.


```lua
+------------------+           creates            +------------------+
           |     Creator      |---------------------------->|      Product     |
           | +templateOp()    |                              +------------------+
           | +createProduct() |<-- override -----------------+  ^     ^     ^
           +------------------+                               |     |     |
                                                              |     |     |
                                                    +---------+  +--+--+  +---------+
                                                    |ConcreteA|  |  B |  | ConcreteC|
                                                    +---------+  +-----+  +---------+
```

## Participants

-   **Product**: defines the interface for objects the factory creates.

-   **ConcreteProduct**: concrete implementations of `Product`.

-   **Creator**: declares the factory method and uses it within its algorithms.

-   **ConcreteCreator**: overrides the factory method to return a specific product.


## Collaboration

-   Client calls a high-level method (often a **template method**) on **Creator**.

-   **Creator** calls its **factory method** to obtain a `Product` and proceeds without knowing the concrete type.

-   **ConcreteCreator** decides which `ConcreteProduct` to instantiate.


## Consequences

**Benefits**

-   **Decouples** product construction from usage.

-   **Open/Closed**: add new products by introducing new ConcreteCreators.

-   Central place to enforce **creation invariants** (defaults, validation, caching).


**Liabilities**

-   Introduces **subclassing**; one subclass per concrete product (can increase class count).

-   If misused for trivial creation, adds **unnecessary indirection**.

-   Choice at runtime often requires **factory selection** (configuration/DI).


## Implementation

-   Put **only the steps that vary** into the factory method; keep the rest in a **template method**.

-   Return the **Product interface**, not a concrete type.

-   If the choice comes from configuration, use a **parameterized** factory method or **Abstract Factory** instead of many subclasses.

-   Consider **object pooling**/caching inside the factory method when appropriate.

-   For testing, override the factory method to return **test doubles**.

-   Keep factories **stateless** where possible; document lifecycle/ownership if not.


---

## Sample Code (Java)

**Scenario:** A generic `Importer` processes text using a pluggable `Parser`. The **factory method** `createParser()` is overridden by concrete importers to choose JSON, XML, or YAML parsing.

```java
// ===== Product =====
interface Parser {
    ParsedDocument parse(String content);
}

final class ParsedDocument {
    private final Map<String, Object> data;
    public ParsedDocument(Map<String, Object> data) { this.data = data; }
    public Map<String, Object> data() { return data; }
    @Override public String toString() { return data.toString(); }
}

// ===== Concrete Products =====
class JsonParser implements Parser {
    @Override public ParsedDocument parse(String content) {
        // demo: pretend to parse JSON -> very naive extraction
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("type", "json");
        map.put("length", content.length());
        return new ParsedDocument(map);
    }
}

class XmlParser implements Parser {
    @Override public ParsedDocument parse(String content) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("type", "xml");
        map.put("elements", Math.max(0, content.split("<").length - 1));
        return new ParsedDocument(map);
    }
}

class YamlParser implements Parser {
    @Override public ParsedDocument parse(String content) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("type", "yaml");
        map.put("lines", content.lines().count());
        return new ParsedDocument(map);
    }
}

// ===== Creator =====
abstract class Importer {
    // Template method uses the product returned by the factory method
    public final ParsedDocument importText(String content) {
        validate(content);
        Parser parser = createParser();                  // <-- Factory Method
        ParsedDocument doc = parser.parse(content);
        postProcess(doc);
        return doc;
    }

    protected void validate(String content) {
        if (content == null || content.isBlank()) throw new IllegalArgumentException("empty input");
    }

    protected void postProcess(ParsedDocument doc) {
        // default: no-op. Subclasses may enrich/validate further
    }

    protected abstract Parser createParser();            // <-- Factory Method
}

// ===== Concrete Creators =====
class JsonImporter extends Importer {
    @Override protected Parser createParser() { return new JsonParser(); }
}

class XmlImporter extends Importer {
    @Override protected Parser createParser() { return new XmlParser(); }
}

class YamlImporter extends Importer {
    @Override protected Parser createParser() { return new YamlParser(); }
}

// ===== Client / Demo =====
public class FactoryMethodDemo {
    public static void main(String[] args) {
        Importer json = new JsonImporter();
        Importer xml  = new XmlImporter();
        Importer yaml = new YamlImporter();

        System.out.println(json.importText("{\"a\":1,\"b\":2}"));  // {type=json, length=15}
        System.out.println(xml.importText("<a><b/></a>"));         // {type=xml, elements=3}
        System.out.println(yaml.importText("a: 1\nb: 2\n"));       // {type=yaml, lines=2}
    }
}
```

**Notes**

-   `Importer.importText` is a **template method**; it calls the **factory method** `createParser()` to obtain the appropriate `Parser`.

-   Adding a new format (e.g., `CsvParser`) only requires a new `CsvImporter` overriding `createParser()`—no changes to `Importer` or clients.


### Variant: Parameterized Factory Method (single creator)

If you don’t want many subclasses, the factory method can accept a **hint**:

```java
enum Format { JSON, XML, YAML }

class ConfigurableImporter extends Importer {
    private final Format format;
    public ConfigurableImporter(Format format) { this.format = format; }
    @Override protected Parser createParser() {
        return switch (format) {
            case JSON -> new JsonParser();
            case XML  -> new XmlParser();
            case YAML -> new YamlParser();
        };
    }
}
```

This trades subclassing for a **switch on an enum/config**. If the list of formats changes often, consider **Abstract Factory** or a **registry**.

## Known Uses

-   **Java XML parsers**: `DocumentBuilderFactory`/`SAXParserFactory` expose factory methods returning parser instances chosen by providers.

-   **Persistence/IO providers**: `java.nio.channels.spi.SelectorProvider#openSelector()` (provider subclasses supply concrete selectors).

-   **UI toolkits / frameworks**: framework base classes override factory methods to produce platform-specific widgets/peers.

-   **Logging frameworks**: factories that vend loggers/appenders while allowing alternative implementations (conceptually similar).


## Related Patterns

-   **Abstract Factory**: creates **families** of related products; often implemented using multiple Factory Methods.

-   **Template Method**: frequently used alongside Factory Method to call the factory at a specific step of a larger algorithm.

-   **Prototype**: creation via cloning instead of instantiation; a factory method may choose which prototype to clone.

-   **Builder**: separates complex **assembly** from representation; Factory Method focuses on **which** product to create.

-   **Dependency Injection / Service Locator**: alternative ways to supply concrete products; DI often **injects** what a factory method would otherwise create.
