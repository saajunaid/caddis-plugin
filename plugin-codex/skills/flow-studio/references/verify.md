# Verification harness reference

`scripts/check.mjs` is the automated headless browser testing harness for flow-studio pages. It drives Chromium via Playwright, interrogates page geometry and accessibility trees, tests user interactions, and asserts visual and behavioral invariants.

## 1. CLI usage and options

```bash
# Run against a local build
node scripts/check.mjs out/lineage.html

# Run with custom output directory and viewports
node scripts/check.mjs out/lineage.html --out check-out --viewports 1600x900,1280x720,820x900

# Specify browser channel and skip optional groups
node scripts/check.mjs out/lineage.html --channel msedge --skip notes,playback,update,hostile

# Test hostile payload safety
node scripts/check.mjs out/lineage.html --hostile out/hostile.html --json report.json

# Skip performance benchmarking
node scripts/check.mjs out/lineage.html --skip-perf
```

### CLI options
- `<page.html | URL>`: File path or HTTP URL to the target page.
- `--out <dir>`: Directory where screenshots and failure captures are saved (default: `check-out`).
- `--viewports <WxH,...>`: Comma-separated list of test viewports (default: `1600x900,1280x720,820x900`).
- `--channel <name>`: Browser executable channel (e.g. `msedge`, `chrome`).
- `--skip <groups>`: Comma-separated list of test groups to skip (`notes`, `playback`, `update`, `hostile`). A skipped group is not a pass: skip one only when the page intentionally omits that feature, and record every skip in your verification notes.
- `--hostile <file.html>`: Path to hostile test page to assert XSS and injection resistance.
- `--json <file.json>`: Output machine-readable test results to a JSON report.
- `--skip-perf`: Omit render and zoom frame timing performance assertions.

---

## 2. Check groups and assertions

`scripts/check.mjs` organizes assertions into distinct groups:

### 1. `structural`
Validates that layout geometry satisfies visual clarity:
- **Zero node-box intersections:** No two node bounding boxes overlap or intersect.
- **Node inside lane:** Every node sits completely within its designated swimlane boundaries.
- **No lane overlap:** Swimlanes do not collide vertically.
- **Links touch node boxes:** Link start points and end points connect cleanly to their endpoint boxes without gaps or overshoots.
- **Fit shows every node:** Canvas auto-fit places all nodes fully within the visible viewport bounds.
- **Hidden nodes not painted:** Collapsed or view-filtered nodes have `visibility: hidden` and `opacity: 0`.

### 2. `interaction`
Validates user input, navigation, and state machines:
- **Wheel zoom & pan:** Canvas zooms centered on the mouse position; zoom is clamped between 0.25x and 2.5x.
- **Key navigation:** `0` fits canvas, arrow keys pan the viewport, `Escape` clears selection and closes the inspector.
- **Group expansion / collapse:** Clicking expand/collapse buttons toggles child visibility and updates visible node counts.
- **Node selection:** Clicking a node selects it, highlights connected edges, and slides open `#inspector`.
- **N-hop search:** Searching terms highlights matches and dims non-matching nodes; increasing hops expands the lit radius.
- **What-if simulation:** Clicking what-if buttons cascades simulated failure states through downstream dependents.
- **View switcher:** Toggling views displays only elements specified in `visibleIn`.

### 3. `a11y` (Accessibility)
Validates compliance with WCAG 2.2 AA standards:
- **Accessible names:** Every button, input, tab, and control has a non-empty `aria-label` or accessible text name.
- **Keyboard navigation:** Visible nodes receive focus via Tab; hidden nodes are not reachable via Tab. No keyboard traps.
- **Focus visibility:** Focused nodes display an active outline.
- **Contrast ratios:** Normal text has at least 4.5:1 contrast against surface backgrounds in both light and dark themes.
- **Table view:** An accessible `<table class="sources" id="tbl">` lists all visible graph nodes for screen reader users.
- **Reduced motion:** `prefers-reduced-motion` disables all transitions and animations, setting edge dashes static.

### 4. `safety`
Validates security against hostile content and network isolation:
- **No unhandled page errors:** Zero unhandled JavaScript exceptions in the console.
- **No external network requests:** Zero external HTTP/HTTPS requests (local and standalone execution).
- **Hostile string escaping:** Malicious HTML (`</script>`, `<img onerror=...>`, Unicode separators) is rendered as plain text without script execution or DOM injection.

### 5. `performance`
Validates responsiveness and frame timing:
- **First render time:** Initial canvas render of all nodes must complete in under 500 ms.
- **Frame budget:** 95th percentile wheel event handling time must be under 16 ms (60 fps threshold).
- **Self-contained bundle size:** Generated single-file HTML pages must stay under 300 KB.

### 6. `notes`
Validates the implementation notes drawer:
- In notes mode, numbered markers appear for every valid anchor.
- Hovering and clicking markers coordinates with drawer cards.

### 7. `playback`
Validates scenario animation:
- Stepping moves the active token along specified links in sequence.
- Decision gateways show branch choice buttons in step mode.
- SLA breaches trigger red counter highlighting and failure flash styling.

### 8. `update`
Validates live graph data updates:
- Calling `FlowStudio.update(newModel)` updates topology while preserving pan, zoom, and active selection.
- Invalid model updates preserve the previous valid DOM state and render `#banner` error notice.

### 9. `hostile`
Validates adversarial resistance:
- Ingests `examples/hostile.json` to prove the parser and inspector remain inert against script injection.

---

## 3. Thresholds and limits

| Metric / Check | Threshold | Rationale |
|---|---|---|
| First render duration | `< 500 ms` | Fast initial load experience |
| Wheel event latency (p95) | `< 16 ms` | Smooth 60fps pan and zoom interaction |
| Zoom range | `0.25` to `2.5` | Prevents disorientation from extreme zoom levels |
| Contrast ratio | `>= 4.5:1` | WCAG AA readability in light and dark modes |
| Node count guideline | `8` to `30` initial visible | Avoids visual clutter in default fit |
| HTML bundle size | `< 300 KB` | Portable, zero-dependency self-contained distribution |

---

## 4. Reading failures and fixing issues

When a check fails, the harness logs:
```text
FAIL  [structural] 1600x900 zero node-box intersections  crm-db/cdc-pipe
```
1. **Identify the group and viewport:** Here, `structural` at `1600x900`.
2. **Read the detail payload:** The detail string lists the offending nodes (`crm-db` and `cdc-pipe`).
3. **Inspect the screenshot:** Open `check-out/01-fit-1600x900.png` to inspect the visual collision.
4. **Apply the fix:** Adjust the column width or node row/slot positions in `model.json`, then re-run `node scripts/check.mjs`.
