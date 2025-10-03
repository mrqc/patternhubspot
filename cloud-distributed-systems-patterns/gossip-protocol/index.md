# Gossip Protocol — Cloud Distributed Systems Pattern

## Pattern Name and Classification

-   **Name:** Gossip Protocol (a.k.a. Epidemic Dissemination)

-   **Category:** Distributed Systems / Communication & Coordination / Scalability Pattern


## Intent

Efficiently and robustly disseminate state (membership, key–value updates, health) across a large, unreliable cluster using **probabilistic**, **peer-to-peer**, **periodic** exchanges rather than centralized coordination.

## Also Known As

-   Epidemic protocols

-   Anti-entropy protocols (push / pull / push–pull)

-   Rumor mongering

-   SWIM-style membership gossip (when failure detector & suspicion are included)


## Motivation (Forces)

Building large clusters faces competing forces:

-   **Scalability:** O(N) fan-out or centralized brokers become bottlenecks; gossip aims for **logarithmic spread** and constant per-node work.

-   **Fault tolerance:** Nodes and links fail; gossip avoids single points of failure.

-   **Churn & partitions:** Membership must converge despite joins/leaves/splits.

-   **Timeliness vs. Cost:** Faster convergence requires higher fan-out and frequency; cost grows with traffic.

-   **Eventual consistency:** Perfect simultaneity is impossible; accept **probabilistic guarantees** with bounded staleness.

-   **Heterogeneity:** Nodes differ in capacity; the protocol must stay stable without global coordination.


## Applicability

Use gossip when you need:

-   Cluster **membership/health** dissemination without a central coordinator.

-   **Metadata/state** propagation (e.g., shard maps, config flags) with eventual consistency.

-   **Failure detection** at scale (SWIM-like suspicion + dissemination).

-   **Anti-entropy** synchronization in weakly connected, high-churn environments.


Avoid or augment it when:

-   You require **strong consistency/linearizability** for updates (consider Raft/Paxos).

-   The cluster is small, static, and a central registry is simpler.

-   Network policy forbids frequent background traffic.


## Structure

-   **Node:** Maintains local state, versioning (e.g., version vectors), peer list, timers.

-   **Peer Sampler:** Selects peers uniformly (or biased) each round.

-   **Gossip Exchange:**

    -   **Digest:** summary of known versions

    -   **Delta:** missing updates

    -   **Ack/Nack:** optional; SWIM uses ping/ack + suspect

-   **Failure Detector:** Heartbeat timestamps or φ-accrual; disseminates **suspect** and **confirm** events.

-   **Transport:** UDP/TCP/QUIC or an app-level RPC.


```scss
Node
 ├─ StateStore (KV + versions)
 ├─ Membership (alive/suspect/faulty, incarnation)
 ├─ FailureDetector (timeouts/φ)
 └─ GossipTask (periodic push–pull with random peers)
```

## Participants

-   **Gossiper:** Initiates periodic exchanges.

-   **Peer:** Responds with digests/deltas.

-   **State Store:** Applies and versions updates (last-writer-wins, vector clocks, CRDTs).

-   **Failure Detector:** Classifies peers; emits membership updates.

-   **Transport Adapter:** Encodes messages, handles retry/timeouts.


## Collaboration

1.  Every `T` ms, a node picks one or more peers via the **Peer Sampler**.

2.  Node sends a **Digest** of (key → version) + **membership** view.

3.  Peer computes set differences; replies with **Delta** for missing/older items and optionally requests its own missing items (push–pull).

4.  Both sides apply updates and bump timestamps/incarnations.

5.  **Failure detector** marks peers suspect on missed acks; membership changes are themselves spread via gossip.


## Consequences

**Pros**

-   **Scales**: O(1) work per node per round; expected logarithmic dissemination time.

-   **Highly available**: No central coordinator; tolerant to failures/partitions.

-   **Simple & adaptive**: Works under churn; easy to extend (e.g., piggyback metrics).


**Cons**

-   **Probabilistic guarantees**: No strict delivery order or global snapshot.

-   **Background traffic**: Constant trickle; must be tuned for WAN.

-   **Staleness**: Eventual consistency; readers may see old state.

-   **Duplicate delivery**: Requires idempotent updates / versioning.

-   **Pathological topologies**: Need good peer sampling (random walk bias mitigation).


**Trade-offs**

-   Tuning (**interval**, **fan-out**, **TTL**, **infection-style backoff**) balances convergence vs. bandwidth.

-   Choice of versioning: LWW (simple) vs. vector clocks/CRDTs (conflict-aware).


## Implementation (Guidelines)

-   **Message Types:** `Digest`, `RequestMissing(keys)`, `Delta(updates)`, `Ping/Ack`, `Suspect/Confirm`.

-   **Versioning:**

    -   Simple: `(version: long, timestamp)` per key.

    -   Robust: **vector clocks** or **CRDTs** for commutativity/idempotence.

-   **Membership:** Track `(status, incarnation)`; only accept higher-incarnation changes.

-   **Failure Detection:** φ-accrual or fixed timeouts; disseminate suspicion to avoid false positives.

-   **Peer Sampling:** Uniform random from `alive`; optionally **Helia/HyParView** for robust overlays.

-   **Anti-Entropy:** Periodically reconcile full digests to heal long partitions.

-   **Backpressure:** Cap delta sizes; chunk large updates; exponential backoff under loss.

-   **Security:** Authenticate messages (MAC/TLS), rate-limit, and partition by cluster ID.


---

## Sample Code (Java, in-JVM simulation of push–pull gossip)

> Notes:
>
> -   Simulates a network bus with per-node queues.
>
> -   Uses simple LWW versions for a KV store + basic membership & heartbeats.
>
> -   Focuses on core gossip mechanics, not production transport/security.
>

```java
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;

/** ---------- Messages ---------- */
sealed interface Msg permits Digest, Delta, RequestMissing, Ping, Ack {
    String to; String from;
}
record Digest(String to, String from,
              Map<String, Long> kvVersions,    // key -> version
              Map<String, Member> membership) implements Msg {}
record RequestMissing(String to, String from,
                      Set<String> missingKeys,
                      Set<String> missingMembers) implements Msg {}
record Delta(String to, String from,
             Map<String, KV> kvUpdates,        // idempotent LWW
             Map<String, Member> membershipUpdates) implements Msg {}
record Ping(String to, String from, long ts) implements Msg {}
record Ack(String to, String from, long ts) implements Msg {}

/** ---------- Data Models ---------- */
record KV(String key, String value, long version, long timestampMs) {}

enum Status { ALIVE, SUSPECT, DEAD }
record Member(String nodeId, Status status, long incarnation, long lastHeardMs) {
    Member bumpLastHeard(long now) { return new Member(nodeId, status, incarnation, now); }
    Member with(Status s, long inc) { return new Member(nodeId, s, inc, lastHeardMs); }
}

/** ---------- Simulated Network Bus ---------- */
class Bus {
    private final Map<String, BlockingQueue<Msg>> queues = new ConcurrentHashMap<>();
    void register(String nodeId) { queues.put(nodeId, new LinkedBlockingQueue<>()); }
    void send(Msg m) { Optional.ofNullable(queues.get(m.to())).ifPresent(q -> q.offer(m)); }
    Msg recv(String nodeId, long timeoutMs) throws InterruptedException {
        return queues.get(nodeId).poll(timeoutMs, TimeUnit.MILLISECONDS);
    }
    Set<String> nodes() { return queues.keySet(); }
}

/** ---------- Node ---------- */
class Node implements Runnable {
    final String id;
    final Bus bus;
    final Random rnd = new Random();
    final ScheduledExecutorService ses = Executors.newScheduledThreadPool(2);
    final Map<String, KV> store = new ConcurrentHashMap<>();
    final Map<String, Member> members = new ConcurrentHashMap<>();
    final AtomicLong versionGen = new AtomicLong(0);
    final long gossipIntervalMs;
    final int fanout;

    Node(String id, Bus bus, long gossipIntervalMs, int fanout) {
        this.id = id; this.bus = bus; this.gossipIntervalMs = gossipIntervalMs; this.fanout = fanout;
        bus.register(id);
        long now = now();
        members.put(id, new Member(id, Status.ALIVE, 1, now));
    }

    // API: put a key locally and let gossip spread it
    void put(String key, String value) {
        long v = versionGen.incrementAndGet();
        store.put(key, new KV(key, value, v, now()));
    }

    // membership management (join)
    void join(Set<String> seeds) {
        // mark seeds as alive with incarnation 1
        long n = now();
        for (String s : seeds) {
            if (s.equals(id)) continue;
            members.putIfAbsent(s, new Member(s, Status.ALIVE, 1, n));
        }
    }

    @Override public void run() {
        // periodic gossip
        ses.scheduleAtFixedRate(this::gossipRound, 100, gossipIntervalMs, TimeUnit.MILLISECONDS);
        // periodic ping for failure detection
        ses.scheduleAtFixedRate(this::pingRandom, 200, gossipIntervalMs / 2, TimeUnit.MILLISECONDS);
        // message loop
        ses.execute(this::receiveLoop);
    }

    private void gossipRound() {
        List<String> peers = alivePeers();
        Collections.shuffle(peers, rnd);
        for (int i = 0; i < Math.min(fanout, peers.size()); i++) {
            String peer = peers.get(i);
            bus.send(new Digest(peer, id, kvVersions(), new HashMap<>(members)));
        }
    }

    private void pingRandom() {
        List<String> peers = alivePeers();
        if (peers.isEmpty()) return;
        String p = peers.get(rnd.nextInt(peers.size()));
        bus.send(new Ping(p, id, now()));
        // suspect on missing acks later (cheap heuristic)
        ses.schedule(() -> {
            Member m = members.get(p);
            if (m != null && now() - m.lastHeardMs() > gossipIntervalMs * 3 && m.status() == Status.ALIVE) {
                members.put(p, m.with(Status.SUSPECT, m.incarnation() + 1));
            }
        }, gossipIntervalMs * 2, TimeUnit.MILLISECONDS);
    }

    private void receiveLoop() {
        try {
            while (true) {
                Msg m = bus.recv(id, 500);
                if (m == null) continue;
                switch (m) {
                    case Digest d -> onDigest(d);
                    case RequestMissing rm -> onRequestMissing(rm);
                    case Delta d -> onDelta(d);
                    case Ping p -> { bus.send(new Ack(p.from(), id, p.ts())); onHeartbeat(p.from()); }
                    case Ack a  -> onHeartbeat(a.from());
                }
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    private void onHeartbeat(String from) {
        members.compute(from, (k, v) -> {
            if (v == null) return new Member(from, Status.ALIVE, 1, now());
            if (v.status() == Status.DEAD) return v; // ignore
            return v.with(Status.ALIVE, Math.max(v.incarnation(), 1)).bumpLastHeard(now());
        });
    }

    private void onDigest(Digest d) {
        onHeartbeat(d.from()); // observe liveness via any message
        // reconcile membership (accept higher incarnation or stronger status)
        mergeMembership(d.membership());
        // Determine missing/older KVs
        Set<String> needFromPeer = new HashSet<>();
        for (var e : d.kvVersions().entrySet()) {
            KV local = store.get(e.getKey());
            if (local == null || local.version() < e.getValue()) {
                needFromPeer.add(e.getKey());
            }
        }
        // Determine what peer needs from us
        Map<String, Long> peerVers = d.kvVersions();
        Set<String> peerNeeds = new HashSet<>();
        for (var e : store.entrySet()) {
            long peerV = peerVers.getOrDefault(e.getKey(), -1L);
            if (e.getValue().version() > peerV) peerNeeds.add(e.getKey());
        }
        // request and push simultaneously (push–pull)
        if (!needFromPeer.isEmpty() || !missingMembersFor(d.membership()).isEmpty()) {
            bus.send(new RequestMissing(d.from(), id, needFromPeer, missingMembersFor(d.membership())));
        }
        if (!peerNeeds.isEmpty()) {
            Map<String, KV> kvs = new HashMap<>();
            for (String k : peerNeeds) kvs.put(k, store.get(k));
            bus.send(new Delta(d.from(), id, kvs, membershipDeltaFor(d.membership())));
        }
    }

    private void onRequestMissing(RequestMissing r) {
        onHeartbeat(r.from());
        Map<String, KV> kvs = new HashMap<>();
        for (String k : r.missingKeys()) {
            KV val = store.get(k);
            if (val != null) kvs.put(k, val);
        }
        Map<String, Member> mems = new HashMap<>();
        for (String m : r.missingMembers()) {
            Member val = members.get(m);
            if (val != null) mems.put(m, val);
        }
        bus.send(new Delta(r.from(), id, kvs, mems));
    }

    private void onDelta(Delta d) {
        onHeartbeat(d.from());
        // Apply KV updates (LWW by version)
        for (KV kv : d.kvUpdates().values()) {
            store.merge(kv.key(), kv, (oldV, newV) -> newV.version() > oldV.version() ? newV : oldV);
        }
        // Apply membership updates
        mergeMembership(d.membershipUpdates());
    }

    private void mergeMembership(Map<String, Member> incoming) {
        long n = now();
        for (Member in : incoming.values()) {
            members.merge(in.nodeId(), in, (cur, inc) -> {
                // Prefer higher incarnation; if equal, prefer "worse" status
                if (inc.incarnation() > cur.incarnation()) return inc.bumpLastHeard(n);
                if (inc.incarnation() < cur.incarnation()) return cur;
                // Same incarnation: status order ALIVE < SUSPECT < DEAD
                int curRank = rank(cur.status()), incRank = rank(inc.status());
                if (incRank > curRank) return inc.bumpLastHeard(n);
                return cur.bumpLastHeard(n);
            });
        }
        // Garbage collect sustained SUSPECT -> DEAD
        members.replaceAll((k, v) -> {
            if (v.status() == Status.SUSPECT && now() - v.lastHeardMs() > gossipIntervalMs * 6) {
                return v.with(Status.DEAD, v.incarnation() + 1);
            }
            return v;
        });
    }

    private Map<String, Long> kvVersions() {
        Map<String, Long> m = new HashMap<>();
        for (var e : store.entrySet()) m.put(e.getKey(), e.getValue().version());
        return m;
    }

    private Set<String> missingMembersFor(Map<String, Member> peer) {
        Set<String> miss = new HashSet<>();
        for (String id : peer.keySet()) if (!members.containsKey(id)) miss.add(id);
        return miss;
    }

    private Map<String, Member> membershipDeltaFor(Map<String, Member> peer) {
        Map<String, Member> delta = new HashMap<>();
        for (var e : members.entrySet()) if (!peer.containsKey(e.getKey())) delta.put(e.getKey(), e.getValue());
        return delta;
    }

    private List<String> alivePeers() {
        List<String> peers = new ArrayList<>();
        for (var e : members.entrySet()) {
            if (!e.getKey().equals(id) && e.getValue().status() == Status.ALIVE) peers.add(e.getKey());
        }
        return peers;
    }

    private static int rank(Status s) { return switch (s) { case ALIVE -> 0; case SUSPECT -> 1; case DEAD -> 2; }; }
    static long now() { return Instant.now().toEpochMilli(); }

    // Debug helpers
    Map<String, String> viewKV() {
        Map<String, String> out = new TreeMap<>();
        for (var e : store.values()) out.put(e.key(), e.value() + " (v" + e.version() + ")");
        return out;
    }
    Map<String, Status> viewMembers() {
        Map<String, Status> out = new TreeMap<>();
        for (var e : members.values()) out.put(e.nodeId(), e.status());
        return out;
    }
}

/** ---------- Demo ---------- */
public class GossipDemo {
    public static void main(String[] args) throws Exception {
        Bus bus = new Bus();
        Node a = new Node("A", bus, 300, 2);
        Node b = new Node("B", bus, 300, 2);
        Node c = new Node("C", bus, 300, 2);
        a.join(Set.of("B","C")); b.join(Set.of("A","C")); c.join(Set.of("A","B"));
        new Thread(a).start(); new Thread(b).start(); new Thread(c).start();

        // Seed some data
        a.put("config/featureX", "on");
        Thread.sleep(1000);
        b.put("shardMap:v", "1");
        Thread.sleep(1500);
        c.put("config/featureX", "off"); // higher version wins (LWW)

        // Let gossip converge
        Thread.sleep(3000);
        System.out.println("A KV = " + a.viewKV());
        System.out.println("B KV = " + b.viewKV());
        System.out.println("C KV = " + c.viewKV());
        System.out.println("A Members = " + a.viewMembers());
    }
}
```

**What to try next**

-   Replace LWW with **vector clocks** or a **CRDT** (e.g., OR-Set, LWW-Register w/ tie-breaker).

-   Swap the in-JVM bus for **Netty/UDP**; piggyback membership on every message.

-   Add **φ-accrual** failure detector and **SWIM** suspicion/indirect probes.

-   Add **backpressure** and **chunked deltas** for large states.


## Known Uses

-   **Apache Cassandra / ScyllaDB** — cluster membership & schema/version propagation.

-   **Amazon Dynamo & Dynamo-inspired systems** — membership/state gossip with vector clocks.

-   **Riak** — ring membership and object replication coordination.

-   **HashiCorp Serf / Consul / Nomad** — SWIM-based membership & health dissemination.

-   **Akka Cluster** — gossip-based cluster membership and failure detection.

-   **Hazelcast / Infinispan** — cluster discovery and metadata sharing.

-   **Redis Cluster** — node state and slot map dissemination via gossip.


## Related Patterns

-   **Leader Election (Bully/Raft/Paxos):** Often paired; gossip disseminates membership while consensus provides strong coordination.

-   **Failure Detector (φ-accrual):** Component commonly embedded in SWIM-like gossip.

-   **CRDTs:** Conflict-free data types that mesh well with gossip’s eventual consistency.

-   **Publish/Subscribe:** Can sit atop gossip for topic metadata; or replace with brokered pub/sub when ordering is needed.

-   **Random Peer Sampling (e.g., HyParView):** Improves overlay robustness for epidemic protocols.

-   **Anti-Entropy / Merkle Trees:** Used by Dynamo/Cassandra for efficient repair alongside gossip discovery.

-   **Service Discovery:** Gossip-based membership as a substrate for discovery (as in Serf/Consul).


---

If you want, I can extend the sample with vector clocks, a φ-accrual detector, or a Netty-based UDP transport to make it closer to production.
