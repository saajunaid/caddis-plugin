# Producing Reliable Excalidraw Diagrams

This reference ensures text never clips and arrows visibly connect to elements. Follow these rules for architecture, flowcharts, network, and ER diagrams. Use the brand color palette in this skill for all elements.

---

## 1. Text Sizing (No Clipping)

Excalidraw clips text to the element's `width` and `height`. If either is too small, labels are cut off.

### Rule

For every `type: "text"` element:

- **Width:** At least **max(line length) × fontSize × 0.7**, **plus 16–24px of horizontal padding**. Use the longest line in the string.
- **Height:** At least **fontSize × 1.2 × number of lines**, then round up and add **~10–20% extra** for vertical padding.
- **Do not** use a fixed small width (e.g. 180) for variable-length or long content.

### Formula

```text
lineLength   = max(length(line) for each line in text)
baseWidth    = lineLength * fontSize * 0.7
width        = ceil(baseWidth) + 16           // horizontal padding

baseHeight   = fontSize * 1.2 * numberOfLines
height       = ceil(baseHeight * 1.1)        // ~10% vertical padding
```

### Examples

1. Two-line feature label

- Text: `"Lane 2: New Feature\n@planner -> @implement -> @tester"` (two lines; longest line length 32).
- fontSize: 16.
- **Width (min):** `32 × 16 × 0.7 ≈ 358` → `≈ 374` after padding → **use 380+**.
- **Height (min):** `16 × 1.2 × 2 ≈ 38` → `≈ 42` after padding → **use 44+**.

2. Outcome label from workflow mental model

- Text: `"LANE 3 — PRD → Build"` (single line; length 22).
- fontSize: 14.
- **Width (min):** `22 × 14 × 0.7 ≈ 216` → `≈ 232` after padding → **use 240+**.
- **Height (min):** `14 × 1.2 × 1 ≈ 17` → `≈ 19` after padding → **use 22+**.

### Compatibility

Include on text elements: `originalText` (same as `text`) and `lineHeight`: 1.25.

---

## 2. Arrow Connections (Bindings)

Arrows that should **attach** to shapes must use `startBinding` and `endBinding` so they stick to the source and target elements. Unbound arrows can look disconnected.

### Binding structure

```json
{
  "elementId": "<id of the rectangle/ellipse/diamond>",
  "focus": 0.5,
  "gap": 0
}
```

- **elementId:** The `id` of the element to attach to.
- **focus:** Position along the edge (-1 to 1). Use 0.5 for center of edge.
- **gap:** Distance in pixels from the element edge (0 = flush).

### Example: Arrow from Box A to Box B

Box A has `id: "box-a"`, right edge at x = 280. Box B has `id: "box-b"`, left edge at x = 400. Arrow:

```json
{
  "id": "arrow-a-b",
  "type": "arrow",
  "x": 280,
  "y": 135,
  "width": 120,
  "height": 0,
  "points": [[0, 0], [120, 0]],
  "roundness": { "type": 2 },
  "startBinding": {
    "elementId": "box-a",
    "focus": 0.5,
    "gap": 0
  },
  "endBinding": {
    "elementId": "box-b",
    "focus": 0.5,
    "gap": 0
  }
}
```

### If not using bindings

Compute arrow `(x, y)` and `points` so the line runs **from the source shape edge to the target shape edge**. Arrow direction and length must match the intended flow (e.g. "YES → L3" means the arrow goes toward the L3 element).

---

## 3. Decision / Flow Direction

For decision diamonds or branch points:

- Each branch arrow must **point toward** the element that branch leads to.
- Place the label (e.g. YES, NO) next to the correct arrow.
- If using bindings, set `endBinding.elementId` to the target shape so the arrow attaches to it.

---

## Golden Template

A minimal working example with correct text sizing and bound arrows, using the brand palette, is in **`templates/reliable-flowchart.excalidraw`** in this skill. Use it as a starting point or reference for valid structure.
