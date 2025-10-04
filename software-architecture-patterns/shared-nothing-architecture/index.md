# Shared-Nothing Architecture — Software Architecture Pattern

## Pattern Name and Classification

-   **Name:** Shared-Nothing Architecture
    
-   **Classification:** Distributed Systems / Scalability & Fault-Isolation / Deployment & Data Partitioning
    

## Intent

Scale horizontally by running **independent nodes that share no memory, disk, or other state**. Each node owns a **disjoint partition of data and workload** and communicates with others only via the **network**. This avoids contention and central bottlenecks while enabling **elastic scale-out, fault isolation, and predictable performance**.

## Also Known As

-   SN (Shared-Nothing)
    
-   Sharding / Partitioned Cluster (data management context)
    
-   Embarrassingly Parallel (for certain compute workloads)
    

## Motivation (Forces)

-   **Scalability:** centralized state (shared DB, shared cache, shared FS) becomes a choke point.
    
-   **Fault Isolation & Availability:** a failure in one node should not cascade.
    
-   **Performance Predictability:** no cross-node locks or shared buses → fewer tail latencies from contention.
    
-   **Elasticity & Cost:** add/remove nodes linearly with load.  
    Tensions include **data partitioning strategy**, **hot partitions / skew**, **cross-partition queries/transactions**, and **routing & rebalancing**.
    

## Applicability

Use when:

-   Data and traffic can be **partitioned** by a key (userId, tenantId, shard key) with limited cross-partition joins.
    
-   You require **independent scaling** and **failure domains**.
    
-   Workloads are **parallelizable** (map/split → process → aggregate).
    

Be careful when:

-   You need **global ACID transactions** and multi-entity joins frequently.
    
-   Access patterns are **skewed** (hot keys) or keys are hard to partition.
    
-   Rebalancing costs (data movement) are prohibitive for your RTO/RPO.
    

## Structure

Core elements:

-   **Partition / Shard:** a disjoint subset of data + compute; owned by one primary node (optionally with replicas).
    
-   **Node:** stateless worker + local state for its partition; no shared memory/disk.
    
-   **Router / Coordinator:** maps keys → nodes (e.g., **consistent hashing**, range maps) and handles **scatter–gather** for cross-partition queries.
    
-   **Replication (optional):** per-partition replicas for HA and read scale.
    
-   **Rebalancer:** moves partitions when nodes join/leave or when load skews.
    

```pgsql
+------------------- Router / Coordinator -------------------+
           |   hash(key) → node; scatter–gather; rebalancing; health    |
           +--------------------------+---------------------------------+
                                      |
      +-------------------------------+-------------------------------+
      |                               |                               |
+-----v-----+  owns P0,P3        +----v-----+  owns P1,P4        +----v-----+  owns P2,P5
|  Node A   |  (local disk/mem)  | Node B   |  (local disk/mem)  | Node C   |  (local disk/mem)
+-----------+                    +----------+                    +----------+
(no shared memory/disk; only network messages between nodes)
```

## Participants

-   **Router/Coordinator:** routes requests to the correct node(s); provides APIs to add/remove nodes; may orchestrate scatter–gather.
    
-   **Partitioner:** strategy mapping keys to partitions (consistent hashing, ranges, directory/lookup).
    
-   **Node:** executes requests for its partitions using **only local state**.
    
-   **Rebalancer:** redistributes partitions when topology changes or load is skewed.
    
-   **Replication Layer (optional):** maintains follower copies; handles failover.
    

## Collaboration

1.  Client sends request with a **routing key** (e.g., userId).
    
2.  **Router** computes owner node(s) and forwards the request directly; for queries spanning many keys, it issues **parallel sub-requests** and **aggregates** results.
    
3.  **Node** reads/writes **local** data; no cross-node locks.
    
4.  On membership change (add/remove node), **Rebalancer** moves only the affected partitions (minimal with consistent hashing).
    
5.  Optional replicas receive changes **asynchronously or synchronously** for HA.
    

## Consequences

**Benefits**

-   Near-linear **scale-out** for partitionable workloads.
    
-   **Fault isolation:** a single node failure affects only its partitions.
    
-   **Simplicity of concurrency:** no global locks; fewer contention hot spots.
    
-   Often **cost-efficient** on commodity hardware.
    

**Liabilities**

-   **Cross-partition operations** are harder (distributed transactions, joins).
    
-   **Hot keys** and data skew can kill performance without mitigation.
    
-   **Operational complexity:** routing, rebalancing, replication, and observability must be done right.
    
-   **Consistency trade-offs:** replication and rebalancing introduce eventual consistency unless carefully handled.
    

## Implementation

### Key Decisions

-   **Partitioning:** consistent hashing (good for churn), ranges (good for scans), directory/lookup (flexible, but adds a hop).
    
-   **Replication & consistency:** single-writer + async replicas (AP) vs. quorum (CP/AP hybrids).
    
-   **Routing:** client library vs. proxy/router service; cache membership with TTL + health checks.
    
-   **Rebalancing:** automatic vs. operator-triggered; throttle data movement; move **partitions**, not individual keys.
    
-   **Hotspot mitigation:** virtual nodes, key salting, caching, rate limiting, or dynamic partitioning.
    

### Operational Guidelines

-   Track **partition load** (QPS, p95/p99 latency, storage) and **rebalance before saturation**.
    
-   Implement **idempotent writes** or write fencing during moves/failover.
    
-   Automate **node join/leave** (discovery, health, draining).
    
-   Expose **routing tables** and **ring state** for debugging and audits.
    
-   Build **dark launch** and **canary** flows for new partitions/nodes.
    

---

## Sample Code (Java 17, single-file demo)

A minimal in-memory **shared-nothing key–value cluster** using **consistent hashing** with **virtual nodes** and **replication factor** `R`. It supports `put/get`, **scatter–gather count**, and **rebalance** on node add/remove.

```java
// SharedNothingDemo.java
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/** Utilities */
class HashUtil {
  static long hash64(String s) {
    try {
      MessageDigest md = MessageDigest.getInstance("MD5");
      byte[] d = md.digest(s.getBytes(StandardCharsets.UTF_8));
      long h = 0;
      for (int i = 0; i < 8; i++) { h = (h << 8) | (d[i] & 0xff); }
      return h & 0x7fffffffffffffffL;
    } catch (Exception e) { throw new RuntimeException(e); }
  }
}

/** A shared-nothing node: owns local data; no shared disk/mem with others. */
class Node {
  final String id;
  private final ConcurrentHashMap<String, String> kv = new ConcurrentHashMap<>();
  Node(String id) { this.id = id; }
  void putLocal(String k, String v) { kv.put(k, v); }
  String getLocal(String k) { return kv.get(k); }
  boolean containsKey(String k){ return kv.containsKey(k); }
  Set<Map.Entry<String,String>> snapshot() { return new HashMap<>(kv).entrySet(); }
  void removeLocal(String k){ kv.remove(k); }
  int size(){ return kv.size(); }
  public String toString(){ return id; }
}

/** Consistent hash ring with virtual nodes. */
class ConsistentHashRing {
  private final TreeMap<Long, Node> ring = new TreeMap<>();
  private final Map<String, Node> byId = new HashMap<>();
  private final int vnodes;

  ConsistentHashRing(int vnodes){ this.vnodes = vnodes; }

  void addNode(Node n){
    if (byId.putIfAbsent(n.id, n) != null) throw new IllegalStateException("Duplicate node " + n.id);
    for (int i=0;i<vnodes;i++){ ring.put(HashUtil.hash64(n.id + "#" + i), n); }
  }
  Node removeNode(String id){
    Node n = byId.remove(id);
    if (n == null) return null;
    for (int i=0;i<vnodes;i++){ ring.remove(HashUtil.hash64(id + "#" + i)); }
    return n;
  }
  List<Node> owners(String key, int replicas){
    if (ring.isEmpty()) throw new IllegalStateException("No nodes in ring");
    long h = HashUtil.hash64(key);
    LinkedHashSet<Node> res = new LinkedHashSet<>();
    ring.tailMap(h).values().forEach(res::add);
    if (res.size() < replicas) ring.values().forEach(res::add);
    return new ArrayList<>(res).subList(0, Math.min(replicas, res.size()));
  }
  Collection<Node> nodes(){ return Collections.unmodifiableCollection(byId.values()); }
}

/** Cluster router/coordinator: routes ops to owners; handles rebalance and scatter–gather. */
class Cluster {
  private final ConsistentHashRing ring;
  private final int replicationFactor;

  Cluster(int vnodes, int replicationFactor){
    this.ring = new ConsistentHashRing(vnodes);
    this.replicationFactor = Math.max(1, replicationFactor);
  }

  void addNode(String id){ ring.addNode(new Node(id)); }
  void removeNode(String id){ ring.removeNode(id); }

  void put(String key, String value){
    for (Node n : ring.owners(key, replicationFactor)) { n.putLocal(key, value); }
  }

  String get(String key){
    for (Node n : ring.owners(key, replicationFactor)) {
      String v = n.getLocal(key);
      if (v != null) return v;           // first hit wins (fallback across replicas)
    }
    return null;
  }

  /** Rebalance data to match the current ring ownership (simple, eager copy). */
  void rebalance() {
    // 1) Snapshot all data
    Map<String,String> all = new HashMap<>();
    for (Node n : ring.nodes()) for (var e : n.snapshot()) all.putIfAbsent(e.getKey(), e.getValue());

    // 2) Ensure each key is on the correct owners; remove extras from non-owners
    for (var entry : all.entrySet()) {
      String k = entry.getKey(), v = entry.getValue();
      List<Node> owners = ring.owners(k, replicationFactor);
      // Put on missing owners
      for (Node o : owners) if (!o.containsKey(k)) o.putLocal(k, v);
      // Remove from nodes that should not own it
      for (Node n : ring.nodes()) {
        if (!owners.contains(n) && n.containsKey(k)) n.removeLocal(k);
      }
    }
  }

  /** Simple scatter–gather: count keys matching a prefix across nodes. */
  long countKeysWithPrefix(String prefix){
    return ring.nodes().stream()
      .mapToLong(n -> n.snapshot().stream().filter(e -> e.getKey().startsWith(prefix)).count())
      .sum();
  }

  Map<String,Integer> distribution(){
    Map<String,Integer> m = new LinkedHashMap<>();
    for (Node n : ring.nodes()) m.put(n.id, n.size());
    return m;
  }
}

/** Demo */
public class SharedNothingDemo {
  public static void main(String[] args) {
    Cluster cluster = new Cluster(/*virtual nodes*/64, /*replication*/2);

    // Start with 3 nodes
    cluster.addNode("A"); cluster.addNode("B"); cluster.addNode("C");
    // Ingest keys
    for (int i=0;i<1000;i++) cluster.put("user:"+i, "v"+i);
    cluster.rebalance(); // place data according to ring

    System.out.println("Dist (3 nodes): " + cluster.distribution());
    System.out.println("Get user:42 -> " + cluster.get("user:42"));
    System.out.println("Prefix count 'user:9' -> " + cluster.countKeysWithPrefix("user:9"));

    // Scale out: add a node, rebalance moves only a slice (thanks to consistent hashing)
    cluster.addNode("D");
    cluster.rebalance();
    System.out.println("Dist (4 nodes): " + cluster.distribution());

    // Scale in / failure: remove a node; replicas keep data available, then rebalance
    cluster.removeNode("B");
    cluster.rebalance();
    System.out.println("Dist (after removing B): " + cluster.distribution());
    System.out.println("Get user:42 after topology change -> " + cluster.get("user:42"));
  }
}
```

**What the demo illustrates**

-   **Shared-nothing nodes** (`Node`) with only local state.
    
-   **Consistent hashing** ring with **virtual nodes** → modest data movement on topology changes.
    
-   **Replication factor** for availability; reads fall back across replicas.
    
-   **Rebalancing** after node add/remove and a **scatter–gather** query.
    

## Known Uses

-   **Distributed databases & caches:** Cassandra, Dynamo-style KV stores, Riak, Couchbase, Redis Cluster, Elasticsearch shards.
    
-   **Large web platforms:** stateless app servers + sharded session/data stores.
    
-   **Analytics frameworks:** MapReduce/Spark executors working on partitioned blocks.
    
-   **Object stores & CDNs:** partitioned buckets/regions with local ownership and replication.
    

## Related Patterns

-   **Sharding** — data-partitioning technique often used within shared-nothing systems.
    
-   **Consistent Hashing** — routing strategy to minimize rebalancing on membership change.
    
-   **Leader–Follower (Primary–Replica)** — complementary for per-partition HA.
    
-   **CQRS** — can pair with SN where command/query paths are partitioned.
    
-   **Event-Driven Architecture** — async replication and rebalancing flows.
    
-   **Service-Oriented / Microservices** — services themselves can be shared-nothing and stateless, backed by sharded stores.
    

---

## Implementation Tips

-   Choose the **right partition key**; monitor **skew** and rotate keys (salting) when needed.
    
-   Use **virtual nodes** to smooth load and simplify rebalancing.
    
-   Prefer **immutable/log-structured** storage to ease movement and recovery.
    
-   Automate **membership** (heartbeats/gossip) and **health-based routing** with fast TTLs.
    
-   Make writes **idempotent**; use **fencing tokens** during moves and failover.
    
-   Design **cross-partition ops** explicitly: scatter–gather, async materialized views, or bounded fan-out.
    
-   Instrument everything: **per-partition** latency, throughput, and storage; visualize the ring and ownership.

