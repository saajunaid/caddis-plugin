---
name: mermaid-diagrams
context: fork
description: Create software diagrams using Mermaid text-based syntax. Use for class diagrams (domain modeling, OOP design), sequence diagrams (API flows, interactions), flowcharts (processes, algorithms, user journeys), ERD (database schemas), C4 architecture diagrams, state diagrams, git graphs, gantt charts, and data visualization.
---

# Mermaid Diagramming

**Works with:** Any AI coding agent (Claude, Cursor, GitHub Copilot, Windsurf, etc.)

Create professional software diagrams using Mermaid's text-based syntax. Diagrams are version-controllable, easy to update, and render automatically in GitHub, GitLab, Notion, and more.

## Triggers

Use this skill when you need to:
- "diagram this", "visualize this", "model this"
- "show the flow", "map out the process"
- "architecture diagram", "class diagram", "sequence diagram"
- "database schema", "ERD", "entity relationship"
- "flowchart", "user journey", "system design"

## Quick Reference

| Diagram Type | Use For | Syntax Starts With |
|--------------|---------|-------------------|
| **Class Diagram** | Domain models, OOP design | `classDiagram` |
| **Sequence Diagram** | API flows, interactions | `sequenceDiagram` |
| **Flowchart** | Processes, algorithms, user journeys | `flowchart TD` or `flowchart LR` |
| **ERD** | Database schemas | `erDiagram` |
| **C4 Diagram** | Architecture (context, container, component) | `C4Context`, `C4Container`, `C4Component` |
| **State Diagram** | State machines, lifecycles | `stateDiagram-v2` |
| **Git Graph** | Branching strategies | `gitGraph` |
| **Gantt Chart** | Project timelines | `gantt` |

## Core Syntax Pattern

All Mermaid diagrams follow this structure:

```mermaid
diagramType
  definition content
```

**Key principles:**
- First line declares diagram type
- Use `%%` for comments
- Indentation improves readability
- Misspellings break diagrams; validate at [mermaid.live](https://mermaid.live)

## Quick Start Examples

### Class Diagram
```mermaid
classDiagram
    User --> Order : places
    Order *-- LineItem
    
    class User {
        +string email
        +string name
        +placeOrder()
    }
    
    class Order {
        +int id
        +decimal total
        +addItem()
    }
```

### Sequence Diagram
```mermaid
sequenceDiagram
    participant User
    participant API
    participant DB
    
    User->>API: POST /login
    API->>DB: Query credentials
    DB-->>API: Return user data
    alt Valid
        API-->>User: 200 OK + token
    else Invalid
        API-->>User: 401 Unauthorized
    end
```

### Flowchart
```mermaid
flowchart TD
    Start([User visits]) --> Auth{Authenticated?}
    Auth -->|No| Login[Login page]
    Auth -->|Yes| Dashboard[Dashboard]
    Login --> Validate{Valid?}
    Validate -->|Yes| Dashboard
    Validate -->|No| Error[Error message]
```

### ERD
```mermaid
erDiagram
    USER ||--o{ ORDER : places
    ORDER ||--|{ LINE_ITEM : contains
    
    USER {
        int id PK
        string email UK
        string name
    }
    
    ORDER {
        int id PK
        int user_id FK
        decimal total
    }
```

### C4 Context
```mermaid
C4Context
    title System Context
    
    Person(user, "User", "Customer")
    System(app, "Web App", "E-commerce platform")
    System_Ext(payment, "Payment Gateway")
    
    Rel(user, app, "Browses, purchases")
    Rel(app, payment, "Processes payments", "HTTPS")
```

## Essential Syntax

### Relationships (Class/ERD)
```
-->   Association
..>   Dependency
--|>  Inheritance/Generalization
--*   Composition
--o   Aggregation
```

### Arrows (Sequence/Flowchart)
```
->>   Solid arrow (sync message)
-->>  Dashed arrow (response)
-->   Flowchart connection
```

### Node Shapes (Flowchart)
```
[]    Rectangle
()    Rounded
{}    Diamond (decision)
([])  Stadium/pill
[()]  Cylinder (database)
```

### Cardinality (ERD)
```
||--||  One to one
||--o{  One to many
}o--o{  Many to many
```

## Configuration

Add themes and styling:

```mermaid
---
config:
  theme: base
  themeVariables:
    primaryColor: "#ff6b6b"
  look: handDrawn
---
flowchart LR
    A --> B
```

**Themes:** default, forest, dark, neutral, base  
**Look:** classic, handDrawn

## Export & Rendering

**Auto-renders in:**
- GitHub/GitLab Markdown
- VS Code (with Mermaid extension)
- Notion, Obsidian, Confluence

**Export to PNG/SVG:**
- Online: [mermaid.live](https://mermaid.live)
- CLI: `npm install -g @mermaid-js/mermaid-cli`
  ```bash
  mmdc -i diagram.mmd -o diagram.png
  ```

## Best Practices

1. **Start simple** - Core elements first, add details incrementally
2. **One concept per diagram** - Split complex views into focused diagrams
3. **Use clear labels, but SHORT ones** - see *Label length* below. Meaningful names make diagrams
   self-documenting; long ones get silently clipped, and a clipped label is worse than a terse one
   because the reader cannot tell text is missing
4. **Comment extensively** - Use `%%` to explain complex parts
5. **Validate syntax** - Test at [mermaid.live](https://mermaid.live) before committing
6. **Version control** - Store `.mmd` files with code
7. **Keep updated** - Update diagrams when code changes

## Label length — text is CLIPPED, not wrapped, and nothing warns you

**The most common defect in a generated diagram, and it is invisible to the author.** Mermaid does
not error, the diagram renders, and the text is simply cut off mid-word. Two distinct causes:

**1. A long unbroken token in a node label cannot wrap.** Mermaid wraps node text at *spaces* only.
`GenesysConversationTranscripts` is 30 characters with no space in it, so there is no break
opportunity — it overflows the box and is clipped to `GenesysConversationTransc…`. Identifiers,
table names, class names and file paths are all this shape.

**2. Edge labels never wrap at all.** `A -->|"E2 · no index on ConversationStart"| B` renders on one
line at any length, clipping or overlapping neighbouring nodes.

**Rules:**

- **Keep any unbroken token to ~20 characters.** Break longer ones explicitly with `<br/>`:
  `["GenesysConversation<br/>Transcripts"]`.
- **Keep each `<br/>`-separated line to ~25 characters.**
- **Never put a sentence on an edge.** Edge labels get a short id or one word — `|"B2"|`, `|"reads"|`.
  If it needs explaining, explain it in prose or a table beside the diagram.
- **Prefer a short display name plus a lookup table** over cramming full identifiers into nodes:

  ```mermaid
  flowchart TD
      B["Voice<br/>transcripts"] --> APP["dashboard"]
  ```

  | short name | actual table |
  |---|---|
  | Voice transcripts | `dbo.GenesysConversationTranscripts` |

**Check it mechanically before shipping** — cheaper than rendering, and catches both causes:

```bash
python -c "
import re,sys
body=re.search(r'\`\`\`mermaid(.*?)\`\`\`',open(sys.argv[1],encoding='utf-8').read(),re.S).group(1)
for e in re.findall(r'\|\"?([^\"|]+)\"?\|',body):
    if len(e)>15: print(f'EDGE LABEL {len(e)} chars (never wraps): {e}')
for lbl in re.findall(r'\[\"(.*?)\"\]',body):
    for line in lbl.split('<br/>'):
        t=max((len(w) for w in line.split()),default=0)
        if t>20: print(f'LONG TOKEN {t} chars (cannot wrap): {line}')
print('checked')
" FILE.md
```

**Rendering to look at it is better still** — but only if you actually open the image. A diagram that
renders without error is not a diagram that reads correctly, which is the same trap as a passing
test that asserts nothing.

## Common Issues

**Text is cut off mid-word:** see *Label length* above — the label is too long to wrap. This does
not produce an error.

**Diagram won't render:**
- Check for typos in diagram type declaration
- Validate syntax at [mermaid.live](https://mermaid.live)
- Avoid special characters in labels (use quotes if needed)

**Arrows not connecting:**
- Verify node IDs match exactly
- Check arrow syntax (`-->` vs `->>` vs `-->>`)

**Layout looks wrong:**
- Try different direction: `TD` (top-down), `LR` (left-right), `RL`, `BT`
- Use subgraphs to group related elements
- Consider splitting into multiple diagrams

## Detailed References

See `references/` for comprehensive syntax:

- **[class-diagrams.md](references/class-diagrams.md)** - Relationships, multiplicity, methods, domain modeling
- **[sequence-diagrams.md](references/sequence-diagrams.md)** - Messages, activations, loops, alt/opt blocks
- **[flowcharts.md](references/flowcharts.md)** - Shapes, subgraphs, styling, complex flows
- **[erd-diagrams.md](references/erd-diagrams.md)** - Entities, cardinality, keys, attributes
- **[c4-diagrams.md](references/c4-diagrams.md)** - Context, container, component levels
- **[architecture-diagrams.md](references/architecture-diagrams.md)** - Cloud services, infrastructure, deployment
- **[advanced-features.md](references/advanced-features.md)** - Themes, configuration, layout options
- **[workflows.md](references/workflows.md)** - Step-by-step examples
- **[troubleshooting.md](references/troubleshooting.md)** - Common problems and solutions
