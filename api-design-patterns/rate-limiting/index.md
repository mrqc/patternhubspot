# Rate Limiting — API Design Pattern

## Pattern Name and Classification

**Rate Limiting** — *Protection / Governance* pattern that controls **how often** clients may call an API over time.

---

## Intent

Protect services and shared resources by **throttling** traffic (per API key, user, IP, route, tenant) to maintain **SLOs**, **fairness**, and **cost control**.

---

## Also Known As

-   **Throttling**

-   **Request Quotas**

-   **Token Bucket / Leaky Bucket / Fixed Window / Sliding Window** (algorithms)


---

## Motivation (Forces)

-   Prevent **overload** (traffic spikes, buggy clients, abuse).

-   Ensure **fair usage** across tenants and keep **latency predictable**.

-   Control **cost** (downstream calls, third-party quotas).

-   Provide **backpressure** and a clear, contractually visible limit.


Trade-offs: accuracy vs. cost (e.g., fixed window is cheap but bursty, token bucket smooths), local vs. **distributed** counters, correctness under clock skew, UX of rejections.

---

## Applicability

Use when:

-   Your API is public/partner/large internal and must guard shared capacity.

-   You enforce **per-subject** limits: API key, IP, user/tenant, route.

-   You need **global** or **multi-node** enforcement (Redis, CDN, gateway).


Avoid / simplify when:

-   Only a handful of trusted clients, or bandwidth is already gated by an upstream.


---

## Structure

```markdown
Client → [ Rate Limiter ]
            |  ├─ classify(request) → key (tenant:route)
            |  ├─ check & consume tokens (bucket store)
            |  └─ set headers (limits/remaining/reset)
         →  [ Auth | Handler ]

 Store options:
   - Local in-memory (node-scoped)
   - Centralized (Redis/Memcache) with scripts for atomicity
   - Edge/CDN rate limiting (Akamai/Cloudflare/API Gateway)
```

---

## Participants

-   **Classifier** — derives a **limiting key** (e.g., `tenantId:GET:/orders`).

-   **Limiter** — algorithm (token bucket, leaky bucket, sliding window).

-   **Store** — counters/buckets with TTL; needs **atomic** updates.

-   **Policy** — limit numbers per plan/route (e.g., 100 RPS, 10k/min).

-   **Responder** — adds headers (`X-RateLimit-*`, `Retry-After`) and 429 on limit.


---

## Collaboration

1.  Request arrives → **classify** to a key and policy.

2.  **Consume token** atomically; if available → proceed; else → **429**.

3.  Add **rate-limit headers** to response; optionally emit metrics.

4.  Optionally implement **soft** limits (log) and **hard** limits (enforce).


---

## Consequences

**Benefits**

-   Shields backends, improves **SLOs** and fairness.

-   Makes capacity **predictable**; reduces blast radius of misbehaving clients.

-   Clear **contract** (limits + headers).


**Liabilities**

-   Requires **distributed** coordination for accuracy at scale.

-   Poorly chosen keys/policies can **punish** good users.

-   Client UX: must handle 429 with **backoff**; clock skew & multi-DC consistency.


---

## Implementation (Key Points)

-   Prefer **Token Bucket** for smooth bursts (capacity = `burst`, refill rate = `tokens/sec`).

-   Use **Redis** with a **Lua** script for atomic consume/refill across nodes.

-   Expose headers (IETF draft/commonly used):

    -   `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset` (or `X-RateLimit-*`)

    -   On block: HTTP **429** + `Retry-After` seconds.

-   Separate **read vs. write** limits; per-route policies.

-   Make limits **plan-driven** (free/pro/enterprise).

-   Log **rejections** and emit metrics for capacity planning.

-   Place limiters **at the edge** (gateway/CDN) when possible; keep **idempotency** on retried POSTs.


---

## Sample Code (Java, Spring Boot)

Two parts:

1.  **In-memory Token Bucket** filter (demo, per-node).

2.  Optional **Redis Lua** script (production sketch).


### 1) In-memory Token Bucket Filter (per-node demo)

**Gradle (snippets)**

```gradle
implementation "org.springframework.boot:spring-boot-starter-web"
implementation "com.fasterxml.jackson.core:jackson-databind"
```

**TokenBucket & Registry**

```java
package demo.ratelimit;

import java.time.Instant;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

class TokenBucket {
  final int capacity;          // max tokens (burst)
  final double refillPerSec;   // tokens per second
  double tokens;
  long lastRefillNanos;

  TokenBucket(int capacity, double refillPerSec) {
    this.capacity = capacity;
    this.refillPerSec = refillPerSec;
    this.tokens = capacity;
    this.lastRefillNanos = System.nanoTime();
  }

  synchronized boolean tryConsume(int n) {
    refill();
    if (tokens >= n) { tokens -= n; return true; }
    return false;
  }

  synchronized long secondsUntilAvailable(int n) {
    refill();
    if (tokens >= n) return 0;
    double deficit = n - tokens;
    return (long)Math.ceil(deficit / refillPerSec);
  }

  private void refill() {
    long now = System.nanoTime();
    double deltaSec = (now - lastRefillNanos) / 1_000_000_000.0;
    if (deltaSec > 0) {
      tokens = Math.min(capacity, tokens + deltaSec * refillPerSec);
      lastRefillNanos = now;
    }
  }

  synchronized int remaining() { refill(); return (int)Math.floor(tokens); }
}

class BucketRegistry {
  private final Map<String, TokenBucket> buckets = new ConcurrentHashMap<>();

  TokenBucket get(String key, int capacity, double refillPerSec) {
    return buckets.computeIfAbsent(key, k -> new TokenBucket(capacity, refillPerSec));
  }
}
```

**Filter (per API key / IP / route)**

```java
package demo.ratelimit;

import jakarta.servlet.*;
import jakarta.servlet.http.*;
import org.springframework.stereotype.Component;
import java.io.IOException;

@Component
public class RateLimitFilter implements Filter {

  private final BucketRegistry registry = new BucketRegistry();

  @Override
  public void doFilter(ServletRequest request, ServletResponse response, FilterChain chain)
      throws IOException, ServletException {

    HttpServletRequest req = (HttpServletRequest) request;
    HttpServletResponse res = (HttpServletResponse) response;

    // ❶ Classify: per API key (preferred) falling back to IP; include route+method
    String apiKey = req.getHeader("X-Api-Key");
    String subject = (apiKey != null && !apiKey.isBlank()) ? apiKey : req.getRemoteAddr();
    String key = subject + ":" + req.getMethod() + ":" + req.getRequestURI();

    // ❷ Policy: e.g., 60 reqs / minute with burst 30 → refill = 1 token/sec, capacity 30
    int capacity = 30;          // burst
    double refillPerSec = 1.0;  // 60/min overall if spread evenly
    TokenBucket bucket = registry.get(key, capacity, refillPerSec);

    if (bucket.tryConsume(1)) {
      // ❸ Permit: set informational headers
      res.setHeader("RateLimit-Limit", String.valueOf(capacity));
      res.setHeader("RateLimit-Remaining", String.valueOf(bucket.remaining()));
      // Reset in seconds until bucket full (approx), optional
      res.setHeader("RateLimit-Reset", String.valueOf(bucket.secondsUntilAvailable(1)));
      chain.doFilter(request, response);
    } else {
      // ❹ Block: 429 Too Many Requests
      long retry = bucket.secondsUntilAvailable(1);
      res.setStatus(429);
      res.setHeader("Retry-After", String.valueOf(retry));
      res.setHeader("RateLimit-Limit", String.valueOf(capacity));
      res.setHeader("RateLimit-Remaining", String.valueOf(bucket.remaining()));
      res.setContentType("application/json");
      res.getWriter().write("{\"error\":\"rate_limit_exceeded\",\"retry_after_sec\":" + retry + "}");
    }
  }
}
```

**Example Controller**

```java
package demo.ratelimit;

import org.springframework.web.bind.annotation.*;

@RestController
class DemoController {
  @GetMapping("/hello")
  public String hello() { return "world"; }
}
```

> Notes (demo):
>
> -   This limiter is **node-local**; in a cluster each instance has its own bucket.
>
> -   Good for development or single-instance services; for production use a **shared store** (Redis) or an **API Gateway**.
>

---

### 2) Production Sketch — Redis Token Bucket (atomic Lua)

**Lua script (consume-and-refill) idea**

```lua
-- KEYS[1] = bucket key
-- ARGV[1] = capacity
-- ARGV[2] = refill_per_sec
-- ARGV[3] = now_millis
-- ARGV[4] = tokens_to_consume
-- returns: {allowed, remaining, retry_after_sec}
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local need = tonumber(ARGV[4])

local b = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(b[1]) or capacity
local ts = tonumber(b[2]) or now

local delta = math.max(0, now - ts) / 1000.0
tokens = math.min(capacity, tokens + delta * refill)

local allowed = 0
local retry = 0
if tokens >= need then
  tokens = tokens - need
  allowed = 1
else
  retry = math.ceil((need - tokens) / refill)
end

redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
redis.call('PEXPIRE', key, 3600000) -- 1h TTL

return {allowed, math.floor(tokens), retry}
```

**Java usage (Jedis/lettuce)**

```java
// Load and eval the Lua once; call per request with key=tenant:route
// Use the return triplet to set headers / 429.
```

This provides **cluster-wide** accuracy and atomicity.

---

## Known Uses

-   Public APIs (Stripe, GitHub, Twitter, Shopify) publish headers and **429** semantics.

-   Gateways (Kong, NGINX, Envoy, Spring Cloud Gateway, AWS API Gateway, Cloudflare/Akamai) implement rate limiting at the edge.

-   Internal multi-tenant platforms enforce **per-tenant** and **per-route** limits.


---

## Related Patterns

-   **Quota / Usage Plans** — longer windows (daily/monthly) with enforcement & billing.

-   **Circuit Breaker** — protects callers from failing downstreams; rate limiting protects **callees**.

-   **Bulkhead** — isolate pools to prevent noisy neighbor effects.

-   **Backoff & Retry** — clients should handle **429** with **exponential backoff + jitter**.

-   **Token Bucket / Leaky Bucket / Sliding Window** — algorithmic choices; often combined with **burst** allowances.
