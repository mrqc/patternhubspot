# Horizontal Scaling — Scalability Pattern

## Pattern Name and Classification

**Name:** Horizontal Scaling  
**Classification:** Scalability / Elasticity / Capacity Management (Scale-out at the application & data tiers)

---

## Intent

Increase system capacity and resilience by **adding more instances** of a component (service, worker, database shard, cache node) so load is **distributed across peers**. Favor **stateless scale-out** and **partitioned state** to grow throughput and reduce tail latency without a single, ever-larger box.

---

## Also Known As

-   Scale-out
    
-   N-way Replication (stateless tiers)
    
-   Shared-nothing Architecture
    
-   Horizontal Partitioning (for state/shards)
    

---

## Motivation (Forces)

-   **Throughput & latency:** A single node hits ceilings (CPU, memory, NIC, IO).
    
-   **Availability:** Many small instances reduce blast radius and allow rolling updates.
    
-   **Cost & limits:** Vertical scaling has diminishing returns, steep pricing, and hard limits.
    
-   **Elastic demand:** Traffic varies by hour/campaign/region; we need to add/remove capacity quickly.
    
-   **State vs stateless:** Scaling is easy when state is externalized; hard when state is sticky.
    

---

## Applicability

Use Horizontal Scaling when:

-   Your service can be made **stateless** (sessions, caches, uploads externalized), or its state can be **partitioned**.
    
-   Requests are **independent** or routable by a **partition key** (userId, tenantId, orderId).
    
-   You can place a **load balancer** or **work queue** in front of many workers.
    

Avoid or adapt when:

-   You require **global serialization**/strong coordination on every call.
    
-   State is **entangled** (single shared mutable dataset without partition strategy).
    
-   Workloads are tiny/bursty where a cache/CDN solves most of the problem cheaper.
    

---

## Structure

-   **Load Balancer / Router:** Distributes requests across N instances (round-robin, least-loaded, consistent hashing).
    
-   **Stateless Instances:** Identical service replicas that handle any request.
    
-   **Partitioned State (optional):** Data sharded by key across storage nodes to scale writes.
    
-   **Shared Services:** Distributed cache, object storage, queues, DB replicas/shards.
    
-   **Autoscaler:** Adjusts N based on metrics (CPU, RPS, queue depth, latency).
    
-   **Observability:** Centralized logs/metrics/traces tagged by **instance id** & **shard id**.
    

---

## Participants

-   **Clients/Producers:** Generate traffic or jobs.
    
-   **Balancer/Ingress:** ALB/NGINX/Envoy/k8s Service, or a **queue** for asynchronous work.
    
-   **Workers/Service Instances:** Stateless compute that can be replicated.
    
-   **State Stores:** DB (sharded or replicated), distributed cache, blob store.
    
-   **Autoscaling Controller:** Decides scale-out/in.
    
-   **Coordinator (optional):** For partition ownership (Kafka consumer groups, shard maps).
    

---

## Collaboration

1.  Client sends a request → **Balancer** selects an instance (or enqueues a job).
    
2.  **Instance** executes logic using externalized state (DB/cache/obj store).
    
3.  If state is partitioned, router/consumer group assigns work by **partition key**, ensuring locality/ordering.
    
4.  **Autoscaler** monitors metrics and adds/removes instances.
    
5.  Rolling updates replace instances gradually; health checks keep traffic safe.
    

---

## Consequences

**Benefits**

-   Near-linear **read** and **embarrassingly parallel** compute scaling.
    
-   **Resilience**: failures of a few instances don’t take the service down.
    
-   **Elasticity & cost**: pay for capacity you need right now.
    

**Liabilities**

-   Requires **statelessness** or **careful partitioning** of state.
    
-   **Hot keys** can concentrate load on a subset of instances/shards.
    
-   **Distributed coordination** (locks, elections) adds complexity.
    
-   **Data consistency** and cross-partition transactions get harder.
    

---

## Implementation

### Key Decisions

-   **Statelessness first:** Move session state to cookies (signed), Redis, or DB; store files in object storage; avoid in-memory affinity.
    
-   **Partitioning key:** Pick a stable key with good cardinality (userId/tenantId). Use **consistent hashing** to survive node churn.
    
-   **Work model:** Synchronous via LB for user APIs; asynchronous via **queue/stream** for heavy/long jobs.
    
-   **Idempotency & retries:** Mandatory when scaling with at-least-once deliveries.
    
-   **Backpressure:** Pair with **throttling**, **timeouts**, and **bulkheads** to avoid meltdown during scale lag.
    
-   **Autoscaling signal:** CPU, RPS/target, p95 latency, queue depth per worker.
    
-   **Data tier:** Reads scale with replicas/caches; **writes** require **shards** or batching.
    
-   **Observability:** Per-instance and per-partition metrics; request IDs for tracing across many replicas.
    

### Anti-Patterns

-   **Sticky sessions** to a node (defeats scale-out and restarts).
    
-   Scaling writes by **just** adding read replicas (write bottleneck remains).
    
-   One giant global lock or **shared mutable** in-memory map across instances.
    
-   Ignoring **hot key** mitigation (prefix randomization, caching, splitting tenants).
    
-   No **graceful drain** on scale-in → 5xx spikes.
    

---

## Sample Code (Java)

Below are two practical snippets:

### A) Stateless REST API (Spring Boot) ready for scale-out

-   Externalized sessions (none on server).
    
-   Cache-aside read to Redis.
    
-   Idempotent POST with **Idempotency-Key** header to make retries safe behind a load balancer.
    

```java
// build.gradle (snip)
// implementation 'org.springframework.boot:spring-boot-starter-web'
// implementation 'org.springframework.boot:spring-boot-starter-data-redis'
// implementation 'org.springframework.boot:spring-boot-starter-actuator'
// implementation 'org.springframework.boot:spring-boot-starter-validation'

package com.example.scaleout;

import jakarta.validation.constraints.*;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.time.Duration;
import java.util.UUID;

@SpringBootApplication
public class App { public static void main(String[] args) { SpringApplication.run(App.class, args); } }

@RestController
@RequestMapping("/v1/products")
@Validated
class ProductController {
  private final ProductRepo repo;            // e.g., JDBC/JPA repository
  private final StringRedisTemplate redis;   // distributed cache shared by all instances

  ProductController(ProductRepo repo, StringRedisTemplate redis) {
    this.repo = repo; this.redis = redis;
  }

  // GET is cache-first; all instances share Redis so the cache is warm across the fleet
  @GetMapping("/{id}")
  public ResponseEntity<ProductDto> get(@PathVariable @NotBlank String id) {
    String key = "product:v1:" + id;
    String cached = redis.opsForValue().get(key);
    if (cached != null) return ResponseEntity.ok(ProductDto.fromJson(cached));

    var dto = repo.find(id).orElse(null);
    if (dto == null) return ResponseEntity.notFound().build();
    // TTL + jitter to avoid synchronized expiry across instances
    redis.opsForValue().set(key, dto.toJson(), Duration.ofSeconds(300 + (int)(Math.random()*60)));
    return ResponseEntity.ok(dto);
  }

  // POST is idempotent by header so retries across any instance are safe
  @PostMapping
  public ResponseEntity<?> create(@RequestHeader(name = "Idempotency-Key", required = false) String idemKey,
                                  @RequestBody @Validated CreateProduct req) {
    String key = "idem:createProduct:" + (idemKey == null ? UUID.randomUUID() : idemKey);
    Boolean first = redis.opsForValue().setIfAbsent(key, "PENDING", Duration.ofMinutes(10));
    if (Boolean.FALSE.equals(first)) {
      // Already processed or in-flight: return previously stored result or 202
      String status = redis.opsForValue().get(key);
      return "SUCCEEDED".equals(status)
          ? ResponseEntity.status(201).build()
          : ResponseEntity.accepted().build();
    }

    repo.insert(req.toDto()); // write to DB (source of truth)
    // invalidate cache entry so all instances see the new value on next GET
    redis.delete("product:v1:" + req.id());
    redis.opsForValue().set(key, "SUCCEEDED", Duration.ofMinutes(10));
    return ResponseEntity.status(201).build();
  }
}

record CreateProduct(@NotBlank String id, @NotBlank String name) {
  ProductDto toDto(){ return new ProductDto(id, name); }
}
record ProductDto(String id, String name) {
  static ProductDto fromJson(String s){ return new com.fasterxml.jackson.databind.ObjectMapper().readValue(s, ProductDto.class); }
  String toJson(){ try { return new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(this); } catch(Exception e){ throw new RuntimeException(e); } }
}

interface ProductRepo { java.util.Optional<ProductDto> find(String id); void insert(ProductDto p); }
```

**Why this scales horizontally**

-   No server sessions; any instance can serve any request.
    
-   Shared Redis makes cache warm across instances.
    
-   Idempotent create shields against duplicate effects under retries behind an ALB/API gateway.
    
-   Add instances → LB spreads load; remove instances → no affinity breakage.
    

---

### B) Parallel Workers via Kafka Consumer Group (scale by adding pods)

-   Each worker instance joins a **consumer group**; partitions are distributed across instances.
    
-   Throughput increases with more instances (bounded by partition count).
    
-   Idempotent processing to handle rebalances/retries.
    

```java
// build.gradle (snip)
// implementation 'org.springframework.kafka:spring-kafka'

package com.example.scaleout;

import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

@Component
public class OrderWorker {

  private final OrderService service;
  public OrderWorker(OrderService service) { this.service = service; }

  // Scale horizontally by running N replicas of this app; Kafka partitions are shared across them
  @KafkaListener(topics = "orders", groupId = "order-workers")
  public void onMessage(ConsumerRecord<String, String> rec) {
    // Use a stable idempotency key (e.g., orderId) so replays during rebalance are safe
    String orderId = rec.key();
    service.processOrderIdempotently(orderId, rec.value());
  }
}

interface OrderService { void processOrderIdempotently(String orderId, String payload); }
```

**Why this scales horizontally**

-   Adding instances increases the number of concurrently processed partitions.
    
-   Failures cause partitions to reassign to healthy instances.
    
-   Idempotent handler guarantees correctness under at-least-once delivery.
    

---

## Known Uses

-   **Web/API tiers**: many stateless service replicas behind a load balancer.
    
-   **Stream processing**: Kafka consumer groups, Flink/Spark executors scaled by partition/parallelism.
    
-   **Background workers**: SQS/RabbitMQ/NATS queues with autoscaled consumers.
    
-   **Data tiers**: sharded databases (horizontal partitioning) and distributed caches/clusters.
    
-   **CDNs & edge**: horizontally scaled edge POPs serving static/dynamic content.
    

---

## Related Patterns

-   **Auto Scaling Group**: automates adding/removing instances based on metrics.
    
-   **Database Replication**: scales reads; combine with horizontal app scale.
    
-   **Sharding (Horizontal Partitioning)**: scales write throughput by splitting data.
    
-   **Distributed Cache / Cache Aside**: offload hot reads to scale further.
    
-   **Idempotent Receiver**: mandatory for safe retries across many replicas.
    
-   **Throttling / Circuit Breaker / Timeout**: protect during scale lag or partial failures.
    
-   **Leader Election**: when a singleton task must run within a scaled fleet.
    

---

## Implementation Checklist

-   Make the service **stateless** (sessions/files/executions externalized).
    
-   Choose **partition keys** and routing (consistent hash, queues, or LB).
    
-   Implement **idempotency** for writes & background jobs.
    
-   Add **health checks** (liveness/readiness) and **graceful drain** on shutdown.
    
-   Configure **autoscaling** signals aligned with user SLOs (CPU, RPS, p95, queue depth).
    
-   Plan for **hot keys** (cache, split tenants, randomize prefixes).
    
-   Externalize **configuration** and secrets; replicas are identical but parameterized.
    
-   Instrument **per-instance** and **per-partition** metrics; trace with request IDs.
    
-   Validate under load: cold starts, rolling deploys, failover, N+1 scaling efficiency.

