
# Cloud Distributed Systems Pattern — Throttling / Rate Limiting

## Pattern Name and Classification

-   **Name:** Throttling / Rate Limiting

-   **Classification:** Behavioral & Control pattern for distributed systems; resilience & abuse-prevention.


## Intent

Control how fast clients can make requests or consume resources by enforcing **limits over time** so systems stay stable, fair, and cost-bounded.

## Also Known As

-   Quotas / Request Quotas

-   Traffic Shaping

-   Flow Control

-   Backpressure (closely related)


## Motivation (Forces)

-   **Stability:** Prevent overload, brownouts, and cascading failures.

-   **Fairness:** Keep one tenant/key from starving others; isolate noisy neighbors.

-   **Cost & Abuse:** Keep within egress/API budgets; deter scraping/DDoS.

-   **Elasticity vs. Limits:** Allow short bursts without exceeding steady-state capacity.

-   **Accuracy vs. Complexity:** Precise limits (sliding windows) can be expensive at scale; probabilistic approaches are cheaper.

-   **Latency:** Server-side throttling must be fast and lock-light.

-   **Distributed coordination:** Global limits must work across many instances/regions.


## Applicability

Use when:

-   You expose public/internal APIs, webhooks, queues, or shared compute/storage.

-   You need per-**identity** controls (API key, user, tenant, IP, token claims).

-   You run multi-tenant or cost-sensitive workloads.


Less useful when:

-   Single-tenant, internal-only systems with ample headroom and hard external caps.


## Structure

-   **Limiter Policy:** e.g., *100 requests per minute, burst 50*.

-   **Key Extractor:** Maps request → limiter key(s) (apiKey, userId, orgId, IP, route).

-   **Limiter Engine:** Algorithm enforcing policy (Token Bucket, Leaky Bucket, Fixed Window, Sliding Window, GCRA).

-   **Store:** In-memory (per-instance), **distributed** (Redis, Memcached), or **global** (sharded DB).

-   **Enforcer / Middleware:** Intercepts requests, decides allow/deny, sets headers, returns 429.

-   **Observability:** Counters, hit/miss, rejections, hot keys.


## Participants

-   **Policy Registry:** Config source (static, DB, control plane) with defaults & overrides.

-   **Request Classifier:** Chooses key(s) and policy per request/route.

-   **Limiter:** Evaluates and updates allowance atomically.

-   **Decision:** `ALLOW | DENY | QUEUE` with metadata (remaining, reset, retryAfter).

-   **Reporter:** Emits metrics, logs, and optionally **Retry-After** / **X-RateLimit-**\* headers.


## Collaboration

1.  Request arrives → **Classifier** derives `(key, policy)`.

2.  **Limiter** checks tokens/slots for the key (optionally in a **distributed store**).

3.  If allowed: decrement tokens, continue; set response headers.

4.  If not: return **429 Too Many Requests** (or 503) with **Retry-After** and log/metric.

5.  Optionally apply **server-side queuing** or **shed load** based on overload signals.


## Consequences

**Benefits**

-   Protects systems and SLOs under spikes.

-   Enforces fairness and contractually defined quotas.

-   Simple, fast hot-path (esp. token bucket).


**Liabilities**

-   Wrong policy → user pain (false rejections).

-   Distributed accuracy is hard (clock skew, cross-region latency).

-   Per-request storage ops can add latency.

-   Needs careful handling of **idempotent retries** to avoid abuse.


## Implementation (Key Points)

-   **Algorithms:**

    -   **Token Bucket:** steady rate + **burst**; cheap; good default.

    -   **Leaky Bucket (queue):** smooth egress; can increase latency.

    -   **Fixed Window:** simple but bursty at window edges.

    -   **Sliding Window (log/counter):** more accurate; heavier.

    -   **GCRA (Generic Cell Rate Algorithm):** precise, O(1) state.

-   **Granularity:** per key, per route, per method; combine with **hierarchical** limits (user < org < global).

-   **Headers:** `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`.

-   **Fail-open vs. fail-closed:** Under store outage, choose a stance (often *fail-open* with alarms).

-   **Distributed:** Use **atomic** operations (Redis Lua, INCR + EXPIRE), local **token caches**, and **leaky** reconciliation.

-   **Adaptive throttling:** Use error rate/latency signals to tighten limits during incidents.

-   **Fairness:** Use **weighted** buckets or **concurrency** limits per key.

-   **Backpressure:** Prefer server-side queueing for internal pipelines; for external APIs, reject with guidance.


---

## Sample Code (Java 17): Pluggable Rate Limiter (Token Bucket & Sliding Window) + HTTP Filter

> Educational, single-JVM example.
>
> -   In-memory **Token Bucket** (burst-friendly) and **Sliding Window Counter** (more accurate).
>
> -   Simple HTTP server using `com.sun.net.httpserver.HttpServer`.
>
> -   Per-API-key limiting with standard rate-limit headers and **429** response.
>

```java
// File: RateLimitingDemo.java
// Compile: javac RateLimitingDemo.java
// Run:     java RateLimitingDemo 8080
// Try:     for i in {1..120}; do curl -s -H "X-API-Key: demo" localhost:8080/hello >/dev/null -w "%{http_code}\n"; done

import com.sun.net.httpserver.*;
import java.io.*;
import java.net.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

public class RateLimitingDemo {

    // -------- Policies --------
    static final class Policy {
        final int limit;             // events per window or rate per second (see impl)
        final Duration window;       // e.g. 60s for sliding; for token bucket, used to compute refill rate
        final int burst;             // token bucket capacity
        Policy(int limit, Duration window, int burst) {
            this.limit = limit; this.window = window; this.burst = burst;
        }
        static Policy perMinute(int limit, int burst) { return new Policy(limit, Duration.ofMinutes(1), burst); }
        static Policy perSecond(int limit, int burst) { return new Policy(limit, Duration.ofSeconds(1), burst); }
    }

    // -------- Limiter SPI --------
    interface RateLimiter {
        Decision allow(String key);
        record Decision(boolean allowed, long remaining, long resetEpochSeconds, long retryAfterSeconds) {}
    }

    // -------- Token Bucket (rate = limit/window, capacity = burst) --------
    static final class TokenBucketLimiter implements RateLimiter {
        static final class Bucket {
            final double capacity;
            final double refillPerSec;
            double tokens;
            long lastRefillNanos;
            Bucket(double capacity, double refillPerSec) {
                this.capacity = capacity; this.refillPerSec = refillPerSec;
                this.tokens = capacity; this.lastRefillNanos = System.nanoTime();
            }
            synchronized boolean tryConsume() {
                long now = System.nanoTime();
                double elapsed = (now - lastRefillNanos) / 1_000_000_000.0;
                tokens = Math.min(capacity, tokens + elapsed * refillPerSec);
                lastRefillNanos = now;
                if (tokens >= 1.0) { tokens -= 1.0; return true; }
                return false;
            }
            synchronized long remainingRounded() { return (long)Math.floor(tokens); }
            synchronized long secondsUntilNextToken() {
                if (tokens >= 1.0) return 0L;
                double need = 1.0 - tokens;
                return Math.max(0L, (long)Math.ceil(need / refillPerSec));
            }
        }

        private final ConcurrentHashMap<String,Bucket> buckets = new ConcurrentHashMap<>();
        private final Policy policy;
        private final long capacity;
        private final double refillPerSec;

        TokenBucketLimiter(Policy p) {
            this.policy = p;
            this.capacity = Math.max(1, p.burst);
            this.refillPerSec = Math.max(0.000001, (double)p.limit / p.window.getSeconds());
        }

        @Override public Decision allow(String key) {
            Bucket b = buckets.computeIfAbsent(key, k -> new Bucket(capacity, refillPerSec));
            boolean ok = b.tryConsume();
            long remaining = b.remainingRounded();
            long retry = ok ? 0L : b.secondsUntilNextToken();
            long reset = Instant.now().plusSeconds(retry).getEpochSecond();
            return new Decision(ok, remaining, reset, retry);
        }
    }

    // -------- Sliding Window Counter (approximate, window split into N slots) --------
    static final class SlidingWindowLimiter implements RateLimiter {
        static final class Window {
            final int slots;
            final long slotMillis;
            final long[] counters;
            long windowStart; // epoch millis aligned to slot0
            Window(int slots, long slotMillis, long now) {
                this.slots = slots; this.slotMillis = slotMillis; this.counters = new long[slots];
                this.windowStart = (now / slotMillis) * slotMillis;
            }
            synchronized boolean add(long now, int limit) {
                advance(now);
                int idx = (int)(((now - windowStart) / slotMillis) % slots);
                long sum = sum();
                if (sum >= limit) return false;
                counters[idx]++;
                return true;
            }
            synchronized long remaining(long limit, long now) { advance(now); return Math.max(0, limit - sum()); }
            synchronized long resetEpochSeconds(long now) {
                advance(now);
                // reset when the oldest slot rolls out (when current window sum can drop below limit)
                long next = windowStart + slots * slotMillis;
                return (next / 1000L);
            }
            private void advance(long now) {
                long aligned = (now / slotMillis) * slotMillis;
                long diff = aligned - windowStart;
                if (diff <= 0) return;
                long steps = Math.min(counters.length, diff / slotMillis);
                for (int i = 0; i < steps; i++) {
                    int idx = (int)(((windowStart / slotMillis) + i) % counters.length);
                    counters[idx] = 0;
                }
                windowStart = aligned - (aligned - windowStart - steps * slotMillis);
                // normalize windowStart to current slot boundary
                windowStart = aligned - ((aligned - windowStart) % slotMillis);
            }
            private long sum() { long s=0; for (long v: counters) s+=v; return s; }
        }

        private final ConcurrentHashMap<String, Window> wins = new ConcurrentHashMap<>();
        private final Policy policy;
        private final int slots;
        private final long slotMillis;

        SlidingWindowLimiter(Policy p, int slots) {
            this.policy = p;
            this.slots = Math.max(2, slots);
            this.slotMillis = Math.max(10, p.window.toMillis() / this.slots);
        }

        @Override public Decision allow(String key) {
            long now = System.currentTimeMillis();
            Window w = wins.computeIfAbsent(key, k -> new Window(slots, slotMillis, now));
            boolean ok = w.add(now, policy.limit);
            long remaining = w.remaining(policy.limit, now);
            long reset = w.resetEpochSeconds(now);
            long retry = ok ? 0 : Math.max(1, reset - (System.currentTimeMillis()/1000L));
            return new Decision(ok, remaining, reset, retry);
        }
    }

    // -------- Simple HTTP server with middleware --------
    public static void main(String[] args) throws Exception {
        int port = args.length > 0 ? Integer.parseInt(args[0]) : 8080;

        // Choose limiter (swap to SlidingWindowLimiter to see differences)
        Policy policy = Policy.perMinute(60, 30); // 60 req/min, burst up to 30
        RateLimiter limiter = new TokenBucketLimiter(policy);
        // RateLimiter limiter = new SlidingWindowLimiter(Policy.perMinute(60, 0), 10);

        HttpServer server = HttpServer.create(new InetSocketAddress(port), 0);
        server.createContext("/hello", exchange -> handleWithRateLimit(exchange, limiter, policy));
        server.createContext("/health", exchange -> ok(exchange, "ok"));
        server.setExecutor(Executors.newFixedThreadPool(Math.max(4, Runtime.getRuntime().availableProcessors())));
        System.out.println("Listening on http://localhost:" + port + " (limits: " + policy.limit + "/" + policy.window.toSeconds() + "s; burst=" + policy.burst + ")");
        server.start();
    }

    static void handleWithRateLimit(HttpExchange ex, RateLimiter limiter, Policy policy) throws IOException {
        String apiKey = Optional.ofNullable(ex.getRequestHeaders().getFirst("X-API-Key"))
                .orElseGet(() -> ex.getRemoteAddress().getAddress().getHostAddress()); // fallback: IP
        RateLimiter.Decision d = limiter.allow("key:" + apiKey);

        // Standard headers
        ex.getResponseHeaders().set("X-RateLimit-Limit", String.valueOf(policy.limit));
        ex.getResponseHeaders().set("X-RateLimit-Remaining", String.valueOf(Math.max(0, d.remaining())));
        ex.getResponseHeaders().set("X-RateLimit-Reset", String.valueOf(d.resetEpochSeconds()));

        if (!d.allowed()) {
            ex.getResponseHeaders().set("Retry-After", String.valueOf(Math.max(1, d.retryAfterSeconds())));
            byte[] body = ("rate limit exceeded; retry after " + d.retryAfterSeconds() + "s\n").getBytes();
            ex.sendResponseHeaders(429, body.length);
            try (var os = ex.getResponseBody()) { os.write(body); }
            return;
        }

        String msg = "Hello! Your key=" + apiKey + " is allowed. Remaining=" + d.remaining() + "\n";
        ok(ex, msg);
    }

    static void ok(HttpExchange ex, String msg) throws IOException {
        byte[] b = msg.getBytes();
        ex.getResponseHeaders().set("content-type", "text/plain; charset=utf-8");
        ex.sendResponseHeaders(200, b.length);
        try (var os = ex.getResponseBody()) { os.write(b); }
    }
}
```

**What the sample shows**

-   Two algorithms behind one interface.

-   Per-key enforcement, standard headers, and **429** behavior.

-   Swap `TokenBucketLimiter` ↔ `SlidingWindowLimiter` to compare burst behavior and accuracy.


> For a **distributed** production variant, keep the same interface and back with Redis using atomic ops or Lua (token bucket or GCRA). Cache local tokens to cut round-trips and refresh asynchronously.

---

## Known Uses

-   **Public cloud APIs** (AWS, GCP, Azure): per-account and per-API family quotas with `Retry-After`.

-   **CDNs / API gateways** (CloudFront, Cloudflare, Kong, Apigee): edge-enforced per-key limits.

-   **Service meshes / proxies** (Envoy, Istio): local + global rate limit service (RLS) with descriptors.

-   **Queue/stream platforms** (Kafka, Pub/Sub): producer/consumer quotas and fetch throttles.

-   **Datastores** (DynamoDB, Firestore): provisioned capacity, adaptive throttling under contention.


## Related Patterns

-   **Circuit Breaker:** When downstream is unhealthy, trip and shed load before limits.

-   **Retry with Backoff:** Pair with limits; advertise `Retry-After` and bound retries.

-   **Bulkhead / Pool Isolation:** Separate resource pools per tenant/route.

-   **Load Balancer:** Spreads traffic; rate limiting constrains per-client flow.

-   **Token Bucket / Leaky Bucket / GCRA:** Algorithmic realizations of this pattern.

-   **Queue-based Backpressure:** Prefer queuing for internal pipelines; throttle producers.


---

### Practical Tips

-   Start with **Token Bucket** (`rate`, `burst`) for most APIs; expose per-tenant configs.

-   Always emit **limit/remaining/reset** headers; document error contract and retry guidance.

-   For global accuracy, use **Redis** (Lua GCRA) or **Envoy RLS**, and add **local warm caches**.

-   Keep fast paths **lock-light** and pre-allocate objects to avoid GC spikes.

-   Monitor **rejection rate**, **hot keys**, and **p95/p99** latency of the limiter store.

-   Decide **fail-open vs. fail-closed** and alert loudly when the limiter backend is degraded.
