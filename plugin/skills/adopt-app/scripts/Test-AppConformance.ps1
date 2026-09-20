<#
.SYNOPSIS
    Phase 3. Measure the app against the adoption standard. Writes conformance.json.

.DESCRIPTION
    THREE VERDICTS, NOT TWO. Most checklists have PASS and FAIL, which forces a tool to
    answer questions it cannot answer - and a tool that guesses at "who owns this?" or
    "which branch is the truth?" produces a confident wrong answer that nobody rechecks.

      PASS  observed true, from the inventory or the profile.
      GAP   observed false. The evidence is named.
      ASK   NOT OBSERVABLE FROM FILES. A person must answer it.

    An unanswered ASK on a blocking item stops the adoption exactly as a GAP does. That is
    the point: the two apps this was built for each had questions only their owner could
    settle, and a checklist that lists them as notes at the bottom lets them be skipped.

    Record an answer with -Answer, and it is kept in answers.json for the next run:

        ./Test-AppConformance.ps1 -Name app -Answer owner="Team Payments, [name]"

    EXIT CODES
      0  every blocking item is PASS
      1  a blocking item is a GAP
      2  a blocking item is an unanswered ASK

.PARAMETER Answer
    One or more `item-id=answer` pairs. Any non-empty answer satisfies an ASK: the answer
    is the record, this script does not judge it.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Name,
    [string]$OutDir,
    [string[]]$Answer = @(),
    [string[]]$Waive = @(),
    [int]$UntrackedThresholdMB = 0
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'AdoptCommon.ps1')

$dir = Resolve-AdoptOutDir -Name $Name -OutDir $OutDir
$inv = Read-AdoptArtifact -Dir $dir -FileName 'inventory.json'
$prof = Read-AdoptArtifact -Dir $dir -FileName 'profile.json'
$cfg = Get-AdoptConfig
if ($UntrackedThresholdMB -le 0) { $UntrackedThresholdMB = [int]$cfg.untrackedThresholdMB }

# ---- answers, kept between runs ------------------------------------------------------
$answersPath = Join-Path $dir 'answers.json'
$answers = @{}
if (Test-Path -LiteralPath $answersPath) {
    $j = Get-Content -LiteralPath $answersPath -Raw | ConvertFrom-Json
    foreach ($p in $j.PSObject.Properties) { $answers[$p.Name] = $p.Value }
}
foreach ($a in $Answer) {
    $i = $a.IndexOf('=')
    if ($i -le 0) { Write-Error "-Answer needs the form item-id=answer, got '$a'"; exit 1 }
    $answers[$a.Substring(0, $i).Trim()] = $a.Substring($i + 1).Trim()
}
$answers | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $answersPath -Encoding UTF8

# ---- facts the checks read -----------------------------------------------------------
$isRepo = [bool]$inv.git.isRepo
$remotes = @()
if ($isRepo -and $inv.git.remotes) { $remotes = @($inv.git.remotes | ForEach-Object { $_.url }) }
# git could not be consulted, so nothing derived from it may be reported as a fact.
$gitUsable = (-not $isRepo) -or (Get-AdoptProp $inv.git 'gitAvailable' $false)
$folders = @($inv.size.folders)
$componentProfiles = @($prof.components | ForEach-Object { $_.profile })
$isBatchOnly = ($componentProfiles.Count -gt 0) -and (@($componentProfiles | Where-Object { $_ -notmatch 'batch' }).Count -eq 0)

$untrackedBig = @($folders | Where-Object { $_.git -eq 'untracked' -and $_.path -ne '.git' -and $_.mb -ge $UntrackedThresholdMB })
# Per FILE, from git itself - not "this folder is tracked, so all of its bytes are".
$trackedJunk = @()
foreach ($e in @($inv.excludableSummary)) {
    if (-not (Get-AdoptProp $e 'tracked' $false)) { continue }
    if ($e.category -eq 'log') { continue }
    $trackedJunk += $e
}
$ignoredHeavy = @($folders | Where-Object { $_.git -eq 'ignored' -and $_.mb -ge 100 })

# A folder the operator told the scan to skip was NOT examined. It is not empty and it is
# not clean - it is unknown. On the first real run, `-SkipFolder tools` hid a 16 GB runtime
# tree and "anything excluded can be got back" reported PASS, which is precisely the
# failure this skill exists to prevent. Coverage-dependent checks may not pass while any
# folder is unscanned.
$skipped = @($folders | Where-Object { $_.skipped })
$coverageNote = ''
if ($skipped.Count -gt 0) { $coverageNote = "NOT SCANNED: $((@($skipped | ForEach-Object { $_.path })) -join ', ') - unknown, not clean. " }
if (-not $gitUsable) { $coverageNote += 'git could not be run, so tracked-vs-ignored is unknown for every folder. ' }
function Limit-ByCoverage {
    param([string]$Verdict)
    if ($Verdict -eq 'PASS' -and ($script:skipped.Count -gt 0 -or -not $script:gitUsable)) { return 'ASK' }
    return $Verdict
}
$lockFiles = @($inv.manifests | Where-Object { $_.name -match '(?i)^(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|Pipfile\.lock|composer\.lock|Gemfile\.lock|Cargo\.lock|go\.sum)$' })
$envTemplates = @($inv.configFiles | Where-Object { $_ -match '(?i)[._-](example|sample|template|dist)$' -or $_ -match '(?i)\.env\.(example|sample|template)' })
$hasReadme = @($inv.docs | Where-Object { $_ -match '(?i)^readme' }).Count -gt 0
$hasAgentRules = @($inv.docs | Where-Object { $_ -match '(?i)^(agents|claude)\.md$' }).Count -gt 0
$runReg = $inv.runRegistrations
$runCount = 0
if ($runReg) { $runCount = @($runReg.services).Count + @($runReg.scheduledTasks).Count + @($runReg.webSites).Count }
$junctionsInTree = @($inv.reparsePoints | Where-Object { $_.path -notmatch '(?i)(^|[\\/])(node_modules|\.venv|venv|vendor)([\\/]|$)' })

$expectedRemote = $null
if (@($cfg.Keys) -contains 'expectedRemotePattern' -and "$($cfg.expectedRemotePattern)" -ne '') {
    $expectedRemote = "$($cfg.expectedRemotePattern)"
}



# ---- the standard --------------------------------------------------------------------
# Each item: id, title, blocking, and a verdict with evidence. `ask` items carry the
# question that has to reach a person.
$items = @()

function Add-Item {
    param([string]$Id, [string]$Title, [bool]$Blocking, [string]$Verdict, [string]$Evidence, [string]$Question = '', [string]$Fix = '')
    # Every key is initialised, including the ones only some items use. Under StrictMode a
    # missing key is an error, not a $null, so an item without an answer would throw the
    # moment the report tried to read one.
    $script:items += [ordered]@{
        id = $Id; title = $Title; blocking = $Blocking; verdict = $Verdict
        evidence = $Evidence; question = $Question; fix = $Fix
        answer = ''; waived = $false
    }
}

Add-Item 'git-repo' 'The source is in a git repository' $true `
    $(if ($isRepo) { 'PASS' } else { 'GAP' }) `
    $(if ($isRepo) { "$($inv.git.commits) commits, $($inv.git.localBranches) local branches" } else { 'no .git in the source folder' }) `
    '' 'Adoption starts by importing the folder as one commit. Decide first what must NOT be in that commit.'

if (-not $gitUsable) {
    Add-Item 'remote-on-team-host' 'The repository lives on the team''s host' $true 'ASK' `
        'there is a repository, but git could not be run where the scan happened, so its remotes were never read' `
        'Run `git remote -v` in that folder yourself: which host does this repository push to?'
}
elseif (-not $isRepo) {
    Add-Item 'remote-on-team-host' 'The repository lives on the team''s host' $true 'GAP' 'there is no repository yet' '' 'Create it after the content policy is settled, not before.'
}
elseif ($remotes.Count -eq 0) {
    Add-Item 'remote-on-team-host' 'The repository lives on the team''s host' $true 'GAP' `
        'no remote is configured - this folder is the ONLY copy of the history' '' `
        'Port it to the team host. Until then one disk failure is the whole project.'
}
elseif ($expectedRemote -and @($remotes | Where-Object { $_ -match $expectedRemote }).Count -eq 0) {
    Add-Item 'remote-on-team-host' 'The repository lives on the team''s host' $true 'GAP' `
        "remotes are $($remotes -join ', '), none matching '$expectedRemote'" '' `
        'A repository on a personal account is not a team asset. Re-home it, then archive the personal copy.'
}
else {
    Add-Item 'remote-on-team-host' 'The repository lives on the team''s host' $true 'PASS' ($remotes -join ', ')
}

# A branch name is not a verdict. With no remote and many branches, only a person knows.
#
# `$isRepo -and ...` used to short-circuit to false when there was NO repository, which made
# this item report PASS for an app that has no branches at all - the tidiest possible way to
# say nothing. It asks in every case except a repository with a remote and few branches.
$branchSettled = $isRepo -and $gitUsable -and $remotes.Count -gt 0 -and [int]$inv.git.localBranches -le 3
Add-Item 'canonical-branch' 'Which branch is the truth is written down' $true `
    $(if ($branchSettled) { 'PASS' } else { 'ASK' }) `
    $(if (-not $isRepo) { 'no repository yet, so the answer decides what the import commit becomes' }
      elseif (-not $gitUsable) { 'git could not be run where the scan happened' }
      else { "checked out: $($inv.git.branch); $($inv.git.localBranches) local, $($inv.git.remoteBranches) remote-tracking" }) `
    'Which branch is the canonical one, and may the others be deleted or archived?'

$sourceOnlyBad = ($trackedJunk.Count -gt 0) -or ($untrackedBig.Count -gt 0)
$so = @()
foreach ($t in $trackedJunk) { $so += "COMMITTED $($t.category): $($t.folder) ($($t.mb) MB)" }
foreach ($u in $untrackedBig) { $so += "NEITHER COMMITTED NOR IGNORED: $($u.path) ($($u.mb) MB)" }
Add-Item 'source-only' 'The repository holds source, not runtimes, data or dependencies' $true `
    $(if ($sourceOnlyBad) { 'GAP' } else { Limit-ByCoverage 'PASS' }) `
    $(if ($so.Count -gt 0) { "$coverageNote$($so -join '; ')" } else { "${coverageNote}nothing excludable is committed, and nothing large is unclassified" }) `
    '' 'Committed content needs a history rewrite, not a .gitignore line. Unclassified content needs a decision per folder: commit, ignore, or move out.'

$secretCount = @($inv.secretsSuspected).Count
Add-Item 'no-secrets' 'No credential is in the working tree' $true `
    $(if ($secretCount -eq 0) { 'PASS' } else { 'GAP' }) `
    $(if ($secretCount -eq 0) { 'the heuristics found none, which is not proof there are none' } else { "$secretCount suspected: $((@($inv.secretsSuspected | Select-Object -First 4 | ForEach-Object { $_.path })) -join ', ')" }) `
    '' 'Read every flagged file. A credential that was ever committed must be ROTATED, not only deleted - history keeps it.'

Add-Item 'config-separation' 'Configuration is outside the code, per environment' $false `
    $(if ($envTemplates.Count -gt 0) { 'PASS' } elseif (@($inv.configFiles).Count -eq 0) { 'ASK' } else { 'GAP' }) `
    $(if ($envTemplates.Count -gt 0) { "templates present: $($envTemplates -join ', ')" } else { "$(@($inv.configFiles).Count) config files, none of them a committed template" }) `
    'Where does each environment get its settings, and what supplies the secret values?'

Add-Item 'deps-pinned' 'Dependencies are pinned' $false `
    $(if ($lockFiles.Count -gt 0) { 'PASS' } else { 'GAP' }) `
    $(if ($lockFiles.Count -gt 0) { (@($lockFiles | ForEach-Object { $_.path }) -join ', ') } else { 'no lock file found' }) `
    '' 'Without a lock file the build is not reproducible, and a broken deploy cannot be told from a moved dependency.'

Add-Item 'tests' 'There is an automated test suite' $false `
    $(if ([int]$inv.tests.files -gt 0) { 'PASS' } else { 'GAP' }) `
    "$($inv.tests.files) test files; markers: $(if (@($inv.tests.markers).Count) { (@($inv.tests.markers) -join ', ') } else { 'none' })"

$ciCount = @($inv.ci).Count
Add-Item 'ci-build' 'CI builds and tests on every push' $false `
    $(if ($ciCount -gt 0) { 'PASS' } else { 'GAP' }) `
    $(if ($ciCount -gt 0) { (@($inv.ci) -join ', ') } else { 'no workflow or pipeline file found' })

Add-Item 'ci-deploy' 'Deployment is reproducible, not manual' $false `
    $(if ($ciCount -gt 0) { 'ASK' } else { 'GAP' }) `
    $(if ($ciCount -gt 0) { 'CI exists; whether it DEPLOYS cannot be read from the file list' } else { 'no CI at all' }) `
    'How is this deployed today, step by step, and who can do it?'

Add-Item 'runtime-manifest' 'Anything excluded from the repository can be got back' $false `
    $(if ($ignoredHeavy.Count -eq 0) { Limit-ByCoverage 'PASS' } else { 'ASK' }) `
    $(if ($ignoredHeavy.Count -eq 0) { "${coverageNote}nothing large is excluded among the folders that were scanned" } else { "$coverageNote" + "excluded and large: $((@($ignoredHeavy | ForEach-Object { "$($_.path) ($($_.mb) MB)" })) -join ', ')" }) `
    'For each excluded or unscanned folder: what installs or restores it, at which exact version?'

$healthCount = @($inv.healthSignals).Count
Add-Item 'health' 'There is a health signal that fails loudly' $false `
    $(if ($healthCount -gt 0) { 'PASS' } elseif ($isBatchOnly) { 'ASK' } else { 'GAP' }) `
    $(if ($healthCount -gt 0) { "$healthCount file(s) mention a health route or check" } else { 'no health route found' }) `
    $(if ($isBatchOnly) { 'A batch job has no endpoint. What is its success signal - exit code, an output artefact, a row written?' } else { '' }) `
    'A check that returns 200 whatever happens is not a health check. It must fail when the app is broken.'

Add-Item 'run-declared' 'How the app runs is declared and version-controlled' $true `
    $(if ($runCount -gt 0) { 'PASS' } else { 'ASK' }) `
    $(if ($runCount -gt 0) {
            # Name them. "1 service" invited the reader to assume it was the app's own; on
            # the first real run it was a database installed inside the app's folder.
            $names = @()
            foreach ($x in @($runReg.services)) { $names += "service $($x.name)" }
            foreach ($x in @($runReg.scheduledTasks)) { $names += "task $($x.name)" }
            foreach ($x in @($runReg.webSites)) { $names += "site $($x.name)" }
            ($names -join ', ') + ' - confirm each one actually runs THIS app'
        } else { 'nothing on the scanned host references this folder' }) `
    'Nothing on this host starts the app. What runs it today - on which machine, as which account, on what trigger?'

Add-Item 'rollback' 'There is a way back to the previous version' $false 'ASK' `
    'not observable from files' `
    'If a release is bad, what is the exact command or step that restores the previous one, and has it ever been run?'

Add-Item 'owner' 'The app has a named owner' $true `
    'ASK' 'not observable from files' `
    'Who owns this app - the person or team who decides changes and is called when it breaks?'

Add-Item 'data-recovery' 'State can be restored from a backup' $false `
    $(if ($ignoredHeavy.Count -eq 0 -and @($inv.excludableSummary | Where-Object { $_.category -eq 'db-data' }).Count -eq 0) { Limit-ByCoverage 'PASS' } else { 'ASK' }) `
    "${coverageNote}the repository carries schema and migrations; data comes from a backup" `
    'Where is the backup of this app''s data, how often is it taken, and when was a restore last tested?'

Add-Item 'docs-readme' 'A README says what it is and how to run it' $false `
    $(if ($hasReadme) { 'PASS' } else { 'GAP' }) `
    $(if ($hasReadme) { (@($inv.docs | Where-Object { $_ -match '(?i)^readme' }) -join ', ') } else { 'no README at the root' })

Add-Item 'agent-rules' 'A rules file the coding agents read' $false `
    $(if ($hasAgentRules) { 'PASS' } else { 'GAP' }) `
    $(if ($hasAgentRules) { (@($inv.docs | Where-Object { $_ -match '(?i)^(agents|claude)\.md$' }) -join ', ') } else { 'none' }) `
    '' 'Without it every agent re-derives the project rules, and each one derives them differently.'

Add-Item 'no-junctions' 'No junction or symlink inside the tree git manages' $false `
    $(if ($junctionsInTree.Count -eq 0) { 'PASS' } else { 'GAP' }) `
    $(if ($junctionsInTree.Count -eq 0) { 'none outside dependency folders' } else { "$($junctionsInTree.Count): $((@($junctionsInTree | Select-Object -First 3 | ForEach-Object { $_.path })) -join ', ')" }) `
    '' 'git''s recursive remove FOLLOWS a junction and deletes the target''s contents. Point at shared state with an absolute path instead.'

Add-Item 'profile' 'The stack is declared, not assumed' $true `
    $(if (@($prof.components).Count -gt 0) { 'PASS' } else { 'GAP' }) `
    $(if (@($prof.components).Count -gt 0) { (@($prof.components | ForEach-Object { "$($_.path)=$($_.profile)" }) -join ', ') } else { 'no component matched a profile' })

# ---- apply answers and waivers -------------------------------------------------------
foreach ($it in $items) {
    if ($it.verdict -eq 'ASK' -and $answers.ContainsKey($it.id) -and "$($answers[$it.id])".Trim() -ne '') {
        $it.verdict = 'ANSWERED'
        $it.answer = "$($answers[$it.id])"
    }
    if ($Waive -contains $it.id -and $it.verdict -ne 'PASS') {
        # A waiver is recorded as a waiver, never rewritten as a pass. The difference is
        # the whole value of the record six months later.
        $it.waived = $true
    }
}

$blockingBad = @($items | Where-Object { $_.blocking -and $_.verdict -eq 'GAP' -and -not $_.waived })
$blockingAsk = @($items | Where-Object { $_.blocking -and $_.verdict -eq 'ASK' -and -not $_.waived })

$report = [ordered]@{
    name      = $Name
    testedAt  = (Get-Date).ToUniversalTime().ToString('o')
    partialInventory = [bool]$inv.partial
    counts    = [ordered]@{
        pass     = @($items | Where-Object { $_.verdict -eq 'PASS' }).Count
        gap      = @($items | Where-Object { $_.verdict -eq 'GAP' }).Count
        ask      = @($items | Where-Object { $_.verdict -eq 'ASK' }).Count
        answered = @($items | Where-Object { $_.verdict -eq 'ANSWERED' }).Count
        waived   = @($items | Where-Object { $_.waived }).Count
    }
    blockingGaps = @($blockingBad | ForEach-Object { $_.id })
    blockingQuestions = @($blockingAsk | ForEach-Object { $_.id })
    items     = $items
}
$out = Write-AdoptArtifact -Dir $dir -FileName 'conformance.json' -Object $report

# ---- report --------------------------------------------------------------------------
Write-AdoptHeading "Conformance: $Name"
foreach ($it in $items) {
    $mark = switch ($it.verdict) {
        'PASS' { 'PASS ' }
        'GAP' { 'GAP  ' }
        'ASK' { 'ASK  ' }
        'ANSWERED' { 'ANSW ' }
        default { '???  ' }
    }
    $colour = switch ($it.verdict) {
        'PASS' { 'Green' }
        'GAP' { if ($it.blocking) { 'Red' } else { 'Yellow' } }
        'ASK' { if ($it.blocking) { 'Red' } else { 'Yellow' } }
        default { 'Gray' }
    }
    $block = if ($it.blocking) { '*' } else { ' ' }
    $waiv = if ($it.waived) { '  [WAIVED]' } else { '' }
    Write-Host ("  {0}{1} {2,-22} {3}{4}" -f $mark, $block, $it.id, $it.title, $waiv) -ForegroundColor $colour
    if ($it.evidence) { Write-Host "         $($it.evidence)" -ForegroundColor DarkGray }
    if ($it.verdict -eq 'ASK' -and $it.question) { Write-Host "         Q: $($it.question)" -ForegroundColor DarkYellow }
    if ($it.verdict -eq 'ANSWERED') { Write-Host "         A: $($it.answer)" -ForegroundColor DarkGray }
}

Write-Host ""
Write-Host "  * = blocking. $($report.counts.pass) pass, $($report.counts.gap) gaps, $($report.counts.ask) open questions, $($report.counts.answered) answered, $($report.counts.waived) waived."
if ($report.partialInventory) {
    Write-Host "  The inventory was PARTIAL, so every 'nothing found' above is 'nothing found so far'." -ForegroundColor Yellow
}
Write-Host "  wrote $out"

if ($blockingBad.Count -gt 0) {
    Write-Host ""
    Write-Host "NOT READY TO ADOPT - blocking gaps: $((@($blockingBad | ForEach-Object { $_.id })) -join ', ')" -ForegroundColor Red
    exit 1
}
if ($blockingAsk.Count -gt 0) {
    Write-Host ""
    Write-Host "NOT READY TO ADOPT - these blocking questions have no answer yet:" -ForegroundColor Red
    foreach ($q in $blockingAsk) { Write-Host "  [$($q.id)] $($q.question)" -ForegroundColor Red }
    Write-Host "Record each with -Answer $($blockingAsk[0].id)=`"...`" once the owner has answered." -ForegroundColor Red
    exit 2
}

Write-Host ""
Write-Host "Every blocking item is satisfied." -ForegroundColor Green
exit 0
