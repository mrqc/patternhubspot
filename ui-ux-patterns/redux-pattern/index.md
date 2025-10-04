# Redux — UI/UX Pattern

## Pattern Name and Classification

**Name:** Redux  
**Category:** UI/UX · State Management · Unidirectional Data Flow · Predictable State Container

## Intent

Centralize application state in a single **immutable store** updated by **pure reducers** in response to **dispatched actions**, so that UI changes are predictable, testable, and easy to time-travel/debug.

## Also Known As

Single Store · Predictable State Container · Flux (reducer-centric) · Elm-like MVU (in spirit)

## Motivation (Forces)

-   **Predictability:** Complex UIs need deterministic updates; reducers as pure functions give same output for same input.
    
-   **Traceability:** Every state change is caused by an action → perfect audit trail & time-travel.
    
-   **Testability:** Pure functions and serializable actions are trivial to test.
    
-   **Composition:** Many small reducers combine into one root reducer.
    
-   **Asynchrony:** Side effects move to **middleware**, keeping reducers pure.
    
-   **Trade-offs:** Boilerplate (actions/reducers), careful immutability, and mental model of unidirectional flow required.
    

## Applicability

Use Redux when:

-   Multiple views depend on shared state that must be consistent.
    
-   You want **undo/redo**, time-travel debugging, or reproducible bug reports.
    
-   Many events/side effects must be coordinated without coupling UI to data sources.
    
-   You need strict separation between **pure state transitions** and **effects**.
    

Avoid or downsize when:

-   App is small with localized state; simpler context or local component state suffices.
    
-   State is mostly ephemeral UI-only (dialogs, toggles) and doesn’t need global consistency.
    
-   Heavy server state dominated by caching can be better handled with a data-fetching cache (e.g., SWR/Query libs).
    

## Structure

-   **Store:** Single source of truth holding current state tree.
    
-   **Action:** Plain object describing “what happened” (`type` + payload).
    
-   **Reducer:** Pure function `(state, action) → newState`.
    
-   **Dispatcher:** Sends actions through **middleware** chain to the store.
    
-   **Middleware (optional):** Intercepts actions for logging, async (thunks/sagas), analytics, etc.
    
-   **Selector (optional):** Pure read helpers `(state) → derived data`.
    
-   **View:** Subscribes to store; dispatches actions on user events.
    

```scss
User → dispatch(Action) → [Middleware*] → Reducer(s) → New State → View updates
```

## Participants

-   **UI/View Layer:** Renders from state; dispatches actions.
    
-   **Action Creators:** Functions that build actions (may be thunks for async).
    
-   **Reducers:** Domain-focused pure functions.
    
-   **Store:** Holds state, `dispatch`, `getState`, `subscribe`.
    
-   **Middleware:** Cross-cutting concerns (logging, async, batching).
    
-   **Selectors:** Memoized derivations for performance.
    

## Collaboration

1.  UI dispatches an **Action**.
    
2.  **Middleware** may log, transform, or trigger async, then forwards.
    
3.  **Reducers** receive the action, compute **new immutable state**.
    
4.  Store notifies subscribers; UI re-renders based on selectors/state.
    
5.  Async flows dispatch additional actions when I/O completes.
    

## Consequences

**Benefits**

-   Deterministic updates, great debugging & tooling (time-travel).
    
-   Strong separation of concerns; side effects isolated.
    
-   Easy testing and reproducibility (state + action log).
    

**Liabilities**

-   Boilerplate and verbose action plumbing.
    
-   Requires immutability discipline; naive copies can hurt performance.
    
-   Single store encourages global thinking—scope state thoughtfully or split by feature with composition.
    

## Implementation

**Guidelines**

1.  **Keep reducers pure:** No I/O, no mutation; return new objects.
    
2.  **Normalize state:** Avoid deep nesting; use IDs & maps for collections.
    
3.  **Prefer small reducers:** Compose with a `combineReducers` function.
    
4.  **Middleware for effects:** Logging, metrics, async thunks/sagas belong here.
    
5.  **Selectors:** Avoid view logic in components; memoize derived data.
    
6.  **Types:** Use sealed interfaces/records for actions and state (Java 17+).
    
7.  **Testing:** Unit test reducers and selectors; integration test middleware.
    

---

## Sample Code (Java — Minimal Redux Core + Counter/Todos)

> Java 17+ with records/sealed classes. This is a framework-agnostic Redux-style store usable from desktop, Android, or server UIs.

```java
// redux/Action.java
package redux;

public sealed interface Action permits Actions.Increment, Actions.Decrement,
                                      Actions.AddTodo, Actions.ToggleTodo,
                                      Actions.AsyncStarted, Actions.AsyncFinished {
    String type();
}
```

```java
// redux/Actions.java
package redux;

public final class Actions {
    public record Increment() implements Action { public String type() { return "counter/increment"; } }
    public record Decrement() implements Action { public String type() { return "counter/decrement"; } }

    public record AddTodo(String text) implements Action { public String type() { return "todos/add"; } }
    public record ToggleTodo(long id) implements Action { public String type() { return "todos/toggle"; } }

    // For demo async
    public record AsyncStarted(String label) implements Action { public String type() { return "async/started"; } }
    public record AsyncFinished(String label) implements Action { public String type() { return "async/finished"; } }

    private Actions() {}
}
```

```java
// redux/State.java
package redux;

import java.util.*;

public record State(int counter, Map<Long, Todo> todos, boolean loading) {
    public static State initial() {
        return new State(0, new LinkedHashMap<>(), false);
    }
    public record Todo(long id, String text, boolean done) {}
}
```

```java
// redux/Reducer.java
package redux;

@FunctionalInterface
public interface Reducer<S, A extends Action> {
    S reduce(S state, A action);
}
```

```java
// redux/Reducers.java
package redux;

import java.util.*;

public final class Reducers {

    // Root reducer delegates to feature reducers
    public static final Reducer<State, Action> ROOT = (state, action) -> {
        State s1 = reduceCounter(state, action);
        State s2 = reduceTodos(s1, action);
        return reduceAsync(s2, action);
    };

    private static State reduceCounter(State state, Action a) {
        int c = state.counter();
        if (a instanceof Actions.Increment) return new State(c + 1, state.todos(), state.loading());
        if (a instanceof Actions.Decrement) return new State(c - 1, state.todos(), state.loading());
        return state;
        }

    private static State reduceTodos(State state, Action a) {
        if (a instanceof Actions.AddTodo add) {
            Map<Long, State.Todo> next = new LinkedHashMap<>(state.todos());
            long id = next.size() == 0 ? 1 : next.keySet().stream().mapToLong(Long::longValue).max().orElse(0) + 1;
            next.put(id, new State.Todo(id, add.text(), false));
            return new State(state.counter(), next, state.loading());
        }
        if (a instanceof Actions.ToggleTodo tog) {
            Map<Long, State.Todo> next = new LinkedHashMap<>(state.todos());
            State.Todo t = next.get(tog.id());
            if (t != null) next.put(tog.id(), new State.Todo(t.id(), t.text(), !t.done()));
            return new State(state.counter(), next, state.loading());
        }
        return state;
    }

    private static State reduceAsync(State state, Action a) {
        if (a instanceof Actions.AsyncStarted) return new State(state.counter(), state.todos(), true);
        if (a instanceof Actions.AsyncFinished) return new State(state.counter(), state.todos(), false);
        return state;
    }

    private Reducers() {}
}
```

```java
// redux/Store.java
package redux;

import java.util.ArrayList;
import java.util.List;
import java.util.function.Function;

public class Store<S, A extends Action> {
    public interface Listener { void onChange(); }
    public interface Dispatch<A extends Action> { void dispatch(A action); }
    public interface Middleware<S, A extends Action> {
        Dispatch<A> apply(Store<S, A> store, Dispatch<A> next);
    }

    private S state;
    private final Reducer<S, A> reducer;
    private final List<Listener> listeners = new ArrayList<>();
    private Dispatch<A> dispatch;

    @SafeVarargs
    public Store(S initial, Reducer<S, A> reducer, Middleware<S, A>... middleware) {
        this.state = initial;
        this.reducer = reducer;

        // Base dispatch that reduces
        Dispatch<A> base = action -> {
            state = reducer.reduce(state, action);
            listeners.forEach(Listener::onChange);
        };

        // Compose middleware right-to-left
        Dispatch<A> chain = base;
        for (int i = middleware.length - 1; i >= 0; i--) {
            chain = middleware[i].apply(this, chain);
        }
        this.dispatch = chain;
    }

    public S getState() { return state; }
    public void dispatch(A action) { dispatch.dispatch(action); }
    public Runnable subscribe(Listener l) { listeners.add(l); return () -> listeners.remove(l); }
}
```

```java
// redux/middleware/Logger.java
package redux.middleware;

import redux.Action;
import redux.Store;

public final class Logger<S, A extends Action> implements Store.Middleware<S, A> {
    @Override
    public Store.Dispatch<A> apply(Store<S, A> store, Store.Dispatch<A> next) {
        return action -> {
            System.out.println("→ " + action.type());
            next.dispatch(action);
            System.out.println("  state: " + store.getState());
        };
    }
}
```

```java
// redux/middleware/Thunk.java
package redux.middleware;

import redux.Action;
import redux.Store;

import java.util.function.BiConsumer;

// Thunk: allows dispatching functions (BiConsumer<dispatch, getState>) as "actions"
public final class Thunk<S> implements Store.Middleware<S, Action> {
    @Override
    public Store.Dispatch<Action> apply(Store<S, Action> store, Store.Dispatch<Action> next) {
        return action -> {
            if (action instanceof ThunkAction ta) {
                ta.run(next, store::getState);
            } else next.dispatch(action);
        };
    }

    // Wrapper to mark thunks as an Action
    public static final class ThunkAction implements Action {
        private final BiConsumer<Store.Dispatch<Action>, java.util.function.Supplier<?>> body;
        public ThunkAction(BiConsumer<Store.Dispatch<Action>, java.util.function.Supplier<?>> body) { this.body = body; }
        public void run(Store.Dispatch<Action> dispatch, java.util.function.Supplier<?> getState) { body.accept(dispatch, getState); }
        @Override public String type() { return "thunk"; }
    }
}
```

```java
// app/Demo.java
package app;

import redux.*;
import redux.middleware.Logger;
import redux.middleware.Thunk;

public class Demo {
    public static void main(String[] args) {
        var store = new Store<>(
                State.initial(),
                Reducers.ROOT,
                new Logger<>(),
                new Thunk<>()
        );

        store.subscribe(() -> {
            State s = store.getState();
            System.out.printf("Counter=%d, Todos=%d, Loading=%s%n",
                    s.counter(), s.todos().size(), s.loading());
        });

        // Synchronous updates
        store.dispatch(new Actions.Increment());
        store.dispatch(new Actions.AddTodo("Write docs"));
        store.dispatch(new Actions.AddTodo("Review PR"));
        store.dispatch(new Actions.ToggleTodo(1));

        // Async using thunk: simulate fetch
        store.dispatch(new Thunk.ThunkAction((dispatch, getState) -> {
            dispatch.dispatch(new Actions.AsyncStarted("fetch"));
            try { Thread.sleep(200); } catch (InterruptedException ignored) {}
            dispatch.dispatch(new Actions.AddTodo("Fetched item"));
            dispatch.dispatch(new Actions.AsyncFinished("fetch"));
        }));
    }
}
```

**Highlights of the sample**

-   **Single Store** holds a `State` record (counter + todos + loading).
    
-   **Actions** are sealed/records; **Reducers** are pure and return **new** `State`.
    
-   **Middleware:** `Logger` and a simple **Thunk** allow async effects while keeping reducers pure.
    
-   **Subscribe:** Views would bind to `subscribe()` and re-render on changes; this demo prints to console.
    

---

## Known Uses

-   **React + Redux Toolkit** in large SPA frontends (time-travel, DevTools, middleware ecosystem).
    
-   **Angular NgRx**, **Vuex/Pinia**, **MobX-State-Tree** (inspired by Redux concepts).
    
-   **Native apps:** Shared reducer logic across Android/iOS/desktop (Kotlin Multiplatform, Java).
    
-   **Server UIs / CLI:** Predictable state machines with pure reducers.
    

## Related Patterns

-   **Flux:** Conceptual ancestor; Redux centers on a single store and pure reducers.
    
-   **Elm Architecture / MVU:** Similar loop (Model, update via messages, view).
    
-   **CQRS/Event Sourcing:** Actions ~ commands/events; reducers akin to projections (pure, no side effects).
    
-   **Observer:** Store subscriptions notify views on state changes.
    
-   **MVI/MVVM:** Redux can power the state in those presentation patterns; bindings/selectors bridge to the UI.

