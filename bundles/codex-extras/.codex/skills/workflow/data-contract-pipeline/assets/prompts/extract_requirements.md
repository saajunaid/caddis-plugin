# Sub-prompt: Extract Requirements

Use this prompt to extract field-level requirements from PRDs, tickets, or docs.
Paste the document content after the divider, then run this prompt.

---

You are extracting structured data requirements from product documentation.

For each UI field, dashboard metric, filter, export column, or data-driven action mentioned in the document, produce a JSON entry with this shape:

```json
{
  "field_label": "Human-readable label as shown in UI",
  "field_key": "camelCase identifier",
  "entity": "Which entity this belongs to (e.g. CustomerSummary)",
  "data_type": "string | number | boolean | date | list | dict",
  "null_semantics": "What NULL means (e.g. 'no revenue on record', 'not applicable')",
  "formula": "Derivation rule if computed (else null)",
  "grain": "Row level, aggregate, daily, monthly (if metric)",
  "source_hint": "Any mention of where data comes from (table name, API, file)",
  "priority": "must-have | nice-to-have | deferred",
  "notes": "Any ambiguity, open questions, or conflicting statements"
}
```

Rules:
- Extract ONLY what is explicitly stated or clearly implied by the document.
- Do not invent field requirements not mentioned.
- If a formula is ambiguous, set `formula: null` and add a note.
- If a field has multiple conflicting definitions, list all variants in `notes`.
- Output a JSON array of requirement objects, followed by a short `## Gaps and Ambiguities` section listing unresolved questions.

---

DOCUMENT:
