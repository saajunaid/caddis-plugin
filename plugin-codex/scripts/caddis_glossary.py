"""caddis_glossary — propose the words a project INVENTED, so they can be defined once.

WHY. Every project coins vocabulary out of ordinary English, and those are the worst words in
the codebase: a reader who guesses from the plain word gets them wrong and never knows. caddis
itself coined `pool`, `relay`, `drift`, `parking-lot`, `live-fire` — and its own glossary went
five and a half months without mentioning any of them, because nothing measured the gap.

WHAT THIS DOES AND DOES NOT DO. It PROPOSES candidates by measurement. It never writes a
definition, because a definition is domain knowledge that only a person or a model reading the
code can supply. A file of correct words with empty meanings is worse than no file: it looks
authoritative and teaches nothing. `/caddis:glossary` is the half that writes the meanings.

    python caddis_glossary.py                  # propose candidates, ranked
    python caddis_glossary.py --check          # exit 1 if a proposed term has no entry
    python caddis_glossary.py --scaffold       # create the file if it is missing

HOW A CANDIDATE IS CHOSEN. Frequency alone is useless — "the file" beats every real term. A
word is a candidate when it is COMMON IN THIS REPO but is not ordinary technical English. The
stop-list below is the load-bearing part, and it is deliberately generous: a false positive
costs a human three seconds to ignore, while a false negative leaves a coined word undefined
forever, which is the failure being fixed.

ACCURACY, MEASURED. On a normal application repo it is good: run against `docket` it proposed
`board`, `lane`, `card`, `gate` — that project's actual coined vocabulary, top of the list. On a
HARNESS repo full of documentation ABOUT agents it is noisier, because words like `protocol` and
`intent` are both ordinary English and genuinely overloaded here. It is a suggester, not an
oracle; a human or the model decides what earns an entry.

Stdlib only, cross-platform, and it never raises on a bad file — it is run by a command and by
a gate, and a traceback from either is worse than a missing suggestion.
"""
from __future__ import annotations

import argparse
import collections
import os
import re
import sys

# ── what a project's own vocabulary lives in ────────────────────────────────────────────
DOC_GLOBS = (".md",)
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__",
    ".mypy_cache", ".pytest_cache", "vendor", "site-packages", ".next", "target",
    # Vendored and reference material is someone ELSE'S vocabulary. Without these, caddis's
    # own run proposed `aws4` (33 files) and `mxgraph` (11) out of bundled AWS and draw-io
    # reference docs — words no caddis reader will ever meet.
    "references", "assets", "fixtures", ".archive", "archive", "examples", "sample",
    "samples", "third_party", "vendored", "node_modules", "bundles", "runtime-resources",
}

# Ordinary technical English. A word here is never proposed, however often it appears.
# Longer than it looks necessary on purpose: the cost of a false positive is a human ignoring
# one line; the cost of a false negative is a coined word nobody ever defines.
COMMON = {
    # english scaffolding
    "the", "and", "for", "with", "that", "this", "from", "into", "than", "then", "when",
    "where", "which", "what", "who", "why", "how", "not", "but", "all", "any", "each",
    "one", "two", "only", "also", "more", "most", "less", "some", "such", "same", "other",
    "its", "it's", "you", "your", "our", "their", "they", "them", "has", "have", "had",
    "was", "were", "been", "being", "are", "can", "will", "would", "should", "must", "may",
    "does", "did", "done", "doing", "use", "used", "using", "make", "made", "get", "got",
    "see", "read", "write", "run", "runs", "running", "ran", "set", "put", "take", "give",
    "new", "old", "first", "last", "next", "now", "here", "there", "before", "after",
    "over", "under", "out", "off", "own", "per", "via", "yes", "no", "if", "in", "on", "of",
    "to", "at", "by", "as", "is", "be", "or", "so", "up", "do", "an", "a",
    # ordinary software vocabulary — predictable from the word itself
    "file", "files", "path", "paths", "dir", "directory", "folder", "code", "line", "lines",
    "test", "tests", "testing", "error", "errors", "bug", "fix", "fixed", "build", "built",
    "commit", "commits", "branch", "merge", "push", "pull", "repo", "repository", "git",
    "api", "cli", "url", "http", "https", "json", "yaml", "toml", "html", "css", "sql",
    "user", "users", "name", "names", "value", "values", "key", "keys", "type", "types",
    "list", "lists", "table", "tables", "row", "rows", "column", "field", "fields",
    "function", "method", "class", "module", "package", "library", "script", "scripts",
    "server", "client", "request", "response", "data", "input", "output", "config",
    "version", "release", "install", "update", "delete", "create", "add", "remove",
    "return", "returns", "call", "calls", "check", "checks", "log", "logs", "note", "notes",
    "step", "steps", "case", "cases", "example", "default", "option", "options", "flag",
    "flags", "command", "commands", "tool", "tools", "agent", "agents", "model", "models",
    "session", "sessions", "context", "prompt", "prompts", "token", "tokens", "cache",
    "state", "status", "result", "results", "change", "changes", "work", "works", "time",
    "does", "doc", "docs", "document", "section", "page", "text", "content", "format",
    "project", "projects", "team", "user", "system", "service", "process", "task", "tasks",
    "issue", "issues", "problem", "solution", "reason", "cause", "point", "part", "way",
    "thing", "things", "need", "needs", "want", "know", "like", "just", "even", "still",
    "never", "always", "every", "both", "because", "while", "since", "about", "against",
    # added after the first real run proposed all of these — ordinary in any codebase
    "skill", "skills", "plan", "plans", "phase", "phases", "design", "designs", "review",
    "reviews", "mode", "modes", "pattern", "patterns", "implementation", "reference",
    "description", "descriptions", "workflow", "workflows", "feature", "features",
    "component", "components", "interface", "structure", "approach", "detail", "details",
    "requirement", "requirements", "specification", "architecture", "instructions",
    "guidelines", "standard", "standards", "best", "practice", "practices", "overview",
    "summary", "report", "reports", "action", "actions", "level", "levels", "order",
    "number", "count", "size", "start", "stop", "begin", "end", "open", "close", "load",
    "save", "store", "fetch", "send", "receive", "handle", "handles", "support", "supports",
    "references", "security", "scope", "verification", "react", "python", "typescript",
}

_WORD = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", re.I)

# A term must appear at least this often, in at least this many files, to be proposed.
# One mention is a passing usage; a coined term earns its definition by recurring.
MIN_USES = 12
MIN_FILES = 3
MAX_SUGGESTIONS = 25
# A coined term is specific, so in a LARGE corpus it shows up in a minority of files. Measured:
# `description` appeared in 2112 of ~2500 caddis docs and outranked every real term.
#
# But this rule INVERTS on a small repo. Applied unconditionally it deleted docket's four best
# candidates — `board`, `lane`, `card`, `docket` — because in a 50-file repo the core vocabulary
# genuinely is in most files. So it only engages once there are enough files for "share" to
# mean anything.
MAX_FILE_SHARE = 0.25
SHARE_RULE_MIN_CORPUS = 200


def _doc_files(root: str) -> list[str]:
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".venv")]
        for n in filenames:
            if n.endswith(DOC_GLOBS):
                found.append(os.path.join(dirpath, n))
    return found


def glossary_path(root: str) -> str:
    """`.caddis/kb/GLOSSARY.md` — beside the KB, which is where reference docs live."""
    return os.path.join(root, ".caddis", "kb", "GLOSSARY.md")


def defined_terms(path: str) -> set[str]:
    """Canonical terms are the first cell of each markdown table row."""
    if not os.path.isfile(path):
        return set()
    terms = set()
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.startswith("|"):
                    continue
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) < 2 or not cells[0] or set(cells[0]) <= {"-", ":", " "}:
                    continue
                head = cells[0].strip("`*").lower()
                if head in {"term", "canonical term", "word"}:
                    continue
                terms.add(head)
    except OSError:
        return set()
    return terms


def propose(root: str) -> list[tuple[str, int, int]]:
    """Return [(term, uses, files)] — words this repo says often that plain English does not."""
    uses: collections.Counter = collections.Counter()
    files: dict[str, set] = collections.defaultdict(set)
    for f in _doc_files(root):
        try:
            text = open(f, encoding="utf-8", errors="replace").read().lower()
        except OSError:
            continue
        # Strip fenced code and inline code: identifiers are not project vocabulary.
        text = re.sub(r"```.*?```", " ", text, flags=re.S)
        text = re.sub(r"`[^`]*`", " ", text)
        for w in _WORD.findall(text):
            if len(w) < 4 or w in COMMON:
                continue
            uses[w] += 1
            files[w].add(f)
    total = max(1, len(_doc_files(root)))
    out = [
        (w, n, len(files[w]))
        for w, n in uses.items()
        if n >= MIN_USES
        and len(files[w]) >= MIN_FILES
        and (total < SHARE_RULE_MIN_CORPUS or (len(files[w]) / total) <= MAX_FILE_SHARE)
    ]
    out.sort(key=lambda r: (-r[1], r[0]))
    return out


TEMPLATE = """# Glossary

The words this project invented out of ordinary English, defined once.

**Admission test:** a term belongs here when its meaning in this project is *distinct enough
from its ordinary technical sense that a newcomer would misread it*. `commit` does not belong.
A word this team uses in its own way does.

Proposed by `caddis_glossary.py`, which measures which words this repo says often that plain
English does not. It cannot write the definitions — run `/caddis:glossary` and the model will
draft them from the actual code, or write them yourself.

| Term | Definition | DO NOT USE |
|---|---|---|
| _example_ | Replace this row. A definition should say what the word means HERE, and why the ordinary reading is wrong. | the synonyms that cause confusion |

## Flagged ambiguities

Name the words that are still overloaded rather than pretending the vocabulary is clean. A
glossary that hides its own dirt starts lying. Delete this section only when there is genuinely
nothing to flag.
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=os.getcwd())
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if a proposed term has no entry")
    ap.add_argument("--scaffold", action="store_true",
                    help="write the glossary template if it does not exist")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root)
    path = glossary_path(root)

    if args.scaffold:
        if os.path.isfile(path):
            print("[glossary] present — kept: %s" % os.path.relpath(path, root))
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(TEMPLATE)
            print("[glossary] wrote %s" % os.path.relpath(path, root))
        return 0

    candidates = propose(root)
    defined = defined_terms(path)
    missing = [(w, n, f) for w, n, f in candidates if w not in defined]

    if args.check:
        # Advisory by design. A project may legitimately decide a frequent word needs no
        # definition, and a gate that cannot be satisfied gets bypassed rather than obeyed.
        if not os.path.isfile(path):
            print("[glossary] no %s — run with --scaffold" % os.path.relpath(path, root))
            return 0
        if missing:
            print("[glossary] %d frequent term(s) with no entry:" % len(missing))
            for w, n, f in missing[:MAX_SUGGESTIONS]:
                print("    %-24s %4d uses in %d files" % (w, n, f))
            print("  Define them, or leave them — this is advisory. `/caddis:glossary` drafts them.")
            return 1
        print("[glossary] every frequent term is defined (%d entries)" % len(defined))
        return 0

    if not candidates:
        print("[glossary] no candidates — too few docs, or nothing recurs enough.")
        return 0
    print("Candidate vocabulary for %s" % root)
    print("  (>= %d uses across >= %d files, ordinary English excluded)\n" % (MIN_USES, MIN_FILES))
    print("  %-26s %6s %6s  %s" % ("TERM", "USES", "FILES", "DEFINED?"))
    for w, n, f in candidates[:MAX_SUGGESTIONS]:
        print("  %-26s %6d %6d  %s" % (w, n, f, "yes" if w in defined else "-- no --"))
    if missing:
        print("\n  %d undefined. Run `/caddis:glossary` to draft definitions from the code."
              % len(missing))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # pragma: no cover — a suggester must never break a caller
        print("[glossary] skipped: %s" % exc)
        sys.exit(0)
