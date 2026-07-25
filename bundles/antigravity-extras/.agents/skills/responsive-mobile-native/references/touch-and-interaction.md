# Touch & Interaction Reference

Complete rules for making web UI feel native on touch devices.

---

## Tap Targets

Every interactive element must meet the **44×44px minimum** (Apple HIG, WCAG 2.5.8).
This includes buttons, links, nav items, table row actions, icon buttons, toggles,
checkboxes, and close/dismiss controls.

**Expanding small elements without changing visual size**:

```css
/* Use padding to expand the hit area without changing appearance */
.icon-btn {
  padding: 12px;            /* visual size + hit area expansion */
  margin: -12px;            /* negative margin to cancel layout effect */
}

/* Or use pseudo-element hit area expansion */
.small-link {
  position: relative;
}
.small-link::after {
  content: '';
  position: absolute;
  inset: -10px;             /* expand hit area 10px in all directions */
}
```

---

## Removing Hover Dependencies

### Audit pattern

Search for every `:hover` style in the codebase. For each one, ask:
- Does this reveal content? → Must have a touch equivalent
- Does this change visual state (colour, shadow)? → Also apply to `:active` and `:focus-visible`
- Is it purely decorative (slight glow)? → Safe to leave but add `:active` too

### Fixing hover-only reveals

```css
/* BEFORE — only shows on hover */
.action-buttons {
  opacity: 0;
  transition: opacity 0.15s;
}
.table-row:hover .action-buttons {
  opacity: 1;
}

/* AFTER — always visible on touch devices */
@media (hover: none) {
  .action-buttons {
    opacity: 1;
  }
}
/* Desktop hover behaviour preserved via @media (hover: hover) */
@media (hover: hover) {
  .action-buttons { opacity: 0; }
  .table-row:hover .action-buttons { opacity: 1; }
}
```

The `@media (hover: hover)` / `@media (hover: none)` media query is the
correct way to distinguish touch from pointer devices. Do not use user-agent sniffing.

### Touch feedback

Every tappable element needs visible feedback on tap. Use `:active`:

```css
.btn:active,
.nav-item:active,
.card:active {
  transform: scale(0.97);
  opacity: 0.85;
  transition: transform 0.1s, opacity 0.1s;
}

/* Prevent iOS default tap highlight (replace with your own) */
* {
  -webkit-tap-highlight-color: transparent;
}
```

---

## Scroll Handling

### Smooth momentum scroll

```css
.scrollable-container {
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;  /* momentum scroll on iOS */
  overscroll-behavior: contain;       /* prevent scroll chaining to parent */
}
```

### Horizontal scroll containers (KPI strips, tab bars, chip lists)

```css
.horizontal-scroll {
  display: flex;
  overflow-x: auto;
  scroll-snap-type: x mandatory;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;           /* hide scrollbar on mobile */
  gap: 10px;
  padding-bottom: 4px;             /* prevents shadow clipping */
}
.horizontal-scroll::-webkit-scrollbar { display: none; }

.scroll-item {
  flex-shrink: 0;
  scroll-snap-align: start;
}
```

### Preventing scroll bleed in modals / sheets

```css
/* When sheet/modal is open, lock the body */
body.sheet-open {
  overflow: hidden;
  /* iOS requires this too: */
  position: fixed;
  width: 100%;
}
```

---

## Safe Area Insets (iPhone Notch & Home Bar)

Required for any fixed elements at top or bottom of screen.

```css
/* Bottom nav bar */
.bottom-nav {
  padding-bottom: env(safe-area-inset-bottom);
  /* min height + safe area */
  height: calc(56px + env(safe-area-inset-bottom));
}

/* Content area */
.main-content {
  padding-bottom: calc(64px + env(safe-area-inset-bottom));
  padding-top: env(safe-area-inset-top);
}

/* Bottom sheets */
.bottom-sheet-content {
  padding-bottom: max(16px, env(safe-area-inset-bottom));
}
```

Requires `viewport-fit=cover` in the viewport meta tag (covered in SKILL.md).

---

## Gesture Hooks

### Swipe to dismiss / navigate back

Implement with `touchstart` + `touchend` tracking:

```js
// Framework-agnostic swipe detector
function useSwipe({ onSwipeLeft, onSwipeRight, threshold = 50 }) {
  let startX = null;

  return {
    onTouchStart: (e) => { startX = e.touches[0].clientX; },
    onTouchEnd: (e) => {
      if (startX === null) return;
      const diff = e.changedTouches[0].clientX - startX;
      if (Math.abs(diff) < threshold) return;
      if (diff < 0) onSwipeLeft?.();
      else onSwipeRight?.();
      startX = null;
    }
  };
}
```

### Pull-to-refresh

Only implement if the page has data that updates in real time (queue, live map).
Use native `overscroll-behavior: contain` + CSS animation, or a lightweight library.
Do not build custom pull-to-refresh — it conflicts with browser scroll behaviour.

### Bottom sheet drag handle

```js
// Minimal drag-to-expand/collapse for a bottom sheet
function initSheetDrag(sheetEl) {
  let startY, startHeight;
  const handle = sheetEl.querySelector('.drag-handle');

  handle.addEventListener('touchstart', (e) => {
    startY = e.touches[0].clientY;
    startHeight = sheetEl.getBoundingClientRect().height;
  });

  handle.addEventListener('touchmove', (e) => {
    const delta = startY - e.touches[0].clientY;
    const newHeight = Math.min(
      Math.max(startHeight + delta, 120),  // min 120px
      window.innerHeight * 0.9              // max 90vh
    );
    sheetEl.style.height = newHeight + 'px';
  });
}
```

---

## Input & Keyboard

### Prevent iOS zoom on input focus

```css
input, select, textarea {
  font-size: 16px; /* minimum to prevent iOS auto-zoom */
}
```

If your design system uses smaller input text, use `font-size: 16px` on the
element itself and `transform: scale(0.875)` with `transform-origin: left` to
visually match your design.

### Keyboard-aware layout

When the virtual keyboard opens, fixed elements at the bottom of the screen can
end up behind it. Use the `visualViewport` API to detect this:

```js
window.visualViewport?.addEventListener('resize', () => {
  const keyboardHeight = window.innerHeight - window.visualViewport.height;
  document.querySelector('.bottom-bar').style.transform =
    `translateY(-${keyboardHeight}px)`;
});
```

---

## CSS `touch-action` Property

Control which gestures the browser handles natively:

| Value | Use case |
|---|---|
| `touch-action: pan-y` | Vertical scroll only (carousel, horizontal swipe area) |
| `touch-action: pan-x` | Horizontal scroll only |
| `touch-action: none` | Fully custom gesture (drawing canvas, drag-and-drop) |
| `touch-action: manipulation` | Allow pan + pinch-zoom, disable double-tap zoom |

Apply `touch-action: manipulation` to all buttons and interactive elements to
eliminate the 300ms tap delay on older browsers.
