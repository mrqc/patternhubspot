
# Data Management & Database Pattern — Snapshot

## Pattern Name and Classification

-   **Name:** Snapshot

-   **Classification:** Data durability & performance pattern (point-in-time copy/checkpoint of data or state)


## Intent

Create a **point-in-time, consistent copy** of data (or an application’s state) to enable **fast recovery, cloning, analytics, long-running reads**, or to **shorten replay** from change logs (e.g., event stores/WAL).

## Also Known As

-   Point-in-Time Copy (PITC) / Point-in-Time Recovery (PITR)

-   Checkpoint / Savepoint (streaming & batch)

-   Copy-on-Write (CoW) Snapshot

-   Database/Volume Snapshot


## Motivation (Forces)

-   **Recovery goals:** Restore quickly without replaying the entire history or reprocessing everything.

-   **Operational agility:** Create **zero/low-downtime clones** for testing, reporting, or schema migrations.

-   **Performance isolation:** Serve **long analytical reads** from a static view without blocking OLTP.

-   **Event sourcing & logs:** Speed up **rehydration** by starting from the last snapshot + replaying tail events.


Tensions:

-   **Storage overhead** vs. recovery speed (full vs. incremental snapshots).

-   **Consistency scope:** Single node/table is easy; **global consistency** across many services is hard.

-   **Write amplification:** CoW/redirect-on-write can add overhead to hot data.


## Applicability

Use snapshots when:

-   You maintain **append-only logs** (WAL, change feed, events) and want faster reloads.

-   You need **fast clones** for testing/reporting with minimal impact to primaries.

-   You must support **PITR** (e.g., “restore to 10:47:03 UTC”).

-   You operate **streaming/dataflow** systems that periodically **checkpoint** operator state.


Avoid or adapt when:

-   Only **tiny datasets** exist (full rebuild is cheaper).

-   Strict **cross-system atomicity** is required but not enforceable (then coordinate a global snapshot or quiesce writers).


## Structure

```pgsql
Writes               periodic                      reads/restore
Client ───> Dataset/DB ───────► Snapshot Store ──────► Consumers / Restorers
             (WAL/Events) \             ▲                 (mount/restore)
                            \            │
                             └──► Change Log (WAL/Event Stream)
                                  (replay tail after snapshot)
```

## Participants

-   **Source Dataset / State:** The live database/table/index or in-memory state.

-   **Snapshot Engine:** Produces consistent copies (full, CoW, redirect-on-write, incremental).

-   **Change Log (WAL/Events):** Operations since the last snapshot; used for replay.

-   **Catalog/Metadata:** Snapshot IDs, timestamps, offsets/LSNs, lineage, retention.

-   **Consumers:** Restore jobs, clones (dev/test), analytics.


## Collaboration

1.  **Trigger snapshot** (schedule, size/age threshold, or manual).

2.  Snapshot engine creates a **consistent point-in-time** copy and writes **metadata** (e.g., LSN/seq).

3.  New writes continue; the WAL/change log tracks post-snapshot changes.

4.  **Restore/rehydrate** loads the latest snapshot and **replays** the tail of the log up to the desired point.

5.  **Retention** periodically deletes/archives old snapshots & logs.


## Consequences

**Benefits**

-   **Fast recovery/cloning** with minimal downtime.

-   **Stable, repeatable reads** for analytics/testing.

-   **Bounded replay** for event-sourced systems.

-   Enabler for **time travel** queries (with versioned table formats).


**Liabilities**

-   **Storage & I/O cost** (especially for frequent full snapshots).

-   **Write overhead** for CoW/redirect-on-write.

-   **Consistency pitfalls** across multiple resources without coordination.

-   **Management complexity** (catalog, retention, encryption, access control).


## Implementation (Key Points)

-   **Technique choices:**

    -   **Block/volume snapshots** (EBS/ZFS/LVM/CoW) for whole-volume speed.

    -   **Database-native** (e.g., Oracle MVs/Flashback, MySQL InnoDB snapshot via LSN, Postgres physical backup + WAL/LSN).

    -   **Table-format snapshots** (Delta Lake / Apache Iceberg / Hudi) with metadata & time-travel.

    -   **Application-level** snapshots for event-sourced aggregates or streaming checkpointing.

-   **Consistency:**

    -   Single resource: take snapshot within a **transaction/LSN** boundary.

    -   Multi-resource: use **global fences**, **barriers**, or **two-phase cut** (quiesce → mark → resume).

-   **Retention & governance:** Tag snapshots with **timestamp, LSN/seq, schema version**; enforce retention, encryption, and access policies.

-   **Performance:** Schedule snapshots off-peak; throttle I/O; choose **incremental** where supported.

-   **Recovery drills:** Regularly **restore & verify** integrity and RPO/RTO objectives.


---

## Sample Code (Java 17): App-Level Snapshot + WAL for a Simple KV Store

> Educational single-file demo (no external libs).
>
> -   Append-only **WAL** for `PUT`/`DELETE` with monotonically increasing `seq`
>
> -   Periodic **snapshot** serializes full state + last `seq`
>
> -   **Restore** loads the latest snapshot and replays WAL entries **after** the snapshot
>

```java
// File: SnapshotKvDemo.java
// Compile: javac SnapshotKvDemo.java
// Run:     java SnapshotKvDemo
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

public class SnapshotKvDemo {

  /* ---------- WAL entry ---------- */
  static final class WalEntry {
    final long seq;
    final String op; // PUT or DEL
    final String key;
    final String value; // null for DEL
    final long ts;

    WalEntry(long seq, String op, String key, String value, long ts) {
      this.seq = seq; this.op = op; this.key = key; this.value = value; this.ts = ts;
    }

    static WalEntry parse(String line) {
      // Format: seq|ts|op|key|valueBase64OrEmpty
      String[] a = line.split("\\|", -1);
      long seq = Long.parseLong(a[0]);
      long ts  = Long.parseLong(a[1]);
      String op = a[2];
      String key = a[3];
      String val = a.length >= 5 && !a[4].isEmpty()
          ? new String(Base64.getDecoder().decode(a[4]), StandardCharsets.UTF_8)
          : null;
      return new WalEntry(seq, op, key, val, ts);
    }

    String serialize() {
      String v = value == null ? "" :
          Base64.getEncoder().encodeToString(value.getBytes(StandardCharsets.UTF_8));
      return seq + "|" + ts + "|" + op + "|" + key + "|" + v + "\n";
    }
  }

  /* ---------- KV store with WAL + snapshots ---------- */
  static final class KvStore implements Closeable {
    private final Map<String,String> map = new ConcurrentHashMap<>();
    private final Path walPath;
    private final Path snapDir;
    private long nextSeq = 1;
    private BufferedWriter walWriter;

    KvStore(Path dir) throws IOException {
      Files.createDirectories(dir);
      this.walPath = dir.resolve("kv.wal");
      this.snapDir = dir.resolve("snapshots");
      Files.createDirectories(snapDir);
      // open WAL for append
      walWriter = Files.newBufferedWriter(walPath,
          StandardCharsets.UTF_8, StandardOpenOption.CREATE, StandardOpenOption.APPEND);
    }

    public synchronized void put(String key, String value) throws IOException {
      apply(new WalEntry(nextSeq++, "PUT", key, value, Instant.now().toEpochMilli()), true);
    }
    public synchronized void del(String key) throws IOException {
      apply(new WalEntry(nextSeq++, "DEL", key, null, Instant.now().toEpochMilli()), true);
    }
    public String get(String key) { return map.get(key); }
    public int size() { return map.size(); }

    private void apply(WalEntry e, boolean append) throws IOException {
      if ("PUT".equals(e.op)) map.put(e.key, e.value);
      else if ("DEL".equals(e.op)) map.remove(e.key);
      if (append) {
        walWriter.write(e.serialize());
        walWriter.flush();
      }
    }

    /** Create a full snapshot file containing: lastSeq\n followed by key\tvalue lines. */
    public synchronized Path snapshot() throws IOException {
      long lastSeq = nextSeq - 1;
      Path tmp = Files.createTempFile(snapDir, "snap-", ".tmp");
      try (BufferedWriter out = Files.newBufferedWriter(tmp, StandardCharsets.UTF_8)) {
        out.write(Long.toString(lastSeq)); out.write("\n");
        for (var e : map.entrySet()) {
          String k = e.getKey();
          String v = e.getValue() == null ? "" :
            Base64.getEncoder().encodeToString(e.getValue().getBytes(StandardCharsets.UTF_8));
          out.write(k + "\t" + v + "\n");
        }
      }
      Path finalPath = snapDir.resolve("snap-" + lastSeq + ".dat");
      Files.move(tmp, finalPath, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
      return finalPath;
    }

    /** Restore from latest snapshot (if any) and replay WAL tail. */
    public synchronized void restore() throws IOException {
      long snapSeq = loadLatestSnapshot();
      // replay WAL entries with seq > snapSeq
      if (Files.exists(walPath)) {
        try (BufferedReader r = Files.newBufferedReader(walPath, StandardCharsets.UTF_8)) {
          String line;
          while ((line = r.readLine()) != null) {
            if (line.isBlank()) continue;
            WalEntry e = WalEntry.parse(line);
            if (e.seq > snapSeq) apply(e, false);
            nextSeq = Math.max(nextSeq, e.seq + 1);
          }
        }
      }
    }

    private long loadLatestSnapshot() throws IOException {
      if (!Files.exists(snapDir)) return 0L;
      long bestSeq = 0L; Path best = null;
      try (DirectoryStream<Path> ds = Files.newDirectoryStream(snapDir, "snap-*.dat")) {
        for (Path p : ds) {
          String s = p.getFileName().toString().replace("snap-", "").replace(".dat", "");
          try {
            long seq = Long.parseLong(s);
            if (seq > bestSeq) { bestSeq = seq; best = p; }
          } catch (NumberFormatException ignore) {}
        }
      }
      if (best == null) return 0L;
      map.clear();
      try (BufferedReader r = Files.newBufferedReader(best, StandardCharsets.UTF_8)) {
        String first = r.readLine(); // lastSeq
        String line;
        while ((line = r.readLine()) != null) {
          if (line.isBlank()) continue;
          int i = line.indexOf('\t');
          String key = (i >= 0) ? line.substring(0, i) : line;
          String v64 = (i >= 0) ? line.substring(i+1) : "";
          String val = v64.isEmpty() ? null :
              new String(Base64.getDecoder().decode(v64), StandardCharsets.UTF_8);
          if (val != null) map.put(key, val); else map.remove(key);
        }
        try { bestSeq = Long.parseLong(first); } catch (Exception ignore) {}
      }
      nextSeq = Math.max(nextSeq, bestSeq + 1);
      return bestSeq;
    }

    @Override public void close() throws IOException { walWriter.close(); }
  }

  /* ---------- Demo ---------- */
  public static void main(String[] args) throws Exception {
    Path dir = Paths.get("kvdata");
    // Start fresh
    if (Files.exists(dir)) {
      try (var s = Files.walk(dir)) { s.sorted(Comparator.reverseOrder()).forEach(p -> { try { Files.delete(p); } catch (Exception ignored) {} }); }
    }

    // 1) Create store, write some keys
    try (KvStore kv = new KvStore(dir)) {
      kv.put("user:1", "Alice");
      kv.put("user:2", "Bob");
      kv.put("feature:dark_mode", "on");
      System.out.println("Before snapshot, size=" + kv.size());
      Path snap = kv.snapshot();
      System.out.println("Snapshot created: " + snap.getFileName());

      // More writes after snapshot
      kv.del("user:2");
      kv.put("user:3", "Carol");
      System.out.println("Post-snapshot writes, size=" + kv.size());
    }

    // 2) Simulate restart: restore from latest snapshot + WAL tail
    try (KvStore kv2 = new KvStore(dir)) {
      kv2.restore();
      System.out.println("Restored size=" + kv2.size());
      System.out.println("user:1=" + kv2.get("user:1"));
      System.out.println("user:2=" + kv2.get("user:2"));
      System.out.println("user:3=" + kv2.get("user:3"));
    }
  }
}
```

**What this demonstrates**

-   A periodic **snapshot** captures full state + the **last applied sequence**.

-   **Restore** loads the snapshot and **replays WAL** entries with `seq > lastSeq`, achieving fast, bounded recovery.

-   This mirrors database/table snapshot + log replay, and event-sourced aggregate **snapshotting**.


---

## Known Uses

-   **Block/volume**: AWS **EBS snapshots**, ZFS/LVM/NetApp CoW snapshots.

-   **Databases**: Postgres physical basebackup + WAL; MySQL/InnoDB LSN-aligned backups; Oracle RMAN; SQL Server DB snapshots.

-   **Lakehouse tables**: Delta Lake / Apache **Iceberg** / Hudi **table snapshots** & time travel.

-   **Streaming**: Flink/Kafka Streams **state checkpoints**; Spark **checkpoint** in streaming pipelines.

-   **Event Sourcing**: Aggregate **snapshots** every *N* events to speed rehydration.


## Related Patterns

-   **Event Sourcing** (snapshots reduce replay cost)

-   **Write-Ahead Log (WAL) / Change Data Capture** (replay tail)

-   **Materialized View** (a kind of maintained snapshot for reads)

-   **Read Replica** (serves consistent-ish read copies; often built from snapshots + logs)

-   **Backup & Restore** (operational counterpart; snapshots can be backups when durable & off-box)

-   **Snapshot Isolation** (transactional read view; conceptually related but not the same artifact)


---

### Practical Tips

-   Always record a **fence/offset** with each snapshot (LSN/GTID/seq + timestamp).

-   Prefer **incremental** or CoW snapshots for hot, large datasets; keep **full** snapshots periodically as anchors.

-   Coordinate **multi-resource** snapshots with barriers or a **two-phase cut**; otherwise, document the **replay strategy** to converge.

-   Encrypt, tag, and **expire** snapshots; test **restore regularly** (the only snapshot that matters is a verified restore).

-   For event-sourced systems, snapshot **every N events** or when **rehydration time** exceeds your SLA; store snapshot **version/schema** for upcasting.
