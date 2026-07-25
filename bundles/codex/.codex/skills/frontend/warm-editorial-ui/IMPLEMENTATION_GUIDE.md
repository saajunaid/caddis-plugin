# RevSight Implementation Guide

This document is the practical implementation companion to [DESIGN_TOKENS.md](DESIGN_TOKENS.md).

Use it when rebuilding the mockup as a standard React web application.

## Purpose

This guide exists to make sure the UI is implemented consistently without:
- drifting from the approved color palette
- breaking light/dark theme behavior
- overusing one-off colors, spacing, or typography
- distorting the mockup structure during React implementation

## Source Of Truth

Use these files as the main references:

- [DESIGN_TOKENS.md](DESIGN_TOKENS.md)
- [styles.css](styles.css)
- [src/shell.jsx](src/shell.jsx)
- [index.html](index.html)

If implementation decisions conflict with ad hoc styling in a page, prefer the token system and shell patterns.

## Core Implementation Rules

- Keep `DM Sans` as the default font across the application
- Use `IBM Plex Sans` only in data-dense tables or operational views
- Use `JetBrains Mono` only for IDs, case references, technical values, and code-like metadata
- Do not hard-code colors when a token already exists
- Do not introduce new accent colors without updating the token source and documentation
- Do not replace the neutral surface system with saturated backgrounds
- Do not treat dark mode as a separate design language; it should preserve the same hierarchy and layout

## Theme Architecture

Implement theme support through shared root-level tokens.

### Required Pattern

- Light mode tokens should live at `:root`
- Dark mode tokens should be activated with `[data-theme="dark"]`
- Theme state should be applied at the document root
- Components should consume semantic or surface tokens instead of hard-coded hex values

### Required Theme Behavior

- The UI must support both light and dark mode
- The sidebar footer toggle should switch between those modes
- Theme changes should affect surfaces, text, borders, charts, badges, and interactive states
- Theme changes should not require per-page custom overrides

## Layout Rules

The mockup is built around an app-shell layout, not a marketing-page layout.

### Sidebar

- Left navigation must remain fixed
- The navigation area inside the sidebar should scroll independently when content exceeds the viewport
- The sidebar footer should stay pinned at the bottom
- Collapsed and expanded sidebar states must preserve icon alignment and navigation clarity

### Main Pane

- The main content region must be fully visible and vertically scrollable
- The top bar should remain stable while the user works through long data views
- Avoid adding bottom whitespace caused by unnecessary wrapper heights, transforms, zoom rules, or extra body padding

### Right Detail Pane

- Drawers and detail panes should render at full available height
- The drawer body should scroll internally when content is long
- Header and close behavior should remain visible while content scrolls

## Component Styling Rules

### Cards And Panels

- Use shared surface, border, and shadow tokens
- Keep app chrome, drawers, modals, filters, search, and compact controls on solid token surfaces
- Keep cards, KPI tiles, chart containers, and table surfaces solid so data remains readable and borders stay clear
- Keep cards visually restrained; rely on spacing and hierarchy before decoration
- Use accent tint and border emphasis for selection states instead of heavy fills

### Search, Dropdowns, And Inputs

- Use the shared premium control tokens for search boxes, selects, text inputs, chips, compact icon actions, and utility buttons
- Keep controls solid and layered with subtle gradient fills, not flat gray blocks and not translucent blur
- Use `--control-border` at rest and `--control-border-strong` on hover or raised states
- Use `--shadow-control` for default controls and `--shadow-control-strong` for hover emphasis
- Use `--control-ring` for focus treatment instead of ad hoc box-shadow colors
- Keep control radii slightly softer than default panel radii so the UI feels more deliberate and polished
- Dropdowns should use the same surface language as search and inputs, including the chevron treatment and focus ring

### Tables

- Use `IBM Plex Sans` for denser data tables where scanning matters
- Preserve strong contrast for headers, row values, and hover states
- Use semantic colors carefully for statuses, but keep row backgrounds mostly neutral

### Badges And Status Indicators

- Use semantic tokens consistently:
  - success for healthy/resolved/recovered
  - warning for watch/pending/caution
  - danger for leakage/failure/fraud/critical
  - info for neutral operational information
- Pair important state colors with text or icon support

### Charts

- Use the documented chart palette
- Avoid introducing ad hoc chart colors from individual pages
- Keep chart backgrounds neutral
- Use danger/red for leakage emphasis only where meaningfully required

## React Implementation Expectations

### State And Theme

- Theme state should be centralized and shared
- Accent selection, density, and sidebar state should come from the same shell-level settings model
- Components should respond to tokens and settings rather than duplicating style logic locally

### Component Structure

- Keep shell concerns in the shell layer
- Keep page-level components focused on data presentation and interaction
- Keep reusable visual primitives shared where possible

### Styling Approach

- Prefer token-driven CSS over inline hard-coded values
- Inline styles are acceptable for small dynamic layout adjustments, not for replacing the theme system
- Repeated visual patterns should become reusable classes or primitives

## Dark Mode Implementation Guidance

- Use the same component structure in both light and dark mode
- Change tone, contrast, and emphasis through tokens only
- Keep dark surfaces cool and restrained
- Reserve brighter reds and blues for action, status, and chart emphasis
- Ensure table rows, nav states, chips, and drawer content remain readable in dark mode
- Check that muted text is still legible and not overly dim against slate surfaces

## Accessibility And QA Checks

Before considering the React implementation complete, verify:

- text contrast is acceptable in both light and dark themes
- active, selected, hover, and focus states are visible in both themes
- search boxes, dropdowns, chips, compact icon actions, and utility buttons feel visually consistent with each other
- charts remain readable for multi-series comparisons
- status colors are not the sole indicator of meaning
- the sidebar, topbar, main pane, and right drawer behave correctly at common desktop sizes
- the layout remains usable on smaller laptop widths without visual breakage

## Handoff Checklist For The Next Agent

- Read [DESIGN_TOKENS.md](DESIGN_TOKENS.md) first
- Reuse the theme tokens already present in [styles.css](styles.css)
- Preserve the shell behavior already established in [src/shell.jsx](src/shell.jsx)
- Do not swap the font system back to generic defaults
- Do not reintroduce terracotta or unrelated editorial accent colors
- Do not hard-code page-specific colors that bypass the token system
- Verify the final implementation in both light and dark mode before closing the task

## Practical Standard

If a future implementation decision is unclear, follow this order:

1. Use the existing token system.
2. Reuse an existing shell or component pattern.
3. Add a new token only if the current system cannot express the need cleanly.
4. Update [DESIGN_TOKENS.md](DESIGN_TOKENS.md) if a new token is introduced.
