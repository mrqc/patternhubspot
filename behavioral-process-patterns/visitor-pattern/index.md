# Visitor — Behavioral / Process Pattern

## Pattern Name and Classification

**Visitor** — *Behavioral / Process* pattern that separates **algorithms** from the **object structure** they operate on via **double dispatch** (`element.accept(visitor)` → `visitor.visit(element)`).

---

## Intent

Add **new operations** over a **stable object structure** without modifying those classes, by externalizing behavior into **Visitor** objects.

---

## Also Known As

-   **Double Dispatch**

-   **External Polymorphism**

-   **Walker** (colloquial, in ASTs)


---

## Motivation (Forces)

-   You have a **fixed hierarchy** (AST, UI widgets, file system nodes, domain model) and you frequently add **new operations** (pretty-print, evaluate, validate, type-check, export).

-   Putting every operation inside each class causes **bloat** and **cascading edits**.

-   Visitor localizes each operation in one class while leveraging **polymorphic dispatch** across node types.


**Trade-offs**

-   Adding a **new element type** forces changes to **all** Visitors (closed for structure changes).

-   Boilerplate visit methods; can be mitigated with **default methods**, **pattern matching**, or **acyclic visitor** variants.


---

## Applicability

Use Visitor when:

-   The **set of element types** is relatively **stable**, but operations change often.

-   You want to perform **multiple unrelated traversals** over the same structure.

-   You need **accumulated state** or **results** during traversal.


Avoid when:

-   Element types change frequently. Consider **pattern matching** (Java 21+), **Strategy**, or methods on elements.


---

## Structure

```arduino
+------------------+             +-------------------------+
Client ─▶ Element          │   accept    │ Visitor                 │
        │ + accept(v) ─────┼───────────▶ │ + visit(ConcreteA)      │
        +--------▲---------+             │ + visit(ConcreteB) ...  │
                 │                       +-----------▲-------------+
     +-----------┴------------+                       │
     | ConcreteA / ConcreteB  |          +------------┴-------------+
     | override accept(v) {   |          | ConcreteVisitors (ops)   |
     |   v.visit(this); }     |          | (Printer, Evaluator, …)  |
     +------------------------+          +--------------------------+
```

(Double dispatch picks **both** the element and visitor types.)

---

## Participants

-   **Element** — interface with `accept(Visitor)`.

-   **Concrete Elements** — implement `accept` and expose getters for data.

-   **Visitor** — interface with a `visit(X)` for each element type.

-   **Concrete Visitors** — algorithms (pretty-print, evaluate, type-check, …).

-   (Optional) **BaseVisitor** with default methods to reduce boilerplate.


---

## Collaboration

1.  Client builds/has an element structure (e.g., AST).

2.  Client calls `root.accept(visitor)`.

3.  Each element calls back `visitor.visit(this)` (double dispatch).

4.  Visitor executes operation, possibly recursing into children.


---

## Consequences

**Benefits**

-   **Open for new operations**: add a Visitor, no element edits.

-   Operations are **localized** and easier to test.

-   Can carry **state/results** across traversal.


**Liabilities**

-   **Closed for new element types**: adding one touches all visitors.

-   Boilerplate; tight coupling between Visitor and element set.

-   Requires exposing element internals (getters) unless placed in same package.


---

## Implementation (Key Points)

-   Keep `Element.accept()` **final** (or trivial) and do traversal in Visitors.

-   Provide a **BaseVisitor** with no-op/default methods; visitors override what they need.

-   For results, either:

    -   mutate the visitor’s fields,

    -   return values via a **Result-returning Visitor** (generic), or

    -   use a small **Context** passed around.

-   If element set evolves often, consider **acyclic visitor**, **pattern matching**, or **double-dispatch by `instanceof`** as a pragmatic alternative.


---

## Sample Code (Java 17) — Arithmetic AST with three Visitors

Operations provided as **separate visitors**: Pretty Printer, Evaluator, and Constant Folder.

```java
import java.util.*;

// ===== 1) Element hierarchy (AST) =====
interface Expr {
  void accept(ExprVisitor v);
}

final class Num implements Expr {
  final double value;
  Num(double value) { this.value = value; }
  @Override public void accept(ExprVisitor v) { v.visit(this); }
}

final class Var implements Expr {
  final String name;
  Var(String name) { this.name = name; }
  @Override public void accept(ExprVisitor v) { v.visit(this); }
}

final class Add implements Expr {
  final Expr left, right;
  Add(Expr left, Expr right) { this.left = left; this.right = right; }
  @Override public void accept(ExprVisitor v) { v.visit(this); }
}

final class Mul implements Expr {
  final Expr left, right;
  Mul(Expr left, Expr right) { this.left = left; this.right = right; }
  @Override public void accept(ExprVisitor v) { v.visit(this); }
}

// ===== 2) Visitor interface & a base with defaults =====
interface ExprVisitor {
  default void visit(Num n) {}
  default void visit(Var v) {}
  default void visit(Add a) {}
  default void visit(Mul m) {}
}

// Helper: a Result-returning visitor using an internal stack
abstract class ResultVisitor<R> implements ExprVisitor {
  protected final Deque<R> stack = new ArrayDeque<>();
  public R result() { return stack.peek(); }

  // Utilities to traverse children in a consistent way
  protected void accept(Expr e) { e.accept(this); }
  protected R pop2AndApply(java.util.function.BiFunction<R,R,R> f) {
    R b = stack.pop(), a = stack.pop(); // left, then right pushed -> right is on top
    R r = f.apply(a, b); stack.push(r); return r;
  }
}

// ===== 3) Concrete visitors =====

// 3.a Pretty Printer (infix with parentheses)
final class PrettyPrinter extends ResultVisitor<String> {
  @Override public void visit(Num n) { stack.push(formatNum(n.value)); }
  @Override public void visit(Var v) { stack.push(v.name); }
  @Override public void visit(Add a) {
    accept(a.left); accept(a.right);
    pop2AndApply((L, R) -> "(" + L + " + " + R + ")");
  }
  @Override public void visit(Mul m) {
    accept(m.left); accept(m.right);
    pop2AndApply((L, R) -> "(" + L + " * " + R + ")");
  }
  private String formatNum(double d) {
    if (Math.floor(d) == d) return String.valueOf((long)d);
    return String.valueOf(d);
  }
}

// 3.b Evaluator with an environment for variables
final class Evaluator extends ResultVisitor<Double> {
  private final Map<String, Double> env;
  Evaluator(Map<String, Double> env) { this.env = env; }

  @Override public void visit(Num n) { stack.push(n.value); }
  @Override public void visit(Var v) {
    Double val = env.get(v.name);
    if (val == null) throw new IllegalArgumentException("Unbound variable: " + v.name);
    stack.push(val);
  }
  @Override public void visit(Add a) {
    accept(a.left); accept(a.right);
    pop2AndApply((L, R) -> L + R);
  }
  @Override public void visit(Mul m) {
    accept(m.left); accept(m.right);
    pop2AndApply((L, R) -> L * R);
  }
}

// 3.c Constant Folder (returns a new simplified Expr)
final class ConstantFolder extends ResultVisitor<Expr> {
  @Override public void visit(Num n) { stack.push(n); }
  @Override public void visit(Var v) { stack.push(v); }

  @Override public void visit(Add a) {
    accept(a.left); Expr l = stack.pop();
    accept(a.right); Expr r = stack.pop();
    stack.push(foldAdd(l, r));
  }

  @Override public void visit(Mul m) {
    accept(m.left); Expr l = stack.pop();
    accept(m.right); Expr r = stack.pop();
    stack.push(foldMul(l, r));
  }

  private Expr foldAdd(Expr l, Expr r) {
    if (l instanceof Num ln && r instanceof Num rn) return new Num(ln.value + rn.value);
    if (l instanceof Num ln && ln.value == 0) return r;
    if (r instanceof Num rn && rn.value == 0) return l;
    return new Add(l, r);
    }

  private Expr foldMul(Expr l, Expr r) {
    if (l instanceof Num ln && r instanceof Num rn) return new Num(ln.value * rn.value);
    if ((l instanceof Num ln && ln.value == 0) || (r instanceof Num rn && rn.value == 0)) return new Num(0);
    if (l instanceof Num ln && ln.value == 1) return r;
    if (r instanceof Num rn && rn.value == 1) return l;
    return new Mul(l, r);
  }
}

// ===== 4) Demo =====
public class VisitorDemo {
  public static void main(String[] args) {
    // Build AST: (x + 2) * (3 + 4)
    Expr ast = new Mul(
        new Add(new Var("x"), new Num(2)),
        new Add(new Num(3), new Num(4))
    );

    // Pretty print
    var pp = new PrettyPrinter();
    ast.accept(pp);
    System.out.println("AST: " + pp.result()); // ((x + 2) * (3 + 4))

    // Constant fold → (x + 2) * 7
    var cf = new ConstantFolder();
    ast.accept(cf);
    Expr folded = cf.result();

    var pp2 = new PrettyPrinter();
    folded.accept(pp2);
    System.out.println("Folded: " + pp2.result());

    // Evaluate with x = 5 → (5 + 2) * 7 = 49
    var eval = new Evaluator(Map.of("x", 5.0));
    folded.accept(eval);
    System.out.println("Value: " + eval.result());
  }
}
```

**Why this illustrates Visitor**

-   The element hierarchy (`Num`, `Var`, `Add`, `Mul`) never changes to add operations.

-   New operations (printing, evaluation, folding) are **new Visitors**.

-   **Double dispatch** chooses `visit(ConcreteType)` without `instanceof`.


---

## Known Uses

-   **Compilers/Interpreters**: visitors over ASTs (print, type-check, eval, codegen).

-   **UI Toolkits**: widget trees walked by renderers/layouters.

-   **File systems/Scenes**: export, collect stats, transform nodes.

-   **Domain models**: validation/export/reporting across heterogeneous entities.


---

## Related Patterns

-   **Composite** — typical host structure for visitors.

-   **Interpreter** — Visitors provide concrete operations over an AST.

-   **Strategy** — alternative when you need to swap one algorithm, not add many over a fixed structure.

-   **Acyclic Visitor / Pattern Matching** — variants to reduce coupling when element sets evolve.

-   **Double Dispatch / Multimethods** — underlying mechanism that Visitor simulates.
