# Competing Consumers — Event-Driven Architecture Pattern

## Pattern Name and Classification

**Name:** Competing Consumers  
**Classification:** Consumption/Scalability pattern (EDA/EIP); multiple independent consumers **compete** for messages from the same **work queue/partitioned stream** to scale throughput and improve availability.

## Intent

Increase processing throughput and resilience by having **N consumers** read from a shared channel so that **each message is handled by exactly one** of them.

## Also Known As

-   Work Queue Consumers
    
-   Consumer Group (Kafka/Pulsar)
    
-   Competing Workers / Worker Pool
    

## Motivation (Forces)

-   **Throughput & parallelism:** a single consumer becomes a bottleneck; more workers increase capacity.
    
-   **Availability:** if one consumer dies, others continue processing.
    
-   **Elasticity:** scale consumer count up/down with load.
    
-   **Resource isolation:** heavy tasks run in separate processes.
    

**Forces to balance**

-   **Ordering:** per-queue/partition order vs. parallelism.
    
-   **Idempotency:** at-least-once delivery → duplicates on retry/failover.
    
-   **Back-pressure:** prefetch/concurrency must match downstream capacity.
    
-   **Fairness & hot partitions:** skewed keys can starve some consumers.
    

## Applicability

Use Competing Consumers when:

-   Work items are **independent** and can be processed in parallel.
    
-   You need **at-least-once** handling with retries.
    
-   You want horizontal scale without changing producers.
    

Avoid or limit when:

-   Strict **global ordering** is required (then partition by key and process per-key sequentially).
    
-   Tasks require **coordination/locking** across items or multi-message transactions.
    

## Structure

```sql
+-------------------+
Producer ---> ---> |   Work Queue /   | ---> Consumer A
            \       |  Topic/Stream    | ---> Consumer B
             \----> +-------------------+ ---> Consumer C
                 (each message goes to exactly one consumer in the group)
```

## Participants

-   **Producer:** Publishes tasks/messages.
    
-   **Work Channel:** Queue (JMS/AMQP/SQS) or partitioned topic/stream (Kafka/Pulsar).
    
-   **Consumer Instances:** Independent workers reading from the same channel (often in a **consumer group**).
    
-   **Broker/Coordinator:** Assigns messages/partitions to consumers; manages acks/offsets.
    
-   **DLQ / Retry Channel:** For poison messages after max attempts.
    

## Collaboration

1.  Producer sends messages to the work channel.
    
2.  Broker assigns each message (or partition share) to one **active** consumer instance.
    
3.  Consumer processes and **acknowledges/commits**; on failure, the message is **redelivered** or moved to **DLQ** after retries.
    
4.  Scaling the number of consumers changes throughput and **partition assignment**.
    

## Consequences

**Benefits**

-   Linear **throughput scale** up to broker/partition limits.
    
-   **Fault tolerance**: surviving consumers continue on failure.
    
-   **Operational simplicity**: stateless workers; elastic autoscaling.
    

**Liabilities**

-   **Duplicates** on retry/rebalance; require **idempotent handlers**.
    
-   **Ordering constraints** limited to **per-partition/queue**.
    
-   **Hot keys/partitions** can limit scalability.
    
-   Mis-tuned **prefetch/concurrency** causes memory pressure or queue oscillation.
    

## Implementation

-   **Delivery semantics:** typically **at-least-once**; design handlers to be **idempotent** (use unique keys, conditional updates).
    
-   **Partitioning & ordering:** choose a **key** (e.g., `orderId`) so that related messages land on the same partition; consumers process that key sequentially.
    
-   **Concurrency knobs:**
    
    -   AMQP/JMS: **prefetch**, **concurrency** (listener threads), **visibility timeout**\-like redelivery.
        
    -   Kafka: **consumer group size ≤ partitions** for effective parallelism; commit **after** successful processing.
        
-   **Retries & DLQ:** exponential backoff; route poison messages to DLQ with diagnostic headers.
    
-   **Back-pressure:** cap in-flight messages per consumer; use bounded thread pools.
    
-   **Observability:** lag/depth per partition/queue, processing latency, redelivery count, DLQ volume.
    
-   **Security:** per-queue/topic ACLs; isolate tenants by namespace.
    
-   **Graceful shutdown:** stop polling, finish in-flight work, commit/ack, then close.
    

---

## Sample Code (Java)

### A) Kafka — Competing Consumers via Consumer Group (idempotent handler)

```java
// build.gradle: implementation("org.springframework.kafka:spring-kafka"), implementation("com.fasterxml.jackson.core:jackson-databind")
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.kafka.support.Acknowledgment;
import org.springframework.stereotype.Component;
import java.util.concurrent.ConcurrentHashMap;

@Component
public class WorkConsumers {

  private final ObjectMapper json = new ObjectMapper();
  // Simple idempotency cache (replace with Redis/DB unique constraint for production)
  private final ConcurrentHashMap<String, Boolean> processed = new ConcurrentHashMap<>();

  // Spin up N instances of the app/pod with the same groupId to scale horizontally.
  @KafkaListener(topics = "work.items.v1", groupId = "workers", concurrency = "3") // 3 threads per instance
  public void onMessage(ConsumerRecord<String, byte[]> rec, Acknowledgment ack) throws Exception {
    WorkItem item = json.readValue(rec.value(), WorkItem.class);

    // Idempotency: skip if we've already processed (e.g., after rebalance or retry)
    String dedupeKey = item.id();
    if (processed.putIfAbsent(dedupeKey, Boolean.TRUE) != null) {
      ack.acknowledge(); // already done
      return;
    }

    try {
      handle(item); // Your business logic
      ack.acknowledge(); // commit offset after success
    } catch (Exception e) {
      processed.remove(dedupeKey); // allow retry
      // Throw to trigger retry/backoff (configured via error handler) or send to DLQ
      throw e;
    }
  }

  private void handle(WorkItem item) {
    // Long-running or I/O bound work; keep it idempotent using item.id() as key
  }

  public record WorkItem(String id, String payload) {}
}
```

**Notes**

-   **Group ID** = `"workers"` makes all instances **compete**; each partition is assigned to one thread/instance.
    
-   Effective parallelism ≤ **number of partitions**; increase partitions to scale group width.
    
-   Use a **real idempotency store** (e.g., Redis `SETNX` with TTL or a DB table with unique key) instead of the in-memory map.
    

---

### B) RabbitMQ (AMQP) — Queue with Prefetch and Multiple Competing Listeners

```java
// build.gradle: implementation("org.springframework.boot:spring-boot-starter-amqp"), jackson
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.amqp.rabbit.config.SimpleRabbitListenerContainerFactory;
import org.springframework.amqp.core.*;
import org.springframework.context.annotation.*;

@Configuration
class AmqpConfig {
  @Bean Queue workQ() { return new Queue("work.items.q", true); }
  @Bean DirectExchange ex() { return new DirectExchange("work.ex"); }
  @Bean Binding bind() { return BindingBuilder.bind(workQ()).to(ex()).with("work.items"); }

  @Bean
  SimpleRabbitListenerContainerFactory factory(org.springframework.amqp.rabbit.connection.ConnectionFactory cf) {
    var f = new SimpleRabbitListenerContainerFactory();
    f.setConnectionFactory(cf);
    f.setConcurrentConsumers(4);      // 4 competing consumers (threads) per instance
    f.setMaxConcurrentConsumers(8);
    f.setPrefetchCount(10);           // back-pressure: at most 10 unacked per consumer
    f.setDefaultRequeueRejected(false);
    return f;
  }
}

@Component
class AmqpWorkers {
  private final ObjectMapper json = new ObjectMapper();

  @RabbitListener(queues = "work.items.q", containerFactory = "factory")
  public void handle(byte[] body) throws Exception {
    WorkItem item = json.readValue(body, WorkItem.class);
    // do work; throw to trigger DLQ if configured with dead-letter exchange
  }
  record WorkItem(String id, String payload) {}
}
```

**Notes**

-   RabbitMQ delivers each message to **one** consumer; `prefetch` controls **in-flight** messages per consumer.
    
-   Configure a **DLX + DLQ** with retry TTL for poison messages.
    

---

## Known Uses

-   **Background jobs**: image/video processing, document OCR, report generation.
    
-   **ETL/ingestion**: parallel parsing/enrichment of incoming batches.
    
-   **Order fulfillment**: independent tasks per order line (pick/pack/label).
    
-   **Notification systems**: send emails/SMS/push using worker fleets.
    
-   **Web crawling / scraping**: shard URLs across many consumers.
    

## Related Patterns

-   **Message Channel (Point-to-Point):** Typical substrate for competing consumers.
    
-   **Partitioned Topic / Consumer Group:** Stream analogue (Kafka/Pulsar) for per-partition competition.
    
-   **Idempotent Receiver:** Essential to tolerate retries/duplicates.
    
-   **Dead Letter Channel / Retry:** Error-handling companions.
    
-   **Message Router / Work Sharding:** Direct certain keys to particular partitions for locality.
    
-   **Transactional Outbox / Inbox:** Reliable publication and consumption around workers.
    
-   **Resequencer:** Restore order if subsequent stages require it.

