# Service Per Team — Microservice Pattern

## Pattern Name and Classification

-   **Name:** Service Per Team
    
-   **Classification:** Organization & Ownership Pattern (Team Topology / Conway’s Law alignment)
    

## Intent

Align **service boundaries** with **long-lived, autonomous teams** so each team **owns a product-shaped service** end-to-end (design, code, data, deploy, operate). This maximizes flow, accountability, and independent evolution.

## Also Known As

-   **You Build It, You Run It**
    
-   **Two-Pizza Team Service Ownership**
    
-   **Team-Aligned Service**
    

## Motivation (Forces)

-   **Conway’s Law:** System structure mirrors communication structure; reflect team boundaries explicitly in architecture.
    
-   **Speed vs. Coupling:** Shared ownership slows change; dedicated ownership keeps deploys independent.
    
-   **Accountability:** Clear DRI for reliability, cost, security, and roadmap.
    
-   **Cognitive Load:** Small, cohesive services match the team’s capacity.
    
-   **Autonomy:** Teams pick fit-for-purpose stacks/persistence within guardrails (platform standards).
    

**Tensions**

-   **Consistency vs. Freedom:** Too much autonomy → fragmentation; too little → central bottlenecks.
    
-   **Duplication:** Intentional duplication beats accidental coupling, but must be governed.
    
-   **Org Change:** Team reshuffles ripple through ownership and service maps.
    
-   **Platform Maturity:** Without a strong platform, per-team ops toil explodes.
    

## Applicability

Use when:

-   Multiple cross-functional teams deliver a product platform.
    
-   Frequent, independent releases are required.
    
-   You can staff **on-call** and **operational ownership** per team.
    

Reconsider when:

-   Very small org or single product line—team per service may be overkill (modular monolith may suffice).
    
-   Strong centralized workflows (e.g., regulated batch systems) make end-to-end ownership impractical.
    

## Structure

-   **One bounded context** (domain) → **one service** → **one owning team**.
    
-   **Team-owned repo + pipeline + runtime**; platform provides paved roads.
    
-   **Service contract** (API/events/SLOs) mediates collaboration; no shared database.
    

```pgsql
[Platform Team] ── paved-road (CI/CD, mesh, observability, security, cost)

  Team A (Orders)   Team B (Billing)   Team C (Catalog)
     │  owns Svc A     │  owns Svc B      │  owns Svc C
     ├── repo, DB       ├── repo, DB       ├── repo, DB
     └── on-call        └── on-call        └── on-call

Collaboration via APIs/events, not shared DB or internal classes.
```

## Participants

-   **Owning Team:** Cross-functional squad (dev, QA, Ops/SRE, product) accountable for SLOs, cost, and security.
    
-   **Service:** Code + data + infrastructure + runbooks.
    
-   **Platform Team:** Provides the golden path (ID, auth, deploy, mesh, observability, runtime policies).
    
-   **Boundary Artifacts:** API specs, event schemas, SLOs, error budgets, ADRs.
    
-   **Service Catalog:** Registry of owners, docs, dashboards, runbooks.
    

## Collaboration

1.  Team publishes **stable contracts** (OpenAPI/AsyncAPI) and **SLOs**.
    
2.  Consumers integrate via **APIs/events**; changes go through **versioning & deprecation** policies.
    
3.  Platform enforces **guardrails** (policy as code, cost/showback, security baselines).
    
4.  Incidents route to **the owning team**; postmortems refine contracts and alerts.
    

## Consequences

**Benefits**

-   **Flow efficiency:** Independent roadmaps, releases, and schema changes.
    
-   **Clear ownership:** Faster incident response and decision-making.
    
-   **Quality & reliability:** Feedback loops sit with the team responsible.
    
-   **Scalability of organization:** Add teams → add services; reduce cross-team contention.
    

**Liabilities**

-   **Inconsistency risk:** APIs/logging/metrics diverge without standards.
    
-   **Duplication:** Some patterns/logic re-implemented across teams.
    
-   **Siloing:** Poor product thinking may fragment UX/data.
    
-   **Operational load:** Each team must be mesh/observability-literate (mitigate with platform).
    

## Implementation

1.  **Define ownership in the catalog:** Every service has an owner, on-call rotation, dashboards, runbooks, SLOs.
    
2.  **Align to bounded contexts:** Use DDD to slice domains; avoid cross-team shared DBs.
    
3.  **Guardrails, not gates:** Paved-road templates (build/deploy, logging, metrics, tracing, security, cost tags).
    
4.  **Contracts & versioning:** OpenAPI/AsyncAPI, semantic versioning, deprecation windows, contract tests.
    
5.  **Access boundaries:** Enforce via network policies, IAM, and schema permissions.
    
6.  **Quality bars:** Linting, API governance, security checks, ArchUnit rules for boundaries.
    
7.  **Observability SLOs:** Standard metrics (latency, error rate, saturation) + trace context propagation.
    
8.  **Cost visibility:** Tag infra by service/team; showback to owners.
    
9.  **Runbooks & incident response:** Pager duty, dashboards, auto-rollbacks, chaos drills.
    
10.  **Evolution:** When team reshapes, transfer ownership cleanly (docs, dashboards, on-call, IAM, domains).
    

---

## Sample Code (Java) — Ownership metadata, boundary guardrails, and architectural rules

> Three practical snippets you can drop into a Spring-Boot service owned by a team:
> 
> 1.  **Typed team metadata** exposed via a small endpoint (feeds service catalog / runbooks).
>     
> 2.  **Dependency guard** to prevent “sneaky” calls to non-declared services (keeps boundaries honest).
>     
> 3.  **ArchUnit test** to enforce package boundaries across teams.
>     

### 1) Team metadata (ownership endpoint)

```java
// TeamProperties.java
package ownership.meta;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;
import jakarta.validation.constraints.NotBlank;

import java.util.List;

@Validated
@ConfigurationProperties(prefix = "team")
public class TeamProperties {
  @NotBlank private String name;
  @NotBlank private String oncall;          // e.g., pager alias
  @NotBlank private String chat;            // e.g., Slack/Teams channel
  @NotBlank private String email;           // team mailbox
  @NotBlank private String service;         // canonical service name
  private List<String> domains;             // bounded contexts
  private String ownerId;                   // cost/showback tag

  // getters/setters...
}
```

```java
// OwnershipConfig.java
package ownership.meta;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;

@Configuration
@EnableConfigurationProperties(TeamProperties.class)
public class OwnershipConfig { }
```

```java
// OwnershipController.java
package ownership.meta;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;
import java.util.Map;

@RestController
@RequestMapping("/__owner")
public class OwnershipController {

  private final TeamProperties team;
  public OwnershipController(TeamProperties team) { this.team = team; }

  @Value("${info.git.commit.id:unknown}") private String gitCommit;
  @Value("${info.app.version:unknown}")  private String version;

  @GetMapping
  public Map<String, Object> owner() {
    return Map.of(
      "service", team.getService(),
      "team", team.getName(),
      "email", team.getEmail(),
      "chat", team.getChat(),
      "oncall", team.getOncall(),
      "domains", team.getDomains(),
      "ownerId", team.getOwnerId(),
      "version", version,
      "commit", gitCommit
    );
  }
}
```

```yaml
# application.yml (example)
team:
  name: "Orders Team"
  service: "orders-service"
  email: "orders-team@example.com"
  chat: "#orders-oncall"
  oncall: "orders-pager"
  ownerId: "cost-center-4711"
  domains: [ "Sales", "Ordering" ]

info:
  app:
    version: 1.12.3
```

### 2) Outbound dependency guard (whitelist service calls)

```java
// AllowedDependenciesProperties.java
package ownership.guard;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.List;

@ConfigurationProperties(prefix = "service.dependencies")
public class AllowedDependenciesProperties {
  /** host patterns your team is allowed to call, e.g. ["^catalog\\..*\\.svc\\.cluster\\.local$", "^payment\\..*$"] */
  private List<String> allowedHosts;
  public List<String> getAllowedHosts() { return allowedHosts; }
  public void setAllowedHosts(List<String> allowedHosts) { this.allowedHosts = allowedHosts; }
}
```

```java
// DependencyGuardInterceptor.java
package ownership.guard;

import org.springframework.http.HttpRequest;
import org.springframework.http.client.*;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.net.URI;
import java.util.List;
import java.util.regex.Pattern;

@Component
public class DependencyGuardInterceptor implements ClientHttpRequestInterceptor {
  private final List<Pattern> allowed;
  public DependencyGuardInterceptor(AllowedDependenciesProperties cfg) {
    this.allowed = cfg.getAllowedHosts().stream().map(Pattern::compile).toList();
  }

  @Override
  public ClientHttpResponse intercept(HttpRequest req, byte[] body, ClientHttpRequestExecution exec) throws IOException {
    URI uri = req.getURI();
    String host = uri.getHost() == null ? "" : uri.getHost();
    boolean ok = allowed.stream().anyMatch(p -> p.matcher(host).find());
    if (!ok) {
      throw new IllegalStateException("Outbound call to [" + host + "] not in declared dependencies. " +
        "Add pattern to service.dependencies.allowed-hosts or refactor integration.");
    }
    return exec.execute(req, body);
  }
}
```

```java
// RestTemplateConfig.java
package ownership.guard;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.*;
import org.springframework.web.client.RestTemplate;

@Configuration
@EnableConfigurationProperties(AllowedDependenciesProperties.class)
public class RestTemplateConfig {
  @Bean
  RestTemplate restTemplate(DependencyGuardInterceptor guard) {
    RestTemplate rt = new RestTemplate();
    rt.getInterceptors().add(guard);
    return rt;
  }
}
```

```yaml
# application.yml (add)
service:
  dependencies:
    allowed-hosts:
      - "^catalog\\.shop\\.svc\\.cluster\\.local$"
      - "^payment\\.shop\\.svc\\.cluster\\.local$"
```

### 3) Architectural rule (ArchUnit) to enforce team boundary in code

```java
// src/test/java/arch/TeamBoundaryRulesTest.java
package arch;

import com.tngtech.archunit.core.importer.ImportOption;
import com.tngtech.archunit.junit.*;
import com.tngtech.archunit.lang.ArchRule;

import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.noClasses;

/**
 * Example: the Orders service code must not depend on internal classes of other teams' modules,
 * such as 'billing..' or 'inventory..' (only public API clients allowed).
 */
@AnalyzeClasses(packages = "com.example", importOptions = { ImportOption.DoNotIncludeTests.class })
public class TeamBoundaryRulesTest {

  @ArchTest
  public static final ArchRule orders_should_not_depend_on_other_teams =
      noClasses().that().resideInAPackage("..orders..")
                 .should().dependOnClassesThat().resideInAnyPackage("..billing..", "..inventory..");
}
```

> These guardrails make “Service Per Team” tangible: ownership is visible, dependencies are declared, and boundaries are enforced in CI.

---

## Known Uses

-   **Amazon** “two-pizza” teams with product-shaped services and strong on-call ownership.

-   **Netflix** and **Spotify** squads/tribes: service per squad with paved-road platforms, SLOs, and incident DRIs.

-   Large enterprises adopting **platform engineering** + **service catalogs** (e.g., Backstage) to codify ownership and golden paths.


## Related Patterns

-   **Bounded Context (DDD):** Conceptual seams that map to team-owned services.

-   **Database per Service:** Data ownership aligns with team ownership.

-   **Polyglot Persistence:** Teams choose best-fit stores within platform guardrails.

-   **API Gateway / BFF:** Encapsulates team services behind stable edges.

-   **Consumer-Driven Contracts:** Keep inter-team integrations robust.

-   **Externalized Configuration:** Team-controlled behavior without rebuilds.

-   **Service Mesh:** Uniform runtime policy; teams focus on business logic.

-   **SLO/Error Budgets:** Ownership backed by measurable reliability targets.
