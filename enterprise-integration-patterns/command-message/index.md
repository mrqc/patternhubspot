# Command Message (Enterprise Integration Pattern)

## Pattern Name and Classification

**Name:** Command Message  
**Classification:** Enterprise Integration Pattern (Messaging / Intent-Driven Request)

---

## Intent

Send a **message that instructs a specific receiver to perform an action** (create, update, delete, process). A Command Message conveys **intent** and optional parameters, may expect a **reply** (synchronous or asynchronous), and should be processed **exactly once** from the business perspective (idempotent handler).

---

## Also Known As

-   Command (over messaging)
    
-   Remote Command Invocation
    
-   Asynchronous Request
    

---

## Motivation (Forces)

-   Need to **decouple** caller and callee across process/network boundaries.
    
-   Want to **avoid tight coupling** of RPC (latency sensitivity, backpressure) while still **telling** another service to do something.
    
-   Must support **retries**, **at-least-once delivery**, and **idempotency** to survive failures.
    
-   Often need a **correlation** between request and eventual reply (success/failure, resource id).
    
-   Desire to preserve **domain intent** (e.g., `ReserveInventory`) rather than leaking low-level CRUD.
    

Tensions to balance:

-   **Fire-and-forget** vs **request/reply** (latency, complexity).
    
-   **Strong validation** vs **evolvable schemas**.
    
-   **Exactly-once semantics** are costly—prefer **idempotent** receivers with at-least-once delivery.
    

---

## Applicability

Use Command Message when:

-   A component must **instruct** another to perform a domain operation.
    
-   You need **resilience** and **loose coupling** compared to synchronous RPC.
    
-   Work may be **long-running** or **queued** (throttled).
    

Avoid or limit when:

-   The interaction is naturally **event notification** (“something happened”) → use **Event Message** instead.
    
-   The caller needs **immediate result** and strict **request-time consistency** → consider RPC with timeouts/circuit breaker.
    
-   The target isn’t authoritative for the action (violates bounded context ownership).
    

---

## Structure

-   **Command Envelope (headers + body):**
    
    -   `messageId` (UUID), `commandType`, `schemaVersion`
        
    -   `correlationId`, `causationId` (for tracing)
        
    -   `replyTo` (optional), `ttl`/`expiresAt`
        
    -   `partitionKey` (routing), `tenantId` (multi-tenancy)
        
-   **Command Payload:** Intent + parameters (domain DTO).
    
-   **Command Channel/Queue/Topic:** Transport (Kafka, SQS, RabbitMQ, AMQP).
    
-   **Reply Channel (optional):** For request/reply, success/failure envelope.
    
-   **Dead Letter Queue (DLQ):** For poison messages after max retries.
    
-   **Idempotency Store:** To deduplicate on the consumer side.
    

---

## Participants

-   **Command Producer (Client):** Creates and sends command; may wait for reply.
    
-   **Message Broker / Channel:** Delivers with at-least-once semantics.
    
-   **Command Handler (Service):** Validates, performs action, ensures idempotency, emits reply/events.
    
-   **Idempotency / Dedup Store:** Tracks processed `messageId`.
    
-   **Reply Consumer (optional):** Correlates and unblocks the original caller.
    
-   **Dead Letter Processor (Ops):** Inspects and remediates failures.
    

---

## Collaboration

1.  Producer creates **Command Message** with unique `messageId`, sets `correlationId`, optional `replyTo`.
    
2.  Broker delivers to **Command Handler** (may retry on failure).
    
3.  Handler checks **idempotency** (`messageId`), validates payload, executes domain logic (owning aggregate).
    
4.  Handler acknowledges success; optionally emits:
    
    -   **Reply Message** to `replyTo` with outcome and any result data, correlated via `correlationId`.
        
    -   **Domain Events** for downstream projections/integrations.
        
5.  On repeated failures, message goes to **DLQ** for manual or automated remediation.
    

---

## Consequences

**Benefits**

-   **Decoupled** invocation with backpressure via queues.
    
-   **Resilient** to intermittent failures (retries, DLQ).
    
-   Preserves **domain intent** in the API layer.
    
-   Enables **throttling** and **work distribution**.
    

**Liabilities**

-   **Eventual consistency**; caller may need a **saga**/compensation.
    
-   Managing **idempotency** and **duplicates** adds complexity.
    
-   **Ordering** only guaranteed within a partition key, not globally.
    
-   Debugging requires **correlation IDs** and good observability.
    

---

## Implementation

**Guidelines**

-   **Model commands** in ubiquitous language (`ReserveInventory`, `AuthorizePayment`).
    
-   Make consumers **idempotent**: store `(messageId, status, result)` and short-circuit duplicates.
    
-   Validate **ownership**: the target bounded context must be authoritative.
    
-   Include **versioning** (`commandType`, `schemaVersion`), avoid breaking changes; use additive fields.
    
-   Use **timeouts** & **circuit breakers** on the producer side if awaiting reply; otherwise fire-and-forget.
    
-   Prefer **reply messages** only when strictly needed; otherwise query read models to observe effects.
    
-   **Security:** sign/authorize commands, carry `tenantId` and scopes/claims.
    
-   **Observability:** log transitions with `correlationId`, emit metrics (accepted, completed, failed, retries).
    

**Delivery patterns**

-   **Fire-and-forget:** Producer publishes and returns. Consumer does the work and emits domain events.
    
-   **Request/Reply over messaging:** Producer waits (with timeout) on `replyTo`.
    
-   **Saga orchestration:** Commands drive steps; replies/events advance the saga.
    

---

## Sample Code (Java, framework-agnostic)

A minimal sketch with:

-   A **typed command** (`ReserveInventory`),
    
-   An **envelope** with headers,
    
-   A **producer** abstraction,
    
-   A **consumer/handler** with **idempotency**.
    

```java
import java.time.Instant;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

// ---------- Envelope & Command DTO ----------

public final class CommandEnvelope<T> {
    public final String messageId;
    public final String commandType;
    public final int schemaVersion;
    public final String correlationId;
    public final String causationId;
    public final String replyTo;        // optional
    public final Instant expiresAt;     // optional
    public final String partitionKey;   // e.g., aggregate id
    public final Map<String, String> headers;
    public final T payload;

    private CommandEnvelope(String messageId, String commandType, int schemaVersion,
                            String correlationId, String causationId, String replyTo,
                            Instant expiresAt, String partitionKey, Map<String, String> headers, T payload) {
        this.messageId = messageId;
        this.commandType = commandType;
        this.schemaVersion = schemaVersion;
        this.correlationId = correlationId;
        this.causationId = causationId;
        this.replyTo = replyTo;
        this.expiresAt = expiresAt;
        this.partitionKey = partitionKey;
        this.headers = headers == null ? Map.of() : Map.copyOf(headers);
        this.payload = Objects.requireNonNull(payload);
    }

    public static <T> CommandEnvelope<T> of(String commandType, int schemaVersion, String partitionKey, T payload) {
        return new CommandEnvelope<>(
                UUID.randomUUID().toString(),
                commandType,
                schemaVersion,
                UUID.randomUUID().toString(), // correlation id (new conversation)
                null, null, null,
                partitionKey,
                Map.of(),
                payload
        );
    }

    public CommandEnvelope<T> withReplyTo(String replyTo) {
        return new CommandEnvelope<>(messageId, commandType, schemaVersion, correlationId, causationId,
                replyTo, expiresAt, partitionKey, headers, payload);
    }
}

// Domain command DTO (Published Language)
public record ReserveInventory(
        String orderId,
        String sku,
        int quantity
) { }
```

```java
// ---------- Producer & Broker Abstractions ----------

public interface CommandBus {
    <T> void send(CommandEnvelope<T> cmd);
}

public interface ReplyBus {
    void send(String replyTo, ReplyMessage reply);
}

public record ReplyMessage(
        String correlationId,
        boolean success,
        String message,
        Map<String, Object> data
) {}

// Example producer usage:
public final class OrderServiceClient {
    private final CommandBus bus;

    public OrderServiceClient(CommandBus bus) { this.bus = bus; }

    public void reserve(String orderId, String sku, int qty) {
        var cmd = CommandEnvelope.of("inventory.reserve", 1, sku, new ReserveInventory(orderId, sku, qty));
        bus.send(cmd);
    }
}
```

```java
// ---------- Idempotent Handler ----------

public interface IdempotencyStore {
    /** @return true if messageId has been seen (processed or in-progress) */
    boolean seen(String messageId);
    /** mark processed with optional result snapshot */
    void recordProcessed(String messageId, boolean success, String summary);
}

public interface InventoryDomainService {
    void reserve(String orderId, String sku, int quantity); // throws on conflict
}

public final class ReserveInventoryHandler {

    private final IdempotencyStore idempotency;
    private final InventoryDomainService domain;
    private final ReplyBus replies; // optional

    public ReserveInventoryHandler(IdempotencyStore idempotency, InventoryDomainService domain, ReplyBus replies) {
        this.idempotency = idempotency; this.domain = domain; this.replies = replies;
    }

    // Framework (Kafka/SQS/Rabbit) invokes this upon message reception
    public void onMessage(CommandEnvelope<ReserveInventory> msg) {
        // TTL
        if (msg.expiresAt != null && Instant.now().isAfter(msg.expiresAt)) {
            // discard or DLQ, depending on policy
            idempotency.recordProcessed(msg.messageId, false, "expired");
            maybeReply(msg, false, "expired", Map.of());
            return;
        }

        // Idempotency (drop duplicates)
        if (idempotency.seen(msg.messageId)) {
            // Optionally re-send previous reply (if cached)
            return;
        }

        try {
            var p = msg.payload;
            // domain authority check: inventory owns this decision
            domain.reserve(p.orderId(), p.sku(), p.quantity());

            idempotency.recordProcessed(msg.messageId, true, "reserved");
            maybeReply(msg, true, "reserved", Map.of("sku", p.sku(), "qty", p.quantity()));
            // Optionally emit a Domain Event: InventoryReserved(orderId, sku, qty)

        } catch (IllegalStateException | IllegalArgumentException ex) {
            // business failure → reply/record and ack (not retriable)
            idempotency.recordProcessed(msg.messageId, false, ex.getMessage());
            maybeReply(msg, false, ex.getMessage(), Map.of());
            // no rethrow → prevent endless retries
        } catch (Exception transientFailure) {
            // retriable failure → let broker retry (do not recordProcessed as success)
            throw transientFailure; // framework visibility (will retry / move to DLQ)
        }
    }

    private void maybeReply(CommandEnvelope<?> msg, boolean ok, String text, Map<String,Object> data) {
        if (msg.replyTo != null && !msg.replyTo.isBlank()) {
            replies.send(msg.replyTo, new ReplyMessage(msg.correlationId, ok, text, data));
        }
    }
}
```

```java
// ---------- In-memory Idempotency Store (demo) ----------

import java.util.concurrent.ConcurrentHashMap;

public final class InMemoryIdempotencyStore implements IdempotencyStore {
    private final ConcurrentHashMap<String, String> processed = new ConcurrentHashMap<>();
    @Override public boolean seen(String messageId) { return processed.containsKey(messageId); }
    @Override public void recordProcessed(String messageId, boolean success, String summary) {
        processed.putIfAbsent(messageId, (success ? "OK: " : "ERR: ") + summary);
    }
}
```

> Wire these abstractions to your transport (Kafka producer/consumer, SQS client, RabbitMQ). The handler code stays **domain-centric** and transport-agnostic.

---

## Known Uses

-   **Order → Inventory:** `ReserveInventory`, `ReleaseInventory`.
    
-   **Payments:** `AuthorizePayment`, `CapturePayment`, `RefundPayment`.
    
-   **Fulfillment:** `CreateShipment`, `PrintLabel`.
    
-   **Identity:** `ProvisionUser`, `AssignRole`.
    
-   **Data pipelines:** `RebuildProjection`, `ReindexSearch` as offline commands with throttling.
    

---

## Related Patterns

-   **Event Message:** Announces something that happened (no imperative). Often emitted after a successful command.
    
-   **Request-Reply:** A messaging style frequently used with Command Messages when a result is needed.
    
-   **Saga / Process Manager:** Coordinates multiple commands across services with compensations.
    
-   **Idempotent Receiver:** Essential consumer design for at-least-once delivery.
    
-   **Message Correlation / Correlation Identifier:** Ties reply to command.
    
-   **Dead Letter Channel:** Handles poison messages after max retries.
    
-   **Transactional Outbox:** If commands are persisted before publishing, use outbox to avoid dual writes.
    
-   **Circuit Breaker / Bulkhead:** For synchronous command invocation (RPC) rather than messaging.
    

---

