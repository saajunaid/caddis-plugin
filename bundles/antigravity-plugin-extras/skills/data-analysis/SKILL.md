---
name: data-analysis
context: fork
description: Analyze datasets and generate insights with a systematic 5-phase workflow. Use when user provides data for analysis, asks about patterns, or needs visualizations.
---

# Data Analysis Skill

Systematically analyze datasets to extract insights, identify patterns, and create visualizations.

## When to Use

- User provides a dataset for analysis
- User asks "analyze this data"
- User wants insights from a CSV, DataFrame, or database table
- User asks about data quality or patterns

---

## Phase 1: Data Discovery

```python
import pandas as pd

df = pd.read_csv("data.csv")
print(f"Shape: {df.shape}")
print(f"Columns:\n{df.dtypes}")
print(f"First rows:\n{df.head()}")

# Data quality
missing = df.isnull().sum()
duplicates = df.duplicated().sum()
```

**Output**: Data Discovery Report (shape, types, quality, initial observations)

## Phase 2: Exploratory Analysis

```python
import plotly.express as px

# Distributions, time series, correlations, outliers
for col in numeric_cols:
    fig = px.histogram(df, x=col, title=f"Distribution of {col}")
    fig.show()

corr = df[numeric_cols].corr()
fig = px.imshow(corr, text_auto=True, title="Correlation Matrix")
fig.show()
```

## Phase 3: Deep Analysis

- Segmentation by category
- Comparative analysis (box plots)
- Statistical tests if needed
- Trend decomposition for time series

## Phase 4: Insight Generation

For each insight:
1. **Finding**: What the data shows
2. **Evidence**: Supporting numbers/charts
3. **Implication**: What this means for the business
4. **Recommendation**: What action to take

## Phase 5: Report

```markdown
# Data Analysis Report

## Executive Summary
## Dataset Overview
## Key Insights
## Recommendations
## Appendix (methodology, data quality notes)
```

---

## Branded Charts

```python
CHART_COLORS = ["<BRAND_PRIMARY>", "<BRAND_DARK>", "#6B7280", "#9CA3AF"]

fig.update_layout(
    template="plotly_white",
    font_family="Inter, sans-serif",
    color_discrete_sequence=CHART_COLORS
)
```

---

## Checklist

- [ ] Data loaded and validated
- [ ] Missing values addressed
- [ ] Distributions analyzed
- [ ] Trends identified
- [ ] Correlations checked
- [ ] Outliers investigated
- [ ] Insights are actionable
- [ ] Visualizations are clear
- [ ] Report is well-structured

### Cross-Source Join Safety (when analysis involves merging data from multiple sources)

- [ ] **Join key type compatibility**: Document column types of join keys in each source. Flag type mismatches (e.g., `INT` vs `VARCHAR`) and document required CAST/conversion.
- [ ] **Row cardinality**: Verify whether join keys are unique per source. If 1:N, document deduplication strategy.
- [ ] **Sample merge validation**: Test-merge on sample data, verify output row count matches expectations.
