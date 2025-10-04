# Service-Oriented Architecture (SOA) — Software Architecture Pattern

## Pattern Name and Classification

-   **Name:** Service-Oriented Architecture (SOA)
    
-   **Classification:** Distributed Systems / Integration & Composition / Macro-Architecture
    

## Intent

Expose **business capabilities as services** with **formal contracts** and **loose coupling**, so heterogeneous systems can interoperate, be **composed/orchestrated**, and evolve independently under **governance** (policies, versioning, monitoring).

## Also Known As

-   Service Orientation
    
-   Enterprise SOA
    
-   (Historically) WS-\* SOA (SOAP/WSDL-centric variants)
    

## Motivation (Forces)

-   **Heterogeneity:** many platforms, languages, vendors.
    
-   **Reuse & alignment:** avoid duplicating core capabilities (customer, payments).
    
-   **Change & autonomy:** teams need to evolve separately but still collaborate.
    
-   **End-to-end processes:** require **composition** across multiple services.
    
-   **Governance & risk:** organizations need policy enforcement, observability, SLAs.  
    SOA addresses these by putting **services with contracts** at the boundary, **mediated** by a bus/gateway/registry, with **orchestration or choreography** for processes.
    

## Applicability

Choose SOA when:

-   Integrating **legacy** + new systems across domains and vendors.
    
-   You need **contract-first** APIs with **policy enforcement** (security, quotas, SLAs).
    
-   Cross-domain **business processes** span multiple internal/external systems.
    
-   Large orgs require **governance, catalogs, and versioning**.
    

Avoid or simplify when:

-   A **single team/product** can move faster with a modular monolith or microservices without centralized mediation.
    
-   Ultra-low latency intra-service calls dominate (prefer direct RPC within one bounded context).
    

## Structure

Core building blocks:

-   **Service** — autonomous capability with a **contract** (interface + schema + policy).
    
-   **Service Contract** — operations, message shapes, pre/post-conditions, QoS.
    
-   **Service Registry/Catalog** — discoverable metadata, versions, endpoints.
    
-   **Mediation Layer** — **ESB/API Gateway** for routing, transformation, security, retries, metrics.
    
-   **Orchestration / Choreography** — compose services into processes.
    
-   **Policy/Governance** — authN/Z, quotas, change control, lifecycle.
    

```pgsql
Clients  -->  Gateway/ESB  -->  Services (Customer, Order, Payment, …)
                 |  ^               |        | 
            Registry/Policy     Data/Adapters to legacy
              (discovery)       (DB, MQ, SAP, Mainframe)
```

## Participants

-   **Service Provider** — implements the capability; publishes the contract.
    
-   **Service Consumer** — binds to the contract; sends requests or events.
    
-   **Contract & Schema** — OpenAPI/AsyncAPI/Avro/WSDL, etc.
    
-   **Service Registry** — endpoint metadata, versions, health, policies.
    
-   **Gateway/ESB** — mediation: routing, transform, protocol bridge, security, observability.
    
-   **Process Manager/Orchestrator** — coordinates multi-step workflows.
    
-   **Event Bus (optional)** — for publish/subscribe and loosely-coupled reactions.
    

## Collaboration

1.  **Publish**: Provider registers the service (name, version, contract, endpoint).
    
2.  **Discover/Bind**: Consumer queries the registry and calls via gateway (or direct).
    
3.  **Mediation**: Gateway enforces policies (auth, rate limit), transforms messages, and routes.
    
4.  **Composition**: A process (orchestrated or choreographed via events) invokes multiple services.
    
5.  **Monitoring**: Metrics/trace logs feed governance and SLOs.
    

## Consequences

**Benefits**

-   **Loose coupling** with stable contracts across heterogeneous tech.
    
-   **Reuse & standardization** of core capabilities.
    
-   **Composability** (processes spanning domains).
    
-   **Central governance** for security, compliance, and observability.
    

**Liabilities**

-   Risk of a **central bottleneck** (oversized ESB).
    
-   **Governance overhead** (versioning, approval flows).
    
-   Potential for **chatty, coarse-grained interfaces** or tight coupling to canonical models.
    
-   Increased **latency** vs. in-process calls; complex failure semantics.
    

## Implementation

### Principles

-   **Contract-first** (schema/versioning) with **backward compatibility**.
    
-   **Autonomous services** (own data, clear SLAs, explicit policies).
    
-   **Idempotent** operations & timeouts/retries with **compensation** for long-running processes.
    
-   **Security**: mTLS/OAuth2/OIDC/WS-Security; least-privilege scopes.
    
-   **Observability**: correlation IDs, tracing (W3C Trace Context), metrics/SLOs.
    
-   **Mediation**: apply at edges (gateway/ESB) — routing, transformation, protocol bridging.
    
-   **Composition**: use **orchestration** (central brain) for strict workflows; **choreography** (events) for autonomy.
    

### Practical choices

-   **Contracts**: OpenAPI/JSON Schema, gRPC/Protobuf, AsyncAPI/Avro; (legacy WSDL/XSD).
    
-   **Registry/Discovery**: service catalog (Backstage), Consul/Eureka, API Gateway catalogs.
    
-   **Mediators**: Kong, Apigee, Mule, WSO2, NGINX, Spring Cloud Gateway.
    
-   **Process**: Camunda/Flowable/Temporal (sagas), or lightweight custom orchestrators.
    
-   **Transport**: HTTP(S), AMQP/Kafka, gRPC; use events for decoupling.
    

---

## Sample Code (Java 17, framework-free)

A **minimal SOA sketch** with:

-   A **Service Bus** (mediation) + **Interceptors** (logging/auth)
    
-   A **Registry** for service lookup
    
-   Three services: `OrderService`, `PaymentService`, and a composite `CheckoutService` (orchestrator)
    
-   A client invoking the composite service via the bus
    

```java
// SoaDemo.java
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Function;

/*** Message & Contract ***/
class Message {
  final Map<String,String> headers = new LinkedHashMap<>();
  final Map<String,Object> body = new LinkedHashMap<>();
  static Message of(Object... kv){
    Message m = new Message();
    for (int i=0; i<kv.length; i+=2) m.body.put((String)kv[i], kv[i+1]);
    return m;
  }
  Message header(String k, String v){ headers.put(k, v); return this; }
  String h(String k){ return headers.get(k); }
  @SuppressWarnings("unchecked") <T> T b(String k){ return (T) body.get(k); }
}

interface Service {
  String name();
  Message handle(Message request) throws Exception; // contract: request/response message
}

/*** Registry ***/
class ServiceRegistry {
  private final Map<String, Service> services = new ConcurrentHashMap<>();
  void register(Service s){ if (services.putIfAbsent(s.name(), s)!=null) throw new IllegalStateException("duplicate "+s.name()); }
  Service resolve(String name){ var s = services.get(name); if (s==null) throw new IllegalArgumentException("service not found: "+name); return s; }
}

/*** Interceptor Chain (mediation policies) ***/
interface Interceptor {
  Message around(String serviceName, Message req, Next next) throws Exception;
  interface Next { Message proceed(String serviceName, Message req) throws Exception; }
}

class LoggingInterceptor implements Interceptor {
  public Message around(String svc, Message req, Next next) throws Exception {
    long t0 = System.nanoTime();
    try {
      var res = next.proceed(svc, req);
      long dt = (System.nanoTime()-t0)/1_000_000;
      System.out.println("[LOG] "+svc+" status="+res.headers.getOrDefault("status","200")+" in "+dt+"ms");
      return res;
    } catch (Exception e) {
      System.out.println("[LOG] "+svc+" ERROR: "+e.getMessage());
      throw e;
    }
  }
}
class AuthInterceptor implements Interceptor {
  public Message around(String svc, Message req, Next next) throws Exception {
    if (!"CheckoutService".equals(svc) && !"OrderService".equals(svc)) {
      String tok = req.h("Authorization");
      if (!"Bearer token-123".equals(tok)) {
        Message res = new Message(); res.header("status","401"); res.body.put("error","unauthorized");
        return res;
      }
    }
    return next.proceed(svc, req);
  }
}

/*** Service Bus ***/
class ServiceBus {
  private final ServiceRegistry registry;
  private final List<Interceptor> chain;
  ServiceBus(ServiceRegistry reg, List<Interceptor> interceptors){ this.registry = reg; this.chain = List.copyOf(interceptors); }

  public Message send(String serviceName, Message request) throws Exception {
    // build chain
    class Runner implements Interceptor.Next {
      private int i=0;
      public Message proceed(String svc, Message req) throws Exception {
        if (i < chain.size()) return chain.get(i++).around(svc, req, this);
        // actual invocation
        Service s = registry.resolve(svc);
        Message res = s.handle(req);
        if (!res.headers.containsKey("status")) res.header("status","200");
        return res;
      }
    }
    return new Runner().proceed(serviceName, request);
  }
}

/*** Services ***/
class OrderService implements Service {
  public String name(){ return "OrderService"; }
  public Message handle(Message req) {
    String email = req.b("email"); String sku = req.b("sku");
    String orderId = UUID.randomUUID().toString();
    Message res = Message.of("orderId", orderId, "email", email, "sku", sku);
    res.header("status","201");
    return res;
  }
}

class PaymentService implements Service {
  public String name(){ return "PaymentService"; }
  public Message handle(Message req) {
    String orderId = req.b("orderId");
    String amount = String.valueOf(req.b("amount"));
    String authId = "AUTH-" + orderId.substring(0,8);
    Message res = Message.of("authorized", true, "authId", authId, "amount", amount);
    return res;
  }
}

/** Composite service: orchestrates Order + Payment via the bus. */
class CheckoutService implements Service {
  private final ServiceBus bus;
  public CheckoutService(ServiceBus bus){ this.bus = bus; }
  public String name(){ return "CheckoutService"; }
  public Message handle(Message req) throws Exception {
    // 1) Create order
    Message orderReq = Message.of("email", req.b("email"), "sku", req.b("sku"));
    orderReq.headers.putAll(req.headers); // propagate headers (auth, corr-id)
    Message orderRes = bus.send("OrderService", orderReq);
    if (!"201".equals(orderRes.h("status"))) return orderRes;

    // 2) Charge payment
    Message payReq = Message.of("orderId", orderRes.b("orderId"), "amount", req.b("amount"));
    payReq.headers.putAll(req.headers);
    Message payRes = bus.send("PaymentService", payReq);

    // 3) Compose response
    return Message.of(
      "orderId", orderRes.b("orderId"),
      "paymentAuth", payRes.b("authId"),
      "status", "COMPLETED"
    );
  }
}

/*** Demo client ***/
public class SoaDemo {
  public static void main(String[] args) throws Exception {
    ServiceRegistry reg = new ServiceRegistry();

    // Create a bus first with interceptors; pass it to the composite service
    ServiceBus bus = new ServiceBus(reg, List.of(new LoggingInterceptor(), new AuthInterceptor()));

    // Register services (providers)
    reg.register(new OrderService());
    reg.register(new PaymentService());
    reg.register(new CheckoutService(bus)); // composite uses the same bus

    // Client (consumer) calls the composite service via the bus
    Message req = Message.of("email","alice@example.com","sku","SKU-1","amount","29.90")
      .header("Authorization","Bearer token-123")
      .header("X-Correlation-Id", UUID.randomUUID().toString());

    Message res = bus.send("CheckoutService", req);
    System.out.println("Result: status=" + res.h("status") + " body=" + res.body);
  }
}
```

**What the sample shows**

-   **Contracts** as message shapes; **registry** resolves logical names.
    
-   A **bus with interceptors** (logging, auth) acting like a lightweight gateway/ESB.
    
-   **Orchestration** (`CheckoutService`) composes two services by calling them through the bus.
    
-   **Policy** centrally enforced (AuthInterceptor) without changing service code.
    

> Productionize with: real transports (HTTP/gRPC/AMQP), schema-validated contracts, centralized gateway, service catalog, retries/circuit breaking, distributed tracing, and a workflow engine for long-running orchestration.

## Known Uses

-   **Enterprises & public sector** integrating ERP/CRM/Mainframe/SaaS via ESBs and contract-first services.
    
-   **Banks & telcos** exposing core capabilities (KYC, ledger, provisioning) as governed services.
    
-   **B2B** partner integrations where **policy & SLAs** matter (throttling, audit, non-repudiation).
    
-   **Evolution** path toward microservices (service contracts + gateways persisted; ESB scopes reduced).
    

## Related Patterns

-   **Microservices** — finer-grained services with decentralized governance; shares many ideas with SOA.
    
-   **API Gateway** — the mediation façade used by SOA and microservices alike.
    
-   **Broker Architecture** — messaging-centric mediation/routing.
    
-   **Event-Driven Architecture** — complements SOA with pub/sub and choreography.
    
-   **Saga / Process Manager** — long-running transaction orchestration in composed services.
    
-   **Canonical Data Model** — optional shared schemas for cross-domain consistency (use carefully).
    

---

## Implementation Tips

-   Start **contract-first**; automate **compatibility checks** (schema diff).
    
-   Enforce **timeouts, retries (idempotent only), and circuit breakers** at the gateway.
    
-   Keep services **coarse-grained** and **business-oriented**; avoid chatty RPC.
    
-   Prefer **events** for async steps; use **orchestration** only where necessary.
    
-   Build a **service catalog** with metadata (owners, SLAs, versions, dashboards).
    
-   Treat the ESB/gateway as a **thin mediator**, not a dumping ground for business logic.
    
-   Bake in **observability**: correlation IDs end-to-end; golden signals per service.

