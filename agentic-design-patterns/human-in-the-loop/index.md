
# Human-in-the-Loop

## Pattern Name and Classification

Human-in-the-Loop — governance/oversight pattern for agentic systems; introduces explicit review, approval, and correction points where a human operator can inspect, steer, or block the agent before it proceeds.

## Intent

Insert human judgment at critical moments to ensure quality, safety, compliance, and accountability, while still benefiting from automation for speed and scale.

## Also Known As

Human Oversight; Approval Gates; Human Review; Human Feedback; Human-on-the-Loop (monitoring variant); Human-in-the-Loop RL (HITL-RL).

## Motivation (Forces)

-   Some tasks require expert judgment, ethics, or policy decisions that models and tools cannot reliably guarantee.

-   High-impact actions (financial trades, production deployments, user communications, data exfiltration risk) demand accountability and audit trails.

-   Human time is scarce; review must be focused and efficient.

-   Excessive gating increases latency and cost; insufficient gating risks harm and liability.  
    The pattern balances automation with targeted human checkpoints.


## Applicability

Use when:

-   Actions have legal, reputational, safety, or financial risk.

-   Outputs must meet non-codified standards (tone, brand, fairness).

-   You need training signals from human feedback to improve future performance.

-   Users expect control or final say (assistive workflows, co-creation).  
    Avoid when actions are fully reversible, low risk, and already validated by deterministic checks.


## Structure

1.  **Checkpoints/Gates** at well-defined stages (pre-action, pre-publish, policy/safety).

2.  **Queue** of review requests with priority, SLA, and metadata.

3.  **Reviewer UI** presenting artifacts, diffs, rationale, and quick actions.

4.  **Decision Schema** (approve, request changes, reject, escalate, override).

5.  **Policy Engine** to require HITL based on risk score, confidence, user segment, or jurisdiction.

6.  **Audit Log** capturing artifacts, decisions, timestamps, and actors.


## Participants

-   **Agent/Executor**: produces artifacts or proposes actions.

-   **Coordinator**: creates review tasks, enforces which steps need HITL, applies outcomes.

-   **Reviewer**: human approver/editor with role-based permissions.

-   **Policy/Guardrails**: compute risk/confidence and trigger gates.

-   **Store/Queue**: persists review items and decisions.

-   **Telemetry/Audit**: records all steps for compliance and learning.


## Collaboration

Agent proposes an action or draft → Policy computes risk/confidence → If gate required, Coordinator creates a review item and pauses execution → Reviewer approves, requests changes, or rejects → Coordinator applies the decision (proceed, revise, abort) → Audit and metrics updated; optional feedback is stored for training or future prompts.

## Consequences

**Benefits**

-   Higher safety and quality on sensitive tasks.

-   Clear accountability and auditability.

-   Human feedback improves future behavior and reduces review load over time.


**Liabilities**

-   Added latency and operational overhead.

-   Potential reviewer bottlenecks and inconsistent judgments.

-   Requires secure, ergonomic tooling and access control.

-   Over-gating can negate automation benefits.


## Implementation (Key Points)

-   Define **risk tiers** and **confidence thresholds** that map to gate policies (e.g., “publish customer-visible email if risk ≤ medium and confidence ≥ 0.85, else review”).

-   Make **checkpoints explicit** in the workflow DAG; never rely on implicit pauses.

-   Use **typed decision schemas** and minimal, actionable diffs to reduce reviewer load.

-   Support **approve**, **revise with comments**, **reject**, **escalate**, and **override with justification**.

-   Enforce **SLAs** and **priorities**; auto-fallbacks if no reviewer responds in time (e.g., abort or safe template).

-   Maintain **immutable audit logs** with correlation IDs; redact sensitive data.

-   Capture reviewer feedback to **fine-tune prompts/policies** and adjust risk scoring.

-   Integrate with **role-based access control** and per-jurisdiction policy rules.

-   Provide **preview/simulation** of downstream side effects before approval.

-   Combine with other patterns: Routing (who reviews), Planning (where gates sit), Reflection (apply reviewer critiques), Exception Handling (timeouts, DLQ for stalled reviews).


## Sample Code (Java)

```java
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Predicate;

/** ---- Domain model ---- */
enum ReviewDecisionType { APPROVE, REVISE, REJECT, ESCALATE, OVERRIDE }

class Artifact {
    final String id;
    final String kind;       // e.g., "email", "deployment", "transfer"
    final String content;    // rendered draft or action summary
    final Map<String, Object> meta; // risk/confidence, user, costs
    Artifact(String id, String kind, String content, Map<String, Object> meta) {
        this.id = id; this.kind = kind; this.content = content; this.meta = meta;
    }
}

class ReviewRequest {
    final String id;
    final Artifact artifact;
    final Instant createdAt = Instant.now();
    final String reason;     // why gated
    ReviewRequest(String id, Artifact artifact, String reason) {
        this.id = id; this.artifact = artifact; this.reason = reason;
    }
}

class ReviewDecision {
    final String requestId;
    final ReviewDecisionType type;
    final String comment; // optional edit instructions or justification
    final String reviewer; // human identity
    final Instant decidedAt = Instant.now();
    ReviewDecision(String requestId, ReviewDecisionType type, String comment, String reviewer) {
        this.requestId = requestId; this.type = type; this.comment = comment; this.reviewer = reviewer;
    }
}

/** ---- Policy: when to require HITL ---- */
class HitlPolicy {
    private final double approveConfidence; // auto-approve threshold
    private final Predicate<Artifact> mustReview; // e.g., sensitive kinds or regions
    HitlPolicy(double approveConfidence, Predicate<Artifact> mustReview) {
        this.approveConfidence = approveConfidence; this.mustReview = mustReview;
    }
    boolean requiresReview(Artifact a) {
        double conf = (double) a.meta.getOrDefault("confidence", 0.0);
        String risk = String.valueOf(a.meta.getOrDefault("risk", "high"));
        if (mustReview.test(a)) return true;
        if ("high".equals(risk)) return true;
        return conf < approveConfidence;
    }
}

/** ---- Queue & store (in-memory demo) ---- */
class ReviewQueue {
    private final BlockingQueue<ReviewRequest> q = new LinkedBlockingQueue<>();
    private final Map<String, ReviewRequest> byId = new ConcurrentHashMap<>();

    void enqueue(ReviewRequest rr) { byId.put(rr.id, rr); q.offer(rr); }
    ReviewRequest take(long timeoutMs) throws InterruptedException { return q.poll(timeoutMs, TimeUnit.MILLISECONDS); }
    Optional<ReviewRequest> get(String id) { return Optional.ofNullable(byId.get(id)); }
    void complete(String id) { byId.remove(id); }
}

/** ---- Coordinator: creates gates, applies decisions ---- */
class HitlCoordinator {
    private final HitlPolicy policy;
    private final ReviewQueue queue;

    HitlCoordinator(HitlPolicy policy, ReviewQueue queue) {
        this.policy = policy; this.queue = queue;
    }

    /** Returns either an immediate “proceed” or the ID of a queued review. */
    Optional<String> gateIfNeeded(Artifact a) {
        if (!policy.requiresReview(a)) return Optional.empty();
        String reqId = UUID.randomUUID().toString();
        queue.enqueue(new ReviewRequest(reqId, a, "policy: risk/confidence gate"));
        return Optional.of(reqId);
    }

    /** Apply decision to the workflow: returns next action for the agent. */
    String applyDecision(ReviewDecision d) {
        queue.complete(d.requestId);
        return switch (d.type) {
            case APPROVE, OVERRIDE -> "proceed";
            case REVISE -> "revise:" + d.comment;
            case REJECT -> "abort";
            case ESCALATE -> "wait_escalation";
        };
    }
}

/** ---- Simulated agent using HITL ---- */
class Agent {
    private final HitlCoordinator coord;
    Agent(HitlCoordinator coord) { this.coord = coord; }

    public String handle(String draft, String kind, double confidence, String risk) {
        Artifact a = new Artifact(
                UUID.randomUUID().toString(),
                kind,
                draft,
                Map.of("confidence", confidence, "risk", risk)
        );

        Optional<String> gate = coord.gateIfNeeded(a);
        if (gate.isEmpty()) {
            // Auto-proceed
            return "SENT: " + a.content;
        } else {
            // Pause execution; await decision (in real life, async and event-driven)
            String reqId = gate.get();
            // For demo: simulate an external reviewer making a decision
            ReviewDecision decision = ReviewerSimulator.review(reqId, a);
            String outcome = coord.applyDecision(decision);
            return switch (outcome) {
                case "proceed" -> "SENT: " + a.content;
                case "abort" -> "ABORTED";
                default -> "REVISE_REQUEST: " + decision.comment;
            };
        }
    }
}

/** ---- Reviewer simulator (would be a real UI) ---- */
class ReviewerSimulator {
    static ReviewDecision review(String reqId, Artifact a) {
        double conf = (double) a.meta.get("confidence");
        if ("high".equals(a.meta.get("risk"))) {
            return new ReviewDecision(reqId, ReviewDecisionType.REVISE,
                    "Remove sensitive claim and add source.", "alice");
        }
        if (conf >= 0.75) {
            return new ReviewDecision(reqId, ReviewDecisionType.APPROVE, "Looks good.", "bob");
        }
        return new ReviewDecision(reqId, ReviewDecisionType.REJECT, "Off-brand tone.", "carol");
    }
}

/** ---- Demo ---- */
public class HumanInTheLoopDemo {
    public static void main(String[] args) {
        HitlPolicy policy = new HitlPolicy(
                0.85,
                a -> a.kind.equals("deployment") || a.kind.equals("financial_transfer")
        );
        ReviewQueue queue = new ReviewQueue();
        HitlCoordinator coord = new HitlCoordinator(policy, queue);
        Agent agent = new Agent(coord);

        System.out.println(agent.handle("Email draft to 5k customers about pricing.", "email", 0.88, "medium"));
        System.out.println(agent.handle("Publish release v2.1 to prod", "deployment", 0.93, "medium"));
        System.out.println(agent.handle("Wire $50k to vendor", "financial_transfer", 0.92, "high"));
        System.out.println(agent.handle("Blog post: roadmap update.", "post", 0.62, "low"));
    }
}
```

## Known Uses

-   Customer communications: human approval of mass emails, chat replies, or policy-sensitive messages.

-   Safety-critical actions: production deploys, infrastructure changes, financial transfers.

-   Content creation: editor approval for tone, style, and accuracy before publishing.

-   Moderation: borderline cases escalated from automated classifiers to human reviewers.

-   Data labeling/feedback pipelines used to improve prompts, policies, and models.


## Related Patterns

-   **Planning:** places gates at milestones and risky steps.

-   **Routing:** sends items to specific reviewers or queues based on domain and risk.

-   **Reflection:** human critiques feed structured revisions back into the loop.

-   **Exception Handling and Recovery:** defines behavior on timeouts, rejections, or missing reviewers.

-   **Tool Use:** previews side effects and simulates actions before approval.

-   **Goal Setting and Monitoring:** gates tied to KR thresholds and SLAs.

-   **Memory Management:** stores decisions and rationales for audit and future adaptation.
