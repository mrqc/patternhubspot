# Test Containers — Testing Pattern

## Pattern Name and Classification

-   **Name:** Test Containers
    
-   **Classification:** Environment Provisioning / Integration & System Testing Enabler
    

## Intent

Provision **real external dependencies** (databases, message brokers, object stores, HTTP services) **on demand** inside tests using lightweight **containers**, so tests are **realistic, hermetic, repeatable, and self-contained**—without maintaining shared test environments.

## Also Known As

-   Ephemeral Test Environments
    
-   Containerized Test Fixtures
    
-   On-Demand Infra for Tests
    

## Motivation (Forces)

-   **Realism vs. speed:** unit tests are fast but miss adapter/config issues; shared staging is realistic but flaky & slow.
    
-   **Isolation:** shared DBs/queues lead to test interference.
    
-   **Reproducibility:** “works on my machine” disappears when tests boot their own infra.
    
-   **Dev/CI parity:** the same container image runs locally and in CI.  
    Tensions:
    
-   **Start-up cost:** pulling/starting containers adds minutes if not cached.
    
-   **Docker availability:** CI must support a Docker daemon or compatible runtime.
    
-   **State management:** keep data deterministic across tests.
    

## Applicability

Use Test Containers when:

-   Verifying code that **talks to real infra** (JDBC, Kafka, S3, SMTP, Redis, Elasticsearch, etc.).
    
-   You want **hermetic integration tests**: each run provisions its own clean dependencies.
    
-   You need **portable, developer-friendly** setups that mirror production images.
    

Be cautious when:

-   Your CI cannot run containers (policy/privileges).
    
-   Very large images or long boot times make feedback too slow—optimize (reusable containers, local registry, thinner images).
    

## Structure

-   **Provisioner (Library):** starts/stops containers programmatically from tests.
    
-   **Containers (Dependencies):** official or custom images (Postgres, Kafka, LocalStack, WireMock…).
    
-   **Network:** optional shared network to connect multiple containers.
    
-   **Wait Strategies:** health/readiness checks before tests proceed.
    
-   **Fixture/Seeder:** creates schema, topics, buckets, test data.
    
-   **SUT/Adapter:** the code under test that connects to the provisioned dependency.
    

```scss
[Test Runner] → [Test Code]
                 ├── start container(s) (wait until ready)
                 ├── seed fixtures (schema/data)
                 ├── exercise SUT using container endpoints
                 └── assert outputs & side effects → stop containers
```

## Participants

-   **Test Framework** (JUnit/TestNG/Spock).
    
-   **Testcontainers Library** (JVM testcontainers).
    
-   **Container Runtime** (Docker/Podman, CI runner).
    
-   **Dependency Images** (e.g., `postgres:16-alpine`, `confluentinc/cp-kafka`, `localstack/localstack`).
    
-   **SUT/Adapters** (JDBC client, HTTP client, SDKs).
    

## Collaboration

1.  Test declares **containers** (class- or method-scoped).
    
2.  Provisioner pulls images, starts containers, and **waits for readiness**.
    
3.  Test seeds **schemas/topics/buckets**.
    
4.  SUT connects using **runtime-provided URLs/ports**.
    
5.  Test asserts **behavior & side effects**; containers stop automatically.
    

## Consequences

**Benefits**

-   **Realistic** adapter/configuration validation (SQL, TLS, serialization, retries).
    
-   **Hermetic** and **parallelizable** tests; no shared state.
    
-   **Portable:** same tests run locally and in CI with identical images.
    
-   **Developer friendly:** no manual service install for contributors.
    

**Liabilities**

-   **Cold-start time** (first pull) and per-test boot overhead.
    
-   Requires **Docker access** and sometimes special CI configuration.
    
-   If abused for long E2E flows, suites can become **slow**—keep tests tight and focused.
    

## Implementation

### Design Guidelines

-   **Scope wisely:** prefer **class-scoped** containers for a test class; method-scoped only when isolation requires it.
    
-   **Seed deterministically:** run migrations/fixtures at setup; **truncate** between tests.
    
-   **Wait for readiness:** use provided **wait strategies** or health endpoints.
    
-   **Network composition:** place related containers on a **shared network** if the SUT container needs to call others.
    
-   **Reuse (optional):** `.withReuse(true)` + `~/.testcontainers.properties` can speed local dev; be careful with stale state.
    
-   **Parallelization:** isolate resources (DB names, topics, buckets) to allow concurrent tests.
    
-   **CI caching:** pre-pull images or use a registry mirror to avoid cold pulls.
    

### Operational Tips

-   Log container **stdout/stderr** on failure for troubleshooting.
    
-   Use **lightweight images** (e.g., `-alpine`) where possible.
    
-   Time-bound your tests; configure **short client timeouts** to fail fast.
    
-   For security-sensitive CI, prefer **Docker socket via sidecar** (sibling) rather than DinD, if allowed.
    

---

## Sample Code (Java 17, JUnit 5 + Testcontainers, PostgreSQL)

> A realistic **JDBC repository integration test** against a **real Postgres** container.  
> The test creates schema, inserts data, verifies **uniqueness** and round-trips entities.

```java
// src/test/java/example/testcontainers/UserRepositoryTcTest.java
package example.testcontainers;

import org.junit.jupiter.api.*;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.sql.*;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;

@Testcontainers
class UserRepositoryTcTest {

  // Class-scoped container: start once for all tests in this class
  @Container
  static final PostgreSQLContainer<?> POSTGRES =
      new PostgreSQLContainer<>("postgres:16-alpine")
          .withDatabaseName("app")
          .withUsername("app")
          .withPassword("secret");
          // .withReuse(true) // optional: enable local reuse (requires testcontainers.properties)

  static String URL, USER, PASS;
  UserRepository repo;

  @BeforeAll
  static void boot() {
    URL = POSTGRES.getJdbcUrl();
    USER = POSTGRES.getUsername();
    PASS = POSTGRES.getPassword();
  }

  @BeforeEach
  void setUp() throws Exception {
    try (Connection c = DriverManager.getConnection(URL, USER, PASS);
         Statement st = c.createStatement()) {
      st.execute("""
        CREATE TABLE IF NOT EXISTS users (
          id UUID PRIMARY KEY,
          email TEXT UNIQUE NOT NULL,
          created_at TIMESTAMPTZ NOT NULL
        );
      """);
      st.execute("TRUNCATE TABLE users;");
    }
    repo = new UserRepository(URL, USER, PASS);
  }

  @Test
  void saves_and_reads_user_through_real_postgres() throws Exception {
    UUID id = UUID.randomUUID();
    Instant now = Instant.parse("2025-01-01T12:00:00Z");

    repo.save(new User(id, "alice@example.com", now));

    Optional<User> loaded = repo.findByEmail("alice@example.com");
    assertTrue(loaded.isPresent());
    assertEquals(id, loaded.get().id());
    assertEquals(now, loaded.get().createdAt());
  }

  @Test
  void enforces_unique_email_constraint() throws Exception {
    repo.save(new User(UUID.randomUUID(), "bob@example.com", Instant.now()));
    SQLException ex = assertThrows(SQLException.class,
        () -> repo.save(new User(UUID.randomUUID(), "bob@example.com", Instant.now())));
    assertTrue(ex.getMessage().toLowerCase().contains("duplicate"),
        "should be a unique constraint violation");
  }

  // --- SUT: a thin JDBC repository (real adapter under test) ---
  static final class User {
    final UUID id; final String email; final Instant createdAt;
    User(UUID id, String email, Instant createdAt) {
      this.id = id; this.email = email; this.createdAt = createdAt;
    }
    UUID id(){ return id; } String email(){ return email; } Instant createdAt(){ return createdAt; }
  }

  static final class UserRepository {
    private final String url, user, pass;
    UserRepository(String url, String user, String pass) { this.url = url; this.user = user; this.pass = pass; }

    void save(User u) throws SQLException {
      try (Connection c = DriverManager.getConnection(url, user, pass)) {
        c.setAutoCommit(false);
        try (PreparedStatement ps = c.prepareStatement(
            "INSERT INTO users(id,email,created_at) VALUES (?,?,?)")) {
          ps.setObject(1, u.id(), java.sql.Types.OTHER);
          ps.setString(2, u.email());
          ps.setObject(3, Timestamp.from(u.createdAt()));
          ps.executeUpdate();
        }
        c.commit();
      }
    }

    Optional<User> findByEmail(String email) throws SQLException {
      try (Connection c = DriverManager.getConnection(url, user, pass);
           PreparedStatement ps = c.prepareStatement(
               "SELECT id,email,created_at FROM users WHERE email=?")) {
        ps.setString(1, email);
        try (ResultSet rs = ps.executeQuery()) {
          if (!rs.next()) return Optional.empty();
          UUID id = (UUID) rs.getObject("id");
          String em = rs.getString("email");
          Instant at = rs.getTimestamp("created_at").toInstant();
          return Optional.of(new User(id, em, at));
        }
      }
    }
  }
}
```

### Variations (concise snippets)

**Multiple containers on a shared network (Kafka + app container):**

```java
Network net = Network.newNetwork();

KafkaContainer kafka = new KafkaContainer("confluentinc/cp-kafka:7.6.0").withNetwork(net);
GenericContainer<?> app = new GenericContainer<>("ghcr.io/acme/myservice:test")
    .withNetwork(net)
    .withEnv("KAFKA_BOOTSTRAP", "PLAINTEXT://"+kafka.getNetworkAliases().get(0)+":9092")
    .waitingFor(Wait.forHttp("/actuator/health").forStatusCode(200));

kafka.start(); app.start();
// drive app through HTTP; assert messages landed on Kafka, etc.
```

**LocalStack for cloud SDK integration:**

```java
@Container
static final LocalStackContainer LOCALSTACK =
    new LocalStackContainer(DockerImageName.parse("localstack/localstack:3.6"))
        .withServices(LocalStackContainer.Service.S3);

String s3Endpoint = LOCALSTACK.getEndpointOverride(LocalStackContainer.Service.S3).toString();
// configure SDK with endpoint + credentials provided by container
```

---

## Known Uses

-   **Repositories/DAOs** against real Postgres/MySQL/SQLite.
    
-   **Messaging**: Kafka/RabbitMQ producers & consumers with real serialization and headers.
    
-   **Object storage** via **LocalStack/MinIO** for S3-compatible flows.
    
-   **Search** with Elasticsearch/OpenSearch containers.
    
-   **HTTP integrations** with WireMock/MockServer containers for contract-level tests.
    
-   **End-to-end “service-in-a-box”** using Docker Compose or multiple containers on a shared network.
    

## Related Patterns

-   **Integration Testing:** Test Containers is a **mechanism** to run realistic integration tests.
    
-   **Contract Testing:** pairs well—verify provider against contracts using containerized dependencies.
    
-   **Golden/Snapshot Testing:** lock text outputs generated while running against real infra.
    
-   **Canary/Smoke Testing:** post-deploy checks; Test Containers handles **pre-deploy** test realism.
    
-   **Fakes/Mocks/Stubs:** great for unit speed; Test Containers covers the **real adapter** path.
    

---

## Implementation Tips

-   Cache images in CI; use a **registry mirror** to avoid cold pulls.
    
-   Prefer **class-scoped** containers and **TRUNCATE/RESET** between tests to balance speed and isolation.
    
-   Use **wait strategies** (port, HTTP health, log message) to avoid race conditions.
    
-   Keep **fixtures small**; fail fast with short client timeouts.
    
-   Consider **reusable containers** only for local dev (guard against stale state).
    
-   Surface **container logs** on failure for quick triage.
    
-   Tag such tests (e.g., `@Tag("integration")`) and run a **thin subset on PRs**, full set nightly or pre-release.
    

With this pattern, you get **realistic, hermetic, and portable** tests that validate the exact adapter and configuration your production code will use—without the operational pain of shared environments.

