
# Proxy — GoF Structural Pattern

## Pattern Name and Classification

**Name:** Proxy  
**Category:** Structural design pattern

## Intent

Provide a **surrogate** (stand-in) for another object to **control access** to it. The proxy exposes the **same interface** as the real subject while adding policies such as **lazy loading**, **access control**, **caching**, **remote access**, **monitoring**, or **fault isolation**.

## Also Known As

Surrogate, Placeholder, Stand-in

## Motivation (Forces)

-   The real object is **expensive** to create/use (e.g., large file, heavy service) → **Virtual Proxy** defers work until needed.

-   The real object sits **across process/network** → **Remote Proxy** hides remoting details behind a local API.

-   Calls must be **authorized**, **metered**, or **audited** → **Protection/Firewall Proxy**.

-   Results are **reused** frequently → **Caching Proxy**.

-   You need **resilience** (timeouts/retries/circuit breakers) or **observability** → **Smart/Monitoring Proxy**.

-   You want to enforce **invariants** or **transaction boundaries** without changing clients or the real subject.


## Applicability

Use Proxy when:

-   You must **control or extend** access to an object **without changing its interface**.

-   Instantiation is **costly** and can be **deferred**.

-   The object is **remote** or **in another address space**.

-   You need **cross-cutting** concerns (auth, cache, logging, rate limit) around a component that clients already use.


## Structure

```kotlin
Client ───────────────→ Subject (interface)
   │                         ▲
   │                         │
   └── calls ─→  Proxy  ─────┘    (same interface; holds/refers to RealSubject)
                     │
                     └─→ RealSubject (the actual implementation)
```

Variants: **Virtual**, **Remote**, **Protection**, **Caching**, **Smart/Monitoring**, **Firewall**.

## Participants

-   **Subject** — the interface expected by clients.

-   **RealSubject** — the real implementation that does the work.

-   **Proxy** — implements `Subject`; holds a reference to (or creates) the `RealSubject`; adds access policy/behavior.


## Collaboration

-   Client invokes methods on the **Proxy** (transparently, as if it were the subject).

-   Proxy decides whether/how to delegate to **RealSubject** (instantiate lazily, authorize, cache, marshal across network, etc.).

-   Some proxies may **short-circuit** (serve from cache, deny access) without calling RealSubject.


## Consequences

**Benefits**

-   Keeps clients **decoupled** from access policies and heavy/remote details.

-   Enables **lazy** instantiation, **caching**, **security**, **observability**, and **fault tolerance** with no client changes.

-   Multiple proxies can be **composed** (chain of wrappers).


**Liabilities**

-   Extra **indirection** and potential latency.

-   Must keep **semantics** and **interface** aligned with RealSubject (risk of subtle differences).

-   **Identity** and **equality** can be surprising (proxy ≠ real instance by reference).

-   For remote proxies, failures are **partial** and exceptions differ (timeouts, network errors).


## Implementation

-   Keep the **Subject** minimal and stable.

-   For **virtual proxies**, use **lazy, thread-safe** initialization (e.g., double-checked locking).

-   For **caching**, define **TTL**, **invalidation**, and **keying** clearly; ensure **idempotency** where needed.

-   For **protection proxies**, do **authorization first** to avoid unnecessary work.

-   Consider **composition** of proxies (order matters: e.g., auth → rate-limit → cache → log).

-   In Java you can build proxies via:

    -   **Static classes** (simple, fast).

    -   **`java.lang.reflect.Proxy` + `InvocationHandler`** (interfaces only).

    -   **Bytecode/CGLIB** (classes; used by many frameworks).

-   Be explicit about **equals/hashCode/toString** delegation.

-   For remote proxies, map **transport errors** to domain exceptions and consider **timeouts/retries/circuit breakers**.


---

## Sample Code (Java)

**Scenario:** A `ReportService` has an expensive real implementation. We compose several proxies:

-   **VirtualProxy**: lazy initialization of the real service.

-   **ProtectionProxy**: role-based access check.

-   **CachingProxy**: simple in-memory TTL cache.

-   **LoggingProxy**: timing/trace.


```java
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Supplier;

/* ---------- Subject ---------- */
interface ReportService {
    String renderReport(String reportId);
}

/* ---------- RealSubject (expensive) ---------- */
class RealReportService implements ReportService {
    public RealReportService() {
        simulate("warm up heavy engine (fonts, templates, db pool)", 400);
    }
    @Override public String renderReport(String reportId) {
        simulate("render " + reportId, 200);
        return "PDF(" + reportId + ")@" + System.currentTimeMillis();
    }
    private static void simulate(String what, int ms) {
        try { Thread.sleep(ms); } catch (InterruptedException ignored) {}
        System.out.println("[Real] " + what);
    }
}

/* ---------- Virtual Proxy (lazy init, thread-safe) ---------- */
class LazyReportProxy implements ReportService {
    private final Supplier<ReportService> factory;
    private volatile ReportService delegate;
    public LazyReportProxy(Supplier<ReportService> factory) { this.factory = factory; }
    private ReportService target() {
        ReportService d = delegate;
        if (d == null) {
            synchronized (this) {
                if (delegate == null) delegate = factory.get();
                d = delegate;
            }
        }
        return d;
    }
    @Override public String renderReport(String reportId) { return target().renderReport(reportId); }
}

/* ---------- Simple security context & Protection Proxy ---------- */
final class SecurityContext {
    private static final ThreadLocal<Set<String>> ROLES = ThreadLocal.withInitial(HashSet::new);
    public static void setRoles(String... roles) { ROLES.set(new HashSet<>(Arrays.asList(roles))); }
    public static boolean hasRole(String role) { return ROLES.get().contains(role); }
}

class SecuredReportProxy implements ReportService {
    private final ReportService delegate;
    private final String requiredRole;
    public SecuredReportProxy(ReportService delegate, String requiredRole) {
        this.delegate = delegate; this.requiredRole = requiredRole;
    }
    @Override public String renderReport(String reportId) {
        if (!SecurityContext.hasRole(requiredRole))
            throw new SecurityException("missing role: " + requiredRole);
        return delegate.renderReport(reportId);
    }
}

/* ---------- Caching Proxy (TTL) ---------- */
class CachingReportProxy implements ReportService {
    private final ReportService delegate;
    private final long ttlMillis;
    private static final class Entry { final String value; final long ts; Entry(String v,long t){value=v;ts=t;} }
    private final Map<String, Entry> cache = new ConcurrentHashMap<>();
    public CachingReportProxy(ReportService delegate, long ttlMillis) {
        this.delegate = delegate; this.ttlMillis = ttlMillis;
    }
    @Override public String renderReport(String reportId) {
        Entry e = cache.get(reportId);
        long now = System.currentTimeMillis();
        if (e != null && now - e.ts < ttlMillis) {
            System.out.println("[Cache] hit for " + reportId);
            return e.value;
        }
        System.out.println("[Cache] miss for " + reportId);
        String v = delegate.renderReport(reportId);
        cache.put(reportId, new Entry(v, now));
        return v;
    }
}

/* ---------- Logging/Timing Proxy ---------- */
class LoggingReportProxy implements ReportService {
    private final ReportService delegate;
    public LoggingReportProxy(ReportService delegate) { this.delegate = delegate; }
    @Override public String renderReport(String reportId) {
        long t0 = System.nanoTime();
        try {
            System.out.println("[Log] render(" + reportId + ") -> start");
            String res = delegate.renderReport(reportId);
            long ms = (System.nanoTime() - t0) / 1_000_000;
            System.out.println("[Log] render(" + reportId + ") -> ok in " + ms + " ms");
            return res;
        } catch (RuntimeException ex) {
            long ms = (System.nanoTime() - t0) / 1_000_000;
            System.out.println("[Log] render(" + reportId + ") -> FAIL in " + ms + " ms : " + ex);
            throw ex;
        }
    }
}

/* ---------- Client / Demo ---------- */
public class ProxyDemo {
    public static void main(String[] args) {
        // Compose proxies: auth → cache → logging → lazy(real)
        ReportService service =
            new SecuredReportProxy(                      // access control first
                new CachingReportProxy(                  // then cache
                    new LoggingReportProxy(              // then log timing
                        new LazyReportProxy(RealReportService::new) // lazy creation
                    ),
                    10_000L
                ),
                "REPORT_READ"
            );

        // 1) Unauthorized call
        SecurityContext.setRoles(); // no roles
        try { service.renderReport("R-100"); } catch (SecurityException e) {
            System.out.println("Expected: " + e.getMessage());
        }

        // 2) Authorized calls
        SecurityContext.setRoles("REPORT_READ");
        String a = service.renderReport("R-100"); // warm-up + miss + render
        String b = service.renderReport("R-100"); // cache hit, fast
        String c = service.renderReport("R-200"); // different key -> miss + render

        System.out.println("A=" + a);
        System.out.println("B=" + b);
        System.out.println("C=" + c);
    }
}
```

**Notes on the example**

-   `ReportService` is the **Subject**; `RealReportService` is the **RealSubject**.

-   **Virtual proxy** defers expensive construction until first call.

-   **Protection proxy** checks a role before touching downstream proxies.

-   **Caching proxy** short-circuits repeated calls.

-   **Logging proxy** adds observability.  
    Order is deliberate: *auth → cache → log → lazy(real)* (you could also log outermost if you want to trace denials).


## Known Uses

-   **Java RMI / EJB / gRPC stubs**: local objects representing remote services.

-   **Hibernate/JPA**: lazy-loading proxies for entities/collections.

-   **Spring AOP**: proxies add transactions, security, caching around beans.

-   **Swing/ImageIcon** (classic): defer image loading/painting via a virtual proxy.

-   **HTTP clients**: caching/authorization proxies (OkHttp interceptors conceptually similar).


## Related Patterns

-   **Decorator**: also wraps with same interface, but focuses on **adding behavior**; Proxy focuses on **access control or indirection**. (They can look identical structurally.)

-   **Adapter**: changes the interface to be compatible; Proxy **preserves** the interface.

-   **Facade**: simplifies a subsystem with a new API; Proxy keeps the API but inserts a stand-in.

-   **Bridge**: separates abstraction from implementation; a proxy is usually for a **single implementation**.

-   **Flyweight**: shares instances to save memory; can be used inside a proxy cache.

-   **Chain of Responsibility**: you can compose multiple proxies (as shown) forming a chain.
