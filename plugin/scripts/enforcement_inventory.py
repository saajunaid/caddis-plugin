#!/usr/bin/env python3
"""Inventory caddis's load-bearing rules, and measure how many are actually enforced.

WHY THIS EXISTS
---------------
Three independent audits reached the same conclusion in different words: strip the prose from
this plugin and the machine content is very small. Nearly every "MUST" / "NEVER" / "STOP" is a
sentence in a markdown file that a model may or may not honour. Those degrade silently under
model change, context pressure, a cheaper lane, or a distracted session — and they read as
guarantees, which is worse than reading as advice.

The things that actually held under pressure were the ones with exit codes: pytest,
validate_pool, the hooks, oss_review's exit 2.

So this script measures the ratio of rules that a machine can fail on, to rules that only a
model can choose to honour. That number is the health metric for the plugin. It is expected to
start LOW; the point is that it is visible and moves in one direction.

THE ANTI-FLATTERY RULE
----------------------
The classification is DERIVED FROM THE LINT TESTS, never asserted by hand. A rule counts as
`machine` only when a test that targets its file asserts a literal string contained in that
rule's text — i.e. deleting the rule would turn a test red. Everything else is `advisory`.

This matters because the first version of this script DID use a hand-written registry, and it
was wrong in both directions: a global substring match credited an unrelated skill's "ALWAYS ask
via AskUserQuestion" to the headless-mode test, while genuinely-covered rules went uncounted
because their sentence lacked the registry keyword. A metric you can talk yourself into is not a
metric. Deriving it from the tests also means it moves on its own the moment someone adds or
removes a lint, which is the only way a health number stays honest.

Known limit, stated rather than hidden: matching is per-line, so a rule spanning two lines can be
missed, and a long asserted literal can match a neighbouring sentence. Treat the ratio as an
order-of-magnitude signal and a direction of travel, not a precise score.

Usage:
  python scripts/enforcement_inventory.py            # summary + ratio
  python scripts/enforcement_inventory.py --list     # every rule, classified
  python scripts/enforcement_inventory.py --advisory # only the unenforced ones
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
SCAN_ROOTS = [REPO / "claude-harness" / "commands", REPO / ".github" / "skills"]

# An imperative that makes a promise. Ordered longest-first so MUST NOT wins over MUST.
IMPERATIVE = re.compile(
    r"\b(MUST NOT|MUST|NEVER|ALWAYS|REQUIRED|STOP|DO NOT|Do not)\b"
)

# ── Deriving enforcement FROM THE TESTS, not from a hand-written claim ──────
# An earlier version used a hand-maintained registry of rule->enforcer. It was wrong in both
# directions: a global substring match credited brand-design's "ALWAYS ask via AskUserQuestion"
# to the headless-mode test, which has nothing to do with it, while genuinely-covered rules went
# uncounted because their sentence lacked the registry's keyword.
#
# So the classifier now READS THE LINT TESTS. For each test module it works out which source
# files that module targets (from its module-level Path constants) and which literal strings it
# asserts on. A rule is `machine` when a test targeting ITS file asserts a literal contained in
# its text. Nothing is claimed that a test does not actually check, and the metric updates itself
# the moment someone adds or deletes a lint - which is the property a health metric must have.
LINT_TEST_DIRS = [REPO / "scripts" / "tests", REPO / "claude-harness" / "hooks" / "tests"]

# Literals shorter than this match too much to mean anything.
MIN_LITERAL = 10


def _test_modules() -> list[tuple[set[str], set[str]]]:
    """(source files this test targets, literals it asserts) for every lint test module."""
    import ast
    out = []
    for d in LINT_TEST_DIRS:
        if not d.exists():
            continue
        for f in sorted(d.glob("test_*.py")):
            if f.name == "test_enforcement_inventory.py":
                continue  # measures the metric; must not feed it
            try:
                tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError:
                continue
            # ONLY literals inside an `assert` count. Scanning every string constant swept in
            # docstrings and fixture data, and this module's own test docstrings describe the very
            # rules being measured - so prose about a rule was being counted as enforcement OF that
            # rule. The metric was measuring how much we had WRITTEN about enforcement.
            literals: set[str] = set()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assert):
                    continue
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        v = sub.value.strip()
                        if len(v) >= MIN_LITERAL:
                            literals.add(v)
            # TARGETS come from ALL string constants, not just asserts: a module names the file
            # it lints in a module-level Path constant (`_IMPLEMENT = ... / "implement.md"`), which
            # is not an assert. Deriving both from the assert set emptied every target and drove
            # the ratio to a false 0.0% - caught by this module's own plausibility test.
            targets = {
                v.strip() for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
                for v in [node.value] if v.strip().endswith(".md")
            }
            out.append((targets, literals))
    return out


_MODULES = _test_modules()


def _enforcer_for(rel_path: str, text: str) -> str | None:
    """The lint that would fail if this rule were deleted, or None."""
    fname = rel_path.rsplit("/", 1)[-1]
    for targets, literals in _MODULES:
        if not any(t == fname or t.endswith(fname) for t in targets):
            continue
        for lit in literals:
            if lit.lower() in text.lower():
                return "lint"
    return None


# ── Gates: rules enforced by an executable, not merely by a content lint ────
# The first version counted only lint tests, so a rule backed by a REAL gate scored the same as
# one backed by nothing - the metric was blind to the strongest form of enforcement and would
# have shown no movement for the phase that introduced it. A rule counts as gate-enforced when
# its file invokes caddis_gate.py AND the rule concerns one of the gate's actual subcommands.
# The subcommand must exist in the script: a claim nobody implements is exactly what this file
# refuses to reward.
GATE_SCRIPT = REPO / "scripts" / "caddis_gate.py"
GATE_CONCERNS = {
    "lane-check": ("lane", "spawn", "launch command", "--print", "-p"),
    "verdict-gate": ("verdict", "advisory-hub", "blocked-pending-hub", "accept-degraded"),
    "tracker-vs-git": ("tracker",),
}


def _live_gates() -> dict[str, tuple[str, ...]]:
    """Subcommands the gate script actually implements. Verified, never assumed."""
    if not GATE_SCRIPT.is_file():
        return {}
    src = GATE_SCRIPT.read_text(encoding="utf-8", errors="ignore")
    return {k: v for k, v in GATE_CONCERNS.items() if f'"{k}"' in src or f"'{k}'" in src}


_GATES = _live_gates()


def _gate_for(file_text: str, text: str) -> str | None:
    if "caddis_gate.py" not in file_text:
        return None
    low = text.lower()
    for sub, needles in _GATES.items():
        if any(n.lower() in low for n in needles):
            return sub
    return None


@dataclass
class Rule:
    path: str
    line: int
    marker: str
    text: str
    enforcer: str | None = None

    @property
    def machine(self) -> bool:
        return self.enforcer is not None


def _sentence(line: str) -> str:
    return " ".join(line.split())[:150]


def collect(roots: list[Path] | None = None) -> list[Rule]:
    rules: list[Rule] = []
    for root in (roots or SCAN_ROOTS):
        if not root.exists():
            continue
        for f in sorted(root.rglob("*.md")):
            try:
                lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
            except Exception:
                continue
            # Fall back to the absolute path for roots outside the repo, so collect() can be
            # pointed at a fixture directory. A metric script that cannot be tested on a fixture
            # can only be verified by eyeballing its output, which is how metrics start lying.
            whole = "\n".join(lines)
            try:
                rel = str(f.relative_to(REPO)).replace("\\", "/")
            except ValueError:
                rel = str(f).replace("\\", "/")
            for i, line in enumerate(lines, 1):
                m = IMPERATIVE.search(line)
                if not m:
                    continue
                text = _sentence(line)
                enf = _enforcer_for(rel, text) or _gate_for(whole, text)
                rules.append(Rule(rel, i, m.group(1), text, enf))
    return rules


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="caddis enforcement inventory")
    ap.add_argument("--list", action="store_true", help="print every rule, classified")
    ap.add_argument("--advisory", action="store_true", help="print only the unenforced rules")
    args = ap.parse_args(argv)

    rules = collect()
    machine = [r for r in rules if r.machine]
    advisory = [r for r in rules if not r.machine]
    total = len(rules)
    ratio = (len(machine) / total) if total else 0.0

    if args.list or args.advisory:
        for r in rules:
            if args.advisory and r.machine:
                continue
            tag = f"machine <- {r.enforcer}" if r.machine else "advisory"
            print(f"  [{tag}] {r.path}:{r.line}  {r.marker}")
            print(f"      {r.text}")
        print()

    # Report the SPLIT, not just the headline. A single blended number is actively misleading:
    # it is dominated by the ~235 skill rules, which are guidance ("prefer this", "consider that")
    # and SHOULD be advisory - turning them into exit codes would be theatre. The number that
    # matters is commands, because that is the execution path where a broken guarantee costs you.
    cmd = [r for r in rules if "/commands/" in r.path]
    skl = [r for r in rules if "/commands/" not in r.path]
    def _pct(group):
        return (sum(1 for r in group if r.machine) / len(group)) if group else 0.0

    print("=" * 62)
    print(f"  load-bearing rules found : {total}")
    print(f"  machine-enforced         : {len(machine)}")
    print(f"  advisory only            : {len(advisory)}")
    print("-" * 62)
    print(f"  COMMANDS (execution path): {sum(1 for r in cmd if r.machine)}/{len(cmd)}  "
          f"= {_pct(cmd):.1%}   <- the figure that matters")
    print(f"  SKILLS   (guidance)      : {sum(1 for r in skl if r.machine)}/{len(skl)}  "
          f"= {_pct(skl):.1%}   (advisory is correct here)")
    print(f"  blended                  : {ratio:.1%}")
    print("=" * 62)
    print("  A low number is not a bug report - it is the starting point. Advisory rules are")
    print("  legitimate; the danger is an advisory rule that READS like a guarantee. Move the")
    print("  load-bearing ones to exit codes, and label the rest honestly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
