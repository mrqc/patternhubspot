# Secure Audit Trail — Security Pattern

## Pattern Name and Classification

**Name:** Secure Audit Trail  
**Classification:** Security / Monitoring & Forensics / Non-Repudiation — *Tamper-evident, append-only logging with integrity, authenticity, ordering, and reliable retention.*

---

## Intent

Record **who did what, when, from where, and why** in a way that is **append-only** and **tamper-evident**, so security teams and auditors can **reconstruct events**, **prove integrity**, and **attribute actions**—even under partial compromise.

---

## Also Known As

-   Tamper-Evident Logging
    
-   Forensic Audit Log / Immutable Log
    
-   Chain-Hashed / Signed Logs
    
-   WORM (Write Once Read Many) Logging
    

---

## Motivation (Forces)

-   **Forensics & non-repudiation:** You must trust logs during incident response and legal discovery.
    
-   **Adversarial environment:** Attackers try to delete/alter logs or disable logging.
    
-   **Distributed systems:** Many services generate events concurrently; ordering and clock skew complicate analysis.
    
-   **Compliance:** PCI-DSS, SOX, ISO 27001, HIPAA, GDPR accountability & traceability.
    
-   **Practicality:** Storage must be scalable and affordable; queries must be fast; PII exposure must be minimized.
    

**Tensions:** Retention vs. privacy (right to erasure), integrity vs. availability (fsync/latency), centralization vs. survivability, and simplicity vs. cryptographic strength.

---

## Applicability

Use this pattern when:

-   You need **provable integrity** of security-relevant events (auth, privilege changes, data access, configuration).
    
-   Your threat model includes **insider risk** or **post-exploitation log tampering**.
    
-   You are subject to **regulatory** or **contractual** logging requirements.
    

Avoid or adapt when:

-   Data is **not security-relevant** and operational metrics suffice.
    
-   Strict **personal data minimization** prohibits storing specific fields; then log **hashes/pseudonyms** and keep raw data elsewhere with access controls.
    

---

## Structure

-   **Event Producer(s):** Applications, gateways, databases, OS, IAM, CI/CD, admin tools.
    
-   **Audit Envelope:** Standardized fields (actor, action, resource, subject/tenant, reason, time, IP/ASN, outcome, correlation id).
    
-   **Sequencer:** Assigns **monotonic sequence** within a stream/partition.
    
-   **Integrity Layer:**
    
    -   **Hash chain** (each entry binds previous hash) and/or **Merkle trees**.
        
    -   **Digital signatures** (service keys or centralized signer/HSM).
        
    -   **Trusted timestamping** (RFC 3161 / time attestation).
        
-   **Transport:** Authenticated, reliable (e.g., TLS syslog, message bus with mTLS + authorization).
    
-   **Immutable Store:** WORM/S3 Object Lock/append-only FS; cross-region replicated.
    
-   **Anchor/Checkpoint:** Periodic publication of log roots to a **separate trust domain** (e.g., other cloud/account, blockchain, notary).
    
-   **Verification Tooling:** Replays chain, verifies signatures & anchors.
    
-   **Access & Analytics:** SIEM/warehouse with RBAC, masking, retention & legal holds.
    

---

## Participants

-   **Audit Client (Library/Agent):** Builds envelopes, signs/links entries, ships them.
    
-   **Signer / KMS/HSM:** Holds private keys; rotates and attests provenance.
    
-   **Collector / Ingest Tier:** Buffers, validates format, rate-limits, enriches with context.
    
-   **Immutable Storage:** Durable append-only store with lifecycle rules.
    
-   **Verifier / Auditor:** Validates integrity and investigates.
    
-   **DLP/Privacy Controls:** Mask/redact sensitive fields; enforce retention & access.
    

---

## Collaboration

1.  **Event creation:** Producer emits an envelope with **minimal PII**, standardized fields, and a **monotonic sequence** (per stream).
    
2.  **Link & sign:** Client computes `entryHash = H(seq || ts || prevHash || event)` and signs it; stores `prevHash` to form a **hash chain**.
    
3.  **Ship & persist:** Send over **TLS/mTLS** to the collector; append to **immutable** storage; optionally index for search.
    
4.  **Checkpoint:** Periodically publish the **tip hash**/Merkle root to a separate trust domain (anchor).
    
5.  **Verify:** Auditor replays chain, verifies signatures, confirms **anchors**, and correlates events across services.
    

---

## Consequences

**Benefits**

-   **Tamper-evident**: modifications break the chain/signature.
    
-   **Attribution**: signatures bind events to identities/keys.
    
-   **Forensic quality**: ordered, normalized, and anchored.
    
-   **Compliance ready**: retention, integrity, and access logs.
    

**Liabilities**

-   **Latency/overhead** from fsync/signing.
    
-   **Key management complexity** (rotation, HSM/KMS, compromise response).
    
-   **Privacy**: logs can become a liability if PII is excessive.
    
-   **Operational dependency** on collectors/storage (design for backpressure & fallback).
    

---

## Implementation

### Key Decisions

-   **Envelope schema**: versioned, minimal PII, include *actor, action, resource, subject, tenant, ts, ip, result, reason, correlationId*.
    
-   **Partitioning & sequence**: single-writer per partition (service/tenant/region) for monotonic `seq`; add `streamId`.
    
-   **Integrity construct**:
    
    -   Hash chain for each partition; optional **Merkle root** per batch/day.
        
    -   **Digital signature** per entry (Ed25519/ECDSA P-256) or per batch.
        
-   **Time**: Record **wall clock** + **monotonic tick**; consider **trusted timestamps** for strong proofs.
    
-   **Anchoring**: Publish periodic roots (e.g., hourly) to an **independent** destination (other cloud/account or public ledger).
    
-   **Storage**: Append-only objects with **Object Lock/WORM**; lifecycle to cold storage; cross-region.
    
-   **Key management**: HSM/KMS-protected keys, **rotation schedule**, key identifiers in entries, compromise playbooks.
    
-   **Backpressure**: Local disk queue with **spill-to-disk**; drop non-critical fields, never drop critical events silently.
    
-   **Privacy & access**: Mask PII where possible, **role-based access**, retention & deletion workflows.
    

### Anti-Patterns

-   Logs that can be **rewritten** (mutable indices) without external anchors.
    
-   **Unsigned** logs or shared keys with unclear provenance.
    
-   Storing **secrets** or excessive PII/raw payloads in audit logs.
    
-   Relying on **client clocks** only; no sequence; no correlation ids.
    
-   Disabling logging on errors/backpressure.
    

### Practical Checklist

-   Define **schema & taxonomy**; publish a contract.
    
-   Implement **hash chain + signatures**; store `prevHash`.
    
-   Use **TLS/mTLS** end-to-end; authenticate producers.
    
-   Write to **append-only/WORM**; enable lifecycle & replication.
    
-   **Anchor** per interval; store anchors out-of-band.
    
-   Build a **verifier** tool and run it continuously; alert on gaps.
    
-   Rotate signer keys; preserve public keys & **key history**.
    
-   Minimize PII; apply **data masking** and retention policies.
    

---

## Sample Code (Java, JDK 17): Append-Only, Tamper-Evident Audit Log

**What it shows**

-   Event envelope → **hash-chained** entry (`prevHash` + `seq` + `ts`).
    
-   **ECDSA P-256** signature over `entryHash`.
    
-   Append-only **line format** (`|`\-delimited, Base64 components) with **fsync**.
    
-   **Verification** routine that replays the chain and validates signatures.
    

> No external dependencies.

```java
package com.example.auditing;

import java.io.*;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.*;
import java.security.interfaces.ECPublicKey;
import java.time.Instant;
import java.util.*;
import java.util.Base64;

public final class SecureAuditLog implements AutoCloseable {

  public static final class AuditEvent {
    public final String streamId;     // e.g., "orders-eu-1"
    public final String actor;        // "user:123" or "svc:checkout"
    public final String action;       // "ORDER_CREATE", "ROLE_UPDATE"
    public final String resource;     // "order:abc123", "role:admin"
    public final String tenant;       // "acme"
    public final String result;       // "SUCCESS" | "DENY" | "ERROR"
    public final String ip;           // optional
    public final String reason;       // optional, brief
    public final String correlationId;// trace/span id, optional
    public final Map<String,String> attrs; // extra small fields (non-PII ideally)

    public AuditEvent(String streamId, String actor, String action, String resource,
                      String tenant, String result, String ip, String reason,
                      String correlationId, Map<String,String> attrs) {
      this.streamId = streamId; this.actor = actor; this.action = action; this.resource = resource;
      this.tenant = tenant; this.result = result; this.ip = ip; this.reason = reason;
      this.correlationId = correlationId; this.attrs = attrs == null ? Map.of() : Map.copyOf(attrs);
    }

    /** Stable, minimal JSON without external libs (keys sorted). */
    public String toStableJson() {
      StringBuilder sb = new StringBuilder();
      sb.append('{');
      put(sb, "v","1"); sb.append(',');
      put(sb, "streamId", streamId); sb.append(',');
      put(sb, "actor", actor); sb.append(',');
      put(sb, "action", action); sb.append(',');
      put(sb, "resource", resource); sb.append(',');
      put(sb, "tenant", tenant); sb.append(',');
      put(sb, "result", result); sb.append(',');
      put(sb, "ip", ip); sb.append(',');
      put(sb, "reason", reason); sb.append(',');
      put(sb, "correlationId", correlationId); sb.append(',');
      // attrs as sorted k=v map
      sb.append("\"attrs\":{");
      boolean first = true;
      for (String k : new TreeSet<>(attrs.keySet())) {
        if (!first) sb.append(',');
        put(sb, k, attrs.get(k));
        first = false;
      }
      sb.append("}}");
      return sb.toString();
    }
    private static void put(StringBuilder sb, String k, String v) {
      sb.append('"').append(esc(k)).append('"').append(':');
      if (v == null) sb.append("null");
      else sb.append('"').append(esc(v)).append('"');
    }
    private static String esc(String s){ return s.replace("\\","\\\\").replace("\"","\\\""); }
  }

  /** On-disk record layout (one line, '|' delimited, base64 fields where needed):
   * seq|tsEpochMillis|streamId|prevHashB64|eventJsonB64|entryHashB64|keyId|sigB64
   */
  private final Path file;
  private final String keyId;
  private final PrivateKey signingKey;
  private final PublicKey verifyKey;

  private long seq;               // monotonic within this stream/file
  private byte[] prevHash = new byte[32]; // 32 zero bytes for genesis
  private FileChannel channel;

  public SecureAuditLog(Path file, String keyId, KeyPair signer) throws IOException {
    this.file = file;
    this.keyId = Objects.requireNonNull(keyId);
    this.signingKey = Objects.requireNonNull(signer.getPrivate());
    this.verifyKey = Objects.requireNonNull(signer.getPublic());
    openAndRecover();
  }

  /** Append one audit event. Thread-safe for a single process; coordinate multi-writers upstream. */
  public synchronized void append(AuditEvent ev) {
    try {
      long ts = Instant.now().toEpochMilli();
      long mySeq = ++seq;
      String json = ev.toStableJson();

      byte[] entryHash = computeEntryHash(mySeq, ts, prevHash, json.getBytes(StandardCharsets.UTF_8));
      byte[] sig = sign(entryHash);

      String line = String.join("|",
          Long.toString(mySeq),
          Long.toString(ts),
          safe(ev.streamId),
          b64(prevHash),
          b64(json.getBytes(StandardCharsets.UTF_8)),
          b64(entryHash),
          safe(keyId),
          b64(sig)
      ) + "\n";

      ByteBuffer buf = ByteBuffer.wrap(line.getBytes(StandardCharsets.UTF_8));
      channel.write(buf);
      channel.force(true);                 // fsync the data + metadata
      prevHash = entryHash;               // advance the chain tip
    } catch (Exception e) {
      throw new RuntimeException("audit append failed", e);
    }
  }

  /** Verify the entire file: hash chain and ECDSA signatures. Returns tip hash (for anchoring). */
  public static VerificationResult verify(Path file, PublicKey key) throws Exception {
    try (BufferedReader br = Files.newBufferedReader(file, StandardCharsets.UTF_8)) {
      String line; long lastSeq = 0; byte[] expectedPrev = new byte[32]; byte[] tip = expectedPrev;
      Signature verifier = Signature.getInstance("SHA256withECDSA");
      verifier.initVerify(key);

      while ((line = br.readLine()) != null) {
        String[] parts = line.split("\\|", -1);
        if (parts.length != 8) throw new IllegalStateException("bad record: " + line);
        long seq = Long.parseLong(parts[0]);
        long ts = Long.parseLong(parts[1]);
        String streamId = parts[2];
        byte[] prevHash = b64d(parts[3]);
        byte[] eventJson = b64d(parts[4]);
        byte[] entryHash = b64d(parts[5]);
        String keyId = parts[6];
        byte[] sig = b64d(parts[7]);

        if (seq != lastSeq + 1) throw new IllegalStateException("non-monotonic seq at " + seq);
        if (!Arrays.equals(prevHash, expectedPrev)) throw new IllegalStateException("prevHash mismatch at " + seq);

        byte[] recomputed = computeEntryHashStatic(seq, ts, prevHash, eventJson);
        if (!Arrays.equals(recomputed, entryHash)) throw new IllegalStateException("hash mismatch at " + seq);

        verifier.update(recomputed);
        if (!verifier.verify(sig)) throw new IllegalStateException("signature invalid at " + seq);

        lastSeq = seq;
        expectedPrev = entryHash;
        tip = entryHash;
      }
      return new VerificationResult(lastSeq, tip);
    }
  }

  public record VerificationResult(long lastSeq, byte[] tipHash) {}

  /* ---------------- internals ---------------- */

  private void openAndRecover() throws IOException {
    Files.createDirectories(file.getParent());
    boolean exists = Files.exists(file);
    channel = FileChannel.open(file, StandardOpenOption.CREATE, StandardOpenOption.WRITE, StandardOpenOption.APPEND);
    if (!exists) { seq = 0; prevHash = new byte[32]; return; }

    // Read last line to recover seq and prevHash
    try (RandomAccessFile raf = new RandomAccessFile(file.toFile(), "r")) {
      long len = raf.length();
      if (len == 0) { seq = 0; prevHash = new byte[32]; return; }
      long pos = len - 1;
      int c;
      while (pos > 0 && (c = raf.read()) != '\n') { pos--; raf.seek(pos); }
      String last = raf.readLine();
      if (last == null || last.isEmpty()) { seq = 0; prevHash = new byte[32]; return; }
      String[] parts = last.split("\\|", -1);
      seq = Long.parseLong(parts[0]);
      prevHash = b64d(parts[5]); // entryHash of last record
    } catch (Exception e) {
      // If recovery fails, do not continue silently
      throw new IOException("failed to recover audit log state", e);
    }
  }

  private static String safe(String s) {
    if (s == null) return "";
    if (s.contains("|") || s.contains("\n")) throw new IllegalArgumentException("invalid char in field");
    return s;
  }

  private static byte[] computeEntryHash(long seq, long ts, byte[] prevHash, byte[] event) throws Exception {
    return computeEntryHashStatic(seq, ts, prevHash, event);
  }

  private static byte[] computeEntryHashStatic(long seq, long ts, byte[] prevHash, byte[] event) throws Exception {
    MessageDigest md = MessageDigest.getInstance("SHA-256");
    ByteBuffer buf = ByteBuffer.allocate(8 + 8 + prevHash.length + event.length);
    buf.putLong(seq);
    buf.putLong(ts);
    buf.put(prevHash);
    buf.put(event);
    return md.digest(buf.array());
  }

  private byte[] sign(byte[] data) throws Exception {
    Signature s = Signature.getInstance("SHA256withECDSA");
    s.initSign(signingKey);
    s.update(data);
    return s.sign();
  }

  private static String b64(byte[] b){ return Base64.getEncoder().encodeToString(b); }
  private static byte[] b64d(String s){ return Base64.getDecoder().decode(s); }

  @Override public void close() throws IOException { if (channel != null) channel.close(); }

  /* ------------------- demo ------------------- */

  public static void main(String[] args) throws Exception {
    // 1) Generate a signer (use KMS/HSM in production), assign a keyId
    KeyPairGenerator kpg = KeyPairGenerator.getInstance("EC");
    kpg.initialize(256);
    KeyPair kp = kpg.generateKeyPair();
    String keyId = "ecdsa-p256-2025-10";

    // 2) Open log and append a few events
    Path path = Paths.get("audit/audit-stream-orders.log");
    try (SecureAuditLog log = new SecureAuditLog(path, keyId, kp)) {
      log.append(new AuditEvent("orders-eu-1", "user:alice", "ORDER_CREATE", "order:abc123",
          "acme", "SUCCESS", "203.0.113.10", null, "trace-1", Map.of("amount","1999","currency","EUR")));
      log.append(new AuditEvent("orders-eu-1", "svc:billing", "PAYMENT_CAPTURE", "order:abc123",
          "acme", "SUCCESS", null, null, "trace-1", Map.of("provider","stripe")));
    }

    // 3) Verify full chain & signature
    VerificationResult vr = verify(path, kp.getPublic());
    System.out.println("Verified seq=" + vr.lastSeq() + " tip=" + b64(vr.tipHash()));
    // Publish vr.tipHash() as an anchor elsewhere (e.g., a separate account/bucket)
  }
}
```

**Notes**

-   The sample uses a **single-writer** file. In real systems, use a **log service** (queue/stream) to serialize events per partition.
    
-   Replace the in-process signer with a **KMS/HSM**; store **`keyId`** and keep a **public key registry** for verification over time.
    
-   Store files in **append-only/WORM** storage with replication and lifecycle management; index copies to your SIEM for search.
    
-   Anchor the **tip hash** regularly (hourly/daily) in a **separate trust domain**; keep an anchor ledger.
    

---

## Known Uses

-   **Cloud & SaaS**: Control-plane audit logs (AWS CloudTrail, GCP Admin Activity, Azure Activity Logs) with tamper-evidence and cross-account delivery.
    
-   **Financial/Healthcare**: Signed, immutable access logs for regulated data (SOX/HIPAA).
    
-   **CI/CD & Admin Tools**: Every privileged action (policy changes, deployments) recorded and signed.
    
-   **Databases**: Row-level access auditing with externalized, append-only export.
    
-   **Zero-Trust Platforms**: Identity-centric audit with per-service signing keys and hourly anchors.
    

---

## Related Patterns

-   **Encryption at Rest & In Transit:** protect audit data in storage and over the wire.
    
-   **Secrets Manager / KMS:** custody and rotation of signing keys.
    
-   **Principle of Least Privilege:** restrict who can read/write/verify audit logs.
    
-   **Idempotent Receiver / Outbox:** reliable event emission from transactional systems.
    
-   **Data Masking:** minimize PII in audit payloads.
    
-   **Leader Election / Sequencer:** ensure single-writer ordering per partition.
    

---

## Implementation Checklist

-   Define a **versioned schema**; include `streamId`, `seq`, `ts`, `prevHash`, `keyId`, `entryHash`, `sig`.
    
-   Use **hash chains** (or Merkle trees) + **digital signatures**; verify continuously.
    
-   Ship over **mutually authenticated TLS**; authenticate producers.
    
-   Persist to **append-only/WORM** storage; enable replication & lifecycle rules.
    
-   **Anchor** roots to a separate trust domain; store anchor history immutably.
    
-   Build **verification tooling** and run it on ingestion + periodically; alert on gaps/mismatches.
    
-   **Rotate keys**; preserve public keys with validity intervals; record `keyId` in each entry.
    
-   Enforce **PII minimization**; mask sensitive fields; honor retention & legal holds.
    
-   Include **backpressure & local queuing**; never silently drop security-critical events.
    
-   Practice **incident drills**: simulate tampering and verify detection end-to-end.
