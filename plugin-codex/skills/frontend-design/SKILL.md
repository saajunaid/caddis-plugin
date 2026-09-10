---
name: frontend-design
description: Create distinctive, production-grade frontend interfaces with high design quality. Use this skill when the user asks to build web components, pages, artifacts, posters, or applications. Generates creative, polished code that avoids generic AI aesthetics while strictly adhering to the user's technical standards.
---

# Frontend Design Skill

This skill guides the creation of distinctive, production-grade frontend interfaces that avoid generic "AI slop" aesthetics. Implement real working code with exceptional attention to aesthetic details and creative choices.

## 1. Core Principle: Avoid "AI Slop"
- **Typography:** Avoid system fonts (Inter, Arial, Roboto). Pair a distinctive display font (e.g., *Cormorant Garamond*, *Playfair Display*, *Space Mono*) with a refined, readable body font. Use dramatic scale jumps ($h1 > 5rem$ vs metadata $< 0.75rem$).
- **Color & Theme:** Commit to a cohesive aesthetic. Use CSS variables for consistency. Dominant colors with sharp accents outperform timid, evenly-distributed palettes.
- **Visuals:** Create atmosphere and depth using textures (grain, noise), glassmorphism, or complex gradients rather than defaulting to solid flat colors.

## 2. Technical Implementation Standards
**CRITICAL:** You must ignore generic React patterns. Instead, you represent the specific technical architecture defined in the user's stack.

**Mandatory Reference:**
Before writing any component logic, state management, or hooks, you must cross-reference and apply the patterns found in:
`./references/my-tech-stack.md`

Specifically, you must:
1.  **Use Composition:** Build flexible UIs using the *Composition Over Inheritance* and *Compound Component* patterns defined in the reference file.
2.  **Use Custom Hooks:** Do not write ad-hoc logic for debouncing or toggling; use `useDebounce` and `useToggle` from the reference.
3.  **Optimize Performance:** Apply `useMemo` and `useCallback` strictly according to the "Memoization Rules" in the reference.
4.  **Ensure Stability:** Wrap complex or risky components in the `ErrorBoundary` pattern provided.
5.  **Enforce Accessibility:** Follow the keyboard navigation and focus management patterns exactly as specified.

## 3. Design Thinking Process
Before coding, understand the context and commit to a BOLD aesthetic direction:
- **Tone:** Pick an extreme (Brutalist, Luxury, Retro-futuristic, Editorial, Industrial).
- **Motion:** Use animations for effects and micro-interactions. Focus on high-impact moments (staggered page loads) rather than scattered micro-interactions.
- **Differentiation:** What makes this UNFORGETTABLE? What's the one thing someone will remember?

## 4. Output Requirements
Then implement working code (HTML/CSS/JS, React, Vue, etc.) that is:
- **Production-grade:** Functional, responsive, and accessible.
- **Visually striking:** Memorable and cohesive with a clear point-of-view.
- **Technically compliant:** Strictly follows the architecture in `my-tech-stack.md`.

## 5. Transition Integrity (No Stale UI)

For data-heavy views that switch entities (profile A → profile B), enforce deterministic transitions:

- Use a **single render region** (e.g., Streamlit's `st.empty()`) that replaces its entire content on each render pass.
- **NEVER use dynamic keys** (nonce, entity ID) on containers inside `st.empty()` — dynamic keys cause the framework to create *new* DOM nodes instead of replacing existing ones, leaving ghost/shadow copies visible for 1-2 seconds until frontend reconciliation catches up.
- Use **stable keys** on inner containers. The render region handles content replacement; inner containers just need stable identity for in-place DOM updates.
- Temporarily hide high-salience identity panels/tabs during loading to avoid ghosted prior-state flashes.
- Execute state transitions outside container context managers to avoid interrupted cleanup.

Acceptance rule: users must only perceive `old state → loader → new state`, with no stale intermediate artifacts.

## 6. Dial System — Design Variance Controls

Calibrate these three dials per project before writing any component. Declare them in a comment at the top of the main design file.

```ts
// DESIGN_VARIANCE: 7      // 1 (safe/corporate) → 10 (experimental/editorial)
// MOTION_INTENSITY: 5     // 1 (static) → 10 (cinematic)
// VISUAL_DENSITY: 4       // 1 (minimal/lots of space) → 10 (data-dense/information-heavy)
```

| Dial | 1–3 | 4–6 | 7–10 |
|---|---|---|---|
| `DESIGN_VARIANCE` | Standard grid, safe palette | Distinctive but accessible | Experimental layout, bold choices |
| `MOTION_INTENSITY` | Opacity fade only | Entrance animations, hover states | Parallax, stagger, spring physics |
| `VISUAL_DENSITY` | Hero + CTA, generous whitespace | Cards with secondary info | Dashboard-style, compact rows |

**Rule**: Do not override the user's declared dials. If undeclared, infer from context and state your assumption.

## 7. AI Tells — Forbidden Patterns

These are signals of generic AI output. Every instance must be eliminated:

### Generic Names
- ❌ `Company Name`, `Your Brand`, `Hello, World!`, `Example Corp`
- ✅ Invent plausible, domain-specific content: `Meridian Analytics`, `Kaspar & Voss`, `Orin Health`

### Fake Placeholder Numbers
- ❌ `$1,234.56`, `1,234 users`, `99.9% uptime`, `42 orders`
- ✅ Domain-plausible numbers with realistic variance: `$14,820`, `3,241 customers`, `99.4% uptime`, `127 orders`

### AI Copywriting Clichés
- ❌ "Empowering your workflow", "Seamlessly integrated", "Next-generation solution", "Unlock the power of..."
- ✅ Specific, functional copy: "Track invoice aging in real time", "Filter by region, team, or date"

### Oversaturated Accents
- ❌ `#FF6B6B` coral-pink, `#6C63FF` purple-blue gradient (the two default AI accent colors)
- ✅ Chosen from the brief or brand guide; if absent, pick something unexpected: amber, forest green, slate

### Generic Iconography
- ❌ Rocket ship for launching, lightbulb for ideas, three horizontal bars for "menu" on desktop nav
- ✅ Icons that match the actual function; text labels as fallback if icon meaning is ambiguous

## 8. Typography Discipline

- **Maximum 2 font families** — one display (headings), one text (body + UI). Loading 3+ is a performance and taste failure.
- **Optical sizing**: Headings at `6rem+` need `letter-spacing: -0.03em`. Text under `0.875rem` needs `letter-spacing: 0.01em`.
- **Vertical rhythm**: `line-height: 1.6` for body, `1.1–1.2` for large headings, `1.4` for UI labels.
- **Scale**: Use a modular scale (1.25× or 1.333×), not arbitrary sizes. Common scale: `0.75 / 0.875 / 1 / 1.125 / 1.5 / 2 / 3 / 4.5rem`.
- **Weight contrast**: Body at 400, labels at 500, headings at 700–800. Avoid using 4 or more weights.

```css
/* Correct optical sizing */
.hero-heading {
  font-size: clamp(3rem, 6vw + 1rem, 6rem);
  line-height: 1.05;
  letter-spacing: -0.04em;
}
.body-text {
  font-size: 1rem;
  line-height: 1.625;
  letter-spacing: 0;
}
```

## 9. Color Calibration

- **Maximum 1 accent color** — two accents compete; zero creates bland work.
- **Palette minimum**: Background, Surface (+1 level of elevation), Text, Muted text, Border, Accent, Destructive.
- **Forbidden**: Purple/blue AI gradient cliché (`from-purple-500 to-blue-600` or equivalent). Use if and only if the brand explicitly requires it.
- **Dark mode**: Shift background to `hsl(220 15% 8%)` range, not pure black (`#000`). Pure black with white text fails contrast for long reading.
- **Accent contrast**: Accent on background must pass WCAG AA (4.5:1 for normal text, 3:1 for large text / UI components).

```css
/* ✅ Correct token setup */
:root {
  --bg: hsl(220 15% 97%);
  --surface: hsl(220 15% 100%);
  --text: hsl(220 25% 12%);
  --muted: hsl(220 10% 50%);
  --border: hsl(220 15% 88%);
  --accent: hsl(38 92% 50%);       /* Amber — unexpected, not AI-default */
  --destructive: hsl(0 72% 51%);
}
```

## 10. Layout Diversification

When `DESIGN_VARIANCE` > 4, **ban the centered-hero-with-CTA default** layout. Use instead:

| Layout Pattern | When to Use |
|---|---|
| **Editorial split** — large text left, visual right (or reversed) | Brand/marketing pages |
| **Bento grid** — asymmetric tiles of varying sizes | Dashboards, feature showcases |
| **Fullbleed scroll narrative** — content revealed on scroll sections | Storytelling, case studies |
| **Sidebar dock + content** — persistent nav or filter rail | Application interfaces |
| **Masonry** — uneven column heights | Media, portfolio grids |
| **Timeline / sequence** — vertical progression with connectors | Onboarding, process flows |

**Never** stack all sections centered on a 1200px `max-width` container unless `DESIGN_VARIANCE` ≤ 3.

## 11. Interactive State Completeness

Every interactive element must implement all four states before the component is done:

| State | What to Implement |
|---|---|
| **Loading** | Skeleton, spinner, or disabled appearance while data fetches |
| **Empty** | Non-generic empty state with context-specific message + action |
| **Error** | Specific error message, retry action, not just "Something went wrong" |
| **Tactile** | Hover + active (pressed) visual feedback — scale, shadow, or color shift |

```tsx
// ✅ Complete interactive state example
function DataCard({ id }: { id: string }) {
  const { data, error, status } = useQuery(...)
  
  if (status === 'pending') return <CardSkeleton />
  if (status === 'error')   return <ErrorCard message={error.message} onRetry={refetch} />
  if (!data.items.length)   return <EmptyCard title="No records yet" action={<CreateButton />} />
  
  return (
    <div className="group transition-all hover:shadow-md hover:-translate-y-0.5 active:scale-[0.99]">
      {/* content */}
    </div>
  )
}
```

## 12. Data Realism

Never use placeholder data that signals the interface is unfinished:

| ❌ Avoid | ✅ Use Instead |
|---|---|
| "Lorem ipsum dolor sit amet" | Domain-appropriate text: "Q3 revenue shows 14% growth vs prior quarter" |
| User: "John Doe" | Plausible name + avatar initial: "Margot Belleview" |
| Date: "January 1, 2024" | Recent plausible date: "Feb 12, 2026" |
| Metric: "1,234" | Realistic variance: "3,817" (not round numbers with too many digits) |
| Chart data: constant line | Realistic noise with trend: slight growth with variance |

**Rule**: Each piece of sample data should make a reviewer believe it could be real production data, not a template. If the user provides real data patterns, use them precisely.