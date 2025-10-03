# CAP Theorem — Cloud / Distributed Systems Pattern

## Pattern Name and Classification

**CAP Theorem** — *Cloud / Distributed Systems* **consistency trade-off** pattern describing what a distributed data system can (and cannot) guarantee during a **network partition**: you can choose at most **two** of **Consistency (C)**, **Availability (A)**, and **Partition tolerance (P)**. Because partitions must be tolerated in real systems, designers trade **C vs. A** under partition.

---

## Intent

Make the **trade-off explicit** for reads/writes under partitions: either **reject/route** operations to preserve **strong consistency (CP)** or **serve every request** with **eventual consistency (AP)**—and design reconciliation accordingly.

---

## Also Known As

-   **Brewer’s CAP**

-   **Consistency vs. Availability under Partition**

-   **Pick Two (C/A with P assumed)**


---

## Motivation (Forces)

-   Real networks **drop/delay** messages; partitions (P) are unavoidable.

-   Some domains require **linearizable reads/writes** (bank balances) → prefer **CP** (sacrifice availability under partition).

-   Others require **always-on** writes (social feeds, telemetry) → prefer **AP** with **convergence** after healing.

-   Product requirements differ per **operation** (e.g., place order CP; write “like” AP).


---

## Applicability

Use CAP framing when you must decide, **during partitions**:

-   **CP**: Reject/redirect writes to protect a single, globally consistent history.

-   **AP**: Accept writes on each side and **reconcile** later (CRDTs, LWW, merge policies).


Avoid misusing CAP when:

-   There’s **no partition**: modern systems can often deliver both strong consistency and high availability.

-   You conflate **latency** with availability: CAP is about *partition behavior*, not normal-path speed.


---

## Structure

```pgsql
┌─────────────── Network ────────────────┐
Client ─┤         (partition between sites)      ├─ Client
        └───────────────╱──────────╲─────────────┘
                         ╲          ╱
                   Node A ╲        ╱ Node B
                         CP: reject writes on one side (quorum)
                         AP: accept writes on both sides; reconcile later
```

---

## Participants

-   **Clients** — issue reads/writes.

-   **Replica Nodes** — hold copies/shards of data.

-   **Partition** — loss of connectivity between node subsets.

-   **Coordinator/Quorum (CP)** — decides if an op can proceed.

-   **Reconciler (AP)** — merges divergent histories (LWW, vector clocks, CRDTs).


---

## Collaboration

-   **CP path:** On partition, operations that can’t reach a **quorum** are **rejected** (or blocked), guaranteeing linearizable order for committed ops.

-   **AP path:** Each side accepts writes, tags versions, and later **merges** to converge when connectivity returns.


---

## Consequences

**Benefits**

-   Clear, explicit **failure semantics**; fewer surprises.

-   Ability to **mix** CP and AP per entity/operation.


**Liabilities**

-   **CP:** Reduced availability during partitions; higher tail latencies with quorum.

-   **AP:** Clients can see **stale/divergent** data; requires careful merge/log semantics; potential **write conflicts**.


---

## Implementation (Key Points)

-   Decide **per operation**: CP (quorum/leases) vs AP (accept + reconcile).

-   **CP toolbox:** majority **quorums**, **leader election**, **linearizable** writes, **lease** or **Raft/Paxos**.

-   **AP toolbox:** **idempotent** updates, **causal** metadata (vector clocks), **CRDTs**, **last-write-wins (LWW)** as a simple—but lossy—merge.

-   For AP, ensure **convergence**: commutative/associative merges; avoid **lost updates** when it matters.

-   Surface behavior to clients (HTTP 503 on CP reject; 202/200 with **eventual** guarantees for AP).

-   Monitor **partition detectors**, **quorum health**, **conflict rates**, **merge lag**.


---

## Sample Code (Java 17) — Tiny Replicated KV in CP vs AP Modes

> Demonstrates the CAP choice under a simulated partition between two nodes:
>
> -   **CP mode** rejects writes on a side that can’t reach quorum.
>
> -   **AP mode** accepts writes on both sides and later **reconciles** by **Last-Write-Wins (Lamport clock)** when the partition heals.
>

```java
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

// === Versioned value with a Lamport timestamp for AP reconciliation ===
final class Vv {
  final String value;
  final long ts;        // Lamport timestamp
  Vv(String value, long ts) { this.value = value; this.ts = ts; }
  static Vv newer(Vv a, Vv b) { return (a == null) ? b : (b == null) ? a : (a.ts >= b.ts ? a : b); }
  public String toString() { return value + "@" + ts; }
}

enum Mode { CP, AP }

// === A single replica node ===
final class Node {
  final String name;
  private final Map<String, Vv> store = new ConcurrentHashMap<>();
  private long clock = 0;

  Node(String name) { this.name = name; }

  synchronized Vv putLocal(String key, String value) {
    clock = Math.max(clock + 1, System.nanoTime()); // monotonic-ish for demo
    Vv vv = new Vv(value, clock);
    store.put(key, vv);
    return vv;
  }
  synchronized void mergeFrom(Node other) {
    other.store.forEach((k, vvOther) -> {
      Vv cur = store.get(k);
      store.put(k, Vv.newer(cur, vvOther));
    });
    clock = Math.max(clock, other.clock);
  }
  Vv get(String key) { return store.get(key); }
  public String dump() { return name + store.toString(); }
}

// === Replicated KV across two nodes with a simulated partition ===
final class ReplicatedKV {
  private final Node a = new Node("A");
  private final Node b = new Node("B");
  private boolean partitioned = false;
  private final Mode mode;

  ReplicatedKV(Mode mode) { this.mode = mode; }

  // choose target by client affinity
  Node nodeFor(String client) { return "left".equals(client) ? a : b; }

  // Write with CAP behavior
  public void put(String clientSide, String key, String value) {
    Node n = nodeFor(clientSide);
    if (mode == Mode.CP) {
      // need "quorum": both sides reachable in this toy 2-node world
      if (partitioned) throw new IllegalStateException("CP reject: partition, no quorum");
      Vv vv = n.putLocal(key, value);
      // synchronous replicate
      other(n).mergeFrom(n);
      System.out.println("[CP] write " + key + "=" + vv + " replicated");
    } else {
      // AP: accept locally and reconcile later
      Vv vv = n.putLocal(key, value);
      System.out.println("[AP] write accepted on " + n.name + " " + key + "=" + vv);
      if (!partitioned) other(n).mergeFrom(n); // if no partition, propagate now
    }
  }

  public String get(String clientSide, String key) {
    Node n = nodeFor(clientSide);
    Vv vv = n.get(key);
    return vv == null ? null : vv.value;
  }

  public void setPartition(boolean p) {
    this.partitioned = p;
    System.out.println("=== Partition " + (p ? "OPENED" : "HEALED") + " ===");
    if (!p && mode == Mode.AP) {
      // reconcile both directions
      a.mergeFrom(b); b.mergeFrom(a);
      System.out.println("[AP] reconciled: " + a.dump() + " | " + b.dump());
    }
  }

  private Node other(Node n) { return n == a ? b : a; }
}

// === Demo ===
public class CapDemo {
  public static void main(String[] args) {
    System.out.println("---- CP mode (consistency over availability) ----");
    var cp = new ReplicatedKV(Mode.CP);
    cp.put("left", "balance:alice", "100");  // ok
    cp.setPartition(true);
    try { cp.put("right", "balance:alice", "200"); } // rejected
    catch (Exception e) { System.out.println(e.getMessage()); }
    System.out.println("read(left): " + cp.get("left", "balance:alice"));   // 100
    System.out.println("read(right): " + cp.get("right", "balance:alice")); // 100 (consistent but some writes unavailable)
    cp.setPartition(false);
    cp.put("right", "balance:alice", "200"); // ok after heal
    System.out.println("read both: " + cp.get("left", "balance:alice"));

    System.out.println("\n---- AP mode (availability over consistency) ----");
    var ap = new ReplicatedKV(Mode.AP);
    ap.put("left", "profile:bio", "Hi");
    ap.setPartition(true);
    ap.put("left", "profile:bio", "Hi from A"); // accepted on A
    ap.put("right","profile:bio", "Hi from B"); // accepted on B (divergent)
    // reads during partition can disagree
    System.out.println("A sees: " + ap.get("left", "profile:bio"));
    System.out.println("B sees: " + ap.get("right","profile:bio"));
    ap.setPartition(false); // heal → reconcile (LWW)
    System.out.println("After heal (converged LWW): " + ap.get("left", "profile:bio"));
  }
}
```

**What the demo shows**

-   In **CP**, writes during a partition are **rejected** (no quorum) → consistent reads, lower availability.

-   In **AP**, both sides **accept** writes → temporary divergence; after healing, state **converges** via **LWW** (simple but lossy—real systems often use CRDTs or richer conflict resolution).


---

## Known Uses

-   **CP-leaning**: ZooKeeper/etcd/Consul (metadata, coordination), Spanner/Raft-based stores for critical rows.

-   **AP-leaning**: Dynamo-style systems (Cassandra, Riak) with **tunable consistency** and **read repair**; caches and feeds that reconcile later.

-   **Mixed per operation**: e-commerce—**order placement (CP)** vs **product view counters (AP)**.


---

## Related Patterns

-   **Quorum / Leader-Based Replication** — typical **CP** mechanisms.

-   **Eventual Consistency / CRDTs** — principled **AP** convergence.

-   **Circuit Breaker / Bulkhead** — keep partitions/failures from cascading.

-   **Saga** — process-level compensation when data stores are AP and anomalies arise.

-   **Read Repair / Anti-Entropy** — background reconciliation for AP systems.
