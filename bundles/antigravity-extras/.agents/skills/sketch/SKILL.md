---
name: sketch
description: Generate 2-3 interactive HTML design variants to explore UI directions side-by-side before committing to production code. Use for early-stage design exploration, comparing layout approaches, or when asked to "sketch this screen" or "show me variants".
source: NousResearch/hermes-agent
---

# Sketch

Generate 2–3 contrasting interactive HTML mockups to explore design directions before committing. Produces a side-by-side comparison table with trade-offs and an opinionated recommendation.

**This is for exploration, not production.** For a polished, framework-feasibility-checked, implementation-annotated mockup ready for handoff, use `mockup` after a sketch direction is chosen.

## When to Use (vs. Alternatives)

| Use `sketch` when... | Use `mockup` when... |
|----------------------|----------------------|
| Exploring "what could this look like?" | A direction is chosen and needs implementation detail |
| Comparing layout or density stances | Need framework feasibility validation |
| Need 2–3 options to react to | Need component annotations + data source mapping |
| Early ideation, no locked design | Ready to hand off to a developer/agent |

## Process

### Step 1 — Intake (3 questions)

Before building anything, get:
1. **Feel / vibe** — what emotional response should this UI create? (e.g., "fast and focused", "warm and editorial", "clinical and precise")
2. **Visual references** — any sites, apps, or design systems they like? (Optional but valuable)
3. **Primary user action** — the ONE thing a user most needs to do on this screen

### Step 2 — Variants (2–3 files)

Build variants that take genuinely different **design stances**. Each variant should differ on at least one of:
- **Density**: compact vs airy
- **Emphasis**: what's visually dominant
- **Aesthetic**: minimal vs expressive, light vs dark
- **Layout**: sidebar vs top nav vs cards vs list
- **Hierarchy**: flat vs layered, single column vs multi-column

**Technical requirements for each variant:**
- Single self-contained HTML file (no build step, no external CSS files)
- Inline `<style>` only
- System fonts OR a single Google Font (`<link>` tag is fine)
- Tailwind CDN acceptable (`<script src="https://cdn.tailwindcss.com">`)
- Realistic content — no "Lorem ipsum", no "Button 1 / Button 2"
- Interactive elements: hover states, clickable links, simple state transitions
- Mobile-responsive (at minimum, don't break on narrow viewports)

**File naming:**
```
sketches/
├── 001-compact-dark/index.html
├── 002-airy-editorial/index.html
└── 003-card-grid/index.html
```

### Step 3 — Visual Verification

Before presenting, verify each file renders correctly by checking:
- No broken layouts or overflowing elements at 1280px and 375px viewport width
- Hover states work as intended
- Fonts load (or fallback gracefully)
- No obvious HTML syntax errors

### Step 4 — Head-to-Head Comparison

Present a comparison table, then give an opinionated recommendation:

```
| Dimension | Variant 1 (Compact Dark) | Variant 2 (Airy Editorial) | Variant 3 (Card Grid) |
|-----------|-------------------------|---------------------------|----------------------|
| Density | High — power-user feel | Low — breathing room | Medium |
| Primary action visibility | Buried in toolbar | Prominent hero CTA | Contextual per card |
| Mobile behavior | Degrades to hamburger | Scales cleanly | Wraps to 1-col |
| Closest brand reference | Linear / Cursor | Notion / Stripe | Airtable / Webflow |
| Best for | Productivity tools | Marketing/content | Data browsing |

RECOMMENDATION: Variant 2 — the airy editorial approach matches the "warm and focused"
feel from intake and gives the most implementation flexibility. Promote to /mockup when ready.
```

## Promoting a Sketch

When the user picks a direction, say:
> "Ready to promote this to a framework-ready mockup? Run `/mockup` — it'll add framework feasibility checks and implementation annotations for handoff."

## Anti-Patterns to Avoid

- **Generic AI defaults**: Inter font, blue primary color, shadcn card grid — make deliberate choices
- **Identical variants**: if two variants look similar, replace one with a genuinely different stance
- **Placeholder content**: "User Name", "Description here" — use realistic fake data
- **Throwaway code**: write it as if the winning variant might get promoted to production
- **Unverified output**: always check rendering before presenting

## Example Stances to Consider

| Stance | Visual signature |
|--------|-----------------|
| Brutalist minimal | System font, no shadows, hard borders, high contrast |
| Dark power-user | Near-black bg, monospace font, keyboard-first layout |
| Warm editorial | Serif heading, cream surface, generous whitespace |
| Card-first | Everything in rounded cards, strong hierarchy within each |
| Data-dense | Tight spacing, tabular layout, information-forward |
| Marketing | Large hero, gradient, bold typography, CTA-forward |
