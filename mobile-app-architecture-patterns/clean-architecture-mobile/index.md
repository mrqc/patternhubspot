# Clean Architecture Mobile — Mobile App Architecture Pattern

## Pattern Name and Classification

-   **Name:** Clean Architecture (Mobile)
    
-   **Classification:** Layered, dependency-inverted **application architecture** for mobile apps (Android/iOS). Combines concepts from **Hexagonal/Ports & Adapters** and **Onion Architecture** applied to client apps.
    

## Intent

Isolate **business rules** from **frameworks and delivery mechanisms** (UI, persistence, network) so your mobile app is:

-   **Testable** (domain/use-cases without device or UI),
    
-   **Independent** of frameworks (Android/iOS, DB, HTTP client),
    
-   **Maintainable & evolvable** (replace data sources or UI with minimal ripple).
    

## Also Known As

-   Ports and Adapters (on mobile)
    
-   Onion Architecture (mobile flavor)
    
-   Dependency-Inverted Layers / Use-Case Driven Architecture
    

## Motivation (Forces)

-   **Framework churn:** Mobile APIs, SDKs, and libraries evolve quickly; you want minimal blast radius.
    
-   **Offline/spotty networks:** Business flows should be correct regardless of connectivity; infra varies by platform.
    
-   **UI volatility:** Screens change frequently; business policies change less often—separate them.
    
-   **Testability:** Running device/emulator tests is slow; pure JVM/unit tests for core rules speed up feedback.
    
-   **Team scale:** Parallel development (UI, data, domain) requires clear seams and contracts.
    

**Counterforces**

-   **Initial overhead:** More classes/modules and mapping boilerplate.
    
-   **Over-abstracting small apps:** For simple or short-lived apps, this can be heavy.
    

## Applicability

Use Clean Architecture Mobile when:

-   The app has **non-trivial domain logic**, offline support, or multiple data sources.
    
-   You target **multiple platforms** or expect frequent UI/SDK swaps.
    
-   You need **reliable tests** that don’t depend on device/emulator.
    

Consider a lighter approach when:

-   It’s a small prototype or throwaway utility.
    
-   Domain logic is minimal and mostly “CRUD over HTTP”.
    

## Structure

Key rule: **Dependencies point inward** (UI/Data → Domain). The domain layer knows nothing about Android/iOS, databases, or HTTP.

```lua
+--------------------------------------------------------------+
|                    Frameworks & Devices                      |
|   (Android/iOS SDK, Retrofit/OkHttp, Room/Realm, Bluetooth)  |
+-----------------------↑------------------↑-------------------+
                        |                  |
                Interface Adapters   Infrastructure
                 (Presenters/VMs,     (Rest, DB, cache,
                 Controllers, Mappers)  sensors, etc.)
                        ↑                  ↑
                        |                  |
                     Use Cases (Interactors)  <--- Orchestrate application-specific rules
                        ↑
                        |
                     Entities (Domain Model, pure)
```

**Modules (typical):**

-   `domain/` — entities, value objects, **use cases**, repository **interfaces**.
    
-   `data/` — repository **implementations**, DTOs, mappers, data sources (remote/local).
    
-   `app/` — UI (Activity/Fragment/ViewModel), DI wiring, platform glue.
    

## Participants

-   **Entities (Domain Model):** Core business objects and invariants (pure Java).
    
-   **Use Cases / Interactors:** Application-specific orchestrators; depend on **interfaces** (ports).
    
-   **Repository Interfaces (Ports):** Domain’s view of persistence/network, defined in `domain`.
    
-   **Presenters / ViewModels / Controllers (Adapters):** Translate domain responses into UI models.
    
-   **Mappers:** Convert between DTOs ↔ domain ↔ UI.
    
-   **Data Sources (Adapters):** Implement ports using HTTP/DB/Cache.
    
-   **DI Container (optional):** Wires implementations to interfaces at the edge.
    

## Collaboration

1.  UI triggers **Use Case** (e.g., “Load user profile”).
    
2.  Use Case calls **Repository interface**; applies business rules, policies, and orchestrates sources.
    
3.  **Data layer** implements repository, fetching from local/remote, mapping **DTO → Domain**.
    
4.  Use Case returns a **Result** to Presenter/ViewModel.
    
5.  Presenter/ViewModel maps **Domain → UI model** and updates the view; errors are shown via states.
    

## Consequences

**Benefits**

-   Highly **testable** domain and use-cases (no Android/iOS deps).
    
-   **Replaceable infrastructure** (swap REST for GraphQL, Room for Realm) with minimal changes.
    
-   Clear seams → **parallel work** across teams.
    

**Liabilities**

-   **Boilerplate & mapping** overhead.
    
-   Requires discipline to keep dependencies pointing inward.
    
-   Overkill for small apps.
    

## Implementation

1.  **Split modules** (logical or Gradle): `domain`, `data`, `app`.
    
2.  In `domain`: define **entities**, **value objects**, **Result/Either**, **use-case classes**, **repository interfaces**.
    
3.  In `data`: implement repositories; add **DTOs**, **mappers**, **data sources** (remote/local), caching policy.
    
4.  In `app`: presenters or **ViewModels**, UI models/states, minimal Android code.
    
5.  **Threading**: keep domain synchronous where possible; schedule in presentation layer (Executors) or use reactive streams.
    
6.  **Error handling**: prefer typed `Result` over exceptions at boundaries.
    
7.  **DI**: manual wiring for clarity, or Hilt/Dagger/Koin on Android.
    
8.  **Testing**: unit-test use cases with fake repositories; instrument only adapters.
    

---

## Sample Code (Java, Android-friendly — 3-layer, minimal dependencies)

> Scenario: Show a **User Profile**. Domain defines `User`, `GetUserProfile` use case, and a `UserRepository` port. Data implements the port from a remote API + in-memory cache. App uses a ViewModel to call the use case on a background executor and exposes **immutable UI state**.

### `domain` module

```java
// domain/src/main/java/domain/User.java
package domain;

import java.util.Objects;
import java.util.UUID;

public final class User {
  private final UUID id;
  private final String name;
  private final String email;

  public User(UUID id, String name, String email) {
    this.id = Objects.requireNonNull(id);
    this.name = Objects.requireNonNull(name);
    this.email = Objects.requireNonNull(email);
  }
  public UUID id() { return id; }
  public String name() { return name; }
  public String email() { return email; }
}
```

```java
// domain/src/main/java/domain/Result.java
package domain;

import java.util.function.Function;

public abstract class Result<T> {
  public static final class Ok<T> extends Result<T> { public final T value; public Ok(T v){ this.value = v; } }
  public static final class Err<T> extends Result<T> { public final String message; public Err(String m){ this.message = m; } }

  public <R> R fold(Function<T,R> onOk, Function<String,R> onErr) {
    if (this instanceof Ok<T> ok) return onOk.apply(ok.value);
    return onErr.apply(((Err<T>)this).message);
  }

  public static <T> Result<T> ok(T v) { return new Ok<>(v); }
  public static <T> Result<T> err(String m) { return new Err<>(m); }
}
```

```java
// domain/src/main/java/domain/UserRepository.java
package domain;

import java.util.UUID;

public interface UserRepository {
  Result<User> findById(UUID id);
}
```

```java
// domain/src/main/java/domain/GetUserProfile.java
package domain;

import java.util.UUID;

public final class GetUserProfile {
  private final UserRepository repo;

  public GetUserProfile(UserRepository repo) { this.repo = repo; }

  /** Domain use case: policy could include caching rules, validation, etc. */
  public Result<User> execute(UUID userId) {
    if (userId == null) return Result.err("invalid user id");
    return repo.findById(userId);
  }
}
```

### `data` module

```java
// data/src/main/java/data/dto/UserDto.java
package data.dto;

import java.util.UUID;

public class UserDto {
  public UUID id;
  public String fullName;
  public String email;
}
```

```java
// data/src/main/java/data/mapper/UserMapper.java
package data.mapper;

import data.dto.UserDto;
import domain.User;

public final class UserMapper {
  public static User toDomain(UserDto dto) {
    return new User(dto.id, dto.fullName, dto.email);
  }
}
```

```java
// data/src/main/java/data/remote/UserApi.java
package data.remote;

import data.dto.UserDto;
import java.util.UUID;

/** Replace with Retrofit/OkHttp in real projects; kept simple here. */
public interface UserApi {
  UserDto getUser(UUID id) throws Exception;
}
```

```java
// data/src/main/java/data/cache/UserCache.java
package data.cache;

import data.dto.UserDto;
import java.util.*;

public final class UserCache {
  private final Map<UUID, UserDto> byId = new HashMap<>();
  public Optional<UserDto> get(UUID id) { return Optional.ofNullable(byId.get(id)); }
  public void put(UserDto dto) { byId.put(dto.id, dto); }
}
```

```java
// data/src/main/java/data/UserRepositoryImpl.java
package data;

import data.cache.UserCache;
import data.mapper.UserMapper;
import data.remote.UserApi;
import data.dto.UserDto;
import domain.*;

import java.util.UUID;

public final class UserRepositoryImpl implements UserRepository {
  private final UserApi api;
  private final UserCache cache;

  public UserRepositoryImpl(UserApi api, UserCache cache) {
    this.api = api; this.cache = cache;
  }

  @Override
  public Result<User> findById(UUID id) {
    // 1) try cache
    var cached = cache.get(id);
    if (cached.isPresent()) return Result.ok(UserMapper.toDomain(cached.get()));
    // 2) remote
    try {
      UserDto dto = api.getUser(id);
      if (dto == null) return Result.err("not found");
      cache.put(dto);
      return Result.ok(UserMapper.toDomain(dto));
    } catch (Exception e) {
      return Result.err("network error: " + e.getMessage());
    }
  }
}
```

### `app` module (Android UI + ViewModel)

```java
// app/src/main/java/app/ui/UserUiModel.java
package app.ui;

public final class UserUiModel {
  public final String title;
  public final String subtitle;
  public UserUiModel(String title, String subtitle) {
    this.title = title; this.subtitle = subtitle;
  }
}
```

```java
// app/src/main/java/app/ui/UserState.java
package app.ui;

public abstract class UserState {
  public static final class Loading extends UserState {}
  public static final class Success extends UserState { public final UserUiModel user; public Success(UserUiModel u){ this.user = u; } }
  public static final class Error extends UserState { public final String message; public Error(String m){ this.message = m; } }
}
```

```java
// app/src/main/java/app/ui/UserViewModel.java
package app.ui;

import androidx.lifecycle.*;
import java.util.UUID;
import java.util.concurrent.*;

import domain.GetUserProfile;
import domain.Result;

public class UserViewModel extends ViewModel {
  private final GetUserProfile getUserProfile;
  private final ExecutorService io = Executors.newSingleThreadExecutor();

  private final MutableLiveData<UserState> _state = new MutableLiveData<>(new UserState.Loading());
  public LiveData<UserState> state = _state;

  public UserViewModel(GetUserProfile useCase) {
    this.getUserProfile = useCase;
  }

  public void load(UUID userId) {
    _state.postValue(new UserState.Loading());
    io.submit(() -> {
      Result<domain.User> res = getUserProfile.execute(userId);
      _state.postValue(res.fold(
          user -> new UserState.Success(new UserUiModel(user.name(), user.email())),
          err  -> new UserState.Error(err)
      ));
    });
  }

  @Override protected void onCleared() { io.shutdownNow(); }
}
```

```java
// app/src/main/java/app/di/CompositionRoot.java
package app.di;

import app.ui.UserViewModel;
import androidx.lifecycle.ViewModel;
import androidx.lifecycle.ViewModelProvider;
import data.UserRepositoryImpl;
import data.cache.UserCache;
import data.remote.UserApi;
import domain.GetUserProfile;
import domain.UserRepository;

import java.util.UUID;

// Simple manual DI for clarity
public final class CompositionRoot {

  // Fake API implementation (replace with Retrofit)
  private static final UserApi api = id -> {
    // emulate network
    data.dto.UserDto dto = new data.dto.UserDto();
    dto.id = id; dto.fullName = "Ada Lovelace"; dto.email = "ada@example.com";
    return dto;
  };

  public static ViewModelProvider.Factory userVmFactory() {
    return new ViewModelProvider.Factory() {
      @Override public <T extends ViewModel> T create(Class<T> modelClass) {
        UserRepository repo = new UserRepositoryImpl(api, new UserCache());
        GetUserProfile uc = new GetUserProfile(repo);
        return (T) new app.ui.UserViewModel(uc);
      }
    };
  }

  // Helper for demo usage
  public static UUID demoUserId() { return UUID.fromString("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"); }
}
```

```java
// app/src/main/java/app/ui/UserActivity.java
package app.ui;

import android.os.Bundle;
import android.widget.TextView;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;
import androidx.lifecycle.ViewModelProvider;
import app.di.CompositionRoot;

public class UserActivity extends AppCompatActivity {

  private UserViewModel vm;
  private TextView title, subtitle, error;

  @Override protected void onCreate(@Nullable Bundle savedInstanceState) {
    super.onCreate(savedInstanceState);
    setContentView(new android.widget.LinearLayout(this) {{
      setOrientation(VERTICAL);
      title = new TextView(getContext()); addView(title);
      subtitle = new TextView(getContext()); addView(subtitle);
      error = new TextView(getContext()); addView(error);
    }});

    vm = new ViewModelProvider(this, CompositionRoot.userVmFactory()).get(UserViewModel.class);
    vm.state.observe(this, s -> {
      if (s instanceof UserState.Loading) { title.setText("Loading…"); subtitle.setText(""); error.setText(""); }
      else if (s instanceof UserState.Success suc) { title.setText(suc.user.title); subtitle.setText(suc.user.subtitle); error.setText(""); }
      else if (s instanceof UserState.Error err) { error.setText(err.message); }
    });

    vm.load(CompositionRoot.demoUserId());
  }
}
```

> Notes:
> 
> -   The **domain** doesn’t import Android or HTTP/DB; it is pure Java → fast unit tests.
>     
> -   Swapping the **UserApi** or adding Room cache only touches the `data` module.
>     
> -   UI changes (View → Compose/SwiftUI) don’t ripple into domain or data.
>     

---

## Known Uses

-   Android community samples and many production apps adopt Clean Architecture variants (e.g., **Android Architecture Blueprints**, modularized apps using **domain/data/app** split).
    
-   Teams migrating legacy Android Java to Kotlin/Compose often keep the **domain/use-case** core intact while they replace UI/infrastructure.
    

## Related Patterns

-   **Hexagonal Architecture / Ports & Adapters** — conceptual foundation (domain defines ports; adapters implement them).
    
-   **Onion Architecture** — concentric layers with dependencies pointing inward.
    
-   **MVVM/MVP/MVI** — presentation patterns that fit the outer layer.
    
-   **Repository Pattern** — domain-facing persistence abstraction.
    
-   **Dependency Inversion Principle (DIP)** — central rule enabling UI/Data to depend on domain.
    
-   **Unidirectional Data Flow (UDF)** — complements Clean in presentation state handling.
    
-   **Strangler Fig** — migrate legacy mobile modules behind a new façade while keeping domain core clean.

