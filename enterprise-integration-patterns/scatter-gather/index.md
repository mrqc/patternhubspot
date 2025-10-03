# Scatter–Gather — Enterprise Integration Pattern

## Pattern Name and Classification

**Name:** Scatter–Gather  
**Classification:** Routing & Aggregation pattern (EIP); parallel **fan-out** of a request to multiple recipients and **aggregation** of their replies into a single result.

## Intent

Send a request to **multiple endpoints concurrently**, collect the **individual responses**, and **aggregate** them (merge, choose best, vote) into one consolidated reply, with policies for **timeouts**, **quorum**, and **partial results**.

## Also Known As

-   Fan-out/Fan-in
    
-   Parallel Request–Reply
    
-   Broadcast & Aggregate
    

## Motivation (Forces)

-   Some queries benefit from **parallelization** (e.g., best price from many providers).
    
-   **Availability** and **latency** improve when you don’t rely on a single responder.
    
-   Real systems require **timeouts**, **quorum thresholds**, and **de-duplication** of late/duplicate replies.
    
-   Consumers want a simple **single response** despite distributed fan-out.
    

**Tensions**

-   Faster overall latency vs. cost of **N calls**.
    
-   **Consistency** of aggregated answer vs. **deadline**.
    
-   **Ordering** of replies is not guaranteed; aggregation must be deterministic.
    

## Applicability

Use Scatter–Gather when:

-   You query **multiple providers** of the same capability (shopping, search, pricing, recommendations).
    
-   You need **hedged requests** for resilience (send to several replicas, pick the first “good” one).
    
-   You rely on **partitioned data** where several shards may hold relevant results.
    
-   You orchestrate **multi-source enrichment** then combine.
    

Avoid or limit when:

-   A single authoritative service exists and extra requests only add cost.
    
-   Responses must be **globally consistent** beyond what a deadline can guarantee.
    

## Structure

```sql
+--------------------+
Request ->   Scatter Router   --+--> Endpoint A --\
         +--------------------+ |                 \
                                 +--> Endpoint B ---->  +-----------------+
                                 |                      |   Aggregator    | --> Combined Reply
                                 +--> Endpoint C --/    | (quorum/timeout |
                                                       |  merge/select)  |
                                                       +-----------------+
```

## Participants

-   **Scatter Router:** Fan-out to recipients (Recipient List, Dynamic Router, multicast).
    
-   **Recipients/Endpoints:** Services handling the sub-requests.
    
-   **Reply Channels:** Each endpoint’s response path.
    
-   **Aggregator:** Correlates replies (by correlation id), applies **completion** and **aggregation** strategies.
    
-   **Completion Strategy:** All, quorum (k of n), first-winner, deadline/time-boxed.
    
-   **Correlation Identifier:** Ties request and all replies together.
    
-   **Message Store (optional):** Persist replies until aggregation completes.
    

## Collaboration

1.  Request arrives with a **correlation id**.
    
2.  Scatter Router determines recipients and sends copies in parallel (possibly transforming per recipient).
    
3.  Endpoints process and send **replies** tagged with the same correlation id.
    
4.  Aggregator collects replies until **completion condition** is met (all/quorum/deadline).
    
5.  Aggregator **merges** replies (union, min/max, ranking, vote) and emits one combined response.
    
6.  Late replies are **discarded**, **logged**, or **used to update caches**.
    

## Consequences

**Benefits**

-   Lower **tail latency** via parallelization and hedged requests.
    
-   Increased **fault tolerance**—some endpoints may fail or be slow.
    
-   Clear **policy point** for deadlines, quorum, and result shaping.
    

**Liabilities**

-   Higher **resource cost** (more requests).
    
-   Requires careful **idempotency** and **correlation**.
    
-   Aggregation logic can grow complex (conflict resolution, weighting).
    
-   Late replies management and **result reproducibility** must be defined.
    

## Implementation

-   **Correlation:** Generate a UUID; place in headers (`correlationId`, `traceparent`).
    
-   **Completion policies:**
    
    -   **all:** wait for n replies or timeout → may return partial.
        
    -   **quorum:** return when ≥k replies (k configurable), or timeout.
        
    -   **first-good:** as soon as a reply passes validation/SLI.
        
    -   **deadline:** fixed timeout; aggregate whatever arrived.
        
-   **Aggregation strategies:**
    
    -   **Reduce:** min/max/avg (e.g., best price).
        
    -   **Merge:** union/intersection with de-dup and ordering.
        
    -   **Rank:** score replies and take top-K.
        
    -   **Vote:** majority/plurality decision.
        
-   **Resilience:** retries with jitter, circuit breakers per recipient, idempotent receivers.
    
-   **Observability:** per-recipient latency, success rate, contribution to aggregate, timeouts, fan-out size.
    
-   **Security:** per-recipient credentials; redact sensitive data before aggregation.
    
-   **Placement:** library in caller; or integration flow (Spring Integration/Camel); or stream processor.
    

---

## Sample Code (Java)

### A) Spring Integration — Scatter-Gather with deadline + “best-price” aggregator

```java
// build.gradle: spring-boot-starter-integration, spring-webflux (for HTTP), jackson
@Configuration
@EnableIntegration
public class ScatterGatherConfig {

  @Bean
  public MessageChannel inbound() { return new DirectChannel(); }

  @Bean
  public MessageChannel replies() { return new PublishSubscribeChannel(); }

  @Bean
  public IntegrationFlow scatterGatherFlow(WebClient.Builder web) {
    WebClient client = web.build();

    return IntegrationFlows.from("inbound")
      // payload: PriceQuery { sku, region }
      .enrichHeaders(h -> h.headerFunction("correlationId", m -> java.util.UUID.randomUUID().toString()))
      // SCATTER: send to three providers in parallel
      .publishSubscribeChannel(Executors.newCachedThreadPool(), s -> s
        .subscribe(f -> f.handle(Http.outboundGateway(client, m -> uri("http://p1/prices", m))
                               .httpMethod(HttpMethod.POST))
                        .channel("replies"))
        .subscribe(f -> f.handle(Http.outboundGateway(client, m -> uri("http://p2/prices", m))
                               .httpMethod(HttpMethod.POST))
                        .channel("replies"))
        .subscribe(f -> f.handle(Http.outboundGateway(client, m -> uri("http://p3/prices", m))
                               .httpMethod(HttpMethod.POST))
                        .channel("replies"))
      )
      // GATHER: aggregate until (quorum=2 OR timeout=1500ms), then choose lowest price
      .aggregate(a -> a
        .correlationExpression("headers['correlationId']")
        .releaseStrategy(group -> group.size() >= 2) // quorum 2
        .groupTimeout(1500)                           // deadline cap
        .outputProcessor(g -> {
          // Map replies to PriceQuote objects, choose min by price
          java.util.List<PriceQuote> quotes = g.getMessages().stream()
            .map(m -> (PriceQuote) m.getPayload()).toList();
          return quotes.stream().min(java.util.Comparator.comparing(PriceQuote::price)).orElse(null);
        })
        .expireGroupsUponCompletion(true)
      )
      .get();
  }

  private java.net.URI uri(String base, Message<?> m) {
    return java.net.URI.create(base);
  }

  public record PriceQuery(String sku, String region) {}
  public record PriceQuote(String provider, String sku, java.math.BigDecimal price, long latencyMs) {}
}
```

### B) Reactor (no framework) — Parallel fan-out + timeout + aggregation

```java
// build.gradle: reactor-core, reactor-netty, jackson
public class ScatterGatherReactor {

  private final reactor.netty.http.client.HttpClient http = reactor.netty.http.client.HttpClient.create();
  private final com.fasterxml.jackson.databind.ObjectMapper json = new com.fasterxml.jackson.databind.ObjectMapper();

  public Mono<BestPrice> getBestPrice(String sku, String region) {
    var q = new PriceQuery(sku, region);

    Mono<Quote> p1 = quote("http://p1/prices", q);
    Mono<Quote> p2 = quote("http://p2/prices", q);
    Mono<Quote> p3 = quote("http://p3/prices", q);

    // Take first 2 that arrive (quorum), within 1.5s, then pick the cheapest
    return Flux.mergeDelayError(3, p1, p2, p3)
      .take(2)                      // quorum
      .timeout(Duration.ofMillis(1500), Flux.empty())
      .collectList()
      .map(list -> list.stream().min(Comparator.comparing(qt -> qt.price)).orElseThrow())
      .map(qt -> new BestPrice(qt.sku, qt.price, qt.provider));
  }

  private Mono<Quote> quote(String url, PriceQuery q) {
    long start = System.nanoTime();
    return http.post()
      .uri(url)
      .send(Mono.fromCallable(() -> toBuf(q)))
      .responseSingle((res, buf) -> buf.asByteArray())
      .map(bytes -> json.readValue(bytes, Quote.class))
      .map(qt -> { qt.latencyMs = (System.nanoTime() - start) / 1_000_000; return qt; })
      .onErrorResume(ex -> Mono.empty()); // treat failure as missing reply
  }

  private io.netty.buffer.ByteBuf toBuf(Object o) throws Exception {
    return io.netty.buffer.Unpooled.wrappedBuffer(json.writeValueAsBytes(o));
  }

  // DTOs
  static final class PriceQuery { public String sku, region; PriceQuery(String s, String r){sku=s;region=r;} }
  static final class Quote { public String provider, sku; public java.math.BigDecimal price; public long latencyMs; }
  static final class BestPrice { public final String sku, provider; public final java.math.BigDecimal price;
    BestPrice(String s, java.math.BigDecimal p, String prov){sku=s;price=p;provider=prov;} }
}
```

### C) Apache Camel — scatter to dynamic recipients, aggregate with strategy

```java
// build.gradle: camel-core, camel-http, camel-jackson
public class ScatterGatherRoutes extends org.apache.camel.builder.RouteBuilder {
  @Override
  public void configure() {
    from("direct:priceRequest")
      .routeId("scatter-gather-price")
      .setHeader("correlationId").method(java.util.UUID.class, "randomUUID")
      // Scatter via Recipient List (could be loaded from config/registry)
      .setHeader("recipients").constant("http://p1/prices,http://p2/prices,http://p3/prices")
      .split().tokenizeHeader("recipients").parallelProcessing()
        .setHeader(org.apache.camel.Exchange.HTTP_METHOD, constant("POST"))
        .toD("${body}") // dynamic HTTP endpoint
      .end()
      // Gather: custom aggregator chooses min price; complete on timeout 1500ms
      .aggregate(header("correlationId"), new BestPriceAggregation())
        .completionTimeout(1500)
        .completionSize(3) // “all” if they arrive before timeout
        .to("mock:result");
  }

  static class BestPriceAggregation implements org.apache.camel.AggregationStrategy {
    @Override
    public org.apache.camel.Exchange aggregate(org.apache.camel.Exchange oldEx, org.apache.camel.Exchange newEx) {
      if (oldEx == null) return newEx;
      var mapper = new com.fasterxml.jackson.databind.ObjectMapper();
      try {
        var q1 = mapper.readValue(oldEx.getMessage().getBody(String.class), Quote.class);
        var q2 = mapper.readValue(newEx.getMessage().getBody(String.class), Quote.class);
        return (q1.price.compareTo(q2.price) <= 0) ? oldEx : newEx;
      } catch (Exception e) { return (oldEx != null) ? oldEx : newEx; }
    }
  }
  static class Quote { public String provider, sku; public java.math.BigDecimal price; }
}
```

*Notes:*

-   All examples assume responders return a `PriceQuote`/`Quote` JSON body.
    
-   Add **circuit breakers**, **retries**, and **metrics** around each recipient call.
    
-   For messaging (JMS/Kafka) responders, pair with **Request–Reply** and aggregate replies on a correlation id.
    

---

## Known Uses

-   **Metasearch/price comparison:** query multiple vendors; choose cheapest or best-score.
    
-   **Recommendations:** fan-out to different engines (collaborative, content-based) then merge/rank.
    
-   **Hedged requests:** send to multiple replicas/regions; take first “good” reply to reduce tail latency.
    
-   **Multi-source enrichment:** collect attributes from CRM, catalog, inventory to assemble a response.
    

## Related Patterns

-   **Recipient List / Publish–Subscribe Channel:** Common ways to implement the scatter phase.
    
-   **Aggregator:** The gather phase—correlation, completion conditions, and merge functions.
    
-   **Request–Reply:** Typical interaction model with each recipient.
    
-   **Content Enricher:** Individual replies can enrich the original payload before aggregation.
    
-   **Message Store:** Persist in-flight replies and aggregation state for recovery.
    
-   **Circuit Breaker / Timeout / Retry / Idempotent Receiver:** Reliability companions for each recipient and reply handling.

