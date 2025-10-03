# GraphQL — API Design Pattern

## Pattern Name and Classification

**GraphQL** — *Query language & runtime for APIs*; an **API design** and **data-fetching** pattern enabling client-defined queries against a typed schema.

---

## Intent

Let clients **ask exactly for the data they need** (and nothing more) via a **strongly-typed schema**, supporting **declarative queries**, **field-level composition**, and **single endpoint** access to multiple backends.

---

## Also Known As

-   **Schema-Driven API**

-   **Query-by-Shape API**

-   **Single Endpoint Graph API**


---

## Motivation (Forces)

-   REST endpoints often over/under-fetch; UIs need **custom shapes** and evolve quickly.

-   Mobile/low-bandwidth clients benefit from **fewer round trips** and smaller payloads.

-   Multiple backends (microservices) must be **composed consistently**.

-   Strong typing and **introspection** improve **tooling**, **docs**, and **change safety**.


Tensions:

-   Resolver fan-out can create **N+1** problems.

-   Complex authorization at **field level**.

-   Caching is less trivial than REST’s URL-based model.


---

## Applicability

Use GraphQL when:

-   Clients require **flexible, evolving** data shapes.

-   You aggregate data from **multiple services** into **one contract**.

-   You value **strong types**, **self-documentation**, and **tooling** (GraphiQL, codegen).


Avoid or restrict when:

-   You serve **very large downloads/streams** (consider REST/download links or gRPC/streaming).

-   **Simple CRUD** with stable shapes is sufficient (REST may be cheaper to operate).

-   Strict **edge caching (CDN)** by URL is critical and field-level caching is not feasible.


---

## Structure

```graphql
Client
  └── POST /graphql { query, variables }
        |
        v
   GraphQL Server (Schema + Resolvers + DataLoaders)
        |                   |                  |
   Services/DB A        Services/DB B     Services/DB C
```

---

## Participants

-   **Schema** (SDL): Types, fields, inputs, enums, directives; single source of truth.

-   **Resolvers**: Functions that fetch data for fields.

-   **DataLoaders**: Batch & cache per-request to avoid N+1.

-   **Clients/Tools**: GraphiQL, Apollo Client, code generators.

-   **Security/Policy Layer**: AuthN/Z at query/field level.


---

## Collaboration

1.  Client posts a **query** with optional **variables** to `/graphql`.

2.  Server **parses → validates → executes** against resolvers.

3.  Resolvers fetch from backends, often **batched** through DataLoaders.

4.  Response returns **data** and optional **errors** (partial data allowed).


---

## Consequences

**Benefits**

-   **Exact data**: reduces over/under-fetching, fewer round trips.

-   **Strong typing & introspection**: great **DX**, schema-driven tooling & codegen.

-   **Composition**: multiple domains unified under one graph.


**Liabilities**

-   Resolver fan-out → **N+1** if not batched.

-   **Caching & observability** require extra design (field-level caching, persisted queries).

-   **Authorization** can be complex (directive/field policies).

-   Schema governance & versioning need discipline (deprecation flows, federations).


---

## Implementation (Key Points)

-   Design the **schema first** (SDL); use **pagination** (Cursor/Relay) and **connections** for large lists.

-   Add **query cost control**: max depth/complexity, timeouts, persisted queries.

-   Use **DataLoader** (per request) to batch/ cache by key → eliminate N+1.

-   Implement **auth** via directives or method security in resolvers.

-   For microservices, consider **GraphQL Federation** (Apollo) or schema stitching.

-   Add **error handling**: map domain errors to GraphQL `errors[]` without leaking internals.

-   **Observability**: field resolver metrics, tracing (OpenTelemetry), query logs.


---

## Sample Code (Java, Spring for GraphQL + DataLoader)

### Gradle (snippets)

```gradle
implementation "org.springframework.boot:spring-boot-starter-graphql"
implementation "org.springframework.boot:spring-boot-starter-web"
implementation "com.fasterxml.jackson.core:jackson-databind"
testImplementation "org.springframework.boot:spring-boot-starter-test"
```

### Schema (resources/graphql/schema.graphqls)

```graphql
type Query {
  order(id: ID!): Order
  orders(first: Int = 10, after: String): OrderConnection!
}

type Order {
  id: ID!
  status: String!
  items: [OrderItem!]!
  payment: Payment
  shipment: Shipment
}

type OrderItem {
  sku: ID!
  name: String!
  quantity: Int!
}

type Payment {
  id: ID!
  state: String!
  method: String
}

type Shipment {
  id: ID!
  carrier: String
  tracking: String
}

type PageInfo {
  endCursor: String
  hasNextPage: Boolean!
}
type OrderEdge { cursor: String!, node: Order! }
type OrderConnection { edges: [OrderEdge!]!, pageInfo: PageInfo! }
```

### Simple Domain/DTOs

```java
public record Order(String id, String status, java.util.List<OrderItem> items) {}
public record OrderItem(String sku, String name, int quantity) {}
public record Payment(String id, String state, String method) {}
public record Shipment(String id, String carrier, String tracking) {}
```

### Data Sources (stubs)

```java
import org.springframework.stereotype.Repository;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

@Repository
class OrderRepo {
  private final Map<String, Order> db = new ConcurrentHashMap<>();
  OrderRepo() {
    db.put("o-1", new Order("o-1", "CONFIRMED",
        List.of(new OrderItem("sku-1","Widget",2), new OrderItem("sku-2","Thing",1))));
  }
  Optional<Order> findById(String id) { return Optional.ofNullable(db.get(id)); }
  List<Order> findPage(int first, String after) {
    var list = new ArrayList<>(db.values());
    list.sort(java.util.Comparator.comparing(Order::id));
    int start = 0;
    if (after != null) {
      for (int i=0;i<list.size();i++) if(list.get(i).id().equals(after)) { start=i+1; break; }
    }
    int end = Math.min(start+first, list.size());
    return list.subList(start, end);
  }
}

@Repository
class PaymentClient {
  Payment getByOrderId(String orderId) { return new Payment("p-"+orderId, "PAID", "VISA"); }
  java.util.Map<String, Payment> getByOrderIdsBatch(java.util.List<String> ids) {
    var map = new java.util.HashMap<String, Payment>();
    ids.forEach(id -> map.put(id, getByOrderId(id)));
    return map;
  }
}

@Repository
class ShippingClient {
  Shipment getByOrderId(String orderId) { return new Shipment("s-"+orderId, "DHL", "TRACK123"); }
  java.util.Map<String, Shipment> getByOrderIdsBatch(java.util.List<String> ids) {
    var map = new java.util.HashMap<String, Shipment>();
    ids.forEach(id -> map.put(id, getByOrderId(id)));
    return map;
  }
}
```

### DataLoader Configuration (batching to avoid N+1)

```java
import org.dataloader.BatchLoader;
import org.dataloader.DataLoader;
import org.dataloader.DataLoaderRegistry;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
class DataLoaderConfig {

  @Bean
  DataLoaderRegistry registry(PaymentClient payments, ShippingClient shipping) {
    DataLoaderRegistry reg = new DataLoaderRegistry();

    BatchLoader<String, Payment> payBatcher = keys ->
      java.util.concurrent.CompletableFuture.supplyAsync(() -> {
        var map = payments.getByOrderIdsBatch(keys);
        return keys.stream().map(k -> map.getOrDefault(k, null)).toList();
      });

    BatchLoader<String, Shipment> shipBatcher = keys ->
      java.util.concurrent.CompletableFuture.supplyAsync(() -> {
        var map = shipping.getByOrderIdsBatch(keys);
        return keys.stream().map(k -> map.getOrDefault(k, null)).toList();
      });

    reg.register("paymentByOrderId", DataLoader.newDataLoader(payBatcher));
    reg.register("shipmentByOrderId", DataLoader.newDataLoader(shipBatcher));
    return reg;
  }
}
```

### Query & Field Resolvers (Spring for GraphQL)

```java
import org.dataloader.DataLoader;
import org.springframework.graphql.data.method.annotation.*;
import org.springframework.stereotype.Controller;
import reactor.core.publisher.Mono;

import java.util.List;
import java.util.concurrent.CompletableFuture;

record OrderEdge(String cursor, Order node) {}
record PageInfo(String endCursor, boolean hasNextPage) {}
record OrderConnection(List<OrderEdge> edges, PageInfo pageInfo) {}

@Controller
class OrderGraphQL {

  private final OrderRepo orders;

  OrderGraphQL(OrderRepo orders) { this.orders = orders; }

  @QueryMapping
  public Order order(@Argument String id) {
    return orders.findById(id).orElse(null);
  }

  @QueryMapping
  public OrderConnection orders(@Argument Integer first, @Argument String after) {
    int pageSize = first == null ? 10 : Math.min(first, 100);
    List<Order> page = orders.findPage(pageSize, after);
    String endCursor = page.isEmpty() ? after : page.get(page.size()-1).id();
    boolean hasNext = orders.findPage(1, endCursor).size() > 0;
    List<OrderEdge> edges = page.stream().map(o -> new OrderEdge(o.id(), o)).toList();
    return new OrderConnection(edges, new PageInfo(endCursor, hasNext));
    // Relay-style cursoring simplified for brevity
  }

  // Field resolvers using DataLoader (avoid N+1)
  @SchemaMapping(typeName = "Order", field = "payment")
  public CompletableFuture<Payment> payment(Order source, DataLoader<String, Payment> paymentByOrderId) {
    return paymentByOrderId.load(source.id());
  }

  @SchemaMapping(typeName = "Order", field = "shipment")
  public CompletableFuture<Shipment> shipment(Order source, DataLoader<String, Shipment> shipmentByOrderId) {
    return shipmentByOrderId.load(source.id());
  }
}
```

### Error/Validation & Security (examples)

```java
import org.springframework.graphql.execution.DataFetcherExceptionResolverAdapter;
import org.springframework.stereotype.Component;
import graphql.GraphQLError;
import graphql.GraphqlErrorBuilder;

@Component
class GraphqlErrors extends DataFetcherExceptionResolverAdapter {
  @Override
  protected GraphQLError resolveToSingleError(Throwable ex, graphql.schema.DataFetchingEnvironment env) {
    return GraphqlErrorBuilder.newError(env)
        .message("ERR_%s".formatted(ex.getClass().getSimpleName()))
        .build();
  }
}
```

```java
// Security idea (pseudocode):
// - Use Spring Security to authenticate the HTTP request
// - Inject user principal into resolvers and enforce field-level checks
```

**Run & Test**

-   Start the app; open `/graphiql` or `/graphql`.

-   Example query:


```graphql
query {
  orders(first: 10) {
    edges { cursor node { id status payment { state } shipment { carrier tracking } } }
    pageInfo { endCursor hasNextPage }
  }
}
```

---

## Known Uses

-   **GitHub GraphQL**, **Shopify**, **Facebook**, **Airbnb**; many enterprises using GraphQL as a **BFF/composition** layer across microservices, often with **Apollo Federation** or **Netflix DGS**.


---

## Related Patterns

-   **API Composition / BFF** — GraphQL commonly *implements* these (read-side aggregation).

-   **Gateway** — GraphQL often runs at the edge (with auth, rate limiting).

-   **Federation / Schema Stitching** — scale GraphQL across teams/services.

-   **Caching / Persisted Queries / CDN** — complementary for performance.

-   **Circuit Breaker / Bulkhead** — protect resolver fan-out to downstreams.
