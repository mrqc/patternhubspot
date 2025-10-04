# Refresh Token — Security Pattern

## Pattern Name and Classification

**Name:** Refresh Token  
**Classification:** Security / Identity & Access Management (IAM) / Session Continuity — *Short-lived access tokens with long-lived, tightly-controlled refresh credentials*

---

## Intent

Maintain a **usable, long-lived login** while keeping **access tokens short-lived** (minutes) by issuing a **refresh token** that can obtain new access tokens without re-authentication—**safely** (rotation, revocation, scope controls, device binding, anomaly detection).

---

## Also Known As

-   Refresh Token Rotation (RTR)
    
-   Sliding Session / Renewable Session
    
-   Offline Token (OIDC term in some IdPs)
    

---

## Motivation (Forces)

-   **Least exposure:** Short access-token TTL limits damage if a bearer token leaks.
    
-   **UX vs. security:** Users shouldn’t log in every 15 minutes; refresh tokens preserve UX.
    
-   **Public clients:** SPAs/mobile cannot hold client secrets; refresh tokens with **PKCE**, rotation, and httpOnly cookies help.
    
-   **Compromise detection:** **Reuse detection** (using a rotated token twice) is a strong theft signal that lets you revoke an entire token family.
    

Tensions: refresh tokens are **high-value** credentials; misuse can lead to silent account takeover if rotation/revocation/auditing aren’t implemented.

---

## Applicability

Use refresh tokens when:

-   You issue **short-lived access tokens** (JWT/opaque) and want long-lived sessions.
    
-   Clients include **mobile/SPA** or **confidential** server apps.
    
-   You need **offline access** (background sync) with explicit user consent.
    

Avoid or adapt when:

-   You can maintain a server session cookie only (no API tokens needed).
    
-   Ultra-short interactive sessions (e.g., kiosks) where re-auth is acceptable.
    
-   Strict environments where **refresh tokens are forbidden**—use re-auth or device-bound tokens.
    

---

## Structure

-   **Access Token (AT):** Short-lived bearer (e.g., JWT, 5–15 min).
    
-   **Refresh Token (RT):** Long-lived, **opaque**, single-use with **rotation**; stored hashed server-side.
    
-   **Token Store:** DB for RT metadata (hash, owner, scopes, expiry, device, IP/UA, family id, parent).
    
-   **Rotation Logic:** On each refresh: **invalidate old RT**, issue a **new RT** (child) + new AT.
    
-   **Reuse Detection:** If an **already-rotated RT** is used again → revoke **entire family** and alert.
    
-   **Revocation / Logout:** Mark current (and optionally family) revoked; block list for AT if needed.
    
-   **Transport:** httpOnly+Secure+SameSite cookies (web) or secure OS keystore (mobile).
    
-   **Policy Engine:** Scope ceilings, absolute max session age, device/IP checks, risk signals.
    

---

## Participants

-   **Client App:** Holds RT securely; calls `/token/refresh`.
    
-   **Authorization Server (AS) / IdP:** Issues AT/RT; rotates, revokes, audits.
    
-   **Resource Server (API):** Verifies AT; may query introspection/allowlist.
    
-   **Token Store / DB:** Persists RT family state and hashes.
    
-   **Risk/Audit:** Detects anomalies (geo jump, reuse, UA mismatch), triggers step-up or kill switch.
    

---

## Collaboration

1.  **Login:** AS authenticates → issues **AT(short)** + **RT(long)**; stores **hash** of RT + metadata (familyId, parent).
    
2.  **Refresh:** Client presents RT → AS verifies **hash + status + expiry** →  
    a) **Rotate:** mark presented RT as used; create **new RT (child)** and new AT; return both.  
    b) **Reuse detection:** if RT already used/revoked → **revoke family**, deny, alert.
    
3.  **Logout/Revocation:** Client or admin invalidates current RT (and optionally family); ATs naturally expire or are added to denylist for a grace period.
    
4.  **Session Max Age:** After absolute TTL, force full re-auth.
    

---

## Consequences

**Benefits**

-   AT compromise window is **small**; session continuity preserved.
    
-   **Reuse detection** provides early compromise signal.
    
-   RT scopes and device binding support **least privilege** and contextual access.
    

**Liabilities**

-   RT becomes a **high-value secret**; storage and transport must be hardened.
    
-   Extra **server state** (RT store) and flows to implement correctly.
    
-   Misconfigured rotation can lock out users or, worse, permit **silent replay**.
    

---

## Implementation

### Key Decisions

-   **Token shapes:**
    
    -   **AT:** JWT (asymmetric, short TTL, audience/issuer/nonce).
        
    -   **RT:** **Opaque** `rt_<id>.<secret>`; store only **HMAC(hash(secret + pepper))** and metadata.
        
-   **Rotation policy:** **One-time use**; always return a **new RT** on refresh.
    
-   **Reuse detection:** If a rotated/invalid RT is presented, **revoke family** and require re-auth.
    
-   **Storage:** Per-user **families** (chain via `parentId`), IP/UA, device id, `createdAt`, `rotatedAt`, `revoked`.
    
-   **Cookies (web):** httpOnly, Secure, SameSite=Lax/Strict, Path, and **`__Host-` prefix** when feasible; store RT only in cookies (never JS).
    
-   **Absolute session TTL:** e.g., 30 days; sliding window within that.
    
-   **Scopes:** Cap RT → AT scopes; don’t allow privilege escalation via refresh.
    
-   **Public clients:** Pair with **PKCE**; optionally bind RT to device key, IP reputation, or DPoP/MTLS.
    
-   **Revocation:** “Logout all devices” = revoke **family**; “logout here” = revoke current branch.
    
-   **Rate limiting & anomaly:** throttle refresh endpoint; step-up auth on risk.
    

### Anti-Patterns

-   **Non-rotating** RTs (replayable).
    
-   Storing RTs **in plaintext** or in browser **localStorage** (XSS risk).
    
-   Allowing **scope elevation** on refresh.
    
-   Accepting refresh over **HTTP** or from **unexpected origins**.
    
-   Overlong RT TTL with no **absolute max**.
    

---

## Sample Code (Java) — Refresh Token Rotation with Reuse Detection

*Demonstrates an opaque RT format (`rt_<id>.<secret>`), server-side hashed storage, rotation, reuse detection, and short-lived JWT access tokens.*

> Gradle (snip)

```gradle
implementation 'io.jsonwebtoken:jjwt-api:0.11.5'
runtimeOnly   'io.jsonwebtoken:jjwt-impl:0.11.5'
runtimeOnly   'io.jsonwebtoken:jjwt-jackson:0.11.5'
```

```java
// RefreshTokenService.java
package com.example.tokens;

import io.jsonwebtoken.*;
import io.jsonwebtoken.security.Keys;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.security.Key;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ThreadLocalRandom;
import java.util.Base64;

public class RefreshTokenService {

  /* ---------------- Models ---------------- */

  public static final class RefreshTokenRecord {
    public final String id;             // public id part
    public final String userId;
    public final String familyId;       // all rotated tokens share a family
    public final String parentId;       // previous token id in chain (nullable)
    public final byte[] secretHash;     // HMAC(secret + pepper)
    public final Instant expiresAt;
    public volatile boolean revoked = false;
    public volatile Instant rotatedAt = null; // set when used to mint a child
    public final String userAgent, ip;

    RefreshTokenRecord(String id, String userId, String familyId, String parentId,
                       byte[] secretHash, Instant expiresAt, String ua, String ip) {
      this.id = id; this.userId = userId; this.familyId = familyId; this.parentId = parentId;
      this.secretHash = secretHash; this.expiresAt = expiresAt; this.userAgent = ua; this.ip = ip;
    }
  }

  /* ---------------- Config ---------------- */

  private final byte[] pepper;                  // server secret for HMAC hashing of RT secrets
  private final long accessTtlSeconds;          // e.g., 900 (15m)
  private final long refreshTtlSeconds;         // e.g., 2592000 (30d absolute)
  private final Key jwtKey;                     // HS256 for demo; prefer RS/EdDSA in prod
  private final String issuer = "example-auth";

  // In-memory store for demo; replace with DB
  private final Map<String, RefreshTokenRecord> storeById = new ConcurrentHashMap<>();

  public RefreshTokenService(byte[] pepper, long accessTtlSeconds, long refreshTtlSeconds) {
    this.pepper = pepper.clone();
    this.accessTtlSeconds = accessTtlSeconds;
    this.refreshTtlSeconds = refreshTtlSeconds;
    this.jwtKey = Keys.hmacShaKeyFor(("replace-with-256-bit-secret-really-long" +
        "----------------------------------------------------------------").getBytes());
  }

  /* ---------------- Public API ---------------- */

  /** On login: issue short AT + long RT (family root). */
  public Tokens login(String userId, String userAgent, String ip) {
    String family = randId(16);
    return issueTokens(userId, family, null, userAgent, ip);
  }

  /** On refresh: verify, rotate, reuse-detect, and return new pair. */
  public Tokens refresh(String presentedRt, String userAgent, String ip) {
    Parsed p = parseRt(presentedRt);
    RefreshTokenRecord rec = storeById.get(p.id);
    if (rec == null || rec.revoked || Instant.now().isAfter(rec.expiresAt) || !constantTimeEq(rec.secretHash, hmac(p.secret))) {
      // If secret mismatch but id exists, it’s tampering → treat as invalid (no detail leakage)
      throw new RuntimeException("invalid refresh token");
    }
    // Reuse detection: token already used to rotate (rotatedAt set) or parent of something?
    if (rec.rotatedAt != null) {
      // Compromise signal: revoke entire family
      revokeFamily(rec.familyId);
      throw new RuntimeException("refresh token reuse detected; session revoked");
    }
    // Basic device/UA checks (optional policy)
    // if (!Objects.equals(rec.userAgent, userAgent)) { ... step-up or deny ... }

    // Mark current as rotated and mint child
    rec.rotatedAt = Instant.now();
    return issueTokens(rec.userId, rec.familyId, rec.id, userAgent, ip);
  }

  /** Logout current: revoke token by id; optionally revoke family. */
  public void logout(String presentedRt, boolean allDevices) {
    Parsed p = parseRt(presentedRt);
    RefreshTokenRecord rec = storeById.get(p.id);
    if (rec != null) {
      if (allDevices) revokeFamily(rec.familyId);
      else rec.revoked = true;
    }
  }

  /* ---------------- Internals ---------------- */

  private Tokens issueTokens(String userId, String familyId, String parentId, String ua, String ip) {
    Instant now = Instant.now();
    String access = Jwts.builder()
        .setIssuer(issuer).setSubject(userId)
        .setIssuedAt(Date.from(now))
        .setExpiration(Date.from(now.plusSeconds(accessTtlSeconds)))
        .claim("scope", "user.read") // cap scopes as needed
        .signWith(jwtKey, SignatureAlgorithm.HS256)
        .compact();

    // Opaque RT: id + secret; store hash(secret)
    String id = randId(12);
    String secret = randUrlSafe(32);
    byte[] hash = hmac(secret);
    Instant exp = now.plusSeconds(refreshTtlSeconds);
    RefreshTokenRecord rec = new RefreshTokenRecord(id, userId, familyId, parentId, hash, exp, ua, ip);
    storeById.put(id, rec);

    String refreshOpaque = "rt_" + id + "." + secret; // only time the secret is revealed
    return new Tokens(access, refreshOpaque, exp);
  }

  private static final class Parsed { String id, secret; Parsed(String i, String s){id=i;secret=s;} }
  private Parsed parseRt(String token) {
    if (token == null || !token.startsWith("rt_")) throw new RuntimeException("missing RT");
    int dot = token.lastIndexOf('.');
    if (dot < 0) throw new RuntimeException("malformed RT");
    return new Parsed(token.substring(3, dot), token.substring(dot + 1));
  }

  private void revokeFamily(String familyId) {
    storeById.values().stream().filter(r -> r.familyId.equals(familyId)).forEach(r -> r.revoked = true);
  }

  /* ---------------- Utils ---------------- */

  private byte[] hmac(String secret) {
    try {
      Mac mac = Mac.getInstance("HmacSHA256");
      mac.init(new SecretKeySpec(pepper, "HmacSHA256"));
      return mac.doFinal(secret.getBytes(java.nio.charset.StandardCharsets.UTF_8));
    } catch (Exception e) { throw new RuntimeException(e); }
  }
  private static boolean constantTimeEq(byte[] a, byte[] b) {
    if (a == null || b == null || a.length != b.length) return false;
    int r = 0; for (int i = 0; i < a.length; i++) r |= a[i] ^ b[i];
    return r == 0;
  }
  private static String randId(int len) { return randBase62(len); }
  private static String randUrlSafe(int bytes) {
    byte[] buf = new byte[bytes];
    ThreadLocalRandom.current().nextBytes(buf);
    return Base64.getUrlEncoder().withoutPadding().encodeToString(buf);
  }
  private static String randBase62(int len) {
    String a = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
    var r = ThreadLocalRandom.current(); var sb = new StringBuilder(len);
    for (int i=0;i<len;i++) sb.append(a.charAt(r.nextInt(a.length())));
    return sb.toString();
  }

  /* ---------------- DTO ---------------- */
  public static final class Tokens {
    public final String accessToken;        // JWT
    public final String refreshToken;       // opaque
    public final Instant refreshExpiresAt;
    Tokens(String at, String rt, Instant exp){ this.accessToken=at; this.refreshToken=rt; this.refreshExpiresAt=exp; }
  }
}
```

```java
// Demo.java
package com.example.tokens;

public class Demo {
  public static void main(String[] args) {
    var svc = new RefreshTokenService("server-pepper-change-and-rotate".getBytes(), 900, 30L * 24 * 3600);

    // Login → AT + RT
    var t1 = svc.login("user-123", "UA-1", "1.2.3.4");
    System.out.println("AT1=" + t1.accessToken.substring(0, 20) + "…");
    System.out.println("RT1=" + t1.refreshToken);

    // Refresh (normal) → rotates RT
    var t2 = svc.refresh(t1.refreshToken, "UA-1", "1.2.3.4");
    System.out.println("RT2=" + t2.refreshToken);

    // Attempt to reuse RT1 → family revoked (compromise signal)
    try {
      svc.refresh(t1.refreshToken, "UA-1", "1.2.3.4");
    } catch (RuntimeException ex) {
      System.out.println("Expected reuse detection: " + ex.getMessage());
    }

    // Logout everywhere
    svc.logout(t2.refreshToken, true);
  }
}
```

**How to deploy this safely**

-   Store RTs in a **database**; index by `id`, store **hash only**; include `familyId`, `parentId`, `expiresAt`, `rotatedAt`, `revoked`, device/IP/UA.
    
-   Return RT **only once**, preferably via **httpOnly+Secure cookies**; never expose to JS.
    
-   Enforce **TLS**, **CORS** and **same-origin** on refresh endpoint; add **rate limits** and CSRF protection if using cookies.
    
-   Use **asymmetric JWT** (RS256/EdDSA) with `aud/iss/exp/nbf/kid` and **short TTL** (5–15 min).
    
-   Enforce **absolute session TTL**; after it elapses, require login.
    
-   On **reuse detection**, revoke **family**, invalidate active sessions, alert the user, and require step-up re-auth.
    

---

## Known Uses

-   **OAuth 2.0 / OIDC** Authorization Servers (Auth0, Keycloak, Azure AD) with **Refresh Token Rotation** and reuse detection.
    
-   **Mobile apps** using RTs in OS keystores (Android Keystore, iOS Keychain) to keep background sync running.
    
-   **SPAs** storing RT in **httpOnly cookies**, using short ATs for API calls.
    
-   **Enterprise SSO** providing **offline\_access** scopes for trusted automation with strict policies.
    

---

## Related Patterns

-   **Authorization Code + PKCE:** secure authorization flow for public clients.
    
-   **Short-Lived Access Tokens / JWT:** complements RTs to lower exposure.
    
-   **Token Introspection / Revocation Lists:** verify/disable tokens after issue.
    
-   **DPoP / mTLS / Token Binding:** bind tokens to a key to reduce replay.
    
-   **Session Management & Back-Channel Logout:** coordinate logout across clients.
    
-   **Principle of Least Privilege:** scope ceilings for refreshed ATs.
    

---

## Implementation Checklist

-   Make RTs **opaque**, **single-use**, and **rotated** on every refresh.
    
-   Store only **hashed** RT secrets (peppered HMAC or slow hash) with **family** metadata.
    
-   Add **reuse detection** and revoke **entire family** on reuse.
    
-   Transport RT via **httpOnly+Secure** cookies; protect refresh with **TLS, CSRF, rate limits**.
    
-   Keep ATs **short-lived**; include `aud`, `iss`, `exp`, `nbf`, `sub`, and `scope`.
    
-   Enforce **absolute session TTL** and device/IP checks as policy allows.
    
-   Provide **logout (current / all devices)** and **admin revocation**.
    
-   Emit **audit events** (issued, refreshed, rotated, revoked, reuse detected).
    
-   Test failure modes: clock skew, rapid multi-tab refresh, concurrent rotation, DB outages.

