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
import { readFileSync, readdirSync, existsSync, mkdtempSync, mkdirSync, cpSync, rmSync, renameSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import type { AgentAdapter, AgentStatus, Detection, DriveOptions, DriveResult, DriveAction, ExtrasStatus, StepResult } from './types.js';
import { run, formatCommand } from '../util/exec.js';
import { findBin } from '../util/which.js';
import { listAgyPids } from '../util/agyProcs.js';
import { bundlePath } from '../util/pkg.js';

const BIN = 'agy';
const BUNDLE = 'antigravity-plugin';
const PLUGIN = 'caddis';

/** The optional long-tail plugin. Separate plugin, separate version line. */
const EXTRAS_BUNDLE = 'antigravity-plugin-extras';
const EXTRAS_PLUGIN = 'caddis-extras';

/** The files an install must leave in the caddis plugin folder. agy refuses every edit without them. */
export const REQUIRED_PLUGIN_FILES = ['plugin.json', 'hooks.json', 'guard_agy.py'] as const;

/** Set to `1` to install while agy runs. Only for a person who knows no agy holds the plugin folder. */
const ALLOW_RUNNING_ENV = 'CADDIS_AGY_ALLOW_RUNNING';

/** The folder agy keeps the imported caddis plugin in. */
export function pluginDirFor(home = os.homedir(), plugin: string = PLUGIN): string {
  return path.join(home, '.gemini', 'config', 'plugins', plugin);
}

/** Which of the required files are missing from the caddis plugin folder. */
export function missingPluginFiles(home = os.homedir()): string[] {
  const dir = pluginDirFor(home);
  return REQUIRED_PLUGIN_FILES.filter((file) => !existsSync(path.join(dir, file)));
}

/**
 * Copy the installed plugin aside before an install, so a failed copy never leaves the user with an
 * empty plugin. Returns null when there is nothing to keep (a first install).
 */
function backupInstalledPlugin(
  home: string,
): { restore: () => string | null; cleanup: () => void; location: string } | null {
  const dir = pluginDirFor(home);
  if (!existsSync(dir)) return null;
  const holder = mkdtempSync(path.join(os.tmpdir(), 'caddis-agy-backup-'));
  const copy = path.join(holder, PLUGIN);
  cpSync(dir, copy, { recursive: true });
  // A failed restore must keep the backup: it is then the only whole copy of the plugin.
  let keep = false;
  return {
    location: copy,
    // Returns null when the old plugin is back, else the reason it could not be put back.
    restore: () => {
      try {
        rmSync(dir, { recursive: true, force: true });
        cpSync(copy, dir, { recursive: true });
        return null;
      } catch (error) {
        keep = true;
        return error instanceof Error ? error.message : String(error);
      }
    },
    cleanup: () => {
      if (keep) return;
      try {
        rmSync(holder, { recursive: true, force: true });
      } catch {
        /* a stray temp folder is clutter, not a failure */
      }
    },
  };
}

/**
 * Where a new plugin version waits while agy runs. Under ~/.caddis, NOT under agy's plugins/ folder (agy would
 * load it as a second plugin), and on the same volume as ~/.gemini so the swap is a rename.
 */
export function agyStagingDir(home = os.homedir(), plugin: string = PLUGIN): string {
  return path.join(home, '.caddis', 'agy-staged', plugin);
}

export type SwapReason = 'swapped' | 'stage-failed' | 'stage-rejected' | 'first-install' | 'in-use' | 'swap-failed';

export interface SwapOutcome {
  /** True when the new version is now the live plugin. */
  swapped: boolean;
  reason: SwapReason;
  /** A rejected stage, kept for inspection. */
  kept?: string;
  /** Where the new version waits: the live folder after a swap, the staging folder while staged, else null. */
  staged: string | null;
  detail: string;
}

/** "<type>: <message>" for an error: the errno code when there is one, else the error class. */
function errorText(error: unknown): string {
  if (!(error instanceof Error)) return String(error);
  const code = (error as NodeJS.ErrnoException).code;
  const kind = code ?? error.constructor.name;
  const message = code && error.message.startsWith(`${code}: `) ? error.message.slice(code.length + 2) : error.message;
  return `${kind}: ${message}`;
}

/** Milliseconds since the epoch for an old-copy stamp: Date.now() here, .NET ticks from sync.ps1. */
function stampMs(stamp: string): number {
  const n = Number(stamp);
  if (!Number.isFinite(n)) return -1;
  return n > 1e15 ? (n - 621_355_968_000_000_000) / 10_000 : n;
}

function isWhole(dir: string, required: readonly string[]): boolean {
  return existsSync(dir) && required.every((file) => existsSync(path.join(dir, file)));
}

/**
 * Run at the start of every refresh, before anything is staged. `<stage>.old-*` folders are what a swap moved
 * aside. If a run died between the two renames, or a rollback failed, the newest whole old copy is the ONLY
 * working plugin: when the live plugin is missing or not whole, rename that copy back and say so. Old copies are
 * swept only when the live plugin is whole. Returns a note when it restored something, else null.
 */
export function recoverInterruptedSwap(home: string, plugin: string, required: readonly string[]): string | null {
  const live = pluginDirFor(home, plugin);
  const staged = agyStagingDir(home, plugin);
  const parent = path.dirname(staged);
  const prefix = `${path.basename(staged)}.old-`;
  let olds: string[];
  try {
    olds = readdirSync(parent)
      .filter((name) => name.startsWith(prefix))
      .sort((x, y) => stampMs(y.slice(prefix.length)) - stampMs(x.slice(prefix.length)))
      .map((name) => path.join(parent, name));
  } catch {
    return null;
  }
  if (isWhole(live, required)) {
    for (const dir of olds) {
      try {
        rmSync(dir, { recursive: true, force: true });
      } catch {
        /* still held: the next refresh tries again */
      }
    }
    return null;
  }
  const source = olds.find((dir) => isWhole(dir, required));
  if (!source) return null;
  try {
    if (existsSync(live)) renameSync(live, `${staged}.broken-${Date.now()}`);
    mkdirSync(path.dirname(live), { recursive: true });
    renameSync(source, live);
    return `restored the previous plugin from ${source}`;
  } catch (error) {
    return `could not restore the previous plugin from ${source} (${errorText(error)}); it is kept there`;
  }
}

/**
 * Refresh a plugin under a running agy without `agy plugin install` (robustness audit #18).
 *
 * `agy plugin install` deletes the folder and then copies, so under a running agy the delete can succeed and the
 * copy fail, leaving an empty plugin (v1.3.136, 2026-10-08). This never deletes the live plugin first:
 *   1. copy the bundle to the staging folder and check the required files THERE. A bad stage is rejected before
 *      the live plugin is touched, and kept for inspection;
 *   2. rename the live folder aside. Windows refuses this while a process holds a file in it: then nothing has
 *      changed, and the new version stays staged for the next refresh;
 *   3. rename the staged folder into place; on failure, rename the old one back. Only then remove the old copy.
 * A first install only stages: agy itself must register a new plugin.
 */
export function stageAndSwap(
  bundleDir: string,
  home: string,
  plugin: string,
  required: readonly string[],
  rename: (from: string, to: string) => void = renameSync,
): SwapOutcome {
  const live = pluginDirFor(home, plugin);
  const staged = agyStagingDir(home, plugin);
  const recovered = recoverInterruptedSwap(home, plugin, required);
  const note = (detail: string): string => (recovered ? `${recovered}; ${detail}` : detail);
  try {
    rmSync(staged, { recursive: true, force: true });
    mkdirSync(path.dirname(staged), { recursive: true });
    cpSync(bundleDir, staged, { recursive: true });
  } catch (error) {
    return { swapped: false, reason: 'stage-failed', staged: null, detail: note(`staging failed (${errorText(error)})`) };
  }
  const missing = required.filter((file) => !existsSync(path.join(staged, file)));
  if (missing.length > 0) {
    return {
      swapped: false,
      reason: 'stage-rejected',
      staged: null,
      kept: staged,
      detail: note(`the staged copy lacks ${missing.join(', ')}; the live plugin was not touched`),
    };
  }
  if (!existsSync(live)) {
    return {
      swapped: false,
      reason: 'first-install',
      staged,
      detail: note('first install: agy must register the plugin with `agy plugin install`'),
    };
  }
  const old = `${staged}.old-${Date.now()}`;
  try {
    rename(live, old);
  } catch (error) {
    return {
      swapped: false,
      reason: 'in-use',
      staged,
      detail: note(`could not move the live plugin aside (${errorText(error)}); agy may be using it`),
    };
  }
  // Between these two renames there is NO plugin folder, for a few milliseconds. An agy hook call in that window
  // finds no guard_agy.py, and agy then refuses the edit ("restore or remove the hook reference to ...guard_agy.py",
  // seen with the empty plugin on 2026-10-08). That refuses one call; the next call finds the new folder.
  try {
    rename(staged, live);
  } catch (error) {
    const why = `the swap failed (${errorText(error)})`;
    try {
      rename(old, live);
      return { swapped: false, reason: 'swap-failed', staged: existsSync(staged) ? staged : null, detail: `${why}; the old plugin is back` };
    } catch (backError) {
      return {
        swapped: false,
        reason: 'swap-failed',
        staged: existsSync(staged) ? staged : null,
        detail: `${why}; putting the old plugin back FAILED (${errorText(backError)}), it is kept at ${old}`,
      };
    }
  }
  try {
    rmSync(old, { recursive: true, force: true });
  } catch {
    /* the next refresh sweeps it */
  }
  return { swapped: true, reason: 'swapped', staged: live, detail: note('swapped in by rename') };
}

/** What `caddis update` prints when a refresh under a running agy did not swap. */
export function runningAgyMessage(pids: string, plugin: string, outcome: SwapOutcome, alreadySwapped: string[] = []): string {
  let text = `agy is running (${pids}), so ${plugin} was not installed: ${outcome.detail}.`;
  if (alreadySwapped.length > 0) text += ` ${alreadySwapped.join(', ')} was already swapped in.`;
  if (outcome.kept) {
    text += ` Nothing was installed; the rejected copy is kept at ${outcome.kept}.`;
  } else if (outcome.staged && existsSync(outcome.staged)) {
    text += ` The new version is staged at ${outcome.staged}. Stop agy and run \`caddis update\` again to put it in place.`;
  } else {
    text += ' Nothing is staged. Stop agy and run `caddis update` again.';
  }
  // The override installs with `agy plugin install` under a running agy. It helps only where agy itself must act
  // (a first install), never when agy holds the files or the stage is bad.
  if (outcome.reason === 'first-install') {
    text += ` Or set ${ALLOW_RUNNING_ENV}=1 if you know no agy holds the plugin folder.`;
  }
  return text;
}

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

  const home = options.home ?? os.homedir();
  // An interrupted earlier swap first: restore its old copy if that is the only working plugin, else sweep.
  const recovered = [
    recoverInterruptedSwap(home, PLUGIN, REQUIRED_PLUGIN_FILES),
    recoverInterruptedSwap(home, EXTRAS_PLUGIN, ['plugin.json']),
  ].filter((note): note is string => note !== null);
  const withRecovery = (result: DriveResult): DriveResult =>
    recovered.length === 0 ? result : { ...result, message: [...recovered, result.message].filter(Boolean).join('; ') };

  // A running agy holds the plugin folder open. `agy plugin install` deletes it and then copies, so
  // the delete can succeed and the copy fail, leaving the plugin empty (v1.3.136, 2026-10-08).
  // So under a running agy: stage the new version and swap it in by rename, never install.
  if (process.env[ALLOW_RUNNING_ENV] !== '1') {
    const running = await listAgyPids();
    if (running.length > 0) return withRecovery(swapUnderRunningAgy(planned, bundle, home, running));
  }

  const backup = backupInstalledPlugin(home);
  const cleanups: Array<() => void> = [];
  if (backup) cleanups.push(backup.cleanup);
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
      // The core plugin must come out whole. If it did not, put the old one back (or say there was none).
      if (step.bundleDir === bundle) {
        const missing = missingPluginFiles(home);
        if (missing.length > 0) {
          let outcome = 'there was nothing to restore';
          if (backup) {
            const failure = backup.restore();
            outcome =
              failure === null
                ? 'the previous plugin was restored'
                : `the restore FAILED (${failure}); the old plugin is kept at ${backup.location}`;
          }
          steps.push({ command, ok: false, code: result.code, output: `missing after the install: ${missing.join(', ')}` });
          return {
            ok: false,
            skipped: false,
            steps,
            message:
              `the caddis plugin is incomplete after the install (missing ${missing.join(', ')}); ` +
              outcome,
          };
        }
      }
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

    // A stage left by an earlier refresh under a running agy is older than what is installed now.
    for (const plugin of [PLUGIN, EXTRAS_PLUGIN]) {
      try {
        rmSync(agyStagingDir(home, plugin), { recursive: true, force: true });
      } catch {
        /* a stale stage is clutter, not a failure */
      }
    }
    return withRecovery({ ok: true, skipped: false, steps });
  } finally {
    cleanups.forEach((fn) => fn());
  }
}

function swapUnderRunningAgy(
  planned: Array<{ bundleDir: string }>,
  bundle: string,
  home: string,
  running: number[],
): DriveResult {
  const pids = `PID ${running.join(', ')}`;
  const steps: StepResult[] = [];
  const swapped: string[] = [];
  for (const step of planned) {
    const core = step.bundleDir === bundle;
    const plugin = core ? PLUGIN : EXTRAS_PLUGIN;
    const outcome = stageAndSwap(step.bundleDir, home, plugin, core ? REQUIRED_PLUGIN_FILES : ['plugin.json']);
    steps.push({
      command: `stage ${step.bundleDir} and swap it into ${pluginDirFor(home, plugin)}`,
      ok: outcome.swapped,
      code: null,
      output: outcome.swapped ? undefined : outcome.detail,
    });
    if (!outcome.swapped) {
      return { ok: false, skipped: false, steps, message: runningAgyMessage(pids, plugin, outcome, swapped) };
    }
    swapped.push(plugin);
  }
  return {
    ok: true,
    skipped: false,
    steps,
    message: `agy is running (${pids}): the new plugin was staged and swapped in by rename; new agy sessions load it.`,
  };
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
