import type { OwnerItem, RepoState, RequestView } from '../types';
import type { LocalAction } from './useActions';

/**
 * Pure helpers for the action buttons (R33, R38, R41). No React here, so vitest covers every rule.
 * The server checks every action again; these rules only decide what the page offers.
 */
export type ActionName = 'hotfix' | 'unhotfix' | 'hold' | 'release' | 'approve' | 'decline';

export interface ActionBody {
  repo_id: string;
  action: ActionName;
  pr: number | null;
  head_sha: string | null;
  what?: string;
}

export interface ActionSpec {
  /** Local key: one per repo, action family and target. A new click on the same key replaces the old state. */
  key: string;
  label: string;
  body: ActionBody;
}

export const ACTION_LABEL: Record<ActionName, string> = {
  hotfix: 'Mark hotfix',
  unhotfix: 'Unmark hotfix',
  hold: 'Hold',
  release: 'Release',
  approve: 'Approve',
  decline: 'Decline',
};

const FAMILY: Record<ActionName, string> = {
  hotfix: 'hotfix',
  unhotfix: 'hotfix',
  hold: 'hold',
  release: 'hold',
  approve: 'approve',
  decline: 'approve',
};

/** The id the server uses for a repo; null for a repo it cannot act on (no GitHub or local id yet). */
export const actionRepoId = (repo: RepoState): string | null => repo.repo_id ?? null;

const keyOf = (repoId: string, action: ActionName, target: string | number): string => `${repoId}:${FAMILY[action]}:${target}`;

/** The queue buttons of one queue item: hotfix or unhotfix, then hold or release (spec 7, D5). */
export function queueSpecs(repo: RepoState, item: { pr: number; headSha: string; hotfix: boolean; held: boolean }): ActionSpec[] {
  const id = actionRepoId(repo);
  // The current GitHub head, as the server checks it; the queue's head lags until the coordinator's next cycle.
  const head = prHead(repo, item.pr) ?? item.headSha;
  if (!id || !head) return [];
  const make = (action: ActionName): ActionSpec => ({
    key: keyOf(id, action, item.pr),
    label: ACTION_LABEL[action],
    body: { repo_id: id, action, pr: item.pr, head_sha: head },
  });
  return [make(item.hotfix ? 'unhotfix' : 'hotfix'), make(item.held ? 'release' : 'hold')];
}

/** Approve and Decline for an owner-only item (spec 7a). The PR head goes with a PR item. */
export function ownerSpecs(repo: RepoState, item: OwnerItem): ActionSpec[] {
  const id = actionRepoId(repo);
  if (!id) return [];
  const head = item.pr !== null ? (prHead(repo, item.pr) ?? item.head_sha) : null;
  return (['approve', 'decline'] as const).map((action) => ({
    key: keyOf(id, action, item.what),
    label: ACTION_LABEL[action],
    body: { repo_id: id, action, pr: item.pr, head_sha: head, what: item.what },
  }));
}

/** The current head of an open PR from the cached GitHub list. */
export function prHead(repo: RepoState, pr: number): string | null {
  return repo.github?.prs?.find((p) => p.number === pr)?.head_sha ?? null;
}

/** Why the buttons of a repo are off, or null when they work (the server's own sentence, R33). */
export function disabledReason(repo: RepoState): string | null {
  if (!repo.actions) return 'Actions need a live coordinator.';
  return repo.actions.enabled ? null : (repo.actions.reason ?? 'Actions need a live coordinator.');
}

/** Why an owner item's buttons are off: the repo's reason, or a PR that is not in the queue (intake needs it). */
export function ownerDisabledReason(repo: RepoState, item: OwnerItem): string | null {
  const base = disabledReason(repo);
  if (base || item.pr === null) return base;
  const queued = (repo.coordinator?.queue ?? []).some((q) => (q as { pr?: unknown })?.pr === item.pr);
  return queued ? null : `PR #${item.pr} is not in the coordinator queue.`;
}

/** The newest request of the repo that matches a spec's family and target (R38). */
export function requestFor(repo: RepoState, spec: ActionSpec): RequestView | null {
  const all = repo.coordinator?.requests ?? [];
  const family = FAMILY[spec.body.action];
  for (let i = all.length - 1; i >= 0; i--) {
    const r = all[i]!;
    const a = r.action as ActionName;
    if (!(a in FAMILY) || FAMILY[a] !== family) continue;
    if (spec.body.what !== undefined ? r.what === spec.body.what && r.pr === spec.body.pr : r.pr === spec.body.pr) return r;
  }
  return null;
}

/** One line of text for a request's state (spec 7 rule 6). */
export function requestText(r: Pick<RequestView, 'action' | 'status' | 'reason'>): string {
  const what = ACTION_LABEL[r.action as ActionName] ?? r.action;
  switch (r.status) {
    case 'requested':
      return `${what}: requested. Waiting for the coordinator.`;
    case 'done':
      return `${what}: done.`;
    case 'rejected':
      return `${what}: rejected${r.reason ? `: ${r.reason}` : ''}.`;
    case 'expired':
      return `${what}: expired before the coordinator read it.`;
    case 'not_picked_up':
      return `${what}: not picked up. The coordinator has not read requests for 2 min.`;
  }
}

export const requestTone = (status: RequestView['status']): 'good' | 'warn' | 'bad' | 'muted' =>
  status === 'done' ? 'good' : status === 'requested' ? 'muted' : status === 'not_picked_up' ? 'warn' : 'bad';

/** The status line of one action key: the local click first, then the server's request view (R38). */
export function statusLine(repo: RepoState, spec: ActionSpec, local: LocalAction | undefined): { text: string; tone: string } | null {
  const server = requestFor(repo, spec);
  if (local?.status === 'sending') return { text: `${spec.label}: sending...`, tone: 'muted' };
  if (local?.status === 'refused') return { text: `${spec.label}: refused. ${local.reason ?? ''}`.trim(), tone: 'bad' };
  if (local?.status === 'sent' && (!server || server.id !== local.requestId)) {
    return { text: `${spec.label}: requested. Waiting for the coordinator.`, tone: 'muted' };
  }
  return server ? { text: requestText(server), tone: requestTone(server.status) } : null;
}
