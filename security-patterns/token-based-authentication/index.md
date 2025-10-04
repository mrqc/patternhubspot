# Token Based Authentication — Security Pattern

## Pattern Name and Classification

-   **Name:** Token Based Authentication
    
-   **Classification:** Security / Authentication & Authorization / Stateless
    

## Intent

Authenticate clients by issuing **time-bounded tokens** that the client presents with each request. Servers **validate** these tokens (locally or via introspection) to establish identity and authorization **without holding session state** on the application tier.

## Also Known As

-   Bearer Token Authentication
    
-   JWT Authentication (when using JSON Web Tokens)
    
-   Opaque Token with Introspection
    

## Motivation (Forces)

-   **Scalability:** Stateless verification avoids server-side session storage and sticky sessions.
    
-   **Performance vs. Revocation:** Locally verifiable (e.g., JWT) is fast but harder to revoke; introspected opaque tokens are slower but centrally controllable.
    
-   **Security:** Tokens are high-value bearer artifacts — must be short-lived, bound to audience/scope, rotated, and transmitted only over TLS.
    
-   **Interoperability:** Microservices and APIs across domains need portable, signed credentials.
    
-   **Privacy:** Minimize sensitive data in tokens; prefer references (opaque) or limited claims.
    
-   **Operational:** Key rotation, clock skew, multi-issuer, and multi-tenant concerns.
    

## Applicability

Use when:

-   You need **stateless auth** for web/mobile clients or microservices.
    
-   Services are horizontally scaled or distributed (edge/API gateway).
    
-   You integrate with **OAuth 2.1/OpenID Connect** providers.
    
-   You need **delegated access** (scopes), **machine-to-machine** access, or SSO across services.
    

## Structure

-   **Client** acquires **Access Token** (and optionally **Refresh Token**) from **Authorization Server (AS)**.
    
-   **Resource Server (RS)** validates token on each request:
    
    -   **Self-contained token** (e.g., **JWT** signed JWS): verify signature, claims.
        
    -   **Opaque token:** call AS **Introspection** endpoint to validate and fetch claims.
        
-   **Key Management:** JWKS for public keys, KMS/HSM for private keys, **kid** for rotation.
    
-   **Policy Engine:** evaluates scopes/roles, audience, tenant, and risk signals.
    
-   **(Optional) Proof-of-Possession:** DPoP or mTLS to bind token to client key.
    

## Participants

-   **Authorization Server (Issuer/IdP)** — authenticates user/client; issues/rotates tokens.
    
-   **Client** — stores and sends tokens in `Authorization: Bearer …`.
    
-   **Resource Server (API)** — validates tokens and enforces authorization.
    
-   **JWKS Endpoint / KMS** — distributes verification keys securely.
    
-   **Token Introspection Endpoint** — validates opaque tokens and returns metadata.
    
-   **Audit/Observability** — logs issuance/validation/revocation (without leaking tokens).
    

## Collaboration

1.  Client authenticates to **AS** (e.g., OAuth2 authorization code + PKCE).
    
2.  AS issues **short-lived access token** (+ optional refresh token).
    
3.  Client calls **RS** with `Authorization: Bearer <token>`.
    
4.  RS validates:
    
    -   **JWT:** verify signature (kid → JWKS), check `iss`, `aud`, `exp`, `nbf`, `iat`, `jti`, scopes/roles.
        
    -   **Opaque:** call **/introspect**, cache positive results briefly.
        
5.  RS authorizes and serves or denies.
    
6.  On expiry, client uses **refresh token** (if applicable) to obtain a new access token (rotation enforced).
    
7.  Revocations/compromises are handled via **short TTL**, **blocklists/jti**, or introspection.
    

## Consequences

**Benefits**

-   Horizontal scalability (stateless, cache-friendly).
    
-   Clear separation of concerns (AS vs RS).
    
-   Interoperable claims model and scopes.
    
-   Works across microservices and zero-trust perimeters.
    

**Liabilities**

-   **Bearer risk:** token theft equals access; always require TLS and prefer PoP for high risk.
    
-   **Revocation gaps** for JWTs (mitigated by short TTL, jti blocklists, back-channel logout).
    
-   **Key rotation complexity** (kid/JWKS caching, leeway for propagation).
    
-   **Claims bloat** if overused; privacy concerns if tokens leak.
    

## Implementation

### Core Rules (Checklist)

-   **TLS only.** Never send tokens over HTTP; consider **HSTS**.
    
-   **Short-lived access tokens** (5–15 minutes); **rotate refresh tokens** and set absolute lifetimes.
    
-   Validate: signature, `iss`, `aud`, `exp`, `nbf`, `iat`, `jti`, **clock skew** (±60–120s), scopes/roles, `cnf` (for PoP).
    
-   Use **`kid`** and **JWKS** for key discovery + rotation; cache keys with reasonable TTL.
    
-   **Do not store secrets** or PII in tokens; prefer subject IDs and minimal claims.
    
-   For browsers, store tokens in **HttpOnly, Secure, SameSite cookies** or keep tokens outside JS-accessible storage; avoid localStorage for high-risk apps.
    
-   For machine-to-machine, prefer **client credentials** or mTLS/DPoP.
    
-   **Audience isolation:** one token should target one API audience when possible.
    
-   **Revoke strategies:** short TTL, jti denylist, introspection for opaque tokens.
    
-   **Log safely:** never log tokens; log `sub`, `jti`, `iss`, `aud` after extraction.
    

### Data Elements (JWT example)

```css
Header:  { "alg": "RS256", "kid": "2025-08-key-01", "typ": "JWT" }
Claims:  { "iss": "https://auth.example.com",
           "sub": "user-123",
           "aud": "https://api.example.com",
           "exp": 1730726400, "nbf": 1730723100, "iat": 1730723100,
           "jti": "a1b2c3...", "scope": "orders:read orders:write",
           "tenant": "t-42" }
```

---

## Sample Code (Java)

Below are **(A) JWT validation** (Nimbus JOSE + JWT) and **(B) Token issuance** (demo only). Also a **(C) simple opaque introspection** stub.

> Dependencies (Gradle)

```gradle
dependencies {
  implementation 'com.nimbusds:nimbus-jose-jwt:9.37.3'
  implementation 'com.fasterxml.jackson.core:jackson-databind:2.17.1'
  implementation 'org.apache.httpcomponents.client5:httpclient5:5.3.1' // if you need HTTP JWKS fetch or introspection
}
```

### A) Resource Server: Validate JWT Access Token

```java
import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.jwk.source.*;
import com.nimbusds.jose.jwk.*;
import com.nimbusds.jose.proc.*;
import com.nimbusds.jwt.proc.*;
import com.nimbusds.jwt.SignedJWT;

import java.net.URL;
import java.time.Instant;
import java.util.Set;

public class JwtValidator {

    private final ConfigurableJWTProcessor<com.nimbusds.jose.proc.SecurityContext> processor;
    private final String expectedIssuer;
    private final String expectedAudience;

    public JwtValidator(String jwksUrl, String expectedIssuer, String expectedAudience) throws Exception {
        JWKSource<com.nimbusds.jose.proc.SecurityContext> keySource =
                new RemoteJWKSet<>(new URL(jwksUrl));
        this.processor = new DefaultJWTProcessor<>();
        JWSKeySelector<com.nimbusds.jose.proc.SecurityContext> keySelector =
                new JWSVerificationKeySelector<>(JWSAlgorithm.RS256, keySource);
        processor.setJWSKeySelector(keySelector);
        this.expectedIssuer = expectedIssuer;
        this.expectedAudience = expectedAudience;
    }

    public TokenPrincipal validate(String bearerToken) throws Exception {
        if (bearerToken == null || !bearerToken.startsWith("Bearer "))
            throw new SecurityException("Missing bearer token");

        String token = bearerToken.substring("Bearer ".length()).trim();
        SignedJWT jwt = SignedJWT.parse(token);

        var ctx = null; // no special context
        var claims = processor.process(jwt, ctx).getJWTClaimsSet();

        // Basic claim checks with slight clock skew tolerance
        var now = Instant.now().getEpochSecond();
        var exp = claims.getExpirationTime().toInstant().getEpochSecond();
        var nbf = claims.getNotBeforeTime() == null ? 0L : claims.getNotBeforeTime().toInstant().getEpochSecond();
        var iat = claims.getIssueTime() == null ? 0L : claims.getIssueTime().toInstant().getEpochSecond();

        long skew = 120; // seconds
        if (exp + 0 < now - skew) throw new SecurityException("Token expired");
        if (nbf - skew > now) throw new SecurityException("Token not yet valid");
        if (!expectedIssuer.equals(claims.getIssuer())) throw new SecurityException("Bad issuer");
        if (claims.getAudience() == null || !claims.getAudience().contains(expectedAudience))
            throw new SecurityException("Bad audience");

        // Extract scopes (space-delimited) and subject
        String scope = (String) claims.getClaim("scope");
        String sub = claims.getSubject();
        String jti = claims.getJWTID();

        // Optionally check denylist by jti
        // if (denylist.contains(jti)) throw new SecurityException("Revoked token");

        return new TokenPrincipal(sub, scope, jti, claims.getIssuer(), claims.getAudience());
    }

    public record TokenPrincipal(String sub, String scope, String jti, String iss, java.util.List<String> aud) {}
}
```

### B) Authorization Server: Issue JWT (Demo Only)

```java
import com.nimbusds.jose.*;
import com.nimbusds.jose.crypto.RSASSASigner;
import com.nimbusds.jose.jwk.RSAKey;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;

import java.time.Instant;
import java.util.Date;
import java.util.UUID;

public class JwtIssuer {

    private final RSAKey rsaKey; // includes private key

    public JwtIssuer(RSAKey rsaKey) {
        this.rsaKey = rsaKey;
    }

    public String mintAccessToken(String subject, String audience, String scope) throws Exception {
        Instant now = Instant.now();
        JWTClaimsSet claims = new JWTClaimsSet.Builder()
                .issuer("https://auth.example.com")
                .subject(subject)
                .audience(audience)
                .issueTime(Date.from(now))
                .notBeforeTime(Date.from(now.minusSeconds(10)))
                .expirationTime(Date.from(now.plusSeconds(900))) // 15 minutes
                .jwtID(UUID.randomUUID().toString())
                .claim("scope", scope)
                .build();

        JWSHeader header = new JWSHeader.Builder(JWSAlgorithm.RS256)
                .keyID(rsaKey.getKeyID())
                .type(JOSEObjectType.JWT)
                .build();

        SignedJWT jwt = new SignedJWT(header, claims);
        JWSSigner signer = new RSASSASigner(rsaKey.toPrivateKey());
        jwt.sign(signer);
        return jwt.serialize();
    }
}
```

> Creating an RSA JWK (demo)

```java
import com.nimbusds.jose.jwk.RSAKey;

import java.security.KeyPair;
import java.security.KeyPairGenerator;

public class KeyUtil {
    public static RSAKey newRsaJwk(String kid) throws Exception {
        KeyPairGenerator kpg = KeyPairGenerator.getInstance("RSA");
        kpg.initialize(2048);
        KeyPair kp = kpg.generateKeyPair();
        return new RSAKey.Builder((java.security.interfaces.RSAPublicKey) kp.getPublic())
                .privateKey(kp.getPrivate())
                .keyID(kid)
                .build();
    }
}
```

### C) Opaque Token Introspection (Resource Server)

```java
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.hc.client5.http.classic.methods.HttpPost;
import org.apache.hc.client5.http.impl.classic.CloseableHttpClient;
import org.apache.hc.client5.http.impl.classic.HttpClients;
import org.apache.hc.core5.http.io.entity.UrlEncodedFormEntity;
import org.apache.hc.core5.http.NameValuePair;
import org.apache.hc.core5.http.message.BasicNameValuePair;

import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;

public class OpaqueIntrospector {

    private final String introspectUrl;
    private final String clientId;
    private final String clientSecret;
    private final ObjectMapper mapper = new ObjectMapper();

    public OpaqueIntrospector(String url, String clientId, String clientSecret) {
        this.introspectUrl = url;
        this.clientId = clientId;
        this.clientSecret = clientSecret;
    }

    public Map<String, Object> introspect(String token) throws Exception {
        try (CloseableHttpClient http = HttpClients.createDefault()) {
            HttpPost post = new HttpPost(introspectUrl);
            post.addHeader("Authorization", "Basic " +
                java.util.Base64.getEncoder().encodeToString((clientId + ":" + clientSecret).getBytes(StandardCharsets.UTF_8)));
            post.setEntity(new UrlEncodedFormEntity(List.of(
                    new BasicNameValuePair("token", token),
                    new BasicNameValuePair("token_type_hint", "access_token")
            )));
            var resp = http.execute(post);
            var body = new String(resp.getEntity().getContent().readAllBytes(), StandardCharsets.UTF_8);
            Map<String, Object> payload = mapper.readValue(body, Map.class);
            if (!(Boolean) payload.getOrDefault("active", false)) throw new SecurityException("Inactive token");
            return payload; // contains sub, scope, client_id, exp, aud, etc.
        }
    }
}
```

**Notes for production**

-   Prefer **authorization code + PKCE** for browser apps; **client credentials** for service-to-service.
    
-   Consider **DPoP** or **mTLS-bound tokens** for stronger replay resistance.
    
-   Cache JWKS and introspection responses with **short TTL** and **negative caching** for performance.
    
-   Enforce **audience and scope** at every API; apply **least privilege**.
    
-   Implement **refresh token rotation** and **replay detection**; revoke on reuse.
    
-   Propagate **trace IDs** but never the token in logs.
    
-   For multi-tenant systems, include/validate `tenant` claim and isolate keys per tenant when feasible.
    

## Known Uses

-   **OpenID Connect** and **OAuth 2.x** across major IdPs (Auth0, Azure AD, Okta, Keycloak) issuing JWT access tokens for APIs.
    
-   **Cloud provider APIs** and **microservice meshes** using JWTs with JWKS discovery.
    
-   **Banking/PSD2** ecosystems with **mTLS/PoP** and fine-grained scopes.
    
-   **Service-to-service** workloads using **client credentials** and short-lived tokens.
    

## Related Patterns

-   **Secure Session Management** (server-side sessions; complements tokens for web)
    
-   **Refresh Token** (longer-lived credential to get new access tokens)
    
-   **API Gateway** (central token validation, caching, policy enforcement)
    
-   **Tamper Detection** (token signature integrity)
    
-   **Secrets Manager** (protects signing keys and client secrets)
    
-   **Secure Logger** (log token metadata safely, never the token itself)
    

---

**Bottom line:** Token Based Authentication enables **stateless, scalable** auth with clear **claims and scopes**. The right choice between **JWT (self-contained)** and **opaque (introspected)** depends on your needs for **latency vs. revocation control**, but both require disciplined **TLS, rotation, short lifetimes, and careful validation**.

