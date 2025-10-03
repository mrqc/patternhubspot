
# Data Management & Database Pattern — Transactional Outbox

## Pattern Name and Classification

-   **Name:** Transactional Outbox

-   **Classification:** Reliable integration & messaging pattern (atomic write of state change and message using a single local database transaction)


## Intent

Ensure that **domain state changes** and the corresponding **integration messages/events** are **persisted atomically** in the **same database transaction**. A separate **relay** process reads the outbox and publishes to a message broker (or other targets) **reliably**, providing *exactly-once–ish* delivery via **at-least-once publish + idempotent consumers**.

## Also Known As

-   Outbox Pattern

-   Reliable Event Publication

-   Transactional Messaging (local transaction, not distributed XA)


## Motivation (Forces)

-   **Dual-write problem:** Writing to a DB and a broker in separate steps can lose messages or create ghosts (message without state).

-   **Avoid XA/2PC:** Global transactions are slow/complex or simply unavailable in modern stacks.

-   **Operational reality:** Publishers crash, brokers are transiently unavailable; we need **retries** and **recovery**.

-   **Traceability:** We want an **auditable log** of what was intended to be published.


## Applicability

Use the Transactional Outbox when:

-   A service **owns** a database and needs to **notify** other systems of changes (events/commands/integration messages).

-   You can tolerate **eventual consistency** between write and publish (milliseconds/seconds).

-   Consumers can be made **idempotent** (recommended, often mandatory).


Be cautious when:

-   Hard requirements demand **synchronous** cross-system atomicity (consider 2PC/TCC with care).

-   Throughput is so high that DB writes become the bottleneck (use batching/partitioning or log-based CDC).


## Structure

```pgsql
+---------------------+     (same local TX)      +--------------------+
  |  Service / Handler  | -----------------------> |  Domain Tables     |
  |  (Command arrives)  |                          +--------------------+
  |                     | -----------------------> |  OUTBOX table      |
  +---------------------+                          +--------------------+
           |                                                 |
           |                                         polling/streaming
           v                                                 v
  +---------------------+   publish (at-least-once)  +-------------------+
  |  Outbox Relay       | -------------------------> |  Broker/Target    |
  |  (retries/backoff)  |                           +-------------------+
           |
           +--> marks sent / schedules retry
```

## Participants

-   **Domain/Command Handler:** Executes business logic and writes domain state.

-   **Outbox Table:** Durable table holding messages/events created *in the same transaction*.

-   **Relay (Publisher):** Background process that reads unsent outbox records, publishes, and marks them as sent (with retries & backoff).

-   **Broker / Target:** Kafka, RabbitMQ, SNS/SQS, HTTP endpoint, search index, etc.

-   **Consumers:** Downstream services that must be **idempotent**; often store a **dedupe key/offset**.


## Collaboration

1.  Handler performs domain updates and inserts a row into **outbox** (same DB transaction).

2.  Relay polls the outbox (FIFO-ish), publishes each message.

3.  On success, relay **marks sent**; on failure, increments **attempts** and computes **next\_attempt\_at** with backoff.

4.  Consumers apply **idempotently** (dedupe by message ID), enabling at-least-once upstream.


## Consequences

**Benefits**

-   **Atomicity without XA:** No lost/phantom messages vs dual-write.

-   **Operable:** Replay, dead-letter, inspect outbox rows.

-   **Portable:** Works with any DB and broker.


**Liabilities**

-   **Eventual consistency:** Messages appear *after* commit.

-   **Throughput limits:** DB I/O for outbox can become hot; mitigate with batching/partitions.

-   **Ordering:** Strict global ordering isn’t guaranteed (per-aggregate ordering is typical).

-   **Cleanup:** Requires compaction/TTL or archive of sent rows.


## Implementation (Key Points)

-   **Outbox schema:** include `id (UUID)`, `aggregate_type`, `aggregate_id`, `event_type`, `payload (JSON)`, `created_at`, `status`, `attempts`, `next_attempt_at`, `trace_id`.

-   **Insert outbox row in same TX** as domain writes; use your ORM’s transaction boundary or JDBC.

-   **Relay**:

    -   query **due** rows (`status='PENDING' AND next_attempt_at <= now()`),

    -   publish with **retries** and **exponential backoff + jitter**,

    -   **mark sent** in a small transaction.

-   **Idempotency:**

    -   Publisher can retry; consumers dedupe by `message_id` (store processed IDs).

    -   When publishing to Kafka, use `message_id` as key; consumer stores it in a **processed table**.

-   **Failure handling:**

    -   Move stuck rows to **dead-letter** after N attempts.

    -   Alert on growing backlog/age.

-   **Scaling:**

    -   Partition outbox table (e.g., by day) or keep multiple **logical queues** via a `topic` column.

    -   Shard relay workers by hash-range on `id`/`aggregate_id`.

-   **Alternative feed:**

    -   **CDC** (Debezium) can read the outbox table and publish to Kafka—no custom relay code.

-   **Observability:** expose metrics: lag (oldest PENDING age), publish rate, attempts, DLQ count.


---

## Sample Code (Java 17 + JDBC/H2): Atomic Write + Outbox Relay (with backoff & idempotent consumer)

> Self-contained demo (no external broker).
>
> -   **OrderService** inserts into `orders` and **outbox** in the *same transaction*.
>
> -   **OutboxRelay** polls and publishes to a mock **MessageBus**.
>
> -   **InventoryConsumer** is **idempotent** (dedupes by `message_id`).
>

```java
// File: TransactionalOutboxDemo.java
// Compile: javac -cp h2.jar TransactionalOutboxDemo.java
// Run:     java  -cp .:h2.jar TransactionalOutboxDemo
import java.sql.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/* ---------- Mock Message Bus (in-memory) ---------- */
interface MessageBus {
  void publish(String topic, String key, String payload) throws Exception;
  void register(String topic, MessageHandler h);
  interface MessageHandler { void onMessage(String key, String payload) throws Exception; }
}

/** Simple in-memory bus that invokes handlers synchronously (success throws = publish failure). */
final class InMemoryBus implements MessageBus {
  private final Map<String, MessageHandler> handlers = new ConcurrentHashMap<>();
  @Override public void publish(String topic, String key, String payload) throws Exception {
    var h = handlers.get(topic);
    if (h != null) h.onMessage(key, payload); // may throw to simulate failure
  }
  @Override public void register(String topic, MessageHandler h) { handlers.put(topic, h); }
}

/* ---------- Outbox Relay ---------- */
final class OutboxRelay implements AutoCloseable {
  private final ConnectionFactory cf;
  private final MessageBus bus;
  private final ScheduledExecutorService exec = Executors.newSingleThreadScheduledExecutor();
  private final AtomicBoolean running = new AtomicBoolean(false);
  private final String topic;

  OutboxRelay(ConnectionFactory cf, MessageBus bus, String topic) {
    this.cf = cf; this.bus = bus; this.topic = topic;
  }

  public void start() {
    if (running.compareAndSet(false, true)) {
      exec.scheduleWithFixedDelay(this::tick, 0, 100, TimeUnit.MILLISECONDS);
    }
  }

  private void tick() {
    if (!running.get()) return;
    try (Connection cx = cf.get()) {
      cx.setAutoCommit(false);
      // Fetch a small batch of due messages (FOR UPDATE SKIP LOCKED to avoid contention in real DBs)
      try (PreparedStatement ps = cx.prepareStatement("""
          SELECT id, aggregate_type, aggregate_id, event_type, payload, attempts
          FROM outbox
          WHERE status='PENDING' AND next_attempt_at <= CURRENT_TIMESTAMP
          ORDER BY created_at
          LIMIT 10
        """, ResultSet.TYPE_FORWARD_ONLY, ResultSet.CONCUR_UPDATABLE)) {
        try (ResultSet rs = ps.executeQuery()) {
          while (rs.next()) {
            String id = rs.getString("id");
            String key = id; // use message id as key for idempotency
            String payload = rs.getString("payload");
            int attempts = rs.getInt("attempts");
            boolean ok = false;
            try {
              bus.publish(topic, key, payload); // may throw
              ok = true;
            } catch (Exception e) {
              // publish failed; schedule retry with exponential backoff + jitter
              attempts++;
              Duration backoff = Duration.ofMillis((long)(Math.min(30_000,
                                 200 * Math.pow(2, Math.min(attempts-1, 7))))); // cap
              long jitter = ThreadLocalRandom.current().nextLong(50, 200);
              try (PreparedStatement upd = cx.prepareStatement("""
                    UPDATE outbox
                      SET attempts=?, next_attempt_at = DATEADD('MILLISECOND', ?, CURRENT_TIMESTAMP)
                    WHERE id=?
                  """)) {
                upd.setInt(1, attempts);
                upd.setLong(2, backoff.toMillis() + jitter);
                upd.setString(3, id);
                upd.executeUpdate();
              }
            }
            if (ok) {
              try (PreparedStatement upd = cx.prepareStatement("""
                    UPDATE outbox SET status='SENT', sent_at=CURRENT_TIMESTAMP WHERE id=?
                  """)) {
                upd.setString(1, id);
                upd.executeUpdate();
              }
            }
          }
        }
      }
      cx.commit();
    } catch (Exception e) {
      // log and continue; next tick will retry
      System.out.println("[relay] error: " + e.getMessage());
    }
  }

  @Override public void close() {
    running.set(false);
    exec.shutdownNow();
  }
}

/* ---------- Order service: domain write + outbox in same TX ---------- */
final class OrderService {
  private final ConnectionFactory cf;
  OrderService(ConnectionFactory cf) { this.cf = cf; }

  public void placeOrder(long orderId, String sku, int qty) throws Exception {
    try (Connection cx = cf.get()) {
      cx.setAutoCommit(false);
      // Domain change
      try (PreparedStatement ins = cx.prepareStatement("""
            INSERT INTO orders(id, sku, qty, status, created_at) VALUES(?,?,?,?, CURRENT_TIMESTAMP)
          """)) {
        ins.setLong(1, orderId);
        ins.setString(2, sku);
        ins.setInt(3, qty);
        ins.setString(4, "CREATED");
        ins.executeUpdate();
      }
      // Outbox message (same TX) — event type + JSON payload
      String msgId = UUID.randomUUID().toString();
      String payload = """
        {"messageId":"%s","type":"OrderCreated","orderId":%d,"sku":"%s","qty":%d}
        """.formatted(msgId, orderId, sku, qty);
      try (PreparedStatement ob = cx.prepareStatement("""
            INSERT INTO outbox(id, aggregate_type, aggregate_id, event_type, payload,
                               status, attempts, next_attempt_at, created_at)
            VALUES(?,?,?,?,?,'PENDING',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
          """)) {
        ob.setString(1, msgId);
        ob.setString(2, "Order");
        ob.setString(3, Long.toString(orderId));
        ob.setString(4, "OrderCreated");
        ob.setString(5, payload);
        ob.executeUpdate();
      }
      cx.commit(); // both domain row and outbox row commit atomically
    }
  }
}

/* ---------- Idempotent consumer that processes messages once ---------- */
final class InventoryConsumer implements MessageBus.MessageHandler {
  private final ConnectionFactory cf;
  InventoryConsumer(ConnectionFactory cf) { this.cf = cf; }

  @Override public void onMessage(String key, String payload) throws Exception {
    // key == messageId; use it to dedupe (idempotent consumer)
    try (Connection cx = cf.get()) {
      cx.setAutoCommit(false);
      // If already processed, do nothing
      try (PreparedStatement ck = cx.prepareStatement("""
            SELECT 1 FROM processed_message WHERE id = ? FOR UPDATE
          """)) {
        ck.setString(1, key);
        try (ResultSet rs = ck.executeQuery()) {
          if (rs.next()) { cx.commit(); return; }
        }
      }
      // Simulate business side effect (reserve stock)
      Map<String,String> kv = parse(payload);
      String sku = kv.get("sku");
      int qty = Integer.parseInt(kv.get("qty"));
      try (PreparedStatement upd = cx.prepareStatement("""
            MERGE INTO stock s KEY(sku)
            VALUES(?, COALESCE((SELECT s.qty FROM stock s2 WHERE s2.sku=?), 100) - ?)
          """)) {
        upd.setString(1, sku);
        upd.setString(2, sku);
        upd.setInt(3, qty);
        upd.executeUpdate();
      }
      // Mark processed
      try (PreparedStatement ins = cx.prepareStatement("""
            INSERT INTO processed_message(id, processed_at) VALUES(?, CURRENT_TIMESTAMP)
          """)) {
        ins.setString(1, key);
        ins.executeUpdate();
      }
      cx.commit();
    }
  }

  // Tiny JSON-ish parser for demo (payload is simple flat JSON)
  private static Map<String,String> parse(String json) {
    Map<String,String> m = new HashMap<>();
    for (String p : json.replaceAll("[\\{\\}\"]","").split(",")) {
      String[] kv = p.split(":",2);
      if (kv.length==2) m.put(kv[0].trim(), kv[1].trim());
    }
    return m;
  }
}

/* ---------- DB bootstrapping ---------- */
final class Schema {
  static void create(Connection cx) throws SQLException {
    try (Statement st = cx.createStatement()) {
      st.execute("""
        CREATE TABLE orders(
          id BIGINT PRIMARY KEY,
          sku VARCHAR(64) NOT NULL,
          qty INT NOT NULL,
          status VARCHAR(32) NOT NULL,
          created_at TIMESTAMP NOT NULL
        );
      """);
      st.execute("""
        CREATE TABLE outbox(
          id VARCHAR(36) PRIMARY KEY,
          aggregate_type VARCHAR(64) NOT NULL,
          aggregate_id   VARCHAR(64) NOT NULL,
          event_type     VARCHAR(64) NOT NULL,
          payload        CLOB NOT NULL,
          status         VARCHAR(16) NOT NULL, -- PENDING | SENT | DEAD
          attempts       INT NOT NULL,
          next_attempt_at TIMESTAMP NOT NULL,
          created_at     TIMESTAMP NOT NULL,
          sent_at        TIMESTAMP
        );
      """);
      // For consumers' idempotency
      st.execute("""
        CREATE TABLE processed_message(
          id VARCHAR(36) PRIMARY KEY,
          processed_at TIMESTAMP NOT NULL
        );
      """);
      st.execute("CREATE TABLE stock(sku VARCHAR(64) PRIMARY KEY, qty INT NOT NULL);");
      st.execute("INSERT INTO stock(sku, qty) VALUES('BOOK-1', 100), ('PEN-1', 100);");
      // Helpful index to scan pending rows quickly
      st.execute("CREATE INDEX ix_outbox_pending ON outbox(status, next_attempt_at, created_at);");
    }
  }
}

@FunctionalInterface interface ConnectionFactory { Connection get() throws SQLException; }

/* ---------- Demo main ---------- */
public class TransactionalOutboxDemo {
  public static void main(String[] args) throws Exception {
    ConnectionFactory cf = () -> DriverManager.getConnection("jdbc:h2:mem:outbox;DB_CLOSE_DELAY=-1");
    try (Connection cx = cf.get()) { cx.setAutoCommit(true); Schema.create(cx); }

    InMemoryBus bus = new InMemoryBus();
    // Register idempotent consumer
    bus.register("inventory", new InventoryConsumer(cf));

    OutboxRelay relay = new OutboxRelay(cf, bus, "inventory");
    relay.start();

    OrderService svc = new OrderService(cf);

    // Place a couple of orders (domain write + outbox in same TX)
    svc.placeOrder(1L, "BOOK-1", 2);
    svc.placeOrder(2L, "PEN-1", 5);

    // Wait for relay to publish & consumer to process
    Thread.sleep(500);

    // Show results
    try (Connection cx = cf.get()) {
      try (Statement st = cx.createStatement();
           ResultSet rs = st.executeQuery("SELECT sku, qty FROM stock ORDER BY sku")) {
        System.out.println("Stock after reservations:");
        while (rs.next()) System.out.printf(" - %s -> %d%n", rs.getString(1), rs.getInt(2));
      }
      try (Statement st = cx.createStatement();
           ResultSet rs = st.executeQuery("SELECT status, COUNT(*) FROM outbox GROUP BY status")) {
        System.out.println("Outbox status counts:");
        while (rs.next()) System.out.printf(" - %s: %d%n", rs.getString(1), rs.getInt(2));
      }
    }

    relay.close();
  }
}
```

**What this demonstrates**

-   **Atomicity:** Domain row and outbox row are created in the same commit.

-   **Relay with backoff:** Retries failed publishes and only marks **SENT** on success.

-   **Idempotent consumer:** Deduplicates by `message_id`, allowing at-least-once delivery upstream.

-   **Operability:** You can query the `outbox` table to observe backlog and status.


---

## Known Uses

-   **Microservices integration:** Emit domain events (OrderCreated, UserUpdated) after local commits.

-   **Search indexing / read models:** Publish change events to update Elasticsearch, caches, or projections.

-   **Email/notification pipelines:** Queue notifications atomically with the state that triggered them.

-   **CDC-powered outbox:** Debezium Outbox pattern to Kafka; consumers subscribe to topics.


## Related Patterns

-   **CDC (Change Data Capture):** Alternative transport—stream the outbox table or domain tables.

-   **Saga / Process Manager:** Sagas often rely on outbox to emit commands/events reliably.

-   **CQRS / Read Models:** Outbox is the reliable source feeding read models.

-   **Idempotent Consumer / Exactly-once-ish:** Consumer-side dedupe to complement at-least-once publish.

-   **Inbox Pattern:** Store processed message IDs to make handlers idempotent (shown as `processed_message`).

-   **Event Sourcing:** Outbox can be derived from an event store or vice versa.


---

### Practical Tips

-   **Per-aggregate ordering:** include `(aggregate_id, created_at)` and process in that order for a given key; use Kafka partitioning by `aggregate_id`.

-   **Batching:** Relay should publish in batches and update statuses in bulk to reduce DB round trips.

-   **Backpressure:** Pause relay when broker is down; monitor **oldest pending age** and **attempts**.

-   **Compaction:** Periodically **archive or delete SENT** rows (partitioned outbox or TTL).

-   **Tracing:** Store `trace_id` and propagate to message headers for end-to-end observability.

-   **Security & PII:** Keep payloads minimal or encrypted; outbox often has wider access.

-   **Failover safety:** Use `SKIP LOCKED`/`FOR UPDATE` where available to avoid double-pick with multiple relays.

-   **Schema evolution:** Version event payloads; consumers should tolerate additive fields.
