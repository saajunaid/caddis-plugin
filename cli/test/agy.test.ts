import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterAll, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../src/util/which.js', () => ({ findBin: vi.fn() }));
vi.mock('../src/util/exec.js', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/util/exec.js')>();
  return { ...actual, run: vi.fn() };
});
vi.mock('../src/util/pkg.js', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/util/pkg.js')>();
  return { ...actual, bundlePath: vi.fn() };
});

import { agyAdapter, pluginManifestPath, readInstalledVersion, statusFromHome } from '../src/agents/agy.js';
import { run } from '../src/util/exec.js';
import { findBin } from '../src/util/which.js';
import { bundlePath } from '../src/util/pkg.js';
import type { RunResult } from '../src/util/exec.js';

const mockRun = vi.mocked(run);
const mockWhich = vi.mocked(findBin);
const mockBundlePath = vi.mocked(bundlePath);

const ok = (stdout = ''): RunResult => ({ ok: true, code: 0, stdout, stderr: '' });
const fail = (stderr = 'boom'): RunResult => ({ ok: false, code: 1, stdout: '', stderr });

const scratch = mkdtempSync(path.join(tmpdir(), 'caddis-agy-'));
afterAll(() => rmSync(scratch, { recursive: true, force: true }));

beforeEach(() => {
  mockRun.mockReset();
  mockWhich.mockReset();
  mockBundlePath.mockReset();
  mockBundlePath.mockReturnValue('/pkg/bundles/antigravity-plugin');
});

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
    const result = await agyAdapter.drive('update', { dryRun: false });
    expect(result.ok).toBe(true);
    expect(result.steps[0]?.command).toBe('agy plugin install /pkg/bundles/antigravity-plugin');
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
    const result = await agyAdapter.drive('update', { dryRun: false });
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
