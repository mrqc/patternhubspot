
# Decorator — GoF Structural Pattern

## Pattern Name and Classification

**Name:** Decorator  
**Category:** Structural design pattern

## Intent

Attach additional responsibilities to an object **dynamically**. Decorators provide a flexible alternative to subclassing for extending behavior at runtime while preserving the object’s interface.

## Also Known As

Wrapper

## Motivation (Forces)

-   You need to **augment behavior** without exploding the subclass hierarchy (e.g., `BorderedScrollableClickableTextView`).

-   Responsibilities are **composable** (e.g., buffering + compression + encryption).

-   Enhancements should be **opt-in** at runtime (feature flags, configuration).

-   You want to **respect the Liskov Substitution Principle**: clients still see the same interface.


## Applicability

Use Decorator when:

-   You want to add **cross-cutting** or optional features (caching, logging, metrics, retries).

-   Different combinations of features are needed per object/tenant/environment.

-   Subclassing a concrete class would cause **class explosion** or isn’t possible (final classes).

-   You need to **stack** multiple behaviors in different orders.


## Structure

-   **Component** — the common interface.

-   **ConcreteComponent** — the core object that does the primary work.

-   **Decorator** — base class that **wraps** a Component and delegates by default.

-   **ConcreteDecorators** — extend behavior **before/after** delegating to the wrapped object.


```lua
+-------------------+           +---------------------+
Client --->|     Component     |<----------|      Decorator      |
           +-------------------+           | - wrappee:Component |
                   ^                       | +operation()        |
                   |                       +----------^----------+
      +------------+-----------+                      |
      |   ConcreteComponent    |          +-----------+-------------------+
      +------------------------+          |     ConcreteDecoratorA        |
                                          +--------------------------------
                                          |     ConcreteDecoratorB        |
                                          +--------------------------------
```

## Participants

-   **Component**: defines the interface for objects that can be decorated.

-   **ConcreteComponent**: the primary implementation.

-   **Decorator**: keeps a reference to a `Component`, forwards calls by default.

-   **ConcreteDecorator**: adds responsibilities (pre/post processing, interception).


## Collaboration

-   Client talks to a `Component`.

-   ConcreteDecorators **wrap** another `Component` and may add behavior **around** the delegated call.

-   Multiple decorators can be **stacked**; order matters.


## Consequences

**Benefits**

-   **Open/Closed**: add features without modifying existing classes.

-   **Composability**: combine features at runtime.

-   **Single Responsibility**: each decorator can focus on one concern.


**Liabilities**

-   **Many small objects**; debugging call stacks can be noisy.

-   **Order sensitivity** (e.g., compress→encrypt ≠ encrypt→compress).

-   Not ideal when clients rely on **identity** or use `instanceof` to detect concrete types.

-   If the base interface is too minimal, decorators may need **leaky** access to internals.


## Implementation

-   Put **only** the stable API on `Component`. Keep it cohesive.

-   The base **Decorator** should be a **pass-through**; concrete decorators override selectively.

-   Prefer **constructor injection** of the wrappee; keep decorators **stateless** when possible.

-   If behavior is order-sensitive, document safe orders and provide **builder/factory** helpers.

-   Ensure decorators preserve **semantics** (e.g., idempotency, exceptions) unless explicitly changing them.

-   For equals/hashCode/toString, decide whether to **delegate** or **expose** wrapper info.


---

## Sample Code (Java)

**Scenario:** A `DataSource` that stores strings. We add **compression** and **encryption** as decorators that can be stacked in either order.

```java
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.ArrayList;
import java.util.List;
import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import java.io.*;
import java.util.zip.GZIPInputStream;
import java.util.zip.GZIPOutputStream;

// ===== Component =====
interface DataSource {
    void write(String data);
    String read();
}

// ===== ConcreteComponent (in-memory for demo) =====
class MemoryDataSource implements DataSource {
    private String storage = "";
    @Override public void write(String data) { this.storage = data; }
    @Override public String read() { return storage; }
    @Override public String toString() { return "MemoryDataSource"; }
}

// ===== Base Decorator =====
abstract class DataSourceDecorator implements DataSource {
    protected final DataSource wrappee;
    protected DataSourceDecorator(DataSource wrappee) { this.wrappee = wrappee; }
    @Override public void write(String data) { wrappee.write(data); }
    @Override public String read() { return wrappee.read(); }
    @Override public String toString() { return getClass().getSimpleName() + "(" + wrappee + ")"; }
}

// ===== ConcreteDecorator: Compression (GZIP + Base64) =====
class CompressionDecorator extends DataSourceDecorator {
    public CompressionDecorator(DataSource wrappee) { super(wrappee); }

    @Override public void write(String data) {
        try {
            byte[] compressed = gzip(data.getBytes(StandardCharsets.UTF_8));
            String b64 = Base64.getEncoder().encodeToString(compressed);
            wrappee.write(b64);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    @Override public String read() {
        try {
            byte[] compressed = Base64.getDecoder().decode(wrappee.read());
            byte[] plain = gunzip(compressed);
            return new String(plain, StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    private static byte[] gzip(byte[] data) throws IOException {
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        try (GZIPOutputStream gzip = new GZIPOutputStream(baos)) {
            gzip.write(data);
        }
        return baos.toByteArray();
    }

    private static byte[] gunzip(byte[] data) throws IOException {
        try (GZIPInputStream gis = new GZIPInputStream(new ByteArrayInputStream(data));
             ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buf = new byte[1024];
            int n;
            while ((n = gis.read(buf)) != -1) out.write(buf, 0, n);
            return out.toByteArray();
        }
    }
}

// ===== ConcreteDecorator: Encryption (AES/GCM + Base64) =====
class EncryptionDecorator extends DataSourceDecorator {
    private final byte[] key; // 16/24/32 bytes
    private static final SecureRandom RNG = new SecureRandom();

    public EncryptionDecorator(DataSource wrappee, byte[] key) {
        super(wrappee);
        this.key = key.clone();
    }

    @Override public void write(String data) {
        try {
            byte[] iv = new byte[12];
            RNG.nextBytes(iv);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, new SecretKeySpec(key, "AES"), new GCMParameterSpec(128, iv));
            byte[] ciphertext = cipher.doFinal(data.getBytes(StandardCharsets.UTF_8));
            // store IV || ciphertext as Base64
            byte[] payload = concat(iv, ciphertext);
            String b64 = Base64.getEncoder().encodeToString(payload);
            wrappee.write(b64);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    @Override public String read() {
        try {
            byte[] payload = Base64.getDecoder().decode(wrappee.read());
            byte[] iv = new byte[12];
            byte[] ciphertext = new byte[payload.length - 12];
            System.arraycopy(payload, 0, iv, 0, 12);
            System.arraycopy(payload, 12, ciphertext, 0, ciphertext.length);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, new SecretKeySpec(key, "AES"), new GCMParameterSpec(128, iv));
            byte[] plain = cipher.doFinal(ciphertext);
            return new String(plain, StandardCharsets.UTF_8);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    private static byte[] concat(byte[] a, byte[] b) {
        byte[] out = new byte[a.length + b.length];
        System.arraycopy(a, 0, out, 0, a.length);
        System.arraycopy(b, 0, out, a.length, b.length);
        return out;
    }
}

// ===== Demo =====
public class DecoratorDemo {
    public static void main(String[] args) {
        String secret = "Meet at 19:30. Bring ☕ and logs.\nLine2.";

        byte[] key = "0123456789ABCDEF0123456789ABCDEF".getBytes(StandardCharsets.UTF_8); // 32B AES-256

        // 1) Bare
        DataSource ds = new MemoryDataSource();
        ds.write(secret);
        System.out.println("Bare read: " + ds.read());

        // 2) Compression only
        DataSource compressed = new CompressionDecorator(new MemoryDataSource());
        compressed.write(secret);
        System.out.println("Compressed->read: " + compressed.read());

        // 3) Encryption then Compression (order A)
        DataSource encThenComp = new CompressionDecorator(new EncryptionDecorator(new MemoryDataSource(), key));
        encThenComp.write(secret);
        System.out.println("Encrypt→Compress read: " + encThenComp.read());

        // 4) Compression then Encryption (order B)
        DataSource compThenEnc = new EncryptionDecorator(new CompressionDecorator(new MemoryDataSource()), key);
        compThenEnc.write(secret);
        System.out.println("Compress→Encrypt read: " + compThenEnc.read());

        // Inspect one storage to see that data is transformed
        System.out.println("Stored (compThenEnc, base64): " + ((MemoryDataSource)((DataSourceDecorator)compThenEnc).wrappee).read());
    }
}
```

**What this shows**

-   `DataSource` is the **Component**; `MemoryDataSource` is the **ConcreteComponent**.

-   `CompressionDecorator` and `EncryptionDecorator` are independent **ConcreteDecorators**.

-   You can **stack** decorators in different orders; both still satisfy `DataSource`.

-   The stored representation differs (transformed), while **client API** remains unchanged.


> ⚠️ **Order matters:** compress→encrypt is typical; encrypt→compress yields poor compression and can leak length patterns.

## Known Uses

-   **Java I/O**: `BufferedInputStream`, `GZIPInputStream`, `CipherInputStream` wrap another `InputStream`.

-   **Collections wrappers**: `Collections.unmodifiableList`, `Collections.synchronizedList`.

-   **Servlet request/response wrappers** (`HttpServletRequestWrapper`) to add behavior.

-   **Logging/metrics**: wrapping DAOs/clients to add tracing, retries, caching.

-   **HTTP clients**: interceptors that decorate requests/responses (OkHttp, Apache HttpClient; conceptually similar).


## Related Patterns

-   **Adapter**: changes interface to match another; Decorator **preserves** the interface and adds behavior.

-   **Proxy**: controls access (remote, virtual, protection); can look identical structurally, but **intent** differs.

-   **Composite**: trees of components; decorators are **single-child** composites specialized for augmentation.

-   **Strategy**: encapsulates algorithms; decorators **wrap** to layer concerns around an algorithm.

-   **Chain of Responsibility**: sequences handlers; decorators usually wrap **one** component and typically always delegate.
