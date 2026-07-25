---
name: ui-review
description: Review UI implementations against design requirements, accessibility standards (WCAG 2.2 AA), and brand guidelines. Use when reviewing designs or validating UI before release.
---

# UI Review Skill

## When to Use
- Reviewing a UI implementation
- Checking accessibility compliance
- Validating brand consistency
- Before releasing new UI features
- Finding and fixing design issues in running websites

## Scope of Application
- Static sites (HTML/CSS/JS)
- SPA frameworks (React, Vue, Angular, Svelte)
- Full-stack frameworks (Next.js, Nuxt, SvelteKit)
- Any web application (local dev, staging, or production)

---

## Steps

### Step 0: Information Gathering

Before reviewing, understand the project context:

| Item | What to Determine |
|------|-------------------|
| Framework | React, Vue, Next.js, etc. |
| Styling Method | CSS, SCSS, Tailwind, CSS-in-JS, CSS Modules |
| Source Location | Where style files and components live |
| Review Scope | Specific pages or entire site |

Detect automatically from workspace files when possible (`package.json`, `tailwind.config.*`, `next.config.*`, etc.).

**References:** For framework-specific fix patterns see `references/framework-fixes.md`. For a detailed visual checklist see `references/visual-checklist.md`.

### Step 1: Capture Current State
Document: Screenshot/URL, purpose, target users, requirements.

### Step 2: Visual Design Review

#### Brand Compliance
- [ ] Primary color (`<BRAND_PRIMARY>`) used for CTAs and accents
- [ ] Dark color (`<BRAND_DARK>`) used for text and headers
- [ ] Light color (`<BRAND_LIGHT>`) used for backgrounds
- [ ] 60-30-10 color rule followed
- [ ] No off-brand colors used

#### Typography
- [ ] Consistent font family
- [ ] Proper heading hierarchy (h1 -> h2 -> h3)
- [ ] Min 14px body text
- [ ] Text contrast meets WCAG AA (4.5:1)

#### Layout Issues to Detect

| Issue | Description | Severity |
|-------|-------------|----------|
| Element Overflow | Content overflows parent or viewport | High |
| Element Overlap | Unintended overlapping | High |
| Alignment Issues | Grid or flex alignment problems | Medium |
| Inconsistent Spacing | Padding/margin inconsistencies | Medium |
| Text Clipping | Long text not handled properly | Medium |
| Font Inconsistency | Mixed font families | Medium |
| Color Inconsistency | Non-unified brand colors | Medium |

#### Layout
- [ ] Consistent spacing
- [ ] Visual hierarchy is clear
- [ ] Sufficient whitespace

### Step 3: Accessibility Review (WCAG 2.2 AA)

#### Perceivable
- [ ] Color contrast: text 4.5:1, large text 3:1, UI 3:1
- [ ] Color not sole means of communication
- [ ] Images have alt text

#### Operable
- [ ] All elements keyboard accessible
- [ ] Focus indicators visible
- [ ] Touch targets minimum 44px

#### Understandable
- [ ] Form labels descriptive
- [ ] Error messages clear
- [ ] Consistent navigation

### Step 4: Functionality Review
- [ ] Buttons trigger expected actions
- [ ] Forms validate correctly
- [ ] Error and success states display
- [ ] Loading states present
- [ ] Empty states handled
- [ ] Pagination works

### Step 5: Responsive Design Review
Test at these viewports:

| Name | Width | Representative Device |
|------|-------|----------------------|
| Mobile | 375px | iPhone SE/12 mini |
| Tablet | 768px | iPad |
| Laptop | 1024px | Standard laptop |
| Desktop | 1280px+ | Standard PC |
| Wide | 1920px | Large display |

Responsive issues to check:

| Issue | Description | Severity |
|-------|-------------|----------|
| Non-mobile Friendly | Layout breaks on small screens | High |
| Breakpoint Issues | Unnatural transitions at size changes | Medium |
| Touch Targets | Buttons/links too small on mobile (<44px) | Medium |

### Step 6: Generate Report

```markdown
## UI Review Report

| Aspect | Status | Score |
|--------|--------|-------|
| Visual Design | Pass/Issues/Fail | X/10 |
| Accessibility | Pass/Issues/Fail | X/10 |
| Functionality | Pass/Issues/Fail | X/10 |
| Responsive | Pass/Issues/Fail | X/10 |

### Issues Found
#### Critical (Must Fix)
#### Major (Should Fix)
#### Minor (Nice to Fix)

### Recommendations
```

## Issue Fix Workflow

When fixing issues found during review:

### Prioritization
- **P1 (Fix Immediately)**: Layout issues affecting functionality
- **P2 (Fix Next)**: Visual issues degrading UX
- **P3 (Fix If Possible)**: Minor visual inconsistencies

### Fix Principles
1. **Minimal Changes**: Only the minimum necessary to resolve the issue
2. **Respect Existing Patterns**: Follow the project's existing code style
3. **Avoid Breaking Changes**: Don't affect other areas
4. **One at a Time**: Fix one issue, verify, then move to the next

### Re-verification After Fixes
1. Reload the page (or wait for HMR)
2. Capture screenshots of fixed areas
3. Compare before and after
4. Verify fixes haven't caused regressions
5. If 3+ fix attempts fail for one issue, consult the user

## Troubleshooting

| Problem | Solutions |
|---------|----------|
| Style files not found | Check `package.json` deps; consider CSS-in-JS or build-time CSS |
| Fixes not reflected | Check HMR; clear cache; rebuild; check CSS specificity |
| Fixes affect other areas | Rollback; use more specific selectors; use scoped styles |

## Checklist
- [ ] Visual design reviewed against brand guidelines
- [ ] Accessibility audit completed (WCAG 2.2 AA)
- [ ] Functionality tested (happy path + errors)
- [ ] Responsive design verified at all viewports
- [ ] Report generated with scores and action items
- [ ] Fixes applied one at a time with verification
- [ ] No regressions introduced by fixes