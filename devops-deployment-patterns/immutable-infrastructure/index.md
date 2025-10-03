
# Immutable Infrastructure — DevOps Deployment Pattern

---

## Pattern Name and Classification

-   **Name:** Immutable Infrastructure

-   **Category:** DevOps / Infrastructure Management / Deployment Pattern

-   **Level:** System + Process pattern (VM/container/infra lifecycle)


---

## Intent

Provision and manage infrastructure by **replacing resources with new instances** instead of patching or mutating them in place.  
This ensures **predictable, consistent, and reproducible environments** and simplifies rollback.

---

## Also Known As

-   Phoenix Servers

-   Cattle not Pets (metaphor)

-   Rebuild not Repair

-   Immutable Deployments


---

## Motivation (Forces)

-   **Configuration drift** is a major source of instability (manual patching, untracked changes).

-   **Consistency across environments:** local, staging, prod should run identical images.

-   **Rollback simplicity:** replace with prior image rather than reverse engineering changes.

-   **Audit/compliance:** infra defined declaratively, not mutated manually.

-   **Resilience:** new instances can be spun up quickly on failure.


**Forces & trade-offs:**

-   Requires **automation maturity** (image building, auto-scaling, CI/CD).

-   Resource heavy if images are large.

-   **Stateful workloads** require special handling (persistent volumes).

-   Patching security updates requires new image rebuilds (slow pipeline if not optimized).


---

## Applicability

Use Immutable Infrastructure when:

-   Running workloads in **cloud-native** environments (Kubernetes, AWS, GCP, Azure).

-   Building **container-based** apps (Docker, OCI).

-   Automating **server fleets** (e.g., auto-scaling groups, VM templates).

-   Seeking compliance with **strict change-control requirements**.


Avoid or adapt when:

-   Legacy apps require **in-place upgrades/patches**.

-   Large stateful systems cannot easily be replaced.

-   Environments lack robust provisioning tools (Terraform, Packer, Ansible, Pulumi).


---

## Structure

1.  **Immutable Artifacts:** Golden images (VMs, AMIs, containers) built once per version.

2.  **Provisioning Tools:** IaC (Terraform, CloudFormation, Pulumi) creates infra from these images.

3.  **Orchestrator:** Schedulers (Kubernetes, Nomad, AWS ASG) manage lifecycle.

4.  **Deployment Model:** Blue/Green, Canary, or Rolling replace old infra with new.


```pgsql
[Source Code] → [CI/CD Build] → [Immutable Image Registry] → [Provisioning] → [Cluster/ASG]
                                       │
                                       └── rollback = redeploy older image
```

---

## Participants

-   **Developers/Build Engineers:** create Dockerfiles, Packer templates, Helm charts.

-   **CI/CD Pipeline:** builds immutable artifacts (images).

-   **Registry/Artifact Store:** DockerHub, ECR, GCR, Artifactory.

-   **Provisioning Tools:** Terraform, Pulumi, CloudFormation.

-   **Orchestrators:** Kubernetes, AWS ASGs, Nomad.

-   **Ops/SRE:** monitor health, rollback if needed.


---

## Collaboration

-   Works with **Infrastructure as Code (IaC)** to describe desired state.

-   Commonly paired with **GitOps** to sync desired state from Git.

-   Used with **Blue/Green** or **Canary Releases** to safely replace infra.

-   Related to **Containerization** (images are naturally immutable).

-   Complements **CI/CD Pipelines** which produce artifacts.


---

## Consequences

**Benefits**

-   Eliminates config drift.

-   Simplifies rollback.

-   Strong audit trail.

-   Predictable deployments and reproducible environments.

-   Supports cloud-native scaling and automation.


**Liabilities**

-   Storage/compute costs for many image versions.

-   Need for fast automated image build pipelines.

-   Stateful services need additional strategies (volumes, DB migrations).

-   Larger operational overhead if org not cloud-native ready.


---

## Implementation

1.  **Build Immutable Image**

    -   Use Packer, Docker, BuildKit to create an image per version.

    -   Tag images (`myapp:v1.2.3`) and push to registry.

2.  **Provision Infrastructure**

    -   Deploy via Terraform/CloudFormation referencing image IDs.

    -   In K8s, update Deployment manifest with new image tag.

3.  **Deploy via Replacement**

    -   Old pods/instances terminated, new pods/instances spawned.

    -   No in-place patching.

4.  **Rollback**

    -   Redeploy older image tag/version.

5.  **Handle State**

    -   Externalize state to DBs, volumes, object storage.

6.  **Observe & Validate**

    -   Monitor health and readiness; auto rollback on failures.


---

## Sample Code (Java + Kubernetes Example)

**Step 1 — Java App (Spring Boot Controller)**

```java
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/version")
public class VersionController {
    @GetMapping
    public String version() {
        return "Immutable MyApp v1.2.3";
    }
}
```

**Step 2 — Dockerfile (Immutable Image)**

```dockerfile
FROM eclipse-temurin:17-jdk-alpine
WORKDIR /app
COPY target/myapp-1.2.3.jar app.jar
ENTRYPOINT ["java", "-jar", "app.jar"]
```

**Step 3 — Kubernetes Deployment Manifest (stored in Git, declarative)**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
  namespace: prod
spec:
  replicas: 3
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
          image: registry.example.com/myapp:1.2.3   # immutable tag
          ports:
            - containerPort: 8080
```

-   To deploy a new version: build a new image `myapp:1.2.4`, update manifest, commit to Git.

-   Rollback = redeploy `myapp:1.2.3`.


---

## Known Uses

-   **Netflix** pioneered “immutable AMIs” for its streaming infra.

-   **AWS Auto Scaling Groups** launch immutable EC2 AMIs.

-   **Kubernetes** inherently uses immutable containers.

-   **HashiCorp Packer** widely used to build golden images.

-   Enterprises in **finance & healthcare** adopt immutability for compliance.


---

## Related Patterns

-   **Blue/Green Deployment** — replaces entire infra set immutably.

-   **Canary Release** — introduces new immutable images to small % of traffic.

-   **Infrastructure as Code (IaC)** — declarative definitions enable immutability.

-   **GitOps** — ensures immutable manifests/images are deployed from Git.

-   **Containerization** — Docker/OCI images are immutable artifacts.

-   **Phoenix Servers** — metaphor for servers always rebuilt from scratch.
