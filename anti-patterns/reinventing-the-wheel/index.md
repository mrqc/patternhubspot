# Reinventing the Wheel

---

## Overview

**Type:** Software Development Antipattern  
**Category:** Productivity / Design / Maintenance Antipattern  
**Context:** Occurs when developers implement functionality from scratch that already exists in well-tested libraries, frameworks, or standard APIs — leading to redundant, inferior, or less secure solutions.

---

## Intent

To describe the **inefficiency and risk** that arise when developers unnecessarily reimplement existing and proven functionality instead of reusing reliable, available solutions.

The “Reinventing the Wheel” antipattern wastes time, increases maintenance burden, and often produces inferior results compared to mature, community-tested alternatives.

---

## Also Known As

-   **DIY Syndrome (Do It Yourself)**
    
-   **Not-Invented-Here (NIH) Subset**
    
-   **Duplicate Implementation**
    
-   **Overengineering by Redundancy**
    
-   **Roll-Your-Own Framework**
    

---

## Motivation (Forces)

Developers often pride themselves on solving problems creatively — but this can lead to *recreating existing solutions* that are already robust, optimized, and well-maintained.

This antipattern arises from a mix of **ego**, **ignorance**, and **fear of dependency**, typically under these forces:

-   **Lack of awareness:** Developer doesn’t know a standard solution exists.
    
-   **Perceived simplicity:** “It’s easier to just write it myself.”
    
-   **Control preference:** Distrust of external libraries or frameworks.
    
-   **Learning exercise turned production code.**
    
-   **Avoidance of dependencies for ideological reasons.**
    
-   **Overconfidence in ability to outperform proven implementations.**
    

While sometimes justified in low-level or embedded systems, it’s usually an unnecessary reinvention that leads to long-term problems.

---

## Applicability

You are likely observing **Reinventing the Wheel** when:

-   Developers write custom utilities for logging, encryption, JSON parsing, or string manipulation.
    
-   Code comments contain phrases like *“simple implementation of XYZ library.”*
    
-   The organization forbids third-party libraries without strong reasons.
    
-   Duplicate functionality exists across multiple internal modules.
    
-   Code quality and performance are poor compared to open-source equivalents.
    
-   Maintenance of custom tools consumes significant time and resources.
    

---

## Structure

```csharp
[Existing Problem]
       ↓
[Developer Writes Custom Solution]
       ↓
[Existing Libraries Ignored]
       ↓
[Custom Implementation with Bugs]
       ↓
[Maintenance, Security, and Integration Issues]
```

Instead of leveraging a proven ecosystem, developers choose to build and maintain everything themselves.

---

## Participants

| Participant | Description |
| --- | --- |
| **Developer** | Creates redundant functionality rather than reusing existing libraries. |
| **Organization** | Supports or encourages “build it here” culture. |
| **Existing Frameworks/Libraries** | Often ignored despite solving the same problem better. |
| **Users** | Suffer from instability, reduced features, and security flaws. |
| **Maintenance Team** | Burdened with supporting non-standard code. |

---

## Collaboration

-   A problem arises (e.g., need for JSON parsing).
    
-   Instead of evaluating libraries, developers implement custom code.
    
-   As requirements evolve, the new code becomes hard to maintain.
    
-   The custom solution diverges from established standards.
    
-   Over time, developers spend more time fixing “their version” than developing new features.
    

---

## Consequences

### Negative Consequences

-   **Time waste:** Reinventing existing solutions delays delivery.
    
-   **Maintenance overhead:** Custom code must be updated and supported indefinitely.
    
-   **Poor reliability:** Lacks the maturity and testing of established libraries.
    
-   **Security risks:** Reimplementation of encryption or validation often introduces vulnerabilities.
    
-   **Incompatibility:** Custom implementations deviate from community standards.
    
-   **Reduced innovation:** Time spent redoing basics detracts from core product development.
    

### (Occasional) Positive Consequences

-   **Learning opportunity:** Developers gain deep understanding of underlying mechanisms.
    
-   **Control over dependencies:** Avoids external vulnerabilities or version conflicts.
    
-   **Performance optimization:** Custom code can outperform general-purpose libraries in niche use cases.
    

However, these benefits rarely outweigh the costs when production-grade reliability is required.

---

## Root Causes

-   **Not-Invented-Here (NIH) mentality.**
    
-   **Lack of library evaluation during design.**
    
-   **Missing architectural governance or code reuse policy.**
    
-   **Poor documentation of existing internal solutions.**
    
-   **Ego-driven development (“I can do it better”).**
    
-   **Fear of license, dependency, or integration complexity.**
    

---

## Refactored Solution (How to Avoid Reinventing the Wheel)

### 1\. **Adopt a “Reuse-First” Policy**

-   Always check for existing libraries or APIs before coding new utilities.
    
-   Evaluate standard frameworks like Apache Commons, Spring, or Java SDK utilities.
    

### 2\. **Establish Dependency Guidelines**

-   Maintain an approved list of vetted, open-source or internal libraries.
    
-   Review new dependencies for license, performance, and security compliance.
    

### 3\. **Perform Architectural Reviews**

-   Validate whether proposed implementations duplicate existing functionality.
    

### 4\. **Encourage Knowledge Sharing**

-   Maintain internal documentation or registries of reusable components.
    

### 5\. **Use Open Source Responsibly**

-   Prefer community-maintained libraries with active contributors and clear licenses.
    

### 6\. **Apply the YAGNI Principle (“You Aren’t Gonna Need It”)**

-   Don’t create frameworks or tools unless absolutely necessary.
    

---

## Example (Java)

### Reinvented Wheel Example

```java
// Custom String Reversal Utility - Reinventing existing methods
public class StringUtil {
    public static String reverse(String input) {
        char[] chars = input.toCharArray();
        StringBuilder reversed = new StringBuilder();
        for (int i = chars.length - 1; i >= 0; i--) {
            reversed.append(chars[i]);
        }
        return reversed.toString();
    }
}

public class Main {
    public static void main(String[] args) {
        System.out.println(StringUtil.reverse("hello"));
    }
}
```

This reimplements functionality already available in standard Java libraries.

---

### Correct and Efficient Alternative

```java
public class Main {
    public static void main(String[] args) {
        String input = "hello";
        String reversed = new StringBuilder(input).reverse().toString();
        System.out.println(reversed);
    }
}
```

The built-in `StringBuilder.reverse()` method is **faster**, **tested**, and **maintained** — eliminating the need for custom code.

---

### Another Common Example — Custom JSON Parser

#### Reinvented Implementation

```java
public class JsonParser {
    public static Map<String, String> parse(String json) {
        Map<String, String> map = new HashMap<>();
        json = json.replace("{", "").replace("}", "").replace("\"", "");
        String[] pairs = json.split(",");
        for (String pair : pairs) {
            String[] kv = pair.split(":");
            map.put(kv[0].trim(), kv[1].trim());
        }
        return map;
    }
}
```

This code will fail on nested JSON, arrays, or escaped characters — reinventing a flawed version of a problem long solved by libraries like **Jackson** or **Gson**.

#### Proper Solution Using Library

```java
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.Map;

public class Main {
    public static void main(String[] args) throws Exception {
        String json = "{\"name\":\"Alice\", \"age\":30}";
        ObjectMapper mapper = new ObjectMapper();
        Map<String, Object> map = mapper.readValue(json, Map.class);
        System.out.println(map);
    }
}
```

This is robust, standard, and widely supported.

---

## Detection Techniques

-   **Code Review Indicators:**
    
    -   Developers implement utilities already available in the standard library.
        
    -   Internal frameworks duplicate external open-source projects.
        
-   **Static Code Analysis:**
    
    -   Detects duplicate functionality patterns across repositories.
        
-   **Dependency Comparison Tools:**
    
    -   Identify overlap between in-house and open-source modules.
        
-   **Team Interviews:**
    
    -   Reveal gaps in awareness of existing solutions.
        

---

## Known Uses

-   **Custom encryption algorithms** instead of using `javax.crypto` or BouncyCastle.
    
-   **Homemade ORM frameworks** instead of using JPA or Hibernate.
    
-   **Internal logging utilities** replacing SLF4J or Log4j.
    
-   **Custom string manipulation or date parsing** functions replacing Apache Commons Lang or Java Time API.
    
-   **Homegrown web frameworks** replacing Spring, Micronaut, or Jakarta EE.
    

---

## Related Patterns

-   **Not-Invented-Here Syndrome (NIH):** Broader organizational resistance to external solutions.
    
-   **Overengineering:** Adding unnecessary complexity to simple tasks.
    
-   **Golden Hammer:** Overusing one tool for all problems instead of adopting fit-for-purpose solutions.
    
-   **Big Ball of Mud:** Emergent result of duplicated and unrefactored internal utilities.
    
-   **YAGNI Principle:** Prevents premature or redundant development.
    

---

## Summary

The **Reinventing the Wheel** antipattern wastes resources and introduces unnecessary complexity by rebuilding what already exists.  
While curiosity and experimentation are valuable for learning, production systems demand reliability, security, and maintainability — best achieved by reusing proven tools.

Good engineers know **when to innovate** and **when to reuse**.  
True craftsmanship lies not in building every wheel yourself, but in choosing **the right one to drive progress forward.**

