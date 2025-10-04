# Data Masking — Security Pattern

## Pattern Name and Classification

**Name:** Data Masking  
**Classification:** Security / Data Protection / Privacy — *Runtime and/or at-rest redaction, obfuscation, tokenization, or generalization of sensitive data based on policy and context*

---

## Intent

Prevent **unnecessary exposure** of sensitive data by **altering its representation** (redaction, partial reveal, hashing, tokenization, generalization) according to **policy**, **purpose**, and **viewer context**—while keeping systems functional (searchability, format constraints, audits).

---

## Also Known As

-   Data Redaction
    
-   Dynamic Data Masking (DDM)
    
-   Pseudonymization / Tokenization
    
-   Anonymization (when irreversible and aggregated)
    
-   Format-Preserving Masking
    

---

## Motivation (Forces)

-   **Least exposure:** Many roles need to *see* that data exists, not its raw value (e.g., last 4 digits of a card).
    
-   **Regulations:** GDPR/CCPA/PCI-DSS/ HIPAA require minimization, purpose limitation, and auditability.
    
-   **Operational leakage:** Logs, analytics, caches, search indexes, support tools easily leak PII/PHI/PCI.
    
-   **Usability:** Call centers must verify identity (“read back last 4”), devs need realistic-but-safe test data.
    
-   **Performance & compatibility:** Preserve formats and checks (e.g., Luhn) where necessary.
    

**Tensions:** Reversibility vs privacy, utility vs security, runtime latency vs safety, consistency for joins/search vs de-identification strength.

---

## Applicability

Use this pattern when:

-   Multiple audiences require **different views** of the same data (role-, tenant-, or purpose-based).
    
-   Data must be **shared** with third parties, test/staging, BI, or support without revealing raw identifiers.
    
-   You need **runtime redaction** for responses, UI, logs, or alerts.
    
-   You need **at-rest tokenization** to reduce the scope of regulated systems (e.g., PCI).
    

Avoid or adapt when:

-   Downstream systems **require originals** (e.g., clearing systems, legal holds). Use **enclaves** or segregated paths.
    
-   You must guarantee **irreversibility** (use anonymization/aggregation rather than masking).
    
-   High-assurance cryptography is required; don’t roll your own **FPE**—use vetted libraries/HSMs.
    

---

## Structure

-   **Classification & Catalog:** Data elements tagged with sensitivity (e.g., `PII.SSN`, `PCI.PAN`, `PHI`).
    
-   **Policy Engine:** Maps *subject, purpose, viewer, environment* → *masking rule*.
    
-   **Masking Strategies:** Redact, partial-reveal, hashing/HMAC, tokenization (lookup), generalization, format-preserving masking.
    
-   **Enforcement Points:**
    
    -   **Runtime:** API layer/serialization filters, database DDM, log scrubbing.
        
    -   **Batch:** ETL/ELT pipelines generating masked datasets.
        
-   **Key & Token Store:** For HMAC/tokenization secrets, with rotation/audit.
    
-   **Audit & Telemetry:** Who saw what (masked or unmasked), policy decisions, denials.
    

---

## Participants

-   **Data Owner / DPO:** Defines policy and approval flows.
    
-   **Policy Service / PDP:** Decides which strategy applies for the current context.
    
-   **PEP (Enforcement):** Serializers, DB views, API gateways, log appenders.
    
-   **Tokenization Service:** Exchanges raw values ↔ tokens (access controlled).
    
-   **Observers/Consumers:** Humans or systems receiving masked data.
    
-   **KMS/HSM:** Protects keys for HMAC/crypto/tokens.
    

---

## Collaboration

1.  **Classify** fields and register them in a **data catalog**.
    
2.  **Request** for data arrives with viewer identity, purpose, and environment.
    
3.  **PDP** evaluates policy → returns **strategy** per field (e.g., last4 for PAN, hash for SSN).
    
4.  **PEP** applies strategies during **serialization** or **query** (DB redaction).
    
5.  **Audit** the decision and exposure (masked/unmasked, who, when, why).
    
6.  **Tokenization** (if used) looks up or creates a token; raw stays in a secure vault.
    

---

## Consequences

**Benefits**

-   Minimizes blast radius of accidental or malicious exposure.
    
-   Aligns with privacy-by-design; reduces compliance scope (e.g., PCI).
    
-   Enables safe operations (support, analytics) with realistic-but-safe data.
    

**Liabilities**

-   Complexity in **policy** and **context propagation**.
    
-   Risk of **inconsistent masking** across services if not centralized.
    
-   **Format edge cases** (i18n names, variable PAN lengths) can lead to broken UX.
    
-   Masking at runtime adds **latency**; static masking may reduce data utility.
    

---

## Implementation

### Key Decisions

-   **Where to enforce:**
    
    -   **Database** (views/column masking) for consistency;
        
    -   **Application** (serializers/filters) for context-aware masking;
        
    -   **Gateway** for coarse policies.
        
-   **Strategy per field:**
    
    -   *Redact:* replace with `****`.
        
    -   *Partial reveal:* keep last N / first N.
        
    -   *Hash/HMAC:* irreversible (for dedupe/joins); use **HMAC** with rotation & pepper.
        
    -   *Tokenize:* reversible by vault; scope of compliance shifted to token service.
        
    -   *Generalize:* age buckets, city→region, date→month.
        
    -   *FPE:* when specific format checks must pass (use vetted library).
        
-   **Context model:** role, tenant, purpose, environment (prod/test), consent flags.
    
-   **Key management:** rotate HMAC/token keys; audit access; wrap in KMS/HSM.
    
-   **Observability:** log policy decisions (not raw values); measure % masked.
    

### Anti-Patterns

-   Hardcoding masking rules in many microservices → drift.
    
-   Logging **pre-masked** values or tokens in plaintext.
    
-   Using plain **hash** for joinability (susceptible to dictionary attacks); prefer **HMAC** with secret.
    
-   Claiming “anonymized” when it’s only masked (re-identification risk).
    
-   Rolling your own cryptography for FPE/tokenization.
    

---

## Sample Code (Java, policy- & context-aware masking)

**What this shows**

-   Field-level masking strategies (`REDACT`, `PARTIAL`, `HMAC_SHA256`, `TOKENIZE`, `GENERALIZE_DATE`).
    
-   A simple **policy evaluator** using viewer roles/purposes.
    
-   **Jackson**\-based serialization hook that applies masking at response time.
    
-   A tiny in-memory **token vault** (for demo; replace with a secure service/KMS).
    

> Dependencies (Gradle snippet)

```gradle
implementation 'com.fasterxml.jackson.core:jackson-databind:2.17.1'
```

```java
// classification/DataTag.java
package com.example.datamasking.classification;

public enum DataTag {
  NAME, EMAIL, PHONE, ADDRESS, DOB, SSN, PCI_PAN, IBAN, FREE_TEXT, OTHER
}
```

```java
// policy/MaskingStrategy.java
package com.example.datamasking.policy;

public enum MaskingStrategy {
  NONE,                // show raw
  REDACT,              // "****"
  PARTIAL_LAST4,       // keep last 4 digits/characters
  PARTIAL_FIRST3,      // keep first 3
  HMAC_SHA256,         // deterministic irreversible (for joins)
  TOKENIZE,            // reversible via vault
  GENERALIZE_DATE_MM,  // keep year+month only
}
```

```java
// policy/MaskingPolicy.java
package com.example.datamasking.policy;

import com.example.datamasking.classification.DataTag;
import java.util.EnumMap;
import java.util.Map;

public class MaskingPolicy {
  private final Map<DataTag, MaskingStrategy> byTag = new EnumMap<>(DataTag.class);

  public MaskingPolicy set(DataTag tag, MaskingStrategy strategy) {
    byTag.put(tag, strategy);
    return this;
  }
  public MaskingStrategy forTag(DataTag tag) {
    return byTag.getOrDefault(tag, MaskingStrategy.REDACT);
  }
}
```

```java
// policy/PolicyEngine.java
package com.example.datamasking.policy;

import com.example.datamasking.classification.DataTag;

public class PolicyEngine {

  /** Decide per field based on viewer role and purpose. */
  public MaskingStrategy decide(String viewerRole, String purpose, DataTag tag) {
    // Examples:
    if ("ADMIN".equals(viewerRole) && "OPERATIONS".equals(purpose)) {
      // admins can see most raw, except PCI where they only see last4
      if (tag == DataTag.PCI_PAN) return MaskingStrategy.PARTIAL_LAST4;
      return MaskingStrategy.NONE;
    }
    if ("SUPPORT".equals(viewerRole)) {
      return switch (tag) {
        case NAME -> MaskingStrategy.PARTIAL_FIRST3;
        case EMAIL -> MaskingStrategy.PARTIAL_FIRST3;
        case PHONE -> MaskingStrategy.PARTIAL_LAST4;
        case PCI_PAN -> MaskingStrategy.PARTIAL_LAST4;
        case DOB -> MaskingStrategy.GENERALIZE_DATE_MM;
        default -> MaskingStrategy.REDACT;
      };
    }
    if ("ANALYTICS".equals(viewerRole)) {
      return switch (tag) {
        case EMAIL, PHONE, SSN, NAME -> MaskingStrategy.HMAC_SHA256; // joinable but irreversible
        case PCI_PAN -> MaskingStrategy.HMAC_SHA256;
        case DOB -> MaskingStrategy.GENERALIZE_DATE_MM;
        default -> MaskingStrategy.REDACT;
      };
    }
    // default: minimal
    return MaskingStrategy.REDACT;
  }
}
```

```java
// runtime/Masker.java
package com.example.datamasking.runtime;

import com.example.datamasking.policy.MaskingStrategy;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.*;

public class Masker {

  private final byte[] hmacKey;
  private final Map<String, String> tokenVault = new HashMap<>(); // demo only

  public Masker(byte[] hmacKey) { this.hmacKey = hmacKey.clone(); }

  public Object apply(MaskingStrategy strategy, Object value) {
    if (value == null) return null;
    String s = String.valueOf(value);

    return switch (strategy) {
      case NONE -> value;
      case REDACT -> "****";
      case PARTIAL_LAST4 -> partialLast4(s);
      case PARTIAL_FIRST3 -> partialFirst3(s);
      case HMAC_SHA256 -> hmacHex(s);
      case TOKENIZE -> tokenize(s);
      case GENERALIZE_DATE_MM -> generalizeDate(s);
    };
  }

  private String partialLast4(String s) {
    if (s.length() <= 4) return "****";
    return "*".repeat(Math.max(0, s.length() - 4)) + s.substring(s.length() - 4);
  }

  private String partialFirst3(String s) {
    if (s.length() <= 3) return "***";
    return s.substring(0, 3) + "*".repeat(s.length() - 3);
  }

  private String hmacHex(String s) {
    try {
      Mac mac = Mac.getInstance("HmacSHA256");
      mac.init(new SecretKeySpec(hmacKey, "HmacSHA256"));
      byte[] out = mac.doFinal(s.getBytes(StandardCharsets.UTF_8));
      StringBuilder sb = new StringBuilder(out.length * 2);
      for (byte b : out) sb.append(String.format("%02x", b));
      return sb.toString();
    } catch (Exception e) { throw new RuntimeException(e); }
  }

  /** Demo tokenization: do NOT use in production. Replace with a secure token vault. */
  private String tokenize(String s) {
    return tokenVault.computeIfAbsent(s, k -> "tok_" + base62(18));
  }

  private static String base62(int len) {
    String a = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
    SecureRandom r = new SecureRandom();
    StringBuilder sb = new StringBuilder(len);
    for (int i=0;i<len;i++) sb.append(a.charAt(r.nextInt(a.length())));
    return sb.toString();
  }

  private String generalizeDate(String s) {
    try {
      // Accept common formats; fallback to year-month of today's date if parse fails
      LocalDate d = LocalDate.parse(s);
      return d.format(DateTimeFormatter.ofPattern("yyyy-MM"));
    } catch (Exception e) {
      return "yyyy-MM";
    }
  }
}
```

```java
// runtime/annotations/Mask.java
package com.example.datamasking.runtime.annotations;

import com.example.datamasking.classification.DataTag;
public @interface Mask {
  DataTag value();
}
```

```java
// model/Customer.java
package com.example.datamasking.model;

import com.example.datamasking.runtime.annotations.Mask;
import com.example.datamasking.classification.DataTag;

public class Customer {
  public String id;

  @Mask(DataTag.NAME)
  public String fullName;

  @Mask(DataTag.EMAIL)
  public String email;

  @Mask(DataTag.PHONE)
  public String phone;

  @Mask(DataTag.PCI_PAN)
  public String cardPan;

  @Mask(DataTag.DOB)
  public String dob; // ISO-8601 "yyyy-MM-dd"

  public Customer(String id, String fullName, String email, String phone, String cardPan, String dob) {
    this.id = id; this.fullName = fullName; this.email = email; this.phone = phone; this.cardPan = cardPan; this.dob = dob;
  }
}
```

```java
// runtime/JacksonMaskingSerializer.java
package com.example.datamasking.runtime;

import com.example.datamasking.classification.DataTag;
import com.example.datamasking.policy.MaskingStrategy;
import com.example.datamasking.policy.PolicyEngine;
import com.example.datamasking.runtime.annotations.Mask;
import com.fasterxml.jackson.core.JsonGenerator;
import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.ser.BeanPropertyWriter;
import com.fasterxml.jackson.databind.ser.BeanSerializerModifier;

import java.lang.annotation.Annotation;

public class JacksonMaskingSerializer {

  public static ObjectMapper configuredMapper(PolicyEngine engine, Masker masker,
                                              String viewerRole, String purpose) {
    ObjectMapper om = new ObjectMapper();
    om.setSerializerFactory(om.getSerializerFactory().withSerializerModifier(
        new BeanSerializerModifier() {
          @Override
          public java.util.List<BeanPropertyWriter> changeProperties(SerializationConfig config,
                                                                     BeanDescription beanDesc,
                                                                     java.util.List<BeanPropertyWriter> props) {
            for (int i = 0; i < props.size(); i++) {
              BeanPropertyWriter bpw = props.get(i);
              Mask ann = findMaskAnnotation(bpw);
              if (ann != null) {
                DataTag tag = ann.value();
                props.set(i, new MaskingWriter(bpw, engine, masker, viewerRole, purpose, tag));
              }
            }
            return props;
          }
        }));
    return om;
  }

  private static Mask findMaskAnnotation(BeanPropertyWriter bpw) {
    Annotation[] anns = bpw.getMember().getAnnotations().getAllAnnotations().toArray(new Annotation[0]);
    for (Annotation a : anns) if (a.annotationType() == Mask.class) return (Mask) a;
    return null;
  }

  static final class MaskingWriter extends BeanPropertyWriter {
    private final PolicyEngine engine;
    private final Masker masker;
    private final String role, purpose;
    private final DataTag tag;

    protected MaskingWriter(BeanPropertyWriter base, PolicyEngine engine, Masker masker,
                            String role, String purpose, DataTag tag) {
      super(base);
      this.engine = engine; this.masker = masker; this.role = role; this.purpose = purpose; this.tag = tag;
    }

    @Override
    public void serializeAsField(Object bean, JsonGenerator gen, SerializerProvider prov) throws java.io.IOException {
      Object raw = get(bean);
      MaskingStrategy strat = engine.decide(role, purpose, tag);
      Object masked = masker.apply(strat, raw);
      gen.writeFieldName(getName());
      if (masked == null) gen.writeNull();
      else gen.writeObject(masked);
    }
  }
}
```

```java
// DemoMain.java
package com.example.datamasking;

import com.example.datamasking.model.Customer;
import com.example.datamasking.policy.PolicyEngine;
import com.example.datamasking.runtime.JacksonMaskingSerializer;
import com.example.datamasking.runtime.Masker;

public class DemoMain {
  public static void main(String[] args) throws Exception {
    Customer c = new Customer(
        "c-123",
        "Alice Wonderland",
        "alice@example.com",
        "+1-202-555-0199",
        "4111111111111111",
        "1989-05-07"
    );

    PolicyEngine engine = new PolicyEngine();
    Masker masker = new Masker("super-secret-hmac-key-rotate-me".getBytes());

    // SUPPORT view
    var supportMapper = JacksonMaskingSerializer.configuredMapper(engine, masker, "SUPPORT", "CASE_VIEW");
    System.out.println(supportMapper.writeValueAsString(c));
    // => {"id":"c-123","fullName":"Ali*************","email":"ali***************","phone":"***********0199","cardPan":"************1111","dob":"1989-05"}

    // ANALYTICS view
    var analyticsMapper = JacksonMaskingSerializer.configuredMapper(engine, masker, "ANALYTICS", "DASHBOARD");
    System.out.println(analyticsMapper.writeValueAsString(c));
    // => HMAC hashes for joinability; DOB generalized to month
  }
}
```

> **Production notes**
> 
> -   Replace demo token vault with a **tokenization service** (vault, tamper-evident logs, RBAC, KMS-wrapped keys).
>     
> -   Prefer **HMAC** for deterministic joins (store `kid`/algorithm); rotate keys with versioning and re-key jobs.
>     
> -   For FPE (format-preserving encryption) on PAN/IBAN, use a vetted implementation (e.g., NIST FF1/FF3-1) with compliance guidance.
>     
> -   Consider **DB-level masking** (e.g., SQL Server DDM, Oracle redaction, Postgres views) to centralize baseline policies.
>     
> -   Add **log scrubbing** filters that mask secrets/PII before output.
>     
> -   Maintain a **data catalog** with tags and owners; automate discovery (DLP scanners).
>     

---

## Known Uses

-   **Customer Support UIs** showing partial contact details and last 4 of payment methods.
    
-   **Analytics/BI** pipelines using **HMAC**\-pseudonymized identifiers for cohort analysis.
    
-   **PCI** environments using **tokenization** to remove core systems from PCI scope.
    
-   **Data sharing** with vendors or test environments via **static masked extracts**.
    
-   **Healthcare** portals generalizing dates/locations to protect PHI.
    

---

## Related Patterns

-   **Encryption at Rest / In Transit:** complementary; masking controls *presentation*, encryption controls *storage/transport*.
    
-   **Tokenization / Vaulted Secrets:** reversible substitution with strict access control.
    
-   **Anonymization / Differential Privacy:** irreversible techniques for releasing datasets.
    
-   **Field-Level Security / Attribute-Based Access Control (ABAC):** drives *when* masking applies.
    
-   **Redaction in Logs:** specialized masking for telemetry and SIEM pipelines.
    

---

## Implementation Checklist

-   Classify sensitive fields and maintain a **data catalog** with owners.
    
-   Define **policies** per role, purpose, tenant, and environment; codify in a **central engine**.
    
-   Choose **masking strategies** per field (redact/partial/hash/tokenize/generalize/FPE).
    
-   Centralize **enforcement** (serialization filters, DB views, gateway plugins).
    
-   Manage **keys/tokens** in KMS/HSM; rotate and audit regularly.
    
-   Add **log scrubbing** and ensure masked data in caches, search indexes, and DLQs.
    
-   Emit **auditable telemetry** of masking decisions (without PII).
    
-   Test i18n, variable lengths, and edge cases; fuzz inputs (Unicode, RTL, separators).
    
-   Document developer guidelines (never log raw PII; always serialize via masking layer).

