# CI and credentials after a port

Every item here broke a real deploy at least once.

## The two kinds of credential

| Faces | Examples | On GitHub |
|---|---|---|
| ORIGIN - this repo | `actions/checkout`, a deploy script's `git fetch`/`reset`, pushing a version tag back | `${{ github.token }}`, username `x-access-token`. Needs `permissions: contents: write` to push. Nothing to store or rotate. |
| DEPENDENCY - another host or repo | a library pinned `git+https://host/org/lib.git@v1`, a private npm/PyPI registry, a Git server that stays behind | A secret that can read THAT host. `github.token` cannot read a different repo, even in the same org. |

Choose the credential **per host**, from the host named in the pin, never from where the app is
hosted. When a pin moves from the old server to GitHub, its credential must move with it in the
same commit; when an app moves but its pins do not, the old credential must stay.

A deploy script that builds its auth header from `git remote get-url origin` needs NO change
for the origin half: repointing origin (phase 5) is the whole cutover. It DOES need a change if
it also uses that origin-derived credential for dependency clones - the moment origin is
GitHub and the dependency is not, that pairing is wrong.

## Injecting a credential for a child process (pip, npm)

`GIT_CONFIG_*` environment entries (git 2.31+) are inherited by every git a tool spawns:

```yaml
env:
  GIT_CONFIG_COUNT: '2'
  GIT_CONFIG_KEY_0: http.https://github.com/.extraheader
  GIT_CONFIG_VALUE_0: AUTHORIZATION: basic <base64 of x-access-token:TOKEN>
  GIT_CONFIG_KEY_1: http.https://old-host.example/.extraheader
  GIT_CONFIG_VALUE_1: AUTHORIZATION: basic <base64 of user:OLD_HOST_TOKEN>
```

Add a new entry and increment the count. Never replace entry 0 when another host still needs
it. Build the base64 in a script step from `env:`; never put a token in a URL - it lands in
lockfiles and logs.

## Traps

- **Header accumulation.** `http.<url>.extraheader` never overrides; git sends every matching
  one. `actions/checkout` persists one in `.git/config`. A second for the same host -> HTTP 400
  `Duplicate header: "Authorization"`. Unset the checkout's entry for the one command that
  needs a different credential, then restore it; otherwise every later step loses its auth.
- **`git config --local` outside a repo fails.** A runner's temp working directory is not a
  repository. Check `git rev-parse --is-inside-work-tree` first.
- **npm uses SSH for GitHub deps** despite `https` in `package.json` and the lockfile. Add
  `url.https://github.com/.insteadOf ssh://git@github.com/`. Also make sure the lockfile's
  `resolved` URLs say `git+https`, not `git+ssh`.
- **A cache hit is not proof of credentials.** A warm npm or pip cache skips the authenticated
  fetch entirely. Prove a new credential with a fresh install (cleared cache, empty `HOME`, no
  credential helper).
- **Windows PowerShell 5.1 runners.** With `$ErrorActionPreference='Stop'`, anything a native
  exe writes to stderr becomes a terminating error, and `2>$null` does not prevent it. Use
  `'Continue'` in the step, `2>&1 | Out-Null` to silence, and judge by `$LASTEXITCODE`.
- **A step whose last native command is EXPECTED to fail** (a negative test) must end with
  `exit 0`, or the step is red after printing its pass.
- **Required checks.** A job skipped by a path filter at the TRIGGER never reports, so making it
  a required check blocks every PR that does not touch those paths. A job skipped by `if:` counts
  as passed. Renaming a job renames its check context and silently breaks a branch rule.
- **`concurrency: cancel-in-progress`** cancels a PR's running jobs when you push again. A
  `cancelled` job or a PR with no runs is often this, not a fault. Re-check against the new
  head SHA.
- **Deploy scripts may run from the deploy checkout**, not from the commit being deployed. If the
  workflow syncs that checkout to the target commit before calling the script, a script change
  takes effect on the first deploy; if it does not, it takes effect on the NEXT deploy. Check
  which before predicting.
