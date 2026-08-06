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

if ($isPythonRepo) {
    if (-not $py) { throw "[hook] python project, but no interpreter found (.venv or PATH) - cannot verify" }
    Write-Host "[hook] interpreter: $py"
    Invoke-PyGate "ruff"   @("check", ".")
    Invoke-PyGate "mypy"   @(".")
    Invoke-PyGate "pytest" @("-q")
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
