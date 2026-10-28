#!/usr/bin/env python3
"""Resolve the local model order for each caddis role."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tomllib
from pathlib import Path
from typing import Callable, Mapping

import oss_model


# agy is Flash-only on some machines and is good only at small, exact, mechanical cards (112 of 114 passed
# in the 2026-10-08 UI-upgrade run) and CI watching. Give design-fidelity, cross-file refactor and judgment
# work to claude. Codex left the routing on 2026-10-12 (owner); a config may still name it. See .caddis/kb/agy-headless-implementer-limits.md. A separate `design` role is an
# owner decision: it changes the routing line every session prints.
DEFAULT_ROUTING: dict[str, list[str]] = {
    "critical": ["opus"],
    "light": ["sonnet"],
    "coding": ["agy"],
    "review": ["deepseek", "glm"],  # owner order 2026-10-16; an agy review runs through caddis_spend.py
    "consult": ["agy", "glm"],
    "ci-watch": ["agy"],
    "mechanical": ["haiku"],
}
KNOWN_MODELS = frozenset({"opus", "sonnet", "haiku", "agy", "codex", "glm", "deepseek", "claude"})

# One session model+effort table (owner, 27 Oct; .caddis/plans/context-handoff-strategy.md Phase 7). handoff,
# coordinate and implement read it; DEFAULT_ROUTING and `show` stay as they are. `orchestrator` stays high until
# Phase 9 measures it; `measure` is for measurement and screenshot subagents. Review is not a row: it goes by tier
# (`caddis_gate.py review-tier`).
SESSION_DEFAULTS: dict[str, tuple[str, str]] = {
    "orchestrator": ("sonnet", "high"),
    "plan-writer": ("opus", "high"),
    "coordinator": ("sonnet", "low"),
    "measure": ("sonnet", "medium"),
    "critical-phase": ("opus", "medium"),
    "coding-phase": ("agy", "medium"),
    "mechanical-phase": ("haiku", "low"),
}
AGY_MODEL_BY_EFFORT: dict[str, str] = {"medium": "gemini-4-argon-medium", "high": "gemini-4-argon-high"}
CLAUDE_SESSION_MODELS = frozenset({"opus", "sonnet", "haiku"})


def session_start(role: str) -> tuple[str, str]:
    """The `claude --model --effort` pair for a new session of `role`.

    A start line can name only a Claude model, so a role with no Claude row (any session-name role, or
    `coding-phase`) starts as the orchestrator."""
    model, effort = SESSION_DEFAULTS.get(role, SESSION_DEFAULTS["orchestrator"])
    if model not in CLAUDE_SESSION_MODELS:
        return SESSION_DEFAULTS["orchestrator"]
    return model, effort


class RoutingConfigError(Exception):
    """A routing file has an invalid value or cannot be parsed."""


def _routing_from(path: Path) -> dict[str, list[str]]:
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as file:
            config = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RoutingConfigError(f"{path}: {exc}") from exc

    routing = config.get("routing", {})
    if not isinstance(routing, dict):
        raise RoutingConfigError(f"{path}: [routing] must be a table")
    for role, models in routing.items():
        if role not in DEFAULT_ROUTING:
            raise RoutingConfigError(f"{path}: unknown routing role {role!r}")
        if not isinstance(models, list):
            raise RoutingConfigError(f"{path}: routing.{role} must be a list")
        for model in models:
            if not isinstance(model, str) or model not in KNOWN_MODELS:
                raise RoutingConfigError(f"{path}: unknown model {model!r} in routing.{role}")
    return routing


def resolve(
    home: Path,
    repo: Path,
    which: Callable[[str], str | None] = shutil.which,
    env: Mapping[str, str] | None = None,
) -> dict[str, list[str]]:
    """Apply user and repo overrides, then keep only locally available models."""
    env = os.environ if env is None else env
    configured = dict(DEFAULT_ROUTING)
    configured.update(_routing_from(Path(home) / ".caddis" / "config.toml"))
    configured.update(_routing_from(Path(repo) / ".caddis" / "config.toml"))

    providers = set(oss_model.configured_providers(dict(env)))
    available = {"opus", "sonnet", "haiku", "claude"} | (providers & {"glm", "deepseek"})
    for tool in ("agy", "codex"):
        if which(tool):
            available.add(tool)

    resolved = {}
    for role, models in configured.items():
        resolved[role] = list(dict.fromkeys(
            model for model in models if model != "claude" and model in available
        )) + ["claude"]
    return resolved


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    show = commands.add_parser("show", help="print the resolved routing table")
    show.add_argument("--json", action="store_true", help="print JSON")
    show.add_argument("--repo", type=Path, default=Path.cwd(), help="repository path")
    session = commands.add_parser("session", help="print the model and effort for a session role")
    session.add_argument("--role", required=True, help=f"one of: {', '.join(SESSION_DEFAULTS)}")
    args = parser.parse_args(argv)

    if args.command == "session":
        if args.role not in SESSION_DEFAULTS:
            print(f"unknown session role {args.role!r}; known: {', '.join(SESSION_DEFAULTS)}", file=sys.stderr)
            return 4
        print(" ".join(SESSION_DEFAULTS[args.role]))
        return 0

    try:
        routing = resolve(Path.home(), args.repo, env=env)
    except RoutingConfigError as exc:
        print(exc, file=sys.stderr)
        return 3
    if args.json:
        print(json.dumps(routing))
    else:
        for role, models in routing.items():
            print(f"{role}: {', '.join(models)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
