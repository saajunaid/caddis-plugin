# CADDIS Sync - bidirectional pool sync
# Dot-sourced by PowerShell profile. Provides caddis-pull and caddis-push globally.
#
# One-time setup (run once per machine):
#   Add-Content $PROFILE "`n. 'E:\Projects\claudster-source\sync.ps1'"
#
# If you previously had juno-ai in your profile, update the path:
#   Old:  . 'E:\Projects\juno-ai\sync.ps1'
#   New:  . 'E:\Projects\claudster-source\sync.ps1'
#
# Usage from any project root:
#   caddis-pull                    pull latest pool from caddis-plugin --> current project
#   caddis-push                    push pool from current project --> caddis-plugin + commit + push (mirror sync only; publish is opt-in)
#   caddis-push -Publish           also release MCP (PyPI) + VS Code extension (content-diff gated; PyPI is PERMANENT)
#   caddis-push -NoPublish         DEPRECATED no-op (publish is now off by default; flag kept for back-compat)
#   caddis-smoke-release           run fresh-shell smoke checks for release automation
#   caddis-ship                    commit source, cascade mirrors/profiles, optionally publish selected lanes
#   caddis-release                 publish MCP + VS Code extension using keyfiles
#   caddis-release -SkipMcp        extension only
#   caddis-release -SkipExtension  MCP only
#   caddis-revert [-Last N] [-Sha SHA[,SHA...]]  revert commits + cascade to all repos
#   caddis-export [OutputPath]     export pool to a local folder or zip (no GitHub needed)
#   caddis-import SourcePath        import pool from a local folder or zip into current project

$REPO_ROOT = $PSScriptRoot
$EXT_REPOS_ROOT = Join-Path $REPO_ROOT "vscode-extensions"
$CADDIS_POOL = Join-Path $EXT_REPOS_ROOT "caddis-plugin"
$CADDIS_GITHUB = "$CADDIS_POOL\.github"
$CADDIS_VSCODE = Join-Path $EXT_REPOS_ROOT "junai-vscode"
$PTARMIGAN_REPO = Join-Path $EXT_REPOS_ROOT "ptarmigan"
$LIFFEY_REPO = Join-Path $EXT_REPOS_ROOT "liffey"
$CADDIS_ENV_FILE = Join-Path $REPO_ROOT ".env"
$PYPI_KEY_FILE = Join-Path $CADDIS_POOL "pypimcp.key"
$VSCE_PAT_FILE = Join-Path $CADDIS_VSCODE "vscode.pat"
$PTARMIGAN_PAT_FILE = Join-Path $PTARMIGAN_REPO "ptarmigan.pat"
$script:CaddisEnvLoaded = $false
$script:CaddisEnv = @{}
$LOCAL_ONLY_POOL_FILES = @(
    "prompts\caddis-ship.prompt.md"
)
# NOTE: "plans" intentionally REMOVED from $POOL_FOLDERS as of 2026-04-27 (Phase 1.0
# stop-the-bleed). Plans are tracked in caddis only; they never sync to the
# public mirror. Do not re-add without explicit privacy review.
$POOL_FOLDERS = @("agents", "skills", "prompts", "instructions", "hooks", "diagrams", "tools", "recipes", "agent-docs", "handoffs")
$POOL_FILES = @("runtime-targets.json")
$ROOT_PUSH_FILES = @("export_runtime_resources.py", "validate_agents.py", "validate_pool.py", "sync.ps1", ".env.example")
# PRIVACY IS NOW STRUCTURAL. This repo (caddis) holds ONLY public, publishable source -
# there is no private vmie/ root and no vmie skill category to purge (they live in the separate,
# private caddis repo and never came across in the extraction). These arrays are therefore
# EMPTY: the post-copy purge loops below iterate over nothing. Keeping the machinery (empty) rather
# than ripping it out means a future accidental re-introduction of a private category can be
# re-gated by simply naming it here - but the intent is that nothing private ever lives in this repo.
$PRIVATE_ROOT_FOLDERS = @()
$PRIVATE_SKILL_CATEGORIES = @()
# Fully-managed folders: wiped before copy so renamed/moved/deleted files don't persist
$CLEAN_FOLDERS = @("agents", "skills", "prompts", "instructions", "hooks", "tools", "recipes")

function Remove-ItemRobust {
    # Recursive delete that survives the Windows "directory is not empty" race:
    # the indexer/AV/Defender briefly holds a handle on a file mid-delete, so a
    # single Remove-Item -Recurse can fail even though nothing is wrong. Retry with
    # a short backoff; the handle releases within a few hundred ms. Warns (never
    # throws) if it still can't - callers immediately re-copy in place, so a stale
    # leftover is overwritten rather than fatal.
    param(
        [Parameter(Mandatory)][string]$Path,
        [int]$Retries = 5,
        [int]$DelayMs = 200
    )
    if (-not (Test-Path $Path)) { return }
    for ($i = 1; $i -le $Retries; $i++) {
        try {
            Remove-Item $Path -Recurse -Force -ErrorAction Stop
            return
        } catch {
            if ($i -eq $Retries) {
                Write-Host "  [WARN]  could not fully remove '$Path' after $Retries tries ($($_.Exception.Message)); re-copy will overwrite in place." -ForegroundColor Yellow
                return
            }
            Start-Sleep -Milliseconds ($DelayMs * $i)
        }
    }
}

function Remove-CaddisCacheDirs {
    param(
        [Parameter(Mandatory)][string]$RootPath,
        [string]$Label = ""
    )

    if (-not (Test-Path $RootPath)) { return }

    $cacheNames = @("__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", "htmlcov")
    $cacheDirs = Get-ChildItem $RootPath -Recurse -Directory -Force -ErrorAction SilentlyContinue |
        Where-Object { $cacheNames -contains $_.Name }

    foreach ($dir in $cacheDirs) {
        Remove-Item $dir.FullName -Recurse -Force -ErrorAction SilentlyContinue
    }

    if ($cacheDirs.Count -gt 0) {
        if ([string]::IsNullOrWhiteSpace($Label)) { $Label = $RootPath }
        Write-Host "  [OK]  cache sweep ($Label): removed $($cacheDirs.Count) generated cache folder(s)" -ForegroundColor Green
    }
}

function Initialize-CaddisEnv {
    if ($script:CaddisEnvLoaded) { return }

    $script:CaddisEnv = @{}
    if (Test-Path $CADDIS_ENV_FILE) {
        foreach ($line in Get-Content $CADDIS_ENV_FILE) {
            $trimmed = $line.Trim()
            if ([string]::IsNullOrWhiteSpace($trimmed) -or $trimmed.StartsWith("#")) {
                continue
            }

            $parts = $trimmed.Split("=", 2)
            if ($parts.Count -ne 2) {
                continue
            }

            $name = $parts[0].Trim()
            if ([string]::IsNullOrWhiteSpace($name)) {
                continue
            }

            $value = $parts[1].Trim()
            if ($value.Length -ge 2) {
                if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                    $value = $value.Substring(1, $value.Length - 2)
                }
            }

            $script:CaddisEnv[$name] = $value
        }
    }

    $script:CaddisEnvLoaded = $true
}

function Get-CaddisEnvValue {
    param([Parameter(Mandatory)][string]$Name)

    Initialize-CaddisEnv

    foreach ($scope in @("Process", "User", "Machine")) {
        $value = [Environment]::GetEnvironmentVariable($Name, $scope)
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            return $value.Trim()
        }
    }

    if ($script:CaddisEnv.ContainsKey($Name) -and -not [string]::IsNullOrWhiteSpace($script:CaddisEnv[$Name])) {
        return $script:CaddisEnv[$Name].Trim()
    }

    return ""
}

function Get-CaddisSecretValue {
    param(
        [Parameter(Mandatory)][string]$EnvName,
        [string]$LegacyFilePath = ""
    )

    $value = Get-CaddisEnvValue -Name $EnvName
    if (-not [string]::IsNullOrWhiteSpace($value)) {
        return $value
    }

    if (-not [string]::IsNullOrWhiteSpace($LegacyFilePath) -and (Test-Path $LegacyFilePath)) {
        return (Get-Content $LegacyFilePath -Raw).Trim()
    }

    return ""
}

function Get-CaddisPythonCommand {
    $venvPython = Join-Path $REPO_ROOT ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return @{
            Path = $venvPython
            PrefixArgs = @()
        }
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return @{
            Path = $pythonCommand.Source
            PrefixArgs = @()
        }
    }

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        return @{
            Path = $pyLauncher.Source
            PrefixArgs = @("-3")
        }
    }

    Write-Host "  [ERROR]  No Python interpreter found. Install Python or create $venvPython" -ForegroundColor Red
    return $null
}

function Invoke-CaddisPoolDeploy {
    param(
        [Parameter(Mandatory)][string]$ProjectRoot
    )

    $python = Get-CaddisPythonCommand
    if (-not $python) {
        throw "No Python interpreter available for pool deployment."
    }

    $scriptPath = Join-Path $REPO_ROOT ".github\tools\pool-sync\pool_sync.py"
    if (-not (Test-Path $scriptPath)) {
        throw "Pool deploy script not found: $scriptPath"
    }

    $args = @()
    $args += $python.PrefixArgs
    $args += @($scriptPath, "--pool-root", $REPO_ROOT, "deploy", "--project", $ProjectRoot, "--json")

    $json = & $python.Path @args
    if ($LASTEXITCODE -ne 0) {
        throw "Pool deployment failed: $json"
    }

    $text = ($json | Out-String)
    if ([string]::IsNullOrWhiteSpace($text)) {
        throw "Pool deployment returned no output."
    }

    return ($text | ConvertFrom-Json)
}

function Get-PackageJsonVersion {
    param([Parameter(Mandatory)][string]$PackageJsonPath)

    if (-not (Test-Path $PackageJsonPath)) {
        return ""
    }

    $content = Get-Content $PackageJsonPath -Raw
    $match = [regex]::Match($content, '"version"\s*:\s*"([^"]+)"')
    if (-not $match.Success) {
        return ""
    }

    return $match.Groups[1].Value
}

function Get-NextPatchVersion {
    param([Parameter(Mandatory)][string]$VersionString)

    if ($VersionString -notmatch '^(?<major>\d+)\.(?<minor>\d+)\.(?<patch>\d+)$') {
        throw "Unsupported version format: $VersionString"
    }

    $major = [int]$Matches.major
    $minor = [int]$Matches.minor
    $patch = [int]$Matches.patch + 1
    return "$major.$minor.$patch"
}

function Try-GetNextPatchVersion {
    param([string]$VersionString = "")

    if ([string]::IsNullOrWhiteSpace($VersionString)) {
        return ""
    }

    try {
        return Get-NextPatchVersion -VersionString $VersionString
    } catch {
        return ""
    }
}

function Set-PackageJsonVersion {
    param(
        [Parameter(Mandatory)][string]$PackageJsonPath,
        [Parameter(Mandatory)][string]$VersionString
    )

    $content = Get-Content $PackageJsonPath -Raw
    $updated = [regex]::Replace($content, '"version"\s*:\s*"[^"]+"', ('"version": "' + $VersionString + '"'), 1)
    if ($updated -eq $content) {
        throw "Could not update version in $PackageJsonPath"
    }

    Set-Content $PackageJsonPath $updated -NoNewline
}

function Bump-PackageJsonPatchVersion {
    param(
        [Parameter(Mandatory)][string]$RepoPath,
        [Parameter(Mandatory)][string]$Label
    )

    $packageJsonPath = Join-Path $RepoPath "package.json"
    if (-not (Test-Path $packageJsonPath)) {
        return ""
    }

    $currentVersion = Get-PackageJsonVersion -PackageJsonPath $packageJsonPath
    if ([string]::IsNullOrWhiteSpace($currentVersion)) {
        throw "Could not read version from $packageJsonPath"
    }

    $nextVersion = Get-NextPatchVersion -VersionString $currentVersion
    Set-PackageJsonVersion -PackageJsonPath $packageJsonPath -VersionString $nextVersion
    Write-Host "  [OK]  $Label version bumped $currentVersion --> $nextVersion" -ForegroundColor Green
    return $nextVersion
}

function Get-RuntimeTargetsPluginVersion {
    # Read the version of a NAMED plugin block inside .github/runtime-targets.json (the export
    # source of truth for plugin.json). Scoped by the plugin's "name" so "caddis" never matches
    # "caddis-extras" - the closing quote after the name disambiguates the two.
    param(
        [Parameter(Mandatory)][string]$ManifestPath,
        [Parameter(Mandatory)][string]$PluginName
    )

    if (-not (Test-Path $ManifestPath)) {
        return ""
    }

    $content = Get-Content $ManifestPath -Raw
    $pattern = '"name"\s*:\s*"' + [regex]::Escape($PluginName) + '"\s*,\s*"version"\s*:\s*"([^"]+)"'
    $match = [regex]::Match($content, $pattern)
    if (-not $match.Success) {
        return ""
    }

    return $match.Groups[1].Value
}

function Set-RuntimeTargetsPluginVersion {
    param(
        [Parameter(Mandatory)][string]$ManifestPath,
        [Parameter(Mandatory)][string]$PluginName,
        [Parameter(Mandatory)][string]$VersionString
    )

    $content = Get-Content $ManifestPath -Raw
    $pattern = '("name"\s*:\s*"' + [regex]::Escape($PluginName) + '"\s*,\s*"version"\s*:\s*")[^"]+(")'
    $updated = [regex]::Replace($content, $pattern, ('${1}' + $VersionString + '${2}'), 1)
    if ($updated -eq $content) {
        throw "Could not update version for plugin '$PluginName' in $ManifestPath"
    }

    Set-Content $ManifestPath $updated -NoNewline
}

function Bump-RuntimeTargetsPluginVersion {
    param(
        [Parameter(Mandatory)][string]$ManifestPath,
        [Parameter(Mandatory)][string]$PluginName
    )

    $currentVersion = Get-RuntimeTargetsPluginVersion -ManifestPath $ManifestPath -PluginName $PluginName
    if ([string]::IsNullOrWhiteSpace($currentVersion)) {
        Write-Host "  [WARN]  Could not read version for plugin '$PluginName' in $ManifestPath" -ForegroundColor Yellow
        return ""
    }

    $nextVersion = Get-NextPatchVersion -VersionString $currentVersion
    Set-RuntimeTargetsPluginVersion -ManifestPath $ManifestPath -PluginName $PluginName -VersionString $nextVersion
    Write-Host "  [OK]  $PluginName manifest version bumped $currentVersion --> $nextVersion" -ForegroundColor Green
    return $nextVersion
}

function Get-PyprojectVersion {
    param([Parameter(Mandatory)][string]$PyprojectPath)

    if (-not (Test-Path $PyprojectPath)) {
        return ""
    }

    $content = Get-Content $PyprojectPath -Raw
    $match = [regex]::Match($content, '(?m)^version\s*=\s*"([^"]+)"')
    if (-not $match.Success) {
        return ""
    }

    return $match.Groups[1].Value.Trim()
}

function Set-PyprojectVersion {
    param(
        [Parameter(Mandatory)][string]$PyprojectPath,
        [Parameter(Mandatory)][string]$VersionString
    )

    $content = Get-Content $PyprojectPath -Raw
    $updated = [regex]::Replace($content, '(?m)^version\s*=\s*"[^"]+"', ('version = "' + $VersionString + '"'), 1)
    if ($updated -eq $content) {
        throw "Could not update version in $PyprojectPath"
    }

    Set-Content $PyprojectPath $updated -NoNewline
}

function Bump-PyprojectPatchVersion {
    param(
        [Parameter(Mandatory)][string]$PyprojectPath,
        [string]$Label = "MCP"
    )

    $currentVersion = Get-PyprojectVersion -PyprojectPath $PyprojectPath
    if ([string]::IsNullOrWhiteSpace($currentVersion)) {
        throw "Could not read version from $PyprojectPath"
    }

    $nextVersion = Get-NextPatchVersion -VersionString $currentVersion
    Set-PyprojectVersion -PyprojectPath $PyprojectPath -VersionString $nextVersion
    Write-Host "  [OK]  $Label version bumped $currentVersion --> $nextVersion" -ForegroundColor Green
    return $nextVersion
}

function Commit-PackageJsonPatchVersion {
    param(
        [Parameter(Mandatory)][string]$RepoPath,
        [Parameter(Mandatory)][string]$Label
    )

    Push-Location $RepoPath
    try {
        $nextVersion = Bump-PackageJsonPatchVersion -RepoPath $RepoPath -Label $Label
        if ([string]::IsNullOrWhiteSpace($nextVersion)) {
            return ""
        }

        git add package.json
        git commit -m "chore: bump version to $nextVersion" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "$Label version bump commit failed"
        }

        git push | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "$Label version bump push failed"
        }

        Write-Host "  [OK]  $Label version bump committed + pushed" -ForegroundColor Green
        return $nextVersion
    } finally {
        Pop-Location
    }
}


function Get-LastOutputValue {
    param([Parameter(ValueFromPipeline = $true)]$InputObject)

    begin {
        $items = @()
    }
    process {
        $items += ,$InputObject
    }
    end {
        if ($items.Count -eq 0) {
            return $null
        }
        return $items[-1]
    }
}

function Confirm-VscePublishedVersion {
    param(
        [Parameter(Mandatory)][string]$ExtensionId,
        [Parameter(Mandatory)][string]$ExpectedVersion
    )

    $output = npx @vscode/vsce show $ExtensionId 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($output | Out-String))) {
        Write-Host "  [WARN]  Could not verify marketplace version for $ExtensionId" -ForegroundColor Yellow
        return $false
    }

    $joined = ($output | Out-String)
    $match = [regex]::Match($joined, 'Version:\s*([^\r\n]+)')
    if (-not $match.Success) {
        Write-Host "  [WARN]  Marketplace version for $ExtensionId could not be parsed" -ForegroundColor Yellow
        return $false
    }

    $publishedVersion = $match.Groups[1].Value.Trim()
    if ($publishedVersion -eq $ExpectedVersion) {
        Write-Host "  [OK]  Marketplace version verified: $ExtensionId v$publishedVersion" -ForegroundColor Green
        return $true
    }

    Write-Host "  [WARN]  Marketplace still shows $ExtensionId v$publishedVersion (expected v$ExpectedVersion). This is usually propagation delay." -ForegroundColor Yellow
    return $false
}

function Backup-LocalOnlyPoolFiles {
    param([Parameter(Mandatory)][string]$GithubRoot)

    $backup = @{}
    foreach ($relativePath in $LOCAL_ONLY_POOL_FILES) {
        $fullPath = Join-Path $GithubRoot $relativePath
        if (Test-Path $fullPath) {
            $backup[$relativePath] = [System.IO.File]::ReadAllText($fullPath)
        }
    }

    return $backup
}

function Restore-LocalOnlyPoolFiles {
    param(
        [Parameter(Mandatory)][string]$GithubRoot,
        [hashtable]$Backup = @{}
    )

    foreach ($relativePath in $LOCAL_ONLY_POOL_FILES) {
        if (-not $Backup.ContainsKey($relativePath)) {
            continue
        }

        $fullPath = Join-Path $GithubRoot $relativePath
        $parent = Split-Path $fullPath -Parent
        if (-not (Test-Path $parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        [System.IO.File]::WriteAllText($fullPath, [string]$Backup[$relativePath])
    }
}

function Remove-LocalOnlyPoolFiles {
    param([Parameter(Mandatory)][string]$GithubRoot)

    foreach ($relativePath in $LOCAL_ONLY_POOL_FILES) {
        $fullPath = Join-Path $GithubRoot $relativePath
        if (Test-Path $fullPath) {
            Remove-Item $fullPath -Force
        }
    }
}

function Get-RepoHeadLine {
    param([Parameter(Mandatory)][string]$RepoPath)

    if (-not (Test-Path $RepoPath)) {
        return "$RepoPath (missing)"
    }

    Push-Location $RepoPath
    try {
        $line = git log -1 --oneline 2>$null
        return (($line | Out-String).Trim())
    } finally {
        Pop-Location
    }
}

function Get-RepoChangedPaths {
    param([Parameter(Mandatory)][string]$RepoPath)

    if (-not (Test-Path $RepoPath)) {
        return @()
    }

    Push-Location $RepoPath
    try {
        $tracked = @(git diff --name-only HEAD 2>$null)
        $untracked = @(git ls-files --others --exclude-standard 2>$null)
        $all = @($tracked + $untracked | ForEach-Object { ($_ | Out-String).Trim() } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
        return @($all | Select-Object -Unique)
    } finally {
        Pop-Location
    }
}

function Get-RuntimeTargetManifest {
    $manifestPath = Join-Path $REPO_ROOT ".github\runtime-targets.json"
    if (-not (Test-Path $manifestPath)) {
        return $null
    }

    return (Get-Content $manifestPath -Raw | ConvertFrom-Json)
}

function Test-CopySpecMatchesPath {
    param(
        [Parameter(Mandatory)]$CopySpec,
        [Parameter(Mandatory)][string]$RelativePath
    )

    $normalizedPath = $RelativePath.Replace("\", "/").Trim("/")
    $sourceRoot = ([string]$CopySpec.source).Replace("\", "/").Trim("/")
    if ([string]::IsNullOrWhiteSpace($sourceRoot)) {
        return $false
    }
    if ($normalizedPath -ne $sourceRoot -and -not $normalizedPath.StartsWith("$sourceRoot/")) {
        return $false
    }

    $subPath = $normalizedPath.Substring($sourceRoot.Length).TrimStart('/')
    if ([string]::IsNullOrWhiteSpace($subPath)) {
        return $true
    }

    $parts = @($subPath -split '/')
    $topLevel = $parts[0]

    $excludedNames = @($CopySpec.excluded_names | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) })
    if ($excludedNames.Count -gt 0 -and $excludedNames -contains $topLevel) {
        return $false
    }

    $includedNames = @($CopySpec.included_names | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) })
    if ($includedNames.Count -gt 0 -and -not ($includedNames -contains $topLevel)) {
        return $false
    }

    if ([string]$CopySpec.source -eq "skills" -and $CopySpec.included_skills) {
        if ($parts.Count -lt 2) {
            return $false
        }

        $categoryName = $parts[0]
        $skillName = $parts[1]
        $categoryProperty = $CopySpec.included_skills.PSObject.Properties | Where-Object { $_.Name -eq $categoryName } | Select-Object -First 1
        if (-not $categoryProperty) {
            return $false
        }

        return (@($categoryProperty.Value) -contains $skillName)
    }

    return $true
}

function Test-TargetMatchesSourcePath {
    param(
        [Parameter(Mandatory)]$Target,
        [Parameter(Mandatory)][string]$RepoRelativePath
    )

    $normalized = $RepoRelativePath.Replace("\", "/").Trim("/")

    if ($normalized -eq "export_runtime_resources.py") {
        return $true
    }

    if (-not $normalized.StartsWith(".github/")) {
        return $false
    }

    $poolRelativePath = $normalized.Substring(8)
    if ([string]::IsNullOrWhiteSpace($poolRelativePath)) {
        return $false
    }

    if ($poolRelativePath -eq "runtime-targets.json") {
        return $true
    }

    foreach ($fileSpec in @($Target.files)) {
        $fileSource = ([string]$fileSpec.source).Replace("\", "/").Trim("/")
        if ($poolRelativePath -eq $fileSource) {
            return $true
        }
    }

    foreach ($copySpec in @($Target.copies)) {
        if (Test-CopySpecMatchesPath -CopySpec $copySpec -RelativePath $poolRelativePath) {
            return $true
        }
    }

    return $false
}

function Get-AffectedProfileNamesFromSourcePaths {
    param([string[]]$ChangedPaths = @())

    $manifest = Get-RuntimeTargetManifest
    if (-not $manifest) {
        return @("ptarmigan", "liffey")
    }

    $profileTargets = @($manifest.targets | Where-Object { $_.name -in @("ptarmigan", "liffey") })
    if ($profileTargets.Count -eq 0) {
        return @()
    }

    $affected = New-Object System.Collections.Generic.HashSet[string]
    foreach ($path in @($ChangedPaths | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
        foreach ($target in $profileTargets) {
            if (Test-TargetMatchesSourcePath -Target $target -RepoRelativePath $path) {
                $null = $affected.Add([string]$target.name)
            }
        }
    }

    return @($affected | Sort-Object)
}

function Test-PathPrefixMatch {
    param(
        [Parameter(Mandatory)][string]$RelativePath,
        [string[]]$Prefixes = @()
    )

    $normalizedPath = $RelativePath.Replace("\", "/").Trim("/")
    foreach ($prefix in @($Prefixes | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
        $normalizedPrefix = ([string]$prefix).Replace("\", "/").Trim("/")
        if ([string]::IsNullOrWhiteSpace($normalizedPrefix)) {
            continue
        }

        if ($normalizedPath -eq $normalizedPrefix -or $normalizedPath.StartsWith("$normalizedPrefix/")) {
            return $true
        }
    }

    return $false
}

function Get-ReleaseRelevantRepoChangedPaths {
    param(
        [Parameter(Mandatory)][string]$Lane,
        [string[]]$ChangedPaths = @()
    )

    $relevant = New-Object System.Collections.Generic.List[string]
    foreach ($path in @($ChangedPaths | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
        $normalizedPath = $path.Replace("\", "/").Trim("/")
        $isRelevant = $false

        switch ($Lane) {
            "junai-vscode" {
                $isRelevant = (
                    (Test-PathPrefixMatch -RelativePath $normalizedPath -Prefixes @("src", "media", "out", "scripts")) -or
                    $normalizedPath -in @("package.json", "esbuild.mjs", "tsconfig.json", "README.md", "CHANGELOG.md", "LICENSE.md")
                )
            }
            "ptarmigan" {
                $isRelevant = (
                    (Test-PathPrefixMatch -RelativePath $normalizedPath -Prefixes @("src", "media", "assets", "pool", "out", "scripts")) -or
                    $normalizedPath -in @("package.json", "esbuild.mjs", "tsconfig.json", "README.md", "CHANGELOG.md", "PUBLISHING.md", "LICENSE.md")
                )
            }
            "liffey" {
                $isRelevant = (
                    (Test-PathPrefixMatch -RelativePath $normalizedPath -Prefixes @("src", "media", "pool", "out", "scripts")) -or
                    $normalizedPath -in @("package.json", "esbuild.mjs", "tsconfig.json", "README.md", "CHANGELOG.md", "LICENSE.md")
                )
            }
            "mcp" {
                $isRelevant = (
                    (Test-PathPrefixMatch -RelativePath $normalizedPath -Prefixes @("src/junai_mcp")) -or
                    $normalizedPath -in @("pyproject.toml", "README.md")
                )
            }
        }

        if ($isRelevant) {
            $null = $relevant.Add($normalizedPath)
        }
    }

    return @($relevant | Select-Object -Unique)
}

function Get-AffectedReleaseTargetsFromSourcePaths {
    param([string[]]$ChangedPaths = @())

    $affected = New-Object System.Collections.Generic.HashSet[string]

    foreach ($profile in @(Get-AffectedProfileNamesFromSourcePaths -ChangedPaths $ChangedPaths)) {
        $null = $affected.Add($profile)
    }

    foreach ($path in @($ChangedPaths | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
        $normalizedPath = $path.Replace("\", "/").Trim("/")

        if ($normalizedPath -eq "export_runtime_resources.py" -or $normalizedPath -eq ".github/runtime-targets.json" -or $normalizedPath.StartsWith(".github/")) {
            $null = $affected.Add("junai-vscode")
        }
    }

    return @($affected | Sort-Object)
}

function Commit-RepoIfDirty {
    param(
        [Parameter(Mandatory)][string]$RepoPath,
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)][string]$Message,
        [switch]$Push
    )

    if (-not (Test-Path $RepoPath)) {
        Write-Host "  [WARN]  $Label repo not found at $RepoPath" -ForegroundColor Yellow
        return $false
    }

    Push-Location $RepoPath
    try {
        $statusOutput = @(git status --porcelain)
        $hasChanges = -not [string]::IsNullOrWhiteSpace(($statusOutput | Out-String).Trim())
        if (-not $hasChanges) {
            Write-Host "  [--]  $Label repo already clean" -ForegroundColor DarkGray
            return $false
        }

        git add -A | Out-Null
        git commit -m $Message | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "$Label commit failed"
        }

        if ($Push) {
            git push | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "$Label push failed"
            }
            Write-Host "  [OK]  $Label committed + pushed" -ForegroundColor Green
        } else {
            Write-Host "  [OK]  $Label committed locally" -ForegroundColor Green
        }

        return $true
    } finally {
        Pop-Location
    }
}

function Test-ManagedExtensionStaging {
    param(
        [Parameter(Mandatory)][string]$RepoPath,
        [Parameter(Mandatory)][string]$Label
    )

    $result = @{
        Label = $Label
        Passed = $true
        Unexpected = @()
    }

    if (-not (Test-Path $RepoPath)) {
        $result.Passed = $false
        $result.Unexpected = @("missing repo: $RepoPath")
        return $result
    }

    $sentinelEnv = Join-Path $RepoPath ".env"
    $sentinelDistDir = Join-Path $RepoPath "dist"
    $sentinelVsix = Join-Path $sentinelDistDir "caddis-smoke-sentinel.vsix"
    $createdEnv = $false
    $createdDistDir = $false
    $createdVsix = $false

    try {
        if (-not (Test-Path $sentinelEnv)) {
            [System.IO.File]::WriteAllText($sentinelEnv, "JUNAI_SMOKE_TEST=1`n")
            $createdEnv = $true
        }
        if (-not (Test-Path $sentinelDistDir)) {
            New-Item -ItemType Directory -Path $sentinelDistDir -Force | Out-Null
            $createdDistDir = $true
        }
        if (-not (Test-Path $sentinelVsix)) {
            [System.IO.File]::WriteAllText($sentinelVsix, "smoke-test")
            $createdVsix = $true
        }

        Push-Location $RepoPath
        try {
            $dryRunOutput = @(git add -n -- package.json pool out 2>&1)
        } finally {
            Pop-Location
        }

        $unexpected = @($dryRunOutput | Where-Object {
            $_ -match 'caddis-smoke-sentinel\.vsix' -or $_ -match '(^|[\\/])\.env($|\s)'
        })

        if ($unexpected.Count -gt 0) {
            $result.Passed = $false
            $result.Unexpected = @($unexpected | ForEach-Object { ($_ | Out-String).Trim() })
        }
    } finally {
        if ($createdVsix -and (Test-Path $sentinelVsix)) {
            Remove-Item $sentinelVsix -Force
        }
        if ($createdDistDir -and (Test-Path $sentinelDistDir)) {
            $remaining = Get-ChildItem $sentinelDistDir -Force -ErrorAction SilentlyContinue
            if (-not $remaining) {
                Remove-Item $sentinelDistDir -Force
            }
        }
        if ($createdEnv -and (Test-Path $sentinelEnv)) {
            Remove-Item $sentinelEnv -Force
        }
    }

    return $result
}

function Invoke-CaddisFreshShell {
    param(
        [Parameter(Mandatory)][string]$ScriptText,
        [string]$WorkingDirectory = $REPO_ROOT
    )

    $tempScript = Join-Path ([System.IO.Path]::GetTempPath()) ("caddis-smoke-" + [guid]::NewGuid().ToString() + ".ps1")
    $scriptContent = @"
Set-Location '$WorkingDirectory'
. '$REPO_ROOT\sync.ps1'

$ErrorActionPreference = 'Stop'
$ScriptText
"@

    [System.IO.File]::WriteAllText($tempScript, $scriptContent)
    try {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $tempScript
        return $LASTEXITCODE
    } finally {
        if (Test-Path $tempScript) {
            Remove-Item $tempScript -Force
        }
    }
}

function Publish-PtarmiganExtension {
    if (-not (Test-Path $PTARMIGAN_REPO)) {
        Write-Host "  [ERROR] Ptarmigan repo not found at $PTARMIGAN_REPO" -ForegroundColor Red
        return $false
    }

    $pat = Get-CaddisSecretValue -EnvName "PTARMIGAN_VSCE_PAT" -LegacyFilePath $PTARMIGAN_PAT_FILE
    if ([string]::IsNullOrWhiteSpace($pat)) {
        Write-Host "  [ERROR] Missing Ptarmigan PAT. Set PTARMIGAN_VSCE_PAT in $CADDIS_ENV_FILE or keep $PTARMIGAN_PAT_FILE." -ForegroundColor Red
        return $false
    }

    Push-Location $PTARMIGAN_REPO
    $prevVscePat = $env:VSCE_PAT
    try {
        $env:VSCE_PAT = $pat
        npx vsce publish --pat $pat --no-dependencies
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [WARN]  Ptarmigan publish failed." -ForegroundColor Yellow
            return $false
        }

        Write-Host "  [OK]  Ptarmigan extension published." -ForegroundColor Green
        $expectedVersion = Get-PackageJsonVersion -PackageJsonPath (Join-Path $PTARMIGAN_REPO "package.json")
        if (-not [string]::IsNullOrWhiteSpace($expectedVersion)) {
            Confirm-VscePublishedVersion -ExtensionId "junai-labs.ptarmigan" -ExpectedVersion $expectedVersion | Out-Null
        }
        return $true
    } finally {
        $env:VSCE_PAT = $prevVscePat
        Pop-Location
    }
}

function Package-LiffeyExtension {
    Push-Location $LIFFEY_REPO
    try {
        $pkg = Get-Content (Join-Path $LIFFEY_REPO "package.json") -Raw | ConvertFrom-Json
        $version = if ($pkg.version) { $pkg.version } else { "0.0.0" }

        $distDir = Join-Path $LIFFEY_REPO "dist"
        New-Item -ItemType Directory -Path $distDir -Force | Out-Null

        $vsixOut = Join-Path $distDir "liffey-$version.vsix"
        npx vsce package --out $vsixOut --no-dependencies
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [WARN]  Liffey VSIX packaging failed." -ForegroundColor Yellow
            return $null
        }

        Write-Host "  [OK]  Liffey VSIX prepared: $vsixOut" -ForegroundColor Green
        return $vsixOut
    } finally {
        Pop-Location
    }
}

function caddis-pull {
    param([string]$ProjectRoot = (Get-Location).Path)

    $target = Join-Path $ProjectRoot ".github"
    $localOnlyBackup = Backup-LocalOnlyPoolFiles -GithubRoot $target

    if (-not (Test-Path $target)) {
        Write-Host "No .github/ folder found at $ProjectRoot" -ForegroundColor Red
        Write-Host "Are you in a project root?" -ForegroundColor Yellow
        return
    }

    Write-Host ""
    Write-Host "  CADDIS PULL  caddis-plugin --> $(Split-Path $ProjectRoot -Leaf)" -ForegroundColor Cyan
    Write-Host "  -----------------------------------------" -ForegroundColor DarkGray

    # Pre-sync hygiene: drop generated caches in canonical pool + target project .github
    Remove-CaddisCacheDirs -RootPath (Join-Path $REPO_ROOT ".github") -Label "pool"
    Remove-CaddisCacheDirs -RootPath $target -Label "project"
    $deployResult = Invoke-CaddisPoolDeploy -ProjectRoot $ProjectRoot
    foreach ($folder in @($deployResult.copied_directories)) {
        Write-Host "  [OK]  $folder" -ForegroundColor Green
    }
    foreach ($file in @($deployResult.copied_files)) {
        Write-Host "  [OK]  $file" -ForegroundColor Green
    }
    foreach ($regionFile in @($deployResult.managed_regions)) {
        Write-Host "  [OK]  $regionFile (managed region)" -ForegroundColor Green
    }
    if ($deployResult.registry_written) {
        Write-Host "  [OK]  skills/_registry.md (profile-filtered)" -ForegroundColor Green
    }
    Write-Host "  [OK]  .pool-version" -ForegroundColor Green

    # Deploy .vscode/mcp.json (pre-configured with ${workspaceFolder} - profile-agnostic)
    $mcpSrc = Join-Path $CADDIS_POOL ".vscode\mcp.json"
    if (Test-Path $mcpSrc) {
        $vscodeTarget = Join-Path $ProjectRoot ".vscode"
        if (-not (Test-Path $vscodeTarget)) { New-Item -ItemType Directory -Path $vscodeTarget | Out-Null }
        Copy-Item $mcpSrc $vscodeTarget -Force
        Write-Host "  [OK]  .vscode/mcp.json" -ForegroundColor Green
    }

    Restore-LocalOnlyPoolFiles -GithubRoot $target -Backup $localOnlyBackup

    Write-Host ""
    Write-Host "  Done. Owned project paths were preserved; .pool-version was updated." -ForegroundColor DarkGray
    Write-Host ""
}

function caddis-push {
    param(
        [string]$ProjectRoot = (Get-Location).Path,
        [string]$Message = "",
        [switch]$Publish,
        [switch]$NoPublish,
        [string]$McpVersion = "",
        [string[]]$Profiles = @("ptarmigan", "liffey"),
        [switch]$SkipProfileSync
    )

    $pushResult = [ordered]@{
        MirrorChanged = $false
        SelectedProfiles = @()
        ProfileResults = @{}
        ReleaseTriggered = $false
    }

    $source = Join-Path $ProjectRoot ".github"

    if (-not (Test-Path $source)) {
        Write-Host "No .github/ folder found at $ProjectRoot" -ForegroundColor Red
        Write-Host "Are you in a project root?" -ForegroundColor Yellow
        return
    }

    # Nested-mirror guard (Phase 0 hygiene, 2026-07): the pool/mirror must NEVER contain a
    # self-nested checkout of itself under vscode-extensions/. A stray copy there means a
    # prior sync mirrored the pool into itself; a find/replace or publish over that tree would
    # touch two inconsistent copies and can leak the whole mirror twice. Fail hard so it is
    # fixed (git rm -r the nested dir in the mirror), never silently shipped.
    # Both the current folder name and the pre-rename one are checked: a mirror committed
    # before the caddis rename can still carry a stale vscode-extensions/junai copy.
    foreach ($nestedName in @("caddis-plugin", "junai")) {
        $nestedMirror = Join-Path $CADDIS_POOL "vscode-extensions\$nestedName"
        if (Test-Path $nestedMirror) {
            Write-Host "  [FAIL]  nested self-copy of the mirror detected at:" -ForegroundColor Red
            Write-Host "          $nestedMirror" -ForegroundColor Red
            throw "caddis-plugin mirror hygiene: a nested vscode-extensions/$nestedName checkout is present inside the pool. Remove it (in the mirror: git rm -r vscode-extensions/$nestedName && commit) before pushing. The mirror must not contain a checkout of itself."
        }
    }

    Write-Host ""
    Write-Host "  CADDIS PUSH  $(Split-Path $ProjectRoot -Leaf) --> caddis-plugin" -ForegroundColor Magenta
    Write-Host "  -----------------------------------------" -ForegroundColor DarkGray

    # Pre-sync hygiene: remove generated caches on both sides so they never leak
    # into the public mirror or get reintroduced by additive copies.
    Remove-CaddisCacheDirs -RootPath $source -Label "source"
    Remove-CaddisCacheDirs -RootPath $CADDIS_GITHUB -Label "mirror"

    foreach ($folder in $POOL_FOLDERS) {
        $src = Join-Path $source $folder
        $dest = Join-Path $CADDIS_GITHUB $folder
        if (Test-Path $src) {
            # Clean destination first to prevent nested folder copies (e.g. diagrams/diagrams)
            # and to ensure moved/deleted files are mirrored correctly.
            if (Test-Path $dest) {
                Remove-ItemRobust $dest
            }
            Copy-Item $src $CADDIS_GITHUB -Recurse -Force
            Write-Host "  [OK]  $folder" -ForegroundColor Green
        } else {
            # Source no longer has this folder: remove stale mirror copy.
            if (Test-Path $dest) {
                Remove-ItemRobust $dest
                Write-Host "  [OK]  $folder - removed stale mirror folder" -ForegroundColor Green
            } else {
                Write-Host "  [--]  $folder - not in project, skipped" -ForegroundColor DarkGray
            }
        }
    }

    # Privacy gate: the public mirror must NEVER carry private skill categories or private root
    # folders. The POOL_FOLDERS copy above mirrors skills/ wholesale, so strip private categories
    # (vmie = vm-ppt + golden-workflow, proprietary) here, plus any private root folder that slipped
    # in. This makes $PRIVATE_ROOT_FOLDERS actually enforced (it was declared but never applied).
    foreach ($cat in $PRIVATE_SKILL_CATEGORIES) {
        $privCat = Join-Path $CADDIS_GITHUB "skills\$cat"
        if (Test-Path $privCat) {
            Remove-ItemRobust $privCat
            Write-Host "  [OK]  privacy: purged skills/$cat from public mirror" -ForegroundColor Green
        }
    }
    foreach ($rootFolder in $PRIVATE_ROOT_FOLDERS) {
        $privRoot = Join-Path $CADDIS_GITHUB $rootFolder
        if (Test-Path $privRoot) {
            Remove-ItemRobust $privRoot
            Write-Host "  [OK]  privacy: purged $rootFolder/ from public mirror" -ForegroundColor Green
        }
    }

    foreach ($file in $POOL_FILES) {
        $src = Join-Path $source $file
        $dest = Join-Path $CADDIS_GITHUB $file
        if (Test-Path $src) {
            Copy-Item $src $dest -Force
            Write-Host "  [OK]  $file" -ForegroundColor Green
        } else {
            Write-Host "  [--]  $file - not in project, skipped" -ForegroundColor DarkGray
        }
    }

    foreach ($file in $ROOT_PUSH_FILES) {
        $src = Join-Path $ProjectRoot $file
        $dest = Join-Path $CADDIS_POOL $file
        if (Test-Path $src) {
            Copy-Item $src $dest -Force
            Write-Host "  [OK]  $file" -ForegroundColor Green
        } else {
            Write-Host "  [--]  $file - not in project root, skipped" -ForegroundColor DarkGray
        }
    }

    # -- Claude Code plugin bundle (Phase 4) -----------------------------------
    # Export the `claude` target and place it in the caddis-plugin repo so it ships in the
    # same commit: marketplace.json at the repo root (.claude-plugin/), the plugin
    # under plugin/. Repo is PUBLIC - vmie/ and any private skill categories are
    # purged from the plugin bundle after copy.
    # Private skills purged from BOTH public plugin bundles. After skill flattening these
    # are flat dirs (skills/<name>/), not a skills/vmie/ category - so purge by skill name.
    # Empty: golden-workflow + windows-deployment were promoted to public categories
    # (devops/, docs/) and now ship in the public bundles. Add a name here only to hold a
    # skill back from publish while keeping it in the pool.
    $PLUGIN_PRIVATE_SKILLS = @()
    $claudePython = Get-CaddisPythonCommand
    if ($claudePython) {
        Push-Location $ProjectRoot
        & $claudePython.Path @($claudePython.PrefixArgs + @("export_runtime_resources.py", "--profile", "claude", "--profile", "claude-extras"))
        $claudeExportOk = ($LASTEXITCODE -eq 0)
        Pop-Location
        $claudeBundle = Join-Path $ProjectRoot "dist\runtime-resources\claude"
        $extrasBundle = Join-Path $ProjectRoot "dist\runtime-resources\claude-extras"
        $haveCore   = $claudeExportOk -and (Test-Path (Join-Path $claudeBundle "plugin"))
        $haveExtras = $claudeExportOk -and (Test-Path (Join-Path $extrasBundle "plugin-extras"))
        if ($haveCore -and $haveExtras) {
            # marketplace.json (lists both plugins) ships from the core bundle root
            $destMarket = Join-Path $CADDIS_POOL ".claude-plugin"
            if (Test-Path $destMarket) { Remove-ItemRobust $destMarket }
            Copy-Item (Join-Path $claudeBundle ".claude-plugin") $CADDIS_POOL -Recurse -Force

            # core plugin -> caddis-plugin/plugin ; extras plugin -> caddis-plugin/plugin-extras
            $destPlugin = Join-Path $CADDIS_POOL "plugin"
            if (Test-Path $destPlugin) { Remove-ItemRobust $destPlugin }
            Copy-Item (Join-Path $claudeBundle "plugin") $CADDIS_POOL -Recurse -Force
            $destExtras = Join-Path $CADDIS_POOL "plugin-extras"
            if (Test-Path $destExtras) { Remove-ItemRobust $destExtras }
            Copy-Item (Join-Path $extrasBundle "plugin-extras") $CADDIS_POOL -Recurse -Force

            # Purge private skills from both public bundles
            foreach ($dest in @($destPlugin, $destExtras)) {
                foreach ($privateSkill in $PLUGIN_PRIVATE_SKILLS) {
                    $privatePath = Join-Path $dest "skills\$privateSkill"
                    if (Test-Path $privatePath) {
                        Remove-Item $privatePath -Recurse -Force
                        Write-Host "  [OK]  purged private skills/$privateSkill from $(Split-Path $dest -Leaf)" -ForegroundColor Green
                    }
                }
            }
            Write-Host "  [OK]  caddis plugins (.claude-plugin + plugin/ + plugin-extras/)" -ForegroundColor Green
        } else {
            Write-Host "  [WARN]  claude plugin export failed; bundle not synced this run." -ForegroundColor Yellow
        }
    } else {
        Write-Host "  [--]  claude plugin - python not found, skipped" -ForegroundColor DarkGray
    }

    # -- Portable bundles (Phase 4 caddis) --------------------------------------
    # Ship the non-Claude bundles at bundles/<target>/ so `caddis-init --target <t>` (GitHub
    # tarball mode, no --from) resolves them (claudster_init.py BUNDLE_ROOTS = bundles, then
    # dist/runtime-resources; dist/ is gitignored in the mirror so bundles/ is the published home),
    # and so `agy plugin install <caddis-plugin-checkout>/bundles/antigravity-plugin` works from a checkout.
    $BUNDLE_TARGETS = @("codex", "codex-extras", "antigravity", "antigravity-extras",
                        "antigravity-plugin", "antigravity-plugin-extras")
    if ($claudePython) {
        Push-Location $ProjectRoot
        $bundleExportArgs = @("export_runtime_resources.py")
        foreach ($t in $BUNDLE_TARGETS) { $bundleExportArgs += @("--profile", $t) }
        & $claudePython.Path @($claudePython.PrefixArgs + $bundleExportArgs)
        $bundleExportOk = ($LASTEXITCODE -eq 0)
        Pop-Location
        if ($bundleExportOk) {
            $bundlesRoot = Join-Path $CADDIS_POOL "bundles"
            New-Item -ItemType Directory -Force $bundlesRoot | Out-Null
            foreach ($t in $BUNDLE_TARGETS) {
                $srcBundle = Join-Path $ProjectRoot "dist\runtime-resources\$t"
                $dstBundle = Join-Path $bundlesRoot $t
                if (Test-Path $srcBundle) {
                    if (Test-Path $dstBundle) { Remove-ItemRobust $dstBundle }
                    Copy-Item $srcBundle $bundlesRoot -Recurse -Force
                    Write-Host "  [OK]  bundle: bundles/$t" -ForegroundColor Green
                } else {
                    Write-Host "  [WARN]  bundle $t not exported; skipped." -ForegroundColor Yellow
                }
            }
        } else {
            Write-Host "  [WARN]  portable-bundle export failed; bundles/ not refreshed this run." -ForegroundColor Yellow
        }
    }

    Remove-LocalOnlyPoolFiles -GithubRoot $CADDIS_GITHUB

    # Commit and push caddis-plugin
    Push-Location $CADDIS_POOL

    $hasChanges = (git status --porcelain) -ne $null
    if (-not $hasChanges) {
        Write-Host ""
        Write-Host "  No changes detected in caddis-plugin. Nothing to commit." -ForegroundColor DarkGray
        Pop-Location
        return [pscustomobject]$pushResult
    }

    # (PyPI build copy of the pool mcp-server retired 2026-07-20 -- the pool
    #  mcp-server tool was removed alongside the Copilot-era pipeline runner.
    #  The published junai-mcp PyPI package is a separate artifact, untouched here.)

    # -- Auto-bump the caddis plugin version when its bundle content changed --
    # plugin.json is GENERATED from .github/runtime-targets.json by the export, so shipping
    # plugin content without bumping that manifest pins clients to a stale cached version (the
    # .claudster migration hit exactly this). When the mirror's plugin/ content changed beyond
    # plugin.json itself (so a manual version edit is not double-bumped), bump the manifest,
    # re-sync it, and re-export so the new version rides in THIS mirror commit. The source
    # manifest is committed separately after the push (it is the export's source of truth).
    $bumpedCaddis = ""
    if ($claudePython) {
        $pluginContentDiff = git status --porcelain -- plugin ":(exclude)plugin/.claude-plugin/plugin.json"
        if (-not [string]::IsNullOrWhiteSpace(($pluginContentDiff | Out-String).Trim())) {
            $manifestSrc = Join-Path $ProjectRoot ".github/runtime-targets.json"
            $bumpedCaddis = Bump-RuntimeTargetsPluginVersion -ManifestPath $manifestSrc -PluginName "caddis"
            if (-not [string]::IsNullOrWhiteSpace($bumpedCaddis)) {
                Copy-Item $manifestSrc (Join-Path $CADDIS_GITHUB "runtime-targets.json") -Force
                Push-Location $ProjectRoot
                & $claudePython.Path @($claudePython.PrefixArgs + @("export_runtime_resources.py", "--profile", "claude"))
                $reExportOk = ($LASTEXITCODE -eq 0)
                Pop-Location
                $rebuiltPlugin = Join-Path $claudeBundle "plugin\.claude-plugin\plugin.json"
                if ($reExportOk -and (Test-Path $rebuiltPlugin)) {
                    Copy-Item $rebuiltPlugin (Join-Path $CADDIS_POOL "plugin\.claude-plugin\plugin.json") -Force
                    Write-Host "  [OK]  caddis bundle changed -> bumped manifest + plugin.json to $bumpedCaddis" -ForegroundColor Green
                } else {
                    Write-Host "  [WARN]  claude re-export failed; plugin.json may lag the $bumpedCaddis bump." -ForegroundColor Yellow
                }
            }
        }
    }

    # -- Same auto-bump for caddis-extras when ITS bundle content changed --
    # The extras plugin (plugin-extras/) versions independently. Without this, a content change
    # to extras (e.g. a skill removed during re-privatization) ships without a version bump, so
    # clients keep the stale cached copy and `/plugin update` reports "already up to date".
    # Mirrors the core block above, scoped to plugin-extras/ and the claude-extras profile.
    $bumpedExtras = ""
    if ($claudePython) {
        $extrasContentDiff = git status --porcelain -- plugin-extras ":(exclude)plugin-extras/.claude-plugin/plugin.json"
        if (-not [string]::IsNullOrWhiteSpace(($extrasContentDiff | Out-String).Trim())) {
            $manifestSrc = Join-Path $ProjectRoot ".github/runtime-targets.json"
            $bumpedExtras = Bump-RuntimeTargetsPluginVersion -ManifestPath $manifestSrc -PluginName "caddis-extras"
            if (-not [string]::IsNullOrWhiteSpace($bumpedExtras)) {
                Copy-Item $manifestSrc (Join-Path $CADDIS_GITHUB "runtime-targets.json") -Force
                Push-Location $ProjectRoot
                & $claudePython.Path @($claudePython.PrefixArgs + @("export_runtime_resources.py", "--profile", "claude-extras"))
                $reExportExtrasOk = ($LASTEXITCODE -eq 0)
                Pop-Location
                $rebuiltExtras = Join-Path $extrasBundle "plugin-extras\.claude-plugin\plugin.json"
                if ($reExportExtrasOk -and (Test-Path $rebuiltExtras)) {
                    Copy-Item $rebuiltExtras (Join-Path $CADDIS_POOL "plugin-extras\.claude-plugin\plugin.json") -Force
                    Write-Host "  [OK]  caddis-extras bundle changed -> bumped manifest + plugin.json to $bumpedExtras" -ForegroundColor Green
                } else {
                    Write-Host "  [WARN]  claude-extras re-export failed; plugin.json may lag the $bumpedExtras bump." -ForegroundColor Yellow
                }
            }
        }
    }

    # Stage all tracked/untracked/deleted files in caddis-plugin so source deletions and
    # folder moves are guaranteed to propagate.
    git add -A | Out-Null

    if ([string]::IsNullOrWhiteSpace($Message)) {
        $projectName = Split-Path $ProjectRoot -Leaf
        $today = Get-Date -Format "yyyy-MM-dd"
        $Message = "feat: sync pool from $projectName - $today"
    }

    git commit -m $Message | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Pop-Location
        throw "caddis-plugin mirror: git commit failed (exit $LASTEXITCODE) - mirror NOT updated."
    }
    git push | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Pop-Location
        throw "caddis-plugin mirror: git push failed (exit $LASTEXITCODE) - the commit is local only and was NOT pushed. Fix the remote/auth and re-run."
    }

    $pushResult.MirrorChanged = $true

    Pop-Location

    Write-Host ""
    Write-Host "  Committed and pushed to caddis-plugin." -ForegroundColor Magenta
    Write-Host ""

    # Persist the auto-bump in the SOURCE repo - runtime-targets.json is the export's source of
    # truth, so it must be committed here or the next export would regenerate plugin.json at the
    # old version and silently revert the bump. Path-scoped commit so unrelated source edits are
    # not swept in.
    if ((-not [string]::IsNullOrWhiteSpace($bumpedCaddis)) -or (-not [string]::IsNullOrWhiteSpace($bumpedExtras))) {
        $bumpParts = @()
        if (-not [string]::IsNullOrWhiteSpace($bumpedCaddis)) { $bumpParts += "caddis v$bumpedCaddis" }
        if (-not [string]::IsNullOrWhiteSpace($bumpedExtras))    { $bumpParts += "extras v$bumpedExtras" }
        $bumpSummary = $bumpParts -join " + "
        Push-Location $ProjectRoot
        git commit ".github/runtime-targets.json" -m "chore(caddis): bump manifest version ($bumpSummary)" | Out-Null
        $bumpExit = $LASTEXITCODE
        Pop-Location
        if ($bumpExit -ne 0) {
            Write-Warning "  Source manifest bump commit failed (exit $bumpExit) - the version bump may silently revert on the next export. Commit .github/runtime-targets.json by hand."
        } else {
            Write-Host "  Source manifest committed: $bumpSummary." -ForegroundColor Magenta
            Write-Host ""
        }
    }

    $selectedProfiles = @($Profiles | Where-Object { $_ -in @("ptarmigan", "liffey") } | Select-Object -Unique)
    $pushResult.SelectedProfiles = $selectedProfiles
    if ($SkipProfileSync -or $selectedProfiles.Count -eq 0) {
        Write-Host "  [--]  Profile sync skipped." -ForegroundColor DarkGray
    } else {
        # Build only the selected profile exports used by downstream sync lanes.
        Push-Location $ProjectRoot
        $pythonCommand = Get-CaddisPythonCommand
        if ($pythonCommand) {
            $exportArgs = @("export_runtime_resources.py")
            foreach ($profile in $selectedProfiles) {
                $exportArgs += @("--profile", $profile)
            }
            $exportArgs += "--report"
            & $pythonCommand.Path @($pythonCommand.PrefixArgs + $exportArgs)
            $profileExportOk = ($LASTEXITCODE -eq 0)
        } else {
            $profileExportOk = $false
        }
        if ($profileExportOk -and (Test-Path (Join-Path $ProjectRoot "validate_pool.py"))) {
            & $pythonCommand.Path @($pythonCommand.PrefixArgs + @("validate_pool.py", "--include-dist"))
            $profileExportOk = ($LASTEXITCODE -eq 0)
        }
        Pop-Location

        if (-not $profileExportOk) {
            Write-Host "  [WARN]  Profile export failed; skipping selected profile cascade for this run." -ForegroundColor Yellow
        } else {
            if ($selectedProfiles -contains "ptarmigan") {
                $pushResult.ProfileResults["ptarmigan"] = [bool](sync-ptarmigan -ProjectRoot $ProjectRoot -Message $Message)
            }
            if ($selectedProfiles -contains "liffey") {
                $pushResult.ProfileResults["liffey"] = [bool](sync-liffey -ProjectRoot $ProjectRoot -Message $Message)
            }
        }
    }

    # -- Publish gating (INVERTED default: release is opt-in via -Publish) ------
    # SAFETY (Track 0, 2026-07): historically caddis-push auto-published whenever a
    # PyPI/VS Code key was merely present in .env - one keystroke from a PERMANENT,
    # un-undoable PyPI upload, even for a plugin-only session. The default is now
    # inverted: a release fires ONLY when -Publish is explicitly passed. -NoPublish is
    # retained as a DEPRECATED silent no-op (its behaviour is now the default). The
    # mirror sync above still runs unconditionally; only the MCP/VS Code release is gated.
    $pypiToken = Get-CaddisSecretValue -EnvName "JUNAI_PYPI_TOKEN" -LegacyFilePath $PYPI_KEY_FILE
    $vscePat = Get-CaddisSecretValue -EnvName "JUNAI_VSCE_PAT" -LegacyFilePath $VSCE_PAT_FILE
    $hasPypiKey = -not [string]::IsNullOrWhiteSpace($pypiToken)
    $hasVscePat = -not [string]::IsNullOrWhiteSpace($vscePat)
    $shouldPublish = [bool]$Publish

    if ($NoPublish) {
        Write-Host "  [--]  -NoPublish is deprecated: publish is now opt-in and skipped by default." -ForegroundColor DarkGray
    }

    if (-not $shouldPublish) {
        Write-Host "  [--]  Mirror synced; release NOT triggered (publish is opt-in)." -ForegroundColor DarkGray
        Write-Host "       Re-run 'caddis-push -Publish' to release the MCP (PyPI) / VS Code extension." -ForegroundColor DarkGray
        return [pscustomobject]$pushResult
    }

    if (-not ($hasPypiKey -or $hasVscePat)) {
        Write-Host "  [--]  -Publish set but no keys found; nothing to release." -ForegroundColor DarkGray
        Write-Host "       Set JUNAI_PYPI_TOKEN and/or JUNAI_VSCE_PAT in $CADDIS_ENV_FILE (legacy key files still work)." -ForegroundColor DarkGray
        return [pscustomobject]$pushResult
    }

    if (-not $hasPypiKey) {
        Write-Host "  [--]  PyPI key missing; MCP publish skipped." -ForegroundColor DarkGray
    }
    if (-not $hasVscePat) {
        Write-Host "  [--]  VS Code PAT missing; extension publish skipped." -ForegroundColor DarkGray
    }

    $pushResult.ReleaseTriggered = $true
    caddis-release -McpVersion $McpVersion -SkipMcp:(-not $hasPypiKey) -SkipExtension:(-not $hasVscePat)
    return [pscustomobject]$pushResult
}

function Sync-CaddisProfileRepo {
    param(
        [Parameter(Mandatory)][string]$Profile,
        [Parameter(Mandatory)][string]$ProjectRoot,
        [Parameter(Mandatory)][string]$RepoPath,
        [string]$Message = "",
        [switch]$NoPush
    )

    $exportRoot = Join-Path $ProjectRoot "dist\runtime-resources\$Profile"
    $sourceGithub = Join-Path $exportRoot ".github"
    $targetGithub = Join-Path $RepoPath ".github"

    if (-not (Test-Path $sourceGithub)) {
        Write-Host "  [WARN]  $Profile export not found at $sourceGithub" -ForegroundColor Yellow
        return $false
    }
    if (-not (Test-Path $RepoPath)) {
        Write-Host "  [WARN]  $Profile repo not found at $RepoPath" -ForegroundColor Yellow
        return $false
    }

    Remove-ItemRobust $targetGithub
    Copy-Item $sourceGithub $RepoPath -Recurse -Force

    Push-Location $RepoPath
    git add -A | Out-Null
    $hasChanges = (git status --porcelain) -ne $null
    if (-not $hasChanges) {
        Write-Host "  [--]  $Profile repo already up to date" -ForegroundColor DarkGray
        Pop-Location
        return $false
    }

    if ([string]::IsNullOrWhiteSpace($Message)) {
        $today = Get-Date -Format "yyyy-MM-dd"
        $Message = "feat: sync $Profile profile from caddis - $today"
    }

    git commit -m $Message | Out-Null
    if ($NoPush) {
        Write-Host "  [OK]  $Profile committed locally (no push)" -ForegroundColor Green
        Pop-Location
        return $true
    }

    git push | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [WARN]  $Profile push failed - the commit is local only. Fix the remote/auth and push manually." -ForegroundColor Yellow
        Pop-Location
        return $true  # committed, push failed - caller can retry
    }
    Write-Host "  [OK]  $Profile committed + pushed" -ForegroundColor Green
    Pop-Location
    return $true
}

function Sync-ExtensionRepo {
    # Shared helper for ptarmigan and liffey.
    # Runs bundle-pool.js in the repo (populates pool/ from the caddis-plugin mirror),
    # then copies the pre-built out/extension.js from junai-vscode, commits, and
    # optionally pushes.  Returns $true if a commit was made, $false otherwise.
    param(
        [Parameter(Mandatory)][string]$RepoPath,
        [Parameter(Mandatory)][string]$Label,
        [string]$ProjectRoot = "",
        [string]$Message = "",
        [switch]$NoPush,
        [switch]$AutoBumpVersion
    )

    if (-not (Test-Path $RepoPath)) {
        Write-Host "  [WARN]  $Label repo not found at $RepoPath" -ForegroundColor Yellow
        return $false
    }

    # 1. Refresh pool/ via the repo's own bundle-pool.js
    Push-Location $RepoPath
    $prevCaddisSource = $env:JUNAI_SOURCE
    try {
        if (-not [string]::IsNullOrWhiteSpace($ProjectRoot)) {
            $env:JUNAI_SOURCE = $ProjectRoot
        }
        node scripts/bundle-pool.js | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [WARN]  $Label bundle-pool failed." -ForegroundColor Yellow
            Pop-Location
            return $false
        }
    } finally {
        $env:JUNAI_SOURCE = $prevCaddisSource
    }

    # 2. Refresh out/ from the canonical junai-vscode build
    $outSrc = Join-Path $CADDIS_VSCODE "out"
    if (Test-Path $outSrc) {
        Copy-Item $outSrc $RepoPath -Recurse -Force
    }

    # 3. Commit if anything changed
    $managedChanges = git status --porcelain -- pool out
    $hasChanges = -not [string]::IsNullOrWhiteSpace(($managedChanges | Out-String).Trim())
    if (-not $hasChanges) {
        Write-Host "  [--]  $Label repo already up to date" -ForegroundColor DarkGray
        Pop-Location
        return $false
    }

    if ($AutoBumpVersion) {
        $null = Bump-PackageJsonPatchVersion -RepoPath $RepoPath -Label $Label

        $prevCaddisSource = $env:JUNAI_SOURCE
        try {
            if (-not [string]::IsNullOrWhiteSpace($ProjectRoot)) {
                $env:JUNAI_SOURCE = $ProjectRoot
            }
            node scripts/bundle-pool.js | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Write-Host "  [WARN]  $Label bundle-pool refresh after version bump failed." -ForegroundColor Yellow
                Pop-Location
                return $false
            }
        } finally {
            $env:JUNAI_SOURCE = $prevCaddisSource
        }
    }

    git add -- package.json pool out | Out-Null

    if ([string]::IsNullOrWhiteSpace($Message)) {
        $today = Get-Date -Format "yyyy-MM-dd"
        $Message = "feat: sync $($Label.ToLower()) pool from caddis - $today"
    }
    git commit -m $Message | Out-Null

    if ($NoPush) {
        Write-Host "  [OK]  $Label committed locally (no push)" -ForegroundColor Green
        Pop-Location
        return $true
    }

    git push | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [WARN]  $Label push failed." -ForegroundColor Yellow
        Pop-Location
        return $true  # committed, push failed - caller can retry
    }

    Write-Host "  [OK]  $Label committed + pushed" -ForegroundColor Green
    Pop-Location
    return $true
}

function sync-ptarmigan {
    param(
        [string]$ProjectRoot = $PSScriptRoot,
        [string]$Message = "",
        [switch]$NoPush,
        [switch]$Publish
    )

    Write-Host "  PTARMIGAN SYNC  caddis-plugin mirror --> $PTARMIGAN_REPO (pool/)" -ForegroundColor Cyan
    $changed = Sync-ExtensionRepo -RepoPath $PTARMIGAN_REPO -Label "Ptarmigan" -ProjectRoot $ProjectRoot -Message $Message -NoPush:$NoPush -AutoBumpVersion
    if (-not $changed -or $NoPush -or -not $Publish) {
        return $changed
    }

    $null = Publish-PtarmiganExtension
    return $changed
}

function sync-liffey {
    param(
        [string]$ProjectRoot = $PSScriptRoot,
        [string]$Message = "",
        [switch]$NoPush,
        [switch]$Package
    )

    Write-Host "  LIFFEY SYNC   caddis-plugin mirror --> $LIFFEY_REPO (pool/)" -ForegroundColor Cyan
    $changed = Sync-ExtensionRepo -RepoPath $LIFFEY_REPO -Label "Liffey" -ProjectRoot $ProjectRoot -Message $Message -NoPush:$NoPush -AutoBumpVersion
    if (-not $changed -or -not $Package) {
        return $changed
    }

    $null = Package-LiffeyExtension
    return $changed
}

function caddis-publish-mcp {
    # Bumps the version in pyproject.toml and publishes junai-mcp to PyPI.
    # Requires: pip install build twine (once per machine), PyPI credentials configured.
    #
    # Usage:
    #   caddis-publish-mcp           # prompts for new version
    #   caddis-publish-mcp -Version 0.1.2
    param([string]$Version = "")

    Push-Location $CADDIS_POOL

    $pyproject = Join-Path $CADDIS_POOL "pyproject.toml"
    if (-not (Test-Path $pyproject)) {
        Write-Host "  pyproject.toml not found at $CADDIS_POOL" -ForegroundColor Red
        Pop-Location
        return $false
    }

    $currentVer = Get-PyprojectVersion -PyprojectPath $pyproject
    if ([string]::IsNullOrWhiteSpace($currentVer)) {
        Write-Host "  [ERROR] Could not read a valid semantic version from $pyproject" -ForegroundColor Red
        Pop-Location
        return $false
    }

    Write-Host ""
    Write-Host "  CADDIS PUBLISH MCP  junai-mcp --> PyPI" -ForegroundColor Cyan
    Write-Host "  -----------------------------------------" -ForegroundColor DarkGray
    Write-Host "  Current version: $currentVer" -ForegroundColor DarkGray

    if ([string]::IsNullOrWhiteSpace($Version)) {
        $Version = Get-NextPatchVersion -VersionString $currentVer
        Write-Host "  [OK]  Auto-selected next patch version: $Version" -ForegroundColor Green
    } elseif ($Version -notmatch '^(\d+)\.(\d+)\.(\d+)$') {
        Write-Host "  [ERROR] MCP version must use semantic version format X.Y.Z: $Version" -ForegroundColor Red
        Pop-Location
        return $false
    }

    if ($Version -ne $currentVer) {
        Set-PyprojectVersion -PyprojectPath $pyproject -VersionString $Version
        Write-Host "  [OK]  pyproject.toml bumped $currentVer --> $Version" -ForegroundColor Green
    } else {
        Write-Host "  [--]  pyproject.toml version unchanged at $currentVer" -ForegroundColor DarkGray
    }

    # Clean old dist/
    $dist = Join-Path $CADDIS_POOL "dist"
    if (Test-Path $dist) { Remove-ItemRobust $dist }

    Write-Host "  Building..." -ForegroundColor DarkGray
    $pythonCommand = Get-CaddisPythonCommand
    if (-not $pythonCommand) {
        Pop-Location
        return $false
    }
    & $pythonCommand.Path @($pythonCommand.PrefixArgs + @("-m", "build")) 2>&1 | Where-Object { $_ -match "Successfully|error|ERROR" } | Write-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [ERROR] MCP build failed." -ForegroundColor Red
        Pop-Location
        return $false
    }

    Write-Host "  Uploading to PyPI..." -ForegroundColor DarkGray
    $uploadOk = $false
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        twine upload dist\*.whl dist\*.tar.gz 2>&1 | Tee-Object -Variable twineOut | Write-Host
        if ($LASTEXITCODE -eq 0) { $uploadOk = $true; break }
        if ($attempt -lt 3) {
            Write-Host "  [WARN]  Upload attempt $attempt failed, retrying in 5s..." -ForegroundColor Yellow
            Start-Sleep -Seconds 5
        }
    }
    if (-not $uploadOk) {
        Write-Host "  [ERROR] MCP upload failed after 3 attempts." -ForegroundColor Red
        Pop-Location
        return $false
    }

    # Commit version bump
    $hasChanges = (git status --porcelain) -ne $null
    if ($hasChanges) {
        git add pyproject.toml
        git commit -m "chore: bump junai-mcp to v$Version" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [ERROR] MCP version bump commit failed." -ForegroundColor Red
            Pop-Location
            return $false
        }
        git push | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [ERROR] MCP version bump push failed." -ForegroundColor Red
            Pop-Location
            return $false
        }
        Write-Host "  [OK]  Committed and pushed version bump" -ForegroundColor Green
    }

    Pop-Location
    Write-Host ""
    Write-Host "  Published junai-mcp v$Version to PyPI." -ForegroundColor Cyan
    Write-Host ""
    return $true
}

function Get-CaddisSourceHash {
    # Deterministic SHA256 over a package's SOURCE files (code only). Backs the
    # publish content-diff gate: an unchanged package is never re-uploaded to a
    # permanent registry (PyPI) / marketplace. Version-bearing files (pyproject.toml,
    # package.json) are intentionally EXCLUDED by the caller's extension filter so an
    # auto version bump alone does not look like a content change.
    param(
        [Parameter(Mandatory)][string]$RootPath,
        [string[]]$IncludeExt = @(".py"),
        [string[]]$ExcludeDirs = @("dist", "build", "out", "node_modules", "__pycache__", ".git", ".venv", ".egg-info")
    )
    if (-not (Test-Path $RootPath)) { return "" }
    $rootFull = (Resolve-Path $RootPath).Path
    $files = Get-ChildItem -Path $RootPath -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object {
            $IncludeExt -contains $_.Extension.ToLowerInvariant()
        } |
        Where-Object {
            $rel = $_.FullName.Substring($rootFull.Length).TrimStart('\', '/')
            $parts = $rel -split '[\\/]'
            -not ($parts | Where-Object { $ExcludeDirs -contains $_ -or $_ -like "*.egg-info" })
        } |
        Sort-Object { $_.FullName.Substring($rootFull.Length).TrimStart('\', '/').ToLowerInvariant() }
    if (-not $files) { return "" }
    $sb = New-Object System.Text.StringBuilder
    foreach ($f in $files) {
        $rel = $f.FullName.Substring($rootFull.Length).TrimStart('\', '/').Replace('\', '/').ToLowerInvariant()
        $fileHash = (Get-FileHash -Path $f.FullName -Algorithm SHA256).Hash
        [void]$sb.AppendLine("$rel  $fileHash")
    }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($sb.ToString())
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $hashBytes = $sha.ComputeHash($bytes)
    } finally {
        $sha.Dispose()
    }
    return (([System.BitConverter]::ToString($hashBytes)) -replace '-', '').ToLowerInvariant()
}

function Test-CaddisPublishNeeded {
    # Returns @{ Needed = <bool>; Hash = <string> }. Needed=$true when the source
    # hash differs from the marker written by the last successful publish. FAILS OPEN:
    # if the source can't be hashed (missing dir), Needed=$true so a real publish is
    # never silently skipped. -Force always publishes.
    param(
        [Parameter(Mandatory)][string]$SourceRoot,
        [Parameter(Mandatory)][string]$MarkerPath,
        [string[]]$IncludeExt = @(".py"),
        [switch]$Force
    )
    $current = Get-CaddisSourceHash -RootPath $SourceRoot -IncludeExt $IncludeExt
    if ($Force -or [string]::IsNullOrWhiteSpace($current)) {
        return @{ Needed = $true; Hash = $current }
    }
    $previous = ""
    if (Test-Path $MarkerPath) { $previous = (Get-Content $MarkerPath -Raw).Trim() }
    return @{ Needed = ($current -ne $previous); Hash = $current }
}

function Save-CaddisPublishMarker {
    param(
        [Parameter(Mandatory)][string]$MarkerPath,
        [Parameter(Mandatory)][string]$Hash
    )
    if ([string]::IsNullOrWhiteSpace($Hash)) { return }
    Set-Content -Path $MarkerPath -Value $Hash -Encoding UTF8
}

function caddis-release {
    # Publishes MCP package and VS Code extension using .env secrets first,
    # with legacy key files as fallback.
    #
    # A SHA256 content-diff gate skips any target whose SOURCE is unchanged since the
    # last successful publish (markers: .last-published-mcp.sha256 / -ext.sha256),
    # so a plugin-only session never re-uploads an identical MCP/extension. -Force
    # bypasses the gate.
    #
    # Usage:
    #   caddis-release                        # publish both MCP + extension (content-diff gated)
    #   caddis-release -SkipMcp               # extension only
    #   caddis-release -SkipExtension         # MCP only
    #   caddis-release -McpVersion "0.2.2"    # bump MCP version before publish
    #   caddis-release -ExtensionVersion "1.2.3"
    #   caddis-release -Force                 # ignore the content-diff gate
    param(
        [string]$McpVersion = "",
        [string]$ExtensionVersion = "",
        [switch]$SkipMcp,
        [switch]$SkipExtension,
        [switch]$Force
    )

    Write-Host ""
    Write-Host "  CADDIS RELEASE  MCP + VS Code" -ForegroundColor Cyan
    Write-Host "  -----------------------------------------" -ForegroundColor DarkGray

    # -- Pre-publish agent validation gate --
    $validatorScript = Join-Path $REPO_ROOT "validate_agents.py"
    $poolValidatorScript = Join-Path $REPO_ROOT "validate_pool.py"
    $pythonCommand = Get-CaddisPythonCommand
    if (-not $pythonCommand) {
        return $false
    }
    if (Test-Path $validatorScript) {
        & $pythonCommand.Path @($pythonCommand.PrefixArgs + @($validatorScript))
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [ABORT]  Agent validation failed. Fix errors above before publishing." -ForegroundColor Red
            return $false
        }

        if (Test-Path $poolValidatorScript) {
            & $pythonCommand.Path @($pythonCommand.PrefixArgs + @($poolValidatorScript))
            if ($LASTEXITCODE -ne 0) {
                Write-Host "  [ABORT]  Pool validation failed. Fix errors above before publishing." -ForegroundColor Red
                return $false
            }
        }
    } else {
        Write-Host "  [WARN]  validate_agents.py not found -- skipping validation" -ForegroundColor Yellow
    }

    if (-not $SkipMcp) {
        # Content-diff gate: SHA256 of the MCP source (src\ *.py - excludes the
        # version-bearing pyproject.toml) vs the last-published marker. PyPI is
        # permanent, so skip the upload entirely when the code is byte-identical.
        $mcpSourceRoot = Join-Path $CADDIS_POOL "src"
        $mcpMarker = Join-Path $CADDIS_POOL ".last-published-mcp.sha256"
        $mcpGate = Test-CaddisPublishNeeded -SourceRoot $mcpSourceRoot -MarkerPath $mcpMarker -IncludeExt @(".py") -Force:$Force
        if (-not $mcpGate.Needed) {
            Write-Host "  [--]  MCP source unchanged since last publish (SHA256 match); skipping PyPI upload." -ForegroundColor DarkGray
        } else {
            $pypiToken = Get-CaddisSecretValue -EnvName "JUNAI_PYPI_TOKEN" -LegacyFilePath $PYPI_KEY_FILE
            if ([string]::IsNullOrWhiteSpace($pypiToken)) {
                Write-Host "  [ERROR] Missing PyPI token. Set JUNAI_PYPI_TOKEN in $CADDIS_ENV_FILE or keep $PYPI_KEY_FILE." -ForegroundColor Red
                return $false
            }

            $prevTwineUser = $env:TWINE_USERNAME
            $prevTwinePass = $env:TWINE_PASSWORD
            try {
                $env:TWINE_USERNAME = "__token__"
                $env:TWINE_PASSWORD = $pypiToken
                $mcpPublished = [bool](caddis-publish-mcp -Version $McpVersion | Get-LastOutputValue)
                if (-not $mcpPublished) {
                    return $false
                }
            } finally {
                $env:TWINE_USERNAME = $prevTwineUser
                $env:TWINE_PASSWORD = $prevTwinePass
            }
            Save-CaddisPublishMarker -MarkerPath $mcpMarker -Hash $mcpGate.Hash
        }
    }

    # Content-diff gate for the extension: SHA256 of the source (src\ *.ts/*.js +
    # esbuild.mjs - excludes version-bearing package.json) vs the last-published marker.
    $extMarker = Join-Path $CADDIS_VSCODE ".last-published-ext.sha256"
    $extGate = $null
    if (-not $SkipExtension) {
        $extGate = Test-CaddisPublishNeeded -SourceRoot $CADDIS_VSCODE -MarkerPath $extMarker -IncludeExt @(".ts", ".js", ".mjs") -Force:$Force
        if (-not $extGate.Needed) {
            Write-Host "  [--]  Extension source unchanged since last publish (SHA256 match); skipping Marketplace publish." -ForegroundColor DarkGray
            $SkipExtension = $true
        }
    }

    if (-not $SkipExtension) {
        $vscePat = Get-CaddisSecretValue -EnvName "JUNAI_VSCE_PAT" -LegacyFilePath $VSCE_PAT_FILE
        if ([string]::IsNullOrWhiteSpace($vscePat)) {
            Write-Host "  [ERROR] Missing VS Code PAT. Set JUNAI_VSCE_PAT in $CADDIS_ENV_FILE or keep $VSCE_PAT_FILE." -ForegroundColor Red
            return $false
        }

        if (-not (Test-Path (Join-Path $CADDIS_VSCODE "package.json"))) {
            Write-Host "  [ERROR] junai-vscode repo not found at $CADDIS_VSCODE" -ForegroundColor Red
            return $false
        }

        $prevVscePat = $env:VSCE_PAT
        try {
            $env:VSCE_PAT = $vscePat
            Push-Location $CADDIS_VSCODE
            $packageJsonPath = Join-Path $CADDIS_VSCODE "package.json"
            $currentExtensionVersion = Get-PackageJsonVersion -PackageJsonPath $packageJsonPath
            if ([string]::IsNullOrWhiteSpace($currentExtensionVersion)) {
                Write-Host "  [ERROR] Could not read junai-vscode package version." -ForegroundColor Red
                return $false
            }

            if ([string]::IsNullOrWhiteSpace($ExtensionVersion)) {
                $ExtensionVersion = Get-NextPatchVersion -VersionString $currentExtensionVersion
            }

            if ($ExtensionVersion -ne $currentExtensionVersion) {
                Set-PackageJsonVersion -PackageJsonPath $packageJsonPath -VersionString $ExtensionVersion
                git add package.json
                git commit -m "chore: bump version to $ExtensionVersion" | Out-Null
                if ($LASTEXITCODE -ne 0) {
                    Write-Host "  [ERROR] junai-vscode version bump commit failed." -ForegroundColor Red
                    return $false
                }
                git push | Out-Null
                if ($LASTEXITCODE -ne 0) {
                    Write-Host "  [ERROR] junai-vscode version bump push failed." -ForegroundColor Red
                    return $false
                }
                Write-Host "  [OK]  junai-vscode version bumped $currentExtensionVersion --> $ExtensionVersion" -ForegroundColor Green
            } else {
                Write-Host "  [--]  junai-vscode version unchanged at $currentExtensionVersion" -ForegroundColor DarkGray
            }

            Write-Host "  Publishing VS Code extension..." -ForegroundColor DarkGray
            npx vsce publish --pat $vscePat --no-dependencies
            if ($LASTEXITCODE -ne 0) {
                Write-Host "  [ERROR] VS Code extension publish failed." -ForegroundColor Red
                return $false
            }

            Confirm-VscePublishedVersion -ExtensionId "junai-labs.junai" -ExpectedVersion $ExtensionVersion | Out-Null
            if ($extGate) { Save-CaddisPublishMarker -MarkerPath $extMarker -Hash $extGate.Hash }
        } finally {
            Pop-Location
            $env:VSCE_PAT = $prevVscePat
        }
    }

    Write-Host "  [OK]  Release flow completed." -ForegroundColor Green
    Write-Host ""
    return $true
}

function caddis-smoke-release {
    param([string]$ProjectRoot = $REPO_ROOT)

    Write-Host ""
    Write-Host "  CADDIS RELEASE SMOKE TEST" -ForegroundColor Cyan
    Write-Host "  -----------------------------------------" -ForegroundColor DarkGray

    $escapedPtarmigan = $PTARMIGAN_REPO.Replace("'", "''")
    $escapedLiffey = $LIFFEY_REPO.Replace("'", "''")
    $scriptText = @"
`$pythonCommand = Get-CaddisPythonCommand
if (-not `$pythonCommand) { throw 'Python resolution failed' }
Write-Host "[OK] python: `$(`$pythonCommand.Path)"

`$mcpVersion = Get-PyprojectVersion -PyprojectPath (Join-Path `$CADDIS_POOL 'pyproject.toml')
if ([string]::IsNullOrWhiteSpace(`$mcpVersion)) { throw 'caddis-plugin pyproject.toml version is missing or invalid' }
if ([string]::IsNullOrWhiteSpace((Try-GetNextPatchVersion -VersionString `$mcpVersion))) { throw ('caddis-plugin pyproject.toml version is not semver: ' + `$mcpVersion) }
Write-Host ('[OK] caddis-plugin pyproject.toml version: ' + `$mcpVersion)

& `$pythonCommand.Path @(`$pythonCommand.PrefixArgs + @('validate_agents.py'))
if (`$LASTEXITCODE -ne 0) { throw 'validate_agents.py failed' }
Write-Host '[OK] validate_agents.py'

& `$pythonCommand.Path @(`$pythonCommand.PrefixArgs + @('export_runtime_resources.py', '--profile', 'ptarmigan', '--profile', 'liffey', '--report'))
if (`$LASTEXITCODE -ne 0) { throw 'export_runtime_resources.py failed' }
Write-Host '[OK] export_runtime_resources.py'

& `$pythonCommand.Path @(`$pythonCommand.PrefixArgs + @('validate_pool.py', '--include-dist'))
if (`$LASTEXITCODE -ne 0) { throw 'validate_pool.py --include-dist failed' }
Write-Host '[OK] validate_pool.py --include-dist'

`$ptarmiganStage = Test-ManagedExtensionStaging -RepoPath '$escapedPtarmigan' -Label 'Ptarmigan'
if (-not `$ptarmiganStage.Passed) {
    throw ('Ptarmigan unmanaged staging leak: ' + ([string]::Join('; ', `$ptarmiganStage.Unexpected)))
}
Write-Host '[OK] Ptarmigan managed staging'

`$liffeyStage = Test-ManagedExtensionStaging -RepoPath '$escapedLiffey' -Label 'Liffey'
if (-not `$liffeyStage.Passed) {
    throw ('Liffey unmanaged staging leak: ' + ([string]::Join('; ', `$liffeyStage.Unexpected)))
}
Write-Host '[OK] Liffey managed staging'
"@

    $exitCode = Invoke-CaddisFreshShell -ScriptText $scriptText -WorkingDirectory $ProjectRoot
    if ($exitCode -ne 0) {
        Write-Host "  [FAIL] Release smoke test failed." -ForegroundColor Red
        return $false
    }

    Write-Host "  [OK]  Release smoke test passed." -ForegroundColor Green
    Write-Host ""
    return $true
}

function caddis-ship {
    param(
        [string]$ProjectRoot = $REPO_ROOT,
        [string]$Message = "",
        [string]$McpVersion = "",
        [string]$CaddisExtensionVersion = "",
        [string[]]$Lanes = @("auto"),
        [string[]]$Profiles = @("auto"),
        [switch]$PublishMcp,
        [switch]$PublishCaddisExtension,
        [switch]$PublishPtarmigan,
        [switch]$PackageLiffey,
        [switch]$PublishAll,
        [switch]$SkipSmokeTest
    )

    if ($PublishAll) {
        $PublishMcp = $true
        $PublishCaddisExtension = $true
        $PublishPtarmigan = $true
        $PackageLiffey = $true
    }

    Write-Host ""
    Write-Host "  CADDIS SHIP" -ForegroundColor Magenta
    Write-Host "  -----------------------------------------" -ForegroundColor DarkGray

    $smokeStatus = if ($SkipSmokeTest) { "skipped" } else { "pending" }
    if (-not $SkipSmokeTest) {
        if (-not (caddis-smoke-release -ProjectRoot $ProjectRoot)) {
            Write-Host "  [ABORT]  Ship halted because the release smoke test failed." -ForegroundColor Red
            return $false
        }
        $smokeStatus = "passed"
    }

    $projectName = Split-Path $ProjectRoot -Leaf
    if ([string]::IsNullOrWhiteSpace($Message)) {
        $Message = "chore: ship from $projectName - $(Get-Date -Format 'yyyy-MM-dd')"
    }

    $normalizedLanes = @($Lanes | ForEach-Object { ([string]$_).Trim().ToLowerInvariant() } | Where-Object { $_ })
    if ($normalizedLanes.Count -eq 0) {
        $normalizedLanes = @("auto")
    }

    $normalizedProfiles = @($Profiles | ForEach-Object { ([string]$_).Trim().ToLowerInvariant() } | Where-Object { $_ })
    if ($normalizedProfiles.Count -eq 0) {
        $normalizedProfiles = @("auto")
    }

    $sourceChangedPaths = @(Get-RepoChangedPaths -RepoPath $ProjectRoot)
    $caddisChangedPaths = @(Get-RepoChangedPaths -RepoPath $CADDIS_POOL)
    $caddisVscodeChangedPaths = @(Get-RepoChangedPaths -RepoPath $CADDIS_VSCODE)
    $ptarmiganChangedPaths = @(Get-RepoChangedPaths -RepoPath $PTARMIGAN_REPO)
    $liffeyChangedPaths = @(Get-RepoChangedPaths -RepoPath $LIFFEY_REPO)

    $sourceReleaseTargets = @(Get-AffectedReleaseTargetsFromSourcePaths -ChangedPaths $sourceChangedPaths)
    $caddisVscodeDirectReleasePaths = @(Get-ReleaseRelevantRepoChangedPaths -Lane "junai-vscode" -ChangedPaths $caddisVscodeChangedPaths)
    $ptarmiganDirectReleasePaths = @(Get-ReleaseRelevantRepoChangedPaths -Lane "ptarmigan" -ChangedPaths $ptarmiganChangedPaths)
    $liffeyDirectReleasePaths = @(Get-ReleaseRelevantRepoChangedPaths -Lane "liffey" -ChangedPaths $liffeyChangedPaths)
    $mcpDirectReleasePaths = @(Get-ReleaseRelevantRepoChangedPaths -Lane "mcp" -ChangedPaths $caddisChangedPaths)

    $sourceDirty = $sourceChangedPaths.Count -gt 0
    $caddisVscodeDirty = $caddisVscodeChangedPaths.Count -gt 0
    $ptarmiganDirty = $ptarmiganChangedPaths.Count -gt 0
    $liffeyDirty = $liffeyChangedPaths.Count -gt 0

    $autoLaneMode = $normalizedLanes -contains "auto"
    $runSourceLane = if ($autoLaneMode) { $sourceDirty } else { $normalizedLanes -contains "source" }
    $runCaddisVscodeLane = if ($autoLaneMode) { $caddisVscodeDirty } else { $normalizedLanes -contains "junai-vscode" }
    $runPtarmiganLane = if ($autoLaneMode) { $ptarmiganDirty } else { $normalizedLanes -contains "ptarmigan" }
    $runLiffeyLane = if ($autoLaneMode) { $liffeyDirty } else { $normalizedLanes -contains "liffey" }

    if ($normalizedProfiles -contains "none") {
        $sourceProfiles = @()
    } elseif ($normalizedProfiles -contains "auto") {
        $sourceProfiles = if ($sourceDirty) { @(Get-AffectedProfileNamesFromSourcePaths -ChangedPaths $sourceChangedPaths) } else { @() }
    } else {
        $sourceProfiles = @($normalizedProfiles | Where-Object { $_ -in @("ptarmigan", "liffey") } | Select-Object -Unique)
    }

    if (-not $runSourceLane) {
        $sourceProfiles = @()
    }

    $sourceCommitted = $false
    $sourcePushResult = [pscustomobject]@{
        MirrorChanged = $false
        SelectedProfiles = @()
        ProfileResults = @{}
        ReleaseTriggered = $false
    }

    if ($runCaddisVscodeLane) {
        $null = Commit-RepoIfDirty -RepoPath $CADDIS_VSCODE -Label "junai-vscode" -Message "$Message (junai-vscode)" -Push
    }
    if ($runPtarmiganLane) {
        $null = Commit-RepoIfDirty -RepoPath $PTARMIGAN_REPO -Label "Ptarmigan" -Message "$Message (ptarmigan)" -Push
    }
    if ($runLiffeyLane) {
        $null = Commit-RepoIfDirty -RepoPath $LIFFEY_REPO -Label "Liffey" -Message "$Message (liffey)" -Push
    }

    if ($runSourceLane) {
        Push-Location $ProjectRoot
        try {
            $statusOutput = @(git status --porcelain)
            $hasSourceChanges = -not [string]::IsNullOrWhiteSpace(($statusOutput | Out-String).Trim())
            if ($hasSourceChanges) {
                git add -A | Out-Null
                git commit -m $Message | Out-Null
                if ($LASTEXITCODE -ne 0) {
                    Write-Host "  [ABORT]  Source commit failed." -ForegroundColor Red
                    return $false
                }
                $sourceCommitted = $true
                Write-Host "  [OK]  Source repo committed." -ForegroundColor Green
            } else {
                Write-Host "  [--]  Source repo already clean; skipping source commit." -ForegroundColor DarkGray
            }
        } finally {
            Pop-Location
        }

        $skipProfileSync = ($sourceProfiles.Count -eq 0)
        $sourcePushResult = caddis-push -ProjectRoot $ProjectRoot -Message $Message -NoPublish -Profiles $sourceProfiles -SkipProfileSync:$skipProfileSync | Get-LastOutputValue
    } else {
        Write-Host "  [--]  Source lane not selected; skipping canonical mirror sync." -ForegroundColor DarkGray
    }

    $sourceMirrorChanged = [bool]$sourcePushResult.MirrorChanged
    $ptarmiganProfileChanged = [bool]$sourcePushResult.ProfileResults["ptarmigan"]
    $liffeyProfileChanged = [bool]$sourcePushResult.ProfileResults["liffey"]

    $caddisExtensionReleaseStatus = "not requested"
    $mcpReleaseStatus = "not requested"
    $ptarmiganReleaseStatus = "not requested"
    $liffeyPackageStatus = "not requested"

    $shouldPublishCaddisExtension = $false
    $shouldPublishMcp = $false
    $shouldPublishPtarmigan = $false
    $shouldPackageLiffey = $false

    if ($PublishCaddisExtension) {
        $caddisExtensionChanged = (($sourceMirrorChanged -and ($sourceReleaseTargets -contains "junai-vscode")) -or $caddisVscodeDirectReleasePaths.Count -gt 0)
        if (-not $caddisExtensionChanged) {
            $caddisExtensionReleaseStatus = "skipped - unchanged"
        } else {
            $resolvedCaddisVersion = if ([string]::IsNullOrWhiteSpace($CaddisExtensionVersion)) {
                Try-GetNextPatchVersion -VersionString (Get-PackageJsonVersion -PackageJsonPath (Join-Path $CADDIS_VSCODE "package.json"))
            } else {
                $CaddisExtensionVersion
            }

            if ([string]::IsNullOrWhiteSpace($resolvedCaddisVersion)) {
                $caddisExtensionReleaseStatus = "skipped - no version bump path"
            } else {
                $CaddisExtensionVersion = $resolvedCaddisVersion
                $shouldPublishCaddisExtension = $true
                $caddisExtensionReleaseStatus = "pending"
            }
        }
    }

    if ($PublishMcp) {
        $mcpChanged = (($sourceMirrorChanged -and ($sourceReleaseTargets -contains "mcp")) -or $mcpDirectReleasePaths.Count -gt 0)
        if (-not $mcpChanged) {
            $mcpReleaseStatus = "skipped - unchanged"
        } else {
            $resolvedMcpVersion = if ([string]::IsNullOrWhiteSpace($McpVersion)) {
                Try-GetNextPatchVersion -VersionString (Get-PyprojectVersion -PyprojectPath (Join-Path $CADDIS_POOL "pyproject.toml"))
            } else {
                $McpVersion
            }

            if ([string]::IsNullOrWhiteSpace($resolvedMcpVersion)) {
                $mcpReleaseStatus = "skipped - no version bump path"
            } else {
                $McpVersion = $resolvedMcpVersion
                $shouldPublishMcp = $true
                $mcpReleaseStatus = "pending"
            }
        }
    }

    if ($PublishPtarmigan) {
        $ptarmiganChangedForRelease = ($ptarmiganProfileChanged -or $ptarmiganDirectReleasePaths.Count -gt 0)
        if (-not $ptarmiganChangedForRelease) {
            $ptarmiganReleaseStatus = "skipped - unchanged"
        } else {
            if (-not $ptarmiganProfileChanged -and $ptarmiganDirectReleasePaths.Count -gt 0) {
                $ptarmiganNextVersion = Try-GetNextPatchVersion -VersionString (Get-PackageJsonVersion -PackageJsonPath (Join-Path $PTARMIGAN_REPO "package.json"))
                if ([string]::IsNullOrWhiteSpace($ptarmiganNextVersion)) {
                    $ptarmiganReleaseStatus = "skipped - no version bump path"
                } else {
                    $null = Commit-PackageJsonPatchVersion -RepoPath $PTARMIGAN_REPO -Label "Ptarmigan"
                    $shouldPublishPtarmigan = $true
                    $ptarmiganReleaseStatus = "pending"
                }
            } else {
                $shouldPublishPtarmigan = $true
                $ptarmiganReleaseStatus = "pending"
            }
        }
    }

    if ($PackageLiffey) {
        $liffeyChangedForRelease = ($liffeyProfileChanged -or $liffeyDirectReleasePaths.Count -gt 0)
        if (-not $liffeyChangedForRelease) {
            $liffeyPackageStatus = "skipped - unchanged"
        } else {
            if (-not $liffeyProfileChanged -and $liffeyDirectReleasePaths.Count -gt 0) {
                $liffeyNextVersion = Try-GetNextPatchVersion -VersionString (Get-PackageJsonVersion -PackageJsonPath (Join-Path $LIFFEY_REPO "package.json"))
                if ([string]::IsNullOrWhiteSpace($liffeyNextVersion)) {
                    $liffeyPackageStatus = "skipped - no version bump path"
                } else {
                    $null = Commit-PackageJsonPatchVersion -RepoPath $LIFFEY_REPO -Label "Liffey"
                    $shouldPackageLiffey = $true
                    $liffeyPackageStatus = "pending"
                }
            } else {
                $shouldPackageLiffey = $true
                $liffeyPackageStatus = "pending"
            }
        }
    }

    if ($shouldPublishMcp -or $shouldPublishCaddisExtension) {
        $releaseOk = [bool](caddis-release -McpVersion $McpVersion -ExtensionVersion $CaddisExtensionVersion -SkipMcp:(-not $shouldPublishMcp) -SkipExtension:(-not $shouldPublishCaddisExtension) | Get-LastOutputValue)
        if (-not $releaseOk) {
            Write-Host "  [ABORT]  caddis-plugin release failed." -ForegroundColor Red
            return $false
        }
        if ($shouldPublishMcp) {
            $mcpReleaseStatus = "published"
        }
        if ($shouldPublishCaddisExtension) {
            $caddisExtensionReleaseStatus = "published"
        }
    }

    if ($shouldPublishPtarmigan) {
        if (-not ([bool](Publish-PtarmiganExtension | Get-LastOutputValue))) {
            Write-Host "  [ABORT]  Ptarmigan publish failed." -ForegroundColor Red
            return $false
        }
        $ptarmiganReleaseStatus = "published"
    }

    if ($shouldPackageLiffey) {
        $packagedVsix = Package-LiffeyExtension | Get-LastOutputValue
        if (-not $packagedVsix) {
            Write-Host "  [ABORT]  Liffey packaging failed." -ForegroundColor Red
            return $false
        }
        $liffeyPackageStatus = "packaged"
    }

    $liffeyVersion = Get-PackageJsonVersion -PackageJsonPath (Join-Path $LIFFEY_REPO "package.json")
    $liffeyVsix = if ([string]::IsNullOrWhiteSpace($liffeyVersion)) { $null } else { Join-Path $LIFFEY_REPO "dist\liffey-$liffeyVersion.vsix" }

    Write-Host ""
    Write-Host "  CADDIS SHIP SUMMARY" -ForegroundColor Cyan
    Write-Host "  -----------------------------------------" -ForegroundColor DarkGray
    Write-Host "  lanes requested       : $([string]::Join(', ', $normalizedLanes))" -ForegroundColor DarkGray
    Write-Host "  source profiles       : $(if ($sourceProfiles.Count -gt 0) { [string]::Join(', ', $sourceProfiles) } else { 'none' })" -ForegroundColor DarkGray
    Write-Host "  smoke test            : $smokeStatus" -ForegroundColor DarkGray
    Write-Host "  source committed      : $sourceCommitted" -ForegroundColor DarkGray
    Write-Host "  mcp release           : $mcpReleaseStatus" -ForegroundColor DarkGray
    Write-Host "  caddis-plugin release : $caddisExtensionReleaseStatus" -ForegroundColor DarkGray
    Write-Host "  ptarmigan release     : $ptarmiganReleaseStatus" -ForegroundColor DarkGray
    Write-Host "  liffey package        : $liffeyPackageStatus" -ForegroundColor DarkGray
    Write-Host "  source HEAD           : $(Get-RepoHeadLine -RepoPath $ProjectRoot)" -ForegroundColor DarkGray
    Write-Host "  caddis-plugin HEAD    : $(Get-RepoHeadLine -RepoPath $CADDIS_POOL)" -ForegroundColor DarkGray
    Write-Host "  junai-vscode HEAD     : $(Get-RepoHeadLine -RepoPath $CADDIS_VSCODE)" -ForegroundColor DarkGray
    Write-Host "  ptarmigan HEAD        : $(Get-RepoHeadLine -RepoPath $PTARMIGAN_REPO)" -ForegroundColor DarkGray
    Write-Host "  liffey HEAD           : $(Get-RepoHeadLine -RepoPath $LIFFEY_REPO)" -ForegroundColor DarkGray
    if ($liffeyVsix) {
        $vsixState = if (Test-Path $liffeyVsix) { $liffeyVsix } else { "missing ($liffeyVsix)" }
        Write-Host "  liffey VSIX         : $vsixState" -ForegroundColor DarkGray
    }
    Write-Host ""
    return $true
}

function caddis-revert {
    # Reverts one or more commits in caddis and cascades to all downstream
    # repos (caddis-plugin, junai-vscode, and any explicit project repos).
    # Safe -- new revert commits, no history rewrite.
    #
    # Usage:
    #   caddis-revert                                         # revert HEAD (last commit)
    #   caddis-revert -Last 3                                 # revert last 3 commits
    #   caddis-revert -Sha abc123                             # revert one specific commit
    #   caddis-revert -Sha abc123,def456,ghi789               # revert multiple commits
    #   caddis-revert -Last 2 -NoCascade                      # revert caddis only
    #   caddis-revert -Last 3 -Force                          # skip confirmation (chat / CI use)
    #   caddis-revert -Last 3 -Projects "E:\Projects\Foo"     # also restore pool in project repo
    #   caddis-revert -Last 3 -Projects "E:\P\Foo,E:\P\Bar"  # multiple project repos
    param(
        [string[]]$Sha       = @(),
        [int]$Last           = 0,
        [string]$Message     = "",
        [string[]]$Projects  = @(),
        [switch]$NoCascade,
        [switch]$Force
    )

    $agentSandbox = $REPO_ROOT

    Push-Location $agentSandbox

    # -- Resolve which SHAs to revert ------------------------------------------
    $resolved = @()

    if ($Sha.Count -gt 0) {
        # Accept comma-separated values passed as a single string element
        $expanded = $Sha | ForEach-Object { $_ -split ',' } |
                           ForEach-Object { $_.Trim() } |
                           Where-Object   { $_ -ne '' }
        foreach ($s in $expanded) {
            $check = git log --oneline -1 $s 2>&1
            if ($LASTEXITCODE -ne 0) {
                Write-Host "  [ERROR]  Commit not found: $s" -ForegroundColor Red
                Pop-Location; return
            }
            $resolved += $s
        }
    } elseif ($Last -gt 0) {
        $resolved = @(git log --format="%H" -n $Last)
    } else {
        # Default: revert HEAD
        $resolved = @(git log --format="%H" -n 1)
    }

    if ($resolved.Count -eq 0) {
        Write-Host "  [ERROR]  No commits resolved to revert." -ForegroundColor Red
        Pop-Location; return
    }

    # Sort newest-first by walking git log order (avoids conflicts on revert)
    $allHashes = @(git log --format="%H")
    $resolved  = $allHashes | Where-Object { $resolved -contains $_ }

    # Expand comma-separated project paths
    $projectList = $Projects | ForEach-Object { $_ -split ',' } |
                               ForEach-Object { $_.Trim() } |
                               Where-Object   { $_ -ne '' }

    # -- Show plan -------------------------------------------------------------
    Write-Host ""
    Write-Host "  CADDIS REVERT" -ForegroundColor Yellow
    Write-Host "  -----------------------------------------" -ForegroundColor DarkGray
    Write-Host "  Commits to revert (newest first):" -ForegroundColor Yellow
    $n = 1
    foreach ($s in $resolved) {
        $line = git log --oneline -1 $s
        Write-Host "    [$n] $line" -ForegroundColor Yellow
        $n++
    }
    Write-Host ""
    if ($NoCascade) {
        Write-Host "  Cascade   : caddis only (-NoCascade)" -ForegroundColor DarkGray
    } else {
        Write-Host "  Cascade   : caddis --> caddis-plugin --> junai-vscode (at next publish)" -ForegroundColor DarkGray
        foreach ($proj in $projectList) {
            Write-Host "              --> $(Split-Path $proj -Leaf)  (caddis-pull + commit)" -ForegroundColor DarkGray
        }
    }
    Write-Host ""

    if (-not $Force) {
        $confirm = Read-Host "  Proceed? (y/N)"
        if ($confirm -notmatch '^[Yy]$') {
            Write-Host "  Cancelled." -ForegroundColor DarkGray
            Pop-Location; return
        }
    }

    # -- Revert each commit (newest first) -------------------------------------
    foreach ($s in $resolved) {
        git revert --no-edit $s | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [ERROR]  git revert failed on $s -- resolve conflicts manually." -ForegroundColor Red
            Pop-Location; return
        }
        Write-Host "  [OK]  reverted $s" -ForegroundColor Green
    }

    # Apply custom message to the final revert commit if provided
    if (-not [string]::IsNullOrWhiteSpace($Message)) {
        git commit --amend -m $Message | Out-Null
    }

    git push | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Pop-Location
        throw "caddis-revert: git push failed (exit $LASTEXITCODE) - the revert commit is local only; cascade aborted. Fix the remote/auth and re-run."
    }
    Write-Host "  [OK]  caddis pushed" -ForegroundColor Green

    Pop-Location

    # -- Cascade to downstream repos -------------------------------------------
    if (-not $NoCascade) {
        $revertMsg = "revert: undo $($resolved.Count) commit(s) from caddis"
        if (-not [string]::IsNullOrWhiteSpace($Message)) { $revertMsg = $Message }

        # 1. caddis-plugin -- pool folders + server.py SHA check (handled inside caddis-push)
        caddis-push -Message $revertMsg

        # 2. caddis-plugin root sync.ps1 -- not inside pool folders, synced separately
        $srcSync = Join-Path $agentSandbox "sync.ps1"
        $dstSync = Join-Path $CADDIS_POOL    "sync.ps1"
        if (Test-Path $srcSync) {
            $srcHash = (Get-FileHash $srcSync -Algorithm SHA256).Hash
            $dstHash = (Get-FileHash $dstSync -Algorithm SHA256).Hash
            if ($srcHash -ne $dstHash) {
                Copy-Item $srcSync $dstSync -Force
                Push-Location $CADDIS_POOL
                git add sync.ps1
                $dirty = (git status --porcelain) -ne $null
                if ($dirty) {
                    git commit -m "$revertMsg (sync.ps1)" | Out-Null
                    git push | Out-Null
                    if ($LASTEXITCODE -ne 0) {
                        Write-Host "  [WARN]  caddis-plugin sync.ps1 revert push failed - commit is local only in the caddis-plugin mirror." -ForegroundColor Yellow
                    } else {
                        Write-Host "  [OK]  caddis-plugin sync.ps1 reverted" -ForegroundColor Green
                    }
                }
                Pop-Location
            }
        }

        # 3. junai-vscode -- pool/ is gitignored, rebuilt from caddis at publish
        Write-Host "  [--]  junai-vscode pool/ is gitignored -- auto-updates at next publish" -ForegroundColor DarkGray

        # 4. Project repos -- restore reverted pool via caddis-pull + commit + push
        foreach ($proj in $projectList) {
            $githubDir = Join-Path $proj ".github"
            if (-not (Test-Path $githubDir)) {
                Write-Host "  [SKIP] $(Split-Path $proj -Leaf) -- no .github/ found" -ForegroundColor Yellow
                continue
            }
            Write-Host "  Restoring pool in $(Split-Path $proj -Leaf) ..." -ForegroundColor DarkGray
            caddis-pull -ProjectRoot $proj
            Push-Location $proj
            $dirty = (git status --porcelain) -ne $null
            if ($dirty) {
                git add ".github"
                git commit -m "$revertMsg (pool)" | Out-Null
                git push | Out-Null
                if ($LASTEXITCODE -ne 0) {
                    Write-Host "  [WARN]  $(Split-Path $proj -Leaf) pool revert push failed - commit is local only." -ForegroundColor Yellow
                } else {
                    Write-Host "  [OK]  $(Split-Path $proj -Leaf) pool reverted and pushed" -ForegroundColor Green
                }
            } else {
                Write-Host "  [--]  $(Split-Path $proj -Leaf) -- pool already up to date" -ForegroundColor DarkGray
            }
            Pop-Location
        }
    }

    Write-Host ""
    Write-Host "  Done. Revert complete." -ForegroundColor Yellow
    Write-Host ""
}

function caddis-export {
    # Exports the AI resource pool to a self-contained local folder or zip.
    # Use this when the target machine has no GitHub access.
    #
    # Usage:
    #   caddis-export                          # exports to .\caddis-pool-export\
    #   caddis-export -OutputPath C:\USB\caddis-plugin  # exports to specific path
    #   caddis-export -Zip                     # exports to .\caddis-pool-export.zip
    param(
        [string]$OutputPath = (Join-Path (Get-Location).Path "caddis-pool-export"),
        [switch]$Zip
    )

    $date = Get-Date -Format "yyyy-MM-dd"
    $zipPath = "$OutputPath-$date.zip"

    if ($Zip) {
        $OutputPath = Join-Path ([System.IO.Path]::GetTempPath()) "caddis-pool-export-tmp"
    }
    New-Item -ItemType Directory -Path $OutputPath | Out-Null

    Write-Host ""
    Write-Host "  CADDIS EXPORT  caddis-plugin --> $OutputPath" -ForegroundColor Cyan
    Write-Host "  -----------------------------------------" -ForegroundColor DarkGray

    # Pre-export hygiene: remove generated caches from source + export target.
    Remove-CaddisCacheDirs -RootPath $CADDIS_GITHUB -Label "pool"
    Remove-CaddisCacheDirs -RootPath $OutputPath -Label "export"

    foreach ($folder in $POOL_FOLDERS) {
        $src = Join-Path $CADDIS_GITHUB $folder
        $dest = Join-Path $OutputPath $folder
        if (Test-Path $src) {
            if (Test-Path $dest) {
                Remove-ItemRobust $dest
            }
            Copy-Item $src $OutputPath -Recurse -Force
            Write-Host "  [OK]  $folder" -ForegroundColor Green
        } else {
            Write-Host "  [--]  $folder - not found, skipped" -ForegroundColor Yellow
        }
    }

    # Include .vscode/mcp.json
    $mcpSrc = Join-Path $CADDIS_POOL ".vscode\mcp.json"
    if (Test-Path $mcpSrc) {
        $vscodeDst = Join-Path $OutputPath ".vscode"
        if (-not (Test-Path $vscodeDst)) { New-Item -ItemType Directory -Path $vscodeDst | Out-Null }
        Copy-Item $mcpSrc $vscodeDst -Force
        Write-Host "  [OK]  .vscode/mcp.json" -ForegroundColor Green
    }

    # Include the sync script itself so the target can dot-source it
    Copy-Item (Join-Path $CADDIS_POOL "sync.ps1") $OutputPath -Force
    Write-Host "  [OK]  sync.ps1" -ForegroundColor Green

    if ($Zip) {
        Compress-Archive -Path "$OutputPath\*" -DestinationPath $zipPath -Force
        Remove-Item $OutputPath -Recurse -Force
        Write-Host ""
        Write-Host "  Exported to: $zipPath" -ForegroundColor Cyan
    } else {
        Write-Host ""
        Write-Host "  Exported to: $OutputPath" -ForegroundColor Cyan
    }

    Write-Host "  On the target machine, run:" -ForegroundColor DarkGray
    Write-Host "    caddis-import PATH-TO-EXPORT-FOLDER   # from any project root" -ForegroundColor DarkGray
    Write-Host ""
}

function caddis-import {
    # Imports AI resource pool from a local export folder (created by caddis-export).
    # Use this on machines with no GitHub access.
    #
    # Usage (run from the target project root):
    #   caddis-import C:\USB\caddis-pool-export
    #   caddis-import C:\USB\caddis-pool-export-2026-02-20.zip
    param(
        [Parameter(Mandatory)][string]$SourcePath,
        [string]$ProjectRoot = (Get-Location).Path
    )

    $target = Join-Path $ProjectRoot ".github"
    $localOnlyBackup = Backup-LocalOnlyPoolFiles -GithubRoot $target

    if (-not (Test-Path $target)) {
        Write-Host "No .github/ folder found at $ProjectRoot" -ForegroundColor Red
        Write-Host "Are you in a project root?" -ForegroundColor Yellow
        return
    }

    # Handle zip input
    $tmpExtract = $null
    if ($SourcePath -match '\.zip$') {
        $tmpExtract = Join-Path ([System.IO.Path]::GetTempPath()) "caddis-import-tmp"
        if (Test-Path $tmpExtract) { Remove-Item $tmpExtract -Recurse -Force }
        Expand-Archive -Path $SourcePath -DestinationPath $tmpExtract
        $SourcePath = $tmpExtract
    }

    if (-not (Test-Path $SourcePath)) {
        Write-Host "Source path not found: $SourcePath" -ForegroundColor Red
        return
    }

    Write-Host ""
    Write-Host "  CADDIS IMPORT  $SourcePath --> $(Split-Path $ProjectRoot -Leaf)" -ForegroundColor Cyan
    Write-Host "  -----------------------------------------" -ForegroundColor DarkGray

    # Pre-import hygiene: remove generated caches in import source + target.
    Remove-CaddisCacheDirs -RootPath $SourcePath -Label "import source"
    Remove-CaddisCacheDirs -RootPath $target -Label "project"

    foreach ($folder in $POOL_FOLDERS) {
        $src = Join-Path $SourcePath $folder
        $dest = Join-Path $target $folder
        if (Test-Path $src) {
            # Clean destination first to prevent folder nesting and stale files.
            if (Test-Path $dest) {
                Remove-ItemRobust $dest
            }
            Copy-Item $src $target -Recurse -Force
            Write-Host "  [OK]  $folder" -ForegroundColor Green
        } else {
            # Import source no longer has this folder: remove stale local copy.
            if (Test-Path $dest) {
                Remove-ItemRobust $dest
                Write-Host "  [OK]  $folder - removed stale local folder" -ForegroundColor Green
            } else {
                Write-Host "  [--]  $folder - not in export, skipped" -ForegroundColor Yellow
            }
        }
    }

    # Deploy .vscode/mcp.json
    $mcpSrc = Join-Path $SourcePath ".vscode\mcp.json"
    if (Test-Path $mcpSrc) {
        $vscodeTarget = Join-Path $ProjectRoot ".vscode"
        if (-not (Test-Path $vscodeTarget)) { New-Item -ItemType Directory -Path $vscodeTarget | Out-Null }
        Copy-Item $mcpSrc $vscodeTarget -Force
        Write-Host "  [OK]  .vscode/mcp.json" -ForegroundColor Green
    }

    Restore-LocalOnlyPoolFiles -GithubRoot $target -Backup $localOnlyBackup

    if ($tmpExtract -and (Test-Path $tmpExtract)) {
        Remove-Item $tmpExtract -Recurse -Force
    }

    Write-Host ""
    Write-Host "  Done. project-config.md was NOT overwritten." -ForegroundColor DarkGray
    Write-Host "  Remember to create/update copilot-instructions.md for this project." -ForegroundColor DarkGray
    Write-Host ""
}

# ---------------------------------------------------------------------------
# Back-compat aliases (repo rename, 2026-07: junai -> caddis-plugin).
# The verbs were renamed junai-* -> caddis-*. These aliases keep muscle memory
# and any un-updated script working for ONE version, then they are dropped.
# ---------------------------------------------------------------------------
Set-Alias junai-pull         caddis-pull
Set-Alias junai-push         caddis-push
Set-Alias junai-publish-mcp  caddis-publish-mcp
Set-Alias junai-release      caddis-release
Set-Alias junai-smoke-release caddis-smoke-release
Set-Alias junai-ship         caddis-ship
Set-Alias junai-revert       caddis-revert
Set-Alias junai-export       caddis-export
Set-Alias junai-import       caddis-import
