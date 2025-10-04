# Auto Scaling Group — Scalability Pattern

## Pattern Name and Classification

**Name:** Auto Scaling Group (ASG)  
**Classification:** Scalability / Elasticity / Capacity Management (Infrastructure & Control Plane)

---

## Intent

Automatically **add or remove compute instances** to keep capacity aligned with demand and SLOs, while optimizing **cost** and **availability**.

---

## Also Known As

-   Elastic Scaling Group
    
-   Cluster Autoscaling (IaaS)
    
-   Managed Instance Group (GCP), Virtual Machine Scale Set (Azure)
    
-   Server Fleet Autoscaling
    

---

## Motivation (Forces)

-   **Demand volatility:** Workload varies by time-of-day, launches, incidents.
    
-   **SLO pressure:** Need enough instances to hit latency/throughput targets.
    
-   **Cost efficiency:** Avoid paying for idle capacity; scale-in when demand drops.
    
-   **Failure resilience:** Replace unhealthy instances automatically; spread across AZs.
    
-   **Heterogeneity:** Different instance types/architectures, mixed purchase options (on-demand/spot) for cost and resilience.
    

---

## Applicability

Use an Auto Scaling Group when:

-   Your workload is **horizontally scalable** (stateless or sharded state).
    
-   Instances are **replaceable** from a template (AMI/Launch Template/Image).
    
-   You can expose **health checks** (LB/K8s readiness) and handle rolling updates.
    
-   You want **policy-driven** elasticity (metrics, schedules, predictive).
    

Avoid or adapt when:

-   The system is **stateful** without replication/migration (session stickiness, local disks).
    
-   **Cold start** times are long relative to demand spikes (pre-warm or buffer via queues).
    
-   Strict per-node **affinity** or unique state prevents replacement.
    

---

## Structure

-   **Launch Template/Configuration:** Image + instance type + user data + security settings.
    
-   **Auto Scaling Group:** Desired/Min/Max capacity, subnets/AZs, health checks.
    
-   **Scaling Policies:** Target tracking (e.g., 50% CPU), step scaling, scheduled actions, predictive.
    
-   **Load Balancer / Target Group:** Routes traffic; health drives instance lifecycle.
    
-   **Health Monitors:** ELB health, EC2 status checks, app health via agents.
    
-   **Lifecycle Hooks:** Entering/Exiting states for graceful bootstrap/drain.
    
-   **Mixed Instances / Purchase Options:** Spot + OnDemand, allocation strategies.
    
-   **Warm Pools / Instance Refresh:** Pre-warmed capacity, rolling image updates.
    

---

## Participants

-   **Controller (ASG service):** Applies policies, replaces instances.
    
-   **Instances (Workers):** Serve traffic; publish health & metrics.
    
-   **Metrics Source:** CloudWatch/Prometheus feeding policies.
    
-   **Load Balancer:** Distributes load and ejects unhealthy targets.
    
-   **Operators/Automation:** Define policies, alarms, schedules.
    

---

## Collaboration

1.  **Metrics** cross a threshold or target (e.g., average CPU > 60%).
    
2.  **Scaling policy** decides to scale out/in (respecting cool-downs and min/max).
    
3.  **ASG** launches or terminates instances using the **Launch Template**; attaches to **Target Groups**.
    
4.  **Lifecycle hooks** allow bootstrap and graceful drain before termination.
    
5.  **Health checks** continuously replace bad instances; **Instance Refresh** rolls the fleet for new images.
    

---

## Consequences

**Benefits**

-   Elastic capacity → better **SLOs** and **cost** control.
    
-   Improved **availability** via multi-AZ spreading and health replacement.
    
-   Declarative, repeatable infrastructure.
    

**Liabilities**

-   **Scale lag** during sudden spikes (cold starts); may need buffers or step policies.
    
-   Risk of **thrashing** if policies are too aggressive (oscillation).
    
-   Requires **statelessness** or careful state externalization (sessions, caches, data).
    
-   Spot interruptions if using mixed purchase options (mitigate with diversity + interruption handling).
    

---

## Implementation

### Key Decisions

-   **Scaling signal:** CPU, ALB request count/target, queue depth, custom latency, RPS.
    
-   **Policy type:**
    
    -   **Target tracking** (recommended): maintain metric near a target.
        
    -   **Step scaling:** discrete add/remove at thresholds.
        
    -   **Scheduled:** known diurnal patterns.
        
    -   **Predictive:** forecasted demand (provider-specific).
        
-   **Bounds:** `min <= desired <= max` sized from capacity planning; enforce **cooldowns** and **instance warm-up**.
    
-   **Health source:** ELB + application readiness; avoid marking *booting* instances as unhealthy.
    
-   **Graceful scale-in:** connection draining, deregistration delay, lifecycle hook to drain queues.
    
-   **Mixed instances:** diversify types/AZs; set **allocation strategy** (e.g., capacity-optimized for Spot).
    
-   **Rollouts:** use **Instance Refresh** (or rolling updates) tied to Launch Template version.
    
-   **Observability:** alarms for **inadequate capacity**, **insufficient instance quota**, **scaling error**, **thrash detection**.
    

### Anti-Patterns

-   Scaling on **CPU only** for IO-bound/latency-bound services without checking **p95 latency**.
    
-   No **cooldown/warmup**, leading to oscillations.
    
-   Tying **state** to instance local disk; losing data on replacement.
    
-   Ignoring **graceful drain** → 5xx spikes during scale-in.
    
-   One AZ/subnet → single-AZ outage takes you down.
    

---

## Sample Code (Java, AWS SDK v2)

Below shows how to: (1) create a **Target Tracking** scaling policy for CPU 50%, (2) update desired capacity, and (3) register a **scale-in protection** window via lifecycle hook. Assumes ASG and Launch Template already exist.

```java
// build.gradle (snip)
// implementation 'software.amazon.awssdk:autoscaling:2.25.0'
// implementation 'software.amazon.awssdk:cloudwatch:2.25.0'
// implementation 'software.amazon.awssdk:regions:2.25.0'

import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.autoscaling.AutoScalingClient;
import software.amazon.awssdk.services.autoscaling.model.*;
import java.time.Duration;

public class AsgDemo {

  private final AutoScalingClient asg = AutoScalingClient.builder()
      .region(Region.EU_CENTRAL_1) // choose your region
      .build();

  /** Create or update a Target Tracking policy: keep average CPU near 50%. */
  public void putTargetTrackingPolicy(String asgName) {
    TargetTrackingConfiguration ttc = TargetTrackingConfiguration.builder()
        .predefinedMetricSpecification(PredefinedMetricSpecification.builder()
            .predefinedMetricType(PredefinedMetricResourceType.ASG_AVERAGE_CPU_UTILIZATION)
            .build())
        .targetValue(50.0)                // target CPU %
        .disableScaleIn(false)
        .estimatedInstanceWarmup(120)     // seconds (align with app bootstrap)
        .build();

    PutScalingPolicyResponse resp = asg.putScalingPolicy(PutScalingPolicyRequest.builder()
        .autoScalingGroupName(asgName)
        .policyName("cpu-50-target-tracking")
        .policyType(PolicyTypeEnum.TARGET_TRACKING_SCALING)
        .targetTrackingConfiguration(ttc)
        .build());

    System.out.println("Policy ARN: " + resp.policyARN());
  }

  /** Adjust desired capacity within min/max bounds (manual nudge or during incidents). */
  public void setDesiredCapacity(String asgName, int desired, boolean honorCooldown) {
    asg.setDesiredCapacity(SetDesiredCapacityRequest.builder()
        .autoScalingGroupName(asgName)
        .desiredCapacity(desired)
        .honorCooldown(honorCooldown)
        .build());
  }

  /** Add a lifecycle hook for scale-in drain (e.g., deregister from LB, drain queue). */
  public void putScaleInHook(String asgName, String hookName, String snsOrSqsArn) {
    PutLifecycleHookRequest req = PutLifecycleHookRequest.builder()
        .autoScalingGroupName(asgName)
        .lifecycleHookName(hookName)
        .lifecycleTransition(LifecycleTransition.INSTANCE_TERMINATING.toString())
        .heartbeatTimeout(300)   // seconds to complete drain
        .defaultResult("ABANDON") // if hook times out, proceed or abandon
        .notificationTargetARN(snsOrSqsArn)
        .build();
    asg.putLifecycleHook(req);
  }

  /** Example: instance refresh to roll to latest Launch Template version gracefully. */
  public void startInstanceRefresh(String asgName) {
    StartInstanceRefreshResponse r = asg.startInstanceRefresh(StartInstanceRefreshRequest.builder()
        .autoScalingGroupName(asgName)
        .preferences(RefreshPreferences.builder()
            .instanceWarmup(120)
            .minHealthyPercentage(90)
            .alarmSpecification(AlarmSpecification.builder().enable(true).build())
            .build())
        .strategy(RefreshStrategy.ROLLING)
        .build());
    System.out.println("Instance Refresh Id: " + r.instanceRefreshId());
  }

  public static void main(String[] args) {
    var demo = new AsgDemo();
    String asgName = "my-app-asg";
    demo.putTargetTrackingPolicy(asgName);
    demo.putScaleInHook(asgName, "graceful-drain", "arn:aws:sns:eu-central-1:123456789012:asg-hooks");
    demo.setDesiredCapacity(asgName, 6, true);
    // later for rollouts:
    // demo.startInstanceRefresh(asgName);
  }
}
```

**Notes**

-   Pair target tracking with **p95 latency** alarms to catch non-CPU bottlenecks.
    
-   For queue workers, scale on **queue depth / backlog per instance** rather than CPU.
    
-   Use **Warm Pools** for heavy boot times; configure **Instance Warmup** & **Cooldown** to avoid oscillation.
    
-   If using **Spot**, enable **capacity-optimized** allocation and implement **interruption handling** (drain on 2-minute notice).
    

---

## Known Uses

-   **Web/API tiers** scaling on ALB requests-per-target or latency.
    
-   **Queue workers** scaling on SQS depth / messages per instance.
    
-   **Batch/ML** fleets scaling via schedule + predictive policies during windows.
    
-   **Event stream processors** scaling on lag per partition.
    

---

## Related Patterns

-   **Queue-Based Load Leveling:** Buffer bursts so ASG can catch up.
    
-   **Throttling / Load Shedding:** Protect services during scale lag.
    
-   **Circuit Breaker & Timeouts:** Maintain stability while under/over capacity.
    
-   **Blue-Green / Rolling Update:** Combine with **Instance Refresh** for zero-downtime rollouts.
    
-   **Leader Election & Watchdog:** Supervisory tasks within scaled fleets.
    
-   **Service Discovery / Health Check:** Drive registration and safe traffic shifting.
    

---

## Implementation Checklist

-   Define **SLOs** and choose **scaling signal(s)** aligned with user experience.
    
-   Set **min/max/desired** from capacity planning; ensure **multi-AZ** subnets.
    
-   Configure **target tracking** with realistic **warmup** and **cooldown**.
    
-   Implement **graceful drain** (LB deregistration delay, connection draining, queue ack).
    
-   Adopt **mixed instances** for resilience/cost; handle **spot interruption**.
    
-   Instrument **scaling actions**, **thrash rate**, **insufficient capacity** events.
    
-   Use **Instance Refresh** tied to Launch Template version for rollouts.
    
-   Load/chaos test scale-out/in behavior before production.

