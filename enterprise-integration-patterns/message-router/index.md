# Message Router — Enterprise Integration Pattern

## Pattern Name and Classification

**Name:** Message Router  
**Classification:** Routing pattern (EIP); directionally forwards a message to one or more output channels based on message **content**, **headers**, or **rules**.

## Intent

Examine each incoming message and **determine the appropriate destination channel(s)** according to a routing decision function, keeping senders and receivers decoupled while centralizing the decision logic.

## Also Known As

-   Content-Based Router (specialized form)
    
-   Dynamic Router
    
-   Rules-Based Router
    
-   Header Router / Predicate Router
    

## Motivation (Forces)

-   **Decoupling:** Producers publish to a single entry point; the router hides the topology.
    
-   **Flexibility:** Add or change recipients without touching producers.
    
-   **Policy/Compliance:** Enforce tenancy/region separation, data classifications, SLAs.
    
-   **Evolution:** Support multiple versions or schema migrations by routing to v1/v2 consumers.
    

**Forces to balance**

-   Centralized logic vs. “too-smart” broker/endpoint.
    
-   Throughput/latency impact of complex predicates.
    
-   Correctness under **out-of-order events** and **partial failures**.
    

## Applicability

Use a Message Router when:

-   Multiple downstream handlers may process different **types, versions, regions, tenants**, or **service capabilities**.
    
-   You need **conditional fan-out** (one-to-one, one-to-many, first-match, best-match).
    
-   You want to **avoid topic sprawl** or publishers knowing specific destination names.
    
-   You manage **schema/version transitions** in-flight.
    

Avoid or limit when:

-   A simple **Message Filter** is enough (route-or-drop, single destination).
    
-   Broker-native bindings (e.g., AMQP topic keys) already express your routing—prefer them for performance.
    

## Structure

```mathematica
+----------------------+
Inbound Channel ->  Message Router      |--> Out Ch A
                 |  (rules/predicates)  |--> Out Ch B
                 +----------------------+--> Out Ch C ...
```

Variations:

-   **Content-Based Router:** Predicate from payload/headers.
    
-   **Recipient List:** Deterministic list → multicast.
    
-   **Dynamic Router:** Next hop determined at runtime, possibly per step.
    
-   **Slip (routing slip):** Precomputed route carried in headers.
    

## Participants

-   **Router:** Evaluates rules and forwards the original message (or a copy) to selected output channel(s).
    
-   **Rules/Predicates/DSL:** Encodes decision logic (code, table, rules engine).
    
-   **Input Channel:** Where messages arrive.
    
-   **Output Channels:** Destinations (queues/topics/streams).
    
-   **Recipients:** Downstream consumers/handlers.
    
-   **Policy/Observability:** Metrics, audit, tracing of routing decisions.
    

## Collaboration

1.  Router receives a message on the input channel.
    
2.  Router evaluates rules (headers/payload/external lookup).
    
3.  Router forwards the message to the selected output channel(s).
    
4.  Recipients process independently; errors handled per-channel (retry/DLQ).
    
5.  Metrics/logs capture which predicate matched and where the message went.
    

## Consequences

**Benefits**

-   Keeps producers simple and **agnostic** of consumer topology.
    
-   Central place to evolve routing policies and **version migrations**.
    
-   Enables conditional **fan-out** and selective processing.
    
-   Improves governance and observability at integration boundaries.
    

**Liabilities**

-   Router can become a **bottleneck** or single point of failure if not scaled.
    
-   Complex logic increases **latency** and can hide domain coupling.
    
-   Misconfiguration risks **misrouting** (silent data loss without auditing).
    
-   When routing implies transformation, responsibilities can blur with translators.
    

## Implementation

-   **Decision sources:**
    
    -   Headers: `eventType`, `tenant`, `region`, `schemaVersion`, `priority`.
        
    -   Payload fields: e.g., `order.total > 1000`, `country == "EU"`.
        
    -   External lookups: feature flags, capability registry.
        
-   **Semantics:**
    
    -   **Exclusive (first-match)** vs. **non-exclusive (multicast)**.
        
    -   **Fallback/default** channel for unmatched messages (or DLQ with reason).
        
-   **Where to route:**
    
    -   **Broker bindings** (AMQP routing keys, JMS selectors) for coarse routing.
        
    -   **Application/router service** (Spring Integration, Camel, Streams) for rich predicates.
        
-   **Reliability:** Preserve message **idempotency keys**; propagate **correlation/trace** headers.
    
-   **Performance:** Pre-compile predicates; avoid heavyweight parsing in hot path; prefer header routing when possible.
    
-   **Governance:** Route by **versioned event types** (`*.v1`, `*.v2`); log routing outcomes with counters per rule.
    
-   **Testing:** Contract-test predicates against sample messages; golden files for regression.
    

## Sample Code (Java)

### A) Spring Integration — Content-Based Router (exclusive with default)

```java
// build.gradle: spring-boot-starter-integration, jackson
@Configuration
@EnableIntegration
public class RoutingFlow {

  @Bean public MessageChannel in()       { return new DirectChannel(); }
  @Bean public MessageChannel euOut()    { return new DirectChannel(); }
  @Bean public MessageChannel usOut()    { return new DirectChannel(); }
  @Bean public MessageChannel highOut()  { return new DirectChannel(); }
  @Bean public MessageChannel defaultOut(){ return new DirectChannel(); }

  @Bean
  public IntegrationFlow route() {
    return IntegrationFlows.from("in")
      .transform(Transformers.fromJson(OrderEvent.class))
      .<OrderEvent, String>route(this::routeKey, m -> m
          .channelMapping("EU", "euOut")
          .channelMapping("US", "usOut")
          .channelMapping("HIGH", "highOut")
          .defaultOutputChannel("defaultOut"))
      .get();
  }

  private String routeKey(OrderEvent e) {
    if (e.total() >= 1000) return "HIGH";
    return switch (e.region()) {
      case "EU" -> "EU";
      case "US" -> "US";
      default -> "DEFAULT";
    };
  }
}

public record OrderEvent(String id, String region, int total, String type) {}
```

### B) Apache Camel — Content-Based Router + Recipient List (multicast)

```java
// build.gradle: camel-core, camel-jackson, camel-kafka or camel-jms
public class RouterRoutes extends RouteBuilder {
  @Override
  public void configure() {
    from("kafka:orders.events.v1?groupId=router")
      .routeId("orders-router")
      .unmarshal().json(JsonLibrary.Jackson, OrderEvent.class)
      // content-based router (exclusive)
      .choice()
        .when(simple("${body.type} == 'OrderCreated' && ${body.region} == 'EU'"))
          .to("kafka:orders.eu.created.v1")
        .when(simple("${body.type} == 'OrderCreated' && ${body.region} == 'US'"))
          .to("kafka:orders.us.created.v1")
        .otherwise()
          .to("kafka:orders.other.v1")
      .end()
      // recipient list (conditional multicast) for high-value orders
      .filter(simple("${body.total} >= 1000"))
        .setHeader("recipients").constant("kafka:fraud.v1,kafka:priority-ship.v1")
        .recipientList(header("recipients")).delimiter(",");
  }
}

public record OrderEvent(String id, String region, int total, String type) {}
```

### C) Kafka Streams — Rule-based Split (two outputs + default)

```java
// build.gradle: kafka-streams, jackson-databind
public class StreamsRouterApp {
  public static void main(String[] args) {
    Properties p = new Properties();
    p.put(StreamsConfig.APPLICATION_ID_CONFIG, "orders-router");
    p.put(StreamsConfig.BOOTSTRAP_SERVERS_CONFIG, "localhost:9092");

    StreamsBuilder b = new StreamsBuilder();
    Serde<OrderEvent> serde = JsonSerdes.serdeFor(OrderEvent.class);

    KStream<String, OrderEvent> in = b.stream("orders.events.v1",
        Consumed.with(Serdes.String(), serde));

    in.filter((k, e) -> "OrderCreated".equals(e.type()) && "EU".equals(e.region()))
      .to("orders.eu.created.v1", Produced.with(Serdes.String(), serde));

    in.filter((k, e) -> "OrderCreated".equals(e.type()) && "US".equals(e.region()))
      .to("orders.us.created.v1", Produced.with(Serdes.String(), serde));

    in.filter((k, e) -> !"OrderCreated".equals(e.type()) ||
                        (!"EU".equals(e.region()) && !"US".equals(e.region())))
      .to("orders.other.v1", Produced.with(Serdes.String(), serde));

    new KafkaStreams(b.build(), p).start();
  }
}

record OrderEvent(String id, String region, int total, String type) {}
```

### D) JMS Selectors — Header-Based Routing at Subscription Time

```java
// Producers set headers; consumers subscribe with selectors (broker routes delivery)
Session session = connection.createSession(false, Session.AUTO_ACKNOWLEDGE);
Topic topic = session.createTopic("orders.events");

String euSelector   = "type = 'OrderCreated' AND region = 'EU'";
String usSelector   = "type = 'OrderCreated' AND region = 'US'";
String otherSelector= "NOT (type = 'OrderCreated' AND (region = 'EU' OR region = 'US'))";

MessageConsumer euConsumer    = session.createConsumer(topic, euSelector);
MessageConsumer usConsumer    = session.createConsumer(topic, usSelector);
MessageConsumer otherConsumer = session.createConsumer(topic, otherSelector);
```

### E) Spring Integration — Routing Slip (dynamic route list)

```java
// Add a precomputed list of channel names into headers; router executes them in order
@Bean
public IntegrationFlow slipFlow() {
  return f -> f
    .enrichHeaders(h -> h.headerFunction("routingSlip",
        m -> List.of("validate", "transform", "publish")))
    .routeToRecipients(r -> r
        .recipientFlow("validate", sf -> sf.handle(this::validate))
        .recipientFlow("transform", sf -> sf.transform(p -> transform(p)))
        .recipientFlow("publish", sf -> sf.channel("out")));
}
```

## Known Uses

-   **AMQP/RabbitMQ** topic exchanges routing by **routing keys** (e.g., `order.eu.created`).
    
-   **ESB/Camel** routes implementing complex content-based routing and recipient lists.
    
-   **Kafka/Kafka Streams** split topics by region or event type into specialized topics for downstream services.
    
-   **Cloud services** (AWS SNS + filter policies; Azure Service Bus subscriptions with SQL filters) for header/predicate routing at the broker.
    
-   **API edge routers** bridging HTTP → bus (headers/claims drive downstream channel selection).
    

## Related Patterns

-   **Content-Based Router:** A specific form where the predicate is the content.
    
-   **Recipient List / Splitter / Aggregator:** Multicast and recomposition around routing.
    
-   **Message Filter:** Router’s degenerate case (route-or-drop).
    
-   **Publish–Subscribe Channel / Topic:** Often the physical substrate for routing.
    
-   **Message Translator / Canonical Data Model:** Normalize before routing.
    
-   **Dynamic Router / Routing Slip:** Runtime-determined next hops.
    
-   **Dead Letter Channel:** Destination for unroutable messages or rule failures.

