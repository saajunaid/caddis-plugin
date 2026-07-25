---
name: mockup
description: Create framework-aware UI mockups with feasibility checks. Prevents wasted effort by validating that proposed designs work within the target framework's constraints.
---

# Mockup Skill

## Purpose

Create visual mockups (HTML/SVG) for UI features with **mandatory framework feasibility validation**. This skill exists because of a real incident: a beautiful HTML mockup was created for a Streamlit app using `position: fixed` — which doesn't work in Streamlit's DOM. 24 hours were wasted discovering this.

**This skill prevents that class of failure for ANY framework.**

---

## When to Use

- Creating a UI mockup for a proposed feature
- Visualizing a design before implementation
- Producing a reference artifact for implementing agents
- When `@ux-designer` routes mockup creation here

---

## Steps

### Step 1: Read Project Context

1. Read `project-config.md` → identify:
   - **Frontend framework** (Streamlit, React, Vue, Angular, Next.js, etc.)
   - **Brand colors** (from profile or placeholder values)
   - **CSS conventions** (scoping method, custom properties, etc.)
2. Read `copilot-instructions.md` → identify:
   - Existing component patterns
   - Framework-specific conventions already documented
3. If a `chain_id` is provided, read the Intent Document from `agent-docs/intents/`

### Step 2: Framework Feasibility Check (MANDATORY)

**Before creating ANY mockup, validate that the proposed design is feasible in the target framework.**

Run through this checklist:

| Check | Question | If NO |
|-------|----------|-------|
| **DOM Control** | Does the framework give you full control over the DOM? | Identify which HTML/CSS features are restricted |
| **Positioning** | Does `position: fixed/absolute` work as expected? | Document the limitation and alternative approach |
| **Custom HTML** | Can you inject arbitrary HTML/JS? | Identify the framework's component/extension API |
| **Event Handling** | Can you attach custom JS event listeners? | Document how events work in this framework |
| **Styling** | Can you use global CSS freely? | Document CSS scoping constraints |
| **Third-party Libraries** | Can you load external JS/CSS? | Check if air-gapped deployment restricts this |

#### Known Framework Constraints

| Framework | Key Constraints |
|-----------|----------------|
| **Streamlit** | No `position: fixed/absolute` (DOM wrapping breaks it). No arbitrary HTML injection without `components.html()` or `declare_component()`. CSS is scoped — use `st.container(key=)` + `.st-key-` selectors. No external CDN in air-gapped environments. |
| **React** | JSX required. CSS-in-JS or CSS Modules typical. Virtual DOM diffing may interfere with manual DOM manipulation. |
| **Vue** | Template syntax. Scoped styles by default. `v-html` for raw HTML but XSS risk. |
| **Gradio** | Similar DOM constraints to Streamlit. Limited CSS control. Use `gr.HTML()` for custom elements. |
| **Next.js** | SSR considerations. `useEffect` needed for client-only code. CSS Modules or Tailwind typical. |

> **If ANY constraint would prevent the proposed design from working:**
> 1. **STOP** — do not create a mockup that can't be implemented
> 2. **WARN** the user with specific details about what won't work and why
> 3. **PROPOSE ALTERNATIVES** that work within the framework's constraints
> 4. **Get confirmation** before proceeding with an alternative approach

### Step 3: Create the Mockup

**Output format**: HTML file (preferred for interactive mockups) or SVG (for static layouts)

**Requirements:**
- Use brand colors from `project-config.md` (never hardcode colors — use CSS custom properties)
- Include responsive behavior if applicable
- Add comments explaining key layout decisions
- If the mockup uses workarounds for framework constraints, document them clearly in comments

**HTML mockup template:**
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{Feature Name} — Mockup</title>
    <style>
        /* Brand colors from project-config.md */
        :root {
            --brand-primary: {<BRAND_PRIMARY>};
            --brand-dark: {<BRAND_DARK>};
            --brand-light: {<BRAND_LIGHT>};
            /* Additional colors from profile */
        }

        /* Mockup styles */
        /* ... */
    </style>
</head>
<body>
    <!-- MOCKUP: {Feature description} -->
    <!-- FRAMEWORK: {Target framework} -->
    <!-- CONSTRAINTS: {Any framework constraints that shaped this design} -->
    <!-- ALTERNATIVES: {If using a workaround, what was the original approach and why it wouldn't work} -->

    <!-- Mockup content -->
</body>
</html>
```

### Step 3b: Implementation-Annotated Mockup (MANDATORY for handoff to implementing agents)

When the mockup will be handed off to `@implement`, `@frontend-developer`, or `@streamlit-developer`, embed **implementation annotations** throughout the HTML so the implementing agent knows exactly what to build without guessing.

#### Annotation Types

Use these four comment patterns consistently:

**1. Component annotations** — Which framework component implements this visual element:
```html
<!-- React: <KpiFlipCard product="broadband" data={surveys.broadband}
     trendData={trend.historicalNPS.byProduct.broadband} /> -->
<!-- React: <ResponsiveContainer width="100%" height={260}>
     <AreaChart data={trendData}><Area type="monotone" dataKey="nps" ... /></AreaChart>
     </ResponsiveContainer> -->
<!-- React: import { ScoreChip, DeltaBadge, SparkBar, TrendDot } from '@/components/table-cells' -->
```

**2. Data source annotations** — Which JSON key / API response field provides the data:
```html
<!-- DATA-SOURCE: surveys.broadband.nps, surveys.broadband.responses -->
<!-- DATA-SOURCE: trend.historicalNPS.byProduct.broadband (array of monthly values) -->
<!-- DATA-SOURCE: ceoInsight.headline, ceoInsight.keyFindings[] (objects with title, detail) -->
```

**3. Implementation notes** — Broader guidance for the implementing agent:
```html
<!-- IMPLEMENTATION NOTE [DATA-SOURCE]: This section uses hardcoded mock values for
     layout reference. React implementation must fetch period-filtered data from the
     /api/nps/overview endpoint and compute all KPIs dynamically. -->
<!-- IMPLEMENTATION NOTE [CHART]: Use Recharts AreaChart with gradient fill.
     Spread CHART_DEFAULTS from chartTheme.ts. No axes/grid for sparkline variant. -->
<!-- IMPLEMENTATION NOTE [ANIMATION]: Use framer-motion rotateY for card flip.
     duration: 0.52, ease: [0.4, 0.2, 0.2, 1]. backfaceVisibility: "hidden". -->
```

**4. Styling annotations** — Which design tokens, CSS vars, or Tailwind classes to use:
```html
<!-- STYLE: bg-surface-card (var(--surface-card)), shadow-card, rounded-lg (var(--r-lg)) -->
<!-- STYLE: Fill color uses var(--status-red) for detractor, var(--status-green) for promoter -->
<!-- STYLE: Tailwind: text-ink-primary font-heading text-2xl font-bold -->
```

#### Annotation Placement Rules

1. Place **component annotations** directly above or inside the HTML element that the component replaces
2. Place **data source annotations** on the element that displays the data value
3. Place **implementation notes** at the top of each major section (tab, panel, card group)
4. Place **styling annotations** on elements where the visual appearance matters and the token name isn't obvious from the CSS
5. Every hardcoded value in the mockup (numbers, text, colors) that will be dynamic in production MUST have a data source annotation

#### Example: Annotated KPI Card

```html
<!-- React: <KpiFlipCard product="broadband" data={surveys.broadband}
     trendData={trend.historicalNPS.byProduct.broadband} color={COLORS.broadband} /> -->
<!-- DATA-SOURCE: surveys.broadband.nps (current score), surveys.broadband.responses (count) -->
<!-- STYLE: var(--surface-card) bg, var(--shadow-card) shadow, 3px left border using COLORS.broadband -->
<div class="kpi-card">
    <div class="kpi-score">+32</div>  <!-- DATA-SOURCE: surveys.broadband.nps -->
    <div class="kpi-delta">▲ 2.1</div>  <!-- DATA-SOURCE: deriveMom(trend.historicalNPS.byProduct.broadband) -->
    <div class="kpi-responses">1,247 responses</div>  <!-- DATA-SOURCE: surveys.broadband.responses -->
    <div class="sparkline">
        <!-- React: <Sparkline data={trend.historicalNPS.byProduct.broadband}
             color={COLORS.broadband} height={72} /> -->
        <!-- IMPLEMENTATION NOTE [CHART]: Recharts AreaChart, no axes/grid/tooltip,
             gradient fill from color at opacity 0.3 to opacity 0. -->
    </div>
</div>
```

#### Completeness Check

Before saving the mockup, verify:
- [ ] Every visual section has at least one **component annotation**
- [ ] Every dynamic value has a **data source annotation** with the exact JSON path
- [ ] Every chart/graph has an **implementation note** specifying the chart library and config
- [ ] The implementing agent can build the feature using ONLY the mockup + annotations (no guessing)

### Step 4: Write Artifact

1. Save the mockup file to `agent-docs/ux/mockups/{feature-slug}.html` (or `.svg`)
2. Add YAML header to a companion markdown file or embed as HTML comment:
   ```yaml
   agent: ux-designer
   created: {date}
   status: current
   chain_id: {chain_id if provided}
   approval: pending
   framework: {target framework}
   feasibility_warnings: {list any constraints encountered}
   ```
3. Update `agent-docs/ARTIFACTS.md` manifest with the new entry

### Step 5: Report

Provide:
- Path to the mockup file
- Framework feasibility summary (what was checked, any warnings)
- Implementation notes for the agent that will build this (which API/component to use, what CSS approach works)
- If alternatives were chosen, explain why the original approach wouldn't work

---

## Framework Feasibility Quick Reference

### Streamlit-Specific

| Want to do | Don't use | Instead use |
|-----------|-----------|-------------|
| Floating element (chat widget, FAB) | `position: fixed/absolute` | `declare_component()` with custom HTML/JS |
| Custom styled container | Global CSS | `st.container(key="name")` + `.st-key-name` selector |
| Modal/overlay | `z-index` + absolute positioning | `st.dialog()` (Streamlit 1.33+) or `st.modal()` |
| Sidebar content | Custom sidebar HTML | `st.sidebar` API |
| Custom header | Fixed position header | `st.container()` at top + CSS with `st.container(key=)` |
| External JavaScript | `<script src="cdn...">` | Bundle locally for air-gapped; use `components.html()` |

### React-Specific

| Want to do | Watch out for | Recommended approach |
|-----------|---------------|---------------------|
| Direct DOM manipulation | React re-renders will overwrite | Use refs (`useRef`) or state-driven rendering |
| Global styles | May conflict with component styles | CSS Modules, styled-components, or Tailwind |
| Third-party widgets | jQuery plugins fight React | Find React-native alternatives or wrap in `useEffect` |

---

## Important Notes

- This skill is designed to be loaded by `@ux-designer` or `@frontend-developer` agents
- The framework constraint tables should be extended as new frameworks and gotchas are discovered
- Always check `project-config.md` for the deployment environment — air-gapped deployments restrict external dependencies
