
# Data Management & Database Pattern — Time-Travel Table

## Pattern Name and Classification

-   **Name:** Time-Travel Table

-   **Classification:** Data versioning & auditability pattern (query state **as of** a past point in time)


## Intent

Keep historical versions of rows so you can **query a table at any point in time** (“as of” queries), **audit changes**, recover from errors, and reproduce past analytics.

## Also Known As

-   System-Versioned Table (SQL:2011 Temporal)

-   Temporal Table / Auditable Table

-   Time-Travel (in lakehouse formats)

-   Bitemporal Table (when modeling **valid time** and **transaction time**)


## Motivation (Forces)

-   **Auditability & forensics:** Who changed what and when?

-   **Reproducibility:** Re-run reports as they were at a past close.

-   **Safety:** Undo mistakes by reading/writing from the last known good state.

-   **Slowly Changing Dimensions:** Keep history without ETL copies.


**Tensions**

-   **Storage & write cost:** Keeping history increases space and write amplification.

-   **Query complexity:** Must think in “as-of” semantics.

-   **Retention/GDPR:** You must eventually purge or anonymize history.


## Applicability

Use time-travel tables when:

-   Regulations or business require **complete history** and **point-in-time** reconstruction.

-   Analytics need to answer “what did we know **then**?”

-   Debugging/RCAs must see prior states reliably.


Be cautious when:

-   Data is extremely write-hot and history volume explodes.

-   You cannot store history for privacy/legal reasons (apply **retention windows** or **hard deletes**).


## Structure

```pgsql
+---------------------------+
Writes  ----->|  Temporal Table (current) |<-----+
              +---------------------------+      |
                 ▲  maintains history            |  FOR SYSTEM_TIME AS OF t0/t1
                 |                                \
                 | (system records row versions)    \-->  Point-in-time queries
                 v
          Historical Versions (hidden history table / change log)
```

**Variants**

-   **System time only** (transaction time): the DB records when a row version existed.

-   **Bitemporal**: add **valid-from / valid-to** to model the business validity period (e.g., contract effective dates).


## Participants

-   **Temporal Table:** Holds the current row and (implicitly/externally) all prior versions.

-   **History Store:** Internal history table, change log, or versioned files (Delta/Iceberg/Hudi).

-   **Time Travel Query Mechanism:** SQL `FOR SYSTEM_TIME AS OF`, or snapshot/version selectors in lakehouses.

-   **Retention/Compaction Job:** Prunes old versions under policy.


## Collaboration

1.  Application executes normal **INSERT/UPDATE/DELETE**.

2.  The engine automatically writes **previous versions** to history with timestamps (or version IDs).

3.  Readers issue **as-of** queries to reconstruct state at a given instant or version.

4.  Retention processes **purge/compact** old versions per policy.


## Consequences

**Benefits**

-   Perfect **audit trail** and **point-in-time** analytics.

-   Simplifies **SCD Type-2** maintenance—no custom audit tables.

-   Enables **time-travel debugging** and **data recovery** without backups.


**Liabilities**

-   Extra **storage** and occasionally slower writes.

-   Query engine must support time-travel semantics (or you implement SCD yourself).

-   **Purge/anonymization** must consider history (and backups).


## Implementation (Key Points)

-   **Relational (SQL:2011 temporal):**

    -   Add **system columns** (row start/row end) and enable **SYSTEM VERSIONING**.

    -   Query with `FOR SYSTEM_TIME AS OF <timestamp>` (SQL Server, MariaDB, DB2, Oracle Flashback‐like, H2).

-   **Bitemporal:** Add business **valid\_from/valid\_to** and query with both time axes.

-   **Lakehouse (Delta Lake / Apache Iceberg / Hudi):**

    -   Use table **version** or **timestamp** selectors (`VERSION AS OF`, `TIMESTAMP AS OF`; or Iceberg snapshots).

    -   Compaction & retention manage file/version growth.

-   **Indexes:** Keep normal indexes on current data; some engines index history too.

-   **Retention:** Define **legal holds** vs **TTL**; cascade to history and backups.

-   **Access control:** History contains sensitive past values—secure it as strictly as current.


---

## Sample Code (Java 17 + JDBC/H2): System-Versioned Temporal Table with “AS OF” Queries

> **What it shows**
>
> -   Creates a **system-versioned** table with SQL:2011 temporal features (H2 syntax).
>
> -   Performs updates/deletes; DB keeps history automatically.
>
> -   Issues **point-in-time** queries using `FOR SYSTEM_TIME AS OF`.
>

```java
// File: TimeTravelTableDemo.java
// Compile: javac -cp h2.jar TimeTravelTableDemo.java
// Run:     java  -cp .:h2.jar TimeTravelTableDemo
import java.sql.*;
import java.time.*;
import java.util.concurrent.TimeUnit;

public class TimeTravelTableDemo {
  public static void main(String[] args) throws Exception {
    try (Connection cx = DriverManager.getConnection("jdbc:h2:mem:tt;DB_CLOSE_DELAY=-1")) {
      cx.setAutoCommit(false);
      try (Statement st = cx.createStatement()) {
        // SQL:2011-style system-versioned temporal table (H2 supports this syntax)
        st.execute("""
          CREATE TABLE accounts(
            id           BIGINT PRIMARY KEY,
            owner        VARCHAR(100) NOT NULL,
            balance_cents INT NOT NULL,
            sys_start    TIMESTAMP AS ROW START,
            sys_end      TIMESTAMP AS ROW END,
            PERIOD FOR SYSTEM_TIME (sys_start, sys_end)
          ) WITH SYSTEM VERSIONING;
        """);
      }
      cx.commit();

      // t0: initial insert
      Timestamp t0 = now(cx);
      insert(cx, 1, "Alice", 10_00);
      cx.commit();
      sleep();

      // t1: update balance
      Timestamp t1 = now(cx);
      updateBalance(cx, 1, 15_00);
      cx.commit();
      sleep();

      // t2: rename owner
      Timestamp t2 = now(cx);
      updateOwner(cx, 1, "Alice Müller");
      cx.commit();
      sleep();

      // t3: delete account
      Timestamp t3 = now(cx);
      delete(cx, 1);
      cx.commit();

      System.out.println("\n--- Point-in-time reads ---");
      queryAsOf(cx, "t0 (after insert)", t0);
      queryAsOf(cx, "t1 (after balance update)", t1);
      queryAsOf(cx, "t2 (after rename)", t2);
      queryAsOf(cx, "t3 (after delete) -> should show last version before delete", t3);

      System.out.println("\n--- Full history (current + past versions) ---");
      // H2 exposes history via FOR SYSTEM_TIME ALL
      try (PreparedStatement ps = cx.prepareStatement("""
        SELECT id, owner, balance_cents, sys_start, sys_end
        FROM accounts FOR SYSTEM_TIME ALL
        WHERE id = ?
        ORDER BY sys_start
      """)) {
        ps.setLong(1, 1L);
        try (ResultSet rs = ps.executeQuery()) {
          while (rs.next()) {
            System.out.printf("id=%d owner=%s balance=%.2f [%s .. %s)%n",
              rs.getLong(1), rs.getString(2), rs.getInt(3)/100.0,
              rs.getTimestamp(4).toInstant(), rs.getTimestamp(5).toInstant());
          }
        }
      }
    }
  }

  static void insert(Connection cx, long id, String owner, int cents) throws SQLException {
    try (PreparedStatement ps = cx.prepareStatement(
      "INSERT INTO accounts(id, owner, balance_cents) VALUES (?,?,?)")) {
      ps.setLong(1, id); ps.setString(2, owner); ps.setInt(3, cents); ps.executeUpdate();
    }
  }
  static void updateBalance(Connection cx, long id, int cents) throws SQLException {
    try (PreparedStatement ps = cx.prepareStatement(
      "UPDATE accounts SET balance_cents=? WHERE id=?")) {
      ps.setInt(1, cents); ps.setLong(2, id); ps.executeUpdate();
    }
  }
  static void updateOwner(Connection cx, long id, String owner) throws SQLException {
    try (PreparedStatement ps = cx.prepareStatement(
      "UPDATE accounts SET owner=? WHERE id=?")) {
      ps.setString(1, owner); ps.setLong(2, id); ps.executeUpdate();
    }
  }
  static void delete(Connection cx, long id) throws SQLException {
    try (PreparedStatement ps = cx.prepareStatement(
      "DELETE FROM accounts WHERE id=?")) {
      ps.setLong(1, id); ps.executeUpdate();
    }
  }

  static void queryAsOf(Connection cx, String label, Timestamp ts) throws SQLException {
    System.out.println(label + " @ " + ts.toInstant());
    try (PreparedStatement ps = cx.prepareStatement("""
      SELECT id, owner, balance_cents
      FROM accounts FOR SYSTEM_TIME AS OF ?
      WHERE id = ?
    """)) {
      ps.setTimestamp(1, ts); ps.setLong(2, 1L);
      try (ResultSet rs = ps.executeQuery()) {
        if (rs.next()) {
          System.out.printf(" -> id=%d owner=%s balance=%.2f%n",
            rs.getLong(1), rs.getString(2), rs.getInt(3)/100.0);
        } else {
          System.out.println(" -> no row at that time");
        }
      }
    }
  }

  static Timestamp now(Connection cx) throws SQLException {
    try (Statement st = cx.createStatement();
         ResultSet rs = st.executeQuery("SELECT CURRENT_TIMESTAMP")) {
      rs.next(); return rs.getTimestamp(1);
    }
  }
  static void sleep() {
    try { TimeUnit.MILLISECONDS.sleep(50); } catch (InterruptedException ignored) {}
  }
}
```

**How to adapt**

-   **SQL Server / MariaDB / DB2 / H2:** Use **system-versioned** tables and `FOR SYSTEM_TIME AS OF`.

-   **Oracle:** Use **Flashback Query** (`AS OF TIMESTAMP`) and Flashback Data Archive for retention.

-   **PostgreSQL:** Emulate with triggers/audit/history table or use extensions; lakehouse formats for analytics.

-   **Delta/Iceberg/Hudi:** Use their **version/snapshot** selectors in SQL; compaction & retention are table-level.


---

## Known Uses

-   **Financial closes** and regulatory reporting (recreate end-of-period views).

-   **Customer data history** (address/plan changes over time).

-   **Debugging/RCAs** in complex data pipelines.

-   **Lakehouses** (Delta/Iceberg/Hudi) for **reproducible** analytics and safe rollbacks.


## Related Patterns

-   **Event Sourcing:** Keep events and rebuild state; time-travel tables keep **states** directly.

-   **Snapshot:** Checkpoints of state; time-travel performs fine-grained row-level versioning.

-   **Soft Delete:** Tombstones are just another historical version.

-   **Materialized View:** Recompute MVs **as of** historical snapshots for reproducibility.

-   **Change Data Capture (CDC) / WAL:** Often the underlying feed to maintain history.


---

### Practical Tips

-   Define **retention** (e.g., 13 months) and implement **purge/compaction** to control costs.

-   Tag versions with **schema version** or add upcasters if you evolve row shape in history.

-   Index common **as-of predicates** (by PK + system time) if your engine supports it.

-   For **bitemporal** needs, store both **system** and **valid** periods and document query recipes.

-   Secure history: restrict access to **past sensitive values** (PII) and log access.

-   Remember backups: purge policies must also apply to **backups/archives** to honor erasure rules.
