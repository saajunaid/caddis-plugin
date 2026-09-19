<#
.SYNOPSIS
  Check a staged repository against the source-only content policy, over the tips AND all history.

.DESCRIPTION
  The policy: a repository holds application code, configuration and templates, migration
  SCRIPTS, tests, and the scripts/manifests that rebuild the environment. It does NOT hold:

    runtime      a runtime or server distribution (MariaDB, PHP, JDK, Node, Python, Apache...)
    binary       compiled or packaged files (.exe .dll .so .jar .msi, archives)
    db-data      database data files (ibdata1, *.ibd, *.frm, *.mdf, SQLite files, dumps)
    data-export  data files above the size threshold (.csv .xlsx .json .xml .sql ...), or any
                 data file under a backups/dumps/exports folder
    dependency   installed dependencies (node_modules, vendor, .venv, site-packages)
    backup       editor and copy backups (*.bak, *.orig, *.old, *~)

  Large files that match no rule are reported as 'large-review' (a decision, not a violation).

  .gitignore does not remove a file that was committed before it: every excluded path is
  checked in ALL history, not only in the current files.

  Reads <staging>\<Name>\mirror.git. Changes nothing. Writes content-policy.json next to it.
  Exit 0: compliant. Exit 1: at least one excluded path exists somewhere in history.

  Project overrides (optional) in the config file, key "contentPolicy":
    { "keep": ["regex", ...], "exclude": ["regex", ...], "dataThresholdMB": 5, "largeMB": 10 }
  Regexes match the repository path (forward slashes).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Name,
    [string]$StagingRoot,
    [string]$ConfigPath,
    [double]$DataThresholdMB,
    [double]$LargeMB,
    # Print every finding, not only the per-folder summary.
    [switch]$Detail
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PortCommon.ps1')

$config = Get-PortConfig $ConfigPath
$stage = Join-Path (Get-PortStagingRoot $config $StagingRoot) $Name
$mirror = Join-Path $stage 'mirror.git'
if (-not (Test-Path -LiteralPath $mirror)) { throw "No staged mirror at $mirror. Run Get-PortSource.ps1 first." }
$manifest = Get-Content -LiteralPath (Join-Path $stage 'manifest.json') -Raw | ConvertFrom-Json
$branch = $manifest.defaultBranch

$policy = Get-PortConfigValue $config 'contentPolicy' $null
$keepRx = @(); $extraExcludeRx = @()
if ($policy) {
    if ($policy.PSObject.Properties.Name -contains 'keep') { $keepRx = @($policy.keep) }
    if ($policy.PSObject.Properties.Name -contains 'exclude') { $extraExcludeRx = @($policy.exclude) }
    if (-not $DataThresholdMB -and $policy.PSObject.Properties.Name -contains 'dataThresholdMB') { $DataThresholdMB = [double]$policy.dataThresholdMB }
    if (-not $LargeMB -and $policy.PSObject.Properties.Name -contains 'largeMB') { $LargeMB = [double]$policy.largeMB }
}
if (-not $DataThresholdMB) { $DataThresholdMB = 5 }
if (-not $LargeMB) { $LargeMB = 10 }
$dataBytes = [int64]($DataThresholdMB * 1MB)
$largeBytes = [int64]($LargeMB * 1MB)

# A runtime folder is the runtime's NAME, optionally followed by a version or platform tag
# (php-8.3.33, jdk-17.0.2, node-v20.11.0-win-x64, apache24). Not any folder that merely STARTS
# with one: redis-migrations/ or apache-poi-wrapper/ are source.
$ver = '([-_ ]?v?\d[\w.]*(-(win|linux|x64|x86|amd64|arm64)[\w.-]*)?)?'
$runtimeDirRx = "(?i)^(mariadb|mysql|mysql-server|php|jdk|jre|openjdk|java|python|python-embed|nodejs|node|apache|httpd|nginx|tomcat|apache-tomcat|redis|postgres|postgresql|pgsql|erlang|ruby|dotnet|go)$ver$"
$runtimeBinRx = '(?i)^(mariadbd|mysqld|mariadb|mysql|php|php-cgi|node|python|pythonw|java|javaw|httpd|nginx|redis-server|postgres|pg_ctl|erl|ruby|dotnet)\.exe$'
$dependencyDirRx = '(?i)^(node_modules|vendor|\.venv|venv|site-packages|bower_components|\.yarn|jspm_packages)$'
$binaryExtRx = '(?i)\.(exe|dll|so|dylib|msi|msix|bin|iso|img|jar|war|ear|class|pyc|pdb|lib|a|o|obj|zip|7z|tar|gz|tgz|rar|bz2|xz|cab|nupkg|whl|deb|rpm)$'
$dbDataRx = '(?i)(^|/)(ibdata\d*|ib_logfile\d*|ib_buffer_pool|aria_log[\w.]*|undo\d+)$|\.(ibd|frm|myd|myi|mdf|ldf|ndf|sqlite3?|db3|dmp)$'
$backupRx = '(?i)(\.(bak|orig|old|swp)|~)$'
$dataExtRx = '(?i)\.(csv|tsv|xlsx|xlsm|xlsb|xls|ods|parquet|avro|orc|jsonl|ndjson|json|xml|sql|dat|txt|log)$'
$dataDirRx = '(?i)^(backups?|dumps?|exports?|snapshots?|data-?dumps?)$'

function Get-Category([string]$Path, [int64]$Bytes) {
    foreach ($rx in $keepRx) { if ($Path -match $rx) { return $null } }
    foreach ($rx in $extraExcludeRx) { if ($Path -match $rx) { return 'project-exclude' } }
    $parts = $Path -split '/'
    $dirs = if ($parts.Count -gt 1) { $parts[0..($parts.Count - 2)] } else { @() }
    $leaf = $parts[-1]
    foreach ($d in $dirs) { if ($d -match $runtimeDirRx) { return 'runtime' } }
    if ($leaf -match $runtimeBinRx) { return 'runtime' }
    foreach ($d in $dirs) { if ($d -match $dependencyDirRx) { return 'dependency' } }
    if ($Path -match $dbDataRx) { return 'db-data' }
    if ($leaf -match $backupRx) { return 'backup' }
    if ($leaf -match $binaryExtRx) { return 'binary' }
    if ($leaf -match $dataExtRx) {
        # Under a backups/dumps folder any data file is excluded, but a plain note (.txt/.md) is not data.
        if ($leaf -notmatch '(?i)\.(txt|md)$') { foreach ($d in $dirs) { if ($d -match $dataDirRx) { return 'data-export' } } }
        # Migration SCRIPTS stay by policy. A large .sql under migration(s)/ may be a script or a
        # data load, so it is a decision, not an automatic exclusion. Data FILES there (csv, json,
        # xlsx) are still data.
        if ($leaf -match '(?i)\.sql$' -and ($dirs | Where-Object { $_ -match '(?i)^migrations?$' })) {
            if ($Bytes -ge $largeBytes -or $Bytes -ge $dataBytes) { return 'large-review' }
            return $null
        }
        if ($Bytes -ge $dataBytes) { return 'data-export' }
    }
    if ($Bytes -ge $largeBytes) { return 'large-review' }
    return $null
}

function MGit([string[]]$a) { Invoke-PortGit (@('-C', $mirror) + $a) }

# ---- every blob in history, with every path it ever had ----------------------------------
Write-PortStep 'Reading every path and blob in history'
$pathsBySha = @{}
$submodules = New-Object System.Collections.Generic.HashSet[string]
function Add-PathForSha([string]$sha, [string]$p) {
    if (-not $pathsBySha.ContainsKey($sha)) { $pathsBySha[$sha] = New-Object System.Collections.Generic.HashSet[string] }
    [void]$pathsBySha[$sha].Add($p)
}
# EVERY path a blob was ever written to. rev-list --objects names each blob only ONCE, by the
# first path it meets, so identical content at a second path was invisible (found by the
# dogfood: a 3-byte test image at two paths survived a clean). log --raw lists every add or
# change, per commit, including merges (-m) and root commits.
foreach ($l in (MGit @('-c', 'core.quotePath=false', 'log', '--all', '--raw', '--no-abbrev', '--no-renames', '-m', '--root', '--format=', '--diff-filter=AMT'))) {
    if (-not $l -or $l[0] -ne ':') { continue }
    $meta, $p = $l -split "`t", 2
    $f = $meta -split ' '
    if ($f.Count -lt 4 -or -not $p -or $f[3] -match '^0+$') { continue }
    # Mode 160000 is a submodule: its "blob" is a commit in ANOTHER repository, invisible to a
    # size scan. Record it, so a runtime vendored as a submodule cannot pass unnoticed.
    if ($f[1] -eq '160000') { [void]$submodules.Add($p); continue }
    Add-PathForSha $f[3] $p
}
# Safety net: anything reachable that the log did not show.
foreach ($l in (MGit @('rev-list', '--objects', '--all'))) {
    $sha, $p = $l -split ' ', 2
    if ($p -and -not $pathsBySha.ContainsKey($sha)) { Add-PathForSha $sha $p }
}
$sizeBySha = @{}
foreach ($l in (MGit @('cat-file', '--batch-all-objects', '--batch-check=%(objecttype) %(objectname) %(objectsize)'))) {
    $t, $o, $s = $l -split ' '
    if ($t -eq 'blob' -and $pathsBySha.ContainsKey($o)) { $sizeBySha[$o] = [int64]$s }
}

# Aggregate per path: largest version, number of versions.
$byPath = @{}
foreach ($sha in $sizeBySha.Keys) {
    foreach ($p in $pathsBySha[$sha]) {
        if (-not $byPath.ContainsKey($p)) { $byPath[$p] = [pscustomobject]@{ path = $p; maxBytes = [int64]0; versions = 0 } }
        $e = $byPath[$p]; $e.versions++
        if ($sizeBySha[$sha] -gt $e.maxBytes) { $e.maxBytes = $sizeBySha[$sha] }
    }
}

$tipFiles = @{}
foreach ($l in (MGit @('-c', 'core.quotePath=false', 'ls-tree', '-r', '--name-only', $branch))) { $tipFiles[$l] = $true }

# ---- classify ----------------------------------------------------------------------------------
$findings = New-Object System.Collections.Generic.List[object]
foreach ($e in $byPath.Values) {
    $cat = Get-Category $e.path $e.maxBytes
    if (-not $cat) { continue }
    $findings.Add([pscustomobject]@{
            path = $e.path; category = $cat; maxBytes = $e.maxBytes; versions = $e.versions
            inDefaultBranch = [bool]$tipFiles[$e.path]
            action = if ($cat -eq 'large-review') { 'review' } else { 'exclude' }
        })
}
foreach ($sm in $submodules) {
    $findings.Add([pscustomobject]@{ path = $sm; category = 'submodule'; maxBytes = [int64]0; versions = 1; inDefaultBranch = [bool]$tipFiles[$sm]; action = 'review' })
}
$exclude = @($findings | Where-Object { $_.action -eq 'exclude' })
$review = @($findings | Where-Object { $_.action -eq 'review' })

# Group by top two path segments so a 3,000-file vendored runtime reads as one line.
# Group by folder, at most 4 levels deep, so one vendored runtime reads as one line and a
# data folder deep in an app is still named precisely.
function Get-Group([string]$p) { $s = $p -split '/'; if ($s.Count -le 1) { return $p }; $d = $s[0..([math]::Min(3, $s.Count - 2))]; ($d -join '/') + '/' }
$groups = @($findings | Group-Object { "$($_.category)|$(Get-Group $_.path)" } | ForEach-Object {
        $cat, $grp = $_.Name -split '\|', 2
        [pscustomobject]@{
            category = $cat; group = $grp; files = $_.Count
            historyMB = [math]::Round((($_.Group | Measure-Object maxBytes -Sum).Sum) / 1MB, 1)
            inDefaultBranch = @($_.Group | Where-Object { $_.inDefaultBranch }).Count
        }
    } | Sort-Object historyMB -Descending)

$totalBytes = [int64]0; foreach ($v in $sizeBySha.Values) { $totalBytes += $v }
# Count each blob once, even when it sits at several excluded paths (a per-path sum can exceed
# the whole history). Plain loops: Measure-Object on NO input has no .Sum under strict mode.
$exPaths = New-Object System.Collections.Generic.HashSet[string]
foreach ($x in $exclude) { [void]$exPaths.Add($x.path) }
$exBytes = [int64]0
foreach ($sha in $sizeBySha.Keys) { foreach ($p in $pathsBySha[$sha]) { if ($exPaths.Contains($p)) { $exBytes += $sizeBySha[$sha]; break } } }
$report = [ordered]@{
    name = $Name; defaultBranch = $branch; checkedAt = (Get-Date).ToString('o')
    thresholds = [ordered]@{ dataThresholdMB = $DataThresholdMB; largeMB = $LargeMB }
    historyBlobMB = [math]::Round($totalBytes / 1MB, 1)
    excludedPaths = $exclude.Count; excludedMB = [math]::Round($exBytes / 1MB, 1)
    reviewPaths = $review.Count
    compliant = ($exclude.Count -eq 0)
    groups = $groups
    findings = @($findings | Sort-Object maxBytes -Descending)
}
ConvertTo-PortJsonFile $report (Join-Path $stage 'content-policy.json')
# Plain path list, one per line, for Invoke-PortHistoryClean.ps1 and for .gitignore review.
Set-Content -LiteralPath (Join-Path $stage 'content-policy-exclude.txt') -Value @($exclude | Sort-Object path | ForEach-Object { $_.path }) -Encoding UTF8

Write-Host ''
Write-Host ("Content policy for {0}: {1} excluded path(s), {2} MB of history; {3} path(s) to review. History holds {4} MB of blobs in total." -f $Name, $exclude.Count, $report.excludedMB, $review.Count, $report.historyBlobMB)
if ($groups.Count -gt 0) {
    Write-Host ''
    Write-Host ('{0,-13} {1,-55} {2,7} {3,10} {4}' -f 'category', 'where', 'files', 'MB', 'in default branch')
    foreach ($g in $groups) { Write-Host ('{0,-13} {1,-55} {2,7} {3,10} {4}' -f $g.category, $g.group, $g.files, $g.historyMB, $g.inDefaultBranch) }
}
if ($Detail) { $findings | Sort-Object maxBytes -Descending | ForEach-Object { Write-Host ('  {0,-13} {1,9:N0} KB  {2}' -f $_.category, ($_.maxBytes / 1KB), $_.path) } }
Write-Host "    report: $(Join-Path $stage 'content-policy.json')"
Write-Host "    exclude list: $(Join-Path $stage 'content-policy-exclude.txt')"
if ($exclude.Count -gt 0) {
    Write-PortWarn 'Not compliant. Decide per group: keep (add a "keep" regex to contentPolicy), or remove from history with Invoke-PortHistoryClean.ps1. Adding a path to .gitignore does NOT remove it from history.'
    exit 1
}
Write-PortOk 'Compliant: no excluded content anywhere in history.'
exit 0
