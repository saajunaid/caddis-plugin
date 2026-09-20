<#
.SYNOPSIS
    Phase 1. Read an existing app and write inventory.json. Changes nothing, runs nothing.

.DESCRIPTION
    An app that never went through a project generator is usually the only copy of
    something that is already running. This script only READS: file metadata, the text of
    small manifests and config files, git state, and what the host has registered to run
    the folder. It never executes an entry point, an installer or a build.

    It also refuses to let a partial answer look like a clean one. Walking a folder over a
    network share can hit a file budget or an access denial. When that happens the script
    reports the size as a MINIMUM, marks the scan partial and exits 1 unless you pass
    -AllowPartial. A truncated scan that exits 0 is how a 140 GB data tree gets called
    "about 200 MB" and committed.

    File CONTENTS never reach inventory.json. A config file holds credentials and an
    artefact gets copied into tickets and chats, so only the path, the line and the key
    NAME are recorded.

.PARAMETER Path
    The app folder. A local path, a UNC share, or a path on the remote box when you pass
    -ComputerName.

.PARAMETER ComputerName
    Scan on this box over WinRM. Use it when the app lives on a server: a UNC scan works
    but is slow, and the host facts (services, scheduled tasks, web sites) can only be
    read on the box itself.

.EXAMPLE
    ./Get-AppInventory.ps1 -Path E:\legacy-app
.EXAMPLE
    ./Get-AppInventory.ps1 -Path G:\apps\batch-engine -ComputerName appserver01 -FileBudget 5000
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Path,
    [string]$Name,
    [string]$ComputerName,
    [string]$OutDir,
    [int]$FileBudget = 0,
    [int]$ProbeBudget = 4000,
    # Top-level folders to leave unscanned by name. Use it for a tree you already know is
    # bulk data, so the budget is spent on the folders whose contents are still a question.
    # They are recorded as not-scanned, never as empty.
    [string[]]$SkipFolder = @(),
    [switch]$AllowPartial,
    [switch]$SkipHostFacts
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'AdoptCommon.ps1')

if (-not $Name) { $Name = (Split-Path $Path -Leaf) -replace '[^A-Za-z0-9._-]', '-' }
$dir = Resolve-AdoptOutDir -Name $Name -OutDir $OutDir

# The project config supplies the defaults; a parameter always wins. Reading it here is what
# makes those keys real - a config value nothing consults is a promise the code does not keep.
$cfg = Get-AdoptConfig
if ($FileBudget -le 0) { $FileBudget = [int]$cfg.fileBudget }
if ($SkipFolder.Count -eq 0) { $SkipFolder = @($cfg.skipFolders) }

Write-AdoptHeading "Inventory: $Name"
Write-Host "  source      : $Path$(if ($ComputerName) { "  (on $ComputerName)" })"
Write-Host "  file budget : $FileBudget per top-level folder"
Write-Host "  nothing in the source is written, and nothing in it is executed."

$scan = Invoke-AdoptScan -Path $Path -ComputerName $ComputerName -FileBudget $FileBudget `
    -ProbeBudget $ProbeBudget -SkipFolders $SkipFolder -SkipPattern $cfg.skipPattern

if (-not $scan.exists) {
    Write-Error "Source not found: $Path$(if ($ComputerName) { " on $ComputerName" }). $($scan.partialReason -join '; ')"
    exit 1
}

$hostFacts = $null
if (-not $SkipHostFacts) {
    try { $hostFacts = Get-AdoptRunRegistrations -Path $Path -ComputerName $ComputerName }
    catch { Write-Warning "Could not read host registrations: $($_.Exception.Message)" }
}

$kind = 'local'
if ($ComputerName) { $kind = 'winrm' }
elseif ($Path -match '^\\\\') { $kind = 'unc' }

$inventory = [ordered]@{
    name         = $Name
    scannedAt    = (Get-Date).ToUniversalTime().ToString('o')
    scannedBy    = 'adopt-app/Get-AppInventory.ps1'
    source       = [ordered]@{ kind = $kind; path = $Path; computerName = $ComputerName }
    partial      = [bool]$scan.partial
    partialReason = @($scan.partialReason)
    size         = [ordered]@{
        totalMB       = $scan.totalMB
        totalMBIsMinimum = [bool]$scan.partial
        totalFiles    = $scan.totalFiles
        folders       = @($scan.folders | Sort-Object { -1 * $_.mb })
    }
    git          = $scan.git
    # A shallow index of ordinary paths, used only by profile detection in phase 2.
    paths        = @($scan.paths)
    manifests    = @($scan.manifests)
    entryPoints  = @($scan.entryPoints)
    configFiles  = @($scan.configFiles)
    secretsSuspected = @($scan.secretFiles)
    certificates = @($scan.certificates)
    excludable   = @($scan.excludable)
    reparsePoints = @($scan.reparse)
    tests        = [ordered]@{ files = $scan.testFiles; markers = @($scan.testMarkers) }
    ci           = @($scan.ciFiles)
    docs         = @($scan.docFiles)
    healthSignals = @($scan.healthHits)
    runRegistrations = $hostFacts
}

# Roll the excludable file list up per top folder. A list of 40,000 paths is unreadable and
# the decision is taken per folder anyway.
# Grouped by folder, category AND whether git tracks the file. A folder is routinely both:
# committed documents beside a gigabyte of correctly-ignored output. Rolling those together
# and labelling the total with the folder's state turned 0.15 MB of committed markdown into
# a report of "1018 MB of data exports are committed".
$byFolder = @{}
foreach ($e in @($scan.excludable)) {
    $top = ($e.path -split '[\\/]')[0]
    $isTracked = [bool](Get-AdoptProp $e 'tracked' $false)
    $key = "$top|$($e.category)|$isTracked"
    if (-not $byFolder.ContainsKey($key)) { $byFolder[$key] = @{ folder = $top; category = $e.category; tracked = $isTracked; files = 0; bytes = [long]0 } }
    $byFolder[$key].files++
    $byFolder[$key].bytes += [long]$e.bytes
}
$inventory.excludableSummary = @($byFolder.Values |
        ForEach-Object { [ordered]@{ folder = $_.folder; category = $_.category; tracked = $_.tracked; files = $_.files; mb = [math]::Round($_.bytes / 1MB, 2) } } |
        Sort-Object { -1 * $_.mb })
$inventory.trackedKnown = [bool](Get-AdoptProp $scan 'trackedKnown' $false)

$out = Write-AdoptArtifact -Dir $dir -FileName 'inventory.json' -Object $inventory

# ---- report ---------------------------------------------------------------------------
Write-AdoptHeading 'Size'
if ($inventory.size.totalMBIsMinimum) { Write-Host "  total AT LEAST $($inventory.size.totalMB) MB in $($inventory.size.totalFiles)+ files - the scan did not finish" -ForegroundColor Yellow }
else { Write-Host "  total $($inventory.size.totalMB) MB in $($inventory.size.totalFiles) files" }
foreach ($f in @($inventory.size.folders | Select-Object -First 12)) {
    $flag = ''
    if ($f.skipped) { $flag = '  [NOT SCANNED - you passed -SkipFolder]' }
    elseif ($f.truncated) { $flag = '  [truncated - at least this size]' }
    elseif ($f.denied) { $flag = '  [access denied somewhere inside - at least this size]' }
    Write-Host ("    {0,10:N1} MB  {1,8} files  {2,-12} {3}{4}" -f $f.mb, $f.files, $f.git, $f.path, $flag)
}

Write-AdoptHeading 'Git'
if ($inventory.git.isRepo -and -not (Get-AdoptProp $inventory.git 'gitAvailable' $false)) {
    Write-Host "  repo     : there is a .git folder, but GIT IS NOT AVAILABLE where the scan ran." -ForegroundColor Red
    Write-Host "             Branches, remotes and which folders are tracked are UNKNOWN, not clean." -ForegroundColor Red
    Write-Host "             Install git on that box, or scan a local copy, before trusting anything below." -ForegroundColor Red
}
elseif ($inventory.git.isRepo) {
    $remotes = @($inventory.git.remotes | ForEach-Object { "$($_.name) -> $($_.url)" })
    Write-Host "  repo     : yes, $($inventory.git.commits) commits on $($inventory.git.branch)"
    Write-Host "  remotes  : $(if ($remotes.Count) { $remotes -join '; ' } else { 'NONE - this folder is the only copy' })"
    Write-Host "  refs     : $($inventory.git.localBranches) local branches, $($inventory.git.remoteBranches) remote-tracking, $($inventory.git.tags) tags"
    Write-Host "  dirty    : $($inventory.git.dirtyFiles) files"
    if ($null -ne $inventory.git.unpushed -and $inventory.git.unpushed -gt 0) {
        Write-Host "  UNPUSHED : $($inventory.git.unpushed) commits ahead of $($inventory.git.upstream)" -ForegroundColor Yellow
    }
}
else { Write-Host "  repo     : NO - there is no history to port; adoption starts with one import commit" -ForegroundColor Yellow }

if ($inventory.git.isRepo) {
    $wts = @(Get-AdoptProp $inventory.git 'worktrees' @())
    $stashes = [int](Get-AdoptProp $inventory.git 'stashes' 0)
    if ($wts.Count -gt 1 -or $stashes -gt 0) {
        Write-AdoptHeading 'Worktrees and stashes'
        foreach ($w in $wts) {
            $what = if ($w.branch) { "on $($w.branch)" } else { "DETACHED at $("$($w.head)".Substring(0,9))" }
            $dirty = if ($null -eq $w.dirtyFiles) { 'unreadable' } else { "$($w.dirtyFiles) uncommitted" }
            $tag = if ($w.isMain) { '  (the main checkout)' } else { '' }
            Write-Host ("    {0,-58} {1,-34} {2}{3}" -f $w.path, $what, $dirty, $tag)
        }
        if ($stashes -gt 0) {
            Write-Host "    $stashes stash entr(ies) - `refs/stash` is NOT copied by a clone or a push." -ForegroundColor Yellow
        }
    }

    # THE ONE THAT LOSES WORK. A mirror copies refs/heads/* and refs/tags/*; a detached
    # HEAD is neither, so its commits are not carried - and with nothing pointing at them,
    # git may collect them. Found on a real app: 200 commits of certified work on two
    # detached worktrees, under a path its own docs called a recurring cleanup hazard.
    $unreachable = @(Get-AdoptProp $inventory.git 'unreachableCommits' @())
    if ($unreachable.Count -gt 0) {
        Write-AdoptHeading 'COMMITS NO PORT WOULD CARRY'
        Write-Host "  These worktrees are on a DETACHED HEAD that no branch and no tag points at." -ForegroundColor Red
        Write-Host "  A clone copies branches and tags. These are neither, so they would be left" -ForegroundColor Red
        Write-Host "  behind - and git is free to delete them." -ForegroundColor Red
        foreach ($u in $unreachable) {
            $n = if ($u.commits) { "$($u.commits) commits" } else { 'unknown depth' }
            Write-Host ("    {0}`n      HEAD {1}  ({2})" -f $u.path, "$($u.head)".Substring(0,9), $n) -ForegroundColor Red
        }
        Write-Host ""
        Write-Host "  FIX IT BEFORE PORTING - one command each, and it changes nothing else:" -ForegroundColor Yellow
        foreach ($u in $unreachable) {
            $leaf = (Split-Path $u.path -Leaf) -replace '[^A-Za-z0-9._-]', '-'
            Write-Host "    git -C <repo> branch rescue/$leaf $("$($u.head)".Substring(0,9))" -ForegroundColor Yellow
        }
    }
}

# Neither committed nor ignored. This is the state that turns one careless `git add -A`
# into gigabytes of runtime data in the history for ever, and no filename pattern finds
# it - only git can tell an undeclared data tree from a source folder.
$untracked = @($inventory.size.folders | Where-Object { $_.git -eq 'untracked' -and $_.mb -ge 1 -and $_.path -ne '.git' })
if ($untracked.Count -gt 0) {
    Write-AdoptHeading 'Neither committed nor ignored'
    Write-Host "  These folders are not in the repository AND not in .gitignore. One 'git add -A'" -ForegroundColor Yellow
    Write-Host "  commits them permanently. Decide each one: commit it, ignore it, or move it out." -ForegroundColor Yellow
    foreach ($u in $untracked) { Write-Host ("    {0,10:N1} MB  {1,8} files  {2}" -f $u.mb, $u.files, $u.path) -ForegroundColor Yellow }
}

$ignoredBig = @($inventory.size.folders | Where-Object { $_.git -eq 'ignored' -and $_.mb -ge 200 })
if ($ignoredBig.Count -gt 0) {
    Write-AdoptHeading 'Correctly ignored, but the app needs them'
    Write-Host "  Excluding these is right. It is only SAFE once something says how to get them back." -ForegroundColor DarkYellow
    foreach ($i in $ignoredBig) { Write-Host ("    {0,10:N1} MB  {1}" -f $i.mb, $i.path) }
}

Write-AdoptHeading 'What the repository must not carry'
if ($inventory.excludableSummary.Count -eq 0) { Write-Host "  nothing found" }
foreach ($e in @($inventory.excludableSummary | Select-Object -First 15)) {
    $state = if ($e.tracked) { 'COMMITTED' } else { 'not committed' }
    $colour = if ($e.tracked) { 'Yellow' } else { 'Gray' }
    Write-Host ("    {0,10:N1} MB  {1,7} files  {2,-13} {3,-14} {4}" -f $e.mb, $e.files, $e.category, $state, $e.folder) -ForegroundColor $colour
}
Write-Host "  Only the COMMITTED rows need a history rewrite. The rest need a .gitignore line," -ForegroundColor DarkGray
Write-Host "  or already have one." -ForegroundColor DarkGray

Write-AdoptHeading 'Possible credentials'
if ($inventory.secretsSuspected.Count -eq 0) { Write-Host "  none found by the heuristics - which is not the same as none present" }
foreach ($s in @($inventory.secretsSuspected | Select-Object -First 25)) {
    # Two traps in one line. A hashtable's PSObject.Properties are Keys/Values/Count and
    # never its entries, so testing them showed a line number for nothing. And under
    # StrictMode, reading a key that is absent THROWS - a name-only record has no 'line',
    # so the whole inventory died after printing most of its report.
    $where = $s.path
    $hasLine = if ($s -is [hashtable]) { $s.ContainsKey('line') } else { @($s.PSObject.Properties.Name) -contains 'line' }
    if ($hasLine -and $s.line) { $where = "$($s.path):$($s.line)  key '$($s.key)'" }
    Write-Host "    $where   ($($s.why))" -ForegroundColor Yellow
}
if ($inventory.certificates.Count -gt 0) {
    Write-Host "  $($inventory.certificates.Count) key container(s) hold a PUBLIC certificate, not a key - not a finding:" -ForegroundColor DarkGray
    foreach ($c in @($inventory.certificates | Select-Object -First 8)) { Write-Host "    $c" -ForegroundColor DarkGray }
}

if ($inventory.reparsePoints.Count -gt 0) {
    Write-AdoptHeading 'Junctions and symlinks'
    Write-Host "  These were NOT followed. A junction inside a tree that git manages is a data-loss" -ForegroundColor Yellow
    Write-Host "  hazard: git's recursive remove follows it and deletes the TARGET's contents." -ForegroundColor Yellow
    foreach ($r in @($inventory.reparsePoints | Select-Object -First 15)) { Write-Host "    $($r.path)" }
}

if ($hostFacts) {
    Write-AdoptHeading 'What runs it'
    $any = $false
    foreach ($s in @($hostFacts.services)) { $any = $true; Write-Host "    service        $($s.name)  [$($s.state)/$($s.startMode)] as $($s.account)" }
    foreach ($t in @($hostFacts.scheduledTasks)) { $any = $true; Write-Host "    scheduled task $($t.path)$($t.name)  [$($t.state)] as $($t.account); last run $($t.lastRun)" }
    foreach ($w in @($hostFacts.webSites)) { $any = $true; Write-Host "    web site       $($w.name)  -> $($w.physicalPath)" }
    if (-not $any) {
        Write-Host "    nothing on $(if ($ComputerName) { $ComputerName } else { 'this machine' }) references this folder." -ForegroundColor Yellow
        Write-Host "    If the app IS running, it runs somewhere else. Find out where before you adopt it." -ForegroundColor Yellow
    }
    foreach ($e in @($hostFacts.errors)) { Write-Host "    (could not check $e)" -ForegroundColor DarkYellow }
}

Write-Host ""
Write-Host "  wrote $out"

if ($inventory.partial) {
    Write-Host ""
    Write-Host "SCAN INCOMPLETE. Sizes above are MINIMUMS:" -ForegroundColor Red
    foreach ($r in @($inventory.partialReason)) { Write-Host "  - $r" -ForegroundColor Red }
    Write-Host "Raise -FileBudget, or accept it with -AllowPartial once you know what is in those folders." -ForegroundColor Red
    if (-not $AllowPartial) { exit 1 }
    Write-Host "Accepted with -AllowPartial; inventory.json records partial=true." -ForegroundColor Yellow
}

exit 0
