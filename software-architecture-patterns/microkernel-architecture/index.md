# Microkernel Architecture — Software Architecture Pattern

## Pattern Name and Classification

-   **Name:** Microkernel Architecture
    
-   **Classification:** Structural / Modularity & Extensibility / Plug-in (a.k.a. plugin-based architecture)
    

## Intent

Keep a **minimal, stable core (the kernel)** that offers essential services and well-defined **extension points**. All variable or domain-specific capabilities are delivered as **plug-ins** that can be **added, replaced, or updated** with minimal impact on the kernel.

## Also Known As

-   Plug-in Architecture
    
-   Plug-in Host / Extension Framework
    
-   Eclipse/IDE-style Architecture
    

## Motivation (Forces)

-   **Product lines & variability:** different customers need different features.
    
-   **Evolvability:** add/upgrade capabilities without redeploying the whole system.
    
-   **Isolation:** faults or heavy workloads in one feature shouldn’t crash the host.
    
-   **Team autonomy:** plug-ins can be developed/released independently.
    
-   **Stability vs. change:** keep kernel small and stable; push volatility to plug-ins.
    

The microkernel separates **stable contracts** from **evolving implementations**, enabling optional features, experiments, and marketplace ecosystems.

## Applicability

Use when:

-   You ship a **platform** consumed by many extensions (IDEs, analytics platforms, gateways).
    
-   You need **customer-specific features** without forking the core.
    
-   Runtime **enable/disable** of features is valuable (A/B tests, trials).
    
-   You want strong **backward compatibility** via versioned extension points.
    

Avoid when:

-   The system is small and unlikely to vary.
    
-   Features are tightly coupled with complex cross-cutting dependencies (may require microservices or modular monolith + eventing instead).
    

## Structure

-   **Kernel:** lifecycle management, plugin registry, contracts (SPIs), messaging/event bus, resource management, configuration, security sandboxing.
    
-   **Extension Points (SPIs):** stable interfaces defined by the kernel.
    
-   **Plug-ins:** implement SPIs; deployed as modules/JARs; loaded by the kernel; communicate only through contracts.
    
-   **Adapter/Bridge (optional):** to “wrap” legacy modules into the SPI.
    
-   **Plugin Loader:** discovers, verifies, and isolates plug-ins (class loaders, sandbox).
    
-   **Management UI/API:** install, enable, disable, update.
    

```pgsql
+---------------------------+
|          Kernel           |  core services: lifecycle, registry, event bus,
|  - Extension Points (SPIs)|  config, security, logging
|  - Plugin Loader          |
+--+---------------------+--+
   |                     |
   v                     v
+------+            +---------+      ... N plugins
|PlugIn| implements | PlugIn  |
|  A   |<-----------|   B     |
+------+    SPI     +---------+
```

## Participants

-   **Kernel / Host** — owns SPIs, lifecycle (init/start/stop), plugin registry, event bus.
    
-   **Plugin Interface (SPI)** — contracts (e.g., `Ingestor`, `Processor`, `Exporter`).
    
-   **Plugins** — modules implementing SPIs; contain metadata (id, version, deps).
    
-   **Plugin Loader** — discovery (filesystem, ServiceLoader, remote), verification, isolation.
    
-   **Event Bus** — decoupled communication among plugins and kernel.
    
-   **Management API** — install/update/enable/disable and health.
    

## Collaboration

1.  **Kernel boot**: load configuration, discover plug-ins, verify compatibility.
    
2.  **Install**: resolve dependencies, create classloader, instantiate, call `initialize(context)`.
    
3.  **Activate**: register capabilities (handlers, routes) and subscribe to events; kernel announces readiness.
    
4.  **Runtime**: events/requests flow through kernel to matching plugins; plugins may publish new events.
    
5.  **Deactivate/Update**: kernel calls `stop()`; unloads classes/resources; swaps version if supported.
    

## Consequences

**Benefits**

-   **Extensibility & customizability** without changing the core.
    
-   **Independent delivery cadence** per plugin; marketplace ecosystems.
    
-   **Fault isolation** (with classloader/process boundaries).
    
-   **Testability** of core independent from plugins.
    

**Liabilities**

-   **Versioning & compatibility** management across SPIs and plugins.
    
-   **Classloader complexity** (isolation, shading, split packages).
    
-   **Security**: plugins are code—need sandboxing/signing.
    
-   **Debuggability** across many boundaries; needs good observability.
    

## Implementation

### Design Guidelines

-   Minimize kernel responsibilities: **lifecycle, registry, contracts, events, config**.
    
-   Define **clear SPIs** with small surface area; version them (e.g., `spi.v1`).
    
-   Provide a **PluginContext** for services (logging, config, event bus, storage handles).
    
-   Isolate plugins via **separate classloaders**; optional process isolation for untrusted code.
    
-   Use **semantic versioning** and capability constraints (requires/provides).
    
-   Add **observability hooks**: health, metrics per plugin, structured logs with plugin id.
    
-   Support **hot enable/disable**; hot reload only if you can guarantee safe resource handoff.
    
-   For data paths, prefer **message/event interfaces** to prevent tight coupling.
    

### Typical Extension Point Examples

-   **Pipeline stages:** Source → Transform → Sink.
    
-   **Command/Action** handlers.
    
-   **Authentication/Authorization** providers.
    
-   **Domain adapters** (payment providers, storage backends).
    
-   **Language/tool support** (parsers, formatters, linters).
    

---

## Sample Code (Java)

A minimal microkernel with:

-   Kernel (registry, event bus, lifecycle)
    
-   SPI: `Plugin` and a `CommandProvider` extension point
    
-   Loader using Java’s `ServiceLoader` (simple) or directory scanning (sketch)
    
-   Two sample plugins
    

> Java 17+. In real systems, use separate JARs for plugins and a custom classloader; here we keep it simple.

```java
// spi/Plugin.java
package spi;
public interface Plugin {
  String id();
  String version();
  void initialize(PluginContext ctx) throws Exception;
  void start() throws Exception;
  void stop() throws Exception;
}
```

```java
// spi/PluginContext.java
package spi;
import java.util.function.Consumer;

public interface PluginContext {
  EventBus eventBus();
  Config config();
  Logger logger(String name);

  interface EventBus {
    <T> void publish(String topic, T payload);
    <T> void subscribe(String topic, Class<T> type, Consumer<T> handler);
  }
  interface Config {
    String get(String key, String defaultValue);
  }
  interface Logger {
    void info(String msg);
    void error(String msg, Throwable t);
  }
}
```

```java
// spi/CommandProvider.java
package spi;
import java.util.Map;

public interface CommandProvider extends Plugin {
  /** Commands exposed by the plugin: name -> handler */
  Map<String, Command> commands();
  interface Command {
    String name();
    String description();
    String execute(String[] args) throws Exception;
  }
}
```

```java
// kernel/Kernel.java
package kernel;
import spi.*;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Consumer;

public class Kernel implements PluginContext {
  private final Map<String, Plugin> plugins = new ConcurrentHashMap<>();
  private final SimpleEventBus bus = new SimpleEventBus();
  private final Config config = key -> System.getProperty(key); // trivial config
  private final Map<String, CommandProvider.Command> commandRegistry = new ConcurrentHashMap<>();

  public void boot() throws Exception {
    // Discover via ServiceLoader (plugins must have META-INF/services/spi.Plugin)
    ServiceLoader<Plugin> loader = ServiceLoader.load(Plugin.class);
    for (Plugin p : loader) {
      register(p);
    }
    // Start after all initialized to allow cross-registration
    for (Plugin p : plugins.values()) p.start();
    log().info("Kernel booted with " + plugins.size() + " plugins and " + commandRegistry.size() + " commands.");
  }

  private void register(Plugin p) throws Exception {
    if (plugins.containsKey(p.id())) throw new IllegalStateException("Duplicate plugin id: " + p.id());
    p.initialize(this);
    plugins.put(p.id(), p);
    if (p instanceof CommandProvider cp) {
      cp.commands().forEach((name, cmd) -> {
        if (commandRegistry.putIfAbsent(name, cmd) != null)
          throw new IllegalStateException("Duplicate command: " + name);
      });
    }
    log().info("Registered plugin " + p.id() + "@" + p.version());
  }

  public void shutdown() {
    plugins.values().forEach(p -> {
      try { p.stop(); } catch (Exception e) { log().error("Stop failed for " + p.id(), e); }
    });
  }

  /** Execute a command exposed by any plugin */
  public String exec(String name, String... args) throws Exception {
    var cmd = commandRegistry.get(name);
    if (cmd == null) throw new IllegalArgumentException("Unknown command: " + name);
    return cmd.execute(args);
  }

  // --- PluginContext impls ---
  @Override public EventBus eventBus() { return bus; }
  @Override public Config config() { return (k, d) -> Optional.ofNullable(config.get(k)).orElse(d); }
  @Override public PluginContext.Logger logger(String name) { return new SimpleLogger(name); }
  private PluginContext.Logger log() { return logger("kernel"); }

  // --- Simple in-memory EventBus & Logger ---
  static class SimpleEventBus implements PluginContext.EventBus {
    private final Map<String, List<Consumer<Object>>> subs = new ConcurrentHashMap<>();
    public <T> void publish(String topic, T payload) {
      subs.getOrDefault(topic, List.of()).forEach(h -> h.accept(payload));
    }
    @SuppressWarnings("unchecked")
    public <T> void subscribe(String topic, Class<T> type, Consumer<T> handler) {
      subs.computeIfAbsent(topic, k -> new ArrayList<>()).add((Consumer<Object>) handler);
    }
  }
  static class SimpleLogger implements PluginContext.Logger {
    private final String name;
    SimpleLogger(String name){ this.name = name; }
    public void info(String msg){ System.out.println("[INFO]["+name+"] " + msg); }
    public void error(String msg, Throwable t){ System.err.println("[ERR]["+name+"] " + msg); t.printStackTrace(); }
  }
}
```

```java
// plugins/HelloPlugin.java
package plugins;
import spi.*;

import java.util.Map;

public class HelloPlugin implements CommandProvider {
  private PluginContext.Logger log;

  @Override public String id() { return "hello"; }
  @Override public String version() { return "1.0.0"; }

  @Override public void initialize(PluginContext ctx) {
    this.log = ctx.logger("hello");
    ctx.eventBus().subscribe("greetings", String.class, s -> log.info("heard: " + s));
    log.info("Initialized");
  }
  @Override public void start() { log.info("Started"); }
  @Override public void stop() { log.info("Stopped"); }

  @Override public Map<String, Command> commands() {
    return Map.of(
      "hello", new Command() {
        public String name(){ return "hello"; }
        public String description(){ return "Greets a user"; }
        public String execute(String[] args) { return "Hello " + (args.length>0?args[0]:"World") + "!"; }
      }
    );
  }
}
```

```java
// plugins/PublishPlugin.java
package plugins;
import spi.*;

import java.util.Map;

public class PublishPlugin implements CommandProvider {
  private PluginContext ctx;
  @Override public String id() { return "publisher"; }
  @Override public String version() { return "1.0.0"; }
  @Override public void initialize(PluginContext ctx) { this.ctx = ctx; }
  @Override public void start() { }
  @Override public void stop() { }

  @Override public Map<String, Command> commands() {
    return Map.of(
      "broadcast", new Command() {
        public String name(){ return "broadcast"; }
        public String description(){ return "Publishes a message to 'greetings' topic"; }
        public String execute(String[] args) {
          String msg = String.join(" ", args);
          ctx.eventBus().publish("greetings", msg);
          return "published";
        }
      }
    );
  }
}
```

```java
// app/Main.java
package app;
import kernel.Kernel;

public class Main {
  public static void main(String[] args) throws Exception {
    Kernel kernel = new Kernel();
    kernel.boot(); // discovers HelloPlugin & PublishPlugin via ServiceLoader

    System.out.println(kernel.exec("hello", "Alice"));
    System.out.println(kernel.exec("broadcast", "Hi", "from", "Plugin!"));

    kernel.shutdown();
  }
}
```

**How to wire ServiceLoader (for each plugin JAR)**

```bash
# In plugin JAR:
META-INF/services/spi.Plugin


# with one line per implementor:
plugins.HelloPlugin
plugins.PublishPlugin
```

**What this demonstrates**

-   A **tiny kernel** exposing **SPIs** and an **event bus**.

-   Plugins discovered via **ServiceLoader**, initialized with a **PluginContext**.

-   **Extension point** `CommandProvider` that registers commands into the kernel.

-   Decoupled collaboration via **topics** (`greetings`) between plugins.


> Production: separate JARs, **signature verification**, **per-plugin classloaders**, sandboxing (SecurityManager alternatives / module system / process isolation), rich dependency metadata, hot-reload strategy, and observability (metrics & health endpoints per plugin).

## Known Uses

-   **IDEs** (Eclipse, IntelliJ): core platform + hundreds of plugins.

-   **Build tools** (Gradle, Maven): tasks/goals as plugins.

-   **API Gateways & ESBs**: policies, auth providers, transformations as plugins.

-   **Data/Stream processors**: sources, transforms, sinks (e.g., Logstash, Flink connectors).

-   **Browsers** and **editors**: extensions for features and themes.

-   **Game engines**: gameplay logic and assets via mod/plugins.


## Related Patterns

-   **Microservices** — runtime decomposition across processes; microkernel is in-process modularity.

-   **Hexagonal/Clean Architecture** — strong boundaries; plug-ins are adapter implementations.

-   **Service Provider Interface (SPI)** — Java mechanism often used in microkernels.

-   **Event-Driven Architecture** — event bus in the kernel decouples plug-ins.

-   **Module System (JPMS/OSGi)** — packaging & isolation foundations for plugins.


---

## Implementation Tips

-   Treat SPIs as **public contracts**: version them and avoid leaking internal types.

-   Provide a **reference SDK** and testing harness for plugin developers.

-   Enforce **compatibility checks** and deny loading incompatible versions.

-   Add **kill switches** and timeouts around plugin calls.

-   Persist plugin **state/config** separately to allow safe updates.

-   Create **observability dashboards** (per-plugin errors, init time, memory, event rates).

-   If trust is low, consider **out-of-process plugins** communicating via RPC for isolation.
