# Layout Guidelines

## Grouping Principles

### Hierarchy Structure
```text
Cloud Provider (outermost)
├── VPC / Virtual Network
│   ├── Public Subnet
│   │   └── Load Balancer, NAT Gateway
│   └── Private Subnet
│       └── Application Servers, Databases
├── Object Storage (S3, Blob, GCS)
├── Monitoring (CloudWatch, Monitor)
└── Other Services
```

### Grouping Rules
- Security boundaries (DMZ, private, management)
- Service tiers (frontend, backend, data)
- Team ownership (team A, team B)

## Flow Directions

### Left-to-Right (Preferred)
```text
[Data Source] → [Processing] → [Storage] → [Analysis]
```
**Use for:** ETL pipelines, request-response, sequential processing

### Top-to-Bottom (Alternative)
```text
[User/Client]
     ↓
[Load Balancer]
     ↓
[Application]
     ↓
[Database]
```
**Use for:** User-facing architectures, hierarchical systems

### Hub-and-Spoke
```text
    [Service A]
         ↓
  [Central Hub] ← [Service C]
         ↓
    [Service B]
```
**Use for:** API gateway, message bus, service mesh

## Line Types

| Flow Type | Line Style | Use Case |
|-----------|------------|----------|
| Data Flow | Solid line | Read/write operations |
| Data Ingestion | Dashed line | Data import |
| Control Flow | Dotted line | Management/config |
| Event Flow | Wavy line | Event-driven |

## Common Patterns

### Three-Tier
```text
[Presentation] → [Business Logic] → [Data Access] → [Database]
```

### Microservices
```text
[API Gateway] → [Service A] → [DB A]
             → [Service B] → [DB B]
             → [Service C] → [Cache]
```

### Event-Driven
```text
[Producer] → [Event Bus] → [Consumer A]
                        → [Consumer B]
```

### Serverless
```text
[API Gateway] → [Lambda] → [DynamoDB]
```

## Visual Clarity Rules

### Spacing
- **Standard gap**: 100px between elements
- **Frame margins**: 30px minimum from boundaries
- **Arrow clearance**: 20px from labels

### Alignment
- Align elements horizontally or vertically
- Match center coordinates for alignment
- Use consistent icon sizes (78x78px standard)

### Labels
- Position near elements
- Avoid overlaps
- Use consistent font (18px+ for presentations)
- Include units where applicable

## Color Usage

Don't rely on color alone - use with patterns/labels:
- **Blue**: Standard services
- **Green**: Success/healthy
- **Red**: Errors/critical
- **Yellow**: Warnings
- **Gray**: Disabled/infrastructure

Ensure WCAG AA contrast (4.5:1 minimum)

## Diagram Types

| Type | Purpose | Include | Audience |
|------|---------|---------|----------|
| Context | System boundaries | External actors, system boundary | Executive |
| System | Main components | Services, databases, flows | Architects |
| Component | Technical details | APIs, integrations, tech choices | Developers |
| Deployment | Infrastructure | VPCs, regions, networks | DevOps |
| Sequence | Time-based interactions | Request/response pairs | Developers |

## Anti-Patterns

### ❌ DON'T:
- Cross arrows unnecessarily
- Use tiny fonts (< 14px)
- Overcrowd diagrams
- Mix abstraction levels
- Use vague labels
- Forget to label arrows

### ✓ DO:
- Keep diagrams focused
- Use consistent spacing
- Label everything clearly
- Align elements
- Include legends
- Version your diagrams
