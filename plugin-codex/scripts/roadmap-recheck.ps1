# roadmap-recheck - the scheduled task for one roadmap (caddis-next Phase 9). It starts
# `roadmap-run.ps1 -Roadmap <slug>` detached only when ALL of these hold, checked in this order:
#   1. `--last-stop` exits 0: the runner's last recorded stop is `BLOCKED nothing ready`, there is none, or one of
#      these, each with its own line prefix: `merged:` (the waiting PR merged), `freed:` (the runners that held our
#      batches are gone), `rollup-ready:` (a milestone waits only for its rollup); any FAILED stop
#      (the snapshot guard, a crash), `running` (a killed run), a cap or a STOP file needs the owner, so it prints
#      why and starts nothing;
#   2. the roadmap runner lock is absent or stale (`--lock-state`); a live lock starts and writes nothing;
#   3. `caddis_roadmap.py recheck` cleared a blocker (exit 0); in a `merged:`, `freed:` or `rollup-ready:` tick
#      recheck is NOT run (the
#      merge is the change, and a cleared blocker would change the roadmap the restart checks against its hash);
#   4. agy engine only (the recorded launch options): `caddis_spend.py check` exits 0.
# It restarts with the launch options the last run recorded (`--restart-args`: engine, model, caps), never the
# defaults. A run that holds the lock records the last stop `running`, so a run killed without a stop (a crash, a
# reboot) is never restarted here: it needs the owner.
# The owner registers it every 2 hours with the command that `roadmap-run.ps1 -Roadmap <slug> -PrintRecheckTask`
# prints. Every Python call here runs with CADDIS_HEADLESS=1, so no owner-only roadmap change can pass.
# Test seams: CADDIS_RECHECK_PYTHON (the interpreter) and CADDIS_RECHECK_SCRIPTS (the folder that holds
# caddis_roadmap.py, caddis_roadmap_run.py, caddis_spend.py and roadmap-run.ps1).
# Usage: roadmap-recheck.ps1 -Roadmap <slug> [-Repo <path>] [-GhAccount <gh login>]
# Exit: 0 started the runner, 1 nothing to start, 3 cannot run, 4 bad input.
param(
    [string]$Roadmap = '',
    [string]$Repo = (Get-Location).Path,
    [string]$GhAccount = ''
)
$SlugRule = '^[a-z0-9][a-z0-9-]{0,62}$'  # = caddis_roadmap.SLUG_RE_TEXT (a test keeps the three equal)
if ($Roadmap -cnotmatch $SlugRule) { Write-Error "roadmap-recheck: -Roadmap must match $SlugRule"; exit 4 }
$py = if ($env:CADDIS_RECHECK_PYTHON) { $env:CADDIS_RECHECK_PYTHON } else { (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $py) { Write-Error "roadmap-recheck: python not found on PATH"; exit 3 }
$dirs = if ($env:CADDIS_RECHECK_SCRIPTS) { @($env:CADDIS_RECHECK_SCRIPTS) } else { @($PSScriptRoot, (Join-Path $PSScriptRoot '../../scripts')) }
function Find-Script([string]$name) {
    foreach ($dir in $dirs) {
        $p = Join-Path $dir $name
        if (Test-Path $p) { return (Resolve-Path $p).Path }
    }
    return $null
}
$roadmapPy = Find-Script 'caddis_roadmap.py'
$runnerPy = Find-Script 'caddis_roadmap_run.py'
$spendPy = Find-Script 'caddis_spend.py'
$runPs1 = Find-Script 'roadmap-run.ps1'
if (-not ($roadmapPy -and $runnerPy -and $spendPy -and $runPs1)) {
    Write-Error "roadmap-recheck: caddis_roadmap.py, caddis_roadmap_run.py, caddis_spend.py or roadmap-run.ps1 not found"
    exit 4
}
$env:CADDIS_HEADLESS = '1'  # inherited by every child below
# No trailing separator (a trailing `\` before a closing quote escapes it); a drive root keeps `X:\`.
$Repo = $Repo.TrimEnd('\', '/')
if ($Repo -match '^[A-Za-z]:$') { $Repo += '\' }
$repoArg = if ($Repo -match '\\$') { "$Repo\" } else { $Repo }  # doubled in front of the closing quote

$ghArgs = if ($GhAccount) { @('--gh-account', $GhAccount) } else { @() }
$why = (& $py $runnerPy --roadmap $Roadmap --repo $Repo --last-stop @ghArgs) -join ' '
if ($LASTEXITCODE -ne 0) { Write-Output "roadmap-recheck: $why; runner not started"; exit 1 }

# A live lock: a runner is starting or running. Start nothing and WRITE nothing (no recheck either: a cleared
# blocker would change the roadmap under that runner's guard). `--last-stop` above only reads.
$state = & $py $runnerPy --roadmap $Roadmap --repo $Repo --lock-state
if ($LASTEXITCODE -ne 0) { Write-Output "roadmap-recheck: runner lock is $state; runner not started"; exit 1 }

$merged = $why -match '^(merged|freed|rollup-ready):'  # merged PR, holder gone, or a milestone waits for its rollup
if (-not $merged) {
    # Only after `BLOCKED nothing ready` (or no stop). Never in a `merged:` tick: clearing a blocker now would change
    # the origin roadmap the restarted runner checks against the hash it recorded at publish time.
    & $py $roadmapPy recheck --roadmap $Roadmap --root $Repo
    $rc = $LASTEXITCODE
    if ($rc -ne 0) { Write-Output "roadmap-recheck: no blocker cleared (recheck exit $rc); runner not started"; exit 1 }
}

$options = @(& $py $runnerPy --roadmap $Roadmap --repo $Repo --restart-args | Where-Object { $_ -ne '' })
if ($LASTEXITCODE -ne 0) { Write-Output "roadmap-recheck: launch options not readable; runner not started"; exit 1 }
if ($GhAccount -and $options -notcontains '-GhAccount') { $options += @('-GhAccount', $GhAccount) }

# The global agy spend cap applies to the agy engine only (a claude run needs no spend-cap file).
$engineAt = [array]::IndexOf($options, '-Engine')
$engine = if ($engineAt -ge 0 -and $engineAt + 1 -lt $options.Count) { $options[$engineAt + 1] } else { 'claude' }
if ($engine -eq 'agy') {
    & $py $spendPy check
    if ($LASTEXITCODE -ne 0) { Write-Output "roadmap-recheck: spend check exit $LASTEXITCODE; runner not started"; exit 1 }
}

$shell = (Get-Process -Id $PID).Path
$argv = @('-NoProfile', '-File', "`"$runPs1`"", '-Roadmap', $Roadmap, '-Repo', "`"$repoArg`"") + $options
$start = @{ FilePath = $shell; ArgumentList = $argv }
if ($IsWindows -or $env:OS -eq 'Windows_NT') { $start['WindowStyle'] = 'Hidden' }
Start-Process @start
Write-Output "roadmap-recheck: started roadmap-run.ps1 -Roadmap $Roadmap $($options -join ' ') (lock was $state)"
exit 0
