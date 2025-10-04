# Dark Mode Toggle — UI/UX Pattern

## Pattern Name and Classification

**Name:** Dark Mode Toggle  
**Category:** UI/UX · Visual Theming · Personalization · Accessibility

## Intent

Provide users a quick, persistent way to switch between light and dark visual themes, improving comfort, accessibility, and perceived quality across environments (bright daylight vs. low-light).

## Also Known As

Night Mode · Theme Switcher · Appearance Toggle · Light/Dark Theme

## Motivation (Forces)

-   **Comfort & eye strain:** Reduced luminance in low-light settings can decrease glare.
    
-   **Battery life:** Dark palettes can lower power usage on OLED displays.
    
-   **Brand & readability:** Maintain contrast and brand colors without degrading legibility.
    
-   **System coherence:** Some users expect apps to follow OS preference.
    
-   **Control vs. automation:** Users want explicit control but also “use system setting.”
    
-   **Performance:** Theme switching should feel instant and not reflow heavily.
    
-   **Persistence:** Preference should survive reloads and, ideally, roam across devices.
    
-   **Accessibility:** Respect WCAG contrast, dyslexia/astigmatism concerns, and motion sensitivity.
    

## Applicability

Use this pattern when:

-   Your application supports two or more visual themes.
    
-   Users operate in variable lighting or on battery-constrained devices.
    
-   Brand permits palette flexibility without harming recognizability.
    
-   You can guarantee adequate contrast and content parity across themes.
    

Avoid when:

-   A single palette is integral to the product (e.g., data-critical color semantics) and can’t be re-mapped accessibly.
    
-   The UI stack cannot apply theme tokens consistently.
    

## Structure

-   **Theme Tokens:** Semantic design tokens (e.g., `--color-bg`, `--color-fg`, `--elevation-1`) mapped per theme.
    
-   **Theme Resolver:** Determines the active theme via precedence: explicit user choice → stored preference → system setting → default.
    
-   **Toggle Control:** Accessible switch/button with clear state, label, and ARIA semantics.
    
-   **Persistence Layer:** Client storage (localStorage), cookie, or server-side profile.
    
-   **Renderer/Binding:** Mechanism to apply tokens (CSS variables/class, component theme provider).
    
-   **Sync Mechanism:** Optional cross-tab/device sync (events, server profile).
    

## Participants

-   **User:** Chooses Light/Dark/System.
    
-   **Theme Manager/Resolver:** Computes final theme.
    
-   **Storage:** Saves preference (cookie, DB).
    
-   **UI Renderer:** Applies tokens (CSS vars, classes).
    
-   **Accessibility Auditor:** Ensures contrast and motion guidelines.
    

## Collaboration

1.  User interacts with Toggle →
    
2.  Theme Resolver updates current theme →
    
3.  Renderer applies token set with minimal layout shift →
    
4.  Preference persisted →
    
5.  Optional: system preference change (media query) triggers update when mode=System.
    

## Consequences

**Benefits**

-   Comfort, perceived quality, and modern expectations met.
    
-   Accessibility improvements with correct contrast handling.
    
-   Potential power savings on OLED.
    

**Liabilities**

-   Increased design/testing matrix (themes × states).
    
-   Color semantics in charts/maps must be re-validated.
    
-   Risk of “flash of incorrect theme” (FOIT/FART equivalent) if not set early.
    
-   Brand drift if tokens aren’t governed.
    

## Implementation

**Key recommendations**

1.  **Tokenize first:** Use semantic tokens; never hard-code raw colors in components.
    
2.  **Decide precedence:** `userChoice > storedPref > systemPref > default`.
    
3.  **Prevent flash:** Apply server-rendered class or early inline script before paint.
    
4.  **Accessible control:** Visible label, keyboard focus, ARIA (`role="switch"`, `aria-checked`), 44×44px tap target.
    
5.  **Persist smartly:** Anonymous users → cookie/localStorage; authenticated → server profile for roaming.
    
6.  **Charts/media:** Provide theme-aware palettes; re-validate contrast (WCAG 2.2 AA+).
    
7.  **Motion/transition:** Keep transitions subtle or respect `prefers-reduced-motion`.
    
8.  **Theming non-UI assets:** Logos/illustrations need light/dark variants with transparent backgrounds.
    
9.  **Testing matrix:** Verify in system light/dark, and when switching live; test high-contrast modes and screen readers.
    
10.  **Security:** Treat theme cookies as non-sensitive; avoid setting `HttpOnly` so client JS can read them if needed.
    

## Sample Code (Java)

Below is a minimal Spring Boot–style server-side implementation to persist and resolve a theme preference via cookie and expose it to templates (Thymeleaf/JSP/any server-side view). It also shows a tiny REST endpoint to toggle themes.

```java
// src/main/java/com/example/theme/Theme.java
package com.example.theme;

public enum Theme {
    LIGHT, DARK, SYSTEM;

    public static Theme from(String raw) {
        if (raw == null) return SYSTEM;
        try {
            return Theme.valueOf(raw.trim().toUpperCase());
        } catch (IllegalArgumentException ex) {
            return SYSTEM;
        }
    }
}
```

```java
// src/main/java/com/example/theme/ThemeProperties.java
package com.example.theme;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "app.theme")
public class ThemeProperties {
    /**
     * Name of the cookie storing the theme preference.
     */
    private String cookieName = "theme";
    /**
     * Max age in days for the cookie.
     */
    private int cookieMaxAgeDays = 365;

    public String getCookieName() { return cookieName; }
    public void setCookieName(String cookieName) { this.cookieName = cookieName; }

    public int getCookieMaxAgeDays() { return cookieMaxAgeDays; }
    public void setCookieMaxAgeDays(int cookieMaxAgeDays) { this.cookieMaxAgeDays = cookieMaxAgeDays; }
}
```

```java
// src/main/java/com/example/theme/ThemeResolver.java
package com.example.theme;

import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;

public class ThemeResolver {
    private final String cookieName;

    public ThemeResolver(String cookieName) {
        this.cookieName = cookieName;
    }

    public Theme resolve(HttpServletRequest request) {
        if (request.getAttribute("themeOverride") instanceof Theme to) {
            return to;
        }
        if (request.getCookies() != null) {
            for (Cookie c : request.getCookies()) {
                if (cookieName.equals(c.getName())) {
                    return Theme.from(c.getValue());
                }
            }
        }
        // Default to SYSTEM; client can map system pref at render.
        return Theme.SYSTEM;
    }
}
```

```java
// src/main/java/com/example/theme/ThemeFilter.java
package com.example.theme;

import jakarta.servlet.*;
import jakarta.servlet.http.HttpServletRequest;
import java.io.IOException;

public class ThemeFilter implements Filter {
    private final ThemeResolver resolver;

    public ThemeFilter(ThemeResolver resolver) {
        this.resolver = resolver;
    }

    @Override
    public void doFilter(ServletRequest req, ServletResponse res, FilterChain chain)
            throws IOException, ServletException {
        HttpServletRequest httpReq = (HttpServletRequest) req;
        Theme theme = resolver.resolve(httpReq);
        // Expose to views (e.g., Thymeleaf model or JSP EL via request attribute)
        req.setAttribute("activeTheme", theme.name().toLowerCase());
        chain.doFilter(req, res);
    }
}
```

```java
// src/main/java/com/example/theme/ThemeController.java
package com.example.theme;

import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/theme")
public class ThemeController {
    private final ThemeProperties props;

    public ThemeController(ThemeProperties props) {
        this.props = props;
    }

    @PostMapping("/set")
    public ResponseEntity<?> setTheme(@RequestParam("value") String value,
                                      HttpServletResponse response) {
        Theme chosen = Theme.from(value);
        Cookie cookie = new Cookie(props.getCookieName(), chosen.name().toLowerCase());
        cookie.setPath("/");
        cookie.setMaxAge(props.getCookieMaxAgeDays() * 24 * 60 * 60);
        // Not HttpOnly so client can read for early apply; secure if using HTTPS.
        cookie.setHttpOnly(false);
        cookie.setSecure(true);
        response.addCookie(cookie);
        return ResponseEntity.noContent().build();
    }
}
```

```java
// src/main/java/com/example/theme/ThemeConfig.java
package com.example.theme;

import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class ThemeConfig {

    @Bean
    public ThemeProperties themeProperties() {
        return new ThemeProperties();
    }

    @Bean
    public ThemeResolver themeResolver(ThemeProperties props) {
        return new ThemeResolver(props.getCookieName());
    }

    @Bean
    public FilterRegistrationBean<ThemeFilter> themeFilter(ThemeResolver resolver) {
        FilterRegistrationBean<ThemeFilter> bean = new FilterRegistrationBean<>();
        bean.setFilter(new ThemeFilter(resolver));
        bean.addUrlPatterns("/*");
        bean.setName("themeFilter");
        bean.setOrder(1);
        return bean;
    }
}
```

**Usage in a server-rendered template (conceptual):**

-   Add a `class="theme-${activeTheme}"` on your `<html>` or `<body>` tag to switch CSS variables.
    
-   The client can still respect system preference when `activeTheme = "system"` by mapping it to `light` or `dark` using `prefers-color-scheme` (handled in CSS/JS).
    

**Notes**

-   For authenticated users, persist `Theme` in their profile and set the cookie during login for instant apply.
    
-   For SPA clients, call `/api/theme/set?value=dark` and also update in-memory theme provider.
    

## Known Uses

-   **Apple iOS/macOS, Android, Windows:** System-wide light/dark with “Use device setting.”
    
-   **GitHub, Twitter/X, Reddit, Slack, VS Code, JetBrains IDEs:** User-controlled theme toggles with persistence and “match system” options.
    
-   **Notion, Figma:** Theme switching with tokenized design systems.
    

## Related Patterns

-   **Design Tokens / Theming:** Foundation for consistent palette and elevation across themes.
    
-   **Preference Center / Settings Panel:** Central place to configure theme and other personalization.
    
-   **Responsive & Adaptive Design:** Theme complements responsiveness for environment-aware UI.
    
-   **Accessibility Settings:** High contrast, reduced motion—often co-configured with theme.
    
-   **Client-Side Composition:** Each micro-frontend respects a shared theme contract.
    
-   **Progressive Enhancement:** Functional without JS; enhanced with instant toggling when JS is present.

