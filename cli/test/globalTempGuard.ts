/**
 * Vitest global setup: a test run must not leave a caddis folder behind in the temp folder (tidy v2 Phase 5).
 *
 * Setup snapshots the names directly in os.tmpdir(). Teardown lists the NEW names that start with a prefix below and
 * fails the run (exit code 1) with the list. Only the prefixes the cli tests make are checked: other programs also
 * write to the temp folder, so a rule of "nothing new" would fail by chance. The Python side keeps the same idea in
 * scripts/tests/temp_guard.py; test_temp_guard.py there checks that every prefix below is a prefix caddis_temp_prune.py
 * knows, so the prune command can clean what this guard misses.
 *
 * Set CADDIS_KEEP_TEMP=1 to skip the check (local debugging).
 */
import { readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';

export const WATCHED_PREFIXES = [
  'caddis-agy-',
  'caddis-codex-',
  'caddis-doctor-',
  'caddis-keys-',
  'caddis-sessions-',
  'caddis-stub-',
];

function names(root: string): Set<string> {
  try {
    return new Set(readdirSync(root));
  } catch {
    return new Set();
  }
}

export function newCaddisEntries(before: Set<string>, root: string): string[] {
  return [...names(root)].filter((n) => !before.has(n) && WATCHED_PREFIXES.some((p) => n.startsWith(p))).sort();
}

export default function setup(): (() => void) | void {
  const skip = process.env.CADDIS_KEEP_TEMP;
  if (skip !== undefined && skip !== '' && skip !== '0') return;
  const root = tmpdir();
  const before = names(root);
  return () => {
    const leaked = newCaddisEntries(before, root);
    if (leaked.length === 0) return;
    throw new Error(
      `TEMP LEAK: this test run left ${leaked.length} caddis folder(s) in ${root}:\n` +
        leaked.map((n) => `  ${n}`).join('\n') +
        '\nFix: remove the folder in an afterEach/afterAll (rmSync with recursive and force), or use a folder under ' +
        'a scratch that is removed. To keep them while debugging: CADDIS_KEEP_TEMP=1.',
    );
  };
}
