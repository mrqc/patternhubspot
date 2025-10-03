# Blue-Green Deployment — Microservice Pattern

## Pattern Name and Classification

**Name:** Blue-Green Deployment  
**Classification:** Microservices / Deployment & Release Management / Zero-Downtime Deployment Pattern

## Intent

Deploy a new version of a service or system **side-by-side** with the current version (blue = live, green = idle or new), then **switch traffic atomically** to the new version. This reduces downtime and risk, and enables fast rollback if issues occur.

## Also Known As

-   Zero-Downtime Deployment
    
-   Red/Black Deployment (alternative naming, popularized by Netflix/Spinnaker)
    
-   Parallel Deployment
    

## Motivation (Forces)

-   **User expectations:** Continuous availability, no downtime during upgrades.
    
-   **Operational risk:** New releases may fail; must allow **instant rollback**.
    
-   **Consistency:** Smooth switch avoids partial upgrades or client confusion.
    
-   **Testing in production:** Green environment allows verification under production-like load before cutover.
    

**Forces & Challenges**

-   **Cost:** Running duplicate environments requires extra resources.
    
-   **Stateful systems:** Must handle DB migrations and session state carefully.
    
-   **Coordination:** Traffic routing, DNS, load balancer, or service mesh control must be precise.
    

## Applicability

Use Blue-Green Deployment when:

-   You want **fast, low-risk deployments** with rollback capability.
    
-   Infrastructure can support **duplicated environments** (cloud/k8s/VMs).
    
-   DB changes are backward-compatible or handled with versioning strategies.
    

Avoid or reconsider when:

-   Operating in highly stateful monoliths without DB migration strategy.
    
-   Infrastructure cost prohibits duplicate environments.
    

## Structure

-   **Blue Environment:** Currently serving all production traffic (stable version).
    
-   **Green Environment:** New version, deployed but not yet live.
    
-   **Traffic Router (Load Balancer / Ingress / Service Mesh):** Controls which environment receives requests.
    
-   **Monitoring & Health Checks:** Ensure green is healthy before switching.
    

```pgsql
+------------------+
Clients -> |  Load Balancer   | --> [ Blue Service v1 ] (live)
          +------------------+
                             \--> [ Green Service v2 ] (staging)
```

After switch:

```scss
Clients -> [ Green Service v2 ] (live)
           [ Blue Service v1 ] (idle/rollback)
```

## Participants

-   **Blue Environment (v1):** Current production version.
    
-   **Green Environment (v2):** New version to be deployed.
    
-   **Router/Load Balancer:** Shifts traffic atomically or gradually.
    
-   **CI/CD Pipeline:** Builds, deploys, and verifies environments.
    
-   **Monitoring/Alerting:** Observes metrics and verifies cutover health.
    

## Collaboration

1.  CI/CD pipeline builds and deploys **green** environment.
    
2.  Automated tests and health checks run against green.
    
3.  Router (load balancer, ingress, DNS) is reconfigured to send **all traffic to green**.
    
4.  Monitor for errors; if issues occur, revert router back to blue instantly.
    
5.  Once stable, blue environment can be decommissioned or kept for rollback.
    

## Consequences

**Benefits**

-   Near-zero downtime deployments.
    
-   Simple, fast rollback by switching back.
    
-   Enables real production validation before cutover.
    
-   Predictable, controlled deployment strategy.
    

**Liabilities**

-   Requires **duplicate infrastructure**, increasing cost.
    
-   Complex with **stateful services** (e.g., DB migrations, sticky sessions).
    
-   Cutover is atomic (all-or-nothing); no partial rollout (unlike canary).
    
-   Monitoring and automation must be reliable to avoid outages.
    

## Implementation

**Key practices**

-   Use **immutable infrastructure** (containers, VM images).
    
-   Deploy new version into **green** while **blue** remains live.
    
-   Run smoke tests, integration tests, and **synthetic traffic** on green.
    
-   Shift traffic by:
    
    -   Updating **load balancer target groups**.
        
    -   Changing **service mesh routing**.
        
    -   Flipping **DNS alias/record**.
        
-   Rollback by switching router back to blue.
    
-   Handle **database migrations** with versioned, backward-compatible schema changes.
    
-   Automate with CI/CD pipelines (Jenkins, Spinnaker, ArgoCD, GitLab).
    

---

## Sample Code (Java — Spring Boot App + Deployment Toggle)

Below is a minimalistic illustration:

-   A Spring Boot REST service with version identifier.
    
-   Deployment uses a configuration flag (`DEPLOYMENT_COLOR`) to distinguish blue vs green.
    
-   Load balancer (not shown in code) directs traffic to either version.
    

```java
// build.gradle dependencies
// implementation 'org.springframework.boot:spring-boot-starter-web'

import org.springframework.boot.*;
import org.springframework.boot.autoconfigure.*;
import org.springframework.web.bind.annotation.*;

@SpringBootApplication
public class DemoServiceApp {
    public static void main(String[] args) {
        SpringApplication.run(DemoServiceApp.class, args);
    }
}

@RestController
class VersionController {
    private final String color;

    public VersionController() {
        // Deployment color provided via env var
        this.color = System.getenv().getOrDefault("DEPLOYMENT_COLOR", "blue");
    }

    @GetMapping("/version")
    public String version() {
        return "Service is running in " + color.toUpperCase() + " environment";
    }
}
```

### Deployment Example (Kubernetes YAML — blue & green services)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: service-blue
spec:
  replicas: 2
  selector:
    matchLabels:
      app: demo
      color: blue
  template:
    metadata:
      labels:
        app: demo
        color: blue
    spec:
      containers:
        - name: demo
          image: myrepo/demo-service:v1
          env:
            - name: DEPLOYMENT_COLOR
              value: "blue"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: service-green
spec:
  replicas: 2
  selector:
    matchLabels:
      app: demo
      color: green
  template:
    metadata:
      labels:
        app: demo
        color: green
    spec:
      containers:
        - name: demo
          image: myrepo/demo-service:v2
          env:
            - name: DEPLOYMENT_COLOR
              value: "green"
---
apiVersion: v1
kind: Service
metadata:
  name: demo-service
spec:
  selector:
    app: demo
    color: blue # switch to green when ready
  ports:
    - port: 80
      targetPort: 8080
```

> Switching traffic is done by updating the **Service selector** from `color: blue` to `color: green`.

---

## Known Uses

-   **Netflix (Spinnaker):** Popularized red/black deployments for rapid rollback.
    
-   **Amazon/AWS:** ELB + Auto Scaling Group cutover with blue/green.
    
-   **Kubernetes:** Service selectors or Istio/Linkerd routing rules.
    
-   **Banking & e-commerce platforms:** High availability upgrades without downtime.
    

## Related Patterns

-   **Canary Release:** Gradual rollout to subset of users vs. atomic switch.
    
-   **Feature Toggle:** Hide new features until ready, often combined with blue-green.
    
-   **Rolling Update:** Replace pods gradually instead of duplicate environment.
    
-   **Immutable Infrastructure:** Build once, deploy many; avoids in-place upgrades.
    
-   **Shadow Deployment:** Deploy new version, send it traffic without exposing to users.

