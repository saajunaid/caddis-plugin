import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

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

import { doctor } from '../src/commands/doctor.js';
import { status } from '../src/commands/status.js';
import { update } from '../src/commands/update.js';
import { run } from '../src/util/exec.js';
import { bundleManifest } from '../src/util/pkg.js';
import type { RunResult } from '../src/util/exec.js';
import { captureStdout, fakeAdapter } from './helpers.js';

let capture: ReturnType<typeof captureStdout>;
const mockRun = vi.mocked(run);

beforeEach(() => {
  vi.mocked(bundleManifest).mockReturnValue({ poolVersion: '1.3.39', bundles: { 'antigravity-plugin': '1.3.39' } });
  // doctor's own npm-registry lookup (checkCliUpdate) must never hit the real network in tests --
  // default to "already current" so it's a non-event unless a test overrides it.
  mockRun.mockReset();
  mockRun.mockResolvedValue({ ok: true, code: 0, stdout: '0.1.0', stderr: '' } satisfies RunResult);
  capture = captureStdout();
});
afterEach(() => capture.restore());

/** The machine this CLI was built on: two supported agents behind, two stubs detected. */
function realWorldAdapters() {
  return [
    fakeAdapter({
      id: 'claude',
      name: 'Claude Code',
      detection: { present: true, path: '/bin/claude', agentVersion: '2.1.220' },
      agentStatus: { installed: true, version: '1.3.38', source: '`claude plugin list`' },
    }),
    fakeAdapter({
      id: 'agy',
      name: 'agy (Antigravity)',
      detection: { present: true, path: '/bin/agy', agentVersion: '1.1.7' },
      agentStatus: { installed: true, version: '1.3.38', source: '~/.gemini/.../plugin.json' },
    }),
    fakeAdapter({ id: 'codex', name: 'Codex', supported: false, detection: { present: true, path: '/bin/codex' } }),
    fakeAdapter({ id: 'copilot', name: 'GitHub Copilot', detection: { present: false } }),
  ];
}

describe('doctor', () => {
  it('reports drift, the source it was read from, and the exact fix', async () => {
    const code = await doctor({ adapters: realWorldAdapters() });
    const out = capture.output();

    expect(out).toContain('@caddis/cli 0.1.0');
    expect(out).toContain('shipped pool 1.3.39');
    expect(out).toContain('Claude Code — caddis 1.3.38 → 1.3.39 available');
    expect(out).toContain('read from `claude plugin list`');
    expect(out).toContain('caddis update --agent claude');
    expect(out).toContain('caddis update --agent agy');
    expect(out).toContain('3 of 4 agents detected');
    expect(code).toBe(0); // non-strict never fails the process
  });

  it('lists a detected v0.2 stub as information, NOT as a thing to fix', async () => {
    await doctor({ adapters: realWorldAdapters() });
    const out = capture.output();
    expect(out).toContain('2 things to fix:'); // claude + agy only
    expect(out).toContain('For your information:');
    expect(out).toMatch(/Codex is on this machine but v0\.1 cannot drive it/);
  });

  it('--strict exits 1 on real drift', async () => {
    expect(await doctor({ adapters: realWorldAdapters(), strict: true })).toBe(1);
  });

  it('flags a stale @caddis/cli itself, not just the agents it drives', async () => {
    mockRun.mockResolvedValue({ ok: true, code: 0, stdout: '0.5.0', stderr: '' } satisfies RunResult);
    const code = await doctor({ adapters: realWorldAdapters(), strict: true });
    const out = capture.output();
    expect(out).toContain('@caddis/cli 0.1.0 → 0.5.0 available');
    expect(out).toContain('@caddis/cli itself is behind: 0.1.0 installed, 0.5.0 published');
    expect(out).toContain('npm i -g @caddis/cli@latest');
    expect(out).toContain('3 things to fix:'); // claude + agy + the CLI itself
    expect(code).toBe(1); // counts toward --strict, unlike the old decoupled update-notifier banner
  });

  it('a registry lookup failure does not add a phantom finding (never blocks doctor offline)', async () => {
    mockRun.mockResolvedValue({ ok: false, code: 1, stdout: '', stderr: 'ENOTFOUND' } satisfies RunResult);
    const code = await doctor({ adapters: realWorldAdapters(), strict: true });
    expect(capture.output()).toContain('2 things to fix:'); // unchanged from the baseline case
    expect(code).toBe(1); // still 1, from the real claude/agy drift -- not from the failed lookup
  });

  it('--strict exits 0 when only v0.2 stubs are outstanding', async () => {
    const adapters = [
      fakeAdapter({ id: 'claude', name: 'Claude Code', agentStatus: { installed: true, version: '1.3.39' } }),
      fakeAdapter({ id: 'codex', name: 'Codex', supported: false, detection: { present: true } }),
    ];
    expect(await doctor({ adapters, strict: true })).toBe(0);
    expect(capture.output()).toContain('Everything caddis manages is current.');
  });

  it('flags an installed-but-DISABLED plugin even at the right version', async () => {
    const adapters = [
      fakeAdapter({
        id: 'claude',
        name: 'Claude Code',
        agentStatus: { installed: true, version: '1.3.39', disabled: true },
      }),
    ];
    expect(await doctor({ adapters, strict: true })).toBe(1);
    expect(capture.output()).toContain('claude plugin enable caddis@caddis');
  });

  it('--json emits parseable machine output and no prose', async () => {
    await doctor({ adapters: realWorldAdapters(), json: true });
    const parsed = JSON.parse(capture.output());
    expect(parsed.poolVersion).toBe('1.3.39');
    expect(parsed.agents).toHaveLength(4);
    expect(parsed.agents[0]).toMatchObject({ id: 'claude', caddisVersion: '1.3.38', drift: 'stale' });
    expect(parsed.agents[3]).toMatchObject({ id: 'copilot', present: false, drift: 'absent' });
  });

  it('calls out a package with no shipped bundles', async () => {
    vi.mocked(bundleManifest).mockReturnValue({ poolVersion: 'unknown', bundles: {} });
    expect(await doctor({ adapters: realWorldAdapters(), strict: true })).toBe(1);
    expect(capture.output()).toContain('this package has no shipped bundles');
  });
});

describe('status', () => {
  it('renders one aligned row per agent under a versions header', async () => {
    const code = await status({ adapters: realWorldAdapters() });
    const out = capture.output();

    expect(out).toContain('cli 0.1.0');
    expect(out).toContain('pool 1.3.39');
    expect(out).toMatch(/AGENT\s+DETECTED\s+CADDIS\s+EXTRAS\s+STATE/);
    expect(out).toMatch(/Claude Code\s+yes\s+1\.3\.38\s+—\s+update available/);
    expect(out).toMatch(/Codex\s+yes\s+—\s+—\s+v0\.2/);
    expect(out).toMatch(/GitHub Copilot\s+no\s+—\s+—/);
    expect(out).toContain('2 agent(s) behind');
    expect(code).toBe(0);
  });

  it('stays quiet when everything is current', async () => {
    await status({
      adapters: [fakeAdapter({ id: 'claude', name: 'Claude Code', agentStatus: { installed: true, version: '1.3.39' } })],
    });
    expect(capture.output()).not.toContain('behind');
  });

  it('--json mirrors the table', async () => {
    await status({ adapters: realWorldAdapters(), json: true });
    const parsed = JSON.parse(capture.output());
    expect(parsed).toMatchObject({ cliVersion: '0.1.0', poolVersion: '1.3.39' });
    expect(parsed.agents.map((a: { drift: string }) => a.drift)).toEqual(['stale', 'stale', 'unsupported', 'absent']);
  });
});

describe('update', () => {
  it('drives only the stale, supported agents', async () => {
    const adapters = realWorldAdapters();
    const code = await update({ adapters, dryRun: false, yes: true });

    expect(adapters[0]?.drive).toHaveBeenCalledWith('update', { dryRun: false, extras: false });
    expect(adapters[1]?.drive).toHaveBeenCalledWith('update', { dryRun: false, extras: false });
    expect(adapters[2]?.drive).not.toHaveBeenCalled(); // codex stub
    expect(adapters[3]?.drive).not.toHaveBeenCalled(); // absent
    expect(code).toBe(0);
  });

  it('says WHY each agent was skipped instead of silently ignoring it', async () => {
    await update({ adapters: realWorldAdapters(), dryRun: false, yes: true });
    const out = capture.output();
    expect(out).toContain('GitHub Copilot — not installed');
    expect(out).toContain('Codex — detected, not yet supported (v0.2)');
  });

  it('--dry-run changes nothing and says so', async () => {
    const adapters = realWorldAdapters();
    await update({ adapters, dryRun: true, yes: true });
    expect(adapters[0]?.drive).toHaveBeenCalledWith('update', { dryRun: true, extras: false });
    expect(capture.output()).toContain('dry run');
  });

  it('does nothing when every supported agent is already current', async () => {
    const adapters = [
      fakeAdapter({ id: 'claude', name: 'Claude Code', agentStatus: { installed: true, version: '1.3.39' } }),
    ];
    await update({ adapters, dryRun: false, yes: true });
    expect(adapters[0]?.drive).not.toHaveBeenCalled();
    expect(capture.output()).toContain('Everything is already current.');
  });

  it('--force re-drives an already-current agent', async () => {
    const adapters = [
      fakeAdapter({ id: 'claude', name: 'Claude Code', agentStatus: { installed: true, version: '1.3.39' } }),
    ];
    await update({ adapters, dryRun: false, yes: true, force: true });
    expect(adapters[0]?.drive).toHaveBeenCalled();
  });

  it('exits 1 on a failure but still drives the OTHER agents', async () => {
    const adapters = [
      fakeAdapter({
        id: 'claude',
        name: 'Claude Code',
        agentStatus: { installed: true, version: '1.3.38' },
        driveResult: { ok: false, skipped: false, steps: [{ command: 'claude plugin update caddis@caddis', ok: false, code: 1, output: 'nope' }], message: 'failed' },
      }),
      fakeAdapter({ id: 'agy', name: 'agy', agentStatus: { installed: true, version: '1.3.38' } }),
    ];
    const code = await update({ adapters, dryRun: false, yes: true });
    expect(adapters[1]?.drive).toHaveBeenCalled();
    expect(code).toBe(1);
    expect(capture.output()).toContain('1 agent(s) failed');
  });

  it('guides the user when no supported agent exists at all', async () => {
    const adapters = [fakeAdapter({ id: 'codex', name: 'Codex', supported: false, detection: { present: true } })];
    expect(await update({ adapters, dryRun: false, yes: true })).toBe(0);
    expect(capture.output()).toContain('No supported agent found.');
  });
});

describe('status qualifies what it cannot know', () => {
  it('names the pool as the yardstick, in the header', async () => {
    // status is network-free and cannot see the marketplace, so `current` only ever meant "matches
    // this CLI's bundled pool". Measured 2026-08-16: Claude Code read `current` at 1.3.74 while
    // the marketplace had 1.3.75.
    await status({ adapters: [fakeAdapter({ id: 'claude', agentStatus: { installed: true, version: '1.3.39' } })] });
    expect(capture.output()).toContain('what "current" is measured against');
  });

  it('adds no extra line, so a healthy run stays quiet', async () => {
    // The first attempt was a footer, and it broke the existing "stays quiet when everything is
    // current" test. That test was right: a qualifier phrased like a warning fires on every healthy
    // run, and a warning that always fires is the one nobody reads.
    await status({ adapters: [fakeAdapter({ id: 'claude', agentStatus: { installed: true, version: '1.3.39' } })] });
    const out = capture.output();
    expect(out).not.toContain('behind');
    expect(out).not.toContain('doctor');
  });
});
