# The profile contract

A profile describes one KIND of component, not one app. It lives at
`profiles/<stack-name>/profile.json`. `profiles/_template/profile.json` is the starting point
for a new one, and phase 2 (`Resolve-AppProfile.ps1`) never matches `_template` itself against a
real inventory unless something explicitly asks `Get-AdoptProfiles` for it with
`-IncludeTemplate`.

Every profile file is loaded and checked against this contract BEFORE any detection runs, by
`Test-AdoptProfileContract` in `AdoptCommon.ps1`. **One broken profile fails detection for every
app being resolved, not just the one that owns it** - `Resolve-AppProfile.ps1` refuses to run at
all while any profile under `profiles/` fails the checks below.

## Required keys

All ten must be present. The contract only checks that the key EXISTS; it does not validate the
shape of what is inside it.

| Key | Meaning |
|---|---|
| `name` | The stack's short name, e.g. `node-service`. Matches the folder name by convention. |
| `status` | `proven`, `draft`, or `placeholder`. See below. |
| `description` | One sentence: what kind of component this is. |
| `detect` | The rules that decide whether a component folder is this stack. See below. |
| `runtimes` | The language/runtime(s) it needs: kind, exact version, and how that version gets onto a box. |
| `build` | The ordered build steps: what each one does and the command. |
| `routing` | How traffic reaches it: reverse proxy, a rewrite rule, a dedicated site, or none. |
| `config` | Which files carry per-environment settings, and the rule that keeps them out of version control. |
| `data` | The migration tool, if any, and where persistent state actually lives. |
| `ci` | The CI workflow file, the jobs that must pass, and which job deploys. |
| `deploy` | The deploy script, and at least one check that would FAIL on a broken deploy. |

**Plus one rule that is not a top-level key check:** the profile must also carry `services` or
`schedule` (or both).

- `services` describes a component that answers requests. Each entry names a role
  (`api`/`web`/`worker`/`database`), a port, a start command, the process manager that keeps it
  running, the interface it binds, and a health check.
- `schedule` describes a batch component instead: what triggers a run - a scheduler, a
  file-arrival watcher, or a manual/CI trigger.

A component that is neither long-running nor scheduled does not fit this contract yet.

## Status values

| Status | Licenses |
|---|---|
| `placeholder` | Only `_template`'s own state. Its `name` is still the literal `<stack-name>` placeholder text - which is exactly why the "no leftover placeholder" rule below is skipped for `placeholder` alone. |
| `draft` | A description a person can follow by hand. It can still be DETECTED and matched to a real component - phase 2 will report it, with its status shown as `draft` - but nothing has automated it end to end yet. Follow it manually, write down what you actually did, and let it earn `proven` later. |
| `proven` | Something has actually automated this stack end to end: build, deploy and verify have all been run for real against a live component, not only described. |

Two more rules `Test-AdoptProfileContract` enforces on `status`:

- It must be exactly one of the three values above. Anything else fails the contract for every
  profile in the directory, not only this one.
- Unless `status` is `placeholder`, `name` must not contain `<` or `>`. This is what stops a copy
  of `_template` being left half-filled-in and silently matching real apps with its placeholder
  name still inside it.

## The five `detect` rule kinds

Checked by `Test-AdoptDetect`, against two things gathered per component: a list of relative
file paths, and the text of a handful of small files. Which files make it into either list is
bounded - see "What `detect` can actually see" below.

| Kind | Shape | Meaning |
|---|---|---|
| `allFiles` | list of globs | Every glob must match at least one path, or the profile does not match at all. |
| `anyFiles` | list of globs | At least one glob must match at least one path, or the profile does not match at all. |
| `noneFiles` | list of globs | If ANY glob matches, the profile does not match at all. A pure veto - it never adds to the score. |
| `fileContains` | list of `{ "file": glob, "pattern": regex }` | Every entry's glob must resolve to a file whose text matches `pattern`, or the profile does not match. |
| `noneContain` | list of `{ "file": glob, "pattern": regex }` | If any entry's glob resolves to a file whose text matches `pattern`, the profile does not match. A pure veto. |

All five are optional; omit whichever a stack does not need. A profile that declares none of them
never matches anything.

## Glob-to-regex translation, exactly

Every glob - in `allFiles`, `anyFiles`, `noneFiles`, or a `fileContains`/`noneContain` entry's
`file` - goes through the same conversion, in this order:

1. `[regex]::Escape($glob)` - escape every regex-special character literally, including `*`.
2. Replace an escaped `**` (now `\*\*`) with `.*` - matches across any number of path segments.
3. Replace a remaining escaped `*` (`\*`) with `[^\\/]*` - matches within ONE path segment only.
4. Replace `/` with `[\\/]` - so a glob written with a forward slash matches a path recorded
   with either separator.
5. Anchor the whole thing as `(?i)^...$` - case-insensitive, and the WHOLE relative path must
   match, not a substring of it.

So `src/*.ts` matches `src/index.ts` but not `src/api/index.ts` (one segment only), while
`src/**/*.ts` matches both. A bare filename like `package.json` matches only at the root of the
component being tested, not at any depth beneath it - write `**/package.json` for "anywhere
under this component."

## How the score is computed

`Test-AdoptDetect` returns `0` for no match, or a positive score where a higher number means a
more specific match:

- `allFiles` declared and satisfied -> **+1**. Declared and NOT satisfied -> return `0`
  immediately, regardless of anything else.
- `anyFiles` declared and satisfied -> **+1**. Declared and NOT satisfied -> return `0`
  immediately.
- `fileContains` declared and satisfied -> **+1**. Declared and NOT satisfied -> return `0`
  immediately.
- `noneFiles` and `noneContain` never add to the score. They are vetoes only: if either is
  violated, the rule returns `0` no matter what else matched.

The maximum score is `3` (`allFiles` + `anyFiles` + `fileContains` all declared and all
satisfied). Phase 2 runs every profile against every component and keeps the highest-scoring
match as the winner. Everything else that scored above `0` is recorded in `alsoMatches`, never
discarded - a component genuinely matching two stacks is a decision for a person, and picking one
silently would hide that decision.

## What `detect` can actually see

A rule can only use evidence the inventory actually indexed. Two different limits apply,
depending on what kind of file a glob names.

- **Manifests, entry points, config files, CI files, docs, and test markers** - anything matching
  one of the fixed name lists `Get-AppInventory.ps1` already recognises (`package.json`,
  `pyproject.toml`, `Dockerfile`, `main.py`, `.env*`, a file under a `workflows` folder,
  `README*`, `pytest.ini`, and the rest) - are indexed at ANY depth in the tree.
- **Everything else** - an arbitrary filename a `detect` rule names that is not one of those
  fixed names, for example `index.html` as evidence of a front end - only lands in the general
  shallow path index, and that index is depth-limited: paths at depth 2 or shallower from the
  scanned root are always kept; paths at depth 3-4 are kept only while a single cap shared across
  the WHOLE scan (`DetectPathCap`, default 20000 paths) still has room. Past depth 4, or once
  that cap is spent, a `detect` rule naming such a file cannot see it - not because the file is
  absent, but because nothing recorded that it exists.

`fileContains`/`noneContain` add a second limit on top of path indexing: the named file must
actually be fetched, which only happens for files under 256 KB. A rule that reads a large
generated file will never see its content.

**Practical rule of thumb:** name a real manifest or entry-point filename in
`allFiles`/`anyFiles` whenever the stack has one - that evidence survives at any depth. Reserve
arbitrary, non-manifest filenames for secondary evidence, and expect them to be missed on a
deeply nested component or a very large tree.

## Worked example: adding a new stack

Say a fleet starts running a Rust service and no profile describes it yet. Phase 2 would report
"NO PROFILE MATCHED ANY FOLDER" and exit 2 for that component.

1. Copy the template:

       cp -r profiles/_template profiles/rust-service

2. Fill in `profiles/rust-service/profile.json`. Start with `status: "draft"` - nothing has
   automated this stack yet, only described it:

       {
         "name": "rust-service",
         "status": "draft",
         "description": "A Rust HTTP service built with Cargo, e.g. Actix Web or Axum.",
         "detect": {
           "allFiles": ["Cargo.toml"],
           "fileContains": [
             { "file": "Cargo.toml", "pattern": "(actix-web|axum|rocket)" }
           ]
         },
         "runtimes": [
           {
             "kind": "rust",
             "version": "<from Cargo.toml or rust-toolchain.toml>",
             "provision": "<installed on dev and prod hosts; confirm the installed version matches what is declared>"
           }
         ],
         "build": [
           { "what": "Compile", "command": "cargo build --release" }
         ],
         "services": [
           {
             "role": "api",
             "port": "<the app's HTTP port>",
             "start": "<the built binary, e.g. target/release/app>",
             "manager": "<a service manager or a container runtime>",
             "bind": "<loopback-only, unless a trusted edge forwards identity>",
             "health": "<the app's real health route - confirm it, do not assume a default path>"
           }
         ],
         "routing": { "mode": "reverse-proxy", "apiPrefix": "/api" },
         "config": {
           "files": ["<the env file it reads, per environment>"],
           "rule": "kept out of version control; a committed example file with placeholder values"
         },
         "data": {
           "migrations": "<its migration tool, if any>",
           "state": "<where persistent state actually lives>"
         },
         "ci": {
           "workflow": "<CI workflow file>",
           "requiredJobs": ["<build_and_test>"],
           "deployJob": "<deploy_prod>"
         },
         "deploy": {
           "script": "<deploy script>",
           "verify": ["<a check that would FAIL on a broken deploy>"]
         }
       }

3. Re-run phase 2. If a real component's `Cargo.toml` mentions `axum`, it now scores `2`
   (`allFiles` + `fileContains`) and is reported with `status: draft`.
4. Follow the profile by hand on a real adoption. Write down what was actually done for build,
   deploy and health, then raise `status` to `proven` only once all of it has genuinely been
   automated - not before.
