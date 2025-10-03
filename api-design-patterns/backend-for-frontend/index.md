# Backend for Frontend (BFF) — Design Pattern

## Pattern Name and Classification

**Backend for Frontend (BFF)** — *Edge/API shaping pattern* that creates a **client-specific backend** for web, mobile, or other channels.

---

## Intent

Provide a **dedicated backend** per frontend (Web, iOS, Android, partner app) that **adapts/aggregates/optimizes** APIs, payloads, and policies to the needs of that client—without leaking channel-specific concerns into domain services.

---

## Also Known As

-   **Per-Client API**

-   **Channel Gateway**

-   **API Facade per UI**


---

## Motivation (Forces)

-   Different UIs need **different shapes** of the same data (fields, nesting, sort/filters).

-   Mobile needs **smaller payloads**, aggressive caching, and **fewer round trips**.

-   Security and **rate limits** differ per channel.

-   Avoid coupling UIs directly to **service topology** and churn.

-   Keep domain services **clean** of presentation logic.


---

## Applicability

Use BFF when:

-   You have **multiple frontends** with distinct requirements.

-   You need **composition/transformation** close to the client.

-   Client evolution is **faster** than core services.

-   Per-channel **security** and **rate limiting** are required.


Avoid / limit BFF when:

-   You can serve all channels with a single, stable **API Gateway** and minor differences.

-   The BFF starts accumulating **domain logic** (smell: “edge monolith”).


---

## Structure

```less
Web App ─────────┐
                             ├─>  [ Web BFF ]  ──┐
Mobile App ────────────────┐ │                   ├─> [ Orders Service ]
                           └─┼─> [ Mobile BFF ] ─┤
Partner/3rd Party ───────────┘                   ├─> [ Payments Service ]
                                                 └─> [ Shipping Service ]
(Each BFF: auth, throttle, compose, transform, cache, version)
```

---

## Participants

-   **Frontend Client** (Web/Mobile/Partner)

-   **BFF** (per client/channel): composition, transformation, policy enforcement

-   **Downstream Services** (Orders/Payments/Shipping/…)

-   **Support Systems** (IdP for OAuth/OIDC, cache/Redis, tracing/metrics)


---

## Collaboration

1.  Client calls **channel-specific** endpoint on its BFF.

2.  BFF authenticates/authorizes, **fans out** to services (parallel), transforms payload.

3.  BFF applies **caching**, **ETags**, and **rate limits** per client.

4.  Returns a **tailored** response to the client.


---

## Consequences

**Benefits**

-   Client-optimized APIs (smaller payloads, fewer calls).

-   Encapsulates service topology; **faster UI iteration**.

-   Clear place for **channel policies** (authz, limits, A/B, canary).


**Liabilities**

-   More deployables (one BFF per channel).

-   Risk of **duplicated** composition across BFFs.

-   Potential **hotspot** if under-scaled; must stay free of domain logic.


---

## Implementation (Key Points)

-   Keep BFF **stateless**; externalize cache/rate-limit counters.

-   Build with **non-blocking** IO (WebFlux/Netty) for fan-out.

-   Add **per-call timeouts**, **retries**, **circuit breakers**.

-   **Shape** responses explicitly (DTOs), version your endpoints.

-   Add **ETag/Cache-Control** and conditional gets for mobile.

-   Propagate **trace IDs** and respect **idempotency** on POSTs.


---

## Sample Code (Java, Spring Boot WebFlux — “Mobile BFF”)

> A minimal BFF that exposes a **mobile-friendly order details** endpoint.  
> It composes **Orders + Payments + Shipping**, trims fields, adds **ETag**, and handles degraded responses.

**Gradle (snippets)**

```gradle
implementation "org.springframework.boot:spring-boot-starter-webflux"
implementation "io.github.resilience4j:resilience4j-spring-boot3"
implementation "org.springframework.boot:spring-boot-starter-oauth2-resource-server"
implementation "com.fasterxml.jackson.core:jackson-databind"
```

**DTOs (mobile-shaped)**

```java
import java.util.List;

record OrderDto(String orderId, String status, List<String> items) {}
record PaymentDto(String orderId, String state) {}
record ShipmentDto(String orderId, String carrier, String tracking) {}

record MobileOrderDetails(
    String id,
    String status,
    int itemCount,
    String payment,
    String tracking
) {}
```

**Downstream Clients**

```java
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;
import java.time.Duration;

@Component
class Downstreams {
  private final WebClient orders  = WebClient.builder().baseUrl("http://orders:8080").build();
  private final WebClient pays    = WebClient.builder().baseUrl("http://payments:8080").build();
  private final WebClient ship    = WebClient.builder().baseUrl("http://shipping:8081").build();

  Mono<OrderDto>   order(String id)   { return orders.get().uri("/orders/{id}", id)
      .retrieve().bodyToMono(OrderDto.class).timeout(Duration.ofSeconds(2)); }
  Mono<PaymentDto> payment(String id) { return pays.get().uri("/payments/by-order/{id}", id)
      .retrieve().bodyToMono(PaymentDto.class).timeout(Duration.ofSeconds(2)); }
  Mono<ShipmentDto> shipment(String id){ return ship.get().uri("/shipments/by-order/{id}", id)
      .retrieve().bodyToMono(ShipmentDto.class).timeout(Duration.ofSeconds(2)); }
}
```

**BFF Service (composition + shaping + ETag)**

```java
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;

@Service
class MobileBffService {

  private final Downstreams ds;

  MobileBffService(Downstreams ds) { this.ds = ds; }

  @CircuitBreaker(name="mobileBFF", fallbackMethod="fallback")
  public Mono<MobileOrderDetails> getOrderDetails(String id) {
    Mono<OrderDto> o = ds.order(id);
    Mono<PaymentDto> p = ds.payment(id).onErrorReturn(new PaymentDto(id, "UNKNOWN"));
    Mono<ShipmentDto> s = ds.shipment(id).onErrorReturn(new ShipmentDto(id, null, null));

    return Mono.zip(o, p, s).map(t -> {
      OrderDto od = t.getT1(); PaymentDto pd = t.getT2(); ShipmentDto sd = t.getT3();
      return new MobileOrderDetails(
          od.orderId(),
          od.status(),
          od.items() != null ? od.items().size() : 0,
          pd.state(),
          sd.tracking()
      );
    });
  }

  Mono<MobileOrderDetails> fallback(String id, Throwable ex) {
    return Mono.just(new MobileOrderDetails(id, "UNKNOWN", 0, "UNKNOWN", null));
  }
}
```

**Controller (adds ETag/Cache headers; scope-based auth)**

```java
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Base64;

@RestController
@RequestMapping("/mobile")
class MobileBffController {

  private final MobileBffService svc;

  MobileBffController(MobileBffService svc) { this.svc = svc; }

  @GetMapping(value="/orders/{id}/details", produces=MediaType.APPLICATION_JSON_VALUE)
  public Mono<ResponseEntity<MobileOrderDetails>> get(@PathVariable String id,
                                                      @RequestHeader(value="If-None-Match", required=false) String inm) {
    return svc.getOrderDetails(id).map(body -> {
      String etag = etagOf(body);
      if (etag.equals(inm)) {
        return ResponseEntity.status(304).eTag(etag).build();
      }
      return ResponseEntity.ok()
          .eTag(etag)
          .header("Cache-Control", "public,max-age=30") // small TTL for mobile
          .body(body);
    });
  }

  private static String etagOf(MobileOrderDetails v) {
    try {
      MessageDigest md = MessageDigest.getInstance("SHA-256");
      byte[] digest = md.digest((v.id()+v.status()+v.itemCount()+v.payment()+v.tracking())
          .getBytes(StandardCharsets.UTF_8));
      return "\"W/\"" + Base64.getUrlEncoder().withoutPadding().encodeToString(digest);
    } catch (Exception e) { return "\"0\""; }
  }
}
```

**Security (WebFlux Resource Server)**

```java
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.web.server.ServerHttpSecurity;
import org.springframework.security.web.server.SecurityWebFilterChain;

@Configuration
class SecurityConfig {
  @Bean
  SecurityWebFilterChain filter(ServerHttpSecurity http) {
    return http.csrf(ServerHttpSecurity.CsrfSpec::disable)
      .authorizeExchange(ex -> ex
        .pathMatchers("/mobile/**").hasAuthority("SCOPE_mobile.read")
        .anyExchange().authenticated())
      .oauth2ResourceServer(oauth -> oauth.jwt())
      .build();
  }
}
```

**Resilience4j (example)**

```yaml
resilience4j:
  circuitbreaker:
    instances:
      mobileBFF:
        sliding-window-size: 50
        failure-rate-threshold: 50
        wait-duration-in-open-state: 5s
  retry:
    instances:
      mobileBFF:
        max-attempts: 3
        wait-duration: 100ms
```

---

## Known Uses

-   **Spotify** (separate BFFs per platform), **Airbnb**, **Netflix** (per-device APIs), many enterprises using **BFFs** for web vs. mobile with tailored payloads and policies.


---

## Related Patterns

-   **API Gateway** — a shared edge; a BFF is a *specialized* gateway per client.

-   **API Composition** — BFF often performs composition for read views.

-   **API Orchestration / Process Manager** — command-side coordination (business flows).

-   **Circuit Breaker / Retry / Timeout / Bulkhead** — resilience for fan-out calls.

-   **Caching / CDN** — combine with ETags and conditional requests for mobile.

ChatGPT:

Fill out the following chapters for the API Design Pattern "Bulk API". Provide a sample code in Java: Pattern Name and Classification, Intent, Also Known As, Motivation (Forces), Applicability, Structure, Participants, Collaboration, Consequences, Implementation, Sample Code, Known Uses, Related Patterns

You:

# Bulk API — Design Pattern

## Pattern Name and Classification

**Bulk API** — *API design / batching & throughput optimization* pattern for high-volume create/update/delete/read operations.

---

## Intent

Enable clients to **submit or retrieve many records in a single request** (or job) with **controlled throughput**, **partial success reporting**, and **idempotency**, reducing chattiness and improving overall efficiency.

---

## Also Known As

-   **Batch API**

-   **Bulk Import/Export**

-   **Mass Operations API**

-   **Asynchronous Job API** (when operations are queued)


---

## Motivation (Forces)

-   UIs/integrations need to **sync thousands to millions** of items.

-   Per-item REST calls cause **excessive latency**, **rate-limit hits**, and **connection overhead**.

-   Need **partial success**, **error details per item**, **ordering guarantees**, **idempotency**, and sometimes **exactly-once** semantics (or practical at-least-once with dedupe).

-   Large payloads demand **streaming**, **chunking**, and often **asynchronous** processing with status endpoints.


---

## Applicability

Use Bulk API when:

-   Import/export, nightly sync, or migration requires **high-volume data transfer**.

-   You must return **per-record results** (IDs, errors) and handle **partial failures**.

-   You want to **minimize API gateway/round-trip overhead**.


Avoid/limit when:

-   Real-time latency per record is critical (consider **streaming/events**).

-   Payload sizes exceed practical HTTP limits and you can use **object storage pre-signed URLs** + **asynchronous ingestion** instead.


---

## Structure

```bash
Client
  | POST /bulk/{resource}          (small batch → sync response)
  | POST /bulk/{resource}/jobs     (large batch → 202 Accepted, jobId)
  | PUT  /bulk/jobs/{jobId}/parts  (multipart/chunk upload or S3 URL manifest)
  | GET  /bulk/jobs/{jobId}/status (progress: queued/running/succeeded/failed, counts)
  | GET  /bulk/jobs/{jobId}/result (NDJSON/CSV with per-item outcome)
  | PATCH/DELETE /bulk/jobs/{jobId} (cancel/expire)

Server
  - Ingestion Controller  - Job Queue / Scheduler - Workers (concurrency, backpressure)
  - Idempotency Store     - Result Store (DLQ/Errors) - Observability (metrics/tracing)
```

---

## Participants

-   **Client/Integrator** — submits batches, polls for status, downloads results.

-   **Bulk API** — validates, accepts payloads, creates jobs.

-   **Job Store / Queue** — persists job metadata & state, schedules work.

-   **Workers** — process items with concurrency & retries.

-   **Idempotency Store** — deduplicates by keys (request or item level).

-   **Result Store** — per-item outcome (success/error); optional DLQ.


---

## Collaboration

1.  Client sends **bulk request** (sync for small batches; async job for large).

2.  Server validates envelope, stores job, starts workers.

3.  Workers process items with **bounded concurrency**, **retries**, **idempotency**.

4.  Client polls **status**; when finished, downloads **per-item results**.

5.  Failures include actionable error codes and indices; client can **resubmit only failed** items.


---

## Consequences

**Benefits**

-   Fewer round-trips → **higher throughput**.

-   **Partial success** with clear error reporting.

-   Supports **idempotency** and **resume** on failure.

-   Can be **asynchronous** to protect backends.


**Liabilities**

-   Larger requests → need **streaming**, **limits**, **backpressure**.

-   More moving parts (jobs, storage, retries, DLQ).

-   Complex **versioning** of bulk formats and **schema evolution**.


---

## Implementation (Key Points)

-   **Formats**: NDJSON (streamable), CSV, or newline-delimited Protobuf; compress with **gzip**.

-   **Sync vs Async**: small batches synchronously; large batches as **202 Accepted** job.

-   **Idempotency**: header `Idempotency-Key` for the request; per-item `dedupeKey` to prevent duplicates.

-   **Concurrency & Backpressure**: bounded worker pools; retry with **exponential backoff + jitter**; dead-letter on persistent failure.

-   **Partial Results**: include `index`, `id`, `status`, `errorCode`, `errorMessage`.

-   **Observability**: metrics (throughput, success rate), tracing, and correlation IDs.

-   **Limits**: per-request max items/bytes; per-tenant quotas; rate limiting.

-   **Security**: authz scopes for bulk ops; validate schemas rigorously.


---

## Sample Code (Java, Spring WebFlux, NDJSON; Sync + Async Job)

> Minimal, production-style sketch: sync endpoint for small batches, async job for large files; per-item results with idempotency. (Omit persistence wiring for brevity.)

**Gradle dependencies (snippets)**

```gradle
implementation "org.springframework.boot:spring-boot-starter-webflux"
implementation "io.github.resilience4j:resilience4j-spring-boot3"
implementation "com.fasterxml.jackson.core:jackson-databind"
```

**DTOs**

```java
// Input item for upsert; includes an optional per-item idempotency key
public record ProductUpsert(String externalId, String name, int priceCents, String dedupeKey) {}

public enum JobState { QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELED }

public record BulkResultItem(int index, String externalId, String status,
                             String id, String errorCode, String errorMessage) {}

public record BulkSyncResponse(int total, int succeeded, int failed,
                               java.util.List<BulkResultItem> results) {}

public record JobMeta(String jobId, JobState state, int received, int processed,
                      int succeeded, int failed, String resultDownloadUrl) {}
```

**Sync Endpoint (NDJSON streaming in, JSON out)**

```java
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ServerWebInputException;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

@RestController
@RequestMapping("/bulk/products")
class BulkProductsController {

  private final ObjectMapper om = new ObjectMapper();
  private final ProductService productService;

  BulkProductsController(ProductService svc) { this.productService = svc; }

  // Accepts NDJSON lines of ProductUpsert; limits to 1000 for sync demo
  @PostMapping(value = "", consumes = "application/x-ndjson", produces = MediaType.APPLICATION_JSON_VALUE)
  public Mono<BulkSyncResponse> upsertNdjson(@RequestHeader(value="Idempotency-Key", required=false) String idemKey,
                                             @RequestBody Flux<String> ndjson) {
    final AtomicInteger idx = new AtomicInteger(0);
    final List<BulkResultItem> results = new ArrayList<>();
    final int MAX_SYNC = 1000;

    return ndjson
      .take(MAX_SYNC + 1L)
      .switchIfEmpty(Flux.error(new ServerWebInputException("Empty NDJSON")))
      .index() // (index, line)
      .concatMap(tuple -> {
        long i = tuple.getT1();
        String line = tuple.getT2();
        if (i >= MAX_SYNC) return Mono.error(new ServerWebInputException("Too many items for sync"));
        try {
          ProductUpsert in = om.readValue(line, ProductUpsert.class);
          return productService.upsert(in, idemKey)
            .timeout(Duration.ofSeconds(2))
            .map(id -> new BulkResultItem((int)i, in.externalId(), "OK", id, null, null))
            .onErrorResume(e -> Mono.just(new BulkResultItem((int)i, in.externalId(), "ERROR", null, "UPSERT_FAILED", e.getMessage())));
        } catch (Exception parse) {
          return Mono.just(new BulkResultItem((int)i, null, "ERROR", null, "PARSE_ERROR", parse.getMessage()));
        }
      }, /*concurrency*/ 32, /*prefetch*/ 64)
      .doOnNext(results::add)
      .then(Mono.fromSupplier(() -> {
        int ok = (int) results.stream().filter(r -> "OK".equals(r.status())).count();
        int err = results.size() - ok;
        return new BulkSyncResponse(results.size(), ok, err, results);
      }));
  }
}
```

**Service with Per-Item Idempotency Stub**

```java
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

@Service
class ProductService {
  // demo stores
  private final Map<String,String> idempotencyItemStore = new ConcurrentHashMap<>(); // dedupeKey -> productId
  private final Map<String,String> productStore = new ConcurrentHashMap<>(); // externalId -> productId

  Mono<String> upsert(ProductUpsert in, String requestIdempotencyKey) {
    // per-item idempotency
    if (in.dedupeKey() != null && idempotencyItemStore.containsKey(in.dedupeKey())) {
      return Mono.just(idempotencyItemStore.get(in.dedupeKey()));
    }
    // pretend to write to DB
    String productId = productStore.computeIfAbsent(in.externalId(), k -> "p_" + Math.abs(k.hashCode()));
    // simulate update
    if (in.dedupeKey() != null) idempotencyItemStore.putIfAbsent(in.dedupeKey(), productId);
    return Mono.just(productId);
  }
}
```

**Async Job Endpoints (outline)**

```java
@RestController
@RequestMapping("/bulk/jobs")
class BulkJobsController {

  private final JobService jobs;

  BulkJobsController(JobService jobs) { this.jobs = jobs; }

  // Client creates a job (metadata). For big uploads, send manifest or upload to storage and reference URL.
  @PostMapping(produces = MediaType.APPLICATION_JSON_VALUE)
  public Mono<JobMeta> createJob(@RequestParam String resource, @RequestParam(required=false) String uploadUrl) {
    return jobs.create(resource, uploadUrl);
  }

  // Stream parts (NDJSON) into the job
  @PutMapping(value="/{jobId}/parts", consumes = "application/x-ndjson", produces = MediaType.APPLICATION_JSON_VALUE)
  public Mono<JobMeta> uploadPart(@PathVariable String jobId, @RequestBody Flux<String> ndjson) {
    return jobs.append(jobId, ndjson);
  }

  // Start processing
  @PostMapping("/{jobId}/start")
  public Mono<JobMeta> start(@PathVariable String jobId) { return jobs.start(jobId); }

  @GetMapping("/{jobId}/status")
  public Mono<JobMeta> status(@PathVariable String jobId) { return jobs.status(jobId); }

  // Download results as NDJSON (per-item outcome)
  @GetMapping(value="/{jobId}/result", produces="application/x-ndjson")
  public Flux<String> result(@PathVariable String jobId) { return jobs.resultNdjson(jobId); }
}
```

**JobService (simplified in-memory pipeline)**

```java
import org.springframework.stereotype.Service;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.util.Map;
import java.util.Queue;
import java.util.UUID;
import java.util.concurrent.*;

@Service
class JobService {
  private final Map<String, JobMeta> jobs = new ConcurrentHashMap<>();
  private final Map<String, Queue<String>> jobParts = new ConcurrentHashMap<>();
  private final Map<String, Queue<BulkResultItem>> jobResults = new ConcurrentHashMap<>();
  private final ExecutorService pool = Executors.newFixedThreadPool(Math.max(4, Runtime.getRuntime().availableProcessors()));
  private final ProductService productService;
  JobService(ProductService ps) { this.productService = ps; }

  Mono<JobMeta> create(String resource, String uploadUrl) {
    String id = UUID.randomUUID().toString();
    JobMeta meta = new JobMeta(id, JobState.QUEUED, 0, 0, 0, 0, null);
    jobs.put(id, meta);
    jobParts.put(id, new ConcurrentLinkedQueue<>());
    jobResults.put(id, new ConcurrentLinkedQueue<>());
    return Mono.just(meta);
  }

  Mono<JobMeta> append(String jobId, Flux<String> ndjson) {
    Queue<String> q = jobParts.get(jobId);
    return ndjson.doOnNext(q::add)
      .then(Mono.defer(() -> {
        JobMeta m = jobs.get(jobId);
        JobMeta upd = new JobMeta(m.jobId(), m.state(), m.received() + q.size(), m.processed(), m.succeeded(), m.failed(), m.resultDownloadUrl());
        jobs.put(jobId, upd);
        return Mono.just(upd);
      }));
  }

  Mono<JobMeta> start(String jobId) {
    JobMeta m = jobs.get(jobId);
    JobMeta running = new JobMeta(m.jobId(), JobState.RUNNING, m.received(), 0, 0, 0, null);
    jobs.put(jobId, running);

    pool.submit(() -> process(jobId)); // fire-and-forget background worker for demo
    return Mono.just(running);
  }

  private void process(String jobId) {
    Queue<String> parts = jobParts.get(jobId);
    Queue<BulkResultItem> out = jobResults.get(jobId);

    AtomicInteger idx = new AtomicInteger(0);
    parts.parallelStream().forEach(line -> {
      int i = idx.getAndIncrement();
      try {
        ProductUpsert in = new com.fasterxml.jackson.databind.ObjectMapper().readValue(line, ProductUpsert.class);
        String id = productService.upsert(in, null).block(); // demo
        out.add(new BulkResultItem(i, in.externalId(), "OK", id, null, null));
      } catch (Exception e) {
        out.add(new BulkResultItem(i, null, "ERROR", null, "PROCESSING_ERROR", e.getMessage()));
      }
      var m = jobs.get(jobId);
      jobs.put(jobId, new JobMeta(m.jobId(), JobState.RUNNING, m.received(), m.processed()+1,
                                  (int)out.stream().filter(r->"OK".equals(r.status())).count(),
                                  (int)out.stream().filter(r->!"OK".equals(r.status())).count(), null));
    });

    var finalMeta = jobs.get(jobId);
    jobs.put(jobId, new JobMeta(finalMeta.jobId(), JobState.SUCCEEDED, finalMeta.received(),
            finalMeta.processed(), finalMeta.succeeded(), finalMeta.failed(), "/bulk/jobs/"+jobId+"/result"));
  }

  Mono<JobMeta> status(String jobId) { return Mono.just(jobs.get(jobId)); }

  Flux<String> resultNdjson(String jobId) {
    Queue<BulkResultItem> out = jobResults.get(jobId);
    return Flux.fromIterable(out).map(item -> {
      try {
        return new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(item);
      } catch (Exception e) { return "{\"status\":\"ERROR\",\"error\":\"SER\"}"; }
    });
  }
}
```

> Notes:
>
> -   For production, replace in-memory stores with a **database** or **queue** (e.g., SQS/Kafka) and persist results to object storage; use **outbox** for reliable progress events.
>
> -   Add **per-tenant quotas**, **gzip**, **schema validation**, and **OpenAPI** docs; support **CSV** in addition to NDJSON.
>

---

## Known Uses

-   **Salesforce Bulk API**, **Google Ads/BigQuery** bulk endpoints, **GitHub GraphQL/REST pagination + bulk**, **Stripe** (idempotent POSTs; not bulk per se but relevant), internal enterprise bulk import/export services for ERPs/CRMs.


---

## Related Patterns

-   **API Composition** (read aggregation) — different goal; Bulk focuses on **high-volume writes/reads**.

-   **API Orchestration / Process Manager** — can drive multi-step bulk jobs.

-   **Idempotency Key**, **Retry/Backoff**, **Circuit Breaker**, **Bulkhead** — resilience companions.

-   **Event-Carried State Transfer / CDC** — alternative for continuous data sync.

-   **Pagination / Streaming** — complements bulk export.
