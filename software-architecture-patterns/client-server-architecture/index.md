# Client–Server Architecture — Software Architecture Pattern

## Pattern Name and Classification

-   **Name:** Client–Server Architecture
    
-   **Classification:** Distributed Systems / Structural Pattern (communication & responsibility split)
    

## Intent

Separate **requesting** components (**clients**) from **service-providing** components (**servers**) connected over a communication channel. The server exposes a **stable interface/protocol**; clients send requests and receive responses, enabling centralization of data/logic and many-to-one access.

## Also Known As

-   Request/Response Architecture
    
-   Two-Tier Architecture (when server includes data tier)
    
-   N-Tier (when extended with app + data servers)
    

## Motivation (Forces)

-   **Centralized data & rules** vs. **distributed consumption**
    
-   **Scalability:** many clients must share compute/data; servers should scale horizontally/vertically
    
-   **Heterogeneity:** clients vary (web/mobile/desktop/IoT) but need a consistent API
    
-   **Security & governance:** control access, audit centrally; avoid leaking internals to clients
    
-   **Latency/bandwidth:** minimize chattiness; batch, cache, compress
    
-   **Evolution:** change server internals without breaking clients (versioned contracts)
    

The pattern addresses these by placing shared resources and policies behind a stable server endpoint and letting diverse clients integrate via an agreed protocol (HTTP/gRPC, custom TCP, etc.).

## Applicability

Use when:

-   Multiple consumers need access to **shared resources** (data, ML inference, business rules).
    
-   You want a **thin client** with centralized updates (web, enterprise apps).
    
-   You need **access control, auditing, and rate limiting** at a central point.
    
-   Interfaces can be **contracted** and evolved with versioning.
    
-   You want to avoid tight coupling between client UI and data/storage.
    

Avoid when:

-   **Ultra-low latency** in a single box is critical (consider in-process modules).
    
-   **Disconnected-first** operation dominates (consider offline-first/sync patterns).
    
-   Peer collaboration without a central authority is paramount (P2P/event-driven).
    

## Structure

-   **Client:** presents UI or automation; composes requests; may cache; handles retries/backoff.
    
-   **Server:** validates/authenticates, executes business logic, accesses storage/backends; returns results/errors.
    
-   **Transport/Protocol:** TCP/HTTP/HTTP2/gRPC/WebSocket, with serialization (JSON/Proto).
    
-   **Optional:** Reverse proxy/API gateway, cache, load balancer, auth service.
    

```pgsql
+---------+       request        +------------------+      storage/backends
| Client  |  ------------------> |      Server      | ---> DBs, queues, services
| (web/   |  <------------------ |  (API/Service)   |
| mobile) |       response       +------------------+
+---------+         ^                     |
                    |                     v
               CDN/cache            AuthN/Z, rate limit, logs
```

## Participants

-   **Client Application** (browser/mobile/desktop/daemon)
    
-   **Server Application / API** (one or more instances)
    
-   **Service Interface / Contract** (OpenAPI/gRPC IDL/ custom protocol)
    
-   **Transport** (HTTP(S), TCP, TLS/mTLS)
    
-   **Infrastructure** (LB, reverse proxy, WAF, cache, DB)
    
-   **Observability** (logs, metrics, tracing)
    

## Collaboration

1.  Client prepares a request per the **contract**, includes auth and correlation IDs.
    
2.  Server authenticates/authorizes, validates input, executes business logic, reaches storage.
    
3.  Server returns a response (success or error with codes).
    
4.  Client interprets the response, updates UI/state, possibly caches and retries on transient failures.
    

## Consequences

**Benefits**

-   Centralized **security, data integrity, and governance**.
    
-   **Scalable**—add more server instances behind a load balancer.
    
-   **Evolvable**—replace or optimize server internals without client rebuilds if the API contract remains.
    
-   **Interoperable**—multiple client types consume the same service.
    

**Liabilities**

-   **Single logical dependency:** server outage affects all clients (mitigate with HA).
    
-   **Network costs/latency**; chatty APIs hurt performance (batching/versioned endpoints).
    
-   **Coupling to contract:** breaking API changes cascade to clients (use versioning, BWC).
    
-   **Security surface:** exposed endpoints need robust defenses (TLS, rate limit, input validation).
    

## Implementation

### Key Guidelines

-   **Define a contract** (OpenAPI/gRPC). Treat it as code; version it.
    
-   **Secure by default:** TLS, OAuth2/OIDC or mTLS, input validation, least privilege to backends.
    
-   **Resilience:** timeouts, retries with jitter (idempotent only), circuit breakers, backoff.
    
-   **Performance:** pagination, compression, caching (`ETag`/`Last-Modified`), request coalescing.
    
-   **Observability:** structured logs with correlation IDs, metrics (p95 latency), tracing (W3C Trace Context).
    
-   **Compatibility:** support **BWC** windows; deprecate gradually.
    
-   **Scalability:** stateless server where possible; externalize state (DB/cache).
    
-   **Error model:** consistent error schema with machine-readable codes.
    

### Typical Variants

-   **Thin client + fat server (web apps)**
    
-   **Smart client (offline-first) + sync server**
    
-   **Gateway fronting microservices** (client still sees one “server”)
    

---

## Sample Code (Java)

Two minimal examples:

1.  **TCP Echo-style service** (shows raw client–server request/response & concurrency)
    
2.  **HTTP JSON API** with Java 11+ built-ins (no frameworks)
    

> Java 17+, no external dependencies.

### 1) Raw TCP Server & Client

```java
// TcpServer.java
import java.io.*;
import java.net.*;
import java.util.concurrent.*;

public class TcpServer {
  private final int port;
  private final ExecutorService pool = Executors.newFixedThreadPool(16);

  public TcpServer(int port){ this.port = port; }

  public void start() throws IOException {
    try (ServerSocket server = new ServerSocket(port)) {
      System.out.println("TCP server listening on " + port);
      while (true) {
        Socket client = server.accept();
        client.setSoTimeout(5000);
        pool.submit(() -> handle(client));
      }
    }
  }

  private void handle(Socket client) {
    String peer = client.getRemoteSocketAddress().toString();
    try (client;
         BufferedReader in = new BufferedReader(new InputStreamReader(client.getInputStream()));
         BufferedWriter out = new BufferedWriter(new OutputStreamWriter(client.getOutputStream()))) {

      String line = in.readLine(); // simple 1-line request protocol
      if (line == null) return;
      String response = process(line);
      out.write(response);
      out.write("\n");
      out.flush();
      System.out.println("Handled " + peer + " -> " + line + " => " + response);
    } catch (IOException e) {
      System.err.println("Error handling " + peer + ": " + e.getMessage());
    }
  }

  // Business logic placeholder
  private String process(String request) {
    if (request.startsWith("HELLO ")) return "Hi " + request.substring(6) + "!";
    if (request.startsWith("ADD ")) {
      String[] p = request.substring(4).split(",");
      int a = Integer.parseInt(p[0].trim()), b = Integer.parseInt(p[1].trim());
      return String.valueOf(a + b);
    }
    return "ERR unknown_command";
  }

  public static void main(String[] args) throws IOException {
    new TcpServer(9090).start();
  }
}
```

```java
// TcpClient.java
import java.io.*;
import java.net.Socket;

public class TcpClient {
  public static void main(String[] args) throws Exception {
    try (Socket s = new Socket("localhost", 9090);
         BufferedReader in = new BufferedReader(new InputStreamReader(s.getInputStream()));
         BufferedWriter out = new BufferedWriter(new OutputStreamWriter(s.getOutputStream()))) {

      out.write("HELLO Alice\n"); out.flush();
      System.out.println("Server: " + in.readLine());

      out.write("ADD 7, 35\n"); out.flush();
      System.out.println("Server: " + in.readLine());
    }
  }
}
```

### 2) Minimal HTTP JSON API (Server + Client)

```java
// HttpJsonServer.java
import com.sun.net.httpserver.*;
import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Map;

public class HttpJsonServer {
  public static void main(String[] args) throws IOException {
    HttpServer server = HttpServer.create(new InetSocketAddress(8080), 0);
    server.createContext("/api/v1/add", exchange -> {
      if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) { exchange.sendResponseHeaders(405, -1); return; }
      String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
      Map<String, Object> json = Json.parse(body); // tiny helper below
      int a = ((Number) json.getOrDefault("a", 0)).intValue();
      int b = ((Number) json.getOrDefault("b", 0)).intValue();
      String response = "{\"sum\":" + (a + b) + "}";
      exchange.getResponseHeaders().add("Content-Type", "application/json");
      byte[] bytes = response.getBytes(StandardCharsets.UTF_8);
      exchange.sendResponseHeaders(200, bytes.length);
      try (OutputStream os = exchange.getResponseBody()) { os.write(bytes); }
    });
    server.setExecutor(java.util.concurrent.Executors.newFixedThreadPool(8));
    server.start();
    System.out.println("HTTP server on http://localhost:8080");
  }

  // ultra-minimal JSON helper (numbers + objects only; replace with a proper library in production)
  static class Json {
    static Map<String, Object> parse(String s){
      // extremely naive: expects {"a":1,"b":2}
      s = s.trim().replaceAll("[{}\\s\"]", "");
      String[] parts = s.split(",");
      java.util.Map<String,Object> m = new java.util.HashMap<>();
      for (String p : parts) {
        if (p.isBlank()) continue;
        String[] kv = p.split(":");
        m.put(kv[0], Integer.parseInt(kv[1]));
      }
      return m;
    }
  }
}
```

```java
// HttpJsonClient.java
import java.net.http.*;
import java.net.URI;
import java.nio.charset.StandardCharsets;

public class HttpJsonClient {
  public static void main(String[] args) throws Exception {
    HttpClient client = HttpClient.newHttpClient();
    String payload = "{\"a\": 21, \"b\": 21}";
    HttpRequest req = HttpRequest.newBuilder()
        .uri(URI.create("http://localhost:8080/api/v1/add"))
        .header("Content-Type", "application/json")
        .POST(HttpRequest.BodyPublishers.ofString(payload, StandardCharsets.UTF_8))
        .build();
    HttpResponse<String> resp = client.send(req, HttpResponse.BodyHandlers.ofString());
    System.out.println(resp.statusCode() + " " + resp.body());
  }
}
```

**What the samples show**

-   A **clear contract** (line protocol / HTTP JSON) between a client and a server.
    
-   **Concurrency** on the server (thread pool).
    
-   Separation of **business logic** (e.g., `process()` or `/add` handler) from transport.
    
-   You can swap clients (mobile/desktop) without changing the server contract.
    

> Productionize with: TLS termination, structured JSON (Jackson), OpenAPI spec, OAuth2/JWT, rate limiting, timeouts, retries (idempotent), metrics/tracing (OpenTelemetry), and deployment behind a load balancer.

## Known Uses

-   Classic **web backends** (HTTP APIs) serving browsers/mobile apps.
    
-   **Database servers** (PostgreSQL/MySQL) as servers with numerous clients/tools.
    
-   **Mail** (SMTP/IMAP/POP3) and **directory services** (LDAP) using standardized client–server protocols.
    
-   **Microservices at the edge**: client-facing API gateways proxied to internal services still follow client–server at each hop.
    

## Related Patterns

-   **Broker Architecture** — adds mediation, routing, and discovery between clients and servers.
    
-   **Layered/N-Tier** — decomposes server into presentation, application, and data tiers.
    
-   **REST/gRPC** — specific client–server protocol styles.
    
-   **Pipes & Filters** — for streaming transformations inside the server.
    
-   **Publish–Subscribe** — decouples via events instead of direct request/response.
    
-   **Clean/Hexagonal Architecture** — internal server structure to isolate business logic from adapters.
    

---

## Implementation Tips

-   Lock down **contracts** early; evolve with **semantic versioning** and **deprecation windows**.
    
-   Keep servers **stateless** where possible; store session/state in external stores to scale out.
    
-   Make **idempotent** endpoints to enable safe retries.
    
-   Use **pagination and filtering** for large result sets; support `ETag` caching.
    
-   Include **correlation IDs** in requests and responses.
    
-   Validate inputs at the boundary; never trust clients.
    
-   Test with **contract tests** (e.g., Pact) so client and server evolve independently.

