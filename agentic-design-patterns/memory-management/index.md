
# Memory Management

## Pattern Name and Classification

Memory Management — state/data pattern for agentic systems; organizes, retrieves, and compacts past interactions, facts, and artifacts across short-term, episodic, and long-term stores.

## Intent

Maintain just enough relevant context for reliable reasoning while controlling cost, latency, privacy, and drift by storing, indexing, retrieving, and pruning memories.

## Also Known As

Context Store; Episodic/Semantic Memory; Working Memory; Conversation History; RAG Memory.

## Motivation (Forces)

-   Context windows are finite and expensive.

-   Important details get buried in long histories.

-   Different tasks need different memory scopes (per user, per session, global).

-   Uncurated memory causes contradictions, leakage, and prompt injection.

-   Compliance, retention, and privacy rules vary across domains.


## Applicability

Use when:

-   The agent must personalize, remember commitments, or track evolving tasks.

-   You need stable facts across sessions (long-term) and fresh details within a session (short-term).

-   Retrieval quality matters more than raw history replay.

-   There are governance constraints for PII, data residency, or retention limits.


## Structure

1.  **Ingestion**: convert events/artifacts into normalized memory records.

2.  **Indexing**: embed, keyword, or hybrid indexing for retrieval.

3.  **Stores**:

    -   Working/Short-term (session window, high churn)

    -   Episodic (timestamped interactions)

    -   Semantic/Long-term (facts, summaries, skills)

4.  **Retrieval**: top-k by similarity + filters (scope, tags, TTL).

5.  **Compaction**: summarization, dedupe, synthesis to reduce size.

6.  **Governance**: PII tagging, encryption, retention policies, redaction.

7.  **Policy**: when to write, read, forget, and expose memory to prompts.


## Participants

-   **Memory Orchestrator**: applies policies for write/read/forget.

-   **Encoder/Indexer**: produces embeddings/keywords for search.

-   **Stores**: physical backends (in-memory, DB, vector DB, KV).

-   **Retriever**: executes similarity + rule filters.

-   **Compactor/Summarizer**: condenses histories into durable facts.

-   **Guard/PII Filter**: detects sensitive fields and enforces retention.

-   **Agent/Planner**: consumes retrieved memories to guide steps.


## Collaboration

Event occurs → Orchestrator normalizes and tags → Indexer updates relevant stores → On a new query, Retriever selects memories by scope and similarity → Agent uses memories in planning/generation → Compactor periodically summarizes and evicts according to policy.

## Consequences

**Benefits**

-   Better personalization, coherence, and adherence to commitments.

-   Lower token cost via targeted retrieval instead of full replay.

-   Auditable, policy-driven handling of sensitive data.


**Liabilities**

-   Stale or wrong memories can mislead the agent.

-   Over-collection risks privacy violations.

-   Extra infra for indexing, compaction, and governance.

-   Retrieval adds latency if not cached.


## Implementation (Key Points)

-   Define a **typed schema**: id, text, vector, scope, tags, created, ttl, source, piiFlags, confidence.

-   Separate **scopes**: `session`, `user`, `team/org`, `global`. Default to least privilege.

-   Use **hybrid retrieval** (embedding + BM25/keyword) and score fusion.

-   Add **write policies**: only store actionable, reusable facts; reject prompt-injected content.

-   **Compaction** on thresholds (tokens, age, duplication): summarize episodic logs into semantic facts.

-   **Eviction** strategies: TTL, LRU, low-score, or conflict-aware replacement.

-   **Governance**: encrypt at rest, redact secrets, store consent and retention metadata.

-   Cache retrievals; batch embeddings; monitor hit rate, precision@k, staleness.


## Sample Code (Java)

```java
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Collectors;

/** ---- Memory model ---- */
enum Scope { SESSION, USER, ORG, GLOBAL }

class MemoryRecord {
    final String id;
    final String text;
    final double[] vector;
    final Scope scope;
    final Set<String> tags;
    final Instant createdAt;
    final Instant expiresAt; // nullable = no TTL
    final boolean pii;

    MemoryRecord(String id, String text, double[] vector, Scope scope,
                 Set<String> tags, Instant createdAt, Instant expiresAt, boolean pii) {
        this.id = id; this.text = text; this.vector = vector; this.scope = scope;
        this.tags = tags; this.createdAt = createdAt; this.expiresAt = expiresAt; this.pii = pii;
    }
}

/** ---- Embedding encoder (toy, deterministic) ---- */
class ToyEncoder {
    static double[] embed(String s, int dim) {
        double[] v = new double[dim];
        int i = 0;
        for (char c : s.toCharArray()) {
            v[i % dim] += (c * 31) % 97;
            i++;
        }
        // L2 normalize
        double norm = 0;
        for (double x : v) norm += x * x;
        norm = Math.sqrt(norm) + 1e-9;
        for (int j = 0; j < dim; j++) v[j] /= norm;
        return v;
    }

    static double cosine(double[] a, double[] b) {
        double dot = 0, na = 0, nb = 0;
        for (int i = 0; i < a.length; i++) { dot += a[i]*b[i]; na += a[i]*a[i]; nb += b[i]*b[i]; }
        double denom = Math.sqrt(na) * Math.sqrt(nb) + 1e-9;
        return dot / denom;
    }
}

/** ---- Memory store ---- */
interface MemoryStore {
    void upsert(MemoryRecord r);
    List<MemoryRecord> retrieve(String query, Scope scope, Set<String> requiredTags, int k);
    void evictExpired();
    void deleteByTag(String tag);
}

class InMemoryStore implements MemoryStore {
    private final Map<String, MemoryRecord> db = new ConcurrentHashMap<>();
    private final int dim;

    InMemoryStore(int dim) { this.dim = dim; }

    public void upsert(MemoryRecord r) { db.put(r.id, r); }

    public List<MemoryRecord> retrieve(String query, Scope scope, Set<String> requiredTags, int k) {
        double[] qv = ToyEncoder.embed(query, dim);
        Instant now = Instant.now();

        return db.values().stream()
                .filter(r -> (r.scope == scope || r.scope == Scope.GLOBAL)
                        && (r.expiresAt == null || r.expiresAt.isAfter(now))
                        && (requiredTags.isEmpty() || r.tags.containsAll(requiredTags)))
                .map(r -> new AbstractMap.SimpleEntry<>(r, ToyEncoder.cosine(qv, r.vector)))
                .sorted((a, b) -> Double.compare(b.getValue(), a.getValue()))
                .limit(k)
                .map(Map.Entry::getKey)
                .collect(Collectors.toList());
    }

    public void evictExpired() {
        Instant now = Instant.now();
        db.values().removeIf(r -> r.expiresAt != null && !r.expiresAt.isAfter(now));
    }

    public void deleteByTag(String tag) {
        db.values().removeIf(r -> r.tags.contains(tag));
    }
}

/** ---- Memory orchestrator with policies ---- */
class MemoryManager {
    private final MemoryStore store;
    private final int dim;

    MemoryManager(MemoryStore store, int dim) { this.store = store; this.dim = dim; }

    public String remember(String text, Scope scope, Set<String> tags, long ttlSeconds, boolean pii) {
        if (!isActionable(text)) return null; // write policy: drop low-value chatter
        Instant now = Instant.now();
        Instant exp = ttlSeconds > 0 ? now.plusSeconds(ttlSeconds) : null;
        String id = UUID.randomUUID().toString();
        double[] v = ToyEncoder.embed(text, dim);
        store.upsert(new MemoryRecord(id, text, v, scope, tags, now, exp, pii));
        return id;
    }

    public List<MemoryRecord> recall(String query, Scope scope, Set<String> tags, int k) {
        return store.retrieve(query, scope, tags, k);
    }

    public void compact(Scope scope) {
        // Example compaction: dedupe near-identical records by tag
        Map<String, List<MemoryRecord>> byTag = new HashMap<>();
        for (MemoryRecord r : store.retrieve("", scope, Set.of(), 1000)) {
            for (String t : r.tags) byTag.computeIfAbsent(t, k -> new ArrayList<>()).add(r);
        }
        for (List<MemoryRecord> group : byTag.values()) {
            // naive: keep newest, remove others if cosine > 0.98
            group.sort(Comparator.comparing(x -> x.createdAt));
            MemoryRecord latest = group.get(group.size() - 1);
            for (int i = 0; i < group.size() - 1; i++) {
                if (ToyEncoder.cosine(latest.vector, group.get(i).vector) > 0.98) {
                    // mark for deletion by a synthetic tag
                    store.deleteByTag("dup:" + group.get(i).id);
                }
            }
        }
    }

    public void forgetByPolicy(String reasonTag) {
        store.deleteByTag(reasonTag); // e.g., "user-requested-deletion" or "expired-consent"
    }

    private boolean isActionable(String text) {
        // trivial heuristic: store only if contains dates, tasks, or explicit facts
        String t = text.toLowerCase();
        return t.contains("todo") || t.contains("deadline") || t.contains("meeting")
                || t.contains("preference") || t.contains("uses") || t.length() > 80;
    }
}

/** ---- Example agent using memory ---- */
class MemoryAgent {
    private final MemoryManager mm;

    MemoryAgent(MemoryManager mm) { this.mm = mm; }

    public String respond(String userId, String sessionQuery) {
        // Write an episodic record for the query (short-term)
        mm.remember("UserQuery: " + sessionQuery, Scope.SESSION, Set.of("q:"+userId), 1800, false);

        // Recall top memories for grounding
        List<MemoryRecord> m = mm.recall(sessionQuery, Scope.USER, Set.of("pref:"+userId), 3);

        StringBuilder ctx = new StringBuilder("Context:\n");
        for (MemoryRecord r : m) ctx.append("- ").append(r.text).append("\n");

        return "Answer (using memory):\n" + ctx + "\nResponse: [grounded reply here]";
    }
}

/** ---- Demo ---- */
public class MemoryDemo {
    public static void main(String[] args) {
        InMemoryStore store = new InMemoryStore(64);
        MemoryManager mm = new MemoryManager(store, 64);
        MemoryAgent agent = new MemoryAgent(mm);

        // Seed long-term user preferences
        mm.remember("Preference: user likes concise answers and Java examples.",
                Scope.USER, Set.of("pref:user123"), 0, false);
        mm.remember("Preference: timezone=Europe/Vienna; language=de/en.",
                Scope.USER, Set.of("pref:user123"), 0, true);

        String out = agent.respond("user123", "Can you show a Java example for retry with backoff?");
        System.out.println(out);

        // Periodic maintenance
        store.evictExpired();
        mm.compact(Scope.USER);
    }
}
```

## Known Uses

-   Conversational assistants persisting preferences, tasks, and facts across sessions.

-   Code assistants caching project context, APIs, and error histories.

-   Research agents storing retrieved chunks and distilled notes for later synthesis.

-   Customer support copilots retaining case history and resolutions.

-   Workflow agents tracking commitments, deadlines, and intermediate artifacts.


## Related Patterns

-   **Planning:** plans reference and update memory as checkpoints complete.

-   **Prompt Chaining:** each step reads/writes scoped memories between stages.

-   **Routing:** route based on remembered user preferences or past successes.

-   **Parallelization:** store and fuse results from concurrent branches.

-   **Reflection:** critiques and summaries are written back as durable facts.

-   **Tool Use:** tool outputs are normalized and saved as retrievable artifacts.
