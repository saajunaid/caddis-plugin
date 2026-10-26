/**
 * Where the tests find the repo's Python scripts (caddis_coordinate.py, caddis_hub_collect.py, ...).
 * Source repo: `<repo>/scripts`. Mirror (where npm publish runs): the bundled copy at
 * `<mirror root>/bundles/antigravity-plugin/scripts`. Before `npm run build` it sits beside cli/;
 * after the build it is also at cli/bundles/.
 */
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const CLI_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SOURCE_SCRIPTS = path.join(CLI_ROOT, '..', 'scripts');
const MARKER = 'caddis_coordinate.py';

/** True in the source repo, where a missing script must fail the run and never skip it. */
export const inSourceRepo = existsSync(path.join(SOURCE_SCRIPTS, MARKER));

/** The scripts folder, or null when neither the source folder nor a bundled copy exists. */
export function findScriptsDir(): string | null {
  const candidates = [
    SOURCE_SCRIPTS,
    path.join(CLI_ROOT, '..', 'bundles', 'antigravity-plugin', 'scripts'),
    path.join(CLI_ROOT, 'bundles', 'antigravity-plugin', 'scripts'),
  ];
  return candidates.find((dir) => existsSync(path.join(dir, MARKER))) ?? null;
}
