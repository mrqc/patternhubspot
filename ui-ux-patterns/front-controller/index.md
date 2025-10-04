# Front Controller — UI/UX Pattern

## Pattern Name and Classification

**Name:** Front Controller  
**Category:** UI/UX · Web Application Architecture · Request Routing · Centralized Control

## Intent

Centralize **request handling, routing, and cross-cutting concerns** (auth, logging, i18n, error handling) in a single entry point before delegating to page/action controllers. This yields consistent behavior and simpler maintenance.

## Also Known As

Application Controller · Dispatcher · Central Controller

## Motivation (Forces)

-   **Consistency:** Authentication, CSRF, rate limits, and error rendering should be uniform.
    
-   **Separation of concerns:** Keep views lean; orchestration lives centrally.
    
-   **Scalability of features:** Adding logging, A/B flags, localization, theming, or caching in one place is safer than scattering.
    
-   **Extensibility:** New routes/actions can be plugged into a registry without boilerplate.
    
-   **Testability:** Deterministic request lifecycle with predictable hooks.
    
-   **Performance vs. flexibility:** Extra indirection must be light; hot paths should short-circuit efficiently.
    

## Applicability

Use when:

-   Building server-rendered UIs or APIs where **all requests** should pass through common policies.
    
-   You need uniform **error pages**, **content negotiation**, **session management**, **metrics**, or **feature flags**.
    
-   Multiple UI technologies (JSP/Thymeleaf/Freemarker/JSON) share the same routing.
    

Avoid or scope carefully when:

-   A serverless or edge-router already performs all cross-cutting concerns and you only have a few endpoints.
    
-   Extreme performance constraints prohibit any central indirection (rare; can still optimize).
    

## Structure

-   **Front Controller (Dispatcher):** Single entry; parses request, runs interceptors, routes to handlers, resolves views.
    
-   **Router/Mapping:** Maps method + path (and params) to **Handlers**.
    
-   **Handlers (Page/Action Controllers):** Small units implementing business use cases for a route.
    
-   **Interceptors/Filters:** Pre-/post-processing (auth, logging, i18n, caching, validation).
    
-   **View Resolver:** Selects and renders view (JSP/HTML/JSON) and sets headers/status codes.
    
-   **Error Strategy:** Maps exceptions to problem details or error views.
    

```javascript
Client → FrontController → [Interceptors] → Router → Handler → Model
                                     ↘               ↘
                                      Error Map       View Resolver → Response
```

## Participants

-   **FrontController:** Coordinates the lifecycle of each request.
    
-   **Interceptor:** Cross-cutting logic (before/after handler).
    
-   **Router:** Finds the correct handler for (method, path).
    
-   **Handler (Controller/Action):** Executes domain logic, returns a Result (Model + View).
    
-   **ViewResolver:** Turns Result into a concrete response.
    
-   **ErrorMapper:** Converts exceptions to structured responses.
    

## Collaboration

1.  Request enters FrontController.
    
2.  Interceptors `preHandle()` (auth, csrf, rate limit).
    
3.  Router selects Handler; parameters bound and validated.
    
4.  Handler executes; returns `Result`.
    
5.  Interceptors `postHandle()` (metrics, caching hints).
    
6.  ViewResolver renders (HTML/JSP/JSON/redirect).
    
7.  On errors, ErrorMapper selects fallback view/JSON body and status.
    

## Consequences

**Benefits**

-   Single, consistent place for policies and observability.
    
-   Reduced duplication across pages/controllers.
    
-   Clear extension points (register routes, add interceptors).
    
-   Easier A/B experiments and feature gating.
    

**Liabilities**

-   Improperly designed controller can become a **god object**.
    
-   Over-general routing might hide intent; keep explicit maps.
    
-   Extra hop vs. direct servlet; usually negligible in practice.
    

## Implementation

**Key Guidelines**

1.  **Keep it thin:** Route, orchestrate, and delegate—don’t pack domain logic.
    
2.  **Explicit mappings:** Prefer code/annotation route maps over ad-hoc reflection.
    
3.  **Idempotent interceptors:** Pre/post hooks must not mutate business state unexpectedly.
    
4.  **Clear results:** Handlers return a typed `Result` (e.g., `View(name, model)` or `Json(body, status)`).
    
5.  **Robust error mapping:** Centralize exception → status/view; support RFC7807 for APIs.
    
6.  **Content negotiation:** Respect `Accept` headers; allow JSON/HTML from the same handler when needed.
    
7.  **Observability:** Correlation IDs, timing, and structured logs at the Front Controller.
    
8.  **Security:** CSRF/session checks here; validate path parameters centrally.
    
9.  **Performance:** Short-circuit static assets at the edge or separate servlet.
    

---

## Sample Code (Java)

A minimal **Jakarta Servlet (6+)** Front Controller with routing, interceptors, and view resolution. (Conceptual but runnable with a servlet container.)

```java
// src/main/java/com/example/fc/http/Result.java
package com.example.fc.http;

import java.util.Map;

public sealed interface Result permits ViewResult, JsonResult, RedirectResult {
    int status();
}

final class ViewResult implements Result {
    private final String viewName; // e.g., "/WEB-INF/views/home.jsp"
    private final Map<String,Object> model;
    private final int status;

    public ViewResult(String viewName, Map<String,Object> model, int status) {
        this.viewName = viewName; this.model = model; this.status = status;
    }
    public String viewName() { return viewName; }
    public Map<String,Object> model() { return model; }
    public int status() { return status; }
}

final class JsonResult implements Result {
    private final String json;
    private final int status;
    public JsonResult(String json, int status) { this.json = json; this.status = status; }
    public String json() { return json; }
    public int status() { return status; }
}

final class RedirectResult implements Result {
    private final String location; private final int status;
    public RedirectResult(String location) { this(location, 302); }
    public RedirectResult(String location, int status) { this.location = location; this.status = status; }
    public String location() { return location; }
    public int status() { return status; }
}
```

```java
// src/main/java/com/example/fc/core/Handler.java
package com.example.fc.core;

import com.example.fc.http.Result;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

@FunctionalInterface
public interface Handler {
    Result handle(HttpServletRequest req, HttpServletResponse resp) throws Exception;
}
```

```java
// src/main/java/com/example/fc/core/Interceptor.java
package com.example.fc.core;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

public interface Interceptor {
    default boolean preHandle(HttpServletRequest req, HttpServletResponse resp) throws Exception { return true; }
    default void postHandle(HttpServletRequest req, HttpServletResponse resp) throws Exception {}
    default void afterCompletion(HttpServletRequest req, HttpServletResponse resp, Exception ex) {}
}
```

```java
// src/main/java/com/example/fc/core/Router.java
package com.example.fc.core;

import java.util.HashMap;
import java.util.Map;
import java.util.Objects;

public class Router {
    private final Map<Key, Handler> routes = new HashMap<>();

    public Router add(String method, String path, Handler handler) {
        routes.put(new Key(method.toUpperCase(), path), handler);
        return this;
    }

    public Handler match(String method, String path) {
        return routes.get(new Key(method.toUpperCase(), path));
    }

    private record Key(String method, String path) {
        public Key {
            Objects.requireNonNull(method); Objects.requireNonNull(path);
        }
    }
}
```

```java
// src/main/java/com/example/fc/core/ErrorMapper.java
package com.example.fc.core;

import com.example.fc.http.JsonResult;
import com.example.fc.http.Result;

public class ErrorMapper {
    public Result toResult(Throwable ex) {
        // Simple mapping; extend with RFC 7807, localization, etc.
        int status = 500;
        String title = "Unexpected error";
        if (ex instanceof IllegalArgumentException iae) {
            status = 400; title = iae.getMessage() != null ? iae.getMessage() : "Bad request";
        }
        String json = "{\"title\":\"" + escape(title) + "\",\"status\":" + status + "}";
        return new JsonResult(json, status);
    }
    private String escape(String s) { return s.replace("\"","\\\""); }
}
```

```java
// src/main/java/com/example/fc/FrontControllerServlet.java
package com.example.fc;

import com.example.fc.core.*;
import com.example.fc.http.*;
import jakarta.servlet.ServletException;
import jakarta.servlet.annotation.WebServlet;
import jakarta.servlet.http.*;

import java.io.IOException;
import java.util.List;
import java.util.Map;

@WebServlet(name = "frontController", urlPatterns = "/*")
public class FrontControllerServlet extends HttpServlet {

    private Router router;
    private List<Interceptor> interceptors;
    private ErrorMapper errors;

    @Override
    public void init() {
        this.router = new Router()
                .add("GET", "/", (req, resp) ->
                        new ViewResult("/WEB-INF/views/home.jsp",
                                Map.of("message", "Welcome"), 200))
                .add("POST", "/login", new LoginHandler());

        this.interceptors = List.of(
                new RequestIdInterceptor(),
                new LoggingInterceptor(),
                new CsrfInterceptor()
        );
        this.errors = new ErrorMapper();
    }

    @Override
    protected void service(HttpServletRequest req, HttpServletResponse resp)
            throws ServletException, IOException {
        Exception failure = null;
        try {
            // PRE
            for (Interceptor i : interceptors) {
                if (!i.preHandle(req, resp)) return; // short-circuit (e.g., unauthorized)
            }

            Handler handler = router.match(req.getMethod(), req.getRequestURI());
            if (handler == null) {
                writeJson(resp, new JsonResult("{\"title\":\"Not found\"}", 404));
                return;
            }

            Result result = handler.handle(req, resp);

            // POST
            for (Interceptor i : interceptors) i.postHandle(req, resp);

            render(resp, result);

        } catch (Exception ex) {
            failure = ex;
            Result err = errors.toResult(ex);
            render(resp, err);
        } finally {
            for (Interceptor i : interceptors) i.afterCompletion(req, resp, failure);
        }
    }

    private void render(HttpServletResponse resp, Result result) throws IOException, ServletException {
        resp.setStatus(result.status());
        if (result instanceof ViewResult vr) {
            vr.model().forEach((k, v) -> reqSet(resp, k, v)); // small helper
            resp.setContentType("text/html;charset=UTF-8");
            resp.getRequestDispatcher(vr.viewName()).forward(getThreadLocalRequest(), resp);
        } else if (result instanceof JsonResult jr) {
            writeJson(resp, jr);
        } else if (result instanceof RedirectResult rr) {
            resp.setHeader("Location", rr.location());
        }
    }

    // Helpers to access current request in forward; in real apps use filters/thread locals/context
    private HttpServletRequest getThreadLocalRequest() {
        return (HttpServletRequest) jakarta.servlet.http.HttpServletRequestWrapper.getRequestFromAttributes();
    }
    private void reqSet(HttpServletResponse resp, String k, Object v) {
        getThreadLocalRequest().setAttribute(k, v);
    }
    private void writeJson(HttpServletResponse resp, JsonResult jr) throws IOException {
        resp.setContentType("application/json;charset=UTF-8");
        resp.getWriter().write(jr.json());
    }
}
```

```java
// src/main/java/com/example/fc/LoginHandler.java
package com.example.fc;

import com.example.fc.core.Handler;
import com.example.fc.http.RedirectResult;
import com.example.fc.http.Result;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

public class LoginHandler implements Handler {
    @Override
    public Result handle(HttpServletRequest req, HttpServletResponse resp) {
        String user = req.getParameter("user");
        String pwd  = req.getParameter("password");
        if (user == null || pwd == null || user.isBlank() || pwd.isBlank()) {
            throw new IllegalArgumentException("Missing credentials");
        }
        // authenticate...
        req.getSession(true).setAttribute("user", user);
        return new RedirectResult("/dashboard");
    }
}
```

```java
// src/main/java/com/example/fc/RequestIdInterceptor.java
package com.example.fc;

import com.example.fc.core.Interceptor;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

import java.util.UUID;

public class RequestIdInterceptor implements Interceptor {
    @Override
    public boolean preHandle(HttpServletRequest req, HttpServletResponse resp) {
        String id = UUID.randomUUID().toString();
        req.setAttribute("rid", id);
        resp.setHeader("X-Request-Id", id);
        return true;
    }
}
```

```java
// src/main/java/com/example/fc/LoggingInterceptor.java
package com.example.fc;

import com.example.fc.core.Interceptor;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

public class LoggingInterceptor implements Interceptor {
    private long start;
    @Override public boolean preHandle(HttpServletRequest req, HttpServletResponse resp) {
        start = System.nanoTime();
        System.out.printf("→ %s %s rid=%s%n", req.getMethod(), req.getRequestURI(), req.getAttribute("rid"));
        return true;
    }
    @Override public void postHandle(HttpServletRequest req, HttpServletResponse resp) {
        long ms = (System.nanoTime() - start) / 1_000_000;
        System.out.printf("← %s %s %dms rid=%s%n", req.getMethod(), req.getRequestURI(), ms, req.getAttribute("rid"));
    }
}
```

```java
// src/main/java/com/example/fc/CsrfInterceptor.java
package com.example.fc;

import com.example.fc.core.Interceptor;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

public class CsrfInterceptor implements Interceptor {
    @Override
    public boolean preHandle(HttpServletRequest req, HttpServletResponse resp) {
        if ("POST".equalsIgnoreCase(req.getMethod())) {
            String token = (String) req.getSession(true).getAttribute("csrf");
            String sent  = req.getParameter("csrf");
            if (token == null || !token.equals(sent)) {
                resp.setStatus(403);
                return false;
            }
        }
        return true;
    }
}
```

> Notes:
> 
> -   In production, use container features (Filters) for request binding/thread context; the above keeps focus on the pattern.
>     
> -   Replace the ad-hoc `getThreadLocalRequest()` with a standard forward using `RequestDispatcher` where you have access to the same `HttpServletRequest`.
>     

**Alternative (Spring MVC):** In Spring, the **`DispatcherServlet`** is the Front Controller. You configure `HandlerMapping`, `HandlerInterceptor`, `HandlerAdapter`, and `ViewResolver`; your controllers are the handlers. Custom cross-cutting logic goes into `HandlerInterceptor` and `ControllerAdvice`.

## Known Uses

-   **Spring MVC `DispatcherServlet`**, **Struts `ActionServlet`**, **Jakarta Faces (JSF) `FacesServlet`**.
    
-   **ASP.NET MVC `ControllerFactory/RouteHandler`**, **Ruby on Rails Router + Controller stack**.
    
-   **Play Framework**, **Laravel**, **Django** (WSGI middleware + URL dispatcher act as front controller pipeline).
    

## Related Patterns

-   **Intercepting Filter:** Chainable pre/post processing around the controller.
    
-   **Application Controller / Command:** Encapsulate request handling logic.
    
-   **View Helper / Template View:** Keep views dumb; render with helpers.
    
-   **Page Controller:** A more granular controller per page (often delegated to by the front controller).
    
-   **Router / URL Mapping:** Separates path parsing from dispatching.
    
-   **Problem Details (RFC 7807):** Standardized error payload when returning JSON.

