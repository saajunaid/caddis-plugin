/**
 * The Python collector source (R22, R23).
 *
 * Runs the bundled `caddis_hub_collect.py --repos ... --json` and keeps the last good
 * data. The collector reports a fingerprint per repo. A repo's cached data is replaced
 * only when its fingerprint differs. Stale after 3 minutes without a good run.
 */
import { existsSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { bundlePath, packageInfo } from '../../util/pkg.js';
import { findBin } from '../../util/which.js';
import { errorLine } from '../../util/log.js';
import { withTimeout } from '../bounded.js';
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

  const fail = (message: string): void => {
    lastError = message;
    lastRunOk = false;
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
      if (!old || old.error !== undefined || old.fingerprint !== entry.fingerprint) cache.set(entry.path, entry);
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
    // The collector needs `--repos`. With none, ask for spend and guide on a path that does not exist.
    const args = repos.length
      ? known.length
        ? [...pre, script, '--repos', ...repos, '--known', ...known, '--json']
        : [...pre, script, '--repos', ...repos, '--json']
      : [...pre, script, '--repos', path.join(os.tmpdir(), 'caddis-hub-no-repos'), '--only', 'spend,guide', '--json'];
    let result = await spawn(cmd, args, { timeoutMs: RUN_TIMEOUT_MS });
    if (!result.ok && result.code === 2 && known.length && repos.length && /unrecognized arguments:.*--known/.test(result.stderr)) {
      knownUnsupported = true;
      log('caddis hub: the collector script does not know --known (old plugin); sending full runs. Update the plugin.');
      result = await spawn(cmd, [...pre, script, '--repos', ...repos, '--json'], { timeoutMs: RUN_TIMEOUT_MS });
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
