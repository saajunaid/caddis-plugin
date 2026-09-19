<#
.SYNOPSIS
  Remove excluded paths from the STAGED repository's history, then prove they are gone.

.DESCRIPTION
  Works only on <staging>\<Name>\mirror.git. The source is never touched.

  -Mode Rewrite     keep every branch, tag and commit, minus the excluded paths. Commit SHAs
                    change from the first commit that touched an excluded path onward, so
                    anything that quotes an old SHA (a deploy record, a tag note) stops matching.
                    Uses git filter-repo if installed, otherwise git filter-branch.
  -Mode FreshStart  one new commit holding the default branch's current files minus the excluded
                    paths. All other branches, tags and history are dropped. Smallest, simplest,
                    and loses the history - an owner decision.

  Paths come from content-policy-exclude.txt (written by Test-PortContentPolicy.ps1) unless
  -PathsFile is given. Afterwards it re-runs Test-PortContentPolicy.ps1, which must exit 0, and
  rewrites manifest.json's heads and tags so Publish's stage-drift check sees the cleaned refs.
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][string]$Name,
    [Parameter(Mandatory)][ValidateSet('Rewrite', 'FreshStart')][string]$Mode,
    [string]$PathsFile,
    [string]$StagingRoot,
    [string]$ConfigPath
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PortCommon.ps1')

$config = Get-PortConfig $ConfigPath
$stage = Join-Path (Get-PortStagingRoot $config $StagingRoot) $Name
$mirror = Join-Path $stage 'mirror.git'
$manifestPath = Join-Path $stage 'manifest.json'
if (-not (Test-Path -LiteralPath $mirror)) { throw "No staged mirror at $mirror." }
if (-not $PathsFile) { $PathsFile = Join-Path $stage 'content-policy-exclude.txt' }
if (-not (Test-Path -LiteralPath $PathsFile)) { throw "No paths file at $PathsFile. Run Test-PortContentPolicy.ps1 first." }
$paths = @(Get-Content -LiteralPath $PathsFile | Where-Object { $_ -and $_.Trim() })
if ($paths.Count -eq 0) { Write-PortOk 'Nothing to remove.'; exit 0 }
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$branch = $manifest.defaultBranch

# git reads pathspecs as patterns; ":(literal)" makes every entry an exact path, so a file
# named with [ ] * ? is never widened into a glob that removes something else.
$specFile = Join-Path $stage 'history-clean-pathspec.txt'
[IO.File]::WriteAllLines($specFile, [string[]]@($paths | ForEach-Object { ":(literal)$_" }), (New-Object Text.UTF8Encoding($false)))

$before = @(Invoke-PortGit @('-C', $mirror, 'for-each-ref', '--format=%(refname) %(objectname)', 'refs/heads', 'refs/tags'))
if (-not $PSCmdlet.ShouldProcess($mirror, "$Mode history, removing $($paths.Count) path(s)")) { exit 0 }

if ($Mode -eq 'Rewrite') {
    $fr = Invoke-PortGit -AllowFailure @('filter-repo', '--version')
    if ($fr.ExitCode -eq 0) {
        Write-PortStep "Rewriting with git filter-repo ($($paths.Count) path(s))"
        $plain = Join-Path $stage 'history-clean-paths.txt'
        [IO.File]::WriteAllLines($plain, [string[]]$paths, (New-Object Text.UTF8Encoding($false)))
        Invoke-PortGit @('-C', $mirror, 'filter-repo', '--force', '--invert-paths', '--paths-from-file', $plain) | Out-Null
    }
    else {
        Write-PortStep "Rewriting with git filter-branch ($($paths.Count) path(s)); git filter-repo is not installed"
        $env:FILTER_BRANCH_SQUELCH_WARNING = '1'
        # The index filter is eval'd by a shell. Pass the path through an environment variable, so a
        # quote in it (C:\Users\O'Brien\...) cannot break the command.
        $env:PORT_PATHSPEC_FILE = $specFile.Replace('\', '/')
        try {
            $idx = 'git rm -r --cached --ignore-unmatch --quiet --pathspec-from-file="$PORT_PATHSPEC_FILE"'
            Invoke-PortGit @('-C', $mirror, 'filter-branch', '-f', '--index-filter', $idx, '--prune-empty', '--tag-name-filter', 'cat', '--', '--all') | Out-Null
        }
        finally { Remove-Item Env:FILTER_BRANCH_SQUELCH_WARNING, Env:PORT_PATHSPEC_FILE -ErrorAction SilentlyContinue }
        foreach ($r in @(Invoke-PortGit @('-C', $mirror, 'for-each-ref', '--format=%(refname)', 'refs/original'))) {
            if ($r) { Invoke-PortGit @('-C', $mirror, 'update-ref', '-d', $r) | Out-Null }
        }
    }
}
else {
    Write-PortStep "Fresh start: one commit from $branch minus $($paths.Count) path(s)"
    $tmpIndex = Join-Path $stage 'fresh.index'
    # git rm needs a work tree even with --cached; a bare mirror has none, so lend it an empty one.
    $tmpWork = Join-Path $stage 'fresh-worktree'
    New-Item -ItemType Directory -Force -Path $tmpWork | Out-Null
    $env:GIT_INDEX_FILE = $tmpIndex
    $env:GIT_WORK_TREE = $tmpWork
    try {
        Invoke-PortGit @('-C', $mirror, 'read-tree', $branch) | Out-Null
        Invoke-PortGit @('-C', $mirror, 'rm', '-r', '--cached', '--ignore-unmatch', '--quiet', "--pathspec-from-file=$specFile") | Out-Null
        $tree = (Invoke-PortGit @('-C', $mirror, 'write-tree')) -join ''
    }
    finally {
        Remove-Item Env:GIT_INDEX_FILE, Env:GIT_WORK_TREE -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $tmpIndex -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $tmpWork -Recurse -Force -ErrorAction SilentlyContinue
    }
    $msg = "Initial import of $Name (fresh start: history not carried over)"
    $body = "Source: $($manifest.source), branch $branch at $((Invoke-PortGit @('-C', $mirror, 'rev-parse', $branch)) -join ''). $($paths.Count) path(s) excluded by the content policy."
    $commit = (Invoke-PortGit @('-C', $mirror, 'commit-tree', $tree, '-m', $msg, '-m', $body)) -join ''
    foreach ($r in @(Invoke-PortGit @('-C', $mirror, 'for-each-ref', '--format=%(refname)', 'refs/heads', 'refs/tags'))) {
        if ($r) { Invoke-PortGit @('-C', $mirror, 'update-ref', '-d', $r) | Out-Null }
    }
    Invoke-PortGit @('-C', $mirror, 'update-ref', "refs/heads/$branch", $commit) | Out-Null
    Invoke-PortGit @('-C', $mirror, 'symbolic-ref', 'HEAD', "refs/heads/$branch") | Out-Null
}

# Drop the unreachable objects, so a later readiness scan measures what will actually be pushed.
Invoke-PortGit @('-C', $mirror, 'reflog', 'expire', '--expire=now', '--all') | Out-Null
Invoke-PortGit @('-C', $mirror, 'gc', '--prune=now', '--quiet') | Out-Null

$after = @(Invoke-PortGit @('-C', $mirror, 'for-each-ref', '--format=%(refname) %(objectname)', 'refs/heads', 'refs/tags'))
$manifest.heads = @(Invoke-PortGit @('-C', $mirror, 'for-each-ref', '--format=%(refname:short) %(objectname)', 'refs/heads'))
$manifest.tags = @(Invoke-PortGit @('-C', $mirror, 'for-each-ref', '--format=%(refname:short) %(objectname)', 'refs/tags'))
$manifest | Add-Member -NotePropertyName historyClean -NotePropertyValue ([pscustomobject]@{
        mode = $Mode; at = (Get-Date).ToString('o'); pathsRemoved = $paths.Count
        refsBefore = $before.Count; refsAfter = $after.Count
        note = 'Commit SHAs changed. The source still holds the original history.'
    }) -Force
ConvertTo-PortJsonFile $manifest $manifestPath

# The proof: the policy must now pass. A clean that cannot fail is not a clean.
Write-PortStep 'Re-checking the content policy on the cleaned history'
& (Join-Path $PSScriptRoot 'Test-PortContentPolicy.ps1') -Name $Name -StagingRoot $StagingRoot -ConfigPath $ConfigPath
if ($LASTEXITCODE -ne 0) { Write-PortFail 'Excluded content is STILL in history after the clean. Do not publish.'; exit 1 }
Write-PortOk ("History cleaned ({0}): refs {1} -> {2}. Re-run Test-PortReadiness.ps1 before publishing." -f $Mode, $before.Count, $after.Count)
exit 0
