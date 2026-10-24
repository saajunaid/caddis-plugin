import { asArray, repoLabel } from '../inbox/derive';
import type { Tone } from '../overview/lanes';
import { repoId } from '../shell/route';
import { DEPLOY_CHECKS } from '../repo/flow';
import type { AuditEntry, HubState, RepoState } from '../types';

/**
 * The Activity model (R52, R53, spec section 5 page 4 and 7a). Pure: one function turns the state into events,
 * newest first. Every event has a stable id, so the page keeps its place across polls.
 */
export type Kind = 'merge' | 'deploy' | 'health' | 'owner' | 'coordinator' | 'approval';
export const KINDS: Kind[] = ['merge', 'deploy', 'health', 'owner', 'coordinator', 'approval'];
export const KIND_LABEL: Record<Kind, string> = {
  merge: 'Merges',
  deploy: 'Deploys',
  health: 'Health checks',
  owner: 'Your actions',
  coordinator: 'Coordinator results',
  approval: 'Routine approvals',
};
export const PAGE_SIZE = 100;

export interface ActivityEvent {
  id: string;
  kind: Kind;
  /** The repo id the hub uses (`repo_id`, else the path). */
  repo: string;
  repoLabel: string;
  /** UTC ISO time. */
  at: string;
  ms: number;
  text: string;
  detail: string | null;
  tone: Tone;
  pr: number | null;
  prUrl: string | null;
}

const rec = (v: unknown): Record<string, unknown> => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {});
const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null);
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isInteger(v) ? v : null);

export const repoIdOf = repoId;
const prUrl = (repo: RepoState | undefined, pr: number | null): string | null =>
  repo?.github?.repo && pr !== null ? `https://github.com/${repo.github.repo}/pull/${pr}` : null;

const ACTION_VERB: Record<string, string> = {
  hotfix: 'marked as hotfix',
  unhotfix: 'unmarked as hotfix',
  hold: 'held',
  release: 'released',
  approve: 'approved',
  decline: 'declined',
};

/** "You held #214", "You approved: spend over 50 EUR". */
export function ownerText(a: AuditEntry): string {
  const verb = a.action ? (ACTION_VERB[a.action] ?? a.action) : 'sent a request';
  const target = a.pr !== null ? ` #${a.pr}` : a.what ? `: ${a.what}` : '';
  return a.result === 'refused' ? `Refused: you ${verb}${target}` : `You ${verb}${target}`;
}

export function deriveActivity(state: HubState): ActivityEvent[] {
  const out: ActivityEvent[] = [];
  const byId = new Map(state.repos.map((r) => [repoIdOf(r), r]));
  const labelOf = (id: string): string => {
    const r = byId.get(id);
    return r ? repoLabel(r) : id.replace('__', '/');
  };
  const push = (e: Omit<ActivityEvent, 'ms' | 'repoLabel'>): void => {
    const ms = Date.parse(e.at);
    if (Number.isNaN(ms)) return;
    out.push({ ...e, ms, repoLabel: labelOf(e.repo) });
  };

  for (const repo of state.repos) {
    const id = repoIdOf(repo);
    const checked = new Set<number>();

    // Deploy checks of the coordinator: a deploy event with D1-D5, and a health event (R52).
    for (const raw of asArray(repo.coordinator?.deploy_checks)) {
      const d = rec(raw);
      const pr = num(d.pr);
      const at = str(d.at);
      if (pr === null || !at) continue;
      const sha = (str(d.merge_sha) ?? '').toLowerCase();
      checked.add(pr);
      const marks = rec(d.checks);
      const hasMarks = Object.keys(marks).length > 0;
      const markText = hasMarks ? DEPLOY_CHECKS.map((n) => `${n} ${str(marks[n]) ?? 'skip'}`).join(' · ') : null;
      const failed = hasMarks && DEPLOY_CHECKS.some((n) => marks[n] === 'fail');
      const run = num(d.deploy_run);
      push({
        id: `deploy:${id}:${pr}:${sha}`,
        kind: 'deploy',
        repo: id,
        at,
        text: `Deploy check for #${pr}`,
        detail: [markText, run !== null ? `run ${run}` : null, str(d.reason)].filter(Boolean).join(' · ') || null,
        tone: failed ? 'bad' : hasMarks ? 'good' : 'muted',
        pr,
        prUrl: prUrl(repo, pr),
      });
      const health = str(d.health);
      if (health === 'ok' || health === 'failed') {
        push({
          id: `health:${id}:${pr}:${sha}`,
          kind: 'health',
          repo: id,
          at,
          text: `Health check ${health} for #${pr}`,
          detail: null,
          tone: health === 'ok' ? 'good' : 'bad',
          pr,
          prUrl: prUrl(repo, pr),
        });
      }
    }

    // Merges from GitHub; deploy runs of a merge that has no coordinator deploy check.
    for (const m of repo.github?.merges ?? []) {
      push({
        id: `merge:${id}:${m.number}:${m.merge_sha.toLowerCase()}`,
        kind: 'merge',
        repo: id,
        at: m.merged_at,
        text: `Merged #${m.number} ${m.title}`,
        detail: m.merge_sha.slice(0, 10),
        tone: 'good',
        pr: m.number,
        prUrl: prUrl(repo, m.number),
      });
      if (!checked.has(m.number) && m.runs.length) {
        const bad = m.runs.some((r) => r.conclusion === 'failure' || r.conclusion === 'cancelled');
        const pending = m.runs.some((r) => r.status !== 'completed');
        push({
          id: `deploy-runs:${id}:${m.number}:${m.merge_sha.toLowerCase()}`,
          kind: 'deploy',
          repo: id,
          at: m.merged_at,
          text: `Deploy runs for #${m.number}`,
          detail: m.runs.map((r) => `${r.name} ${r.status === 'completed' ? (r.conclusion ?? 'done') : r.status}`).join(' · '),
          tone: bad ? 'bad' : pending ? 'muted' : 'good',
          pr: m.number,
          prUrl: prUrl(repo, m.number),
        });
      }
    }

    // Coordinator results: processed requests joined with the request view for the action and the PR.
    const requests = new Map((repo.coordinator?.requests ?? []).map((r) => [r.id, r]));
    for (const raw of asArray(repo.coordinator?.processed_requests)) {
      const p = rec(raw);
      const rid = str(p.id);
      const at = str(p.at);
      const result = str(p.result);
      if (!rid || !at || !result) continue;
      const req = requests.get(rid);
      const what = req ? `${ACTION_VERB[req.action] ?? req.action}${req.pr !== null ? ` #${req.pr}` : req.what ? `: ${req.what}` : ''}` : `request ${rid.slice(0, 8)}`;
      push({
        id: `result:${id}:${rid}`,
        kind: 'coordinator',
        repo: id,
        at,
        text: `Coordinator ${result}: ${what}`,
        detail: str(p.reason),
        tone: result === 'done' ? 'good' : result === 'rejected' ? 'bad' : 'warn',
        pr: req?.pr ?? null,
        prUrl: prUrl(repo, req?.pr ?? null),
      });
    }

    // Routine approvals: the coordinator's own ledger entries, with its reason (spec 7a).
    // Owner approvals are not repeated: their audit line and result line show.
    for (const raw of asArray(repo.coordinator?.ledger)) {
      const e = rec(raw);
      const at = str(e.at);
      const what = str(e.what);
      if (e.approved_by !== 'coordinator' || !at || !what) continue;
      push({
        id: `ledger:${id}:${at}:${what}`,
        kind: 'approval',
        repo: id,
        at,
        text: `Coordinator ${e.decision === 'decline' ? 'declined' : 'approved'}: ${what}`,
        detail: str(e.reason),
        tone: e.decision === 'decline' ? 'warn' : 'good',
        pr: null,
        prUrl: null,
      });
    }
  }

  // Owner actions from the audit tail (R51).
  // The id is the line's own fields; a repeated line gets a counter, so ids hold when the 200-line window moves.
  const seen = new Map<string, number>();
  asArray(state.audit).forEach((raw) => {
    const a = raw as AuditEntry;
    const repoId = a.repo ?? 'unknown';
    const base = `audit:${a.at}:${a.request_id ?? 'x'}:${a.action ?? ''}:${a.result ?? ''}`;
    const n = (seen.get(base) ?? 0) + 1;
    seen.set(base, n);
    push({
      id: n === 1 ? base : `${base}:${n}`,
      kind: 'owner',
      repo: repoId,
      at: a.at,
      text: ownerText(a),
      detail: a.reason,
      tone: a.result === 'refused' ? 'warn' : 'muted',
      pr: a.pr,
      prUrl: prUrl(byId.get(repoId), a.pr),
    });
  });

  return out.sort((x, y) => y.ms - x.ms || (x.id < y.id ? -1 : 1));
}

export interface ActivityFilter {
  /** A repo id, or null for all repos. */
  repo: string | null;
  /** The kinds to show; empty means all. */
  kinds: ReadonlySet<Kind>;
}
export const noFilter = (): ActivityFilter => ({ repo: null, kinds: new Set() });

export function filterActivity(events: ActivityEvent[], f: ActivityFilter): ActivityEvent[] {
  return events.filter((e) => (f.repo === null || e.repo === f.repo) && (f.kinds.size === 0 || f.kinds.has(e.kind)));
}
