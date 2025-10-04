# Timeout — Resilience & Fault Tolerance Pattern

## Pattern Name and Classification

**Name:** Timeout  
**Classification:** Resilience / Fault Tolerance / Latency Control (Client- and Server-Side)

---

## Intent

Bound the **maximum time** spent waiting for an operation to complete so that stalled or slow dependencies do not consume resources indefinitely and do not violate end-to-end latency SLOs. Timeouts enable **fast failure**, **back-pressure**, and **predictable behavior** under partial outages.

---

## Also Known As

-   Deadline (when propagated end-to-end)
    
-   Call Timeout / Request Timeout
    
-   Time Budget / Latency Budget
    

---

## Motivation (Forces)

-   **Hanging calls** (network stalls, GC pauses, lock contention) can tie up threads and connection slots, cascading into system-wide failures.
    
-   **Tail latency** dominates user experience; bounding waits keeps p95/p99 predictable.
    
-   **Retries & backoff** require a bounded attempt duration to fit an overall **time budget**.
    
-   **Resource control:** Pools and queues need calls to release capacities in bounded time.
    
-   **Fairness & isolation:** One slow dependency should not starve other work.
    

---

## Applicability

Use Timeouts when:

-   Calling remote services, data stores, queues, or any I/O where latency is variable.
    
-   Executing **potentially long-running** computations that can be aborted or abandoned.
    
-   You enforce **SLOs/SLAs** and must cap end-to-end latency.
    
-   You run **retries** or **fallbacks** that need a remaining budget.
    

Avoid or tailor when:

-   Operations are **atomic and non-cancelable** (ensure idempotency and safe abandon).
    
-   You have **internal batch jobs** where throughput > latency and cancellation is impractical (use checkpoints).
    

---

## Structure

-   **Per-Attempt Timeout:** Max time for one call/attempt.
    
-   **Overall Deadline:** Absolute timestamp or total budget across chained calls.
    
-   **Propagator:** Passes remaining budget (`X-Deadline`, `grpc-timeout`, `traceparent` baggage) downstream.
    
-   **Canceler:** Cancels the in-flight operation (interrupt, token, context).
    
-   **Classifier:** Decides whether a timeout is retryable.
    
-   **Observer:** Metrics for timeouts vs successes, and remaining budget distribution.
    

---

## Participants

-   **Caller/Client:** Sets and enforces timeouts/deadlines.
    
-   **Dependency:** Honors cancellation or at least fails fast when late.
    
-   **Scheduler/Timer:** Implements accurate clocks/timers.
    
-   **Policy Store:** Provides endpoint/tenant-specific timeout defaults.
    
-   **Metrics/Tracing:** Records attempts, durations, and cancellations.
    

---

## Collaboration

1.  Caller computes **deadline** from the user’s SLO (e.g., 500 ms total).
    
2.  For each sub-call, compute **per-attempt timeout** as min(remaining budget, per-endpoint cap).
    
3.  Pass remaining budget downstream via headers/context; start the call with a **cancel token**.
    
4.  On expiry, cancel/abort the call, free resources, optionally **retry with backoff** if budget remains.
    
5.  Emit metrics/logs with **timeout cause** and **remaining budget** when aborted.
    

---

## Consequences

**Benefits**

-   Prevents **thread starvation** and connection pool exhaustion.
    
-   Shields user experience by bounding tail latency; enables graceful **degradation**.
    
-   Creates a clear contract with dependencies; simplifies failure handling.
    

**Liabilities**

-   **Too aggressive** → false timeouts, unnecessary retries, lower throughput.
    
-   **Too lax** → still suffer hangs and SLO violations.
    
-   Not all libs are **cancellation-cooperative**; may leak work in background.
    
-   Requires consistent **budget propagation** across services.
    

---

## Implementation

### Key Decisions

-   **Choose budgets from SLOs:** e.g., page view 500 ms → API has 350 ms; DB 150 ms.
    
-   **Timeout granularity:** connect, read, write, handshake, and overall call.
    
-   **Cancellation semantics:** interrupts, reactive cancellation, or context tokens.
    
-   **Propagation:** standardized header or RPC metadata; subtract elapsed time at each hop.
    
-   **Classification:** Treat client/network timeouts as *retryable* (with idempotency), server timeouts often *non-retryable* if at capacity.
    
-   **Observability:** Histogram of durations, counts of timeouts by endpoint and cause.
    

### Anti-Patterns

-   A single global timeout everywhere regardless of endpoint semantics.
    
-   Retrying after **overall deadline** expired.
    
-   Ignoring **connect vs read** timeouts (connect can be shorter).
    
-   Blocking threads waiting for long timeouts on servlet stacks (use async/reactive).
    
-   Not releasing resources on timeout (connections, locks).
    

---

## Sample Code (Java)

### A) HTTP Client with Per-Attempt Timeout + Overall Deadline (OkHttp)

```java
// build.gradle
// implementation 'com.squareup.okhttp3:okhttp:4.12.0'

import okhttp3.*;
import java.io.IOException;
import java.time.Duration;
import java.time.Instant;

public class BudgetedHttpClient {
  private final OkHttpClient base;

  public BudgetedHttpClient() {
    this.base = new OkHttpClient.Builder()
        .connectTimeout(Duration.ofMillis(150))  // fast connect fail
        .writeTimeout(Duration.ofMillis(300))
        .readTimeout(Duration.ofMillis(300))     // per-attempt cap
        .build();
  }

  public Response getWithDeadline(HttpUrl url, Duration overallBudget) throws IOException {
    Instant deadline = Instant.now().plus(overallBudget);

    int attempt = 0;
    IOException last = null;
    while (true) {
      attempt++;
      long remainingMs = Duration.between(Instant.now(), deadline).toMillis();
      if (remainingMs <= 0) throw new IOException("overall deadline exceeded", last);

      // Clone client with per-attempt read timeout = min(remaining, 300ms)
      int perAttemptMs = (int) Math.min(remainingMs, 300);
      OkHttpClient attemptClient = base.newBuilder()
          .readTimeout(Duration.ofMillis(perAttemptMs))
          .build();

      Request req = new Request.Builder()
          .url(url)
          .header("X-Deadline-Ms", String.valueOf(remainingMs))
          .build();

      try (Response resp = attemptClient.newCall(req).execute()) {
        if (resp.isSuccessful() || !isRetryable(resp.code())) return resp;
        last = new IOException("retryable status " + resp.code());
      } catch (IOException ioe) {
        last = ioe;
        if (!isRetryable(ioe)) throw ioe;
      }

      // Exponential backoff with jitter, bounded by remaining budget
      long backoff = Math.min(200L * (1L << Math.min(4, attempt-1)), 1000L);
      long sleep = (long)(Math.random() * backoff);
      if (sleep >= Duration.between(Instant.now(), deadline).toMillis()) {
        throw new IOException("deadline would be exceeded on backoff", last);
      }
      try { Thread.sleep(sleep); } catch (InterruptedException ie) {
        Thread.currentThread().interrupt(); throw new IOException("interrupted", ie);
      }
    }
  }

  private static boolean isRetryable(int code) {
    return code == 429 || code == 503 || code == 502 || code == 504;
  }
  private static boolean isRetryable(IOException e) {
    // connection reset, timeout, etc. Simplified; tune per stack
    return true;
  }
}
```

---

### B) Spring WebClient (Reactive) with Cancellation and Propagated Deadline

```java
// build.gradle
// implementation 'org.springframework.boot:spring-boot-starter-webflux'

import org.springframework.http.HttpHeaders;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.time.Instant;

public class ReactiveBudgetClient {
  private final WebClient client = WebClient.builder().build();

  public Mono<String> getWithDeadline(String url, Duration overall) {
    Instant deadline = Instant.now().plus(overall);
    return client.get()
        .uri(url)
        .headers(h -> h.add("X-Deadline-EpochMs", String.valueOf(deadline.toEpochMilli())))
        .retrieve()
        .bodyToMono(String.class)
        .timeout(Duration.ofMillis(Math.min(300, overall.toMillis()))) // per-attempt
        .onErrorResume(throwable -> Mono.error(new RuntimeException("timeout or IO", throwable)));
  }
}
```

---

### C) gRPC with True Deadlines (Client & Server)

```java
// build.gradle
// implementation 'io.grpc:grpc-netty-shaded:1.66.0'
// implementation 'io.grpc:grpc-stub:1.66.0'
// implementation 'io.grpc:grpc-protobuf:1.66.0'

import io.grpc.*;

public class GrpcDeadlineExample {
  public void callWithDeadline(MyServiceGrpc.MyServiceBlockingStub stub, long overallMs) {
    var response = stub.withDeadlineAfter(overallMs, java.util.concurrent.TimeUnit.MILLISECONDS)
        .someRpc(MyRequest.newBuilder().build());
  }

  // Server: honor cancellation to free resources early
  static class MyService extends MyServiceGrpc.MyServiceImplBase {
    @Override
    public void someRpc(MyRequest req, io.grpc.stub.StreamObserver<MyResponse> obs) {
      Context ctx = Context.current();
      // Periodically check if deadline exceeded/cancelled
      if (ctx.isCancelled()) { obs.onError(Status.CANCELLED.asRuntimeException()); return; }
      // ... do work
      obs.onNext(MyResponse.newBuilder().build());
      obs.onCompleted();
    }
  }
}
```

---

### D) Spring Boot Configuration (Tomcat/HTTP and JDBC)

```yaml
# application.yml
server:
  tomcat:
    connection-timeout: 2s       # accept/connect timeout
    max-threads: 200
spring:
  datasource:
    hikari:
      connection-timeout: 500     # ms to wait for a pool connection
  webclient:
    connect-timeout: 150          # ms
# Per-endpoint timeouts are better applied in code or via Gateway filters
```

```java
// JDBC query with timeout and cancellation
var stmt = dataSource.getConnection().prepareStatement("select * from heavy where id=?");
stmt.setQueryTimeout(2); // seconds; driver-enforced
```

---

## Known Uses

-   **gRPC** pervasive **deadlines** propagate budgets across microservices.

-   **Cloud SDKs** (AWS/GCP/Azure) expose per-operation timeouts and automatic retries.

-   **Databases** offer statement or lock timeouts (e.g., PostgreSQL `statement_timeout`, MySQL `lock_wait_timeout`).

-   **API gateways** (Envoy/Istio/NGINX) provide per-route connect/read/idle timeouts and `504` on expiry.


---

## Related Patterns

-   **Retry with Exponential Backoff:** Retries must fit within the **remaining budget**.

-   **Circuit Breaker:** Avoids repeatedly timing out into a known-bad dependency.

-   **Bulkhead:** Prevents timeouts from exhausting shared threads/connections.

-   **Throttling / Load Shedding:** Reduces load to avoid server-side timeouts.

-   **Fallback / Graceful Degradation:** Provide alternative responses when timeouts occur.

-   **Idempotent Receiver:** Makes retries safe after client-side timeouts.


---

## Implementation Checklist

-   Derive **per-endpoint** timeouts from user SLOs; avoid “one size fits all”.

-   Use **overall deadlines** and **propagate** remaining budget.

-   Distinguish **connect**, **read**, **write**, **idle** timeouts.

-   Ensure **cancellation** frees resources (reactive/async preferred).

-   Classify timeout outcomes; **retry** only when safe and budget allows.

-   Instrument **timeouts vs successes**; alert on spikes by endpoint/tenant.

-   Validate under chaos (packet loss, latency injection, GC pauses).
