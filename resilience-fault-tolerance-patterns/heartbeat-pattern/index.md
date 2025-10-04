# Heartbeat — Resilience and Fault Tolerance Pattern

## Pattern Name and Classification

**Name:** Heartbeat  
**Category:** Resilience & Fault Tolerance · Monitoring & Health Patterns · Communication Reliability

## Intent

Enable **continuous monitoring of system liveness and connectivity** by periodically sending “heartbeat” messages or signals from one component (the sender) to another (the monitor or observer). The heartbeat ensures that systems can detect failures or unresponsiveness early, triggering fallback or recovery mechanisms automatically.

## Also Known As

Liveness Probe · Keep-Alive Signal · Watchdog Timer · Health Ping

## Motivation (Forces)

-   **Unreliable networks and distributed systems** require a way to confirm that nodes or services are still responsive.
    
-   **Early detection of failures** allows proactive recovery and failover instead of waiting for timeouts.
    
-   **Load balancing, orchestration, and clustering** rely on heartbeat signals to track active nodes.
    
-   **Monitoring precision:** Overly frequent heartbeats waste resources; too infrequent heartbeats delay failure detection.
    
-   **Trade-offs:** Balancing accuracy, network load, and false positives.
    

## Applicability

Use Heartbeat when:

-   Multiple components or services communicate across unreliable networks.
    
-   You need to monitor **system availability**, **cluster node health**, or **client liveness**.
    
-   Systems require **automatic failover** or **leader election** based on active participants.
    
-   Components depend on **external dependencies** (e.g., database, message broker) that must be health-checked periodically.
    

Avoid or adapt when:

-   The environment already provides health metrics (e.g., managed cloud services with built-in probes).
    
-   Network constraints make frequent pings costly.
    
-   One-time connections (stateless APIs) can rely on timeouts rather than continuous heartbeats.
    

## Structure

-   **Heartbeat Sender (Emitter):** Periodically sends signals (“I am alive”) to the receiver or monitoring service.
    
-   **Heartbeat Receiver (Monitor):** Receives signals and tracks last-seen timestamps.
    
-   **Timeout Detector:** Flags nodes as “unhealthy” or “offline” if no heartbeat is received within the threshold.
    
-   **Recovery/Failover Handler:** Takes corrective action (restart service, reassign leader, alert operator).
    

```pgsql
┌────────────────┐     send heartbeat      ┌──────────────────┐
     │  Sender Node   │ ──────────────────────► │   Monitor Node   │
     │  (Producer)    │                        │ (Receiver/Watcher)│
     └────────────────┘ ◄───────────────────────┘
             ▲              ACK or status update
             │
   Timeout → Restart / Alert / Reassign
```

## Participants

-   **Heartbeat Sender:** Periodically emits heartbeat signals or health pings.
    
-   **Monitor/Receiver:** Records last received timestamp for each sender.
    
-   **Timeout Manager:** Periodically checks for missed heartbeats.
    
-   **Recovery Handler:** Executes remediation (restart node, remove from pool, trigger alert).
    
-   **Communication Channel:** Typically HTTP, TCP, UDP, or message queue.
    

## Collaboration

1.  **Sender** initializes a scheduled job that emits heartbeat messages at a fixed interval.
    
2.  **Receiver** accepts these messages and updates an internal “last-seen” timestamp map.
    
3.  A **monitoring thread** checks each sender’s last heartbeat time.
    
4.  If a sender exceeds the configured threshold, it’s marked as **unhealthy** or **offline**.
    
5.  **Recovery actions** (alert, restart, failover) are triggered automatically.
    

## Consequences

**Benefits**

-   Enables **early fault detection** in distributed systems.
    
-   Supports **automatic failover and recovery**.
    
-   Provides **visibility** into component availability.
    
-   Reduces downtime by proactive remediation.
    

**Liabilities**

-   **False positives:** Temporary network latency can cause false failure detection.
    
-   **Overhead:** Frequent heartbeats consume bandwidth and CPU cycles.
    
-   **Synchronization issues:** Clock drift can cause inaccurate timeouts.
    
-   **Scalability concerns:** Monitoring thousands of nodes requires efficient aggregation.
    

## Implementation

**Guidelines**

1.  **Choose interval wisely:** Short intervals increase responsiveness but add overhead.
    
2.  **Use configurable thresholds:** Allow tuning of missed-heartbeat tolerance.
    
3.  **Leverage monotonic time:** Avoid system clock drift using monotonic timestamps.
    
4.  **Decouple communication:** Use async protocols (e.g., message queues) to reduce coupling.
    
5.  **Security:** Authenticate heartbeat messages to prevent spoofing.
    
6.  **Aggregate monitoring:** For large clusters, aggregate node health via a distributed store or monitoring service.
    
7.  **Testing:** Simulate latency, dropped packets, and delayed heartbeats to test recovery logic.
    

---

## Sample Code (Java — Heartbeat Monitor using ScheduledExecutorService)

This example demonstrates a **simple heartbeat pattern** between nodes and a monitoring component using scheduled tasks.

```java
// src/main/java/com/example/heartbeat/HeartbeatMessage.java
package com.example.heartbeat;

public record HeartbeatMessage(String nodeId, long timestamp) {}
```

```java
// src/main/java/com/example/heartbeat/HeartbeatSender.java
package com.example.heartbeat;

import java.util.concurrent.*;
import java.util.function.Consumer;

public class HeartbeatSender {
    private final String nodeId;
    private final ScheduledExecutorService scheduler = Executors.newSingleThreadScheduledExecutor();
    private final Consumer<HeartbeatMessage> sendFunction;
    private final long intervalMs;

    public HeartbeatSender(String nodeId, long intervalMs, Consumer<HeartbeatMessage> sendFunction) {
        this.nodeId = nodeId;
        this.intervalMs = intervalMs;
        this.sendFunction = sendFunction;
    }

    public void start() {
        scheduler.scheduleAtFixedRate(() ->
            sendFunction.accept(new HeartbeatMessage(nodeId, System.currentTimeMillis())),
            0, intervalMs, TimeUnit.MILLISECONDS);
    }

    public void stop() {
        scheduler.shutdownNow();
    }
}
```

```java
// src/main/java/com/example/heartbeat/HeartbeatMonitor.java
package com.example.heartbeat;

import java.util.*;
import java.util.concurrent.*;

public class HeartbeatMonitor {
    private final ConcurrentMap<String, Long> lastSeen = new ConcurrentHashMap<>();
    private final ScheduledExecutorService scheduler = Executors.newSingleThreadScheduledExecutor();
    private final long timeoutMs;

    public HeartbeatMonitor(long timeoutMs) {
        this.timeoutMs = timeoutMs;
    }

    public void receive(HeartbeatMessage msg) {
        lastSeen.put(msg.nodeId(), msg.timestamp());
        System.out.printf("[Monitor] Received heartbeat from %s at %d%n", msg.nodeId(), msg.timestamp());
    }

    public void startMonitoring() {
        scheduler.scheduleAtFixedRate(this::checkNodes, timeoutMs, timeoutMs, TimeUnit.MILLISECONDS);
    }

    private void checkNodes() {
        long now = System.currentTimeMillis();
        for (var entry : lastSeen.entrySet()) {
            if (now - entry.getValue() > timeoutMs) {
                System.err.printf("[ALERT] Node %s missed heartbeat! (Last seen %d ms ago)%n",
                        entry.getKey(), now - entry.getValue());
            }
        }
    }

    public void stop() {
        scheduler.shutdownNow();
    }
}
```

```java
// src/main/java/com/example/heartbeat/HeartbeatDemo.java
package com.example.heartbeat;

public class HeartbeatDemo {
    public static void main(String[] args) throws Exception {
        HeartbeatMonitor monitor = new HeartbeatMonitor(3000);
        monitor.startMonitoring();

        HeartbeatSender senderA = new HeartbeatSender("node-A", 1000, monitor::receive);
        HeartbeatSender senderB = new HeartbeatSender("node-B", 1000, monitor::receive);

        senderA.start();
        senderB.start();

        // Simulate runtime (node-B stops after a while)
        Thread.sleep(8000);
        System.out.println("Simulating node-B failure...");
        senderB.stop();

        // Continue monitoring node-A
        Thread.sleep(8000);

        senderA.stop();
        monitor.stop();
    }
}
```

**Behavior:**

-   Two senders (`node-A` and `node-B`) emit heartbeats every second.
    
-   The monitor checks if any node missed heartbeats beyond 3 seconds.
    
-   When `node-B` stops, an alert is printed after the timeout window.
    

**Output (example):**

```css
[Monitor] Received heartbeat from node-A at 1696400123012
[Monitor] Received heartbeat from node-B at 1696400123013
...
Simulating node-B failure...
[ALERT] Node node-B missed heartbeat! (Last seen 4500 ms ago)
```

---

## Known Uses

-   **Cluster managers:** Kubernetes liveness probes, Docker Swarm node heartbeats.
    
-   **Databases:** Cassandra, ZooKeeper, and Consul use heartbeats to track membership.
    
-   **Load balancers:** ELB and HAProxy health checks.
    
-   **IoT devices:** Remote sensors send heartbeats to cloud gateways.
    
-   **Message brokers:** RabbitMQ and Kafka track producer/consumer liveness via heartbeats.
    
-   **Distributed caches:** Hazelcast and Redis cluster membership detection.
    

## Related Patterns

-   **Health Check:** Broader health validation including dependencies and metrics.
    
-   **Circuit Breaker:** Temporarily disables communication with unresponsive services; may use heartbeat for recovery.
    
-   **Failover / Leader Election:** Relies on heartbeat absence to detect leader failure.
    
-   **Watchdog Timer:** Local variant monitoring process threads instead of remote nodes.
    
-   **Retry / Timeout Pattern:** Often used together to ensure robust request handling.

