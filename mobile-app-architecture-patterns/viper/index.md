# VIPER — Mobile App Architecture Pattern

## Pattern Name and Classification

-   **Name:** VIPER (View–Interactor–Presenter–Entity–Router)
    
-   **Classification:** Presentation & Application Architecture Pattern (screen/feature modularization)
    

## Intent

Divide a feature into **five roles**—**View**, **Interactor**, **Presenter**, **Entity**, **Router**—to achieve **highly modular**, **testable**, and **navigable** screens. VIPER enforces strict unidirectional dependencies, clear boundaries between **UI**, **application logic**, and **navigation**.

## Also Known As

-   VIP
    
-   VIPER Clean Architecture (iOS origin)
    

## Motivation (Forces)

-   **Complex features** mix UI rendering, orchestration, data access, and navigation.
    
-   **Testability** suffers when logic lives inside controllers/views.
    
-   **Navigation** rules leak across screens without a single owner.
    
-   **Team scaling** requires stable contracts per feature.
    

**Tensions**

-   **Boilerplate:** Multiple interfaces/classes per feature.
    
-   **Over-engineering for small screens:** For trivial flows, VIPER may be heavy.
    
-   **Discipline required:** Sloppy boundaries turn VIPER into “MVP + extra files”.
    

## Applicability

Use VIPER when:

-   Features have **non-trivial orchestration**, validations, and branching.
    
-   You want **strict separation** of navigation (Router) and application logic (Interactor).
    
-   The codebase is **modularized** with teams owning features.
    

Consider lighter patterns when:

-   The screen is simple (MVVM/MVP may be enough).
    
-   You already standardized on a unidirectional state store (Redux/MVI).
    

## Structure

```sql
+--------------------+       +------------------+
User ---> |        View        | <---> |     Presenter    | <---> Router (navigation)
          +--------------------+       +------------------+
                    |                           ^
                    | displays ViewModel        |
                    v                           |
               +---------+     uses/reports     |
               | Entity  | <----------------> Interactor (business/use-case logic)
               +---------+
```

-   **View** owns widgets and user input; **no business logic**.
    
-   **Presenter** formats data for the View and reacts to user intents.
    
-   **Interactor** contains application/business rules and talks to data sources.
    
-   **Entity** holds domain data structures.
    
-   **Router** performs navigation and wiring of the module.
    

## Participants

-   **View (Activity/Fragment/ViewController):** Renders state; forwards user intents to Presenter.
    
-   **Presenter:** Binds View ↔ Interactor; converts Entities → ViewModels; tells Router to navigate.
    
-   **Interactor:** Executes use cases; talks to repositories/services; returns Entities or results to Presenter.
    
-   **Entity:** Domain models/value objects.
    
-   **Router (a.k.a. Wireframe):** Navigation and module assembly (creates/wires VIPER stack).
    

## Collaboration

1.  **Router** builds the module and injects dependencies.
    
2.  **View** forwards events (e.g., refresh, select item) to **Presenter**.
    
3.  **Presenter** asks **Interactor** to execute a use case.
    
4.  **Interactor** fetches/computes data (via repositories), returns **Entities** (or errors).
    
5.  **Presenter** maps Entities → **ViewModels** and calls **View** to render.
    
6.  When navigation is required, **Presenter** asks **Router** to route.
    

## Consequences

**Benefits**

-   **Testability:** Presenter and Interactor are plain classes.
    
-   **Separation of concerns:** UI, navigation, and application logic are isolated.
    
-   **Scalability:** Teams own features; contracts are explicit.
    

**Liabilities**

-   **Boilerplate** (interfaces + mappers).
    
-   **Onboarding cost** for newcomers.
    
-   Can devolve into **anemic layers** if responsibilities aren’t enforced.
    

## Implementation

1.  **Define contracts** (`View`, `Presenter`, `Interactor`, `Router`) per feature.
    
2.  **Keep View passive**; only render states and forward events.
    
3.  **Put business rules in Interactor**; keep it UI-agnostic.
    
4.  **Presenter** becomes the single place that formats UI models and coordinates navigation via the Router.
    
5.  **Router** also acts as **module assembler**: construct and wire the VIPER stack.
    
6.  **Testing:**
    
    -   Unit-test Interactor with fake repositories.
        
    -   Unit-test Presenter with fake View/Interactor/Router.
        
    -   Navigation rules are tested by asserting Router calls.
        

---

## Sample Code (Java, Android-friendly VIPER)

> Feature: **Articles List** screen
> 
> -   User opens the list, sees titles, taps an item → navigates to details.
>     
> -   Fake repository returns data; threading kept simple with a single executor.
>     

### Contracts

```java
// viper/articles/ArticlesContract.java
package viper.articles;

import java.util.List;

public interface ArticlesContract {

  interface View {
    void showLoading(boolean loading);
    void showArticles(List<ArticleVM> items);
    void showError(String message);
  }

  interface Presenter {
    void attach(View view);
    void detach();
    void onViewReady();
    void onRefresh();
    void onArticleSelected(String id);
  }

  interface Interactor {
    void loadArticles(Callback cb);
    interface Callback {
      void onSuccess(java.util.List<Article> articles);
      void onError(String message);
    }
  }

  interface Router {
    void goToArticleDetail(String articleId);
  }

  // UI model
  final class ArticleVM {
    public final String id; public final String title;
    public ArticleVM(String id, String title){ this.id=id; this.title=title; }
    @Override public String toString() { return title; }
  }

  // Domain entity
  final class Article {
    public final String id; public final String title;
    public Article(String id, String title){ this.id=id; this.title=title; }
  }
}
```

### Interactor + Repository

```java
// viper/articles/ArticlesRepository.java
package viper.articles;

import java.util.Arrays;
import java.util.List;

class ArticlesRepository {
  List<ArticlesContract.Article> fetchAll() throws Exception {
    Thread.sleep(300); // emulate IO
    return Arrays.asList(
        new ArticlesContract.Article("1", "Clean Architecture on Mobile"),
        new ArticlesContract.Article("2", "VIPER Explained Clearly"),
        new ArticlesContract.Article("3", "Caching & Offline-First Patterns")
    );
  }
}
```

```java
// viper/articles/ArticlesInteractor.java
package viper.articles;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

class ArticlesInteractor implements ArticlesContract.Interactor {
  private final ArticlesRepository repo;
  private final ExecutorService io = Executors.newSingleThreadExecutor();

  ArticlesInteractor(ArticlesRepository repo) { this.repo = repo; }

  @Override public void loadArticles(Callback cb) {
    io.submit(() -> {
      try {
        cb.onSuccess(repo.fetchAll());
      } catch (Exception e) {
        cb.onError("Failed to load articles");
      }
    });
  }
}
```

### Presenter

```java
// viper/articles/ArticlesPresenter.java
package viper.articles;

import java.util.List;
import java.util.stream.Collectors;

class ArticlesPresenter implements ArticlesContract.Presenter, ArticlesContract.Interactor.Callback {

  private final ArticlesContract.Interactor interactor;
  private final ArticlesContract.Router router;
  private ArticlesContract.View view;

  ArticlesPresenter(ArticlesContract.Interactor interactor, ArticlesContract.Router router) {
    this.interactor = interactor; this.router = router;
  }

  @Override public void attach(ArticlesContract.View view) { this.view = view; }
  @Override public void detach() { this.view = null; }

  @Override public void onViewReady() {
    if (view != null) view.showLoading(true);
    interactor.loadArticles(this);
  }

  @Override public void onRefresh() { onViewReady(); }

  @Override public void onArticleSelected(String id) { router.goToArticleDetail(id); }

  // Interactor callbacks
  @Override public void onSuccess(List<ArticlesContract.Article> articles) {
    if (view == null) return;
    List<ArticlesContract.ArticleVM> vms = articles.stream()
        .map(a -> new ArticlesContract.ArticleVM(a.id, a.title))
        .collect(Collectors.toList());
    view.showLoading(false);
    view.showArticles(vms);
  }

  @Override public void onError(String message) {
    if (view == null) return;
    view.showLoading(false);
    view.showError(message);
  }
}
```

### Router (navigation & module assembly)

```java
// viper/articles/ArticlesRouter.java
package viper.articles;

import android.content.Context;
import android.content.Intent;

class ArticlesRouter implements ArticlesContract.Router {
  private final Context appContext;
  ArticlesRouter(Context context) { this.appContext = context.getApplicationContext(); }

  @Override public void goToArticleDetail(String articleId) {
    Intent i = new Intent(appContext, ArticleDetailActivity.class);
    i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
    i.putExtra("id", articleId);
    appContext.startActivity(i);
  }

  // Assembler: build/wire the VIPER stack for the feature
  static ArticlesContract.Presenter build(Context context, ArticlesContract.View view) {
    ArticlesRepository repo = new ArticlesRepository();
    ArticlesInteractor interactor = new ArticlesInteractor(repo);
    ArticlesRouter router = new ArticlesRouter(context);
    ArticlesPresenter presenter = new ArticlesPresenter(interactor, router);
    presenter.attach(view);
    return presenter;
  }
}
```

### View (Activity)

```java
// viper/articles/ArticlesActivity.java
package viper.articles;

import android.os.Bundle;
import android.view.View;
import android.widget.*;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;

import java.util.ArrayList;
import java.util.List;

public class ArticlesActivity extends AppCompatActivity implements ArticlesContract.View {

  private ProgressBar progress;
  private ListView list;
  private TextView error;
  private Button refresh;

  private ArticlesContract.Presenter presenter;
  private ArrayAdapter<String> adapter;
  private List<ArticlesContract.ArticleVM> current = new ArrayList<>();

  @Override protected void onCreate(@Nullable Bundle savedInstanceState) {
    super.onCreate(savedInstanceState);

    LinearLayout root = new LinearLayout(this);
    root.setOrientation(LinearLayout.VERTICAL);
    progress = new ProgressBar(this);
    list = new ListView(this);
    error = new TextView(this); error.setTextColor(0xFFB00020);
    refresh = new Button(this); refresh.setText("Refresh");
    root.addView(progress); root.addView(error); root.addView(list); root.addView(refresh);
    setContentView(root);

    adapter = new ArrayAdapter<>(this, android.R.layout.simple_list_item_1, new ArrayList<>());
    list.setAdapter(adapter);

    presenter = ArticlesRouter.build(getApplicationContext(), this);

    list.setOnItemClickListener((parent, view, position, id) ->
        presenter.onArticleSelected(current.get(position).id)
    );
    refresh.setOnClickListener(v -> presenter.onRefresh());
  }

  @Override protected void onStart() {
    super.onStart();
    presenter.onViewReady();
  }

  @Override protected void onDestroy() {
    super.onDestroy();
    presenter.detach();
  }

  // ---- View methods ----
  @Override public void showLoading(boolean loading) {
    progress.setVisibility(loading ? View.VISIBLE : View.GONE);
    refresh.setEnabled(!loading);
  }

  @Override public void showArticles(List<ArticlesContract.ArticleVM> items) {
    current = items;
    error.setText("");
    adapter.clear();
    for (var vm : items) adapter.add(vm.title);
    adapter.notifyDataSetChanged();
  }

  @Override public void showError(String message) {
    error.setText(message);
  }
}
```

```java
// viper/articles/ArticleDetailActivity.java
package viper.articles;

import android.os.Bundle;
import android.widget.TextView;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;

public class ArticleDetailActivity extends AppCompatActivity {
  @Override protected void onCreate(@Nullable Bundle savedInstanceState) {
    super.onCreate(savedInstanceState);
    String id = getIntent().getStringExtra("id");
    TextView tv = new TextView(this);
    tv.setText("Detail for article id = " + id);
    setContentView(tv);
  }
}
```

**Notes**

-   The **View** only renders and forwards intents.
    
-   **Presenter** coordinates; **Interactor** does the work; **Router** handles navigation and assembly.
    
-   Swap `ArticlesRepository` with a real API/DB without touching View/Presenter.
    

---

## Known Uses

-   **iOS**: VIPER is popular in large UIKit codebases; also **Clean Swift (VIP)** variant.
    
-   **Android**: Less common but used in enterprise apps seeking strict separation (often combined with Coordinators/DI).
    
-   **VIPER-inspired frameworks**: Uber’s **RIBs** (Router-Interactor-Builder), point-of-sale and banking apps with strong modularity.
    

## Related Patterns

-   **MVP / MVVM:** Alternative presentation patterns; VIPER adds explicit Router and Interactor roles.
    
-   **Clean Architecture (Mobile):** VIPER aligns with use-case oriented interactors and clear boundaries.
    
-   **Coordinator:** Complements VIPER by managing cross-feature navigation.
    
-   **Repository:** Typically consumed by Interactors.
    
-   **Redux/MVI:** Different approach focusing on a single immutable state and reducers; can be used inside Interactor.
    

---

### Practical Guidance

-   Start VIPER where **navigation and business rules are complex**; use lighter patterns elsewhere.
    
-   Keep **Presenter thin**—formatting and orchestration only; **Interactor** owns application logic.
    
-   Let **Router assemble** dependencies (or delegate to DI).
    
-   Favor **immutable view models** from Presenter to View.
    
-   Make **Interactor** return **Entities**/**Results**; do not leak DTOs/Room entities.
    
-   Write **unit tests first** for Presenter and Interactor; stub the others.

