/**
 * The Python collector source (R22, R23).
 *
 * Runs the bundled `caddis_hub_collect.py --repos ... --json` and keeps the last good
 * data. The collector reports a fingerprint per repo. A repo's cached data is replaced
 * only when its fingerprint differs. Stale after 3 minutes without a good run.
 */
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { bundlePath, packageInfo } from '../../util/pkg.js';
import { findBin } from '../../util/which.js';
import { errorLine } from '../../util/log.js';
import { withTimeout } from '../bounded.js';
import type { PrHead } from '../prHead.js';
import { spawnBounded, type SpawnFn } from '../spawn.js';

export const COLLECTOR_SCHEMA = 1;
export const STALE_AFTER_MS = 3 * 60_000;
const RUN_TIMEOUT_MS = 60_000;

export type Slot = Record<string, unknown>;
export interface RepoData {
  path: string;
  fingerprint?: string;
  unchanged?: boolean;
  error?: string;
  roadmaps?: Slot;
  plans?: Slot;
  relays?: Slot;
}
export interface CollectorData {
  schema: number;
  generated_at: string;
  repos: RepoData[];
  spend: Slot;
  guide: Slot;
}
export interface CollectorState {
  ok: boolean;
  last_ok_at: string | null;
  last_error: string | null;
  stale: boolean;
  update_needed: boolean;
  data: CollectorData | null;
}
export interface CollectorSource {
  refresh(): Promise<void>;
  get(): CollectorState;
}
export interface CollectorOptions {
  repos: () => string[];
  python?: string;
  scriptPath?: string;
  now?: () => number;
  spawn?: SpawnFn;
  /** Where a short note goes. Default: stderr. */
  log?: (text: string) => void;
  prs?: () => Record<string, PrHead[]>;
  prsFile?: string;
}

/** The script in the npm bundle, or the repo's `scripts/` folder in a dev checkout, or the mirror's bundles/ folder. */
export function defaultScriptPath(): string {
  const name = 'caddis_hub_collect.py';
  const bundle = bundlePath('antigravity-plugin', { requireManifest: false });
  if (bundle) {
    const shipped = path.join(bundle, 'scripts', name);
    if (existsSync(shipped)) return shipped;
  }
  // A checkout before `npm run build`: the repo's scripts/, or in the mirror the bundles/ folder beside cli/.
  const root = path.join(packageInfo().root, '..');
  const repoScript = path.join(root, 'scripts', name);
  const mirrorScript = path.join(root, 'bundles', 'antigravity-plugin', 'scripts', name);
  return !existsSync(repoScript) && existsSync(mirrorScript) ? mirrorScript : repoScript;
}

/** A PATH lookup reads the disk; a dead network folder on PATH must not hold the collector forever. */
const FIND_TIMEOUT_MS = 10_000;
const find = (name: string): Promise<string | null> => withTimeout(findBin(name), FIND_TIMEOUT_MS, `finding ${name}`);

export async function resolvePython(): Promise<{ cmd: string; pre: string[] } | null> {
  const py = await find('python');
  if (py) return { cmd: py, pre: [] };
  if (process.platform === 'win32') {
    const launcher = await find('py');
    if (launcher) return { cmd: launcher, pre: ['-3'] };
    return null;
  }
  const py3 = await find('python3');
  return py3 ? { cmd: py3, pre: [] } : null;
}

export function createCollectorSource(opts: CollectorOptions): CollectorSource {
  const now = opts.now ?? Date.now;
  const spawn = opts.spawn ?? spawnBounded;
  const log = opts.log ?? errorLine;
  const cache = new Map<string, RepoData>();
  let spend: Slot | null = null;
  let guide: Slot | null = null;
  let schema = COLLECTOR_SCHEMA;
  let generatedAt = '';
  let lastOkAt: number | null = null;
  let lastError: string | null = null;
  let updateNeeded = false;
  let lastRunOk = false;
  let running: Promise<void> | null = null;
  // An older plugin script exits 2 on `--known`. Once seen, the hub stops sending it.
  let knownUnsupported = false;
  let prsFileUnsupported = false;
  // Same for `--done-known` (done plans cached by tree hash).
  let doneKnownUnsupported = false;

  const fail = (message: string): void => {
    lastError = message;
    lastRunOk = false;
  };

  /**
   * Done plans ride in the plans slot (`plans.done`). `{tree, unchanged: true}` means "same tree as `--done-known`":
   * keep the old list when its tree matches. With no usable old list the slot holds an error and no tree, so the next
   * run asks for the full list.
   */
  const withDone = (entry: RepoData, old: RepoData | undefined): RepoData => {
    const plans = entry.plans;
    const done = plans?.done as Slot | undefined;
    if (!plans || !done || typeof done !== 'object' || done.unchanged !== true) return entry;
    const oldDone = old?.error === undefined ? (old?.plans?.done as Slot | undefined) : undefined;
    const reuse = oldDone && typeof done.tree === 'string' && oldDone.tree === done.tree && Array.isArray(oldDone.plans);
    if (reuse) return { ...entry, plans: { ...plans, done: oldDone } };
    // No fingerprint: the next run sends no `--known` for this repo and `ingest` takes the fresh entry.
    return { ...entry, fingerprint: undefined, plans: { ...plans, done: { error: 'done plans not cached' } } };
  };

  const ingest = (parsed: unknown, wanted: string[]): void => {
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return fail('collector output is not a JSON object');
    const out = parsed as Record<string, unknown>;
    const version = out.schema;
    if (typeof version !== 'number' || !Number.isInteger(version) || version < COLLECTOR_SCHEMA - 1) {
      return fail(`collector output has an unusable schema: ${String(version)}`);
    }
    if (version > COLLECTOR_SCHEMA) {
      updateNeeded = true;
      return fail(`collector schema ${version} is newer than this hub (${COLLECTOR_SCHEMA}): update the hub`);
    }
    if (!Array.isArray(out.repos)) return fail('collector output has no repos list');
    updateNeeded = false;
    schema = version;
    generatedAt = typeof out.generated_at === 'string' ? out.generated_at : '';
    const keep = new Set(wanted);
    for (const key of [...cache.keys()]) if (!keep.has(key)) cache.delete(key);
    for (const entry of out.repos as RepoData[]) {
      if (!entry || typeof entry.path !== 'string' || !keep.has(entry.path)) continue;
      if (entry.unchanged === true) continue;
      const old = cache.get(entry.path);
      if (entry.error !== undefined || entry.fingerprint === undefined) {
        // A failed repo keeps its last good data. A new error entry is stored only first time.
        if (!old || old.error !== undefined) cache.set(entry.path, entry);
        continue;
      }
      if (!old || old.error !== undefined || old.fingerprint !== entry.fingerprint) cache.set(entry.path, withDone(entry, old));
    }
    const keepOrError = (next: unknown, old: Slot | null): Slot | null => {
      if (!next || typeof next !== 'object') return old;
      const slot = next as Slot;
      if ('error' in slot && old && !('error' in old)) return old;
      return slot;
    };
    spend = keepOrError(out.spend, spend);
    guide = keepOrError(out.guide, guide);
    lastOkAt = now();
    lastError = null;
    lastRunOk = true;
  };

  const run = async (): Promise<void> => {
    const repos = opts.repos();
    let cmd = opts.python;
    let pre: string[] = [];
    if (!cmd) {
      const found = await resolvePython();
      if (!found) return fail('python was not found (tried python, then py -3)');
      cmd = found.cmd;
      pre = found.pre;
    }
    const script = opts.scriptPath ?? defaultScriptPath();
    const known = [...cache.values()]
      .filter((r) => !knownUnsupported && r.error === undefined && typeof r.fingerprint === 'string' && repos.includes(r.path))
      .map((r) => `${r.path}=${r.fingerprint}`);
    // Only a cached done tree is sent. A restarted hub has no cache, so it gets the full list.
    const doneKnown = [...cache.values()]
      .filter((r) => !knownUnsupported && !doneKnownUnsupported && r.error === undefined && repos.includes(r.path))
      .flatMap((r) => {
        const tree = (r.plans?.done as Slot | undefined)?.tree;
        return typeof tree === 'string' && tree ? [`${r.path}=${tree}`] : [];
      });
    let prsFlag: string[] = [];
    if (opts.prs && opts.prsFile && repos.length > 0 && !prsFileUnsupported) {
      try {
        mkdirSync(path.dirname(opts.prsFile), { recursive: true });
        writeFileSync(opts.prsFile, JSON.stringify({ schema: 1, repos: opts.prs() }));
        prsFlag = ['--prs-file', opts.prsFile];
      } catch {
        /* leave the flag out for this run */
      }
    }
    // The collector needs `--repos`. With none, ask for spend and guide on a path that does not exist.
    const build = (): string[] =>
      repos.length
        ? [
            ...pre,
            script,
            '--repos',
            ...repos,
            ...(known.length ? ['--known', ...known] : []),
            ...(doneKnown.length ? ['--done-known', ...doneKnown] : []),
            ...prsFlag,
            '--json',
          ]
        : [...pre, script, '--repos', path.join(os.tmpdir(), 'caddis-hub-no-repos'), '--only', 'spend,guide', '--json'];
    let result = await spawn(cmd, build(), { timeoutMs: RUN_TIMEOUT_MS });
    // An old script rejects a flag it does not know with exit 2. Drop that flag, remember it, run again.
    for (let attempt = 0; attempt < 3 && !result.ok; attempt += 1) {
      if (prsFlag.length && /unrecognized arguments:.*--prs-file/.test(result.stderr)) {
        prsFileUnsupported = true;
        prsFlag = [];
        log('caddis hub: the collector script does not know --prs-file (old plugin); branch progress is off. Update the plugin.');
      } else if (result.code === 2 && known.length && repos.length && /unrecognized arguments:.*--known/.test(result.stderr)) {
        knownUnsupported = true;
        known.length = 0;
        doneKnown.length = 0;
        log('caddis hub: the collector script does not know --known (old plugin); sending full runs. Update the plugin.');
      } else if (result.code === 2 && doneKnown.length && /unrecognized arguments:.*--done-known/.test(result.stderr)) {
        doneKnownUnsupported = true;
        doneKnown.length = 0;
        log('caddis hub: the collector script does not know --done-known (old plugin); done plans are sent in full. Update the plugin.');
      } else break;
      result = await spawn(cmd, build(), { timeoutMs: RUN_TIMEOUT_MS });
    }
    if (result.timedOut) return fail(`collector timed out after ${RUN_TIMEOUT_MS / 1000} s`);
    if (!result.ok) {
      const detail = (result.stderr || result.stdout).trim().slice(0, 500);
      return fail(`collector failed (exit ${result.code ?? 'none'})${detail ? `: ${detail}` : ''}`);
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(result.stdout);
    } catch (error) {
      return fail(`collector output is not valid JSON: ${error instanceof Error ? error.message : String(error)}`);
    }
    ingest(parsed, repos);
  };

  return {
    refresh(): Promise<void> {
      if (!running) {
        running = run()
          .catch((error) => fail(error instanceof Error ? error.message : String(error)))
          .finally(() => {
            running = null;
          });
      }
      return running;
    },
    get(): CollectorState {
      const hasData = lastOkAt !== null;
      return {
        ok: lastRunOk,
        last_ok_at: lastOkAt === null ? null : new Date(lastOkAt).toISOString(),
        last_error: lastError,
        stale: lastOkAt === null || now() - lastOkAt > STALE_AFTER_MS,
        update_needed: updateNeeded,
        data: hasData
          ? { schema, generated_at: generatedAt, repos: [...cache.values()], spend: spend ?? {}, guide: guide ?? {} }
          : null,
      };
    },
  };
}
