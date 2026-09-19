<#
.SYNOPSIS
  Repoint an existing checkout (a deploy target, a dev box) from its old origin to GitHub,
  prove it still agrees with GitHub, and roll back by itself if it does not.

.DESCRIPTION
  Works on a local path, or on a remote box over WinRM (-ComputerName).

  -Mode Inspect   print origin, branch, HEAD, dirty count. Changes nothing.
  -Mode Switch    record the old URL in a local state file, keep it as a second remote
                  (-KeepOldAs), set origin to -NewUrl, fetch, and require HEAD to be contained
                  in some origin/* branch. On ANY failure the old URL is restored at once.
  -Mode Rollback  put the old URL back from the state file and remove the remote Switch added.

  A deploy host usually holds NO GitHub credential of its own: CI supplies one per run.
  -VerifyWithGhToken passes your current gh token to that ONE fetch as an HTTP header in the
  process environment. It is never written to disk or to git config, and it is gone when the
  command ends. Without it, a private repo fetch on such a host fails and the switch rolls back.

  If the old URL embedded a credential (user:secret@host), the state file stores it WITHOUT
  the credential and says so. Rotate that credential.
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][string]$Path,
    [string]$ComputerName,
    [pscredential]$Credential,
    [ValidateSet('Inspect', 'Switch', 'Rollback')][string]$Mode = 'Inspect',
    [string]$NewUrl,
    [string]$KeepOldAs,
    [string]$StateFile,
    [string]$StagingRoot,
    [string]$ConfigPath,
    [switch]$VerifyWithGhToken
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PortCommon.ps1')
$config = Get-PortConfig $ConfigPath
if (-not $KeepOldAs) { $KeepOldAs = Get-PortConfigValue $config 'oldRemoteName' 'old-origin' }

$where = if ($ComputerName) { $ComputerName } else { $env:COMPUTERNAME }
if (-not $StateFile) {
    $dir = Join-Path (Get-PortStagingRoot $config $StagingRoot) 'cutover'
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $safe = ($Path -replace '[:\\/ ]+', '_').Trim('_')
    $StateFile = Join-Path $dir "$where-$safe.json"
}

# One script block, run locally or remotely. Windows PowerShell 5.1 compatible. Native stderr
# must not become a terminating error, so git runs under 'Continue' and is judged by exit code.
$block = {
    param($P, $M, $New, $KeepAs, $OldUrl, $RestoreUrl, $AddedRemote, $Token)
    $ErrorActionPreference = 'Continue'
    function G { $o = & git -c safe.directory=* -C $P @args 2>&1; $c = $LASTEXITCODE; return @{ code = $c; out = @($o | ForEach-Object { "$_" }) } }
    $r = @{ ok = $false; origin = $null; branch = $null; head = $null; dirty = 0; remotes = @(); message = $null; addedRemote = $false; rolledBack = $false }
    if (-not (Test-Path -LiteralPath $P)) { $r.message = "Path not found: $P"; return $r }
    $o = G remote get-url origin
    if ($o.code -ne 0) { $r.message = "No origin remote in $P"; return $r }
    $r.origin = ($o.out -join '')
    $b = G symbolic-ref --short HEAD; if ($b.code -eq 0) { $r.branch = ($b.out -join '') }
    $hd = G rev-parse --verify -q HEAD
    if ($hd.code -ne 0 -or -not ($hd.out -join '')) { $r.message = "$P has no commit at HEAD (empty or unborn repository)"; return $r }
    $r.head = ($hd.out -join '')
    $r.dirty = @((G status --porcelain).out | Where-Object { $_ }).Count
    $r.remotes = @((G remote).out)

    if ($M -eq 'Inspect') { $r.ok = $true; return $r }

    if ($M -eq 'Rollback') {
        $s = G remote set-url origin $OldUrl
        if ($s.code -ne 0) { $r.message = "set-url failed: $($s.out -join ' ')"; return $r }
        if ($AddedRemote -and ($r.remotes -contains $KeepAs)) { G remote remove $KeepAs | Out-Null }
        $r.origin = $OldUrl; $r.ok = $true; $r.message = 'rolled back'; return $r
    }

    # Switch
    if ($r.origin -eq $New) { $r.ok = $true; $r.message = 'origin already points at the new URL'; return $r }
    if (-not ($r.remotes -contains $KeepAs)) {
        $a = G remote add $KeepAs $OldUrl
        if ($a.code -ne 0) { $r.message = "could not add remote ${KeepAs}: $($a.out -join ' ')"; return $r }
        $r.addedRemote = $true
    }
    $s = G remote set-url origin $New
    if ($s.code -ne 0) { $r.message = "set-url failed: $($s.out -join ' ')"; return $r }

    # From here origin points at the new URL. ANY failure, including an exception, must restore it.
    $fail = $null
    $env:GIT_TERMINAL_PROMPT = '0'
    try {
        if ($Token) {
            $env:GIT_CONFIG_COUNT = '1'
            $env:GIT_CONFIG_KEY_0 = 'http.https://github.com/.extraheader'
            $env:GIT_CONFIG_VALUE_0 = 'AUTHORIZATION: basic ' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("x-access-token:$Token"))
        }
        $f = G fetch -q origin
        $contained = @()
        if ($f.code -eq 0) { $contained = @((G for-each-ref --contains HEAD --format='%(refname)' refs/remotes/origin).out | Where-Object { $_ }) }
        if ($f.code -ne 0) { $fail = "fetch from the new origin failed (exit $($f.code)): $(($f.out | Select-Object -First 3) -join ' ')" }
        elseif ($contained.Count -eq 0) { $fail = "HEAD $($r.head.Substring(0,12)) is not contained in any origin/* branch: this checkout has commits GitHub does not" }
    }
    catch { $fail = "verification threw: $($_.Exception.Message)" }
    finally {
        Remove-Item Env:GIT_CONFIG_COUNT, Env:GIT_CONFIG_KEY_0, Env:GIT_CONFIG_VALUE_0 -ErrorAction SilentlyContinue
    }
    if ($fail) {
        G remote set-url origin $RestoreUrl | Out-Null
        if ($r.addedRemote) { G remote remove $KeepAs | Out-Null; $r.addedRemote = $false }
        $r.rolledBack = $true; $r.message = $fail; return $r
    }
    $r.origin = $New; $r.ok = $true; $r.message = "HEAD is contained in: $($contained -join ', ')"; return $r
}

function Invoke-Block($ArgList) {
    if ($ComputerName) {
        $sa = @{ ComputerName = $ComputerName; ScriptBlock = $block; ArgumentList = $ArgList }
        if ($Credential) { $sa.Credential = $Credential }
        return Invoke-Command @sa
    }
    return & $block @ArgList
}

# Always inspect first.
$now = Invoke-Block @($Path, 'Inspect', $null, $KeepOldAs, $null, $null, $false, $null)
if (-not $now.ok) { throw "[$where] $($now.message)" }
$clean = Remove-UrlCredential $now.origin
Write-Host ("[{0}] {1}`n    origin : {2}`n    branch : {3}   HEAD {4}   uncommitted: {5}   remotes: {6}" -f $where, $Path, $clean.Url, $now.branch, $now.head.Substring(0, 12), $now.dirty, ($now.remotes -join ', '))
if ($clean.HadCredential) { Write-PortWarn 'The current origin URL EMBEDS A CREDENTIAL. It is shown without it. Rotate that credential after the cutover.' }
if ($Mode -eq 'Inspect') { exit 0 }

if ($Mode -eq 'Switch') {
    if (-not $NewUrl) { throw '-NewUrl is required for -Mode Switch.' }
    if ($now.dirty -gt 0) { Write-PortWarn "The checkout has $($now.dirty) uncommitted change(s). A deploy that resets the tree will discard them. Look before you continue." }
    if (-not $PSCmdlet.ShouldProcess("$where $Path", "Set origin to $NewUrl")) { exit 0 }
    $token = $null
    if ($VerifyWithGhToken) {
        $token = (& gh auth token 2>$null)
        if ($LASTEXITCODE -ne 0 -or -not $token) { throw 'gh auth token returned nothing. Sign in with gh auth login, or drop -VerifyWithGhToken.' }
    }
    # Record the rollback BEFORE changing anything.
    $state = [ordered]@{
        computer = $where; path = $Path; oldUrl = $clean.Url; oldUrlHadCredential = $clean.HadCredential
        newUrl = $NewUrl; keepOldAs = $KeepOldAs; addedRemote = $false; switchedAt = (Get-Date).ToString('o'); headAtSwitch = $now.head
    }
    ConvertTo-PortJsonFile $state $StateFile
    # The second remote gets the credential-free URL. On failure the ORIGINAL value is restored.
    try {
        $res = Invoke-Block @($Path, 'Switch', $NewUrl, $KeepOldAs, $clean.Url, $now.origin, $false, $token)
    }
    catch {
        # The call itself failed (e.g. the WinRM transport dropped). The remote side may or may
        # not have changed origin. Put the ORIGINAL value back; leave the kept remote for a human.
        $token = $null
        Write-PortFail "[$where] Switch call failed: $($_.Exception.Message). Restoring the original origin."
        try { $null = Invoke-Block @($Path, 'Rollback', $null, $KeepOldAs, $now.origin, $null, $false, $null) } catch { Write-PortFail "[$where] Restore ALSO failed. Set origin back by hand to the URL in $StateFile." }
        exit 1
    }
    $token = $null
    if (-not $res.ok) {
        if ($res.rolledBack) { Write-PortFail "[$where] Switch failed and was ROLLED BACK: $($res.message)" }
        else { Write-PortFail "[$where] Switch failed: $($res.message)" }
        Remove-Item -LiteralPath $StateFile -ErrorAction SilentlyContinue
        exit 1
    }
    $state.addedRemote = [bool]$res.addedRemote
    ConvertTo-PortJsonFile $state $StateFile
    Write-PortOk "[$where] origin -> $NewUrl. $($res.message)"
    Write-Host "    old origin kept as remote '$KeepOldAs'. Rollback: $($MyInvocation.MyCommand.Name) -Path '$Path'$(if ($ComputerName) { " -ComputerName $ComputerName" }) -Mode Rollback"
    Write-Host "    state: $StateFile"
    exit 0
}

if ($Mode -eq 'Rollback') {
    if (-not (Test-Path -LiteralPath $StateFile)) { throw "No state file at $StateFile. Pass -StateFile." }
    $state = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
    if (-not $PSCmdlet.ShouldProcess("$where $Path", "Set origin back to $($state.oldUrl)")) { exit 0 }
    $res = Invoke-Block @($Path, 'Rollback', $null, $state.keepOldAs, $state.oldUrl, $null, [bool]$state.addedRemote, $null)
    if (-not $res.ok) { Write-PortFail "[$where] Rollback failed: $($res.message)"; exit 1 }
    if ($state.oldUrlHadCredential) { Write-PortWarn 'The old URL had an embedded credential. It was restored WITHOUT it; the credential helper must supply one.' }
    Write-PortOk "[$where] origin restored to $($state.oldUrl)"
    exit 0
}
