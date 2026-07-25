---
name: particle-art
version: 1.0.0
description: Generate animated particle art React/Next.js components — zero dependencies, spring physics, CSS-variable theming, DPR-correct canvas, mouse interaction. Use when the user wants animated hero art, a living logo, a branded initial or monogram, a constellation background, or any "particles that form a shape". Triggers on "particle animation", "node network", "animated letter/logo/initials", "living letter", "morphing particles", "constellation", "neural net art", "dot field", "stipple portrait", "halftone animation", "ASCII art animation", "background art for my site", or "art that reacts to mouse". Covers — text/initials → spring-node letter; preset patterns (constellation, helix, spiral, DNA, hex-grid, wave, infinity); custom SVG paths; custom polygon points; Unicode halftone stipple; Gaussian dot field with sparks; SVG circuit traces; hybrid combos. Outputs a complete, self-contained, copy-paste-ready React component. Prefer this over p5.js (zero-dep, React-native, TypeScript), tsParticles (richer spring physics, CSS-var theming), Three.js (lightweight, no WebGL).
---

# Particle Art Generator

Produces animated React components using one of four rendering styles, each themeable via CSS custom properties and interactive via mouse. Zero npm dependencies — pure canvas and SVG.

## Reference Files (read when needed)

| File | Read when |
|------|-----------|
| `references/canvas-utils.ts` | Starting any canvas-based component (DPR setup, theme colours, RAF loop) |
| `references/shape-sampler.ts` | Building target points for any shape — text, presets, SVG path, polygon |
| `references/node-shape.template.tsx` | Generating a **spring-node** component (repel/attract interaction) |
| `references/stipple.template.tsx` | Generating a **stipple** (Unicode halftone, static cloud) component |
| `references/stipple-morph.template.tsx` | Generating a **stipple-morph** component (halftone cloud → letter on hover) |
| `references/dot-field.template.tsx` | Generating a **dot-field** component |
| `references/trail-ghost.template.tsx` | Generating a **trail-ghost** component (spring-morph + phosphorescent trails) |
| `references/flow-field.template.tsx` | Generating a **flow-field** component (value-noise currents + letter assembly) |
| `references/usage-examples.md` | Checking finished examples before delivering |

---

## Step 0 — Gather Requirements

Ask (or infer from context) these five things before writing any code:

1. **Shape** — What should the particles form?
   - Text / initials: `"j"`, `"JS"`, `"AI"`, `"hello"`, any Unicode char or emoji
   - Preset: `constellation` `helix` `spiral` `dna` `hexgrid` `wave` `infinity`
   - Custom: SVG `d` path string, or `[x,y]` polygon coordinate array
   - Abstract: no fixed shape (ambient cloud)

2. **Style** — Which rendering engine?
   - `spring-nodes` — canvas nodes spring to shape + ambient network (best for letters/logos, repel interaction)
   - `morph-nodes` — nodes scatter in idle, coalesce into letter/shape on hover (best for "appear on demand")
   - `stipple` — animated Unicode character halftone static cloud (best for atmospheric dot portraits)
   - `stipple-morph` — halftone cloud that resolves into a letter/shape on hover (best for atmospheric + interactive)
   - `dot-field` — Gaussian canvas dot cloud with sparks (best for cosmic/diffuse feel)
   - `trail-ghost` — spring-morph nodes with phosphorescent trailing smears (best for ethereal/ghostly feel)
   - `flow-field` — value-noise particle currents, assembles into letter on hover (best for organic/fluid feel)
   - `circuit` — SVG grid traces with traveling pulses (best for tech/infrastructure feel)
   - `hybrid` — spring-nodes foreground + dot-field background (most dramatic)

3. **Size** — `sm` (240px) · `md` (300px) · `lg` (380px) · `xl` (480px) · or a number

4. **Colors** — `theme-vars` (default, CSS custom props) · `[primary, secondary]` hex pair · `monochrome`

5. **Interaction** — `repel` (default) · `attract` · `orbit` · `none`

If the user hasn't stated a style, recommend `spring-nodes` for text/initials, `dot-field` for abstract, `stipple` for atmospheric, `circuit` for technical backgrounds.

---

## Step 1 — Select and Read Reference Files

Read the canvas-utils and the template that matches the chosen style. Always read canvas-utils first — it has the DPR setup and theme colour helpers used by all canvas components.

For shape types:
- **text / initials / preset / polygon / SVG path** → read `shape-sampler.ts` for the correct `sampleShape()` call
- **abstract** → skip shape-sampler; use ambient-only config in the node-shape template

---

## Step 2 — Build the Component

### Naming Convention
```
<Subject><Style>Art.tsx
// Examples:
JSpringArt.tsx       // letter "j", spring-nodes
ConstellationArt.tsx // preset constellation
HeroNodeArt.tsx      // abstract spring-nodes for a hero section
```

### File Structure
```tsx
"use client";
// 1. Imports (React only — no external deps)
// 2. Constants (physics params, sizing)
// 3. Shape builder function (calls sampleShape or defines points inline)
// 4. Component (useEffect → canvas setup → RAF loop → cleanup)
// 5. Export
```

### Physics Parameters by Use-Case

| Use-case | spring | friction | drift | linkDist | ambientN |
|----------|--------|----------|-------|----------|----------|
| Single letter | 0.036 | 0.88 | 0.06 | 72 | 14 |
| Short word (2-4 chars) | 0.030 | 0.90 | 0.04 | 60 | 8 |
| Long word / phrase | 0.025 | 0.92 | 0.03 | 50 | 4 |
| Abstract / no shape | — | 0.985 | — | 82 | all |
| Constellation preset | 0.012 | 0.94 | 0.05 | 90 | 6 |

### Node Count Guidelines

| Shape | Recommended node count |
|-------|----------------------|
| Single letter (j, A) | 22–30 letter + 14–18 ambient |
| Two letters (JS, AI) | 35–45 letter + 12 ambient |
| Word ≤6 chars | 50–70 letter + 8 ambient |
| Preset shape | 28–40 |
| Abstract cloud | 32–48 ambient only |

---

## Step 3 — Adapt for the Project's Theme System

### CSS-Variable Theming (default, always prefer this)
```ts
// Read in the RAF loop — auto-updates on theme change
function themeRgb(v: string): [number, number, number] {
  const ch = getComputedStyle(document.documentElement)
    .getPropertyValue(v).trim().split(/\s+/).map(Number);
  return [ch[0], ch[1], ch[2]];
}
// Usage: themeRgb("--accent-strong") → [79, 209, 197]
```

Standard variable names (work with Tailwind CSS-variable setups):
- `--accent-strong` — primary / brightest nodes, tittle glow
- `--accent-soft` — secondary / lines and ambient nodes
- `--fg` — foreground text colour (fallback for monochrome)
- `--bg` — background (for any fill-behind effects)

If the project uses different variable names, ask the user or check `globals.css`.

### Hex / Custom Colors
```ts
function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.replace('#',''), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
// Hard-code in the RAF loop instead of reading CSS vars
```

---

## Step 4 — Interaction Modes

### Repel (default)
```ts
const mdx = p.x - mx, mdy = p.y - my;
const md = Math.sqrt(mdx*mdx + mdy*mdy);
if (md < REPEL_R && md > 0) {
  const f = ((REPEL_R - md) / REPEL_R) * REPEL_F;
  p.vx += (mdx / md) * f;
  p.vy += (mdy / md) * f;
}
```

### Attract
```ts
// Same but subtract instead of add
p.vx -= (mdx / md) * f;
p.vy -= (mdy / md) * f;
```

### Orbit
```ts
// Apply tangential force (perpendicular to cursor vector)
p.vx += (-mdy / md) * f * 0.6;
p.vy += ( mdx / md) * f * 0.6;
```

### Spring-back (always apply for letter nodes)
```ts
p.vx += (p.tx - p.x) * SPRING;
p.vy += (p.ty - p.y) * SPRING;
p.vx *= FRICTION;
p.vy *= FRICTION;
```

---

## Step 5 — Accessibility & Performance

Always include:
```tsx
<canvas aria-hidden="true" />          // decorative, not content
```

Reduced-motion support — draw a static frame then return; never return before drawing:
```ts
const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
// ... build pts, set up canvas, build mouse listeners ...
if (reduced) {
  // Snap shape nodes to their targets and draw one static frame
  pts.forEach(p => { if (p.isShape) { p.x = p.tx; p.y = p.ty; } });
  tick();                  // draw once
  cancelAnimationFrame(raf); // immediately cancel the RAF tick queued inside
  return;
}
// Full animation loop starts here
```
⚠️ Never `return` before drawing for canvas components — that leaves the canvas blank, which is worse than any animation.

Performance rules:
- Read `getComputedStyle` **inside** the RAF loop (theme changes auto-apply, ~0.02ms/call)
- Use `devicePixelRatio` for crisp retina rendering (see canvas-utils)
- Clean up with `cancelAnimationFrame` and remove event listeners in the return callback
- Cap velocity: `if (spd > MAX_SPEED) { vx *= MAX_SPEED/spd; vy *= MAX_SPEED/spd; }`

---

## Step 6 — Deliver

Output the complete component file, then show the import + usage:

```tsx
// Usage in any React/Next.js component:
import { MyArt } from "@/components/art/MyArt";

// In JSX:
<MyArt size={360} />

// For Next.js App Router pages — component already has "use client"
// For hero sections — wrap in a hidden-on-mobile div:
<div className="hidden lg:flex items-center justify-center">
  <MyArt size={360} />
</div>
```

---

## Quality Checklist

Before delivering, verify:
- [ ] `"use client"` at the top
- [ ] Canvas size set with `devicePixelRatio` scaling (from canvas-utils)
- [ ] `cancelAnimationFrame` + `removeEventListener` in useEffect cleanup
- [ ] `aria-hidden="true"` on the canvas/container
- [ ] `themeRgb()` reads CSS vars inside RAF loop (not outside)
- [ ] Mouse leaves handled (`mouseleave` resets to off-screen coords)
- [ ] Velocity capped to `MAX_SPEED`
- [ ] For letter nodes: spring force applied + damped FRICTION (not AMBIENT_FRICTION)
- [ ] TypeScript types — no `any`, interfaces for Pt/Dot/Spark
- [ ] Prefers-reduced-motion check
- [ ] Component is self-contained (no imports beyond React)
