import { mkdtempSync, mkdirSync, writeFileSync, rmSync, existsSync, readFileSync, renameSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterAll, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../src/util/which.js', () => ({ findBin: vi.fn() }));
vi.mock('../src/util/agyProcs.js', () => ({ listAgyPids: vi.fn(async () => [] as number[]) }));
vi.mock('../src/util/exec.js', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/util/exec.js')>();
  return { ...actual, run: vi.fn() };
});
vi.mock('../src/util/pkg.js', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/util/pkg.js')>();
  return { ...actual, bundlePath: vi.fn() };
});

import {
  agyAdapter,
  agyStagingDir,
  recoverInterruptedSwap,
  runningAgyMessage,
  extrasStatusFromHome,
  pluginManifestPath,
  readInstalledVersion,
  stageAndSwap,
  statusFromHome,
} from '../src/agents/agy.js';
import { run } from '../src/util/exec.js';
import { findBin } from '../src/util/which.js';
import { listAgyPids } from '../src/util/agyProcs.js';
import { bundlePath } from '../src/util/pkg.js';
import type { RunResult } from '../src/util/exec.js';

const mockRun = vi.mocked(run);
const mockWhich = vi.mocked(findBin);
const mockBundlePath = vi.mocked(bundlePath);
const mockAgyPids = vi.mocked(listAgyPids);

const ok = (stdout = ''): RunResult => ({ ok: true, code: 0, stdout, stderr: '' });
const fail = (stderr = 'boom'): RunResult => ({ ok: false, code: 1, stdout: '', stderr });

const scratch = mkdtempSync(path.join(tmpdir(), 'caddis-agy-'));
afterAll(() => rmSync(scratch, { recursive: true, force: true }));

beforeEach(() => {
  mockRun.mockReset();
  mockWhich.mockReset();
  mockBundlePath.mockReset();
  mockAgyPids.mockReset();
  mockAgyPids.mockResolvedValue([]);
  delete process.env.CADDIS_AGY_ALLOW_RUNNING;
  mockBundlePath.mockImplementation((name: string) => `/pkg/bundles/${name}`);
});

/** Build a fake agy home with the given plugins installed. */
function agyHome(label: string, plugins: Record<string, string | null>): string {
  const home = path.join(scratch, label);
  for (const [plugin, version] of Object.entries(plugins)) {
    mkdirSync(path.join(home, '.gemini', 'config', 'plugins', plugin), { recursive: true });
    writeFileSync(pluginManifestPath(home, plugin), version === null ? '{ broken' : JSON.stringify({ name: plugin, version }));
  }
  return home;
}

const PLUGIN_FILES = ['plugin.json', 'hooks.json', 'guard_agy.py'];

/** A fake agy home whose caddis plugin holds the three files an install must leave behind. */
function completeHome(label: string): string {
  const home = path.join(scratch, label);
  const dir = path.join(home, '.gemini', 'config', 'plugins', 'caddis');
  mkdirSync(dir, { recursive: true });
  for (const file of PLUGIN_FILES) writeFileSync(path.join(dir, file), `old ${file}`);
  return home;
}
const pluginDir = (home: string) => path.join(home, '.gemini', 'config', 'plugins', 'caddis');

describe('pluginManifestPath', () => {
  it('points at agy\'s own plugin manifest under the home dir', () => {
    expect(pluginManifestPath('/home/u')).toBe(path.join('/home/u', '.gemini', 'config', 'plugins', 'caddis', 'plugin.json'));
  });
});

describe('readInstalledVersion', () => {
  it('reads the version from a real manifest shape', () => {
    const file = path.join(scratch, 'plugin.json');
    writeFileSync(file, JSON.stringify({ name: 'caddis', version: '1.3.38', description: 'x' }));
    expect(readInstalledVersion(file)).toBe('1.3.38');
  });

  it('returns null for a missing file', () => {
    expect(readInstalledVersion(path.join(scratch, 'nope.json'))).toBeNull();
  });

  it('returns null for corrupt JSON instead of throwing', () => {
    const file = path.join(scratch, 'bad.json');
    writeFileSync(file, '{ not json');
    expect(readInstalledVersion(file)).toBeNull();
  });

  it('returns null when the manifest has no version', () => {
    const file = path.join(scratch, 'noversion.json');
    writeFileSync(file, JSON.stringify({ name: 'caddis' }));
    expect(readInstalledVersion(file)).toBeNull();
  });
});

describe('agy adapter detect', () => {
  it('reports absent without the binary', async () => {
    mockWhich.mockResolvedValue(null);
    expect((await agyAdapter.detect()).present).toBe(false);
  });

  it('reports present with the agent version', async () => {
    mockWhich.mockResolvedValue('C:\\agy\\agy.EXE');
    mockRun.mockResolvedValue(ok('agy 1.1.7'));
    expect(await agyAdapter.detect()).toMatchObject({ present: true, agentVersion: '1.1.7' });
  });
});

describe('agy adapter drive', () => {
  it('installs from the bundle shipped in the package', async () => {
    mockWhich.mockResolvedValue('/bin/agy');
    mockRun.mockResolvedValueOnce(ok('1.1.7')).mockResolvedValueOnce(ok());
    const result = await agyAdapter.drive('update', { dryRun: false, home: completeHome('h1') });
    expect(result.ok).toBe(true);
    expect(result.steps[0]?.command).toBe('agy plugin install /pkg/bundles/antigravity-plugin');
  });

  it('stages the bundle outside any @-scoped path before calling agy (regression: agy misparses "@" as a marketplace qualifier)', async () => {
    // Reproduces the real npx layout: node_modules/@caddis/cli/bundles/... -- agy's own
    // `plugin install <path>` splits on the first "@" and treats the remainder as a
    // marketplace name, failing with "unknown marketplace: caddis\cli\bundles\...".
    const scoped = path.join(scratch, 'node_modules', '@caddis', 'cli', 'bundles', 'antigravity-plugin');
    mkdirSync(scoped, { recursive: true });
    writeFileSync(path.join(scoped, 'plugin.json'), JSON.stringify({ name: 'caddis', version: '1.3.47' }));
    mockBundlePath.mockImplementation(() => scoped);
    mockWhich.mockResolvedValue('/bin/agy');
    mockRun.mockResolvedValueOnce(ok('1.1.7')).mockResolvedValueOnce(ok());

    const result = await agyAdapter.drive('update', { dryRun: false, home: completeHome('h2') });

    expect(result.ok).toBe(true);
    const installCall = mockRun.mock.calls[1];
    const executedPath = installCall?.[1]?.[2];
    expect(executedPath).toBeDefined();
    expect(executedPath).not.toContain('@');
    // The reported command still shows the real, meaningful bundle path, not the
    // throwaway staged copy -- a user reading the log should see intent, not plumbing.
    expect(result.steps[0]?.command).toBe(`agy plugin install ${scoped}`);
  });

  it('does not stage (no-op) when the bundle path has no "@" -- the common npm-link/dev case', async () => {
    mockWhich.mockResolvedValue('/bin/agy');
    mockRun.mockResolvedValueOnce(ok('1.1.7')).mockResolvedValueOnce(ok());
    const result = await agyAdapter.drive('update', { dryRun: false, home: completeHome('h3') });
    const installCall = mockRun.mock.calls[1];
    expect(installCall?.[1]?.[2]).toBe('/pkg/bundles/antigravity-plugin');
    expect(result.ok).toBe(true);
  });

  it('drives the same command for install and update (agy install is idempotent)', async () => {
    mockWhich.mockResolvedValue('/bin/agy');
    mockRun.mockResolvedValue(ok('1.1.7'));
    const installed = await agyAdapter.drive('install', { dryRun: true });
    const updated = await agyAdapter.drive('update', { dryRun: true });
    expect(installed.steps[0]?.command).toBe(updated.steps[0]?.command);
  });

  it('skips when agy is absent', async () => {
    mockWhich.mockResolvedValue(null);
    expect(await agyAdapter.drive('update', { dryRun: false })).toMatchObject({ ok: true, skipped: true });
  });

  it('fails with a fixable message when the bundle was not packed', async () => {
    mockWhich.mockResolvedValue('/bin/agy');
    mockRun.mockResolvedValue(ok('1.1.7'));
    mockBundlePath.mockReturnValue(null);
    const result = await agyAdapter.drive('update', { dryRun: false });
    expect(result.ok).toBe(false);
    expect(result.message).toMatch(/missing from this package/);
  });

  it('--dry-run executes nothing', async () => {
    mockWhich.mockResolvedValue('/bin/agy');
    mockRun.mockResolvedValue(ok('1.1.7'));
    const result = await agyAdapter.drive('update', { dryRun: true });
    expect(result.skipped).toBe(true);
    expect(mockRun.mock.calls.every(([, args]) => args[0] === '--version')).toBe(true);
  });

  it('surfaces an install failure without throwing', async () => {
    mockWhich.mockResolvedValue('/bin/agy');
    mockRun.mockResolvedValueOnce(ok('1.1.7')).mockResolvedValueOnce(fail('plugin validation failed'));
    const result = await agyAdapter.drive('update', { dryRun: false, home: completeHome('h4') });
    expect(result.ok).toBe(false);
    expect(result.steps[0]?.output).toContain('plugin validation failed');
  });
});

describe('agy adapter status', () => {
  it('reads the version from agy\'s manifest on disk', async () => {
    const home = path.join(scratch, 'home');
    mkdirSync(path.join(home, '.gemini', 'config', 'plugins', 'caddis'), { recursive: true });
    writeFileSync(pluginManifestPath(home), JSON.stringify({ name: 'caddis', version: '1.3.39' }));

    expect(statusFromHome(home)).toMatchObject({ installed: true, version: '1.3.39' });
  });

  it('is not-installed when agy has never imported caddis', async () => {
    expect(statusFromHome(path.join(scratch, 'empty-home'))).toMatchObject({ installed: false });
  });

  it('flags a present-but-broken manifest as installed with a note', async () => {
    const home = path.join(scratch, 'broken-home');
    mkdirSync(path.join(home, '.gemini', 'config', 'plugins', 'caddis'), { recursive: true });
    writeFileSync(pluginManifestPath(home), '{ truncated');
    const status = statusFromHome(home);
    expect(status.installed).toBe(true);
    expect(status.version).toBeUndefined();
    expect(status.note).toMatch(/unreadable/);
  });

  it('short-circuits to not-installed when agy itself is absent', async () => {
    mockWhich.mockResolvedValue(null);
    expect(await agyAdapter.status()).toMatchObject({ installed: false, note: 'agent not installed' });
  });
});


describe('agy extras (caddis-extras)', () => {
  it('reports extras as not-installed when absent — the normal opt-in state', () => {
    const home = agyHome('extras-none', { caddis: '1.3.39' });
    expect(statusFromHome(home).extras).toEqual({ installed: false });
  });

  it('reads the extras version from its OWN manifest, not the core one', () => {
    // extras versions independently: 1.3.13 while core is 1.3.39. Reading core's
    // version for extras would report it as current when it is 26 patches behind.
    const home = agyHome('extras-both', { caddis: '1.3.39', 'caddis-extras': '1.3.13' });
    const status = statusFromHome(home);
    expect(status.version).toBe('1.3.39');
    expect(status.extras).toMatchObject({ installed: true, version: '1.3.13' });
  });

  it('handles extras installed without core', () => {
    const home = agyHome('extras-only', { 'caddis-extras': '1.3.13' });
    const status = statusFromHome(home);
    expect(status.installed).toBe(false);
    expect(status.extras?.installed).toBe(true);
  });

  it('treats a corrupt extras manifest as installed-but-versionless', () => {
    const home = agyHome('extras-broken', { caddis: '1.3.39', 'caddis-extras': null });
    const extras = extrasStatusFromHome(home);
    expect(extras.installed).toBe(true);
    expect(extras.version).toBeUndefined();
  });

  it('does NOT install extras by default', async () => {
    mockWhich.mockResolvedValue('/bin/agy');
    mockRun.mockResolvedValue(ok('1.1.7'));
    const result = await agyAdapter.drive('install', { dryRun: true });
    expect(result.steps).toHaveLength(1);
    expect(result.steps[0]?.command).toContain('antigravity-plugin');
    expect(result.steps[0]?.command).not.toContain('extras');
  });

  it('installs extras when --extras is passed', async () => {
    mockWhich.mockResolvedValue('/bin/agy');
    mockRun.mockResolvedValue(ok('1.1.7'));
    const result = await agyAdapter.drive('install', { dryRun: true, extras: true });
    expect(result.steps).toHaveLength(2);
    expect(result.steps[1]?.command).toBe('agy plugin install /pkg/bundles/antigravity-plugin-extras');
  });

  it('installs core BEFORE extras', async () => {
    mockWhich.mockResolvedValue('/bin/agy');
    mockRun.mockResolvedValue(ok('1.1.7'));
    const result = await agyAdapter.drive('install', { dryRun: true, extras: true });
    expect(result.steps[0]?.command).toContain('/antigravity-plugin');
    expect(result.steps[0]?.command).not.toContain('extras');
  });

  it('does not attempt extras when core install fails', async () => {
    mockWhich.mockResolvedValue('/bin/agy');
    mockRun
      .mockResolvedValueOnce(ok('1.1.7')) // detect
      .mockResolvedValueOnce(fail('core exploded'));
    const result = await agyAdapter.drive('update', { dryRun: false, extras: true, home: completeHome('h5') });
    expect(result.ok).toBe(false);
    expect(result.steps).toHaveLength(1);
  });

  it('fails with a clear message when --extras is asked for but the bundle was not packed', async () => {
    mockWhich.mockResolvedValue('/bin/agy');
    mockRun.mockResolvedValue(ok('1.1.7'));
    mockBundlePath.mockImplementation((name: string) =>
      name === 'antigravity-plugin-extras' ? null : `/pkg/bundles/${name}`,
    );
    const result = await agyAdapter.drive('update', { dryRun: false, extras: true });
    expect(result.ok).toBe(false);
    expect(result.message).toMatch(/--extras requested but the antigravity-plugin-extras bundle is missing/);
  });
});


describe('agy adapter drive: the release must not empty the plugin under a running agy', () => {
  const agyUp = () => {
    mockWhich.mockResolvedValue('/bin/agy');
  };

  it('never runs `agy plugin install` while agy.exe runs, and names the PIDs when it cannot swap', async () => {
    agyUp();
    mockRun.mockResolvedValue(ok('1.1.7'));
    mockAgyPids.mockResolvedValue([31160, 3572]);
    // The bundle path does not exist here, so the stage fails and nothing can be swapped.
    const result = await agyAdapter.drive('update', { dryRun: false, home: completeHome('r1') });
    expect(result.ok).toBe(false);
    expect(result.steps).toHaveLength(1);
    expect(result.steps[0]!.ok).toBe(false);
    expect(result.message).toMatch(/agy is running/);
    expect(result.message).toContain('31160');
    expect(result.message).toContain('3572');
    // Staging failed: say so, never "staged at", and never suggest the override (it would not help).
    expect(result.message).toMatch(/staging failed/);
    expect(result.message).not.toMatch(/staged at/);
    expect(result.message).not.toContain('CADDIS_AGY_ALLOW_RUNNING');
    expect(mockRun).toHaveBeenCalled(); // the version probe ran, so "every call" is not vacuous
    expect(mockRun.mock.calls.every(([, args]) => args[0] === '--version')).toBe(true);
  });

  it('lets a --dry-run through while agy runs, because it changes nothing', async () => {
    agyUp();
    mockRun.mockResolvedValue(ok('1.1.7'));
    mockAgyPids.mockResolvedValue([31160]);
    const result = await agyAdapter.drive('update', { dryRun: true, home: completeHome('r2') });
    expect(result.ok).toBe(true);
    expect(result.skipped).toBe(true);
  });

  it('installs while agy runs only when CADDIS_AGY_ALLOW_RUNNING=1 is set', async () => {
    agyUp();
    mockAgyPids.mockResolvedValue([31160]);
    process.env.CADDIS_AGY_ALLOW_RUNNING = '1';
    mockRun.mockResolvedValueOnce(ok('1.1.7')).mockResolvedValueOnce(ok());
    const result = await agyAdapter.drive('update', { dryRun: false, home: completeHome('r3') });
    expect(result.ok).toBe(true);
  });

  it('restores the old plugin when the install leaves it empty, and says so', async () => {
    agyUp();
    const home = completeHome('r4');
    mockRun.mockResolvedValueOnce(ok('1.1.7')).mockImplementationOnce(async () => {
      // What the 2026-10-08 release did: the delete went through and the copy did not.
      rmSync(pluginDir(home), { recursive: true, force: true });
      mkdirSync(pluginDir(home), { recursive: true });
      return ok();
    });
    const result = await agyAdapter.drive('update', { dryRun: false, home });
    expect(result.ok).toBe(false);
    expect(result.message).toMatch(/incomplete after the install/);
    expect(result.message).toMatch(/restored/);
    for (const file of PLUGIN_FILES) {
      expect(readFileSync(path.join(pluginDir(home), file), 'utf8')).toBe(`old ${file}`);
    }
  });

  it('restores the old plugin when the install command fails and leaves it broken', async () => {
    agyUp();
    const home = completeHome('r5');
    mockRun.mockResolvedValueOnce(ok('1.1.7')).mockImplementationOnce(async () => {
      rmSync(path.join(pluginDir(home), 'guard_agy.py'));
      return fail('copy failed');
    });
    const result = await agyAdapter.drive('update', { dryRun: false, home });
    expect(result.ok).toBe(false);
    expect(existsSync(path.join(pluginDir(home), 'guard_agy.py'))).toBe(true);
    expect(result.message).toMatch(/restored/);
  });

  it('accepts a fresh machine whose install creates the three files', async () => {
    agyUp();
    const home = path.join(scratch, 'r6');
    mockRun.mockResolvedValueOnce(ok('1.1.7')).mockImplementationOnce(async () => {
      mkdirSync(pluginDir(home), { recursive: true });
      for (const file of PLUGIN_FILES) writeFileSync(path.join(pluginDir(home), file), 'new');
      return ok();
    });
    const result = await agyAdapter.drive('install', { dryRun: false, home });
    expect(result.ok).toBe(true);
  });

  it('fails clearly on a fresh machine when the install leaves nothing to restore', async () => {
    agyUp();
    const home = path.join(scratch, 'r7');
    mockRun.mockResolvedValueOnce(ok('1.1.7')).mockResolvedValueOnce(ok());
    const result = await agyAdapter.drive('install', { dryRun: false, home });
    expect(result.ok).toBe(false);
    expect(result.message).toMatch(/incomplete after the install/);
    expect(result.message).toMatch(/nothing to restore/);
  });
});


/** A real bundle folder on disk, holding the three files a whole plugin needs. */
function bundleDir(label: string, version: string, files: readonly string[] = PLUGIN_FILES): string {
  const dir = path.join(scratch, 'bundles', label, 'antigravity-plugin');
  mkdirSync(dir, { recursive: true });
  for (const file of files) writeFileSync(path.join(dir, file), `${version} ${file}`);
  return dir;
}

describe('agy refresh under a running agy: stage, then swap by rename (robustness audit #18)', () => {
  const agyUp = () => mockWhich.mockResolvedValue('/bin/agy');

  it('swaps the new plugin in by rename when nothing holds the files, and runs no agy install', async () => {
    agyUp();
    const home = completeHome('s1');
    const bundle = bundleDir('s1', 'new');
    mockBundlePath.mockImplementation((name: string) => (name === 'antigravity-plugin' ? bundle : null));
    mockRun.mockResolvedValue(ok('1.1.7'));
    mockAgyPids.mockResolvedValue([4242]);
    const result = await agyAdapter.drive('update', { dryRun: false, home });
    expect(result.ok).toBe(true);
    expect(result.message).toMatch(/swapped/);
    for (const file of PLUGIN_FILES) {
      expect(readFileSync(path.join(pluginDir(home), file), 'utf8')).toBe(`new ${file}`);
    }
    expect(existsSync(agyStagingDir(home, 'caddis'))).toBe(false);
    expect(mockRun.mock.calls.every(([, args]) => args[0] === '--version')).toBe(true);
  });

  it('keeps the new version staged and the old plugin whole when agy holds the files', async () => {
    const home = completeHome('s2');
    const bundle = bundleDir('s2', 'new');
    const busy = Object.assign(new Error('resource busy or locked'), { code: 'EBUSY' });
    const outcome = stageAndSwap(bundle, home, 'caddis', PLUGIN_FILES, () => {
      throw busy;
    });
    expect(outcome.swapped).toBe(false);
    expect(outcome.reason).toBe('in-use');
    expect(outcome.detail).toBe('could not move the live plugin aside (EBUSY: resource busy or locked); agy may be using it');
    expect(outcome.staged).toBe(agyStagingDir(home, 'caddis'));
    for (const file of PLUGIN_FILES) {
      expect(readFileSync(path.join(pluginDir(home), file), 'utf8')).toBe(`old ${file}`);
      expect(readFileSync(path.join(outcome.staged!, file), 'utf8')).toBe(`new ${file}`);
    }
    const message = runningAgyMessage('PID 7', 'caddis', outcome);
    expect(message).toContain(`staged at ${outcome.staged}`);
    expect(message).not.toContain('CADDIS_AGY_ALLOW_RUNNING');
  });

  it('puts the old plugin back when the second rename fails', async () => {
    const home = completeHome('s3');
    const bundle = bundleDir('s3', 'new');
    let calls = 0;
    const outcome = stageAndSwap(bundle, home, 'caddis', PLUGIN_FILES, (from, to) => {
      calls += 1;
      if (calls === 2) throw Object.assign(new Error('denied'), { code: 'EPERM' });
      renameSync(from, to);
    });
    expect(outcome.swapped).toBe(false);
    expect(outcome.detail).toMatch(/the old plugin is back/);
    for (const file of PLUGIN_FILES) {
      expect(readFileSync(path.join(pluginDir(home), file), 'utf8')).toBe(`old ${file}`);
    }
  });

  it('rejects an incomplete stage BEFORE it touches the live plugin, and keeps the stage for inspection', async () => {
    const home = completeHome('s4');
    const bundle = bundleDir('s4', 'new', ['plugin.json']);
    let renames = 0;
    const outcome = stageAndSwap(bundle, home, 'caddis', PLUGIN_FILES, () => {
      renames += 1;
    });
    expect(renames).toBe(0);
    expect(outcome.swapped).toBe(false);
    expect(outcome.reason).toBe('stage-rejected');
    expect(outcome.staged).toBeNull();
    expect(outcome.detail).toMatch(/hooks.json/);
    expect(outcome.kept).toBe(agyStagingDir(home, 'caddis'));
    expect(existsSync(path.join(agyStagingDir(home, 'caddis'), 'plugin.json'))).toBe(true);
    for (const file of PLUGIN_FILES) {
      expect(readFileSync(path.join(pluginDir(home), file), 'utf8')).toBe(`old ${file}`);
    }
    expect(runningAgyMessage('PID 7', 'caddis', outcome)).not.toMatch(/staged at/);
  });

  it('reports a failed stage with no staged path', async () => {
    const home = completeHome('s8');
    const outcome = stageAndSwap(path.join(scratch, 'no-such-bundle'), home, 'caddis', PLUGIN_FILES);
    expect(outcome.swapped).toBe(false);
    expect(outcome.reason).toBe('stage-failed');
    expect(outcome.staged).toBeNull();
    expect(outcome.detail).toMatch(/^staging failed/);
  });

  it('only stages on a first install: agy itself must register the plugin', async () => {
    const home = path.join(scratch, 's5');
    const bundle = bundleDir('s5', 'new');
    const outcome = stageAndSwap(bundle, home, 'caddis', PLUGIN_FILES);
    expect(outcome.swapped).toBe(false);
    expect(outcome.detail).toMatch(/agy plugin install/);
    expect(existsSync(pluginDir(home))).toBe(false);
    expect(existsSync(path.join(agyStagingDir(home, 'caddis'), 'plugin.json'))).toBe(true);
  });

  it('says where the stage is and what to do when the swap fails under a running agy', async () => {
    agyUp();
    const home = path.join(scratch, 's6'); // first install: stage only
    const bundle = bundleDir('s6', 'new');
    mockBundlePath.mockImplementation((name: string) => (name === 'antigravity-plugin' ? bundle : null));
    mockRun.mockResolvedValue(ok('1.1.7'));
    mockAgyPids.mockResolvedValue([4242]);
    const result = await agyAdapter.drive('update', { dryRun: false, home });
    expect(result.ok).toBe(false);
    expect(result.message).toContain('4242');
    expect(result.message).toContain(agyStagingDir(home, 'caddis'));
    expect(result.message).toMatch(/caddis update/);
  });

  /** An old copy beside the stage, as a swap leaves it: `<stage>.old-<stamp>` with the given files. */
  function oldCopy(home: string, stamp: number, files: readonly string[] = PLUGIN_FILES, label = 'old'): string {
    const dir = `${agyStagingDir(home, 'caddis')}.old-${stamp}`;
    mkdirSync(dir, { recursive: true });
    for (const file of files) writeFileSync(path.join(dir, file), `${label} ${file}`);
    return dir;
  }

  it('(a) restores the old copy when the live plugin is missing, instead of sweeping it', () => {
    const home = path.join(scratch, 'rc-a');
    const older = oldCopy(home, 1000, PLUGIN_FILES, 'older');
    const newest = oldCopy(home, 2000, PLUGIN_FILES, 'newest');
    const broken = oldCopy(home, 3000, ['plugin.json'], 'broken'); // newest stamp, but not whole
    const note = recoverInterruptedSwap(home, 'caddis', PLUGIN_FILES);
    expect(note).toBe(`restored the previous plugin from ${newest}`);
    for (const file of PLUGIN_FILES) {
      expect(readFileSync(path.join(pluginDir(home), file), 'utf8')).toBe(`newest ${file}`);
    }
    expect(existsSync(older)).toBe(true); // nothing is swept while recovering
    expect(existsSync(broken)).toBe(true);
  });

  it('(b) sweeps old copies only when the live plugin is whole', () => {
    const home = completeHome('rc-b');
    const leftover = oldCopy(home, 1000);
    expect(recoverInterruptedSwap(home, 'caddis', PLUGIN_FILES)).toBeNull();
    expect(existsSync(leftover)).toBe(false);
  });

  it('(c) a refresh after a failed rollback restores the old plugin first, then refreshes it', async () => {
    agyUp();
    const home = completeHome('rc-c');
    const bundle = bundleDir('rc-c', 'new');
    // The rollback-failed state: the second rename and the rename back both failed.
    let calls = 0;
    const first = stageAndSwap(bundle, home, 'caddis', PLUGIN_FILES, (from, to) => {
      calls += 1;
      if (calls >= 2) throw Object.assign(new Error('denied'), { code: 'EPERM' });
      renameSync(from, to);
    });
    expect(first.detail).toMatch(/putting the old plugin back FAILED/);
    expect(existsSync(pluginDir(home))).toBe(false);
    // Next refresh, agy running: recover the old copy, then swap the new one in.
    mockBundlePath.mockImplementation((name: string) => (name === 'antigravity-plugin' ? bundle : null));
    mockRun.mockResolvedValue(ok('1.1.7'));
    mockAgyPids.mockResolvedValue([4242]);
    const result = await agyAdapter.drive('update', { dryRun: false, home });
    expect(result.ok).toBe(true);
    expect(result.message).toMatch(/restored the previous plugin from/);
    for (const file of PLUGIN_FILES) {
      expect(readFileSync(path.join(pluginDir(home), file), 'utf8')).toBe(`new ${file}`);
    }
  });

  it('names where a rejected copy is kept, not "Nothing is staged"', () => {
    const outcome = { swapped: false, reason: 'stage-rejected' as const, staged: null, detail: 'x', kept: '/k/caddis' };
    const message = runningAgyMessage('PID 7', 'caddis', outcome);
    expect(message).toContain('the rejected copy is kept at /k/caddis');
    expect(message).not.toContain('Nothing is staged');
  });

  it('names the plugin that already swapped when a later one fails', async () => {
    agyUp();
    const home = completeHome('rc-e');
    const core = bundleDir('rc-e', 'new');
    mockBundlePath.mockImplementation((name: string) =>
      name === 'antigravity-plugin' ? core : name === 'antigravity-plugin-extras' ? path.join(scratch, 'missing-extras') : null,
    );
    mockRun.mockResolvedValue(ok('1.1.7'));
    mockAgyPids.mockResolvedValue([4242]);
    const result = await agyAdapter.drive('update', { dryRun: false, home, extras: true });
    expect(result.ok).toBe(false);
    expect(result.message).toMatch(/caddis-extras was not installed/);
    expect(result.message).toMatch(/caddis was already swapped in/);
  });

  it('sweeps leftover old copies at the start of a refresh', async () => {
    agyUp();
    const home = completeHome('s9');
    const leftover = oldCopy(home, 123);
    mockRun.mockResolvedValueOnce(ok('1.1.7')).mockResolvedValueOnce(ok());
    await agyAdapter.drive('update', { dryRun: false, home });
    expect(existsSync(leftover)).toBe(false);
  });

  it('clears an old stage after a normal install when agy is not running', async () => {
    agyUp();
    const home = completeHome('s7');
    mkdirSync(agyStagingDir(home, 'caddis'), { recursive: true });
    writeFileSync(path.join(agyStagingDir(home, 'caddis'), 'plugin.json'), 'stale stage');
    mockRun.mockResolvedValueOnce(ok('1.1.7')).mockResolvedValueOnce(ok());
    const result = await agyAdapter.drive('update', { dryRun: false, home });
    expect(result.ok).toBe(true);
    expect(existsSync(agyStagingDir(home, 'caddis'))).toBe(false);
  });
});
