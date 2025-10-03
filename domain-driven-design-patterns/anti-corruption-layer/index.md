
# Anti Corruption Layer — Domain-Driven Design Pattern

---

## Pattern Name and Classification

-   **Name:** Anti Corruption Layer (ACL)

-   **Category:** Domain-Driven Design (DDD) / Strategic Design / Context Mapping

-   **Level:** Integration boundary pattern (between bounded contexts or external systems)


---

## Intent

Protect your core domain from **conceptual and technical “corruption”** when integrating with a foreign model (legacy system, third-party API, another bounded context) by interposing a **translation/adapter layer** that:

-   **Translates** foreign concepts into your **ubiquitous language**,

-   **Isolates** protocols/technology of the external system,

-   **Enforces** domain invariants at the boundary.


---

## Also Known As

-   **ACL**, Translation Layer, Protection Layer

-   Gateway + Translator (Evans)

-   Adapter/Façade + Mapper boundary


---

## Motivation (Forces)

-   External systems expose different **concepts, constraints, and names** (often leaky or inconsistent).

-   Direct coupling leaks **foreign language and quirks** into the core model → erosion of domain purity, testability, and agility.

-   You need to **integrate** while keeping your model **clean, stable, and evolvable**.


**Forces / Trade-offs**

-   -   Protects invariants, improves clarity and testability.

-   − Extra code, latency, and operational surface.

-   Requires disciplined **ownership** and **versioning** of the boundary.


---

## Applicability

Use an ACL when:

-   Integrating with **legacy** or vendor systems you cannot change.

-   Two **bounded contexts** must talk but use different ubiquitous languages.

-   You foresee **long-term evolution** on your side independent of the external.


Avoid or downsize when:

-   Models are already **aligned** and stable (simple adapter might suffice).

-   Integration is **short-lived** or low value (YAGNI).


---

## Structure

-   **Client (Core Domain)** → depends on **Ports** (interfaces) in your language.

-   **ACL Implementation** (Adapters + Translators + Anti-corruption Policies) realizes the ports, calls the **Foreign System** via its protocol, and maps back/forth.

-   **Mappers** convert DTOs/enums/errors; **Policies** guard invariants.


```scss
[Core Domain / App Service]
          │ (Port in Ubiquitous Language)
          ▼
   [ACL Adapter + Policies]
          │ (protocol mapping, DTO translation)
          ▼
     [Foreign System API]
```

---

## Participants

-   **Port (Domain-side interface):** Your language and intent.

-   **ACL Adapter:** Implements the port; orchestrates calls.

-   **Translators/Mappers:** Deterministic mapping between models.

-   **Anti-corruption Policies:** Validations, compensations, defaults.

-   **Foreign System Client:** Low-level API/protocol (HTTP/SOAP/JDBC).

-   **Domain Model / Services:** Consume the port without foreign leakage.


---

## Collaboration

-   Pairs naturally with **Hexagonal/Ports-and-Adapters** (ACL as an outbound adapter).

-   Works with **Saga/Process Manager** to coordinate cross-context workflows.

-   Often combined with **Domain Events** (publish clean events after translation).

-   Coexists with **Outbox** for reliable propagation across boundaries.


---

## Consequences

**Benefits**

-   Core model remains **pure**; changes in foreign API isolated.

-   **Testability:** ACL is mockable; mappings can be unit-tested.

-   **Resilience:** Central place for retries, timeouts, idempotency, compensations.


**Liabilities**

-   Extra **complexity & cost** (code, monitoring, latency).

-   Risk of “**god translator**” if the foreign model is not well sliced.

-   Requires disciplined **versioning** and **contract tests**.


---

## Implementation

1.  **Define Ports in your language** (no foreign DTOs leak in).

2.  **Implement an ACL Adapter** that talks to the foreign API and returns domain objects.

3.  **Create translators/mappers** (one direction per concern, keep pure and deterministic).

4.  **Enforce policies at the boundary**: input validation, defaulting, invariants, error mapping.

5.  **Handle reliability**: retries with jitter, circuit breaker, idempotency keys, timeouts.

6.  **Version your mappings** (V1/V2) to absorb external change.

7.  **Test**: golden files for mappings, contract tests against sandbox of the foreign system.

8.  **Observe**: feature-level metrics (hit rate, mapping failures), structured logs with correlation IDs.


---

## Sample Code (Java, Spring — Integrating a Legacy CRM)

**Goal:** Core domain needs `CustomerProfile` in its language. Legacy CRM exposes `LegacyCustomerDTO` with different fields & semantics.

```java
// 1) Domain-side model (clean)
public record CustomerId(String value) {
    public CustomerId {
        if (value == null || value.isBlank()) throw new IllegalArgumentException("id");
    }
}

public enum Tier { STANDARD, GOLD, PLATINUM }

public record CustomerProfile(
        CustomerId id,
        String fullName,
        String email,
        Tier tier,
        boolean marketingOptIn
) {}
```

```java
// 2) Domain Port: what the core needs (no foreign types)
public interface CustomerDirectory {
    CustomerProfile findById(CustomerId id);
    List<CustomerProfile> searchByEmailDomain(String domain);
}
```

```java
// 3) Foreign/legacy DTOs (kept in adapter package; never leak into domain)
class LegacyCustomerDTO {
    public String cust_no;         // e.g., "C-00123"
    public String first_name;
    public String last_name;
    public String mail;
    public String segment;         // e.g., "A","B","C"
    public String mrkt_flag;       // "Y"/"N"/null
}
```

```java
// 4) Translator (pure mapping + policy defaults)
final class LegacyCustomerTranslator {

    CustomerProfile toDomain(LegacyCustomerDTO dto) {
        var id = new CustomerId(dto.cust_no);
        var fullName = (dto.first_name + " " + dto.last_name).trim();
        var email = dto.mail;

        var tier = switch (dto.segment == null ? "C" : dto.segment) {
            case "A" -> Tier.PLATINUM;
            case "B" -> Tier.GOLD;
            default -> Tier.STANDARD; // policy defaulting
        };

        boolean marketingOptIn = "Y".equalsIgnoreCase(dto.mrkt_flag);

        // Boundary validation (anti-corruption policy)
        if (email == null || !email.contains("@")) {
            // Map foreign inconsistency to a domain-safe form or raise a domain exception
            throw new IllegalStateException("foreign email invalid for " + id.value());
        }

        return new CustomerProfile(id, fullName, email, tier, marketingOptIn);
    }
}
```

```java
// 5) Low-level foreign client (HTTP, retried/circuit-broken)
interface LegacyCrmClient {
    Optional<LegacyCustomerDTO> fetchById(String customerNo);
    List<LegacyCustomerDTO> queryByEmailDomain(String domain);
}
```

```java
// 6) ACL Adapter implementing the Port using the client + translator
import org.slf4j.*;

public class CrmAclAdapter implements CustomerDirectory {
    private static final Logger log = LoggerFactory.getLogger(CrmAclAdapter.class);

    private final LegacyCrmClient client;
    private final LegacyCustomerTranslator mapper = new LegacyCustomerTranslator();

    public CrmAclAdapter(LegacyCrmClient client) {
        this.client = client;
    }

    @Override
    public CustomerProfile findById(CustomerId id) {
        var dto = client.fetchById(id.value())
                        .orElseThrow(() -> new NoSuchElementException("Customer " + id.value() + " not found"));
        var profile = mapper.toDomain(dto);
        log.info("acl=crm map=ok id={}", id.value());
        return profile;
    }

    @Override
    public List<CustomerProfile> searchByEmailDomain(String domain) {
        return client.queryByEmailDomain(domain).stream()
                     .map(dto -> {
                         try { return mapper.toDomain(dto); }
                         catch (Exception ex) {
                             log.warn("acl=crm map=fail cust_no={} reason={}", dto.cust_no, ex.toString());
                             return null; // or use error channel / dead-letter
                         }
                     })
                     .filter(Objects::nonNull)
                     .toList();
    }
}
```

```java
// 7) Example Spring configuration wiring the adapter behind the port
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
class AclConfig {

    @Bean
    CustomerDirectory customerDirectory(LegacyCrmClient client) {
        // the rest of the app injects CustomerDirectory; foreign types are invisible
        return new CrmAclAdapter(client);
    }
}
```

```java
// 8) Example application service (uses the port; core remains clean)
public class LoyaltyApplicationService {
    private final CustomerDirectory customers;

    public LoyaltyApplicationService(CustomerDirectory customers) {
        this.customers = customers;
    }

    public Tier lookupTier(String customerNo) {
        return customers.findById(new CustomerId(customerNo)).tier();
    }
}
```

**Notes**

-   All **foreign DTOs/protocols** are contained in the adapter package.

-   The **translator** applies policy defaults and validation (true anti-corruption).

-   Add **resilience** (timeouts, retries, circuit breaker, bulkhead), **idempotency**, and **observability** at the adapter.


---

## Known Uses

-   **Payment gateways**: Gateway/translator hides PSP quirks and error codes.

-   **Search/reco migrations**: New domain talks to legacy engine via ACL until replacement.

-   **ERP/CRM integrations**: Domain keeps its own Customer model; ACL maps to SAP/Salesforce schemas.

-   **Strangler migrations**: New bounded context grows while ACL shields it from the old monolith.


---

## Related Patterns

-   **Bounded Context & Context Map** — ACL is a context map relationship.

-   **Hexagonal Architecture (Ports & Adapters)** — ACL is a specialized outbound adapter.

-   **Translator / Mapper / Façade / Adapter (GoF)** — building blocks of ACL.

-   **Saga / Process Manager** — when invariants span contexts.

-   **Domain Events** — publish clean events after translation.

-   **Transactional Outbox** — reliable handoff across the boundary.
