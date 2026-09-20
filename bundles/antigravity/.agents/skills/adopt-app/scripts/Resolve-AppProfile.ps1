<#
.SYNOPSIS
    Phase 2. Decide what KIND of app this is, per component, and write profile.json.

.DESCRIPTION
    An app is rarely one thing. A folder can honestly be a web API and a batch CLI at the
    same time, and a real repository often holds several components: a service, a static
    front end, a vendored third-party product.

    So this script reports EVERY profile that matches each component folder, not just the
    best one. Silently picking the winner hides a decision a person has to make - and the
    dogfood found a repository carrying an abandoned Java scaffold that a best-match
    detector would have called a Java service.

    Nothing here is a guess you have to accept. The output records the score, the runners
    up and the evidence, and the script exits 2 when no profile matches at all, because
    "no stack" is never the right answer for an app that is running.

.PARAMETER Name
    The name used for the inventory in phase 1.

.PARAMETER ForceProfile
    Force one profile for the root component instead of detecting it. Use it when you
    know better than the rules, and say why in the plan. NOT named -Profile: $Profile is a PowerShell automatic
    variable (the path to the shell profile), and shadowing it inside a script is a trap.

.EXAMPLE
    ./Resolve-AppProfile.ps1 -Name legacy-app
.EXAMPLE
    ./Resolve-AppProfile.ps1 -Name batch-engine -ForceProfile batch-job
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Name,
    [string]$OutDir,
    [string]$ProfilesDir,
    [string]$ForceProfile,
    [int]$MaxComponents = 12
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'AdoptCommon.ps1')

$dir = Resolve-AdoptOutDir -Name $Name -OutDir $OutDir
$inventory = Read-AdoptArtifact -Dir $dir -FileName 'inventory.json'

Write-AdoptHeading "Stack profile: $Name"

# ---- the profiles themselves must meet their own contract ----------------------------
$profiles = @(Get-AdoptProfiles -ProfilesDir $ProfilesDir)
$broken = @()
foreach ($p in $profiles) {
    # No @() here. Test-AdoptProfileContract returns `, $problems`, so the array arrives as
    # a single object; wrapping it again makes a one-element array of an array, whose Count
    # is 1 whether the profile was clean or not - every profile then reads as broken.
    $probs = Test-AdoptProfileContract -Spec $p
    if ($probs.Count -gt 0) { $broken += "$($p.name): $($probs -join '; ')" }
}
if ($broken.Count -gt 0) {
    Write-Error "These profiles do not meet the contract, so no detection can be trusted:`n  $($broken -join "`n  ")"
    exit 1
}
Write-Host "  $($profiles.Count) profiles loaded, all meeting the contract"

# ---- which folders are components ----------------------------------------------------
# A component is the root, plus any folder that carries a dependency manifest. Manifests
# inside an excluded tree do not count: a vendored product's own composer.json is part of
# that product, not a component of this app.
$manifestPaths = @($inventory.manifests | ForEach-Object { $_.path })
$excludedRx = '(?i)(^|[\\/])(node_modules|vendor|\.venv|venv|site-packages|bower_components|dist|build|target|out|\.git)([\\/]|$)'

$componentDirs = @('.')
foreach ($m in $manifestPaths) {
    if ($m -match $excludedRx) { continue }
    $d = Split-Path $m -Parent
    if ([string]::IsNullOrEmpty($d)) { continue }
    $componentDirs += ($d -replace '\\', '/')
}
$componentDirs = @($componentDirs | Sort-Object -Unique | Sort-Object { $_.Length })

if ($componentDirs.Count -gt $MaxComponents) {
    Write-Host "  $($componentDirs.Count) candidate component folders; keeping the $MaxComponents shallowest" -ForegroundColor Yellow
    $componentDirs = @($componentDirs | Select-Object -First $MaxComponents)
}

# ---- the file list each component is matched against ---------------------------------
# Detection needs the paths RELATIVE TO THE COMPONENT, so a rule saying `package.json`
# matches a manifest in apps/api when apps/api is the component being tested.
$allPaths = @()
$allPaths += @($inventory.paths)
$allPaths += @($inventory.manifests | ForEach-Object { $_.path })
$allPaths += @($inventory.entryPoints | ForEach-Object { $_.path })
$allPaths += @($inventory.configFiles)
$allPaths += @($inventory.ci)
$allPaths += @($inventory.docs)
$allPaths += @($inventory.tests.markers)
$allPaths = @($allPaths | Where-Object { $_ } | Sort-Object -Unique)

# Any file a detect rule wants to read, fetched once from the source.
$wantedFiles = @()
foreach ($p in $profiles) {
    $names = @($p.detect.PSObject.Properties.Name)
    foreach ($key in @('fileContains', 'noneContain')) {
        if ($names -notcontains $key) { continue }
        foreach ($c in @($p.detect.$key)) { foreach ($g in @($c.file)) { $wantedFiles += $g } }
    }
}
$wantedFiles = @($wantedFiles | Sort-Object -Unique)

$concreteWanted = @()
foreach ($g in $wantedFiles) {
    if ($g -match '[*?]') {
        $rx = '(?i)^' + [regex]::Escape($g).Replace('\*\*', '.*').Replace('\*', '[^\\/]*').Replace('/', '[\\/]') + '$'
        foreach ($cd in $componentDirs) {
            $prefix = if ($cd -eq '.') { '' } else { "$cd/" }
            foreach ($ap in $allPaths) {
                $relToComp = $ap -replace '\\', '/'
                if ($prefix -and -not $relToComp.StartsWith($prefix)) { continue }
                $tail = if ($prefix) { $relToComp.Substring($prefix.Length) } else { $relToComp }
                if ($tail -match $rx) { $concreteWanted += $ap }
            }
        }
    }
    else {
        foreach ($cd in $componentDirs) {
            $prefix = if ($cd -eq '.') { '' } else { "$cd/" }
            $concreteWanted += "$prefix$g"
        }
    }
}
$concreteWanted = @($concreteWanted | Sort-Object -Unique)

$fileText = @{}
if ($concreteWanted.Count -gt 0) {
    $fetched = Get-AdoptFileText -Path $inventory.source.path -ComputerName $inventory.source.computerName -RelativePaths $concreteWanted
    foreach ($k in @($fetched.Keys)) { $fileText[($k -replace '\\', '/')] = $fetched[$k] }
}

# ---- match ---------------------------------------------------------------------------
$components = @()
foreach ($cd in $componentDirs) {
    $prefix = if ($cd -eq '.') { '' } else { "$cd/" }

    $relPaths = @()
    foreach ($ap in $allPaths) {
        $n = $ap -replace '\\', '/'
        if ($prefix) {
            if (-not $n.StartsWith($prefix)) { continue }
            $relPaths += $n.Substring($prefix.Length)
        }
        else { $relPaths += $n }
    }
    if ($relPaths.Count -eq 0) { continue }

    $localText = @{}
    foreach ($k in @($fileText.Keys)) {
        if ($prefix) {
            if (-not $k.StartsWith($prefix)) { continue }
            $localText[$k.Substring($prefix.Length)] = $fileText[$k]
        }
        else { $localText[$k] = $fileText[$k] }
    }

    # NOT $matches: that is PowerShell's automatic $Matches, and the names collide
    # case-insensitively.
    $hits = @()
    foreach ($p in $profiles) {
        $score = Test-AdoptDetect -Detect $p.detect -RelativePaths $relPaths -FileText $localText
        if ($score -gt 0) { $hits += [pscustomobject]@{ name = $p.name; status = $p.status; score = $score } }
    }
    $hits = @($hits | Sort-Object -Property @{ Expression = 'score'; Descending = $true }, @{ Expression = 'name'; Descending = $false })
    if ($hits.Count -eq 0) { continue }

    $components += [ordered]@{
        path        = $cd
        profile     = $hits[0].name
        status      = $hits[0].status
        score       = $hits[0].score
        alsoMatches = @($hits | Select-Object -Skip 1 | ForEach-Object { $_.name })
        evidence    = @($relPaths | Where-Object { $_ -notmatch '[\\/]' } | Select-Object -First 8)
    }
}

# A folder inside an already-matched folder of the SAME profile is part of it, not a
# second component: apps/api inside a workspace is one service, not two.
$kept = @()
foreach ($c in $components) {
    $parent = $kept | Where-Object { $_.profile -eq $c.profile -and ($_.path -eq '.' -or $c.path.StartsWith("$($_.path)/")) }
    if (-not $parent) { $kept += $c }
}

if ($ForceProfile) {
    $forced = @($profiles | Where-Object { $_.name -eq $ForceProfile })
    if ($forced.Count -eq 0) {
        Write-Error "No profile '$ForceProfile'. Known: $(($profiles | ForEach-Object { $_.name }) -join ', ')"
        exit 1
    }
    $root = @($kept | Where-Object { $_.path -eq '.' })
    if ($root.Count -gt 0) { $kept = @($kept | Where-Object { $_.path -ne '.' }) }
    $kept = @([ordered]@{ path = '.'; profile = $ForceProfile; status = $forced[0].status; score = 0; alsoMatches = @(); evidence = @('forced with -Profile') }) + $kept
    Write-Host "  root component FORCED to '$ForceProfile' - record why in the plan" -ForegroundColor Yellow
}

$result = [ordered]@{
    name       = $Name
    resolvedAt = (Get-Date).ToUniversalTime().ToString('o')
    profilesDir = (Get-AdoptProfileDir -ProfilesDir $ProfilesDir)
    components = @($kept)
}
$out = Write-AdoptArtifact -Dir $dir -FileName 'profile.json' -Object $result

Write-AdoptHeading 'Components'
if ($kept.Count -eq 0) {
    Write-Host "  NO PROFILE MATCHED ANY FOLDER." -ForegroundColor Red
    Write-Host "  An app that runs has a stack, so this means the rules do not describe it yet." -ForegroundColor Red
    Write-Host "  Copy profiles/_template into a new folder, fill it in, and re-run. Set status" -ForegroundColor Red
    Write-Host "  to 'draft' - only a stack something has actually automated may be 'proven'." -ForegroundColor Red
    Write-Host ""
    Write-Host "  wrote $out"
    exit 2
}
foreach ($c in $kept) {
    $also = ''
    if (@($c.alsoMatches).Count -gt 0) { $also = "   ALSO MATCHES: $(@($c.alsoMatches) -join ', ')" }
    Write-Host ("    {0,-28} {1,-16} [{2}] score {3}{4}" -f $c.path, $c.profile, $c.status, $c.score, $also)
}

$ambiguous = @($kept | Where-Object { @($_.alsoMatches).Count -gt 0 })
if ($ambiguous.Count -gt 0) {
    Write-Host ""
    Write-Host "  A component that matches more than one profile is a DECISION, not a defect." -ForegroundColor Yellow
    Write-Host "  Confirm each with the owner before the plan is written. Leftover scaffolding from" -ForegroundColor Yellow
    Write-Host "  an abandoned rewrite matches its own stack perfectly and is not part of the app." -ForegroundColor Yellow
}

$draft = @($kept | Where-Object { $_.status -ne 'proven' })
if ($draft.Count -gt 0) {
    Write-Host ""
    Write-Host "  $($draft.Count) component(s) are on a DRAFT profile: described, not automated." -ForegroundColor DarkYellow
    Write-Host "  Follow it by hand and record what you did, so it can become proven later." -ForegroundColor DarkYellow
}

Write-Host ""
Write-Host "  wrote $out"
exit 0
