# RevSight Design Tokens

This document captures the current visual token system used by the RevSight mockup in `mobile-revenue-assurance/project`.

Source of truth:
- `styles.css` for theme tokens
- `src/shell.jsx` for selectable accent options

## Design Direction

The current theme uses:
- Warm neutral light surfaces
- Cool slate dark surfaces
- A strong operational red as the default brand/accent
- A premium solid-control treatment for search, dropdowns, compact buttons, and filter chips
- Utility-oriented semantic colors for success, warning, error, and info states

Default accent:
- `Signal Red`

Default fonts:
- Primary UI: `DM Sans`
- Data-heavy tables: `IBM Plex Sans`
- Mono/code/IDs: `JetBrains Mono`

## Light Theme Tokens

### Brand

- `--brand-primary`: `#E10A0A`
- `--brand-primary-strong`: `#B90707`
- `--brand-primary-soft`: `#FFECEC`
- `--brand-primary-tint`: `#FFF3F3`

### Accent Options

- `Signal Red`: `#E10A0A`
- `Cobalt`: `#2563EB`
- `Evergreen`: `#15803D`
- `Slate`: `#334155`

### Surfaces

- `--bg-default`: `#F2EFEB`
- `--bg-subtle`: `#EEE8E0`
- `--surface-default`: `#FFFFFF`
- `--surface-subtle`: `#F6F3EF`
- `--card-default`: `#FFFFFF`

### Text

- `--text-primary`: `#11100F`
- `--text-secondary`: `#2D2925`
- `--text-muted`: `#5B554E`
- `--text-muted-2`: `#81786F`

### Borders

- `--border-default`: `#D8D1C7`
- `--border-subtle`: `#E5E2DC`
- `--border-strong`: `#B9AEA1`

### Semantic Colors

- `--color-success`: `#16A34A`
- `--color-success-soft`: `#F0FDF4`
- `--color-warning`: `#D97706`
- `--color-warning-soft`: `#FFFBEB`
- `--color-danger`: `#DC2626`
- `--color-danger-soft`: `#FEF2F2`
- `--color-info`: `#2563EB`
- `--color-info-soft`: `#EFF6FF`
- `--color-support`: `#7C3AED`
- `--color-support-soft`: `#F5F3FF`

### Chart Palette

- `--chart-1`: `#E10A0A`
- `--chart-2`: `#2563EB`
- `--chart-3`: `#16A34A`
- `--chart-4`: `#D97706`
- `--chart-5`: `#7C3AED`
- `--chart-6`: `#334155`
- `--chart-7`: `#11100F`

## Dark Theme Tokens

### Surfaces

- `--bg-default`: `#0B1118`
- `--bg-subtle`: `#101824`
- `--surface-default`: `#151D28`
- `--surface-subtle`: `#101824`
- `--card-default`: `#18212D`

### Text

- `--text-primary`: `#EEF3F8`
- `--text-secondary`: `#CBD5E1`
- `--text-muted`: `#9AA8B8`
- `--text-muted-2`: `#748194`

### Borders

- `--border-default`: `#314159`
- `--border-subtle`: `#243244`
- `--border-strong`: `#52657C`

### Brand

- `--brand-primary`: `#FF4A4A`
- `--brand-primary-strong`: `#FFD6D6`
- `--brand-primary-soft`: `rgba(255, 74, 74, 0.14)`
- `--brand-primary-tint`: `rgba(255, 74, 74, 0.10)`

### Semantic Colors

- `--color-success`: `#4ADE80`
- `--color-success-soft`: `rgba(63, 185, 80, 0.12)`
- `--color-warning`: `#FBBF24`
- `--color-warning-soft`: `rgba(227, 179, 65, 0.12)`
- `--color-danger`: `#F85149`
- `--color-danger-soft`: `rgba(248, 81, 73, 0.12)`
- `--color-info`: `#38BDF8`
- `--color-info-soft`: `rgba(88, 166, 255, 0.12)`
- `--color-support`: `#A78BFA`
- `--color-support-soft`: `rgba(167, 139, 250, 0.12)`

### Chart Palette

- `--chart-1`: `#FF4A4A`
- `--chart-2`: `#38BDF8`
- `--chart-3`: `#4ADE80`
- `--chart-4`: `#FBBF24`
- `--chart-5`: `#A78BFA`
- `--chart-6`: `#94A3B8`
- `--chart-7`: `#EEF3F8`

## Dark Mode Guidance

Dark mode is not just an inverted light theme. It should feel like a deliberate cool-slate operational workspace.

### Dark Mode Intent

- Keep dark mode cooler and cleaner than light mode
- Preserve the same information hierarchy as light mode
- Use brighter accents only where emphasis is needed
- Avoid flooding the UI with saturated red, blue, or purple fills

### Dark Mode Surface Rules

- Use `--bg-default` for the app shell and main page background
- Use `--bg-subtle` for recessed regions and background layering
- Use `--surface-default` for primary panels, cards, drawers, and top bars
- Use `--surface-subtle` for nested panes, secondary trays, and subdued UI blocks
- Use `--card-default` where a slightly lifted panel needs stronger separation from the background

### Dark Mode Text Rules

- Use `--text-primary` for headings, KPI values, table values, and core content
- Use `--text-secondary` for labels, subtitles, and standard supporting text
- Use `--text-muted` and `--text-muted-2` for low-priority metadata only
- Do not use muted text for anything interactive or operationally important

### Dark Mode Border and Separation Rules

- Use `--border-default` for standard panel outlines and table dividers
- Use `--border-subtle` for softer internal separators
- Use `--border-strong` only when an outline needs more emphasis, such as active or pinned containers
- Prefer separation through tone and spacing first, borders second

### Dark Mode Accent Rules

- Keep `--brand-primary` reserved for primary actions, selected states, active nav highlights, and critical emphasis
- Use `--brand-primary-tint` for selected fills and soft highlighted backgrounds
- Avoid large blocks of pure red background unless the element is intentionally urgent
- In dark mode, red should signal action and leakage emphasis, not become the background system

### Dark Mode Semantic Rules

- `--color-success` should indicate healthy, recovered, or resolved states
- `--color-warning` should indicate watch, pending, or caution states
- `--color-danger` should indicate leakage, failures, fraud, or breached thresholds
- `--color-info` should indicate neutral informational metrics and non-failure operational states
- `--color-support` should be used sparingly for secondary emphasis, special statuses, or supporting charts

### Dark Mode Data Visualization Rules

- Keep chart backgrounds neutral and let the data colors carry meaning
- Prefer `--chart-1` and `--chart-2` for primary series
- Use `--color-danger` or `--chart-1` for problem-series emphasis
- Use `--chart-6` and `--chart-7` for supporting axes, baselines, or neutral comparison series
- Do not place too many saturated series adjacent to each other without neutral spacing or hierarchy

### Dark Mode Interaction Rules

- Hover states should shift tone subtly, not flash brighter versions of the base color
- Selected states should use tint plus border or text reinforcement
- Focus states should remain clearly visible against dark surfaces
- Destructive actions should still be distinguishable from normal primary actions

### Dark Mode Accessibility Notes

- Maintain strong contrast between `--text-primary` and dark surfaces
- Avoid using tinted semantic soft colors as the only signal for status
- Pair color with iconography, labels, dots, or badges for critical states
- Check charts, badges, table chips, and nav highlights for readability on both light and dark themes

## Do and Don't

### Do

- Use `DM Sans` as the default UI font across the application
- Use `IBM Plex Sans` only where denser operational data needs clearer scanning
- Use `JetBrains Mono` for IDs, technical values, and code-like metadata
- Keep page backgrounds neutral and let panels/cards create structure
- Use `Signal Red` for primary actions, active states, and revenue-risk emphasis
- Use semantic colors consistently for health, warning, error, and informational states
- Use tinted fills for selected and active states instead of heavy saturated blocks
- Keep chart colors intentional and limited to meaningful comparisons
- Preserve the same hierarchy and spacing rules in both light and dark mode
- Test important UI surfaces in both themes before treating the design as final

### Don't

- Do not use the accent color as a generic background color for large regions
- Do not mix multiple accent options in the same view without a clear rule
- Do not use muted text for important KPIs, controls, or critical statuses
- Do not rely on color alone to communicate severity or state
- Do not overuse purple/support colors where info, warning, or danger are clearer
- Do not make dark mode a simple inverted copy of light mode
- Do not introduce low-contrast gray-on-gray combinations in panels, tables, or drawers
- Do not overload charts with too many saturated series at once
- Do not use IBM Plex Sans or JetBrains Mono as the default font for the whole UI
- Do not add new colors casually without updating this token note and the shared theme tokens

## Implementation Checklist

- Confirm the app uses `DM Sans` as the default UI font
- Confirm `IBM Plex Sans` is limited to dense tables and operational data views
- Confirm `JetBrains Mono` is limited to IDs, technical metadata, and code-like values
- Confirm all page backgrounds, panels, cards, drawers, and top bars map to the documented surface tokens
- Confirm text colors use the documented hierarchy: primary, secondary, and muted
- Confirm borders and dividers use the shared border tokens instead of hard-coded colors
- Confirm the default accent is `Signal Red`
- Confirm alternate accents, if exposed to users, are limited to `Signal Red`, `Cobalt`, `Evergreen`, and `Slate`
- Confirm primary actions, selected states, and active navigation use the accent system consistently
- Confirm success, warning, danger, and info states use the semantic tokens consistently across badges, chips, KPIs, and alerts
- Confirm charts use the shared chart palette and do not introduce ad hoc series colors
- Confirm both light mode and dark mode are implemented using the documented tokens rather than one-off overrides
- Confirm hover, active, selected, and focus states remain legible in both themes
- Confirm search boxes, dropdowns, chips, icon actions, and utility buttons use the shared control tokens
- Confirm tables, drawers, sidebars, and detail panes maintain sufficient contrast in both themes
- Confirm critical states are not communicated by color alone and include supporting labels, icons, or badges where needed
- Confirm any new token added during implementation is documented in this file and reflected in the shared theme source

## Typography Tokens

- `--font-sans`: `"DM Sans", system-ui, -apple-system, "Segoe UI", sans-serif`
- `--font-display`: `"DM Sans", system-ui, -apple-system, "Segoe UI", sans-serif`
- `--font-data`: `"IBM Plex Sans", "DM Sans", system-ui, sans-serif`
- `--font-mono`: `"JetBrains Mono", "IBM Plex Mono", ui-monospace, Menlo, monospace`

Usage guidance:
- Use `DM Sans` for the majority of the application UI
- Use `IBM Plex Sans` for tables and dense operational data
- Use `JetBrains Mono` for IDs, code-style values, and technical metadata

## Radius Tokens

- `--radius-sm`: `4px`
- `--radius-md`: `6px`
- `--radius-lg`: `10px`
- `--radius-control`: `10px`

## Spacing and Layout Tokens

- `--row-height-default`: `36px`
- `--space-default`: `16px`
- `--space-tight`: `10px`
- `--sidebar-width`: `232px`
- `--topbar-height`: `56px`

## Elevation Tokens

### Light

- `--shadow-sm`: `0 1px 2px rgba(35,34,31,0.04), 0 1px 1px rgba(35,34,31,0.03)`
- `--shadow-md`: `0 2px 8px rgba(35,34,31,0.06), 0 1px 2px rgba(35,34,31,0.04)`
- `--shadow-lg`: `0 12px 32px rgba(35,34,31,0.12), 0 2px 6px rgba(35,34,31,0.06)`

### Dark

- `--shadow-sm`: `0 1px 2px rgba(0,0,0,0.42)`
- `--shadow-md`: `0 8px 24px rgba(0,0,0,0.36)`
- `--shadow-lg`: `0 18px 44px rgba(0,0,0,0.48)`

## Premium Control Tokens

These tokens define the higher-end control styling used on search boxes, dropdowns, text inputs, chips, compact icon actions, and utility buttons.

### Light

- `--control-bg`: `#FBF8F4`
- `--control-bg-hover`: `#FFFFFF`
- `--control-bg-active`: `#FFFFFF`
- `--control-border`: `#D4CCC1`
- `--control-border-strong`: `#B9AEA1`
- `--control-ring`: `color-mix(in oklab, var(--accent-tint) 84%, white)`
- `--shadow-control`: `0 1px 0 rgba(255,255,255,0.78) inset, 0 1px 2px rgba(35,34,31,0.05)`
- `--shadow-control-strong`: `0 1px 0 rgba(255,255,255,0.86) inset, 0 10px 24px rgba(35,34,31,0.08)`

### Dark

- `--control-bg`: `#1B2532`
- `--control-bg-hover`: `#202C3B`
- `--control-bg-active`: `#223041`
- `--control-border`: `#3A4B61`
- `--control-border-strong`: `#5A6E87`
- `--control-ring`: `color-mix(in oklab, var(--accent-tint) 76%, rgba(255,255,255,0.06))`
- `--shadow-control`: `0 1px 0 rgba(255,255,255,0.05) inset, 0 1px 2px rgba(0,0,0,0.22)`
- `--shadow-control-strong`: `0 1px 0 rgba(255,255,255,0.08) inset, 0 12px 28px rgba(0,0,0,0.32)`

## Recommended Usage Rules

### Backgrounds and Surfaces

- App/page background: `--bg-default`
- Secondary app background or subtle pane fills: `--bg-subtle`
- Main panels, cards, drawers: `--surface-default` or `--card-default`
- Sub-panels, selected states, secondary controls: `--surface-subtle`
- Keep cards, KPI tiles, chart containers, and tables on solid surfaces with clear borders
- Keep app chrome, filters, drawers, modals, and compact controls on solid token surfaces with clear borders
- Search boxes, dropdowns, text inputs, chips, compact icon actions, and utility buttons should use the shared control background, border, shadow, and focus-ring tokens rather than raw surface tokens

### Text

- Main content and headings: `--text-primary`
- Secondary labels and subtitles: `--text-secondary`
- Metadata and low-priority text: `--text-muted` or `--text-muted-2`

### Borders

- Standard border: `--border-default`
- Softer separators and inner dividers: `--border-subtle`
- Strong outline emphasis: `--border-strong`
- Premium control outline: `--control-border`
- Hover and raised control outline: `--control-border-strong`

### Actions and States

- Primary actions: `--brand-primary`
- Active nav/selected states: `--brand-primary` with `--brand-primary-tint`
- Positive or recovered states: `--color-success`
- Warning/watch states: `--color-warning`
- Leakage-critical/error states: `--color-danger`
- Informational data states: `--color-info`
- Secondary highlight or special status: `--color-support`
- Focus rings for premium controls should come from `--control-ring`

### Data Visualization

- Use `--chart-1` through `--chart-7` in sequence
- Prefer `--chart-1` and `--chart-2` for primary series
- Reserve `--color-danger` or `--chart-1` for revenue leakage/problem emphasis

## Suggested Standard Naming

If these tokens are later formalized into a shared design system, use a consistent naming model like:

- `color-bg-default`
- `color-bg-subtle`
- `color-surface-default`
- `color-surface-subtle`
- `color-text-primary`
- `color-text-secondary`
- `color-text-muted`
- `color-border-default`
- `color-border-subtle`
- `color-border-strong`
- `color-brand-primary`
- `color-brand-primary-soft`
- `color-brand-primary-tint`
- `color-semantic-success`
- `color-semantic-warning`
- `color-semantic-danger`
- `color-semantic-info`
- `font-sans`
- `font-data`
- `font-mono`
- `radius-sm`
- `radius-md`
- `radius-lg`
- `shadow-sm`
- `shadow-md`
- `shadow-lg`

## CSS Reference Block

```css
:root {
  --brand-primary: #E10A0A;
  --brand-primary-strong: #B90707;
  --brand-primary-soft: #FFECEC;
  --brand-primary-tint: #FFF3F3;

  --accent-signal-red: #E10A0A;
  --accent-cobalt: #2563EB;
  --accent-evergreen: #15803D;
  --accent-slate: #334155;

  --bg-default: #F2EFEB;
  --bg-subtle: #EEE8E0;
  --surface-default: #FFFFFF;
  --surface-subtle: #F6F3EF;
  --card-default: #FFFFFF;

  --text-primary: #11100F;
  --text-secondary: #2D2925;
  --text-muted: #5B554E;
  --text-muted-2: #81786F;

  --border-default: #D8D1C7;
  --border-subtle: #E5E2DC;
  --border-strong: #B9AEA1;

  --color-success: #16A34A;
  --color-success-soft: #F0FDF4;
  --color-warning: #D97706;
  --color-warning-soft: #FFFBEB;
  --color-danger: #DC2626;
  --color-danger-soft: #FEF2F2;
  --color-info: #2563EB;
  --color-info-soft: #EFF6FF;
  --color-support: #7C3AED;
  --color-support-soft: #F5F3FF;

  --chart-1: #E10A0A;
  --chart-2: #2563EB;
  --chart-3: #16A34A;
  --chart-4: #D97706;
  --chart-5: #7C3AED;
  --chart-6: #334155;
  --chart-7: #11100F;
}

[data-theme="dark"] {
  --bg-default: #0B1118;
  --bg-subtle: #101824;
  --surface-default: #151D28;
  --surface-subtle: #101824;
  --card-default: #18212D;

  --text-primary: #EEF3F8;
  --text-secondary: #CBD5E1;
  --text-muted: #9AA8B8;
  --text-muted-2: #748194;

  --border-default: #314159;
  --border-subtle: #243244;
  --border-strong: #52657C;

  --brand-primary: #FF4A4A;
  --brand-primary-strong: #FFD6D6;
  --brand-primary-soft: rgba(255, 74, 74, 0.14);
  --brand-primary-tint: rgba(255, 74, 74, 0.10);

  --color-success: #4ADE80;
  --color-success-soft: rgba(63, 185, 80, 0.12);
  --color-warning: #FBBF24;
  --color-warning-soft: rgba(227, 179, 65, 0.12);
  --color-danger: #F85149;
  --color-danger-soft: rgba(248, 81, 73, 0.12);
  --color-info: #38BDF8;
  --color-info-soft: rgba(88, 166, 255, 0.12);
  --color-support: #A78BFA;
  --color-support-soft: rgba(167, 139, 250, 0.12);

  --chart-1: #FF4A4A;
  --chart-2: #38BDF8;
  --chart-3: #4ADE80;
  --chart-4: #FBBF24;
  --chart-5: #A78BFA;
  --chart-6: #94A3B8;
  --chart-7: #EEF3F8;
}
```
