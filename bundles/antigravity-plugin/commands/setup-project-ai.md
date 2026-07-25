---
description: Install or refresh the agent-agnostic dev harness in this project (AGENTS.md-canonical rules hierarchy + CLAUDE.md @import shims, subagents, commands, settings)
argument-hint: [--force] [project description]
---

# /setup-project-ai — install the harness

Set up (or refresh) the agent-agnostic development harness for this project. Follow the
`setup-project-ai` skill end-to-end: run the deterministic generator, resolve any reported
placeholders, enrich the generated AGENTS.md rules hierarchy (the canonical files — never the CLAUDE.md
shims) with project-specific facts, ensure the test env, and smoke-test.

Context / args: **$ARGUMENTS**

Load and follow the `setup-project-ai` skill. Do not hand-roll the steps — the deterministic parts
must go through the bundled generator so they don't vary. Resolve its path per the skill's Step 1:
- Plugin install: `${CLAUDE_PLUGIN_ROOT}/scripts/setup_project_ai.py`
- harness (claudster-source) checkout: `scripts/setup_project_ai.py`

## After the deterministic step — install the claude-oss / claude-glm launchers (optional)

`claude-oss` / `claude-glm` (see `/caddis:use-model`) let a session run on an OSS provider (GLM,
DeepSeek, OpenRouter). They live at `claude-harness/scripts/claude-oss.{sh,ps1}`. This step never
silently edits the user's shell profile — print the one-liner and let them run it:

```powershell
# PowerShell — add to $PROFILE (or run once per session):
function claude-oss { & "<path-to>\claude-harness\scripts\claude-oss.ps1" @args }
function claude-glm  { & "<path-to>\claude-harness\scripts\claude-oss.ps1" @args }
```
```bash
# bash/zsh — add to ~/.bashrc / ~/.zshrc:
alias claude-oss="<path-to>/claude-harness/scripts/claude-oss.sh"
alias claude-glm="<path-to>/claude-harness/scripts/claude-oss.sh"
```
Resolve `<path-to>` per the same plugin-vs-source rule as the generator itself (`${CLAUDE_PLUGIN_ROOT}`
for a plugin install, the harness checkout path for claudster-source). Also set `CADDIS_KEYS_FILE`
(default `~/.claudster/keys.env`) with the provider keys — see `docs/guide/providers-and-keys.md`.

## After the deterministic step — deploy vmie skills (optional, personal)

`vmie` skills (deploy-local, golden-workflow, windows-deployment) are **private** and are not shipped
in the public plugin. This step is for a local harness author who keeps a vmie source on disk; it is a
no-op for everyone else. Point `CADDIS_HARNESS_SRC` at your harness root (the folder containing
`skills/vmie/`) and run:

```powershell
# CADDIS_HARNESS_SRC is current; CLAUDSTER_HARNESS_SRC is read as a one-version fallback.
$harnessSrc = if ($env:CADDIS_HARNESS_SRC) { $env:CADDIS_HARNESS_SRC } else { $env:CLAUDSTER_HARNESS_SRC }
$src = if ($harnessSrc) { Join-Path $harnessSrc "skills\vmie" } else { $null }
$dest = ".github\skills\vmie"
if ($src -and (Test-Path $src)) {
    New-Item -ItemType Directory -Force $dest | Out-Null
    Copy-Item "$src\*" $dest -Recurse -Force
    Write-Host "vmie skills deployed to $dest"
} else {
    Write-Host "vmie source not found (set CADDIS_HARNESS_SRC) — skipping; public installs have no vmie."
}
```

Do not commit the vmie skills to the project repo — they are private harness resources.
