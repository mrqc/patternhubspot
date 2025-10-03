# gRPC — API Design Pattern

## Pattern Name and Classification

**gRPC** — *High-performance, contract-first, binary RPC* pattern built on **HTTP/2** and **Protocol Buffers** for service-to-service APIs.

---

## Intent

Enable **fast, strongly-typed, streaming-capable** remote procedure calls between services with **IDL-driven contracts**, **code generation**, and **bidirectional streaming** over a single HTTP/2 connection.

---

## Also Known As

-   **Remote Procedure Calls over HTTP/2**

-   **Protobuf RPC**

-   **Binary RPC**


---

## Motivation (Forces)

-   Need **low-latency**, **high-throughput** inter-service communication.

-   Desire **strong contracts** and codegen across many languages.

-   Support for **unary**, **server streaming**, **client streaming**, and **bidirectional streaming**.

-   HTTP/1.1 JSON REST can be verbose; lacks efficient streaming and built-in contracts.


Trade-offs:

-   Harder to **debug with curl/browsers**; requires tooling.

-   **Edge exposure** to the public internet is less common (often paired with a gateway).

-   **Binary payloads** complicate CDN caching/inspection.


---

## Applicability

Use gRPC when:

-   Service-to-service (north-south inside the DC / east-west) needs **speed** and **type safety**.

-   You need **streaming** semantics (real-time feeds, long-lived calls).

-   You want **polyglot** clients from a single IDL.


Avoid / limit when:

-   You need **simple public APIs** for third-party developers (REST/GraphQL may be friendlier).

-   You rely on **browser-only** clients without a proxy (gRPC-web is required).

-   Heavy **edge caching** by URL is critical.


---

## Structure

```css
[ .proto (IDL) ]  →  Codegen  →  Client Stub      ──HTTP/2──>  Server Impl
                                  (Java, etc.)                     (Java)
               messages + services                 unary / streaming methods
```

---

## Participants

-   **.proto Schema**: Messages, services, RPC methods.

-   **Client Stub**: Generated strongly-typed client.

-   **Server Skeleton**: Generated base to implement.

-   **gRPC Channel**: HTTP/2 connection with multiplexed streams.

-   **Interceptors**: Auth, logging, tracing, retries (client-side).


---

## Collaboration

1.  Define **.proto** contract.

2.  Generate code for client/server.

3.  Server implements methods; client calls stubs (unary or streaming).

4.  Metadata/headers carry auth, tracing, etc.

5.  Observability via interceptors and metrics.


---

## Consequences

**Benefits**

-   **High performance** (binary Protobuf + HTTP/2 multiplexing).

-   **Rich semantics** (4 RPC styles, deadlines, cancellation).

-   **Strong typing** and **language-agnostic** codegen.


**Liabilities**

-   Less accessible to humans; needs **special tooling**.

-   **Protobuf evolution rules** must be respected (field numbers, compatibility).

-   Public internet exposure usually needs **gateway/translation**.


---

## Implementation (Key Points)

-   Define **backward-compatible** Protobuf schemas (never reuse/renumber tags).

-   Use **deadlines** (`withDeadlineAfter`) and **cancellation** to avoid leaks.

-   Add **interceptors** for auth (e.g., JWT in metadata), tracing, and retries.

-   For browsers, consider **gRPC-Web** behind Envoy.

-   Consider **load balancing** (pick\_first/round\_robin/xDS) and TLS.


---

## Sample Code (Java) — Unary + Server Streaming

### 1) Gradle (Kotlin DSL) dependencies & codegen

```kotlin
plugins {
  id("java")
  id("com.google.protobuf") version "0.9.4"
}

repositories { mavenCentral() }

dependencies {
  implementation("io.grpc:grpc-netty-shaded:1.66.0")
  implementation("io.grpc:grpc-protobuf:1.66.0")
  implementation("io.grpc:grpc-stub:1.66.0")
  compileOnly("org.apache.tomcat:annotations-api:6.0.53") // for javax.annotation
  testImplementation("org.junit.jupiter:junit-jupiter:5.10.2")
}

protobuf {
  protoc { artifact = "com.google.protobuf:protoc:3.25.3" }
  plugins {
    id("grpc") { artifact = "io.grpc:protoc-gen-grpc-java:1.66.0" }
  }
  generateProtoTasks {
    all().forEach { task ->
      task.plugins { id("grpc") }
    }
  }
}

tasks.test { useJUnitPlatform() }
```

### 2) `order.proto` (place under `src/main/proto/order.proto`)

```proto
syntax = "proto3";
package demo.order.v1;

option java_multiple_files = true;
option java_package = "demo.order.v1";
option java_outer_classname = "OrderProto";

message OrderRequest {
  string order_id = 1;
}

message Order {
  string id = 1;
  string status = 2; // e.g., CONFIRMED, SHIPPED
  repeated string items = 3;
}

message OrdersByStatusRequest {
  string status = 1;
}

service OrderService {
  // Unary RPC
  rpc GetOrder (OrderRequest) returns (Order);

  // Server streaming RPC
  rpc StreamOrdersByStatus (OrdersByStatusRequest) returns (stream Order);
}
```

Run `./gradlew build` to generate Java stubs under `build/generated/source/proto`.

### 3) Server Implementation

```java
package demo.order.v1;

import io.grpc.Server;
import io.grpc.ServerBuilder;
import io.grpc.stub.StreamObserver;
import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

public class OrderServer {

  // toy in-memory store
  private static final Map<String, Order> DB = new ConcurrentHashMap<>();
  static {
    DB.put("o-1", Order.newBuilder().setId("o-1").setStatus("CONFIRMED")
        .addAllItems(List.of("sku-1","sku-2")).build());
    DB.put("o-2", Order.newBuilder().setId("o-2").setStatus("SHIPPED")
        .addAllItems(List.of("sku-3")).build());
  }

  public static class OrderServiceImpl extends OrderServiceGrpc.OrderServiceImplBase {
    @Override
    public void getOrder(OrderRequest req, StreamObserver<Order> resp) {
      Order o = DB.get(req.getOrderId());
      if (o == null) {
        resp.onError(io.grpc.Status.NOT_FOUND.withDescription("order not found").asRuntimeException());
        return;
      }
      resp.onNext(o);
      resp.onCompleted();
    }

    @Override
    public void streamOrdersByStatus(OrdersByStatusRequest req, StreamObserver<Order> resp) {
      String status = req.getStatus();
      DB.values().stream()
        .filter(o -> o.getStatus().equalsIgnoreCase(status))
        .forEach(resp::onNext);
      resp.onCompleted();
    }
  }

  public static void main(String[] args) throws IOException, InterruptedException {
    Server server = ServerBuilder.forPort(9090)
        .addService(new OrderServiceImpl())
        .build()
        .start();
    System.out.println("gRPC server started on :9090");
    server.awaitTermination();
  }
}
```

### 4) Client (Unary + Streaming, with Deadline)

```java
package demo.order.v1;

import io.grpc.ManagedChannel;
import io.grpc.ManagedChannelBuilder;
import io.grpc.StatusRuntimeException;
import java.util.concurrent.TimeUnit;

public class OrderClient {

  public static void main(String[] args) throws Exception {
    ManagedChannel channel = ManagedChannelBuilder
        .forTarget("localhost:9090")
        .usePlaintext() // use TLS in production
        .build();

    try {
      OrderServiceGrpc.OrderServiceBlockingStub stub =
          OrderServiceGrpc.newBlockingStub(channel)
              .withDeadlineAfter(2, TimeUnit.SECONDS); // deadline

      // Unary call
      try {
        Order order = stub.getOrder(OrderRequest.newBuilder().setOrderId("o-1").build());
        System.out.println("Order: " + order.getId() + " status=" + order.getStatus());
      } catch (StatusRuntimeException e) {
        System.err.println("Unary failed: " + e.getStatus());
      }

      // Server streaming call
      var stream = stub.streamOrdersByStatus(
          OrdersByStatusRequest.newBuilder().setStatus("SHIPPED").build());
      stream.forEachRemaining(o -> System.out.println("Stream item: " + o.getId()));

    } finally {
      channel.shutdownNow().awaitTermination(5, TimeUnit.SECONDS);
    }
  }
}
```

### 5) Optional: Interceptor (Tracing/Headers)

```java
import io.grpc.*;

public class CorrelationIdClientInterceptor implements ClientInterceptor {
  @Override
  public <ReqT, RespT> ClientCall<ReqT, RespT> interceptCall(
      MethodDescriptor<ReqT, RespT> method, CallOptions callOptions, Channel next) {
    return new ForwardingClientCall.SimpleForwardingClientCall<>(next.newCall(method, callOptions)) {
      @Override
      public void start(Listener<RespT> responseListener, Metadata headers) {
        Metadata.Key<String> CID = Metadata.Key.of("x-correlation-id", Metadata.ASCII_STRING_MARSHALLER);
        headers.put(CID, java.util.UUID.randomUUID().toString());
        super.start(responseListener, headers);
      }
    };
  }
}
```

Register this interceptor when creating the stub:

```java
var intercepted = io.grpc.ClientInterceptors.intercept(channel, new CorrelationIdClientInterceptor());
OrderServiceGrpc.OrderServiceBlockingStub stub = OrderServiceGrpc.newBlockingStub(intercepted);
```

---

## Known Uses

-   **Google**, **Netflix**, **Square**, **Cloud Native** ecosystems for internal microservice RPC.

-   CNCF projects and service meshes frequently integrate with **gRPC** for efficient east-west traffic.


---

## Related Patterns

-   **API Gateway / BFF** — translate public REST/GraphQL to internal gRPC.

-   **API Composition** — gRPC stubs used inside the composition layer.

-   **Circuit Breaker / Retry / Timeout / Bulkhead** — essential resilience with gRPC calls.

-   **GraphQL Federation** — can call gRPC backends in resolvers.

-   **gRPC-Web** — for browser compatibility via Envoy/Ingress.
