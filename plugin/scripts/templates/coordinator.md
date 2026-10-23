# Coordinator config

This file is the per-repo config for `/caddis:coordinate`. The coordinator session reads the ONE fenced
`json` block below. The prose around it is for people.

How to fill it:

- Replace every `"<fill: ...>"` string with the real value. The coordinator refuses to start while any
  `<fill:` string is left (`caddis_coordinate.py config show` lists them).
- Keep every key. A missing key also stops the coordinator.
- Put no host names and no secrets here. The production base URL comes from the environment variable that
  `deploy.base_url_env` names.

What the keys mean:

| Key | Meaning |
|---|---|
| `schema` | The config format version. Keep `1`. |
| `default_branch` | The branch that PRs merge into. |
| `merge_method` | `squash`, `merge` or `rebase`. Match the repo's branch protection (linear history needs `squash` or `rebase`). |
| `required_checks` | The required status checks, as branch protection names them. A fallback only: the coordinator reads branch protection first and tells the owner on a mismatch. |
| `not_required` | Checks that may fail or skip on a PR without blocking the merge. |
| `docs_only.signal` | The CI job that decides if a change is docs-only (the other required checks then conclude `skipped`). |
| `docs_only.deploy_check` | The deploy checks for a docs-only merge. A docs-only push deploys nothing. |
| `main_workflow` | The name of the CI workflow that runs on the default branch. No merge while it runs. |
| `reviews.count` | How many reviews a PR needs before it is ready. |
| `reviews.stop_on` | Which review findings stop a merge. `blocking`: only blocking findings. |
| `peer_ack.warning_min` | Minutes between the merge warning and the merge. |
| `peer_ack.ack_file` | Where each peer writes its ack: `{head, acked[], at}`. An ack older than 30 minutes does not count. |
| `deploy.event` | The event that starts the deploy run (for example `push`). |
| `deploy.jobs` | The number of jobs in the deploy run. |
| `deploy.tag` | The release tag scheme. With `calver`, the tag must point at the merge SHA. |
| `deploy.base_url_env` | The environment variable that holds the production base URL on this machine. |
| `deploy.auth` | How the checks authenticate to production. |
| `deploy.version_path` | The JSON endpoint whose `sha` field must equal the merge SHA after the deploy. |
| `deploy.health_path` | The endpoint that must answer 200 after the deploy. |
| `deploy.never_health_path` | A path that looks healthy even when the API is dead. Never used as a health check. |
| `deploy.render_check` | How the PR's session checks a served page: 0 console errors and one value checked against its source. |
| `deploy.wait` | How to wait for the deploy run. No fixed sleep. |
| `owner_reserved` | Changes that only the owner may approve. |
| `stall.busy_silent_min` | Minutes a busy session may stay silent before the coordinator asks. |
| `stall.ready_no_ready_msg_min` | Minutes a green PR may wait for its session's ready message. |
| `quiet.coordination` | Quiet hours for merges (`none`: no quiet hours). |
| `quiet.timing_checks` | When timing checks may run. |

```json
{
  "schema": 1,
  "default_branch": "<fill: the branch that PRs merge into, for example main>",
  "merge_method": "squash",
  "required_checks": [
    "<fill: one required status check as branch protection names it, for example ci / lint_and_test; one string per check>"
  ],
  "not_required": [
    "<fill: one check that may fail or skip on a PR, for example notify; one string per check, or an empty list>"
  ],
  "docs_only": {
    "signal": "<fill: name of the CI job that decides if a change is docs-only>",
    "deploy_check": ["push_run", "health"]
  },
  "main_workflow": "<fill: name of the CI workflow that runs on the default branch>",
  "reviews": {"count": 2, "stop_on": "blocking"},
  "peer_ack": {
    "warning_min": 2,
    "ack_file": "~/.claude/merge-acks/<repo>/pr-<n>.json"
  },
  "deploy": {
    "event": "push",
    "jobs": "<fill: number of jobs in the deploy run>",
    "tag": "<fill: release tag scheme, for example calver, or none>",
    "base_url_env": "<fill: name of the environment variable that holds the production base URL>",
    "auth": "<fill: how the checks authenticate to production, for example none>",
    "version_path": "<fill: path of the JSON endpoint whose sha field is the deployed commit>",
    "health_path": "<fill: path of the endpoint that must answer 200 after the deploy>",
    "never_health_path": "<fill: path that looks healthy even when the API is dead, or null>",
    "render_check": "<fill: how the PR's session checks a served page, for example a headless browser>",
    "wait": "gh run watch"
  },
  "owner_reserved": [
    "schema change or data write on prod",
    "permission change",
    "any open blocking review finding",
    "<fill: a rule the owner reserved by name; one string per rule, or delete this line>"
  ],
  "stall": {"busy_silent_min": 45, "ready_no_ready_msg_min": 20},
  "quiet": {
    "coordination": "none",
    "timing_checks": "<fill: when timing checks may run, for example quiet window only>"
  }
}
```
