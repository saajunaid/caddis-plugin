---
name: fastapi-dev
description: Build FastAPI backends with standard patterns, error handling, and testing
---

# FastAPI Development

> **Project Context** — Read `project-config.md` in the repo root for brand tokens, shared-library paths, and deployment targets.

## When to Use

Invoke this skill when:
- Creating a new FastAPI backend for a project
- Adding API endpoints for Streamlit frontends
- Implementing repository pattern with SQL Server
- Setting up dependency injection chains
- Configuring CORS for Streamlit ↔ FastAPI communication
- Deploying FastAPI on IIS/on-premise infrastructure

---

## Project Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application entry
│   ├── config.py            # Settings (pydantic-settings)
│   ├── dependencies.py      # Shared DI providers
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── records.py        # Records endpoints
│   │   └── analytics.py     # Analytics endpoints
│   ├── models/
│   │   ├── __init__.py
│   │   ├── record.py         # Pydantic request/response models
│   │   └── user.py
│   ├── services/
│   │   ├── __init__.py
│   │   └── record_service.py
│   └── repositories/
│       ├── __init__.py
│       └── record_repo.py
├── tests/
├── .env
└── requirements.txt
```

---

## Steps

### Step 1: Configuration (pydantic-settings)

```python
# app/config.py
from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    app_name: str = "API"
    debug: bool = False
    db_server: str = Field(..., description="SQL Server host")
    db_name: str = Field(..., description="Database name")
    db_password: str = Field(..., repr=False)
    api_key: str = Field(..., repr=False)
    allowed_origins: list[str] = ["http://localhost:8501"]
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"

    class Config:
        env_file = ".env"

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

### Step 2: Pydantic Models (Base/Create/Update/Response pattern)

```python
# app/models/record.py
from pydantic import BaseModel, ConfigDict, Field
from uuid import UUID
from datetime import datetime
from typing import Literal

class RecordBase(BaseModel):
    customer_id: str = Field(..., min_length=1, max_length=50, example="CUST001")
    record_type: Literal["billing", "service", "technical"]
    description: str = Field(..., min_length=10, max_length=5000)
    priority: int = Field(default=3, ge=1, le=5)

class RecordCreate(RecordBase):
    pass

class RecordUpdate(BaseModel):
    status: Literal["open", "in_progress", "resolved"] | None = None
    resolution_notes: str | None = Field(None, max_length=2000)
    priority: int | None = Field(None, ge=1, le=5)

class RecordResponse(RecordBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str
    created_at: datetime
    updated_at: datetime | None = None

class RecordList(BaseModel):
    items: list[RecordResponse]
    total: int
    page: int
    per_page: int
    pages: int
```

### Step 3: Dependency Injection Chain

```python
# app/dependencies.py
from typing import Annotated, Generator
from fastapi import Depends, Header, HTTPException
from libs.data import DatabaseAdapter

def get_db_adapter() -> Generator[DatabaseAdapter, None, None]:
    adapter = DatabaseAdapter()
    try:
        yield adapter
    finally:
        adapter.close()

def get_record_repository(
    db: Annotated[DatabaseAdapter, Depends(get_db_adapter)]
) -> RecordRepository:
    return RecordRepository(db)

def get_record_service(
    repo: Annotated[RecordRepository, Depends(get_record_repository)]
) -> RecordService:
    return RecordService(repo)

async def verify_api_key(
    x_api_key: Annotated[str, Header(..., description="API Key")]
) -> str:
    if x_api_key != get_settings().api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key
```

### Step 4: Router Pattern

```python
# app/routers/records.py
from fastapi import APIRouter, Depends, Query
from typing import Annotated

router = APIRouter(prefix="/records", tags=["records"])

@router.get("/", response_model=RecordList)
async def list_records(
    service: Annotated[RecordService, Depends(get_record_service)],
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    status: str | None = None,
):
    return await service.list_records(page=page, per_page=per_page, status=status)

@router.post("/", response_model=RecordResponse, status_code=201)
async def create_record(
    record: RecordCreate,
    service: Annotated[RecordService, Depends(get_record_service)],
):
    return await service.create_record(record)
```

### Step 5: Application Entry

```python
# app/main.py
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

app = FastAPI(title="API", version="1.0.0")

# CORS for Streamlit frontends
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(records_router)

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "API"}

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled error on {request.url.path}: {exc}")
    return JSONResponse(status_code=500, content={"detail": "An internal error occurred"})
```

### Step 6: SQL Server Connection

```python
# Using pyodbc for MSSQL with Windows Auth
import pyodbc

conn_str = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    f"SERVER={settings.db_server};"
    f"DATABASE={settings.db_name};"
    "Trusted_Connection=yes;"
    "Encrypt=yes;"
    "TrustServerCertificate=yes;"
)
conn = pyodbc.connect(conn_str, timeout=10)
```

---

## Patterns and Examples

### Repository Pattern

```python
class RecordRepository:
    def __init__(self, adapter: DatabaseAdapter):
        self._adapter = adapter

    def get_by_id(self, record_id: UUID) -> dict | None:
        query = "SELECT * FROM AppRecords WHERE CaseID = ?"
        return self._adapter.fetch_one(query, (str(record_id),))

    def get_paginated(self, page: int, per_page: int, status: str | None) -> tuple[list, int]:
        count_query = "SELECT COUNT(*) FROM AppRecords"
        params = []
        if status:
            count_query += " WHERE Status = ?"
            params.append(status)
        total = self._adapter.fetch_scalar(count_query, params)

        query = "SELECT * FROM AppRecords"
        if status:
            query += " WHERE Status = ?"
        query += " ORDER BY [Created Date Time] DESC OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
        params.extend([(page - 1) * per_page, per_page])
        items = self._adapter.fetch_all(query, params)
        return items, total
```

### Error Handling with loguru

```python
from loguru import logger

@router.post("/")
async def create_record(record: RecordCreate, service: ...):
    try:
        result = await service.create_record(record)
        logger.info(f"Created record {result.id} for customer {record.customer_id}")
        return result
    except ValidationError as e:
        logger.warning(f"Validation error: {e}")
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to create record: {e}")
        raise HTTPException(status_code=500, detail="Internal error")
```

---

## Checklist

- [ ] Project structure follows standard pattern (routers/models/services/repositories)
- [ ] Pydantic models use Base/Create/Update/Response hierarchy
- [ ] Dependency injection chain: adapter -> repo -> service
- [ ] CORS configured for Streamlit frontend origins
- [ ] Health check endpoint at `/health`
- [ ] Global exception handler with loguru logging
- [ ] SQL queries use parameterized inputs (no f-strings)
- [ ] Configuration via pydantic-settings and .env file
- [ ] API key verification on protected endpoints
- [ ] All endpoints have proper response_model types

## Related Resources

| Resource | Path |
|----------|------|
| FastAPI instructions | `instructions/fastapi.instructions.md` |
| SQL expert skill | `skills/coding/sql/SKILL.md` |
| Python instructions | `instructions/python.instructions.md` |
| Security instructions | `instructions/security.instructions.md` |
