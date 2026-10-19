/**
 * Live agent sessions and the caddis version each one loaded (robustness audit #18).
 *
 * A plugin update reaches only NEW sessions: a session that started earlier keeps the old hooks and
 * guard until it restarts. The SessionStart hook (`caddis_heartbeat.py`, called from `inject_relay.py`)
 * writes one file per session to `~/.caddis/sessions/<id>.json`; `caddis doctor` reads them here and
 * names the live sessions that run an older caddis than the installed one.
 *
 * Read-only. The hook prunes dead entries; this module only filters them out.
 */
import { readFileSync, readdirSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { compareVersions } from './semver.js';

/** Same value as STALE_AFTER_S in claude-harness/scripts/caddis_heartbeat.py. A pid seen this long ago may be reused. */
export const STALE_AFTER_MS = 7 * 24 * 3600 * 1000;

export interface SessionBeat {
  sessionId: string;
  harness: string;
  caddisVersion: string | null;
  pid: number;
  /** Epoch milliseconds. */
  started: number;
  lastSeen: number;
}

export interface OlderSession extends SessionBeat {
  installed: string;
}

/**
 * The home folder caddis state lives under. `CADDIS_HOME` replaces the user home (state goes to
 * `$CADDIS_HOME/.caddis/...`), exactly as in caddis_heartbeat.py, caddis_governor.py and setup_project_ai.py.
 * An empty value means unset.
 */
export function caddisHome(): string {
  return process.env.CADDIS_HOME || os.homedir();
}

export function sessionsDir(home: string = caddisHome()): string {
  return path.join(home, '.caddis', 'sessions');
}

/** True when a process with this pid exists. EPERM means it exists but belongs to someone else. */
export function pidAlive(pid: number): boolean {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === 'EPERM';
  }
}

function parse(raw: unknown): SessionBeat | null {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Record<string, unknown>;
  const pid = Number(r.pid);
  const lastSeen = Number(r.last_seen);
  if (typeof r.session_id !== 'string' || !Number.isInteger(pid) || !Number.isFinite(lastSeen)) return null;
  return {
    sessionId: r.session_id,
    harness: typeof r.harness === 'string' ? r.harness : 'claude',
    caddisVersion: typeof r.caddis_version === 'string' && r.caddis_version ? r.caddis_version : null,
    pid,
    started: (Number(r.started) || lastSeen) * 1000,
    lastSeen: lastSeen * 1000,
  };
}

/** Live sessions: the pid runs and last_seen is not stale. Oldest start first. */
export function liveSessions(
  home: string = caddisHome(),
  now: number = Date.now(),
  alive: (pid: number) => boolean = pidAlive,
): SessionBeat[] {
  const dir = sessionsDir(home);
  let names: string[];
  try {
    names = readdirSync(dir);
  } catch {
    return [];
  }
  const out: SessionBeat[] = [];
  for (const name of names) {
    if (!name.endsWith('.json') || name.startsWith('.')) continue;
    let beat: SessionBeat | null = null;
    try {
      beat = parse(JSON.parse(readFileSync(path.join(dir, name), 'utf8')));
    } catch {
      continue;
    }
    if (beat && now - beat.lastSeen <= STALE_AFTER_MS && alive(beat.pid)) out.push(beat);
  }
  return out.sort((a, b) => a.started - b.started);
}

/** The sessions whose caddis is older than the installed version of their own harness. Unknown versions are skipped. */
export function olderSessions(sessions: SessionBeat[], installed: Partial<Record<string, string>>): OlderSession[] {
  const out: OlderSession[] = [];
  for (const session of sessions) {
    // Own keys only: a harness named "constructor" must not read Object.prototype.
    const current = Object.hasOwn(installed, session.harness) ? installed[session.harness] : undefined;
    if (typeof current !== 'string' || !current || !session.caddisVersion) continue;
    const order = compareVersions(session.caddisVersion, current);
    if (order !== null && order < 0) out.push({ ...session, installed: current });
  }
  return out;
}
