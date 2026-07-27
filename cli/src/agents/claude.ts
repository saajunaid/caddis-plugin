/**
 * Claude Code adapter.
 *
 * Native mechanism: the plugin marketplace. We drive it, we do not replace it.
 *   update = `claude plugin marketplace update caddis`
 *          + `claude plugin update caddis@caddis`
 *   status = parse `claude plugin list` for the caddis entry's version.
 *
 * Note that Claude Code ALSO auto-updates caddis through its marketplace on
 * its own schedule. Driving it here just makes "update everything now"
 * deterministic and gives doctor a version to compare against the pool.
 */
import type { AgentAdapter, AgentStatus, Detection, DriveOptions, DriveResult, DriveAction, StepResult } from './types.js';
import { run, formatCommand } from '../util/exec.js';
import { findBin } from '../util/which.js';

const BIN = 'claude';
const MARKETPLACE = 'caddis';
const PLUGIN = 'caddis@caddis';

/**
 * `claude plugin list` prints a human block per plugin:
 *
 *     ❯ caddis@caddis
 *       Version: 1.3.38
 *       Scope: user
 *       Status: ✔ enabled
 *
 * There is no --json flag as of Claude Code 2.x, so parse the block. Match the
 * header on the plugin NAME only (`caddis`, not `caddis-extras`) and take the
 * first Version line after it — keyed to the header so a neighbouring plugin's
 * version can never be misread as ours.
 */
export function parsePluginList(stdout: string, plugin = PLUGIN): { version?: string; disabled?: boolean } | null {
  const wanted = plugin.split('@')[0] ?? plugin;

  for (const [name, body] of pluginBlocks(stdout)) {
    if (name !== wanted) continue;
    const entry: { version?: string; disabled?: boolean } = {};
    for (const line of body) {
      const version = line.match(/^\s*Version\s*:\s*(.+?)\s*$/i);
      // Claude Code prints `Version: unknown` for marketplace plugins with no
      // manifest version — that is "installed, version unavailable", not "1.0".
      if (version?.[1] && entry.version === undefined) {
        entry.version = version[1] === 'unknown' ? undefined : version[1];
      }
      const status = line.match(/^\s*Status\s*:\s*(.+?)\s*$/i);
      if (status?.[1]) entry.disabled = /disabled/i.test(status[1]);
    }
    return entry;
  }
  return null;
}

/**
 * Split `claude plugin list` into (pluginName, fieldLines) pairs.
 *
 * A block header is a line whose only content is `<name>@<marketplace>`,
 * optionally preceded by a bullet glyph. Everything until the next header is
 * that plugin's body. Keying on the header (rather than scanning for the next
 * `Version:`) is what stops `caddis-extras`' version being read as `caddis`'.
 */
function* pluginBlocks(stdout: string): Generator<[string, string[]]> {
  const HEADER = /^\s*(?:\S\s+)?([A-Za-z0-9._-]+)@([A-Za-z0-9._-]+)\s*$/;
  let current: [string, string[]] | null = null;

  for (const line of stdout.split(/\r?\n/)) {
    const header = line.match(HEADER);
    if (header?.[1]) {
      if (current) yield current;
      current = [header[1], []];
    } else if (current) {
      current[1].push(line);
    }
  }
  if (current) yield current;
}

async function detect(): Promise<Detection> {
  const path = await findBin(BIN);
  if (!path) {
    return { present: false, note: 'no `claude` binary on PATH' };
  }
  const version = await run(BIN, ['--version'], { timeout: 20_000 });
  return {
    present: true,
    path,
    agentVersion: version.ok ? (version.stdout.trim().split(/\s+/)[0] || undefined) : undefined,
    note: version.ok ? undefined : 'binary found but `claude --version` failed',
  };
}

async function status(): Promise<AgentStatus> {
  const detected = await detect();
  if (!detected.present) return { installed: false, note: 'agent not installed' };

  const listed = await run(BIN, ['plugin', 'list'], { timeout: 60_000 });
  if (!listed.ok) {
    return {
      installed: false,
      source: '`claude plugin list`',
      note: `could not read plugin list (${listed.failure ?? `exit ${listed.code}`})`,
    };
  }
  const entry = parsePluginList(listed.stdout);
  if (!entry) {
    return { installed: false, source: '`claude plugin list`', note: 'caddis plugin not installed' };
  }
  return {
    installed: true,
    version: entry.version,
    disabled: entry.disabled,
    source: '`claude plugin list`',
    note: entry.version ? undefined : 'installed but the version is not reported',
  };
}

function steps(action: DriveAction): { cmd: string; args: string[] }[] {
  if (action === 'install') {
    // `plugin install` is idempotent for an already-installed plugin and is
    // what a first run needs; the marketplace must be refreshed first or the
    // install resolves against a stale cached index.
    return [
      { cmd: BIN, args: ['plugin', 'marketplace', 'update', MARKETPLACE] },
      { cmd: BIN, args: ['plugin', 'install', PLUGIN] },
    ];
  }
  return [
    { cmd: BIN, args: ['plugin', 'marketplace', 'update', MARKETPLACE] },
    { cmd: BIN, args: ['plugin', 'update', PLUGIN] },
  ];
}

async function drive(action: DriveAction, options: DriveOptions): Promise<DriveResult> {
  const detected = await detect();
  if (!detected.present) {
    return { ok: true, skipped: true, steps: [], message: 'Claude Code not installed — skipped' };
  }

  const planned = steps(action);
  if (options.dryRun) {
    return {
      ok: true,
      skipped: true,
      steps: planned.map((step) => ({ command: formatCommand(step.cmd, step.args), ok: true, code: null })),
      message: 'dry run — nothing executed',
    };
  }

  const results: StepResult[] = [];
  for (const step of planned) {
    const command = formatCommand(step.cmd, step.args);
    const result = await run(step.cmd, step.args);
    results.push({
      command,
      ok: result.ok,
      code: result.code,
      output: result.ok ? undefined : tail(result.stderr || result.stdout || result.failure || ''),
    });
    // The marketplace refresh is advisory: a transient network failure there
    // should not stop the update itself from being attempted.
    if (!result.ok && step.args[1] !== 'marketplace') {
      return { ok: false, skipped: false, steps: results, message: `\`${command}\` failed` };
    }
  }
  return { ok: true, skipped: false, steps: results };
}

function tail(text: string, lines = 3): string {
  return text.trim().split(/\r?\n/).slice(-lines).join('\n');
}

export const claudeAdapter: AgentAdapter = {
  id: 'claude',
  name: 'Claude Code',
  supported: true,
  summary: 'refresh the caddis marketplace, then update the caddis plugin',
  detect,
  drive,
  status,
};
