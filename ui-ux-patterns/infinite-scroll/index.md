# Infinite Scroll — UI/UX Pattern

## Pattern Name and Classification

**Name:** Infinite Scroll  
**Category:** UI/UX · Content Navigation · Progressive Loading · Performance

## Intent

Continuously load additional content as the user approaches the end of the current list/grid, minimizing explicit pagination steps and perceived wait times while keeping scrolling flow uninterrupted.

## Also Known As

Endless Scrolling · Continuous Scrolling · Auto-Pagination · Lazy Feed

## Motivation (Forces)

-   **Flow & engagement:** Reduce friction of clicking “next page”; keep users immersed.
    
-   **Perceived performance:** Small chunks load quickly; skeletons keep UI responsive.
    
-   **Limited device resources:** Avoid loading the entire dataset at once; progressive memory use.
    
-   **Ranking freshness:** Dynamic feeds (social/news) benefit from “more of the same” behavior.
    
-   **Trade-offs:**
    
    -   **Findability/returnability:** Deep links and “place in list” must be preservable.
        
    -   **Footer reachability:** Continuous loading can bury the footer.
        
    -   **Orientation:** Users may feel lost without page boundaries.
        
    -   **Accessibility/SEO:** Screen readers, keyboard users, and crawlers need explicit anchors.
        

## Applicability

Use when:

-   Content is **stream-like** or **discovery-oriented** (news feed, social, image grid).
    
-   Users typically **browse**, not target a specific item (serendipity > precision).
    
-   You can provide **stable, cursor-based pagination** from the backend.
    

Avoid or use cautiously when:

-   **Task completion** requires precise navigation, bookmarking, or comparison (search results, admin tables).
    
-   **SEO** for paginated content is critical (prefer classic pagination or hybrid).
    
-   **Footer links** (legal, contact) must remain reliably reachable (offer “Jump to footer” or switch to “Load more”).
    

## Structure

-   **Viewport Trigger:** Intersection observer (sentinel element) or scroll listener to detect proximity to end.
    
-   **Paginator:** Client-side state (cursor/keyset/offset) + throttling/backpressure.
    
-   **Data Source/API:** Cursor (token) or keyset-based endpoint with deterministic order.
    
-   **Renderer/Virtualizer:** DOM virtualization/windowing to cap memory/DOM nodes.
    
-   **Skeleton/Placeholder:** Shimmer tiles while loading; consistent item heights where possible.
    
-   **Error/Retry/UI State:** Inline error row with “Retry”; offline indicator.
    
-   **History/Deep-Linking:** URL state (e.g., `?cursor=…&count=…&scroll=…`) + restore on back/forward.
    
-   **Accessibility Layer:** Announce “N items loaded”, keyboard-accessible “Load more” fallback, focus management.
    
-   **Footer Strategy:** Sticky utility bar or explicit “End of results” sentinel enabling footer reach.
    

## Participants

-   **User:** Scrolls and consumes content.
    
-   **Scroller/Observer:** Detects when to fetch more.
    
-   **Paginator State:** Holds `cursor`, `isLoading`, `hasMore`, error.
    
-   **API Endpoint:** Returns items in stable order with `nextCursor`.
    
-   **Renderer/Virtualizer:** Renders items and prunes off-screen nodes.
    
-   **History Manager:** Syncs list position with URL/session storage.
    
-   **Telemetry:** Measures fetch cadence, item exposure, and abandonment.
    

## Collaboration

1.  Viewport observer signals “near end”.
    
2.  Paginator requests the next chunk using **cursor**.
    
3.  API returns `items[]`, `nextCursor`, `hasMore`.
    
4.  Renderer appends items; virtualizer updates window.
    
5.  Announce loads via ARIA live region; update URL/history.
    
6.  On error, show inline retry; on exhaustion, show “End of results” sentinel.
    

## Consequences

**Benefits**

-   Frictionless exploration; higher session duration for discovery feeds.
    
-   Lower initial payload; improved perceived speed.
    
-   Natural fit for real-time or frequently updated content.
    

**Liabilities**

-   Can harm **findability**, bookmarks, and user orientation.
    
-   Footer/secondary navigation becomes hard to reach.
    
-   Potential **memory/CPU bloat** without virtualization.
    
-   Accessibility challenges (focus traps, screen reader verbosity).
    
-   Analytics complexity (no page boundaries).
    

## Implementation

**Guidelines**

1.  **Use cursor/keyset pagination** (not offset) for stability under insertions/deletions.
    
2.  **Deterministic ordering:** e.g., `ORDER BY created_at DESC, id DESC`.
    
3.  **Backpressure & throttling:** Only one fetch at a time; debounce intersection events.
    
4.  **Virtualize lists:** Keep DOM node count bounded (window ~30–100 rows).
    
5.  **State machine:** `idle → loading → append/swap → idle` with error and exhausted states.
    
6.  **Accessible fallback:** Provide a visible **“Load more”** button that the observer can click programmatically; ensure it works without JS.
    
7.  **History/restore:** Save/restore scroll position and last cursor on navigation/back.
    
8.  **Footer reachability:** Offer “Jump to footer,” auto-stop after N batches, or switch to pagination.
    
9.  **Offline/Retry:** Detect `navigator.onLine`; exponential backoff; idempotent requests.
    
10.  **Instrumentation:** Track time-to-first-item, items-per-batch, errors, user position on exit.
    

---

## Sample Code (Java)

Below is a **Spring Boot** keyset/cursor pagination API for infinite scroll. It returns a stable slice with a `nextCursor` token. Pair this with a client that uses an `IntersectionObserver` and renders items.

```java
// src/main/java/com/example/feed/FeedItem.java
package com.example.feed;

import jakarta.persistence.*;
import java.time.Instant;

@Entity
@Table(name = "feed_item", indexes = {
  @Index(name = "idx_feed_created_id", columnList = "createdAt,id")
})
public class FeedItem {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, updatable = false)
    private Instant createdAt = Instant.now();

    @Column(nullable = false, length = 280)
    private String content;

    // getters/setters
    public Long getId() { return id; }
    public Instant getCreatedAt() { return createdAt; }
    public String getContent() { return content; }
    public void setContent(String content) { this.content = content; }
}
```

```java
// src/main/java/com/example/feed/FeedItemRepository.java
package com.example.feed;

import jakarta.persistence.EntityManager;
import jakarta.persistence.PersistenceContext;
import org.springframework.stereotype.Repository;

import java.time.Instant;
import java.util.Base64;
import java.util.List;

@Repository
public class FeedItemRepository {
    @PersistenceContext private EntityManager em;

    // Cursor format: base64("createdAtMillis:id"), ordered DESC by (createdAt,id)
    public List<FeedItem> findNext(String cursor, int limit) {
        Instant createdBefore = Instant.ofEpochMilli(Long.MAX_VALUE);
        long idBefore = Long.MAX_VALUE;

        if (cursor != null && !cursor.isBlank()) {
            String[] parts = new String(Base64.getUrlDecoder().decode(cursor)).split(":");
            createdBefore = Instant.ofEpochMilli(Long.parseLong(parts[0]));
            idBefore = Long.parseLong(parts[1]);
        }

        return em.createQuery("""
            select f from FeedItem f
            where (f.createdAt < :cAt)
               or (f.createdAt = :cAt and f.id < :id)
            order by f.createdAt desc, f.id desc
            """, FeedItem.class)
            .setParameter("cAt", createdBefore)
            .setParameter("id", idBefore)
            .setMaxResults(Math.min(Math.max(limit, 1), 100))
            .getResultList();
    }

    public static String makeCursor(FeedItem last) {
        String raw = last.getCreatedAt().toEpochMilli() + ":" + last.getId();
        return Base64.getUrlEncoder().withoutPadding().encodeToString(raw.getBytes());
    }
}
```

```java
// src/main/java/com/example/feed/dto/FeedDtos.java
package com.example.feed.dto;

import java.util.List;

public record FeedResponse(
        List<Item> items,
        String nextCursor,
        boolean hasMore
) {}

public record Item(long id, long createdAtMs, String content) {}
```

```java
// src/main/java/com/example/feed/FeedController.java
package com.example.feed;

import com.example.feed.dto.FeedResponse;
import com.example.feed.dto.Item;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/feed")
public class FeedController {

    private final FeedItemRepository repo;

    public FeedController(FeedItemRepository repo) { this.repo = repo; }

    @GetMapping
    public ResponseEntity<FeedResponse> get(
            @RequestParam(value = "cursor", required = false) String cursor,
            @RequestParam(value = "limit", defaultValue = "20") int limit
    ) {
        List<FeedItem> slice = repo.findNext(cursor, limit);
        String next = null;
        boolean hasMore = false;

        if (!slice.isEmpty()) {
            FeedItem last = slice.get(slice.size() - 1);
            next = FeedItemRepository.makeCursor(last);
            // Soft-signal more items exist if we returned 'limit' rows.
            hasMore = slice.size() == Math.min(Math.max(limit, 1), 100);
        }

        FeedResponse body = new FeedResponse(
                slice.stream()
                     .map(f -> new Item(f.getId(), f.getCreatedAt().toEpochMilli(), f.getContent()))
                     .toList(),
                next,
                hasMore
        );

        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore()) // feeds are personalized; avoid caching
                .body(body);
    }
}
```

```java
// src/main/java/com/example/feed/GlobalExceptionHandler.java
package com.example.feed;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(Exception.class)
    public ResponseEntity<?> handle(Exception e) {
        return ResponseEntity.status(500).body(
            new java.util.LinkedHashMap<>() {{
                put("title", "Unexpected error");
                put("status", 500);
            }}
        );
    }
}
```

**Client (conceptual, not Java):**

-   Use an `IntersectionObserver` on a sentinel div at the list end.
    
-   Debounce triggers; guard with `isLoading/hasMore`.
    
-   Append `items` to a virtualized list.
    
-   Update the URL with `?cursor=` and restore on back/forward.
    
-   Provide a visible **Load more** button that is activated when the observer fires; ensure it’s reachable by keyboard and announced via ARIA live region: “20 items loaded.”
    

---

## Known Uses

-   **Twitter/X, Instagram, Facebook feeds** — continuous discovery streams.
    
-   **Reddit, Pinterest** — masonry grids with infinite loading.
    
-   **Google Images / Unsplash** — image search results with progressive loading.
    
-   **News apps** — “Top stories” sections that extend as you scroll.
    

## Related Patterns

-   **Pagination (Numbered / “Load More”)** — explicit boundaries; better for tasks and SEO.
    
-   **Virtual Scrolling / Windowing** — performance technique often paired with infinite scroll.
    
-   **Pull to Refresh** — complements endless feeds on mobile.
    
-   **Skeleton Screens / Progressive Loading** — keeps perceived latency low.
    
-   **Sticky Footer / Jump Links** — mitigates footer reachability issues.
    
-   **Back/Forward Restoration** — preserves position when navigating detail → list.

