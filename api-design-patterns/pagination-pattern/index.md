# Pagination — API Design Pattern

## Pattern Name and Classification

**Pagination** — *API design / data access* pattern for retrieving large collections in **bounded chunks** (pages) with **stable ordering** and **navigational tokens**.

---

## Intent

Limit response size and round-trips by returning **partial lists** with **navigation metadata** (offset/limit or cursor tokens), ensuring predictable traversal and performance.

---

## Also Known As

-   **Paging**

-   **Offset Pagination** (`page`/`size`, `offset`/`limit`)

-   **Cursor / Keyset Pagination** (`after`/`before` tokens)


---

## Motivation (Forces)

-   Collections can be **huge**; returning everything is slow/expensive.

-   UIs need **infinite scroll**, **“Load more”**, or **table pages**.

-   **Offset** is simple but suffers from **skew** and **O(n) count/offset** cost.

-   **Cursor** (keyset) is resilient to inserts/deletes and provides **stable, fast** navigation.


---

## Applicability

Use pagination when:

-   Lists can exceed a few dozen items.

-   You need **consistent ordering**, **bounded payloads**, and **stateless** navigation.


Prefer **cursor (keyset)** when:

-   Data changes frequently; **stable ordering** matters; performance at scale.


Prefer **offset** when:

-   You must **jump to arbitrary pages** or integrate with existing SQL **OFFSET**\-based UIs.


---

## Structure

```bash
GET /orders?limit=20&after=eyJrZXkiOiIyMDI1LTA5LTI5VDEyOj..."}  → page of items
Response:
{
  "items": [ ... ],
  "page": { "limit":20, "nextCursor":"...", "prevCursor":"...", "count": null }
}
Headers (optional): Link: <...after=...>; rel="next"
Ordering: by (created_at DESC, id DESC)
```

---

## Participants

-   **Client/UI**: Renders and requests next/previous pages.

-   **API**: Accepts `limit`, `after`/`before` (cursor) or `offset`/`page`, returns items + metadata.

-   **Store/Service**: Applies **ordered** queries with **stable sort keys**.


---

## Collaboration

1.  Client requests first page (no cursor).

2.  API returns items + **nextCursor**; client uses it to fetch more.

3.  Optionally supports **prevCursor** for backwards navigation.

4.  Offset flow is analogous with `offset` and `limit`.


---

## Consequences

**Benefits**

-   Predictable latency; smaller payloads.

-   Cursor pagination avoids **missing/duplicated rows** when data changes.

-   Works well with **infinite scroll** and mobile networks.


**Liabilities**

-   Offset can be **slow** at high offsets and can **skip/duplicate** under churn.

-   Cursor requires generating **opaque tokens** and **stable ordering**.

-   Counting total rows can be **expensive**.


---

## Implementation (Key Points)

-   Choose ordering by **immutable/monotonic** keys (e.g., `(created_at desc, id desc)`).

-   Encode cursor as **opaque** (e.g., Base64 JSON of the last item’s sort keys).

-   Enforce **max page size** (defensive; e.g., 100).

-   Optionally provide **Link** headers (`rel="next"`/`prev"`).

-   For offset: add indexes for the sort; beware of `OFFSET N` cost.

-   Expose **deterministic** filters and sorting; document defaults.

-   Consider **count** optional or async (expensive on big tables).


---

## Sample Code (Java, Spring Boot — Cursor + Offset)

**Gradle (snippets)**

```gradle
implementation "org.springframework.boot:spring-boot-starter-web"
implementation "com.fasterxml.jackson.core:jackson-databind"
```

### DTOs

```java
package demo.pagination;

import java.time.Instant;
import java.util.List;

public record Order(String id, Instant createdAt, String status) {}

public record PageMeta(
    Integer limit,
    String nextCursor,
    String prevCursor,
    Integer count // nullable; omit if expensive
) {}

public record PageResponse<T>(List<T> items, PageMeta page) {}
```

### Cursor Codec (opaque Base64)

```java
package demo.pagination;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.Map;

class CursorCodec {
  private static final ObjectMapper MAPPER = new ObjectMapper();

  static String encode(Instant createdAt, String id) {
    try {
      var json = MAPPER.writeValueAsBytes(Map.of(
          "createdAt", createdAt.toString(),
          "id", id
      ));
      return Base64.getUrlEncoder().withoutPadding().encodeToString(json);
    } catch (Exception e) { throw new RuntimeException(e); }
  }

  static Cursor decode(String cursor) {
    try {
      var json = new String(Base64.getUrlDecoder().decode(cursor), StandardCharsets.UTF_8);
      var map = MAPPER.readValue(json, Map.class);
      return new Cursor(Instant.parse((String) map.get("createdAt")), (String) map.get("id"));
    } catch (Exception e) { throw new IllegalArgumentException("Invalid cursor", e); }
  }

  record Cursor(Instant createdAt, String id) {}
}
```

### In-Memory Repository (ordered by createdAt desc, id desc)

*(Replace with DB queries using `WHERE (created_at,id) < (:createdAt,:id)` for next page.)*

```java
package demo.pagination;

import org.springframework.stereotype.Repository;

import java.time.Instant;
import java.util.*;
import java.util.stream.Collectors;

@Repository
class OrderRepo {
  private final List<Order> data = new ArrayList<>();

  OrderRepo() {
    // demo dataset
    for (int i = 1; i <= 120; i++) {
      data.add(new Order("o-%03d".formatted(i),
          Instant.parse("2025-09-29T12:00:00Z").minusSeconds(i * 60L),
          (i % 3 == 0) ? "SHIPPED" : "NEW"));
    }
    data.sort(Comparator.<Order, Instant>comparing(Order::createdAt).reversed()
        .thenComparing(Order::id, Comparator.reverseOrder()));
  }

  List<Order> firstPage(int limit) {
    return data.stream().limit(limit).collect(Collectors.toList());
  }

  List<Order> after(Instant createdAt, String id, int limit) {
    // keyset: items strictly “less” than the cursor in (createdAt desc, id desc)
    return data.stream()
        .filter(o -> o.createdAt().isBefore(createdAt)
            || (o.createdAt().equals(createdAt) && o.id().compareTo(id) < 0))
        .limit(limit)
        .collect(Collectors.toList());
  }

  List<Order> offset(int offset, int limit) {
    if (offset >= data.size()) return List.of();
    return data.subList(offset, Math.min(offset + limit, data.size()));
  }

  int count() { return data.size(); }
}
```

### Service (build PageResponse with cursors)

```java
package demo.pagination;

import org.springframework.stereotype.Service;
import java.util.List;

@Service
class OrderPagingService {
  private static final int MAX_LIMIT = 100;
  private final OrderRepo repo;

  OrderPagingService(OrderRepo repo) { this.repo = repo; }

  PageResponse<Order> listCursor(Integer limit, String after, String before) {
    int lim = normalize(limit);
    List<Order> items;
    String prev = null;

    if (before != null) {
      // Simple prev implementation: reverse traversal could be implemented by inverted comparison.
      var c = CursorCodec.decode(before);
      // For demo, emulate "previous page" by getting items greater than the cursor then taking last 'lim'.
      items = repo.firstPage(repo.count()); // not optimal; DB should do an inverted keyset
      items = items.stream()
          .filter(o -> o.createdAt().isAfter(c.createdAt())
              || (o.createdAt().equals(c.createdAt()) && o.id().compareTo(c.id()) > 0))
          .limit(lim)
          .toList();
    } else if (after != null) {
      var c = CursorCodec.decode(after);
      items = repo.after(c.createdAt(), c.id(), lim);
    } else {
      items = repo.firstPage(lim);
    }

    String next = items.isEmpty() ? null
        : CursorCodec.encode(items.get(items.size()-1).createdAt(), items.get(items.size()-1).id());
    return new PageResponse<>(items, new PageMeta(lim, next, prev, null));
  }

  PageResponse<Order> listOffset(Integer offset, Integer limit, boolean includeCount) {
    int off = offset == null || offset < 0 ? 0 : offset;
    int lim = normalize(limit);
    var items = repo.offset(off, lim);
    Integer count = includeCount ? repo.count() : null;
    return new PageResponse<>(items, new PageMeta(lim, null, null, count));
  }

  private int normalize(Integer limit) {
    int lim = (limit == null || limit <= 0) ? 20 : limit;
    return Math.min(lim, MAX_LIMIT);
  }
}
```

### Controller (cursor + offset endpoints, Link headers)

```java
package demo.pagination;

import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/orders")
class OrderController {
  private final OrderPagingService svc;

  OrderController(OrderPagingService svc) { this.svc = svc; }

  // Cursor-style
  @GetMapping
  public ResponseEntity<PageResponse<Order>> listCursor(
      @RequestParam(required = false) Integer limit,
      @RequestParam(required = false) String after,
      @RequestParam(required = false) String before) {

    var page = svc.listCursor(limit, after, before);

    HttpHeaders h = new HttpHeaders();
    if (page.page().nextCursor() != null) {
      h.add(HttpHeaders.LINK, String.format("</orders?limit=%d&after=%s>; rel=\"next\"",
          page.page().limit(), page.page().nextCursor()));
    }
    if (page.page().prevCursor() != null) {
      h.add(HttpHeaders.LINK, String.format("</orders?limit=%d&before=%s>; rel=\"prev\"",
          page.page().limit(), page.page().prevCursor()));
    }
    return ResponseEntity.ok().headers(h).body(page);
  }

  // Offset-style (optional)
  @GetMapping("/offset")
  public PageResponse<Order> listOffset(
      @RequestParam(defaultValue = "0") Integer offset,
      @RequestParam(defaultValue = "20") Integer limit,
      @RequestParam(defaultValue = "false") boolean includeCount) {
    return svc.listOffset(offset, limit, includeCount);
  }
}
```

### Example Responses

**Cursor (first page)**  
`GET /orders?limit=5`

```json
{
  "items": [
    {"id":"o-120","createdAt":"2025-09-29T10:00:00Z","status":"NEW"},
    {"id":"o-119","createdAt":"2025-09-29T10:01:00Z","status":"SHIPPED"},
    ...
  ],
  "page": { "limit": 5, "nextCursor":"eyJjcmVhdGVkQXQiOiIyMDI1L...","prevCursor":null,"count":null }
}
```

`Link: </orders?limit=5&after=eyJjcm...>; rel="next"`

**Offset**  
`GET /orders/offset?offset=20&limit=10&includeCount=true`

```json
{
  "items":[ ... 10 items ... ],
  "page": { "limit":10, "nextCursor":null, "prevCursor":null, "count":120 }
}
```

---

## Known Uses

-   **GitHub REST** (cursor & offset in different endpoints), **Twitter API v2** (tokens), **Stripe**, **Shopify**, most large SaaS APIs and databases (keyset pagination in SQL: `WHERE (created_at,id) < (?, ?)`).


---

## Related Patterns

-   **Keyset (Seek) Pagination** — underlying SQL technique for cursors.

-   **HATEOAS** — provide `next`/`prev` links in responses.

-   **GraphQL Connections** — Relay-style `edges`/`pageInfo`.

-   **Rate Limiting** — pair with small `limit` to control load.

-   **Caching / ETags** — cache individual pages safely.

-   **Sorting** — define stable sort keys; expose sort options carefully.
