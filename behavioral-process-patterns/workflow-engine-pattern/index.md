# Workflow Engine — Behavioral / Process Pattern

## Pattern Name and Classification

**Workflow Engine** — *Behavioral / Process* pattern that models and executes **long-running, multi-step workflows** using an explicit **process definition** (steps, transitions, timers, retries, compensation).

---

## Intent

Externalize **process logic** (sequence, branching, timeouts) from business components so you can **define, run, observe, and evolve** workflows without hard-coding orchestration in services/controllers.

---

## Also Known As

-   **Process Orchestrator**

-   **Stateful Job Runner**

-   **BPM Light / Flow Engine** (code-centric variant)


---

## Motivation (Forces)

-   Real-world processes span **multiple steps** across systems (payments, KYC, emails).

-   Steps may be **asynchronous**, **idempotent**, require **retries**, **backoff**, and **timeouts**.

-   Hard-wiring orchestration scatters logic and is hard to test/observe.

-   A workflow engine offers **definitions + runtime** with **state, timers, and history**.


**Trade-offs**: Another moving piece to operate; poor designs become a “monolithic brain.” Keep engines **minimal**, scope **per domain**, and keep steps **idempotent**.

---

## Applicability

Use a workflow engine when:

-   You need **long-running** orchestration (> seconds) with **retries/timeouts**.

-   Workflows **change** more often than step implementations.

-   You want **observability** (state, history) and **operability** (pause/resume, retry).


Avoid when:

-   A single transaction or a simple **FSM** inside one service suffices.

-   The flow is short, synchronous, and rarely changes.


---

## Structure

```sql
+-----------------------------+
Definition|  WorkflowDefinition         |
          |  - steps: name -> Step     |
          |  - transitions: (step, outcome) -> nextStep
          |  - startStep               |
          +--------------+--------------+
                         |
                         v
          +-----------------------------+
Runtime   |  WorkflowEngine             |
          |  - run(instanceId, ctx)     -> schedules first step
          |  - execute(step, ctx)       -> StepResult
          |  - timers, retries, store   |
          +--------------+--------------+
                         |
                         v
          +-----------------------------+
          |     Step (idempotent)       |
          |  execute(ctx) -> StepResult |
          +-----------------------------+
```

**StepResult** drives the engine: `SUCCESS`, `FAILURE`, `RETRY(after)`, `SLEEP(delay)`, `GOTO(step)`.

---

## Participants

-   **WorkflowDefinition** — names steps and **transition table**.

-   **Step** — encapsulates one business action; **idempotent**; returns `StepResult`.

-   **WorkflowEngine** — executes steps, persists state, schedules **delays/retries**.

-   **Store** — persists **instances** (state, context, history, dedup).

-   **Timers/Scheduler** — fires delayed continuations.


---

## Collaboration

1.  Client starts an **instance** with an initial **context**.

2.  Engine executes the **current step** → receives `StepResult`.

3.  Engine consults **transitions** (or `GOTO`) → moves to **next step**.

4.  On `RETRY`/`SLEEP`, engine **schedules** and persists.

5.  On terminal result, engine marks **COMPLETED/FAILED**, keeping **history**.


---

## Consequences

**Benefits**

-   Process logic is **declarative** and centralized; steps stay focused.

-   First-class **timeouts/retries/compensation**.

-   **Observability**: inspect instances, replay, manual retry.


**Liabilities**

-   Operational complexity (state store, timers, dead-letter handling).

-   Wrong granularity can bloat the engine or steps.

-   Requires **idempotency** and **deduplication** discipline.


---

## Implementation (Key Points)

-   Steps must be **idempotent**; use **idempotency keys** and outbox for side-effects.

-   Persist **(state, context, history)** before/after each transition (transactional if possible).

-   Provide **backoff** policies and maximum retries per step.

-   Model **compensation steps** reachable on failure.

-   Use **correlation IDs** and **metrics/tracing** per instance/step.

-   Keep the engine **pluggable** (in-memory for tests, persistent for prod).


---

## Sample Code (Java 17) — Minimal, Runnable Workflow Engine

> A small code-first engine with: definition, steps, transitions, retries, timers, and in-memory store.  
> Example workflow: **User Onboarding** with email verification, account creation, payment, and welcome email; includes **retry** and **compensation**.

```java
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Function;

// ---------- Engine primitives ----------
enum Outcome { SUCCESS, FAILURE, RETRY, SLEEP, GOTO }

record StepResult(Outcome type, String detail, Duration delay, String nextOverride) {
  static StepResult success()                          { return new StepResult(Outcome.SUCCESS, null, null, null); }
  static StepResult failure(String why)                { return new StepResult(Outcome.FAILURE, why, null, null); }
  static StepResult retry(Duration after, String why)  { return new StepResult(Outcome.RETRY, why, after, null); }
  static StepResult sleep(Duration delay, String why)  { return new StepResult(Outcome.SLEEP, why, delay, null); }
  static StepResult goTo(String step)                  { return new StepResult(Outcome.GOTO, null, null, step); }
}

interface Step {
  String name();
  StepResult execute(Map<String,Object> ctx) throws Exception;
}

// ---------- Definition ----------
final class WorkflowDefinition {
  final String name;
  final String startStep;
  final Map<String, Step> steps = new LinkedHashMap<>();
  // transitions.get(step).get(outcome) -> nextStep
  final Map<String, Map<Outcome, String>> transitions = new HashMap<>();

  WorkflowDefinition(String name, String startStep) { this.name = name; this.startStep = startStep; }

  WorkflowDefinition step(Step s) { steps.put(s.name(), s); return this; }
  WorkflowDefinition on(String step, Outcome when, String next) {
    transitions.computeIfAbsent(step, k -> new EnumMap<>(Outcome.class)).put(when, next); return this;
  }
}

// ---------- Runtime state & store ----------
enum InstanceStatus { RUNNING, COMPLETED, FAILED }

final class Instance {
  final String id;
  final String wfName;
  String currentStep;
  InstanceStatus status = InstanceStatus.RUNNING;
  int attempts = 0;
  final Map<String,Object> ctx = new ConcurrentHashMap<>();
  final List<String> history = new CopyOnWriteArrayList<>();

  Instance(String id, String wfName, String startStep, Map<String,Object> init) {
    this.id = id; this.wfName = wfName; this.currentStep = startStep; if (init != null) ctx.putAll(init);
  }
}

interface Store {
  void save(Instance i);
  Optional<Instance> load(String id);
  void appendHistory(Instance i, String line);
}

final class InMemoryStore implements Store {
  private final Map<String, Instance> map = new ConcurrentHashMap<>();
  @Override public void save(Instance i) { map.put(i.id, i); }
  @Override public Optional<Instance> load(String id) { return Optional.ofNullable(map.get(id)); }
  @Override public void appendHistory(Instance i, String line) { i.history.add(Instant.now()+" "+line); }
}

// ---------- Engine ----------
final class WorkflowEngine {
  private final Store store;
  private final ScheduledExecutorService scheduler = Executors.newScheduledThreadPool(2);
  private final Map<String, WorkflowDefinition> registry = new ConcurrentHashMap<>();
  private final int maxRetries;

  WorkflowEngine(Store store, int maxRetries) {
    this.store = store; this.maxRetries = maxRetries;
  }

  void register(WorkflowDefinition def) { registry.put(def.name, def); }

  String start(String wfName, Map<String,Object> ctx) {
    var def = require(registry.get(wfName), "Unknown workflow: "+wfName);
    String id = UUID.randomUUID().toString();
    var inst = new Instance(id, wfName, def.startStep, ctx);
    store.save(inst);
    scheduleNow(inst.id);
    return id;
  }

  void scheduleNow(String instanceId) {
    scheduler.submit(() -> tick(instanceId));
  }

  void scheduleAfter(String instanceId, Duration d) {
    scheduler.schedule(() -> tick(instanceId), d.toMillis(), TimeUnit.MILLISECONDS);
  }

  private void tick(String instanceId) {
    var inst = store.load(instanceId).orElseThrow();
    if (inst.status != InstanceStatus.RUNNING) return;

    var def = registry.get(inst.wfName);
    var step = require(def.steps.get(inst.currentStep), "Missing step: "+inst.currentStep);

    try {
      store.appendHistory(inst, "EXEC " + step.name());
      StepResult r = step.execute(inst.ctx);

      switch (r.type()) {
        case SUCCESS -> {
          inst.attempts = 0;
          String next = nextOf(def, step.name(), Outcome.SUCCESS, r);
          if (next == null) { inst.status = InstanceStatus.COMPLETED; store.appendHistory(inst, "DONE"); }
          else { inst.currentStep = next; store.appendHistory(inst, "NEXT " + next); scheduleNow(inst.id); }
        }
        case FAILURE -> {
          String next = nextOf(def, step.name(), Outcome.FAILURE, r);
          if (next != null) { inst.currentStep = next; inst.attempts = 0; store.appendHistory(inst, "FAIL->GOTO "+next+" reason="+r.detail()); scheduleNow(inst.id); }
          else { inst.status = InstanceStatus.FAILED; store.appendHistory(inst, "FAILED reason="+r.detail()); }
        }
        case RETRY -> {
          inst.attempts++;
          if (inst.attempts > maxRetries) {
            store.appendHistory(inst, "MAX-RETRIES reached"); 
            String next = nextOf(def, step.name(), Outcome.FAILURE, r);
            if (next != null) { inst.currentStep = next; inst.attempts = 0; scheduleNow(inst.id); }
            else { inst.status = InstanceStatus.FAILED; }
          } else {
            Duration d = r.delay() != null ? r.delay() : Duration.ofSeconds((long)Math.min(60, Math.pow(2, inst.attempts)));
            store.appendHistory(inst, "RETRY in " + d.toSeconds() + "s ("+inst.attempts+")");
            scheduleAfter(inst.id, d);
          }
        }
        case SLEEP -> {
          Duration d = r.delay() != null ? r.delay() : Duration.ofSeconds(5);
          store.appendHistory(inst, "SLEEP " + d.toSeconds() + "s");
          scheduleAfter(inst.id, d);
        }
        case GOTO -> {
          inst.currentStep = r.nextOverride();
          inst.attempts = 0;
          store.appendHistory(inst, "GOTO " + inst.currentStep);
          scheduleNow(inst.id);
        }
      }
    } catch (Exception ex) {
      // Treat exceptions as RETRYable with backoff
      inst.attempts++;
      Duration d = Duration.ofSeconds((long)Math.min(60, Math.pow(2, inst.attempts)));
      store.appendHistory(inst, "EXCEPTION: " + ex.getMessage() + " -> RETRY in " + d.toSeconds()+"s");
      if (inst.attempts > maxRetries) {
        // escalate to FAILURE path
        var def = registry.get(inst.wfName);
        String next = nextOf(def, inst.currentStep, Outcome.FAILURE, StepResult.failure(ex.getMessage()));
        if (next != null) { inst.currentStep = next; inst.attempts = 0; scheduleNow(inst.id); }
        else { inst.status = InstanceStatus.FAILED; }
      } else {
        scheduleAfter(inst.id, d);
      }
    } finally {
      store.save(inst);
    }
  }

  private static <T> T require(T v, String msg) { if (v==null) throw new IllegalArgumentException(msg); return v; }

  private String nextOf(WorkflowDefinition def, String step, Outcome out, StepResult r) {
    if (r.nextOverride()!=null) return r.nextOverride();
    return Optional.ofNullable(def.transitions.get(step)).map(m->m.get(out)).orElse(null);
  }

  // Debug helper
  void printInstance(String id) {
    var inst = store.load(id).orElseThrow();
    System.out.println("Instance " + id + " ["+inst.status+"] step=" + inst.currentStep);
    inst.history.forEach(System.out::println);
  }
}

// ---------- Demo steps: onboarding ----------
final class VerifyEmail implements Step {
  public String name() { return "verify-email"; }
  public StepResult execute(Map<String,Object> ctx) {
    // If flag not set, "send mail" and sleep awaiting user
    if (!Boolean.TRUE.equals(ctx.getOrDefault("emailVerified", false))) {
      System.out.println("[VerifyEmail] Email not yet verified; sending link…");
      // Pretend we sent a link; wait for an external callback that flips context
      return StepResult.sleep(Duration.ofSeconds(2), "await-user");
    }
    System.out.println("[VerifyEmail] Email verified");
    return StepResult.success();
  }
}

final class CreateAccount implements Step {
  public String name() { return "create-account"; }
  public StepResult execute(Map<String,Object> ctx) {
    if (ctx.containsKey("accountId")) return StepResult.success(); // idempotent
    // Simulate transient error
    if (!ctx.containsKey("try")) ctx.put("try", 1); else ctx.put("try", (int)ctx.get("try")+1);
    int attempt = (int)ctx.get("try");
    if (attempt < 2) {
      System.out.println("[CreateAccount] transient failure, attempt " + attempt);
      return StepResult.retry(Duration.ofSeconds(1), "transient");
    }
    String id = "acct_" + UUID.randomUUID();
    ctx.put("accountId", id);
    System.out.println("[CreateAccount] created " + id);
    return StepResult.success();
  }
}

final class ChargePayment implements Step {
  public String name() { return "charge-payment"; }
  public StepResult execute(Map<String,Object> ctx) {
    Integer amount = (Integer) ctx.getOrDefault("amountCents", 0);
    if (amount <= 0) return StepResult.failure("no-amount");
    // Simulate charge
    ctx.put("paymentId", "pay_"+amount);
    System.out.println("[ChargePayment] charged " + amount);
    return StepResult.success();
  }
}

final class RefundPayment implements Step {
  public String name() { return "refund-payment"; }
  public StepResult execute(Map<String,Object> ctx) {
    if (ctx.get("paymentId") != null) System.out.println("[RefundPayment] refunded "+ctx.get("paymentId"));
    return StepResult.success();
  }
}

final class SendWelcome implements Step {
  public String name() { return "send-welcome"; }
  public StepResult execute(Map<String,Object> ctx) {
    System.out.println("[SendWelcome] welcome email to user");
    return StepResult.success();
  }
}

// ---------- Wiring & Demo ----------
public class WorkflowEngineDemo {
  public static void main(String[] args) throws Exception {
    Store store = new InMemoryStore();
    WorkflowEngine engine = new WorkflowEngine(store, /*maxRetries*/ 3);

    // Define workflow
    WorkflowDefinition onboarding = new WorkflowDefinition("onboarding", "verify-email")
        .step(new VerifyEmail())
        .step(new CreateAccount())
        .step(new ChargePayment())
        .step(new RefundPayment())
        .step(new SendWelcome());

    // Happy path transitions
    onboarding.on("verify-email", Outcome.SUCCESS, "create-account");
    onboarding.on("create-account", Outcome.SUCCESS, "charge-payment");
    onboarding.on("charge-payment", Outcome.SUCCESS, "send-welcome");
    onboarding.on("send-welcome", Outcome.SUCCESS, null); // terminal

    // Failure → compensation path
    onboarding.on("charge-payment", Outcome.FAILURE, "refund-payment");
    onboarding.on("refund-payment", Outcome.SUCCESS, null);

    engine.register(onboarding);

    // Start instance
    Map<String,Object> ctx = new HashMap<>();
    ctx.put("amountCents", 2599);
    String id = engine.start("onboarding", ctx);

    // Simulate the user verifying email after a moment (external callback)
    ScheduledExecutorService ses = Executors.newSingleThreadScheduledExecutor();
    ses.schedule(() -> {
      store.load(id).ifPresent(inst -> {
        inst.ctx.put("emailVerified", true);
        store.save(inst);
        // Nudge engine (would normally be an event)
        engine.scheduleNow(inst.id);
      });
    }, 3, TimeUnit.SECONDS);

    // Let it run a bit
    Thread.sleep(6000);
    engine.printInstance(id);
    ses.shutdownNow();
    System.exit(0);
  }
}
```

**What this demonstrates**

-   **Definition vs. execution** separation; transitions are **data**, not code branching.

-   **Idempotent** steps; **retry** with backoff; **sleep** for external waits; **compensation** via failure transition.

-   Minimal **store** and **timers**; easy to swap for persistent implementations.


---

## Known Uses

-   User **onboarding**, **KYC**, **checkout**, **fulfillment** flows.

-   Data pipelines (ETL), document approval, subscription lifecycle.

-   Code-centric engines (Temporal/Cadence, Netflix Conductor-lite patterns, Spring Statemachine/Batch) and BPMN engines (Camunda/Zeebe, jBPM) for heavier needs.


---

## Related Patterns

-   **Process Manager / Saga** — workflow engine is a *generalized orchestrator*; sagas add explicit **compensations** for distributed transactions.

-   **Finite State Machine** — the workflow can be modeled as an FSM; the engine executes it with timers/retries.

-   **Command** — steps can be implemented as commands; history enables undo/redo semantics.

-   **Mediator** — coordinates components; the engine is a reusable mediator with state and timers.

-   **Transactional Outbox / Idempotency Key / Retry** — reliability building blocks for steps.
