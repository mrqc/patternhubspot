# Authorization — Security Pattern

## Pattern Name and Classification

**Name:** Authorization  
**Classification:** Security / Access Control / Identity & Access Management (IAM) — *Controlling “what” an authenticated principal can do after authentication*

---

## Intent

Ensure that an **authenticated principal** can only perform actions or access resources that they are **explicitly permitted** to, based on **roles**, **attributes**, **policies**, or **contextual conditions**, thereby enforcing **least privilege** and protecting resources from misuse or escalation.

---

## Also Known As

-   Access Control
    
-   Permission Checking
    
-   Entitlement Enforcement
    
-   Access Decision Pattern
    

---

## Motivation (Forces)

-   **Separation of concerns:** Authentication verifies *who* you are; Authorization decides *what* you may do.
    
-   **Principle of Least Privilege (POLP):** Grant only necessary privileges.
    
-   **Scalability:** Simple role checks don’t scale to complex multi-tenant or contextual access.
    
-   **Auditability:** Every access decision must be traceable, explainable, and logged.
    
-   **Consistency:** Centralized policies prevent drift and inconsistent rules.
    
-   **Evolving business logic:** Policies often change faster than code → externalized, data-driven rules.
    
-   **Regulatory & compliance:** Sensitive domains (finance, healthcare) require fine-grained, auditable authorization.
    

---

## Applicability

Use this pattern when:

-   You need to **restrict access** to data or operations after authentication.
    
-   Access control depends on **user roles, ownership, or contextual data** (department, tenant, region, time, etc.).
    
-   Multi-tenant systems require **data partitioning** per tenant.
    
-   Microservices must **consistently enforce** access rules across boundaries.
    

Avoid or simplify when:

-   All resources are **public** or read-only.
    
-   Context is static and trivial (e.g., single-user desktop app).
    
-   Security decisions are fully delegated to a **trusted gateway** or **external policy engine**.
    

---

## Structure

-   **Policy Store:** Central repository of authorization rules (RBAC/ABAC/PBAC).
    
-   **Policy Decision Point (PDP):** Evaluates policies based on subject, resource, action, and environment.
    
-   **Policy Enforcement Point (PEP):** Enforces decisions in applications or gateways.
    
-   **Context Provider:** Supplies attributes (roles, org, ownership, device, risk level).
    
-   **Audit Logger:** Records access requests, results, reasons, timestamps.
    
-   **Administration Interface:** Manage roles, permissions, tenants, and policies.
    

---

## Participants

-   **Subject (Principal):** The authenticated entity (user, service, device).
    
-   **Resource:** Object or API endpoint being accessed.
    
-   **Action:** Operation to perform (`read`, `write`, `delete`, `approve`).
    
-   **Policy:** Defines who can perform which action under which conditions.
    
-   **PDP:** Evaluates whether access should be allowed.
    
-   **PEP:** The middleware or service applying the PDP decision.
    
-   **Audit Log / SIEM:** Records all access decisions for compliance and forensics.
    

---

## Collaboration

1.  The principal is **authenticated** (session, JWT, mTLS, etc.).
    
2.  The principal sends a **request** to access a protected resource.
    
3.  The **PEP** intercepts the request and gathers **attributes** (subject roles, resource type, environment).
    
4.  The **PEP** calls the **PDP**, passing (subject, action, resource, context).
    
5.  The **PDP** evaluates policies (RBAC, ABAC, or custom) and returns a **decision** (`Permit`, `Deny`, or `NotApplicable`).
    
6.  The **PEP** enforces the result and optionally logs it in **Audit**.
    
7.  Audit records contain the principal, decision, timestamp, and justification.
    

---

## Consequences

**Benefits**

-   **Centralized, consistent control** over resource access.
    
-   Enforces **least privilege**, **defense in depth**, and **compliance**.
    
-   Supports **context-aware** and **dynamic** policies.
    
-   Facilitates **auditing** and **forensics**.
    

**Liabilities**

-   Poorly designed policies can create **denial-of-service** for legitimate users.
    
-   Centralized PDP may become a **performance bottleneck**.
    
-   Hard to maintain if mixed hard-coded and externalized rules.
    
-   Requires strong synchronization between **identity**, **policy**, and **resource** systems.
    

---

## Implementation

### Key Decisions

-   **Model choice:**
    
    -   **RBAC (Role-Based Access Control):** Roles aggregate permissions; simple, static.
        
    -   **ABAC (Attribute-Based Access Control):** Decisions depend on attributes (e.g., department, ownerId).
        
    -   **PBAC / Policy-Based Access Control:** Externalized policies (e.g., OPA/Rego, XACML).
        
    -   **ReBAC (Relationship-Based Access Control):** Graph-based, e.g., “user can view resource if they are part of same project.”
        
-   **Scope:** Global, per-tenant, per-resource.
    
-   **Enforcement point:** API Gateway, Controller interceptor, or service layer.
    
-   **Caching:** PDP results can be cached briefly for performance.
    
-   **Auditing:** Record both *grants* and *denies*.
    
-   **Delegation:** Support fine-grained sharing (“grant Alice read access to my document”).
    
-   **Policy language:** Internal DSL, JSON, Rego, SpEL, YAML, etc.
    
-   **Fail-safe defaults:** If in doubt, deny access.
    

### Anti-Patterns

-   Hardcoding permissions in UI or frontend.
    
-   Authorizing based on **username** instead of **roles/claims**.
    
-   Failing to enforce ownership checks on multi-tenant data.
    
-   “Permit-all” fallbacks when policy lookup fails.
    
-   Lack of auditing for access denials.
    

---

## Sample Code (Java, Spring Boot — Role + Ownership Based Access Control)

This example demonstrates:

-   **JWT-based authentication** (token contains roles and user ID).
    
-   **Annotation-based** authorization with ownership checks.
    
-   **Centralized service** for permission evaluation.
    

> Dependencies:
> 
> -   `spring-boot-starter-security`
>     
> -   `spring-boot-starter-web`
>     
> -   `io.jsonwebtoken:jjwt-api:0.11.5`
>     

```java
// domain/Document.java
package com.example.authz.domain;

public class Document {
  private Long id;
  private String ownerId;
  private String content;

  public Document(Long id, String ownerId, String content) {
    this.id = id; this.ownerId = ownerId; this.content = content;
  }

  public Long getId() { return id; }
  public String getOwnerId() { return ownerId; }
  public String getContent() { return content; }
}
```

```java
// security/AuthzService.java
package com.example.authz.security;

import org.springframework.stereotype.Service;
import java.util.Set;

@Service
public class AuthzService {

  /** Core policy: admins can do anything; owners can read/update their docs */
  public boolean canAccess(String action, String principalId, Set<String> roles, String resourceOwnerId) {
    if (roles.contains("ADMIN")) return true;
    return switch (action) {
      case "read", "update" -> principalId.equals(resourceOwnerId);
      case "delete" -> false; // only admin can delete
      default -> false;
    };
  }
}
```

```java
// security/JwtAuthFilter.java (simplified JWT parsing)
package com.example.authz.security;

import io.jsonwebtoken.*;
import io.jsonwebtoken.security.Keys;
import org.springframework.web.filter.OncePerRequestFilter;
import javax.servlet.*;
import javax.servlet.http.*;
import java.io.IOException;
import java.security.Key;
import java.util.*;

public class JwtAuthFilter extends OncePerRequestFilter {

  private static final Key key = Keys.hmacShaKeyFor("replace-with-a-long-256bit-secret-key".getBytes());

  @Override
  protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain)
      throws ServletException, IOException {
    String h = req.getHeader("Authorization");
    if (h != null && h.startsWith("Bearer ")) {
      try {
        Jws<Claims> jws = Jwts.parserBuilder().setSigningKey(key).build().parseClaimsJws(h.substring(7));
        req.setAttribute("userId", jws.getBody().getSubject());
        req.setAttribute("roles", Set.copyOf((List<String>) jws.getBody().get("roles")));
      } catch (Exception e) {
        res.sendError(401, "Invalid token");
        return;
      }
    }
    chain.doFilter(req, res);
  }
}
```

```java
// security/SecurityConfig.java
package com.example.authz.security;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

@Configuration
public class SecurityConfig {
  @Bean
  SecurityFilterChain chain(HttpSecurity http) throws Exception {
    http.csrf().disable()
        .authorizeHttpRequests(auth -> auth
            .antMatchers("/auth/**").permitAll()
            .anyRequest().authenticated())
        .addFilterBefore(new JwtAuthFilter(), UsernamePasswordAuthenticationFilter.class);
    return http.build();
  }
}
```

```java
// web/DocumentController.java
package com.example.authz.web;

import com.example.authz.domain.Document;
import com.example.authz.security.AuthzService;
import org.springframework.web.bind.annotation.*;
import javax.servlet.http.HttpServletRequest;
import java.util.*;

@RestController
@RequestMapping("/api/docs")
public class DocumentController {

  private final AuthzService authz;
  private final Map<Long, Document> store = new HashMap<>();

  public DocumentController(AuthzService authz) {
    this.authz = authz;
    // prepopulate
    store.put(1L, new Document(1L, "userA", "Doc 1 content"));
    store.put(2L, new Document(2L, "userB", "Doc 2 content"));
  }

  @GetMapping("/{id}")
  public Object read(@PathVariable Long id, HttpServletRequest req) {
    var doc = store.get(id);
    if (doc == null) return Map.of("error", "not found");
    String userId = (String) req.getAttribute("userId");
    @SuppressWarnings("unchecked")
    Set<String> roles = (Set<String>) req.getAttribute("roles");
    if (!authz.canAccess("read", userId, roles, doc.getOwnerId()))
      return Map.of("error", "forbidden");
    return doc;
  }

  @DeleteMapping("/{id}")
  public Object delete(@PathVariable Long id, HttpServletRequest req) {
    var doc = store.get(id);
    if (doc == null) return Map.of("error", "not found");
    String userId = (String) req.getAttribute("userId");
    @SuppressWarnings("unchecked")
    Set<String> roles = (Set<String>) req.getAttribute("roles");
    if (!authz.canAccess("delete", userId, roles, doc.getOwnerId()))
      return Map.of("error", "forbidden");
    store.remove(id);
    return Map.of("status", "deleted");
  }
}
```

**Notes:**

-   The `AuthzService` is the **Policy Decision Point**.
    
-   The controller acts as the **Policy Enforcement Point**.
    
-   For scalability, externalize `AuthzService` to an **OPA** (Open Policy Agent) instance, or integrate **Spring Authorization Server / ABAC DSL**.
    
-   In distributed systems, you can push down decisions as **JWT claims** or **OPA partial evaluations** to avoid latency.
    

---

## Known Uses

-   **Enterprise applications** implementing RBAC via roles like `ADMIN`, `MANAGER`, `USER`.
    
-   **Cloud platforms** (AWS IAM, GCP IAM, Azure RBAC) using hierarchical and resource-based policies.
    
-   **API Gateways** enforcing route-level and method-level policies via scopes and claims.
    
-   **OPA/Rego**, **XACML**, or **Cedar** policies in microservice architectures.
    
-   **Document sharing apps** (Google Docs, Notion) applying relationship-based policies (“viewer”, “editor”, “owner”).
    

---

## Related Patterns

-   **Authentication:** prerequisite for identity verification.
    
-   **API Key Management:** non-interactive identification of system clients.
    
-   **Policy Enforcement Point (PEP) & Policy Decision Point (PDP):** foundational sub-patterns.
    
-   **Attribute-Based Access Control (ABAC):** generalization of RBAC.
    
-   **Role-Based Access Control (RBAC):** specialization of Authorization for simplicity.
    
-   **Federated Identity (OIDC/SAML):** enables delegated authorization with claims.
    
-   **Audit Logging & Security Event Correlation:** companion for compliance and traceability.
    

---

## Implementation Checklist

-   Choose **model** (RBAC, ABAC, PBAC, or ReBAC) based on complexity and domain.
    
-   Clearly separate **authentication** (identity) from **authorization** (access rights).
    
-   Implement **policy decision points** (centralized or decentralized).
    
-   Enforce **fail-safe deny**: default to denial on missing rules or errors.
    
-   Externalize policies to reduce coupling; allow **policy versioning and auditing**.
    
-   Ensure **multi-tenant isolation** (tenantID checks).
    
-   Cache short-lived PDP decisions; invalidate on policy updates.
    
-   Include **contextual attributes** (time, device, IP, location) for ABAC.
    
-   Log all access grants and denials with **principal**, **action**, **resource**, **decision**, and **reason**.
    
-   Regularly review roles, scopes, and policies to prevent privilege creep.

