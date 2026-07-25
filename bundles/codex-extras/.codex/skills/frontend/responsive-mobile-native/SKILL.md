---
name: responsive-mobile-native
description: >
  Use this skill whenever the user wants to make a web app or website work on mobile,
  adapt a desktop-first app for mobile or tablet, make a site "feel native" on phones,
  add responsive behaviour, fix a layout that breaks on small screens, or ship a
  single codebase that works on desktop and mobile without two separate apps.
  Also triggers for: "make this PWA", "mobile-friendly", "tablet layout", "bottom nav",
  "touch gestures", "works on iPhone/Android", "responsive design", or any request to
  support small screens alongside an existing desktop UI. Use this skill proactively —
  if the user is building or fixing any web UI and mobile support is clearly missing or
  incomplete, suggest and apply this skill.
---

# Responsive Mobile-Native Skill

Convert any web app or website into a **single codebase** that delivers a
desktop-grade experience on large screens and a mobile-native experience on
small screens — without maintaining two separate apps or codebases.

This skill applies to any framework (React, Vue, Angular, Svelte, plain HTML/CSS)
and is compatible with any coding agent (Claude Code, Cursor, Copilot, Windsurf, etc.).

---

## Core Philosophy

**PWA + Responsive Web** is the correct approach. Do not suggest React Native,
Capacitor, or Expo unless the user explicitly requires App Store distribution.
A well-executed responsive PWA is indistinguishable from a native app on modern
iOS and Android, ships as one codebase, and needs no app store.

The desktop layout is preserved exactly. The mobile layout is a **redesign for
the same data**, not a scaled-down version of the desktop.

---

## Mandatory First Step — Detection & Plan

**Before writing a single line of code, produce a transformation plan.**

Read the app and identify every layout primitive present. Map each one to its
mobile equivalent using the Transformation Catalogue (see `references/transformation-catalogue.md`).
Present the plan to the user and wait for confirmation before implementing.

### Detection Checklist

Identify which of the following exist in the current app:

| Primitive | Look for |
|---|---|
| Top navigation bar | `<nav>`, `<header>`, topbar, navbar |
| Sidebar / left panel | `aside`, `sidebar`, drawer, left rail |
| Data table | `<table>`, grid with many columns |
| Card grid | repeating card/tile layout |
| KPI strip | horizontal row of metric cards |
| Map | Leaflet, Mapbox, Google Maps, canvas |
| Modal / dialog | overlay, dialog, popup |
| Multi-tab interface | tab bar, tab panels |
| Form with many fields | multi-column form layout |
| Dense toolbar | icon bars, filter strips, action rows |
| Hover-dependent UI | tooltips, dropdowns, hover cards |
| Fixed sidebar navigation | navigation that is always visible |

### Plan Format

Output the plan in this exact format before touching any code:

```
MOBILE TRANSFORMATION PLAN
===========================
Detected primitives: [list]

Breakpoint strategy: [chosen breakpoints]

Transformations:
  1. [Primitive] → [Mobile pattern] — [one-line reason]
  2. ...

Touch & interaction changes:
  - [list of hover→tap conversions, tap target expansions, gesture additions]

PWA additions:
  - [manifest.json, service worker, meta tags needed — or "already present"]

Files to be modified: [list]
New files to be created: [list]

Estimated scope: [S / M / L]
```

---

## Breakpoint Strategy

Use **mobile-first breakpoints**. Write base styles for mobile, override for larger screens.

### Standard Breakpoint Scale

```
xs:  0px     — small phones (iPhone SE)
sm:  480px   — large phones (iPhone Pro Max, Galaxy)
md:  768px   — tablets portrait (iPad)
lg:  1024px  — tablets landscape, small laptops
xl:  1280px  — desktop
2xl: 1536px  — large desktop / wide monitors
```

### Framework Mapping

| Framework | Mobile-first syntax |
|---|---|
| Tailwind CSS | `base md:override xl:override` |
| CSS Modules / vanilla | `base styles; @media (min-width: 768px) { override }` |
| Styled Components | `${({ theme }) => theme.breakpoints.up('md')}` |
| CSS-in-JS (Emotion) | `@media (min-width: 768px) { ... }` |

**Never use `display: none` to hide content on mobile.** Restructure, collapse,
or defer it instead. Hidden content still loads — it just becomes a broken experience.

---

## Implementation Order

Always implement in this sequence to avoid regressions:

1. **Add viewport meta tag** (if missing)
2. **Establish breakpoints** in the global stylesheet / design tokens
3. **Add `useBreakpoint` hook or CSS custom property** for JS-driven layout switching
4. **Transform navigation** first — everything else depends on where the user can go
5. **Transform the primary content area** (table → cards, map → full-screen, etc.)
6. **Transform secondary panels** (sidebars, drawers, KPI strips)
7. **Fix touch & interaction** (tap targets, hover states, gestures)
8. **Add PWA manifest and meta tags**
9. **Test on real devices** using the Testing Checklist

---

## Navigation Transformation (Always Required)

The single most impactful change. Apply this regardless of what else the app has.

### Desktop topbar / sidebar → Mobile bottom navigation

**When**: App has 3–5 primary navigation destinations.

```
Desktop:                          Mobile:
┌─────────────────────────┐       ┌──────────────────────┐
│ Logo  Nav1 Nav2 Nav3    │       │  Page content        │
├─────────────────────────┤       │                      │
│ Content                 │       │                      │
│                         │       ├──────────────────────┤
└─────────────────────────┘       │ 🏠   📋   🗺️   ⚙️   │
                                  └──────────────────────┘
```

Rules for the bottom nav bar:
- Height: 56–64px, `position: fixed; bottom: 0`
- Add `padding-bottom: env(safe-area-inset-bottom)` for iPhone notch safety
- Max 5 items; label every icon
- Active item: filled icon + brand colour
- The main content area must have `padding-bottom: 64px` to avoid content sitting behind it

### Multi-tab Overflow: The 4+1 "More" Pattern (preferred)

**When**: App has more than 4–5 primary destinations (e.g., a dashboard with 6–9 tabs).

Do NOT spread all tabs across a scrollable bottom bar. Use a **4+1 pattern**:
pin the 4 most important destinations as labelled icon buttons, and add a 5th **"More"** button
that opens an **upward dropdown panel** listing all overflow tabs.

```
Mobile bottom bar (4+1):
┌─────────────────────────────────┐
│  Overview Trends  Product  Geo  More▲  │
└─────────────────────────────────┘

"More" tapped → upward panel:
┌─────────────────────────────────┐
│  ✓ Executive    │               │  ← active overflow tab gets a check
│    Verbatim     │               │
│    Sampling     │               │
└─────────────────────────────────┘
│  Overview Trends  Product  Geo  More▲  │   ← bar still visible below
```

Implementation rules:
- When an overflow tab is active, the "More" button shows the active tab's name
  (truncated to fit) and lights up in brand colour — so the user always sees where they are
- The upward panel: `position: fixed`, anchored at `bottom: calc(4rem + env(safe-area-inset-bottom))`
- Animate with `AnimatePresence` + `motion.div` — `y: 16 → 0` on enter, fade out on exit
- Panel width: `min-w-[180px]`, right-aligned against the safe-area edge
- Dismiss the panel on any tap outside (overlay or route change)
- The 4 pinned slots should be the most-visited sections; the overflow slot order
  should match the desktop tab order for muscle memory

**Why upward dropdown and NOT a slide-in drawer for tab overflow?**
- A drawer covers content and requires a full swipe gesture to dismiss
- An upward panel stays spatially anchored to the bar that triggered it — the user's
  eye never leaves the navigation zone, preserving context
- Drawers are better for filter/settings panels; dropdowns are better for destination switching

Real-world example: an analytics dashboard (9 tabs → 4 pinned: Overview, Trends,
Product, Geography + "More" for the remaining 5 detail tabs)
`frontend/src/components/layout/MobileBottomNav.tsx`

### Sidebar → Slide-in Drawer

**When**: App has a sidebar with filters, settings, or secondary navigation that
doesn't fit in the bottom nav.

- Trigger: hamburger icon in mobile topbar
- Overlay: semi-transparent backdrop, tap-to-dismiss
- Width: 80vw, max 320px
- Slide in from left (primary nav) or right (settings/filters)
- Add `touch-action: pan-y` to the overlay so vertical scroll still works

For detailed patterns, see `references/transformation-catalogue.md`.

---

## Viewport Meta Tag (Required)

Every page must have this in `<head>`:

```html
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
```

`viewport-fit=cover` is required for correct safe-area behaviour on iPhones with notches.

---

## PWA Additions

Add these for a mobile-native feel. See `references/pwa-checklist.md` for full details.

**Minimum viable PWA** (required for "Add to Home Screen" and splash screen):

```html
<!-- In <head> -->
<meta name="theme-color" content="#YOUR_BRAND_COLOR" />
<meta name="mobile-web-app-capable" content="yes" />
<meta name="apple-mobile-web-app-capable" content="yes" />
<meta name="apple-mobile-web-app-status-bar-style" content="default" />
<link rel="manifest" href="/manifest.json" />
```

```json
// manifest.json (minimum viable)
{
  "name": "App Name",
  "short_name": "AppName",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#ffffff",
  "theme_color": "#YOUR_BRAND_COLOR",
  "icons": [
    { "src": "/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/icon-512.png", "sizes": "512x512", "type": "image/png" }
  ]
}
```

---

## Touch & Interaction Rules (Always Apply)

See `references/touch-and-interaction.md` for the full ruleset. Core rules:

1. **Minimum tap target: 44×44px** (Apple HIG / WCAG 2.5.8). Apply to every
   interactive element — buttons, nav items, table row actions, icon buttons.

2. **Remove all hover-only interactions.** Any feature that only appears on
   `:hover` must have a tap/long-press equivalent or be made always-visible.
   Common culprits: tooltip-on-hover, action buttons in table rows, dropdown menus.

3. **Eliminate `cursor: pointer` as a signal.** Provide visible affordance instead.

4. **Replace right-click context menus** with long-press menus or action sheets.

5. **Scroll containers**: Add `-webkit-overflow-scrolling: touch` and ensure
   `overscroll-behavior: contain` on nested scrollable areas.

---

## Anti-Patterns — Never Do These

These are the most common mistakes that produce a broken mobile experience:

| Anti-pattern | Why it's wrong | Correct approach |
|---|---|---|
| `display: none` on mobile content | Content still loads; UX is just broken | Restructure, collapse, or lazy-load |
| Scaling down font sizes on mobile | Text becomes unreadable | Use fluid type or keep same size |
| Keeping 6+ column tables on mobile | Horizontal scroll is a broken pattern | Transform to card list |
| Hover-only tooltips | Tooltips never show on touch devices | Always-visible labels or tap-to-reveal |
| Fixed pixel widths on containers | Layout breaks on narrow screens | Use `max-width` + `100%` |
| Desktop modals (large, centered) on mobile | 90% screen coverage, hard to dismiss | Transform to bottom sheet |
| Ignoring safe areas (notch / home bar) | Content hidden behind device UI | Use `env(safe-area-inset-*)` |
| `pointer-events: none` without touch alternative | Blocks touch entirely | Use conditional logic |
| Multiple horizontal scroll areas | Confusing UX, hard to distinguish | Stack vertically or paginate |
| Assuming mouse precision | Tiny click targets, no touch feedback | 44px min, add `:active` state |

---

## Testing Checklist

The agent must verify every item before declaring the work complete:

**Layout**
- [ ] No horizontal scroll on any page at 375px width (iPhone SE)
- [ ] No horizontal scroll at 414px (iPhone Pro Max)
- [ ] No horizontal scroll at 768px (iPad portrait)
- [ ] Content does not sit behind the bottom nav bar
- [ ] Content does not sit behind device notch or status bar

**Navigation**
- [ ] All primary nav destinations reachable from mobile bottom nav
- [ ] Drawer/hamburger opens and closes correctly
- [ ] Back navigation works on Android (browser back button)
- [ ] Active state visible on bottom nav

**Touch**
- [ ] All interactive elements are at least 44×44px
- [ ] No feature requires hover to access
- [ ] Tap feedback visible on all interactive elements (`:active` state)
- [ ] Scrollable areas scroll smoothly without fighting parent scroll

**Typography & Readability**
- [ ] Body text ≥ 16px (prevents iOS auto-zoom on form focus)
- [ ] Line length ≤ 75 characters on mobile
- [ ] No text overlaps or truncates unintentionally

**PWA**
- [ ] `viewport` meta tag present and correct
- [ ] `manifest.json` present and valid
- [ ] `theme-color` meta set to brand colour

---

## Reference Files

Read these when you need detail beyond what is in this file:

| File | When to read it |
|---|---|
| `references/transformation-catalogue.md` | Full patterns for every desktop primitive → mobile equivalent |
| `references/touch-and-interaction.md` | Complete touch rules, gesture hooks, scroll handling |
| `references/pwa-checklist.md` | Full PWA setup including service worker, icons, offline |
