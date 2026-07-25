---
name: architecture-diagram
description: Generate dark-themed technical architecture diagrams as self-contained HTML/SVG files. No external libraries or render tools needed — just a browser. Use for software system architecture, cloud infrastructure, microservice topologies, and deployment diagrams.
source: NousResearch/hermes-agent
---

# Architecture Diagram

Generate professional dark-themed architecture diagrams as standalone HTML files with embedded SVG. Browser-only — no Graphviz, no Mermaid renderer, no server required.

**Not suitable for**: scientific subjects, physical objects, floor plans, hand-drawn aesthetics — use `excalidraw` or `draw-io` for those.

## When to Use

Load this skill when users ask for:
- System architecture or component diagrams
- Cloud infrastructure diagrams (AWS/Azure/GCP)
- Microservice topology maps
- API and database relationship diagrams
- Deployment diagrams

Complements `architecture-design` (planning/notation) — use that first, then use this skill to produce the rendered output artifact.

## Semantic Color System

Map every component to a type, then apply these colors consistently:

| Component Type | Stroke | Fill |
|----------------|--------|------|
| Frontend | `#22d3ee` | `rgba(8, 51, 68, 0.4)` |
| Backend / Service | `#34d399` | `rgba(6, 78, 59, 0.4)` |
| Database | `#a78bfa` | `rgba(76, 29, 149, 0.4)` |
| Cloud / AWS | `#fbbf24` | `rgba(120, 53, 15, 0.3)` |
| Security / Auth | `#fb7185` | `rgba(136, 19, 55, 0.4)` |
| Message Bus / Queue | `#fb923c` | `rgba(251, 146, 60, 0.3)` |
| External / Third-party | `#94a3b8` | `rgba(30, 41, 59, 0.5)` |

## Canvas & Typography

- **Background**: `#020617` (slate-950) with a 40px grid pattern using `rgba(148, 163, 184, 0.05)` lines
- **Font**: JetBrains Mono from Google Fonts (`wght@400;500;700`)
  - Component labels: 12px weight 500
  - Section/group titles: 14px weight 700
  - Annotations: 7–9px weight 400
- **Stroke width**: 1.5px on all component boxes

## SVG Structure Rules

### Render Order (critical)
Render in this exact sequence to avoid transparency bleed-through:
1. Background + grid
2. Region/security boundary containers (dashed)
3. **Connection arrows** ← must come before components
4. Component boxes
5. Component labels
6. Legend

### Double-Rect Masking (required for all component boxes)
Prevents arrow lines from showing through filled shapes:
```svg
<!-- 1. opaque background rect (clips arrow lines) -->
<rect x="X" y="Y" width="W" height="H" rx="6"
      fill="#020617" stroke="none"/>
<!-- 2. semi-transparent styled rect on top -->
<rect x="X" y="Y" width="W" height="H" rx="6"
      fill="FILL_COLOR" stroke="STROKE_COLOR" stroke-width="1.5"/>
<!-- 3. label -->
<text x="X+W/2" y="Y+H/2+4" text-anchor="middle"
      font-family="JetBrains Mono" font-size="12" font-weight="500"
      fill="STROKE_COLOR">Component Name</text>
```

### Arrowheads
Define in `<defs>`:
```svg
<defs>
  <marker id="arrow-cyan" markerWidth="8" markerHeight="6"
          refX="7" refY="3" orient="auto">
    <polygon points="0 0, 8 3, 0 6" fill="#22d3ee"/>
  </marker>
  <!-- repeat for each stroke color used -->
</defs>
```
Use `marker-end="url(#arrow-cyan)"` on connection lines.

### Security Boundaries & Regions
Use dashed strokes for grouping boxes:
```svg
<rect x="X" y="Y" width="W" height="H" rx="8"
      fill="rgba(251,113,133,0.05)" stroke="#fb7185"
      stroke-width="1" stroke-dasharray="6,3"/>
<text font-size="11" font-weight="700" fill="#fb7185" opacity="0.7">
  Security Zone
</text>
```

### Legend
Always position below all boundary boxes, never overlapping content:
```svg
<!-- Legend box -->
<rect x="20" y="BOTTOM+20" width="320" height="..." rx="6"
      fill="rgba(148,163,184,0.05)" stroke="rgba(148,163,184,0.2)" stroke-width="1"/>
<!-- Legend entries: color dot + label -->
<circle cx="36" cy="Y" r="5" fill="#22d3ee"/>
<text x="48" y="Y+4" fill="#94a3b8" font-size="10">Frontend</text>
```

## Output Format

Single self-contained HTML file:
```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Architecture — [System Name]</title>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
    body { margin: 0; background: #020617; display: flex; justify-content: center; padding: 24px; }
    svg { max-width: 100%; height: auto; }
  </style>
</head>
<body>
  <svg viewBox="0 0 WIDTH HEIGHT" xmlns="http://www.w3.org/2000/svg">
    <!-- defs: markers, grid pattern -->
    <!-- background + grid -->
    <!-- boundary containers -->
    <!-- connection arrows -->
    <!-- component boxes (double-rect) -->
    <!-- legend -->
  </svg>
</body>
</html>
```

## Sizing Guidelines

| Diagram complexity | viewBox width | Component box |
|--------------------|---------------|---------------|
| Simple (< 8 nodes) | 900px | 140 × 50px |
| Medium (8–20 nodes) | 1200px | 140 × 50px |
| Large (20+ nodes) | 1600px | 120 × 45px |

Minimum padding from SVG edge: 40px. Minimum gap between components: 30px.

## Checklist Before Saving

- [ ] All component boxes use double-rect masking
- [ ] Arrows are drawn before component boxes in SVG order
- [ ] Every component type uses its semantic color
- [ ] Legend present and positioned below all content
- [ ] Security/region boundaries use dashed strokes
- [ ] No external JS libraries (pure SVG + CSS only)
- [ ] JetBrains Mono loaded from Google Fonts CDN
- [ ] File is a single self-contained HTML — open in browser to verify
