<#
.SYNOPSIS
  Copy Gitea/Forgejo Actions workflows to .github/workflows in a working clone, and lint them.

.DESCRIPTION
  Run inside a normal (non-bare) clone of the NEW GitHub repository, on a feature branch.
  - Reads each workflow from -SourceRef (default HEAD), NOT from the working tree, so you can
    point it at the last commit before a workflow was frozen (e.g. -SourceRef <sha>).
  - Rewrites the `gitea.` expression context to `github.` (same meaning on both).
  - Optionally adds top-level `permissions: contents: write` (needed to push tags).
  - Never touches scripts the workflows call. GitHub only needs the WORKFLOW under
    .github/workflows; leaving .gitea/scripts where it is keeps the diff small.
  - Never stages or commits. It prints the files it wrote so you can review and add them by name.

  Exit 1 if any written workflow still contains an empty expression.
#>
[CmdletBinding()]
param(
    [string]$RepoPath = '.',
    [string]$From,
    [string]$SourceRef = 'HEAD',
    [switch]$AddPermissions,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PortCommon.ps1')

$RepoPath = (Resolve-Path -LiteralPath $RepoPath).Path
if (-not $From) {
    foreach ($c in '.gitea/workflows', '.forgejo/workflows') {
        $ls = Invoke-PortGit -AllowFailure @('-C', $RepoPath, 'ls-tree', '--name-only', "${SourceRef}:$c")
        if ($ls.ExitCode -eq 0 -and ($ls.Output -join '')) { $From = $c; break }
    }
}
if (-not $From) { throw "No .gitea/workflows or .forgejo/workflows at $SourceRef. Pass -From." }

$names = @(Invoke-PortGit @('-C', $RepoPath, 'ls-tree', '--name-only', "${SourceRef}:$From") | Where-Object { $_ -match '\.ya?ml$' })
if ($names.Count -eq 0) { throw "No workflow files in $From at $SourceRef." }

$target = Join-Path $RepoPath '.github/workflows'
New-Item -ItemType Directory -Force -Path $target | Out-Null
$written = @()
$bad = 0

foreach ($n in $names) {
    $dest = Join-Path $target $n
    if ((Test-Path -LiteralPath $dest) -and -not $Force) { Write-PortWarn "$n already exists in .github/workflows. Skipped (use -Force)."; continue }
    $text = (Invoke-PortGit @('-C', $RepoPath, 'show', "${SourceRef}:$From/$n")) -join "`n"

    $ctx = 0
    foreach ($m in [regex]::Matches($text, '\$\{\{[^}]*\}\}')) { $ctx += ([regex]::Matches($m.Value, '\bgitea\.')).Count }
    $text = [regex]::Replace($text, '(\$\{\{[^}]*?)\bgitea\.', '$1github.')
    # Repeat until no gitea. context remains inside any expression (several per expression).
    while ([regex]::IsMatch($text, '\$\{\{[^}]*?\bgitea\.')) { $text = [regex]::Replace($text, '(\$\{\{[^}]*?)\bgitea\.', '$1github.') }

    if ($AddPermissions -and $text -notmatch '(?m)^permissions:') {
        # Instance Replace with a real count. The static [regex]::Replace(s, p, r, 1) binds the 1 to
        # RegexOptions.IgnoreCase and replaces EVERY match.
        if ($text -match '(?m)^jobs:') { $text = ([regex]'(?m)^jobs:').Replace($text, "permissions:`n  contents: write`n`njobs:", 1) }
    }

    if ($text -match '(?m)^on:\s*(\[\s*)?workflow_dispatch' -and $text -notmatch '(?m)^\s+(push|pull_request)\s*:') {
        Write-PortWarn "$n triggers only on workflow_dispatch at $SourceRef. That is what a FROZEN workflow looks like. Re-run with -SourceRef set to the last commit before it was frozen."
    }

    [IO.File]::WriteAllText($dest, ($text -replace "`r?`n", "`n"), (New-Object Text.UTF8Encoding($false)))
    $written += ".github/workflows/$n"

    $lines = $text -split "`n"
    $empty = @()
    for ($i = 0; $i -lt $lines.Count; $i++) { if ($lines[$i] -match '\$\{\{\s*\}\}') { $empty += ($i + 1) } }
    if ($empty.Count -gt 0) {
        $bad++
        Write-PortFail "$n line(s) $($empty -join ', '): empty `${{ }}. GitHub rejects the whole file. Reword the text (a comment inside run: is still scanned)."
    }
    Write-PortOk "$n -> .github/workflows/$n (gitea. context rewritten: $ctx)"
    $creds = @()
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match 'secrets\.|github\.token|(?i)token\s*:|_TOKEN\b|_USER\b|PASSWORD') { $creds += ("    {0}: {1}" -f ($i + 1), $lines[$i].Trim()) }
    }
    if ($creds.Count -gt 0) {
        Write-Host "  Credential lines - decide EACH one: ORIGIN-facing (this repo: fetch, checkout, tag push) -> `${{ github.token }} with user x-access-token; DEPENDENCY host -> a secret valid for THAT host."
        $creds | ForEach-Object { Write-Host $_ }
    }
}

Write-Host ''
Write-Host 'Written (review, then git add each file BY NAME):'
$written | ForEach-Object { Write-Host "  $_" }
if ($bad -gt 0) { exit 1 }
exit 0
