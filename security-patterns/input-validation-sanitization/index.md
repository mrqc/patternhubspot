# Input Validation & Sanitization — Security Pattern

## Pattern Name and Classification

**Name:** Input Validation & Sanitization  
**Classification:** Security / Defensive Coding / Data Integrity — *Prevention of injection, data corruption, and abuse by constraining, normalizing, and encoding untrusted input*

---

## Intent

Constrain **what is accepted**, **normalize** it into a canonical form, and **encode/sanitize** any data that crosses trust boundaries so that only **expected, safe, and well-formed** input reaches business logic, storage, and renderers.

---

## Also Known As

-   Defensive Input Handling
    
-   Allow-List (Positive) Validation
    
-   Canonicalization & Output Encoding
    
-   Taint Checking (conceptual)
    

---

## Motivation (Forces)

-   **Injection risks:** SQL/NoSQL/LDAP/OS command/HTML/Template injection occur when untrusted input is interpreted as code.
    
-   **Ambiguity & evasion:** Unicode confusables, overlong encodings, mixed normal forms, and path traversal defeat naive filters.
    
-   **Usability vs. strictness:** Too strict → false rejections; too lax → exploitation.
    
-   **Multiple sinks:** The same input may be used in SQL, JSON, HTML, file paths, logs—each needs **context-aware** handling.
    
-   **Performance & DX:** Centralized, declarative validation is easier to maintain and test.
    

---

## Applicability

Use this pattern when:

-   Accepting **any** data from users, devices, jobs, webhooks, or partner APIs.
    
-   Persisting data, generating HTML/CSV/XML, constructing file paths, invoking shell tools, or building queries.
    
-   Parsing complex formats (JSON, XML, CSV, uploads).
    

Avoid or adapt when:

-   Data is already strongly typed and verified at the source (e.g., mutually authenticated services with strict schemas) — still **canonicalize** and **encode on output**.
    
-   You need cryptographic authenticity/integrity — use **signatures/MAC** in addition.
    

---

## Structure

-   **Allow-List Validators:** Length, character class, format, range, enumeration, schema validation.
    
-   **Canonicalizer:** Trim, Unicode **NFC** normalization, collapse whitespace, reject control characters & invalid code points.
    
-   **Context Encoders / Sanitizers:**
    
    -   **Output encoding** for HTML/JS/URL/JSON/CSV.
        
    -   **Sanitizers** for rich content (e.g., HTML policy).
        
-   **Policy Registry:** Central rules per field + per sink.
    
-   **Error Mapper:** Consistent, user-friendly messages; never echo raw attacker data.
    
-   **Logging (safe):** Structured logs with placeholders; no sensitive/unsanitized echo.
    

---

## Participants

-   **Client-to-Server Adapters** (controllers, message handlers) — first gate.
    
-   **Validation Service** — reusable rules & schemas.
    
-   **Sanitization/Encoding Layer** — sink-aware encoders & HTML sanitizer.
    
-   **Business Logic** — operates only on validated models.
    
-   **Persistence/Renderer** — uses parameterized APIs + output encoding.
    

---

## Collaboration

1.  **Receive** bytes → decode to text using expected charset (e.g., UTF-8).
    
2.  **Canonicalize** (NFC, trim, collapse) and **basic screen** (length, ASCII/Unicode classes).
    
3.  **Validate** against allow-list rules or schemas (e.g., Bean Validation, JSON Schema).
    
4.  **Reject** with precise errors; **do not auto-correct silently** (except minor canonicalization).
    
5.  **Sanitize/encode** according to the **sink** (HTML, SQL via parameters, URLs, file paths).
    
6.  **Persist/Render** using **parameterized** APIs and context encoders.
    

---

## Consequences

**Benefits**

-   Blocks whole classes of injection & traversal issues.
    
-   Predictable data quality; simpler downstream logic.
    
-   Clear security contract at boundaries.
    

**Liabilities**

-   Over-strict rules can harm UX; under-strict rules invite bypasses.
    
-   Multiple sinks require **context-specific** handling (no single “sanitize everything” function).
    
-   Added latency if done naively in hot paths—solve via centralized, compiled validators and caching.
    

---

## Implementation

### Principles & Key Decisions

-   **Validate early, encode late.** Validate on ingress; **encode/sanitize at each sink**.
    
-   **Prefer allow-list** (define what’s valid) over deny-list.
    
-   **Canonicalize before validate:** use **Unicode NFC**, strip nulls, reject control chars except necessary whitespace.
    
-   **Use parameterized APIs:** Prepared statements, ORM parameters, templating with auto-escaping, safe file APIs.
    
-   **Per-context encoding:**
    
    -   HTML text → HTML-escape;
        
    -   HTML attribute → attribute encoding;
        
    -   JS string → JS string encoding;
        
    -   URLs → percent-encode components;
        
    -   CSV → quote and escape per RFC 4180.
        
-   **Rich HTML input:** Use a **policy-based sanitizer** (e.g., OWASP Java HTML Sanitizer) to allow a minimal tag set.
    
-   **File paths:** Normalize, **resolve against a base directory**, and **enforce stay-inside** checks.
    
-   **Structured formats:** Validate JSON/XML against schemas; disable dangerous XML features (XXE).
    
-   **Error handling:** return **field-level** validation errors; never expose stack traces or raw input in responses.
    
-   **Logs & analytics:** log **metadata** not raw secrets/PII; if necessary, **mask**.
    

### Anti-Patterns

-   Home-grown regex “sanitizers” for HTML/JS.
    
-   String concatenation for SQL/OS command/HTML building.
    
-   Validating after persistence or after rendering.
    
-   Trusting client-side validation; server must re-validate.
    
-   Normalizing *after* validation (lets bypasses slip through).
    

---

## Sample Code (Java)

**What’s included**

-   Canonicalization & allow-list validation utilities.
    
-   Bean Validation (Jakarta) DTO example.
    
-   Safe HTML sanitization (using *jsoup* for demo).
    
-   Safe SQL (prepared statements).
    
-   Safe file path handling (prevent traversal).
    
-   Output encoding with OWASP Encoder.
    

> Minimal Gradle deps (example)

```gradle
implementation 'org.hibernate.validator:hibernate-validator:8.0.1.Final'   // Bean Validation
implementation 'org.glassfish:jakarta.el:4.0.2'                             // EL for HV
implementation 'org.owasp.encoder:encoder:1.2.3'                            // Output encoding
implementation 'org.jsoup:jsoup:1.17.2'                                     // HTML sanitizer (demo)
```

```java
// InputValidation.java
package com.example.security.input;

import org.jsoup.Jsoup;
import org.jsoup.safety.Safelist;
import org.owasp.encoder.Encode;

import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.text.Normalizer;
import java.util.Optional;
import java.util.regex.Pattern;

public final class InputValidation {

  // Allow-lists
  private static final Pattern USERNAME = Pattern.compile("^[a-zA-Z0-9_.-]{3,32}$");
  private static final Pattern EMAIL = Pattern.compile("^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]{2,}\\.[A-Za-z]{2,63}$");
  private static final Pattern PHONE = Pattern.compile("^[+0-9()\\-\\s]{6,20}$");
  private static final Pattern UUID_RE = Pattern.compile("^[0-9a-fA-F-]{36}$");

  /** Step 1: Canonicalize (NFC), trim, collapse whitespace, reject control chars. */
  public static String canonicalize(String raw) {
    if (raw == null) return null;
    String s = new String(raw.getBytes(StandardCharsets.UTF_8), StandardCharsets.UTF_8); // decode defense
    s = Normalizer.normalize(s, Normalizer.Form.NFC).trim();
    // collapse internal whitespace to single space
    s = s.replaceAll("\\p{Zs}+", " ");
    // reject non-printable control characters except \n\r\t
    if (Pattern.compile("[\\p{Cntrl}&&[^\\n\\r\\t]]").matcher(s).find()) {
      throw new IllegalArgumentException("Invalid control characters present");
    }
    return s;
  }

  /** Step 2: Validate specific fields via allow-lists. */
  public static String validateUsername(String s) {
    s = canonicalize(s);
    if (s == null || !USERNAME.matcher(s).matches())
      throw new IllegalArgumentException("Username must be 3-32 chars (letters, digits, _.-)");
    return s;
  }

  public static String validateEmail(String s) {
    s = canonicalize(s);
    if (s == null || s.length() > 254 || !EMAIL.matcher(s).matches())
      throw new IllegalArgumentException("Invalid email format");
    return s;
  }

  public static String validatePhone(String s) {
    s = canonicalize(s);
    if (s == null || !PHONE.matcher(s).matches())
      throw new IllegalArgumentException("Invalid phone format");
    return s;
  }

  public static String validateUUID(String s) {
    s = canonicalize(s);
    if (s == null || !UUID_RE.matcher(s).matches())
      throw new IllegalArgumentException("Invalid UUID");
    return s;
  }

  /** HTML sanitization: allow a tiny safe subset (p, b, i, a[href], ul/ol/li, br). */
  public static String sanitizeHtml(String html) {
    if (html == null) return null;
    return Jsoup.clean(html, Safelist.basic().addTags("ul","ol","li").addAttributes("a","rel","target"));
  }

  /** Output encoders — use at sinks (HTML templates, attributes, JS strings). */
  public static String html(String s) { return s == null ? "" : Encode.forHtml(s); }
  public static String htmlAttr(String s){ return s == null ? "" : Encode.forHtmlAttribute(s); }
  public static String jsString(String s){ return s == null ? "''" : "'" + Encode.forJavaScript(s) + "'"; }
  public static String urlParam(String s){ return s == null ? "" : Encode.forUriComponent(s); }

  /** Safe file path creation: normalize and enforce base directory constraint. */
  public static Path safeResolve(Path baseDir, String userPath) {
    String canon = canonicalize(userPath);
    Path candidate = baseDir.resolve(canon).normalize();
    if (!candidate.startsWith(baseDir)) throw new IllegalArgumentException("Path traversal blocked");
    return candidate;
  }
}
```

```java
// RegistrationDto.java  (Bean Validation example)
package com.example.security.input;

import jakarta.validation.constraints.*;

public class RegistrationDto {

  @NotBlank @Size(min = 3, max = 32)
  @Pattern(regexp = "^[a-zA-Z0-9_.-]+$", message = "letters, digits, _ . - only")
  public String username;

  @NotBlank @Email @Size(max = 254)
  public String email;

  @NotBlank @Size(min = 8, max = 72)
  public String password; // store only as strong hash elsewhere

  @Pattern(regexp = "^[+0-9()\\-\\s]{6,20}$", message = "invalid phone")
  public String phone;

  // helpers for canonicalization before validation (e.g., in controller)
  public void canonicalize() {
    username = InputValidation.canonicalize(username);
    email    = InputValidation.canonicalize(email);
    phone    = InputValidation.canonicalize(phone);
  }
}
```

```java
// SafeRepository.java  (Prepared statements only)
package com.example.security.input;

import java.sql.*;

public class SafeRepository {
  private final Connection conn;
  public SafeRepository(Connection conn) { this.conn = conn; }

  public void insertUser(String username, String email, String pwHash, String phone) throws SQLException {
    try (PreparedStatement ps = conn.prepareStatement(
        "INSERT INTO users(username,email,pw_hash,phone) VALUES(?,?,?,?)")) {
      ps.setString(1, username);
      ps.setString(2, email);
      ps.setString(3, pwHash);
      ps.setString(4, phone);
      ps.executeUpdate();
    }
  }

  public boolean existsByEmail(String email) throws SQLException {
    try (PreparedStatement ps = conn.prepareStatement("SELECT 1 FROM users WHERE email=?")) {
      ps.setString(1, email);
      try (ResultSet rs = ps.executeQuery()) { return rs.next(); }
    }
  }
}
```

```java
// Demo.java  (Putting it together)
package com.example.security.input;

import jakarta.validation.*;
import java.nio.file.Path;
import java.sql.*;
import java.util.Set;

public class Demo {
  public static void main(String[] args) throws Exception {
    // 1) Canonicalize + Bean Validation
    RegistrationDto dto = new RegistrationDto();
    dto.username = "  Alice.W_  ";
    dto.email = "Alice@example.com ";
    dto.password = "CorrectHorseBatteryStaple";
    dto.phone = " +1 (202) 555-0175 ";
    dto.canonicalize();

    Validator v = Validation.buildDefaultValidatorFactory().getValidator();
    Set<ConstraintViolation<RegistrationDto>> errors = v.validate(dto);
    if (!errors.isEmpty()) {
      errors.forEach(e -> System.out.println(e.getPropertyPath() + ": " + e.getMessage()));
      return;
    }

    // 2) Extra allow-list validation utilities
    String username = InputValidation.validateUsername(dto.username);
    String email    = InputValidation.validateEmail(dto.email);
    String phone    = InputValidation.validatePhone(dto.phone);

    // 3) Safe HTML handling for a bio field (rich text)
    String userHtmlBio = "<p>Hello <b>world</b><script>alert(1)</script></p>";
    String safeBio = InputValidation.sanitizeHtml(userHtmlBio); // script removed

    // 4) DB insert with prepared statements (no string concatenation)
    Connection conn = DriverManager.getConnection("jdbc:h2:mem:test;DB_CLOSE_DELAY=-1");
    try (Statement st = conn.createStatement()) {
      st.executeUpdate("create table users(id identity, username varchar(64), email varchar(254), pw_hash varchar(255), phone varchar(32))");
    }
    SafeRepository repo = new SafeRepository(conn);
    String pwHash = "$2y$12$example"; // store a real bcrypt/argon2 hash in production
    repo.insertUser(username, email, pwHash, phone);

    // 5) Safe file path resolution
    Path base = Path.of("/srv/uploads");
    Path file = InputValidation.safeResolve(base, "../etc/passwd"); // throws
  }
}
```

**Notes on the sample**

-   **Validation**: Jakarta Bean Validation covers common constraints; custom validators encapsulate allow-lists.
    
-   **Canonicalization**: enforces a predictable form before regex checks.
    
-   **Sanitization**: policy-based HTML cleaner; for rich HTML use **OWASP Java HTML Sanitizer** in production.
    
-   **Output encoding**: use OWASP Encoder per sink.
    
-   **SQL**: only **prepared statements**; never concatenate.
    
-   **Files**: prevent traversal by normalizing and verifying base-path prefix.
    

---

## Known Uses

-   Web/API forms and webhooks validation in virtually every internet-facing service.
    
-   Payment & checkout flows (strict formats, Luhn checks, length ranges).
    
-   CMS/markdown editors sanitizing user-generated content before storage/render.
    
-   Data ingestion pipelines validating CSV/JSON (schema + canonicalization) before ETL.
    
-   File upload services enforcing extensions/MIME + size + path constraints.
    

---

## Related Patterns

-   **Parameterized Queries / ORM Binding:** complements validation to prevent injection.
    
-   **Output Encoding (Context-Aware Escaping):** required at each sink.
    
-   **Data Masking:** reduce exposure in logs/UI after validation.
    
-   **Rate Limiting / WAF:** outer guardrails for abusive traffic.
    
-   **Content Security Policy (CSP):** mitigates XSS even if encoding fails.
    
-   **Schema Validation (JSON/XML/Protobuf):** structural validation at boundaries.
    

---

## Implementation Checklist

-   Define **field rules** (length, charset, regex, enums) and **schemas**; centralize them.
    
-   **Canonicalize** (NFC, trim, collapse) **before** validation; reject controls/nulls.
    
-   Use **allow-lists**; prefer libraries (Bean Validation, JSON Schema).
    
-   At every sink, apply **parameterization** (SQL, shell) or **context-specific encoding/sanitization** (HTML/URL/JS).
    
-   Enforce **safe file handling** (MIME sniffing, size limits, base-dir).
    
-   Provide **clear errors**; do not echo raw malicious payloads.
    
-   Add **structured logging** with masked values; keep raw payloads out of logs.
    
-   Unit-test with **fuzz/attack** cases (null bytes, overlong, RTL/Unicode, extremely long input).
    
-   Keep rules **consistent** across services (shared library/policy).

