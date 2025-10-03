# Token Authentication — API Design Pattern

## Pattern Name and Classification

**Token Authentication** — *Security / Access Control* pattern for authenticating API calls using **bearer tokens** (opaque or self-contained like **JWT**), sent on each request.

---

## Intent

Authenticate clients **statelessly** by presenting a **short string token** in every request (typically in `Authorization: Bearer <token>`), allowing the server or an auth server to validate the token and derive the caller’s identity/permissions.

---

## Also Known As

-   **Bearer Token Auth**

-   **JWT Auth** (when using JSON Web Tokens)

-   **Opaque Token + Introspection**

-   **Access/Refresh Token Pattern**


---

## Motivation (Forces)

-   Need **stateless**, horizontally scalable authentication (no server-side session).

-   Support **mobile, SPA, machine-to-machine** clients.

-   Enforce **scopes/roles/claims**, **expiry**, and **revocation**.

-   Balance **performance** (local JWT verify) vs. **control** (central introspection).


Trade-offs:

-   JWT: fast local verify, but **revocation is harder** (use short TTL + revocation lists).

-   Opaque: easy **central control** (introspection), but **extra hop** and latency.


---

## Applicability

Use when:

-   You expose APIs to multiple clients/services and need **stateless auth**.

-   You want **fine-grained authorization** via scopes/claims embedded in the token.

-   You integrate with **OAuth2/OIDC** providers.


Avoid / limit when:

-   Long-lived web sessions with server-rendered pages (cookie/session may be simpler).

-   Strict, immediate **token revocation** without central check (prefer opaque).


---

## Structure

```scss
Client --(credentials)--> Auth Server ----> issues token (JWT or opaque)
Client --(Authorization: Bearer <token>)--> Resource Server (API)
Resource Server:
  - JWT: verify signature + exp/nbf + audience + scopes
  - Opaque: call /introspect on Auth Server
  - Authorize by roles/scopes → allow/deny
```

---

## Participants

-   **Client** – obtains and presents tokens.

-   **Auth Server (IdP)** – issues/refreshes tokens; introspects opaque tokens.

-   **Resource Server (API)** – validates token, enforces authorization.

-   **Token** – carries identity/claims: `sub`, `aud`, `exp`, `scope`, custom claims.


---

## Collaboration

1.  Client authenticates to **Auth Server** (password, client credentials, PKCE, etc.).

2.  Receives **access token** (and optionally **refresh token**).

3.  Calls API with `Authorization: Bearer <access_token>`.

4.  API validates the token (signature or introspection) and authorizes.

5.  On expiry, client uses **refresh token** to obtain a new access token.


---

## Consequences

**Benefits**

-   **Stateless** and cache-friendly; scales horizontally.

-   Clear **separation of concerns** (IdP vs. resource).

-   Fine-grained auth via **claims/scopes**.


**Liabilities**

-   **Revocation** complexity for JWT (short TTL + rotations, or introspect).

-   Token leakage is critical → must use **TLS**, proper storage, and least-privilege scopes.

-   Clock skew and key rotation must be handled.


---

## Implementation (Key Points)

-   Prefer **HTTPS only**; reject tokens over plain HTTP.

-   Validate **signature**, **issuer (iss)**, **audience (aud)**, **expiry (exp)**, **not-before (nbf)**.

-   Apply **authorization** by scopes/roles/claims per route.

-   **Key rotation**: JWKS (kid) with caching; handle rollover.

-   JWT TTL: **short (5–15 min)**; use refresh tokens securely (httpOnly cookie, rotating).

-   Consider **opaque tokens** + **introspection** for immediate revocation and central policy.

-   Add **rate limiting** and **replay protections** where relevant.

-   Log **token thumbprint/kid**, not the token itself.


---

## Sample Code (Java, Spring Boot 3)

Two common setups: **JWT validation (local)** and **Opaque introspection**.  
Below is a runnable JWT resource server + a tiny token issuer (demo only).

### Gradle (snippets)

```gradle
implementation "org.springframework.boot:spring-boot-starter-web"
implementation "org.springframework.boot:spring-boot-starter-security"
implementation "org.springframework.boot:spring-boot-starter-oauth2-resource-server"
implementation "io.jsonwebtoken:jjwt-api:0.11.5"
runtimeOnly "io.jsonwebtoken:jjwt-impl:0.11.5"
runtimeOnly "io.jsonwebtoken:jjwt-jackson:0.11.5"
```

### 1) Demo Token Issuer (HS256 for simplicity—use **RS256/ES256** in production)

```java
package demo.token;

import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;

import javax.crypto.SecretKey;
import java.time.Instant;
import java.util.Date;
import java.util.Map;

@RestController
@RequestMapping("/auth")
class AuthController {
  // Use asymmetric keys in prod; rotate via JWKS. This is demo only.
  static final SecretKey KEY = Keys.hmacShaKeyFor("change-this-demo-secret-change-this-demo-secret".getBytes());

  @PostMapping(value="/token", produces=MediaType.APPLICATION_JSON_VALUE)
  public Map<String,String> token(@RequestParam String user, @RequestParam String scope) {
    Instant now = Instant.now();
    String jwt = Jwts.builder()
      .setIssuer("https://issuer.example")
      .setSubject(user)                    // sub
      .setAudience("orders-api")           // aud
      .setIssuedAt(Date.from(now))
      .setExpiration(Date.from(now.plusSeconds(600))) // 10 min
      .addClaims(Map.of("scope", scope))   // e.g. "orders.read orders.write"
      .signWith(KEY)
      .compact();
    return Map.of("access_token", jwt, "token_type","Bearer", "expires_in","600");
  }
}
```

### 2) Resource Server (validates JWT locally; enforces scopes)

```java
package demo.token;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.oauth2.jwt.*;
import org.springframework.security.web.SecurityFilterChain;

@Configuration
@EnableMethodSecurity // enables @PreAuthorize
class SecurityConfig {

  @Bean
  SecurityFilterChain api(HttpSecurity http, JwtDecoder decoder) throws Exception {
    return http
      .csrf(csrf -> csrf.disable())
      .authorizeHttpRequests(auth -> auth
          .requestMatchers("/auth/**").permitAll()
          .requestMatchers(HttpMethod.GET, "/orders/**").hasAuthority("SCOPE_orders.read")
          .requestMatchers(HttpMethod.POST, "/orders/**").hasAuthority("SCOPE_orders.write")
          .anyRequest().authenticated())
      .oauth2ResourceServer(oauth -> oauth.jwt(jwt -> jwt.decoder(decoder)))
      .build();
  }

  // HS256 demo decoder. Prefer Nimbus with JWKS for RS256/ES256:
  // JwtDecoders.fromIssuerLocation("https://issuer.example") with a real IdP.
  @Bean
  JwtDecoder jwtDecoder() {
    var key = AuthController.KEY; // demo only
    return NimbusJwtDecoder.withSecretKey(key).build();
  }

  // Map "scope" claim (space-delimited) -> SCOPE_ authorities
  @Bean
  JwtAuthenticationConverter jwtAuthConverter() {
    var conv = new JwtGrantedAuthoritiesConverter();
    conv.setAuthorityPrefix("SCOPE_");
    conv.setAuthoritiesClaimName("scope");
    var wrapper = new JwtAuthenticationConverter();
    wrapper.setJwtGrantedAuthoritiesConverter(conv);
    return wrapper;
  }
}
```

### 3) Example API with method-level auth

```java
package demo.token;

import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/orders")
class OrdersController {

  @GetMapping
  @PreAuthorize("hasAuthority('SCOPE_orders.read')")
  public List<Map<String,Object>> list() {
    return List.of(Map.of("id","o-1","status","NEW"), Map.of("id","o-2","status","SHIPPED"));
  }

  @PostMapping
  @PreAuthorize("hasAuthority('SCOPE_orders.write')")
  public Map<String,Object> create(@RequestBody Map<String,Object> req) {
    return Map.of("id","o-3","status","NEW");
  }
}
```

**Try it (demo flow):**

1.  Issue a token:  
    `POST /auth/token?user=alice&scope=orders.read%20orders.write`

2.  Call API with header:  
    `Authorization: Bearer <access_token>`

3.  `GET /orders` works with `orders.read`; `POST /orders` requires `orders.write`.


---

## Opaque Token (Introspection) – Alternative Setup (outline)

-   Replace JWT decoder with:


```java
.oauth2ResourceServer(oauth -> oauth.opaqueToken(ot -> ot
  .introspectionUri("https://idp.example/oauth2/introspect")
  .introspectionClientCredentials("clientId","clientSecret")));
```

-   The API will call the IdP to verify each token; enables **instant revocation** and central policies.


---

## Known Uses

-   **OAuth2/OIDC** ecosystems (Auth0, Okta, Keycloak, AWS Cognito).

-   Public SaaS APIs (GitHub Apps, Stripe) and internal microservices adopting **JWT** for service-to-service auth.


---

## Related Patterns

-   **Authorization (RBAC/ABAC)** — apply roles/attributes after authentication.

-   **API Gateway / BFF** — commonly terminate/verify tokens at the edge.

-   **Rate Limiting** — per token/key quotas.

-   **Idempotency Key** — complements POST safety for authenticated clients.

-   **mTLS** — alternative/adjunct for service-to-service identity.

-   **Refresh Token Rotation** — secure renewal of short-lived access tokens.
