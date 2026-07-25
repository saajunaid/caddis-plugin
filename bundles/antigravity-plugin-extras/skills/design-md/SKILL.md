---
name: design-md
description: Google's open DESIGN.md specification for describing visual identities to coding agents. YAML tokens + Markdown rationale + npx CLI for WCAG validation and W3C DTCG/Tailwind export. Use for formal, agent-consumable design system documentation.
source: NousResearch/hermes-agent
---

# DESIGN.md

[Google's open spec](https://github.com/google-labs-code/design.md) (Apache-2.0) for writing visual identities as structured files that coding agents can consume. Combines machine-readable YAML tokens with human-readable Markdown rationale.

**Not the same as `design-system-tokens`**: that skill covers our internal three-layer token architecture (primitive→semantic→component) for building actual CSS systems. `design-md` is a *specification format* — a document you write to describe a brand to an agent, with a CLI for validation and export.

## When to Use

- Creating a formal design spec a coding agent will reference when building UI
- Multi-project brand consistency where the spec needs to be version-controlled
- Validating color palette for WCAG AA contrast compliance
- Exporting to Tailwind theme JSON or W3C DTCG token format
- Working with teams who want a single source of truth for design tokens

Use `popular-web-designs` or `warm-editorial-ui` instead for one-off prototypes or visual inspiration.

## File Structure

```
DESIGN.md
```
Single file. YAML front matter (tokens) + Markdown body (rationale).

```yaml
---
version: alpha
name: "Brand Name"
description: "One-line description of the visual identity"

colors:
  primary: "#6366f1"
  primary-hover: "#4f46e5"
  background: "#ffffff"
  surface: "#f8fafc"
  text: "#0f172a"
  text-secondary: "#64748b"
  border: "#e2e8f0"
  success: "#10b981"
  warning: "#f59e0b"
  danger: "#ef4444"

typography:
  font-heading: "Inter"
  font-body: "Inter"
  font-mono: "JetBrains Mono"
  size-xs: "0.75rem"
  size-sm: "0.875rem"
  size-base: "1rem"
  size-lg: "1.125rem"
  size-xl: "1.25rem"
  size-2xl: "1.5rem"
  size-3xl: "1.875rem"
  size-4xl: "2.25rem"

spacing:
  xs: "0.25rem"
  sm: "0.5rem"
  md: "1rem"
  lg: "1.5rem"
  xl: "2rem"
  2xl: "3rem"

rounded:
  sm: "0.25rem"
  md: "0.375rem"
  lg: "0.5rem"
  xl: "0.75rem"
  full: "9999px"
---
```

## Markdown Sections (canonical order)

```markdown
## Overview
One paragraph: brand personality, target audience, emotional goal.

## Colors
Why each color was chosen. Contrast ratios for key pairs. Light/dark mode notes.

## Typography
Font selection rationale. Hierarchy explanation. When to use heading vs body.

## Layout
Grid system. Max content width. Whitespace philosophy.

## Elevation & Depth
Shadow system. Z-index scale. When to use each elevation level.

## Shapes
Border-radius philosophy. When to use rounded vs sharp.

## Components
Key component decisions. Button variants. Card patterns. Form style.

## Do's and Don'ts
Concrete usage rules. What breaks the brand. Common mistakes.
```

## Token Reference Syntax

Use dotted paths to reference other tokens (single source of truth):

```yaml
colors:
  primary: "#6366f1"
  button-bg: "{colors.primary}"         # references primary
  button-hover: "{colors.primary-hover}"
```

## Critical Rules

- **Component variants as sibling keys** — never nested:
  ```yaml
  # ✓ Correct
  button-primary-bg: "#6366f1"
  button-primary-hover-bg: "#4f46e5"
  button-secondary-bg: "transparent"
  
  # ✗ Wrong (no nesting)
  button:
    primary:
      bg: "#6366f1"
  ```
- **Hex colors must be quoted** in YAML (they start with `#` which YAML treats as comments if unquoted)
- **Negative values must be quoted**: `margin-top: "-0.5rem"` not `margin-top: -0.5rem`
- Current spec version is `alpha` — the schema may evolve

## CLI

```bash
# Install (one-time)
npx @google/design.md --help

# Validate structure and WCAG contrast
npx @google/design.md validate DESIGN.md

# Compare two versions (detect regressions)
npx @google/design.md diff DESIGN.md DESIGN.v2.md

# Export to Tailwind theme config
npx @google/design.md export --format tailwind DESIGN.md > tailwind-theme.json

# Export to W3C DTCG format
npx @google/design.md export --format dtcg DESIGN.md > tokens.json
```

## Workflow

1. **Gather brand inputs**: existing screenshots, hex codes, font names, brand guidelines
2. **Write YAML tokens** first — colors, typography, spacing, rounded
3. **Write Markdown sections** — explain rationale, not just values
4. **Run validate** — check WCAG contrast on critical pairs (primary on background, text on surface)
5. **Export if needed** — Tailwind JSON for implementation, DTCG for design tools
6. **Commit alongside code** — `DESIGN.md` lives in the repo root or `docs/`

## Integration with Other Skills

- After writing `DESIGN.md`, use `popular-web-designs` for inspiration on how real brands apply similar systems
- Use `design-system-tokens` when you need to implement the spec as actual CSS custom properties
- Use `warm-editorial-ui` when the project is your organization's internal app family — it already has a complete DESIGN.md-compatible token set
