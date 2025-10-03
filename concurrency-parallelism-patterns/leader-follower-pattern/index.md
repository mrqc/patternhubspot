
# Concurrency / Parallelism Pattern — Leader–Follower

## Pattern Name and Classification

-   **Name:** Leader–Follower

-   **Classification:** Event-demultiplexing & thread coordination pattern (server concurrency)


## Intent

Use a **pool of worker threads** that **take turns** playing *leader*: exactly one thread blocks waiting for events (accept/read/…); upon an event, the leader **promotes a follower** to become the new leader and **handles** the event itself. This minimizes context switches, reduces synchronization, and keeps the hot path cache-friendly.

## Also Known As

-   Thread Pool with Leader Election

-   Turn-taking Reactor


## Motivation (Forces)

-   **Throughput vs. latency:** One blocking demultiplexer (e.g., `select`) per CPU-efficient thread avoids the overhead of many selectors or thread-per-connection.

-   **Context switch minimization:** Only one thread is blocked in the system call; others are runnable and can pick up leadership quickly.

-   **Cache locality:** The leader that detected the event often handles it immediately, improving locality.

-   **Fairness:** Rotate leadership to avoid one thread monopolizing `select`.

-   **Simplify handoffs:** Unlike Proactor or thread-per-connection, no extra handoff queue is necessary on event arrival.


## Applicability

Use when:

-   You build **high-performance servers** (NIO sockets, IPC, file watchers) where events are demultiplexed by a single OS call (e.g., `select`, `poll`, `epoll`, `kqueue`).

-   You want to **bound threads** (pool) and avoid a handoff queue between demux and handlers.

-   Most work after event readiness is **non-blocking** or short-lived.


Avoid/Adapt when:

-   Handlers are **long-running or blocking** (risk starving leadership); prefer reactive I/O + dedicated worker pool or Proactor.

-   You need **per-connection affinity** with heavyweight state—consider Actors or one-thread-per-core partitioning.


## Structure

```pgsql
+-----------------------+
            |   Leader–Follower     |
            |     Thread Pool       |
            +-----------------------+
                   ▲         ▲
            followers       leader (exactly one blocks)
                   │         │
                   │   [select()/poll()]
                   │         │  events ready
                   │         └─ promote follower
                   │            handle events (accept/read/write)
                   └───────────────► (after handling) rejoin as follower
```

## Participants

-   **Demultiplexer:** OS mechanism (selector/epoll/kqueue) that waits for readiness on multiple handles.

-   **Leader:** Exactly one thread that blocks on the demultiplexer.

-   **Followers:** The remaining threads in the pool, waiting to become leader.

-   **Handlers:** Code that processes a ready event (accept, read, parse, write).

-   **Coordinator:** Small critical section that elects a leader and promotes the next follower.


## Collaboration

1.  Threads start as **followers**.

2.  One becomes **leader** and calls `select()` (or equivalent).

3.  When events arrive, the leader **promotes** a follower to become the next leader (so the system keeps listening).

4.  The former leader **handles** the ready events.

5.  After handling, it **reverts to follower** and waits for another turn.


## Consequences

**Benefits**

-   Fewer context switches than handoff designs; at most one thread blocked in demux.

-   Good cache locality (detection → handling on same thread).

-   Scales with cores while bounding thread count.

-   Simple back-pressure: if handlers are busy, fewer threads reach leadership.


**Liabilities / Trade-offs**

-   If handlers block, leadership rotation slows → **head-of-line blocking**.

-   Requires careful correctness around **promotion** to avoid multiple leaders or no leader.

-   If work is very uneven, may need **prioritization** or a separate worker pool.


## Implementation (Key Points)

-   Use a **lock + condition** to guard the “there is a leader” flag.

-   Order of operations on readiness: **promote follower first**, **then** handle events.

-   Keep handlers **non-blocking**; offload long work to another pool.

-   Batch handling: process all ready keys, but yield if it takes too long.

-   Integrate with **Reactor** (NIO `Selector`) cleanly—Leader–Follower orchestrates the threads; Reactor owns registrations.

-   Instrument: queue depths, time as leader vs. as follower, events/second, select wakeups.


---

## Sample Code (Java 17): NIO Echo Server with Leader–Follower Rotation

> What it shows:
>
> -   A fixed pool where **one thread at a time** blocks on a shared `Selector`.
>
> -   On wakeup, the leader **promotes** a follower and then handles accept/read events.
>
> -   Non-blocking sockets; simple line echo; back-pressure via OP\_WRITE.
>
> -   Minimal, production-leaning structure (no external libs).
>

```java
// File: LeaderFollowerDemo.java
// Compile: javac LeaderFollowerDemo.java
// Run:     java LeaderFollowerDemo 9090 4
// Try it:  nc localhost 9090  (type lines; they are echoed back)
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.ByteBuffer;
import java.nio.CharBuffer;
import java.nio.channels.*;
import java.nio.charset.Charset;
import java.time.Duration;
import java.util.Iterator;
import java.util.Set;
import java.util.concurrent.*;
import java.util.concurrent.locks.*;

public class LeaderFollowerDemo {

  public static void main(String[] args) throws Exception {
    int port = args.length > 0 ? Integer.parseInt(args[0]) : 9090;
    int threads = args.length > 1 ? Integer.parseInt(args[1]) : Math.max(2, Runtime.getRuntime().availableProcessors());

    var server = new EchoServer(port, threads);
    server.start();
    System.out.printf("Echo server on :%d with %d threads%n", port, threads);
  }

  /* ====================== Leader–Follower Group ======================= */
  static final class LeaderFollowerGroup implements AutoCloseable {
    private final ReentrantLock lock = new ReentrantLock();
    private final Condition noLeader = lock.newCondition();
    private boolean hasLeader = false;

    /** Become leader: exactly one thread may hold leadership at a time. */
    void acquireLeadership() throws InterruptedException {
      lock.lock();
      try {
        while (hasLeader) noLeader.await();
        hasLeader = true;
      } finally {
        lock.unlock();
      }
    }

    /** Promote a follower so someone else will block in select(). */
    void promoteFollower() {
      lock.lock();
      try {
        hasLeader = false;
        noLeader.signal(); // wake exactly one follower
      } finally {
        lock.unlock();
      }
    }

    @Override public void close() { /* nothing here; demo keeps it simple */ }
  }

  /* ====================== Echo Server (NIO + LF) ======================= */
  static final class EchoServer implements AutoCloseable {
    private final int port;
    private final int poolSize;
    private final Selector selector;
    private final ServerSocketChannel server;
    private final LeaderFollowerGroup group = new LeaderFollowerGroup();
    private final ExecutorService pool;
    private volatile boolean running = true;
    private static final Charset UTF8 = Charset.forName("UTF-8");

    EchoServer(int port, int poolSize) throws IOException {
      this.port = port;
      this.poolSize = poolSize;
      this.selector = Selector.open();
      this.server = ServerSocketChannel.open();
      server.configureBlocking(false);
      server.bind(new InetSocketAddress(port));
      server.register(selector, SelectionKey.OP_ACCEPT);
      this.pool = Executors.newFixedThreadPool(poolSize, r -> {
        Thread t = new Thread(r, "lf-worker");
        t.setDaemon(true);
        return t;
      });
    }

    void start() {
      for (int i = 0; i < poolSize; i++) {
        pool.submit(this::runWorker);
      }
    }

    private void runWorker() {
      try {
        while (running) {
          // ---- Become the leader ----
          group.acquireLeadership();
          int ready = 0;
          try {
            // Block waiting for events
            ready = selector.select(500); // timeout to observe shutdown
          } catch (IOException e) {
            e.printStackTrace();
          }

          // ---- Promote follower BEFORE handling ----
          group.promoteFollower();

          if (ready == 0) continue;
          // Handle all ready keys (batch)
          Set<SelectionKey> selected = selector.selectedKeys();
          Iterator<SelectionKey> it = selected.iterator();
          while (it.hasNext()) {
            SelectionKey key = it.next();
            it.remove();
            try {
              if (!key.isValid()) continue;
              if (key.isAcceptable()) onAccept(key);
              else if (key.isReadable()) onRead(key);
              else if (key.isWritable()) onWrite(key);
            } catch (CancelledKeyException ignored) {
            } catch (IOException io) {
              closeQuiet(key);
            }
          }
        }
      } catch (InterruptedException ie) {
        Thread.currentThread().interrupt();
      }
    }

    private void onAccept(SelectionKey key) throws IOException {
      ServerSocketChannel ssc = (ServerSocketChannel) key.channel();
      SocketChannel ch = ssc.accept();
      if (ch == null) return; // spurious
      ch.configureBlocking(false);
      // Attach a per-connection buffer pair
      ConnectionState state = new ConnectionState();
      ch.register(selector, SelectionKey.OP_READ, state);
    }

    private void onRead(SelectionKey key) throws IOException {
      SocketChannel ch = (SocketChannel) key.channel();
      ConnectionState st = (ConnectionState) key.attachment();

      int n = ch.read(st.readBuf);
      if (n == -1) {
        closeQuiet(key);
        return;
      }
      if (n == 0) return;

      st.readBuf.flip();
      // Very simple line echo: copy bytes; switch interest to WRITE
      while (st.readBuf.hasRemaining()) {
        if (!st.writeBuf.hasRemaining()) {
          // write buffer full; expand or drop. We'll expand a bit for demo
          ByteBuffer bigger = ByteBuffer.allocate(st.writeBuf.capacity() * 2);
          st.writeBuf.flip(); bigger.put(st.writeBuf); st.writeBuf = bigger;
        }
        st.writeBuf.put(st.readBuf.get());
      }
      st.readBuf.clear();
      key.interestOps(SelectionKey.OP_WRITE | SelectionKey.OP_READ); // try to drain
      selector.wakeup(); // nudge selector if another thread is the leader now
    }

    private void onWrite(SelectionKey key) throws IOException {
      SocketChannel ch = (SocketChannel) key.channel();
      ConnectionState st = (ConnectionState) key.attachment();
      st.writeBuf.flip();
      int wrote = ch.write(st.writeBuf);
      st.writeBuf.compact();
      if (wrote == 0) {
        // Socket not ready; keep OP_WRITE
        return;
      }
      if (st.writeBuf.position() == 0) {
        // nothing left to write; focus on reads again
        key.interestOps(SelectionKey.OP_READ);
      }
    }

    private static void closeQuiet(SelectionKey key) {
      try { key.channel().close(); } catch (IOException ignored) {}
      try { key.cancel(); } catch (Exception ignored) {}
    }

    @Override public void close() throws IOException {
      running = false;
      selector.wakeup();
      pool.shutdown();
      try { pool.awaitTermination(2, TimeUnit.SECONDS); } catch (InterruptedException ignored) { }
      server.close();
      selector.close();
    }

    /* Per-connection state: small read/write buffers */
    static final class ConnectionState {
      ByteBuffer readBuf = ByteBuffer.allocate(4096);
      ByteBuffer writeBuf = ByteBuffer.allocate(4096);
      @Override public String toString() {
        return "State[r=" + readBuf.position() + ", w=" + writeBuf.position() + "]";
      }
    }
  }
}
```

**How it works**

-   **Leader selection:** `acquireLeadership()` ensures exactly one thread calls `selector.select()`.

-   **Promotion order:** After `select()` returns, the leader calls `promoteFollower()` so another thread can immediately become leader. Then it handles the ready keys.

-   **Handlers:** `onAccept`, `onRead`, `onWrite` are short and non-blocking. Any slow/CPU-heavy work should be offloaded.


> Quick test: run the program, then `nc localhost 9090`, type lines; the server echoes them back. Open multiple `nc` clients to see concurrency.

---

## Known Uses

-   **ACE (ADAPTIVE Communication Environment):** Original pattern popularization (Schmidt et al.).

-   **High-performance network servers** on POSIX/Windows using `select/poll/epoll/kqueue` with thread pools.

-   **NIO frameworks** (custom reactors) and some proprietary trading/telecom servers.

-   **Web servers / proxies** (variants where accept is handled by leader; processing in the same thread).


## Related Patterns

-   **Reactor:** Leader–Follower often *implements* the dispatcher side of a Reactor with a thread pool.

-   **Proactor:** Completion-based I/O; different handoff model (OS completes; handlers run on pool).

-   **Thread Pool:** LF is a specialization with leadership rotation instead of queue submission.

-   **Half-Sync/Half-Async:** LF occupies the async boundary; heavy work may transition to the sync layer.

-   **Active Object / Actor Model:** If handlers are long-running or need isolation, hand off from LF to these models.


---

### Practical Tips

-   Keep event handlers **non-blocking** and short. If you must block, **hand off** to a separate executor.

-   **Promote before handle** to keep the system continuously listening.

-   Consider **batch limits** (e.g., handle up to N events, then rejoin followers) to ensure fair rotation.

-   Use **selector.wakeup()** when you change interest ops from a non-leader thread.

-   Monitor **select wakeups**, **handler latency**, **utilization per thread**, and **GC** to tune pool size and thresholds.

-   For multi-CPU NUMA boxes, pin groups of threads to cores/sockets to improve locality.
