# Blackboard Architecture — Software Architecture Pattern

## Pattern Name and Classification

-   **Name:** Blackboard Architecture
    
-   **Classification:** AI/Knowledge-Intensive Systems / Integrative Architecture / Behavioral & Structural
    

## Intent

Coordinate **multiple specialized, independent problem-solvers** (knowledge sources) that incrementally contribute to a **shared, structured data store** (the blackboard) while an **arbiter/controller** orchestrates when and how they fire—until the solution emerges or a stopping criterion is met.

## Also Known As

-   Shared Working Memory
    
-   Opportunistic Problem Solving
    
-   Hypothesis Blackboard
    

## Motivation (Forces)

Complex inference or perception tasks (speech recognition, image understanding, parsing, cybersecurity triage) rarely have a single best algorithm:

-   **Heterogeneous expertise:** Different algorithms shine on different subproblems.
    
-   **Uncertain, partial information:** Early results are noisy; confidence evolves.
    
-   **Non-linear progress:** Useful contributions can arise in any order.
    
-   **Scalability & parallelism:** Many KSs (knowledge sources) should run concurrently without tight coupling.
    
-   **Opportunism vs. control:** Allow KSs to trigger on relevant changes but avoid thrashing and starvation.  
    The blackboard reconciles these by centralizing **state and hypotheses**, letting **specialists contribute** when relevant changes occur, guided by a **controller policy**.
    

## Applicability

Use when:

-   The problem is **ill-structured** with incomplete or evolving data.
    
-   You want to **combine diverse heuristics/ML models/rules** without hardwiring their sequence.
    
-   Intermediate results should be **shared and refined** by peers.
    
-   You need **anytime behavior** (return best-so-far) and **explainability** via traceable hypotheses.
    

## Structure

-   **Blackboard:** Central, structured repository of *facts, hypotheses, annotations*, with versioning and events.
    
-   **Knowledge Sources (KS):** Independent modules; each declares *preconditions*, consumes data from the blackboard, and posts *contributions* (facts/hypotheses with confidence).
    
-   **Controller / Arbiter:** Monitors blackboard events, selects next KS to fire based on **agenda** (e.g., salience, utility, cost, freshness), enforces stopping rules.
    
-   **Agenda / Scheduler:** Priority queue of eligible KS activations.
    
-   **Evidence Model:** Confidence/weighting, conflict resolution, provenance.
    
-   **Tracer/Logger:** Records decisions and contributions for audit/explainability.
    

```sql
+------------------+
|    Controller    |  <-- observes events, manages agenda, selects KS
+--------+---------+
         |
         v
+------------------+         +--------------------+
|    Blackboard    | <-----> | Knowledge Source i |  (i = 1..N)
+------------------+         +--------------------+
  facts/hypotheses                  consumes/produces contributions
  events / subscriptions
```

## Participants

-   **Blackboard API** — publish/subscribe, transact updates, conflict resolution.
    
-   **Knowledge Source** — `precondition` (match), `contribute` (write), optional `estimateUtility`.
    
-   **Controller/Arbiter** — builds agenda, prioritizes, enforces policies (deadline, utility).
    
-   **Confidence/Evidence Engine** — merges scores; resolves contradictory hypotheses.
    
-   **Tracer/Logger** — captures rationale, provenance, timing.
    

## Collaboration

1.  **Initialization:** Seed blackboard with input facts.
    
2.  **Eligibility discovery:** Blackboard emits events; KSs whose preconditions match become **eligible** and enqueue activations.
    
3.  **Selection:** Controller picks the **most promising** activation (utility/cost/confidence/age).
    
4.  **Execution:** KS reads snapshot, computes contribution, writes hypotheses/facts with provenance and confidence.
    
5.  **Propagation:** New facts emit events; cycle repeats.
    
6.  **Termination:** Stop when goal satisfied, confidence threshold reached, agenda empty, or deadline hit.
    
7.  **Resulting solution** is the highest-confidence hypothesis set consistent under constraints.
    

## Consequences

**Benefits**

-   High flexibility; easy to add/replace KSs without rewiring flows.
    
-   Naturally supports **anytime** and **incremental refinement**.
    
-   Good for **heterogeneous** techniques (rules + ML + heuristics).
    
-   Strong **explainability** via provenance/hypothesis lattice.
    

**Liabilities**

-   Central blackboard can be a **contention point**; needs careful concurrency design.
    
-   Controller policy is **non-trivial** (risk of thrash or starvation).
    
-   Global shared state can grow complex; requires robust schema and pruning.
    
-   Harder to give strict worst-case latency guarantees.
    

## Implementation

### Key Design Guidelines

-   **Data model:** Explicit types (fact, hypothesis, relation), IDs, timestamps, `confidence`, `source`, `parents`.
    
-   **Concurrency:** Use **copy-on-write snapshots** or **optimistic transactions**; post contributions atomically.
    
-   **Agenda policy:** Priority by `expectedUtility = deltaGain / costEstimate`; include freshness and diversity bias.
    
-   **Subscriptions:** KS registers interest via predicates (e.g., pattern on types/tags).
    
-   **Conflict resolution:** Dempster–Shafer / Bayesian update / max-confidence-wins with hysteresis.
    
-   **Anytime & budgets:** Time-slice KS execution; support progressive refinement.
    
-   **Observability:** Trace each activation: KS, inputs, outputs, utility, duration.
    

### Stopping Criteria Examples

-   Confidence of target hypothesis ≥ τ.
    
-   Agenda empty or deadline exceeded.
    
-   Marginal utility below ε for K consecutive steps.
    

---

## Sample Code (Java)

A compact, production-inspired skeleton showing a thread-safe blackboard, pluggable knowledge sources, and a utility-driven controller. The example domain is **vehicle identification** from partial observations (plate text, color, body type). Replace with your own KSs (ML models, rules, external services).

> #### Build
> 
> Java 17+, Gradle deps only for annotations (optional). No external libs needed.

```java
// Domain primitives
enum Kind { FACT, HYPOTHESIS }

record Evidence(String source, double confidence, List<String> parents) {}

record Item(String id, String type, Map<String, Object> data, Kind kind, Evidence evidence, long ts) {}

// Contribution from a KS
record Contribution(List<Item> items, String note, double utilityEstimate) {}

// Blackboard API
interface Blackboard {
    Optional<Item> get(String id);
    List<Item> query(String type, java.util.function.Predicate<Item> pred);
    long version();

    // Atomically append items; returns new version and emitted events
    long post(List<Item> items, String ksName);
    void subscribe(String ksName, java.util.function.Predicate<Item> pred);
    List<Item> changedSince(long version);
}

// In-memory, thread-safe blackboard
class InMemoryBlackboard implements Blackboard {
    private final Map<String, Item> store = new java.util.concurrent.ConcurrentHashMap<>();
    private final List<Item> journal = new java.util.concurrent.CopyOnWriteArrayList<>();
    private final Map<String, java.util.function.Predicate<Item>> subs = new java.util.concurrent.ConcurrentHashMap<>();
    private final java.util.concurrent.atomic.AtomicLong ver = new java.util.concurrent.atomic.AtomicLong();

    @Override public Optional<Item> get(String id){ return Optional.ofNullable(store.get(id)); }
    @Override public List<Item> query(String type, java.util.function.Predicate<Item> pred){
        return store.values().stream().filter(i -> i.type().equals(type) && pred.test(i)).toList();
    }
    @Override public long version(){ return ver.get(); }
    @Override public void subscribe(String ks, java.util.function.Predicate<Item> pred){ subs.put(ks, pred); }
    @Override public List<Item> changedSince(long v){ return journal.stream().filter(i -> i.ts() > v).toList(); }

    @Override public synchronized long post(List<Item> items, String ksName){
        long now = System.nanoTime();
        for (Item it : items){
            Item stamped = new Item(it.id(), it.type(), Map.copyOf(it.data()), it.kind(),
                                    it.evidence(), now);
            store.put(stamped.id(), stamped);
            journal.add(stamped);
        }
        return ver.updateAndGet(x -> Math.max(x, now));
    }
}

// Knowledge Source interface
interface KnowledgeSource {
    String name();
    // Should this KS fire given the delta on the blackboard?
    boolean isEligible(Blackboard bb, List<Item> delta);
    // Estimate utility quickly for prioritization
    double estimateUtility(Blackboard bb, List<Item> delta);
    // Perform work and return contribution
    Contribution contribute(Blackboard bb, List<Item> delta);
    default long costMillisEstimate(){ return 10; }
}

// Example KS: license plate OCR refinement (toy heuristic)
class PlateRefinerKS implements KnowledgeSource {
    public String name(){ return "PlateRefiner"; }
    public boolean isEligible(Blackboard bb, List<Item> delta){
        return delta.stream().anyMatch(i -> i.type().equals("plate_raw"));
    }
    public double estimateUtility(Blackboard bb, List<Item> delta){ return 0.6; }
    public Contribution contribute(Blackboard bb, List<Item> delta){
        var raw = bb.query("plate_raw", i -> true);
        if (raw.isEmpty()) return new Contribution(List.of(), "no raw plate", 0);
        String txt = (String) raw.get(0).data().get("text");
        String refined = txt.replaceAll("[^A-Z0-9]", "").toUpperCase();
        Item hyp = new Item(
            "plate:"+refined,
            "plate",
            Map.of("text", refined),
            Kind.HYPOTHESIS,
            new Evidence(name(), 0.8, List.of(raw.get(0).id())),
            0L
        );
        return new Contribution(List.of(hyp), "refined plate", 0.5);
    }
}

// Example KS: reconcile vehicle make from plate prefix (toy rule)
class MakeFromPlateKS implements KnowledgeSource {
    public String name(){ return "MakeFromPlate"; }
    public boolean isEligible(Blackboard bb, List<Item> delta){
        return delta.stream().anyMatch(i -> i.type().equals("plate"));
    }
    public double estimateUtility(Blackboard bb, List<Item> delta){ return 0.4; }
    public Contribution contribute(Blackboard bb, List<Item> delta){
        var plates = bb.query("plate", i -> true);
        if (plates.isEmpty()) return new Contribution(List.of(), "no plate", 0);
        String text = (String) plates.get(0).data().get("text");
        String make = text.startsWith("W") ? "Volkswagen" : "Unknown";
        Item hyp = new Item(
            "make:"+make,
            "vehicle_make",
            Map.of("make", make),
            Kind.HYPOTHESIS,
            new Evidence(name(), "Volkswagen".equals(make) ? 0.6 : 0.2, List.of(plates.get(0).id())),
            0L
        );
        return new Contribution(List.of(hyp), "derived make from plate", 0.3);
    }
}

// Example KS: fuse color & body type to raise final hypothesis
class VehicleSynthesizerKS implements KnowledgeSource {
    public String name(){ return "VehicleSynthesizer"; }
    public boolean isEligible(Blackboard bb, List<Item> delta){
        return !bb.query("vehicle_make", i->true).isEmpty()
            && !bb.query("color", i->true).isEmpty()
            && !bb.query("body_type", i->true).isEmpty();
    }
    public double estimateUtility(Blackboard bb, List<Item> delta){ return 0.9; }
    public Contribution contribute(Blackboard bb, List<Item> delta){
        var make = (String) bb.query("vehicle_make", i->true).get(0).data().get("make");
        var color = (String) bb.query("color", i->true).get(0).data().get("value");
        var body  = (String) bb.query("body_type", i->true).get(0).data().get("value");
        double conf = 0.75;
        Item hyp = new Item(
            "vehicle:"+UUID.randomUUID(),
            "vehicle_hypothesis",
            Map.of("make", make, "color", color, "body", body, "confidence", conf),
            Kind.HYPOTHESIS,
            new Evidence(name(), conf, List.of()),
            0L
        );
        return new Contribution(List.of(hyp), "synthesized vehicle", conf);
    }
}

// Controller: builds agenda and fires KS opportunistically
class Controller {
    private final Blackboard bb;
    private final List<KnowledgeSource> sources;
    private volatile boolean running = true;
    private double targetConfidence = 0.8;
    private final java.util.concurrent.ExecutorService pool = java.util.concurrent.Executors.newFixedThreadPool(4);

    Controller(Blackboard bb, List<KnowledgeSource> sources){ this.bb = bb; this.sources = sources; }

    public void run(){
        long seen = 0;
        while (running){
            List<Item> delta = bb.changedSince(seen);
            seen = bb.version();

            // Build agenda
            record Act(KnowledgeSource ks, double utility){ }
            var agenda = new java.util.PriorityQueue<Act>(java.util.Comparator.comparingDouble((Act a) -> a.utility).reversed());
            for (var ks : sources){
                if (ks.isEligible(bb, delta)) agenda.add(new Act(ks, ks.estimateUtility(bb, delta)));
            }

            if (agenda.isEmpty()){
                sleep(5);
                continue;
            }

            // Fire a few top activations in parallel
            List<java.util.concurrent.Future<?>> futures = new java.util.ArrayList<>();
            int batch = Math.min(3, agenda.size());
            for (int i=0; i<batch; i++){
                var act = agenda.poll();
                futures.add(pool.submit(() -> {
                    var c = act.ks().contribute(bb, delta);
                    if (!c.items().isEmpty()) {
                        bb.post(c.items(), act.ks().name());
                    }
                }));
            }
            futures.forEach(f -> { try { f.get(); } catch(Exception ignored){} });

            // Check termination (toy criterion)
            var best = bb.query("vehicle_hypothesis", i -> true).stream()
                .map(i -> (double) i.data().getOrDefault("confidence", 0.0))
                .max(Double::compare).orElse(0.0);
            if (best >= targetConfidence) stop();
        }
        pool.shutdownNow();
    }
    public void stop(){ running = false; }
    private void sleep(long ms){ try { Thread.sleep(ms); } catch (InterruptedException ignored){} }
}

// Demo bootstrap
public class BlackboardDemo {
    public static void main(String[] args) {
        InMemoryBlackboard bb = new InMemoryBlackboard();

        // Seed initial observations
        bb.post(List.of(
            new Item("obs:plate_raw", "plate_raw", Map.of("text", " w- 123_ab "), Kind.FACT, new Evidence("sensor", 0.7, List.of()), 0L),
            new Item("obs:color", "color", Map.of("value", "blue"), Kind.FACT, new Evidence("sensor", 0.9, List.of()), 0L),
            new Item("obs:body", "body_type", Map.of("value", "hatchback"), Kind.FACT, new Evidence("sensor", 0.8, List.of()), 0L)
        ), "bootstrap");

        var ksList = List.of(new PlateRefinerKS(), new MakeFromPlateKS(), new VehicleSynthesizerKS());
        Controller ctrl = new Controller(bb, ksList);
        ctrl.run();

        // Print final hypotheses
        var results = bb.query("vehicle_hypothesis", i->true);
        results.forEach(i -> System.out.println("Result: " + i.data()));
    }
}
```

**Notes**

-   Replace toy KS logic with **ML models**, **rule engines**, or **external services**.
    
-   For scale: shard by case ID; use an event log for the journal; adopt **optimistic locking** with retries on conflicts.
    
-   Persist provenance to enable **explainable decisions** and replay.
    

## Known Uses

-   **Hearsay-II / speech understanding** (classic AI).
    
-   **BBN Hound** and **MIT HEARSAY**\-family systems for multi-level parsing/recognition.
    
-   **Image understanding** pipelines combining segmentation, detection, and semantic labeling.
    
-   **Cybersecurity SOC triage:** different detectors enrich incidents on a shared board.
    
-   **Autonomous driving perception:** fusion of camera/LiDAR/radar hypotheses.
    
-   **Clinical decision support:** multiple diagnostic KSs contribute to a working diagnosis.
    

## Related Patterns

-   **Mediator** (controller role) — but blackboard emphasizes **shared, evolving state** and opportunistic scheduling.
    
-   **Event-Driven Architecture** — blackboard events trigger KSs; EDA can back the journal.
    
-   **Pipes & Filters** — linear flows; blackboard generalizes to **nonlinear, opportunistic** refinement.
    
-   **Rule Engine / Production System** — similar agenda/activation; blackboard is **state-centric** with rich artifacts.
    
-   **Microkernel** — blackboard as core with pluggable KS services.
    
-   **Observer** — KS subscriptions to blackboard changes.
    

---

**Implementation Tips**

-   Use **CRDTs** or **immutable snapshots** if you need distributed blackboards.
    
-   Add **utility learning**: log KS payoff and train a scheduler (contextual bandit).
    
-   Integrate **confidence fusion** (Bayes/D-S theory) and **conflict clauses** to prevent oscillation.
    
-   Provide **anytime APIs** to query best-so-far solutions with provenance graphs.

