# Message Translator — Enterprise Integration Pattern

## Pattern Name and Classification

**Name:** Message Translator  
**Classification:** Transformation pattern (EIP); converts between message **formats, schemas, and semantics** so endpoints can remain decoupled.

## Intent

Isolate producers and consumers from each other’s data models by **translating** a message’s payload (and often headers/metadata) from one representation to another—e.g., JSON ↔ XML, v1 ↔ v2 schema, external DTO ↔ domain model—while preserving meaning.

## Also Known As

-   Transformer
    
-   Data Mapper
    
-   Canonical ↔ Anti-Corruption Translator (DDD)
    
-   Adapter (for messages)
    

## Motivation (Forces)

-   **Heterogeneity:** Different teams, vendors, and legacy systems speak different formats and schemas.
    
-   **Evolution:** Schemas change (version bumps, renamed fields, split/merged structures).
    
-   **Boundary protection:** Keep domain model clean; prevent leaky abstractions and vendor lock-in.
    
-   **Compliance:** Redact/transform PII, standardize units, normalize enumerations.
    

**Tensions**

-   Fidelity vs. simplicity (lossy vs. lossless transforms).
    
-   Performance vs. flexibility (code vs. rules/DSL).
    
-   Central translators vs. many local mappers (governance, reuse).
    

## Applicability

Use a Message Translator when:

-   Producers and consumers **disagree on structure, types, units, or vocabulary**.
    
-   You migrate from **legacy** formats or operate with **canonical data models**.
    
-   You must **version** message contracts and keep older clients working.
    
-   You need **policy transforms** (masking, enrichment, normalization) at the boundary.
    

Avoid or limit when:

-   Both sides already share a stable schema/contract and a direct pass-through suffices.
    
-   Transformation is so heavy that it belongs in an **ETL/stream processor** instead.
    

## Structure

```pgsql
+------------------+      +--------------------+
Msg A -> Message Translator -> Msg B (new schema/format)
       |  - header map    |      | payload transformed|
       |  - payload map   |      | units normalized   |
       +------------------+      +--------------------+
```

## Participants

-   **Source Message:** Original payload + headers.
    
-   **Translator:** Component implementing mapping logic (code, XSLT, Jolt, rules).
    
-   **Target Message:** New payload/headers; optionally enriched/redacted.
    
-   **Schema Registry (optional):** Guides versioned mapping.
    
-   **Lookup/Enrichment Services (optional):** Code tables, unit converters.
    

## Collaboration

1.  Endpoint receives a source message.
    
2.  Translator validates and maps headers/payload, optionally consulting code tables or services.
    
3.  Translator emits a target message to the next channel/handler.
    
4.  Errors are mapped to **retriable** vs. **fatal** outcomes; invalid messages may go to DLQ with diagnostics.
    

## Consequences

**Benefits**

-   Decouples teams and systems; enables independent schema evolution.
    
-   Keeps domain model clean (anti-corruption at boundaries).
    
-   Central point for **normalization** (units, enums), **masking**, and **policy**.
    

**Liabilities**

-   Adds latency and CPU; can become a hotspot.
    
-   Mapping drift if not governed; duplicated translators across services.
    
-   Complex transforms are harder to test and observe; risk of silent data loss.
    

## Implementation

-   **Styles:**
    
    -   **Code mappers (Java/MapStruct):** fast, type-safe, great for DTO↔domain.
        
    -   **Declarative DSLs:** XSLT (XML), Jolt/JMESPath (JSON), jq; flexible but slower.
        
    -   **Streaming transforms:** Jackson streaming, Kafka Streams/Flink map functions for high throughput.
        
-   **Versioning:** Embed `eventType` + `eventVersion` in headers; keep **backward-compatible** changes where possible; for breaking changes, publish to `*.v2` and supply **v1→v2** translators.
    
-   **Semantics:** Normalize **units** (e.g., cents↔EUR), **timezones** (UTC ISO-8601), **enums** (external codes → internal enums).
    
-   **Safety:** Validate inputs; fail fast with clear diagnostics. Perform **PII masking**/tokenization if required.
    
-   **Observability:** Count translations, failures, per-rule hit rates; sample transformed payloads with redaction.
    
-   **Placement:** Usually inside **Message Endpoint** or a dedicated **translation microservice**; keep pure and side-effect-free.
    

---

## Sample Code (Java)

### A) Pure Java + MapStruct — External DTO → Canonical Event (lossless, type-safe)

```java
// build.gradle: implementation 'org.mapstruct:mapstruct:1.5.5.Final', annotationProcessor 'org.mapstruct:mapstruct-processor:1.5.5.Final'
// Plus Jackson for (de)serialization if needed.

public record ExtOrderCreatedV1(
    String id,            // external order id
    String sku,
    int quantity,
    String region,        // "EU" | "US" | ...
    long amountCents,     // money in cents
    String occurredAtUtc  // ISO-8601 string
) {}

public record CanonicalOrderCreatedV2(
    String orderId,
    String sku,
    int qty,
    String region,        // normalized uppercase
    java.math.BigDecimal amount,  // EUR
    java.time.Instant occurredAt, // Instant
    String currency       // "EUR"
) {}

@org.mapstruct.Mapper(imports = {java.math.BigDecimal.class, java.time.Instant.class})
public interface OrderTranslator {

  @org.mapstruct.Mapping(target = "orderId", source = "id")
  @org.mapstruct.Mapping(target = "qty", source = "quantity")
  @org.mapstruct.Mapping(target = "amount",
      expression = "java(new BigDecimal(src.amountCents()).movePointLeft(2))")
  @org.mapstruct.Mapping(target = "occurredAt",
      expression = "java(Instant.parse(src.occurredAtUtc()))")
  @org.mapstruct.Mapping(target = "currency", constant = "EUR")
  @org.mapstruct.Mapping(target = "region",
      expression = "java(src.region() == null ? null : src.region().toUpperCase())")
  CanonicalOrderCreatedV2 toCanonical(ExtOrderCreatedV1 src);

  // Inverse example (if you need it):
  @org.mapstruct.InheritInverseConfiguration
  ExtOrderCreatedV1 fromCanonical(CanonicalOrderCreatedV2 tgt);
}
```

### B) Spring Integration Transformer — JSON→JSON with Header & Schema Version Mapping

```java
// build.gradle: spring-boot-starter-integration, jackson-databind
@Configuration
@EnableIntegration
public class TranslationFlow {

  @Bean
  public IntegrationFlow translateOrder() {
    return IntegrationFlows.from("orders.v1.in")
      .enrichHeaders(h -> h
          .header("eventType", "orders.order.created")
          .header("eventVersion", "v2"))
      .transform(Transformers.converter(this::v1JsonToV2Json)) // payload transform
      .channel("orders.v2.out")
      .get();
  }

  private org.springframework.messaging.Message<?> v1JsonToV2Json(org.springframework.messaging.Message<?> msg) {
    try {
      ObjectMapper m = new ObjectMapper();
      ExtOrderCreatedV1 v1 = m.readValue((byte[]) msg.getPayload(), ExtOrderCreatedV1.class);

      CanonicalOrderCreatedV2 v2 = Mappers.getMapper(OrderTranslator.class).toCanonical(v1);

      byte[] out = m.writeValueAsBytes(v2);
      return org.springframework.messaging.support.MessageBuilder.withPayload(out)
          .copyHeaders(msg.getHeaders())
          .setHeader("contentType", "application/json")
          .build();
    } catch (Exception e) {
      throw new IllegalStateException("translation failed", e);
    }
  }
}
```

### C) Apache Camel — Content Enrichment + Field Mapping (JSON)

```java
// build.gradle: camel-core, camel-jackson
public class TranslationRoutes extends org.apache.camel.builder.RouteBuilder {
  @Override
  public void configure() {
    from("kafka:orders.created.v1?groupId=translator")
      .routeId("orders-v1-to-v2")
      .unmarshal().json(org.apache.camel.model.dataformat.JsonLibrary.Jackson, ExtOrderCreatedV1.class)
      .process(e -> {
        ExtOrderCreatedV1 v1 = e.getIn().getBody(ExtOrderCreatedV1.class);
        OrderTranslator mapper = org.mapstruct.factory.Mappers.getMapper(OrderTranslator.class);
        CanonicalOrderCreatedV2 v2 = mapper.toCanonical(v1);
        e.getIn().setBody(v2);
        e.getIn().setHeader("eventType", "orders.order.created");
        e.getIn().setHeader("eventVersion", "v2");
      })
      .marshal().json(org.apache.camel.model.dataformat.JsonLibrary.Jackson)
      .to("kafka:orders.created.v2");
  }
}
```

### D) Kafka Streams — High-Throughput Map (Stateless Transform)

```java
// build.gradle: kafka-streams, jackson-databind, mapstruct at build time for DTOs
public class StreamsTranslatorApp {
  public static void main(String[] args) {
    var props = new java.util.Properties();
    props.put(org.apache.kafka.streams.StreamsConfig.APPLICATION_ID_CONFIG, "orders-v1-to-v2");
    props.put(org.apache.kafka.streams.StreamsConfig.BOOTSTRAP_SERVERS_CONFIG, "localhost:9092");

    var builder = new org.apache.kafka.streams.StreamsBuilder();
    var serdeV1 = JsonSerdes.serdeFor(ExtOrderCreatedV1.class);
    var serdeV2 = JsonSerdes.serdeFor(CanonicalOrderCreatedV2.class);

    var stream = builder.stream("orders.created.v1",
        org.apache.kafka.streams.Consumed.with(org.apache.kafka.common.serialization.Serdes.String(), serdeV1));

    OrderTranslator mapper = org.mapstruct.factory.Mappers.getMapper(OrderTranslator.class);

    stream.mapValues(mapper::toCanonical)
          .to("orders.created.v2",
             org.apache.kafka.streams.kstream.Produced.with(org.apache.kafka.common.serialization.Serdes.String(), serdeV2));

    new org.apache.kafka.streams.KafkaStreams(builder.build(), props).start();
  }
}
```

### E) Validation & Error Mapping (robust boundary)

```java
public final class TranslationValidator {
  public static void validate(ExtOrderCreatedV1 v1) {
    if (v1.id() == null || v1.id().isBlank()) throw new BadMessage("id missing");
    if (v1.quantity() <= 0) throw new BadMessage("quantity must be > 0");
    if (v1.amountCents() < 0) throw new BadMessage("amountCents must be >= 0");
  }
  public static class BadMessage extends RuntimeException { public BadMessage(String m){ super(m);} }
}
```

---

## Known Uses

-   **Spring Integration / Camel** transformers bridging XML/JSON/Avro across services and partners.
    
-   **API edge**: HTTP → canonical message; canonical → vendor API payloads.
    
-   **Event versioning**: publishing `*.v2` while still accepting `*.v1` through translators.
    
-   **Payments/logistics**: normalizing currency, weight/measure units, and country codes.
    
-   **Data protection**: masking/redacting PII at egress/ingress via translators.
    

## Related Patterns

-   **Canonical Data Model:** A shared schema that translators map to/from.
    
-   **Messaging Gateway / Channel Adapter:** Edges where translation commonly lives.
    
-   **Content Enricher / Filter:** Often applied with translation (add or drop fields).
    
-   **Anti-Corruption Layer (DDD):** Strategic placement of translators to shield the domain.
    
-   **Schema Registry / Message Validator:** Governs versions and compatibility.
    
-   **Message Router:** Route by version/type before applying the appropriate translator.

