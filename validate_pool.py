"""
validate_pool.py  —  Companion pool validator for the caddis resource pool.

Complements validate_agents.py (which checks agent-file structure). This validator
checks the broader pool: registry consistency, gate consistency, public-resource
privacy scan, generated-artifact scan, prompt frontmatter, skill registry drift,
and golden-plan quality.

Exit codes:
  0  all checks passed
  1  one or more checks failed

Usage:
  python validate_pool.py
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


REPO_ROOT = Path(__file__).resolve().parent
GITHUB_DIR = REPO_ROOT / ".github"
AGENTS_DIR = GITHUB_DIR / "agents"
PROMPTS_DIR = GITHUB_DIR / "prompts"
SKILLS_DIR = GITHUB_DIR / "skills"
SKILLS_REGISTRY = SKILLS_DIR / "_registry.md"
RUNTIME_TARGETS = GITHUB_DIR / "runtime-targets.json"
DIST_RUNTIME_ROOT = REPO_ROOT / "dist" / "runtime-resources"
POOL_SYNC_DIR = GITHUB_DIR / "tools" / "pool-sync"
GOLDEN_PLAN_SKILL = SKILLS_DIR / "workflow" / "golden-plan" / "SKILL.md"
DENYLIST_EXCEPTIONS = GITHUB_DIR / "tools" / "pool-validator" / "denylist-exceptions.txt"
DOC_FRONTMATTER_INSTRUCTION = GITHUB_DIR / "instructions" / "document-frontmatter.instructions.md"
DOC_FRONTMATTER_REQUIRED_FIELDS = [
    "Original Author",
    "Creation Date",
    "Creating Model",
    "Last Author",
    "Last Updated",
    "Last Model Used",
]
DOC_FRONTMATTER_REQUIRED_PHRASES = [
    "ISO 8601",
    "YYYY-MM-DDTHH:MM:SSZ",
]
DOC_FRONTMATTER_REFERENCERS = [
    GITHUB_DIR / "instructions" / "plan-mode.instructions.md",
    GITHUB_DIR / "skills" / "docs" / "code-documentation" / "SKILL.md",
    GITHUB_DIR / "skills" / "docs" / "technical-writing" / "SKILL.md",
    GITHUB_DIR / "skills" / "docs" / "writing-plans" / "SKILL.md",
    GITHUB_DIR / "skills" / "docs" / "architecture-document" / "SKILL.md",
    GITHUB_DIR / "skills" / "docs" / "doc-coauthoring" / "SKILL.md",
    GITHUB_DIR / "skills" / "workflow" / "brainstorming" / "SKILL.md",
    GITHUB_DIR / "skills" / "workflow" / "golden-plan" / "SKILL.md",
    GITHUB_DIR / "skills" / "workflow" / "intent-writer" / "SKILL.md",
    GITHUB_DIR / "skills" / "workflow" / "preflight" / "SKILL.md",
    GITHUB_DIR / "prompts" / "plan.prompt.md",
    GITHUB_DIR / "prompts" / "adr.prompt.md",
    GITHUB_DIR / "prompts" / "documentation-writer.prompt.md",
    GITHUB_DIR / "prompts" / "api-documentation.prompt.md",
    GITHUB_DIR / "prompts" / "create-readme.prompt.md",
    GITHUB_DIR / "prompts" / "generate-hld-lld.prompt.md",
    GITHUB_DIR / "prompts" / "new-feature.prompt.md",
    GITHUB_DIR / "prompts" / "project-setup.prompt.md",
]

# External pool roots that are checked when present. Only this repo's own build output — the old
# hardcoded mirror paths (E:\Projects\junai-vscode\pool, E:\Projects\junai\.github) were predecessor-repo
# artefacts and are dropped in the extraction; Phase 3 re-adds mirror roots (configurable) if needed.
EXTRA_POOL_ROOTS = [
    REPO_ROOT / "dist" / "runtime-resources",
]

# Models allowed in prompt frontmatter (matches validate_agents.KNOWN_MODELS)
KNOWN_MODELS = {
    "Claude Opus 4.6",
    "Claude Opus 4.8",
    "Claude Sonnet 4.6",
    "Gemini 3.1 Pro (Preview)",
    "GPT-5.3-Codex",
    "GPT-5.4",
    "GPT-5.4-mini",
}

# Privacy denylist — case-insensitive substring matches
PRIVACY_SUBSTRINGS = [
    "git.local",
    "vmie-admin",
    "vmie-",
    "***REDACTED-CRED***",
    "***REDACTED-HASH***",
    "@vmie.local",
    r"\\vmie",
    # Internal hosts / bot-token names / usernames — added 2026-07-16 after the Fable privacy audit
    # found these shipping in the public bundle. The class must fail-closed, not be allowlisted (real infra).
    "iegbcoppoc",
    "ievxcoppoc",
    "gitea.internal",
    "VMIE_BOT_TOKEN",
    # Real internal product codenames — found leaking into ui-brief.md / design-md / popular-web-designs
    # skill-routing examples during the Track B2 public-readiness sweep (2026-07-20), genericized there.
    # These four are specific enough to be unambiguous internal identifiers (not generic English), so
    # they fail-closed here rather than being allowlisted — a bare "vmie" mention stays permitted (it's
    # also used as a legitimate, intentional category label for the private-skill opt-in mechanism, e.g.
    # setup-project-ai.md's "deploy vmie skills (optional, personal)" step).
    "appointment-assist",
    "nps-lens",
    "rev-sight",
    "app-sight",
    # Internal-tool references found leaking as "learned from X" provenance comments / worked
    # examples (check_doc_coverage.py, test_hook_paths.py, an onboarding runbook + recipe runbook
    # excluded from export entirely) during the same B2 sweep — an internal scaffolding tool with
    # no public existence, so genericizing a mention of it would describe something readers can't
    # use anyway.
    "platform-infra",
    "new-vmie-project",
]

# Privacy denylist — regex matches
PRIVACY_REGEXES = [
    re.compile(r"\b[a-f0-9]{40}\b"),
    re.compile(r"(?i)(password|token|api[_-]?key)\s*[:=]\s*['\"][^'\"]{8,}"),
]

# Generated artifacts forbidden under distributable resource folders
GENERATED_ARTIFACTS = {
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    ".coverage",
    "htmlcov",
    ".ruff_cache",
}

# File extensions to scan for privacy violations
SCAN_TEXT_EXTENSIONS = {".md", ".py", ".json", ".yml", ".yaml", ".txt", ".js", ".ts", ".tsx", ".jsx"}
REQUIRED_OWNED_TOP_LEVEL_PATHS = [
    "agent-docs",
    "plans",
    "handoffs",
    "pipeline-state.json",
    ".pool-version",
    "project-config.md",
]

if str(POOL_SYNC_DIR) not in sys.path:
    sys.path.insert(0, str(POOL_SYNC_DIR))


# ---------------------------------------------------------------------------
# Result accumulation
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    name: str
    passed: bool = True
    failures: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)


def _print_check(result: CheckResult) -> None:
    status = "[OK]  " if result.passed else "[FAIL]"
    print(f"{status} {result.name}")
    for line in result.info:
        print(f"        {line}")
    for line in result.failures:
        print(f"        - {line}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_path_allowlist() -> list[str]:
    """Load path-substring allowlist (one pattern per line). Patterns match against
    both forward-slash and backslash forms of the file path."""
    if not DENYLIST_EXCEPTIONS.exists():
        return []
    out: list[str] = []
    for line in DENYLIST_EXCEPTIONS.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


def _is_allowlisted(path: Path, allowlist: list[str]) -> bool:
    if not allowlist:
        return False
    forward = str(path).replace("\\", "/")
    back = str(path).replace("/", "\\")
    for pat in allowlist:
        norm = pat.replace("\\", "/")
        if norm in forward or pat in back:
            return True
    return False


def _read_text_safe(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _load_pool_manifest():
    try:
        from manifest import load_manifest  # type: ignore[import]

        return load_manifest(REPO_ROOT), None
    except Exception as exc:  # noqa: BLE001
        return None, exc


def _generated_registry_text() -> tuple[str | None, Exception | None]:
    try:
        from generate_registry import render_registry, collect_public_skills  # type: ignore[import]

        return render_registry(collect_public_skills(REPO_ROOT)), None
    except Exception as exc:  # noqa: BLE001
        return None, exc


def _generated_public_skill_paths() -> tuple[set[str] | None, Exception | None]:
    try:
        from generate_registry import collect_public_skills  # type: ignore[import]

        return {skill.path for skill in collect_public_skills(REPO_ROOT)}, None
    except Exception as exc:  # noqa: BLE001
        return None, exc


def _split_frontmatter(text: str) -> tuple[dict, str] | None:
    # Tolerate VS Code prompt-file convention where frontmatter is wrapped
    # in a ```prompt ... ``` code fence.
    stripped = text.lstrip()
    if stripped.startswith("```"):
        nl = stripped.find("\n")
        if nl != -1:
            stripped = stripped[nl + 1 :]
    if not stripped.startswith("---"):
        return None
    try:
        end = stripped.index("\n---", 3)
    except ValueError:
        return None
    fm_text = stripped[3:end].lstrip("\n")
    body = stripped[end + 4 :]
    try:
        meta = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(meta, dict):
        return None
    return meta, body


# ---------------------------------------------------------------------------
# Check 1 — Manifest classification
# ---------------------------------------------------------------------------

def check_manifest_contract() -> CheckResult:
    r = CheckResult(name="Manifest contract — tiers, ownership, classification")
    manifest, error = _load_pool_manifest()
    if error is not None or manifest is None:
        r.passed = False
        r.failures.append(f"Could not load pool manifest: {error}")
        return r

    r.info.append(f"top-level classified paths: {len(manifest.top_level_tiers)}")
    r.info.append(f"profiles: {sorted(manifest.profiles)}")

    for path in REQUIRED_OWNED_TOP_LEVEL_PATHS:
        tier = manifest.top_level_tiers.get(path)
        if tier != "owned":
            r.failures.append(f"{path} must be tier 'owned', found {tier!r}")

    if manifest.top_level_tiers.get("copilot-instructions.md") != "managed_region":
        r.failures.append("copilot-instructions.md must be tier 'managed_region'")

    r.passed = not r.failures
    return r


def check_agy_plugin_target() -> CheckResult:
    """Lint the antigravity-plugin (agy) export target so the shipped agy plugin stays valid:
    an `agy_plugin` block with a name, and a skills roster that resolves (via `included_skills_from`
    to a real sibling target, or an inline `included_skills`) — else the bundle would ship empty or
    name a phantom skill. Source-level (reads .github/runtime-targets.json); runs by default."""
    r = CheckResult(name="Antigravity plugin target — agy plugin.json + roster")
    rt = GITHUB_DIR / "runtime-targets.json"
    try:
        manifest = json.loads(rt.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        r.passed = False
        r.failures.append(f"could not load runtime-targets.json: {exc}")
        return r
    targets = {t["name"]: t for t in manifest.get("targets", [])}
    agy = targets.get("antigravity-plugin")
    if agy is None:
        r.info.append("no antigravity-plugin target — skipped")
        return r
    if not (agy.get("agy_plugin") or {}).get("name"):
        r.failures.append("antigravity-plugin: agy_plugin.name is required (agy plugin.json needs a name)")
    skills_copy = next((c for c in agy.get("copies", []) if c.get("source", "").replace("\\", "/").strip("/") == "skills"), None)
    if skills_copy is None:
        r.failures.append("antigravity-plugin: no skills copy — the plugin would ship no skills")
    else:
        roster = skills_copy.get("included_skills")
        if not roster:
            ref = skills_copy.get("included_skills_from")
            ref_t = targets.get(ref) if ref else None
            if ref_t is None:
                r.failures.append(f"antigravity-plugin: included_skills_from '{ref}' is not a known target")
            else:
                ref_copy = next((c for c in ref_t.get("copies", []) if c.get("source", "").replace("\\", "/").strip("/") == "skills"), None)
                roster = (ref_copy or {}).get("included_skills")
                if not roster:
                    r.failures.append(f"antigravity-plugin: included_skills_from '{ref}' has no skills roster to reuse")
        if roster:
            skills_root = GITHUB_DIR / "skills"
            for cat, names in roster.items():
                cat_dir = skills_root / cat
                if not cat_dir.is_dir():
                    r.failures.append(f"antigravity-plugin roster: category '{cat}' does not exist under skills/")
                    continue
                present = {p.name for p in cat_dir.iterdir() if p.is_dir()}
                for sk in names:
                    if sk not in present:
                        r.failures.append(f"antigravity-plugin roster: skill '{cat}/{sk}' does not exist")
            r.info.append(f"roster categories: {len(roster)}")
    r.passed = not r.failures
    return r


# ---------------------------------------------------------------------------
# (Checks 2–3 — pipeline-runner registry + gate-consistency — removed 2026-07-20
#  when the Copilot-era pipeline-runner was retired; superseded by docket.)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Check 4 — Public-resource privacy scan
# ---------------------------------------------------------------------------

def _scan_text_for_privacy(text: str) -> list[str]:
    hits: list[str] = []
    lower = text.lower()
    for needle in PRIVACY_SUBSTRINGS:
        if needle.lower() in lower:
            hits.append(f"substring match: {needle!r}")
    for rx in PRIVACY_REGEXES:
        for m in rx.finditer(text):
            sample = m.group(0)
            hits.append(f"regex {rx.pattern!r} matched: {sample!r}")
    return hits


def _iter_pool_files(root: Path) -> list[Path]:
    out: list[Path] = []
    if not root.exists():
        return out
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        # Skip vmie/ folder — private by design
        try:
            rel_parts = p.relative_to(root).parts
        except ValueError:
            rel_parts = p.parts
        if "vmie" in rel_parts:
            continue
        # Skip .github/plans/ — planning artefacts are intentionally source-only,
        # not distributable pool content.
        if root == GITHUB_DIR and "plans" in rel_parts:
            continue
        if any(part in GENERATED_ARTIFACTS for part in rel_parts):
            continue
        if p.suffix.lower() in SCAN_TEXT_EXTENSIONS:
            out.append(p)
    return out


def check_privacy_scan(roots: list[Path]) -> CheckResult:
    r = CheckResult(name="Privacy scan — public resource folders")
    allowlist = _load_path_allowlist()

    total_files = 0
    skipped = 0
    for root in roots:
        for f in _iter_pool_files(root):
            total_files += 1
            if _is_allowlisted(f, allowlist):
                skipped += 1
                continue
            if f.resolve() == DENYLIST_EXCEPTIONS.resolve():
                continue
            if f.resolve() == Path(__file__).resolve():
                continue
            text = _read_text_safe(f)
            if text is None:
                continue
            hits = _scan_text_for_privacy(text)
            if hits:
                rel = f.relative_to(REPO_ROOT) if REPO_ROOT in f.parents else f
                for h in hits:
                    r.failures.append(f"{rel}: {h}")

    r.info.append(f"scanned {total_files} files across {len(roots)} root(s)")
    if allowlist:
        r.info.append(f"loaded {len(allowlist)} allowlist pattern(s); skipped {skipped} file(s)")
    r.passed = not r.failures
    return r


def check_privacy_scan_tracked() -> CheckResult:
    """Privacy scan over EVERY git-tracked file, not just the pool.

    `check_privacy_scan` above only ever looks at the roots in `_resolve_scan_roots`,
    which starts at `.github/`. That is the pool — but the repo is PUBLIC, and a visitor
    sees every tracked file. On 2026-08-05 that blind spot was holding four internal audit
    reports under `docs/analysis/` and 25 working-record files under `.caddis/`, carrying
    internal hostnames, a bot-token name and fleet app names — every one of them already in
    PRIVACY_SUBSTRINGS. The denylist was right; nothing had ever pointed it at those paths.

    Generated mirrors are skipped: they derive from source, so fixing the source fixes them,
    and reporting both doubles every finding. Untracked files are skipped because they are
    not published — local caches (`.mypy_cache`) otherwise drown the signal in SHA noise.
    """
    r = CheckResult(name="Privacy scan — every tracked file (public surface)")
    allowlist = _load_path_allowlist()

    try:
        tracked = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files"],
            capture_output=True, text=True, timeout=60,
        )
    except Exception as exc:  # pragma: no cover — git absent is not a privacy failure
        r.info.append(f"skipped — could not list tracked files ({exc})")
        r.passed = True
        return r
    if tracked.returncode != 0:
        r.info.append("skipped — not a git repo")
        r.passed = True
        return r

    # Mirrors are generated from source; fix the source and they follow.
    #
    # `.caddis/` and `docs/` are the WORKING RECORD and are excluded deliberately. This repo
    # (saajunaid/caddis) is PRIVATE as of 2026-08-05; the thing the public sees is the generated
    # mirror saajunaid/caddis-plugin, which carries `.github/`, the bundles, and a handful of root
    # scripts — and zero `.caddis/` or `docs/` files (verified against the mirror's index). So an
    # internal hostname in a plan or a parking-lot note cannot reach anyone, while the same string
    # in `claude-harness/` or a root script can. Scanning the working record would fail the build
    # over notes that are private by construction, and a check that cries wolf gets switched off.
    skip_prefixes = ("dist/", "cli/bundles/", "vscode-extensions/", ".caddis/", "docs/")
    scanned = skipped = 0
    for rel in tracked.stdout.splitlines():
        if rel.startswith(skip_prefixes):
            continue
        f = REPO_ROOT / rel
        if f.suffix.lower() not in SCAN_TEXT_EXTENSIONS:
            continue
        if _is_allowlisted(f, allowlist):
            skipped += 1
            continue
        if f.resolve() == DENYLIST_EXCEPTIONS.resolve() or f.resolve() == Path(__file__).resolve():
            continue
        text = _read_text_safe(f)
        if text is None:
            continue
        scanned += 1
        for h in _scan_text_for_privacy(text):
            r.failures.append(f"{rel}: {h}")

    r.info.append(f"scanned {scanned} tracked file(s) outside the generated mirrors")
    if skipped:
        r.info.append(f"{skipped} allowlisted")
    r.passed = not r.failures
    return r


def check_enforcement_ratio() -> CheckResult:
    """Report the enforcement ratio. INFORMATIONAL — never fails the build.

    How many of caddis's load-bearing rules (MUST / NEVER / STOP / REQUIRED) can a machine fail
    on, versus how many only a model can choose to honour? Three audits independently found that
    stripping the prose leaves very little machine content, and an advisory rule that READS like a
    guarantee is worse than one that reads like advice.

    Deliberately not a gate: a threshold here would tempt someone to hit the number by deleting
    the word MUST from a paragraph, which improves the ratio and nothing else. It is a direction
    of travel, printed where it cannot be ignored.
    """
    r = CheckResult(name="Enforcement ratio — machine-enforced vs advisory rules")
    try:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        import enforcement_inventory as ei
        rules = ei.collect()
        machine = [x for x in rules if x.machine]
        ratio = (len(machine) / len(rules)) if rules else 0.0
        cmd = [x for x in rules if "/commands/" in x.path]
        cmd_m = sum(1 for x in cmd if x.machine)
        r.info.append(f"commands (execution path): {cmd_m}/{len(cmd)} = "
                      f"{(cmd_m/len(cmd) if cmd else 0):.1%} — the figure that matters")
        r.info.append(f"blended incl. skills: {len(machine)}/{len(rules)} = {ratio:.1%} "
                      "(skill guidance is advisory by design)")
        r.info.append("informational only — `python scripts/enforcement_inventory.py --advisory` "
                      "lists the unenforced ones")
    except Exception as exc:  # pragma: no cover — never break the validator over a metric
        r.info.append(f"skipped — {exc}")
    r.passed = True
    return r


# ---------------------------------------------------------------------------
# Check 5 — Generated artifacts under distributable folders
# ---------------------------------------------------------------------------

def check_generated_artifacts(roots: list[Path]) -> CheckResult:
    """Flag generated artifacts only in distributable roots (dist/, external mirrors).
    The source `.github/` folder is excluded — these caches are local build artefacts,
    are gitignored, and never reach the pool."""
    r = CheckResult(name="Generated artifacts — must not appear in distributable pool")
    distributable = [p for p in roots if p != GITHUB_DIR]
    if not distributable:
        r.info.append("(skipped — no distributable roots in scope; rerun with --include-dist or --include-external)")
        return r
    for root in distributable:
        for p in root.rglob("*"):
            if p.name in GENERATED_ARTIFACTS:
                r.failures.append(f"{p}")
    r.passed = not r.failures
    return r


# ---------------------------------------------------------------------------
# Check 6 — Prompt frontmatter validation
# ---------------------------------------------------------------------------

def check_prompts() -> CheckResult:
    r = CheckResult(name="Prompts — frontmatter & model allowlist")
    if not PROMPTS_DIR.exists():
        r.passed = True
        r.info.append("(no prompts directory)")
        return r

    count = 0
    for p in sorted(PROMPTS_DIR.glob("*.prompt.md")):
        count += 1
        text = _read_text_safe(p)
        if text is None:
            r.failures.append(f"{p.name}: cannot read")
            continue
        parsed = _split_frontmatter(text)
        if parsed is None:
            r.failures.append(f"{p.name}: missing or invalid YAML frontmatter")
            continue
        meta, _ = parsed
        if not str(meta.get("description", "")).strip():
            r.failures.append(f"{p.name}: missing 'description' in frontmatter")
        model = meta.get("model")
        if model and model not in KNOWN_MODELS:
            r.failures.append(f"{p.name}: model '{model}' not in KNOWN_MODELS")

    r.info.append(f"validated {count} prompt file(s)")
    r.passed = not r.failures
    return r


def check_prompts_in_dir(prompts_dir: Path, label: str) -> CheckResult:
    r = CheckResult(name=f"Prompts — frontmatter ({label})")
    if not prompts_dir.exists():
        r.passed = True
        r.info.append("(no prompts directory)")
        return r

    count = 0
    for p in sorted(prompts_dir.glob("*.prompt.md")):
        count += 1
        text = _read_text_safe(p)
        if text is None:
            r.failures.append(f"{p.name}: cannot read")
            continue
        parsed = _split_frontmatter(text)
        if parsed is None:
            r.failures.append(f"{p.name}: missing or invalid YAML frontmatter")
            continue
        meta, _ = parsed
        if not str(meta.get("description", "")).strip():
            r.failures.append(f"{p.name}: missing 'description' in frontmatter")
        model = meta.get("model")
        if model and model not in KNOWN_MODELS:
            r.failures.append(f"{p.name}: model '{model}' not in KNOWN_MODELS")

    r.info.append(f"validated {count} prompt file(s)")
    r.passed = not r.failures
    return r


# ---------------------------------------------------------------------------
# Check 7 — Skill frontmatter + registry drift
# ---------------------------------------------------------------------------

def check_skill_frontmatter() -> CheckResult:
    r = CheckResult(name="Skills — frontmatter contract")
    count = 0
    for skill_md in sorted(SKILLS_DIR.rglob("SKILL.md")):
        count += 1
        text = _read_text_safe(skill_md)
        if text is None:
            r.failures.append(f"{skill_md.relative_to(REPO_ROOT)}: cannot read")
            continue
        parsed = _split_frontmatter(text)
        if parsed is None:
            r.failures.append(
                f"{skill_md.relative_to(REPO_ROOT)}: missing or invalid YAML frontmatter"
            )
            continue
        meta, _ = parsed
        for field_name in ("name", "description"):
            if not str(meta.get(field_name, "")).strip():
                r.failures.append(
                    f"{skill_md.relative_to(REPO_ROOT)}: missing '{field_name}' in frontmatter"
                )
    r.info.append(f"validated {count} skill file(s)")
    r.passed = not r.failures
    return r

def _disk_public_skills() -> set[str]:
    """Return set of '<category>/<skill>/' paths present on disk, excluding vmie."""
    out: set[str] = set()
    if not SKILLS_DIR.exists():
        return out
    for skill_md in SKILLS_DIR.rglob("SKILL.md"):
        rel = skill_md.relative_to(SKILLS_DIR).parts
        if not rel:
            continue
        # Ignore vmie/* entirely
        if rel[0] == "vmie" or "vmie" in rel:
            continue
        if len(rel) < 2:
            # SKILL.md directly under skills/ — not a categorized public skill
            continue
        # Rejoin everything except trailing SKILL.md
        path = "/".join(rel[:-1]) + "/"
        out.add(path)
    return out


def _disk_public_skills_from_dir(skills_dir: Path) -> set[str]:
    """Return set of '<category>/<skill>/' paths present on disk, excluding vmie."""
    out: set[str] = set()
    if not skills_dir.exists():
        return out
    for skill_md in skills_dir.rglob("SKILL.md"):
        rel = skill_md.relative_to(skills_dir).parts
        if not rel:
            continue
        if rel[0] == "vmie" or "vmie" in rel:
            continue
        if len(rel) < 2:
            continue
        out.add("/".join(rel[:-1]) + "/")
    return out


def _registry_listed_skills() -> set[str]:
    if not SKILLS_REGISTRY.exists():
        return set()
    text = SKILLS_REGISTRY.read_text(encoding="utf-8")
    # Match `cat/skill/` or `cat/sub/skill/` paths inside backticks. Path segments
    # are lowercase alphanumeric with hyphens/underscores, two or more segments.
    pattern = re.compile(r"`((?:[a-z0-9_\-]+/){2,}[a-z0-9_\-]+/)`")
    found = set(pattern.findall(text))
    # Also accept exact two-segment form
    pattern2 = re.compile(r"`([a-z0-9_\-]+/[a-z0-9_\-]+/)`")
    found |= set(pattern2.findall(text))
    return found


def _registry_listed_skills_from_file(registry_file: Path) -> set[str]:
    if not registry_file.exists():
        return set()
    text = registry_file.read_text(encoding="utf-8")
    pattern = re.compile(r"`((?:[a-z0-9_\-]+/){2,}[a-z0-9_\-]+/)`")
    found = set(pattern.findall(text))
    pattern2 = re.compile(r"`([a-z0-9_\-]+/[a-z0-9_\-]+/)`")
    found |= set(pattern2.findall(text))
    return found


def check_skill_registry() -> CheckResult:
    r = CheckResult(name="Skill registry — _registry.md vs disk")
    expected, generation_error = _generated_registry_text()
    if generation_error is not None or expected is None:
        r.passed = False
        r.failures.append(f"Could not generate expected registry: {generation_error}")
        return r

    disk, disk_error = _generated_public_skill_paths()
    if disk_error is not None or disk is None:
        r.passed = False
        r.failures.append(f"Could not enumerate public skills: {disk_error}")
        return r

    listed = _registry_listed_skills()

    missing_in_registry = disk - listed
    extra_in_registry = listed - disk
    for s in sorted(missing_in_registry):
        r.failures.append(f"Skill on disk but not in _registry.md: {s}")
    for s in sorted(extra_in_registry):
        r.failures.append(f"Skill listed in _registry.md but not on disk: {s}")

    current_text = _read_text_safe(SKILLS_REGISTRY)
    if current_text is None:
        r.failures.append(f"Cannot read skill registry: {SKILLS_REGISTRY.relative_to(REPO_ROOT)}")
    elif current_text != expected:
        r.failures.append(
            "Skill registry content does not match generated output from SKILL.md frontmatter"
        )

    r.info.append(f"disk={len(disk)} listed={len(listed)}")
    r.passed = not r.failures
    return r


def check_skill_registry_in_dir(skills_dir: Path, label: str) -> CheckResult:
    r = CheckResult(name=f"Skill registry — _registry.md vs disk ({label})")
    disk = _disk_public_skills_from_dir(skills_dir)
    listed = _registry_listed_skills_from_file(skills_dir / "_registry.md")

    missing_in_registry = disk - listed
    for s in sorted(missing_in_registry):
        r.failures.append(f"Skill on disk but not in _registry.md: {s}")
    extra_in_registry = listed - disk
    if extra_in_registry:
        r.info.append(f"extra registry-only entries (allowed in profile mode): {len(extra_in_registry)}")

    r.info.append(f"disk={len(disk)} listed={len(listed)}")
    r.passed = not r.failures
    return r


def _load_manifest_target(profile: str) -> dict | None:
    if not RUNTIME_TARGETS.exists():
        return None
    try:
        data = json.loads(RUNTIME_TARGETS.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    for target in data.get("targets", []):
        if target.get("name") == profile:
            return target
    return None


def check_profile_manifest_alignment(profile: str, profile_root: Path) -> CheckResult:
    r = CheckResult(name=f"Profile manifest alignment — {profile}")
    target = _load_manifest_target(profile)
    if target is None:
        r.passed = False
        r.failures.append(f"Profile '{profile}' not found in runtime-targets.json")
        return r

    for copy_spec in target.get("copies", []):
        excluded = set(copy_spec.get("excluded_names", []))
        included = set(copy_spec.get("included_names", []))
        if not excluded:
            destination = profile_root / copy_spec.get("destination", "")
        else:
            destination = profile_root / copy_spec.get("destination", "")
        if not destination.exists():
            continue
        if included:
            top_level_names = {child.name for child in destination.iterdir()}
            unexpected = top_level_names - included
            for name in sorted(unexpected):
                r.failures.append(
                    f"Unexpected entry leaked into profile: {copy_spec.get('destination')}/{name}"
                )
        if not excluded:
            continue
        for name in excluded:
            if (destination / name).exists():
                r.failures.append(
                    f"Excluded entry leaked into profile: {copy_spec.get('destination')}/{name}"
                )

    r.passed = not r.failures
    return r


def check_ptarmigan_content_restrictions(profile_root: Path) -> CheckResult:
    r = CheckResult(name="Ptarmigan ADLC restrictions — exact 6-agent roster and forbidden resources")

    # --- Agent roster: exactly these 6 ---
    required_agents = {
        "orchestrator.agent.md",
        "planner.agent.md",
        "preflight.agent.md",
        "implement.agent.md",
        "tester.agent.md",
        "code-reviewer.agent.md",
    }
    agents_dir = profile_root / "agents"
    if agents_dir.exists():
        present = {f.name for f in agents_dir.glob("*.agent.md")}
        for expected in sorted(required_agents):
            if expected not in present:
                r.failures.append(f"Ptarmigan ADLC agent missing: {expected}")
            for extra in sorted(present - required_agents):
                r.failures.append(f"Ptarmigan ADLC unexpected agent present: {extra}")
        r.info.append(f"agent files present: {len(present)}, required: {len(required_agents)}")
    else:
        r.failures.append("agents/ directory missing from Ptarmigan profile")

    # --- Forbidden stack-specific resources ---
    forbidden_paths = [
        profile_root / "instructions" / "streamlit.instructions.md",
        profile_root / "instructions" / "sql.instructions.md",
        profile_root / "instructions" / "sql-stored-procedures.instructions.md",
        profile_root / "instructions" / "mssql-dba.instructions.md",
        profile_root / "instructions" / "docker.instructions.md",
        profile_root / "instructions" / "github-actions.instructions.md",
        profile_root / "skills" / "coding" / "sql",
        profile_root / "skills" / "data",
        profile_root / "skills" / "cloud",
        profile_root / "skills" / "frontend" / "streamlit-dev",
        profile_root / "skills" / "frontend" / "streamlit-animate",
    ]
    checked = 0
    for forbidden in forbidden_paths:
        checked += 1
        if forbidden.exists():
            rel = forbidden.relative_to(profile_root)
            r.failures.append(f"Forbidden Ptarmigan resource present: {rel}")
    r.info.append(f"checked {checked} forbidden resources")
    r.passed = not r.failures
    return r


def check_liffey_content_restrictions(profile_root: Path) -> CheckResult:
    r = CheckResult(name="Liffey ADLC restrictions — exact 8-agent roster and forbidden resources")

    # --- Agent roster: exactly these 8 ---
    required_agents = {
        "orchestrator.agent.md",
        "prd.agent.md",
        "architect.agent.md",
        "planner.agent.md",
        "implement.agent.md",
        "tester.agent.md",
        "code-reviewer.agent.md",
        "devops.agent.md",
    }
    agents_dir = profile_root / "agents"
    if agents_dir.exists():
        present = {f.name for f in agents_dir.glob("*.agent.md")}
        for expected in sorted(required_agents):
            if expected not in present:
                r.failures.append(f"Liffey ADLC agent missing: {expected}")
        for extra in sorted(present - required_agents):
            r.failures.append(f"Liffey ADLC unexpected agent present: {extra}")
        r.info.append(f"agent files present: {len(present)}, required: {len(required_agents)}")
    else:
        r.failures.append("agents/ directory missing from Liffey profile")

    # --- Forbidden resources (stack-specific ones not in Liffey roster) ---
    forbidden_paths = [
        profile_root / "instructions" / "streamlit.instructions.md",
        profile_root / "instructions" / "sql.instructions.md",
        profile_root / "instructions" / "sql-stored-procedures.instructions.md",
        profile_root / "instructions" / "mssql-dba.instructions.md",
        profile_root / "skills" / "coding" / "sql",
        profile_root / "skills" / "cloud",
        profile_root / "skills" / "frontend" / "streamlit-dev",
        profile_root / "skills" / "frontend" / "streamlit-animate",
    ]
    checked = 0
    for forbidden in forbidden_paths:
        checked += 1
        if forbidden.exists():
            rel = forbidden.relative_to(profile_root)
            r.failures.append(f"Forbidden Liffey resource present: {rel}")
    r.info.append(f"checked {checked} forbidden resources")
    r.passed = not r.failures
    return r


# ---------------------------------------------------------------------------
# Check 9 — Claude Code plugin-bundle validation (profiles: claude, claude-extras)
# ---------------------------------------------------------------------------
#
# The shipped plugin bundle previously had ZERO validation (DECISIONS.md fix-regardless
# item). These checks guard the packaged bundle under dist/runtime-resources/<profile>/
# so a broken plugin (version drift, missing hook script, leaked secret) cannot publish.
#
#   claude        -> dist/runtime-resources/claude/plugin
#   claude-extras -> dist/runtime-resources/claude-extras/plugin-extras
#
# Checks:
#   (a) plugin.json shape + name/version match runtime-targets.json
#   (b) flattened SKILL.md frontmatter + roster count
#   (c) commands/agents/hooks present            (core plugin only)
#   (d) hooks.json command references resolve     (core plugin only)
#   (e) leak scan over the bundle                 (shared privacy scan)
#   (f) scripts/ contains every module the hooks import  (core plugin only;
#       catches the Dream Memory packaging bug — hooks importing scripts that
#       were never copied into the bundle, silently disabling the layer)

CLAUDE_PLUGIN_ROOTS = {
    "claude": DIST_RUNTIME_ROOT / "claude" / "plugin",
    "claude-extras": DIST_RUNTIME_ROOT / "claude-extras" / "plugin-extras",
}


def _claude_plugin_root(profile: str) -> Path:
    return CLAUDE_PLUGIN_ROOTS[profile]


def check_claude_plugin_manifest(profile: str, plugin_root: Path) -> CheckResult:
    """(a) plugin.json exists, is well-formed, and its name/version match the
    runtime-targets.json declaration for this profile."""
    r = CheckResult(name=f"Plugin manifest — {profile} (.claude-plugin/plugin.json)")
    plugin_json = plugin_root / ".claude-plugin" / "plugin.json"
    if not plugin_json.is_file():
        r.passed = False
        r.failures.append(f"Missing plugin.json: {plugin_json}")
        return r

    try:
        data = json.loads(plugin_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.passed = False
        r.failures.append(f"Invalid plugin.json JSON: {exc}")
        return r

    for key in ("name", "version", "description"):
        if not str(data.get(key, "")).strip():
            r.failures.append(f"plugin.json missing required key: {key!r}")

    version = str(data.get("version", "")).strip()
    if version and not re.fullmatch(r"\d+\.\d+\.\d+", version):
        r.failures.append(f"plugin.json version not semver X.Y.Z: {version!r}")

    target = _load_manifest_target(profile)
    if target is None:
        r.failures.append(f"Profile {profile!r} not found in runtime-targets.json")
    else:
        declared = target.get("plugin", {}) or {}
        declared_version = str(declared.get("version", "")).strip()
        declared_name = str(declared.get("name", "")).strip()
        if declared_version and version and declared_version != version:
            r.failures.append(
                f"Version drift: plugin.json={version!r} but runtime-targets.json={declared_version!r}"
            )
        if declared_name and str(data.get("name", "")).strip() != declared_name:
            r.failures.append(
                f"Name drift: plugin.json={data.get('name')!r} but runtime-targets.json={declared_name!r}"
            )

    r.info.append(f"name={data.get('name')!r} version={version!r}")
    r.passed = not r.failures
    return r


def check_claude_skills_bundle(profile: str, plugin_root: Path) -> CheckResult:
    """(b) skills are flattened (skills/<name>/SKILL.md), every SKILL.md carries
    name+description frontmatter, and the roster is non-empty with no orphan dirs."""
    r = CheckResult(name=f"Skill bundle — {profile} (flattened frontmatter + roster)")
    skills_dir = plugin_root / "skills"
    if not skills_dir.is_dir():
        r.passed = False
        r.failures.append(f"Missing skills/ directory: {skills_dir}")
        return r

    skill_mds = sorted(skills_dir.rglob("SKILL.md"))
    if not skill_mds:
        r.passed = False
        r.failures.append("No SKILL.md files found in bundle")
        return r

    for skill_md in skill_mds:
        rel_parts = skill_md.relative_to(skills_dir).parts
        # Flattened contract: exactly skills/<name>/SKILL.md (one dir segment).
        if len(rel_parts) != 2:
            r.failures.append(
                f"Skill not flattened (expected skills/<name>/SKILL.md): skills/{'/'.join(rel_parts)}"
            )
        text = _read_text_safe(skill_md)
        if text is None:
            r.failures.append(f"skills/{'/'.join(rel_parts)}: cannot read")
            continue
        parsed = _split_frontmatter(text)
        if parsed is None:
            r.failures.append(f"skills/{'/'.join(rel_parts)}: missing or invalid frontmatter")
            continue
        meta, _ = parsed
        for field_name in ("name", "description"):
            if not str(meta.get(field_name, "")).strip():
                r.failures.append(f"skills/{'/'.join(rel_parts)}: missing '{field_name}'")

    # Roster count: every immediate child dir of skills/ must contain a SKILL.md (no orphans).
    skill_dirs = [d for d in skills_dir.iterdir() if d.is_dir()]
    orphans = [d.name for d in skill_dirs if not (d / "SKILL.md").is_file()]
    for name in sorted(orphans):
        r.failures.append(f"Skill dir without SKILL.md (orphan in roster): skills/{name}")

    r.info.append(f"roster: {len(skill_mds)} skill(s), {len(skill_dirs)} dir(s)")
    r.passed = not r.failures
    return r


def check_claude_components_present(profile: str, plugin_root: Path) -> CheckResult:
    """(c) the core plugin ships commands/, agents/, and hooks/hooks.json — each non-empty."""
    r = CheckResult(name=f"Plugin components — {profile} (commands/agents/hooks)")
    commands = sorted((plugin_root / "commands").glob("*.md")) if (plugin_root / "commands").is_dir() else []
    agents = (
        sorted((plugin_root / "agents").glob("*.md")) if (plugin_root / "agents").is_dir() else []
    )
    hooks_json = plugin_root / "hooks" / "hooks.json"

    if not commands:
        r.failures.append("No command files under commands/*.md")
    if not agents:
        r.failures.append("No agent files under agents/*.md")
    if not hooks_json.is_file():
        r.failures.append("Missing hooks/hooks.json")

    r.info.append(f"commands={len(commands)} agents={len(agents)} hooks.json={hooks_json.is_file()}")
    r.passed = not r.failures
    return r


def check_claude_hooks_references(profile: str, plugin_root: Path) -> CheckResult:
    """(d) every command referenced in hooks.json resolves to a file in the bundle."""
    r = CheckResult(name=f"Hook references — {profile} (hooks.json commands resolve)")
    hooks_json = plugin_root / "hooks" / "hooks.json"
    if not hooks_json.is_file():
        r.passed = False
        r.failures.append(f"Missing hooks.json: {hooks_json}")
        return r
    try:
        data = json.loads(hooks_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        r.passed = False
        r.failures.append(f"Invalid hooks.json JSON: {exc}")
        return r

    # Extract ${CLAUDE_PLUGIN_ROOT}/<rel> references from every hook command string.
    ref_re = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\"'\s]+)")
    refs: set[str] = set()
    for event_hooks in (data.get("hooks") or {}).values():
        for matcher_block in event_hooks:
            for hook in matcher_block.get("hooks", []):
                cmd = str(hook.get("command", ""))
                refs.update(ref_re.findall(cmd))

    for rel in sorted(refs):
        target = plugin_root / rel
        if not target.is_file():
            r.failures.append(f"hooks.json references missing file: {rel}")

    r.info.append(f"resolved {len(refs)} hook command reference(s)")
    r.passed = not r.failures
    return r


def _stdlib_module_names() -> set[str]:
    names = set(getattr(sys, "stdlib_module_names", set()))
    names |= set(sys.builtin_module_names)
    return names


def check_claude_hook_imports(profile: str, plugin_root: Path) -> CheckResult:
    """(f) every non-stdlib module the hooks import must be shipped in scripts/ (or be
    a sibling hook). Catches the Dream Memory bug: hooks importing dream_memory/
    dream_capture that were never packaged, silently disabling the memory layer."""
    import ast

    r = CheckResult(name=f"Hook imports — {profile} (scripts/ ships every imported module)")
    hooks_dir = plugin_root / "hooks"
    scripts_dir = plugin_root / "scripts"
    if not hooks_dir.is_dir():
        r.passed = False
        r.failures.append(f"Missing hooks/ directory: {hooks_dir}")
        return r

    stdlib = _stdlib_module_names()
    hook_module_names = {p.stem for p in hooks_dir.glob("*.py")}
    imported: dict[str, str] = {}  # module -> first hook that imports it
    for py in sorted(hooks_dir.glob("*.py")):
        text = _read_text_safe(py)
        if text is None:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            r.failures.append(f"hooks/{py.name}: syntax error, cannot analyse imports ({exc})")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.setdefault(alias.name.split(".")[0], py.name)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    imported.setdefault(node.module.split(".")[0], py.name)

    def _shipped_in_scripts(mod: str) -> bool:
        return (scripts_dir / f"{mod}.py").is_file() or (scripts_dir / mod / "__init__.py").is_file()

    checked = 0
    for mod, source_hook in sorted(imported.items()):
        if mod in stdlib or mod in hook_module_names:
            continue
        checked += 1
        if not _shipped_in_scripts(mod):
            r.failures.append(
                f"hooks/{source_hook} imports '{mod}' but scripts/{mod}.py is not in the bundle"
            )

    r.info.append(f"non-stdlib hook imports checked: {checked}")
    r.passed = not r.failures
    return r


def run_claude_profile_checks(profile: str, plugin_root: Path, roots: list[Path]) -> list[CheckResult]:
    results = [
        check_claude_plugin_manifest(profile, plugin_root),
        check_claude_skills_bundle(profile, plugin_root),
        check_privacy_scan(roots),  # (e) leak scan
    ]
    # (c)/(d)/(f) apply to the core plugin (commands/agents/hooks); the extras bundle
    # is skills-only, so run the component/hook checks only when a hooks/ dir exists.
    if (plugin_root / "hooks").is_dir():
        results.insert(2, check_claude_components_present(profile, plugin_root))
        results.insert(3, check_claude_hooks_references(profile, plugin_root))
        results.append(check_claude_hook_imports(profile, plugin_root))
    return results


# ---------------------------------------------------------------------------
# Check 8 — Golden-plan quality
# ---------------------------------------------------------------------------

def check_golden_plan() -> CheckResult:
    r = CheckResult(name="Golden-plan SKILL.md — fence contract & self-sweep")
    if not GOLDEN_PLAN_SKILL.exists():
        r.passed = False
        r.failures.append(f"Missing: {GOLDEN_PLAN_SKILL.relative_to(REPO_ROOT)}")
        return r

    text = GOLDEN_PLAN_SKILL.read_text(encoding="utf-8")

    # Fence contract — Phase Prompt structure must reference loaded skills + instructions inside a fenced block
    if "### Phase Prompt" not in text:
        r.failures.append("Missing '### Phase Prompt' heading (fence contract section)")
    if "SKILLS TO READ FIRST" not in text:
        r.failures.append("Phase Prompt fence contract missing 'SKILLS TO READ FIRST' marker")
    if "INSTRUCTIONS TO FOLLOW" not in text:
        r.failures.append("Phase Prompt fence contract missing 'INSTRUCTIONS TO FOLLOW' marker")

    # Self-sweep — Phase 3 heading + decay-signal regex examples
    if "## Phase 3 — Self-Sweep" not in text and "Self-Sweep" not in text:
        r.failures.append("Missing self-sweep section")
    decay_signals = ["same pattern", "as above", "similar to", "etc"]
    missing_signals = [s for s in decay_signals if s not in text]
    if missing_signals:
        r.failures.append(f"Self-sweep missing decay-signal examples: {missing_signals}")

    r.passed = not r.failures
    return r


def check_document_frontmatter_contract() -> CheckResult:
    r = CheckResult(name="Document frontmatter contract — instruction + doc generators")

    if not DOC_FRONTMATTER_INSTRUCTION.exists():
        r.passed = False
        r.failures.append(
            f"Missing: {DOC_FRONTMATTER_INSTRUCTION.relative_to(REPO_ROOT)}"
        )
        return r

    instruction_text = _read_text_safe(DOC_FRONTMATTER_INSTRUCTION)
    if instruction_text is None:
        r.passed = False
        r.failures.append(
            f"Cannot read: {DOC_FRONTMATTER_INSTRUCTION.relative_to(REPO_ROOT)}"
        )
        return r

    parsed = _split_frontmatter(instruction_text)
    if parsed is None:
        r.failures.append(
            f"{DOC_FRONTMATTER_INSTRUCTION.relative_to(REPO_ROOT)}: missing or invalid YAML frontmatter"
        )
    else:
        meta, _ = parsed
        if str(meta.get("applyTo", "")).strip() != "**/*.md":
            r.failures.append(
                f"{DOC_FRONTMATTER_INSTRUCTION.relative_to(REPO_ROOT)}: applyTo must be '**/*.md'"
            )

    for field_name in DOC_FRONTMATTER_REQUIRED_FIELDS:
        if field_name not in instruction_text:
            r.failures.append(
                f"{DOC_FRONTMATTER_INSTRUCTION.relative_to(REPO_ROOT)}: missing required field '{field_name}'"
            )

    for phrase in DOC_FRONTMATTER_REQUIRED_PHRASES:
        if phrase not in instruction_text:
            r.failures.append(
                f"{DOC_FRONTMATTER_INSTRUCTION.relative_to(REPO_ROOT)}: missing required phrase '{phrase}'"
            )

    for path in DOC_FRONTMATTER_REFERENCERS:
        if not path.exists():
            r.failures.append(f"Missing doc-generator template: {path.relative_to(REPO_ROOT)}")
            continue
        text = _read_text_safe(path)
        if text is None:
            r.failures.append(f"Cannot read doc-generator template: {path.relative_to(REPO_ROOT)}")
            continue
        if "document-frontmatter.instructions.md" not in text:
            r.failures.append(
                f"{path.relative_to(REPO_ROOT)}: missing reference to document-frontmatter.instructions.md"
            )

    r.info.append(f"checked {len(DOC_FRONTMATTER_REFERENCERS)} doc-generation template(s)")
    r.passed = not r.failures
    return r


def check_document_frontmatter_contract_in_profile(profile_root: Path, label: str) -> CheckResult:
    r = CheckResult(name=f"Document frontmatter contract — exported profile '{label}'")

    instruction_path = profile_root / "instructions" / "document-frontmatter.instructions.md"
    referenced_by: list[Path] = []

    for folder_name in ("skills", "prompts", "instructions"):
        folder = profile_root / folder_name
        if not folder.exists():
            continue
        for path in folder.rglob("*.md"):
            text = _read_text_safe(path)
            if text is None:
                continue
            if "document-frontmatter.instructions.md" in text:
                referenced_by.append(path)

    if not referenced_by:
        r.info.append("no exported files reference document-frontmatter.instructions.md")
        return r

    if not instruction_path.exists():
        r.failures.append(
            f"{instruction_path.relative_to(profile_root)} missing, but {len(referenced_by)} exported file(s) reference it"
        )
    else:
        text = _read_text_safe(instruction_path)
        if text is None:
            r.failures.append(f"Cannot read: {instruction_path.relative_to(profile_root)}")
        else:
            for field_name in DOC_FRONTMATTER_REQUIRED_FIELDS:
                if field_name not in text:
                    r.failures.append(
                        f"{instruction_path.relative_to(profile_root)}: missing required field '{field_name}'"
                    )
            for phrase in DOC_FRONTMATTER_REQUIRED_PHRASES:
                if phrase not in text:
                    r.failures.append(
                        f"{instruction_path.relative_to(profile_root)}: missing required phrase '{phrase}'"
                    )

    r.info.append(f"exported files referencing contract: {len(referenced_by)}")
    r.passed = not r.failures
    return r


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _resolve_scan_roots(args: argparse.Namespace) -> list[Path]:
    roots = [GITHUB_DIR]
    if args.include_dist:
        dist = REPO_ROOT / "dist" / "runtime-resources"
        if dist.exists():
            roots.append(dist)
    if args.include_external:
        for p in EXTRA_POOL_ROOTS:
            if p == REPO_ROOT / "dist" / "runtime-resources":
                continue
            if p.exists():
                roots.append(p)
    return roots


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="caddis pool validator")
    parser.add_argument(
        "--include-dist",
        action="store_true",
        help="Also scan dist/runtime-resources (post-export check).",
    )
    parser.add_argument(
        "--include-external",
        action="store_true",
        help="Also scan junai-vscode/pool and caddis-plugin/.github mirrors.",
    )
    parser.add_argument(
        "--profile",
        choices=["ptarmigan", "liffey", "claude", "claude-extras"],
        help="Validate a specific exported profile under dist/runtime-resources/<profile>/.",
    )
    args = parser.parse_args(argv)

    claude_profile = args.profile in ("claude", "claude-extras")

    roots = _resolve_scan_roots(args)
    profile_root: Path | None = None
    if args.profile and not claude_profile:
        profile_root = DIST_RUNTIME_ROOT / args.profile / ".github"
        profile_root_path: Path = cast(Path, profile_root)
        roots = [profile_root_path]
    elif claude_profile:
        profile_root = _claude_plugin_root(args.profile)
        roots = [cast(Path, profile_root)]

    print("=" * 70)
    print("  validate_pool.py — caddis pool validator")
    print("=" * 70)
    print(f"  scope: {[str(p) for p in roots]}")
    print("-" * 70)

    if claude_profile:
        if profile_root is None or not profile_root.exists():
            print(f"[FAIL] Plugin bundle not found: {profile_root}")
            print("       Run export_runtime_resources.py first.")
            return 1
        results = run_claude_profile_checks(args.profile, cast(Path, profile_root), roots)
    elif args.profile:
        if profile_root is None or not profile_root.exists():
            print(f"[FAIL] Profile export not found: {profile_root}")
            print("       Run export_runtime_resources.py for this profile first.")
            return 1

        results = [
            check_profile_manifest_alignment(args.profile, profile_root),
            check_privacy_scan(roots),
            check_generated_artifacts([profile_root.parent]),
            check_prompts_in_dir(profile_root / "prompts", args.profile),
            check_skill_registry_in_dir(profile_root / "skills", args.profile),
            check_document_frontmatter_contract_in_profile(profile_root, args.profile),
        ]
        if args.profile == "ptarmigan":
            results.append(check_ptarmigan_content_restrictions(profile_root))
        elif args.profile == "liffey":
            results.append(check_liffey_content_restrictions(profile_root))
    else:
        results = [
            check_manifest_contract(),
            check_agy_plugin_target(),
            check_privacy_scan(roots),
            check_privacy_scan_tracked(),
            check_enforcement_ratio(),
            check_generated_artifacts(roots),
            check_prompts(),
            check_skill_frontmatter(),
            check_skill_registry(),
            check_document_frontmatter_contract(),
            check_golden_plan(),
        ]

    for result in results:
        _print_check(result)

    failed = sum(1 for r in results if not r.passed)

    print("-" * 70)
    if failed:
        print(f"[FAIL] {failed} check(s) failed.")
        return 1
    print("[OK] All pool checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
