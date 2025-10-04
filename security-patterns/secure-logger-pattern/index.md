# Secure Logger — Security Pattern

## Pattern Name and Classification

-   **Name:** Secure Logger
    
-   **Classification:** Security / Defensive / Cross-cutting concern (observability & compliance)
    

## Intent

Provide a systematic way to generate, transport, store, and query application logs so that they are **useful for operations and forensics** while **preventing leakage or tampering** of sensitive data and resisting log-based attacks.

## Also Known As

-   Confidential Logging
    
-   Privacy-Preserving Logging
    
-   Tamper-Evident Logging
    

## Motivation (Forces)

Systems need rich telemetry for debugging, audit, and incident response, but:

-   **Confidentiality vs. Observability:** PII/PHI/credentials must never leak; operators still need context.
    
-   **Regulatory pressure:** GDPR/PCI/ISO-27001 demand data minimization, retention limits, and integrity.
    
-   **Integrity:** Attackers may try to erase or alter traces.
    
-   **Availability/Performance:** Logging must not block hot paths or inflate latency/cost.
    
-   **Injection & traversal:** Untrusted input can break log parsers or smuggle control characters.
    
-   **Correlation:** Traces must join across services without exposing identities.  
    This pattern balances these forces via **structured, policy-driven, redacted, and (optionally) encrypted** logs with **append-only, tamper-evident storage**.
    

## Applicability

Use Secure Logger when:

-   Handling PII/PHI/payment data/secrets.
    
-   Operating in regulated environments (e.g., PCI DSS, GDPR, HIPAA, ISO 27001).
    
-   Multi-tenant/SaaS where tenant isolation matters.
    
-   You need chain-of-custody or forensic-grade auditability.
    
-   You ingest logs into a SIEM/EDR with strict schemas and retention.
    

## Structure

-   **Application Code** → calls → **Logging Facade** (e.g., SLF4J)
    
-   **Secure Logging Library**
    
    -   **Policy Engine:** allow/deny lists, redaction rules, minimization.
        
    -   **Classifier:** tag severity, event types, data categories.
        
    -   **PII Filter/Masker:** regex/tokenization/format-preserving masking.
        
    -   **Crypto Service:** HMAC for integrity; optional field or file-level encryption (AES-GCM).
        
    -   **Normalizer:** structured JSON, escaping, newline/CTL filtering.
        
    -   **Correlation Context:** trace/span IDs (MDC).
        
-   **Sinks/Transports:** stdout, file with rotation, syslog/TLS, cloud logging API.
    
-   **Immutable Storage:** WORM/append-only bucket, object lock, or ledger table.
    
-   **Key Management:** KMS/HSM for signing and encryption keys.
    
-   **Retention/Deletion Controller:** schedules, legal holds, and purge.
    

## Participants

-   **Developers** use the facade and structured events.
    
-   **SecureLogger** enforces policy + transforms events.
    
-   **CryptoService/KMS** provides keys and primitives.
    
-   **Log Router/Agent** ships logs to SIEM securely.
    
-   **Compliance/IR Teams** query immutable store.
    
-   **Clock/Time Source** (NTP) for trustworthy timestamps.
    

## Collaboration

1.  App builds an event with safe fields (no secrets).
    
2.  SecureLogger **classifies**, **redacts**, **hashes** identities, adds **correlation IDs**.
    
3.  For critical events, SecureLogger **signs (HMAC)** payload; optional **field encryption**.
    
4.  Event is **structured** (JSON), **escaped**, and emitted.
    
5.  Log agent forwards over **mutual TLS** to SIEM.
    
6.  Storage enforces **append-only**, **retention**, and **object-lock**.
    
7.  IR tools verify **integrity** (recompute HMAC) during investigations.
    

## Consequences

**Benefits**

-   Minimizes data breach impact; supports compliance & forensics.
    
-   Prevents log injection; normalizes for analytics.
    
-   Clear separation: developers focus on messages, policy does the rest.
    

**Liabilities**

-   More moving parts (policy/KMS/agents).
    
-   Crypto and redaction add CPU cost.
    
-   Encrypted fields may reduce searchability (need dual-write of non-sensitive metadata).
    
-   Misconfigured policies can over- or under-redact.
    

## Implementation

**Key Practices**

-   **Structured logging (JSON)** with a stable schema and event types.
    
-   **Data minimization:** log IDs, not full objects.
    
-   **Redaction/masking:** e.g., keep last 4 digits of card; hash emails.
    
-   **No secrets in logs:** never log tokens, passwords, private keys.
    
-   **Integrity:** include an **HMAC** or sign batches; store in append-only/WORM.
    
-   **Transport security:** mTLS/TLS, restricted egress, least privilege.
    
-   **Rotation & retention:** size/time-based rolling; object lock; legal hold.
    
-   **Escape/normalize:** strip control characters (`\r`, `\n`, `\u0000`…), remove ANSI.
    
-   **Correlation:** `trace_id`, `span_id`, `correlation_id`, `tenant_id`.
    
-   **Rate limiting/sampling:** avoid log storms and cost explosions.
    
-   **Clock discipline:** NTP + monotonic sequence to avoid tampering via skew.
    

**Policy Hints**

-   **Allowlist fields** per event type; everything else dropped.
    
-   **PII catalog** with regex + context rules; test policies with golden logs.
    
-   **Key rotation** (HMAC/DEK via KMS) with key IDs embedded in each record.
    
-   **Backpressure strategy:** drop debug/info first; always keep security/audit.
    

## Sample Code (Java)

> Illustrative example using SLF4J + Logback, JSON logs, field-level masking, identity hashing, and HMAC signing. (Production systems should use vetted libs and managed KMS/HSM.)

```java
// build.gradle (snippets)
// implementation 'org.slf4j:slf4j-api:2.0.13'
// runtimeOnly 'ch.qos.logback:logback-classic:1.5.6'
// implementation 'com.fasterxml.jackson.core:jackson-databind:2.17.1'
// implementation 'org.bouncycastle:bcprov-jdk18on:1.78.1' // if needed
```

```xml
<!-- logback.xml: JSON to stdout, daily rotation if file sink is used -->
<configuration>
  <appender name="STDOUT" class="ch.qos.logback.core.ConsoleAppender">
    <encoder class="ch.qos.logback.core.encoder.LayoutWrappingEncoder">
      <layout class="ch.qos.logback.contrib.json.classic.JsonLayout">
        <timestampFormat>yyyy-MM-dd'T'HH:mm:ss.SSSX</timestampFormat>
        <appendLineSeparator>true</appendLineSeparator>
        <includes>
          <includes>timestamp,level,thread,message,mdc</includes>
        </includes>
      </layout>
    </encoder>
  </appender>

  <root level="INFO">
    <appender-ref ref="STDOUT"/>
  </root>
</configuration>
```

```java
// SecureLogger.java
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.time.OffsetDateTime;
import java.util.*;
import java.util.regex.Pattern;

public final class SecureLogger {
    private static final Logger raw = LoggerFactory.getLogger("secure");
    private static final ObjectMapper MAPPER = new ObjectMapper();

    // Example HMAC key (load from KMS/HSM/env; rotate by keyId)
    private final byte[] hmacKey;
    private final String keyId;
    private final List<Pattern> piiPatterns;

    public SecureLogger(byte[] hmacKey, String keyId) {
        this.hmacKey = Arrays.copyOf(hmacKey, hmacKey.length);
        this.keyId = keyId;
        this.piiPatterns = List.of(
            Pattern.compile("(?i)(password|pwd)\\s*[:=]\\s*\\S+"),
            Pattern.compile("(?i)(authorization: Bearer)\\s+\\S+"),
            Pattern.compile("\\b\\d{13,19}\\b") // naive PAN
        );
    }

    public void info(String eventType, Map<String, Object> fields) { log("INFO", eventType, fields, null); }
    public void warn(String eventType, Map<String, Object> fields) { log("WARN", eventType, fields, null); }
    public void error(String eventType, Map<String, Object> fields, Throwable t) { log("ERROR", eventType, fields, t); }

    private void log(String level, String eventType, Map<String, Object> fields, Throwable t) {
        Map<String, Object> ev = new LinkedHashMap<>();
        ev.put("ts", OffsetDateTime.now().toString());
        ev.put("level", level);
        ev.put("event", eventType);
        ev.put("correlation_id", safe(MDC.get("correlation_id")));
        ev.put("trace_id", safe(MDC.get("trace_id")));
        ev.put("tenant_id", safe(limit(fields.removeOrDefault("tenant_id", null))));
        // Allowlist core fields; drop noisy ones by policy
        Map<String, Object> payload = minimize(fields);

        // Redact/mask known sensitive fields
        redact(payload, "email", v -> hashId(v));
        redact(payload, "user_id", v -> hashId(v));
        redact(payload, "phone", v -> maskPhone(v));
        redact(payload, "card", v -> maskCard(v));
        // Scrub unstructured message fields with regexes
        scrubFreeText(payload);

        ev.put("data", payload);

        // Integrity: HMAC over canonical JSON of {event,data,trace_id,ts}
        String canonical = toCanonicalString(ev, List.of("ts","event","trace_id","data"));
        String sig = hmacSha256Base64(hmacKey, canonical);
        ev.put("sig", Map.of("alg","HMAC-SHA256","kid", keyId, "value", sig));

        try {
            String json = MAPPER.writeValueAsString(ev);
            // Ensure no newlines/control chars
            json = json.replaceAll("[\\r\\n\\u0000-\\u001F]", " ");
            switch (level) {
                case "INFO" -> raw.info(json);
                case "WARN" -> raw.warn(json);
                case "ERROR" -> raw.error(json, t);
                default -> raw.info(json);
            }
        } catch (Exception e) {
            // Last resort: emit minimal safe line
            raw.error("{\"event\":\"logging_failure\",\"reason\":\"serialization\"}");
        }
    }

    private Map<String, Object> minimize(Map<String, Object> in) {
        // Example allowlist: keep only whitelisted keys; drop the rest
        Set<String> allow = Set.of("user_id","email","phone","path","method","status","latency_ms","remote_ip","error_code","reason","card");
        Map<String, Object> out = new LinkedHashMap<>();
        in.forEach((k,v) -> { if (allow.contains(k)) out.put(k, limit(v)); });
        return out;
    }

    private void redact(Map<String, Object> map, String key, java.util.function.Function<String,String> fn) {
        Object v = map.get(key);
        if (v instanceof String s && !s.isEmpty()) map.put(key, fn.apply(s));
    }

    private void scrubFreeText(Map<String, Object> map) {
        for (Map.Entry<String,Object> e : map.entrySet()) {
            if (e.getValue() instanceof String s) {
                String scrubbed = s;
                for (Pattern p : piiPatterns) {
                    scrubbed = p.matcher(scrubbed).replaceAll("<redacted>");
                }
                // Remove ANSI and control characters
                scrubbed = scrubbed.replaceAll("\\e\\[[\\d;]*[^\\d;]", "")
                                   .replaceAll("[\\r\\n\\u0000-\\u001F]", " ");
                map.put(e.getKey(), scrubbed);
            }
        }
    }

    private String maskCard(String v) {
        String digits = v.replaceAll("\\D", "");
        if (digits.length() < 12) return "<redacted>";
        return "**** **** **** " + digits.substring(digits.length()-4);
    }

    private String maskPhone(String v) {
        String d = v.replaceAll("\\D", "");
        if (d.length() <= 4) return "<redacted>";
        return d.substring(0, Math.max(0, d.length() - 4)).replaceAll("\\d", "*") + d.substring(d.length() - 4);
    }

    private String hashId(String v) {
        // Simple SHA-256 (better: salted or keyed hash for re-identification protection)
        try {
            var md = java.security.MessageDigest.getInstance("SHA-256");
            return Base64.getUrlEncoder().withoutPadding().encodeToString(md.digest(v.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) { return "<hash_error>"; }
    }

    private String toCanonicalString(Map<String,Object> ev, List<String> keys) {
        Map<String,Object> m = new LinkedHashMap<>();
        for (String k : keys) if (ev.containsKey(k)) m.put(k, ev.get(k));
        try { return MAPPER.writeValueAsString(m); } catch (Exception e) { return ""; }
    }

    private String hmacSha256Base64(byte[] key, String msg) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(key, "HmacSHA256"));
            return Base64.getUrlEncoder().withoutPadding().encodeToString(mac.doFinal(msg.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) { return "<sig_error>"; }
    }

    private String safe(String v) { return v == null ? null : v.replaceAll("[\\r\\n\\u0000-\\u001F]", " "); }
    private Object limit(Object v) {
        if (v instanceof String s && s.length() > 2048) return s.substring(0, 2048) + "...";
        return v;
    }
}
```

```java
// Usage example
import org.slf4j.MDC;
import java.util.Map;

public class Example {
    public static void main(String[] args) {
        // In real apps, fetch HMAC key from KMS and rotate regularly
        byte[] key = "super-secret-32-bytes-minimum-key-here-please".getBytes();
        SecureLogger slog = new SecureLogger(key, "k1");

        MDC.put("correlation_id", UUID.randomUUID().toString());
        MDC.put("trace_id", UUID.randomUUID().toString());

        slog.info("http_request", Map.of(
            "tenant_id", "t-123",
            "user_id", "alice@example.com",
            "email", "alice@example.com",
            "method", "POST",
            "path", "/api/v1/orders",
            "status", 201,
            "latency_ms", 73,
            "remote_ip", "203.0.113.10",
            "card", "4111-1111-1111-1234"
        ));

        try {
            throw new IllegalStateException("Operation failed for user password: secret");
        } catch (Exception e) {
            slog.error("order_failed", Map.of(
                "tenant_id", "t-123",
                "user_id", "alice@example.com",
                "reason", e.getMessage(),
                "error_code", "ORD-500"
            ), e);
        }
    }
}
```

**Optional field encryption sketch** (encrypt only the `data` map or selected fields with AES-GCM using a DEK from KMS; store `dek_kid`, `iv`, and `ciphertext` while leaving non-sensitive metadata in plaintext for search).

## Known Uses

-   Financial/healthcare services that ship **JSON logs with masking** to a SIEM (e.g., Splunk/Elastic) over **mTLS**, keep **90 days hot + WORM cold storage**, and verify **HMAC** during incident response.
    
-   Cloud platforms and modern microservice stacks adopting **MDC-based correlation**, **redaction filters**, and **object-lock** in S3-compatible stores.
    

## Related Patterns

-   **Secure Audit Trail** (immutability & non-repudiation focus)
    
-   **Secrets Manager** (key/credential handling used by the logger)
    
-   **Privacy Filter** / **Data Minimization**
    
-   **Append-Only/WORM Storage**
    
-   **Event Sourcing** (separate; but shares append-only integrity concerns)
    
-   **Health Check / Fail-Safe Logger** (fallback to local buffer on SIEM outage)
    

---

**Notes for production hardening**

-   Use vetted libraries for regex PII detection and tokenization.
    
-   Maintain a **schema registry** for log events; validate in CI.
    
-   Add **sampling & rate limits** per event type and tenant.
    
-   Employ **key rotation & envelope encryption** (KMS-managed CMKs + DEKs).
    
-   Test with **golden logs** to prevent regression of redaction policies.
    
-   Enforce **least-privilege IAM** for log pipelines and buckets.

