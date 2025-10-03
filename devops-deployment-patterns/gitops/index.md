# GitOps — DevOps Deployment Pattern

---

## Pattern Name and Classification

-   **Name:** GitOps

-   **Category:** DevOps / Infrastructure as Code / Continuous Delivery Pattern

-   **Level:** System + Process pattern (workflow + tooling)


---

## Intent

Use **Git as the single source of truth** for both application and infrastructure configuration.  
Operational state is reconciled automatically against Git, ensuring deployments are **declarative, auditable, and version-controlled**.

---

## Also Known As

-   Git-driven Operations

-   Git-based Continuous Delivery

-   Operations via Pull Requests


---

## Motivation (Forces)

-   **Declarative state management:** Desired state is captured in Git.

-   **Single source of truth:** Version control, history, rollback.

-   **Automation & safety:** CI/CD pipelines or agents reconcile reality with Git.

-   **Auditability & compliance:** PR reviews document all changes.

-   **Collaboration:** Same workflow developers use for code now applies to operations.


**Forces / Trade-offs**

-   **Requires maturity in IaC:** YAML/Helm/Kustomize/Terraform must fully describe infra/app state.

-   **Latency:** Reconciliation is not always instant.

-   **Security:** Git access = infra access; RBAC and secrets management are critical.

-   **Tooling complexity:** Controllers (e.g., ArgoCD, Flux) must be operated themselves.


---

## Applicability

Use GitOps when:

-   You deploy to **Kubernetes** or another IaC-friendly platform.

-   You need **auditable, controlled, repeatable** deployments.

-   Teams are already familiar with **Git workflows (PRs, code review, branching)**.

-   You want **automatic drift detection & reconciliation**.


Avoid when:

-   The platform lacks declarative IaC capabilities.

-   The org does not yet have **branching/review discipline**.

-   Deployments require **imperative/manual operations** that cannot be modeled declaratively.


---

## Structure

1.  **Desired State Repository** (in Git):

    -   Application manifests (K8s YAML, Helm charts, Kustomize).

    -   Infra configs (Terraform, Pulumi, CloudFormation).

2.  **GitOps Operator/Agent** (ArgoCD, Flux):

    -   Watches Git for changes.

    -   Syncs cluster/cloud state to match repo.

    -   Reports drift.

3.  **CI/CD Integration:**

    -   CI builds images/artifacts, pushes tags.

    -   Deployment happens when manifests in Git reference the new version.


```pgsql
Developer → Pull Request → Git Repository → GitOps Operator → Cluster/Infra State
                                       ↑
                                  Observability & Drift Alerts
```

---

## Participants

-   **Developer/Architect:** Defines manifests, submits PRs.

-   **Reviewer/Lead:** Approves changes, enforces policy.

-   **Git Repository:** Source of truth for all configs.

-   **GitOps Operator:** Reconciles desired vs actual state.

-   **Observability/Alerting System:** Detects drift or failed reconciliations.

-   **Secrets Manager:** Provides sensitive values outside Git.


---

## Collaboration

-   Works with **Infrastructure as Code** (Terraform, Helm, Kustomize).

-   Supports **Progressive Delivery** (with feature flags, canaries).

-   Complements **Policy as Code** (OPA/Gatekeeper).

-   Pairs with **ChatOps** (PR notifications, approvals in Slack/Teams).


---

## Consequences

**Benefits**

-   Full audit trail of all ops changes.

-   Easy rollback via `git revert`.

-   Strong security model: cluster changes only through Git.

-   Consistency across environments.

-   Familiar workflows for devs and ops.


**Liabilities**

-   Git as a single choke point; if down/unavailable, ops is blocked.

-   Requires discipline in PR review & merge practices.

-   Drift handling: manual correction if operator cannot reconcile.

-   Large-scale infra changes may cause long reconcile loops.


---

## Implementation

1.  **Choose GitOps Tooling**

    -   Kubernetes: ArgoCD, Flux.

    -   Cloud: Atlantis (for Terraform), Pulumi with Git hooks.

2.  **Design Repo Structure**

    -   **App Repo** → source code & Dockerfiles.

    -   **Ops Repo** → manifests/Helm values referencing image tags.

3.  **Pipeline Flow**

    -   Developer pushes code → CI builds image `myapp:v2`.

    -   Ops repo updated with new tag (via automated PR).

    -   Reviewer approves → merge to main.

    -   GitOps operator detects new commit, applies manifests.

4.  **Drift Detection**

    -   Operator periodically compares cluster state to Git.

    -   Drift triggers alerts and auto-reconciliation.

5.  **Secrets Management**

    -   Do not store secrets in Git.

    -   Use Vault, SealedSecrets, SOPS, AWS KMS, etc.

6.  **Observability**

    -   Track sync status, reconcile metrics, deployment SLOs.


---

## Sample Code (Java, Spring Boot + GitOps Example)

*(Here we simulate a service writing its config declaratively; in practice, GitOps is tool-driven rather than app-driven.)*

### Example: Config file for deployment (in Git, Kubernetes manifest)

```yaml
# k8s/deployment.yaml
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
          image: registry.example.com/myapp:2.0.1
          ports:
            - containerPort: 8080
```

### Example: Java service reads config (from mounted ConfigMap)

```java
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/config")
public class ConfigController {

    @Value("${feature.mode:default}")
    private String featureMode;

    @GetMapping
    public String currentMode() {
        return "Feature mode: " + featureMode;
    }
}
```

### Example: ConfigMap stored in Git

```yaml
# k8s/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: myapp-config
  namespace: prod
data:
  application.properties: |
    feature.mode=experimental
```

-   When PR updates this file and merges → GitOps operator syncs it into the cluster → app reloads config (via ConfigMap reload sidecar or rolling restart).

-   Rollback = `git revert` commit.


---

## Known Uses

-   **Weaveworks** (originator of the term) → pioneered GitOps for Kubernetes.

-   **Intuit** uses ArgoCD for multi-cluster deployments.

-   **Amazon EKS / Azure AKS / Google GKE** → cloud providers advocate GitOps as best practice.

-   **Financial services & regulated industries** for auditability and compliance.


---

## Related Patterns

-   **Infrastructure as Code (IaC):** foundational building block.

-   **Immutable Infrastructure:** GitOps ensures drift-free immutable state.

-   **Continuous Deployment / Continuous Delivery:** GitOps is a CD flavor.

-   **Blue/Green Deployments & Canary Releases:** triggered declaratively via Git changes.

-   **Policy as Code:** enforces compliance on PR before merge.

-   **Feature Toggles / Dark Launch:** GitOps deploys infra/app, toggles handle exposure.
