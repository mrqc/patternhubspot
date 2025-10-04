# Tamper Detection — Security Pattern

## Pattern Name and Classification

-   **Name:** Tamper Detection
    
-   **Classification:** Security / Integrity / Defensive Pattern
    

## Intent

Detect unauthorized modifications of data, code, configurations, or runtime artifacts by using **cryptographic integrity checks**, **version validation**, and **attestation mechanisms** to ensure the system can recognize if something has been altered—whether at rest, in transit, or in execution.

## Also Known As

-   Integrity Verification
    
-   Anti-Tamper Mechanism
    
-   Integrity Guard
    

## Motivation (Forces)

Modern systems operate in hostile or semi-trusted environments:

-   Attackers may **modify binaries, configuration files, logs, or transmitted data** to inject malicious code, hide traces, or escalate privileges.
    
-   Users may alter local files (e.g., client apps, license files) for fraud.
    
-   Cloud or container workloads might be **tampered post-deployment** (supply chain risk).
    
-   IoT devices face **firmware manipulation** threats.
    
-   Audit and forensic systems need to **prove data integrity**.
    

**Forces:**

-   **Performance vs. Security:** Frequent integrity checks add CPU cost.
    
-   **Granularity:** File-level vs. block-level detection.
    
-   **Key Management:** Verification keys must themselves be protected.
    
-   **Usability:** Too many alerts can create noise.  
    The Tamper Detection pattern balances these by integrating **cryptographic signatures**, **hash chains**, and **secure storage of reference states**.
    

## Applicability

Use the Tamper Detection pattern when:

-   You must ensure **data or binary integrity** (executables, configuration, logs, models).
    
-   Data travels through **untrusted intermediaries** or **distributed environments**.
    
-   You deploy **firmware, mobile, or desktop clients** where the environment may be compromised.
    
-   You need **chain-of-custody guarantees** for audit or regulatory compliance (GDPR, ISO 27001, SOC 2).
    
-   You want to \*\*detect—not just prevent—\*\*tampering to trigger alerts or fail-safes.
    

## Structure

**Core Components:**

-   **Originator:** Creates artifact or data and computes integrity metadata (hash or signature).
    
-   **Verifier:** Checks hash/signature against a trusted reference.
    
-   **Reference Store:** Secure storage for baseline hashes, digests, or certificates.
    
-   **Crypto Service:** Provides signing, hashing (SHA-256/SHA-512), HMAC, or public-key verification.
    
-   **Event Logger:** Logs tamper detection events securely.
    
-   **Response Handler:** Defines what happens upon detection (alert, quarantine, rollback).
    

**Data Flow:**

```rust
Artifact -> Hash(Sign) -> Store Reference -> Verify at Usage -> Alert/Reject if mismatch
```

## Participants

-   **Producer (Trusted Source):** Generates the artifact and signs it.
    
-   **Verifier:** Validates signature or digest at read/load time.
    
-   **Key Manager (KMS/HSM):** Protects signing/verification keys.
    
-   **Reference Repository:** Holds known-good checksums/signatures.
    
-   **Monitoring/Audit Service:** Receives tamper detection alerts.
    
-   **End User or System Component:** Consumes verified artifacts.
    

## Collaboration

1.  **Creation:** Producer computes a hash (SHA-256) of the artifact.
    
2.  **Signing:** Hash is signed using a private key (RSA/ECDSA).
    
3.  **Distribution:** Artifact and signature are delivered together.
    
4.  **Verification:** Consumer uses public key to verify signature matches artifact hash.
    
5.  **Detection:** Any mismatch signals tampering → logged + blocked.
    
6.  **Response:** Incident handler quarantines artifact, triggers alert, or restores last valid version.
    
7.  **Audit Trail:** Secure Logger records detection and cryptographic evidence for forensics.
    

## Consequences

**Benefits**

-   Ensures early detection of unauthorized modification.
    
-   Builds user trust and regulatory compliance.
    
-   Protects supply chain integrity (build to deploy).
    
-   Enables tamper-evident logs and data archives.
    

**Liabilities**

-   Requires **cryptographic key management** (rotation, storage, distribution).
    
-   Adds CPU overhead for large files.
    
-   Detection only—**does not prevent tampering**, only reveals it.
    
-   False positives possible if legitimate changes occur without re-signing.
    
-   Secure storage for reference digests must itself be trusted.
    

## Implementation

### Principles

-   **Immutable Baseline:** Store reference hashes in secure storage (DB with HMAC or append-only ledger).
    
-   **Cryptographic Algorithms:** Use modern secure algorithms (SHA-256+, HMAC, RSA-2048+, ECDSA).
    
-   **Timestamping:** Combine hash with trusted timestamp to detect rollback.
    
-   **Chain Hashing:** For logs or sequences, hash next block including previous hash (blockchain style).
    
-   **Runtime Verification:** Compare code signatures at startup.
    
-   **Fail-Closed Behavior:** Deny or alert upon verification failure.
    
-   **Key Protection:** Keep signing keys in HSM or Secrets Manager.
    
-   **Regular Integrity Scans:** Periodically verify file system, configuration, and deployment manifests.
    

---

## Sample Code (Java)

The following example demonstrates file-level tamper detection using SHA-256 hashing and RSA digital signatures.

### Step 1 — Sign a file (producer side)

```java
import java.io.*;
import java.nio.file.*;
import java.security.*;
import java.security.spec.*;
import java.util.Base64;

public class FileSigner {

    public static void signFile(Path filePath, Path privateKeyPath, Path signatureOut) throws Exception {
        // Load private key
        byte[] keyBytes = Files.readAllBytes(privateKeyPath);
        PKCS8EncodedKeySpec spec = new PKCS8EncodedKeySpec(keyBytes);
        KeyFactory kf = KeyFactory.getInstance("RSA");
        PrivateKey privateKey = kf.generatePrivate(spec);

        // Read file content and compute hash
        byte[] data = Files.readAllBytes(filePath);
        Signature sig = Signature.getInstance("SHA256withRSA");
        sig.initSign(privateKey);
        sig.update(data);
        byte[] signatureBytes = sig.sign();

        // Write signature to file
        Files.write(signatureOut, Base64.getEncoder().encode(signatureBytes));
        System.out.println("File signed successfully. Signature stored at: " + signatureOut);
    }

    public static void main(String[] args) throws Exception {
        Path file = Paths.get("artifact.jar");
        Path privateKey = Paths.get("private_key.der");
        Path sig = Paths.get("artifact.sig");
        signFile(file, privateKey, sig);
    }
}
```

### Step 2 — Verify the signature (consumer side)

```java
import java.io.*;
import java.nio.file.*;
import java.security.*;
import java.security.spec.*;
import java.util.Base64;

public class FileVerifier {

    public static boolean verifyFile(Path filePath, Path publicKeyPath, Path signaturePath) throws Exception {
        // Load public key
        byte[] keyBytes = Files.readAllBytes(publicKeyPath);
        X509EncodedKeySpec spec = new X509EncodedKeySpec(keyBytes);
        KeyFactory kf = KeyFactory.getInstance("RSA");
        PublicKey publicKey = kf.generatePublic(spec);

        // Read file and signature
        byte[] data = Files.readAllBytes(filePath);
        byte[] signatureBytes = Base64.getDecoder().decode(Files.readString(signaturePath));

        // Verify
        Signature sig = Signature.getInstance("SHA256withRSA");
        sig.initVerify(publicKey);
        sig.update(data);
        boolean verified = sig.verify(signatureBytes);

        if (verified)
            System.out.println("Integrity verified: file not tampered.");
        else
            System.err.println("Tampering detected! File integrity failed.");

        return verified;
    }

    public static void main(String[] args) throws Exception {
        Path file = Paths.get("artifact.jar");
        Path pubKey = Paths.get("public_key.der");
        Path sig = Paths.get("artifact.sig");
        verifyFile(file, pubKey, sig);
    }
}
```

### Step 3 — Integration Ideas

-   Integrate verification step at **application startup** (verify all config and binaries).
    
-   Combine with **HMAC signatures** for faster symmetric integrity checks of smaller data.
    
-   Use **Merkle trees** or **hash chains** for logs or datasets.
    
-   Employ **timestamped ledgers** (e.g., blockchain or WORM S3) for forensic-grade immutability.
    

---

## Known Uses

-   **Linux package managers** (APT, YUM) verifying packages via GPG signatures.
    
-   **Container registries** (Docker Content Trust, Notary) using SHA256 digests and signed manifests.
    
-   **Firmware & OTA updates** in IoT and automotive software verified with signed images.
    
-   **Blockchain and distributed ledgers** ensuring immutable transaction records.
    
-   **Digital signing of audit logs** in financial and healthcare systems for compliance.
    
-   **Code signing** for executables and mobile apps (Apple, Microsoft, Android).
    

## Related Patterns

-   **Secure Audit Trail** (adds chain-of-hash for immutability)
    
-   **Data Confidentiality** (complements tamper detection by encryption)
    
-   **Secure Logger** (integrity-protected event logging)
    
-   **Write-Ahead Log** (append-only journaling for integrity)
    
-   **Immutable Storage** / **WORM (Write Once Read Many)**
    
-   **Secure Boot** (hardware-assisted tamper detection at startup)
    

---

**Summary:**  
Tamper Detection ensures **integrity and trustworthiness** of data and code by using **cryptographic signatures, hashing, and verifiable baselines**, enabling systems to detect unauthorized changes, trigger security responses, and maintain forensic validity across environments.

