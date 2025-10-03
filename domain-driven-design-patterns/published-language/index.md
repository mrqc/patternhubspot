# Published Language (Domain-Driven Design)

## Pattern Name and Classification

**Name:** Published Language (PL)  
**Classification:** DDD strategic integration pattern (contract for inter-context communication; typically paired with **Open Host Service** or **AsyncAPI/Message contracts**)

---

## Intent

Define and **publish a stable, versioned language**—schemas, message types, and error models—that all parties use to integrate with a bounded context. A Published Language prevents ambiguity and model leakage, enabling independent evolution with compatibility guarantees.

---

## Also Known As

-   Canonical Integration Language

-   Public Contract / Public Schema

-   Provider Contract (when owned by the Supplier)


---

## Motivation (Forces)

-   **Shared understanding.** Without an explicit contract, teams “guess” the meaning of fields; brittle, bespoke mappings proliferate.

-   **Decoupling through stability.** Internals change frequently; consumers need **stable** contracts and **predictable versioning**.

-   **Multiple consumers.** Point-to-point interfaces collapse under their own weight; one clear language scales better.

-   **Automation.** Contracts enable codegen, validation, consumer-driven contract tests, and documentation.


Tensions to balance:

-   **Expressiveness vs simplicity.** Rich models vs straightforward contracts.

-   **Backward compatibility** vs **domain evolution** (versioning, upcasting).

-   **One language for all** vs tailored variants (don’t overfit to a single consumer).

-   **Synchronous vs asynchronous** modes (HTTP vs messaging) using the same semantics.


---

## Applicability

Use a Published Language when:

-   Your bounded context exposes an **Open Host Service** to multiple consumers.

-   You publish **events** to many subscribers (Kafka, SQS, etc.).

-   You must guarantee **compatibility** across versions and time.

-   External partners rely on your definitions for automation or regulation.


Avoid or limit when:

-   There is only one consumer and you intentionally accept a **Conformist** relationship.

-   Communication stays entirely in-process within the same bounded context (no public contract needed).


---

## Structure

-   **Schemas & Types:** Versioned DTOs/messages (e.g., JSON Schema, OpenAPI, Avro/Protobuf, Java DTOs).

-   **Error Model:** Stable, machine-readable errors (e.g., `application/problem+json`).

-   **Versioning Policy:** Semantic and path/namespace conventions (`/api/v1`, `com.example.orders.api.v1`).

-   **Docs & Examples:** Human-readable docs and example payloads; sample code & test fixtures.

-   **Compatibility Tests:** Contract & CDC tests as part of CI.

-   **Serialization Rules:** Canonical encodings, naming, timestamps, and number formats.


---

## Participants

-   **Provider (Host/Owner):** Authors and publishes the PL, govern changes.

-   **Consumers:** Generate clients, validate against schemas, pin versions.

-   **Schema Artifacts:** OpenAPI/AsyncAPI/Avro/Protobuf files, Java DTOs, example catalog.

-   **Gateways/Registries:** API gateway, schema registry, documentation portal.

-   **Test Harness:** Contract verifiers (CDC), schema validators, golden samples.


---

## Collaboration

1.  Provider models the domain and **distills** a published, consumer-friendly schema.

2.  Contract artifacts are **published** (registry/repo), with changelog and deprecation policy.

3.  Consumers integrate **only through** the PL (codegen or hand-written).

4.  Provider evolves internals freely; evolves the PL via **additive changes**, and **new majors** for breaking changes.

5.  CI runs **contract tests** to prevent regressions.


---

## Consequences

**Benefits**

-   Reduces integration ambiguity and **tight coupling**.

-   Enables **automation** (validation, codegen, docs).

-   Scales to many consumers with **predictable evolution**.

-   Protects the domain from **model leakage**.


**Liabilities**

-   Requires **governance** and discipline (changelogs, deprecations).

-   Overly general “canonical models” can become **bloated**.

-   Version proliferation if not managed.

-   Migration costs for breaking changes.


---

## Implementation

**Guidelines**

-   **Namespace by version** (e.g., `com.acme.orders.api.v1`). Keep types additive within a major.

-   **Describe semantics**: required/optional, units, formats, enums, invariants.

-   **Stabilize the error language** (`problem+json`, error codes).

-   **Idempotency for unsafe operations** (header or token field) and **correlation IDs** for tracing.

-   **Date/time**: ISO-8601 in UTC; money with currency code; avoid floats for money.

-   **Events**: Include `eventType`, `version`, `occurredAt`, `aggregateId`, `sequence`.

-   **Schema evolution**: additive fields with defaults; use upcasters for old payloads.

-   **Contract publishing**: versioned artifacts + examples + change logs.

-   **Tests**: golden payloads, JSON Schema/Avro validation, CDC verifiers in CI.


---

## Sample Code (Java – DTOs, events, validation, versioning)

Below is a minimal, production-shaped **Published Language** for an Orders context.  
It shows **HTTP DTOs**, a **stable error model**, and an **event type** for async consumers, all namespaced under `api.v1`.

```java
// ======================================
// Published Language: HTTP DTOs (api.v1)
// ======================================
package com.acme.orders.api.v1;

import jakarta.validation.constraints.*;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;

// Command DTO (request to host service)
public record PlaceOrderRequest(
        @NotBlank String requestId,          // idempotency key supplied by client
        @NotBlank String customerId,
        @NotBlank String currency,           // ISO-4217
        @NotEmpty List<Line> lines
) {
    public record Line(
            @NotBlank String sku,
            @Positive int quantity,
            @DecimalMin(value = "0.00", inclusive = false) BigDecimal unitPrice
    ) {}
}

// Response DTO
public record PlaceOrderResponse(String orderId, String status) {}

// Query DTO (read model shape)
public record OrderView(
        String orderId,
        String customerId,
        String status,                       // PL enum: "PLACED" | "PAID" | "CANCELLED"
        String currency,
        BigDecimal totalAmount,
        Instant createdAt,
        Instant updatedAt
) {}
```

```java
// ======================================
// Published Language: Error Model
// ======================================
package com.acme.problem;

import java.time.Instant;
import java.util.Map;

/**
 * Stable error language aligned with RFC 7807 (problem+json).
 * Providers MUST return these fields; do not leak stack traces or internals.
 */
public record Problem(
        String type,      // URL to error doc, e.g., https://errors.acme.com/domain.validation_failed
        String title,     // short, human title
        int status,       // HTTP status
        String detail,    // human detail
        String code,      // stable machine-readable error code
        String traceId,   // correlation id (from header)
        Instant timestamp,
        Map<String, Object> context // optional extra machine-readable fields
) {
    public static Problem of(String type, String title, int status, String code, String detail, String traceId) {
        return new Problem(type, title, status, detail, code, traceId, Instant.now(), Map.of());
    }
}
```

```java
// ======================================
// Published Language: Domain Event (async)
// ======================================
package com.acme.orders.api.v1.events;

import java.math.BigDecimal;
import java.time.Instant;

/**
 * Versioned event contract published to a broker (Kafka/SNS/etc.).
 * Additive changes ONLY within v1 (new optional fields with sensible defaults).
 */
public record OrderPlacedV1(
        String eventType,        // "orders.order_placed"
        int version,             // 1
        String aggregateId,      // orderId
        long sequence,           // per-order sequence
        Instant occurredAt,      // UTC
        // Payload (minimal, stable)
        String customerId,
        BigDecimal totalAmount,
        String currency
) {
    public static OrderPlacedV1 of(String orderId, long seq, Instant t, String customerId, BigDecimal total, String currency) {
        return new OrderPlacedV1("orders.order_placed", 1, orderId, seq, t, customerId, total, currency);
    }
}
```

```java
// ======================================
// Serialization Helpers (Jackson)
// ======================================
package com.acme.support.serialization;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jdk8.Jdk8Module;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;

public final class Json {
    private static final ObjectMapper MAPPER = new ObjectMapper()
            .registerModule(new Jdk8Module())
            .registerModule(new JavaTimeModule())
            .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

    private Json() { }
    public static ObjectMapper mapper() { return MAPPER; }
}
```

```java
// ======================================
// Example: Controller using the PL
// (OHS facade; returns Problem on errors)
// ======================================
package com.acme.orders.api.v1.http;

import com.acme.orders.api.v1.*;
import com.acme.problem.Problem;
import org.springframework.http.*;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.net.URI;

@RestController
@RequestMapping(path = "/api/v1/orders", produces = MediaType.APPLICATION_JSON_VALUE)
public class OrdersController {

    private final OrdersAppService app;

    public OrdersController(OrdersAppService app) { this.app = app; }

    @PostMapping(consumes = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<?> place(@RequestHeader(name = "Idempotency-Key") String key,
                                   @Validated @RequestBody PlaceOrderRequest req,
                                   @RequestHeader(name = "X-Trace-Id", required = false) String traceId) {
        try {
            var orderId = app.place(req, key);
            return ResponseEntity.created(URI.create("/api/v1/orders/" + orderId))
                                 .body(new PlaceOrderResponse(orderId, "PLACED"));
        } catch (IllegalArgumentException e) {
            var p = Problem.of("https://errors.acme.com/domain.validation_failed",
                               "Bad Request", 400, "domain.validation_failed", e.getMessage(), traceId);
            return ResponseEntity.status(400)
                    .contentType(MediaType.APPLICATION_PROBLEM_JSON)
                    .body(p);
        } catch (IllegalStateException e) {
            var p = Problem.of("https://errors.acme.com/domain.conflict",
                               "Conflict", 409, "domain.conflict", e.getMessage(), traceId);
            return ResponseEntity.status(409)
                    .contentType(MediaType.APPLICATION_PROBLEM_JSON)
                    .body(p);
        }
    }

    @GetMapping("/{orderId}")
    public OrderView get(@PathVariable String orderId) {
        return app.view(orderId);
    }
}
```

```java
// ======================================
// Example: App Service maps PL <-> Domain
// ======================================
package com.acme.orders.api.v1.http;

import com.acme.orders.api.v1.*;
import com.acme.orders.domain.*;

import java.util.stream.Collectors;

public class OrdersAppService {
    private final OrderFactory factory;
    private final OrderRepository repo;
    private final OrderReadModel reads;

    public OrdersAppService(OrderFactory factory, OrderRepository repo, OrderReadModel reads) {
        this.factory = factory; this.repo = repo; this.reads = reads;
    }

    // @Transactional
    public String place(PlaceOrderRequest req, String idempotencyKey) {
        var lines = req.lines().stream()
                .map(l -> new OrderFactory.Line(new Sku(l.sku()),
                                                l.quantity(),
                                                new Money(l.unitPrice(), req.currency())))
                .collect(Collectors.toList());
        var order = factory.createAndPlace(new CustomerId(req.customerId()), lines, idempotencyKey);
        repo.save(order);
        return order.id();
    }

    public OrderView view(String orderId) {
        var v = reads.find(orderId);
        return new OrderView(v.orderId(), v.customerId(), v.status(), v.currency(), v.totalAmount(), v.createdAt(), v.updatedAt());
    }
}
```

```java
// ======================================
// Messaging Publisher: emits PL event
// ======================================
package com.acme.orders.messaging;

import com.acme.orders.api.v1.events.OrderPlacedV1;
import com.acme.support.serialization.Json;
import java.time.Clock;

public class OrderEventsPublisher {
    private final MessageBroker broker;  // your abstraction over Kafka/SNS/etc.
    private final Clock clock;

    public OrderEventsPublisher(MessageBroker broker, Clock clock) { this.broker = broker; this.clock = clock; }

    public void publishOrderPlaced(String orderId, long seq, String customerId, java.math.BigDecimal total, String currency) {
        var evt = OrderPlacedV1.of(orderId, seq, clock.instant(), customerId, total, currency);
        broker.publish("orders.order_placed.v1", Json.mapper().valueToTree(evt)); // topic naming includes version
    }
}
```

**Notes on the sample**

-   The **DTOs/events live under a versioned package** `com.acme.orders.api.v1`.

-   The **error model** is separate and stable.

-   Event topic includes version; payload carries `version=1`.

-   The controller returns **Problem JSON** for consistent errors across all endpoints.

-   Domain internals (entities, repositories) stay **behind** the PL.


---

## Known Uses

-   **Public SaaS APIs** (Stripe, Shopify-like domains) using OpenAPI + SDKs.

-   **Event platforms** (order/payment events) with Avro/Protobuf in a **schema registry**.

-   **Internal platforms** exposing a **company-wide language** for identity, payments, and products.

-   **Regulated integrations** where schemas and error codes are audited.


---

## Related Patterns

-   **Open Host Service:** The façade that exposes operations in the Published Language.

-   **Anti-Corruption Layer (ACL):** Use on the consumer side to map *their* model to the PL without polluting the domain.

-   **Context Map (Customer–Supplier/Conformist):** Describes governance and power dynamics around the PL.

-   **Domain Event / Event Sourcing:** Events use the PL; storage/propagation depend on these patterns.

-   **Transactional Outbox:** Ensures events in the PL are published after commit.

-   **Contract Tests / CDC:** Tooling to verify providers don’t break the PL.


---
