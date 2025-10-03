# Chain of Responsibility — Behavioral / Process Pattern

## Pattern Name and Classification

**Chain of Responsibility (CoR)** — *Behavioral / Process* pattern for **decoupling senders from receivers** by passing a request along a **chain of handlers** until one handles it (or all pass).

---

## Intent

Let multiple handlers **process, transform, or decide** on a request **without the sender knowing which one** will handle it. Support **short-circuiting**, **fallback**, and **extensible pipelines**.

---

## Also Known As

-   **Pipeline** (close kin in integration/ETL)

-   **Middleware Chain** (web frameworks)

-   **Filter Chain / Interceptor Chain**


---

## Motivation (Forces)

-   You want to add/remove behaviors (auth, rate limiting, logging, validation, business rules) **without editing the caller**.

-   Ordering and **short-circuit** logic (e.g., reject unauthorized early) matters.

-   Many potential handlers, but typically **only a few will act** per request.

-   You need to avoid **giant if/else** blocks or **hardcoded coupling**.


Trade-offs:

-   Too many handlers → latency/complexity.

-   Ordering can be subtle; debugging requires **good tracing**.

-   Global state or side effects can make behavior non-obvious—prefer **immutable requests** or a scoped **context**.


---

## Applicability

Use CoR when:

-   There are **several candidate** processors for a request.

-   You need a **pluggable pipeline** (e.g., HTTP middleware, message pre-processors).

-   Handlers may **transform** the request/response or **stop propagation**.


Avoid when:

-   Exactly **one known** component must handle the request → use direct dispatch or **Strategy**.

-   Handler order cannot vary and the chain adds no value.


---

## Structure

```pgsql
Client → [Handler A] → [Handler B] → [Handler C] → … 
              |            |            |
           (handle?)    (pass on)    (stop / return)
```

-   Each handler knows **how to do one thing** and whether to **delegate** to the next.


---

## Participants

-   **Handler**: Declares `handle(request, chain)` (or `setNext`). May stop or continue.

-   **Concrete Handlers**: Auth, validation, rate-limit, enrichment, routing, etc.

-   **Chain**: Maintains the ordered list and invokes the next handler.

-   **Request/Context**: Input + per-request metadata; may carry a **Response**.


---

## Collaboration

1.  Client submits a request to the **chain entry**.

2.  Each handler decides to **handle** (possibly producing a result) or **delegate** to the next.

3.  Any handler can **short-circuit** with a result (e.g., 401/429) or **augment** and pass along.

4.  Final result bubbles back to the client.


---

## Consequences

**Benefits**

-   **Open/Closed**: add handlers without changing clients.

-   **Separation of concerns**; test handlers in isolation.

-   **Reusability**: compose different chains per product/tenant.


**Liabilities**

-   **Ordering** matters; mis-ordering causes bugs.

-   **Observability** is essential (logs/traces).

-   Possible **overhead** for long chains.


---

## Implementation (Key Points)

-   Prefer a **small, typed Request/Response** and an immutable input with a mutable **Context** for side-effects.

-   Support **short-circuit** returns (e.g., Optional/Result/Either).

-   Provide a **builder** to assemble chains declaratively.

-   Add **tracing + timing** handlers for debuggability.

-   For async/reactive stacks, make handlers return `CompletionStage`/`Mono` and chain accordingly.

-   Distinguish **pre**, **around**, **post** phases if you need before/after behavior (Interceptor flavor).


---

## Sample Code (Java 17, synchronous; easy to adapt to reactive)

> Scenario: Process an incoming `Request` through **Auth → RateLimit → Validation → Handler**.  
> Any step can **short-circuit** with an error `Response`.

```java
// Request/Response models
record Request(String userId, String path, String method, String body) {}
record Response(int status, String message) {
  static Response ok(String msg) { return new Response(200, msg); }
  static Response unauthorized() { return new Response(401, "Unauthorized"); }
  static Response tooMany() { return new Response(429, "Too Many Requests"); }
  static Response badRequest(String msg) { return new Response(400, msg); }
}

// Chain SPI
interface Handler {
  Response handle(Request req, Chain chain);

  interface Chain {
    Response proceed(Request req);
  }
}

// Chain implementation
final class HandlerChain implements Handler.Chain {
  private final java.util.List<Handler> handlers;
  private int index = 0;

  HandlerChain(java.util.List<Handler> handlers) {
    this.handlers = handlers;
  }

  @Override
  public Response proceed(Request req) {
    if (index >= handlers.size()) {
      // default fall-through if nobody handled
      return new Response(404, "Not handled");
    }
    Handler next = handlers.get(index++);
    return next.handle(req, this);
  }
}

// Concrete handlers

// 1) Authentication — short-circuit if user missing
class AuthHandler implements Handler {
  @Override public Response handle(Request req, Chain chain) {
    if (req.userId() == null || req.userId().isBlank()) {
      return Response.unauthorized();
    }
    return chain.proceed(req);
  }
}

// 2) Rate limiting (demo, per-user in-memory token bucket)
class RateLimitHandler implements Handler {
  private static final java.util.Map<String, Bucket> buckets = new java.util.concurrent.ConcurrentHashMap<>();

  @Override public Response handle(Request req, Chain chain) {
    var b = buckets.computeIfAbsent(req.userId(), k -> new Bucket(10, 5)); // cap 10, refill 5/min
    if (!b.tryConsume(1)) return Response.tooMany();
    return chain.proceed(req);
  }

  static final class Bucket {
    final int capacity;
    final double refillPerSec;
    double tokens;
    long last;

    Bucket(int capacity, int perMinute) {
      this.capacity = capacity;
      this.refillPerSec = perMinute / 60.0;
      this.tokens = capacity;
      this.last = System.nanoTime();
    }
    synchronized boolean tryConsume(int n) {
      refill();
      if (tokens >= n) { tokens -= n; return true; }
      return false;
    }
    void refill() {
      long now = System.nanoTime();
      double delta = (now - last) / 1_000_000_000.0;
      tokens = Math.min(capacity, tokens + delta * refillPerSec);
      last = now;
    }
  }
}

// 3) Validation — ensure body exists for POST-like methods
class ValidationHandler implements Handler {
  @Override public Response handle(Request req, Chain chain) {
    if ("POST".equalsIgnoreCase(req.method()) && (req.body() == null || req.body().isBlank())) {
      return Response.badRequest("Body required");
    }
    return chain.proceed(req);
  }
}

// 4) Business handler — final processing
class BusinessHandler implements Handler {
  @Override public Response handle(Request req, Chain chain) {
    // This handler decides to "handle" and NOT delegate further
    if ("/orders".equals(req.path()) && "POST".equalsIgnoreCase(req.method())) {
      return Response.ok("Order created for user " + req.userId());
    }
    // Not mine → pass along (maybe someone else can handle)
    return chain.proceed(req);
  }
}

// Chain builder utility
final class Chains {
  static Response execute(Request req, Handler... hs) {
    var list = java.util.List.of(hs);
    return new HandlerChain(list).proceed(req);
  }
}

// --- Demo ---
public class App {
  public static void main(String[] args) {
    var req1 = new Request("alice", "/orders", "POST", "{...}");
    var res1 = Chains.execute(req1,
        new AuthHandler(),
        new RateLimitHandler(),
        new ValidationHandler(),
        new BusinessHandler()
    );
    System.out.println(res1.status() + " " + res1.message());

    var req2 = new Request("", "/orders", "POST", "{...}");
    var res2 = Chains.execute(req2, new AuthHandler(), new BusinessHandler());
    System.out.println(res2.status() + " " + res2.message());
  }
}
```

**What to notice**

-   Each handler does **one thing well** and either **handles** or **delegates**.

-   You can **reorder** or **swap** handlers without changing others.

-   The chain **short-circuits** on errors (401/429/400).

-   A real system would add **logging/tracing** (another handler), and persist rate-limit buckets.


> **Reactive variant**: Replace `Response` with `Mono<Response>` and `proceed` with `Mono.defer(() -> next.handle(...))` to compose non-blocking chains.

---

## Known Uses

-   **Java Servlet Filter** / **Spring `HandlerInterceptor`** / **Spring Security filter chain**.

-   **Netty `ChannelPipeline`**, **Undertow Handlers**.

-   **HTTP middleware** stacks (Express/Koa in JS, ASP.NET Core pipeline analog).

-   **Message processing** pipelines (pre-filters, enrichment, routing).


---

## Related Patterns

-   **Interceptor** — similar “around” semantics; often supports before/after in one unit.

-   **Pipeline** — emphasizes staged transformation of data; often fully processes rather than “first who can handle”.

-   **Strategy** — choose one algorithm explicitly; CoR *discovers* who handles.

-   **Decorator** — wraps to add behavior but always forwards; CoR may **stop** forwarding.

-   **Mediator** — centralizes communication; CoR distributes along a path.
