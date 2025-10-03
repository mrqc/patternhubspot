# Agile Squad — Organizational Team Pattern

## Pattern Name and Classification

-   **Name:** Agile Squad
    
-   **Classification:** Cross-functional, product-oriented **organizational team** pattern (long-lived, outcome-focused, stream-aligned)
    

## Intent

Create a **small, autonomous, and cross-functional team** that owns a customer or value stream end-to-end—**discovery → delivery → operation**—so it can ship, learn, and iterate continuously with minimal handoffs.

## Also Known As

-   **Squad** (popularized by the Spotify model)
    
-   **Feature Team**
    
-   **Stream-aligned Team** (Team Topologies)
    
-   **Product Team**
    

## Motivation (Forces)

-   **Speed vs. coordination:** Centralized functions slow delivery; colocated skills reduce handoffs.
    
-   **Autonomy vs. alignment:** Teams need freedom to execute while aligning on vision, APIs, and standards.
    
-   **Ownership vs. specialization:** A single team must cover UX, data, quality, reliability, and code.
    
-   **Discovery vs. delivery:** Continuous product discovery must coexist with engineering execution.
    
-   **Stability vs. responsiveness:** Long-lived teams build domain expertise yet must react to incidents.
    
-   **Compliance & risk:** Regulated contexts need guardrails without central bottlenecks.
    

## Applicability

Use Agile Squads when:

-   Work can be **mapped to a value stream** (checkout, onboarding, search, pricing, mobile app shell…).
    
-   You can give the team **all skills** to ship to production.
    
-   The problem benefits from **continuous iteration** and user feedback.
    

Be cautious when:

-   The organization is **project-funded** with short engagements and heavy matrixing.
    
-   **Tight central constraints** require serialized approvals for every change.
    
-   Work is primarily shared infrastructure → consider a **Platform/Enabling** team instead.
    

## Structure

```css
TRIBE / PRODUCT AREA
         ┌─────────────────────────────────────────────────────┐
         │  Shared vision, roadmap, standards, platform APIs   │
         └───┬─────────────────┬──────────────────┬────────────┘
             │                 │                  │
      ┌──────▼──────┐   ┌──────▼──────┐    ┌──────▼──────┐
      │  Squad A    │   │  Squad B    │    │  Squad C    │   … (6–10 people each)
      │ (Search)    │   │ (Checkout)  │    │ (Mobile UX) │
      ├─────────────┤   ├─────────────┤    ├─────────────┤
      │ PO  │ Designer  │ PO │ QA      │    │ PO │ iOS/Android
      │ Eng │ Dev/QA    │ Eng│ DevOps  │    │ Eng│ Data   │
      └─────┴───────────┴────┴─────────┴────┴─────────────┘
       ↑ Discovery+Delivery+Operations       ↑ Chapters/Guilds (craft alignment)
```

## Participants

-   **Product Owner / Product Manager (PO/PM):** Owns outcomes, backlog, and discovery cadence.
    
-   **Engineering Lead / Tech Lead (TL) or EM:** Technical direction, architecture, quality, delivery.
    
-   **Developers:** Backend, frontend/mobile, data/ML—T-shaped where possible.
    
-   **QA/SET (embedded):** Exploratory testing, quality coaching, test automation.
    
-   **Designer/UX Researcher:** Journeys, discovery, prototypes, usability.
    
-   **Data/Analytics:** Metrics, experiments, instrumentation.
    
-   **SRE/DevOps (embedded or shared):** Reliability, CI/CD, infra as code.
    
-   **Platform & Enabling Teams (external):** Provide reusable services, guardrails, coaching.
    
-   **Chapters/Guilds (community of practice):** Cross-squad standards for craft.
    

## Collaboration

-   **Cadences:**
    
    -   **Planning** (bi-weekly), **Backlog Refinement** (weekly), **Daily Sync** (15 min), **Demo/Review** (bi-weekly), **Retro** (bi-weekly).
        
    -   **Incident reviews** and **operational readiness** in the squad.
        
-   **Artifacts:** Outcome-based roadmap/OKRs, team charter, Definition of Ready/Done, Team API (how others engage), runbooks, dashboards (DORA, cycle time, SLOs).
    
-   **Interfaces:**
    
    -   With **platform** via clear APIs and paved paths.
        
    -   With **other squads** via contracts (API, events), lightweight RFCs, and dependency boards.
        
    -   With **leadership** via outcome reviews and guardrail metrics, not task status.
        

## Consequences

**Benefits**

-   Faster cycle time and **reduced handoffs**.
    
-   **Clear ownership** of a value stream; better accountability and domain expertise.
    
-   Strong **learning loop**: discovery and delivery in one unit.
    
-   **Resilience**: on-call and incident response close to the code and users.
    

**Liabilities**

-   Risk of **local optimization** or duplicated solutions across squads.
    
-   **Standards drift** without strong chapters/platform boundaries.
    
-   **Overloaded roles** (PO/TL) if staffing is thin.
    
-   **Dependency management** can still bite; requires explicit contracts and planning.
    

## Implementation

1.  **Define the stream:** Pick a user journey or product slice with measurable outcomes.
    
2.  **Form the squad (6–10 ppl):** PO, TL/EM, 3–6 devs, embedded QA, design, data; avoid sub-teams.
    
3.  **Team charter & operating model:** Mission, decision rights, Definition of Done, code ownership, on-call.
    
4.  **Backlog & outcomes:** Write outcome-oriented hypotheses, OKRs, and measurable leading indicators.
    
5.  **Technical guardrails:** Coding standards, trunk-based CI/CD, SLOs, security baselines, platform interfaces.
    
6.  **Cadences & rituals:** Plan/review/retro; add discovery cadence (weekly research, experiments).
    
7.  **Interfaces to the org:** Team API, RFC template, dependency board, release calendar.
    
8.  **Metrics & learning:** DORA, cycle time, defect escape rate, experiment velocity, customer health (NPS/engagement).
    
9.  **Scaling:** Create **chapters/guilds**, establish a **platform team**, and use **lightweight architecture reviews**.
    
10.  **Recalibrate:** Quarterly health checks, rotate roles (incident commander, story lead), adjust scope.
    

---

## Sample Code (Java) — Sprint Capacity & WIP Guard for an Agile Squad

> A tiny utility you can run from the command line to:
> 
> 1.  calculate **sprint capacity** given availability and a focus factor, and
>     
> 2.  enforce a simple **WIP limit** per developer to avoid over-committing.
>     

```java
// SquadPlanner.java
import java.time.LocalDate;
import java.util.*;
import java.util.stream.Collectors;

/** Simple capacity & WIP helper for an Agile Squad. */
public class SquadPlanner {

  // ---- Domain ----
  static final class Member {
    final String name;
    final double availabilityPct; // e.g. 0.9 if 10% meetings/support
    final int daysOff;            // PTO during the sprint
    final int wipLimit;           // max concurrent tasks
    Member(String name, double availabilityPct, int daysOff, int wipLimit) {
      this.name = name; this.availabilityPct = availabilityPct; this.daysOff = daysOff; this.wipLimit = wipLimit;
    }
  }

  static final class Sprint {
    final LocalDate start; final int lengthDays; final double focusFactor; // 0.6–0.8 typical
    Sprint(LocalDate start, int lengthDays, double focusFactor) {
      this.start = start; this.lengthDays = lengthDays; this.focusFactor = focusFactor;
    }
  }

  static final class Task {
    final String id; final String title; final String assignee; final int estPoints;
    final boolean started;
    Task(String id, String title, String assignee, int estPoints, boolean started) {
      this.id = id; this.title = title; this.assignee = assignee; this.estPoints = estPoints; this.started = started;
    }
  }

  // ---- Capacity calculation ----
  static int memberCapacityPoints(Member m, Sprint s, int pointsPerIdealDay) {
    int workableDays = Math.max(0, s.lengthDays - m.daysOff);
    double ideal = workableDays * pointsPerIdealDay * m.availabilityPct;
    return (int) Math.floor(ideal * s.focusFactor);
  }

  static int squadCapacityPoints(List<Member> members, Sprint s, int ppd) {
    return members.stream().mapToInt(m -> memberCapacityPoints(m, s, ppd)).sum();
  }

  // ---- WIP guard ----
  static Map<String, List<Task>> wipViolations(List<Member> members, List<Task> tasks) {
    Map<String, Integer> limits = members.stream().collect(Collectors.toMap(m -> m.name, m -> m.wipLimit));
    Map<String, Long> inProgress = tasks.stream()
        .filter(t -> t.started).collect(Collectors.groupingBy(t -> t.assignee, Collectors.counting()));
    Map<String, List<Task>> offenders = new HashMap<>();
    for (var e : inProgress.entrySet()) {
      int limit = limits.getOrDefault(e.getKey(), Integer.MAX_VALUE);
      if (e.getValue() > limit) {
        List<Task> violating = tasks.stream()
            .filter(t -> t.started && t.assignee.equals(e.getKey()))
            .collect(Collectors.toList());
        offenders.put(e.getKey(), violating);
      }
    }
    return offenders;
  }

  // ---- Demo ----
  public static void main(String[] args) {
    Sprint sprint = new Sprint(LocalDate.now(), 10, 0.7); // 2-week (10 working days), 70% focus
    List<Member> squad = List.of(
        new Member("Ada", 0.9, 1, 2),
        new Member("Grace", 0.8, 0, 2),
        new Member("Linus", 0.85, 0, 3),
        new Member("Ken", 0.75, 2, 2)
    );

    int pointsPerIdealDay = 2; // your local calibration
    int capacity = squadCapacityPoints(squad, sprint, pointsPerIdealDay);
    System.out.println("Sprint capacity (story points): " + capacity);

    List<Task> board = List.of(
        new Task("T-1", "Implement login", "Ada", 5, true),
        new Task("T-2", "Add metrics", "Ada", 3, true),
        new Task("T-3", "Fix crash", "Ada", 2, true), // Ada exceeds WIP=2
        new Task("T-4", "Checkout API", "Grace", 8, true),
        new Task("T-5", "UX polish", "Grace", 3, false),
        new Task("T-6", "Cache layer", "Linus", 5, true)
    );

    Map<String, List<Task>> offenders = wipViolations(squad, board);
    if (offenders.isEmpty()) {
      System.out.println("No WIP violations 🎉");
    } else {
      System.out.println("WIP violations detected:");
      offenders.forEach((assignee, tasks) -> {
        System.out.println(" - " + assignee + " has " + tasks.size() + " in progress (limit exceeded).");
        tasks.forEach(t -> System.out.println("    • " + t.id + " — " + t.title));
      });
    }
  }
}
```

**How to use it**

-   Adjust `availabilityPct`, `daysOff`, `focusFactor`, and `pointsPerIdealDay` to your squad.
    
-   Run the class; it prints a **capacity estimate** and flags **WIP overages**—useful in planning/stand-up.
    

---

## Known Uses

-   Product-oriented tech companies and digital organizations widely adopt squad-like structures to align teams to customer journeys (e.g., onboarding, payments, search, mobile shell).
    
-   The overall idea is seen across industries under labels like **feature teams**, **stream-aligned teams**, or **product teams**.
    

## Related Patterns

-   **Team Topologies:** *Stream-aligned*, *Platform*, *Enabling*, *Complicated-Subsystem* teams.
    
-   **Platform Team Pattern:** Provides paved paths and shared services to many squads.
    
-   **Chapter/Guild (Communities of Practice):** Cross-squad craft alignment.
    
-   **Service-per-Team / Microservice Ownership:** Organizational mirror of service boundaries.
    
-   **Trunk-Based Development / DevOps:** Engineering practices that empower squads.
    
-   **Coordinator (Mobile), Repository, MVVM/MVI:** Typical software patterns used inside a squad’s codebase.

