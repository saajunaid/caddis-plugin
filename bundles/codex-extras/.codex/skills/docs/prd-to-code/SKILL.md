---
name: prd-to-code
context: fork
description: Transform PRD documents into working application code using a systematic 6-phase methodology. Use when starting projects from requirements or converting specs to implementation.
---

# PRD to Code Skill

Transform a Product Requirements Document into a fully functional application.

## When to Use
- User provides a PRD document
- User asks to "build from PRD" or "implement this PRD"
- User has requirements to implement

---

## Phase 1: Discovery

1. Read the PRD thoroughly
2. Extract: data models, API endpoints, UI components, integrations, security requirements
3. **Interrogate for gaps** — do not assume context. Ask about:
   - **The Core Problem**: Why are we building this now?
   - **Success Metrics**: How do we know it worked? (measurable KPIs)
   - **Constraints**: Budget, tech stack, timeline, compliance?
4. Ask clarifying questions if needed

### PRD Quality Check

Validate that the PRD uses concrete, measurable criteria:

```diff
# Vague (BAD) — reject or clarify
- The search should be fast and return relevant results.
- The UI must look modern and be easy to use.

# Concrete (GOOD) — proceed with implementation
+ The search must return results within 200ms for a 10k record dataset.
+ The UI must follow the design system and achieve 100% Lighthouse Accessibility score.
```

**Output**: Structured PRD summary with features, models, APIs, components.

## Phase 2: Architecture & Scoping

1. Create architecture diagram (Mermaid)
2. Define project structure
3. Plan database schema
4. Identify shared libraries to use
5. **Define Non-Goals** — explicitly list what is NOT being built to protect the timeline
6. **Map User Flows** — trace paths through the system for each persona

```
project/
├── app/              # Frontend
│   ├── pages/
│   ├── components/
│   └── services/
├── backend/          # API layer
│   ├── routers/
│   ├── models/
│   └── services/
└── tests/
```

## Phase 3: Implementation Planning
Break into ordered tasks: Foundation -> Backend -> Frontend -> Integration

## Phase 4: Execution
- Set up foundation (structure, config, DB connection)
- Implement backend (models -> repositories -> services -> routers)
- Implement frontend (components -> pages -> integration)
- Apply standards: type hints, logging, parameterized queries, tests

**Checkpoint after each component**: run tests, check errors, commit.

## Phase 5: Validation
- Requirement verification checklist
- Run all tests (`pytest --cov`)
- Manual testing (happy path, errors, edge cases)
- Code quality: no secrets, SQL parameterized, proper error handling

## Phase 6: Completion

```markdown
## Implementation Summary
### What Was Built
### Files Created
### How to Run
### Testing
### Future Improvements
```

---

## PRD Section Reference

When analyzing a PRD, ensure these sections are present or extracted:

1. **Executive Summary** — Problem statement, proposed solution, 3-5 measurable KPIs
2. **User Experience** — Personas, user stories (`As a [user], I want to [action] so that [benefit]`), acceptance criteria, non-goals
3. **Technical Specifications** — Architecture overview, integration points, security & privacy
4. **AI System Requirements** (if applicable) — Tools, APIs, evaluation strategy
5. **Risks & Roadmap** — Phased rollout (MVP → v1.1 → v2.0), technical risks

## Implementation Guidelines

### DO
- **Define Testing**: Specify how to validate output quality before building
- **Iterate**: Present a draft and ask for feedback on specific sections
- **Label unknowns**: If the PRD doesn't specify tech stack or constraints, label as `TBD`

### DON'T
- **Skip Discovery**: Never start coding without asking at least 2 clarifying questions
- **Hallucinate Constraints**: If the user didn't specify details, ask — don't guess

---

## Checklist
- [ ] PRD fully analyzed and summarized
- [ ] Vague requirements converted to measurable criteria
- [ ] Non-goals explicitly defined
- [ ] Architecture designed with diagrams
- [ ] Tasks broken down and prioritized
- [ ] Each feature implemented with tests
- [ ] All requirements verified
- [ ] Documentation complete
