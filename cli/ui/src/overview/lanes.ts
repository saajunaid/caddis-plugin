import { mergingPr, otherAgent, queueOf, repoLabel, samePath, type QueueEntry } from '../inbox/derive';
import type { HubState, RepoState } from '../types';

export type Tone = 'good' | 'warn' | 'bad' | 'muted';
export interface Card {
  key: string;
  title: string;
  sub: string;
  tone: Tone;
  /** True for the last known queue of a coordinator that stopped. */
  grey?: boolean;
  /** A queue entry: the card gets the compact Hotfix and Hold buttons (R41). */
  queue?: { pr: number; headSha: string; hotfix: boolean; held: boolean };
}
export interface Column {
  id: 'sessions' | 'blocked' | 'waiting' | 'merging' | 'done';
  title: string;
  cards: Card[];
  emptyText: string;
}
export type LaneMode = 'coordinator' | 'none' | 'down' | 'stopped';
export interface Lane {
  id: string;
  name: string;
  mode: LaneMode;
  /** Dot colour of the repo. */
  tone: 'ok' | 'attention' | 'blocked' | 'idle';
  note: string | null;
  /** Set when `gh` fails for this repo: the account to sign in again and the command. */
  github: { account: string | null; error: string | null; command: string } | null;
  summary: string;
  columns: Column[];
}

export const NO_COORDINATOR_TEXT = 'No coordinator: each session merges its own PRs.';
export const NO_COORDINATOR_HINT = '/caddis:coordinate';
export const GH_LOGIN_COMMAND = 'gh auth login -h github.com';

const clock = (iso: string | null): string => {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime()) ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'unknown';
};

export const coordinatorDownText = (since: string | null): string => `Coordinator not responding since ${clock(since)}`;
export const coordinatorStoppedText = (at: string | null): string => `Coordinator stopped at ${clock(at)}`;

function ago(iso: string | null | undefined, now: number): string {
  const t = iso ? Date.parse(iso) : NaN;
  if (Number.isNaN(t)) return 'unknown';
  const m = Math.max(0, Math.round((now - t) / 60_000));
  if (m < 60) return `${m} min ago`;
  if (m < 1440) return `${Math.floor(m / 60)} h ago`;
  return `${Math.floor(m / 1440)} d ago`;
}

const sessionSub = (status: string, waitingFor: string | null, waitingClass: string | null): { sub: string; tone: Tone } => {
  if (status === 'waiting') return { sub: `waiting: ${waitingFor ?? 'unknown'}`, tone: waitingClass === 'peer' ? 'muted' : 'warn' };
  if (status === 'busy' || status === 'running' || status === 'working') return { sub: 'busy', tone: 'good' };
  return { sub: status, tone: 'muted' };
};

const queueCard = (q: QueueEntry, grey: boolean): Card => {
  const why = q.whyWaiting || q.state;
  const bits = [q.hotfix ? 'hotfix' : '', q.held && !why.includes('held') ? 'held' : '', why].filter(Boolean);
  return {
    key: `q${q.pr}`,
    title: `#${q.pr} ${q.title}`.trim(),
    sub: grey ? 'last known queue' : bits.join(' · '),
    tone: q.hotfix || q.held ? 'warn' : 'muted',
    grey,
    queue: { pr: q.pr, headSha: q.headSha, hotfix: q.hotfix, held: q.held },
  };
};

export function deriveLane(state: HubState, repo: RepoState, now: number): Lane {
  const coord = repo.coordinator;
  const mode: LaneMode = !coord ? 'none' : coord.status === 'stopped' ? 'stopped' : coord.responding ? 'coordinator' : 'down';
  const label = repoLabel(repo);

  const sessions: Card[] = state.sessions
    .filter((s) => samePath(s.repo_path, repo.path))
    .map((s) => {
      const v = sessionSub(s.status, s.waiting_for, s.waiting_class);
      const agent = otherAgent(s);
      return { key: `s${s.session_id}`, title: s.name ?? s.session_id.slice(0, 8), sub: agent ? `${agent} · ${v.sub}` : v.sub, tone: v.tone };
    });

  const blocked: Card[] = [];
  const blockedPrs = new Set<number>();
  for (const pr of repo.github?.prs ?? []) {
    if (pr.draft || pr.required_state !== 'fail') continue;
    const failed = pr.checks.filter((c) => c.required && c.conclusion === 'failure').map((c) => c.name);
    blockedPrs.add(pr.number);
    blocked.push({
      key: `b${pr.number}`,
      title: `#${pr.number} ${pr.title}`,
      sub: failed.length > 0 ? `${failed.join(', ')} failed` : 'required check failed',
      tone: 'bad',
    });
  }

  const queue = queueOf(repo);
  const waiting: Card[] = [];
  const merging: Card[] = [];
  if (mode === 'coordinator') {
    const mp = mergingPr(repo);
    for (const q of queue) {
      if (q.state === 'blocked') {
        if (!blockedPrs.has(q.pr)) {
          blockedPrs.add(q.pr);
          blocked.push({ key: `b${q.pr}`, title: `#${q.pr} ${q.title}`.trim(), sub: q.whyWaiting || 'blocked', tone: 'bad' });
        }
      } else if (q.state === 'merging' || q.pr === mp) {
        merging.push(queueCard(q, false));
      } else {
        waiting.push(queueCard(q, false));
      }
    }
  } else if (mode === 'down' || mode === 'stopped') {
    // The frozen queue stays visible, greyed. The Blocked column keeps GitHub truth only.
    for (const q of queue) if (q.state !== 'blocked') waiting.push(queueCard(q, true));
  }

  const done: Card[] = (repo.github?.merges ?? [])
    .slice()
    .sort((a, b) => Date.parse(b.merged_at) - Date.parse(a.merged_at))
    .slice(0, 3)
    .map((m) => {
      const runs = m.runs ?? [];
      const failed = runs.some((r) => r.conclusion === 'failure');
      const ok = runs.length > 0 && runs.every((r) => r.conclusion === 'success');
      const when = ago(m.merged_at, now);
      return {
        key: `d${m.number}`,
        title: `#${m.number} ${m.title}`,
        sub: failed ? `deploy failed · ${when}` : ok ? `deployed ${when}` : `merged ${when}`,
        tone: failed ? 'bad' : ok ? 'good' : 'muted',
      } as Card;
    });

  let note: string | null = null;
  if (mode === 'none') note = `${NO_COORDINATOR_TEXT} Start one with ${NO_COORDINATOR_HINT}.`;
  else if (mode === 'down') note = `${coordinatorDownText(coord?.heartbeat_at ?? null)}. The lane shows GitHub data; the last known queue is greyed.`;
  else if (mode === 'stopped') {
    note = `${coordinatorStoppedText(coord?.stopped_at ?? null)}. Each session merges its own PRs until one starts again (/caddis:coordinate). The last known queue is greyed.`;
  }

  const agentsDown = state.sources?.agents ? !state.sources.agents.ok : false;
  const gh = repo.github?.error
    ? { account: repo.github.account ?? null, error: repo.github.error, command: GH_LOGIN_COMMAND }
    : null;

  let summary: string;
  if (mode === 'down') summary = coordinatorDownText(coord?.heartbeat_at ?? null);
  else if (mode === 'stopped') summary = coordinatorStoppedText(coord?.stopped_at ?? null);
  else {
    const parts = [
      mode === 'none' ? 'No coordinator' : '',
      agentsDown ? 'sessions unknown' : sessions.length > 0 ? `${sessions.length} session${sessions.length === 1 ? '' : 's'}` : 'no sessions running',
      blocked.length > 0 ? `${blocked.length} blocked` : '',
      waiting.length > 0 ? `${waiting.length} waiting` : '',
      merging.length > 0 ? `${merging.length} merging` : '',
      done.length > 0 ? `${done.length} deployed` : '',
    ];
    summary = parts.filter(Boolean).join(' · ');
  }

  const anyOwnerWait = state.sessions.some((s) => samePath(s.repo_path, repo.path) && s.waiting_class === 'owner');
  const tone: Lane['tone'] =
    mode === 'down' || repo.error || repo.github?.error
      ? 'blocked'
      : anyOwnerWait
        ? 'attention'
        : mode === 'none' || mode === 'stopped'
          ? 'idle'
          : 'ok';

  return {
    id: repo.path,
    name: label,
    mode,
    tone,
    note,
    github: gh,
    summary,
    columns: [
      { id: 'sessions', title: 'Sessions', cards: sessions, emptyText: agentsDown ? 'Sessions unknown: "claude agents" failed' : 'No sessions running' },
      { id: 'blocked', title: 'Blocked', cards: blocked, emptyText: 'None' },
      {
        id: 'waiting',
        title: 'Waiting for its turn',
        cards: waiting,
        emptyText: mode === 'none' ? NO_COORDINATOR_TEXT : 'None',
      },
      { id: 'merging', title: 'Merging now', cards: merging, emptyText: 'None' },
      { id: 'done', title: 'Done and deployed', cards: done, emptyText: 'None' },
    ],
  };
}

export const deriveLanes = (state: HubState, now: number): Lane[] => state.repos.map((r) => deriveLane(state, r, now));
