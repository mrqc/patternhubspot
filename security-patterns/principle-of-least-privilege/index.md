# Principle of Least Privilege — Security Pattern

## Pattern Name and Classification

**Name:** Principle of Least Privilege (PoLP)  
**Classification:** Security / Access Control / Governance — *Minimize authority: every identity, process, token, network path, and component runs with only the permissions strictly necessary for its purpose, and only for as long as needed.*

---

## Intent

Limit **blast radius** and **abuse potential** by granting the **smallest possible set of privileges** (scope, resources, actions, duration) to subjects and components, and by enforcing **deny-by-default** with explicit, audited grants.

---

## Also Known As

-   Least Authority (POLA)
    
-   Minimal Privilege
    
-   Need-to-Know / Need-to-Use
    
-   Zero Trust Authorization (operational practice)
    

---

## Motivation (Forces)

-   **Risk reduction:** Fewer privileges → fewer ways to exfiltrate, destroy, or corrupt data.
    
-   **Cascading compromise:** Compromised tokens with broad rights become catastrophic; tight scopes limit impact.
    
-   **Regulatory pressure:** Segregation of duties, auditability, and data minimization are recurring controls.
    
-   **Operational reality:** “Temporary exceptions” and convenience often bloat privileges (“privilege creep”).
    
-   **Microservices & multi-tenancy:** Fine-grained resource boundaries are necessary to keep tenants isolated.
    
-   **Supply chain:** Third-party integrations must be constrained to only their contract surface.
    

Trade-offs: more **policy management**, **role design** work, and **operational overhead** (rotations, approvals), and the risk of **over-restricting** and blocking legitimate work.

---

## Applicability

Apply PoLP when:

-   Issuing **credentials/tokens/keys** to users, services, CI/CD, or partners.
    
-   Designing **IAM roles**, **Kubernetes RBAC**, **database roles**, **cloud policies**, **network ACLs**, **sudoers**.
    
-   Exposing **APIs/webhooks** or delegating to background jobs.
    
-   Building **multi-tenant** systems or handling sensitive data (PII/PHI/PCI).
    

Consider complementary controls when:

-   A function must perform **broad, high-risk** operations: require **short-lived elevation** with approvals and extra monitoring (“break-glass”).
    
-   The environment is **air-gapped** but still needs internal least privilege (data-class boundaries still matter).
    

---

## Structure

-   **Subjects:** users, services, workloads, build agents.
    
-   **Resources:** data objects, APIs, databases, files, queues, clusters.
    
-   **Actions:** verbs on resources (`read`, `write`, `approve`, `delete`, `rotate`).
    
-   **Grants (Scopes):** tuples *(subject, resource-selector, actions, constraints, expiry)*.
    
-   **Policy Store (PDP):** evaluates grants and context (tenant, time, device posture).
    
-   **Enforcement Points (PEP):** gateways, service methods, DBs, OS, network devices.
    
-   **Observability:** audit logs, approvals, anomaly alerts, recertification workflows.
    

---

## Participants

-   **Role/Policy Designer:** curates roles from minimal permissions; avoids wildcards.
    
-   **Identity Provider / IAM:** issues identities and tokens with scopes/claims and expiries.
    
-   **Policy Decision Point (PDP):** answers “Permit/Deny” using grants and context.
    
-   **Policy Enforcement Point (PEP):** code that calls PDP or enforces locally.
    
-   **Auditor / Risk:** reviews grants, accesses, and emergency elevations.
    

---

## Collaboration

1.  **Model resources** and actions explicitly (no “\*”).
    
2.  **Create minimal roles** or direct grants for each use-case (task → permissions).
    
3.  **Issue short-lived tokens** (minutes–hours) carrying only needed scopes and tenant/resource selectors.
    
4.  **PEP checks** the request: subject, action, resource, constraints (tenant, time, IP).
    
5.  **Decision + audit**: PDP returns permit/deny with reason; event is logged.
    
6.  **Recertify & rotate**: periodic reviews prune unused/overly broad privileges; tokens/keys rotate.
    

---

## Consequences

**Benefits**

-   Limits damage from stolen credentials and bugs (smaller blast radius).
    
-   Improves **compliance** and **forensics** (clear, auditable grants).
    
-   Encourages **clean architecture** (explicit boundaries and resource models).
    

**Liabilities**

-   **Complexity** in policy design and maintenance.
    
-   Risk of **over-restriction** causing usability incidents.
    
-   Requires **good inventory** of resources and continuous review to avoid drift.
    

---

## Implementation

### Key Decisions

-   **Deny by default:** closed perimeter; only explicit, reviewed grants open paths.
    
-   **Granularity:** prefer resource-level or tenant-level selectors over global roles.
    
-   **Time bounds:** issue **ephemeral** credentials; require re-authentication or approval for elevation.
    
-   **Context:** add conditions (tenant, attributes, network, device, shift/time).
    
-   **Separation of duties:** ensure no single identity can create/approve/pay (or deploy/approve).
    
-   **Token content:** use **scopes/claims** listing *actions + resource selectors + expiry + tenant*.
    
-   **Where to enforce:** defense in depth — API gateway, service layer, DB, and network (e.g., SGs/NetworkPolicies).
    
-   **Review & automation:** access reviews, usage telemetry, and removal of unused privileges.
    

### Anti-Patterns

-   “**Admin**” or “**god-mode**” tokens used by automation and humans alike.
    
-   Policies with wildcards (`"*:*"`) or cross-tenant resource selectors.
    
-   **Long-lived** secrets embedded in code or CI variables.
    
-   Shared accounts (no attribution) and skipped audits.
    
-   Granting permanent elevation to fix rare incidents (“temporary forever”).
    

### Practical Checklist

-   Inventory resources and define **verbs**.
    
-   Build **least-priv roles** from verbs; **no wildcards**; prefer *allow* rules only.
    
-   Enforce **short-lived tokens** with scopes; rotate keys; disable unused ones.
    
-   Put PEPs at **gateways** and **service methods**; DB accounts per service with **limited SQL privileges**.
    
-   Add **monitoring**: denied/allowed decisions, unusual elevation, cross-tenant access.
    
-   Recertify regularly; remove stale grants; track last-used timestamps.
    

---

## Sample Code (Java) — Minimal, Scoped, Time-Bound Authorization

The snippet shows:

-   A **permission model** with resource scoping and expiry.
    
-   An **authorizer** that enforces least privilege (no wildcard by default).
    
-   A **service** that always checks permissions *and* constrains data access by tenant/resource.
    

> No frameworks required (pure Java). Replace in production with your PDP/OPA/ABAC engine and JWT parsing.

```java
package com.example.leastpriv;

import java.time.Instant;
import java.util.*;
import java.util.function.Predicate;

/** Define actions (verbs) explicitly. */
enum Action { READ, CREATE, UPDATE, DELETE, APPROVE, REFUND }

/** Reference to a concrete resource. */
record ResourceRef(String type, String tenantId, String id) {}

/** A minimal, least-privilege scope/grant. */
final class Scope {
  final String resourceType;         // e.g., "invoice"
  final String tenantId;             // must match the request's tenant
  final Set<Action> actions;         // allowed verbs
  final Optional<String> resourceId; // optional exact resource id (no wildcard)
  final Instant expiresAt;           // short-lived

  Scope(String type, String tenantId, Set<Action> actions, String resourceId, Instant expiresAt) {
    this.resourceType = Objects.requireNonNull(type);
    this.tenantId = Objects.requireNonNull(tenantId);
    this.actions = Set.copyOf(actions);
    this.resourceId = Optional.ofNullable(resourceId);
    this.expiresAt = Objects.requireNonNull(expiresAt);
  }

  boolean permits(Action act, ResourceRef res, Instant now) {
    if (now.isAfter(expiresAt)) return false;
    if (!resourceType.equals(res.type())) return false;
    if (!tenantId.equals(res.tenantId())) return false;
    if (!actions.contains(act)) return false;
    return resourceId.map(id -> id.equals(res.id())).orElse(true);
  }
}

/** Principal with least-privilege scopes. */
record Principal(String subject, List<Scope> scopes) {}

/** Authorizer enforcing deny-by-default and no-wildcard semantics. */
final class Authorizer {
  public void require(Principal p, Action act, ResourceRef res) {
    Instant now = Instant.now();
    boolean ok = p.scopes().stream().anyMatch(s -> s.permits(act, res, now));
    if (!ok) throw new Forbidden("deny: " + p.subject() + " cannot " + act + " " + res);
  }
  static class Forbidden extends RuntimeException { Forbidden(String m){ super(m); } }
}

/** Example repository with tenant scoping at the data layer (defense in depth). */
final class InvoiceRepo {
  static final class Invoice { final String tenantId, id; final long cents; Invoice(String t, String i, long c){tenantId=t;id=i;cents=c;} }
  private final Map<String, Invoice> store = new HashMap<>(); // key = tenant:id

  Optional<Invoice> get(String tenantId, String id) {
    return Optional.ofNullable(store.get(tenantId + ":" + id));
  }
  void put(Invoice inv) {
    store.put(inv.tenantId + ":" + inv.id, inv);
  }
}

/** Service that always checks least-privilege scopes AND constrains queries by tenant. */
final class InvoiceService {
  private final Authorizer auth = new Authorizer();
  private final InvoiceRepo repo = new InvoiceRepo();

  public Optional<InvoiceRepo.Invoice> viewInvoice(Principal p, String tenantId, String invoiceId) {
    ResourceRef res = new ResourceRef("invoice", tenantId, invoiceId);
    auth.require(p, Action.READ, res);
    // Data-layer guard: never read outside tenantId even if a bug elsewhere
    return repo.get(tenantId, invoiceId);
  }

  public void createInvoice(Principal p, String tenantId, String invoiceId, long cents) {
    ResourceRef res = new ResourceRef("invoice", tenantId, invoiceId);
    auth.require(p, Action.CREATE, res);
    repo.put(new InvoiceRepo.Invoice(tenantId, invoiceId, cents));
  }

  public void refundInvoice(Principal p, String tenantId, String invoiceId) {
    ResourceRef res = new ResourceRef("invoice", tenantId, invoiceId);
    auth.require(p, Action.REFUND, res);
    // ... call payment gateway with tenant-bound, least-privileged credentials ...
  }
}

/** Demo: build a short-lived, narrow scope token and use it. */
class Demo {
  public static void main(String[] args) {
    Instant ttl = Instant.now().plusSeconds(600); // 10 minutes
    Scope readSpecific = new Scope("invoice", "acme", Set.of(Action.READ), "inv-123", ttl);
    Scope refundSpecific = new Scope("invoice", "acme", Set.of(Action.REFUND), "inv-123", ttl);
    Principal caller = new Principal("svc:billing-worker", List.of(readSpecific, refundSpecific));

    InvoiceService svc = new InvoiceService();
    // Requires CREATE — should fail because the principal lacks CREATE
    try {
      svc.createInvoice(caller, "acme", "inv-123", 1999);
    } catch (Authorizer.Forbidden e) {
      System.out.println(e.getMessage()); // deny as expected
    }

    // Assuming invoice exists, the principal can READ and REFUND that single invoice only
    // Any other tenant or invoiceId will be denied automatically.
  }
}
```

**What this demonstrates**

-   **No wildcards**: scopes can optionally pin to a single `resourceId`; otherwise still constrained by `resourceType` and **tenant**.
    
-   **Short-lived**: each scope has an `expiresAt`.
    
-   **Deny-by-default**: if no scope matches, access is denied.
    
-   **Defense in depth**: the repository is also tenant-scoped.
    

> In production: parse JWTs to `Principal` and `Scope`s; enforce at API gateway and service methods; constrain database access with **least-privileged DB roles** (e.g., only `SELECT` on tenant partitions for read-only services).

---

## Known Uses

-   **Cloud IAM** (AWS/GCP/Azure): resource-level policies, condition keys, time-bounded sessions (STS/Workload Identity).
    
-   **Kubernetes RBAC & NetworkPolicies:** service accounts scoped to namespaces; pods limited by egress/ingress.
    
-   **Databases:** per-service accounts with schema- or table-level privileges; RLS (Row-Level Security) by tenant.
    
-   **POSIX & sudo:** minimal file permissions; `sudo` rules for specific commands with logging.
    
-   **API tokens & webhooks:** tokens limited to specific endpoints, tenants, and HTTP methods; short TTL.
    
-   **CI/CD:** job-scoped deploy keys limited to a single repo/namespace/environment.
    

---

## Related Patterns

-   **Authorization (RBAC/ABAC/ReBAC):** the decision models used to express PoLP.
    
-   **Separation of Duties (SoD):** ensure no single identity can complete sensitive workflows.
    
-   **Zero Trust Networking:** pair identity-aware policies with least network reachability.
    
-   **Short-Lived Credentials / Just-In-Time Access:** ephemeral elevation with approvals.
    
-   **Audit Logging & Recertification:** governance to keep privileges minimal over time.
    
-   **Attribute-Based Access Control (ABAC):** express conditions like tenant, department, time.
    

---

## Implementation Notes (beyond the code)

-   **DB accounts:** create per-service users with only needed verbs; enable **RLS** to enforce tenant filters.
    
-   **Secrets & keys:** issue **ephemeral**, rotation-backed credentials; store in a vault; never embed in code.
    
-   **Gateways:** require scopes at the edge (e.g., `orders:read:tenant=acme`), verify JWT `aud/iss/exp`.
    
-   **OS/containers:** drop root, use read-only FS, Linux capabilities minimal set, seccomp/AppArmor.
    
-   **Network:** default-deny; open only needed egress/ingress per workload.
    
-   **Operations:** add **break-glass** with short TTL, MFA, and mandatory post-incident review.

