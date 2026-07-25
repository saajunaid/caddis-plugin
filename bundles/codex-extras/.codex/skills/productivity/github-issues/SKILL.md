---
name: github-issues
context: fork
description: Create well-structured GitHub issues with proper labels, descriptions, and acceptance criteria. Use when creating bug reports, feature requests, or tracking tasks.
---

# GitHub Issues Skill

Create clear, actionable GitHub issues that provide all necessary context.

## Trigger

Activate when:
- User asks to create an issue
- User reports a bug that needs tracking
- User wants to propose a feature
- User says "open an issue for..."

---

## Issue Types

Additional issue and PR body templates: `references/templates.md`.

### ðŸ› Bug Report

For unexpected behavior or errors.

```markdown
## Bug Report

### Description
[Clear description of the bug]

### Steps to Reproduce
1. [First Step]
2. [Second Step]
3. [See error]

### Expected Behavior
[What should happen]

### Actual Behavior
[What actually happens]

### Environment
- OS: [Windows 11]
- Python: [3.11.x]
- Browser: [Chrome 120]

### Screenshots/Logs
[If applicable]

### Additional Context
[Any other relevant information]
```

### âœ¨ Feature Request

For new functionality.

```markdown
## Feature Request

### Problem Statement
[Describe the problem this feature would solve]

### Proposed Solution
[Describe your proposed solution]

### Alternatives Considered
[Other approaches you considered]

### Acceptance Criteria
- [ ] [Criterion 1]
- [ ] [Criterion 2]

### Additional Context
[Mockups, examples, or additional information]
```

### ðŸ“‹ Task

For general work items.

```markdown
## Task

### Description
[Clear description of the task]

### Acceptance Criteria
- [ ] [Criterion 1]
- [ ] [Criterion 2]

### Technical Notes
[Implementation guidance or constraints]

### Dependencies
[Related issues or prerequisites]
```

---

## Phase 1: Gather Information

### Questions to Ask

**For Bugs:**
1. What were you trying to do?
2. What did you expect to happen?
3. What actually happened?
4. Can you reproduce it consistently?
5. What environment are you using?

**For Features:**
1. What problem are you trying to solve?
2. Who will benefit from this?
3. What would success look like?
4. Are there any constraints or requirements?

**For Tasks:**
1. What needs to be done?
2. Why is this needed?
3. What are the acceptance criteria?
4. Are there dependencies?

---

## Phase 2: Structure the Issue

### Title Guidelines

```markdown
# Format: [Type] Brief descriptive title

# âœ… Good
[Bug] Dashboard fails to load with special characters in filter
[Feature] Add export to CSV for complaints report
[Task] Migrate database connection to use connection pooling

# âŒ Bad
Bug in dashboard          # Too vague
It doesn't work           # Not descriptive
Feature request please    # No description
```

### Body Structure

1. **Context first**: Why does this matter?
2. **Details**: What specifically needs to happen?
3. **Acceptance criteria**: How do we know it's done?
4. **Additional info**: Screenshots, logs, examples

### Labels to Suggest

| Label | Use When |
|-------|----------|
| `bug` | Something isn't working |
| `enhancement` | New feature or request |
| `documentation` | Docs need updating |
| `good first issue` | Good for new contributors |
| `help wanted` | Extra attention needed |
| `question` | Further information requested |
| `wontfix` | Will not be addressed |
| `duplicate` | Already exists |
| `priority:high` | Urgent issue |
| `priority:low` | Nice to have |
| `area:frontend` | Frontend/UI issues |
| `area:backend` | Backend/API issues |
| `area:database` | Database issues |

---

## Phase 3: Generate Issue

### Template Output

```markdown
## Generated Issue

### Title
[Type] [Descriptive title]

### Body
[Formatted issue body using appropriate template]

### Suggested Labels
- [label1]
- [label2]

### Suggested Assignee
[If applicable]
```

---

## Examples

### Bug Example

**User says**: "The complaints dashboard crashes when I select a date range more than 30 days"

```markdown
### Title
[Bug] Dashboard crashes when selecting date range over 30 days

### Body

## Bug Report

### Description
The complaints dashboard crashes with an error when selecting a date range 
greater than 30 days in the filter.

### Steps to Reproduce
1. Navigate to Complaints Dashboard
2. Click on date range filter
3. Select start date more than 30 days ago
4. Select end date as today
5. Error appears and dashboard fails to load

### Expected Behavior
Dashboard should load complaints for the selected date range, 
potentially with pagination for large result sets.

### Actual Behavior
Application crashes with "Memory Error" or becomes unresponsive.

### Environment
- OS: Windows 11
- Python: 3.11.4
- Streamlit: 1.28.0

### Possible Cause
The query may be fetching too much data without pagination, 
causing memory issues.

### Suggested Labels
- bug
- priority:high
- area:frontend
```

### Feature Example

**User says**: "We need to be able to export complaint reports to Excel"

```markdown
### Title
[Feature] Export complaints report to Excel

### Body

## Feature Request

### Problem Statement
Analysts need to share complaint data with stakeholders who don't 
have access to the dashboard. Currently there's no way to export 
the data.

### Proposed Solution
Add an "Export to Excel" button on the complaints report page that:
- Exports currently filtered data
- Includes all visible columns
- Formats dates in DD/MM/YYYY format
- Names file with date: `complaints_export_2024-01-15.xlsx`

### Acceptance Criteria
- [ ] Export button visible on complaints report page
- [ ] Export respects current filters
- [ ] Excel file opens correctly in Microsoft Excel
- [ ] Large exports (>10k rows) don't crash the app
- [ ] File includes column headers

### Technical Notes
Consider using `openpyxl` or `xlsxwriter` for Excel generation.
May need to implement streaming for large datasets.

### Suggested Labels
- enhancement
- area:frontend
```

### Task Example

**User says**: "We need to add logging to the API endpoints"

```markdown
### Title
[Task] Add structured logging to API endpoints

### Body

## Task

### Description
Add consistent logging to all API endpoints using loguru for 
better debugging and monitoring in production.

### Acceptance Criteria
- [ ] All endpoints log request received (INFO level)
- [ ] All endpoints log response sent with status code
- [ ] Errors logged with full stack trace (ERROR level)
- [ ] Sensitive data (passwords, tokens) excluded from logs
- [ ] Log format includes timestamp, request ID, user ID

### Technical Notes
- Use loguru for logging
- Follow pattern in [python.instructions.md](../instructions/python.instructions.md)
- Add request ID middleware for tracing

### Dependencies
- None

### Suggested Labels
- enhancement
- area:backend
```

---

## Updating Existing Issues

When updating rather than creating:
1. **Fetch current issue first** to preserve unchanged fields
2. Only modify fields that need changing (title, body, state, labels, assignees)
3. State values: `open`, `closed`
4. Link related issues when known: `Related to #123`

## Workflow Summary

1. **Determine action**: Create, update, or query?
2. **Gather context**: Get repo info, existing labels, milestones if needed
3. **Structure content**: Use the appropriate template above
4. **Execute**: Create or update the issue via CLI (`gh issue create`) or API
5. **Confirm**: Report the issue URL to the user

## Tips

- Always confirm the repository context before creating issues
- Ask for missing critical information rather than guessing
- For updates, fetch current issue first to preserve unchanged fields
- Keep titles under 72 characters
- Use `gh` CLI for automation: `gh issue create --title "..." --body "..." --label bug`

---

## Checklist

Before finalizing the issue:

- [ ] Title is clear and descriptive
- [ ] Body provides enough context
- [ ] Steps to reproduce (for bugs) are complete
- [ ] Acceptance criteria are measurable
- [ ] Appropriate labels suggested
- [ ] No sensitive information included
- [ ] Related issues linked where applicable