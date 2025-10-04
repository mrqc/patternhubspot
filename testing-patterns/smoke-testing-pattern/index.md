# Smoke Testing — Testing Pattern

## Pattern Name and Classification

-   **Name:** Smoke Testing
    
-   **Classification:** Release Readiness / Build Verification / Shallow Health Checks
    

## Intent

Provide a **fast, shallow** verification that a build or deployment is **basically functional**. Run a **tiny set of critical checks** (can the app start? key endpoints respond? DB connects?) to **fail fast** before running heavier suites or sending traffic.

## Also Known As

-   Build Verification Test (BVT)
    
-   Sanity Check
    
-   Post-Deploy Smoke
    
-   Health/Readiness Probe (closely related mechanism)
    

## Motivation (Forces)

-   **Speed vs. confidence:** you need minutes (not hours) feedback that the system is alive after a build/deploy.
    
-   **Cost control:** full regression/E2E suites are too slow and expensive to run on every pipeline step.
    
-   **Blast radius:** catch misconfigurations (secrets, URLs, migrations) before customers see errors.
    
-   **Signal quality:** checks must be reliable and environment-aware to avoid flakiness.
    

## Applicability

Use smoke tests when:

-   **After each build** to validate packaging/startup.
    
-   **Right after deploy** (pre- or post-traffic) to ensure the stack is reachable and healthy.
    
-   **Before running costly suites** (regression, E2E, performance).
    

Avoid or adapt when:

-   Validating **business rules** or deep flows (use integration/E2E).
    
-   Environments are **shared & unstable**; ensure isolation or run against the just-deployed target.
    

## Structure

-   **Target Environment:** app instance(s) just built or deployed.
    
-   **Probes:** minimal checks for **process up**, **health/readiness**, **critical dependency reachability**.
    
-   **Runner:** a tiny, deterministic test harness (often tagged `smoke`).
    
-   **Policy:** fail fast, surface clear diagnostics, block promotion on red.
    

```pgsql
[Deploy/Start] → [Smoke Runner]
                     ├─ HTTP /healthz → 200 + "UP"
                     ├─ DB "SELECT 1" → OK
                     ├─ Version / build info matches
                     └─ Optional: queue/cache ping
           → pass? promote : halt + diagnose
```

## Participants

-   **CI/CD Orchestrator** — invokes smoke stage.
    
-   **Smoke Test Runner** — tiny test suite (JUnit, shell, k6, etc.).
    
-   **Application/Service** — the target being verified.
    
-   **Observability** — logs/metrics to explain failures quickly.
    

## Collaboration

1.  Pipeline builds & deploys the service (or starts it locally).
    
2.  Smoke runner executes a **handful of probes** with short timeouts.
    
3.  On failure, pipeline **halts** and surfaces logs/diagnostics; on green, it **promotes** to further tests or traffic.
    

## Consequences

**Benefits**

-   **Immediate feedback** on deploy/build health.
    
-   **Cheap confidence** before heavier stages.
    
-   **Clear failure modes** (misconfig, missing secret, dead dependency).
    

**Liabilities**

-   **Shallow coverage**—green smoke ≠ correct behavior.
    
-   Can be **flaky** if coupled to shared dependencies without guards.
    
-   Temptation to **overgrow** the suite; keep it tiny and stable.
    

## Implementation

### Principles

-   **Keep it minimal:** 5–10 checks max, < 1–2 minutes runtime.
    
-   **Environment-driven:** targets via env vars or config (no hardcoded hosts).
    
-   **Short timeouts & retries:** fail fast, include one or two quick retries on transient startup jitter.
    
-   **Deterministic & stateless:** do not depend on pre-existing data; avoid changing state unless necessary.
    
-   **Clear diagnostics:** print endpoint, status, and snippet of body on failure.
    
-   **Tagging:** mark tests with `@Tag("smoke")` so CI can run them alone.
    

### Typical Checks

-   `GET /health` or `/ready` returns **200** and body contains `"UP"`/`"ready":true`.
    
-   `GET /version` equals expected `GIT_SHA` / build number.
    
-   DB **connectivity**: open connection and `SELECT 1`.
    
-   Cache/broker **ping** (optional).
    
-   Critical endpoint simple **happy-path** (`/api/ping`) returns 200 quickly.
    

---

## Sample Code (Java 17, JUnit 5) — Minimal, Taggable Smoke Suite

> This suite hits a running service (URL from env), verifies health/version, and checks DB connectivity.  
> It uses **assumptions** to skip checks if env vars aren’t provided (keeps the suite portable).

```java
// src/test/java/smoke/SmokeTest.java
package smoke;

import static org.junit.jupiter.api.Assertions.*;
import static org.junit.jupiter.api.Assumptions.*;

import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

import java.net.URI;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.sql.*;
import java.time.Duration;
import java.util.Map;

@Tag("smoke")
class SmokeTest {

  private static final HttpClient HTTP = HttpClient.newBuilder()
      .connectTimeout(Duration.ofSeconds(3))
      .version(HttpClient.Version.HTTP_1_1)
      .build();

  // Helper to fetch env with default
  private static String env(String key, String def) {
    return System.getenv().getOrDefault(key, def);
  }

  @Test
  @Timeout(10)
  void health_endpoint_is_up() throws Exception {
    String base = env("BASE_URL", "http://localhost:8080");
    HttpRequest req = HttpRequest.newBuilder(URI.create(base + "/health"))
        .timeout(Duration.ofSeconds(5))
        .GET().build();
    HttpResponse<String> resp = HTTP.send(req, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));

    assertEquals(200, resp.statusCode(), () ->
        "Health failed: " + resp.statusCode() + " body=" + truncate(resp.body(), 200));
    assertTrue(resp.body().toLowerCase().contains("up") || resp.body().toLowerCase().contains("ready"),
        () -> "Unexpected health body: " + truncate(resp.body(), 200));
  }

  @Test
  @Timeout(10)
  void version_matches_expected_commit() throws Exception {
    String expected = env("EXPECTED_VERSION", "").trim();
    assumeFalse(expected.isEmpty(), "EXPECTED_VERSION not set; skipping version check");

    String base = env("BASE_URL", "http://localhost:8080");
    HttpRequest req = HttpRequest.newBuilder(URI.create(base + "/version"))
        .timeout(Duration.ofSeconds(5)).GET().build();
    HttpResponse<String> resp = HTTP.send(req, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));

    assertEquals(200, resp.statusCode(), "Version endpoint not reachable");
    String body = resp.body().trim();
    // Accept direct match or JSON field containing the expected
    assertTrue(body.contains(expected), () ->
        "Version mismatch. expected contains=" + expected + " actual=" + truncate(body, 200));
  }

  @Test
  @Timeout(10)
  void database_connection_and_select1() throws Exception {
    String url = env("JDBC_URL", "");
    String user = env("JDBC_USER", "");
    String pass = env("JDBC_PASS", "");
    assumeFalse(url.isEmpty(), "JDBC_URL not set; skipping DB check");

    try (Connection c = DriverManager.getConnection(url, user, pass);
         Statement st = c.createStatement();
         ResultSet rs = st.executeQuery("SELECT 1")) {
      assertTrue(rs.next(), "SELECT 1 returned no rows");
      assertEquals(1, rs.getInt(1), "SELECT 1 mismatch");
    }
  }

  private static String truncate(String s, int n) {
    if (s == null) return "";
    return s.length() <= n ? s : s.substring(0, n) + "...";
  }
}
```

**Maven Surefire configuration to run only smoke tests in a pipeline stage**

```xml
<!-- pom.xml -->
<build>
  <plugins>
    <plugin>
      <groupId>org.apache.maven.plugins</groupId>
      <artifactId>maven-surefire-plugin</artifactId>
      <version>3.2.5</version>
      <configuration>
        <groups>smoke</groups> <!-- run only @Tag("smoke") -->
        <trimStackTrace>false</trimStackTrace>
      </configuration>
    </plugin>
  </plugins>
</build>
```

**CI usage example (environment-driven)**

```cpp
BASE_URL=https://myapp.staging.acme.com \
EXPECTED_VERSION=$GIT_COMMIT \
JDBC_URL='jdbc:postgresql://db.staging:5432/app' \
JDBC_USER=app JDBC_PASS=secret \
mvn -q -Dtest=smoke.SmokeTest test
```

---

## Known Uses

-   **Post-deploy gates**: canary/blue-green rollout pauses until smoke is green.
    
-   **Build verification**: after packaging, start app locally (Testcontainers/docker compose) and run smoke before pushing images.
    
-   **Synthetic probes**: scheduled smoke checks against production (`/health`, `/version`) for operational visibility.
    

## Related Patterns

-   **Regression Testing:** deeper functional coverage after smoke passes.
    
-   **End-to-End Testing:** validates full journeys; slower and broader than smoke.
    
-   **Integration Testing:** verifies real adapters; smoke only pings them.
    
-   **Canary Testing:** gradual traffic after smoke gate.
    
-   **Health/Readiness Probes:** platform-level checks used by orchestrators (K8s) — smoke can reuse these endpoints.
    
-   **Contract Testing:** compatibility between services; can complement smoke in CI.
    

---

## Implementation Tips

-   Keep smoke **tiny, fast, and stable**; move anything flaky or business-heavy to other suites.
    
-   **Reuse platform probes** (`/health`, `/ready`) and ensure they are meaningful (checks deps).
    
-   Make failures **actionable**: log endpoint called, status code, and body snippet.
    
-   Run smoke **per environment** (dev, staging, prod pre-traffic) with environment-specific config.
    
-   Add **timeouts and small retries** (with backoff) to handle just-after-start races.
    
-   Treat smoke as **gates** in CI/CD: green → proceed, red → stop and page the owner.

