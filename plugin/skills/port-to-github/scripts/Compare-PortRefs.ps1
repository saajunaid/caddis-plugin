<#
.SYNOPSIS
  Compare branches and tags between two git locations by SHA. The only honest "did it copy" check.

.DESCRIPTION
  -Left and -Right can each be a URL, a local path, a UNC path or a bare repository.
  Uses git ls-remote, so nothing is fetched or changed.

  Modes:
    Equal           every head and tag matches on both sides (after a push)
    LeftInRight     every Left ref exists in Right with the same SHA; Right may have more
                    (before destroying an old host: nothing on the old host may be lost)

  Exit 0 when the mode holds, 1 when it does not, and the differing refs are printed.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Left,
    [Parameter(Mandatory)][string]$Right,
    [ValidateSet('Equal', 'LeftInRight')][string]$Mode = 'Equal',
    [string]$LeftLabel = 'left',
    [string]$RightLabel = 'right',
    [switch]$PassThru
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PortCommon.ps1')

function Get-Refs([string]$Where) {
    $lines = Invoke-PortGit @('ls-remote', '--heads', '--tags', $Where)
    $map = @{}
    foreach ($l in $lines) {
        if (-not $l) { continue }
        $sha, $ref = $l -split "`t", 2
        # An annotated tag shows twice: the tag object and the peeled commit (^{}). Compare the
        # tag object; the peeled line is derived from it.
        if ($ref -like '*^{}') { continue }
        $map[$ref] = $sha
    }
    return $map
}

$l = Get-Refs $Left
$r = Get-Refs $Right

$onlyLeft = @($l.Keys | Where-Object { -not $r.ContainsKey($_) } | Sort-Object)
$onlyRight = @($r.Keys | Where-Object { -not $l.ContainsKey($_) } | Sort-Object)
$differ = @($l.Keys | Where-Object { $r.ContainsKey($_) -and $r[$_] -ne $l[$_] } | Sort-Object)

$ok = ($onlyLeft.Count -eq 0 -and $differ.Count -eq 0)
if ($Mode -eq 'Equal') { $ok = $ok -and ($onlyRight.Count -eq 0) }

Write-Host ("{0}: {1} refs   {2}: {3} refs   only-{0}: {4}   only-{2}: {5}   differ: {6}" -f $LeftLabel, $l.Count, $RightLabel, $r.Count, $onlyLeft.Count, $onlyRight.Count, $differ.Count)
foreach ($x in $onlyLeft) { Write-Host "  only in ${LeftLabel}:  $x" }
if ($Mode -eq 'Equal') { foreach ($x in $onlyRight) { Write-Host "  only in ${RightLabel}: $x" } }
foreach ($x in $differ) { Write-Host "  differs:        $x  $($l[$x].Substring(0,12)) vs $($r[$x].Substring(0,12))" }

if ($l.Count -eq 0) {
    Write-PortFail "$LeftLabel has no refs at all. An empty side cannot prove anything."
    $ok = $false
}
if ($ok) { Write-PortOk "Refs agree ($Mode)." } else { Write-PortFail "Refs do NOT agree ($Mode)." }

if ($PassThru) {
    [pscustomobject]@{ Ok = $ok; OnlyLeft = $onlyLeft; OnlyRight = $onlyRight; Differ = $differ; LeftCount = $l.Count; RightCount = $r.Count }
}
if (-not $ok) { exit 1 }
exit 0
