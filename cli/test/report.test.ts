import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../src/util/pkg.js', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/util/pkg.js')>();
  return {
    ...actual,
    packageInfo: () => ({ root: '/pkg', name: '@caddis/cli', version: '0.1.0' }),
    bundleManifest: vi.fn(() => ({ poolVersion: '1.3.39', bundles: { 'antigravity-plugin': '1.3.39' } })),
  };
});
vi.mock('../src/util/exec.js', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/util/exec.js')>();
  return { ...actual, run: vi.fn() };
});

import { actionable, checkCliUpdate, gather } from '../src/commands/report.js';
import { run } from '../src/util/exec.js';
import { bundleManifest } from '../src/util/pkg.js';
import type { RunResult } from '../src/util/exec.js';
import { fakeAdapter } from './helpers.js';

const mockRun = vi.mocked(run);
const ok = (stdout = ''): RunResult => ({ ok: true, code: 0, stdout, stderr: '' });
const fail = (stderr = 'boom'): RunResult => ({ ok: false, code: 1, stdout: '', stderr });

beforeEach(() => {
  vi.mocked(bundleManifest).mockReturnValue({ poolVersion: '1.3.39', bundles: { 'antigravity-plugin': '1.3.39' } });
  mockRun.mockReset();
  mockRun.mockResolvedValue(ok('0.1.0')); // default: "no update available" for gather()'s own lookup
});

describe('drift classification', () => {
  it('current when the agent matches the shipped pool exactly', async () => {
    const report = await gather([fakeAdapter({ id: 'claude', agentStatus: { installed: true, version: '1.3.39' } })]);
    expect(report.agents[0]?.drift).toBe('current');
  });

  it('stale when the agent is behind the shipped pool', async () => {
    const report = await gather([fakeAdapter({ id: 'claude', agentStatus: { installed: true, version: '1.3.38' } })]);
    expect(report.agents[0]?.drift).toBe('stale');
  });

  it('stale when the agent is AHEAD of the shipped pool (a downgrade is still drift)', async () => {
    const report = await gather([fakeAdapter({ id: 'claude', agentStatus: { installed: true, version: '1.4.0' } })]);
    expect(report.agents[0]?.drift).toBe('stale');
  });

  it('missing when the agent is present but caddis is not installed', async () => {
    const report = await gather([fakeAdapter({ id: 'agy', agentStatus: { installed: false } })]);
    expect(report.agents[0]?.drift).toBe('missing');
  });

  it('unknown when the agent will not report a version', async () => {
    const report = await gather([fakeAdapter({ id: 'claude', agentStatus: { installed: true } })]);
    expect(report.agents[0]?.drift).toBe('unknown');
  });

  it('unknown when the package has no shipped pool version to compare against', async () => {
    vi.mocked(bundleManifest).mockReturnValue({ poolVersion: 'unknown', bundles: {} });
    const report = await gather([fakeAdapter({ id: 'claude', agentStatus: { installed: true, version: '1.3.39' } })]);
    expect(report.agents[0]?.drift).toBe('unknown');
  });

  it('absent beats everything when the agent is not on the machine', async () => {
    const report = await gather([
      fakeAdapter({ id: 'agy', detection: { present: false }, agentStatus: { installed: true, version: '1.3.39' } }),
    ]);
    expect(report.agents[0]?.drift).toBe('absent');
  });

  it('unsupported for a detected stub, regardless of what status says', async () => {
    const report = await gather([fakeAdapter({ id: 'codex', supported: false })]);
    expect(report.agents[0]?.drift).toBe('unsupported');
  });

  it('does not call status() on an absent agent', async () => {
    const adapter = fakeAdapter({ id: 'agy', detection: { present: false } });
    await gather([adapter]);
    expect(adapter.status).not.toHaveBeenCalled();
  });
});

describe('actionable()', () => {
  const adapters = [
    fakeAdapter({ id: 'claude', agentStatus: { installed: true, version: '1.3.38' } }), // stale
    fakeAdapter({ id: 'agy', agentStatus: { installed: true, version: '1.3.39' } }), // current
    fakeAdapter({ id: 'codex', supported: false }), // detected stub
    fakeAdapter({ id: 'copilot', detection: { present: false } }), // absent
  ];

  it('selects only present, supported, non-current agents', async () => {
    const report = await gather(adapters);
    expect(actionable(report).map((entry) => entry.adapter.id)).toEqual(['claude']);
  });

  it('includes already-current agents when asked (the init / --force path)', async () => {
    const report = await gather(adapters);
    expect(actionable(report, true).map((entry) => entry.adapter.id)).toEqual(['claude', 'agy']);
  });

  it('never selects an unsupported or absent agent, even with includeCurrent', async () => {
    const report = await gather(adapters);
    const ids = actionable(report, true).map((entry) => entry.adapter.id);
    expect(ids).not.toContain('codex');
    expect(ids).not.toContain('copilot');
  });
});

describe('report metadata', () => {
  it('carries the CLI version and the shipped pool version', async () => {
    const report = await gather([fakeAdapter({ id: 'claude' })]);
    expect(report.cliVersion).toBe('0.1.0');
    expect(report.poolVersion).toBe('1.3.39');
  });
});

describe('checkCliUpdate()', () => {
  it('returns null when already on the latest published version', async () => {
    mockRun.mockResolvedValue(ok('0.1.0'));
    expect(await checkCliUpdate('0.1.0')).toBeNull();
  });

  it('returns current + latest when a newer version is published', async () => {
    mockRun.mockResolvedValue(ok('0.2.0'));
    expect(await checkCliUpdate('0.1.0')).toEqual({ current: '0.1.0', latest: '0.2.0' });
  });

  it('returns null on a registry failure -- never a defect on its own, doctor must work offline', async () => {
    mockRun.mockResolvedValue(fail('ENOTFOUND registry.npmjs.org'));
    expect(await checkCliUpdate('0.1.0')).toBeNull();
  });

  it('returns null on empty/garbage stdout rather than a bogus "update"', async () => {
    mockRun.mockResolvedValue(ok('   '));
    expect(await checkCliUpdate('0.1.0')).toBeNull();
  });
});

describe('gather() cliUpdate opt-in', () => {
  it('does NOT check npm by default -- status/init/update stay network-free', async () => {
    await gather([fakeAdapter({ id: 'claude' })]);
    expect(mockRun).not.toHaveBeenCalled();
  });

  it('checks npm and surfaces cliUpdate when explicitly requested (doctor)', async () => {
    mockRun.mockResolvedValue(ok('9.9.9'));
    const report = await gather([fakeAdapter({ id: 'claude' })], { checkCliUpdate: true });
    expect(report.cliUpdate).toEqual({ current: '0.1.0', latest: '9.9.9' });
  });

  it('omits cliUpdate when requested but already current', async () => {
    mockRun.mockResolvedValue(ok('0.1.0'));
    const report = await gather([fakeAdapter({ id: 'claude' })], { checkCliUpdate: true });
    expect(report.cliUpdate).toBeUndefined();
  });
});
