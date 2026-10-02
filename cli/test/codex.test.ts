/**
 * OpenAI Codex adapter tests.
 *
 * Codex 0.159.0+ has a native plugin marketplace:
 *   install = `codex plugin marketplace add https://github.com/saajunaid/caddis-plugin`
 *           + `codex plugin add caddis-codex@caddis`
 *   update  = `codex plugin marketplace upgrade caddis`
 *           + `codex plugin add caddis-codex@caddis`
 *   status  = parse `codex plugin list` for `caddis-codex@caddis`
 */
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os, { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../src/util/which.js', () => ({ findBin: vi.fn() }));
vi.mock('../src/util/exec.js', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/util/exec.js')>();
  return { ...actual, run: vi.fn() };
});

import {
  caddisSkillsDir,
  codexAdapter,
  parseCodexPluginList,
  versionFile,
} from '../src/agents/codex.js';
import { run } from '../src/util/exec.js';
import { findBin } from '../src/util/which.js';
import type { RunResult } from '../src/util/exec.js';

const mockRun = vi.mocked(run);
const mockWhich = vi.mocked(findBin);

function ok(stdout = ''): RunResult {
  return { ok: true, code: 0, stdout, stderr: '' };
}
function fail(stderr = 'boom', code = 1): RunResult {
  return { ok: false, code, stdout: '', stderr };
}

const scratches: string[] = [];
function tmpHome(): string {
  const dir = mkdtempSync(path.join(tmpdir(), 'caddis-codex-'));
  scratches.push(dir);
  return dir;
}

let currentHome = '';

beforeEach(() => {
  mockRun.mockReset();
  mockWhich.mockReset();
  currentHome = tmpHome();
  vi.spyOn(os, 'homedir').mockReturnValue(currentHome);
});

afterEach(() => {
  vi.restoreAllMocks();
  while (scratches.length) rmSync(scratches.pop()!, { recursive: true, force: true });
});

describe('install location', () => {
  it('namespaces everything under a single caddis/ directory', () => {
    const home = tmpHome();
    expect(caddisSkillsDir(home)).toBe(path.join(home, '.codex', 'skills', 'caddis'));
  });

  it('never installs flat into the user skills root', () => {
    const home = tmpHome();
    const dir = caddisSkillsDir(home);
    expect(dir).not.toBe(path.join(home, '.codex', 'skills'));
    expect(dir.startsWith(path.join(home, '.codex', 'skills'))).toBe(true);
  });
});

describe('parseCodexPluginList', () => {
  const SAMPLE_LIST = `
Marketplace \`caddis\`
C:\\Users\\user\\.codex\\.tmp\\marketplaces\\caddis\\.claude-plugin\\marketplace.json
caddis@caddis         not installed                C:\\Users\\user\\plugin
caddis-extras@caddis  not installed                C:\\Users\\user\\plugin-extras
caddis-codex@caddis   installed, enabled  1.3.125  C:\\Users\\user\\plugin-codex
`;

  it('reads the caddis-codex version from plugin list output', () => {
    expect(parseCodexPluginList(SAMPLE_LIST)).toEqual({
      installed: true,
      disabled: false,
      version: '1.3.125',
    });
  });

  it('detects disabled status', () => {
    const disabled = `caddis-codex@caddis   installed, disabled  1.3.124  /path`;
    expect(parseCodexPluginList(disabled)).toEqual({
      installed: true,
      disabled: true,
      version: '1.3.124',
    });
  });

  it('reports not installed when listed as not installed', () => {
    const notInstalled = `caddis-codex@caddis         not installed                /path`;
    expect(parseCodexPluginList(notInstalled)).toEqual({
      installed: false,
    });
  });

  it('returns null when absent from list', () => {
    expect(parseCodexPluginList('openai-templates@openai-curated-remote installed, enabled 0.1.1')).toBeNull();
  });
});

describe('codex adapter detect', () => {
  it('reports absent when binary is not on PATH', async () => {
    mockWhich.mockResolvedValue(null);
    const detected = await codexAdapter.detect();
    expect(detected.present).toBe(false);
  });

  it('reports present with agent version', async () => {
    mockWhich.mockResolvedValue('/usr/bin/codex');
    mockRun.mockResolvedValue(ok('codex-cli 0.159.0'));
    const detected = await codexAdapter.detect();
    expect(detected).toMatchObject({ present: true, path: '/usr/bin/codex', agentVersion: '0.159.0' });
  });

  it('stays present when --version fails', async () => {
    mockWhich.mockResolvedValue('/usr/bin/codex');
    mockRun.mockResolvedValue(fail());
    const detected = await codexAdapter.detect();
    expect(detected.present).toBe(true);
    expect(detected.agentVersion).toBeUndefined();
    expect(detected.note).toMatch(/--version` failed/);
  });
});

describe('codex status', () => {
  it('codex status reads codex plugin list', async () => {
    mockWhich.mockResolvedValue('/usr/bin/codex');
    const sampleOutput = `
PLUGIN               STATUS              VERSION   SOURCE
caddis-codex@caddis  installed, enabled  1.3.125   /home/user/plugins/caddis
`;
    mockRun
      .mockResolvedValueOnce(ok('0.159.0')) // detect
      .mockResolvedValueOnce(ok(sampleOutput)); // plugin list

    const status = await codexAdapter.status();
    expect(status).toMatchObject({
      installed: true,
      version: '1.3.125',
      disabled: false,
      source: '`codex plugin list`',
    });
  });

  it('reports not installed when plugin is absent', async () => {
    mockWhich.mockResolvedValue('/usr/bin/codex');
    mockRun
      .mockResolvedValueOnce(ok('0.159.0'))
      .mockResolvedValueOnce(ok('other-plugin installed, enabled 1.0.0'));
    const status = await codexAdapter.status();
    expect(status.installed).toBe(false);
    expect(status.note).toMatch(/not installed/);
  });

  it('degrades gracefully when plugin list fails', async () => {
    mockWhich.mockResolvedValue('/usr/bin/codex');
    mockRun
      .mockResolvedValueOnce(ok('0.159.0'))
      .mockResolvedValueOnce(fail('codex error', 1));
    const status = await codexAdapter.status();
    expect(status.installed).toBe(false);
    expect(status.note).toMatch(/could not read plugin list/);
  });
});

describe('codex drive', () => {
  it('skips cleanly when codex is absent', async () => {
    mockWhich.mockResolvedValue(null);
    const result = await codexAdapter.drive('install', { dryRun: false });
    expect(result).toMatchObject({ ok: true, skipped: true, steps: [] });
    expect(result.message).toMatch(/not installed/i);
  });

  it('codex install uses the plugin commands', async () => {
    mockWhich.mockResolvedValue('/usr/bin/codex');
    mockRun.mockResolvedValue(ok());

    const result = await codexAdapter.drive('install', { dryRun: false });
    expect(result.ok).toBe(true);
    const commands = result.steps.map((s) => s.command);
    expect(commands).toEqual([
      'codex plugin marketplace add https://github.com/saajunaid/caddis-plugin',
      'codex plugin add caddis-codex@caddis',
    ]);
  });

  it('codex update uses marketplace upgrade and plugin add', async () => {
    mockWhich.mockResolvedValue('/usr/bin/codex');
    mockRun.mockResolvedValue(ok());

    const result = await codexAdapter.drive('update', { dryRun: false });
    expect(result.ok).toBe(true);
    const commands = result.steps.map((s) => s.command);
    expect(commands).toEqual([
      'codex plugin marketplace upgrade caddis',
      'codex plugin add caddis-codex@caddis',
    ]);
  });

  it('--dry-run lists the commands and executes nothing', async () => {
    mockWhich.mockResolvedValue('/usr/bin/codex');
    mockRun.mockResolvedValue(ok('0.159.0'));

    const result = await codexAdapter.drive('install', { dryRun: true });
    expect(result.skipped).toBe(true);
    expect(result.steps).toHaveLength(2);
    expect(mockRun.mock.calls.every(([, args]) => args[0] === '--version')).toBe(true);
  });

  it('removes the old caddis skill copy only with its marker', async () => {
    mockWhich.mockResolvedValue('/usr/bin/codex');
    mockRun.mockResolvedValue(ok());

    const home = tmpHome();
    vi.spyOn(os, 'homedir').mockReturnValue(home);

    // Setup legacy install with marker
    mkdirSync(caddisSkillsDir(home), { recursive: true });
    writeFileSync(versionFile(home), '1.3.82\n', 'utf8');
    writeFileSync(path.join(caddisSkillsDir(home), 'some-file.txt'), 'legacy', 'utf8');

    const result = await codexAdapter.drive('install', { dryRun: false });
    expect(result.ok).toBe(true);
    expect(existsSync(caddisSkillsDir(home))).toBe(false);
    expect(result.steps.some((s) => s.command.includes('remove legacy'))).toBe(true);
  });

  it('keeps the legacy copy when the plugin install fails', async () => {
    mockWhich.mockResolvedValue('/usr/bin/codex');
    // detect ok, marketplace add ok, plugin add fails
    mockRun
      .mockResolvedValueOnce(ok('0.159.0'))
      .mockResolvedValueOnce(ok())
      .mockResolvedValueOnce({ ok: false, code: 1, stdout: '', stderr: 'boom' });

    const home = tmpHome();
    vi.spyOn(os, 'homedir').mockReturnValue(home);
    mkdirSync(caddisSkillsDir(home), { recursive: true });
    writeFileSync(versionFile(home), '1.3.82\n', 'utf8');

    const result = await codexAdapter.drive('install', { dryRun: false });
    expect(result.ok).toBe(false);
    expect(existsSync(caddisSkillsDir(home))).toBe(true); // a failed install must not leave nothing
    expect(result.steps.some((s) => s.command.includes('remove legacy'))).toBe(false);
  });

  it('a failed marketplace upgrade is advisory: the plugin step still runs', async () => {
    mockWhich.mockResolvedValue('/usr/bin/codex');
    mockRun
      .mockResolvedValueOnce(ok('0.159.0')) // detect
      .mockResolvedValueOnce({ ok: false, code: 1, stdout: '', stderr: 'network down' }) // upgrade
      .mockResolvedValueOnce(ok()); // plugin add

    const home = tmpHome();
    vi.spyOn(os, 'homedir').mockReturnValue(home);

    const result = await codexAdapter.drive('update', { dryRun: false });
    expect(result.ok).toBe(true);
    expect(result.steps.map((s) => s.command)).toEqual([
      expect.stringContaining('marketplace upgrade'),
      expect.stringContaining('plugin add'),
    ]);
    expect(result.steps[0]?.ok).toBe(false);
  });

  it('says so when --extras is asked for, because Codex has no extras plugin', async () => {
    mockWhich.mockResolvedValue('/usr/bin/codex');
    mockRun.mockResolvedValue(ok());
    const home = tmpHome();
    vi.spyOn(os, 'homedir').mockReturnValue(home);

    const result = await codexAdapter.drive('install', { dryRun: false, extras: true });
    expect(result.ok).toBe(true);
    expect(result.message).toContain('--extras has no Codex plugin');
  });

  it('warns about a marker-less old skills folder and leaves it alone', async () => {
    mockWhich.mockResolvedValue('/usr/bin/codex');
    mockRun.mockResolvedValue(ok());
    const home = tmpHome();
    vi.spyOn(os, 'homedir').mockReturnValue(home);
    mkdirSync(caddisSkillsDir(home), { recursive: true });
    writeFileSync(path.join(caddisSkillsDir(home), 'custom.txt'), 'mine', 'utf8');

    const result = await codexAdapter.drive('install', { dryRun: false });
    expect(result.ok).toBe(true);
    expect(existsSync(caddisSkillsDir(home))).toBe(true);
    expect(result.message).toContain('did not write it');
  });

  it('does not remove legacy directory without marker', async () => {
    mockWhich.mockResolvedValue('/usr/bin/codex');
    mockRun.mockResolvedValue(ok());

    const home = tmpHome();
    vi.spyOn(os, 'homedir').mockReturnValue(home);

    // Directory without marker
    mkdirSync(caddisSkillsDir(home), { recursive: true });
    writeFileSync(path.join(caddisSkillsDir(home), 'custom.txt'), 'custom', 'utf8');

    const result = await codexAdapter.drive('install', { dryRun: false });
    expect(result.ok).toBe(true);
    expect(existsSync(caddisSkillsDir(home))).toBe(true);
    expect(result.steps.some((s) => s.command.includes('remove legacy'))).toBe(false);
  });

  it('an already-present marketplace counts as success on install', async () => {
    mockWhich.mockResolvedValue('/usr/bin/codex');
    mockRun
      .mockResolvedValueOnce(ok('0.159.0')) // detect
      .mockResolvedValueOnce(fail("Marketplace `caddis` is already added from ...", 1)) // marketplace add exits 1
      .mockResolvedValueOnce(ok()); // plugin add

    const result = await codexAdapter.drive('install', { dryRun: false });
    expect(result.ok).toBe(true);
    expect(result.steps[0]?.ok).toBe(true);
  });

  it('fails when a plugin command fails', async () => {
    mockWhich.mockResolvedValue('/usr/bin/codex');
    mockRun
      .mockResolvedValueOnce(ok('0.159.0'))
      .mockResolvedValueOnce(ok()) // marketplace add ok
      .mockResolvedValueOnce(fail('plugin not found', 1)); // plugin add fails

    const result = await codexAdapter.drive('install', { dryRun: false });
    expect(result.ok).toBe(false);
    expect(result.message).toMatch(/plugin add.*failed/);
  });
});

describe('what it refuses to touch', () => {
  it('never writes config.toml', () => {
    const source = readFileSync(new URL('../src/agents/codex.ts', import.meta.url), 'utf8');
    const code = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
    expect(code).not.toMatch(/config\.toml['"`]/);
  });

  it('is registered as supported, and says config is never merged', () => {
    expect(codexAdapter.supported).toBe(true);
    expect(codexAdapter.summary).toMatch(/never merged/i);
  });
});
