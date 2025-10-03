# Service Registry — Microservice Pattern

## Pattern Name and Classification

-   **Name:** Service Registry
    
-   **Classification:** Service Discovery & Networking Pattern (infrastructure/platform)
    

## Intent

Provide a **directory of live service instances** (name → endpoints/metadata) that clients can **discover at runtime** instead of using fixed hostnames. Enables **dynamic scaling**, **resilience**, and **zero-downtime** deployments.

## Also Known As

-   Service Discovery
    
-   Registry/Directory
    
-   Name Service for Microservices
    

## Motivation (Forces)

-   **Dynamic infrastructure:** Containers scale up/down; IPs change frequently.
    
-   **Zero-downtime rollouts:** Need to route around draining or unhealthy instances.
    
-   **Multi-zone/regional routing:** Prefer local instances for latency and cost.
    
-   **Polyglot stacks:** Central directory avoids hard-coding endpoints across languages.
    
-   **Least surprise:** Operators want one place to see what’s registered, where, and why it’s failing.
    

**Tensions**

-   **Consistency vs. freshness:** Registries are eventually consistent; clients must tolerate small staleness.
    
-   **Central point of failure:** The registry must be highly available or cached.
    
-   **Who registers?:** Apps, sidecars/agents, or the platform (e.g., Kubernetes) — trade-offs in control and complexity.
    

## Applicability

Use when:

-   Instances are **ephemeral** (containers/VMs/FCs) and scale elastically.
    
-   You need **client-side load balancing** and **zone-aware** routing.
    
-   Multiple runtimes (Java, Node, Go, …) must discover each other uniformly.
    

Reconsider when:

-   You’re on **Kubernetes** and simple **cluster DNS** discovery suffices (no external LB or advanced filters needed).
    
-   A **service mesh** or managed platform already provides discovery and traffic policy end-to-end.
    

## Structure

Two discovery styles:

**Client-side discovery (via registry):**

```scss
Client → Registry (lookup: catalog) → [ip:port, …]
        ↳ choose instance (zone-aware, LB policy)
        ↳ call instance directly
```

**Server-side discovery (via LB/gateway):**

```arduino
Client → L4/L7 Load Balancer → (LB queries registry) → pick instance → forward
```

Additional concerns:

-   **Self-registration vs. 3rd-party registration:** service registers itself vs. an agent/platform does it.
    
-   **Health checks:** TTL heartbeats or active HTTP/TCP checks.
    
-   **Metadata:** version, zone, canary flag, capabilities.
    

## Participants

-   **Service Instance:** Process/container exposing health and metadata.
    
-   **Service Registry:** Stores service → instances (Eureka, Consul, Zookeeper, AWS Cloud Map, etc.).
    
-   **Registrar:** Client library, sidecar, or platform controller that performs register/renew/deregister.
    
-   **Discovery Client / Load Balancer:** Resolves name to instances and picks one.
    
-   **Health Checker:** Validates liveness/readiness and prunes failing instances.
    

## Collaboration

1.  Instance **registers** on startup (with name, `ip:port`, metadata).
    
2.  Instance **renews lease** (heartbeat/TTL).
    
3.  On **SIGTERM/drain**, instance **deregisters** or flips to `OUT_OF_SERVICE`; traffic drains.
    
4.  Clients **resolve** service name → get **instance list**, apply **LB policy** (zone, version, canary), and call.
    
5.  Registry prunes **expired** instances; health checker updates status.
    

## Consequences

**Benefits**

-   Decouples clients from concrete addresses → **elastic scaling**.
    
-   Enables **zone-aware**, **version-aware**, and **canary-aware** routing.
    
-   Central visibility of fleet health.
    

**Liabilities**

-   Extra moving part (availability, backup/restore).
    
-   **Stale caches** can cause brief 5xx if not guarded with retries/timeouts.
    
-   Security & multi-tenant concerns (who can register/resolve what).
    

## Implementation

1.  **Choose topology:** Client-side (Eureka/Consul + client LB) or server-side (LB integrates registry).
    
2.  **Registration path:** Self-registration (library) vs. agent/platform (e.g., Consul agent, K8s controllers).
    
3.  **Health semantics:**
    
    -   **Readiness** gates traffic; **liveness** restarts instance.
        
    -   Prefer **deregister on shutdown** + **drain** windows.
        
4.  **Metadata & routing:** Add zone, version, canary labels; implement selection policy.
    
5.  **Resilience:** Cache results, set TTLs, **retry with jitter**, and enforce **deadline** per request.
    
6.  **Security:** mTLS or signed requests to registry; ACLs on namespaces/services.
    
7.  **Observability:** Export **registered count**, **renewal lag**, **stale ratio**, **resolution latency**; trace lookups.
    
8.  **Kubernetes note:** If you run on K8s and don’t need dynamic policy, **use DNS** (`http://catalog.namespace.svc.cluster.local`) and readiness gates; add a mesh if you need L7 policy.
    

---

## Sample Code (Java, Spring Boot 3.x) — Eureka Registry + Client-side Discovery (with Spring Cloud LoadBalancer)

Below is a minimal end-to-end setup:

1.  a **Registry** (Eureka Server),
    
2.  a **Producer** service (Catalog) registering itself,
    
3.  a **Consumer** (Orders) that resolves `catalog-service` by name and calls it with client-side load balancing.
    

> Uses `spring-cloud-starter-loadbalancer` (Ribbon-free) and Eureka client/server.

### 1) Registry (Eureka Server)

**pom.xml (snippets)**

```xml
<dependencies>
  <dependency>
    <groupId>org.springframework.cloud</groupId>
    <artifactId>spring-cloud-starter-netflix-eureka-server</artifactId>
  </dependency>
</dependencies>
```

**Application**

```java
// RegistryApplication.java
package registry;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cloud.netflix.eureka.server.EnableEurekaServer;

@SpringBootApplication
@EnableEurekaServer
public class RegistryApplication {
  public static void main(String[] args) {
    SpringApplication.run(RegistryApplication.class, args);
  }
}
```

**application.yml**

```yaml
server:
  port: 8761

eureka:
  client:
    register-with-eureka: false
    fetch-registry: false
  server:
    eviction-interval-timer-in-ms: 30000
    renewal-threshold-update-interval-ms: 15000
```

### 2) Producer service (Catalog) — registers itself

**pom.xml (snippets)**

```xml
<dependencies>
  <dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-web</artifactId>
  </dependency>
  <dependency>
    <groupId>org.springframework.cloud</groupId>
    <artifactId>spring-cloud-starter-netflix-eureka-client</artifactId>
  </dependency>
</dependencies>
```

**Application**

```java
// CatalogApplication.java
package catalog;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class CatalogApplication {
  public static void main(String[] args) { SpringApplication.run(CatalogApplication.class, args); }
}
```

**API + Health**

```java
// ProductController.java
package catalog;

import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/products")
public class ProductController {
  @GetMapping("/{sku}")
  public Product get(@PathVariable String sku) {
    return new Product(sku, "Example " + sku, 1999);
  }
  record Product(String sku, String name, int priceCents) {}
}
```

**application.yml**

```yaml
spring:
  application:
    name: catalog-service

server:
  port: 0  # random port → many instances per node

eureka:
  client:
    service-url:
      defaultZone: http://localhost:8761/eureka/
  instance:
    prefer-ip-address: true
    lease-renewal-interval-in-seconds: 10
    lease-expiration-duration-in-seconds: 30
# graceful shutdown & drain
server.shutdown: graceful
spring.lifecycle.timeout-per-shutdown-phase: 20s
management.endpoints.web.exposure.include: health,info
```

### 3) Consumer service (Orders) — resolves by logical name + LB

**pom.xml (snippets)**

```xml
<dependencies>
  <dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-web</artifactId>
  </dependency>
  <dependency>
    <groupId>org.springframework.cloud</groupId>
    <artifactId>spring-cloud-starter-netflix-eureka-client</artifactId>
  </dependency>
  <dependency>
    <groupId>org.springframework.cloud</groupId>
    <artifactId>spring-cloud-starter-loadbalancer</artifactId>
  </dependency>
```

**LB-aware WebClient**

```java
// HttpConfig.java
package orders;

import org.springframework.cloud.client.loadbalancer.LoadBalanced;
import org.springframework.context.annotation.*;
import org.springframework.web.reactive.function.client.WebClient;

@Configuration
public class HttpConfig {
  @Bean
  @LoadBalanced
  WebClient.Builder loadBalancedWebClientBuilder() {
    return WebClient.builder(); // resolves "http://catalog-service" via registry
  }
}
```

**Consumer**

```java
// OrdersApplication.java
package orders;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class OrdersApplication {
  public static void main(String[] args) { SpringApplication.run(OrdersApplication.class, args); }
}
```

```java
// OrdersController.java
package orders;

import org.springframework.web.bind.annotation.*;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

@RestController
@RequestMapping("/orders")
public class OrdersController {
  private final WebClient.Builder http;

  public OrdersController(WebClient.Builder http) { this.http = http; }

  @GetMapping("/{sku}")
  public Mono<String> place(@PathVariable String sku) {
    // Service name, not host: the LB picks an instance from the registry
    return http.build().get()
        .uri("http://catalog-service/products/{sku}", sku)
        .retrieve()
        .bodyToMono(String.class)
        .map(body -> "ORDER_OK for " + sku + " with product=" + body);
  }
}
```

**application.yml**

```yaml
spring:
  application:
    name: orders-service

eureka:
  client:
    service-url:
      defaultZone: http://localhost:8761/eureka/

server:
  port: 8080
```

> **How it works:**
>
> -   Catalog registers itself with Eureka (random port); keeps renewing its lease.
>
> -   Orders calls `http://catalog-service/...`; Spring Cloud LoadBalancer resolves instances from Eureka and picks one (round-robin by default).
>
> -   On shutdown, Catalog performs graceful shutdown; Eureka stops advertising it after lease expiry or explicit deregistration.
>

---

### Alternative: Consul (agent-based) quick notes

**Dependencies**

```xml
<dependency>
  <groupId>org.springframework.cloud</groupId>
  <artifactId>spring-cloud-starter-consul-discovery</artifactId>
</dependency>
```

**application.yml**

```yaml
spring:
  application.name: catalog-service
  cloud.consul.host: localhost
  cloud.consul.port: 8500
  cloud.consul.discovery:
    register: true
    prefer-ip-address: true
    heartbeat:
      enabled: true
```

**Use the same `@LoadBalanced WebClient.Builder`** and call `http://catalog-service/...`.

---

## Known Uses

-   **Netflix** Eureka for client-side discovery at scale.

-   **HashiCorp Consul** (agent + catalog + health checks) in multi-platform estates.

-   **Zookeeper/etcd** for service directories and coordination.

-   **AWS Cloud Map**, **GCP Service Directory**, **Azure App Configuration/Service Discovery** in managed clouds.

-   **Kubernetes** core DNS as the de-facto registry inside clusters (often augmented by a mesh).


## Related Patterns

-   **Client-side Load Balancing:** Pairs with a registry to select instances.

-   **Service Mesh:** May subsume discovery; the mesh control plane feeds sidecars.

-   **API Gateway:** Handles north-south while registry handles east-west.

-   **Health Check / Readiness Probe:** Drives registry presence.

-   **Circuit Breaker / Retry / Timeout:** Complement lookups for resilient calls.

-   **Service Per Team / Database Per Service:** Organizational/data boundaries that discovery routes between.
