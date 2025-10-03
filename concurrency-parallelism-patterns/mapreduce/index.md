
# Concurrency / Parallelism Pattern — Map-Reduce

## Pattern Name and Classification

-   **Name:** Map-Reduce

-   **Classification:** Data-parallel pattern (bulk synchronous, embarrassingly parallel map + keyed aggregation)


## Intent

Process very large datasets by:

1.  **Mapping** input records independently into intermediate **(key, value)** pairs, and

2.  **Reducing** all values that share the same key to a single (usually smaller) result.  
    The runtime parallelizes `map`, groups/shuffles by key, and executes `reduce` per key (often in parallel), optionally with **combiners** to pre-aggregate near the source.


## Also Known As

-   Keyed Aggregation

-   Group-By followed by Reduce

-   (In streaming) Keyed Windowed Aggregation


## Motivation (Forces)

-   **Throughput & scale:** Split massive input across workers; maps are independent → easy to parallelize.

-   **Data locality:** Move compute to data; only shuffle compacted `(k,v)` pairs.

-   **Fault tolerance:** Re-execute deterministic tasks on failure; reducers rehydrate from shuffled data.

-   **Load balance:** Many small tasks smooth skew; but keys can be **hot** → need good partitioning/combining.

-   **Simplicity:** Developers write two pure functions; the framework handles parallelism, scheduling, and recovery.


## Applicability

Use Map-Reduce when:

-   Work can be expressed as **map → group by key → reduce** (counts, sums, joins, histograms, inverted indexes, ETL).

-   Input is **large** and can be partitioned; mappers don’t depend on each other.

-   Aggregations are **associative/commutative** (or can be made so), enabling parallel reduction and combiners.


Avoid/Adapt when:

-   You need **iterative, low-latency** algorithms (e.g., graph ML); prefer dataflow engines with caching (Spark) or streaming.

-   Results require **global ordering** beyond per-key reductions.

-   Heavy **skew** (few hot keys) dominates; consider secondary partitioning or two-phase reduce.


## Structure

```css
[Input splits] -->  map(record) -> [(k,v)...]  --shuffle/partition-->  {k -> [v...]}
                                                                           │
                                                                          reduce(k, [v...]) -> [(k, out)...]
                                                                                   │
                                                                                 [Output]
```

-   **Combiner (optional):** run after map, before shuffle: `combine(k, [v...]) -> (k, v')` to shrink network I/O.

-   **Partitioner:** routes each `(k, v)` to a reducer shard, e.g., `hash(k) % R`.


## Participants

-   **Mapper:** Pure function `record -> 0..n (k,v)` pairs.

-   **Combiner (optional):** Local pre-reducer to compact mapper output.

-   **Partitioner:** Key → reducer shard mapping.

-   **Shuffle/Sort:** Groups and orders pairs by key per reducer.

-   **Reducer:** Processes all values for one key to an output value (or values).

-   **Coordinator / Job Tracker:** Schedules tasks, handles failures (framework responsibility).


## Collaboration

1.  Input is split; **mappers** run in parallel on different splits.

2.  Each mapper emits `(k,v)` pairs; optional **combiner** compacts locally.

3.  **Shuffle** partitions by key to reducers; within each partition, pairs are grouped (often sorted).

4.  **Reducers** run per key (or per key-group), outputting final results.


## Consequences

**Benefits**

-   Scales horizontally; simple programming model.

-   Deterministic recomputation enables robust fault tolerance.

-   Efficient network usage through combiners and locality.


**Liabilities / Trade-offs**

-   One or more **global shuffle** steps; network/IO heavy.

-   **Skew** can create stragglers (hot keys).

-   Batch-oriented; latency is at least a shuffle.

-   Restricted expressiveness (two-stage thinking—work around with chaining).


## Implementation (Key Points)

-   Keep **map** side-effect free and stateless; serialize only needed data.

-   Ensure **reduce** is associative/commutative; if not, enforce ordering or use two-stage reductions.

-   Add a **combiner** when possible (same signature as reducer) to reduce shuffle volume.

-   Design a **partitioner** that spreads hot keys; consider salting or two-phase reduce for skew.

-   Persist intermediate data if you need recovery; in a single-JVM demo, memory suffices.

-   Monitor: mapper/reducer times, spill counts, shuffle bytes, skew (p95/p99 key group sizes).


---

## Sample Code (Java 17): Minimal In-JVM Map-Reduce Engine + Word Count

> Educational, single-process demo that:
>
> -   Runs mappers in parallel over inputs
>
> -   Optionally runs a **combiner** on each mapper shard
>
> -   **Shuffles** by key and runs reducers in parallel
>
> -   Shows **word count** and a **top-N** variant
>

```java
// File: MiniMapReduce.java
// Compile: javac MiniMapReduce.java
// Run:     java MiniMapReduce

import java.util.*;
import java.util.concurrent.*;
import java.util.function.*;
import java.util.stream.Collectors;

/* --------- Core abstractions --------- */
@FunctionalInterface
interface Mapper<I, K, V> {
    void map(I record, Emitter<K, V> out);
}
@FunctionalInterface
interface Reducer<K, V, R> {
    void reduce(K key, Iterable<V> values, Emitter<K, R> out);
}
/** Optional: local pre-aggregation on each mapper's output. Usually same signature as Reducer. */
@FunctionalInterface
interface Combiner<K, V> {
    V combine(K key, Iterable<V> values); // returns a single compacted V per key
}
@FunctionalInterface
interface Partitioner<K> {
    int partition(K key, int numReducers);
}
@FunctionalInterface
interface Emitter<K, V> {
    void emit(K key, V value);
}

/* --------- Mini MapReduce engine --------- */
final class MapReduceEngine {
    private final ExecutorService mapPool;
    private final ExecutorService reducePool;

    MapReduceEngine(int mapParallelism, int reduceParallelism) {
        this.mapPool = Executors.newFixedThreadPool(mapParallelism);
        this.reducePool = Executors.newFixedThreadPool(reduceParallelism);
    }

    public <I,K,V,R> List<Map.Entry<K,R>> run(
            List<I> input,
            Mapper<I,K,V> mapper,
            Reducer<K,V,R> reducer,
            Combiner<K,V> combiner,               // nullable
            Partitioner<K> partitioner,           // nullable -> hash partitioner
            int numReducers) {

        Objects.requireNonNull(mapper);
        Objects.requireNonNull(reducer);
        if (partitioner == null) {
            partitioner = (k, n) -> (k == null ? 0 : Math.floorMod(k.hashCode(), n));
        }
        numReducers = Math.max(1, numReducers);

        try {
            // ---- MAP phase (parallel) ----
            // Each mapper shard collects outputs in a local map (per key list).
            List<Future<Map<Integer, Map<K, List<V>>>>> mapFutures = new ArrayList<>();
            int chunk = Math.max(1, input.size() / Math.max(1, ((ThreadPoolExecutor)mapPool).getMaximumPoolSize()));
            for (int start = 0; start < input.size(); start += chunk) {
                int from = start, to = Math.min(input.size(), start + chunk);
                mapFutures.add(mapPool.submit(() -> {
                    Map<Integer, Map<K, List<V>>> byPartition = new HashMap<>();
                    for (int i = from; i < to; i++) {
                        I rec = input.get(i);
                        Map<K, List<V>> local = new HashMap<>();
                        // collect mapper outputs for this record
                        mapper.map(rec, (k, v) -> local.computeIfAbsent(k, __ -> new ArrayList<>()).add(v));
                        // apply combiner locally per record (or per chunk) to reduce volume
                        if (combiner != null) {
                            Map<K, List<V>> combined = new HashMap<>();
                            for (var e : local.entrySet()) {
                                V c = combiner.combine(e.getKey(), e.getValue());
                                combined.put(e.getKey(), List.of(c));
                            }
                            local = combined;
                        }
                        // partition to reducers
                        for (var e : local.entrySet()) {
                            int p = partitioner.partition(e.getKey(), numReducers);
                            byPartition.computeIfAbsent(p, __ -> new HashMap<>())
                                       .computeIfAbsent(e.getKey(), __ -> new ArrayList<>())
                                       .addAll(e.getValue());
                        }
                    }
                    return byPartition;
                }));
            }

            // ---- SHUFFLE: merge mapper outputs per reducer partition ----
            @SuppressWarnings("unchecked")
            Map<K, List<V>>[] partitions = new Map[numReducers];
            for (int i = 0; i < numReducers; i++) partitions[i] = new HashMap<>();

            for (Future<Map<Integer, Map<K, List<V>>>> f : mapFutures) {
                Map<Integer, Map<K, List<V>>> part = f.get();
                for (var pe : part.entrySet()) {
                    int p = pe.getKey();
                    Map<K, List<V>> target = partitions[p];
                    for (var e : pe.getValue().entrySet()) {
                        target.computeIfAbsent(e.getKey(), __ -> new ArrayList<>()).addAll(e.getValue());
                    }
                }
            }

            // ---- REDUCE phase (parallel across partitions and keys) ----
            List<Future<List<Map.Entry<K,R>>>> redFutures = new ArrayList<>();
            for (int p = 0; p < numReducers; p++) {
                final Map<K, List<V>> bucket = partitions[p];
                redFutures.add(reducePool.submit(() -> {
                    List<Map.Entry<K,R>> out = new ArrayList<>(bucket.size());
                    Emitter<K,R> sink = (k, r) -> out.add(Map.entry(k, r));
                    for (var e : bucket.entrySet()) {
                        reducer.reduce(e.getKey(), e.getValue(), sink);
                    }
                    return out;
                }));
            }

            // Gather results
            List<Map.Entry<K,R>> results = new ArrayList<>();
            for (Future<List<Map.Entry<K,R>>> f : redFutures) results.addAll(f.get());
            return results;

        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
            throw new RuntimeException(ie);
        } catch (ExecutionException ee) {
            throw new RuntimeException(ee.getCause());
        }
    }

    public void shutdown() {
        mapPool.shutdown();
        reducePool.shutdown();
    }
}

/* --------- Example job: Word Count + Top-N --------- */
public class MiniMapReduce {
    public static void main(String[] args) {
        List<String> input = List.of(
            "To be or not to be that is the question",
            "Whether tis nobler in the mind to suffer",
            "The slings and arrows of outrageous fortune",
            "Or to take arms against a sea of troubles"
        );

        MapReduceEngine engine = new MapReduceEngine(
            Math.max(2, Runtime.getRuntime().availableProcessors()/2),
            Math.max(2, Runtime.getRuntime().availableProcessors()/2)
        );

        // --- Word Count ---
        Mapper<String, String, Integer> mapper = (line, out) -> {
            for (String raw : line.toLowerCase().split("\\W+")) {
                if (!raw.isBlank()) out.emit(raw, 1);
            }
        };

        // Combiner: local sum to shrink shuffle volume
        Combiner<String, Integer> combiner = (k, vals) -> {
            int s = 0; for (int v : vals) s += v; return s;
        };

        // Reducer: global sum
        Reducer<String, Integer, Integer> reducer = (key, values, out) -> {
            int s = 0; for (int v : values) s += v; out.emit(key, s);
        };

        var results = engine.run(
            input, mapper, reducer, combiner,
            (k, n) -> Math.floorMod(k.hashCode(), n),  // partitioner
            4                                          // reducers
        );

        // Pretty print sorted by count desc
        var sorted = results.stream()
            .sorted(Comparator.<Map.Entry<String,Integer>>comparingInt(Map.Entry::getValue).reversed())
            .collect(Collectors.toList());

        System.out.println("Word counts:");
        for (var e : sorted) {
            System.out.printf("%-12s %d%n", e.getKey(), e.getValue());
        }

        // --- Top-N words using another reduce (chained job) ---
        int N = 5;
        List<Map.Entry<String,Integer>> topN = sorted.stream().limit(N).toList();
        System.out.println("\nTop " + N + ": " + topN);

        engine.shutdown();
    }
}
```

**What the demo shows**

-   Parallel **map** over input lines and per-mapper **combining** (local sum) to reduce shuffle size.

-   **Shuffle/partition** of `(word, count)` pairs to reducer buckets.

-   Parallel **reduce** per bucket to produce global counts.

-   A tiny, understandable backbone you can extend with spill-to-disk, sort, or secondary partitioning.


---

## Known Uses

-   **Google MapReduce** (original paper): large-scale batch processing.

-   **Apache Hadoop**: HDFS + MapReduce (YARN) classic implementation.

-   **Apache Spark**: Wide transformations (`map`, `reduceByKey`, `aggregateByKey`) generalize Map-Reduce with DAG scheduling and caching.

-   **Streaming engines**: Flink, Kafka Streams—“map” + keyed/windowed reduce for low-latency streams (continuous Map-Reduce).

-   **Index builders / ETL pipelines**: inverted indexes, click log aggregation, metrics rollups.


## Related Patterns

-   **Fork–Join:** In-memory divide-and-conquer; Map-Reduce adds **keyed shuffle**.

-   **Bulk Synchronous Processing (BSP):** Map-Reduce fits BSP supersteps (map + barrier + reduce).

-   **Pipeline:** Chain multiple Map-Reduce jobs (map→reduce→map…).

-   **Combiner / Partial Aggregation:** Optimization pattern inside Map-Reduce.

-   **Shuffle & Sort / Group-By:** The grouping phase between map and reduce.

-   **Actor Model:** Mappers/Reducers as actors, shuffle as message routing by key.


---

### Practical Tips

-   Make **map** & **reduce** **deterministic and side-effect free** for easy retries.

-   Use **combiners** aggressively for additive/associative operations (count, sum, min/max).

-   Handle **skew**: detect hot keys; salt keys and do a second reduce, or use a custom partitioner.

-   Keep emitted pairs **compact** (efficient encoding).

-   For iterative algorithms, prefer an engine with **caching** (Spark) to avoid repeated shuffles.

-   Measure the **shuffle**: it’s usually the bottleneck—optimize partitions and compression.
