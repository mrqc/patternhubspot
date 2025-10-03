# Distributed Lock — Cloud / Distributed Systems Pattern

## Pattern Name and Classification

**Distributed Lock** — *Cloud / Distributed Systems* **coordination** pattern to ensure **mutual exclusion** for actions performed by multiple nodes against a shared resource.

---

## Intent

Provide a **lease-based mutex** across processes/machines so that **at most one** holder performs a critical action at a time; include **timeouts**, **renewals**, and **fencing tokens** to remain safe across crashes and partitions.

---

## Also Known As

-   **Distributed Mutex / Lease**

-   **Leader-for-Work**

-   **Advisory Lock**

-   **Fencing Lock** (when combined with monotonic tokens)


---

## Motivation (Forces)

-   Many workers may attempt an exclusive operation (e.g., **run a daily job**, **migrate a partition**, **write to a single-writer store**, **process the same message**).

-   Failures happen: crashes, **GC pauses**, **network partitions**, and **clock skew**.

-   We need: **mutual exclusion**, **liveness** (no permanent deadlocks), and **safety** even if a “zombie” resumes after its lease expired.


**Tensions:**

-   **Safety** vs **availability** (what to do in partitions).

-   **Lease duration** vs **renewal overhead**.

-   Single point of failure vs **quorum-backed** coordinators.


---

## Applicability

Use a Distributed Lock when:

-   Multiple processes **compete** to operate on a **shared resource** and only one should proceed at a time.

-   You can tolerate **short exclusive windows** and design **idempotent**/compensable work.

-   You can add **fencing** at the resource or consumer side.


Avoid when:

-   You need **strong transactions**; use a transactional DB with row-level locks.

-   You cannot modify the resource to **check fencing tokens** and safety must be absolute—then use a **CP** store (e.g., ZooKeeper/etcd) and design carefully.


---

## Structure

```scss
Workers ──► Lock Service (Redis/ZooKeeper/etcd) ──► grants lease(id, ttl, fencingToken)
                     │
                     └─► Resource validates fencingToken (monotonic) to reject stale holders
```

---

## Participants

-   **Lock Service** — provides atomic *acquire-with-ttl*, *renew*, *release* (Redis, ZooKeeper, etcd/Consul).

-   **Worker / Client** — attempts to acquire, runs work only while lease is valid, renews, releases.

-   **Resource** — guarded system that **checks fencing tokens** (monotonic) on write/commit.

-   **Fencing Token Generator** — monotonically increasing counter to **defeat split-brain/zombies**.


---

## Collaboration

1.  Worker calls **acquire(name, ttl)** → if empty, service sets holder and returns **(leaseId, fencingToken, expiry)**.

2.  Worker performs work, periodically **renews** before expiry.

3.  Resource checks **fencingToken** on each mutation and rejects **older** tokens.

4.  On crash or missed renewals, the **lease expires**; another worker can acquire a **newer** fencing token.

5.  Release is **best-effort** (idempotent); safety does not rely on it.


---

## Consequences

**Benefits**

-   Prevents **concurrent execution** of critical sections across nodes.

-   **Leases** guarantee liveness (lock eventually expires).

-   **Fencing** preserves safety even with **paused/zombie** processes.


**Liabilities**

-   Requires a **reliable coordinator**; Redis needs careful config, Redlock debate; ZooKeeper/etcd use **quorum**.

-   Wrong **TTL/renewal** tuning may cause premature expiry or long stalls.

-   Must add **fencing checks** to the resource to be robust against split-brain.


---

## Implementation (Key Points)

-   Prefer **quorum-backed** stores (ZooKeeper/etcd) for strong guarantees; if using Redis, use **single instance or Sentinel/Cluster** and *simple lease with fencing*; be cautious with multi-master Redlock debates.

-   Use **SET key value NX PX ttl** (Redis) or **create ephemeral znode** (ZooKeeper) to acquire.

-   Always attach a **monotonic fencing token** to successful acquisitions and **require the resource** to verify it (e.g., “reject if token ≤ lastSeen”).

-   Implement a **renewal/heartbeat** at *ttl/2* (or less) with jitter; stop work if renewal fails.

-   Make releases **compare-and-delete** (only the holder may release).

-   Ensure **idempotent** critical work; persist **lastAppliedToken** where the work applies.

-   Export **metrics**: lock wait time, renew failures, token age, holder id.


---

## Sample Code (Java 17) — In-Memory Lock Service with Leases + Fencing Tokens

> This is a **self-contained** example illustrating the APIs and safety mechanics.  
> Swap `InMemoryLockStore` with Redis/ZooKeeper/etcd in real systems. The **resource** enforces fencing.

```java
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;

// ===== Lock Service SPI =====
record Lease(String lockName, String holderId, long fencingToken, Instant expiresAt) {
  boolean validNow() { return Instant.now().isBefore(expiresAt); }
}

interface DistributedLockService {
  Optional<Lease> tryAcquire(String lockName, String holderId, Duration ttl);
  Optional<Lease> renew(String lockName, String holderId, Duration ttl);
  boolean release(String lockName, String holderId);
}

// ===== In-memory store (for demo). Replace with Redis/ZooKeeper/etcd. =====
final class InMemoryLockStore implements DistributedLockService {
  private static final class Entry {
    String holderId;
    long fencing;
    Instant expiresAt;
  }
  private final Map<String, Entry> locks = new ConcurrentHashMap<>();
  private final AtomicLong globalFencing = new AtomicLong(0);

  @Override
  public synchronized Optional<Lease> tryAcquire(String lock, String holder, Duration ttl) {
    Entry e = locks.get(lock);
    Instant now = Instant.now();
    if (e == null || now.isAfter(e.expiresAt)) {
      Entry n = new Entry();
      n.holderId = holder;
      n.fencing = globalFencing.incrementAndGet(); // monotonic token
      n.expiresAt = now.plus(ttl);
      locks.put(lock, n);
      return Optional.of(new Lease(lock, holder, n.fencing, n.expiresAt));
    }
    return Optional.empty();
  }

  @Override
  public synchronized Optional<Lease> renew(String lock, String holder, Duration ttl) {
    Entry e = locks.get(lock);
    Instant now = Instant.now();
    if (e != null && Objects.equals(e.holderId, holder) && now.isBefore(e.expiresAt)) {
      e.expiresAt = now.plus(ttl);
      return Optional.of(new Lease(lock, holder, e.fencing, e.expiresAt));
    }
    return Optional.empty();
  }

  @Override
  public synchronized boolean release(String lock, String holder) {
    Entry e = locks.get(lock);
    if (e != null && Objects.equals(e.holderId, holder)) {
      locks.remove(lock);
      return true;
    }
    return false;
  }
}

// ===== Resource guarded by fencing tokens =====
final class GuardedCounter {
  private long value = 0;
  private long lastToken = 0; // monotonic guard

  // Only accepts operations with strictly increasing fencing tokens
  public synchronized void increment(long fencingToken) {
    if (fencingToken <= lastToken) {
      throw new IllegalStateException("Stale token " + fencingToken + " <= lastToken " + lastToken);
    }
    lastToken = fencingToken;
    value++;
    System.out.println("Counter=" + value + " (token=" + fencingToken + ")");
  }

  public synchronized long get() { return value; }
  public synchronized long lastToken() { return lastToken; }
}

// ===== Lock client helper with auto-renew ("watchdog") =====
final class LockGuard implements AutoCloseable {
  private final DistributedLockService svc;
  private final String lockName;
  private final String holderId;
  private final Duration ttl;
  private final ScheduledExecutorService ses = Executors.newSingleThreadScheduledExecutor(r -> {
    Thread t = new Thread(r, "lock-renewer"); t.setDaemon(true); return t;
  });
  private volatile Lease lease;

  private LockGuard(DistributedLockService svc, String lockName, String holderId, Duration ttl, Lease lease) {
    this.svc = svc; this.lockName = lockName; this.holderId = holderId; this.ttl = ttl; this.lease = lease;
    // schedule renew at ttl/2 with jitter
    long periodMs = Math.max(100, (long)(ttl.toMillis() * 0.5));
    ses.scheduleAtFixedRate(this::safeRenew, periodMs, periodMs, TimeUnit.MILLISECONDS);
  }

  static Optional<LockGuard> acquire(DistributedLockService svc, String lockName, String holderId, Duration ttl) {
    return svc.tryAcquire(lockName, holderId, ttl).map(lease -> new LockGuard(svc, lockName, holderId, ttl, lease));
  }

  long fencingToken() { return lease.fencingToken(); }

  private void safeRenew() {
    try {
      var r = svc.renew(lockName, holderId, ttl);
      if (r.isEmpty()) {
        System.err.println("[renew] lost lease for " + lockName + " by " + holderId);
        ses.shutdownNow();
      } else {
        lease = r.get();
      }
    } catch (Throwable t) {
      System.err.println("[renew] error: " + t.getMessage());
    }
  }

  @Override public void close() {
    ses.shutdownNow();
    svc.release(lockName, holderId);
  }
}

// ===== Demo: two workers, one becomes a zombie after TTL and gets fenced =====
public class DistributedLockDemo {
  public static void main(String[] args) throws Exception {
    DistributedLockService locks = new InMemoryLockStore();
    GuardedCounter resource = new GuardedCounter();
    Duration ttl = Duration.ofMillis(600);

    // Worker A acquires lock and starts incrementing
    var a = LockGuard.acquire(locks, "daily-job", "worker-A", ttl).orElseThrow();
    System.out.println("A got token " + a.fencingToken());
    resource.increment(a.fencingToken()); // ok

    // Simulate A being paused (GC/stop-the-world) so its renew stops and lease expires
    Thread.sleep(900); // > ttl, lease will expire

    // Worker B acquires after expiry with a newer fencing token
    var b = LockGuard.acquire(locks, "daily-job", "worker-B", ttl).orElseThrow();
    System.out.println("B got token " + b.fencingToken());
    resource.increment(b.fencingToken()); // ok (token increased)

    // A "zombie" wakes up and tries to write with its **old** token — resource rejects it
    try {
      resource.increment(a.fencingToken()); // should throw
    } catch (IllegalStateException ex) {
      System.out.println("Zombie A blocked: " + ex.getMessage());
    }

    // Clean up
    a.close(); b.close();
    System.out.println("Final counter=" + resource.get() + ", lastToken=" + resource.lastToken());
  }
}
```

### How to adapt this to real systems

-   **Redis (simple lease):**

    -   Acquire: `SET lockKey uniqueHolder NX PX ttl`.

    -   Renew: `PEXPIRE lockKey ttl` only if `GET lockKey==uniqueHolder` (Lua script).

    -   Release: `DEL` only if value matches (Lua compare-and-delete).

    -   **Fencing token:** maintain a separate Redis `INCR fencing:lockName` returned on successful acquire; send the token with each write, and **enforce at the resource**.

-   **ZooKeeper / etcd (quorum):**

    -   Create **ephemeral** node (ZK) or use **lease** (etcd).

    -   Use **sequential** nodes to implement **fair** locks or leader election.

    -   Fencing token can be **zxid/czxid** (ZK) or **revision** (etcd), which are naturally monotonic.

-   **Renewal/Watchdog:** schedule at ~`ttl/2` with jitter; if a renew fails → **stop work immediately**.

-   **Safety checklist:**

    -   Never rely on **release** for safety; rely on **TTL + fencing**.

    -   The **resource** must reject non-monotonic tokens (store last-seen token transactionally).

    -   Keep critical operations **idempotent** and **small**.

    -   Monitor **wait times**, **lost leases**, **stale token rejects**.


---

## Known Uses

-   **Leader election** (one active scheduler/consumer).

-   **Job deduplication** in workers (process a message once).

-   **Single-writer** enforcement for files/buckets/partitions.

-   **Maintenance windows/migrations** to avoid concurrent runs.


---

## Related Patterns

-   **Leader Election** — specialized one-winner coordination; often built with the same primitives.

-   **Idempotency Key** — complementary to make retries safe.

-   **Circuit Breaker / Bulkhead** — resilience at call level, not mutual exclusion.

-   **Saga / Process Manager** — workflow-level coordination; locks guard critical sections inside such flows.

-   **Quorum / CP Stores** — foundational mechanism to implement robust locks.
