# Event Router — Event-Driven Architecture Pattern

## Pattern Name and Classification

**Name:** Event Router  
**Classification:** Event-Driven Architecture (EDA) / Integration & Routing / Enterprise Integration Pattern (content-based + header/topic routing)

## Intent

Direct events to the appropriate downstream channels, consumers, or processing paths based on event attributes (type, headers, schema, tenant, importance, policy), without coupling producers to specific consumers.

## Also Known As

-   Content-Based Router (EIP)
    
-   Topic Router / Header Router
    
-   Event Switch / Conditional Dispatcher
    
-   Policy-Based Routing
    

## Motivation (Forces)

-   **Decoupling:** Producers shouldn’t know receivers; routing isolates topology from producers.
    
-   **Heterogeneous consumers:** Different services want different subsets, formats, and QoS.
    
-   **Multi-tenant & regional constraints:** Route by tenant/region for data residency and throttling.
    
-   **Policy & compliance:** Some events must avoid certain paths (PII filtering, geo-fencing).
    
-   **Evolution & experimentation:** A/B paths, canaries, or versioned handlers require dynamic routing.
    
-   **Throughput & cost:** Avoid fan-out storms; deliver only what’s needed to where it’s needed.
    

## Applicability

Use **Event Router** when:

-   Topics/queues are coarse-grained and you need finer fan-out control.
    
-   You onboard new consumers frequently and want zero producer changes.
    
-   You need dynamic policies (feature flags, allow/deny lists, SLA-aware paths).
    
-   You perform **content-based** or **header-based** routing (type/tenant/schema/version).
    

Be cautious when:

-   Routing rules become complex and hide business logic; keep domain logic out of the router.
    
-   Strict ordering must be preserved but routing can reorder; constrain routing keys to partitions.
    
-   Router becomes a bottleneck; prefer scalable/partitioned designs and stateless routing.
    

## Structure

-   **Ingress Channel:** Where events arrive (source topic/queue/stream).
    
-   **Router Core:** Stateless (preferably) component evaluating rules/policies to select **egress** destinations.
    
-   **Rule Store / Policy Engine:** Declarative routing table (in config/DB) with hot-reload and audit.
    
-   **Egress Channels:** Target topics/queues/HTTP sinks per rule.
    
-   **Observability:** Metrics, traces, audit of decisions, DLQ for routing failures.
    
-   **(Optional) Filter/Transformer:** Light normalization before routing; heavy transforms belong to downstreams.
    

*Textual diagram*

```rust
+------------------+
[Producers] --> [Ingress Bus] --> [Event Router] --match--> [Topic A]
                                       | \----match--> [Topic B]
                                       | \----match--> [HTTP Sink]
                                       +----no match--> [DLQ]
```

## Participants

-   **Producer:** Emits domain events (agnostic of consumers).
    
-   **Event Bus / Broker:** Kafka/Pulsar/RabbitMQ/SNS, etc.
    
-   **Event Router:** Applies routing rules/policies.
    
-   **Rule Store:** CRUD-managed routing table with versioning.
    
-   **Target Channels:** Topics/queues/webhooks/lakes.
    
-   **DLQ / Audit:** For unroutable or policy-violating messages.
    
-   **Ops/Control Plane:** Manages rules, feature flags, and governance.
    

## Collaboration

1.  Event lands on ingress topic.
    
2.  Router parses envelope (headers + payload), optionally upcasts schema/version.
    
3.  Router queries rule store and evaluates predicates (type, tenant, region, PII tag, priority, contract version).
    
4.  Router publishes the event to one or more destinations; optionally adds routing headers/labels.
    
5.  On rule miss or policy violation, router sends to DLQ with a reason code; emits metrics and traces.
    

## Consequences

**Benefits**

-   Strong decoupling and agility: add/retire consumers without changing producers.
    
-   Centralized governance: enforce data residency, PII policies, throttling tiers.
    
-   Supports multi-tenancy and regional sharding.
    
-   Enables progressive delivery (A/B, canary) and versioned rollouts.
    

**Liabilities**

-   Risk of central bottleneck (“smart pipe”); must be horizontally scalable and stateless.
    
-   Complex rules can become opaque; require observability and explainability.
    
-   Misrouting has wide blast radius; strong testing and change controls needed.
    
-   Potential ordering impact when routing to multiple destinations/partitions.
    

## Implementation

**Key practices**

-   **Stateless & partition-aware:** Hash by routing key (e.g., aggregateId) to preserve per-key ordering.
    
-   **Declarative rules:** Keep rules in a versioned store (YAML/JSON/DB) with audit and rollout controls.
    
-   **Policy first:** Validate compliance (PII, geo) before delivery; deny > allow.
    
-   **Observability:** Emit counters (by rule/destination), latency, and unroutable rates; sample payload fingerprints.
    
-   **Resiliency:** Use DLQ on failure; backpressure to ingress; circuit breakers for HTTP sinks.
    
-   **Schema evolution:** Upcasters to normalize old versions to current routing fields.
    
-   **Throughput:** Batch reads/writes; use async send with bounded in-flight and retries + idempotency.
    
-   **Change safety:** Dry-run/simulate new rules against historical samples; shadow routes.
    

### Typical rule types

-   **Content-based:** `event.type == "OrderCreated" && event.total > 1000`
    
-   **Header-based:** `headers["tenant"] == "eu-west" && headers["pii"] == "false"`
    
-   **Pattern-based:** topic/category/namespace matches
    
-   **Version/Contract-based:** `schemaVersion >= 3`
    
-   **Rate & canary:** percentage splits or hash mod routing for A/B
    

## Sample Code (Java, Spring Boot + Kafka)

Below is a compact, production-leaning router. It:

-   Parses headers + JSON payload into a small **Envelope**.
    
-   Evaluates a set of pluggable **Rule** predicates (strategy pattern).
    
-   Publishes to one or more target topics via **KafkaTemplate**.
    
-   Preserves per-aggregate ordering by using the same key for egress.
    
-   Emits basic metrics and routes unroutable events to **DLQ**.
    

```java
// Envelope & minimal model
public record Envelope(
    String key,                    // e.g., aggregateId/orderId
    String type,                   // event type
    String tenant,                 // tenant/region
    int schemaVersion,             // schema version
    boolean containsPii,           // computed/classified
    String payloadJson             // original JSON
) {}

public interface Rule {
    boolean matches(Envelope e);
    /** Return target topics for this rule (could be 1..n). */
    java.util.List<String> targets(Envelope e);
    default String name() { return getClass().getSimpleName(); }
}

// Example concrete rules
class HighValueOrderRule implements Rule {
    public boolean matches(Envelope e) {
        if (!"OrderCreated".equals(e.type())) return false;
        // quick peek: avoid full parse if possible; or parse with a fast JSON lib
        // naive parse for demo (extract "total" from JSON)
        return e.payloadJson().contains("\"total\":") && extractTotal(e.payloadJson()) >= 1000.0;
    }
    public java.util.List<String> targets(Envelope e) { return java.util.List.of("orders.high-value"); }
    private double extractTotal(String json) {
        try {
            var idx = json.indexOf("\"total\":");
            if (idx < 0) return 0.0;
            var sub = json.substring(idx + 8).replaceAll("[^0-9.]", " ");
            var parts = sub.trim().split("\\s+");
            return Double.parseDouble(parts[0]);
        } catch (Exception ex) { return 0.0; }
    }
}

class TenantEuNoPiiRule implements Rule {
    public boolean matches(Envelope e) {
        return "eu".equalsIgnoreCase(e.tenant()) && !e.containsPii();
    }
    public java.util.List<String> targets(Envelope e) { return java.util.List.of("eu.events"); }
}

class SchemaV3PaymentsRule implements Rule {
    public boolean matches(Envelope e) { return e.schemaVersion() >= 3 && e.type().startsWith("Payment"); }
    public java.util.List<String> targets(Envelope e) { return java.util.List.of("payments.v3"); }
}

class CatchAllAuditRule implements Rule {
    public boolean matches(Envelope e) { return true; } // last rule
    public java.util.List<String> targets(Envelope e) { return java.util.List.of("audit.events"); }
}

// Router service
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.common.header.Header;
import org.apache.kafka.common.header.Headers;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Service;

@Service
public class EventRouterService {

    private final KafkaTemplate<String, String> kafka;
    private final java.util.List<Rule> rules;
    private final String dlqTopic = "router.dlq";

    public EventRouterService(KafkaTemplate<String, String> kafka) {
        this.kafka = kafka;
        // In production: load from DB/config and hot-reload
        this.rules = java.util.List.of(
                new HighValueOrderRule(),
                new TenantEuNoPiiRule(),
                new SchemaV3PaymentsRule(),
                new CatchAllAuditRule()
        );
    }

    @KafkaListener(topics = "ingress.events", groupId = "event-router")
    public void onIngress(ConsumerRecord<String, String> rec) {
        try {
            Envelope env = toEnvelope(rec);
            var destinations = route(env);

            if (destinations.isEmpty()) {
                publishDlq(rec, "NO_MATCH");
                return;
            }
            for (String topic : destinations) {
                // Preserve key-based ordering
                var out = new ProducerRecord<String, String>(topic, env.key(), env.payloadJson());
                // propagate useful headers
                out.headers().add(byteHeader("type", env.type()));
                out.headers().add(byteHeader("tenant", env.tenant()));
                out.headers().add(byteHeader("schemaVersion", Integer.toString(env.schemaVersion())));
                out.headers().add(byteHeader("routed-by", "EventRouterService"));
                kafka.send(out);
            }
            // increment metrics: routed_count{destinations}
        } catch (Exception ex) {
            publishDlq(rec, "ROUTER_EXCEPTION:" + safe(ex.getMessage()));
        }
    }

    private Envelope toEnvelope(ConsumerRecord<String, String> rec) {
        Headers h = rec.headers();
        String type = stringHeader(h, "type", "Unknown");
        String tenant = stringHeader(h, "tenant", "default");
        int schemaV = Integer.parseInt(stringHeader(h, "schemaVersion", "1"));
        boolean pii = Boolean.parseBoolean(stringHeader(h, "pii", "false"));
        String key = rec.key() != null ? rec.key() : computeStableKey(rec.value(), type);
        String payload = rec.value();
        return new Envelope(key, type, tenant, schemaV, pii, payload);
    }

    private java.util.List<String> route(Envelope e) {
        java.util.LinkedHashSet<String> targets = new java.util.LinkedHashSet<>();
        for (Rule r : rules) {
            if (r.matches(e)) targets.addAll(r.targets(e));
        }
        return new java.util.ArrayList<>(targets);
    }

    private void publishDlq(ConsumerRecord<String, String> rec, String reason) {
        var pr = new ProducerRecord<String, String>(dlqTopic, rec.key(), rec.value());
        pr.headers().add(byteHeader("dlq-reason", reason));
        // carry context for triage
        copyIfPresent(rec.headers(), pr.headers(), "type", "tenant", "schemaVersion");
        kafka.send(pr);
        // increment metrics: dlq_count{reason}
    }

    // Helpers
    private static String stringHeader(Headers h, String k, String def) {
        Header hd = h.lastHeader(k);
        return hd == null ? def : new String(hd.value());
    }
    private static Header byteHeader(String k, String v) { return new org.apache.kafka.common.header.internals.RecordHeader(k, v.getBytes()); }
    private static void copyIfPresent(Headers from, Headers to, String... keys) {
        for (String k : keys) {
            Header h = from.lastHeader(k);
            if (h != null) to.add(byteHeader(h.key(), new String(h.value())));
        }
    }
    private static Header byteHeader(String k, byte[] v) { return new org.apache.kafka.common.header.internals.RecordHeader(k, v); }
    private static String computeStableKey(String payload, String type) {
        return Integer.toHexString(java.util.Objects.hash(payload, type));
    }
    private static String safe(String s) { return s == null ? "" : (s.length() > 256 ? s.substring(0,256) : s); }
}
```

**Operational notes**

-   Deploy multiple router instances; partition consumption by key to scale horizontally.
    
-   Keep rules fast; prefer header-based predicates or pre-extracted envelope fields.
    
-   Provide a **simulation mode**: evaluate new rule sets against sampled historical events and compare destinations.
    
-   Expose **/health** and **/metrics** for routed\_count, dlq\_count{reason}, rule\_hit\_count{rule}, and p95 route latency.
    

## Known Uses

-   **Kafka header/content routers** in microservice platforms to split monolithic topics into service-specific destinations.
    
-   **RabbitMQ topic exchanges** to route by routing key pattern (e.g., `order.*.created`).
    
-   **AWS SNS → SQS fan-out** with filter policies per subscription (attributes-based routing).
    
-   **Pulsar namespaces/regex subscriptions** for multi-tenant event segregation.
    
-   **Payment/ledger systems** routing by region/brand/PII policy; **search indexing** routers separating PII vs. public indexes.
    

## Related Patterns

-   **Content-Based Router (EIP):** Core routing logic over message content.
    
-   **Message Filter / Event Filter:** Drop non-matching events instead of routing.
    
-   **Publish–Subscribe / Fan-out:** Broadcast; often combined with router for selective fan-out.
    
-   **Event Gateway:** Front-door routing, protocol bridging, auth & policy enforcement.
    
-   **Event Mesh:** Multi-broker/multi-region routing and replication fabric.
    
-   **Message Translator / Upcaster:** Normalize/upgrade events before routing.
    
-   **Dead Letter Channel:** Sink for unroutable or policy-violating events.

