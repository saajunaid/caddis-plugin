---
name: enterprise-dashboard-aesthetic-system
description: "Use when: upgrading React/Vite enterprise dashboards, harmonizing dashboard pages, improving executive analytics UI aesthetics, creating cohesive dashboard design systems, adding tasteful motion, or turning data-heavy pages into a polished narrative cockpit. Applies to RevSight-style FastAPI + React + Tailwind + shadcn dashboards."
---

# Enterprise Dashboard Aesthetic System

Use this skill to turn a functional data dashboard into a cohesive executive analytics product. The goal is not decoration. The goal is a calm, high-trust cockpit where every page feels like part of the same operational story.

## Outcome Standard

Ship a dashboard that feels:

- Cohesive across every route, not page-by-page styled.
- Rich enough to attract attention, restrained enough for repeated work.
- Data-first: charts, tables, KPIs, maps, and filters remain readable.
- Brand-aware: brand color drives interaction; semantic colors drive data.
- Accessible: keyboard focus, contrast, reduced motion, and touch targets survive the polish pass.

## Design Direction

Use this default direction for telecom, finance, operations, and internal enterprise dashboards:

- **Aesthetic:** warm executive cockpit with machined surfaces, fine-line grids, and quiet depth.
- **Brand accent:** one interaction accent, usually the brand color.
- **Data palette:** keep separate semantic colors for chart streams and status states.
- **Typography:** one readable UI family, one condensed/display family for KPI punch, one tabular numeric family.
- **Motion:** page and card entrance via transform + opacity only; no layout animation.

Avoid marketing-page hero layouts, decorative blobs, generic blue-purple gradients, and oversized copy that pushes the actual data below the fold.

## Workflow

1. **Map the shared layer first**
   - Find the app shell, global stylesheet, theme store, Tailwind config, shadcn primitives, and route pages.
   - Prefer global tokens and shared classes over one-off page styles.
   - Identify token gaps such as undefined `--surface-*`, status colors, chart colors, or duplicate font definitions.

2. **Establish a token contract**
   - Define primitive, semantic, and component tokens in CSS custom properties.
   - Include light and dark variants together.
   - Include aliases for common usage: `--bg`, `--surface`, `--surface-1`, `--surface-2`, `--border-soft`, `--ink-1..4`, `--brand`, `--brand-tint`, `--green`, `--amber`, `--red`, `--blue`, chart colors, radius, shadows, and motion curve.
   - Point Tailwind `fontFamily` and shadcn HSL bridge tokens at the same source of truth.

3. **Separate interaction color from data color**
   - Brand color: nav active states, primary actions, focus rings, selected chips, important app affordances.
   - Blue/green/amber/red: charts, quality status, revenue signals, health, warnings, and semantic data states.
   - Do not let every page become one hue. Each page can lead with a different data semantic while sharing brand interaction rules.
   - User-selectable color themes must go deeper than accents. Override semantic background, surface, border, ink, shadow, chart, and map-marker tokens so the selected palette changes the whole workspace.
   - Keep product identity separate from theme identity. App names, official logos, and fixed brand marks should use dedicated `--app-*` tokens instead of dynamic `--brand` tokens.

4. **Create page storytelling grammar**
   - Every major route should have a hero/story section with:
     - a short eyebrow naming the operational lens,
     - an H1 that explains the decision surface,
     - concise supporting copy,
     - fact pills grounded in the active data window/source,
     - an optional signal card summarizing the page's core story.
   - Utility pages such as detail browsers still need a hero. They should feel like investigative workspaces, not leftover forms.

5. **Upgrade shared surfaces**
   - Panels/cards use warm gradients, subtle borders, inset highlights, and a consistent shadow scale.
   - KPI cards use top accent bars and tabular numbers.
   - Tables use readable sticky-like headers, clear hover state, and tabular numeric columns.
   - Chart frames use a quiet inset surface so charts feel intentionally housed.
   - Maps use a contained frame with matching radius, border, and attribution styling.

6. **Motion and interaction rules**
   - Animate only `transform` and `opacity`.
   - Use one custom curve, for example `cubic-bezier(0.32, 0.72, 0, 1)`.
   - Add staggered page-section entrance sparingly.
   - Respect `prefers-reduced-motion` by disabling entrance animation and shortening transitions.
   - Buttons and cards should have hover and active states. Keyboard focus must remain visible.

7. **Mobile and dense-data safeguards**
   - Collapse asymmetric layouts to one column below tablet width.
   - Keep main controls near or above 40-44px on mobile.
   - Avoid horizontal page overflow; tables may scroll inside their own container.
   - Do not hide core data just to preserve a desktop composition.

8. **Verification**
   - Run TypeScript build and lint where available.
   - Check modified files for diagnostics.
   - Use the browser at desktop and mobile widths to verify no overlap, no blank charts/maps, and no unreadable text.
   - Review light and dark modes if the app supports both.

## RevSight Implementation Notes

For RevSight-style apps, start with these files:

- `frontend/src/styles/globals.css` for tokens, shared surfaces, motion, tables, charts, maps, and responsive rules.
- `frontend/tailwind.config.js` for token-backed font utilities.
- `frontend/src/components/layout/AppShell.tsx` for sidebar, topbar, navigation, and source-card story details.
- `frontend/src/components/ui/` for shadcn primitive defaults.
- `frontend/src/pages/*Page.tsx` for route-specific hero copy and signal cards.
- `frontend/src/stores/themeStore.ts` and `frontend/src/lib/colorTheme.ts` for persisted color themes, Settings theme options, and map/chart palette wiring.

Useful route grammar:

- Roaming: footprint and country-level operating pulse.
- Geo: spatial spend density and country/operator map context.
- Cost/Revenue: revenue yield, leakage watch, service mix.
- CDR Detail: forensic row-level traceability and export workflow.
- Data Quality: trust, risk, and data integrity verdicts.
- Observability: runtime health and usage signals.
- Settings: control center for appearance, data, telemetry, cache, and deployment health.

## Quality Checklist

- [ ] Brand accent is consistent across nav, focus, chips, and primary actions.
- [ ] App name/logo colors remain stable when user-selectable themes change.
- [ ] Theme palettes affect surfaces, ink, borders, shadows, charts, and maps, not just accents.
- [ ] Data colors are semantic and not overloaded as interaction colors.
- [ ] All route heroes follow the same storytelling grammar.
- [ ] Cards, panels, tables, chart frames, map frames, controls, and badges share tokenized surfaces.
- [ ] No undefined CSS variables are used.
- [ ] No negative letter spacing or viewport-scaled font sizing is introduced.
- [ ] Motion respects reduced-motion preferences.
- [ ] Mobile layout collapses cleanly without text overlap or clipped controls.
- [ ] Build, lint, and browser smoke checks pass.
