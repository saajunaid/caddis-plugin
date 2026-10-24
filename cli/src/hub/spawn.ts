/**
 * Bounded, hidden spawns for the hub (R22, L9).
 *
 * Every spawn: `windowsHide: true`, `shell: false`, a timeout. On timeout the whole
 * process tree dies: `taskkill /T /F` on Windows, a process-group SIGKILL elsewhere.
 * `spawnBounded` never throws and never rejects.
 */
import { spawn } from 'node:child_process';

export interface SpawnOptions {
  timeoutMs: number;
  cwd?: string;
  env?: Record<string, string | undefined>;
  /** Cap for captured stdout and stderr, in bytes. Default 16 MB. */
  maxBytes?: number;
}

export interface SpawnResult {
  ok: boolean;
  code: number | null;
  stdout: string;
  stderr: string;
  timedOut: boolean;
}

export type SpawnFn = (cmd: string, args: string[], opts: SpawnOptions) => Promise<SpawnResult>;

const DEFAULT_MAX_BYTES = 16 * 1024 * 1024;

function killTree(pid: number): void {
  if (process.platform === 'win32') {
    try {
      spawn('taskkill', ['/T', '/F', '/PID', String(pid)], {
        windowsHide: true,
        shell: false,
        stdio: 'ignore',
      }).on('error', () => {});
    } catch {
      /* the process may already be gone */
    }
    return;
  }
  try {
    process.kill(-pid, 'SIGKILL');
  } catch {
    try {
      process.kill(pid, 'SIGKILL');
    } catch {
      /* already gone */
    }
  }
}

const SAFE_ARG = /^[A-Za-z0-9._:/@=-]+$/;
// `%` and `!` expand variables in cmd (`!` when delayed expansion is on); CR and LF end the command line.
const UNSAFE_PATH = /["&|<>^%!\r\n]/;

/**
 * Node 22 refuses to spawn a `.cmd` or `.bat` file with `shell: false` (EINVAL). On Windows we run
 * `cmd.exe /d /s /c ""<path>" args"` instead, and only when every argument is plainly safe.
 * Returns the new command line, or an error text when the call is refused.
 */
function wrapWindowsShim(cmd: string, args: string[]): { cmd: string; args: string[] } | { error: string } | null {
  if (process.platform !== 'win32' || !/\.(cmd|bat)$/i.test(cmd)) return null;
  if (UNSAFE_PATH.test(cmd)) return { error: `refused: the command path contains an unsafe character: ${cmd}` };
  for (const a of args) {
    if (!SAFE_ARG.test(a)) return { error: `refused argument for a .cmd shim: ${JSON.stringify(a)}` };
  }
  return { cmd: process.env.ComSpec || 'cmd.exe', args: ['/d', '/s', '/c', `""${cmd}"${args.map((a) => ` ${a}`).join('')}"`] };
}

export const spawnBounded: SpawnFn = (cmd, args, opts) =>
  new Promise<SpawnResult>((resolve) => {
    let verbatim = false;
    const wrapped = wrapWindowsShim(cmd, args);
    if (wrapped && 'error' in wrapped) {
      resolve({ ok: false, code: null, stdout: '', stderr: wrapped.error, timedOut: false });
      return;
    }
    if (wrapped) {
      verbatim = true;
      cmd = wrapped.cmd;
      args = wrapped.args;
    }
    const cap = opts.maxBytes ?? DEFAULT_MAX_BYTES;
    let stdout = '';
    let stderr = '';
    let timedOut = false;
    let settled = false;

    const finish = (code: number | null, extraErr = ''): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({
        ok: code === 0 && !timedOut,
        code,
        stdout,
        stderr: extraErr ? `${stderr}${stderr ? '\n' : ''}${extraErr}` : stderr,
        timedOut,
      });
    };

    let child;
    try {
      child = spawn(cmd, args, {
        cwd: opts.cwd,
        env: opts.env ? { ...process.env, ...opts.env } : process.env,
        windowsHide: true,
        shell: false,
        // The wrapped command line is already quoted for cmd.exe. Node must not quote it again.
        windowsVerbatimArguments: verbatim,
        detached: process.platform !== 'win32',
        stdio: ['ignore', 'pipe', 'pipe'],
      });
    } catch (error) {
      resolve({
        ok: false,
        code: null,
        stdout: '',
        stderr: error instanceof Error ? error.message : String(error),
        timedOut: false,
      });
      return;
    }

    const timer = setTimeout(() => {
      timedOut = true;
      if (child.pid !== undefined) killTree(child.pid);
      // Do not wait for pipes to close: a grandchild may hold them open.
      setTimeout(() => finish(null), 2000).unref();
    }, opts.timeoutMs);

    const append = (current: string, chunk: Buffer): string => {
      if (current.length >= cap) return current;
      return (current + chunk.toString('utf8')).slice(0, cap);
    };
    child.stdout?.on('data', (c: Buffer) => {
      stdout = append(stdout, c);
    });
    child.stderr?.on('data', (c: Buffer) => {
      stderr = append(stderr, c);
    });
    child.on('error', (error) => finish(null, error.message));
    child.on('close', (code) => finish(code));
  });
