# Database Per Service — Microservice Pattern

## Pattern Name and Classification

-   **Name:** Database Per Service
    
-   **Classification:** Data Ownership & Persistence Pattern for Microservices Architecture
    

## Intent

Ensure each microservice **fully owns** its data by having an **exclusive database** (logical or physical). This hardens service boundaries, enables independent evolution, and reduces cross-team coupling at the persistence layer.

## Also Known As

-   **Private Database**
    
-   **Service-Local Persistence**
    
-   **Polyglot Persistence per Service**
    

## Motivation (Forces)

-   **Autonomy vs. Coupling:** Shared databases reintroduce coupling (shared schemas, cross-service joins, coordinated changes). Giving each service its own DB preserves autonomy.
    
-   **Independent Deployability:** Schema changes affect only the owning service; no lockstep releases.
    
-   **Team Boundaries & Ownership:** Clear “you build it, you run it, you own the data” accountability.
    
-   **Polyglot Persistence:** Different services can choose the datastore best suited to their workload (SQL, NoSQL, time-series, graph, etc.).
    
-   **Security & Blast Radius:** Compromise or failure is limited to a single service/database.
    
-   **Scalability:** Scale storage independently per service (vertical/horizontal, read replicas, sharding).
    
-   **Consistency Trade-offs:** Without cross-service joins, you lean on **eventual consistency**, asynchronous messaging, or sagas for multi-service workflows.
    
-   **Reporting & Analytics:** Global queries now require data warehousing, CDC, or materialized views instead of ad-hoc cross-service SQL.
    

## Applicability

Use when:

-   You want **independent deployment** and fast schema evolution per microservice.
    
-   Cross-team clashes over DB schemas slow you down.
    
-   Services have **distinct data access patterns** (OLTP vs. analytics; document vs. relational).
    
-   You plan to adopt **event-driven** integration (outbox/CDC, domain events, sagas).
    
-   Regulatory or security requirements demand **data isolation**.
    

Avoid or reconsider when:

-   The system is small/monolithic and teams are co-located; a shared DB may suffice.
    
-   Strong, **synchronous consistency** across many domains is required (e.g., highly coupled transactions).
    
-   You lack platform maturity for **observability, operations, CDC, backups**, and **schema governance** per service.
    

## Structure

-   **Service A** —owns→ **Database A**
    
-   **Service B** —owns→ **Database B**
    
-   **Service C** —owns→ **Database C**
    
-   Cross-service communication via **API calls** or **event bus/stream**; **no direct cross-service DB access**.
    
-   Optional **read models** or **data products** materialized from events/CDC for queries spanning multiple domains.
    

```scss
[Client] → [API Gateway]
                 │
   ┌─────────────┼────────────────┐
   ▼             ▼                ▼
[Service A]   [Service B]     [Service C]
     │             │                │
 [DB A only]   [DB B only]     [DB C only]
     │             │                │
          (Events / CDC / Sagas via Message Broker)
```

## Participants

-   **Service (Owner):** Implements domain logic and owns its schema and data lifecycle.
    
-   **Service Database:** Private datastore; access only through the owning service.
    
-   **Message Broker / Event Log:** Transports domain events and commands between services.
    
-   **API Gateway (optional):** Entry point that routes/aggregates API requests.
    
-   **Read Model / Data Product (optional):** Denormalized view for cross-service queries or UX composition.
    
-   **CDC / Outbox (optional):** Mechanism to publish reliable events from local transactions.
    

## Collaboration

1.  **Intra-service:** The service reads/writes **its own** database using transactions.
    
2.  **Inter-service:** Services never query each other’s databases; they collaborate via:
    
    -   **Synchronous APIs** (REST/GraphQL/gRPC) for request/response.
        
    -   **Asynchronous events** for eventual consistency; sagas for long-running, multi-service business transactions.
        
3.  **Query Composition:** UI composition or BFFs call multiple services; alternatively, consume events/CDC to build **read models** that answer composite queries efficiently.
    

## Consequences

**Benefits**

-   Strong **modularity and autonomy**; easier continuous delivery.
    
-   Freedom to choose the **best-fit datastore** per service.
    
-   Improved **security isolation** and **failure containment**.
    
-   Cleaner domain boundaries and ownership.
    

**Liabilities**

-   **No cross-service joins**; complexity shifts to data integration and orchestration.
    
-   **Eventual consistency** & **saga complexity** for multi-entity workflows.
    
-   **Operational overhead:** Backups, monitoring, migrations, scaling **per service**.
    
-   **Global reporting** requires data pipelines (CDC, ETL, lakehouse) and governance.
    
-   Potential **data duplication** across services/read models.
    

## Implementation

1.  **Enforce Ownership**
    
    -   Separate **network access**: security groups, credentials per service.
        
    -   Disallow foreign connections; schema read-only for others.
        
2.  **Schema Management**
    
    -   Use **Liquibase/Flyway** per service repo; migrations versioned with the code.
        
    -   Backward-compatible migrations for zero-downtime deploys.
        
3.  **Integration**
    
    -   Publish domain events using **Transactional Outbox + CDC** (e.g., Debezium/Kafka) or within the same transaction if supported.
        
    -   For synchronous needs, expose APIs; avoid remote joins—compose at the **BFF/UI** or precompute **read models**.
        
4.  **Polyglot Persistence**
    
    -   Select storage per workload: e.g., orders in Postgres, catalog in Elasticsearch, payments in a ledger DB.
        
5.  **Observability & Ops**
    
    -   Per-service dashboards: query latency, pool saturation, slow queries, replication lag.
        
    -   Backups & DR **per database**; define RPO/RTO per domain.
        
6.  **Security & Compliance**
    
    -   Least-privilege DB roles, rotation, encryption at rest/in transit.
        
    -   Data retention and PII handling per service (e.g., delete/anonymize events).
        
7.  **Reporting**
    
    -   Stream changes via **CDC** into a **lake/warehouse**; build governed **data products** for cross-domain analytics.
        

## Sample Code (Java, Spring Boot, JPA + Transactional Outbox)

> This demonstrates a service that owns its **Order** database, writes within a local transaction, and persists an **outbox** record for reliable event publishing via CDC.

```java
// build.gradle (snippets)
// dependencies {
//   implementation 'org.springframework.boot:spring-boot-starter-web'
//   implementation 'org.springframework.boot:spring-boot-starter-data-jpa'
//   implementation 'org.postgresql:postgresql:42.7.3'
//   implementation 'com.fasterxml.jackson.core:jackson-databind:2.17.0'
// }
```

```properties
# application.properties
spring.datasource.url=jdbc:postgresql://orders-db:5432/orders
spring.datasource.username=orders_service
spring.datasource.password=secret
spring.jpa.hibernate.ddl-auto=validate
spring.jpa.open-in-view=false
spring.jpa.properties.hibernate.jdbc.lob.non_contextual_creation=true
spring.datasource.hikari.maximum-pool-size=20
```

```sql
-- db/changelog/001_init.sql  (Liquibase/Flyway-friendly)
create table if not exists customer_order (
  id uuid primary key,
  customer_id uuid not null,
  status varchar(32) not null,
  total_cents bigint not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists outbox_event (
  id bigserial primary key,
  aggregate_type varchar(64) not null,
  aggregate_id uuid not null,
  event_type varchar(64) not null,
  payload jsonb not null,
  headers jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null default now(),
  published boolean not null default false
);

create index if not exists idx_outbox_published on outbox_event(published, occurred_at);
```

```java
// Order.java
package com.example.orders.domain;

import jakarta.persistence.*;
import java.time.OffsetDateTime;
import java.util.UUID;

@Entity
@Table(name = "customer_order")
public class Order {
  @Id
  private UUID id;

  @Column(nullable = false)
  private UUID customerId;

  @Column(nullable = false)
  private String status;

  @Column(nullable = false)
  private long totalCents;

  @Column(nullable = false)
  private OffsetDateTime createdAt = OffsetDateTime.now();

  @Column(nullable = false)
  private OffsetDateTime updatedAt = OffsetDateTime.now();

  protected Order() { }

  public static Order create(UUID customerId, long totalCents) {
    Order o = new Order();
    o.id = UUID.randomUUID();
    o.customerId = customerId;
    o.totalCents = totalCents;
    o.status = "CREATED";
    return o;
  }

  // getters/setters omitted for brevity
}
```

```java
// OutboxEvent.java
package com.example.orders.outbox;

import jakarta.persistence.*;
import java.time.OffsetDateTime;
import java.util.UUID;

@Entity
@Table(name = "outbox_event")
public class OutboxEvent {
  @Id
  @GeneratedValue(strategy = GenerationType.IDENTITY)
  private Long id;

  private String aggregateType;
  private UUID aggregateId;
  private String eventType;

  @Lob
  @Column(columnDefinition = "jsonb")
  private String payload;

  @Lob
  @Column(columnDefinition = "jsonb")
  private String headers = "{}";

  private OffsetDateTime occurredAt = OffsetDateTime.now();
  private boolean published = false;

  protected OutboxEvent() {}

  public OutboxEvent(String aggregateType, UUID aggregateId, String eventType, String payload) {
    this.aggregateType = aggregateType;
    this.aggregateId = aggregateId;
    this.eventType = eventType;
    this.payload = payload;
  }

  // getters/setters omitted for brevity
}
```

```java
// Repositories
package com.example.orders.persistence;

import com.example.orders.domain.Order;
import com.example.orders.outbox.OutboxEvent;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.UUID;

public interface OrderRepository extends JpaRepository<Order, UUID> {}
public interface OutboxRepository extends JpaRepository<OutboxEvent, Long> {}
```

```java
// OrderService.java
package com.example.orders.app;

import com.example.orders.domain.Order;
import com.example.orders.outbox.OutboxEvent;
import com.example.orders.persistence.OrderRepository;
import com.example.orders.persistence.OutboxRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Map;
import java.util.UUID;

@Service
public class OrderService {
  private final OrderRepository orders;
  private final OutboxRepository outbox;
  private final ObjectMapper mapper;

  public OrderService(OrderRepository orders, OutboxRepository outbox, ObjectMapper mapper) {
    this.orders = orders;
    this.outbox = outbox;
    this.mapper = mapper;
  }

  @Transactional
  public UUID placeOrder(UUID customerId, long totalCents) {
    Order order = Order.create(customerId, totalCents);
    orders.save(order);

    // Create a domain event in the outbox in the SAME transaction
    Map<String, Object> event = Map.of(
        "orderId", order.getId().toString(),
        "customerId", order.getCustomerId().toString(),
        "totalCents", order.getTotalCents(),
        "status", order.getStatus()
    );
    try {
      String payload = mapper.writeValueAsString(event);
      outbox.save(new OutboxEvent(
          "Order", order.getId(), "OrderPlaced", payload));
    } catch (Exception e) {
      throw new RuntimeException("Failed to serialize event", e);
    }

    return order.getId();
  }
}
```

```java
// OrderController.java
package com.example.orders.api;

import com.example.orders.app.OrderService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;
import java.util.UUID;

@RestController
@RequestMapping("/orders")
public class OrderController {
  private final OrderService service;

  public OrderController(OrderService service) {
    this.service = service;
  }

  @PostMapping
  public ResponseEntity<Map<String, Object>> place(@RequestBody Map<String, Object> req) {
    UUID customerId = UUID.fromString((String) req.get("customerId"));
    long totalCents = ((Number) req.get("totalCents")).longValue();
    UUID id = service.placeOrder(customerId, totalCents);
    return ResponseEntity.ok(Map.of("orderId", id.toString(), "status", "CREATED"));
  }
}
```

```java
// (Optional) Publisher - runs in a separate process or scheduled task, reads outbox and publishes to Kafka
package com.example.orders.outbox;

import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

@Component
public class OutboxPublisher {
  private final OutboxRepository repo;
  private final DomainEventBus bus;

  public OutboxPublisher(OutboxRepository repo, DomainEventBus bus) {
    this.repo = repo;
    this.bus = bus;
  }

  @Scheduled(fixedDelay = 500)
  @Transactional
  public void publishUnsent() {
    repo.findAll().stream()
        .filter(e -> !e.isPublished())
        .limit(100)
        .forEach(e -> {
          bus.publish(e.getEventType(), e.getPayload()); // e.g., Kafka topic
          e.setPublished(true);
          repo.save(e);
        });
  }
}
```

```java
// DomainEventBus.java (abstraction; implement Kafka/RabbitMQ etc.)
package com.example.orders.outbox;

public interface DomainEventBus {
  void publish(String eventType, String payload);
}
```

**Notes**

-   This service connects only to **its own** `orders` database.

-   Other services (e.g., Billing, Shipping) do **not** query `customer_order` directly; they consume `OrderPlaced` events (via CDC/publisher) or call the Orders API.

-   For read-composition, a **BFF** or **Query service** can build a denormalized projection by subscribing to events.


## Known Uses

-   Large-scale microservice adopters commonly describe this practice (e.g., **Amazon**, **Netflix**, **Uber**, **Spotify**) in public talks/blogs as a foundational tenet of service autonomy.

-   Many enterprises adopting **event-driven architectures** pair Database Per Service with **outbox/CDC** and **data products** for analytics.


## Related Patterns

-   **Bounded Context (DDD):** Conceptual ownership aligns with physical data ownership.

-   **Transactional Outbox & CDC:** Reliable event publication from local transactions.

-   **Saga (Orchestration/Choreography):** Manage distributed, long-running business processes.

-   **CQRS & Read Models:** Separate write models per service; compose queries via projections.

-   **API Gateway / BFF:** Compose data at the edge instead of database joins.

-   **Event Sourcing:** Persist events as the source of truth within a service (still service-local).

-   **Strangler Fig (Migration):** Gradually peel data and capabilities from a shared DB into service-owned stores.
# application.properties
spring.kafka.bootstrap-servers=PLAINTEXT://kafka:9092
spring.kafka.consumer.group-id=orders-consumer
spring.kafka.consumer.auto-offset-reset=earliest
spring.kafka.consumer.properties.spring.json.trusted.packages=*
app.topics.orders=orders.v1
app.topics.orders.dlq=orders.v1.DLQ
```

```java
// KafkaConfig.java
package com.example.dlq;

import org.apache.kafka.clients.admin.NewTopic;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.TopicPartition;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.annotation.EnableKafka;
import org.springframework.kafka.config.TopicBuilder;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.listener.DeadLetterPublishingRecoverer;
import org.springframework.kafka.listener.DefaultErrorHandler;
import org.springframework.util.backoff.ExponentialBackOffWithMaxRetries;

@Configuration
@EnableKafka
public class KafkaConfig {

  @Bean
  NewTopic orders(@Value("${app.topics.orders}") String topic) {
    return TopicBuilder.name(topic).partitions(6).replicas(1).build();
  }

  @Bean
  NewTopic ordersDlq(@Value("${app.topics.orders.dlq}") String topic) {
    return TopicBuilder.name(topic).partitions(6).replicas(1).build();
  }

  @Bean
  DefaultErrorHandler errorHandler(KafkaTemplate<Object, Object> template,
                                   @Value("${app.topics.orders.dlq}") String dlq) {
    DeadLetterPublishingRecoverer recoverer = new DeadLetterPublishingRecoverer(template,
        (record, ex) -> {
          // route all failures to the DLQ topic, preserve partition for locality
          TopicPartition tp = new TopicPartition(dlq, record.partition());
          return tp;
        }) {
      @Override
      public void accept(ProducerRecord<Object, Object> out, Exception ex) {
        // Enrich headers for forensics
        out.headers()
           .add("x-exception-class", ex.getClass().getName().getBytes())
           .add("x-exception-message", String.valueOf(ex.getMessage()).getBytes());
      }
    };
    ExponentialBackOffWithMaxRetries backoff = new ExponentialBackOffWithMaxRetries(3);
    backoff.setInitialInterval(500);
    backoff.setMultiplier(2.0);
    backoff.setMaxInterval(5_000);
    DefaultErrorHandler handler = new DefaultErrorHandler(recoverer, backoff);

    // classify non-retryable exceptions
    handler.addNotRetryableExceptions(IllegalArgumentException.class);
    return handler;
  }
}
```

```java
// OrderEvent.java
package com.example.dlq;

public record OrderEvent(String orderId, String status, long amountCents) { }
```

```java
// OrderConsumer.java
package com.example.dlq;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

@Component
public class OrderConsumer {
  private final ObjectMapper mapper = new ObjectMapper();

  @KafkaListener(topics = "${app.topics.orders}", containerFactory = "kafkaListenerContainerFactory")
  public void onMessage(ConsumerRecord<String, String> record) throws Exception {
    OrderEvent evt = mapper.readValue(record.value(), OrderEvent.class);

    // Example business validation
    if (evt.amountCents() <= 0) {
      throw new IllegalArgumentException("amountCents must be > 0");
    }

    // Simulate transient error
    if ("PAYMENT_PENDING".equals(evt.status()) && Math.random() < 0.2) {
      throw new RuntimeException("Transient downstream error");
    }

    // Process successfully...
    // e.g., update local DB, emit domain events, etc.
  }
}
```

```java
// DlqReplayController.java
package com.example.dlq;

import java.time.Duration;
import java.util.List;

import org.apache.kafka.clients.consumer.*;
import org.apache.kafka.common.TopicPartition;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.kafka.core.DefaultKafkaConsumerFactory;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/admin/replay")
public class DlqReplayController {

  private final KafkaTemplate<String, String> template;
  private final DefaultKafkaConsumerFactory<String, String> consumerFactory;
  private final String sourceDlq;
  private final String targetTopic;

  public DlqReplayController(KafkaTemplate<String, String> template,
                             DefaultKafkaConsumerFactory<String, String> consumerFactory,
                             @Value("${app.topics.orders.dlq}") String dlq,
                             @Value("${app.topics.orders}") String primary) {
    this.template = template;
    this.consumerFactory = consumerFactory;
    this.sourceDlq = dlq;
    this.targetTopic = primary;
  }

  @PostMapping
  public String replay(@RequestParam(defaultValue = "100") int max) {
    try (Consumer<String, String> cons = consumerFactory.createConsumer("dlq-replayer", "dlq-replayer")) {
      cons.subscribe(List.of(sourceDlq));
      int sent = 0;
      while (sent < max) {
        ConsumerRecords<String, String> records = cons.poll(Duration.ofSeconds(1));
        if (records.isEmpty()) break;
        for (ConsumerRecord<String, String> r : records) {
          // Optionally sanitize/transform before replay
          template.send(targetTopic, r.key(), r.value());
          sent++;
          if (sent >= max) break;
        }
        cons.commitSync();
      }
      return "Replayed " + sent + " message(s) from " + sourceDlq + " to " + targetTopic;
    }
  }
}
```

```java
// ListenerContainerFactoryConfig.java
package com.example.dlq;

import org.apache.kafka.common.serialization.StringDeserializer;
import org.apache.kafka.common.serialization.StringSerializer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.config.ConcurrentKafkaListenerContainerFactory;
import org.springframework.kafka.core.*;

import java.util.Map;

@Configuration
public class ListenerContainerFactoryConfig {

  @Bean
  public ProducerFactory<Object, Object> producerFactory() {
    return new DefaultKafkaProducerFactory<>(Map.of(
      org.apache.kafka.clients.producer.ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class,
      org.apache.kafka.clients.producer.ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, StringSerializer.class,
      org.apache.kafka.clients.producer.ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, "kafka:9092"
    ));
  }

  @Bean
  public KafkaTemplate<Object, Object> kafkaTemplate() {
    return new KafkaTemplate<>(producerFactory());
  }

  @Bean
  public DefaultKafkaConsumerFactory<String, String> consumerFactory() {
    return new DefaultKafkaConsumerFactory<>(Map.of(
      org.apache.kafka.clients.consumer.ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class,
      org.apache.kafka.clients.consumer.ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class,
      org.apache.kafka.clients.consumer.ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, "kafka:9092",
      org.apache.kafka.clients.consumer.ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest",
      org.springframework.kafka.support.serializer.JsonDeserializer.TRUSTED_PACKAGES, "*"
    ));
  }

  @Bean
  public ConcurrentKafkaListenerContainerFactory<String, String> kafkaListenerContainerFactory(
      DefaultKafkaConsumerFactory<String, String> consumerFactory,
      org.springframework.kafka.listener.DefaultErrorHandler errorHandler) {
    ConcurrentKafkaListenerContainerFactory<String, String> factory = new ConcurrentKafkaListenerContainerFactory<>();
    factory.setConsumerFactory(consumerFactory);
    factory.setCommonErrorHandler(errorHandler);
    factory.setConcurrency(3);
    return factory;
  }
}
```

> **Notes:**
>
> -   `DefaultErrorHandler` (Spring Kafka) retries transient errors, routes unrecoverable ones to `<topic>.DLQ`.
>
> -   The replay controller is a minimal example; in production, guard with authn/z, apply **rate limiting**, and support **filtering by error type/time window**.
>
> -   Ensure **idempotency** on downstream handlers to avoid duplicates on replay.
>

### Alternative Broker Config Snippets (non-Java, for completeness)

-   **RabbitMQ (DLX):** declare queue with args: `x-dead-letter-exchange=dlx`, `x-dead-letter-routing-key=orders.v1.DLQ`.

-   **AWS SQS:** set RedrivePolicy `{ "deadLetterTargetArn": "...:queue:orders-dlq", "maxReceiveCount": 5 }`.


## Known Uses

-   **AWS SQS/SNS**, **GCP Pub/Sub**, **Azure Service Bus**: native dead-lettering with redrive options.

-   **Kafka** ecosystems: DLQ topics with Spring Kafka, Kafka Streams, or Connect error-handling (e.g., DeadLetterQueueReporter).

-   **RabbitMQ**: DLX pattern widely adopted for microservices with Spring AMQP or MassTransit.


## Related Patterns

-   **Retry (Exponential Backoff, Jitter):** First line of defense before DLQ.

-   **Poison Message Handling:** Detection and classification of non-retryable failures.

-   **Idempotent Consumer:** Safe reprocessing after replay.

-   **Transactional Outbox & CDC:** Ensure producer → broker delivery reliability to avoid “lost before DLQ” cases.

-   **Circuit Breaker/Bulkhead:** Prevent cascading failures that would flood DLQ.

-   **Saga:** Coordinates recovery/compensation when failed commands/events impact business workflows.
