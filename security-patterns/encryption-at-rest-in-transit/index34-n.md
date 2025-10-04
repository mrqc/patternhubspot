# Encryption at Rest & In Transit — Security Pattern

## Pattern Name and Classification

**Name:** Encryption at Rest & In Transit  
**Classification:** Security / Data Protection / Cryptography — *Confidentiality, integrity, and authenticity of data on disk and over the wire*

---

## Intent

Ensure that sensitive data is **unreadable to unauthorized parties** both **while stored** (at rest) and **while moving** between components (in transit). Use strong, modern cryptography, sound key management, and authenticated channels to prevent eavesdropping, tampering, or data theft.

---

## Also Known As

-   Data-at-Rest Encryption (DaRE) & Data-in-Transit Encryption (DiTE)
    
-   End-to-End Encryption (E2EE) *(when keys never leave endpoints)*
    
-   TLS Everywhere + Envelope Encryption
    

---

## Motivation (Forces)

-   **Threats at rest:** disk theft, snapshot exfiltration, insider misuse, backup/media loss.
    
-   **Threats in transit:** on-path attackers, TLS downgrade, misissued certs, proxy interception.
    
-   **Compliance:** GDPR, HIPAA, PCI-DSS, ISO 27001 expect encryption + key lifecycle controls.
    
-   **Zero trust:** networks and platforms are assumed hostile; crypto becomes the contract boundary.
    
-   **Operational realities:** keys must rotate, be auditable, and survive incidents; performance must remain acceptable.
    

Trade-offs include performance overhead, operational complexity (keys, rotation, HSM/KMS), and failure modes if keys are unavailable.

---

## Applicability

Use this pattern when:

-   You persist PII/PHI/PCI, secrets, or proprietary code/data.
    
-   Services communicate over networks you **don’t fully control** (LAN/VPN/public internet).
    
-   You must **reduce breach blast radius** and meet regulatory requirements.
    

Avoid or adapt when:

-   Data is **public** and integrity alone suffices → use signing only.
    
-   You require **lawful inspection**/IDS: pair TLS with sanctioned termination points and explicit controls.
    
-   Ultra-low latency links with hardware encryptors are available (specialized environments).
    

---

## Structure

-   **At Rest:**
    
    -   **Envelope Encryption:** Random per-object **Data Encryption Key (DEK)** (AES-GCM), wrapped by a **Key Encryption Key (KEK)** in KMS/HSM.
        
    -   **Transparent encryption:** volume/table/column-level solutions (LUKS, TDE) for coarse coverage.
        
    -   **Backups/Snapshots** encrypted with independent keys/policies.
        
-   **In Transit:**
    
    -   **TLS 1.2+ (prefer 1.3):** strong cipher suites, certificate validation, ALPN, HSTS.
        
    -   **Mutual TLS (mTLS):** both sides authenticate with X.509 where needed.
        
    -   **Certificate Pinning:** optional defense against rogue CAs for high-value clients.
        
-   **Key Management:** rotation, revocation, usage boundaries, access control, audit.
    
-   **Observability:** crypto errors, TLS versions, cipher suites, cert expiry, KMS usage.
    

---

## Participants

-   **KMS/HSM:** generates and protects KEKs; wraps/unwraps DEKs; enforces policies.
    
-   **Crypto Library:** AES-GCM for confidentiality+integrity; X.509/TLS stack.
    
-   **Application:** requests DEKs, encrypts/decrypts payloads, talks over TLS/mTLS.
    
-   **Certificate Authority (CA):** issues/verifies cert chains.
    
-   **Secrets Store:** holds client certs, private keys, and API credentials securely.
    
-   **Audit/SIEM:** records key usage, TLS failures, rotation events.
    

---

## Collaboration

1.  **At Rest (write):** App asks KMS for a new DEK → encrypts data with AES-GCM (+AAD) → stores ciphertext + wrapped DEK + IV (+ metadata).
    
2.  **At Rest (read):** App unwraps DEK via KMS → decrypts AES-GCM → verifies tag; returns plaintext.
    
3.  **In Transit:** Client and server negotiate **TLS 1.3**, validate certificates; optionally perform **mTLS** and/or **pin server SPKI**; data is exchanged over the authenticated, encrypted channel.
    
4.  **Lifecycle:** Keys/certs rotate before expiry; old items phased out; audits emitted.
    

---

## Consequences

**Benefits**

-   Confidentiality and integrity against storage and network attackers.
    
-   Limits breach impact (per-object DEKs; compromised disk ≠ plaintext).
    
-   Satisfies regulatory controls; enables zero-trust postures.
    

**Liabilities**

-   Crypto adds **latency/CPU**; requires careful tuning (AES-NI, offload).
    
-   **Key unavailability** can make data unreadable; design HA for KMS.
    
-   Operational complexity: rotation, revocation, inventory, and incident playbooks.
    

---

## Implementation

### Key Decisions

-   **Algorithms:** AES-256-GCM for data, RSA-OAEP/ECIES/KMS-wrap for DEKs, TLS 1.3 with AEAD suites (e.g., `TLS_AES_128_GCM_SHA256`).
    
-   **Granularity:** Per-record/object DEKs (max isolation) vs file/volume encryption (simplicity).
    
-   **AAD (Additional Authenticated Data):** Bind ciphertext to context (tenantId, schema version) to detect mixups.
    
-   **Rotation:** Short-lived DEKs (per object), KEKs rotated on schedule; dual-KEK windows support rolling re-wrap.
    
-   **mTLS scope:** Service-to-service, admin APIs, data plane? Keep a **clear matrix**.
    
-   **Pinning:** For mobile/edge/high-risk clients; pin **SPKI SHA-256** and support **pin roll**.
    
-   **Fail-closed vs fail-open:** Crypto/tls failures generally **fail-closed**; provide controlled maintenance bypass only with explicit break-glass.
    

### Anti-Patterns

-   Homegrown crypto or deprecated primitives (ECB, CBC without AEAD, MD5/SHA-1, RC4).
    
-   Long-lived static keys stored with data or in code.
    
-   Accepting any certificate or disabling hostname verification.
    
-   Reusing IVs with GCM; omitting AAD when context is available.
    
-   Using JWTs/opaque tokens without TLS (bearers leak).
    

---

## Sample Code (Java)

Below are two cohesive snippets:

-   **A)** Envelope encryption for *at rest* (AES-GCM + RSA-OAEP wrapping, easily swapped for KMS).
    
-   **B)** HTTPS client with **TLS 1.3**, **SPKI pinning**, and optional **mTLS** for *in transit*.
    

> These are reference examples. In production, prefer a managed **KMS**, a vetted TLS stack, and secrets from a secure store.

### A) Envelope Encryption (AES-GCM + RSA-OAEP)

```java
// EnvelopeCrypto.java
package com.example.crypto;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.security.*;
import java.security.spec.MGF1ParameterSpec;
import java.security.spec.PSSParameterSpec;
import javax.crypto.spec.OAEPParameterSpec;
import javax.crypto.spec.PSource;
import java.util.Base64;
import java.util.Map;

public class EnvelopeCrypto {

  public static final int AES_KEY_BITS = 256;
  public static final int GCM_TAG_BITS = 128;
  public static final int GCM_IV_BYTES = 12;

  public static record Envelope(String alg, String kid, String ivB64, String dekWrappedB64,
                                String aadB64, String ciphertextB64) {}

  /** Encrypts plaintext with a fresh AES-GCM DEK; wraps DEK with RSA-OAEP (kept in KMS/HSM in real life). */
  public static Envelope encrypt(byte[] plaintext, Map<String, String> aadHeaders,
                                PublicKey wrappingKey, String keyId, SecureRandom rng) throws Exception {
    // 1) Generate a data key (DEK)
    KeyGenerator kg = KeyGenerator.getInstance("AES");
    kg.init(AES_KEY_BITS, rng);
    SecretKey dek = kg.generateKey();

    // 2) AES-GCM encrypt
    byte[] iv = new byte[GCM_IV_BYTES]; rng.nextBytes(iv);
    Cipher gcm = Cipher.getInstance("AES/GCM/NoPadding");
    GCMParameterSpec spec = new GCMParameterSpec(GCM_TAG_BITS, iv);
    gcm.init(Cipher.ENCRYPT_MODE, dek, spec);
    byte[] aad = serializeAad(aadHeaders);
    if (aad != null) gcm.updateAAD(aad);
    byte[] ct = gcm.doFinal(plaintext);

    // 3) Wrap DEK with RSA-OAEP(SHA-256)
    Cipher wrap = Cipher.getInstance("RSA/ECB/OAEPWithSHA-256AndMGF1Padding");
    OAEPParameterSpec oaep = new OAEPParameterSpec("SHA-256", "MGF1",
        MGF1ParameterSpec.SHA256, PSource.PSpecified.DEFAULT);
    wrap.init(Cipher.WRAP_MODE, wrappingKey, oaep);
    byte[] dekWrapped = wrap.wrap(dek);

    return new Envelope(
        "AES256-GCM+RSAOAEP256",
        keyId,
        b64(iv),
        b64(dekWrapped),
        b64(aad),
        b64(ct)
    );
  }

  /** Decrypts an envelope using RSA private key to unwrap DEK, then AES-GCM to decrypt. */
  public static byte[] decrypt(Envelope env, PrivateKey unwrappingKey) throws Exception {
    // 1) Unwrap DEK
    Cipher unwrap = Cipher.getInstance("RSA/ECB/OAEPWithSHA-256AndMGF1Padding");
    OAEPParameterSpec oaep = new OAEPParameterSpec("SHA-256", "MGF1",
        MGF1ParameterSpec.SHA256, PSource.PSpecified.DEFAULT);
    unwrap.init(Cipher.UNWRAP_MODE, unwrappingKey, oaep);
    Key dek = unwrap.unwrap(b64d(env.dekWrappedB64()), "AES", Cipher.SECRET_KEY);

    // 2) AES-GCM decrypt
    Cipher gcm = Cipher.getInstance("AES/GCM/NoPadding");
    GCMParameterSpec spec = new GCMParameterSpec(GCM_TAG_BITS, b64d(env.ivB64()));
    gcm.init(Cipher.DECRYPT_MODE, (SecretKey) dek, spec);
    byte[] aad = b64dOrNull(env.aadB64());
    if (aad != null) gcm.updateAAD(aad);
    return gcm.doFinal(b64d(env.ciphertextB64()));
  }

  private static String b64(byte[] b){ return Base64.getEncoder().encodeToString(b); }
  private static byte[] b64d(String s){ return Base64.getDecoder().decode(s); }
  private static byte[] b64dOrNull(String s){ return s==null? null : b64d(s); }

  private static byte[] serializeAad(Map<String,String> m) {
    if (m == null || m.isEmpty()) return null;
    // Simple, deterministic `k=v` joined with `;` as AAD. In prod use canonical JSON.
    StringBuilder sb = new StringBuilder();
    m.entrySet().stream().sorted(Map.Entry.comparingByKey())
        .forEach(e -> sb.append(e.getKey()).append('=').append(e.getValue()).append(';'));
    return sb.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8);
  }
}
```

**Usage sketch**

```java
// ExampleMain.java (envelope encryption usage)
import com.example.crypto.EnvelopeCrypto;
import java.security.*;
import java.util.Map;

public class ExampleMain {
  public static void main(String[] args) throws Exception {
    // Load/generate RSA 3072-bit keypair (simulate KMS; in prod, delegate wrap/unwrap to KMS/HSM)
    KeyPairGenerator kpg = KeyPairGenerator.getInstance("RSA");
    kpg.initialize(3072);
    KeyPair kp = kpg.generateKeyPair();

    byte[] plaintext = "tenant=acme;secret=super-confidential".getBytes();
    var aad = Map.of("tenantId","acme","schema","v1");

    var env = EnvelopeCrypto.encrypt(plaintext, aad, kp.getPublic(), "kek-2025-10", new SecureRandom());
    byte[] decrypted = EnvelopeCrypto.decrypt(env, kp.getPrivate());

    System.out.println(new String(decrypted)); // sanity check
    // Store env.ivB64, env.dekWrappedB64, env.ciphertextB64, env.kid with the record.
  }
}
```

### B) HTTPS Client with TLS 1.3, SPKI Pinning, and optional mTLS

```java
// PinnedHttpClient.java
package com.example.tls;

import javax.net.ssl.*;
import java.net.URI;
import java.net.http.*;
import java.security.*;
import java.security.cert.*;
import java.security.interfaces.RSAPublicKey;
import java.util.Base64;
import java.util.List;

public class PinnedHttpClient {

  /** SHA-256 of server certificate's SPKI (Subject Public Key Info). Example pin string from deployment. */
  private final String expectedSpkiSha256B64;
  private final SSLContext sslContext;

  /** Build an HttpClient that performs SPKI pinning and (optionally) mTLS with a client KeyStore. */
  public PinnedHttpClient(String expectedSpkiSha256B64, KeyManager[] clientKeyManagers) throws Exception {
    this.expectedSpkiSha256B64 = expectedSpkiSha256B64;

    TrustManager tm = new X509TrustManager() {
      private final X509TrustManager defaultTm = defaultTrustManager();

      @Override public void checkClientTrusted(X509Certificate[] chain, String authType) throws CertificateException {
        defaultTm.checkClientTrusted(chain, authType);
      }

      @Override public void checkServerTrusted(X509Certificate[] chain, String authType) throws CertificateException {
        // 1) Standard PKI validation
        defaultTm.checkServerTrusted(chain, authType);
        // 2) Pin SPKI of leaf (or set of allowed pins)
        X509Certificate leaf = chain[0];
        String pin = spkiSha256B64(leaf);
        if (!pin.equals(expectedSpkiSha256B64)) {
          throw new CertificateException("SPKI pin mismatch");
        }
      }

      @Override public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
    };

    this.sslContext = SSLContext.getInstance("TLS");
    this.sslContext.init(clientKeyManagers, new TrustManager[]{ tm }, new SecureRandom());
  }

  public HttpResponse<String> get(String url) throws Exception {
    HttpClient client = HttpClient.newBuilder()
        .sslContext(sslContext)
        .version(HttpClient.Version.HTTP_2)
        .build();
    HttpRequest req = HttpRequest.newBuilder(URI.create(url))
        .header("Accept","application/json")
        .GET()
        .build();
    return client.send(req, HttpResponse.BodyHandlers.ofString());
  }

  private static X509TrustManager defaultTrustManager() {
    try {
      TrustManagerFactory tmf = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
      tmf.init((KeyStore) null);
      for (TrustManager tm : tmf.getTrustManagers()) if (tm instanceof X509TrustManager xtm) return xtm;
      throw new IllegalStateException("No default X509TrustManager");
    } catch (Exception e) { throw new RuntimeException(e); }
  }

  private static String spkiSha256B64(X509Certificate cert) throws CertificateException {
    try {
      // Extract the SubjectPublicKeyInfo bytes and hash
      byte[] spki = cert.getPublicKey().getEncoded();
      MessageDigest sha256 = MessageDigest.getInstance("SHA-256");
      byte[] digest = sha256.digest(spki);
      return Base64.getEncoder().encodeToString(digest);
    } catch (NoSuchAlgorithmException e) {
      throw new CertificateException("SHA-256 not available", e);
    }
  }

  /** Utility: build KeyManagers for mTLS from a client PKCS#12 keystore. */
  public static KeyManager[] keyManagersFromPkcs12(byte[] pkcs12Bytes, String password) throws Exception {
    KeyStore ks = KeyStore.getInstance("PKCS12");
    ks.load(new java.io.ByteArrayInputStream(pkcs12Bytes), password.toCharArray());
    KeyManagerFactory kmf = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm());
    kmf.init(ks, password.toCharArray());
    return kmf.getKeyManagers();
  }
}
```

**Usage sketch**

```java
// TlsDemo.java
import com.example.tls.PinnedHttpClient;

public class TlsDemo {
  public static void main(String[] args) throws Exception {
    // Precomputed SPKI pin (base64 of SHA-256 over server cert public key)
    String pin = "m0rXv3xgE3kX3Jm0o6sd4j2m0J8yq3K6WZrPI2a8vGk=";

    // If mTLS required, load client PKCS#12 from secure store; else pass null
    PinnedHttpClient client = new PinnedHttpClient(pin, null);
    var resp = client.get("https://api.example.com/secure");
    System.out.println(resp.statusCode());
    System.out.println(resp.body());
  }
}
```

> Notes:
> 
> -   This client still uses the platform trust store **and** enforces SPKI pinning for the leaf certificate.
>     
> -   To support **pin rotation**, allow a set of valid pins and retire old pins after a grace period.
>     
> -   For servers, enable TLS 1.3, disable legacy/downgrade ciphers, provide **OCSP stapling**, and set **HSTS**.
>     

---

## Known Uses

-   **Cloud providers & managed DBs:** default at-rest encryption with KMS and TLS-only endpoints.
    
-   **Payment systems:** envelope encryption for PANs; TLS 1.3 with mTLS for processor links.
    
-   **Healthcare:** PHI stored with per-record DEKs; all APIs require TLS + mTLS inside private networks.
    
-   **Mobile apps:** SPKI pinning for high-risk endpoints; rotating pins with staged releases.
    
-   **SaaS multi-tenant:** AAD binds ciphertext to **tenantId** to prevent cross-tenant misuse.
    

---

## Related Patterns

-   **Key Management / Secrets Management:** lifecycle for keys, rotation, custody, auditing.
    
-   **Data Masking:** complements encryption by limiting exposure in views/logs.
    
-   **Tokenization:** replaces sensitive values; stored tokens *also* require TLS.
    
-   **Hardware-backed Attestation / Secure Enclaves:** stronger protection for keys in use.
    
-   **Circuit Breaker / Rate Limiting:** guard encrypted channels against abuse and downgrade attempts.
    

---

## Implementation Checklist

-   Use **AES-GCM** (or ChaCha20-Poly1305) with **unique IVs**; include **AAD** (tenant, schema, purpose).
    
-   Adopt **envelope encryption**: per-object DEKs, wrapped by KEKs in **KMS/HSM**; rotate KEKs regularly.
    
-   Encrypt **backups/snapshots** with independent policies; test restore paths.
    
-   Enforce **TLS 1.3**; disable weak ciphers; verify hostnames; consider **mTLS** for service traffic.
    
-   For clients, consider **SPKI pinning** with planned **pin rotation**.
    
-   Centralize **key & cert inventory**; set alerts for **expiry** and **KMS errors**.
    
-   Build **break-glass** procedures (documented), but default to **fail-closed**.
    
-   Load test crypto hot paths; enable **AES-NI**; size CPU appropriately.
    
-   Periodically **re-encrypt** legacy data and retire deprecated algorithms.

