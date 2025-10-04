# Watchdog Timer — Resilience & Fault Tolerance Pattern

## Pattern Name and Classification

**Name:** Watchdog Timer  
**Classification:** Resilience / Fault Tolerance / Liveness Supervision (Self-healing & Control Plane)

---

## Intent

Continuously verify that a component **progresses** (isn’t hung, deadlocked, or stalled) by requiring it to **periodically signal (“kick”)** a timer. If the timer **expires** without a kick, execute a **corrective action** (e.g., restart process, failover, abort task, dump diagnostics).

---

## Also Known As

-   Watchdog
    
-   Heartbeat Supervisor
    
-   Liveness Timer / Deadman’s Switch
    
-   Guard Timer
    

---

## Motivation (Forces)

-   **Hangs are silent:** Timeouts catch slow calls, but entire threads or processes can **deadlock**, stall on GC or I/O, or enter infinite loops.
    
-   **Fail fast for recovery:** Automatic **restart** or **cutover** often beats human intervention.
    
-   **External supervision:** Kubernetes/systemd can restart a crashed process, but **hung** processes may still look “alive” to the OS unless we **self-report** progress.
    
-   **Bounded SLOs:** Stuck background jobs and schedulers must not hold locks or capacity indefinitely.
    
-   **Forensics:** On expiry, collect diagnostics (thread dumps, heap histograms) to shorten MTTR.
    

---

## Applicability

Use a Watchdog Timer when:

-   You run **long-lived workers**, batch jobs, or schedulers that must **make progress**.
    
-   Critical sections must **not exceed** a duration (e.g., leader reconciliation, compaction).
    
-   You need **external action** (restart, failover) when liveness is unknown.
    
-   The environment supports **hooks** (systemd, K8s, ECS, supervisors) or you can implement in-process.
    

Avoid or scope carefully when:

-   Operations are **legitimately long** and non-interruptible; prefer chunking/checkpoints.
    
-   False positives would be **worse** than waiting (e.g., financial settlement mid-commit).
    
-   You already have **end-to-end deadlines** and robust cancellation; a watchdog may be redundant.
    

---

## Structure

-   **Watchdog Timer:** Counts down from a configured interval; requires **kicks** before expiry.
    
-   **Kicker/Probe:** The code path that must prove progress (e.g., each item processed).
    
-   **Expiry Policy:** What to do on timeout (kill, restart, failover, diagnostics, alert).
    
-   **Supervisor/Orchestrator:** Optional external entity that reacts to expiry signals (K8s, systemd, Monit).
    
-   **Telemetry & Forensics:** Metrics and dumps produced on expiry for root cause analysis.
    

---

## Participants

-   **Observed Component:** Worker, scheduler, leader loop, critical section.
    
-   **Watchdog:** Local timer (in the same process) or external heartbeat file/socket/health endpoint.
    
-   **Supervisor:** Takes action on expiry (SIGTERM/SIGKILL, pod restart, fencing).
    
-   **Observer:** Metrics/logging/alerts consuming watchdog events.
    

---

## Collaboration

1.  **Component** starts work and **arms** the watchdog with an interval (`T`).
    
2.  As work **progresses**, the component **kicks** the watchdog (resets countdown).
    
3.  If no kick occurs before `T` expires, the **watchdog fires**:
    
    -   Runs **expiry hooks** (dump stacks, emit metric/alert).
        
    -   Optionally **terminates** the process or **releases a lease** (to allow failover).
        
4.  The **supervisor** sees termination or degraded health and **restarts or reassigns**.
    

---

## Consequences

**Benefits**

-   Detects **hung** or **deadlocked** threads that health probes may miss.
    
-   Provides **deterministic recovery** and limits worst-case outage duration.
    
-   Produces **forensics** at the right moment (on the first failure).
    
-   Simple mental model: “if no progress, act.”
    

**Liabilities**

-   **False positives** if interval too short or GC pauses are long.
    
-   If the **kicker** runs in the same blocked threads, it may never kick—design kicks from **independent** execution contexts.
    
-   Over-eager expiry actions (hard kill) can cause partial work or require compensation.
    
-   Requires careful **idempotency** and **re-entry safety** on restart.
    

---

## Implementation

### Key Decisions

-   **Interval selection:** Base on **expected progress cadence** + headroom (e.g., 3× p99 step time).
    
-   **Placement:**
    
    -   **In-process** (fastest): Scheduled watchdog thread; kick via API.
        
    -   **External heartbeat**: Write timestamp to file/Redis; a sidecar or supervisor checks freshness.
        
-   **Action on expiry:**
    
    -   **Soft**: dump diagnostics, mark unhealthy, release leadership.
        
    -   **Hard**: `System.exit(1)` (let the orchestrator restart).
        
-   **Isolation:** Run watchdog on a **dedicated thread** with elevated priority; avoid sharing pools with the work being observed.
    
-   **Integration:**
    
    -   **Kubernetes:** Flip **readiness** to false or crash; use `liveness` to restart.
        
    -   **systemd:** `WatchdogSec=` with `sd_notify` (JNI wrapper if needed).
        
-   **Forensics:** On expiry, **thread dump**, **heap summary**, and key counters; ship to logs.
    

### Anti-Patterns

-   Kicking the watchdog on a **timer**, not on **actual progress** (masks hangs).
    
-   Only in-process watchdog with **no external reaction**—expiry logged but nothing restarts it.
    
-   Using the same **busy thread pool** to run both work and watchdog (watchdog stalls too).
    
-   Immediate **hard kill** without attempts to release locks/leases/fences.
    
-   Single global watchdog for many unrelated tasks with different cadences.
    

---

## Sample Code (Java)

### A) In-Process Watchdog for Critical Sections (ScheduledExecutorService)

A lightweight watchdog that you **arm**, **kick**, and **disarm** around progress. On expiry, it executes hooks (e.g., thread dump) and **terminates** the process (configurable) so the orchestrator can restart it.

```java
// Watchdog.java
package com.example.watchdog;

import java.io.PrintWriter;
import java.io.StringWriter;
import java.lang.management.ManagementFactory;
import java.lang.management.ThreadInfo;
import java.lang.management.ThreadMXBean;
import java.time.Duration;
import java.util.Objects;
import java.util.concurrent.*;
import java.util.function.Consumer;

public final class Watchdog implements AutoCloseable {

  private final ScheduledExecutorService ses;
  private final Duration interval;
  private final Consumer<WatchdogEvent> onExpire;
  private final boolean hardExit;

  private final Object lock = new Object();
  private ScheduledFuture<?> future;
  private volatile long deadlineNanos;

  public record WatchdogEvent(Duration interval, String threadDump) {}

  public Watchdog(Duration interval,
                  Consumer<WatchdogEvent> onExpire,
                  boolean hardExit) {
    this.ses = Executors.newSingleThreadScheduledExecutor(r -> {
      Thread t = new Thread(r, "watchdog");
      t.setDaemon(true);
      t.setPriority(Math.min(Thread.NORM_PRIORITY + 1, Thread.MAX_PRIORITY));
      return t;
    });
    this.interval = Objects.requireNonNull(interval);
    this.onExpire = Objects.requireNonNullElse(onExpire, e -> {});
    this.hardExit = hardExit;
  }

  /** Start or restart countdown. Call this when real progress happens. */
  public void kick() {
    synchronized (lock) {
      deadlineNanos = System.nanoTime() + interval.toNanos();
      if (future == null || future.isDone()) {
        future = ses.scheduleWithFixedDelay(this::check, interval.toMillis() / 2,
            Math.max(50, interval.toMillis() / 4), TimeUnit.MILLISECONDS);
      }
    }
  }

  /** Stop monitoring. */
  public void disarm() {
    synchronized (lock) {
      if (future != null) {
        future.cancel(false);
        future = null;
      }
    }
  }

  private void check() {
    long now = System.nanoTime();
    if (now >= deadlineNanos) {
      String dump = threadDump();
      try {
        onExpire.accept(new WatchdogEvent(interval, dump));
      } catch (Throwable ignore) {}
      if (hardExit) {
        System.err.println("[WATCHDOG] Expired. Exiting.");
        System.err.println(dump);
        // Give logs a moment to flush
        try { Thread.sleep(200); } catch (InterruptedException ignored) { Thread.currentThread().interrupt(); }
        System.exit(1);
      } else {
        disarm();
      }
    }
  }

  private static String threadDump() {
    ThreadMXBean mx = ManagementFactory.getThreadMXBean();
    ThreadInfo[] infos = mx.dumpAllThreads(true, true);
    StringWriter sw = new StringWriter();
    PrintWriter pw = new PrintWriter(sw);
    for (ThreadInfo ti : infos) {
      if (ti != null) pw.println(ti.toString());
    }
    return sw.toString();
  }

  @Override public void close() { disarm(); ses.shutdownNow(); }
}
```

**Usage around a progressing loop (kick on real work):**

```java
// Worker.java
package com.example.watchdog;

import java.time.Duration;

public class Worker {
  public static void main(String[] args) throws Exception {
    Watchdog wd = new Watchdog(
        Duration.ofSeconds(30),
        evt -> {
          // ship metrics / logs, release leases, etc.
          System.err.println("[WATCHDOG] Interval " + evt.interval() + " expired.");
        },
        true // hard exit to trigger orchestrator restart
    );

    try {
      while (true) {
        // Fetch next unit of work (blocking pop with timeout recommended)
        // ...
        doUnitOfWork();
        wd.kick(); // prove progress after each successfully processed unit
      }
    } finally {
      wd.close();
    }
  }

  static void doUnitOfWork() {
    // business logic; ensure this returns periodically
  }
}
```

### B) Leader Duty with Watchdog & Fencing (combining patterns)

Guard a **leader loop** so that if reconciliation stalls, the watchdog **releases leadership** and exits safely.

```java
// LeaderDuty.java
package com.example.watchdog;

import java.time.Duration;
import java.util.concurrent.atomic.AtomicBoolean;

public final class LeaderDuty {

  private final AtomicBoolean haveLease = new AtomicBoolean(false);

  public void run() {
    try (Watchdog wd = new Watchdog(Duration.ofSeconds(45),
        evt -> {
          // release leadership/lease before exiting to allow fast failover
          try { releaseLease(); } catch (Exception ignored) {}
        },
        true)) {
      acquireLease();
      haveLease.set(true);
      wd.kick(); // arm at start

      while (haveLease.get()) {
        reconcileOnce(); // should complete within a few seconds
        wd.kick();       // only after successful progress
        sleepQuietly(2000);
      }
    }
  }

  private void acquireLease() { /* grab via DB/ZK/etcd */ }
  private void releaseLease() { /* release to prevent zombie leader */ }
  private void reconcileOnce() { /* do single reconciliation step */ }

  private static void sleepQuietly(long ms) {
    try { Thread.sleep(ms); } catch (InterruptedException ie) { Thread.currentThread().interrupt(); }
  }
}
```

### C) External Heartbeat (file-based) checked by a sidecar/supervisor

If you prefer external supervision, have your process **touch** a file; a lightweight sidecar restarts you if it’s stale.

```java
// Heartbeat.java
package com.example.watchdog;

import java.io.IOException;
import java.nio.file.*;
import java.time.Instant;

public final class Heartbeat {
  private final Path path;
  public Heartbeat(Path path) { this.path = path; }
  public void beat() {
    try {
      Files.writeString(path, Long.toString(Instant.now().toEpochMilli()),
          StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING, StandardOpenOption.WRITE);
    } catch (IOException e) {
      // log
    }
  }
}
```

A sidecar (shell/Go) polls the file’s mtime and kills the process if it’s older than `T`.

---

## Known Uses

-   **System firmware/embedded**: hardware watchdogs reset devices on hangs.
    
-   **systemd**: `WatchdogSec=` with `sd_notify(WATCHDOG=1)` for service liveness.
    
-   **Kubernetes operators/controllers**: leader loops guarded with watchdogs; on expiry, **resign** and let another leader take over.
    
-   **Stream processors**: job managers/TaskExecutors use heartbeats to detect stuck tasks and reschedule.
    
-   **Distributed schedulers** (Airflow workers, custom cron runners): watchdog around task executors to bound runtime.
    

---

## Related Patterns

-   **Timeout:** Bounds a **single call**; the watchdog bounds **overall progress**.
    
-   **Health Check (Liveness/Readiness):** Watchdog failures flip health state or crash to trigger restart.
    
-   **Leader Election + Fencing:** On expiry, **release lease/fencing token** to prevent zombie leaders.
    
-   **Circuit Breaker:** If cycles keep expiring, open breakers to stop futile work.
    
-   **Bulkhead:** Watchdog protects pools from starvation; bulkheads limit blast radius.
    
-   **Retry with Exponential Backoff:** Combine with watchdog to avoid endless retry loops without progress.
    

---

## Implementation Checklist

-   Choose an **interval** tied to real progress (e.g., per record, per reconciliation step).
    
-   Ensure the **kick** happens from a thread that **won’t be blocked** by the work being observed.
    
-   Decide **expiry actions** (diagnostics, lease release, crash) and verify **idempotent restarts**.
    
-   Integrate with **orchestrator** (K8s/systemd) to actually **restart** on exit.
    
-   Emit **metrics/logs**: last kick time, expiries count, current interval.
    
-   Test with **fault injection** (deadlocks, infinite loops, GC pauses) to tune thresholds.
    
-   Document **operational runbooks** (what to check after an expiry: dumps, hotspots, object counts).

