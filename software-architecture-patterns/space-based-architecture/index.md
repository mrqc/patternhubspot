# Space-Based Architecture — Software Architecture Pattern

## Pattern Name and Classification

-   **Name:** Space-Based Architecture (SBA)
    
-   **Classification:** Distributed Systems / High-Scalability & Low-Latency / Data-Oriented (In-Memory Data Grid + Collocated Compute)
    

## Intent

Eliminate centralized bottlenecks (databases, message brokers) by moving **state and messaging into a distributed in-memory “space”**, and **collocating processing units** with the data partitions. Scale by **adding partitions/replicas**, not by scaling a single shared store. Persist to the system of record asynchronously (write-behind) and serve traffic from the **space**.

## Also Known As

-   Space-Based Computing
    
-   Tuple Space / Object Space
    
-   In-Memory Data Grid (IMDG) architecture
    
-   RAM Grid / Memory Fabric (e.g., GigaSpaces, Coherence, Hazelcast, Ignite)
    

## Motivation (Forces)

-   **Spiky traffic** (flash crowds, sales campaigns) collapses centralized DBs and queues.
    
-   **Latency sensitivity:** every cross-network hop and disk roundtrip hurts tail latencies.
    
-   **Linear scale-out:** you want throughput to grow with the number of nodes.
    
-   **Fault isolation:** avoid global locks and single points of contention.
    
-   **Graceful degradation:** when the system of record is slow, keep serving from memory and **reconcile later**.
    

SBA addresses these by putting **state + messaging** in a **partitioned, replicated memory grid (“space”)** and running **Processing Units (PUs)** next to their data. External databases become **asynchronous sinks** (write-behind), not the hot path.

## Applicability

Use SBA when:

-   You must handle **unpredictable bursts** with **millisecond-level** response times.
    
-   Workloads can be **partitioned** (by user, tenant, key, order id).
    
-   Reads/writes can be served from **collocated in-memory data** most of the time.
    
-   Eventual consistency to the system of record is acceptable.
    

Be cautious when:

-   You need **cross-partition ACID transactions** and global joins frequently.
    
-   Dataset size far exceeds affordable memory, or strict **durability on commit** is mandatory.
    
-   Complex analytics over the full dataset dominate (consider separate OLAP stores).
    

## Structure

**Logical components**

-   **Space (In-Memory Data Grid):** partitioned, replicated key/value (or object) store; also provides **publish/subscribe**.
    
-   **Processing Unit (PU):** stateless code + local caches **collocated** with a space partition; handles requests/events.
    
-   **Gateway/Load Balancer:** routes requests to the owning partition (consistent hashing / affinity).
    
-   **Persistence Adapter:** **write-through/behind** to the system of record (DB, log, object store).
    
-   **Admin/Orchestrator:** manages partitions, primaries/backups, scaling, failover.
    

```pgsql
Clients
           |
      [Gateway / Router]  -- hash(key) -->
           |                         |                         |
     +-----v-----+            +------v------+            +-----v-----+
     |  PU +     |            |  PU +       |            |  PU +     |
     |  Space P0 |<--replica->|  Space P1   |<--replica->|  Space P2 |
     +-----------+            +-------------+            +-----------+
           |                        |                          |
      write-behind             write-behind               write-behind
           v                        v                          v
        System of Record (DB / Log)  <--- batch / async sync --->
```

## Participants

-   **Space Partition (Primary + Backup):** owns a shard of keys and local event streams.
    
-   **Processing Unit (PU):** business logic bound to a partition; processes collocated data and events.
    
-   **Router:** computes partition from the **affinity key**; supports scatter–gather when needed.
    
-   **Persistence Writer:** batches and flushes changes to durable storage (write-behind).
    
-   **Failover Manager:** promotes backups, rehydrates partitions, rebalances load.
    
-   **Monitoring/Autoscaler:** watches latency/QPS/heap and scales partitions.
    

## Collaboration

1.  Client request carries a **routing key**.
    
2.  **Gateway** routes to the **owning partition**; the PU reads/writes the **local space**.
    
3.  **Events** are published into the partition; subscribers in the same PU react immediately.
    
4.  **Write-behind** process persists mutations asynchronously; **read-through** can hydrate misses from the DB.
    
5.  On failure, **backup** becomes primary; router updates membership; write-behind resumes after replay.
    

## Consequences

**Benefits**

-   **Linear scale-out** by adding partitions; no central DB contention on the hot path.
    
-   **Low latency** via in-memory access and CPU-cache locality.
    
-   **Fault isolation**: failures affect one partition; others keep serving.
    
-   **Elasticity**: autoscale partitions under bursty load.
    
-   **Simple concurrency** within a partition (single-threaded or local locking).
    

**Liabilities**

-   **Memory footprint** and **GC pressure**; requires sizing & tuning.
    
-   **Eventual consistency** to the system of record; needs reconciliation strategies.
    
-   **Cross-partition operations** are harder (scatter–gather, saga).
    
-   **Recovery logic** (replay, rehydration, fencing tokens) adds complexity.
    
-   **Operational tooling** required (ring state, rebalancing, hot/cold backups).
    

## Implementation

### Key Decisions

-   **Affinity key / partitioning:** pick the key that keeps related data and processing together.
    
-   **Replication:** primary-backup per partition (sync vs. async) and promotion policy.
    
-   **Persistence policy:** read-through, write-through, or write-behind; batching size/interval.
    
-   **Consistency envelope:** per-partition serializability vs. global eventual consistency.
    
-   **Routing:** client-side library vs. smart proxy; consistent hashing + virtual nodes.
    
-   **Warmup & rehydration:** snapshots, journal replay, cold vs. warm start.
    

### Design Guidelines

-   Keep PUs **idempotent**; include **versioning** (ETags/sequence numbers) in entries.
    
-   Use **immutable events** and **copy-on-write** entries for safety.
    
-   Prefer **single-threaded** critical sections per partition to avoid lock contention.
    
-   Implement **backpressure** (bounded queues) on event ingestion.
    
-   Add **observability**: partition lag, write-behind queue depth, promotion events, GC, hit/miss.
    
-   Plan **rebalancing** ahead of time; use **virtual nodes** to move only small slices.
    
-   For multi-region: cross-region async replication with **conflict resolution** (CRDTs or last-write-wins with vector clocks).
    

---

## Sample Code (Java 17, single-file demo)

A tiny **space** with:

-   Partitioned in-memory “space” (hash routing by key)
    
-   **Processing Units** attached to each partition that `take` tasks from the space and write results
    
-   A **write-behind** persistence agent that listens for results and “persists” (simulated)
    
-   Collocation: each PU processes tasks on *its own* partition queue
    

> This is an educational sketch, not a framework. Replace with a real IMDG (Hazelcast/Ignite/Coherence) in production.

```java
// SpaceBasedArchitectureDemo.java
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Consumer;

/** Entries that want partition affinity provide a routing key. */
interface HasRoutingKey { String routingKey(); }

/** Task and Result entries stored in the space. */
record Task(String id, String ownerKey, int n) implements HasRoutingKey {
  public String routingKey() { return ownerKey; } // affinity key (e.g., user/tenant)
}
record Result(String taskId, long value, String processedBy) implements HasRoutingKey {
  public String routingKey() { return taskId; } // arbitrary; not used for routing here
}

/** Minimal Space API for this demo. */
interface Space {
  <T> void write(T entry);
  <T> T take(Class<T> type, long timeoutMillis) throws InterruptedException; // removes one matching entry (FIFO)
  <T> void addListener(Class<T> type, Consumer<T> listener);
}

/** A partition-local space backed by typed blocking queues, with simple listeners. */
class InMemorySpace implements Space {
  private final Map<Class<?>, LinkedBlockingQueue<Object>> queues = new ConcurrentHashMap<>();
  private final Map<Class<?>, CopyOnWriteArrayList<Consumer<?>>> listeners = new ConcurrentHashMap<>();
  private final ExecutorService notifyPool = Executors.newCachedThreadPool();

  @Override public <T> void write(T entry) {
    var q = queues.computeIfAbsent(entry.getClass(), k -> new LinkedBlockingQueue<>());
    q.offer(entry);
    // async notify listeners
    var ls = listeners.getOrDefault(entry.getClass(), new CopyOnWriteArrayList<>());
    for (var l : ls) {
      @SuppressWarnings("unchecked") Consumer<T> c = (Consumer<T>) l;
      notifyPool.submit(() -> c.accept(entry));
    }
  }

  @Override public <T> T take(Class<T> type, long timeoutMs) throws InterruptedException {
    var q = queues.computeIfAbsent(type, k -> new LinkedBlockingQueue<>());
    Object o = (timeoutMs <= 0) ? q.take() : q.poll(timeoutMs, TimeUnit.MILLISECONDS);
    return type.cast(o);
  }

  @Override public <T> void addListener(Class<T> type, Consumer<T> listener) {
    listeners.computeIfAbsent(type, k -> new CopyOnWriteArrayList<>()).add(listener);
  }

  public void shutdown() { notifyPool.shutdownNow(); }
}

/** Partitioned "space": routes writes by routing key to a partition's local space. */
class PartitionedSpace {
  private final List<InMemorySpace> partitions;
  public PartitionedSpace(int parts) {
    if (parts <= 0) throw new IllegalArgumentException("parts>0");
    partitions = new ArrayList<>(parts);
    for (int i=0;i<parts;i++) partitions.add(new InMemorySpace());
  }
  public InMemorySpace partition(int idx) { return partitions.get(idx); }
  public List<InMemorySpace> allPartitions() { return partitions; }

  private int route(String key) { return Math.floorMod(key.hashCode(), partitions.size()); }

  public void write(Object entry) {
    if (entry instanceof HasRoutingKey rk) {
      partitions.get(route(rk.routingKey())).write(entry);
    } else {
      // broadcast if no key (rare in SBA; typically everything has affinity)
      for (var p : partitions) p.write(entry);
    }
  }
}

/** Processing Unit: collocated with a partition. Consumes Tasks -> produces Results. */
class ProcessingUnit implements Runnable {
  private final String name;
  private final InMemorySpace localSpace;
  private volatile boolean running = true;

  public ProcessingUnit(String name, InMemorySpace space) {
    this.name = name; this.localSpace = space;
  }

  @Override public void run() {
    try {
      while (running) {
        Task t = localSpace.take(Task.class, 500); // block up to 500ms
        if (t == null) continue; // idle
        long value = fib(t.n()); // “business logic”
        localSpace.write(new Result(t.id(), value, name)); // emit to space
      }
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
    }
  }

  private long fib(int n) { // deliberately simple CPU work
    if (n < 2) return n;
    long a=0,b=1; for (int i=2;i<=n;i++){ long c=a+b; a=b; b=c; }
    return b;
  }

  public void shutdown(){ running = false; }
}

/** Write-behind “persistence”: listens for Results and simulates durable write. */
class PersistenceAgent {
  private final ExecutorService pool = Executors.newSingleThreadExecutor();
  public void attach(InMemorySpace space) {
    space.addListener(Result.class, res -> pool.submit(() -> {
      try { Thread.sleep(10); } catch (InterruptedException ignored) {} // pretend IO
      System.out.println("[Persist] task=" + res.taskId() + " value=" + res.value() + " by " + res.processedBy());
    }));
  }
  public void shutdown(){ pool.shutdownNow(); }
}

/** Demo: 3 partitions, 3 PUs, tasks routed by ownerKey. */
public class SpaceBasedArchitectureDemo {
  public static void main(String[] args) throws Exception {
    int partitions = 3;
    PartitionedSpace ps = new PartitionedSpace(partitions);

    // Collocate a PU per partition
    List<ProcessingUnit> pus = new ArrayList<>();
    List<Thread> threads = new ArrayList<>();
    for (int i=0;i<partitions;i++) {
      ProcessingUnit pu = new ProcessingUnit("PU-" + i, ps.partition(i));
      pus.add(pu);
      Thread t = new Thread(pu, "PU-" + i);
      t.start();
      threads.add(t);
    }

    // Attach write-behind persistence to each partition
    PersistenceAgent persistence = new PersistenceAgent();
    ps.allPartitions().forEach(persistence::attach);

    // Collect results (observer)
    int tasks = 20;
    CountDownLatch done = new CountDownLatch(tasks);
    ps.allPartitions().forEach(p -> p.addListener(Result.class, r -> done.countDown()));

    // Feed tasks (router chooses partition via ownerKey)
    Random rnd = new Random(42);
    for (int i=0;i<tasks;i++) {
      String owner = "user-" + (rnd.nextInt(10)); // affinity key
      ps.write(new Task(UUID.randomUUID().toString(), owner, 25 + rnd.nextInt(5)));
    }

    // Wait for completion or timeout
    if (!done.await(5, TimeUnit.SECONDS)) {
      System.out.println("Timed out waiting for results");
    }

    // Shutdown
    persistence.shutdown();
    pus.forEach(ProcessingUnit::shutdown);
    for (Thread t : threads) t.interrupt();
    ps.allPartitions().forEach(InMemorySpace::shutdown);

    System.out.println("Demo finished.");
  }
}
```

**What this demonstrates**

-   **Routing by affinity key** (`ownerKey`) → tasks land on their owning **partition**.
    
-   **Processing Units** consume from their **local space** (collocation).
    
-   **Publish/subscribe** style events (results) flow through the same space.
    
-   A simple **write-behind** listener “persists” results asynchronously.
    
-   Scaling up = add another partition + PU; no shared DB on the hot path.
    

> Replace the toy space with Hazelcast/Ignite/Coherence (partitioned maps, entry processors, continuous queries) and a real persistence store. Use partition-aware clients and near caches for lowest latency.

## Known Uses

-   **Trading / risk / pricing engines**: collocated positions + pricing, write-behind to the book.
    
-   **E-commerce flash sales**: carts/sessions/orders in the space; DB as sink.
    
-   **Telecom/IoT**: device/session state and counters in grid; streaming analytics as PUs.
    
-   **Ad tech / real-time bidding**: bidder state in memory; logs asynchronously.
    
-   **Gaming backends**: player/session state partitioned by playerId.
    

## Related Patterns

-   **Shared-Nothing / Sharding** — SBA is typically shared-nothing with partitioned memory.
    
-   **CQRS** — queries hit in-memory projections; commands mutate partitioned state.
    
-   **Event-Driven Architecture** — spaces often provide pub/sub/event listeners.
    
-   **Cache-Aside / Read-Through / Write-Behind** — persistence strategies used inside SBA.
    
-   **Actor Model** — similar affinity/ownership idea; actors often map to partitions.
    

---

## Implementation Tips

-   Pick an **affinity key** that keeps hot paths local (e.g., `userId`, `cartId`).
    
-   Collocate compute with data via **entry processors** or **partition-aware executors**.
    
-   Use **virtual partitions** to smooth rebalancing and reduce data movement.
    
-   Tune **GC & heap** (G1/ZGC), prefer **off-heap** where supported; monitor pause times.
    
-   For write-behind, **batch** and **coalesce** updates; add **backpressure** when the sink is slow.
    
-   Test **failover**: backup promotion, fence tokens to avoid split-brain, and **replay** journals.
    
-   Expose **ring state**, **partition load**, and **queue depths** on dashboards; autoscale before saturation.
    
-   Keep cross-partition flows **asynchronous**; when synchronous is unavoidable, use **scatter–gather** with strict timeouts.

