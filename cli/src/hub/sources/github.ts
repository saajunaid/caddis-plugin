/**
 * The GitHub source (R22, R23, L6, L10, L11).
 *
 * Per repo: open PRs with their check runs, and the last merges with their deploy runs.
 * Every URL keeps its ETag and body. A 304 reuses the body and costs no rate limit.
 * The token comes from `gh auth token -u <account>`. It is never logged, stored in data or returned.
 *
 * The account for a repo (L6, final review I4): the `accounts` override in `~/.caddis/hub/config.json`
 * (exact `owner/name`, then the owner), else the logged-in accounts from `gh auth status`: the remote owner
 * when it is one of them, then the active account, then the others. The first account that can see the repo
 * is kept for its owner. Every wait has a time limit, so the `running` latch always opens again.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { findBin } from '../../util/which.js';
import { withTimeout } from '../bounded.js';
import { spawnBounded, type SpawnFn } from '../spawn.js';
import { repoPathFor } from './agents.js';

export const STALE_AFTER_MS = 3 * 60_000;
export const POLL_MS = 60_000;
export const SLOW_POLL_MS = 5 * 60_000;
export const RATE_RESERVE = 500;
const API = 'https://api.github.com';
const TOKEN_TIMEOUT_MS = 10_000;
const FIND_TIMEOUT_MS = 10_000;
/** One request, body included. `AbortSignal.timeout` stops the socket; `withTimeout` bounds a fetch that ignores it. */
export const FETCH_TIMEOUT_MS = 15_000;
const MERGES_SHOWN = 5;

export type FetchFn = (
  url: string,
  init: { headers: Record<string, string>; signal?: AbortSignal },
) => Promise<Response>;

/** The github.com accounts `gh auth status` lists, and the active one. */
export interface GhAuthStatus {
  active: string | null;
  accounts: string[];
}

export interface CheckEntry {
  name: string;
  status: string;
  conclusion: string | null;
  required: boolean | null;
}
export type RequiredState = 'pass' | 'fail' | 'pending' | 'unknown';
export interface PrEntry {
  number: number;
  title: string;
  head_sha: string;
  author: string | null;
  draft: boolean;
  updated_at: string | null;
  url: string;
  checks: CheckEntry[];
  required_state: RequiredState;
}
export interface RunEntry {
  name: string;
  status: string;
  conclusion: string | null;
  url: string;
}
export interface MergeEntry {
  number: number;
  title: string;
  merge_sha: string;
  merged_at: string;
  runs: RunEntry[];
}
export interface GithubRepoSlot {
  path: string;
  repo?: string;
  account?: string;
  reason?: string;
  error?: string;
  /** When this repo last loaded. One failing repo shows its own age; the others stay fresh (I3). */
  last_ok_at?: string;
  prs?: PrEntry[];
  merges?: MergeEntry[];
}
export interface RateInfo {
  remaining: number;
  reset_at: string | null;
}
export interface GithubData {
  repos: GithubRepoSlot[];
  rate: Record<string, RateInfo>;
}
export interface GithubState {
  ok: boolean;
  last_ok_at: string | null;
  last_error: string | null;
  stale: boolean;
  data: GithubData | null;
}
export interface GithubSource {
  refresh(): Promise<void>;
  get(): GithubState;
  nextDelayMs(): number;
}
export interface GithubOptions {
  repos: () => string[];
  accounts: () => Record<string, string>;
  fetch?: FetchFn;
  getToken?: (account: string) => Promise<string | null>;
  /** The logged-in accounts. null: not known (then the remote owner is tried, as before discovery). */
  authStatus?: () => Promise<GhAuthStatus | null>;
  now?: () => number;
  spawn?: SpawnFn;
}

/** `owner/name` from a GitHub remote URL (https, scp-style or ssh), else null. */
export function parseGithubRemote(url: string): string | null {
  const m =
    /^(?:https?:\/\/(?:[^@/]+@)?|ssh:\/\/git@|git@)github\.com[/:]([^/\s]+)\/([^/\s]+?)(?:\.git)?\/?$/i.exec(url.trim());
  return m ? `${m[1]}/${m[2]}` : null;
}

/** The URL of remote `origin` from `.git/config` (no subprocess). A worktree maps to its main repo. */
export function readOriginUrl(repoDir: string): string | null {
  const root = repoPathFor(repoDir);
  if (!root) return null;
  let text: string;
  try {
    text = readFileSync(path.join(root, '.git', 'config'), 'utf8');
  } catch {
    return null;
  }
  let inOrigin = false;
  for (const line of text.split(/\r?\n/)) {
    const section = /^\s*\[(.+)\]\s*$/.exec(line);
    if (section) {
      inOrigin = /^remote\s+"origin"$/.test(section[1] ?? '');
      continue;
    }
    const kv = inOrigin ? /^\s*url\s*=\s*(.+?)\s*$/.exec(line) : null;
    if (kv) return kv[1] ?? null;
  }
  return null;
}

/** `required_checks` from the first fenced json block of `.caddis/coordinator.md`. null: not known. */
export function readRequiredChecks(repoDir: string): string[] | null {
  try {
    const text = readFileSync(path.join(repoDir, '.caddis', 'coordinator.md'), 'utf8');
    const m = /```json[^\S\r\n]*\r?\n([\s\S]*?)\r?\n[^\S\r\n]*```/.exec(text);
    if (!m) return null;
    const parsed: unknown = JSON.parse(m[1] ?? '');
    if (!parsed || typeof parsed !== 'object') return null;
    const req = (parsed as Record<string, unknown>).required_checks;
    if (!Array.isArray(req) || !req.every((x) => typeof x === 'string')) return null;
    return req as string[];
  } catch {
    return null;
  }
}

const FAILED = new Set(['failure', 'cancelled', 'timed_out', 'action_required', 'startup_failure', 'stale']);
const PASSED = new Set(['success', 'neutral', 'skipped']);

export function requiredState(checks: CheckEntry[], required: string[] | null): RequiredState {
  if (required === null) return 'unknown';
  let pending = false;
  for (const name of required) {
    const c = checks.find((x) => x.name === name);
    if (!c || c.status !== 'completed') pending = true;
    else if (c.conclusion && FAILED.has(c.conclusion)) return 'fail';
    else if (!c.conclusion || !PASSED.has(c.conclusion)) pending = true;
  }
  return pending ? 'pending' : 'pass';
}

class HttpError extends Error {
  /** This token cannot see the repo: try the next account. */
  readonly access: boolean;
  constructor(
    readonly status: number,
    readonly rateLimited: boolean,
    message: string,
    access = false,
  ) {
    super(message);
    this.access = access || status === 401 || (status === 403 && !rateLimited);
  }
}

const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null);
const rec = (v: unknown): Record<string, unknown> => (v && typeof v === 'object' ? (v as Record<string, unknown>) : {});
const list = (v: unknown): Record<string, unknown>[] => (Array.isArray(v) ? v.map(rec) : []);

const findGh = (): Promise<string | null> => withTimeout(findBin('gh'), FIND_TIMEOUT_MS, 'finding gh');

async function defaultToken(spawn: SpawnFn, account: string): Promise<string | null> {
  const gh = await findGh();
  if (!gh) return null;
  const r = await spawn(gh, ['auth', 'token', '-u', account], { timeoutMs: TOKEN_TIMEOUT_MS });
  const token = r.stdout.trim();
  return r.ok && token ? token : null;
}

/**
 * The github.com accounts in `gh auth status` text: `Logged in to github.com account <user>` (gh 2.40+, with an
 * `Active account: true` line) or `Logged in to github.com as <user>` (older gh, one account). The text holds no
 * token (no `--show-token`); it is never logged.
 */
export function parseAuthStatus(text: string): GhAuthStatus {
  const accounts: string[] = [];
  let active: string | null = null;
  let current: string | null = null;
  for (const line of text.split(/\r?\n/)) {
    const m = /Logged in to (\S+) (?:account|as) (\S+)/.exec(line);
    if (m) {
      current = m[1] === 'github.com' ? (m[2] ?? null) : null;
      if (current && !accounts.includes(current)) accounts.push(current);
      continue;
    }
    if (current && /Active account:\s*true/i.test(line)) active = current;
  }
  if (!active && accounts.length === 1) active = accounts[0] ?? null;
  return { active, accounts };
}

async function defaultAuthStatus(spawn: SpawnFn): Promise<GhAuthStatus | null> {
  const gh = await findGh();
  if (!gh) return null;
  const r = await spawn(gh, ['auth', 'status', '-h', 'github.com'], { timeoutMs: TOKEN_TIMEOUT_MS });
  if (r.timedOut) return null;
  // gh writes the status to stderr in some versions, and exits 1 when one account has a bad token.
  const status = parseAuthStatus(`${r.stdout}\n${r.stderr}`);
  return status.accounts.length || r.ok ? status : null;
}

/** The accounts to try for a repo of `owner` with no override: see the file comment. */
export function accountCandidates(owner: string, status: GhAuthStatus | null, known?: string): string[] {
  if (!status) return [known ?? owner];
  const out: string[] = [];
  const add = (a: string | null | undefined): void => {
    if (a && !out.includes(a)) out.push(a);
  };
  if (known && status.accounts.includes(known)) add(known);
  add(status.accounts.find((a) => a.toLowerCase() === owner.toLowerCase()));
  add(status.active);
  status.accounts.forEach(add);
  return out;
}

/** The slot error when no account can see the repo. It names the fix. */
export function accessError(owner: string, tried: string[]): string {
  const set = `set "accounts": {"${owner}": "<gh user>"} in ~/.caddis/hub/config.json`;
  if (!tried.length) return `no gh account is logged in: run gh auth login -h github.com, then ${set}`;
  return `no access with account ${tried.join(', ')}: run gh auth login -h github.com, or ${set}`;
}

export function createGithubSource(opts: GithubOptions): GithubSource {
  const now = opts.now ?? Date.now;
  const doFetch: FetchFn = opts.fetch ?? ((url, init) => fetch(url, init));
  const spawn = opts.spawn ?? spawnBounded;
  const getToken = opts.getToken ?? ((account: string) => defaultToken(spawn, account));
  // An injected token reader with no status reader means "status not known", so a test never runs the real gh.
  const authStatus = opts.authStatus ?? (opts.getToken ? async () => null : () => defaultAuthStatus(spawn));
  // The account that could see each owner's repos, found by trying the candidates. Kept across runs.
  const ownerAccount = new Map<string, string>();
  let etags = new Map<string, { etag: string; body: unknown }>();
  // Cache keys requested during the current run. At the end of a run the cache keeps only these (bounded).
  let seen = new Set<string>();
  const slots = new Map<string, GithubRepoSlot>();
  const rate = new Map<string, RateInfo>();
  let lastOkAt: number | null = null;
  let lastError: string | null = null;
  let lastRunOk = false;
  let running: Promise<void> | null = null;

  const noteRate = (account: string, res: Response): void => {
    const left = res.headers.get('x-ratelimit-remaining');
    const remaining = Number(left);
    if (left === null || !Number.isFinite(remaining)) return;
    const reset = Number(res.headers.get('x-ratelimit-reset'));
    rate.set(account, {
      remaining,
      reset_at: Number.isFinite(reset) && reset > 0 ? new Date(reset * 1000).toISOString() : null,
    });
  };

  const getJson = async (account: string, token: string, pathAndQuery: string): Promise<unknown> => {
    const url = `${API}${pathAndQuery}`;
    const key = `${account}\n${url}`;
    seen.add(key);
    const cached = etags.get(key);
    const headers: Record<string, string> = {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'caddis-hub',
    };
    if (cached) headers['If-None-Match'] = cached.etag;
    const signal = AbortSignal.timeout(FETCH_TIMEOUT_MS);
    const res = await withTimeout(doFetch(url, { headers, signal }), FETCH_TIMEOUT_MS + 1_000, 'GitHub request');
    noteRate(account, res);
    if (res.status === 304) {
      if (cached) return cached.body;
      throw new HttpError(304, false, 'GitHub answered 304 with no cached copy');
    }
    if (!res.ok) {
      const limited =
        (res.status === 403 || res.status === 429) &&
        (res.headers.get('x-ratelimit-remaining') === '0' || res.headers.get('retry-after') !== null);
      throw new HttpError(res.status, limited, limited ? 'GitHub rate limit reached' : `GitHub answered ${res.status}`);
    }
    const body: unknown = await withTimeout(res.json() as Promise<unknown>, FETCH_TIMEOUT_MS + 1_000, 'GitHub response');
    const etag = res.headers.get('etag');
    if (etag) etags.set(key, { etag, body });
    return body;
  };

  // Page limits: no pagination. We read the first 50 open PRs, and the 20 most recently updated closed PRs;
  // the last 5 merges come from those 20.
  const loadRepo = async (repoPath: string, repo: string, account: string, token: string): Promise<GithubRepoSlot> => {
    const required = readRequiredChecks(repoPath);
    let first: unknown;
    try {
      first = await getJson(account, token, `/repos/${repo}/pulls?state=open&per_page=50`);
    } catch (error) {
      // GitHub answers 404, not 403, when the token cannot see a private repo: the wrong-account case (L6, I3).
      if (error instanceof HttpError && error.status === 404) throw new HttpError(404, false, error.message, true);
      throw error;
    }
    const pulls = list(first);
    const prs: PrEntry[] = [];
    for (const p of pulls) {
      const head = str(rec(p.head).sha) ?? '';
      const byName = new Map<string, CheckEntry>();
      if (head) {
        const body = rec(await getJson(account, token, `/repos/${repo}/commits/${head}/check-runs?per_page=100`));
        for (const c of list(body.check_runs)) {
          const name = str(c.name);
          if (!name) continue;
          // A re-run repeats the name. The later entry wins.
          byName.set(name, {
            name,
            status: str(c.status) ?? 'unknown',
            conclusion: str(c.conclusion),
            required: required === null ? null : required.includes(name),
          });
        }
      }
      const checks = [...byName.values()];
      prs.push({
        number: Number(p.number),
        title: str(p.title) ?? '',
        head_sha: head,
        author: str(rec(p.user).login),
        draft: p.draft === true,
        updated_at: str(p.updated_at),
        url: str(p.html_url) ?? '',
        checks,
        required_state: requiredState(checks, required),
      });
    }
    const closed = list(
      await getJson(account, token, `/repos/${repo}/pulls?state=closed&sort=updated&direction=desc&per_page=20`),
    );
    const merged = closed
      .filter((p) => str(p.merged_at) && str(p.merge_commit_sha))
      .sort((a, b) => String(b.merged_at).localeCompare(String(a.merged_at)))
      .slice(0, MERGES_SHOWN);
    const merges: MergeEntry[] = [];
    for (const p of merged) {
      const sha = str(p.merge_commit_sha) ?? '';
      const body = rec(await getJson(account, token, `/repos/${repo}/actions/runs?head_sha=${sha}&per_page=10`));
      merges.push({
        number: Number(p.number),
        title: str(p.title) ?? '',
        merge_sha: sha,
        merged_at: str(p.merged_at) ?? '',
        runs: list(body.workflow_runs).map((r) => ({
          name: str(r.name) ?? '',
          status: str(r.status) ?? 'unknown',
          conclusion: str(r.conclusion),
          url: str(r.html_url) ?? '',
        })),
      });
    }
    return { path: repoPath, repo, account, prs, merges };
  };

  const run = async (): Promise<void> => {
    seen = new Set<string>();
    const limitedAccounts = new Set<string>();
    try {
      await runRepos(limitedAccounts);
    } finally {
      const kept = new Map<string, { etag: string; body: unknown }>();
      for (const key of seen) {
        const entry = etags.get(key);
        if (entry) kept.set(key, entry);
      }
      etags = kept;
    }
  };

  const runRepos = async (limitedAccounts: Set<string>): Promise<void> => {
    const accounts = opts.accounts();
    const wanted = opts.repos();
    const tokens = new Map<string, string | null>();
    const errors: string[] = [];
    let loaded = false;
    let status: GhAuthStatus | null | undefined;
    const tokenFor = async (account: string): Promise<string | null> => {
      if (!tokens.has(account)) {
        tokens.set(account, await withTimeout(getToken(account), TOKEN_TIMEOUT_MS + 5_000, 'gh auth token'));
      }
      return tokens.get(account) ?? null;
    };
    for (const key of [...slots.keys()]) if (!wanted.includes(key)) slots.delete(key);
    for (const repoPath of wanted) {
      const url = readOriginUrl(repoPath);
      const repo = url ? parseGithubRemote(url) : null;
      if (!repo) {
        slots.set(repoPath, { path: repoPath, reason: 'no github remote' });
        continue;
      }
      const owner = repo.split('/')[0] ?? '';
      const override = accounts[repo] ?? accounts[owner];
      let candidates: string[];
      if (override) {
        candidates = [override];
      } else {
        if (status === undefined) {
          status = await withTimeout(authStatus(), TOKEN_TIMEOUT_MS + 5_000, 'gh auth status').catch(() => null);
        }
        candidates = accountCandidates(owner, status, ownerAccount.get(owner));
      }
      const old = slots.get(repoPath);
      const tried: string[] = [];
      let settled = false;
      for (const account of candidates) {
        // After a rate limit, skip the other repos of this account. Their last good data stays.
        if (limitedAccounts.has(account)) {
          settled = true;
          break;
        }
        tried.push(account);
        try {
          const token = await tokenFor(account);
          if (!token) continue; // not logged in as this account: try the next one
          const slot = await loadRepo(repoPath, repo, account, token);
          slots.set(repoPath, { ...slot, last_ok_at: new Date(now()).toISOString() });
          if (!override) ownerAccount.set(owner, account);
          loaded = true;
          settled = true;
          break;
        } catch (error) {
          if (error instanceof HttpError && error.access && !error.rateLimited) continue;
          if (error instanceof HttpError && error.rateLimited) limitedAccounts.add(account);
          const message = error instanceof Error ? error.message : String(error);
          errors.push(`${repo}: ${message}`);
          // Keep the last good data when a later run fails; a rate limit is shown at source level only.
          if (old?.prs !== undefined) {
            if (!(error instanceof HttpError && error.rateLimited)) slots.set(repoPath, { ...old, error: message });
          } else {
            slots.set(repoPath, { path: repoPath, repo, account, error: message });
          }
          settled = true;
          break;
        }
      }
      if (!settled) {
        if (!override && ownerAccount.get(owner) !== undefined) ownerAccount.delete(owner);
        const slot: GithubRepoSlot = { path: repoPath, repo, error: accessError(owner, tried) };
        if (tried[0]) slot.account = tried[0];
        if (old?.last_ok_at) slot.last_ok_at = old.last_ok_at;
        slots.set(repoPath, slot);
      }
    }
    lastRunOk = errors.length === 0;
    lastError = errors.length ? errors.join('; ') : null;
    // One failing repo does not make the whole source stale: the run counts when any repo loaded (I3).
    if (lastRunOk || loaded) lastOkAt = now();
  };

  return {
    refresh(): Promise<void> {
      if (!running) {
        running = run()
          .catch((error) => {
            lastError = error instanceof Error ? error.message : String(error);
            lastRunOk = false;
          })
          .finally(() => {
            running = null;
          });
      }
      return running;
    },
    get(): GithubState {
      return {
        ok: lastRunOk,
        last_ok_at: lastOkAt === null ? null : new Date(lastOkAt).toISOString(),
        last_error: lastError,
        stale: lastOkAt === null || now() - lastOkAt > STALE_AFTER_MS,
        data: lastOkAt === null && slots.size === 0 ? null : { repos: [...slots.values()], rate: Object.fromEntries(rate) },
      };
    },
    nextDelayMs(): number {
      for (const r of rate.values()) if (r.remaining < RATE_RESERVE) return SLOW_POLL_MS;
      return POLL_MS;
    },
  };
}
