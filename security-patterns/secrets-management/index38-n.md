# Secrets Manager — Security Pattern

## Pattern Name and Classification

**Name:** Secrets Manager  
**Classification:** Security / Key & Secret Management / Confidential Computing — *Centralized issuance, storage, rotation, and access control for credentials, keys, and other sensitive configuration.*

---

## Intent

Centralize **creation, storage, distribution, rotation, and revocation** of secrets (API keys, DB passwords, TLS private keys, OAuth credentials, signing keys) so applications never hard-code or persist plaintext secrets locally and always retrieve the **minimum** they need **just-in-time**, with **auditability** and **policy enforcement**.

---

## Also Known As

-   Secret Store / Secret Vault
    
-   Key Vault (when also managing cryptographic keys)
    
-   KMS + Secrets (envelope encryption + metadata store)
    

---

## Motivation (Forces)

-   **Risk reduction:** Secrets in code, images, or logs get exfiltrated.
    
-   **Rotation & revocation:** Credentials must rotate without redeploying apps.
    
-   **Least privilege:** Scope access by identity, environment, tenant, path, IP, or device posture.
    
-   **Operational reliability:** Expiring credentials must be renewed proactively.
    
-   **Audit & compliance:** Who accessed which secret, when, and from where.
    
-   **Heterogeneity:** Multiple runtimes/clouds need a uniform abstraction.
    

Tensions: added network hop & availability dependency, rollout complexity, and the need for robust bootstrap (how apps authenticate to the vault).

---

## Applicability

Use a Secrets Manager when:

-   You manage **multiple services** that need secrets and keys.
    
-   You require **regular rotation**, **short-lived credentials**, or **dynamic secrets** (e.g., per-app DB users).
    
-   Compliance requires **central audit logs** and **access policies**.
    

Avoid or adapt when:

-   Truly **public** data (no secrecy needed).
    
-   **Offline/air-gapped** components with no path to an internal vault (then use hardware modules or pre-provisioned, short-lived tokens with strict handling).
    

---

## Structure

-   **Secure Storage (Vault):** encrypted at rest (HSM/KMS-wrapped master key), versioned secret entries, ACLs.
    
-   **Policy Engine (PDP):** evaluates requests (identity, path, scope, time, network).
    
-   **Authentication (Workload Identity):** app identities (mTLS certs, OIDC/JWT, cloud IAM) to obtain **session tokens**.
    
-   **Broker/Issuers:** dynamic secrets for DBs/Cloud IAM; PKI for short-lived certs.
    
-   **Client Library/Sidecar/Agent:** retrieves, caches, renews, and hot-reloads secrets.
    
-   **Audit Log:** immutable, tamper-evident logs for reads/writes/renewals.
    
-   **Rotation Pipelines:** rotate upstream credentials & update stored values atomically.
    

---

## Participants

-   **Producer (Ops/Sec/CI):** writes/rotates secrets, defines policies.
    
-   **Consumer (Application/Service):** reads secrets at runtime via client/agent.
    
-   **Vault/KMS/HSM:** stores ciphertext/material, enforces crypto operations.
    
-   **Identity Provider:** issues workload identities (SPIFFE/SPIRE, cloud IAM, OIDC).
    
-   **Auditor:** reviews access logs, anomalies, and rotation posture.
    

---

## Collaboration

1.  **Bootstrap:** Application authenticates to vault using **workload identity** (mTLS, OIDC, cloud IAM).
    
2.  **Authorize:** PDP evaluates policy; vault issues **short-lived token/lease**.
    
3.  **Fetch:** Client requests secret (`/app/db/password`), receives value (+metadata: version, TTL).
    
4.  **Cache & Renew:** Client caches in memory, **renews/rotates** before expiry, hot-reloads dependents.
    
5.  **Rotate/Update:** Ops rotates the upstream credential; vault updates the version; clients pick up new value.
    
6.  **Audit/Respond:** Access recorded; anomalous usage triggers alerts or revocation.
    

---

## Consequences

**Benefits**

-   Removes secrets from source code, images, and config files.
    
-   Enables **automatic rotation**, **dynamic** per-service credentials, and **least privilege**.
    
-   Central **audit trail** and policy control.
    

**Liabilities**

-   New dependency: vault availability and latency.
    
-   Bootstrap problem: securing the **first** identity/token.
    
-   Client complexity (caching, renewal, failure handling).
    
-   Potential blast radius if policies are too broad or audit disabled.
    

---

## Implementation

### Key Decisions

-   **Bootstrap identity:** mTLS (SPIFFE), cloud IAM (IRSA/Workload Identity), or OIDC JWT.
    
-   **Secret types:** static (API key) vs **dynamic** (per-lease DB users/certs).
    
-   **Lease & rotation:** TTLs, refresh-ahead thresholds, **reuse detection** on client tokens.
    
-   **Caching:** in-memory only; optional local **tmpfs** with strict perms; never on disk unencrypted.
    
-   **Hot reload:** signal (SIGHUP), file watchers, or live pool reconfiguration.
    
-   **Fail modes:** fail-closed by default; if allowed, **stale-while-revalidate** window with alerting.
    
-   **Observability:** metrics (hit/miss, renewal latency, failures), structured logs (no secret values).
    
-   **Defense in depth:** network policies, mTLS to vault, per-path policies, IP/ASN controls, and rate limits.
    
-   **Rotation runbooks:** upstream rotate → update vault → notify/validate → revoke old.
    

### Anti-Patterns

-   Storing secrets in **ENV vars**, code, or git; putting them in logs/trace metadata.
    
-   Long-lived vault tokens; no TTL or renewal.
    
-   Wide “`*`” policies (any app can read anything).
    
-   Writing secrets to local disk or container image layers.
    
-   Treating the vault as a generic KV without audits/ACLs.
    

### Practical Checklist

-   Adopt **workload identity** (no static bootstrap secrets).
    
-   Enforce **short TTL** client tokens; rotate secrets regularly.
    
-   Use **namespacing & least privilege** per app/env/tenant.
    
-   Build **backpressure** and **circuit breaking** to the vault; expose SLOs.
    
-   Integrate secret change **notifications** → reload dependent pools/certs.
    
-   Periodically **rekey** vault master and rotate KEKs; test disaster recovery.
    

---

## Sample Code (Java, JDK 17)

*A small, production-style client that fetches secrets over HTTPS, caches with TTL, proactively refreshes, and supports “stale-while-revalidate” with jittered backoff. The `HttpSecretsBackend` is a stand-in for a real vault (AWS/GCP/Azure/Vault); wire it to your provider’s API and auth (OIDC/mTLS).*

> Dependencies: none beyond the JDK (uses `java.net.http`)

```java
package com.example.secrets;

import java.net.URI;
import java.net.http.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Supplier;

public class SecretsManager implements AutoCloseable {

  public record SecretRecord(String value, Instant expiresAt, String version) {}

  public interface SecretsBackend {
    SecretRecord fetch(String name) throws Exception;
  }

  /** Policy knobs for cache & refresh. */
  public static final class Config {
    public Duration refreshAhead = Duration.ofMinutes(2);      // renew before TTL
    public Duration maxStale = Duration.ofMinutes(10);         // optional stale-while-revalidate
    public Duration minBackoff = Duration.ofMillis(200);
    public Duration maxBackoff = Duration.ofSeconds(5);
  }

  private static final class CacheEntry {
    final AtomicReference<SecretRecord> rec = new AtomicReference<>();
    final AtomicReference<Instant> nextRefresh = new AtomicReference<>(Instant.EPOCH);
    final AtomicReference<Boolean> refreshing = new AtomicReference<>(false);
  }

  private final Config cfg;
  private final SecretsBackend backend;
  private final ScheduledExecutorService sched = Executors.newSingleThreadScheduledExecutor(r -> {
    Thread t = new Thread(r, "secrets-refresh"); t.setDaemon(true); return t;
  });
  private final ConcurrentHashMap<String, CacheEntry> cache = new ConcurrentHashMap<>();

  public SecretsManager(Config cfg, SecretsBackend backend) {
    this.cfg = cfg; this.backend = backend;
  }

  /** Get a secret by name with TTL-aware caching and refresh-ahead. */
  public String getSecret(String name) {
    CacheEntry ce = cache.computeIfAbsent(name, k -> new CacheEntry());
    SecretRecord rec = ce.rec.get();

    if (rec == null) {
      rec = fetchFresh(name, ce); // first fetch; may throw
      return rec.value();
    }

    Instant now = Instant.now();
    // schedule refresh-ahead once we pass the threshold
    if (now.isAfter(rec.expiresAt().minus(cfg.refreshAhead))) {
      scheduleRefresh(name, ce);
    }

    // allow stale within maxStale
    if (now.isAfter(rec.expiresAt())) {
      if (now.isBefore(rec.expiresAt().plus(cfg.maxStale))) {
        // stale-but-serve to avoid outages; refresh already scheduled
        return rec.value();
      }
      // too stale -> block and fetch or fail
      rec = fetchFresh(name, ce);
    }
    return rec.value();
  }

  private void scheduleRefresh(String name, CacheEntry ce) {
    if (Boolean.TRUE.equals(ce.refreshing.get())) return;
    Instant due = ce.nextRefresh.get();
    Instant now = Instant.now();
    if (now.isBefore(due)) return;
    ce.refreshing.set(true);
    ce.nextRefresh.set(now.plusSeconds(2));

    sched.execute(() -> {
      long backoffMs = cfg.minBackoff.toMillis();
      for (int attempt = 0; attempt < 6; attempt++) {
        try {
          SecretRecord latest = backend.fetch(name);
          ce.rec.set(latest);
          break;
        } catch (Exception e) {
          try { Thread.sleep(ThreadLocalRandom.current().nextLong(backoffMs)); }
          catch (InterruptedException ie) { Thread.currentThread().interrupt(); }
          backoffMs = Math.min((long)(backoffMs * 2.0), cfg.maxBackoff.toMillis());
        }
      }
      ce.refreshing.set(false);
      ce.nextRefresh.set(Instant.now().plusSeconds(10 + ThreadLocalRandom.current().nextInt(10)));
    });
  }

  private SecretRecord fetchFresh(String name, CacheEntry ce) {
    try {
      SecretRecord latest = backend.fetch(name);
      ce.rec.set(latest);
      ce.nextRefresh.set(Instant.now().plusSeconds(10));
      return latest;
    } catch (RuntimeException re) { throw re; }
    catch (Exception e) { throw new RuntimeException("secret fetch failed for " + name, e); }
  }

  @Override public void close() { sched.shutdownNow(); }

  /* ---------------- Example HTTP backend (replace with your provider) ---------------- */

  public static final class HttpSecretsBackend implements SecretsBackend {
    private final HttpClient http;
    private final URI baseUri;
    private final Supplier<String> authHeaderSupplier; // e.g., "Bearer <sts token>"

    public HttpSecretsBackend(URI baseUri, Supplier<String> authHeaderSupplier, SSLContextProvider ssl) {
      this.baseUri = baseUri;
      this.authHeaderSupplier = authHeaderSupplier;
      this.http = HttpClient.newBuilder()
          .sslContext(ssl != null ? ssl.sslContext() : null)
          .version(HttpClient.Version.HTTP_2)
          .build();
    }

    @Override public SecretRecord fetch(String name) throws Exception {
      HttpRequest req = HttpRequest.newBuilder(baseUri.resolve("/v1/secrets/" + encode(name)))
          .header("Authorization", authHeaderSupplier.get())
          .header("Accept", "application/json")
          .GET().build();

      HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
      if (resp.statusCode() == 404) throw new NoSuchElementException("secret not found: " + name);
      if (resp.statusCode() / 100 != 2) throw new IllegalStateException("vault error: " + resp.statusCode());

      // Very small JSON parse (replace with Jackson/Gson)
      Map<String, String> m = parseJson(resp.body());
      String value = Objects.requireNonNull(m.get("value"));
      Instant exp = Optional.ofNullable(m.get("expiresAt"))
          .map(Instant::parse).orElse(Instant.now().plus(Duration.ofHours(1)));
      String version = Optional.ofNullable(m.get("version")).orElse("v1");
      return new SecretRecord(value, exp, version);
    }

    private static String encode(String s) { return java.net.URLEncoder.encode(s, java.nio.charset.StandardCharsets.UTF_8); }

    private static Map<String, String> parseJson(String s) {
      Map<String,String> out = new HashMap<>();
      s = s.trim().replaceAll("[{}\" ]","");
      for (String part : s.split(",")) {
        String[] kv = part.split(":",2);
        if (kv.length==2) out.put(kv[0], kv[1]);
      }
      return out;
    }
  }

  /** Optional SSL context provider for mTLS/pinning; stub for brevity. */
  public interface SSLContextProvider { javax.net.ssl.SSLContext sslContext(); }
}
```

**Usage (example wiring)**

```java
package com.example.secrets;

import java.net.URI;
import java.time.*;

public class Demo {
  public static void main(String[] args) {
    // Acquire a workload identity token outside (OIDC, STS, mTLS, etc.). Example: env var already populated
    var authSupplier = (java.util.function.Supplier<String>) () -> "Bearer " + System.getenv("WORKLOAD_ID_TOKEN");

    var backend = new SecretsManager.HttpSecretsBackend(
        URI.create("https://vault.internal.example"),
        authSupplier,
        null // provide mTLS/pinning if required
    );

    var cfg = new SecretsManager.Config();
    cfg.refreshAhead = Duration.ofMinutes(3);
    cfg.maxStale = Duration.ofMinutes(5);

    try (var sm = new SecretsManager(cfg, backend)) {
      // Retrieve a DB password (cached, auto-refreshed)
      String dbPass = sm.getSecret("prod/app1/database/password");
      System.out.println("Got DB password length: " + dbPass.length());

      // Later gets will be served from cache and refreshed ahead of TTL
      String apiKey = sm.getSecret("prod/app1/stripe/apiKey");
      System.out.println("Stripe key prefix: " + apiKey.substring(0, 6) + "****");
    }
  }
}
```

**Hardening notes for the sample**

-   Replace the toy JSON parser with a real one; never log secret values.
    
-   Supply an **SSLContext** that enforces **mTLS** and optional **SPKI pinning**.
    
-   Derive `Authorization` from a real **workload identity** (OIDC/JWT/mTLS) with short TTL.
    
-   If your provider returns **encrypted secrets**, decrypt in-process using **envelope encryption** with keys in KMS/HSM; keep plaintext in memory only.
    
-   Consider file-based **tmpfs** projection for libraries that require files (e.g., TLS key files); restrict perms and watch for changes to hot-reload.
    

---

## Known Uses

-   **Cloud key vaults** (AWS Secrets Manager, Azure Key Vault, GCP Secret Manager) providing rotation & IAM-based access.
    
-   **HashiCorp Vault** for dynamic DB users, PKI short-lived certs, transit encryption, and multi-cloud secret distribution.
    
-   **Service meshes** (SPIRE/istiod) issuing **mTLS** identities and rotating certs automatically.
    
-   **Kubernetes** with external secrets controllers syncing from a central vault (with namespaced RBAC).
    

---

## Related Patterns

-   **Key Management (KMS/HSM):** generate/wrap keys; vault may delegate crypto to KMS/HSM.
    
-   **Refresh Token / Short-Lived Credentials:** keep client auth to the vault short-lived.
    
-   **Principle of Least Privilege:** narrow policies per app/env/tenant/secret path.
    
-   **Encryption at Rest & In Transit:** vault storage and transport guarantees.
    
-   **Configuration as Data:** treat secret metadata and policies as versioned, declarative config.
    
-   **Audit Logging & Anomaly Detection:** monitor secret access patterns, geo/ASN, and rate spikes.
    

---

## Implementation Checklist

-   Use **workload identity** (no static bootstrap secrets).
    
-   Protect transport with **TLS 1.3** (consider **mTLS** + optional pinning).
    
-   Enforce **least privilege** policies per path/env/tenant; deny-by-default.
    
-   Prefer **dynamic/short-lived** secrets where possible; set sane TTLs and **refresh-ahead**.
    
-   Cache **in memory** only; support **hot reload** for DB pools/TLS certs.
    
-   Never log or expose secret values; scrub telemetry; emit **access metadata** only.
    
-   Rotate secrets on a schedule and after incidents; test recovery/DR and **break-glass** flows.
    
-   Alert on anomalies (repeated failures, new ASNs, unusual rate), and implement **rate limiting**.
    
-   Periodically **review policies**, remove unused secrets, and re-key master keys.

