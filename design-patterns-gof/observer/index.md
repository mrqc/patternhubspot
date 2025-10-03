
# Observer — GoF Behavioral Pattern

## Pattern Name and Classification

**Name:** Observer  
**Category:** Behavioral design pattern

## Intent

Define a **one-to-many dependency** between objects so that when one object (the **Subject**) changes state, all its dependents (the **Observers**) are **notified and updated** automatically—without tight coupling.

## Also Known As

Publish–Subscribe (local/in-process), Listener, Dependents

## Motivation (Forces)

-   You want to **decouple state** (the model) from **reactions** (views, side effects).

-   Multiple parties need to react to **the same event** in different ways.

-   The set of interested parties is **dynamic** (observers come and go).

-   You don’t want the subject to know **who** listens or **what** they do.


## Applicability

Use Observer when:

-   A change in one object requires **updating others** and you don’t know how many dependents there are.

-   You want to **broadcast events** within the same process without hard dependencies.

-   You need **extensible reactions** (add observers for logging, metrics, caching, UI, …).


## Structure

-   **Subject** keeps a list of observers and notifies them of changes.

-   **Observer** defines an `update`/`onEvent` method.

-   **ConcreteSubject** stores state, triggers notifications.

-   **ConcreteObserver** registers and reacts.


```sql
+-----------+      notifies       +-----------------+
   |  Subject  |-------------------->|    Observer     |
   |(attach/detach,                  | + update(...)   |
   | notify)     ^   ^               +-----------------+
   +-----------+  \  \_____ multiple observers
        |           \
   +---------+       \
   | Concrete|        --> +---------------------+
   | Subject |            | ConcreteObserver... |
   +---------+            +---------------------+
```

## Participants

-   **Subject**: manages observer registration and notification.

-   **Observer**: callback contract for updates.

-   **ConcreteSubject**: holds state; calls `notifyObservers`.

-   **ConcreteObserver**: pulls state from subject or consumes pushed event data.


## Collaboration

-   Observers **subscribe** to the subject.

-   Subject **pushes** data (event) **or** a reference to itself (observers then **pull** what they need).

-   Observers can **unsubscribe** at any time; subject remains oblivious to who they are.


## Consequences

**Benefits**

-   **Loose coupling** between publisher and subscribers.

-   **Open/Closed**: add new behaviors by adding observers.

-   Supports **dynamic** fan-out and reuse of subject/observers.


**Liabilities**

-   **Notification storms** if you don’t debounce/coalesce.

-   **Order** of observer invocation may matter (document it if so).

-   Risk of **memory leaks** if observers aren’t detached (consider weak refs).

-   Error handling and **backpressure** are non-trivial for async/high-volume streams.


## Implementation

-   **Push vs Pull**:

    -   *Push:* `onEvent(payload)` (fast path, minimal coupling to subject).

    -   *Pull:* `update(subject)` then call getters (classic GoF).

-   Decide **sync vs async** delivery:

    -   Sync is simple but observers can block each other.

    -   Async needs an **executor**, error strategy, and possibly backpressure.

-   Thread-safety: use `CopyOnWriteArrayList/Set` or concurrent structures.

-   **Lifecycle**: return a `Subscription` from `subscribe()` so observers can easily unsubscribe.

-   Consider **weak references** for UI observers to avoid leaks.

-   For typed events, prefer **generics** and immutable event objects.

-   In Java, prefer modern approaches over the deprecated `java.util.Observable`/`Observer` (use your own interfaces, `PropertyChangeSupport`, or `java.util.concurrent.Flow` / reactive libraries).


---

## Sample Code (Java)

**Scenario:** A `TemperatureSensor` (Subject) publishes readings.  
Observers: a `DisplayPanel`, an `AlertService` (only when over a threshold), and an `AsyncLogger` receiving events on a thread pool.

```java
import java.time.Instant;
import java.util.Set;
import java.util.concurrent.*;
import java.util.concurrent.CopyOnWriteArraySet;
import java.util.function.Predicate;

/* ====== Contracts ====== */

interface Observer<E> {
    void onEvent(E event);
    default void onError(Throwable t) { t.printStackTrace(); }
    default void onComplete() { /* optional */ }
}

interface Subscription {
    void unsubscribe();
    boolean isActive();
}

/** Thread-safe Subject base with push-style events. */
class Subject<E> {
    private final Set<Observer<E>> observers = new CopyOnWriteArraySet<>();

    public Subscription subscribe(Observer<E> obs) {
        observers.add(obs);
        return new Subscription() {
            private volatile boolean active = true;
            public void unsubscribe() { if (active) { active = false; observers.remove(obs); } }
            public boolean isActive() { return active; }
        };
    }

    protected void publish(E event) {
        for (Observer<E> o : observers) {
            try { o.onEvent(event); } catch (Throwable t) { o.onError(t); }
        }
    }

    protected void complete() {
        for (Observer<E> o : observers) {
            try { o.onComplete(); } catch (Throwable t) { o.onError(t); }
        }
        observers.clear();
    }
}

/* ====== Domain Event & Subject ====== */

record TemperatureReading(double celsius, Instant at) {
    @Override public String toString() { return "%.2f°C @ %s".formatted(celsius, at); }
}

class TemperatureSensor extends Subject<TemperatureReading> {
    public void emit(double celsius) {
        publish(new TemperatureReading(celsius, Instant.now()));
    }
}

/* ====== Utility: filtering and async wrappers ====== */

class FilteringObserver<E> implements Observer<E> {
    private final Predicate<? super E> predicate;
    private final Observer<E> delegate;
    FilteringObserver(Predicate<? super E> predicate, Observer<E> delegate) {
        this.predicate = predicate; this.delegate = delegate;
    }
    public void onEvent(E event) { if (predicate.test(event)) delegate.onEvent(event); }
    public void onError(Throwable t) { delegate.onError(t); }
    public void onComplete() { delegate.onComplete(); }
}

class AsyncObserver<E> implements Observer<E>, AutoCloseable {
    private final Observer<E> delegate;
    private final ExecutorService exec;
    AsyncObserver(Observer<E> delegate, ExecutorService exec) {
        this.delegate = delegate; this.exec = exec;
    }
    public void onEvent(E event) { exec.submit(() -> delegate.onEvent(event)); }
    public void onError(Throwable t) { exec.submit(() -> delegate.onError(t)); }
    public void onComplete() { exec.submit(delegate::onComplete); }
    @Override public void close() { exec.shutdownNow(); }
}

/* ====== Concrete Observers ====== */

class DisplayPanel implements Observer<TemperatureReading> {
    public void onEvent(TemperatureReading r) {
        System.out.println("[Panel] " + r);
    }
}

class AlertService implements Observer<TemperatureReading> {
    private final double threshold;
    AlertService(double threshold) { this.threshold = threshold; }
    public void onEvent(TemperatureReading r) {
        System.out.println("[ALERT] Temperature high: " + r);
    }
}

/* ====== Demo ====== */

public class ObserverDemo {
    public static void main(String[] args) throws Exception {
        TemperatureSensor sensor = new TemperatureSensor();

        // Plain observer
        Subscription uiSub = sensor.subscribe(new DisplayPanel());

        // Filtered observer: only warnings when over 30°C
        Observer<TemperatureReading> alert = new FilteringObserver<>(
            r -> r.celsius() > 30.0, new AlertService(30.0)
        );
        Subscription alertSub = sensor.subscribe(alert);

        // Async observer: logging on a thread pool
        AsyncObserver<TemperatureReading> asyncLogger =
            new AsyncObserver<>(r -> System.out.println("[LOG] " + r),
                                Executors.newFixedThreadPool(1));
        Subscription logSub = sensor.subscribe(asyncLogger);

        // Emit some data
        sensor.emit(21.3);
        sensor.emit(29.9);
        sensor.emit(31.4); // triggers alert
        sensor.emit(35.0); // triggers alert

        // Unsubscribe UI; others continue
        uiSub.unsubscribe();
        sensor.emit(22.0);

        // Complete stream and cleanup
        sensor.complete();
        asyncLogger.close();
    }
}
```

**What this shows**

-   A **thread-safe** subject using `CopyOnWriteArraySet`.

-   **Subscription** handle to detach observers cleanly.

-   **Filtering** and **asynchronous** observers as reusable wrappers.

-   Push-style events with optional `onError`/`onComplete` hooks (familiar to reactive users).


---

## Known Uses

-   **GUI frameworks**: Swing/JavaFX listeners (`ActionListener`, `ChangeListener`, etc.).

-   **`PropertyChangeSupport` / `ObservableValue`**: property observers.

-   **Java 9+ Reactive Streams**: `java.util.concurrent.Flow` (Publisher/Subscriber).

-   **Logging/metrics hooks**: appenders/sinks subscribe to events.

-   **Caching/invalidation**: observers clear caches when the model changes.

-   **Event buses / domain events** (in-process): components subscribe to domain notifications.


## Related Patterns

-   **Mediator**: centralizes interaction **policy**; Observer just **broadcasts** updates. They can be combined (a mediator also observes).

-   **Publisher–Subscriber** (distributed): networked variant of Observer (brokers like Kafka, SNS).

-   **MVC/MVP**: views observe the model.

-   **Command**: observers may execute commands in response to events.

-   **Iterator**: pull vs push—Observer is push-based; iterators are pull-based.

-   **Reactor**/**Proactor**: system-level event demultiplexing; Observer is the design-level callback side.
