---
name: anchor-review
context: fork
description: Single-model adversarial review technique — 3-lens analysis with confidence scoring and self-challenge
---

# Anchor Review Skill

## Purpose

Perform a rigorous adversarial review using a **single model** by systematically arguing both sides of every finding. This compensates for the lack of multi-model disagreement by forcing structured self-challenge.

Use this skill whenever you need high-confidence code review, fix verification, or implementation validation — especially for 🔴 findings, L-sized changes, hotfixes, or `@anchor` Evidence Bundles.

---

## The 3-Lens Review

Review every changed file through three adversarial lenses, **in order**. Each lens has a different goal and a different failure mode it's designed to catch.

### Lens 1: Correctness

> *"Does this code do what it claims to do?"*

| Check | How to Verify |
|-------|---------------|
| Logic matches spec/plan requirements | Cross-reference against plan/PRD |
| Edge cases handled (null, empty, zero, boundary) | Trace each input path mentally |
| Error paths return meaningful results | Read every `except`/`catch` block |
| State mutations are intentional | Check session state, database writes, file I/O |
| Return types match declared signatures | Verify type hints against actual returns |

### Lens 2: Security

> *"Can this code be exploited or leak data?"*

| Check | How to Verify |
|-------|---------------|
| SQL injection | All queries use `?` parameterization, no f-strings/format() |
| Secrets exposure | No hardcoded credentials; `.env` or pydantic-settings only |
| Input validation | User inputs validated before use (Pydantic, type checks) |
| PII in logs | `logger.*` calls don't include passwords, tokens, emails |
| Auth bypass | Protected routes check authentication before processing |

### Lens 3: Performance

> *"Will this code break under real-world load?"*

| Check | How to Verify |
|-------|---------------|
| N+1 queries | Database calls inside loops → batch instead |
| Unbounded collections | Lists/dicts that grow without limit → add caps |
| Missing caching | Expensive repeated calls → `@st.cache_data` or equivalent |
| Large IN clauses | SQL IN with >900 params → batch to 900 |
| Blocking operations | Long I/O in main thread → async or background |

---

## Confidence Scoring

Every finding gets a confidence level based on **how you verified it**:

| Confidence | Criteria | Action |
|------------|----------|--------|
| **High** | Verified by running code (`run_command`), or reproduced the bug/vulnerability | Report as-is |
| **Medium** | Verified by code reading + pattern matching, but didn't execute | Report, note "not execution-verified" |
| **Low** | Suspected based on code smell, but could be intentional | Report as 🟡 suggestion, not 🔴 |

**Rule:** Never report a 🔴 Critical Issue with Low confidence. Either verify it to Medium+ or downgrade to 🟡.

---

## Self-Challenge Protocol

After completing all 3 lenses, **before finalizing your review**, run this self-challenge:

### Step 1: Challenge Every 🔴

For each Critical Issue you found:

```markdown
**Finding:** [your 🔴 finding]
**Devil's advocate:** [argue why this might be CORRECT or INTENTIONAL]
**Evidence check:** [did you verify with run_command, grep, or code reading?]
**Verdict:** [CONFIRMED 🔴 | DOWNGRADED to 🟡 | WITHDRAWN]
```

### Step 2: Check for Blind Spots

Ask yourself these three questions:
1. **"What did I NOT check?"** — List any files or paths you skipped
2. **"Is there a project convention that explains this pattern?"** — Search the codebase for 2-3 similar patterns before flagging something as wrong
3. **"Would this finding survive a second reviewer?"** — If another model saw your finding, would they agree or push back?

### Step 3: Final Verdict

Only after self-challenge, produce your final finding list. Include the confidence level on each:

```markdown
## Findings

### 🔴 Critical [Confidence: High]
**File:** `path/to/file.py` L42-58
**Issue:** [description]
**Self-challenge result:** Confirmed — [reason it survived challenge]

### 🟡 Warning [Confidence: Medium]
**File:** `path/to/file.py` L15
**Issue:** [description]
**Note:** Not execution-verified — based on code reading
```

---

## When to Use This Skill

| Agent | When to Load |
|-------|-------------|
| `@code-reviewer` | All reviews — especially 🔴 findings or L-sized changes |
| `@anchor` | Phase 4 verification — validate Evidence Bundle claims |
| `@implement` | Post-implementation self-review before handoff |
| `@debug` | Fix verification — confirm the fix doesn't introduce new issues |

---

## Quick Reference

```
1. LENS 1: Correctness  — Does it do what it claims?
2. LENS 2: Security     — Can it be exploited?
3. LENS 3: Performance  — Will it break under load?
4. SCORE each finding   — High / Medium / Low confidence
5. SELF-CHALLENGE       — Devil's advocate every 🔴
6. FINALIZE             — Only confirmed findings survive
```
