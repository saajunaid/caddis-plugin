# Knowledge Graph Schema Reference

## Node Types (13 total)

| Type | Description | ID Convention |
|---|---|---|
| `file` | Source code file | `file:<relative-path>` |
| `function` | Function or method | `function:<relative-path>:<name>` |
| `class` | Class, interface, or type | `class:<relative-path>:<name>` |
| `module` | Logical module or package | `module:<name>` |
| `concept` | Abstract concept or pattern | `concept:<name>` |
| `config` | Config file (YAML, JSON, TOML, env) | `config:<relative-path>` |
| `document` | Docs file (Markdown, RST, TXT) | `document:<relative-path>` |
| `service` | Deployable service (Dockerfile, K8s) | `service:<relative-path>` |
| `table` | Database table or migration | `table:<relative-path>:<table-name>` |
| `endpoint` | API endpoint or route | `endpoint:<relative-path>:<endpoint-name>` |
| `pipeline` | CI/CD pipeline config | `pipeline:<relative-path>` |
| `schema` | Schema definition (GraphQL, Protobuf, Prisma) | `schema:<relative-path>` |
| `resource` | Infrastructure resource (Terraform, CloudFormation) | `resource:<relative-path>` |

**File-level types** (assigned to layers, used in tour):
`file`, `config`, `document`, `service`, `table`, `endpoint`, `pipeline`, `schema`, `resource`

**Sub-file types** (not assigned to layers):
`function`, `class`, `module`, `concept`

**Domain/knowledge types** (used by `/understand-knowledge` and `/understand-domain`):
`domain`, `flow`, `step`, `article`, `entity`, `topic`, `claim`, `source`

## Node Fields

| Field | Required | Description |
|---|---|---|
| `id` | ✓ | Unique identifier (type-prefixed) |
| `type` | ✓ | One of the 13 types above |
| `name` | ✓ | Display name |
| `summary` | ✓ | Plain-English description |
| `tags` | ✓ | Array of topic strings |
| `filePath` | ✓ (file-level) | Relative path from project root |
| `complexity` | — | `simple`, `moderate`, or `complex` |
| `languageNotes` | — | Language-specific idioms worth noting |
| `languageLesson` | — | Teaching note for the guided tour |

## Edge Types (26 total)

| Category | Types |
|---|---|
| Structural | `imports`, `exports`, `contains`, `inherits`, `implements` |
| Behavioral | `calls`, `subscribes`, `publishes`, `middleware` |
| Data flow | `reads_from`, `writes_to`, `transforms`, `validates` |
| Dependencies | `depends_on`, `tested_by`, `configures` |
| Semantic | `related`, `similar_to` |
| Infrastructure | `deploys`, `serves`, `provisions`, `triggers` |
| Schema/Data | `migrates`, `documents`, `routes`, `defines_schema` |
| Knowledge graph | `contains_flow`, `flow_step`, `cites` |

## Edge Fields

| Field | Description |
|---|---|
| `source` | Source node ID |
| `target` | Target node ID |
| `type` | One of the 26 edge types |
| `direction` | `outgoing` (source→target) or `incoming` |
| `weight` | 0.0–1.0 relevance weight |

## Edge Weight Conventions

| Type | Weight |
|---|---|
| `contains` | 1.0 |
| `inherits`, `implements` | 0.9 |
| `calls`, `exports`, `defines_schema` | 0.8 |
| `imports`, `deploys`, `migrates` | 0.7 |
| `depends_on`, `configures`, `triggers` | 0.6 |
| `tested_by`, `documents`, `provisions`, `serves`, `routes` | 0.5 |
| All others | 0.5 (default) |

## Architecture Layers (Standard)

Typical layer assignments (may vary by project):

| Layer | Description | Typical types |
|---|---|---|
| `layer:api` | API endpoints, controllers, routes | `endpoint`, `file` |
| `layer:service` | Business logic, services | `file`, `function`, `class` |
| `layer:data` | Database access, models, migrations | `table`, `file`, `schema` |
| `layer:ui` | UI components, views, styles | `file` |
| `layer:utility` | Shared utilities, helpers, types | `file`, `module`, `concept` |
| `layer:config` | Configuration, environment | `config` |
| `layer:infra` | Infrastructure, CI/CD, containers | `service`, `pipeline`, `resource` |
| `layer:docs` | Documentation | `document` |

## Graph-Level Structure

```json
{
  "version": "1.0.0",
  "project": {
    "name": "string",
    "description": "string",
    "languages": ["string"],
    "frameworks": ["string"],
    "analyzedAt": "ISO 8601",
    "gitCommitHash": "string"
  },
  "nodes": [/* GraphNode objects */],
  "edges": [/* GraphEdge objects */],
  "layers": [
    { "id": "layer:<name>", "name": "string", "description": "string", "nodeIds": ["string"] }
  ],
  "tour": [
    { "order": 1, "title": "string", "description": "string", "nodeIds": ["string"], "languageLesson?": "string" }
  ]
}
```
