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
