
# Interpreter — GoF Behavioral Pattern

## Pattern Name and Classification

**Name:** Interpreter  
**Category:** Behavioral design pattern

## Intent

Given a language, define a representation for its grammar along with an **interpreter** that uses the representation to **evaluate sentences** in the language.

## Also Known As

Expression Tree, AST Interpreter, Little Language

## Motivation (Forces)

-   You need to support a **small, domain-specific language** (DSL) with **stable grammar** (e.g., filtering rules, arithmetic formulas, alert conditions).

-   You want a **readable, composable** in-memory representation (an expression tree) and an easy way to **evaluate** or **transform** it (evaluate, pretty-print, optimize).

-   You prefer embedding the language directly in code rather than bringing in a full parser generator, because the grammar is **simple** and changes are **infrequent**.


## Applicability

Use Interpreter when:

-   The language is **simple** and describes a **well-bounded** problem (predicates, math formulas, patterns).

-   You want to **compose** complex expressions from a **small set** of primitives.

-   You benefit from **multiple interpreters** over the same AST (evaluation, static checks, code gen, SQL translation).

-   Performance is acceptable with **recursive evaluation**; if you need high throughput or complex grammars, consider a parser/bytecode compiler.


## Structure

-   **AbstractExpression** — declares the `interpret(Context)` operation.

-   **TerminalExpression** — represents leaves (literals, variables, constants).

-   **NonterminalExpression** — represents grammar rules composed of sub-expressions.

-   **Context** — holds external information for interpretation (variable bindings, environment).

-   **Client/Parser** — builds the AST (manually or via a simple parser) and triggers interpretation.


```lua
+----------------------+
            |   AbstractExpression |
            |  + interpret(ctx)    |
            +----------+-----------+
                       ^
          +------------+------------+
          |                         |
 +--------------------+   +----------------------+
 |  TerminalExpression|   |  NonterminalExpression|
 +--------------------+   +----------------------+
                                   ^
                                   |
                            (composes children)
```

## Participants

-   **Context**: external, mutable data used during evaluation (e.g., variable map).

-   **AbstractExpression**: common interface for all nodes.

-   **TerminalExpression**: literals, identifiers; evaluates directly from the context.

-   **NonterminalExpression**: combines subexpressions (e.g., `And`, `Or`, `Add`, `Compare`).

-   **Client/Parser**: builds the expression tree from source (string or structured input).


## Collaboration

-   The Client (or Parser) constructs an AST out of **Terminal** and **Nonterminal** nodes.

-   The Client supplies a **Context** and calls `interpret(ctx)` on the root.

-   Each node recursively interprets its children and **combines** results according to the rule it represents.


## Consequences

**Benefits**

-   **Extensible**: add new rules by adding new node classes without touching others.

-   **Composable**: expressions are trees; easy to build, transform, or traverse (e.g., with Visitor).

-   **Multiple interpretations**: the same AST can be evaluated, pretty-printed, optimized, or translated.


**Liabilities**

-   **Class proliferation** for each grammar rule; many small objects.

-   **Performance**: recursive evaluation can be slower than compiled forms.

-   Not ideal for **complex** grammars (maintenance cost); prefer parser generators/compilers then.


## Implementation

-   Keep the grammar **small** and the AST **immutable** (thread-safe, sharable).

-   Separate **parsing** from **evaluation**; even a simple recursive-descent parser keeps responsibilities clear.

-   Use **Value Objects/records** for tokens and literals.

-   Consider a **Visitor** if you will add many operations on the AST (eval, type-check, toSQL).

-   Add a **Context** abstraction that supports variable lookup and type coercion where appropriate.

-   For performance-sensitive scenarios: memoize subtrees, precompute constant folds, or compile AST to a lambda/bytecode.


---

## Sample Code (Java)

**Scenario:** A tiny boolean rule language for filtering events.  
Grammar (simplified, case-insensitive keywords):

```go
expr        := or
or          := and ( OR and )*
and         := not ( AND not )*
not         := NOT not | primary
primary     := '(' expr ')' | comparison | booleanIdent
comparison  := ident op literalOrIdent
op          := '=' | '!=' | '>' | '>=' | '<' | '<='
literalOrIdent := STRING | NUMBER | TRUE | FALSE | ident
booleanIdent := ident               // must resolve to boolean in context
ident       := [A-Za-z_][A-Za-z0-9_]*
STRING      := '...'(single quotes)
NUMBER      := digits[.digits]?
```

We implement:

-   A **lexer** and **recursive-descent parser** to build an AST,

-   An **interpreter** that evaluates the AST against a `Map<String,Object>` context.


```java
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/* ===========================
   Lexical Analysis (Tokenizer)
   =========================== */
enum TokenType {
    IDENT, NUMBER, STRING, TRUE, FALSE,
    AND, OR, NOT,
    EQ, NE, GT, GE, LT, LE,
    LPAREN, RPAREN, EOF
}

record Token(TokenType type, String text) {
    public String toString() { return type + (text == null ? "" : "(" + text + ")"); }
}

final class Lexer {
    private final String s;
    private int i = 0;

    Lexer(String s) { this.s = s; }

    Token next() {
        skipWs();
        if (i >= s.length()) return new Token(TokenType.EOF, null);
        char c = s.charAt(i);

        // Operators and parens
        if (c == '(') { i++; return new Token(TokenType.LPAREN, "("); }
        if (c == ')') { i++; return new Token(TokenType.RPAREN, ")"); }
        if (c == '=' ) { i++; return new Token(TokenType.EQ, "="); }
        if (c == '!' && peek('=') ) { i+=2; return new Token(TokenType.NE, "!="); }
        if (c == '>' && peek('=') ) { i+=2; return new Token(TokenType.GE, ">="); }
        if (c == '<' && peek('=') ) { i+=2; return new Token(TokenType.LE, "<="); }
        if (c == '>') { i++; return new Token(TokenType.GT, ">"); }
        if (c == '<') { i++; return new Token(TokenType.LT, "<"); }

        // String literal: '...'
        if (c == '\'') {
            i++; StringBuilder sb = new StringBuilder();
            while (i < s.length()) {
                char ch = s.charAt(i++);
                if (ch == '\'') break;
                if (ch == '\\' && i < s.length()) { // simple escape
                    char esc = s.charAt(i++);
                    sb.append(esc);
                } else sb.append(ch);
            }
            return new Token(TokenType.STRING, sb.toString());
        }

        // Number
        if (Character.isDigit(c)) {
            int start = i++;
            while (i < s.length() && Character.isDigit(s.charAt(i))) i++;
            if (i < s.length() && s.charAt(i) == '.') {
                i++;
                while (i < s.length() && Character.isDigit(s.charAt(i))) i++;
            }
            return new Token(TokenType.NUMBER, s.substring(start, i));
        }

        // Identifier / keyword
        if (Character.isLetter(c) || c == '_') {
            int start = i++;
            while (i < s.length() && (Character.isLetterOrDigit(s.charAt(i)) || s.charAt(i) == '_')) i++;
            String ident = s.substring(start, i);
            String kw = ident.toUpperCase(Locale.ROOT);
            return switch (kw) {
                case "AND" -> new Token(TokenType.AND, ident);
                case "OR"  -> new Token(TokenType.OR, ident);
                case "NOT" -> new Token(TokenType.NOT, ident);
                case "TRUE" -> new Token(TokenType.TRUE, ident);
                case "FALSE" -> new Token(TokenType.FALSE, ident);
                default -> new Token(TokenType.IDENT, ident);
            };
        }

        throw new IllegalArgumentException("Unexpected char at " + i + ": '" + c + "'");
    }

    private void skipWs() {
        while (i < s.length() && Character.isWhitespace(s.charAt(i))) i++;
    }
    private boolean peek(char next) {
        return (i + 1 < s.length()) && (s.charAt(i + 1) == next);
    }
}

/* ===========================
   AST (Expressions) & Context
   =========================== */
interface Expr {
    boolean interpret(Map<String, Object> ctx);
}

final class BoolLiteral implements Expr {
    final boolean value;
    BoolLiteral(boolean v) { this.value = v; }
    public boolean interpret(Map<String, Object> ctx) { return value; }
}

final class Identifier implements Expr {
    final String name;
    Identifier(String n) { this.name = n; }
    public boolean interpret(Map<String, Object> ctx) {
        Object v = ctx.get(name);
        if (v instanceof Boolean b) return b;
        if (v instanceof Number n) return n.doubleValue() != 0.0;
        if (v instanceof String s) return !s.isEmpty();
        return false;
    }
    public Object value(Map<String, Object> ctx) { return ctx.get(name); }
}

enum CmpOp { EQ, NE, GT, GE, LT, LE }

final class Comparison implements Expr {
    final Identifier left;
    final CmpOp op;
    final Expr right; // literal or identifier (must yield a value when evaluated)
    Comparison(Identifier l, CmpOp op, Expr r) { this.left = l; this.op = op; this.right = r; }
    public boolean interpret(Map<String, Object> ctx) {
        Object a = left.value(ctx);
        Object b = valueOf(right, ctx);
        int c = compare(a, b);
        return switch (op) {
            case EQ -> c == 0;
            case NE -> c != 0;
            case GT -> c > 0;
            case GE -> c >= 0;
            case LT -> c < 0;
            case LE -> c <= 0;
        };
    }
    private static Object valueOf(Expr e, Map<String,Object> ctx) {
        if (e instanceof StringLiteral sl) return sl.value;
        if (e instanceof NumberLiteral nl) return nl.value;
        if (e instanceof BoolLiteral bl) return bl.value;
        if (e instanceof Identifier id) return id.value(ctx);
        throw new IllegalStateException("Unsupported right operand: " + e);
    }
    private static int compare(Object a, Object b) {
        if (a == null || b == null) return a == b ? 0 : (a == null ? -1 : 1);
        if (a instanceof Number an && b instanceof Number bn) {
            double d = an.doubleValue() - bn.doubleValue();
            return d == 0.0 ? 0 : (d < 0 ? -1 : 1);
        }
        // case-insensitive string compare for convenience
        String sa = String.valueOf(a), sb = String.valueOf(b);
        return sa.compareToIgnoreCase(sb);
    }
}

final class And implements Expr {
    final Expr left, right;
    And(Expr l, Expr r) { this.left = l; this.right = r; }
    public boolean interpret(Map<String, Object> ctx) { return left.interpret(ctx) && right.interpret(ctx); }
}

final class Or implements Expr {
    final Expr left, right;
    Or(Expr l, Expr r) { this.left = l; this.right = r; }
    public boolean interpret(Map<String, Object> ctx) { return left.interpret(ctx) || right.interpret(ctx); }
}

final class Not implements Expr {
    final Expr inner;
    Not(Expr e) { this.inner = e; }
    public boolean interpret(Map<String, Object> ctx) { return !inner.interpret(ctx); }
}

// Terminals for literals
final class StringLiteral implements Expr {
    final String value;
    StringLiteral(String v) { this.value = v; }
    public boolean interpret(Map<String, Object> ctx) { return value != null && !value.isEmpty(); }
}
final class NumberLiteral implements Expr {
    final double value;
    NumberLiteral(double v) { this.value = v; }
    public boolean interpret(Map<String, Object> ctx) { return value != 0.0; }
}

/* ===========================
   Parser (Recursive Descent)
   =========================== */
final class Parser {
    private final Lexer lexer;
    private Token lookahead;

    Parser(String input) {
        this.lexer = new Lexer(input);
        this.lookahead = lexer.next();
    }

    Expr parse() {
        Expr e = parseOr();
        expect(TokenType.EOF);
        return e;
    }

    private Expr parseOr() {
        Expr left = parseAnd();
        while (lookahead.type() == TokenType.OR) {
            consume();
            Expr right = parseAnd();
            left = new Or(left, right);
        }
        return left;
    }

    private Expr parseAnd() {
        Expr left = parseNot();
        while (lookahead.type() == TokenType.AND) {
            consume();
            Expr right = parseNot();
            left = new And(left, right);
        }
        return left;
    }

    private Expr parseNot() {
        if (lookahead.type() == TokenType.NOT) {
            consume();
            return new Not(parseNot());
        }
        return parsePrimary();
    }

    private Expr parsePrimary() {
        if (lookahead.type() == TokenType.LPAREN) {
            consume();
            Expr e = parseOr();
            expect(TokenType.RPAREN);
            return e;
        }
        // comparison or boolean identifier
        if (lookahead.type() == TokenType.IDENT) {
            Identifier id = new Identifier(lookahead.text());
            consume();
            if (isCmpOp(lookahead.type())) {
                CmpOp op = toOp(lookahead.type());
                consume();
                Expr rhs = parseOperand();
                return new Comparison(id, op, rhs);
            }
            // bare boolean variable
            return id;
        }
        // literals
        if (lookahead.type() == TokenType.TRUE)  { consume(); return new BoolLiteral(true); }
        if (lookahead.type() == TokenType.FALSE) { consume(); return new BoolLiteral(false); }
        if (lookahead.type() == TokenType.STRING){ String v = lookahead.text(); consume(); return new StringLiteral(v); }
        if (lookahead.type() == TokenType.NUMBER){ double d = Double.parseDouble(lookahead.text()); consume(); return new NumberLiteral(d); }

        throw error("Unexpected token: " + lookahead);
    }

    private Expr parseOperand() {
        return switch (lookahead.type()) {
            case STRING -> { String v = lookahead.text(); consume(); yield new StringLiteral(v); }
            case NUMBER -> { double d = Double.parseDouble(lookahead.text()); consume(); yield new NumberLiteral(d); }
            case TRUE -> { consume(); yield new BoolLiteral(true); }
            case FALSE -> { consume(); yield new BoolLiteral(false); }
            case IDENT -> { Identifier id = new Identifier(lookahead.text()); consume(); yield id; }
            default -> throw error("Expected literal or identifier, got " + lookahead);
        };
    }

    private boolean isCmpOp(TokenType t) {
        return switch (t) {
            case EQ, NE, GT, GE, LT, LE -> true;
            default -> false;
        };
    }
    private CmpOp toOp(TokenType t) {
        return switch (t) {
            case EQ -> CmpOp.EQ;
            case NE -> CmpOp.NE;
            case GT -> CmpOp.GT;
            case GE -> CmpOp.GE;
            case LT -> CmpOp.LT;
            case LE -> CmpOp.LE;
            default -> throw error("Not a comparison operator: " + t);
        };
    }

    private void consume() { lookahead = lexer.next(); }
    private void expect(TokenType t) {
        if (lookahead.type() != t) throw error("Expected " + t + " but found " + lookahead.type());
        consume();
    }
    private RuntimeException error(String msg) { return new RuntimeException(msg); }
}

/* ===========================
   Demo
   =========================== */
public class InterpreterDemo {
    public static void main(String[] args) {
        // Example rule:
        String rule = "(country = 'AT' AND age >= 18) OR (premium = true AND NOT banned)";

        Parser parser = new Parser(rule);
        Expr expr = parser.parse();

        Map<String,Object> alice = Map.of(
                "country", "AT",
                "age", 17,
                "premium", false,
                "banned", false
        );

        Map<String,Object> bob = Map.of(
                "country", "DE",
                "age", 25,
                "premium", true,
                "banned", false
        );

        Map<String,Object> eve = Map.of(
                "country", "DE",
                "age", 16,
                "premium", false,
                "banned", true
        );

        System.out.println("Alice => " + expr.interpret(alice)); // true (AT & >=18? no, but wait: 17 -> false; however second disjunct? premium=false, so false; overall false) <-- adjust alice age:
        alice = new HashMap<>(alice); ((HashMap<String,Object>)alice).put("age", 18);
        System.out.println("Alice(18) => " + expr.interpret(alice)); // true
        System.out.println("Bob   => " + expr.interpret(bob));   // true  (premium & not banned)
        System.out.println("Eve   => " + expr.interpret(eve));   // false
    }
}
```

### Notes on the example

-   The **AST** implements the classic Interpreter roles (`TerminalExpression` for literals/identifiers and `NonterminalExpression` for `And/Or/Not/Comparison`).

-   The **Context** is a `Map<String,Object>`; the interpreter performs minimal **type coercion** for comparisons.

-   Parsing and interpreting are **separate**; you could add a second interpreter to translate the AST to SQL or to validate variables against a schema.


> Extensions you can add quickly:
>
> -   New operator `IN ('AT','DE')` via a `Membership` node.
>
> -   Arithmetic expressions and computed fields with `+ - * /`.
>
> -   Constant folding to pre-evaluate subtrees with only literals.
>

## Known Uses

-   **XPath/XQuery** engines (interpreting path expressions against XML/DOM/trees).

-   **Regular expression** engines (pattern ASTs evaluated over text).

-   **Rule engines** and **feature flags** (boolean DSLs).

-   **Search query languages** (e.g., Lucene query parser → AST → interpreter/planner).

-   **Template engines** (EL/OGNL/MVEL) interpreting expressions against a model.


## Related Patterns

-   **Composite**: Expression trees are composites; Interpreter is essentially “Composite + evaluate”.

-   **Visitor**: Add operations (pretty-print, type-check, toSQL) without changing node classes.

-   **Flyweight**: Share immutable literal nodes or operator singletons if you build many trees.

-   **Builder**: Fluent builders can help assemble ASTs programmatically.

-   **Strategy**: Alternative evaluation strategies (e.g., short-circuit vs. three-valued logic).

-   **Facade**: Provide a simple API (`evaluate(rule, context)`) hiding parser + interpreter internals.

-   **Command**: A parsed expression can be wrapped as a command to defer execution.
