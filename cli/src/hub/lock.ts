/**
 * The single-instance lock `~/.caddis/hub/hub.lock` (L25).
 *
 * The lock is JSON `{pid, started_at, port}`. It never holds the key.
 * An exclusive create (`wx`) decides who owns it. A lock whose pid is dead is stale: the next
 * owner removes it and takes over. A corrupt lock is also treated as stale.
 *
 * Known limit: two processes that take over the same stale lock at the same moment can race.
 * The second one reads the lock again before it removes it, which makes the window small.
 * The hub is a single-user tool, so we accept that.
 */
import { closeSync, mkdirSync, openSync, readFileSync, unlinkSync, writeSync } from 'node:fs';
import path from 'node:path';
import { writeJsonAtomic } from './config.js';
import { lockPath } from './paths.js';
import { pidAlive } from '../util/sessions.js';

export interface LockInfo {
  pid: number;
  /** UTC ISO 8601 with `Z`. */
  started_at: string;
  port: number;
  /**
   * 16 random bytes hex, new for each serve run. The server answers it on `GET /api/hub/whoami`.
   * The CLI sends the key only when the port answers this instance (a reused pid is not enough).
   */
  instance?: string;
}

export type AcquireResult = { ok: true } | { ok: false; holder: LockInfo };

// Lock files this process holds. A lock with our own pid that we do not hold is left over from an
// earlier process whose pid the OS gave to us: it is stale.
const held = new Set<string>();

/** Read the lock. Missing or corrupt: null. Never throws. */
export function readLock(home?: string): LockInfo | null {
  try {
    const raw = JSON.parse(readFileSync(lockPath(home), 'utf8')) as Record<string, unknown>;
    const pid = raw.pid;
    const port = raw.port;
    if (typeof pid !== 'number' || !Number.isInteger(pid) || pid <= 0) return null;
    if (typeof port !== 'number' || !Number.isInteger(port)) return null;
    const started = typeof raw.started_at === 'string' ? raw.started_at : '';
    const info: LockInfo = { pid, started_at: started, port };
    if (typeof raw.instance === 'string' && /^[0-9a-f]{32}$/.test(raw.instance)) info.instance = raw.instance;
    return info;
  } catch {
    return null;
  }
}

/**
 * True when the lock holder's pid runs. Our own pid counts only when this process took the lock.
 * A live pid is NOT proof of a live hub (the OS reuses pids): the CLI also checks `whoami` and the start time.
 */
export function holderAlive(h: LockInfo, home: string | undefined, alive: (pid: number) => boolean): boolean {
  return h.pid === process.pid ? held.has(lockPath(home)) : alive(h.pid);
}

function removeFile(file: string): void {
  try {
    unlinkSync(file);
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code !== 'ENOENT') throw e;
  }
}

/**
 * Take the lock for `info.pid`. A live holder (`alive(pid)` true; EPERM counts as alive) wins.
 * A dead or corrupt holder is removed and we try again.
 */
export function acquireLock(
  info: LockInfo,
  home?: string,
  alive: (pid: number) => boolean = pidAlive,
): AcquireResult {
  const file = lockPath(home);
  const live = (h: LockInfo | null): h is LockInfo => h !== null && holderAlive(h, home, alive);
  mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  for (let attempt = 0; attempt < 3; attempt++) {
    let fd: number;
    try {
      fd = openSync(file, 'wx', 0o600);
    } catch (e) {
      if ((e as NodeJS.ErrnoException).code !== 'EEXIST') throw e;
      const holder = readLock(home);
      if (live(holder)) return { ok: false, holder };
      // Stale or corrupt: read it again just before removal, to keep the race window small.
      const again = readLock(home);
      if (live(again)) return { ok: false, holder: again };
      removeFile(file);
      continue;
    }
    try {
      writeSync(fd, JSON.stringify(info) + '\n');
    } finally {
      closeSync(fd);
    }
    if (info.pid === process.pid) held.add(file);
    return { ok: true };
  }
  const holder = readLock(home);
  if (holder) return { ok: false, holder };
  throw new Error('could not take the hub lock');
}

/** Rewrite the lock (for example with the real port after listen). */
export function writeLock(info: LockInfo, home?: string): void {
  writeJsonAtomic(lockPath(home), info);
}

/** Remove the lock, but only when `pid` owns it. A missing lock is fine. Never throws. */
export function releaseLock(pid: number, home?: string): void {
  const cur = readLock(home);
  if (!cur || cur.pid !== pid) return;
  if (pid === process.pid) held.delete(lockPath(home));
  try {
    removeFile(lockPath(home));
  } catch {
    /* the next start treats it as stale */
  }
}

/** Remove the lock only when it is still this exact lock (same pid and instance). Never throws. */
export function removeLockIf(expected: LockInfo, home?: string): void {
  const cur = readLock(home);
  if (cur && cur.pid === expected.pid && cur.instance === expected.instance && cur.started_at === expected.started_at) {
    removeLock(home);
  }
}

/** Remove the lock whoever owns it. Never throws. */
export function removeLock(home?: string): void {
  held.delete(lockPath(home));
  try {
    removeFile(lockPath(home));
  } catch {
    /* nothing more to do */
  }
}
