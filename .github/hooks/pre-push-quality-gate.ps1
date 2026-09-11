#!/usr/bin/env pwsh
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "[hook] pre-push quality gate"

$isPythonRepo = (Test-Path "pyproject.toml") -or (Test-Path "requirements.txt")
$isNodeRepo = Test-Path "package.json"

# Tools run in the PROJECT'S interpreter, not whatever is on PATH.
#
# `Get-Command ruff` asks about PATH; the question that matters is whether the tool can run
# in the environment the project's code imports from. On Windows PATH finds the machine-wide
# interpreter, so the gate tested the project WITHOUT its own dependencies, while a tool
# present only in the venv looked "not installed" and was silently skipped. Same defect as
# the sh sibling and the generated hook - fixed the same way. Found 2026-08-06.
$py = $null
foreach ($cand in @(".venv\Scripts\python.exe", ".venv/bin/python", "venv\Scripts\python.exe", "venv/bin/python")) {
    if (Test-Path $cand) { $py = $cand; break }
}
# A LINKED WORKTREE has no .venv of its own: the venv is gitignored and lives in the MAIN
# checkout. Without this the gate sees a project that declares ruff/mypy, finds neither
# runnable, reports "environment is broken" and blocks a push that is perfectly
# legitimate. The reflex that trains is --no-verify, and a gate people habitually bypass
# has stopped being a gate.
#
# The venv is not missing, it is elsewhere. `git rev-parse --git-common-dir` points at the
# MAIN repository's .git even from inside a linked worktree, so its parent is the main
# working tree - look there before falling back to PATH.
if (-not $py) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $common = (& git rev-parse --git-common-dir 2>$null | Select-Object -First 1)
    $ErrorActionPreference = $prev
    $global:LASTEXITCODE = 0
    if ($common) {
        $main = Split-Path -Parent $common
        foreach ($cand in @("$main\.venv\Scripts\python.exe", "$main/.venv/bin/python",
                            "$mainenv\Scripts\python.exe", "$main/venv/bin/python")) {
            if (Test-Path $cand) {
                $py = $cand
                Write-Host "[hook] linked worktree: using the main checkout's interpreter ($py)"
                break
            }
        }
    }
}
if (-not $py) { $py = (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $py) { $py = (Get-Command python3 -ErrorAction SilentlyContinue).Source }

function Test-PyTool([string]$Tool) {
    if (-not $py) { return $false }
    # EAP=Stop turns a native command's STDERR into a terminating NativeCommandError, and
    # `python -m <missing>` writes "No module named X" to stderr - which is the NORMAL answer
    # to the question being asked here, not a failure. Without this the probe blew up on
    # exactly the case it exists to detect. Same class as the notify step-level EAP fix.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $py -m $Tool --version 2>&1 | Out-Null
        return ($LASTEXITCODE -eq 0)
    }
    catch { return $false }
    finally { $ErrorActionPreference = $prev }
}

function Test-PyWanted([string]$Tool) {
    foreach ($f in @("pyproject.toml", "requirements.txt", "requirements-dev.txt")) {
        if ((Test-Path $f) -and (Select-String -Path $f -Pattern $Tool -SimpleMatch -Quiet)) { return $true }
    }
    return $false
}

function Invoke-PyGate([string]$Tool, [string[]]$GateArgs) {
    if (Test-PyTool $Tool) {
        Write-Host "[hook] $Tool $($GateArgs -join ' ')"
        & $py -m $Tool @GateArgs
        # StrictMode + ErrorActionPreference=Stop do NOT trip on a native exe's exit code,
        # so without this an actual lint/test failure would sail through as a pass.
        if ($LASTEXITCODE -ne 0) {
            # pytest exit 5 = "no tests collected". A repo that has not written tests yet is
            # not a failing repo, and blocking it would hit exactly the fresh-scaffold case
            # this fix exists for. Every other non-zero code is a real failure.
            if ($Tool -eq "pytest" -and $LASTEXITCODE -eq 5) {
                Write-Host "[hook] pytest: no tests collected yet - not treated as a failure"
            }
            else {
                throw "[hook] $Tool failed (exit $LASTEXITCODE)"
            }
        }
    }
    elseif (Test-PyWanted $Tool) {
        # Degrade CLOSED: a declared tool that cannot run means a broken environment, and a
        # check that cannot run must not report success.
        throw "[hook] ${Tool}: DECLARED by this project but not runnable in $py - fix the venv (pip install -e '.[dev]')"
    }
}

# Each tool gets the PROJECT'S scope, not the whole tree: see gate_scope.py beside this
# file. `mypy .`, `ruff check .` and `pytest -q` all read untracked scratch files, so one
# of them blocked every push in that repo, while CI (`mypy src/`, `ruff check src/ tests/`,
# `pytest tests/`) never saw it. Found 2026-09-11.
function Invoke-ScopedGate([string]$Tool, [string[]]$Prefix, [string[]]$Fallback) {
    $scopeScript = Join-Path $PSScriptRoot "gate_scope.py"
    if (-not ((Test-PyTool $Tool) -and (Test-Path $scopeScript))) {
        Invoke-PyGate $Tool $Fallback     # keeps the declared-but-not-runnable check
        return
    }
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $scopeOut = @(& $py $scopeScript "--tool" $Tool)
    $scopeExit = $LASTEXITCODE
    $ErrorActionPreference = $prev
    $scopeOut | Where-Object { $_ -like "# *" } | ForEach-Object { Write-Host "[hook] $($_.Substring(2))" }
    if ($scopeExit -eq 3) {
        Write-Host "[skip] ${Tool}: nothing tracked to check"
        return
    }
    if ($scopeExit -ne 0) {
        throw "[hook] gate_scope.py failed for $Tool (exit $scopeExit)"
    }
    Invoke-PyGate $Tool ($Prefix + @($scopeOut | Where-Object { $_ -notlike "# *" }))
}

if ($isPythonRepo) {
    if (-not $py) { throw "[hook] python project, but no interpreter found (.venv or PATH) - cannot verify" }
    Write-Host "[hook] interpreter: $py"
    Invoke-ScopedGate "ruff"   @("check") @("check", ".", "--extend-exclude", ".github/hooks")
    Invoke-ScopedGate "mypy"   @()        @(".")
    Invoke-ScopedGate "pytest" @("-q")    @("-q")
}

if ($isNodeRepo -and (Get-Command npm -ErrorAction SilentlyContinue)) {
    $npmScripts = (npm run --silent) 2>$null
    if ($npmScripts -match "\blint\b") {
        Write-Host "[hook] npm run lint"
        npm run lint
    }
    if ($npmScripts -match "\btypecheck\b") {
        Write-Host "[hook] npm run typecheck"
        npm run typecheck
    }
    if ($npmScripts -match "\btest\b") {
        Write-Host "[hook] npm test -- --runInBand"
        npm test -- --runInBand
    }
}

Write-Host "[hook] pre-push quality gate completed"
