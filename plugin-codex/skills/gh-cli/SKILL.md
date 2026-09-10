---
name: gh-cli
description: "GitHub CLI operations — issues, PRs, releases, and repo management"
---

# GitHub CLI Operations

Practical reference for `gh` — the GitHub CLI. Covers repos, issues, PRs, releases, Actions, and automation.

## Prerequisites

```bash
# Install
brew install gh          # macOS
winget install GitHub.cli # Windows
sudo apt install gh       # Linux

# Authenticate and verify
gh auth login
gh auth status
```

## Phase 1: Repositories

```bash
# Create and clone
gh repo create my-project --public --description "My project" --clone
gh repo clone owner/repo
gh repo fork owner/repo --clone

# View and edit
gh repo view owner/repo
gh repo edit --description "Updated desc"
gh browse                  # Open in browser

# Sync fork
gh repo sync
```

## Phase 2: Issues

```bash
# Create
gh issue create --title "Bug: login broken" --labels bug --assignee @me

# List and search
gh issue list
gh issue list --labels bug --assignee @me
gh issue list --search "is:open label:bug sort:updated-desc"
gh issue list --json number,title --jq '.[].title'

# Manage
gh issue view 42
gh issue close 42 --comment "Fixed in PR #55"
gh issue edit 42 --add-label priority-high
gh issue develop 42 --branch fix/issue-42
```

## Phase 3: Pull Requests

```bash
# Create
gh pr create --title "feat: add dark mode" --body "Closes #42" --reviewer user
gh pr create --draft --title "WIP: new feature"

# List and view
gh pr list
gh pr list --author @me
gh pr view 55
gh pr diff 55

# Review and merge
gh pr checkout 55
gh pr review 55 --approve --body "LGTM!"
gh pr review 55 --request-changes --body "Please fix error handling"
gh pr merge 55 --squash --delete-branch

# Manage
gh pr ready 55             # Mark draft as ready
gh pr checks 55 --watch    # Watch CI
gh pr edit 55 --add-label reviewed
gh pr update-branch 55     # Rebase with base
```

## Phase 4: Releases

```bash
# Create
gh release create v1.2.0 --generate-notes --title "v1.2.0"
gh release create v1.2.0 --notes-file CHANGELOG.md
gh release create v1.2.0 ./dist/*.tar.gz   # With assets

# Manage
gh release list
gh release view v1.2.0
gh release download v1.2.0 --pattern "*.tar.gz" --dir ./downloads
gh release upload v1.2.0 ./dist/checksums.txt
gh release delete v1.2.0 --yes
```

## Phase 5: GitHub Actions

```bash
# Monitor
gh run list
gh run list --workflow ci.yml
gh run view 123456 --log
gh run watch 123456
gh run download 123456 --dir ./artifacts

# Trigger
gh workflow run deploy.yml
gh workflow run deploy.yml --raw-field environment=staging

# Manage
gh run rerun 123456
gh run cancel 123456

# Secrets and variables
gh secret list
echo "value" | gh secret set API_KEY
gh secret set DB_PASS --env production
gh variable set DEPLOY_ENV --body "staging"
```

## Phase 6: Advanced

### API Requests

```bash
gh api /repos/owner/repo/contributors --jq '.[].login'
gh api --method POST /repos/owner/repo/issues \
  --field title="API issue" --field body="Created via gh api"
```

### Bulk Operations

```bash
# Close stale issues
gh issue list --search "label:stale" --json number --jq '.[].number' | \
  xargs -I {} gh issue close {} --comment "Closing as stale"

# Label all open PRs
gh pr list --json number --jq '.[].number' | \
  xargs -I {} gh pr edit {} --add-label needs-review
```

### Search

```bash
gh search repos "topic:fastapi stars:>100" --json name,url
gh search code "def authenticate" --repo owner/repo
gh search issues "label:bug state:open" --limit 20
```

### Aliases

```bash
gh alias set co 'pr checkout'
gh alias set myissues 'issue list --assignee @me'
gh alias set review 'pr list --search "review-requested:@me"'
```

## Common Workflows

### Issue to PR (Full Cycle)

```bash
gh issue develop 42 --branch fix/issue-42
git add . && git commit -m "fix: resolve login bug" && git push -u origin HEAD
gh pr create --title "fix: resolve login bug" --body "Closes #42"
gh pr checks --watch
gh pr merge --squash --delete-branch
```

### Release Workflow

```bash
git tag v1.3.0 && git push origin v1.3.0
gh release create v1.3.0 --generate-notes --title "v1.3.0"
gh release upload v1.3.0 ./dist/*.tar.gz
```

## Quick Reference

| Task              | Command                                        |
|-------------------|------------------------------------------------|
| Create repo       | `gh repo create name --public`                 |
| Create issue      | `gh issue create --title "..." --labels bug`   |
| Create PR         | `gh pr create --title "..." --reviewer user`   |
| Merge PR          | `gh pr merge 55 --squash --delete-branch`      |
| Create release    | `gh release create v1.0.0 --generate-notes`    |
| Watch CI          | `gh run watch`                                 |
| Set secret        | `echo "val" \| gh secret set KEY`              |
| API call          | `gh api /repos/o/r --jq '.description'`        |
