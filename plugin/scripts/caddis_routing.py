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


DEFAULT_ROUTING: dict[str, list[str]] = {
    "critical": ["opus"],
    "light": ["sonnet"],
    "coding": ["agy", "codex"],
    "review": ["glm", "deepseek"],
    "consult": ["agy", "glm", "codex"],
    "ci-watch": ["agy"],
}
KNOWN_MODELS = frozenset({"opus", "sonnet", "agy", "codex", "glm", "deepseek", "claude"})


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
    available = {"opus", "sonnet", "claude"} | (providers & {"glm", "deepseek"})
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
    args = parser.parse_args(argv)

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
