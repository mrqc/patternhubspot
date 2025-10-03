# Cloud Distributed Systems Pattern — Service Discovery

## Pattern Name and Classification

-   **Name:** Service Discovery

-   **Classification:** Structural / Integration pattern for distributed systems (runtime infrastructure).


## Intent

Enable services to **find** other services’ current **network locations** (IPs/ports/endpoints) at runtime, despite dynamic scaling, failures, and relocations.

## Also Known As

-   Service Registry

-   Naming Service

-   Service Directory

-   DNS-SRV/Endpoint Discovery


## Motivation (Forces)

-   **Dynamic Topology:** Instances scale up/down; IPs change (containers, autoscaling).

-   **Decoupling:** Callers shouldn’t hardcode addresses or require manual config.

-   **Health & Freshness:** Only route to **alive** instances; remove stale entries quickly.

-   **Latency & Locality:** Prefer same-zone/region; fall back across zones.

-   **Consistency vs. Availability:** Strongly consistent registry vs. eventually consistent caches.

-   **Load & Chatter:** Avoid overloading the registry; use caching/watch/TTL.

-   **Security:** Authn/z for register/resolve; avoid rogue registrations; support mTLS.

-   **Heterogeneity:** Multiple protocols (HTTP, gRPC, TCP), weights, metadata for routing.


## Applicability

Use Service Discovery when:

-   You run **many** services/instances that change frequently (Kubernetes, ECS, Nomad, VM ASGs).

-   You need **client-side load balancing** or smart routing (metadata/weights/affinity).

-   You require **multi-AZ/region** awareness and failover.


Avoid/trim when:

-   Topology is static (a handful of stable endpoints).

-   A managed platform already provides reliable discovery (e.g., k8s Services + DNS), and you don’t need extras.


## Structure

-   **Service Registry:** Authoritative catalog of service instances (name → {endpoint, meta, ttl, health}).

-   **Providers:** Register/renew/deregister themselves; optionally send heartbeats.

-   **Consumers:** Resolve service name to healthy instances; cache and watch changes.

-   **Health Prober (optional):** Active/passive checks to suppress bad instances.

-   **Discovery Client (lib/sidecar):** Implements policy (caching, filtering, balancing).

-   **(Optional) Discovery via DNS:** Registry exposes records (A/AAAA/SRV) consumed by standard resolvers.


## Participants

-   **Registry API:** `register`, `renew`, `deregister`, `resolve`, optionally `watch`.

-   **Lease/TTL Manager:** Expires non-renewed instances.

-   **Health Monitor:** Marks instances healthy/unhealthy.

-   **Policy Engine:** Locality, weights, metadata selectors (e.g., version=blue).

-   **Cache/Subscriber:** Keeps a fresh local view with TTL or stream updates.

-   **Security Gate:** Authenticates nodes; enforces ownership of registrations.


## Collaboration

1.  **Provider** starts, obtains credentials, **registers** with the **Registry** (TTL lease + metadata).

2.  Provider periodically **renews** lease (heartbeat).

3.  **Consumer** asks the Registry (or local cache/agent) to **resolve** `serviceName`.

4.  Registry returns **healthy** instances (+weights/metadata).

5.  Consumer uses a **balancing policy** to pick one; on failure it may retry a different instance.

6.  On crash or network loss, TTL **expires** → instance is purged without manual cleanup.


## Consequences

**Benefits**

-   Decouples callers from concrete addresses → enables **elasticity** and **zero-touch** rollouts.

-   Improves **resilience** via quick suppression of failed instances.

-   Enables **policy-based routing** (locality, canary, version pinning).


**Liabilities / Trade-offs**

-   The registry is **critical infrastructure**; must be highly available and partition-tolerant.

-   Stale caches cause **misroutes**; short TTLs increase traffic/chatter.

-   Security & multi-tenant hygiene add complexity (auth, ACLs, cert rotation).

-   Eventual consistency can yield brief **inconsistencies** between clients.


## Implementation (Key Points)

-   **API shape:** Keep it minimal (`register/renew/deregister/resolve`), add `watch` when you can stream.

-   **Leases/TTLs:** Use **short TTLs** (e.g., 10–30s) + renew every 1/3–1/2 TTL; auto-expire.

-   **Health:** Combine **passive** outlier detection (5xx/timeouts) with **active** checks.

-   **Caching:** Clients should cache with TTL and/or subscribe to change streams.

-   **Locality:** Encode **zone/region** and prefer same-zone to reduce cross-AZ costs.

-   **Weights/Metadata:** Support canary (`version=blue`), hardware classes, capabilities.

-   **HA & Storage:** Run the registry as a replicated cluster (e.g., Raft/etcd/Consul/ZooKeeper) or leverage k8s API server.

-   **DNS integration:** Optionally expose SRV records (`_svc._proto.name`) for broad compatibility.

-   **Security:** mTLS between clients and registry; **signed registrations**; ACLs by service identity.

-   **Observability:** Count registrations, renewals, expirations; per-service instance counts; resolve latency.


---

## Sample Code (Java 17): Minimal TTL-Based Registry + Client (HTTP)

> Educational single-file demo showing:
>
> -   Registry with **register/renew/deregister/resolve** and TTL expiry
>
> -   Providers **self-register** and renew
>
> -   Consumer library with **cached resolution** and **round-robin** choice
>
> -   Uses only JDK `HttpServer`/`HttpClient`
>

```java
// File: MiniServiceDiscovery.java
// Compile & run registry:  javac MiniServiceDiscovery.java && java MiniServiceDiscovery registry 7070
// Register a provider:     java MiniServiceDiscovery provider orders http://localhost:9001 7070
// Resolve as consumer:     java MiniServiceDiscovery consumer orders 7070
import com.sun.net.httpserver.*;
import java.io.*;
import java.net.*;
import java.net.http.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Collectors;

public class MiniServiceDiscovery {

    // ==== Domain ====
    static final class Instance {
        final String service;
        final URI endpoint;
        final String zone; // optional locality tag
        final Map<String,String> meta;
        volatile long expiresAt; // epoch millis

        Instance(String service, URI endpoint, String zone, Map<String,String> meta, long ttlMillis) {
            this.service = service;
            this.endpoint = endpoint;
            this.zone = zone;
            this.meta = meta;
            this.expiresAt = System.currentTimeMillis() + ttlMillis;
        }
        boolean expired() { return System.currentTimeMillis() > expiresAt; }
        void renew(long ttlMillis) { this.expiresAt = System.currentTimeMillis() + ttlMillis; }
        public String toString() { return service + "@" + endpoint + " zone=" + zone + " expires=" + expiresAt; }
    }

    // ==== Registry Server ====
    static final class Registry {
        private final Map<String, List<Instance>> byService = new ConcurrentHashMap<>();
        private final ScheduledExecutorService janitor = Executors.newSingleThreadScheduledExecutor();
        private final long defaultTtlMillis;

        Registry(long defaultTtlMillis) {
            this.defaultTtlMillis = defaultTtlMillis;
            janitor.scheduleAtFixedRate(this::sweep, 1, 1, TimeUnit.SECONDS);
        }
        void stop() { janitor.shutdownNow(); }

        void register(String service, URI endpoint, String zone, Map<String,String> meta, Long ttlMs) {
            long ttl = ttlMs != null ? ttlMs : defaultTtlMillis;
            var inst = new Instance(service, endpoint, zone, meta, ttl);
            byService.compute(service, (k, list) -> {
                List<Instance> l = (list == null) ? new CopyOnWriteArrayList<>() : (List<Instance>) list;
                // idempotent: if same endpoint exists, renew instead
                for (Instance i : l) {
                    if (i.endpoint.equals(endpoint)) { i.renew(ttl); return l; }
                }
                l.add(inst);
                return l;
            });
        }
        boolean renew(String service, URI endpoint, Long ttlMs) {
            var list = byService.getOrDefault(service, List.of());
            for (Instance i : list) {
                if (i.endpoint.equals(endpoint)) { i.renew(ttlMs != null ? ttlMs : defaultTtlMillis); return true; }
            }
            return false;
        }
        boolean deregister(String service, URI endpoint) {
            var list = byService.get(service);
            if (list == null) return false;
            return list.removeIf(i -> i.endpoint.equals(endpoint));
        }
        List<Instance> resolve(String service) {
            var list = byService.getOrDefault(service, List.of());
            return list.stream().filter(i -> !i.expired()).collect(Collectors.toList());
        }
        private void sweep() {
            byService.values().forEach(list -> list.removeIf(Instance::expired));
        }
    }

    // ==== Lightweight HTTP API for Registry ====
    static void startRegistryHttp(int port, long defaultTtlMillis) throws IOException {
        Registry reg = new Registry(defaultTtlMillis);
        HttpServer s = HttpServer.create(new InetSocketAddress(port), 0);

        s.createContext("/register", ex -> {
            var q = query(ex.getRequestURI());
            String service = q.getOrDefault("service", "");
            String endpoint = q.getOrDefault("endpoint", "");
            String zone = q.getOrDefault("zone", "z-default");
            Long ttl = q.containsKey("ttlMs") ? Long.parseLong(q.get("ttlMs")) : null;
            Map<String,String> meta = q.entrySet().stream()
                    .filter(e -> e.getKey().startsWith("meta."))
                    .collect(Collectors.toMap(
                            e -> e.getKey().substring("meta.".length()), Map.Entry::getValue));
            if (service.isBlank() || endpoint.isBlank()) { send(ex, 400, "missing service/endpoint"); return; }
            reg.register(service, URI.create(endpoint), zone, meta, ttl);
            send(ex, 200, "ok");
        });

        s.createContext("/renew", ex -> {
            var q = query(ex.getRequestURI());
            String service = q.getOrDefault("service", "");
            String endpoint = q.getOrDefault("endpoint", "");
            Long ttl = q.containsKey("ttlMs") ? Long.parseLong(q.get("ttlMs")) : null;
            boolean ok = reg.renew(service, URI.create(endpoint), ttl);
            send(ex, ok ? 200 : 404, ok ? "ok" : "not found");
        });

        s.createContext("/deregister", ex -> {
            var q = query(ex.getRequestURI());
            boolean ok = reg.deregister(q.get("service"), URI.create(q.get("endpoint")));
            send(ex, ok ? 200 : 404, ok ? "ok" : "not found");
        });

        s.createContext("/resolve", ex -> {
            var q = query(ex.getRequestURI());
            String service = q.getOrDefault("service", "");
            if (service.isBlank()) { send(ex, 400, "missing service"); return; }
            List<Instance> list = reg.resolve(service);
            String json = listToJson(list);
            var bytes = json.getBytes();
            ex.getResponseHeaders().add("content-type", "application/json");
            ex.sendResponseHeaders(200, bytes.length);
            try (var os = ex.getResponseBody()) { os.write(bytes); }
        });

        s.setExecutor(Executors.newCachedThreadPool());
        System.out.println("Registry listening on http://localhost:" + port + "  (TTL default=" + defaultTtlMillis + " ms)");
        s.start();
    }

    // ==== Consumer Library (cached discovery + RR selection) ====
    static final class DiscoveryClient {
        private final HttpClient http = HttpClient.newHttpClient();
        private final URI registryBase;
        private final Map<String, CacheEntry> cache = new ConcurrentHashMap<>();
        private final String preferredZone;
        static final class CacheEntry {
            List<Instance> instances = List.of();
            long expiresAt;
            final AtomicInteger rr = new AtomicInteger();
        }
        DiscoveryClient(URI registryBase, String preferredZone) { this.registryBase = registryBase; this.preferredZone = preferredZone; }

        List<Instance> resolve(String service, long ttlMs) throws Exception {
            CacheEntry ce = cache.computeIfAbsent(service, k -> new CacheEntry());
            if (System.currentTimeMillis() < ce.expiresAt && !ce.instances.isEmpty()) return ce.instances;

            URI u = registryBase.resolve("/resolve?service=" + URLEncoder.encode(service, "UTF-8"));
            HttpRequest req = HttpRequest.newBuilder(u).GET().timeout(Duration.ofSeconds(1)).build();
            HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() != 200) throw new RuntimeException("resolve failed: " + resp.statusCode());
            List<Instance> list = parseJson(resp.body());
            // zone preference first
            List<Instance> sorted = new ArrayList<>(list);
            sorted.sort(Comparator.comparing((Instance i) -> !Objects.equals(i.zone, preferredZone)));
            ce.instances = sorted;
            ce.expiresAt = System.currentTimeMillis() + ttlMs;
            return ce.instances;
        }

        Optional<Instance> pick(String service, long cacheTtlMs) throws Exception {
            List<Instance> list = resolve(service, cacheTtlMs);
            if (list.isEmpty()) return Optional.empty();
            CacheEntry ce = cache.get(service);
            int i = Math.floorMod(ce.rr.getAndIncrement(), list.size());
            return Optional.of(list.get(i));
        }
    }

    // ==== Provider helper (register + renew loop) ====
    static void providerLoop(String service, URI endpoint, int registryPort, long ttlMs) throws Exception {
        HttpClient http = HttpClient.newHttpClient();
        URI base = URI.create("http://localhost:" + registryPort);
        Runnable register = () -> {
            try {
                URI u = base.resolve(String.format("/register?service=%s&endpoint=%s&zone=%s&ttlMs=%d",
                        URLEncoder.encode(service, "UTF-8"),
                        URLEncoder.encode(endpoint.toString(), "UTF-8"),
                        URLEncoder.encode("z-a", "UTF-8"),
                        ttlMs));
                http.send(HttpRequest.newBuilder(u).GET().build(), HttpResponse.BodyHandlers.discarding());
                System.out.println("Registered: " + service + " -> " + endpoint);
            } catch (Exception e) { System.err.println("register failed: " + e); }
        };
        register.run();
        ScheduledExecutorService ses = Executors.newSingleThreadScheduledExecutor();
        ses.scheduleAtFixedRate(() -> {
            try {
                URI u = base.resolve(String.format("/renew?service=%s&endpoint=%s&ttlMs=%d",
                        URLEncoder.encode(service, "UTF-8"),
                        URLEncoder.encode(endpoint.toString(), "UTF-8"),
                        ttlMs));
                http.send(HttpRequest.newBuilder(u).GET().build(), HttpResponse.BodyHandlers.discarding());
            } catch (Exception e) { System.err.println("renew failed: " + e); }
        }, ttlMs / 3, ttlMs / 3, TimeUnit.MILLISECONDS);
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            try {
                URI u = base.resolve(String.format("/deregister?service=%s&endpoint=%s",
                        URLEncoder.encode(service, "UTF-8"),
                        URLEncoder.encode(endpoint.toString(), "UTF-8")));
                http.send(HttpRequest.newBuilder(u).GET().build(), HttpResponse.BodyHandlers.discarding());
            } catch (Exception ignored) {}
        }));
        System.out.println("Provider heartbeat running. Ctrl+C to exit.");
    }

    // ==== CLI Entrypoints ====
    public static void main(String[] args) throws Exception {
        if (args.length == 0) {
            System.out.println("""
                usage:
                  registry <port> [ttlMs]
                  provider <service> <endpointUri> <registryPort> [ttlMs]
                  consumer <service> <registryPort> [zone]
                """);
            return;
        }
        switch (args[0]) {
            case "registry" -> {
                int port = Integer.parseInt(args[1]);
                long ttl = args.length > 2 ? Long.parseLong(args[2]) : 15000;
                startRegistryHttp(port, ttl);
            }
            case "provider" -> {
                String service = args[1];
                URI endpoint = URI.create(args[2]);
                int regPort = Integer.parseInt(args[3]);
                long ttl = args.length > 4 ? Long.parseLong(args[4]) : 15000;
                providerLoop(service, endpoint, regPort, ttl);
            }
            case "consumer" -> {
                String service = args[1];
                int regPort = Integer.parseInt(args[2]);
                String zone = args.length > 3 ? args[3] : "z-a";
                DiscoveryClient dc = new DiscoveryClient(URI.create("http://localhost:" + regPort), zone);
                for (int i = 0; i < 5; i++) {
                    Optional<Instance> inst = dc.pick(service, 2000);
                    System.out.println("Pick[" + i + "]: " + inst.map(x -> x.endpoint + " (" + x.zone + ")").orElse("<none>"));
                    Thread.sleep(500);
                }
            }
        }
    }

    // ==== Tiny helpers (stringy JSON to keep it concise) ====
    static Map<String,String> query(URI u) throws UnsupportedEncodingException {
        Map<String,String> map = new HashMap<>();
        String q = u.getRawQuery();
        if (q == null) return map;
        for (String kv : q.split("&")) {
            int i = kv.indexOf('=');
            String k = URLDecoder.decode(i < 0 ? kv : kv.substring(0, i), "UTF-8");
            String v = i < 0 ? "" : URLDecoder.decode(kv.substring(i + 1), "UTF-8");
            map.put(k, v);
        }
        return map;
    }
    static String listToJson(List<Instance> list) {
        return list.stream().map(i ->
                String.format(Locale.ROOT,
                        "{\"service\":\"%s\",\"endpoint\":\"%s\",\"zone\":\"%s\",\"expiresAt\":%d}",
                        esc(i.service), esc(i.endpoint.toString()), esc(i.zone), i.expiresAt))
                .collect(Collectors.joining(",", "[", "]"));
    }
    static List<Instance> parseJson(String json) {
        // naive parser for demo: expects the format from listToJson
        List<Instance> out = new ArrayList<>();
        if (json == null || json.isBlank() || json.equals("[]")) return out;
        String body = json.substring(1, json.length() - 1);
        for (String obj : body.split("(?<=\\}),")) {
            Map<String,String> m = new HashMap<>();
            for (String f : obj.replaceAll("[\\{\\}\"]","").split(",")) {
                int i = f.indexOf(':'); if (i <= 0) continue;
                m.put(f.substring(0,i), f.substring(i+1));
            }
            out.add(new Instance(
                    m.get("service"),
                    URI.create(m.get("endpoint")),
                    m.getOrDefault("zone","z-default"),
                    Map.of(),
                    10_000)); // TTL unused on client side
        }
        return out;
    }
    static String esc(String s) { return s.replace("\"","\\\""); }
    static void send(HttpExchange ex, int code, String msg) throws IOException {
        byte[] b = msg.getBytes();
        ex.getResponseHeaders().add("content-type","text/plain; charset=utf-8");
        ex.sendResponseHeaders(code, b.length);
        try (var os = ex.getResponseBody()) { os.write(b); }
    }
}
```

**How to try (quick demo)**

1.  Start the **registry**:  
    `javac MiniServiceDiscovery.java && java MiniServiceDiscovery registry 7070`

2.  Simulate two **providers** (in two terminals):

    -   `java MiniServiceDiscovery provider orders http://localhost:9001 7070`

    -   `java MiniServiceDiscovery provider orders http://localhost:9002 7070`

3.  From a **consumer**:  
    `java MiniServiceDiscovery consumer orders 7070`  
    You’ll see alternating picks; kill one provider and watch it disappear after TTL expiry.


---

## Known Uses

-   **Kubernetes:** `kube-apiserver` + Endpoints/EndpointSlices + `kube-dns/CoreDNS` (cluster IPs & DNS).

-   **Consul:** Key/value + health checks; DNS & HTTP APIs; widely used for VM/container fleets.

-   **etcd/ZooKeeper:** Backing stores for discovery systems; direct usage in some stacks.

-   **Eureka (Netflix OSS):** Client-side discovery with self-registration and renewals.

-   **Cloud providers:** AWS Cloud Map, AWS NLB+Target Groups, GCP Service Directory, Azure Private DNS/Service Discovery.


## Related Patterns

-   **Load Balancer:** Often paired; can be server-side (edge) or client-side using discovery.

-   **Circuit Breaker & Outlier Detection:** Suppress bad instances between registry refreshes.

-   **Health Check / Heartbeat:** Foundation for accurate liveness in the registry.

-   **Blue-Green / Canary / Traffic Shadowing:** Use metadata/weights to steer traffic.

-   **Retry with Backoff:** When resolution gives multiple instances, retry on **different** instance.

-   **Service Mesh:** Sidecars (Envoy) subscribe to discovery (xDS) and apply richer policies.


---

### Practical tips

-   Default TTL around **10–30s**, renew every **3–10s**.

-   Always include **zone/region** and **version** labels; prefer same-zone first.

-   Cache with TTL and **coalesce** refreshes to avoid stampedes.

-   Secure the registry (mTLS + ACLs); only owners can register their services.

-   Emit metrics: active instances per service, resolve latency, expiry counts, watch lag.
