<#
.SYNOPSIS
  Create the GitHub repository (empty) and push a staged mirror to it, then prove every ref landed.

.DESCRIPTION
  - Pushes with an EXPLICIT refspec (heads and tags). Never --mirror: a server's hidden refs
    (refs/pull/*) are refused by GitHub, and --mirror would also DELETE anything on GitHub the
    stage lacks.
  - Never force-pushes. If the GitHub repo already exists it must be empty, or every one of its
    branches must be an ancestor of (or equal to) the staged branch of the same name. Otherwise it
    refuses: pushing on top of unrelated history welds a fake ancestry in permanently.
  - Verifies by SHA with Compare-PortRefs.ps1 and exits 1 if any ref differs.

  Uses the gh CLI for the API and your normal git credential helper for the push
  (run `gh auth setup-git` once if git cannot authenticate to github.com).
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][string]$Name,
    [string]$Owner,
    [string]$Repo,
    [ValidateSet('private', 'internal', 'public')][string]$Visibility,
    [string]$Description,
    [string]$StagingRoot,
    [string]$ConfigPath,
    # Allow pushing into an existing NON-empty repo whose history is compatible (fast-forward only).
    [switch]$AllowExisting,
    # The staged branches already contain .github/workflows; pushing them WILL run those
    # workflows (a deploy job included). Pass only after reading them.
    [switch]$AllowWorkflowRuns
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PortCommon.ps1')

$config = Get-PortConfig $ConfigPath
$stage = Join-Path (Get-PortStagingRoot $config $StagingRoot) $Name
$mirror = Join-Path $stage 'mirror.git'
$manifestPath = Join-Path $stage 'manifest.json'
if (-not (Test-Path -LiteralPath $mirror)) { throw "No staged mirror at $mirror. Run Get-PortSource.ps1 first." }
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json

$readinessPath = Join-Path $stage 'readiness.json'
if (-not (Test-Path -LiteralPath $readinessPath)) { throw "No readiness report. Run Test-PortReadiness.ps1 -Name $Name first." }
$readiness = Get-Content -LiteralPath $readinessPath -Raw | ConvertFrom-Json
if (-not $readiness.ready) { throw "Readiness has $(@($readiness.blockers).Count) blocker(s). Fix them and re-run Test-PortReadiness.ps1 before publishing." }
$live = @()
if ($readiness.PSObject.Properties.Name -contains 'branchesWithGithubWorkflows') { $live = @($readiness.branchesWithGithubWorkflows) }
if ($live.Count -gt 0 -and -not $AllowWorkflowRuns) {
    throw "Branch(es) $($live -join ', ') contain .github/workflows. The push will RUN them on GitHub (deploy jobs included). Read them, then re-run with -AllowWorkflowRuns - or remove/disable them in the source first."
}

# The stage must still hold exactly what Get-PortSource recorded. Anything else (a stray fetch,
# a hand edit, a second tool) would be pushed and then "verified" against itself.
$nowRefs = @(Invoke-PortGit @('-C', $mirror, 'for-each-ref', '--format=%(refname:short) %(objectname)', 'refs/heads', 'refs/tags') | Sort-Object)
$wasRefs = @(@($manifest.heads) + @($manifest.tags) | Where-Object { $_ } | Sort-Object)
$drift = @(Compare-Object $wasRefs $nowRefs)
$extra = @(Invoke-PortGit @('-C', $mirror, 'for-each-ref', '--format=%(refname)') | Where-Object { $_ -and $_ -notlike 'refs/heads/*' -and $_ -notlike 'refs/tags/*' })
if ($drift.Count -gt 0 -or $extra.Count -gt 0) {
    $d = @($drift | ForEach-Object { "$($_.SideIndicator) $($_.InputObject)" }) + @($extra | ForEach-Object { "extra $_" })
    throw "The staged mirror no longer matches manifest.json (=> added, <= missing):`n  $($d -join "`n  ")`nRe-run Get-PortSource.ps1 -Force to rebuild the stage."
}

if (-not $Owner) { $Owner = Get-PortConfigValue $config 'owner' $null }
if (-not $Owner) { throw 'No -Owner and no "owner" in the config file.' }
if (-not $Repo) { $Repo = $Name }
if (-not $Visibility) { $Visibility = Get-PortConfigValue $config 'visibility' 'private' }
$full = "$Owner/$Repo"
$url = "https://github.com/$full.git"

# ---- 1. Who am I, and can I see the owner -------------------------------------------------------
$login = (& gh api user --jq .login 2>&1)
if ($LASTEXITCODE -ne 0) { throw "gh is not signed in: $login. Run gh auth login." }
Write-PortStep "Signed in to GitHub as $login; target $full ($Visibility)"

# ---- 2. Does the repo exist? -----------------------------------------------------------------------
$exists = $false
$null = & gh api "repos/$full" --jq .full_name 2>$null
if ($LASTEXITCODE -eq 0) { $exists = $true }
$global:LASTEXITCODE = 0

if ($exists) {
    $remoteRefs = @(Invoke-PortGit @('ls-remote', '--heads', $url))
    if ($remoteRefs.Count -eq 0 -or -not ($remoteRefs -join '')) {
        Write-PortStep "$full exists and is empty. Using it."
    }
    else {
        if (-not $AllowExisting) {
            throw "$full already exists and has $($remoteRefs.Count) branch(es). Check it shares history with the source (see SKILL.md, 'An existing repo'), then re-run with -AllowExisting, or delete it and re-run."
        }
        Write-PortStep "$full exists with history. Checking every GitHub branch is an ancestor of the staged branch."
        # --no-tags: without it git auto-follows the OTHER repo's tags into the stage, and the
        # next push would publish them. Found by the dogfood run, 2026-09-19.
        Invoke-PortGit @('-C', $mirror, 'fetch', '-q', '--no-tags', $url, '+refs/heads/*:refs/port-check/*') | Out-Null
        try {
            foreach ($line in $remoteRefs) {
                $sha, $ref = $line -split "`t", 2
                $b = $ref.Substring(11)
                $local = Invoke-PortGit -AllowFailure @('-C', $mirror, 'rev-parse', '--verify', '-q', "refs/heads/$b")
                if ($local.ExitCode -ne 0) { continue }   # branch only on GitHub: left alone
                $anc = Invoke-PortGit -AllowFailure @('-C', $mirror, 'merge-base', '--is-ancestor', $sha, ($local.Output -join ''))
                if ($anc.ExitCode -ne 0) {
                    throw "GitHub branch '$b' ($($sha.Substring(0,12))) is NOT an ancestor of the staged '$b'. The histories are unrelated or diverged. Refusing: resolve this by hand."
                }
            }
        }
        finally {
            foreach ($r in @(Invoke-PortGit @('-C', $mirror, 'for-each-ref', '--format=%(refname)', 'refs/port-check'))) {
                if ($r) { Invoke-PortGit @('-C', $mirror, 'update-ref', '-d', $r) | Out-Null }
            }
        }
        Write-PortOk 'Every GitHub branch is an ancestor. The push is a fast-forward.'
    }
}
else {
    if ($PSCmdlet.ShouldProcess($full, "Create $Visibility GitHub repository")) {
        $createArgs = @('repo', 'create', $full, "--$Visibility", '--disable-wiki')
        if ($Description) { $createArgs += @('--description', $Description) }
        $out = & gh @createArgs 2>&1
        if ($LASTEXITCODE -ne 0) { throw "gh repo create failed: $out" }
        Write-PortOk "Created $full"
    }
    else { Write-Host "WhatIf: would create $full"; return }
}

# ---- 3. Push -------------------------------------------------------------------------------------------
if ($PSCmdlet.ShouldProcess($full, 'Push refs/heads/* and refs/tags/*')) {
    Write-PortStep "Pushing branches and tags to $full"
    # --no-verify is NOT used: no hooks exist in a fresh bare mirror anyway.
    Invoke-PortGit @('-C', $mirror, 'push', '--porcelain', $url, 'refs/heads/*:refs/heads/*', 'refs/tags/*:refs/tags/*') | Out-Null
}
else { Write-Host "WhatIf: would push to $url"; return }

# ---- 4. Default branch ---------------------------------------------------------------------------------
$def = $manifest.defaultBranch
$cur = (& gh api "repos/$full" --jq .default_branch 2>$null)
if ($cur -ne $def) {
    & gh api -X PATCH "repos/$full" -f "default_branch=$def" --silent 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-PortWarn "Could not set the default branch to $def. Set it by hand." }
}

# ---- 5. Prove it by SHA ---------------------------------------------------------------------------------
Write-PortStep 'Verifying every branch and tag by SHA'
$mode = if ($exists) { 'LeftInRight' } else { 'Equal' }
& (Join-Path $PSScriptRoot 'Compare-PortRefs.ps1') -Left $mirror -Right $url -Mode $mode -LeftLabel 'staged' -RightLabel 'github'
$verified = ($LASTEXITCODE -eq 0)

$manifest | Add-Member -NotePropertyName github -NotePropertyValue ([pscustomobject]@{
        repo = $full; url = $url; pushedAt = (Get-Date).ToString('o'); pushedBy = $login; verified = $verified; defaultBranch = $def
    }) -Force
$manifest.status = if ($verified) { 'published' } else { 'publish-unverified' }
ConvertTo-PortJsonFile $manifest $manifestPath

if (-not $verified) { Write-PortFail "Push finished but refs do not match. Do NOT continue to CI or cutover."; exit 1 }
Write-PortOk "Published $full - https://github.com/$full"
exit 0
