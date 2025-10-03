# Distributed Tracing — Microservice Pattern

## Pattern Name and Classification

-   **Name:** Distributed Tracing
    
-   **Classification:** Observability & Diagnostics Pattern for Microservices / Event-Driven Systems
    

## Intent

Correlate work that flows through multiple services into a **single end-to-end trace** so you can **see, measure, and debug** how a request or event propagates across network, processes, and queues.

## Also Known As

-   End-to-End Tracing
    
-   Cross-Service Tracing
    
-   Request Correlation
    

## Motivation (Forces)

-   **Many hops, little context:** In microservices, one user action may traverse dozens of services; logs alone become insufficient to see the **critical path**.
    
-   **Latency and errors are emergent:** Slowdowns often result from **interactions** (N+1 calls, retries, timeouts), not a single line of code.
    
-   **Heterogeneous protocols:** HTTP, gRPC, messaging, batch; you must **propagate context** across all.
    
-   **SLOs and cost:** You need concrete **service dependency graphs**, **percentiles**, and **span attributes** to tune budgets, caching, and scaling.
    
-   **Compliance & security:** Traces must avoid sensitive payloads while still being **diagnostic**.
    

## Applicability

Use when:

-   You operate **multiple services** or a mix of sync/async chains.
    
-   You need to debug **tail latency**, **timeouts**, **retries**, or **partial failures**.
    
-   You want to feed **SLO/Error Budget** processes with dependency-aware data.
    

Not essential when:

-   A small monolith with single hop execution and simple logs suffice.
    
-   You cannot propagate any cross-process identifiers due to hard regulatory constraints (rare; usually solvable with filtered attributes).
    

## Structure

Core concepts (W3C Trace Context / OpenTelemetry):

-   **Trace**: a tree/DAG of spans representing an end-to-end operation.
    
-   **Span**: timed unit of work with **name**, **attributes**, **status**, **events**, **links**.
    
-   **Span Context**: (`trace_id`, `span_id`, flags) carried via **HTTP headers** (`traceparent`, `tracestate`) or **message headers**.
    
-   **Baggage** (optional): key/value metadata that travels with the context (e.g., `tenant.id`).
    

```css
[Client] 
   └─► API Gateway (span A)
            ├─► Service A (span B)
            │      ├─► DB (span C)
            │      └─► Publish Event (span D)
            └─► Service B (span E)
                   └─► External API (span F)

Async path:  Event (trace/links) ─► Consumer (span G) ─► DB (span H)
```

## Participants

-   **Tracer/SDK**: Creates spans, manages context, exporters, sampling.
    
-   **Instrumentation**: HTTP server/client, DB drivers, messaging libraries.
    
-   **Propagation Layer**: Injects/extracts W3C headers across boundaries.
    
-   **Collector/Exporter**: Ships telemetry to **Jaeger/Zipkin/Tempo**, APM, or **OTLP** collector.
    
-   **Visualization Backend**: UI to explore traces, flame graphs, service maps.
    
-   **Sampling/Policy**: Head/tail sampling, rate/attribute sampling.
    

## Collaboration

1.  **Entry**: First hop (gateway or service) creates a **root span** unless one exists; extracts `traceparent` if the client sent it.
    
2.  **Propagation**: Downstream calls inject `traceparent`/`baggage` headers; async messages carry equivalent headers/attributes.
    
3.  **Child Spans**: Each hop creates a span for work it performs (handlers, DB calls, external requests).
    
4.  **Errors/Events**: Exceptions set span status; structured attributes capture **error.kind**, **http.status\_code**, **db.system**, etc.
    
5.  **Export**: Spans stream to a collector/exporter; backend assembles full trace and renders the **critical path**.
    
6.  **Analysis**: Teams use traces to debug, compute SLIs, and optimize dependencies.
    

## Consequences

**Benefits**

-   End-to-end visibility; **find the slow hop**.
    
-   Natural **service dependency map** and **latency breakdown**.
    
-   Works across sync and async flows with **links**.
    
-   Enables **tail-based sampling** and **SLO drill-downs**.
    

**Liabilities**

-   Operational overhead (collectors, storage, retention).
    
-   **Cost/volume** of spans; requires sane sampling and span design.
    
-   Risk of **PII** leakage if attributes are not curated.
    
-   Must ensure **context propagation everywhere** (including retries, thread pools, reactive chains).
    

## Implementation

1.  **Choose standard & backend**: Adopt **OpenTelemetry** (OTel) with **W3C Trace Context**; export via **OTLP** to Jaeger/Tempo/Zipkin/APM.
    
2.  **Bootstrap SDK once per service**: Configure **sampler**, **resource attributes** (service.name, version, env).
    
3.  **Auto-instrument first**: HTTP server/client, DB, messaging; fill gaps with **manual spans** in critical code paths.
    
4.  **Propagate across all boundaries**:
    
    -   HTTP: `traceparent`, `tracestate`, `baggage`.
        
    -   Messaging: add headers (e.g., Kafka/Rabbit), or message attributes (SQS/PubSub).
        
5.  **Async correctness**: Use **links** when processing events that logically belong to an existing trace but do not share parent/child relationship.
    
6.  **Sampling strategy**: Start with **parent-based + 1–10%** head sampling; add **tail-based** for error/slow traces if backend supports it.
    
7.  **Metadata hygiene**: Whitelist attributes; avoid payloads/PII; cap attribute/event sizes.
    
8.  **Dashboards & alerts**: Percentiles per endpoint, error spans, queue delays; **age of oldest span** for exporters/collectors.
    
9.  **Testing**: Contract tests verify presence of `traceparent` and basic span attributes in calls/messages.
    
10.  **Runtime controls**: Dynamic sampling and feature flags to modulate volume.
    

## Sample Code (Java, Spring Boot 3 + OpenTelemetry)

> Minimal, production-friendly snippets showing: SDK bootstrap, HTTP extraction/injection, manual spans, and Kafka header propagation.

### `pom.xml` (snippets)

```xml
<dependencies>
  <!-- Spring Web -->
  <dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-web</artifactId>
  </dependency>

  <!-- OpenTelemetry API + SDK -->
  <dependency>
    <groupId>io.opentelemetry</groupId>
    <artifactId>opentelemetry-api</artifactId>
    <version>1.41.0</version>
  </dependency>
  <dependency>
    <groupId>io.opentelemetry</groupId>
    <artifactId>opentelemetry-sdk</artifactId>
    <version>1.41.0</version>
  </dependency>
  <dependency>
    <groupId>io.opentelemetry</groupId>
    <artifactId>opentelemetry-exporter-otlp</artifactId>
    <version>1.41.0</version>
  </dependency>

  <!-- Optional: Spring instrumentation (auto) -->
  <dependency>
    <groupId>io.opentelemetry.instrumentation</groupId>
    <artifactId>opentelemetry-spring-boot-starter</artifactId>
    <version>2.8.0</version>
  </dependency>

  <!-- Kafka for the messaging example -->
  <dependency>
    <groupId>org.springframework.kafka</groupId>
    <artifactId>spring-kafka</artifactId>
  </dependency>
</dependencies>
```

### `application.properties`

```properties
# Service identity
otel.resource.attributes=service.name=orders-service,service.version=1.3.7,deployment.environment=prod

# OTLP exporter (collector or APM endpoint)
otel.exporter.otlp.endpoint=http://otel-collector:4317
otel.metrics.exporter=none
otel.logs.exporter=none
# Sampling (parent-based + 10%)
otel.traces.sampler=parentbased_traceidratio
otel.traces.sampler.arg=0.10
```

### OpenTelemetry SDK Bootstrap

```java
// TelemetryConfig.java
package com.example.tracing;

import io.opentelemetry.api.OpenTelemetry;
import io.opentelemetry.api.common.Attributes;
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.sdk.OpenTelemetrySdk;
import io.opentelemetry.sdk.resources.Resource;
import io.opentelemetry.sdk.trace.SdkTracerProvider;
import io.opentelemetry.sdk.trace.export.BatchSpanProcessor;
import io.opentelemetry.exporter.otlp.trace.OtlpGrpcSpanExporter;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class TelemetryConfig {

  @Bean
  public OpenTelemetry openTelemetry() {
    var exporter = OtlpGrpcSpanExporter.builder().build();
    var resource = Resource.getDefault()
        .merge(Resource.create(Attributes.builder()
           // Redundant if provided via properties; explicit here for clarity
           .put("service.name", "orders-service")
           .put("service.version", "1.3.7")
           .put("deployment.environment", "prod")
           .build()));

    var tracerProvider = SdkTracerProvider.builder()
        .setResource(resource)
        .addSpanProcessor(BatchSpanProcessor.builder(exporter).build())
        .build();

    return OpenTelemetrySdk.builder().setTracerProvider(tracerProvider).build();
  }

  @Bean
  public Tracer tracer(OpenTelemetry otel) {
    return otel.getTracer("com.example.tracing");
  }
}
```

### HTTP Context Extraction for Incoming Requests

```java
// TraceContextFilter.java
package com.example.tracing;

import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.context.Context;
import io.opentelemetry.context.propagation.TextMapGetter;
import io.opentelemetry.api.trace.SpanKind;
import io.opentelemetry.api.common.Attributes;
import io.opentelemetry.api.common.AttributeKey;
import io.opentelemetry.api.GlobalOpenTelemetry;
import jakarta.servlet.*;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.stereotype.Component;
import java.io.IOException;
import java.util.Collections;

@Component
public class TraceContextFilter implements Filter {
  private static final TextMapGetter<HttpServletRequest> GETTER = new TextMapGetter<>() {
    @Override public Iterable<String> keys(HttpServletRequest carrier) {
      return Collections.list(carrier.getHeaderNames());
    }
    @Override public String get(HttpServletRequest carrier, String key) {
      return carrier.getHeader(key);
    }
  };

  private final Tracer tracer;
  public TraceContextFilter(Tracer tracer) { this.tracer = tracer; }

  @Override
  public void doFilter(ServletRequest req, ServletResponse res, FilterChain chain)
      throws IOException, ServletException {
    HttpServletRequest http = (HttpServletRequest) req;
    var propagator = GlobalOpenTelemetry.getPropagators().getTextMapPropagator();
    Context parent = propagator.extract(Context.current(), http, GETTER);

    var span = tracer.spanBuilder(http.getMethod() + " " + http.getRequestURI())
        .setSpanKind(SpanKind.SERVER)
        .setParent(parent)
        .startSpan();

    try (var scope = span.makeCurrent()) {
      span.setAllAttributes(Attributes.of(
          AttributeKey.stringKey("http.method"), http.getMethod(),
          AttributeKey.stringKey("http.route"), http.getRequestURI()
      ));
      chain.doFilter(req, res);
    } catch (Exception e) {
      span.recordException(e);
      span.setStatus(io.opentelemetry.api.trace.StatusCode.ERROR);
      throw e;
    } finally {
      span.end();
    }
  }
}
```

### Inject Context on Outgoing HTTP Calls

```java
// TracingRestTemplateConfig.java
package com.example.tracing;

import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.api.trace.SpanKind;
import io.opentelemetry.context.Scope;
import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.context.propagation.TextMapSetter;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.http.HttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

@Component
public class TracingRestTemplateConfig {

  private static final TextMapSetter<HttpRequest> SETTER = (carrier, key, value) ->
      carrier.getHeaders().set(key, value);

  @Bean
  RestTemplate tracedRestTemplate(RestTemplateBuilder b, Tracer tracer) {
    RestTemplate rt = b.build();
    rt.getInterceptors().add((request, body, execution) -> {
      var span = tracer.spanBuilder("HTTP " + request.getMethod() + " " + request.getURI().getHost())
          .setSpanKind(SpanKind.CLIENT)
          .startSpan();
      try (Scope s = span.makeCurrent()) {
        GlobalOpenTelemetry.getPropagators().getTextMapPropagator().inject(
            io.opentelemetry.context.Context.current(), request, SETTER);
        return execution.execute(request, body);
      } catch (Exception e) {
        span.recordException(e);
        span.setStatus(io.opentelemetry.api.trace.StatusCode.ERROR);
        throw e;
      } finally {
        span.end();
      }
    });
    return rt;
  }
}
```

### Controller with Manual Child Span

```java
// OrderController.java
package com.example.tracing;

import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.api.trace.Span;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestTemplate;

@RestController
@RequestMapping("/orders")
public class OrderController {
  private final Tracer tracer;
  private final RestTemplate http;

  public OrderController(Tracer tracer, RestTemplate tracedRestTemplate) {
    this.tracer = tracer;
    this.http = tracedRestTemplate;
  }

  @GetMapping("/{id}")
  public String get(@PathVariable String id) {
    var span = tracer.spanBuilder("load-order-aggregate").startSpan();
    try (var s = span.makeCurrent()) {
      // pretend: query DB (another child span if you manually instrument)
      // external call (context auto-injected by the RestTemplate interceptor)
      http.getForEntity("http://pricing:8080/prices/" + id, String.class);
      span.setAttribute("app.order.id", id);
      return "ok";
    } finally {
      span.end();
    }
  }
}
```

### Kafka Header Propagation (Producer & Consumer)

```java
// KafkaTracing.java
package com.example.tracing;

import io.opentelemetry.api.trace.*;
import io.opentelemetry.context.Context;
import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.context.propagation.TextMapSetter;
import io.opentelemetry.context.propagation.TextMapGetter;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.header.Headers;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Component;

@Component
public class KafkaTracing {
  private static final TextMapSetter<Headers> HEADER_SETTER = (carrier, key, value) ->
      carrier.add(key, value.getBytes());
  private static final TextMapGetter<Headers> HEADER_GETTER = new TextMapGetter<>() {
    @Override public Iterable<String> keys(Headers carrier) { return carrier.toArray().length == 0 ? java.util.List.of() : java.util.Arrays.stream(carrier.toArray()).map(h->h.key()).toList(); }
    @Override public String get(Headers carrier, String key) {
      var h = carrier.lastHeader(key);
      return h == null ? null : new String(h.value());
    }
  };

  private final Tracer tracer;
  private final KafkaTemplate<String, String> kafka;

  public KafkaTracing(Tracer tracer, KafkaTemplate<String, String> kafka) {
    this.tracer = tracer; this.kafka = kafka;
  }

  public void publish(String topic, String key, String value) {
    var span = tracer.spanBuilder("kafka-produce " + topic).setSpanKind(SpanKind.PRODUCER).startSpan();
    try (var scope = span.makeCurrent()) {
      var record = new ProducerRecord<String, String>(topic, key, value);
      GlobalOpenTelemetry.getPropagators().getTextMapPropagator()
          .inject(Context.current(), record.headers(), HEADER_SETTER);
      kafka.send(record);
    } finally {
      span.end();
    }
  }

  @KafkaListener(topics = "orders.events", groupId = "orders-consumer")
  public void consume(org.apache.kafka.clients.consumer.ConsumerRecord<String, String> record) {
    var parent = GlobalOpenTelemetry.getPropagators().getTextMapPropagator()
        .extract(Context.current(), record.headers(), HEADER_GETTER);
    var span = tracer.spanBuilder("kafka-consume orders.events")
        .setParent(parent)
        .setSpanKind(SpanKind.CONSUMER)
        .startSpan();
    try (var scope = span.makeCurrent()) {
      // process message...
      span.setAttribute("messaging.kafka.offset", record.offset());
      span.setAttribute("messaging.message.key", record.key() == null ? "null" : record.key());
    } catch (Exception e) {
      span.recordException(e);
      span.setStatus(StatusCode.ERROR);
      throw e;
    } finally {
      span.end();
    }
  }
}
```

> Notes:
>
> -   In production, prefer **auto-instrumentation agents** for HTTP/DB/common libs, and use manual spans only for business-critical sections.
>
> -   For **async fan-out/fan-in**, use **span links** to associate multiple producer spans to a single consumer span.
>
> -   Configure **attribute limits** and **redaction** (e.g., via `otel.attribute.value.length.limit`).
>
> -   For tail-based sampling, route spans through a collector (e.g., OTel Collector with tail sampling processor).
>

## Known Uses

-   Cloud providers’ managed tracing (e.g., AWS X-Ray, GCP Cloud Trace) and open source stacks (Jaeger/Zipkin/Tempo) are widely adopted by organizations like **Netflix**, **Uber**, **DoorDash**, **Shopify**, and **Spotify** to analyze p99 latency, retries, and dependency health.


## Related Patterns

-   **Correlation ID / Request ID:** Basic single-ID correlation; tracing generalizes and standardizes this across hops.

-   **Log Enrichment:** Insert trace/span IDs into logs for pivoting between logs and traces.

-   **Metrics-Driven SLOs:** Traces inform where to place SLIs and set budgets.

-   **Bulkhead / Circuit Breaker / Timeout & Retry:** Traces reveal where to apply resilience patterns.

-   **Event Choreography & Saga:** Use span links to correlate multi-event business transactions.
