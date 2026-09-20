<#
.SYNOPSIS
    Shared helpers for the adopt-app skill. Dot-source this file.

.DESCRIPTION
    Two rules shape everything here.

    1. NOTHING IN THIS SKILL EXECUTES THE APP. An app that was never bootstrapped is
       usually the only copy of something that is running in production. We read files
       and file metadata. We never run an entry point, an installer, a migration or a
       build, and we never write inside the source folder.

    2. A PARTIAL ANSWER MUST NOT READ AS A CLEAN ANSWER. The scan walks trees that can
       be hundreds of gigabytes over a network share. When it runs out of budget or is
       denied access it says so, reports a MINIMUM size rather than a wrong total, and
       the caller fails unless the operator accepted the partial scan.

    The scan itself is a single scriptblock so that one implementation serves both a
    local folder and a remote box over WinRM. That block must stay Windows PowerShell
    5.1 compatible: no ternary, no null-coalescing, no `Join-Path` with three arguments,
    no `-AsHashtable`. It is ASCII only.
#>

Set-StrictMode -Version 2.0

# Every key here is READ by something. An earlier version also carried `contentPolicy` and a
# `blockingItems` list that no script ever consulted, and the list had drifted out of step
# with the real blocking set - so a project could set it, see no effect, and never find out.
# Config that does nothing is worse than no config: it is a promise the code does not keep.
$script:AdoptDefaultConfig = [ordered]@{
    # Read by Resolve-AdoptOutDir.
    outDir        = '.caddis/adopt'
    # Read by Get-AppInventory.ps1 when -FileBudget is not passed.
    fileBudget    = 20000
    # Read by Get-AppInventory.ps1 when -SkipFolder is not passed.
    skipFolders   = @()
    # Default for Invoke-AdoptScan -SkipPattern: folders whose contents are never classified.
    skipPattern   = '(?i)[\\/](\.git|node_modules|\.venv|venv|__pycache__|\.mypy_cache|\.pytest_cache|\.tox|dist|build|target|bin|obj|vendor|packages|\.terraform|\.gradle|\.next|\.nuxt|coverage)([\\/]|$)'
    # Read by Test-AppConformance.ps1: the regex that says what "the team's host" means.
    # Empty means unknown, and the remote check then says so instead of guessing.
    expectedRemotePattern = ''
    # Read by Test-AppConformance.ps1: a folder neither committed nor ignored that is at
    # least this big is a finding.
    untrackedThresholdMB = 10
}

# Files whose NAME alone says "this is a credential". Matching the name is enough to flag.
$script:AdoptSecretNamePattern = '(?i)(^|[\\/])(\.env(\.[a-z0-9_-]+)?|.*\.pem|.*\.key|.*\.pfx|.*\.p12|.*\.jks|.*\.keystore|id_rsa|id_ed25519|.*\.ppk|credentials|\.npmrc|\.pypirc|\.netrc|secrets?\.(json|ya?ml|ini|toml|txt)|.*[._-]secrets?\.(json|ya?ml|ini|toml)|appsettings\.(Production|Prod)\.json)$'

# A file whose whole purpose is to show the SHAPE of a secret file. `.env.example` is
# committed on purpose in most repositories; flagging it teaches the reader to skim.
$script:AdoptSecretNameExemptPattern = '(?i)[._-](example|sample|template|dist|placeholder|default)$'

# A container that may hold a private key or may hold a public certificate. Which one it
# is decides whether it is a finding, and only the content says.
$script:AdoptKeyContainerPattern = '(?i)\.(pem|key)$'

# Lines whose SHAPE says "this is a credential value". Matched ONE LINE AT A TIME, because
# a whole-file regex cannot tell code from the prose in a comment about code.
#
# Precision is not a nicety here. The first version flagged three lines in a scripts folder
# and all three were noise: `$Token = Read-Host -AsSecureString ...`, and two sentences in
# comments that happened to contain "token=True". A check that cries wolf on every script
# gets switched off, which is the same failure as a check that cannot fire - approached
# from the other side.
# The value is captured as ONE token - a quoted string or a run of non-delimiter
# characters - never as "the rest of the line". A greedy `.*$` swallowed the remainder of
# every statement it matched, so `Token = '?'; Verdict = 'NO CHECKOUT' }` arrived as a
# 30-character "credential" and passed every length test.
$script:AdoptValueToken = '(?<val>"[^"\r\n]*"|''[^''\r\n]*''|[^\s,;)\]}]+)'

$script:AdoptSecretContentPatterns = @(
    '(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|client[_-]?secret|connection[_-]?string)\b\s*[:=]{1,2}>?\s*' + $script:AdoptValueToken
    # SimpleSAMLphp and friends write a user list as 'user:password' => array(...). The key
    # must itself carry the `user:pass` shape; without that colon this matched EVERY PHP
    # array literal, and a vendored ITSM tree produced findings like key 'css_classes'.
    '(?i)''[^'':\r\n]{2,40}:(?<val>[^''\r\n]{4,60})''\s*=>\s*(array|\[)'
    '(?<val>-----BEGIN [A-Z ]*PRIVATE KEY-----)'
    '(?i)\b(?<val>gh[pousr]_[A-Za-z0-9]{16,}|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{20,})\b'
    '(?i)(server|data source)\s*=\s*[^;]+;[^\r\n]*\b(password|pwd)\s*=\s*' + $script:AdoptValueToken
)

# A line that starts a comment. Prose about a credential is not a credential.
$script:AdoptCommentLinePattern = '^\s*(#|//|--|;|\*|<#|/\*|"""|'''''')'

# A value that is NOT a literal secret: a variable, an environment lookup, a prompt, a
# boolean, or a placeholder somebody left for a real value.
$script:AdoptNonLiteralValuePattern = '(?i)^\s*(\$|%|@|\{|<|\(|`|\\|env[:.]|os\.environ|getenv|process\.env|secrets\.|vault|Read-Host|Get-Credential|ConvertTo-SecureString|true|false|null|none|nil|""|''''|\[|-|\.\.\.|xxx+|changeme|your[-_]|replace[-_]?me|example|placeholder|todo|fixme|\*{3,})' +
# A TYPE, not a value. `password: string` in an interface and `secret: string` in a
# function signature are declarations; a scan that reads them as credentials reports a
# finding on every typed codebase.
'|(?i)^\s*(string|number|boolean|int|integer|bool|str|text|varchar|char|any|unknown|object|array|bytes|float|double|decimal|uuid|date|datetime)\s*[;,)\]}]?\s*$'

# A value that REFERS to a secret rather than being one. `${{ secrets.X }}`, `%VAR%`,
# `{token}` and a regex fragment are all references, wherever they appear in the value.
#
# A value containing `(` is a call - `readFileSync(...)`, `this.secrets.resolve(...)` - and
# a dotted identifier is a lookup - `config.ITOBFF_DB_PASSWORD`. Both READ a credential;
# neither IS one.
$script:AdoptReferenceValuePattern = '(\$\{|\{\{|\\[sdwbn]|%[A-Za-z_][A-Za-z0-9_]*%|\{[A-Za-z_][A-Za-z0-9_]*\}|\(|^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_])'

# Below this length a value cannot be a real credential, and above the noise floor it is
# almost always a flag, an index or a single-letter test fixture.
$script:AdoptMinSecretLength = 6

# Content that belongs on a machine, not in a repository. Category drives the advice, so
# keep them separate rather than folding them into one "junk" bucket.
$script:AdoptExcludablePatterns = @(
    @{ category = 'dependency'; pattern = '(?i)(^|[\\/])(node_modules|vendor|\.venv|venv|site-packages|packages|bower_components|\.gradle|\.m2)([\\/]|$)' }
    @{ category = 'runtime';    pattern = '(?i)(^|[\\/])(tools|runtimes?|jdk[0-9._-]*|jre[0-9._-]*|php[0-9._-]*|python[0-9._-]*|node-v[0-9]|mariadb[0-9._-]*|mysql[0-9._-]*|apache[0-9._-]*|nginx[0-9._-]*|tomcat[0-9._-]*)([\\/]|$)' }
    @{ category = 'build-output'; pattern = '(?i)(^|[\\/])(dist|build|out|target|bin|obj|\.next|\.nuxt|publish)([\\/]|$)' }
    @{ category = 'cache';      pattern = '(?i)(^|[\\/])(__pycache__|\.mypy_cache|\.ruff_cache|\.pytest_cache|\.tox|\.cache|\.parcel-cache|\.eslintcache|htmlcov|coverage)([\\/]|$)' }
    @{ category = 'db-data';    pattern = '(?i)(\.mdf|\.ldf|\.ibd|\.frm|\.myd|\.myi|\.sqlite3?|\.db3|[\\/]data[\\/].*\.(ib_logfile[0-9]+|ibdata[0-9]+))$' }
    @{ category = 'archive';    pattern = '(?i)\.(zip|7z|rar|tar|tgz|gz|bz2|xz|iso|msi|exe|dll|so|dylib|jar|war|ear|nupkg|whl)$' }
    @{ category = 'data-export'; pattern = '(?i)\.(csv|tsv|parquet|avro|xlsx?|bak|dmp|dump|sql\.gz|pdf|afp|ps)$' }
    @{ category = 'media';      pattern = '(?i)\.(mp4|mov|avi|mkv|wav|mp3|psd|ai|sketch)$' }
    @{ category = 'log';        pattern = '(?i)([\\/]logs?[\\/]|\.log(\.[0-9]+)?$)' }
)

# --------------------------------------------------------------------------------------
# The scan. Runs locally or inside Invoke-Command. Windows PowerShell 5.1 compatible.
# --------------------------------------------------------------------------------------
$script:AdoptScanBlock = {
    param($Path, $FileBudget, $SkipPattern, $SecretNamePattern, $SecretContentPatterns, $ExcludableSpecs, $MaxProbeBytes, $CommentLinePattern, $NonLiteralValuePattern, $ProbeBudget, $SkipFolders, $ReferenceValuePattern, $MinSecretLength, $SecretNameExemptPattern, $KeyContainerPattern, $DetectPathCap)

    $ErrorActionPreference = 'Continue'

    $result = @{
        path          = $Path
        exists        = $false
        partial       = $false
        partialReason = @()
        folders       = @()
        manifests     = @()
        entryPoints   = @()
        configFiles   = @()
        secretFiles   = @()
        certificates  = @()
        paths         = @()
        excludable    = @()
        reparse       = @()
        testFiles     = 0
        testMarkers   = @()
        ciFiles       = @()
        docFiles      = @()
        healthHits    = @()
        totalFiles    = 0
        totalMB       = 0.0
        probed        = 0
        git           = @{ isRepo = $false }
    }
    $probeCandidates = New-Object System.Collections.ArrayList
    $keyContainers = New-Object System.Collections.ArrayList
    $detectPaths = New-Object System.Collections.ArrayList

    # Files whose CONTENT is worth reading. A credential hides in application source at
    # least as often as in a config file: the first version of this scan probed only
    # manifests and config, and walked straight past an API key assigned in settings.py.
    $textExtensions = @('.py', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.php', '.rb', '.go',
        '.java', '.kt', '.scala', '.cs', '.vb', '.ps1', '.psm1', '.psd1', '.sh', '.bash', '.bat',
        '.cmd', '.sql', '.json', '.yml', '.yaml', '.xml', '.ini', '.cfg', '.conf', '.config',
        '.toml', '.env', '.properties', '.txt', '.md', '.tf', '.tfvars', '.gradle', '.pl', '.r',
        '.aspx', '.jsp', '.html', '.htm', '.css', '.scss', '.tpl', '.twig', '.erb', '.j2')

    if (-not (Test-Path -LiteralPath $Path)) {
        $result.partialReason += "path not found: $Path"
        return $result
    }
    $result.exists = $true
    $root = (Resolve-Path -LiteralPath $Path).ProviderPath.TrimEnd('\')

    # ---- git state, read only -------------------------------------------------------
    # Is git even here? On a remote box it often is not, and without this test every git
    # call returns nothing, every exit code is non-zero, and the folder classifier reported
    # ALL TWELVE folders of a fully tracked repository as "neither committed nor ignored" -
    # the most alarming verdict it has, produced entirely by a missing executable.
    #
    # `git --version` is not enough. git also refuses a repository whose files belong to
    # another account - "detected dubious ownership" - which is the normal case for a folder
    # on a server reached over WinRM. Every command then exits non-zero, and the scan
    # reported a repository with no remotes, no commits and no tracked folders at all.
    # `-c safe.directory=*` is scoped to these read-only commands and changes nothing on disk.
    $gitAvailable = $false
    $gitError = ''
    & git --version 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { $gitError = 'git is not installed where the scan ran' }
    else {
        $probe = & git -c safe.directory=* -C $root rev-parse --is-inside-work-tree 2>&1
        if ($LASTEXITCODE -eq 0) { $gitAvailable = $true }
        else { $gitError = "git cannot read this repository: $(@($probe) -join ' ')" }
    }

    if (Test-Path -LiteralPath (Join-Path $root '.git')) {
        # Every field is initialised and the record is attached NOW, so a caller never reads
        # a key that is missing because one git call did not run.
        $g = @{ isRepo = $true; gitAvailable = $gitAvailable; gitError = $gitError; commits = $null; branch = $null
                localBranches = 0; remoteBranches = 0; tags = 0; dirtyFiles = $null
                remotes = @(); upstream = $null; unpushed = $null; lastCommit = $null }
        $result.git = $g
        if (-not $gitAvailable) {
            $result.partial = $true
            $result.partialReason += "$gitError - so branches, remotes and which folders are tracked could not be read"
        }
    }
    if ((Test-Path -LiteralPath (Join-Path $root '.git')) -and $gitAvailable) {
        $runGit = {
            param($argLine)
            $out = & git -c safe.directory=* -C $root -c core.longpaths=true @argLine 2>&1
            if ($LASTEXITCODE -ne 0) { return $null }
            return $out
        }
        $g.remotes = @()
        $r = & $runGit @('remote', '-v')
        if ($r) { foreach ($line in @($r)) { if ("$line" -match '^(\S+)\s+(\S+)\s+\(fetch\)') { $g.remotes += @{ name = $Matches[1]; url = $Matches[2] } } } }
        $b = & $runGit @('rev-parse', '--abbrev-ref', 'HEAD'); if ($b) { $g.branch = "$b" }
        $lb = & $runGit @('for-each-ref', '--format=%(refname:short)', 'refs/heads'); $g.localBranches = @($lb | Where-Object { "$_" -ne '' }).Count
        $rb = & $runGit @('for-each-ref', '--format=%(refname:short)', 'refs/remotes'); $g.remoteBranches = @($rb | Where-Object { "$_" -ne '' }).Count
        $tg = & $runGit @('tag', '--list'); $g.tags = @($tg | Where-Object { "$_" -ne '' }).Count
        $st = & $runGit @('status', '--porcelain'); $g.dirtyFiles = @($st | Where-Object { "$_" -ne '' }).Count
        $lc = & $runGit @('log', '-1', '--format=%H|%an|%aI|%s')
        if ($lc) {
            $parts = "$lc" -split '\|', 4
            $g.lastCommit = @{ sha = $parts[0]; author = $parts[1]; date = $parts[2]; subject = $parts[3] }
        }
        $cc = & $runGit @('rev-list', '--count', 'HEAD'); if ($cc) { $g.commits = [int]"$cc" }
        $up = & $runGit @('rev-parse', '--abbrev-ref', '@{upstream}')
        if ($up) {
            $g.upstream = "$up"
            $ahead = & $runGit @('rev-list', '--count', "$up..HEAD")
            if ($ahead) { $g.unpushed = [int]"$ahead" }
        }
        else { $g.upstream = $null; $g.unpushed = $null }
    }

    # ---- one bounded walk per top-level folder --------------------------------------
    $tops = @()
    try { $tops = @(Get-ChildItem -LiteralPath $root -Force -ErrorAction Stop | Where-Object { $_.PSIsContainer }) }
    catch { $result.partial = $true; $result.partialReason += "cannot list $root : $($_.Exception.Message)" }

    $rootFiles = @()
    try { $rootFiles = @(Get-ChildItem -LiteralPath $root -Force -File -ErrorAction Stop) }
    catch { $result.partial = $true; $result.partialReason += "cannot list files in $root : $($_.Exception.Message)" }

    # Lock files belong here too. Without them the "dependencies are pinned" check had no
    # evidence it could ever find, so it reported a GAP for every npm project in the world
    # - a check that cannot pass is as useless as one that cannot fail.
    $manifestNames = @('pyproject.toml', 'requirements.txt', 'setup.py', 'setup.cfg', 'Pipfile',
        'package.json', 'composer.json', 'pom.xml', 'build.gradle', 'build.gradle.kts', 'Gemfile',
        'go.mod', 'Cargo.toml', 'Dockerfile', 'docker-compose.yml', 'docker-compose.yaml', 'Makefile',
        'poetry.lock', 'Pipfile.lock', 'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
        'composer.lock', 'Gemfile.lock', 'Cargo.lock', 'go.sum')
    $entryNames = @('main.py', 'app.py', 'wsgi.py', 'asgi.py', 'manage.py', '__main__.py', 'server.js',
        'index.js', 'server.ts', 'index.php', 'Program.cs', 'Application.java', 'Procfile', 'run.sh', 'start.sh')
    $configGlobs = '(?i)^(\.env.*|.*\.ini|.*\.cfg|.*\.conf|.*\.toml|.*\.ya?ml|appsettings.*\.json|web\.config|settings\.json|config\.json)$'
    $docNames = '(?i)^(readme(\..+)?|agents\.md|claude\.md|contributing\.md|changelog\.md)$'
    $testMarkerNames = '(?i)^(pytest\.ini|tox\.ini|conftest\.py|jest\.config\.[cm]?[jt]s|vitest\.config\.[cm]?[jt]s|phpunit\.xml(\.dist)?|karma\.conf\.js|\.mocharc\..+)$'

    $classify = {
        param($file, $rel)

        if ($manifestNames -contains $file.Name) { $result.manifests += @{ path = $rel; name = $file.Name } }
        if ($entryNames -contains $file.Name) { $result.entryPoints += @{ path = $rel; why = "named $($file.Name)" } }
        if ($file.Extension -match '(?i)^\.(ps1|bat|cmd|sh)$' -and $rel -notmatch '[\\/]') {
            $result.entryPoints += @{ path = $rel; why = 'top-level script' }
        }
        if ($file.Name -match $testMarkerNames) { $result.testMarkers += $rel }
        if ($file.Name -match $docNames) { $result.docFiles += $rel }
        if ($rel -match '(?i)^\.(github|gitea|forgejo)[\\/]workflows[\\/]' -or
            $file.Name -match '(?i)^(\.gitlab-ci\.yml|Jenkinsfile|azure-pipelines\.ya?ml|\.travis\.yml|appveyor\.yml|bitbucket-pipelines\.yml)$') {
            $result.ciFiles += $rel
        }
        if ($rel -match '(?i)(^|[\\/])(tests?|spec|__tests__)[\\/]' -or $file.Name -match '(?i)(^test_.*\.py$|_test\.py$|\.test\.[jt]sx?$|\.spec\.[jt]sx?$|Test\.php$|Tests?\.cs$)') {
            $result.testFiles++
        }
        if ($file.Name -match $configGlobs -and $file.Length -lt 512KB) { $result.configFiles += $rel }
        $baseName = [System.IO.Path]::GetFileNameWithoutExtension($file.Name)
        if ($rel -match $SecretNamePattern -and $baseName -notmatch $SecretNameExemptPattern -and $file.Name -notmatch $SecretNameExemptPattern) {
            if ($file.Name -match $KeyContainerPattern) {
                # A .pem is a container, not a verdict. A public certificate chain is not a
                # finding; a private key is. Deciding by extension reported four public CA
                # certificates as credentials, which is how a real one gets skimmed past.
                [void]$keyContainers.Add($rel)
            }
            else { $result.secretFiles += @{ path = $rel; why = 'name looks like a credential file' } }
        }

        # A shallow index of ordinary file paths, for profile detection. Without it a rule
        # can only see manifests and config: a front end whose evidence is `index.html`
        # matched nothing at all, and the component was silently missing from the plan.
        # Shallow paths are ALWAYS kept. A single global cap is consumed by whichever tree
        # the walk happens to reach first: on a real app it filled up before reaching the
        # front end at all, so the front end was missing from the plan and nothing said so.
        $depth = @($rel -split '[\\/]').Count
        if ($depth -le 2) { [void]$detectPaths.Add($rel) }
        elseif ($depth -le 4 -and $detectPaths.Count -lt $DetectPathCap) { [void]$detectPaths.Add($rel) }

        $ext = "$($file.Extension)".ToLowerInvariant()
        if (($textExtensions -contains $ext -or $file.Name -match '(?i)^(\.env.*|dockerfile|makefile|procfile)$') -and $file.Length -le $MaxProbeBytes) {
            [void]$probeCandidates.Add($rel)
        }

        foreach ($spec in $ExcludableSpecs) {
            if ($rel -match $spec.pattern) {
                $result.excludable += @{ path = $rel; category = $spec.category; bytes = $file.Length }
                break
            }
        }
    }

    $walk = {
        param($dir, $label)

        $seen = 0
        $bytes = [long]0
        $truncated = $false
        $denied = $false
        $stack = New-Object System.Collections.Stack
        $stack.Push($dir)

        while ($stack.Count -gt 0) {
            $cur = $stack.Pop()
            $kids = $null
            try { $kids = @(Get-ChildItem -LiteralPath $cur -Force -ErrorAction Stop) }
            catch { $denied = $true; continue }

            foreach ($k in $kids) {
                # Never follow a reparse point. A junction inside a tree a tool manages is a
                # live data-loss hazard, so record it and do not descend into it.
                if ($k.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                    $rp = $k.FullName
                    if ($rp.Length -gt $root.Length) { $rp = $rp.Substring($root.Length + 1) }
                    $result.reparse += @{ path = $rp; kind = "$($k.Attributes)" }
                    continue
                }
                if ($k.PSIsContainer) {
                    $stack.Push($k.FullName)
                    continue
                }

                $seen++
                $bytes += $k.Length
                $rel = $k.FullName
                if ($rel.Length -gt $root.Length) { $rel = $rel.Substring($root.Length + 1) }

                if ($rel -notmatch $SkipPattern) { & $classify $k $rel }
                else {
                    foreach ($spec in $ExcludableSpecs) {
                        if ($rel -match $spec.pattern) { $result.excludable += @{ path = $rel; category = $spec.category; bytes = $k.Length }; break }
                    }
                }

                if ($seen -ge $FileBudget) { $truncated = $true; break }
            }
            if ($truncated) { break }
        }

        return @{ label = $label; files = $seen; bytes = $bytes; truncated = $truncated; denied = $denied }
    }

    foreach ($f in $rootFiles) {
        $result.totalFiles++
        $result.totalMB += [math]::Round($f.Length / 1MB, 4)
        & $classify $f $f.Name
    }

    foreach ($t in $tops) {
        if ($t.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            $result.reparse += @{ path = $t.Name; kind = "$($t.Attributes)" }
            continue
        }
        if ($SkipFolders -contains $t.Name) {
            $result.folders += @{ path = $t.Name; files = 0; mb = 0; truncated = $false; denied = $false; skipped = $true; git = 'not-scanned' }
            continue
        }
        $w = & $walk $t.FullName $t.Name

        # Three states, and only git can tell them apart. The dangerous one is UNTRACKED:
        # a folder that is neither committed nor ignored is one `git add -A` away from
        # being in the repository for ever. A real app had 7.6 GB sitting in that state.
        $gitState = 'no-repo'
        if ($result.git.isRepo -and -not $gitAvailable) { $gitState = 'unknown' }
        elseif ($result.git.isRepo) {
            & git -c safe.directory=* -C $root check-ignore -q -- "$($t.Name)/" 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) { $gitState = 'ignored' }
            else {
                # Collect into an array, never `| Select-Object -First 1`. Select stops the
                # pipeline early, which leaves $LASTEXITCODE at 1 even though git succeeded,
                # so the exit-code test below failed for EVERY folder and a fully tracked
                # repository was reported as entirely untracked. A wrong verdict that looks
                # like a finding is worse than no verdict.
                $tracked = @(& git -c safe.directory=* -C $root ls-files -- "$($t.Name)/" 2>&1)
                if ($LASTEXITCODE -eq 0 -and $tracked.Count -gt 0 -and "$($tracked[0])" -ne '') { $gitState = 'tracked' }
                else { $gitState = 'untracked' }
            }
        }

        $entry = @{
            path      = $t.Name
            files     = $w.files
            mb        = [math]::Round($w.bytes / 1MB, 2)
            truncated = $w.truncated
            denied    = $w.denied
            skipped   = $false
            git       = $gitState
        }
        $result.folders += $entry
        $result.totalFiles += $w.files
        $result.totalMB += $entry.mb
        if ($w.truncated) {
            $result.partial = $true
            $result.partialReason += "$($t.Name): stopped after $($w.files) files (budget $FileBudget); its size is AT LEAST $($entry.mb) MB"
        }
        if ($w.denied) {
            $result.partial = $true
            $result.partialReason += "$($t.Name): access denied to at least one subfolder; its size is AT LEAST $($entry.mb) MB"
        }
    }
    $result.totalMB = [math]::Round($result.totalMB, 2)
    $result.paths = @($detectPaths)
    if ($detectPaths.Count -ge $DetectPathCap) {
        $result.partial = $true
        $result.partialReason += "path index: reached the cap of $DetectPathCap shallow paths, so profile detection sees only part of the tree"
    }

    # ---- key containers: private key, or public certificate? ------------------------
    foreach ($rel in @($keyContainers)) {
        $full = Join-Path $root $rel
        if (-not (Test-Path -LiteralPath $full)) { continue }
        $fi = Get-Item -LiteralPath $full -Force -ErrorAction SilentlyContinue
        if (-not $fi) { continue }
        # An empty file holds nothing, and saying "unreadable - check it by hand" about a
        # zero-byte placeholder sends someone to look at nothing.
        if ($fi.Length -eq 0) { continue }
        if ($fi.Length -gt $MaxProbeBytes) {
            $result.secretFiles += @{ path = $rel; why = 'key container, too large to read - check it by hand' }
            continue
        }
        $body = $null
        try { $body = Get-Content -LiteralPath $full -Raw -ErrorAction Stop } catch { }
        if ($null -eq $body) {
            $result.secretFiles += @{ path = $rel; why = 'key container, unreadable - check it by hand' }
        }
        elseif ($body -match 'PRIVATE KEY') {
            $result.secretFiles += @{ path = $rel; why = 'holds a PRIVATE KEY' }
        }
        else {
            $result.certificates += $rel
        }
    }

    # ---- content probes -------------------------------------------------------------
    $probe = @($probeCandidates | Sort-Object -Unique)
    if ($probe.Count -gt $ProbeBudget) {
        $result.partial = $true
        $result.partialReason += "content probe: $($probe.Count) text files found, only the first $ProbeBudget were read for credentials and health signals"
        $probe = @($probe | Select-Object -First $ProbeBudget)
    }
    $result.probed = $probe.Count

    foreach ($rel in $probe) {
        $full = Join-Path $root $rel
        if (-not (Test-Path -LiteralPath $full)) { continue }
        $fi = Get-Item -LiteralPath $full -Force -ErrorAction SilentlyContinue
        if (-not $fi -or $fi.Length -gt $MaxProbeBytes) { continue }
        $lines = $null
        try { $lines = @(Get-Content -LiteralPath $full -ErrorAction Stop) } catch { continue }
        if ($lines.Count -eq 0) { continue }

        $found = $false
        for ($i = 0; $i -lt $lines.Count -and -not $found; $i++) {
            $line = "$($lines[$i])"
            if ($line -match $CommentLinePattern) { continue }
            foreach ($p in $SecretContentPatterns) {
                $m = [regex]::Match($line, $p)
                if (-not $m.Success) { continue }
                $val = "$($m.Groups['val'].Value)".Trim().Trim('"', "'")
                if ($val.Length -lt $MinSecretLength) { continue }
                if ($val -match $NonLiteralValuePattern) { continue }
                if ($val -match $ReferenceValuePattern) { continue }
                # The opening of a template reference sits BEFORE the key, not inside the
                # value: `{{SECRET:bff-user}}` yields the value `bff-user`, which passes
                # every test above. Look back at the real text - with backslashes removed,
                # because in a regex literal the same reference is written `\{\{SECRET:...`
                # and a look-back that keeps the escaping sees `{\{` and misses it. That is
                # exactly how 20 files of migration scripts were reported as credentials.
                $lookBack = 0
                if ($m.Index -gt 6) { $lookBack = $m.Index - 6 }
                $before = $line.Substring($lookBack, $m.Index - $lookBack + 1).Replace('\', '')
                if ($before -match '(\{\{|\$\{|%)') { continue }
                # A value that ends in a backslash is part of a regular expression.
                if ($val.EndsWith('\')) { continue }
                # Three or more words is a sentence, not a credential. A quoted string of
                # prose - "LocalMachine\My store, exportable=false policy observed" - is
                # captured whole by the quoted alternative and passes every other test.
                if (@($val -split '\s+' | Where-Object { $_ -ne '' }).Count -ge 3) { continue }
                # The VALUE never leaves the machine in the report: only the file, the line
                # and the key name. A report is a file, and a file gets copied around.
                $keyName = ($m.Value -split '[:=]', 2)[0].Trim()
                if ($keyName.Length -gt 60) { $keyName = $keyName.Substring(0, 60) }
                $result.secretFiles += @{ path = $rel; why = 'value looks like a credential'; line = ($i + 1); key = $keyName }
                $found = $true
                break
            }
        }

        foreach ($line in $lines) {
            if ("$line" -match '(?i)(/health\b|/healthz\b|/api/health\b|healthcheck)') {
                $result.healthHits += @{ path = $rel; signal = 'health route or check' }
                break
            }
        }
    }

    return $result
}

# --------------------------------------------------------------------------------------
function Get-AdoptConfig {
    param([string]$RepoRoot = (Get-Location).Path)

    $cfg = [ordered]@{}
    foreach ($k in $script:AdoptDefaultConfig.Keys) { $cfg[$k] = $script:AdoptDefaultConfig[$k] }

    $path = $env:ADOPT_APP_CONFIG
    if (-not $path) { $path = Join-Path $RepoRoot '.caddis/adopt-app.json' }
    if (Test-Path -LiteralPath $path) {
        $json = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
        foreach ($p in $json.PSObject.Properties) { $cfg[$p.Name] = $p.Value }
        $cfg['_configPath'] = (Resolve-Path -LiteralPath $path).ProviderPath
    }
    else { $cfg['_configPath'] = $null }
    return $cfg
}

function Resolve-AdoptOutDir {
    param([Parameter(Mandatory)][string]$Name, [string]$OutDir, [string]$RepoRoot = (Get-Location).Path)

    if (-not $OutDir) {
        $cfg = Get-AdoptConfig -RepoRoot $RepoRoot
        $OutDir = Join-Path $RepoRoot $cfg.outDir
    }
    $dir = Join-Path $OutDir $Name
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    return (Resolve-Path -LiteralPath $dir).ProviderPath
}

function Write-AdoptArtifact {
    param([Parameter(Mandatory)][string]$Dir, [Parameter(Mandatory)][string]$FileName, [Parameter(Mandatory)]$Object)
    $p = Join-Path $Dir $FileName
    $Object | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $p -Encoding UTF8
    return $p
}

function Read-AdoptArtifact {
    param([Parameter(Mandatory)][string]$Dir, [Parameter(Mandatory)][string]$FileName)
    $p = Join-Path $Dir $FileName
    if (-not (Test-Path -LiteralPath $p)) {
        throw "No $FileName in $Dir. Run the earlier phase first (see the skill's phase table)."
    }
    return Get-Content -LiteralPath $p -Raw | ConvertFrom-Json
}

function Invoke-AdoptScan {
    param(
        [Parameter(Mandatory)][string]$Path,
        [string]$ComputerName,
        [int]$FileBudget = 20000,
        [string]$SkipPattern = $script:AdoptDefaultConfig.skipPattern,
        [int]$MaxProbeBytes = 262144,
        [int]$ProbeBudget = 4000,
        [int]$DetectPathCap = 20000,
        [string[]]$SkipFolders = @()
    )

    # NOT $args: that is PowerShell's automatic argument array, and writing to it inside a
    # function is how a splat silently becomes the wrong list.
    $scanArgs = @($Path, $FileBudget, $SkipPattern, $script:AdoptSecretNamePattern,
        $script:AdoptSecretContentPatterns, $script:AdoptExcludablePatterns, $MaxProbeBytes,
        $script:AdoptCommentLinePattern, $script:AdoptNonLiteralValuePattern, $ProbeBudget, $SkipFolders, $script:AdoptReferenceValuePattern, $script:AdoptMinSecretLength, $script:AdoptSecretNameExemptPattern, $script:AdoptKeyContainerPattern, $DetectPathCap)

    if ($ComputerName) {
        $session = $null
        try {
            $session = New-PSSession -ComputerName $ComputerName -ErrorAction Stop
            return Invoke-Command -Session $session -ScriptBlock $script:AdoptScanBlock -ArgumentList $scanArgs
        }
        finally { if ($session) { Remove-PSSession -Session $session -ErrorAction SilentlyContinue } }
    }
    return & $script:AdoptScanBlock @scanArgs
}

# --------------------------------------------------------------------------------------
# Profiles. Same contract as the fleet copy this skill was extracted from, so a profile
# written for one is readable by the other.
# --------------------------------------------------------------------------------------
$script:AdoptProfileRequiredKeys = @('name', 'status', 'description', 'detect', 'runtimes', 'build', 'routing', 'config', 'data', 'ci', 'deploy')

function Get-AdoptProfileDir {
    param([string]$ProfilesDir)
    $p = $ProfilesDir
    if (-not $p) { $p = Join-Path $PSScriptRoot '..\profiles' }
    if (-not (Test-Path -LiteralPath $p)) {
        throw "No profiles directory at '$p'. A profile describes one KIND of component; without any, nothing can be detected. Pass -ProfilesDir, or copy the skill's profiles/ folder next to scripts/."
    }
    return (Resolve-Path -LiteralPath $p).ProviderPath
}

function Get-AdoptProfiles {
    param([string]$ProfilesDir, [switch]$IncludeTemplate)
    $dir = Get-AdoptProfileDir -ProfilesDir $ProfilesDir
    $out = @()
    foreach ($d in @(Get-ChildItem -LiteralPath $dir -Directory | Sort-Object Name)) {
        if ($d.Name -eq '_template' -and -not $IncludeTemplate) { continue }
        $f = Join-Path $d.FullName 'profile.json'
        if (-not (Test-Path -LiteralPath $f)) { continue }
        $p = Get-Content -LiteralPath $f -Raw | ConvertFrom-Json
        $p | Add-Member -NotePropertyName _dir -NotePropertyValue $d.FullName -Force
        $out += $p
    }
    return $out
}

function Test-AdoptProfileContract {
    param([Parameter(Mandatory)]$Spec)
    $problems = @()
    $names = @($Spec.PSObject.Properties.Name)
    foreach ($k in $script:AdoptProfileRequiredKeys) { if ($names -notcontains $k) { $problems += "missing '$k'" } }
    if ($names -notcontains 'services' -and $names -notcontains 'schedule') { $problems += "needs 'services' or 'schedule'" }
    if ($names -contains 'status' -and $Spec.status -notin @('proven', 'draft', 'placeholder')) {
        $problems += "status '$($Spec.status)' is not proven|draft|placeholder"
    }
    if ($names -contains 'status' -and $Spec.status -ne 'placeholder' -and "$($Spec.name)" -match '[<>]') {
        $problems += "name still holds a placeholder"
    }
    return , $problems
}

# Matches one profile's detect rules against a FILE LIST (so it works for a remote scan
# without a second round trip). Returns 0 for no match, or a score: more matched rule
# kinds means a more specific match.
function Test-AdoptDetect {
    param([Parameter(Mandatory)]$Detect, [Parameter(Mandatory)][string[]]$RelativePaths, [hashtable]$FileText = @{})

    $has = {
        param($glob)
        $rx = '(?i)^' + [regex]::Escape($glob).Replace('\*\*', '.*').Replace('\*', '[^\\/]*').Replace('/', '[\\/]') + '$'
        foreach ($p in $RelativePaths) { if ($p -match $rx) { return $true } }
        return $false
    }
    $contains = {
        param($spec)
        foreach ($g in @($spec.file)) {
            $rx = '(?i)^' + [regex]::Escape($g).Replace('\*\*', '.*').Replace('\*', '[^\\/]*').Replace('/', '[\\/]') + '$'
            foreach ($k in $FileText.Keys) {
                if ($k -match $rx -and "$($FileText[$k])" -match $spec.pattern) { return $true }
            }
        }
        return $false
    }

    $names = @($Detect.PSObject.Properties.Name)
    $score = 0
    if ($names -contains 'allFiles') { foreach ($f in @($Detect.allFiles)) { if (-not (& $has $f)) { return 0 } }; $score++ }
    if ($names -contains 'anyFiles') { if (-not (@($Detect.anyFiles) | Where-Object { & $has $_ })) { return 0 }; $score++ }
    if ($names -contains 'noneFiles') { if (@($Detect.noneFiles) | Where-Object { & $has $_ }) { return 0 } }
    if ($names -contains 'fileContains') { foreach ($c in @($Detect.fileContains)) { if (-not (& $contains $c)) { return 0 } }; $score++ }
    if ($names -contains 'noneContain') { foreach ($c in @($Detect.noneContain)) { if (& $contains $c) { return 0 } } }
    return $score
}

# Fetches the text of a few small files, local or remote, for profile detection.
#
# File bodies are NEVER written into an artefact by this skill. A config file holds
# credentials, and an artefact is a file that gets copied into a ticket, a chat and a
# report. Detection reads the text in memory and keeps only the verdict.
function Get-AdoptFileText {
    param(
        [Parameter(Mandatory)][string]$Path,
        [string]$ComputerName,
        [Parameter(Mandatory)][string[]]$RelativePaths,
        [int]$MaxBytes = 262144
    )

    $block = {
        param($root, $rels, $maxBytes)
        $out = @{}
        foreach ($rel in $rels) {
            $full = Join-Path $root $rel
            if (-not (Test-Path -LiteralPath $full)) { continue }
            $fi = Get-Item -LiteralPath $full -Force -ErrorAction SilentlyContinue
            if (-not $fi -or $fi.Length -gt $maxBytes) { continue }
            try { $out[$rel] = Get-Content -LiteralPath $full -Raw -ErrorAction Stop } catch { }
        }
        return $out
    }

    if ($ComputerName) {
        $session = $null
        try {
            $session = New-PSSession -ComputerName $ComputerName -ErrorAction Stop
            return Invoke-Command -Session $session -ScriptBlock $block -ArgumentList @($Path, $RelativePaths, $MaxBytes)
        }
        finally { if ($session) { Remove-PSSession -Session $session -ErrorAction SilentlyContinue } }
    }
    return & $block $Path $RelativePaths $MaxBytes
}

# What is registered on a host to RUN this folder. An app nobody bootstrapped is usually
# started by something nobody wrote down: a service, a scheduled task, a web site.
function Get-AdoptRunRegistrations {
    param([Parameter(Mandatory)][string]$Path, [string]$ComputerName)

    $block = {
        param($needle)
        $out = @{ services = @(); scheduledTasks = @(); webSites = @(); checked = @(); errors = @() }

        try {
            $svcs = Get-CimInstance Win32_Service -ErrorAction Stop |
                Where-Object { "$($_.PathName)" -like "*$needle*" }
            foreach ($s in $svcs) {
                $out.services += @{ name = $s.Name; state = $s.State; startMode = $s.StartMode; account = $s.StartName; path = $s.PathName }
            }
            $out.checked += 'services'
        }
        catch { $out.errors += "services: $($_.Exception.Message)" }

        try {
            $tasks = Get-ScheduledTask -ErrorAction Stop
            foreach ($t in $tasks) {
                # Not every action is an Exec action. A ComHandler or SendEmail action has
                # no Execute property at all, and reading it under StrictMode throws - which
                # killed the whole scheduled-task check on a box that had one.
                $hits = @($t.Actions | Where-Object {
                        $props = @($_.PSObject.Properties.Name)
                        $exec = ''; $argus = ''; $wd = ''
                        if ($props -contains 'Execute') { $exec = "$($_.Execute)" }
                        if ($props -contains 'Arguments') { $argus = "$($_.Arguments)" }
                        if ($props -contains 'WorkingDirectory') { $wd = "$($_.WorkingDirectory)" }
                        $exec -like "*$needle*" -or $argus -like "*$needle*" -or $wd -like "*$needle*"
                    })
                if ($hits.Count -eq 0) { continue }
                $info = $null
                try { $info = $t | Get-ScheduledTaskInfo -ErrorAction Stop } catch { }
                $lastRun = $null
                if ($info) { $lastRun = "$($info.LastRunTime)" }
                $out.scheduledTasks += @{
                    name    = $t.TaskName
                    path    = $t.TaskPath
                    state   = "$($t.State)"
                    account = "$($t.Principal.UserId)"
                    action  = ("$($hits[0].Execute) $($hits[0].Arguments)").Trim()
                    lastRun = $lastRun
                }
            }
            $out.checked += 'scheduledTasks'
        }
        catch { $out.errors += "scheduledTasks: $($_.Exception.Message)" }

        try {
            Import-Module WebAdministration -ErrorAction Stop
            foreach ($s in @(Get-Website)) {
                if ("$($s.physicalPath)" -like "*$needle*") {
                    $out.webSites += @{ name = $s.Name; state = "$($s.State)"; physicalPath = "$($s.physicalPath)" }
                }
            }
            foreach ($a in @(Get-WebApplication)) {
                if ("$($a.PhysicalPath)" -like "*$needle*") {
                    $out.webSites += @{ name = "$($a.Path)"; state = 'application'; physicalPath = "$($a.PhysicalPath)" }
                }
            }
            $out.checked += 'webSites'
        }
        catch { $out.errors += "webSites: $($_.Exception.Message)" }

        return $out
    }

    # Match on the last path segment: a service command line names a local drive path, and
    # the caller may have handed us a UNC path to the same folder.
    $needle = Split-Path $Path -Leaf

    if ($ComputerName) {
        $session = $null
        try {
            $session = New-PSSession -ComputerName $ComputerName -ErrorAction Stop
            return Invoke-Command -Session $session -ScriptBlock $block -ArgumentList @($needle)
        }
        finally { if ($session) { Remove-PSSession -Session $session -ErrorAction SilentlyContinue } }
    }
    return & $block $needle
}

# Reads a key that may not be there. Under StrictMode a missing property throws, and these
# records are deliberately heterogeneous: a credential found by NAME has no line number, a
# credential found by VALUE does. Reading it directly killed two scripts mid-report.
function Get-AdoptProp {
    param($Object, [Parameter(Mandatory)][string]$Name, $Default = $null)
    if ($null -eq $Object) { return $Default }
    if ($Object -is [hashtable]) {
        if ($Object.ContainsKey($Name)) { return $Object[$Name] }
        return $Default
    }
    if (@($Object.PSObject.Properties.Name) -contains $Name) { return $Object.$Name }
    return $Default
}

function Write-AdoptHeading {
    param([Parameter(Mandatory)][string]$Text)
    Write-Host ""
    Write-Host $Text -ForegroundColor Cyan
    Write-Host ('-' * $Text.Length) -ForegroundColor DarkCyan
}
