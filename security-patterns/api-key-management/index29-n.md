# API Key Management — Security Pattern

## Pattern Name and Classification

**Name:** API Key Management  
**Classification:** Security / Access Control / Secrets & Identity (Non-interactive client authentication & authorization)

---

## Intent

Provide a **simple, non-interactive credential** that identifies and authorizes a calling system, with **safe issuance, storage, transmission, rotation, revocation, scoping, monitoring, and abuse prevention** across the API lifecycle.

---

## Also Known As

-   Service Token / Access Token (non-OAuth)
    
-   Shared Secret Key
    
-   Machine-to-Machine Key
    
-   Static Token (when not rotated)
    

---

## Motivation (Forces)

-   **Ease-of-use:** Many server-to-server clients don’t support full OAuth/OIDC flows.
    
-   **Least privilege:** Keys must be **scoped** (permissions, rate limits, environment) and **time-bound**.
    
-   **Breach impact:** Stolen keys are valid until detected → need **prefixing, audit trails, alerts, rotation, and kill switches**.
    
-   **Storage risk:** Servers must **never** store plaintext keys; use **hashed/peppered** representations.
    
-   **Operational load:** Keys need **self-service issuance**, **expiry/rotation reminders**, **visibility** (usage analytics), and **automation**.
    
-   **Compatibility:** Must work over **TLS**, behind proxies, and with multi-tenant routing.
    

---

## Applicability

Use API Keys when:

-   You need **programmatic** access from services, scripts, or IoT without user interaction.
    
-   **OAuth client credentials** are overkill or unavailable.
    
-   You can restrict access via **scopes**, **IP allow-lists**, **rate limits**, and **time-boxed** validity.
    

Avoid or augment when:

-   You need **user identity** and consent → use OAuth/OIDC.
    
-   You require **fine-grained, dynamic authorization** → consider JWTs with claims or mTLS.
    
-   You must **strongly bind** client to hardware/network → use **mTLS** or device attestation.
    

---

## Structure

-   **Key Issuer / Portal:** Generates keys, shows **once**, stores only **hashed** material.
    
-   **Key Format:** `prefix_env_keyId.secret` (e.g., `ak_live_01H….<base64url>`), where only **keyId** is stored in clear.
    
-   **Secure Store:** DB with **hash(pepper ⊕ secret)**, metadata (owner, scopes, quotas, expiry, status).
    
-   **Validator (Gateway/Middleware):** Parses header, looks up **keyId**, constant-time verifies hash, enforces **policy**.
    
-   **Policy Engine:** Scopes, **per-key rate limits**, IP rules, **time windows**, environment.
    
-   **Rotation/Revocation:** Dual-key overlap, **kill-switch**, and **audit logs**.
    
-   **Telemetry:** Usage counts, 4xx/5xx, geos, anomaly detection, leak signals.
    

---

## Participants

-   **Producer / Admin**: creates, rotates, revokes keys.
    
-   **Consumer (Client App)**: stores key securely and sends it over **TLS** in `Authorization: Api-Key <token>` or `X-API-Key`.
    
-   **API Gateway / Service Filter**: authenticates & authorizes key; applies rate limits.
    
-   **Key Directory / DB**: stores keyed records (`keyId`, `hash`, `owner`, `scopes`, `expiresAt`, `revoked`, quotas).
    
-   **Auditor**: reviews logs, alerts, and anomalies (e.g., new ASN/geo).
    

---

## Collaboration

1.  **Issuance:** Portal generates random **secret** (≥256 bits), returns **token** once; stores **hash + metadata**.
    
2.  **Request:** Client sends key in header over **TLS**.
    
3.  **Validation:** Service extracts **keyId**, fetches record, **constant-time** verifies hash(secret).
    
4.  **Authorization & Controls:** Enforce **scopes**, **quotas/rate limits**, **IP allow-list**, **expiry**, **environment**.
    
5.  **Rotation:** Issue secondary key; client cutover; revoke the old.
    
6.  **Revocation:** Immediate disable; purge caches; alerts fire.
    
7.  **Observability:** Emit metrics & logs for every decision.
    

---

## Consequences

**Benefits**

-   Simple **on the wire**, widely compatible.
    
-   Works offline (no token endpoint at call time).
    
-   Can be **scoped**, **time-limited**, and **rate-limited** per client.
    

**Liabilities**

-   **Static secret** risk if leaked; requires strong **rotation & monitoring**.
    
-   No inherent **user identity**; coarse-grained unless you add scopes.
    
-   **Client-side storage** is tricky (CI/CD, mobile, browser = unsafe).
    
-   Replayable within TTL (unless paired with **nonce/timestamp** signing or mTLS).
    

---

## Implementation

### Key Decisions

-   **Key format:** Include **prefix** (type/env), short **keyId**, and opaque **secret**. Example:  
    `ak_live_<base62 keyId>.<base64url secret 32B>`
    
-   **Storage:** Only keep **keyId** (clear) and **hash(secret + pepper)** using **HMAC-SHA-256/512** or **Argon2id/bcrypt**. Pepper is an env secret.
    
-   **Transport:** Always over **TLS**. Prefer `Authorization: Api-Key …`.
    
-   **Scope model:** CRUD/resource scopes, tenant bounds, environment (`live`/`test`).
    
-   **Quotas & rate limits:** Per key; optionally **burst + sustained**.
    
-   **Rotation:** Allow **two active keys** per principal. Warn before expiry, auto-revoke after grace.
    
-   **Revocation:** Hard kill, soft disable, reason code; propagate to caches.
    
-   **Defense-in-depth:** IP allow-lists, ASN/geofence, **request signing** (optional): `HMAC(keySecret, date + path + bodyHash)` with **timestamp** and **nonce**.
    
-   **Telemetry:** Per-key metrics, anomaly alerts (new IP/ASN/geo, unusual rate).
    

### Anti-Patterns

-   Storing **plaintext** keys or reversible encryption.
    
-   Using **predictable** secrets or UUIDv4 as the only “randomness”.
    
-   Accepting keys over **HTTP** or in **query strings**.
    
-   Never rotating keys; no **kill switch**.
    
-   Returning full key in logs/trace headers (only log **keyId**).
    

---

## Sample Code (Java, Spring Boot — in-memory demo)

Features:

-   Key generation (one-time display), **hash with pepper**.
    
-   `OncePerRequestFilter` verifies header, **constant-time** compare, checks **expiry/revoked/scopes**, and **rate limits** per key.
    
-   Simple in-memory store for brevity (replace with DB/KMS).
    

> Dependencies (typical):
> 
> -   `spring-boot-starter-web`
>     
> -   (optional for JSON) `com.fasterxml.jackson.core:jackson-databind`
>     

```java
// ApiKey.java
package com.example.apikey;

import java.time.Instant;
import java.util.Set;

public record ApiKey(
    String keyId,              // public id
    byte[] secretHash,         // HMAC/Hash(secret + pepper)
    Set<String> scopes,
    Instant expiresAt,
    boolean revoked,
    long ratePerMinute         // simple quota
) {}
```

```java
// KeyUtils.java
package com.example.apikey;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.security.SecureRandom;
import java.util.Base64;

public final class KeyUtils {
  private static final SecureRandom RNG = new SecureRandom();

  public static String randomSecretBase64Url(int bytes) {
    byte[] b = new byte[bytes];
    RNG.nextBytes(b);
    return Base64.getUrlEncoder().withoutPadding().encodeToString(b);
  }

  /** HMAC-SHA256(secret || pepper) as stored hash */
  public static byte[] hmacHash(String secret, byte[] pepper) {
    try {
      Mac mac = Mac.getInstance("HmacSHA256");
      mac.init(new SecretKeySpec(pepper, "HmacSHA256"));
      return mac.doFinal(secret.getBytes(java.nio.charset.StandardCharsets.UTF_8));
    } catch (Exception e) { throw new RuntimeException(e); }
  }

  /** Constant-time equality */
  public static boolean constTimeEq(byte[] a, byte[] b) {
    if (a == null || b == null || a.length != b.length) return false;
    int r = 0; for (int i=0;i<a.length;i++) r |= a[i] ^ b[i];
    return r == 0;
  }
}
```

```java
// InMemoryKeyStore.java
package com.example.apikey;

import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

public class InMemoryKeyStore {
  private final Map<String, ApiKey> byId = new ConcurrentHashMap<>();
  private final byte[] pepper;

  public InMemoryKeyStore(byte[] pepper) { this.pepper = pepper.clone(); }

  /** Issue a new key: returns the ONLY time the caller sees the full token. */
  public String issue(String envPrefix, Set<String> scopes, Instant expiresAt, long rpm) {
    String keyId = randomId();
    String secret = KeyUtils.randomSecretBase64Url(32);
    String token = envPrefix + "_" + keyId + "." + secret;
    byte[] hash = KeyUtils.hmacHash(secret, pepper);
    byId.put(keyId, new ApiKey(keyId, hash, scopes, expiresAt, false, rpm));
    return token;
  }

  public Optional<ApiKey> get(String keyId) { return Optional.ofNullable(byId.get(keyId)); }
  public void revoke(String keyId) { byId.computeIfPresent(keyId, (k,v) -> new ApiKey(k, v.secretHash(), v.scopes(), v.expiresAt(), true, v.ratePerMinute())); }

  private static String randomId() {
    // 12-char base62-ish id
    final String alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    var r = new java.security.SecureRandom(); var sb = new StringBuilder();
    for (int i=0;i<12;i++) sb.append(alphabet.charAt(r.nextInt(alphabet.length())));
    return sb.toString();
  }
}
```

```java
// RateLimiter.java (per-key fixed-window, simple for demo)
package com.example.apikey;

import java.time.Instant;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

public class RateLimiter {
  private static final class Counter { volatile long windowStart; AtomicLong used = new AtomicLong(); }
  private final ConcurrentHashMap<String, Counter> map = new ConcurrentHashMap<>();

  /** returns true if allowed */
  public boolean allow(String keyId, long quotaPerMinute) {
    long now = Instant.now().getEpochSecond();
    long window = now / 60;
    Counter c = map.computeIfAbsent(keyId, k -> new Counter());
    synchronized (c) {
      if (c.windowStart != window) { c.windowStart = window; c.used.set(0); }
      if (c.used.incrementAndGet() <= quotaPerMinute) return true;
      return false;
    }
  }
}
```

```java
// ApiKeyFilter.java
package com.example.apikey;

import javax.servlet.*;
import javax.servlet.http.*;
import java.io.IOException;
import java.time.Instant;
import java.util.Base64;
import java.util.Set;

public class ApiKeyFilter extends OncePerRequestFilter {
  private final InMemoryKeyStore store;
  private final RateLimiter limiter;
  private final byte[] pepper;

  public ApiKeyFilter(InMemoryKeyStore store, RateLimiter limiter, byte[] pepper) {
    this.store = store; this.limiter = limiter; this.pepper = pepper.clone();
  }

  @Override
  protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain)
      throws ServletException, IOException {
    String token = extractToken(req);
    if (token == null) { res.sendError(401, "Missing API key"); return; }

    // Token format: prefix_keyId.secret
    int us = token.indexOf('_'); int dot = token.lastIndexOf('.');
    if (us < 0 || dot < 0 || dot <= us+1) { res.sendError(401, "Malformed API key"); return; }
    String keyId = token.substring(us+1, dot);
    String secret = token.substring(dot+1);

    var recOpt = store.get(keyId);
    if (recOpt.isEmpty()) { res.sendError(401, "Unknown API key"); return; }
    ApiKey rec = recOpt.get();
    if (rec.revoked() || rec.expiresAt().isBefore(Instant.now())) { res.sendError(401, "Key expired/revoked"); return; }

    byte[] presented = KeyUtils.hmacHash(secret, pepper);
    if (!KeyUtils.constTimeEq(presented, rec.secretHash())) { res.sendError(401, "Invalid API key"); return; }

    if (!limiter.allow(keyId, rec.ratePerMinute())) { res.sendError(429, "Rate limit exceeded"); return; }

    // Example scope enforcement: attach to request for downstream checks
    req.setAttribute("apiKeyId", keyId);
    req.setAttribute("scopes", rec.scopes());
    chain.doFilter(req, res);
  }

  private static String extractToken(HttpServletRequest req) {
    String h = req.getHeader("Authorization");
    if (h != null && h.startsWith("Api-Key ")) return h.substring("Api-Key ".length()).trim();
    String x = req.getHeader("X-API-Key"); if (x != null) return x.trim();
    return null;
  }
}
```

```java
// DemoApplication.java (wiring)
package com.example.apikey;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Set;

@SpringBootApplication
public class DemoApplication {
  private static final byte[] PEPPER = "server-pepper-rotate-regularly".getBytes();

  public static void main(String[] args) { SpringApplication.run(DemoApplication.class, args); }

  @Bean InMemoryKeyStore keyStore() {
    return new InMemoryKeyStore(PEPPER);
  }

  @Bean RateLimiter rateLimiter() { return new RateLimiter(); }

  @Bean FilterRegistrationBean<ApiKeyFilter> apiKeyFilter(InMemoryKeyStore ks, RateLimiter rl) {
    // Issue one key at startup (demo)
    String token = ks.issue("ak_live", Set.of("orders:read", "orders:write"),
        Instant.now().plus(30, ChronoUnit.DAYS), 600);
    System.out.println("DEMO API KEY (store securely; shown once): " + token);

    var reg = new FilterRegistrationBean<ApiKeyFilter>(new ApiKeyFilter(ks, rl, PEPPER));
    reg.addUrlPatterns("/api/*");
    reg.setOrder(1);
    return reg;
  }
}
```

```java
// ExampleController.java (scope check)
package com.example.apikey;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import javax.servlet.http.HttpServletRequest;
import java.util.Set;

@RestController
@RequestMapping("/api/orders")
public class ExampleController {

  @GetMapping("/{id}")
  public ResponseEntity<?> getOrder(@PathVariable String id, HttpServletRequest req) {
    if (!hasScope(req, "orders:read")) return ResponseEntity.status(403).body("Missing scope");
    return ResponseEntity.ok("{\"id\":\"" + id + "\",\"status\":\"ok\"}");
  }

  @PostMapping
  public ResponseEntity<?> createOrder(@RequestBody String body, HttpServletRequest req) {
    if (!hasScope(req, "orders:write")) return ResponseEntity.status(403).body("Missing scope");
    return ResponseEntity.status(201).build();
  }

  @SuppressWarnings("unchecked")
  private boolean hasScope(HttpServletRequest req, String scope) {
    Object s = req.getAttribute("scopes");
    return (s instanceof Set<?> set) && set.contains(scope);
  }
}
```

**Notes on hardening the sample**

-   Replace in-memory with a **database/KV**; wrap writes in transactions.
    
-   Move pepper to a **KMS/Secrets Manager**; rotate regularly.
    
-   Consider **Argon2id** / **bcrypt** for hashing (with per-key salt) if secrets are human-generated; for random 32-byte secrets, **HMAC with pepper** is fine.
    
-   Add **IP allow-lists**, **ASN/geofence**, and **HMAC request signing** with a `Date` header + 5-minute clock skew to defeat replay.
    
-   Emit **audit logs** (keyId, decision, scopes, ip, user-agent); never log the secret.
    

---

## Known Uses

-   Public SaaS APIs offering **test/live** keys with per-key scopes and quotas.
    
-   Internal platform service-to-service calls where OAuth is unavailable.
    
-   IoT devices calling ingestion endpoints with **key rotation windows**.
    

---

## Related Patterns

-   **OAuth 2.0 Client Credentials**: stronger lifecycle & delegation; heavier integration.
    
-   **mTLS (Mutual TLS)**: binds identity to certificates; good for internal meshes.
    
-   **HMAC Request Signing**: complements API keys to prevent replay and tampering.
    
-   **Rate Limiting / Throttling**: always pair with per-key budgets.
    
-   **Secrets Management**: issuance, storage, rotation (KMS/ Vault).
    
-   **Zero Trust / Policy Enforcement**: combine device posture, network context.
    

---

## Implementation Checklist

-   Design **key format** with **prefix**, **keyId**, **secret**; expose only once.
    
-   Store **hash(pepper ⊕ secret)**; never store or log plaintext.
    
-   Enforce **TLS**; accept key only in **Authorization** or a dedicated header.
    
-   Implement **scopes**, **expiry**, **revocation**, **rate limits**, and **IP allow-lists**.
    
-   Provide **rotation**: allow two active keys; notify before expiry; kill switch.
    
-   Add **telemetry**: per-key usage, anomalies (geo/ASN/rate), and alerts.
    
-   Consider **request signing** (HMAC over canonical request) for tamper-resistance.
    
-   Run **secrets scanning** (CI/CD & repos), and set up **leak response** (auto-revoke + notify).
    
-   Document **client storage guidelines** (no browser/mobile; use server vaults).

