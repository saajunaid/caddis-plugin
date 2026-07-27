/**
 * Process execution. Every adapter drives another vendor's CLI through here.
 *
 * Contract: `run` NEVER throws and NEVER rejects. Driving CLIs we do not
 * control is plan risk #3 — a missing binary, a renamed flag or a non-zero
 * exit must surface as a readable line, not a stack trace that kills the whole
 * multi-agent run.
 */
export interface RunResult {
  ok: boolean;
  code: number | null;
  stdout: string;
  stderr: string;
  /** Set when the process could not be started at all (ENOENT, EACCES, ...). */
  failure?: string;
}

export interface RunOptions {
  cwd?: string;
  timeout?: number;
  env?: Record<string, string>;
}

/** Default per-command timeout. `claude plugin update` hits the network. */
const DEFAULT_TIMEOUT_MS = 120_000;

export async function run(cmd: string, args: string[], opts: RunOptions = {}): Promise<RunResult> {
  const { execa } = await import('execa');
  try {
    const result = await execa(cmd, args, {
      cwd: opts.cwd,
      timeout: opts.timeout ?? DEFAULT_TIMEOUT_MS,
      env: opts.env,
      reject: false,
      all: false,
      stripFinalNewline: true,
      // Windows: resolve .cmd/.ps1 shims through the shell-less path lookup
      // execa already does, but be explicit that we are not using a shell.
      shell: false,
      windowsHide: true,
    });
    return {
      ok: result.exitCode === 0 && !result.failed,
      code: result.exitCode ?? null,
      stdout: String(result.stdout ?? ''),
      stderr: String(result.stderr ?? ''),
      failure: result.failed && result.exitCode === undefined ? result.shortMessage : undefined,
    };
  } catch (error) {
    return {
      ok: false,
      code: null,
      stdout: '',
      stderr: '',
      failure: error instanceof Error ? error.message : String(error),
    };
  }
}

/** Render a command the way a user would retype it. Used by --dry-run and errors. */
export function formatCommand(cmd: string, args: string[]): string {
  const quoted = args.map((a) => (/\s/.test(a) ? `"${a}"` : a));
  return [cmd, ...quoted].join(' ');
}
