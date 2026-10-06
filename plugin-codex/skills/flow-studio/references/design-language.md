# Design language

Grounded in `src/styles.css`. This document defines the visual design system, CSS custom properties, typography, spatial scales, state encodings, motion catalogue, and dark theme strategy for flow-studio.

## 1. Design tokens

Tokens are defined on `:root` and adapted for dark mode via `@media (prefers-color-scheme: dark)` and `:root[data-theme="dark"]`.

| Token | Light value | Dark value | Description / Purpose |
|---|---|---|---|
| `--bg` | `#f6f8fa` | `#0d1117` | Canvas and page background |
| `--panel` | `#ffffff` | `#161b22` | Cards, drawer, top header, surfaces |
| `--panel2` | `#f6f8fa` | `#0d1117` | Secondary surface, subtle contrast, table header |
| `--fg` | `#1f2328` | `#e6edf3` | Primary text and foreground elements |
| `--muted` | `#59636e` | `#9198a1` | Secondary text, captions, inactive icons |
| `--edge` | `#d0d7de` | `#30363d` | Element borders, tool dividers, card outlines |
| `--rule` | `#d8dee4` | `#2b323a` | Dividers, grid separators, table borders |
| `--accent` | `#0969da` | `#4493f8` | Primary brand accent, selected state, hot trails |
| `--accent-solid` | `#0969da` | `#1f6feb` | Solid button background, active tab pill |
| `--ok` | `#1a7f37` | `#3fb950` | Healthy, passed, on-time indicators |
| `--warn` | `#9a6700` | `#d29922` | Warning, degraded, late indicators |
| `--crit` | `#cf222e` | `#f85149` | Critical failure, breach, error indicators |
| `--up` | `#0a7ea4` | `#6fcbe6` | Upstream relation count and badge color |
| `--down` | `#8250df` | `#d0a0ee` | Downstream relation count and notes marker |
| `--glow` | `rgba(9,105,218,.22)` | `rgba(68,147,248,.35)` | Accent halo for selection, hover, and canvas focus |
| `--shadow` | `0 1px 0 rgba(31,35,40,.04), 0 6px 18px rgba(31,35,40,.08)` | `0 1px 0 rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.45)` | Elevated card and modal elevation shadow |
| `--grid` | `rgba(31,35,40,.035)` | `rgba(255,255,255,.04)` | Viewport grid pattern dots and lines |
| `--ok-bg` | `rgba(26,127,55,.10)` | `rgba(63,185,80,.12)` | Subtle tinted background for healthy states |
| `--warn-bg` | `rgba(154,103,0,.10)` | `rgba(210,153,34,.14)` | Subtle tinted background for warning states |
| `--crit-bg` | `rgba(207,34,46,.08)` | `rgba(248,81,73,.12)` | Subtle tinted background for critical states |
| `--info-bg` | `rgba(9,105,218,.10)` | `rgba(68,147,248,.14)` | Subtle tinted background for informational badges |
| `--mono` | `"IBM Plex Mono", ui-monospace, ...` | Same | Monospace font family for metrics, counters, and code |

---

## 2. Typography scale

Flow-studio uses system sans-serif (`Inter, "Segoe UI", system-ui, -apple-system, sans-serif`) for readable text and `--mono` for tabular numerals and technical metadata.

| Role | Size | Weight | Line height | Letter spacing | Font family |
|---|---|---|---|---|---|
| Page title (`h1`) | 20px | 700 | 1.2 | normal | Sans-serif |
| KPI / Tile numbers (`.tn`, `.cn`) | 20px | 600 | 1.1 | tabular-nums | Sans-serif |
| Inspector node title (`.nname`) | 15px | 600 | 1.25 | normal | Sans-serif |
| Drawer heading (`#drawer h2`) | 15px | 700 | 1.3 | normal | Sans-serif |
| Body / Default | 14px | 400 | 1.45 | normal | Sans-serif |
| Card title (`.node .t`) | 13px | 600 | 1.25 | normal | Sans-serif |
| Lane label (`.bandlabel b`) | 13px | 700 | 1.2 | normal | Sans-serif |
| Card subtitle / state (`.node .s`) | 12px | 400 | 1.3 | normal | Sans-serif |
| Help text / Footer | 12px | 400 | 1.4 | normal | Sans-serif |
| Column header (`#cols .hd`) | 10.5px | 700 | 1.2 | 0.08em (caps) | Sans-serif |
| Phase pill (`#cols .ph`) | 10px | 700 | 1.2 | 0.14em (caps) | Sans-serif |
| Evidence / Badges (`.ev`, `.pill`) | 9.5px to 10.5px | 700 | 1.2 | 0.03em (caps) | Sans-serif |
| Metric badges & code (`.mono`, `code`) | 11px to 11.5px | 500 | 1.2 | normal | Monospace |

---

## 3. Spacing scale

Layout elements follow a strict 4px grid rhythm:

| Scale | Value | Typical usage |
|---|---|---|
| 2xs | 2px to 4px | Inline icon gaps, badge vertical padding, bottom border highlights |
| xs | 4px to 7px | Button vertical padding (`4px 11px`), card vertical padding (`5px 10px 7px`), playbar gaps (`7px`) |
| sm | 8px to 10px | Card horizontal padding (`10px`), toolbar item gaps, summary grid gaps |
| md | 12px to 16px | Page padding (`12px 14px 20px`), header gaps, inspector body padding |
| lg | 20px to 28px | Section margins, top header padding, grid line pitch (28px canvas grid) |
| xl | 32px to 44px | Column header heights (44px), tool button dimensions (34px x 32px) |

---

## 4. Border radius and shadow tiers

### Border radius
- **Sharp (0px):** Segmented buttons inside groups, summary tiles inside strips, tools.
- **Small (6px):** Buttons, search inputs, dropdowns, segmented group wrappers.
- **Medium (8px):** Node cards (`.node`).
- **Pill (9px to 10px):** Edge labels (`.elabel`), lane bands (`.band` radius 10px).
- **Large (12px):** Workspace container (`.workspace`).
- **Circular (50%):** Markers, status dots, tokens, and avatar chips.

### Shadow tiers
- **Subtle border shadow (`var(--shadow)`):** `0 1px 0 rgba(31,35,40,.04), 0 6px 18px rgba(31,35,40,.08)` (Light) / `0 1px 0 rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.45)` (Dark).
- **Interactive hover:** `box-shadow: 0 0 0 3px var(--glow), var(--shadow)`.
- **Slide-in drawer elevation:** `box-shadow: -14px 0 34px rgba(0,0,0,.16), -1px 0 0 var(--glow)`.
- **Marker pulse halo:** `box-shadow: 0 0 0 3px rgba(130,80,223,.3)`.

---

## 5. Glow tiers

Glows communicate focus, connection, and selection:
1. **Normal:** `box-shadow: 0 0 14px -4px color-mix(in srgb, <tone> 55%, transparent)` on healthy or highlighted cards.
2. **Hover:** `box-shadow: 0 0 0 3px var(--glow)` with border color change to `--accent`.
3. **Selected / Lit:** `box-shadow: 0 0 0 2px var(--glow), 0 0 18px var(--glow)` plus animated ripple or trail.

---

## 6. State encoding table

The engine generates CSS from 12 canonical domain states defined in `src/stateCss.ts`:

| State ID | Tone | Border Style | Edge Style | Motion | Bucket | Semantic Meaning |
|---|---|---|---|---|---|---|
| `ok` | `ok` | `solid` | `flow` | `flow` | `good` | Fully healthy, active, operational |
| `healthy` | `ok` | `solid` | `flow` | `flow` | `good` | System running within normal operating SLAs |
| `planned` | `muted` | `dashed` | `dash` | `flow-slow` | `neutral` | Future work or planned integration |
| `in-progress` | `accent` | `solid` | `flow` | `flow` | `neutral` | Actively processing or undergoing update |
| `waiting` | `warn` | `dashed` | `dash-short` | `breathe` | `neutral` | Blocked on upstream dependency or approval |
| `late` | `warn` | `solid` | `flow` | `flow` | `neutral` | Running behind schedule but executing |
| `degraded` | `warn` | `dashed` | `dash` | `breathe` | `neutral` | Performance or capacity reduced |
| `failed` | `crit` | `solid` | `flow` | `flow` | `gap` | Execution halted due to fatal defect |
| `breached` | `crit` | `solid` | `flow` | `flow` | `gap` | SLA threshold crossed |
| `blocked` | `crit` | `dashed` | `dot` | `none` | `gap` | Cannot proceed due to hard impediment |
| `unknown` | `warn` | `dotted` | `dot` | `breathe` | `gap` | No telemetry or unverified source |
| `skipped` | `muted` | `dotted` | `dot` | `none` | `neutral` | Deliberately omitted execution step |

---

## 7. Motion catalogue

`src/styles.css` defines 12 `@keyframes`; the count treats the three flow dash variants (`flow`, `flowd`, `flowc`) separately. Motion is never decorative; every animation carries status information.

| Animation name | Duration | Easing | Meaning / State Carried |
|---|---|---|---|
| `beat` | 2.6s | ease (default), infinite | Live indicator pulse on the header brand dot. Indicates the engine session is active. |
| `fadein` | 0.6s / 1s (0.5s delay) | ease (default) | Lane bands and the edge layer fade in during initial canvas load. |
| `rise` | 0.5s / 0.55s / 1.2s | ease (default) / ease-out | Cards, tiles and summary cells enter with subtle upward movement (`translateY(8px)` to `none`); `1.2s` marks a node added by a live update. |
| `flow` | 3s or 7s | linear infinite | Dash-offset marching on links whose state has `edge: "flow"` (`3s` with `motion: "flow"`, `7s` with `motion: "flow-slow"`). Indicates active data transit. |
| `flowd` | 3s or 7s | linear infinite | Same marching for `edge: "dash"` links. |
| `flowc` | 3s or 7s | linear infinite | Same marching for `edge: "dash-short"` links. |
| `flowhot` | 0.9s | linear infinite | Faster marching on highlighted (hot) edges: search trails, relations, playback. |
| `selpulse` | 2.4s / 1.8s | ease-out infinite | Expanding glowing ring around a selected card (`2.4s`) or the active playback node (`1.8s`). |
| `breathe` | 3.2s | ease-in-out infinite | Soft pulsing box-shadow on warning or waiting nodes (`color-mix` with `--warn` or the state tone). |
| `failflash` | 0.9s | ease-out 1 | Red box-shadow burst indicating SLA breach or what-if blast-radius failure. |
| `newring` | 1.2s / 1.8s | ease-out 1 | Accent ring on a node changed by a live update (`1.2s`) or newly appeared in a view (`1.8s`). |
| `ring` | - | - | Defined but referenced by no rule today; reserved. |

---

## 8. Reduced motion fallback rules

Accessibility rules respect user OS preferences:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation: none !important;
    transition: none !important;
  }
  path.edge.hot {
    stroke-dasharray: none;
  }
}
```

- When reduced motion is active, token animations are immediate without transitions.
- Selection rings remain solid outlines without pulsating box-shadows.
- Links show solid or static dashed strokes without moving dashes.

---

## 9. Dark theme strategy

1. The page listens to system preference: `@media (prefers-color-scheme: dark)` applies dark tokens to `:root:not([data-theme="light"])`.
2. Manual override is supported via the `data-theme="dark"` attribute set on `<html>` or `:root`.
3. The theme toggle button switches between light and dark without page reload.
4. Colors do not invert naively; backgrounds use `#0d1117`, card panels use `#161b22`, borders use `#30363d`, and semantic colors (ok, warn, crit) use high-contrast luminance tuned for dark backgrounds.
