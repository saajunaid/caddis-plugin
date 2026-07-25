---
name: caching-patterns
description: Caching strategies for Streamlit and FastAPI applications
---

# Caching Patterns

> **Project Context** — Read `project-config.md` in the repo root for brand tokens, shared-library paths, and deployment targets.

## When to Use

Invoke this skill when:
- Adding caching to Streamlit data fetches
- Caching database connections or ML models
- Implementing multi-user caching for dashboards
- Setting up Redis caching for FastAPI
- Deciding cache TTL values for application data
- Debugging stale data issues
- Optimizing page load performance

---

## Steps

### Step 1: Choose the Right Caching Strategy

| Scenario | Strategy | Decorator/Tool |
|----------|----------|----------------|
| SQL query results (DataFrames) | Data cache with TTL | `@st.cache_data(ttl=...)` |
| DB connections, adapters | Resource cache (singleton) | `@st.cache_resource` |
| ML models, LLM clients | Resource cache (singleton) | `@st.cache_resource` |
| Multi-user shared data | Cached repository pattern | Custom `get_repo()` |
| FastAPI endpoint responses | Redis or in-memory | `redis` / `cachetools` |
| Static config, lookups | Long TTL or no TTL | `@st.cache_data` |

### Step 2: Implement Streamlit Caching

#### Data Caching (returns serialized copy per caller)

```python
from datetime import timedelta
import streamlit as st
import pandas as pd

@st.cache_data(ttl=timedelta(minutes=15), show_spinner="Loading records...")
def load_records() -> pd.DataFrame:
    """Cached data fetch -- each caller gets an independent copy."""
    from libs.data import DatabaseAdapter
    adapter = DatabaseAdapter()
    return adapter.fetch_dataframe(
        "SELECT * FROM AppRecords WHERE [Created Date Time] >= DATEADD(day, -7, GETDATE())"
    )
```

#### Resource Caching (shared singleton)

```python
@st.cache_resource
def get_database_adapter():
    """Singleton resource -- shared across all users."""
    from libs.data import DatabaseAdapter
    return DatabaseAdapter()

@st.cache_resource
def load_ml_model():
    """Load and cache ML model."""
    import joblib
    return joblib.load("models/classifier.joblib")
```

### Step 3: Multi-User Cached Repository Pattern

```python
# src/services/cached_repository.py
import streamlit as st
from datetime import timedelta
from copy import deepcopy

@st.cache_data(ttl=timedelta(minutes=15), show_spinner=False)
def _fetch_data(query_name: str, filter_type: str, date_str: str = "") -> pd.DataFrame:
    """Internal cached fetch -- keyed by query + filters."""
    repo = _get_repo_instance()
    return repo.execute_query(query_name, filter_type=filter_type, date_str=date_str)

def get_chart_data(query_name: str, filter_type: str, date_str: str = "") -> pd.DataFrame:
    """Public API -- returns deep copy to prevent mutation."""
    return deepcopy(_fetch_data(query_name, filter_type, date_str))

@st.cache_resource
def _get_repo_instance():
    """Singleton repository instance."""
    from src.services.data_repository import DataRepository
    return DataRepository()
```

### Step 4: FastAPI Caching (Redis or In-Memory)

```python
# Redis caching for FastAPI
from functools import lru_cache
from cachetools import TTLCache

# In-memory TTL cache (simple, no Redis dependency)
_cache = TTLCache(maxsize=100, ttl=900)  # 15 min TTL

async def get_records_cached(status: str) -> list:
    cache_key = f"records:{status}"
    if cache_key in _cache:
        return _cache[cache_key]
    result = await repo.get_by_status(status)
    _cache[cache_key] = result
    return result

# Cache invalidation on write
async def create_record(record: RecordCreate):
    result = await repo.create(record)
    # Invalidate relevant cache entries
    _cache.pop(f"records:{record.status}", None)
    return result
```

### Step 5: Set TTL Values

| Data Type | Recommended TTL | Rationale |
|-----------|----------------|-----------|
| Dashboard KPIs | 15 min | Balance freshness vs performance |
| Records list | 5-10 min | Users expect near-real-time |
| Static lookups (categories) | 1 hour | Rarely change |
| User session data | No cache | Must be real-time |
| Historical reports | 1 hour+ | Data doesn't change |
| DB connections | No TTL (resource) | Persist for app lifetime |

### Step 6: SPA Shell/Asset Cache Coherence (FastAPI + Vite)

For FastAPI-served SPAs, split cache behavior by file type:

- `index.html` (app shell): `Cache-Control: no-cache, no-store, must-revalidate`
- `/assets/*` hashed bundles: `Cache-Control: public, max-age=31536000, immutable`

Why this matters:
- The shell maps route/module imports to hashed chunk filenames.
- If old shell HTML is cached, it points to deleted chunks after deploy.
- Hashed bundles are immutable and safe for long cache.

Recommended implementation:
1. Mount `/assets` using a `StaticFiles` subclass that injects immutable cache headers.
2. Serve `index.html` via `FileResponse(..., headers={"Cache-Control": "no-cache, no-store, must-revalidate"})`.
3. Add frontend lazy-import fallback: one automatic reload on chunk-load failure, then show explicit retry UI.

---

## Patterns and Examples

### Cache Key Strategy

```python
# Good: include all parameters that affect the result
@st.cache_data(ttl=timedelta(minutes=15))
def load_data(filter_type: str, date_range: str, category: str | None = None):
    # Streamlit auto-generates cache key from all arguments
    ...

# Bad: mutable objects as parameters (breaks caching)
@st.cache_data(ttl=timedelta(minutes=15))
def load_data(filters: dict):  # dict is unhashable!
    ...
```

### Performance Logging

```python
from loguru import logger
import time

@st.cache_data(ttl=timedelta(minutes=15), show_spinner="Loading...")
def load_records_with_logging() -> pd.DataFrame:
    start = time.perf_counter()
    adapter = get_database_adapter()
    df = adapter.fetch_dataframe("SELECT * FROM AppRecords WHERE Status = 'Open'")
    elapsed = time.perf_counter() - start
    logger.info(f"Loaded {len(df)} records in {elapsed:.2f}s")
    return df
```

### Cache Warming

```python
def warm_caches():
    """Pre-load critical data on app startup."""
    logger.info("Warming caches...")
    load_records()  # Triggers initial cache fill
    load_categories()
    logger.info("Caches warmed successfully")

# Call at app startup
if "caches_warmed" not in st.session_state:
    warm_caches()
    st.session_state.caches_warmed = True
```

---

## ⚠️ Caching Gotchas (CRITICAL — Read Before Caching)

These are **proven failure modes** encountered in production. Every caching decision must account for them.

### Gotcha 1: `@st.cache_data` Uses Pickle — Pydantic Computed Fields Break

`@st.cache_data` serializes return values with `pickle`. Pydantic models with `@computed_field` or `@property` **will fail** because pickle cannot serialize computed/dynamic attributes.

```python
# ❌ WILL FAIL: Pickle cannot serialize computed fields
from pydantic import BaseModel, computed_field

class CustomerProfile(BaseModel):
    first_name: str
    last_name: str

    @computed_field
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

@st.cache_data(ttl=timedelta(minutes=30))
def get_cached_profile(account: str) -> CustomerProfile:
    return service.lookup(account)  # 💥 UnpicklingError on cache hit
```

**Fix — Use JSON serialization layer:**
```python
# ✅ CORRECT: Serialize to JSON, deserialize on read
@st.cache_data(ttl=timedelta(minutes=30))
def _get_profile_json(account: str) -> str:
    """Cache stores JSON string (always picklable)."""
    profile = service.lookup(account)
    return profile.model_dump_json()

def get_cached_profile(account: str) -> CustomerProfile:
    """Public API — returns reconstructed Pydantic model."""
    json_str = _get_profile_json(account)
    return CustomerProfile.model_validate_json(json_str)
```

**Rule: Never use `@st.cache_data` directly on functions returning Pydantic models with computed fields. Always use a JSON serialization layer.**

### Gotcha 2: `@st.cache_resource` + Streamlit Hot-Reload = Type Mismatch

`@st.cache_resource` returns a **singleton reference**. When Streamlit hot-reloads (code change, file save), Python re-imports all modules, creating **new class definitions**. But the cached singleton still holds an instance of the **old** class. This causes `isinstance()` checks and Pydantic `model_validate()` to fail with confusing `ValidationError`s.

```python
# ❌ DANGEROUS: Cached resource survives hot-reload, class identity changes
@st.cache_resource
def get_service() -> CustomerLookupService:
    return CustomerLookupService()

# After hot-reload, this service holds old CustomerInfo class
# Any isinstance() or Pydantic validation against new CustomerInfo fails
```

**Fix — Use `@st.cache_resource` only for stateless adapters, never for services that return typed domain objects:**
```python
# ✅ SAFE: Cache the stateless adapter, create service fresh
@st.cache_resource
def get_db_adapter():
    return DatabaseAdapter()  # Stateless, no typed domain objects

def get_service() -> CustomerLookupService:
    """Fresh service instance — uses cached adapter underneath."""
    return CustomerLookupService(adapter=get_db_adapter())
```

**Rule: `@st.cache_resource` is safe for stateless I/O objects (DB adapters, HTTP clients, ML models). It is NOT safe for services that construct and return Pydantic/dataclass instances.**

### Gotcha 3: Caching Objects That Hold References to Session State

Objects stored in `@st.cache_resource` must NEVER reference `st.session_state`. Session state is per-user; cached resources are shared across all users.

```python
# ❌ BAD: Leaks one user's state to all users
@st.cache_resource
def get_service():
    service = MyService()
    service.user = st.session_state.get("current_user")  # 💥 Shared!
    return service
```

### Gotcha 4: Don't Cache What Shouldn't Be Cached (YAGNI)

Not everything benefits from caching. Apply the KISS principle:

| Should Cache | Should NOT Cache |
|-------------|-----------------|
| Expensive DB queries (>500ms) | Lightweight dict lookups |
| ML model loading | Simple string formatting |
| External API calls | Already-loaded DataFrame filtering |
| Aggregate computations | Session-specific data |

**Rule: Measure before caching. If the uncached operation takes <100ms, caching adds complexity for zero benefit.**

### Gotcha 5: Overlapping Model Fields (Data Deduplication)

When a model has multiple fields that can resolve to the same value (e.g., `display_phone` and `mobile_number` both containing the mobile number for mobile-only customers), the **UI must deduplicate** before display.

```python
# ❌ BAD: Shows same number twice
st.caption(f"📞 {profile.display_phone}")
st.caption(f"📱 {profile.mobile_number}")

# ✅ GOOD: Deduplicate at display time
phones = {}
if profile.display_phone:
    phones[profile.display_phone] = "📞"
if profile.mobile_number and profile.mobile_number != profile.display_phone:
    phones[profile.mobile_number] = "📱"
for number, icon in phones.items():
    st.caption(f"{icon} {number}")
```

### Gotcha 6: Stale Shell HTML Causes Chunk 404s After Deploy

Symptom:
- Browser error: `Failed to fetch dynamically imported module: .../assets/<chunk>.js`
- Requested chunk hash does not exist on server.

Root cause:
- Cached `index.html` references old chunk hash names from prior build.

Mitigation:
1. Enforce shell/asset split cache policy from Step 6.
2. Keep route/module imports behind retry-capable lazy loaders.
3. Auto-reload once on chunk-load error, then stop and show retry prompt.

### Gotcha 7: Long-Lived Sessions Miss Deploys (Dashboard Left Open)

Symptom:
- User leaves dashboard tab open for hours/days (common with executives).
- After a deploy, the old main bundle references chunk hashes that no longer exist on disk.
- Navigating between tabs triggers `Failed to fetch dynamically imported module` errors.
- Reactive chunk recovery (Gotcha 6) helps but only fires on error — user already sees a broken state.

Root cause:
- The browser loaded the main bundle at time T. A deploy at T+N produced new chunk hashes. The running bundle still references the old hashes.

**Why not Service Workers?** Service workers (e.g. `vite-plugin-pwa`) are the industry standard for cache management but require HTTPS. Intranet apps on plain HTTP (e.g. IIS on internal hostnames) cannot register a service worker. Use the 3-layer approach below instead.

Mitigation (3-layer proactive version detection — zero-gap):
1. **Build-time**: Emit `version.json` to `dist/` with a unique build ID. Inject the same ID as `import.meta.env.VITE_BUILD_VERSION`.
2. **Router `beforeLoad`**: Check version on every route navigation via a shared `version-check.ts` module. This is the critical layer — it catches stale chunks **before** they are requested, not after.
3. **Periodic polling (60 s)** + **`visibilitychange`**: A React hook polls every 60 seconds and on tab refocus. Handles the idle-tab and tab-switch-back scenarios.
4. **Update strategy**:
   - Background tab → `window.location.reload()` silently.
   - Foreground tab → brief "Updating…" toast, reload after ~3 seconds.
5. **Loop prevention**: Store reloaded version in `sessionStorage`. Skip reload if session already reloaded for that version.
6. **Fetch hygiene**: Use `cache: "no-store"` + `_t=<timestamp>` query param to bypass HTTP cache for `version.json`. Shared module caches fetch results for 30 s so rapid tab switches don't hammer the server.

Version JSON should live in the dist root (not under `/assets/`), which means the SPA catch-all serves it — verify no immutable cache header leaks onto it.

This pattern is complementary to chunk retry (Step 6 + Gotcha 6) — the 3-layer check prevents the error from happening at all, while retry handles transient network failures.

---

## Checklist

- [ ] Data fetches use `@st.cache_data` with appropriate TTL
- [ ] DB connections use `@st.cache_resource` (no TTL)
- [ ] Multi-user data returns deep copies (not shared references)
- [ ] Cache keys include all filter/parameter variations
- [ ] No mutable objects (dict, list) as cache function parameters
- [ ] TTL values documented and justified
- [ ] Cache invalidation strategy for write operations
- [ ] Performance logging for slow queries
- [ ] `show_spinner` set on user-facing cached functions
- [ ] Cache warming for critical dashboard data
- [ ] **No `@st.cache_data` on Pydantic models with computed fields** (use JSON layer)
- [ ] **No `@st.cache_resource` on services returning typed domain objects** (hot-reload risk)
- [ ] **Caching is justified by measurement** (not speculative — YAGNI)
- [ ] **SPA version polling implemented** for long-lived sessions (Gotcha 7)

## Related Resources

| Resource | Path |
|----------|------|
| Streamlit dev skill | `skills/frontend/streamlit-dev/SKILL.md` |
| Streamlit instructions | `instructions/streamlit.instructions.md` |
| SQL expert skill | `skills/coding/sql/SKILL.md` |
