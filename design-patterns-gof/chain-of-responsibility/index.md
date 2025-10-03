
# Chain of Responsibility — GoF Behavioral Pattern

## Pattern Name and Classification

**Name:** Chain of Responsibility  
**Category:** Behavioral design pattern

## Intent

Avoid coupling the sender of a request to its receiver by giving **more than one** object a chance to handle the request. Chain the receiving objects and pass the request along the chain until one of them handles it.

## Also Known As

Chain, Interceptor (closely related), Pipeline (variant)

## Motivation (Forces)

-   You want to **decouple** *what happens* (request handling) from *who handles it*.

-   There may be **zero, one, or many** suitable handlers for a given request.

-   The handling **policy is dynamic**: you may add, remove, reorder, or configure handlers at runtime.

-   You want **open/closed extensibility**: add a new behavior by adding a new handler, not by modifying existing code.

-   You need **separation of concerns**: each handler encapsulates one responsibility (auth, rate limit, validation, etc.).


## Applicability

Use Chain of Responsibility when:

-   Several objects can handle a request and the **handler isn’t known a priori**.

-   You want to **dispatch without hard `if/else` or `switch` ladders**.

-   The set or order of handlers should be **configurable** (e.g., from DI, config, or feature flags).

-   You want to **reuse** behaviors across different flows by recombining handlers.


## Structure

-   **Handler** — declares an interface with `handle()` and a way to forward to the next handler.

-   **ConcreteHandler** — handles the request or forwards it.

-   **Client** — initiates the request by calling the first handler.

-   **(Optional) Chain/Configurator** — builds/wires the chain.


```rust
Client -> [HandlerA] -> [HandlerB] -> [HandlerC] -> … (ends)
             |            |            |
           handle?      handle?      handle?
           else -> next else -> next else -> next
```

## Participants

-   **Handler**: defines the contract; keeps a reference to the **next** handler.

-   **ConcreteHandler**: decides to handle or **delegate**. May *partially* handle then pass on.

-   **Client**: knows only the first handler; doesn’t know who will ultimately handle the request.

-   **Chain Builder** (optional): assembles handlers (order matters).


## Collaboration

-   The Client sends a request to the head of the chain.

-   Each handler either **handles and stops**, **handles and continues**, or **skips** and forwards.

-   The request may traverse **none, some, or all** handlers; termination is explicit (end of chain or early return).


## Consequences

**Benefits**

-   **Loose coupling** of sender and receiver.

-   **Composability** and **reusability** of cross-cutting steps.

-   **Open for extension**: new behaviors via new handlers; reorder at runtime.

-   Clean alternative to nested **conditionals**.


**Liabilities**

-   **Uncertain handling**: request might go unhandled if no handler accepts it.

-   **Debugging can be harder** (flow spans multiple objects).

-   **Performance**: long chains add overhead; “chatty” request mutation can be expensive.

-   **Order sensitivity**: correctness may depend on chain order.

-   **Error handling**: exceptions/short-circuiting must be clearly defined.


## Implementation

-   Keep the **Handler interface minimal**: `boolean handle(Request req, Context ctx, Chain chain)` or classic `void handle(Request req)`.

-   Decide **propagation policy**:

    -   *Stop-on-handle* (first match handles, then stop).

    -   *Pass-through* (all handlers may contribute).

-   Provide a **safe terminal**: a no-op end or a default/fallback handler.

-   Prefer **immutability** for the request where possible; if mutation is required, document it or carry a **Context** object.

-   **Chain assembly**: use DI (Spring), builders, or configuration to define order.

-   Consider **asynchronous** chains (CompletableFuture/Reactive) for I/O-bound steps.

-   Logging/metrics: wrap handlers or introduce a **decorating handler** for observability.

-   Thread safety: handlers should be **stateless** or properly synchronized if shared.


---

## Sample Code (Java)

**Scenario:** HTTP-like request processing with pluggable handlers (authentication → rate limiting → validation → dispatch). Shows both **stop-on-error** and **pass-through** behaviors.

```java
// ----- Request/Response/Context -----
final class Request {
    private final String path;
    private final String method;
    private final String token;
    private final String body;

    public Request(String method, String path, String token, String body) {
        this.method = method; this.path = path; this.token = token; this.body = body;
    }
    public String method() { return method; }
    public String path() { return path; }
    public String token() { return token; }
    public String body() { return body; }
}

final class Response {
    private int status = 200;
    private String body = "";
    public int getStatus() { return status; }
    public String getBody() { return body; }
    public void set(int status, String body) { this.status = status; this.body = body; }
    @Override public String toString() { return "HTTP " + status + " :: " + body; }
}

// Optional context to share derived data (e.g., user id, rate info)
final class Context {
    private final Map<String, Object> data = new HashMap<>();
    public void put(String key, Object value) { data.put(key, value); }
    @SuppressWarnings("unchecked")
    public <T> T get(String key) { return (T) data.get(key); }
}

// ----- Chain core contracts -----
interface Handler {
    /**
     * @return true if processing should continue, false to short-circuit the chain.
     */
    boolean handle(Request req, Response res, Context ctx, Chain chain);
}

final class Chain {
    private final List<Handler> handlers;
    private int index = 0;

    public Chain(List<Handler> handlers) { this.handlers = List.copyOf(handlers); }

    public void proceed(Request req, Response res, Context ctx) {
        if (index < handlers.size()) {
            Handler h = handlers.get(index++);
            boolean shouldContinue = h.handle(req, res, ctx, this);
            if (shouldContinue) {
                proceed(req, res, ctx);
            }
        }
    }
}

// ----- Concrete Handlers -----
class AuthHandler implements Handler {
    @Override public boolean handle(Request req, Response res, Context ctx, Chain chain) {
        String token = req.token();
        if (token == null || token.isBlank() || !"secret".equals(token)) {
            res.set(401, "Unauthorized");
            return false; // stop-on-error
        }
        // derive principal from token (demo)
        ctx.put("user", "alice");
        return true; // continue
    }
}

class RateLimitHandler implements Handler {
    private final Map<String, Integer> counters = new ConcurrentHashMap<>();
    private final int limitPerMinute;

    public RateLimitHandler(int limitPerMinute) { this.limitPerMinute = limitPerMinute; }

    @Override public boolean handle(Request req, Response res, Context ctx, Chain chain) {
        String user = ctx.get("user");
        String key = user + ":" + (System.currentTimeMillis() / 60_000);
        int count = counters.merge(key, 1, Integer::sum);
        if (count > limitPerMinute) {
            res.set(429, "Too Many Requests");
            return false; // short-circuit
        }
        return true;
    }
}

class ValidationHandler implements Handler {
    @Override public boolean handle(Request req, Response res, Context ctx, Chain chain) {
        if ("POST".equals(req.method()) && (req.body() == null || req.body().isBlank())) {
            res.set(400, "Body required");
            return false;
        }
        return true;
    }
}

class DispatchHandler implements Handler {
    @Override public boolean handle(Request req, Response res, Context ctx, Chain chain) {
        // "Handle and stop" by default
        if ("GET".equals(req.method()) && "/hello".equals(req.path())) {
            String user = ctx.get("user");
            res.set(200, "Hello " + (user != null ? user : "guest") + "!");
            return false; // terminate after successful handling
        }
        if ("POST".equals(req.method()) && "/echo".equals(req.path())) {
            res.set(201, "Created: " + req.body());
            return false;
        }
        // Not handled here, continue (maybe a fallback exists)
        return true;
    }
}

class NotFoundHandler implements Handler {
    @Override public boolean handle(Request req, Response res, Context ctx, Chain chain) {
        // Final fallback: set 404 and stop.
        res.set(404, "Not Found: " + req.method() + " " + req.path());
        return false;
    }
}

// ----- Chain Builder (fluent) -----
final class ChainBuilder {
    private final List<Handler> handlers = new ArrayList<>();
    public ChainBuilder add(Handler h) { handlers.add(h); return this; }
    public Chain build() { return new Chain(handlers); }
}

// ----- Demo -----
public class ChainOfResponsibilityDemo {
    public static void main(String[] args) {
        Chain chain = new ChainBuilder()
                .add(new AuthHandler())
                .add(new RateLimitHandler(3))
                .add(new ValidationHandler())
                .add(new DispatchHandler())
                .add(new NotFoundHandler()) // terminal fallback
                .build();

        Context ctx = new Context();
        Response res = new Response();

        Request ok = new Request("GET", "/hello", "secret", null);
        chain.proceed(ok, res, ctx);
        System.out.println(res); // HTTP 200 :: Hello alice!

        // Exceed rate limit
        for (int i = 0; i < 5; i++) {
            ctx = new Context(); res = new Response();
            chain.proceed(ok, res, ctx);
            System.out.println(res);
        }

        // Validation failure
        Request bad = new Request("POST", "/echo", "secret", "");
        ctx = new Context(); res = new Response();
        chain.proceed(bad, res, ctx);
        System.out.println(res); // HTTP 400 :: Body required

        // Unknown route → NotFound
        Request unknown = new Request("GET", "/nope", "secret", null);
        ctx = new Context(); res = new Response();
        chain.proceed(unknown, res, ctx);
        System.out.println(res); // HTTP 404 :: Not Found: GET /nope
    }
}
```

**Notes**

-   Each handler is **single-purpose** and composable.

-   `boolean` return controls **propagation**. You can invert semantics (e.g., return `handled` vs `continue`).

-   The **fallback** handler ensures a request never silently vanishes.


### Async/Reactive Variant (sketch)

If handlers perform I/O, prefer an async signature (e.g., `CompletionStage<Boolean> handleAsync(...)`) and chain with `thenCompose`. In reactive frameworks, handlers can return a `Mono<Response>`/`Flow.Publisher<Response>` and compose with operators.

## Known Uses

-   **Servlet Filters** and **Spring HandlerInterceptors/Filter chains**.

-   **Netty ChannelPipeline**.

-   **Logging frameworks** (appenders/filters).

-   **Middleware** stacks (Express.js, ASP.NET Core pipeline—conceptually similar).

-   **GUI event handling** bubbling up widget hierarchies.


## Related Patterns

-   **Decorator**: wraps to add responsibilities, but always handles; CoR may **choose** to handle or pass along.

-   **Mediator**: centralizes communication; CoR distributes it along a path.

-   **Observer**: notifies multiple listeners; in CoR, handlers are **ordered** and may **short-circuit**.

-   **Command**: requests are often encapsulated as Commands and **routed via** a chain.

-   **Strategy**: a single interchangeable algorithm; CoR is **sequencing/multiplexing** of potential handlers.

-   **Pipeline**/**Interceptor**: close cousins; pipelines typically process **all** stages, while CoR often stops at the **first** suitable handler.
