# Authentication — Security Pattern

## Pattern Name and Classification

**Name:** Authentication  
**Classification:** Security / Identity & Access Management (IAM) — *Proving “who” a principal is before authorization*

---

## Intent

Reliably **verify the identity** of a principal (user, service, device) before granting access to protected resources, using one or more factors and secure protocols; produce an **authenticated session or token** that downstream components can trust.

---

## Also Known As

-   Login / Sign-in
    
-   Principal Verification
    
-   Identity Proofing (broader lifecycle)
    
-   Primary Auth (precedes Authorization)
    

---

## Motivation (Forces)

-   **Confidentiality & integrity:** Only legitimate principals should access/modify data.
    
-   **Usability vs. security:** Simplicity (passwords, magic links) vs. stronger factors (MFA, passkeys).
    
-   **Federation & portability:** Avoid password silos; allow SSO (SAML/OIDC).
    
-   **Lifecycle:** Enrollment, recovery, rotation, revocation must be safe.
    
-   **Attack resistance:** Phishing, credential stuffing, replay, MITM, device theft.
    
-   **Stateless scale:** Tokens must be verifiable at scale, ideally **without** central lookups.
    

---

## Applicability

Use this pattern when:

-   Any resource requires **identity** before policy decisions.
    
-   Services need **mutual authentication** (mTLS, client credentials).
    
-   You issue **bearer tokens** (JWT) or **sessions** for APIs/UI.
    

Avoid or adapt when:

-   Access is intentionally **anonymous** (public content).
    
-   Trust is derived from **physical possession** only (e.g., kiosk) — still consider device auth.
    
-   Regulatory constraints demand **phishing-resistant** factors (prefer **WebAuthn/passkeys** or CAC/PIV).
    

---

## Structure

-   **Authenticator(s):** Password (with strong hashing), OTP/TOTP, WebAuthn/passkey, X.509 (mTLS), OAuth client creds.
    
-   **Identity Store:** User directory (DB/IdP) with salted/peppered password hashes and public keys.
    
-   **Token Service:** Issues sessions (cookies) or tokens (JWT/Opaque) with **audience**, **issuer**, **exp**, **iat**, **sub**.
    
-   **Verifier / Middleware:** Validates tokens or sessions on each request (sig check, expiry, revocation).
    
-   **Risk Engine (optional):** Contextual signals (IP, device, geo, velocity).
    
-   **Audit & Telemetry:** Auth events, anomalies, lockouts.
    

---

## Participants

-   **Principal:** Human user, service account, or device.
    
-   **Relying Party (RP) / Application:** Initiates auth, consumes identity.
    
-   **Identity Provider (IdP):** Local or federated (OIDC/SAML) authority that authenticates and issues tokens.
    
-   **Credential/Key Manager:** Stores password hashes, WebAuthn public keys, client secrets.
    
-   **Verifier/Gateway:** Enforces authentication on protected endpoints.
    

---

## Collaboration

1.  **Credential presentation:** Principal proves identity (password+MFA, WebAuthn challenge, client cert, etc.).
    
2.  **Verification:** RP/IdP validates proof (hash compare, signature verification, cert chain).
    
3.  **Token/session issuance:** Short-lived signed JWT or httpOnly secure cookie; bind to device/context when possible.
    
4.  **Request processing:** Middleware verifies token each call (signature, `aud`, `exp`) and attaches identity (`sub`, claims).
    
5.  **Refresh/rotation:** Long-lived refresh tokens or re-auth with step-up when risk increases.
    
6.  **Logout/revocation:** Invalidate refresh tokens or server session; optionally maintain a revocation list.
    

---

## Consequences

**Benefits**

-   Clear separation of **authentication** (who) from **authorization** (what).
    
-   Scales via **stateless tokens**; supports SSO/federation.
    
-   Stronger factors drastically lower account takeover risk.
    

**Liabilities**

-   **Bearer tokens** are transferable if exfiltrated — protect at rest and in transit.
    
-   Passwords demand **sophisticated storage and defense** (hashing, breach monitoring).
    
-   Token **revocation** is harder with non-opaque JWTs (use short TTL + rotation).
    
-   Usability friction if MFA is too aggressive (use risk-based, remember device).
    

---

## Implementation

### Key Decisions

-   **Credential types:**
    
    -   Users: **Passkeys (WebAuthn)** → strongest, phishing-resistant.
        
    -   Transitional: Password **\+ TOTP** (or push/FIDO2).
        
    -   Services: **mTLS** or **OAuth2 Client Credentials** (signed JWTs).
        
-   **Token model:**
    
    -   **JWT** (RS256/EdDSA) with **short TTL (5–15 min)** + **refresh token rotation**, or
        
    -   **Opaque** tokens with server session store (simpler revocation, more I/O).
        
-   **Session hardening:** httpOnly, Secure, SameSite cookies; **CSRF** protection; IP/device binding optional.
    
-   **Password storage:** **Argon2id** (preferred) or **bcrypt** with unique salt; optional pepper in HSM/KMS.
    
-   **MFA:** TOTP, WebAuthn, or push. Enforce step-up for sensitive actions.
    
-   **Account protection:** lockouts (smart, temporary), **breached-password** checks, **rate limits** and **CAPTCHA** after failures.
    

### Anti-Patterns

-   Storing plaintext or reversible passwords.
    
-   Long-lived bearer JWTs (days) without rotation.
    
-   Accepting tokens without verifying **audience/issuer** and **exp**.
    
-   Rolling your own crypto/signing when libraries exist.
    
-   Sending tokens in URLs (logs/referrers leak them).
    

---

## Sample Code (Java, Spring Boot)

**Scenario:** Username/password (+ optional TOTP) → issue **short-lived JWT**; middleware validates per request.  
*Notes:* Uses BCrypt for brevity (swap to Argon2), HS256 for demo (use **RS256/EdDSA** with key rotation in production).

> Gradle deps (snippet)

```gradle
implementation 'org.springframework.boot:spring-boot-starter-web'
implementation 'org.springframework.boot:spring-boot-starter-security'
implementation 'io.jsonwebtoken:jjwt-api:0.11.5'
runtimeOnly   'io.jsonwebtoken:jjwt-impl:0.11.5'
runtimeOnly   'io.jsonwebtoken:jjwt-jackson:0.11.5'
implementation 'org.springframework.boot:spring-boot-starter-data-jpa'
runtimeOnly   'org.postgresql:postgresql'
```

```java
// domain/UserAccount.java
package com.example.auth.domain;
import javax.persistence.*;
@Entity
public class UserAccount {
  @Id @GeneratedValue(strategy = GenerationType.IDENTITY) Long id;
  @Column(unique = true, nullable = false) String username;
  @Column(nullable = false) String passwordHash;            // BCrypt/Argon2id
  String totpSecret;                                        // null if MFA not enrolled
  boolean locked; boolean enabled = true;
  // getters/setters omitted
}
```

```java
// security/PasswordConfig.java
package com.example.auth.security;
import org.springframework.context.annotation.Bean; import org.springframework.context.annotation.Configuration;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder; import org.springframework.security.crypto.password.PasswordEncoder;
@Configuration public class PasswordConfig {
  @Bean public PasswordEncoder passwordEncoder() { return new BCryptPasswordEncoder(12); } // prefer Argon2 in prod
}
```

```java
// security/JwtService.java
package com.example.auth.security;
import io.jsonwebtoken.*; import io.jsonwebtoken.security.Keys;
import java.security.Key; import java.time.Instant; import java.util.Date; import java.util.Map;
public class JwtService {
  private final Key key = Keys.hmacShaKeyFor("replace-with-256-bit-secret-really-long...".getBytes());
  private static final String ISS = "example-auth";
  public String issue(String subject, Map<String,Object> claims, long ttlSeconds) {
    Instant now = Instant.now();
    return Jwts.builder()
        .setIssuer(ISS).setSubject(subject).addClaims(claims)
        .setIssuedAt(Date.from(now))
        .setExpiration(Date.from(now.plusSeconds(ttlSeconds)))
        .signWith(key, SignatureAlgorithm.HS256).compact();
  }
  public Jws<Claims> verify(String jwt) {
    return Jwts.parserBuilder().requireIssuer(ISS).setSigningKey(key).build().parseClaimsJws(jwt);
  }
}
```

```java
// security/JwtAuthFilter.java
package com.example.auth.security;
import org.springframework.web.filter.OncePerRequestFilter;
import javax.servlet.*; import javax.servlet.http.*; import java.io.IOException;
public class JwtAuthFilter extends OncePerRequestFilter {
  private final JwtService jwt;
  public JwtAuthFilter(JwtService jwt){ this.jwt = jwt; }
  @Override protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain)
      throws ServletException, IOException {
    String h = req.getHeader("Authorization");
    if (h != null && h.startsWith("Bearer ")) {
      try {
        var jws = jwt.verify(h.substring(7));
        req.setAttribute("sub", jws.getBody().getSubject());
        req.setAttribute("roles", jws.getBody().get("roles"));
      } catch (Exception e) { res.sendError(401, "Invalid/expired token"); return; }
    }
    chain.doFilter(req, res);
  }
}
```

```java
// web/AuthController.java
package com.example.auth.web;
import com.example.auth.domain.UserAccount;
import com.example.auth.repo.UserRepo;
import com.example.auth.security.JwtService;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.web.bind.annotation.*;
import java.util.Map;
@RestController @RequestMapping("/auth")
public class AuthController {
  private final UserRepo users; private final PasswordEncoder enc; private final JwtService jwt; private final Totp totp;
  public AuthController(UserRepo users, PasswordEncoder enc, JwtService jwt, Totp totp) {
    this.users = users; this.enc = enc; this.jwt = jwt; this.totp = totp;
  }

  public static record LoginRequest(String username, String password, String otp) {}
  public static record TokenResponse(String accessToken) {}

  @PostMapping("/login")
  public TokenResponse login(@RequestBody LoginRequest req) {
    UserAccount u = users.findByUsername(req.username()).orElseThrow(() -> new Unauthorized("bad creds"));
    if (!u.enabled || u.locked || !enc.matches(req.password(), u.passwordHash)) throw new Unauthorized("bad creds");
    if (u.totpSecret != null) {
      if (req.otp() == null || !totp.verify(u.totpSecret, req.otp())) throw new Unauthorized("otp required/invalid");
    }
    String token = jwt.issue(u.username, Map.of("roles", "USER"), 900); // 15m
    return new TokenResponse(token);
  }

  @ResponseStatus(code = org.springframework.http.HttpStatus.UNAUTHORIZED)
  private static class Unauthorized extends RuntimeException { public Unauthorized(String m){super(m);} }
}
```

```java
// security/Totp.java  (RFC 6238 compatible; use a library in prod)
package com.example.auth.security;
import javax.crypto.Mac; import javax.crypto.spec.SecretKeySpec; import java.time.Instant; import java.util.Base64;
public class Totp {
  public boolean verify(String base32Secret, String code) {
    long now = Instant.now().getEpochSecond() / 30; // 30s window
    for (long t : new long[]{now-1, now, now+1}) { // small drift tolerance
      if (code.equals(generate(base32Secret, t))) return true;
    }
    return false;
  }
  public String generate(String base32Secret, long timeStep) {
    byte[] key = Base64.getDecoder().decode(base32Secret); // demo assumes base64; usually base32
    try {
      Mac mac = Mac.getInstance("HmacSHA1");
      mac.init(new SecretKeySpec(key, "HmacSHA1"));
      byte[] msg = new byte[8];
      for (int i=7;i>=0;i--){ msg[i] = (byte)(timeStep & 0xff); timeStep >>= 8; }
      byte[] h = mac.doFinal(msg);
      int o = h[h.length-1] & 0xf;
      int bin = ((h[o] & 0x7f) << 24) | ((h[o+1] & 0xff) << 16) | ((h[o+2] & 0xff) << 8) | (h[o+3] & 0xff);
      int otp = bin % 1_000_000;
      return String.format("%06d", otp);
    } catch (Exception e) { throw new RuntimeException(e); }
  }
}
```

```java
// security/SecurityConfig.java
package com.example.auth.security;
import org.springframework.context.annotation.*; import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.web.SecurityFilterChain; import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
@Configuration public class SecurityConfig {
  @Bean JwtService jwtService(){ return new JwtService(); }
  @Bean Totp totp(){ return new Totp(); }
  @Bean SecurityFilterChain filterChain(HttpSecurity http, JwtService jwt) throws Exception {
    http.csrf().disable()
        .authorizeHttpRequests(auth -> auth
            .antMatchers("/auth/**").permitAll()
            .anyRequest().authenticated())
        .addFilterBefore(new JwtAuthFilter(jwt), UsernamePasswordAuthenticationFilter.class);
    return http.build();
  }
}
```

```java
// repo/UserRepo.java
package com.example.auth.repo;
import com.example.auth.domain.UserAccount;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.Optional;
public interface UserRepo extends JpaRepository<UserAccount, Long> {
  Optional<UserAccount> findByUsername(String username);
}
```

**Hardening & Production Notes**

-   Prefer **Argon2id** (`spring-security-crypto` or libsodium) with memory cost tuned.
    
-   Use **asymmetric JWT** (RS256/EdDSA) with **kid** and a **JWKS** endpoint for rotation; validate `aud`, `iss`, `exp`, `nbf`.
    
-   For browsers, favor **httpOnly, Secure, SameSite** cookies; include **CSRF** protection for state-changing requests.
    
-   Implement **refresh token rotation** and revoke on reuse; store refresh tokens **server-side** (or DPoP/MTLS-bound).
    
-   Support **WebAuthn/passkeys** for phishing-resistant primary auth (FIDO2).
    
-   Add **rate limits**, smart lockouts, breach password checks (HIBP), and **IP/ASN risk heuristics**.
    
-   Emit **auth events** (success/failure, reason, IP, UA) to SIEM; never log credentials or tokens.
    
-   For service-to-service, use **mTLS** or **OAuth2 client credentials** instead of user flows.
    

---

## Known Uses

-   Web & mobile apps with password + TOTP / passkeys and JWT or session cookies.
    
-   Enterprise SSO via **OIDC/SAML** to central IdPs (Azure AD, Okta, Keycloak).
    
-   API-only backends issuing **short-lived JWTs** for SPA/native clients.
    
-   Internal microservices with **mTLS** and SPIFFE/SPIRE identities.
    

---

## Related Patterns

-   **Authorization (RBAC/ABAC/OPA):** decisions after identity is established.
    
-   **API Key Management:** non-interactive service identification (coarser than user auth).
    
-   **mTLS:** mutual endpoint authentication with X.509.
    
-   **Session Management & CSRF Protection:** for cookie-based web sessions.
    
-   **Rate Limiting / Account Lockout:** mitigate brute force.
    
-   **Credential Recovery & Rotation:** lifecycle management (email/SMS risks; prefer passkeys).
    

---

## Implementation Checklist

-   Choose primary factor(s): **passkeys** preferred; else password + **MFA**.
    
-   Store credentials with **Argon2id/bcrypt** + unique salts; optionally **pepper** in KMS/HSM.
    
-   Define token model: **short-lived JWT** + **refresh rotation** or **opaque sessions**.
    
-   Verify tokens on every request (sig, `aud`, `iss`, `exp`, `nbf`) and **enforce HTTPS**.
    
-   Protect sessions: **httpOnly/Secure/SameSite**, CSRF tokens, same-device binding if feasible.
    
-   Add **rate limits**, **lockouts**, breach password checks; instrument auth telemetry.
    
-   Implement **account lifecycle** (enroll MFA, recovery, disable, delete); log and alert on anomalies.
    
-   Regularly **rotate keys**, test **revocation**, and run **phishing/resilience** exercises.

