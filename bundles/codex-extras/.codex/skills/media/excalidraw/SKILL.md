---
name: excalidraw
context: fork
description: "Brand-themed Excalidraw diagrams for project documentation"
---

# Excalidraw Diagram Generation

Generate `.excalidraw` JSON files for architecture, flowcharts, and whiteboard-style diagrams using consistent brand theming.

> **Project Context** — Read `project-config.md` in the repo root for brand tokens, color palette, and project metadata.

Use these colors for diagrams that appear in project docs, runbooks, or architecture artifacts.

## When to Use

- Creating architecture or system design diagrams for systems
- Drawing flowcharts or decision trees for internal processes
- Building mind maps or relationship diagrams with brand theming
- Producing whiteboard visuals for project documentation

## Supported Diagram Types

| Type           | Use Case                              |
|----------------|---------------------------------------|
| Flowchart      | Processes, decision trees             |
| Architecture   | System components, microservices      |
| Mind Map       | Concept hierarchies, brainstorming    |
| Relationship   | Entity relationships, data models     |
| Sequence       | Message flows, interactions           |

## Phase 1: Plan Layout

### Spacing

| Context                     | Pixels  |
|-----------------------------|---------|
| Horizontal gap              | 200-300 |
| Vertical gap                | 100-150 |
| Canvas margin               | 50+     |
| Arrow clearance             | 20-30   |

### Brand Color Palette

| Role            | Hex        | Use |
|-----------------|------------|-----|
| Primary entity  | `#E10A0A`  | Primary Red — main components, CTAs |
| Process step    | `#ECFDF5`  | Light green fill (border #10B981) |
| Key / central   | `#FEF3C7`  | Light yellow (border #F59E0B) |
| Warning / error | `#FFF7ED`  | Light orange (border #F97316) |
| Background      | `#F8F9FA`  | Light background |
| Default stroke  | `#1F2937`  | Navy |

Keep total elements under 20 per diagram. Split larger systems.

## Phase 2: JSON Structure

Same as standard Excalidraw: `type`, `version`, `source`, `elements`, `appState`, `files`. Use brand palette hex values in `backgroundColor` and `strokeColor`.

```json
{
  "type": "excalidraw",
  "version": 2,
  "source": "https://excalidraw.com",
  "elements": [],
  "appState": {
    "viewBackgroundColor": "#F8F9FA",
    "gridSize": 20
  },
  "files": {}
}
```

## Phase 3: Element Types

Use rectangle, diamond, ellipse, arrow, and text. Apply brand colors from the table above.

### Rectangle (boxes, containers)

```json
{
  "id": "step-1", "type": "rectangle",
  "x": 100, "y": 100, "width": 200, "height": 80,
  "strokeColor": "#1F2937", "backgroundColor": "#ECFDF5",
  "fillStyle": "solid", "strokeWidth": 2, "roughness": 1,
  "opacity": 100, "roundness": { "type": 3 },
  "isDeleted": false, "locked": false
}
```

### Diamond (decisions)

```json
{ "id": "d1", "type": "diamond", "x": 200, "y": 100,
  "width": 140, "height": 140, "strokeColor": "#1F2937",
  "backgroundColor": "#FEF3C7" }
```

### Ellipse (start/end, states)

```json
{ "id": "start", "type": "ellipse", "x": 100, "y": 100,
  "width": 120, "height": 80, "strokeColor": "#1F2937",
  "backgroundColor": "#ECFDF5" }
```

### Arrow (connections)

```json
{
  "id": "a1", "type": "arrow",
  "x": 300, "y": 140, "width": 100, "height": 0,
  "points": [[0, 0], [100, 0]],
  "roundness": { "type": 2 },
  "strokeColor": "#1F2937",
  "startBinding": null, "endBinding": null
}
```

Directions: horizontal `[[0,0],[200,0]]`, vertical `[[0,0],[0,150]]`, diagonal `[[0,0],[200,150]]`.

**Arrow connections (mandatory):** Arrows that should attach to shapes must either **(A)** use `startBinding` and `endBinding` with `elementId` (and optional `focus`, `gap`) pointing at the source and target elements, or **(B)** be drawn so the arrow's start/end coordinates sit on the edges of the source and target shapes. Unbound arrows must run from source to target; direction and length must match the intended flow. See `references/reliable-diagrams.md` for binding structure and example.

### Text (labels, titles)

```json
{
  "id": "t1", "type": "text",
  "x": 100, "y": 50, "width": 300, "height": 36,
  "text": "System Architecture", "fontSize": 28,
  "fontFamily": 5, "textAlign": "center",
  "strokeColor": "#1F2937"
}
```

**Fonts (mandatory):** Use **Excalifont** as the default for all text (do not use Virgil). In JSON set `fontFamily`: **`5`** for Excalifont. Optionally, when your Excalidraw version or font picker supports them: use **Comic Shanns** for headings (e.g. diagram title, section labels); **Lilita One** for emphasis or important callouts; **Nunito** for legends and descriptive text. If a font is not available, fall back to Excalifont.

**Text sizing (mandatory):** For every `type: "text"` element, set `width` to at least **max(line length) × fontSize × 0.7 + 16px** and `height` to at least **fontSize × 1.2 × number of lines × 1.1**. This matches `references/reliable-diagrams.md` and adds horizontal and vertical padding so labels never clip. Never use a fixed small width for variable-length content — Excalidraw clips text to the element bounds.

**Text inside shapes:** Some Excalidraw versions do not render the `text` property when it is embedded on rectangle, ellipse, or diamond elements. For reliable labels, use **separate `type: "text"` elements** positioned inside the shape, with width/height sized as above. Include `originalText` and `lineHeight`: 1.25 on text elements for compatibility.

## Phase 4: Common Patterns

### Connected Boxes

Use bindings so arrows attach to boxes. Example: two rectangles with one arrow using `startBinding` and `endBinding`; see `templates/reliable-flowchart.excalidraw`.

### Decision Branch

Place a diamond, then arrows for each branch. **Each arrow must point toward the element that branch leads to**; place the label (e.g. YES, NO) next to the correct arrow. If using bindings, set `endBinding.elementId` to the target shape.

### Mind Map (Radial)

```
angle = (2 * PI * index) / branchCount
x = centerX + radius * cos(angle)
y = centerY + radius * sin(angle)
```

## Phase 5: Save and Open

Save as `<name>.excalidraw`. Open in excalidraw.com, VS Code Excalidraw extension, or Obsidian.

### Validation Checklist

- [ ] All IDs unique
- [ ] No overlapping elements
- [ ] Text readable (fontSize 16+); text elements have width/height sized so content is not clipped (see references/reliable-diagrams.md)
- [ ] Arrows connect logically: use bindings or draw arrows from source edge to target edge; direction matches flow
- [ ] Decision branches: each arrow points toward the correct target element
- [ ] Brand color scheme applied
- [ ] Valid JSON
- [ ] Under 20 total elements

## Quick Reference

| Element   | Type        | Key Properties                          |
|-----------|-------------|------------------------------------------|
| Box       | `rectangle` | x, y, width, height, backgroundColor    |
| Circle    | `ellipse`   | x, y, width, height                     |
| Decision  | `diamond`   | x, y, width (= height)                  |
| Arrow     | `arrow`     | x, y, points, startBinding, endBinding  |
| Label     | `text`      | x, y, text, fontSize, fontFamily (5 = Excalifont), width, height |

## Resources

All paths below are **within this skill** (self-contained). Do not reference generic or media Excalidraw assets.

- **Reliable diagrams (text sizing, arrow bindings):** see `references/reliable-diagrams.md`. Required for architecture, flowcharts, network, and ER diagrams.
- **Full element types and schema:** see `references/element-types.md` and `references/excalidraw-schema.md`.
- **Golden template (correct text + bound arrows, brand palette):** use `templates/reliable-flowchart.excalidraw` as a minimal working reference.
- **Other templates:** `templates/flowchart-template.excalidraw`, `templates/sequence-diagram-template.excalidraw`, and others in `templates/`.
- **Scripts:** if present in `scripts/` (e.g. add-arrow), use them with brand palette; see `scripts/README.md` when available.
