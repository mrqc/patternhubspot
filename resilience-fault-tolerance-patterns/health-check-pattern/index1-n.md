# Health Check — Resilience & Fault Tolerance Pattern

## Pattern Name and Classification

**Name:** Health Check  
**Classification:** Resilience / Fault-Tolerance / Operability Pattern (Observability & Control Plane)

---

## Intent

Continuously determine whether a service instance is **alive**, **ready**, and **healthy** so that load balancers, orchestrators, and dependents can make safe routing and recovery decisions (e.g., take instance out of rotation, restart it, or fail fast).

---

## Also Known As

-   Liveness/Readiness Probes
    
-   Self-Test Endpoint
    
-   Application Health Endpoint
    
-   Service Probe
    

---

## Motivation (Forces)

-   **Early failure detection:** You want failing instances removed before they cause user-visible errors.
    
-   **Traffic safety:** A service can be *alive* but not *ready* (e.g., warming caches, replaying events).
    
-   **Dependency fragility:** Downstream outages should surface as degraded health, not latent timeouts.
    
-   **Automated orchestration:** Platforms (Kubernetes, EC2 ASG, service meshes) need a binary signal.
    
-   **Observability:** Operators require an aggregated, human- and machine-readable health view.
    
-   **Least privilege:** Health must not expose secrets or heavy operations.
    
-   **Performance:** Checks should be fast and non-blocking to avoid causing the very outages they detect.
    

---

## Applicability

Use Health Check when:

-   Instances are behind a load balancer or orchestrator that can eject/restart nodes.
    
-   Startup has multi-step initialization (schema migration, warm-up, external connections).
    
-   You rely on external dependencies (DB, queues, caches, third-party APIs).
    
-   You deploy frequently and need safe rollout/rollback gates (blue/green, canary).
    
-   You provide a platform component that other teams depend on and need a simple “good/bad” signal.
    

---

## Structure

-   **Health Endpoint:** Lightweight HTTP (or gRPC) endpoint exposing health states.
    
-   **Checkers:** Small components verifying specific concerns (DB connectivity, disk, queue lag).
    
-   **Aggregator:** Combines results into overall status (e.g., `UP`, `DEGRADED`, `DOWN`) plus details.
    
-   **Policies:** Thresholds & time budgets (circuit-breaker state, retries, dependency SLOs).
    
-   **Consumers:** Load balancers, schedulers, service discovery, synthetic monitors.
    

---

## Participants

-   **Prober/Client:** LB, K8s kubelet, service discovery, uptime robot.
    
-   **Health Endpoint (Server):** Returns status with minimal overhead.
    
-   **Health Checkers:** Pluggable tests for dependencies and internal state.
    
-   **Health Aggregator:** Reduces checker results to a canonical status and payload.
    
-   **Operator/Developer:** Reads details/logs/metrics to act on failures.
    

---

## Collaboration

1.  **Prober** periodically calls `/health` (or `/live` & `/ready`).
    
2.  **Endpoint** invokes relevant **Checkers** with strict timeouts.
    
3.  **Aggregator** merges results, applies **Policies**, returns status code + JSON body.
    
4.  **Prober** uses result to route traffic or restart the instance; **Operator** inspects details and metrics.
    

---

## Consequences

**Benefits**

-   Faster fault isolation and automatic remediation (ejection, restart).
    
-   Safer rollouts via readiness gating.
    
-   Clear operational contract; improved MTTR and availability.
    
-   Foundation for SLOs and dashboards.
    

**Liabilities**

-   False positives/negatives if checks are too strict/lenient.
    
-   Over-eager checks can overload dependencies (N \* instances \* frequency).
    
-   Long or blocking checks can create self-inflicted outages.
    
-   Information leakage risk if verbose details are exposed publicly.
    

---

## Implementation

**Key Decisions**

-   **Separate endpoints:**
    
    -   **Liveness** (`/live`): “process not dead/looping”. **Never** depend on externals.
        
    -   **Readiness** (`/ready`): “safe to receive traffic”. May include dependency checks.
        
    -   **Health** (`/health`): Optional consolidated operational view.
        
-   **Timeouts & budgets:** Per-checker deadlines and overall response SLA (e.g., ≤ 100 ms).
    
-   **Degradation policy:** Mark `DEGRADED` for partial failures; keep serving read-only, etc.
    
-   **Security:** Expose status code publicly; restrict detailed payload (mTLS, auth, network policy).
    
-   **Frequency:** Tune probe intervals to avoid thundering herds.
    
-   **Idempotence & lightness:** No side effects; fast, cached where safe.
    

**Anti-Patterns**

-   Doing heavy queries or full dependency pings every probe.
    
-   Coupling liveness to external systems (may kill healthy pods during dependencies’ outages).
    
-   Returning 200 OK with “OK” string only—machines need structured payloads.
    
-   Hiding failures to “stay green”; it only defers outages to users.
    

---

## Sample Code (Java, Spring Boot with Actuator)

```java
// build.gradle (snip)
// implementation 'org.springframework.boot:spring-boot-starter-actuator'
// implementation 'org.springframework.boot:spring-boot-starter-web'
// implementation 'org.springframework.boot:spring-boot-starter-data-jdbc' // if using a DB
```

```java
// src/main/java/com/example/health/App.java
package com.example.health;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class App {
  public static void main(String[] args) {
    SpringApplication.run(App.class, args);
  }
}
```

```java
// src/main/java/com/example/health/check/DatabaseHealthIndicator.java
package com.example.health.check;

import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
public class DatabaseHealthIndicator implements HealthIndicator {
  private final JdbcTemplate jdbc;

  public DatabaseHealthIndicator(JdbcTemplate jdbc) {
    this.jdbc = jdbc;
  }

  @Override
  public Health health() {
    try {
      // lightweight ping; avoid heavy queries
      Integer one = jdbc.queryForObject("select 1", Integer.class);
      boolean ok = (one != null && one == 1);
      return ok ? Health.up().withDetail("db", "reachable").build()
                : Health.down().withDetail("db", "unexpected result").build();
    } catch (Exception e) {
      return Health.down(e).withDetail("db", "unreachable").build();
    }
  }
}
```

```java
// src/main/java/com/example/health/check/QueueLagHealthIndicator.java
package com.example.health.check;

import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.stereotype.Component;

// Example: pretend we read a lightweight lag metric from memory/cache
@Component("eventQueue") // name appears in /health details
public class QueueLagHealthIndicator implements HealthIndicator {

  // typically injected from a metrics registry or lightweight client
  private long currentLag() { return 42L; }

  @Override
  public Health health() {
    long lag = currentLag();
    if (lag < 100) {
      return Health.up().withDetail("lag", lag).build();
    } else if (lag < 1000) {
      return Health.status("DEGRADED").withDetail("lag", lag).build();
    } else {
      return Health.down().withDetail("lag", lag).build();
    }
  }
}
```

```java
// src/main/java/com/example/health/probes/Probes.java
package com.example.health.probes;

import org.springframework.boot.actuate.health.HealthEndpoint;
import org.springframework.boot.actuate.health.Status;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

// Optional: explicit lightweight liveness/readiness endpoints
@RestController
@RequestMapping("/probe")
public class Probes {

  private final HealthEndpoint healthEndpoint;

  public Probes(HealthEndpoint healthEndpoint) {
    this.healthEndpoint = healthEndpoint;
  }

  // Liveness: purely process/self checks; do NOT call external systems here
  @GetMapping("/live")
  public ResponseEntity<String> live() {
    // If the thread can return here, process is alive
    return ResponseEntity.ok("LIVE");
  }

  // Readiness: reuse actuator 'health' but typically a reduced set via group
  @GetMapping("/ready")
  public ResponseEntity<String> ready() {
    var health = healthEndpoint.healthForPath("readiness"); // uses health group
    Status status = health.getStatus();
    return new ResponseEntity<>(status.getCode(), status.equals(Status.UP) ? 200 : 503);
  }
}
```

```yaml
# src/main/resources/application.yml
management:
  endpoints:
    web:
      exposure:
        include: "health,info"
  endpoint:
    health:
      show-details: when_authorized
      probes:
        enabled: true      # adds /actuator/health/liveness & /actuator/health/readiness
  health:
    defaults:
      enabled: true
# Define health groups to separate readiness checks (include only safe, fast dependencies)
management:
  endpoint:
    health:
      group:
        readiness:
          include: db, eventQueue
```

**Behavior**

-   `/actuator/health/liveness` → returns **UP** if process is responsive.

-   `/actuator/health/readiness` or `/probe/ready` → **UP** only if DB and queue indicators pass.

-   `/actuator/health` → aggregated payload (restricted details unless authorized).


**Notes**

-   Keep checks **fast** and **non-blocking**; apply small per-checker timeouts (e.g., via client config).

-   Prefer cached/metric signals (e.g., last successful ping time) over live heavy probes.

-   Protect details (e.g., behind auth) if the endpoint is internet-exposed.


---

## Known Uses

-   **Kubernetes** liveness/readiness probes to gate traffic and restarts.

-   **AWS ALB/NLB** target health checks to unregister failing instances.

-   **Service Meshes (Istio/Linkerd)** for traffic shifting during canary and faults.

-   **Platform Health Dashboards** aggregating Actuator health across microservices.


---

## Related Patterns

-   **Circuit Breaker:** Downstream failures trip breaker; readiness reflects breaker state.

-   **Bulkhead:** Health may include pool/saturation checks for isolated compartments.

-   **Timeouts & Retries:** Feed into health degradation based on failure rates.

-   **Graceful Degradation:** Health can surface partial capability states.

-   **Blue/Green & Canary Release:** Readiness gates during rollout.

-   **Heartbeat (Monitoring):** External active checks complement internal health endpoints.
