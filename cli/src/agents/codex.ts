/**
 * OpenAI Codex adapter.
 *
 * Codex 0.159.0+ provides a native plugin marketplace:
 *   install = `codex plugin marketplace add https://github.com/saajunaid/caddis-plugin`
 *           + `codex plugin add caddis-codex@caddis`
 *   update  = `codex plugin marketplace upgrade caddis`
 *           + `codex plugin add caddis-codex@caddis`
 *   status  = parse `codex plugin list` for `caddis-codex@caddis`
 *
 * This adapter drives the vendor CLI commands rather than copying files into
 * ~/.codex/skills/. If an older caddis version left files in ~/.codex/skills/caddis/,
 * verified by the .caddis-version marker, they are removed to avoid duplication.
 *
 * WHAT THIS ADAPTER DELIBERATELY WILL NOT DO. It never writes `~/.codex/config.toml`.
 */
import { existsSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import type {
  AgentAdapter,
  AgentStatus,
  Detection,
  DriveAction,
  DriveOptions,
  DriveResult,
  StepResult,
} from './types.js';
import { run, formatCommand } from '../util/exec.js';
import { findBin } from '../util/which.js';

const BIN = 'codex';
const MARKETPLACE_URL = 'https://github.com/saajunaid/caddis-plugin';
const MARKETPLACE = 'caddis';
const PLUGIN = 'caddis-codex@caddis';

/** Legacy skills directory from older caddis file-drop installs. */
export function caddisSkillsDir(home = os.homedir()): string {
  return path.join(home, '.codex', 'skills', 'caddis');
}

/** Marker file proving caddis owned the legacy skills directory. */
export function versionFile(home = os.homedir()): string {
  return path.join(caddisSkillsDir(home), '.caddis-version');
}

async function detect(): Promise<Detection> {
  const binPath = await findBin(BIN);
  if (!binPath) {
    const configDir = path.join(os.homedir(), '.codex');
    if (existsSync(configDir)) {
      return { present: false, path: configDir, note: 'no `codex` binary on PATH, but ~/.codex exists' };
    }
    return { present: false, note: 'no `codex` binary on PATH' };
  }
  const version = await run(BIN, ['--version'], { timeout: 20_000 });
  return {
    present: true,
    path: binPath,
    agentVersion: version.ok ? (version.stdout.trim().split(/\s+/).pop() || undefined) : undefined,
    note: version.ok ? undefined : 'binary found but `codex --version` failed',
  };
}

function shortenHome(target: string): string {
  const home = os.homedir();
  return target.startsWith(home) ? path.join('~', target.slice(home.length)) : target;
}

/**
 * Parse `codex plugin list` output for the caddis-codex plugin entry.
 *
 * Output row format:
 *   caddis-codex@caddis   installed, enabled  1.3.125  <source>
 */
export function parseCodexPluginList(
  stdout: string,
  plugin = PLUGIN,
): { installed: boolean; version?: string; disabled?: boolean } | null {
  const wanted = plugin.toLowerCase();
  for (const rawLine of stdout.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line.toLowerCase().startsWith(wanted)) continue;

    const rest = line.slice(wanted.length).trim();
    if (/^not installed/i.test(rest)) {
      return { installed: false };
    }

    const match = rest.match(/^installed,\s*(enabled|disabled)(?:\s+([^\s]+))?/i);
    if (match) {
      return {
        installed: true,
        disabled: match[1]?.toLowerCase() === 'disabled',
        version: match[2],
      };
    }

    const simpleMatch = rest.match(/^installed(?:\s+([^\s]+))?/i);
    if (simpleMatch) {
      return {
        installed: true,
        disabled: false,
        version: simpleMatch[1],
      };
    }
  }
  return null;
}

async function status(): Promise<AgentStatus> {
  const detected = await detect();
  if (!detected.present) return { installed: false, note: 'agent not installed' };

  const listed = await run(BIN, ['plugin', 'list'], { timeout: 60_000 });
  if (!listed.ok) {
    return {
      installed: false,
      source: '`codex plugin list`',
      note: `could not read plugin list (${listed.failure ?? `exit ${listed.code}`})`,
    };
  }
  const entry = parseCodexPluginList(listed.stdout);
  if (!entry || !entry.installed) {
    return { installed: false, source: '`codex plugin list`', note: 'caddis-codex plugin not installed' };
  }
  return {
    installed: true,
    version: entry.version,
    disabled: entry.disabled,
    source: '`codex plugin list`',
    note: entry.version ? undefined : 'installed but the version is not reported',
  };
}

function steps(action: DriveAction): { cmd: string; args: string[] }[] {
  if (action === 'install') {
    return [
      { cmd: BIN, args: ['plugin', 'marketplace', 'add', MARKETPLACE_URL] },
      { cmd: BIN, args: ['plugin', 'add', PLUGIN] },
    ];
  }
  return [
    { cmd: BIN, args: ['plugin', 'marketplace', 'upgrade', MARKETPLACE] },
    { cmd: BIN, args: ['plugin', 'add', PLUGIN] },
  ];
}

async function drive(action: DriveAction, options: DriveOptions): Promise<DriveResult> {
  const detected = await detect();
  if (!detected.present) {
    return { ok: true, skipped: true, steps: [], message: 'codex not installed — skipped' };
  }

  const home = os.homedir();
  const legacyDir = caddisSkillsDir(home);
  const legacyMarker = versionFile(home);
  const hasLegacyMarker = existsSync(legacyMarker);

  const planned = steps(action);
  const removalCommand = `remove legacy ${shortenHome(legacyDir)}`;

  if (options.dryRun) {
    const plannedSteps: StepResult[] = planned.map((step) => (
      { command: formatCommand(step.cmd, step.args), ok: true, code: null }
    ));
    if (hasLegacyMarker) {
      // After the plugin install, never before: a failed install must not leave nothing behind.
      plannedSteps.push({ command: removalCommand, ok: true, code: null });
    }
    return { ok: true, skipped: true, steps: plannedSteps, message: 'dry run — nothing executed' };
  }

  const results: StepResult[] = [];

  for (const step of planned) {
    const command = formatCommand(step.cmd, step.args);
    const result = await run(step.cmd, step.args);

    const isMarketplaceAdd = step.args[1] === 'marketplace' && step.args[2] === 'add';
    const isMarketplaceUpgrade = step.args[1] === 'marketplace' && step.args[2] === 'upgrade';

    let ok = result.ok;
    let code = result.code;
    if (!ok && isMarketplaceAdd) {
      const output = `${result.stdout}\n${result.stderr}`;
      if (/already (exists|added|configured|installed)/i.test(output)) {
        ok = true;
        code = 0;
      }
    }

    results.push({
      command,
      ok,
      code,
      output: ok ? undefined : tail(result.stderr || result.stdout || result.failure || ''),
    });

    // The marketplace refresh is advisory, as it is for Claude Code: a network failure there must
    // not stop the plugin step from being tried (it installs what the cached marketplace has).
    if (!ok && !isMarketplaceUpgrade) {
      return { ok: false, skipped: false, steps: results, message: `\`${command}\` failed` };
    }
  }

  // The plugin is installed. Only now remove the old file-drop copy that caddis itself wrote (the
  // marker proves it), so the same skills do not show up twice. A failed removal is reported, and
  // does not undo the install.
  if (hasLegacyMarker) {
    try {
      rmSync(legacyDir, { recursive: true, force: true });
      results.push({ command: removalCommand, ok: true, code: 0 });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      results.push({ command: removalCommand, ok: false, code: null, output: message });
    }
  }

  const notes: string[] = [];
  if (!hasLegacyMarker && existsSync(legacyDir)) {
    notes.push(
      `${shortenHome(legacyDir)} exists but caddis did not write it (no version marker), so it was left in place; Codex may list the same skills twice. Remove it by hand if you do not need it.`,
    );
  }
  if (options.extras) {
    notes.push('--extras has no Codex plugin; core only');
  }
  return {
    ok: true,
    skipped: false,
    steps: results,
    ...(notes.length ? { message: notes.join(' ') } : {}),
  };
}

function tail(text: string, lines = 3): string {
  return text.trim().split(/\r?\n/).slice(-lines).join('\n');
}

export const codexAdapter: AgentAdapter = {
  id: 'codex',
  name: 'Codex',
  supported: true,
  summary: 'install the caddis-codex plugin from the caddis marketplace (config.toml never merged)',
  detect,
  drive,
  status,
};
