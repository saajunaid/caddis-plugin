# Shared helpers for the port-to-github scripts. Dot-source this file.
# ASCII only: these scripts may be read by Windows PowerShell 5.1.

Set-StrictMode -Version 2.0

function Write-PortStep([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-PortWarn([string]$Message) {
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-PortFail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
}

function Write-PortOk([string]$Message) {
    Write-Host "[OK] $Message" -ForegroundColor Green
}

# Run git and fail loud on a non-zero exit. Returns stdout lines.
# safe.directory=* lets us READ a repository another account owns (a UNC share,
# a service-owned prod checkout). -c is forwarded to git's subprocesses through
# GIT_CONFIG_PARAMETERS, so upload-pack sees it too.
function Invoke-PortGit {
    param(
        [Parameter(Mandatory)][string[]]$Arguments,
        [switch]$AllowFailure
    )
    $all = @('-c', 'safe.directory=*') + $Arguments
    $out = & git @all 2>&1
    $code = $LASTEXITCODE
    $text = @($out | ForEach-Object { "$_" })
    if ($code -ne 0 -and -not $AllowFailure) {
        throw "git $($Arguments -join ' ') failed with exit $code`n$($text -join "`n")"
    }
    if ($AllowFailure) {
        return [pscustomobject]@{ ExitCode = $code; Output = $text }
    }
    return $text
}

# Read defaults from a project config file. Order: -ConfigPath, $env:PORT_TO_GITHUB_CONFIG,
# .caddis/port-to-github.json in the current git repository. Missing file = empty config.
function Get-PortConfig([string]$ConfigPath) {
    $candidates = @()
    if ($ConfigPath) { $candidates += $ConfigPath }
    if ($env:PORT_TO_GITHUB_CONFIG) { $candidates += $env:PORT_TO_GITHUB_CONFIG }
    $top = & git rev-parse --show-toplevel 2>$null
    if ($LASTEXITCODE -eq 0 -and $top) {
        $candidates += (Join-Path $top '.caddis/port-to-github.json')
    }
    foreach ($c in $candidates) {
        if ($c -and (Test-Path -LiteralPath $c)) {
            $cfg = Get-Content -LiteralPath $c -Raw | ConvertFrom-Json
            $cfg | Add-Member -NotePropertyName _path -NotePropertyValue (Resolve-Path -LiteralPath $c).Path -Force
            return $cfg
        }
    }
    return [pscustomobject]@{ _path = $null }
}

function Get-PortConfigValue($Config, [string]$Name, $Default) {
    if ($null -ne $Config -and $Config.PSObject.Properties.Name -contains $Name -and $null -ne $Config.$Name -and "$($Config.$Name)" -ne '') {
        return $Config.$Name
    }
    return $Default
}

function Get-PortStagingRoot($Config, [string]$Override) {
    if ($Override) { $root = $Override }
    else { $root = Get-PortConfigValue $Config 'stagingRoot' (Join-Path ([IO.Path]::GetTempPath()) 'port-to-github') }
    $root = [Environment]::ExpandEnvironmentVariables($root)
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    return (Resolve-Path -LiteralPath $root).Path
}

# Remove "user:secret@" from a URL. Returns @{ Url; HadCredential }.
function Remove-UrlCredential([string]$Url) {
    if ($Url -match '^(?<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?<userinfo>[^@/]+)@(?<rest>.*)$') {
        return [pscustomobject]@{ Url = "$($Matches.scheme)$($Matches.rest)"; HadCredential = ($Matches.userinfo -match ':') }
    }
    return [pscustomobject]@{ Url = $Url; HadCredential = $false }
}

# Directories that are never source, skipped when importing a plain folder (no .git).
# Only unambiguous ones: 'dist', 'build', 'bin' can hold real source in some projects,
# so they are imported and REPORTED instead (see $PortSuspectDirs).
$script:PortJunkDirs = @(
    'node_modules', '.venv', 'venv', '__pycache__', '.pytest_cache', '.mypy_cache',
    '.ruff_cache', '.tox', '.next', '.nuxt', '.parcel-cache', '.turbo', 'htmlcov', '.git'
)
$script:PortSuspectDirs = @('dist', 'build', 'bin', 'obj', 'out', 'coverage', 'logs', 'data')

# File-name patterns that usually hold secrets.
$script:PortSecretNamePatterns = @(
    '^\.env$', '^\.env\..+', '\.pem$', '\.key$', '\.pfx$', '\.p12$', '^id_rsa', '^id_ed25519',
    '^credentials(\..+)?$', '\.kdbx$', '^\.netrc$', '^\.git-credentials$', '^\.npmrc$', '^\.pypirc$'
)
# .env.example / .env.sample / .env.template are documentation, not secrets.
$script:PortSecretNameAllow = @('\.example$', '\.sample$', '\.template$', '\.dist$')

# Content patterns that usually are a real credential.
$script:PortSecretContentPatterns = @(
    'gh[pousr]_[A-Za-z0-9]{36,}',
    'github_pat_[A-Za-z0-9_]{40,}',
    'AKIA[0-9A-Z]{16}',
    '-----BEGIN [A-Z ]*PRIVATE KEY-----',
    'xox[baprs]-[A-Za-z0-9-]{10,}',
    '(?i)(password|passwd|pwd|secret|api[_-]?key|token)\s*[:=]\s*[''"][^''"\s]{8,}[''"]',
    '(?i)(password|pwd)=[^;\s]{6,};'
)

function Test-PortSecretName([string]$FileName) {
    foreach ($a in $script:PortSecretNameAllow) { if ($FileName -match $a) { return $false } }
    foreach ($p in $script:PortSecretNamePatterns) { if ($FileName -match $p) { return $true } }
    return $false
}

function Test-PortSecretContent([string]$Text) {
    foreach ($p in $script:PortSecretContentPatterns) {
        if ($Text -match $p) { return $p }
    }
    return $null
}

function ConvertTo-PortJsonFile($Object, [string]$Path) {
    $Object | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Path -Encoding UTF8
}
