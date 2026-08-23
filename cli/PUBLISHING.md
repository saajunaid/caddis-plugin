# Publishing `@caddis/cli`

> **Nothing here has been run.** The CLI is built and wired; publishing is a deliberate human act.

## The chain

```
  claudster-source (SOURCE OF TRUTH)            caddis-plugin (PUBLIC MIRROR)
  ├─ .github/            the agent pool         ├─ plugin/            Claude Code plugin
  ├─ cli/                @caddis/cli source ──► ├─ cli/               synced by caddis-push
  └─ sync.ps1            caddis-push  ─────────►├─ bundles/           synced by caddis-push
                                                └─ .github/workflows/
                                                     npm-publish.yml  synced by caddis-push
                                                              │
                                                       tag cli-v0.1.0
                                                              ▼
                                                         npm: @caddis/cli
```

The CLI source lives in `claudster-source` (one source of truth, versioned with the pool — no
separate repo, no cross-repo drift). It is **published from the mirror**, which is already the public
distribution repo and already receives the exported bundles. `caddis-push` syncs `cli/` and installs
the workflow; the mirror's Action publishes on a tag.

## Status

| | |
| --- | --- |
| `@caddis` npm org | ✅ claimed |
| Package name | ✅ `@caddis/cli`, bins `caddis`, `caddis-cli`, `claude-oss`, `claude-glm`, `claude-deepseek` |
| Pre-publish scrub | ✅ done (shipped 1.3.39) |
| CLI build + tests | ✅ green |
| `caddis-push` syncs `cli/` | ✅ wired (`sync.ps1`) |
| Publish workflow | ✅ live in the mirror |
| npm bootstrap publish | ✅ `0.0.0` placeholder published + deprecated 2026-07-27 |
| npm trusted publisher | ✅ configured (`saajunaid/caddis-plugin` · `npm-publish.yml` · env `npm-publish`) |
| **First OIDC release** | ✅ **`@caddis/cli@0.1.0` published 2026-07-27, provenance signed** |

**Steps 1–3 below are DONE and never repeat.** For a new version, jump to
[Releasing a new version](#releasing-a-new-version-steps-13-are-never-repeated) — bump, `caddis-push`,
tag. They are kept here as the record of how the package was bootstrapped.

### v0.1.0 release evidence

- Run [30308306628](https://github.com/saajunaid/caddis-plugin/actions/runs/30308306628) — all steps green in 25 s
- `npm notice publish Signed provenance statement with source and build information from GitHub Actions`
- Sigstore transparency log: <https://search.sigstore.dev/?logIndex=2261751228>
- `npx @caddis/cli@0.1.0 doctor` verified from the public registry

### Known follow-up (non-blocking)

`actions/checkout@v4` and `actions/setup-node@v4` target Node 20, which GitHub has deprecated — runs
are force-migrated to Node 24 and emit a warning. Bump both to `@v5` with the next release; it needs a
`caddis-push` + dry run, so it was deliberately not done mid-release.

---

# THE BOOTSTRAP PROBLEM — read this first

**npm trusted publishing cannot perform a package's FIRST publish.**

Trusted publishing is configured **per package**, on that package's own settings page — there is no
org-level "Trusted publishers" screen, which is why you could not find one under the `@caddis` org.
And npm will not let you configure a trusted publisher for a package that does not exist yet
([npm/cli#8544](https://github.com/npm/cli/issues/8544)). PyPI allows this; npm does not.

So the order is forced:

```
  1. upgrade npm            →  2. publish a 0.0.0 placeholder BY HAND (creates the package)
                            →  3. add the trusted publisher to the now-existing package
                            →  4. caddis-push + rehearse
                            →  5. tag cli-v0.1.0  →  every release from here is OIDC, no token
```

Only step 2 is done by hand. It exists purely to make the package exist.

---

## Step 1 — npm version (OPTIONAL — skip if using the web UI)

**You do not need to upgrade npm to publish.** The version floors apply where OIDC actually happens:

| Need | Floor | Where it applies |
| --- | --- | --- |
| Trusted Publishing (OIDC) | npm ≥ 11.5.1 | **the CI runner** — the workflow installs it itself |
| `npm trust` CLI | npm ≥ 11.15.0 | **this machine**, and only for step 3 Route B |
| Bootstrap publish (step 2) | any modern npm | this machine — **npm 10.9.2 is fine** |

So: if you configure the trusted publisher through the **web UI (Route A)**, skip this step entirely.

If you want the `npm trust` CLI, **do not run `npm install -g npm@latest`** — `npm@latest` is now
12.0.1, which requires `node ^22.22.2 || ^24.15.0 || >=26.0.0`, and this machine runs node 22.14.0.
That fails with `EBADENGINE`. Pin to the 11.x line instead, which requires only
`node ^20.17.0 || >=22.9.0`:

```powershell
npm install -g npm@^11.15.0
npm -v            # expect 11.18.x
```

(Upgrading node to 22.22+ or 24 would also work and would let `npm@latest` install — but it is a
bigger change than this needs.)

Regardless of route, confirm **2FA is enabled on your npm account** (Account → Two-factor
authentication). Trusted publishing requires it, and granular tokens with "bypass 2FA" are not accepted.

## Step 2 — Publish the 0.0.0 placeholder by hand

This is the one manual publish. It creates the package so a trusted publisher can be attached to it.
Publish a **minimal placeholder**, not the real CLI — the real 0.1.0 should be built and signed by CI.

> 🚨 **Run this from a TEMP DIRECTORY, never from `cli/`.** `npm publish` publishes whatever is in
> the current directory. Run it in `cli/` and you publish the real 0.1.0 by hand — unsigned, no
> provenance, not built by CI — and burn the version number you wanted CI to release. The block below
> `Set-Location`s away from the repo first, on purpose. **Do not `cd` back to `cli/` until after the
> publish.**

An ordinary VS Code / PowerShell terminal is fine — **no administrator elevation is needed**.
`npm publish` writes to the registry, and `npm login` writes a token to `%USERPROFILE%\.npmrc`;
neither touches a protected location. Running elevated would put the token in the wrong profile.

```powershell
# 1. build the placeholder in a temp dir (no here-strings: safe to paste)
$boot = Join-Path $env:TEMP "caddis-cli-bootstrap"
Remove-Item -Recurse -Force $boot -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $boot | Out-Null
Set-Location $boot

npm init -y | Out-Null
npm pkg set name='@caddis/cli' version='0.0.0' description='Placeholder - the real CLI publishes from CI at 0.1.0.' license='MIT' publishConfig.access='public'
npm pkg delete main scripts devDependencies keywords author
'Placeholder. Install 0.1.0 or later.' | Set-Content README.md -Encoding utf8

# 2. CHECK before you publish — name @caddis/cli, version 0.0.0, 2 files, ~300 B
Get-Location
Get-Content package.json
npm pack --dry-run

# 3. publish
npm login                       # opens a browser; 2FA
npm publish --provenance=false  # provenance CANNOT be generated outside CI
```

Expected output of the check step:

```
Path: C:\Users\<you>\AppData\Local\Temp\caddis-cli-bootstrap
{ "name": "@caddis/cli", "version": "0.0.0", ... "publishConfig": { "access": "public" } }
npm notice name: @caddis/cli   version: 0.0.0   total files: 2   package size: 305 B
```

If `Get-Location` shows anything under `claudster-source`, **stop** — you are about to publish the
real package.

> **Why `--provenance=false`:** `cli/package.json` sets `publishConfig.provenance: true` so CI always
> attaches provenance. That same setting makes a **local** publish fail — provenance can only be
> generated inside a supported CI with an OIDC token. The flag is needed for this one command only.

Then mark it so nobody installs it by accident:

```powershell
npm deprecate @caddis/cli@0.0.0 "Placeholder release. Use 0.1.0 or later."
```

## Step 3 — Add the trusted publisher

Now that the package exists, either route works. **The web UI is the reliable one.**

**Route A — web UI (recommended)**

Go to **<https://www.npmjs.com/package/@caddis/cli/access>**
(equivalently: npmjs.com → your package → **Settings** → **Trusted publishing** → *Select your publisher*)

Choose **GitHub Actions** and enter, exactly:

| Field | Value |
| --- | --- |
| Organization or user | `saajunaid` |
| Repository | `caddis-plugin` ← the **mirror**, not `claudster-source` |
| Workflow filename | `npm-publish.yml` |
| Environment name | `npm-publish` |
| Allowed actions | publish |

**Route B — CLI** (only this route needs the npm upgrade in step 1):

```powershell
npm trust github @caddis/cli --repo saajunaid/caddis-plugin --file npm-publish.yml --env npm-publish --allow-publish --dry-run
# drop --dry-run when the preview looks right
npm trust list @caddis/cli
```

> ⚠️ **The Environment name must match the workflow — change both or neither.** The workflow declares
> `environment: npm-publish`. If you enter `npm-publish` above, they match and you are done. If you
> would rather not use an environment, leave that field blank **and** delete the `environment:`
> line from `.github/workflows/npm-publish.yml`. A mismatch fails the OIDC claim check at publish time.

**Recommended while you are here:** in the mirror, **Settings → Environments → New environment →
`npm-publish`**, and add yourself as a *required reviewer*. Every publish then waits for your click.

## Step 4 — Sync into the mirror and rehearse

From `claudster-source`:

```powershell
caddis-push
```

This copies `cli/` (src, test, scripts, package.json, package-lock.json, configs, README, LICENSE)
into the mirror and installs `.github/workflows/npm-publish.yml` at the mirror root. It publishes
nothing. Confirm:

```powershell
cd ..\vscode-extensions\caddis-plugin
git status        # cli/ + .github/workflows/npm-publish.yml present
```

Then rehearse in CI — `workflow_dispatch` defaults to `dry_run: true`, which installs, typechecks,
tests, builds, smoke-tests `dist/cli.js` and runs `npm pack --dry-run` **without publishing**:

> mirror → **Actions** → **npm-publish** → **Run workflow** → leave *dry run* checked.

A green dry run proves the OIDC handshake, the build and the tarball before anything is public.

## Step 5 — The first real release

```powershell
# in the mirror, on the commit you want released
git tag cli-v0.1.0
git push origin cli-v0.1.0
```

The tag prefix is `cli-` on purpose: the mirror also carries the Claude Code plugin, and a bare `v*`
tag must not fire an npm publish. The workflow fails the run if the tag does not match
`cli/package.json`'s version.

Verify:

```powershell
npm view @caddis/cli version
npx @caddis/cli@latest doctor
```

## Step 6 — Reserve the defensive alias (optional)

The unscoped `caddis-cli` name is free and worth holding so `npx caddis-cli` also resolves. Publish a
minimal placeholder that depends on `@caddis/cli`. Unscoped `caddis` itself is taken by an abandoned
2022 package — not worth blocking launch on.

---

## Releasing a new version (steps 1–3 are never repeated)

1. Change the pool and/or `cli/src` in `claudster-source`.
2. Bump `cli/package.json`'s version.
3. `caddis-push` — re-exports the bundles, syncs `cli/`.
4. In the mirror: `git tag cli-vX.Y.Z && git push origin cli-vX.Y.Z`.

The bundles are copied into the package at build time by `scripts/copy-bundles.mjs`, so a release
always carries the pool exported alongside it. That script **warns** if the exported bundle version
disagrees with `.github/runtime-targets.json` — that warning means the bundles are stale, so re-run
the export before tagging.

## Guard rails already in the workflow

- Tag/`package.json` version match is enforced.
- `typecheck` → `test` → `build` → bundle-presence check → CLI smoke test all gate the publish.
- `npm pack --dry-run` prints the tarball contents into the log before anything is published.
- `permissions:` is `id-token: write` + `contents: read` — nothing else.
- Publishing only ever happens on a `cli-v*` tag push, never on a branch.
- No `NPM_TOKEN` exists anywhere after step 3. Nothing to leak, nothing to rotate.

## If the publish step fails

| Error | Cause |
| --- | --- |
| `404` / `you do not have permission` | trusted publisher not configured, or configured on the wrong repo |
| OIDC claim mismatch | workflow `environment:` and npm's *Environment name* disagree — see step 3 |
| `provenance ... not supported` | you ran `npm publish` locally; add `--provenance=false` (bootstrap only) |
| `npm trust` not found | npm < 11.15.0 — redo step 1, or use the web UI |
| `EBADENGINE` upgrading npm | you ran `npm i -g npm@latest`; npm 12 needs newer node. Use `npm i -g npm@^11.15.0` |
