# Cloud Distributed Systems Pattern — Replication

## Pattern Name and Classification

-   **Name:** Replication

-   **Classification:** Structural & data-management pattern for distributed systems; reliability/scalability/latency optimization.


## Intent

Maintain multiple copies of data or state across nodes/regions so the system remains **available**, **scalable**, and **fault-tolerant**, and so reads (and sometimes writes) can be served from the **nearest** or **least-loaded** replica.

## Also Known As

-   Mirroring

-   Standby / Follower / Secondary

-   Multi-master / Active-Active

-   Leader–Follower (for state machine replication)

-   Geo-replication


## Motivation (Forces)

-   **Availability vs Consistency:** Failovers and read-availability during outages vs the risk of stale or conflicting data.

-   **Latency:** Serving reads close to users vs ensuring fresh data globally.

-   **Throughput:** Spreading read load across replicas vs increased write amplification.

-   **Topology:** Single-leader simplicity vs multi-leader/leaderless flexibility and conflict handling.

-   **Failure Modes:** Partitions, lagging replicas, split-brain, clock skew.

-   **Operational Cost:** More nodes and cross-region bandwidth vs business continuity.

-   **Data Model:** Some models are easy to merge (CRDTs), others require application-level conflict resolution.


## Applicability

Use Replication when you need:

-   **High availability** and **disaster recovery** (RPO/RTO goals).

-   **Read scaling** (many readers, fewer writers).

-   **Geo-distribution** to reduce user-perceived latency.

-   **Zero/low downtime maintenance** and online upgrades.

-   **Event streaming / CDC** to feed downstream systems.


Avoid or restrict when:

-   Strong, linearizable writes across distant regions are mandatory but ultra-low latency is required (consider consensus placement, locality, or redesign).


## Structure

-   **Primary Roles:**

    -   **Leader/Primary:** Accepts writes, orders them (WAL/log).

    -   **Follower/Replica:** Applies the leader’s log in order; serves reads per policy.

-   **Multi-Leader or Leaderless:** Any replica may accept writes; conflicts resolved via **last-write-wins**, **causal metadata**, or **CRDTs**.

-   **Transport:** Async or sync streaming of log/operations; optional **quorums**.

-   **Metadata:** Version vectors, Lamport timestamps, or Raft terms/indexes.

-   **Anti-Entropy:** Background repair (Merkle trees, read repair, hinted handoff).


```pgsql
Client → (Write) → Leader ──(log/ops)──▶ Followers
            ▲                         ↘  Async/SYNC
            └── Reads (policy: leader/replica/nearest)
Geo: Region A Leader ⇄ Region B Followers (or multi-leader)
```

## Participants

-   **Replicator/Streamer:** Ships WAL/operations to replicas.

-   **Applier/State Machine:** Replays ops deterministically.

-   **Health/Failover Controller:** Promotes replicas; prevents split-brain.

-   **Conflict Resolver:** App logic, LWW, vector clocks, CRDT merge.

-   **Quorum Manager:** Calculates read/write consistency (R + W > N).

-   **Repair/Scanner:** Detects divergence and heals.


## Collaboration

1.  **Write** arrives at leader (or any node in multi-leader).

2.  The **log entry** is created and shipped to replicas.

3.  **Sync/quorum**: commit after majority acks; **Async**: commit locally, ship later.

4.  **Reads** are served by leader or replicas subject to staleness policy.

5.  **Failures** trigger **promotion**, **redirects**, and **repair**.

6.  **Conflicts** (multi-leader/leaderless) are resolved via deterministic rules or CRDTs.


## Consequences

**Benefits**

-   Higher **availability** (mask node/zone failures).

-   **Read scalability** and **geo-latency** improvements.

-   Supports **online maintenance** and **backups** without write downtime.


**Liabilities / Trade-offs**

-   **Consistency gaps** (replica lag, read-after-write anomalies).

-   **Conflicts** in multi-leader/leaderless topologies.

-   **Write amplification** and increased **storage/bandwidth**.

-   **Operational complexity** (failover, topology change, repair).

-   Risk of **split-brain** without robust coordination.


## Implementation (Key Points)

-   **Topology:** Single-leader (easiest), multi-leader (active-active), leaderless (Dynamo-style with quorums).

-   **Sync vs Async:**

    -   Sync: stronger guarantees, higher latency.

    -   Async: better latency/availability, risk of data loss on leader failure (tune RPO).

-   **Consistency Levels:** linearizable, sequential, causal, eventual; client-observed **session** or **monotonic** reads.

-   **Conflict Resolution:** LWW (Lamport time), app-specific merge, or **CRDTs** (sets, counters, maps) for convergent merges.

-   **Ordering:** WAL with offsets (term,index) or vector clocks for causality.

-   **Snapshots & Compaction:** Prevent unbounded logs; enable fast catch-up.

-   **Backpressure & Flow Control:** Don’t let lag explode; throttle producers.

-   **Idempotency:** Deduplicate with op IDs; make appliers idempotent.

-   **Security:** AuthN/Z between peers; encrypt in transit; per-region KMS.

-   **Operations:** Health probes, lag metrics, promotion runbooks, fencing tokens.


---

## Sample Code (Java 17): Tiny CRDT G-Counter with Gossip Replication

> This example demonstrates **leaderless, eventually consistent replication** using a **Grow-Only Counter (GCounter)** CRDT. Each node maintains a per-node integer. Increments only increase local state; **merge** takes pairwise max per node-id, guaranteeing convergence without conflicts. A lightweight “gossip” thread periodically exchanges and merges states with peers.

```java
// File: GossipGCounterDemo.java
// Compile & run multiple processes with different ports to see convergence.
//   javac GossipGCounterDemo.java
//   java GossipGCounterDemo 7001 7002,7003
//   java GossipGCounterDemo 7002 7001,7003
//   java GossipGCounterDemo 7003 7001,7002
//
// Then POST increments: curl -XPOST localhost:7001/inc?by=5
// Check values:        curl localhost:7002/value

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.OutputStream;
import java.net.*;
import java.net.http.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;

public class GossipGCounterDemo {

    // --- CRDT: Grow-only Counter (per-node map, merge = pointwise max) ---
    static class GCounter {
        private final Map<String, Long> counts = new ConcurrentHashMap<>();

        public void inc(String nodeId, long by) {
            counts.merge(nodeId, by, Long::sum); // grow-only
        }

        public long value() {
            return counts.values().stream().mapToLong(Long::longValue).sum();
        }

        // Merge another counter: for each node, take the max seen so far
        public synchronized void merge(Map<String, Long> other) {
            for (var e : other.entrySet()) {
                counts.merge(e.getKey(), e.getValue(), Math::max);
            }
        }

        public synchronized Map<String, Long> snapshot() {
            return new HashMap<>(counts);
        }
    }

    static class Node {
        final String nodeId;
        final int port;
        final List<Integer> peers;
        final GCounter counter = new GCounter();
        final HttpClient http = HttpClient.newBuilder()
                .connectTimeout(Duration.ofMillis(500)).build();
        final ScheduledExecutorService ses = Executors.newScheduledThreadPool(2);
        final AtomicLong gossipRounds = new AtomicLong();

        Node(int port, List<Integer> peers) {
            this.nodeId = "n" + port;
            this.port = port;
            this.peers = peers;
        }

        void start() throws IOException {
            // seed with zero for this node id
            counter.inc(nodeId, 0);

            // HTTP API
            HttpServer srv = HttpServer.create(new InetSocketAddress(port), 0);
            srv.createContext("/inc", this::incHandler);
            srv.createContext("/value", this::valueHandler);
            srv.createContext("/state", this::stateHandler);     // GET and POST for gossip
            srv.setExecutor(Executors.newCachedThreadPool());
            srv.start();

            // Gossip loop: periodically push our state to a random peer (best-effort)
            ses.scheduleAtFixedRate(this::gossipOnce, 500, 500, TimeUnit.MILLISECONDS);

            System.out.println("Node " + nodeId + " listening on :" + port + " peers=" + peers);
        }

        void stop() {
            ses.shutdownNow();
        }

        private void incHandler(HttpExchange ex) throws IOException {
            var q = Optional.ofNullable(ex.getRequestURI().getQuery()).orElse("by=1");
            long by = Arrays.stream(q.split("&"))
                    .filter(s -> s.startsWith("by="))
                    .findFirst().map(s -> Long.parseLong(s.substring(3))).orElse(1L);
            counter.inc(nodeId, by);
            respond(ex, 200, "ok\n");
        }

        private void valueHandler(HttpExchange ex) throws IOException {
            respond(ex, 200, counter.value() + "\n");
        }

        // GET /state -> JSON-like map;  POST /state with body "k:v,k2:v2" to merge
        private void stateHandler(HttpExchange ex) throws IOException {
            if ("GET".equalsIgnoreCase(ex.getRequestMethod())) {
                respond(ex, 200, serialize(counter.snapshot()));
            } else if ("POST".equalsIgnoreCase(ex.getRequestMethod())) {
                String body = new String(ex.getRequestBody().readAllBytes());
                counter.merge(deserialize(body));
                respond(ex, 200, "merged\n");
            } else {
                respond(ex, 405, "method not allowed\n");
            }
        }

        private void gossipOnce() {
            if (peers.isEmpty()) return;
            int idx = ThreadLocalRandom.current().nextInt(peers.size());
            int peerPort = peers.get(idx);
            String body = serialize(counter.snapshot());
            HttpRequest req = HttpRequest.newBuilder(URI.create("http://localhost:" + peerPort + "/state"))
                    .timeout(Duration.ofMillis(400))
                    .POST(HttpRequest.BodyPublishers.ofString(body))
                    .header("content-type", "text/plain")
                    .build();
            http.sendAsync(req, HttpResponse.BodyHandlers.discarding())
                    .orTimeout(400, TimeUnit.MILLISECONDS)
                    .whenComplete((r, e) -> gossipRounds.incrementAndGet());
        }

        private static String serialize(Map<String, Long> m) {
            // compact "n7001:12,n7002:7"
            StringBuilder sb = new StringBuilder();
            boolean first = true;
            for (var e : m.entrySet()) {
                if (!first) sb.append(',');
                sb.append(e.getKey()).append(':').append(e.getValue());
                first = false;
            }
            return sb.toString();
        }

        private static Map<String, Long> deserialize(String s) {
            Map<String, Long> m = new HashMap<>();
            if (s == null || s.isBlank()) return m;
            for (String p : s.split(",")) {
                if (p.isBlank()) continue;
                String[] kv = p.split(":");
                m.put(kv[0], Long.parseLong(kv[1]));
            }
            return m;
        }

        private static void respond(HttpExchange ex, int code, String msg) throws IOException {
            byte[] bytes = msg.getBytes();
            ex.getResponseHeaders().add("content-type", "text/plain; charset=utf-8");
            ex.sendResponseHeaders(code, bytes.length);
            try (OutputStream os = ex.getResponseBody()) { os.write(bytes); }
        }
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.out.println("Usage: java GossipGCounterDemo <port> [peerPortsCSV]");
            return;
        }
        int port = Integer.parseInt(args[0]);
        List<Integer> peers = new ArrayList<>();
        if (args.length >= 2 && !args[1].isBlank()) {
            for (String p : args[1].split(",")) peers.add(Integer.parseInt(p.trim()));
        }
        Node n = new Node(port, peers);
        n.start();
    }
}
```

**What this shows**

-   **Leaderless replication** with **eventual consistency** and **conflict-free** merge.

-   Nodes can increment independently; their states converge via gossip merges.


> For a leader-based approach, swap the CRDT with a simple **WAL entry** that followers apply in order, and commit only after a **quorum** of acks (majority). That yields stronger (often linearizable) semantics at the cost of latency.

---

## Known Uses

-   **Databases:** PostgreSQL streaming replication; MySQL primary–replica; MongoDB replica sets; SQL Server AGs; Oracle Data Guard.

-   **Dynamo-style stores:** Amazon DynamoDB global tables; Apache Cassandra/Scylla (quorums, hinted handoff, read repair).

-   **Consensus-replicated logs:** Etcd, Consul, ZooKeeper (Raft/Zab) for config/locks.

-   **Streams:** Apache Kafka ISR replication; Redpanda.

-   **Caches/Key-value:** Redis replication & Redis Cluster; Hazelcast/Infinispan.

-   **Object stores & filesystems:** S3 CRR, HDFS replication, Ceph/RADOS, MinIO.


## Related Patterns

-   **Sharding/Partitioning:** Split dataset across nodes; often combined with replication per shard.

-   **Consensus (Raft/Paxos/Zab):** Order and commit replicated logs.

-   **Event Sourcing / Write-Ahead Log:** Capture changes as an append-only log for shipping to replicas.

-   **Quorum / Read-Repair / Anti-Entropy:** Healing and consistency techniques.

-   **Leader Election / Fencing:** Safe promotion and split-brain prevention.

-   **Cache & CDN:** Replicate immutable content to edges.

-   **CQRS:** Direct reads to replicas optimized for queries.


---

### Production Tips

-   Define **RPO/RTO** targets; choose sync/async per data class.

-   Expose **lag metrics** (seconds/bytes/LSN); alert on thresholds.

-   Implement **fencing tokens** on failover to avoid dual leaders.

-   Prefer **idempotent** appliers and **dedupe** on operation IDs.

-   For multi-region, prefer **conflict-free types** (CRDTs) or clear, deterministic merge rules.
