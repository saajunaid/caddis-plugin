#!/usr/bin/env pwsh
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "[hook] pre-commit quality gate"

if (Test-Path "validate_pool.py") {
    $pythonCmd = $null
    if (Test-Path ".venv\\Scripts\\python.exe") {
        $pythonCmd = ".venv\\Scripts\\python.exe"
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        $pythonCmd = "python"
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        $pythonCmd = "py -3"
    }

    if ($pythonCmd) {
        Write-Host "[hook] python validate_pool.py"
        Invoke-Expression "$pythonCmd validate_pool.py"
    }
}

# Doc-coverage discipline — dogfood the feature on the caddis repo itself. Blocks on a hard
# invariant (missing route / dangling doc-map link); soft signals warn. No-op if the checker is absent.
if (Test-Path "claude-harness\scripts\check_doc_coverage.py") {
    $docPy = $null
    if (Test-Path ".venv\Scripts\python.exe") { $docPy = ".venv\Scripts\python.exe" }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { $docPy = "python" }
    elseif (Get-Command py -ErrorAction SilentlyContinue) { $docPy = "py -3" }
    if ($docPy) {
        Write-Host "[hook] doc coverage"
        Invoke-Expression "$docPy claude-harness\scripts\check_doc_coverage.py --check"
        if ($LASTEXITCODE -ne 0) { throw "doc coverage check failed (missing route / dangling doc-map link)" }
    }
}

$isPythonRepo = (Test-Path "pyproject.toml") -or (Test-Path "requirements.txt")
$isNodeRepo = Test-Path "package.json"

if ($isPythonRepo) {
    if (Get-Command ruff -ErrorAction SilentlyContinue) {
        Write-Host "[hook] ruff check ."
        ruff check .
    }

    if (Get-Command mypy -ErrorAction SilentlyContinue) {
        Write-Host "[hook] mypy . (best-effort)"
        mypy .
    }

    if (Get-Command pytest -ErrorAction SilentlyContinue) {
        Write-Host "[hook] pytest -q"
        pytest -q
    }
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
}

Write-Host "[hook] quality gate completed"
