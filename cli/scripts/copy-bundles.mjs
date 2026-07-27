#!/usr/bin/env node
/**
 * Copy the pre-exported caddis bundles into the npm package at build time.
 *
 * The bundles are NOT source. They are produced by `export_runtime_resources.py`
 * and land in the public mirror at `vscode-extensions/caddis-plugin/bundles/`
 * via `caddis-push`. This script snapshots the ones the CLI actually ships so
 * "the caddis you installed IS the pool you get" (plan: bundle-shipping).
 *
 * Run standalone:  node scripts/copy-bundles.mjs [--check]
 *   --check  verify only; do not write. Exits 1 if a shipped bundle is missing.
 */
import { cp, mkdir, readFile, rm, writeFile, stat, readdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CLI_ROOT = path.resolve(HERE, '..');
const SOURCE_ROOT = path.resolve(CLI_ROOT, '..');

/**
 * Candidate locations for the exported bundles, most-canonical first.
 *  1. the public mirror checkout (what caddis-push writes, what ships)
 *  2. the local export output (dist/runtime-resources) — lets a dev build the
 *     CLI straight after `export_runtime_resources.py` without a mirror.
 *  3. `bundles/` beside the CLI — the layout inside the MIRROR itself, where
 *     this package is published from and no `vscode-extensions/` exists.
 */
const BUNDLE_SOURCES = [
  path.join(SOURCE_ROOT, 'vscode-extensions', 'caddis-plugin', 'bundles'),
  path.join(SOURCE_ROOT, 'dist', 'runtime-resources'),
  path.join(SOURCE_ROOT, 'bundles'),
];

/**
 * v0.1 ships ONLY the bundles an implemented adapter installs from.
 *
 * The export produces six bundles (~32 MB total). What each one is, and why it
 * is or is not in the npm tarball:
 *
 *   antigravity-plugin        1.4 MB  ✅ SHIPPED — the agy PLUGIN (plugin.json,
 *                                     hooks.json, agents/, skills/, guard +
 *                                     session_end + warm_start, statusline, mcp).
 *                                     This is the only bundle a v0.1 adapter
 *                                     installs from: `agy plugin install <dir>`.
 *   antigravity               1.3 MB  ✗  same content as a file-drop (.agents/ +
 *                                     AGENTS.md) for agy users who do not use the
 *                                     plugin system. No v0.1 adapter drives it.
 *   codex                     1.3 MB  ✗  the Codex file-drop (.codex/ + AGENTS.md).
 *                                     The Codex adapter is a v0.2 stub that writes
 *                                     nothing, so this would be dead weight.
 *   antigravity-plugin-extras 9.3 MB  ✅ SHIPPED (v0.2) — the SEPARATE `caddis-extras`
 *                                     agy plugin, versioned independently of core.
 *                                     Installed ONLY on `--extras` (or to keep an
 *                                     existing extras install current), matching
 *                                     `caddis-init --extras`. ~7 MB of its size is
 *                                     two asset-heavy skills (canvas-design 5.6 MB,
 *                                     ui-ux-intelligence 1.5 MB).
 *   antigravity-extras        9.3 MB  ✗  the same extras as a file-drop, and
 *   codex-extras              9.3 MB  ✗  the Codex form. No adapter reads either.
 *
 * Claude Code is absent from this list on purpose: it installs caddis from its
 * own marketplace, so its bundle never needs to ride in the tarball at all.
 *
 * Shipping all six would put ~32 MB in front of every `npx` cold start to
 * deliver 1.4 MB of used content (plan risk #4). Add a name here when the
 * adapter that consumes it lands — the size tripwire below will flag the cost.
 */
const SHIPPED_BUNDLES = ['antigravity-plugin', 'antigravity-plugin-extras'];

/**
 * Bundles whose version is NOT the core pool version. `caddis-extras` ships and
 * versions independently (1.3.13 while core is 1.3.39), so the staleness warning
 * below must not compare it against the pool manifest.
 */
const INDEPENDENTLY_VERSIONED = new Set(['antigravity-plugin-extras']);

/** Warn if the packed bundles grow past this. Plan risk #4 tripwire. */
const SIZE_WARN_BYTES = 5 * 1024 * 1024;

const check = process.argv.includes('--check');

async function dirSize(dir) {
  let total = 0;
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) total += await dirSize(full);
    else total += (await stat(full)).size;
  }
  return total;
}

async function readJson(file) {
  try {
    return JSON.parse(await readFile(file, 'utf8'));
  } catch {
    return null;
  }
}

/** The pool version of record: the caddis plugin version in runtime-targets.json. */
async function poolVersionFromManifest() {
  const manifest = await readJson(path.join(SOURCE_ROOT, '.github', 'runtime-targets.json'));
  if (!manifest?.targets) return null;
  for (const target of manifest.targets) {
    const plugin = target?.plugin_manifest ?? target?.manifest ?? null;
    if (plugin?.name === 'caddis' && plugin?.version) return plugin.version;
  }
  // The manifest nests the generated plugin.json under varying keys across
  // targets; fall back to the first `caddis` + version pair anywhere in it.
  const found = JSON.stringify(manifest).match(/"name"\s*:\s*"caddis"\s*,\s*"version"\s*:\s*"([^"]+)"/);
  return found?.[1] ?? null;
}

function fail(message) {
  console.error(`[copy-bundles] ERROR ${message}`);
  process.exit(1);
}

const sourceRoot = BUNDLE_SOURCES.find((candidate) =>
  SHIPPED_BUNDLES.every((name) => existsSync(path.join(candidate, name, 'plugin.json'))),
);

if (!sourceRoot) {
  fail(
    `no exported bundles found. Looked for ${SHIPPED_BUNDLES.join(', ')} in:\n` +
      BUNDLE_SOURCES.map((p) => `    ${p}`).join('\n') +
      `\n  Run: python export_runtime_resources.py --profile ${SHIPPED_BUNDLES.join(' --profile ')}`,
  );
}

console.log(`[copy-bundles] source: ${sourceRoot}`);

const destRoot = path.join(CLI_ROOT, 'bundles');
const versions = {};

if (!check) await rm(destRoot, { recursive: true, force: true });
if (!check) await mkdir(destRoot, { recursive: true });

let totalBytes = 0;
for (const name of SHIPPED_BUNDLES) {
  const src = path.join(sourceRoot, name);
  const dest = path.join(destRoot, name);
  if (!check) await cp(src, dest, { recursive: true });
  const manifest = await readJson(path.join(src, 'plugin.json'));
  versions[name] = manifest?.version ?? 'unknown';
  const bytes = await dirSize(src);
  totalBytes += bytes;
  console.log(`[copy-bundles] ${check ? 'check' : 'copy '} ${name} @ ${versions[name]} (${(bytes / 1024 / 1024).toFixed(2)} MB)`);
}

const poolVersion = (await poolVersionFromManifest()) ?? versions[SHIPPED_BUNDLES[0]] ?? 'unknown';

for (const [name, version] of Object.entries(versions)) {
  if (INDEPENDENTLY_VERSIONED.has(name)) continue;
  if (version !== poolVersion) {
    console.warn(
      `[copy-bundles] WARN bundle ${name} is ${version} but the pool manifest says ${poolVersion}.\n` +
        `                    The exported bundles are stale — re-run the export / caddis-push before publishing.`,
    );
  }
}

if (totalBytes > SIZE_WARN_BYTES) {
  console.warn(
    `[copy-bundles] WARN shipped bundles total ${(totalBytes / 1024 / 1024).toFixed(1)} MB (> ${SIZE_WARN_BYTES / 1024 / 1024} MB).\n` +
      `                    npx cold start suffers past this. Consider on-demand fetch (plan risk #4).`,
  );
}

if (!check) {
  await writeFile(
    path.join(destRoot, 'manifest.json'),
    `${JSON.stringify({ poolVersion, bundles: versions }, null, 2)}\n`,
    'utf8',
  );
  console.log(`[copy-bundles] wrote bundles/manifest.json (poolVersion ${poolVersion})`);
}
