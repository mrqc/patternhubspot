# Event Bus (Mobile) — Mobile App Architecture Pattern

## Pattern Name and Classification

-   **Name:** Event Bus (Mobile)
    
-   **Classification:** In-process **Publish/Subscribe** communication & decoupling pattern for mobile apps (Android/iOS)
    

## Intent

Provide a **decoupled, one-to-many communication** mechanism inside the app. Publishers **post events** without knowing receivers; subscribers **listen to event types** and react. Useful for cross-feature notifications, background→UI signals, and system-wide broadcasts without tight coupling.

## Also Known As

-   Pub/Sub (in-process)
    
-   Notification Center (iOS)
    
-   RxBus / LiveData Bus (Android variants)
    
-   Message/Event Aggregator
    

## Motivation (Forces)

-   **Cross-module signaling:** Background services (BLE/location/downloads) must notify various screens.
    
-   **One-to-many:** Analytics, logging, and UI toasts often fan out.
    
-   **Lifecycle churn:** Activities/Fragments are frequently recreated; direct references are fragile.
    
-   **Decoupling:** Avoids hard dependencies between features/teams.
    

**Tensions**

-   **Hidden coupling:** “Global” buses can mask dependencies; behavior becomes harder to trace.
    
-   **Lifecycle leaks:** Forgetting to unsubscribe → memory leaks / crashes.
    
-   **Threading:** UI must receive on main thread; producers may run off the main thread.
    
-   **Ordering & delivery:** Usually at-least-once, unordered; not a reliable message queue.
    

## Applicability

Use an Event Bus when:

-   You need **in-app broadcast** style communication (one publisher → many listeners).
    
-   Events are **ephemeral** (e.g., “UserLoggedIn”, “ThemeChanged”, “ShowSnackbar”).
    
-   You want to **decouple** background components from UI (e.g., service → multiple screens).
    

Prefer alternatives or constrain the bus when:

-   You’re doing **request/response** or **data flows** → use explicit calls, ViewModel, or repository.
    
-   You need **guaranteed delivery / persistence / ordering** → use a real queue or store state.
    
-   The app is simple → direct callbacks or navigation APIs may be clearer.
    

## Structure

```css
[Publisher(s)] --post(E)---> [Event Bus] --deliver--> [Subscriber A]
                                             └-------> [Subscriber B]
                                             └-------> [Subscriber C]
(typed events; delivery possibly on main thread; subscribers scoped to lifecycle)
```

## Participants

-   **Event:** Immutable, typed message (`UserLoggedIn`, `NetworkLost`).
    
-   **Publisher:** Any component that posts events (repo, service, VM).
    
-   **Subscriber:** Registers interest in a type and handles it (Activity/Fragment/VM).
    
-   **Event Bus / Dispatcher:** Maintains subscriptions, handles thread marshalling, and dispatches.
    
-   **Lifecycle Adapter (optional):** Auto-unsubscribes on `onDestroy` to prevent leaks.
    

## Collaboration

1.  Subscriber **registers** for `EventType` (optionally bound to lifecycle).
    
2.  Publisher **posts** an event instance.
    
3.  Bus matches event type (and supertypes, if supported) and **dispatches** to all subscribers.
    
4.  Unsubscribe happens on lifecycle end or explicitly.
    

## Consequences

**Benefits**

-   **Loose coupling** between features/modules.
    
-   **Fan-out** made easy (analytics, UI notifications).
    
-   **Simplifies background→UI** communication with thread switching.
    

**Liabilities**

-   **Discoverability/debugging:** Harder to trace “who triggers what.”
    
-   **Overuse risk:** Becomes a “global variable” if used for everything.
    
-   **Lifecycle hazards:** Must unsubscribe; otherwise leaks.
    
-   **No strong delivery guarantees:** Don’t use for critical state transfer.
    

## Implementation

1.  **Keep events small & immutable.** Use plain classes/records; avoid passing heavy objects (Views/Contexts).
    
2.  **Scope your bus.** Prefer **feature-local** buses injected via DI; avoid a single global bus unless truly cross-cutting.
    
3.  **Lifecycle safety.** Tie subscriptions to `LifecycleOwner` (Android) or the view lifecycle; auto-unsubscribe.
    
4.  **Threading.** Expose `post()` (current thread) and `postMain()` (main thread) helpers.
    
5.  **Typing.** Subscribe by **class**, not by string topic; consider delivering to supertypes/interfaces if useful.
    
6.  **Observability.** Add lightweight logging around post/subscribe in debug builds.
    
7.  **Don’t model state with a bus.** Keep state in VMs/Stores; emit **events** for occurrences.
    
8.  **Avoid sticky broadcasts** unless you truly need late subscribers to see the last value (prefer state holders instead).
    

---

## Sample Code (Java, Android-friendly; no third-party libs)

A minimal, thread-safe, lifecycle-aware Event Bus.

-   **Typed subscriptions** by `Class<T>`.
    
-   **post** (current thread) and **postMain** (UI thread).
    
-   Optional **LifecycleOwner** binding for auto-unsubscribe.
    

```java
// EventBus.java
package mobile.bus;

import android.os.Handler;
import android.os.Looper;
import androidx.annotation.MainThread;
import androidx.annotation.NonNull;
import androidx.lifecycle.DefaultLifecycleObserver;
import androidx.lifecycle.LifecycleOwner;

import java.util.Map;
import java.util.Set;
import java.util.concurrent.*;
import java.util.function.Consumer;

public final class EventBus {

  public interface Listener<T> { void onEvent(T event); }

  private static final EventBus DEFAULT = new EventBus();
  public static EventBus getDefault() { return DEFAULT; }

  private final ConcurrentMap<Class<?>, CopyOnWriteArraySet<Consumer<?>>> map = new ConcurrentHashMap<>();
  private final Handler main = new Handler(Looper.getMainLooper());

  public EventBus() {}

  /** Subscribe; returns AutoCloseable to easily unsubscribe. */
  public <T> AutoCloseable subscribe(Class<T> type, Listener<T> listener) {
    Consumer<T> c = listener::onEvent;
    map.computeIfAbsent(type, k -> new CopyOnWriteArraySet<>()).add((Consumer<?>) c);
    return () -> {
      Set<Consumer<?>> set = map.get(type);
      if (set != null) set.remove(c);
    };
  }

  /** Subscribe bound to a LifecycleOwner; auto-unsubscribes on onDestroy. */
  public <T> void subscribe(@NonNull LifecycleOwner owner, Class<T> type, Listener<T> listener) {
    AutoCloseable token = subscribe(type, listener);
    owner.getLifecycle().addObserver(new DefaultLifecycleObserver() {
      @Override public void onDestroy(@NonNull LifecycleOwner o) {
        try { token.close(); } catch (Exception ignored) {}
      }
    });
  }

  /** Post on current thread (handlers decide what to do). */
  public void post(Object event) { dispatch(event, false); }

  /** Post ensuring delivery on main thread (useful for UI). */
  public void postMain(Object event) { dispatch(event, true); }

  private void dispatch(Object event, boolean ensureMain) {
    if (event == null) return;
    Runnable deliver = () -> {
      Class<?> evClass = event.getClass();
      // Deliver to exact type and its supertypes/interfaces
      for (Map.Entry<Class<?>, CopyOnWriteArraySet<Consumer<?>>> e : map.entrySet()) {
        if (e.getKey().isAssignableFrom(evClass)) {
          for (Consumer<?> c : e.getValue()) {
            @SuppressWarnings("unchecked") Consumer<Object> cc = (Consumer<Object>) c;
            try { cc.accept(event); } catch (Throwable t) { /* log in debug */ }
          }
        }
      }
    };
    if (ensureMain && Looper.myLooper() != Looper.getMainLooper()) main.post(deliver);
    else deliver.run();
  }
}
```

**Example events**

```java
// Events.java
package mobile.bus;
import java.util.UUID;

public final class Events {
  private Events() {}
  public static final class UserLoggedIn { public final UUID userId; public UserLoggedIn(UUID id){ this.userId=id; } }
  public static final class NetworkChanged { public final boolean online; public NetworkChanged(boolean online){ this.online=online; } }
  public static final class ShowToast { public final String message; public ShowToast(String msg){ this.message=msg; } }
}
```

**Publisher usage (e.g., Repository or Service)**

```java
// AuthRepository.java
package mobile.bus;

import java.util.UUID;

public class AuthRepository {
  public void login(String email, String pass) {
    // ... do work, then:
    EventBus.getDefault().post(new Events.UserLoggedIn(UUID.randomUUID()));
  }
}
```

**Subscriber usage in an Activity/Fragment (lifecycle-safe)**

```java
// HomeFragment.java
package mobile.bus;

import android.os.Bundle;
import android.view.*;
import android.widget.Toast;
import androidx.annotation.*;
import androidx.fragment.app.Fragment;

public class HomeFragment extends Fragment {
  @Nullable @Override
  public View onCreateView(@NonNull LayoutInflater i, @Nullable ViewGroup c, @Nullable Bundle b) {
    var v = new android.widget.FrameLayout(getContext());
    // Subscribe for UI events; auto-unsubscribes on onDestroy
    EventBus bus = EventBus.getDefault();
    bus.subscribe(getViewLifecycleOwner(), Events.ShowToast.class, e ->
        Toast.makeText(requireContext(), e.message, Toast.LENGTH_SHORT).show()
    );
    bus.subscribe(getViewLifecycleOwner(), Events.UserLoggedIn.class, e ->
        bus.postMain(new Events.ShowToast("Welcome, user " + e.userId))
    );
    return v;
  }
}
```

> Notes
> 
> -   Keep events **small, immutable**.
>     
> -   Prefer **feature-scoped** buses injected via DI for modularity (`new EventBus()` per feature).
>     
> -   Use the bus for **notifications**, not for pulling data—expose data via ViewModels/Repositories.
>     

---

## Known Uses

-   **Android:** greenrobot **EventBus** (popular), Square **Otto** (historical), “RxBus” patterns with **RxJava**, **LiveData** or **SharedFlow** used as typed in-app buses.
    
-   **iOS:** **NotificationCenter** plays the same role for in-process broadcasts.
    
-   Large apps with modular features (e.g., super-apps) often use **feature-scoped** event buses to decouple plugin-like modules.
    

## Related Patterns

-   **Observer** (foundational; Event Bus is a centralized, typed Observer).
    
-   **Mediator** (coordinates interactions; an Event Bus is a lightweight mediator).
    
-   **MVVM/MVI** (use Event Bus sparingly; keep **state** in VMs/Stores, use the bus for **one-off events**).
    
-   **Dependency Injection** (inject buses per feature/scope).
    
-   **Broadcast Receiver** (system/IPC level; Event Bus is in-process).
    
-   **Message Queue / Stream** (for guaranteed, cross-process delivery—not replaced by an in-process bus).
    
-   **Clean Architecture (Mobile)** (Event Bus lives in outer layers; domain should not depend on it).
    

---

### Practical guidance

-   Start with **explicit dependencies** (method calls, ViewModels). Add a bus **only where one-to-many decoupling** is clearly beneficial.
    
-   If you introduce a **global bus**, document allowed events and owners; log posts/subscribes in debug builds to aid tracing.
    
-   For **critical flows**, model them as state in a store or ViewModel; emit **events** only for notifications and side effects.

