# Idempotent Receiver — Enterprise Integration Pattern

## Pattern Name and Classification

**Name:** Idempotent Receiver  
**Classification:** Message Consumer / Reliability pattern in Enterprise Integration Patterns (EIP)

## Intent

Ensure that processing the same message more than once has the **same effect as processing it exactly once**. The receiver detects duplicates (by an idempotency key or fingerprint) and **processes each logical message at most once**.

## Also Known As

-   Duplicate Message Eliminator
    
-   De-duplication Consumer
    
-   Exactly-once *effect* (not delivery)
    

## Motivation (Forces)

-   **At-least-once delivery** is common in messaging systems (retries, redeliveries, network partitions).
    
-   **Handlers may not be naturally idempotent** (e.g., “charge credit card,” “create order”).
    
-   **Operational realities:** consumer restarts, batch replays, and out-of-order delivery.
    
-   **Audit & compliance:** must prove that an operation was applied once even under retries.
    

**Forces to balance**

-   Duplicates vs. throughput and latency.
    
-   Durable vs. in-memory de-duplication.
    
-   Global vs. partition-scoped identifiers.
    
-   TTL/retention vs. unbounded dedup store growth.
    

## Applicability

Use an Idempotent Receiver when:

-   Your transport offers **at-least-once** semantics (Kafka, SQS, JMS with redelivery).
    
-   You perform **non-idempotent side effects** (payments, shipments, state transitions).
    
-   You support **replays** (backfills, CDC reprocess) or **eventual consistency**.
    
-   You need **fault-tolerance** across restarts and deployments.
    

## Structure

-   **Producer** emits a message with a **unique idempotency key** (e.g., business key, UUID, hash of canonical content).
    
-   **Receiver** checks a **Dedup Store** (cache/DB/Redis) using the key:
    
    -   If unseen → reserve/record → process → mark completed (or atomic upsert).
        
    -   If seen → drop/short-circuit (optionally return cached result).
        

```sql
[Producer] --(Message{key=K, payload})--> [Receiver]
   [Receiver] -- check K in Dedup Store --> [Seen?]
        | no                                     | yes
        v                                        v
   reserve K -> process -> commit           skip / return cached
```

## Participants

-   **Idempotency Key**: a stable identifier (requestId, paymentId, natural key, or payload hash).
    
-   **Receiver/Handler**: business logic guarded by the idempotency gate.
    
-   **Dedup Store**: persistent or partition-scoped store (DB table, Redis, Kafka compacted topic).
    
-   **Serializer/Canonicalizer**: optional; produces canonical payload before hashing.
    
-   **Result Cache (optional)**: returns prior response for duplicates.
    

## Collaboration

1.  Producer sets `Idempotency-Key` (header) or embeds it in payload.
    
2.  Receiver extracts the key and queries the Dedup Store.
    
3.  If new, the receiver **atomically** records the key (often with a processing state) and executes the side effect.
    
4.  On success/failure, the receiver updates the record (e.g., `COMPLETED` vs `FAILED/EXPIRED`).
    
5.  If duplicate arrives, the receiver short-circuits (and may return previous result).
    

## Consequences

**Benefits**

-   Eliminates duplicate side effects under retries/redelivery.
    
-   Enables safe reprocessing and backfills.
    
-   Clear audit trail of applied operations.
    

**Liabilities**

-   Requires **global uniqueness** criteria and **atomicity** with side effects.
    
-   Dedup store adds latency and a new failure mode; must handle **race conditions**.
    
-   **Key design** matters: too coarse drops legitimate requests; too fine fails to deduplicate.
    
-   Retention/TTL required to avoid unbounded growth.
    

## Implementation

-   **Choose the key:** Prefer a **business identifier** (e.g., `paymentId`, `orderId#version`). If none exists, use a **content fingerprint** (SHA-256 of canonical JSON).
    
-   **Store:**
    
    -   **DB table** with `unique` key + status (RESERVED/COMPLETED/FAILED) and optional result blob.
        
    -   **Redis** with `SETNX` + TTL for quick reservation; optionally persist completion separately.
        
    -   **Kafka compacted topic** keyed by id for streaming topologies.
        
-   **Atomicity:**
    
    -   Use **upsert** or **`INSERT ... ON CONFLICT DO NOTHING`** to reserve.
        
    -   For “write side effect to DB” cases, make the idempotency record part of the **same transaction**.
        
    -   For “external side effect” (e.g., payment provider), write **RESERVED → call provider → mark COMPLETED**; retries check the record first.
        
-   **Exactly-once effect:** Aim for **idempotent handler + dedup store**, not transport-level exactly-once.
    
-   **TTL & eviction:** Set retention beyond max redelivery window/backfill horizon.
    
-   **Observability:** metric for `dedup_hits`, `dedup_miss`, `processing_time`, and DLQ counts.
    
-   **Re-entrancy:** If processing crashes after side effect but before marking COMPLETED, ensure **retries are safe** (idempotent side effect or provider-side idempotency keys).
    
-   **Out-of-order:** For versioned updates, include a **monotonic sequence** or **event version** (drop older).
    

## Sample Code (Java)

### A) Spring Kafka Listener with Redis-backed Idempotency (atomic SETNX + TTL)

```java
// Gradle deps (reference): spring-kafka, spring-data-redis, jackson, lettuce, micrometer

@Component
public class PaymentConsumer {

    private final StringRedisTemplate redis;
    private final PaymentService paymentService;
    private static final Duration RESERVATION_TTL = Duration.ofHours(24);

    public PaymentConsumer(StringRedisTemplate redis, PaymentService paymentService) {
        this.redis = redis;
        this.paymentService = paymentService;
    }

    @KafkaListener(topics = "payments", groupId = "payments-handler")
    public void onMessage(ConsumerRecord<String, String> record) {
        PaymentCommand cmd = deserialize(record.value());
        String key = idempotencyKey(cmd); // e.g., cmd.getPaymentId()

        String reservationKey = "idem:payments:" + key;
        Boolean reserved = redis.opsForValue().setIfAbsent(reservationKey, "RESERVED", RESERVATION_TTL);

        if (Boolean.FALSE.equals(reserved)) {
            // duplicate → short-circuit
            return;
        }

        try {
            // side effect, designed to be idempotent with the same key
            PaymentResult res = paymentService.charge(cmd);

            // write completion marker (optionally store result)
            redis.opsForValue().set(reservationKey, "COMPLETED", RESERVATION_TTL);
        } catch (Exception e) {
            // leave RESERVED (so a later retry can attempt again) or set to FAILED with shorter TTL
            redis.opsForValue().set(reservationKey, "FAILED", Duration.ofMinutes(10));
            throw e; // let Kafka retry per your error policy / DLT
        }
    }

    private PaymentCommand deserialize(String json) { /* Jackson */ }
    private String idempotencyKey(PaymentCommand cmd) { return cmd.getPaymentId(); }
}
```

### B) JPA/Hibernate with a Dedup Table (transactional reservation)

```java
@Entity
@Table(name = "idempotency",
       uniqueConstraints = @UniqueConstraint(name = "uq_idempotency_key", columnNames = "id_key"))
public class IdempotencyRecord {
    @Id @GeneratedValue private Long id;

    @Column(name = "id_key", nullable = false, length = 128)
    private String key;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 16)
    private Status status; // RESERVED, COMPLETED, FAILED

    @Column(name = "created_at", nullable = false)
    private Instant createdAt = Instant.now();

    public enum Status { RESERVED, COMPLETED, FAILED }
    // getters/setters
}

public interface IdempotencyRepo extends JpaRepository<IdempotencyRecord, Long> {
    Optional<IdempotencyRecord> findByKey(String key);
}

@Service
public class OrderHandler {

    private final IdempotencyRepo repo;
    private final EntityManager em;

    public OrderHandler(IdempotencyRepo repo, EntityManager em) {
        this.repo = repo;
        this.em = em;
    }

    @Transactional
    public OrderConfirmation handle(PlaceOrderCommand cmd) {
        String key = "order:" + cmd.orderId();

        try {
            // Try to reserve (unique constraint enforces single reservation)
            IdempotencyRecord rec = new IdempotencyRecord();
            rec.setKey(key);
            rec.setStatus(IdempotencyRecord.Status.RESERVED);
            repo.saveAndFlush(rec);
        } catch (DataIntegrityViolationException dup) {
            // duplicate → skip or return cached response
            return existingConfirmation(cmd.orderId());
        }

        // Perform side effects within same TX where possible
        OrderConfirmation conf = createOrderInDb(cmd);

        // Mark completed (optional if existence + domain state is enough)
        repo.findByKey(key).ifPresent(r -> r.setStatus(IdempotencyRecord.Status.COMPLETED));

        return conf;
    }

    private OrderConfirmation createOrderInDb(PlaceOrderCommand cmd) {
        // insert order row with natural key order_id; unique constraint protects duplicates too
        // em.persist(...)
        return new OrderConfirmation(cmd.orderId(), "CREATED");
    }

    private OrderConfirmation existingConfirmation(String orderId) {
        // lookup existing order state and synthesize response
        return new OrderConfirmation(orderId, "CREATED");
    }
}
```

### C) Content Fingerprinting (canonical JSON → SHA-256)

```java
public final class Fingerprints {
    private static final ObjectMapper MAPPER = new ObjectMapper()
        .configure(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS, true);

    public static String canonicalSha256(Object payload) {
        try {
            String canonical = MAPPER.writeValueAsString(payload);
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] hash = md.digest(canonical.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder();
            for (byte b : hash) sb.append(String.format("%02x", b));
            return sb.toString();
        } catch (Exception e) {
            throw new IllegalStateException("fingerprint failed", e);
        }
    }
}
```

## Known Uses

-   **Payment APIs** (Stripe, Adyen): client-supplied idempotency keys to prevent double charges.
    
-   **Order creation** in e-commerce systems behind Kafka/SQS with redeliveries.
    
-   **Bank transfers** and ledger postings where exactly-once is realized as “idempotent effect.”
    
-   **CDC pipelines** to avoid re-applying the same change on replays.
    
-   **REST endpoints** offering `Idempotency-Key` headers to clients for retriable POSTs.
    

## Related Patterns

-   **Message Deduplication / Content-Based Router:** Upstream elimination vs. consumer-side elimination.
    
-   **Transactional Outbox:** Ensures message publication; pairs well with idempotent consumers downstream.
    
-   **Retry / Circuit Breaker / Dead Letter Channel:** Control failure handling and poison messages.
    
-   **Saga / Process Manager:** Coordinates multi-step processes; each step should be idempotent.
    
-   **Optimistic Lock / Versioned Entity:** Guards against conflicting updates; complements idempotency.

