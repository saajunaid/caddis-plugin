#!/usr/bin/env python3
"""Resolve the local model order for each caddis role, and route one task deterministically (routing v3).

CLI:
    show [--json] [--repo P]                      the resolved role table ([routing] in .caddis/config.toml)
    session --role R                              the model and effort for a session role
    agy-model [--effort E]                        the agy --model id for an effort
    route --task T --risk R [--context-tokens N] [--author-model M] [--db-high] [--json] [--repo P]
                                                  agent, model, effort, reviewer and next escalation (routing.toml)
    verify-launch --requested M --effective M [--json]
                                                  exit 1 when the model that ran is not the one requested
    check-conflicts --files F... [--json] [--repo P]
                                                  exit 1 when a file is on the sequence list (run that worker alone)
    config [--repo P]                             the merged routing.toml as JSON

Exit codes: 0 ok, 1 refused (verify-launch mismatch, check-conflicts hit), 3 bad config, 4 bad input.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

import oss_model
import tomllib

# agy is Flash-only on some machines and is good only at small, exact, mechanical cards (112 of 114 passed
# in the 2026-10-08 UI-upgrade run) and CI watching. Give design-fidelity, cross-file refactor and judgment
# work to claude. Codex left the routing on 2026-10-12 (owner); a config may still name it. See .caddis/kb/agy-headless-implementer-limits.md. A separate `design` role is an
# owner decision: it changes the routing line every session prints.
DEFAULT_ROUTING: dict[str, list[str]] = {
    "critical": ["opus"],
    "light": ["sonnet"],
    "coding": ["agy"],
    "review": ["deepseek", "glm"],  # owner order 2026-10-16; an agy review runs through caddis_spend.py run (no cap)
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
    "coding-phase": ("agy", "high"),
    "mechanical-phase": ("haiku", "low"),
}
AGY_MODEL_BY_EFFORT: dict[str, str] = {"medium": "gemini-4-carbon-medium", "high": "gemini-4-carbon-high"}
AGY_DEFAULT_EFFORT = "high"  # owner, 12 Nov 2026: Carbon high; an effort with no row here (low, max) gets this model
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


# ── routing v3: routing.toml, route, verify-launch, review pairs, sequencing ─────────────────────────────────────
# The shipped routing.toml sits beside this file. Overrides merge on top, table by table (a list replaces the list):
# ~/.caddis/routing.toml, then <repo>/.caddis/routing.toml. The rules below are code, so no override can lift them.

SHIPPED_ROUTING_TOML = Path(__file__).with_name("routing.toml")
ROUTING_FILE = "routing.toml"
RISKS: tuple[str, ...] = ("low", "medium", "high", "critical")
CLAUDE_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
# Evergreen Claude aliases and the full ids they stand for today.
CLAUDE_MODEL_IDS: dict[str, str] = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}
AGY_MODELS = frozenset({
    "gemini-4-carbon-low", "gemini-4-carbon-medium", "gemini-4-carbon-high",  # no carbon-xhigh
    "gemini-4-neon-low", "gemini-4-neon-medium", "gemini-4-neon-high", "gemini-4-neon-xhigh",
    "gemini-4-hydrogen-low", "gemini-4-hydrogen-medium", "gemini-4-hydrogen-high",  # no hydrogen-xhigh
})
VALID_MODELS = frozenset(CLAUDE_MODEL_IDS) | AGY_MODELS
SHELL = "shell"  # a bot that runs no model (ci-watch)
NEON_CONTEXT_CAP = 512_000
NEON_PREFIX = "gemini-4-neon-"
HYDROGEN_PREFIX = "gemini-4-hydrogen-"
HYDROGEN_ALLOWED = "gemini-4-hydrogen-low"
CODING_TASKS = frozenset({"implement_feature", "ui", "write_tests", "small_fix", "bulk_mechanical_edit", "bug_sweep"})
READ_ONLY_TASKS = frozenset({"classify", "explore", "commit_pr_text", "ci_summary"})
TASKS = CODING_TASKS | READ_ONLY_TASKS | frozenset({
    "plan_architecture", "root_cause_analysis", "hard_reasoning", "merge_conflict",
    "critical_seam", "db_high", "security_rbac_pii", "governance_gate", "mockup",
})
# DB-HIGH and security code always get a cross-vendor reviewer, at every risk (oss_review.py refuses a same-vendor
# review for them too).
SENSITIVE_TASKS = frozenset({"db_high", "security_rbac_pii"})
# Never a reviewer: Carbon high went 10 of 10 NOT_RUN on reviews, Neon medium approved buggy code in 3 of 20,
# Hydrogen is read-only (17 Nov 2026 benchmark).
BANNED_REVIEWERS = frozenset({"gemini-4-carbon-high", "gemini-4-neon-medium"})
REVIEW_MODES = ("none", "same_vendor_cross_model", "cross_vendor")
_TOP_KEYS = frozenset({"version", "defaults", "context", "trial", "tasks", "review", "bots", "concurrency"})
_TABLE_KEYS: dict[str, frozenset[str]] = {
    "defaults": frozenset({"claude_effort", "agy_print_timeout_s"}),
    "context": frozenset({"neon_guard_tokens", "large_context_model"}),
    "trial": frozenset({"coding_model"}),
    "bots": frozenset({"wave", "core", "core_merge_conflict", "ci_watch"}),
    "concurrency": frozenset({"max_parallel_workers", "sequence_when_touching"}),
}
_TASK_KEYS = frozenset({"model", "effort", "escalation", "opus_at", "large_context", "reviewer", "extra_reviewers"})
# Other names a caller may use for a task.
TASK_ALIASES: dict[str, str] = {"ui_mockup": "mockup"}
_REVIEW_KEYS = frozenset({"medium_pairs", "strict"})
_STRICT_KEYS = frozenset({"agy_high", "agy_critical", "claude", "claude_fallback", "db_high_reviewer"})


def canonical_model(model: str | None) -> str:
    """The routing id of a model: trimmed, lower case, a full Claude id as its alias (`claude-opus-5-5` -> `opus`)."""
    value = (model or "").strip().lower()
    for alias, full in CLAUDE_MODEL_IDS.items():
        if value == full:
            return alias
    return value


def is_hydrogen(model: str | None) -> bool:
    return "hydrogen" in canonical_model(model)


def vendor_of(model: str | None) -> str | None:
    value = canonical_model(model)
    if value in CLAUDE_MODEL_IDS:
        return "anthropic"
    if value.startswith("gemini-"):
        return "google"
    return None


def agent_of(model: str) -> str:
    """`claude`, `agy` or `shell`: the tool that runs `model`."""
    if model == SHELL:
        return SHELL
    return "claude" if vendor_of(model) == "anthropic" else "agy"


def is_banned_reviewer(model: str | None) -> bool:
    value = canonical_model(model)
    return value in BANNED_REVIEWERS or is_hydrogen(value)


def _agy_effort(model: str) -> str:
    return model.rsplit("-", 1)[1]


def _load_layer(path: Path, required: bool) -> dict:
    if not path.is_file():
        if required:
            raise RoutingConfigError(f"{path}: the shipped routing.toml is missing")
        return {}
    try:
        with path.open("rb") as file:
            return tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RoutingConfigError(f"{path}: {exc}") from exc


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for key, value in over.items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def _model(value, where: str, *, shell: bool = False) -> str:
    if shell and value == SHELL:
        return SHELL
    if not isinstance(value, str) or canonical_model(value) not in VALID_MODELS:
        raise RoutingConfigError(f"{where}: unknown model {value!r} (valid: {', '.join(sorted(VALID_MODELS))})")
    return canonical_model(value)


def _no_hydrogen(model: str, where: str) -> None:
    if is_hydrogen(model):
        raise RoutingConfigError(f"{where}: {model} is read-only (Hydrogen never codes, reviews or runs a bot)")


def _table(config: dict, key: str, where: str) -> dict:
    table = config.get(key, {})
    if not isinstance(table, dict):
        raise RoutingConfigError(f"{where}: [{key}] must be a table")
    return table


def _check_keys(table: dict, allowed: frozenset[str], where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise RoutingConfigError(f"{where}: unknown key(s) {', '.join(unknown)}")


def _validate_task(name: str, row, where: str) -> None:
    here = f"{where}: tasks.{name}"
    if name not in TASKS:
        raise RoutingConfigError(f"{where}: unknown task {name!r} (known: {', '.join(sorted(TASKS))})")
    if not isinstance(row, dict):
        raise RoutingConfigError(f"{here} must be a table")
    _check_keys(row, _TASK_KEYS, here)
    models = []
    if "model" in row:
        models.append(_model(row["model"], f"{here}.model"))
    escalation = row.get("escalation", [])
    if not isinstance(escalation, list):
        raise RoutingConfigError(f"{here}.escalation must be a list")
    models += [_model(m, f"{here}.escalation") for m in escalation]
    if "large_context" in row:
        large = _model(row["large_context"], f"{here}.large_context")
        if large.startswith(NEON_PREFIX):
            raise RoutingConfigError(f"{here}.large_context: Neon holds 512K tokens; pick Carbon or a Claude model")
        models.append(large)
    for model in models:
        if name in READ_ONLY_TASKS:
            if is_hydrogen(model) and model != HYDROGEN_ALLOWED:
                raise RoutingConfigError(f"{here}: only {HYDROGEN_ALLOWED} may run a read-only task, not {model}")
        else:
            _no_hydrogen(model, here)
    if "reviewer" in row:
        reviewer = _model(row["reviewer"], f"{here}.reviewer")
        if is_banned_reviewer(reviewer):
            raise RoutingConfigError(f"{here}.reviewer: {reviewer} never reviews (banned reviewer)")
        if "model" in row and canonical_model(row["model"]) == reviewer:
            raise RoutingConfigError(f"{here}.reviewer: a model never reviews its own output")
    extra = row.get("extra_reviewers", [])
    if not isinstance(extra, list) or not all(isinstance(name, str) and name.strip() for name in extra):
        raise RoutingConfigError(f"{here}.extra_reviewers must be a list of agent names")
    if "effort" in row and (not isinstance(row["effort"], str) or row["effort"] not in CLAUDE_EFFORTS):
        raise RoutingConfigError(f"{here}.effort: {row['effort']!r} is not one of {', '.join(sorted(CLAUDE_EFFORTS))}")
    opus_at = row.get("opus_at", [])
    if not isinstance(opus_at, list) or any(r not in RISKS for r in opus_at):
        raise RoutingConfigError(f"{here}.opus_at must be a list of {', '.join(RISKS)}")


def _validate_review(review: dict, where: str) -> None:
    _check_keys(review, _REVIEW_KEYS, f"{where}: [review]")
    pairs = _table(review, "medium_pairs", where)
    for author, reviewer in pairs.items():
        here = f"{where}: review.medium_pairs.{author}"
        author_id = _model(author, here)
        reviewer_id = _model(reviewer, here)
        if author != author_id or reviewer != reviewer_id:
            raise RoutingConfigError(f"{here}: write the routing id ({author_id} = {reviewer_id!r})")
        _no_hydrogen(author_id, here)
        if author_id == reviewer_id:
            raise RoutingConfigError(f"{here}: a model never reviews its own output")
        if is_banned_reviewer(reviewer_id):
            raise RoutingConfigError(f"{here}: {reviewer_id} never reviews (banned reviewer)")
    strict = _table(review, "strict", where)
    _check_keys(strict, _STRICT_KEYS, f"{where}: [review.strict]")
    for key in ("agy_high", "agy_critical", "claude", "claude_fallback"):
        if key not in strict:
            continue
        here = f"{where}: review.strict.{key}"
        reviewer = _model(strict[key], here)
        want = "google" if key.startswith("claude") else "anthropic"
        if vendor_of(reviewer) != want:
            raise RoutingConfigError(f"{here}: a strict reviewer is always another vendor ({want}), not {reviewer}")
        if is_banned_reviewer(reviewer):
            raise RoutingConfigError(f"{here}: {reviewer} never reviews (banned reviewer)")
    if "db_high_reviewer" in strict and not (isinstance(strict["db_high_reviewer"], str)
                                              and strict["db_high_reviewer"].strip()):
        raise RoutingConfigError(f"{where}: review.strict.db_high_reviewer must be a name")


def _validate_layer(config: dict, where: str) -> None:
    """Every rule that one file can break on its own: keys, types, model ids, Hydrogen, banned reviewers."""
    _check_keys(config, _TOP_KEYS, where)
    for key, allowed in _TABLE_KEYS.items():
        _check_keys(_table(config, key, where), allowed, f"{where}: [{key}]")
    defaults = _table(config, "defaults", where)
    effort = defaults.get("claude_effort", "high")
    if not isinstance(effort, str) or effort not in CLAUDE_EFFORTS:
        raise RoutingConfigError(f"{where}: defaults.claude_effort must be one of {', '.join(sorted(CLAUDE_EFFORTS))}")
    timeout = defaults.get("agy_print_timeout_s", 1)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        raise RoutingConfigError(f"{where}: defaults.agy_print_timeout_s must be a whole number of seconds above 0")
    context = _table(config, "context", where)
    guard = context.get("neon_guard_tokens", 1)
    if isinstance(guard, bool) or not isinstance(guard, int) or not 0 < guard <= NEON_CONTEXT_CAP:
        raise RoutingConfigError(f"{where}: context.neon_guard_tokens must be 1 to {NEON_CONTEXT_CAP} (Neon's cap)")
    if "large_context_model" in context:
        large = _model(context["large_context_model"], f"{where}: context.large_context_model")
        _no_hydrogen(large, f"{where}: context.large_context_model")
        if large.startswith(NEON_PREFIX):
            raise RoutingConfigError(f"{where}: context.large_context_model: Neon holds 512K tokens")
    coding = _table(config, "trial", where).get("coding_model", "")
    if coding != "":
        _no_hydrogen(_model(coding, f"{where}: trial.coding_model"), f"{where}: trial.coding_model")
    for name, row in _table(config, "tasks", where).items():
        _validate_task(name, row, where)
    _validate_review(_table(config, "review", where), where)
    for bot, model in _table(config, "bots", where).items():
        _no_hydrogen(_model(model, f"{where}: bots.{bot}", shell=True), f"{where}: bots.{bot}")
    concurrency = _table(config, "concurrency", where)
    workers = concurrency.get("max_parallel_workers", 1)
    if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= 32:
        raise RoutingConfigError(f"{where}: concurrency.max_parallel_workers must be 1 to 32")
    patterns = concurrency.get("sequence_when_touching", [])
    if not isinstance(patterns, list) or not all(isinstance(p, str) and p.strip() for p in patterns):
        raise RoutingConfigError(f"{where}: concurrency.sequence_when_touching must be a list of path patterns")


def load_config(home: Path, repo: Path, shipped: Path | None = None) -> dict:
    """The merged routing.toml: shipped, then ~/.caddis/routing.toml, then <repo>/.caddis/routing.toml.
    Raises RoutingConfigError on a parse error, a bad value, or a merged table with a task or table missing."""
    paths = [(Path(shipped or SHIPPED_ROUTING_TOML), True),
             (Path(home) / ".caddis" / ROUTING_FILE, False),
             (Path(repo) / ".caddis" / ROUTING_FILE, False)]
    merged: dict = {}
    used = []
    for path, required in paths:
        layer = _load_layer(path, required)
        if layer:
            _validate_layer(layer, str(path))
            merged = _merge(merged, layer)
            used.append(str(path))
    where = f"routing config ({', '.join(used)})"
    missing = sorted(TASKS - set(merged.get("tasks", {})))
    if missing:
        raise RoutingConfigError(f"{where}: no row for task(s) {', '.join(missing)}")
    for name in sorted(TASKS):
        if "model" not in merged["tasks"][name]:
            raise RoutingConfigError(f"{where}: tasks.{name} has no model")
    for table in ("defaults", "context", "bots", "concurrency"):
        if table not in merged:
            raise RoutingConfigError(f"{where}: no [{table}] table")
    if "large_context_model" not in merged["context"]:
        raise RoutingConfigError(f"{where}: context.large_context_model is missing")
    for name, row in merged["tasks"].items():
        if "reviewer" in row and canonical_model(row["reviewer"]) == canonical_model(row["model"]):
            raise RoutingConfigError(f"{where}: tasks.{name}.reviewer: a model never reviews its own output")
    strict = merged.get("review", {}).get("strict", {})
    missing_strict = sorted(_STRICT_KEYS - set(strict))
    if missing_strict:
        raise RoutingConfigError(f"{where}: review.strict has no {', '.join(missing_strict)}")
    return merged


def _strict_review(author: str, risk: str, config: dict) -> tuple[str, str | None]:
    strict = config["review"]["strict"]
    if vendor_of(author) == "google":
        return canonical_model(strict["agy_critical" if risk == "critical" else "agy_high"]), None
    return canonical_model(strict["claude"]), canonical_model(strict["claude_fallback"])


def review_for(author: str, risk: str, task: str, config: dict, db_high: bool = False) -> dict:
    """The review a change by `author` gets at `risk` (owner, 27 Nov 2026). low: deterministic gates only. medium:
    the proven pair for the author, else the strict reviewer. high and critical: the strict cross-vendor reviewer;
    critical adds the owner's approval. A read-only task changes no code, so it gets no model review. A task row's
    own `reviewer` (a design reviewer) reviews at every risk where review_pair_problem allows it; else the rules above."""
    author = canonical_model(author)
    row = config["tasks"][task]
    review = {"reviewer": None, "reviewer_fallback": None, "review_mode": "none",
              "extra_reviewers": list(row.get("extra_reviewers", [])), "human_approval": risk == "critical"}
    if db_high:
        review["extra_reviewers"].append(config["review"]["strict"]["db_high_reviewer"])
    review["extra_reviewers"] = list(dict.fromkeys(review["extra_reviewers"]))
    if task in READ_ONLY_TASKS:
        return review
    if db_high or task in SENSITIVE_TASKS:  # DB-HIGH and security code: another vendor at every risk, no pair
        reviewer, fallback = _strict_review(author, "critical" if risk == "critical" else "high", config)
        review.update({"reviewer": reviewer, "reviewer_fallback": fallback, "review_mode": "cross_vendor"})
        return review
    task_reviewer = canonical_model(row.get("reviewer", ""))
    if risk == "low" and not task_reviewer:
        return review
    pair = config["review"].get("medium_pairs", {}).get(author) if risk == "medium" else None
    if task_reviewer and review_pair_problem(author, task_reviewer, risk, risk == "medium", config) is None:
        reviewer, fallback = task_reviewer, None  # a design reviewer, only where the review rules allow it
    elif risk == "low":
        return review
    elif pair:
        reviewer = canonical_model(pair)
        fallback = _strict_review(author, "high", config)[0 if vendor_of(reviewer) == vendor_of(author) else 1]
    else:
        reviewer, fallback = _strict_review(author, risk, config)
    if reviewer == author or is_banned_reviewer(reviewer):  # config validation makes this unreachable
        raise RoutingConfigError(f"no valid reviewer for author {author} at risk {risk}")
    review.update({
        "reviewer": reviewer,
        "reviewer_fallback": fallback if fallback and fallback not in (author, reviewer) else None,
        "review_mode": "same_vendor_cross_model" if vendor_of(reviewer) == vendor_of(author) else "cross_vendor",
    })
    return review


def review_pair_problem(author: str, reviewer: str, risk: str, allow_same_vendor_cross_model: bool,
                        config: dict) -> str | None:
    """Why `reviewer` may not review `author`'s change at `risk`, or None when it may.

    A model never reviews its own output, a banned reviewer never reviews, and a same-vendor review needs
    --allow-same-vendor-cross-model, risk medium and the proven pair for the author in review.medium_pairs."""
    author_id, reviewer_id = canonical_model(author), canonical_model(reviewer)
    if risk not in RISKS:
        return f"unknown risk {risk!r} (expected {', '.join(RISKS)})"
    if allow_same_vendor_cross_model and risk != "medium":
        need = "uses the deterministic gates only" if risk == "low" else "needs a cross-vendor reviewer"
        return f"--allow-same-vendor-cross-model is for risk medium only; risk {risk} {need}"
    for label, value in (("author", author_id), ("reviewer", reviewer_id)):
        if value not in VALID_MODELS:
            return f"unknown {label} model {value!r}"
    if author_id == reviewer_id:
        return f"a model never reviews its own output ({author_id})"
    if is_banned_reviewer(reviewer_id):
        return f"{reviewer_id} never reviews (banned: Carbon high, Neon medium, every Hydrogen model)"
    if vendor_of(author_id) == vendor_of(reviewer_id):
        if not allow_same_vendor_cross_model:
            return f"same-vendor review ({author_id} -> {reviewer_id}) needs --allow-same-vendor-cross-model"
        proven = config.get("review", {}).get("medium_pairs", {}).get(author_id)
        if canonical_model(proven) != reviewer_id:
            return (f"{author_id} -> {reviewer_id} is not a proven pair; the medium pair for {author_id} is "
                    f"{proven or 'none'}")
    return None


def route(task: str, risk: str, config: dict, context_tokens: int = 0, author_model: str | None = None,
          db_high: bool = False) -> dict:
    """The deterministic route for one task: agent, model, effort, reviewer and the next escalation. No model call.
    Raises ValueError on an unknown task, risk or author model."""
    task = TASK_ALIASES.get(task, task)
    if task not in TASKS:
        raise ValueError(f"unknown task {task!r}; known: {', '.join(sorted(TASKS | set(TASK_ALIASES)))}")
    if risk not in RISKS:
        raise ValueError(f"unknown risk {risk!r}; known: {', '.join(RISKS)}")
    if context_tokens < 0:
        raise ValueError("context tokens must be 0 or more")
    row = config["tasks"][task]
    claude_effort = config["defaults"].get("claude_effort", "high")
    model = canonical_model(row["model"])
    ladder = [canonical_model(m) for m in row.get("escalation", [])]
    trial = canonical_model(config.get("trial", {}).get("coding_model", ""))
    if trial and task in CODING_TASKS:
        model = trial
        # The ladder never goes down: a trialled model drops itself and every step below it.
        ladder = [] if model == "opus" else ladder[ladder.index(model) + 1:] if model in ladder else ladder
    if risk in row.get("opus_at", []):
        model, ladder = "opus", []
    guard = config["context"].get("neon_guard_tokens", 400_000)
    context_guard = context_tokens > guard and (model.startswith(NEON_PREFIX)
                                                or any(m.startswith(NEON_PREFIX) for m in ladder))
    if context_guard:
        if model.startswith(NEON_PREFIX):
            model = canonical_model(row.get("large_context") or config["context"]["large_context_model"])
        ladder = [m for m in ladder if not m.startswith(NEON_PREFIX)]
    ladder = [m for m in dict.fromkeys(ladder) if m != model]
    if model in CLAUDE_MODEL_IDS:
        effort = row.get("effort", claude_effort) if model == canonical_model(row["model"]) else claude_effort
    else:
        effort = _agy_effort(model)
    author = canonical_model(author_model) if author_model else model
    if author not in VALID_MODELS:
        raise ValueError(f"unknown author model {author_model!r}")

    def step(next_model: str) -> dict:
        return {"agent": agent_of(next_model), "model": next_model,
                "effort": claude_effort if next_model in CLAUDE_MODEL_IDS else _agy_effort(next_model)}

    result = {"task": task, "risk": risk, "agent": agent_of(model), "model": model,
              "model_id": CLAUDE_MODEL_IDS.get(model, model), "effort": effort, "author_model": author,
              "context_tokens": context_tokens, "context_guard": context_guard,
              "escalation_next": step(ladder[0]) if ladder else None, "escalation": ladder,
              "print_timeout_s": config["defaults"].get("agy_print_timeout_s", 2400) if agent_of(model) == "agy" else None}
    result.update(review_for(author, risk, task, config, db_high=db_high or task == "db_high"))
    return result


# agy has been seen to fall back silently to a model caddis never routes (agy 1.5.10: a fallback list that ended
# on Hydrogen and Flash). A launch whose effective model is not the requested one fails closed.
_SILENT_FALLBACK_MARKERS = ("hydrogen", "flash", "argon")


def verify_launch(requested: str, effective: str) -> tuple[bool, str]:
    """(True, note) when the effective model is the requested one (a full Claude id equals its alias), else
    (False, why). An unknown requested model or an empty effective model fails closed."""
    want, got = canonical_model(requested), canonical_model(effective)
    if want not in VALID_MODELS:
        return False, f"requested model {requested!r} is not a valid routing model"
    if not got:
        return False, f"no effective model reported for the launch of {want}"
    if want == got:
        return True, f"launch ok: {got}"
    if any(marker in got for marker in _SILENT_FALLBACK_MARKERS) and not any(m in want for m in _SILENT_FALLBACK_MARKERS):
        return False, f"silent agy fallback: requested {want}, effective {got}. Stop and relaunch with --model {want}."
    return False, f"launch mismatch: requested {want}, effective {got}. Stop and relaunch with --model {want}."


def _glob_regex(pattern: str) -> re.Pattern[str]:
    """A path pattern as a regex: `**/` any folders (or none), `/**` anything below, `*` and `?` within one name."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("/**", i) and i + 3 == len(pattern):
            out, i = out + "/.*", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z", re.IGNORECASE)


def sequence_matches(files: list[str], patterns: list[str]) -> list[str]:
    """The files that are on the sequence list. A pattern with no "/" matches the file name at any depth. Matching
    ignores case (Windows file names)."""
    compiled = [(p, _glob_regex(p)) for p in (raw.replace("\\", "/").strip() for raw in patterns)]
    hits = []
    for raw in files:
        path = raw.replace("\\", "/").strip()
        while path.startswith("./"):
            path = path[2:]
        name = path.rsplit("/", 1)[-1]
        for pattern, regex in compiled:
            if regex.match(name if "/" not in pattern else path):
                hits.append(path)
                break
    return hits


def _print(data: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data))
        return
    for key, value in data.items():
        print(f"{key}: {value if isinstance(value, str) else json.dumps(value)}")


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    show = commands.add_parser("show", help="print the resolved routing table")
    show.add_argument("--json", action="store_true", help="print JSON")
    show.add_argument("--repo", type=Path, default=Path.cwd(), help="repository path")
    session = commands.add_parser("session", help="print the model and effort for a session role")
    session.add_argument("--role", required=True, help=f"one of: {', '.join(SESSION_DEFAULTS)}")
    agy_model = commands.add_parser("agy-model", help="print the agy --model id for an effort (the agy Lane line takes it)")
    agy_model.add_argument("--effort", default=AGY_DEFAULT_EFFORT, help="the effort on the phase's Model line")
    route_p = commands.add_parser("route", help="route one task by routing.toml (no model call)")
    route_p.add_argument("--task", required=True, help=f"one of: {', '.join(sorted(TASKS | set(TASK_ALIASES)))}")
    route_p.add_argument("--risk", required=True, choices=RISKS)
    route_p.add_argument("--context-tokens", type=int, default=0, help="context the task needs (Neon holds 512K)")
    route_p.add_argument("--author-model", default=None, help="the model that wrote the change (default: the routed one)")
    route_p.add_argument("--db-high", action="store_true", help="the change is DB: HIGH (adds the DB reviewer)")
    route_p.add_argument("--json", action="store_true", help="print JSON")
    route_p.add_argument("--repo", type=Path, default=Path.cwd(), help="repository path")
    verify = commands.add_parser("verify-launch", help="fail closed when the effective model is not the requested one")
    verify.add_argument("--requested", required=True)
    verify.add_argument("--effective", required=True)
    verify.add_argument("--json", action="store_true", help="print JSON")
    conflicts = commands.add_parser("check-conflicts", help="files on the sequence list (lockfiles, migrations)")
    conflicts.add_argument("--files", nargs="+", required=True)
    conflicts.add_argument("--json", action="store_true", help="print JSON")
    conflicts.add_argument("--repo", type=Path, default=Path.cwd(), help="repository path")
    config_p = commands.add_parser("config", help="print the merged routing.toml as JSON")
    config_p.add_argument("--repo", type=Path, default=Path.cwd(), help="repository path")
    args = parser.parse_args(argv)

    if args.command == "verify-launch":
        ok, note = verify_launch(args.requested, args.effective)
        _print({"ok": ok, "requested": canonical_model(args.requested), "effective": canonical_model(args.effective),
                "note": note}, args.json)
        return 0 if ok else 1

    if args.command in ("route", "check-conflicts", "config"):
        home = (env or {}).get("USERPROFILE") or (env or {}).get("HOME")
        try:
            config = load_config(Path(home) if home else Path.home(), args.repo)
        except RoutingConfigError as exc:
            print(exc, file=sys.stderr)
            return 3
        if args.command == "config":
            print(json.dumps(config, indent=2))
            return 0
        if args.command == "check-conflicts":
            patterns = config["concurrency"].get("sequence_when_touching", [])
            hits = sequence_matches(args.files, patterns)
            _print({"sequence": bool(hits), "files": hits,
                    "max_parallel_workers": config["concurrency"].get("max_parallel_workers", 1)}, args.json)
            return 1 if hits else 0
        try:
            result = route(args.task, args.risk, config, context_tokens=args.context_tokens,
                           author_model=args.author_model, db_high=args.db_high)
        except RoutingConfigError as exc:
            print(exc, file=sys.stderr)
            return 3
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 4
        _print(result, args.json)
        return 0

    if args.command == "agy-model":
        print(AGY_MODEL_BY_EFFORT.get(args.effort, AGY_MODEL_BY_EFFORT[AGY_DEFAULT_EFFORT]))
        return 0

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
