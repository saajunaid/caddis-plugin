from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / ".github" / "runtime-targets.json"

TOOL_MAP: dict[str, list[str]] = {
    "read": ["Read", "Glob"],
    "search": ["Grep"],
    "edit": ["Edit", "Write", "MultiEdit"],
    "execute": ["Bash"],
    "web": ["WebSearch", "WebFetch"],
    "problems": [],
    "testFailure": [],
    "changes": [],
}


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    """Load the runtime export manifest."""
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def ensure_clean_dir(path: Path) -> None:
    """Recreate a directory from scratch."""
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


CACHE_DIR_NAMES = {"__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".coverage", "htmlcov"}


@dataclass
class ExportStats:
    profile: str
    files_copied: int = 0
    skipped_by_reason: dict[str, int] = field(default_factory=dict)
    # Hard errors that make the export fail-closed (missing declared sources,
    # phantom skills in a roster). Distinct from skips, which are expected.
    errors: list[str] = field(default_factory=list)

    def bump_skip(self, reason: str, count: int = 1) -> None:
        self.skipped_by_reason[reason] = self.skipped_by_reason.get(reason, 0) + count

    def add_error(self, message: str) -> None:
        self.errors.append(message)


def _ignore_caches(_dir: str, names: list[str]) -> list[str]:
    """shutil.copytree ignore callable that drops Python cache dirs at every depth."""
    return [n for n in names if n in CACHE_DIR_NAMES]


def copy_tree(
    source: Path,
    destination: Path,
    excluded_names: set[str] | None = None,
    included_names: set[str] | None = None,
    depth2_included: dict[str, set[str]] | None = None,
    depth2_excluded: set[str] | None = None,
    stats: ExportStats | None = None,
) -> int:
    """Copy a directory tree with optional top-level and depth-2 allow/deny lists.

    included_names:   allowlist at depth 0 (direct children of source).
    depth2_included:  per-category allowlist at depth 1.  A dict mapping
                      category-name → set of allowed item names.  Categories
                      absent from the dict are excluded entirely when the dict
                      is provided (i.e. it is a full allowlist across categories).
    depth2_excluded:  category-agnostic denylist at depth 1 — skill names to skip
                      regardless of category.  Used by the extras bundle, which copies
                      everything-minus-core (no allowlist, just a denylist of the core).
    """
    excluded_names = excluded_names or set()
    included_names = included_names or set()
    destination.mkdir(parents=True, exist_ok=True)
    copied_files = 0

    for root_str, dirs, files in os.walk(source):
        root = Path(root_str)
        rel_root = root.relative_to(source)
        depth = 0 if rel_root == Path(".") else len(rel_root.parts)
        is_depth0 = depth == 0
        is_depth1 = depth == 1
        depth1_category = rel_root.parts[0] if is_depth1 else None

        kept_dirs: list[str] = []
        for d in dirs:
            if d in CACHE_DIR_NAMES:
                if stats is not None:
                    stats.bump_skip("cache_dir")
                continue
            # depth-0: top-level included_names allowlist
            if is_depth0 and included_names and d not in included_names:
                if stats is not None:
                    stats.bump_skip("not_included")
                continue
            # depth-0: top-level excluded_names
            if is_depth0 and d in excluded_names:
                if stats is not None:
                    stats.bump_skip("excluded_name")
                continue
            # depth-0: depth2_included acts as category allowlist
            if is_depth0 and depth2_included is not None and d not in depth2_included:
                if stats is not None:
                    stats.bump_skip("not_included")
                continue
            # depth-1: per-category skill allowlist
            if is_depth1 and depth2_included is not None and depth1_category is not None:
                category_filter = depth2_included.get(depth1_category)
                if category_filter is not None and d not in category_filter:
                    if stats is not None:
                        stats.bump_skip("not_included")
                    continue
            # depth-1: category-agnostic skill denylist (extras = everything minus core)
            if is_depth1 and depth2_excluded and d in depth2_excluded:
                if stats is not None:
                    stats.bump_skip("excluded_skill")
                continue
            kept_dirs.append(d)
        dirs[:] = kept_dirs

        for filename in files:
            if filename in CACHE_DIR_NAMES:
                if stats is not None:
                    stats.bump_skip("cache_file")
                continue
            if is_depth0 and included_names and filename not in included_names:
                if stats is not None:
                    stats.bump_skip("not_included")
                continue
            if is_depth0 and filename in excluded_names:
                if stats is not None:
                    stats.bump_skip("excluded_name")
                continue
            if is_depth0 and depth2_included is not None and filename not in depth2_included:
                # depth2_included is a directory-level allowlist — never filter root files
                pass
            if is_depth1 and depth2_included is not None and depth1_category is not None:
                category_filter = depth2_included.get(depth1_category)
                if category_filter is not None and filename not in category_filter:
                    if stats is not None:
                        stats.bump_skip("not_included")
                    continue

            src_file = root / filename
            dest_dir = destination / rel_root
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dest_dir / filename)
            copied_files += 1

    return copied_files


def copy_file(source: Path, destination: Path) -> int:
    """Copy a single file, creating parent directories when necessary."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return 1


def flatten_skill_tree(skills_dir: Path, stats: ExportStats | None = None) -> int:
    """Collapse skills/<category>/<skill>/ → skills/<skill>/ for plugin discovery.

    Claude Code discovers plugin skills at skills/<name>/SKILL.md (flat, one level deep).
    The pool is organized by category, so each skill dir is lifted up one level and the
    now-empty category dir is dropped. Top-level files (e.g. _registry.md) are left in
    place. A category child that is NOT a leaf skill (no SKILL.md of its own — e.g. a
    nested skill *bundle*) is left where it is; such bundles must be kept out of the
    roster since they don't fit the flat model. Returns the number of skills moved.
    """
    if not skills_dir.exists():
        return 0
    moved = 0
    for category in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        for skill in sorted(p for p in category.iterdir() if p.is_dir()):
            if not (skill / "SKILL.md").is_file():
                continue  # not a leaf skill (bundle) — leave for roster exclusion
            target = skills_dir / skill.name
            if target.exists():
                raise ValueError(
                    f"flatten_skills: name collision '{skill.name}' in {skills_dir}"
                )
            shutil.move(str(skill), str(target))
            moved += 1
        leftover = list(category.iterdir())
        if not leftover:
            category.rmdir()
        elif stats is not None:
            stats.bump_skip("flatten_left_nonempty")
    return moved


def convert_tools_to_claude_format(copilot_tools: list[str]) -> str:
    """Map Copilot tool names to Claude agent tool names."""
    claude_tools: list[str] = []

    for tool in copilot_tools:
        normalized = tool.strip()
        if "/" in normalized:
            continue
        for mapped in TOOL_MAP.get(normalized, []):
            if mapped and mapped not in claude_tools:
                claude_tools.append(mapped)

    if not claude_tools:
        # No mapped tools → default read-only. NEVER implicitly grant Bash (shell):
        # a Copilot agent that never declared 'execute' must not silently gain
        # arbitrary command execution on conversion. Explicit 'execute' still maps
        # to Bash above.
        claude_tools = ["Read", "Grep", "Glob"]

    return ", ".join(claude_tools)


def split_frontmatter(text: str) -> tuple[str, str]:
    """Split a markdown file into frontmatter and body."""
    if not text.startswith("---"):
        return "", text

    closing_index = text.find("\n---", 3)
    if closing_index == -1:
        return "", text

    frontmatter = text[4:closing_index]
    body = text[closing_index + 4 :].lstrip("\n")
    return frontmatter, body


def extract_simple_frontmatter(frontmatter: str) -> dict[str, str]:
    """Extract simple frontmatter key/value pairs without a YAML dependency."""
    data: dict[str, str] = {}
    for line in frontmatter.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"')
    return data


def extract_tools(frontmatter: str) -> list[str]:
    """Extract tools from a one-line list in frontmatter."""
    for line in frontmatter.splitlines():
        if not line.startswith("tools:"):
            continue
        raw = line.split("[", 1)[-1].rsplit("]", 1)[0]
        return [item.strip().strip('"').strip("'") for item in raw.split(",") if item.strip()]
    return []


def convert_agent_to_claude(source_file: Path, destination_file: Path) -> None:
    """Convert a Copilot .agent.md file into Claude-compatible agent markdown."""
    content = source_file.read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(content)
    data = extract_simple_frontmatter(frontmatter)
    claude_tools = convert_tools_to_claude_format(extract_tools(frontmatter))

    lines = [
        "---",
        f"name: {data.get('name', source_file.stem)}",
        f'description: {json.dumps(data.get("description", ""))}',
        f'tools: {json.dumps(claude_tools)}',
        "---",
        "",
        body,
    ]
    destination_file.parent.mkdir(parents=True, exist_ok=True)
    destination_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def convert_instruction_to_rule(source_file: Path, destination_file: Path) -> None:
    """Convert a Copilot instruction file into a Claude rules file."""
    content = source_file.read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(content)
    data = extract_simple_frontmatter(frontmatter)
    description = data.get("description", "")
    globs = data.get("applyTo", "**")

    lines = [
        "---",
        f'description: {json.dumps(description)}',
        f'globs: [{json.dumps(globs)}]',
        "---",
        "",
        body,
    ]
    destination_file.parent.mkdir(parents=True, exist_ok=True)
    destination_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _normalize_paths(paths: list[str]) -> set[str]:
    """Normalize manifest path entries to forward-slash relative form."""
    return {p.replace("\\", "/").strip("/") for p in paths if p}


def write_plugin_manifests(bundle_root: Path, plugin_dir: Path, target: dict[str, Any]) -> None:
    """Emit the plugin + marketplace manifests for a plugin-shaped target.

    Two-level layout: `marketplace.json` lives at the bundle root (which becomes the host
    repo root after publish), and the plugin itself — including `plugin.json` — lives in a
    subdirectory (`plugin/`). The marketplace's `plugin_source` points at that subdir. This
    is required because the host repo (caddis-plugin) carries other content, so the plugin cannot
    occupy the repo root with `source: "."`.
    """
    plugin = target.get("plugin")
    if not plugin:
        return
    plugin_meta = plugin_dir / ".claude-plugin"
    plugin_meta.mkdir(parents=True, exist_ok=True)
    plugin_manifest = {k: v for k, v in plugin.items() if v not in (None, "", [], {})}
    (plugin_meta / "plugin.json").write_text(
        json.dumps(plugin_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    mkt = target.get("marketplace")
    if mkt:
        mkt_meta = bundle_root / ".claude-plugin"
        mkt_meta.mkdir(parents=True, exist_ok=True)
        marketplace_manifest: dict[str, Any] = {"name": mkt["name"], "owner": mkt["owner"]}
        if mkt.get("description"):
            marketplace_manifest["description"] = mkt["description"]
        # A marketplace may list multiple plugins explicitly (core + extras). When the
        # manifest provides a `plugins` array, ship it verbatim; otherwise fall back to a
        # single entry built from this target's plugin block.
        if mkt.get("plugins"):
            marketplace_manifest["plugins"] = mkt["plugins"]
        else:
            marketplace_manifest["plugins"] = [
                {
                    "name": plugin["name"],
                    "source": mkt.get("plugin_source", "./plugin"),
                    "description": plugin.get("description", ""),
                }
            ]
        (mkt_meta / "marketplace.json").write_text(
            json.dumps(marketplace_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )


def _canonical_plugin_version(manifest: dict[str, Any], plugin_name: str | None = None) -> str:
    """The single-source plugin version — the SAME-NAMED Claude plugin's version (bumped by
    sync.ps1), so one manifest bump propagates to every plugin-shaped target: `caddis` follows
    the `claude` target, `caddis-extras` follows `claude-extras`. Without the name match the
    extras agy plugin would wrongly inherit the core version (the first versioned target).
    Falls back to the first versioned target when no name matches."""
    fallback = ""
    for t in manifest.get("targets", []):
        plugin = t.get("plugin") or {}
        ver = plugin.get("version")
        if not ver:
            continue
        if plugin_name and plugin.get("name") == plugin_name:
            return ver
        if not fallback:
            fallback = ver
    return fallback or "0.0.0"


_AGY_DROP_AGENT_KEYS = re.compile(r"^\s*(tools|model|color)\s*:", re.IGNORECASE)


def strip_agent_frontmatter_for_agy(agents_dir: Path) -> int:
    """agy lists a custom agent by name+description; Claude-only frontmatter keys (`tools`, `model`,
    `color`) make `agy agents` silently skip it. Strip those keys from the plugin's agent files so the
    agents register (keep name/description + the body). Returns the count adjusted. Verified: an agent
    with only name+description lists; one with `tools:`/`model:` does not."""
    if not agents_dir.is_dir():
        return 0
    n = 0
    for md in sorted(agents_dir.glob("*.md")):
        lines = md.read_text(encoding="utf-8").splitlines(keepends=True)
        if not lines or lines[0].strip() != "---":
            continue
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if end is None:
            continue
        kept = [lines[0]] + [ln for ln in lines[1:end] if not _AGY_DROP_AGENT_KEYS.match(ln)] + lines[end:]
        if len(kept) != len(lines):
            md.write_text("".join(kept), encoding="utf-8")
            n += 1
    return n


def write_agy_plugin_manifest(
    workspace_root: Path, target: dict[str, Any], manifest: dict[str, Any]
) -> None:
    """Emit an Antigravity (`agy`) plugin.json at the plugin ROOT (agy 1.1.5 contract — NOT the
    Claude `.claude-plugin/` layout). Required keys: name, version. See
    docs/analysis/antigravity-plugin-contract.md. Version single-sourced from the claude plugin."""
    spec = target.get("agy_plugin")
    if not spec:
        return
    plugin = {
        "name": spec["name"],
        "version": spec.get("version") or _canonical_plugin_version(manifest, spec["name"]),
    }
    if spec.get("description"):
        plugin["description"] = spec["description"]
    workspace_root.mkdir(parents=True, exist_ok=True)
    (workspace_root / "plugin.json").write_text(
        json.dumps(plugin, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def write_bundle_registry(skills_dir: Path, category_map: dict[str, str] | None = None) -> int:
    """Regenerate _registry.md from the skills actually present in the bundle.

    Self-contained (no pool manifest dependency) so the shipped subset's registry matches
    what was exported, not the full 133-skill pool. Handles both the categorized layout
    (skills/<category>/<skill>/SKILL.md) and the flattened plugin layout
    (skills/<skill>/SKILL.md) — for the latter the category comes from `category_map`
    (skill-name → category), defaulting to "general". Returns the number of rows written.
    """
    if not skills_dir.exists():
        return 0
    category_map = category_map or {}
    by_category: dict[str, list[tuple[str, str, str]]] = {}
    for skill_md in sorted(skills_dir.rglob("SKILL.md")):
        rel = skill_md.relative_to(skills_dir)
        if len(rel.parts) < 2:
            continue
        name_dir = rel.parts[-2]
        if len(rel.parts) >= 3:
            category = rel.parts[0]            # categorized layout
        else:
            category = category_map.get(name_dir, "general")  # flattened layout
        frontmatter, _ = split_frontmatter(skill_md.read_text(encoding="utf-8"))
        data = extract_simple_frontmatter(frontmatter)
        name = data.get("name", name_dir)
        description = " ".join(data.get("description", "").split())
        display = " ".join(w.capitalize() for w in name.replace("-", " ").split())
        path = "/".join(rel.parts[:-1]) + "/"
        by_category.setdefault(category, []).append((display, path, description))

    lines = [
        "# Skills Registry",
        "",
        "> Bundle skill inventory generated from `SKILL.md` frontmatter for the shipped subset.",
        "> Load a skill by reading its `SKILL.md`.",
        "",
        "---",
        "",
        "## Skills by Category",
        "",
    ]
    count = 0
    for category in sorted(by_category):
        lines.append(f"### {category.capitalize()}")
        lines.append("")
        lines.append("| Skill | Path | When to Use |")
        lines.append("|-------|------|-------------|")
        for display, path, description in sorted(by_category[category]):
            lines.append(f"| {display} | `{path}` | {description} |")
            count += 1
        lines.append("")
    (skills_dir / "_registry.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return count


def _validate_skill_roster(
    source_skills: Path, roster: dict[str, set[str]]
) -> list[str]:
    """Return roster entries (category or skill) absent from ``source_skills``.

    A target's ``included_skills`` maps category → skill names. If a named category
    isn't a real directory, or a named skill isn't present under it, the roster is
    stale: the export would silently ship fewer skills than declared (as the `codex`
    target did with 5 renamed frontend skills). Callers treat any result as fatal.
    """
    problems: list[str] = []
    for category in sorted(roster):
        category_dir = source_skills / category
        if not category_dir.is_dir():
            problems.append(
                f"included_skills category '{category}' does not exist under "
                f"{source_skills.name}/"
            )
            continue
        present = {p.name for p in category_dir.iterdir() if p.is_dir()}
        for skill in sorted(roster[category]):
            if skill not in present:
                problems.append(f"included_skills skill '{category}/{skill}' does not exist")
    return problems


def export_target(manifest: dict[str, Any], target: dict[str, Any]) -> ExportStats:
    """Export one runtime target from the canonical .github source."""
    canonical_root = PROJECT_ROOT / manifest["canonical_root"]
    output_root = PROJECT_ROOT / manifest["output_root"] / target["name"]
    workspace_root = output_root / target["workspace_root"]
    stats = ExportStats(profile=target["name"])
    # extra_roots: a target may pull some copies/files from a second source root
    # (e.g. the claude target sources agents/commands from `claude-harness/`, not `.github`).
    extra_roots: dict[str, Path] = {
        key: PROJECT_ROOT / rel for key, rel in target.get("extra_roots", {}).items()
    }

    def _base_root(spec: dict[str, Any]) -> Path:
        root_key = spec.get("root")
        if root_key:
            if root_key not in extra_roots:
                raise ValueError(
                    f"{target['name']}: copy/file references unknown root '{root_key}'"
                )
            return extra_roots[root_key]
        return canonical_root
    exclusion_cfg = manifest.get("exclusions", {})
    # A target may opt back into otherwise-private content (e.g. the personal `claude`
    # bundle includes vmie; a future public plugin target omits it). include_private
    # lifts the named items out of the global exclusions for THIS target only.
    include_private = set(target.get("include_private", []))
    skill_exclusions = set(exclusion_cfg.get("skills", [])) - include_private
    private_roots = set(exclusion_cfg.get("private_roots", [])) - include_private
    private_paths = _normalize_paths(exclusion_cfg.get("private_paths", []))

    ensure_clean_dir(output_root)

    for copy_spec in target.get("copies", []):
        source_rel = copy_spec["source"].replace("\\", "/").strip("/")
        if source_rel in private_paths or source_rel in private_roots:
            print(f"[SKIP] {target['name']}: copy '{source_rel}' is in exclusions")
            stats.bump_skip("private_path")
            continue
        source = _base_root(copy_spec) / copy_spec["source"]
        destination = workspace_root / copy_spec["destination"]
        excluded_names: set[str] = set(private_roots)
        included_names: set[str] = set(copy_spec.get("included_names", []))
        depth2_included: dict[str, set[str]] | None = None
        depth2_excluded: set[str] | None = None
        if source_rel == "skills":
            excluded_names |= skill_exclusions
            raw_skill_roster = copy_spec.get("included_skills")
            # A plugin target may reuse another target's roster (single source, no duplication):
            # `included_skills_from: <target-name>` pulls that target's skills-copy included_skills.
            if not raw_skill_roster and copy_spec.get("included_skills_from"):
                ref = copy_spec["included_skills_from"]
                ref_target = next((t for t in manifest.get("targets", []) if t["name"] == ref), None)
                if ref_target:
                    for cs in ref_target.get("copies", []):
                        if cs.get("source", "").replace("\\", "/").strip("/") == "skills" and cs.get("included_skills"):
                            raw_skill_roster = cs["included_skills"]
                            break
                if not raw_skill_roster:
                    stats.add_error(f"included_skills_from '{ref}' resolved no roster")
                    print(f"[FAIL] {target['name']}: included_skills_from '{ref}' resolved no roster")
            if raw_skill_roster:
                depth2_included = {cat: set(skills) for cat, skills in raw_skill_roster.items()}
            excluded_skills = set(copy_spec.get("excluded_skills", []))
            # An extras bundle may reuse another target's denylist (single source): the tail =
            # every pool skill EXCEPT the core. `excluded_skills_from: <target>` pulls that target's
            # excluded_skills (e.g. claude-extras' denylist) so core/extras stays one split.
            if not excluded_skills and copy_spec.get("excluded_skills_from"):
                ref = copy_spec["excluded_skills_from"]
                ref_target = next((t for t in manifest.get("targets", []) if t["name"] == ref), None)
                if ref_target:
                    for cs in ref_target.get("copies", []):
                        if cs.get("source", "").replace("\\", "/").strip("/") == "skills" and cs.get("excluded_skills"):
                            excluded_skills = set(cs["excluded_skills"])
                            break
                if not excluded_skills:
                    stats.add_error(f"excluded_skills_from '{ref}' resolved no denylist")
                    print(f"[FAIL] {target['name']}: excluded_skills_from '{ref}' resolved no denylist")
            if excluded_skills:
                depth2_excluded = excluded_skills
        excluded_names |= set(copy_spec.get("excluded_names", []))
        if not source.exists():
            stats.bump_skip("missing_source")
            stats.add_error(f"copy source '{source_rel}' does not exist")
            print(f"[FAIL] {target['name']}: copy source '{source_rel}' does not exist")
            continue
        # Fail-closed: a stale skill roster (names a skill/category not on disk)
        # would otherwise silently ship fewer skills than declared.
        if depth2_included is not None:
            for problem in _validate_skill_roster(source, depth2_included):
                stats.add_error(problem)
                print(f"[FAIL] {target['name']}: {problem}")
        stats.files_copied += copy_tree(
            source,
            destination,
            excluded_names=excluded_names,
            included_names=included_names,
            depth2_included=depth2_included,
            depth2_excluded=depth2_excluded,
            stats=stats,
        )
        if copy_spec.get("flatten_skills"):
            flatten_skill_tree(destination, stats)

    for file_spec in target.get("files", []):
        source_rel = file_spec["source"].replace("\\", "/").strip("/")
        top = source_rel.split("/", 1)[0]
        if source_rel in private_paths or top in private_paths or top in private_roots:
            print(f"[SKIP] {target['name']}: file '{source_rel}' is in exclusions")
            stats.bump_skip("private_path")
            continue
        source = _base_root(file_spec) / file_spec["source"]
        destination = workspace_root / file_spec["destination"]
        if not source.exists():
            stats.bump_skip("missing_source")
            stats.add_error(f"file source '{source_rel}' does not exist")
            print(f"[FAIL] {target['name']}: file source '{source_rel}' does not exist")
            continue
        stats.files_copied += copy_file(source, destination)

    for transform_spec in target.get("transforms", []):
        source_dir = canonical_root / transform_spec["source"]
        destination_dir = workspace_root / transform_spec["destination"]
        destination_dir.mkdir(parents=True, exist_ok=True)

        if transform_spec["type"] == "agents_to_claude":
            for source_file in source_dir.glob("*.agent.md"):
                destination_file = destination_dir / f"{source_file.stem.replace('.agent', '')}.md"
                convert_agent_to_claude(source_file, destination_file)
        elif transform_spec["type"] == "instructions_to_rules":
            for source_file in source_dir.glob("*.instructions.md"):
                destination_file = destination_dir / f"{source_file.stem.replace('.instructions', '')}.md"
                convert_instruction_to_rule(source_file, destination_file)
        else:
            raise ValueError(f"Unsupported transform type: {transform_spec['type']}")

    # Plugin packaging (Phase 4): emit .claude-plugin manifests + a bundle-scoped skill registry.
    # marketplace.json at the bundle root (output_root); plugin.json + content under workspace_root.
    if target.get("plugin"):
        write_plugin_manifests(output_root, workspace_root, target)
        # Build a full skill→category map from the source pool so the flattened registry
        # keeps real categories (works for both allowlist and denylist rosters).
        cat_map: dict[str, str] = {}
        canonical_skills = canonical_root / "skills"
        if canonical_skills.exists():
            for cat_dir in canonical_skills.iterdir():
                if cat_dir.is_dir():
                    for sk in cat_dir.iterdir():
                        if sk.is_dir():
                            cat_map[sk.name] = cat_dir.name
        rows = write_bundle_registry(workspace_root / "skills", cat_map or None)
        if rows:
            stats.bump_skip("registry_rows_written", rows)

    # Antigravity (agy) plugin packaging: plugin.json at the plugin ROOT + a bundle-scoped registry.
    if target.get("agy_plugin"):
        write_agy_plugin_manifest(workspace_root, target, manifest)
        strip_agent_frontmatter_for_agy(workspace_root / "agents")  # drop Claude-only tools/model keys
        cat_map = {}
        canonical_skills = canonical_root / "skills"
        if canonical_skills.exists():
            for cat_dir in canonical_skills.iterdir():
                if cat_dir.is_dir():
                    for sk in cat_dir.iterdir():
                        if sk.is_dir():
                            cat_map[sk.name] = cat_dir.name
        rows = write_bundle_registry(workspace_root / "skills", cat_map or None)
        if rows:
            stats.bump_skip("registry_rows_written", rows)

    return stats


def _select_targets(manifest: dict[str, Any], profiles: list[str] | None) -> list[dict[str, Any]]:
    targets = manifest["targets"]
    if not profiles:
        return targets
    requested = {p.strip() for p in profiles if p and p.strip()}
    selected = [t for t in targets if t.get("name") in requested]
    if len(selected) != len(requested):
        known = {t.get("name") for t in targets}
        missing = sorted(requested - known)
        raise ValueError(f"Unknown profile(s): {', '.join(missing)}; known: {', '.join(sorted(known))}")
    return selected


def _print_report(all_stats: list[ExportStats]) -> None:
    print("\n=== Export report ===")
    for stats in all_stats:
        print(f"profile={stats.profile}")
        print(f"  files_copied: {stats.files_copied}")
        if stats.skipped_by_reason:
            print("  skipped:")
            for reason, count in sorted(stats.skipped_by_reason.items()):
                print(f"    - {reason}: {count}")
        else:
            print("  skipped: none")
        if stats.errors:
            print("  errors:")
            for err in stats.errors:
                print(f"    - {err}")
        else:
            print("  errors: none")


def main() -> int:
    """Build runtime-specific resource exports from the canonical .github source."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help="Path to the runtime export manifest.",
    )
    parser.add_argument(
        "--profile",
        action="append",
        help="Export only the named profile(s). Repeat the flag to select multiple.",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print per-profile export counts, skip counts, and dependency errors.",
    )
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    exclusion_cfg = manifest.get("exclusions", {})
    forbidden_names = set(exclusion_cfg.get("private_roots", [])) | set(
        exclusion_cfg.get("skills", [])
    ) | _normalize_paths(exclusion_cfg.get("private_paths", []))

    all_stats: list[ExportStats] = []
    try:
        selected_targets = _select_targets(manifest, args.profile)
    except ValueError as exc:
        print(f"[FAIL] {exc}")
        return 1

    for target in selected_targets:
        stats = export_target(manifest, target)
        all_stats.append(stats)
        print(f"[OK] Exported {target['name']} resources")

    if args.report:
        _print_report(all_stats)

    # Fail-closed: missing declared sources and phantom skills are defects, not skips.
    export_errors = [
        f"{stats.profile}: {err}" for stats in all_stats for err in stats.errors
    ]
    if export_errors:
        print(f"[FAIL] Export errors detected ({len(export_errors)}):")
        for err in export_errors:
            print(f"   - {err}")
        return 1

    # Post-export verification: no private content in any output tree
    output_root = PROJECT_ROOT / manifest["output_root"]
    leaks: list[str] = []
    target_names = {t["name"] for t in selected_targets}
    include_private_by_target = {
        t["name"]: set(t.get("include_private", [])) for t in selected_targets
    }
    for path in output_root.rglob("*"):
        rel_parts = path.relative_to(output_root).parts
        if not rel_parts or rel_parts[0] not in target_names:
            continue
        # a target that opted into private content is not "leaking" it
        tgt_forbidden = forbidden_names - include_private_by_target.get(rel_parts[0], set())
        if any(part in tgt_forbidden for part in rel_parts):
            leaks.append(str(path.relative_to(output_root)))
    if leaks:
        print(f"[FAIL] Private content leaked into export ({len(leaks)} paths):")
        for leak in leaks[:20]:
            print(f"   - {leak}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
