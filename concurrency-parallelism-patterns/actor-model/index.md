# Concurrency / Parallelism Pattern — Actor Model

## Pattern Name and Classification

-   **Name:** Actor Model

-   **Classification:** Concurrency & distribution pattern (message-driven, share-nothing, asynchronous)


## Intent

Model computation as a set of **actors**—independent entities that communicate by **asynchronous message passing**. Each actor:

1.  processes one message at a time,

2.  can send messages to other actors,

3.  can create new actors, and

4.  can change its own behavior (state) for the next message.


## Also Known As

-   Message-Driven Concurrency

-   Share-Nothing Concurrency

-   Mailbox/Inbox Pattern


## Motivation (Forces)

-   **Avoid shared mutable state:** eliminate locks by isolating state inside actors.

-   **Scalability:** natural parallelism; actors map well to threads/cores and to distributed nodes.

-   **Fault isolation:** failures are contained and managed by **supervision** (restart/stop/ escalate).

-   **Elasticity:** actors are lightweight; can be created on demand and routed across machines.

-   **Backpressure:** mailboxes and routers can throttle or shed load.

-   **Trade-offs:** message reordering, at-least-once semantics, distributed debugging, and the need for explicit protocols.


## Applicability

Use the Actor Model when:

-   You have many **independent, stateful** components that must run concurrently.

-   You need **high throughput** with low coordination overhead.

-   You want **failure containment** and **supervision** semantics.

-   You target **distributed** deployments (location transparency).


Avoid/Adapt when:

-   You require strict **global ordering**/transactions across many entities.

-   Latency budgets can’t tolerate queue hops.

-   Work is primarily synchronous, CPU-bound, and better handled by a fork-join pool.


## Structure

```css
+--------------+          async messages          +--------------+
Caller ─►  ActorRef A  ├──────────────────────────────────►  ActorRef B  ─► ...
        +--------------+                                   +--------------+
               │                                                   │
        [Mailbox (FIFO-ish, per actor)]                    [Mailbox]
               │                                                   │
        [Dispatcher/Executor] ──► invokes Actor behavior (single-threaded per actor)
```

## Participants

-   **Actor:** Encapsulated state + behavior; processes one message at a time.

-   **ActorRef:** The address/handle used to send messages (never exposes actor state).

-   **Mailbox:** Thread-safe queue receiving messages for an actor.

-   **Dispatcher/Executor:** Runs actors; ensures single-threaded processing per actor.

-   **Supervisor:** Parent actor that decides **restart/stop/escalate** on child failure.

-   **Router (optional):** Distributes messages across actor pool (round-robin/consistent-hash).


## Collaboration

1.  A sender posts a message to an **ActorRef** (fire-and-forget) or uses **ask** to obtain a future.

2.  The **Dispatcher** pulls from the actor’s **Mailbox** and invokes its behavior.

3.  The actor updates private state, sends messages, spawns children, or replies.

4.  Exceptions bubble to the **Supervisor** which applies a strategy (restart/stop).

5.  Scaling is achieved by adding actors and/or routing messages across nodes.


## Consequences

**Benefits**

-   Simpler reasoning about concurrency; no shared locks.

-   High throughput; natural parallelism.

-   Failure isolation via supervision trees.

-   Location transparency (in-JVM, inter-JVM, or remote).


**Liabilities / Trade-offs**

-   Message delivery is usually **at-least-once** (or best-effort); you must design **idempotent** handlers.

-   No implicit ordering across actors; only **per-mailbox** order (often FIFO).

-   Backpressure & overload need explicit handling (bounded mailboxes, drop strategies).

-   Protocol design and debugging distributed flows add complexity.


## Implementation (Key Points)

-   **One mailbox per actor**; strictly serialize processing for that actor.

-   **Bound mailboxes**; define policy when full (drop/backoff/fail).

-   **Ask pattern:** implement request/response via `CompletableFuture` with timeouts.

-   **Supervision:** on exception, **restart** (= replace behavior/state), **stop**, or **escalate**.

-   **Routers:** for hot paths, pool actors and round-robin based on key (consistent hash for affinity).

-   **Persistence:** for critical state, persist events (event sourcing) or snapshots.

-   **Observability:** track mailbox depth, throughput, processing time, dead letters.

-   **Distribution:** keep protocol serializable; abstract `ActorRef` so local/remote look identical.


---

## Sample Code (Java 17): Minimal Actor System (local, single JVM)

> Features:
>
> -   `ActorRef.tell()` (fire-and-forget) and `ask()` (future reply)
>
> -   Single-threaded processing per actor (no shared locks)
>
> -   Bounded mailbox with backpressure
>
> -   Simple **supervision** (restart on failure)
>
> -   Example `CounterActor` with `Inc`, `Get` messages
>

```java
// File: MiniActorSystem.java
// Compile: javac MiniActorSystem.java
// Run:     java MiniActorSystem
import java.time.Duration;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Supplier;

/** ===== Core API ===== */
interface Actor {
    void onReceive(ActorContext ctx, Object msg) throws Exception;
    default void preStart(ActorContext ctx) throws Exception {}
    default void postStop(ActorContext ctx) throws Exception {}
}

final class ActorRef {
    private final String id;
    private final MiniActorSystem sys;
    ActorRef(String id, MiniActorSystem sys) { this.id = id; this.sys = sys; }
    public void tell(Object msg, ActorRef sender) { sys.enqueue(id, Envelope.of(msg, sender, null)); }
    public CompletableFuture<Object> ask(Object msg, Duration timeout) {
        CompletableFuture<Object> reply = new CompletableFuture<>();
        sys.enqueue(id, Envelope.of(msg, sys.deadLetters(), reply));
        return reply.orTimeout(timeout.toMillis(), TimeUnit.MILLISECONDS);
    }
    public String path() { return id; }
    @Override public String toString() { return "ActorRef(" + id + ")"; }
}

final class ActorContext {
    private final MiniActorSystem sys;
    private final ActorRef self;
    private final ActorRef sender;
    ActorContext(MiniActorSystem sys, ActorRef self, ActorRef sender) { this.sys = sys; this.self = self; this.sender = sender; }
    public ActorRef self()   { return self; }
    public ActorRef sender() { return sender; }
    public ActorRef spawn(Supplier<Actor> props) { return sys.spawn(props); }
    public void stop(ActorRef ref) { sys.stop(ref); }
    public void reply(Object value) { sys.replyToCurrent(value); }
}

/** ===== System internals ===== */
final class Envelope {
    final Object msg;
    final ActorRef sender;
    final CompletableFuture<Object> replyTo; // null for tell
    Envelope(Object msg, ActorRef sender, CompletableFuture<Object> replyTo) {
        this.msg = msg; this.sender = sender; this.replyTo = replyTo;
    }
    static Envelope of(Object msg, ActorRef sender, CompletableFuture<Object> reply) { return new Envelope(msg, sender, reply); }
}

final class MiniActorSystem implements AutoCloseable {
    private static final class Cell {
        final ActorRef ref;
        final Supplier<Actor> factory;
        volatile Actor instance;
        final BlockingQueue<Envelope> mailbox;
        final AtomicBoolean running = new AtomicBoolean(true);
        Cell(ActorRef ref, Supplier<Actor> factory, int mailboxCapacity) {
            this.ref = ref; this.factory = factory;
            this.instance = factory.get();
            this.mailbox = new ArrayBlockingQueue<>(mailboxCapacity);
        }
    }

    private final Map<String, Cell> cells = new ConcurrentHashMap<>();
    private final ExecutorService dispatcher;
    private final ThreadLocal<Envelope> currentEnvelope = new ThreadLocal<>();
    private final ActorRef deadLetters = new ActorRef("deadLetters", this);
    private final int mailboxCapacity;

    public MiniActorSystem(int threads, int mailboxCapacity) {
        this.dispatcher = Executors.newFixedThreadPool(threads);
        this.mailboxCapacity = mailboxCapacity;
    }

    public ActorRef spawn(Supplier<Actor> props) {
        String id = "user/" + UUID.randomUUID();
        ActorRef ref = new ActorRef(id, this);
        Cell cell = new Cell(ref, props, mailboxCapacity);
        cells.put(id, cell);
        safeInvoke(cell, a -> a.preStart(new ActorContext(this, ref, deadLetters)));
        schedule(cell);
        return ref;
    }

    public void stop(ActorRef ref) {
        Cell cell = cells.get(ref.path());
        if (cell != null && cell.running.compareAndSet(true, false)) {
            safeInvoke(cell, a -> a.postStop(new ActorContext(this, ref, deadLetters)));
            cells.remove(ref.path());
        }
    }

    public ActorRef deadLetters() { return deadLetters; }

    void enqueue(String id, Envelope env) {
        Cell cell = cells.get(id);
        if (cell == null || !cell.running.get()) {
            if (env.replyTo != null) env.replyTo.completeExceptionally(new CancellationException("dead letter"));
            return;
        }
        // backpressure: offer with timeout; on failure, fail fast
        try {
            if (!cell.mailbox.offer(env, 100, TimeUnit.MILLISECONDS)) {
                if (env.replyTo != null) env.replyTo.completeExceptionally(new RejectedExecutionException("mailbox full"));
            }
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
            if (env.replyTo != null) env.replyTo.completeExceptionally(ie);
        }
    }

    private void schedule(Cell cell) {
        dispatcher.submit(() -> {
            while (cell.running.get()) {
                Envelope env = null;
                try {
                    env = cell.mailbox.poll(200, TimeUnit.MILLISECONDS);
                    if (env == null) continue;
                    currentEnvelope.set(env);
                    ActorContext ctx = new ActorContext(this, cell.ref, env.sender);
                    cell.instance.onReceive(ctx, env.msg);
                    // complete ask if handler called reply()
                    if (env.replyTo != null && !env.replyTo.isDone()) {
                        env.replyTo.complete(null); // no explicit reply given
                    }
                } catch (Throwable t) {
                    // supervision: restart actor (simple strategy)
                    if (env != null && env.replyTo != null) env.replyTo.completeExceptionally(t);
                    try {
                        safeInvoke(cell, a -> a.postStop(new ActorContext(this, cell.ref, deadLetters)));
                    } catch (Exception ignored) {}
                    cell.instance = cell.factory.get(); // restart with fresh state
                    safeInvoke(cell, a -> a.preStart(new ActorContext(this, cell.ref, deadLetters)));
                } finally {
                    currentEnvelope.remove();
                }
            }
        });
    }

    void replyToCurrent(Object value) {
        Envelope env = currentEnvelope.get();
        if (env != null && env.replyTo != null && !env.replyTo.isDone()) {
            env.replyTo.complete(value);
        }
    }

    private static void safeInvoke(Cell cell, ThrowingConsumer<Actor> c) {
        try { c.accept(cell.instance); } catch (Exception ignored) {}
    }

    @FunctionalInterface interface ThrowingConsumer<T> { void accept(T t) throws Exception; }

    @Override public void close() {
        cells.values().forEach(c -> c.running.set(false));
        dispatcher.shutdown();
        try { dispatcher.awaitTermination(2, TimeUnit.SECONDS); } catch (InterruptedException ignored) { }
    }
}

/** ===== Example: Counter actor & messages ===== */
final class CounterActor implements Actor {
    private int n = 0;
    public record Inc(int by) {}
    public enum Get { INSTANCE }

    @Override public void onReceive(ActorContext ctx, Object msg) throws Exception {
        if (msg instanceof Inc m) {
            n += m.by;
        } else if (msg == Get.INSTANCE) {
            ctx.reply(n); // fulfill ask() future with current value
        } else if (msg instanceof String s && s.equals("boom")) {
            throw new RuntimeException("simulated failure"); // triggers restart
        }
    }

    @Override public void preStart(ActorContext ctx) { /* init */ }
    @Override public void postStop(ActorContext ctx) { /* cleanup */ }
}

/** ===== Demo ===== */
public class MiniActorSystem {
    public static void main(String[] args) throws Exception {
        try (var system = new MiniActorSystem(threads(2), 1024)) {
            ActorRef counter = system.spawn(CounterActor::new);

            // Fire-and-forget
            for (int i = 0; i < 5; i++) counter.tell(new CounterActor.Inc(2), system.deadLetters());

            // Ask pattern with timeout
            Object v1 = counter.ask(CounterActor.Get.INSTANCE, Duration.ofMillis(500)).join();
            System.out.println("count = " + v1); // expect 10

            // Supervision demo: force a failure, then continue
            counter.tell("boom", system.deadLetters());
            // After restart, state is reset to 0 (simple strategy)
            Object v2 = counter.ask(CounterActor.Get.INSTANCE, Duration.ofMillis(500)).join();
            System.out.println("after restart, count = " + v2);

            // Backpressure test: rapid increments
            for (int i = 0; i < 100; i++) counter.tell(new CounterActor.Inc(1), system.deadLetters());
            System.out.println("final = " + counter.ask(CounterActor.Get.INSTANCE, Duration.ofSeconds(1)).join());
        }
    }
    private static int threads(int n) { return Math.max(1, n); }
}
```

**What the example shows**

-   **ActorRef** hides location/state; callers use `tell` (fire-and-forget) or `ask` (future with timeout).

-   Each actor has a **bounded mailbox**; messages are processed **one at a time**.

-   **Supervision strategy**: simple restart on exception (state reset).

-   Shut down cleanly by closing the system (executor termination).


---

## Known Uses

-   **Akka / Akka Typed (JVM):** Production actor toolkit (local & clustered).

-   **Erlang/Elixir (BEAM VM):** Classic actor-based runtimes with robust supervision.

-   **Orleans (Microsoft .NET):** Virtual actors for cloud services.

-   **Ray / Dapr building blocks:** Actor-like components for distributed apps and microservices.

-   **IoT & Telecom:** Massive numbers of independent stateful endpoints.


## Related Patterns

-   **Active Object:** Similar single-threaded processing with a queue; Actor adds **location transparency** and **supervision trees**.

-   **Reactor / Proactor:** I/O event demultiplexing; actors often sit atop Reactor.

-   **Supervisor Tree:** Organization of failure handling in actor systems.

-   **Message Queue / Pub-Sub:** Transport substrate; actors are the endpoints/consumers.

-   **Saga / Process Manager:** Actor-style coordination of long-running workflows.


---

### Practical Tips

-   Keep messages **small, immutable, serializable**; version message schemas for evolution.

-   **Bound every mailbox** and monitor depth; define behavior on overflow (drop, dead letters, backoff).

-   Use **keyed routers** to shard hot entities across actor instances.

-   Design **idempotent** handlers or use **deduplication** when delivery can repeat.

-   Add **metrics** (mailbox size, processing time, failures) and **tracing** (propagate trace IDs in messages).

-   For distribution, abstract transport so `ActorRef` can point to local or remote actors without changing user code.
