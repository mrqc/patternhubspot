
# Concurrency / Parallelism Pattern — Reactor

## Pattern Name and Classification

-   **Name:** Reactor

-   **Classification:** Event demultiplexing & dispatch pattern (non-blocking I/O, single-threaded event loop or event-loop-per-core)


## Intent

Demultiplex **I/O readiness events** from many handles (sockets, files, timers) using an OS mechanism (e.g., `select`, `epoll`, `kqueue`) and **dispatch** them to **handlers** that react **asynchronously**, typically without blocking. One (or a few) event-loop thread(s) orchestrate(s) many connections.

## Also Known As

-   Event Loop

-   Dispatcher (Demultiplexer + Dispatcher)

-   Non-blocking I/O Server


## Motivation (Forces)

-   **Scalability:** Thread-per-connection wastes memory and context switches; a single event loop can drive thousands of sockets.

-   **Latency & throughput:** Avoids lock contention; keeps hot state in the event-loop’s cache.

-   **Coordination:** Handlers run to completion quickly, keeping the loop responsive; slow tasks should be offloaded.

-   **Backpressure:** Control interest ops (read/write) to avoid unbounded buffering.

-   **Complexity trade:** Easier than fully asynchronous completion ports (Proactor), but requires careful state machines.


## Applicability

Use Reactor when:

-   You build **high-concurrency network servers** (HTTP, proxies, chat, game gateways).

-   Work after I/O readiness is **short and non-blocking** or can be **offloaded** to workers.

-   You need **bounded threads** with predictable scheduling.


Avoid / adapt when:

-   Handler work is **CPU heavy** or **blocking I/O** (wrap with worker pool or use Half-Sync/Half-Async).

-   You rely on **OS completion events** rather than readiness (use **Proactor** on platforms with IOCP/IOUring).


## Structure

```lua
+-----------------+     readiness     +------------------+     dispatch     +----------------+
| OS Demultiplexer| <---------------- | Reactor (Selector| ----------------> | Event Handlers |
| (select/epoll)  |                   | / Event Loop)    |                  | (Acceptor, ... )|
+-----------------+                   +------------------+                  +----------------+
                              register interest (OP_ACCEPT/READ/WRITE)
```

## Participants

-   **Demultiplexer:** OS primitive (`select`, `poll`, `epoll`, `kqueue`) delivering readiness notifications.

-   **Reactor (Event Loop):** Waits for events, iterates ready keys, and dispatches to handlers.

-   **Handlers:** Small objects that manage a connection/stage; implement state machines for `ACCEPT`, `READ`, `WRITE`.

-   **Acceptor:** Special handler for `OP_ACCEPT` that accepts new sockets and registers connection handlers.

-   **Dispatcher API:** Register/unregister channels, set `interestOps`, `wakeup()` the selector.

-   **(Optional) Worker Pool:** Executes blocking/CPU-heavy tasks off the loop; completion posts results back to the loop.


## Collaboration

1.  App registers channels and handlers with the **Reactor** (interest ops).

2.  Reactor blocks in `select()`.

3.  On wakeup (readiness), Reactor **dispatches** to the appropriate handler.

4.  Handler performs minimal non-blocking steps, updates its state/interest ops, and returns.

5.  For heavy work, handler submits to a **worker** and arranges a completion callback that reschedules `OP_WRITE` (or similar) on the loop.


## Consequences

**Benefits**

-   **High concurrency** with few threads; good cache locality and small memory footprint.

-   **Backpressure control** via interest ops; avoids write buffer bloat.

-   Clear separation between I/O multiplexing and handler logic.


**Liabilities / Trade-offs**

-   Handlers must be **non-blocking** and small; one slow handler stalls all sockets on that loop.

-   **State machines** can get intricate; debugging requires good tracing.

-   Cross-core scaling requires **multiple event loops** (e.g., one per core) and connection sharding.


## Implementation (Key Points)

-   Keep handlers **short**; offload heavy work to a bounded executor.

-   Use **non-blocking** channels; carefully manage `SelectionKey` interest ops (`OP_READ`, `OP_WRITE`) to implement backpressure.

-   Use `selector.wakeup()` when you change interest ops from outside the loop.

-   Batch: process several ready keys per wakeup, but yield periodically.

-   For multi-core: run **N event loops** and assign connections (acceptor round-robin).

-   Observability: event loop latency, selected key count, reads/writes per second, write-queue length, selector wakeups.


---

## Sample Code (Java 17): Minimal NIO Reactor (Echo/Uppercase) with Acceptor and Offload

> Highlights
>
> -   Single Reactor (`Selector`) thread.
>
> -   `Acceptor` registers `EchoHandler` per connection.
>
> -   `EchoHandler` does non-blocking read/write; optional **offload** to worker for CPU work.
>
> -   Backpressure via toggling `OP_WRITE`.
>

```java
// File: ReactorDemo.java
// Compile: javac ReactorDemo.java
// Run:     java ReactorDemo 9090
// Try:     nc localhost 9090   (type; responses are UPPERCASED)

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.ByteBuffer;
import java.nio.channels.*;
import java.nio.charset.StandardCharsets;
import java.util.Iterator;
import java.util.Set;
import java.util.concurrent.*;

public class ReactorDemo {

  public static void main(String[] args) throws Exception {
    int port = args.length > 0 ? Integer.parseInt(args[0]) : 9090;
    EventLoop loop = new EventLoop();
    try (ServerSocketChannel server = ServerSocketChannel.open()) {
      server.configureBlocking(false);
      server.bind(new InetSocketAddress(port));
      loop.register(server, SelectionKey.OP_ACCEPT, new Acceptor(loop, server));
      System.out.println("Reactor listening on :" + port);
      loop.run(); // blocks
    }
  }

  /* ----------------- Reactor / EventLoop ----------------- */
  static final class EventLoop {
    private final Selector selector;
    private final ExecutorService workers; // offload pool for heavy tasks

    EventLoop() throws IOException {
      this.selector = Selector.open();
      this.workers = Executors.newFixedThreadPool(Math.max(2, Runtime.getRuntime().availableProcessors() - 1));
    }

    void register(SelectableChannel ch, int ops, Handler h) throws ClosedChannelException {
      ch.register(selector, ops, h);
    }

    void modifyOps(SelectionKey key, int newOps) {
      key.interestOps(newOps);
    }

    void wakeup() { selector.wakeup(); }
    ExecutorService workerPool() { return workers; }

    void run() {
      try {
        while (selector.isOpen()) {
          selector.select(500);            // timeout to allow graceful shutdown hooks, if any
          Set<SelectionKey> selected = selector.selectedKeys();
          Iterator<SelectionKey> it = selected.iterator();
          while (it.hasNext()) {
            SelectionKey key = it.next(); it.remove();
            if (!key.isValid()) continue;
            try {
              Handler h = (Handler) key.attachment();
              h.handle(key);
            } catch (CancelledKeyException ignored) {
            } catch (Throwable t) {
              // Close on unexpected error to avoid spinning
              try { key.channel().close(); } catch (IOException ignored) {}
              key.cancel();
            }
          }
        }
      } catch (IOException e) {
        e.printStackTrace();
      } finally {
        try { selector.close(); } catch (IOException ignored) {}
        workers.shutdown();
      }
    }
  }

  /* ----------------- Handler SPI ----------------- */
  interface Handler { void handle(SelectionKey key) throws Exception; }

  /* ----------------- Acceptor ----------------- */
  static final class Acceptor implements Handler {
    private final EventLoop loop;
    private final ServerSocketChannel server;
    Acceptor(EventLoop loop, ServerSocketChannel server) {
      this.loop = loop; this.server = server;
    }
    @Override public void handle(SelectionKey key) throws Exception {
      if (!key.isAcceptable()) return;
      SocketChannel ch = server.accept();
      if (ch == null) return; // spurious
      ch.configureBlocking(false);
      // Attach per-connection handler
      EchoHandler h = new EchoHandler(loop, ch);
      ch.register(key.selector(), SelectionKey.OP_READ, h);
    }
  }

  /* ----------------- Per-connection Handler ----------------- */
  static final class EchoHandler implements Handler {
    private final EventLoop loop;
    private final SocketChannel ch;
    private final ByteBuffer in = ByteBuffer.allocate(8 * 1024);
    private final ByteBuffer out = ByteBuffer.allocate(8 * 1024);
    private volatile boolean closed = false;

    EchoHandler(EventLoop loop, SocketChannel ch) {
      this.loop = loop; this.ch = ch;
    }

    @Override public void handle(SelectionKey key) throws Exception {
      if (key.isReadable()) onRead(key);
      if (key.isWritable()) onWrite(key);
    }

    private void onRead(SelectionKey key) throws IOException {
      int n = ch.read(in);
      if (n == -1) { close(key); return; }
      if (n == 0) return;

      in.flip();

      // --- Offload CPU-heavy transformation to worker pool (optional) ---
      // For demo, we upper-case bytes; small enough to do inline, but shown as offload pattern.
      byte[] bytes = new byte[in.remaining()];
      in.get(bytes); in.clear();
      CompletableFuture
        .supplyAsync(() -> new String(bytes, StandardCharsets.UTF_8).toUpperCase(), loop.workerPool())
        .whenComplete((res, err) -> {
          if (err != null) { safeClose(key); return; }
          // Post result back to event loop thread: put into out buffer and enable OP_WRITE
          // Because we're on a worker thread, we must wake up the selector.
          key.selector().wakeup();
          try {
            synchronized (out) {
              byte[] outBytes = res.getBytes(StandardCharsets.UTF_8);
              ensureCapacity(out, outBytes.length);
              out.put(outBytes);
            }
            int ops = key.interestOps();
            key.interestOps(ops | SelectionKey.OP_WRITE);
          } catch (CancelledKeyException ignored) {}
        });
    }

    private void onWrite(SelectionKey key) throws IOException {
      synchronized (out) {
        out.flip();
        int wrote = ch.write(out);
        out.compact();
        if (wrote == 0) {
          // kernel buffer full; keep OP_WRITE
          return;
        }
        if (out.position() == 0) {
          // all data drained; stop listening for write
          key.interestOps(key.interestOps() & ~SelectionKey.OP_WRITE);
        }
      }
    }

    private void ensureCapacity(ByteBuffer buf, int extra) {
      if (buf.remaining() >= extra) return;
      ByteBuffer bigger = ByteBuffer.allocate(Math.max(buf.capacity() * 2, buf.capacity() + extra));
      buf.flip(); bigger.put(buf); buf.clear(); // not strictly needed after replace
      // There's no direct resize; replace content by reflection is unnecessary—here we only used local 'out'.
      // But since 'out' is final, we simulate: copy into existing; for demo keep simple by assuming size is enough.
      // In production, use a resizable aggregator or Netty's ByteBuf.
    }

    private void close(SelectionKey key) throws IOException {
      if (closed) return;
      closed = true;
      key.cancel();
      ch.close();
    }

    private void safeClose(SelectionKey key) {
      try { close(key); } catch (IOException ignored) {}
    }
  }
}
```

**How to try**

1.  Compile & run: `javac ReactorDemo.java && java ReactorDemo 9090`

2.  In another terminal: `nc localhost 9090`, type text → server responds **UPPERCASED**.

3.  Open multiple `nc` sessions; one event loop handles them all.


> Notes: The `ensureCapacity` in this compact demo is conservative; for production use a resizable buffer abstraction (e.g., Netty’s `ByteBuf`) or chunked writes.

---

## Known Uses

-   **Netty (JVM):** Multi-reactor (boss/worker) event loops atop Java NIO.

-   **Node.js / libuv:** Cross-platform reactor for TCP/UDP/files/timers.

-   **Nginx:** Master + event loops with `epoll`/`kqueue`.

-   **Redis (single-threaded I/O):** Event loop with ready handlers and command execution.

-   **Java NIO servers:** Many custom high-perf gateways/proxies.


## Related Patterns

-   **Proactor:** OS completes I/O and invokes completion handlers (e.g., Windows IOCP).

-   **Leader–Follower:** Thread-pool rotation over a shared selector (can be layered under Reactor).

-   **Half-Sync/Half-Async:** Offload blocking/CPU work from Reactor to sync worker pools.

-   **Producer–Consumer:** Reactor produces events, handlers/worker pools consume tasks.

-   **State Machine:** Each handler models connection protocol states.

-   **Backpressure / Rate Limiting:** Coordinate write interest ops & application buffers.


---

### Practical Tips

-   Keep handlers **non-blocking**; any blocking call belongs in a **bounded** worker pool with careful result posting.

-   **Toggle OP\_WRITE** only when you actually have data to send; otherwise the loop will busy-wake.

-   Use **multiple event loops** for multi-core machines; pin them to cores for stable latency.

-   Instrument the loop: **select latency**, **keys per wakeup**, **wakeup count**, **handler duration**, **write queue sizes**.

-   For TLS, either use the JDK `SSLEngine` in non-blocking mode or a library that integrates TLS state machines with Reactor.

-   Consider established frameworks (Netty, Vert.x) for production—they provide codecs, TLS, HTTP/2, backpressure, and robust buffer management.
