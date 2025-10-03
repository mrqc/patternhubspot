# Data Management & Database Pattern — Soft Delete

## Pattern Name and Classification

-   **Name:** Soft Delete

-   **Classification:** Data lifecycle & safety pattern (logical deletion via flags/timestamps rather than physical removal)


## Intent

Mark records as **deleted** (e.g., `is_deleted = true` or `deleted_at != NULL`) so that they’re **excluded from normal reads** but remain recoverable for **audit, restore, or reference integrity** until a separate **purge** process physically removes them.

## Also Known As

-   Logical Delete / Tombstoning

-   Flagged Delete / Mark-as-Deleted

-   Deferred/Two-phase Delete (when paired with later hard delete)


## Motivation (Forces)

-   **Accidental deletion & restore:** Undo user mistakes quickly.

-   **Audit/forensics:** Preserve history for investigations or compliance holds.

-   **Reference integrity:** Avoid breaking references while dependents still exist.

-   **Operational safety:** De-risk migrations and “un-delete” flows.


**Tensions**

-   **Data minimization / privacy:** Some regulations require true deletion on request.

-   **Performance & correctness:** Every read must filter tombstones; tables grow; indexes need care.

-   **Uniqueness constraints:** “Deleted” rows shouldn’t block creating a new live row.


## Applicability

Use soft delete when:

-   You need **undo**, **trash bin**, or **retention holds**.

-   You must safeguard against mistaken deletes in operational systems.

-   Downstream pipelines need to **observe** delete events (tombstones) before purge.


Be cautious when:

-   Law/policy requires **immediate, irreversible deletion** (e.g., “right to be forgotten”).

-   Datasets are extremely hot/high-churn; tombstone bloat can harm performance.


## Structure

```sql
+----------------------+
DELETE intent ->|  Domain Service      |
                +----------+-----------+
                           |
                           v
                     Soft Delete
        (set is_deleted=true or deleted_at=now())
                           |
                           v
                Normal reads add predicate:
                WHERE is_deleted = FALSE  (or deleted_at IS NULL)

Periodically:
  Purge job: DELETE FROM table WHERE is_deleted=TRUE AND deleted_at < retention_cutoff
```

## Participants

-   **Domain Service / DAO:** Enforces soft delete instead of physical delete; adds default filters to reads.

-   **Schema Columns:** `is_deleted` (bool) or `deleted_at` (timestamp), often `deleted_by`.

-   **Indexes & Constraints:** Designed so uniqueness applies to **active** rows only (e.g., partial index or composite key).

-   **Purge/Retention Job:** Physically deletes old tombstones; may archive first.

-   **Audit/Events:** Outbox/CDC to emit “deleted” events for consumers.


## Collaboration

1.  A delete command arrives.

2.  Service performs a **local transaction**: set `is_deleted=true` and `deleted_at=NOW()`.

3.  All read paths **filter** out deleted rows by default.

4.  Optional **restore** clears the flag.

5.  Scheduled **purge** permanently removes soft-deleted rows past retention (and cascades).


## Consequences

**Benefits**

-   **Reversibility:** Easy undelete within retention.

-   **Safety:** Fewer catastrophic data-loss incidents.

-   **Observability:** Downstream systems can react to tombstones.


**Liabilities**

-   **Query complexity:** Every read must include the predicate (risk of leaks if forgotten).

-   **Storage bloat:** Large volume of tombstones unless purged.

-   **Indexes/uniqueness:** Must be rethought so deleted rows don’t block new inserts.

-   **Privacy:** Not sufficient for immediate erasure obligations—needs a purge path.


## Implementation (Key Points)

-   **Column choice:**

    -   `deleted_at TIMESTAMP NULL` is self-descriptive and supports retention windows.

    -   `is_deleted BOOLEAN` is fast; pair with `deleted_at` if you need dates.

-   **Uniqueness:**

    -   **PostgreSQL:** partial unique index, e.g. `CREATE UNIQUE INDEX ... ON users(email) WHERE deleted_at IS NULL;`

    -   **Portable approach:** composite unique on `(email, is_deleted)` ensuring only one *active* row per value.

-   **ORM integration:** Hibernate/JPA support `@SQLDelete` & `@Where` filters; ensure bulk operations also respect filters.

-   **Cascades:** Do *logical* cascades in application code; avoid physical `ON DELETE CASCADE` when parent is soft-deleted.

-   **Purging:** Run a job (e.g., daily) to delete rows where `deleted_at < NOW() - retention`. Consider archiving to cold storage first.

-   **Auditing:** Store `deleted_by`, capture outbox events (`EntityDeleted{ id, occurredAt }`).

-   **Security:** Default to **secure-by-default** reads (always filtered). Provide explicit admin methods to include deleted.


---

## Sample Code (Java 17 + JDBC/H2): Soft Delete with Restore and Purge

> Demonstrates:
>
> -   Schema with `is_deleted`, `deleted_at`, and a **composite unique** `(email, is_deleted)` so only one *active* row per email.
>
> -   DAO methods: create, get/list active, soft-delete, restore, purge.
>
> -   Shows that a **new active** user can be created with the same email after soft delete.
>

```java
// File: SoftDeleteDemo.java
// Compile: javac -cp h2.jar SoftDeleteDemo.java
// Run:     java  -cp .:h2.jar SoftDeleteDemo
import java.sql.*;
import java.time.*;
import java.util.*;

public class SoftDeleteDemo {

  public static void main(String[] args) throws Exception {
    try (Connection cx = DriverManager.getConnection("jdbc:h2:mem:demo;DB_CLOSE_DELAY=-1")) {
      cx.setAutoCommit(false);
      createSchema(cx);

      // Create a user
      long u1 = insertUser(cx, "alice@example.com", "Alice");
      cx.commit();
      System.out.println("Created user id=" + u1);

      // List active users
      System.out.println("Active users: " + listActiveUsers(cx));

      // Soft-delete the user
      softDeleteUser(cx, u1, "admin");
      cx.commit();
      System.out.println("After soft delete, active users: " + listActiveUsers(cx));

      // Re-create another active user with same email (allowed because previous is_deleted=true)
      long u2 = insertUser(cx, "alice@example.com", "Alice (new)");
      cx.commit();
      System.out.println("Created replacement user id=" + u2 + " for same email");

      System.out.println("Active users now: " + listActiveUsers(cx));
      System.out.println("Including deleted: " + listUsersIncludingDeleted(cx));

      // Restore the old one (this would violate unique(email,is_deleted=false)). Expect failure.
      try {
        restoreUser(cx, u1);
        cx.commit();
      } catch (SQLException e) {
        cx.rollback();
        System.out.println("Restore failed due to uniqueness on active email: " + e.getMessage());
      }

      // Purge soft-deleted rows older than 0 days (immediate purge for demo)
      int purged = purgeDeletedBefore(cx, LocalDate.now().plusDays(0));
      cx.commit();
      System.out.println("Purged rows: " + purged);
      System.out.println("All rows after purge: " + listUsersIncludingDeleted(cx));
    }
  }

  static void createSchema(Connection cx) throws SQLException {
    try (Statement st = cx.createStatement()) {
      st.execute("""
        CREATE TABLE users (
          id          BIGINT AUTO_INCREMENT PRIMARY KEY,
          email       VARCHAR(255) NOT NULL,
          full_name   VARCHAR(255) NOT NULL,
          is_deleted  BOOLEAN NOT NULL DEFAULT FALSE,
          deleted_at  TIMESTAMP NULL,
          deleted_by  VARCHAR(64),
          created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
      """);
      // Ensure only one ACTIVE (is_deleted=false) row per email is allowed
      st.execute("CREATE UNIQUE INDEX ux_users_email_active ON users(email, is_deleted);");
      // Basic trigger-like updated_at maintenance via H2 computed column alternative:
      // We'll set updated_at manually in SQL statements.
    }
  }

  /* ---------- DAO operations ---------- */

  static long insertUser(Connection cx, String email, String fullName) throws SQLException {
    try (PreparedStatement ps = cx.prepareStatement("""
      INSERT INTO users(email, full_name, is_deleted, deleted_at, deleted_by, created_at, updated_at)
      VALUES(?,?, FALSE, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, Statement.RETURN_GENERATED_KEYS)) {
      ps.setString(1, email);
      ps.setString(2, fullName);
      ps.executeUpdate();
      try (ResultSet rs = ps.getGeneratedKeys()) {
        rs.next(); return rs.getLong(1);
      }
    }
  }

  static void softDeleteUser(Connection cx, long id, String deletedBy) throws SQLException {
    try (PreparedStatement ps = cx.prepareStatement("""
      UPDATE users SET is_deleted = TRUE,
                       deleted_at = CURRENT_TIMESTAMP,
                       deleted_by = ?,
                       updated_at = CURRENT_TIMESTAMP
      WHERE id = ? AND is_deleted = FALSE
    """)) {
      ps.setString(1, deletedBy);
      ps.setLong(2, id);
      ps.executeUpdate();
    }
  }

  static void restoreUser(Connection cx, long id) throws SQLException {
    // Restoration clears the flag; UNIQUE(email,is_deleted) may reject if another active row with same email exists.
    try (PreparedStatement ps = cx.prepareStatement("""
      UPDATE users
      SET is_deleted = FALSE,
          deleted_at = NULL,
          deleted_by = NULL,
          updated_at = CURRENT_TIMESTAMP
      WHERE id = ? AND is_deleted = TRUE
    """)) {
      ps.setLong(1, id);
      ps.executeUpdate();
    }
  }

  static int purgeDeletedBefore(Connection cx, LocalDate cutoffDate) throws SQLException {
    try (PreparedStatement ps = cx.prepareStatement("""
      DELETE FROM users
      WHERE is_deleted = TRUE AND deleted_at < ?
    """)) {
      ps.setTimestamp(1, Timestamp.valueOf(cutoffDate.atStartOfDay()));
      return ps.executeUpdate();
    }
  }

  static List<String> listActiveUsers(Connection cx) throws SQLException {
    try (PreparedStatement ps = cx.prepareStatement("""
      SELECT id, email, full_name FROM users
      WHERE is_deleted = FALSE
      ORDER BY id
    """)) {
      try (ResultSet rs = ps.executeQuery()) {
        List<String> out = new ArrayList<>();
        while (rs.next()) out.add(rs.getLong(1) + "|" + rs.getString(2) + "|" + rs.getString(3));
        return out;
      }
    }
  }

  static List<String> listUsersIncludingDeleted(Connection cx) throws SQLException {
    try (PreparedStatement ps = cx.prepareStatement("""
      SELECT id, email, full_name, is_deleted, deleted_at FROM users ORDER BY id
    """)) {
      try (ResultSet rs = ps.executeQuery()) {
        List<String> out = new ArrayList<>();
        while (rs.next()) out.add(
          rs.getLong("id") + "|" + rs.getString("email") + "|" + rs.getString("full_name")
          + "|deleted=" + rs.getBoolean("is_deleted") + "|at=" + rs.getTimestamp("deleted_at"));
        return out;
      }
    }
  }
}
```

**Notes about the example**

-   Uses a **composite unique index** `(email, is_deleted)` to guarantee only one *active* row per email; soft-deleted rows don’t block new active inserts.

-   **Restore** will fail if another active row exists with the same email—this is often desirable. If restoration must win, handle with an **application-level swap** (soft-delete the active row first, then restore).

-   Replace with **partial unique indexes** (e.g., PostgreSQL) for a cleaner model: `UNIQUE WHERE is_deleted=false`.


---

## Known Uses

-   **SaaS business objects:** customers, projects, documents with “Trash/Recycle Bin.”

-   **Collaboration/content:** posts/files with version history and undelete.

-   **E-commerce:** products/orders where deletes are rare; soft delete + **archive** before true purge.

-   **Event-sourced/CQRS systems:** logical delete emits a **tombstone event** for read model convergence before compaction.


## Related Patterns

-   **Hard Delete (Physical Delete):** The eventual purge step; required for privacy erasure.

-   **Event Sourcing:** Use **tombstone events**; snapshots/projections exclude deleted aggregates.

-   **Materialized View / Read Models:** Downstream views need to **consume tombstones** to stay consistent.

-   **Outbox / CDC:** Publish delete events reliably to other stores.

-   **Snapshot & Backup/Restore:** Snapshots include deleted state; purging must consider backups too.

-   **Database per Service:** Soft delete semantics belong to the **owning service’s** domain model.


---

### Practical Tips

-   **Secure-by-default:** Centralize query builders/ORM filters so “active-only” is automatic; require explicit opt-in to include deleted.

-   **Indexes:** Add indexes on the delete marker to keep predicates cheap, e.g., `(is_deleted)` or `(deleted_at)`.

-   **Retention policies:** Define time-based purge and exceptions (legal hold). Log purge decisions.

-   **GDPR/Privacy:** Implement **hard delete** (and deletion in backups/archives) for erasure requests; soft delete alone is insufficient.

-   **Cascading strategy:** For dependent rows, design **logical cascades** and **restore cascades**; avoid physical `ON DELETE CASCADE` on soft-deleted parents.

-   **APIs:** Provide `GET ?includeDeleted=true` for admins; surface `deleted_at/by` in audit endpoints.

-   **Testing:** Add contract tests that assert **no endpoint** leaks soft-deleted rows by default.
