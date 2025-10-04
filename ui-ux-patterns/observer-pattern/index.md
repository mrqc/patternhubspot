# Observer — UI/UX Pattern

## Pattern Name and Classification

**Name:** Observer  
**Category:** UI/UX · Behavioral Design Pattern · Eventing/Subscriptions · Reactive Interaction

## Intent

Define a **one-to-many dependency** so that when a subject’s state changes, **all dependent observers are notified** and updated automatically—without tight coupling between them.

## Also Known As

Publish–Subscribe (when decoupled by a broker) · Listener · Event Handler · Reactive Notifications

## Motivation (Forces)

-   **Decoupling:** Producers shouldn’t know concrete consumers; consumers subscribe to what they need.
    
-   **Timeliness:** UIs must react to model changes (e.g., cart total updates, live badge counters).
    
-   **Scalability:** Multiple views/components can reuse the same source of truth.
    
-   **Asynchrony:** Sources may emit at unpredictable times (network, sensors, timers).
    
-   **Trade-offs:** Ordering, re-entrancy, and error propagation become non-trivial; risk of leaks if observers aren’t detached.
    

## Applicability

Use Observer when:

-   Multiple UI elements depend on shared state (model changes → updates).
    
-   You need a push model for events (data arrives and should be propagated).
    
-   Plugins or extensions should react to system events without modifying the core.
    

Avoid or adapt when:

-   The number of observers is huge and you need **fan-out control/backpressure** (consider reactive streams).
    
-   You require **exactly-once**, transactional delivery (use message queues/event sourcing).
    
-   Strong ordering across heterogeneous observers is critical (consider explicit pipelines).
    

## Structure

-   **Subject (Observable):** Maintains a list of observers; exposes subscribe/unsubscribe; notifies on state change.
    
-   **Observer (Subscriber/Listener):** Registers interest and implements an `update` method.
    
-   **Event/Change:** Optional value describing the change (type + payload).
    
-   **Dispatcher:** (Optional) Synchronous or asynchronous delivery strategy.
    

```scss
┌───────────────┐     notify(event)     ┌─────────────┐
State ─►│   Subject      │──────────────────────►│  Observer A │
change   └───────────────┘                       └─────────────┘
              │   ▲                                   ▲
              │   └────────── notify(event) ──────────┘
              │
              └──────────────── notify(event) ───────► Observer B
```

## Participants

-   **Subject:** Source of truth that emits changes.
    
-   **Observer:** Consumer reacting to changes (updates view, caches, logs).
    
-   **Event/Message:** (Optional) Encapsulation of change details.
    
-   **Subscription:** Handle for lifecycle control (unsubscribing, once-only).
    

## Collaboration

1.  Observer subscribes to Subject.
    
2.  Subject state changes (method call, timer, I/O).
    
3.  Subject **notifies** all observers (pushes event/state).
    
4.  Observers react (render, compute, chain).
    
5.  Observers may unsubscribe (lifecycle/end of screen).
    

## Consequences

**Benefits**

-   Looser coupling; subjects don’t depend on concrete observers.
    
-   Natural fit for UI refresh and reactive data flows.
    
-   Extensible—new observers attach without changing subject code.
    

**Liabilities**

-   **Memory leaks:** Forgotten subscriptions keep views alive.
    
-   **Notification storms:** N² effects; need debouncing/batching.
    
-   **Ordering/re-entrancy:** Cascading updates if observers mutate subject.
    
-   **Error handling:** One faulty observer can break synchronous loops.
    
-   **Threading concerns:** Cross-thread updates in GUIs must marshal to UI thread.
    

## Implementation

**Guidelines**

1.  **Contract:** Define clear semantics (sync vs. async, ordering guarantees, error handling).
    
2.  **Thread safety:** Use concurrent collections; marshal to UI thread when needed.
    
3.  **Lifecycle:** Provide `Subscription` with `unsubscribe()`; support weak listeners if appropriate.
    
4.  **Granularity:** Prefer event objects over “pull latest from subject” when changes are specific.
    
5.  **Backpressure:** If emissions can outpace observers, consider queues or reactive libraries (Project Reactor/RxJava).
    
6.  **Batching/Debounce:** Reduce redundant UI work on rapid sequences.
    
7.  **Exception isolation:** Catch exceptions per observer to avoid poisoning the loop.
    
8.  **Testing:** Verify that a change triggers exactly the expected observer calls, once.
    

---

## Sample Code (Java — Minimal, Thread-Safe Observer)

This example shows a **thread-safe Subject** using `CopyOnWriteArrayList`, a **Subscription** for lifecycle control, and an **Event** payload. A simple **StockTicker** subject notifies multiple observers (console view, moving-average calculator).

```java
// src/main/java/com/example/observer/Event.java
package com.example.observer;

import java.time.Instant;
import java.util.Map;

public record Event(String type, Instant timestamp, Map<String, Object> data) {
    public static Event of(String type, Map<String,Object> data) {
        return new Event(type, Instant.now(), Map.copyOf(data));
    }
}
```

```java
// src/main/java/com/example/observer/Observer.java
package com.example.observer;

@FunctionalInterface
public interface Observer {
    void onEvent(Event event);
}
```

```java
// src/main/java/com/example/observer/Subscription.java
package com.example.observer;

public interface Subscription extends AutoCloseable {
    void unsubscribe();
    @Override default void close() { unsubscribe(); }
}
```

```java
// src/main/java/com/example/observer/Subject.java
package com.example.observer;

import java.util.List;
import java.util.Objects;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.function.Predicate;

public class Subject {
    private final List<Observer> observers = new CopyOnWriteArrayList<>();
    private final Predicate<Observer> allow; // optional filter/hook

    public Subject() { this(o -> true); }
    public Subject(Predicate<Observer> allow) { this.allow = allow; }

    public Subscription subscribe(Observer observer) {
        Objects.requireNonNull(observer, "observer");
        if (allow.test(observer)) observers.add(observer);
        return () -> observers.remove(observer);
    }

    public void publish(Event event) {
        for (Observer o : observers) {
            try { o.onEvent(event); }
            catch (RuntimeException ex) {
                // isolate observer failures
                System.err.println("Observer error: " + ex.getMessage());
            }
        }
    }

    public int observerCount() { return observers.size(); }
}
```

```java
// src/main/java/com/example/observer/StockTicker.java
package com.example.observer;

import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;

public class StockTicker {
    private final Subject subject = new Subject();

    public Subscription subscribe(Observer o) { return subject.subscribe(o); }

    // Simulate a tick
    public void tick(String symbol, double lastPrice) {
        double change = ThreadLocalRandom.current().nextDouble(-0.5, 0.5);
        double price = Math.max(0.01, lastPrice + change);
        subject.publish(Event.of("price.tick", Map.of(
                "symbol", symbol,
                "price", price
        )));
    }

    // Convenience for external publishers
    public void publishManual(String symbol, double price) {
        subject.publish(Event.of("price.tick", Map.of("symbol", symbol, "price", price)));
    }
}
```

```java
// src/main/java/com/example/observer/Demo.java
package com.example.observer;

import java.util.ArrayDeque;
import java.util.Deque;

public class Demo {
    public static void main(String[] args) throws Exception {
        StockTicker ticker = new StockTicker();

        // Observer 1: Console view
        Subscription s1 = ticker.subscribe(e -> {
            String symbol = (String) e.data().get("symbol");
            double price = (double) e.data().get("price");
            System.out.printf("[%s] %s: %.2f%n", e.timestamp(), symbol, price);
        });

        // Observer 2: 5-tick moving average calculator
        Subscription s2 = ticker.subscribe(new MovingAverage("ACME", 5)::onEvent);

        // Emit some ticks
        double price = 100.0;
        for (int i = 0; i < 8; i++) {
            ticker.tick("ACME", price);
            Thread.sleep(50);
        }

        // Unsubscribe console, keep MA running
        s1.unsubscribe();
        for (int i = 0; i < 4; i++) {
            ticker.tick("ACME", price);
            Thread.sleep(50);
        }

        // Clean up
        s2.close();
    }

    // Helper Observer
    static class MovingAverage {
        private final String symbol;
        private final int window;
        private final Deque<Double> values = new ArrayDeque<>();
        private double sum = 0;

        MovingAverage(String symbol, int window) {
            this.symbol = symbol; this.window = window;
        }

        void onEvent(Event e) {
            if (!"price.tick".equals(e.type())) return;
            if (!symbol.equals(e.data().get("symbol"))) return;
            double p = (double) e.data().get("price");
            values.addLast(p); sum += p;
            if (values.size() > window) sum -= values.removeFirst();
            double avg = sum / values.size();
            System.out.printf("MA(%d) %s = %.2f%n", window, symbol, avg);
        }
    }
}
```

**Notes on the sample**

-   `Subject.publish` isolates observer failures so one bad listener doesn’t break the chain.
    
-   `Subscription` allows explicit unsubscription (important for UI lifecycles).
    
-   For GUI frameworks, marshal `Observer.onEvent` to the UI thread (e.g., `Platform.runLater` in JavaFX or `SwingUtilities.invokeLater`).
    

---

## Known Uses

-   **Java UI toolkits:** Swing/AWT listeners, JavaFX properties/observables.
    
-   **Android:** `LiveData`, `Flow/StateFlow` (reactive observers on lifecycle-aware owners).
    
-   **Web UIs:** DOM events, RxJS observables, custom event emitters.
    
-   **Desktop apps:** Property change events (`PropertyChangeSupport`).
    
-   **Reactive libraries:** RxJava, Project Reactor (Observer at scale with operators/backpressure).
    
-   **Framework internals:** Template engines, cache invalidation, logging appenders.
    

## Related Patterns

-   **Mediator:** Centralizes communications; Observer fans out changes.
    
-   **Publish–Subscribe:** Observer with a broker/topic layer (loosely coupled).
    
-   **Event Sourcing / CQRS:** System-wide event logs; observers project read models.
    
-   **Model–View–Controller / MVVM / MVP:** UIs observe models or view-models for rendering.
    
-   **Reactor/Reactive Streams:** Formalize async sequences with backpressure.

