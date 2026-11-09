# @caddis/cli

**One command to install, update and diagnose the [caddis](https://github.com/saajunaid/caddis-plugin) dev harness across every coding agent you use.**

```bash
npx @caddis/cli init      # detect your agents, confirm, install caddis into each
npx @caddis/cli doctor    # what is installed where, and what to do about it
```

If you use more than one coding agent, you have more than one place caddis can go stale.
This CLI is the single front door.

---

## What it does

caddis is a **meta-installer**. It detects the agents on your machine and drives **each one's own
native install mechanism** — it never reimplements them, and it never installs an agent for you.

| Agent | Detected via | How caddis is installed | Status |
| --- | --- | --- | --- |
| **Claude Code** | `claude` on PATH | its plugin marketplace | ✅ |
| **agy** (Antigravity) | `agy` on PATH | the caddis bundle shipped inside this package (`--extras` adds `caddis-extras`) | ✅ |
| **Codex** | `codex` on PATH / `~/.codex` | config merge | planned |
| **GitHub Copilot** | `copilot` on PATH / `.github/copilot-instructions.md` | config merge | planned |

Codex and Copilot are **detected and reported**, never written to. They are file-configured,
which means supporting them properly requires merging into config you already own — that ships when
it is safe, not before.

**Absence is graceful.** Missing agents are skipped with a reason, never an error. One agent failing
never stops the others.

---

## Install

```bash
npx @caddis/cli <command>      # no install
npm i -g @caddis/cli           # then just: caddis <command>
```

Requires **Node >= 20.19**.

---

## Commands

### `caddis doctor`

The one worth knowing. Every agent, the caddis version each actually has, whether that matches what
this CLI ships, where the version was read from, and the exact command that fixes each gap.

```
Environment
  ✓ node 22.14.0
  • platform win32 x64
  • @caddis/cli 0.2.0
  ✓ shipped pool 1.3.39
      bundle antigravity-plugin @ 1.3.39
      bundle antigravity-plugin-extras @ 1.3.13

Agents
  ▲ Claude Code — caddis 1.3.38 → 1.3.39 available
      C:\Users\you\AppData\Roaming\npm\claude.CMD
      agent version 2.1.220
      read from `claude plugin list`
      → caddis update --agent claude
  ▲ agy (Antigravity) — caddis 1.3.38 → 1.3.39 available
      ~\.gemini\config\plugins\caddis\plugin.json
      → caddis update --agent agy
  • Codex — detected — not yet supported

Summary
  3 of 4 agents detected · 0 current · 2 stale · 0 not installed

  2 things to fix:
    • Claude Code has caddis 1.3.38, this CLI ships 1.3.39
      caddis update --agent claude
    • agy (Antigravity) has caddis 1.3.38, this CLI ships 1.3.39
      caddis update --agent agy
```

`--strict` exits non-zero when something needs fixing (for CI). Detected-but-unsupported agents are
information, not failures, and never trip `--strict`. `--json` gives machine-readable output.

**`doctor` also checks whether `@caddis/cli` itself is behind npm** (a 5s `npm view` lookup, opt-in to
`doctor` only — `status`/`init`/`update` stay network-free by default so they never feel hung offline).
This matters because every per-agent drift check above compares against the pool bundled in *this*
install — a CLI that is itself stale can under-report drift even though each individual comparison is
correct. When behind, doctor adds:
```
  ▲ @caddis/cli 0.2.3 → 0.2.4 available
      npm i -g @caddis/cli@latest
```
and counts it as a `--strict`-tripping problem, same as an agent gap.

### `caddis status`

The same facts as a glanceable table. Running bare `caddis` does this.

```
  caddis  cli 0.2.0  ·  pool 1.3.39  ·  extras 1.3.13

  AGENT              DETECTED  CADDIS  EXTRAS  STATE
  ─────────────────  ────────  ──────  ──────  ────────────────
  Claude Code        yes       1.3.38  —       update available
  agy (Antigravity)  yes       1.3.38  1.3.13  update available
  Codex              yes       —       —       planned
  GitHub Copilot     no        —       —       —

  2 agent(s) behind — run caddis update (or caddis doctor for detail)
```

### `caddis update`

Brings every detected, supported agent up to the caddis version shipped in this CLI, through that
agent's native mechanism. Agents already current are skipped (`--force` re-drives them).

**Extras.** `caddis-extras` is the optional long-tail skill library. It is **never installed by
default** — it is large and always-loaded — but `--extras` adds it, and once installed, plain
`update` keeps it current so it can't rot behind a forgotten flag. It versions independently of the
core pool, so `status` and `doctor` report its drift in a separate column.

```bash
caddis init --extras       # core + extras
caddis update --extras     # add extras to an existing install
```

### `caddis init`

The first run. Detects, shows exactly what it is about to run, asks, then installs. `--yes` skips
the prompt for CI.

### `caddis email`

`caddis email setup` is the guided one-time setup for the send-email skill. It asks for the provider (Graph or SMTP), the sender
mailbox and the secrets, writes `~/.caddis/email.toml` (settings only) and, if you enter values, `~/.caddis/email.env` (mode 0600), then
runs the check. A secret is never printed and never goes into `email.toml`. An existing file is replaced only on a yes or `--force`.
For scripts, use `--provider --sender --env-file --tenant-id --client-id --yes`; the secret comes from `CADDIS_EMAIL_CLIENT_SECRET`
(SMTP: `CADDIS_EMAIL_SMTP_PASSWORD`) or the env file, never a flag. `caddis email check` runs the skill's `send_email.py --check`.

### `caddis hub`

A local web page (127.0.0.1 only) with your repos, PRs, plans and live sessions. `caddis hub start`
starts it in the background; `caddis hub stop` stops it.

**Updates by itself.** A running hub checks npm for a new `@caddis/cli` 60 s after it starts, then every 30 minutes. When a newer version is published, the hub installs it (`npm i -g @caddis/cli@<version>`), checks the installed version, and restarts on the same port. Open tabs show "caddis hub updated to X, reloading" and reload. A manual `npm i -g @caddis/cli` also restarts the hub within a minute. A failed install keeps the old hub running and tries again after an hour. Only a hub that runs from the global npm install installs updates: a hub from a dev checkout or `npx` only logs "update available". To check and log only, set `"auto_update": false` in `~/.caddis/hub/config.json`. Each step goes to `~/.caddis/hub/hub.log`.

**Start at logon.** `caddis hub autostart enable` starts the hub after each logon, so it comes back after a reboot. On Windows it creates the logon task `caddis-hub`. When Windows refuses the task ("Access is denied" for a user who is not an administrator), it puts `caddis-hub.vbs` in your Startup folder instead, and the message says which one it used. `caddis hub autostart status` shows which is in place; `caddis hub autostart disable` removes both.

**Logins that last.** Run `caddis hub open` to get a one-time login code and open the hub. Your session lasts 7 days without use and 30 days at most, and it survives a hub restart.

**Timeline first, Board second.** Roadmaps and plans open on the Timeline view by default, with the Board view as the second option. Click any phase tile on the Timeline to open the phase panel and read its Tracker status, PR links and plan section text.

**Branch progress.** A plan that an open PR changes shows the PR branch's Tracker and `status:`, with the badge `on branch (PR #n)`. Done on main never goes back, and forks are not shown. The hub reads PR heads from GitHub and branch refs from the local origin refs, and never fetches. With no PR data, the line above the plans says `branch progress off (no PR data)`. `caddis hub export --prs <file>` takes the output of `gh pr list --json number,headRefName,isDraft,isCrossRepository,updatedAt`. The export never publishes a branch name, and a privacy hit only in branch content publishes main only.

**Guide Poster and Details.** The Guide page has a `Poster` tab (with `Workflow` and `Mind map` views, plus a `Print` button for a two-page A3 landscape wall poster) and a `Details` tab. Every item on the poster links to its entry in Details.

**Guide Wall poster.** A third tab, `Wall poster` (`#/guide/wall`), shows one A4 landscape sheet: the daily commands in order, a card per stage (plan, build, review, ship, continuity, knowledge, setup), and the agents. The `Print` button prints exactly that sheet on one page. It is built from the same installed guide data as the other tabs, so a new command, agent or count appears by itself after `caddis update` and a hub restart. The text shrinks (to 60% at most) when the guide grows, so nothing is cut off. Each line is the first clause of the description; the Details tab has the full text.

**Guide Map.** A fourth tab, `Map` (`#/guide/map`), lays out the whole plugin: the daily loop (plan, build, review, ship) with its commands, the support lanes (continuity, knowledge, setup), the hooks as a timeline in the order a session fires them, the agents with their model and a `writes files` marker, the skills by family, and the runtimes that receive caddis. Every name links to its entry in Details. A filter box dims what does not match, and `Print` prints the map on A3 landscape. Nothing on the map is written by hand: it is built from the installed guide data, so a new command, agent, skill or hook appears by itself after `caddis update` and a hub restart.

**Sessions from more than one agent.** Claude Code sessions come from `claude agents --json`. agy
(Antigravity) sessions come from the caddis agy hooks: each agy turn writes a status file, and the
hub lists that session with an `agy` chip. A turn that starts sets `working`. A turn that ends sets
`waiting` (waiting for you, after 45 s). A session that has not written for 10 minutes shows as
`idle`, unless it waits and its agy process still runs. The hub drops a session when its process
stops or when it has not written for 24 hours. Headless runs (`CADDIS_HEADLESS`) write nothing.

Any other agent can show its sessions the same way. Write one JSON file per session to
`~/.caddis/sessions/<session-id>.json` (`CADDIS_HOME` replaces the home folder). Write a temp file
in that folder, then rename it over the target:

```json
{
  "session_id": "c0ffee-1234",
  "harness": "my-agent",
  "caddis_version": "1.3.200",
  "pid": 4242,
  "started": 1793000000.0,
  "last_seen": 1793000300.0,
  "status": "waiting",
  "status_since": 1793000300.0,
  "cwd": "/work/shop",
  "repo_path": "/work/shop",
  "waiting_for": "input needed"
}
```

- Times are Unix seconds. `status` is `working` or `waiting`; the hub ignores a file without one.
- `pid` is the agent's own process, or `null` when it is not known. With a pid, the hub drops the
  session when that process stops. Without one, only the times count.
- `harness` names the agent. The hub skips `claude`, because Claude Code sessions come from
  `claude agents`.
- `cwd` puts the session under its repo. `waiting_for` is a short reason; it is shown when waiting.
- The first six keys are the session heartbeat that `caddis doctor` already reads. Do not remove them.

### Removing caddis

**There is no `caddis remove`.** This CLI installs and updates; it never uninstalls. Removal goes
through each agent's own command — the same principle as everything else here:

```bash
claude plugin uninstall caddis@caddis         # Claude Code
claude plugin uninstall caddis-extras@caddis
agy plugin uninstall caddis                   # agy
agy plugin uninstall caddis-extras
```

`npm uninstall -g @caddis/cli` removes **only this CLI**, not the caddis plugins it installed into
your agents. Uninstall those first if you want caddis gone entirely.

---

## Flags

| Flag | Effect |
| --- | --- |
| `--dry-run` | print the exact vendor commands; change nothing |
| `-y, --yes` | never prompt |
| `-a, --agent <name...>` | limit to specific agents (`claude`, `agy`, `codex`, `copilot`) |
| `--extras` | also install the optional `caddis-extras` long-tail skills (`init`, `update`) |
| `--json` | machine-readable output (`doctor`, `status`) |
| `--strict` | exit 1 when something needs fixing (`doctor`) |
| `--no-update-notifier` | skip the "newer @caddis/cli available" check |

Flags work before or after the subcommand: `caddis update --dry-run` and `caddis --dry-run update`
are the same.

**Always safe to preview:**

```bash
$ caddis update --dry-run
  · Claude Code — dry run — nothing executed
      would run: claude plugin marketplace update caddis
      would run: claude plugin update caddis@caddis
  · agy (Antigravity) — dry run — nothing executed
      would run: agy plugin install <shipped bundle>
```

---

## Where the caddis content comes from

The caddis bundles ship **inside this npm package**, versioned in lockstep with the CLI — the caddis
you install is the caddis you get, with no extra fetch. That is why the tarball is a few MB: it
carries both the core agy bundle and the optional `caddis-extras` library. `doctor` compares each agent's installed
version against that shipped version; that difference is what "drift" means throughout.

## License

MIT
