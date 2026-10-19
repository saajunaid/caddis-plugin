import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// The Python doctor script is "present" unless a test says otherwise.
vi.mock('node:fs', async (importOriginal) => {
  const actual = await importOriginal<typeof import('node:fs')>();
  return { ...actual, existsSync: vi.fn(() => true) };
});
vi.mock('../src/util/which.js', () => ({ findBin: vi.fn() }));
vi.mock('../src/util/pkg.js', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/util/pkg.js')>();
  return {
    ...actual,
    bundlePath: vi.fn(),
    bundleManifest: vi.fn(() => ({ poolVersion: '1.3.39', bundles: { 'antigravity-plugin': '1.3.39' } })),
  };
});
vi.mock('../src/util/exec.js', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/util/exec.js')>();
  return { ...actual, run: vi.fn() };
});

import { existsSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { doctor } from '../src/commands/doctor.js';
import { run } from '../src/util/exec.js';
import { bundlePath, packageInfo } from '../src/util/pkg.js';
import { findBin } from '../src/util/which.js';
import type { RunResult } from '../src/util/exec.js';
import { captureStdout, fakeAdapter } from './helpers.js';

// The registry lookup must say "this is the newest": use the version the package really has, so a
// version bump at release time cannot turn a clean doctor into "CLI behind" (it did on 0.4.40).
const CLI_VERSION = packageInfo().version;
let capture: ReturnType<typeof captureStdout>;
const mockWhich = vi.mocked(findBin);
const mockBundle = vi.mocked(bundlePath);
const mockRun = vi.mocked(run);

// No test reads the real ~/.caddis/sessions/: this machine's live sessions are not test data.
const emptyHome = mkdtempSync(path.join(tmpdir(), 'caddis-doctor-home-'));

beforeEach(() => {
  vi.stubEnv('CADDIS_HOME', emptyHome);
  mockWhich.mockReset();
  mockWhich.mockResolvedValue('/usr/bin/python');
  mockBundle.mockReset();
  mockBundle.mockReturnValue('/mock/bundle');
  mockRun.mockReset();
  mockRun.mockImplementation(async (cmd, args) => {
    if (cmd === 'npm') {
      return { ok: true, code: 0, stdout: CLI_VERSION, stderr: '' };
    }
    return {
      ok: true,
      code: 0,
      stdout: '=== caddis doctor ===\n-- machine\n  OK   python\n',
      stderr: '',
    };
  });
  capture = captureStdout();
});
afterEach(() => {
  capture.restore();
  vi.unstubAllEnvs();
});

function cleanAdapters() {
  return [
    fakeAdapter({ id: 'claude', name: 'Claude Code', agentStatus: { installed: true, version: '1.3.39' } }),
  ];
}

describe('caddis doctor project health check', () => {
  it('prints the python report under Project', async () => {
    mockRun.mockImplementation(async (cmd) => {
      if (cmd === 'npm') return { ok: true, code: 0, stdout: CLI_VERSION, stderr: '' };
      return {
        ok: true,
        code: 0,
        stdout: '=== caddis doctor — /project ===\n-- machine\n  OK   python (on PATH): 3.12.4\nOK.',
        stderr: '',
      };
    });
    const code = await doctor({ adapters: cleanAdapters() });
    const out = capture.output();

    expect(out).toContain('Project');
    expect(out).toContain('=== caddis doctor — /project ===');
    expect(out).toContain('OK   python (on PATH): 3.12.4');
    expect(mockRun).toHaveBeenCalledWith(
      '/usr/bin/python',
      [expect.stringContaining('claudster_doctor.py'), '--dest', process.cwd()],
      { timeout: 60_000 },
    );
    expect(code).toBe(0);
  });

  it('python missing is a problem', async () => {
    mockWhich.mockResolvedValue(null);
    const code = await doctor({ adapters: cleanAdapters(), strict: true });
    const out = capture.output();

    expect(out).toContain('Project');
    expect(out).toContain('python not on PATH');
    expect(out).toContain('install Python 3.11 or later (see docs/ONBOARDING.md)');
    expect(code).toBe(1);
  });

  it('a failing python report fails --strict', async () => {
    mockRun.mockImplementation(async (cmd) => {
      if (cmd === 'npm') return { ok: true, code: 0, stdout: CLI_VERSION, stderr: '' };
      return {
        ok: false,
        code: 1,
        stdout: '=== caddis doctor ===\n-- machine\n  FAIL python (on PATH): not found\nFAIL — fix the above.',
        stderr: '',
      };
    });
    const code = await doctor({ adapters: cleanAdapters(), strict: true });
    const out = capture.output();

    expect(out).toContain('project health check failed');
    expect(out).toContain('read the FAIL lines above');
    expect(code).toBe(1);
  });

  it('a clean python report keeps --strict at 0', async () => {
    mockRun.mockImplementation(async (cmd) => {
      if (cmd === 'npm') return { ok: true, code: 0, stdout: CLI_VERSION, stderr: '' };
      return {
        ok: true,
        code: 0,
        stdout: '=== caddis doctor ===\nOK.',
        stderr: '',
      };
    });
    const code = await doctor({ adapters: cleanAdapters(), strict: true });
    const out = capture.output();

    expect(out).toContain('Everything caddis manages is current.');
    expect(code).toBe(0);
  });

  it('json carries the project exit code', async () => {
    mockRun.mockImplementation(async (cmd) => {
      if (cmd === 'npm') return { ok: true, code: 0, stdout: CLI_VERSION, stderr: '' };
      return {
        ok: true,
        code: 0,
        stdout: 'OK.',
        stderr: '',
      };
    });
    const code = await doctor({ adapters: cleanAdapters(), json: true });
    const parsed = JSON.parse(capture.output());

    expect(parsed.project).toEqual({ ran: true, exitCode: 0 });
    expect(code).toBe(0);
  });

  it('reports a problem when the bundle exists but claudster_doctor.py is not in it', async () => {
    vi.mocked(existsSync).mockReturnValueOnce(false);
    const code = await doctor({ adapters: cleanAdapters(), strict: true });
    expect(capture.output()).toContain('reinstall: npm i -g @caddis/cli');
    expect(code).toBe(1);
  });

  it('reports a problem when claudster_doctor.py is missing', async () => {
    mockBundle.mockReturnValue(null);
    const code = await doctor({ adapters: cleanAdapters(), strict: true });
    const out = capture.output();

    expect(out).toContain('reinstall: npm i -g @caddis/cli');
    expect(code).toBe(1);
  });
});

describe('caddis doctor live sessions on an older caddis', () => {
  function homeWith(entries: object[]): string {
    const home = mkdtempSync(path.join(tmpdir(), 'caddis-doctor-sessions-'));
    const dir = path.join(home, '.caddis', 'sessions');
    mkdirSync(dir, { recursive: true });
    entries.forEach((entry, i) => writeFileSync(path.join(dir, `s${i}.json`), JSON.stringify(entry)));
    return home;
  }
  const nowS = Date.now() / 1000;

  it('names each live session that runs an older caddis and says to restart them', async () => {
    const home = homeWith([
      { session_id: 'aaaa-old', harness: 'claude', caddis_version: '1.3.30', pid: process.pid, started: nowS - 3600, last_seen: nowS },
      { session_id: 'bbbb-new', harness: 'claude', caddis_version: '1.3.39', pid: process.pid, started: nowS, last_seen: nowS },
    ]);
    const code = await doctor({ adapters: cleanAdapters(), strict: true, home });
    const out = capture.output();
    expect(out).toContain('Sessions');
    expect(out).toContain('aaaa-old');
    expect(out).not.toContain('bbbb-new');
    expect(out).toContain('1.3.30');
    expect(out).toMatch(/restart these sessions/);
    expect(code).toBe(1);
  });

  it('says nothing is behind when every live session is current', async () => {
    const home = homeWith([
      { session_id: 'cccc', harness: 'claude', caddis_version: '1.3.39', pid: process.pid, started: nowS, last_seen: nowS },
    ]);
    const code = await doctor({ adapters: cleanAdapters(), strict: true, home });
    expect(capture.output()).toContain('no live session runs an older caddis');
    expect(code).toBe(0);
  });

  it('prints "started unknown" for a start time that is not a valid date', async () => {
    const home = homeWith([
      { session_id: 'eeee', harness: 'claude', caddis_version: '1.3.1', pid: process.pid, started: 1e20, last_seen: nowS },
    ]);
    await doctor({ adapters: cleanAdapters(), home });
    expect(capture.output()).toMatch(/eeee.*started unknown/);
  });

  it('lists the older sessions in --json', async () => {
    const home = homeWith([
      { session_id: 'dddd', harness: 'claude', caddis_version: '1.3.1', pid: process.pid, started: nowS, last_seen: nowS },
    ]);
    await doctor({ adapters: cleanAdapters(), json: true, home });
    const parsed = JSON.parse(capture.output());
    expect(parsed.olderSessions).toEqual([
      expect.objectContaining({ sessionId: 'dddd', caddisVersion: '1.3.1', installed: '1.3.39', pid: process.pid }),
    ]);
  });
});
