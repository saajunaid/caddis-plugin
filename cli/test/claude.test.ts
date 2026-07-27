import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('../src/util/which.js', () => ({ findBin: vi.fn() }));
vi.mock('../src/util/exec.js', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/util/exec.js')>();
  return { ...actual, run: vi.fn() };
});

import { claudeAdapter, parsePluginList } from '../src/agents/claude.js';
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

/** Verbatim `claude plugin list` output from Claude Code 2.1.220. */
const REAL_LIST = `Installed plugins:

  ❯ caddis-extras@caddis
    Version: 1.3.10
    Scope: user
    Status: ✘ disabled

  ❯ caddis@caddis
    Version: 1.3.38
    Scope: user
    Status: ✔ enabled

  ❯ context7@claude-plugins-official
    Version: unknown
    Scope: user
    Status: ✔ enabled
`;

beforeEach(() => {
  mockRun.mockReset();
  mockWhich.mockReset();
});

describe('parsePluginList', () => {
  it('reads the caddis version out of real `claude plugin list` output', () => {
    expect(parsePluginList(REAL_LIST)).toEqual({ version: '1.3.38', disabled: false });
  });

  it('does NOT confuse caddis-extras with caddis', () => {
    // caddis-extras (1.3.10) is printed FIRST. A scan-for-the-next-Version
    // parser returns 1.3.10 here; keying on the block header is what prevents it.
    expect(parsePluginList(REAL_LIST)?.version).toBe('1.3.38');
    expect(parsePluginList(REAL_LIST, 'caddis-extras@caddis')).toEqual({ version: '1.3.10', disabled: true });
  });

  it('reports a disabled plugin as disabled', () => {
    expect(parsePluginList(REAL_LIST, 'caddis-extras@caddis')?.disabled).toBe(true);
  });

  it('treats "Version: unknown" as no version, not a literal', () => {
    expect(parsePluginList(REAL_LIST, 'context7@claude-plugins-official')?.version).toBeUndefined();
  });

  it('returns null when caddis is not installed', () => {
    expect(parsePluginList('Installed plugins:\n\n  ❯ other@mp\n    Version: 1.0.0\n')).toBeNull();
  });

  it('handles CRLF and a missing bullet glyph', () => {
    expect(parsePluginList('caddis@caddis\r\n  Version: 2.0.0\r\n  Status: enabled\r\n')).toEqual({
      version: '2.0.0',
      disabled: false,
    });
  });
});

describe('claude adapter detect', () => {
  it('reports absent when the binary is not on PATH', async () => {
    mockWhich.mockResolvedValue(null);
    const detected = await claudeAdapter.detect();
    expect(detected.present).toBe(false);
    expect(mockRun).not.toHaveBeenCalled();
  });

  it('reports present with the agent version', async () => {
    mockWhich.mockResolvedValue('C:\\bin\\claude.CMD');
    mockRun.mockResolvedValue(ok('2.1.220 (Claude Code)'));
    const detected = await claudeAdapter.detect();
    expect(detected).toMatchObject({ present: true, path: 'C:\\bin\\claude.CMD', agentVersion: '2.1.220' });
  });

  it('stays present when --version fails', async () => {
    mockWhich.mockResolvedValue('/usr/bin/claude');
    mockRun.mockResolvedValue(fail());
    const detected = await claudeAdapter.detect();
    expect(detected.present).toBe(true);
    expect(detected.agentVersion).toBeUndefined();
    expect(detected.note).toMatch(/--version` failed/);
  });
});

describe('claude adapter status', () => {
  it('returns the installed caddis version', async () => {
    mockWhich.mockResolvedValue('/usr/bin/claude');
    mockRun.mockResolvedValueOnce(ok('2.1.220')).mockResolvedValueOnce(ok(REAL_LIST));
    expect(await claudeAdapter.status()).toMatchObject({ installed: true, version: '1.3.38' });
  });

  it('is not-installed when caddis is absent from the list', async () => {
    mockWhich.mockResolvedValue('/usr/bin/claude');
    mockRun.mockResolvedValueOnce(ok('2.1.220')).mockResolvedValueOnce(ok('Installed plugins:\n'));
    expect(await claudeAdapter.status()).toMatchObject({ installed: false });
  });

  it('degrades gracefully when `plugin list` itself fails', async () => {
    mockWhich.mockResolvedValue('/usr/bin/claude');
    mockRun.mockResolvedValueOnce(ok('2.1.220')).mockResolvedValueOnce(fail('not logged in'));
    const status = await claudeAdapter.status();
    expect(status.installed).toBe(false);
    expect(status.note).toMatch(/could not read plugin list/);
  });
});

describe('claude adapter drive', () => {
  it('skips cleanly when the agent is absent', async () => {
    mockWhich.mockResolvedValue(null);
    const result = await claudeAdapter.drive('update', { dryRun: false });
    expect(result).toMatchObject({ ok: true, skipped: true });
    expect(mockRun).not.toHaveBeenCalled();
  });

  it('runs marketplace update then plugin update', async () => {
    mockWhich.mockResolvedValue('/usr/bin/claude');
    mockRun.mockResolvedValue(ok());
    const result = await claudeAdapter.drive('update', { dryRun: false });
    expect(result.ok).toBe(true);
    const commands = result.steps.map((step) => step.command);
    expect(commands).toEqual([
      'claude plugin marketplace update caddis',
      'claude plugin update caddis@caddis',
    ]);
  });

  it('uses `plugin install` for the install action', async () => {
    mockWhich.mockResolvedValue('/usr/bin/claude');
    mockRun.mockResolvedValue(ok());
    const result = await claudeAdapter.drive('install', { dryRun: false });
    expect(result.steps.at(-1)?.command).toBe('claude plugin install caddis@caddis');
  });

  it('--dry-run lists the commands and executes nothing', async () => {
    mockWhich.mockResolvedValue('/usr/bin/claude');
    mockRun.mockResolvedValue(ok('2.1.220'));
    const result = await claudeAdapter.drive('update', { dryRun: true });
    expect(result.skipped).toBe(true);
    expect(result.steps).toHaveLength(2);
    // the only run() call allowed is the detect probe
    expect(mockRun.mock.calls.every(([, args]) => args[0] === '--version')).toBe(true);
  });

  it('tolerates a failing marketplace refresh but still updates', async () => {
    mockWhich.mockResolvedValue('/usr/bin/claude');
    mockRun
      .mockResolvedValueOnce(ok('2.1.220')) // detect
      .mockResolvedValueOnce(fail('network unreachable')) // marketplace update
      .mockResolvedValueOnce(ok()); // plugin update
    const result = await claudeAdapter.drive('update', { dryRun: false });
    expect(result.ok).toBe(true);
    expect(result.steps[0]?.ok).toBe(false);
    expect(result.steps[1]?.ok).toBe(true);
  });

  it('fails the agent — not the process — when the update itself fails', async () => {
    mockWhich.mockResolvedValue('/usr/bin/claude');
    mockRun
      .mockResolvedValueOnce(ok('2.1.220'))
      .mockResolvedValueOnce(ok())
      .mockResolvedValueOnce(fail('marketplace caddis not found'));
    const result = await claudeAdapter.drive('update', { dryRun: false });
    expect(result.ok).toBe(false);
    expect(result.message).toMatch(/plugin update caddis@caddis` failed/);
    expect(result.steps.at(-1)?.output).toContain('marketplace caddis not found');
  });
});
