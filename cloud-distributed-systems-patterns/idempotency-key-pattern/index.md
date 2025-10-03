# Idempotency Key

## Pattern Name and Classification

-   **Name:** Idempotency Key

-   **Category:** Cloud/Distributed Reliability Pattern (client–server, integration, messaging)

-   **Scope:** Service/API boundary and message-processing boundary


## Intent

Ensure that **retries** of the same logical operation (due to network errors, timeouts, or client retries) **do not produce duplicate side-effects**. The server detects duplicates using a client-supplied or server-derived **idempotency key**, returning the **same outcome** for all attempts of the same operation.

## Also Known As

-   Deduplication Token

-   Request Idempotency

-   De-dupe Key / De-duplication ID (messaging)


## Motivation (Forces)

-   **At-least-once retries** are the default in cloud networks; clients and load balancers repeat requests on ambiguous failures.

-   Many operations are **not naturally idempotent** (e.g., “charge card”, “create order”, “send email”).

-   We want **safety** (no duplicates) without giving up **availability** (allowing retries).

-   We must balance **storage cost + TTL** for keys against **deduplication window** guarantees.

-   We need **bounded consistency**: return the **original result** (including error vs success) for the same key even across nodes and restarts.

-   Keys must respect **multi-tenancy** and **scope** (per endpoint, per resource).

-   We want to **avoid global locks**; prefer conditional writes/unique constraints.


## Applicability

Use this pattern when:

-   An API endpoint or consumer performs **non-idempotent side-effects** (e.g., payment capture, provisioning).

-   You employ **automatic retries** (client libraries, gateways, message queues).

-   You need **exactly-once effect** semantics on top of **at-least-once delivery**.

-   You can store a **small dedup record** keyed by an idempotency key for a limited time.


## Structure

```lua
+---------+      POST /payments
| Client  |--- Idempotency-Key: <uuid> ----------------------+
+---------+                                                 |
                                                          v v
            +--------------------+   (unique on key, scope, tenant)
            |  Idempotency Store | <------------------------------+
            | (DB/Redis/Dynamo)  |                                 |
            +----------+---------+                                 |
                       |                                           |
                       v                                           |
                  +----+----------------+                          |
                  |  Business Operation |----> Side-effect (e.g., charge)
                  +---------------------+                          |
                       | result/error                              |
                       v                                           |
            +------------------------------+                       |
            | Persist result (status, body) |----------------------+
            +--------------------------------+
```

## Participants

-   **Client/Caller**: Generates/chooses the idempotency key; retries on failure.

-   **API Gateway/Server**: Extracts key, orchestrates dedup logic.

-   **Idempotency Store**: Durable store to detect duplicates and return cached result.

-   **Business Operation**: Non-idempotent effect executed at most once per key.


## Collaboration

1.  Client sends request with `Idempotency-Key` (or body-derived hash).

2.  Server attempts **conditional insert** of a record `{key, scope, status=IN_PROGRESS}`.

    -   If insert **succeeds** → first execution: run operation, persist **final status + response**, return it.

    -   If insert **conflicts** → duplicate:

        -   If **IN\_PROGRESS** → return 409/202 with retry-after *or* wait/subscribe.

        -   If **COMPLETED/FAILED** → **return stored result** verbatim.

3.  Record has **TTL** to bound storage and duplicate window.


## Consequences

**Benefits**

-   Prevents duplicate side-effects under retries and race conditions.

-   Enables idempotency across **stateless** horizontal scaling.

-   Returns **consistent response** for same logical request.


**Liabilities**

-   Requires **persistent storage** and **TTL management**.

-   Incorrect **scope** (e.g., same key across different endpoints) can cause false positives/negatives.

-   Must capture enough **response context** (status code, body, headers) to replay.

-   Handling **long-running operations** needs IN\_PROGRESS semantics and timeouts/heartbeat.


## Implementation (Guidelines)

-   **Key Source**

    -   Prefer **client-generated UUIDv4** per logical operation.

    -   Alternatively, **hash** stable request parts (e.g., `sha256(userId|amount|currency|merchantRef)`), but beware of legitimate repeats.

-   **Scope & Uniqueness**

    -   Unique on `(tenant_id, endpoint, idempotency_key)`; optionally include **request\_hash** for extra safety.

-   **Atomicity**

    -   Use **unique constraint/conditional write**:

        -   SQL: `INSERT ... ON CONFLICT DO NOTHING` / unique index.

        -   DynamoDB: `ConditionExpression attribute_not_exists(PK)`.

        -   Redis: `SET key value NX EX <ttl>` for lightweight claims (but still persist final result).

-   **States**

    -   `IN_PROGRESS` (with start timestamp), `SUCCEEDED` (status + serialized response), `FAILED` (error class + message).

    -   Guard against **stuck** IN\_PROGRESS with **expiry/lease**.

-   **Serialization**

    -   Store **HTTP status, headers subset, response body** to replay duplicates faithfully.

-   **TTL & Cleanup**

    -   TTL matches your **retry horizon** (e.g., 24–72h).

    -   Background job to purge expired records; or native TTL (Redis key expiry, DynamoDB TTL).

-   **Errors**

    -   If first attempt fails with 4xx/5xx, **cache that failure**; subsequent retries return the same failure unless the client changes the key.

-   **Security**

    -   Treat idempotency key as **opaque**; bind to tenant/auth identity.

    -   Enforce **rate limits** to avoid key-space abuse.

-   **Observability**

    -   Log key, scope, state transitions; emit metrics for duplicates and conflicts.


---

## Sample Code (Java, Spring Boot + JPA)

> Demonstrates: extracting `Idempotency-Key`, conditional insert via unique constraint, IN\_PROGRESS handling, storing and replaying the original response. Replace JPA with your datastore as needed.

**Entity**

```java
// package: com.example.idem;
import jakarta.persistence.*;
import java.time.Instant;

@Entity
@Table(name = "idempotency_record",
       uniqueConstraints = @UniqueConstraint(name = "uq_tenant_endpoint_key",
                    columnNames = {"tenantId","endpoint","idempotencyKey"}))
public class IdempotencyRecord {
  public enum Status { IN_PROGRESS, SUCCEEDED, FAILED }

  @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
  private Long id;

  @Column(nullable = false, length = 64)  private String tenantId;
  @Column(nullable = false, length = 128) private String endpoint;
  @Column(nullable = false, length = 100) private String idempotencyKey;

  @Enumerated(EnumType.STRING) @Column(nullable = false)
  private Status status;

  @Column(columnDefinition = "text") private String requestHash; // optional
  @Column(columnDefinition = "text") private String responseBody;
  @Column(nullable = false) private int httpStatus;
  @Column(nullable = false) private Instant createdAt = Instant.now();
  @Column(nullable = false) private Instant updatedAt = Instant.now();
  @Column(nullable = true)  private Instant expiresAt;

  @Version private long version;

  // getters/setters omitted for brevity
}
```

**Repository**

```java
import org.springframework.data.jpa.repository.*;
import java.util.Optional;

public interface IdempotencyRecordRepo extends JpaRepository<IdempotencyRecord, Long> {
  Optional<IdempotencyRecord> findByTenantIdAndEndpointAndIdempotencyKey(
      String tenantId, String endpoint, String idempotencyKey);
}
```

**Service Wrapper**

```java
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.function.Supplier;

@Service
public class IdempotencyService {

  private final IdempotencyRecordRepo repo;

  public IdempotencyService(IdempotencyRecordRepo repo) { this.repo = repo; }

  /**
   * Wrap a non-idempotent operation with idempotency handling.
   * @param tenantId caller/tenant
   * @param endpoint logical scope, e.g. "/payments"
   * @param key Idempotency-Key header
   * @param requestHash optional stable hash of request payload
   * @param op business operation producing ResponseEntity<String>
   */
  @Transactional
  public ResponseEntity<String> execute(
      String tenantId, String endpoint, String key, String requestHash,
      Supplier<ResponseEntity<String>> op) {

    // 1) Try to create IN_PROGRESS record (first claim).
    IdempotencyRecord rec = new IdempotencyRecord();
    rec.setTenantId(tenantId);
    rec.setEndpoint(endpoint);
    rec.setIdempotencyKey(key);
    rec.setStatus(IdempotencyRecord.Status.IN_PROGRESS);
    rec.setRequestHash(requestHash);
    rec.setExpiresAt(Instant.now().plus(3, ChronoUnit.DAYS));

    try {
      repo.saveAndFlush(rec); // unique constraint enforces first-writer-wins
    } catch (DataIntegrityViolationException conflict) {
      // Duplicate: someone already created a record for this key.
      IdempotencyRecord existing = repo
        .findByTenantIdAndEndpointAndIdempotencyKey(tenantId, endpoint, key)
        .orElseThrow(); // highly unlikely right after conflict

      switch (existing.getStatus()) {
        case IN_PROGRESS:
          // Option A: tell client to retry later (avoid double-run)
          return ResponseEntity.status(409).header("Retry-After", "3").body(
            "{\"error\":\"idempotency_in_progress\"}");
        case SUCCEEDED:
        case FAILED:
          return ResponseEntity.status(existing.getHttpStatus())
                               .body(existing.getResponseBody());
      }
    }

    // 2) First execution: run business op
    ResponseEntity<String> response;
    try {
      response = op.get(); // may have side-effects (charge, create order)
      // 3) Persist final response and status=SUCCEEDED
      rec.setStatus(IdempotencyRecord.Status.SUCCEEDED);
      rec.setHttpStatus(response.getStatusCode().value());
      rec.setResponseBody(response.getBody());
      rec.setUpdatedAt(Instant.now());
      repo.save(rec);
      return response;
    } catch (RuntimeException ex) {
      // Map exception to a stable error response and cache it
      var failure = ResponseEntity.status(502).body("{\"error\":\"upstream\"}");
      rec.setStatus(IdempotencyRecord.Status.FAILED);
      rec.setHttpStatus(502);
      rec.setResponseBody(failure.getBody());
      rec.setUpdatedAt(Instant.now());
      repo.save(rec);
      return failure;
    }
  }
}
```

**Controller Example**

```java
import org.springframework.http.ResponseEntity;
import org.springframework.util.DigestUtils;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/payments")
public class PaymentController {

  private final IdempotencyService idm;
  private final PaymentService payments; // your real business service

  public PaymentController(IdempotencyService idm, PaymentService payments) {
    this.idm = idm; this.payments = payments;
  }

  @PostMapping
  public ResponseEntity<String> createPayment(
      @RequestHeader(name = "Idempotency-Key", required = true) String idemKey,
      @RequestHeader(name = "X-Tenant", required = true) String tenantId,
      @RequestBody PaymentRequest req) {

    String endpoint = "/payments";
    String requestHash = DigestUtils.md5DigestAsHex(
        (req.customerId()+"|"+req.amount()+"|"+req.currency()+"|"+req.reference()).getBytes());

    return idm.execute(tenantId, endpoint, idemKey, requestHash, () -> {
      // Non-idempotent effect (example)
      PaymentResult r = payments.charge(req);
      String body = "{\"paymentId\":\""+r.id()+"\",\"status\":\""+r.status()+"\"}";
      return ResponseEntity.status(201).body(body);
    });
  }
}
```

**DDL (example)**

```sql
create table idempotency_record (
  id bigint primary key generated always as identity,
  tenant_id varchar(64) not null,
  endpoint varchar(128) not null,
  idempotency_key varchar(100) not null,
  status varchar(20) not null,
  request_hash text,
  response_body text,
  http_status int not null default 200,
  created_at timestamp not null,
  updated_at timestamp not null,
  expires_at timestamp null,
  version bigint not null,
  constraint uq_tenant_endpoint_key unique (tenant_id, endpoint, idempotency_key)
);
create index idx_idem_expires on idempotency_record(expires_at);
```

**Notes**

-   Swap JPA for **Redis + RDBMS** hybrid if you need faster IN\_PROGRESS detection: `SETNX idem:<tenant>:<endpoint>:<key> "lease" EX 30`. Persist final result in DB; renew lease while running.

-   For message queues (e.g., SQS FIFO), you can reuse the **message deduplication ID** as the idempotency key.


---

## Known Uses

-   **Stripe**: `Idempotency-Key` header to make POST requests idempotent.

-   **Square / Adyen / PayPal**: idempotency keys on payment APIs.

-   **AWS SQS FIFO**: `MessageDeduplicationId` provides de-duplication over a window.

-   **Google Cloud Tasks / Workflows**: task names used as idempotency keys.

-   **DynamoDB**: conditional writes (`attribute_not_exists`) to claim a key atomically.

-   **Cloudflare API, Shopify API, Twilio API**: idempotent POST endpoints via keys.


## Related Patterns

-   **Transactional Outbox**: pair DB commit with message publication; can also record idempotency results.

-   **Retry** (with jitter/backoff): pairs naturally; retries must reuse the **same key**.

-   **At-Least-Once Delivery**: the transport guarantee that motivates this pattern.

-   **Message De-duplication**: similar idea at the queue level.

-   **Saga / Process Manager**: long-running flows still benefit from idempotent step handlers.

-   **Circuit Breaker, Bulkhead, Timeout**: complementary resilience patterns; reduce retries but don’t make effects idempotent.

-   **Optimistic Concurrency (Compare-and-Set)**: used to claim keys atomically.


---

### Practical Checklist

-    Require `Idempotency-Key` on non-idempotent endpoints.

-    Unique constraint on `(tenant, endpoint, key)`; optional `request_hash`.

-    States: IN\_PROGRESS → (SUCCEEDED|FAILED); lease/timeout for stuck runs.

-    Persist **exact HTTP result** and replay for duplicates.

-    TTL purge job; set to your max retry horizon.

-    Telemetry for conflict hits and replay ratio.

-    Document client behavior: **reuse the same key for the same logical operation**; new key ⇒ new effect.
