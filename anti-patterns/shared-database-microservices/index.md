# Shared Database Microservices

---

## Overview

**Type:** Software Architecture Antipattern  
**Category:** Data Management / Microservices Architecture Antipattern  
**Context:** Arises in microservice-based systems when multiple services share the same underlying database schema or instance, violating the principle of service autonomy and leading to tight coupling, hidden dependencies, and fragile integrations.

---

## Intent

To describe the **antipattern of microservices sharing a common database**, undermining their independence and scalability.  
While intended to simplify data consistency or reduce duplication, this approach reintroduces monolithic behavior at the data layer, negating many benefits of microservice architectures such as loose coupling, isolation, and independent deployability.

---

## Also Known As

-   **Database Monolith**
    
-   **Shared Persistence Trap**
    
-   **Tight-Coupled Data Layer**
    
-   **Microservices Without Boundaries**
    

---

## Motivation (Forces)

Microservices are designed to encapsulate both business logic and data ownership within well-defined boundaries.  
However, in many real-world projects, teams take a shortcut — instead of maintaining separate databases per service, they use a **single shared database** accessed by multiple services.

This decision is often motivated by short-term convenience or legacy integration needs, but it leads to **cross-service coupling**, **data integrity issues**, and **deployment paralysis** in the long term.

Common forces that lead to this antipattern:

-   **Desire for real-time consistency** without proper event-driven mechanisms.
    
-   **Legacy database reuse:** A monolithic schema already exists.
    
-   **Lack of data ownership clarity** across domains.
    
-   **Cross-cutting reporting or analytics requirements.**
    
-   **Pressure to deliver quickly without refactoring data models.**
    
-   **DBA-driven architecture decisions prioritizing schema centralization.**
    

---

## Applicability

You are likely facing **Shared Database Microservices** if:

-   Multiple microservices access the same database schema or tables.
    
-   Schema changes require coordination between several teams.
    
-   Deploying one service necessitates redeploying others.
    
-   Business transactions span multiple microservices with direct SQL joins.
    
-   Database foreign keys exist between tables owned by different services.
    
-   You observe data anomalies after independent service updates.
    

---

## Structure

```sql
+-----------------------------+
|         Shared DB           |
|-----------------------------|
|  table: customers           |
|  table: orders              |
|  table: payments            |
|  table: products            |
+-------------+---------------+
              ^
   +----------+----------+
   |                     |
+--+--+               +--+--+
| SvcA |              | SvcB |
| Cust |              | Order|
+------+              +------+
```

All services depend on the same database tables.  
Any schema change in one domain affects the others — reintroducing tight coupling through the data layer.

---

## Participants

| Participant | Description |
| --- | --- |
| **Service A (Customer Service)** | Reads and writes data directly from shared `customers` table. |
| **Service B (Order Service)** | Depends on `orders` and `customers` tables for relational joins. |
| **Shared Database** | Central schema acting as a hidden integration point. |
| **DBA Team** | Controls schema changes, impacting all services. |
| **Developers** | Forced to coordinate deployments due to shared data dependencies. |

---

## Collaboration

-   Each microservice performs direct SQL queries on shared tables.
    
-   One team changes table structure or constraints to suit its logic.
    
-   Other services break unexpectedly because of the same table dependency.
    
-   Over time, database-level coupling becomes stronger than service-level boundaries.
    
-   Services cannot evolve or scale independently.
    

---

## Consequences

### Negative Consequences

-   **Tight coupling:** Schema changes ripple across services.
    
-   **Loss of autonomy:** Services must coordinate releases and migrations.
    
-   **Deployment bottlenecks:** Database migrations require global synchronization.
    
-   **Data ownership confusion:** Multiple services claim control over the same entity.
    
-   **Reduced fault isolation:** One service’s bad query can degrade the shared DB.
    
-   **Scalability issues:** Shared database becomes a performance and scaling bottleneck.
    
-   **Data corruption risks:** Inconsistent updates across services without transaction boundaries.
    
-   **Testing complexity:** Integration tests depend on shared DB state.
    

### (Occasional) Positive Consequences

-   **Simpler reporting:** All data available in one schema.
    
-   **Quick initial development:** No need to create separate data models.
    
-   **Familiar approach for teams transitioning from monoliths.**
    

However, these short-term gains come at the cost of **long-term architectural rigidity** and **reduced agility**.

---

## Root Causes

-   **Misinterpretation of microservice principles.**
    
-   **Fear of data duplication or eventual consistency.**
    
-   **Legacy monolithic database reuse.**
    
-   **Organizational silos where DBAs control schema evolution.**
    
-   **Lack of event-driven or API-based integration design.**
    
-   **Centralized reporting demands overriding domain boundaries.**
    

---

## Refactored Solution (How to Avoid or Fix It)

### 1\. **Adopt Database per Service Principle**

-   Each microservice must own its **schema** and **data model**.
    
-   No other service should directly query or modify its data.
    

### 2\. **Introduce Data Ownership Boundaries**

-   Clearly define which service is responsible for which domain entity.
    
-   Use Domain-Driven Design (DDD) to identify **Bounded Contexts**.
    

### 3\. **Use APIs for Cross-Service Data Access**

-   Expose read-only APIs or query endpoints instead of shared tables.
    
-   Example: `OrderService` calls `CustomerService` via REST or gRPC to fetch customer info.
    

### 4\. **Adopt Event-Driven Communication**

-   Use event streaming (Kafka, RabbitMQ, AWS SNS/SQS) to propagate data changes asynchronously.
    
-   Services maintain local views or caches updated by domain events.
    

### 5\. **Introduce a Read-Optimized Aggregation Layer**

-   For reporting or analytics, use a **data warehouse** or **CQRS read model**.
    
-   Keep operational services isolated.
    

### 6\. **Gradual Decoupling Strategy**

-   Start by extracting one service at a time with its schema subset.
    
-   Replace cross-service queries with API calls or replication pipelines.
    

---

## Example (Java)

### Shared Database Antipattern Example

```java
// CustomerService accessing shared table directly
@Repository
public class CustomerRepository {
    @Autowired
    private JdbcTemplate jdbcTemplate;

    public Customer findById(long id) {
        return jdbcTemplate.queryForObject("SELECT * FROM customers WHERE id = ?", 
            new Object[]{id}, new BeanPropertyRowMapper<>(Customer.class));
    }
}

// OrderService accessing the same shared 'customers' table
@Repository
public class OrderRepository {
    @Autowired
    private JdbcTemplate jdbcTemplate;

    public List<Order> findOrdersWithCustomer(long customerId) {
        String sql = "SELECT o.*, c.name FROM orders o " +
                     "JOIN customers c ON o.customer_id = c.id";
        return jdbcTemplate.query(sql, new OrderMapper());
    }
}
```

Both services read the **same `customers` table**, creating implicit coupling at the database level.  
If `CustomerService` changes the schema, `OrderService` breaks silently.

---

### Refactored Example (Using Service API and Event-Driven Sync)

**CustomerService**

```java
@RestController
@RequestMapping("/customers")
public class CustomerController {

    @Autowired
    private CustomerRepository repository;

    @GetMapping("/{id}")
    public ResponseEntity<Customer> getCustomer(@PathVariable long id) {
        return ResponseEntity.of(repository.findById(id));
    }
}
```

**OrderService**

```java
@Service
public class OrderService {
    private final RestTemplate restTemplate = new RestTemplate();

    public Customer getCustomerDetails(long customerId) {
        String url = "http://customer-service/customers/" + customerId;
        return restTemplate.getForObject(url, Customer.class);
    }
}
```

**Event Synchronization Example (Kafka)**

```java
@Component
public class CustomerEventListener {

    @KafkaListener(topics = "customer-updates", groupId = "order-service")
    public void handleCustomerUpdate(String eventJson) {
        CustomerEvent event = new Gson().fromJson(eventJson, CustomerEvent.class);
        // update local cache or read model
    }
}
```

Each service owns its data and communicates changes asynchronously — achieving autonomy and scalability.

---

## Detection Techniques

-   **Database-level Analysis:**
    
    -   Detect shared tables accessed by multiple services.
        
    -   Identify cross-service foreign key relationships.
        
-   **Code Inspection:**
    
    -   Look for direct SQL queries across domain boundaries.
        
-   **Deployment Analysis:**
    
    -   If multiple services fail after a single DB migration, shared DB exists.
        
-   **Dependency Graph Tools:**
    
    -   Tools like *JDepend* or *SonarQube* reveal service-level database coupling.
        

---

## Known Uses

-   **Legacy monoliths** split into microservices but keeping one shared database.
    
-   **Large enterprises** with centralized database teams managing all schemas.
    
-   **Data-heavy systems** (e.g., ERP, banking) reluctant to adopt event-driven approaches.
    
-   **Projects under time pressure** that defer proper database separation.
    

---

## Related Patterns

-   **Database per Service (Good Practice):** Each microservice owns its schema.
    
-   **API Composition Pattern:** Combine data from multiple services via APIs.
    
-   **CQRS (Command Query Responsibility Segregation):** Separate read and write models.
    
-   **Event Sourcing / Outbox Pattern:** Enable data synchronization through events.
    
-   **Data Replication Pattern:** Maintain local copies of needed data for read access.
    
-   **Service Mesh + Caching:** Improve inter-service data access performance.
    

---

## Summary

The **Shared Database Microservices** antipattern undermines the very essence of microservice architecture.  
While it may simplify data sharing initially, it creates **hidden coupling**, **deployment dependency**, and **loss of autonomy** — turning distributed systems back into monoliths.

True microservices achieve independence not only at the code level but also at the **data ownership level**.  
Each service must **own its schema, expose APIs**, and **communicate through contracts or events** — ensuring flexibility, resilience, and scalability in the long run.

A microservice that shares its database isn’t a microservice — it’s just a **distributed monolith with a single point of failure.**

