
# Data Management & Database Pattern — Distributed Transactions

## Pattern Name and Classification

-   **Name:** Distributed Transactions

-   **Classification:** Data consistency & coordination pattern across multiple resources (databases, message queues, services)


## Intent

Guarantee **atomicity** for a business operation that spans **multiple independent resources** so that **all** effects commit or **none** do—despite failures, partial outages, or concurrency.

## Also Known As

-   Two-Phase Commit (2PC) / Three-Phase Commit (3PC)

-   XA Transactions / JTA (on the JVM)

-   TCC (Try–Confirm/Cancel) — a compensating variant


## Motivation (Forces)

-   **Atomicity vs. distribution:** Updating more than one database/queue risks partial success.

-   **Isolation:** Concurrent transactions must not interleave into inconsistent states.

-   **Availability & performance:** Global coordination adds latency, locks, and failure modes.

-   **Operational reality:** Networks partition, coordinators crash, participants can time out.


Trade-offs:

-   Strong ACID across boundaries increases **latency, lock hold times, and coupling**.

-   Avoid **in-doubt**/heuristic outcomes; if they occur, recovery procedures must resolve them.


## Applicability

Use distributed transactions when:

-   You need **strong atomicity** over multiple **transactional** resources you control (e.g., two RDBMS, a DB + durable queue).

-   The business requirement **cannot** tolerate temporary divergence (e.g., **exactly-once** ledger postings).


Prefer alternatives when:

-   Services are independently deployed and loosely coupled → favor **Sagas (compensations)** or **Outbox + idempotent consumers**.

-   One resource is non-transactional → use **TCC** or application-level retries with compensations.

-   Latency/availability are critical → avoid global locks.


## Structure

```sql
+-------------------+           prepare/commit/rollback
Client ---> |  Tx Coordinator   |  <--------------------------------+
            +-------------------+                                     \
                    | prepare all                                      \
           +--------+--------+                                          \
           |                 |                                           \
   +---------------+  +---------------+                         +-----------------+
   | Resource A    |  | Resource B    |     ...                 | Resource N      |
   | (DB/Queue/XA) |  | (DB/Queue/XA) |                         | (DB/Queue/XA)   |
   +---------------+  +---------------+                         +-----------------+
```

**Two-Phase Commit (2PC):**

1.  **Prepare (voting):** Coordinator asks all participants to persist intent and **guarantee commit feasibility** (locking resources).

2.  **Commit:** If **all** vote yes, coordinator instructs commit; otherwise **rollback** everywhere.


(3PC adds a pre-commit phase to reduce blocking but is rarely used in practice.)

## Participants

-   **Transaction Coordinator:** Assigns global Tx ID, drives 2PC/3PC, logs decisions for recovery.

-   **Participants / Resource Managers:** Databases/queues that implement `prepare/commit/rollback` (e.g., XA).

-   **Transaction Manager API:** JTA on JVM (`javax.transaction` / `jakarta.transaction`).

-   **Recovery Manager:** Replays coordinator log after crashes to finish in-doubt transactions.


## Collaboration

1.  Client begins a **global transaction** via the Transaction Manager.

2.  Work on each resource is enlisted (local operations).

3.  **Prepare:** each participant flushes redo/undo and locks rows/pages.

4.  **Decision:** all yes → **commit**; any no/failure → **rollback**.

5.  **Recovery:** on crash, coordinator re-reads its log and completes pending outcomes.


## Consequences

**Benefits**

-   **Strong atomicity** across heterogeneous resources.

-   Simplifies application logic for truly all-or-nothing operations.

-   Fits classic enterprise stacks with XA-capable middleware.


**Liabilities**

-   **Blocking & contention:** resources may hold locks between **prepare** and **commit**.

-   **Coordinator SPOF:** needs durable logging and HA; otherwise **in-doubt** transactions.

-   **Heuristic outcomes:** participants may unilaterally decide under long partitions.

-   **Coupling:** all parties must support the same protocol and coordinate versions.

-   **Latency:** network round trips + disk flushes across all participants.


## Implementation (Key Points)

-   **XA/JTA (JVM):** Use a JTA Transaction Manager (e.g., Narayana, Atomikos, Bitronix). Enlist JDBC XADataSources and JMS XAConnections.

-   **Time bounds:** Set **prepare/commit** timeouts to avoid endless in-doubt states.

-   **Idempotency:** Coordinators may retry `commit/rollback`; participants must be idempotent.

-   **Recovery log:** Persist decisions (write-ahead log) before contacting participants.

-   **Failure handling:** Detect and resolve **heuristic mixed** states with ops runbooks.

-   **Security & observability:** Correlate with **global Tx IDs**; emit metrics (prepare time, in-doubt count).


**Alternatives / Complements**

-   **Saga (choreography/orchestration):** sequence of local transactions with compensations.

-   **Outbox + CDC:** atomically persist change + message; downstream applies idempotently.

-   **TCC:** Try (reserve) → Confirm/Cancel with explicit business APIs per service.


---

## Sample Code (Java 17): Minimal 2-Phase Commit Simulation (no external libs)

> Educational, in-JVM demo of a coordinator driving `prepare/commit/rollback` over two resources  
> (a debit and a credit “account store”). This **simulates** 2PC semantics; real systems would use XA/JTA.

```java
// File: TwoPhaseCommitDemo.java
// Compile: javac TwoPhaseCommitDemo.java
// Run:     java TwoPhaseCommitDemo
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/** Resource interface with 2PC-style operations. */
interface Resource {
    String name();
    /** Vote YES by returning true; MUST persist enough to commit after crash. */
    boolean prepare(String txId);
    /** Commit previously prepared TX; must be idempotent. */
    void commit(String txId);
    /** Roll back previously prepared TX; must be idempotent. */
    void rollback(String txId);
}

/** A tiny account store supporting "reserve during prepare, apply at commit". */
final class AccountStore implements Resource {
    private final String name;
    private final Map<String, Long> balances = new ConcurrentHashMap<>();
    private final Map<String, Long> pending = new ConcurrentHashMap<>(); // txId -> delta

    AccountStore(String name, Map<String, Long> initial) {
        this.name = name;
        this.balances.putAll(initial);
    }
    public String name() { return name; }

    /** Begin a local unit of work. For simplicity we enqueue deltas keyed by txId. */
    public void addOperation(String txId, String account, long delta) {
        // Validate business rules up-front if desired (e.g., non-negative after delta)
        pending.merge(txId, 0L, Long::sum); // ensure key exists
        // Store the intent per tx (for demo we don't break down per account)
        // In a real system we'd record the per-account delta set per tx.
        // We'll piggyback the per-account change in prepare below.
    }

    /** Prepare: ensure feasibility and record intent durably (here: in-memory). */
    @Override public synchronized boolean prepare(String txId) {
        // Demo uses attached context (ThreadLocal) to know the actual operations.
        // We'll fetch the staged map from TxContext and check feasibility.
        TxContext.TxOps ops = TxContext.getOps(txId, this);
        if (ops == null) return false;
        // Validate: all debits must not overdraft
        for (var e : ops.perAccountDelta.entrySet()) {
            String acc = e.getKey();
            long delta = e.getValue();
            long cur = balances.getOrDefault(acc, 0L);
            if (cur + delta < 0) return false; // cannot proceed
        }
        // Record intent: copy into pending "log"
        long sum = 0;
        for (var e : ops.perAccountDelta.entrySet()) sum += e.getValue();
        pending.put(txId, sum); // simplistic (aggregate); enough for commit/rollback demo
        return true;
    }

    @Override public synchronized void commit(String txId) {
        TxContext.TxOps ops = TxContext.getOps(txId, this);
        if (ops == null && !pending.containsKey(txId)) return; // already committed/rolled back
        if (ops != null) {
            for (var e : ops.perAccountDelta.entrySet()) {
                balances.merge(e.getKey(), e.getValue(), Long::sum);
            }
        }
        pending.remove(txId);
    }

    @Override public synchronized void rollback(String txId) {
        pending.remove(txId); // forget intent; balances unchanged
    }

    public long balanceOf(String account) { return balances.getOrDefault(account, 0L); }
}

/** Coordinator for 2PC. */
final class TwoPhaseCoordinator {
    private final List<Resource> participants;
    private final Map<String, String> decisionLog = new HashMap<>(); // txId -> "COMMIT"/"ROLLBACK"

    TwoPhaseCoordinator(List<Resource> participants) { this.participants = participants; }

    public boolean doTransaction(String txId) {
        // Phase 1: prepare (vote)
        for (Resource r : participants) {
            boolean yes = r.prepare(txId);
            if (!yes) {
                // Abort path
                decisionLog.put(txId, "ROLLBACK");
                for (Resource rr : participants) safe(() -> rr.rollback(txId));
                return false;
            }
        }
        // Persist decision before notifying (write-ahead log; here in-memory)
        decisionLog.put(txId, "COMMIT");
        // Phase 2: commit
        for (Resource r : participants) safe(() -> r.commit(txId));
        return true;
    }

    private static void safe(Runnable r) { try { r.run(); } catch (Exception ignored) {} }
}

/** Thread-local to carry per-tx, per-resource staged operations (demo plumbing). */
final class TxContext {
    static final class TxOps {
        final Resource res;
        final Map<String, Long> perAccountDelta = new LinkedHashMap<>();
        TxOps(Resource res) { this.res = res; }
    }
    private static final Map<String, Map<Resource, TxOps>> CTX = new HashMap<>();

    static void add(String txId, Resource r, String account, long delta) {
        var map = CTX.computeIfAbsent(txId, __ -> new HashMap<>());
        var ops = map.computeIfAbsent(r, __ -> new TxOps(r));
        ops.perAccountDelta.merge(account, delta, Long::sum);
    }
    static TxOps getOps(String txId, Resource r) {
        var map = CTX.getOrDefault(txId, Map.of());
        return map.get(r);
    }
    static void clear(String txId) { CTX.remove(txId); }
}

public class TwoPhaseCommitDemo {
    public static void main(String[] args) {
        // Two independent "databases"
        AccountStore ledgerA = new AccountStore("DB_A", Map.of("alice", 10_00L)); // €10.00
        AccountStore ledgerB = new AccountStore("DB_B", Map.of("vault", 0L));

        TwoPhaseCoordinator coord = new TwoPhaseCoordinator(List.of(ledgerA, ledgerB));

        // 1) Successful transfer: debit alice in A; credit vault in B
        String tx1 = UUID.randomUUID().toString();
        TxContext.add(tx1, ledgerA, "alice", -3_50L); // -€3.50
        TxContext.add(tx1, ledgerB, "vault", +3_50L); // +€3.50
        boolean ok = coord.doTransaction(tx1);
        TxContext.clear(tx1);
        System.out.printf("TX1 committed=%s | A.alice=%.2f, B.vault=%.2f%n",
                ok, ledgerA.balanceOf("alice")/100.0, ledgerB.balanceOf("vault")/100.0);

        // 2) Failing transfer: overdraft would occur; 2PC rolls back both
        String tx2 = UUID.randomUUID().toString();
        TxContext.add(tx2, ledgerA, "alice", -10_00L); // would drive negative
        TxContext.add(tx2, ledgerB, "vault", +10_00L);
        boolean ok2 = coord.doTransaction(tx2);
        TxContext.clear(tx2);
        System.out.printf("TX2 committed=%s | A.alice=%.2f, B.vault=%.2f%n",
                ok2, ledgerA.balanceOf("alice")/100.0, ledgerB.balanceOf("vault")/100.0);
    }
}
```

**What the demo shows**

-   A **coordinator** driving `prepare → commit/rollback` across two resources.

-   **Prepare** validates feasibility; **commit** applies changes atomically across both.

-   If any participant returns **NO**, the coordinator **rolls back everywhere**.


> Real XA/JTA code would enlist XA resources and rely on a transaction manager (e.g., Narayana). This toy example illustrates the control flow without external dependencies.

---

## Known Uses

-   **Enterprise middleware** with XA (application servers, message brokers + RDBMS).

-   **Banking/ledger** systems (intra-bank postings under a single coordinator).

-   **Monolithic apps** touching multiple schemas/databases inside one trust boundary.

-   **ETL jobs** that atomically move data + publish messages (when both are XA-aware).


## Related Patterns

-   **Saga (Choreography/Orchestration):** Prefer when services are autonomous or latency/availability matter.

-   **Outbox / Transactional Messaging:** Atomic local write + asynchronous publish for integration.

-   **TCC (Try–Confirm/Cancel):** Business-level reservation/confirm APIs instead of XA.

-   **Idempotent Consumer / Exactly-once-ish:** Complements Saga/Outbox to handle retries.

-   **Event Sourcing:** Alternative consistency model via event logs and projections.


---

### Practical Tips

-   Scope XA to **few, critical** paths; keep transactions **short** to minimize lock time.

-   Configure **timeouts** and backstops to detect in-doubt participants; automate **recovery**.

-   Prefer **one coordinator domain** (same org/network boundary); avoid cross-org global transactions.

-   If any participant is not XA-capable, **don’t fake it**—use **TCC/Saga**.

-   Expose **global transaction IDs** in logs/metrics; watch **prepare latency**, **lock wait**, **heuristics**.

-   When in doubt, consider **eventual consistency** with Sagas—often faster, safer, and more operable for microservices.
