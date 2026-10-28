/**
 * Sessions of agents other than Claude Code, from their status files in `~/.caddis/sessions/`.
 *
 * Claude Code sessions come from `claude agents --json` (agents.ts). Another agent (agy today) has no such
 * list, so caddis hooks write one status file per session (claude-harness/scripts/caddis_heartbeat.py,
 * format in cli/README.md, "caddis hub"). This module reads those files and maps them to session entries.
 *
 * Read-only and synchronous: a few small files. The hooks prune old files; this module only filters them.
 */
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { sessionsDir } from '../../util/sessions.js';
import { repoPathFor, WAIT_DEBOUNCE_MS, type SessionEntry } from './agents.js';

/** A session not seen for this long is idle, unless it waits and its pid is alive. */
export const AGENT_IDLE_AFTER_MS = 10 * 60_000;
/** A session not seen for this long is dropped. Same value as NO_PID_STALE_AFTER_S in caddis_heartbeat.py. */
export const AGENT_DROP_AFTER_MS = 24 * 3600_000;
/** The statuses a status file may carry. */
const STATUSES = new Set(['working', 'waiting']);

export interface BeatsOptions {
  home: string;
  now: number;
  alive: (pid: number) => boolean;
  /** Session ids already listed (from `claude agents`): never listed twice. */
  exclude: Set<string>;
}

const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null);

function toEntry(raw: unknown, opts: BeatsOptions): SessionEntry | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const r = raw as Record<string, unknown>;
  const sessionId = str(r.session_id);
  const agent = str(r.harness);
  const status = str(r.status);
  const lastSeen = Number(r.last_seen) * 1000;
  if (!sessionId || !agent || agent === 'claude' || !status || !STATUSES.has(status)) return null;
  if (opts.exclude.has(sessionId) || !Number.isFinite(lastSeen)) return null;
  const age = opts.now - lastSeen;
  if (age > AGENT_DROP_AFTER_MS) return null;
  const pid = Number.isInteger(r.pid) && (r.pid as number) > 0 ? (r.pid as number) : null;
  if (pid !== null && !opts.alive(pid)) return null;

  const quiet = age > AGENT_IDLE_AFTER_MS;
  // A wait holds while its process lives. Without a pid, a quiet session may have closed: show it idle.
  const shown = status === 'waiting' ? (quiet && pid === null ? 'idle' : 'waiting') : quiet ? 'idle' : 'working';
  const sinceRaw = Number(r.status_since) * 1000;
  const since = Number.isFinite(sinceRaw) && sinceRaw > 0 ? sinceRaw : lastSeen;
  const waiting = shown === 'waiting';
  const cwd = str(r.cwd);
  return {
    key: `${agent}:${sessionId}`,
    pid,
    session_id: sessionId,
    name: str(r.name),
    kind: 'interactive',
    agent,
    cwd,
    repo_path: repoPathFor(cwd ?? str(r.repo_path)),
    status: shown,
    waiting_for: waiting ? (str(r.waiting_for) ?? 'input needed') : null,
    // A stopped agent turn always waits on the owner. The debounce matches the Claude sessions.
    waiting_class: waiting && opts.now - since >= WAIT_DEBOUNCE_MS ? 'owner' : null,
    waiting_since: waiting ? new Date(since).toISOString() : null,
    copies: 1,
  };
}

/** The live sessions of other agents, oldest file name order. Never throws. */
export function readAgentBeats(opts: BeatsOptions): SessionEntry[] {
  const dir = sessionsDir(opts.home);
  let names: string[];
  try {
    names = readdirSync(dir).sort();
  } catch {
    return [];
  }
  const out: SessionEntry[] = [];
  const seen = new Set<string>();
  for (const name of names) {
    if (!name.endsWith('.json') || name.startsWith('.')) continue;
    let entry: SessionEntry | null = null;
    try {
      entry = toEntry(JSON.parse(readFileSync(path.join(dir, name), 'utf8')), opts);
    } catch {
      continue;
    }
    if (entry && !seen.has(entry.session_id)) {
      seen.add(entry.session_id);
      out.push(entry);
    }
  }
  return out;
}
