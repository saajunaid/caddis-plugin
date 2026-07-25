---
name: warm-editorial-ui
description: Apply the "Warm Editorial Refinement" design system — a sophisticated, executive-grade aesthetic with warm cream surfaces (light mode) and warm charcoal surfaces (dark mode), Bahnschrift + Plus Jakarta Sans typography, generous rounded corners, multi-layer shadows, and a warm neutral palette. Supports both light and dark themes via CSS custom properties and the `.dark` class. Use this skill whenever the user wants to build an app, dashboard, component, or web UI using the abc-project visual style. Trigger on phrases like "use our design system", "apply our template", "make it look like abc-project", "use the warm editorial style", "use our brand template", "add dark mode", or any request to build a new tool/app/dashboard for XYZ Brand or similar contexts. This is the canonical design template for all new frontend builds.
---

# Warm Editorial Refinement — Design System

A premium, editorial-grade UI template built for data-rich internal tools. Combines the warmth of analogue design with the precision of modern SaaS.

**Canonical reference apps:** `scratch/mockups/ceo-dashboard-mockup.html` _(executive-reviewed baseline)_

---

## Design Philosophy

> Warm surfaces. Editorial type. Intentional depth. Not corporate grey — warm cream.

This system was designed for **XYZ Brand internal tools** but is brand-agnostic at the token level. It avoids cold grey SaaS aesthetics and instead uses warm-toned surfaces, editorial typography, and refined component geometry.

---

## Design Tokens

Always define these CSS custom properties in `:root`:

```css
:root {
  /* Brand Accent — replace with your brand color */
  --brand:          #E10A0A;
  --brand-dark:     #C00909;
  --brand-soft:     #FEF2F2;
  --brand-tint:     rgba(225,10,10,0.08);

  /* Warm Surfaces — NOT cold grey */
  --bg:             #F5F3F0;   /* page background */
  --surface:        #FFFFFF;   /* cards, panels */
  --surface-2:      #F9F8F6;   /* subtle inset, inputs */
  --surface-3:      #F0EDE8;   /* deeper inset, table rows */
  --surface-hover:  #EFEDE9;   /* hover states */

  /* Warm Borders */
  --border:         #E5E2DC;
  --border-strong:  #CCC9C2;

  /* Warm Ink (text) — slightly brown-tinged, never cold */
  --ink-1:          #1A1816;   /* primary text */
  --ink-2:          #3D3A36;   /* secondary text */
  --ink-3:          #6B6760;   /* tertiary text */
  --ink-4:          #9C9890;   /* muted/placeholder */

  /* Status Palette */
  --green:          #16A34A;
  --green-soft:     #F0FDF4;
  --green-tint:     rgba(22,163,74,0.12);
  --green-border:   #A7F3D0;

  --amber:          #D97706;
  --amber-soft:     #FFFBEB;

  --red:            #DC2626;
  --red-soft:       #FEF2F2;
  --red-border:     #FCA5A5;

  --blue:           #2563EB;
  --blue-soft:      #EFF6FF;
  --blue-border:    #BFDBFE;

  /* Radius Scale — generous, not tight */
  --r-xs:           4px;
  --r-sm:           8px;
  --r-md:           12px;
  --r-lg:           16px;    /* standard cards */
  --r-xl:           22px;    /* panels, large containers */

  /* Shadows — multi-layer, warm-tinted (warm brown base, not cold black) */
  --shadow-xs:      0 1px 2px rgba(26,24,22,0.04);
  --shadow-sm:      0 1px 3px rgba(26,24,22,0.06), 0 1px 2px rgba(26,24,22,0.04);
  --shadow-md:      0 4px 12px rgba(26,24,22,0.08), 0 2px 4px rgba(26,24,22,0.04);
  --shadow-lg:      0 10px 30px rgba(26,24,22,0.12), 0 4px 8px rgba(26,24,22,0.06);

  /* Typography */
  /* NOTE: --font-heading uses Bahnschrift — a Windows 10+ system font.
     Falls back to Franklin Gothic Medium on macOS/Linux. Correct for Windows-hosted tools. */
  --font-sans:      'Plus Jakarta Sans', system-ui, sans-serif;
  --font-heading:   'Bahnschrift', 'Franklin Gothic Medium', 'Arial Narrow', sans-serif;
  --font-mono:      'JetBrains Mono', monospace;
}
```

### Google Fonts Import
```html
<!-- Plus Jakarta Sans (body) + JetBrains Mono (data). Bahnschrift is Windows system — no CDN needed. -->
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
```

---

## Typography Rules

### Default Pairing (active)

| Role | Font | Weight | Usage |
|------|------|--------|-------|
| UI body | Plus Jakarta Sans | 300–700 | Labels, body text, navigation |
| Numbers/data | JetBrains Mono | 400–600 | KPI values, counts, codes |
| Section headings | Bahnschrift (system) | 700–800 | KPI values, card titles, brand name |

### Font Pairing Selection (agent decision logic)

**Before generating any UI, resolve the font pairing using this priority:**

1. **Check `project-config.md`** — if the project's profile has a Design System section with declared fonts, use those. Done.
2. **No project-config?** — Present the pairing table below to the user and ask: *"Which font pairing would you like for this project? (A–F, or describe your preference)"*. Wait for the user to choose before generating UI.
3. **User says "you pick" or doesn't care** — Use pairing **E (Sora + Nunito Sans)** as the default.

> **Never silently pick a non-default pairing.** The user must explicitly opt in to A–E.

### Alternative Font Pairings

All are Google Fonts unless marked (system).

| Pairing | Heading | Body | Character |
|---------|---------|------|-----------|
| **A — Geometric Precision** | Geist (system/self-host) | Plus Jakarta Sans | Clean SaaS feel, Linear/Vercel aesthetic |
| **B — Neo-Industrial** | Clash Display (self-host) | General Sans | Bold brutalist contrast, strong visual hierarchy |
| **C — Refined Corporate** | Manrope | Source Sans 3 | Polished enterprise, Microsoft/Notion vibe |
| **D — Editorial Luxury** | Fraunces | Outfit | Warm serif contrast, premium editorial weight |
| **E — Modern Humanist** | Sora | Nunito Sans | Approachable geometric, health/fintech feel |
| **F — Condensed Executive** | Bahnschrift (system) | Plus Jakarta Sans | *(current default)* — dense KPI headers |

To switch, update these tokens in `:root`:
```css
/* Example: Pairing D — Editorial Luxury */
--font-heading: 'Fraunces', Georgia, serif;
--font-sans:    'Outfit', system-ui, sans-serif;
```
And update the Google Fonts import:
```html
<link href="https://fonts.googleapis.com/css2?family=Fraunces:wght@600;700;800&family=Outfit:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
```

**Never use:** Inter, DM Sans, Syne, Roboto, Space Grotesk as primary fonts.

---

## Layout Architecture

### App Shell with Left Sidebar
```
┌──────────────────────────────────────────────────────┐
│  Sidebar (236px)  │  Top Filter Bar (52px)            │
│                   ├──────────────────────────────────┤
│  Brand Logo       │  Sub-tab Bar (40px)               │
│  Nav Groups       ├──────────────────────────────────┤
│  Footer / User    │  Page Content (scrollable)        │
└──────────────────────────────────────────────────────┘
```

### Sidebar Pattern
```css
.sidebar {
  width: 236px;
  background: var(--surface);
  border-right: 1px solid var(--border);
}

/* Brand lockup */
.brand-logo {
  width: 36px; height: 36px;
  background: var(--brand);
  border-radius: 10px;
  box-shadow: 0 3px 10px rgba(225,10,10,0.3);
  font-family: var(--font-heading);
  font-size: 14px; font-weight: 800;
}

/* Active nav item */
.nav-item.active {
  background: var(--brand-soft);
  color: var(--brand);
  font-weight: 600;
}
.nav-item.active::before {
  content: '';
  position: absolute; left: 0;
  top: 5px; bottom: 5px; width: 3px;
  background: var(--brand);
  border-radius: 0 3px 3px 0;
}
```

---

## Component Patterns

### KPI Cards
```css
.kpi-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);      /* 16px */
  padding: 14px 16px;
  box-shadow: var(--shadow-sm);
  transition: box-shadow 0.15s, transform 0.15s;
}
.kpi-card:hover { box-shadow: var(--shadow-md); transform: translateY(-1px); }
.kpi-card::before {
  /* colored top bar */
  content: ''; position: absolute; top: 0; left: 0; right: 0;
  height: 3px; border-radius: var(--r-lg) var(--r-lg) 0 0;
  background: var(--kpi-color, var(--border));
}
/* KPI value uses Bahnschrift for condensed executive punch */
.kpi-value {
  font-family: var(--font-heading);
  font-size: 30px; font-weight: 700; letter-spacing: -1px;
}
```

### Filter Pills (Topbar)
```css
.fchip {
  border: 1.5px solid var(--border);
  border-radius: 20px;
  padding: 4px 11px;
  font-size: 12px; font-weight: 500;
  background: var(--surface);
  transition: all 0.12s;
}
.fchip:hover  { border-color: var(--brand); color: var(--brand); background: var(--brand-soft); }
.fchip.active { border-color: var(--brand); color: var(--brand); background: var(--brand-soft); }
```

### Buttons
```css
/* Primary */
.btn-primary {
  height: 32px; padding: 0 16px;
  background: var(--brand); color: white; border: none;
  border-radius: var(--r-sm);
  font-family: var(--font-heading); font-size: 12.5px; font-weight: 700;
  box-shadow: 0 2px 8px rgba(225,10,10,0.2);
  transition: all 0.12s;
}
.btn-primary:hover { transform: translateY(-1px); box-shadow: 0 4px 14px rgba(225,10,10,0.3); }

/* Ghost */
.btn-ghost {
  height: 32px; padding: 0 12px;
  border: 1.5px solid var(--border); border-radius: var(--r-sm);
  background: var(--surface); color: var(--ink-3);
  font-family: var(--font-sans); font-weight: 500;
}
.btn-ghost:hover { background: var(--surface-2); color: var(--ink-1); }
```

### Status Badges / Pills
```css
.badge { padding: 2px 7px; border-radius: 20px; font-size: 10px; font-weight: 700; }
.badge.success { background: var(--green-soft); color: var(--green); border: 1px solid var(--green-tint); }
.badge.warning { background: var(--amber-soft); color: var(--amber); }
.badge.danger  { background: var(--red-soft);   color: var(--red);   border: 1px solid var(--red-border); }
```

### Chart Cards
```css
.chart-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);     /* 16px */
  padding: 18px 20px;
  box-shadow: var(--shadow-sm);
}
/* Card title uses Bahnschrift */
.chart-title { font-family: var(--font-heading); font-size: 13.5px; font-weight: 700; letter-spacing: -0.2px; }
.chart-sub   { font-size: 11px; color: var(--ink-4); }
```

### Section Labels
```css
.section-title {
  font-size: 10px; font-weight: 700;
  letter-spacing: 1.5px; text-transform: uppercase;
  color: var(--ink-4);
  font-family: var(--font-sans);
}
```

---

## Alert / Highlight Cards
```css
/* Warning alert */
.alert-card {
  background: linear-gradient(135deg, #FFF8F5 0%, #FFF2EE 100%);
  border: 1.5px solid #FCCAB4;
  border-radius: var(--r-lg);
}
/* Success callout */
.callout-green {
  background: var(--green-soft);
  border: 1px solid var(--green-border);
  border-radius: var(--r-md);
  padding: 10px 13px;
}
/* Info callout */
.callout-blue {
  background: var(--blue-soft);
  border: 1px solid var(--blue-border);
  border-radius: var(--r-md);
  padding: 10px 13px;
}
```

---

## React Component Structure

When building React components with this design system:

```tsx
// Design tokens map directly to Tailwind-like CSS vars
// Use inline styles or a theme provider pattern:

const theme = {
  surface: 'var(--surface)',
  surface2: 'var(--surface-2)',
  border: 'var(--border)',
  ink1: 'var(--ink-1)',
  ink4: 'var(--ink-4)',
  brand: 'var(--brand)',
  brandSoft: 'var(--brand-soft)',
  fontHeading: 'var(--font-heading)',
  fontMono: 'var(--font-mono)',
  // Radius
  rLg: 'var(--r-lg)',
  rXl: 'var(--r-xl)',
  // Shadows
  shadowSm: 'var(--shadow-sm)',
  shadowMd: 'var(--shadow-md)',
};

// KPI Card example
function KpiCard({ label, value, delta, color, trend }) {
  return (
    <div style={{
      background: 'var(--surface)',
      border: '1px solid var(--border)',
      borderRadius: 'var(--r-lg)',
      padding: '14px 16px',
      boxShadow: 'var(--shadow-sm)',
      position: 'relative',
      overflow: 'hidden',
    }}>
      {/* Colored top bar */}
      <div style={{ position:'absolute', top:0, left:0, right:0, height:'3px', background:color }} />
      <p style={{ fontSize:'10px', fontWeight:700, letterSpacing:'1.2px', textTransform:'uppercase', color:'var(--ink-4)', marginBottom:'8px' }}>
        {label}
      </p>
      <p style={{ fontFamily:'var(--font-heading)', fontSize:'30px', fontWeight:700, letterSpacing:'-1px', color }}>
        {value}
      </p>
    </div>
  );
}
```

---

## Grid Layouts

```css
/* KPI row — 6 columns */
.kpi-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; }

/* 2-column charts */
.charts-2col { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }

/* 3-column charts */
.charts-3col { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 14px; }
```

---

## Sidebar Nav Badge Colors

```css
.nav-badge.red   { background: var(--red-soft);   color: var(--red);   border: 1px solid var(--red-border); }
.nav-badge.green { background: var(--green-soft);  color: var(--green); }
.nav-badge.grey  { background: var(--surface-3);   color: var(--ink-4); }
```

---

## Dropdown / Select Panel Styling

Dropdowns must have a smooth, modern appearance — never blocky or browser-default.

Use these control-specific tokens (add to `:root` alongside the main token set):

```css
:root {
  --control-bg:           var(--surface-2);
  --control-bg-hover:     var(--surface-hover);
  --control-bg-active:    var(--surface-3);
  --control-border:       var(--border);
  --control-border-strong:var(--border-strong);
  --control-ring:         var(--brand);
  --shadow-control:       var(--shadow-xs);
  --shadow-control-strong:var(--shadow-sm);
  --radius-control:       var(--r-sm);   /* 8px */
}
```

```css
.select-panel {
  background: var(--control-bg);
  border: 1.5px solid var(--control-border);
  border-radius: var(--radius-control);
  box-shadow: var(--shadow-control-strong);
  padding: 6px 0;
  min-width: 180px;
  transition: box-shadow 0.18s, border-color 0.18s;
}
.select-panel:focus-within {
  outline: none;
  box-shadow: 0 0 0 2px var(--control-ring), var(--shadow-control-strong);
  border-color: var(--control-border-strong);
}
.select-panel__option {
  padding: 8px 18px;
  border-radius: 7px;
  cursor: pointer;
  transition: background 0.14s;
}
.select-panel__option:hover { background: var(--control-bg-hover); }
```

- For shadcn/ui `<Select>`: override `SelectContent` and `SelectItem` with these tokens
- Never use native browser `<select>` appearance without overriding all visual states
- Test in both light and dark mode — tokens swap automatically via `.dark`

---

## Appearance Settings Rules

These UX rules apply to all apps using this design system:

- **Theme / accent controls belong in the Settings tab only.** Do not place color or theme pickers in the main nav, topbar, or sidebar.
- **The dark/light mode toggle must always be rendered as an icon (sun/moon), never as text.**

```tsx
// Correct: icon-only toggle in Settings tab
<button className="theme-toggle" aria-label="Switch theme" onClick={toggle}>
  {dark ? <MoonIcon /> : <SunIcon />}
</button>
```

- Place in the Settings tab, not in the topbar or sidebar footer
- Use `aria-label` for screen reader accessibility

---

## What Makes This Style Distinctive

1. **Warm vs cold**: Surfaces are `#F8F7F5` and `#F2F0ED` — cream/linen, not cold `#F9FAFB`
2. **Ink tones**: Text is `#1A1816` (warm black) not `#111827` (cold)
3. **Borders**: `#E5E2DC` (warm beige) not `#E5E7EB` (cool grey)
4. **Typography**: Bahnschrift headings give condensed executive weight; Plus Jakarta Sans body is premium and distinctive — not generic Inter/Roboto
5. **Radius**: 16px cards, 22px panels — generous, contemporary
6. **Shadows**: Always multi-layer (`0 1px 3px ... 0 1px 2px ...`) for depth

---

## Don'ts

- ❌ No `Inter`, `DM Sans`, `Syne`, `Roboto`, or `Space Grotesk`
- ❌ No cold grey surfaces (`#F9FAFB`, `#F3F4F6`)
- ❌ No generic SaaS blue (`#3B82F6`) as primary
- ❌ No glass morphism effects
- ❌ No tight corners (avoid radius < 8px on cards)
- ❌ No single-layer flat shadows
- ❌ No uppercase text in `var(--font-heading)` for body copy

---

## Adapting for Different Brands

Change only the brand token and optionally the accent palette:

```css
/* e.g. for a teal-branded product */
:root {
  --brand:       #0891B2;
  --brand-dark:  #0E7490;
  --brand-soft:  #ECFEFF;
  --brand-tint:  rgba(8,145,178,0.08);
}
/* All other tokens remain the same */
```

The warm surface, ink, and border tokens are **brand-neutral** — they work for any brand colour.

---

## Dark Mode — Warm Soft Dark

A warm, editorial-grade dark theme inspired by GitHub's Dark Dimmed aesthetic but with warm brown-grey tones instead of cold blue-grey. **Not pure black** — surfaces are tinted warm charcoal, like aged paper in low light.

### Design Philosophy (Dark)

> Soft dark. Warm charcoal. Never cold, never pure black.

- Backgrounds use warm near-black (`#1A1917`) — NOT cold `#0a0a0a` or blue-tinted `#1C2128`
- Ink inverts to warm off-whites (`#E8E5DF`) — NOT stark `#FFFFFF` or cold `#C9D1D9`
- Status colors brighten slightly for readability on dark surfaces
- Shadows shift to `rgba(0,0,0,...)` (higher opacity) because dark surfaces absorb light
- Brand accent brightens slightly to maintain vibrancy

### Dark Mode Tokens

Apply under `.dark` (or `[data-theme="dark"]` for explicit toggling):

```css
.dark {
  /* Brand Accent — slightly brighter for dark backgrounds */
  --brand:          #F52D2D;
  --brand-dark:     #E41B1B;
  --brand-soft:     rgba(245,45,45,0.12);
  --brand-tint:     rgba(245,45,45,0.10);

  /* Warm Soft Dark Surfaces — charcoal, not cold */
  --bg:             #1A1917;   /* page background — warm near-black */
  --surface:        #242320;   /* cards, panels — warm dark paper */
  --surface-2:      #1E1D1B;   /* subtle inset, inputs — darker than surface */
  --surface-3:      #2A2926;   /* deeper inset, table rows */
  --surface-hover:  #302E2A;   /* hover states */

  /* Warm Dark Borders */
  --border:         #3A3834;
  --border-strong:  #4D4A44;

  /* Warm Ink (inverted) — off-white with warm tint */
  --ink-1:          #E8E5DF;   /* primary text — warm off-white */
  --ink-2:          #C5C1B8;   /* secondary text */
  --ink-3:          #A8A49C;   /* tertiary text — lifted for readability on dark surfaces */
  --ink-4:          #8A8680;   /* muted/placeholder — 4.5:1 on card surface (was #706C64, too dark) */

  /* Status Palette — brightened for dark backgrounds */
  --green:          #3FB950;
  --green-soft:     rgba(63,185,80,0.12);
  --green-tint:     rgba(63,185,80,0.15);
  --green-border:   rgba(63,185,80,0.25);

  --amber:          #E3B341;
  --amber-soft:     rgba(227,179,65,0.12);

  --red:            #F85149;
  --red-soft:       rgba(248,81,73,0.12);
  --red-border:     rgba(248,81,73,0.25);

  --blue:           #58A6FF;
  --blue-soft:      rgba(88,166,255,0.12);
  --blue-border:    rgba(88,166,255,0.25);

  /* Shadows — darker, higher opacity (dark surfaces absorb light) */
  --shadow-xs:      0 1px 2px rgba(0,0,0,0.24);
  --shadow-sm:      0 1px 3px rgba(0,0,0,0.32), 0 1px 2px rgba(0,0,0,0.24);
  --shadow-md:      0 4px 12px rgba(0,0,0,0.40), 0 2px 4px rgba(0,0,0,0.24);
  --shadow-lg:      0 10px 30px rgba(0,0,0,0.48), 0 4px 8px rgba(0,0,0,0.32);

  /* Typography — unchanged (fonts don't change between modes) */
  /* --font-sans, --font-heading, --font-mono remain the same */

  /* Radius — unchanged */
  /* --r-xs through --r-xl remain the same */
}
```

### Theme Toggle Setup

Use the `.dark` class on `<html>` or a container element. shadcn's `next-themes` or a simple toggle works:

```tsx
// Minimal dark mode toggle (Vite / React)
import { useEffect, useState } from 'react';

function useTheme() {
  const [dark, setDark] = useState(() =>
    window.matchMedia('(prefers-color-scheme: dark)').matches
  );

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
  }, [dark]);

  return { dark, toggle: () => setDark(d => !d) };
}
```

```html
<!-- The .dark class activates the override tokens -->
<html class="dark">
  <!-- All var(--surface), var(--ink-1), etc. now resolve to dark values -->
</html>
```

### Tailwind CSS Integration

Map tokens to Tailwind in `tailwind.config.js`:

```js
// tailwind.config.js (extends existing warm-editorial setup)
module.exports = {
  darkMode: 'class',  // Use .dark class, not media query
  theme: {
    extend: {
      colors: {
        background: 'var(--bg)',
        surface:    'var(--surface)',
        'surface-2': 'var(--surface-2)',
        'surface-3': 'var(--surface-3)',
        border:     'var(--border)',
        'ink-1':    'var(--ink-1)',
        'ink-2':    'var(--ink-2)',
        'ink-3':    'var(--ink-3)',
        'ink-4':    'var(--ink-4)',
        brand:      'var(--brand)',
        'brand-soft': 'var(--brand-soft)',
      },
    },
  },
};
```

Components then use `bg-surface`, `text-ink-1`, `border-border` — **no `dark:` prefix needed**. The CSS variables swap automatically when `.dark` is applied.

### Dark Mode Component Adaptations

#### Alert / Highlight Cards

```css
.dark .alert-card {
  background: linear-gradient(135deg, rgba(248,81,73,0.08) 0%, rgba(248,81,73,0.04) 100%);
  border-color: rgba(248,81,73,0.20);
}
.dark .callout-green {
  background: var(--green-soft);
  border-color: var(--green-border);
}
.dark .callout-blue {
  background: var(--blue-soft);
  border-color: var(--blue-border);
}
```

#### Sidebar (Dark)

```css
.dark .sidebar {
  background: var(--surface);       /* #242320 — warm dark */
  border-right-color: var(--border); /* #3A3834 */
}
.dark .nav-item.active {
  background: var(--brand-soft);    /* rgba tint, not opaque */
  color: var(--brand);              /* #F52D2D — brightened */
}
.dark .brand-logo {
  box-shadow: 0 3px 10px rgba(245,45,45,0.35);  /* slightly more glow on dark */
}
```

#### KPI Cards (Dark)

No CSS changes needed — KPI cards already use `var(--surface)`, `var(--border)`, `var(--shadow-sm)` which swap automatically. The colored top bar uses `var(--kpi-color)` which is set per-card (brand/green/amber/red).

#### Charts (Dark)

When using Recharts, Plotly, or similar:

```tsx
// Chart colors adapt to theme via CSS variables
const chartConfig = {
  backgroundColor: 'var(--surface)',
  gridColor: 'var(--border)',
  textColor: 'var(--ink-3)',
  axisColor: 'var(--ink-4)',
};

// For Plotly specifically:
const plotlyLayout = {
  paper_bgcolor: 'transparent',
  plot_bgcolor: 'transparent',
  font: { color: 'var(--ink-2)' },
  xaxis: { gridcolor: 'var(--border)', zerolinecolor: 'var(--border-strong)' },
  yaxis: { gridcolor: 'var(--border)', zerolinecolor: 'var(--border-strong)' },
};
```

### Dark Mode vs Light Mode — Quick Reference

| Token | Light | Dark | Notes |
|-------|-------|------|-------|
| `--bg` | `#F5F3F0` cream | `#1A1917` warm near-black | Both warm-tinted |
| `--surface` | `#FFFFFF` white | `#242320` warm charcoal | Cards, panels |
| `--surface-2` | `#F9F8F6` subtle | `#1E1D1B` recessed | Inputs, insets |
| `--border` | `#E5E2DC` warm beige | `#3A3834` warm dark | Both avoid cold grey |
| `--ink-1` | `#1A1816` warm black | `#E8E5DF` warm off-white | Primary text |
| `--ink-3` | `#6B6760` warm grey | `#A8A49C` lighter warm grey | Tertiary text |
| `--ink-4` | `#9C9890` muted | `#8A8680` muted (lifted) | Placeholder/section labels |
| `--brand` | `#E10A0A` | `#F52D2D` | Brightened for dark |
| `--green` | `#16A34A` | `#3FB950` | Brightened for dark |
| `--red` | `#DC2626` | `#F85149` | Brightened for dark |
| `--shadow-sm` | `rgba(26,24,22,0.06)` | `rgba(0,0,0,0.32)` | Higher opacity on dark |

### What Makes This Dark Mode Distinctive

1. **Warm charcoal, not cold**: Backgrounds are `#1A1917` (brown-black), not `#0D1117` (GitHub blue-black) or `#0a0a0a` (pure black)
2. **Soft, not harsh**: Surfaces at `#242320` are visibly lighter than the `#1A1917` page — creating depth without being stark
3. **Status colors breathe**: Green/red/amber/blue are ~15% brighter than their light-mode counterparts — they pop without screaming
4. **Shadows still work**: Unlike many dark themes where shadows vanish, the `rgba(0,0,0,0.3-0.5)` range creates visible but subtle elevation
5. **Brand stays warm**: The red accent at `#F52D2D` glows slightly warmer, working with the warm charcoal surface instead of fighting it
6. **Muted text stays readable**: `--ink-4` at `#8A8680` achieves 4.6:1 contrast on card surfaces — grey but never invisible

### Don'ts (Dark Mode)

- ❌ No pure black backgrounds (`#000000`, `#0a0a0a`)
- ❌ No cold blue-grey (`#1C2128`, `#22272E`) — use warm tones
- ❌ No stark white text (`#FFFFFF`) — use warm off-white `#E8E5DF`
- ❌ No identical status colors as light mode — brighten them for dark backgrounds
- ❌ No `opacity: 0.5` for muting — use dedicated muted tokens instead
- ❌ No light-mode shadow values — dark surfaces need higher-opacity shadows
