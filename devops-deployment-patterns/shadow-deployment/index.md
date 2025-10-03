
# Shadow Deployment — DevOps Deployment Pattern

---

## Pattern Name and Classification

-   **Name:** Shadow Deployment

-   **Category:** DevOps / Deployment / Progressive Delivery Pattern

-   **Level:** Deployment & Testing Strategy


---

## Intent

Deploy a new version of a service alongside the current production version, and **mirror live production traffic** to the new version without exposing its responses to users.  
This allows validation of performance, correctness, and scalability under **real workloads** before release.

---

## Also Known As

-   Traffic Mirroring

-   Dark Testing

-   Shadowing

-   Production Traffic Testing


---

## Motivation (Forces)

-   Staging/testing environments often fail to capture **real-world traffic patterns** and data diversity.

-   Traditional canary/blue-green approaches expose users to potential risk.

-   Shadow deployments allow running **real traffic in production infra** without impacting users.

-   Helps evaluate **latency, throughput, correctness, error handling**.


**Forces & trade-offs:**

-   Requires **traffic duplication** (load balancer, service mesh).

-   Shadow service responses must be discarded to avoid side effects.

-   Expensive: requires full duplicate infra for the shadow service.

-   Data integrity risk if shadow writes data (must be sandboxed).


---

## Applicability

Use Shadow Deployment when:

-   You need to validate **functional correctness** under real production input.

-   You want to test **performance and scalability** without user impact.

-   You need to evaluate a **major refactor, new algorithm, or new data store**.

-   You want to compare **metrics between old and new service versions**.


Avoid when:

-   Infra cost constraints prevent running duplicate services.

-   Shadow service has **side effects** (DB writes, external calls) that are hard to isolate.

-   Mirroring is not supported by load balancers/service mesh.


---

## Structure

1.  **Traffic Router (LB/Service Mesh):** Duplicates incoming requests.

2.  **Production Service (v1):** Responds to user.

3.  **Shadow Service (v2):** Processes mirrored traffic, response discarded or logged.

4.  **Observability/Analysis:** Metrics and logs compared between v1 and v2.


```pgsql
User Request
    │
[Load Balancer / Service Mesh]
    │───────────────► [Production Service v1] ─► Response to User
    │
    └───────────────► [Shadow Service v2] ─► Response discarded / logged
```

---

## Participants

-   **Load Balancer / Service Mesh:** Handles traffic mirroring.

-   **Production Service (v1):** Current live version.

-   **Shadow Service (v2):** Candidate version, not user-facing.

-   **Observability Tools:** Compare metrics, correctness, latency.

-   **Developers:** Analyze shadow logs to validate assumptions.

-   **SRE/Ops:** Monitor infra cost, performance impact.


---

## Collaboration

-   Works with **Canary Release** (once shadow passes validation, expose gradually).

-   Complements **Dark Launch** (hidden features + real traffic).

-   Relies on **Service Mesh Deployment** (Envoy, Istio, Linkerd for mirroring).

-   Uses **Immutable Infrastructure** for repeatable shadow service builds.


---

## Consequences

**Benefits**

-   Safe validation with **zero user impact**.

-   Real traffic exposure detects edge cases missed in tests.

-   Allows measurement of **performance differences**.

-   Facilitates large migrations (e.g., new DB engine, new framework).


**Liabilities**

-   Requires **duplicate infra** (costly).

-   Risk of **side effects** (shadow must not persist writes).

-   Complex to compare responses (deterministic vs nondeterministic behavior).

-   Can increase **latency** if traffic duplication overhead is high.


---

## Implementation

1.  **Deploy Shadow Version**

    -   Run candidate service in same cluster/environment.

    -   Isolate DB writes or use **sandbox DB**.

2.  **Configure Traffic Mirroring**

    -   Service mesh (Istio, Envoy) or API Gateway duplicates requests.

    -   Shadow receives mirrored traffic but responses are discarded.

3.  **Observability Setup**

    -   Collect **latency, throughput, error rates, logs**.

    -   Optionally, store responses for comparison against production.

4.  **Analyze & Decide**

    -   Validate correctness/performance.

    -   If shadow performs well, proceed with canary → full release.

5.  **Rollback Plan**

    -   If issues are detected, remove shadow service deployment.


---

## Sample Code

### Example: Java Spring Boot Shadow Service (v2)

```java
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/orders")
public class OrderController {

    @GetMapping
    public String getOrders() {
        // Business logic for new version
        return "Order Service v2 (shadow deployment)";
    }
}
```

### Example: Kubernetes Deployment (Shadow Version)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: order-service-v2
  labels:
    app: order-service
    version: v2
spec:
  replicas: 2
  selector:
    matchLabels:
      app: order-service
      version: v2
  template:
    metadata:
      labels:
        app: order-service
        version: v2
    spec:
      containers:
        - name: order-service
          image: registry.example.com/order-service:2.0.0
          ports:
            - containerPort: 8080
```

### Example: Istio VirtualService with Traffic Mirroring

```yaml
apiVersion: networking.istio.io/v1alpha3
kind: VirtualService
metadata:
  name: order-service
spec:
  hosts:
    - order-service
  http:
    - route:
        - destination:
            host: order-service
            subset: v1
          weight: 100        # all user traffic to v1
      mirror:
        host: order-service
        subset: v2           # shadow copy to v2
      mirrorPercentage:
        value: 100.0         # 100% traffic mirrored
```

---

## Known Uses

-   **Facebook & Google**: Use traffic shadowing to test new ranking/search algorithms.

-   **Netflix**: Shadows production traffic into new services to validate scale.

-   **Airbnb, Uber**: Shadow DB and service queries to new data stores during migration.

-   **Istio/Envoy** widely adopted for shadow deployments in Kubernetes.


---

## Related Patterns

-   **Canary Release:** Next step after shadowing proves stability.

-   **Dark Launch:** Hide features while they run under real traffic.

-   **Blue/Green Deployment:** Entire environment duplication, but visible switch.

-   **Service Mesh Deployment:** Enables traffic mirroring easily.

-   **Immutable Infrastructure:** Shadow version is immutable image.
