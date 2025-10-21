
# Inter-Agent Communication (A2A)

## Pattern Name and Classification

Inter-Agent Communication (A2A) — coordination/messaging pattern for agentic systems; enables agents to exchange intents, data, and artifacts through structured messages over request/reply and publish/subscribe channels.

## Intent

Provide a reliable, typed way for multiple agents to coordinate work, share state, and negotiate responsibilities without tight coupling.

## Also Known As

Agent-to-Agent Messaging; Blackboard Messaging; Pub/Sub for Agents; Request/Reply Bus.

## Motivation (Forces)

-   Agents specialize; they must coordinate without embedding each other’s logic.

-   Direct calls create brittle dependencies, tight coupling, and cascading failures.

-   Some exchanges are synchronous (ask/answer), others are asynchronous (events).

-   We need observability, idempotency, and backpressure to avoid chatter and loops.


## Applicability

Use when:

-   More than one autonomous agent collaborates on shared tasks.

-   You need both event-driven fan-out and targeted request/reply.

-   Agents evolve independently and should be deployable without lockstep changes.

-   Auditable traces and correlation across steps matter.  
    Avoid when a single agent or a simple pipeline suffices.


## Structure

1.  **Message Schema**: id, type, subject/topic, payload, headers (trace, ttl, causality).

2.  **Channels**: request/reply queues and pub/sub topics.

3.  **Broker/Bus**: routes messages, enforces delivery and QoS.

4.  **Inbox/Outbox**: per-agent buffers with idempotency keys and retries.

5.  **Router/Policy**: filters, ACLs, and rate limits to prevent storms.

6.  **Observability**: metrics, traces, and dead-letter queues.


## Participants

-   **Agents**: autonomous roles (Planner, Researcher, Coder, Reviewer).

-   **Message Bus**: transport abstraction for send/subscribe/call.

-   **Serializer/Validator**: encodes payloads and validates schemas.

-   **Registry/Directory**: optional service discovery or topic catalog.

-   **Monitor**: logs, traces, SLOs; surfaces loops and retries.

-   **DLQ/Quarantine**: captures malformed or repeatedly failing messages.


## Collaboration

An agent emits a message (event or request) → the bus routes to subscribers or a specific responder → recipients process and respond with correlated replies or new events → policies enforce retries, timeouts, and dedupe → monitor records spans and outcomes.

## Consequences

**Benefits**

-   Loose coupling and independent evolution of agents.

-   Natural fit for both synchronous queries and asynchronous events.

-   Clear audit trails via correlation and causality headers.

-   Resilience with retries, DLQ, and backpressure.


**Liabilities**

-   Additional infrastructure and operational complexity.

-   Message schemas and versioning require discipline.

-   Risk of feedback loops or storms without policies.

-   Observability and idempotency must be engineered explicitly.


## Implementation (Key Points)

-   Standardize envelopes: `messageId`, `causationId`, `correlationId`, `type`, `topic`, `ttlMs`, `headers`, `payload`.

-   Offer both **request/reply** (RPC-like with timeout) and **pub/sub** for events.

-   Enforce **idempotency** with `messageId` and dedupe caches.

-   Add **retry with jitter**, **DLQ**, and **circuit breakers** per destination.

-   Version schemas; use backward-compatible changes and content negotiation.

-   Guard with ACLs and quotas; isolate noisy agents.

-   Include **tracing**: span ids, timing, and per-topic metrics.

-   Provide **backpressure**: bounded inboxes, drop policies, or slow-start.


## Sample Code (Java)

```java
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Consumer;

/** ---- Message model ---- */
class Message {
    final String messageId = UUID.randomUUID().toString();
    final String correlationId;   // stable across a conversation
    final String causationId;     // parent messageId
    final String type;            // e.g., "research.query", "draft.request"
    final String topic;           // pub/sub topic
    final Map<String, String> headers;
    final String payload;
    final long ttlMs;
    final Instant createdAt = Instant.now();

    Message(String correlationId, String causationId, String type, String topic,
            Map<String,String> headers, String payload, long ttlMs) {
        this.correlationId = correlationId;
        this.causationId = causationId;
        this.type = type;
        this.topic = topic;
        this.headers = headers == null ? Map.of() : headers;
        this.payload = payload;
        this.ttlMs = ttlMs;
    }
    boolean expired() {
        return Instant.now().toEpochMilli() - createdAt.toEpochMilli() > ttlMs;
    }
}

/** ---- Bus abstraction ---- */
interface AgentBus {
    void publish(Message m);
    void subscribe(String topic, Consumer<Message> handler);
    String call(String topic, String type, String payload, long timeoutMs); // request/reply
}

/** ---- In-memory bus with pub/sub, request/reply, DLQ and idempotency ---- */
class InMemoryBus implements AgentBus {
    private final Map<String, List<Consumer<Message>>> subs = new ConcurrentHashMap<>();
    private final BlockingQueue<Message> dlq = new LinkedBlockingQueue<>();
    private final Set<String> seen = ConcurrentHashMap.newKeySet(); // idempotency
    private final ExecutorService pool = Executors.newCachedThreadPool();

    public void publish(Message m) {
        if (m.expired()) { dlq.offer(m); return; }
        if (!seen.add(m.messageId)) return; // dedupe
        List<Consumer<Message>> handlers = subs.getOrDefault(m.topic, List.of());
        if (handlers.isEmpty()) dlq.offer(m);
        for (Consumer<Message> h : handlers) {
            pool.submit(() -> {
                try { h.accept(m); } catch (Throwable t) { dlq.offer(m); }
            });
        }
    }

    public void subscribe(String topic, Consumer<Message> handler) {
        subs.computeIfAbsent(topic, k -> new CopyOnWriteArrayList<>()).add(handler);
    }

    public String call(String topic, String type, String payload, long timeoutMs) {
        String corr = UUID.randomUUID().toString();
        String replyTopic = "reply." + corr;
        CompletableFuture<String> fut = new CompletableFuture<>();

        subscribe(replyTopic, msg -> {
            if (corr.equals(msg.correlationId)) fut.complete(msg.payload);
        });

        publish(new Message(corr, null, type, topic,
                Map.of("replyTo", replyTopic), payload, timeoutMs));

        try { return fut.get(timeoutMs, TimeUnit.MILLISECONDS); }
        catch (Exception e) { return "ERROR: timeout"; }
        finally { subs.remove(replyTopic); }
    }

    public Message takeDLQ(long ms) throws InterruptedException { return dlq.poll(ms, TimeUnit.MILLISECONDS); }
}

/** ---- Agent base ---- */
abstract class Agent {
    protected final AgentBus bus;
    protected final String name;
    protected Agent(String name, AgentBus bus) { this.name = name; this.bus = bus; }
    protected Message newMsg(String corrId, String causeId, String type, String topic, String payload, long ttlMs) {
        return new Message(corrId, causeId, type, topic, Map.of("from", name), payload, ttlMs);
    }
}

/** ---- Concrete agents ---- */
class ResearchAgent extends Agent {
    ResearchAgent(AgentBus bus) { super("researcher", bus); }

    void start() {
        bus.subscribe("research.query", msg -> {
            // Very naive “retrieval”
            String answer = "Facts for: " + msg.payload + " | refs: [A],[B]";
            String replyTo = msg.headers.getOrDefault("replyTo", "reply." + msg.correlationId);
            bus.publish(new Message(msg.correlationId, msg.messageId,
                    "research.answer", replyTo, Map.of("from", name), answer, 2000));
        });
    }
}

class WriterAgent extends Agent {
    WriterAgent(AgentBus bus) { super("writer", bus); }

    void start() {
        bus.subscribe("draft.request", msg -> {
            String draft = "Draft: " + msg.payload + " ✔";
            bus.publish(new Message(msg.correlationId, msg.messageId,
                    "draft.event", "draft.created", Map.of("from", name), draft, 2000));
        });
    }
}

class CoordinatorAgent extends Agent {
    CoordinatorAgent(AgentBus bus) { super("coordinator", bus); }

    String runFlow(String goal) {
        String corr = UUID.randomUUID().toString();

        // Step 1: ask Research via request/reply
        String facts = bus.call("research.query", "research.request", goal, 1500);
        if (facts.startsWith("ERROR")) return "Failed: research timeout";

        // Step 2: publish a draft request; wait for a draft event (simple latch)
        CompletableFuture<String> draftFut = new CompletableFuture<>();
        String draftTopic = "draft.created";
        Consumer<Message> handler = m -> {
            if (corr.equals(m.correlationId)) draftFut.complete(m.payload);
        };
        bus.subscribe(draftTopic, handler);

        bus.publish(new Message(corr, null, "draft.request", "draft.request",
                Map.of("from", name), "Use: " + facts, 1500));

        try { return draftFut.get(1500, TimeUnit.MILLISECONDS); }
        catch (Exception e) { return "Failed: draft timeout"; }
        finally { /* in-memory cleanup omitted for brevity */ }
    }
}

/** ---- Demo ---- */
public class InterAgentCommunicationDemo {
    public static void main(String[] args) throws Exception {
        InMemoryBus bus = new InMemoryBus();
        new ResearchAgent(bus).start();
        new WriterAgent(bus).start();
        CoordinatorAgent coord = new CoordinatorAgent(bus);

        String result = coord.runFlow("Q3 EV trends for EU");
        System.out.println(result);

        // Inspect DLQ (if any)
        Message dead = bus.takeDLQ(50);
        if (dead != null) System.err.println("DLQ: " + dead.type + " from " + dead.headers.get("from"));
    }
}
```

## Known Uses

-   Multi-agent research-and-write loops where researcher, planner, coder, and reviewer exchange requests and events.

-   Orchestrations that require both targeted queries and broadcast signals (e.g., “new facts available,” “review needed”).

-   Marketplaces of agents that subscribe to domains and compete or collaborate.

-   Tool ecosystems where agents expose capabilities via topics instead of RPC stubs.


## Related Patterns

-   **Multi-Agent:** A2A provides the communication fabric for teams of agents.

-   **Planning:** plans define which messages should be exchanged at each step.

-   **Routing:** directs messages to appropriate agents or topics.

-   **Parallelization:** multiple agents consume the same event and work concurrently.

-   **Reflection:** critique/approval messages form review loops.

-   **Exception Handling and Recovery:** retries, DLQ, and circuit breaking wrap A2A exchanges.

-   **Memory Management:** messages carry references to stored artifacts and context.
