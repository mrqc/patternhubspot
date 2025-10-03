# Repository — Mobile App Architecture Pattern

## Pattern Name and Classification

-   **Name:** Repository
    
-   **Classification:** Data Access & Abstraction Pattern (presentation/domain-facing gateway to data sources)
    

## Intent

Provide a **single, cohesive interface** for retrieving and persisting domain objects while **hiding** the details of data sources (HTTP, local DB, cache, files, sensors). The Repository offers **use-case friendly APIs**, centralizes caching/merging, and enables **offline-first** strategies.

## Also Known As

-   Data Access Facade
    
-   Data Gateway
    
-   Persistence Abstraction
    

## Motivation (Forces)

-   **Multiple sources:** Remote API + local database + in-memory cache.
    
-   **Offline & latency:** UI needs instant reads with eventual synchronization.
    
-   **Testability:** Domain/presentation should not depend on Retrofit/Room/SQLite.
    
-   **Consistency:** Centralize mapping, validation, and conflict handling.
    
-   **Evolution:** Swap REST ↔ GraphQL, Room ↔ Realm without touching callers.
    

**Tensions**

-   **Over-abstraction:** Too generic repositories hide useful capabilities.
    
-   **State & staleness:** Must define freshness, invalidation, and merge rules.
    
-   **Concurrency:** Multiple writers/readers; avoid race conditions and UI jank.
    

## Applicability

Use Repository when:

-   You have **non-trivial data flows** (cache + network, pagination, sync).
    
-   You want **UI-agnostic** data APIs and **unit-testable** presentation logic.
    
-   You need **offline** or **retry** semantics.
    

Avoid/limit when:

-   The app is tiny and only does one-off network calls (a simple client might suffice).
    

## Structure

```pgsql
View / ViewModel / Presenter
        │
        ▼
   ┌───────────────┐     (interface, domain types)
   │   Repository   │
   └───────┬───────┘
           │ orchestrates: cache-aside / read-through / write-through
  ┌────────┴────────┐
  │                 │
Local Data Source   Remote Data Source
(Room/SQL/Files)    (Retrofit/GraphQL/gRPC)
  │                 │
  └─── Mappers/DTO ↔┘  (+ policy: freshness, conflict, idempotency)
```

## Participants

-   **Repository Interface:** Domain-facing API (`getUser(id)`, `save(note)`), returns domain models or observable `State`.
    
-   **Repository Implementation:** Orchestrates sources, caching, mapping, threading.
    
-   **Local Data Source:** Room/Realm/SQLite; persist domain snapshots.
    
-   **Remote Data Source:** Retrofit/gRPC client; fetches/mutates server state.
    
-   **Mappers/DTOs:** Convert between transport/DB types and domain models.
    
-   **Policy Objects:** Freshness windows, conflict resolution, retry/backoff.
    

## Collaboration

1.  UI calls Repository (e.g., `getUser(id)`), typically receives **observable** data.
    
2.  Repository **immediately** serves local snapshot; decides whether to **fetch/refresh**.
    
3.  If remote fetch occurs, Repository **persists** result locally and **emits** updated data.
    
4.  Writes: Repository writes to local first (optional outbox) and **syncs** to remote (write-through).
    

## Consequences

**Benefits**

-   **Decoupling:** UI and domain independent of data tech.
    
-   **Single policy point:** Consistent caching, mapping, errors.
    
-   **Testability:** Swap fakes/mocks; simulate offline easily.
    
-   **Offline-first:** Natural fit with local-as-source-of-truth.
    

**Liabilities**

-   **Extra code/boilerplate:** Interfaces, mappers, models, state wrappers.
    
-   **Risk of anemic APIs:** Too CRUD-like, not use-case oriented.
    
-   **Hidden complexity:** Wrong freshness/conflict policies can cause subtle bugs.
    

## Implementation

1.  **Start with the interface** in the domain module; name APIs by use cases, not CRUD.
    
2.  **Choose a state carrier**: `LiveData`, Flow/Observable, or callbacks; include **loading/error**.
    
3.  **Define freshness** (TTL) and **invalidations** (explicit refresh, mutation success, app events).
    
4.  **Make local the source of truth** (recommended): write-through updates local, remote sync updates local, UI observes local.
    
5.  **Map types** at boundaries; do not leak DTOs/Entities into the domain/presentation.
    
6.  **Threading**: do IO off main; post results on main.
    
7.  **Testing**: provide an in-memory/fake Repository; assert behavior under offline/timeout/merge conditions.
    

---

## Sample Code (Java, Android — Repository with Room + Retrofit + LiveData)

> A minimal **UserRepository** that:
> 
> -   Returns **LiveData<Resource<User>>**.
>     
> -   Reads from Room immediately; **refreshes** from Retrofit on staleness or when forced.
>     
> -   Persists server result, then emits updated domain data.
>     

### 1) Domain Model

```java
// domain/User.java
package repo.domain;

import java.util.Objects;

public final class User {
  private final String id;
  private final String name;
  private final String email;

  public User(String id, String name, String email) {
    this.id = Objects.requireNonNull(id);
    this.name = Objects.requireNonNull(name);
    this.email = Objects.requireNonNull(email);
  }
  public String id() { return id; }
  public String name() { return name; }
  public String email() { return email; }
}
```

### 2) State Wrapper

```java
// common/Resource.java
package repo.common;

import androidx.annotation.Nullable;

public final class Resource<T> {
  public enum Status { LOADING, SUCCESS, ERROR }
  public final Status status;
  public final T data;
  public final String message;

  private Resource(Status s, @Nullable T d, @Nullable String m) {
    this.status = s; this.data = d; this.message = m;
  }
  public static <T> Resource<T> loading(@Nullable T d){ return new Resource<>(Status.LOADING, d, null); }
  public static <T> Resource<T> success(T d){ return new Resource<>(Status.SUCCESS, d, null); }
  public static <T> Resource<T> error(String m, @Nullable T d){ return new Resource<>(Status.ERROR, d, m); }
}
```

### 3) Local (Room)

```java
// data/local/UserEntity.java
package repo.data.local;

import androidx.annotation.NonNull;
import androidx.room.Entity;
import androidx.room.PrimaryKey;

@Entity(tableName = "user")
public class UserEntity {
  @PrimaryKey @NonNull public String id;
  public String name;
  public String email;
  public long updatedAtMs; // last local update (for freshness)
}
```

```java
// data/local/UserDao.java
package repo.data.local;

import androidx.lifecycle.LiveData;
import androidx.room.*;

@Dao
public interface UserDao {
  @Query("SELECT * FROM user WHERE id = :id LIMIT 1")
  LiveData<UserEntity> live(String id);

  @Query("SELECT * FROM user WHERE id = :id LIMIT 1")
  UserEntity get(String id);

  @Insert(onConflict = OnConflictStrategy.REPLACE)
  void upsert(UserEntity e);
}
```

```java
// data/local/AppDb.java
package repo.data.local;

import androidx.room.Database;
import androidx.room.RoomDatabase;

@Database(entities = {UserEntity.class}, version = 1)
public abstract class AppDb extends RoomDatabase {
  public abstract UserDao users();
}
```

### 4) Remote (Retrofit)

```java
// data/remote/UserDto.java
package repo.data.remote;
public class UserDto { public String id; public String name; public String email; public long serverUpdatedAtMs; }
```

```java
// data/remote/UserService.java
package repo.data.remote;

import retrofit2.Call;
import retrofit2.http.GET;
import retrofit2.http.Path;

public interface UserService {
  @GET("users/{id}")
  Call<UserDto> getUser(@Path("id") String id);
}
```

### 5) Mappers

```java
// data/mapper/UserMapper.java
package repo.data.mapper;

import repo.data.local.UserEntity;
import repo.data.remote.UserDto;
import repo.domain.User;

public final class UserMapper {
  public static User toDomain(UserEntity e) {
    return e == null ? null : new User(e.id, e.name, e.email);
  }
  public static UserEntity toEntity(UserDto d) {
    if (d == null) return null;
    UserEntity e = new UserEntity();
    e.id = d.id; e.name = d.name; e.email = d.email;
    e.updatedAtMs = Math.max(d.serverUpdatedAtMs, System.currentTimeMillis());
    return e;
  }
}
```

### 6) Repository API

```java
// domain/UserRepository.java
package repo.domain;

import androidx.lifecycle.LiveData;
import repo.common.Resource;

public interface UserRepository {
  LiveData<Resource<User>> getUser(String id, boolean forceRefresh);
  void refreshUser(String id); // explicit refresh trigger (optional)
}
```

### 7) Repository Implementation

```java
// data/UserRepositoryImpl.java
package repo.data;

import androidx.lifecycle.*;
import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

import java.util.concurrent.Executor;
import java.util.concurrent.Executors;

import repo.common.Resource;
import repo.data.local.*;
import repo.data.mapper.UserMapper;
import repo.data.remote.*;
import repo.domain.User;
import repo.domain.UserRepository;

public class UserRepositoryImpl implements UserRepository {

  private static final long STALE_MS = 10 * 60 * 1000; // 10 minutes

  private final AppDb db;
  private final UserDao dao;
  private final UserService api;
  private final Executor io = Executors.newSingleThreadExecutor();

  public UserRepositoryImpl(AppDb db, UserService api) {
    this.db = db; this.dao = db.users(); this.api = api;
  }

  @Override
  public LiveData<Resource<User>> getUser(String id, boolean forceRefresh) {
    MediatorLiveData<Resource<User>> out = new MediatorLiveData<>();
    LiveData<UserEntity> source = dao.live(id);
    out.setValue(Resource.loading(null));

    out.addSource(source, entity -> {
      User domain = UserMapper.toDomain(entity);
      out.setValue(domain == null ? Resource.loading(null) : Resource.success(domain));

      boolean stale = isStale(entity);
      if (entity == null || forceRefresh || stale) {
        fetchAndPersist(id, out, domain); // pass current domain for interim display on error
      }
    });
    return out;
  }

  @Override
  public void refreshUser(String id) { fetchAndPersist(id, null, null); }

  private void fetchAndPersist(String id, MediatorLiveData<Resource<User>> out, User current) {
    api.getUser(id).enqueue(new Callback<>() {
      @Override public void onResponse(Call<UserDto> call, Response<UserDto> resp) {
        if (!resp.isSuccessful() || resp.body() == null) {
          if (out != null) out.postValue(Resource.error("Server error " + resp.code(), current));
          return;
        }
        io.execute(() -> {
          UserEntity e = UserMapper.toEntity(resp.body());
          db.runInTransaction(() -> dao.upsert(e));
        });
      }
      @Override public void onFailure(Call<UserDto> call, Throwable t) {
        if (out != null) out.postValue(Resource.error("Network error", current));
      }
    });
  }

  private boolean isStale(UserEntity e) {
    return e == null || (System.currentTimeMillis() - e.updatedAtMs) > STALE_MS;
  }
}
```

### 8) Usage from ViewModel (example)

```java
// vm/UserViewModel.java
package repo.vm;

import androidx.lifecycle.*;
import repo.common.Resource;
import repo.domain.User;
import repo.domain.UserRepository;

public class UserViewModel extends ViewModel {
  private final UserRepository repo;
  private LiveData<Resource<User>> live;

  public UserViewModel(UserRepository repo) { this.repo = repo; }

  public LiveData<Resource<User>> user(String id, boolean force) {
    if (live == null) live = repo.getUser(id, force);
    return live;
  }

  public void refresh(String id) { repo.refreshUser(id); }
}
```

---

## Known Uses

-   **Android Jetpack samples** and many production codebases: Repository mediates Room + Retrofit.
    
-   **Offline-first apps** (notes, messaging, field service): repository fronts local DB with sync engines.
    
-   **Multi-source data** (remote + BLE/sensors/files): repository composes heterogeneous inputs.
    

## Related Patterns

-   **Offline First Sync / Transactional Outbox:** Repositories often host the outbox & sync triggers.
    
-   **Clean Architecture (Mobile):** Repository is the **port**; implementations are adapters.
    
-   **MVVM / MVP / MVC:** Presentation talks to Repository, not to data sources directly.
    
-   **Cache-Aside / Read-Through / Write-Through:** Repository implements these caching policies.
    
-   **Gateway/Facade:** Repository is a domain-focused facade over data infrastructure.
    

---

### Practical Tips

-   Keep repositories **use-case oriented** (e.g., `searchUsers`, `loadTimeline(page)`), not generic CRUD.
    
-   Prefer **local-as-source-of-truth** with change observation → smooth UI and offline capability.
    
-   Centralize **error mapping** and **retry policies** in repositories.
    
-   Expose **immutable domain models**; keep DTO/Entity private to data layer.
    
-   Add **metrics/logging** around fetch vs. cache hits to tune staleness thresholds.

