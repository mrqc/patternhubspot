# Dependency Injection — Mobile App Architecture Pattern

## Pattern Name and Classification

-   **Name:** Dependency Injection (DI)
    
-   **Classification:** Construction & Composition Pattern (inversion of control for mobile apps)
    

## Intent

Decouple **object creation** from **object use** by supplying a class with the dependencies it needs (via constructors/factories), rather than letting it build/locate them itself. This yields **testable**, **replaceable**, and **scoped** dependencies across app, activity/screen, and feature boundaries.

## Also Known As

-   Inversion of Control (IoC)
    
-   Composition Root
    
-   Injector / Container
    

## Motivation (Forces)

-   **Testability:** Provide stubs/fakes without touching production code.
    
-   **Separation of concerns:** Construction/wiring lives at the edge; classes focus on behavior.
    
-   **Lifecycle scopes:** Reuse expensive objects (e.g., HTTP clients) at **Application** scope; create short-lived ones per **Activity/Fragment**.
    
-   **Swap implementations:** e.g., real vs. mock API, SQLite vs. in-memory cache, feature flags.
    
-   **Avoid hidden coupling:** Replaces singletons/service locators that make code hard to reason about and to test.
    

**Tensions**

-   **Boilerplate:** More constructors/modules/factories.
    
-   **Tooling/learning curve:** DI frameworks add annotations, apt, and generated code.
    
-   **Over-injection:** Injecting everything (instead of passing simple values) can bloat APIs.
    

## Applicability

Use DI when:

-   Your app has **non-trivial graphs** (network, DB, repositories, use cases, VMs).
    
-   You want **fast unit tests** and **swap-in fakes**.
    
-   You need **clear scopes** across Application/Activity/Fragment.
    

Consider lighter options when:

-   Very small utilities/prototypes; manual factories may suffice.
    

## Structure

```css
[Composition Root / Injector]  constructs  ──►  [Graph: Api, DB, Repos, UseCases]
                 ▲                                        ▲
                 │                                        │ ctor injection
        App/Activity start                                │
                 │                                        │
                 └──────── supplies dependencies to ──────┘ [Consumers: ViewModels, Presenters, Controllers]
```

## Participants

-   **Consumers:** Classes that need collaborators (ViewModels, Presenters, Use Cases).
    
-   **Dependencies:** Services, repositories, clients, caches.
    
-   **Interfaces & Qualifiers:** Abstractions and tags (e.g., `@Named("baseUrl")`).
    
-   **Injector / Container:** Manual composition or a framework (Dagger/Hilt, Koin, Toothpick, Guice).
    
-   **Scopes:** Application, Activity/Screen, Feature.
    

## Collaboration

1.  On startup, the **composition root** builds the object graph and exposes factories/components.
    
2.  Consumers receive dependencies via **constructor injection** (preferred) or **field injection** at injection points.
    
3.  Scopes manage lifecycle (app-wide singletons vs. short-lived objects).
    
4.  Tests build a different graph (fakes/mocks) and inject them.
    

## Consequences

**Benefits**

-   **Test-friendly:** No global singletons; easy to stub.
    
-   **Replaceable infrastructure:** Swap HTTP/DB/logging with minimal ripple.
    
-   **Explicit wiring:** Dependencies are visible in constructors and reviews.
    

**Liabilities**

-   **Boilerplate/complexity** (especially with frameworks).
    
-   **Startup work:** Containers generate code/graphs; reflection-heavy DI can impact cold start.
    
-   **Design temptation:** Over-abstracting trivial collaborators.
    

## Implementation

1.  Prefer **constructor injection**; avoid new-ing dependencies inside classes.
    
2.  Centralize wiring in a **composition root** (Application/Activity).
    
3.  Define clear **scopes** and **qualifiers** for variants (debug vs prod, region, tenant).
    
4.  For Android, inject at **Application/Activity/Fragment** boundaries (they’re created by the framework).
    
5.  Keep DI **framework-agnostic** in domain layer; frameworks live in app/data layers.
    
6.  For tests, build graphs with **fakes/mocks** and inject them into the same constructors.
    
7.  Monitor cold start; avoid reflection-heavy containers on the hot path (Dagger/Hilt use codegen, which is good for performance).
    

---

## Sample Code (Java, Android)

Two approaches:

### A) Manual DI (no framework) — explicit, small, test-friendly

**Domain & data**

```java
// api/UserApi.java
package di.sample;
import java.util.UUID;
public interface UserApi { UserDto getUser(UUID id) throws Exception; }

// api/UserDto.java
package di.sample;
import java.util.UUID;
public class UserDto { public UUID id; public String name; public String email; }

// data/UserRepository.java
package di.sample;
import java.util.UUID;
public interface UserRepository { User get(UUID id) throws Exception; }

// data/UserRepositoryImpl.java
package di.sample;
import java.util.UUID;
public final class UserRepositoryImpl implements UserRepository {
  private final UserApi api; private final Cache cache;
  public UserRepositoryImpl(UserApi api, Cache cache) { this.api = api; this.cache = cache; }
  @Override public User get(UUID id) throws Exception {
    User u = cache.get(id); if (u != null) return u;
    UserDto dto = api.getUser(id);
    u = new User(dto.id, dto.name, dto.email);
    cache.put(u); return u;
  }
}

// data/Cache.java
package di.sample;
import java.util.*;
public final class Cache {
  private final Map<java.util.UUID, User> map = new HashMap<>();
  public User get(java.util.UUID id){ return map.get(id); }
  public void put(User u){ map.put(u.id(), u); }
}

// domain/User.java
package di.sample;
import java.util.UUID;
public record User(UUID id, String name, String email) {}
```

**Use case & presenter**

```java
// domain/GetUser.java
package di.sample;
import java.util.UUID;
public final class GetUser {
  private final UserRepository repo;
  public GetUser(UserRepository repo){ this.repo = repo; }
  public User execute(UUID id) throws Exception { return repo.get(id); }
}

// ui/UserPresenter.java
package di.sample;
import java.util.UUID;
public final class UserPresenter {
  public interface View { void showLoading(); void showUser(String name, String email); void showError(String msg); }
  private final GetUser getUser; private final View view;
  public UserPresenter(GetUser getUser, View view){ this.getUser = getUser; this.view = view; }
  public void load(UUID id) {
    view.showLoading();
    new Thread(() -> {
      try {
        User u = getUser.execute(id);
        view.showUser(u.name(), u.email());
      } catch (Exception e) { view.showError(e.getMessage()); }
    }).start();
  }
}
```

**Composition root (manual)**

```java
// di/CompositionRoot.java
package di.sample;
import java.util.UUID;

public final class CompositionRoot {
  private final String baseUrl;
  private final Cache cache = new Cache();

  public CompositionRoot(String baseUrl) { this.baseUrl = baseUrl; }

  // factories
  public UserApi userApi() {
    return id -> { // very small fake HTTP client (replace with Retrofit)
      UserDto dto = new UserDto();
      dto.id = id; dto.name = "Ada Lovelace"; dto.email = "ada@example.com";
      return dto;
    };
  }
  public UserRepository userRepo() { return new UserRepositoryImpl(userApi(), cache); }
  public GetUser getUser() { return new GetUser(userRepo()); }
  public UserPresenter presenter(UserPresenter.View view) { return new UserPresenter(getUser(), view); }

  // demo
  public static void main(String[] args) {
    CompositionRoot root = new CompositionRoot("https://api.example.com");
    UserPresenter.View view = new UserPresenter.View() {
      @Override public void showLoading() { System.out.println("Loading..."); }
      @Override public void showUser(String name, String email) { System.out.println(name+" <"+email+">"); }
      @Override public void showError(String msg) { System.err.println(msg); }
    };
    root.presenter(view).load(UUID.randomUUID());
  }
}
```

**Why this is DI:** all collaborators are **passed in** (constructors/factories). For tests, build `CompositionRoot` with **fake** `UserApi` or a prefilled `Cache`.

---

### B) Dagger (compile-time DI) — scoped, fast, production-ready

> Minimal Dagger setup showing **Application scope** singletons and an **Activity scope** presenter.

**Gradle (snippet)**

```gradle
implementation "com.google.dagger:dagger:2.51"
annotationProcessor "com.google.dagger:dagger-compiler:2.51"
```

**Scopes**

```java
// di/ActivityScope.java
package di.dagger;
@javax.inject.Scope @java.lang.annotation.Retention(java.lang.annotation.RetentionPolicy.RUNTIME)
public @interface ActivityScope {}
```

**Modules**

```java
// di/NetworkModule.java
package di.dagger;
import dagger.*; import javax.inject.*; import di.sample.*;

@Module
public class NetworkModule {
  private final String baseUrl;
  public NetworkModule(String baseUrl){ this.baseUrl = baseUrl; }

  @Provides @Singleton @Named("baseUrl")
  String baseUrl(){ return baseUrl; }

  @Provides @Singleton
  Cache cache(){ return new Cache(); }

  @Provides @Singleton
  UserApi userApi(@Named("baseUrl") String base){  // could return Retrofit impl
    return id -> {
      UserDto dto = new UserDto();
      dto.id = id; dto.name = "Grace Hopper"; dto.email = "grace@example.com";
      return dto;
    };
  }
}

@Module
interface RepoModule {
  @Binds @Singleton
  UserRepository bindRepo(di.sample.UserRepositoryImpl impl);
}
```

**App component & Activity subcomponent**

```java
// di/AppComponent.java
package di.dagger;
import dagger.*; import javax.inject.*; import di.sample.*;

@Singleton
@Component(modules = { NetworkModule.class, RepoModule.class })
public interface AppComponent {
  ActivityComponent.Factory activityComponent();
}

// di/ActivityComponent.java
package di.dagger;
import dagger.*; import di.sample.*;

@ActivityScope
@Subcomponent
public interface ActivityComponent {
  @Subcomponent.Factory interface Factory { ActivityComponent create(); }
  void inject(MainActivity activity);
}
```

**Consumers with `@Inject`**

```java
// di/sample/UserRepositoryImpl.java (enable @Inject ctor)
package di.sample;
import javax.inject.Inject;

public final class UserRepositoryImpl implements UserRepository {
  private final UserApi api; private final Cache cache;
  @Inject public UserRepositoryImpl(UserApi api, Cache cache){ this.api=api; this.cache=cache; }
  // ... (same impl as above)
}

// di/sample/UserPresenter.java
package di.sample;
import javax.inject.Inject;
public final class UserPresenter {
  public interface View { void showLoading(); void showUser(String n, String e); void showError(String m); }
  private final GetUser getUser; private final View view;
  @Inject public UserPresenter(GetUser getUser, View view){ this.getUser=getUser; this.view=view; }
  // ...
}

// di/sample/GetUser.java
package di.sample;
import javax.inject.Inject;
public final class GetUser {
  private final UserRepository repo;
  @Inject public GetUser(UserRepository repo){ this.repo = repo; }
  public User execute(java.util.UUID id) throws Exception { return repo.get(id); }
}
```

**Android wiring**

```java
// App.java
package di.app;
import android.app.Application; import di.dagger.*;

public class App extends Application {
  private AppComponent appComponent;
  @Override public void onCreate() {
    super.onCreate();
    appComponent = DaggerAppComponent.builder()
        .networkModule(new NetworkModule("https://api.example.com"))
        .build();
  }
  public AppComponent appComponent(){ return appComponent; }
}
```

```java
// MainActivity.java
package di.app;
import android.os.Bundle;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;
import javax.inject.Inject;
import di.dagger.ActivityComponent;
import di.sample.UserPresenter;

public class MainActivity extends AppCompatActivity implements UserPresenter.View {

  @Inject UserPresenter presenter; // view is this (bound via Activity module or assisted)

  private ActivityComponent activityComponent;

  @Override protected void onCreate(@Nullable Bundle savedInstanceState) {
    super.onCreate(savedInstanceState);
    ((App)getApplication()).appComponent()
        .activityComponent().create()
        .inject(this);

    presenter.load(java.util.UUID.randomUUID());
  }

  // UserPresenter.View impl
  @Override public void showLoading(){ /* ... */ }
  @Override public void showUser(String n, String e){ /* ... */ }
  @Override public void showError(String m){ /* ... */ }
}
```

> Notes
> 
> -   Real projects often inject **ViewModels** instead of direct presenters; with Dagger you can provide `ViewModelProvider.Factory`.
>     
> -   Hilt simplifies Android entry points (`@HiltAndroidApp`, `@AndroidEntryPoint`), but pure Dagger is shown here for Java clarity.
>     
> -   For tests, create a **TestComponent** or pass a different `NetworkModule` to return fakes.
>     

---

## Known Uses

-   **Android:** Dagger 2 / **Hilt** (codegen, fast), **Koin**/**Toothpick** (runtime DI), legacy **Guice**.
    
-   **iOS:** **Swinject**, **Needle**, **Resolver** for Swift apps (same pattern, different ecosystem).
    
-   Heavily used in modularized apps where features own their graphs and expose **component interfaces** to other modules.
    

## Related Patterns

-   **Clean Architecture (Mobile):** DI wires infrastructure to domain/use-cases.
    
-   **Factory / Abstract Factory / Builder:** Object creation helpers often used inside DI modules.
    
-   **Service Locator (anti-pattern):** The opposite of DI; prefer DI to avoid hidden global state.
    
-   **Coordinator:** Works with DI to inject flow dependencies.
    
-   **Repository Pattern:** Common dependency injected into use-cases/VMs.
    
-   **Facade / Adapter:** Often injected to isolate frameworks (e.g., wrap Retrofit/Room).

