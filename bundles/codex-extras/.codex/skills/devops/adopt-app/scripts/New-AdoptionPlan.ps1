<#
.SYNOPSIS
    Phase 4. Turn the inventory, the profile and the conformance report into an ORDERED
    plan a person can work through. Writes adoption-plan.md and adoption.json.

.DESCRIPTION
    The order is the product. Every step in an adoption has a prerequisite, and doing them
    in the wrong order costs real work:

      - Create the repository BEFORE settling what must not be in it, and removing it
        later means rewriting history that other people have already cloned.
      - Rotate a credential AFTER publishing, and it was public in between.
      - Wire up CI before anyone has said which branch is the truth, and CI builds the
        wrong branch.

    So the plan is emitted in dependency order, each step carrying the evidence that put
    it there and the check that says it is done. Steps that cannot start are listed as
    BLOCKED with the reason, rather than left out - a plan that silently omits what it
    cannot do reads like a shorter job.

    This script writes a document. It changes nothing else, and it deliberately does not
    execute any step.

.EXAMPLE
    ./New-AdoptionPlan.ps1 -Name legacy-app
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Name,
    [string]$OutDir,
    # The fleet- or team-specific skill that performs the adoption once this plan is
    # agreed. Named in the handover section so the plan does not end in mid-air.
    [string]$HandoverSkill = ''
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'AdoptCommon.ps1')

$dir = Resolve-AdoptOutDir -Name $Name -OutDir $OutDir
$inv = Read-AdoptArtifact -Dir $dir -FileName 'inventory.json'
$prof = Read-AdoptArtifact -Dir $dir -FileName 'profile.json'
$conf = Read-AdoptArtifact -Dir $dir -FileName 'conformance.json'

function Get-ConformanceItem { param([string]$Id) return @($conf.items | Where-Object { $_.id -eq $Id })[0] }
function Test-ItemPasses { param([string]$Id) $i = Get-ConformanceItem $Id; return ($null -ne $i) -and ($i.verdict -in @('PASS', 'ANSWERED')) }

$steps = @()
function Add-Step {
    param(
        [string]$Id, [string]$Title, [string[]]$Needs = @(), [string]$Why = '',
        [string[]]$Do = @(), [string]$Done = '', [string]$State = 'TODO'
    )
    $script:steps += [ordered]@{ id = $Id; title = $Title; needs = $Needs; why = $Why; actions = $Do; doneWhen = $Done; state = $State }
}

# ---------------------------------------------------------------------------------------
# 1. Answer what only a person can answer.
$openQuestions = @($conf.items | Where-Object { $_.verdict -eq 'ASK' })
if ($openQuestions.Count -gt 0) {
    Add-Step 'answers' 'Get the owner''s answers' @() `
        'Every later step depends on at least one of these. They are not observable from files, so no amount of scanning will settle them.' `
        (@($openQuestions | ForEach-Object { "[$($_.id)] $($_.question)" }) + @("Record each: Test-AppConformance.ps1 -Name $Name -Answer <id>=`"...`"")) `
        'Test-AppConformance.ps1 reports no open ASK on a blocking item.' `
        $(if (@($conf.blockingQuestions).Count -gt 0) { 'TODO' } else { 'TODO-NONBLOCKING' })
}

# 2. Decide the content policy, BEFORE any repository exists.
$so = Get-ConformanceItem 'source-only'
if ($so -and $so.verdict -eq 'GAP') {
    $lines = @()
    foreach ($f in @($inv.size.folders | Where-Object { $_.git -eq 'untracked' -and $_.path -ne '.git' -and $_.mb -ge 1 })) {
        $lines += "$($f.path) - $($f.mb) MB, neither committed nor ignored: commit it, ignore it, or move it out of the tree"
    }
    foreach ($e in @($inv.excludableSummary | Select-Object -First 10)) {
        $g = @($inv.size.folders | Where-Object { $_.path -eq $e.folder })
        if ($g.Count -gt 0 -and $g[0].git -eq 'tracked') {
            $lines += "$($e.folder) - $($e.mb) MB of $($e.category) is COMMITTED: needs a history rewrite, not a .gitignore line"
        }
    }
    Add-Step 'content-policy' 'Settle what the repository may hold' @('answers') `
        'A .gitignore added later does not remove what is already committed, and a folder that is neither committed nor ignored is one careless command away from being permanent.' `
        $lines `
        'Every folder over the size threshold is classified: source, ignored-and-provisioned, or moved out.'
}

# 3. Credentials.
$sec = Get-ConformanceItem 'no-secrets'
if ($sec -and $sec.verdict -eq 'GAP') {
    Add-Step 'secrets' 'Read every flagged file, then rotate what was real' @('content-policy') `
        'Publishing is irreversible. A credential that reaches a hosted repository must be treated as disclosed, whether or not anyone fetched it.' `
        (@(@($inv.secretsSuspected | Select-Object -First 15 | ForEach-Object {
            $ln = Get-AdoptProp $_ 'line'
            if ($ln) { "$($_.path):$ln - key '$(Get-AdoptProp $_ 'key')'" } else { "$($_.path) - $($_.why)" }
        })) + @('For each: is it real? If yes, ROTATE it and remove it from the tree AND from history.')) `
        'No real credential remains in the tree, and every one that was there has been rotated.'
}

# 4. The repository.
if (-not (Test-ItemPasses 'git-repo')) {
    Add-Step 'import' 'Import the folder as a repository' @('content-policy', 'secrets') `
        'There is no history to preserve, so the first commit is a decision about content, not about history.' `
        @('Write .gitignore FIRST, from the content policy above.', 'Stage files BY NAME. Never `git add -A` in a folder this size.', 'One import commit, then push.') `
        'The remote holds the source and nothing the content policy excluded.'
}
elseif (-not (Test-ItemPasses 'remote-on-team-host')) {
    $rem = Get-ConformanceItem 'remote-on-team-host'
    Add-Step 'port' 'Move the repository to the team''s host' @('content-policy', 'secrets', 'answers') `
        "Today: $($rem.evidence)" `
        @('Use the port-to-github skill: it stages the source read-only, verifies every branch and tag by SHA, and never pushes back to the source.',
          'Push every ref that exists only on the old host BEFORE converting or deleting it.',
          'Keep the old remote as a second remote until the first deploy from the new one is green.') `
        'Every branch and tag matches by SHA on the new host, and the old one is read-only or archived.'
}

# 5. The rest, in the order they unblock each other.
if (-not (Test-ItemPasses 'deps-pinned')) {
    Add-Step 'pin-deps' 'Pin the dependencies' @('import', 'port') `
        'Without a lock file a failed build cannot be told from a dependency that moved underneath it.' `
        @('Commit the lock file the ecosystem produces.', 'Record the exact runtime version the app is built and run with.') `
        'A clean checkout on another machine installs the same versions.'
}

$rm = Get-ConformanceItem 'runtime-manifest'
if ($rm -and $rm.verdict -ne 'PASS') {
    Add-Step 'provision' 'Write down how to rebuild the environment' @('content-policy') `
        "Excluding a runtime from the repository is only safe once something says how to get it back. $($rm.evidence)" `
        @('For each excluded folder: name the component, the EXACT version, and where it is installed from.',
          'Write a provisioning script that FAILS for anything it cannot provision, rather than skipping it.',
          'Copy configuration out of the runtime folders as templates - configuration is app content even when the runtime around it is not.') `
        'A new machine can be brought to a working state from the repository plus the provisioning script.'
}

if (-not (Test-ItemPasses 'tests')) {
    Add-Step 'tests' 'Get a test suite that CI can run' @('pin-deps') `
        'CI that runs no tests only proves the code compiles.' `
        @('Start with the paths that would break silently: the ones with no health signal and no rollback.') `
        'One command runs the suite and returns a non-zero exit code when it fails.'
}

if (-not (Test-ItemPasses 'ci-build')) {
    Add-Step 'ci' 'Add CI that builds and tests every push' @('import', 'port', 'pin-deps') `
        'Until CI exists, "it works" means "it worked on one machine".' `
        @('Build and test on push and on pull request.',
          'Classify every credential in the workflow: it faces ORIGIN, or it names a DEPENDENCY host. There is no third kind.',
          'Never write double-curly-brace text anywhere in a workflow file, including inside comments in a run block.') `
        'A pull request cannot merge while the build or the tests fail.'
}

$health = Get-ConformanceItem 'health'
if ($health -and $health.verdict -ne 'PASS') {
    Add-Step 'health' 'Add a health signal that can fail' @('ci') `
        'A check that cannot fail manufactures confidence. The commonest version returns 200 from a catch-all route while the app is broken.' `
        @('For a service: an endpoint that reports its dependencies and fails when one is down.',
          'For a batch job: a non-zero exit code AND an output artefact whose absence is detectable.',
          'Prove it fails: break the dependency on purpose and watch the check go red.') `
        'The check has been observed FAILING, not only passing.'
}

if (-not (Test-ItemPasses 'ci-deploy')) {
    Add-Step 'deploy' 'Make the deployment reproducible' @('ci', 'health', 'provision') `
        'A manual deploy is a procedure that exists only in somebody''s memory.' `
        @('Build the artefact BEFORE stopping anything. Only a build that produced one earns the right to interrupt the service.',
          'Roll the code and the built artefact back together - restoring one without the other leaves a mixed state that passes every check.',
          'Verify by the artefact CHANGING - a bundle hash, a file time - never by an HTTP 200 or a version endpoint. Both pass in the mixed state.') `
        'A deploy can be run by someone who has never done it, from the written steps alone.'
}

$rb = Get-ConformanceItem 'rollback'
if ($rb -and $rb.verdict -ne 'PASS') {
    Add-Step 'rollback' 'Write and TEST the way back' @('deploy') `
        'A rollback nobody has run is a plan, not a capability.' `
        @('Write the exact command.', 'Run it once, deliberately, on a real release.', 'Note what it cannot undo - a database migration usually cannot.') `
        'The rollback has been executed at least once and the result was verified.'
}

$run = Get-ConformanceItem 'run-declared'
if ($run -and $run.verdict -ne 'PASS') {
    Add-Step 'run-declared' 'Declare how it runs, in the repository' @('deploy') `
        "How this app starts is not currently recorded anywhere version-controlled. $($run.evidence)" `
        @('Commit the service definition or the schedule.', 'Record the account it runs as and why that account.', 'Record the trigger: a port, a timer, a queue, a person.') `
        'Recreating the runtime registration needs no undocumented knowledge.'
}

foreach ($small in @(
        @{ id = 'docs'; item = 'docs-readme'; title = 'Write the README'; why = 'The first question a new person asks is what this is and how to run it.'; done = 'A new person can run it locally from the README alone.' },
        @{ id = 'agent-rules'; item = 'agent-rules'; title = 'Add the agent rules file'; why = 'Without it every coding agent re-derives the project rules, and each derives them differently.'; done = 'The file exists and states the rules that are not obvious from the code.' },
        @{ id = 'junctions'; item = 'no-junctions'; title = 'Remove the junctions from the tree'; why = 'git''s recursive remove follows a junction and deletes the TARGET''s contents. This is data loss, not an inconvenience.'; done = 'No reparse point remains inside the tree git manages; shared state is reached by absolute path.' }
    )) {
    if (-not (Test-ItemPasses $small.item)) {
        Add-Step $small.id $small.title @('import', 'port') $small.why @() $small.done
    }
}

# ---- mark blocked steps --------------------------------------------------------------
$presentIds = @($steps | ForEach-Object { $_.id })
foreach ($s in $steps) {
    $blockers = @($s.needs | Where-Object { $presentIds -contains $_ })
    if ($blockers.Count -gt 0 -and $s.id -ne 'answers') { $s.state = 'BLOCKED' }
    $s.needs = $blockers
}

# ---- write ----------------------------------------------------------------------------
$json = [ordered]@{
    name = $Name; plannedAt = (Get-Date).ToUniversalTime().ToString('o')
    source = $inv.source; components = @($prof.components)
    blockingGaps = @($conf.blockingGaps); blockingQuestions = @($conf.blockingQuestions)
    steps = $steps
}
$jsonPath = Write-AdoptArtifact -Dir $dir -FileName 'adoption.json' -Object $json

$md = New-Object System.Text.StringBuilder
[void]$md.AppendLine("# Adopting $Name")
[void]$md.AppendLine()
[void]$md.AppendLine("Generated $((Get-Date).ToUniversalTime().ToString('u')) by the adopt-app skill, from a read-only scan. Nothing in the app was executed.")
[void]$md.AppendLine()
[void]$md.AppendLine('## What this app is')
[void]$md.AppendLine()
# A markdown code span is delimited by a backtick, which is also PowerShell's escape
# character, so the delimiter is built as a variable rather than typed inside the string.
$tick = [char]0x60
$sourceHost = ''
if ($inv.source.computerName) { $sourceHost = " on $($inv.source.computerName)" }
[void]$md.AppendLine("- **Source**: $tick$($inv.source.path)$tick$sourceHost ($($inv.source.kind))")
$sizeWord = if ($inv.size.totalMBIsMinimum) { 'at least ' } else { '' }
[void]$md.AppendLine("- **Size**: $sizeWord$($inv.size.totalMB) MB in $($inv.size.totalFiles) files")
if ($inv.git.isRepo) {
    $remoteText = if (@($inv.git.remotes).Count -gt 0) { (@($inv.git.remotes | ForEach-Object { $_.url }) -join ', ') } else { '**none - this folder is the only copy**' }
    [void]$md.AppendLine("- **Git**: $($inv.git.commits) commits, $($inv.git.localBranches) local branches, $($inv.git.tags) tags; remote: $remoteText")
}
else { [void]$md.AppendLine('- **Git**: not a repository') }
[void]$md.AppendLine("- **Components**:")
foreach ($c in @($prof.components)) {
    $also = if (@($c.alsoMatches).Count -gt 0) { " (also matches $((@($c.alsoMatches)) -join ', ') - confirm which it is)" } else { '' }
    [void]$md.AppendLine("  - $tick$($c.path)$tick -> **$($c.profile)** [$($c.status)]$also")
}
if ($inv.partial) {
    [void]$md.AppendLine()
    [void]$md.AppendLine('> **The scan was partial.** Every "nothing found" below means "nothing found so far":')
    foreach ($r in @($inv.partialReason)) { [void]$md.AppendLine("> - $r") }
}
[void]$md.AppendLine()

[void]$md.AppendLine('## Where it stands')
[void]$md.AppendLine()
[void]$md.AppendLine('| | Item | Verdict | Evidence |')
[void]$md.AppendLine('|---|---|---|---|')
foreach ($it in @($conf.items)) {
    $b = if ($it.blocking) { '**!**' } else { '' }
    $ev = "$($it.evidence)" -replace '\|', '\|'
    [void]$md.AppendLine("| $b | $($it.title) | $($it.verdict) | $ev |")
}
[void]$md.AppendLine()
[void]$md.AppendLine('`!` marks a blocking item. `ASK` means it cannot be read from the files; a person must answer it.')
[void]$md.AppendLine()

if ($openQuestions.Count -gt 0) {
    [void]$md.AppendLine('## Questions for the owner')
    [void]$md.AppendLine()
    [void]$md.AppendLine('Ask these before starting. Each one changes what the later steps are.')
    [void]$md.AppendLine()
    foreach ($q in $openQuestions) {
        $star = if ($q.blocking) { ' **(blocking)**' } else { '' }
        [void]$md.AppendLine("1. **$($q.id)**$star - $($q.question)")
    }
    [void]$md.AppendLine()
}

[void]$md.AppendLine('## The plan, in order')
[void]$md.AppendLine()
if ($steps.Count -eq 0) {
    [void]$md.AppendLine('Nothing to do: every item passes.')
}
$n = 0
foreach ($s in $steps) {
    $n++
    $needs = if (@($s.needs).Count -gt 0) { " - needs: $((@($s.needs)) -join ', ')" } else { '' }
    [void]$md.AppendLine("### $n. $($s.title)$needs")
    [void]$md.AppendLine()
    if ($s.why) { [void]$md.AppendLine("$($s.why)"); [void]$md.AppendLine() }
    foreach ($a in @($s.actions)) { [void]$md.AppendLine("- $a") }
    if (@($s.actions).Count -gt 0) { [void]$md.AppendLine() }
    [void]$md.AppendLine("**Done when:** $($s.doneWhen)")
    [void]$md.AppendLine()
}

[void]$md.AppendLine('## Handover')
[void]$md.AppendLine()
if ($HandoverSkill) {
    [void]$md.AppendLine("Once every blocking item is satisfied, the $tick$HandoverSkill$tick skill performs the adoption: it knows this team's hosts, ports, routing and CI. This plan is its input.")
}
else {
    [void]$md.AppendLine('This plan says WHAT must be true, not HOW your platform does it. The team-specific skill that owns hosts, ports, routing and CI performs the steps; give it this file.')
}
[void]$md.AppendLine()
[void]$md.AppendLine('Re-run Test-AppConformance.ps1 after each step. It is the same gate either way, so the plan cannot quietly drift from the standard.')

$mdPath = Join-Path $dir 'adoption-plan.md'
$md.ToString() | Set-Content -LiteralPath $mdPath -Encoding UTF8

Write-AdoptHeading "Adoption plan: $Name"
Write-Host "  $($steps.Count) steps, $(@($steps | Where-Object { $_.state -eq 'BLOCKED' }).Count) of them blocked by an earlier one"
Write-Host "  $($openQuestions.Count) open question(s), $(@($conf.blockingQuestions).Count) of them blocking"
foreach ($s in $steps) {
    $mark = if ($s.state -eq 'BLOCKED') { 'blocked' } else { 'ready  ' }
    Write-Host ("    {0}  {1}" -f $mark, $s.title)
}
Write-Host ""
Write-Host "  wrote $mdPath"
Write-Host "  wrote $jsonPath"
exit 0
