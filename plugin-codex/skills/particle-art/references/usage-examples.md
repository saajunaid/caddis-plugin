# Particle Art — Usage Examples

Real configurations with descriptions of what they produce. Use these as a reference before
delivering a component to verify your output looks right.

---

## Example 1 — Lowercase "j" brand mark (NodeJ.tsx)

**Shape:** Single letter "j"  
**Style:** spring-nodes  
**Size:** 300px  
**Colors:** CSS vars (dark: teal mint, light: dark teal)  
**Interaction:** repel

### What it produces
- 13 stem nodes stacked vertically, centered horizontally
- 9 hook nodes curving left and back up via cubic bezier
- 1 tittle node at the top with a slow pulsing ring
- 16 ambient halo nodes floating in an elliptical orbit around the letter
- On mouse hover: nodes scatter outward, spring back smoothly when cursor leaves
- The letter shape is always visible even during mouse scatter — spring force is strong enough

### Physics values used
```ts
const LINK = 72;
const FRICTION = 0.88;      // strong damping for letter nodes
const AMBIENT_FRICTION = 0.985;
const REPEL_R = 85;
const REPEL_F = 0.5;
const DRIFT = 0.06;
```

### Bezier hook definition
```ts
const P0 = [cx, stemBot];
const P1 = [cx, stemBot + size * 0.115];      // control: extend down
const P2 = [cx - size * 0.115, stemBot + size * 0.145]; // control: curve left
const P3 = [cx - size * 0.155, stemBot + size * 0.040]; // end: curl back up
```

---

## Example 2 — Abstract neural node cloud (NodeCluster.tsx)

**Shape:** abstract (no fixed targets)  
**Style:** spring-nodes (ambient only)  
**Size:** 360px  
**Colors:** CSS vars  
**Interaction:** repel

### What it produces
- 32 free-floating nodes with mild random drift
- Dense connection web — links form and break as nodes wander
- Mouse sends nodes scattering; they slowly drift back
- No fixed shape — pure kinetic energy

### Physics values used
```ts
const N = 32;
const LINK = 82;
const MAX_SPEED = 1.5;
const FRICTION = 0.984;
const REPEL_R = 90;
const REPEL_F = 0.55;
```

---

## Example 3 — Stipple halftone dot portrait (StippleGlyph.tsx)

**Shape:** Gaussian density grid  
**Style:** stipple  
**Size:** determined by COLS × ROWS (not a fixed px size)  
**Colors:** CSS vars  
**Interaction:** none (scan wave + breathing)

### What it produces
- 26 × 20 = 520 Unicode character spans (●, •, ·)
- Gaussian falloff: dense ● at centre, dispersing · at edges
- Scan wave sweeps outward every 8 seconds (480 frames @ 60fps)
- Each dot has an independent breathing oscillation (opacity 0.04–0.14 amplitude)
- ✦ glyph floats above the grid, pulsing gently

### GRID construction
```ts
const base = Math.exp(-(dist * dist) / (2 * 0.28 * 0.28));
const jitter = srand(xi * 53, yi * 97) * 0.12 - 0.06;
v = clamp(base + jitter, 0, 1);
```

---

## Example 4 — Gaussian dot field with sparks (DotField.tsx)

**Shape:** abstract Gaussian cloud  
**Style:** dot-field  
**Size:** 260px  
**Colors:** CSS vars (inner → --accent-strong, outer → --accent-soft)  
**Interaction:** repel + spring-back

### What it produces
- 120 canvas dots, Box-Muller distributed around centre (σ = 0.28)
- Inner dots bright (accent-strong), outer dots dim (accent-soft), linearly blended
- Sparks: 1.2% chance per frame to spawn a tiny bright dot near centre that drifts outward and fades
- Max 8 concurrent sparks
- Mouse pushes nearest dots away; they spring back at 8% per frame (gradual, elastic feel)
- ✦ as an HTML span centered over canvas (stays crisp, scales independently)

### Colour blend
```ts
const t = Math.min(1, d.distRatio * 1.6);
const r = sr + (lr - sr) * t;   // interpolate R
const g = sg + (lg - sg) * t;   // interpolate G
const b = sb + (lb - sb) * t;   // interpolate B
```

---

## Example 5 — "JS" initials (using shape-sampler sampleText)

**Shape:** text "JS"  
**Style:** spring-nodes  
**Size:** 380px  

```tsx
// In buildTargets():
const pts = sampleText("JS", size, { nodeCount: 40, font: "bold 160px sans-serif" });
return pts.map(([tx, ty]) => ({
  tx, ty, spring: 0.030, r: 2.0, alpha: 0.88, isDot: false
}));
// Add ambient: ambientCount={10}
```

**Physics:** use Short word row from SKILL.md table (spring 0.030, friction 0.90)

---

## Example 6 — Constellation preset

**Shape:** constellation  
**Style:** spring-nodes  
**Size:** 340px  

```tsx
import { sampleConstellation } from "./shape-sampler";

function buildTargets(size: number) {
  return sampleConstellation(size, 32).map(([tx, ty]) => ({
    tx, ty, spring: 0.012, r: 1.8, alpha: 0.75, isDot: false
  }));
}
// ambientCount={6}, LINK=90, FRICTION=0.94
```

Produces a loose ring of 20 outer nodes + 12 inner cluster nodes.
Nodes drift slowly (low spring 0.012), giving a star-field feel.

---

---

## Example 7 — Stipple Morph (StippleMorph.tsx)

**Shape:** Halftone cloud → letter "j" on hover  
**Style:** stipple-morph  
**Size:** determined by COLS × ROWS  
**Colors:** CSS vars (--accent-strong)  
**Interaction:** mousemove → cloud resolves into letter; mouseleave → drifts back

### What it produces
- 24 × 18 = 432 Unicode dot spans, each with an independently computed opacity
- Idle: Gaussian cloud + breathing oscillation + scan wave sweep every 8 seconds
- Hover: dots rearrange opacity to match a letter sampled from an off-screen canvas (Grid B)
- Morph lerps at 0.045/frame — smooth 1-second transition
- Grid B oversamples at 8× (192 × 144 px) and averages per cell, then boosts contrast ×2.2
- Breathing amplitude fades to 15% at full morph so the letter reads clearly

### Tunable constants
```ts
const COLS = 24, ROWS = 18;   // increase for denser dot field
const SCAN_PERIOD = 480;       // frames between scan sweeps
const MORPH_SPEED = 0.045;     // lerp rate per frame; 0.03 = slower, dreamier

function buildLetterGrid(text: string) {
  const S = 8; // oversample factor; 6–10 works well
  // font sizing auto-fits one character; for multi-char reduce to COLS*S*0.35
}
```

### Import and usage
```tsx
import { StippleMorphArt } from "@/components/art/StippleMorph";

<StippleMorphArt text="j" />           // single character
<StippleMorphArt text="JS" />          // initials (auto-sizes font)
<StippleMorphArt text="AI" className="mt-4" />
```

---

## Example 8 — Trail Ghost (TrailGhost.tsx)

**Shape:** Scattered cloud → letter "j" on hover  
**Style:** trail-ghost  
**Size:** 280px  
**Colors:** CSS vars  
**Interaction:** mousemove → nodes fly to letter leaving glowing smears; mouseleave → drift apart

### What it produces
- 23 letter nodes (same "j" bezier as NodeJ) starting scattered around centre
- 10 ambient atmosphere nodes drifting in a loose orbit
- Each node records a trail of up to 50 positions per frame; each position fades at 0.91× per frame
- Canvas uses `fillStyle = "rgba(0,0,0,0.10)"` instead of `clearRect` — old frames decay naturally, creating ghosted smears
- On hover: spring force engages, nodes race toward targets trailing bright streaks
- Tittle node has extra pulsing glow ring when morph > 0.15

### Key technique — canvas persistence ghost
```ts
// Instead of: ctx.clearRect(0, 0, size, size)
ctx.fillStyle = "rgba(0,0,0,0.10)"; // 10% fill each frame → 10-frame decay
ctx.fillRect(0, 0, size, size);
```

### Tunable constants
```ts
const TRAIL_DECAY = 0.91;  // per-frame alpha multiplier: 0.80 = shorter, 0.96 = longer
const TRAIL_MAX   = 50;    // trail history length per node; increase for longer tails
const MORPH_SPEED = 0.05;  // faster snap than other components
const IDLE_FRICTION   = 0.984;
const ACTIVE_FRICTION = 0.88;
```

### Import and usage
```tsx
import { TrailGhostArt } from "@/components/art/TrailGhost";

<TrailGhostArt size={280} />
<TrailGhostArt size={360} />   // larger for hero sections
```

---

## Example 9 — Flow Field (FlowField.tsx)

**Shape:** Noise-driven particle streams → letter "j" on hover  
**Style:** flow-field  
**Size:** 280px  
**Colors:** CSS vars  
**Interaction:** mousemove → flow currents bend toward letter targets; mouseleave → particles disperse back into streams

### What it produces
- 23 letter particles + 22 ambient flow-only particles (45 total)
- Idle: all particles follow 2-octave value-noise angle field — organic river/smoke behaviour
- Hover: spring forces toward letter targets compete with flow field; morph controls the blend
  - At m=0: pure noise, particles wander freely
  - At m=1: 75% spring + 25% noise — letter forms with a residual alive quality
- Particles drawn as velocity-aligned streaks (tail length ∝ speed) — shows flow direction
- Edge wrapping (particle exits right → re-enters left) disabled during morph to let letter hold shape
- Ambient particles never spring; they perpetually flow

### 2D value noise implementation
```ts
function vnoise(x: number, y: number): number {
  // Smoothstep bilinear interpolation of sin-hashed corner values
  const ix = Math.floor(x), iy = Math.floor(y);
  const fx = x - ix, fy = y - iy;
  const ux = fx*fx*(3-2*fx), uy = fy*fy*(3-2*fy);
  const h = (a: number, b: number) => (Math.abs(Math.sin(a*127.1 + b*311.7)*43758.5453)) % 1;
  const aa=h(ix,iy), ba=h(ix+1,iy), ab=h(ix,iy+1), bb=h(ix+1,iy+1);
  return aa + (ba-aa)*ux + (ab-aa)*uy + (aa-ba-ab+bb)*ux*uy;
}
```

### Tunable constants
```ts
const FLOW_FORCE  = 0.06;   // noise field push: raise for wilder currents
const FRICTION    = 0.965;  // less damping than spring → particles glide
const MORPH_SPEED = 0.048;  // slightly slower than TrailGhost for dreamier assembly
const LINK        = 80;     // connection line threshold; lines strengthen as letter forms
```

### Import and usage
```tsx
import { FlowFieldArt } from "@/components/art/FlowField";

<FlowFieldArt size={280} />
<FlowFieldArt size={400} />   // larger = more visible noise patterns
```

---

## Placement Pattern (Next.js App Router hero section)

```tsx
// page.tsx (server component — no "use client")
import { MyArt } from "@/components/art/MyArt";

export default function Page() {
  return (
    <div className="flex flex-col lg:flex-row lg:items-center lg:gap-16">
      {/* Text content */}
      <div className="flex-1 min-w-0">
        <h1>...</h1>
      </div>

      {/* Art — desktop only, fades in after text */}
      <div
        className="hidden lg:flex shrink-0 items-center justify-center animate-fade-up"
        style={{ animationDelay: "0.35s" }}
      >
        <MyArt size={360} />
      </div>
    </div>
  );
}
```

The `hidden lg:flex` keeps the canvas off mobile where layout space is tight.
The `animate-fade-up` + delay staggers the art in after the headline text.
