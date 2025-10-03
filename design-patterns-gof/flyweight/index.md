
# Flyweight — GoF Structural Pattern

## Pattern Name and Classification

**Name:** Flyweight  
**Category:** Structural design pattern

## Intent

Minimize memory (and sometimes initialization time) by **sharing** as much state as possible between many fine-grained objects. Split state into:

-   **Intrinsic (shared)** — immutable, context-independent data stored once in a flyweight.

-   **Extrinsic (unshared)** — context-specific data supplied by the client at use time.


## Also Known As

Cache, Interning, Canonical Instance

## Motivation (Forces)

-   You have **huge numbers** of conceptually similar objects (e.g., text glyphs, map tiles, chess pieces, particles).

-   Much of their state is **identical** across instances (glyph outline, tile image, piece type) while only a small part varies (position, color, orientation).

-   Creating/storing a “full” object per occurrence causes **high memory pressure**, slower GC, and longer load times.

-   You need **identity transparency**: many logical objects may share the **same underlying representation**.


## Applicability

Use Flyweight when:

-   The app manages **very many** objects with **significant shared state**.

-   Shared state can be made **immutable** and **contained** in a flyweight.

-   The remaining state can be **externalized** and passed in when needed.

-   Clients **do not rely on object identity** (i.e., `==` comparisons) for logical equality.


## Structure

-   **Flyweight** — interface for operations that receive **extrinsic** state as parameters.

-   **ConcreteFlyweight** — stores **intrinsic** state; implements operations.

-   **UnsharedConcreteFlyweight** — optional for objects that can’t/shouldn’t be shared.

-   **FlyweightFactory** — creates and **reuses** flyweights; returns canonical instances.

-   **Client** — keeps/derives **extrinsic** state and passes it into flyweights.


```pgsql
Client --(extrinsic)--> [Flyweight]  (intrinsic stored here)
             ^
             |
       FlyweightFactory (cache/pool keyed by intrinsic state)
```

## Participants

-   **Flyweight**: declares operations requiring extrinsic state.

-   **ConcreteFlyweight**: immutable holder of intrinsic state.

-   **FlyweightFactory**: maintains a cache of flyweights keyed by intrinsic state.

-   **Client**: supplies extrinsic state (e.g., position, current color, transform).

-   **UnsharedConcreteFlyweight**: optional non-shared node when sharing isn’t possible.


## Collaboration

-   Client requests a flyweight from the **factory** using intrinsic parameters (key).

-   Factory returns an **existing** instance or **creates** one and caches it.

-   Client invokes operations on the flyweight, **supplying extrinsic state** each time.


## Consequences

**Benefits**

-   **Large memory savings**; fewer allocations and less GC churn.

-   **Faster startup** when expensive intrinsic state (e.g., glyph outlines) is created once.

-   Encourages **immutability** and **sharing**, simplifying thread safety.


**Liabilities**

-   Requires **discipline** separating intrinsic vs. extrinsic state.

-   More **parameters** must be passed around (extrinsic state).

-   If clients accidentally rely on **identity**, sharing can break assumptions.

-   The **factory/cache** adds complexity (eviction, lifecycle, concurrency).


## Implementation

-   Make flyweights **immutable**; all intrinsic fields `final`.

-   Define a **canonical key** (record/value object) for the intrinsic state (`equals`/`hashCode`).

-   Use a **factory with a cache** (`ConcurrentHashMap.computeIfAbsent`).

-   Consider **weak/soft refs** for eviction if the universe of keys is unbounded.

-   Avoid leaking extrinsic state into the flyweight; pass it via parameters or a small context object.

-   Document **equality semantics**: prefer `equals` over `==`; flyweights may be shared.

-   Threading: immutable flyweights are **thread-safe**; the factory’s cache must be **concurrent**.


---

## Sample Code (Java)

**Scenario:** Text rendering. Each **glyph** (code point + font + size + metrics) is a flyweight (intrinsic). The **occurrence** (x, y, color, underline) is extrinsic and provided at render time.

```java
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

// ---------- Intrinsic Key ----------
record GlyphKey(int codePoint, String font, int size) {}

// ---------- Flyweight interface ----------
interface Glyph {
    GlyphKey key();                        // intrinsic identity
    int advance();                         // intrinsic metric (e.g., advance width)
    void draw(GlyphContext ctx);           // ctx carries extrinsic state
}

// ---------- Extrinsic context ----------
record GlyphContext(int x, int y, int colorRgb, boolean underline, boolean strikeThrough) {}

// ---------- Concrete Flyweight ----------
final class CharacterGlyph implements Glyph {
    private final GlyphKey key;
    private final int advance;             // pretend derived from outline/kerning table

    CharacterGlyph(GlyphKey key) {
        this.key = key;
        // expensive outline metrics computation simulated:
        this.advance = Math.max(6, key.size() / 2);
    }

    @Override public GlyphKey key() { return key; }
    @Override public int advance() { return advance; }

    @Override
    public void draw(GlyphContext ctx) {
        // In a real renderer, we'd draw using the shared outline & the extrinsic style/position.
        System.out.printf(
            "draw '%s' font=%s size=%d @(%d,%d) color=#%06X%s%s%n",
            new String(Character.toChars(key.codePoint())),
            key.font(), key.size(), ctx.x(), ctx.y(), ctx.colorRgb(),
            ctx.underline() ? " underline" : "",
            ctx.strikeThrough() ? " strike" : ""
        );
    }
}

// ---------- Flyweight Factory ----------
final class GlyphFactory {
    private final Map<GlyphKey, Glyph> cache = new ConcurrentHashMap<>();

    public Glyph get(int codePoint, String font, int size) {
        GlyphKey k = new GlyphKey(codePoint, font, size);
        return cache.computeIfAbsent(k, CharacterGlyph::new);
    }

    public int uniqueGlyphs() { return cache.size(); }
}

// ---------- Client-side "document" that stores occurrences ----------
record GlyphOccurrence(Glyph glyph, GlyphContext ctx) {}

final class TextDocument {
    private final List<GlyphOccurrence> runs = new ArrayList<>();
    private final GlyphFactory factory;

    TextDocument(GlyphFactory factory) { this.factory = factory; }

    public void append(String text, String font, int size, int startX, int baselineY, int color) {
        int x = startX;
        for (int i = 0; i < text.length(); ) {
            int cp = text.codePointAt(i);
            i += Character.charCount(cp);

            Glyph glyph = factory.get(cp, font, size); // shared
            GlyphContext ctx = new GlyphContext(x, baselineY, color, false, false);
            runs.add(new GlyphOccurrence(glyph, ctx));
            x += glyph.advance();
        }
    }

    public void render() { runs.forEach(go -> go.glyph().draw(go.ctx())); }
    public int occurrences() { return runs.size(); }
}

// ---------- Demo ----------
public class FlyweightDemo {
    public static void main(String[] args) {
        GlyphFactory factory = new GlyphFactory();
        TextDocument doc = new TextDocument(factory);

        String line = "Flyweight pattern!! ";
        // Build a “page” by repeating the line in different colors/sizes
        for (int row = 0; row < 3; row++) {
            int size = 12 + row * 2;
            int color = switch (row) { case 0 -> 0x333333; case 1 -> 0x0055AA; default -> 0xAA3300; };
            doc.append(line, "DejaVu Sans", size, 10, 20 + row * 18, color);
        }

        doc.render();

        System.out.println("\nOccurrences stored: " + doc.occurrences());
        System.out.println("Unique flyweights : " + factory.uniqueGlyphs() +
                " (distinct codePoint×font×size)");
    }
}
```

**What this demonstrates**

-   **Intrinsic** state = `codePoint`, `font`, `size`, `advance` (kept in `CharacterGlyph`).

-   **Extrinsic** state = `(x, y, color, underline, strike)` (passed each draw via `GlyphContext`).

-   The factory **reuses** `CharacterGlyph` instances across many occurrences.  
    If you render thousands of “e” characters at different positions/colors, you still hold **one** flyweight for that `(‘e’, font, size)` triple.


---

## Known Uses

-   **Java boxing caches**: `Integer.valueOf(-128..127)`, `Byte.valueOf`, `Character.valueOf` reuse canonical instances.

-   **`String#intern()`**: returns a canonical shared `String` instance per content.

-   **Font/glyph caches** in AWT/Swing/JavaFX and most graphics engines.

-   **Charset & regex internals**: cached encoders/decoders, compiled patterns.

-   **Game engines**: particle systems, tiles, sprites sharing meshes/textures.

-   **Compilers/IDEs**: symbol or string interning tables; shared AST nodes for literals.


## Related Patterns

-   **Factory Method / Abstract Factory**: used by the **flyweight factory** to obtain/create instances.

-   **Object Pool**: both reuse objects; a pool manages **mutable, leased** objects; Flyweight shares **immutable** ones.

-   **Immutable Value Object**: flyweights are typically immutable; value objects may also be interned.

-   **Composite**: flyweights often act as **leaves** within large trees (e.g., glyphs in a document).

-   **Proxy**: can stand in front of heavy shared state (lazy materialization).

-   **Memento**: extrinsic context may resemble memento-like snapshots, but is not stored in the flyweight.
