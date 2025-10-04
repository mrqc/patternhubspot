# Command — UI/UX Pattern

## Pattern Name and Classification

-   **Name:** Command
    
-   **Classification:** UI/UX Interaction & Application Architecture Pattern / Action Abstraction with Optional Undo/Redo
    

## Intent

Represent user actions as **first-class command objects** that encapsulate *what to do*, *how to do it*, and optionally *how to undo it*. Decouple **invocation** (menus, buttons, shortcuts, command palette, voice, automation) from **execution** (domain logic), while enabling **enablement/visibility logic, telemetry, undo/redo, and consistent UX**.

## Also Known As

-   Action (Swing/IntelliJ “Action System”)
    
-   Invoker–Command–Receiver (GoF Command, applied to UI)
    
-   Command Palette / Command Bar (UX manifestation)
    
-   Intent (Android), NSAction/NSMenuItem (Apple platforms)
    

## Motivation (Forces)

-   **Multiple entry points:** the same action appears in toolbar, context menu, keyboard shortcut, command palette.
    
-   **Consistency & accessibility:** single source of truth for labels, enabled/disabled state, ARIA/hints, shortcuts.
    
-   **Undo/redo & safety:** many UI actions must be reversible.
    
-   **Testability & automation:** commands are scriptable and can be logged/telemetrized.
    
-   **Modularity:** features ship as self-contained commands.  
    Tensions: keeping **enablement** fast and context-aware, avoiding **brittle coupling** to UI widgets, and managing **long-running** commands (progress, cancellation).
    

## Applicability

Use the Command pattern when:

-   Actions need **multiple invokers** (menu, shortcut, toolbar, API).
    
-   You require **undo/redo** or optimistic UI with rollback.
    
-   You want a **command palette** or macro/automation features.
    
-   You want to enforce **role/permission** checks and **feature flags** consistently.
    

Be cautious when:

-   Actions are **purely transient UI effects** (animations) with no domain meaning.
    
-   You have extremely **simple apps** where indirection adds overhead.
    

## Structure

```less
[Invoker]
  Button / Menu / Shortcut / Palette / Voice / API
        │ triggers
        ▼
[Command] — execute(ctx) / isEnabled(ctx) / undo(ctx)?
        │ calls
        ▼
[Receiver(s) / Domain]: Document, Selection, Services, Gateways
        │
   [History/UndoStack], [CommandRegistry], [Keymap], [Telemetry]
```

## Participants

-   **Invoker:** any UI/control that initiates an action (button, menu, shortcut, command palette).
    
-   **Command:** object with id, metadata (label, icon, shortcut), `isEnabled(ctx)`, `execute(ctx)`, optional `undo(ctx)`.
    
-   **Receiver:** domain model/service that actually performs work.
    
-   **Command Registry:** discovery, lookup, and search for commands.
    
-   **Keymap/Bindings:** maps input gestures to command ids.
    
-   **History/Undo Manager:** records undoable commands.
    
-   **Context:** current app state (selection, document, permissions).
    
-   **Telemetry/Security:** logs usage, checks authorization/feature flags.
    

## Collaboration

1.  Invoker asks **CommandRegistry** for a command (by id or search).
    
2.  UI queries `isEnabled(ctx)` to set **enabled/disabled** state.
    
3.  On activation, invoker calls `execute(ctx)`.
    
4.  If undoable, command pushes an **inverse** (or memento) to **UndoStack**.
    
5.  Telemetry/analytics/logging record the invocation.
    
6.  Undo/redo invokers call `undo(ctx)` / re-`execute(ctx)`.
    

## Consequences

**Benefits**

-   **Single point of truth** for action semantics and presentation.
    
-   **Reusability:** same command plumbed into menus, shortcuts, palette, APIs.
    
-   **Undo/redo** support by design.
    
-   **Testability/automation:** commands run headless in tests or scripts.
    
-   **Extensibility:** plug-in systems expose new commands cleanly.
    

**Liabilities**

-   Slight **indirection** overhead; simple apps may not need it.
    
-   Poorly bounded **context** objects can become god-objects.
    
-   Long-running commands need **progress/cancel** patterns to avoid frozen UIs.
    

## Implementation

### Design Guidelines

-   Keep `Command` interface **small**: id, label, optional icon/shortcut, `isEnabled(ctx)`, `execute(ctx)`, optional `isUndoable/undo`.
    
-   Make commands **pure application intent**; UI widgets only *invoke*.
    
-   Store **enablement rules** (e.g., selection not empty, permission X) in the command.
    
-   Use a **Context** value object (current selection, document, user) to avoid global state.
    
-   Implement **Undo** via:
    
    -   **Memento** (capture pre-state), or
        
    -   **Inverse command** (explicit undo logic).
        
-   Provide a **Command Palette** (searchable list) using registry metadata.
    
-   Centralize **key bindings** in a keymap; avoid hardcoding in widgets.
    
-   Add **telemetry hooks** and **policy checks** (RBAC/feature flags) before `execute`.
    
-   For async work, return a **Future/CompletionStage**, show progress, and support **cancellation**.
    

---

## Sample Code (Java 17, single-file demo)

A minimal command framework with: registry, keymap, undo stack, and three text-editing commands (Copy, Cut, Paste).  
UI is simulated via method calls (buttons/shortcuts/command palette would call the same API).

```java
// CommandPatternDemo.java
import java.util.*;
import java.util.function.Predicate;

/* ---------- Core abstractions ---------- */
interface Command {
  String id();
  String title();
  Optional<String> shortcut();                    // e.g., "Ctrl+C"
  boolean isEnabled(Context ctx);
  void execute(Context ctx);
  default boolean isUndoable() { return false; }
  default void undo(Context ctx) { /* no-op */ }
}

final class Context {
  final Document doc;
  final Clipboard clipboard;
  final User user;
  Context(Document doc, Clipboard clipboard, User user) { this.doc = doc; this.clipboard = clipboard; this.user = user; }
}

final class User { final String role; User(String role){ this.role = role; } boolean hasRole(String r){ return Objects.equals(role, r); } }

final class Document {
  private StringBuilder content = new StringBuilder();
  private int selStart = 0, selEnd = 0;
  Document(String text) { content.append(text); }
  String text() { return content.toString(); }
  void select(int start, int end) { this.selStart = Math.max(0, Math.min(start, content.length())); this.selEnd = Math.max(selStart, Math.min(end, content.length())); }
  boolean hasSelection() { return selEnd > selStart; }
  String selected() { return content.substring(selStart, selEnd); }
  void replaceSelection(String s) {
    content.replace(selStart, selEnd, s);
    // place caret after inserted text
    int pos = selStart + s.length();
    selStart = selEnd = pos;
  }
}

final class Clipboard { String data = ""; }

/* ---------- Registry, keymap, palette ---------- */
final class CommandRegistry {
  private final Map<String, Command> byId = new HashMap<>();
  CommandRegistry register(Command c) { byId.put(c.id(), c); return this; }
  Optional<Command> get(String id) { return Optional.ofNullable(byId.get(id)); }
  List<Command> search(String query, Context ctx) {
    String q = query.toLowerCase(Locale.ROOT).trim();
    return byId.values().stream()
        .filter(c -> c.title().toLowerCase(Locale.ROOT).contains(q) || c.id().toLowerCase(Locale.ROOT).contains(q))
        .filter(c -> c.isEnabled(ctx))
        .sorted(Comparator.comparing(Command::title))
        .toList();
  }
  Collection<Command> all() { return byId.values(); }
}

final class Keymap {
  private final Map<String, String> keyToCommandId = new HashMap<>();
  Keymap bind(String shortcut, String commandId) { keyToCommandId.put(shortcut, commandId); return this; }
  Optional<String> lookup(String shortcut) { return Optional.ofNullable(keyToCommandId.get(shortcut)); }
}

final class UndoStack {
  private final Deque<Command> stack = new ArrayDeque<>();
  void push(Command c) { stack.push(c); }
  boolean canUndo() { return !stack.isEmpty(); }
  void undo(Context ctx) { if (!stack.isEmpty()) { Command c = stack.pop(); c.undo(ctx); } }
}

/* ---------- Concrete commands ---------- */
abstract class BaseCommand implements Command {
  private final String id, title, shortcut;
  BaseCommand(String id, String title, String shortcut) { this.id = id; this.title = title; this.shortcut = shortcut; }
  public String id() { return id; }
  public String title() { return title; }
  public Optional<String> shortcut() { return Optional.ofNullable(shortcut); }
}

final class CopyCommand extends BaseCommand {
  CopyCommand() { super("edit.copy", "Copy", "Ctrl+C"); }
  public boolean isEnabled(Context ctx) { return ctx.doc.hasSelection(); }
  public void execute(Context ctx) { ctx.clipboard.data = ctx.doc.selected(); }
}

final class CutCommand extends BaseCommand {
  private String memento = null;
  CutCommand() { super("edit.cut", "Cut", "Ctrl+X"); }
  public boolean isEnabled(Context ctx) { return ctx.doc.hasSelection() && ctx.user.hasRole("editor"); }
  public void execute(Context ctx) {
    memento = ctx.doc.text();                     // memento for undo
    ctx.clipboard.data = ctx.doc.selected();
    ctx.doc.replaceSelection("");
  }
  public boolean isUndoable() { return true; }
  public void undo(Context ctx) { if (memento != null) ctx.doc.select(0, ctx.doc.text().length()); ctx.doc.replaceSelection(memento); }
}

final class PasteCommand extends BaseCommand {
  private String memento = null;
  PasteCommand() { super("edit.paste", "Paste", "Ctrl+V"); }
  public boolean isEnabled(Context ctx) { return !ctx.clipboard.data.isEmpty() && ctx.user.hasRole("editor"); }
  public void execute(Context ctx) { memento = ctx.doc.text(); ctx.doc.replaceSelection(ctx.clipboard.data); }
  public boolean isUndoable() { return true; }
  public void undo(Context ctx) { if (memento != null) { ctx.doc.select(0, ctx.doc.text().length()); ctx.doc.replaceSelection(memento); } }
}

/* ---------- Invokers (simulated) ---------- */
final class Invokers {
  static void invokeById(CommandRegistry reg, UndoStack undo, Context ctx, String id) {
    reg.get(id).filter(c -> c.isEnabled(ctx)).ifPresent(c -> {
      c.execute(ctx);
      if (c.isUndoable()) undo.push(c);
    });
  }
  static void handleShortcut(CommandRegistry reg, Keymap km, UndoStack undo, Context ctx, String shortcut) {
    km.lookup(shortcut).ifPresent(id -> invokeById(reg, undo, ctx, id));
  }
  static void openPalette(CommandRegistry reg, Context ctx, String query, Predicate<Command> onPick) {
    List<Command> items = reg.search(query, ctx);
    // Render items in a UI; here we just simulate by picking the first enabled item.
    if (!items.isEmpty()) onPick.test(items.get(0));
  }
}

/* ---------- Demo ---------- */
public class CommandPatternDemo {
  public static void main(String[] args) {
    var doc = new Document("Hello world!");
    var ctx = new Context(doc, new Clipboard(), new User("editor"));
    var reg = new CommandRegistry()
        .register(new CopyCommand())
        .register(new CutCommand())
        .register(new PasteCommand());

    var km = new Keymap().bind("Ctrl+C", "edit.copy").bind("Ctrl+X", "edit.cut").bind("Ctrl+V", "edit.paste");
    var undo = new UndoStack();

    // select "world"
    doc.select(6, 11);

    // Shortcut: copy, then cut, then paste at end
    Invokers.handleShortcut(reg, km, undo, ctx, "Ctrl+C");
    Invokers.handleShortcut(reg, km, undo, ctx, "Ctrl+X");
    // move caret to end
    doc.select(doc.text().length(), doc.text().length());
    Invokers.handleShortcut(reg, km, undo, ctx, "Ctrl+V");

    System.out.println("Doc after paste: " + doc.text()); // "Hello world!"
    // Undo paste
    if (undo.canUndo()) undo.undo(ctx);
    System.out.println("After undo: " + doc.text());      // "Hello !"
  }
}
```

**Notes**

-   Commands carry **metadata** (id/title/shortcut), **enablement**, **execution**, and **undo**.
    
-   UI widgets (buttons/menus/shortcuts/palette) are pure **invokers** that call the same `invokeById`.
    
-   Permissions are handled in `isEnabled(ctx)` (e.g., editor role).
    
-   The sample uses a **memento** approach for undo; in production you might store fine-grained diffs.
    

## Known Uses

-   **VS Code / IntelliJ**: “Action System” + Command Palette, consistent across menu, shortcut, palette.
    
-   **Photoshop/Figma**: commands with undo/redo stacks for editing operations.
    
-   **Slack/Teams**: slash commands (text invoker) calling command handlers.
    
-   **macOS/iOS**: NSMenu/NSResponder chain routes first responder commands across multiple invokers.
    
-   **Design systems**: central Action/Command abstractions for menu/toolbar consistency.
    

## Related Patterns

-   **GoF Command:** underlying OO pattern (invoker/receiver/command).
    
-   **Memento:** snapshot state for **undo/redo**.
    
-   **Mediator / Event Bus:** coordinate cross-component effects after a command executes.
    
-   **CQRS:** commands (state-changing) vs. queries (read-only).
    
-   **Toolbar/Menu/Shortcut Patterns:** different invokers bound to the same command.
    
-   **Macro/Automation:** sequences of commands scripted; palettes often expose these.
    

---

## Implementation Tips

-   Keep commands **idempotent where reasonable** or guard re-entrancy.
    
-   Provide **global enablement** + **contextual enablement** (selection, permissions, feature flags).
    
-   Add **progress & cancellation** for long operations (return `CompletionStage`).
    
-   Centralize **icons/labels/shortcuts** in the command to keep UI consistent and localizable.
    
-   Expose a **searchable palette** with fuzzy search over command titles and ids.
    
-   Log command usage for **telemetry** and surface to product analytics.
    
-   Write **unit tests** per command (enabled/disabled, execute, undo) and **UI tests** for critical invokers only.
