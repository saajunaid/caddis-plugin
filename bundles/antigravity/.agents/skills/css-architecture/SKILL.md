---
name: css-architecture
description: CSS architecture, design token strategy, Tailwind conventions, CSS Modules, container queries, dark mode, responsive patterns, and animation architecture. Use for design token naming, CSS custom properties, Tailwind config, container queries, dark mode implementation, fluid typography, or CSS animation decisions. Complements frontend-design (what to achieve) with how to implement it.
---

# CSS Architecture Skill

How to implement what `frontend-design` specifies. Covers design token strategy, Tailwind conventions, responsive patterns, dark mode, and animation architecture.

## 1. Design Token Strategy — CSS Custom Properties

### Hierarchy (global → component)
```css
/* Layer 1: Primitive tokens (raw values) */
:root {
  --color-slate-900: #0f172a;
  --color-slate-100: #f1f5f9;
  --color-amber-500: #f59e0b;
  --space-4: 1rem;
  --space-8: 2rem;
  --radius-md: 0.5rem;
  --font-sans: 'Inter Variable', system-ui, sans-serif;

  /* Layer 2: Semantic tokens (intent) */
  --color-bg: var(--color-slate-900);
  --color-surface: hsl(220 15% 12%);
  --color-text: var(--color-slate-100);
  --color-accent: var(--color-amber-500);
  --color-border: hsl(220 15% 20%);

  /* Layer 3: Component tokens */
  --button-bg: var(--color-accent);
  --button-text: var(--color-slate-900);
  --card-padding: var(--space-8);
}
```

### Naming Conventions
- Primitive: `--color-{hue}-{shade}`, `--space-{n}`, `--radius-{size}`
- Semantic: `--color-{role}` (bg, surface, text, accent, border, error, success)
- Component: `--{component}-{property}` (button-bg, card-radius)
- Never skip semantic layer — primitives must not be used directly in components.

## 2. Tailwind Conventions

### v3 Config (`tailwind.config.ts`)
```ts
import type { Config } from 'tailwindcss'
import { fontFamily } from 'tailwindcss/defaultTheme'

const config: Config = {
  content: ['./src/**/*.{ts,tsx,mdx}'],
  darkMode: 'class',  // or 'media'
  theme: {
    extend: {
      colors: {
        // Map to CSS custom properties so tokens work everywhere
        bg: 'hsl(var(--color-bg) / <alpha-value>)',
        surface: 'hsl(var(--color-surface) / <alpha-value>)',
        accent: 'hsl(var(--color-accent) / <alpha-value>)',
        border: 'hsl(var(--color-border) / <alpha-value>)',
      },
      fontFamily: {
        sans: ['var(--font-sans)', ...fontFamily.sans],
        display: ['var(--font-display)', ...fontFamily.serif],
      },
      borderRadius: { DEFAULT: 'var(--radius-md)' },
      animation: {
        'fade-up': 'fadeUp 0.4s ease-out',
        'fade-in': 'fadeIn 0.3s ease-out',
      },
      keyframes: {
        fadeUp: { from: { opacity: '0', transform: 'translateY(12px)' }, to: { opacity: '1', transform: 'none' } },
        fadeIn: { from: { opacity: '0' }, to: { opacity: '1' } },
      },
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
    require('@tailwindcss/container-queries'),
  ],
}
export default config
```

### v4 Config (CSS-first)
```css
/* globals.css — Tailwind v4 uses @theme, no tailwind.config.ts */
@import "tailwindcss";

@theme {
  --color-accent: oklch(75% 0.18 85);
  --font-sans: 'Inter Variable', system-ui, sans-serif;
  --radius-default: 0.5rem;
}
```

### `@apply` Rules
- Use `@apply` sparingly — only for repeated utility combos in shared components (`btn`, `card`).
- Prefer component classes over `@apply` in large components — Tailwind utility classes in JSX are more readable.
- Never `@apply` responsive or state variants (`hover:`, `md:`) — those are JSX-only.

## 3. CSS Modules vs Tailwind — Decision Criteria

| Use Tailwind | Use CSS Modules |
|---|---|
| UI components, layouts, spacing | Complex animations with `@keyframes` that need JS access |
| Responsive design | Component styles that conflict with Tailwind's reset |
| Dark mode | Styles requiring CSS `calc()` with token math |
| One-off utility combos | Legacy codebases with existing `.module.css` patterns |
| New projects | Server-rendered styles that must avoid className hydration |

**Hybrid**: Tailwind for layout/spacing/color, CSS Modules for complex animation or context-dependent logic.

## 4. Container Queries

Responsive based on parent container width, not viewport.

```tsx
// tailwind.config.ts: add @tailwindcss/container-queries plugin
// Install: pnpm add -D @tailwindcss/container-queries

export function Card({ children }: { children: React.ReactNode }) {
  return (
    // Mark the container
    <div className="@container rounded-lg bg-surface p-6">
      <div className="grid @sm:grid-cols-2 @lg:grid-cols-3 gap-4">
        {children}
      </div>
    </div>
  )
}
```

```css
/* Pure CSS container queries */
.card { container-type: inline-size; }

@container (min-width: 400px) {
  .card-body { display: grid; grid-template-columns: 1fr 1fr; }
}
```

**Use container queries when**: a component is used in multiple layout contexts (sidebar vs main vs modal) and needs different layouts in each.

## 5. Dark Mode

### Class Toggle (recommended for app control)
```tsx
// Toggle on <html> element
document.documentElement.classList.toggle('dark')

// Tailwind: darkMode: 'class' in config
// CSS: dark: prefix on utilities
<div className="bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100">
```

### CSS Custom Property Token Switching
```css
:root {
  --color-bg: hsl(0 0% 100%);
  --color-text: hsl(220 15% 10%);
  --color-accent: hsl(220 90% 55%);
}

.dark {
  --color-bg: hsl(220 15% 8%);
  --color-text: hsl(220 10% 90%);
  --color-accent: hsl(220 90% 65%);
}

/* With prefers-color-scheme fallback */
@media (prefers-color-scheme: dark) {
  :root:not(.light) {
    --color-bg: hsl(220 15% 8%);
    --color-text: hsl(220 10% 90%);
  }
}
```

## 6. Responsive Patterns — Mobile-First

```tsx
// Mobile-first: base = mobile, md: = tablet, lg+ = desktop
<div className="
  flex flex-col gap-4          /* mobile */
  md:flex-row md:gap-6         /* tablet */
  lg:gap-8                     /* desktop */
">
```

### Fluid Typography with `clamp()`
```css
/* Min, preferred (viewport-relative), max */
.hero-heading {
  font-size: clamp(2rem, 5vw + 1rem, 5rem);
  line-height: clamp(1.1, 1.2, 1.3);
}

/* In Tailwind (custom utility) */
/* tailwind.config.ts > theme.extend.fontSize */
'fluid-xl': 'clamp(1.5rem, 3vw + 0.5rem, 2.5rem)',
```

### Breakpoint Tokens
```ts
// Consistent with Tailwind defaults
const breakpoints = { sm: '640px', md: '768px', lg: '1024px', xl: '1280px', '2xl': '1536px' }
```

## 7. Animation Architecture

### Decision Matrix
| Use Case | Solution |
|---|---|
| Simple enter/exit | CSS `@keyframes` + `transition` |
| Complex sequences / orchestrated | Framer Motion |
| Physics-based spring | Framer Motion `spring` |
| Hover/focus micro-interactions | CSS `transition` (no JS cost) |
| Scroll-driven | CSS `@scroll-timeline` or Framer `useInView` |
| Page transitions | Framer `AnimatePresence` |

### CSS Transitions
```css
/* ✅ GPU-accelerated properties only */
.card {
  transition: transform 200ms ease-out, opacity 200ms ease-out,
              box-shadow 200ms ease-out;
}
.card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 32px hsl(0 0% 0% / 0.15);
}
```

### `@keyframes` Structure
```css
@keyframes slideIn {
  from { opacity: 0; transform: translateX(-16px); }
  to   { opacity: 1; transform: none; }
}

/* Apply with animation shorthand */
.panel { animation: slideIn 300ms ease-out both; }
```

### `prefers-reduced-motion` — Non-Negotiable
```css
/* Global reset for reduced motion */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

## 8. Anti-Patterns

| Anti-Pattern | Problem | Fix |
|---|---|---|
| `!important` | Specificity wars, hard to override | Refactor selector or use CSS layers (`@layer`) |
| Specificity wars | `.sidebar .card .button {}` | BEM naming or CSS Modules scoping |
| Magic numbers z-index (`z-[9999]`) | Unpredictable stacking | Named z-index tokens in config |
| Inline style overrides | Bypasses design system | Add utility class or extend Tailwind theme |
| Animating layout properties | Reflow on every frame | Animate `transform` + `opacity` only |
| `@apply` for large blocks | Reduces readability benefit of Tailwind | Component extraction instead |
| Global selector bleed in CSS Modules | `.module.css` affects non-module elements | Scope all selectors with `:local()` or class names |

## 9. Z-Index Layer System

```ts
// tailwind.config.ts
extend: {
  zIndex: {
    base: '0',
    above: '10',
    dropdown: '100',
    sticky: '200',
    overlay: '300',
    modal: '400',
    toast: '500',
    tooltip: '600',
  }
}
```

```tsx
// Use named z-index in JSX
<div className="z-modal">…</div>
```

## 10. Checklist

- [ ] CSS custom properties defined at 3 layers (primitive → semantic → component)
- [ ] No primitive tokens used directly in component styles
- [ ] Tailwind version confirmed before writing config
- [ ] `@apply` used only for repeated utility combos, not state variants
- [ ] Container queries used for multi-context components
- [ ] Dark mode uses token switching (not duplicated utility classes)
- [ ] All animations respect `prefers-reduced-motion`
- [ ] Fluid typography with `clamp()` for hero/heading text
- [ ] Z-index uses named tokens, not inline integers
- [ ] No `!important` in component styles
