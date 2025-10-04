# Circular Dependency

---

## Overview

**Type:** Software Design and Architecture Antipattern  
**Category:** Structural / Dependency Management Antipattern  
**Context:** Occurs when two or more modules, classes, or components depend on each other directly or indirectly, creating a cyclic relationship that prevents proper modularization, testing, and maintenance.

---

## Intent

To describe how cyclic dependencies between components or classes create tight coupling, hinder modular evolution, and lead to fragile systems that are difficult to refactor, test, or extend.

Circular dependencies represent a **violation of dependency direction** and **architectural layering principles**.

---

## Also Known As

-   **Cyclic Dependency**
    
-   **Circular Reference**
    
-   **Mutual Coupling**
    
-   **Dependency Loop**
    
-   **Tangled Hierarchy**
    

---

## Motivation (Forces)

Well-designed software systems rely on a directed acyclic graph (DAG) of dependencies: higher-level modules depend on lower-level modules, but not the other way around.

When this directionality is violated, a **circular dependency** emerges. These cycles introduce fragility and make independent development, compilation, and testing impossible.

Common forces leading to circular dependencies include:

-   **Lack of clear architectural boundaries** between layers or modules.
    
-   **Poor package design** with bidirectional class imports.
    
-   **Overuse of bidirectional associations** in domain models.
    
-   **Time pressure** causing shortcuts like “just import this class to fix it.”
    
-   **Inadequate dependency analysis tools.**
    
-   **Tight coupling between data and behavior** across layers.
    

---

## Applicability

You are likely facing a **Circular Dependency** if:

-   Two classes import each other directly or via a third class.
    
-   A package cannot compile independently because of cross-imports.
    
-   Unit testing one component requires loading unrelated ones.
    
-   Build tools report circular references (e.g., Maven cyclic dependency error).
    
-   Dependency inversion becomes impossible.
    
-   Changes in one module cause cascading changes across unrelated modules.
    

---

## Structure

```pgsql
+------------------+        depends on        +------------------+
|     Module A     | -----------------------> |     Module B     |
|                  |                          |                  |
+------------------+ <----------------------- +------------------+
             depends on A
```

This cycle forms a loop, breaking the principle of **unidirectional dependency flow**.

In large systems, this can involve multiple intermediate components (A → B → C → A).

---

## Participants

| Participant | Description |
| --- | --- |
| **Class A** | Defines logic that requires access to Class B. |
| **Class B** | Relies on Class A for functionality, creating a circular chain. |
| **Developers** | Introduce cross-dependencies without realizing their architectural impact. |
| **Build System** | Detects cycles and prevents modular compilation. |
| **Architects** | Struggle to enforce layering or dependency rules once cycles proliferate. |

---

## Collaboration

-   Two or more modules exchange references, often both holding strong knowledge of each other’s implementation details.
    
-   Circular references lead to **bidirectional data flow**, breaking encapsulation.
    
-   In runtime, cycles may cause **stack overflows**, **memory leaks**, or **initialization errors** in dependency injection frameworks (e.g., Spring).
    

---

## Consequences

### Negative Consequences

-   **Tight Coupling:** Changes in one module ripple across the dependency chain.
    
-   **Compilation Issues:** Independent compilation and deployment become impossible.
    
-   **Testability Problems:** Unit tests require full system context.
    
-   **Initialization Failures:** Dependency injection frameworks (Spring, CDI) fail due to circular bean references.
    
-   **Refactoring Pain:** Breaking cycles later requires major architectural surgery.
    
-   **Reduced Clarity:** Logical layer boundaries (UI, Service, Repository) become meaningless.
    

### (Occasional) Positive Consequences

-   Temporary workaround to enable rapid prototyping.
    
-   Quick interconnection of two modules before a refactor.
    

However, this is a **debt** that compounds rapidly.

---

## Root Causes

-   **Violation of Layered Architecture principles.**
    
-   **Overcoupled class design.**
    
-   **Poor cohesion and unclear responsibilities.**
    
-   **Shared mutable state or logic between layers.**
    
-   **Improper dependency injection configuration (mutual @Autowired).**
    
-   **Cyclic imports across packages or Maven modules.**
    

---

## Refactored Solution (How to Break the Cycle)

### 1\. **Apply Dependency Inversion Principle (DIP)**

-   Introduce interfaces to decouple concrete implementations.
    
-   Both modules depend on abstractions, not on each other.
    

### 2\. **Introduce a Mediator or Event Bus**

-   Use an intermediary to coordinate communication between components.
    

### 3\. **Apply Layered Architecture**

-   Ensure strict directionality (e.g., Controller → Service → Repository).
    

### 4\. **Restructure Packages**

-   Move shared interfaces or DTOs into neutral packages (e.g., `common`).
    

### 5\. **Use Dependency Injection Wisely**

-   Avoid mutual field injection in Spring; prefer setter or constructor injection with clear ownership.
    

### 6\. **Refactor Bidirectional Relationships**

-   Use unidirectional associations in domain models where possible.
    

---

## Example (Java)

### Circular Dependency Example

```java
// Class A depends on Class B
public class ClassA {
    private ClassB classB;

    public ClassA(ClassB classB) {
        this.classB = classB;
    }

    public void doSomething() {
        System.out.println("A is calling B");
        classB.respond();
    }

    public void respond() {
        System.out.println("A responds to B");
    }
}

// Class B depends on Class A
public class ClassB {
    private ClassA classA;

    public ClassB(ClassA classA) {
        this.classA = classA;
    }

    public void doSomething() {
        System.out.println("B is calling A");
        classA.respond();
    }

    public void respond() {
        System.out.println("B responds to A");
    }
}

// Instantiation
public class Main {
    public static void main(String[] args) {
        // Circular construction causes chaos
        ClassA a = new ClassA(null);
        ClassB b = new ClassB(a);
        a = new ClassA(b); // Reassigning just to break the cycle manually
        a.doSomething();
        b.doSomething();
    }
}
```

This design creates a tight mutual dependency:

-   **ClassA** cannot exist without **ClassB**, and vice versa.
    
-   There is no clear ownership or abstraction layer.
    

---

### Refactored Version Using an Interface

```java
// Define abstraction to invert dependency
public interface Responder {
    void respond();
}

// ClassA depends only on interface
public class ClassA {
    private final Responder responder;

    public ClassA(Responder responder) {
        this.responder = responder;
    }

    public void doSomething() {
        System.out.println("A is calling responder");
        responder.respond();
    }
}

// ClassB implements Responder but does not depend on A
public class ClassB implements Responder {
    @Override
    public void respond() {
        System.out.println("B responds");
    }
}

// Instantiation
public class Main {
    public static void main(String[] args) {
        Responder b = new ClassB();
        ClassA a = new ClassA(b);
        a.doSomething(); // No circular dependency anymore
    }
}
```

This refactoring:

-   Removes the circular dependency.
    
-   Introduces a stable abstraction (`Responder`).
    
-   Improves testability and modularity.
    

---

## Detection Techniques

-   **Static Analysis Tools:**
    
    -   IntelliJ IDEA “Dependency Structure Matrix” (DSM).
        
    -   SonarQube “Cyclic Dependency” rule.
        
    -   JDepend or Structure101 for dependency analysis.
        
-   **Build Tools:**
    
    -   Maven/Gradle dependency graph inspection (`mvn dependency:tree`).
        
-   **Runtime Indicators:**
    
    -   Spring `BeanCurrentlyInCreationException` during startup.
        

---

## Known Uses

-   **Large monolithic systems** where modules grow organically without boundaries.
    
-   **Spring Boot projects** with mutual `@Autowired` beans.
    
-   **Domain models** with bidirectional entity relationships (`User` ↔ `Address`).
    
-   **UI frameworks** where components call each other recursively (e.g., controller ↔ view).
    

---

## Related Patterns

-   **Dependency Inversion Principle (SOLID)** – Prevents this antipattern.
    
-   **Mediator Pattern** – Centralizes communication to break direct links.
    
-   **Observer Pattern** – Enables decoupled notification instead of direct callbacks.
    
-   **Layered Architecture** – Enforces directionality in dependencies.
    
-   **Interface Segregation** – Reduces large cross-cutting interfaces.
    

---

## Summary

The **Circular Dependency** antipattern breaks one of the fundamental principles of software design — that dependencies should form a directed acyclic structure.

When components mutually depend on each other, **modularity, clarity, and scalability** collapse.

Breaking these cycles through **abstraction**, **dependency inversion**, and **layer enforcement** restores architectural integrity.  
Without this discipline, systems become rigid, fragile, and prone to cascade failures — trapped in an endless loop of their own making.

