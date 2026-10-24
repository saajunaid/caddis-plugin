import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { readManifest, stageMirror } from '../../scripts/stage-mirror.mjs';

const cliRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
// Top-level cli/ entries that caddis-push does NOT send to the mirror, and why.
const NOT_SYNCED = new Set([
  '.github', // sync.ps1 installs the workflows at the mirror root, separately
  'dist', // build output; the mirror builds its own
  'bundles', // copied in at build time by copy-bundles.mjs
  'node_modules',
  'test-results',
  'playwright-report',
]);

let tmp: string;
beforeEach(() => {
  tmp = mkdtempSync(path.join(tmpdir(), 'caddis-hub-mirror-'));
});
afterEach(() => rmSync(tmp, { recursive: true, force: true }));

describe('sync-manifest.json (the mirror file set)', () => {
  it('lists every top-level cli/ entry that is not on the not-synced list', () => {
    const { dirs, files } = readManifest();
    const listed = new Set([...dirs, ...files]);
    const missing = readdirSync(cliRoot).filter((n) => !listed.has(n) && !NOT_SYNCED.has(n) && !n.endsWith('.tsbuildinfo'));
    expect(missing, 'add these to cli/sync-manifest.json or to NOT_SYNCED').toEqual([]);
  });

  it('lists the UI build inputs', () => {
    const { dirs, files } = readManifest();
    expect(dirs).toEqual(expect.arrayContaining(['src', 'test', 'scripts', 'ui', 'e2e']));
    expect(files).toEqual(expect.arrayContaining(['playwright.config.ts', 'sync-manifest.json', 'package-lock.json']));
  });

  it('is read by sync.ps1 (when the source checkout has it)', () => {
    const sync = path.resolve(cliRoot, '..', 'sync.ps1');
    if (!existsSync(sync)) return;
    expect(readFileSync(sync, 'utf8')).toContain('sync-manifest.json');
  });
});

describe('stageMirror', () => {
  it('copies the manifest set and skips build output', () => {
    stageMirror(tmp);
    for (const f of ['package.json', 'sync-manifest.json', 'ui/tsconfig.json', 'ui/fonts-src/fonts.css', 'e2e/hub.spec.ts']) {
      expect(existsSync(path.join(tmp, f)), f).toBe(true);
    }
    expect(existsSync(path.join(tmp, 'node_modules'))).toBe(false);
    expect(existsSync(path.join(tmp, 'dist'))).toBe(false);
    expect(existsSync(path.join(tmp, '.github'))).toBe(false);
  }, 30_000);
});
