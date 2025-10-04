# Responsive Design — UI/UX Pattern

## Pattern Name and Classification

**Name:** Responsive Design  
**Category:** UI/UX · Layout/Presentation · Multi-Device Adaptation · Progressive Enhancement

## Intent

Adapt layout, typography, media, and interactions so the same content works **gracefully across viewport sizes, pixel densities, and input modes**—without separate codebases per device.

## Also Known As

Mobile-First · Fluid Layouts · Adaptive UI · Responsive Web Design (RWD)

## Motivation (Forces)

-   **Device diversity:** Phones, tablets, desktops, TVs, foldables, and high-DPI screens.
    
-   **Performance:** Ship only what’s needed per device (images, scripts).
    
-   **Maintainability:** One codebase instead of “m.example.com” forks.
    
-   **Accessibility:** Respect zoom, reduced motion, contrast preferences.
    
-   **Brand consistency:** Visual identity must scale.
    
-   **Trade-offs:** Breakpoint creep, complex CSS matrices, and testing burden across devices.
    

## Applicability

Use when:

-   The UI must run on multiple form factors or window sizes.
    
-   Content parity matters—no “mobile-lite” dead ends.
    
-   You can rely on **progressive enhancement** (works without JS; enhances with it).
    

Avoid or adjust when:

-   A specialized device/app demands a **task-optimized** interface that diverges heavily (then deliver a dedicated experience).
    
-   Highly interactive apps with desktop-only affordances (still support minimum graceful degradation).
    

## Structure

-   **Fluid grid & flexible media:** Percent/viewport units, container queries, `max-width: 100%`.
    
-   **Breakpoints:** Content-driven media/container queries (e.g., 480/768/1024/1280).
    
-   **Responsive media:** `srcset`/`sizes`, AVIF/WebP, DPR-aware images, art direction via `<picture>`.
    
-   **Progressive enhancement:** Base HTML → CSS layout → JS enhancements.
    
-   **Feature queries & user prefs:** `@supports`, `prefers-reduced-motion`, `prefers-color-scheme`.
    
-   **Server assist (optional):** Responsive image variants, HTTP Client Hints, content negotiation.
    

```css
Content  →  Base HTML  →  CSS (fluid + breakpoints + container queries)
                               ↓
                         Responsive media
                               ↓
                   JS enhances interactions progressively
```

## Participants

-   **Content/Components:** Semantically marked-up units.
    
-   **Layout System:** Grid, flex, container queries, spacing scale.
    
-   **Media Pipeline:** Images/video variants, CDNs.
    
-   **Behavior Layer:** Progressive, input-agnostic interactions (mouse/touch/keyboard).
    
-   **Server/CDN (optional):** Negotiates image type/size and sets Client Hints.
    

## Collaboration

1.  Browser loads baseline HTML/CSS (fast first render).
    
2.  CSS applies fluid rules; breakpoints/container queries refine layout.
    
3.  Media elements pick optimal sources via `srcset/sizes` and Client Hints.
    
4.  JS enhances components (menus, carousels) without breaking core flow.
    
5.  Server/CDN can tailor media based on hints (DPR, width, formats).
    

## Consequences

**Benefits**

-   One codebase; consistent brand; better SEO.
    
-   Better performance: fewer bytes on mobile, sharper media on retina.
    
-   Accessibility wins via user-preference queries and flexible typography.
    

**Liabilities**

-   More CSS states to design/test.
    
-   Complex responsive media pipelines if done server-side.
    
-   Risk of layout shifts if aspect ratios aren’t reserved.
    

## Implementation

**Guidelines**

1.  **Mobile-first CSS:** Start narrow; add min-width queries for larger screens.
    
2.  **Design tokens:** Spacing, typography, color; scale responsively (clamp()).
    
3.  **Container queries first:** Prefer `@container` over global breakpoints when styling components.
    
4.  **Reserve media space:** Use `aspect-ratio` to avoid CLS.
    
5.  **Images:** Use `<picture>` + `srcset/sizes`; serve AVIF/WebP with fallbacks.
    
6.  **Client Hints:** `Accept-CH: DPR, Width, Viewport-Width` to help the server pick an optimal asset.
    
7.  **Accessibility:** Respect `prefers-reduced-motion`, `prefers-contrast`, larger font zoom.
    
8.  **Testing:** Real devices + emulators; test orientations, zoom, and reduced-motion.
    
9.  **Performance budgets:** Per breakpoint; measure Core Web Vitals.
    

---

## Sample Code (Java — Spring Boot: Responsive Image Negotiation)

*Goal:* Serve responsive image variants (by width and format) using **HTTP Client Hints** and content negotiation. Frontend uses standard `<picture>`/`srcset`; backend returns the best variant.

```java
// build.gradle (relevant)
/// implementation 'org.springframework.boot:spring-boot-starter-web'
```

```java
// src/main/java/com/example/rwd/WebConfig.java
package com.example.rwd;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.*;

@Configuration
public class WebConfig implements WebMvcConfigurer {
    @Override
    public void addCorsMappings(CorsRegistry registry) { /* if CDN/domain split needed */ }
}
```

```java
// src/main/java/com/example/rwd/ResponsiveImageService.java
package com.example.rwd;

import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;

import java.util.*;

@Service
public class ResponsiveImageService {
    // Pretend we have pre-generated variants in a CDN/bucket:
    // key: baseId, value: list of width->url (and available formats).
    private static final Map<String, List<Variant>> DB = Map.of(
        "hero", List.of(
            new Variant(480,  "image/avif", "https://cdn.example.com/hero-480.avif"),
            new Variant(480,  "image/webp", "https://cdn.example.com/hero-480.webp"),
            new Variant(960,  "image/avif", "https://cdn.example.com/hero-960.avif"),
            new Variant(960,  "image/webp", "https://cdn.example.com/hero-960.webp"),
            new Variant(1440, "image/avif", "https://cdn.example.com/hero-1440.avif"),
            new Variant(1440, "image/webp", "https://cdn.example.com/hero-1440.webp")
        )
    );

    record Variant(int width, String mime, String url) {}

    public Optional<Variant> choose(String id, int viewportWidth, double dpr, List<MediaType> accepted) {
        var list = DB.getOrDefault(id, List.of());
        if (list.isEmpty()) return Optional.empty();

        // Target CSS slot ≈ 100vw (simplified) * DPR, clamp to largest available
        int targetPixels = (int)Math.min(viewportWidth * Math.max(1.0, dpr),
                                         list.stream().mapToInt(Variant::width).max().orElse(480));

        // Preferred formats in order of client accept
        List<String> preferred = accepted.stream().map(MediaType::toString).toList();

        // Pick the smallest >= targetPixels with preferred format fallback
        return list.stream()
                .sorted(Comparator.comparingInt(Variant::width))
                .filter(v -> v.width >= targetPixels)
                .sorted((a,b) -> {
                    // prefer better format first based on Accept header order
                    int ia = indexOf(preferred, a.mime);
                    int ib = indexOf(preferred, b.mime);
                    return Integer.compare(ia, ib);
                })
                .findFirst()
                .or(() -> Optional.of(list.get(list.size()-1))); // largest fallback
    }

    private int indexOf(List<String> prefs, String mime) {
        int i = prefs.indexOf(mime);
        return i < 0 ? Integer.MAX_VALUE : i;
    }
}
```

```java
// src/main/java/com/example/rwd/ResponsiveImageController.java
package com.example.rwd;

import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;

import java.net.URI;
import java.util.*;

@RestController
@RequestMapping("/img")
public class ResponsiveImageController {
    private final ResponsiveImageService service;

    public ResponsiveImageController(ResponsiveImageService service) { this.service = service; }

    /**
     * Example: /img/hero
     * Uses Client Hints:
     *   Width: viewport width in CSS px
     *   DPR: device pixel ratio
     * Also respects Accept for image formats (AVIF/WebP).
     */
    @GetMapping("/{id}")
    public ResponseEntity<Void> get(
            @PathVariable String id,
            @RequestHeader(value = "Width", required = false, defaultValue = "768") int vw,
            @RequestHeader(value = "DPR", required = false, defaultValue = "1") double dpr,
            @RequestHeader(value = "Accept", required = false, defaultValue = "image/avif,image/webp,image/*") String accept
    ) {
        List<MediaType> accepted = MediaType.parseMediaTypes(accept);
        var variant = service.choose(id, vw, dpr, accepted);
        if (variant.isEmpty()) return ResponseEntity.notFound().build();

        // 302 redirect to the optimal CDN URL (or stream it directly)
        return ResponseEntity.status(HttpStatus.FOUND)
                .location(URI.create(variant.get().url()))
                // Advertise that we honor Client Hints; browsers send them on next requests
                .header("Accept-CH", "DPR, Width, Viewport-Width")
                .header("Vary", "DPR, Width, Viewport-Width, Accept")
                .build();
    }
}
```

**How to use on the page (conceptual HTML):**

```html
<picture>
  <!-- Art direction example -->
  <source type="image/avif" srcset="/img/hero" />
  <source type="image/webp" srcset="/img/hero" />
  <img src="/img/hero" alt="Hero" style="width:100%; aspect-ratio: 16/9; height:auto;">
</picture>
```

*What this demonstrates*

-   A **single endpoint** chooses the best image variant using **Client Hints** (`Width`, `DPR`) and **Accept** format negotiation, returning a redirect to the CDN asset.
    
-   Adds `Vary` to keep caches honest per device characteristics.
    
-   Pairs naturally with CSS fluid layout and `aspect-ratio` to avoid layout shifts.
    

---

## Known Uses

-   **News, e-commerce, and SaaS marketing sites** using fluid grids and responsive images.
    
-   **Design systems** (Material, Fluent) with responsive tokens/spacing and component breakpoints.
    
-   **CDNs** (Cloudinary, Imgix, Akamai) generating responsive media variants.
    
-   **PWAs** balancing mobile/desktop layouts with the same codebase.
    

## Related Patterns

-   **Progressive Enhancement / Graceful Degradation**
    
-   **Adaptive Images / Responsive Images** (`srcset`, Client Hints)
    
-   **Device/Feature Detection** (`@supports`, UA/CH)
    
-   **Lazy Loading & Infinite Scroll** (often combined for performance)
    
-   **Design Tokens / Theming** (consistent scaling across breakpoints)
    
-   **Accessible Design** (prefers-reduced-motion/contrast, scalable type)

