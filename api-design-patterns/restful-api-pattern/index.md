# RESTful API — API Design Pattern

## Pattern Name and Classification

**RESTful API** — *Resource-oriented* HTTP API design pattern grounded in **Representational State Transfer** constraints (client–server, stateless, cacheable, layered system, uniform interface, hypermedia).

---

## Intent

Expose **resources** with **stable identifiers (URIs)** and manipulate them using **standard HTTP methods** (GET/POST/PUT/PATCH/DELETE), semantics, status codes, caching, and content negotiation.

---

## Also Known As

-   **Resource-Oriented Architecture (ROA)**

-   **HTTP/REST APIs**

-   **CRUD over HTTP** (colloquial; REST is broader)


---

## Motivation (Forces)

-   Interop via ubiquitous HTTP + media types.

-   Predictable semantics: **GET is safe**, **PUT/PATCH is idempotent/partial**, **DELETE is idempotent**, **POST creates or triggers actions**.

-   Need **evolvable** APIs (versioning, content negotiation) and **performance** (caching, ETags).

-   Desire **discoverability** via links (HATEOAS optional/pragmatic).


---

## Applicability

Use when:

-   You expose **public/partner/internal** APIs for general consumption.

-   Human/web tooling friendliness and **cacheability** matter.

-   You can model the domain as **resources & relationships**.


Avoid/limit when:

-   You need **low-latency binary streaming** or **strict contracts/codegen** across polyglot (consider **gRPC**).

-   Client-defined shapes/field selection dominate (consider **GraphQL**).


---

## Structure

```bash
/orders                ← collection
/orders/{id}           ← resource
/orders/{id}/items     ← sub-resource
GET/POST/PUT/PATCH/DELETE + Status Codes + Headers (ETag, Cache-Control, Link)
Representations: application/json (versioned via vendor media type)
```

---

## Participants

-   **Client** — issues HTTP requests, follows links, honors caching.

-   **API** — routes, validates, authorizes, executes, returns proper codes/headers.

-   **Representations** — JSON (or others) with optional hypermedia links.

-   **Caches** — CDN/proxy/client honoring `Cache-Control`, `ETag`, `Last-Modified`.


---

## Collaboration

1.  Client `GET /orders?limit=20` → server returns list + paging links/headers.

2.  Client `POST /orders` → `201 Created` + `Location` + body.

3.  Client `PUT /orders/{id}` (full replace) or `PATCH` (partial) with **idempotency key** for safety.

4.  Client uses `If-None-Match` / `If-Match` for caching & optimistic concurrency.


---

## Consequences

**Benefits**

-   Standardized semantics & tooling, easy adoption.

-   **Cache-friendly**, evolvable, debuggable with curl.

-   Decouples clients via **uniform interface**.


**Liabilities**

-   Over/under-fetch risk for complex UIs (mitigate with expansion params, embedding, BFFs).

-   Verbose JSON and chattiness across many resources (mitigate with **API Composition**, pagination, compression).

-   Strict REST purity can be heavy; pragmatic REST is common.


---

## Implementation (Key Points)

-   **Resource modeling** first; nouns for URIs; actions as sub-resources only when needed (`/orders/{id}:cancel` as POST).

-   Use **proper status codes** (200/201/202/204/304/400/401/403/404/409/412/415/422/429/5xx).

-   **Pagination** (cursor or offset) + `Link` headers.

-   **Caching**: `ETag` + `If-None-Match`; **optimistic locking** with `If-Match`.

-   **Versioning**: media type (`Accept: application/vnd.acme.v1+json`) or URI (`/v1/...`).

-   **Errors**: machine-readable problem details (`application/problem+json`).

-   **Security**: OAuth2/OIDC (Bearer), scopes per route.

-   **Validation**: RFC 7807 + field errors.

-   **Idempotency-Key** for non-idempotent POSTs.


---

## Sample Code (Java, Spring Boot — REST with ETags, pagination, problem details)

**Gradle (snippets)**

```gradle
implementation "org.springframework.boot:spring-boot-starter-web"
implementation "com.fasterxml.jackson.core:jackson-databind"
```

**DTOs**

```java
package demo.rest;

import java.time.Instant;
import java.util.List;

public record Order(String id, String status, Instant createdAt, List<String> items, long version) {}
public record CreateOrderRequest(List<String> items) {}
public record UpdateOrderRequest(String status, List<String> items) {}

public record PageMeta(Integer limit, String nextCursor) {}
public record PageResponse<T>(List<T> items, PageMeta page) {}

public record Problem(String type, String title, int status, String detail) {}
```

**In-Memory Repo (optimistic locking by `version`)**

```java
package demo.rest;

import org.springframework.stereotype.Repository;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

@Repository
class OrderRepo {
  private final Map<String, Order> db = new ConcurrentHashMap<>();

  Order saveNew(List<String> items) {
    String id = UUID.randomUUID().toString();
    Order o = new Order(id, "NEW", Instant.now(), List.copyOf(items), 1);
    db.put(id, o); return o;
  }
  Optional<Order> find(String id) { return Optional.ofNullable(db.get(id)); }
  List<Order> list(int limit, String afterId) {
    var list = new ArrayList<>(db.values());
    list.sort(Comparator.comparing(Order::createdAt).reversed().thenComparing(Order::id).reversed());
    if (afterId != null) {
      int idx = -1;
      for (int i=0; i<list.size(); i++) if (list.get(i).id().equals(afterId)) { idx=i; break; }
      list = (idx >= 0 && idx+1 < list.size()) ? new ArrayList<>(list.subList(idx+1, list.size())) : new ArrayList<>();
    }
    return list.subList(0, Math.min(limit, list.size()));
  }
  Order replace(Order current, UpdateOrderRequest body, long ifMatch) {
    if (current.version() != ifMatch) throw new ConcurrentModificationException();
    long nextV = current.version()+1;
    Order upd = new Order(current.id(),
        body.status() != null ? body.status() : current.status(),
        current.createdAt(),
        body.items() != null ? List.copyOf(body.items()) : current.items(),
        nextV);
    db.put(upd.id(), upd); return upd;
  }
}
```

**ETag Helper**

```java
package demo.rest;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Base64;

class Etags {
  static String quote(String s) { return "\"" + s + "\""; }
  static String from(Order o) {
    try {
      var md = MessageDigest.getInstance("SHA-256");
      md.update((o.id()+":"+o.version()).getBytes(StandardCharsets.UTF_8));
      return quote(Base64.getUrlEncoder().withoutPadding().encodeToString(md.digest()));
    } catch (Exception e) { return "\"0\""; }
  }
}
```

**Controller**

```java
package demo.rest;

import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import java.net.URI;
import java.util.List;
import java.util.ConcurrentModificationException;

@RestController
@RequestMapping(value="/orders", produces=MediaType.APPLICATION_JSON_VALUE)
class OrderController {

  private final OrderRepo repo;
  OrderController(OrderRepo repo) { this.repo = repo; }

  // List with simple cursor (after=id)
  @GetMapping
  ResponseEntity<PageResponse<Order>> list(
      @RequestParam(defaultValue="20") int limit,
      @RequestParam(required=false) String after) {
    int lim = Math.min(Math.max(limit, 1), 100);
    var items = repo.list(lim, after);
    var nextCursor = items.isEmpty() ? null : items.get(items.size()-1).id();
    var page = new PageResponse<>(items, new PageMeta(lim, nextCursor));

    HttpHeaders h = new HttpHeaders();
    if (nextCursor != null) {
      h.add(HttpHeaders.LINK, String.format("</orders?limit=%d&after=%s>; rel=\"next\"", lim, nextCursor));
    }
    return ResponseEntity.ok().headers(h).body(page);
  }

  // Get with ETag / conditional GET
  @GetMapping("/{id}")
  ResponseEntity<Order> get(@PathVariable String id,
                            @RequestHeader(value="If-None-Match", required=false) String inm) {
    var o = repo.find(id).orElseThrow(() -> new NotFoundException("order not found"));
    var etag = Etags.from(o);
    if (etag.equals(inm)) return ResponseEntity.status(HttpStatus.NOT_MODIFIED).eTag(etag).build();
    return ResponseEntity.ok().eTag(etag).cacheControl(CacheControl.noCache()).body(o);
  }

  // Create (POST) → 201 + Location
  @PostMapping(consumes=MediaType.APPLICATION_JSON_VALUE)
  ResponseEntity<Order> create(@RequestBody CreateOrderRequest req) {
    if (req.items() == null || req.items().isEmpty())
      return problem(422, "Unprocessable Entity", "items must not be empty");
    var o = repo.saveNew(req.items());
    return ResponseEntity.created(URI.create("/orders/" + o.id()))
        .eTag(Etags.from(o))
        .body(o);
  }

  // Update (PUT for replace / PATCH for partial; here PUT-like semantics with If-Match)
  @PatchMapping(value="/{id}", consumes=MediaType.APPLICATION_JSON_VALUE)
  ResponseEntity<Order> update(@PathVariable String id,
                               @RequestHeader("If-Match") String ifMatch,
                               @RequestBody UpdateOrderRequest body) {
    var o = repo.find(id).orElseThrow(() -> new NotFoundException("order not found"));
    long v;
    try { v = Long.parseLong(ifMatch.replace("\"","")); } catch (Exception e) { return problem(428, "Precondition Required", "Provide If-Match version"); }
    try {
      var upd = repo.replace(o, body, v);
      return ResponseEntity.ok().eTag(Etags.from(upd)).body(upd);
    } catch (ConcurrentModificationException ex) {
      return problem(412, "Precondition Failed", "Version mismatch");
    }
  }

  // Minimal RFC7807 helper
  private ResponseEntity<Order> problem(int code, String title, String detail) {
    var p = new Problem("about:blank", title, code, detail);
    return ResponseEntity.status(code)
        .contentType(MediaType.valueOf("application/problem+json"))
        .header(HttpHeaders.CACHE_CONTROL, "no-store")
        .body(null);
  }

  @ResponseStatus(HttpStatus.NOT_FOUND)
  static class NotFoundException extends RuntimeException {
    NotFoundException(String m){ super(m); }
  }
}
```

**Usage highlights**

-   `GET /orders` returns page + `Link: rel="next"`.

-   `GET /orders/{id}` supports `If-None-Match` (304).

-   `POST /orders` returns `201 Created` + `Location`.

-   `PATCH /orders/{id}` requires `If-Match` (optimistic concurrency → `412` on mismatch).

-   Errors return **problem details** media type (simplified here).


---

## Known Uses

-   Practically every public SaaS API (GitHub, Stripe, Shopify, etc.) and most internal enterprise services use REST with pragmatic choices (pagination, ETags, problem+json, OAuth2).


---

## Related Patterns

-   **HATEOAS/Hypermedia** — add links & actions to guide clients.

-   **Pagination** — bounded lists and navigation tokens.

-   **Idempotency Key** — safe retries for POST.

-   **API Gateway / BFF** — edge shaping, auth, rate limits.

-   **API Composition** — aggregate multiple resources for view endpoints.

-   **GraphQL** — alternative for client-defined shapes; can coexist behind the same domain.
