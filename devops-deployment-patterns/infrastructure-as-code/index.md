# Infrastructure as Code — DevOps Deployment Pattern

---

## Pattern Name and Classification

-   **Name:** Infrastructure as Code (IaC)

-   **Category:** DevOps / Infrastructure Management / Automation Pattern

-   **Level:** System + Process Pattern (infrastructure provisioning, deployment, operations)


---

## Intent

Define and manage infrastructure (servers, networks, clusters, databases, etc.) **declaratively or programmatically** using code instead of manual processes.  
This enables **repeatability, version control, automation, and collaboration** across teams.

---

## Also Known As

-   Programmable Infrastructure

-   Declarative Infrastructure

-   Infrastructure Automation

-   Software-Defined Infrastructure


---

## Motivation (Forces)

-   **Repeatability:** Manual changes lead to drift and errors.

-   **Scalability:** Large-scale systems require automation.

-   **Auditability:** Code in version control provides history and accountability.

-   **Speed:** Faster provisioning of consistent environments.

-   **Collaboration:** Developers and ops work in the same workflows.


**Forces & trade-offs:**

-   Requires **tooling maturity** (Terraform, Pulumi, Ansible, etc.).

-   Misconfigured IaC can spread errors quickly (blast radius).

-   Sensitive data (secrets, keys) must not be hardcoded.

-   Debugging declarative config can be difficult.


---

## Applicability

Use IaC when:

-   You manage **cloud infrastructure** (AWS, GCP, Azure, etc.).

-   You need **repeatable test/prod environments**.

-   Your system needs **auto-scaling, frequent infra changes, or compliance/audit trails**.

-   You want to align infra changes with **Git workflows** (GitOps).


Avoid or adapt when:

-   Small systems rarely change infra (overhead may outweigh benefits).

-   Legacy systems rely heavily on **manual configuration**.

-   Team lacks **automation skills** or IaC practices.


---

## Structure

1.  **Declarative Templates:** YAML/JSON/Terraform describing desired infra state.

2.  **IaC Tool/Engine:** Terraform, Pulumi, Ansible, CloudFormation, etc.

3.  **Version Control Repository:** Source of truth for infra.

4.  **CI/CD Pipeline:** Applies infra definitions automatically.

5.  **Target Environment:** Cloud, on-prem, or hybrid systems.


```css
[Git Repo] → [CI/CD Pipeline] → [IaC Engine] → [Provision Infrastructure]
                                       ↑
                              Review / Pull Request
```

---

## Participants

-   **Developers:** Write code + infra config.

-   **Ops/SRE:** Review, approve, and operate IaC pipelines.

-   **CI/CD System:** Executes provisioning/deployment.

-   **IaC Engine:** Applies templates to actual infra.

-   **Cloud Provider / Data Center:** Executes requested changes.

-   **Compliance/Security:** Review infra definitions for risks.


---

## Collaboration

-   **Works with GitOps** — IaC definitions live in Git.

-   **Supports Immutable Infrastructure** — infra replaced instead of mutated.

-   **Pairs with Continuous Delivery** — infra is provisioned alongside apps.

-   **Interacts with Policy as Code** — validates compliance automatically.

-   **Complements Monitoring** — infra code includes observability configs.


---

## Consequences

**Benefits**

-   Predictable infra deployments.

-   Faster environment provisioning.

-   Strong audit/compliance trails.

-   Reduces human error.

-   Enables disaster recovery (rebuild infra from code).


**Liabilities**

-   IaC sprawl if not structured (many modules/files).

-   Steep learning curve (Terraform, Kubernetes manifests).

-   Risk of “copy-paste infra anti-patterns.”

-   If misused, IaC can destroy infra quickly.


Mitigations:

-   Use **linting, testing, and policy enforcement**.

-   Maintain **modular, reusable templates**.

-   Apply **least-privilege access controls**.


---

## Implementation

1.  **Choose IaC Tool**

    -   Terraform, Pulumi, CloudFormation, Ansible, SaltStack, Chef.

2.  **Design Repo Structure**

    -   Organize per environment (dev/stage/prod).

    -   Use modules for reusability.

3.  **Write Infrastructure Code**

    -   Declarative (Terraform, K8s YAML).

    -   Imperative (Ansible, Pulumi).

4.  **Integrate with Git**

    -   Review infra changes via pull requests.

5.  **Automate via CI/CD**

    -   Validate + apply on merge.

6.  **Add Guardrails**

    -   Policy as Code (OPA, Sentinel).

    -   Pre-checks for drift.

7.  **Secrets Management**

    -   Store secrets in Vault, AWS Secrets Manager, or SOPS.

8.  **Monitoring & Rollback**

    -   Rollback = revert commit and re-apply.


---

## Sample Code

### Example: Terraform IaC (AWS EC2)

```hcl
provider "aws" {
  region = "eu-central-1"
}

resource "aws_instance" "web" {
  ami           = "ami-123456"
  instance_type = "t3.micro"
  tags = {
    Name = "myapp-server"
  }
}
```

### Example: Kubernetes Deployment (YAML in Git)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  replicas: 2
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
          image: registry.example.com/myapp:1.0.0
          ports:
            - containerPort: 8080
```

### Example: Java App Reading Config from IaC (Spring Boot)

*(App does not provision infra but relies on IaC for environment consistency)*

```java
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/config")
public class ConfigController {

    @Value("${environment.name:dev}")
    private String envName;

    @GetMapping
    public String configInfo() {
        return "Running in environment: " + envName;
    }
}
```

-   The **`environment.name`** is set via ConfigMap/terraform provisioned vars.

-   Infra (VMs, containers, networking) is provisioned via IaC.

-   The Java app simply trusts the environment built by IaC.


---

## Known Uses

-   **Netflix, Google, AWS**: heavy Terraform/Pulumi/CloudFormation usage.

-   **Financial institutions**: IaC for auditability and compliance (Git + PR reviews).

-   **Startups**: standardize dev/test/prod parity with Kubernetes manifests.

-   **HashiCorp**: provides Terraform as IaC flagship tool.


---

## Related Patterns

-   **GitOps** — IaC definitions deployed from Git.

-   **Immutable Infrastructure** — IaC provisions immutable VMs/containers.

-   **Blue/Green Deployment** — IaC orchestrates environments.

-   **Canary Release** — IaC provisions cohorts/segments.

-   **Policy as Code** — validate infra definitions.

-   **Configuration as Code** — sibling pattern (app config).
