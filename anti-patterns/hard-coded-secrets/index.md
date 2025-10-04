# Hard Coded Secrets

---

## Overview

**Type:** Software Security Antipattern  
**Category:** Configuration / Security / Deployment Antipattern  
**Context:** Occurs when sensitive information such as passwords, API keys, encryption keys, tokens, or database credentials is directly embedded in the source code, configuration files, or version control history.

---

## Intent

To describe the **security risk and maintenance hazard** of embedding secrets directly into application code or version-controlled files.  
This practice exposes systems to unauthorized access, data breaches, and compliance violations — often leading to catastrophic consequences when secrets leak publicly (e.g., on GitHub or CI logs).

The “Hard Coded Secrets” antipattern undermines confidentiality, scalability, and proper DevSecOps practices.

---

## Also Known As

-   **Embedded Credentials**
    
-   **Secrets in Code**
    
-   **Configuration in Source**
    
-   **Static Secrets**
    
-   **Key in Codebase**
    

---

## Motivation (Forces)

Developers often embed credentials in code for convenience or to avoid complex configuration setups during development or testing.  
However, this shortcut leads to **long-term vulnerabilities**, as credentials become exposed to everyone with code access — including repositories, logs, and CI/CD pipelines.

Common motivations and forces include:

-   **Convenience:** Easier to embed credentials for quick testing.
    
-   **Lack of secrets management tools:** No infrastructure for secure storage.
    
-   **Time pressure:** Security practices perceived as overhead.
    
-   **Limited awareness:** Developers underestimate exposure risk.
    
-   **Legacy code:** Credentials committed historically and forgotten.
    
-   **CI/CD pipelines not secured:** Secrets hardcoded to avoid environment config errors.
    

---

## Applicability

You are likely dealing with **Hard Coded Secrets** if:

-   The source code contains visible strings like passwords, tokens, or keys.
    
-   The same credential is used across multiple environments (dev, test, prod).
    
-   Version control history reveals credentials in commits.
    
-   Applications fail when secrets are rotated.
    
-   Static code analysis or scanners flag exposed secrets.
    
-   Build or deployment scripts include credentials inline.
    

---

## Structure

```css
[Source Code]
   ↓
   [Hardcoded Secret] → [Version Control Repository]
                            ↓
                    [Developers / CI / External Access]
                            ↓
                     [Potential Exposure]
```

A single leaked repository or misconfigured CI environment can expose all connected systems.

---

## Participants

| Participant | Description |
| --- | --- |
| **Developer** | Embeds secrets directly into code or configuration for simplicity. |
| **Version Control System** | Stores code and secrets permanently, even after deletion. |
| **Build and Deployment Pipelines** | Unintentionally expose secrets in logs or artifacts. |
| **Attackers** | Exploit leaked credentials for unauthorized access. |
| **Security Teams** | Must detect, revoke, and rotate compromised secrets. |

---

## Collaboration

-   A developer hardcodes credentials (e.g., database password) in the codebase.
    
-   Code is committed to a repository (Git, SVN).
    
-   Other developers clone or fork the repo, spreading exposure.
    
-   Automated systems (CI/CD) build and deploy code, logging secrets accidentally.
    
-   If the repository is ever made public, attackers can instantly extract credentials using scanning tools.
    

---

## Consequences

### Negative Consequences

-   **Security Breach:** Exposed secrets can lead to system compromise, data theft, or service abuse.
    
-   **Non-compliance:** Violates regulations such as GDPR, PCI-DSS, or ISO 27001.
    
-   **High cost of incident response:** Secret revocation, rotation, and audit.
    
-   **Harder secret rotation:** Secrets buried in code require recompilation and redeployment.
    
-   **Propagation of exposure:** Forks, backups, and CI logs spread the secrets further.
    
-   **Loss of trust:** Users and partners lose confidence after exposure incidents.
    

### (Occasional) Positive Consequences

-   **Immediate convenience:** Quicker setup during local development.
    
-   **Predictable behavior:** Works without external configuration.
    

However, these benefits are extremely short-lived and far outweighed by the security risks.

---

## Root Causes

-   **Lack of secure secret storage (Vault, AWS Secrets Manager, etc.).**
    
-   **No environment configuration strategy.**
    
-   **Inexperienced developers unaware of security practices.**
    
-   **Improper access control and code review processes.**
    
-   **Legacy codebases without refactoring or secret rotation.**
    

---

## Refactored Solution (How to Avoid Hard Coded Secrets)

### 1\. **Use Environment Variables**

-   Store secrets in environment variables instead of source code.
    
-   Load them dynamically during runtime.
    

```java
public class DatabaseConnection {
    public static Connection connect() throws SQLException {
        String dbUrl = System.getenv("DB_URL");
        String dbUser = System.getenv("DB_USER");
        String dbPassword = System.getenv("DB_PASSWORD");
        return DriverManager.getConnection(dbUrl, dbUser, dbPassword);
    }
}
```

### 2\. **Leverage Secrets Management Systems**

-   Use tools designed for secret lifecycle management:
    
    -   **HashiCorp Vault**
        
    -   **AWS Secrets Manager**
        
    -   **Azure Key Vault**
        
    -   **Google Secret Manager**
        
-   Integrate them via secure SDKs or APIs.
    

```java
import com.amazonaws.services.secretsmanager.*;
import com.amazonaws.services.secretsmanager.model.*;

public class AwsSecretFetcher {
    public static String getSecret(String secretName) {
        AWSSecretsManager client = AWSSecretsManagerClientBuilder.standard().build();
        GetSecretValueRequest request = new GetSecretValueRequest().withSecretId(secretName);
        GetSecretValueResult result = client.getSecretValue(request);
        return result.getSecretString();
    }
}
```

### 3\. **Use Configuration Files Outside of Source Control**

-   Store secrets in external config files or encrypted key stores.
    
-   Use `.gitignore` to ensure these files are never committed.
    

### 4\. **Encrypt Secrets at Rest and in Transit**

-   Always encrypt configuration files or environment variables that contain sensitive data.
    
-   Use key management systems (KMS) for encryption keys.
    

### 5\. **Automate Secret Rotation**

-   Periodically rotate credentials and revoke old ones automatically.
    
-   Avoid manual rotation, which often leads to mistakes.
    

### 6\. **Implement Static Secret Scanning**

-   Integrate tools into CI/CD pipelines to detect exposed secrets early:
    
    -   **TruffleHog**
        
    -   **GitLeaks**
        
    -   **GitGuardian**
        
    -   **AWS CodeGuru Security**
        

---

## Example (Java)

### Hard Coded Secret Example

```java
public class PaymentProcessor {
    private static final String API_KEY = "sk_test_1234567890abcdef"; // ❌ BAD PRACTICE

    public void processPayment(double amount) {
        System.out.println("Processing payment with key: " + API_KEY);
        // Call to external API...
    }
}
```

Here the secret (API key) is directly embedded in code.  
If this code is committed to GitHub, the key can be easily harvested by attackers using automated scanning tools.

---

### Refactored Secure Example

```java
public class PaymentProcessor {
    private static final String API_KEY = System.getenv("PAYMENT_API_KEY");

    public void processPayment(double amount) {
        if (API_KEY == null || API_KEY.isEmpty()) {
            throw new IllegalStateException("API key not configured");
        }
        System.out.println("Processing payment securely.");
        // Secure API call using key loaded from environment
    }
}
```

This code dynamically loads the secret from the runtime environment — preventing exposure in source control and allowing secure rotation.

---

## Detection Techniques

-   **Static Code Scanners:**
    
    -   Tools like *TruffleHog*, *GitLeaks*, *GitGuardian*, and *SonarQube Security Rules* detect secrets in repositories.
        
-   **Regex-based Scanning:**
    
    -   Custom scripts detect common patterns (e.g., “AKIA\[0-9A-Z\]{16}” for AWS keys).
        
-   **Git Hooks:**
    
    -   Pre-commit hooks that block commits containing potential secrets.
        
-   **Continuous Monitoring:**
    
    -   Integrate scanning tools into CI/CD pipelines for every push.
        

---

## Known Uses

-   **Mobile apps** embedding API keys in client code.
    
-   **Java enterprise systems** with JDBC URLs and credentials hardcoded.
    
-   **Open-source libraries** accidentally leaking production keys.
    
-   **Cloud deployments** where configuration files were uploaded with plaintext secrets.
    
-   **Legacy systems** using static encryption keys in code for decades.
    

---

## Related Patterns

-   **Secrets Management Pattern** – Centralized, dynamic management of secrets.
    
-   **Configuration Externalization Pattern** – Move environment-specific details out of code.
    
-   **Environment-Specific Configuration Pattern** – Use environment variables or configuration servers.
    
-   **Security by Design Principle** – Integrate security early, not as an afterthought.
    
-   **Zero Trust Principle** – Assume all environments are potentially hostile.
    

---

## Summary

The **Hard Coded Secrets** antipattern represents one of the most common — and dangerous — security pitfalls in software engineering.  
While embedding credentials in code might simplify early development, it **destroys confidentiality** and **violates basic security hygiene**.

Preventing it requires adopting **secure configuration practices**, **secrets management tools**, and **automated scanning** to detect leaks before they become breaches.

Security is not about hiding keys in code — it’s about **never putting them there in the first place.**

