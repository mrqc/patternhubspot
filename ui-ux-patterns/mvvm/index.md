# MVVM — UI/UX Pattern

## Pattern Name and Classification

**Name:** Model–View–ViewModel (MVVM)  
**Category:** UI/UX · Presentation Architecture · Data Binding · Separation of Concerns

## Intent

Isolate UI rendering from application logic by introducing a **ViewModel** that exposes observable state and commands for a **View** to bind to, while keeping **Model** (domain) independent. MVVM enables declarative UIs, testable presentation logic, and straightforward state synchronization through bindings.

## Also Known As

Presentation Model (closely related) · View Model · Bindable Presenter

## Motivation (Forces)

-   **Declarative UIs & bindings:** Modern toolkits (JavaFX, Android, WPF) support property bindings that automatically sync UI with state.
    
-   **Testability:** Presentation logic lives in the ViewModel (POJOs with observables), enabling unit tests without a UI toolkit.
    
-   **Separation of concerns:** Views define layout/styling; Models encapsulate domain rules; ViewModels adapt Models to View-friendly shape.
    
-   **State orchestration:** Loading/empty/error states are centralized in the ViewModel.
    
-   **Trade-offs:** More moving parts (VMs, converters). Over-binding can hide control flow; naïve two-way binding can cause update loops.
    

## Applicability

Use MVVM when:

-   The UI framework supports **bindings/observables** (JavaFX, Android Jetpack, WPF).
    
-   You need **testable** presentation logic independent of rendering.
    
-   The same domain model should power multiple UIs (desktop/mobile/web) via different ViewModels.
    
-   Complex screens need **explicit view state** (loading, empty, error, content).
    

Avoid or adapt when:

-   Minimal UIs where MVC or MVP is simpler.
    
-   Highly event-driven apps better served by unidirectional flows (Flux/Redux/MVI).
    
-   Tooling lacks bindings—then MVP may be more straightforward.
    

## Structure

-   **Model:** Domain entities/services/repositories; no UI concerns.
    
-   **ViewModel:** Exposes observable properties (e.g., `StringProperty`, `BooleanProperty`, `ObservableList`) and commands; transforms domain data to View-ready state.
    
-   **View:** Declarative layout; binds to ViewModel properties/commands. No domain logic.
    

```sql
User ↔ View (binds) ↔ ViewModel ↔ Model (services/repos)
                ↑             ↑
            bindings       method calls / async results
```

## Participants

-   **User:** Interacts with UI controls.
    
-   **View:** JavaFX/Android component tree, FXML/Layouts; subscribes via binding.
    
-   **ViewModel:** Pure Java; holds observable state + command methods; orchestrates async work.
    
-   **Model/Service/Repository:** Enforces business rules, persistence, and I/O.
    
-   **Binder/Converter:** (Optional) Adapts types (e.g., `Instant → String`).
    

## Collaboration

1.  View creates/obtains the ViewModel and binds its UI controls to the VM’s properties.
    
2.  User actions trigger **commands** on the ViewModel.
    
3.  ViewModel validates input, calls Model services, updates observable state.
    
4.  Bindings propagate state changes back to the View automatically.
    
5.  Tests target the ViewModel in isolation.
    

## Consequences

**Benefits**

-   Clear separation and high testability of UI behavior.
    
-   Less glue code due to data binding.
    
-   Domain independence; Views are replaceable.
    
-   Easy to represent complex screen states.
    

**Liabilities**

-   Risk of **Massive ViewModel** if business logic leaks in—keep rules in the Model.
    
-   Hidden dependencies through bindings make debugging harder if not instrumented.
    
-   Overuse of two-way binding can introduce cycles or unexpected writes.
    

## Implementation

**Guidelines**

1.  **Keep View dumb:** No business branching; just layout and bindings.
    
2.  **Keep ViewModel pure:** No direct widget references; only observable properties and methods.
    
3.  **Explicit state model:** Represent `loading/empty/error/content` as booleans or a sealed state.
    
4.  **Asynchrony:** Offload I/O to executors; marshal results to UI thread (JavaFX Application Thread).
    
5.  **Mapping layer:** Map domain entities to View-friendly DTOs/Item-VMs.
    
6.  **One VM per screen/use case:** Limits size, clarifies responsibilities.
    
7.  **Testing:** Unit-test VM logic, including validation and state transitions.
    

---

## Sample Code (Java — JavaFX MVVM “Tasks”)

### Domain Model

```java
// src/main/java/com/example/mvvm/domain/Task.java
package com.example.mvvm.domain;

import java.time.Instant;
import java.util.Objects;

public class Task {
    private Long id;
    private String title;
    private boolean done;
    private Instant createdAt = Instant.now();

    public Task(Long id, String title) {
        rename(title);
        this.id = id;
    }

    public void markDone() { this.done = true; }
    public void rename(String t) {
        if (t == null || t.isBlank()) throw new IllegalArgumentException("title.required");
        if (t.length() > 200) throw new IllegalArgumentException("title.tooLong");
        this.title = t;
    }

    public Long getId() { return id; }
    public String getTitle() { return title; }
    public boolean isDone() { return done; }
    public Instant getCreatedAt() { return createdAt; }

    @Override public boolean equals(Object o){ return o instanceof Task t && Objects.equals(id,t.id); }
    @Override public int hashCode(){ return Objects.hashCode(id); }
}
```

```java
// src/main/java/com/example/mvvm/domain/TaskRepository.java
package com.example.mvvm.domain;

import java.util.*;
import java.util.concurrent.atomic.AtomicLong;

public class TaskRepository {
    private final Map<Long, Task> store = new LinkedHashMap<>();
    private final AtomicLong seq = new AtomicLong(1);

    public synchronized Task create(String title) {
        long id = seq.getAndIncrement();
        Task t = new Task(id, title);
        store.put(id, t);
        return t;
    }
    public synchronized List<Task> findAll() { return new ArrayList<>(store.values()); }
    public synchronized Optional<Task> findById(long id) { return Optional.ofNullable(store.get(id)); }
    public synchronized void delete(long id) { store.remove(id); }
}
```

```java
// src/main/java/com/example/mvvm/domain/TaskService.java
package com.example.mvvm.domain;

import java.util.List;

public class TaskService {
    private final TaskRepository repo;
    public TaskService(TaskRepository repo) { this.repo = repo; }

    public Task create(String title) { return repo.create(title); }
    public List<Task> list() { return repo.findAll(); }
    public void markDone(long id) { repo.findById(id).orElseThrow().markDone(); }
    public void rename(long id, String title) { repo.findById(id).orElseThrow().rename(title); }
    public void delete(long id) { repo.delete(id); }
}
```

### ViewModel Layer

```java
// src/main/java/com/example/mvvm/viewmodel/TaskItemViewModel.java
package com.example.mvvm.viewmodel;

import com.example.mvvm.domain.Task;
import javafx.beans.property.*;

public class TaskItemViewModel {
    private final LongProperty id = new SimpleLongProperty();
    private final StringProperty title = new SimpleStringProperty();
    private final BooleanProperty done = new SimpleBooleanProperty();

    public TaskItemViewModel(Task t) {
        id.set(t.getId());
        title.set(t.getTitle());
        done.set(t.isDone());
    }

    public long getId() { return id.get(); }
    public LongProperty idProperty() { return id; }
    public StringProperty titleProperty() { return title; }
    public BooleanProperty doneProperty() { return done; }

    public void updateFrom(Task t) {
        title.set(t.getTitle());
        done.set(t.isDone());
    }
}
```

```java
// src/main/java/com/example/mvvm/viewmodel/TaskListViewModel.java
package com.example.mvvm.viewmodel;

import com.example.mvvm.domain.Task;
import com.example.mvvm.domain.TaskService;
import javafx.application.Platform;
import javafx.beans.property.*;
import javafx.collections.*;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class TaskListViewModel {
    private final TaskService service;
    private final ExecutorService io = Executors.newSingleThreadExecutor();

    // Observable screen state
    private final ObservableList<TaskItemViewModel> items = FXCollections.observableArrayList();
    private final StringProperty newTitle = new SimpleStringProperty("");
    private final BooleanProperty loading = new SimpleBooleanProperty(false);
    private final StringProperty error = new SimpleStringProperty("");

    public TaskListViewModel(TaskService service) {
        this.service = service;
    }

    public ObservableList<TaskItemViewModel> getItems() { return items; }
    public StringProperty newTitleProperty() { return newTitle; }
    public BooleanProperty loadingProperty() { return loading; }
    public StringProperty errorProperty() { return error; }

    // Command: load tasks
    public void load() {
        setBusy(true, "");
        io.submit(() -> {
            try {
                var list = service.list();
                Platform.runLater(() -> {
                    items.setAll(list.stream().map(TaskItemViewModel::new).toList());
                    setBusy(false, "");
                });
            } catch (Exception ex) {
                Platform.runLater(() -> setBusy(false, "Failed to load tasks"));
            }
        });
    }

    // Command: add task
    public void addTask() {
        String title = newTitle.get();
        if (title == null || title.isBlank()) {
            error.set("Enter a title");
            return;
        }
        setBusy(true, "");
        io.submit(() -> {
            try {
                Task t = service.create(title);
                Platform.runLater(() -> {
                    items.add(new TaskItemViewModel(t));
                    newTitle.set("");
                    setBusy(false, "");
                });
            } catch (Exception ex) {
                Platform.runLater(() -> setBusy(false, "Could not add task"));
            }
        });
    }

    // Command: mark done
    public void markDone(long id) {
        setBusy(true, "");
        io.submit(() -> {
            try {
                service.markDone(id);
                var updated = service.list().stream().filter(t -> t.getId() == id).findFirst().orElseThrow();
                Platform.runLater(() -> {
                    items.stream().filter(vm -> vm.getId() == id).findFirst().ifPresent(vm -> vm.updateFrom(updated));
                    setBusy(false, "");
                });
            } catch (Exception ex) {
                Platform.runLater(() -> setBusy(false, "Could not mark as done"));
            }
        });
    }

    public void delete(long id) {
        setBusy(true, "");
        io.submit(() -> {
            try {
                service.delete(id);
                Platform.runLater(() -> {
                    items.removeIf(vm -> vm.getId() == id);
                    setBusy(false, "");
                });
            } catch (Exception ex) {
                Platform.runLater(() -> setBusy(false, "Could not delete task"));
            }
        });
    }

    private void setBusy(boolean isBusy, String err) {
        loading.set(isBusy);
        error.set(err);
    }
}
```

### View (JavaFX) — binds to ViewModel

```java
// src/main/java/com/example/mvvm/view/TaskListView.java
package com.example.mvvm.view;

import com.example.mvvm.domain.TaskRepository;
import com.example.mvvm.domain.TaskService;
import com.example.mvvm.viewmodel.TaskListViewModel;
import javafx.application.Application;
import javafx.geometry.Insets;
import javafx.scene.Scene;
import javafx.scene.control.*;
import javafx.scene.layout.*;
import javafx.stage.Stage;

public class TaskListView extends Application {
    @Override
    public void start(Stage stage) {
        var vm = new TaskListViewModel(new TaskService(new TaskRepository()));

        var titleField = new TextField();
        titleField.promptTextProperty().set("New task title");
        titleField.textProperty().bindBidirectional(vm.newTitleProperty());

        var addBtn = new Button("Add");
        addBtn.setOnAction(e -> vm.addTask());

        var list = new ListView<>(vm.getItems());
        list.setCellFactory(_ -> new ListCell<>() {
            private final Button doneBtn = new Button("Done");
            private final Button delBtn = new Button("Delete");
            private final HBox box = new HBox(8, doneBtn, delBtn);

            @Override protected void updateItem(com.example.mvvm.viewmodel.TaskItemViewModel item, boolean empty) {
                super.updateItem(item, empty);
                if (empty || item == null) {
                    setText(null); setGraphic(null);
                } else {
                    setText((item.doneProperty().get() ? "✓ " : "") + item.titleProperty().get());
                    doneBtn.setDisable(item.doneProperty().get());
                    doneBtn.setOnAction(e -> vm.markDone(item.getId()));
                    delBtn.setOnAction(e -> vm.delete(item.getId()));
                    setGraphic(box);
                }
            }
        });

        var errorLbl = new Label();
        errorLbl.textProperty().bind(vm.errorProperty());
        errorLbl.setStyle("-fx-text-fill: red;");

        var progress = new ProgressIndicator();
        progress.visibleProperty().bind(vm.loadingProperty());

        var root = new VBox(10,
                new HBox(8, titleField, addBtn),
                errorLbl,
                list,
                progress
        );
        root.setPadding(new Insets(12));
        stage.setScene(new Scene(root, 480, 400));
        stage.setTitle("Tasks — MVVM");
        stage.show();

        vm.load();
    }

    public static void main(String[] args) { launch(args); }
}
```

**Notes**

-   **ViewModel** exposes **observables** and **commands** (`load`, `addTask`, `markDone`, `delete`).
    
-   **View** only binds and wires event handlers to those commands; no domain logic.
    
-   **Model** remains toolkit-agnostic.
    
-   Asynchrony uses an Executor; UI updates are marshaled with `Platform.runLater`.
    

---

## Known Uses

-   **JavaFX**: Properties/bindings with MVVM-like structures.
    
-   **Android Jetpack**: `ViewModel`, `LiveData`/`StateFlow`, Data Binding/Compose.
    
-   **Microsoft WPF/UWP**: MVVM with bindings and `INotifyPropertyChanged`.
    
-   **Avalonia, Xamarin.Forms, MAUI**: Bindings + ViewModels across platforms.
    

## Related Patterns

-   **MVC**: Sibling; Controller mediates input; less binding-focused.
    
-   **MVP**: Presenter calls View via interface; MVVM prefers bindings and observable state.
    
-   **Presentation Model**: Conceptual precursor to MVVM.
    
-   **Flux/Redux/MVI**: Unidirectional state management; can power the Model or ViewModel state.
    
-   **Observer / Data Binding**: Underlying mechanism for View ↔ ViewModel synchronization.

