---
name: streamlit-dev
description: Build production-ready Streamlit dashboards with best-practice patterns, caching, components, and theming. Use when implementing any Streamlit page, component, chart, or UI feature.
---

# Streamlit Development Skill

## When to Use

Invoke this skill when:
- Creating a new Streamlit page
- Building or modifying UI components
- Adding charts or KPIs
- Implementing caching for data or resources
- Applying consistent branding/theming
- Fixing UI/UX issues in Streamlit apps

---

## Page Template (MANDATORY)

Every Streamlit page MUST follow this structure:

```python
"""Page Title - Brief description."""
import streamlit as st

# Page config MUST be the first Streamlit call
st.set_page_config(page_title="PageName", page_icon="icon", layout="wide")

# If using a shared header/navigation component:
# from components.header import render_header
# render_header(current_page="PageName")

# --- Page content below ---
```

### Key Rules
- `st.set_page_config()` MUST be the first Streamlit command
- Choose navigation pattern: sidebar (default) or custom header
- Always set `layout="wide"` for dashboards

---

## Branding & Theming

### Color Palette (Configure Per Project)

```python
BRAND_PRIMARY = "<BRAND_PRIMARY>"     # Primary accent color
BRAND_DARK = "<BRAND_DARK>"           # Headings, dark text
BRAND_LIGHT = "<BRAND_LIGHT>"         # Page/card backgrounds
GRAY_500 = "#6C757D"                  # Secondary text
GRAY_100 = "#E9ECEF"                  # Borders, dividers
SUCCESS = "#22C55E"                   # Positive indicators
WARNING = "#F59E0B"                   # Warning indicators
ERROR = "#EF4444"                     # Error/negative indicators
```

### 60-30-10 Color Rule
- **60%**: Light backgrounds (white, `<BRAND_LIGHT>`)
- **30%**: Dark text and structure (`<BRAND_DARK>`)
- **10%**: Primary accents (`<BRAND_PRIMARY>`)

---

## Charts (Plotly)

### CRITICAL: Avoid "undefined" Labels

```python
# NEVER pass title directly to px functions
fig = px.pie(data, names="cat", values="count")
fig.update_layout(title="Chart Title", height=300)
```

### Branded Charts

```python
import plotly.express as px

CHART_COLORS = ["<BRAND_PRIMARY>", "<BRAND_DARK>", "#6B7280", "#9CA3AF", "#D1D5DB"]

def create_chart(df, x, y, chart_type="bar", title=None):
    if chart_type == "bar":
        fig = px.bar(df, x=x, y=y, color_discrete_sequence=CHART_COLORS)
    elif chart_type == "line":
        fig = px.line(df, x=x, y=y, color_discrete_sequence=CHART_COLORS)
    elif chart_type == "pie":
        fig = px.pie(df, names=x, values=y, color_discrete_sequence=CHART_COLORS)

    fig.update_layout(
        title=title if title and title.strip() else "",
        template="plotly_white",
        font_family="Inter, sans-serif",
        title_font_size=18,
        legend_title_text="",
        hovermode="x unified",
    )
    return fig

st.plotly_chart(fig, use_container_width=True)
```

---

## Caching Strategy

### Data Caching (serialized copy per caller)

```python
from datetime import timedelta

@st.cache_data(ttl=timedelta(minutes=15), show_spinner="Loading data...")
def load_orders() -> pd.DataFrame:
    return repo.get_all_orders()
```

### Resource Caching (shared singleton)

```python
@st.cache_resource
def get_repository():
    return OrdersRepository()
```

### When to Use Each

| Decorator | Use For | Returns |
|-----------|---------|---------|
| `@st.cache_data` | DataFrames, lists, dicts | Serialized copy |
| `@st.cache_resource` | Connections, models, adapters | Same object ref |

---

## Component Patterns

### KPI Cards

```python
def render_kpi_row(kpis: list[dict]):
    cols = st.columns(len(kpis))
    for col, kpi in zip(cols, kpis):
        with col:
            st.metric(label=kpi["label"], value=kpi["value"], delta=kpi.get("delta"))
```

### Data Tables

```python
st.dataframe(
    df, use_container_width=True, hide_index=True,
    column_config={
        "id": st.column_config.TextColumn("ID", width="small"),
        "created_at": st.column_config.DatetimeColumn("Created", format="DD/MM/YYYY HH:mm"),
    }
)
```

### Pagination

```python
def paginate_df(df, page, per_page):
    start = (page - 1) * per_page
    return df.iloc[start:start + per_page]

total_pages = (len(df) - 1) // per_page + 1
page = st.number_input(f"Page (of {total_pages})", 1, total_pages, 1)
st.dataframe(paginate_df(df, page, per_page))
```

---

## Session State

```python
def init_session_state():
    defaults = {"authenticated": False, "selected_filters": {}, "page_number": 1}
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

def on_filter_change():
    st.session_state.page_number = 1

st.selectbox("Category", options=categories, key="filter", on_change=on_filter_change)
```

---

## Forms

```python
with st.form("order_form", clear_on_submit=True):
    customer_id = st.text_input("Customer ID*")
    description = st.text_area("Description*", max_chars=2000)
    priority = st.slider("Priority", 1, 5, 3)

    if st.form_submit_button("Submit", type="primary"):
        if not customer_id or not description:
            st.error("Please fill in all required fields")
        else:
            save_order(customer_id, description, priority)
            st.success("Submitted!")
```

---

## Error Handling

```python
try:
    data = load_data()
    render_dashboard(data)
except ConnectionError:
    st.error("Unable to connect to database. Please try again later.")
except Exception:
    st.error("An unexpected error occurred. Please contact support.")
```

### Empty State

```python
if df.empty:
    st.info("No data found for the selected filters.")
    return
```

---

## Performance Tips

1. **Cache aggressively** -- data fetches, computations, model loading
2. **Lazy load** -- only fetch data when needed
3. **Paginate** -- never dump 10K+ rows into `st.dataframe`
4. **Minimize reruns** -- use `st.session_state` and callbacks
5. **Use `st.fragment`** -- for widgets that shouldn't rerun the whole page

---

## Framework Limitations — Floating UI (CRITICAL)

Streamlit wraps all `st.markdown(unsafe_allow_html=True)` in **20-30 nested `<div>` containers**, breaking CSS `position: fixed/absolute`. **Do NOT attempt CSS-only solutions for floating elements.**

| Approach | Use For | Limitations |
|----------|---------|-------------|
| `st.markdown(unsafe_allow_html=True)` | Inline styling, cards, badges | Wrapped in nested divs; no DOM control |
| `st.html()` | Self-contained HTML snippets | Sandboxed iframe; no access to parent DOM |
| `components.declare_component()` | **Floating UI, chat widgets, FABs, toasts, modals** | Requires HTML/JS file; bi-directional via `setComponentValue` |

**Pattern:** Use `declare_component()` with `height=0` to create an invisible iframe, then inject elements into `window.parent.document.body` from the component's JavaScript.

> CSS `position: fixed` and `z-index` escalation will **never work** reliably in Streamlit due to its DOM wrapping architecture.

---

## Checklist

- [ ] `st.set_page_config()` is the first Streamlit call
- [ ] Navigation pattern applied consistently
- [ ] Brand colors applied (60-30-10 rule)
- [ ] Charts use `update_layout(title=...)` not `title=` in px call
- [ ] Data cached with appropriate TTL
- [ ] Empty states show helpful messages
- [ ] Error handling with user-friendly messages
- [ ] Large datasets paginated
- [ ] Session state initialized with defaults
- [ ] Forms validate required fields
