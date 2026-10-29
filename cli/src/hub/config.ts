import { mkdirSync, readFileSync, renameSync, unlinkSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { randomBytes } from 'node:crypto';
import { configPath, registryPath } from './paths.js';

export const DEFAULT_PORT = 47821;

export interface HubConfig {
  schema: 1;
  port: number;
  /** Maps `owner/name` or `owner` to the gh account that reads that repo. */
  accounts: Record<string, string>;
  pinned: string[];
  hidden: string[];
}

export interface RepoEntry {
  path: string;
  added_at: string;
}

export interface Registry {
  schema: 1;
  repos: RepoEntry[];
}

/** `error` is set when the file is corrupt. `value` is then the last good copy (or the defaults). */
export interface ReadResult<T> {
  value: T;
  error?: string;
}

const isWin = (): boolean => process.platform === 'win32';

function defaultConfig(): HubConfig {
  return { schema: 1, port: DEFAULT_PORT, accounts: {}, pinned: [], hidden: [] };
}

function defaultRegistry(): Registry {
  return { schema: 1, repos: [] };
}

// Last good copy per file, for the life of the process.
const lastGood = new Map<string, unknown>();

/** Forget the cached copies. For tests. */
export function resetHubCache(): void {
  lastGood.clear();
}

function sleepSync(ms: number): void {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

/** Rename, and on Windows retry a short while when a scanner or indexer briefly holds the path (EPERM, EBUSY). */
export function renameWithRetry(from: string, to: string): void {
  const retryable = new Set(['EPERM', 'EBUSY', 'EACCES']);
  const attempts = isWin() ? 6 : 1;
  for (let i = 0; ; i++) {
    try {
      renameSync(from, to);
      return;
    } catch (e) {
      const code = (e as NodeJS.ErrnoException).code ?? '';
      if (i + 1 >= attempts || !retryable.has(code)) throw e;
      sleepSync(15 * 2 ** i);
    }
  }
}

/**
 * Write JSON atomically: a temp file in the same folder, then a rename.
 * POSIX: the folder is created 0700 and the file 0600.
 * Windows: the mode bits do nothing. H1.3 sets the ACL (`icacls`) on the key file only.
 */
export function writeJsonAtomic(file: string, data: unknown): void {
  mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const tmp = `${file}.${process.pid}.${randomBytes(4).toString('hex')}.tmp`;
  try {
    writeFileSync(tmp, JSON.stringify(data, null, 2) + '\n', { mode: 0o600 });
    renameWithRetry(tmp, file);
  } catch (e) {
    try {
      unlinkSync(tmp);
    } catch {
      /* temp file already gone */
    }
    throw e;
  }
}

/** Read a JSON file. Missing file: undefined. Corrupt file: last good copy plus an error. Never throws. */
function readJson<T>(file: string, normalize: (raw: unknown) => T, fallback: () => T): ReadResult<T> {
  let text: string;
  try {
    text = readFileSync(file, 'utf8');
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === 'ENOENT') {
      const good = lastGood.get(file) as T | undefined;
      return { value: good ?? fallback() };
    }
    return failure(file, fallback, `cannot read ${path.basename(file)}: ${(e as Error).message}`);
  }
  try {
    const value = normalize(JSON.parse(text));
    lastGood.set(file, value);
    return { value };
  } catch (e) {
    return failure(file, fallback, `corrupt ${path.basename(file)}: ${(e as Error).message}`);
  }
}

function failure<T>(file: string, fallback: () => T, error: string): ReadResult<T> {
  return { value: (lastGood.get(file) as T | undefined) ?? fallback(), error };
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);
const strings = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []);

function normalizeConfig(raw: unknown): HubConfig {
  if (!isObj(raw)) throw new Error('not a JSON object');
  const d = defaultConfig();
  const port = raw.port;
  // Keep any number as written. `caddis hub start|serve` refuses a port outside 1-65535 with a clear error.
  if (typeof port === 'number' && Number.isFinite(port)) d.port = port;
  if (isObj(raw.accounts)) {
    for (const [k, v] of Object.entries(raw.accounts)) if (typeof v === 'string') d.accounts[k] = v;
  }
  d.pinned = strings(raw.pinned);
  d.hidden = strings(raw.hidden);
  return d;
}

function normalizeRegistry(raw: unknown): Registry {
  if (!isObj(raw)) throw new Error('not a JSON object');
  const repos: RepoEntry[] = [];
  if (Array.isArray(raw.repos)) {
    for (const r of raw.repos) {
      if (isObj(r) && typeof r.path === 'string' && typeof r.added_at === 'string') {
        repos.push({ path: r.path, added_at: r.added_at });
      }
    }
  }
  return { schema: 1, repos };
}

export function readConfig(home?: string): ReadResult<HubConfig> {
  return readJson(configPath(home), normalizeConfig, defaultConfig);
}

export function readRegistry(home?: string): ReadResult<Registry> {
  return readJson(registryPath(home), normalizeRegistry, defaultRegistry);
}

/** Resolve and strip trailing separators. */
export function normalizeRepoPath(p: string): string {
  const r = path.resolve(p);
  const root = path.parse(r).root;
  let out = r;
  while (out.length > root.length && /[\/]$/.test(out)) out = out.slice(0, -1);
  return out;
}

/** The compare key of a normalized repo path: case-insensitive on Windows only. */
export const repoKey = (p: string): string => (isWin() ? p.toLowerCase() : p);

/**
 * Add repo folders to the registry. Duplicates are skipped (case-insensitive on Windows only).
 * A corrupt registry is not overwritten: the result carries the error and nothing is written.
 */
export function addRepos(paths: string[], home?: string): ReadResult<Registry> {
  const cur = readRegistry(home);
  if (cur.error) return cur;
  const seen = new Set(cur.value.repos.map((r) => repoKey(r.path)));
  const repos = [...cur.value.repos];
  const now = new Date().toISOString();
  let changed = false;
  for (const p of paths) {
    const n = normalizeRepoPath(p);
    const k = repoKey(n);
    if (seen.has(k)) continue;
    seen.add(k);
    repos.push({ path: n, added_at: now });
    changed = true;
  }
  const value: Registry = { schema: 1, repos };
  if (changed) {
    writeJsonAtomic(registryPath(home), value);
    lastGood.set(registryPath(home), value);
  }
  return { value };
}

