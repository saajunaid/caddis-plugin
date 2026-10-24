import { asArray, mergingPr, ownerItemsOf, queueOf, type QueueEntry } from '../inbox/derive';
import { clockText } from '../shell/format';
import type { HubState, OwnerItem, RepoState, RequestView } from '../types';

/**
 * The repo Flow view model (R41). Pure, so vitest checks the order and every text.
 * The queue order is `queue_order` of `caddis_coordinate.py`: merging first, then hotfix items, then the rest;
 * inside a group, ready items that are not held by `entered_ready_at`, then the others in add order.
 */
export type FlowMode = 'live' | 'stopped' | 'down' | 'none';

export interface FlowItem extends QueueEntry {
  position: number;
  merging: boolean;
}
export interface DeployRow {
  pr: number;
  mergeSha: string;
  run: number | null;
  health: string;
  at: string | null;
  /** D1-D5 marks of the last deploy check run, or null when the coordinator stored none. */
  checks: { name: string; mark: string }[] | null;
  reason: string | null;
}
export interface FlowModel {
  mode: FlowMode;
  statusText: string;
  /** True when the queue is the last known one of a coordinator that is not live. */
  grey: boolean;
  merging: number | null;
  queue: FlowItem[];
  deploys: DeployRow[];
  owner: OwnerItem[];
  /** Open PRs that are not drafts and not in the queue. */
  unqueued: { number: number; title: string; requiredState: string; headSha: string }[];
  /** Newest first. */
  requests: RequestView[];
}

export const DEPLOY_CHECKS = ['D1', 'D2', 'D3', 'D4', 'D5'] as const;

const rec = (v: unknown): Record<string, unknown> =>
  v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};

export function orderQueue(queue: QueueEntry[]): QueueEntry[] {
  const rank = (q: QueueEntry, i: number): (number | string)[] => {
    if (q.state === 'merging') return [0, 0, 0, '', i];
    const group = q.hotfix ? 1 : 2;
    if (q.state === 'ready' && !q.held) return [group, 0, q.since ? 0 : 1, q.since ?? '', i];
    return [group, 1, 0, '', i];
  };
  return queue
    .map((q, i) => ({ q, r: rank(q, i) }))
    .sort((a, b) => {
      for (let k = 0; k < a.r.length; k++) {
        const x = a.r[k]!;
        const y = b.r[k]!;
        if (x < y) return -1;
        if (x > y) return 1;
      }
      return 0;
    })
    .map((x) => x.q);
}

export function flowMode(repo: RepoState): FlowMode {
  const c = repo.coordinator;
  if (!c) return 'none';
  if (c.status === 'stopped') return 'stopped';
  return c.responding ? 'live' : 'down';
}

export function flowStatusText(repo: RepoState): string {
  const c = repo.coordinator;
  const name = typeof rec(c?.coordinator_session).name === 'string' ? String(rec(c?.coordinator_session).name) : null;
  switch (flowMode(repo)) {
    case 'none':
      return 'No coordinator: each session merges its own PRs. Start one with /caddis:coordinate.';
    case 'stopped':
      return `Coordinator stopped at ${clockText(c?.stopped_at)}. The last known queue is greyed.`;
    case 'down':
      return `Coordinator not responding since ${clockText(c?.heartbeat_at)}. The last known queue is greyed.`;
    case 'live':
      return `Coordinator ${name ?? ''} live, heartbeat ${clockText(c?.heartbeat_at)}.`.replace('  ', ' ');
  }
}

function deployRows(repo: RepoState): DeployRow[] {
  const out: DeployRow[] = [];
  for (const raw of asArray(repo.coordinator?.deploy_checks)) {
    const d = rec(raw);
    if (typeof d.pr !== 'number') continue;
    const marks = rec(d.checks);
    const checks = Object.keys(marks).length
      ? DEPLOY_CHECKS.map((name) => ({ name, mark: typeof marks[name] === 'string' ? String(marks[name]) : 'skip' }))
      : null;
    out.push({
      pr: d.pr,
      mergeSha: typeof d.merge_sha === 'string' ? d.merge_sha.slice(0, 10) : '',
      run: typeof d.deploy_run === 'number' ? d.deploy_run : null,
      health: typeof d.health === 'string' ? d.health : 'unknown',
      at: typeof d.at === 'string' ? d.at : null,
      checks,
      reason: typeof d.reason === 'string' && d.reason ? d.reason : null,
    });
  }
  return out.reverse();
}

export function deriveFlow(_state: HubState, repo: RepoState): FlowModel {
  const mode = flowMode(repo);
  const mp = mergingPr(repo);
  const ordered = orderQueue(queueOf(repo));
  const queued = new Set(ordered.map((q) => q.pr));
  return {
    mode,
    statusText: flowStatusText(repo),
    grey: mode === 'stopped' || mode === 'down',
    merging: mode === 'live' ? mp : null,
    queue: ordered.map((q, i) => ({ ...q, position: i + 1, merging: q.state === 'merging' || q.pr === mp })),
    deploys: deployRows(repo),
    owner: ownerItemsOf(repo),
    unqueued: (repo.github?.prs ?? [])
      .filter((p) => !p.draft && !queued.has(p.number))
      .map((p) => ({ number: p.number, title: p.title, requiredState: p.required_state, headSha: p.head_sha })),
    requests: [...(repo.coordinator?.requests ?? [])].reverse(),
  };
}
