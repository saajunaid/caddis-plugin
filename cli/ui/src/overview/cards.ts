import { samePath } from '../inbox/derive';
import { isBusy } from '../inbox/headline';
import { deriveRoadmaps, gateCount, listRow } from '../repo/roadmap';
import { ageText } from '../shell/format';
import { repoBusy } from '../shell/repoHint';
import { repoHref, repoId } from '../shell/route';
import type { HubState, RepoState } from '../types';
import { deriveLane, type Lane, type LaneMode } from './lanes';

/** One repo card of the Overview (Aurora mockup B): a status, a roadmap line, sessions, and an open-PR ring. */
export interface RepoCard {
  id: string;
  name: string;
  href: string;
  tone: Lane['tone'];
  mode: LaneMode;
  status: string;
  statusTone: 'good' | 'warn' | 'bad' | 'muted';
  line: string;
  sessions: string;
  note: string | null;
  github: Lane['github'];
  prsOpen: number;
  prsPassing: number;
  ringLabel: string;
  foot: string;
}

const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;

function statusOf(state: HubState, repo: RepoState, lane: Lane): { status: string; statusTone: RepoCard['statusTone'] } {
  if (lane.mode === 'down') return { status: 'Coordinator down', statusTone: 'bad' };
  if (lane.mode === 'stopped') return { status: 'Coordinator stopped', statusTone: 'bad' };
  const gates = gateCount(deriveRoadmaps(repo));
  if (gates > 0) return { status: plural(gates, 'gate', 'gates'), statusTone: 'warn' };
  const owner = state.sessions.filter((s) => samePath(s.repo_path, repo.path) && s.waiting_class === 'owner').length;
  if (owner > 0) return { status: `${owner} waiting on you`, statusTone: 'warn' };
  const prs = repo.github?.prs ?? [];
  const failing = prs.filter((p) => p.required_state === 'fail').length;
  if (failing > 0) return { status: plural(failing, 'PR failing', 'PRs failing'), statusTone: 'bad' };
  if (repoBusy(state, repo)) return { status: 'Agent working', statusTone: 'good' };
  if (prs.length > 0) return { status: plural(prs.length, 'PR waiting', 'PRs waiting'), statusTone: 'muted' };
  return { status: 'Quiet', statusTone: 'muted' };
}

function lineOf(repo: RepoState): string {
  const m = deriveRoadmaps(repo);
  const first = m.roadmaps[0];
  if (first) {
    const row = listRow(first);
    return `Roadmap ${row.slug}: ${row.milestonesDone} of ${row.milestonesTotal} milestones`;
  }
  const open = m.plans.filter((p) => p.open > 0).length;
  return open > 0 ? plural(open, 'open plan', 'open plans') : 'No roadmap';
}

function newestMerge(repo: RepoState): string | null {
  let best: string | null = null;
  for (const m of repo.github?.merges ?? []) {
    if (!Number.isNaN(Date.parse(m.merged_at)) && (!best || Date.parse(m.merged_at) > Date.parse(best))) best = m.merged_at;
  }
  return best;
}

/** The Overview repo cards, one per repo, in repo order. Pure: no clock except `nowMs`. */
export function deriveRepoCards(state: HubState, nowMs: number): RepoCard[] {
  return state.repos.map((repo) => {
    const lane = deriveLane(state, repo, nowMs);
    const col = lane.columns.find((c) => c.id === 'sessions');
    const busy = state.sessions.filter((s) => samePath(s.repo_path, repo.path) && isBusy(s.status)).length;
    const sessions = col && col.cards.length > 0 ? `${plural(col.cards.length, 'session', 'sessions')} · ${busy} busy` : (col?.emptyText ?? '');
    const prs = repo.github?.prs ?? [];
    const prsOpen = prs.length;
    const prsPassing = prs.filter((p) => p.required_state === 'pass').length;
    const merged = newestMerge(repo);
    const id = repoId(repo);
    return {
      id,
      name: repo.name,
      href: repoHref(id),
      tone: lane.tone,
      mode: lane.mode,
      ...statusOf(state, repo, lane),
      line: lineOf(repo),
      sessions,
      note: lane.note,
      github: lane.github,
      prsOpen,
      prsPassing,
      ringLabel: prsOpen > 0 ? `${prsPassing}/${prsOpen}` : '0',
      foot: `${prsOpen > 0 ? plural(prsOpen, 'open PR', 'open PRs') : 'No open PRs'} · ${merged ? `shipped ${ageText(merged, nowMs)}` : 'never shipped'}`,
    };
  });
}

export interface LiveRow {
  key: string;
  name: string;
  repo: string;
  status: string;
}

/** The sessions of the Live now card: the busy ones, then the rest. */
export function deriveLive(state: HubState): { busy: LiveRow[]; other: LiveRow[] } {
  const busy: LiveRow[] = [];
  const other: LiveRow[] = [];
  for (const s of state.sessions) {
    const repo = state.repos.find((r) => samePath(r.path, s.repo_path));
    const tail = (s.repo_path ?? '').replace(/[\\/]+$/, '').split(/[\\/]/).pop() ?? '';
    const row: LiveRow = { key: s.key, name: s.name ?? s.session_id.slice(0, 8), repo: repo?.name ?? tail, status: s.status };
    (isBusy(s.status) ? busy : other).push(row);
  }
  return { busy, other };
}
