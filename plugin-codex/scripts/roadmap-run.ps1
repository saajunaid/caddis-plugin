# roadmap-run - start one fresh headless session per batch, until a stop. A thin shim over caddis_roadmap_run.py
# (design: .caddis/plans/programme-method-design.md sections 8.2 and 8.5; caddis-next Phase 9).
# -Plan runs a plain plan (plan mode). -Roadmap runs the next batches of a roadmap on origin (roadmap mode). Give one.
# -PrintRecheckTask prints a PowerShell block (Register-ScheduledTask) that registers roadmap-recheck.ps1 every 2 hours;
# it registers nothing.
# Usage: roadmap-run.ps1 (-Plan <slug> | -Roadmap <slug>) [-Repo <path>] [-MaxHours 10] [-MaxSessions 12]
#          [-SessionTimeoutMin 120] [-MaxUsdPerSession 25] [-MaxUsdTotal 150]
#          [-Engine claude] [-Model opus] [-GhAccount <gh login>] [-DryRun]
#        roadmap-run.ps1 -Roadmap <slug> [-Repo <path>] -PrintRecheckTask
#        roadmap-run.ps1 -Roadmap <slug> [-Repo <path>] -AcceptRoadmap [-DryRun] [-Yes]   (owner only: accept an owner
#          edit made during
#          a merge wait as the new baseline)
param(
    [string]$Plan = '',
    [string]$Roadmap = '',
    [string]$Repo = (Get-Location).Path,
    [double]$MaxHours = 10,
    [int]$MaxSessions = 12,
    [double]$SessionTimeoutMin = 120,
    [double]$MaxUsdPerSession = 25,
    [double]$MaxUsdTotal = 150,
    [ValidateSet('claude', 'agy', 'codex')][string]$Engine = 'claude',
    [string]$Model = '',
    [switch]$DryRun,
    [string]$GhAccount = '',
    [switch]$PrintRecheckTask,
    [switch]$AcceptRoadmap,
    [switch]$Yes
)
if ([bool]$Plan -eq [bool]$Roadmap) { Write-Error "roadmap-run: give exactly one of -Plan <slug> and -Roadmap <slug>"; exit 4 }
$SlugRule = '^[a-z0-9][a-z0-9-]{0,62}$'  # = caddis_roadmap.SLUG_RE_TEXT (a test keeps the three equal)
if ($GhAccount -and $GhAccount -notmatch '^[A-Za-z0-9._-]+$') {
    Write-Error "roadmap-run: -GhAccount must be a gh login name (got '$GhAccount')"; exit 4
}
if ($Roadmap -and $Roadmap -cnotmatch $SlugRule) {
    Write-Error "roadmap-run: -Roadmap must match $SlugRule (got '$Roadmap')"; exit 4
}
if ($PrintRecheckTask) {
    if (-not $Roadmap) { Write-Error "roadmap-run: -PrintRecheckTask needs -Roadmap <slug>"; exit 4 }
    # A PowerShell block for the owner to paste: every value is a single-quoted literal (a ' is doubled), and the
    # task's whole argument line is ONE string, so no shell splits it.
    if (-not (Test-Path -LiteralPath $Repo -PathType Container)) {
        Write-Error "roadmap-run: -Repo '$Repo' is not a folder; nothing printed"; exit 4
    }
    $recheck = (Resolve-Path (Join-Path $PSScriptRoot 'roadmap-recheck.ps1')).Path
    # A full path with no trailing separator: in a quoted command-line argument a trailing `\` would escape the quote. A
    # drive root keeps one `\`, doubled so it stays a backslash in front of the closing quote.
    $repoFull = (Resolve-Path -LiteralPath $Repo).Path.TrimEnd('\', '/')
    if ($repoFull -match '^[A-Za-z]:$') { $repoFull += '\\' }
    $shellExe = (Get-Process -Id $PID).Path
    function Sq([string]$s) { "'" + $s.Replace("'", "''") + "'" }
    $argLine = "-NoProfile -NonInteractive -File `"$recheck`" -Roadmap $Roadmap -Repo `"$repoFull`""
    if ($GhAccount) { $argLine += " -GhAccount $GhAccount" }
    Write-Output "`$action = New-ScheduledTaskAction -Execute $(Sq $shellExe) -Argument $(Sq $argLine)"
    Write-Output "`$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 2)"
    Write-Output ("Register-ScheduledTask -TaskName $(Sq "caddis-roadmap-recheck-$Roadmap") -Action `$action " +
        "-Trigger `$trigger -Description $(Sq "caddis roadmap $Roadmap recheck, every 2 hours")")
    Write-Output ("# Note: this task runs only while you are logged on. To run it whether you are logged on or not, " +
        "add -User <DOMAIN\user> -Password <password> to Register-ScheduledTask, or set that option in Task Scheduler.")
    exit 0
}
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { Write-Error "roadmap-run: python not found on PATH"; exit 3 }
# Installed plugin: both files sit in scripts/. Source repo: the Python file is in <repo>/scripts.
$runner = Join-Path $PSScriptRoot 'caddis_roadmap_run.py'
if (-not (Test-Path $runner)) { $runner = Join-Path $PSScriptRoot '..\..\scripts\caddis_roadmap_run.py' }
if (-not (Test-Path $runner)) { Write-Error "roadmap-run: caddis_roadmap_run.py not found"; exit 4 }
$inv = [Globalization.CultureInfo]::InvariantCulture
$argv = @($runner)
if ($Plan) { $argv += @('--plan', $Plan) } else { $argv += @('--roadmap', $Roadmap) }
$argv += @('--repo', $Repo,
    '--max-hours', $MaxHours.ToString($inv), '--max-sessions', $MaxSessions.ToString($inv),
    '--session-timeout-min', $SessionTimeoutMin.ToString($inv),
    '--max-usd-per-session', $MaxUsdPerSession.ToString($inv), '--max-usd-total', $MaxUsdTotal.ToString($inv),
    '--engine', $Engine)
if ($Model) { $argv += @('--model', $Model) }
if ($DryRun) { $argv += '--dry-run' }
if ($AcceptRoadmap) {  # owner only: the Python side refuses it headless
    if (-not $Roadmap) { Write-Error "roadmap-run: -AcceptRoadmap needs -Roadmap <slug>"; exit 4 }
    $acceptArgs = @('--roadmap', $Roadmap, '--repo', $Repo, '--accept-roadmap')
    if ($DryRun) { $acceptArgs += '--dry-run' }  # print the diff, write nothing
    if ($Yes) { $acceptArgs += '--yes' }  # no console confirmation
    & $py $runner @acceptArgs
    exit $LASTEXITCODE
}
if ($GhAccount) { $argv += @('--gh-account', $GhAccount) }
& $py @argv
exit $LASTEXITCODE
