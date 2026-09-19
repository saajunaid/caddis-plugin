<#
.SYNOPSIS
  Copy an app from ANY source into a local staging bare repository, ready to push to GitHub.

.DESCRIPTION
  Source kinds, detected from -Source:
    url    https://, http://, ssh://, git://, or user@host:path   (Gitea, GitLab, Bitbucket, any git server)
    local  a folder on this machine, with or without a .git
    unc    \\server\share\folder, with or without a .git
    winrm  winrm://HOST/C:/path, or -ComputerName HOST with -Source C:\path

  Every kind ends in the same place: <staging>\<Name>\mirror.git, a bare repository holding
  only refs/heads/* and refs/tags/*, with NO remote configured (so a stray push can never go
  back to the source), plus <staging>\<Name>\manifest.json describing what was found.

  The source is never modified. A folder without git history becomes one import commit.

.EXAMPLE
  ./Get-PortSource.ps1 -Source http://gitea.example:3000/org/app.git
  ./Get-PortSource.ps1 -Source D:\work\app -IncludeUncommitted
  ./Get-PortSource.ps1 -Source \\fileserver\projects\app
  ./Get-PortSource.ps1 -Source winrm://prodbox/D:/apps/app
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Source,
    [string]$ComputerName,
    [pscredential]$Credential,
    [string]$Name,
    [string]$StagingRoot,
    [string]$ConfigPath,
    # Put uncommitted and untracked changes on a separate branch instead of leaving them behind.
    [switch]$IncludeUncommitted,
    # Turn remote-tracking branches of this remote (e.g. 'origin') into real branches when the
    # source has no local branch of that name. Use when a checkout is the only surviving copy.
    [string]$PromoteRemoteBranches,
    # What to do when a plain folder or an uncommitted snapshot contains a likely secret.
    [ValidateSet('Stop', 'Exclude')][string]$OnSecret = 'Stop',
    [string]$InitialBranch = 'main',
    # Replace an existing staging folder for this Name.
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PortCommon.ps1')

$config = Get-PortConfig $ConfigPath
$stagingBase = Get-PortStagingRoot $config $StagingRoot

# ---- 1. Work out what kind of source this is -------------------------------------------
$remotePath = $null
if ($Source -match '^winrm://(?<host>[^/]+)/(?<path>.+)$') {
    $ComputerName = $Matches.host
    $remotePath = ($Matches.path -replace '/', '\')
}
elseif ($ComputerName) {
    $remotePath = $Source
}

if ($ComputerName) { $kind = 'winrm' }
elseif ($Source -match '^(https?|ssh|git)://' -or $Source -match '^[^@\s\\/]+@[^:\s]+:') { $kind = 'url' }
elseif ($Source -match '^\\\\') { $kind = 'unc' }
else { $kind = 'local' }

if (-not $Name) {
    $leaf = ($Source.TrimEnd('/', '\') -split '[\\/:]')[-1]
    $Name = $leaf -replace '\.git$', ''
}
if ($Name -notmatch '^[A-Za-z0-9._-]+$') { throw "Name '$Name' is not a valid GitHub repository name. Pass -Name." }

$stage = Join-Path $stagingBase $Name
if (Test-Path -LiteralPath $stage) {
    if (-not $Force) { throw "Staging folder $stage already exists. Pass -Force to replace it." }
    Remove-Item -LiteralPath $stage -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $stage | Out-Null
$mirror = Join-Path $stage 'mirror.git'
$work = Join-Path $stage 'work'

$manifest = [ordered]@{
    name                 = $Name
    sourceKind           = $kind
    source               = (Remove-UrlCredential $Source).Url
    computerName         = $ComputerName
    capturedAt           = (Get-Date).ToString('o')
    hadGitHistory        = $false
    sourceHead           = $null
    defaultBranch        = $null
    dirtyFiles           = @()
    snapshotBranch       = $null
    remoteOnlyBranches   = @()
    promotedBranches     = @()
    droppedRefs          = @()
    secretFindings       = @()
    excludedSecretFiles  = @()
    suspectDirs          = @()
    largeFiles           = @()
    heads                = @()
    tags                 = @()
    status               = 'in-progress'
    warnings             = @()
}
if ((Remove-UrlCredential $Source).HadCredential) {
    $manifest.warnings += 'The source URL embedded a credential. It was used for the clone and is not recorded. Consider rotating it.'
}

function Save-Manifest { ConvertTo-PortJsonFile $manifest (Join-Path $stage 'manifest.json') }

# ---- helpers used by more than one kind ---------------------------------------------------

function Find-Secrets([string]$Root, [string[]]$RelativeFiles) {
    $found = @()
    foreach ($rel in $RelativeFiles) {
        $full = Join-Path $Root $rel
        if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { continue }
        $leafName = Split-Path $rel -Leaf
        if (Test-PortSecretName $leafName) {
            $found += [pscustomobject]@{ file = ($rel -replace '\\', '/'); reason = 'file name' }
            continue
        }
        $info = Get-Item -LiteralPath $full
        if ($info.Length -gt 1MB) { continue }
        $text = $null
        try { $text = [IO.File]::ReadAllText($full) } catch { continue }
        if ($text -match "`0") { continue }   # binary
        $hit = Test-PortSecretContent $text
        if ($hit) { $found += [pscustomobject]@{ file = ($rel -replace '\\', '/'); reason = "content matches $hit" } }
    }
    return , $found
}

function Resolve-Secrets([string]$Root, [string[]]$RelativeFiles, [string]$Context) {
    $found = Find-Secrets $Root $RelativeFiles
    if ($found.Count -eq 0) { return @() }
    $manifest.secretFindings += $found
    foreach ($f in $found) { Write-PortWarn "Likely secret in ${Context}: $($f.file) ($($f.reason))" }
    if ($OnSecret -eq 'Stop') {
        $manifest.status = 'blocked-secrets'
        Save-Manifest
        Write-PortFail "Stopped: $($found.Count) likely secret file(s). Nothing was pushed anywhere. Review them, then re-run with -OnSecret Exclude to leave them out, or move the secret out of the file."
        exit 2
    }
    foreach ($f in $found) {
        Remove-Item -LiteralPath (Join-Path $Root $f.file) -Force
        $manifest.excludedSecretFiles += $f.file
    }
    return @($found | ForEach-Object { $_.file })
}

function Copy-Tree([string]$From, [string]$To) {
    New-Item -ItemType Directory -Force -Path $To | Out-Null
    $xd = @($script:PortJunkDirs)
    & robocopy $From $To /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP /XJ /XD @xd | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy $From -> $To failed with exit $LASTEXITCODE" }
    $global:LASTEXITCODE = 0
}

function Import-PlainTree([string]$Tree) {
    # A folder with no history becomes ONE import commit on $InitialBranch.
    $files = @(Get-ChildItem -LiteralPath $Tree -Recurse -File -Force | ForEach-Object { $_.FullName.Substring($Tree.Length).TrimStart('\', '/') })
    if ($files.Count -eq 0) { throw "The source folder has no files to import." }
    $excluded = @(Resolve-Secrets $Tree $files 'the source folder')

    foreach ($d in $script:PortSuspectDirs) {
        if (Test-Path -LiteralPath (Join-Path $Tree $d) -PathType Container) { $manifest.suspectDirs += $d }
    }
    foreach ($f in (Get-ChildItem -LiteralPath $Tree -Recurse -File -Force | Where-Object { $_.Length -gt 50MB })) {
        $manifest.largeFiles += [pscustomobject]@{ file = $f.FullName.Substring($Tree.Length).TrimStart('\'); bytes = $f.Length }
    }

    $gi = Join-Path $Tree '.gitignore'
    $ignoreLines = @()
    if (-not (Test-Path -LiteralPath $gi)) {
        $ignoreLines += '# Written by port-to-github for a folder that had no .gitignore.'
        $ignoreLines += ($script:PortJunkDirs | Where-Object { $_ -ne '.git' } | ForEach-Object { "$_/" })
        $ignoreLines += @('.env', '.env.*', '!.env.example', '*.log')
    }
    if ($excluded.Count -gt 0) {
        $ignoreLines += '# Likely secrets left out of the import by port-to-github:'
        $ignoreLines += ($excluded | ForEach-Object { "/$_" })
    }
    if ($ignoreLines.Count -gt 0) { Add-Content -LiteralPath $gi -Value $ignoreLines -Encoding UTF8 }

    Invoke-PortGit @('init', '-q', '-b', $InitialBranch, $Tree) | Out-Null
    $email = Invoke-PortGit -AllowFailure @('-C', $Tree, 'config', 'user.email')
    if ($email.ExitCode -ne 0 -or -not ($email.Output -join '')) {
        throw "git has no user.email for this folder. Set your identity (git config --global user.email ...) and re-run."
    }
    # A brand-new repository built from a copied folder: adding everything IS the import.
    Invoke-PortGit @('-C', $Tree, 'add', '-A') | Out-Null
    Invoke-PortGit @('-C', $Tree, 'commit', '-q', '-m', "Import $Name from a $kind folder (no prior git history)", '-m', "Source: $($manifest.source)") | Out-Null
    Invoke-PortGit @('clone', '-q', '--mirror', $Tree, $mirror) | Out-Null
}

function Add-Snapshot([string]$DirtyRoot, [string[]]$Changed, [string[]]$Deleted, [string]$BaseRef) {
    # Uncommitted work goes on its OWN branch, so the real branches stay exactly as committed.
    $snapTree = Join-Path $work 'snapshot'
    Invoke-PortGit @('clone', '-q', $mirror, $snapTree) | Out-Null
    Invoke-PortGit @('-C', $snapTree, 'checkout', '-q', '--detach', $BaseRef) | Out-Null
    $branch = 'port/uncommitted-snapshot-' + (Get-Date -Format 'yyyyMMdd-HHmm')
    Invoke-PortGit @('-C', $snapTree, 'checkout', '-q', '-b', $branch) | Out-Null
    foreach ($rel in $Changed) {
        $src = Join-Path $DirtyRoot $rel
        if (-not (Test-Path -LiteralPath $src -PathType Leaf)) { continue }
        $dst = Join-Path $snapTree $rel
        New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent) | Out-Null
        Copy-Item -LiteralPath $src -Destination $dst -Force
    }
    foreach ($rel in $Deleted) {
        $dst = Join-Path $snapTree $rel
        if (Test-Path -LiteralPath $dst) { Remove-Item -LiteralPath $dst -Force }
    }
    $excluded = @(Resolve-Secrets $snapTree $Changed 'the uncommitted changes')
    foreach ($rel in $excluded) { Invoke-PortGit -AllowFailure @('-C', $snapTree, 'rm', '-q', '--cached', '--ignore-unmatch', '--', $rel) | Out-Null }
    # A throwaway clone that holds only the snapshot: adding everything is the snapshot.
    Invoke-PortGit @('-C', $snapTree, 'add', '-A') | Out-Null
    $pending = Invoke-PortGit @('-C', $snapTree, 'status', '--porcelain')
    if (-not ($pending -join '')) { Write-PortWarn 'The uncommitted changes produced no difference. No snapshot branch.'; return }
    Invoke-PortGit @('-C', $snapTree, 'commit', '-q', '-m', "Snapshot of uncommitted work found in the source during the port", '-m', "Source: $($manifest.source). Base: $BaseRef.") | Out-Null
    Invoke-PortGit @('-C', $snapTree, 'push', '-q', $mirror, "HEAD:refs/heads/$branch") | Out-Null
    $manifest.snapshotBranch = $branch
    Write-PortOk "Uncommitted work saved on branch $branch"
}

# ---- 2. Acquire -----------------------------------------------------------------------------
Write-PortStep "Source kind: $kind"
switch ($kind) {
    'url' {
        Write-PortStep "Mirror-cloning $($manifest.source)"
        Invoke-PortGit @('clone', '-q', '--mirror', $Source, $mirror) | Out-Null
        $manifest.hadGitHistory = $true
    }
    { $_ -in 'local', 'unc' } {
        if (-not (Test-Path -LiteralPath $Source -PathType Container)) { throw "Folder not found: $Source" }
        $full = (Resolve-Path -LiteralPath $Source).ProviderPath.TrimEnd('\')
        $top = Invoke-PortGit -AllowFailure @('-C', $full, 'rev-parse', '--show-toplevel')
        $bare = Invoke-PortGit -AllowFailure @('-C', $full, 'rev-parse', '--is-bare-repository')
        $isBare = ($bare.ExitCode -eq 0 -and ($bare.Output -join '') -eq 'true')
        $isRepo = $isBare
        if (-not $isBare -and $top.ExitCode -eq 0) {
            $topPath = ($top.Output -join '').Replace('/', '\').TrimEnd('\')
            if ($topPath -ieq $full) { $isRepo = $true }
            else {
                throw "$full is a SUBFOLDER of the repository $topPath. Port the whole repository, or split the folder out first (git subtree split --prefix=<dir>) and port the result."
            }
        }
        if ($isRepo) {
            Write-PortStep "Folder is a git repository. Mirror-cloning it (history is kept)."
            Invoke-PortGit @('clone', '-q', '--mirror', '--no-local', $full, $mirror) | Out-Null
            $manifest.hadGitHistory = $true
            if (-not $isBare) {
                $headRes = Invoke-PortGit -AllowFailure @('-C', $full, 'symbolic-ref', '--short', 'HEAD')
                $manifest.sourceHead = if ($headRes.ExitCode -eq 0) { $headRes.Output -join '' } else { (Invoke-PortGit @('-C', $full, 'rev-parse', 'HEAD')) -join '' }
                $manifest.dirtyFiles = @(Invoke-PortGit @('-C', $full, 'status', '--porcelain', '--untracked-files=all'))
                if ($manifest.dirtyFiles.Count -gt 0) {
                    if ($IncludeUncommitted) {
                        $changed = @(Invoke-PortGit @('-C', $full, 'ls-files', '-m', '-o', '--exclude-standard'))
                        $deleted = @(Invoke-PortGit @('-C', $full, 'ls-files', '-d'))
                        $baseRef = (Invoke-PortGit @('-C', $full, 'rev-parse', 'HEAD')) -join ''
                        Add-Snapshot $full $changed $deleted $baseRef
                    }
                    else {
                        $manifest.warnings += "The source has $($manifest.dirtyFiles.Count) uncommitted change(s). They are NOT included. Re-run with -IncludeUncommitted to keep them on a separate branch."
                    }
                }
            }
        }
        else {
            Write-PortStep "Folder has no git history. Importing it as one commit."
            $tree = Join-Path $work 'tree'
            Copy-Tree $full $tree
            Import-PlainTree $tree
        }
    }
    'winrm' {
        Write-PortStep "Reading $remotePath on $ComputerName over WinRM"
        $sessArgs = @{ ComputerName = $ComputerName }
        if ($Credential) { $sessArgs.Credential = $Credential }
        $session = New-PSSession @sessArgs
        $remote = $null
        try {
            # Runs on the remote box under Windows PowerShell 5.1: keep it 5.1-compatible.
            $remote = Invoke-Command -Session $session -ArgumentList $remotePath, [bool]$IncludeUncommitted, $script:PortJunkDirs -ScriptBlock {
                param($Path, $WantDirty, $JunkDirs)
                # 'Continue', not 'Stop': under Windows PowerShell 5.1 a native command's stderr
                # becomes a TERMINATING error with 'Stop', even with 2>$null - so probing a plain
                # folder with git would kill the block. Git is judged by $LASTEXITCODE instead;
                # cmdlets that must not fail carry -ErrorAction Stop.
                $ErrorActionPreference = 'Continue'
                $r = @{ exists = $false; isRepo = $false; tmp = $null; bundle = $null; treeZip = $null; dirtyZip = $null; dirty = @(); changed = @(); deleted = @(); head = $null; headSha = $null; error = $null }
                if (-not (Test-Path -LiteralPath $Path -PathType Container)) { return $r }
                try {
                $r.exists = $true
                Add-Type -AssemblyName System.IO.Compression.FileSystem
                $tmp = Join-Path $env:TEMP ('port-to-github-' + [guid]::NewGuid().ToString('N'))
                New-Item -ItemType Directory -Path $tmp -ErrorAction Stop | Out-Null
                $r.tmp = $tmp
                $git = $null
                $cmd = Get-Command git -ErrorAction SilentlyContinue
                if ($cmd) { $git = $cmd.Source } elseif (Test-Path 'C:\Program Files\Git\cmd\git.exe') { $git = 'C:\Program Files\Git\cmd\git.exe' }
                $isRepo = $false
                $isBare = $false
                if ($git) {
                    # A BARE repository has no work tree, so --show-toplevel fails on it. Check
                    # for bare first, or the whole history is imported as one plain-folder commit.
                    $bareOut = & $git -c safe.directory=* -C $Path rev-parse --is-bare-repository 2>$null
                    if ($LASTEXITCODE -eq 0 -and "$bareOut" -eq 'true') { $isRepo = $true; $isBare = $true }
                }
                if ($git -and -not $isBare) {
                    $top = & $git -c safe.directory=* -C $Path rev-parse --show-toplevel 2>$null
                    if ($LASTEXITCODE -eq 0 -and $top) {
                        $topPath = ("$top").Replace('/', '\').TrimEnd('\')
                        if ($topPath -ieq ((Resolve-Path -LiteralPath $Path).ProviderPath.TrimEnd('\'))) { $isRepo = $true }
                        else { $r.error = "$Path is a subfolder of the repository $topPath"; return $r }
                    }
                }
                $r.isRepo = $isRepo
                if ($isRepo) {
                    $bundle = Join-Path $tmp 'repo.bundle'
                    & $git -c safe.directory=* -C $Path bundle create $bundle --all 2>&1 | Out-Null
                    if ($LASTEXITCODE -ne 0) { $r.error = "git bundle failed with exit $LASTEXITCODE"; return $r }
                    $r.bundle = $bundle
                    $h = & $git -c safe.directory=* -C $Path symbolic-ref --short HEAD 2>$null
                    if ($LASTEXITCODE -eq 0) { $r.head = "$h" }
                    $r.headSha = "$(& $git -c safe.directory=* -C $Path rev-parse HEAD)"
                    # A bare repository has no working tree, so nothing can be uncommitted.
                    if (-not $isBare) { $r.dirty = @(& $git -c safe.directory=* -C $Path status --porcelain --untracked-files=all) }
                    if ($WantDirty -and $r.dirty.Count -gt 0) {
                        $r.changed = @(& $git -c safe.directory=* -C $Path ls-files -m -o --exclude-standard)
                        $r.deleted = @(& $git -c safe.directory=* -C $Path ls-files -d)
                        $dd = Join-Path $tmp 'dirty'
                        New-Item -ItemType Directory -Path $dd -ErrorAction Stop | Out-Null
                        foreach ($rel in $r.changed) {
                            $src = Join-Path $Path $rel
                            if (-not (Test-Path -LiteralPath $src -PathType Leaf)) { continue }
                            $dst = Join-Path $dd $rel
                            New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent) -ErrorAction Stop | Out-Null
                            Copy-Item -LiteralPath $src -Destination $dst -Force -ErrorAction Stop
                        }
                        $r.dirtyZip = Join-Path $tmp 'dirty.zip'
                        [IO.Compression.ZipFile]::CreateFromDirectory($dd, $r.dirtyZip)
                    }
                }
                else {
                    $tree = Join-Path $tmp 'tree'
                    & robocopy $Path $tree /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP /XJ /XD @JunkDirs | Out-Null
                    if ($LASTEXITCODE -ge 8) { $r.error = "robocopy failed with exit $LASTEXITCODE"; return $r }
                    $r.treeZip = Join-Path $tmp 'tree.zip'
                    # ZipFile, not Compress-Archive: Compress-Archive's wildcard skips hidden files (.env, .gitignore).
                    [IO.Compression.ZipFile]::CreateFromDirectory($tree, $r.treeZip)
                }
                } catch { $r.error = "remote step failed: $($_.Exception.Message)" }
                return $r
            }
            if (-not $remote.exists) { throw "Folder not found on ${ComputerName}: $remotePath" }
            if ($remote.error) { throw "Remote read failed on ${ComputerName}: $($remote.error)" }
            New-Item -ItemType Directory -Force -Path $work | Out-Null
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            if ($remote.isRepo) {
                $localBundle = Join-Path $work 'repo.bundle'
                Copy-Item -FromSession $session -Path $remote.bundle -Destination $localBundle
                Invoke-PortGit @('bundle', 'verify', $localBundle) | Out-Null
                Invoke-PortGit @('clone', '-q', '--mirror', $localBundle, $mirror) | Out-Null
                $manifest.hadGitHistory = $true
                $manifest.sourceHead = if ($remote.head) { $remote.head } else { $remote.headSha }
                $manifest.dirtyFiles = @($remote.dirty)
                if ($manifest.dirtyFiles.Count -gt 0) {
                    if ($IncludeUncommitted -and $remote.dirtyZip) {
                        $localDirtyZip = Join-Path $work 'dirty.zip'
                        Copy-Item -FromSession $session -Path $remote.dirtyZip -Destination $localDirtyZip
                        $dirtyRoot = Join-Path $work 'dirty'
                        [IO.Compression.ZipFile]::ExtractToDirectory($localDirtyZip, $dirtyRoot)
                        Add-Snapshot $dirtyRoot @($remote.changed) @($remote.deleted) $remote.headSha
                    }
                    elseif (-not $IncludeUncommitted) {
                        $manifest.warnings += "The source has $($manifest.dirtyFiles.Count) uncommitted change(s). They are NOT included. Re-run with -IncludeUncommitted to keep them on a separate branch."
                    }
                }
            }
            else {
                $localZip = Join-Path $work 'tree.zip'
                Copy-Item -FromSession $session -Path $remote.treeZip -Destination $localZip
                $tree = Join-Path $work 'tree'
                [IO.Compression.ZipFile]::ExtractToDirectory($localZip, $tree)
                Import-PlainTree $tree
            }
        }
        finally {
            if ($session) {
                if ($remote -and $remote.tmp) {
                    Invoke-Command -Session $session -ArgumentList $remote.tmp -ScriptBlock { param($t) Remove-Item -LiteralPath $t -Recurse -Force -ErrorAction SilentlyContinue }
                }
                Remove-PSSession $session
            }
        }
    }
}

# ---- 3. Normalise the mirror to heads and tags only ---------------------------------------
$allRefs = @(Invoke-PortGit @('-C', $mirror, 'for-each-ref', '--format=%(refname)'))
$headNames = @($allRefs | Where-Object { $_ -like 'refs/heads/*' } | ForEach-Object { $_.Substring(11) })
foreach ($ref in ($allRefs | Where-Object { $_ -like 'refs/remotes/*' })) {
    $parts = $ref.Substring(13) -split '/', 2
    if ($parts.Count -lt 2 -or $parts[1] -eq 'HEAD') { continue }
    if ($headNames -contains $parts[1]) { continue }
    if ($PromoteRemoteBranches -and $parts[0] -eq $PromoteRemoteBranches) {
        Invoke-PortGit @('-C', $mirror, 'update-ref', "refs/heads/$($parts[1])", $ref) | Out-Null
        $manifest.promotedBranches += $parts[1]
        $headNames += $parts[1]
    }
    else {
        $manifest.remoteOnlyBranches += "$($parts[0])/$($parts[1])"
    }
}
foreach ($ref in $allRefs) {
    if ($ref -like 'refs/heads/*' -or $ref -like 'refs/tags/*') { continue }
    Invoke-PortGit @('-C', $mirror, 'update-ref', '-d', $ref) | Out-Null
    $manifest.droppedRefs += $ref
}
# A mirror clone keeps a push-capable remote pointing at the SOURCE. Remove it, so no command
# run in this folder can ever write back to where the app came from.
$remotes = @(Invoke-PortGit @('-C', $mirror, 'remote'))
foreach ($r in $remotes) { if ($r) { Invoke-PortGit @('-C', $mirror, 'remote', 'remove', $r) | Out-Null } }

$heads = @(Invoke-PortGit @('-C', $mirror, 'for-each-ref', '--format=%(refname:short) %(objectname)', 'refs/heads'))
$tags = @(Invoke-PortGit @('-C', $mirror, 'for-each-ref', '--format=%(refname:short) %(objectname)', 'refs/tags'))
$manifest.heads = $heads
$manifest.tags = $tags
if ($heads.Count -eq 0) { throw "The source produced no branches. Nothing to port." }

$symHead = Invoke-PortGit -AllowFailure @('-C', $mirror, 'symbolic-ref', '--short', 'HEAD')
$def = if ($symHead.ExitCode -eq 0) { $symHead.Output -join '' } else { $null }
if (-not $def -or -not ($headNames -contains $def)) {
    $def = @('main', 'master', 'develop') | Where-Object { $headNames -contains $_ } | Select-Object -First 1
    if (-not $def) { $def = $headNames[0] }
    Invoke-PortGit @('-C', $mirror, 'symbolic-ref', 'HEAD', "refs/heads/$def") | Out-Null
}
$manifest.defaultBranch = $def

if ($manifest.remoteOnlyBranches.Count -gt 0) {
    $manifest.warnings += "$($manifest.remoteOnlyBranches.Count) branch(es) exist only as remote-tracking refs in the source and are NOT included: $($manifest.remoteOnlyBranches -join ', '). If this checkout is the only copy, re-run with -PromoteRemoteBranches <remote>. If a server holds them, port from the server URL instead."
}
if ($manifest.excludedSecretFiles.Count -gt 0) {
    $manifest.warnings += "Left out $($manifest.excludedSecretFiles.Count) likely secret file(s): $($manifest.excludedSecretFiles -join ', '). They stay only in the source. Rotate any real credential they hold."
}
if ($manifest.suspectDirs.Count -gt 0) {
    $manifest.warnings += "Imported folders that are often build output or data: $($manifest.suspectDirs -join ', '). Check they belong in the repository."
}
if ($manifest.largeFiles.Count -gt 0) {
    $manifest.warnings += "$($manifest.largeFiles.Count) file(s) over 50 MB. GitHub rejects files over 100 MB."
}

$manifest.status = 'staged'
Save-Manifest

Write-PortOk "Staged $Name at $mirror"
Write-Host ("    kind={0} history={1} branches={2} tags={3} default={4} dropped-refs={5}" -f $kind, $manifest.hadGitHistory, $heads.Count, $tags.Count, $def, $manifest.droppedRefs.Count)
foreach ($w in $manifest.warnings) { Write-PortWarn $w }
Write-Host "    manifest: $(Join-Path $stage 'manifest.json')"
