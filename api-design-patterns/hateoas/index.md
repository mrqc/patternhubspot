# HATEOAS — API Design Pattern

## Pattern Name and Classification

**HATEOAS (Hypermedia as the Engine of Application State)** — *REST maturity / API navigation & affordances* pattern.

---

## Intent

Expose **hypermedia links and controls** (relations, actions, forms) in responses so that clients can **discover available transitions at runtime** and navigate the API **without hard-coding URIs**.

---

## Also Known As

-   **Hypermedia-Driven REST**

-   **REST Level 3 (Richardson Maturity Model)**

-   **Hypermedia Controls / Affordances**


---

## Motivation (Forces)

-   Reduce client coupling to URL structures and workflow logic.

-   Enable **discoverability**, **evolution** (versioning, URI refactors), and **self-documentation**.

-   Convey **“what can I do next?”** (create, update, cancel) with **typed link relations** and optional **forms**.

-   Support **state-dependent affordances** (e.g., `cancel` present only when order is `NEW`).


Tensions:

-   Extra payload size, link building effort, client libraries.

-   Many clients are accustomed to static REST without hypermedia.

-   Standardization of link relations and forms (HAL vs JSON:API vs Siren vs ALPS/UD).


---

## Applicability

Use HATEOAS when:

-   You need **long-lived clients** resilient to URL changes.

-   Workflows are **stateful** and benefit from server-driven navigation.

-   You want machine-readable **capabilities** and **next steps**.


Avoid/limit when:

-   You control both client & server with short release cycles and stable paths.

-   Extremely tight bandwidth constraints (links add bytes).


---

## Structure

```bash
GET /orders/42
{
  "id": "42",
  "status": "NEW",
  "_links": {
    "self":   { "href": "/orders/42" },
    "cancel": { "href": "/orders/42/cancel", "method": "POST" },
    "items":  { "href": "/orders/42/items" }
  }
}
```

Key elements:

-   **Resource representation**

-   **Links** (relation → target URI, type, method)

-   **Affordances** (optional forms/operations with inputs)


---

## Participants

-   **Server**: Builds representations with links/affordances based on state & auth.

-   **Client**: Follows links/relations instead of hardcoding URIs; interprets forms.

-   **Media Type / Conventions**: HAL, Siren, JSON:API, Collection+JSON, etc.

-   **Link Relations Registry**: IANA rels + custom `urn:rel:` where needed.


---

## Collaboration

1.  Client fetches an **entry point** (e.g., `/` with links to top resources).

2.  Client follows **link relations** (e.g., `orders`, `self`, `cancel`).

3.  Server returns **state-appropriate** links/affordances; client drives workflow by following them.


---

## Consequences

**Benefits**

-   **Looser coupling**; server can refactor URLs.

-   **Discoverability & self-describing** APIs.

-   **Safer evolution** (clients follow rels, not paths).

-   Built-in **workflow guidance** via affordances.


**Liabilities**

-   More complex to implement & document.

-   Some tooling/SDKs don’t fully embrace hypermedia.

-   Clients must be built to **follow links** (not all are).


---

## Implementation (Key Points)

-   Choose a **media type/convention** (e.g., **HAL** with Spring HATEOAS).

-   Define **canonical link relations** (prefer IANA, document custom rels).

-   Create **assemblers** to compose links from controllers/routes.

-   Add **conditional links** based on **state** and **authorizations**.

-   For actions with payloads, expose **affordances** (method, schema).

-   Keep representation **stable**; treat links as part of the **contract**.

-   Provide an **API root** with **link index** (entry point).


---

## Sample Code (Java, Spring Boot + Spring HATEOAS, HAL)

**Gradle (snippets)**

```gradle
implementation "org.springframework.boot:spring-boot-starter-web"
implementation "org.springframework.boot:spring-boot-starter-hateoas"
implementation "com.fasterxml.jackson.core:jackson-databind"
```

**Domain**

```java
package demo.hateoas;

public record Order(String id, String status) {
  public boolean cancellable() { return "NEW".equals(status); }
}
```

**Controller + HATEOAS Assembler**

```java
package demo.hateoas;

import org.springframework.hateoas.*;
import org.springframework.hateoas.server.RepresentationModelAssembler;
import org.springframework.hateoas.server.mvc.WebMvcLinkBuilder;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.*;

import static org.springframework.hateoas.server.mvc.WebMvcLinkBuilder.*;

@RestController
@RequestMapping("/orders")
public class OrderController {

  private final Map<String, Order> db = new HashMap<>();

  public OrderController() {
    db.put("42", new Order("42", "NEW"));
    db.put("43", new Order("43", "SHIPPED"));
  }

  @GetMapping("/{id}")
  public EntityModel<Order> get(@PathVariable String id) {
    Order order = Optional.ofNullable(db.get(id)).orElseThrow(() -> new OrderNotFound(id));
    return new OrderModelAssembler().toModel(order);
  }

  @GetMapping
  public CollectionModel<EntityModel<Order>> list() {
    var assembler = new OrderModelAssembler();
    var models = db.values().stream().map(assembler::toModel).toList();
    Link self = linkTo(methodOn(OrderController.class).list()).withSelfRel();
    return CollectionModel.of(models, self);
  }

  @PostMapping("/{id}/cancel")
  public ResponseEntity<?> cancel(@PathVariable String id) {
    Order o = Optional.ofNullable(db.get(id)).orElseThrow(() -> new OrderNotFound(id));
    if (!o.cancellable()) return ResponseEntity.status(409).body("Cannot cancel");
    db.put(id, new Order(id, "CANCELLED"));
    return ResponseEntity.noContent().build();
  }

  static class OrderNotFound extends RuntimeException {
    OrderNotFound(String id) { super("Order " + id + " not found"); }
  }

  static class OrderModelAssembler implements RepresentationModelAssembler<Order, EntityModel<Order>> {
    @Override
    public EntityModel<Order> toModel(Order o) {
      EntityModel<Order> model = EntityModel.of(o);
      // self
      model.add(linkTo(methodOn(OrderController.class).get(o.id())).withSelfRel());
      // collection
      model.add(linkTo(methodOn(OrderController.class).list()).withRel("orders"));
      // conditional affordance: cancel only if NEW
      if (o.cancellable()) {
        Link cancel = linkTo(methodOn(OrderController.class).cancel(o.id())).withRel("cancel").withType("POST");
        model.add(cancel);
      }
      return model;
    }
  }
}
```

**HAL Example Response (`GET /orders/42`)**

```json
{
  "id": "42",
  "status": "NEW",
  "_links": {
    "self":   { "href": "http://localhost:8080/orders/42" },
    "orders": { "href": "http://localhost:8080/orders" },
    "cancel": { "href": "http://localhost:8080/orders/42/cancel", "type": "POST" }
  }
}
```

**Entry Point (optional)**

```java
@RestController
class ApiRootController {
  @GetMapping("/")
  public RepresentationModel<?> root() {
    RepresentationModel<?> m = new RepresentationModel<>();
    m.add(WebMvcLinkBuilder.linkTo(OrderController.class).withRel("orders"));
    return m;
  }
}
```

**Notes**

-   Spring HATEOAS renders HAL by default. You can switch to **JSON:API** or **Siren** with different libraries.

-   For **forms/affordances with input schemas**, consider Siren/Spring Affordances or **ALPS** to describe semantics.

-   Add **conditional links** based on **roles/scopes** as well as resource state.


---

## Known Uses

-   **GitHub API** (hypermedia hints in some endpoints), **PayPal**, **Amazon** internal REST, many enterprise APIs delivering HAL/JSON:API/Siren responses for navigability and evolution.


---

## Related Patterns

-   **API Gateway / BFF** — often where hypermedia responses are shaped per client.

-   **API Composition** — HATEOAS links can span composed resources.

-   **Content Negotiation / Versioning** — evolve media types and link relations over time.

-   **Tolerant Reader / Consumer-Driven Contracts** — help clients adapt while server evolves.

-   **GraphQL** — alternative approach (schema-driven vs link-driven navigation).
