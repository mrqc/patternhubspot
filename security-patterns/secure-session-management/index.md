# Secure Session Management — Security Pattern

## Pattern Name and Classification

-   **Name:** Secure Session Management
    
-   **Classification:** Security / Authentication & State / Cross-cutting (Web & Service)
    

## Intent

Manage authenticated user state safely across requests by issuing, transporting, storing, rotating, and invalidating **server-side sessions** (or session identifiers) to resist theft, fixation, replay, and abuse—while preserving usability and performance.

## Also Known As

-   Session Hardening
    
-   Hardened HttpSession
    
-   Secure Web Session
    

## Motivation (Forces)

Systems with login need continuity of identity between requests. However:

-   **Confidentiality:** Session IDs must not leak (referrer, logs, URLs, third-party scripts).
    
-   **Integrity:** Attackers try **fixation** (set ID before login) or **tamper** with client-stored state.
    
-   **Availability/Performance:** Timeout too aggressively → friction; too lax → risk.
    
-   **Multi-device & concurrency:** Limit parallel sessions vs. user convenience.
    
-   **Federation/microservices:** Sessions across multiple apps behind gateways.
    
-   **Regulation & privacy:** Minimize PII in session; support revocation & retention policies.  
    This pattern balances these forces with **opaque, unpredictable IDs**, **rotation on privilege change**, **short lifetimes + idle timeouts**, **HttpOnly/Secure/SameSite cookies**, **server-side storage**, **revocation lists**, and **instrumentation**.
    

## Applicability

Use Secure Session Management when:

-   A web or API workload stores authenticated state server-side.
    
-   You need SSO bridging to apps that still expect server sessions.
    
-   You must comply with PCI DSS, GDPR, ISO 27001, HIPAA session controls.
    
-   You need **fine-grained invalidation** (logout everywhere, admin force-logout).
    
-   You want stronger protections than pure bearer tokens in browsers.
    

## Structure

-   **Client (Browser/App)** ↔ **Reverse Proxy / WAF** ↔ **Application**
    
    -   **Session Manager:** create/renew/invalidate; concurrency limits.
        
    -   **ID Generator:** CSPRNG for opaque, high-entropy IDs.
        
    -   **Cookie Issuer:** sets `Secure`, `HttpOnly`, `SameSite`, `Path`, `Domain`.
        
    -   **Store:** in-memory / Redis / database; optional **envelope encryption**.
        
    -   **Rotation Policy:** on login, privilege elevation, sensitive actions.
        
    -   **Idle/Absolute Timeout Controller**.
        
    -   **CSRF Defense:** per-session **synchronizer token** or SameSite policy.
        
    -   **Device/Client Fingerprint (optional, privacy-aware)**.
        
    -   **Session Events/Audit:** creation, rotation, invalidation, anomalies.
        

## Participants

-   **User / Client** — Sends cookie on each request.
    
-   **SessionManager** — Issues and validates sessions, enforces policies.
    
-   **Store** — Holds server-side session attributes and metadata.
    
-   **Crypto/KMS** — (Optional) encrypts attributes at rest.
    
-   **IdGenerator** — CSPRNG for IDs.
    
-   **Policy Engine** — Timeouts, rotation, concurrency, IP/rate rules.
    
-   **Security Middleware** — CSRF filter, header hardening, WAF.
    
-   **Audit Logger** — Records lifecycle events (without leaking secrets).
    

## Collaboration

1.  **Authenticate** → SessionManager creates server-side record with minimal attributes; generates **opaque ID**.
    
2.  **Rotate on login** to prevent fixation; set cookie with `Secure`+`HttpOnly`+`SameSite`.
    
3.  **Each request**: Session ID validated → load attributes → check timeouts, IP/UA constraints → refresh idle timer or rotate if needed.
    
4.  **Privilege change** (e.g., 2FA success, role elevation) → **rotate** session.
    
5.  **Logout / Admin revoke** → invalidate server record; cookie cleared.
    
6.  **Concurrency controls** enforce max active sessions per account; oldest sessions evicted if policy dictates.
    
7.  **Audit** logs lifecycle events with correlation IDs.
    

## Consequences

**Benefits**

-   Resists **session fixation, theft, replay**; stronger than client-side bearer tokens in browsers.
    
-   Centralized **revocation & visibility**; per-user force logout.
    
-   Clear policy knobs (idle/absolute timeouts, rotation, concurrency).
    

**Liabilities**

-   Requires **sticky sessions** or distributed store.
    
-   Rotation and strict cookie flags may affect **legacy cross-site embeds**.
    
-   State on server increases **memory/cost**; scaling needs Redis/DB.
    
-   Misconfiguration (e.g., `SameSite=None` without `Secure`) can re-expose risk.
    

## Implementation

### Core Rules (Checklist)

-   **IDs:** 128+ bits entropy from CSPRNG; **opaque** (no user data).
    
-   **Cookies:** `Secure`, `HttpOnly`, **`SameSite=Lax`** (default) or `Strict` for very sensitive flows; use `None` only when truly cross-site and **always with `Secure`**.
    
-   **Rotation:** on login, on privilege change, and periodically (e.g., every 15–30 min of continuous use).
    
-   **Timeouts:** **Idle** (e.g., 15–30 min) and **Absolute** (e.g., 8–12 h; shorter for admin).
    
-   **Store:** server-side (Redis/DB); **do not** store secrets/credentials; keep minimal claims/IDs and look up details as needed.
    
-   **Fixation defense:** **invalidate pre-auth session** and issue a new ID post-auth.
    
-   **CSRF:** enable framework CSRF or synchronizer token; pair with `SameSite`.
    
-   **Transport:** enforce HTTPS/mTLS; HSTS.
    
-   **Concurrency:** limit sessions per user (e.g., 3), with administrative override.
    
-   **Logout:** server-side invalidate + client cookie delete; support “logout all devices.”
    
-   **Audit:** creation/rotation/invalidation with trace IDs (no PII).
    
-   **Regeneration on error:** if suspicious activity detected (IP/ASN change), optionally challenge (re-auth, step-up).
    
-   **Distributed deployments:** use **Spring Session / Redis** or similar; avoid in-JVM only.
    

### Data Model (example)

```pgsql
session_id (opaque, key) | user_id | created_at | last_seen | absolute_expiry | ip_hint | ua_hash | attributes (JSON) | rotated_from | status
```

### Operational Guidance

-   **Key Rotation:** if encrypting attributes, rotate DEKs via KMS; store key IDs with record.
    
-   **Rate Limits:** per account/IP to slow brute force on sessions.
    
-   **Monitoring:** alert on unusual spikes of session creation or invalidation, or many rotations from one IP.
    
-   **Blue/Green:** ensure both versions can read existing session format during deploys.
    

## Sample Code (Java)

Below are two pragmatic setups: **(A) Spring Boot 3 / Spring Security 6 + Spring Session (Redis)** and **(B) Plain Servlet filter** for essentials.

### A) Spring Security + Spring Session (Redis)

**Gradle (snippets)**

```gradle
dependencies {
  implementation 'org.springframework.boot:spring-boot-starter-web'
  implementation 'org.springframework.boot:spring-boot-starter-security'
  implementation 'org.springframework.session:spring-session-data-redis'
  implementation 'org.springframework.boot:spring-boot-starter-data-redis'
}
```

**application.yml**

```yaml
server:
  servlet:
    session:
      timeout: 20m     # idle timeout
spring:
  session:
    store-type: redis
    redis:
      namespace: app:sess
  redis:
    host: localhost
    port: 6379
# If behind TLS-terminating proxy, ensure X-Forwarded-* handled by server.forward-headers-strategy=framework
```

**SecurityConfig.java**

```java
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.session.ChangeSessionIdAuthenticationStrategy;
import org.springframework.security.web.csrf.CookieCsrfTokenRepository;
import org.springframework.security.web.session.HttpSessionEventPublisher;
import org.springframework.security.web.session.SessionManagementFilter;
import org.springframework.session.security.web.authentication.SpringSessionBackedSessionRegistry;
import org.springframework.session.data.redis.RedisIndexedSessionRepository;

@Configuration
public class SecurityConfig {

    // Rotates session ID on successful authentication (fixation defense)
    @Bean
    SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
          .requiresChannel(c -> c.anyRequest().requiresSecure())
          .headers(h -> h
              .httpStrictTransportSecurity(hsts -> hsts.includeSubDomains(true).preload(true))
              .contentSecurityPolicy(csp -> csp.policyDirectives("default-src 'self'"))
          )
          .csrf(csrf -> csrf
              .csrfTokenRepository(CookieCsrfTokenRepository.withHttpOnlyFalse()) // token readable by JS if SPA needs to send it
          )
          .sessionManagement(sm -> sm
              .sessionFixation(sf -> sf.changeSessionId())
              .maximumSessions(3) // limit concurrent logins
              .maxSessionsPreventsLogin(false)
          )
          .logout(l -> l
              .invalidateHttpSession(true)
              .deleteCookies("SESSION")
          )
          .authorizeHttpRequests(auth -> auth
              .requestMatchers("/login", "/health").permitAll()
              .anyRequest().authenticated()
          )
          .formLogin(Customizer.withDefaults());

        return http.build();
    }

    // Spring Session registry enables concurrency control across cluster
    @Bean
    SpringSessionBackedSessionRegistry<?> sessionRegistry(RedisIndexedSessionRepository repo) {
        return new SpringSessionBackedSessionRegistry<>(repo);
    }

    // Publishes session lifecycle events (create/destroy) for auditing/concurrency
    @Bean
    public HttpSessionEventPublisher httpSessionEventPublisher() {
        return new HttpSessionEventPublisher();
    }
}
```

**Cookie hardening (Spring Session)**

```java
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.session.web.http.CookieSerializer;
import org.springframework.session.web.http.DefaultCookieSerializer;

@Configuration
class CookieConfig {
    @Bean
    CookieSerializer cookieSerializer() {
        DefaultCookieSerializer s = new DefaultCookieSerializer();
        s.setCookieName("SESSION");         // short, generic
        s.setUseHttpOnlyCookie(true);
        s.setUseSecureCookie(true);
        s.setSameSite("Lax");               // use "Strict" for highly sensitive apps; "None" only if truly cross-site
        s.setCookiePath("/");
        // s.setDomainNamePattern("^.+?\\.(example\\.com)$"); // if sharing across subdomains
        return s;
    }
}
```

**Session Rotation on Privilege Elevation (e.g., after 2FA)**

```java
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.context.HttpSessionSecurityContextRepository;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

// After successful step-up auth:
public void rotateSession(HttpServletRequest req, HttpServletResponse res) {
    req.changeSessionId(); // forces new ID, preserves attributes
    // Optionally: tighten absolute expiry by marking a timestamp attribute
    req.getSession().setAttribute("elevated_at", System.currentTimeMillis());
    // Persist updated security context explicitly if needed
    new HttpSessionSecurityContextRepository()
        .saveContext(SecurityContextHolder.getContext(), req, res);
}
```

**Programmatic “Logout All Devices”**

```java
import org.springframework.session.FindByIndexNameSessionRepository;
import org.springframework.session.Session;

public class LogoutAllDevicesService<S extends Session> {
    private final FindByIndexNameSessionRepository<S> repo;
    public LogoutAllDevicesService(FindByIndexNameSessionRepository<S> repo) { this.repo = repo; }

    public void revokeAllForUser(String principalName) {
        repo.findByPrincipalName(principalName).values()
            .forEach(s -> repo.deleteById(s.getId()));
    }
}
```

### B) Plain Servlet Filter Essentials (no framework)

```java
import jakarta.servlet.*;
import jakarta.servlet.http.*;
import java.io.IOException;
import java.security.SecureRandom;
import java.util.Base64;

public class SecureSessionFilter implements Filter {
    private static final SecureRandom RNG = new SecureRandom();

    @Override public void doFilter(ServletRequest req, ServletResponse res, FilterChain chain)
            throws IOException, ServletException {
        HttpServletRequest r = (HttpServletRequest) req;
        HttpServletResponse w = (HttpServletResponse) res;

        // Enforce HTTPS only
        if (!r.isSecure()) { w.sendError(400, "HTTPS required"); return; }

        HttpSession session = r.getSession(false);
        if (session == null) {
            // Create minimal pre-auth session if absolutely needed
            session = r.getSession(true);
            session.setMaxInactiveInterval(20 * 60); // 20 minutes
        }

        // Harden cookie on every response
        addCookieFlags(r, w);

        chain.doFilter(req, res);
    }

    // Rotate after login (call this when auth succeeds)
    public static void onSuccessfulAuthentication(HttpServletRequest r) {
        r.changeSessionId(); // prevents fixation
        HttpSession s = r.getSession(false);
        if (s != null) {
            s.setAttribute("auth_time", System.currentTimeMillis());
        }
    }

    private void addCookieFlags(HttpServletRequest r, HttpServletResponse w) {
        for (Cookie c : r.getCookies() == null ? new Cookie[0] : r.getCookies()) {
            if ("JSESSIONID".equals(c.getName())) {
                c.setHttpOnly(true);
                c.setSecure(true);
                c.setPath("/");
                c.setAttribute("SameSite", "Lax"); // Servlet API lacks native setter pre-6.0; attribute works on modern containers
                w.addCookie(c);
            }
        }
    }

    // Example high-entropy ID (if you implement your own session id scheme—usually let container do it)
    public static String newOpaqueId() {
        byte[] b = new byte[32]; RNG.nextBytes(b);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(b);
    }
}
```

## Known Uses

-   Enterprise web apps using **Spring Session + Redis** for clustered session state with **session fixation protection** and **SameSite** cookies.

-   Banking and healthcare portals with **short idle + absolute timeouts** and **step-up rotation** for high-risk operations.

-   SaaS admin consoles enforcing **max concurrent sessions** with “logout all devices.”


## Related Patterns

-   **Secure Logger** (audit session lifecycle events)

-   **Refresh Token** (for API/OAuth flows; complements browser session for SPA)

-   **CSRF Token / SameSite Cookies** (request forgery defenses)

-   **Secrets Manager** (protects encryption keys if encrypting attributes)

-   **Secure Audit Trail** (immutability of auth/session events)

-   **Back-Channel Logout / Token Revocation** (in federated SSO)


---

**Production Hardening Notes**

-   Put the app behind **TLS-terminating proxy** with HSTS and secure cookie forwarding.

-   For SPAs: prefer **SameSite=Lax** and use **CSRF token**; avoid `None` unless truly cross-site.

-   Store only **IDs & minimal claims**; fetch fresh authorities server-side.

-   Detect anomalies: rapid rotations, many sessions per IP, UA changes.

-   Test flows: login, rotation, timeout, logout, revoke-all, remember-me (if used, use **hashed persistent tokens**, short TTL).
