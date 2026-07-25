---
name: plantuml
context: fork
description: "Brand-themed PlantUML diagrams for project documentation"
---

# PlantUML Diagram Generation

Generate PlantUML diagrams for architecture, API flows, and process visualization using project branding.

> **Project Context** — Read `project-config.md` in the repo root for brand tokens, color palette, and project metadata.

## Brand Theme

Use this block at the start of your `.puml` files for consistent brand styling:

```plantuml
@startuml
skinparam backgroundColor #F8F9FA
skinparam defaultFontSize 14
skinparam defaultFontColor #1F2937
skinparam rectangle {
  BackgroundColor #FFF7ED
  BorderColor #F97316
  FontColor #1F2937
}
skinparam participant {
  BackgroundColor #F0F9FF
  BorderColor #0EA5E9
}
skinparam database {
  BackgroundColor #ECFDF5
  BorderColor #10B981
}
skinparam arrow {
  Color #1F2937
}
skinparam arrowColor #E10A0A
' Use arrowColor for key flows; Color for default
@enduml
```

For **sequence diagrams**, you can add:

```plantuml
skinparam sequenceArrowColor #E10A0A
skinparam sequenceLifeLineBorderColor #1F2937
skinparam sequenceParticipantBackgroundColor #F8F9FA
skinparam sequenceParticipantBorderColor #E10A0A
```

## Standard Participants

When documenting systems, use consistent participant names where applicable:

| Participant   | Use case                |
|---------------|-------------------------|
| Streamlit App | Streamlit dashboards      |
| FastAPI       | API services              |
| SQL Server    | Data layer               |
| Redis / Cache | Caching layer           |
| User          | End user / operator     |

Example:

```plantuml
@startuml
actor User
participant "Streamlit App" as app
participant "FastAPI" as api
database "SQL Server" as db
User -> app : Request
app -> api : API call
api -> db : Query
db --> api : Result
api --> app : Response
app --> User : Display
@enduml
```

## Diagram Types

| Type       | Best For                           |
|------------|-------------------------------------|
| Sequence   | API calls, request/response flows  |
| Class      | OOP design, data models            |
| Component  | System architecture, microservices |
| Activity   | Workflows, business logic          |
| State      | State machines, lifecycles         |
| Deployment | Infrastructure, network topology   |

Use the brand theme above for all diagram types. Syntax reference follows.

### Class diagram

```plantuml
@startuml
class User {
  +id: int
  +email: str
  +name: str
  +authenticate(password): bool
}
class Order {
  +id: int
  +total: Decimal
  +status: OrderStatus
  +calculate_total(): Decimal
}
class OrderItem {
  +quantity: int
  +unit_price: Decimal
}
User "1" -- "*" Order : places >
Order "1" *-- "*" OrderItem : contains
@enduml
```

**Relationship arrows:**

| Arrow    | Meaning        |
|----------|----------------|
| `-->`    | Dependency     |
| `--`     | Association    |
| `*--`    | Composition    |
| `o--`    | Aggregation    |
| `<\|--`  | Inheritance    |
| `..\|>`  | Implementation |

### Component diagram (packages and dependencies)

```plantuml
@startuml
package "Frontend" {
  [React App] as web
}
package "Backend" {
  [API Gateway] as gw
  [User Service] as users
}
package "Data" {
  database "PostgreSQL" as pg
  database "Redis" as redis
}
web --> gw : HTTPS
gw --> users
gw --> orders
users --> pg
orders --> pg
gw --> redis : cache
@enduml
```

### Activity diagram (flow and branches)

```plantuml
@startuml
start
:Receive request;
if (Authenticated?) then (yes)
  :Validate input;
  if (Valid?) then (yes)
    :Process request;
    :Return 200 OK;
  else (no)
    :Return 400;
  endif
else (no)
  :Return 401;
endif
stop
@enduml
```

### State diagram

```plantuml
@startuml
[*] --> Draft
Draft --> PendingReview : submit()
PendingReview --> Approved : approve()
PendingReview --> Rejected : reject()
Rejected --> Draft : revise()
Approved --> Published : publish()
Published --> [*]
@enduml
```

### Deployment diagram

```plantuml
@startuml
actor User
node "CDN" as cdn
node "Load Balancer" as lb
node "App Server 1" as app1
node "App Server 2" as app2
database "Primary DB" as db1
database "Replica" as db2
User --> cdn
cdn --> lb
lb --> app1
lb --> app2
app1 --> db1
app2 --> db1
db1 --> db2 : replication
@enduml
```

## Generating Output

```bash
plantuml diagram.puml          # PNG (default)
plantuml -tsvg diagram.puml    # SVG
plantuml -txt diagram.puml     # ASCII art
plantuml -utxt diagram.puml    # Unicode ASCII
plantuml -tsvg diagrams/       # Batch process folder
plantuml -syntax diagram.puml  # Syntax check only
```

## Tips

1. Apply the brand theme block once per file.
2. Use Primary Red (#E10A0A) for primary flows or key components.
3. Keep participant labels short; use "Streamlit App", "FastAPI", "SQL Server" for project context.
4. Keep diagrams simple — 5–12 elements per diagram.
5. Use `left to right direction` for horizontal layouts.
6. Version control `.puml` files; they diff well.
