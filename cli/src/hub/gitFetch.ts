/**
 * Quiet, bounded, read-only `git fetch` for the hub's repos.
 *
 * The collector reads `origin/<default>` and never fetches (R15). This module brings those refs up to date,
 * so roadmaps and plans change within seconds of a merge. It runs only
 * `git -C <repo> fetch origin --prune --quiet`: it never touches a working tree, a checked-out branch or the
 * index, and it never runs pull, merge, reset or checkout.
 *
 * - It never blocks on a prompt: `GIT_TERMINAL_PROMPT=0` and `GCM_INTERACTIVE=never`.
 * - It never waits long: `spawnBounded` kills the git process tree after `FETCH_TIMEOUT_MS`.
 * - One fetch per repo at a time: a second caller joins the fetch that runs (keyed by the repo path).
 * - It never rejects. A missing git, no origin, no network, a non-zero exit or a time-out gives a
 *   `failed` or `skipped` result, and the caller keeps its cached data.
 */
import { existsSync } from 'node:fs';
import path from 'node:path';
import { normalizeRepoPath, repoKey } from './config.js';
import { spawnBounded, type SpawnFn } from './spawn.js';
import { readOriginUrl } from './sources/github.js';
import { repoPathFor } from './sources/agents.js';

/** The longest one `git fetch` may run. */
export const FETCH_TIMEOUT_MS = 30_000;
/** A repo is fetched again after this long, even when GitHub shows no change. */
export const PERIODIC_FETCH_MS = 150_000;
/** The most `git fetch` processes that run at the same time. */
export const FETCH_CONCURRENCY = 4;

/** `fetched`: git exited 0. `failed`: it did not (offline, auth, time-out). `skipped`: not a git repo, or no origin. */
export interface FetchResult {
  path: string;
  status: 'fetched' | 'failed' | 'skipped';
  error?: string;
}

export interface GitFetcher {
  /** Fetch one repo. A call while a fetch of the same repo runs joins that fetch. Never rejects. */
  fetchRepo(repoPath: string): Promise<FetchResult>;
}

export interface GitFetchOptions {
  spawn?: SpawnFn;
  /** The git program. Default: `git` from PATH. */
  git?: string;
  timeoutMs?: number;
}

/** True when the folder is a git repo with an `origin` remote. Local reads only. */
function hasOrigin(repoPath: string): boolean {
  const root = repoPathFor(repoPath);
  if (!root || !existsSync(path.join(root, '.git', 'HEAD'))) return false;
  return readOriginUrl(root) !== null;
}

export function createGitFetcher(opts: GitFetchOptions = {}): GitFetcher {
  const spawn = opts.spawn ?? spawnBounded;
  const git = opts.git ?? 'git';
  const timeoutMs = opts.timeoutMs ?? FETCH_TIMEOUT_MS;
  const running = new Map<string, Promise<FetchResult>>();

  const run = async (repoPath: string): Promise<FetchResult> => {
    try {
      if (!hasOrigin(repoPath)) return { path: repoPath, status: 'skipped', error: 'no origin remote' };
      const r = await spawn(git, ['-C', repoPath, 'fetch', 'origin', '--prune', '--quiet'], {
        timeoutMs,
        env: { GIT_TERMINAL_PROMPT: '0', GCM_INTERACTIVE: 'never' },
        maxBytes: 64 * 1024,
      });
      if (r.ok) return { path: repoPath, status: 'fetched' };
      const detail = r.timedOut ? `git fetch timed out after ${timeoutMs / 1000} s` : r.stderr.trim().slice(0, 300);
      return { path: repoPath, status: 'failed', error: detail || `git fetch exited ${r.code ?? 'none'}` };
    } catch (error) {
      return { path: repoPath, status: 'failed', error: error instanceof Error ? error.message : String(error) };
    }
  };

  return {
    fetchRepo(repoPath: string): Promise<FetchResult> {
      const key = repoKey(normalizeRepoPath(repoPath));
      let p = running.get(key);
      if (!p) {
        p = run(repoPath).finally(() => running.delete(key));
        running.set(key, p);
      }
      return p;
    },
  };
}

/** Run `fn` over `items`, at most `limit` at a time. Results keep the order of `items`. `fn` must not throw. */
export async function mapLimit<T, R>(items: T[], limit: number, fn: (item: T) => Promise<R>): Promise<R[]> {
  const out = new Array<R>(items.length);
  let next = 0;
  const worker = async (): Promise<void> => {
    while (next < items.length) {
      const i = next;
      next += 1;
      out[i] = await fn(items[i] as T);
    }
  };
  await Promise.all(Array.from({ length: Math.min(Math.max(1, limit), items.length) }, worker));
  return out;
}
