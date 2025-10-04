# Template View — UI/UX Pattern

## Pattern Name and Classification

**Name:** Template View  
**Category:** UI/UX · Presentation Layer · View Composition · Web MVC Pattern

## Intent

Define the structure of a page or view using a **template** with placeholders or directives that are populated with data at runtime. The pattern separates static layout (HTML, markup, template) from dynamic content (model data), enabling designers and developers to work independently and allowing reuse of common visual layouts across multiple views.

## Also Known As

View Template · Page Template · Server-Side Rendering Template · Markup Template

## Motivation (Forces)

-   **Separation of concerns:** Design (HTML/CSS) should remain independent of backend logic.
    
-   **Reusability:** Common headers, footers, and layouts should be shared across views.
    
-   **Maintainability:** Changes to visual structure shouldn’t require changes to application logic.
    
-   **Collaboration:** Designers can modify templates without touching Java code.
    
-   **Performance:** Server-side rendering with templates reduces client rendering time for static parts.
    
-   **Trade-offs:** Dynamic rendering can add server load; templating syntax can complicate debugging if abused.
    

## Applicability

Use Template View when:

-   Pages share consistent layout structures with varying data (e.g., dashboards, reports, detail views).
    
-   You need server-side rendering for SEO, first-load performance, or email templates.
    
-   Multiple roles (designers/developers) collaborate on UI development.
    
-   You aim to minimize code duplication in page layout.
    

Avoid or adapt when:

-   The app is purely client-side with dynamic rendering handled in the browser (then use client templating).
    
-   Templates become too complex or contain too much logic (then refactor into reusable partials or components).
    

## Structure

-   **Template:** Defines static layout and markup with placeholders for dynamic content.
    
-   **View Engine:** Processes the template by merging it with the model data to produce output.
    
-   **Controller:** Supplies the model data and selects which template to render.
    
-   **Model:** Holds domain data or DTOs to populate templates.
    

```pgsql
Request → Controller → Model + View Template → View Engine → Rendered HTML → Client
```

## Participants

-   **Template (View):** Static markup file containing placeholders.
    
-   **Controller:** Coordinates which view template to use and provides model data.
    
-   **Model:** Provides data objects to fill template placeholders.
    
-   **View Engine:** Parses template, injects data, and renders final output (e.g., Thymeleaf, JSP, Freemarker).
    
-   **Client:** Consumes rendered HTML or document output.
    

## Collaboration

1.  Controller handles a request and collects data into a **Model**.
    
2.  Controller selects a **Template View** (e.g., `user-profile.html`).
    
3.  View Engine merges template and data.
    
4.  The rendered output is sent to the browser or client.
    

## Consequences

**Benefits**

-   Clean separation between **presentation** and **logic**.
    
-   Designers can modify templates without breaking backend logic.
    
-   Layout reuse via template inheritance and fragments.
    
-   Suitable for SEO and server-rendered environments.
    
-   Simplifies localization and theming (different templates per locale/theme).
    

**Liabilities**

-   Templates can become too “smart” (logic leakage into view).
    
-   Tight coupling to template engine syntax (e.g., Thymeleaf, JSP).
    
-   Server-side rendering may add latency for highly interactive apps.
    
-   Harder to manage state transitions client-side compared to SPAs.
    

## Implementation

**Guidelines**

1.  **Define base templates:** Create master layouts (e.g., `layout.html`) with content placeholders.
    
2.  **Use fragments/partials:** For headers, navbars, and footers to avoid duplication.
    
3.  **Keep logic out of templates:** Use expression language only for simple rendering (e.g., conditionals, loops).
    
4.  **Pass minimal data models:** Avoid leaking domain entities directly into views.
    
5.  **Internationalization:** Use message resource bundles for localized text.
    
6.  **Test rendering:** Verify that all dynamic placeholders are resolved correctly.
    
7.  **Cache:** Cache rendered views for static or infrequently changing pages.
    

---

## Sample Code (Java — Spring Boot + Thymeleaf)

**Goal:** Render a user profile page using a shared layout and a dynamic template view.

```java
// build.gradle (relevant dependencies)
// implementation 'org.springframework.boot:spring-boot-starter-web'
// implementation 'org.springframework.boot:spring-boot-starter-thymeleaf'
```

```java
// src/main/java/com/example/templateview/model/User.java
package com.example.templateview.model;

public record User(Long id, String name, String email, String bio) {}
```

```java
// src/main/java/com/example/templateview/service/UserService.java
package com.example.templateview.service;

import com.example.templateview.model.User;
import org.springframework.stereotype.Service;

@Service
public class UserService {
    public User getUserById(Long id) {
        // Mock data for demo purposes
        return new User(id, "Alice Johnson", "alice@example.com", "Software Architect with 10 years of experience.");
    }
}
```

```java
// src/main/java/com/example/templateview/controller/UserController.java
package com.example.templateview.controller;

import com.example.templateview.service.UserService;
import com.example.templateview.model.User;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;

@Controller
public class UserController {
    private final UserService users;

    public UserController(UserService users) {
        this.users = users;
    }

    @GetMapping("/user/{id}")
    public String userProfile(@PathVariable Long id, Model model) {
        User user = users.getUserById(id);
        model.addAttribute("user", user);
        model.addAttribute("pageTitle", "User Profile - " + user.name());
        return "user-profile"; // Thymeleaf template name
    }
}
```

```html
<!-- src/main/resources/templates/layout.html -->
<!DOCTYPE html>
<html xmlns:th="http://www.thymeleaf.org" lang="en">
<head>
    <meta charset="UTF-8">
    <title th:text="${pageTitle}">Template View Example</title>
    <link rel="stylesheet" href="/css/style.css"/>
</head>
<body>
<header th:fragment="header">
    <h1>Company Portal</h1>
    <nav><a href="/">Home</a> | <a href="/users">Users</a></nav>
</header>

<main>
    <!-- Placeholder for child content -->
    <div th:insert="~{::content}"></div>
</main>

<footer th:fragment="footer">
    <p>&copy; 2025 Example Corp</p>
</footer>
</body>
</html>
```

```html
<!-- src/main/resources/templates/user-profile.html -->
<!DOCTYPE html>
<html xmlns:th="http://www.thymeleaf.org" lang="en"
      th:replace="layout :: layout">
<head>
    <title th:text="${pageTitle}">User Profile</title>
</head>
<body>
<div th:fragment="content">
    <section class="user-profile">
        <h2 th:text="${user.name}">Name</h2>
        <p><strong>Email:</strong> <span th:text="${user.email}">email</span></p>
        <p><strong>Bio:</strong> <span th:text="${user.bio}">bio</span></p>
    </section>
</div>
</body>
</html>
```

**Explanation:**

-   The **layout.html** defines a master template with header and footer.
    
-   The **user-profile.html** extends it by inserting its own `content` fragment.
    
-   The **controller** chooses the template and populates the model.
    
-   The **view engine (Thymeleaf)** merges layout and content dynamically before sending the final HTML.
    

---

## Known Uses

-   **Spring MVC / Thymeleaf / JSP / Freemarker / Mustache:** Standard server-side rendering in Java web apps.
    
-   **Django Templates / Ruby on Rails ERB / Laravel Blade:** Equivalent in other ecosystems.
    
-   **CMS platforms (WordPress, Magnolia, Adobe AEM):** Template-based rendering for pages and components.
    
-   **Email rendering systems:** Dynamic email bodies built with template engines.
    

## Related Patterns

-   **View Helper:** Encapsulates complex logic used by templates (formatting, tags).
    
-   **Page Controller:** Coordinates which template and model to use per request.
    
-   **Composite View:** Combines multiple templates (fragments) into a full page.
    
-   **Front Controller:** Routes requests to appropriate page controllers or views.
    
-   **MVC (Model–View–Controller):** Template View represents the “View” part of MVC.

