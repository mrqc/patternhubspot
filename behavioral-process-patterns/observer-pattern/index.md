# Observer — Behavioral / Process Pattern

## Pattern Name and Classification

**Observer** — *Behavioral / Process* pattern for **publish–subscribe** (one-to-many) notification of state changes or events.

---

## Intent

Define a **one-to-many dependency** so when one object (**Subject**) changes state, it **notifies** all dependent objects (**Observers**) automatically, without the subject knowing their concrete types.

---

## Also Known As

-   **Publish–Subscribe (Pub/Sub)** (in-process variant)

-   **Listener** / **Event Handler**

-   **Reactive Push Model**


---

## Motivation (Forces)

-   Multiple parts of a system must react to **the same event** (UI refresh, caches, logs, metrics, workflows).

-   We want **loose coupling**: the subject should not depend on observers.

-   Observers may come and go at runtime (subscribe/unsubscribe).


Trade-offs:

-   Push vs. pull (how much data the subject sends).

-   Delivery guarantees (best-effort vs. durable), ordering, thread-safety, backpressure (for high frequency).


---

## Applicability

Use Observer when:

-   There is **one source** and **many dependents** that need timely updates.

-   You need **extensibility**: new reactions without touching the subject.

-   Event volume is moderate (or you adopt a reactive library for high volume).


Avoid / limit when:

-   You need **cross-process** fan-out (use message brokers).

-   You require **backpressure**/buffering (prefer Reactor/RxJava/Flow APIs).


---

## Structure

```css
Subject ──────── notifies ───────▶ Observer A
   │                               Observer B
   └─ manages subscriptions        Observer C
```

-   Observers register with the subject and receive **onNext / onError / onComplete** or a simple `update()` callback.


---

## Participants

-   **Subject (Observable)** — holds state; manages **subscribe/unsubscribe**; emits notifications.

-   **Observer (Listener)** — receives notifications; typically stateless or keeps a projection.

-   **Subscription/Handle** — allows **cancellation** of observation.


---

## Collaboration

1.  Observers **subscribe** to the subject.

2.  Subject changes state or receives an event → **notifies** all current observers.

3.  Observers process the event; they can **unsubscribe** at any time.


---

## Consequences

**Benefits**

-   **Loose coupling** between producer and consumers.

-   Easy to add new behaviors by **adding observers**.

-   Encourages **event-driven** designs and UI reactivity.


**Liabilities**

-   Harder to reason about **implicit control flow** (who runs when).

-   Risk of **memory leaks** if observers never unsubscribe.

-   Potential **notification storms**; need throttling/debouncing/backpressure.


---

## Implementation (Key Points)

-   Provide a **thread-safe** subscription list (e.g., `CopyOnWriteArrayList`).

-   Return a **Subscription handle** (closeable) to allow explicit unsubscription (avoid leaks).

-   Decide **synchronous** vs **asynchronous** notification and document ordering guarantees.

-   Consider push **contract**: `onNext(T)`, optional `onError(Throwable)`, `onComplete()`.

-   Guard observers: **catch exceptions** so one bad observer doesn’t break the others.

-   For high-throughput/asynchrony, consider **java.util.concurrent.Flow**, **Project Reactor**, or **RxJava**.


---

## Sample Code (Java 17) — Minimal, Thread-Safe Observer with Unsubscribe

> Scenario: a `PriceTicker` (Subject) pushes price updates to multiple observers (console logger, alerting).

```java
import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

// --- Observer API (push style) ---
interface Observer<T> {
  void onNext(T event);
  default void onError(Throwable t) { t.printStackTrace(); }
  default void onComplete() {}
}

// Subscription handle to avoid leaks
interface Subscription extends AutoCloseable {
  @Override void close(); // unsubscribe
  boolean isActive();
}

// --- Subject (Observable) ---
class Subject<T> {
  private final List<Observer<T>> observers = new CopyOnWriteArrayList<>();
  private volatile boolean completed = false;

  public Subscription subscribe(Observer<T> obs) {
    Objects.requireNonNull(obs, "observer");
    if (completed) { obs.onComplete(); return new NoopSubscription(); }
    observers.add(obs);
    return new Subscription() {
      private volatile boolean active = true;
      public void close() { if (active) { observers.remove(obs); active = false; } }
      public boolean isActive() { return active; }
    };
  }

  public void next(T event) {
    if (completed) return;
    for (Observer<T> o : observers) {
      try { o.onNext(event); } catch (Throwable t) { o.onError(t); }
    }
  }

  public void error(Throwable t) {
    for (Observer<T> o : observers) {
      try { o.onError(t); } catch (Throwable ignore) {}
    }
    observers.clear();
    completed = true;
  }

  public void complete() {
    for (Observer<T> o : observers) {
      try { o.onComplete(); } catch (Throwable ignore) {}
    }
    observers.clear();
    completed = true;
  }

  private static final class NoopSubscription implements Subscription {
    public void close() {}
    public boolean isActive() { return false; }
  }
}

// --- Domain model ---
record PriceTick(String symbol, double price, Instant at) { }

// --- Concrete observers ---
class LoggingObserver implements Observer<PriceTick> {
  @Override public void onNext(PriceTick e) {
    System.out.printf("[LOG] %s %.2f @ %s%n", e.symbol(), e.price(), e.at());
  }
}

class AlertObserver implements Observer<PriceTick> {
  private final String symbol; private final double threshold;
  AlertObserver(String symbol, double threshold) { this.symbol = symbol; this.threshold = threshold; }
  @Override public void onNext(PriceTick e) {
    if (e.symbol().equals(symbol) && e.price() >= threshold) {
      System.out.println("[ALERT] " + symbol + " hit " + e.price());
    }
  }
}

// --- Subject implementation example ---
class PriceTicker extends Subject<PriceTick> {
  // Optionally, push on a background pool for async delivery
  private final ExecutorService pool = Executors.newSingleThreadExecutor();
  public void publishAsync(PriceTick tick) { pool.submit(() -> next(tick)); }
  public void shutdown() { complete(); pool.shutdownNow(); }
}

// --- Demo ---
public class ObserverDemo {
  public static void main(String[] args) throws InterruptedException {
    var ticker = new PriceTicker();

    Subscription s1 = ticker.subscribe(new LoggingObserver());
    Subscription s2 = ticker.subscribe(new AlertObserver("ACME", 100.00));

    // Emit a few synchronous events
    ticker.next(new PriceTick("ACME", 98.40, Instant.now()));
    ticker.next(new PriceTick("ACME", 100.05, Instant.now())); // triggers alert
    ticker.next(new PriceTick("FOO", 12.30, Instant.now()));

    // Unsubscribe one observer to avoid leaks
    s1.close();

    // Async emission example
    ticker.publishAsync(new PriceTick("ACME", 101.25, Instant.now()));
    Thread.sleep(50);

    ticker.complete();  // notifies remaining observers and closes
    ticker.shutdown();
  }
}
```

**Highlights**

-   Thread-safe subscription via `CopyOnWriteArrayList`.

-   **Subscription handle** prevents memory leaks.

-   Subject catches observer exceptions so **one bad listener** doesn’t break others.

-   Shows **sync** (`next`) and **async** (`publishAsync`) emission.


---

## Known Uses

-   GUI frameworks (Swing/SWT listeners), logging appenders, cache invalidation listeners.

-   Domain events within a process; file system watchers; configuration hot-reload.

-   Reactive libraries: **Reactor**, **RxJava**, Java 9 **Flow** (Publisher/Subscriber) formalize Observer with backpressure.


---

## Related Patterns

-   **Mediator** — coordinates targeted interactions; Observer is broadcast-style.

-   **Event Bus** — wider system-level pub/sub (often cross-component or cross-thread).

-   **Reactor / Flow** — standardized reactive observer with **backpressure**.

-   **CQRS + Domain Events** — observers project changes into read models.

-   **Decorator / Proxy** — orthogonal; can be observers of lifecycle to add behavior.
