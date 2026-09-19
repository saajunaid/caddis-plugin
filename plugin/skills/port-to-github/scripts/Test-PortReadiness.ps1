<#
.SYNOPSIS
  Inspect a staged repository and list what will break or leak when it moves to GitHub.

.DESCRIPTION
  Reads <staging>\<Name>\mirror.git (written by Get-PortSource.ps1). Changes nothing.
  Writes <staging>\<Name>\readiness.json and prints a report.

  BLOCKERS (exit 1): a file over 100 MB anywhere in history, Git LFS content, a workflow
  containing an empty expression, a likely live credential in the current tree.
  WARNINGS: everything a human must decide: CI credentials, dependency hosts, runner labels,
  hardcoded references to the old host, secret-looking files in past history.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Name,
    [string]$StagingRoot,
    [string]$ConfigPath
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PortCommon.ps1')

$config = Get-PortConfig $ConfigPath
$stage = Join-Path (Get-PortStagingRoot $config $StagingRoot) $Name
$mirror = Join-Path $stage 'mirror.git'
if (-not (Test-Path -LiteralPath $mirror)) { throw "No staged mirror at $mirror. Run Get-PortSource.ps1 first." }
$manifest = Get-Content -LiteralPath (Join-Path $stage 'manifest.json') -Raw | ConvertFrom-Json
$branch = $manifest.defaultBranch

$blockers = New-Object System.Collections.Generic.List[string]
$warnings = New-Object System.Collections.Generic.List[string]
$report = [ordered]@{ name = $Name; defaultBranch = $branch; checkedAt = (Get-Date).ToString('o') }

function MGit([string[]]$a) { Invoke-PortGit (@('-C', $mirror) + $a) }
function MGitTry([string[]]$a) { Invoke-PortGit -AllowFailure (@('-C', $mirror) + $a) }

# ---- 1. Size: GitHub refuses any blob over 100 MB, in ANY commit, not just the tip ----------
Write-PortStep 'Checking object sizes across all history'
$big = @()
foreach ($line in (MGit @('cat-file', '--batch-all-objects', '--batch-check=%(objecttype) %(objectsize) %(objectname)'))) {
    $t, $s, $o = $line -split ' '
    if ($t -eq 'blob' -and [int64]$s -gt 50MB) { $big += [pscustomobject]@{ sha = $o; bytes = [int64]$s } }
}
if ($big.Count -gt 0) {
    $paths = @{}
    foreach ($l in (MGit @('rev-list', '--objects', '--all'))) {
        $sha, $p = $l -split ' ', 2
        if ($p -and ($big.sha -contains $sha)) { $paths[$sha] = $p }
    }
    foreach ($b in $big) {
        $p = $paths[$b.sha]
        $mb = [math]::Round($b.bytes / 1MB, 1)
        if ($b.bytes -gt 100MB) { $blockers.Add("File over 100 MB in history: $p ($mb MB). GitHub rejects the push. Rewrite history (git filter-repo) or move it to LFS/releases first.") }
        else { $warnings.Add("Large file in history: $p ($mb MB). GitHub warns above 50 MB.") }
    }
}
$report.largeBlobs = $big.Count

# ---- 2. LFS ---------------------------------------------------------------------------------
$attrs = MGitTry @('show', "${branch}:.gitattributes")
if ($attrs.ExitCode -eq 0 -and (($attrs.Output -join "`n") -match 'filter=lfs')) {
    $blockers.Add('The repository uses Git LFS. LFS objects are not in a git mirror; push them separately (git lfs fetch --all from the source, git lfs push --all to GitHub) before declaring the port done.')
}

# ---- 3. Secrets ---------------------------------------------------------------------------------
Write-PortStep 'Scanning for credentials'
$liveSecretPatterns = @('gh[pousr]_[A-Za-z0-9]{36,}', 'github_pat_[A-Za-z0-9_]{40,}', 'AKIA[0-9A-Z]{16}', '-----BEGIN [A-Z ]*PRIVATE KEY-----', 'xox[baprs]-[A-Za-z0-9-]{10,}')
$grepArgs = @('grep', '-I', '-l', '-E')
$liveHits = @()
foreach ($p in $liveSecretPatterns) {
    $g = MGitTry ($grepArgs + @('-e', $p, $branch))
    if ($g.ExitCode -eq 0) { $liveHits += $g.Output }
}
foreach ($h in ($liveHits | Sort-Object -Unique)) { $blockers.Add("Likely live credential in the current tree: $h. Remove it and ROTATE it; history still holds it.") }

# The same patterns across ALL history. A token committed once and deleted later is gone from
# the tip but still readable by anyone who can clone the new repo. -G matches commits whose
# diff adds or removes a matching line (extended regex).
$histPattern = $liveSecretPatterns -join '|'
$histOut = @(MGit @('log', '--all', "-G$histPattern", '--format=@@%h', '--name-only'))
$cur = $null
$histHits = @{}
foreach ($l in $histOut) {
    if (-not $l) { continue }
    if ($l.StartsWith('@@')) { $cur = $l.Substring(2); continue }
    if (-not $histHits.ContainsKey($l)) { $histHits[$l] = @() }
    $histHits[$l] += $cur
}
foreach ($file in ($histHits.Keys | Sort-Object)) {
    $tipName = "${branch}:$file"
    if ($liveHits -contains $tipName) { continue }   # already reported as a current-tree blocker
    $blockers.Add("Likely credential in PAST history: $file (commit(s) $(($histHits[$file] | Select-Object -Unique) -join ', ')). It is gone from the tip but ships with the history. ROTATE it, then either accept that or rewrite history (git filter-repo) before publishing.")
}
$report.historySecretFiles = @($histHits.Keys)

$pwHits = MGitTry @('grep', '-I', '-l', '-i', '-E', '-e', '(password|passwd|pwd|api[_-]?key|secret)[[:space:]]*[:=][[:space:]]*[''"][^''" ]{8,}[''"]', $branch)
if ($pwHits.ExitCode -eq 0) {
    foreach ($h in $pwHits.Output) { $warnings.Add("Possible hardcoded password or key: $h. Check it is a placeholder or test value.") }
}

$treeFiles = @(MGit @('ls-tree', '-r', '--name-only', $branch))
foreach ($f in $treeFiles) {
    if (Test-PortSecretName (Split-Path $f -Leaf)) { $warnings.Add("Secret-type file tracked in the current tree: $f. Check it holds no real value.") }
}
$histNames = @(MGit @('log', '--all', '--format=', '--name-only') | Where-Object { $_ } | Sort-Object -Unique)
$histSecret = @($histNames | Where-Object { (Test-PortSecretName (Split-Path $_ -Leaf)) -and ($treeFiles -notcontains $_) })
foreach ($f in $histSecret) { $warnings.Add("Secret-type file existed in PAST history: $f. It will be public to anyone who can read the new repo. Rotate what it held, or rewrite history first.") }

# ---- 4. CI ----------------------------------------------------------------------------------
Write-PortStep 'Inventorying CI'
$ciFiles = @($treeFiles | Where-Object {
        $_ -match '^\.(gitea|github|forgejo)/workflows/[^/]+\.ya?ml$' -or
        $_ -in @('.gitlab-ci.yml', 'Jenkinsfile', 'azure-pipelines.yml', 'bitbucket-pipelines.yml', '.drone.yml', '.woodpecker.yml')
    })
$report.ciFiles = $ciFiles
$workflows = @()
foreach ($f in $ciFiles) {
    $text = (MGit @('show', "${branch}:$f")) -join "`n"
    $lines = $text -split "`n"
    $wf = [ordered]@{ file = $f; emptyExpressions = @(); credentialLines = @(); runsOn = @(); hosts = @(); dispatchOnly = $false }
    for ($i = 0; $i -lt $lines.Count; $i++) {
        $ln = $lines[$i]
        if ($ln -match '\$\{\{\s*\}\}') { $wf.emptyExpressions += ($i + 1) }
        if ($ln -match 'secrets\.|github\.token|(?i)token\s*:|_TOKEN\b|_USER\b|PASSWORD') { $wf.credentialLines += ("{0}: {1}" -f ($i + 1), $ln.Trim()) }
        if ($ln -match '^\s*runs-on:\s*(.+)$') { $wf.runsOn += $Matches[1].Trim() }
        foreach ($m in [regex]::Matches($ln, 'https?://([A-Za-z0-9.-]+(:\d+)?)')) { $wf.hosts += $m.Groups[1].Value }
    }
    $wf.runsOn = @($wf.runsOn | Sort-Object -Unique)
    $wf.hosts = @($wf.hosts | Where-Object { $_ -notmatch '^(github\.com|api\.github\.com|localhost|127\.0\.0\.1)' } | Sort-Object -Unique)
    if ($text -match '(?m)^on:\s*(\[\s*)?workflow_dispatch' -and $text -notmatch '(?m)^\s+(push|pull_request)\s*:') { $wf.dispatchOnly = $true }
    if ($wf.emptyExpressions.Count -gt 0) {
        $msg = "$f has an empty `${{ }} on line(s) $($wf.emptyExpressions -join ', '). GitHub rejects the WHOLE file (startup_failure, zero jobs), even inside a comment in a run: block."
        # GitHub parses only .github/workflows. A .gitea/.forgejo file is inert on GitHub until
        # phase 4 copies it, so it is a warning here and a blocker there.
        if ($f -like '.github/*') { $blockers.Add($msg) } else { $warnings.Add("$msg Fix it when translating (phase 4).") }
    }
    if ($wf.dispatchOnly) { $warnings.Add("$f triggers only on workflow_dispatch. If this is a FROZEN copy, generate the GitHub workflow from the last live version in history instead.") }
    if ($wf.hosts.Count -gt 0) { $warnings.Add("$f references non-GitHub host(s): $($wf.hosts -join ', '). Each needs a credential that works FROM GitHub's runners, or the step breaks.") }
    $workflows += [pscustomobject]$wf
}
$report.workflows = $workflows
# Workflows already under .github/workflows RUN on GitHub the moment their branch is pushed.
# Check every branch, not only the default one: a push of any branch fires its own workflows.
$liveOnPush = @()
foreach ($h in @(MGit @('for-each-ref', '--format=%(refname:short)', 'refs/heads'))) {
    $ls = MGitTry @('ls-tree', '--name-only', "${h}:.github/workflows")
    if ($ls.ExitCode -eq 0 -and ($ls.Output -join '')) { $liveOnPush += $h }
}
$report.branchesWithGithubWorkflows = $liveOnPush
if ($liveOnPush.Count -gt 0) {
    $warnings.Add("$($liveOnPush.Count) branch(es) already contain .github/workflows ($($liveOnPush -join ', ')). Publishing PUSHES them, which fires every push-triggered workflow - including any deploy job. Publish refuses unless you pass -AllowWorkflowRuns after reading those workflows.")
}

$otherCi = @($ciFiles | Where-Object { $_ -notmatch '^\.(gitea|github|forgejo)/workflows/' })
if ($otherCi.Count -gt 0) {
    $warnings.Add("Non-Actions CI found ($($otherCi -join ', ')). It will not run on GitHub; it must be rewritten as a GitHub Actions workflow.")
}
if ($ciFiles.Count -eq 0) { $warnings.Add('No CI found. After the port nothing builds, tests or deploys this app automatically.') }

# ---- 5. Dependencies that live on another host --------------------------------------------------
Write-PortStep 'Checking dependency pins'
$depHosts = @()
foreach ($f in ($treeFiles | Where-Object { $_ -match '(^|/)(pyproject\.toml|requirements[^/]*\.txt|setup\.cfg|package\.json|\.npmrc|\.pypirc|pip\.conf|go\.mod|Cargo\.toml)$' })) {
    $text = (MGit @('show', "${branch}:$f")) -join "`n"
    foreach ($m in [regex]::Matches($text, '(git\+)?(https?|ssh)://(?:[^@/\s]+@)?([A-Za-z0-9.-]+(:\d+)?)/')) {
        $h = $m.Groups[3].Value
        if ($h -match '^(pypi\.org|files\.pythonhosted\.org|registry\.npmjs\.org|github\.com)$') {
            if ($h -eq 'github.com' -and $m.Groups[1].Value) { $depHosts += [pscustomobject]@{ file = $f; host = $h } }
            continue
        }
        $depHosts += [pscustomobject]@{ file = $f; host = $h }
    }
    if ($text -match '(?m)^\s*registry\s*=') { $warnings.Add("$f sets a custom package registry. CI on GitHub needs a credential for it, or the install fails.") }
}
$report.dependencyHosts = $depHosts
foreach ($h in ($depHosts | Group-Object host)) {
    $warnings.Add("Dependencies pinned from $($h.Name) in: $((($h.Group.file) | Sort-Object -Unique) -join ', '). CI and every deploy host need a read credential for THAT host, chosen per host.")
}

# ---- 6. References to the old host --------------------------------------------------------------
$oldHost = $null
if ($manifest.sourceKind -eq 'url') {
    if ($manifest.source -match '^[a-z]+://(?:[^@/]+@)?(?<h>[^/:]+)') { $oldHost = $Matches.h }
    elseif ($manifest.source -match '^[^@\s]+@(?<h>[^:\s]+):') { $oldHost = $Matches.h }   # scp form: git@host:org/repo.git
}
if ($oldHost) {
    $ref = MGitTry @('grep', '-I', '-l', '-F', '-e', $oldHost, $branch)
    if ($ref.ExitCode -eq 0) {
        $files = @($ref.Output | ForEach-Object { $_ -replace "^${branch}:", '' })
        $report.oldHostReferences = $files
        $warnings.Add("$($files.Count) file(s) still name the old host $oldHost ($($files[0..([math]::Min(4, $files.Count - 1))] -join ', ')$(if ($files.Count -gt 5) { ', ...' })). Decide per file: a dependency pin (keep, needs a credential) or an origin reference (change).")
    }
}

# ---- 7. Carry forward what the source step found -----------------------------------------------
foreach ($w in $manifest.warnings) { $warnings.Add($w) }

$report.blockers = @($blockers)
$report.warnings = @($warnings)
$report.ready = ($blockers.Count -eq 0)
ConvertTo-PortJsonFile $report (Join-Path $stage 'readiness.json')

Write-Host ''
Write-Host "Readiness for $Name (branch $branch): $($blockers.Count) blocker(s), $($warnings.Count) warning(s)"
foreach ($b in $blockers) { Write-PortFail $b }
foreach ($w in $warnings) { Write-PortWarn $w }
foreach ($wf in $workflows) {
    if ($wf.credentialLines.Count -gt 0) {
        Write-Host ''
        Write-Host "Credential lines in $($wf.file) - classify EACH as ORIGIN (becomes github.token) or DEPENDENCY (keeps a token for that host):"
        $wf.credentialLines | ForEach-Object { Write-Host "    $_" }
    }
    if ($wf.runsOn.Count -gt 0) { Write-Host "Runner labels in $($wf.file): $($wf.runsOn -join ' | ') - confirm GitHub has runners with these labels." }
}
Write-Host "    report: $(Join-Path $stage 'readiness.json')"
if ($blockers.Count -gt 0) { exit 1 }
exit 0
