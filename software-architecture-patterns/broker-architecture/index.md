# Broker Architecture — Software Architecture Pattern

## Pattern Name and Classification

-   **Name:** Broker Architecture
    
-   **Classification:** Distributed Systems / Integration / Structural (decoupling & location transparency)
    

## Intent

Decouple clients from servers by introducing a **broker** that mediates communication, service discovery, and orchestration. The broker provides **location transparency**, **heterogeneity shielding**, and **non-functional services** such as routing, load balancing, retries, monitoring, and security.

## Also Known As

-   Message Broker Pattern
    
-   Request–Broker–Server (RBS)
    
-   ORB (Object Request Broker) / Service Bus (conceptually related)
    

## Motivation (Forces)

Modern systems are distributed and polyglot:

-   **Decoupling vs. Coordination:** Clients should not embed server locations or protocols.
    
-   **Heterogeneity:** Different platforms, languages, and transports must interoperate.
    
-   **Scalability & elasticity:** Servers come and go; broker should route accordingly.
    
-   **Resilience:** Need retries, timeouts, circuit breaking, backpressure.
    
-   **Observability & governance:** Central place to meter, authenticate, authorize, and trace.  
    A **broker** centralizes these cross-cutting concerns while keeping producers and consumers loosely coupled.
    

## Applicability

Use this pattern when:

-   You need **location transparency** and dynamic service discovery.
    
-   Multiple services must be **composed** or **balanced** behind a single logical endpoint.
    
-   You integrate **heterogeneous** technologies (protocols, languages).
    
-   Cross-cutting concerns (security, quotas, monitoring) are best enforced centrally.
    
-   You require **async messaging** (pub/sub) or **sync request/response** with mediation.
    

## Structure

Core elements:

-   **Client**: Issues service requests without knowing provider locations.
    
-   **Broker**: Registry + router + policy engine; handles discovery, routing, retries, auth, tracing.
    
-   **Server (Service Provider)**: Registers capabilities with broker and handles requests.
    
-   **Proxy/Stubs (optional)**: Generated or hand-written adapters that hide wire details from clients/servers.
    
-   **Transport**: Message channel(s) used by broker (TCP/HTTP/gRPC/JMS/MQTT/Kafka).
    
-   **Directory/Registry**: Maintains service instances and capabilities (health, weight, metadata).
    

```pgsql
+--------+           +----------------+            +-----------+
| Client | <-------> |     Broker     | <--------> |  Server   |
+--------+    req/   |  Registry+     |   routed   | Instances |
             resp    |  Router+Policy |    calls   +-----------+
                     +----------------+
                    (auth, LB, retries, metrics)
```

## Participants

-   **Client Proxy** — marshals requests, adds correlation IDs, retries per policy.
    
-   **Broker Core** — service registry, router, circuit breaker, metrics, tracing.
    
-   **Adapters** — protocol translators (HTTP↔JMS, REST↔gRPC).
    
-   **Providers** — actual business logic handlers; publish health/metadata.
    
-   **Observability** — logs, metrics, traces, dead-letter queues.
    
-   **Security** — authentication/authorization, mTLS, token validation.
    

## Collaboration

1.  **Registration:** Providers register themselves (name, endpoint, metadata, health).
    
2.  **Lookup:** Client sends request to the broker using a logical service name + operation.
    
3.  **Routing:** Broker selects a healthy provider (LB) and forwards the request.
    
4.  **Execution:** Provider handles the request and returns a response (or publishes events).
    
5.  **Policies:** On failure, broker may retry to another instance, trip circuit, or send to DLQ.
    
6.  **Observability:** Broker emits metrics/traces; clients/servers remain unaware of peers.
    

## Consequences

**Benefits**

-   Strong decoupling and **location transparency**.
    
-   Central control for **security, rate-limiting, governance**.
    
-   Easier **scaling and evolution** of services.
    
-   Supports **sync** and **async** interaction styles.
    

**Liabilities**

-   Broker can become a **bottleneck** or **single point of failure** (mitigate via clustering/sharding).
    
-   Added **latency** and operational complexity.
    
-   Risk of **over-centralization** (turning into an ESB anti-pattern if overused).
    
-   Requires robust **backpressure** and **capacity planning**.
    

## Implementation

### Key Decisions

-   **Interaction style:** request/response, pub/sub, or both.
    
-   **Transport(s):** HTTP/gRPC for sync, JMS/Kafka/MQTT for async; consider hybrid.
    
-   **Registry:** embedded or external (Consul, Eureka, etcd, Kubernetes).
    
-   **Resilience:** timeouts, retries with jitter, circuit breakers, DLQs.
    
-   **Security:** mTLS, JWT validation, tenant isolation, per-service ACLs.
    
-   **Observability:** correlation IDs, OpenTelemetry traces, structured logs.
    

### Policies (typical defaults)

-   **Timeouts:** 300–1000 ms per hop; absolute deadline propagation.
    
-   **Retries:** 1–2 retries with exponential backoff for idempotent ops only.
    
-   **Load balancing:** round-robin + outlier detection.
    
-   **Health:** heartbeat or passive health based on recent failures.
    
-   **Backpressure:** queue bounds + 429/503 signaling; shed lowest priority.
    

---

## Sample Code (Java)

A compact in-memory **broker** with:

-   service registry & health,
    
-   request/response over in-process channels,
    
-   load balancing, timeouts, retries,
    
-   correlation IDs and metrics.
    

> Java 17+, no external dependencies.

```java
import java.time.Duration;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.Function;

/*** Messages ***/
record Request(String service, String operation, Map<String, Object> payload,
               String correlationId, Instant deadline, int attempt) {}

record Response(int status, Map<String, Object> payload, String correlationId, String error) {
    static Response ok(Map<String,Object> p, String cid){ return new Response(200, p, cid, null); }
    static Response error(int s, String cid, String e){ return new Response(s, Map.of(), cid, e); }
}

/*** Service Provider API ***/
@FunctionalInterface
interface Handler { Response handle(Request req) throws Exception; }

/*** Registry & Instance ***/
class ServiceInstance {
    final String id; final String service; final Handler handler;
    volatile boolean healthy = true; volatile long failures = 0;
    ServiceInstance(String id, String service, Handler h){ this.id=id; this.service=service; this.handler=h; }
}

class Registry {
    private final Map<String, List<ServiceInstance>> services = new ConcurrentHashMap<>();
    void register(ServiceInstance inst){ services.computeIfAbsent(inst.service, k->new CopyOnWriteArrayList<>()).add(inst); }
    void unregister(ServiceInstance inst){ services.getOrDefault(inst.service, List.of()).remove(inst); }
    List<ServiceInstance> healthy(String service){
        return services.getOrDefault(service, List.of()).stream().filter(i -> i.healthy).toList();
    }
}

/*** Broker Core ***/
class Broker {
    private final Registry registry;
    private final ScheduledExecutorService scheduler = Executors.newScheduledThreadPool(1);
    private final ExecutorService pool = Executors.newFixedThreadPool(Runtime.getRuntime().availableProcessors());
    private final AtomicLong rr = new AtomicLong(0);
    private final Duration callTimeout;
    private final int maxRetries;

    Broker(Registry registry, Duration callTimeout, int maxRetries){
        this.registry = registry; this.callTimeout = callTimeout; this.maxRetries = maxRetries;
        // simple outlier detector (heal after delay)
        scheduler.scheduleAtFixedRate(this::heal, 5, 5, TimeUnit.SECONDS);
    }

    /** Client entrypoint */
    public Response call(String service, String operation, Map<String,Object> payload, Duration timeout) {
        String cid = UUID.randomUUID().toString();
        Instant deadline = Instant.now().plus(timeout);
        Request req = new Request(service, operation, payload, cid, deadline, 0);
        return routeWithRetries(req);
    }

    private Response routeWithRetries(Request req){
        int attempt = 0;
        Throwable last = null;
        while (attempt <= maxRetries) {
            try {
                return route(req.withAttempt(attempt));
            } catch (TimeoutException te) {
                last = te;
            } catch (Exception e) {
                last = e;
            }
            attempt++;
            sleepJitter(attempt);
        }
        return Response.error(504, req.correlationId(), "broker_timeout: " + last);
    }

    private Response route(Request req) throws Exception {
        var candidates = registry.healthy(req.service());
        if (candidates.isEmpty()) return Response.error(503, req.correlationId(), "no_healthy_instances");
        // round-robin
        int idx = (int) (rr.getAndIncrement() % candidates.size());
        ServiceInstance inst = candidates.get(Math.max(0, idx));
        Instant perCallDeadline = min(req.deadline(), Instant.now().plus(callTimeout));

        Callable<Response> task = () -> inst.handler.handle(req);
        Future<Response> fut = pool.submit(task);
        try {
            long wait = Math.max(1, Duration.between(Instant.now(), perCallDeadline).toMillis());
            Response r = fut.get(wait, TimeUnit.MILLISECONDS);
            if (r.status() >= 500) markFailure(inst); else markSuccess(inst);
            return r;
        } catch (TimeoutException te) {
            fut.cancel(true); markFailure(inst);
            throw te;
        } catch (Exception ex) {
            markFailure(inst);
            throw ex;
        }
    }

    private void markFailure(ServiceInstance i){ if (++i.failures > 3) i.healthy = false; }
    private void markSuccess(ServiceInstance i){ i.failures = 0; i.healthy = true; }
    private void heal(){
        // naive healing: mark all as healthy to re-test
        // real impl would probe instances
        // System.out.println("heal tick");
        registry.services().values().forEach(list -> list.forEach(i -> { if (!i.healthy) i.healthy = true; }));
    }
    private void sleepJitter(int attempt){
        try { Thread.sleep((long) (Math.min(200L * attempt, 1000) + ThreadLocalRandom.current().nextInt(50))); }
        catch (InterruptedException ignored) {}
    }
}

/*** Helpers for immutability ergonomics ***/
record Pair<A,B>(A a, B b) {}
/*** Extensions to Request for convenience ***/
interface RequestExt {
    static Request withAttempt(Request r, int a){
        return new Request(r.service(), r.operation(), r.payload(), r.correlationId(), r.deadline(), a);
    }
}
```

Add a few **services** and a **demo**:

```java
public class BrokerDemo {
    public static void main(String[] args) {
        Registry reg = new Registry();
        Broker broker = new Broker(reg, Duration.ofMillis(500), 1); // 1 retry, 500ms per call

        // Register two instances of "pricing" service
        ServiceInstance pricing1 = new ServiceInstance("pricing-1", "pricing", req -> {
            // simulate variable latency
            sleep(80);
            if ("quote".equals(req.operation())) {
                double base = ((Number) req.payload().getOrDefault("amount", 100)).doubleValue();
                return Response.ok(Map.of("price", base * 1.07, "inst", "pricing-1"), req.correlationId());
            }
            return Response.error(400, req.correlationId(), "unknown_op");
        });

        ServiceInstance pricing2 = new ServiceInstance("pricing-2", "pricing", req -> {
            sleep(200);
            // occasional failure to exercise retry
            if (ThreadLocalRandom.current().nextInt(5) == 0) throw new RuntimeException("boom");
            double base = ((Number) req.payload().getOrDefault("amount", 100)).doubleValue();
            return Response.ok(Map.of("price", base * 1.05, "inst", "pricing-2"), req.correlationId());
        });

        ServiceInstance inventory = new ServiceInstance("inv-1", "inventory", req -> {
            sleep(60);
            if ("reserve".equals(req.operation())) {
                String sku = (String) req.payload().get("sku");
                return Response.ok(Map.of("reserved", true, "sku", sku), req.correlationId());
            }
            return Response.error(400, req.correlationId(), "unknown_op");
        });

        reg.register(pricing1);
        reg.register(pricing2);
        reg.register(inventory);

        // Client calls (location-transparent): only knows service + operation
        Response r1 = broker.call("pricing", "quote", Map.of("amount", 250), Duration.ofSeconds(1));
        Response r2 = broker.call("inventory", "reserve", Map.of("sku", "ABC-123"), Duration.ofSeconds(1));

        System.out.println("Pricing -> " + r1.status() + " " + r1.payload());
        System.out.println("Inventory -> " + r2.status() + " " + r2.payload());
    }

    static void sleep(long ms){ try { Thread.sleep(ms); } catch (InterruptedException ignored){} }
}
```

**What this demonstrates**

-   **Registry & routing:** clients never see instance addresses.
    
-   **LB & retries:** naive round-robin with retry/jitter; failed instance is temporarily quarantined.
    
-   **Deadlines:** end-to-end deadline enforced per call.
    
-   **Correlation:** `correlationId` carried across hops (ready for logging/tracing).
    

> Productionizing: replace the in-memory transport with HTTP/gRPC, add OpenTelemetry, real health checks, circuit breakers (e.g., resilience4j), auth (JWT/mTLS), DLQ, and a distributed registry (Eureka/Consul/Kubernetes).

## Known Uses

-   **Enterprise messaging** with **RabbitMQ**, **ActiveMQ**, **IBM MQ** (request/reply + pub/sub via broker).
    
-   **Kafka** clusters (brokers) mediating producers/consumers (log-based variant).
    
-   **CORBA ORB**, **DCOM**, **RMI-IIOP** (historical object request brokers).
    
-   **API gateways** acting as lightweight brokers (routing, auth, rate limiting).
    
-   **IoT** with **MQTT brokers** (Mosquitto/EMQX) mediating devices and services.
    

## Related Patterns

-   **Message Bus / Pub-Sub** — event distribution; broker often provides this.
    
-   **Mediator** — similar intent; broker specializes in distributed messaging and discovery.
    
-   **Microkernel** — pluggable providers around a core; broker plays the hub.
    
-   **Service Registry & Discovery** — a key subsystem used by brokers.
    
-   **API Gateway** — edge broker for HTTP traffic.
    
-   **Enterprise Service Bus (ESB)** — heavyweight broker variant with orchestration and transformation.
    

---

**Implementation Notes**

-   **Clustered brokers** with partitioning and replication eliminate single points of failure.
    
-   Prefer **idempotent handlers** to enable safe retries.
    
-   Carry **deadlines** and **trace context** (W3C Traceparent) across broker boundaries.
    
-   Apply **backpressure**: bounded queues, priority scheduling, and 429/503.
    
-   Enforce **security** centrally (mTLS/JWT/OPA policies) with per-service scopes.
    
-   For hybrid sync/async: wrap request/response over topics with **correlation IDs** and **reply-to** channels.

