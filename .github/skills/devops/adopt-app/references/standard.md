# The adoption standard

`Test-AppConformance.ps1` (phase 3) measures an app against 21 items, in the order below - the
same order the script adds them in. Each one gets a verdict, never a guess:

| Verdict | Means |
|---|---|
| `PASS` | Observed true, from the inventory or the profile. |
| `GAP` | Observed false. The evidence is named. |
| `ASK` | Not observable from files. A person must answer it. |
| `ANSWERED` | Was `ASK`; a non-empty answer has been recorded for it (see below). Not a fourth independent state - it only exists once an `ASK` has been answered. |

Items marked **blocking** below stop the adoption exactly the same way whether they are `GAP` or
an unanswered `ASK` - a checklist that only tracks blocking failures and lists open questions as
notes at the bottom lets those questions be skipped, which is the failure this standard exists to
prevent.

---

### 1. `git-repo` - The source is in a git repository

**Blocking.**

**Decided by:** `PASS` if the source folder contains a `.git` directory (`inventory.git.isRepo`
is true). `GAP` otherwise, with "no `.git` in the source folder" as the evidence.

**Why it is on the list:** an app with no repository has no history and no way to see what
changed. Adoption starts by importing the folder as one commit - but only once the content
policy (item 4) is settled, because that first commit decides what is in the history forever.

### 2. `remote-on-team-host` - The repository lives on the team's host

**Blocking.**

**Decided by:** `GAP` if there is no repository at all; `GAP` if a repository exists but has zero
remotes configured ("this folder is the ONLY copy of the history"); `GAP` if
`expectedRemotePattern` is set in the config and none of the remote URLs match it; `PASS` if a
remote exists and either no pattern is configured or one remote matches it.

**Why it is on the list:** a repository with no remote, or hosted on a personal account, is one
disk failure or one departure away from disappearing. `expectedRemotePattern` is what lets this
check tell "the team's host" from "somewhere else" - without it configured, having any remote at
all is enough to pass, which is a weaker check than it looks like.

### 3. `canonical-branch` - Which branch is the truth is written down

**Blocking.**

**Decided by:** `ASK` when the app has a repository AND (it has no remote, OR it has more than 3
local branches). `PASS` otherwise. Note the edge case this produces: when there is no repository
at all, this item reads `PASS` (evidence: "no repository") even though `git-repo` itself is a
`GAP` for the same app - there being no branches yet is not treated as a question to ask.

**Why it is on the list:** with more than a handful of local branches and no shared remote to
compare against, which one is actually deployed cannot be read from the files. Wiring CI to the
wrong branch before this is answered means CI builds and tests code nobody ships.

### 4. `source-only` - The repository holds source, not runtimes, data or dependencies

**Blocking.**

**Decided by:** `GAP` if either of these is true. First, a FILE that git actually tracks also
matches an excludable content category (dependency, runtime, build-output, cache, db-data,
archive, data-export or media - `log` is exempt) - something was committed that should not have
been. Second, a top-level folder is git-untracked, is not `.git`, and is at least
`-UntrackedThresholdMB` (default 10 MB). Otherwise `PASS` - downgraded to `ASK` if any folder was
skipped with `-SkipFolder`, or if git could not be run (see "Coverage" below).

**Tracked state is per FILE, and that distinction is the whole check.** An earlier version asked
git for the state of the FOLDER and applied it to every byte inside. A folder is routinely both
things at once: on a real app, `reports/` held 40 committed markdown documents beside 1,060 MB of
correctly-ignored run output, under an ignore rule that already existed. The check reported
`COMMITTED data-export: reports (1018.47 MB)`. The true figure was 0.01 MB in 4 files - wrong by
about seven thousand times, and wrong in the expensive direction, because it said "rewrite your
history" when the answer was "nothing to do". The summary now prints `COMMITTED` or
`not committed` per row, and only the first kind needs a rewrite.

`git check-ignore` alone cannot make this distinction: by default it does not report a path that
git tracks, so the same folder answers "not ignored" plainly and "ignored" under `--no-index`.
Both answers are true. Only a per-file tracked set says which files are which.

**Why it is on the list:** a `.gitignore` added later does not remove what is already committed -
that needs a history rewrite. And a folder that is neither committed nor ignored is the genuinely
dangerous state: it sits there doing nothing until one `git add -A` puts it in the history
forever. A filename pattern cannot find that state; only asking git can.

### 5. `no-secrets` - No credential is in the working tree

**Blocking.**

**Decided by:** `GAP` if the inventory's `secretsSuspected` list is non-empty (files flagged by
name, e.g. `.env`, `*.pem`, `id_rsa`, `credentials.json`; or by content, e.g. a line shaped like
`password = "..."` or a live-looking token, with comments, non-literal values, and template
references excluded). `PASS` if the heuristics found nothing - which the evidence text says
explicitly is not proof there is nothing.

**Why it is on the list:** history keeps a credential, so the fix is to ROTATE it, not delete it.
Deleting the file in a later commit does not stop anyone who already has a clone, or ever will,
from reading the old value out of history. Only rotating the credential itself closes that.

### 6. `config-separation` - Configuration is outside the code, per environment

**Not blocking.**

**Decided by:** `PASS` if at least one config file looks like a committed template (matches a
name like `.env.example`, `*.sample`, `*.template`, or `*.dist`). `ASK` if the inventory found
zero config files at all. `GAP` if config files exist but none of them look like a template.

**Why it is on the list:** hardcoded, per-environment values in committed config are exactly
where a real credential tends to leak. A committed template proves the separation exists without
exposing a real value; its absence does not prove the opposite, which is why zero config files
reads as a question rather than a pass or a fail.

### 7. `deps-pinned` - Dependencies are pinned

**Not blocking.**

**Decided by:** `PASS` if a recognised lock file is present among the manifests
(`package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `poetry.lock`, `Pipfile.lock`,
`composer.lock`, `Gemfile.lock`, `Cargo.lock`, `go.sum`). `GAP` otherwise.

**Why it is on the list:** without a lock file the build is not reproducible, and a broken deploy
cannot be told apart from a dependency that moved underneath it between two runs.

### 8. `tests` - There is an automated test suite

**Not blocking.**

**Decided by:** `PASS` if the inventory's test-file count is greater than zero (files under a
`tests`/`spec`/`__tests__` folder, or matching a test-name convention like `*_test.py` or
`*.spec.ts`). `GAP` otherwise.

**Why it is on the list:** CI that runs no tests only proves the code compiles.

### 9. `ci-build` - CI builds and tests on every push

**Not blocking.**

**Decided by:** `PASS` if any CI file was found (a workflow under `.github`/`.gitea`/`.forgejo`,
or a known pipeline file like `Jenkinsfile`, `azure-pipelines.yml`, `.travis.yml`,
`appveyor.yml`, `bitbucket-pipelines.yml`). `GAP` if none was found.

**Why it is on the list:** without CI, "it works" means "it worked on one machine, once."

### 10. `ci-deploy` - Deployment is reproducible, not manual

**Not blocking.**

**Decided by:** `ASK` if CI files exist (the file LIST cannot say whether that CI actually
deploys, only that some pipeline exists). `GAP` if there is no CI at all.

**Why it is on the list:** a build pipeline is not the same claim as a deploy pipeline. Whether
pushing to the default branch actually ships the app has to be answered by a person or by reading
the workflow's job list, not assumed from its presence.

### 11. `runtime-manifest` - Anything excluded from the repository can be got back

**Not blocking.**

**Decided by:** `PASS` if no ignored folder is 100 MB or larger among the folders that were
scanned. `ASK` if one or more ignored folders reach that size. A `PASS` is downgraded to `ASK` if
any top-level folder was scanned with `-SkipFolder` (see "Coverage" below).

**Why it is on the list:** excluding a large runtime or dependency tree from the repository is
correct. It is only SAFE once something says how to get it back - the exact version and where it
installs from - and a folder nobody looked at cannot be assumed to already have that answer.

### 12. `health` - There is a health signal that fails loudly

**Not blocking.**

**Decided by:** `PASS` if any probed text file contains a line matching `/health`, `/healthz`,
`/api/health`, or `healthcheck` (case-insensitive). `ASK` if every matched component's profile
name contains `batch` (a batch job has no HTTP endpoint to check at all). `GAP` otherwise.

**Why it is on the list:** a check that returns 200 whatever happens is not a health check.
Finding the STRING `/health` in the source only proves a route exists - it says nothing about
whether that route actually fails when the app is broken. That is why the plan step this item
produces explicitly requires breaking the dependency on purpose and watching the check go red
before it counts as done.

### 13. `run-declared` - How the app runs is declared and version-controlled

**Blocking.**

**Decided by:** `PASS` if the host's registered services, scheduled tasks, or web sites include
at least one whose path references this folder (matched on the folder's last path segment,
against Windows services, scheduled tasks, and IIS sites/applications). `ASK` if nothing on the
scanned host references it at all.

**Why it is on the list:** on a real run, the only "service" `run-declared` found for one app was
a database engine that happened to be installed inside the app's own folder - not the app's
process at all. That is why the evidence names each hit individually (`service X`, `task Y`, `site
Z`): a non-zero count is not proof that any of them is actually running THIS app, and the reader
has to check, not assume.

### 14. `rollback` - There is a way back to the previous version

**Not blocking.**

**Decided by:** Always `ASK` - the code marks it "not observable from files" unconditionally.

**Why it is on the list:** whether the previous release can be restored, by what exact command,
and whether that command has ever actually been run, is not written down anywhere a scan can
read. It can only be answered by a person, and then it has to be exercised at least once to be
believed (see the plan step this item produces).

### 15. `owner` - The app has a named owner

**Blocking.**

**Decided by:** Always `ASK` - "not observable from files" unconditionally.

**Why it is on the list:** nothing in a repository can say who is accountable for it. Without a
named owner there is nobody to decide a change and nobody to call when it breaks, so this has to
reach a person before anything else proceeds.

### 16. `data-recovery` - State can be restored from a backup

**Not blocking.**

**Decided by:** `PASS` if no ignored folder is 100 MB or larger AND the excludable-content
summary contains no `db-data` category entry. `ASK` otherwise. A `PASS` is downgraded the same
way as items 4 and 11 if any top-level folder was scanned with `-SkipFolder`.

**Why it is on the list:** excluding a database file or a data dump from the repository is
correct. It is only safe once a backup schedule exists and a restore from it has actually been
tested - a repository holding schema and migrations is not itself a backup of the data.

### 17. `docs-readme` - A README says what it is and how to run it

**Not blocking.**

**Decided by:** `PASS` if any doc file's name matches `README*` (case-insensitive). `GAP`
otherwise.

**Why it is on the list:** the first two questions a new person asks - what is this, and how do I
run it - should not require finding and interrupting someone.

### 18. `agent-rules` - A rules file the coding agents read

**Not blocking.**

**Decided by:** `PASS` if a doc file is named exactly `AGENTS.md` or `CLAUDE.md`
(case-insensitive). `GAP` otherwise.

**Why it is on the list:** without it, every coding agent that touches the app re-derives its
non-obvious rules from scratch, and different agents derive them differently.

### 19. `work-is-in-a-ref` - Every commit is reachable from a branch or a tag

**Blocking.**

**Decided by:** `GAP` when a worktree is on a DETACHED HEAD that no branch and no tag contains.
`ASK` when there are no unreachable commits but there are stashes, or worktrees with
uncommitted files. `ASK` when git could not be run. `PASS` otherwise.

**Why it is on the list.** A port copies refs. A clone takes `refs/heads/*` and `refs/tags/*`,
so a worktree's BRANCH travels with it like any other - a worktree is an extra folder, not an
extra repository. A **detached HEAD is neither a branch nor a tag**, so its commits are not
copied, and because nothing points at them git is free to collect them. The work is not
protected by being on disk; it is protected by being in a ref.

Measured on a real app: two detached worktrees under a temporary path that the app's own
documents called a "recurring external cleanup hazard", with three recorded incidents. They
held **200 commits** of certified work. `branch --contains` returned 0 for both. Every other
check passed; a port would have carried 127 branches and left behind the only copy of the part
that mattered.

**The fix costs nothing** and the report prints it per worktree:

```
git -C <repo> branch rescue/<worktree-name> <sha>
```

It creates a branch name and changes nothing else. After it, `branch --contains` returns 1 and
the commits port like anything else.

Stashes are the same class of problem for a smaller amount of work: `refs/stash` is not copied
by a clone or a push. Uncommitted files in a worktree are invisible to the main checkout's
`git status`, which is why the inventory reports each worktree's own count.

### 20. `no-junctions` - No junction or symlink inside the tree git manages

**Not blocking.**

**Decided by:** `PASS` if no reparse point (junction or symlink) was found outside a dependency
folder (`node_modules`, `.venv`, `venv`, `vendor`). `GAP` otherwise, naming up to three.

**Why it is on the list:** git's own recursive remove (for example `git worktree remove --force`)
FOLLOWS a junction and deletes the TARGET's contents - this was proven directly, not assumed.
Ordinary Windows delete operations (`Remove-Item -Recurse`, `cmd /c rmdir /s /q`,
`[IO.Directory]::Delete`) all correctly refuse to follow a junction, which is exactly what makes
this trap easy to miss: a delete you tested yourself can look completely safe right up until git
does the deleting instead.

### 21. `profile` - The stack is declared, not assumed

**Blocking.**

**Decided by:** `PASS` if phase 2 matched at least one component to a profile. `GAP` if it
matched none.

**Why it is on the list:** without a declared stack, every later step - runtimes, build, deploy -
is a guess dressed up as a plan. "No profile matched" means the rules do not describe this app
yet; it does not mean the app has no stack.

---

## Coverage: a skipped folder cannot pass a check

Three items above (`source-only`, `runtime-manifest`, `data-recovery`) can only reach `PASS`
through `Limit-ByCoverage`, which downgrades a would-be `PASS` to `ASK` whenever any top-level
folder was scanned with `-SkipFolder`. A folder passed to `-SkipFolder` is recorded as **not
scanned**, never as empty and never as clean - it is unknown. On a real run, `-SkipFolder tools`
hid a 16 GB runtime tree, and without this rule the check for "anything excluded can be got back"
would have reported `PASS` on a folder nobody had actually looked at. Coverage-dependent checks
stay open until every folder has been scanned, or the operator explicitly accepts a partial
inventory (`-AllowPartial` in phase 1).

## Answers and waivers

**`-Answer id=text`** (phase 3) records a non-empty answer for an item that is currently `ASK`.
The tool does not judge the content - any non-empty text satisfies it - and the verdict becomes
`ANSWERED`. Answers persist in `answers.json` inside the app's output folder and are merged with
any new `-Answer` arguments on every run, so recording one once is enough for every later
re-check.

**`-Waive <id>`** records an accepted exception for an item that is not already `PASS`. It sets a
`waived` flag; **it never rewrites the verdict itself**. A waived `GAP` is still recorded as
`GAP`, permanently, with `waived: true` next to it - six months later, that difference between "we
fixed it" and "we accepted the risk" is the whole value of the record. A waived item is excluded
from the blocking counts below, so it can no longer stop the exit code, but the report still shows
what it really is.

## Exit codes

| Code | Means |
|---|---|
| `0` | Every blocking item is `PASS`, `ANSWERED`, or waived. |
| `1` | At least one blocking item is `GAP` and not waived. Checked first - if both a blocking `GAP` and a blocking unanswered `ASK` exist at once, exit code `1` wins. |
| `2` | No blocking `GAP` remains, but at least one blocking item is still an unanswered `ASK` and not waived. |

The nine blocking items, as the code actually enforces them, are: `git-repo`,
`remote-on-team-host`, `canonical-branch`, `source-only`, `no-secrets`, `work-is-in-a-ref`,
`run-declared`, `owner` and `profile`. Which items block is decided in the script, by the `Blocking` argument to each
item, and not by the project config. An earlier draft of the config carried a `blockingItems`
list that nothing read and that had drifted out of step with this set; it was removed from the
code and from `config.example.json` together, rather than documented as a thing that looks
settable and is not.
