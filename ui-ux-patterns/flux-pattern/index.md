# Flux — UI/UX Pattern

## Pattern Name and Classification

**Name:** Flux  
**Category:** UI Architecture · State Management · Unidirectional Data Flow · Frontend Pattern

## Intent

Establish a **predictable, unidirectional data flow** between user actions, data updates, and view rendering, ensuring that UI state changes are deterministic, traceable, and easier to reason about, especially in large-scale, interactive applications.

## Also Known As

Unidirectional Data Flow · State Store Pattern · Reactive Data Architecture · Redux-like Architecture

## Motivation (Forces)

Modern web UIs frequently require dynamic updates, partial refreshes, and cross-component state sharing. Without structure, this leads to **data inconsistency**, **circular dependencies**, and **hard-to-debug side effects**.

Flux introduces **a strict one-way flow** of data, ensuring that state changes always follow the same cycle:

1.  User actions trigger *dispatches*.
    
2.  Dispatchers notify *stores* of state changes.
    
3.  *Stores* update their data and notify *views*.
    
4.  *Views* re-render based on new store data.
    

**Forces at play:**

-   Multiple components depend on shared state (e.g., authentication, preferences).
    
-   Asynchronous data updates (API calls, streams) can cause race conditions.
    
-   Two-way data binding (as in MVC) can create hidden coupling.
    
-   Debugging requires visibility of cause → effect.
    
-   State must be predictable and serializable for time travel debugging and testing.
    

## Applicability

Use Flux when:

-   Building rich, client-heavy single-page applications (SPAs).
    
-   The same data influences multiple UI components.
    
-   You need predictable data flow and robust debugging tools.
    
-   Undo/redo or time-travel debugging is required.
    
-   Server and client logic should share consistent state semantics.
    

Avoid when:

-   The app is small and mostly static.
    
-   Simpler two-way binding (MVC/MVVM) suffices.
    
-   Overhead of stores and dispatchers outweighs complexity.
    

## Structure

**Core Components:**

1.  **Action:** Describes an event that occurred (e.g., `ADD_ITEM`, `DELETE_USER`).
    
2.  **Dispatcher:** Central hub broadcasting actions to stores.
    
3.  **Store:** Holds application state and logic for updating it.
    
4.  **View (UI):** Renders data from stores and triggers actions in response to user input.
    

**Unidirectional Flow:**

```csharp
[User Interaction] 
     ↓ 
  [Action]
     ↓
 [Dispatcher]
     ↓
   [Store]
     ↓
   [View/UI]
```

## Participants

-   **Action Creators:** Encapsulate event generation and payload construction.
    
-   **Dispatcher:** Central mechanism ensuring every store receives actions in the same sequence.
    
-   **Store:** State container that reacts to specific action types, updates data, and emits change events.
    
-   **View (UI Layer):** Subscribes to store changes and renders state-driven views.
    
-   **User:** Interacts with the UI, triggering new actions.
    

## Collaboration

1.  User triggers an interaction (e.g., click, form submit).
    
2.  The View calls an Action Creator, producing an Action.
    
3.  The Dispatcher sends the Action to all registered Stores.
    
4.  Each Store updates its internal state if it cares about that Action.
    
5.  The Store emits a change event.
    
6.  The View re-renders with updated state.
    
7.  Cycle repeats predictably.
    

This strict one-way data flow eliminates feedback loops and keeps system behavior consistent.

## Consequences

**Benefits**

-   Predictable and traceable data changes.
    
-   Simplified debugging — logs can show full state transitions.
    
-   Decoupled components — views and stores communicate only through actions.
    
-   Facilitates hot-reloading, state serialization, and time-travel debugging.
    
-   Works well with React or any declarative view layer.
    

**Liabilities**

-   Verbose setup for small apps.
    
-   Boilerplate-heavy (especially in plain Java).
    
-   Performance overhead if not batched correctly.
    
-   Requires developer discipline to avoid shortcuts (e.g., direct store mutation).
    

## Implementation

**Design Recommendations:**

1.  Keep the Dispatcher as a singleton.
    
2.  Each Store owns its own domain of the state and must be the single source of truth.
    
3.  Use immutable state objects to avoid side effects.
    
4.  Views subscribe to Stores, not to each other.
    
5.  Always trigger state changes through Actions.
    
6.  Keep actions pure — avoid business logic inside them.
    

---

## Sample Code (Java)

Below is a minimal, conceptual **Flux implementation in Java**.  
It uses simple event propagation and a store that notifies listeners when data changes.

```java
// src/main/java/com/example/flux/Action.java
package com.example.flux;

public class Action {
    private final String type;
    private final Object payload;

    public Action(String type, Object payload) {
        this.type = type;
        this.payload = payload;
    }

    public String getType() { return type; }
    public Object getPayload() { return payload; }
}
```

```java
// src/main/java/com/example/flux/Dispatcher.java
package com.example.flux;

import java.util.ArrayList;
import java.util.List;
import java.util.function.Consumer;

public class Dispatcher {
    private final List<Consumer<Action>> listeners = new ArrayList<>();

    public void register(Consumer<Action> listener) {
        listeners.add(listener);
    }

    public void dispatch(Action action) {
        for (Consumer<Action> listener : listeners) {
            listener.accept(action);
        }
    }
}
```

```java
// src/main/java/com/example/flux/Store.java
package com.example.flux;

import java.util.ArrayList;
import java.util.List;

public abstract class Store {
    private final List<Runnable> listeners = new ArrayList<>();

    public void emitChange() {
        for (Runnable l : listeners) {
            l.run();
        }
    }

    public void addChangeListener(Runnable listener) {
        listeners.add(listener);
    }

    public abstract void onAction(Action action);
}
```

```java
// src/main/java/com/example/flux/TodoStore.java
package com.example.flux;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public class TodoStore extends Store {
    private final List<String> todos = new ArrayList<>();

    @Override
    public void onAction(Action action) {
        switch (action.getType()) {
            case "ADD_TODO" -> {
                todos.add((String) action.getPayload());
                emitChange();
            }
            case "CLEAR_TODOS" -> {
                todos.clear();
                emitChange();
            }
        }
    }

    public List<String> getTodos() {
        return Collections.unmodifiableList(todos);
    }
}
```

```java
// src/main/java/com/example/flux/Actions.java
package com.example.flux;

public class Actions {
    private final Dispatcher dispatcher;

    public Actions(Dispatcher dispatcher) {
        this.dispatcher = dispatcher;
    }

    public void addTodo(String text) {
        dispatcher.dispatch(new Action("ADD_TODO", text));
    }

    public void clearTodos() {
        dispatcher.dispatch(new Action("CLEAR_TODOS", null));
    }
}
```

```java
// src/main/java/com/example/flux/View.java
package com.example.flux;

public class View {
    private final TodoStore store;
    private final Actions actions;

    public View(TodoStore store, Actions actions) {
        this.store = store;
        this.actions = actions;
        this.store.addChangeListener(this::render);
    }

    public void render() {
        System.out.println("=== TODO LIST ===");
        store.getTodos().forEach(System.out::println);
        System.out.println("=================");
    }

    public void simulateUserInput() {
        actions.addTodo("Write documentation");
        actions.addTodo("Review pull requests");
        actions.clearTodos();
    }

    public static void main(String[] args) {
        Dispatcher dispatcher = new Dispatcher();
        TodoStore store = new TodoStore();
        dispatcher.register(store::onAction);
        Actions actions = new Actions(dispatcher);
        View view = new View(store, actions);

        view.simulateUserInput();
    }
}
```

**Execution Flow:**

```sql
User → View → Action → Dispatcher → Store → View Update
```

Console Output:

```markdown
=== TODO LIST ===
Write documentation
=================
=== TODO LIST ===
Write documentation
Review pull requests
=================
=== TODO LIST ===
=================
```

---

## Known Uses

-   **React + Redux** (Redux is a Flux implementation emphasizing pure reducers).
    
-   **Facebook Flux Architecture** (original pattern creator).
    
-   **Vuex (Vue.js)** — inspired by Flux with centralized state store.
    
-   **NgRx (Angular)** — Redux-like reactive state management built on RxJS.
    
-   **Recoil / MobX** — alternative reactive state patterns built on similar principles.
    

## Related Patterns

-   **Model-View-Intent (MVI):** Reactive variant emphasizing streams instead of dispatchers.
    
-   **Redux Pattern:** Pure functional evolution of Flux.
    
-   **Observer Pattern:** Stores notify views (reactive re-render).
    
-   **Command Pattern:** Actions resemble commands sent to dispatcher.
    
-   **Mediator Pattern:** Dispatcher centralizes communication among stores.
    
-   **CQRS (Command Query Responsibility Segregation):** Conceptually related in separating intent (actions) from state reads.

