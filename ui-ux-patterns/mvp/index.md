# MVP — UI/UX Pattern

## Pattern Name and Classification

**Name:** Model–View–Presenter (MVP)  
**Category:** UI/UX · Presentation Architecture · Separation of Concerns · Testability

## Intent

Decouple rendering and user interaction from application logic by introducing a **Presenter** that mediates between a passive **View** and the **Model**. The Presenter interprets user input, coordinates model operations, and updates the View via an explicit interface—making UI behavior easy to unit test and reuse.

## Also Known As

Passive View · Supervising Presenter · Presenter-First

## Motivation (Forces)

-   **Testability:** UI toolkits are hard to unit test. Moving logic into a Presenter that talks to the View via an interface makes behavior testable with mocks/fakes.
    
-   **Separation of concerns:** UI widgets remain dumb; domain/model code is framework-agnostic.
    
-   **Parallel work:** Designers focus on views while engineers evolve presenters and models.
    
-   **State orchestration:** Presenter is the single place managing view state transitions (loading, error, empty).
    
-   **Framework volatility:** Minimizes coupling to specific UI frameworks (Swing/JavaFX/Android/Web).
    
-   **Trade-offs:** More interfaces/boilerplate; danger of a “Massive Presenter” if not controlled.
    

## Applicability

Use MVP when:

-   You need deterministic, unit-testable UI behavior (e.g., form/wizard flows).
    
-   The UI framework complicates direct testing (desktop/mobile).
    
-   You target multiple UIs over one domain model.
    
-   You require explicit control over view state transitions and error handling.
    

Avoid or adapt when:

-   The app is tiny and a simpler MVC or Controller+Template suffices.
    
-   Highly reactive, streaming UIs might benefit more from MVI/MVU or Flux/Redux.
    
-   Frameworks with strong binding (e.g., MVVM) already fit your needs.
    

## Structure

-   **Model:** Domain state and operations (entities, services, repositories).
    
-   **View (interface):** Rendering API (no business logic). Concrete implementation uses a UI toolkit.
    
-   **Presenter:** Orchestrates user events → model calls → view updates. Holds minimal UI state.
    

```sql
User → View (UI events) → Presenter → Model
                       ↑            ↓
                    updates      results/errors
```

## Participants

-   **User:** Interacts with UI controls.
    
-   **View Interface:** e.g., `LoginView`, declares `showLoading()`, `showError(String)`, etc.
    
-   **Presenter:** Consumes view events, coordinates model, updates view.
    
-   **Model/Service/Repository:** Performs business logic and data access.
    
-   **View Implementation:** Concrete UI (Swing/JavaFX/Android/Web) that delegates events to Presenter.
    

## Collaboration

1.  Concrete View is created and given a Presenter.
    
2.  User interacts → View forwards event to Presenter.
    
3.  Presenter validates input, calls Model, handles results/errors.
    
4.  Presenter drives the View via its interface (loading/data/error states).
    
5.  View renders; Presenter remains the single source of UI truth.
    

## Consequences

**Benefits**

-   Highly testable presentation logic (Presenter can be unit-tested without UI).
    
-   Clean separation; views are thin and replaceable.
    
-   Reduced framework lock-in.
    

**Liabilities**

-   Extra indirection and interfaces (boilerplate).
    
-   Risk of **Massive Presenter** if it accumulates domain logic (keep business rules in Model).
    
-   Requires discipline for threading/asynchrony and lifecycle (attach/detach view).
    

## Implementation

**Guidelines**

1.  **Passive View:** Keep the View dumb—no branching; just render what Presenter tells it.
    
2.  **One Presenter per screen/use case:** Limits size and clarifies ownership.
    
3.  **Presenter lifecycle:** Provide `attach(view)` / `detach()` to prevent UI updates after disposal.
    
4.  **Background work:** Do I/O off the UI thread; marshal results back before calling view methods.
    
5.  **Model owns business rules:** Presenter validates interaction-level constraints; domain rules live in the Model.
    
6.  **DTO/ViewModel:** Presenters adapt domain objects to view-friendly data.
    
7.  **Error handling:** Normalize errors into user-friendly messages; keep stack traces in logs.
    
8.  **Testing:** Mock the View; assert ordered calls for each scenario (happy path, validation error, server error).
    

---

## Sample Code (Java — Framework-agnostic, with a tiny CLI “View”)

### Contracts

```java
// src/main/java/com/example/mvp/view/LoginView.java
package com.example.mvp.view;

public interface LoginView {
    void showLoading();
    void showForm();
    void showError(String message);
    void showWelcome(String displayName);
}
```

```java
// src/main/java/com/example/mvp/presenter/LoginPresenter.java
package com.example.mvp.presenter;

import com.example.mvp.view.LoginView;

public interface LoginPresenter {
    void attach(LoginView view);
    void detach();
    void onLoginClicked(String email, String password);
}
```

### Model (Domain/Service)

```java
// src/main/java/com/example/mvp/model/AuthService.java
package com.example.mvp.model;

import java.util.Optional;

public interface AuthService {
    Optional<User> authenticate(String email, String password);
}
```

```java
// src/main/java/com/example/mvp/model/User.java
package com.example.mvp.model;

public record User(long id, String displayName, String email) {}
```

```java
// src/main/java/com/example/mvp/model/InMemoryAuthService.java
package com.example.mvp.model;

import java.util.Map;
import java.util.Optional;

public class InMemoryAuthService implements AuthService {
    private final Map<String, String> users = Map.of(
            "jane@company.com", "Secret1234!",
            "john@company.com", "Password12!"
    );

    @Override
    public Optional<User> authenticate(String email, String password) {
        if (email == null || password == null) return Optional.empty();
        String stored = users.get(email.toLowerCase());
        if (stored != null && stored.equals(password)) {
            String name = email.substring(0, email.indexOf('@'));
            return Optional.of(new User(name.hashCode(), capitalize(name), email));
        }
        return Optional.empty();
    }

    private String capitalize(String s) { return s.isEmpty() ? s : Character.toUpperCase(s.charAt(0)) + s.substring(1); }
}
```

### Presenter Implementation

```java
// src/main/java/com/example/mvp/presenter/LoginPresenterImpl.java
package com.example.mvp.presenter;

import com.example.mvp.model.AuthService;
import com.example.mvp.model.User;
import com.example.mvp.view.LoginView;

import java.util.Optional;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class LoginPresenterImpl implements LoginPresenter {
    private final AuthService auth;
    private final ExecutorService io = Executors.newSingleThreadExecutor();

    private volatile LoginView view; // attach/detach aware

    public LoginPresenterImpl(AuthService auth) {
        this.auth = auth;
    }

    @Override public void attach(LoginView view) { this.view = view; }
    @Override public void detach() { this.view = null; }

    @Override
    public void onLoginClicked(String email, String password) {
        if (view == null) return;

        // Interaction-level validation (domain rules stay in Model)
        if (email == null || !email.contains("@")) {
            view.showError("Enter a valid email address.");
            return;
        }
        if (password == null || password.length() < 8) {
            view.showError("Password must be at least 8 characters.");
            return;
        }

        view.showLoading();

        // Simulate async I/O
        io.submit(() -> {
            Optional<User> user = auth.authenticate(email, password);
            LoginView v = this.view; // capture current view
            if (v == null) return;   // detached meanwhile

            if (user.isPresent()) {
                v.showWelcome(user.get().displayName());
            } else {
                v.showError("Invalid email or password.");
                v.showForm();
            }
        });
    }
}
```

### A Minimal Concrete View (CLI demo)

```java
// src/main/java/com/example/mvp/cli/CliLoginView.java
package com.example.mvp.cli;

import com.example.mvp.presenter.LoginPresenter;
import com.example.mvp.presenter.LoginPresenterImpl;
import com.example.mvp.model.InMemoryAuthService;
import com.example.mvp.view.LoginView;

import java.util.Scanner;

public class CliLoginView implements LoginView {
    private final LoginPresenter presenter;

    public CliLoginView(LoginPresenter presenter) {
        this.presenter = presenter;
        presenter.attach(this);
    }

    public void start() {
        showForm();
        try (Scanner sc = new Scanner(System.in)) {
            System.out.print("Email: ");
            String email = sc.nextLine();
            System.out.print("Password: ");
            String password = sc.nextLine();
            presenter.onLoginClicked(email, password);
            // Wait briefly to simulate async result (only for CLI demo)
            try { Thread.sleep(300); } catch (InterruptedException ignored) {}
        }
    }

    @Override public void showLoading() { System.out.println("[Loading…]"); }
    @Override public void showForm() { System.out.println("== Login =="); }
    @Override public void showError(String message) { System.out.println("[Error] " + message); }
    @Override public void showWelcome(String displayName) { System.out.println("Welcome, " + displayName + "!"); }

    public static void main(String[] args) {
        var presenter = new LoginPresenterImpl(new InMemoryAuthService());
        new CliLoginView(presenter).start();
    }
}
```

### How to Test the Presenter (outline)

-   Mock `LoginView` to verify calls occur in order: `showLoading()` → `showWelcome()` (success) or `showError()` then `showForm()` (failure).
    
-   Stub `AuthService` to return `Optional.of(user)` or `Optional.empty()` accordingly.
    
-   No UI toolkit required in tests.
    

---

## Known Uses

-   **Android (pre-Architecture Components):** MVP widely used to isolate Activity/Fragment UI from logic.
    
-   **Desktop UIs (Swing/JavaFX/.NET WinForms):** Views are GUI classes, Presenters handle logic.
    
-   **Web with templating engines:** Presenter prepares view models; server template remains dumb.
    
-   **Large enterprise apps:** Presenter-first teams for complex wizards and back-office tooling.
    

## Related Patterns

-   **MVC:** Sibling pattern; Controller often triggers View directly. MVP emphasizes a View interface and Presenter mediation.
    
-   **MVVM:** Pushes state/binding to the ViewModel with data binding; less explicit than MVP about calls.
    
-   **Presentation Model / ViewModel:** Encapsulates view state; pairs well with MVP for complex UIs.
    
-   **Observer / Pub-Sub:** Underlies event and state notifications.
    
-   **Clean/Hexagonal Architecture:** Keeps domain independent; Presenter adapts domain to the View.

