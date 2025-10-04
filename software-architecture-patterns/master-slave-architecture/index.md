# Primary–Replica Architecture (formerly “Master–Slave”) — Software Architecture Pattern

> Note on terminology: The industry has largely moved to **Primary–Replica**, **Leader–Follower**, or **Primary–Secondary** to avoid problematic language while describing the same technical pattern.

## Pattern Name and Classification

-   **Name:** Primary–Replica Architecture (a.k.a. Master–Slave)
    
-   **Classification:** Distributed Systems / Replication & Coordination / Structural
    

## Intent

Separate **authority to accept writes** (the **primary**) from **read-only replicas** (the **replicas**) that **synchronize state** from the primary. The pattern provides **scalability for reads**, **data redundancy**, and a **single ordered source of truth for writes**.

## Also Known As

-   Leader–Follower
    
-   Primary–Secondary
    
-   Master–Replica (legacy term)
    

## Motivation (Forces)

-   **Scalability:** Many workloads are read-heavy; replicating state to followers scales reads horizontally.
    
-   **Consistency vs. Availability:** Centralizing writes simplifies ordering and invariants but can reduce availability during failover.
    
-   **Latency:** Replicas placed near users lower read latency; replication lag creates **eventual consistency** for reads.
    
-   **Simplicity:** A single write authority avoids multi-leader conflict resolution.
    
-   **Recovery:** Replicas provide hot/warm standbys for failover and backups.
    

The pattern balances these by **serializing mutations at the primary**, then **streaming changes** to replicas which serve **fast, scalable reads**.

## Applicability

Use when:

-   Read traffic vastly exceeds write traffic.
    
-   You need straightforward **write ordering** and **conflict-free** updates.
    
-   Read latency should be minimized globally (geo-distributed replicas).
    
-   You want **disaster recovery** via hot standbys.
    

Avoid or adapt when:

-   You need **multi-region write** with low latency → consider **multi-leader** or **CRDTs**.
    
-   You require **strongly consistent reads** immediately after a write for the same client—either route to primary or use **read-your-writes** strategies.
    
-   Primary becomes a bottleneck due to very high write rates.
    

## Structure

-   **Primary (Leader):** Accepts all writes; defines the serialization order; emits a **replication log/stream**.
    
-   **Replicas (Followers):** Apply the primary’s log; serve **read-only** queries; optionally take over on failover.
    
-   **Replication Channel:** Physical/logical (change stream, WAL shipping, event log) with at-least-once semantics.
    
-   **Failover Coordinator:** Detects primary failure; promotes a replica (manual or automatic).
    
-   **Client Router:** Routes **writes → primary**, **reads → replicas**; may support **stickiness** for read-your-writes.
    

```pgsql
writes                    replication
Clients  ---------------->  Primary  ==================>  Replica 1
   |                         (log)                          |   ^
   |------ reads ---------->                                |   |
   |------------------------------------------------------> Replica 2
```

## Participants

-   **Primary Node** — authoritative state; mutation API; replication publisher.
    
-   **Replica Node** — read API; replication applier; candidate for promotion.
    
-   **Replication Manager** — transport, offsets, backpressure, retries.
    
-   **Failover/Health Monitor** — leader election or orchestration (e.g., Raft/ZK/consensus or cloud managed).
    
-   **Client Router/Driver** — read/write splitting, stickiness, fallback.
    

## Collaboration

1.  Client sends **write** to **primary** → primary validates & writes → appends to replication log.
    
2.  Replicas **pull/push** log entries → apply in order → expose updated state for reads.
    
3.  Clients send **reads** to replicas; **read-your-writes** can pin a user/session to primary or wait for replica version ≥ write version.
    
4.  On primary failure, **failover** promotes a healthy replica, updates routing, resumes replication from new primary.
    

## Consequences

**Benefits**

-   **Read scalability** and lower read latency via replicas.
    
-   **Simpler write path** with clear ordering and invariants.
    
-   **High availability** with replica promotion and backups.
    
-   **Operational clarity** (one authoritative source for writes).
    

**Liabilities**

-   **Replication lag** → stale reads; need strategies for consistency-sensitive operations.
    
-   **Primary hotspot** for heavy writes; vertical scaling or sharding may be needed.
    
-   **Failover complexity** (split-brain prevention, fencing tokens).
    
-   **Operational overhead** (monitoring lag, backpressure, re-seeding replicas).
    

## Implementation

### Key Decisions

-   **Replication mode:** synchronous (lower RPO, higher latency) vs. asynchronous (better latency, possible data loss on failover).
    
-   **Consistency policy:** strong on primary; eventual/monotonic on replicas; support **session** or **timeline** guarantees if needed.
    
-   **Routing:** driver-side read/write split, proxy/gateway, or app logic.
    
-   **Failover:** manual, orchestrated (Sentinel/Pacemaker/Operator), or consensus (Raft-based leaders).
    
-   **Schema & versioning:** compatible changes across primary/replicas; snapshot + incremental log.
    
-   **Safety:** fencing/tokens during promotion to prevent split-brain; idempotent replication.
    

### Operational Guidelines

-   Track **replication lag** and **apply throughput**; alarm on thresholds.
    
-   Provide **read-after-write** options:
    
    -   sticky reads to primary for a time window,
        
    -   version-based reads (wait until replica ≥ version),
        
    -   per-user session affinity.
        
-   Snapshot & seed new replicas; support **catch-up** from checkpoints.
    
-   Test failover regularly; document **RPO/RTO**.
    
-   For multi-tenant or massive scale, combine with **sharding** (primary–replica per shard).
    

---

## Sample Code (Java)

A minimal, framework-free simulation of **Primary–Replica** with:

-   A **Primary** that applies writes and publishes a change log
    
-   **Replicas** that apply the log asynchronously
    
-   A **Router** that sends writes to the primary and reads to replicas
    
-   A simple **read-your-writes** option via “stick to primary” flag
    

> Java 17; uses in-memory queues to model replication.

```java
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;

/** Change event representing a mutation applied at the primary. */
record Change(long seq, String key, String value) {}

/** Primary node: owns the authoritative map and emits a log of changes. */
class Primary {
  private final Map<String, String> store = new ConcurrentHashMap<>();
  private final BlockingQueue<Change> log = new LinkedBlockingQueue<>();
  private final AtomicLong seq = new AtomicLong(0);

  public long put(String key, String value) {
    store.put(key, value);
    long s = seq.incrementAndGet();
    log.add(new Change(s, key, value));
    return s; // return sequence for read-your-writes
  }

  public Optional<String> get(String key) { return Optional.ofNullable(store.get(key)); }
  public BlockingQueue<Change> log() { return log; }
}

/** Replica node: applies changes from primary log and serves reads. */
class Replica implements AutoCloseable {
  private final Map<String, String> local = new ConcurrentHashMap<>();
  private final String name;
  private final ExecutorService es = Executors.newSingleThreadExecutor();
  private volatile long appliedSeq = 0;
  private volatile boolean running = true;

  public Replica(String name, BlockingQueue<Change> sourceLog) {
    this.name = name;
    es.submit(() -> {
      while (running) {
        Change c = sourceLog.take(); // blocking take (simulates streaming)
        // Simulate network/processing delay
        Thread.sleep(20);
        local.put(c.key(), c.value());
        appliedSeq = c.seq();
      }
    });
  }

  public Optional<String> get(String key) { return Optional.ofNullable(local.get(key)); }
  public long appliedSeq() { return appliedSeq; }
  public String name() { return name; }

  @Override public void close() { running = false; es.shutdownNow(); }
}

/** Router that implements read/write splitting and optional read-your-writes. */
class ClientRouter {
  private final Primary primary;
  private final List<Replica> replicas;
  private final AtomicLong rr = new AtomicLong();

  public ClientRouter(Primary primary, List<Replica> replicas) {
    this.primary = primary; this.replicas = replicas;
  }

  /** Write to primary; returns the change sequence for consistency coordination. */
  public long write(String key, String value) { return primary.put(key, value); }

  /** Read method with two modes: stickToPrimary for strong reads; else go to a replica. */
  public Optional<String> read(String key, boolean stickToPrimary) {
    if (stickToPrimary || replicas.isEmpty()) return primary.get(key);
    // naive round-robin replica
    int idx = (int) (rr.getAndIncrement() % replicas.size());
    return replicas.get(idx).get(key);
  }

  /** Wait until any replica has applied at least the given sequence (basic read-your-writes). */
  public void waitUntilReplicated(long seq, long timeoutMs) throws InterruptedException, TimeoutException {
    long start = System.currentTimeMillis();
    while (true) {
      for (Replica r : replicas) if (r.appliedSeq() >= seq) return;
      if (System.currentTimeMillis() - start > timeoutMs) throw new TimeoutException("lag too high");
      Thread.sleep(10);
    }
  }
}

/** Demo */
public class PrimaryReplicaDemo {
  public static void main(String[] args) throws Exception {
    Primary primary = new Primary();
    Replica r1 = new Replica("replica-1", primary.log());
    Replica r2 = new Replica("replica-2", primary.log());
    ClientRouter router = new ClientRouter(primary, List.of(r1, r2));

    // Write and read from replicas (may be stale initially)
    long seq = router.write("user:42:name", "Alice");
    System.out.println("Replica read (may be stale): " + router.read("user:42:name", false));

    // Ensure read-your-writes by waiting for replication or by sticking to primary
    router.waitUntilReplicated(seq, 1000);
    System.out.println("Replica read (after catch-up): " + router.read("user:42:name", false));

    // Strong read by sticking to primary
    router.write("user:42:name", "Alice B.");
    System.out.println("Primary read (strong): " + router.read("user:42:name", true));

    r1.close(); r2.close();
  }
}
```

**What this demonstrates**

-   **Writes** serialize on the **primary** and yield a **sequence number**.
    
-   **Replicas** asynchronously apply changes; reads may observe lag.
    
-   **Read-your-writes** can be achieved by **stickiness** or **waiting for sequence**.
    

> Productionizing: replace in-memory queues with a **replication log** (WAL shipping, Kafka, Raft log), add **health checks**, **promotion with fencing tokens**, **quorum decisions** for leader election, and **observability** around lag and throughput.

## Known Uses

-   **Relational databases:** PostgreSQL/MySQL primary–replica, Oracle Data Guard.
    
-   **Search & caches:** Elasticsearch primaries with replicas; Redis primary–replica.
    
-   **Message brokers:** Kafka partition leaders and followers (replicas).
    
-   **File/object stores:** HDFS NameNode/JournalNodes; Ceph RADOS (leader per placement group).
    
-   **Microservices:** API with read replicas behind a read/write-splitting router.
    

## Related Patterns

-   **Single-Writer Principle** — one authority for mutations.
    
-   **Sharding** — partitioned data with a primary–replica set per shard.
    
-   **Multi-Leader Replication** — multiple writable leaders (conflict resolution required).
    
-   **Event Sourcing** — log as source of truth (leaders append, followers replay).
    
-   **Circuit Breaker / Bulkhead** — protect primary and replicas from overload.
    
-   **Broker Architecture** — can carry the replication stream/events.
    

---

## Implementation Tips

-   Choose **sync vs. async replication** per data criticality (RPO vs. latency).
    
-   Expose **replication metrics**: lag (time/ops), apply rate, queue depth.
    
-   Enforce **fencing** on promotion (epoch/term number) to avoid split-brain.
    
-   Use **idempotent apply** and **replay-safe** logs for catch-up.
    
-   Implement **routing policies**: stale-reads allowed, session stickiness, version-aware reads.
    
-   Regularly **drill failovers** and document operational runbooks.
    
-   Combine with **sharding** when the primary’s write throughput becomes the bottleneck.

