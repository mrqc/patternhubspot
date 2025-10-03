# Message Filter — Enterprise Integration Pattern

## Pattern Name and Classification

**Name:** Message Filter  
**Classification:** Routing pattern (EIP); selective consumption that drops messages not matching a predicate.

## Intent

Allow a consumer to receive only the messages it is interested in by applying a **boolean predicate** to each incoming message and **discarding** those that do not satisfy the condition.

## Also Known As

-   Selective Consumer
    
-   Predicate Filter
    
-   Guard / Gate
    

## Motivation (Forces)

-   **Noise reduction:** Channels often carry mixed traffic; consumers should not process irrelevant messages.
    
-   **Cost & safety:** Avoid expensive side effects (billing, external calls) for out-of-scope messages.
    
-   **Throughput & stability:** Reduce load, contention, and failure surface by dropping early.
    
-   **Policy enforcement:** Enforce compliance/tenancy/region/business rules at the boundary.
    

**Forces to balance**

-   Predicate complexity vs. latency.
    
-   False positives/negatives vs. business correctness.
    
-   Where to place the filter (producer, broker, consumer) for optimal efficiency and governance.
    

## Applicability

Use a Message Filter when:

-   A consumer reads from a **shared channel** and only needs a subset (e.g., region, tenant, type).
    
-   You must **block** messages violating validation, auth, or policy rules.
    
-   You need **phased processing** (early cheap filter → later expensive handler).
    
-   Broker-level routing is insufficient or cannot express business-level predicates.
    

Avoid when:

-   The predicate is already enforceable by **topic/queue partitioning** or **subscription expressions**; prefer upstream routing if possible.
    
-   You require auditing of all messages regardless of relevance—then use a **wiretap** plus filter.
    

## Structure

```lua
+---------------------------+
Channel -->|  Message Filter (predicate) |--> Accepted --> Handler
           |           |                |
           |           +-- Rejected ----+--> Discard / DLQ / Side-channel
           +---------------------------+
```

## Participants

-   **Message Filter:** Component that evaluates a predicate against message headers/payload.
    
-   **Predicate:** Boolean function (e.g., `tenant == EU`, `type in {'OrderCreated'}`).
    
-   **Accepted Output:** Channel or direct handoff to the handler.
    
-   **Rejected Output:** Drop, send to DLQ, metrics-only, or alternate channel.
    
-   **Handler:** Business code that processes accepted messages.
    

## Collaboration

1.  Consumer endpoint receives a message from a channel.
    
2.  Filter evaluates the predicate using headers and/or payload.
    
3.  If **true**, pass the message to the handler or accepted channel.
    
4.  If **false**, **discard** or route to a **rejection** channel/DLQ; record metrics.
    

## Consequences

**Benefits**

-   Decouples handlers from irrelevant traffic.
    
-   Lowers latency and cost by **failing fast**.
    
-   Central, testable enforcement point for business/policy rules.
    
-   Plays well with **content-based routing** and **recipient lists**.
    

**Liabilities**

-   Dropped messages may be hard to trace if not metered/audited.
    
-   Complex predicates can increase CPU and create hidden coupling to message schema.
    
-   If misused in place of proper **topic/queue design**, can mask upstream modeling issues.
    

## Implementation

-   **Predicate source:**
    
    -   **Headers:** type, tenant, region, event version, correlation IDs.
        
    -   **Payload:** parsed fields; prefer **canonical DTOs**.
        
-   **Placement:**
    
    -   **Consumer-side:** simplest, per-service autonomy.
        
    -   **Broker-side:** some brokers support **selectors** (JMS) or **binding keys** (AMQP); prefer these when possible.
        
    -   **Stream processors:** Kafka Streams / Flink `filter()` for high-throughput pipelines.
        
-   **Behavior on rejection:** drop, DLQ with reason, side-channel for **audit/tuning**.
    
-   **Observability:** counters for accepted/rejected; sample rejected messages (rate-limited) for diagnostics.
    
-   **Safety:** validate and authenticate before filtering to avoid information leaks.
    
-   **Config:** externalize predicates (properties, feature flags) when policies change frequently.
    
-   **Testing:** unit-test predicates; contract-test against message schemas.
    

## Sample Code (Java)

### A) Spring Integration — Filter with Accept/Reject Channels

```java
// build.gradle: spring-boot-starter-integration, jackson
@Configuration
@EnableIntegration
public class FilterFlow {

  @Bean
  public MessageChannel inbound() { return new DirectChannel(); }

  @Bean
  public MessageChannel accepted() { return new DirectChannel(); }

  @Bean
  public MessageChannel rejected() { return new DirectChannel(); }

  @Bean
  public IntegrationFlow flow() {
    return IntegrationFlows.from("inbound")
      .transform(Transformers.fromJson(OrderEvent.class))
      .filter((OrderEvent evt) -> "EU".equals(evt.region()) && "OrderCreated".equals(evt.type()),
              f -> f.discardChannel("rejected"))
      .channel("accepted")
      .handle((payload, headers) -> {
        // business logic for accepted
        return null;
      })
      .get();
  }
}

public record OrderEvent(String type, String region, String orderId) {}
```

### B) Apache Camel — Filter EIP with DLQ on Reject

```java
// build.gradle: camel-core, camel-jackson, camel-kafka (or jms)
public class FilterRoutes extends RouteBuilder {
  @Override
  public void configure() {
    // send rejected messages to DLQ with reason header
    from("kafka:orders.events.v1?groupId=billing")
      .routeId("orders-filter")
      .unmarshal().json(JsonLibrary.Jackson, OrderEvent.class)
      .filter().method(OrderPredicates.class, "isRelevant")
        .to("bean:billingHandler?method=charge")
      .end()
      .filter().method(OrderPredicates.class, "isNotRelevant")
        .setHeader("rejectReason").simple("Not EU or wrong type")
        .marshal().json(JsonLibrary.Jackson)
        .to("kafka:orders.events.v1.DLQ");
  }
}

public class OrderPredicates {
  public boolean isRelevant(OrderEvent e) {
    return "OrderCreated".equals(e.type()) && "EU".equals(e.region());
  }
  public boolean isNotRelevant(OrderEvent e) { return !isRelevant(e); }
}

public record OrderEvent(String type, String region, String orderId) {}
```

### C) Spring Kafka + Predicate (Listener-level Filter)

```java
// build.gradle: spring-kafka, jackson
@Component
public class FilteredListener {
  private final ObjectMapper mapper = new ObjectMapper();

  @KafkaListener(topics = "orders.events.v1", groupId = "shipping")
  public void onMessage(ConsumerRecord<String, byte[]> rec) throws Exception {
    OrderEvent evt = mapper.readValue(rec.value(), OrderEvent.class);
    if (!"OrderCreated".equals(evt.type()) || !"EU".equals(evt.region())) {
      // discard; optionally produce to a reject topic and increment a metric
      return;
    }
    handle(evt);
  }

  private void handle(OrderEvent evt) { /* ... */ }
}

record OrderEvent(String type, String region, String orderId) {}
```

### D) Kafka Streams — High-throughput Filter Stage

```java
// build.gradle: kafka-streams, jackson
public class StreamsFilterApp {
  public static void main(String[] args) {
    Properties p = new Properties();
    p.put(StreamsConfig.APPLICATION_ID_CONFIG, "orders-filter");
    p.put(StreamsConfig.BOOTSTRAP_SERVERS_CONFIG, "localhost:9092");
    StreamsBuilder b = new StreamsBuilder();

    Serde<OrderEvent> serde = JsonSerdes.serdeFor(OrderEvent.class);

    KStream<String, OrderEvent> events = b.stream("orders.events.v1",
        Consumed.with(Serdes.String(), serde));

    events.filter((k, e) -> "OrderCreated".equals(e.type()) && "EU".equals(e.region()))
          .to("orders.events.v1.eu.created", Produced.with(Serdes.String(), serde));

    events.filter((k, e) -> !"OrderCreated".equals(e.type()) || !"EU".equals(e.region()))
          .mapValues(e -> e.withRejectReason("filtered_out"))
          .to("orders.events.v1.rejected", Produced.with(Serdes.String(), serde));

    new KafkaStreams(b.build(), p).start();
  }
}

record OrderEvent(String type, String region, String orderId) {
  OrderEvent withRejectReason(String reason) { return this; /* extend as needed */ }
}
```

### E) JMS Selector (Broker-side Header Filter)

```java
// Requires producers to set headers; filter at subscription time
Session session = connection.createSession(false, Session.AUTO_ACKNOWLEDGE);
Topic topic = session.createTopic("orders.events");
String selector = "eventType = 'OrderCreated' AND region = 'EU'";
MessageConsumer consumer = session.createConsumer(topic, selector);
```

## Known Uses

-   **Billing/Shipping** services subscribing to a shared `orders.events` topic but filtering by `type` and `region`.
    
-   **Multi-tenant** platforms filtering by `tenantId` at the consumer boundary.
    
-   **Security/compliance** layers dropping events that lack required classification headers.
    
-   **ETL/streaming** pipelines (Kafka Streams/Flink) narrowing high-volume topics before enrichment.
    

## Related Patterns

-   **Content-Based Router:** Routes messages to different channels; a filter is the degenerate case of “route-or-drop.”
    
-   **Message Router / Recipient List:** Broader routing variants; combine with filter for targeted fan-out.
    
-   **Message Translator:** Normalize payloads before applying predicates.
    
-   **Wire Tap:** Copy messages to an audit stream while filtering main flow.
    
-   **Dead Letter Channel:** Destination for rejected/poison messages.
    
-   **Idempotent Receiver:** Often paired downstream to ensure exactly-once effects after filtering.

