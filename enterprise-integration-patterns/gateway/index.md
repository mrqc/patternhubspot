# Gateway — Enterprise Integration Pattern

## Pattern Name and Classification

**Name:** Gateway (Messaging Gateway)  
**Classification:** Endpoint pattern in Enterprise Integration Patterns (EIP); a specialized form of **Channel Adapter** that exposes a messaging system as a method-invocation style API (or vice versa).

## Intent

Encapsulate the messaging infrastructure behind a simple interface so that clients can call methods (or send HTTP/JMS/AMQP requests) without knowing about channels, envelopes, correlation, or transport details. A gateway translates between request/response method calls and asynchronous message exchanges.

## Also Known As

-   Messaging Gateway
    
-   Service Gateway
    
-   API Gateway (conceptually related but broader in scope at microservice edge)
    
-   Facade for Messaging
    

## Motivation (Forces)

-   **Simplicity for callers:** Business code should not depend on messaging APIs or wire formats.
    
-   **Transport independence:** Replace JMS with AMQP, HTTP with gRPC, etc., without changing callers.
    
-   **Consistent policy enforcement:** Centralize auth, throttling, timeouts, retries, circuit breaking, observation, and mapping.
    
-   **Protocol bridging:** Method calls ↔ messages; HTTP ↔ AMQP; sync ↔ async.
    
-   **Testability:** Mock the gateway interface in unit tests; integration tests verify messaging flows separately.
    

## Applicability

Use a Gateway when:

-   You want to provide **method-like** access to a messaging system.
    
-   Multiple clients must call a remote capability but **must not** know about channels, message headers, serialization, or correlation IDs.
    
-   You need **consistent cross-cutting concerns** at the integration boundary (security, validation, rate limits).
    
-   You are **straddling sync and async** interaction styles (e.g., request–reply over a message bus, or fire-and-forget with acknowledgments).
    
-   You need a **stable façade** while back-end transports evolve.
    

## Structure

-   **Client** invokes methods on the **Gateway Interface**.
    
-   **Gateway Implementation** maps calls to **Message** objects (payload + headers), sends to a **Request Channel**, optionally awaits a reply via a **Reply Channel** (correlated).
    
-   **Messaging Infrastructure** routes to **Endpoint(s)** (Service Activator, Handler).
    
-   **Reply** (if any) is transformed back to a return type or exception.
    

```rust
Client -> Gateway (method call)
       -> (translate) Message -> Request Channel -> Handler(s)
                                           |
                                      (process)
                                           v
                                 Reply Channel (correlated)
                             -> Gateway (translate)
                             -> Client (return/exception)
```

## Participants

-   **Gateway Interface:** Typed API for callers.
    
-   **Gateway Implementation:** Encodes/decodes payloads, headers, correlation; applies policies.
    
-   **Channels:** Request and (optional) reply channels.
    
-   **Endpoint/Handler:** Actual service/processor.
    
-   **Message Translators/Validators:** Optional mappers.
    
-   **Policy Modules:** Retry, timeout, circuit breaker, auth, metrics, tracing.
    

## Collaboration

1.  Client calls a method on the Gateway.
    
2.  Gateway builds a message (payload + headers), sets correlation and reply expectations.
    
3.  Message is sent to the Request Channel; infrastructure routes to a handler.
    
4.  Handler processes and (optionally) returns a reply.
    
5.  Gateway correlates reply and returns a typed result or raises an error.
    

## Consequences

**Pros**

-   Decouples business code from messaging APIs and protocols.
    
-   Enables transparent transport and policy changes.
    
-   Improves testability and boundary control.
    
-   Central place for observability (metrics, tracing), security, and governance.
    

**Cons**

-   Another abstraction to maintain; can hide important back-pressure or latency concerns.
    
-   If misused, can turn inherently asynchronous flows into blocking calls and reduce throughput.
    
-   Incorrect timeout/retry configuration can amplify failures (retry storms).
    
-   Over-broad gateways can become “god façades”; keep them cohesive.
    

## Implementation

-   **Define a narrow, cohesive interface.** Separate commands from queries if latency/SLAs differ.
    
-   **Map types explicitly.** Use DTOs and translators; avoid leaking internal models.
    
-   **Correlation & reply:** For request–reply, set correlation IDs and reply channels; for fire-and-forget, expose async return types (`CompletionStage`, Reactor `Mono/Flux`).
    
-   **Policies:** Apply timeouts, retries with jitter, circuit breakers, rate limits.
    
-   **Error semantics:** Map transport and app errors to typed exceptions or error results.
    
-   **Observability:** Emit metrics (success, latency, error), logs with correlation IDs, and distributed traces.
    
-   **Idempotency:** For retried operations, design idempotent handlers or use deduplication keys.
    
-   **Back-pressure:** Prefer async APIs; surface queue-depth or “busy” signals.
    
-   **Configuration:** Externalize destinations, marshalling, and credentials.
    
-   **Security:** Authenticate/authorize at the gateway; sign/verify messages where appropriate.
    

## Sample Code (Java)

### 1) Pure Java Gateway Interface (sync and async)

```java
public interface OrderGateway {
    // Request-Reply (synchronous)
    OrderConfirmation placeOrder(PlaceOrderCommand cmd) throws OrderException;

    // Fire-and-forget
    void submitOrderAsync(PlaceOrderCommand cmd);

    // Async with completion
    java.util.concurrent.CompletableFuture<OrderConfirmation> placeOrderAsync(PlaceOrderCommand cmd);
}

public record PlaceOrderCommand(String orderId, String sku, int quantity) {}
public record OrderConfirmation(String orderId, String status) {}
```

### 2) Spring Integration: @MessagingGateway over AMQP (Request–Reply)

```java
import org.springframework.integration.annotation.MessagingGateway;
import org.springframework.integration.annotation.Gateway;
import org.springframework.messaging.handler.annotation.Header;
import java.util.concurrent.CompletableFuture;

@MessagingGateway
public interface OrderGatewaySi {

    @Gateway(requestChannel = "orders.request",
             replyChannel   = "orders.reply",
             headers = @GatewayHeader(name = "x-command", expression = "'PlaceOrder'"),
             requestTimeout = 3000, replyTimeout = 5000)
    OrderConfirmation placeOrder(PlaceOrderCommand cmd);

    @Gateway(requestChannel = "orders.fireAndForget")
    void submitOrderAsync(PlaceOrderCommand cmd);

    @Gateway(requestChannel = "orders.requestAsync", replyChannel = "orders.reply")
    CompletableFuture<OrderConfirmation> placeOrderAsync(PlaceOrderCommand cmd);
}
```

```java
// Integration flow configuration (Java DSL)
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.integration.amqp.dsl.Amqp;
import org.springframework.integration.dsl.IntegrationFlow;
import org.springframework.integration.dsl.IntegrationFlows;

@Configuration
class IntegrationConfig {

    @Bean
    IntegrationFlow ordersRequestFlow(org.springframework.amqp.rabbit.core.RabbitTemplate rabbit) {
        return IntegrationFlows
            .from("orders.request")
            .transform(p -> serialize(p)) // e.g., JSON
            .handle(Amqp.outboundGateway(rabbit)
                    .routingKey("orders.place")
                    .exchangeName("orders-exchange")
                    .mappedRequestHeaders("*")
                    .replyTimeout(5000))
            .transform(m -> deserialize((byte[]) m))
            .channel("orders.reply")
            .get();
    }

    @Bean
    IntegrationFlow fireAndForgetFlow(org.springframework.amqp.rabbit.core.RabbitTemplate rabbit) {
        return IntegrationFlows
            .from("orders.fireAndForget")
            .transform(p -> serialize(p))
            .handle(Amqp.outboundAdapter(rabbit)
                    .routingKey("orders.submit")
                    .exchangeName("orders-exchange"))
            .get();
    }

    private byte[] serialize(Object o) {
        // use your favorite JSON mapper
        return toJsonBytes(o);
    }
    private Object deserialize(byte[] bytes) {
        return fromJsonBytes(bytes, OrderConfirmation.class);
    }
}
```

### 3) Resilient HTTP Gateway with Circuit Breaker (Spring WebClient + Resilience4j)

```java
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import io.github.resilience4j.timelimiter.annotation.TimeLimiter;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import java.time.Duration;
import java.util.concurrent.CompletableFuture;

@Component
public class HttpOrderGateway implements OrderGateway {

    private final WebClient client = WebClient.builder()
        .baseUrl("https://orders.example.com/api")
        .build();

    @Override
    @CircuitBreaker(name = "orders", fallbackMethod = "fallbackConfirm")
    public OrderConfirmation placeOrder(PlaceOrderCommand cmd) {
        return client.post()
            .uri("/orders")
            .bodyValue(cmd)
            .retrieve()
            .bodyToMono(OrderConfirmation.class)
            .timeout(Duration.ofSeconds(5))
            .block();
    }

    @Override
    public void submitOrderAsync(PlaceOrderCommand cmd) {
        client.post().uri("/orders/async").bodyValue(cmd).retrieve().toBodilessEntity().subscribe();
    }

    @Override
    @TimeLimiter(name = "orders")
    @CircuitBreaker(name = "orders", fallbackMethod = "fallbackConfirmAsync")
    public CompletableFuture<OrderConfirmation> placeOrderAsync(PlaceOrderCommand cmd) {
        return client.post()
            .uri("/orders")
            .bodyValue(cmd)
            .retrieve()
            .bodyToMono(OrderConfirmation.class)
            .timeout(Duration.ofSeconds(5))
            .toFuture();
    }

    private OrderConfirmation fallbackConfirm(PlaceOrderCommand cmd, Throwable t) {
        // map to a safe default or raise domain exception
        return new OrderConfirmation(cmd.orderId(), "PENDING");
    }

    private CompletableFuture<OrderConfirmation> fallbackConfirmAsync(PlaceOrderCommand cmd, Throwable t) {
        return CompletableFuture.completedFuture(new OrderConfirmation(cmd.orderId(), "PENDING"));
    }
}
```

### 4) Error Mapping Example

```java
public class OrderException extends RuntimeException {
    private final String code;
    public OrderException(String code, String message, Throwable cause) {
        super(message, cause);
        this.code = code;
    }
    public String code() { return code; }
}
```

## Known Uses

-   **Spring Integration** `@MessagingGateway` and gateway endpoints for JMS/AMQP/HTTP.
    
-   **Apache Camel** `direct:`/`seda:` endpoints with bean proxies and Rest DSL acting as gateways.
    
-   **Netflix/Resilience4j patterns** at service edges (timeouts, circuit breakers) behind typed client interfaces.
    
-   **Cloud API edges** (Kong, Apigee, AWS API Gateway) conceptually serve as macro-gateways—though at a different architectural level.
    

## Related Patterns

-   **Channel Adapter:** Gateway is a specialized, typed adapter for method-style access.
    
-   **Service Activator:** The mirror on the service side processing incoming messages.
    
-   **Request–Reply / Correlation Identifier:** Often used to realize synchronous semantics.
    
-   **Message Translator:** For payload/header mapping.
    
-   **Anti-Corruption Layer (DDD):** A Gateway frequently participates in an ACL to isolate models.
    
-   **API Gateway (Microservices):** Edge gateway across many services; the EIP Gateway can live behind it.
    
-   **Content Enricher / Filter:** Often applied inside gateway flows for policy or compliance.

