# Platform Team — Organizational Team Pattern

## Pattern Name and Classification

**Name:** Platform Team  
**Classification:** Organizational Team Pattern — Enabling & Infrastructure-Support Team (Team Topologies)

## Intent

Provide internal teams with a **self-service platform** of reusable services, tools, and paved roads that reduce cognitive load and enable stream-aligned teams to deliver features faster, safer, and with higher quality.

## Also Known As

-   Internal Platform Engineering Team
    
-   Developer Experience (DevEx) Team
    
-   Infrastructure as a Product Team
    
-   Foundation Services Team
    

## Motivation (Forces)

-   **Cognitive load:** Stream-aligned/feature teams cannot manage infrastructure, CI/CD, monitoring, and business logic simultaneously.
    
-   **Consistency vs. autonomy:** Teams want autonomy in delivery, but organizations need consistency in deployment pipelines, observability, and security.
    
-   **Economies of scale:** Centralizing common concerns (logging, build pipelines, container orchestration) saves effort and prevents reinvention.
    
-   **Security & compliance:** Guardrails ensure teams meet regulatory and security requirements by default.
    
-   **Accelerated delivery:** A usable, reliable platform accelerates feature teams rather than blocking them.
    

## Applicability

Use a Platform Team when:

-   Multiple product/stream-aligned teams require common infrastructure and practices.
    
-   Duplicated effort (CI/CD pipelines, auth libraries, monitoring setup) is slowing down delivery.
    
-   The organization struggles with inconsistent environments or non-standardized practices.
    
-   You want to provide **“golden paths”** that balance freedom with best practices.
    

Avoid if:

-   The organization is too small (informal sharing may suffice).
    
-   Platform is treated as a ticket-based ops team instead of a product team.
    

## Structure

```arduino
┌─────────────────────────┐
                        │     Leadership / CTO     │
                        └───────────┬─────────────┘
                                    │
                                    ▼
                           ┌───────────────┐
                           │  Platform Team │
                           │ (builds tools, │
                           │ APIs, services)│
                           └───────┬────────┘
                                   │
      ┌────────────────────────────┼───────────────────────────┐
      │                            │                           │
┌─────▼─────┐              ┌───────▼───────┐            ┌──────▼───────┐
│ Stream-    │              │ Stream-       │            │ Stream-       │
│ Aligned    │              │ Aligned       │            │ Aligned       │
│ Team A     │              │ Team B        │            │ Team C        │
└────────────┘              └───────────────┘            └───────────────┘
```

-   Platform Team → provides reusable capabilities.
    
-   Stream-Aligned Teams → consume platform as self-service.
    

## Participants

-   **Platform Engineers:** Build and maintain platform services (CI/CD, Kubernetes, observability, auth).
    
-   **Product Manager (Platform):** Treats platform as a product, defines roadmap, measures adoption.
    
-   **UX for Developers:** Ensures platform is intuitive and usable.
    
-   **Stream-Aligned Teams:** Consumers of platform services; provide feedback.
    

## Collaboration

-   **Platform as a product:** Engage with stream-aligned teams as customers.
    
-   **Feedback loops:** Regular surveys, office hours, guilds for platform adoption.
    
-   **Documentation & onboarding:** Clear guides, templates, and paved roads.
    
-   **Shared governance:** Work with security, compliance, and architecture for built-in guardrails.
    

## Consequences

**Benefits**

-   Reduced cognitive load for feature teams.
    
-   Higher velocity and consistency across teams.
    
-   Secure, compliant, and observable systems by default.
    
-   Centralized cost optimization for infrastructure.
    

**Liabilities / Trade-offs**

-   Risk of becoming a **ticket factory Ops team** if not product-oriented.
    
-   Requires investment in developer experience and support.
    
-   Poorly designed platform → low adoption, shadow platforms emerge.
    
-   May inadvertently reduce autonomy if guardrails become constraints.
    

## Implementation

1.  **Adopt a Product Mindset**
    
    -   Define the platform as an internal product.
        
    -   Assign a product manager to prioritize features based on user needs.
        
2.  **Identify Common Needs**
    
    -   Build golden pipelines, service templates, observability frameworks.
        
    -   Provide SDKs/libraries for auth, monitoring, error handling.
        
3.  **Start Small, Iterate**
    
    -   Deliver a minimal viable platform service (e.g., CI/CD pipeline).
        
    -   Expand capabilities incrementally (logging, metrics, secrets management).
        
4.  **Developer-Centric UX**
    
    -   Provide self-service portals and CLIs.
        
    -   Focus on documentation and “paved roads.”
        
5.  **Measure Adoption & Outcomes**
    
    -   Metrics: Deployment frequency, cognitive load surveys, platform usage.
        
    -   Use adoption as success criteria, not just feature delivery.
        
6.  **Avoid Pitfalls**
    
    -   Don’t force adoption; incentivize via ease of use.
        
    -   Avoid building “ivory tower” platforms disconnected from users.
        

## Sample Code (Java)

*Example: Platform Team provides a reusable library for standardized service health checks, consumed by product teams to reduce cognitive load.*

```java
// Platform-provided library
package com.company.platform.health;

import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthIndicator;

public class DatabaseHealthIndicator implements HealthIndicator {

    private final DatabaseClient dbClient;

    public DatabaseHealthIndicator(DatabaseClient dbClient) {
        this.dbClient = dbClient;
    }

    @Override
    public Health health() {
        try {
            dbClient.ping();
            return Health.up().withDetail("database", "reachable").build();
        } catch (Exception e) {
            return Health.down().withDetail("database", "unreachable").withException(e).build();
        }
    }
}

// Stream-aligned team consumes it in their service
package com.company.orders;

import com.company.platform.health.DatabaseHealthIndicator;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class HealthConfig {

    @Bean
    public DatabaseHealthIndicator dbHealth(DatabaseClient client) {
        return new DatabaseHealthIndicator(client);
    }
}
```

**Why this helps:**

-   Platform Team provides **reusable, standardized infrastructure code** (e.g., health indicators).
    
-   Stream-aligned teams integrate with minimal effort, focusing on business features instead of boilerplate.
    

## Known Uses

-   **Spotify:** Infrastructure squads evolved into platform teams to support squads with DevOps, CI/CD, and observability.
    
-   **Netflix:** Platform engineering teams provide tools like Spinnaker, Chaos Monkey, and paved roads.
    
-   **Google (SRE model):** SRE teams act as platform/product teams for reliability practices.
    
-   **Airbnb & Uber:** Developer productivity and platform engineering teams provide golden paths.
    

## Related Patterns

-   **Enabling Team:** Helps platform adoption but does not own long-term services.
    
-   **Stream-Aligned Team:** Primary consumer of platform services.
    
-   **Complicated Subsystem Team:** Specialized experts focusing on areas too complex for platform teams.
    
-   **Guilds and Chapters:** Share practices across teams, influencing platform features.
    
-   **Inverse Conway Maneuver:** Platform teams are often formed as part of aligning team structures with desired architecture.

