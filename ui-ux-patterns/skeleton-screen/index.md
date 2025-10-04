# Skeleton — UI/UX Pattern

## Pattern Name and Classification

**Name:** Skeleton (Loading Skeleton)  
**Category:** UI/UX · Feedback Pattern · Progressive Rendering · Perceived Performance

## Intent

Provide an immediate **visual placeholder** that mimics the layout of content while real data loads, reducing perceived latency and keeping users engaged instead of staring at blank or shifting screens.

## Also Known As

Loading Placeholder · Ghost UI · Shimmer Loading · Content Placeholder

## Motivation (Forces)

-   **Perceived performance:** Humans tolerate delay better when progress is visible. A skeleton shows structure immediately, improving perceived responsiveness.
    
-   **Layout stability:** Prevents layout shifts (CLS) by reserving space for incoming content.
    
-   **Predictability:** Users see the approximate shape of what’s coming (text blocks, images, lists).
    
-   **Engagement:** Keeps attention and context during data fetching or transitions.
    
-   **Trade-offs:** Slightly more UI complexity and possible mismatch if placeholders don’t reflect final layout accurately.
    

## Applicability

Use Skeleton when:

-   Data is fetched asynchronously (API, DB, network) and UI would otherwise appear empty.
    
-   Content layout is predictable and stable (cards, lists, forms).
    
-   You want to minimize flicker or sudden jumps on data arrival.
    
-   You want smoother transitions in **SPA**, **mobile**, or **progressive web** environments.
    

Avoid or adjust when:

-   Load times are under ~150ms (skeleton may flash annoyingly).
    
-   Content layout changes significantly after load (prefer a progress bar or spinner).
    
-   Server-side rendering (SSR) already renders meaningful HTML instantly.
    

## Structure

-   **Skeleton Container:** Wrapper component visible during loading state.
    
-   **Placeholder Elements:** Shapes (rects, circles, text bars) matching final content.
    
-   **Animation Layer (optional):** Shimmer or pulse effect to indicate activity.
    
-   **State Controller:** Switches between “loading” (show skeleton) and “loaded” (show content).
    

```scss
User Request → Loading State (show skeleton)
               ↓
         Data Fetching (async)
               ↓
        Data Received → Replace placeholders with content
```

## Participants

-   **View Component:** Renders skeletons and real data.
    
-   **Data Provider/Service:** Async data fetch.
    
-   **State Manager:** Holds `loading` flag; triggers view updates.
    
-   **Skeleton Template:** Defines placeholders corresponding to each content type.
    
-   **Animator (optional):** Provides shimmer/pulse transitions.
    

## Collaboration

1.  View initializes → `loading=true`.
    
2.  Skeleton placeholders are rendered immediately.
    
3.  DataProvider fetches data asynchronously.
    
4.  On success → `loading=false`.
    
5.  Real content replaces placeholders, preserving layout size.
    

## Consequences

**Benefits**

-   Improved **perceived performance**.
    
-   Maintains **layout consistency** and reduces CLS.
    
-   Reduces user frustration and increases trust.
    
-   Works well with lazy loading and pagination.
    

**Liabilities**

-   Requires additional design effort for placeholder states.
    
-   Adds a few rendering steps and condition checks.
    
-   Poorly designed skeletons may mislead users or feel fake.
    
-   Needs synchronization with async data flow to prevent flicker.
    

## Implementation

**Guidelines**

1.  **Design accurate placeholders:** Match the real layout’s shape, not just generic bars.
    
2.  **Control timing:** Avoid showing skeletons for micro-delays (<150ms). Use debounce thresholds.
    
3.  **Shimmer animation:** Optional; subtle movement signals liveness.
    
4.  **Consistent transitions:** Fade between skeleton and real content to reduce abrupt changes.
    
5.  **Accessibility:** Ensure skeletons are not focusable and have proper ARIA roles (`aria-busy`, `aria-hidden`).
    
6.  **Code reuse:** Abstract skeleton templates as reusable components (e.g., `CardSkeleton`, `ListSkeleton`).
    
7.  **Testing:** Validate transitions and flicker absence; simulate slow networks.
    

---

## Sample Code (Java — Spring Boot with Thymeleaf, Asynchronous Service Rendering Skeleton Placeholder)

**Goal:** Show a static skeleton page while data loads asynchronously, then dynamically inject content.

```java
// build.gradle (relevant)
// implementation 'org.springframework.boot:spring-boot-starter-web'
// implementation 'org.springframework.boot:spring-boot-starter-thymeleaf'
// implementation 'org.springframework.boot:spring-boot-starter-webflux'
```

```java
// src/main/java/com/example/skeleton/DemoApplication.java
package com.example.skeleton;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class DemoApplication {
    public static void main(String[] args) {
        SpringApplication.run(DemoApplication.class, args);
    }
}
```

```java
// src/main/java/com/example/skeleton/service/UserService.java
package com.example.skeleton.service;

import com.example.skeleton.model.User;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.List;

@Service
public class UserService {

    public Mono<List<User>> fetchUsers() {
        // Simulate slow I/O
        return Mono.just(List.of(
                new User("Alice", "Architect"),
                new User("Bob", "Developer"),
                new User("Carol", "Designer")
        )).delayElement(Duration.ofSeconds(2));
    }
}
```

```java
// src/main/java/com/example/skeleton/model/User.java
package com.example.skeleton.model;

public record User(String name, String role) {}
```

```java
// src/main/java/com/example/skeleton/controller/UserController.java
package com.example.skeleton.controller;

import com.example.skeleton.service.UserService;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import reactor.core.publisher.Mono;

@Controller
public class UserController {
    private final UserService service;

    public UserController(UserService service) { this.service = service; }

    @GetMapping("/users")
    public String users(Model model) {
        // Initially render skeleton page
        model.addAttribute("loading", true);
        return "users"; // Thymeleaf template
    }

    @GetMapping(value = "/api/users", produces = "application/json")
    public Mono<?> apiUsers() {
        return service.fetchUsers();
    }
}
```

```html
<!-- src/main/resources/templates/users.html -->
<!DOCTYPE html>
<html xmlns:th="http://www.thymeleaf.org">
<head>
    <meta charset="UTF-8"/>
    <title>Users</title>
    <style>
        .skeleton {
            background: linear-gradient(90deg, #e2e2e2 25%, #f5f5f5 50%, #e2e2e2 75%);
            background-size: 200% 100%;
            animation: shimmer 1.5s infinite;
            border-radius: 4px;
        }
        @keyframes shimmer {
            0% { background-position: -200% 0; }
            100% { background-position: 200% 0; }
        }
        .user-card { width: 200px; margin: 10px; padding: 10px; border: 1px solid #ccc; border-radius: 6px; }
        .name, .role { height: 16px; margin: 5px 0; }
        #user-container { display: flex; flex-wrap: wrap; }
    </style>
</head>
<body>
<h2>User Directory</h2>

<div id="user-container">
    <!-- Skeleton placeholders -->
    <div class="user-card" id="skeleton1">
        <div class="name skeleton" style="width:120px;"></div>
        <div class="role skeleton" style="width:80px;"></div>
    </div>
    <div class="user-card" id="skeleton2">
        <div class="name skeleton" style="width:130px;"></div>
        <div class="role skeleton" style="width:90px;"></div>
    </div>
    <div class="user-card" id="skeleton3">
        <div class="name skeleton" style="width:110px;"></div>
        <div class="role skeleton" style="width:70px;"></div>
    </div>
</div>

<script>
    async function loadUsers() {
        const res = await fetch('/api/users');
        const users = await res.json();
        const container = document.getElementById('user-container');
        container.innerHTML = ''; // Remove skeletons
        users.forEach(u => {
            const card = document.createElement('div');
            card.className = 'user-card';
            card.innerHTML = `<div><strong>${u.name}</strong></div><div>${u.role}</div>`;
            container.appendChild(card);
        });
    }
    window.addEventListener('DOMContentLoaded', loadUsers);
</script>
</body>
</html>
```

**Behavior:**

-   The server renders HTML skeleton placeholders instantly.
    
-   Frontend fetches `/api/users` asynchronously.
    
-   After 2 seconds, JSON data replaces skeletons with real content.
    
-   The shimmer animation keeps the page “alive” during loading.
    

---

## Known Uses

-   **Facebook, LinkedIn, YouTube:** Shimmer skeleton loaders for feeds and videos.
    
-   **Twitter:** Timeline skeleton placeholders before tweets load.
    
-   **E-commerce sites:** Product grid skeletons during pagination or filtering.
    
-   **Mobile apps:** Lists and cards with skeleton shapes before data binding.
    

## Related Patterns

-   **Progress Indicator / Spinner:** Simple feedback without preserving layout.
    
-   **Lazy Loading:** Skeleton often accompanies on-demand loading.
    
-   **Placeholder / Content Placeholder:** Broader category; skeleton is its modern, shaped variant.
    
-   **Optimistic UI:** Complements skeletons by showing predicted results before server confirmation.
    
-   **Responsive Design:** Skeleton shapes adapt to viewport size for consistent perceived performance.

