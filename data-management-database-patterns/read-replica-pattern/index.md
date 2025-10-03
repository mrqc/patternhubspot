
# Data Management & Database Pattern — Read Replica

## Pattern Name and Classification

-   **Name:** Read Replica

-   **Classification:** Scalability & availability pattern (asynchronous data replication for read offloading)


## Intent

Scale reads and improve availability by **replicating** a primary database to one or more **read-only replicas**. Route **writes** to the **primary**, **reads** to **replicas**, with policies to handle **replication lag** and **failover**.

## Also Known As

-   Read-only Replica / Standby

-   Read Scaling with Replication

-   Follower / Secondary (primary–secondary replication)


## Motivation (Forces)

-   **Read-heavy workloads** overwhelm a single primary.

-   **Operational isolation:** long-running analytics, ad-hoc queries shouldn’t impact OLTP writes.

-   **Availability:** replicas can serve reads during primary maintenance; may be promoted on failure.

-   **Trade-off:** async replication introduces **staleness** (replica lag) and potential **read-your-write** violations.


## Applicability

Use when:

-   Workload is **much heavier on reads** than writes.

-   Some endpoints tolerate **slightly stale** data (seconds).

-   You need **blue/green** or **zero-downtime** maintenance windows for read traffic.


Be cautious when:

-   Strict **read-your-write** or linearizability is required for all requests.

-   Complex **cross-shard** transactions already exist (layering replicas increases complexity).

-   Regulatory constraints prohibit **geo-replication**.


## Structure

```pgsql
+------------------+
Writes (R/W)   |     Primary      |  WAL/binlog ->  Replication Stream
──────────────►|  (read-write)    |==============================┐
               +------------------+                              │
                      ▲        ▲                                 │
                      │ Failover│                                 │
                      │        │                                 ▼
               +------------------+                       +------------------+
Reads (R) ────►|    Replica 1     |      Reads (R) ─────►|    Replica 2     |
               |   (read-only)    |                       |   (read-only)    |
               +------------------+                       +------------------+

            ▲
            │
      +-----------+
      |  Router   |  (read/write split, lag-aware, read-your-write policies)
      +-----------+
```

## Participants

-   **Primary (Leader):** Accepts writes and authoritative reads.

-   **Replicas (Followers):** Read-only nodes applying the primary’s change log (WAL/binlog).

-   **Replication Channel:** WAL shipping, logical/row-based, or physical streaming.

-   **Router / Data Access Layer:** Sends writes to the primary and reads to suitable replicas (can be app code, driver, or proxy).

-   **Lag Monitor:** Measures replica freshness (e.g., LSN distance, `Seconds_Behind_Master`).

-   **Failover Controller (optional):** Promotes a replica, updates routing.


## Collaboration

1.  Application issues **write** → routed to **primary**; change is durably logged.

2.  Primary’s log is **streamed** to replicas; replicas **replay** and update state.

3.  Application issues **read** → router selects a **replica** (or primary) based on:

    -   query criticality,

    -   user/session **read-your-write** requirement,

    -   **lag** thresholds or tokens (LSN/GTID).

4.  On primary failure, a **replica is promoted**; router updates targets.


## Consequences

**Benefits**

-   **Horizontal read scaling** without partitioning data.

-   **Operational isolation** for expensive reads.

-   **Geo-proximity** reads for latency reductions.


**Liabilities**

-   **Staleness:** replicas lag; clients may read old data.

-   **Complex routing:** you must detect/handle lag, retries, fallbacks.

-   **Write amplification:** extra network/storage; heavy writes can saturate replication.

-   **Failover complexity:** risk of **split-brain** or data loss with async replication.


## Implementation (Key Points)

-   **Routing policy:**

    -   Default: reads → replicas, writes → primary.

    -   **Pinned/critical reads:** route to primary or enforce **read-your-write** with tokens.

-   **Freshness / Lag handling:**

    -   Postgres: compare **LSN** (`pg_last_wal_replay_lsn()` vs. `pg_current_wal_lsn()`), or `pg_last_xact_replay_timestamp()`.

    -   MySQL: `Seconds_Behind_Master` or **GTID** wait (`MASTER_GTID_WAIT`).

    -   Configure **max acceptable lag** per endpoint; **fallback** to primary when exceeded.

-   **Read-your-write strategies:**

    -   **Primary reads** after write (simplest).

    -   **Session token**: capture LSN/GTID at commit; replicas **wait until** they’ve replayed ≥ token before serving.

    -   **Sticky routing:** pin a session to primary for N seconds after a write.

-   **Connection pools:** separate pools for **primary** and **replicas**; mark replica sessions **read-only**.

-   **Transactions:** keep **write transactions on primary**; don’t mix R/W in the same tx across nodes.

-   **Failover:** use managed proxies (e.g., PgBouncer with lists, RDS/Aurora endpoints) or service discovery to update targets.

-   **Observability:** metrics on lag, replica error rates, read split %, fallback counts.


---

## Sample Code (Java 17): Lag-Aware Read/Write Router with Optional “Read-Your-Write” Token

> What it shows
>
> -   Two `DataSource`s: **primary** and **replica(s)**
>
> -   A **Router** that sends writes to primary; reads to freshest replica if below **lag threshold**
>
> -   Optional **consistency token** (e.g., Postgres LSN / MySQL GTID) captured after writes; reads can wait for a replica to catch up or **fallback** to primary
>
> -   Pure JDBC; replace the “lag” and “LSN” queries with your DB’s specifics
>

```java
// File: ReadReplicaRouterDemo.java
// Compile: javac ReadReplicaRouterDemo.java
// Run:     java ReadReplicaRouterDemo
import javax.sql.DataSource;
import java.sql.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.ThreadLocalRandom;

/** Represents a replica with a lag probe and optional LSN/GTID query. */
final class ReplicaTarget {
  final String name;
  final DataSource ds;
  final LagProbe probe; // how to measure lag (seconds or LSN distance)

  ReplicaTarget(String name, DataSource ds, LagProbe probe) {
    this.name = name; this.ds = ds; this.probe = probe;
  }

  boolean isFreshEnough(Duration maxLag, Optional<ConsistencyToken> token, Duration waitUpTo) {
    long start = System.nanoTime();
    while (true) {
      if (token.isPresent()) {
        if (probe.hasCaughtUp(ds, token.get())) return true;
      } else {
        if (probe.currentLagSeconds(ds) <= maxLag.getSeconds()) return true;
      }
      if (System.nanoTime() - start > waitUpTo.toNanos()) return false;
      sleep(50);
    }
  }

  private static void sleep(long ms){ try { Thread.sleep(ms); } catch (InterruptedException ignored) {} }
}

interface LagProbe {
  /** Return current approximate replication lag in seconds. */
  long currentLagSeconds(DataSource replicaDs);

  /** Return true if replica has replayed at or past the session's consistency token. */
  default boolean hasCaughtUp(DataSource replicaDs, ConsistencyToken token) { return false; }
}

/** Consistency token captured at commit (e.g., LSN/GTID). */
sealed interface ConsistencyToken permits PostgresLsnToken, MySqlGtidToken {}
record PostgresLsnToken(String lsn) implements ConsistencyToken {}
record MySqlGtidToken(String gtidSet) implements ConsistencyToken {}

enum ReadPreference {
  REPLICA_OK,      // prefer replica; fallback to primary if lag too high
  PRIMARY_ONLY,    // always primary (strict)
  REPLICA_REQUIRED // fail if no fresh replica available
}

/** Router with simple policies: R/W split, lag-aware, optional token wait. */
final class ReadReplicaRouter {
  private final DataSource primary;
  private final List<ReplicaTarget> replicas;
  private final Duration maxReplicaLag;     // acceptable staleness
  private final Duration tokenWait;         // max wait for read-your-write on a replica

  ReadReplicaRouter(DataSource primary, List<ReplicaTarget> replicas,
                    Duration maxReplicaLag, Duration tokenWait) {
    this.primary = primary;
    this.replicas = List.copyOf(replicas);
    this.maxReplicaLag = maxReplicaLag;
    this.tokenWait = tokenWait;
  }

  /** Execute a write (INSERT/UPDATE/DELETE) on the primary. Returns an optional consistency token. */
  public Optional<ConsistencyToken> executeWrite(String sql, SqlConfigurer cfg, boolean captureToken) throws SQLException {
    try (Connection c = primary.getConnection()) {
      c.setAutoCommit(false);
      try (PreparedStatement ps = c.prepareStatement(sql)) {
        cfg.apply(ps);
        ps.executeUpdate();
      }
      Optional<ConsistencyToken> token = Optional.empty();
      if (captureToken) {
        token = Optional.ofNullable(captureToken(c));
      }
      c.commit();
      return token;
    }
  }

  /** Execute a read; routes to replica if fresh enough, else to primary (based on preference). */
  public <T> T executeRead(String sql, SqlConfigurer cfg, ResultMapper<T> map,
                           ReadPreference pref, Optional<ConsistencyToken> token) throws SQLException {
    // Try replicas first when allowed
    if (pref != ReadPreference.PRIMARY_ONLY && !replicas.isEmpty()) {
      // simple shuffle to spread load
      List<ReplicaTarget> shuffled = new ArrayList<>(replicas);
      Collections.shuffle(shuffled, ThreadLocalRandom.current());
      for (ReplicaTarget r : shuffled) {
        if (r.isFreshEnough(maxReplicaLag, token, token.map(t -> tokenWait).orElse(Duration.ZERO))) {
          return query(r.ds, sql, cfg, map);
        }
      }
      if (pref == ReadPreference.REPLICA_REQUIRED) {
        throw new SQLException("No replica fresh enough for query.");
      }
    }
    // Fallback or strict: primary
    return query(primary, sql, cfg, map);
  }

  private <T> T query(DataSource ds, String sql, SqlConfigurer cfg, ResultMapper<T> map) throws SQLException {
    try (Connection c = ds.getConnection()) {
      // Safe guard for replicas:
      c.setReadOnly(true);
      try (PreparedStatement ps = c.prepareStatement(sql)) {
        cfg.apply(ps);
        try (ResultSet rs = ps.executeQuery()) {
          return map.map(rs);
        }
      }
    }
  }

  /** Capture a token at commit time (DB-specific). Here we demo Postgres LSN query. */
  private ConsistencyToken captureToken(Connection c) {
    try (Statement st = c.createStatement();
         ResultSet rs = st.executeQuery("SELECT pg_current_wal_lsn()")) {
      if (rs.next()) return new PostgresLsnToken(rs.getString(1));
    } catch (SQLException ignore) { /* not Postgres or insufficient privileges */ }
    return null;
  }
}

/* ---------- DB-specific lag probes (examples) ---------- */
final class PostgresLagProbe implements LagProbe {
  @Override public long currentLagSeconds(DataSource ds) {
    // Approximate: now() - last replay time on replica
    String q = "SELECT EXTRACT(EPOCH FROM now() - pg_last_xact_replay_timestamp())::bigint AS lag";
    try (Connection c = ds.getConnection(); Statement st = c.createStatement(); ResultSet rs = st.executeQuery(q)) {
      return rs.next() ? Math.max(0, rs.getLong(1)) : Long.MAX_VALUE;
    } catch (SQLException e) {
      return Long.MAX_VALUE;
    }
  }
  @Override public boolean hasCaughtUp(DataSource ds, ConsistencyToken token) {
    if (!(token instanceof PostgresLsnToken p)) return false;
    String q = "SELECT pg_last_wal_replay_lsn() >= pg_lsn(?) AS ok";
    try (Connection c = ds.getConnection();
         PreparedStatement ps = c.prepareStatement(q)) {
      ps.setString(1, p.lsn());
      try (ResultSet rs = ps.executeQuery()) {
        return rs.next() && rs.getBoolean(1);
      }
    } catch (SQLException e) {
      return false;
    }
  }
}

final class MySqlLagProbe implements LagProbe {
  @Override public long currentLagSeconds(DataSource ds) {
    try (Connection c = ds.getConnection(); Statement st = c.createStatement();
         ResultSet rs = st.executeQuery("SHOW SLAVE STATUS")) {
      if (rs.next()) {
        long lag = rs.getLong("Seconds_Behind_Master");
        return rs.wasNull() ? Long.MAX_VALUE : lag;
      }
    } catch (SQLException ignored) {}
    return Long.MAX_VALUE;
  }
  @Override public boolean hasCaughtUp(DataSource ds, ConsistencyToken token) {
    // Typically you'd use MASTER_GTID_WAIT or WAIT_FOR_EXECUTED_GTID_SET here.
    return false;
  }
}

/* ---------- Functional helpers ---------- */
@FunctionalInterface interface SqlConfigurer { void apply(PreparedStatement ps) throws SQLException; }
@FunctionalInterface interface ResultMapper<T> { T map(ResultSet rs) throws SQLException; }

/* ---------- Demo skeleton (datasource wiring is environment-specific) ---------- */
public class ReadReplicaRouterDemo {
  public static void main(String[] args) throws Exception {
    // In a real system, obtain DataSources from HikariCP / your container.
    DataSource primary = null; // TODO: init
    DataSource replica1 = null; // TODO: init
    DataSource replica2 = null; // TODO: init

    // Example wiring (replace with your DB and probe):
    List<ReplicaTarget> replicas = List.of(
      new ReplicaTarget("replica-1", replica1, new PostgresLagProbe()),
      new ReplicaTarget("replica-2", replica2, new PostgresLagProbe())
    );

    ReadReplicaRouter router = new ReadReplicaRouter(
      primary,
      replicas,
      Duration.ofSeconds(3),    // tolerate up to 3s lag for normal reads
      Duration.ofSeconds(2)     // wait up to 2s for read-your-write on a replica
    );

    // --- WRITE: insert a user and capture a consistency token (Postgres example) ---
    Optional<ConsistencyToken> token = router.executeWrite(
      "INSERT INTO users(id, name) VALUES (?, ?) ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name",
      ps -> { ps.setLong(1, 42L); ps.setString(2, "Alice"); },
      true // capture LSN if supported
    );

    // --- READ (normal): prefer replica, fallback to primary if laggy ---
    String name = router.executeRead(
      "SELECT name FROM users WHERE id = ?",
      ps -> ps.setLong(1, 42L),
      rs -> rs.next() ? rs.getString(1) : null,
      ReadPreference.REPLICA_OK,
      Optional.empty()
    );
    System.out.println("Normal read => " + name);

    // --- READ (read-your-write): require replica has applied our LSN; else fallback to primary ---
    String consistentName = router.executeRead(
      "SELECT name FROM users WHERE id = ?",
      ps -> ps.setLong(1, 42L),
      rs -> rs.next() ? rs.getString(1) : null,
      ReadPreference.REPLICA_OK,
      token
    );
    System.out.println("RYW read => " + consistentName);
  }
}
```

**How to adapt this:**

-   **DataSources:** wire with your favorite pool (HikariCP).

-   **Lag probes:** swap `PostgresLagProbe` for `MySqlLagProbe` or your platform’s calls.

-   **Consistency tokens:**

    -   Postgres: LSN (`pg_current_wal_lsn()` / `pg_last_wal_replay_lsn()`), or `pg_last_xact_replay_timestamp()` for coarse checks.

    -   MySQL: GTID (`MASTER_GTID_WAIT` / `WAIT_FOR_EXECUTED_GTID_SET`).

-   **Policies:** set different `maxReplicaLag` for endpoints (e.g., dashboards vs. user profiles).


---

## Known Uses

-   **Web/mobile backends:** read-heavy product/catalog/user-profile endpoints.

-   **SaaS multi-tenant apps:** offload analytics/reporting to replicas.

-   **Managed databases:** AWS RDS/Aurora, Azure Database, Cloud SQL—built-in read replicas with reader endpoints.

-   **Global apps:** geo-distributed replicas for regional reads.


## Related Patterns

-   **Cache Aside / Read-Through:** Complement for ultra-low latency; cache sits in front of replicas.

-   **CQRS:** Reads naturally target replicas; writes go to the primary/write model.

-   **Database per Service:** Each service may keep its own replicas.

-   **Leader–Follower Replication:** The underlying replication topology.

-   **Materialized View:** Precomputed aggregates on top of replicas.

-   **Failover / Election (Leader Election):** Promote a replica on primary failure.


---

### Practical Tips

-   **Separate pools** for primary and replicas; set `readOnly=true` on replica connections.

-   **Protect** against stale reads: per-endpoint **lag budgets**, **RYW tokens**, or **PRIMARY\_ONLY** for sensitive reads.

-   **Backpressure:** stop routing to replicas that exceed lag; autoscale or fix replication throughput.

-   **Query tagging:** add comments (e.g., `/* read-replica */`) to identify paths in logs.

-   **Health & SLOs:** track **lag**, **error rates**, **read split %**, **fallbacks**, **promotion events**.

-   **Failover drills:** exercise promotion and router reconfiguration regularly.

-   **Security:** replicas are production data—enforce encryption, IAM, and auditing as strictly as the primary.
