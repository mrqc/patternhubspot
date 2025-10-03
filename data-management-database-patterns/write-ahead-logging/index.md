
# Data Management & Database Pattern — Write-Ahead Logging (WAL)

## Pattern Name and Classification

-   **Name:** Write-Ahead Logging (WAL)

-   **Classification:** Durability & crash-recovery pattern (append-only redo/undo log; commit ordering)


## Intent

Before mutating persistent state, **append a log record** describing the change and **durably flush the log**. On crash or restart, **replay the log** (redo and/or undo) to make the database **atomic & durable** (the “A” and “D” in ACID) without forcing full data pages to disk synchronously.

## Also Known As

-   Redo/Undo Log

-   Transaction Log / Commit Log / Journal

-   Write-Ahead Journal (filesystems)


## Motivation (Forces)

-   **Power loss/crashes** must not corrupt data or lose committed transactions.

-   **Performance:** Flushing large/ scattered pages per txn is slow; appending to a **sequential log** is fast (coalesced writes, group commit).

-   **Concurrency:** Buffer cache can apply changes lazily if the **log is durable first**.

-   **Replication/CDC:** The log is a natural **change feed** for replicas and downstream systems.


Tensions:

-   **Extra writes** (log + data) and **log management** (size, archiving).

-   **Complex recovery algorithms** (ARIES) for high concurrency.

-   **Ordering guarantees** vs. modern storage (fsync semantics, caches, FUA).


## Applicability

Use WAL when:

-   You need **ACID** durability on top of disks/SSDs.

-   You want **fast commits** (append) with delayed page flushing.

-   You plan to build **replication** or **CDC** by shipping the log.


Be careful when:

-   Very high ingest plus large values may make the log the bottleneck → batch/group commit, compress, or use parallel logs.

-   You cannot rely on OS/filesystem flushing semantics → use **fdatasync**, `O_DSYNC`/FUA, checksums.


## Structure

```vbnet
Client Txn ---> Buffer Cache (dirty pages) ----.
                    |                          |
                    | write-ahead              |
                    v                          |
            WAL (append-only, LSN-ordered)     |
                    |  fsync/flush             |
                    '----> Commit acknowledged |
                               (group commit)  |
Crash/Restart:  WAL scan -> REDO committed; UNDO uncommitted (depending on design)
Checkpoint: snapshot+LSN to bound recovery time
```

## Participants

-   **WAL/Log:** Append-only file(s) with **Log Sequence Numbers (LSN)**, payload, checksums.

-   **Buffer Manager:** Holds dirty pages; each page stores **pageLSN** of last change.

-   **Flusher/Checkpointer:** Periodically fsyncs WAL and data pages; writes **checkpoint** with min LSN still needed.

-   **Recovery Manager:** On restart, scans WAL (and sometimes a dirty page table/txn table) to REDO/UNDO.

-   **Archiver/Streamer:** Ships/archives WAL segments for PITR/replication.


## Collaboration

1.  Transaction generates a change → **append log record** with new state (and old state if UNDO needed).

2.  **Flush WAL** up to the record’s LSN (**before** flushing the corresponding data page).

3.  Optionally delay/apply page writes; maintain **pageLSN** ≥ last applied log LSN.

4.  On **commit**, ensure WAL up to the commit LSN is durable (group commit).

5.  On **crash**, run recovery: **REDO** all operations ≥ checkpoint LSN (idempotent) and **UNDO** losers if using undo logging.


## Consequences

**Benefits**

-   **Durable, atomic commits** with **sequential I/O**.

-   **Fast recovery** by replaying only recent log (bounded by checkpoints).

-   Enables **replication**, **CDC**, **time travel/PITR**.


**Liabilities**

-   **Write amplification** (log + data).

-   **Space management:** log rotation, archiving, checkpoints.

-   **Implementation complexity:** careful ordering, checksums, torn-write handling.


## Implementation (Key Points)

-   **Record format:** `(LSN, txnId, type, page/key, before/after image, checksum)`.

-   **LSN discipline:** data page can be written only after WAL ≤ pageLSN is durable (**write-ahead rule**).

-   **Atomicity choices:**

    -   **Redo-only** (common with copy-on-write/index-log-structured engines)

    -   **ARIES** style **physiological logging** with **Undo/Redo**, CLRs, and repeating history.

-   **Group commit:** batch fsyncs to amortize latency.

-   **Checksums + headers:** detect torn/partial log writes; **truncate** at last valid LSN on recovery.

-   **Checkpoints:** write snapshot/markers (active txns + dirty pages) to **cap recovery time**.

-   **Log shipping:** stream fsynced segments to replicas for **async replication** and **PITR**.

-   **Storage semantics:** use `fdatasync`/`FileChannel.force(true)`; beware controller caches; consider **FUA**/barriers.

-   **Compaction:** archive or delete log segments older than the last durable **checkpoint**.


---

## Sample Code (Java 17): Minimal Redo-Only WAL for a Tiny KV Store

> Educational single-file demo (no external libs).
>
> -   **Write-ahead rule:** append + fsync WAL, **then** update the store file.
>
> -   **Checksum** per record, **LSN** monotonic.
>
> -   **Recovery:** on startup, scan WAL and **redo** idempotently; truncates on first corrupted/torn record.
>
> -   **Checkpoint:** snapshot the entire KV and reset WAL (bounds recovery time).
>

```java
// File: WalKvDemo.java
// Compile: javac WalKvDemo.java
// Run:     java WalKvDemo
import java.io.*;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.zip.CRC32;

public class WalKvDemo implements Closeable {
  /* ----- Record layout: [len][lsn][op][kLen][vLen][key][val][crc] ----- */
  static final byte OP_PUT = 1;
  static final byte OP_DEL = 2;

  private final Path dir, walPath, dataPath, snapPath;
  private final Map<String,String> kv = new ConcurrentHashMap<>();
  private long nextLsn = 1;
  private FileChannel wal;

  public WalKvDemo(Path dir) throws Exception {
    this.dir = dir;
    this.walPath = dir.resolve("wal.log");
    this.dataPath = dir.resolve("store.dat");
    this.snapPath = dir.resolve("snapshot.dat");
    Files.createDirectories(dir);
    wal = FileChannel.open(walPath,
        StandardOpenOption.CREATE, StandardOpenOption.WRITE, StandardOpenOption.APPEND);
    // Restore: snapshot then WAL redo
    loadSnapshotIfAny();
    redoWal();
  }

  /* ---------------- Public API ---------------- */

  public synchronized void put(String key, String value) throws Exception {
    byte[] k = key.getBytes(StandardCharsets.UTF_8);
    byte[] v = value.getBytes(StandardCharsets.UTF_8);
    long lsn = nextLsn++;
    appendWal(lsn, OP_PUT, k, v);     // 1) WAL append + fsync
    kv.put(key, value);                // 2) apply in-memory
    flushStore();                      // 3) persist state lazily (demo does full rewrite)
  }

  public synchronized void del(String key) throws Exception {
    byte[] k = key.getBytes(StandardCharsets.UTF_8);
    long lsn = nextLsn++;
    appendWal(lsn, OP_DEL, k, new byte[0]);
    kv.remove(key);
    flushStore();
  }

  public String get(String key) { return kv.get(key); }

  /** Checkpoint: write full snapshot, rotate WAL (truncate). */
  public synchronized void checkpoint() throws Exception {
    // Write snapshot atomically
    Path tmp = snapPath.resolveSibling("snapshot.tmp");
    try (BufferedWriter out = Files.newBufferedWriter(tmp, StandardCharsets.UTF_8)) {
      out.write(Long.toString(nextLsn - 1)); out.write("\n"); // last applied LSN
      for (var e : kv.entrySet()) {
        out.write(escape(e.getKey())); out.write("\t"); out.write(escape(e.getValue())); out.write("\n");
      }
    }
    Files.move(tmp, snapPath, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
    // Reset WAL
    wal.close();
    Files.deleteIfExists(walPath);
    wal = FileChannel.open(walPath,
        StandardOpenOption.CREATE, StandardOpenOption.WRITE, StandardOpenOption.APPEND);
  }

  @Override public void close() throws IOException { if (wal != null) wal.close(); }

  /* ---------------- Internals ---------------- */

  private void appendWal(long lsn, byte op, byte[] key, byte[] val) throws Exception {
    int len = 8 + 1 + 4 + 4 + key.length + val.length + 8; // lsn+op+kLen+vLen+data+crc
    ByteBuffer buf = ByteBuffer.allocate(4 + len);
    buf.putInt(len);
    buf.putLong(lsn);
    buf.put(op);
    buf.putInt(key.length);
    buf.putInt(val.length);
    buf.put(key);
    buf.put(val);
    long crc = crc32(buf.array(), 4, len - 8); // exclude [len] and placeholder crc field
    buf.putLong(crc);
    buf.flip();
    wal.write(buf);
    wal.force(true); // fsync WAL before acknowledging/continuing
  }

  private void redoWal() throws Exception {
    if (!Files.exists(walPath)) return;
    try (FileChannel ch = FileChannel.open(walPath, StandardOpenOption.READ)) {
      long pos = 0;
      while (true) {
        ByteBuffer hdr = ByteBuffer.allocate(4);
        int r = ch.read(hdr, pos);
        if (r < 0) break; if (r < 4) break; // truncated
        hdr.flip();
        int len = hdr.getInt();
        ByteBuffer rec = ByteBuffer.allocate(len);
        r = ch.read(rec, pos + 4);
        if (r < len) break; // partial record -> crash during write; stop here (truncate)
        rec.flip();

        long lsn = rec.getLong();
        byte op = rec.get();
        int kLen = rec.getInt();
        int vLen = rec.getInt();
        byte[] k = new byte[kLen];
        rec.get(k);
        byte[] v = new byte[vLen];
        rec.get(v);
        long storedCrc = rec.getLong();
        long crc = crc32(rec.array(), 0, len - 8);
        if (crc != storedCrc) break; // torn write -> stop replay at last valid record

        String key = new String(k, StandardCharsets.UTF_8);
        if (op == OP_PUT) kv.put(key, new String(v, StandardCharsets.UTF_8));
        else if (op == OP_DEL) kv.remove(key);
        nextLsn = Math.max(nextLsn, lsn + 1);
        pos += 4 + len;
      }
    }
    flushStore(); // persist reconstructed state
  }

  private void loadSnapshotIfAny() throws Exception {
    if (!Files.exists(snapPath)) return;
    try (BufferedReader r = Files.newBufferedReader(snapPath, StandardCharsets.UTF_8)) {
      String first = r.readLine();
      if (first != null) {
        try { nextLsn = Long.parseLong(first) + 1; } catch (NumberFormatException ignore) {}
      }
      kv.clear();
      for (String line; (line = r.readLine()) != null; ) {
        int i = line.indexOf('\t');
        if (i < 0) continue;
        kv.put(unescape(line.substring(0, i)), unescape(line.substring(i + 1)));
      }
    }
  }

  private void flushStore() throws Exception {
    // For demo simplicity: rewrite whole map atomically (real systems flush pages)
    Path tmp = dataPath.resolveSibling("store.tmp");
    try (BufferedWriter out = Files.newBufferedWriter(tmp, StandardCharsets.UTF_8)) {
      for (var e : kv.entrySet()) {
        out.write(escape(e.getKey())); out.write("\t"); out.write(escape(e.getValue())); out.write("\n");
      }
    }
    Files.move(tmp, dataPath, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
  }

  private static long crc32(byte[] a, int off, int len) {
    CRC32 c = new CRC32(); c.update(a, off, len); return c.getValue();
  }
  private static String escape(String s){ return s.replace("\\","\\\\").replace("\t","\\t").replace("\n","\\n"); }
  private static String unescape(String s){ return s.replace("\\t","\t").replace("\\n","\n").replace("\\\\","\\"); }

  /* ---------------- Demo main ---------------- */
  public static void main(String[] args) throws Exception {
    Path dir = Paths.get("wal_demo");
    // Start fresh (delete old demo files)
    if (Files.exists(dir)) try (var st = Files.walk(dir)) { st.sorted(Comparator.reverseOrder())
        .forEach(p -> { try { Files.delete(p); } catch (Exception ignored) {} }); }

    // 1) Start node, write a few keys
    try (WalKvDemo db = new WalKvDemo(dir)) {
      db.put("user:1", "Alice");
      db.put("user:2", "Bob");
      db.del("user:2");
      System.out.println("Before checkpoint: user:1=" + db.get("user:1") + ", user:2=" + db.get("user:2"));
      db.checkpoint(); // bounds recovery
      db.put("feature:dark_mode", "on");
      System.out.println("Wrote more after checkpoint.");
    }

    // 2) Simulate crash: reopen and recover from snapshot + WAL
    try (WalKvDemo db2 = new WalKvDemo(dir)) {
      System.out.println("After recovery: user:1=" + db2.get("user:1"));
      System.out.println("After recovery: user:2=" + db2.get("user:2"));
      System.out.println("After recovery: feature=" + db2.get("feature:dark_mode"));
    }
  }
}
```

**Why this is WAL**

-   Every mutation is **logged and fsynced** first; only then is the persistent state updated—so a crash can always **redo** to reach a consistent, committed state.

-   **Checkpoint** trims recovery time by snapshotting and resetting the log.

-   **Checksums** guard against torn writes and define a safe truncation point.


---

## Known Uses

-   **Databases:** PostgreSQL **WAL**, MySQL/InnoDB **redo log**, SQLite **WAL mode**, H2 MVStore log, SQL Server **transaction log**.

-   **KV/LSM engines:** RocksDB/LevelDB write-ahead log.

-   **Distributed filesystems & FS journaling:** ext4/NTFS/XFS journals; HDFS NameNode **edits log**.

-   **Stream processors:** Flink/Kafka Streams **changelogs** for state stores.


## Related Patterns

-   **Snapshot / Checkpoint:** Pair with WAL to bound recovery time.

-   **Change Data Capture (CDC):** Tail WAL to publish change events.

-   **Read Replica / Log Shipping:** Replicate by streaming fsynced WAL segments.

-   **Event Sourcing:** Conceptually similar (append facts then rebuild), but WAL is implementation-level and often binary/physical.

-   **Transactional Outbox:** Application-level reliable messaging; WAL is the storage-level journal.

-   **Write-Through/Write-Behind Cache:** WAL ensures durability of the authoritative store.


---

### Practical Tips

-   Use **group commit** and sticky batching to amortize fsync latency.

-   Stamp each page with **pageLSN**; only flush a page after WAL ≤ pageLSN is durable.

-   Add **segment rotation** (e.g., 16 MB) with naming like `000000010000000A.wal` and an **archiver**.

-   Protect against **torn pages** with page checksums and **double-write buffers** (InnoDB) or copy-on-write.

-   Measure **fsync latency** and consider **direct I/O**/barriers; validate your platform’s guarantees.

-   Expose metrics: **oldest required LSN** (recovery window), log flush time, bytes/sec, and replication lag.

-   Verify recovery regularly; an untested WAL is not a recovery plan.
