# Idempotent Receiver — Resilience & Fault Tolerance Pattern

## Pattern Name and Classification

**Name:** Idempotent Receiver  
**Classification:** Resilience / Fault Tolerance / Message Processing (Enterprise Integration Pattern)

---

## Intent

Ensure that **processing the same message/request multiple times produces the same effect as processing it once**. This protects state from duplicates caused by retries, redeliveries, failovers, or client/network errors while preserving at-least-once delivery guarantees.

---

## Also Known As

-   Idempotent Consumer
    
-   Duplicate Message Suppression
    
-   Exactly-Once Effect (pragmatic)
    
-   De-duplication on Receipt
    

---

## Motivation (Forces)

-   **At-least-once delivery** is common in reliable systems (brokers retry, clients resubmit).
    
-   **Retries** are necessary for transient failures but create duplicates.
    
-   **Side effects** (payments, inventory decrement, email sending) must not happen twice.
    
-   **Throughput** and **latency** matter—duplicate detection must be cheap and scalable.
    
-   **Ordering** may be weak; we need correctness without strict sequence guarantees.
    
-   **Simplicity** beats distributed transactions; we want strong effects with modest machinery.
    

---

## Applicability

Use this pattern when:

-   The transport or client may deliver **duplicate** messages/requests (SQS, Kafka, HTTP with retries).
    
-   Operations are **non-commutative** (charge once, ship once, increment exactly once).
    
-   You cannot rely on **global transactions** across systems.
    
-   You control the **receiver** but not all **senders**.
    
-   You must meet **financial** or **inventory** integrity requirements.
    

Avoid when:

-   The upstream already guarantees uniqueness with **strong de-duplication** and you trust it end-to-end.
    
-   The operation is **naturally idempotent** (pure reads) and requires no stateful defense.
    

---

## Structure

-   **Idempotency Key** (message id, request id, natural business key, or hash of payload).
    
-   **Dedup Store** (persistent log/cache of processed keys with outcome/status and TTL).
    
-   **Guarded Handler** (business logic executed at most once per key).
    
-   **Effect Log** (optional) records the canonical result to return for replays.
    
-   **Policy** (TTL/window, eviction, conflict resolution, late arrival handling).
    

---

## Participants

-   **Sender/Client:** May retry the same request or publish duplicates.
    
-   **Receiver/Service:** Enforces idempotency at the boundary.
    
-   **Key Extractor:** Derives/validates the idempotency key from headers or payload.
    
-   **Dedup Store:** DB/Redis/Cache table keyed by idempotency key + status/version.
    
-   **Business Handler:** Performs side effects once, under a transactional guard.
    
-   **Result Cache:** Stores canonical response for subsequent duplicates.
    

---

## Collaboration

1.  **Receiver** extracts the **idempotency key**.
    
2.  Checks **Dedup Store**:
    
    -   If **present & completed**, short-circuit with the **canonical result** (no side effects).
        
    -   If **present & in-progress**, return 409/425/202 or wait (configurable).
        
    -   If **absent**, **reserve** the key (insert row with unique constraint).
        
3.  Execute **Business Handler** inside a transaction.
    
4.  Persist **Effect Log** (result and version), mark key **completed**.
    
5.  On duplicate arrivals, return the logged result.
    

---

## Consequences

**Benefits**

-   Prevents double-spends/ships/emails under retries or redelivery.
    
-   Works with **at-least-once** infrastructure; no XA required.
    
-   Can return **deterministic responses** to repeated requests.
    
-   Clear operational visibility into duplicates.
    

**Liabilities**

-   Requires **stable keys**; poor key choice → false positives/negatives.
    
-   **Dedup Store** adds write path latency and capacity costs.
    
-   **TTL trade-offs:** Too short → late duplicates slip through; too long → storage growth.
    
-   Must handle **in-progress** records to avoid thundering herds or stuck keys.
    
-   Schema evolution/versioning of the business operation complicates result replay.
    

---

## Implementation

### Key Decisions

-   **Key selection:**
    
    -   Prefer **sender-generated** unique IDs (e.g., `requestId`, payment `idempotency-key` header).
        
    -   If missing, derive from **natural key** (e.g., `orderId#lineId#version`) or **hash(payload)**.
        
-   **Atomic reservation:** Insert into a table with **unique constraint** on key before side effects.
    
-   **Isolation:** Wrap reservation + effect in a **transaction** to avoid race conditions.
    
-   **Result recording:** Store canonical response (status, body hash, effect version) for quick replay.
    
-   **Expiry:** Apply TTL or archival to keep the store bounded (based on business re-delivery window).
    
-   **Concurrency policy:** Block, return 202/409, or **idempotent merge** for concurrent duplicates.
    
-   **Error policy:** If the handler fails, clear reservation or mark **FAILED** with retry guidance.
    

### Data Model (relational example)

```sql
create table idempotency_keys (
  id                bigint generated always as identity primary key,
  idem_key          varchar(100) not null,
  operation         varchar(50)  not null,
  status            varchar(20)  not null,       -- PENDING|SUCCEEDED|FAILED
  result_code       integer,
  result_body_hash  char(64),
  created_at        timestamp not null default now(),
  updated_at        timestamp not null default now(),
  expires_at        timestamp,
  unique (operation, idem_key)
);
create index on idempotency_keys (expires_at);
```

### Anti-Patterns

-   Using **liveness probes** or caches as dedup source of truth.
    
-   Performing side effects **before** reserving the key.
    
-   Deriving keys from **non-stable** fields (timestamps truncated to seconds, random order).
    
-   Ignoring **schema/version** in keys when payload meaning changes.
    

---

## Sample Code (Java)

### A) HTTP Receiver with Idempotency-Key (Spring Boot)

```java
// build.gradle (snip)
// implementation 'org.springframework.boot:spring-boot-starter-web'
// implementation 'org.springframework.boot:spring-boot-starter-data-jdbc'
// implementation 'org.springframework.boot:spring-boot-starter-json'
// runtimeOnly 'org.postgresql:postgresql'
```

```java
package com.example.idem.http;

import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.DigestUtils;
import org.springframework.web.bind.annotation.*;

import java.nio.charset.StandardCharsets;
import java.time.OffsetDateTime;
import java.util.Map;

@RestController
@RequestMapping("/payments")
public class PaymentController {

  private final NamedParameterJdbcTemplate jdbc;
  private final PaymentService paymentService;

  public PaymentController(NamedParameterJdbcTemplate jdbc, PaymentService paymentService) {
    this.jdbc = jdbc;
    this.paymentService = paymentService;
  }

  @PostMapping
  @Transactional
  public ResponseEntity<?> createPayment(
      @RequestHeader(value = "Idempotency-Key", required = false) String idemKey,
      @RequestBody PaymentRequest body) {

    String operation = "createPayment";
    String stableKey = (idemKey != null && !idemKey.isBlank())
        ? idemKey.trim()
        : body.naturalKey(); // e.g., orderId#lineId#amount#currency

    // 1) Reserve idempotency key (unique constraint (operation, idem_key))
    try {
      jdbc.update("""
        insert into idempotency_keys (idem_key, operation, status, created_at, expires_at)
        values (:k, :op, 'PENDING', now(), now() + interval '7 days')
      """, new MapSqlParameterSource(Map.of("k", stableKey, "op", operation)));
    } catch (DuplicateKeyException dup) {
      // Duplicate arrival: read canonical result and short-circuit
      Map<String, Object> row = jdbc.queryForMap("""
        select status, result_code, result_body_hash from idempotency_keys
        where idem_key = :k and operation = :op
      """, Map.of("k", stableKey, "op", operation));
      String status = (String) row.get("status");
      Integer code = (Integer) row.get("result_code");
      if ("SUCCEEDED".equals(status) && code != null) {
        return ResponseEntity.status(code).body(Map.of(
            "idempotent", true, "message", "duplicate accepted"));
      }
      // In-progress or failed: advise client to retry later
      return ResponseEntity.status(425).body(Map.of(
          "idempotent", true, "message", "request is being processed"));
    }

    // 2) Execute side effects (charge money, etc.)
    PaymentResult result = paymentService.charge(body);

    // 3) Record canonical result
    String bodyHash = sha256Hex(result.canonicalBody());
    jdbc.update("""
      update idempotency_keys
         set status='SUCCEEDED',
             result_code=:code,
             result_body_hash=:hash,
             updated_at=now()
       where idem_key=:k and operation=:op
    """, new MapSqlParameterSource(Map.of(
        "code", result.httpCode(), "hash", bodyHash, "k", stableKey, "op", operation)));

    return ResponseEntity.status(result.httpCode()).body(result.response());
  }

  private static String sha256Hex(String s) {
    // Simple MD5/sha util; replace with a proper SHA-256 if needed
    return DigestUtils.md5DigestAsHex(s.getBytes(StandardCharsets.UTF_8));
  }

  // --- DTOs & service sketch ---
  public record PaymentRequest(String orderId, String lineId, long amountCents, String currency) {
    String naturalKey() {
      return "%s#%s#%d#%s".formatted(orderId, lineId, amountCents, currency).toLowerCase();
    }
  }
  public record PaymentResult(int httpCode, String canonicalBody, Map<String,Object> response) {}
}
```

```java
package com.example.idem.http;

import org.springframework.stereotype.Service;

import java.util.Map;

@Service
public class PaymentService {
  public PaymentController.PaymentResult charge(PaymentController.PaymentRequest req) {
    // Perform real side effects (call PSP, persist ledger, emit events) once.
    // MUST be idempotent with respect to the chosen key (e.g., PSP supports idempotency keys).
    Map<String,Object> body = Map.of(
        "status", "captured",
        "orderId", req.orderId(),
        "lineId", req.lineId());
    return new PaymentController.PaymentResult(201, body.toString(), body);
  }
}
```

**Notes**

-   The **unique constraint** on `(operation, idem_key)` is the atomic guard.
    
-   A **PENDING** record handles races; later duplicates read the status and return 425/409.
    
-   Store a **result hash** for optional consistency checks if you also cache full bodies elsewhere.
    

### B) Message Receiver (Kafka) with Idempotent Consumer

```java
// build.gradle (snip)
// implementation 'org.springframework.kafka:spring-kafka'
// implementation 'org.springframework.boot:spring-boot-starter-data-jdbc'
```

```java
package com.example.idem.kafka;

import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.util.Map;

@Component
public class OrderEventConsumer {

  private final NamedParameterJdbcTemplate jdbc;
  private final OrderProjector projector;

  public OrderEventConsumer(NamedParameterJdbcTemplate jdbc, OrderProjector projector) {
    this.jdbc = jdbc;
    this.projector = projector;
  }

  @KafkaListener(topics = "orders", groupId = "order-projector")
  @Transactional
  public void onMessage(ConsumerRecord<String, String> rec) {
    String key = "orders@" + rec.topic() + "/" + rec.partition() + "/" + rec.key() + "#" + rec.value().hashCode();
    try {
      jdbc.update("""
        insert into idempotency_keys (idem_key, operation, status, created_at, expires_at)
        values (:k, 'projectOrder', 'PENDING', now(), now() + interval '3 days')
      """, Map.of("k", key));
    } catch (DuplicateKeyException ignored) {
      // already processed -> just return (ack)
      return;
    }

    projector.apply(rec.value()); // side effects: update read model, etc.

    jdbc.update("""
      update idempotency_keys set status='SUCCEEDED', updated_at=now()
      where idem_key=:k and operation='projectOrder'
    """, Map.of("k", key));
  }
}
```

**Notes**

-   The composed key includes **topic/partition** and a **payload hash** (or eventId if present).
    
-   For high-throughput, place the dedup store on a **fast key-value DB/Redis** with persistence.
    

---

## Known Uses

-   **Payment APIs** (e.g., idempotency keys to avoid double charges on HTTP retries).
    
-   **E-commerce** order creation (client retries won’t create duplicate orders).
    
-   **Event-driven projections** (prevent double application of events during rebalances/retries).
    
-   **Email/SMS** senders (dedupe to avoid multi-send).
    
-   **Warehouse/inventory** adjustments under network partitions.
    

---

## Related Patterns

-   **Transactional Outbox:** Complements idempotent receivers by ensuring each state change produces exactly one message.
    
-   **At-Least-Once Delivery:** Idempotent receiver is the standard consumer-side defense.
    
-   **Deduplication Queue/SQS FIFO:** Upstream dedup helps, but receiver idempotency remains prudent.
    
-   **Saga / Compensating Transaction:** If duplicates slipped through, compensations must be idempotent too.
    
-   **Optimistic Concurrency / Versioning:** Natural business keys + versions can serve as idempotency keys.
    
-   **Retry/Backoff/Timeout:** Retries create duplicates; pair them with idempotent receivers.
    

---

## Implementation Checklist

-   Choose a **stable idempotency key** and document it for clients.
    
-   Add a **unique constraint** and **atomic reservation** before side effects.
    
-   Wrap side effects in a **transaction**; mark completion with a durable write.
    
-   Store a **canonical result** (status/body) and **return it** for duplicates.
    
-   Define **TTL** and cleanup for the dedup store.
    
-   Handle **in-progress** collisions (425/409 or brief wait).
    
-   Monitor **duplicate rate** and **store saturation**; alert on anomalies.
    
-   Version keys if the business semantics change.

