# Leader Election — Resilience & Fault Tolerance Pattern

## Pattern Name and Classification

**Name:** Leader Election  
**Classification:** Resilience / Coordination / High-Availability Control Pattern

---

## Intent

Elect **exactly one** node (the *leader*) from a group of peers to perform a **singleton responsibility** (e.g., scheduling, compaction, partition ownership) while others remain **followers** and **automatically take over** upon failure or demotion of the leader.

---

## Also Known As

-   Master Election / Primary Election
    
-   Coordinator Election
    
-   Singleton Service / Singleton Task
    

---

## Motivation (Forces)

-   **Avoid duplication:** Certain tasks must run **once** cluster-wide (e.g., cron-like jobs, cache warmups, compactions).
    
-   **Failover:** If the current leader fails, **another node** must take over quickly and deterministically.
    
-   **Split brain risks:** Network partitions can create **multiple leaders** unless guarded with fencing/leases/quorum.
    
-   **Simplicity vs. guarantees:** Practical systems need **fast** elections and **bounded staleness**, not global consensus for everything.
    
-   **Heterogeneous environments:** Need to work with K8s, VMs, mixed languages, or managed stores.
    

---

## Applicability

Use Leader Election when:

-   Exactly-one semantics are required for a background/maintenance task.
    
-   Work partitioning requires a **coordinator** (e.g., assign shards to workers).
    
-   The transport is at-least-once and you need a **single publisher** or compactor.
    
-   You can rely on a **shared coordination substrate** (Zookeeper/etcd/Consul, a SQL DB with advisory locks, Redis with Redlock *with caution*).
    

Not a fit when:

-   Each instance can operate **independently** without coordination.
    
-   You require **linearizable** global state for *all* operations—then use a consensus service for that state itself.
    

---

## Structure

-   **Candidates:** Processes willing to be leader.
    
-   **Coordination Store:** Provides primitives (ephemeral nodes + watches, leases, unique locks, compare-and-set).
    
-   **Election Primitive:** E.g., lock with TTL, ephemeral znode, etcd lease, SQL advisory lock.
    
-   **Leadership Lease:** Time-bound right to act; must be renewed (heartbeat).
    
-   **Fencing Token:** Monotonic term/epoch to **prevent old leaders** from acting after a pause.
    
-   **Leader Duty:** The singleton responsibility executed only when holding valid leadership.
    

---

## Participants

-   **Leader:** Currently elected node, holds a lease and executes the duty.
    
-   **Followers:** Compete but stand by; monitor the leader’s state.
    
-   **Coordinator:** Zookeeper/etcd/Consul/SQL providing atomicity & liveness properties.
    
-   **Watchers/Listeners:** Trigger re-elections on changes; may redistribute work.
    

---

## Collaboration

1.  Each candidate **tries to acquire** the election primitive (lock/lease/ephemeral node).
    
2.  Winner becomes **Leader**, stores a **fencing token/term**, and starts heartbeating.
    
3.  Followers **watch** the leader key and re-contend when it expires or is released.
    
4.  If the leader fails or cannot renew, the lease **expires**; a follower becomes leader.
    
5.  Any side-effectful operation validates the **current term/fencing token** to avoid stale leaders acting.
    

---

## Consequences

**Benefits**

-   Ensures **single execution** of critical tasks.
    
-   Enables **automatic failover** without human intervention.
    
-   Simple mental model: “only the leader does X.”
    

**Liabilities**

-   **Split brain** if the substrate doesn’t provide strong-enough primitives or clocks are skewed.
    
-   **Liveness vs safety** trade-offs via lease duration and heartbeat interval.
    
-   Added **operational dependency** (ZK/etcd/DB availability/latency).
    
-   Leaders can become **hotspots**; plan capacity and backpressure.
    

---

## Implementation

### Key Decisions

-   **Substrate choice:**
    
    -   **ZooKeeper/Curator** or **etcd/Consul** (ephemeral nodes + watches, strong semantics).
        
    -   **RDBMS advisory locks** (PostgreSQL `pg_try_advisory_lock`) for simplicity where DB is already HA.
        
    -   **Redis**: be careful; Redlock is debated for safety across partitions—prefer single Redis with `SET NX PX` + fencing via term in a durable store.
        
-   **Lease & heartbeat:** Keep lease **short** enough for fast failover, **long** enough to tolerate hiccups.
    
-   **Fencing:** Store an **ever-increasing term** in durable storage and include it in all leader actions.
    
-   **Preemption policy:** Newer term can **preempt** older leader if both appear alive (rare, but design for it).
    
-   **Observability:** Surface metrics/logs (election count, current term, leadership duration, failovers).
    

### Anti-Patterns

-   Long-running leader tasks **without periodic checks** of leadership/term.
    
-   No fencing token—old leader can continue acting after GC pauses (“**zombie leader**”).
    
-   Depending solely on wall-clock time across nodes.
    
-   Election via **best-effort** cache (no atomicity) or ad-hoc fileshares.
    

---

## Sample Code (Java)

Below are two pragmatic implementations:

### A) PostgreSQL Advisory Lock + Fencing Token (minimal dependencies)

**Idea:** Use `pg_try_advisory_lock` as a cluster-wide mutex. Maintain a **`leadership_term`** table to issue **monotonic fencing tokens**. Leader renews by periodically verifying it still holds the lock; workers validate the token.

```java
// build.gradle (snip)
// implementation 'org.springframework.boot:spring-boot-starter'
// implementation 'org.springframework.boot:spring-boot-starter-jdbc'
// runtimeOnly 'org.postgresql:postgresql'
```

```sql
-- schema.sql
create table if not exists leadership_term (
  name        text primary key,
  term        bigint not null,
  updated_at  timestamptz not null default now()
);
insert into leadership_term(name, term) values ('singleton.scheduler', 0)
  on conflict (name) do nothing;
```

```java
package com.example.leader.pg;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.concurrent.CustomizableThreadFactory;

import java.time.Duration;
import java.util.Objects;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * PostgreSQL-based leader election using advisory locks and fencing tokens.
 */
public final class PgLeaderElector implements AutoCloseable {

  private static final long LOCK_KEY = 0x5EED_1EADL;           // choose a unique 64-bit key per election
  private static final String NAME = "singleton.scheduler";    // election name

  private final JdbcTemplate jdbc;
  private final Duration renewEvery;
  private final Duration dutyTick;
  private final ScheduledExecutorService ses;
  private final AtomicBoolean isLeader = new AtomicBoolean(false);
  private volatile long currentTerm = -1;

  public interface LeaderDuty {
    /** Called periodically while leadership is held. Receive the fencing token (term). */
    void tick(long fencingToken) throws Exception;
  }

  public PgLeaderElector(JdbcTemplate jdbc, Duration renewEvery, Duration dutyTick) {
    this.jdbc = jdbc;
    this.renewEvery = renewEvery;
    this.dutyTick = dutyTick;
    this.ses = Executors.newScheduledThreadPool(2, new CustomizableThreadFactory("pg-leader-"));
  }

  /** Start background election & leadership loop. */
  public void start(LeaderDuty duty) {
    // Election loop: try to acquire lock; if gained, increment term and run duty loop.
    ses.scheduleWithFixedDelay(() -> {
      try {
        if (!isLeader.get()) tryAcquireLeadership();
      } catch (Exception e) {
        // log and retry; do not crash
        e.printStackTrace();
      }
    }, 0, 500, TimeUnit.MILLISECONDS);

    // Duty loop: only runs action if still leader; double-checks lock each tick.
    ses.scheduleWithFixedDelay(() -> {
      if (!isLeader.get()) return;
      try {
        if (!stillHoldsLock()) {
          demote("lock lost");
          return;
        }
        duty.tick(currentTerm);
      } catch (Exception e) {
        // duty failure should not necessarily drop leadership; decide per use case
        e.printStackTrace();
      }
    }, dutyTick.toMillis(), dutyTick.toMillis(), TimeUnit.MILLISECONDS);

    // Renewal loop: keep the session alive and check connectivity
    ses.scheduleWithFixedDelay(() -> {
      if (isLeader.get()) {
        if (!stillHoldsLock()) demote("renewal failed");
      }
    }, renewEvery.toMillis(), renewEvery.toMillis(), TimeUnit.MILLISECONDS);
  }

  private void tryAcquireLeadership() {
    Boolean ok = jdbc.queryForObject("select pg_try_advisory_lock(?)", Boolean.class, LOCK_KEY);
    if (Boolean.TRUE.equals(ok)) {
      // increment fencing term atomically
      Long newTerm = jdbc.queryForObject("""
          update leadership_term
             set term = term + 1, updated_at = now()
           where name = ?
        returning term
        """, Long.class, NAME);
      currentTerm = Objects.requireNonNull(newTerm);
      isLeader.set(true);
      System.out.println("Became leader; term=" + currentTerm);
    }
  }

  private boolean stillHoldsLock() {
    // pg_advisory_lock is session-bound; this checks via try-and-release trick
    Boolean held = jdbc.queryForObject("select pg_try_advisory_lock(?)", Boolean.class, LOCK_KEY);
    if (Boolean.TRUE.equals(held)) {
      // We didn't hold it; we just acquired unexpectedly -> release and report false
      jdbc.update("select pg_advisory_unlock(?)", LOCK_KEY);
      return false;
    }
    return true;
  }

  private void demote(String reason) {
    if (isLeader.compareAndSet(true, false)) {
      System.out.println("Demoted: " + reason + "; term=" + currentTerm);
      // best-effort unlock (if held)
      jdbc.update("select pg_advisory_unlock(?)", LOCK_KEY);
      currentTerm = -1;
    }
  }

  @Override public void close() {
    ses.shutdownNow();
    if (isLeader.get()) jdbc.update("select pg_advisory_unlock(?)", LOCK_KEY);
  }
}
```

```java
// Usage example (e.g., in a Spring @Configuration or @PostConstruct)
PgLeaderElector elector = new PgLeaderElector(jdbcTemplate, Duration.ofSeconds(5), Duration.ofSeconds(2));
elector.start(fencingToken -> {
  // Perform singleton work guarded by fencing token.
  // Include 'fencingToken' with side-effect writes or checks to refuse stale leaders.
  System.out.println("Doing leader work with term " + fencingToken);
});
```

**Notes**

-   The **DB connection** is your “session”; keep it warm. Use a dedicated datasource with reconnect logic.
    
-   For operations that mutate shared state, **persist the fencing token** with the write or validate it server-side.
    

---

### B) ZooKeeper + Apache Curator `LeaderLatch` (classic coordination service)

```java
// build.gradle (snip)
// implementation 'org.apache.curator:curator-recipes:5.6.0'
// implementation 'org.apache.curator:curator-framework:5.6.0'
```

```java
package com.example.leader.zk;

import org.apache.curator.framework.CuratorFramework;
import org.apache.curator.framework.CuratorFrameworkFactory;
import org.apache.curator.framework.recipes.leader.LeaderLatch;
import org.apache.curator.retry.ExponentialBackoffRetry;

import java.io.Closeable;

public final class ZkLeader implements Closeable {
  private final CuratorFramework client;
  private final LeaderLatch latch;
  private final Thread dutyThread;
  private volatile boolean running = true;

  public ZkLeader(String connect, String path, String id, Runnable duty) throws Exception {
    client = CuratorFrameworkFactory.newClient(connect, new ExponentialBackoffRetry(100, 10));
    client.start();
    latch = new LeaderLatch(client, path, id);
    latch.start();

    dutyThread = new Thread(() -> {
      while (running) {
        try {
          latch.await(); // blocks until we're leader
          while (latch.hasLeadership() && running) {
            duty.run();    // do periodic leader work (sleep inside)
          }
        } catch (InterruptedException ie) {
          Thread.currentThread().interrupt();
          break;
        } catch (Exception e) {
          e.printStackTrace();
        }
      }
    }, "zk-leader-duty");
    dutyThread.start();
  }

  @Override public void close() {
    running = false;
    dutyThread.interrupt();
    try { latch.close(); } catch (Exception ignored) {}
    client.close();
  }
}
```

```java
// Usage
ZkLeader leader = new ZkLeader(
  "zk-1:2181,zk-2:2181,zk-3:2181",
  "/elections/scheduler",
  System.getenv().getOrDefault("POD_NAME", "node-"+System.nanoTime()),
  () -> {
    try {
      // singleton task
      System.out.println("I am leader; doing work...");
      Thread.sleep(1500); // duty cadence
    } catch (InterruptedException ignored) { Thread.currentThread().interrupt(); }
  }
);
```

**Notes**

-   Curator uses **ephemeral znodes**; if the process dies or the session expires, leadership is **automatically relinquished**.
    
-   For **fencing**, persist and check a **term** in your business store when performing side effects.
    

---

## Known Uses

-   **Kafka Controller / Partition Leader assignment** (ZK/RAFT, depending on version).
    
-   **HDFS NameNode HA** (Active/Standby with ZKFC fencing).
    
-   **Kubernetes controllers/operators** elect a leader to reconcile CRDs.
    
-   **Elasticsearch master election** (cluster manager).
    
-   **Distributed schedulers** (Airflow/K8s CronJobs operators/Argo) to avoid duplicate runs.
    

---

## Related Patterns

-   **Fencing Token / Monotonic Term:** Prevents **zombie leaders** from acting after lease loss.
    
-   **Bulkhead & Partitioning:** Leaders may coordinate **shard ownership** among workers.
    
-   **Circuit Breaker:** Leader may manage breaker state or reconfiguration.
    
-   **Idempotent Receiver:** Pair with leader changes so repeated actions remain safe.
    
-   **Transactional Outbox:** If the leader publishes events, use outbox to guarantee once-per-change.
    
-   **Service Discovery / Heartbeat:** Followers monitor leader liveness via heartbeats.
    

---

## Implementation Checklist

-   Choose a **coordination substrate** with atomic primitives (ZK/etcd/SQL lock).
    
-   Define **lease/heartbeat intervals** and **timeouts** for desired failover speed.
    
-   Implement **fencing**: monotonic term stored durably and validated on every side effect.
    
-   Ensure leader work **periodically checks** leadership/term and **exits fast** on loss.
    
-   Add **metrics/logging**: current leader id, term, elections count, failover time.
    
-   Test **partition & GC pause** scenarios (chaos tests) to validate safety.
    
-   Document **preemption/hand-over** policy during rolling upgrades.

