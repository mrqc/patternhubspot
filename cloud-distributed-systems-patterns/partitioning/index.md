# Partitioning - Cloud Distributed Systems Pattern

## Pattern Name and Classification

-   **Name:** Partitioning

-   **Classification:** Data & workload distribution pattern; scalability & elasticity pattern for storage, stateful services, and parallel compute.


## Intent

Split a large dataset or workload into **smaller, independent partitions** (shards) that can be stored and processed separately to:

-   scale horizontally,

-   reduce contention and hot spots,

-   improve locality and parallelism,

-   enable independent failure and recovery domains.


## Also Known As

-   Sharding

-   Data/Key Partitioning

-   Horizontal Partitioning

-   Range/Hash/Consistent-Hash Partitioning

-   Topic/Queue Partitioning (streaming systems)


## Motivation (Forces)

-   **Scale:** A single node can’t store/process all data or handle the traffic.

-   **Hot Keys & Skew:** Uneven key popularity can overload a subset of nodes.

-   **Locality:** Keep related data together for efficient queries/transactions.

-   **Elasticity/Rebalancing:** Add/remove capacity with minimal data movement.

-   **Consistency vs. Availability:** Cross-partition queries/transactions are costly.

-   **Routing:** Clients or routers must deterministically map requests to partitions.

-   **Operational Complexity:** Rebalancing, resharding, and schema changes across partitions.


## Applicability

Use Partitioning when:

-   state or throughput exceeds a single node’s limits,

-   you need to parallelize processing (e.g., map/reduce, stream processing),

-   you want to limit blast radius (per-partition failures),

-   multi-tenant isolation requires per-tenant shards,

-   you must colocate data for locality (range scans, geo-affinity).


## Structure

-   **Partition Function:** Deterministic mapping from key/work to a partition id (hash, range, composite keys, geo).

-   **Partition Directory/Metadata:** Maps partition ids to physical nodes (with replication sets).

-   **Router:** Uses the partition function + directory to forward requests.

-   **Storage/Compute Nodes:** Hold one or more partitions.

-   **Rebalancer:** Moves partitions when nodes are added/removed or load shifts.

-   **Replicas (optional):** Per-partition replicas for HA, quorum, and read scale.


## Participants

-   **Client / SDK:** May embed client-side routing (saves a hop).

-   **Partitioner:** Implements hash/range/consistent-hash mapping.

-   **Directory Service:** Source of truth for partition→node assignments (ZooKeeper/etcd/Consul/dynamic config).

-   **Router/Gateway:** Stateless layer that translates requests to the right node.

-   **Node/Shard Owner:** Processes the request; persists state for the partition.

-   **Rebalancer/Controller:** Automates partition splits/merges and movement.


## Collaboration

1.  Client generates key (e.g., `customerId`).

2.  **Partitioner** computes partition id.

3.  **Router** looks up the current owner (directory) and forwards to the node.

4.  Node processes request; replication/quorum logic (if any) applies.

5.  **Rebalancer** updates the directory when capacity changes. Clients/routers refresh.


## Consequences

**Benefits**

-   Linear(ish) scale-out; independent failure domains.

-   Lower contention; better cache and I/O locality.

-   Enables parallel batch/stream processing.


**Liabilities**

-   Cross-partition operations become complex/slow (2PC, sagas, fan-out).

-   Hot partitions (skewed keys) still possible; need salting or adaptive schemes.

-   Rebalancing causes data movement and potential write amplification.

-   Operational overhead: metadata, monitoring, backfills, split/merge orchestration.


## Implementation (Key Points)

-   **Partitioning Strategies**

    -   **Hash:** `partition = hash(key) mod N`. Simple, uniform; hard reshard (many keys move).

    -   **Consistent Hashing (with virtual nodes):** Minimal key movement on membership change; great for caches/streams.

    -   **Range:** Preserves order; enables range scans; needs split/merge & hotspot mitigation.

    -   **Directory/Lookup:** Central table from key→partition or tenant→shard; flexible but adds an extra lookup.

    -   **Composite/Hierarchical:** e.g., `(tenantId, userId)` with tenant-based top-level routing.

    -   **Geo/Locality-aware:** Partition by region/zone for latency/regulatory reasons.

-   **Skew Handling**

    -   Hot key **salting**, **key folding** (`key#randomSuffix`), **time bucketing**, or **sub-partitioning**.

-   **Rebalancing**

    -   For mod-N hash: plan dual-writes + backfill; flip over after convergence.

    -   For consistent hashing: add/remove virtual nodes; only adjacent ranges move.

    -   For range: **split** hot ranges; **merge** cold ranges; background copy + tail sync (change streams).

-   **Routing Placement**

    -   **Client-side** (libraries) reduces latency, requires config push.

    -   **Proxy-side** centralizes policy, simplifies clients, adds a hop.

-   **Replication & Consistency**

    -   Leader/follower per partition (Raft), or quorum (primary-less) per key.

    -   Read-your-writes, monotonic reads often need same-partition affinity.

-   **Observability**

    -   Per-partition QPS/latency/p99, keyspace heatmaps, movement metrics, directory change lag.


---

## Sample Code (Java 17): Consistent Hash + Range Partitioner and a Router

> Educational, in-process examples to demonstrate routing and rebalancing concepts.
>
> -   **ConsistentHashPartitioner** with virtual nodes (vnodes)
>
> -   **RangePartitioner** with dynamic splits
>
> -   **Router** that uses a registry to resolve owners
>
> -   Minimal **rebalance** example
>

```java
// File: PartitioningDemo.java
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/** -----------------------
 *  Partition Abstractions
 *  ----------------------*/
interface Partitioner<K> {
    String partitionIdFor(K key);
}

final class PartitionDirectory {
    // partitionId -> nodeId
    private final Map<String, String> assignment = new ConcurrentHashMap<>();
    // nodeId -> endpoint (placeholder)
    private final Map<String, String> nodes = new ConcurrentHashMap<>();

    void registerNode(String nodeId, String endpoint) { nodes.put(nodeId, endpoint); }
    void unregisterNode(String nodeId) {
        nodes.remove(nodeId);
        assignment.entrySet().removeIf(e -> e.getValue().equals(nodeId));
    }

    void assign(String partitionId, String nodeId) { assignment.put(partitionId, nodeId); }

    Optional<String> ownerOf(String partitionId) { return Optional.ofNullable(assignment.get(partitionId)); }
    Optional<String> endpointOf(String nodeId) { return Optional.ofNullable(nodes.get(nodeId)); }

    Map<String,String> snapshotAssignments() { return Map.copyOf(assignment); }
    Set<String> nodeIds() { return Set.copyOf(nodes.keySet()); }
}

/** -----------------------
 *  Consistent Hash Partitioner (with vnodes)
 *  ----------------------*/
final class ConsistentHashPartitioner implements Partitioner<String> {
    private final SortedMap<Long, String> ring = new TreeMap<>(); // hash -> partitionId (virtual)
    private final int vnodes;
    private final MessageDigest md;

    // partitionId here is actually "nodeId#vX" to keep keys moving minimally per vnode
    ConsistentHashPartitioner(Collection<String> nodeIds, int vnodes) {
        try { this.md = MessageDigest.getInstance("SHA-256"); }
        catch (Exception e) { throw new RuntimeException(e); }
        this.vnodes = Math.max(1, vnodes);
        for (String nodeId : nodeIds) addNode(nodeId);
    }

    void addNode(String nodeId) {
        for (int v = 0; v < vnodes; v++) {
            String vnode = nodeId + "#v" + v;
            ring.put(hash64(vnode), vnode);
        }
    }

    void removeNode(String nodeId) {
        for (int v = 0; v < vnodes; v++) {
            ring.remove(hash64(nodeId + "#v" + v));
        }
    }

    @Override public String partitionIdFor(String key) {
        if (ring.isEmpty()) throw new IllegalStateException("ring is empty");
        long h = hash64(key);
        SortedMap<Long, String> tail = ring.tailMap(h);
        Long chosen = tail.isEmpty() ? ring.firstKey() : tail.firstKey();
        return ring.get(chosen); // returns vnode id (partitionId)
    }

    private long hash64(String s) {
        byte[] digest = md.digest(s.getBytes(StandardCharsets.UTF_8));
        // take first 8 bytes as signed long
        long val = 0;
        for (int i = 0; i < 8; i++) val = (val << 8) | (digest[i] & 0xff);
        return val;
    }
}

/** -----------------------
 *  Range Partitioner (split-friendly)
 *  ----------------------*/
final class RangePartitioner implements Partitioner<Long> {
    // non-overlapping ranges: ["p0":[minInclusive,maxExclusive), ...]
    private final NavigableMap<Long, String> byStart = new TreeMap<>();

    RangePartitioner() {
        // start with a single big range
        byStart.put(Long.MIN_VALUE, "p0");
    }

    @Override public String partitionIdFor(Long key) {
        Map.Entry<Long, String> e = byStart.floorEntry(key);
        return e != null ? e.getValue() : byStart.firstEntry().getValue();
    }

    // Split a range at a splitPoint, yielding a new partition id for the upper half
    public void split(long splitPoint, String newPartitionId) {
        Map.Entry<Long, String> e = byStart.floorEntry(splitPoint);
        if (e == null) throw new IllegalArgumentException("no range to split");
        long start = e.getKey();
        String oldPid = e.getValue();
        if (Objects.equals(oldPid, newPartitionId))
            throw new IllegalArgumentException("newPartitionId must differ");
        // Re-map the upper subrange to new pid
        byStart.put(splitPoint, newPartitionId);
        // Lower subrange remains assigned to oldPid at 'start'
    }

    // For demo only
    public NavigableMap<Long, String> ranges() { return Collections.unmodifiableNavigableMap(byStart); }
}

/** -----------------------
 *  Router using a directory
 *  ----------------------*/
final class Router {
    private final PartitionDirectory directory;

    Router(PartitionDirectory directory) { this.directory = directory; }

    String route(String partitionId) {
        return directory.ownerOf(partitionId)
                .flatMap(directory::endpointOf)
                .orElseThrow(() -> new IllegalStateException("no owner for " + partitionId));
    }
}

/** -----------------------
 *  Demo
 *  ----------------------*/
public class PartitioningDemo {
    public static void main(String[] args) {
        // --- Consistent hashing demo (string keys)
        var directory = new PartitionDirectory();
        directory.registerNode("n1", "http://10.0.0.1:8080");
        directory.registerNode("n2", "http://10.0.0.2:8080");
        directory.registerNode("n3", "http://10.0.0.3:8080");

        var ch = new ConsistentHashPartitioner(List.of("n1","n2","n3"), 128);
        // Map vnode (partitionId) -> physical node (owner) 1:1 by prefix
        for (String nodeId : directory.nodeIds()) {
            for (int v = 0; v < 128; v++) {
                String pid = nodeId + "#v" + v;
                directory.assign(pid, nodeId);
            }
        }
        var router = new Router(directory);

        String[] keys = {"user:42", "user:1001", "cart:88", "order:7777"};
        System.out.println("--- Consistent hash routing ---");
        for (String k : keys) {
            String pid = ch.partitionIdFor(k);      // vnode id
            String endpoint = router.route(pid);    // owner endpoint
            System.out.printf("key=%-10s -> partition=%-8s -> %s%n", k, pid, endpoint);
        }

        // Simulate adding capacity (n4). Only a fraction of keys should move.
        System.out.println("\n--- Add node n4 (minimal key movement) ---");
        directory.registerNode("n4", "http://10.0.0.4:8080");
        ch.addNode("n4");
        for (int v = 0; v < 128; v++) directory.assign("n4#v" + v, "n4");

        for (String k : keys) {
            String pid = ch.partitionIdFor(k);
            String endpoint = router.route(pid);
            System.out.printf("key=%-10s -> partition=%-8s -> %s%n", k, pid, endpoint);
        }

        // --- Range partitioning demo (numeric keys)
        var rp = new RangePartitioner();
        // start: (-inf, +inf) -> p0 on n1
        directory.assign("p0", "n1");
        System.out.println("\n--- Range routing before split ---");
        long[] nums = { -5, 10, 1_000, 25_000 };
        for (long k : nums) {
            String pid = rp.partitionIdFor(k);
            System.out.printf("key=%8d -> %s -> %s%n", k, pid, router.route(pid));
        }

        // Split at 10_000 creating p1, assign to n2
        rp.split(10_000, "p1");
        directory.assign("p1", "n2");
        System.out.println("\n--- Range routing after split (hot range moved) ---");
        for (long k : nums) {
            String pid = rp.partitionIdFor(k);
            System.out.printf("key=%8d -> %s -> %s%n", k, pid, router.route(pid));
        }

        // Show current ranges
        System.out.println("\nRanges: " + rp.ranges());
    }
}
```

**What this shows**

-   **Consistent hashing** with vnodes: adding `n4` moves only keys that land on `n4`’s virtual ranges.

-   **Range partitioning:** a **split** moves only the upper subrange to `p1`, useful for hotspot relief.

-   **Directory & Router:** clean separation of partitioning logic and ownership mapping.


> Production systems layer on replication (Raft), backfills for movement, change streams for tail sync, and throttled rebalancing to protect latency SLOs.

---

## Known Uses

-   **Databases:**

    -   MongoDB (range/hash shards), Cassandra (token ranges), CockroachDB (range splits), Vitess (MySQL sharding), Azure Cosmos DB (logical partitions).

-   **Caches/Key-Value Stores:**

    -   Redis Cluster (hash slots), Memcached clients (consistent hashing).

-   **Streams & Logs:**

    -   Apache Kafka / Pulsar / Kinesis (topic/stream partitions; key-based routing).

-   **Search:**

    -   Elasticsearch/OpenSearch (index shards with routing and reallocation).

-   **Object Stores/Filesystems:**

    -   HDFS/S3 internal partitioning of namespace and data placement (implementation-specific).


## Related Patterns

-   **Load Balancer:** Distributes requests; often used in front of partitioned backends.

-   **Replication / Quorum / Leader Election:** Per-partition availability & consistency.

-   **Saga / Outbox:** Manage cross-partition workflows & atomicity boundaries.

-   **Consistent Hashing:** A specific partitioning technique minimizing key movement.

-   **CQRS & Materialized Views:** Keep per-partition write paths simple; build cross-partition read models.

-   **Federation / Multi-Tenant Isolation:** Route tenants to dedicated shards.

-   **Bulkhead:** Resource isolation per partition or tenant.

-   **Caching & CDN:** Complement partitioning by reducing backend load (hot key shielding).


---

### Practical Tips

-   Prefer **stable, high-cardinality keys** for hashing.

-   Track **per-partition heat**; automate split/merge and key salting for hotspots.

-   Throttle rebalancing; use **background copy + tail catch-up**, then cut over.

-   Keep partition **metadata small** and **strongly consistent**; changes should be evented to clients/routers.

-   For cross-partition queries, build **pre-computed aggregates** or **scatter–gather** with budgets and partial-result tolerance.
