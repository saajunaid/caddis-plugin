# Sub-prompt: Extract UI Demand

Use this prompt to extract data demand from existing frontend components (JSX, TSX, HTML, Vue templates).
Paste the component source after the divider, then run this prompt.

---

You are extracting data field demand from a frontend component or page.

For each field, prop, variable, or binding that renders or filters data, produce a JSON entry:

```json
{
  "display_label": "Text shown to the user (from label, column header, tooltip, etc.)",
  "prop_or_key": "The prop name or object key used in code (e.g. row.customerId)",
  "component": "Component or page file name",
  "context": "table-column | kpi-card | chart-axis | filter | export | badge | detail-panel | other",
  "inferred_type": "string | number | boolean | date | list | enum | unknown",
  "nullable_in_ui": "true if the UI renders a fallback (e.g. '—', 'N/A') for missing values",
  "current_source": "Where does the value come from? (mock constant, API call, prop, store, hardcoded)",
  "backed": "true | false | unknown — is this connected to a real API or DB?",
  "notes": "Anything suspicious: hardcoded data, TODO comments, demo-only flags"
}
```

Rules:
- Include EVERY rendered field, even if it appears backed by mock data.
- Mark `backed: false` when value is a hardcoded string, imported mock constant, or demo fixture.
- Mark `backed: unknown` when you cannot determine the source from the component alone.
- Do not skip fields because they seem obvious — completeness is required.
- Output a JSON array of demand objects, followed by a `## Mock/Unbacked Fields` section listing fields that are NOT currently connected to real data.

---

COMPONENT SOURCE:
