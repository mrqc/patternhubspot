# Error Feedback — UI/UX Pattern

## Pattern Name and Classification

**Name:** Error Feedback  
**Category:** UI/UX · Input Validation · System Status/Notifications · Accessibility

## Intent

Communicate problems clearly, precisely, and at the right moment so users understand **what went wrong**, **where**, **why**, and **how to fix it**—without breaking flow.

## Also Known As

Inline Validation · Form Error Messages · Problem Details · Toast/Alert Errors · Validation Feedback

## Motivation (Forces)

-   **Clarity vs. brevity:** Users need actionable guidance without walls of text.
    
-   **Timing:** Immediate (inline) feedback keeps momentum; deferred (on submit) reduces noise.
    
-   **Context:** Field-level errors point to the exact place; global errors explain cross-field/system failures.
    
-   **Consistency:** Predictable message patterns and placements lower cognitive load.
    
-   **Accessibility:** Screen-reader friendly, keyboard focus management, and color-contrast compliance.
    
-   **Internationalization:** Localized messages, number/date formats, pluralization.
    
-   **Resilience:** Network/server errors must be handled as gracefully as client-side validation issues.
    
-   **Security:** Avoid leaking sensitive internals (stack traces, IDs).
    

## Applicability

Use this pattern when:

-   Collecting user input (forms, wizards, multi-step flows).
    
-   Displaying API/server-side errors (search failures, payment declines).
    
-   Guiding recovery from transient failures (timeouts, offline).
    

Avoid or scope carefully when:

-   Errors are irrecoverable and require a **dedicated error page** (e.g., 403/404/410 with navigation options).
    
-   High-sensitivity workflows where revealing specifics could aid attackers (limit detail).
    

## Structure

-   **Error Source:** Client validation, server validation, business rules, network/system faults.
    
-   **Error Target:** Field-level, form-level (global), page/app-level.
    
-   **Message Unit:** Short title, human-readable description, optional remediation hint, machine-readable code.
    
-   **Presentation:**
    
    -   Inline message beneath the field + visual affordance (icon, color, ARIA).
        
    -   Summary at top with anchor links to fields.
        
    -   Non-blocking toast for transient issues; modal only if a decision is required.
        
-   **State Management:** Error list, touched/dirty flags, submit attempts, retry tokens.
    
-   **Persistence:** Keep user input; never wipe fields on error.
    
-   **Logging/Telemetry:** Redacted server logs, metrics for error rates, fields with highest friction.
    

## Participants

-   **User:** Encounters and resolves issues.
    
-   **Validator(s):** Client and server rule engines.
    
-   **Presenter:** UI layer that renders messages and manages focus.
    
-   **Error Model:** Typed errors (code, field, message, parameters).
    
-   **Logger/Monitor:** Observability pipeline for triage and quality improvement.
    

## Collaboration

1.  User inputs data → client validator flags violations inline.
    
2.  On submit, server validates; returns structured errors (problem details).
    
3.  Presenter maps server errors to fields, shows summary, sets focus to the first error.
    
4.  Logger captures error codes/contexts (redacted), metrics power product improvements.
    
5.  User applies fixes and proceeds; errors clear automatically when resolved.
    

## Consequences

**Benefits**

-   Faster task completion, fewer support tickets.
    
-   Clear, consistent remediation improves trust.
    
-   Works across layers (client + server) and devices.
    

**Liabilities**

-   More UI states to design/test (valid/invalid/focused/disabled).
    
-   Internationalization and accessibility add complexity.
    
-   Poor mapping from server errors to fields creates confusion.
    

## Implementation

**Guidelines**

1.  **Layered validation:** Duplicate key rules on client and server; server is the source of truth.
    
2.  **Message style:** Imperative, specific, and actionable. Prefer “Enter a 10-digit phone number” over “Invalid input.”
    
3.  **Placement:** Inline beneath field; summary at top for multiple errors; do not rely solely on color.
    
4.  **Focus management:** On submit failure, move focus to the first error and set `aria-describedby` to its message.
    
5.  **Iconography & color:** Pair with text and adequate contrast (WCAG 2.2 AA+).
    
6.  **Persistence:** Retain inputs after failures; prefill on retries.
    
7.  **Error model:** Use machine-readable codes to map to localized strings.
    
8.  **Problem Details:** For APIs, use standardized envelopes (e.g., RFC 7807 / 9457 “problem+json”).
    
9.  **Security:** Strip stack traces and internals from user-facing errors; log safely server-side.
    
10.  **Observability:** Emit metrics (error rate by rule, step abandonment).
    

**Anti-Patterns**

-   Only red borders with no text.
    
-   Clearing fields after an error.
    
-   Vague “Something went wrong.” messages without recovery steps.
    
-   Modal storms for simple validation issues.
    

## Sample Code (Java)

Minimal Spring Boot example using Bean Validation and a `ProblemDetails`\-style response for server-side errors, plus field mapping.

```java
// src/main/java/com/example/validation/SignUpRequest.java
package com.example.validation;

import jakarta.validation.constraints.*;

public class SignUpRequest {
    @NotBlank(message = "{email.required}")
    @Email(message = "{email.invalid}")
    private String email;

    @NotBlank(message = "{password.required}")
    @Size(min = 12, message = "{password.tooShort}")
    private String password;

    @NotBlank(message = "{fullName.required}")
    @Size(max = 80, message = "{fullName.tooLong}")
    private String fullName;

    // getters/setters omitted for brevity
    public String getEmail() { return email; }
    public void setEmail(String email) { this.email = email; }
    public String getPassword() { return password; }
    public void setPassword(String password) { this.password = password; }
    public String getFullName() { return fullName; }
    public void setFullName(String fullName) { this.fullName = fullName; }
}
```

```java
// src/main/java/com/example/validation/ErrorField.java
package com.example.validation;

public class ErrorField {
    private String field;     // e.g., "email"
    private String code;      // e.g., "email.invalid"
    private String message;   // localized user-facing text

    public ErrorField() {}
    public ErrorField(String field, String code, String message) {
        this.field = field; this.code = code; this.message = message;
    }
    public String getField() { return field; }
    public String getCode() { return code; }
    public String getMessage() { return message; }
}
```

```java
// src/main/java/com/example/validation/Problem.java
package com.example.validation;

import java.net.URI;
import java.util.List;

/**
 * Simplified Problem Details body compatible with RFC 7807/9457.
 */
public class Problem {
    private URI type;         // machine-readable category
    private String title;     // short, human-readable summary
    private int status;
    private String detail;    // optional expanded text
    private String instance;  // request correlation id/path
    private List<ErrorField> errors; // field-level errors

    public Problem() {}
    public Problem(URI type, String title, int status, String detail,
                   String instance, List<ErrorField> errors) {
        this.type = type; this.title = title; this.status = status;
        this.detail = detail; this.instance = instance; this.errors = errors;
    }
    // getters omitted
    public URI getType() { return type; }
    public String getTitle() { return title; }
    public int getStatus() { return status; }
    public String getDetail() { return detail; }
    public String getInstance() { return instance; }
    public List<ErrorField> getErrors() { return errors; }
}
```

```java
// src/main/java/com/example/validation/SignUpController.java
package com.example.validation;

import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/signup")
public class SignUpController {

    @PostMapping
    public ResponseEntity<?> signUp(@Valid @RequestBody SignUpRequest req) {
        // Imagine business rule: email domain must be company.com
        if (!req.getEmail().toLowerCase().endsWith("@company.com")) {
            throw new BusinessRuleException("email.domainNotAllowed", "email");
        }
        // ... normal processing
        return ResponseEntity.noContent().build();
    }
}
```

```java
// src/main/java/com/example/validation/BusinessRuleException.java
package com.example.validation;

public class BusinessRuleException extends RuntimeException {
    private final String code;
    private final String field;

    public BusinessRuleException(String code, String field) {
        super(code);
        this.code = code;
        this.field = field;
    }
    public String getCode() { return code; }
    public String getField() { return field; }
}
```

```java
// src/main/java/com/example/validation/GlobalExceptionHandler.java
package com.example.validation;

import org.springframework.context.MessageSource;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.*;

import jakarta.servlet.http.HttpServletRequest;
import java.net.URI;
import java.util.*;
import java.util.stream.Collectors;

@ControllerAdvice
public class GlobalExceptionHandler {

    private final MessageSource messages;

    public GlobalExceptionHandler(MessageSource messages) {
        this.messages = messages;
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<Problem> handleValidation(MethodArgumentNotValidException ex,
                                                    Locale locale,
                                                    HttpServletRequest req) {
        List<ErrorField> fields = ex.getBindingResult()
                .getFieldErrors()
                .stream()
                .map(fe -> new ErrorField(
                        fe.getField(),
                        messageCode(fe),
                        localize(fe, locale)))
                .collect(Collectors.toList());

        Problem body = new Problem(
                URI.create("https://example.com/problems/validation"),
                "Validation failed",
                HttpStatus.UNPROCESSABLE_ENTITY.value(),
                "Please correct the highlighted fields.",
                req.getRequestURI(),
                fields
        );

        return ResponseEntity
                .status(HttpStatus.UNPROCESSABLE_ENTITY)
                .contentType(MediaType.APPLICATION_PROBLEM_JSON)
                .body(body);
    }

    @ExceptionHandler(BusinessRuleException.class)
    public ResponseEntity<Problem> handleBusiness(BusinessRuleException ex,
                                                  Locale locale,
                                                  HttpServletRequest req) {
        ErrorField field = new ErrorField(ex.getField(), ex.getCode(),
                localizeCode(ex.getCode(), locale, ex.getField()));
        Problem body = new Problem(
                URI.create("https://example.com/problems/business-rule"),
                "Business rule violation",
                HttpStatus.CONFLICT.value(),
                "A business rule prevents completing this action.",
                req.getRequestURI(),
                List.of(field)
        );
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .contentType(MediaType.APPLICATION_PROBLEM_JSON)
                .body(body);
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Problem> handleGeneric(Exception ex,
                                                 HttpServletRequest req) {
        Problem body = new Problem(
                URI.create("about:blank"),
                "Unexpected error",
                HttpStatus.INTERNAL_SERVER_ERROR.value(),
                "Please try again later. If the problem persists, contact support.",
                req.getRequestURI(),
                Collections.emptyList()
        );
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .contentType(MediaType.APPLICATION_PROBLEM_JSON)
                .body(body);
    }

    private String messageCode(FieldError fe) {
        // prefer the first code Spring provides (constraint), fallback to field
        if (fe.getCodes() != null && fe.getCodes().length > 0) {
            return fe.getCodes()[0];
        }
        return fe.getField() + ".invalid";
    }

    private String localize(FieldError fe, Locale locale) {
        String code = messageCode(fe);
        Object[] args = fe.getArguments() != null ? fe.getArguments() : new Object[]{};
        return messages.getMessage(code, args, fe.getDefaultMessage(), locale);
    }

    private String localizeCode(String code, Locale locale, String field) {
        return messages.getMessage(code, new Object[]{field}, code, locale);
    }
}
```

```properties
# src/main/resources/messages.properties (default locale)
email.required=Enter your email address.
email.invalid=Enter a valid email address.
password.required=Enter a password.
password.tooShort=Use at least 12 characters.
fullName.required=Enter your full name.
fullName.tooLong=Full name must be 80 characters or fewer.
email.domainNotAllowed=Use your company email address (e.g., name@company.com).
```

**Client Mapping (conceptual)**

-   On `422 Unprocessable Entity` with `application/problem+json`, iterate `errors[]` and attach each message below the corresponding field; set focus to the first.

-   On `409 Conflict` business-rule errors, also map the `field` if provided or show a global banner.


**Accessibility Tips**

-   Each invalid input: `aria-invalid="true"` and `aria-describedby="field-error-id"`.

-   Move keyboard focus to the first error on submit failure; make the summary an ARIA live region (`role="alert"`).

-   Do not rely on color alone; include icons/text.


## Known Uses

-   **Material Design / Fluent / Human Interface Guidelines:** Prescribe inline validation and error messaging patterns.

-   **Stripe & GitHub APIs:** Structured error responses with codes and documentation links.

-   **Large SaaS forms (Google, Microsoft, Atlassian, AWS):** Field-level + summary errors with focus management and preservation of user input.


## Related Patterns

-   **Form Validation** (client/server)

-   **Inline Hints & Help Text**

-   **Progressive Disclosure** (show details only when needed)

-   **Empty State & Empty Error** (no results vs. failure)

-   **Notification System** (toast, banners)

-   **Retry with Backoff** (for transient faults)

-   **Skeleton/Placeholder Loading** (distinguish loading from error)
