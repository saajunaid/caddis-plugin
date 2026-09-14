# caddis-run — start an agent session inside a capped Job Object (see docs/guide/resource-protection.md in the caddis source repo).
# Usage: caddis-run claude | caddis-run codex | caddis-run agy | caddis-run claude-glm
# Always goes through the governor: an environment variable is not proof of a cap. Prefers the
# admin-installed governor copy, which an agent running as the user cannot edit.
if ($args.Count -eq 0) { Write-Error "usage: caddis-run <command> [args...]"; exit 2 }
$installed = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'caddis\caddis_governor.py'
$gov = if (Test-Path $installed) { $installed } else { Join-Path $PSScriptRoot 'caddis_governor.py' }
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { Write-Error "caddis-run: python not found on PATH; refusing to start ungoverned"; exit 3 }
& $py $gov exec --scope session -- @args
exit $LASTEXITCODE
