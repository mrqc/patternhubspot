# Presentation–Abstraction–Control (PAC) — UI/UX Pattern

## Pattern Name and Classification

**Name:** Presentation–Abstraction–Control (PAC)  
**Category:** UI/UX · Architectural Pattern · Hierarchical Agents · Interactive Systems

## Intent

Structure an interactive application as a **hierarchy of cooperating agents**, where each agent cleanly separates **Presentation** (UI), **Abstraction** (domain/data), and **Control** (mediation, flow, inter-agent communication). PAC improves modularity, parallel development, and supports multiple, heterogeneous interaction modalities.

## Also Known As

PAC Agents · Hierarchical Agent Architecture

## Motivation (Forces)

-   **Heterogeneity:** Complex UIs mix modalities (touch, voice, visualization). Each modality benefits from a self-contained module.
    
-   **Local reasoning:** Keep each unit’s UI, domain state, and coordination logic close together.
    
-   **Hierarchy & composition:** A root agent coordinates sub-agents (e.g., dashboard → charts, filters, notifications).
    
-   **Low coupling across modules:** UI or model changes in one agent shouldn’t ripple globally.
    
-   **Concurrency & distribution:** Agents can be developed, tested, and even deployed separately.
    
-   **Trade-offs:** More moving parts and explicit messaging; risk of “chatty” controllers if boundaries are unclear.
    

## Applicability

Use PAC when:

-   The UI is **modular** (dashboards, multi-tool editors, micro-frontends).
    
-   Multiple **input/output modalities** must be combined.
    
-   Teams own **independent features** that must coordinate through clear seams.
    
-   You need **scalable composition** (root ↔ sub-agents) and isolated failure domains.
    

Avoid or adapt when:

-   The app is small/simple—MVC/Page Controller is sufficient.
    
-   You need a single global, unidirectional state flow (Flux/Redux/MVI may fit better).
    
-   Inter-agent messaging would dwarf actual domain complexity.
    

## Structure

Each **Agent** = Presentation + Abstraction + Control.

```mathematica
┌───────────────────────────────────────────────┐
                 │                 Root Agent                     │
                 │  Presentation   Abstraction   Control          │
                 └────────────┬──────────────┬──────────────┬─────┘
                              │              │              │
                   ┌──────────▼──────┐ ┌─────▼────────┐ ┌───▼─────────┐
                   │   Chart Agent   │ │ Filter Agent  │ │  Alert Agent │
                   │ P | A | C       │ │ P | A | C     │ │ P | A | C     │
                   └─────────────────┘ └───────────────┘ └──────────────┘

          P ↔ C (within agent)   C ↔ A (within agent)   C ↔ C (between agents)
```

-   **Presentation (P):** Renders the agent’s UI and raises user events.
    
-   **Abstraction (A):** Encapsulates domain data/logic/state for the agent.
    
-   **Control (C):** Mediates P↔A, manages agent lifecycle, and exchanges messages with other agents (usually via a parent/child hierarchy or a bus).
    

## Participants

-   **Agent:** Tripartite unit `{P, A, C}` with a public interface (messages).
    
-   **Control:** Internal coordinator for its agent; external collaborator to other Controls.
    
-   **Presentation:** Concrete widgets/views (web, desktop, mobile).
    
-   **Abstraction:** Domain model/repository/service specific to the agent.
    
-   **Mediator/Bus (optional):** Infrastructure to route inter-agent messages.
    

## Collaboration

1.  **User → Presentation:** User acts; Presentation raises an event.
    
2.  **Presentation → Control:** Control validates/interprets and invokes Abstraction.
    
3.  **Control ↔ Abstraction:** Update/query domain state; receive results.
    
4.  **Control → Presentation:** Update view state.
    
5.  **Control ↔ Control (inter-agent):** Publish/handle messages (e.g., “FilterChanged”) to coordinate sibling agents via parent/root.
    

## Consequences

**Benefits**

-   High modularity and team autonomy; each feature is a self-contained agent.
    
-   Supports heterogeneous UIs and incremental composition via hierarchy.
    
-   Clear separation of display, domain, and orchestration concerns.
    
-   Localized testing; agents can be simulated or replaced independently.
    

**Liabilities**

-   More boilerplate (three roles per agent).
    
-   Inter-agent messaging design is non-trivial (naming, routing, error handling).
    
-   Risk of overly central **root Control** becoming a bottleneck.
    
-   Debugging distributed flows requires good tracing/telemetry.
    

## Implementation

**Guidelines**

1.  **One agent per cohesive feature:** Keep agents small and composable.
    
2.  **Thin Presentation, rich Abstraction, explicit Control:** Presentation has no domain rules; Control has orchestration only; Abstraction owns invariants.
    
3.  **Message contracts:** Define typed messages/events for Control↔Control; avoid leaky, ad-hoc coupling.
    
4.  **Hierarchy first, bus later:** Start with parent/child messaging; introduce a lightweight bus when many peers must communicate.
    
5.  **Lifecycle hooks:** `init/start/stop` in Control; detach views safely.
    
6.  **Testing:** Unit-test Abstraction; verify Control logic with fake P/A; contract-test inter-agent messages.
    

---

## Sample Code (Java — Framework-agnostic PAC with a tiny console Presentation)

**Scenario:** A small dashboard with two sub-agents: **FilterAgent** (sets a text filter) and **ListAgent** (shows items filtered). A **RootAgent** wires them and relays messages.

### Common messaging

```java
// pac/core/Message.java
package pac.core;

public sealed interface Message permits FilterChanged, LoadItems, ItemsLoaded {
    String type();
}

// pac/core/FilterChanged.java
package pac.core;
public record FilterChanged(String value) implements Message {
    @Override public String type() { return "FilterChanged"; }
}

// pac/core/LoadItems.java
package pac.core;
public record LoadItems() implements Message {
    @Override public String type() { return "LoadItems"; }
}

// pac/core/ItemsLoaded.java
package pac.core;
import java.util.List;
public record ItemsLoaded(java.util.List<String> items) implements Message {
    @Override public String type() { return "ItemsLoaded"; }
}
```

### Agent contracts

```java
// pac/core/Presentation.java
package pac.core;
public interface Presentation {
    void render(ViewModel vm);
    void attach(Controller controller);
    record ViewModel(String title, java.util.List<String> lines, String hint) {}
}

// pac/core/Abstraction.java
package pac.core;
public interface Abstraction { /* marker for domain services/models */ }

// pac/core/Controller.java
package pac.core;
public interface Controller {
    void onUserAction(String action, String payload); // from Presentation
    void onMessage(Message msg);                       // from other agents
    void start();                                      // lifecycle
    void stop();
}
```

### Filter Agent (P, A, C)

```java
// pac/filter/FilterModel.java
package pac.filter;
import pac.core.Abstraction;
public class FilterModel implements Abstraction {
    private String value = "";
    public String get() { return value; }
    public void set(String v) { value = v == null ? "" : v.trim(); }
}
```

```java
// pac/filter/FilterPresentationConsole.java
package pac.filter;
import pac.core.Controller;
import pac.core.Presentation;

public class FilterPresentationConsole implements Presentation {
    private Controller controller;
    @Override public void render(ViewModel vm) {
        System.out.println("[" + vm.title() + "] " + vm.hint());
    }
    @Override public void attach(Controller c) { this.controller = c; }

    // For demo, expose a method to simulate user input:
    public void simulateUserTyping(String text) {
        controller.onUserAction("input", text);
    }
}
```

```java
// pac/filter/FilterController.java
package pac.filter;

import pac.core.*;
public class FilterController implements Controller {
    private final FilterModel model;
    private final Presentation view;
    private Controller parent; // Root controller for inter-agent messages

    public FilterController(FilterModel model, Presentation view) {
        this.model = model; this.view = view; view.attach(this);
    }
    public void setParent(Controller parent) { this.parent = parent; }

    @Override public void onUserAction(String action, String payload) {
        if ("input".equals(action)) {
            model.set(payload);
            // Notify siblings via the parent/root
            if (parent != null) parent.onMessage(new FilterChanged(model.get()));
            // Update own view (hint)
            view.render(new Presentation.ViewModel("Filter", java.util.List.of(), "Current: " + model.get()));
        }
    }

    @Override public void onMessage(Message msg) { /* FilterAgent does not consume others in this demo */ }
    @Override public void start() { view.render(new Presentation.ViewModel("Filter", java.util.List.of(), "Type to filter…")); }
    @Override public void stop() {}
}
```

### List Agent (P, A, C)

```java
// pac/list/ListRepo.java
package pac.list;
import pac.core.Abstraction;
import java.util.List;
import java.util.stream.Collectors;

public class ListRepo implements Abstraction {
    private final java.util.List<String> all = java.util.List.of("alpha","beta","gamma","delta","alphabet","gamut");
    public List<String> loadFiltered(String filter) {
        if (filter == null || filter.isBlank()) return all;
        String f = filter.toLowerCase();
        return all.stream().filter(s -> s.contains(f)).collect(Collectors.toList());
    }
}
```

```java
// pac/list/ListPresentationConsole.java
package pac.list;
import pac.core.Presentation;

public class ListPresentationConsole implements Presentation {
    @Override public void render(ViewModel vm) {
        System.out.println("[" + vm.title() + "]");
        vm.lines().forEach(line -> System.out.println(" - " + line));
        if (vm.lines().isEmpty()) System.out.println(" (no items)");
    }
    @Override public void attach(pac.core.Controller controller) { /* not used in list view */ }
}
```

```java
// pac/list/ListController.java
package pac.list;

import pac.core.*;

public class ListController implements Controller {
    private final ListRepo repo;
    private final Presentation view;
    private String currentFilter = "";

    public ListController(ListRepo repo, Presentation view) { this.repo = repo; this.view = view; view.attach(this); }

    @Override public void onUserAction(String action, String payload) { /* list is passive in this demo */ }

    @Override public void onMessage(Message msg) {
        if (msg instanceof FilterChanged fc) {
            currentFilter = fc.value();
            var items = repo.loadFiltered(currentFilter);
            view.render(new Presentation.ViewModel("List (filter='" + currentFilter + "')", items, ""));
        } else if (msg instanceof LoadItems) {
            var items = repo.loadFiltered(currentFilter);
            view.render(new Presentation.ViewModel("List", items, ""));
        }
    }

    @Override public void start() { onMessage(new LoadItems()); }
    @Override public void stop() {}
}
```

### Root Agent (Control coordinating two sub-agents)

```java
// pac/root/RootController.java
package pac.root;

import pac.core.*;
import pac.filter.*;
import pac.list.*;

public class RootController implements Controller {
    private final FilterController filter;
    private final ListController list;

    public RootController() {
        // Compose agents
        var filterP = new FilterPresentationConsole();
        var listP   = new ListPresentationConsole();
        this.filter = new FilterController(new FilterModel(), filterP);
        this.list   = new ListController(new ListRepo(), listP);

        // Parent linkage for inter-agent messaging (Filter -> Root -> List)
        filter.setParent(this);

        // Demo: expose filter presentation to simulate user input
        this.filterPresentation = filterP;
    }

    private final FilterPresentationConsole filterPresentation;

    @Override public void onUserAction(String action, String payload) { /* Root receives none from UI in this demo */ }

    @Override public void onMessage(Message msg) {
        // Simple routing: root forwards to interested children
        if (msg instanceof FilterChanged || msg instanceof LoadItems) {
            list.onMessage(msg);
        } else if (msg instanceof ItemsLoaded) {
            // broadcast or handle globally if needed
        }
    }

    @Override public void start() {
        filter.start();
        list.start();
        // Simulate interactions
        filterPresentation.simulateUserTyping("alp");
        filterPresentation.simulateUserTyping("ga");
    }
    @Override public void stop() {}

    // Entry point
    public static void main(String[] args) {
        new RootController().start();
    }
}
```

**What this shows**

-   Each feature is an **agent** with **P/A/C**.
    
-   **Control** mediates inside the agent and uses **messages** between agents.
    
-   The **root** composes and forwards messages, avoiding tight coupling between Filter and List.
    

---

## Known Uses

-   **Multimedia & multimodal UIs:** Speech/gesture subsystems cooperating via a root controller.
    
-   **Complex editors/dashboards:** Independent tool panels (layers, timeline, properties) communicating via PAC.
    
-   **Distributed HMIs (automotive/industrial):** Separate agents per instrument cluster widget coordinated by a root.
    
-   **Historic influence:** PAC informed later modular UI architectures and micro-frontend thinking.
    

## Related Patterns

-   **MVC / MVP / MVVM:** PAC generalizes them by organizing UI into **agents** with P/A/C inside each.
    
-   **Mediator:** The **Control** role often acts as a mediator within and across agents.
    
-   **Observer / Pub-Sub:** Common mechanism for Control↔Control messaging.
    
-   **Front Controller / Page Controller:** PAC can live under a front controller in web apps, with each page composed of multiple agents.
    
-   **Micro-Frontends / Plugin Architecture:** Organizational analogs; PAC provides the intra-module structure.

