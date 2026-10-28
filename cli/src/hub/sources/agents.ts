/**
 * The sessions source: `claude agents --json` (R22, R23, L16, L17).
 *
 * Keeps the last good list when a run fails. A session counts as waiting only after it
 * has been `waiting` for 45 s across refreshes, so the Inbox does not flap.
 *
 * With a `home`, each refresh also reads the status files other agents (agy) write to
 * `~/.caddis/sessions/` (beats.ts) and lists those sessions after the Claude ones. A session id that
 * `claude agents` lists is never listed twice.
 */
import { existsSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { findBin } from '../../util/which.js';
import { withTimeout } from '../bounded.js';
import { spawnBounded, type SpawnFn } from '../spawn.js';
import { normalizeRepoPath } from '../config.js';
import { pidAlive } from '../../util/sessions.js';
import { readAgentBeats } from './beats.js';

export const STALE_AFTER_MS = 3 * 60_000;
export const WAIT_DEBOUNCE_MS = 45_000;
const RUN_TIMEOUT_MS = 10_000;
/** A PATH lookup reads the disk; a dead network folder on PATH must not hold the latch forever. */
const FIND_TIMEOUT_MS = 10_000;

export interface SessionEntry {
  key: string;
  pid: number | null;
  session_id: string;
  name: string | null;
  kind: string;
  /** The agent that runs the session: `claude`, or another agent such as `agy`. Absent in old state: `claude`. */
  agent?: string;
  cwd: string | null;
  repo_path: string | null;
  status: string;
  waiting_for: string | null;
  waiting_class: 'owner' | 'peer' | null;
  waiting_since: string | null;
  copies: number;
}
export interface AgentsState {
  ok: boolean;
  last_ok_at: string | null;
  last_error: string | null;
  stale: boolean;
  data: SessionEntry[] | null;
}
export interface AgentsSource {
  refresh(): Promise<void>;
  get(): AgentsState;
}
export interface AgentsOptions {
  now?: () => number;
  spawn?: SpawnFn;
  findClaude?: () => Promise<string | null>;
  /** The home folder whose `.caddis/sessions/` holds other agents' status files. Unset: none are read. */
  home?: string;
  alive?: (pid: number) => boolean;
}

export function classifyWaiting(waitingFor: string | null): 'owner' | 'peer' {
  const w = (waitingFor ?? '').toLowerCase();
  if (w === 'permission prompt' || w === 'input needed' || w.includes('question')) return 'owner';
  return 'peer';
}

const isFile = (p: string): boolean => {
  try {
    return statSync(p).isFile();
  } catch {
    return false;
  }
};
const isDir = (p: string): boolean => {
  try {
    return statSync(p).isDirectory();
  } catch {
    return false;
  }
};

/**
 * The repo root of a folder, by the git common dir, with no subprocess.
 * A worktree maps to its main repo. No `.git` above the folder: null.
 */
export function repoPathFor(cwd: string | null | undefined): string | null {
  if (!cwd) return null;
  let dir = path.resolve(cwd);
  for (;;) {
    const dotGit = path.join(dir, '.git');
    if (existsSync(dotGit)) {
      if (isDir(dotGit)) return normalizeRepoPath(dir);
      if (isFile(dotGit)) return commonRoot(dir, dotGit);
      return null;
    }
    const parent = path.dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

function commonRoot(dir: string, dotGitFile: string): string | null {
  try {
    const m = /^gitdir:\s*(.+?)\s*$/m.exec(readFileSync(dotGitFile, 'utf8'));
    if (!m) return null;
    const gitdir = path.resolve(dir, m[1] ?? '');
    let common: string;
    try {
      const rel = readFileSync(path.join(gitdir, 'commondir'), 'utf8').trim();
      if (!rel) return normalizeRepoPath(dir);
      common = path.resolve(gitdir, rel);
    } catch {
      // No commondir: a submodule. Its work tree is the folder that holds the `.git` file.
      return normalizeRepoPath(dir);
    }
    return normalizeRepoPath(path.dirname(common));
  } catch {
    return null;
  }
}

const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null);

export function createAgentsSource(opts: AgentsOptions = {}): AgentsSource {
  const now = opts.now ?? Date.now;
  const spawn = opts.spawn ?? spawnBounded;
  const find = opts.findClaude ?? (() => findBin('claude'));
  const alive = opts.alive ?? pidAlive;
  const waitingSince = new Map<string, number>();
  let sessions: SessionEntry[] | null = null;
  let others: SessionEntry[] = [];
  let lastOkAt: number | null = null;
  let lastError: string | null = null;
  let lastRunOk = false;
  let running: Promise<void> | null = null;

  const fail = (message: string): void => {
    lastError = message;
    lastRunOk = false;
  };

  const ingest = (parsed: unknown): void => {
    if (!Array.isArray(parsed)) return fail('claude agents output is not a JSON array');
    const t = now();
    const byId = new Map<string, SessionEntry>();
    const seenWaiting = new Set<string>();
    for (const raw of parsed) {
      if (!raw || typeof raw !== 'object') continue;
      const e = raw as Record<string, unknown>;
      const sessionId = str(e.sessionId);
      if (!sessionId) continue;
      const kind = str(e.kind) ?? 'interactive';
      const status = str(e.status) ?? str(e.state) ?? 'unknown';
      if (kind === 'background' && status === 'done') continue;
      const prior = byId.get(sessionId);
      if (prior) {
        prior.copies += 1;
        continue;
      }
      const pid = typeof e.pid === 'number' ? e.pid : null;
      const cwd = str(e.cwd);
      const isWaiting = status === 'waiting';
      const waitingFor = isWaiting ? str(e.waitingFor) : null;
      const key = `${pid ?? str(e.id) ?? kind}:${sessionId}`;
      let since: number | null = null;
      if (isWaiting) {
        seenWaiting.add(key);
        since = waitingSince.get(key) ?? t;
        waitingSince.set(key, since);
      }
      const confirmed = isWaiting && t - (since ?? t) >= WAIT_DEBOUNCE_MS;
      byId.set(sessionId, {
        key,
        pid,
        session_id: sessionId,
        name: str(e.name),
        kind,
        agent: 'claude',
        cwd,
        repo_path: repoPathFor(cwd),
        status,
        waiting_for: waitingFor,
        waiting_class: confirmed ? classifyWaiting(waitingFor) : null,
        waiting_since: since === null ? null : new Date(since).toISOString(),
        copies: 1,
      });
    }
    for (const k of [...waitingSince.keys()]) if (!seenWaiting.has(k)) waitingSince.delete(k);
    sessions = [...byId.values()];
    lastOkAt = t;
    lastError = null;
    lastRunOk = true;
  };

  const run = async (): Promise<void> => {
    const bin = await withTimeout(find(), FIND_TIMEOUT_MS, 'finding claude');
    if (!bin) return fail('claude was not found on PATH');
    const result = await spawn(bin, ['agents', '--json'], { timeoutMs: RUN_TIMEOUT_MS });
    if (result.timedOut) return fail(`claude agents timed out after ${RUN_TIMEOUT_MS / 1000} s`);
    if (!result.ok) {
      const detail = (result.stderr || result.stdout).trim().slice(0, 500);
      return fail(`claude agents failed (exit ${result.code ?? 'none'})${detail ? `: ${detail}` : ''}`);
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(result.stdout);
    } catch (error) {
      return fail(`claude agents output is not valid JSON: ${error instanceof Error ? error.message : String(error)}`);
    }
    ingest(parsed);
  };

  return {
    refresh(): Promise<void> {
      if (!running) {
        running = run()
          .catch((error) => fail(error instanceof Error ? error.message : String(error)))
          .then(() => {
            if (opts.home === undefined) return;
            const exclude = new Set((sessions ?? []).map((s) => s.session_id));
            others = readAgentBeats({ home: opts.home, now: now(), alive, exclude });
          })
          .finally(() => {
            running = null;
          });
      }
      return running;
    },
    get(): AgentsState {
      return {
        ok: lastRunOk,
        last_ok_at: lastOkAt === null ? null : new Date(lastOkAt).toISOString(),
        last_error: lastError,
        stale: lastOkAt === null || now() - lastOkAt > STALE_AFTER_MS,
        data: sessions === null && others.length === 0 ? null : [...(sessions ?? []), ...others],
      };
    },
  };
}
