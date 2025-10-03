# Open Host Service (Domain-Driven Design)

## Pattern Name and Classification

**Name:** Open Host Service (OHS)  
**Classification:** DDD strategic integration pattern (interface to a bounded context, typically paired with *Published Language*)

---

## Intent

Provide a **stable, openly published interface** to a bounded context that exposes a *cohesive set of domain operations* and **accepts external clients** without creating tight, point-to-point couplings. The OHS is expressed in a **Published Language** (API schema/contracts) and acts as the **official entry point** for other contexts/organizations.

---

## Also Known As

-   Public Service Interface

-   Host Service / Hosted API

-   Context API (with Published Language)

-   External Facade


---

## Motivation (Forces)

-   **Many consumers, one provider.** Without a formal host service, every integration becomes a bespoke connector that leaks internal models and multiplies maintenance.

-   **Stable contracts vs evolving internals.** The domain must change freely; external consumers need **compatibility & semantic stability**.

-   **Boundary clarity.** Keep the provider’s invariants and ubiquitous language authoritative; **do not** let consumer models bleed in.

-   **Interoperability.** A clear, versioned **Published Language** (OpenAPI/JSON Schema, Avro/Protobuf) prevents ambiguity.

-   **Security, SLAs, observability.** A first-class endpoint allows authentication, rate limiting, idempotency, metrics, and deprecation policies.


Tensions:

-   **How much to expose?** Minimal surface area vs usefulness.

-   **Versioning cadence** vs contract stability.

-   **Compatibility guarantees** (backward/forward) vs domain evolution.

-   **Sync vs async** operations (commands vs events, callbacks, webhooks).


---

## Applicability

Use an Open Host Service when:

-   Multiple external systems (internal teams, partners) must invoke your bounded context.

-   You need a **single authoritative integration point** with explicit semantics.

-   You must **stabilize** integration despite frequent internal refactoring.

-   You want **contract-first** governance (schemas, tests, deprecation rules).


Avoid or limit when:

-   Only a single consumer exists and a **Conformist** relationship is acceptable.

-   Communication is **outbound** from your context to others → consider **Anti-Corruption Layer (ACL)** on your side instead.

-   The problem is best solved by **events only** (fire-and-forget) rather than exposed commands/queries.


---

## Structure

-   **Host Context:** The bounded context providing capabilities.

-   **OHS (Facade/API):** The **only** externally consumable interface; technology-specific (HTTP/gRPC/messaging) but **domain-driven**.

-   **Published Language:** Schemas, message types, error model, versioning policy, examples, and documentation (OpenAPI/AsyncAPI, Protobuf, Avro).

-   **Policy & Governance:** AuthN/Z, rate limits, idempotency, SLAs, deprecation.

-   **Consumers:** Other contexts or third parties that integrate **only via** the OHS.


---

## Participants

-   **Provider (Host) Team:** Owns the OHS, its contract, and evolution policy.

-   **Consumers:** Integrate against the published contracts; submit change requests through governance.

-   **Contract & Schema Artifacts:** OpenAPI/AsyncAPI/Protobuf, example catalogs, conformance tests.

-   **Gateway/Adapter:** API gateway, mTLS, OAuth2, throttling, observability.

-   **Domain Layer:** Entities, Value Objects, Domain Services behind the façade.


---

## Collaboration

1.  Provider designs or refines the **Published Language** for relevant use cases.

2.  Consumers integrate **against the contract** (codegen, SDK, or manual).

3.  Calls hit the **OHS façade**, which validates, authorizes, and translates DTOs to domain types.

4.  Domain layer executes use case; results and errors are returned strictly **in the Published Language**.

5.  Changes follow **versioning & deprecation** policy (e.g., additive v1.x, breaking → v2).


---

## Consequences

**Benefits**

-   **Decoupling & scalability:** Many consumers integrate without bespoke adapters.

-   **Stability & clarity:** A single, versioned contract and error model.

-   **Governance:** Auth, throttling, audit, compatibility testing.

-   **Domain protection:** Internal model stays private; external shape is curated.


**Liabilities**

-   **Up-front design & maintenance** of contracts and governance.

-   **Risk of over-exposure** (too many endpoints) or under-exposure (not useful).

-   **Version proliferation** if not disciplined.

-   **Contract drift** when shortcuts bypass the OHS.


---

## Implementation

**Guidelines**

-   **Contract-first.** Start from OpenAPI/AsyncAPI/Protobuf; treat them as source artifacts.

-   **Published Language discipline.** Terms map to the **host’s ubiquitous language**, not any consumer’s.

-   **Versioning.** Semantic versioning; additive changes within minor/patch; breaking changes → new major (`/v2`).

-   **Idempotency.** Require `Idempotency-Key` for unsafe operations; store request hashes & results.

-   **Error model.** Machine-readable (`problem+json`), stable error codes; no stack traces.

-   **Security.** OAuth2 client-credentials or mTLS; scopes map to domain capabilities.

-   **Observation.** Correlation IDs, structured logs, metrics per operation & consumer.

-   **Limits.** Pagination, filtering, rate limits, payload caps; document SLAs.

-   **Sync/Async.** For long-running tasks return **202 + operation resource** or emit **domain events** (AsyncAPI).

-   **Backward compatibility tests.** Contract tests and consumer-driven contracts in CI.

-   **Keep the façade thin.** Map DTOs ⇄ domain types and invoke Application/Domain Services; no business logic in the controller.


---

## Sample Code (Java, Spring Boot-style OHS façade)

**Scenario:** *Orders* bounded context exposes an OHS to **place an order** and **query its status**.  
It uses a Published Language (DTOs) and supports **idempotency**, **versioning**, and a **problem+json** error model.

```java
// --- DTOs: Published Language (v1) ---

package api.v1;

import jakarta.validation.constraints.*;
import java.math.BigDecimal;
import java.util.List;

public record PlaceOrderRequest(
        @NotBlank String customerId,
        @NotEmpty List<Line> lines,
        @NotBlank String currency
) {
    public record Line(@NotBlank String sku,
                       @Positive int quantity,
                       @Positive BigDecimal unitPrice) {}
}

public record PlaceOrderResponse(String orderId, String status) {}

public record OrderView(String orderId,
                        String customerId,
                        String status,
                        String currency,
                        java.math.BigDecimal totalAmount,
                        java.time.Instant createdAt,
                        java.time.Instant updatedAt) {}
```

```java
// --- Controller: Open Host Service ---

package api.v1;

import org.springframework.http.*;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.net.URI;

@RestController
@RequestMapping(path = "/api/v1/orders", produces = "application/json")
public class OrdersOhsController {

    private final OrdersApplicationService app;
    private final IdempotencyService idempotency;

    public OrdersOhsController(OrdersApplicationService app, IdempotencyService idempotency) {
        this.app = app; this.idempotency = idempotency;
    }

    // Idempotent create with Idempotency-Key
    @PostMapping(consumes = "application/json")
    public ResponseEntity<PlaceOrderResponse> placeOrder(
            @RequestHeader(name = "Idempotency-Key") String key,
            @Validated @RequestBody PlaceOrderRequest req) {

        return idempotency.execute("placeOrder", key, req, () -> {
            var orderId = app.placeOrder(
                    req.customerId(),
                    req.currency(),
                    req.lines().stream().map(l -> new OrdersApplicationService.Line(l.sku(), l.quantity(), l.unitPrice())).toList()
            );
            var body = new PlaceOrderResponse(orderId, "PLACED");
            return ResponseEntity
                    .created(URI.create("/api/v1/orders/" + orderId))
                    .body(body);
        });
    }

    @GetMapping("/{orderId}")
    public OrderView getOrder(@PathVariable String orderId) {
        return app.getOrderView(orderId);
    }
}
```

```java
// --- Idempotency Port (persisted store; could be Redis/DB) ---

package api.v1;

import org.springframework.http.ResponseEntity;

import java.util.function.Supplier;

public interface IdempotencyService {
    <TReq, TResp> ResponseEntity<TResp> execute(String operation, String key, TReq requestBody, Supplier<ResponseEntity<TResp>> action);
}
```

```java
// --- Application Service: maps DTOs to domain, orchestrates transactions ---

package api.v1;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;

public class OrdersApplicationService {

    public record Line(String sku, int quantity, BigDecimal unitPrice) {}

    private final OrderFactory factory;
    private final OrderRepository orders;
    private final OrderQuery query; // read model

    public OrdersApplicationService(OrderFactory factory, OrderRepository orders, OrderQuery query) {
        this.factory = factory; this.orders = orders; this.query = query;
    }

    // @Transactional
    public String placeOrder(String customerId, String currency, List<Line> lines) {
        var order = factory.createAndPlace(new CustomerId(customerId),
                lines.stream().map(l -> new OrderFactory.LineRequest(new Sku(l.sku()), l.quantity(), new Money(l.unitPrice(), currency))).toList());
        orders.save(order);
        // publish domain events via outbox if needed
        return order.id();
    }

    public api.v1.OrderView getOrderView(String orderId) {
        var v = query.find(orderId);
        return new api.v1.OrderView(v.orderId(), v.customerId(), v.status(), v.currency(), v.totalAmount(), v.createdAt(), v.updatedAt());
    }
}
```

```java
// --- Problem+JSON error model & exception handling (stable codes) ---

package api;

import org.springframework.http.*;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.*;

import java.time.Instant;
import java.util.Map;

@RestControllerAdvice
public class ProblemHandler {

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String,Object>> onBadInput(IllegalArgumentException ex) {
        return problem(HttpStatus.BAD_REQUEST, "domain.validation_failed", ex.getMessage());
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<Map<String,Object>> onBeanValidation(MethodArgumentNotValidException ex) {
        return problem(HttpStatus.BAD_REQUEST, "request.validation_failed", "Invalid request");
    }

    @ExceptionHandler(IllegalStateException.class)
    public ResponseEntity<Map<String,Object>> onConflict(IllegalStateException ex) {
        return problem(HttpStatus.CONFLICT, "domain.conflict", ex.getMessage());
    }

    private static ResponseEntity<Map<String,Object>> problem(HttpStatus status, String code, String detail) {
        return ResponseEntity.status(status).contentType(MediaType.APPLICATION_PROBLEM_JSON).body(Map.of(
                "type", "https://errors.example.com/" + code,
                "title", status.getReasonPhrase(),
                "status", status.value(),
                "detail", detail,
                "timestamp", Instant.now()
        ));
    }
}
```

*Notes on the sample*

-   The **controller is the OHS**; DTOs are the **Published Language**.

-   **Idempotency-Key** ensures safe retries by consumers.

-   **Problem+JSON** provides a **stable error language**.

-   The domain (factory, repository, value objects) stays **behind** the façade.

-   Add **OpenAPI** (`/openapi.yaml`) and publish it with examples and a **deprecation** header strategy.


---

## Known Uses

-   **Payments:** Expose `authorize`, `capture`, `refund` in a stable API while internal risk engines evolve.

-   **Orders/Commerce:** Public order placement & status checks; pricing quotes; availability checks.

-   **Identity/Access:** User provisioning, roles, and permissions as a host service.

-   **Logistics:** Shipment creation, label generation, tracking queries.

-   **Telecom/Utilities:** Service activation, plan changes, metering reads via standardized APIs.


---

## Related Patterns

-   **Published Language:** The companion to OHS; defines the shared contract (schemas, messages).

-   **Anti-Corruption Layer (ACL):** For *your* outbound integrations to other contexts; OHS is inbound for others.

-   **Context Map (Customer–Supplier, Conformist):** OHS typically represents a **Supplier** with explicit contracts.

-   **Facade:** Technical resemblance, but OHS is **strategic, contract-driven** and externally consumable.

-   **Domain Service, Application Service, Repository:** Internal layers behind the OHS façade.

-   **Transactional Outbox / Event Publishing:** To notify consumers asynchronously after commands.


---
