# Redux (Mobile) — Mobile App Architecture Pattern

## Pattern Name and Classification

-   **Name:** Redux (Mobile)
    
-   **Classification:** State Management & Unidirectional Data-Flow Pattern for mobile apps
    

## Intent

Provide a **single, predictable source of truth** for UI by keeping all screen state in a **Store** (an immutable tree), updating it only via **Actions** processed by pure **Reducers**, with side-effects handled in **Middleware**. The View observes state and renders; **data flows in one direction**.

## Also Known As

-   Unidirectional Data Flow (UDF)
    
-   Flux/Elm Architecture (close relatives)
    
-   MVI/Redux style
    

## Motivation (Forces)

-   **Lifecycle churn:** Views/activities/fragments are frequently recreated; state should be retained elsewhere.
    
-   **Concurrency:** Network, DB, sensors, and background workers push updates concurrently.
    
-   **Predictability & testability:** Pure reducers + action logs enable replay, time travel, and simple unit tests.
    
-   **Cross-feature coordination:** One place to derive combined state and enforce invariants.
    

**Tensions**

-   **Boilerplate/verbosity:** Actions, reducers, state classes, middleware.
    
-   **Performance pitfalls:** Naïve observers re-render too often; need selectors/diffing.
    
-   **Learning curve:** Immutability + reducers + effect isolation can feel unnatural at first.
    

## Applicability

Use Redux Mobile when:

-   Screens manage **non-trivial, long-lived state** (pagination, filters, offline, forms, background sync).
    
-   Multiple sources can change state (push notifications, services, user input).
    
-   You need **predictable logs** and easy **undo/redo** or **replay**.
    

Consider lighter alternatives when:

-   Feature is small and linear—MVVM with a simple state holder may be enough.
    
-   You don’t need cross-screen/global state, only local screen state.
    

## Structure

```sql
User Intent ──> Action ──> Middleware (effects, async) ──> Reducer (pure) ──> New State ──> View renders
                            │                                      ▲
                            └────────── dispatch follow-up actions ┘
```

## Participants

-   **State:** Immutable tree representing what the UI needs.
    
-   **Action:** Plain object describing a state change request.
    
-   **Reducer:** Pure function `(state, action) -> newState` (no I/O).
    
-   **Store:** Holds state, dispatches actions through middleware chain, notifies subscribers.
    
-   **Middleware:** Intercepts actions for side-effects (network/DB), then dispatches follow-up actions.
    
-   **Selectors:** Pure functions to compute derived view data.
    
-   **View:** Observes state and renders; sends user intents as actions.
    

## Collaboration

1.  View dispatches an **Action** (e.g., `RefreshTapped`).
    
2.  **Middleware** may emit **StartLoading**, call a repository, and later dispatch **Success/Failure** actions.
    
3.  **Reducer** computes a **new immutable State** from every action.
    
4.  **Store** notifies subscribers; View re-renders from state (no manual widget mutation apart from rendering).
    
5.  **Logging/time travel** come from the store’s ordered action log (optional).
    

## Consequences

**Benefits**

-   **Predictability:** Same inputs → same outputs. Easy reasoning and tests.
    
-   **Isolation of effects:** I/O contained in middleware.
    
-   **Debuggability:** Action log, replay, and state snapshots.
    
-   **Composability:** Combine reducers/middleware per feature.
    

**Liabilities**

-   **Boilerplate:** More types and mapping code.
    
-   **Over-centralization:** Dumping everything in global state hurts modularity—prefer **feature stores**.
    
-   **Performance tuning required:** Use selectors, throttling, and targeted subscriptions.
    

## Implementation

1.  **Choose store scope:** Global app store plus **feature stores** (recommended) to avoid a “god state”.
    
2.  **Model state immutably:** final fields + copy/`withX()` methods; avoid in-place mutation.
    
3.  **Keep reducers pure:** No I/O, no time, no random.
    
4.  **Do effects in middleware:** Thunks/sagas/mobs—dispatch **intent** actions, handle async, dispatch results.
    
5.  **Threading:** Reduce and notify on the **main thread** (for UI safety); run I/O in background.
    
6.  **Selectors & memoization:** Derive view data; avoid recompute/re-render.
    
7.  **Persistence:** Optionally serialize state to disk (e.g., on background) and rehydrate on launch.
    
8.  **Testing:** Unit-test reducers with action sequences; middleware with fake dispatch/repo; store with integration tests.
    

---

## Sample Code (Java, Android — minimal Redux core + a counter with async load)

> Pure Java core (no external libs).  
> Store dispatches on any thread; state notifications are marshalled to the **main thread** via `Handler`.

### Core: Action, Reducer, Middleware, Store

```java
// redux/Action.java
package redux;
public interface Action { }
```

```java
// redux/Reducer.java
package redux;
public interface Reducer<S> { S reduce(S state, Action action); }
```

```java
// redux/Dispatcher.java
package redux;
public interface Dispatcher { void dispatch(Action action); }
```

```java
// redux/Middleware.java
package redux;
public interface Middleware<S> {
  void apply(Store<S> store, Action action, Dispatcher next);
}
```

```java
// redux/Store.java
package redux;

import android.os.Handler;
import android.os.Looper;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;

public final class Store<S> implements Dispatcher {
  public interface Subscriber<S> { void onNewState(S state); }

  private final Reducer<S> reducer;
  private final List<Middleware<S>> middleware;
  private volatile S state;
  private final List<Subscriber<S>> subscribers = new CopyOnWriteArrayList<>();
  private final Handler main = new Handler(Looper.getMainLooper());
  private final Dispatcher chain;

  public Store(S initialState, Reducer<S> reducer, List<Middleware<S>> middleware) {
    this.state = initialState; this.reducer = reducer; this.middleware = middleware;
    // compose middleware right-to-left, ending in reduceAndNotify
    Dispatcher last = this::reduceAndNotify;
    for (int i = middleware.size() - 1; i >= 0; i--) {
      Middleware<S> m = middleware.get(i);
      Dispatcher next = last;
      last = action -> m.apply(this, action, next);
    }
    this.chain = last;
  }

  public S getState() { return state; }

  public AutoCloseable subscribe(Subscriber<S> sub) {
    subscribers.add(sub);
    main.post(() -> sub.onNewState(state));
    return () -> subscribers.remove(sub);
  }

  @Override public void dispatch(Action action) { chain.dispatch(action); }

  private synchronized void reduceAndNotify(Action action) {
    S newState = reducer.reduce(state, action);
    if (newState != state) { // reference check; states are immutable
      state = newState;
      main.post(() -> { for (Subscriber<S> s : subscribers) s.onNewState(state); });
    }
  }
}
```

### Feature: Counter domain (State, Actions, Reducer, Middleware)

```java
// counter/CounterState.java
package counter;

public final class CounterState {
  public final int value;
  public final boolean loading;
  public final String error;

  public CounterState(int value, boolean loading, String error) {
    this.value = value; this.loading = loading; this.error = error;
  }
  public static CounterState initial() { return new CounterState(0, false, null); }
  public CounterState withValue(int v) { return new CounterState(v, loading, error); }
  public CounterState withLoading(boolean l){ return new CounterState(value, l, error); }
  public CounterState withError(String e){ return new CounterState(value, loading, e); }
}
```

```java
// counter/Actions.java
package counter;

import redux.Action;

public final class Actions {
  private Actions(){}

  public static final class Increment implements Action { }
  public static final class Decrement implements Action { }
  public static final class LoadFromServer implements Action { }     // intent
  public static final class LoadStarted implements Action { }
  public static final class LoadSucceeded implements Action { public final int value; public LoadSucceeded(int v){ this.value=v; } }
  public static final class LoadFailed implements Action { public final String message; public LoadFailed(String m){ this.message=m; } }
}
```

```java
// counter/CounterReducer.java
package counter;

import redux.Action;
import redux.Reducer;

public final class CounterReducer implements Reducer<CounterState> {
  @Override public CounterState reduce(CounterState s, Action a) {
    if (a instanceof Actions.Increment) return s.withValue(s.value + 1).withError(null);
    if (a instanceof Actions.Decrement) return s.withValue(s.value - 1).withError(null);
    if (a instanceof Actions.LoadStarted) return s.withLoading(true).withError(null);
    if (a instanceof Actions.LoadSucceeded ls) return new CounterState(ls.value, false, null);
    if (a instanceof Actions.LoadFailed lf) return s.withLoading(false).withError(lf.message);
    return s; // unknown action → no change
  }
}
```

```java
// counter/CounterMiddleware.java
package counter;

import redux.*;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Thunk-like async loader: turns LoadFromServer intent into Start → Success/Failed. */
public final class CounterMiddleware implements Middleware<CounterState> {
  private final ExecutorService io = Executors.newSingleThreadExecutor();

  @Override public void apply(Store<CounterState> store, Action action, Dispatcher next) {
    if (action instanceof Actions.LoadFromServer) {
      next.dispatch(new Actions.LoadStarted()); // optimistic UI
      io.submit(() -> {
        try {
          // Simulate network (return a random-ish value)
          Thread.sleep(500);
          int serverValue = (int)(Math.random() * 10);
          store.dispatch(new Actions.LoadSucceeded(serverValue));
        } catch (Exception e) {
          store.dispatch(new Actions.LoadFailed("Network error"));
        }
      });
      return; // handled
    }
    next.dispatch(action); // pass through
  }
}
```

### Android wiring: Activity as the View

```java
// ui/CounterActivity.java
package ui;

import android.os.Bundle;
import android.widget.*;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;

import java.util.List;

import counter.*;
import redux.Store;

public class CounterActivity extends AppCompatActivity {

  private Store<CounterState> store;
  private AutoCloseable sub;

  private TextView valueText, errorText;
  private ProgressBar progress;
  private Button inc, dec, load;

  @Override protected void onCreate(@Nullable Bundle savedInstanceState) {
    super.onCreate(savedInstanceState);

    // --- UI ---
    LinearLayout root = new LinearLayout(this);
    root.setOrientation(LinearLayout.VERTICAL);
    valueText = new TextView(this);
    errorText = new TextView(this); errorText.setTextColor(0xFFB00020);
    progress = new ProgressBar(this);
    inc = new Button(this); inc.setText("Increment");
    dec = new Button(this); dec.setText("Decrement");
    load = new Button(this); load.setText("Load from server");
    root.addView(valueText); root.addView(progress); root.addView(errorText);
    root.addView(inc); root.addView(dec); root.addView(load);
    setContentView(root);

    // --- Store ---
    store = new Store<>(
        CounterState.initial(),
        new CounterReducer(),
        List.of(new CounterMiddleware())
    );

    inc.setOnClickListener(v -> store.dispatch(new Actions.Increment()));
    dec.setOnClickListener(v -> store.dispatch(new Actions.Decrement()));
    load.setOnClickListener(v -> store.dispatch(new Actions.LoadFromServer()));
  }

  @Override protected void onStart() {
    super.onStart();
    sub = store.subscribe(this::render); // get initial state immediately
  }

  @Override protected void onStop() {
    super.onStop();
    try { if (sub != null) sub.close(); } catch (Exception ignored) {}
  }

  private void render(CounterState s) {
    valueText.setText("Value: " + s.value);
    progress.setVisibility(s.loading ? android.view.View.VISIBLE : android.view.View.GONE);
    errorText.setText(s.error != null ? s.error : "");
    // Buttons enabled/disabled as needed
    inc.setEnabled(!s.loading); dec.setEnabled(!s.loading); load.setEnabled(!s.loading);
  }
}
```

> Notes
> 
> -   **Immutability:** `CounterState` is immutable; reducers return **new** instances.
>     
> -   **Effects:** All I/O lives in `CounterMiddleware`; reducers stay pure.
>     
> -   **Threading:** Reducer + subscriber notifications are marshalled onto the **main thread**.
>     
> -   **Scaling out:** Use `combineReducers` (compose reducers by feature) and multiple middlewares (logging, analytics, persistence).
>     

---

## Known Uses

-   **React Native** apps commonly use Redux; the same pattern ports well to native Android/iOS.
    
-   Large Android codebases implement **Redux/MVI** variants (single store or per-feature stores) to manage complex state, offline sync, and background events.
    
-   **Flutter** has redux libraries; **Kotlin** ecosystems use MVI/Redux-style stores (e.g., Mobius, Orbit, ReduxKotlin).
    

## Related Patterns

-   **MVVM / MVI:** MVVM with a single immutable `State` and one-way event flow is very close to Redux.
    
-   **Elm Architecture / Flux:** Conceptual ancestors—single state and reducer/update function.
    
-   **Observer:** Store → subscribers is an observer relationship.
    
-   **Transactional Outbox / Offline First Sync:** Pair Redux state with an outbox and background sync.
    
-   **Coordinator:** Use alongside Redux to keep **navigation** out of reducers.
    
-   **Clean Architecture (Mobile):** Store sits in the presentation layer; reducers call domain/use-cases via middleware.
    

---

**Practical tips**

-   Keep **reducers tiny** and **feature-scoped**; wire them together near the composition root.
    
-   Use **selectors** to limit re-renders and keep `render()` O(1).
    
-   Log actions in debug builds; optionally add a **time-travel** middleware for replay.
    
-   Persist only the **minimal** slice of state (rehydrate on launch), not volatile UI flags.
    
-   For very large apps, prefer **many feature stores** over one global god store.

