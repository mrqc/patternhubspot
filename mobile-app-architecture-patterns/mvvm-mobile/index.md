# MVVM (Mobile) — Mobile App Architecture Pattern

## Pattern Name and Classification

-   **Name:** Model–View–ViewModel (Mobile)
    
-   **Classification:** Presentation & State-Management Architecture Pattern for mobile apps (Android/iOS)
    

## Intent

Keep **UI rendering** (View) separate from **presentation state & logic** (ViewModel) and **data/domain** (Model). The **ViewModel** exposes observable **state** and **one-off events**; the **View** observes and renders without knowing data sources.

## Also Known As

-   MVVM (Jetpack on Android / SwiftUI on iOS)
    
-   Presentation Model (historical roots)
    
-   “State-holder + Bindings” (reactive flavor)
    

## Motivation (Forces)

-   **Volatile UI + stable rules:** Screens change often; business rules less so—decouple them.
    
-   **Lifecycle churn:** Mobile views are destroyed/recreated; keep state outside the View.
    
-   **Asynchrony everywhere:** Network, DB, sensors—need a safe place (ViewModel) to orchestrate and expose results.
    
-   **Testability:** ViewModels are plain classes; easy to unit test without UI frameworks.
    

**Tensions**

-   **State modeling discipline:** Without a single source of truth, state/event duplication creeps in.
    
-   **Overuse of two-way bindings:** Can obscure data flow; prefer unidirectional updates.
    
-   **Boilerplate:** Mapping domain → UI state and handling one-off effects adds code (worth it for clarity).
    

## Applicability

Use MVVM when:

-   Your screens maintain **non-trivial state** (loading, errors, partial content, pagination, offline).
    
-   You want **UI-agnostic tests** for presentation logic.
    
-   You need **rotation-proof** state and lifecycle safety.
    

Consider alternatives when:

-   Screen is tiny and static → MVC/MVP might be enough.
    
-   Complex multi-screen flows → pair MVVM with a **Coordinator**.
    

## Structure

```pgsql
User Input                 async calls
   ┌───────────► View ──────────────► ViewModel ───────────► Model (repos/use cases)
   │                 ▲                   │
   │   observes      │   exposes         │ maps domain -> UI State + one-off Events
   └──────── State & Events ◄────────────┘
```

-   **View** observes **State** and **Events**; sends user intents to ViewModel.
    
-   **ViewModel** holds the **single source of truth** for a screen.
    
-   **Model** provides data (repositories, use-cases, entities).
    

## Participants

-   **Model:** Entities, repositories, use-cases (no UI deps).
    
-   **ViewModel:** Lifecycle-aware state holder; exposes `LiveData`/`Flow`/`Observable` to the View.
    
-   **View:** Activity/Fragment/Compose View/SwiftUI View; renders state and forwards intents.
    
-   **State:** Immutable data class representing everything the View needs to render.
    
-   **Event:** One-time side effects (toast, navigation) kept separate from State.
    

## Collaboration

1.  View **observes** `state` and `events` from ViewModel.
    
2.  User interaction → View calls ViewModel intent (`onRefresh()` etc.).
    
3.  ViewModel invokes Model (async), reduces results into new **State**, emits **Events** if needed.
    
4.  View re-renders; no direct calls from View to Model.
    

## Consequences

**Benefits**

-   **Lifecycle-safe:** State survives configuration changes.
    
-   **Testable:** ViewModel logic is plain Java/Kotlin.
    
-   **Clear data flow:** Unidirectional state updates, easier to reason about.
    

**Liabilities**

-   Requires **state modeling** (no ad-hoc widget mutations).
    
-   **Event handling** needs care (avoid re-emitting on rotate).
    
-   Potential **boilerplate** for mappers and state reducers.
    

## Implementation

1.  Define a **State** object (immutable) capturing UI needs (loading, data, error…).
    
2.  Define an **Event** channel for one-offs (snackbars, navigation).
    
3.  Implement a **ViewModel** that exposes `LiveData<State>` (or Flow) and exposes intent methods.
    
4.  Keep domain logic in **Model** (repos/use-cases). ViewModel orchestrates + maps domain → State.
    
5.  In the **View**, observe state/events; render and forward intents.
    
6.  Retain ViewModel via platform helpers (`ViewModelProvider` on Android).
    
7.  Unit test ViewModel with fake repositories.
    

---

## Sample Code (Java, Android — MVVM with AndroidX ViewModel + LiveData)

> Feature: Show a user profile with pull-to-refresh. ViewModel holds state; Activity renders it.  
> (Pure Java to keep it accessible; swap `LiveData` for `Flow` in Kotlin projects.)

### 1) Domain (Model)

```java
// domain/User.java
package mvvm.domain;

import java.util.UUID;

public final class User {
  private final UUID id; private final String name; private final String email;
  public User(UUID id, String name, String email) { this.id = id; this.name = name; this.email = email; }
  public UUID id() { return id; } public String name() { return name; } public String email() { return email; }
}
```

```java
// domain/UserRepository.java
package mvvm.domain;

import java.util.UUID;

public interface UserRepository {
  User getById(UUID id) throws Exception;
}
```

```java
// data/FakeUserRepository.java
package mvvm.data;

import mvvm.domain.*;
import java.util.UUID;

public final class FakeUserRepository implements UserRepository {
  @Override public User getById(UUID id) throws Exception {
    Thread.sleep(400); // emulate network/IO
    return new User(id, "Ada Lovelace", "ada@example.com");
  }
}
```

### 2) Presentation state & events

```java
// vm/UserState.java
package mvvm.vm;

public final class UserState {
  public final boolean loading;
  public final String name;
  public final String email;
  public final String error;

  private UserState(boolean loading, String name, String email, String error) {
    this.loading = loading; this.name = name; this.email = email; this.error = error;
  }
  public static UserState loading() { return new UserState(true, null, null, null); }
  public static UserState success(String name, String email) { return new UserState(false, name, email, null); }
  public static UserState error(String message) { return new UserState(false, null, null, message); }
}
```

```java
// vm/Event.java  (one-time events wrapper)
package mvvm.vm;

import androidx.annotation.Nullable;

/** Simple one-off event wrapper to avoid re-consuming after rotation. */
public final class Event<T> {
  private final T content;
  private boolean handled = false;
  public Event(T content) { this.content = content; }
  @Nullable public T getIfNotHandled() {
    if (handled) return null;
    handled = true; return content;
  }
  public T peek() { return content; }
}
```

### 3) ViewModel

```java
// vm/UserViewModel.java
package mvvm.vm;

import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;
import androidx.lifecycle.ViewModel;

import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import mvvm.domain.User;
import mvvm.domain.UserRepository;

public class UserViewModel extends ViewModel {

  private final UserRepository repo;
  private final ExecutorService io = Executors.newSingleThreadExecutor();

  private final MutableLiveData<UserState> state = new MutableLiveData<>(UserState.loading());
  private final MutableLiveData<Event<String>> events = new MutableLiveData<>();

  private UUID currentId;

  public UserViewModel(UserRepository repo) { this.repo = repo; }

  public LiveData<UserState> state() { return state; }
  public LiveData<Event<String>> events() { return events; }

  public void load(UUID userId) {
    currentId = userId;
    state.postValue(UserState.loading());
    io.submit(() -> {
      try {
        User u = repo.getById(userId);
        state.postValue(UserState.success(u.name(), u.email()));
      } catch (Exception e) {
        state.postValue(UserState.error("Failed to load user"));
        events.postValue(new Event<>("Please try again"));
      }
    });
  }

  public void refresh() {
    if (currentId != null) load(currentId);
  }

  @Override protected void onCleared() {
    io.shutdownNow();
  }
}
```

### 4) View (Activity observing LiveData)

```java
// ui/UserActivity.java
package mvvm.ui;

import android.os.Bundle;
import android.widget.*;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;
import androidx.lifecycle.ViewModel;
import androidx.lifecycle.ViewModelProvider;

import java.util.UUID;

import mvvm.data.FakeUserRepository;
import mvvm.vm.Event;
import mvvm.vm.UserState;
import mvvm.vm.UserViewModel;

public class UserActivity extends AppCompatActivity {

  private TextView name, email, error;
  private ProgressBar progress;
  private Button refresh;

  private UserViewModel vm;

  // Simple factory to pass a repository to the ViewModel (no DI framework needed)
  static class Factory implements ViewModelProvider.Factory {
    @SuppressWarnings("unchecked")
    @Override public <T extends ViewModel> T create(Class<T> modelClass) {
      return (T) new UserViewModel(new FakeUserRepository());
    }
  }

  @Override protected void onCreate(@Nullable Bundle savedInstanceState) {
    super.onCreate(savedInstanceState);

    // Build a tiny UI
    LinearLayout root = new LinearLayout(this);
    root.setOrientation(LinearLayout.VERTICAL);
    progress = new ProgressBar(this);
    name = new TextView(this);
    email = new TextView(this);
    error = new TextView(this); error.setTextColor(0xFFB00020);
    refresh = new Button(this); refresh.setText("Refresh");
    root.addView(progress); root.addView(name); root.addView(email); root.addView(error); root.addView(refresh);
    setContentView(root);

    vm = new ViewModelProvider(this, new Factory()).get(UserViewModel.class);

    // Observe state
    vm.state().observe(this, this::render);

    // Observe one-off events
    vm.events().observe(this, ev -> {
      String msg = ev != null ? ev.getIfNotHandled() : null;
      if (msg != null) Toast.makeText(this, msg, Toast.LENGTH_SHORT).show();
    });

    refresh.setOnClickListener(v -> vm.refresh());

    // First load
    vm.load(UUID.fromString("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"));
  }

  private void render(UserState s) {
    progress.setVisibility(s.loading ? android.view.View.VISIBLE : android.view.View.GONE);
    name.setText(s.name != null ? s.name : "");
    email.setText(s.email != null ? s.email : "");
    error.setText(s.error != null ? s.error : "");
    refresh.setEnabled(!s.loading);
  }
}
```

**Notes**

-   The **ViewModel** is UI-agnostic and unit-testable (inject a fake `UserRepository`).
    
-   **State** is the single source of truth; the View never mutates widgets based on ad-hoc callbacks.
    
-   **Events** are separated from State to avoid replay on rotation.
    

---

## Known Uses

-   **Android Jetpack MVVM** (ViewModel + LiveData/Flow) across most modern Android apps.
    
-   **iOS**—MVVM is common with **Combine**/**SwiftUI** (state + bindings), though idioms differ.
    
-   Companies with large apps (commerce, banking, social) adopt MVVM to keep screens testable and resilient to lifecycle changes.
    

## Related Patterns

-   **MVP / MVC (Mobile):** Alternative presentation patterns; MVVM favors a **state container** rather than callbacks.
    
-   **Clean Architecture (Mobile):** MVVM sits in the presentation ring; ViewModel talks to use-cases.
    
-   **Coordinator:** Handles navigation so ViewModels stay UI-agnostic.
    
-   **Repository Pattern:** Supplies data to ViewModels.
    
-   **Unidirectional Data Flow (MVI/Redux):** A stricter cousin—single event stream → reducer → state.
    
-   **Dependency Injection:** Provide repos/use-cases to ViewModels; scope them properly.

