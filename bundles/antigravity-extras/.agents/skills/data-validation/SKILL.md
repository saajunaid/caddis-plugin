---
name: data-validation
context: fork
description: Data quality and validation patterns for ETL pipelines, API inputs, and data processing. Use when defining validation rules, building data quality checks, implementing schema validation, or designing data contracts. Covers Pydantic, Great Expectations patterns, and SQL-level constraints.
---

# Data Validation Skill

Bad data in → bad decisions out. Validate at every boundary: ingestion, transformation, and output.

## 1. When to Apply This Skill

**Trigger conditions:**
- Building or reviewing ETL/ELT pipelines
- "How do we validate incoming data?"
- Designing data contracts between services
- Data quality issues in production
- Schema migration or new data source integration

## 2. Validation Layers

Validate at three boundaries — not just one.

```
Source → [Ingestion Validation] → Raw Layer
Raw    → [Transform Validation] → Clean Layer
Clean  → [Output Validation]    → Consumer / API / Report
```

| Layer | What to Check | Fail Strategy |
|-------|--------------|---------------|
| **Ingestion** | Schema, types, required fields, file format | Reject row or file, log to dead-letter |
| **Transform** | Business rules, referential integrity, ranges | Flag row, route to review queue |
| **Output** | Final shape matches consumer contract | Block publish, alert team |

## 3. Pydantic Validation (Python)

### Schema Definition

```python
from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import date
from enum import Enum

class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class ComplaintRecord(BaseModel):
    complaint_id: str = Field(..., min_length=1, max_length=50)
    customer_id: str = Field(..., pattern=r"^CUST-\d{6}$")
    category: str = Field(..., min_length=1)
    priority: Priority
    description: str = Field(..., min_length=10, max_length=5000)
    created_date: date
    resolved_date: date | None = None
    amount: float = Field(default=0, ge=0, le=1_000_000)

    @field_validator("resolved_date")
    @classmethod
    def resolved_after_created(cls, v, info):
        if v and info.data.get("created_date") and v < info.data["created_date"]:
            raise ValueError("Resolved date cannot be before created date")
        return v

    @model_validator(mode="after")
    def critical_must_have_description(self):
        if self.priority == Priority.CRITICAL and len(self.description) < 50:
            raise ValueError("Critical complaints require detailed description (50+ chars)")
        return self
```

### Batch Validation with Error Collection

```python
from pydantic import ValidationError
from loguru import logger

def validate_batch(records: list[dict]) -> tuple[list[ComplaintRecord], list[dict]]:
    """Validate records, separating valid from invalid."""
    valid = []
    errors = []

    for i, record in enumerate(records):
        try:
            valid.append(ComplaintRecord.model_validate(record))
        except ValidationError as e:
            errors.append({
                "row": i,
                "data": record,
                "errors": e.errors(),
            })
            logger.warning(f"Row {i} validation failed: {e.error_count()} errors")

    logger.info(f"Validation: {len(valid)} valid, {len(errors)} invalid out of {len(records)}")
    return valid, errors
```

## 4. SQL-Level Constraints

Always enforce at the database level too — application validation alone is insufficient.

```sql
-- Column-level constraints
CREATE TABLE complaints (
    complaint_id    UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID(),
    customer_id     NVARCHAR(50)     NOT NULL,
    category        NVARCHAR(100)    NOT NULL,
    priority        TINYINT          NOT NULL CHECK (priority BETWEEN 1 AND 5),
    description     NVARCHAR(MAX)    NOT NULL,
    amount          DECIMAL(12,2)    NOT NULL DEFAULT 0 CHECK (amount >= 0),
    created_date    DATE             NOT NULL DEFAULT GETDATE(),
    resolved_date   DATE             NULL,

    CONSTRAINT PK_complaints PRIMARY KEY (complaint_id),
    CONSTRAINT CK_resolved_after_created
        CHECK (resolved_date IS NULL OR resolved_date >= created_date)
);

-- Referential integrity
ALTER TABLE complaints
    ADD CONSTRAINT FK_complaints_customer
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id);
```

## 5. Data Quality Checks (Great Expectations Pattern)

Define expectations as declarative rules, then run them against datasets.

```python
def run_quality_checks(df: pd.DataFrame) -> list[dict]:
    """Run data quality checks and return failures."""
    checks = [
        {
            "name": "no_null_customer_ids",
            "check": lambda: df["customer_id"].notna().all(),
            "severity": "critical",
        },
        {
            "name": "valid_priority_range",
            "check": lambda: df["priority"].between(1, 5).all(),
            "severity": "critical",
        },
        {
            "name": "amount_non_negative",
            "check": lambda: (df["amount"] >= 0).all(),
            "severity": "error",
        },
        {
            "name": "description_not_empty",
            "check": lambda: (df["description"].str.len() > 0).all(),
            "severity": "warning",
        },
        {
            "name": "no_future_created_dates",
            "check": lambda: (df["created_date"] <= pd.Timestamp.now()).all(),
            "severity": "error",
        },
    ]

    failures = []
    for check in checks:
        try:
            passed = check["check"]()
            if not passed:
                failures.append({"name": check["name"], "severity": check["severity"]})
        except Exception as e:
            failures.append({"name": check["name"], "severity": "error", "exception": str(e)})

    return failures
```

## 6. Data Contract Template

```markdown
# Data Contract: {Source} → {Consumer}

## Schema
| Field | Type | Required | Constraints | Example |
|-------|------|----------|-------------|---------|
| customer_id | string | Yes | Pattern: CUST-\d{6} | CUST-001234 |
| amount | decimal(12,2) | Yes | >= 0 | 150.00 |
| created_date | date | Yes | <= today | 2025-01-15 |

## Quality SLAs
| Metric | Target |
|--------|--------|
| Null rate (required fields) | 0% |
| Schema conformance | 100% |
| Freshness | Updated within 1 hour |
| Completeness | ≥ 99.5% of source records |

## Change Management
- Schema changes require 2-week notice
- Breaking changes require new version
- Consumer must validate on read (trust but verify)
```

## 7. Validation Strategy by Data Source

| Source | Trust Level | Validation Depth |
|--------|------------|------------------|
| User input (forms, API) | None | Full: type, range, format, business rules |
| Internal service | Medium | Schema + nullability + range |
| Database query result | High | Spot-check: row count, nulls, date ranges |
| Third-party API | Low | Full: schema + retry + fallback |
| File upload (CSV, Excel) | None | Full: encoding, headers, types, row-level |

## 8. Anti-Patterns

| Anti-Pattern | Problem | Fix |
|---|---|---|
| Validate only in application | DB has no constraints = data corruption | Validate at both layers |
| Silently dropping invalid rows | Data loss without trace | Log to dead-letter table with error detail |
| Trusting internal data | One service bug corrupts downstream | Schema-validate at every boundary |
| String-typing everything | No type safety, "1" vs 1 bugs | Use typed models (Pydantic, TypeScript interfaces) |
| Validating after transform | Garbage in, garbage amplified | Validate at ingestion before any transform |
| No freshness check | Stale data looks valid | Check max(created_date) and row counts |
