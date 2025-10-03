# Consumer-Driven Contracts — Design Pattern

## Pattern Name and Classification

**Consumer-Driven Contracts (CDC)** — *API Design / Integration Testing* pattern for service collaboration in microservices and distributed systems.

---

## Intent

Let **consumers define executable contracts** that specify exactly how they call a provider (request + response schema, headers, status), and **verify** that providers continuously satisfy those expectations.

---

## Also Known As

-   **Contract Testing**

-   **Pact Testing** (by tool association)

-   **Provider Verification against Consumer Contracts**


---

## Motivation (Forces)

-   Independent deployability needs **fast feedback** that integrations still work.

-   End-to-end tests are **slow/flaky/expensive**; unit tests miss **integration details**.

-   Providers tend to **over- or under-document**; consumers rely on **actual behavior**.

-   Schemas evolve; you need **safe change** and **backward compatibility**.


---

## Applicability

Use CDC when:

-   You have multiple **consumers** of a service (web, mobile, other services).

-   You need **CI-time verification** that provider changes won’t break consumers.

-   You version APIs and want **confidence without full E2E**.


Avoid/limit when:

-   Integration is **binary/proprietary** with no feasible contract runner.

-   Interactions are **highly dynamic** and not stabilizable into tests (e.g., ad-hoc SQL access—don’t do that).


---

## Structure

```java
Consumer Test (mock provider)   ──>  Produces Contract (pact.json)
           |                                   |
           v                                   v
    Publishes to Broker                Provider Verification
 (Pact Broker / Git / Registry)   runs against real provider or test instance
```

---

## Participants

-   **Consumer**: Defines expectations and generates contracts.

-   **Provider**: Verifies contracts; serves API.

-   **Contract/Broker**: Stores/distributes contracts and verification results.

-   **CI/CD**: Fails builds when verification fails.


---

## Collaboration

1.  **Consumer** runs tests against a **mock provider**, producing a **contract file**.

2.  Contract is **published** (e.g., Pact Broker).

3.  **Provider** CI pipeline **pulls** contracts and runs **verification** against the real provider (or provider stub).

4.  Results are **reported** back to the broker; release gates use them.


---

## Consequences

**Benefits**

-   **Early, fast feedback**; fewer brittle E2E tests.

-   Enables **independent deployment** with confidence.

-   Contracts double as **living documentation**.


**Liabilities**

-   Requires **discipline** to keep contracts meaningful (not over-specific).

-   **Multi-consumer** cases require managing **compatibility** across versions.

-   Doesn’t test **runtime concerns** (latency, auth flows) unless modeled explicitly.


---

## Implementation (Key Points)

-   Pick a mature tool: **Pact** (JVM/JS), **Spring Cloud Contract**, **OpenAPI + schematized tests**.

-   Keep contracts **consumer-focused** (required fields only; permissive where appropriate).

-   Use a **broker** to coordinate many consumers/providers and **can-I-deploy** checks.

-   Verify in CI on **every change** (consumer produces; provider verifies).

-   Treat contracts like code: **review, version, diff**.


---

## Sample Code (Java, Pact JVM + Spring Boot)

### Scenario

Consumer needs `GET /customers/{id}` → `200 OK` with minimal fields.  
We’ll show:

1.  **Consumer test** generating the pact.

2.  **Provider verification** running against a Spring Boot controller.


> Gradle (snippets)

```gradle
dependencies {
  testImplementation "au.com.dius.pact.consumer:junit5:4.6.10"
  testImplementation "au.com.dius.pact.provider:junit5spring:4.6.10"
  implementation "org.springframework.boot:spring-boot-starter-web"
  testImplementation "org.springframework.boot:spring-boot-starter-test"
}
test {
  systemProperty "pact.rootDir", "$buildDir/pacts" // where pacts are written
}
```

### 1) Consumer side (produces contract)

```java
// src/test/java/com/example/consumer/CustomerConsumerPactTest.java
package com.example.consumer;

import au.com.dius.pact.consumer.dsl.PactDslWithProvider;
import au.com.dius.pact.consumer.dsl.PactDslJsonBody;
import au.com.dius.pact.consumer.junit5.*;
import au.com.dius.pact.core.model.RequestResponsePact;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

@ExtendWith(PactConsumerTestExt.class)
@PactTestFor(providerName = "customer-service", port = "0")
class CustomerConsumerPactTest {

  @Pact(consumer = "mobile-app")
  public RequestResponsePact definePact(PactDslWithProvider builder) {
    var body = new PactDslJsonBody()
        .stringType("id", "c-123")
        .stringType("name", "Ada Lovelace")
        .stringMatcher("email", ".+@.+\\..+", "ada@example.com");

    return builder
        .given("customer c-123 exists")
        .uponReceiving("get existing customer by id")
            .path("/customers/c-123")
            .method("GET")
            .headers(Map.of("Accept", "application/json"))
        .willRespondWith()
            .status(200)
            .headers(Map.of("Content-Type", "application/json"))
            .body(body)
        .toPact();
  }

  @Test
  void consumerCanParseResponse(MockServer mockServer) throws Exception {
    var url = mockServer.getUrl() + "/customers/c-123";
    var json = new java.net.URL(url).openStream().readAllBytes();
    var s = new String(json);
    assertThat(s).contains("\"id\":\"c-123\"");
  }
}
```

This test produces `build/pacts/mobile-app-customer-service.json`.

### 2) Provider side (verifies contract)

**Provider Controller (real implementation)**

```java
// src/main/java/com/example/provider/CustomerApp.java
package com.example.provider;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
@SpringBootApplication
public class CustomerApp {
  public static void main(String[] args) { SpringApplication.run(CustomerApp.class, args); }
}
```

```java
// src/main/java/com/example/provider/CustomerController.java
package com.example.provider;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/customers")
class CustomerController {

  @GetMapping("/{id}")
  ResponseEntity<CustomerDto> get(@PathVariable String id) {
    // demo dataset
    if (!"c-123".equals(id)) return ResponseEntity.notFound().build();
    return ResponseEntity.ok(new CustomerDto("c-123", "Ada Lovelace", "ada@example.com"));
  }

  record CustomerDto(String id, String name, String email) {}
}
```

**Provider Verification Test**

```java
// src/test/java/com/example/provider/CustomerProviderPactVerificationTest.java
package com.example.provider;

import au.com.dius.pact.provider.junit5.*;
import au.com.dius.pact.provider.spring.junit5.PactVerificationSpringProvider;
import au.com.dius.pact.provider.junit5.HttpTestTarget;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;

import static org.assertj.core.api.Assertions.assertThat;

@Provider("customer-service")
@Consumer("mobile-app")
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ExtendWith(PactVerificationInvocationContextProvider.class)
class CustomerProviderPactVerificationTest {

  @LocalServerPort int port;

  @BeforeEach
  void before(PactVerificationContext context) {
    context.setTarget(new HttpTestTarget("localhost", port, "/"));
  }

  @State("customer c-123 exists")
  void customerExists() {
    // set up state if needed (seed DB, etc.)
    assertThat(true).isTrue();
  }

  @TestTemplate
  @ExtendWith(PactVerificationSpringProvider.class)
  void verify(PactVerificationContext context) {
    context.verifyInteraction();
  }
}
```

Run provider verification with the pact file available (e.g., copy from consumer or pull from a Pact Broker). In CI you’d typically use a **Pact Broker** and `can-i-deploy` checks before releasing.

---

## Known Uses

-   Widely adopted with **Pact** and **Spring Cloud Contract** across microservice estates (e.g., financial services, retail, streaming).

-   Teams replacing a portion of brittle **E2E tests** with CDC to speed up pipelines.


---

## Related Patterns

-   **API Composition** — CDC complements aggregation by ensuring each composed call is compatible.

-   **API Gateway / BFF** — contracts per edge surface help stabilize clients.

-   **Schema Versioning / Tolerant Reader** — strategies for safely evolving responses.

-   **Contract-First (OpenAPI/AsyncAPI)** — CDC can be generated from/validated against specs.

-   **Consumer-Driven Schema / Event Contracts** — same idea for **messaging** (Kafka, SNS/SQS).
