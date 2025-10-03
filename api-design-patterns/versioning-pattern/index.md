# Versioning — API Design Pattern

## Pattern Name and Classification

**Versioning** — *API lifecycle & compatibility* pattern for evolving an API **without breaking existing clients**, by exposing **coexisting versions** and a **deprecation path**.

---

## Intent

Allow the API to **change safely** (fields, shapes, behaviors) while **preserving compatibility** for older consumers, and provide **clear discovery and migration** to newer versions.

---

## Also Known As

-   **API Evolution**

-   **Backward-Compatible Changes**

-   **Media-Type Versioning / URI Versioning / Header Versioning**


---

## Motivation (Forces)

-   APIs live for years; business/UX changes require **new fields and semantics**.

-   Clients cannot all upgrade at once (mobile apps, partners, SDKs).

-   We need **coexistence** of old/new forms, **discoverability** of versions, and **predictable deprecation** (communication, headers, dates).

-   Balance **simplicity** (URI `/v2/...`) vs **purism** (content negotiation with vendor media types).


Tensions:

-   Too many versions → **operational burden**.

-   Incompatible behavior hidden under the same route → **surprises**.

-   Where to put the version? **URI** vs **Header** vs **Media-Type** vs **Namespace fields**.


---

## Applicability

Use when:

-   Your API has **external consumers** or long-lived internal clients.

-   You need to make **breaking changes** or **semantic shifts**.

-   You want a **documented deprecation** runway and telemetry on version usage.


Avoid/limit when:

-   You can maintain **strict backward compatibility** (additive only) and don’t need a version bump yet.

-   The API is **private and co-deployed** with clients (lockstep deploys).


---

## Structure

Common strategies (often combined):

1.  **URI Versioning**

    -   `/v1/orders/{id}` → `/v2/orders/{id}`

    -   Clear & cache/CDN friendly; visible in logs; coexists easily.

2.  **Media-Type Versioning (Content Negotiation)**

    -   `Accept: application/vnd.acme.orders.v2+json`

    -   Keeps stable URIs; expressive per-resource versioning.

3.  **Header Versioning**

    -   `X-API-Version: 2`

    -   Simple, but less cache-friendly; relies on gateway/config.

4.  **Field/Schema Versioning (in-payload)** *(use sparingly)*

    -   Embed `version` or evolve with **tolerant readers**.


**Deprecation signaling (IETF)**

-   `Deprecation: true` and `Sunset: <http-date>` (RFC 8594)

-   `Link: <https://api.example.com/docs/v2>; rel="successor-version"`


---

## Participants

-   **API Provider** — ships multiple versions, emits deprecation metadata, collects usage.

-   **Clients** — pin to a version, migrate on a schedule.

-   **Gateway/CDN** — routes by path/header/media type; caches per version.

-   **Documentation/SDKs** — versioned, aligned with API behavior.


---

## Collaboration

1.  Client calls a **specific version** (URI/header/media-type).

2.  Server routes to the **matching controller/handler** and returns **versioned representation**.

3.  For deprecated versions, server adds **Deprecation/Sunset/Link** headers.

4.  Telemetry reveals usage; provider coordinates **sunset** and removal.


---

## Consequences

**Benefits**

-   Safe evolution; **no surprise breakage**.

-   Fine-grained control of **coexistence** and **migration**.

-   Enables **experimentation** and **incremental redesign**.


**Liabilities**

-   Operational overhead (testing, docs, monitoring **per version**).

-   Risk of **version sprawl**; must have a retirement plan.

-   Cache keys and routing rules become **more complex**.


---

## Implementation (Key Points)

-   Pick one **primary** strategy; support a second only if it brings clear value.

-   Keep **versions few and short-lived**; publish a **deprecation policy** (e.g., 12 months).

-   Emit headers: `Deprecation`, `Sunset`, `Link rel="successor-version"`.

-   Maintain **semantic versioning** in docs/SDKs; **major** for breaking API changes.

-   Provide **compat shims** or **transformers** internally to reduce duplication.

-   Instrument **per-version metrics**; block new apps from old versions after a date.

-   Use **contract tests** and **CDC** to verify each version.


---

## Sample Code (Java, Spring Boot)

The example shows **three** versioning schemes side-by-side for clarity:

-   **URI**: `/v1/orders/{id}` and `/v2/orders/{id}`

-   **Header**: `X-API-Version: 1|2` on `/orders/{id}`

-   **Media-Type**: `Accept: application/vnd.acme.orders.v1+json|v2+json` on `/orders/{id}`


> In production pick **one** primary scheme (URI or media-type are most common).

### Gradle (snippets)

```gradle
implementation "org.springframework.boot:spring-boot-starter-web"
implementation "com.fasterxml.jackson.core:jackson-databind"
```

### DTOs (V1 vs V2)

```java
package demo.versioning;

import java.time.Instant;
import java.util.List;

public record OrderV1(String id, String status, List<String> items) {}
public record OrderV2(String id, String state, List<LineItem> items, Instant createdAt) {
  public record LineItem(String sku, int qty) {}
}
```

### Simple Repository (one canonical model → mapped to versioned DTOs)

```java
package demo.versioning;

import org.springframework.stereotype.Repository;
import java.time.Instant;
import java.util.List;
import java.util.Map;

@Repository
class OrderRepo {
  record Canon(String id, String status, List<Map<String,Object>> items, Instant createdAt) {}

  Canon find(String id) {
    // demo data
    return new Canon(
      id, "CONFIRMED",
      List.of(Map.of("sku","sku-1","qty",2), Map.of("sku","sku-2","qty",1)),
      Instant.parse("2025-09-29T12:00:00Z")
    );
  }

  OrderV1 toV1(Canon c) {
    var itemNames = c.items().stream().map(m -> (String)m.get("sku")).toList();
    return new OrderV1(c.id(), c.status(), itemNames);
  }

  OrderV2 toV2(Canon c) {
    var lines = c.items().stream()
      .map(m -> new OrderV2.LineItem((String)m.get("sku"), (int)m.get("qty")))
      .toList();
    return new OrderV2(c.id(), c.status(), lines, c.createdAt());
  }
}
```

### 1) URI Versioning Controllers

```java
package demo.versioning;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/v1/orders")
class OrdersV1Controller {
  private final OrderRepo repo;
  OrdersV1Controller(OrderRepo r) { this.repo = r; }

  @GetMapping("/{id}")
  ResponseEntity<OrderV1> get(@PathVariable String id) {
    var dto = repo.toV1(repo.find(id));
    return ResponseEntity.ok()
      .header("Deprecation","true")                             // v1 is deprecated
      .header("Sunset","Wed, 01 Apr 2026 00:00:00 GMT")
      .header("Link","</v2/orders/"+id+">; rel=\"successor-version\"")
      .body(dto);
  }
}

@RestController
@RequestMapping("/v2/orders")
class OrdersV2Controller {
  private final OrderRepo repo;
  OrdersV2Controller(OrderRepo r) { this.repo = r; }

  @GetMapping("/{id}")
  ResponseEntity<OrderV2> get(@PathVariable String id) {
    return ResponseEntity.ok(repo.toV2(repo.find(id)));
  }
}
```

### 2) Header Versioning (same path, different header)

```java
package demo.versioning;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/orders")
class OrdersHeaderVersioningController {
  private final OrderRepo repo;
  OrdersHeaderVersioningController(OrderRepo r) { this.repo = r; }

  @GetMapping(value="/{id}", headers="X-API-Version=1")
  ResponseEntity<OrderV1> getV1(@PathVariable String id) {
    return ResponseEntity.ok()
      .header("Deprecation","true")
      .header("Sunset","Wed, 01 Apr 2026 00:00:00 GMT")
      .header("Link","</orders/"+id+">; rel=\"successor-version\"; title=\"X-API-Version: 2\"")
      .body(repo.toV1(repo.find(id)));
  }

  @GetMapping(value="/{id}", headers="X-API-Version=2")
  ResponseEntity<OrderV2> getV2(@PathVariable String id) {
    return ResponseEntity.ok(repo.toV2(repo.find(id)));
  }
}
```

### 3) Media-Type Versioning (vendor types via `Accept`)

```java
package demo.versioning;

import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/orders")
class OrdersMediaTypeController {
  private final OrderRepo repo;
  OrdersMediaTypeController(OrderRepo r) { this.repo = r; }

  public static final String V1 = "application/vnd.acme.orders.v1+json";
  public static final String V2 = "application/vnd.acme.orders.v2+json";

  @GetMapping(value="/{id}", produces=V1)
  ResponseEntity<OrderV1> getV1(@PathVariable String id) {
    return ResponseEntity.ok()
      .header("Deprecation","true")
      .header("Sunset","Wed, 01 Apr 2026 00:00:00 GMT")
      .header("Link","</orders/"+id+">; rel=\"successor-version\"; type=\""+V2+"\"")
      .contentType(MediaType.valueOf(V1))
      .body(repo.toV1(repo.find(id)));
  }

  @GetMapping(value="/{id}", produces=V2)
  ResponseEntity<OrderV2> getV2(@PathVariable String id) {
    return ResponseEntity.ok()
      .contentType(MediaType.valueOf(V2))
      .body(repo.toV2(repo.find(id)));
  }
}
```

### (Optional) Content Negotiation Tip

If your framework needs hints, configure a `ContentNegotiationStrategy` or ensure your clients send `Accept: application/vnd.acme.orders.v2+json`.

---

## Known Uses

-   **GitHub**: media-type previews → promoted to new versions.

-   **Stripe**: **date-stamped** API versions via headers; per-account pinning.

-   **Google APIs**: **URI-based** versions (e.g., `v1`, `v1beta`).

-   Many enterprises: mix of **URI** for major versions + **minor additive changes** without bump.


---

## Related Patterns

-   **Tolerant Reader** — clients ignore unknown fields to allow additive server changes.

-   **Consumer-Driven Contracts** — verify compatibility for each version/consumer.

-   **Deprecation / Sunset** — lifecycle signaling for old versions.

-   **API Gateway** — routes per version; can rewrite/transform responses for legacy clients.

-   **Pagination / Caching / ETags** — continue to apply per versioned resource.
