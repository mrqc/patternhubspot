# Event Mesh — Event-Driven Architecture Pattern

## Pattern Name and Classification

**Name:** Event Mesh  
**Classification:** Distributed event infrastructure / routing pattern for EDA; a **network of brokers/relays** that provides global **any-to-any publish/subscribe**, policy-based routing, and **location transparency**.

## Intent

Connect multiple event backbones (regions, clouds, data centers, edge sites, tenants) into a **coherent fabric** that routes events based on **topic, tenant, attributes, or policy**, so producers and consumers interact as if on one logical bus—while each domain keeps **autonomy, isolation, and governance**.

## Also Known As

-   Event Fabric / Event Grid
    
-   Event Mesh Network / Mesh of Brokers
    
-   Federation of Brokers / Interconnect
    

## Motivation (Forces)

-   Enterprises span **multi-region, multi-cloud, on-prem & edge**; one broker cluster rarely fits all.
    
-   Need **local autonomy** (latency, data residency, blast radius) but also **global propagation** of selected events.
    
-   Different domains use different **protocols/vendors** (Kafka, AMQP, MQTT, NATS, Pulsar).
    
-   Cross-boundary traffic must carry **security, tenancy, schema, and rate limits**.
    

**Forces to balance**

-   **Simplicity** (single logical bus) vs. **governance** (who can see what, where).
    
-   **Latency & bandwidth** vs. **fan-out scope**.
    
-   **Exactly-once effects** with **at-least-once** links across meshes.
    
-   **Ordering** across WAN partitions and failover paths.
    

## Applicability

Use an Event Mesh when:

-   You must move events **between regions/sites/clouds** with policy control.
    
-   Domains want to **publish locally** and selectively **share** events outward.
    
-   You require **protocol bridging** (e.g., MQTT edge ⇄ Kafka core) and **multi-tenant isolation**.
    
-   You need **resilient routing** (failover, replay, buffering) over unreliable links.
    

Avoid or limit when:

-   A single cluster with **local** clients suffices and governance is simple.
    
-   You need **hard global ordering** across domains (hard to guarantee over meshes—scope ordering per key/partition).
    

## Structure

```bash
+-----------+            +-----------+             +-----------+
 Region A |  Broker A |<--mesh---->|  Broker B |<--mesh----->|  Broker C |  Region C
 (Kafka)  |  + Relay  |            |  + Relay  |             |  + Relay  |  (AMQP/MQTT)
          +-----------+            +-----------+             +-----------+
                ^                         ^                        ^
                |                         |                        |
          local apps                 local apps                local apps
        (produce/consume)         (produce/consume)         (produce/consume)

Policies: routing (topic/tenant), filters, transforms, masking, quotas, retries, DLQ
```

## Participants

-   **Local Brokers/Backbones:** Kafka/Pulsar/NATS/AMQP clusters per domain/region.
    
-   **Mesh Relays/Bridges:** Processes or built-in broker links that consume from one side and publish to another, applying **policy**.
    
-   **Policy & Registry:** Routing tables, topic maps, schema contracts, tenant catalogs, ACLs.
    
-   **Producers/Consumers:** Unaware (ideally) of cross-site routing—interact with the local broker.
    
-   **Observability Stack:** Mesh metrics/trace/lag dashboards, replay tooling, DLQs.
    

## Collaboration

1.  Producers publish to the **local broker** (fast, governed).
    
2.  **Relays** subscribe/mirror selected topics/partitions per **routing policy** (topic patterns, header predicates, tenant scopes).
    
3.  Relays **transform** (envelope normalization, PII scrubbing), then publish to **remote brokers** (possibly multiple).
    
4.  Consumers in other domains subscribe **locally**; the mesh delivers.
    
5.  On link failure, relays **buffer** and **retry**; poisoned events go to **DLQ**; operators can **replay**.
    

## Consequences

**Benefits**

-   **Location transparency** with **local autonomy**; reduces cross-region latency for clients.
    
-   **Resilience & scale-out**: domains can operate independently yet share events selectively.
    
-   **Heterogeneity support**: bridge protocols/vendors while centralizing governance.
    
-   **Data residency** controls: keep data local; export only permitted subsets.
    

**Liabilities**

-   Added **operational surface** (relays, policies, keys, certs).
    
-   Potential **duplicated delivery** across failover paths → consumers need **idempotency**.
    
-   **Eventual consistency** across sites; no global total order.
    
-   Misconfigured routing can cause **echo loops** or data leakage—requires strict governance.
    

## Implementation

-   **Topology:** Hub-and-spoke, ring, or partial mesh. Prefer **explicit peering** with **directionality** per route to avoid loops.
    
-   **Routing keys:** Topic patterns (`orders.*.v1`), tenant namespaces (`t1.*`), header predicates (`region=EU`), content filters.
    
-   **Transformations:** Envelope normalization (e.g., **CloudEvents**), schema upgrades, header mapping, **PII redaction**.
    
-   **Reliability:**
    
    -   Use **at-least-once** replication, idempotent producers, and **Inbox/Idempotent Receiver** on consumers.
        
    -   **Replay**: retain source offsets; enable DLQ for permanent failures.
        
-   **Ordering:** Preserve **per-key** order by keying the relay’s publish with the same key; don’t mix keys across links.
    
-   **Backpressure:** Bounded in-memory queues, on-disk spill, rate limits per route/tenant.
    
-   **Security:** mTLS between relays and brokers; per-tenant ACLs; payload encryption/masking.
    
-   **Config/Governance:** Declarative route config with code-review; CI to lint for loops & forbidden flows.
    
-   **Observability:** Per-route lag, throughput, drop/DLQ count, latency, error cause histograms; trace IDs propagated across hops.
    

---

## Sample Code (Java)

**Mesh Relay (Kafka → Kafka)**  
A minimal relay that mirrors selected topics from **source cluster** to **target cluster** with routing rules, header filtering, idempotent production, manual commits, and DLQ on the source cluster. Adapt for other brokers by swapping clients.

> Build (Gradle deps):

```gradle
implementation "org.apache.kafka:kafka-clients:3.7.0"
implementation "com.fasterxml.jackson.core:jackson-databind:2.17.1"
```

```java
import org.apache.kafka.clients.consumer.*;
import org.apache.kafka.clients.producer.*;
import org.apache.kafka.common.TopicPartition;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.apache.kafka.common.serialization.ByteArrayDeserializer;
import org.apache.kafka.common.serialization.StringSerializer;
import org.apache.kafka.common.serialization.ByteArraySerializer;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/** Declarative routing: sourceTopicPattern -> targetTopic template (supports ${tenant} substitution) */
record Route(Pattern sourcePattern, String targetTemplate,
             Map<String,String> requiredHeaders, boolean redactEmail) {}

public class MeshRelayApp {

  public static void main(String[] args) {
    // --- CONFIG (env/props in real life) ---
    var sourceProps = Map.<String,Object>of(
        ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, "SRC_KAFKA:9092",
        ConsumerConfig.GROUP_ID_CONFIG, "mesh-relay-eu-to-us",
        ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class.getName(),
        ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, ByteArrayDeserializer.class.getName(),
        ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, "false",
        ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest",
        ConsumerConfig.MAX_POLL_RECORDS_CONFIG, "500"
    );

    var targetProps = Map.<String,Object>of(
        ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, "DST_KAFKA:9092",
        ProducerConfig.ACKS_CONFIG, "all",
        ProducerConfig.ENABLE_IDEMPOTENCE_CONFIG, "true",
        ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class.getName(),
        ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, ByteArraySerializer.class.getName()
    );

    // Example routes
    var routes = List.of(
        new Route(Pattern.compile("^t1\\.orders\\..*\\.v1$"), "t1.orders.${tenant}.v1",
            Map.of("region", "EU"), true),
        new Route(Pattern.compile("^t2\\.customers\\.state\\.v1$"), "t2.customers.state.v1",
            Map.of(), false)
    );

    // --- Start relay ---
    new MeshRelayApp().run(sourceProps, targetProps, routes, "mesh.DLQ");
  }

  void run(Map<String,Object> srcProps, Map<String,Object> dstProps, List<Route> routes, String dlqTopic) {
    try (KafkaConsumer<String, byte[]> consumer = new KafkaConsumer<>(srcProps);
         KafkaProducer<String, byte[]> producer = new KafkaProducer<>(dstProps)) {

      // Subscribe to union of all patterns
      consumer.subscribe(routes.stream().map(r -> r.sourcePattern()).collect(Collectors.toList()));

      var inFlightOffsets = new ConcurrentHashMap<TopicPartition, Long>();

      while (true) {
        ConsumerRecords<String, byte[]> records = consumer.poll(Duration.ofMillis(1000));
        if (records.isEmpty()) continue;

        for (ConsumerRecord<String, byte[]> rec : records) {
          try {
            Route route = pickRoute(routes, rec.topic());
            if (route == null) continue; // not routed

            if (!headersMatch(route.requiredHeaders(), rec.headers())) {
              // skip silently or route to DLQ for audit
              continue;
            }

            // Determine tenant (from header or topic prefix)
            String tenant = header(rec.headers(), "tenant");
            if (tenant == null || tenant.isBlank()) {
              tenant = rec.topic().split("\\.")[0]; // naive fallback
            }

            String targetTopic = route.targetTemplate()
                .replace("${tenant}", tenant);

            String targetKey = rec.key(); // preserve per-key ordering
            byte[] value = route.redactEmail() ? redactEmail(rec.value()) : rec.value();

            ProducerRecord<String, byte[]> out = new ProducerRecord<>(targetTopic, targetKey, value);
            // Copy selected headers through
            copyHeader("messageId", rec.headers(), out);
            copyHeader("correlationId", rec.headers(), out);
            copyHeader("eventType", rec.headers(), out);
            out.headers().add("x-relayed-by", "mesh-relay".getBytes(StandardCharsets.UTF_8));

            // Send and wait to ensure at-least-once across link before committing
            producer.send(out).get();

            // track highest offset per partition to commit later
            inFlightOffsets.merge(new TopicPartition(rec.topic(), rec.partition()), rec.offset(),
                Math::max);

          } catch (Exception ex) {
            // Publish to DLQ on source cluster with diagnostics (best-effort)
            try {
              ProducerRecord<String, byte[]> dlq = new ProducerRecord<>(dlqTopic, rec.key(), rec.value());
              dlq.headers().add("dlq.error", ex.getClass().getName().getBytes(StandardCharsets.UTF_8));
              dlq.headers().add("dlq.message", shortBytes(ex.getMessage()));
              dlq.headers().add("dlq.originalTopic", rec.topic().getBytes(StandardCharsets.UTF_8));
              producer.send(dlq);
            } catch (Exception ignore) {}
          }
        }

        // Commit offsets after successful shipments
        if (!inFlightOffsets.isEmpty()) {
          var commitMap = new HashMap<TopicPartition, OffsetAndMetadata>();
          inFlightOffsets.forEach((tp, off) -> commitMap.put(tp, new OffsetAndMetadata(off + 1)));
          consumer.commitSync(commitMap);
          inFlightOffsets.clear();
        }
      }
    }
  }

  private Route pickRoute(List<Route> routes, String topic) {
    for (Route r : routes) if (r.sourcePattern().matcher(topic).matches()) return r;
    return null;
  }

  private boolean headersMatch(Map<String,String> req, Headers headers) {
    for (var e : req.entrySet()) {
      String val = header(headers, e.getKey());
      if (!e.getValue().equals(val)) return false;
    }
    return true;
  }

  private String header(Headers h, String k) {
    var v = h.lastHeader(k);
    return v == null ? null : new String(v.value(), StandardCharsets.UTF_8);
  }

  private void copyHeader(String k, Headers from, ProducerRecord<String, byte[]> to) {
    var v = from.lastHeader(k);
    if (v != null) to.headers().add(k, v.value());
  }

  private static byte[] redactEmail(byte[] jsonBytes) {
    // Tiny, naive email redactor; replace user part with "***"
    try {
      String s = new String(jsonBytes, StandardCharsets.UTF_8);
      s = s.replaceAll("\"email\"\\s*:\\s*\"([^\"]+)@([^\"]+)\"", "\"email\":\"***@$2\"");
      return s.getBytes(StandardCharsets.UTF_8);
    } catch (Exception e) { return jsonBytes; }
  }

  private static byte[] shortBytes(String s) {
    if (s == null) return new byte[0];
    var t = s.length() > 240 ? s.substring(0, 240) : s;
    return t.getBytes(StandardCharsets.UTF_8);
  }
}
```

**What this relay demonstrates**

-   **Policy-based routing** via regex + header predicates.
    
-   **Per-key ordering** preserved by reusing the source key.
    
-   **At-least-once** link with idempotent producer and **commit-after-send**.
    
-   **DLQ** for failures on the source cluster.
    
-   **Transformation** example: email redaction.
    

*Production hardening*: TLS/mTLS, retries with backoff, bounded buffers, circuit breakers, config hot-reload, loop prevention (route IDs, “x-relayed-by” hop count), metrics (throughput/lag/DLQ).

---

## Known Uses

-   **Multi-region e-commerce:** share `orders.*` and `inventory.*` between EU/US with regional residency and filtered propagation.
    
-   **Hybrid cloud:** on-prem manufacturing lines (MQTT/AMQP) bridged into a cloud Kafka analytics backbone.
    
-   **SaaS multi-tenant platforms:** tenant-scoped topics with selective broadcast (e.g., reference data) across regions.
    
-   **Edge analytics:** local NATS/MQTT at plants, relayed to centralized Pulsar/Kafka for ML pipelines.
    
-   **Disaster recovery/active-active:** bi-directional routes with conflict policy and replay.
    

## Related Patterns

-   **Event Gateway:** Edge ingress/egress for external systems; meshes connect **internal domains/regions**.
    
-   **Publish–Subscribe Channel:** Underlying abstraction per domain; mesh federates many.
    
-   **Message Router / Content-Based Router:** Core of policy-driven forwarding.
    
-   **Transactional Outbox & Inbox:** Reliability at producer/consumer edges surrounding the mesh.
    
-   **Dead Letter Queue:** Quarantine cross-link failures.
    
-   **Event Carried State Transfer (ECST):** Often the payload type moved across sites.
    
-   **Choreography Saga:** Sagas spanning domains rely on meshes to propagate events.
    

> **Bottom line:** An Event Mesh lets you keep systems **local and governable** while still sharing the **right events** globally—with policy, resilience, and protocol freedom.
