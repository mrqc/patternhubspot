# Zero Trust Architecture — Security Pattern

## Pattern Name and Classification

-   **Name:** Zero Trust Architecture (ZTA)
    
-   **Classification:** Security / Enterprise Architecture / Access Control (ABAC + Continuous Verification)
    

## Intent

Eliminate implicit trust based on network location by **continuously verifying identity, device health, and context** for every request, enforcing **least privilege** via **explicit, policy-driven decisions** across people, devices, and services—**assume breach** and contain impact through segmentation and strong authentication.

## Also Known As

-   BeyondCorp-style Access
    
-   Per-Request Trust Evaluation
    
-   Never Trust, Always Verify
    

## Motivation (Forces)

-   **Perimeter erosion:** Cloud, SaaS, remote work, and partner integrations make “inside = trusted” false.
    
-   **Compromised nodes:** Phishing, token theft, and lateral movement demand **continuous** checks.
    
-   **Heterogeneous estates:** BYOD, IoT, legacy apps, microservices, and multi-cloud.
    
-   **Business velocity vs. security:** Strong security must not cripple developer and user productivity.
    
-   **Compliance & auditability:** Need centralized policies, consistent enforcement, clear evidence.  
    ZTA balances these by moving from **implicit network trust** to **explicit, identity- and posture-based authorization** with **fine-grained segmentation**.
    

## Applicability

Adopt ZTA when you have:

-   Remote/hybrid workforce or third-party access.
    
-   Multi-cloud/microservices where IP-based allowlists don’t scale.
    
-   Sensitive data (PII/PHI/PCI) and strong audit requirements.
    
-   Repeated lateral-movement incidents or credential phishing risks.
    
-   Need for **standardized policy** across web, API, and service-to-service traffic.
    

## Structure

**Logical building blocks**

-   **Policy Enforcement Point (PEP):** Gateways, sidecars, service mesh, or app filters that intercept requests.
    
-   **Policy Decision Point (PDP):** Central policy engine (e.g., OPA/ABAC engine) evaluating identity, device, risk, and resource.
    
-   **Identity Provider (IdP):** MFA, strong auth, issues tokens/claims (OIDC/OAuth2).
    
-   **Device/Workload Identity:** Certificates (mTLS/SPIFFE), EDR posture, attestation.
    
-   **Inventory/Context:** CMDB, asset inventory, labels, data classification.
    
-   **Trust Signals:** Risk scores, geolocation, anomaly detection.
    
-   **Microsegmentation:** Network and identity-based segmentation (SDN, mesh AuthorizationPolicies).
    
-   **Telemetry & SIEM:** Centralized logs, detections, and feedback loops.
    
-   **Key Management:** CA/KMS/HSM for token signing and mTLS.
    

**Data/decision flow (simplified)**

```bash
Client/Workload -> PEP (gateway/sidecar) -> PDP (policy eval) -> allow/deny + obligations
        ^                    |                      |
      IdP tokens         Device posture         Context stores
```

## Participants

-   **Subjects:** Users, services, bots.
    
-   **Relying Resources:** APIs, apps, datasets.
    
-   **PEPs:** API gateways, Envoy/Istio sidecars, application filters.
    
-   **PDP:** Policy server (e.g., OPA), receives attributes and returns decision/obligations.
    
-   **IdP / CA:** Provides user/service identity; issues tokens & certs.
    
-   **Device/Workload Posture Service:** EDR/MDM or workload attestation.
    
-   **KMS/PKI:** Rotates and protects keys/certs.
    
-   **Observability:** SIEM, SOAR, UEBA.
    

## Collaboration

1.  **Authenticate:** Subject obtains **strong identity** (MFA) and the workload establishes **mutual TLS** (service identity).
    
2.  **Collect context:** PEP gathers attributes—`sub`, `roles/scopes`, device posture, request risk, resource labels, tenant.
    
3.  **Decide:** PEP sends attributes to PDP; policy (ABAC + risk) returns **Permit/Deny** and **obligations** (e.g., mask fields, step-up MFA).
    
4.  **Enforce:** PEP allows/denies, applies rate limits or data filters; microsegmentation rules restrict east-west traffic.
    
5.  **Observe:** All decisions and signals logged to a tamper-evident logger.
    
6.  **Adapt:** Risk engines and detections feed policy updates (closed-loop).
    

## Consequences

**Benefits**

-   Minimizes lateral movement; **breach containment**.
    
-   Consistent policy across environments (cloud, on-prem, edge).
    
-   Fine-grained, auditable access with dynamic signals (risk-aware).
    
-   Works with legacy via gateways and with cloud-native via mesh.
    

**Liabilities**

-   Requires **policy engineering** and high-quality identity/posture data.
    
-   More components (IdP, PDP, mesh, PKI) → **operational complexity**.
    
-   Legacy protocols may need **proxies or adapters**.
    
-   Latency overhead from per-request evaluation (mitigate with caching).
    

## Implementation

### Ten ZTA Essentials (Checklist)

1.  **Strong identity:** OIDC with MFA for users; SPIFFE/SPIRE or certs for workloads.
    
2.  **mTLS everywhere:** Service-to-service authenticated encryption; rotate certs automatically.
    
3.  **Short-lived tokens:** 5–15 min access tokens; refresh with rotation and replay detection.
    
4.  **ABAC policies:** Central PDP with attributes (subject, device, resource, environment, risk).
    
5.  **Microsegmentation:** Per-service intents; deny-by-default; explicit allow policies.
    
6.  **Continuous verification:** Re-evaluate on context change (new IP, degraded device health).
    
7.  **Step-up authentication:** Trigger MFA/reauth for sensitive actions.
    
8.  **Least privilege:** Scopes/claims tied to precise resources; just-in-time elevation.
    
9.  **Telemetry + integrity:** Structured, privacy-preserving logging; HMAC/sign decisions.
    
10.  **Automated key & cert lifecycle:** ACME/SPIRE/KMS; measurable SLOs for rotation.
    

### Reference Policy (high-level ABAC)

```lua
permit if
  sub.authenticated
  and device.posture in {"healthy","attested"}
  and token.aud == "orders-api"
  and scope contains "orders:write"
  and resource.label.sensitivity <= "internal"
  and risk.score < 70
else deny
```

### Deployment Patterns

-   **Edge-first:** API gateway as PEP; PDP is OPA with bundle-distributed policies.
    
-   **Mesh-first:** Envoy/Istio (or Linkerd) sidecars enforce mTLS + RBAC/ABAC; OPA/Envoy ext\_authz for PDP.
    
-   **App-embedded:** Spring Security filter acting as PEP calling PDP; good for legacy or granular obligations.
    

---

## Sample Code (Java)

Below is a pragmatic **application-embedded PEP** for a Spring Boot API that:

-   Verifies **JWT** (user identity),
    
-   Checks for **mTLS client cert** (workload/device identity),
    
-   Calls a **PDP (OPA)** with attributes for a decision,
    
-   Enforces **deny-by-default** and supports **step-up MFA** obligation.
    

> **Dependencies (Gradle snippets)**

```gradle
dependencies {
  implementation 'org.springframework.boot:spring-boot-starter-web'
  implementation 'org.springframework.boot:spring-boot-starter-security'
  implementation 'com.nimbusds:nimbus-jose-jwt:9.37.3'
  implementation 'org.apache.httpcomponents.client5:httpclient5:5.3.1'
  implementation 'com.fasterxml.jackson.core:jackson-databind:2.17.1'
}
```

**SecurityConfig.java** — secure defaults, HTTPS required

```java
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.web.SecurityFilterChain;

@Configuration
class SecurityConfig {
  @Bean
  SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
    http
      .requiresChannel(c -> c.anyRequest().requiresSecure())
      .csrf(csrf -> csrf.disable()) // for pure API; otherwise enable with token
      .authorizeHttpRequests(auth -> auth.anyRequest().authenticated())
      .addFilterBefore(new ZeroTrustPepFilter(), org.springframework.security.web.authentication.AnonymousAuthenticationFilter.class);
    return http.build();
  }
}
```

**ZeroTrustPepFilter.java** — the PEP

```java
import jakarta.servlet.*;
import jakarta.servlet.http.*;
import java.io.IOException;
import java.security.cert.X509Certificate;
import java.time.Instant;
import java.util.*;
import com.nimbusds.jwt.SignedJWT;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.hc.client5.http.classic.methods.HttpPost;
import org.apache.hc.client5.http.impl.classic.HttpClients;
import org.apache.hc.core5.http.io.entity.StringEntity;

public class ZeroTrustPepFilter implements Filter {
  private static final ObjectMapper M = new ObjectMapper();

  @Override
  public void doFilter(ServletRequest req, ServletResponse res, FilterChain chain) throws IOException, ServletException {
    HttpServletRequest r = (HttpServletRequest) req;
    HttpServletResponse w = (HttpServletResponse) res;

    // 1) Extract identity (JWT) and workload/device (mTLS cert if present)
    String authz = r.getHeader("Authorization");
    if (authz == null || !authz.startsWith("Bearer ")) {
      deny(w, 401, "missing_token"); return;
    }
    String jwtString = authz.substring("Bearer ".length()).trim();

    Map<String, Object> userClaims;
    try {
      var jwt = SignedJWT.parse(jwtString);
      // NOTE: Configure JWKS verification (omitted here for brevity). Assume already verified by upstream gateway or another filter.
      userClaims = jwt.getJWTClaimsSet().getClaims();
      long now = Instant.now().getEpochSecond();
      if (jwt.getJWTClaimsSet().getExpirationTime().toInstant().getEpochSecond() < now - 30) {
        deny(w, 401, "token_expired"); return;
      }
    } catch (Exception e) {
      deny(w, 401, "bad_token"); return;
    }

    String subject = (String) userClaims.getOrDefault("sub", "unknown");
    List<String> aud = (List<String>) userClaims.getOrDefault("aud", List.of());
    String scope = (String) userClaims.getOrDefault("scope", "");

    // mTLS client certificate (optional but recommended for service/workload identity)
    String spiffe = null;
    X509Certificate[] chainCerts = (X509Certificate[]) r.getAttribute("jakarta.servlet.request.X509Certificate");
    if (chainCerts != null && chainCerts.length > 0) {
      var cert = chainCerts[0];
      var dn = cert.getSubjectX500Principal().getName();
      // Example extraction; with SPIFFE you'd parse SAN URI
      spiffe = dn;
    }

    // 2) Collect context attributes
    Map<String, Object> input = new HashMap<>();
    input.put("subject", Map.of("sub", subject, "scope", scope, "mfa", userClaims.getOrDefault("amr", List.of())));
    input.put("workload", Map.of("spiffe", spiffe));
    input.put("request", Map.of(
            "method", r.getMethod(),
            "path", r.getRequestURI(),
            "audience_ok", aud.contains("https://api.example.com"),
            "ip", r.getRemoteAddr()
    ));
    input.put("resource", Map.of(
            "label", Map.of("sensitivity", resourceSensitivity(r.getRequestURI()))
    ));
    input.put("env", Map.of("risk", Map.of("score", 42))); // placeholder from risk engine

    // 3) Ask PDP (OPA) for decision
    try (var http = HttpClients.createDefault()) {
      HttpPost post = new HttpPost("http://opa:8181/v1/data/zt/allow");
      post.setHeader("Content-Type", "application/json");
      String body = M.writeValueAsString(Map.of("input", input));
      post.setEntity(new StringEntity(body));
      var resp = http.execute(post);
      var respBody = new String(resp.getEntity().getContent().readAllBytes());
      Map<String, Object> decision = M.readValue(respBody, Map.class);
      boolean allow = (Boolean) ((Map<String, Object>) decision.getOrDefault("result", Map.of())).getOrDefault("allow", false);
      Map<String, Object> obligations = (Map<String, Object>) ((Map<String, Object>) decision.getOrDefault("result", Map.of())).getOrDefault("obligations", Map.of());

      if (!allow) { deny(w, 403, "policy_denied"); return; }
      if ("step_up_mfa".equals(obligations.getOrDefault("action", ""))) {
        deny(w, 401, "mfa_required"); return;
      }

      // 4) Proceed—optionally attach sanitized principal attributes for app logic
      r.setAttribute("zt.principal", Map.of("sub", subject, "scope", scope, "spiffe", spiffe));
      chain.doFilter(req, res);
    } catch (Exception e) {
      deny(w, 503, "pdp_unavailable"); // fail-closed at the edge; inside app you might fail-open by policy
    }
  }

  private String resourceSensitivity(String path) {
    if (path.startsWith("/admin") || path.startsWith("/payments")) return "confidential";
    return "internal";
  }

  private void deny(HttpServletResponse w, int status, String code) throws IOException {
    w.setStatus(status);
    w.setContentType("application/json");
    w.getWriter().write("{\"error\":\"" + code + "\"}");
  }
}
```

**Example Rego policy (PDP concept)** — not Java, but illustrates the decision model the filter expects:

```rego
package zt

default allow = false
default obligations = {}

allow {
  input.request.audience_ok
  some method
  method := input.request.method
  method != "DELETE"  # example
  input.resource.label.sensitivity == "internal"
  input.env.risk.score < 70
  contains(input.subject.scope, "orders:read")
}

# Step-up for sensitive paths
allow {
  input.resource.label.sensitivity == "confidential"
  contains(input.subject.scope, "payments:write")
  input.env.risk.score < 40
  mfa_present
}
mfa_present { input.subject.mfa[_] == "mfa" }

obligations = {"action": "step_up_mfa"} {
  input.resource.label.sensitivity == "confidential"
  not mfa_present
}
```

> **Notes**

-   In production, place a **gateway/mesh PEP** in front of apps; app-level PEPs add defense-in-depth.

-   Verify JWT signature via **JWKS**, and enforce **mTLS** at the ingress/mesh.

-   Cache PDP decisions briefly (e.g., 10–60s) with **invalidation** on risk changes.


---

## Known Uses

-   **Google BeyondCorp**\-style access for internal applications.

-   **Service meshes** (Istio/Envoy) with mTLS + authorization policies and external PDPs.

-   **Cloud provider control planes** enforcing short-lived credentials and per-request evaluation.

-   **Enterprise VPN replacements** using identity-aware proxies and device posture checks.

-   **Financial & healthcare** orgs adopting ABAC with step-up auth and microsegmentation.


## Related Patterns

-   **Token Based Authentication** (short-lived tokens; PoP/mTLS binding)

-   **Secure Session Management** (where sessions remain, still require continuous checks)

-   **Secrets Manager** (protect keys, certs, JWKS signing)

-   **Tamper Detection** & **Secure Logger** (integrity and auditability of decisions)

-   **Policy as Code** (OPA/Rego), **Microsegmentation**, **mTLS Everywhere**, **Device Posture Assessment**


---

**Implementation Tips (Hardening)**

-   Enforce **deny by default**; explicitly enumerate allowed paths/resources.

-   Prefer **DPoP or mTLS-bound tokens** for browser and service clients in high-risk contexts.

-   Maintain **authoritative inventory** (people, services, devices, data) with labels feeding policy.

-   Automate **certificate issuance/rotation** (SPIRE/ACME) and **key rotation** (KMS).

-   Validate **time** (NTP) and include **jti** + **nonce** where applicable to prevent replay.

-   Design for **graceful degradation**: cache allow decisions with short TTL; fail-closed at the edge.

-   Test with policy unit tests and **dynamic access reviews**; record **who/what/why** for every permit.
