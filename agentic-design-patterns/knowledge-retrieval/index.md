
# Knowledge Retrieval (RAG)

## Pattern Name and Classification

Knowledge Retrieval (RAG) — data/interaction pattern for agentic systems; augments generation with retrieved, domain-grounded context.

## Intent

Ground model outputs in relevant external knowledge by retrieving source passages and conditioning the response on them.

## Also Known As

Retrieval-Augmented Generation; Grounded Generation; Open-Book QA; Context Injection.

## Motivation (Forces)

-   Models hallucinate when asked for specifics outside their parametric memory.

-   Domain knowledge lives in docs, wikis, code, tickets, and databases.

-   Context windows are finite; irrelevant stuffing destroys quality.

-   Data changes over time and must be refreshed, filtered, and cited.  
    RAG narrows context to the most relevant chunks so answers are specific, current, and auditable.


## Applicability

Use when:

-   Precision, traceability, or freshness matters (docs, compliance, APIs).

-   You can index content (text, code, tables) and filter by metadata.

-   Questions vary widely; precomputing all answers is impossible.  
    Avoid when the full truth is already in short, static prompts or the task is pure generation without factual grounding.


## Structure

1.  **Ingestion & Chunking:** parse sources, split into chunks, attach metadata.

2.  **Indexing:** embeddings, keywords, or hybrid.

3.  **Retrieval:** similarity search with filters, rerank, optional MMR/diversity.

4.  **Context Builder:** compose top chunks into a prompt under token budget.

5.  **Generator:** produce the answer conditioned on retrieved context.

6.  **Attribution & Guardrails:** cite sources, dedupe, redact, and validate.

7.  **Feedback Loop:** click/accept signals refine indexing and prompts.


## Participants

-   **Retriever**: top-k search over vector/keyword indexes with filters.

-   **Reranker**: improves ordering (cross-encoder or heuristics).

-   **Context Assembler**: window/budget manager, de-dup, diversity.

-   **Generator**: LLM that writes the final answer grounded in context.

-   **Store/Indexer**: vector DB, BM25, or hybrid engine.

-   **Governance**: redaction, access control, PII handling.


## Collaboration

User query → Retriever fetches candidate chunks → Reranker orders and diversifies → Context Assembler packs the best chunks → Generator answers using only that context → System returns answer plus citations and confidence; logs signals for improvement.

## Consequences

**Benefits**

-   Fewer hallucinations and better specificity.

-   Transparent provenance and easier audits.

-   Easy to update: re-index content without model changes.


**Liabilities**

-   Pipeline complexity and latency.

-   Poor chunking or indexing yields bad answers.

-   Access control and redaction must be handled correctly.

-   Requires continuous freshness management.


## Implementation (Key Points)

-   **Chunk smart:** structure-aware splits (headings, code blocks). Store titles, ids, timestamps.

-   **Hybrid retrieval:** combine embeddings with BM25; fuse scores (e.g., RRF).

-   **Diversity:** MMR or per-source caps to avoid near-duplicates.

-   **Budgeting:** pack context by utility per token; keep a safety margin.

-   **Prompting:** strictly instruct the model to answer from context only; allow “I don’t know.”

-   **Attribution:** return source ids, titles, and anchors.

-   **Freshness:** recrawl and re-embed on change; TTL by collection.

-   **Safety:** redact secrets before indexing; enforce ACLs at query time.

-   **Evaluation:** exact-match/F1 for QA, faithfulness scores, citation accuracy.


## Sample Code (Java)

```java
import java.util.*;
import java.util.stream.Collectors;

/** ----- Domain model ----- */
class Doc {
    final String id;
    final String text;
    final Map<String, String> meta;
    Doc(String id, String text, Map<String, String> meta) { this.id = id; this.text = text; this.meta = meta; }
}

/** ----- Toy embedding model & similarity ----- */
class Embedding {
    static double[] encode(String s, int d) {
        double[] v = new double[d];
        int i = 0; for (char c : s.toCharArray()) { v[i % d] += (c * 31) % 97; i++; }
        double n = 1e-9; for (double x : v) n += x*x; n = Math.sqrt(n);
        for (int j = 0; j < d; j++) v[j] /= n;
        return v;
    }
    static double cosine(double[] a, double[] b) {
        double dot = 0, na = 0, nb = 0;
        for (int i = 0; i < a.length; i++) { dot += a[i]*b[i]; na += a[i]*a[i]; nb += b[i]*b[i]; }
        return dot / (Math.sqrt(na)*Math.sqrt(nb) + 1e-9);
    }
}

/** ----- Vector store with MMR selection ----- */
class VectorStore {
    static class Entry { final Doc doc; final double[] vec; Entry(Doc d, double[] v){doc=d;vec=v;} }
    private final List<Entry> entries = new ArrayList<>();
    private final int dim;
    VectorStore(int dim){ this.dim = dim; }

    void add(Doc d){ entries.add(new Entry(d, Embedding.encode(d.text, dim))); }

    /** Retrieve with Max Marginal Relevance for diversity. */
    List<Doc> mmr(String query, int k, double lambda) {
        double[] q = Embedding.encode(query, dim);
        List<Entry> sorted = entries.stream()
                .sorted((a,b) -> Double.compare(Embedding.cosine(q,b.vec), Embedding.cosine(q,a.vec)))
                .collect(Collectors.toList());
        List<Entry> selected = new ArrayList<>();
        while (selected.size() < k && !sorted.isEmpty()) {
            Entry best = null; double bestScore = -1;
            for (Entry e : sorted) {
                double rel = Embedding.cosine(q, e.vec);
                double div = 0.0;
                for (Entry s : selected) div = Math.max(div, Embedding.cosine(e.vec, s.vec));
                double mmr = lambda * rel - (1 - lambda) * div;
                if (mmr > bestScore) { bestScore = mmr; best = e; }
            }
            selected.add(best); sorted.remove(best);
        }
        return selected.stream().map(en -> en.doc).collect(Collectors.toList());
    }
}

/** ----- Context builder respecting a rough token budget ----- */
class ContextBuilder {
    static String pack(List<Doc> docs, int maxChars) {
        StringBuilder sb = new StringBuilder();
        for (Doc d : docs) {
            String header = "\n[Source " + d.id + "] " + d.meta.getOrDefault("title", "") + "\n";
            if (sb.length() + header.length() >= maxChars) break;
            sb.append(header);
            String t = d.text;
            int remain = maxChars - sb.length();
            sb.append(t, 0, Math.min(t.length(), Math.max(remain, 0)));
            if (sb.length() >= maxChars) break;
        }
        return sb.toString();
    }
}

/** ----- LLM client (stub) ----- */
interface LlmClient { String answer(String system, String user); }
class MockLlm implements LlmClient {
    public String answer(String system, String user) {
        // Extremely naive “grounded” reply: just echoes context snippets.
        String ctx = user.contains("CONTEXT:") ? user.split("CONTEXT:")[1] : "";
        return "Grounded answer using the following context:" + ctx + "\n\nIf information is missing, reply: I don't know.";
    }
}

/** ----- RAG pipeline ----- */
class RagEngine {
    private final VectorStore store;
    private final LlmClient llm;
    RagEngine(VectorStore store, LlmClient llm) { this.store = store; this.llm = llm; }

    public String ask(String query) {
        // 1) Retrieve diverse top-k
        List<Doc> hits = store.mmr(query, 4, 0.7);

        // 2) Build compact context
        String context = ContextBuilder.pack(hits, 1200);

        // 3) Grounded prompt
        String system = "You answer strictly from the provided context. If unsure, say \"I don't know.\" Keep citations as [Source ID].";
        String user = "QUESTION: " + query + "\nCONTEXT:" + context;

        return llm.answer(system, user);
    }
}

/** ----- Demo ----- */
public class RagDemo {
    public static void main(String[] args) {
        VectorStore vs = new VectorStore(64);
        vs.add(new Doc("A1", "The EV market grew 18% YoY in Q3 with strongest demand in compact SUVs.", Map.of("title","EV Q3 Summary")));
        vs.add(new Doc("B2", "Supply chain constraints eased as battery material prices declined 12% since Q2.", Map.of("title","Battery Materials")));
        vs.add(new Doc("C3", "Charging infrastructure expanded with 2,500 new fast chargers in the EU.", Map.of("title","Infrastructure Update")));
        vs.add(new Doc("D4", "Tax incentives in several markets are scheduled to sunset next year.", Map.of("title","Policy Outlook")));

        RagEngine rag = new RagEngine(vs, new MockLlm());
        String answer = rag.ask("What drove EV growth last quarter in Europe?");
        System.out.println(answer);
    }
}
```

## Known Uses

-   Developer helpdesks grounded on internal runbooks and ADRs.

-   Customer support copilots citing policy and product docs.

-   Enterprise search/chat over wikis, tickets, and code.

-   Regulated content generation with source-attributed facts.

-   API assistants answering from OpenAPI specs and changelogs.


## Related Patterns

-   **Memory Management:** long-term facts and summaries become retrievable artifacts.

-   **Routing:** select which retriever or corpus to query.

-   **Planning:** include retrieval steps at specific milestones.

-   **Parallelization:** query multiple retrievers or shards, then fuse results.

-   **Reflection:** verify faithfulness and request additional retrieval if weak.

-   **Tool Use:** retrieval engines are invoked as tools with typed inputs/outputs.
