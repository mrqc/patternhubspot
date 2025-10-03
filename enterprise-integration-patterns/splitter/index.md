# Splitter — Enterprise Integration Pattern

## Pattern Name and Classification

**Name:** Splitter  
**Classification:** Message transformation/routing pattern (EIP); decomposes a **composite message** into **multiple smaller messages** for independent processing.

## Intent

Take a message that contains a **collection** (array, list, batch, file, multipart, composite object) and **split** it into **one message per element** (or logical part), preserving correlation so downstream consumers can process items independently and (optionally) be **re-aggregated** later.

## Also Known As

-   Message Splitter
    
-   Decomposer
    
-   Batch Exploder
    
-   File Splitter (specialization)
    

## Motivation (Forces)

-   Producers often send **batches** for efficiency (database dumps, CSV files, arrays of orders).
    
-   Downstream services typically expect **single-entity** messages for simpler logic, back-pressure, scaling, and idempotency.
    
-   Splitting enables **parallelism** and **selective routing** per item, and supports **partial failure** handling.
    

**Tensions**

-   Throughput from batching vs. granularity of single-item processing.
    
-   Preserving **order** and **correlation** across split items.
    
-   Handling **partial successes** and late failures.
    

## Applicability

Use a Splitter when:

-   The payload is a **collection** (list/array/stream), **bulk file**, **multipart**, or a **composite DTO** containing many parts.
    
-   You want to **fan-out** items to different handlers (with Router/Filter) or **parallelize** processing.
    
-   You need **fine-grained retries/DLQ** per element instead of failing the entire batch.
    

Avoid or limit when:

-   Atomicity is required for the whole batch (all-or-nothing).
    
-   Elements are **not independent** (hard ordering constraints or global invariants).
    

## Structure

```rust
+-------------------+
Composite --> |     Splitter      | --> item #1 --> ...
  Message     |  (iterate/parse)  | --> item #2 --> ...
              +-------------------+ --> item #n --> ...
                     | preserve correlationId / sequence
```

## Participants

-   **Splitter:** Component that parses/iterates the composite payload and emits individual messages.
    
-   **Correlation/Sequence Metadata:** `correlationId`, `sequenceId`, `sequenceNumber`, total size (optional).
    
-   **Downstream Handlers:** Services that process each item independently.
    
-   **Aggregator (optional):** Recombines after processing (e.g., results list, success/failure summary).
    
-   **Message Store (optional):** Persists state for recovery and re-aggregation.
    

## Collaboration

1.  A composite message arrives at the Splitter.
    
2.  Splitter iterates elements, emitting one message per element, copying **headers** and setting correlation/sequence.
    
3.  Items flow through routers/filters/handlers, possibly in parallel.
    
4.  Optionally, an **Aggregator** collects results keyed by correlation until complete or timeout.
    

## Consequences

**Benefits**

-   Enables **parallelism**, **selective routing**, and **per-item retries/DLQ**.
    
-   Simplifies downstream logic to **single-item** handlers.
    
-   Improves **fault isolation**—bad items don’t poison the whole batch.
    

**Liabilities**

-   More messages → potential **overhead** on broker and consumers.
    
-   Requires **correlation** & **ordering** management if re-aggregation is needed.
    
-   Large splits can cause **memory pressure**; streaming splitters help.
    
-   Partial completion semantics must be defined (how to report “some failed”).
    

## Implementation

-   **Input forms:** in-memory collections, delimited files (CSV), JSON arrays, XML lists, multipart messages, large streams.
    
-   **Metadata:** set `correlationId` (usually original message ID), `sequenceNumber`, optional `sequenceSize`.
    
-   **Streaming vs. materialized:** prefer **streaming** reading for big files (line-by-line, chunked) to avoid OOM.
    
-   **Back-pressure:** limit concurrency, chunk size, or use **windowed splitting**.
    
-   **Idempotency:** include stable per-item keys; dedupe downstream.
    
-   **Error handling:** per-item retries and DLQ; aggregate a **result report** if needed.
    
-   **Security/PII:** redact sensitive fields at split time if downstream doesn’t need them.
    
-   **Observability:** counters for items emitted, failures, lag; propagate `traceparent`.
    

---

## Sample Code (Java)

### A) Spring Integration — Split JSON array into items, process, then optionally aggregate

```java
// build.gradle: spring-boot-starter-integration, jackson-databind
@Configuration
@EnableIntegration
public class SplitterFlow {

  @Bean public MessageChannel in() { return new DirectChannel(); }
  @Bean public MessageChannel items() { return new ExecutorChannel(Executors.newFixedThreadPool(8)); }
  @Bean public MessageChannel results() { return new DirectChannel(); }

  @Bean
  public IntegrationFlow splitProcessAggregate(ObjectMapper mapper, ItemHandler handler) {
    return IntegrationFlows.from("in")
      // payload: byte[] or String of JSON array [ {...}, {...} ]
      .enrichHeaders(h -> h.headerFunction("correlationId",
            m -> m.getHeaders().getId().toString()))
      .split(jsonArraySplitter(mapper), s -> s.applySequence(true).outputProcessor(m -> m)) // set sequence headers
      .channel("items")
      .handle((Message<?> m) -> {
        Item item = toItem(mapper, m.getPayload());
        Result r = handler.process(item);            // domain logic per item
        return MessageBuilder.withPayload(r)
            .copyHeaders(m.getHeaders()).build();
      })
      // Optional: aggregate results back into a list (wait for all or timeout)
      .aggregate(a -> a
        .correlationExpression("headers['correlationId']")
        .releaseStrategy(g -> g.getMessages().size() == (Integer) g.getOne().getHeaders()
            .getOrDefault(IntegrationMessageHeaderAccessor.SEQUENCE_SIZE, -1))
        .groupTimeout(2000) // fallback deadline
        .outputProcessor(g -> g.getMessages().stream().map(Message::getPayload).toList())
        .expireGroupsUponCompletion(true))
      .channel("results")
      .get();
  }

  private org.springframework.integration.splitter.AbstractMessageSplitter jsonArraySplitter(ObjectMapper mapper) {
    return new org.springframework.integration.splitter.AbstractMessageSplitter() {
      @Override
      protected Object splitMessage(Message<?> message) {
        try {
          JsonNode root = mapper.readTree((byte[]) message.getPayload());
          java.util.List<byte[]> parts = new java.util.ArrayList<>();
          for (JsonNode n : root) parts.add(mapper.writeValueAsBytes(n));
          return parts;
        } catch (Exception e) { throw new IllegalArgumentException("bad json", e); }
      }
    };
  }

  private Item toItem(ObjectMapper m, Object p) {
    try {
      if (p instanceof byte[] b) return m.readValue(b, Item.class);
      if (p instanceof String s)  return m.readValue(s, Item.class);
      return (Item) p;
    } catch (Exception e) { throw new RuntimeException(e); }
  }

  public record Item(String id, String sku, int qty) {}
  public record Result(String id, boolean ok, String note) {}

  @Component
  public static class ItemHandler {
    public Result process(Item i) { return new Result(i.id(), true, "processed"); }
  }
}
```

### B) Apache Camel — Split file lines, parallel process, aggregate failures

```java
// build.gradle: camel-core, camel-file, camel-jackson
public class SplitterRoutes extends org.apache.camel.builder.RouteBuilder {
  @Override
  public void configure() {
    errorHandler(deadLetterChannel("kafka:orders.items.DLQ").maximumRedeliveries(3).redeliveryDelay(500));

    from("file:inbox?fileName=orders.csv&noop=true")
      .routeId("csv-splitter")
      // Split by lines (skip header), parallel process with streaming to avoid loading whole file
      .split(body().tokenize("\n")).streaming().parallelProcessing().stopOnException()
        .filter(simple("${body} regex '^[^#].*'")) // skip comments
        .process(e -> {
          String[] cols = e.getIn().getBody(String.class).split(",");
          Item item = new Item(cols[0], cols[1], Integer.parseInt(cols[2]));
          e.getIn().setBody(item);
        })
        .to("bean:itemService?method=handle")
      .end()
      .to("log:done");
  }

  public static class ItemService {
    public Result handle(Item i) { return new Result(i.id(), true, "ok"); }
  }
  public record Item(String id, String sku, int qty) {}
  public record Result(String id, boolean ok, String note) {}
}
```

### C) Kafka Streams — Split a JSON array event into individual item events (flatMap)

```java
// build.gradle: kafka-streams, jackson-databind
public class StreamsSplitterApp {
  public static void main(String[] args) {
    var props = new java.util.Properties();
    props.put(org.apache.kafka.streams.StreamsConfig.APPLICATION_ID_CONFIG, "orders-splitter");
    props.put(org.apache.kafka.streams.StreamsConfig.BOOTSTRAP_SERVERS_CONFIG, "localhost:9092");

    var builder = new org.apache.kafka.streams.StreamsBuilder();
    var in = builder.stream("orders.batch.v1",
        org.apache.kafka.streams.Consumed.with(org.apache.kafka.common.serialization.Serdes.String(),
            JsonSerdes.serdeFor(Batch.class)));
    var outSerde = JsonSerdes.serdeFor(Item.class);

    in.flatMap((key, batch) -> {
        java.util.List<org.apache.kafka.streams.KeyValue<String, Item>> out = new java.util.ArrayList<>();
        String corr = java.util.UUID.randomUUID().toString();
        int i = 1, size = batch.items.size();
        for (Item it : batch.items) {
          it.correlationId = corr; it.seq = i++; it.total = size;
          out.add(org.apache.kafka.streams.KeyValue.pair(it.id, it));
        }
        return out;
      })
      .to("orders.item.v1", org.apache.kafka.streams.kstream.Produced.with(
          org.apache.kafka.common.serialization.Serdes.String(), outSerde));

    new org.apache.kafka.streams.KafkaStreams(builder.build(), props).start();
  }

  static final class Batch { public java.util.List<Item> items; }
  static final class Item { public String id, sku; public int qty; public String correlationId; public int seq, total; }

  static final class JsonSerdes {
    static <T> org.apache.kafka.common.serialization.Serde<T> serdeFor(Class<T> cls) {
      var m = new com.fasterxml.jackson.databind.ObjectMapper();
      var s = new org.apache.kafka.common.serialization.Serializer<T>() {
        public byte[] serialize(String t, T o){ try { return m.writeValueAsBytes(o);} catch(Exception e){ throw new RuntimeException(e);} }
      };
      var d = new org.apache.kafka.common.serialization.Deserializer<T>() {
        public T deserialize(String t, byte[] b){ try { return m.readValue(b, cls);} catch(Exception e){ throw new RuntimeException(e);} }
      };
      return org.apache.kafka.common.serialization.Serdes.serdeFrom(s, d);
    }
  }
}
```

### D) Minimal Jakarta JMS — Split a JSON array and send individual messages

```java
// Maven: jakarta.jms-api, activemq-artemis-jakarta-client, jackson-databind
import jakarta.jms.*;
import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.core.type.TypeReference;
import org.apache.activemq.artemis.jms.client.ActiveMQConnectionFactory;
import java.util.*;

public class JmsSplitter {
  public static void main(String[] args) throws Exception {
    ObjectMapper json = new ObjectMapper();
    String batchJson = """
      [{"id":"I-1","sku":"A","qty":2},{"id":"I-2","sku":"B","qty":1}]
    """;
    List<Item> items = json.readValue(batchJson, new TypeReference<List<Item>>(){});
    String correlationId = UUID.randomUUID().toString();

    try (ConnectionFactory cf = new ActiveMQConnectionFactory("tcp://localhost:61616");
         Connection conn = cf.createConnection()) {
      Session s = conn.createSession(false, Session.AUTO_ACKNOWLEDGE);
      Queue out = s.createQueue("orders.item.v1");
      MessageProducer p = s.createProducer(out);

      int i = 1, total = items.size();
      for (Item it : items) {
        TextMessage m = s.createTextMessage(json.writeValueAsString(it));
        m.setStringProperty("correlationId", correlationId);
        m.setIntProperty("sequenceNumber", i++);
        m.setIntProperty("sequenceSize", total);
        p.send(m);
      }
    }
  }
  public static class Item { public String id, sku; public int qty; }
}
```

---

## Known Uses

-   **Bulk to stream**: nightly CSV/XML batches split into per-entity messages for nearline processing.
    
-   **Order ingestion**: e-commerce checkout sending an array of line items → one message per line item.
    
-   **IoT telemetry**: gateway uploads a bundle; backend splits per sensor/reading.
    
-   **Email/SMS campaigns**: a single campaign definition split into per-recipient tasks.
    
-   **ETL**: large JSON arrays split for parallel enrichment and loading.
    

## Related Patterns

-   **Aggregator:** Commonly used to **gather** results after splitting.
    
-   **Resequencer:** If order must be restored after parallel handling.
    
-   **Message Router / Recipient List:** Route split items to different destinations.
    
-   **Message Filter:** Drop unwanted elements during or after split.
    
-   **Message Store:** Persist correlation/sequence and partial results.
    
-   **Transactional Outbox / Idempotent Receiver:** Reliability when transports are at-least-once.

