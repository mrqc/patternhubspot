
# Rolling Updates — DevOps Deployment Pattern

---

## Pattern Name and Classification

-   **Name:** Rolling Updates

-   **Category:** DevOps / Deployment / Release Strategy Pattern

-   **Level:** Application & Infrastructure Deployment Pattern


---

## Intent

Deploy a new version of an application **gradually, one instance at a time (or in small batches)**, while keeping the service available. Older instances are terminated only after new ones are successfully running, ensuring **zero downtime**.

---

## Also Known As

-   Incremental Deployment

-   Gradual Upgrade

-   Staggered Deployment


---

## Motivation (Forces)

-   **High availability:** Users should not experience downtime.

-   **Progressive risk reduction:** Not all instances are updated at once.

-   **Scalability:** Works with clusters and auto-scaled systems.

-   **Cost optimization:** No need to double infra (unlike Blue/Green).


**Forces & trade-offs:**

-   Slower rollout compared to all-at-once.

-   If new version has a systemic bug, all updated instances may fail progressively.

-   Requires load balancing and health checks.

-   Handling **stateful sessions** is harder (may need sticky sessions or session replication).


---

## Applicability

Use Rolling Updates when:

-   The application is **stateless** or supports quick failover.

-   The system must remain **continuously available** during updates.

-   You operate in **clustered/containerized environments** (Kubernetes, ECS, ASG).

-   You can handle **partial traffic** with old and new versions simultaneously.


Avoid when:

-   Apps are **stateful** without session migration.

-   Version skew is not supported (old and new instances cannot coexist).

-   You require **instant switchover** (use Blue/Green instead).


---

## Structure

1.  **Load Balancer / Service Mesh:** Routes requests to healthy instances.

2.  **Deployment Controller:** Orchestrates rollout (Kubernetes Deployment, AWS ECS, etc.).

3.  **Update Strategy:**

    -   Replace one pod/VM at a time.

    -   Optionally define batch size (e.g., 25% of replicas).

4.  **Health Checks:** Verify readiness of new instances before terminating old ones.


```scss
[Load Balancer]
     │
 ┌───┴───────────────┐
 │                   │
[Old v1 Instances]   [New v2 Instances]
 (shrinking set)       (growing set)
```

---

## Participants

-   **Deployment Controller:** Automates instance replacement.

-   **Load Balancer / Service Mesh:** Ensures only healthy nodes receive traffic.

-   **CI/CD Pipeline:** Triggers rollout after build/test success.

-   **Developers/Operators:** Configure rollout policy (batch size, pause, max surge).

-   **Monitoring/Alerting Systems:** Detect regressions during rollout.


---

## Collaboration

-   Often combined with **Canary Releases** (update small % of nodes, validate, then continue).

-   Can work with **Feature Toggles** for safe enablement after deploy.

-   Complements **Immutable Infrastructure** — each rollout uses new images.

-   Uses **Infrastructure as Code** to define rollout strategies declaratively.


---

## Consequences

**Benefits**

-   Zero downtime upgrades.

-   Efficient resource usage (no duplicate environment like Blue/Green).

-   Easy rollback by reversing rollout.

-   Transparent to users.


**Liabilities**

-   Rollout time can be long.

-   Risk of mixed-version state if incompatible protocols/DB migrations.

-   More operational complexity (requires readiness/liveness probes).

-   Requires **rollback automation** if errors detected mid-rollout.


---

## Implementation

1.  **Define Deployment Strategy**

    -   Configure batch size (e.g., `maxUnavailable=1`, `maxSurge=1`).

    -   Ensure readiness/liveness probes for health checks.

2.  **Prepare New Image**

    -   Build & push to registry (`myapp:v2`).

3.  **Update Deployment Descriptor**

    -   Change image tag in Kubernetes Deployment (or ECS service).

4.  **Orchestrator Action**

    -   Starts new pods → runs readiness checks → reroutes traffic → removes old pods.

5.  **Rollback**

    -   If new version fails, rollout automatically stops and reverts to last stable image.


---

## Sample Code (Java + Kubernetes Example)

### Step 1: Java Service

```java
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/version")
public class VersionController {
    @GetMapping
    public String version() {
        return "MyApp v2.0.0 (rolling update)";
    }
}
```

### Step 2: Dockerfile

```dockerfile
FROM eclipse-temurin:17-jdk-alpine
WORKDIR /app
COPY target/myapp-2.0.0.jar app.jar
ENTRYPOINT ["java", "-jar", "app.jar"]
```

### Step 3: Kubernetes Deployment with Rolling Update Strategy

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
  namespace: prod
spec:
  replicas: 4
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1         # allow one extra pod during update
      maxUnavailable: 1   # only one pod down at a time
  selector:
    matchLabels:
      app: myapp
  template:
    metadata:
      labels:
        app: myapp
    spec:
      containers:
        - name: myapp
          image: registry.example.com/myapp:2.0.0
          ports:
            - containerPort: 8080
          readinessProbe:   # ensure only ready pods get traffic
            httpGet:
              path: /actuator/health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
```

### Step 4: Rollback Example

```bash
kubectl rollout undo deployment/myapp
```

---

## Known Uses

-   **Kubernetes Deployments** default to RollingUpdate strategy.

-   **AWS ECS/Fargate** supports rolling replacement of tasks.

-   **AWS Auto Scaling Groups** allow rolling replacements of EC2 instances.

-   **Netflix** and other cloud-native companies widely use rolling updates for microservices.


---

## Related Patterns

-   **Canary Release:** Smaller subset update + verification before full rollout.

-   **Blue/Green Deployment:** Two complete environments switched instantly.

-   **Immutable Infrastructure:** Ensures new nodes are clean builds during rollout.

-   **Feature Toggle / Dark Launch:** Control feature visibility after rolling deploy.

-   **A/B Testing:** Similar coexistence of multiple versions, but with controlled cohorts.
