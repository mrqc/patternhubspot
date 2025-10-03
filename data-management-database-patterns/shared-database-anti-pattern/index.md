# Data Management & Database — Shared Database **Antipattern**

## Pattern Name and Classification

-   **Name:** Shared Database

-   **Classification:** **Antipattern** (tight-coupling integration via a common database)


## Intent

Use a **single shared database/schema** as the integration point between multiple services/teams to “avoid building APIs.” It appears to reduce duplication and speed up delivery—but creates **implicit coupling, fragile change management, and unsafe cross-team dependencies**.

## Also Known As

-   Integration Database

-   Shared Schema / Shared Tables

-   “Just read their tables”

-   Database-as-API


## Motivation (Forces)

-   **Short-term speed pressure:** “We already have the data; let’s query it directly.”

-   **Perceived DRYness:** Avoid duplicating read models or building contracts.

-   **Centralized governance:** One DBA team, one place to back up and secure.

-   **Reporting needs:** Ad-hoc joins are easier when everything is in one place.


**Counterforces / Reality**

-   **Tight coupling:** Any schema change risks **breaking other teams**.

-   **Hidden contracts:** Tables/columns act as APIs without versioning or tests.

-   **Invariants bypassed:** Other services can violate domain rules with direct writes.

-   **Deployment lockstep:** Database migrations require **orchestrated multi-team releases**.

-   **Security & blast radius:** Over-privileged access increases risk and audit scope.

-   **Scaling bottleneck:** One DB becomes the **contention point** for compute, I/O, and operations.


## Applicability

**You are likely in the antipattern** when:

-   Multiple services **read/write the same tables**.

-   Teams coordinate **schema changes in meetings** rather than through versioned contracts.

-   Production incidents are caused by **unexpected queries or migrations** from other teams.

-   “Integration” commonly means **running SQL against someone else’s schema**.


## Structure

```pgsql
+-------------+         +-------------+         +-------------+
          |  Service A  |         |  Service B  |         |  Service C  |
          |  (Team A)   |         |  (Team B)   |         |  (Team C)   |
          +------+------+         +------+------+         +------+------+
                 \                        |                         /
                  \                       |                        /
                   \__________  Shared Database  __________________/
                               (shared schema & tables)
                     (implicit contracts; cross-team migrations)
```

## Participants

-   **Services / Teams:** Independent codebases that **depend directly** on shared tables.

-   **Shared Database:** Single point of storage, security, scaling, and failure.

-   **DBA / Platform Team:** Becomes the de facto integration gatekeeper.

-   **Shadow Consumers:** Reports, scripts, or jobs that silently depend on the same schema.


## Collaboration

1.  Team A introduces / evolves a table.

2.  Team B reads/writes it directly.

3.  A schema refactor (rename, split, constraints) by Team A **breaks** Team B at runtime.

4.  Ops must coordinate **big-bang** migrations & rollbacks; incident blast radius is large.


## Consequences

**Liabilities (why it’s an antipattern)**

-   **Change paralysis:** Every change risks downstream breakage → slow delivery.

-   **Operational coupling:** Hotfixes require **multi-team** sync.

-   **Integrity leaks:** Business rules are bypassed via direct DB writes.

-   **Security complexity:** Granting least-privilege is hard when tables are shared.

-   **Performance contention:** One DB becomes a shared choke point.

-   **Test brittleness:** CI isn’t representative; consumers rely on **private columns**.


**Perceived Benefits (short-term)**

-   Fast to prototype.

-   Simplifies **ad-hoc analytics** (until volume & ownership grow).


## Implementation (What People Do in Practice—**Not** Recommended)

-   Give every service a connection/user with broad privileges to the same schema.

-   Rely on wiki docs for table meanings.

-   Coordinate changes via spreadsheets and “freeze windows.”


## Safer Alternatives / Migration Path

-   **Database per Service:** each service **owns** its database & schema.

-   **Publish read models:** via **Outbox + CDC**, **events**, or **materialized views**.

-   **CQRS:** command/write model in the owning service; consumers read **derived** models.

-   **API / BFF / GraphQL:** formal, versioned contracts.

-   **Reporting:** copy to **warehouse/lake** (ELT) for cross-domain analytics.

-   **Strangler migration:** introduce an **anti-corruption layer**; move one bounded context at a time.


---

## Sample Code (Java 17, H2): How a Shared DB Breaks on a “Harmless” Schema Change

**Scenario:**

-   *Service A* expects a `users(full_name)` column.

-   *Service B* “improves” the schema to `first_name/last_name` and **drops** `full_name`.

-   Service A **crashes at runtime**—classic shared DB blast radius.


```java
// File: SharedDbAntipatternDemo.java
// Compile: javac -cp h2.jar SharedDbAntipatternDemo.java
// Run:     java  -cp .:h2.jar SharedDbAntipatternDemo
import java.sql.*;

public class SharedDbAntipatternDemo {

  public static void main(String[] args) throws Exception {
    try (Connection cx = DriverManager.getConnection("jdbc:h2:mem:shared;DB_CLOSE_DELAY=-1")) {
      cx.setAutoCommit(false);
      try (Statement st = cx.createStatement()) {
        // Team A's original schema and code expectations
        st.execute("""
          CREATE TABLE users(
            id BIGINT PRIMARY KEY,
            full_name VARCHAR(200) NOT NULL
          );
        """);
        st.execute("INSERT INTO users(id, full_name) VALUES (1,'Alice Smith'), (2,'Bob Müller');");
        cx.commit();
      }

      // --- Service A: works today
      serviceAListUsers(cx);

      // --- Service B: "harmless" refactor (no coordination with A)
      try (Statement st = cx.createStatement()) {
        st.execute("ALTER TABLE users ADD COLUMN first_name VARCHAR(100);");
        st.execute("ALTER TABLE users ADD COLUMN last_name  VARCHAR(100);");
        st.execute("UPDATE users SET first_name = SUBSTRING(full_name, 1, LOCATE(' ', full_name)-1), " +
                   "last_name = SUBSTRING(full_name, LOCATE(' ', full_name)+1, 200) " +
                   "WHERE LOCATE(' ', full_name) > 0;");
        // Drops column that Service A still reads:
        st.execute("ALTER TABLE users DROP COLUMN full_name;");
        cx.commit();
      }

      // --- Service A: deploys nothing; still running the old code -> boom
      try {
        serviceAListUsers(cx); // runtime failure
      } catch (SQLException e) {
        System.out.println("\nService A broke due to shared schema change:");
        System.out.println("  " + e.getMessage());
      }
    }
  }

  // Service A code that assumes 'full_name' exists (implicit contract via schema)
  static void serviceAListUsers(Connection cx) throws SQLException {
    System.out.println("\nService A reading users (expects column 'full_name'):");
    try (PreparedStatement ps = cx.prepareStatement("SELECT id, full_name FROM users ORDER BY id");
         ResultSet rs = ps.executeQuery()) {
      while (rs.next()) {
        System.out.printf(" - id=%d name=%s%n", rs.getLong("id"), rs.getString("full_name"));
      }
    }
  }
}
```

**What this demonstrates**

-   There is **no versioned contract**: the *table is the contract*.

-   A unilateral change by one team **instantly breaks** another team’s runtime.

-   Fix requires **coordinated releases** or temporary shims (views), defeating the “move fast” goal.


> If you’re currently stuck with a shared DB, mitigate by adding **compatibility views**, **feature-flagged migrations** (add → backfill → dual-read → flip → remove), and **least-privilege** DB accounts. Then plan the migration away.

---

## Known Uses

-   Early “microservices” where only the code was split but the **database stayed monolithic**.

-   Enterprise apps with many teams writing “integration SQL” against a central OLTP.

-   Reporting tools directly querying production OLTP tables used by multiple services.


## Related Patterns

-   **Database per Service** (recommended)

-   **Outbox / Transactional Messaging** (publish changes reliably)

-   **CQRS** (separate write model from read models)

-   **Materialized Views / Data Warehouse** (serve cross-domain analytics)

-   **Saga / TCC** (coordinate cross-service workflows without XA)

-   **Anti-Corruption Layer / Strangler Fig** (gradual migration)


---

### Practical Guidance

-   Treat direct table access by another team as a **breaking-change risk**.

-   If you must share temporarily:

    -   Expose **read-only** SQL **views** as a stable façade; version them.

    -   Enforce **least-privilege** (read-only for consumers, writes only via owning service).

    -   Use **feature-flagged, multi-step migrations** (add → backfill → dual-read/write → cutover → drop).

    -   Provide **contract tests** for views (shape & semantics).

    -   Replicate to **read replicas** or a **warehouse** for heavy reads.

-   Set a migration goal: **one bounded context → one owning service → one database**, plus **published read models** for everyone else.
