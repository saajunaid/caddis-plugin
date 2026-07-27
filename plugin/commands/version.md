---
description: Report the installed caddis version
---

# /version — what caddis am I running?

Report the caddis toolchain version to the user as **caddis &lt;version&gt;**.

Get the version by reading the `version` field of the `plugin.json` manifest that ships in THIS install —
do NOT guess or infer it from anything else. Read whichever path exists:

- **Claude Code:** `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json`
- **agy (Antigravity):** the caddis plugin install dir — `~/.gemini/config/plugins/caddis/plugin.json`
- **Otherwise:** the nearest `plugin.json` at/above this skill whose `name` is `caddis`.

Read that file, take its `version`, and report `caddis &lt;version&gt;`. This reads the manifest live, so it is
always the exact installed version. If no manifest is found, say so plainly rather than reporting a guess.
