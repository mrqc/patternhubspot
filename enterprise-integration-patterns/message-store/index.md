# Message Store — Enterprise Integration Pattern

## Pattern Name and Classification

**Name:** Message Store  
**Classification:** Reliability / State Management pattern (EIP); persistent storage for messages and message-related state (headers, payloads, correlation, sequence).

## Intent

Persist messages and/or message metadata in a durable store to support **reliability, recovery, correlation, resequencing, auditing, replay, throttling**, and **long-running workflows** that outlive process memory.

## Also Known As

-   Message Repository
    
-   Durable Message Cache
    
-   Inbox/Outbox Store (context-specific)
    
-   Saga/Process Instance Store (when tied to orchestration)
    

## Motivation (Forces)

-   **At-least-once delivery** implies duplicates and redeliveries—state is needed to deduplicate and resume.
    
-   **Long-running flows** (Aggregator, Resequencer, Saga) keep partial state across minutes/hours/days.
    
-   **Operational robustness:** recover after crashes, roll deployments, or reboots without losing in-flight context.
    
-   **Audit/Compliance:** retain message history for traceability and forensics.
    
-   **Replay:** re-drive consumers (bug fix, backfill) from persisted messages.
    

**Forces to balance**

-   Storage cost vs. retention/audit needs.
    
-   Queryability (SQL) vs. write throughput (log/NoSQL).
    
-   Security (PII, encryption) vs. operability (search/trace).
    
-   Consistency with side effects (transaction boundaries, exactly-once *effects*).
    

## Applicability

Use a Message Store when:

-   Implementing **Aggregator**, **Resequencer**, **Claim Check**, **Idempotent Receiver**, **Saga/Process Manager**.
    
-   You need **Outbox/Inbox** patterns to bridge DB and messaging reliably.
    
-   You must **correlate** messages by keys, **buffer** until a condition is met, or **replay** messages.
    
-   Regulatory or engineering needs require **audit logs** of messages and decisions.
    

Avoid or narrow scope when:

-   Transient memory suffices (short-lived, loss-tolerant).
    
-   Broker already provides the history you need (e.g., Kafka with adequate retention and compaction).
    

## Structure

```lua
+--------------------+
Channel  --->  |  Message Endpoint  |  ---> Handler
               +----------+---------+
                          |
                          v
                    +-----------+           lookups by: messageId, correlationId,
                    | Message   |<--------  sequenceId, state=AGGREGATING, etc.
                    |   Store   |
                    +-----------+
                          ^
                          | periodic purge / TTL
                          +---- Admin/Retention
```

## Participants

-   **Message Endpoint/Handler:** Reads/writes message state.
    
-   **Message Store:** Durable repository of headers, payloads, correlation, sequence/position, status, timestamps, and optional result/exception.
    
-   **Retention/Compaction Job:** Purges or compacts historical data.
    
-   **Schema/Serializer:** JSON/Avro/Protobuf mapping; optional compression/encryption.
    
-   **Indices/Queries:** Support correlation, deduplication, resequencing, and audit queries.
    

## Collaboration

1.  Endpoint receives a message, derives keys (e.g., `messageId`, `correlationId`, `seqNo`).
    
2.  Endpoint **persists** an entry (or updates an existing one) capturing state and progress.
    
3.  Business logic executes; intermediate outcomes (e.g., partial aggregate) update the store.
    
4.  When a terminal condition is met, the endpoint emits results, marks records **COMPLETED**, and optionally **purges** or archives.
    
5.  On crash/restart, the service **resumes** by reading non-terminal records and continuing.
    

## Consequences

**Benefits**

-   Enables **recovery**, **replay**, **correlation**, **dedup**, **resequencing**, **auditing**.
    
-   Decouples long-running flow state from process memory.
    
-   Clear boundary for **observability** and governance.
    

**Liabilities**

-   Additional **latency** and **write amplification**.
    
-   Needs **retention policies**, otherwise growth is unbounded.
    
-   Introduces a new **SPOF** if not replicated and monitored.
    
-   Must handle **PII** securely; consider encryption/tokenization.
    
-   Requires careful **transaction design** with side effects (avoid “stored but not sent” gaps unless using Outbox).
    

## Implementation

-   **Storage options:**
    
    -   **Relational DB (JDBC/JPA):** flexible queries; good for correlation/aggregator.
        
    -   **Key-Value/Cache (Redis) + DB:** fast reservations (SETNX) + persistent final state.
        
    -   **Log/Stream (Kafka compacted topic):** latest-state store keyed by ID with stream processors.
        
-   **Schema design (relational):**
    
    -   `id` (surrogate), `message_id` (unique), `correlation_id`, `sequence_id`, `sequence_no`,  
        `headers_json`, `payload_bytes`/`payload_json`, `status` (RECEIVED|PROCESSING|COMPLETED|FAILED|EXPIRED),  
        `result_bytes`, `error`, `created_at`, `updated_at`, `ttl_expires_at`, index on correlation/sequence/status.
        
-   **Transactions:**
    
    -   Prefer **single-DB transaction** when message store and domain DB are the same (e.g., Outbox + Inbox).
        
    -   Otherwise ensure **idempotency** and use **two-step** state transitions (RESERVED → COMPLETED).
        
-   **Security:** encrypt sensitive payloads at rest; sign headers; restrict access; scrub PII on purge.
    
-   **Retention:** TTL per use case; archive to object storage for audits; compact derived tables.
    
-   **Observability:** counters for inserts/updates, resumed flows, purge counts, sizes; sample payloads safely.
    
-   **Versioning:** include `schema_version` header; transform on read or write.
    

---

## Sample Code (Java)

### A) JPA Entity and Repository for a Generic Message Store

```java
// Maven: spring-boot-starter-data-jpa, jackson-databind, hibernate-types-60 (optional for JSON)
import jakarta.persistence.*;
import java.time.Instant;

@Entity
@Table(name = "message_store",
       indexes = {
         @Index(name = "ix_msg_message_id", columnList = "messageId", unique = true),
         @Index(name = "ix_msg_corr", columnList = "correlationId"),
         @Index(name = "ix_msg_seq", columnList = "sequenceId,sequenceNo"),
         @Index(name = "ix_msg_status", columnList = "status")
       })
public class MessageRecord {

  @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
  private Long id;

  @Column(nullable = false, length = 100)
  private String messageId;          // globally unique

  @Column(length = 100)
  private String correlationId;      // aggregate/saga key

  @Column(length = 100)
  private String sequenceId;         // resequencer key (e.g., orderId)
  private Long sequenceNo;           // resequencer position

  @Column(length = 20, nullable = false)
  private String status;             // RECEIVED, PROCESSING, COMPLETED, FAILED, EXPIRED

  @Lob
  private String headersJson;

  @Lob
  private byte[] payloadBytes;       // compressed/encrypted if needed

  @Lob
  private byte[] resultBytes;

  @Column(length = 500)
  private String error;

  @Column(nullable = false)
  private Instant createdAt = Instant.now();

  @Column(nullable = false)
  private Instant updatedAt = Instant.now();

  private Instant ttlExpiresAt;

  // getters/setters omitted for brevity
}
```

```java
import org.springframework.data.jpa.repository.*;
import java.util.*;

public interface MessageStoreRepository extends JpaRepository<MessageRecord, Long> {
  Optional<MessageRecord> findByMessageId(String messageId);
  List<MessageRecord> findTop100ByCorrelationIdAndStatusOrderByCreatedAtAsc(String correlationId, String status);
  List<MessageRecord> findTop100BySequenceIdAndStatusOrderBySequenceNoAsc(String sequenceId, String status);
}
```

### B) Service Layer: Upsert, Complete, Resume (Aggregator/Resequencer Friendly)

```java
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.time.Instant;
import java.util.Map;
import java.util.zip.Deflater;
import java.util.zip.DeflaterOutputStream;
import java.io.ByteArrayOutputStream;

@Service
public class MessageStoreService {

  private final MessageStoreRepository repo;
  private final ObjectMapper mapper;

  public MessageStoreService(MessageStoreRepository repo, ObjectMapper mapper) {
    this.repo = repo; this.mapper = mapper;
  }

  @Transactional
  public void storeReceived(String messageId,
                            String correlationId,
                            String sequenceId,
                            Long sequenceNo,
                            Map<String, Object> headers,
                            Object payload,
                            long ttlSeconds) {
    MessageRecord rec = repo.findByMessageId(messageId).orElseGet(MessageRecord::new);
    rec.setMessageId(messageId);
    rec.setCorrelationId(correlationId);
    rec.setSequenceId(sequenceId);
    rec.setSequenceNo(sequenceNo);
    rec.setStatus("RECEIVED");
    rec.setHeadersJson(writeJson(headers));
    rec.setPayloadBytes(compress(writeBytes(payload)));
    rec.setTtlExpiresAt(Instant.now().plusSeconds(ttlSeconds));
    rec.setUpdatedAt(Instant.now());
    repo.save(rec);
  }

  @Transactional
  public void markProcessing(String messageId) {
    MessageRecord rec = repo.findByMessageId(messageId)
        .orElseThrow(() -> new IllegalStateException("not found: " + messageId));
    rec.setStatus("PROCESSING");
    rec.setUpdatedAt(Instant.now());
  }

  @Transactional
  public void markCompleted(String messageId, Object result) {
    MessageRecord rec = repo.findByMessageId(messageId)
        .orElseThrow(() -> new IllegalStateException("not found: " + messageId));
    rec.setStatus("COMPLETED");
    rec.setResultBytes(compress(writeBytes(result)));
    rec.setUpdatedAt(Instant.now());
  }

  @Transactional
  public void markFailed(String messageId, String error) {
    MessageRecord rec = repo.findByMessageId(messageId)
        .orElseThrow(() -> new IllegalStateException("not found: " + messageId));
    rec.setStatus("FAILED");
    rec.setError(error);
    rec.setUpdatedAt(Instant.now());
  }

  public ResumeBatch loadForCorrelation(String correlationId) {
    var list = repo.findTop100ByCorrelationIdAndStatusOrderByCreatedAtAsc(correlationId, "RECEIVED");
    return new ResumeBatch(list);
  }

  public ResumeBatch loadForResequencer(String sequenceId) {
    var list = repo.findTop100BySequenceIdAndStatusOrderBySequenceNoAsc(sequenceId, "RECEIVED");
    return new ResumeBatch(list);
  }

  private String writeJson(Object o) {
    try { return mapper.writeValueAsString(o); } catch (Exception e) { throw new RuntimeException(e); }
  }
  private byte[] writeBytes(Object o) {
    try { return mapper.writeValueAsBytes(o); } catch (Exception e) { throw new RuntimeException(e); }
  }
  private byte[] compress(byte[] data) {
    try (var baos = new ByteArrayOutputStream(); var dos = new DeflaterOutputStream(baos, new Deflater(Deflater.BEST_SPEED))) {
      dos.write(data); dos.finish(); return baos.toByteArray();
    } catch (Exception e) { return data; }
  }

  public record ResumeBatch(java.util.List<MessageRecord> records) {}
}
```

### C) Inbox/Outbox Use (Exactly-Once *Effects* Companion)

```java
// Outbox write within the same DB transaction as domain change
@Transactional
public void createOrderAndOutbox(Order order, Object eventPayload) {
  entityManager.persist(order);
  // outbox table not shown; you can reuse MessageRecord with status=RECEIVED and a topic header
  messageStoreService.storeReceived(
      /*messageId*/ java.util.UUID.randomUUID().toString(),
      /*correlationId*/ order.getId(),
      /*sequenceId*/ null, /*sequenceNo*/ null,
      Map.of("topic", "orders.created.v1", "schemaVersion", "v1"),
      eventPayload,
      /*ttlSeconds*/ 7 * 24 * 3600);
  // a publisher job later reads un-sent records and publishes to the broker, then marks COMPLETED
}
```

### D) Scheduled Retention/Purge

```java
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import java.time.Instant;

@Component
public class MessageStoreRetention {

  private final MessageStoreRepository repo;

  public MessageStoreRetention(MessageStoreRepository repo) {
    this.repo = repo;
  }

  @Scheduled(fixedDelay = 60_000)
  public void purgeExpired() {
    // Example JPQL (replace with a custom @Modifying query for efficiency)
    // delete from MessageRecord where ttlExpiresAt < now() and status in ('COMPLETED','FAILED','EXPIRED')
  }
}
```

---

## Known Uses

-   **Spring Integration**’s `MessageStore` SPI (`JdbcMessageStore`, `MongoDbMessageStore`) to back **Aggregator**, **Resequencer**, **Claim Check**.
    
-   **Transactional Outbox/Inbox** implementations persisting messages in the service DB and publishing asynchronously.
    
-   **Kafka Streams state stores** and compacted topics acting as message/state stores for latest-value and replay.
    
-   **Saga orchestrators** (Camunda, Temporal, Axon) storing message-driven workflow state and events.
    
-   **Audit trails** in finance/healthcare where every inbound/outbound message must be retained.
    

## Related Patterns

-   **Aggregator / Resequencer / Claim Check:** Depend on a message store for intermediate state.
    
-   **Idempotent Receiver:** Uses a store to track processed message IDs.
    
-   **Transactional Outbox / Inbox:** Specific uses of a message store for reliable publish/consume.
    
-   **Dead Letter Channel:** Stores failed messages and diagnostic metadata.
    
-   **Message History / Message Tracker:** Audit and trace built atop the store.
    
-   **Saga / Process Manager:** Long-running workflow state persisted via a message store.

