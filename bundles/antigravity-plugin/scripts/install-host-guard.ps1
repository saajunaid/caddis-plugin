[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$NssmSha256,
    [ValidateSet('report', 'enforce')]
    [string]$Mode = 'report'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$sourceNssm = 'C:\Tools\nssm\nssm.exe'
$serviceName = 'caddis-host-guard'
$programRoot = Join-Path $env:ProgramFiles 'caddis'
$nssmDir = Join-Path $programRoot 'nssm'
$nssm = Join-Path $nssmDir 'nssm.exe'
$pythonDir = Join-Path $env:ProgramFiles 'caddis\python'
$privatePython = Join-Path $pythonDir 'python.exe'
$serviceDir = Join-Path $env:ProgramData 'caddis'
$guardScript = Join-Path $serviceDir 'caddis_host_guard.py'
$governorScript = Join-Path $serviceDir 'caddis_governor.py'
$budget = Join-Path $env:ProgramData 'caddis\host-budget.toml'
$stdoutLog = Join-Path $serviceDir 'guard.out.log'
$stderrLog = Join-Path $serviceDir 'guard.err.log'
$sourceGuard = Join-Path $PSScriptRoot 'caddis_host_guard.py'
$sourceGovernor = Join-Path $PSScriptRoot 'caddis_governor.py'

if ($Apply -and $NssmSha256 -notmatch '\A[0-9a-fA-F]{64}\z') {
    [Console]::Error.WriteLine('-Apply requires -NssmSha256 with the trusted NSSM SHA256 (64 hexadecimal characters).')
    exit 3
}

if (-not (Test-Path -LiteralPath $sourceNssm -PathType Leaf)) {
    [Console]::Error.WriteLine("NSSM was not found at $sourceNssm.")
    exit 3
}

if (-not $Apply) {
    Write-Output '# Dry run. Run again with -Apply -NssmSha256 <trusted SHA256> from an elevated shell.'
    Write-Output "New-Item -ItemType Directory -Force -Path `"$programRoot`""
    Write-Output "New-Item -ItemType Directory -Force -Path `"$serviceDir`""
    Write-Output "Get-ChildItem -LiteralPath `"$programRoot`" -Force -Recurse  # refuse reparse points"
    Write-Output "Get-ChildItem -LiteralPath `"$serviceDir`" -Force -Recurse  # refuse reparse points"
    Write-Output "icacls `"$programRoot`" /setowner `"*S-1-5-32-544`" /T /C"
    Write-Output "icacls `"$programRoot`" /reset /T /C"
    Write-Output "icacls `"$programRoot`" /inheritance:r /grant:r `"*S-1-5-32-544:(OI)(CI)F`" `"*S-1-5-18:(OI)(CI)F`" `"*S-1-5-32-545:(OI)(CI)RX`""
    Write-Output "icacls `"$serviceDir`" /setowner `"*S-1-5-32-544`" /T /C"
    Write-Output "icacls `"$serviceDir`" /reset /T /C"
    Write-Output "icacls `"$serviceDir`" /inheritance:r /grant:r `"*S-1-5-32-544:(OI)(CI)F`" `"*S-1-5-18:(OI)(CI)F`" `"*S-1-5-32-545:(OI)(CI)RX`""
    Write-Output "New-Item -ItemType Directory -Force -Path `"$nssmDir`""
    Write-Output "Lock-CaddisTree -Path `"$nssmDir`""
    Write-Output "Copy-Item -LiteralPath `"$sourceNssm`" -Destination `"$nssm`" -Force"
    Write-Output "Lock-CaddisTree -Path `"$nssmDir`""
    Write-Output "Get-TrustedFileHash -Path `"$nssm`"  # must equal -NssmSha256; refuse with exit 3 otherwise"
    Write-Output '$sourcePython = (Get-Command python -CommandType Application -ErrorAction Stop).Source  # require a valid PSF signature'
    Write-Output '$basePrefix = Split-Path -Parent $sourcePython  # refuse venvs, python*._pth and python*.zip'
    Write-Output ('robocopy "$basePrefix" "{0}" /MIR /XD Lib\site-packages /XF python*._pth python*.zip' -f $pythonDir)
    Write-Output ('& "{0}" -I -S -c ''import sys; print(sys.base_prefix)''  # must resolve to the private copy' -f $privatePython)
    Write-Output "Copy-Item -LiteralPath `"$sourceGuard`" -Destination `"$guardScript`" -Force"
    Write-Output "Copy-Item -LiteralPath `"$sourceGovernor`" -Destination `"$governorScript`" -Force"
    Write-Output "Write default host budget to `"$budget`" with guard mode `"$Mode`" if it is missing"
    Write-Output "icacls `"$programRoot`" /setowner `"*S-1-5-32-544`" /T /C"
    Write-Output "icacls `"$serviceDir`" /setowner `"*S-1-5-32-544`" /T /C"
    Write-Output "& `"$nssm`" install $serviceName `"$privatePython`" -I -S `"$guardScript`" run --budget `"$budget`""
    Write-Output "Update the existing $serviceName service PathName to the quoted protected path `"$nssm`" using Win32_Service.Change."
    Write-Output "& `"$nssm`" set $serviceName AppStdout `"$stdoutLog`""
    Write-Output "& `"$nssm`" set $serviceName AppStderr `"$stderrLog`""
    Write-Output "& `"$nssm`" set $serviceName ObjectName LocalSystem"
    Write-Output "& `"$nssm`" set $serviceName Start SERVICE_AUTO_START"
    Write-Output "& `"$nssm`" start $serviceName"
    exit 0
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin) {
    [Console]::Error.WriteLine('install-host-guard.ps1 -Apply requires an elevated shell.')
    exit 3
}

foreach ($source in @($sourceGuard, $sourceGovernor)) {
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Required service file not found: $source"
    }
}

$serviceAlreadyInstalled = $null -ne (Get-Service -Name $serviceName -ErrorAction SilentlyContinue)
$budgetAlreadyExists = Test-Path -LiteralPath $budget -PathType Leaf
if ($budgetAlreadyExists -and -not $serviceAlreadyInstalled) {
    [Console]::Error.WriteLine(
        "Refusing the pre-existing $budget because no installed service proves that it is admin-owned. " +
        'Inspect it, remove it, and run the installer again.'
    )
    exit 3
}

function Lock-CaddisTree {
    param([Parameter(Mandatory)][string]$Path)

    $rootItem = Get-Item -LiteralPath $Path -Force
    $reparsePoint = @($rootItem) + @(Get-ChildItem -LiteralPath $Path -Force -Recurse)
    $reparsePoint = $reparsePoint | Where-Object {
        ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
    } | Select-Object -First 1
    if ($null -ne $reparsePoint) {
        throw "Refusing reparse point in service tree: $($reparsePoint.FullName)"
    }

    # Remove inherited and explicit grants from any pre-existing tree before the LocalSystem
    # service can read it. New files then inherit only the three grants below.
    & icacls.exe $Path '/setowner' '*S-1-5-32-544' '/T' '/C'
    if ($LASTEXITCODE -ne 0) {
        throw "icacls owner change failed for $Path with exit code $LASTEXITCODE"
    }
    & icacls.exe $Path '/reset' '/T' '/C'
    if ($LASTEXITCODE -ne 0) {
        throw "icacls reset failed for $Path with exit code $LASTEXITCODE"
    }
    & icacls.exe $Path '/inheritance:r' '/grant:r' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)RX'
    if ($LASTEXITCODE -ne 0) {
        throw "icacls lock failed for $Path with exit code $LASTEXITCODE"
    }
}

function Set-CaddisTreeOwner {
    param([Parameter(Mandatory)][string]$Path)

    & icacls.exe $Path '/setowner' '*S-1-5-32-544' '/T' '/C'
    if ($LASTEXITCODE -ne 0) {
        throw "icacls owner change failed for $Path with exit code $LASTEXITCODE"
    }
}

function Assert-NoPythonPathOverride {
    param([Parameter(Mandatory)][string]$Path)

    if (Test-Path -LiteralPath $Path -PathType Container) {
        foreach ($pattern in @('python*._pth', 'python*.zip')) {
            $override = Get-ChildItem -LiteralPath $Path -Filter $pattern -File -Force |
                Select-Object -First 1
            if ($null -ne $override) {
                [Console]::Error.WriteLine("Refusing Python path override file: $($override.FullName)")
                exit 3
            }
        }
    }
}

function Assert-AdminOwned {
    param(
        [Parameter(Mandatory)][string]$Path,
        [switch]$RequireReadOnlyFile
    )

    $acl = Get-Acl -LiteralPath $Path
    $ownerSid = ([Security.Principal.NTAccount]$acl.Owner).Translate(
        [Security.Principal.SecurityIdentifier]
    ).Value
    $trustedSids = @('S-1-5-18', 'S-1-5-32-544')
    if ($ownerSid -notin $trustedSids) {
        [Console]::Error.WriteLine("Refusing non-admin-owned path: $Path (owner $ownerSid)")
        exit 3
    }

    if ($RequireReadOnlyFile) {
        $writeRights = [Security.AccessControl.FileSystemRights]::Write -bor
            [Security.AccessControl.FileSystemRights]::Delete -bor
            [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
            [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
            [Security.AccessControl.FileSystemRights]::TakeOwnership
        foreach ($rule in $acl.Access) {
            $ruleSid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
            if ($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
                $ruleSid -notin $trustedSids -and ($rule.FileSystemRights -band $writeRights)) {
                [Console]::Error.WriteLine("Refusing user-writable path: $Path ($ruleSid)")
                exit 3
            }
        }
    }
}

function Get-TrustedFileHash {
    param([Parameter(Mandatory)][string]$Path)

    $stream = [IO.File]::Open(
        $Path,
        [IO.FileMode]::Open,
        [IO.FileAccess]::Read,
        [IO.FileShare]::Read
    )
    try {
        # The open handle denies writes and deletes, so this ACL check and hash describe
        # the same file even when the parent directory permits users to add files.
        Assert-AdminOwned -Path $Path -RequireReadOnlyFile
        $sha256 = [Security.Cryptography.SHA256]::Create()
        try {
            return [BitConverter]::ToString($sha256.ComputeHash($stream)).Replace('-', '')
        } finally {
            $sha256.Dispose()
        }
    } finally {
        $stream.Dispose()
    }
}

function Get-TrustedPythonFiles {
    param([Parameter(Mandatory)][string]$BasePrefix)

    $trustedFiles = [Collections.Generic.Dictionary[string, string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    $sitePackages = [IO.Path]::GetFullPath((Join-Path $BasePrefix 'Lib\site-packages')).TrimEnd('\') + '\'
    foreach ($item in Get-ChildItem -LiteralPath $BasePrefix -Force -Recurse -ErrorAction Stop) {
        $fullPath = [IO.Path]::GetFullPath($item.FullName)
        if ($fullPath.StartsWith($sitePackages, [StringComparison]::OrdinalIgnoreCase)) {
            continue
        }

        if ($item.PSIsContainer) {
            Assert-AdminOwned -Path $fullPath
            continue
        }

        $relativePath = [IO.Path]::GetRelativePath($BasePrefix, $fullPath)
        if ($item.Extension -in @('.dll', '.pyd') -and
            -not $relativePath.StartsWith('tcl\', [StringComparison]::OrdinalIgnoreCase)) {
            $signature = Get-AuthenticodeSignature -LiteralPath $fullPath
            if ($signature.Status -ne 'Valid' -or
                $signature.SignerCertificate.Subject -notmatch
                    'O=(?:Python Software Foundation|Microsoft Corporation)(?:,|$)') {
                [Console]::Error.WriteLine("Refusing an unsigned or unexpected Python binary: $fullPath")
                exit 3
            }
        }
        $trustedFiles[$relativePath] = Get-TrustedFileHash -Path $fullPath
    }
    return ,$trustedFiles
}

$sourcePython = (Get-Command python -CommandType Application -ErrorAction Stop).Source
$sourcePythonDir = Split-Path -Parent $sourcePython
Assert-NoPythonPathOverride -Path $sourcePythonDir
$sourcePythonItem = Get-Item -LiteralPath $sourcePython -Force
if (($sourcePythonItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
    [Console]::Error.WriteLine("Refusing a reparse-point Python executable: $sourcePython")
    exit 3
}
Assert-AdminOwned -Path $sourcePython -RequireReadOnlyFile
$sourceSignature = Get-AuthenticodeSignature -LiteralPath $sourcePython
if ($sourceSignature.Status -ne 'Valid' -or
    $sourceSignature.SignerCertificate.Subject -notmatch 'O=Python Software Foundation(?:,|$)') {
    [Console]::Error.WriteLine("Refusing an untrusted Python executable: $sourcePython")
    exit 3
}

$basePrefix = $sourcePythonDir
if (-not (Test-Path -LiteralPath (Join-Path $basePrefix 'Lib') -PathType Container) -or
    (Test-Path -LiteralPath (Join-Path (Split-Path -Parent $basePrefix) 'pyvenv.cfg') -PathType Leaf)) {
    [Console]::Error.WriteLine('The Python on PATH must be a base installation, not a virtual environment.')
    exit 3
}
$sourceReparsePoint = Get-ChildItem -LiteralPath $basePrefix -Force -Recurse | Where-Object {
    ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
} | Select-Object -First 1
if ($null -ne $sourceReparsePoint) {
    [Console]::Error.WriteLine("Refusing reparse point in the source Python tree: $($sourceReparsePoint.FullName)")
    exit 3
}
Assert-NoPythonPathOverride -Path $basePrefix
$trustedSourceFiles = Get-TrustedPythonFiles -BasePrefix $basePrefix

New-Item -ItemType Directory -Force -Path $programRoot | Out-Null
New-Item -ItemType Directory -Force -Path $serviceDir | Out-Null
Lock-CaddisTree -Path $programRoot
Lock-CaddisTree -Path $serviceDir

New-Item -ItemType Directory -Force -Path $nssmDir | Out-Null
Lock-CaddisTree -Path $nssmDir
Copy-Item -LiteralPath $sourceNssm -Destination $nssm -Force
Lock-CaddisTree -Path $nssmDir
Assert-AdminOwned -Path $nssmDir -RequireReadOnlyFile
if ((Get-TrustedFileHash -Path $nssm) -ine $NssmSha256) {
    [Console]::Error.WriteLine('The protected NSSM copy does not match -NssmSha256.')
    exit 3
}

& robocopy.exe $basePrefix $pythonDir /MIR /XD 'Lib\site-packages' /XF 'python*._pth' 'python*.zip'
if ($LASTEXITCODE -ge 8) {
    throw "robocopy failed with exit code $LASTEXITCODE"
}
if (-not (Test-Path -LiteralPath $privatePython -PathType Leaf)) {
    throw "The private Python copy does not contain $privatePython"
}
Assert-NoPythonPathOverride -Path $pythonDir
Set-CaddisTreeOwner -Path $programRoot
$trustedPrivateFiles = Get-TrustedPythonFiles -BasePrefix $pythonDir
if ($trustedPrivateFiles.Count -ne $trustedSourceFiles.Count) {
    throw 'The private Python copy does not contain the validated source file set.'
}
foreach ($entry in $trustedSourceFiles.GetEnumerator()) {
    $privateHash = $null
    if (-not $trustedPrivateFiles.TryGetValue($entry.Key, [ref]$privateHash) -or
        $privateHash -ne $entry.Value) {
        throw "The private Python copy does not match the validated source: $($entry.Key)"
    }
}
$privateSignature = Get-AuthenticodeSignature -LiteralPath $privatePython
if ($privateSignature.Status -ne 'Valid' -or
    $privateSignature.SignerCertificate.Subject -notmatch 'O=Python Software Foundation(?:,|$)') {
    throw "The private Python copy failed signature validation: $privatePython"
}
$copiedBasePrefix = (& $privatePython -I -S -c 'import sys; print(sys.base_prefix)').Trim()
if ($LASTEXITCODE -ne 0 -or $copiedBasePrefix -ine $pythonDir) {
    throw "The private Python resolved sys.base_prefix to $copiedBasePrefix instead of $pythonDir"
}

Copy-Item -LiteralPath $sourceGuard -Destination $guardScript -Force
Copy-Item -LiteralPath $sourceGovernor -Destination $governorScript -Force

if (-not (Test-Path -LiteralPath $budget -PathType Leaf)) {
    $budgetText = @"
[session]
cpu_percent = 50
memory_mb = 24576
max_processes = 256

[lane]
cpu_percent = 25
memory_mb = 8192
max_processes = 64

[guard]
mode = "$Mode"
host_cpu_percent = 85
sustain_seconds = 60
sample_seconds = 10
min_free_memory_mb = 4096
root_images = ["claude.exe", "codex.exe", "agy.exe"]
"@
    [System.IO.File]::WriteAllText($budget, $budgetText, [System.Text.UTF8Encoding]::new($false))
}

$modeReader = 'import pathlib, sys, tomllib; p = pathlib.Path(sys.argv[1]); data = tomllib.loads(p.read_text(encoding="utf-8")); print(data.get("guard", {}).get("mode", "enforce"))'
$configuredMode = (& $privatePython -I -S -c $modeReader $budget).Trim()
if ($LASTEXITCODE -ne 0 -or -not $configuredMode) {
    throw "Could not read the guard mode from $budget"
}
if ($configuredMode -ne $Mode) {
    [Console]::Error.WriteLine(
        "$budget is in $configuredMode mode, not requested $Mode mode. Change it from an elevated shell and run again."
    )
    exit 3
}

Set-CaddisTreeOwner -Path $programRoot
Set-CaddisTreeOwner -Path $serviceDir

if ($serviceAlreadyInstalled) {
    # Updating Application alone leaves the old wrapper in the service ImagePath.
    $service = Get-CimInstance -ClassName Win32_Service -Filter "Name='$serviceName'"
    $change = Invoke-CimMethod -InputObject $service -MethodName Change -Arguments @{
        PathName = '"{0}"' -f $nssm
    }
    if ($change.ReturnValue -ne 0) {
        throw "Service binary update failed with code $($change.ReturnValue)"
    }
    $appParameters = '-I -S "{0}" run --budget "{1}"' -f $guardScript, $budget
    & $nssm set $serviceName Application $privatePython
    if ($LASTEXITCODE -ne 0) { throw "nssm Application failed with exit code $LASTEXITCODE" }
    & $nssm set $serviceName AppParameters $appParameters
    if ($LASTEXITCODE -ne 0) { throw "nssm AppParameters failed with exit code $LASTEXITCODE" }
} else {
    & $nssm install $serviceName $privatePython '-I' '-S' $guardScript 'run' '--budget' $budget
    if ($LASTEXITCODE -ne 0) { throw "nssm install failed with exit code $LASTEXITCODE" }
}
& $nssm set $serviceName AppStdout $stdoutLog
if ($LASTEXITCODE -ne 0) { throw "nssm AppStdout failed with exit code $LASTEXITCODE" }
& $nssm set $serviceName AppStderr $stderrLog
if ($LASTEXITCODE -ne 0) { throw "nssm AppStderr failed with exit code $LASTEXITCODE" }
& $nssm set $serviceName ObjectName LocalSystem
if ($LASTEXITCODE -ne 0) { throw "nssm ObjectName failed with exit code $LASTEXITCODE" }
& $nssm set $serviceName Start SERVICE_AUTO_START
if ($LASTEXITCODE -ne 0) { throw "nssm Start failed with exit code $LASTEXITCODE" }
if ($serviceAlreadyInstalled) {
    & $nssm restart $serviceName
    if ($LASTEXITCODE -ne 0) { throw "nssm restart failed with exit code $LASTEXITCODE" }
} else {
    & $nssm start $serviceName
    if ($LASTEXITCODE -ne 0) { throw "nssm start failed with exit code $LASTEXITCODE" }
}

Write-Output "installed in $Mode mode; switch with: set mode in $budget then & `"$nssm`" restart $serviceName"
