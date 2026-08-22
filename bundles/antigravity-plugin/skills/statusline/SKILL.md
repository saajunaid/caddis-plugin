---
name: statusline
description: Install the caddis status line into Claude Code and agy — one renderer, once per machine
---

# /statusline — set up the status bar

Wire the caddis status line into every coding agent on this machine. One Python renderer serves
both hosts. It installs at **user scope**, so every project gets the line and no project holds a
copy that can drift.

## What the user gets

Claude Code:

```
⌂ claudster-source | saajunaid/caddis ⎇ main +2 ●1 ?3 ↑1 | ◆ Opus 5 (1M context) v2.1.239 |
◉ 412k/1M [███░░░░░]  41%  | ⚡ 386k cached | effort:high | style:Plain | thinking |
5h:12% 7d:40% | 💻 57% (37 GB) | ⏺ relay | ◷ 07:58
```

agy (Antigravity):

```
▛▜ agy | ● idle | 🧠 Gemini 3.6 Flash (High) (high) | 📁 claudster-source | ⎇ main ?3 |
◉ 48.5k/1M [░░░░░░░░]  5%  | ⚡ 40k cached | q 62% | 💻 57% (37 GB) | ⏺ relay | ◷ 08:01
```

Both lines come from `caddis_statusline.py`. It has two profiles, because the two hosts send
different field names — agy's payload is a sibling of Claude Code's, not a copy.

## Run it

Find the renderer in this install and run it. Try these paths in order and use the first that exists:

- `${CLAUDE_PLUGIN_ROOT}/scripts/caddis_statusline.py`
- `claude-harness/scripts/caddis_statusline.py` (working inside the caddis source repo)

Then:

```bash
python <path>/caddis_statusline.py --install          # both hosts
python <path>/caddis_statusline.py --install --host claude
python <path>/caddis_statusline.py --install --host agy
python <path>/caddis_statusline.py --install --dry-run # print, write nothing
```

`--install` does four things:

1. Copies the renderer to `~/.caddis/statusline.py` — a **stable** path. Pointing the host
   settings at the plugin cache would break on every caddis upgrade, because the version number
   is in that path.
2. Creates `~/.caddis/statusline.json` with the default toggles. It never overwrites an existing one.
3. Backs up each host's `settings.json` to `settings.json.bak-caddis-statusline`.
4. Sets `statusLine` in `~/.claude/settings.json` and `~/.gemini/antigravity-cli/settings.json`,
   preserving every other key. A host that is not installed is skipped, not failed.

Report the tool's own output to the user. Then tell them the line appears on the **next** session —
neither host re-reads `settings.json` mid-session.

## Verify

```bash
python ~/.caddis/statusline.py --check                        # what is wired where
python ~/.caddis/statusline.py --sample --profile claude      # preview, no host needed
python ~/.caddis/statusline.py --sample --profile agy
```

`--check` exits non-zero when a host's `statusLine` is missing or points somewhere else.

## Change the look

Edit `~/.caddis/statusline.json`. Every key is optional; a missing file means defaults.

| key | default | what it controls |
|---|---|---|
| `color` | `true` | ANSI colour |
| `icons` | `true` | Unicode segment icons. These are plain Unicode, **not** Nerd Font glyphs |
| `progress_bar` | `true` | the `[███░░░░░]` context bar |
| `bar_width` | `8` | bar cells |
| `token_counts` | `true` | `◉ 412k/1M` |
| `cached_tokens` | `true` | `⚡ 386k cached` — bold and bright by design, never width-gated |
| `ram` | `true` | `💻 57% (37 GB)` |
| `ram_min_width` | `0` | hide RAM below this terminal width; `0` always shows it |
| `clock` | `true` | `◷ 07:58` |
| `relay` | `true` | `⏺ relay` when a parked resume pointer exists |
| `rate_limits` | `true` | `5h:12% 7d:40%` (Claude Code only) |
| `session_id` | `false` | `#a1b2c3d4` |
| `git` | `true` | branch, staged/unstaged/untracked counts, ahead/behind |
| `separator` | `"\|"` | segment separator |

Config changes take effect on the next render. No reinstall needed.

## Notes for you, not the user

- Do **not** hand-edit either `settings.json` to wire this. `--install` reads, merges and writes
  back, so it cannot drop an unrelated key. Hand edits have dropped `trustedWorkspaces` before.
- The renderer never crashes the host. A bad payload, a missing field, or an unreadable config
  degrades to fewer segments; a hard failure degrades to the directory name.
- RAM on Windows uses `ctypes` `GlobalMemoryStatusEx`, an in-process call. Do not replace it with
  `Get-CimInstance Win32_OperatingSystem` — that cost about 300 ms on **every** render in the
  PowerShell line this replaced.
- If the user asks why their old `~/.claude/statusline-custom.sh` or
  `~/.gemini/statusline/statusline.ps1` no longer runs: nothing points at them any more. They are
  superseded, not deleted. Both are safe to remove once the user is happy with the new line.
