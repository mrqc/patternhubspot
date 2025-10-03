# Externalized Configuration — Microservice Pattern

## Pattern Name and Classification

-   **Name:** Externalized Configuration
    
-   **Classification:** Operational & Deployment Pattern for Microservices (12-Factor “Config”)
    

## Intent

Move all environment-specific settings (endpoints, credentials, limits, feature flags, timeouts, etc.) **out of the application binary** so you can change behavior **without rebuilding or redeploying** code and promote the *same* artifact across environments safely.

## Also Known As

-   Runtime Configuration
    
-   Out-of-Process Configuration
    
-   Centralized Configuration (when using a config service)
    

## Motivation (Forces)

-   **Promote once, run everywhere:** The same artifact must work in dev/test/stage/prod.
    
-   **Separation of concerns:** Code belongs in the artifact; **secrets, URLs, limits** belong in the environment.
    
-   **Operational agility:** Tune timeouts/feature flags instantly; rotate secrets without rollouts.
    
-   **Security:** Keep secrets out of source control and images; apply least privilege and rotation.
    
-   **Governance & audit:** Central stores provide versioning, approvals, and change logs.
    

**Tensions**

-   **Where to store config?:** Files, env vars, config servers, secret managers—often a mix.
    
-   **Dynamic vs. static:** Some values can refresh live; others require restart for safety.
    
-   **Consistency & precedence:** Multiple sources (file, env, server) require deterministic override order.
    
-   **Drift risks:** Per-service overrides may diverge across environments without guardrails.
    

## Applicability

Use when:

-   Services are deployed across **multiple environments/regions**.
    
-   You need **fast toggles** (feature flags, circuit thresholds, query limits).
    
-   You must **rotate secrets** (DB/API keys) regularly.
    
-   Teams deploy the **same image** to many tenants/markets.
    

Maybe skip when:

-   Small monolith, single environment, low compliance needs (a single app.properties may suffice).
    
-   You cannot provide a reliable config distribution/refresh plane.
    

## Structure

-   **Service** reads configuration **at startup** and optionally **watches** for updates.
    
-   **Config Sources (ordered):** defaults in code → packaged config → environment variables → config server → secret manager.
    
-   **Refresh agent** (optional) triggers live updates for whitelisted properties.
    
-   **Audit & policy** layer governs who can change what, where, and when.
    

```sql
+------------------+
          |  Config Server   |◄──── Admins / Git (versioned)
          +------------------+ \
                                 \ OTLP/HTTP/Watch
  +----------+     env vars        \              +------------------+
  |  Secret  |-----------------------> Service    |  Metrics/Alerts  |
  | Manager  |  files/configMaps  /  /            +------------------+
  +----------+--------------------/  /
                         +--------------+
                         |   Service    |
                         |  @Config...  |
                         +--------------+
```

## Participants

-   **Service / Config Client:** Loads and binds config to typed objects.
    
-   **Config Store:** Git-backed (e.g., Spring Cloud Config), Consul, etcd, Zookeeper, SSM Parameter Store.
    
-   **Secret Manager:** Vault, AWS Secrets Manager, Azure Key Vault, KMS-backed stores.
    
-   **Refresh Agent / Bus:** Propagates change notifications (e.g., Spring Cloud Bus, Consul watch, Kubernetes reloader).
    
-   **Policy & Audit:** RBAC, change approvals, versioning, and rollbacks.
    

## Collaboration

1.  **Bootstrap:** On startup, the service resolves sources in a **known precedence** (e.g., env vars override packaged defaults).
    
2.  **Bind & Validate:** Values bind to typed config with bean validation; startup fails if invalid.
    
3.  **Runtime Refresh (optional):** On change, refreshable beans are re-instantiated or values updated atomically.
    
4.  **Secret Rotation:** The secret manager rotates; service re-reads seamlessly (short-lived caches).
    
5.  **Observability:** Config values (non-sensitive) are exposed for diagnostics; changes are logged and audited.
    

## Consequences

**Benefits**

-   **Zero-redeploy tweaks**; safer rollouts across environments.
    
-   **Security posture:** Secrets out of code and CI logs; centralized rotation.
    
-   **Compliance:** Versioned, auditable changes.
    
-   **Standardization:** Consistent key naming and precedence reduce surprises.
    

**Liabilities**

-   **Operational complexity:** You must run a **config plane** that is secure and highly available.
    
-   **Failure modes:** If config server is down at bootstrap, services may fail to start; you need fallbacks.
    
-   **Runtime hazard:** Hot-reloading critical values (e.g., pool sizes) can destabilize if not guarded.
    
-   **Drift:** Environment-specific overrides can diverge without policy/validation.
    

## Implementation

1.  **Define precedence** (clear contract): packaged defaults < file < env vars < config server < secrets.
    
2.  **Typed config + validation:** Use `@ConfigurationProperties` (Spring) or MicroProfile Config with `@NotNull`, ranges, patterns. Fail fast on invalid values.
    
3.  **Segment keys:** `domain.feature.property` (e.g., `orders.rate-limit.max-rps`).
    
4.  **Separate secrets from non-secrets:** Secrets in secret manager; non-secrets in config server/ConfigMap.
    
5.  **Hot vs. cold:** Mark which properties are **refreshable**; require restart for the rest.
    
6.  **Secure distribution:** mTLS to the config server; encrypt at rest; narrow IAM/RBAC.
    
7.  **Fallbacks:** Cache last-known-good; start with defaults if remote store unavailable (configurable).
    
8.  **Observability:** Expose a safe `/actuator/configprops` or `/config` view; never leak secrets.
    
9.  **Promotion workflow:** Git-Ops for config; PR review, CI validation, auto-sync to config store.
    
10.  **Testing:** Contract tests assert presence and shape of required keys; chaos tests simulate missing/invalid config.
    

---

## Sample Code (Java, Spring Boot 3.x + Spring Cloud, refreshable + validated config)

### `pom.xml` (snippets)

```xml
<dependencies>
  <dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-web</artifactId>
  </dependency>
  <dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-validation</artifactId>
  </dependency>
  <dependency>
    <groupId>org.springframework.cloud</groupId>
    <artifactId>spring-cloud-starter-config</artifactId>
  </dependency>
  <!-- Optional: broadcast refresh events (Kafka/Rabbit) -->
  <dependency>
    <groupId>org.springframework.cloud</groupId>
    <artifactId>spring-cloud-starter-bus-kafka</artifactId>
  </dependency>
  <!-- Optional: metadata for @ConfigurationProperties (no runtime cost) -->
  <dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-configuration-processor</artifactId>
    <optional>true</optional>
  </dependency>
</dependencies>
```

### `application.yml` (packaged defaults)

```yaml
spring:
  application:
    name: orders-service
  # Modern config client bootstrap via Config Data API
  config:
    import: "optional:configserver:http://config:8888"

management:
  endpoints:
    web:
      exposure:
        include: health,info,env,configprops,refresh

orders:
  rate-limit:
    max-rps: 200        # sensible default, can be overridden
  pricing:
    base-url: http://localhost:8081
  features:
    new-pricing: false
  db:
    url: jdbc:postgresql://localhost:5432/orders
    user: orders
    # password intentionally absent (pulled from secret)
```

### Environment overrides (examples)

-   **Env vars** (highest precedence over file and config server):
    

```bash
export ORDERS_RATE_LIMIT_MAX_RPS=500
export ORDERS_PRICING_BASE_URL=https://pricing.prod.svc.cluster.local
export SPRING_DATASOURCE_PASSWORD_FILE=/var/run/secrets/db_password  # mounted secret file
```

-   **Kubernetes** (snippet for ConfigMap & Secret mounting):
    

```yaml
apiVersion: v1
kind: ConfigMap
metadata: { name: orders-config }
data:
  application.yaml: |
    orders:
      features:
        new-pricing: true
---
apiVersion: v1
kind: Secret
metadata: { name: orders-secrets }
stringData:
  db_password: "s3cr3t"
---
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      containers:
      - name: orders
        env:
        - name: SPRING_CONFIG_IMPORT
          value: optional:configserver:http://config:8888
        - name: ORDERS_RATE_LIMIT_MAX_RPS
          valueFrom: { configMapKeyRef: { name: orders-config, key: ORDERS_RATE_LIMIT_MAX_RPS } }
        volumeMounts:
        - name: secrets
          mountPath: /var/run/secrets
          readOnly: true
      volumes:
      - name: secrets
        secret: { secretName: orders-secrets }
```

### Typed configuration with validation and refresh

```java
// OrdersProperties.java
package com.example.config;

import jakarta.validation.constraints.*;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.cloud.context.config.annotation.RefreshScope;
import org.springframework.validation.annotation.Validated;

@Validated
@RefreshScope // allows runtime refresh of this bean (when a refresh event is received)
@ConfigurationProperties(prefix = "orders")
public class OrdersProperties {

  private final RateLimit rateLimit = new RateLimit();
  private final Pricing pricing = new Pricing();
  private final Features features = new Features();
  private final Db db = new Db();

  public RateLimit getRateLimit() { return rateLimit; }
  public Pricing getPricing() { return pricing; }
  public Features getFeatures() { return features; }
  public Db getDb() { return db; }

  public static class RateLimit {
    @Min(1) @Max(10_000)
    private int maxRps = 200;
    public int getMaxRps() { return maxRps; }
    public void setMaxRps(int maxRps) { this.maxRps = maxRps; }
  }

  public static class Pricing {
    @NotBlank
    private String baseUrl = "http://localhost:8081";
    public String getBaseUrl() { return baseUrl; }
    public void setBaseUrl(String baseUrl) { this.baseUrl = baseUrl; }
  }

  public static class Features {
    private boolean newPricing = false;
    public boolean isNewPricing() { return newPricing; }
    public void setNewPricing(boolean newPricing) { this.newPricing = newPricing; }
  }

  public static class Db {
    @NotBlank private String url;
    @NotBlank private String user;
    // password is sourced from secret file/env; do not expose via /configprops
    private String password;
    public String getUrl() { return url; }
    public void setUrl(String url) { this.url = url; }
    public String getUser() { return user; }
    public void setUser(String user) { this.user = user; }
    public String getPassword() { return password; }
    public void setPassword(String password) { this.password = password; }
  }
}
```

```java
// ConfigBootstrap.java
package com.example.config;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;

@Configuration
@EnableConfigurationProperties(OrdersProperties.class)
public class ConfigBootstrap { }
```

```java
// RateLimiter.java (uses refreshable properties)
package com.example.runtime;

import com.example.config.OrdersProperties;
import org.springframework.cloud.context.config.annotation.RefreshScope;
import org.springframework.stereotype.Component;
import java.util.concurrent.Semaphore;

@RefreshScope
@Component
public class RateLimiter {

  private final OrdersProperties props;
  private volatile Semaphore tokens;

  public RateLimiter(OrdersProperties props) {
    this.props = props;
    this.tokens = new Semaphore(props.getRateLimit().getMaxRps());
  }

  // Called by Spring Cloud on refresh: bean is re-instantiated with new props
  public boolean tryAcquire() {
    return tokens.tryAcquire();
  }
}
```

```java
// OrdersController.java
package com.example.api;

import com.example.config.OrdersProperties;
import com.example.runtime.RateLimiter;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/orders")
public class OrdersController {
  private final OrdersProperties cfg;
  private final RateLimiter limiter;

  public OrdersController(OrdersProperties cfg, RateLimiter limiter) {
    this.cfg = cfg;
    this.limiter = limiter;
  }

  @GetMapping("/config")
  public Object currentConfig() {
    // never return secrets; only safe values
    return java.util.Map.of(
      "maxRps", cfg.getRateLimit().getMaxRps(),
      "pricingBaseUrl", cfg.getPricing().getBaseUrl(),
      "newPricing", cfg.getFeatures().isNewPricing()
    );
  }

  @GetMapping("/{id}")
  public String get(@PathVariable String id) {
    if (!limiter.tryAcquire()) throw new TooManyRequests("rate limit exceeded");
    // call pricing using cfg.getPricing().getBaseUrl()...
    return "ok:" + id;
  }

  static class TooManyRequests extends RuntimeException { TooManyRequests(String m){super(m);} }
}
```

```properties
# Actuator refresh (POST /actuator/refresh) with Spring Cloud Context or via Spring Cloud Bus
management.endpoints.web.exposure.include=health,info,env,configprops,refresh
```

**Refresh flow (options):**

-   **Pull:** `POST /actuator/refresh` on the service after updating env/Config Server.

-   **Push (bus):** Commit to Git → Config Server webhook → Bus broadcasts refresh → `@RefreshScope` beans rebind.


> **Security note:** protect `/actuator/refresh` with auth, network policy, and rate limits.

---

### Optional: MicroProfile Config variant (Jakarta EE)

```java
// AppConfig.java
import org.eclipse.microprofile.config.inject.ConfigProperty;
import jakarta.enterprise.context.ApplicationScoped;

@ApplicationScoped
public class AppConfig {
  @ConfigProperty(name = "orders.rate-limit.max-rps", defaultValue = "200")
  int maxRps;
  @ConfigProperty(name = "orders.pricing.base-url")
  String pricingBaseUrl;
}
```

*Backed by env vars, system properties, config files, plus extensions for Vault/Consul in your runtime (Quarkus/Helidon/Payara).*

---

## Known Uses

-   **Spring Cloud Config** (Git-backed) with `@RefreshScope` in many enterprises.

-   **Netflix Archaius** (historical) powering dynamic properties at scale.

-   **Kubernetes ConfigMaps/Secrets** + sidecar reloaders (e.g., Reloader, Stakater) for hot updates.

-   **HashiCorp Vault** / **AWS Secrets Manager** / **GCP Secret Manager** with auto-rotation.

-   **Consul** / **etcd** as centralized KV with watches for dynamic config.


## Related Patterns

-   **12-Factor App (Config):** Foundational principle this pattern operationalizes.

-   **Feature Flags / Toggles:** A specialized, dynamic subset of externalized config.

-   **Circuit Breaker / Bulkhead / Timeout & Retry:** Their thresholds are prime candidates for externalization.

-   **Service Discovery:** Often configured via externalized endpoints.

-   **Blue-Green / Canary:** Driven by external flags and environment-specific configuration.

-   **Secrets Management:** Complements externalized config by isolating sensitive values and rotation policies.
