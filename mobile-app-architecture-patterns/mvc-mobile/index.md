# MVC (Mobile) — Mobile App Architecture Pattern

## Pattern Name and Classification

-   **Name:** Model–View–Controller (Mobile)
    
-   **Classification:** Presentation & UI Architecture Pattern (separation of concerns for mobile apps)
    

## Intent

Separate **what the app does** (Model), **what the user sees** (View), and **how the app responds to input and orchestrates flows** (Controller). On mobile, this typically maps to **Model (domain/data)**, **View (XML/custom views)**, and **Controller (Activity/Fragment/ViewController)**.

## Also Known As

-   Cocoa MVC (iOS)
    
-   Activity/Fragment-as-Controller (Android)
    
-   “Massive View Controller” (anti-pattern risk)
    

## Motivation (Forces)

-   **UI changes often**; domain rules less so → isolate them.
    
-   **Device lifecycle churn** (rotation/backgrounding) requires a clear owner for UI state and events.
    
-   **Parallel work**: designers iterate on views while devs refine models.
    
-   **Testability**: business logic should be testable without the UI toolkit.
    

**Tensions**

-   On mobile, it’s easy to pile logic into the Controller (Activity/Fragment/UIViewController) → *massive controller*.
    
-   Views have lifecycles; models generally don’t—coordination is required.
    
-   Async work (network/DB) must not block the UI thread.
    

## Applicability

Use MVC when:

-   Building small-to-medium apps or features where a **simple, explicit split** is enough.
    
-   You want minimal ceremony compared to MVVM/MVI, but better structure than “everything in Activity”.
    

Consider alternatives when:

-   Complex state & async flows dominate (MVVM/MVI + state holder may be superior).
    
-   Cross-screen coordination and navigation rules are non-trivial (add **Coordinator** pattern).
    

## Structure

```pgsql
User Input         Updates/Commands             Data/Events
   ┌───────────► Controller ───────────────► Model (domain, repos)
   │                 │                               │
   │                 └── ViewState/Rendering ────────┘
   └──── View (renders UI, forwards intents) ◄───────┘
```

-   **Controller** listens to View events, invokes Model operations, transforms results to **ViewState**, and updates the View.
    
-   **View** is passive: renders state and exposes user intents via callbacks/listeners.
    
-   **Model** contains domain entities, services, repositories.
    

## Participants

-   **Model:** Entities, use-cases, repositories (HTTP/DB).
    
-   **View:** XML layouts, custom views, adapters. No domain logic.
    
-   **Controller:** Activity/Fragment (Android) or UIViewController (iOS). Handles input, navigation, threading, and mapping Model → View.
    

## Collaboration

1.  View raises an **intent** (e.g., “Load user”).
    
2.  Controller handles it, calls Model (repository/use-case).
    
3.  Model returns data (often asynchronously).
    
4.  Controller maps data/errors to **ViewState** and calls View’s render methods.
    
5.  Controller may navigate to other screens.
    

## Consequences

**Benefits**

-   Clear separation; easy to reason about small features.
    
-   Low ceremony; fits native platform paradigms.
    
-   View remains dumb → easier styling/theming/swapping.
    

**Liabilities**

-   **Massive Controller** risk: too much logic in Activity/Fragment/UIViewController.
    
-   Harder lifecycle management vs. VM-based patterns; must handle rotations carefully.
    
-   Without discipline/tests, business logic leaks into the Controller.
    

## Implementation

1.  **Define passive views** exposing:
    
    -   `render(State)` to display data & loading/error.
        
    -   Listener interfaces for user intents.
        
2.  **Keep controllers lean**:
    
    -   Delegate business logic to **use-cases/repositories** in the Model.
        
    -   Use **executors**/coroutines to keep work off the main thread.
        
    -   Convert results to a small **ViewState** object.
        
3.  **Threading & lifecycle**:
    
    -   Cancel in-flight work on `onStop()` or `onDestroyView()` as appropriate.
        
    -   Re-render state on recreation (e.g., keep last state in controller or saved state).
        
4.  **Testing**:
    
    -   Unit-test Model first.
        
    -   For the Controller, fake the View and assert interactions (`render(...)` calls).
        
5.  **Guardrails to avoid massive controllers**:
    
    -   Extract mappers, formatters, and navigation helpers.
        
    -   For complex flows, combine MVC with a **Coordinator**.
        

---

## Sample Code (Java, Android — minimal clean MVC)

> Feature: Display a user profile and allow manual refresh.
> 
> -   **Model:** `User`, `UserRepository` (fake network)
>     
> -   **View:** `UserView` custom view with `render(State)` and a `Listener`
>     
> -   **Controller:** `UserActivity` orchestrates, threads, and navigation
>     

### Model

```java
// domain/User.java
package mvc.sample.domain;

import java.util.UUID;

public final class User {
  private final UUID id; private final String name; private final String email;
  public User(UUID id, String name, String email) { this.id = id; this.name = name; this.email = email; }
  public UUID id() { return id; } public String name() { return name; } public String email() { return email; }
}
```

```java
// domain/UserRepository.java
package mvc.sample.domain;

import java.util.UUID;

public interface UserRepository {
  User getById(UUID id) throws Exception;
}
```

```java
// data/FakeUserRepository.java
package mvc.sample.data;

import java.util.UUID;
import mvc.sample.domain.*;

public final class FakeUserRepository implements UserRepository {
  @Override public User getById(UUID id) throws Exception {
    Thread.sleep(500); // emulate network
    return new User(id, "Ada Lovelace", "ada@example.com");
  }
}
```

### View (passive)

```java
// ui/UserView.java
package mvc.sample.ui;

import android.content.Context;
import android.util.AttributeSet;
import android.view.View;
import android.widget.*;
import androidx.annotation.Nullable;

public class UserView extends LinearLayout {

  public interface Listener { void onRefreshClicked(); }

  private ProgressBar progress;
  private TextView name, email, error;
  private Button refresh;
  private Listener listener;

  public UserView(Context c) { super(c); init(c); }
  public UserView(Context c, @Nullable AttributeSet a) { super(c, a); init(c); }

  private void init(Context c) {
    setOrientation(VERTICAL);
    int pad = (int) (16 * c.getResources().getDisplayMetrics().density);
    setPadding(pad, pad, pad, pad);

    progress = new ProgressBar(c);
    name = new TextView(c);
    email = new TextView(c);
    error = new TextView(c);
    error.setTextColor(0xFFB00020);
    refresh = new Button(c); refresh.setText("Refresh");

    addView(progress, new LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT));
    addView(name); addView(email); addView(error); addView(refresh);

    refresh.setOnClickListener(v -> { if (listener != null) listener.onRefreshClicked(); });
  }

  public void setListener(Listener l) { this.listener = l; }

  // ViewState to render
  public static final class State {
    public final boolean loading; public final String name; public final String email; public final String error;
    public State(boolean loading, String name, String email, String error) {
      this.loading = loading; this.name = name; this.email = email; this.error = error;
    }
    public static State loading() { return new State(true, null, null, null); }
    public static State success(String n, String e) { return new State(false, n, e, null); }
    public static State error(String m) { return new State(false, null, null, m); }
  }

  public void render(State s) {
    progress.setVisibility(s.loading ? VISIBLE : GONE);
    name.setText(s.name != null ? s.name : "");
    email.setText(s.email != null ? s.email : "");
    error.setText(s.error != null ? s.error : "");
    refresh.setEnabled(!s.loading);
  }
}
```

### Controller

```java
// ui/UserActivity.java
package mvc.sample.ui;

import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;

import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import mvc.sample.data.FakeUserRepository;
import mvc.sample.domain.User;
import mvc.sample.domain.UserRepository;

public class UserActivity extends AppCompatActivity implements UserView.Listener {

  private final ExecutorService io = Executors.newSingleThreadExecutor();
  private final Handler main = new Handler(Looper.getMainLooper());
  private UserRepository repo;
  private UserView view;
  private UUID userId;

  @Override protected void onCreate(@Nullable Bundle savedInstanceState) {
    super.onCreate(savedInstanceState);

    // Compose Model
    repo = new FakeUserRepository();
    userId = UUID.fromString("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa");

    // Compose View
    view = new UserView(this);
    view.setListener(this);
    setContentView(view);

    // Initial load
    loadUser();
  }

  @Override protected void onDestroy() {
    super.onDestroy();
    io.shutdownNow(); // cancel work; in real apps consider more granular cancellation
  }

  @Override public void onRefreshClicked() { loadUser(); }

  private void loadUser() {
    view.render(UserView.State.loading());
    io.submit(() -> {
      try {
        User u = repo.getById(userId);
        main.post(() -> view.render(UserView.State.success(u.name(), u.email())));
      } catch (Exception e) {
        main.post(() -> view.render(UserView.State.error("Failed to load user")));
      }
    });
  }
}
```

**Notes**

-   The **View** is passive and reusable; it exposes a `Listener` and renders a `State`.
    
-   The **Controller** (Activity) owns threading, lifecycle, and mapping Model → View.
    
-   The **Model** is UI-agnostic and testable.
    

---

## Known Uses

-   **iOS Cocoa MVC:** `UIView` + `UIViewController` orchestrating models (classic Apple guidance).
    
-   **Early Android apps:** Activities/Fragments used as Controllers, XML/custom views as Views, repositories as Models.
    
-   Small mobile features where MVVM/MVI would be overkill.
    

## Related Patterns

-   **MVP / MVVM / MVI:** Alternative presentation patterns that address “massive controller” and state management.
    
-   **Coordinator:** Composes navigation flows alongside MVC screens.
    
-   **Repository / Use Case:** Common modeling inside the **Model** layer.
    
-   **Dependency Injection:** Wires repositories/services into controllers; keeps controllers lean.
    
-   **Observer / Event Bus (Mobile):** For one-to-many notifications; use sparingly with MVC.

