# Client-Side Composition — UI/UX Pattern

## Pattern Name and Classification

-   **Name:** Client-Side Composition
    
-   **Classification:** UI/UX Composition Pattern / Micro-Frontend Integration / Runtime Page Assembly in the Browser
    

## Intent

Assemble a page **in the browser** from **independently deployed UI fragments** (micro-frontends, widgets, web components, remote modules). The shell (host) fetches a **composition manifest** and **renders & wires** fragments on the client, enabling **autonomous delivery** and **fast, incremental evolution** of product areas.

## Also Known As

-   Micro-Frontends (Client-Orchestrated)
    
-   Frontend Integration via Web Components / Module Federation
    
-   Client-side Page Assembly
    

## Motivation (Forces)

-   **Team autonomy vs. coherence:** multiple teams shipping independent UI parts without blocking each other while keeping a coherent UX.
    
-   **Release independence:** deploy a header, cart, or recommendations UI without redeploying the whole app.
    
-   **Runtime adaptability:** tailor composition per user/feature flag/experiment.
    
-   **Edge vs. device:** move assembly to the client to reduce origin coupling and leverage CDN caching.
    

Tensions to balance:

-   **Waterfalls & latency:** too many round-trips can slow first paint.
    
-   **SEO/SSR:** purely client-side assembly may hurt crawlers or time-to-content.
    
-   **Versioning/safety:** incompatible fragment/shell versions and CSS conflicts.
    
-   **Accessibility:** consistent semantics and focus management across fragments.
    

## Applicability

Use client-side composition when:

-   You have **multiple product surfaces** owned by different teams (e.g., search, cart, recommendations).
    
-   Personalization/experimentation demands **runtime swaps** of fragments.
    
-   You can accept **CSR** (client-side rendering) trade-offs or complement with SSR/ISR.
    

Be cautious when:

-   **SEO-critical** pages require server rendering.
    
-   Target users or devices have **constrained bandwidth/CPU**.
    
-   Strict **compliance/perf budgets** make extra JS overhead unacceptable.
    

## Structure

```scss
[Shell App / Host]
   ├─ fetch composition manifest (JSON)
   ├─ fetch fragment bundles (ES modules / Web Components)
   ├─ fetch data (BFF or fragment-owned APIs)
   └─ mount fragments into slots (#header, #main, #aside...)

[Fragments]
   ├─ UI bundle (JS/CSS) + public interface (props/events)
   ├─ optional data endpoint(s)
   └─ styling isolation (Shadow DOM/CSS namespaces)
```

## Participants

-   **Shell (Host):** loads the manifest, resolves modules, owns routing/layout, provides shared services (auth, theming, telemetry).
    
-   **Fragments (Micro-frontends):** independently built and deployed UI units exposing a **stable contract** (tag name/props/events).
    
-   **Composition Service (optional):** returns a **manifest** (which fragments, versions, URLs, props, guards).
    
-   **BFFs (per fragment or per page):** data endpoints optimized for UI.
    
-   **CDN/Edge:** caches static bundles and manifests.
    

## Collaboration

1.  Shell loads **manifest** (consider user/feature flags/AB bucket).
    
2.  For each slot, shell **loads fragment module** (dynamic `import()` or Module Federation) and **passes props**.
    
3.  Fragments fetch their data (or receive from shell), render in their DOM slot, and **emit events**.
    
4.  Shell mediates cross-fragment **navigation & contracts** (events up, commands/props down).
    
5.  Telemetry and error boundaries capture fragment failures without crashing the page.
    

## Consequences

**Benefits**

-   **Independent deployability** and team ownership.
    
-   **Runtime flexibility** (personalization, experiments).
    
-   **Resilience:** a fragment can “fail soft” while the shell remains usable.
    
-   **Performance at the edge:** static assets cached; manifest rewires runtime.
    

**Liabilities**

-   **Initial payload** can grow (multiple bundles).
    
-   **Waterfall risk** (manifest → modules → data).
    
-   **Styling & contract drift** (need versioning, isolation).
    
-   **SEO/SSR gap** if not complemented with server-rendering or pre-render.
    

## Implementation

### Design Guidelines

-   **Contract first:** each fragment defines tag name, props (JSON-serializable), events, and CSS isolation policy.
    
-   **Isolation:** prefer **Web Components + Shadow DOM** or strict CSS module scoping.
    
-   **Versioning:** use semver in manifest; allow parallel versions during rollout.
    
-   **Data strategy:** avoid N+1 waterfalls—use **BFF per page** or **prefetch** data and pass via props.
    
-   **Performance:**
    
    -   Inline **critical shell** code, lazy-load fragments below the fold.
        
    -   Use **import maps**/Module Federation for shared libs (react, design system).
        
    -   Show **skeletons/shimmers**; set **timeout fallbacks**.
        
-   **Observability:** standardize **logging/metrics/traces** and error boundaries.
    
-   **Security:** enforce **CSP**, integrity (SRI), and **allowed origins** for manifest/modules.
    
-   **Accessibility:** shared focus management, ARIA roles, and keyboard nav contracts.
    

### SEO/Rendering Options

-   Pure **CSR** (this pattern) for apps behind auth.
    
-   **Hybrid SSR**: shell renders HTML + placeholders; fragments **hydrate** client-side.
    
-   **Edge Composition**: pre-compose at CDN/edge for critical paths, fallback to client for long tail.
    

---

## Sample Code (Java 17, minimal server + client-side composition)

> A tiny Java HTTP server serves:
> 
> -   a **composition manifest** (`/composition/home`)
>     
> -   two **data endpoints** (`/api/user`, `/api/offers`)
>     
> -   the **shell page** that composes fragments client-side using Web Components
>     

> For brevity, JS modules are served as static strings from Java. In production, you’d ship them as separate files behind a CDN.

```java
// ClientSideCompositionDemo.java
import com.sun.net.httpserver.*;
import java.io.*;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.*;

public class ClientSideCompositionDemo {

  public static void main(String[] args) throws Exception {
    HttpServer http = HttpServer.create(new InetSocketAddress(8080), 0);

    // 1) Shell page (serves HTML with small loader; fragments are client-side)
    http.createContext("/", ex -> sendHtml(ex, INDEX_HTML));

    // 2) Composition manifest: which fragments to mount where
    http.createContext("/composition/home", ex -> {
      String manifest = """
        {
          "version": "1.0.0",
          "slots": [
            { "id": "header", "module": "/components/user-card.js", "tag": "user-card",
              "props": { "dataSrc": "/api/user" } },
            { "id": "main", "module": "/components/offers-list.js", "tag": "offers-list",
              "props": { "dataSrc": "/api/offers" } }
          ]
        }
      """;
      sendJson(ex, manifest);
    });

    // 3) Data endpoints owned by fragments (could be separate services/BFFs)
    http.createContext("/api/user", ex -> {
      String user = """
        { "email": "alice@example.com", "displayName": "Alice", "lastLogin": "%s" }
      """.formatted(Instant.parse("2025-01-01T12:00:00Z"));
      sendJson(ex, user);
    });

    http.createContext("/api/offers", ex -> {
      String offers = """
        { "items": [
          { "sku":"SKU-100", "title":"Coffee Beans", "price": 9.90 },
          { "sku":"SKU-200", "title":"Espresso Mug", "price": 4.50 },
          { "sku":"SKU-300", "title":"Grinder", "price": 79.00 }
        ] }
      """;
      sendJson(ex, offers);
    });

    // 4) Fragment modules as static JS (Web Components with Shadow DOM)
    http.createContext("/components/user-card.js", ex -> sendJs(ex, USER_CARD_JS));
    http.createContext("/components/offers-list.js", ex -> sendJs(ex, OFFERS_LIST_JS));

    http.setExecutor(null);
    http.start();
    System.out.println("Client-side composition demo at http://localhost:8080/");
  }

  /* ---------- Static assets (HTML/JS) ---------- */

  private static final String INDEX_HTML = """
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>Client-Side Composition Demo</title>
      <style>
        :root { font-family: system-ui, sans-serif; }
        header, main { max-width: 860px; margin: 1.25rem auto; padding: 1rem; border-radius: 12px; box-shadow: 0 4px 18px rgba(0,0,0,.06); }
        .skeleton { background: linear-gradient(90deg,#eee,#f6f6f6,#eee); background-size: 200% 100%; animation: shimmer 1.2s infinite; border-radius: 8px; }
        @keyframes shimmer { 0%{background-position:200% 0}100%{background-position:-200% 0} }
      </style>
    </head>
    <body>
      <header id="header"><div class="skeleton" style="height:80px"></div></header>
      <main id="main"><div class="skeleton" style="height:180px"></div></main>

      <script type="module">
        // Simple composition loader: fetch manifest, load modules, mount tags with props
        async function compose() {
          const res = await fetch('/composition/home', { credentials: 'same-origin' });
          const manifest = await res.json();

          for (const slot of manifest.slots) {
            // Load the fragment module; it should define the custom element
            await import(slot.module);

            const host = document.getElementById(slot.id);
            host.innerHTML = ''; // clear skeleton
            const el = document.createElement(slot.tag);

            // Pass props as attributes or property bag
            for (const [k, v] of Object.entries(slot.props || {})) {
              // Expose both attribute and property for convenience
              el.setAttribute(k, String(v));
              el[k] = v;
            }

            host.appendChild(el);
          }
        }
        compose().catch(err => {
          console.error('Composition failed', err);
          document.getElementById('main').innerHTML = '<p>Something went wrong loading the page.</p>';
        });
      </script>
    </body>
    </html>
  """;

  private static final String USER_CARD_JS = """
    // Web Component: <user-card data-src="/api/user">
    class UserCard extends HTMLElement {
      shadow = this.attachShadow({ mode: 'open' });
      async connectedCallback() {
        const dataSrc = this.getAttribute('dataSrc') || this.getAttribute('data-src') || this.dataSrc;
        try {
          const res = await fetch(dataSrc);
          const user = await res.json();
          this.render(user);
        } catch (e) {
          this.shadow.innerHTML = '<p role="alert">Failed to load user</p>';
        }
      }
      render(user) {
        this.shadow.innerHTML = `
          <style>
            .card { display:flex; gap:.75rem; align-items:center; }
            .avatar { width:48px; height:48px; border-radius:50%; background:#ddd; }
            .meta { line-height:1.2 }
            h2 { font-size:1rem; margin:.25rem 0; }
            small { color:#666 }
          </style>
          <div class="card" aria-label="User">
            <div class="avatar" aria-hidden="true"></div>
            <div class="meta">
              <h2>${user.displayName}</h2>
              <small>${user.email}</small><br/>
              <small>Last login: ${user.lastLogin}</small>
            </div>
          </div>
        `;
      }
    }
    customElements.define('user-card', UserCard);
  """;

  private static final String OFFERS_LIST_JS = """
    // Web Component: <offers-list data-src="/api/offers">
    class OffersList extends HTMLElement {
      shadow = this.attachShadow({ mode: 'open' });
      async connectedCallback() {
        const dataSrc = this.getAttribute('dataSrc') || this.getAttribute('data-src') || this.dataSrc;
        try {
          const res = await fetch(dataSrc);
          const { items } = await res.json();
          this.render(items || []);
          this.shadow.addEventListener('click', e => {
            const li = e.target.closest('li[data-sku]');
            if (li) this.dispatchEvent(new CustomEvent('offer:selected', { detail: { sku: li.dataset.sku }, bubbles: true }));
          });
        } catch (e) {
          this.shadow.innerHTML = '<p role="alert">Failed to load offers</p>';
        }
      }
      render(items) {
        const lis = items.map(i => `<li data-sku="${i.sku}">${i.title} — <strong>€${i.price.toFixed(2)}</strong></li>`).join('');
        this.shadow.innerHTML = `
          <style>
            ul { list-style:none; margin:0; padding:0; }
            li { padding:.5rem .25rem; border-bottom:1px solid #eee; cursor:pointer }
            li:hover { background:#fafafa }
          </style>
          <h2>Offers</h2>
          <ul>${lis}</ul>
        `;
      }
    }
    customElements.define('offers-list', OffersList);
  """;

  /* ---------- tiny helpers ---------- */

  private static void sendHtml(HttpExchange ex, String html) throws IOException {
    ex.getResponseHeaders().add("Content-Type", "text/html; charset=utf-8");
    byte[] b = html.getBytes(StandardCharsets.UTF_8);
    ex.sendResponseHeaders(200, b.length);
    try (OutputStream os = ex.getResponseBody()) { os.write(b); }
  }

  private static void sendJson(HttpExchange ex, String json) throws IOException {
    ex.getResponseHeaders().add("Content-Type", "application/json; charset=utf-8");
    byte[] b = json.getBytes(StandardCharsets.UTF_8);
    ex.sendResponseHeaders(200, b.length);
    try (OutputStream os = ex.getResponseBody()) { os.write(b); }
  }

  private static void sendJs(HttpExchange ex, String js) throws IOException {
    ex.getResponseHeaders().add("Content-Type", "application/javascript; charset=utf-8");
    byte[] b = js.getBytes(StandardCharsets.UTF_8);
    ex.sendResponseHeaders(200, b.length);
    try (OutputStream os = ex.getResponseBody()) { os.write(b); }
  }
}
```

**Run it**

```cpp
javac ClientSideCompositionDemo.java
java ClientSideCompositionDemo
# open http://localhost:8080
```

This demonstrates a **client-orchestrated** composition: the shell fetches a manifest, loads fragment modules, and mounts them into slots, passing props (e.g., `dataSrc`) for data fetches.

---

## Known Uses

-   **E-commerce**: header/cart/PLP/PDP widgets owned by different teams.

-   **SaaS consoles**: pluggable admin areas per product line.

-   **Design-system rollouts**: migrate areas incrementally by swapping fragments in the manifest.

-   **A/B experimentation**: route users to different fragment versions at runtime.


## Related Patterns

-   **Server-Side Composition (Edge/Backend Layout, ESI, SSI):** assemble HTML on server/edge for SEO & first-paint; can hydrate client fragments later.

-   **Micro-Frontends:** architectural umbrella; client-side composition is one implementation style.

-   **BFF (Backend-for-Frontend):** reduce client waterfalls by aggregating data per page.

-   **Module Federation / Import Maps:** mechanics to load remote modules and share deps.

-   **Widget Bus / Pub-Sub:** eventing between fragments.

-   **Skeleton Screens & Optimistic UI:** perceived-performance aids during fragment loads.

-   **Contract Testing (UI contracts):** stabilize fragment–shell integration (props/events versioned).


---

## Implementation Tips

-   **Manifest** should support **targeting** (user segment, locale, experiment) and **safe rollout** (percentage flags).

-   **Prevent waterfalls:** prefetch critical data and pass as props; batch data in a **BFF**.

-   **Standardize**: auth headers propagation, error boundary component, telemetry schema.

-   **Style safely:** Shadow DOM or CSS modules; a shared **tokens** layer for theme coherence.

-   **Cache smartly:** long-cache static fragments; short-cache manifest; use **ETags**.

-   **Gradual SSR:** critical pages server-render shell + above-the-fold fragments, hydrate the rest on the client.

-   **Contract hygiene:** semver for props/events, deprecation windows, adapter shims during transitions.
