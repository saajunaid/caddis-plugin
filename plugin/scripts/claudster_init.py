"""caddis-init — install a caddis toolbox bundle into a project, for any harness.

One canonical toolbox, many harnesses: Claude Code gets the plugin/marketplace; every other
harness (codex, antigravity, copilot, …) gets a per-harness bundle laid into the project by
this script. See docs/guide/porting-to-a-harness.md for how bundles are produced.

Guidance — **repo = rules, user = skills**: install SKILLS once at the user level (`--user`, into
~/.codex/skills / ~/.agents/skills) so every project sees them; keep RULES (AGENTS.md) per-repo (the
default `--dest` mode), since rules are project-specific. Teams that want vendored/pinned skills can
still install per-repo. Every apply is recorded in ~/.caddis/installs.json; `--update-all` refreshes
them all, `--uninstall` removes only the unmodified files it wrote, and `claudster_doctor.py` reports health.

Usage:
    python claudster_init.py --target codex                 # fetch from GitHub (published bundles)
    python claudster_init.py --target antigravity --from E:\\path\\to\\caddis
    python claudster_init.py --target codex --from repo.tar.gz --dest C:\\proj

Source resolution (--from may be):
    • a published caddis-plugin checkout → <src>/bundles/<target>/
    • a caddis checkout                  → <src>/dist/runtime-resources/<target>/
    • a .tar.gz (GitHub codeload shape, single top-level dir) → same roots inside it
    • omitted → download DEFAULT_TARBALL_URL and proceed as tarball

Safety contract:
    • a sha256 manifest (.claudster-init.json) records every file this tool wrote;
    • re-runs update only files still matching their manifest hash (unmodified);
    • files the user edited — or pre-existing files never written by this tool — are
      CONFLICTS: reported, left untouched, exit 1. --force overwrites them.

Exit codes: 0 ok / up-to-date · 1 conflicts (rest installed) · 2 bad target or source.
Windows-first: stdlib only, no POSIX assumptions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_NAME = ".claudster-init.json"   # hidden tool-internal; deliberately NOT renamed this round

# Functional identity in one place — every URL below derives from REPO_SLUG, and every env var from
# ENV_PREFIX, so a future rename is a constant edit. (Mirrored from claudster_config.py rather than
# imported: this script is downloadable standalone and must stay import-free.)
REPO_SLUG = "saajunaid/caddis-plugin"
REPO_URL = f"https://github.com/{REPO_SLUG}"
DEFAULT_TARBALL_URL = f"https://codeload.github.com/{REPO_SLUG}/tar.gz/refs/heads/main"
ENV_PREFIX = "CADDIS"
# Roots (relative to a source checkout) that may hold bundles, in preference order.
BUNDLE_ROOTS = ("bundles", "dist/runtime-resources")

def _home() -> Path:
    """User home — overridable via CADDIS_FAKE_HOME so tests never touch the real ~/.caddis etc."""
    return Path(os.environ.get(f"{ENV_PREFIX}_FAKE_HOME") or Path.home())


def _registry_path() -> Path:
    """The install registry: every apply is recorded so --update-all can re-run them and --doctor can
    report skew. User-level (survives per-project churn)."""
    return _home() / ".caddis" / "installs.json"


def _user_skills(target: str):
    """Harness user-level skills root + the bundle subdir holding that target's skills (probed
    2026-07-23): the harness merges skills from here for EVERY project, so --user installs once. The
    per-file manifest makes a later --uninstall surgical, so a flat install never disturbs the user's
    own skills (e.g. the azure-* set already under ~/.agents/skills)."""
    home = _home()
    table = {
        "codex": (home / ".codex" / "skills", ".codex/skills"),
        "antigravity": (home / ".agents" / "skills", ".agents/skills"),
        "codex-extras": (home / ".codex" / "skills", ".codex/skills"),
        "antigravity-extras": (home / ".agents" / "skills", ".agents/skills"),
    }
    return table.get(target)


def _user_skills_supported() -> list[str]:
    return ["codex", "antigravity", "codex-extras", "antigravity-extras"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _bundle_version(bundle: Path, src_root: Path | None) -> str:
    """Best-effort caddis version for stamping: the bundle's own plugin.json, else the source
    checkout's canonical claude-plugin version, else 'unknown'."""
    pj = bundle / "plugin.json"
    if pj.is_file():
        try:
            v = json.loads(pj.read_text(encoding="utf-8")).get("version")
            if v:
                return str(v)
        except Exception:
            pass
    if src_root is not None:
        rt = src_root / ".github" / "runtime-targets.json"
        if rt.is_file():
            try:
                m = json.loads(rt.read_text(encoding="utf-8"))
                for t in m.get("targets", []):
                    v = (t.get("plugin") or {}).get("version")
                    if v:
                        return str(v)
            except Exception:
                pass
    return "unknown"


def _read_registry() -> list[dict]:
    rp = _registry_path()
    if rp.is_file():
        try:
            return json.loads(rp.read_text(encoding="utf-8")).get("installs", [])
        except Exception:
            return []
    return []


def _record_install(location: Path, target: str, mode: str, version: str) -> None:
    """Append (or refresh) a registry entry keyed by (location, target). Idempotent per key."""
    installs = _read_registry()
    key = (str(location), target)
    installs = [e for e in installs if (e.get("location"), e.get("target")) != key]
    installs.append({
        "location": str(location), "target": target, "mode": mode,
        "version": version, "timestamp": _now(),
    })
    rp = _registry_path()
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps({"installs": installs}, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _available_targets(src_root: Path) -> dict[str, Path]:
    """Map target name -> bundle dir for every bundle the source offers."""
    found: dict[str, Path] = {}
    for rel in BUNDLE_ROOTS:
        root = src_root / rel
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if child.is_dir() and child.name not in found:
                found[child.name] = child
    return found


def _resolve_source(from_arg: str | None, scratch: Path) -> Path:
    """Return a directory that contains one of BUNDLE_ROOTS. Downloads/extracts as needed."""
    if from_arg is None:
        tgz = scratch / "bundle-source.tar.gz"
        print(f"Fetching {DEFAULT_TARBALL_URL} ...")
        urllib.request.urlretrieve(DEFAULT_TARBALL_URL, tgz)  # noqa: S310 — fixed https URL
        return _extract_tarball(tgz, scratch)
    src = Path(from_arg)
    if src.is_file():  # tarball path
        return _extract_tarball(src, scratch)
    return src


def _extract_tarball(tgz: Path, scratch: Path) -> Path:
    out = scratch / "extracted"
    with tarfile.open(tgz, "r:gz") as tf:
        tf.extractall(out, filter="data")
    # codeload tarballs have exactly one top-level directory (<repo>-<ref>/)
    entries = [p for p in out.iterdir() if p.is_dir()]
    return entries[0] if len(entries) == 1 else out


def _install(bundle: Path, dest: Path, target: str, force: bool, version: str = "unknown") -> int:
    manifest_path = dest / MANIFEST_NAME
    old_hashes: dict[str, str] = {}
    if manifest_path.exists():
        old_hashes = json.loads(manifest_path.read_text(encoding="utf-8")).get("files", {})

    new_hashes: dict[str, str] = {}
    installed, updated, conflicts, unchanged = [], [], [], []

    for src_file in sorted(p for p in bundle.rglob("*") if p.is_file()):
        rel = src_file.relative_to(bundle).as_posix()
        dst_file = dest / rel
        src_hash = _sha256(src_file)

        if not dst_file.exists():
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
            installed.append(rel)
            new_hashes[rel] = src_hash
            continue

        dst_hash = _sha256(dst_file)
        if dst_hash == src_hash:
            unchanged.append(rel)  # identical — adopt (covers pre-existing identical files)
            new_hashes[rel] = src_hash
        elif rel in old_hashes and dst_hash == old_hashes[rel]:
            shutil.copy2(src_file, dst_file)  # ours, unmodified — safe to update
            updated.append(rel)
            new_hashes[rel] = src_hash
        elif force:
            shutil.copy2(src_file, dst_file)
            updated.append(rel)
            new_hashes[rel] = src_hash
        else:
            conflicts.append(rel)  # user-modified or never ours — do not touch
            new_hashes[rel] = old_hashes.get(rel, dst_hash)

    manifest_path.write_text(
        json.dumps({"target": target, "version": version, "installed": _now(),
                    "files": new_hashes}, indent=2) + "\n",
        encoding="utf-8",
    )

    if installed:
        print(f"Installed {len(installed)} file(s).")
    if updated:
        print(f"Updated {len(updated)} file(s).")
    if not installed and not updated and not conflicts:
        print(f"Already up to date ({len(unchanged)} file(s) verified).")
    if conflicts:
        print("CONFLICTS — locally modified (or pre-existing) files left untouched;")
        print("re-run with --force to overwrite:")
        for rel in conflicts:
            print(f"  {rel}")
        return 1
    return 0


def _uninstall(dest: Path, target: str) -> int:
    """Remove manifest-tracked UNMODIFIED files (+ the registry entry). Modified/pre-existing files
    the user changed are listed and left. Makes trying caddis risk-free."""
    manifest_path = dest / MANIFEST_NAME
    if not manifest_path.exists():
        print(f"[FAIL] no {MANIFEST_NAME} at {dest} — nothing caddis-init installed here.", file=sys.stderr)
        return 2
    files = json.loads(manifest_path.read_text(encoding="utf-8")).get("files", {})
    removed, kept = [], []
    for rel, h in files.items():
        f = dest / rel
        if not f.exists():
            continue
        if _sha256(f) == h:
            f.unlink()
            removed.append(rel)
            p = f.parent  # prune now-empty dirs up to dest
            while p != dest and p.is_dir() and not any(p.iterdir()):
                p.rmdir()
                p = p.parent
        else:
            kept.append(rel)
    manifest_path.unlink()
    installs = [e for e in _read_registry() if (e.get("location"), e.get("target")) != (str(dest), target)]
    rp = _registry_path()
    if rp.is_file():
        rp.write_text(json.dumps({"installs": installs}, indent=2) + "\n", encoding="utf-8")
    print(f"Uninstalled {len(removed)} unmodified file(s).")
    if kept:
        print(f"Left {len(kept)} modified file(s) in place:")
        for rel in kept:
            print(f"  {rel}")
    return 0


def _apply(src_root: Path, target: str, dest: Path, force: bool, extras: bool, user: bool) -> int:
    """Install one target into dest (per-repo) or the user-level skills root (--user), record the
    registry, and (optionally) lay the extras tier over the core."""
    targets = _available_targets(src_root)
    if target not in targets:
        avail = ", ".join(sorted(targets)) or "none found"
        print(f"[FAIL] no '{target}' bundle in source. Available: {avail}", file=sys.stderr)
        return 2
    version = _bundle_version(targets[target], src_root)

    if user:
        # user = skills once for every project. Install only the skills subtree to the harness's
        # user skills root. Flat (the proven discovery path); the manifest tracks exactly what we wrote,
        # so a later --uninstall is surgical and never touches the user's own (e.g. azure-*) skills.
        us = _user_skills(target)
        if us is None:
            print(f"[FAIL] --user not supported for '{target}' (no user skills root). "
                  f"Supported: {', '.join(_user_skills_supported())}", file=sys.stderr)
            return 2
        user_root, subdir = us
        skills_src = targets[target] / subdir
        if not skills_src.is_dir():
            print(f"[FAIL] bundle '{target}' has no skills at {subdir}", file=sys.stderr)
            return 2
        user_root.mkdir(parents=True, exist_ok=True)
        rc = _install(skills_src, user_root, target, force, version)
        if rc in (0, 1):
            _record_install(user_root, target, "user", version)
        return rc

    rc = _install(targets[target], dest, target, force, version)
    if rc in (0, 1):
        _record_install(dest, target, "repo", version)
    if rc == 0 and extras:
        extras_name = f"{target}-extras"
        if extras_name in targets:
            print(f"-- installing extras tier: {extras_name}")
            rc = _install(targets[extras_name], dest, extras_name, force,
                          _bundle_version(targets[extras_name], src_root))
        else:
            avail = ", ".join(sorted(t for t in targets if t.endswith("-extras"))) or "none"
            print(f"[WARN] --extras: no '{extras_name}' bundle in source (available extras: {avail}) — "
                  "installed core only.", file=sys.stderr)
    return rc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="caddis-init", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--target", help="Harness bundle to install (e.g. codex, antigravity).")
    parser.add_argument("--from", dest="from_", metavar="SRC",
                        help="Local checkout dir or .tar.gz. Omit to download from GitHub.")
    parser.add_argument("--dest", default=".", help="Project directory to install into (default: cwd).")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite locally modified / pre-existing conflicting files.")
    parser.add_argument("--extras", action="store_true",
                        help="Also install the long-tail EXTRAS skills (the '<target>-extras' bundle) on "
                             "top of the lean core. Default install is core-only, to keep context lean.")
    parser.add_argument("--user", action="store_true",
                        help="Install SKILLS once at the harness's user level (~/.codex/skills, "
                             "~/.agents/skills) instead of per-project. Rules (AGENTS.md) stay per-repo.")
    parser.add_argument("--update-all", action="store_true",
                        help="Re-run every install recorded in the registry (~/.caddis/installs.json).")
    parser.add_argument("--uninstall", action="store_true",
                        help="Remove manifest-tracked UNMODIFIED files at --dest (+ registry entry).")
    args = parser.parse_args(argv)

    if args.update_all:
        installs = _read_registry()
        if not installs:
            print("No installs recorded — nothing to update.")
            return 0
        with tempfile.TemporaryDirectory(prefix="caddis-init-") as tmp:
            try:
                src_root = _resolve_source(args.from_, Path(tmp))
            except Exception as exc:
                print(f"[FAIL] could not obtain bundle source: {exc}", file=sys.stderr)
                return 2
            worst = 0
            for e in installs:
                loc, tgt, mode = Path(e["location"]), e["target"], e.get("mode", "repo")
                print(f"== update: {tgt} @ {loc} ({mode}) ==")
                if mode == "user":
                    rc = _apply(src_root, tgt, loc, args.force, False, True)
                else:
                    if not loc.is_dir():
                        print(f"[WARN] location gone, skipping: {loc}", file=sys.stderr)
                        continue
                    rc = _apply(src_root, tgt, loc, args.force, False, False)
                worst = max(worst, rc)
            return worst

    if args.uninstall:
        if not args.target:
            print("[FAIL] --uninstall needs --target.", file=sys.stderr)
            return 2
        dest = Path(args.dest).resolve()
        if args.user and _user_skills(args.target) is not None:
            dest = _user_skills(args.target)[0]
        return _uninstall(dest, args.target)

    if not args.target:
        print("[FAIL] --target is required (or use --update-all).", file=sys.stderr)
        return 2

    dest = Path(args.dest).resolve()
    if not args.user and not dest.is_dir():
        print(f"[FAIL] --dest is not a directory: {dest}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="caddis-init-") as tmp:
        try:
            src_root = _resolve_source(args.from_, Path(tmp))
        except Exception as exc:  # download/extract failure — actionable, fail-closed
            print(f"[FAIL] could not obtain bundle source: {exc}", file=sys.stderr)
            return 2
        return _apply(src_root, args.target, dest, args.force, args.extras, args.user)


if __name__ == "__main__":
    raise SystemExit(main())
