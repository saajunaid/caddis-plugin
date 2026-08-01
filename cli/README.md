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
