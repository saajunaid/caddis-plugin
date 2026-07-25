---
name: draw-io
context: fork
description: draw.io diagram creation, editing, and review. Use for .drawio XML editing, PNG conversion, layout adjustment, and AWS icon usage.
---

# draw.io Diagram Skill

**Works with:** Any AI coding agent (Claude, Cursor, GitHub Copilot, Windsurf, etc.)

## Quick Reference

| Task | Command |
|------|---------|
| Convert to PNG | `bash scripts/convert-drawio-to-png.sh file.drawio` |
| Find AWS icon | `python scripts/find_aws_icon.py ec2` |
| List all icons | `python scripts/find_aws_icon.py --list-all` |
| Direct export | `drawio -x -f png -s 2 -t -o out.png in.drawio` |

## Core Rules

### File Handling
- Edit only `.drawio` files (XML format)
- Never edit `.drawio.png` directly
- Always verify PNG output after changes
- After edits, validate XML structure before handing off

### Fonts
- Set `defaultFontFamily` in `<mxGraphModel>` tag
- Set `fontFamily` in each text element's style
- Use 18px+ for presentations, 14px minimum

### Background
- Remove `background="#ffffff"` attribute
- Use `page="0"` for transparent background

### Arrows
- **Critical**: Place arrows after title, before other elements
- Maintain 20px clearance from labels
- Use explicit coordinates for text element connections
- For flow edges, set explicit arrowheads and stroke styling:
  - `endArrow=block;endFill=1`
  - `strokeColor=<visible color>;strokeWidth>=1`

### XML Structure (Critical)
- **Never nest `mxCell` inside another `mxCell`; all `mxCell` entries must be direct children of `<root>`.**
- **Edge labels must be separate sibling `mxCell` nodes with `parent` set to the edge id.**
- Keep only geometry/content tags (for example `mxGeometry`) inside a given `mxCell`.

### Viewport and Coordinates
- Use sane viewport defaults: keep `dx`/`dy` near 0.
- Ensure page dimensions cover the full drawing bounds (`pageWidth`/`pageHeight` large enough).
- Keep nodes/points in positive in-canvas coordinates unless there is an explicit reason not to.
- If a diagram opens off-screen, normalize coordinates and reset `dx`/`dy` before finalizing.

### Container Margins
- **Must**: 30px minimum margin from frame boundaries
- Calculate: element top ≥ frame.y + 30
- Calculate: element bottom ≤ frame.y + frame.height - 30

### Text Width
- English: ~10px per character + 20px padding
- For "Application Server" (18 chars): ~200px width

## XML Structure

```xml
<mxGraphModel defaultFontFamily="Arial" page="0">
  <!-- Title (always first) -->
  <mxCell id="title" value="Diagram Title" .../>
  
  <!-- Arrows (back layer) -->
  <mxCell id="arrow1" style="edgeStyle=..." edge="1">
    <mxGeometry relative="1">
      <mxPoint x="100" y="200" as="sourcePoint"/>
      <mxPoint x="500" y="200" as="targetPoint"/>
    </mxGeometry>
  </mxCell>
  
  <!-- Elements (front layer) -->
  <mxCell id="box1" .../>
</mxGraphModel>
```

## AWS Icons

Use latest `mxgraph.aws4.*` icons:

```xml
<!-- Resource icon -->
style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.ec2;"

<!-- Official names -->
value="Amazon ECS"  <!-- Not "ECS" -->
value="AWS Lambda"  <!-- Not "Lambda" -->
```

Find icons: `python scripts/find_aws_icon.py <service>`

## Layout Calculations

**Align elements vertically:**
```
Box 1: y=100, height=80 → center = y + h/2 = 140
Box 2: y=120, height=40 → center = y + h/2 = 140
Result: Aligned ✓
```

**Container margin check:**
```
Frame: y=20, height=400 → range 20-420
Element: y=50 → margin from top = 50-20 = 30px ✓
Element: y+h=390 → margin from bottom = 420-390 = 30px ✓
```

## Common Fixes

**Overlapping arrows:** Move arrow XML after title, before elements
**Text cut off:** Increase `width` in mxGeometry
**No PNG output:** Check `drawio --version`, install if missing
**Element overflow:** Verify 30px margins from container
**Could not add object for mxCell:** flatten malformed nested `mxCell` nodes into root-level siblings
**Diagram opens out of sight:** reset `dx`/`dy` close to 0 and move all key geometries to positive coordinates
**Arrows not visible:** add `endArrow=block;endFill=1` and explicit `strokeColor` on each flow edge

## Required Validation (Post-Edit)

Run these checks after every `.drawio` XML edit:

1. **Well-formed XML parse**
  - Parse the file with an XML parser and ensure no syntax errors.
2. **Nested-`mxCell` structural check**
  - Confirm no `mxCell` contains a child `mxCell`.
3. **Viewport/canvas sanity check**
  - Verify `dx`/`dy` are sane and geometry coordinates are not unintentionally far negative.
4. **Edge visibility check**
  - For flow diagrams, confirm edges include explicit arrowheads and visible stroke colors.
5. **Visual open test**
  - Open in draw.io and ensure diagram is visible at normal zoom without manual panning.

## Quality Checklist

- [ ] `page="0"` (no background)
- [ ] Font size 18px+ for presentations
- [ ] Arrows at back layer
- [ ] Flow edges use explicit arrowheads (`endArrow=block;endFill=1`) and visible stroke colors
- [ ] 30px+ margins from frames
- [ ] No nested `mxCell` nodes (all cells are root-level siblings)
- [ ] Edge labels are sibling `mxCell` nodes with `parent=<edge_id>`
- [ ] `dx`/`dy` near 0 and page size fits diagram bounds
- [ ] Main nodes/points are in positive in-canvas coordinates
- [ ] Official service names (Amazon ECS, AWS Lambda)
- [ ] Latest icons (aws4, not aws3)
- [ ] PNG visually verified

## Extended Documentation

See `references/` directory for:
- Layout patterns and best practices
- Complete AWS icon catalog
- Detailed troubleshooting
- CI/CD integration examples
