# Pipe and Filter — Software Architecture Pattern

## Pattern Name and Classification

-   **Name:** Pipe and Filter
    
-   **Classification:** Dataflow / Streaming Processing / Structural & Behavioral
    

## Intent

Compose a computation as a **pipeline of independent filters** connected by **pipes**. Each filter transforms data and passes results downstream. Pipes **buffer** data and decouple filters so they can be **developed, tested, scaled, and executed independently** (often in parallel).

## Also Known As

-   Pipeline
    
-   Filter–Stream
    
-   Producer–Consumer Chain
    

## Motivation (Forces)

-   **Separation of concerns:** Break complex transformations into simple, reusable steps.
    
-   **Composability:** Reorder, replace, or insert filters without touching others.
    
-   **Throughput & parallelism:** Independent filters + buffered pipes enable concurrency and backpressure.
    
-   **Robustness:** Failures are localized; retries/restarts can be per-filter.  
    Tensions include **end-to-end latency vs. buffering**, **stateful vs. stateless processing**, **ordering guarantees**, and **error handling across filter boundaries**.
    

## Applicability

Use this pattern when:

-   You have a **linear or DAG-like sequence** of transformations (ETL, media transcoding, compilers).
    
-   Steps can be **isolated** with well-defined input/output contracts.
    
-   You want **streaming** or **batch** processing with potential parallelization.
    
-   You need **configurable** pipelines (add/remove filters at runtime).
    

Avoid or adapt when:

-   Strong **transactional consistency across many steps** is required (consider sagas or a workflow engine).
    
-   Steps have heavy **cross-dependencies** or require complex shared state (consider micro-batching, actors, or shared stores).
    

## Structure

-   **Filter:** A component with one or more input ports and output ports; transforms or routes data.
    
-   **Pipe:** A connector/buffer (queue, channel, stream) carrying typed messages between filters; may implement **backpressure**.
    
-   **Source / Sink:** Specialized filters that originate or terminate the stream.
    
-   **Supervisor (optional):** Builds pipelines, handles restarts, metrics, and error routing.
    

```scss
[Source] --pipe--> [Filter A] --pipe--> [Filter B] --pipe--> [Filter C] --pipe--> [Sink]
         (buffer)             (transform)           (enrich)             (persist/emit)
```

## Participants

-   **Source:** Reads from files, sockets, DB, or APIs; emits messages to the first pipe.
    
-   **Filter:** Stateless or stateful transformer; must be **side-effect aware** and ideally **idempotent**.
    
-   **Pipe:** Queue/stream/channel with bounded buffers; defines ordering and delivery guarantees.
    
-   **Sink:** Writes to external systems, files, UI, or final API.
    
-   **Orchestrator:** Constructs topology, sets capacities, concurrency, and error policies.
    

## Collaboration

1.  The **Source** pushes messages to a **Pipe**.
    
2.  Each **Filter** reads from its input pipe, transforms or splits/aggregates data, and writes results to its output pipe.
    
3.  **Backpressure** (bounded pipes) slows upstream producers when downstream lags.
    
4.  **Errors** can be handled per-filter (retry, dead-letter pipe) without stopping the whole pipeline.
    

## Consequences

**Benefits**

-   High **modularity** and **reusability** of filters.
    
-   **Parallelism & scalability** by running filters concurrently or sharding pipes.
    
-   **Replaceability** of steps without global rewrites.
    
-   Natural fit for **streaming** and **batch** alike.
    

**Liabilities**

-   End-to-end **latency** due to buffering.
    
-   **Debugging** across many steps requires good tracing and correlation IDs.
    
-   **Global transactions** are hard; need idempotency and compensation.
    
-   **Schema evolution** across filter boundaries needs governance.
    

## Implementation

### Design Guidelines

-   **Contracts:** Make each pipe **strongly typed**; keep payloads immutable.
    
-   **Buffering:** Use **bounded queues** to enforce backpressure.
    
-   **Lifecycle:** Define start/stop and a **poison pill / completion signal** to drain gracefully.
    
-   **Errors:** Decide per-filter policies (max retries, DLQ).
    
-   **Observability:** Include correlation IDs; measure throughput, queue depth, and latency per stage.
    
-   **Parallelism:** Scale by (a) duplicating a filter instance (competing consumers) or (b) partitioning by key.
    
-   **Stateful filters:** Keep local state minimal; checkpoint if needed.
    

### Variants

-   **Linear pipeline** (classic), **fan-out/fan-in** (split/merge), **tee** (side-channel), and **feedback loops** (careful with cycles/backpressure).
    
-   **Synchronous functional** (compose functions) vs. **asynchronous queued** (threads/actors/reactive streams).
    

---

## Sample Code (Java, asynchronous queued pipeline)

A small **word-count** pipeline:

-   `TextSource` → `NormalizeFilter` → `SplitFilter` → `StopwordFilter` → `CountFilter` → `Sink`
    
-   Uses `BlockingQueue` pipes and a **poison message** to signal completion.
    

```java
import java.util.*;
import java.util.concurrent.*;
import java.util.regex.Pattern;

/** Envelope to carry data or a poison (end-of-stream) marker through queues. */
class Envelope<T> {
  final T data; final boolean poison;
  private Envelope(T data, boolean poison){ this.data = data; this.poison = poison; }
  static <T> Envelope<T> data(T d){ return new Envelope<>(d, false); }
  static <T> Envelope<T> poison(){ return new Envelope<>(null, true); }
}

/** Base class for filters with one input and one output queue. */
abstract class Stage<I,O> implements Runnable {
  protected final BlockingQueue<Envelope<I>> in;
  protected final BlockingQueue<Envelope<O>> out;
  Stage(BlockingQueue<Envelope<I>> in, BlockingQueue<Envelope<O>> out){ this.in = in; this.out = out; }
  protected abstract void onData(I item) throws Exception;
  protected void onEnd() throws Exception { if (out != null) out.put(Envelope.poison()); }
  @Override public void run() {
    try {
      while (true) {
        Envelope<I> env = in.take();
        if (env.poison) { onEnd(); break; }
        onData(env.data);
      }
    } catch (InterruptedException ie) {
      Thread.currentThread().interrupt();
    } catch (Exception e) {
      e.printStackTrace();
    }
  }
}

/** Source: emits text lines into the first pipe. */
class TextSource implements Runnable {
  private final List<String> lines;
  private final BlockingQueue<Envelope<String>> out;
  TextSource(List<String> lines, BlockingQueue<Envelope<String>> out){ this.lines = lines; this.out = out; }
  @Override public void run() {
    try {
      for (String line : lines) out.put(Envelope.data(line));
      out.put(Envelope.poison());
    } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
  }
}

/** Filter: normalize (lowercase, strip punctuation, collapse spaces). */
class NormalizeFilter extends Stage<String,String> {
  private static final Pattern NON_ALNUM = Pattern.compile("[^\\p{L}\\p{Nd}]+");
  NormalizeFilter(BlockingQueue<Envelope<String>> in, BlockingQueue<Envelope<String>> out){ super(in,out); }
  @Override protected void onData(String s) throws Exception {
    String normalized = NON_ALNUM.matcher(s.toLowerCase(Locale.ROOT)).replaceAll(" ").trim();
    if (!normalized.isEmpty()) out.put(Envelope.data(normalized));
  }
}

/** Filter: split lines into words (fan-out: 1 input → N outputs). */
class SplitFilter extends Stage<String,String> {
  SplitFilter(BlockingQueue<Envelope<String>> in, BlockingQueue<Envelope<String>> out){ super(in,out); }
  @Override protected void onData(String line) throws Exception {
    for (String token : line.split("\\s+")) {
      if (!token.isBlank()) out.put(Envelope.data(token));
    }
  }
}

/** Filter: drop common stopwords. */
class StopwordFilter extends Stage<String,String> {
  private final Set<String> stop = Set.of("a","an","and","the","of","to","in","on","for","with","is","are","be","or","as","at","by");
  StopwordFilter(BlockingQueue<Envelope<String>> in, BlockingQueue<Envelope<String>> out){ super(in,out); }
  @Override protected void onData(String word) throws Exception {
    if (!stop.contains(word)) out.put(Envelope.data(word));
  }
}

/** Filter: aggregate counts; emits a single Map on end-of-stream. */
class CountFilter extends Stage<String, Map<String,Integer>> {
  private final Map<String,Integer> counts = new HashMap<>();
  CountFilter(BlockingQueue<Envelope<String>> in, BlockingQueue<Envelope<Map<String,Integer>>> out){ super(in,out); }
  @Override protected void onData(String word) {
    counts.merge(word, 1, Integer::sum);
  }
  @Override protected void onEnd() throws Exception {
    out.put(Envelope.data(Collections.unmodifiableMap(counts)));
    super.onEnd(); // send poison
  }
}

/** Sink: prints the top-N words and terminates. */
class TopNSink implements Runnable {
  private final BlockingQueue<Envelope<Map<String,Integer>>> in;
  private final int topN;
  TopNSink(BlockingQueue<Envelope<Map<String,Integer>>> in, int topN){ this.in = in; this.topN = topN; }
  @Override public void run() {
    try {
      while (true) {
        Envelope<Map<String,Integer>> env = in.take();
        if (env.poison) break;
        var map = env.data;
        var top = map.entrySet().stream()
            .sorted((a,b) -> Integer.compare(b.getValue(), a.getValue()))
            .limit(topN)
            .toList();
        System.out.println("Top " + topN + " words:");
        for (var e : top) System.out.println("  " + e.getKey() + " = " + e.getValue());
      }
    } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
  }
}

/** Demo: wire the pipeline and run it. */
public class PipeAndFilterDemo {
  public static void main(String[] args) throws Exception {
    // Pipes (bounded queues for backpressure)
    var q1 = new ArrayBlockingQueue<Envelope<String>>(128);
    var q2 = new ArrayBlockingQueue<Envelope<String>>(128);
    var q3 = new ArrayBlockingQueue<Envelope<String>>(128);
    var q4 = new ArrayBlockingQueue<Envelope<String>>(128);
    var q5 = new ArrayBlockingQueue<Envelope<Map<String,Integer>>>(16);

    // Stages
    var source   = new TextSource(List.of(
        "The quick brown fox jumps over the lazy dog.",
        "Pipes and filters encourage composition and reuse.",
        "Filters can run in parallel; pipes add buffering."
    ), q1);
    var normalize = new NormalizeFilter(q1, q2);
    var split     = new SplitFilter(q2, q3);
    var stop      = new StopwordFilter(q3, q4);
    var count     = new CountFilter(q4, q5);
    var sink      = new TopNSink(q5, 5);

    // Run concurrently
    var threads = List.of(
        new Thread(source, "src"),
        new Thread(normalize, "normalize"),
        new Thread(split, "split"),
        new Thread(stop, "stop"),
        new Thread(count, "count"),
        new Thread(sink, "sink")
    );
    threads.forEach(Thread::start);
    for (var t : threads) t.join();
  }
}
```

**Highlights**

-   Filters are **independent** runnables; pipes are **bounded** queues for backpressure.
    
-   A **poison envelope** cleanly shuts the pipeline.
    
-   Fan-out (split) and stateful aggregation (count) are demonstrated.
    

> Productionize with: multiple instances per filter (competing consumers), DLQ for failures, metrics on queue depth and stage latency, and reactive streams (Project Reactor/Mutiny/Flow) for non-blocking pipes.

## Known Uses

-   **Unix pipelines:** `cat | grep | awk | sort | uniq -c`.
    
-   **Compilers:** lexing → parsing → semantic analysis → optimization → codegen.
    
-   **ETL & data pipelines:** ingest → cleanse → transform → enrich → load.
    
-   **Media processing:** decode → filter → transcode → package.
    
-   **Log processing & SIEM:** parse → classify → correlate → alert.
    
-   **IoT streams:** normalize → denoise → detect → act.
    

## Related Patterns

-   **Batch Processing / Map–Reduce:** specialized large-scale pipelines with shuffle phases.
    
-   **Event-Driven Architecture:** pipes implemented by brokers/streams (Kafka/Pulsar).
    
-   **Mediator / Broker:** central coordination vs. linear composition.
    
-   **Actor Model:** filters as actors with mailboxes.
    
-   **Reactive Streams:** backpressured, non-blocking pipe abstraction.
    

---

## Implementation Tips

-   Make filters **pure** when possible; keep side effects in sinks/adapters.
    
-   Prefer **immutable messages**; attach **metadata** (trace IDs) for observability.
    
-   Keep pipes **bounded** and tune sizes empirically; expose depth metrics.
    
-   Ensure filters are **idempotent** to allow retries.
    
-   For fan-in/fan-out, define clear **partitioning keys** (ordering per key).
    
-   Version your **message schemas**; treat them as contracts between filters.

