# Leader Election — Cloud Distributed Systems Pattern

## Pattern Name and Classification

-   **Name:** Leader Election

-   **Classification:** Coordination / Availability / Consistency pattern for distributed systems


## Intent

Select exactly one **active leader** from a group of cooperating nodes to perform *singleton* work (e.g., scheduling, partition ownership, metadata updates) while allowing **fast failover** to a new leader when the current one becomes unavailable.

## Also Known As

-   Master Election / Primary Election

-   Coordinator Election

-   Singleton Service (clustered)


## Motivation (Forces)

You have multiple instances for availability and scale, but some tasks **must be performed by one node at a time** to avoid duplication or conflicting writes (e.g., compaction, cron-like jobs, partition rebalancing, writing to a single-writer store).

Forces you must balance:

-   **Safety:** Never have two leaders at once (avoid split-brain).

-   **Liveness:** Always have *some* leader when a quorum of nodes is healthy.

-   **Failure detection:** Distinguish slow from dead nodes (timeouts, leases, heartbeats).

-   **Partition tolerance:** Handle network partitions without corrupting state.

-   **Performance:** Keep election overhead low; leaders shouldn’t hold heavyweight global locks longer than necessary.

-   **Simplicity vs. rigor:** A DB-backed lock may be simple, while a consensus-backed lease (Raft/Paxos) is safer under partitions.

-   **Operational reality:** Nodes crash, clocks drift, GC pauses happen, containers get rescheduled; elections must tolerate all of it.


## Applicability

Use this pattern when:

-   Exactly one instance should run a *singleton* process (scheduler, job runner, compactor, cache warmer).

-   A cluster component must own *coordination state* (e.g., controller/metadata manager).

-   You need **automatic failover** without a human in the loop.

-   You can rely on a **shared coordination substrate** (ZooKeeper/etcd/Consul/K8s Lease, or a relational DB).


Avoid or be cautious when:

-   Your task can be fully **sharded** with idempotency (then prefer partition ownership/sharding).

-   **Split-brain** has severe cost and you don’t have a strong coordinator (then use a consensus system with fencing).


## Structure

-   **Participants (nodes/workers):** Symmetric peers attempting to become leader.

-   **Coordinator store:** Provides *atomic* create/update/delete with TTL/lease semantics and *watch/notification* (e.g., ZooKeeper ephemeral znode, etcd Lease, Consul Session, Kubernetes Lease object) **or** a DB lock with fencing tokens.

-   **Lease/Lock:** Represents leadership and expires automatically if the holder dies (ephemeral) or must be renewed periodically (lease).

-   **Callbacks/Observers:** Notify losers to wait; notify followers when leadership changes.


## Participants

-   **Candidate:** A node that tries to acquire leadership.

-   **Leader:** The node that currently holds the lease/lock and runs singleton tasks.

-   **Followers:** Non-leaders; they watch the lease and remain on standby.

-   **Coordination Backend:** ZooKeeper/etcd/Consul/K8s API/DB guaranteeing atomicity and (ideally) linearizable reads/writes.


## Collaboration

1.  Each candidate attempts to **acquire** a leadership lease/lock.

2.  Exactly one succeeds → becomes **Leader** and **renews** the lease periodically (heartbeats).

3.  Followers **watch** the lease; when it’s lost/expired, they **contend** again.

4.  On leader crash or partition, lease **expires** (or session drops) → new leader is elected.

5.  Optional: Use **fencing tokens** (monotonic numbers) to prevent an old, paused leader from writing after a new leader is elected.


## Consequences

**Benefits**

-   **High availability** of singleton responsibilities with automatic failover.

-   **Simplicity** relative to full consensus for all writes (only the leadership is coordinated).

-   **Operational decoupling:** Followers remain hot-standby.


**Liabilities**

-   **Split-brain risk** if you rely on weak coordination (e.g., DB lock without fencing) or long GC pauses.

-   **Liveness dependency** on the coordination backend (it’s a critical component).

-   **Clock/timeout tuning:** Too short → flapping; too long → slow failover.

-   **Throughput bottleneck** if the leader becomes hot; consider sharding or multiple independent elections.


## Implementation

**Key decisions**

-   **Backend choice:**

    -   *ZooKeeper/Curator*, *etcd*, *Consul*, *Kubernetes Lease*, or *RDBMS locks*.

-   **Lease semantics:** Prefer **ephemeral + TTL** or **renewed leases** with clear timeouts.

-   **Fencing tokens:** If leaders interact with external systems that don’t observe the same linearizable store, attach a monotonically increasing token to every leader action and **reject stale tokens** downstream.

-   **Backoff & jitter:** Randomize retries to avoid thundering herds.

-   **Health checks:** Only keep leadership while healthy; relinquish on degraded state.

-   **Observability:** Emit metrics/events for leadership transitions, lease latencies, renew failures.


**Typical pitfalls**

-   Holding leadership while the process is **hung** (stop-the-world GC, long IO). Renewals must fail fast; watchers must detect session loss.

-   **Clock skew** if lease renewal/expiry uses local time (prefer server-side TTLs).

-   **Non-idempotent** leader actions (always design as idempotent, or protect with tokens).

-   Forgetting to **gracefully step down** on SIGTERM during rolling updates.


---

## Sample Code (Java)

### A. Curator (ZooKeeper) Leader Election — simple and battle-tested

```java
import org.apache.curator.framework.CuratorFramework;
import org.apache.curator.framework.CuratorFrameworkFactory;
import org.apache.curator.retry.ExponentialBackoffRetry;
import org.apache.curator.framework.recipes.leader.LeaderLatch;

import java.io.Closeable;
import java.io.IOException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class CuratorLeaderExample implements Closeable {

    private final CuratorFramework client;
    private final LeaderLatch leaderLatch;
    private final ExecutorService leaderExecutor = Executors.newSingleThreadExecutor();

    public CuratorLeaderExample(String zkConnect, String latchPath, String nodeId) throws Exception {
        this.client = CuratorFrameworkFactory.builder()
                .connectString(zkConnect)
                .retryPolicy(new ExponentialBackoffRetry(200, 5))
                .sessionTimeoutMs(15_000)
                .connectionTimeoutMs(5_000)
                .build();
        client.start();

        this.leaderLatch = new LeaderLatch(client, latchPath, nodeId);
        this.leaderLatch.addListener(() -> {
            if (leaderLatch.hasLeadership()) {
                onElectedLeader();
            } else {
                onRevokedLeadership();
            }
        });
        this.leaderLatch.start(); // participates immediately
    }

    private void onElectedLeader() {
        System.out.println("🎉 Became leader. Starting singleton work.");
        leaderExecutor.submit(this::runSingletonLoop);
    }

    private void onRevokedLeadership() {
        System.out.println("⚠️ Leadership revoked. Stopping singleton work.");
        leaderExecutor.shutdownNow();
    }

    private void runSingletonLoop() {
        try {
            while (!Thread.currentThread().isInterrupted()) {
                // Do idempotent work guarded by leadership
                doScheduledWorkWithFencing();
                Thread.sleep(5_000);
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    // Example of attaching a fencing token stored in ZooKeeper (or elsewhere)
    private void doScheduledWorkWithFencing() {
        // Fetch monotonic fencing token from a ZK node or separate counter service.
        // For brevity, we just print; in real code, include the token in downstream writes.
        System.out.println("Running leader-only task with fencing token...");
    }

    @Override
    public void close() throws IOException {
        try {
            leaderLatch.close();
        } catch (IOException ignored) {}
        client.close();
        leaderExecutor.shutdownNow();
    }

    public static void main(String[] args) throws Exception {
        String zk = System.getenv().getOrDefault("ZK_CONNECT", "localhost:2181");
        try (CuratorLeaderExample app =
                     new CuratorLeaderExample(zk, "/app/leader-latch", System.getenv().getOrDefault("NODE_ID", "node-" + System.nanoTime()))) {
            Thread.currentThread().join(); // keep running
        }
    }
}
```

**Notes**

-   `LeaderLatch` creates an **ephemeral** znode; if the process dies or the session drops, leadership is automatically released.

-   For long-running tasks, ensure **idempotency** and consider **fencing tokens** if the task writes to systems that cannot consult ZooKeeper.


---

### B. PostgreSQL Advisory Lock + Fencing (no extra infrastructure)

Good when you already have Postgres and the risk profile is acceptable. Use **advisory locks** for mutual exclusion **and** add a **fencing token** table to prevent split-brain effects from long STW pauses.

```java
import java.sql.*;
import java.time.Instant;
import java.util.concurrent.TimeUnit;

public class PostgresLeader implements AutoCloseable {

    private final Connection conn;
    private final long lockKey; // choose a stable 64-bit key per "election group"
    private volatile boolean leader = false;
    private volatile long fencingToken = -1;

    public PostgresLeader(String jdbcUrl, String user, String pwd, long lockKey) throws Exception {
        this.conn = DriverManager.getConnection(jdbcUrl, user, pwd);
        this.conn.setAutoCommit(true);
        this.lockKey = lockKey;
        initSchema();
    }

    private void initSchema() throws SQLException {
        try (Statement st = conn.createStatement()) {
            st.execute("""
                create table if not exists leadership_fence (
                  id int primary key default 1,
                  token bigint not null,
                  updated_at timestamptz not null
                );
                insert into leadership_fence(id, token, updated_at)
                values (1, 0, now())
                on conflict (id) do nothing;
            """);
        }
    }

    public void run() throws Exception {
        while (true) {
            if (!leader) {
                tryAcquire();
            } else {
                renewAndDoWork();
            }
            TimeUnit.SECONDS.sleep(2);
        }
    }

    private void tryAcquire() {
        try (PreparedStatement ps = conn.prepareStatement("select pg_try_advisory_lock(?)")) {
            ps.setLong(1, lockKey);
            try (ResultSet rs = ps.executeQuery()) {
                if (rs.next() && rs.getBoolean(1)) {
                    leader = true;
                    // increment fencing token atomically
                    try (Statement st = conn.createStatement();
                         ResultSet r = st.executeQuery("update leadership_fence set token = token + 1, updated_at = now() where id = 1 returning token")) {
                        if (r.next()) fencingToken = r.getLong(1);
                    }
                    System.out.println("🎉 Acquired leadership with fencing token " + fencingToken);
                }
            }
        } catch (SQLException e) {
            e.printStackTrace();
            leader = false;
        }
    }

    private void renewAndDoWork() {
        try {
            // Verify we still hold the lock
            if (!stillHoldsLock()) {
                System.out.println("⚠️ Lost advisory lock; stepping down.");
                leader = false;
                return;
            }
            // Do idempotent leader work; pass fencingToken to downstream systems
            doLeaderOnlyAction(fencingToken);
        } catch (SQLException e) {
            e.printStackTrace();
            leader = false;
        }
    }

    private boolean stillHoldsLock() throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement("select pg_advisory_lock_session_lock(?)")) {
            // In PG 16+, pg_advisory_lock_session_lock() shows current session locks.
            // As a portable alternative, attempt a non-blocking re-lock with try; if false AND not held, step down.
            ps.setLong(1, lockKey);
            // Not all versions have this function; fallback approach:
        } catch (SQLException ignored) {
            try (PreparedStatement ps = conn.prepareStatement("select pg_try_advisory_lock(?)")) {
                ps.setLong(1, lockKey);
                try (ResultSet rs = ps.executeQuery()) {
                    if (rs.next()) {
                        boolean acquiredAgain = rs.getBoolean(1);
                        if (acquiredAgain) {
                            // We already had it; PG allows re-entrant session locks, so we must unlock once.
                            try (PreparedStatement un = conn.prepareStatement("select pg_advisory_unlock(?)")) {
                                un.setLong(1, lockKey);
                                un.execute(); // release one level
                            }
                            return true;
                        }
                        return false;
                    }
                }
            }
        }
        return true;
    }

    private void doLeaderOnlyAction(long fencingToken) {
        System.out.println(Instant.now() + " leader work with token=" + fencingToken);
        // Example: write to a table that rejects stale tokens:
        //   insert into jobs(..., fencing_token) values(..., ?)
        //   and downstream consumers ensure the token is >= their last seen value
    }

    @Override
    public void close() throws Exception {
        // Best-effort unlock on shutdown
        try (PreparedStatement ps = conn.prepareStatement("select pg_advisory_unlock(?)")) {
            ps.setLong(1, lockKey);
            ps.execute();
        } catch (SQLException ignored) {}
        conn.close();
    }

    public static void main(String[] args) throws Exception {
        try (PostgresLeader app = new PostgresLeader(
                "jdbc:postgresql://localhost:5432/app", "app", "app", 0xC0FFEE_L)) {
            app.run();
        }
    }
}
```

**Notes**

-   Advisory locks are **session-scoped**; if the process dies, the lock is released.

-   Because DB locks **don’t provide cluster-wide fencing**, we explicitly add a **fencing counter** and attach it to side effects; downstream systems must reject stale tokens.


---

## Known Uses

-   **Kubernetes** controllers/managers use **Lease objects** in the coordination.k8s.io API group for leader election.

-   **Apache Kafka** historically elected a **Controller** via ZooKeeper; modern KRaft mode uses an internal **Raft** quorum.

-   **Hadoop HDFS NameNode** HA uses **ZKFC** (ZooKeeper Failover Controller) for active/standby selection.

-   **Consul/Etcd** leader elections for service schedulers and control planes.

-   **HashiCorp Nomad** and **Vault** use Raft for leaders within their clusters.


## Related Patterns

-   **Singleton (Clustered Singleton):** Leader Election is the cluster-safe way to realize it.

-   **Service Registry / Discovery:** Often co-resident with leadership info.

-   **Heartbeat / Health Check:** Feeds liveness signals into lease renewal.

-   **Leases / Fencing Tokens:** Safety adjuncts that prevent stale leaders from causing harm.

-   **Consensus (Raft/Paxos):** Underpins robust elections and state replication when you need stronger guarantees.

-   **Sharding / Partition Ownership (e.g., consistent hashing):** Alternative when the task can be decomposed.

-   **Scheduler / Orchestrator:** Leaders often schedule work to followers (Master-Worker).


## Consequence Summary (Cheat Sheet)

-   Prefer **consensus-backed** leases (etcd/ZK/Consul/K8s Lease) for stronger safety.

-   Always design leader work to be **idempotent** and carry a **fencing token** to downstream writes.

-   **Tune timeouts** to your GC/profile; test with chaos (kill -9, network partitions).

-   **Observe** leadership transitions and renewal latencies; alert on churn/flapping.


## Implementation Checklist

-    Choose coordination backend (ZK/etcd/Consul/K8s/DB).

-    Define election group path/key and permissions.

-    Implement acquisition + **renewal** + **watch**.

-    Add **graceful step-down** on shutdown or health degradation.

-    Make leader actions **idempotent**.

-    Introduce **fencing tokens** where side effects matter.

-    Add metrics/logs for elections, renew failures, split-brain detection.

-    Load/chaos test: GC pauses, partitions, pod evictions.


---

If you want, I can adapt the sample to **Kubernetes Leases (Fabric8)**, **etcd Java client**, or **Hazelcast CP/Raft** and include container/readiness probes and Prometheus metrics.
