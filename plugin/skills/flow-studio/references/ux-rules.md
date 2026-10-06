# UX and design rules

The 10 rules ensure flow-studio pages remain readable, informative, accessible, and fast.

## The 10 rules

### 1. One screen
- **Rule statement:** The full flow fits on one screen without requiring panning in the initial default view.
- **Rationale:** A user must comprehend the entire topology before diving into specific components.
- **Pre-flight checklist question:** Did you check that the initial canvas fit scale is between 0.35 and 1.0 at standard desktop viewports (1600x900 and 1280x720)?
- **Common mistake & fix:** Authoring 80 expanded nodes in 15 lanes so text is unreadable at fit. *Fix:* Group sub-systems into collapsible groups with `contains` and `collapsed: true` to keep initial visible nodes under 30.

### 2. Left to right
- **Rule statement:** Primary flow and time progress left to right, never right to left.
- **Rationale:** Readers process sequential workflows and dependencies left to right; backward links create cognitive dissonance unless explicitly marked.
- **Pre-flight checklist question:** Did you check that all forward links connect earlier columns to later columns?
- **Common mistake & fix:** Drawing a return cycle with a standard forward arrow. *Fix:* Mark backward transitions as `kind: "loop-back"` so the router draws them under or over the main lane bands.

### 3. Named states
- **Rule statement:** States use plain domain words instead of raw enum strings or database codes.
- **Rationale:** Stakeholders and domain experts should understand node statuses without a translation glossary.
- **Pre-flight checklist question:** Did you check that state `word` fields display human-readable phrases like `READY`, `ON TIME`, or `DEGRADED` instead of `STATUS_200` or `ERR_412`?
- **Common mistake & fix:** Exporting raw database enums directly into the model. *Fix:* Map internal enums to friendly words in `states.<id>.word`.

### 4. Color carries meaning
- **Rule statement:** Semantic colors communicate health: green is healthy, amber is warning, red is critical, blue is accent.
- **Rationale:** Consistent visual coding allows immediate recognition of anomalies across diverse systems.
- **Pre-flight checklist question:** Did you check that green tones indicate operational health and red tones indicate SLA breaches or defects?
- **Common mistake & fix:** Styling informational cards with red or critical cards with blue. *Fix:* Use `tone: "ok"` for good, `tone: "warn"` for warning, `tone: "crit"` for critical, and `tone: "accent"` for active selection.

### 5. No orphans
- **Rule statement:** Every node connects to at least one other node unless explicitly marked.
- **Rationale:** Isolated nodes look like layout bugs or forgotten elements.
- **Pre-flight checklist question:** Did you check that every card has at least one incoming or outgoing link?
- **Common mistake & fix:** Forgetting to link an auxiliary service. *Fix:* Connect the service to its callers, or set `allowIsolated: true` if isolation is an intentional design choice.

### 6. Honest gaps
- **Rule statement:** If an architecture layer or data source is unverified, draw a visible gap band rather than guessing.
- **Rationale:** A diagram that fabricates missing systems causes dangerous production assumptions.
- **Pre-flight checklist question:** Did you check that undocumented lanes have `gap: true` and an explanatory note?
- **Common mistake & fix:** Omitting a legacy undocumented system or assuming its structure. *Fix:* Add the lane with `gap: true` and an amber dashed border to prompt clarification.

### 7. Inspector on demand
- **Rule statement:** The inspector side panel slides in on click and is never permanently open.
- **Rationale:** A permanent side panel robs the canvas of 340px of width and compromises the one-screen overview.
- **Pre-flight checklist question:** Did you check that the page loads with the inspector closed (`#inspector` hidden)?
- **Common mistake & fix:** Hardcoding the inspector to be permanently expanded on desktop. *Fix:* Leave `#inspector` closed until a user selects a node or card.

### 8. Two clicks to detail
- **Rule statement:** Any node reveals its upstream dependencies, downstream impact, and telemetry in at most two clicks.
- **Rationale:** Deep navigation trees frustrate operators during incident investigations.
- **Pre-flight checklist question:** Did you check that clicking a node opens the inspector, and clicking a relation tab highlights the full related subgraph?
- **Common mistake & fix:** Burying downstream connections behind nested menus or modal dialogs. *Fix:* Configure `inspector.relations` with `up` and `down` counts right at the top of the inspector.

### 9. Motion explains
- **Rule statement:** Animation represents data transit or status change, never mere cosmetic decoration.
- **Rationale:** Unnecessary movement distracts users and triggers motion sickness.
- **Pre-flight checklist question:** Did you check that running animations (`flow`, `breathe`, `failflash`) reflect active scenarios, degradation, or SLA breaches?
- **Common mistake & fix:** Adding infinite spinning rings to inactive cards. *Fix:* Reserve `animation: flow` for active links, `breathe` for warning cards, and respect `prefers-reduced-motion`.

### 10. Dark mode first-class
- **Rule statement:** Every color token has a manually tuned dark value, not an automatic browser filter inversion.
- **Rationale:** Inverted canvases distort data colors, destroy contrast, and wash out delicate edge lines.
- **Pre-flight checklist question:** Did you check that all text and badge contrasts meet WCAG AA (>= 4.5:1) in both light and dark themes?
- **Common mistake & fix:** Relying on `filter: invert(1)` which turns warning amber into unusable purple. *Fix:* Define distinct semantic variables in `:root[data-theme="dark"]`.

---

## Pre-flight checklist for agents

Before presenting a generated flow page, verify:
1. **Fit:** Open the page in a browser at 1600x900. Does the full diagram fit within the viewport without horizontal scrollbars?
2. **Zero overlaps:** Ensure zero node-to-node box intersections and zero node-over-lane-title collisions.
3. **No text truncation:** Do titles fit within card bounds? Are long labels handled with word-break or ellipsis?
4. **Lane ownership:** Does every row correspond to an identifiable owner, service, or system?
5. **No dead links:** Does every link id point to existing, valid node ids?
6. **Accessible names:** Does every button, input, tab, and control have an `aria-label` or visible text?
7. **Keyboard navigation:** Can a user Tab through controls and press Escape to close the inspector?
8. **Responsive breakdown:** Does the layout degrade cleanly down to 820x900?

---

## Common mistakes and fixes

- **Orphan nodes:** A node sits with no connecting edges. *Fix:* Add the missing connection or set `allowIsolated: true`.
- **Unreadable first view:** Diagram has 70 nodes rendered simultaneously. *Fix:* Collapse secondary clusters into groups with `contains: [...]` and `collapsed: true`.
- **Overlapping lanes:** Free-form node coordinates push nodes into neighboring lane regions. *Fix:* Ensure node Y coordinates plus heights stay within lane boundaries.
- **Text spill:** Node labels exceed card width. *Fix:* Use short titles (under 24 characters) and set `subtitle` for auxiliary metadata.
- **Permanent side panel:** The inspector remains open on load. *Fix:* The inspector must start closed and open only on selection.
- **Flat visual hierarchy:** Every card looks identical. *Fix:* Vary card kinds (`card`, `group`, `gateway`, `chip`) and state tones (`ok`, `warn`, `crit`, `accent`).
- **Unlabelled controls:** Icon buttons without text lack screen reader descriptions. *Fix:* Provide descriptive `aria-label` attributes on all buttons.
