---
name: test-strategy
context: fork
description: Test planning and strategy for projects of any size. Use when defining what to test, choosing test types, setting coverage goals, building test pyramids, or planning quality gates. Produces TEST-STRATEGY.md with prioritized test plan. Routes to Tester agent for execution.
---

# Test Strategy Skill

Define what to test, at what level, and why — before writing a single test. Strategy first, implementation second.

## 1. When to Apply This Skill

**Trigger conditions:**
- "What should we test?"
- "Create a test plan for this feature"
- "We need a testing strategy"
- New project or major feature without existing test coverage
- Before a Tester agent handoff where scope is unclear

**Do not skip strategy** — writing tests without a plan leads to low-value tests that cover the wrong things.

## 2. The Test Pyramid

Map every test to the right level. Cost increases as you go up.

```
          ┌──────────┐
          │   E2E    │  ← Fewest: critical user journeys only
          │ (Slow)   │     5-10% of total tests
         ─┼──────────┼─
         │Integration │  ← Middle: API contracts, DB queries, service boundaries
         │ (Medium)   │     20-30% of total tests
        ─┼────────────┼─
        │    Unit      │  ← Most: pure functions, business logic, edge cases
        │   (Fast)     │     60-70% of total tests
        └──────────────┘
```

### Level Selection Rules

| Level | Test When | Do NOT Test |
|-------|-----------|-------------|
| **Unit** | Pure logic, calculations, transformations, validators, parsers | Framework glue, wrappers with no logic |
| **Integration** | DB queries, API endpoints, service interactions, auth flows | Simple CRUD with no business rules |
| **E2E** | Critical user journeys (login → action → result), payment flows | Every page variation, admin-only features |

## 3. Strategy Template

Produce this for every feature or project:

```markdown
# Test Strategy: {Feature Name}

## Risk Assessment
| Component | Risk Level | Why |
|-----------|-----------|-----|
| {component} | High/Med/Low | {data loss, revenue, security, UX} |

## Coverage Plan
| Layer | Target | What's Covered |
|-------|--------|----------------|
| Unit | {n} tests | {list of modules/functions} |
| Integration | {n} tests | {list of API/DB interactions} |
| E2E | {n} tests | {list of user journeys} |

## Priority Order (implement in this sequence)
1. {highest-risk component} — unit tests
2. {API contracts} — integration tests
3. {critical journey} — E2E test
4. ... remaining by descending risk

## Quality Gates
- [ ] All unit tests pass
- [ ] Integration tests pass with test DB
- [ ] E2E critical path passes
- [ ] Coverage ≥ {target}% on changed files
```

## 4. Risk-Based Prioritisation

Not all code deserves equal test investment. Prioritise by risk:

### High Risk (test thoroughly)
- Money/payment logic
- Authentication and authorisation
- Data mutations (writes, deletes, migrations)
- External API integrations
- Security-sensitive code (input validation, sanitisation)

### Medium Risk (test key paths)
- Business logic with branching conditions
- Data transformations and aggregations
- State management (complex reducers, stores)
- Error handling and recovery

### Low Risk (test selectively)
- Display components with no logic
- Configuration files
- Static content
- Simple pass-through functions

## 5. Coverage Goals

Set coverage targets by component risk, not a blanket number.

| Component Type | Minimum Coverage | Rationale |
|---------------|-----------------|-----------|
| Business logic / calculations | 90%+ | High cost of bugs |
| API endpoints / routes | 80%+ | Contract stability |
| Data access layer | 75%+ | Data integrity |
| UI components with logic | 70%+ | User-facing bugs |
| Utility functions | 85%+ | Widely reused |
| Configuration / glue code | — | Not worth unit testing |

## 6. Test Naming Convention

Every test name answers three questions:

```
test_{what}_{condition}_{expected_outcome}
```

Examples:
```python
def test_calculate_discount_with_expired_coupon_returns_zero():
def test_login_with_invalid_password_returns_401():
def test_export_csv_with_empty_dataset_creates_headers_only():
```

## 7. When to Update the Strategy

- New risk identified (security audit, incident, production bug)
- Architecture change (new service, DB migration, API version)
- Coverage drops below target on consecutive PRs
- Feature scope expands significantly

## 8. Anti-Patterns to Avoid

| Anti-Pattern | Problem | Fix |
|---|---|---|
| Testing implementation details | Brittle, breaks on refactor | Test behaviour and outputs |
| 100% coverage target | Leads to low-value tests | Risk-based targets per component |
| Only happy path | Misses edge cases that cause incidents | Add error/boundary tests per risk |
| Shared mutable state between tests | Flaky, order-dependent | Isolate with setup/teardown |
| Slow test suite | Developers skip running tests | Keep unit tests under 30s total |
| Testing mocked-only code | False confidence | Mix unit + integration testing |

## 9. Output Artefact

Produce `TEST-STRATEGY.md` in the project docs or agent-docs directory. Ensure it includes:
1. Risk assessment table
2. Coverage plan with test counts per layer
3. Priority order for implementation
4. Quality gate checklist
5. Named test cases for the top 10 highest-risk areas
