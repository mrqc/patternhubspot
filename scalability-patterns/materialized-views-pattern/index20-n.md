# Materialized View — Scalability Pattern

## Pattern Name and Classification

**Name:** Materialized View  
**Classification:** Scalability / Performance / Data Architecture (Precomputation & Read Optimization)

---

## Intent

Precompute and **persist** the result of an expensive query (or aggregation/denormalization) so that reads become **fast and predictable**, while keeping the view **periodically or incrementally refreshed** from the source-of-truth data.

---

## Also Known As

-   Materialized Projection / Read Model
    
-   Precomputed View / Summary Table
    
-   Cache Table
    
-   (In streaming systems) **Projection** or **Sink**
    

---

## Motivation (Forces)

-   **Expensive queries** (joins, aggregations) hurt p95/p99 latency and saturate OLTP systems.
    
-   **Asymmetric read/write**: many more reads of the *same* derived data than writes to base tables.
    
-   **Operational safety**: running heavy queries in production competes with core transactions.
    
-   **Predictability**: denormalized, indexed structures deliver consistent response times.
    
-   **Trade-off**: views may be **stale**; refresh strategy balances freshness vs cost.
    

---

## Applicability

Use Materialized Views when:

-   Queries are **repeatable** and expensive (multi-join, group-by, windowed summaries).
    
-   **Bounded staleness** is acceptable (seconds/minutes), or you can do **incremental** updates.
    
-   You need **read isolation** (views served from a different store/cluster).
    
-   You want to **shape** data differently for specific APIs, reports, or search.
    

Avoid or adapt when:

-   You require **strict real-time** consistency on every read.
    
-   Underlying data changes are **too frequent** versus read benefits (view constantly churning).
    
-   Storage for duplicate/denormalized data is a hard constraint.
    

---

## Structure

-   **Base Tables (Source of Truth)** — OLTP schema.
    
-   **Materialized View Store** — a table or engine-managed MV (PostgreSQL MV, Oracle MV, ClickHouse MV, Kafka → Elasticsearch, etc.).
    
-   **Refresh Mechanism** — scheduled full/CONCURRENT refresh, CDC/outbox-driven incremental updates, or streaming pipeline.
    
-   **Indexes** — tailored for query patterns on the view.
    
-   **Access Layer (API/DAO)** — reads from the MV; may fall back to base if needed.
    

---

## Participants

-   **Producers** — write to base tables (transactions).
    
-   **MV Builder/Projector** — process changes and update the MV.
    
-   **Materialized View** — precomputed, query-optimized dataset.
    
-   **Consumers** — dashboards, APIs, search, analytics.
    
-   **Scheduler/Stream Processor** — cron/worker or Kafka/Flink stream.
    

---

## Collaboration

1.  Producers update **base tables**.
    
2.  A **refresh mechanism** (scheduled or incremental) updates the **materialized view**.
    
3.  Consumers query the MV (fast, indexed).
    
4.  On schema/view changes, **rebuild** the MV without impacting OLTP.
    

---

## Consequences

**Benefits**

-   **Low-latency** reads for complex queries.
    
-   **Load isolation**: OLTP unaffected by heavy read shapes.
    
-   **Operational simplicity** (compared to recomputing on every request).
    

**Liabilities**

-   **Staleness** between refreshes.
    
-   **Storage cost** for duplicated/denormalized data.
    
-   **Complexity** in refresh logic, especially incremental updates.
    
-   **Backfill/rebuild time** for large datasets.
    

---

## Implementation

### Key Decisions

-   **Refresh mode**
    
    -   *Periodic full refresh*: simple; use `REFRESH ... CONCURRENTLY` where supported.
        
    -   *Incremental/CDC*: apply row-level deltas (best freshness; more logic).
        
    -   *Streaming*: append-only events → projector updates view continuously.
        
-   **Isolation & indexing**: put MV in its own DB/cluster/read replicas; add covering indexes for query patterns.
    
-   **Freshness contract**: SLA/SLO (“< 60s behind”), expose a **last\_refreshed\_at** column/endpoint.
    
-   **Rebuilds**: support fast rebuilds and rollouts (build new view side-by-side + swap).
    
-   **Idempotence**: incremental upserts must handle duplicates/out-of-order changes.
    

### Anti-Patterns

-   Using a materialized view as the **source of truth**.
    
-   Refreshing **synchronously** on hot request paths.
    
-   Building MV with the **same schema** as base tables (missed optimization).
    
-   No indices on MV; performance regresses over time.
    
-   Full refreshes during peak traffic without **CONCURRENT** semantics (locks).
    

---

## Sample Code (Java + PostgreSQL)

Below: (A) DB-native MV with scheduled **concurrent** refresh; (B) incremental projector applying changes via an **outbox/CDC**\-style table.

### A) PostgreSQL Materialized View + Scheduled Refresh

**SQL (one-time setup):**

```sql
-- Base tables
create table if not exists orders (
  id bigserial primary key,
  customer_id bigint not null,
  created_at timestamptz not null default now(),
  amount_cents bigint not null,
  status text not null check (status in ('NEW','PAID','CANCELLED'))
);

create table if not exists customers (
  id bigserial primary key,
  name text not null,
  region text not null
);

-- Materialized view: daily revenue per region (last 30 days)
create materialized view if not exists mv_daily_revenue_region as
select
  date_trunc('day', o.created_at) as day,
  c.region,
  sum(case when o.status='PAID' then o.amount_cents else 0 end) as revenue_cents,
  count(*) filter (where o.status='PAID') as paid_orders
from orders o
join customers c on c.id = o.customer_id
where o.created_at >= now() - interval '30 days'
group by 1,2;

-- Indexes for fast reads and concurrent refresh
create unique index if not exists mv_drr_day_region_uq
  on mv_daily_revenue_region (day, region);

-- Enable concurrent refreshes (requires unique index on all rows).
```

**Java (Spring Boot / JDBC) to refresh & query:**

```java
// build.gradle (snip)
// implementation 'org.springframework.boot:spring-boot-starter'
// implementation 'org.springframework.boot:spring-boot-starter-jdbc'
// runtimeOnly 'org.postgresql:postgresql'

package com.example.mv;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Repository;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.util.List;

@Service
public class MaterializedViewRefresher {
  private final JdbcTemplate jdbc;
  public MaterializedViewRefresher(JdbcTemplate jdbc) { this.jdbc = jdbc; }

  // Refresh concurrently every minute. Tune schedule to your freshness SLO.
  @Scheduled(fixedDelay = 60_000)
  public void refresh() {
    jdbc.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_revenue_region");
  }
}

@Repository
class RevenueReadModel {
  private final JdbcTemplate jdbc;
  public RevenueReadModel(JdbcTemplate jdbc) { this.jdbc = jdbc; }

  public List<DailyRevenue> byRegion(String region, LocalDate from, LocalDate to) {
    return jdbc.query("""
      select day, region, revenue_cents, paid_orders
      from mv_daily_revenue_region
      where region = ? and day between ?::date and ?::date
      order by day desc
    """, (rs, i) -> new DailyRevenue(
        rs.getObject("day", java.time.OffsetDateTime.class).toLocalDate(),
        rs.getString("region"),
        rs.getLong("revenue_cents"),
        rs.getLong("paid_orders")),
        region, from, to);
  }

  public record DailyRevenue(LocalDate day, String region, long revenueCents, long paidOrders) {}
}
```

**Notes**

-   `CONCURRENTLY` avoids blocking reads; needs a **unique index** that covers all rows.
    
-   Expose an endpoint that returns **last refresh time**, e.g., `select pg_last_refresh_timestamp()` (or maintain your own timestamp table).
    

---

### B) Incremental Materialized View via Outbox/CDC Projector

When you need near-real-time freshness, incrementally update a **plain table** that acts as a materialized view.

**SQL (view table + outbox):**

```sql
create table if not exists mv_customer_summary (
  customer_id bigint primary key,
  region text not null,
  paid_orders bigint not null default 0,
  revenue_cents bigint not null default 0,
  updated_at timestamptz not null default now()
);

-- Outbox to emit order changes (written in same TX as orders)
create table if not exists outbox (
  id bigserial primary key,
  event_type text not null,          -- e.g., 'OrderPaid'
  aggregate_id bigint not null,      -- order id
  payload jsonb not null,
  created_at timestamptz not null default now(),
  published boolean not null default false
);
create index if not exists outbox_pub_created_idx on outbox (published, created_at);
```

**Java Projector (poll outbox → upsert view):**

```java
package com.example.mv;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;

@Component
public class CustomerSummaryProjector {
  private final NamedParameterJdbcTemplate jdbc;
  private final ObjectMapper om = new ObjectMapper();

  public CustomerSummaryProjector(NamedParameterJdbcTemplate jdbc) { this.jdbc = jdbc; }

  @Scheduled(fixedDelay = 500) // near-real-time
  public void project() {
    List<Map<String,Object>> rows = jdbc.getJdbcTemplate().queryForList(
        "select id, event_type, payload::text as payload from outbox where published=false order by created_at asc limit 200");

    for (Map<String,Object> r : rows) {
      long outboxId = ((Number) r.get("id")).longValue();
      String type = (String) r.get("event_type");
      try {
        JsonNode j = om.readTree((String) r.get("payload"));
        switch (type) {
          case "OrderPaid" -> applyPaid(j);
          case "OrderCancelled" -> applyCancelled(j);
          default -> { /* ignore */ }
        }
        jdbc.update("update outbox set published=true where id=:id", Map.of("id", outboxId));
      } catch (Exception e) {
        // keep unpublished for retry or move to DLQ
      }
    }
  }

  private void applyPaid(JsonNode j) {
    long customerId = j.get("customerId").asLong();
    String region = j.get("region").asText();
    long amount = j.get("amountCents").asLong();

    jdbc.update("""
      insert into mv_customer_summary (customer_id, region, paid_orders, revenue_cents, updated_at)
      values (:cid, :region, 1, :amt, now())
      on conflict (customer_id) do update set
        region = excluded.region,
        paid_orders = mv_customer_summary.paid_orders + 1,
        revenue_cents = mv_customer_summary.revenue_cents + :amt,
        updated_at = now()
    """, Map.of("cid", customerId, "region", region, "amt", amount));
  }

  private void applyCancelled(JsonNode j) {
    long customerId = j.get("customerId").asLong();
    long amount = j.get("amountCents").asLong();
    jdbc.update("""
      update mv_customer_summary
         set paid_orders = greatest(0, paid_orders - 1),
             revenue_cents = greatest(0, revenue_cents - :amt),
             updated_at = now()
       where customer_id = :cid
    """, Map.of("cid", customerId, "amt", amount));
  }
}
```

**Notes**

-   **Idempotent** updates (use `on conflict` / natural keys).
    
-   Works with **CDC** tools too (Debezium → Kafka → consumer updates MV).
    
-   You can run a **periodic reconcile** job that recomputes from base data as a safety net.
    

---

## Known Uses

-   **OLTP → MV** for dashboards and APIs (PostgreSQL/Oracle/SQL Server MVs).
    
-   **Evented CQRS** read models (append-only events projected into denormalized tables).
    
-   **Search/analytics sinks** (CDC to Elasticsearch/ClickHouse/BigQuery for fast reads).
    
-   **E-commerce**: product availability summaries, customer/order aggregates.
    
-   **Fintech**: account balances, statement lines precomputed for fast retrieval.
    

---

## Related Patterns

-   **CQRS / Read Models** — MVs are a concrete form of read models.
    
-   **Cache Aside** — MV is a *durable* cache with stronger query capabilities.
    
-   **Database Replication** — complements MVs for read scale; MVs reshape data.
    
-   **Transactional Outbox / CDC** — reliable change propagation for incremental MVs.
    
-   **Indexing / Search Projection** — specialized MVs into search engines.
    

---

## Implementation Checklist

-   Define **query shapes** → design MV schema + **indexes** to match.
    
-   Choose **refresh**: periodic concurrent refresh vs **incremental projector** vs streaming.
    
-   Document **freshness SLO** and expose **last\_refreshed\_at**.
    
-   Make projector **idempotent**; handle replays, out-of-order events, and restarts.
    
-   Plan **rebuilds** (side-by-side build + swap) and **backfills**.
    
-   Monitor **lag**, refresh duration, errors, and MV size growth.
    
-   Secure **access**; MVs often combine PII—enforce row/column-level policies if needed.
    
-   Load test: ensure MV reads meet SLOs under peak; verify refresh does not harm OLTP.

