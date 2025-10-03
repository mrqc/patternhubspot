# Coordinator — Mobile App Architecture Pattern

## Pattern Name and Classification

-   **Name:** Coordinator
    
-   **Classification:** Presentation & Navigation Orchestration Pattern for Mobile Apps (UI flow controller)
    

## Intent

Encapsulate **navigation flow and screen orchestration** in dedicated objects called **Coordinators**, so **views/fragments/activities** and **view models** remain free of routing logic. This delivers testable, composable flows that can be started, nested, and dismissed independently.

## Also Known As

-   Flow Controller
    
-   Navigator / Router (related)
    
-   App Flow / Scene Coordinator
    

## Motivation (Forces)

-   **Fat activities/fragments:** Mixing UI and navigation causes hard-to-test spaghetti.
    
-   **Reusable flows:** Auth, onboarding, checkout recur across apps; make them **pluggable**.
    
-   **Single-Activity architecture:** Fragments need a clean, centralized navigation policy.
    
-   **Separation of concerns:** VM handles state; **Coordinator** decides **where to go next**.
    
-   **Team scaling:** Different teams own flows without trampling global nav rules.
    

**Tensions**

-   More files/abstractions; must keep boundaries clear.
    
-   Coordinators can themselves bloat—need composition and child-coordinator management.
    
-   Requires discipline with lifecycles/back-stack integration.
    

## Applicability

Use when:

-   You have **non-trivial navigation** (wizards, conditional branches, deep links).
    
-   You target **Single-Activity** (Android) or multi-scene apps and want **testable routing**.
    
-   You share flows (e.g., **Auth**, **KYC**, **Checkout**) across features.
    

Consider lighter options when:

-   The app is tiny with linear navigation (Jetpack Navigation XML may suffice).
    
-   You already rely on a framework that dictates routing (e.g., Compose Navigation or iOS SwiftUI NavigationStack) and don’t need custom orchestration.
    

## Structure

```pgsql
+------------------+        starts            +--------------------+
|  AppCoordinator  |------------------------->|  AuthCoordinator   |
|  (root, decides) |                          |  (login flow)      |
+----+-------------+                          +---------+----------+
     | start child                                      |
     v                                                  v finish->callback
+----+-------------+                          +---------+----------+
| MainCoordinator  |<--------------------------|       Views        |
| (home flow)      |  shows fragments via      | (Fragments/Views)  |
+------------------+  Navigator (FragmentMgr)  +--------------------+
```

-   **Navigator**: thin wrapper over FragmentManager / Activity / NavController.
    

## Participants

-   **Coordinator**: object with `start()`, `finish()`, `onBackPressed()`; composes child coordinators.
    
-   **Navigator**: performs concrete transitions (push/replace/pop/animations).
    
-   **Views/Fragments**: only render UI and expose user intents via callbacks.
    
-   **ViewModels**: hold state/business logic; **do not** navigate.
    
-   **Root/AppCoordinator**: decides initial flow (auth vs. main), handles deep links.
    

## Collaboration

1.  Root coordinator is created in the host Activity and calls `start()`.
    
2.  It evaluates app state (session/deeplink) and **starts a child coordinator** (Auth or Main).
    
3.  Child coordinator presents screens via **Navigator** and listens to screen callbacks.
    
4.  On flow completion, child calls a **completion callback** → parent removes child and continues.
    
5.  Back button is delegated to the **current coordinator** for custom handling.
    

## Consequences

**Benefits**

-   **Testable navigation** (coordinators as plain objects).
    
-   **Reusability**: flows can be embedded in different entry points.
    
-   **Separation of concerns**: thin activities/fragments; VMs are navigation-agnostic.
    
-   **Composability**: nested flows, modal subflows, feature isolation.
    

**Liabilities**

-   More plumbing (interfaces, wiring).
    
-   Risk of “mega-coordinator” if not decomposed.
    
-   Must align with platform back stack (Android back press, lifecycle).
    

## Implementation

1.  Define a `Coordinator` interface and a `BaseCoordinator` that manages child lifecycles.
    
2.  Provide a `Navigator` abstraction over Fragment transactions.
    
3.  Implement feature coordinators (Auth, Main, Checkout…) with clear **completion callbacks**.
    
4.  Pass **only minimal dependencies** into coordinators (Navigator, factories).
    
5.  Delegate **back press** from Activity to the current coordinator.
    
6.  Keep Fragments dumb: expose intents via listener interfaces; no direct `FragmentManager` usage there.
    
7.  Unit test coordinators by **stubbing Navigator** and asserting transitions.
    

---

## Sample Code (Java, Android, Single-Activity with Fragments)

> Minimal, drop-in friendly skeleton showing a root `AppCoordinator` that decides between `AuthCoordinator` and `MainCoordinator`. Navigation goes through a `Navigator` that wraps `FragmentManager`.

### Coordinator contracts

```java
// Coordinator.java
package arch.coordinator;

public interface Coordinator {
  void start();
  /** Return true if handled, false to let system pop/back. */
  boolean onBackPressed();
  default void finish() {}
}
```

```java
// BaseCoordinator.java
package arch.coordinator;

import java.util.ArrayList;
import java.util.List;

public abstract class BaseCoordinator implements Coordinator {
  protected final List<Coordinator> children = new ArrayList<>();
  protected void addChild(Coordinator c) { children.add(c); }
  protected void removeChild(Coordinator c) { children.remove(c); }

  @Override public boolean onBackPressed() {
    if (!children.isEmpty()) {
      Coordinator last = children.get(children.size()-1);
      if (last.onBackPressed()) return true;
    }
    return false;
  }
}
```

### Navigator

```java
// Navigator.java
package arch.nav;

import androidx.annotation.IdRes;
import androidx.fragment.app.Fragment;
import androidx.fragment.app.FragmentManager;
import androidx.fragment.app.FragmentTransaction;

public class Navigator {
  private final FragmentManager fm;
  private final @IdRes int containerId;

  public Navigator(FragmentManager fm, int containerId) {
    this.fm = fm; this.containerId = containerId;
  }

  public void setRoot(Fragment f) {
    fm.popBackStack(null, FragmentManager.POP_BACK_STACK_INCLUSIVE);
    fm.beginTransaction()
      .setTransition(FragmentTransaction.TRANSIT_FRAGMENT_FADE)
      .replace(containerId, f)
      .commit();
  }

  public void push(Fragment f, boolean addToBackstack) {
    FragmentTransaction tx = fm.beginTransaction()
      .setTransition(FragmentTransaction.TRANSIT_FRAGMENT_OPEN)
      .replace(containerId, f);
    if (addToBackstack) tx.addToBackStack(f.getClass().getSimpleName());
    tx.commit();
  }

  public boolean pop() {
    if (fm.getBackStackEntryCount() > 0) { fm.popBackStack(); return true; }
    return false;
  }
}
```

### Root and feature coordinators

```java
// AppCoordinator.java
package app.flow;

import arch.coordinator.BaseCoordinator;
import arch.nav.Navigator;

public class AppCoordinator extends BaseCoordinator {
  private final Navigator nav;
  private final SessionProvider session;

  public AppCoordinator(Navigator nav, SessionProvider session) {
    this.nav = nav; this.session = session;
  }

  @Override public void start() {
    if (session.isLoggedIn()) startMain();
    else startAuth();
  }

  private void startAuth() {
    AuthCoordinator auth = new AuthCoordinator(nav, () -> {
      removeChild(auth);
      startMain();
    });
    addChild(auth);
    auth.start();
  }

  private void startMain() {
    MainCoordinator main = new MainCoordinator(nav, () -> {
      removeChild(main);
      session.clear();
      startAuth();
    });
    addChild(main);
    main.start();
  }
}
```

```java
// AuthCoordinator.java
package app.flow;

import arch.coordinator.BaseCoordinator;
import arch.nav.Navigator;

public class AuthCoordinator extends BaseCoordinator {
  public interface Completion { void onFinished(); }
  private final Navigator nav; private final Completion onDone;

  public AuthCoordinator(Navigator nav, Completion onDone) {
    this.nav = nav; this.onDone = onDone;
  }

  @Override public void start() {
    nav.setRoot(new LoginFragment(() -> {
      // on login success
      onDone.onFinished();
    }, () -> {
      // go to sign-up
      nav.push(new SignUpFragment(() -> onDone.onFinished()), true);
    }));
  }

  @Override public boolean onBackPressed() {
    // handle nested screens; fallback to navigator pop
    return nav.pop();
  }
}
```

```java
// MainCoordinator.java
package app.flow;

import arch.coordinator.BaseCoordinator;
import arch.nav.Navigator;

public class MainCoordinator extends BaseCoordinator {
  public interface Completion { void onLogout(); }
  private final Navigator nav; private final Completion onLogout;

  public MainCoordinator(Navigator nav, Completion onLogout) {
    this.nav = nav; this.onLogout = onLogout;
  }

  @Override public void start() {
    nav.setRoot(new HomeFragment(
        () -> nav.push(new DetailsFragment(), true),
        onLogout::onLogout
    ));
  }

  @Override public boolean onBackPressed() {
    return nav.pop(); // let fragments back-stack handle it
  }
}
```

### Example fragments (intents via callbacks)

```java
// LoginFragment.java
package app.flow;

import android.os.Bundle;
import android.view.*;
import android.widget.Button;
import androidx.annotation.*;
import androidx.fragment.app.Fragment;

public class LoginFragment extends Fragment {
  public interface Listener { void onLoginSuccess(); }
  public interface Nav { void toSignUp(); }

  private final Listener listener;
  private final Nav nav;

  public LoginFragment(Listener listener, Nav nav) {
    super(); this.listener = listener; this.nav = nav;
  }

  @Nullable @Override
  public View onCreateView(@NonNull LayoutInflater i, @Nullable ViewGroup c, @Nullable Bundle b) {
    var root = new android.widget.LinearLayout(getContext());
    root.setOrientation(android.widget.LinearLayout.VERTICAL);
    Button login = new Button(getContext()); login.setText("Login");
    Button signup = new Button(getContext()); signup.setText("Sign up");
    root.addView(login); root.addView(signup);
    login.setOnClickListener(v -> listener.onLoginSuccess());
    signup.setOnClickListener(v -> nav.toSignUp());
    return root;
  }
}
```

```java
// SignUpFragment.java
package app.flow;

import android.os.Bundle;
import android.view.*;
import android.widget.Button;
import androidx.annotation.*;
import androidx.fragment.app.Fragment;

public class SignUpFragment extends Fragment {
  public interface Done { void onSignedUp(); }
  private final Done done;
  public SignUpFragment(Done done) { this.done = done; }

  @Nullable @Override
  public View onCreateView(@NonNull LayoutInflater i, @Nullable ViewGroup c, @Nullable Bundle b) {
    Button finish = new Button(getContext()); finish.setText("Finish Sign Up");
    finish.setOnClickListener(v -> done.onSignedUp());
    return finish;
  }
}
```

```java
// HomeFragment.java
package app.flow;

import android.os.Bundle;
import android.view.*;
import android.widget.Button;
import androidx.annotation.*;
import androidx.fragment.app.Fragment;

public class HomeFragment extends Fragment {
  public interface Listener { void openDetails(); void logout(); }
  private final Listener l;
  public HomeFragment(Runnable openDetails, Runnable logout) {
    this.l = new Listener() {
      @Override public void openDetails() { openDetails.run(); }
      @Override public void logout() { logout.run(); }
    };
  }

  @Nullable @Override
  public View onCreateView(@NonNull LayoutInflater i, @Nullable ViewGroup c, @Nullable Bundle b) {
    var layout = new android.widget.LinearLayout(getContext());
    layout.setOrientation(android.widget.LinearLayout.VERTICAL);
    Button details = new Button(getContext()); details.setText("Details");
    Button logout = new Button(getContext()); logout.setText("Logout");
    layout.addView(details); layout.addView(logout);
    details.setOnClickListener(v -> l.openDetails());
    logout.setOnClickListener(v -> l.logout());
    return layout;
  }
}
```

```java
// DetailsFragment.java
package app.flow;

import androidx.fragment.app.Fragment;
public class DetailsFragment extends Fragment { /* render something */ }
```

### Host Activity (wires everything)

```java
// MainActivity.java
package app;

import android.os.Bundle;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;
import app.flow.AppCoordinator;
import arch.nav.Navigator;

public class MainActivity extends AppCompatActivity {
  private AppCoordinator appCoordinator;

  @Override protected void onCreate(@Nullable Bundle savedInstanceState) {
    super.onCreate(savedInstanceState);
    setContentView(new android.widget.FrameLayout(this) {{ setId(android.R.id.content); }});

    Navigator navigator = new Navigator(getSupportFragmentManager(), android.R.id.content);
    SessionProvider session = new InMemorySession(); // your implementation
    appCoordinator = new AppCoordinator(navigator, session);
    appCoordinator.start();
  }

  @Override public void onBackPressed() {
    if (!appCoordinator.onBackPressed()) super.onBackPressed();
  }
}
```

```java
// SessionProvider.java
package app.flow;

public interface SessionProvider {
  boolean isLoggedIn();
  void clear();
}

// InMemorySession.java (demo)
package app.flow;
public class InMemorySession implements SessionProvider {
  private boolean logged = false;
  @Override public boolean isLoggedIn() { return logged; }
  @Override public void clear() { logged = false; }
  // set logged=true in LoginFragment on success in a real app (via VM/Repo)
}
```

> Testing tip: unit-test `AuthCoordinator` and `MainCoordinator` by injecting a **fake Navigator** that records operations, then assert sequences like `setRoot(Login) → push(SignUp)` and completion callbacks.

---

## Known Uses

-   Widely used in **iOS** (origin of the Coordinator pattern) and adapted to **Android** Single-Activity apps to tame Fragment navigation.
    
-   Adopted for **reusable flows** (authentication, onboarding, checkout) across superapps and modularized Android projects.
    

## Related Patterns

-   **MVVM / MVI / MVP:** Coordinator complements these by **owning navigation**, leaving VMs/presenters pure.
    
-   **Clean Architecture (Mobile):** Coordinators live in the outer/presentation layer.
    
-   **Router/Navigator abstractions:** Lower-level mechanism used by a Coordinator.
    
-   **State Machine / Workflow:** For complex branching, Coordinators can embed an explicit state machine.
    
-   **Strangler Fig (mobile modernization):** Use a coordinator-backed façade to stage new flows alongside legacy screens.

