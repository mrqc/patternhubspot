# Write-Behind Cache — Scalability Pattern

## Pattern Name and Classification

**Name:** Write-Behind Cache  
**Classification:** Scalability / Performance / Data Access (Asynchronous write buffering & coalescing)

---

## Intent

Absorb **write bursts** and reduce **write amplification** on the source of truth by **buffering updates in a cache** and **persisting them asynchronously** (often in **batches**). Reads are served from the cache; writes update the cache immediately and are **written “behind”** to the backing store later.

---

## Also Known As

-   Write-Back Cache
    
-   Deferred Writes / Asynchronous Persistence
    
-   Buffered Writes
    

---

## Motivation (Forces)

-   **Burstiness:** upstream can generate spikes of writes that a database cannot absorb at once.
    
-   **Cost & efficiency:** coalescing multiple updates to the same key → **fewer DB writes**; batch I/O is cheaper.
    
-   **Latency:** caller returns faster after updating the cache; persistence is off the critical path.
    
-   **Hardware patterns:** drives and remote APIs often favor **sequential/batched** writes.
    

**Trade-offs:** risk of **data loss** on crash if not durably journaled; **stale reads** outside the cache; **ordering** and **idempotency** must be considered.

---

## Applicability

Use Write-Behind when:

-   You can tolerate **eventual consistency** from cache → store with a bounded delay.
    
-   Many writes **overwrite** the same keys (coalescing pays off).
    
-   The backing store is **write-expensive** but handles **bulk/batched** writes well.
    
-   You control the cache layer and can add durability/observability.
    

Avoid or adapt when:

-   **Strong durability** is required at the point of write acceptance (use write-through/synchronous tx).
    
-   Readers outside the cache must see **read-after-write** immediately.
    
-   The domain has **non-idempotent side effects** triggered per write (e.g., send email on each change).
    

---

## Structure

-   **Cache**: holds hot objects and a **dirty map** for modified entries.
    
-   **Write Queue / Buffer**: collects dirty keys; deduplicates & coalesces.
    
-   **Flusher/Drainer**: asynchronous worker persisting batched updates with retry/backoff.
    
-   **Durability Layer (optional but recommended)**: WAL/journal or message broker to survive cache crashes.
    
-   **Backing Store**: source of truth (DB/service).
    
-   **Metrics & Control**: backlog depth, flush latency, failure rate, backpressure.
    

---

## Participants

-   **Client / Application**: reads/writes via the cache API.
    
-   **Write-Behind Manager**: tracks dirties, schedules flush, handles retries.
    
-   **Serializer**: compact wire format for journal/batch write.
    
-   **Backing Store Adapter**: provides batch upsert/delete with idempotency.
    
-   **Observability**: meters, logs, and alerts on lag and errors.
    

---

## Collaboration

1.  **Write**: client updates cache → item marked **dirty**; enqueue key (coalesced).
    
2.  **Flush** (time/size/pressure trigger): manager builds a **batch** from dirty entries and writes to store.
    
3.  On **success**: clear dirty flags; on **failure**: retry with backoff, optionally put to **DLQ/journal**.
    
4.  **Read**: served from cache; if miss and allowed, read-through to store and populate.
    

---

## Consequences

**Benefits**

-   **Smooths write spikes**; protects DB from overload.
    
-   **Lower write amplification** via **coalescing/batching**.
    
-   **Lower write latency** seen by callers.
    

**Liabilities**

-   **Durability gap** unless journaled (risk of data loss on crash).
    
-   **Stale views** outside the cache; **read-your-write** only if you read from cache.
    
-   **Complexity**: ordering, retries, backpressure, and recovery paths.
    
-   **Eviction hazards**: evicting a **dirty** entry before flush must be handled.
    

---

## Implementation

### Key Decisions

-   **Durability:**
    
    -   *At-least-once* via **WAL/journal** (fsync) before acknowledging writes.
        
    -   Broker-backed (e.g., Kafka/SQS) instead of local WAL.
        
-   **Flush policy:** max batch size, max age, and backpressure thresholds.
    
-   **Coalescing:** last-writer-wins per key, or **merge** function for partial updates.
    
-   **Ordering & idempotency:** ensure **upserts** are idempotent; carry **version/ETag** or **idempotency key**.
    
-   **Failure policy:** bounded retries + DLQ; expose lag and fail fast when backlog grows.
    
-   **Eviction:** prevent eviction of dirty entries, or **write-through-on-evict**.
    
-   **Consistency contract:** document **read-your-write** guarantee from the cache and staleness for external readers.
    

### Anti-Patterns

-   Acknowledging writes **without** WAL / durable queue when durability is required.
    
-   **Infinite retries** on permanent errors (poison batch) – use DLQ/quarantine.
    
-   Allowing **unbounded backlog** – add quotas and fail fast with clear errors.
    
-   Writing **every mutation immediately** (no coalescing) – defeats the purpose.
    

---

## Sample Code (Java, Spring JDBC)

*A minimal write-behind cache with: coalescing, batching, retry with exponential backoff, optional file-backed WAL, and safe shutdown flush.*

> Dependencies (example):
> 
> -   `org.springframework.boot:spring-boot-starter-jdbc`
>     
> -   `org.postgresql:postgresql` (or your driver)
>     

```java
package com.example.writebehind;

import org.springframework.jdbc.core.JdbcTemplate;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** Domain object */
public record Product(long id, String name, long priceCents) {}

/** Write-behind cache for Product keyed by id (last-write-wins with coalescing). */
public class WriteBehindProductCache implements AutoCloseable {

  private final ConcurrentHashMap<Long, Product> cache = new ConcurrentHashMap<>();
  private final ConcurrentHashMap<Long, Boolean> dirty = new ConcurrentHashMap<>();
  private final BlockingQueue<Long> dirtyQueue = new LinkedBlockingQueue<>(100_000); // backpressure

  private final JdbcTemplate jdbc;
  private final ScheduledExecutorService scheduler = Executors.newScheduledThreadPool(1);
  private final ExecutorService flusherPool = Executors.newFixedThreadPool(2);
  private final AtomicBoolean running = new AtomicBoolean(true);

  // tuning knobs
  private final int maxBatch = 500;
  private final Duration maxAge = Duration.ofMillis(500); // flush at least twice per second
  private final int maxRetries = 6;

  // optional WAL for durability (very simple line-based journal)
  private final Path walPath;
  private final boolean useWal;

  public WriteBehindProductCache(JdbcTemplate jdbc, Path walPath) {
    this.jdbc = jdbc;
    this.walPath = walPath;
    this.useWal = walPath != null;
    if (useWal) loadWal(); // recovery
    scheduler.scheduleWithFixedDelay(this::flushLoopSafely, maxAge.toMillis(), maxAge.toMillis(), TimeUnit.MILLISECONDS);
  }

  /** Public API: read from cache (read-through optional). */
  public Optional<Product> get(long id, boolean readThrough) {
    Product p = cache.get(id);
    if (p != null) return Optional.of(p);
    if (!readThrough) return Optional.empty();
    // simple read-through
    List<Product> rows = jdbc.query("select id,name,price_cents from product where id=?",
        (rs, i) -> new Product(rs.getLong(1), rs.getString(2), rs.getLong(3)), id);
    if (!rows.isEmpty()) {
      cache.put(id, rows.get(0));
      return Optional.of(rows.get(0));
    }
    return Optional.empty();
  }

  /** Public API: write updates the cache and enqueues the key; caller returns immediately. */
  public void put(Product p) {
    ensureRunning();
    cache.put(p.id(), p);
    markDirty(p.id(), p); // persists to WAL (optional) and enqueues
  }

  /** Public API: delete example (also write-behind) */
  public void delete(long id) {
    ensureRunning();
    cache.remove(id);
    // Represent deletion as a tombstone (price -1)
    Product tombstone = new Product(id, "", -1);
    markDirty(id, tombstone);
  }

  // --------------- internals ---------------

  private void markDirty(long id, Product p) {
    if (useWal) appendWal(p);
    if (dirty.put(id, Boolean.TRUE) == null) {
      // newly dirty → enqueue; if full, apply backpressure by throwing
      if (!dirtyQueue.offer(id)) {
        dirty.remove(id);
        throw new RejectedExecutionException("write backlog full; apply backpressure");
      }
    }
  }

  private void flushLoopSafely() {
    try { flushOnce(); } catch (Throwable t) { /* log */ }
  }

  private void flushOnce() {
    if (dirty.isEmpty()) return;

    List<Long> ids = new ArrayList<>(maxBatch);
    dirtyQueue.drainTo(ids, maxBatch);
    if (ids.isEmpty()) return;

    // Build batch snapshot, coalescing duplicates to latest
    Map<Long, Product> batch = new LinkedHashMap<>();
    for (Long id : ids) {
      Product p = cache.get(id);
      if (p != null) batch.put(id, p);
      else batch.put(id, new Product(id, "", -1)); // treat as tombstone
    }

    flusherPool.submit(() -> persistBatch(batch, ids));
  }

  private void persistBatch(Map<Long, Product> batch, List<Long> ids) {
    int attempt = 0;
    while (true) {
      try {
        jdbc.batchUpdate("""
          insert into product (id, name, price_cents)
          values (?, ?, ?)
          on conflict (id) do update set
            name = excluded.name,
            price_cents = excluded.price_cents
        """, batch.values(), batch.size(),
            (ps, p) -> {
              if (p.priceCents() < 0) {
                // delete tombstone: convert to delete
                // we cannot mix in batch; run separate delete batch after upserts
                ps.setLong(1, p.id()); ps.setString(2, p.name()); ps.setLong(3, 0L);
              } else {
                ps.setLong(1, p.id()); ps.setString(2, p.name()); ps.setLong(3, p.priceCents());
              }
            });

        // handle deletes (tombstones)
        List<Long> deletes = batch.values().stream().filter(p -> p.priceCents() < 0).map(Product::id).toList();
        if (!deletes.isEmpty()) {
          jdbc.batchUpdate("delete from product where id = ?", deletes, deletes.size(),
              (ps, id) -> ps.setLong(1, id));
        }

        // success: clear dirty flags and compact WAL
        ids.forEach(dirty::remove);
        if (useWal) compactWal(ids);
        return;
      } catch (Exception e) {
        if (++attempt > maxRetries) {
          // move failed keys back to queue for later retry and alert
          ids.forEach(id -> { dirty.put(id, Boolean.TRUE); dirtyQueue.offer(id); });
          return;
        }
        sleep(jitteredBackoff(attempt));
      }
    }
  }

  // --------- WAL (very simple, for illustration) ---------

  private synchronized void appendWal(Product p) {
    try {
      Files.writeString(walPath,
          "%d|%s|%d%n".formatted(p.id(), escape(p.name()), p.priceCents()),
          StandardCharsets.UTF_8,
          StandardOpenOption.CREATE, StandardOpenOption.WRITE, StandardOpenOption.APPEND);
    } catch (IOException ioe) {
      throw new UncheckedIOException("WAL append failed", ioe);
    }
  }

  private synchronized void loadWal() {
    if (!Files.exists(walPath)) return;
    try (BufferedReader br = Files.newBufferedReader(walPath)) {
      String line;
      while ((line = br.readLine()) != null) {
        String[] parts = line.split("\\|", 3);
        long id = Long.parseLong(parts[0]);
        String name = unescape(parts[1]);
        long price = Long.parseLong(parts[2]);
        cache.put(id, new Product(id, name, price));
        dirty.put(id, Boolean.TRUE);
        dirtyQueue.offer(id);
      }
    } catch (IOException e) { /* log */ }
  }

  private synchronized void compactWal(List<Long> flushedIds) {
    // naive compaction: rebuild file from current dirty set only
    try {
      Path tmp = walPath.resolveSibling(walPath.getFileName() + ".tmp");
      try (BufferedWriter bw = Files.newBufferedWriter(tmp, StandardCharsets.UTF_8)) {
        for (Map.Entry<Long, Boolean> e : dirty.entrySet()) {
          Product p = cache.get(e.getKey());
          if (p != null)
            bw.write("%d|%s|%d%n".formatted(p.id(), escape(p.name()), p.priceCents()));
        }
      }
      Files.move(tmp, walPath, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
    } catch (Exception ignore) { /* best-effort */ }
  }

  private static String escape(String s){ return s.replace("|","\\|").replace("\n"," "); }
  private static String unescape(String s){ return s.replace("\\|","|"); }

  // --------- utils ---------

  private static long jitteredBackoff(int attempt) {
    long base = (long) (100 * Math.pow(2, Math.min(6, attempt)));
    return ThreadLocalRandom.current().nextLong(base / 2, base);
  }
  private static void sleep(long ms){ try { Thread.sleep(ms); } catch (InterruptedException ie){ Thread.currentThread().interrupt(); } }
  private void ensureRunning(){ if (!running.get()) throw new IllegalStateException("closed"); }

  @Override public void close() {
    running.set(false);
    scheduler.shutdown();
    // drain and flush synchronously
    while (!dirty.isEmpty() || !dirtyQueue.isEmpty()) flushOnce();
    flusherPool.shutdown();
    try { flusherPool.awaitTermination(5, TimeUnit.SECONDS); } catch (InterruptedException ignored) { Thread.currentThread().interrupt(); }
  }
}
```

**Schema example**

```sql
create table if not exists product (
  id bigint primary key,
  name text not null,
  price_cents bigint not null
);
```

**How to use**

```java
JdbcTemplate jdbc = /* injected */;
Path wal = Paths.get("/var/lib/app/product.wal");
try (WriteBehindProductCache cache = new WriteBehindProductCache(jdbc, wal)) {
  // Writes return fast:
  cache.put(new Product(1L, "Pen", 199));
  cache.put(new Product(1L, "Pen - updated", 249)); // coalesced, one DB write later

  // Reads get cache view (strong read-your-write within this process)
  cache.get(1L, false).ifPresent(System.out::println);

  // On shutdown, cache flushes remaining dirties
}
```

**Notes**

-   This is a minimal reference. Production systems often use:
    
    -   **Distributed caches** (Redis/Hazelcast) with **write-behind map stores**.
        
    -   **Broker-backed durability** (Kafka) to persist write-behind streams.
        
    -   **Per-key merge functions** and **version vectors** when merging partial updates.
        
    -   **Cross-node coordination** for multi-writer caches (e.g., partitioned keys).
        

---

## Known Uses

-   **User/profile updates** coalesced before persisting to relational DB.
    
-   **Metrics/telemetry aggregation** flushed in intervals to cold storage.
    
-   **Shopping carts / session state** batched to DB for durability.
    
-   **Feature usage counters** and **rate statistics** rolled up periodically.
    

---

## Related Patterns

-   **Write-Through Cache:** durability at write time; higher latency; simpler semantics.
    
-   **Read-Through / Cache-Aside:** complements write-behind on read paths.
    
-   **Queue-Based Load Leveling:** an alternative for decoupling writes (enqueue updates).
    
-   **Materialized Views:** precompute & persist read shapes; can be fed by write-behind streams.
    
-   **Idempotent Receiver / Outbox:** ensure safe replay and cross-system delivery.
    
-   **Circuit Breaker / Retry with Backoff / Timeouts:** guard flusher interactions with the store.
    

---

## Implementation Checklist

-   Decide **durability** (WAL, broker) before acknowledging writes.
    
-   Define **batching/flush** triggers (size, age, backpressure).
    
-   Ensure **idempotent upserts** and a **merge function** if partial updates occur.
    
-   Prevent or handle **dirty eviction** (pin dirty, or write-through on evict).
    
-   Implement **retries** with budgets, **DLQ/quarantine** for poison records.
    
-   Expose **lag metrics** (dirty count, oldest age) and **error rate**; alert on thresholds.
    
-   Document **consistency**: cache gives read-your-write; external readers may be stale by ≤ *flush interval*.
    
-   Test **crash recovery**: restart from WAL/broker; verify no loss/duplication.

