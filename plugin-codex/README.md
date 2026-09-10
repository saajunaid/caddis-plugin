# caddis for Codex CLI

Codex reads the Claude plugin format verbatim, so this installs from the same marketplace:

```
codex plugin marketplace add https://github.com/saajunaid/caddis-plugin
codex plugin add caddis-codex@caddis
```

**Install `caddis-codex`, not `caddis`.** The plain `caddis` plugin installs cleanly in Codex and
its skills work — but Codex has **no command concept**, so all 31 `/caddis:*` commands are inert
there. This bundle reshapes every one of them into a skill, which is the form Codex loads.

## One setup step

16 of those skills shell out to a script. Codex sets **no** plugin-root variable — verified:
`CLAUDE_PLUGIN_ROOT` is unset, and the only `CODEX_*` variables are session and sandbox ones. So
point `CADDIS_PLUGIN_ROOT` at this plugin once:

```powershell
# PowerShell — the version is the plugin version, visible in `codex plugin list`
$env:CADDIS_PLUGIN_ROOT = "$env:USERPROFILE\.codex\plugins\cache\caddis\caddis-codex\<version>"
```

```bash
export CADDIS_PLUGIN_ROOT="$HOME/.codex/plugins/cache/caddis/caddis-codex/<version>"
```

Without it, the other 15 skills still work; the 16 that call a script will not.

## What is here

| | |
|---|---|
| `skills/` | the caddis skill pool, plus all 31 commands reshaped into skills |
| `scripts/` | the scripts those skills call |
| `agents/` | agent definitions |

Skills are flat — `skills/<name>/SKILL.md` — which is what Codex loads. Measured in a live
install: 134 flat versus 6 nested.
