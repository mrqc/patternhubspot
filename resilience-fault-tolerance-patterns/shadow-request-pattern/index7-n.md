# Shadow Request — Resilience & Fault Tolerance Pattern

## Pattern Name and Classification

**Name:** Shadow Request  
**Classification:** Resilience / Release Safety / Observability (Traffic Mirroring, Dark Launch)

---

## Intent

Send a **copy** of real production requests to a **shadow** (non-user-visible) service or version **in parallel**, **ignore its response**, and compare behavior/metrics to validate correctness, performance, and resilience **without risking user impact**.

---

## Also Known As

-   Traffic Mirroring
    
-   Dark Launch / Dark Read
    
-   Tee Request / Shadow Traffic
    
-   Silent Canary
    

---

## Motivation (Forces)

-   **Safe validation:** Proving a new implementation (algorithm, stack, DB, ML model) with realistic, long-tail production inputs before switching traffic.
    
-   **Non-determinism & data drift:** Synthetic tests miss production skew (PII formats, rare paths, malformed clients).
    
-   **Performance regressions:** Need to observe latency/CPU/memory under real load without delaying users.
    
-   **Resilience checks:** Verify timeouts, retries, fallbacks, and error mapping in the new path.
    
-   **Cost & blast radius:** Must cap resource usage and prevent the shadow from affecting user latency or downstream systems.
    

---

## Applicability

Use Shadow Request when:

-   Rolling out a **major change** (rewrite, dependency swap, new ML model, query planner).
    
-   You need **evidence** that behavior matches (functional diffs) and SLOs hold (latency, errors).
    
-   User response must **not** depend on the new path.
    
-   You can properly **isolate** side effects (read-only, sandbox data, or idempotent/neutralized writes).
    

Avoid when:

-   Side effects cannot be isolated and **duplicate effects** would be harmful (payments, emails) without strong idempotency/sandboxing.
    
-   PII/compliance prohibits mirroring outside strict controls and masking.
    
-   The extra shadow load would threaten **production capacity**.
    

---

## Structure

-   **Tee Point:** Where original request is duplicated (client SDK, API gateway, service mesh, edge proxy, or within the service).
    
-   **Primary Service:** Handles the user request; its response is the **only** one returned to the user.
    
-   **Shadow Target:** New version/environment receiving mirrored traffic; responses are **discarded**.
    
-   **Sanitizer/Mutator:** Removes PII, scrubs secrets, normalizes timestamps/IDs, neutralizes side effects.
    
-   **Sampler/Rate Limiter:** Controls what fraction/shape of traffic is mirrored.
    
-   **Comparator/Telemetry Correlator:** Compares results/side effects out-of-band (logs, events) using correlation IDs.
    
-   **Kill Switch:** Instant disable if budget is exceeded or impact detected.
    

---

## Participants

-   **Request Origin (Client/Upstream):** Issues the original call.
    
-   **Tee/Mirroring Component:** Clones request metadata/body; enforces policies (sampling, masking, timeout).
    
-   **Primary Handler:** Produces user-visible result.
    
-   **Shadow Handler:** Processes mirrored request in isolation; emits metrics/trace only.
    
-   **Observer/Analyzer:** Diff tool comparing logs/metrics/traces between primary and shadow.
    

---

## Collaboration

1.  **Tee Point** receives user request → forwards to **Primary** normally.
    
2.  In parallel, it creates a **shadow copy** (headers + body) → applies **sanitization** and **sampling** → sends to **Shadow Target** with a **shadow flag** header and **short deadline**.
    
3.  **Primary** returns its response immediately; **shadow response is ignored** (fire-and-forget).
    
4.  **Comparator** correlates by **Correlation-ID** to analyze latency distributions and functional diffs (e.g., body hash, status code mapping).
    
5.  **Kill Switch** or auto-tuning adjusts sampling if error/latency budgets are at risk.
    

---

## Consequences

**Benefits**

-   De-risks releases by validating under **real, messy** traffic.
    
-   Reveals latent **compatibility** and **performance** issues before cutover.
    
-   Enables **iterative tuning** (e.g., cache, query plans) with production shapes.
    

**Liabilities**

-   Extra **load** on upstream and shadow target; must be budgeted and rate-limited.
    
-   **Data protection** and **compliance** risks if PII is mirrored improperly.
    
-   **Duplicate side effects** if the shadow path writes; requires sandboxing or idempotency.
    
-   **Heisenberg effects:** Mirroring inside a hot path can add minimal overhead; keep it strictly async and bounded.
    

---

## Implementation

### Key Decisions

-   **Where to mirror:**
    
    -   **Infrastructure:** API gateway (e.g., NGINX/Envoy/Istio `mirror`), service mesh (Istio `trafficMirrorPercentage`).
        
    -   **In-process:** HTTP filter/interceptor (fast to ship, app-level control).
        
-   **Isolation level:**
    
    -   **Read-only** shadow preferred. If write-paths are unavoidable, use **sandbox datasets**, **idempotency keys**, or write to **null sinks**.
        
-   **Sampling & shaping:**
    
    -   Start at 0.1–1% of traffic; bias by **endpoint**, **tenant**, or **payload size**; add **rate caps**.
        
-   **Timeouts & budgets:**
    
    -   Shadow calls must have tight deadlines (e.g., 50–150 ms) and **never** block primary.
        
-   **Sanitization:**
    
    -   Remove **Authorization** tokens, cookies; redact PII fields; rotate identifiers.
        
-   **Correlation:**
    
    -   Propagate `X-Correlation-ID` / `traceparent`; tag spans as `shadow=true`.
        
-   **Observation & Diffing:**
    
    -   Compare **status codes**, **response shape hashes**, **side-effect summaries**; store only aggregates or masked diffs.
        

### Anti-Patterns

-   Waiting for the shadow response or **reading its body** on the hot path.
    
-   Mirroring **all traffic** without a budget or kill switch.
    
-   Sending **real credentials** or PII to the shadow.
    
-   Mirroring to a target that can **call back** or affect user state.
    
-   Ignoring **idempotency** when the shadow has any write path.
    

---

## Sample Code (Java, Spring Boot, WebFlux `WebClient` tee)

> In-process mirroring with sanitization, sampling, correlation, strict timeout, and fire-and-forget execution. The shadow response is dropped and **never** impacts the user path.

```java
// build.gradle (snip)
// implementation 'org.springframework.boot:spring-boot-starter-webflux'
// implementation 'org.springframework.boot:spring-boot-starter'
// implementation 'io.micrometer:micrometer-core'

package com.example.shadow;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.util.unit.DataSize;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.net.URI;
import java.time.Duration;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ThreadLocalRandom;

@Component
public class ShadowTee {

  private final WebClient shadowClient;
  private final double samplingRatio;
  private final int rateCapPerSec;
  private final Duration shadowTimeout;
  private final long bodySizeCapBytes;
  private volatile long tokens; // naive token bucket; prefer a proper RateLimiter in prod
  private volatile long lastRefillMs;

  public ShadowTee(
      @Value("${shadow.url}") String shadowBaseUrl,
      @Value("${shadow.sampling:0.01}") double samplingRatio,
      @Value("${shadow.rateCapPerSec:50}") int rateCapPerSec,
      @Value("${shadow.timeoutMillis:100}") long timeoutMillis,
      @Value("${shadow.bodyCap:64KB}") String bodyCap
  ) {
    this.shadowClient = WebClient.builder()
        .baseUrl(shadowBaseUrl)
        .build();
    this.samplingRatio = samplingRatio;
    this.rateCapPerSec = rateCapPerSec;
    this.shadowTimeout = Duration.ofMillis(timeoutMillis);
    this.bodySizeCapBytes = DataSize.parse(bodyCap).toBytes();
    this.tokens = rateCapPerSec;
    this.lastRefillMs = System.currentTimeMillis();
  }

  /** Fire-and-forget mirror. Never blocks the caller beyond minimal enqueue cost. */
  public void mirror(String method, String path, HttpHeaders originalHeaders, byte[] body, String correlationId) {
    if (!sampled() || !rateAllowed()) return;

    HttpHeaders sanitized = sanitize(originalHeaders, correlationId);
    byte[] cappedBody = capBody(body);

    shadowClient.method(org.springframework.http.HttpMethod.valueOf(method))
        .uri(URI.create(path))
        .headers(h -> h.addAll(sanitized))
        .contentType(MediaType.APPLICATION_JSON)
        .bodyValue(cappedBody)
        .retrieve()
        .toBodilessEntity()
        .timeout(shadowTimeout)
        .onErrorResume(ex -> Mono.empty())   // swallow errors
        .subscribe();                        // fire-and-forget
  }

  private boolean sampled() {
    return ThreadLocalRandom.current().nextDouble() < samplingRatio;
  }

  private boolean rateAllowed() {
    long now = System.currentTimeMillis();
    if (now - lastRefillMs >= 1000) {
      tokens = rateCapPerSec;
      lastRefillMs = now;
    }
    if (tokens > 0) { tokens--; return true; }
    return false;
  }

  private HttpHeaders sanitize(HttpHeaders in, String correlationId) {
    HttpHeaders out = new HttpHeaders();
    // keep correlation; drop auth
    out.set("X-Correlation-ID", correlationId != null ? correlationId : UUID.randomUUID().toString());
    out.set("X-Shadow", "true");
    // copy a safe subset of headers if needed (content-type, accept)
    out.setContentType(in.getContentType());
    out.setAccept(in.getAccept());
    return out;
  }

  private byte[] capBody(byte[] body) {
    if (body == null) return new byte[0];
    return body.length <= bodySizeCapBytes ? body : java.util.Arrays.copyOf(body, (int) bodySizeCapBytes);
  }
}
```

```java
// Example usage inside a controller or handler
package com.example.shadow;

import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/orders")
public class OrderController {

  private final ShadowTee tee;
  private final ShadowComparator comparator; // optional, see below

  public OrderController(ShadowTee tee, ShadowComparator comparator) {
    this.tee = tee;
    this.comparator = comparator;
  }

  @PostMapping
  public ResponseEntity<?> create(@RequestHeader HttpHeaders headers, @RequestBody byte[] body) {
    // 1) Process normally
    var result = doPrimaryCreate(body);

    // 2) Fire-and-forget shadow request (do not await)
    String corr = headers.getFirst("X-Correlation-ID");
    tee.mirror("POST", "/api/v1/orders", headers, body, corr);

    // 3) Optionally record a compact hash for later diffing
    comparator.recordPrimary(corr, result.status(), result.bodyHash());

    return ResponseEntity.status(result.status()).body(result.body());
  }

  private Result doPrimaryCreate(byte[] body) {
    // business logic, writes to real systems
    String responseBody = "{\"status\":\"ok\"}";
    return new Result(201, responseBody, Integer.toHexString(responseBody.hashCode()));
  }

  static class Result {
    final int status; final String body; final String bodyHash;
    Result(int s, String b, String h) { status=s; body=b; bodyHash=h; }
    int status(){ return status; } String body(){ return body; } String bodyHash(){ return bodyHash; }
  }
}
```

```java
// Optional: out-of-band comparator (stores minimal info for diffing)
package com.example.shadow;

import org.springframework.stereotype.Component;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

@Component
public class ShadowComparator {
  private final Map<String, PrimaryRecord> primary = new ConcurrentHashMap<>();
  public void recordPrimary(String corrId, int status, String hash) {
    if (corrId != null) primary.put(corrId, new PrimaryRecord(status, hash));
  }
  public void recordShadow(String corrId, int status, String hash) {
    var p = primary.get(corrId);
    if (p == null) return;
    if (p.status != status || !p.hash.equals(hash)) {
      // emit a metric/event: functional diff spotted
      System.out.printf("DIFF corr=%s primary=%d/%s shadow=%d/%s%n",
          corrId, p.status, p.hash, status, hash);
    }
  }
  record PrimaryRecord(int status, String hash) {}
}
```

> **Shadow service** should accept `X-Shadow: true`, avoid writes or use sandbox datasets, and call `ShadowComparator.recordShadow(...)` with masked/hashed results through telemetry rather than synchronously returning to the caller.

---

### Alternative: Infrastructure-level mirroring (Istio/Envoy)

-   Configure **`mirror`** to a shadow destination with `percentage: 1–5%`.
    
-   Add a **header route filter** to inject `X-Shadow: true` and strip `Authorization`.
    
-   Enforce **timeout** and **retry: disabled** on the mirror route.
    
-   Use **destination rules** so shadow cluster cannot call back or access production DBs.
    

---

## Known Uses

-   **Search & Ads** stacks shadow new ranking models against production queries before enabling.
    
-   **Payments** teams shadow to a **sandbox** PSP to validate SDK upgrades (with idempotency keys).
    
-   **Database migration** (e.g., MySQL → Postgres) with shadow reads/writes into a migration env and diffs.
    
-   **API gateway** providers (NGINX/Envoy/Istio) widely support traffic mirroring for dark launches.
    

---

## Related Patterns

-   **Canary Release / Blue-Green:** Gradually serve user traffic; shadowing gathers confidence beforehand.
    
-   **Idempotent Receiver:** Protects against accidental duplicate side effects in shadow paths.
    
-   **Rate Limiting / Bulkhead:** Constrain shadow load and isolate resources.
    
-   **Feature Flag / Dark Launch:** Enable code paths for evaluation without user visibility.
    
-   **A/B Testing (offline):** Shadow enables validation without user assignment.
    
-   **Replay Testing:** Complements shadowing by feeding archived traffic at controlled pace.
    

---

## Implementation Checklist

-   Choose **tee point** (infra vs in-process) and validate **non-blocking** behavior.
    
-   Set **sampling** and **rate caps**; include a **kill switch** and alerts.
    
-   **Sanitize** headers/body (no tokens/PII); tag with `X-Shadow: true` and a **Correlation-ID**.
    
-   Enforce **tight timeouts**, **no retries**, and **drop on error** semantics for shadow calls.
    
-   Ensure **isolation**: sandbox datasets or fully read-only shadow.
    
-   Build **diffing**: status codes, shape hashes, side-effect summaries; log only masked aggregates.
    
-   Monitor **overhead** (p95/p99 latency delta on primary) and **shadow error rates**.
    
-   Document exit criteria to move from **shadow → canary → full rollout**.

