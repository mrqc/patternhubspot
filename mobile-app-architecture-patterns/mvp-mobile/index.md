# MVP (Mobile) — Mobile App Architecture Pattern

## Pattern Name and Classification

-   **Name:** Model–View–Presenter (Mobile)
    
-   **Classification:** Presentation Architecture Pattern (separates UI rendering from presentation logic)
    

## Intent

Separate **presentation logic** (in the **Presenter**) from **UI rendering** (the **View**) and **data/domain** (the **Model**) so screens are:

-   **Testable** without the UI toolkit,
    
-   **Lifecycle-resilient** (attach/detach the View),
    
-   **Composable** and easier to evolve.
    

## Also Known As

-   **Passive View** (most common mobile flavor)
    
-   **Supervising Controller** (Presenter lets View do simple bindings)
    

## Motivation (Forces)

-   **UI lifecycles churn** (rotation, background/foreground): logic shouldn’t live in Views that are destroyed.
    
-   **Async everywhere** (network, DB, sensors): presentation logic must orchestrate threads and map to UI states.
    
-   **Testability:** Activities/Fragments/ViewControllers are hard to unit test; plain Presenters are easy.
    
-   **Separation of concerns:** Reduce “Massive Activity/Fragment/VC”.
    

**Tensions**

-   Potential for **“Massive Presenter”** if domain logic leaks upward.
    
-   **Lifecycle coupling:** must attach/detach to avoid leaks.
    
-   State handling and one-off events (toasts, navigation) need discipline.
    

## Applicability

Use MVP when:

-   You want **plain-Java** presentation logic with **UI-agnostic tests**.
    
-   Screens have **non-trivial orchestration**, validation, or error handling.
    
-   You’re on classic **Android Views/Fragments** or UIKit (iOS) and prefer explicit control.
    

Consider alternatives when:

-   You’re all-in on **Compose/SwiftUI + MVVM/MVI** state containers.
    
-   The screen is trivial and a controller-only solution suffices.
    

## Structure

```pgsql
User Input      calls/intents      Use-cases / repositories
     ┌─────────────► Presenter ─────────────────────────────► Model
     │                    │
     │         renders    │  ViewState / one-off events
     └────── View ◄───────┘
(Controller in mobile is often the View host: Activity/Fragment/VC)
```

-   **Presenter** holds no platform UI refs beyond the `View` interface; owns orchestration and mapping to **ViewState**.
    
-   **View** is **passive**: it forwards intents and renders states, no business logic.
    
-   **Model** is domain/services/repositories.
    

## Participants

-   **View (interface):** `render(State)` + small methods for one-off effects (e.g., `showToast`).
    
-   **Presenter:** Presentation logic; exposes `attach(view)`, `detach()`, and intent handlers.
    
-   **Model:** Repositories, use-cases, entities.
    
-   **Controller/Host:** Activity/Fragment/VC that implements the View interface and delegates to the Presenter.
    

## Collaboration

1.  Host creates or retrieves the **Presenter**, **attaches** the View.
    
2.  View forwards **intents** (clicks, refresh).
    
3.  Presenter calls **Model**, transforms results/errors to **ViewState**.
    
4.  Presenter calls `view.render(state)`; View updates widgets.
    
5.  Host **detaches** the View on stop/destroy to avoid leaks; Presenter keeps (lightweight) state.
    

## Consequences

**Benefits**

-   **Unit-testable** presentation logic (no Android/iOS classes).
    
-   **Slim Views** and clearer responsibilities.
    
-   Easier to **share presenters** across platforms or UIs.
    

**Liabilities**

-   Risk of **bloated presenters**; extract mappers/formatters/use-cases.
    
-   Must manage **attach/detach** carefully.
    
-   **State duplication** if not centralized (consider a simple state holder).
    

## Implementation

1.  Define a **contract** (`View`, `Presenter`) per screen.
    
2.  Keep **View passive** and platform-bound; never call Model from View.
    
3.  Presenter owns **threading** (executors/coroutines) and **ViewState** mapping.
    
4.  Handle **one-off effects** separately (navigation, toasts) to avoid replay on reattach.
    
5.  **Retain** Presenter across rotations (e.g., via `ViewModel`/retained fragment) and **reattach** the View.
    
6.  Write **unit tests** for Presenter using fake View and fake Repository.
    

---

## Sample Code (Java, Android-friendly MVP — Passive View)

### 1) Contract

```java
// mvp/UserProfileContract.java
package mvp;

import java.util.UUID;

public interface UserProfileContract {
  interface View {
    void render(State state);
    void showMessage(String message); // one-off effect
  }

  interface Presenter {
    void attach(View view);
    void detach();
    void load(UUID userId);
    void onRefresh();
  }

  final class State {
    public final boolean loading;
    public final String name;
    public final String email;
    public final String error;

    private State(boolean loading, String name, String email, String error) {
      this.loading = loading; this.name = name; this.email = email; this.error = error;
    }
    public static State loading()              { return new State(true,  null,  null,  null); }
    public static State success(String n,String e){ return new State(false, n, e, null); }
    public static State error(String msg)      { return new State(false, null, null, msg); }
  }
}
```

### 2) Model (domain + repository)

```java
// domain/User.java
package mvp.domain;
import java.util.UUID;
public record User(UUID id, String name, String email) {}
```

```java
// domain/UserRepository.java
package mvp.domain;
import java.util.UUID;
public interface UserRepository {
  User getById(UUID id) throws Exception;
}
```

```java
// data/FakeUserRepository.java
package mvp.data;

import mvp.domain.*;
import java.util.UUID;

public final class FakeUserRepository implements UserRepository {
  @Override public User getById(UUID id) throws Exception {
    Thread.sleep(400); // emulate network
    return new User(id, "Ada Lovelace", "ada@example.com");
  }
}
```

### 3) Presenter (plain Java, no Android deps)

```java
// mvp/UserProfilePresenter.java
package mvp;

import mvp.domain.User;
import mvp.domain.UserRepository;

import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Consumer;

/**
 * Presenter is platform-agnostic; the host supplies a main-thread post mechanism.
 */
public final class UserProfilePresenter implements UserProfileContract.Presenter {

  private final UserRepository repo;
  private final ExecutorService io = Executors.newSingleThreadExecutor();
  private final Consumer<Runnable> mainThread; // e.g., Activity's Handler::post

  private UserProfileContract.View view;
  private UUID currentId;

  public UserProfilePresenter(UserRepository repo, Consumer<Runnable> mainThread) {
    this.repo = repo; this.mainThread = mainThread;
  }

  @Override public void attach(UserProfileContract.View view) {
    this.view = view;
    if (currentId != null) { // optionally re-render cached state
      onRefresh();
    }
  }

  @Override public void detach() { this.view = null; }

  @Override public void load(UUID userId) {
    this.currentId = userId;
    render(UserProfileContract.State.loading());
    io.submit(() -> {
      try {
        User u = repo.getById(userId);
        mainThread.accept(() -> render(UserProfileContract.State.success(u.name(), u.email())));
      } catch (Exception e) {
        mainThread.accept(() -> {
          render(UserProfileContract.State.error("Failed to load"));
          if (view != null) view.showMessage("Please try again");
        });
      }
    });
  }

  @Override public void onRefresh() {
    if (currentId != null) load(currentId);
  }

  private void render(UserProfileContract.State s) {
    if (view != null) view.render(s);
  }
}
```

### 4) Android Host (Activity as the View & Controller)

```java
// ui/UserProfileActivity.java
package mvp.ui;

import android.os.*;
import android.widget.*;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;
import androidx.lifecycle.ViewModel;
import androidx.lifecycle.ViewModelProvider;

import java.util.UUID;

import mvp.*;
import mvp.data.FakeUserRepository;

public class UserProfileActivity extends AppCompatActivity implements UserProfileContract.View {

  private TextView name, email, error;
  private ProgressBar progress;
  private Button refresh;

  private UserProfileContract.Presenter presenter;
  private UUID userId = UUID.fromString("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa");

  // Retain presenter across config changes using a ViewModel holder
  public static class PresenterHolder extends ViewModel {
    public UserProfileContract.Presenter presenter;
  }

  @Override protected void onCreate(@Nullable Bundle savedInstanceState) {
    super.onCreate(savedInstanceState);

    // Simple UI
    LinearLayout root = new LinearLayout(this);
    root.setOrientation(LinearLayout.VERTICAL);
    progress = new ProgressBar(this);
    name = new TextView(this);
    email = new TextView(this);
    error = new TextView(this); error.setTextColor(0xFFB00020);
    refresh = new Button(this); refresh.setText("Refresh");
    root.addView(progress); root.addView(name); root.addView(email); root.addView(error); root.addView(refresh);
    setContentView(root);

    // Build or retrieve Presenter
    PresenterHolder holder = new ViewModelProvider(this).get(PresenterHolder.class);
    if (holder.presenter == null) {
      holder.presenter = new UserProfilePresenter(
          new FakeUserRepository(),
          r -> new Handler(Looper.getMainLooper()).post(r) // main thread executor
      );
    }
    presenter = holder.presenter;

    refresh.setOnClickListener(v -> presenter.onRefresh());
  }

  @Override protected void onStart() {
    super.onStart();
    presenter.attach(this);
    presenter.load(userId);
  }

  @Override protected void onStop() {
    super.onStop();
    presenter.detach(); // avoid leaking the Activity
  }

  // ---- View implementation ----
  @Override public void render(UserProfileContract.State s) {
    progress.setVisibility(s.loading ? android.view.View.VISIBLE : android.view.View.GONE);
    name.setText(s.name != null ? s.name : "");
    email.setText(s.email != null ? s.email : "");
    error.setText(s.error != null ? s.error : "");
    refresh.setEnabled(!s.loading);
  }

  @Override public void showMessage(String message) {
    Toast.makeText(this, message, Toast.LENGTH_SHORT).show();
  }
}
```

**Why this is MVP:**

-   Presenter contains **all** presentation logic (threading, mapping to `State`), no Android UI classes.
    
-   View (`Activity`) is **passive**, only renders.
    
-   Presenter is **retained** via a `ViewModel` and **reattached** after rotation.
    

**Testing idea (unit):**

-   Provide a fake `UserRepository` and a fake `View` that records calls; invoke `presenter.load(id)` and assert `render(State.loading)` followed by `render(State.success(...))`.
    

---

## Known Uses

-   **Android** MVP libraries and samples (pre-MVVM era) and still common in large legacy codebases; many teams keep MVP for Views while using Clean Architecture for domain.
    
-   **iOS** used a lot before VIPER/MVVM; still appears in UIKit-heavy apps that prefer explicit presenters.
    

## Related Patterns

-   **MVC (Mobile):** MVP extracts presentation logic out of controllers to reduce “massive controller”.
    
-   **MVVM / MVI:** Alternatives emphasizing reactive state holders; similar separation with different data flow.
    
-   **Coordinator:** Pair with MVP to move **navigation** out of presenters.
    
-   **Clean Architecture (Mobile):** MVP lives in the outer presentation ring; presenters call use-cases.
    
-   **Dependency Injection:** Wires presenters and repositories; eases testing.
    
-   **Event Bus (Mobile):** For one-to-many app-wide notifications; use sparingly with MVP.

