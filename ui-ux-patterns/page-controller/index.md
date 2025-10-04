# Page Controller — UI/UX Pattern

## Pattern Name and Classification

**Name:** Page Controller  
**Category:** UI/UX · Web Application Architecture · Request Handling · Presentation

## Intent

Handle a **single page (or closely related set of views)** with a dedicated controller that processes the request, coordinates application logic, and selects the view to render—keeping logic localized to that page and reducing global coupling.

## Also Known As

Page Action · Screen Controller · Action Controller (per-page)

## Motivation (Forces)

-   **Locality of change:** Changes to one page shouldn’t ripple across the whole app.
    
-   **Simplicity:** A slim controller per page is easier to read, test, and deploy than a monolithic handler.
    
-   **Team ownership:** Pages can be owned by different squads with clear boundaries.
    
-   **Separation of concerns:** Page orchestration belongs in the page controller; domain logic belongs in services/models.
    
-   **Trade-offs:** Too many controllers can fragment cross-cutting concerns; duplicated logic must be factored out into filters/interceptors or a Front Controller.
    

## Applicability

Use Page Controller when:

-   Each **URL/page** has distinct behavior and a small, well-defined set of actions (GET show, POST submit).
    
-   You want **clear ownership** per screen (e.g., checkout page, profile page).
    
-   Frameworks map routes → controllers naturally (e.g., Spring MVC, Rails, Laravel).
    

Avoid or adapt when:

-   Many cross-cutting concerns need centralization (consider **Front Controller** + interceptors).
    
-   Highly dynamic routing or microfrontends require composition (consider **Front Controller** or **Client-Side Composition**).
    
-   You have dozens of tiny actions differing only by parameters—prefer a cohesive resource/controller.
    

## Structure

-   **Router:** Maps a page path to its specific controller.
    
-   **Page Controller:** Orchestrates request for that page; performs input binding/validation; delegates to services; selects view.
    
-   **Service/Domain Layer:** Business logic and persistence.
    
-   **View/Template:** Renders page-specific UI.
    
-   **Cross-Cutting:** Filters/interceptors for auth, logging, i18n, CSRF, etc.
    

```pgsql
Client → Router → PageController("/checkout") → Services/Model → View Resolver → HTML/JSON
```

## Participants

-   **User/Client:** Triggers HTTP requests.
    
-   **Router:** Chooses the correct page controller by URL/method.
    
-   **Page Controller:** The per-page coordinator.
    
-   **Services/Repositories:** Domain logic, data access.
    
-   **View Resolver/Template Engine:** Produces the final representation.
    

## Collaboration

1.  Router dispatches `/profile` to `ProfileController`.
    
2.  Controller binds params, validates, calls `UserService`.
    
3.  Service returns DTO/domain results; controller selects view `profile/view`.
    
4.  View renders; filters/interceptors add headers, metrics, etc.
    

## Consequences

**Benefits**

-   High cohesion and readability; each page has a single home for orchestration.
    
-   Easy testing (controller slice tests).
    
-   Clear team boundaries and deployment independence with modular controllers.
    

**Liabilities**

-   Risk of **duplication** across controllers (factor out shared helpers/middlewares).
    
-   Cross-cutting concerns must be handled elsewhere (filters, aspects).
    
-   Can devolve into **fat controllers** if domain logic isn’t pushed into services.
    

## Implementation

**Guidelines**

1.  **One controller per page/resource** with a small set of actions (GET render, POST submit).
    
2.  **Keep controllers thin**—delegate to services; return view names or DTOs.
    
3.  **Use DTO/ViewModels**—don’t bind web forms directly to domain entities.
    
4.  **Validate inputs** with Bean Validation; handle errors with a consistent strategy.
    
5.  **Handle cross-cutting** via interceptors/filters (security, logging, i18n).
    
6.  **Consistent naming:** `XxxController`, views under `/templates/xxx/*.html`.
    
7.  **Testing:** Write controller slice tests (mock MVC) and service unit tests.
    
8.  **Versioning/routing:** Keep route definitions explicit; avoid reflection magic that hides intent.
    

**Anti-Patterns**

-   Putting SQL or complex domain rules in the controller.
    
-   Sharing state between controllers via static fields.
    
-   Overloading one controller with unrelated pages.
    

---

## Sample Code (Java — Spring Boot MVC “Profile Page”)

**Goal:** A dedicated `ProfileController` handles `/profile` view (GET) and profile updates (POST). The controller stays thin; business logic is inside `UserService`.

```java
// build.gradle (relevant deps)
// implementation 'org.springframework.boot:spring-boot-starter-web'
// implementation 'org.springframework.boot:spring-boot-starter-thymeleaf'
// implementation 'org.springframework.boot:spring-boot-starter-validation'
// implementation 'org.springframework.boot:spring-boot-starter-data-jpa'
// runtimeOnly 'com.h2database:h2'
```

```java
// src/main/java/com/example/page/domain/User.java
package com.example.page.domain;

import jakarta.persistence.*;
import java.util.Objects;

@Entity
@Table(name = "users")
public class User {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable=false, length=80)  private String fullName;
    @Column(nullable=false, unique=true) private String email;
    @Column(length=160)                  private String bio;

    protected User() {}
    public User(String fullName, String email) { this.fullName = fullName; this.email = email; }

    public Long getId(){ return id; }
    public String getFullName(){ return fullName; }
    public String getEmail(){ return email; }
    public String getBio(){ return bio; }

    public void rename(String fullName) {
        if (fullName == null || fullName.isBlank()) throw new IllegalArgumentException("name.required");
        if (fullName.length() > 80) throw new IllegalArgumentException("name.tooLong");
        this.fullName = fullName;
    }
    public void changeBio(String bio) { this.bio = bio == null ? "" : bio.strip(); }

    @Override public boolean equals(Object o){ return o instanceof User u && Objects.equals(id,u.id); }
    @Override public int hashCode(){ return Objects.hash(id); }
}
```

```java
// src/main/java/com/example/page/domain/UserRepository.java
package com.example.page.domain;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface UserRepository extends JpaRepository<User, Long> {
    Optional<User> findByEmail(String email);
}
```

```java
// src/main/java/com/example/page/domain/UserService.java
package com.example.page.domain;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@Transactional
public class UserService {
    private final UserRepository repo;
    public UserService(UserRepository repo) { this.repo = repo; }

    @Transactional(readOnly = true)
    public User byEmailOrThrow(String email) {
        return repo.findByEmail(email).orElseThrow(() -> new IllegalArgumentException("user.notFound"));
    }

    public User updateProfile(String email, String fullName, String bio) {
        User u = byEmailOrThrow(email);
        u.rename(fullName);
        u.changeBio(bio);
        return u; // JPA dirty-checking persists changes
    }
}
```

```java
// src/main/java/com/example/page/web/ProfileForm.java
package com.example.page.web;

import jakarta.validation.constraints.*;

public class ProfileForm {
    @NotBlank @Size(max = 80)
    private String fullName;

    @Email @NotBlank
    private String email;

    @Size(max = 160)
    private String bio;

    public String getFullName(){ return fullName; }
    public void setFullName(String fullName){ this.fullName = fullName; }
    public String getEmail(){ return email; }
    public void setEmail(String email){ this.email = email; }
    public String getBio(){ return bio; }
    public void setBio(String bio){ this.bio = bio; }
}
```

```java
// src/main/java/com/example/page/web/ProfileController.java
package com.example.page.web;

import com.example.page.domain.User;
import com.example.page.domain.UserService;
import jakarta.validation.Valid;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.validation.BindingResult;
import org.springframework.web.bind.annotation.*;

@Controller
@RequestMapping("/profile")
public class ProfileController {

    private final UserService users;

    public ProfileController(UserService users) { this.users = users; }

    // GET /profile?email=jane@company.com
    @GetMapping
    public String show(@RequestParam String email, Model model, @ModelAttribute("form") ProfileForm form) {
        User u = users.byEmailOrThrow(email);
        form.setEmail(u.getEmail());
        form.setFullName(u.getFullName());
        form.setBio(u.getBio());
        model.addAttribute("user", u);
        return "profile/view";
    }

    // POST /profile
    @PostMapping
    public String update(@Valid @ModelAttribute("form") ProfileForm form,
                         BindingResult br,
                         Model model) {
        if (br.hasErrors()) {
            model.addAttribute("user", users.byEmailOrThrow(form.getEmail()));
            return "profile/view";
        }
        User updated = users.updateProfile(form.getEmail(), form.getFullName(), form.getBio());
        model.addAttribute("user", updated);
        model.addAttribute("saved", true);
        return "profile/view";
    }
}
```

**View (Thymeleaf) — `src/main/resources/templates/profile/view.html`**

```html
<!doctype html>
<html xmlns:th="http://www.thymeleaf.org">
<head><meta charset="utf-8"><title>Profile</title></head>
<body>
  <h1 th:text="${user.fullName}">Profile</h1>

  <div th:if="${saved}" style="color: green;">Saved.</div>

  <form th:action="@{/profile}" method="post" th:object="${form}">
    <label>Full name
      <input type="text" th:field="*{fullName}" />
      <span style="color:red" th:errors="*{fullName}"></span>
    </label><br/>

    <label>Email (read-only)
      <input type="email" th:field="*{email}" readonly />
      <span style="color:red" th:errors="*{email}"></span>
    </label><br/>

    <label>Bio
      <textarea th:field="*{bio}" rows="3"></textarea>
      <span style="color:red" th:errors="*{bio}"></span>
    </label><br/>

    <button type="submit">Save</button>
  </form>
</body>
</html>
```

**Why this is Page Controller**

-   The **URL `/profile`** is handled by a single **`ProfileController`** responsible for that page’s display and submission.
    
-   It delegates business logic to `UserService` and only orchestrates request/response for this page.
    

---

## Known Uses

-   **Spring MVC:** One controller per page/feature (e.g., `CheckoutController`, `ProfileController`).
    
-   **Ruby on Rails / Laravel / Play:** Route per action mapped to a page-centric controller.
    
-   **Classic JSP/Servlet apps:** One servlet per page (e.g., `OrderPageServlet`).
    
-   **Server-side rendered CMS modules:** Each module exposes a page controller to render/edit content.
    

## Related Patterns

-   **Front Controller:** Central entry point; typically routes to page controllers and applies cross-cutting concerns.
    
-   **Application Controller / Command:** Encapsulates action-level logic that page controllers can invoke.
    
-   **View Helper / Template View:** Keeps templates simple and reusable.
    
-   **Model–View–Controller (MVC):** Page Controller is a common controller role within MVC.
    
-   **Intercepting Filter:** Auth/logging/i18n before reaching the page controller.

