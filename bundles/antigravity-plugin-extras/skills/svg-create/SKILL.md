---
name: svg-create
context: fork
description: "Brand-themed SVG diagrams with consistent color palette and accessible design"
---

# SVG Creation Skill

Create professional SVG diagrams with consistent brand theming.

> **Project Context** — Read `project-config.md` in the repo root for brand tokens, color palette, and project metadata.

## When to Use

- Workflow diagrams and flowcharts
- Architecture diagrams
- Decision trees
- Process visualizations
- Quick reference cards
- Any visual that needs to be version-controlled

## SVG Best Practices

### Document Structure

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 600">
  <defs>
    <!-- Reusable styles and markers -->
    <style>
      .title { font: bold 24px 'Segoe UI', Arial, sans-serif; fill: #1F2937; }
      .text { font: 14px 'Segoe UI', Arial, sans-serif; fill: #374151; }
    </style>
    <marker id="arrow" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
      <polygon points="0 0, 10 3.5, 0 7" fill="#6B7280"/>
    </marker>
  </defs>
  
  <!-- Background -->
  <rect width="800" height="600" fill="white"/>
  
  <!-- Content here -->
</svg>
```

### Print-Friendly Design

**CRITICAL**: Always design for print compatibility:

```xml
<!-- ✅ GOOD: Light backgrounds for print -->
<rect fill="white"/>
<rect fill="#F8FAFC"/>  <!-- Very light gray -->
<rect fill="#ECFDF5"/>  <!-- Very light green -->

<!-- ❌ BAD: Dark backgrounds don't print well -->
<rect fill="#1F2937"/>  <!-- Dark navy - avoid -->
<rect fill="black"/>     <!-- Never for large areas -->
```

### Color Palette

```xml
<!-- Primary Colors -->
#E10A0A    <!-- Primary Red - primary accent -->
#1F2937    <!-- Navy - text only, not backgrounds -->

<!-- Scenario Colors (use light fills) -->
#ECFDF5    <!-- Light green - new/create -->
#10B981    <!-- Green - borders/accents -->
#EEF2FF    <!-- Light indigo - existing/continue -->
#6366F1    <!-- Indigo - borders/accents -->
#F0F9FF    <!-- Light blue - simple/quick -->
#0EA5E9    <!-- Blue - borders/accents -->
#FFF7ED    <!-- Light orange - warning/emergency -->
#F97316    <!-- Orange - borders/accents -->
#FEF3C7    <!-- Light yellow - help/info -->
#F59E0B    <!-- Amber - borders/accents -->

<!-- Neutral Colors -->
#374151    <!-- Text color -->
#6B7280    <!-- Secondary text -->
#E5E7EB    <!-- Light border -->
#F8FAFC    <!-- Light background -->
```

### Common Patterns

#### Numbered Steps

```xml
<!-- Step circle with number -->
<circle cx="50" cy="100" r="18" fill="#10B981"/>
<text x="50" y="106" text-anchor="middle" fill="white" 
      font-weight="bold" font-size="16">1</text>
```

#### Connection Arrows

```xml
<!-- Define marker in <defs> first -->
<marker id="arrow" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
  <polygon points="0 0, 10 3.5, 0 7" fill="#6B7280"/>
</marker>

<!-- Use the arrow -->
<line x1="100" y1="50" x2="100" y2="100" stroke="#6B7280" 
      stroke-width="2" marker-end="url(#arrow)"/>
```

#### Rounded Boxes

```xml
<!-- Container box -->
<rect x="30" y="80" width="400" height="200" rx="12" 
      fill="#ECFDF5" stroke="#10B981" stroke-width="2"/>

<!-- Content box -->
<rect x="50" y="100" width="360" height="40" rx="6" 
      fill="white" stroke="#10B981" stroke-width="1"/>
```

#### Text Styling

```xml
<!-- Title -->
<text x="400" y="40" text-anchor="middle" 
      font-size="24" font-weight="bold" fill="#1F2937">Title</text>

<!-- Monospace code -->
<text font-family="'Courier New', monospace" fill="#E10A0A">/command</text>

<!-- Agent reference -->
<text font-weight="bold" fill="#7C3AED">@agent-name</text>

<!-- File path -->
<text font-family="'Courier New', monospace" fill="#059669">plans/</text>
```

### Responsive ViewBox

Calculate viewBox from content:
- **Width**: Rightmost element + padding (usually 30-50px)
- **Height**: Bottom element + padding (usually 30-50px)

```xml
<!-- For 800x600 content with 30px padding -->
<svg viewBox="0 0 860 660">
```

### Font Stack

Always specify fallbacks:

```css
font-family: 'Segoe UI', Arial, sans-serif;  /* Text */
font-family: 'Courier New', monospace;        /* Code */
```

## Reliable Text & Layout (No Clipping)

To keep project diagrams sharp and readable (and avoid cropped text):

### Text box sizing

For a `<text>` block (optionally with `<tspan>` lines):

- `maxLineLen` = length of the longest line.
- `fontSize` = size in px.
- `lines` = number of lines.

Use:

```text
baseWidth   = maxLineLen * fontSize * 0.7
cardWidth   = ceil(baseWidth) + 16      // horizontal padding

baseHeight  = fontSize * 1.2 * lines
cardHeight  = ceil(baseHeight * 1.1)    // ~10% vertical padding
```

Size the surrounding `<rect>` to at least `cardWidth × cardHeight`. Do not let text touch the edges.

### clipPath usage

- Prefer simple rounded boxes without clipping.
- If you use `<clipPath>` for a lane or card:
  - Make the clip rect **larger** than the visible card by 8–12px on all sides.
  - Never set the clip rect tighter than the text block; otherwise labels like “More than ~5 files or new page/component/source?” will be cut.

### Card Example

```xml
<defs>
  <clipPath id="lane1-clip">
    <rect x="20" y="80" width="300" height="100" rx="8"/>
  </clipPath>
</defs>

<g clip-path="url(#lane1-clip)">
  <rect x="30" y="90" width="280" height="80" rx="8"
        fill="#ECFDF5" stroke="#10B981" stroke-width="2"/>
  <text x="170" y="116" text-anchor="middle" class="text">
    <tspan x="170" dy="0">Lane 1: Quick Fix</tspan>
    <tspan x="170" dy="18">~1 session, &lt;10 files</tspan>
  </text>
</g>
```

The `lane1-clip` rectangle is larger than the card, so text won’t clip even if it grows slightly.

## Checklist Before Creating

- [ ] Using white or very light fills for backgrounds
- [ ] Text is at least 11px for readability
- [ ] Text blocks have generous padding; no line touches card edges or clip paths
- [ ] Contrast ratio is print-safe
- [ ] ViewBox sized to content + padding
- [ ] Arrow markers defined in `<defs>`
- [ ] Font families have fallbacks
- [ ] File saved with `.svg` extension

## Example: Simple Flowchart

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200">
  <defs>
    <marker id="arrow" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
      <polygon points="0 0, 10 3.5, 0 7" fill="#6B7280"/>
    </marker>
  </defs>
  
  <rect width="400" height="200" fill="white"/>
  
  <!-- Start -->
  <rect x="20" y="80" width="100" height="40" rx="8" fill="#ECFDF5" stroke="#10B981" stroke-width="2"/>
  <text x="70" y="105" text-anchor="middle" fill="#374151">Start</text>
  
  <!-- Arrow -->
  <line x1="120" y1="100" x2="170" y2="100" stroke="#6B7280" stroke-width="2" marker-end="url(#arrow)"/>
  
  <!-- End -->
  <rect x="180" y="80" width="100" height="40" rx="8" fill="#EEF2FF" stroke="#6366F1" stroke-width="2"/>
  <text x="230" y="105" text-anchor="middle" fill="#374151">End</text>
</svg>
```

## Related Resources

- Agent: `@svg-diagram` - For complex, multi-element diagrams
- Tool: Mermaid - For quick code-based diagrams (then export to SVG)
