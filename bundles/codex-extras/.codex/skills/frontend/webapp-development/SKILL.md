---
name: webapp-development
description: End-to-end web application development workflow with brand theming and standard patterns
---

# Web Application Development

> **Project Context** — Read `project-config.md` in the repo root for brand tokens, shared-library paths, and deployment targets.

## When to Use

Invoke this skill when:
- Building a new web application from scratch
- Adding a new page to an existing Streamlit multi-page app
- Implementing a full feature (UI + service + data layer)
- Integrating Streamlit frontend with FastAPI backend
- Setting up session state and navigation patterns
- Combining multiple standard patterns into a cohesive app

---

## Steps

### Step 1: Create the Page

Every Streamlit page follows this mandatory template:

```python
"""Page Title - Brief description of this page."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.components.shared_header import apply_page_config, render_header

# MUST be the FIRST Streamlit call
apply_page_config("PageName", "icon")
render_header(current_page="PageName")

# --- Page content below ---
```

**Key Rules:**
- `apply_page_config()` MUST be the first Streamlit command
- Use fixed header navigation (NOT sidebar)
- Call `render_header()` with the current page name

### Step 2: Build Components

Extract reusable UI elements into `src/components/`:

```python
# src/components/kpi_cards.py
import streamlit as st

def render_kpi_row(kpis: list[dict]):
    """Render a row of KPI cards with brand theming."""
    cols = st.columns(len(kpis))
    for col, kpi in zip(cols, kpis):
        with col:
            st.metric(
                label=kpi["label"],
                value=kpi["value"],
                delta=kpi.get("delta"),
            )
```

### Step 3: Implement Service Layer

```python
# src/services/record_service.py
from loguru import logger
import pandas as pd

class RecordService:
    def __init__(self, repository):
        self._repo = repository

    def get_dashboard_data(self, filter_type: str, date_str: str = "") -> dict:
        """Get all data needed for the dashboard page."""
        logger.info(f"Loading dashboard data: filter={filter_type}, date={date_str}")
        return {
            "kpis": self._repo.get_kpi_summary(filter_type, date_str),
            "trend": self._repo.get_trend_data(filter_type, date_str),
            "distribution": self._repo.get_workbasket_distribution(filter_type, date_str),
        }
```

### Step 4: Implement Repository Pattern

```python
# src/services/record_repository.py
import pandas as pd
from src.ingestion_config.data_sources import get_data_source_config

class RecordRepository:
    def __init__(self):
        self._config = get_data_source_config()
        self._adapter = self._create_adapter()

    def execute_query(self, query_name: str, **params) -> pd.DataFrame:
        """Execute a named query from queries.yaml."""
        query_config = self._config.get_query(query_name)
        sql = query_config["sql"].format(table=self._config.get_table(query_config["entity"]))
        return self._adapter.fetch_dataframe(sql, params.get("params", []))
```

### Step 5: Externalize SQL Queries

All SQL goes in `src/ingestion_config/queries.yaml`:

```yaml
home_charts:
  workbasket_distribution:
    description: "Count open cases by workbasket for dashboard"
    entity: pega_cases
    sql: |
      SELECT
          ISNULL(WorkbasketHeading, 'Unknown') AS workbasket_heading,
          COUNT(*) AS count
      FROM {table}
      WHERE [Created Date Time] >= ?
        AND [Created Date Time] < ?
        AND Status = 'Open'
      GROUP BY WorkbasketHeading
      ORDER BY count DESC
```

### Step 6: Apply Brand Theming

```python
# Use brand color constants
BRAND_RED = "#E10A0A"
BRAND_NAVY = "#1F2937"
LIGHT_BG = "#F8F9FA"

CHART_COLORS = [BRAND_RED, BRAND_NAVY, "#6B7280", "#9CA3AF", "#D1D5DB"]

# Load CSS theme
def load_theme():
    css_path = Path(__file__).parent.parent / "styles" / "theme.css"
    if css_path.exists():
        st.markdown(f"<style>{css_path.read_text()}</style>", unsafe_allow_html=True)
```

### Step 7: Manage Session State

```python
def init_session_state():
    defaults = {
        "authenticated": False,
        "current_user": None,
        "selected_filters": {},
        "page_number": 1,
        "filter_type": "daily",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

def on_filter_change():
    """Reset pagination when filters change."""
    st.session_state.page_number = 1
```

### Step 8: Add Caching

```python
from datetime import timedelta

@st.cache_data(ttl=timedelta(minutes=15), show_spinner="Loading data...")
def load_dashboard_data(filter_type: str, date_str: str) -> dict:
    service = RecordService(get_repo())
    return service.get_dashboard_data(filter_type, date_str)

@st.cache_resource
def get_repo():
    return RecordRepository()
```

### Step 9: Error Handling

```python
from loguru import logger

try:
    data = load_dashboard_data(filter_type, date_str)
    render_dashboard(data)
except ConnectionError as e:
    logger.error(f"Database connection failed: {e}")
    st.error("Unable to connect to database. Please try again later.")
except Exception as e:
    logger.exception(f"Unexpected error: {e}")
    st.error("An unexpected error occurred. Please contact support.")
```

---

## Patterns and Examples

### Multi-Page App Structure

```
app/
├── Home.py                    # Main entry (streamlit run app/Home.py)
├── pages/
│   ├── 1_Search.py
│   ├── 2_Analytics.py
│   └── 3_Admin.py
├── src/
│   ├── components/
│   │   ├── shared_header.py   # Fixed header with brand theming
│   │   └── kpi_cards.py
│   ├── services/
│   │   ├── cached_repository.py
│   │   └── record_service.py
│   ├── models/
│   ├── ingestion_config/
│   │   ├── data_sources.py
│   │   └── queries.yaml
│   └── styles/
│       └── theme.css
└── .env
```

### Full Page Example

```python
"""Dashboard - Main overview with KPIs and charts."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
from src.components.shared_header import apply_page_config, render_header
from src.components.kpi_cards import render_kpi_row
from src.services.cached_repository import get_chart_data

apply_page_config("Dashboard", "📊")
render_header(current_page="Dashboard")

# Filters
col1, col2 = st.columns([2, 1])
with col1:
    filter_type = st.selectbox("Period", ["daily", "weekly", "monthly"],
                                key="filter_type", on_change=lambda: None)

# KPIs
kpi_data = get_chart_data("kpi_summary", filter_type=filter_type)
render_kpi_row([
    {"label": "Open Cases", "value": kpi_data["open_count"]},
    {"label": "Avg Resolution", "value": f"{kpi_data['avg_hours']:.1f}h"},
    {"label": "SLA Compliance", "value": f"{kpi_data['sla_pct']:.0%}"},
])

# Charts
st.plotly_chart(create_trend_chart(filter_type), use_container_width=True)
```

---

## Checklist

- [ ] `apply_page_config()` is the first Streamlit call on every page
- [ ] `render_header()` called with correct page name
- [ ] No sidebar -- using fixed header navigation
- [ ] Brand colors applied (60-30-10 rule)
- [ ] Service layer separates business logic from UI
- [ ] Repository pattern abstracts data access
- [ ] SQL externalized to queries.yaml
- [ ] Data cached with appropriate TTL
- [ ] Session state initialized with defaults
- [ ] Error handling with user-friendly messages
- [ ] loguru logging for debugging
- [ ] Large datasets paginated
- [ ] Charts use `update_layout(title=...)` not `title=` in px call
- [ ] Empty states show helpful messages

## Related Resources

| Resource | Path |
|----------|------|
| Streamlit dev skill | `skills/frontend/streamlit-dev/SKILL.md` |
| FastAPI dev skill | `skills/coding/fastapi-dev/SKILL.md` |
| SQL expert skill | `skills/coding/sql/SKILL.md` |
| Caching patterns | `skills/coding/caching-patterns/SKILL.md` |
| UX design skill | `skills/frontend/ux-design/SKILL.md` |
