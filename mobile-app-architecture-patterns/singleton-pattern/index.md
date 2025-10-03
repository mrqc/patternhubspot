# Singleton — Mobile App Architecture Pattern

## Pattern Name and Classification

-   **Name:** Singleton
    
-   **Classification:** Creational Pattern (global, single-instance lifecycle within a process)
    

## Intent

Ensure **exactly one instance** of a class exists **per process**, provide a **global access point**, and control its lifecycle. In mobile, used for shared, expensive, or cross-cutting components (e.g., HTTP client, analytics, caches).

## Also Known As

-   Global Instance
    
-   Single Accessor
    
-   (Often confused with) **Service Locator** — different pattern; avoid conflating
    

## Motivation (Forces)

-   **Expensive resources:** HTTP connection pools, DB handles, thread pools should be reused.
    
-   **Cross-cutting concerns:** Logging, analytics, feature flags shared across screens.
    
-   **Coordination:** Centralized state (e.g., session token) must be consistent.
    

**Tensions**

-   **Testability:** Harder to substitute in tests; global state causes order-coupling.
    
-   **Lifecycle:** On Android, “singleton” is **per process** and dies on process death; multi-process apps get **multiple** instances.
    
-   **Memory leaks:** Holding an `Activity/Fragment/View` in a singleton leaks the UI.
    
-   **Hidden dependencies:** Globals obscure who uses what (worse than explicit DI).
    

## Applicability

Use a Singleton when:

-   A component is **stateless or lightly stateful**, expensive to create, and safe to share (e.g., OkHttp client, JSON mapper).
    
-   You need a **coordinator** for cross-cutting behavior (analytics logger), not tied to UI lifecycle.
    

Avoid or constrain when:

-   You need **different lifetimes/scopes** (per screen/feature/tenant) → prefer **Dependency Injection**.
    
-   You’re tempted to stash mutable app state globally (leads to tight coupling).
    
-   The object must hold references to volatile contexts (Activities, Views).
    

## Structure

```scss
(global access)
Clients ────────────────►  Singleton.getInstance()
                               │
                               ▼
                         [ Single Instance ]
                         (thread-safe init)
```

## Participants

-   **Singleton Class:** Controls creation and exposes `getInstance()`.
    
-   **Clients:** Call `getInstance()` to use shared behavior.
    
-   **Process/Runtime:** On mobile, defines the true lifetime (process-scoped).
    

## Collaboration

1.  First client calls `getInstance()` → instance is created (lazy or eager).
    
2.  Subsequent callers reuse the same instance.
    
3.  Optional `init(...)` to install runtime dependencies (e.g., app context, configs).
    

## Consequences

**Benefits**

-   **Resource reuse** (connection pools, caches).
    
-   **Simple access** from anywhere.
    
-   Potential **lower latency** and **less GC** from reusing heavy objects.
    

**Liabilities**

-   **Global mutable state** risks: order-dependent tests, hidden couplings.
    
-   **Difficult to mock** without seams (requires indirection or reset hooks).
    
-   **Android specifics:** per-process, reset on process death; can break assumptions.
    
-   **Memory leaks** if it captures short-lived contexts.
    

> Rule of thumb: prefer **DI singletons** (scoped, testable). Use the **GoF Singleton** only for small, infrastructure-style components and keep them **stateless or trivially stateful**.

## Implementation

1.  **Choose initialization strategy:**
    
    -   **Lazy Holder** (thread-safe, simple) or **Double-Checked Locking** (DCL with `volatile` in Java 5+).
        
    -   Avoid synchronization on every call.
        
2.  **Context hygiene:** If you need Android context, store **only the `Application` context**. Never hold Activities/Views.
    
3.  **Test seams:** Provide **interfaces** and **reset hooks** (`@VisibleForTesting`) or inject a provider.
    
4.  **Multi-process awareness:** If using multiple processes (remote services, `android:process`), each has its own instance.
    
5.  **Persistence & crash safety:** Don’t rely on a singleton to store critical data—persist it (DB, prefs).
    
6.  **DI-friendly alternative:** With Dagger/Hilt, mark providers `@Singleton` and let DI manage lifecycle.
    

---

## Sample Code (Java, Android-safe singletons)

### A) Thread-safe, lazy singleton for a `SettingsStore` (uses only Application context)

```java
// SettingsStore.java
package singleton.sample;

import android.content.Context;
import android.content.SharedPreferences;
import androidx.annotation.VisibleForTesting;

public final class SettingsStore {

  private static volatile SettingsStore INSTANCE;

  private final SharedPreferences prefs;

  private SettingsStore(Context appContext) {
    this.prefs = appContext.getSharedPreferences("app_settings", Context.MODE_PRIVATE);
  }

  /** Preferred entry: pass any Context; we keep only the Application context. */
  public static SettingsStore getInstance(Context context) {
    SettingsStore local = INSTANCE;
    if (local == null) {
      synchronized (SettingsStore.class) {
        local = INSTANCE;
        if (local == null) {
          INSTANCE = local = new SettingsStore(context.getApplicationContext());
        }
      }
    }
    return local;
  }

  // Example API
  public void setUserToken(String token) {
    prefs.edit().putString("user_token", token).apply();
  }

  public String getUserToken() {
    return prefs.getString("user_token", null);
  }

  @VisibleForTesting
  static void clearInstanceForTests() { INSTANCE = null; }
}
```

**Usage**

```java
// In any Activity/Fragment/Service:
SettingsStore settings = SettingsStore.getInstance(getApplicationContext());
settings.setUserToken("abc123");
```

### B) Lazy holder idiom for a lightweight `Logger` (no context, fully stateless)

```java
// Logger.java
package singleton.sample;

public final class Logger {
  private Logger() {}

  public static Logger get() { return Holder.INSTANCE; }

  private static final class Holder { static final Logger INSTANCE = new Logger(); }

  public void d(String tag, String msg) { android.util.Log.d(tag, msg); }
  public void e(String tag, String msg, Throwable t) { android.util.Log.e(tag, msg, t); }
}
```

### C) Enum Singleton (simple, serialization-safe)

```java
// Analytics.java
package singleton.sample;

public enum Analytics {
  INSTANCE;

  public void track(String event, String details) {
    // send to your analytics pipeline
    android.util.Log.i("Analytics", event + " - " + details);
  }
}
```

> Notes on the three variants
> 
> -   **DCL** (A) is appropriate when you need to pass runtime params (context).
>     
> -   **Lazy holder** (B) is concise for param-less singletons.
>     
> -   **Enum** (C) is inherently single-instance and serialization-safe; not ideal if you must inject runtime dependencies later.
>     

---

## Known Uses

-   **OkHttpClient**: recommended to reuse a single instance (connection pooling).
    
-   **Room database**: apps commonly keep one DB instance per process.
    
-   **Image loaders**: Glide/Picasso manage global caches internally.
    
-   **WorkManager / FirebaseApp**: expose default singletons for app-wide coordination.
    
-   **iOS analogs**: `URLSession.shared`, `NotificationCenter.default` (conceptually singleton).
    

## Related Patterns

-   **Dependency Injection (@Singleton scope):** Prefer this to wire single instances in a testable way.
    
-   **Service Locator (anti-pattern):** A global registry—easy to misuse; worse than DI.
    
-   **Multiton:** Like Singleton but keyed by ID (e.g., per-tenant cache).
    
-   **Factory / Provider:** Create instances without exposing constructors; pairs well with DI.
    
-   **Repository / Facade:** Often implemented as DI-managed singletons, not GoF singletons.
    

---

### Practical Guidance

-   Keep singleton **state minimal**; avoid storing user/session state there—persist it or scope via DI.
    
-   Expose **idempotent init** and **clear/reset** for tests.
    
-   Never retain **Activity/Fragment/View**; if you need callbacks, use **weak references** or observer patterns.
    
-   Document **process-scope** semantics and **multi-process** caveats.
    
-   If you later adopt DI, **wrap** the singleton behind an interface and bind the DI `@Singleton` provider to it, enabling an easy swap without touching call sites.

