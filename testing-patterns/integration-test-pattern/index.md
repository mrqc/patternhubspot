# Integration Test — Testing Pattern

## Pattern Name and Classification

-   **Name:** Integration Test
    
-   **Classification:** System Construction / Multi-Component Verification / Black- & Gray-box Testing
    

## Intent

Verify that **multiple components** (your code + real adapters such as databases, message brokers, filesystems, HTTP services) **work together correctly** in a production-like way—exercising wiring, configuration, data mappings, transactions, timeouts, and error handling that unit tests won’t catch.

## Also Known As

-   Component Integration Test
    
-   Service Integration Test
    
-   “IT” (common module suffix)
    
-   Contract + Adapter Test (when focused on a particular boundary)
    

## Motivation (Forces)

-   **Realism vs. speed:** you need realistic signals (actual drivers, SQL, TLS, JSON) but want fast feedback.
    
-   **Hidden defects:** misconfigured pools, N+1 queries, serialization quirks, transaction boundaries, and timeouts tend to surface only with **real dependencies**.
    
-   **Confidence:** before E2E, verify each service (+ its infrastructure) behaves correctly in isolation.  
    Tensions include **environment parity** (prod-like), **flakiness** (shared envs), **data management**, and **runtime**.
    

## Applicability

Use Integration Tests when:

-   You must verify **adapters** (JDBC repositories, REST clients, Kafka producers/consumers).
    
-   You are adding a new **infrastructure dependency** (cache, queue, object store).
    
-   You need to validate **configurations** (connection pools, migrations, auth, TLS).
    
-   You want **guardrails** that are stronger than unit tests but cheaper than E2E.
    

Be cautious when:

-   The behavior is purely algorithmic (unit test suffices).
    
-   Tests depend on **shared, mutable external environments** (prefer ephemeral containers/sandboxes).
    
-   You’re attempting to test **entire business flows** across many services (that’s E2E).
    

## Structure

-   **SUT (Service/Component):** business logic plus its **real adapters**.
    
-   **Real Dependency:** DB, broker, filesystem, HTTP service (ideally ephemeral).
    
-   **Provisioner:** spins up dependencies (e.g., Testcontainers, Docker Compose, local emulators).
    
-   **Fixture/Data Seeder:** creates schemas/seed data; resets state.
    
-   **Driver:** invokes SUT through public API or port.
    
-   **Assertions/Probes:** verify side effects (rows, messages, files), timing, transactions.
    

```scss
[Test Runner] → [SUT (service)] ↔ [Real DB/Broker/HTTP]   (provisioned per test/class)
                           ↑
                        [Fixtures/Seeders]  →  assert persisted state & side effects
```

## Participants

-   **Test Runner/Framework** (JUnit/TestNG/Spock).
    
-   **Provisioner** (Testcontainers, Docker Compose, k8s kind, LocalStack, WireMock).
    
-   **SUT** (service class/app module).
    
-   **Real Adapter** (JDBC/REST/gRPC/Kafka client).
    
-   **Assertion Helpers** (DB probe, HTTP capture, message consumer).
    

## Collaboration

1.  Provision the **real dependency** (container/emulator).
    
2.  Initialize **schema/config/fixtures**.
    
3.  Invoke SUT via **public interfaces** (service method/HTTP).
    
4.  Assert **outputs and side effects** (rows, messages, files), including **transactionality and retries**.
    
5.  Tear down; keep **artifacts** (logs) on failure.
    

## Consequences

**Benefits**

-   Catches **adapter/config bugs** early (SQL, serialization, TLS, pool limits).
    
-   High confidence that service **“works on my CI”** before staging/E2E.
    
-   Encourages clean **ports/adapters** and reproducible environments.
    

**Liabilities**

-   Slower than unit tests; can be **flaky** if env is unstable.
    
-   Requires **orchestration** (containers/emulators) and **test data management**.
    
-   Overuse can bloat CI—keep a **thin, valuable set**.
    

## Implementation

### Guidelines

-   **Ephemeral dependencies:** start per test/class using containers or emulators; avoid shared long-lived envs.
    
-   **Idempotent setup:** migrations run on empty DB; unique namespaces/queues per run.
    
-   **Deterministic time:** fake/controlled clocks when relevant; avoid “sleep” in favor of **awaiting conditions**.
    
-   **Tight scope:** each IT focuses on **one boundary** (DB repo, HTTP client, messaging).
    
-   **Observability:** capture dependency logs; surface SQL/HTTP for triage.
    
-   **Parallelism:** run containers in parallel where possible; shard suites in CI.
    
-   **Fail-fast:** short timeouts, clear assertions, minimal fixtures.
    

### Typical Tooling

-   **Provisioning:** Testcontainers, Docker Compose, LocalStack, Embedded Redis, WireMock/MockServer (when the real third party is impractical).
    
-   **DB:** Flyway/Liquibase for schema; JDBC/JPA/Hibernate.
    
-   **HTTP:** REST-Assured/Java HttpClient for calls + assertions.
    
-   **Messaging:** Testcontainers for Kafka/RabbitMQ + consumer probes.
    

---

## Sample Code (Java 17, JUnit 5 + Testcontainers, PostgreSQL)

> Verifies a JDBC repository against a **real Postgres** container: schema migration, insert, uniqueness, and transactional readback.  
> (Requires dependencies: `org.testcontainers:junit-jupiter`, `org.testcontainers:postgresql`.)

```java
// src/test/java/example/integration/UserRepositoryIntegrationTest.java
package example.integration;

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
class UserRepositoryIntegrationTest {

  // --- Provision a real Postgres instance (ephemeral) ---
  @Container
  static final PostgreSQLContainer<?> POSTGRES =
      new PostgreSQLContainer<>("postgres:16-alpine")
          .withDatabaseName("app")
          .withUsername("app")
          .withPassword("secret");

  static String URL, USER, PASS;
  UserRepository repo;

  @BeforeAll
  static void startDb() {
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
        TRUNCATE TABLE users;
      """);
    }
    repo = new UserRepository(URL, USER, PASS);
  }

  @Test
  void saves_and_reads_user_through_real_jdbc() throws Exception {
    UUID id = UUID.randomUUID();
    Instant now = Instant.parse("2025-01-01T12:00:00Z");

    repo.save(new User(id, "alice@example.com", now));

    Optional<User> loaded = repo.findByEmail("alice@example.com");
    assertTrue(loaded.isPresent(), "user should exist");
    assertEquals(id, loaded.get().id());
    assertEquals(now, loaded.get().createdAt());
  }

  @Test
  void enforces_unique_email_constraint() throws Exception {
    repo.save(new User(UUID.randomUUID(), "bob@example.com", Instant.now()));
    var e = assertThrows(SQLException.class, () ->
        repo.save(new User(UUID.randomUUID(), "bob@example.com", Instant.now())));
    assertTrue(e.getMessage().toLowerCase().contains("duplicate"), "should be unique violation");
  }

  // --- SUT: a very small JDBC-based repository (real adapter under test) ---
  static final class User {
    final UUID id; final String email; final Instant createdAt;
    User(UUID id, String email, Instant createdAt) { this.id = id; this.email = email; this.createdAt = createdAt; }
    UUID id(){ return id; } String email(){ return email; } Instant createdAt(){ return createdAt; }
  }

  static final class UserRepository {
    private final String url, user, pass;
    UserRepository(String url, String user, String pass) { this.url = url; this.user = user; this.pass = pass; }

    void save(User u) throws SQLException {
      try (Connection c = DriverManager.getConnection(url, user, pass)) {
        c.setAutoCommit(false);
        try (PreparedStatement ps = c.prepareStatement("INSERT INTO users(id,email,created_at) VALUES (?,?,?)")) {
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
           PreparedStatement ps = c.prepareStatement("SELECT id,email,created_at FROM users WHERE email=?")) {
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

**Highlights of the sample**

-   Uses **real Postgres** via Testcontainers (no mocking).
    
-   Creates and truncates schema per test for **isolation**.
    
-   Asserts **uniqueness** is enforced by the DB (real constraint).
    
-   Exercises **transactions** and **JDBC mappings**—the essence of an integration test.
    

> Variations: spin up Kafka and verify produced messages; start a WireMock server to validate an HTTP client; use LocalStack for S3/GCS; or compose multiple dependencies.

## Known Uses

-   **Repository/DAO** tests against real databases (Postgres/MySQL/SQLite).
    
-   **HTTP client** integration (OAuth/TLS/serialization quirks) against WireMock or partner sandboxes.
    
-   **Message broker** tests (Kafka/RabbitMQ) verifying serialization, headers, and retries.
    
-   **Filesystem/object storage** integrations (S3/MinIO/LocalStack).
    
-   **Cache** integration (Redis) to validate TTLs, eviction, and serialization.
    

## Related Patterns

-   **Unit Test:** isolates logic with doubles—faster but less realistic.
    
-   **Contract Testing:** verifies interface compatibility with other teams/services.
    
-   **End-to-End Testing:** full system journeys across multiple services.
    
-   **Fake Object / Test Double:** useful **inside** unit tests; integration tests replace those with **real adapters**.
    
-   **Golden Master:** snapshot external outputs; can be used inside integration tests for renderers/serializers.
    
-   **Canary Testing:** production rollout pattern after integration tests pass.
    

---

## Implementation Tips

-   Prefer **ephemeral, local** dependencies (containers/emulators) to avoid shared-env flake.
    
-   Keep tests **focused**: one boundary per IT; broad flows belong to E2E.
    
-   Make setup **idempotent** (migrations), and teardown **fast** (truncate, drop schema).
    
-   Use **short timeouts** and **awaitility** for async dependencies instead of sleeps.
    
-   Capture and surface **logs/artifacts** (SQL, HTTP) to make failures actionable.
    
-   Run a **small, critical** set per PR; a fuller suite nightly to balance cost and confidence.

