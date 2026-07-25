# Transformation Catalogue

Complete catalogue of desktop UI primitive → mobile pattern mappings.
For each transformation: what it is, when to apply it, and the pattern to follow.

---

## Table of Contents

1. Data Table → Card List
2. KPI Strip → Horizontal Scroll / Stacked Grid
3. Multi-column Form → Single Column
4. Map → Full-Screen with Floating Controls
5. Modal / Dialog → Bottom Sheet
6. Multi-tab Interface → Tab Bar or Accordion
7. Dense Toolbar / Filter Strip → Collapsible / Sheet
8. Sidebar Panel → Bottom Sheet or Drawer
9. Hover Cards / Tooltip Content → Always Visible or Tap-to-Reveal
10. Split Pane (master/detail) → Stack with Navigation
11. Dropdown Menus → Action Sheet
12. Pagination → Infinite Scroll or Load More

---

## 1. Data Table → Card List

**When to apply**: Table has more than 3 columns, or any column would be less
than 80px wide at 375px viewport.

**Pattern**: Each table row becomes a card. The most important column value
becomes the card headline. All other columns become label–value pairs within
the card.

```
Desktop row:                        Mobile card:
│ #84201 │ Niamh O'S │ Dispatch │   ┌────────────────────────────┐
│ XGS-PON│ 27 Mar    │ 91%      │   │ #84201  [XGS-PON]          │
                                    │ Niamh O'Sullivan           │
                                    │ Fault Repair — No Service  │
                                    │ 27 Mar · 09:00–13:00       │
                                    │ ✅ Dispatch  91% confident  │
                                    └────────────────────────────┘
```

**Rules**:
- Card min-height: 72px; padding: 14px 16px
- Primary identifier (ID, name) at top in bold
- Status badge always visible (not hidden in a column)
- Row actions (arrow, kebab) become a visible button at top-right of card
- Swipe-left to reveal destructive action (optional but native-feeling)

---

## 2. KPI Strip → Horizontal Scroll or 2×N Grid

**When to apply**: KPI strip has more than 3 cards and does not fit at 375px.

**Option A — Horizontal scroll** (preferred when cards are equal weight):
```css
.kpi-strip {
  display: flex;
  overflow-x: auto;
  scroll-snap-type: x mandatory;
  -webkit-overflow-scrolling: touch;
  gap: 10px;
  padding-bottom: 4px; /* show scroll shadow */
}
.kpi-card {
  flex: 0 0 160px; /* fixed width, scrollable */
  scroll-snap-align: start;
}
```

**Option B — 2×N grid** (preferred when one KPI is primary):
```css
@media (max-width: 767px) {
  .kpi-strip {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }
  .kpi-card:first-child {
    grid-column: 1 / -1; /* primary KPI spans full width */
  }
}
```

---

## 3. Multi-column Form → Single Column

**When to apply**: Any form with more than 1 column at mobile widths.

**Rules**:
- All fields: `width: 100%`
- Labels above fields (not inline/floating on mobile)
- Input `font-size: 16px` minimum (prevents iOS zoom on focus)
- Grouping: use visual separators (border-top, section label) not columns
- Submit button: full width, 48px height, at the bottom of the form

---

## 4. Map → Full-Screen with Floating Controls

**When to apply**: Map is embedded in a split layout (map + sidebar).

**Pattern**: The map goes full-screen. Sidebar content moves to a
bottom sheet that the user can pull up.

```
Desktop:                          Mobile:
┌──────────┬─────────┐           ┌──────────────────────┐
│          │ Summary │           │                      │
│   MAP    │ Stats   │           │      MAP             │
│          │ Alerts  │           │  (full screen)       │
│          │         │           ├──────────────────────┤
└──────────┴─────────┘           │ ▲ Summary   38 jobs  │
                                 │ (pull up for detail) │
                                 └──────────────────────┘
```

**Implementation**:
- Map container: `position: fixed; inset: 0; z-index: 0`
- Bottom sheet: `position: fixed; bottom: 0; left: 0; right: 0; z-index: 10`
- Bottom sheet default height: ~200px; expanded height: 50vh–80vh
- Use CSS `transform: translateY()` + `transition` for pull-up animation
- Add touch drag handle (40×4px rounded bar at top of sheet)
- Floating action controls (zoom, locate): `position: absolute` over map

---

## 5. Modal / Dialog → Bottom Sheet

**When to apply**: Any `position: fixed` modal / dialog on mobile.

**Pattern**: Modals on mobile should slide up from the bottom, not float
in the center. Center-modal on mobile = awkward dismiss, keyboard issues,
95% coverage.

```css
/* Desktop: centered modal */
@media (min-width: 768px) {
  .modal {
    top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    max-width: 600px; border-radius: 16px;
  }
}

/* Mobile: bottom sheet */
@media (max-width: 767px) {
  .modal {
    top: auto; left: 0; right: 0; bottom: 0;
    transform: translateY(0);
    border-radius: 20px 20px 0 0;
    max-height: 90vh;
    overflow-y: auto;
  }
  .modal-enter { transform: translateY(100%); }
  .modal-enter-active { transform: translateY(0); transition: transform 0.3s ease; }
}
```

**Rules**:
- Add drag handle at top
- `padding-bottom: env(safe-area-inset-bottom)` on content
- Tap outside backdrop dismisses sheet
- Scrollable content inside sheet: `overflow-y: auto; -webkit-overflow-scrolling: touch`

---

## 6. Multi-tab Interface → Bottom Tab Bar or Accordion

**When to apply**: App has horizontal tab bar in the page body (not top nav).

**Option A — Bottom tab bar** (when tabs = primary navigation, 3–5 items):
Already covered in SKILL.md under Navigation Transformation.

**Option B — Accordion** (when tabs = secondary navigation or filtering):

```
Desktop:                        Mobile:
[ Tab1 ] [ Tab2 ] [ Tab3 ]      ▼ Tab1 (expanded)
─────────────────────────         content...
  Tab1 content                  ▶ Tab2 (collapsed)
                                ▶ Tab3 (collapsed)
```

Use accordion when:
- Tabs contain long-form content
- More than 5 tabs
- Tabs live inside a card or panel (not top-level)

---

## 7. Dense Toolbar / Filter Strip → Collapsible Row + Sheet

**When to apply**: Horizontal filter bar, action bar, or toolbar with 4+ controls.

**Pattern**:
- Show only the 1–2 most important controls inline
- Remaining controls behind a "Filters" or "More" button
- Tapping opens a bottom sheet with all filter options

```
Desktop: [Search___] [Date▼] [Status▼] [Type▼] [Sort▼] [Export]
Mobile:  [Search___] [⚙ Filters (3)]
                          ↕ (sheet opens)
                     Date: [...]
                     Status: [...]
                     Type: [...]
```

Active filter count badge on the "Filters" button shows how many are applied.

---

## 8. Sidebar Panel → Bottom Sheet or Off-canvas Drawer

**When to apply**: Right-side detail panel in a master/detail layout,
or a left sidebar with secondary navigation.

**For detail panels** (e.g., selected-case right pane in a queue):

```
Desktop:                      Mobile:
┌────────────┬──────────┐     ┌──────────────────┐
│ Queue list │ Detail   │  →  │ Queue list       │
│            │ panel    │     │ [tap row]        │
└────────────┴──────────┘     └──────────────────┘
                                      ↓ (tap)
                              ┌──────────────────┐
                              │ ← Back  Detail   │
                              │ (full-screen)    │
                              └──────────────────┘
```

**Rules**:
- Stack becomes a navigation: list → push detail page onto stack
- Back button or swipe-right returns to list
- Alternatively: detail slides up as bottom sheet (simpler, no routing needed)

---

## 9. Hover Cards / Tooltips → Always Visible or Tap-to-Reveal

**When to apply**: Any content that only appears on `:hover`.

**Decision tree**:
```
Is the content critical to understanding the item?
  YES → Make it always visible (move it below/beside the element)
  NO  → Is the content supplementary detail (e.g. full name for truncated text)?
    YES → Show on tap (toggle visibility with :focus or JS)
    NO  → Remove it (was probably unnecessary)
```

**Never**: Leave hover-only content as-is on mobile. It simply never appears.

---

## 10. Split Pane (Master/Detail) → Stacked Navigation

**When to apply**: Two-panel layout where left = list, right = detail.

Already covered in item 8. The key pattern:

- On mobile, only one panel is visible at a time
- Tapping a list item pushes the detail view (slide in from right)
- Back button / swipe-right gesture returns to the list
- URL should reflect the detail state if the app has routing

**Routing approach** (framework-agnostic):
```
/queue          → shows list only on mobile, both on desktop
/queue/:caseId  → shows detail only on mobile, detail highlighted on desktop
```

---

## 11. Dropdown Menus → Action Sheet

**When to apply**: Click-triggered dropdown menus with 3+ options.

**Pattern**: On mobile, dropdowns become action sheets (list of options sliding
up from the bottom of the screen).

```
Desktop: [▼ Sort by Name ▼]
             ↓ hover/click
         ┌─────────────┐
         │ Name ↑      │
         │ Name ↓      │
         │ Date        │
         └─────────────┘

Mobile: [⇅ Sort]
             ↓ tap
         ┌──────────────────────┐
         │ Sort by              │
         ├──────────────────────┤
         │ ○ Name (A→Z)         │
         │ ● Name (Z→A)         │
         │ ○ Date               │
         ├──────────────────────┤
         │ [Cancel]             │
         └──────────────────────┘
```

---

## 12. Pagination → Infinite Scroll or Load More Button

**When to apply**: Page-number pagination at bottom of a list or table.

**Option A — "Load More" button** (recommended for internal tools):
- Simpler to implement, predictable position in the list
- User has control over loading
- Works well with slow network connections

**Option B — Infinite scroll**:
- Better for content-feed style lists
- Use `IntersectionObserver` to trigger next page load when sentinel element is visible
- Always show a loading indicator, never a blank gap

**Never** use page number pagination on mobile — tap targets are too small
and the UX is unexpected on touch devices.
