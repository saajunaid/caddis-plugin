# Mermaid Diagram Workflows

Step-by-step examples for common diagramming tasks.

## Workflow 1: Document a New API Endpoint

**When:** You've built a new API endpoint and need to document the flow for frontend developers.

**Steps:**

1. **Choose diagram type:** Sequence diagram (shows temporal interactions)

2. **Identify participants:**
   ```mermaid
   sequenceDiagram
       participant Client
       participant API
       participant Database
   ```

3. **Add the happy path:**
   ```mermaid
   sequenceDiagram
       participant Client
       participant API
       participant Database
       
       Client->>API: POST /users
       API->>Database: INSERT user
       Database-->>API: Return user_id
       API-->>Client: 201 Created + user object
   ```

4. **Add error handling:**
   ```mermaid
   sequenceDiagram
       participant Client
       participant API
       participant Database
       
       Client->>API: POST /users
       API->>API: Validate input
       alt Valid input
           API->>Database: INSERT user
           Database-->>API: Return user_id
           API-->>Client: 201 Created + user object
       else Invalid input
           API-->>Client: 400 Bad Request + errors
       else Duplicate email
           Database-->>API: Constraint violation
           API-->>Client: 409 Conflict
       end
   ```

5. **Add notes for clarification:**
   ```mermaid
   sequenceDiagram
       participant Client
       participant API
       participant Database
       
       Note over Client,Database: User Registration Flow
       
       Client->>API: POST /users
       Note right of API: Validates email format,<br/>password strength
       
       alt Valid input
           API->>Database: INSERT user
           Database-->>API: Return user_id
           Note left of Database: Email must be unique
           API-->>Client: 201 Created + user object
       else Invalid input
           API-->>Client: 400 Bad Request
       end
   ```

## Workflow 2: Design a Database Schema

**When:** You're planning a new feature that needs new tables.

**Steps:**

1. **Identify core entities:**
   ```mermaid
   erDiagram
       USER
       ORDER
       PRODUCT
   ```

2. **Define relationships:**
   ```mermaid
   erDiagram
       USER ||--o{ ORDER : places
       ORDER ||--|{ LINE_ITEM : contains
       PRODUCT ||--o{ LINE_ITEM : includes
   ```

3. **Add attributes:**
   ```mermaid
   erDiagram
       USER ||--o{ ORDER : places
       ORDER ||--|{ LINE_ITEM : contains
       PRODUCT ||--o{ LINE_ITEM : includes
       
       USER {
           int id PK
           string email UK
           string name
           datetime created_at
       }
       
       ORDER {
           int id PK
           int user_id FK
           string status
           decimal total
           datetime created_at
       }
       
       PRODUCT {
           int id PK
           string name
           string sku UK
           decimal price
       }
       
       LINE_ITEM {
           int id PK
           int order_id FK
           int product_id FK
           int quantity
           decimal price
       }
   ```

4. **Validate design:**
   - Check all foreign keys have corresponding primary keys
   - Verify cardinality matches business rules
   - Ensure unique constraints are marked (UK)

## Workflow 3: Model a Domain (DDD)

**When:** You're implementing a new feature using Domain-Driven Design.

**Steps:**

1. **Start with aggregates:**
   ```mermaid
   classDiagram
       class Order
       class LineItem
       class Product
   ```

2. **Add relationships:**
   ```mermaid
   classDiagram
       Order *-- LineItem : contains
       LineItem --> Product : references
   ```

3. **Define entities with properties:**
   ```mermaid
   classDiagram
       Order *-- LineItem
       LineItem --> Product
       
       class Order {
           +OrderId id
           +CustomerId customerId
           +OrderStatus status
           +Money total
           +addItem(Product, quantity)
           +calculateTotal()
           +submit()
       }
       
       class LineItem {
           +ProductId productId
           +int quantity
           +Money price
           +updateQuantity(int)
       }
       
       class Product {
           +ProductId id
           +string name
           +Money price
           +bool inStock()
       }
   ```

4. **Add value objects and enums:**
   ```mermaid
   classDiagram
       Order *-- LineItem
       Order --> OrderStatus
       Order --> Money
       LineItem --> Product
       LineItem --> Money
       
       class Order {
           +OrderId id
           +CustomerId customerId
           +OrderStatus status
           +Money total
       }
       
       class OrderStatus {
           <<enumeration>>
           DRAFT
           SUBMITTED
           PAID
           SHIPPED
           DELIVERED
           CANCELLED
       }
       
       class Money {
           <<value object>>
           +decimal amount
           +Currency currency
           +add(Money)
       }
   ```

## Workflow 4: Map a User Journey

**When:** You're planning a new feature and need to visualize the user experience.

**Steps:**

1. **Define start and end points:**
   ```mermaid
   flowchart TD
       Start([User lands on checkout])
       End([Order confirmed])
   ```

2. **Add main path:**
   ```mermaid
   flowchart TD
       Start([User lands on checkout]) --> Review[Review cart]
       Review --> Payment[Enter payment]
       Payment --> Confirm[Confirm order]
       Confirm --> End([Order confirmed])
   ```

3. **Add decision points:**
   ```mermaid
   flowchart TD
       Start([User lands on checkout]) --> Review[Review cart]
       Review --> HasItems{Cart has items?}
       HasItems -->|Yes| Payment[Enter payment]
       HasItems -->|No| Empty[Show empty cart]
       Payment --> Valid{Payment valid?}
       Valid -->|Yes| Confirm[Confirm order]
       Valid -->|No| Error[Show error]
       Error --> Payment
       Confirm --> End([Order confirmed])
   ```

4. **Add alternative flows:**
   ```mermaid
   flowchart TD
       Start([User lands on checkout]) --> Auth{Logged in?}
       Auth -->|No| Login[Login/Register]
       Auth -->|Yes| Review[Review cart]
       Login --> Review
       
       Review --> HasItems{Cart has items?}
       HasItems -->|Yes| Address{Has address?}
       HasItems -->|No| Empty[Empty cart message]
       
       Address -->|Yes| Payment[Enter payment]
       Address -->|No| AddAddress[Add shipping address]
       AddAddress --> Payment
       
       Payment --> Valid{Payment valid?}
       Valid -->|Yes| Confirm[Confirm order]
       Valid -->|No| PaymentError[Show error]
       PaymentError --> Payment
       
       Confirm --> End([Order confirmed])
   ```

## Workflow 5: Document System Architecture

**When:** You need to show how your system components interact.

**Steps:**

1. **Create context diagram (external view):**
   ```mermaid
   C4Context
       title System Context - E-commerce Platform
       
       Person(customer, "Customer", "Shops for products")
       System(ecommerce, "E-commerce System", "Web application")
       System_Ext(payment, "Payment Gateway", "Stripe")
       System_Ext(email, "Email Service", "SendGrid")
       System_Ext(shipping, "Shipping Provider", "FedEx API")
       
       Rel(customer, ecommerce, "Browses and purchases")
       Rel(ecommerce, payment, "Processes payments")
       Rel(ecommerce, email, "Sends notifications")
       Rel(ecommerce, shipping, "Creates shipments")
   ```

2. **Create container diagram (components):**
   ```mermaid
   C4Container
       title Container Diagram - E-commerce System
       
       Person(customer, "Customer")
       
       Container_Boundary(c1, "E-commerce System") {
           Container(web, "Web Application", "React", "SPA")
           Container(api, "API", "Node.js", "REST API")
           ContainerDb(db, "Database", "PostgreSQL", "Product, order data")
           Container(worker, "Background Worker", "Node.js", "Processes async tasks")
           ContainerQueue(queue, "Message Queue", "RabbitMQ")
       }
       
       System_Ext(payment, "Payment Gateway")
       
       Rel(customer, web, "Uses", "HTTPS")
       Rel(web, api, "Calls", "HTTPS/JSON")
       Rel(api, db, "Reads/Writes")
       Rel(api, queue, "Publishes messages")
       Rel(worker, queue, "Subscribes to messages")
       Rel(api, payment, "Processes payments", "HTTPS")
   ```

3. **Create component diagram (internal structure):**
   ```mermaid
   C4Component
       title Component Diagram - API
       
       Container_Boundary(api, "API") {
           Component(controller, "Order Controller", "Express", "Handles HTTP requests")
           Component(service, "Order Service", "TypeScript", "Business logic")
           Component(repo, "Order Repository", "TypeORM", "Data access")
       }
       
       ContainerDb(db, "Database")
       ContainerQueue(queue, "Message Queue")
       
       Rel(controller, service, "Uses")
       Rel(service, repo, "Uses")
       Rel(repo, db, "Reads/Writes", "SQL")
       Rel(service, queue, "Publishes events")
   ```

## Workflow 6: Plan a Refactoring

**When:** You want to document before/after states for a refactoring effort.

**Steps:**

1. **Document current state:**
   ```mermaid
   classDiagram
       class OrderController {
           +createOrder(req, res)
           +validatePayment()
           +sendEmail()
           +updateInventory()
       }
       
       note for OrderController "Controller doing too much:<br/>- Payment validation<br/>- Email sending<br/>- Inventory management"
   ```

2. **Design target state:**
   ```mermaid
   classDiagram
       OrderController --> OrderService
       OrderService --> PaymentService
       OrderService --> EmailService
       OrderService --> InventoryService
       
       class OrderController {
           +createOrder(req, res)
       }
       
       class OrderService {
           +processOrder(orderData)
       }
       
       class PaymentService {
           +validatePayment(paymentInfo)
       }
       
       class EmailService {
           +sendOrderConfirmation(order)
       }
       
       class InventoryService {
           +reserveItems(lineItems)
       }
   ```

3. **Create migration steps:**
   - Extract PaymentService
   - Extract EmailService
   - Extract InventoryService
   - Refactor OrderController to use OrderService

## Tips for Effective Workflows

1. **Start with the big picture** - Context before details
2. **Iterate incrementally** - Add complexity gradually
3. **Validate at each step** - Test syntax at [mermaid.live](https://mermaid.live)
4. **Use consistent naming** - Match code/database names
5. **Add explanatory notes** - Clarify non-obvious parts
6. **Version control** - Commit diagrams with related code changes
7. **Update regularly** - Keep diagrams current as code evolves
