# Idempotency Key — API Design Pattern

## Pattern Name and Classification

**Idempotency Key** — *Reliability / Consistency* pattern for **safe retries** of non-idempotent operations (e.g., POST payments) in APIs.

---

## Intent

Allow clients to **safely retry** a request without causing **duplicate side effects**, by sending a unique **Idempotency-Key** that the server uses to **deduplicate** and **replay the original result**.

---

## Also Known As

-   **Request Deduplication**

-   **Safe Retries for Non-Idempotent Operations**

-   **Exactly-once(ish) on the API Edge**


---

## Motivation (Forces)

-   Networks fail: clients **retry**; load balancers can **replay**; mobile apps **double-submit**.

-   Many operations are **not** naturally idempotent (e.g., charge a credit card, create an order).

-   We want **at-least-once delivery semantics** at the transport level but **exactly-once effects** at the application/API level.

-   Need observability and **deterministic responses** to the same key.


---

## Applicability

Use when:

-   A client may **retry** a request that creates side effects (payments, bookings, order submissions).

-   You must guarantee “**no duplicates**” for the **same intent** within a **time window**.

-   You can **persist** a small ledger per request to cache the canonical outcome.


Avoid/limit when:

-   The operation is **naturally idempotent** (PUT replace / DELETE by id).

-   Response depends on **rapidly changing context** and you cannot/shouldn’t replay.

-   Storage/latency constraints prevent maintaining a key store (rare).


---

## Structure

```pgsql
Client
  └─ POST /payments
     Header: Idempotency-Key: <uuid>
     Body: { intent }

API Server
  └─ Idempotency Store
       - reserve(key, scope)  -> RUNNING | CONFLICT
       - complete(key, result, status, headers) -> DONE
       - fetch(key) -> {status, headers, body} (for replays)

Scope = hash(method + route + normalized body + authenticated principal)
```

---

## Participants

-   **Client**: Generates **Idempotency-Key** and retries with the same key.

-   **Idempotency Middleware/Service**: Reserves the key (atomic), deduplicates, stores **final response** for replays, applies TTL.

-   **Domain Service**: Executes the actual business action exactly once per key/scope.

-   **Backing Store**: Redis/DB for **atomic reserve + TTL**.


---

## Collaboration

1.  Client sends POST with `Idempotency-Key`.

2.  Server **atomically reserves** the key for the computed **scope**.

3.  If first time → run domain logic → **persist outcome** → return response.

4.  If repeated → **replay stored response** (same status/body/headers).

5.  If in progress → return **409/425** (or block briefly) to avoid concurrent duplicates.


---

## Consequences

**Benefits**

-   Eliminates **duplicate side effects** on retries.

-   Makes **retries safe**; improves UX and resilience.

-   Provides **auditable ledger** of intents/outcomes.


**Liabilities**

-   Requires **persistent store** and **atomicity**.

-   Must define correct **scope** (key alone is not enough).

-   **TTL/eviction** policies and storage growth to manage.

-   Response **replay** implies you must store enough (status/body/headers).


---

## Implementation (Key Points)

-   **Key ingestion**: from `Idempotency-Key` header (UUID, ULID).

-   **Scope**: `hash(method + path + normalized body + userId/tenantId)`. Prevents reusing a key for a *different* intent.

-   **Atomic reserve**: `SETNX` in Redis (with TTL) or DB unique constraint.

-   **States**: `RUNNING` (reserved), `DONE` (immutable result).

-   **Replay**: Return the **exact** status/body/headers previously stored.

-   **TTL**: e.g., 24–72h; longer for payment intents.

-   **Observability**: log correlation id, key, scope, state transitions.

-   Combine with **retry/backoff**, **timeouts**, and downstream **idempotency** if needed.


---

## Sample Code (Java, Spring Boot)

> Minimal, production-style sketch showing a **payment creation** endpoint with **idempotency**.  
> For brevity this uses an **in-memory store**; swap with **Redis** in real systems.

**Gradle (snippets)**

```gradle
implementation "org.springframework.boot:spring-boot-starter-web"
implementation "com.fasterxml.jackson.core:jackson-databind"
testImplementation "org.springframework.boot:spring-boot-starter-test"
```

### 1) DTOs

```java
package demo.idem;

import java.time.Instant;
import java.util.Map;

public record CreatePaymentRequest(String customerId, int amountCents, String currency) {}
public record Payment(String id, String customerId, int amountCents, String currency, String status) {}

enum IdemState { RUNNING, DONE }

public record StoredResponse(
    String key, String scopeHash, IdemState state,
    int httpStatus, Map<String,String> headers, String body,
    String contentType, Instant expiresAt
) {}
```

### 2) Idempotency Store (In-Memory, replaceable with Redis)

```java
package demo.idem;

import org.springframework.stereotype.Repository;

import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

@Repository
class IdempotencyStore {

  private final Map<String, StoredResponse> db = new ConcurrentHashMap<>();

  // Atomically reserve a key for a scope; return existing if already present
  synchronized Optional<StoredResponse> reserve(String key, String scopeHash, Duration ttl) {
    var existing = db.get(key);
    if (existing != null) return Optional.of(existing);
    var rec = new StoredResponse(key, scopeHash, IdemState.RUNNING, 0, Map.of(), null, null,
                                 Instant.now().plus(ttl));
    db.put(key, rec);
    return Optional.of(rec);
  }

  Optional<StoredResponse> find(String key) { return Optional.ofNullable(db.get(key)); }

  synchronized void complete(String key, String scopeHash, int status,
                             Map<String,String> headers, String body, String contentType) {
    var old = db.get(key);
    if (old == null) return;
    // verify scope matches to prevent key reuse for different intent
    if (!old.scopeHash().equals(scopeHash)) {
      throw new IllegalStateException("Idempotency-Key scope mismatch");
    }
    var done = new StoredResponse(key, scopeHash, IdemState.DONE, status, headers, body, contentType, old.expiresAt());
    db.put(key, done);
  }

  // naive TTL cleanup (call periodically in prod)
  void purgeExpired() {
    var now = Instant.now();
    db.entrySet().removeIf(e -> e.getValue().expiresAt().isBefore(now));
  }
}
```

### 3) Idempotency Executor Helper

```java
package demo.idem;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.Base64;
import java.util.Map;
import java.util.function.Supplier;

@Component
class IdempotencyExecutor {

  private final IdempotencyStore store;
  private final ObjectMapper mapper = new ObjectMapper();
  private static final Duration TTL = Duration.ofHours(48);

  IdempotencyExecutor(IdempotencyStore store) { this.store = store; }

  String scopeHash(String method, String path, Object body, String principal) {
    try {
      var md = MessageDigest.getInstance("SHA-256");
      md.update(method.getBytes(StandardCharsets.UTF_8));
      md.update((path == null ? "" : path).getBytes(StandardCharsets.UTF_8));
      md.update((principal == null ? "" : principal).getBytes(StandardCharsets.UTF_8));
      if (body != null) {
        md.update(mapper.writeValueAsBytes(body)); // normalized JSON
      }
      return Base64.getUrlEncoder().withoutPadding().encodeToString(md.digest());
    } catch (Exception e) {
      throw new RuntimeException(e);
    }
  }

  /**
   * Execute the supplier exactly once per (key, scope).
   * If the key exists: return stored response.
   * If running: you can return 425 or 409; here we just wait up to smallTime for completion (simplified: no wait).
   */
  <T> ResponseEntity<T> execute(String idemKey, String scopeHash, Class<T> type,
                                Supplier<ResponseEntity<T>> supplier) {
    var rec = store.reserve(idemKey, scopeHash, TTL).orElseThrow();

    if (rec.state() == IdemState.DONE) {
      // Replay: deserialize stored body
      try {
        T body = rec.body() == null ? null : new ObjectMapper().readValue(rec.body(), type);
        var builder = ResponseEntity.status(rec.httpStatus());
        rec.headers().forEach(builder::header);
        return builder.body(body);
      } catch (Exception e) {
        throw new RuntimeException("Failed to deserialize stored response", e);
      }
    }

    // First execution path
    ResponseEntity<T> resp = supplier.get();

    try {
      String bodyJson = resp.getBody() == null ? null : mapper.writeValueAsString(resp.getBody());
      store.complete(idemKey, scopeHash, resp.getStatusCode().value(),
          Map.of("Idempotent-Replay", "false"), bodyJson, "application/json");
    } catch (Exception e) {
      // You may mark as FAILED and allow re-exec; for simplicity, leave RUNNING or set DONE with error code
      throw new RuntimeException(e);
    }
    return resp;
  }
}
```

### 4) Domain Service (fake payment processor)

```java
package demo.idem;

import org.springframework.stereotype.Service;

import java.util.UUID;

@Service
class PaymentService {
  Payment create(CreatePaymentRequest req) {
    // pretend to call PSP; ensure side effect happens only once per idempotency key
    return new Payment(UUID.randomUUID().toString(), req.customerId(), req.amountCents(), req.currency(), "CONFIRMED");
  }
}
```

### 5) Controller (Idempotent POST)

```java
package demo.idem;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/payments")
class PaymentsController {

  private final PaymentService payments;
  private final IdempotencyExecutor idem;

  PaymentsController(PaymentService payments, IdempotencyExecutor idem) {
    this.payments = payments; this.idem = idem;
  }

  @PostMapping
  public ResponseEntity<Payment> create(@RequestHeader(name="Idempotency-Key", required=true) String key,
                                        @RequestBody CreatePaymentRequest body,
                                        @RequestHeader(name="X-User", required=false) String user) {

    String principal = (user == null ? "anon" : user);
    String scope = idem.scopeHash("POST", "/payments", body, principal);

    return idem.execute(key, scope, Payment.class, () -> {
      Payment p = payments.create(body);
      return ResponseEntity.status(HttpStatus.CREATED)
          .header("Location", "/payments/" + p.id())
          .body(p);
    });
  }
}
```

**Behavior**

-   First POST with a new `Idempotency-Key`: executes and **stores** the 201 response.

-   Retries with the **same key and same body**: **replays** the original 201 + body + headers.

-   Same key but **different body/intent**: **scope mismatch** → error (prevents key reuse).


> **Production tips**
>
> -   Replace `IdempotencyStore` with **Redis** (`SET key val NX EX <ttl>`) and a hash for the final response.
>
> -   Return `409 Conflict` or `425 Too Early` if a second in-flight request uses the same key while **RUNNING**.
>
> -   For payments, consider **two-phase**: create *intent* (idempotent) → confirm.
>
> -   Propagate the key to downstreams (as metadata) or use **Transactional Outbox** to ensure exactly-once messaging.
>

---

## Known Uses

-   **Stripe** (Idempotency-Key for POSTs), **PayPal**, **Square**, many internal enterprise APIs for **payments, orders, booking**.


---

## Related Patterns

-   **Retry with Exponential Backoff & Jitter** — clients safely retry with the same key.

-   **Transactional Outbox / CDC** — ensure reliable emission of events after the idempotent write.

-   **Exactly-Once Processing (pragmatic)** — idempotency provides *effectively once* semantics at API level.

-   **Sagas / Compensations** — when workflows involve multiple services.

-   **Deduplication Token (Messaging)** — analogous idea for message consumers.
