/**
 * Copy the cli/ file set that caddis-push sends to the mirror (sync-manifest.json) into <dest>.
 * CI then runs `npm ci`, `typecheck` and `build:ui` in <dest>, to prove the mirror's cli/ builds alone.
 * sync.ps1 reads the same manifest, so the two lists cannot drift.
 *
 * The real mirror also has bundles/ beside cli/. With `--bundles <dir>` the shipped bundles are copied from <dir>
 * (for example dist/runtime-resources) to <dest>/../bundles, so the tests find the bundled Python scripts.
 *
 * Usage: node scripts/stage-mirror.mjs <dest> [--bundles <dir>]
 */
import { cpSync, existsSync, mkdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const cliRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

/** Returns `{ dirs, files }` from sync-manifest.json. */
export function readManifest(root = cliRoot) {
  const m = JSON.parse(readFileSync(path.join(root, 'sync-manifest.json'), 'utf8'));
  if (!Array.isArray(m.dirs) || !Array.isArray(m.files)) throw new Error('sync-manifest.json needs "dirs" and "files" arrays');
  return { dirs: m.dirs, files: m.files };
}

/** Copies the manifest set from `root` to `dest`. Skips node_modules and build output inside the dirs. */
export function stageMirror(dest, root = cliRoot, bundlesFrom = null) {
  const { dirs, files } = readManifest(root);
  mkdirSync(dest, { recursive: true });
  const skip = new Set(['node_modules', 'dist', 'test-results', 'playwright-report']);
  for (const d of dirs) {
    const from = path.join(root, d);
    if (!existsSync(from)) continue;
    cpSync(from, path.join(dest, d), { recursive: true, filter: (p) => !skip.has(path.basename(p)) });
  }
  for (const f of files) {
    const from = path.join(root, f);
    if (existsSync(from)) cpSync(from, path.join(dest, f));
  }
  if (bundlesFrom) {
    for (const name of ['antigravity-plugin', 'antigravity-plugin-extras', 'codex']) {
      cpSync(path.join(bundlesFrom, name), path.join(dest, '..', 'bundles', name), { recursive: true });
    }
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const dest = process.argv[2];
  const at = process.argv.indexOf('--bundles');
  if (!dest || (at !== -1 && !process.argv[at + 1])) {
    console.error('usage: node scripts/stage-mirror.mjs <dest> [--bundles <dir>]');
    process.exit(2);
  }
  stageMirror(path.resolve(dest), cliRoot, at === -1 ? null : path.resolve(process.argv[at + 1]));
  console.log(`staged mirror cli/ into ${path.resolve(dest)}`);
}
