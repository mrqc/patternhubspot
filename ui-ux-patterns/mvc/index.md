# MVC — UI/UX Pattern

## Pattern Name and Classification

**Name:** Model–View–Controller (MVC)  
**Category:** UI/UX · Presentation Architecture · Separation of Concerns

## Intent

Separate **domain state** (Model), **rendering** (View), and **input/control flow** (Controller) so that each concern evolves independently, enabling testability, parallel work, and reuse of domain logic across multiple UIs.

## Also Known As

Model–View–Presenter family (historical kin) · Application MVC · Web MVC · Passive View (variation)

## Motivation (Forces)

-   **Separation of concerns:** Keep business rules out of templates and event-handling out of models.
    
-   **Testability:** Models and controllers become unit-test friendly; views can be exercised via component tests.
    
-   **Multiple views:** Same model can drive HTML, mobile, CLI, or APIs.
    
-   **Parallel development:** Designers iterate on views while engineers evolve models/controllers.
    
-   **Complexity management:** Clear boundaries reduce tangling and regressions.
    
-   **Trade-offs:** Strict separation adds indirection; poorly enforced boundaries drift into “Massive Controller” or “Fat Model.”
    

## Applicability

Use MVC when:

-   You build interactive applications where UI changes frequently while core domain rules stay stable.
    
-   Multiple presentations (web, API, mobile) should share the same domain model.
    
-   You need maintainable, testable codebases with clear module ownership.
    

Avoid or adapt when:

-   The app is tiny (the added layers outweigh benefits).
    
-   Highly stateful, real-time UIs may benefit more from **MVU/MVI** or unidirectional dataflow (Flux/Redux).
    
-   Serverless endpoints with thin presentation needs may be simpler as “Controller + DTO” only.
    

## Structure

-   **Model:** Domain state + business invariants; not tied to UI widgets.
    
-   **View:** Pure presentation; renders model data; minimal logic (formatting only).
    
-   **Controller:** Translates user input into model operations and selects a view to render.
    

```pgsql
User Input → Controller → (invokes) Model → (provides data to) View → Output to User
                          ↑-----------------------------------------------↓
                                   View reads model state
```

## Participants

-   **Model:** Entities, value objects, services, repositories.
    
-   **View:** Templates (Thymeleaf/JSP), components, or serializers.
    
-   **Controller:** Routes, parameter binding, validation, application flow.
    
-   **Router (web):** Maps URLs to controllers (often framework-provided).
    
-   **Formatter/Mapper:** Adapters between domain objects and view models/DTOs.
    

## Collaboration

1.  Router dispatches a request to a **Controller**.
    
2.  Controller validates input, calls **Model** services/repositories.
    
3.  Model updates state/queries data and returns results.
    
4.  Controller selects **View** and supplies a view model (DTO).
    
5.  View renders output (HTML/JSON) and returns it to client.
    

## Consequences

**Benefits**

-   Cleaner codebases, easier testing and refactoring.
    
-   Designers and developers can work independently.
    
-   Domain logic reusable across multiple UIs.
    

**Liabilities**

-   Boilerplate and extra layers for small apps.
    
-   Risk of **anemic models** (logic pushed to controllers) or **god controllers**.
    
-   Leaky abstractions when views directly reach into domain types.
    

## Implementation

**Guidelines**

1.  **Keep controllers thin:** Orchestrate, validate, delegate—no business rules.
    
2.  **Keep views dumb:** Formatting and layout only; no persistence or domain branching.
    
3.  **Make models rich:** Encapsulate invariants and operations close to data.
    
4.  **Use DTOs/view models:** Don’t couple templates to domain entities.
    
5.  **Centralize cross-cutting concerns:** Auth, i18n, error handling via filters/interceptors.
    
6.  **Testing strategy:** Unit-test models, slice-test controllers, snapshot or component-test views.
    
7.  **Validation:** Bean Validation at DTO boundaries; business rules inside the model/service.
    

---

## Sample Code (Java — Spring Boot Web MVC)

Minimal CRUD slice for a “Task” using **Model (domain + service)**, **Controller**, and **View** (Thymeleaf).  
*(Templates shown conceptually; any server-side view engine works.)*

```java
// build.gradle (relevant deps)
// implementation 'org.springframework.boot:spring-boot-starter-web'
// implementation 'org.springframework.boot:spring-boot-starter-thymeleaf'
// implementation 'org.springframework.boot:spring-boot-starter-validation'
// implementation 'org.springframework.boot:spring-boot-starter-data-jpa'
// runtimeOnly 'com.h2database:h2'
```

```java
// src/main/java/com/example/mvc/domain/Task.java
package com.example.mvc.domain;

import jakarta.persistence.*;
import java.time.Instant;
import java.util.Objects;

@Entity
public class Task {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable=false, length=200)
    private String title;

    @Column(nullable=false)
    private boolean done = false;

    @Column(nullable=false, updatable=false)
    private Instant createdAt = Instant.now();

    protected Task() {}
    public Task(String title) { setTitle(title); }

    // Domain behavior
    public void markDone() { this.done = true; }
    public void rename(String newTitle) {
        if (newTitle == null || newTitle.isBlank())
            throw new IllegalArgumentException("title.required");
        if (newTitle.length() > 200)
            throw new IllegalArgumentException("title.tooLong");
        this.title = newTitle;
    }

    private void setTitle(String t) { rename(t); }

    // getters
    public Long getId() { return id; }
    public String getTitle() { return title; }
    public boolean isDone() { return done; }
    public Instant getCreatedAt() { return createdAt; }

    @Override public boolean equals(Object o){ return o instanceof Task t && Objects.equals(id,t.id); }
    @Override public int hashCode(){ return Objects.hashCode(id); }
}
```

```java
// src/main/java/com/example/mvc/domain/TaskRepository.java
package com.example.mvc.domain;

import org.springframework.data.jpa.repository.JpaRepository;

public interface TaskRepository extends JpaRepository<Task, Long> {}
```

```java
// src/main/java/com/example/mvc/domain/TaskService.java
package com.example.mvc.domain;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
@Transactional
public class TaskService {
    private final TaskRepository repo;
    public TaskService(TaskRepository repo) { this.repo = repo; }

    public Task create(String title) { return repo.save(new Task(title)); }
    @Transactional(readOnly = true)
    public List<Task> list() { return repo.findAll(); }
    public void markDone(long id) {
        Task t = repo.findById(id).orElseThrow();
        t.markDone();
    }
    public void rename(long id, String title) {
        Task t = repo.findById(id).orElseThrow();
        t.rename(title);
    }
    public void delete(long id) { repo.deleteById(id); }
}
```

```java
// src/main/java/com/example/mvc/web/TaskForm.java
package com.example.mvc.web;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

public class TaskForm {
    @NotBlank @Size(max = 200)
    private String title;

    public String getTitle(){ return title; }
    public void setTitle(String title){ this.title = title; }
}
```

```java
// src/main/java/com/example/mvc/web/TaskController.java
package com.example.mvc.web;

import com.example.mvc.domain.TaskService;
import jakarta.validation.Valid;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.*;

@Controller
@RequestMapping("/tasks")
public class TaskController {
    private final TaskService service;
    public TaskController(TaskService service){ this.service = service; }

    @GetMapping
    public String list(Model model, @ModelAttribute("form") TaskForm form) {
        model.addAttribute("tasks", service.list());
        return "tasks/list"; // View name resolved to a template
    }

    @PostMapping
    public String create(@Valid @ModelAttribute("form") TaskForm form) {
        service.create(form.getTitle());
        return "redirect:/tasks";
    }

    @PostMapping("/{id}/done")
    public String done(@PathVariable long id) {
        service.markDone(id);
        return "redirect:/tasks";
    }

    @PostMapping("/{id}/rename")
    public String rename(@PathVariable long id, @RequestParam String title) {
        service.rename(id, title);
        return "redirect:/tasks";
    }

    @PostMapping("/{id}/delete")
    public String delete(@PathVariable long id) {
        service.delete(id);
        return "redirect:/tasks";
    }
}
```

**View (Thymeleaf concept) — `src/main/resources/templates/tasks/list.html`**

```html
<!doctype html>
<html xmlns:th="http://www.thymeleaf.org">
<head><meta charset="utf-8"><title>Tasks</title></head>
<body>
  <h1>Tasks</h1>

  <form th:action="@{/tasks}" method="post">
    <input type="text" name="title" th:value="${form.title}" placeholder="New task"/>
    <button type="submit">Add</button>
  </form>

  <ul>
    <li th:each="t : ${tasks}">
      <span th:text="${t.title}">Title</span>
      <span th:if="${t.done}">(done)</span>
      <form th:action="@{|/tasks/${t.id}/done|}" method="post" style="display:inline">
        <button type="submit">Done</button>
      </form>
      <form th:action="@{|/tasks/${t.id}/delete|}" method="post" style="display:inline">
        <button type="submit">Delete</button>
      </form>
    </li>
  </ul>
</body>
</html>
```

**Notes**

-   **Model:** `Task`, `TaskService` encapsulate behavior and persistence.
    
-   **View:** `list.html` renders; no business rules.
    
-   **Controller:** `TaskController` handles HTTP, binds DTOs, delegates to services, returns view names.
    
-   Replace Thymeleaf with JSP/Freemarker or return JSON (`@RestController`) if needed—MVC still applies.
    

---

## Known Uses

-   **Spring MVC / Spring Boot `@Controller` + `ModelAndView`**
    
-   **ASP.NET MVC, Ruby on Rails, Django (MTV is MVC-like)**
    
-   **JavaFX/Swing apps structured with MVC on the client side**
    
-   **iOS/macOS Cocoa MVC (historical)**
    

## Related Patterns

-   **Front Controller:** Central entry that routes requests to MVC controllers.
    
-   **View Helper / Template View:** Keeps views thin and reusable.
    
-   **MVVM / MVP / MVI:** Variants optimizing binding, testability, or unidirectional flow.
    
-   **Domain Model / Hexagonal Architecture:** Deepens model independence from frameworks.
    
-   **DTO / Presenter:** Adapters to decouple views from domain entities.

