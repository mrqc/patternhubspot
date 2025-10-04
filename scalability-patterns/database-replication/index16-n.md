# Database Replication — Scalability Pattern

## Pattern Name and Classification

**Name:** Database Replication  
**Classification:** Scalability / Availability / Data Management (Storage Tier Horizontal Scale-Out)

---

## Intent

Increase **read scalability**, **availability**, and **disaster tolerance** by **copying data from a primary database to one or more replicas**. Direct **writes** to the **primary**; serve **reads** from **replicas** (when consistency allows). Use replication topology and consistency tactics that fit workload and SLOs.

---

## Also Known As

-   Primary/Replica (formerly Master/Slave)
    
-   Read Replicas / Hot Standby
    
-   Synchronous vs. Asynchronous Replication
    
-   Logical vs. Physical Replication
    
-   Multi-AZ / Multi-Region Replication
    

---

## Motivation (Forces)

-   **Skewed traffic**: reads ≫ writes in most OLTP systems; reads become the bottleneck.
    
-   **Availability goals**: fast failover when a primary dies; maintenance without downtime.
    
-   **Latency**: serve users closer to data (geo-replicated replicas).
    
-   **Cost & risk**: scale reads horizontally without sharding; keep a durable secondary for DR.
    
-   **Trade-off**: stronger consistency reduces latency/throughput; asynchronous gives scale but introduces **replication lag**.
    

---

## Applicability

Use Database Replication when:

-   Read traffic is heavy and can tolerate **bounded staleness** (or you can route consistency-sensitive reads elsewhere).
    
-   You require **high availability** and fast **failover** of the primary.
    
-   You need **geo-local** reads to cut RTT (e.g., EU vs US users).
    
-   You want **backup/DR** without taking write downtime.
    

Avoid or adapt when:

-   **Strict linearizability** is required on **all** reads; prefer single-writer, synchronous replicas, or use the primary for those reads.
    
-   **Write throughput** is the bottleneck (replication won’t help; consider partitioning/sharding).
    
-   You can’t operationally handle **failover**, **split-brain** prevention, and **lag monitoring**.
    

---

## Structure

-   **Primary (Writer)**: authoritative source; accepts writes, streams changes.
    
-   **Replicas (Readers)**: apply changes from primary; serve reads; may be promotable.
    
-   **Replication Channel**: physical (WAL/redo log shipping) or logical (row/statement events).
    
-   **Topology**: star (1→N), cascaded (1→R1→R2…), bi-directional (multi-primary; advanced), multi-region DR.
    
-   **Failover Controller**: orchestrates promotion and re-pointing clients (manual or automated).
    
-   **Router**: app or proxy (e.g., PgBouncer/HAProxy/Aurora endpoints) that splits read/write traffic.
    
-   **Lag Signals**: replication delay, last LSN, seconds behind master.
    

---

## Participants

-   **Application**: chooses target (primary vs replica) per query/transaction.
    
-   **Database Engine**: implements replication (streaming/WAL, binlog, redo).
    
-   **Proxy/Router**: optional middle layer for read/write splitting and health.
    
-   **Orchestrator**: manages health checks, promotion, reparenting, fencing.
    
-   **Monitor/Alerting**: watches lag, replication errors, failover events.
    

---

## Collaboration

1.  App executes a **write** → goes to **primary** → commit persists to durable log.
    
2.  Primary **streams** changes to replicas.
    
3.  Replicas **apply** changes; become queryable (possibly with delay).
    
4.  App issues **reads** → router/policy directs to replica **unless** a stricter consistency rule sends to primary.
    
5.  On **primary failure**, orchestrator **promotes** a replica, updates routing/DSN, and resumes service.
    

---

## Consequences

**Benefits**

-   **Read scale-out** without app-level sharding.
    
-   **HA/DR**: hot standbys with quick promotion.
    
-   **Geo-latency** reduction via regional replicas.
    
-   **Maintenance**: backups and index builds offloaded to replicas.
    

**Liabilities**

-   **Stale reads** due to **replication lag** (asynchronous).
    
-   **Complex failover** (split-brain risk; client re-routing).
    
-   **Write amplification** on primary; replication can throttle under load.
    
-   **Read-your-writes** anomalies unless mitigated (stickiness, session consistency).
    
-   **Schema changes** must be replication-safe; some engines restrict DDL.
    

---

## Implementation

### Key Decisions

-   **Sync level**:
    
    -   **Asynchronous** (default scale; risk of data loss on primary crash).
        
    -   **Semi-sync / Quorum** (primary waits for ≥1 replica ACK; higher latency, better durability).
        
    -   **Synchronous** (RAID-1 writes across nodes; lowest RPO, highest latency).
        
-   **Replication type**:
    
    -   **Physical (WAL/redo log)**: byte/block-level, exact copy, version-bound.
        
    -   **Logical (row/statement/CDC)**: version-flexible; enables **selective** replication and hetero targets (e.g., to search/analytics).
        
-   **Routing strategy**: app-side `@Transactional(readOnly=true)` → replicas; primary for writes/strict reads; sticky reads after writes.
    
-   **Consistency tactics**:
    
    -   **Read-your-writes**: (a) read from primary after your write; (b) wait-for-replica LSN ≥ write LSN; (c) **sticky session** to primary for Δt.
        
    -   **Monotonic reads**: carry **“staleness token”** (LSN/GTID/timestamp) and only read from replicas at or beyond it.
        
-   **Failover**: manual vs orchestrated (e.g., Patroni/Orchestrator/Pacemaker, cloud managed); **fencing** old primary before promotion.
    
-   **DDL**: use **online schema changes** compatible with replication; stage rollouts carefully.
    
-   **Observability**: track `seconds_behind`, `replay_lag`, `replication_slot` lag, WAL queue size; alert on thresholds.
    

### Anti-Patterns

-   Blindly sending **all** reads to replicas (including read-after-write critical ones).
    
-   Promoting a replica **without** fencing/demoting the old primary (split-brain).
    
-   No app-level strategy for **stale reads** → user confusion and correctness bugs.
    
-   Long transactions on replicas blocking replay (vacuum/long-running snapshots).
    
-   Mixing proxies and app routing inconsistently → “half of reads” stale, hard to reason about.
    

---

## Sample Code (Java, Spring Boot)

**Goal:** Read/write splitting with **read-your-writes** safety option.

-   Primary DataSource for writes and strict reads.
    
-   Replica pool (round-robin) for read-only transactions.
    
-   Automatic routing via `AbstractRoutingDataSource` keyed by `@Transactional(readOnly=true)`.
    
-   Optional **sticky reads** for N seconds after a write (per request/correlation id).
    

> Dependencies: Spring Boot Web & JDBC, HikariCP. Replace JDBC URLs with your Postgres/MySQL/Aurora endpoints.

```java
// build.gradle (snip)
// implementation 'org.springframework.boot:spring-boot-starter-web'
// implementation 'org.springframework.boot:spring-boot-starter-jdbc'
// runtimeOnly 'org.postgresql:postgresql'
```

```java
// RoutingConfig.java
package com.example.replication;

import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.autoconfigure.jdbc.DataSourceProperties;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.*;
import org.springframework.jdbc.datasource.lookup.AbstractRoutingDataSource;

import javax.sql.DataSource;
import java.util.*;
import java.util.concurrent.ThreadLocalRandom;

@Configuration
public class RoutingConfig {

  @Bean
  @ConfigurationProperties("app.datasource.primary")
  public DataSourceProperties primaryProps() { return new DataSourceProperties(); }

  @Bean
  @ConfigurationProperties("app.datasource.primary.hikari")
  public DataSource primary(@Qualifier("primaryProps") DataSourceProperties p) {
    return p.initializeDataSourceBuilder().build();
  }

  @Bean
  @ConfigurationProperties("app.datasource.replicas[0]")
  public DataSourceProperties replica0Props() { return new DataSourceProperties(); }

  @Bean
  @ConfigurationProperties("app.datasource.replicas[0].hikari")
  public DataSource replica0(@Qualifier("replica0Props") DataSourceProperties p) {
    return p.initializeDataSourceBuilder().build();
  }

  // Add more replicas by index (replicas[1], …) as needed.

  @Bean
  public DataSource routingDataSource(@Qualifier("primary") DataSource primary,
                                      @Qualifier("replica0") DataSource replica0) {
    Map<Object,Object> targets = new HashMap<>();
    targets.put(Target.PRIMARY, primary);
    targets.put(Target.REPLICA, new RoundRobin(Arrays.asList(replica0)));
    RoutingDataSource rds = new RoutingDataSource();
    rds.setDefaultTargetDataSource(primary);
    rds.setTargetDataSources(targets);
    return rds;
  }

  enum Target { PRIMARY, REPLICA }

  /** Holder to correlate routing decision with the current request/tx. */
  public static final class RouteContext {
    private static final ThreadLocal<Boolean> READ_ONLY = new ThreadLocal<>();
    private static final ThreadLocal<Long> STICKY_UNTIL_MS = new ThreadLocal<>();
    public static void setReadOnly(boolean ro) { READ_ONLY.set(ro); }
    public static Boolean isReadOnly() { return READ_ONLY.get(); }
    public static void clear() { READ_ONLY.remove(); STICKY_UNTIL_MS.remove(); }
    public static void stickForMillis(long ms) { STICKY_UNTIL_MS.set(System.currentTimeMillis() + ms); }
    public static boolean stickyActive() {
      Long until = STICKY_UNTIL_MS.get(); return until != null && System.currentTimeMillis() < until;
    }
  }

  static final class RoutingDataSource extends AbstractRoutingDataSource {
    @Override protected Object determineCurrentLookupKey() {
      // Sticky after write? then force PRIMARY
      if (RouteContext.stickyActive()) return Target.PRIMARY;
      Boolean ro = RouteContext.isReadOnly();
      return (ro != null && ro) ? Target.REPLICA : Target.PRIMARY;
    }
    @Override protected DataSource determineTargetDataSource() {
      Object key = determineCurrentLookupKey();
      Object ds = this.resolveSpecifiedLookupKey(key);
      if (ds instanceof RoundRobin rr) return rr.pick();
      return (DataSource) ds;
    }
  }

  static final class RoundRobin {
    private final List<DataSource> list;
    RoundRobin(List<DataSource> l) { this.list = List.copyOf(l); }
    DataSource pick() { return list.get(ThreadLocalRandom.current().nextInt(list.size())); }
  }
}
```

```java
// ReadOnlyTxAspect.java
package com.example.replication;

import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.*;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/** Sets RouteContext based on @Transactional(readOnly=true). */
@Aspect @Component @Order(0)
public class ReadOnlyTxAspect {
  @Around("@annotation(tx)")
  public Object around(ProceedingJoinPoint pjp, Transactional tx) throws Throwable {
    try {
      RoutingConfig.RouteContext.setReadOnly(tx.readOnly());
      return pjp.proceed();
    } finally {
      RoutingConfig.RouteContext.clear();
    }
  }
}
```

```java
// StickyAfterWrite.java
package com.example.replication;

import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.*;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;

/** After a successful write method, keep reads on primary for N ms to guarantee read-your-writes. */
@Aspect @Component @Order(1)
public class StickyAfterWrite {

  private static final long STICKY_MS = 800; // tune: typical replica lag p99 + safety

  @Around("@annotation(com.example.replication.WriteOperation)")
  public Object around(ProceedingJoinPoint pjp) throws Throwable {
    Object res = pjp.proceed(); // let write happen on primary (default route)
    RoutingConfig.RouteContext.stickForMillis(STICKY_MS);
    return res;
  }
}
```

```java
// WriteOperation.java (marker)
package com.example.replication;
import java.lang.annotation.*;
@Retention(RetentionPolicy.RUNTIME)
@Target({ElementType.METHOD})
public @interface WriteOperation {}
```

```java
// application.yml (example)
app:
  datasource:
    primary:
      url: jdbc:postgresql://primary.db.example:5432/app
      username: app
      password: secret
      hikari:
        maximum-pool-size: 20
    replicas:
      - url: jdbc:postgresql://replica1.db.example:5432/app
        username: app_ro
        password: secret
        hikari:
          maximum-pool-size: 30

spring:
  datasource:
    # Point Spring to the routing DataSource bean
    name: routingDataSource
```

```java
// Repository usage
package com.example.replication;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import java.util.Map;
import java.util.UUID;

@Repository
public class CustomerRepository {
  private final JdbcTemplate jdbc;
  public CustomerRepository(JdbcTemplate jdbc) { this.jdbc = jdbc; }

  @WriteOperation
  @Transactional // default readOnly=false -> PRIMARY
  public UUID create(String name, String email) {
    UUID id = UUID.randomUUID();
    jdbc.update("insert into customer(id,name,email) values (?,?,?)", id, name, email);
    return id;
  }

  @Transactional(readOnly = true) // -> REPLICA (unless sticky active)
  public Map<String,Object> find(UUID id) {
    return jdbc.queryForMap("select id,name,email from customer where id=?", id);
  }
}
```

**Notes**

-   The **sticky window** is a pragmatic guard for read-your-writes. For stronger guarantees in Postgres, you can also **wait for replica LSN** ≥ client’s commit LSN (server-side function) before reading from a replica.
    
-   In cloud managed databases (e.g., Aurora, AlloyDB), you can replace app routing with **cluster endpoints** (writer vs reader) and still keep a **sticky policy** in the app for post-write reads.
    

---

## Known Uses

-   **PostgreSQL streaming replication**: primary with hot standby replicas; Patroni/pg\_auto\_failover for HA.
    
-   **MySQL/InnoDB** replication via **binlog** to multiple replicas; Orchestrator for topology and failover.
    
-   **Aurora / Cloud SQL / Azure Flexible Server**: managed primary/replicas with read endpoints.
    
-   **MongoDB replica sets**: primary/secondaries; read preferences/tags for local reads.
    
-   **Cassandra/Scylla**: eventually consistent multi-replica writes with tunable consistency (different model but used for read scale).
    

---

## Related Patterns

-   **Cache Aside**: further offload replicas and smooth spikes, knowing it adds another freshness layer.
    
-   **CQRS & Read Models**: replicate (or project) into denormalized stores/search for heavy queries.
    
-   **Sharding**: when write volume exceeds primary capacity; can be combined with per-shard replicas.
    
-   **Leader Election**: for primary promotion in self-managed clusters.
    
-   **Transactional Outbox / CDC**: logical replication to other systems without impacting OLTP replicas.
    
-   **Timeouts / Retry with Backoff**: protect callers during failover or lag spikes.
    

---

## Implementation Checklist

-   Choose **replication mode** (async/semisync/sync) and **topology**.
    
-   Define **routing policy** (read-only → replicas; strict reads → primary; sticky window or LSN wait).
    
-   Implement **failover** with fencing, promotion, and client re-pointing (DSN or proxy endpoint).
    
-   Instrument **lag metrics** and **error budgets**; gate replica reads when lag > threshold.
    
-   Guard **DDL** with online strategies; test replication safety and rollback.
    
-   Validate **transaction semantics** on replicas (long queries can block replay).
    
-   Run **DR drills**: backup restore, replica rebuild, promotion, and application reconnection.
    
-   Document **consistency expectations** for each endpoint/use-case (who may read from replicas and when).

