/**
 * Launch a Claude Code session against an OSS provider's Anthropic-protocol endpoint.
 *
 * Behaviour is ported from `claude-harness/scripts/claude-oss.sh` / `.ps1`, which stay in
 * the repo for plugin-only installs that have no npm CLI. Two behaviours carry across
 * exactly, because other parts of caddis depend on them:
 *
 *  * The provider env lives on the CHILD only. The shell that ran `claude-glm` keeps a
 *    clean environment, so a later plain `claude` is untouched. The `.sh` gets this from
 *    `exec`; here it comes from passing `env` to spawn rather than mutating `process.env`.
 *
 *  * `-p` / `--print` sets `CADDIS_HEADLESS=1`. The SessionStart relay hook reads it
 *    (`inject_relay.py`) and skips injection for headless runs — a run handed its task on
 *    the command line was observed EXECUTING the relay's leftover next step instead of its
 *    own prompt.
 */
import { ConfigError, maskKey, resolve } from '../providers/resolve.js';
import { errorLine } from '../util/log.js';
import { findBin } from '../util/which.js';

export interface LaunchOptions {
  /** Preset name, or undefined to take $OSS_PROVIDER then the default. */
  provider?: string;
  /** Everything after the provider — passed to `claude` untouched. */
  args: string[];
  env?: NodeJS.ProcessEnv;
}

/** True when the args ask for a non-interactive run. */
export function isHeadless(args: string[]): boolean {
  return args.some((a) => a === '-p' || a === '--print');
}

export async function launch(options: LaunchOptions): Promise<number> {
  const env = options.env ?? process.env;
  const args = options.args;

  // `--print-config` is ours, not claude's. It is the zero-token smoke test: it proves the
  // endpoint, model and key all resolved without spending anything on a request.
  const printConfig = args.includes('--print-config');
  const forwarded = args.filter((a) => a !== '--print-config');

  let resolved;
  try {
    resolved = resolve(options.provider, env as Record<string, string | undefined>);
  } catch (error) {
    if (error instanceof ConfigError) {
      errorLine(error.message);
      return 3; // same exit code the shell launchers use for a resolve failure
    }
    throw error;
  }

  if (printConfig) {
    process.stdout.write(
      `provider  ${resolved.provider}\n` +
        `base_url  ${resolved.baseUrl}\n` +
        `model     ${resolved.model}\n` +
        `api_key   ${maskKey(resolved.apiKey)}\n`,
    );
    return 0;
  }

  const claude = await findBin('claude');
  if (!claude) {
    errorLine(
      'claude is not on PATH. The lanes drive Claude Code itself — install it first:\n' +
        '  npm i -g @anthropic-ai/claude-code',
    );
    return 127;
  }

  const childEnv: NodeJS.ProcessEnv = {
    ...env,
    ANTHROPIC_BASE_URL: resolved.baseUrl,
    ANTHROPIC_MODEL: resolved.model,
    ANTHROPIC_AUTH_TOKEN: resolved.apiKey,
  };
  if (isHeadless(forwarded)) childEnv.CADDIS_HEADLESS = '1';

  // execa, not child_process.spawn. On Windows `claude` resolves to `claude.cmd`, and
  // since the Node 18.20/20.12/22 security change spawning a .cmd with `shell: false`
  // fails outright with EINVAL — which is exactly what this lane did on the first live
  // run. `shell: true` would fix the spawn and break the arguments instead: a prompt
  // containing quotes or spaces gets re-parsed by cmd.exe. execa handles the shim
  // safely and passes arguments verbatim, which is why every other caddis adapter goes
  // through it (see src/util/exec.ts).
  const { execa } = await import('execa');
  try {
    const result = await execa(claude, forwarded, {
      env: childEnv,
      extendEnv: false,
      stdio: 'inherit',
      reject: false,
      windowsHide: true,
      // No timeout: this is an interactive session, however long the user wants it.
    });
    if (typeof result.exitCode === 'number') return result.exitCode;
    return result.failed ? 1 : 0;
  } catch (error) {
    errorLine(`could not start claude: ${error instanceof Error ? error.message : String(error)}`);
    return 127;
  }
}

/**
 * Entry point shared by all three lane binaries.
 *
 * `fixedProvider` is set for `claude-glm` / `claude-deepseek`, where every argument belongs
 * to claude. `claude-oss` leaves it undefined and takes the provider as its first argument.
 */
export async function laneMain(fixedProvider: string | undefined, argv: string[]): Promise<number> {
  let provider = fixedProvider;
  let args = argv;

  if (!fixedProvider) {
    const first = argv[0];
    if (!first || first.startsWith('-')) {
      errorLine(
        'usage: claude-oss <provider> [claude args...]\n' +
          '       providers: deepseek, glm, openrouter\n' +
          '       or use the direct lanes: claude-glm, claude-deepseek',
      );
      return 2;
    }
    provider = first;
    args = argv.slice(1);
  }

  return await launch({ provider, args });
}
