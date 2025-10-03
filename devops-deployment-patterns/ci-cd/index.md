
# CI/CD — DevOps Deployment Pattern

## Pattern Name and Classification

**Continuous Integration / Continuous Delivery (CI/CD)** — DevOps **Build–Test–Release** pipeline pattern.

## Intent

Automate the **build–test–package–verify–release** lifecycle so that each code change is **integrated early**, **validated repeatedly**, and **deployed reliably** to target environments with minimal manual effort and maximal traceability.

## Also Known As

Build pipeline; Deployment pipeline; Continuous Deployment (when prod releases are fully automated).

## Motivation (Forces)

-   Frequent merges create **integration risk** → integrate and test continuously.

-   Manual builds/tests/releases are **slow and error-prone** → automate end-to-end.

-   Fast feedback loops require **short lead time** from commit to production.

-   Regulatory/compliance needs **traceability, reproducibility, and approvals**.

-   Modern stacks demand **repeatable environments** (IaC, containers) and **supply-chain security**.


Balance:

-   **Speed** (ship fast) vs **Quality** (gates, tests) vs **Safety** (staged rollouts, approvals).

-   **Standardization** (golden pipeline) vs **Team autonomy**.


## Applicability

Use CI/CD when:

-   Multiple developers contribute frequently; you need **automatic validation** per change.

-   You deploy **often** to multiple environments (dev → test → staging → prod).

-   You require **consistent, reproducible** builds and releases across teams/services.


Avoid/Adapt when:

-   Hard real-time, air-gapped, or regulated environments that **mandate** specific manual gates (you can still automate most checks and collect evidence).


## Structure

A commit flows through **stages** with **quality gates**, producing an **immutable artifact** that is promoted across environments.

```plantuml
@startuml
skinparam packageStyle rectangle
actor Developer
package "Source Control" {
  class Repo { PRs/Branches }
}
package "CI Pipeline" {
  class Build { compile, unit tests, SCA/SAST }
  class Package { artifact, image, SBOM }
  class Test { integration, contract, e2e }
}
package "Artifact Registry" {
  class Artifacts { jars, images }
}
package "CD Orchestrator" {
  class Deploy_Dev
  class Deploy_Stage
  class Deploy_Prod
}
package "Environments" {
  class Dev
  class Stage
  class Prod
}

Developer --> Repo : push/PR
Repo --> Build : webhook
Build --> Package : on success
Package --> Artifacts : publish
Artifacts --> Test : pull artifact
Test --> Deploy_Dev : if gates pass
Deploy_Dev --> Dev
Deploy_Stage --> Stage : promote artifact
Deploy_Prod --> Prod : promote & approve
@enduml
```

## Participants

-   **SCM** (Git): branches, PRs, required checks.

-   **CI Runner**: executes stages (build, test, scan).

-   **Artifact Registry**: Maven repo/Docker registry; stores immutable artifacts + SBOM.

-   **CD Orchestrator**: rollout controller (ArgoCD/Spinnaker/GitOps/Actions runners).

-   **Environments**: dev/test/staging/prod; configured via **IaC** (Terraform, Helm, Kustomize).

-   **Quality Gates**: unit/integration/contract tests, coverage, SAST/SCA, lint, license, DAST.

-   **Approvers** (optional): human gate for production.


## Collaboration

1.  Developer opens PR → **CI** runs fast checks (lint, unit, SCA, SAST).

2.  Merge to main → **pipeline** builds, packages, signs, and publishes the artifact.

3.  **CD** pulls the exact artifact (by digest/SHA), deploys to **dev**, runs integration/e2e and DAST.

4.  On gate success → **promote** the very same artifact to **staging**, then **production** (auto or with approval).

5.  Telemetry and change records are attached to each run for traceability and rollback.


## Consequences

**Benefits**

-   **Short lead time** & **high deployment frequency**.

-   **Repeatability** and **auditability** (immutable artifacts, logs).

-   **Shift-left quality & security** (early fail).

-   Enables progressive delivery (canary/blue-green) as pipeline steps.


**Liabilities**

-   **Pipeline flakiness** hurts trust → requires investment in test stability and caching.

-   **Cost** (runners, environments, storage) and **maintenance** of shared libraries.

-   Over-gating can slow delivery; under-gating can ship defects.

-   Organizational change needed (branching, reviews, ownership).


## Implementation

**Foundations**

-   **Branching**: trunk-based or short-lived feature branches with PR checks.

-   **Immutable artifacts**: build once, run everywhere; tag by **SCM SHA** and **version**.

-   **Environment parity**: containers + IaC; config via environment variables/secrets.

-   **Security**: sign artifacts (Sigstore), generate **SBOM**, enforce **SLSA-style** provenance.

-   **Caching**: restore build caches (Maven, npm) and layers for speed.

-   **Test strategy**: fast unit on PR; integration/contract on main; e2e/DAST post-deploy.


**Quality Gates (typical)**

-   Static analysis: formatting, lint, **SAST**.

-   Dependency scanning: **SCA** & license policies.

-   Tests: unit (fast), integration (Testcontainers), contract/consumer-driven (Pact), e2e (Selenium/Playwright/API).

-   Coverage thresholds; mutation testing (optional).

-   Performance smoke & security checks (DAST) in pre-prod.


**Delivery**

-   **CD** options:

    -   Push-based (runner triggers cluster).

    -   **GitOps**: commit desired state; controller (ArgoCD/Flux) reconciles.

-   **Deployment patterns**: rolling, blue-green, canary; feature flags for last-mile safety.

-   **Rollback**: versioned manifests, database **expand/contract**, automated revert on guardrail breach.


**Observability & Compliance**

-   Propagate `version`, `git.sha`, `build.id` to logs/metrics/traces.

-   Keep an **audit trail** (who/what/when) and attach pipeline evidence to releases.


---

## Sample Code (Java)

### 1) Build-Proof Application Bits (Spring Boot)

Expose health/info for pipeline checks and embed version/commit for traceability.

```java
// ApplicationInfo.java
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public class ApplicationInfo {
  @Value("${app.version:dev}") private String version;
  @Value("${app.commit:unknown}") private String commit;
  public String version() { return version; }
  public String commit() { return commit; }
}
```

```java
// InfoController.java
import org.springframework.web.bind.annotation.*;
import java.util.Map;

@RestController
public class InfoController {
  private final ApplicationInfo info;
  public InfoController(ApplicationInfo info) { this.info = info; }

  @GetMapping("/info")
  public Map<String, String> info() {
    return Map.of("version", info.version(), "commit", info.commit(), "status", "up");
  }

  @GetMapping("/ready") public String ready() { return "OK"; } // readiness probe
  @GetMapping("/live")  public String live()  { return "OK"; } // liveness probe
}
```

```properties
# application.properties (supplied by CI/CD at build time)
app.version=${APP_VERSION}
app.commit=${GIT_COMMIT}
management.endpoints.web.exposure.include=health,info
```

### 2) CI-Friendly Tests (Unit + Testcontainers Integration)

```java
// PriceService.java
public class PriceService {
  public long applyDiscount(long cents, int percent) {
    if (percent < 0 || percent > 100) throw new IllegalArgumentException();
    return Math.max(0, cents - (cents * percent) / 100);
  }
}
```

```java
// PriceServiceTest.java (unit test)
import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.Test;

class PriceServiceTest {
  @Test void appliesPercentage() {
    var s = new PriceService();
    assertEquals(800, s.applyDiscount(1000, 20));
  }
}
```

```java
// UserRepoIT.java (integration test with Testcontainers + Postgres)
import org.junit.jupiter.api.*;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import static org.junit.jupiter.api.Assertions.*;

@Testcontainers
class UserRepoIT {
  @Container static PostgreSQLContainer<?> db =
      new PostgreSQLContainer<>("postgres:16-alpine")
          .withDatabaseName("app").withUsername("app").withPassword("app");

  @Test void connectionWorks() throws Exception {
    try (var conn = java.sql.DriverManager.getConnection(db.getJdbcUrl(), db.getUsername(), db.getPassword())) {
      try (var st = conn.createStatement()) {
        st.execute("create table if not exists t(id serial primary key, name text)");
        st.execute("insert into t(name) values ('alice')");
        var rs = st.executeQuery("select count(*) from t");
        rs.next();
        assertEquals(1, rs.getInt(1));
      }
    }
  }
}
```

```xml
<!-- pom.xml (snippets for CI speed & reliability) -->
<project>
  <properties>
    <maven.test.skip>false</maven.test.skip>
    <maven.deploy.skip>false</maven.deploy.skip>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
  </properties>

  <build>
    <plugins>
      <!-- Reproducible builds -->
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-jar-plugin</artifactId>
        <version>3.4.1</version>
        <configuration>
          <archive>
            <manifestEntries>
              <Build-Version>${env.APP_VERSION}</Build-Version>
              <Build-Commit>${env.GIT_COMMIT}</Build-Commit>
            </manifestEntries>
          </archive>
        </configuration>
      </plugin>

      <!-- Surefire for unit tests; Failsafe for integration -->
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-surefire-plugin</artifactId>
        <version>3.5.0</version>
      </plugin>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-failsafe-plugin</artifactId>
        <version>3.5.0</version>
        <executions>
          <execution>
            <goals><goal>integration-test</goal><goal>verify</goal></goals>
            <configuration>
              <includes>
                <include>**/*IT.java</include>
              </includes>
            </configuration>
          </execution>
        </executions>
      </plugin>
    </plugins>
  </build>

  <dependencies>
    <dependency>
      <groupId>org.junit.jupiter</groupId><artifactId>junit-jupiter</artifactId><version>5.10.2</version><scope>test</scope>
    </dependency>
    <dependency>
      <groupId>org.testcontainers</groupId><artifactId>postgresql</artifactId><version>1.20.1</version><scope>test</scope>
    </dependency>
  </dependencies>
</project>
```

### 3) Example Pipeline (conceptual, minimal GitHub Actions)

> Not Java, but shows how the Java pieces integrate.

```yaml
name: ci-cd
on:
  pull_request: { branches: ["main"] }
  push: { branches: ["main"] }

jobs:
  build-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with: { distribution: temurin, java-version: '21', cache: 'maven' }
      - name: Unit tests + static checks
        run: mvn -B -DskipITs=true verify
      - name: Package + SBOM
        run: |
          export APP_VERSION=${{ github.run_number }}
          export GIT_COMMIT=${{ github.sha }}
          mvn -B -DskipITs=false -DskipTests=false package
      - name: Publish artifact
        run: mvn -B deploy  # to Maven repo / registry
  deploy-dev:
    needs: build-test
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to Dev (GitOps or kubectl)
        run: echo "Promote artifact sha=${{ github.sha }} to Dev"
```

---

## Known Uses

-   Most modern SaaS/enterprise platforms (microservices, mobile backends).

-   Open-source projects with PR **required checks** before merge.

-   Payment, identity, and retail systems with **auditable** pipelines and staged rollouts.

-   Regulated industries using CI/CD to collect evidence and enforce **policy-as-code**.


## Related Patterns

-   **Blue–Green Deployment** / **Canary Release**: deployment strategies driven from CD stages.

-   **A/B Testing**: experimentation layer; can be triggered post-deploy.

-   **Feature Flags**: fine-grained runtime control; complements CI/CD.

-   **Shadow Traffic**: pre-production validation step in the pipeline.

-   **Infrastructure as Code**: ensures parity and repeatability across environments.

-   **Database Expand/Contract**: migration approach used within release steps.


---

### Practical Checklist

-   Trunk-based or short-lived branches; enforce PR checks.

-   Build once; **sign** and store immutable artifacts with **SBOM**.

-   Tiered tests: unit (fast) → integration/contract → e2e/DAST.

-   Secrets via a secure store; no secrets in repos.

-   Propagate `git.sha`/`version` to runtime; expose `/ready` and `/live`.

-   Observability wired (logs/metrics/traces) with version labels.

-   Clear rollback path and automated promotion between environments.
