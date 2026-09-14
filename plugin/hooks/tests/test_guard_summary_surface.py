"""Core checks for the host-guard installer and SessionStart surface."""

import ast
import os
from pathlib import Path
import sys
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[3]
INJECT_RELAY = REPO_ROOT / "claude-harness" / "hooks" / "inject_relay.py"
INSTALLER = REPO_ROOT / "claude-harness" / "scripts" / "install-host-guard.ps1"


def test_inject_relay_surfaces_the_guard_summary(monkeypatch, capsys) -> None:
    tree = ast.parse(INJECT_RELAY.read_text(encoding="utf-8"))
    calls = []
    log_path = Path("guard-actions.jsonl")
    summary = "[host guard] 2 processes ended"

    def summarise(path):
        calls.append(path)
        return summary

    monkeypatch.setitem(sys.modules, "caddis_host_guard", SimpleNamespace(
        summarise=summarise, guard_log_path=lambda: log_path,
    ))
    monkeypatch.setattr(sys, "path", sys.path.copy())
    # Execute the real helper and its top-level call site only. The full hook
    # also provisions user settings, which this test must not run.
    nodes = [node for node in tree.body if
             (isinstance(node, ast.FunctionDef) and node.name == "_guard_summary") or
             (isinstance(node, ast.Try) and any(
                 isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                 and child.func.id == "_guard_summary" for child in ast.walk(node)
             ))]
    namespace = {"__file__": str(INJECT_RELAY), "os": os, "sys": sys}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(INJECT_RELAY), "exec"), namespace)

    assert calls == [log_path]
    assert capsys.readouterr().out == "\n" + summary + "\n"


def test_artifact_root_fallback_survives_config_import_failure(monkeypatch) -> None:
    tree = ast.parse(INJECT_RELAY.read_text(encoding="utf-8"))
    config_import = next(node for node in tree.body if isinstance(node, ast.Try) and any(
        isinstance(child, ast.ImportFrom) and child.module == "claudster_config"
        for child in ast.walk(node)
    ))
    monkeypatch.setitem(sys.modules, "claudster_config", None)
    monkeypatch.setattr(sys, "path", sys.path.copy())
    namespace = {"__file__": str(INJECT_RELAY), "os": os, "sys": sys}
    exec(compile(ast.Module(body=[config_import], type_ignores=[]), str(INJECT_RELAY), "exec"), namespace)

    assert namespace["artifact_root"]("repo") == os.path.join("repo", ".caddis")


def test_install_script_locks_down_the_service_python() -> None:
    text = INSTALLER.read_text(encoding="utf-8")

    assert "$Mode = 'report'" in text
    assert "if (-not $Apply)" in text
    assert "ObjectName LocalSystem" in text
    assert "exit 3" in text
    assert "/inheritance:r" in text
    assert "/setowner" in text
    assert "-I -S" in text
    assert "python*._pth" in text
    assert "python*.zip" in text
    assert "$env:ProgramFiles" in text and "caddis\\python" in text
    assert "$env:ProgramData" in text and "host-budget.toml" in text
    assert "$HOME\\.caddis\\host-budget.toml" not in text

    apply_body = text[text.index("exit 0") + len("exit 0") :]
    assert "New-Item -ItemType Directory -Force -Path $programRoot" in apply_body
    assert "& robocopy.exe" in apply_body
    assert "& $nssm install" in apply_body


def test_installer_verifies_private_nssm_before_use() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    apply_body = text[text.index("exit 0") + len("exit 0") :]

    assert "$Apply -and $NssmSha256 -notmatch '\\A[0-9a-fA-F]{64}\\z'" in text
    assert "$nssmDir = Join-Path $programRoot 'nssm'" in text
    assert "$nssm = Join-Path $nssmDir 'nssm.exe'" in text
    copy = apply_body.index("Copy-Item -LiteralPath $sourceNssm -Destination $nssm -Force")
    lock = apply_body.index("Lock-CaddisTree -Path $nssmDir", copy)
    check = apply_body.index("(Get-TrustedFileHash -Path $nssm) -ine $NssmSha256", lock)
    assert apply_body.index("exit 3", check) < apply_body.index("& $nssm")
    assert "Invoke-CimMethod -InputObject $service -MethodName Change -Arguments" in apply_body
    assert "PathName = '\"{0}\"' -f $nssm" in apply_body
    assert "$change.ReturnValue -ne 0" in apply_body
    assert "& $sourceNssm" not in text
    assert "& $nssm set caddis-host-guard" not in text
