from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from manifest import load_manifest


MODULE_DIR = Path(__file__).resolve().parent
POOL_ROOT = MODULE_DIR.parents[2]
SKILLS_DIR = POOL_ROOT / ".github" / "skills"
REGISTRY_PATH = SKILLS_DIR / "_registry.md"

CATEGORY_TITLES = {
    "cloud": "Cloud",
    "coding": "Coding",
    "data": "Data",
    "devops": "DevOps",
    "docs": "Docs",
    "frontend": "Frontend",
    "testing": "Testing",
    "workflow": "Workflow",
    "media": "Media",
    "productivity": "Productivity",
}

UPPER_TOKENS = {
    "ai": "AI",
    "api": "API",
    "aws": "AWS",
    "cdk": "CDK",
    "ci": "CI",
    "cli": "CLI",
    "css": "CSS",
    "db": "DB",
    "docx": "DOCX",
    "eda": "EDA",
    "fastapi": "FastAPI",
    "github": "GitHub",
    "hld": "HLD",
    "html": "HTML",
    "json": "JSON",
    "lld": "LLD",
    "llm": "LLM",
    "mcp": "MCP",
    "nextjs": "Next.js",
    "oauth": "OAuth",
    "pdf": "PDF",
    "prd": "PRD",
    "pptx": "PPTX",
    "pwa": "PWA",
    "qa": "QA",
    "rag": "RAG",
    "readme": "README",
    "sql": "SQL",
    "svg": "SVG",
    "ts": "TS",
    "ui": "UI",
    "ux": "UX",
    "vitest": "Vitest",
    "wcag": "WCAG",
    "xlsx": "XLSX",
    "xml": "XML",
}


@dataclass(frozen=True)
class SkillMetadata:
    category: str
    display_name: str
    skill_name: str
    description: str
    path: str


def _split_frontmatter(text: str) -> tuple[dict, str] | None:
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


def collect_public_skills(
    pool_root: Path | None = None,
    *,
    profile: str | None = None,
) -> list[SkillMetadata]:
    root = (pool_root or POOL_ROOT).resolve()
    manifest = load_manifest(root)
    skills_dir = root / ".github" / "skills"
    skills: list[SkillMetadata] = []

    if profile is not None and profile not in manifest.profiles:
        raise ValueError(f"Unknown profile {profile!r}")

    for skill_md in sorted(skills_dir.rglob("SKILL.md")):
        classification = manifest_mod_classify(skill_md, manifest)
        # A project install (profile set) skips every private file, including the privacy-scan
        # allow list. The published registry (no profile) leaves out only what is never
        # published: `private.paths` and the local-private tier. The plugin bundles and the
        # mirror ship allow-listed skills, so that registry must list them.
        if classification.is_private if profile is not None else _is_unpublished(classification, manifest):
            continue

        rel = skill_md.relative_to(skills_dir)
        if len(rel.parts) < 2:
            continue

        parsed = _split_frontmatter(skill_md.read_text(encoding="utf-8"))
        if parsed is None:
            raise ValueError(f"Missing or invalid frontmatter in {skill_md}")
        meta, _ = parsed

        skill_name = str(meta.get("name", "")).strip()
        description = " ".join(str(meta.get("description", "")).split())
        if not skill_name or not description:
            raise ValueError(f"Missing name/description in {skill_md}")

        category = rel.parts[0]
        skill_path = "/".join(rel.parts[:-1]) + "/"
        if profile is not None and not _profile_includes_skill_path(skill_path, manifest, profile):
            continue
        skills.append(
            SkillMetadata(
                category=category,
                display_name=_titleize_skill_name(skill_name),
                skill_name=skill_name,
                description=description,
                path=skill_path,
            )
        )

    return skills


def _is_unpublished(classification, manifest) -> bool:
    from manifest import TIER_LOCAL_PRIVATE, _matches_private_path_pattern  # type: ignore[attr-defined]

    return classification.tier == TIER_LOCAL_PRIVATE or _matches_private_path_pattern(
        classification.path, manifest.private_paths
    )


def manifest_mod_classify(path: Path, manifest):
    from manifest import _classify_with_manifest  # type: ignore[attr-defined]

    return _classify_with_manifest(path, manifest)


def _titleize_skill_name(name: str) -> str:
    tokens = name.replace("/", " / ").replace("-", " ").split()
    words: list[str] = []
    for token in tokens:
        lowered = token.lower()
        words.append(UPPER_TOKENS.get(lowered, token.capitalize()))
    return " ".join(words)


def _profile_includes_skill_path(skill_path: str, manifest, profile: str) -> bool:
    if profile == "full":
        return True
    candidate = skill_path.replace("\\", "/").strip("/")
    for pattern in manifest.profiles[profile]:
        normalized = pattern.replace("\\", "/").strip("/")
        if normalized == "**":
            return True
        if normalized.endswith("/**"):
            prefix = normalized[:-3].rstrip("/")
            if candidate == prefix or candidate.startswith(prefix + "/"):
                return True
        elif candidate == normalized:
            return True
    return False


def render_registry(skills: list[SkillMetadata]) -> str:
    grouped: dict[str, list[SkillMetadata]] = {}
    for skill in skills:
        grouped.setdefault(skill.category, []).append(skill)

    lines = [
        "# Skills Registry",
        "",
        "> Public skill inventory generated from `SKILL.md` frontmatter. Private material and denylist-exception paths are excluded from this registry.",
        "> Load a skill by reading its `SKILL.md`. See `project-config.md` for project-specific placeholder values.",
        "",
        "---",
        "",
        "## Skills by Category",
        "",
    ]

    for category in CATEGORY_TITLES:
        entries = sorted(grouped.get(category, []), key=lambda item: item.path)
        if not entries:
            continue
        lines.extend(
            [
                f"### {CATEGORY_TITLES[category]}",
                "",
                "| Skill | Path | When to Use |",
                "|-------|------|-------------|",
            ]
        )
        for entry in entries:
            lines.append(
                f"| {entry.display_name} | `{entry.path}` | {entry.description} |"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_registry(pool_root: Path | None = None) -> str:
    root = (pool_root or POOL_ROOT).resolve()
    output = render_registry(collect_public_skills(root))
    (root / ".github" / "skills" / "_registry.md").write_text(
        output,
        encoding="utf-8",
    )
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate .github/skills/_registry.md")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the checked-in registry does not match generated output.",
    )
    args = parser.parse_args(argv)

    rendered = render_registry(collect_public_skills())
    if args.check:
        current = REGISTRY_PATH.read_text(encoding="utf-8") if REGISTRY_PATH.exists() else ""
        if current != rendered:
            sys.stdout.write(rendered)
            return 1
        return 0

    REGISTRY_PATH.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
