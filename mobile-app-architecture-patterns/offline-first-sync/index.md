# Offline First Sync — Mobile App Architecture Pattern

## Pattern Name and Classification

-   **Name:** Offline First Sync
    
-   **Classification:** Data Management & Synchronization Pattern for mobile apps
    

## Intent

Make the app **fully usable without network** by treating the **local store as the source of truth** and synchronizing with the backend **opportunistically**. All reads hit local storage; writes are recorded locally and placed in a **sync queue** (outbox) to be **pushed** when conditions allow, while **pull** keeps the local store fresh.

## Also Known As

-   Local-First / Client-First
    
-   Opportunistic Sync
    
-   Outbox + Incremental Pull
    
-   Stateless API + Idempotent Writes
    

## Motivation (Forces)

-   **Unreliable connectivity:** tunnels, subways, roaming, airplane mode.
    
-   **UX:** instant reads/writes; no “spinner of doom”.
    
-   **Cost & battery:** batch/rate-limit network calls; fewer wakeups.
    
-   **Consistency:** resolve conflicts deterministically; avoid data loss.
    
-   **Security & privacy:** optionally encrypt local data at rest.
    

**Tensions**

-   **Eventual consistency:** views may be stale briefly.
    
-   **Conflicts:** parallel edits across devices; need a policy (e.g., LWW, server-wins, field-merge, CRDT).
    
-   **Operational complexity:** background jobs, retries with backoff, idempotency keys, schema migrations.
    
-   **Storage:** local caches and tombstones can grow.
    

## Applicability

Use when:

-   The app must work **offline** or with flaky networks (field work, travel, messaging, notes, POS, maps).
    
-   Latency matters; UI must stay responsive.
    
-   Users can tolerate **eventual** rather than immediate global consistency.
    

Reconsider when:

-   Hard **real-time global invariants** are mandatory (e.g., stock trading order matching).
    
-   Data cannot be stored on the device (policy/compliance), or conflicts are legally problematic.
    

## Structure

```pgsql
┌──────────────┐     writes (always)
View ──►│  Repository  │────────────────────────────┐
        └──────┬───────┘                            │
               │       read (always)                ▼
               │     ┌──────────────┐      ┌───────────────────┐
               ├────►│ Local Store  │◄────►│   Sync Engine     │◄───── Connectivity/WorkManager
               │     └──────────────┘      └───────────────────┘
               │           ▲                         │  ▲
               │           │ outbox (pending ops)    │  │
               │           └──────────────────────────┘  │
               │             pull changes since token       │
               ▼                                            ▼
            Domain                                    Remote API (idempotent)
```

## Participants

-   **Local Store:** On-device DB (e.g., Room/Realm/SQLite) with domain tables and an **Outbox** table.
    
-   **Repository:** Facade used by ViewModels/Presenters; always reads/writes local, enqueues outbox ops.
    
-   **Outbox:** Append-only queue of pending mutations, with attempt/backoff metadata.
    
-   **Sync Engine:** Background worker that **pushes** outbox ops and **pulls** server deltas; applies merges.
    
-   **Conflict Resolver:** Strategy (LWW timestamp, version check + merge, server-wins, field-level).
    
-   **Remote API:** Stateless, **idempotent** endpoints that accept client IDs/versions and return new versions/cursors.
    
-   **Connectivity Monitor / Scheduler:** Triggers sync on network regain, app foreground, periodic cadence.
    

## Collaboration

1.  **Read:** UI asks Repository → returns **local** data immediately (LiveData/Flow).
    
2.  **Write:** Repository updates local rows (sets `dirty`), enqueues an outbox op, and returns instantly.
    
3.  **Trigger:** Connectivity or user action schedules Sync Engine (e.g., WorkManager).
    
4.  **Push:** Sync Engine drains outbox in deterministic order (per entity), calling idempotent API.
    
5.  **Resolve:** On conflict (412/409), fetch server state, run **Conflict Resolver**, update local, possibly re-enqueue.
    
6.  **Pull:** After push, fetch **changes since** last cursor; upsert into local; update cursor.
    
7.  **Retry:** Transient failures → exponential backoff with jitter; poison ops → DLQ/flag for manual intervention.
    

## Consequences

**Benefits**

-   **Instant UX**, works offline.
    
-   **Resilient** to network issues; fewer drops/lost writes.
    
-   **Efficient:** batch sync, fewer radio wakes.
    
-   **Clear layering:** UI unaware of network; Repository abstracts sync.
    

**Liabilities**

-   **Complexity:** outbox, cursors, conflict policies, background constraints.
    
-   **Eventual consistency:** need user-visible cues (sync status).
    
-   **Storage growth:** handle compaction and tombstones.
    
-   **Testing burden:** simulate network partitions, replays, duplicates.
    

## Implementation

1.  **Identifiers:** Use **client-generated stable IDs** (UUID/ULID) for new entities.
    
2.  **Versioning:** Keep `version` (server monotonic) and `updatedAt` (client clock, or server on success).
    
3.  **Outbox schema:** `op_id, entity_id, type(UPSERT/DELETE), payload(JSON), attempts, nextAttemptAt`.
    
4.  **Idempotency:** Include `requestId` per op; server must be idempotent and return current `version`.
    
5.  **Ordering:** Push **per-entity** in order to avoid write reordering.
    
6.  **Conflict policy:** Start pragmatic: **LWW** on `updatedAt`, or **server-wins** for sensitive fields; evolve to field-merge/CRDT if required.
    
7.  **Pull strategy:** Use **delta tokens** (since cursor) or `If-Modified-Since`.
    
8.  **Backoff & constraints:** Use **WorkManager** with `NetworkType.UNMETERED/CONNECTED`; exponential backoff + jitter.
    
9.  **State surfacing:** Expose sync status to UI (e.g., tiny badge / last synced time).
    
10.  **Security:** Encrypt local DB, protect at-rest keys, scrub PII in logs.
    
11.  **Testing:** Contract tests for idempotency, duplicate events, conflict, airplane-mode toggles.
    

---

## Sample Code (Java, Android — Room + WorkManager + simple LWW)

> Minimal end-to-end skeleton: **Notes** app with offline create/update/delete, an **Outbox**, and a **SyncWorker** that pushes then pulls.

### Gradle (dependencies)

```gradle
implementation "androidx.room:room-runtime:2.6.1"
annotationProcessor "androidx.room:room-compiler:2.6.1"
implementation "androidx.work:work-runtime:2.9.0"
implementation "com.google.code.gson:gson:2.11.0"
```

### Entities & DAOs

```java
// data/NoteEntity.java
package offline.data;

import androidx.annotation.NonNull;
import androidx.room.Entity;
import androidx.room.PrimaryKey;

@Entity(tableName = "note")
public class NoteEntity {
  @PrimaryKey @NonNull public String id;     // client-stable UUID
  public String title;
  public String content;
  public long updatedAt;                     // client timestamp (ms)
  public long version;                       // server-assigned version
  public boolean dirty;                      // pending local change
  public boolean deleted;                    // tombstone
}
```

```java
// data/OutboxOp.java
package offline.data;

import androidx.annotation.NonNull;
import androidx.room.*;

@Entity(tableName = "outbox",
        indices = {@Index("noteId"), @Index("nextAttemptAt")})
public class OutboxOp {
  @PrimaryKey(autoGenerate = true) public long id;
  @NonNull public String noteId;
  @NonNull public String type;     // "UPSERT" or "DELETE"
  public String payloadJson;       // snapshot for UPSERT
  public int attempts;
  public long nextAttemptAt;       // epoch millis
}
```

```java
// data/SyncState.java
package offline.data;

import androidx.room.Entity;
import androidx.room.PrimaryKey;

@Entity(tableName = "sync_state")
public class SyncState {
  @PrimaryKey public int id = 1;
  public String cursor;   // server change token
  public long lastSuccessMs;
}
```

```java
// data/NoteDao.java
package offline.data;

import androidx.lifecycle.LiveData;
import androidx.room.*;
import java.util.List;

@Dao
public interface NoteDao {
  @Query("SELECT * FROM note WHERE deleted = 0 ORDER BY updatedAt DESC")
  LiveData<List<NoteEntity>> liveNotes();

  @Insert(onConflict = OnConflictStrategy.REPLACE)
  void upsert(NoteEntity n);

  @Query("UPDATE note SET deleted=1, dirty=1, updatedAt=:now WHERE id=:id")
  void softDelete(String id, long now);

  @Query("UPDATE note SET dirty=0, version=:version, updatedAt=:updatedAt WHERE id=:id")
  void markClean(String id, long version, long updatedAt);
}
```

```java
// data/OutboxDao.java
package offline.data;

import androidx.room.*;
import java.util.List;

@Dao
public interface OutboxDao {
  @Insert void insert(OutboxOp op);
  @Delete void delete(OutboxOp op);

  @Query("""
         SELECT * FROM outbox 
         WHERE nextAttemptAt <= :now 
         ORDER BY noteId, id 
         LIMIT :limit
         """)
  List<OutboxOp> due(long now, int limit);

  @Query("UPDATE outbox SET attempts=attempts+1, nextAttemptAt=:next WHERE id=:id")
  void backoff(long id, long next);
}
```

```java
// data/SyncStateDao.java
package offline.data;

import androidx.room.*;

@Dao
public interface SyncStateDao {
  @Query("SELECT * FROM sync_state WHERE id=1") SyncState get();
  @Insert(onConflict = OnConflictStrategy.REPLACE) void put(SyncState s);
}
```

```java
// data/AppDb.java
package offline.data;

import androidx.room.Database;
import androidx.room.RoomDatabase;

@Database(entities = { NoteEntity.class, OutboxOp.class, SyncState.class }, version = 1)
public abstract class AppDb extends RoomDatabase {
  public abstract NoteDao notes();
  public abstract OutboxDao outbox();
  public abstract SyncStateDao syncState();
}
```

### Remote API (placeholder)

```java
// net/NotesApi.java
package offline.net;

import java.util.List;

public interface NotesApi {
  // Idempotent upsert; returns new server version and server timestamp
  UpsertResult upsert(NoteDto dto, long ifMatchVersion) throws Exception;
  void delete(String id, long ifMatchVersion) throws Exception;
  ChangesResult fetchChanges(String cursor) throws Exception;

  class NoteDto { public String id, title, content; public long updatedAt, version; }
  class UpsertResult { public long version; public long serverUpdatedAt; }
  public static class ChangesResult {
    public String nextCursor;
    public List<NoteDto> upserts;     // includes deletions with content == null & deleted flag (if API prefers)
    public List<String> deletions;     // optional
  }
}
```

### Repository (always local; enqueue outbox)

```java
// repo/NotesRepository.java
package offline.repo;

import androidx.lifecycle.LiveData;
import com.google.gson.Gson;
import java.util.List;
import java.util.UUID;
import offline.data.*;

public class NotesRepository {
  private final AppDb db;
  private final Gson gson = new Gson();

  public NotesRepository(AppDb db) { this.db = db; }

  public LiveData<List<NoteEntity>> observeNotes() {
    return db.notes().liveNotes();
  }

  public String createOrUpdate(String idOrNull, String title, String content) {
    String id = idOrNull != null ? idOrNull : UUID.randomUUID().toString();
    long now = System.currentTimeMillis();

    NoteEntity n = new NoteEntity();
    n.id = id; n.title = title; n.content = content;
    n.updatedAt = now; n.version = n.version; n.dirty = true; n.deleted = false;
    db.runInTransaction(() -> {
      db.notes().upsert(n);
      OutboxOp op = new OutboxOp();
      op.noteId = id; op.type = "UPSERT"; op.payloadJson = gson.toJson(n);
      op.nextAttemptAt = 0L;
      db.outbox().insert(op);
    });
    return id;
  }

  public void delete(String id) {
    long now = System.currentTimeMillis();
    db.runInTransaction(() -> {
      db.notes().softDelete(id, now);
      OutboxOp op = new OutboxOp();
      op.noteId = id; op.type = "DELETE"; op.payloadJson = null; op.nextAttemptAt = 0L;
      db.outbox().insert(op);
    });
  }
}
```

### Sync Worker (push then pull; LWW resolution)

```java
// sync/SyncWorker.java
package offline.sync;

import android.content.Context;
import androidx.annotation.NonNull;
import androidx.work.*;

import com.google.gson.Gson;
import java.util.List;
import java.util.concurrent.TimeUnit;

import offline.data.*;
import offline.net.NotesApi;

public class SyncWorker extends Worker {

  private final AppDb db; private final NotesApi api; private final Gson gson = new Gson();

  public SyncWorker(@NonNull Context ctx, @NonNull WorkerParameters params) {
    super(ctx, params);
    this.db = DbProvider.get(ctx);               // your Room provider
    this.api = ApiProvider.get();                // your API provider
  }

  @NonNull @Override
  public Result doWork() {
    try {
      pushOutbox();
      pullDeltas();
      return Result.success();
    } catch (Exception e) {
      return Result.retry();
    }
  }

  private void pushOutbox() throws Exception {
    long now = System.currentTimeMillis();
    List<OutboxOp> batch = db.outbox().due(now, 100);
    for (OutboxOp op : batch) {
      try {
        if ("UPSERT".equals(op.type)) handleUpsert(op);
        else if ("DELETE".equals(op.type)) handleDelete(op);
        db.outbox().delete(op);
      } catch (NotesConflict ex) {
        // LWW: compare updatedAt; keep newer
        NotesApi.NoteDto server = ex.server;
        NoteEntity local = gson.fromJson(op.payloadJson, NoteEntity.class);
        boolean localWins = local.updatedAt >= server.updatedAt;
        if (localWins) {
          // re-send with server's version (optimistic concurrency)
          NotesApi.UpsertResult res = api.upsert(toDto(local), server.version);
          db.notes().markClean(local.id, res.version, res.serverUpdatedAt);
          db.outbox().delete(op);
        } else {
          // server wins; overwrite local and drop op
          db.runInTransaction(() -> {
            NoteEntity n = fromDto(server);
            n.dirty = false; n.deleted = false;
            db.notes().upsert(n);
            db.outbox().delete(op);
          });
        }
      } catch (Exception e) {
        // backoff with jitter
        long wait = (long) Math.min(60_000, (Math.pow(2, op.attempts + 1) * 1000));
        long jitter = (long) (Math.random() * 500);
        db.outbox().backoff(op.id, System.currentTimeMillis() + wait + jitter);
      }
    }
  }

  private void handleUpsert(OutboxOp op) throws Exception {
    NoteEntity local = gson.fromJson(op.payloadJson, NoteEntity.class);
    try {
      NotesApi.UpsertResult res = api.upsert(toDto(local), local.version);
      db.notes().markClean(local.id, res.version, res.serverUpdatedAt);
    } catch (ConflictHttp409 c) {
      throw new NotesConflict(apiFetch(local.id)); // wrap with server state
    }
  }

  private void handleDelete(OutboxOp op) throws Exception {
    // Use last known version; if unknown, pass 0 and let server decide idempotently.
    NoteEntity snapshot = db.notes().liveNotes().getValue() != null ? null : null; // not needed here
    try {
      api.delete(op.noteId, /*ifMatchVersion*/ 0);
    } catch (ConflictHttp409 c) {
      throw new NotesConflict(apiFetch(op.noteId));
    } finally {
      // Locally purge tombstone after a successful DELETE or if server already gone
      db.runInTransaction(() -> {
        NoteEntity n = new NoteEntity(); n.id = op.noteId; n.deleted = true;
        // Could actually remove the row; keeping tombstone can help dedupe pulls.
      });
    }
  }

  private void pullDeltas() throws Exception {
    SyncState s = db.syncState().get();
    String cursor = (s == null) ? null : s.cursor;
    NotesApi.ChangesResult res = api.fetchChanges(cursor);

    db.runInTransaction(() -> {
      // upserts
      if (res.upserts != null) for (NotesApi.NoteDto dto : res.upserts) {
        NoteEntity n = fromDto(dto);
        n.dirty = false; // server-sourced data is clean
        db.notes().upsert(n);
      }
      // deletions
      if (res.deletions != null) for (String id : res.deletions) {
        db.notes().softDelete(id, System.currentTimeMillis());
      }
      SyncState ns = (s == null) ? new SyncState() : s;
      ns.cursor = res.nextCursor; ns.lastSuccessMs = System.currentTimeMillis();
      db.syncState().put(ns);
    });
  }

  private NotesApi.NoteDto toDto(NoteEntity n) {
    NotesApi.NoteDto d = new NotesApi.NoteDto();
    d.id = n.id; d.title = n.title; d.content = n.content;
    d.updatedAt = n.updatedAt; d.version = n.version; return d;
  }
  private NoteEntity fromDto(NotesApi.NoteDto d) {
    NoteEntity n = new NoteEntity();
    n.id = d.id; n.title = d.title; n.content = d.content;
    n.updatedAt = d.updatedAt; n.version = d.version; return n;
  }

  private NotesApi.NoteDto apiFetch(String id) throws Exception {
    // Implement GET /notes/{id} in your API and use it here
    // For brevity, reuse pull API or add a dedicated endpoint.
    throw new ConflictHttp409(); // placeholder in this snippet
  }

  // Light conflict wrappers for brevity
  static class ConflictHttp409 extends Exception {}
  static class NotesConflict extends Exception { final NotesApi.NoteDto server; NotesConflict(NotesApi.NoteDto s){ this.server=s; } }

  // Enqueue helper
  public static void enqueueNow(Context ctx) {
    Constraints c = new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build();
    OneTimeWorkRequest req = new OneTimeWorkRequest.Builder(SyncWorker.class)
        .setConstraints(c)
        .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 5, TimeUnit.SECONDS)
        .build();
    WorkManager.getInstance(ctx).enqueueUniqueWork("sync-now", ExistingWorkPolicy.KEEP, req);
  }
}
```

### Kick sync on connectivity/app start

```java
// sync/SyncTriggers.java
package offline.sync;

import android.content.*;
import android.net.*;

public class SyncTriggers {
  public static void onAppForeground(Context ctx) {
    SyncWorker.enqueueNow(ctx);
  }
  public static void registerNetworkCallback(Context ctx) {
    ConnectivityManager cm = (ConnectivityManager) ctx.getSystemService(Context.CONNECTIVITY_SERVICE);
    cm.registerDefaultNetworkCallback(new ConnectivityManager.NetworkCallback() {
      @Override public void onAvailable(Network network) { SyncWorker.enqueueNow(ctx); }
    });
  }
}
```

> Notes
> 
> -   Replace placeholder API parts with your real endpoints.
>     
> -   For deletes, you may keep **tombstones** locally to prevent re-appearing items from stale pulls.
>     
> -   Encrypt the Room database if you store sensitive content.
>     

---

## Known Uses

-   **Google Docs/Drive mobile, Notion, Evernote:** local-first editors with background sync.
    
-   **Messaging apps** (e.g., WhatsApp): queue messages offline, send when online.
    
-   **Field service / logistics / POS** apps: capture data offline, batch sync later.
    
-   **Map & content apps**: offline regions with delta updates.
    

## Related Patterns

-   **Repository Pattern:** Repository fronts local store + sync.
    
-   **Transactional Outbox:** The outbox inside the app mirrors this pattern.
    
-   **MVVM/MVP:** Pair with MVVM; ViewModel observes local DB and triggers sync intents.
    
-   **Conflict Resolution / CRDTs:** Advanced merging for collaborative edits.
    
-   **WorkManager / Background Sync:** Scheduling mechanism for Android.
    
-   **Cache-Aside / Read-Through:** Reads from cache (local DB) with background refresh.
    
-   **Service Worker (Web):** Similar idea for PWAs.
    

---

**Practical checklist**

-   Stable IDs ✔︎ Versioning ✔︎ Outbox ✔︎ Idempotent API ✔︎
    
-   Push then pull ✔︎ Backoff + jitter ✔︎ Conflict policy ✔︎
    
-   Expose sync status to users ✔︎ Telemetry (lag, queue depth) ✔︎

