# Consumer-Driven Contracts — Microservice Pattern

## Pattern Name and Classification

**Name:** Consumer-Driven Contracts (CDC)  
**Classification:** Microservices / Integration Governance / Automated Contract Testing

## Intent

Let **consumers specify executable expectations** of a provider’s API (HTTP/gRPC/events). Turn these expectations into **machine-verifiable contracts** that run in CI so providers can **safely evolve** without breaking consumers and consumers can **develop against stable stubs**.

## Also Known As

-   Contract Testing
    
-   Provider Contract Verification
    
-   Consumer-First API Design
    
-   Executable API Specifications
    

## Motivation (Forces)

-   **Independent deployability:** Teams want to ship without big-bang integration tests.
    
-   **Hidden coupling:** Small breaking changes (renamed field, status code) can crash downstreams.
    
-   **Flaky end-to-end tests:** Slow, brittle, environment-heavy; CDC brings feedback **left** into CI.
    
-   **Schema drift:** Multiple consumers expect different shapes; evolution must be explicit.
    
-   **Polyglot stacks:** Contract tests abstract wire format and let each side use its own toolchain.
    

## Applicability

Use CDC when:

-   Multiple clients consume a service (web/mobile/BFF/other services).
    
-   You want **fast, reliable integration feedback** in PR/CI rather than after deploy.
    
-   You maintain **message-driven** contracts (Kafka, SNS/SQS, AMQP) or **HTTP/gRPC** APIs.
    

Avoid or complement with other techniques when:

-   A single team owns both sides and can run **shared component tests** more cheaply.
    
-   The provider exposes a **public, standardized API** (OpenAPI/GraphQL) and strict schema governance already exists—CDC can still back the spec with tests.
    

## Structure

-   **Consumer Contract**: An executable test that generates a pact/spec for expectations (request → response or message in/out).
    
-   **Stub/Mock Server**: Spins up from the contract so the consumer can develop offline.
    
-   **Contract Broker/Registry**: Stores versioned contracts, tags (e.g., `prod`, `main`), environment promotions.
    
-   **Provider Verification**: Provider CI downloads contracts and verifies its implementation against **all active consumer contracts**.
    
-   **Can-I-Deploy Gate**: Pipeline step that blocks deploy when verification status fails.
    

```rust
[Consumer Tests] -> generate contract -> [Broker]
                                   \               \
                                    \               -> [Provider CI] -> verify against live/localhost provider
                                     -> [Consumer uses stub]          -> publish verification -> can-I-deploy?
```

## Participants

-   **Consumer Team** — writes expectations and publishes contracts.
    
-   **Provider Team** — verifies contracts and publishes verification results.
    
-   **Contract Broker** — stores contracts, tags, verification status, and supports “can-I-deploy”.
    
-   **CI/CD Pipelines** — wire steps to publish/verify/gate.
    
-   **Matchers/DSL** — express flexible value constraints (types, regex, arrays).
    

## Collaboration

1.  **Consumer** writes a test describing an interaction it needs. The test runs against a mock based on the contract DSL and produces a **contract artifact**.
    
2.  Contract is **published** to a **broker** and tagged (e.g., `main`, `prod`).
    
3.  **Provider** pipeline **pulls all relevant contracts** (by tag/branch) and **verifies** them against the real implementation (on localhost or test env), providing **state setup** for scenarios.
    
4.  Verification results are sent back to the broker.
    
5.  A **can-I-deploy** check ensures only compatible artifacts get promoted.
    

## Consequences

**Benefits**

-   **Rapid feedback** (seconds) vs. brittle end-to-end tests (minutes/hours).
    
-   **Consumer safety**: Providers can’t accidentally break existing consumers.
    
-   **Parallel development**: Consumers develop against **generated stubs**.
    
-   **Living documentation**: Contracts are executable, versioned, and visible.
    

**Liabilities**

-   **Narrow scope**: CDC proves interaction compatibility, **not** end-to-end correctness or data realism.
    
-   **Over-specification risk**: Consumers must avoid pinning incidental details (headers, ordering) unless required.
    
-   **Contract sprawl**: Many consumers × endpoints → many contracts; needs broker governance.
    
-   **State management**: Provider verification requires realistic **provider states**.
    

## Implementation

**Key practices**

-   **Per-consumer contracts**: Provider must satisfy all **active** consumer contracts.
    
-   **Loose but precise**: Use **matchers** (types, regex, min/max sizes). Avoid hard-coding timestamps/IDs.
    
-   **Versioning & tags**: Tag contracts by branch/environment; promote only when verified in target env.
    
-   **Provider states**: Implement `@State("…")` handlers (HTTP) or fixtures (messaging) to set data preconditions.
    
-   **Negative paths**: Include expected error responses (e.g., `404`, `422`).
    
-   **Non-HTTP**: For events, use message CDC (e.g., Pact message pacts or Spring Cloud Contract messaging).
    
-   **Governance**: Expire old contracts, document deprecations, enforce **backward compatible** changes (additive fields).
    
-   **Spec alignment**: Optionally generate or check **OpenAPI/AsyncAPI** from contracts to keep docs in sync.
    

---

## Sample Code (Java) — Pact JVM (HTTP)

Below is a compact, end-to-end example:

-   **Consumer test** defines expectations and generates a pact file.
    
-   **Provider verification** runs the contract against a real Spring Boot controller with **provider states**.
    

> Dependencies (Gradle snippets)

```groovy
// Consumer module
testImplementation 'au.com.dius.pact.consumer:junit5:4.6.9'
testImplementation 'org.junit.jupiter:junit-jupiter:5.10.2'

// Provider module
testImplementation 'au.com.dius.pact.provider:junit5:4.6.9'
testImplementation 'org.springframework.boot:spring-boot-starter-web'
testImplementation 'org.springframework.boot:spring-boot-starter-test'
```

### 1) Consumer contract test (generates the pact)

```java
// consumer/src/test/java/com/example/catalog/CatalogConsumerPactTest.java
package com.example.catalog;

import au.com.dius.pact.consumer.dsl.PactDslJsonBody;
import au.com.dius.pact.consumer.dsl.PactDslWithProvider;
import au.com.dius.pact.consumer.junit5.*;
import au.com.dius.pact.core.model.annotations.Pact;
import au.com.dius.pact.core.model.RequestResponsePact;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

@ExtendWith(PactConsumerTestExt.class)
@PactTestFor(providerName = "catalog-service", pactVersion = PactSpecVersion.V3)
class CatalogConsumerPactTest {

  @Pact(consumer = "web-bff")
  RequestResponsePact productExists(PactDslWithProvider p) {
    var body = new PactDslJsonBody()
        .stringMatcher("sku", "SKU-[0-9]+", "SKU-123")
        .stringType("name", "Coffee Beans")
        .integerType("priceMinor", 1299)
        .stringMatcher("currency", "EUR|USD", "EUR")
        .booleanType("active", true);

    return p
      .uponReceiving("get product by sku (exists)")
        .path("/api/products/SKU-123").method("GET")
        .headers(Map.of("Accept", "application/json"))
      .willRespondWith()
        .status(200)
        .headers(Map.of("Content-Type", "application/json; charset=UTF-8"))
        .body(body)
      .toPact();
  }

  @Test
  @PactTestFor(pactMethod = "productExists")
  void consumerCanDeserialize(MockServer server) {
    var client = new CatalogClient(); // simple HTTP client below
    var prod = client.get(server.getUrl() + "/api/products/SKU-123");
    assertThat(prod.sku()).startsWith("SKU-");
    assertThat(prod.currency()).isIn("EUR", "USD");
  }
}

// Minimal DTO + client used by the consumer
record Product(String sku, String name, int priceMinor, String currency, boolean active) {}

class CatalogClient {
  Product get(String url) {
    try (var http = java.net.http.HttpClient.newHttpClient()) {
      var req = java.net.http.HttpRequest.newBuilder(java.net.URI.create(url))
          .GET().header("Accept", "application/json").build();
      var res = http.send(req, java.net.http.HttpResponse.BodyHandlers.ofString());
      if (res.statusCode() != 200) throw new RuntimeException("bad status " + res.statusCode());
      var json = new com.fasterxml.jackson.databind.ObjectMapper().readTree(res.body());
      return new Product(
          json.get("sku").asText(),
          json.get("name").asText(),
          json.get("priceMinor").asInt(),
          json.get("currency").asText(),
          json.get("active").asBoolean()
      );
    } catch (Exception e) { throw new RuntimeException(e); }
  }
}
```

This test generates `web-bff-catalog-service.json` under `target/pacts` (or `build/pacts`). Publish it to your broker in CI.

### 2) Provider verification (Spring Boot, JUnit 5)

```java
// provider/src/test/java/com/example/catalog/CatalogProviderPactTest.java
package com.example.catalog;

import au.com.dius.pact.provider.junit5.*;
import au.com.dius.pact.provider.junitsupport.*;
import au.com.dius.pact.provider.junitsupport.loader.*;
import au.com.dius.pact.provider.junitsupport.target.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.TestTemplate;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.web.server.LocalServerPort;

import java.util.Map;

@Provider("catalog-service")
// Option A: load pact from local folder (CI can clone/export from broker)
@PactFolder("build/pacts")
// Option B (preferred): use a Pact Broker
// @PactBroker(url = "${PACT_BROKER_URL}", authentication = @PactBrokerAuth(token = "${PACT_BROKER_TOKEN}"))
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ExtendWith(PactVerificationInvocationContextProvider.class)
class CatalogProviderPactTest {

  @LocalServerPort int port;

  @BeforeEach
  void setup(PactVerificationContext context) {
    context.setTarget(new HttpTestTarget("localhost", port, "/"));
  }

  // Provider states set up data preconditions for interactions
  @State("product SKU-123 exists")
  public void productExistsState() {
    FakeCatalogRepository.DATA.put("SKU-123",
      new Product("SKU-123", "Coffee Beans", 1299, "EUR", true));
  }

  @TestTemplate
  void pactVerification(PactVerificationContext context) { context.verifyInteraction(); }
}
```

```java
// provider/src/main/java/com/example/catalog/CatalogApp.java
package com.example.catalog;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
@SpringBootApplication public class CatalogApp {
  public static void main(String[] args) { SpringApplication.run(CatalogApp.class, args); }
}
```

```java
// provider/src/main/java/com/example/catalog/CatalogController.java
package com.example.catalog;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import java.util.*;

@RestController
@RequestMapping("/api/products")
class CatalogController {
  private final FakeCatalogRepository repo = new FakeCatalogRepository();

  @GetMapping("/{sku}")
  ResponseEntity<Product> get(@PathVariable String sku) {
    return Optional.ofNullable(repo.find(sku))
      .map(ResponseEntity::ok)
      .orElse(ResponseEntity.notFound().build());
  }
}

// Simple in-memory repo used in tests
class FakeCatalogRepository {
  static final Map<String, Product> DATA = new HashMap<>();
  Product find(String sku) { return DATA.get(sku); }
}

// Shared DTO (provider can have its own internal model; expose API model)
record Product(String sku, String name, int priceMinor, String currency, boolean active){}
```

**How this fits a real pipeline**

-   **Consumer CI**: run consumer tests → **publish pact** to broker → tag `main`.
    
-   **Provider CI**: fetch all pacts tagged `main` → run provider verification (with provider states) → **publish verification**.
    
-   **Deploy gate**: run `can-i-deploy` (broker CLI) for the provider/consumer and target environment tag (e.g., `prod`).
    

> For **messaging** (Kafka, SQS), use Pact **message pacts** or **Spring Cloud Contract** messaging; the idea is identical—consumers define the message they expect to receive (or produce), providers verify serialization and schema.

## Known Uses

-   Widely adopted with **Pact** or **Spring Cloud Contract** across e-commerce, fintech, media, and govtech.
    
-   Replaces large portions of brittle **end-to-end** suites with fast, reliable CI gates.
    
-   Governs both **HTTP** and **event** interfaces in event-driven architectures.
    

## Related Patterns

-   **Published Language / Open Host Service:** CDC can validate the executable form of these contracts.
    
-   **API Gateway / BFF:** CDC guards the contracts exposed to those edges.
    
-   **Schema Registry (Avro/Protobuf/JSON):** CDC complements schema compatibility checks for event streams.
    
-   **Anti-Corruption Layer (ACL):** Translate upstream contracts to your domain model; CDC verifies the boundary.
    
-   **Canary / Blue-Green:** After contract verification, progressive delivery reduces residual risk.
    
-   **Change Data Capture (CDC-DB)** *(homonym)*: Database log capture—unrelated to this pattern except both involve “contracts”.

