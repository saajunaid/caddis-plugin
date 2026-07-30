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
import { readFileSync, existsSync, mkdtempSync, cpSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import type { AgentAdapter, AgentStatus, Detection, DriveOptions, DriveResult, DriveAction, ExtrasStatus, StepResult } from './types.js';
import { run, formatCommand } from '../util/exec.js';
import { findBin } from '../util/which.js';
import { bundlePath } from '../util/pkg.js';

const BIN = 'agy';
const BUNDLE = 'antigravity-plugin';
const PLUGIN = 'caddis';

/** The optional long-tail plugin. Separate plugin, separate version line. */
const EXTRAS_BUNDLE = 'antigravity-plugin-extras';
const EXTRAS_PLUGIN = 'caddis-extras';

/** Where agy records an imported plugin's manifest. Overridable for tests. */
export function pluginManifestPath(home = os.homedir(), plugin: string = PLUGIN): string {
  return path.join(home, '.gemini', 'config', 'plugins', plugin, 'plugin.json');
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
  const extras = extrasStatusFromHome(home);

  if (version) {
    return { installed: true, version, source: shortenHome(manifestFile), extras };
  }
  if (existsSync(manifestFile)) {
    return {
      installed: true,
      source: shortenHome(manifestFile),
      extras,
      note: 'manifest present but unreadable / has no version',
    };
  }
  return {
    installed: false,
    source: shortenHome(manifestFile),
    extras,
    note: 'caddis plugin not imported into agy',
  };
}

/** The `caddis-extras` plugin's own install state. Absent is normal — it is opt-in. */
export function extrasStatusFromHome(home: string): ExtrasStatus {
  const manifestFile = pluginManifestPath(home, EXTRAS_PLUGIN);
  const version = readInstalledVersion(manifestFile);
  if (version) return { installed: true, version, source: shortenHome(manifestFile) };
  if (existsSync(manifestFile)) return { installed: true, source: shortenHome(manifestFile) };
  return { installed: false };
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

/**
 * agy's `plugin install <path>` parses "@" in its argument as a `plugin@marketplace`
 * qualifier — so it cannot accept a raw path containing one, which is exactly what
 * `npx @caddis/cli` always produces (npm installs scoped packages under a literal
 * `@scope/name/` directory). Symptom, verbatim: `agy plugin install
 * .../node_modules/@caddis/cli/bundles/antigravity-plugin` fails with
 * `Error: unknown marketplace: caddis\cli\bundles\antigravity-plugin` — agy split on
 * the first "@" and took everything after it as the marketplace name.
 *
 * Fix: if the resolved bundle path contains "@", stage a copy under a plain temp
 * directory (guaranteed "@"-free) and install from there instead. No-op for layouts
 * where this never triggers (npm link, a local checkout run from source).
 */
function stageForAgy(bundleDir: string): { installPath: string; cleanup: () => void } {
  if (!bundleDir.includes('@')) {
    return { installPath: bundleDir, cleanup: () => {} };
  }
  const staged = mkdtempSync(path.join(os.tmpdir(), 'caddis-agy-'));
  const dest = path.join(staged, path.basename(bundleDir));
  cpSync(bundleDir, dest, { recursive: true });
  return {
    installPath: dest,
    // Best-effort: a stray temp dir left behind is harmless clutter, not a failure.
    cleanup: () => {
      try {
        rmSync(staged, { recursive: true, force: true });
      } catch {
        /* ignore */
      }
    },
  };
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
  // `bundleDir` is tracked alongside `args` (not re-derived from it) so staging
  // never has to guess which array slot holds the path.
  const planned = [{ cmd: BIN, args: ['plugin', 'install', bundle], bundleDir: bundle }];

  // Extras is opt-in via --extras, BUT an extras install that already exists is
  // always kept current: leaving it to rot at an old version because the user
  // forgot a flag is worse than the 1 extra command. So --extras means "add it",
  // not "the only way it ever updates".
  const extrasInstalled = extrasStatusFromHome(os.homedir()).installed;
  if (options.extras === true || extrasInstalled) {
    const extrasBundle = bundlePath(EXTRAS_BUNDLE);
    if (extrasBundle) {
      planned.push({ cmd: BIN, args: ['plugin', 'install', extrasBundle], bundleDir: extrasBundle });
    } else if (options.extras === true) {
      return {
        ok: false,
        skipped: false,
        steps: [],
        message: `--extras requested but the ${EXTRAS_BUNDLE} bundle is missing from this package — reinstall @caddis/cli`,
      };
    }
  }

  if (options.dryRun) {
    return {
      ok: true,
      skipped: true,
      // Show the logical bundle path, not a staged temp copy that was never created.
      steps: planned.map((s) => ({ command: formatCommand(s.cmd, s.args), ok: true, code: null })),
      message: 'dry run — nothing executed',
    };
  }

  const cleanups: Array<() => void> = [];
  try {
    const steps: StepResult[] = [];
    for (const step of planned) {
      const command = formatCommand(step.cmd, step.args);
      // Substitute a staged copy only at execution time -- dry-run and the logged
      // `command` above stay in terms of the real, meaningful bundle path.
      const staged = stageForAgy(step.bundleDir);
      cleanups.push(staged.cleanup);
      const execArgs = [...step.args.slice(0, -1), staged.installPath];

      const result = await run(step.cmd, execArgs);
      steps.push({
        command,
        ok: result.ok,
        code: result.code,
        output: result.ok
          ? undefined
          : (result.stderr || result.stdout || result.failure || '').trim().split(/\r?\n/).slice(-3).join('\n'),
      });
      // Core must succeed before extras is attempted — extras is an add-on to it.
      if (!result.ok) {
        return { ok: false, skipped: false, steps, message: `\`${command}\` failed` };
      }
    }

    return { ok: true, skipped: false, steps };
  } finally {
    cleanups.forEach((fn) => fn());
  }
}

export const agyAdapter: AgentAdapter = {
  id: 'agy',
  name: 'agy (Antigravity)',
  supported: true,
  summary: 'install the caddis bundle shipped in this package (--extras adds caddis-extras)',
  detect,
  drive,
  status,
};
