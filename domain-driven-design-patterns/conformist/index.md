
# Conformist — Domain-Driven Design Pattern

---

## Pattern Name and Classification

-   **Name:** Conformist

-   **Category:** DDD / Strategic Design / Context Mapping

-   **Level:** Inter-context integration relationship


---

## Intent

When integrating two bounded contexts with **asymmetric power** (the provider dominates), the consumer **adopts the provider’s model and language as-is**—*conforming* to its published contracts instead of protecting itself behind an Anti-Corruption Layer (ACL).

---

## Also Known As

-   Consumer Conformance

-   Provider-Dominated Relationship

-   “Just Use Their Model”


---

## Motivation (Forces)

-   **Power imbalance:** A large/central platform (Payments, Identity, ERP) dictates the model; changing it is unlikely.

-   **Speed-to-integration:** Translators/ACLs slow down; conformance reduces initial lead time.

-   **Stability of provider contracts:** Well-governed “Published Language” with versioning and SLAs may be safe to adopt.


**Forces / Trade-offs**

-   **Pros:** Fast integration, less code, fewer moving parts.

-   **Cons:** **Model leakage** into your core, tighter coupling, harder long-term evolution; upgrade cadence tied to provider.


---

## Applicability

Use Conformist when:

-   The provider **won’t change** for you (multi-tenant SaaS, de facto standard).

-   The provider publishes **clean, stable contracts** (OpenAPI/Avro/gRPC) with versioning.

-   You need **quick adoption** and can tolerate coupling.


Avoid (prefer ACL) when:

-   You must **preserve a distinct ubiquitous language** in your core.

-   The provider’s model is **messy or unstable**.

-   Compliance/security demands **boundary policies and translation**.


---

## Structure

-   **Provider Context** exposes an **Open Host Service / Published Language** (APIs, events, schemas).

-   **Conformist (Consumer) Context** **imports/uses** those contracts directly (generated DTOs/clients), optionally wrapping them thinly, but **does not translate semantics**.


```pgsql
[Provider Context]
   ↑  Published Language (API/Events/Schemas)
   │
[Conformist Context]
   └─ uses provider DTOs/types directly (no ACL)
```

---

## Participants

-   **Provider Context:** Owns the canonical model and contracts.

-   **Conformist Context (Consumer):** Uses provider DTOs/enums/errors as part of its integration surface.

-   **Contract Artifacts:** OpenAPI/Avro/gRPC schemas, SDKs, event types.

-   **Minimal Glue Code:** Client configuration, retries, auth (not semantic translation).


---

## Collaboration

-   Often paired with **Open Host Service** and **Published Language** from the provider.

-   May still use **Sagas/Process Managers** and **Outbox** for reliability—but without semantic translation.

-   Upgrades follow the provider’s **versioning** and **deprecation** timelines.


---

## Consequences

**Benefits**

-   Very **fast integration**; fewer layers to maintain.

-   **Lower cognitive load**—one ubiquitous language (the provider’s) across the boundary.

-   Easier **tooling/SDK reuse** (codegen, typed clients).


**Liabilities**

-   **Tight coupling:** Provider’s names and quirks leak in.

-   **Change ripple:** Provider version bumps force consumer updates.

-   **Domain purity risk:** Your domain may contort to fit the external language.

-   **Migration cost:** Switching providers later is expensive.


Mitigations:

-   Keep provider types at the **edge** of your application services (don’t let them sprawl into the core aggregates).

-   **Wrap** clients behind ports (interfaces) to localize blast radius (still conformist if semantics remain provider’s).

-   Track provider **deprecation schedules**; automate compatibility tests.


---

## Implementation

1.  **Adopt the Published Language**: import provider OpenAPI/Avro/gRPC and generate DTOs/clients.

2.  **Define a Port** in your app layer that **exposes provider semantics directly** (conformance).

3.  **Use provider DTOs** in the port and in application services; avoid creating parallel domain objects unless necessary.

4.  **Reliability**: add retries, timeouts, idempotency, circuit breakers—without semantic translation.

5.  **Contract Testing**: run provider’s compatibility tests; pin schema versions; monitor SDK updates.

6.  **Bound the blast radius**: forbid provider types in core aggregates; keep them in application/integration layers.

7.  **Plan for evolution**: feature flags for cutovers, canary usage of new provider versions.


---

## Sample Code (Java, Spring) — Conformist to a Payment Provider

*Scenario:* Your “Billing” context conforms to the **AcmePay** provider. You **generate** client & DTOs from the provider’s OpenAPI and **use them directly**—no ACL/translation layer.

```java
// === 1) Generated from provider's OpenAPI (do not edit) ===================
// package: com.acmepay.sdk (generated)
package com.acmepay.sdk;

public class ChargeRequest {
    public String customerId;
    public long amountCents;
    public String currency;   // "EUR", "USD", ...
    public String idempotencyKey;
}

public class ChargeResponse {
    public String chargeId;
    public String status;     // "AUTHORIZED", "DECLINED", "FAILED"
}

public interface AcmePayApi {
    ChargeResponse authorize(ChargeRequest request);
}
```

```java
// === 2) Conformist Port (semantics match provider; still your interface) ===
package billing.app;

import com.acmepay.sdk.ChargeRequest;
import com.acmepay.sdk.ChargeResponse;

public interface PaymentsPort {
    ChargeResponse authorize(ChargeRequest request);
}
```

```java
// === 3) Adapter simply delegates to provider SDK (no translation) ==========
package billing.infra;

import billing.app.PaymentsPort;
import com.acmepay.sdk.AcmePayApi;
import com.acmepay.sdk.ChargeRequest;
import com.acmepay.sdk.ChargeResponse;

public class AcmePayConformistAdapter implements PaymentsPort {
    private final AcmePayApi api;
    public AcmePayConformistAdapter(AcmePayApi api) { this.api = api; }

    @Override
    public ChargeResponse authorize(ChargeRequest request) {
        // reliability knobs still ok (timeouts/retries), but semantics unchanged
        return api.authorize(request);
    }
}
```

```java
// === 4) Application Service uses provider DTOs directly ====================
package billing.app;

import com.acmepay.sdk.ChargeRequest;
import com.acmepay.sdk.ChargeResponse;

import java.util.UUID;

public class BillingApplicationService {
    private final PaymentsPort payments;

    public BillingApplicationService(PaymentsPort payments) {
        this.payments = payments;
    }

    public String chargeCustomer(String customerId, long totalCents, String currency) {
        ChargeRequest req = new ChargeRequest();
        req.customerId = customerId;
        req.amountCents = totalCents;
        req.currency = currency;
        req.idempotencyKey = UUID.randomUUID().toString();

        ChargeResponse resp = payments.authorize(req);
        if (!"AUTHORIZED".equals(resp.status)) {
            throw new IllegalStateException("Payment " + resp.status);
        }
        return resp.chargeId;
    }
}
```

```java
// === 5) Controller (thin) ==================================================
package billing.api;

import billing.app.BillingApplicationService;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/billing")
public class BillingController {
    private final BillingApplicationService app;
    public BillingController(BillingApplicationService app) { this.app = app; }

    @PostMapping("/charge")
    public String charge(@RequestParam String customerId,
                         @RequestParam long amountCents,
                         @RequestParam(defaultValue = "EUR") String currency) {
        return app.chargeCustomer(customerId, amountCents, currency);
    }
}
```

**Notes**

-   We **conform** by using `ChargeRequest/Response` directly. No semantic translation happens.

-   To **limit spread**, keep provider DTOs in **app/adapter layers**; do not embed them inside aggregates.

-   If you later switch providers, you’ll likely need broader changes—this is an accepted trade-off in Conformist.


---

## Known Uses

-   **Payments** (Stripe/Adyen/Braintree): consumers adopt provider’s charges/refunds model & webhooks.

-   **Identity/OAuth** (Auth0/Keycloak): consumers use token formats & claims as-is.

-   **Shipping/Logistics** (UPS/FedEx): provider label/tracking schemas adopted across systems.

-   **Cloud Billing/Usage**: consumers ingest provider-defined usage records/events.


---

## Related Patterns

-   **Published Language / Open Host Service:** Enablers on the provider side.

-   **Customer–Supplier (Context Map):** Describes the power dynamic officially.

-   **Anti-Corruption Layer:** The *alternative* when you need to shield your model.

-   **Partnership / Shared Kernel:** Other relationships with different trade-offs.

-   **Saga / Process Manager:** Orchestrate flows that include the provider.

-   **Outbox / Idempotency:** Reliability mechanisms often needed even in Conformist.
