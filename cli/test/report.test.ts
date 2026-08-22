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

  // CHANGED 2026-08-16. This previously asserted 'stale', on the reasoning that "a downgrade is
  // still drift". The difference IS still drift and is still surfaced — but calling it 'stale' put
  // two harmful things on it: the label read "update available" when no update exists, and
  // actionable() drives anything not 'current', so `caddis update` installed this package's OLDER
  // bundled pool over the newer one.
  //
  // That is not theoretical. Right after caddis 1.3.74 was published, `caddis status` reported
  // Claude Code (1.3.74, the newest thing on the machine) as "update available" and agy (1.3.54,
  // twenty releases behind) as "current" — wrong in both directions on the same run — and
  // `caddis update` then downgraded agy and reported success.
  it('ahead, not stale, when the agent is NEWER than the shipped pool', async () => {
    const report = await gather([fakeAdapter({ id: 'claude', agentStatus: { installed: true, version: '1.4.0' } })]);
    expect(report.agents[0]?.drift).toBe('ahead');
  });

  it('never drives an agent that is ahead — that would be a downgrade', async () => {
    const report = await gather([fakeAdapter({ id: 'claude', agentStatus: { installed: true, version: '1.4.0' } })]);
    expect(actionable(report)).toHaveLength(0);
  });

  it('--force can still drive an ahead agent — a deliberate rollback is a real thing to want', async () => {
    const report = await gather([fakeAdapter({ id: 'claude', agentStatus: { installed: true, version: '1.4.0' } })]);
    expect(actionable(report, { includeCurrent: true, allowDowngrade: true })).toHaveLength(1);
  });

  // REGRESSION 2026-08-22. `includeCurrent` and "may downgrade" used to be the SAME flag, and
  // init.ts passed it to reinstall every detected agent. So `npx caddis init` on a machine whose
  // agy install was newer than the CLI's bundle silently rolled it back and reported success —
  // the same failure 652dcfd fixed for `update`, reachable through the other command.
  it('init (includeCurrent, no --force) must NEVER drive an ahead agent', async () => {
    const report = await gather([fakeAdapter({ id: 'claude', agentStatus: { installed: true, version: '1.4.0' } })]);
    expect(actionable(report, { includeCurrent: true })).toHaveLength(0);
  });

  it('still drives an agent that is genuinely behind', async () => {
    const report = await gather([fakeAdapter({ id: 'claude', agentStatus: { installed: true, version: '1.3.38' } })]);
    expect(actionable(report)).toHaveLength(1);
  });

  it('orders numerically, not as strings — 1.3.9 is BEHIND 1.3.39', async () => {
    const report = await gather([fakeAdapter({ id: 'claude', agentStatus: { installed: true, version: '1.3.9' } })]);
    expect(report.agents[0]?.drift).toBe('stale');
  });

  it('falls back to equality when a version cannot be ordered', async () => {
    // An unreadable version must never become an ordering claim, because an ordering claim is what
    // authorises a downgrade. Different-and-unorderable stays 'stale', the old conservative answer.
    const report = await gather([fakeAdapter({ id: 'claude', agentStatus: { installed: true, version: 'nightly' } })]);
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
    expect(actionable(report, { includeCurrent: true }).map((entry) => entry.adapter.id)).toEqual([
      'claude',
      'agy',
    ]);
  });

  it('never selects an unsupported or absent agent, even with includeCurrent', async () => {
    const report = await gather(adapters);
    const ids = actionable(report, { includeCurrent: true }).map((entry) => entry.adapter.id);
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

describe('what "current" is allowed to claim', () => {
  it('an agent equal to a STALE bundled pool still reads current — the known blind spot', async () => {
    // Documented, not fixed in the classifier: status is deliberately network-free, so it cannot
    // know the marketplace version. Measured 2026-08-16 — Claude Code read `current` at 1.3.74
    // while the marketplace had 1.3.75. The mitigation is that status now SAYS what `current` is
    // relative to, and doctor says every `current` may be wrong when the CLI itself is behind.
    const report = await gather([fakeAdapter({ id: 'claude', agentStatus: { installed: true, version: '1.3.39' } })]);
    expect(report.agents[0]?.drift).toBe('current');
  });
});
