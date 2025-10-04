# Lazy Loading — UI/UX Pattern

## Pattern Name and Classification

**Name:** Lazy Loading  
**Category:** UI/UX · Performance Optimization · Resource Management · Progressive Rendering

## Intent

Defer the loading or instantiation of non-critical resources or components until they are actually needed—improving initial load time, perceived performance, and resource efficiency.

## Also Known As

Deferred Loading · On-Demand Loading · Just-in-Time Loading · Load-on-Access

## Motivation (Forces)

Modern applications, especially web and mobile UIs, deliver large amounts of assets—images, components, and data. Loading everything up front causes:

-   **Slow first render** (large bundle or heavy network requests).
    
-   **High memory and CPU usage.**
    
-   **Bandwidth waste** on unseen resources (e.g., below-the-fold images).
    

**Lazy Loading** mitigates this by delaying expensive loads until the content or component enters the viewport or is explicitly requested.

**Forces:**

-   Balance between **speed of first interaction** and **smoothness of subsequent content**.
    
-   **Predictability vs. responsiveness:** Prefetching can reduce latency but may increase resource usage.
    
-   **Accessibility:** Ensure deferred resources still announce correctly for assistive technologies.
    
-   **Caching & state management:** Avoid flicker or reloads when scrolling back.
    

## Applicability

Use when:

-   Large datasets, media, or third-party components are present.
    
-   Many items are initially invisible (scrollable lists, galleries).
    
-   Application modules can be loaded independently (modular SPA).
    
-   Network and device performance vary significantly (mobile users).
    

Avoid when:

-   Content is critical for first meaningful paint (hero image, key CTA).
    
-   Sequential dependencies require preloading for seamless UX (animations, timelines).
    

## Structure

-   **Trigger/Event Source:** Scroll, viewport entry, click, route change.
    
-   **Loader:** Mechanism to fetch or instantiate deferred resource.
    
-   **Placeholder/Skeleton:** Visual placeholder or stub until real content is ready.
    
-   **Cache:** Prevent re-fetching of already loaded resources.
    
-   **Observer/Controller:** Manages thresholds and triggers (IntersectionObserver, reactive signals).
    
-   **Resource:** Image, module, dataset, or component that will be lazily loaded.
    

```sql
User Scroll/Action
      ↓
   Trigger
      ↓
   Loader → Fetch Resource
      ↓
   Cache → Display Resource
```

## Participants

-   **User:** Triggers the event (scroll, click, navigation).
    
-   **Lazy Loader:** Detects trigger conditions and initiates load.
    
-   **Data Provider / API / Module Loader:** Provides deferred content or code.
    
-   **Placeholder Renderer:** Displays interim visual until loaded.
    
-   **Cache/Memory Manager:** Retains already loaded assets for quick reaccess.
    
-   **View/Component Renderer:** Replaces placeholders with final content.
    

## Collaboration

1.  User scrolls or interacts with UI.
    
2.  Observer detects visibility or interaction threshold.
    
3.  Lazy Loader fetches data or imports module asynchronously.
    
4.  Placeholder replaced with actual resource once loaded.
    
5.  Cache stores loaded resource for reuse.
    
6.  Renderer updates layout smoothly.
    

## Consequences

**Benefits**

-   Faster initial load and time-to-interactive (TTI).
    
-   Reduced bandwidth and memory usage.
    
-   Improved perceived performance and energy efficiency.
    
-   Scalable for large feeds, images, or modular UIs.
    

**Liabilities**

-   Slight delay when content first appears.
    
-   Requires careful handling for SEO (search bots may not trigger load).
    
-   Accessibility issues if content appears unpredictably.
    
-   Increased implementation complexity (observer logic, state handling).
    
-   Potential layout shifts (CLS) if placeholders not sized correctly.
    

## Implementation

**Key Recommendations:**

1.  **Predictable placeholders:** Reserve exact dimensions to avoid layout shifts.
    
2.  **Use native browser features:** `<img loading="lazy">`, dynamic `import()`, IntersectionObserver API.
    
3.  **Batch requests:** Group loads to minimize request storms.
    
4.  **Prioritize visible + near-visible elements:** Prefetch slightly above the viewport.
    
5.  **Cache smartly:** Use memory/disk caching to prevent redundant fetches.
    
6.  **Fallbacks:** Provide default images or error placeholders if loading fails.
    
7.  **Accessibility:** Announce new content dynamically (ARIA live regions).
    
8.  **Testing:** Simulate slow networks and scrolling to ensure stable progressive loading.
    
9.  **Progressive enhancement:** Use `noscript` fallback for critical content.
    

---

## Sample Code (Java)

Below is a minimal **Spring Boot REST example** that supports server-side lazy loading for a large image gallery.  
The backend provides **paged data** to be fetched progressively by the UI.

```java
// src/main/java/com/example/lazyload/Image.java
package com.example.lazyload;

import jakarta.persistence.*;

@Entity
@Table(name = "images")
public class Image {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private String url;

    @Column(nullable = false)
    private String title;

    // Getters/setters
    public Long getId() { return id; }
    public String getUrl() { return url; }
    public void setUrl(String url) { this.url = url; }
    public String getTitle() { return title; }
    public void setTitle(String title) { this.title = title; }
}
```

```java
// src/main/java/com/example/lazyload/ImageRepository.java
package com.example.lazyload;

import org.springframework.data.domain.*;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ImageRepository extends JpaRepository<Image, Long> {
    Page<Image> findAll(Pageable pageable);
}
```

```java
// src/main/java/com/example/lazyload/ImageController.java
package com.example.lazyload;

import org.springframework.data.domain.*;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/images")
public class ImageController {

    private final ImageRepository repo;

    public ImageController(ImageRepository repo) { this.repo = repo; }

    @GetMapping
    public ResponseEntity<?> list(
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size
    ) {
        Page<Image> p = repo.findAll(PageRequest.of(page, size, Sort.by("id").ascending()));

        return ResponseEntity.ok(new java.util.LinkedHashMap<>() {{
            put("content", p.getContent());
            put("page", p.getNumber());
            put("totalPages", p.getTotalPages());
            put("hasNext", p.hasNext());
        }});
    }
}
```

**Explanation:**

-   The client (frontend) initially loads the first 20 images.
    
-   As the user scrolls, it requests `/api/images?page=1`, `/api/images?page=2`, etc.
    
-   Each response includes `hasNext` to decide whether to continue loading.
    
-   Placeholder elements (blurred boxes) are shown while images load.
    

---

**Client (conceptual example)**

```html
<div id="gallery">
  <img src="placeholder.jpg" data-src="image1.jpg" loading="lazy" alt="..." />
  <img src="placeholder.jpg" data-src="image2.jpg" loading="lazy" alt="..." />
</div>

<script>
const images = document.querySelectorAll('img[data-src]');
const observer = new IntersectionObserver(entries => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      const img = entry.target;
      img.src = img.dataset.src;
      observer.unobserve(img);
    }
  });
});
images.forEach(img => observer.observe(img));
</script>
```

**Server logs (example):**

```arduino
GET /api/images?page=0&size=20
GET /api/images?page=1&size=20
GET /api/images?page=2&size=20
```

---

## Known Uses

-   **YouTube / TikTok / Instagram:** Load video thumbnails as they appear on screen.
    
-   **Google Images / Pinterest:** Progressive grid image loading.
    
-   **E-commerce (Amazon, Zalando):** Deferred loading of product thumbnails or details.
    
-   **React, Angular, Vue apps:** Dynamic `import()` for components loaded on route or interaction.
    
-   **Modern browsers:** Native `<img loading="lazy">` attribute.
    

## Related Patterns

-   **Infinite Scroll:** Often combines lazy loading for incremental data fetch.
    
-   **Virtual Scrolling / Windowing:** Keeps only visible items in DOM, often paired with lazy loading.
    
-   **Progressive Rendering:** Renders partial content first, then enhances.
    
-   **Skeleton Screens:** Visual placeholders complement lazy loading.
    
-   **Content Delivery Optimization (CDN, caching):** Reduces latency for deferred resources.
    
-   **Code Splitting:** Backend or build-level lazy loading for JavaScript modules.

