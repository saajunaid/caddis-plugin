/**
 * agy (Antigravity) adapter.
 *
 * agy has NO marketplace and no native auto-update — it installs a plugin from
 * a directory on disk. That makes it the highest-value adapter: without this
 * CLI the only way to move agy forward is a manual `agy plugin install` against
 * a checkout the user has to clone and keep fresh themselves.
 *
 *   install/update = `agy plugin install <shipped antigravity-plugin bundle>`
 *   status         = read ~/.gemini/config/plugins/caddis/plugin.json
 *
 * Because the bundle ships INSIDE this npm package, `npx @caddis/cli update`
 * needs no network beyond npm itself and the installed version is pinned to
 * the CLI version — "the caddis you installed IS the pool you get".
 */
import { readFileSync, existsSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import type { AgentAdapter, AgentStatus, Detection, DriveOptions, DriveResult, DriveAction, StepResult } from './types.js';
import { run, formatCommand } from '../util/exec.js';
import { findBin } from '../util/which.js';
import { bundlePath } from '../util/pkg.js';

const BIN = 'agy';
const BUNDLE = 'antigravity-plugin';
const PLUGIN = 'caddis';

/** Where agy records an imported plugin's manifest. Overridable for tests. */
export function pluginManifestPath(home = os.homedir()): string {
  return path.join(home, '.gemini', 'config', 'plugins', PLUGIN, 'plugin.json');
}

async function detect(): Promise<Detection> {
  const binPath = await findBin(BIN);
  if (!binPath) {
    return { present: false, note: 'no `agy` binary on PATH' };
  }
  const version = await run(BIN, ['--version'], { timeout: 20_000 });
  return {
    present: true,
    path: binPath,
    agentVersion: version.ok ? (version.stdout.trim().split(/\s+/).pop() || undefined) : undefined,
    note: version.ok ? undefined : 'binary found but `agy --version` failed',
  };
}

/** Read the installed caddis version out of agy's own plugin manifest. */
export function readInstalledVersion(manifestFile: string): string | null {
  if (!existsSync(manifestFile)) return null;
  try {
    const parsed = JSON.parse(readFileSync(manifestFile, 'utf8'));
    return typeof parsed?.version === 'string' ? parsed.version : null;
  } catch {
    return null;
  }
}

/**
 * Split out from `status()` so the home directory is an argument rather than a
 * hidden `os.homedir()` call — otherwise the only way to test it is to spy on
 * a node builtin.
 */
export function statusFromHome(home: string): AgentStatus {
  const manifestFile = pluginManifestPath(home);
  const version = readInstalledVersion(manifestFile);
  if (version) {
    return { installed: true, version, source: shortenHome(manifestFile) };
  }
  if (existsSync(manifestFile)) {
    return {
      installed: true,
      source: shortenHome(manifestFile),
      note: 'manifest present but unreadable / has no version',
    };
  }
  return { installed: false, source: shortenHome(manifestFile), note: 'caddis plugin not imported into agy' };
}

async function status(): Promise<AgentStatus> {
  const detected = await detect();
  if (!detected.present) return { installed: false, note: 'agent not installed' };
  return statusFromHome(os.homedir());
}

function shortenHome(target: string): string {
  const home = os.homedir();
  return target.startsWith(home) ? path.join('~', target.slice(home.length)) : target;
}

async function drive(_action: DriveAction, options: DriveOptions): Promise<DriveResult> {
  const detected = await detect();
  if (!detected.present) {
    return { ok: true, skipped: true, steps: [], message: 'agy not installed — skipped' };
  }

  const bundle = bundlePath(BUNDLE);
  if (!bundle) {
    return {
      ok: false,
      skipped: false,
      steps: [],
      message: `the ${BUNDLE} bundle is missing from this package — reinstall @caddis/cli`,
    };
  }

  // install is idempotent in agy: re-installing over an existing import is the
  // update path, so `install` and `update` drive the same command.
  const step = { cmd: BIN, args: ['plugin', 'install', bundle] };
  const command = formatCommand(step.cmd, step.args);

  if (options.dryRun) {
    return { ok: true, skipped: true, steps: [{ command, ok: true, code: null }], message: 'dry run — nothing executed' };
  }

  const result = await run(step.cmd, step.args);
  const stepResult: StepResult = {
    command,
    ok: result.ok,
    code: result.code,
    output: result.ok ? undefined : (result.stderr || result.stdout || result.failure || '').trim().split(/\r?\n/).slice(-3).join('\n'),
  };
  return {
    ok: result.ok,
    skipped: false,
    steps: [stepResult],
    message: result.ok ? undefined : `\`${command}\` failed`,
  };
}

export const agyAdapter: AgentAdapter = {
  id: 'agy',
  name: 'agy (Antigravity)',
  supported: true,
  summary: 'install the caddis bundle shipped in this package',
  detect,
  drive,
  status,
};
