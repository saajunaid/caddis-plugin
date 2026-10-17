"""Programme notifications: a Windows toast, and the Claude push-notification fallback call.

Design: programme-method-design.md section 8.3. Probe 6 of .caddis/kb/headless-runner-probes.md: Windows PowerShell 5.1
shows a WinRT toast (template ToastText02) with no extra module, and a `claude -p` session has the `PushNotification`
tool. A session that ends on a status other than CONTINUE sends the push itself and prints `PUSH-SENT`; the runner calls
`push` only when the session did not.

Exit codes: 0 sent, 3 not sent (no PowerShell, not Windows, the call failed, or no `PUSH-SENT` marker). A failed send never
hides a stop: the caller logs the exit code and goes on.

    python caddis_notify.py toast --title T --message M
    python caddis_notify.py push --message M
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence
from xml.sax.saxutils import escape

try:
    import caddis_exit
except ModuleNotFoundError as exc:
    if exc.name != "caddis_exit":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-harness" / "scripts"))
    import caddis_exit

APP_ID = "caddis"
PUSH_MARKER = "PUSH-SENT"
PUSH_BUDGET_USD = "1"
Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def _ps_literal(text: str) -> str:
    """A PowerShell single-quoted literal: only `'` needs escaping (doubled)."""
    return "'" + text.replace("'", "''") + "'"


def toast_script(title: str, message: str) -> str:
    """The PowerShell 5.1 script for one ToastText02 toast. Text is XML-escaped, then quoted for PowerShell."""
    xml = (f"<toast><visual><binding template=\"ToastText02\"><text id=\"1\">{escape(title)}</text>"
           f"<text id=\"2\">{escape(message)}</text></binding></visual></toast>")
    return "; ".join([
        "$ErrorActionPreference = 'Stop'",
        "[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]",
        "[void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]",
        "$doc = New-Object Windows.Data.Xml.Dom.XmlDocument",
        f"$doc.LoadXml({_ps_literal(xml)})",
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier({_ps_literal(APP_ID)})"
        ".Show([Windows.UI.Notifications.ToastNotification]::new($doc))",
    ])


def toast(title: str, message: str, *, run: Runner = subprocess.run, platform: str | None = None) -> int:
    """Show one toast. Windows PowerShell 5.1 (`powershell.exe`) has the WinRT bridge; pwsh 7 does not."""
    if (platform or sys.platform) != "win32":
        print("caddis_notify: a toast needs Windows", file=sys.stderr)
        return caddis_exit.NOT_RUN
    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", toast_script(title, message)]
    try:
        proc = run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"caddis_notify: toast not sent: {exc}", file=sys.stderr)
        return caddis_exit.NOT_RUN
    if proc.returncode != 0:
        print(f"caddis_notify: toast not sent (exit {proc.returncode}): {(proc.stderr or '').strip()[:300]}",
              file=sys.stderr)
        return caddis_exit.NOT_RUN
    return caddis_exit.CLEAN


def push_prompt(message: str) -> str:
    return ("Your only task: call the PushNotification tool once with exactly this message, then print the line "
            f"{PUSH_MARKER} and stop. Do nothing else.\n\nMessage: {message}")


def push(message: str, *, run: Runner = subprocess.run, claude: Sequence[str] | None = None) -> int:
    """The fallback: a short `claude -p` call whose only task is the push notification. The prompt goes on stdin: on
    Windows `claude` is a `.cmd` shim that cuts a multi-line argument at its first newline."""
    claude = list(claude) if claude else [shutil.which("claude") or "claude"]
    # An explicit, least mode: the only task is one PushNotification call. Since Claude Code 2.1.302 a headless run with
    # no mode depends on the provider and the machine's settings; this one must not inherit bypassPermissions.
    # `--allowedTools PushNotification`: in `default` mode a tool that asks would stall a print session with no human.
    cmd = [*claude, "-p", "--permission-mode", "default", "--allowedTools", "PushNotification",
           "--output-format", "json", "--max-budget-usd", PUSH_BUDGET_USD]
    try:
        proc = run(cmd, input=push_prompt(message), capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"caddis_notify: push not sent: {exc}", file=sys.stderr)
        return caddis_exit.NOT_RUN
    try:
        result = json.loads(proc.stdout or "")
    except ValueError:
        result = {}
    text = result.get("result", "") if isinstance(result, dict) else ""
    if proc.returncode != 0 or not isinstance(text, str) or PUSH_MARKER not in text:
        print(f"caddis_notify: push not confirmed (exit {proc.returncode})", file=sys.stderr)
        return caddis_exit.NOT_RUN
    return caddis_exit.CLEAN


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("toast", help="show one Windows toast")
    t.add_argument("--title", required=True)
    t.add_argument("--message", required=True)
    p = sub.add_parser("push", help="send a Claude push notification through a short claude -p call")
    p.add_argument("--message", required=True)
    args = parser.parse_args(argv)
    if args.command == "toast":
        return toast(args.title, args.message)
    return push(args.message)


if __name__ == "__main__":
    raise SystemExit(main())
