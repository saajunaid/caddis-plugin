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

import { existsSync } from 'node:fs';
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

beforeEach(() => {
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
afterEach(() => capture.restore());

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
