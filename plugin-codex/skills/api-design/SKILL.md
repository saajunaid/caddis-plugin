---
name: api-design
description: REST and GraphQL API design patterns. Use when designing new API endpoints, defining resource schemas, planning versioning strategies, or reviewing API contracts. Covers naming conventions, pagination, filtering, error responses, and OpenAPI documentation.
---

# API Design Skill

Design APIs that are consistent, discoverable, and hard to misuse. Conventions over configuration.

## 1. When to Apply This Skill

**Trigger conditions:**
- Designing new API endpoints or a full API surface
- "What should this endpoint look like?"
- Planning API versioning or migration
- Reviewing API contracts for consistency
- Building an API spec or OpenAPI document

## 2. REST Resource Naming

### URL Convention

```
# Resources are nouns, plural, lowercase, kebab-case
GET    /api/v1/customers                  # List
GET    /api/v1/customers/{id}             # Get one
POST   /api/v1/customers                  # Create
PUT    /api/v1/customers/{id}             # Full update
PATCH  /api/v1/customers/{id}             # Partial update
DELETE /api/v1/customers/{id}             # Delete

# Nested resources for strong ownership
GET    /api/v1/customers/{id}/orders      # Customer's orders
POST   /api/v1/customers/{id}/orders      # Create order for customer

# Actions (when CRUD doesn't fit) — verb suffix
POST   /api/v1/orders/{id}/cancel         # Action on resource
POST   /api/v1/reports/generate           # Trigger async operation
```

### Naming Rules

| Rule | Good | Bad |
|------|------|-----|
| Plural nouns | `/customers` | `/customer`, `/getCustomers` |
| Kebab-case | `/order-items` | `/orderItems`, `/order_items` |
| No verbs in path | `/customers` (POST = create) | `/createCustomer` |
| Consistent nesting depth | Max 2 levels: `/customers/{id}/orders` | `/customers/{id}/orders/{id}/items/{id}/details` |
| No trailing slash | `/customers` | `/customers/` |

## 3. Request & Response Envelope

### Success Response

```json
{
  "data": { ... },
  "meta": {
    "request_id": "req_abc123",
    "timestamp": "2025-01-15T10:30:00Z"
  }
}
```

### List Response (with pagination)

```json
{
  "data": [ ... ],
  "pagination": {
    "page": 1,
    "per_page": 25,
    "total": 142,
    "total_pages": 6
  }
}
```

### Error Response

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed",
    "details": [
      { "field": "email", "message": "Invalid email format" },
      { "field": "age", "message": "Must be at least 18" }
    ]
  }
}
```

## 4. HTTP Status Codes

Use the right code. Clients depend on these for control flow.

| Code | When to Use |
|------|-------------|
| `200 OK` | Successful GET, PUT, PATCH |
| `201 Created` | Successful POST that creates a resource |
| `204 No Content` | Successful DELETE |
| `400 Bad Request` | Malformed request body or parameters |
| `401 Unauthorized` | Missing or invalid authentication |
| `403 Forbidden` | Authenticated but not authorized |
| `404 Not Found` | Resource doesn't exist |
| `409 Conflict` | Duplicate resource, version conflict |
| `422 Unprocessable Entity` | Valid syntax but semantic validation failed |
| `429 Too Many Requests` | Rate limit exceeded (include `Retry-After` header) |
| `500 Internal Server Error` | Unhandled server error |

## 5. Pagination

### Offset-based (simple, good for most cases)

```
GET /api/v1/customers?page=2&per_page=25
```

### Cursor-based (better for real-time data, large datasets)

```
GET /api/v1/events?cursor=eyJpZCI6MTAwfQ&limit=25
```

| Strategy | Pros | Cons |
|----------|------|------|
| Offset | Simple, supports jumping to page N | Skips/duplicates on mutations, slow at high offsets |
| Cursor | Consistent with mutations, performant | No "jump to page 5", harder to implement |

**Rule:** Use offset for admin/dashboard UIs. Use cursor for feeds, events, and public APIs.

## 6. Filtering, Sorting, and Search

```
# Filtering — field-level with operators
GET /api/v1/orders?status=open&created_after=2025-01-01

# Sorting — field with direction prefix
GET /api/v1/orders?sort=-created_at        # descending
GET /api/v1/orders?sort=status,created_at   # multi-field

# Search — dedicated parameter
GET /api/v1/customers?q=acme+corp

# Field selection — sparse fieldsets
GET /api/v1/customers?fields=id,name,email
```

## 7. Versioning

### URL Path versioning (recommended)

```
/api/v1/customers
/api/v2/customers
```

### Version lifecycle

| Phase | Duration | Behaviour |
|-------|----------|-----------|
| **Current** | Indefinite | Actively maintained |
| **Deprecated** | 6-12 months | Returns `Deprecation` header, still works |
| **Sunset** | After deprecation | Returns `410 Gone` |

```python
# FastAPI deprecation header
@app.get("/api/v1/old-endpoint", deprecated=True)
async def old_endpoint(response: Response):
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "2026-06-01"
    response.headers["Link"] = '</api/v2/new-endpoint>; rel="successor-version"'
    return {"data": ...}
```

## 8. Authentication & Security

- Use `Authorization: Bearer <token>` for API auth
- Never put tokens in URL query parameters (they appear in logs)
- Return `401` for missing/invalid auth, `403` for insufficient permissions
- Include `X-Request-Id` header for tracing
- Rate limit all public endpoints

## 9. FastAPI Implementation Pattern

```python
from fastapi import APIRouter, Depends, Query, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/customers", tags=["customers"])

class CustomerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., pattern=r"^[\w.-]+@[\w.-]+\.\w+$")

class CustomerResponse(BaseModel):
    id: str
    name: str
    email: str

class PaginatedResponse(BaseModel):
    data: list[CustomerResponse]
    pagination: dict

@router.get("", response_model=PaginatedResponse)
async def list_customers(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
):
    ...

@router.post("", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_customer(body: CustomerCreate):
    ...

@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(customer_id: str):
    customer = await repo.find(customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer
```

## 10. API Design Checklist

Before shipping an API endpoint:

- [ ] Resource names are plural nouns in kebab-case
- [ ] Correct HTTP methods (GET reads, POST creates, etc.)
- [ ] Correct status codes (201 for create, 204 for delete)
- [ ] Request body validated with Pydantic/Zod
- [ ] Error responses use consistent envelope with error code
- [ ] Pagination implemented for list endpoints
- [ ] Authentication required (unless intentionally public)
- [ ] Rate limiting configured
- [ ] OpenAPI spec generated and reviewed
- [ ] No sensitive data in URLs or logs

## 11. Anti-Patterns

| Anti-Pattern | Problem | Fix |
|---|---|---|
| Verbs in URLs | `/getUser`, `/deleteOrder` | Use HTTP methods + nouns |
| Inconsistent pluralisation | `/user` vs `/orders` | Always plural |
| Returning 200 for errors | Client can't distinguish success/failure | Use proper status codes |
| Nested resources > 2 levels | Hard to discover, fragile URLs | Flatten with query params |
| No pagination on lists | Unbounded response size, OOM | Always paginate |
| Exposing internal IDs/schemas | Coupling clients to implementation | Use public-facing schemas |
