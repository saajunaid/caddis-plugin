import { otherAgent, samePath } from '../inbox/derive';
import type { HubState, RepoState, SessionEntry } from '../types';

/** The Sessions tab model (R50). Pure. */
export interface SessionRow {
  key: string;
  name: string;
  kind: string;
  /** The agent when it is not Claude Code (`agy`), for a small chip. Null for a Claude session. */
  agent: string | null;
  status: string;
  waitingFor: string | null;
  /** Who the wait is for: the owner, a peer session, or unknown. */
  waitingClass: 'owner' | 'peer' | null;
  since: string | null;
  copies: number;
  /** "2 copies" when the same session id runs twice (L16). */
  copyWarning: string | null;
}
export interface SessionsModel {
  /** True when `claude agents` failed and no other agent reports a session: the list is unknown (spec section 6). */
  unknown: boolean;
  error: string | null;
  rows: SessionRow[];
}

const RANK: Record<string, number> = { waiting: 0, busy: 1, working: 1, idle: 2 };

const toRow = (s: SessionEntry): SessionRow => ({
  key: s.key,
  name: s.name ?? s.session_id,
  kind: s.kind,
  agent: otherAgent(s),
  status: s.status,
  waitingFor: s.waiting_for,
  waitingClass: s.waiting_class,
  since: s.waiting_since,
  copies: s.copies,
  copyWarning: s.copies > 1 ? `${s.copies} copies` : null,
});

export function repoSessions(state: HubState, repo: RepoState): SessionsModel {
  const agents = state.sources.agents;
  // `claude agents` never loaded: its sessions are unknown, but other agents' status files still count.
  const failed = !agents.ok && agents.last_ok_at === null;
  const rows = state.sessions
    .filter((s) => samePath(s.repo_path, repo.path) && (!failed || otherAgent(s) !== null))
    .map(toRow)
    .sort((a, b) => {
      const owner = Number(b.waitingClass === 'owner') - Number(a.waitingClass === 'owner');
      return owner || (RANK[a.status] ?? 3) - (RANK[b.status] ?? 3) || a.name.localeCompare(b.name);
    });
  const unknown = failed && rows.length === 0;
  return { unknown, error: agents.ok ? null : agents.last_error, rows };
}
