
# Bridge — GoF Structural Pattern

## Pattern Name and Classification

**Name:** Bridge  
**Classification:** Structural design pattern

## Intent

Decouple an abstraction from its implementation so that the two can vary independently. You can change or extend either side without touching the other.

## Also Known As

Handle/Body, Interface/Implementation

## Motivation (Forces)

-   You have **two (or more) dimensions of variability** (e.g., *Remote type* × *Device type*, *Shape* × *Rendering API*, *Message* × *Transport*).

-   Inheritance alone would create a **class explosion** (e.g., `AdvancedRemoteForRadio`, `BasicRemoteForTV`, …).

-   You want to **swap implementations at runtime** (e.g., change the rendering backend from OpenGL to Vulkan).

-   You want to **distribute ownership** and compile/deploy each side independently (plugin-like implementations).


## Applicability

Use Bridge when:

-   Abstractions and implementations **should not be bound** at compile time.

-   Both sides of the hierarchy will **evolve independently**.

-   You must **avoid subclass proliferation** caused by cross-product combinations.

-   You need to **switch implementations dynamically** (configuration, A/B tests, feature flags).

-   You want to **mock or stub** the implementation for testing the abstraction.


## Structure

-   **Abstraction** — the high-level interface (owns a reference to Implementor).

-   **RefinedAbstraction** — specialized abstractions.

-   **Implementor** — low-level interface (can be very slim).

-   **ConcreteImplementor** — concrete low-level implementations.


```nginx
Abstraction ------------------------------> Implementor
     |                                           ^
     | has-a (composition)                       |
     v                                           |
RefinedAbstraction                      ConcreteImplementorA/B/...
```

## Participants

-   **Abstraction**

    -   Declares high-level operations and **delegates** work to an **Implementor**.

-   **RefinedAbstraction**

    -   Extends Abstraction’s behavior without changing Implementor contracts.

-   **Implementor**

    -   Declares the low-level operations the Abstraction needs (often minimal).

-   **ConcreteImplementor**

    -   Provides the actual low-level behavior (platform, vendor, API).


## Collaboration

-   Abstraction forwards requests to its Implementor object.

-   RefinedAbstraction may add behavior **before/after** delegating.

-   Clients talk to Abstraction; they typically never depend on ConcreteImplementors directly (DI/container can wire them).


## Consequences

**Pros**

-   **Independent extensibility** of abstraction and implementation.

-   **Runtime swapping** of implementations.

-   **Fewer classes** than naive multiple inheritance/cross-product solutions.

-   **Better testability** (mock the Implementor).


**Cons**

-   **Indirection** adds small runtime overhead and complexity.

-   Requires **careful interface design**; leaky Implementor contracts can re-couple layers.

-   Too many tiny methods in Implementor can lead to **chatty** interfaces.


## Implementation

-   Define a **stable, minimal Implementor** interface aligned to what the Abstraction truly needs.

-   Use **composition**, not inheritance, to hold the Implementor in the Abstraction.

-   Prefer **constructor injection** for the Implementor; allow **setters** if you need hot-swapping.

-   Keep the Implementor **cohesive**; avoid dumping unrelated operations into it.

-   Consider **SPIs** for pluggable implementations (service loader).

-   For thread safety, ensure Implementors are either **stateless** or **properly synchronized**.

-   Testing: mock Implementor to unit-test Abstraction; separately test ConcreteImplementors.


## Sample Code (Java)

**Scenario:** Remotes (abstractions) controlling Devices (implementations). We can add new remote types *or* new devices independently.

```java
// Implementor
public interface Device {
    boolean isEnabled();
    void enable();
    void disable();
    int getVolume();              // 0..100
    void setVolume(int percent);
    int getChannel();
    void setChannel(int channel);
}

// ConcreteImplementor A
public class TV implements Device {
    private boolean on;
    private int volume = 20;
    private int channel = 1;

    @Override public boolean isEnabled() { return on; }
    @Override public void enable() { on = true; }
    @Override public void disable() { on = false; }
    @Override public int getVolume() { return volume; }
    @Override public void setVolume(int percent) { volume = clamp(percent); }
    @Override public int getChannel() { return channel; }
    @Override public void setChannel(int channel) { this.channel = Math.max(1, channel); }

    private int clamp(int p) { return Math.max(0, Math.min(100, p)); }

    @Override public String toString() {
        return "TV{" + "on=" + on + ", volume=" + volume + ", channel=" + channel + '}';
    }
}

// ConcreteImplementor B
public class Radio implements Device {
    private boolean on;
    private int volume = 30;
    private int channel = 88; // FM frequency or preset

    @Override public boolean isEnabled() { return on; }
    @Override public void enable() { on = true; }
    @Override public void disable() { on = false; }
    @Override public int getVolume() { return volume; }
    @Override public void setVolume(int percent) { volume = clamp(percent); }
    @Override public int getChannel() { return channel; }
    @Override public void setChannel(int channel) { this.channel = Math.max(1, channel); }

    private int clamp(int p) { return Math.max(0, Math.min(100, p)); }

    @Override public String toString() {
        return "Radio{" + "on=" + on + ", volume=" + volume + ", channel=" + channel + '}';
    }
}

// Abstraction
public class Remote {
    protected Device device;

    public Remote(Device device) {
        this.device = device;
    }

    public void togglePower() {
        if (device.isEnabled()) device.disable(); else device.enable();
    }

    public void volumeDown() { device.setVolume(device.getVolume() - 10); }
    public void volumeUp()   { device.setVolume(device.getVolume() + 10); }
    public void channelDown(){ device.setChannel(device.getChannel() - 1); }
    public void channelUp()  { device.setChannel(device.getChannel() + 1); }

    @Override public String toString() { return "Remote{" + device + "}"; }
}

// RefinedAbstraction
public class AdvancedRemote extends Remote {
    public AdvancedRemote(Device device) { super(device); }

    public void mute() { device.setVolume(0); }

    // Example of extra behavior that still delegates to the same implementor
    public void setFavoriteChannel(int channel) { device.setChannel(channel); }
}

// Client demo
public class BridgeDemo {
    public static void main(String[] args) {
        Device tv = new TV();
        Remote remote = new Remote(tv);
        remote.togglePower();
        remote.volumeUp();
        remote.channelUp();
        System.out.println(remote); // Remote{TV{on=true, volume=30, channel=2}}

        Device radio = new Radio();
        AdvancedRemote advanced = new AdvancedRemote(radio);
        advanced.togglePower();
        advanced.setFavoriteChannel(101);
        advanced.mute();
        System.out.println(advanced); // Remote{Radio{on=true, volume=0, channel=101}}

        // Runtime swap of implementor:
        advanced.device = tv; // hot-swap
        advanced.setFavoriteChannel(7);
        System.out.println(advanced); // Remote{TV{on=true, volume=30, channel=7}}
    }
}
```

### Notes on the example

-   `Remote` (Abstraction) doesn’t know *which* Device it controls.

-   `AdvancedRemote` (RefinedAbstraction) adds behavior without altering Device implementations.

-   Adding a **new device** (e.g., `Projector`) requires no change to remotes; adding a **new remote** (e.g., `VoiceRemote`) requires no change to devices.


## Known Uses

-   **Java AWT “peer” architecture**: AWT components (abstractions) delegate to platform-specific peers (implementors).

-   **JDBC**: `java.sql.Connection` etc. abstract over driver implementations from different vendors.

-   **SLF4J / java.util.logging**: logging façade (abstraction) bridged to multiple backends (implementations).

-   **java.nio.file.FileSystem / FileSystemProvider**: abstraction bridged to different file system providers (ZIP, default FS, custom).

-   **Graphics toolkits**: shapes vs. renderers (e.g., SWT/GTK, Skia backends).


## Related Patterns

-   **Abstract Factory**: can create families of Implementors for the Bridge; useful to select a platform bundle.

-   **Strategy**: similar shape (interface + implementations), but Strategy is typically **algorithm substitution** for a single behavior; Bridge separates **entire hierarchies** (abstraction vs. implementation).

-   **Adapter**: makes an existing implementation fit the Implementor interface; often used to plug third-party libs into a Bridge.

-   **Decorator**: adds responsibilities to an Implementor or Abstraction without changing its interface; can wrap either side.

-   **Facade**: provides a simplified interface; can sit on top of a Bridge to hide selection/wiring details.
