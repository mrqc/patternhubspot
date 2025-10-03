# Hypermedia — API Design Pattern

## Pattern Name and Classification

**Hypermedia** — *REST maturity / Runtime navigation & affordances* pattern.

---

## Intent

Represent **resources plus controls** (links, actions, forms) so clients can **discover valid next steps at runtime** and navigate workflows **without hard-coded URLs or flow logic**.

---

## Also Known As

-   **Hypermedia Controls / Affordances**

-   **REST Level 3 (Richardson Maturity Model)**

-   **HATEOAS (when emphasized as the runtime driver)**


---

## Motivation (Forces)

-   Decouple clients from **URL schemas** and **server workflows**.

-   Allow **evolution** (renames, splits, migrations) behind stable **link relations**.

-   Encode **state-dependent actions** (only show `cancel` when order is `NEW`).

-   Make APIs **self-describing** and **discoverable**.


Tensions: payload overhead; client libraries must **follow links**; choice of media type (HAL, JSON:API, Siren) and **link-rel taxonomy**.

---

## Applicability

Use when:

-   Clients are **long-lived**, third-party, or multiple channels with varied release cycles.

-   Workflows change and should be **server-driven**.

-   You want machine-readable **capabilities** and **navigation**.


Avoid / limit when:

-   You fully control clients and paths are stable; bandwidth is extremely constrained; or you need **heavy CDN URL caching** with zero body parsing.


---

## Structure

```swift
GET /orders/42
{
  "id": "42",
  "status": "NEW",
  "_links": {
    "self":   { "href": "/orders/42" },
    "items":  { "href": "/orders/42/items" },
    "cancel": { "href": "/orders/42/cancel", "method": "POST" }
  },
  "_embedded": { ...optional related resources... }
}
```

Key elements: **resource state**, **links (rels → href, type, method)**, optional **forms/affordances** and **embedded** expansions.

---

## Participants

-   **Server** builds representations with links/affordances based on **state & auth**.

-   **Client** follows **link relations** rather than constructing URLs.

-   **Media Type / Conventions**: HAL, Siren, JSON:API, Collection+JSON, ALPS.

-   **Link-Relations Registry**: IANA registered rels + documented custom rels.


---

## Collaboration

1.  Client fetches an **entry point** or collection.

2.  Parses **links** and optional **forms**; chooses the next relation.

3.  Performs the indicated method/target; repeats, guided by returned affordances.


---

## Consequences

**Benefits**

-   **Looser coupling**, safer refactors; **discoverability** and **self-documentation**.

-   Encodes **valid transitions** and **capabilities** in responses.


**Liabilities**

-   More code to assemble links; slightly larger payloads.

-   Requires **hypermedia-aware** client behavior and testing.

-   Coordination on **rels** and media type conventions.


---

## Implementation (Key Points)

-   Pick a convention (**HAL** is pragmatic with Spring HATEOAS; **Siren** if you want forms/actions).

-   Define and document **canonical rels** (prefer IANA; prefix custom rels).

-   Use **assemblers** to add links; generate **conditional links** from state/permissions.

-   Provide an **API root** with link index; support **content negotiation** if needed.

-   Treat links as **contract**; version only when semantics change.


---

## Sample Code (Java — Spring Boot + Spring HATEOAS, HAL)

**Gradle (snippets)**

```gradle
implementation "org.springframework.boot:spring-boot-starter-web"
implementation "org.springframework.boot:spring-boot-starter-hateoas"
implementation "com.fasterxml.jackson.core:jackson-databind"
```

**Domain**

```java
package demo.hypermedia;

public record Order(String id, String status) {
  public boolean cancellable() { return "NEW".equals(status); }
}
```

**Controller + Assembler**

```java
package demo.hypermedia;

import org.springframework.hateoas.*;
import org.springframework.hateoas.server.RepresentationModelAssembler;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.*;
import static org.springframework.hateoas.server.mvc.WebMvcLinkBuilder.*;

@RestController
@RequestMapping("/orders")
class OrderController {

  private final Map<String, Order> db = new LinkedHashMap<>();

  OrderController() {
    db.put("42", new Order("42", "NEW"));
    db.put("43", new Order("43", "SHIPPED"));
  }

  @GetMapping("/{id}")
  public EntityModel<Order> get(@PathVariable String id) {
    Order o = Optional.ofNullable(db.get(id)).orElseThrow(() -> new NoSuchElementException("order not found"));
    return new OrderModelAssembler().toModel(o);
  }

  @GetMapping
  public CollectionModel<EntityModel<Order>> list() {
    var assembler = new OrderModelAssembler();
    var models = db.values().stream().map(assembler::toModel).toList();
    return CollectionModel.of(models, linkTo(methodOn(OrderController.class).list()).withSelfRel());
  }

  @PostMapping("/{id}/cancel")
  public ResponseEntity<?> cancel(@PathVariable String id) {
    Order o = db.get(id);
    if (o == null) return ResponseEntity.notFound().build();
    if (!o.cancellable()) return ResponseEntity.status(409).body("Cannot cancel");
    db.put(id, new Order(id, "CANCELLED"));
    return ResponseEntity.noContent().build();
  }

  static final class OrderModelAssembler implements RepresentationModelAssembler<Order, EntityModel<Order>> {
    @Override
    public EntityModel<Order> toModel(Order o) {
      EntityModel<Order> model = EntityModel.of(o);
      model.add(linkTo(methodOn(OrderController.class).get(o.id())).withSelfRel());
      model.add(linkTo(methodOn(OrderController.class).list()).withRel("collection"));
      if (o.cancellable()) {
        model.add(linkTo(methodOn(OrderController.class).cancel(o.id()))
            .withRel("cancel")
            .withType("POST"));
      }
      return model;
    }
  }
}
```

**Entry Point (link index)**

```java
@RestController
class ApiRootController {
  @GetMapping("/")
  RepresentationModel<?> root() {
    RepresentationModel<?> m = new RepresentationModel<>();
    m.add(linkTo(OrderController.class).withRel("orders"));
    return m;
  }
}
```

**Example Response (`GET /orders/42`)**

```json
{
  "id": "42",
  "status": "NEW",
  "_links": {
    "self": { "href": "http://localhost:8080/orders/42" },
    "collection": { "href": "http://localhost:8080/orders" },
    "cancel": { "href": "http://localhost:8080/orders/42/cancel", "type": "POST" }
  }
}
```

*Notes:*

-   For richer **actions/forms**, consider **Siren**: actions with `method`, `fields`, `type`.

-   Add **auth-aware links** (omit links user isn’t authorized for).

-   Integrate **ETags** and **cache** headers; links are still valid across versions if rel semantics are stable.


---

## Known Uses

-   Enterprises exposing HAL/JSON:API/Siren for internal/external REST; **PayPal**, **Amazon** (internal), and many public APIs provide hypermedia hints or full hypermedia responses.


---

## Related Patterns

-   **HATEOAS** — the principle that hypermedia drives state transitions.

-   **API Gateway / BFF** — often shapes hypermedia per client.

-   **API Composition** — links can stitch aggregated resources.

-   **Content Negotiation / Versioning** — evolve formats and link semantics.

-   **Consumer-Driven Contracts** — verify presence/shape of links and actions.

-   **GraphQL** — alternative: schema-driven querying vs link-driven navigation.
