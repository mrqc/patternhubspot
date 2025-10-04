# Queue Based Load Leveling — Scalability Pattern

## Pattern Name and Classification

**Name:** Queue Based Load Leveling  
**Classification:** Scalability / Throughput Smoothing / Asynchrony (Workload Buffering & Back-Pressure)

---

## Intent

Insert a **durable queue** between producers and consumers to **buffer bursts**, **smooth load**, and **decouple** request rate from processing capacity so workers can run at a **controlled pace** without dropping requests or overloading downstream systems.

---

## Also Known As

-   Message Queue Buffering
    
-   Asynchronous Offloading
    
-   Producer–Consumer via Queue
    
-   Work Queue / Task Queue
    

---

## Motivation (Forces)

-   **Bursty traffic**: request spikes exceed service capacity for short periods.
    
-   **Downstream limits**: databases, payment gateways, or third-party APIs have strict quotas.
    
-   **Elasticity lag**: autoscaling takes time; a queue absorbs demand while capacity catches up.
    
-   **SLO protection**: synchronous paths must respond quickly; heavy work can be deferred.
    
-   **Resilience**: retries and redelivery can recover from transient failures.
    

Trade-offs include **eventual completion**, **out-of-order** processing (unless ordered queues), and the need for **idempotent consumers**.

---

## Applicability

Use this pattern when:

-   Tasks can be processed **asynchronously** without blocking user interactions.
    
-   You need to **throttle** or **shape** load to downstream dependencies.
    
-   Work items are **independent** and safely **retriable**.
    

Avoid or adapt when:

-   You require **strict synchronous** read-after-write behavior for the user request.
    
-   Tasks are **non-idempotent** and cannot be guarded with keys/transactions.
    
-   You need **global ordering** across all tasks (very costly at scale).
    

---

## Structure

-   **Producers**: accept user/API requests; enqueue work quickly.
    
-   **Queue/Broker**: durable buffer with visibility timeout/ack, TTL, dead-lettering.
    
-   **Consumers/Workers**: pull tasks, execute, ack/nack; concurrency is configurable.
    
-   **DLQ (Dead Letter Queue)**: captures poison messages after retry budget exhausted.
    
-   **Scheduler/Autoscaler**: scales consumers by queue depth/lag.
    
-   **Store/Side Systems**: databases, external APIs affected by the work.
    

---

## Participants

-   **Ingress/API**: transforms synchronous requests into queued tasks.
    
-   **Broker**: RabbitMQ/SQS/Kafka (with semantics appropriate to queues).
    
-   **Worker**: idempotent processor with retry/backoff and timeouts.
    
-   **Observability**: queue depth, age, processing rate, DLQ, success/fail metrics.
    
-   **Operations**: scripts/runbooks for replay from DLQ, backfills, drains.
    

---

## Collaboration

1.  Producer validates the request, persists any **authoritative state** (if needed), and **enqueues** a task (with an **idempotency key**).
    
2.  The queue **buffers** items; workers **pull** at a configured rate (prefetch/concurrency).
    
3.  Worker executes with **timeouts** and **retries with backoff**; on success it **acks**; on failure it **nacks** → requeue or DLQ after N attempts.
    
4.  Autoscaler adjusts worker count based on **queue depth/age**.
    
5.  Operators monitor SLOs and handle DLQ reprocessing when necessary.
    

---

## Consequences

**Benefits**

-   **Smooths bursts** and protects downstreams (back-pressure).
    
-   **Decouples** producer latency from processing latency.
    
-   Enables **elastic scaling** of consumers and isolation of failures.
    
-   Improves **resilience** via replay and retries.
    

**Liabilities**

-   **Eventual** (not immediate) completion; added complexity for status tracking.
    
-   Requires **idempotent** handling to tolerate redelivery.
    
-   Potential **reordering** and **duplicate** deliveries.
    
-   Another moving piece to secure, monitor, and operate.
    

---

## Implementation

### Key Decisions

-   **Broker choice & semantics:**
    
    -   **RabbitMQ/SQS** for queue semantics (visibility timeout, DLQ).
        
    -   **Kafka** for high-throughput streams; model tasks as records; manage ordering per partition.
        
-   **Message contract:** include **idempotency key**, type, version, and minimal payload (use lookups for large data).
    
-   **Delivery & retries:** ack/nack; **max attempts** → DLQ; **exponential backoff**; consider **per-error** retryability.
    
-   **Idempotency:** dedupe table, natural keys, or conditional writes to prevent duplicate side effects.
    
-   **Consumer concurrency:** prefetch/pool size matched to downstream capacity; **rate limits** if necessary.
    
-   **Poison message handling:** DLQ + alert + tooling to inspect/replay with fixes.
    
-   **Observability:** depth, **oldest message age**, processing rate, success/failure counters, per-error class.
    
-   **Autoscaling signal:** queue depth per worker, backlog minutes, or lag.
    

### Anti-Patterns

-   Doing heavy work **synchronously** and also enqueuing (double work).
    
-   **Infinite retries** on permanent errors (fill queue, starve good work).
    
-   No **visibility timeout** / long-running tasks without heartbeat/renewal.
    
-   Lack of **idempotency** → duplicate emails/charges/updates.
    
-   Monolithic “one queue for everything” with mixed priorities (use per-type queues or priorities).
    

---

## Sample Code (Java + Spring Boot + RabbitMQ)

Features shown:

-   Declares **work queue** + **DLQ** with TTL and dead-lettering.
    
-   **Producer** publishes with **publisher confirms** and an **Idempotency-Key**.
    
-   **Consumer** with manual acks, **prefetch**, retry with **exponential backoff**, and **idempotent** processing using a dedupe table.
    

> Dependencies:
> 
> -   `org.springframework.boot:spring-boot-starter-amqp`
>     
> -   `org.springframework.boot:spring-boot-starter`
>     
> -   (optional) `org.springframework.boot:spring-boot-starter-data-jdbc`
>     

```java
// QueueConfig.java
package com.example.qbll;

import org.springframework.amqp.core.*;
import org.springframework.amqp.rabbit.config.SimpleRabbitListenerContainerFactory;
import org.springframework.amqp.rabbit.connection.*;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class QueueConfig {

  public static final String EX = "orders-ex";
  public static final String QUEUE = "orders-q";
  public static final String DLX = "orders-dlx";
  public static final String DLQ = "orders-dlq";
  public static final String RK = "orders.create";

  @Bean
  public Declarables topology() {
    var ex = ExchangeBuilder.topicExchange(EX).durable(true).build();
    var dlx = ExchangeBuilder.topicExchange(DLX).durable(true).build();

    var q = QueueBuilder.durable(QUEUE)
        .withArgument("x-dead-letter-exchange", DLX)
        .withArgument("x-dead-letter-routing-key", "dead")
        .withArgument("x-message-ttl", 86_400_000) // 1 day
        .build();

    var dlq = QueueBuilder.durable(DLQ).build();

    return new Declarables(
        ex, dlx, q, dlq,
        BindingBuilder.bind(q).to(ex).with(RK).noargs(),
        BindingBuilder.bind(dlq).to(dlx).with("dead").noargs());
  }

  @Bean
  public SimpleRabbitListenerContainerFactory listenerFactory(ConnectionFactory cf) {
    var f = new SimpleRabbitListenerContainerFactory();
    f.setConnectionFactory(cf);
    f.setConcurrentConsumers(4);
    f.setMaxConcurrentConsumers(20);
    f.setAcknowledgeMode(AcknowledgeMode.MANUAL);       // manual acks
    f.setPrefetchCount(20);                              // back-pressure
    return f;
  }

  @Bean
  public RabbitTemplate rabbitTemplate(ConnectionFactory cf) {
    var tpl = new RabbitTemplate(cf);
    tpl.setMandatory(true);
    // publisher confirms
    if (cf instanceof CachingConnectionFactory ccf) ccf.setPublisherConfirmType(CachingConnectionFactory.ConfirmType.CORRELATED);
    return tpl;
  }
}
```

```java
// OrderMessage.java
package com.example.qbll;

public record OrderMessage(String idempotencyKey, String orderId, String customerId, long amountCents) {}
```

```java
// Producer.java
package com.example.qbll;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.amqp.core.MessageBuilder;
import org.springframework.amqp.core.MessageDeliveryMode;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.util.UUID;

import static com.example.qbll.QueueConfig.*;

@Component
public class Producer {
  private final RabbitTemplate tpl;
  private final ObjectMapper om = new ObjectMapper();

  public Producer(RabbitTemplate tpl) { this.tpl = tpl; }

  public void enqueueCreateOrder(String orderId, String customerId, long amountCents, String idemKey) {
    try {
      var msg = new OrderMessage(
          idemKey != null ? idemKey : UUID.randomUUID().toString(),
          orderId, customerId, amountCents);
      byte[] body = om.writeValueAsBytes(msg);

      var amqMsg = MessageBuilder.withBody(body)
          .setContentType("application/json")
          .setDeliveryMode(MessageDeliveryMode.PERSISTENT)
          .setHeader("Idempotency-Key", msg.idempotencyKey())
          .build();

      tpl.convertAndSend(EX, RK, amqMsg);
    } catch (Exception e) { throw new RuntimeException(e); }
  }
}
```

```java
// DedupeRepository.java (simple JDBC-based idempotency guard)
package com.example.qbll;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import java.time.Instant;

@Repository
public class DedupeRepository {
  private final JdbcTemplate jdbc;
  public DedupeRepository(JdbcTemplate jdbc) { this.jdbc = jdbc; }

  // returns true if this idempotency key was newly recorded
  public boolean recordFirstUse(String key) {
    Integer inserted = jdbc.update("""
      insert into idempotency_keys(key, created_at)
      values (?, ?) on conflict (key) do nothing
      """, key, Instant.now());
    return inserted != null && inserted > 0;
  }
}
```

```sql
-- schema.sql (run once)
create table if not exists idempotency_keys(
  key text primary key,
  created_at timestamptz not null
);

create table if not exists orders(
  order_id text primary key,
  customer_id text not null,
  amount_cents bigint not null,
  created_at timestamptz not null default now()
);
```

```java
// Consumer.java
package com.example.qbll;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.rabbitmq.client.Channel;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.time.Duration;
import java.util.concurrent.ThreadLocalRandom;

import static com.example.qbll.QueueConfig.QUEUE;

@Component
public class Consumer {

  private final ObjectMapper om = new ObjectMapper();
  private final DedupeRepository dedupe;
  private final OrderService orderService;

  public Consumer(DedupeRepository dedupe, OrderService orderService) {
    this.dedupe = dedupe;
    this.orderService = orderService;
  }

  @RabbitListener(queues = QUEUE, containerFactory = "listenerFactory")
  public void onMessage(Message message, Channel channel) throws IOException {
    long deliveryTag = message.getMessageProperties().getDeliveryTag();
    String idemKey = (String) message.getMessageProperties().getHeaders().get("Idempotency-Key");

    try {
      var payload = om.readValue(message.getBody(), OrderMessage.class);

      // Idempotency guard: if key already seen, ack and exit
      if (!dedupe.recordFirstUse(idemKey)) {
        channel.basicAck(deliveryTag, false);
        return;
      }

      // Business processing (with timeouts/retryable/non-retryable classification inside)
      orderService.createOrder(payload.orderId(), payload.customerId(), payload.amountCents());

      channel.basicAck(deliveryTag, false);
    } catch (TransientException te) {
      // retry with bounded backoff by requeueing (or use delayed exchange / per-message TTL)
      sleep(jitteredBackoff(te.attempt()));
      channel.basicNack(deliveryTag, false, true); // requeue
    } catch (PermanentException pe) {
      // don't poison the queue; send to DLQ via reject (queue has DLX configured)
      channel.basicReject(deliveryTag, false);
    } catch (Exception unknown) {
      // treat as transient with cap; in real code add attempt counting header
      channel.basicNack(deliveryTag, false, true);
    }
  }

  private static void sleep(long ms) {
    try { Thread.sleep(ms); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
  }
  private static long jitteredBackoff(int attempt) {
    long base = (long) (100 * Math.pow(2, Math.min(5, Math.max(0, attempt-1))));
    return ThreadLocalRandom.current().nextLong(0, Math.min(2000, base + 1));
  }
}
```

```java
// OrderService.java
package com.example.qbll;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
public class OrderService {
  private final JdbcTemplate jdbc;
  public OrderService(JdbcTemplate jdbc) { this.jdbc = jdbc; }

  public void createOrder(String orderId, String customerId, long amountCents) throws TransientException {
    try {
      jdbc.update("insert into orders(order_id, customer_id, amount_cents) values (?,?,?)",
          orderId, customerId, amountCents);
    } catch (org.springframework.dao.DuplicateKeyException dke) {
      // idempotent: already processed
    } catch (org.springframework.dao.DataAccessResourceFailureException transientDb) {
      throw new TransientException(1);
    }
  }
}

class TransientException extends Exception { private final int attempt; public TransientException(int a){attempt=a;} public int attempt(){return attempt;} }
class PermanentException extends Exception { }
```

**Notes**

-   **Prefetch** + **manual acks** implement consumer-side back-pressure.
    
-   **DLX/DLQ** captures poison messages for inspection.
    
-   **Idempotency** via dedupe table + natural keys prevents duplicates.
    
-   For scheduled backoff, consider **delayed exchanges** (RabbitMQ plugin) or **per-message TTL** + dead-letter cycling.
    
-   Swap RabbitMQ with **SQS** (use visibility timeout & DLQ) or **Kafka** (use partitioning, consumer groups, and pause/resume).
    

---

## Known Uses

-   **Order processing**, **email/SMS** sending, **webhook** fan-out.
    
-   **Image/video** processing pipelines.
    
-   **Payments**: asynchronous capture/settlement with retries and DLQs.
    
-   **Data pipelines**: ETL/ELT staging to protect downstream warehouses.
    

---

## Related Patterns

-   **Throttling / Rate Limiting:** Limit enqueue or consume rate to protect dependencies.
    
-   **Auto Scaling Group:** Scale workers by **queue depth / backlog minutes**.
    
-   **Idempotent Receiver:** Mandatory for safe redelivery/retries.
    
-   **Circuit Breaker & Timeouts & Retries:** Consumer resiliency under dependency failures.
    
-   **Dead Letter Channel:** Structured handling of poison messages.
    
-   **CQRS / Outbox:** Produce tasks reliably from transactional changes.
    

---

## Implementation Checklist

-   Choose broker and **configure DLQ**, TTL, and visibility/ack semantics.
    
-   Define **message schema** with **idempotency key** and versioning.
    
-   Implement **idempotent consumer** and classify retryable vs permanent errors.
    
-   Set **prefetch/concurrency** and **rate limits** to match downstream capacity.
    
-   Instrument **queue depth, age, successes/failures, DLQ rate**; alert on backlogs.
    
-   Add **autoscaling** policies on backlog minutes/lag.
    
-   Provide **DLQ replay** tooling with safety checks.
    
-   Load test with **burst traffic** and partial dependency outages.

