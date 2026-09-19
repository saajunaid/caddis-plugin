<#
.SYNOPSIS
  Record the runtimes an app needs but the repository must not carry, so the environment can
  be rebuilt from the repository alone.

.DESCRIPTION
  Scans the app's SOURCE FOLDER (not the git history), including ignored folders such as tools/,
  for runtime distributions: MariaDB/MySQL, PHP, Node, Python, Java, Apache, nginx, Redis,
  PostgreSQL. Versions come from file metadata. NOTHING it finds is executed.

  Writes to -OutDir (put it in the repository, e.g. environment/):
    runtimes.json      name, version, where it lived, binary SHA-256, data folders, config files
    README.md          the same for people, plus every decision still open
    provision.ps1      downloads and unpacks each runtime with a known public source; fails
                       loudly for any runtime it cannot provision, so a gap is never silent
    config-templates/  configuration found INSIDE runtime folders (my.ini, php.ini, config/,
                       metadata/). The teammate rule keeps configuration in the repo even when
                       the runtime around it is excluded. A file that looks like it holds a
                       credential is NOT copied; it is listed for a hand-made template.

  Folders beside a runtime that match nothing (a deployed web tree, a vendored library) are
  listed as UNCLASSIFIED: each needs a human decision.

  Works on a local or UNC path, or on a remote box with -ComputerName (Windows PowerShell 5.1
  on the far side is fine).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Path,
    [string]$ComputerName,
    [pscredential]$Credential,
    [Parameter(Mandatory)][string]$OutDir,
    [int]$MaxDepth = 5,
    [int]$ConfigMaxKB = 256
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PortCommon.ps1')

# Runs locally or remotely. 5.1-compatible, read-only, never executes a found binary.
$scan = {
    param($Root, $Depth, $CfgMaxKB)
    $ErrorActionPreference = 'Continue'
    $res = @{ ok = $false; error = $null; runtimes = @(); unclassified = @() }
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { $res.error = "Folder not found: $Root"; return $res }
    $Root = (Resolve-Path -LiteralPath $Root).ProviderPath.TrimEnd('\')
    function Rel($p) { $p.Substring($Root.Length).TrimStart('\').Replace('\', '/') }
    # A plain loop: Measure-Object over an EMPTY folder has no .Sum under strict mode, and an
    # empty data/ folder (a runtime never started) is normal here.
    function DirMB($p) { $t = [int64]0; foreach ($f in @(Get-ChildItem -LiteralPath $p -Recurse -File -Force -ErrorAction SilentlyContinue)) { $t += $f.Length }; [math]::Round($t / 1MB, 1) }

    $binRx = '(?i)^(mariadbd|mysqld|php|node|python|java|httpd|nginx|redis-server|postgres)\.exe$'
    $skipRx = '(?i)\\(node_modules|\.venv|venv|\.git|site-packages|vendor)\\'
    $bins = @(Get-ChildItem -LiteralPath $Root -Recurse -Depth $Depth -File -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match $binRx -and $_.FullName -notmatch $skipRx })
    $roots = @{}
    $priority = @('mariadbd', 'mysqld', 'php', 'node', 'python', 'java', 'httpd', 'nginx', 'redis-server', 'postgres')
    foreach ($b in $bins) {
        $dir = $b.Directory
        $rootDir = if ($dir.Name -ieq 'bin' -and $dir.Parent) { $dir.Parent.FullName } else { $dir.FullName }
        if ($rootDir -ieq $Root) { continue }
        $base = [IO.Path]::GetFileNameWithoutExtension($b.Name).ToLower()
        if (-not $roots.ContainsKey($rootDir) -or ($priority.IndexOf($base) -lt $priority.IndexOf($roots[$rootDir].base))) {
            $roots[$rootDir] = @{ file = $b; base = $base }
        }
    }
    # A runtime nested inside another runtime (php inside apache/) belongs to the outer one.
    $rootList = @($roots.Keys | Sort-Object Length)
    $kept = @()
    foreach ($r in $rootList) { if (-not ($kept | Where-Object { $r.StartsWith($_ + '\', [StringComparison]::OrdinalIgnoreCase) })) { $kept += $r } }

    $cfgExt = '(?i)\.(ini|cnf|conf|php|ya?ml|json|xml|properties|toml)$'
    function Get-Configs($dir, $dataDirs) {
        $out = @()
        $cands = @(Get-ChildItem -LiteralPath $dir -File -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '(?i)\.(ini|cnf|conf)$' })
        foreach ($sub in @(Get-ChildItem -LiteralPath $dir -Directory -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '(?i)^(conf|config|etc|metadata|cert)$' })) {
            $cands += @(Get-ChildItem -LiteralPath $sub.FullName -Recurse -Depth 2 -File -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -match $cfgExt -or $sub.Name -ieq 'cert' })
        }
        foreach ($f in $cands) {
            if ($dataDirs | Where-Object { $f.FullName.StartsWith($_ + '\', [StringComparison]::OrdinalIgnoreCase) }) { continue }
            if ($f.Name -match '(?i)\.(dist|example|sample|template)$') { continue }
            $o = @{ rel = (Rel $f.FullName); bytes = $f.Length; b64 = $null; tooBig = $false }
            if ($f.Length -le ($CfgMaxKB * 1KB)) { $o.b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($f.FullName)) } else { $o.tooBig = $true }
            $out += $o
        }
        return , $out
    }

    foreach ($rd in $kept) {
        $e = $roots[$rd]; $vi = $e.file.VersionInfo
        $ver = "$($vi.ProductVersion)".Trim(); if (-not $ver) { $ver = "$($vi.FileVersion)".Trim() }
        $kind = switch -Regex ($e.base) { '^(mariadbd|mysqld)$' { if ("$($vi.ProductName)$($vi.FileDescription)" -match '(?i)mariadb' -or (Test-Path (Join-Path $rd 'bin\mariadbd.exe'))) { 'mariadb' } else { 'mysql' } } '^php$' { 'php' } '^node$' { 'node' } '^python$' { 'python' } '^java$' { 'java' } '^httpd$' { 'apache' } '^nginx$' { 'nginx' } '^redis-server$' { 'redis' } '^postgres$' { 'postgresql' } default { $e.base } }
        $sha = (Get-FileHash -LiteralPath $e.file.FullName -Algorithm SHA256).Hash.ToLower()
        $dataDirs = @(Get-ChildItem -LiteralPath $rd -Directory -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '(?i)^(data|db|pgdata|var)$' } | ForEach-Object { $_.FullName })
        $ts = $null
        if ($kind -eq 'php') { $ts = [bool](Get-ChildItem -LiteralPath $rd -Filter 'php*ts.dll' -File -ErrorAction SilentlyContinue) }
        $res.runtimes += @{
            kind = $kind; root = (Rel $rd); binary = (Rel $e.file.FullName); version = $ver
            product = "$($vi.ProductName)"; binarySha256 = $sha; sizeMB = (DirMB $rd); threadSafe = $ts
            dataDirs = @($dataDirs | ForEach-Object { @{ rel = (Rel $_); sizeMB = (DirMB $_) } })
            configs = (Get-Configs $rd $dataDirs)
        }
    }

    # Siblings of runtime roots that match nothing: a human must decide what they are.
    $containers = @($kept | ForEach-Object { Split-Path $_ -Parent } | Sort-Object -Unique | Where-Object { $_ -and ($_ -ine $Root) })
    foreach ($c in $containers) {
        foreach ($d in @(Get-ChildItem -LiteralPath $c -Directory -Force -ErrorAction SilentlyContinue)) {
            if ($kept -contains $d.FullName) { continue }
            $hints = @()
            $cj = Join-Path $d.FullName 'composer.json'
            if (Test-Path $cj) { try { $j = Get-Content $cj -Raw | ConvertFrom-Json; $hints += "composer package $($j.name)$(if ($j.version) { ' ' + $j.version })" } catch { $hints += 'composer.json' } }
            if (Test-Path (Join-Path $d.FullName 'package.json')) { $hints += 'package.json' }
            foreach ($s in 'conf', 'config', 'cert', 'data', 'log') { if (Test-Path (Join-Path $d.FullName $s)) { $hints += "$s/" } }
            $res.unclassified += @{ rel = (Rel $d.FullName); sizeMB = (DirMB $d.FullName); hints = $hints; configs = (Get-Configs $d.FullName @()) }
        }
    }
    $res.ok = $true
    return $res
}

if ($ComputerName) {
    $ia = @{ ComputerName = $ComputerName; ScriptBlock = $scan; ArgumentList = @($Path, $MaxDepth, $ConfigMaxKB) }
    if ($Credential) { $ia.Credential = $Credential }
    Write-PortStep "Scanning $Path on $ComputerName for runtimes (read-only)"
    $res = Invoke-Command @ia
}
else {
    Write-PortStep "Scanning $Path for runtimes (read-only)"
    $res = & $scan $Path $MaxDepth $ConfigMaxKB
}
if (-not $res.ok) { throw $res.error }

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$tplRoot = Join-Path $OutDir 'config-templates'
$withheld = @(); $copied = @(); $tooBig = @()
function Save-Configs($list) {
    foreach ($c in @($list)) {
        if ($c.tooBig) { $script:tooBig += $c.rel; continue }
        $bytes = [Convert]::FromBase64String($c.b64)
        $text = [Text.Encoding]::UTF8.GetString($bytes)
        $leaf = Split-Path $c.rel -Leaf
        # Heuristics, so they err toward WITHHOLDING. Found by the dogfood: SimpleSAMLphp's
        # exampleauth writes a user as 'name:password' => array(...), which no key=value rule sees.
        $secret = (Test-PortSecretName $leaf) -or ($c.rel -match '(?i)(^|/)cert/') -or (Test-PortSecretContent $text) -or
            ($text -match '(?i)(password|passwd|pass|pwd|secret|salt|token|api_?key|private_?key|auth\.adminpassword|credentials?)\s*[''"]?\s*(=>|=|:)\s*[''"][^''"\s]{4,}[''"]') -or
            ($text -match '[''"][^''"\s:/]{2,}:[^''"\s]{4,}[''"]\s*=>') -or
            ($text -match '(?i)[a-z][a-z0-9+.-]*://[^/\s:@''"]+:[^/\s@''"]+@') -or
            # Unquoted INI/properties form, the one my.ini and php.ini actually use: password=Secret123
            ($text -match '(?im)^\s*[\w.-]*(password|passwd|pwd|pass|_pw|secret|api[_-]?key|token|credential)s?\s*=\s*[^\s;#]+')
        if ($secret) { $script:withheld += $c.rel; continue }
        $dst = Join-Path $tplRoot ($c.rel -replace '/', '\')
        New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent) | Out-Null
        [IO.File]::WriteAllBytes($dst, $bytes)
        $script:copied += $c.rel
    }
}
foreach ($r in $res.runtimes) { Save-Configs $r.configs }
foreach ($u in $res.unclassified) { Save-Configs $u.configs }

function Get-Source($r) {
    $v = ($r.version -split '\.')
    $v3 = ($v | Select-Object -First 3) -join '.'
    switch ($r.kind) {
        'mariadb' { return @("https://archive.mariadb.org/mariadb-$v3/winx64-packages/mariadb-$v3-winx64.zip") }
        'php' {
            $mm = [version](($v | Select-Object -First 2) -join '.')
            $vs = if ($mm -ge [version]'8.4') { 'vs17' } elseif ($mm -ge [version]'8.0') { 'vs16' } else { 'vc15' }
            $ts = if ($r.threadSafe) { 'Win32' } else { 'nts-Win32' }
            $f = "php-$v3-$ts-$vs-x64.zip"
            return @("https://windows.php.net/downloads/releases/$f", "https://windows.php.net/downloads/releases/archives/$f")
        }
        'node' { return @("https://nodejs.org/dist/v$v3/node-v$v3-win-x64.zip") }
        'python' { return @("https://www.python.org/ftp/python/$v3/python-$v3-embed-amd64.zip") }
        default { return @() }
    }
}

$runtimes = @(foreach ($r in $res.runtimes) {
        [ordered]@{
            kind = $r.kind; version = $r.version; product = $r.product; wasAt = $r.root; binary = $r.binary
            binarySha256 = $r.binarySha256; installedSizeMB = $r.sizeMB; threadSafe = $r.threadSafe
            sources = @(Get-Source $r); archiveSha256 = $null
            dataDirs = @($r.dataDirs | ForEach-Object { [ordered]@{ path = $_.rel; sizeMB = $_.sizeMB } })
        }
    })
$uncl = @(foreach ($u in $res.unclassified) { [ordered]@{ path = $u.rel; sizeMB = $u.sizeMB; hints = @($u.hints); decision = 'OPEN' } })
$doc = [ordered]@{
    generatedAt = (Get-Date).ToString('o'); scannedPath = $Path; computerName = $ComputerName
    runtimes = $runtimes; unclassified = $uncl
    configTemplates = @($copied); configWithheld = @($withheld); configTooBig = @($tooBig)
}
ConvertTo-PortJsonFile $doc (Join-Path $OutDir 'runtimes.json')

# ---- provision.ps1: downloads what has a known source, and FAILS for the rest ----------------
$prov = New-Object System.Collections.Generic.List[string]
$prov.Add('# Generated by port-to-github New-PortRuntimeManifest.ps1. Rebuilds the local runtimes that the')
$prov.Add('# repository deliberately does not carry. Review the URLs once, then record each archive''s')
$prov.Add('# SHA-256 in runtimes.json (archiveSha256) so later runs verify the download.')
$prov.Add('[CmdletBinding()] param([string]$ToolsRoot = (Join-Path $PSScriptRoot ''..\tools''), [switch]$Force)')
$prov.Add('$ErrorActionPreference = ''Stop''')
$prov.Add('$spec = Get-Content -LiteralPath (Join-Path $PSScriptRoot ''runtimes.json'') -Raw | ConvertFrom-Json')
$prov.Add('$missing = @()')
$prov.Add('New-Item -ItemType Directory -Force -Path $ToolsRoot | Out-Null')
$prov.Add('foreach ($r in $spec.runtimes) {')
$prov.Add('    $dest = Join-Path $ToolsRoot (Split-Path $r.wasAt -Leaf)')
$prov.Add('    if ((Test-Path $dest) -and -not $Force) { Write-Host "[skip] $($r.kind) $($r.version): $dest exists"; continue }')
$prov.Add('    $replace = Test-Path $dest')
$prov.Add('    if (@($r.sources).Count -eq 0) { $missing += "$($r.kind) $($r.version) (no known public source)"; continue }')
$prov.Add('    $zip = Join-Path ([IO.Path]::GetTempPath()) "$($r.kind)-$($r.version).zip"; $got = $false')
$prov.Add('    foreach ($u in $r.sources) { try { Invoke-WebRequest -Uri $u -OutFile $zip -UseBasicParsing; $got = $true; break } catch { Write-Host "[miss] $u" } }')
$prov.Add('    if (-not $got) { $missing += "$($r.kind) $($r.version) (download failed)"; continue }')
$prov.Add('    $h = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()')
$prov.Add('    if ($r.archiveSha256 -and $h -ne $r.archiveSha256) { throw "$($r.kind): archive SHA-256 $h does not match runtimes.json $($r.archiveSha256)" }')
$prov.Add('    if (-not $r.archiveSha256) { Write-Warning "$($r.kind): unverified download, SHA-256 $h - record it in runtimes.json" }')
$prov.Add('    $tmp = Join-Path ([IO.Path]::GetTempPath()) "$($r.kind)-$($r.version)-x"; Expand-Archive -LiteralPath $zip -DestinationPath $tmp -Force')
$prov.Add('    $inner = @(Get-ChildItem $tmp); $src = if ($inner.Count -eq 1 -and $inner[0].PSIsContainer) { $inner[0].FullName } else { $tmp }')
$prov.Add('    if ($replace) { Remove-Item -LiteralPath $dest -Recurse -Force }   # Move-Item -Force onto a folder NESTS; replace it instead')
$prov.Add('    Move-Item -LiteralPath $src -Destination $dest; Write-Host "[ok] $($r.kind) $($r.version) -> $dest"')
$prov.Add('    $bin = Join-Path $ToolsRoot ((Split-Path $r.wasAt -Leaf) + ''/'' + ($r.binary.Substring($r.wasAt.Length).TrimStart(''/'')))')
$prov.Add('    if (-not (Test-Path $bin)) { $missing += "$($r.kind): expected binary $bin not found after unpack" }')
$prov.Add('    elseif ((Get-FileHash $bin -Algorithm SHA256).Hash.ToLower() -ne $r.binarySha256) { Write-Warning "$($r.kind): binary differs from the recorded build (different package variant?)" }')
$prov.Add('}')
$prov.Add('Write-Host ''Copy config-templates\ into place, fill in every withheld secret, and restore data from its backup - see README.md.''')
$prov.Add('if ($missing.Count) { $missing | ForEach-Object { Write-Host "[FAIL] $_" }; exit 1 }')
$prov.Add('exit 0')
[IO.File]::WriteAllLines((Join-Path $OutDir 'provision.ps1'), [string[]]$prov, (New-Object Text.UTF8Encoding($false)))

# ---- README.md ------------------------------------------------------------------------------------
$md = New-Object System.Collections.Generic.List[string]
$md.Add('# Local runtime environment')
$md.Add('')
$md.Add('The runtimes below are needed to run this app locally or in UAT. They are NOT in the repository:')
$md.Add('they are third-party distributions, not application source. `provision.ps1` rebuilds them.')
$md.Add('Generated by the port-to-github skill; edit freely, but keep `runtimes.json` the source of truth.')
$md.Add('')
$md.Add('| Runtime | Version | Was at | Installed MB | Source |')
$md.Add('|---|---|---|---|---|')
foreach ($r in $runtimes) { $md.Add(('| {0} | {1} | `{2}` | {3} | {4} |' -f $r.kind, $r.version, $r.wasAt, $r.installedSizeMB, $(if (@($r.sources).Count) { $r.sources[0] } else { '**none known - install by hand**' }))) }
$data = @($runtimes | ForEach-Object { $k = $_.kind; $_.dataDirs | ForEach-Object { "- ``$($_.path)`` ($k, $($_.sizeMB) MB): runtime STATE, not code. Rebuild from the schema and migrations in this repository, or restore from backup. Never commit it." } })
if ($data.Count) { $md.Add(''); $md.Add('## Data folders (never committed)'); $data | ForEach-Object { $md.Add($_) } }
if ($uncl.Count) {
    $md.Add(''); $md.Add('## OPEN: folders beside the runtimes that nothing identified')
    $md.Add('Decide each: provision it (add it here), rebuild it from repository code, or keep it in the repository.')
    foreach ($u in $uncl) { $md.Add(('- `{0}` ({1} MB){2}' -f $u.path, $u.sizeMB, $(if (@($u.hints).Count) { ' - ' + ($u.hints -join ', ') } else { '' }))) }
}
$md.Add(''); $md.Add('## Configuration')
$md.Add("- Copied to ``config-templates/`` ($($copied.Count) file(s)): configuration that lived inside a runtime folder. It IS part of the app. **Read each one before committing it**: the credential check is a heuristic.")
if ($withheld.Count) { $md.Add("- **Withheld, $($withheld.Count) file(s) that look like they hold a credential.** Make a template by hand with the secret replaced by a placeholder:"); $withheld | ForEach-Object { $md.Add("  - ``$_``") } }
if ($tooBig.Count) { $md.Add("- Too large to copy automatically ($($tooBig.Count)): " + (($tooBig | ForEach-Object { "``$_``" }) -join ', ')) }
[IO.File]::WriteAllLines((Join-Path $OutDir 'README.md'), [string[]]$md, (New-Object Text.UTF8Encoding($false)))

Write-Host ''
Write-Host ("Runtimes: {0}   unclassified folders: {1}   config templates: {2}   withheld (credentials): {3}" -f $runtimes.Count, $uncl.Count, $copied.Count, $withheld.Count)
foreach ($r in $runtimes) { Write-Host ("  {0,-11} {1,-12} {2,-35} {3} MB{4}" -f $r.kind, $r.version, $r.wasAt, $r.installedSizeMB, $(if (@($r.dataDirs).Count) { "   data: " + (($r.dataDirs | ForEach-Object { "$($_.path) $($_.sizeMB) MB" }) -join ', ') } else { '' })) }
foreach ($u in $uncl) { Write-PortWarn ("UNCLASSIFIED {0} ({1} MB) {2}" -f $u.path, $u.sizeMB, ($u.hints -join ', ')) }
Write-Host "    written to $OutDir (runtimes.json, README.md, provision.ps1, config-templates/)"
exit 0
