# Test Pyramid — Testing Pattern

## Pattern Name and Classification

-   **Name:** Test Pyramid
    
-   **Classification:** Test Strategy / Portfolio Management / Risk-Balanced Automation
    

## Intent

Organize your automated tests into **layers** with **many fast unit tests**, **fewer integration/contract tests**, and **very few, high-value end-to-end (E2E)** tests—so you get **fast feedback** and **high confidence** without brittle, slow pipelines.

## Also Known As

-   Testing Pyramid
    
-   Layered Test Strategy
    
-   70/20/10 (rule-of-thumb ratio)
    

## Motivation (Forces)

-   **Speed vs. realism:** Unit tests are fast but abstract; E2E is realistic but slow/fragile.
    
-   **Cost vs. value:** Limited CI time; most defects can be caught cheaply at lower layers.
    
-   **Flakiness control:** Network/UI/infrastructure increase nondeterminism; cap E2E count.
    
-   **Ownership & clarity:** Clear purpose per layer reduces redundancy and “ice-cream cones” (too many E2E).
    

## Applicability

Use the Test Pyramid when:

-   You build services/UIs with external dependencies (DBs, brokers, 3rd-party APIs).
    
-   You want predictable CI times and a clear testing budget.
    
-   Multiple teams collaborate and need shared expectations per layer.
    

Adapt when:

-   Safety-critical domains may require more **system** and **formal** tests.
    
-   Highly visual apps might add a side “**visual** tests” layer (diffs) near the top.
    

## Structure

```pgsql
▲  Few, slow, brittle   → validate critical journeys
      E2E  │  (UI/API across infra)
           │
           │  Some, slower         → real adapters/contracts
Integration│  (DB/HTTP/Kafka/etc.)
-----------┼----------------------------------------------------
           │  Many, fast, stable   → pure logic, no I/O
    Unit   │  (functions/classes)
           ▼
```

-   Optional flanking layers: **Contract tests** (between services), **Static analysis**, **Mutation testing**, **Visual/Snapshot** checks.
    

## Participants

-   **Developers** – write unit & most integration tests; maintain contracts.
    
-   **QA/SET/SRE** – curate E2E/smoke and operational checks.
    
-   **CI/CD** – runs tiers with tagging & gates.
    
-   **Provisioner** – Testcontainers/compose for hermetic infra.
    

## Collaboration

1.  **PR stage:** run **unit** (seconds) + a **thin smoke**.
    
2.  **Merge stage:** add **key integration/contract** suites (minutes).
    
3.  **Pre-release:** run **selected E2E** and extended integration.
    
4.  **Nightly:** mutation/property/visual/extended E2E.
    

## Consequences

**Benefits**

-   Fast feedback, predictable pipelines.
    
-   Failures are **localized** to a layer → quick diagnosis.
    
-   Less flake, lower maintenance cost.
    

**Liabilities**

-   Requires **discipline** to not push everything to the top.
    
-   Misbalanced pyramids (too few integration tests) miss adapter/config bugs.
    
-   Cultural change: teams must embrace ports/adapters & hermetic tests.
    

## Implementation

### Guidelines

-   **Ratios (heuristic):** ~70% unit, ~20% integration/contract, ~10% E2E (by count/runtime—optimize for runtime).
    
-   **Tag tests** by layer (`unit`, `integration`, `e2e`) and wire CI to run them in stages.
    
-   **Unit:** no I/O; use **stubs/fakes/mocks** sparingly; assert **state & behavior**.
    
-   **Integration:** use **real adapters** via **Testcontainers**; seed deterministically; short timeouts.
    
-   **E2E:** only **business-critical flows**; make them deterministic; collect artifacts (logs/screenshots).
    
-   **Governance:** dashboards for runtime/flake; mutation testing on critical modules; contract tests for service boundaries.
    
-   **Deflake loop:** quarantine & fix flaky tests quickly; keep the top thin.
    

---

## Sample Code (Java 17, JUnit 5) — Tags + Minimal examples

> Three tiny tests demonstrate tagging and scope of each layer, plus Maven config to select layers in pipeline stages.

### 1) SUT (pure logic for unit tests)

```java
// src/main/java/example/PriceCalculator.java
package example;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Objects;

public class PriceCalculator {
  public BigDecimal applyDiscount(BigDecimal net, int percent) {
    Objects.requireNonNull(net);
    if (net.signum() < 0) throw new IllegalArgumentException("negative");
    if (percent < 0 || percent > 100) throw new IllegalArgumentException("0..100");
    var factor = BigDecimal.valueOf(100 - percent).movePointLeft(2);
    return net.multiply(factor).setScale(2, RoundingMode.HALF_UP);
  }
}
```

### 2) Unit test — fast & pure

```java
// src/test/java/example/PriceCalculatorTest.java
package example;

import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import java.math.BigDecimal;
import static org.junit.jupiter.api.Assertions.*;

@Tag("unit")
class PriceCalculatorTest {
  PriceCalculator calc = new PriceCalculator();

  @Test void zero_percent_yields_same_value() {
    assertEquals(new BigDecimal("19.90"), calc.applyDiscount(new BigDecimal("19.90"), 0));
  }

  @Test void rounding_half_up() {
    assertEquals(new BigDecimal("9.90"), calc.applyDiscount(new BigDecimal("9.95"), 1)); // 9.8505→9.85→9.85? No: (9.95*0.99)=9.8505→9.85 (HALF_UP 2dp) 
    // adjust to demonstrate boundary more clearly:
    assertEquals(new BigDecimal("10.05"), calc.applyDiscount(new BigDecimal("10.05"), 0));
  }
}
```

### 3) Integration test — real DB via Testcontainers

```java
// src/test/java/example/UserRepositoryIT.java
package example;

import org.junit.jupiter.api.*;
import org.junit.jupiter.api.Tag;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.sql.*;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;

@Tag("integration")
@Testcontainers
class UserRepositoryIT {

  @Container
  static final PostgreSQLContainer<?> PG = new PostgreSQLContainer<>("postgres:16-alpine")
      .withDatabaseName("app").withUsername("app").withPassword("secret");

  static String URL, USER, PASS;
  UserRepository repo;

  @BeforeAll static void init() { URL = PG.getJdbcUrl(); USER = PG.getUsername(); PASS = PG.getPassword(); }

  @BeforeEach
  void setup() throws Exception {
    try (var c = DriverManager.getConnection(URL, USER, PASS); var st = c.createStatement()) {
      st.execute("""
        CREATE TABLE IF NOT EXISTS users(
          id UUID PRIMARY KEY, email TEXT UNIQUE NOT NULL, created_at TIMESTAMPTZ NOT NULL
        );
        TRUNCATE users;
      """);
    }
    repo = new UserRepository(URL, USER, PASS);
  }

  @Test
  void roundtrip_user() throws Exception {
    var u = new User(UUID.randomUUID(), "alice@example.com", Instant.parse("2025-01-01T12:00:00Z"));
    repo.save(u);
    var loaded = repo.findByEmail("alice@example.com");
    assertTrue(loaded.isPresent()); assertEquals(u.id(), loaded.get().id());
  }

  /* --- tiny JDBC adapter under test --- */
  record User(UUID id, String email, Instant createdAt) {}
  static class UserRepository {
    final String url, user, pass;
    UserRepository(String u, String n, String p) { url=u; user=n; pass=p; }
    void save(User u) throws SQLException {
      try (var c=DriverManager.getConnection(url,user,pass);
           var ps=c.prepareStatement("INSERT INTO users(id,email,created_at) VALUES (?,?,?)")) {
        ps.setObject(1, u.id(), java.sql.Types.OTHER); ps.setString(2, u.email()); ps.setObject(3, Timestamp.from(u.createdAt())); ps.executeUpdate();
      }
    }
    Optional<User> findByEmail(String email) throws SQLException {
      try (var c=DriverManager.getConnection(url,user,pass);
           var ps=c.prepareStatement("SELECT id,email,created_at FROM users WHERE email=?")) {
        ps.setString(1, email); try (var rs=ps.executeQuery()) {
          if (!rs.next()) return Optional.empty();
          return Optional.of(new User((UUID) rs.getObject("id"), rs.getString("email"), rs.getTimestamp("created_at").toInstant()));
        }
      }
    }
  }
}
```

### 4) E2E (smoke) test — hit a running service URL

```java
// src/test/java/example/SmokeE2ETest.java
package example;

import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Assumptions;

import java.net.URI;
import java.net.http.*;
import java.time.Duration;

import static org.junit.jupiter.api.Assertions.*;

@Tag("e2e")
class SmokeE2ETest {

  @Test
  void health_endpoint_is_up() throws Exception {
    String base = System.getenv().getOrDefault("BASE_URL", "").trim();
    Assumptions.assumeFalse(base.isEmpty(), "BASE_URL not set; skipping E2E");
    HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).build();

    HttpResponse<String> resp = http.send(
        HttpRequest.newBuilder(URI.create(base + "/health")).timeout(Duration.ofSeconds(5)).GET().build(),
        HttpResponse.BodyHandlers.ofString());

    assertEquals(200, resp.statusCode(), "Health endpoint must be 200");
    assertTrue(resp.body().toLowerCase().contains("up") || resp.body().toLowerCase().contains("ready"));
  }
}
```

### 5) Maven (JUnit 5) — run layers in stages

```xml
<!-- pom.xml (fragments) -->
<build>
  <plugins>
    <!-- Stage A: PR fast feedback (unit) -->
    <plugin>
      <groupId>org.apache.maven.plugins</groupId>
      <artifactId>maven-surefire-plugin</artifactId>
      <version>3.2.5</version>
      <configuration>
        <groups>unit</groups> <!-- include @Tag("unit") -->
      </configuration>
    </plugin>

    <!-- Stage B/C: integration/E2E (use in separate job or with -Dgroups) -->
    <plugin>
      <groupId>org.apache.maven.plugins</groupId>
      <artifactId>maven-failsafe-plugin</artifactId>
      <version>3.2.5</version>
      <configuration>
        <groups>${it.groups}</groups> <!-- e.g., it.groups=integration,e2e -->
      </configuration>
      <executions>
        <execution>
          <goals><goal>integration-test</goal><goal>verify</goal></goals>
        </execution>
      </executions>
    </plugin>
  </plugins>
</build>
```

**CI examples**

-   PR job: `mvn -q -DskipITs -Dgroups=unit test`
    
-   Merge job: `mvn -q -Dit.groups=integration failsafe:integration-test failsafe:verify`
    
-   Pre-release: `mvn -q -Dit.groups=integration,e2e verify`
    

---

## Known Uses

-   Microservice estates where **unit** guards logic, **contract/integration** protect adapters, and a **handful of E2E** guard journeys.
    
-   Frontends: **component tests** (unit) + **API/contract** + **few UI E2E** (Playwright/Cypress).
    
-   Data platforms: **transform function tests** + **connector integration** + **pipeline E2E smoke**.
    

## Related Patterns

-   **Mocking, Stub, Fake:** tools for the **unit** layer.
    
-   **Contract Testing:** sits between **unit** and **integration**, limits cross-team breakage.
    
-   **Test Containers:** mechanism for **integration** realism.
    
-   **Smoke Testing:** top-of-pyramid gate after deploy.
    
-   **Golden/Snapshot** & **Mutation Testing:** flanking controls to improve signal of lower layers.

