import { readyGates } from '../repo/roadmap';
import type { HubState, OwnerItem, RepoState, SessionEntry, SourceName } from '../types';

/**
 * Inbox items, derived in the browser from one state snapshot (R29). Pure: no clock except `now`.
 * Sources (design section 5): sessions, relay STATUS lines, coordinator queue, GitHub PRs, source health.
 */
export type ItemKind = 'waiting' | 'owner-gate' | 'blocked' | 'blocked-merge' | 'coordinator' | 'hub';
export type Folder = 'needs' | 'approvals' | 'blocked' | 'resolved';

export interface InboxItem {
  /** Stable across polls: built from the source identity, never from a time or an index. */
  id: string;
  kind: ItemKind;
  folder: Exclude<Folder, 'resolved'>;
  repo: string;
  title: string;
  why: string;
  next: string;
  /** A command, path or session name the owner can copy. */
  cmd: string;
  /** ISO time the item began, or null when the source has none. */
  since: string | null;
  /** An owner-only item: Approve and Decline, with its recommendation (R37). */
  owner?: OwnerItem;
  /** A coordinator queue entry: Hotfix and Hold (spec 7). */
  queue?: { pr: number; headSha: string; hotfix: boolean; held: boolean };
  /** The state source this item comes from. A failing or stale source freezes its items. */
  source?: SourceName;
  /** The repo folder of a repo item. A per-repo read failure of its source freezes it too. */
  repoPath?: string;
  /** True while the item is kept from the last good read because its source is failing or stale. */
  stale?: boolean;
}

export interface Tiles {
  waitingOnYou: number;
  blockedMerges: number;
  inQueue: number;
  workingSessions: number;
  lastDeploy: { label: string; sub: string; ok: boolean | null } | null;
}

export interface InboxModel {
  items: InboxItem[];
  tiles: Tiles;
}

export const KIND_LABEL: Record<ItemKind, string> = {
  waiting: 'Waiting',
  'owner-gate': 'Owner gate',
  blocked: 'Blocked',
  'blocked-merge': 'Blocked merge',
  coordinator: 'Coordinator',
  hub: 'Hub',
};

const SOURCE_LABEL = {
  collector: 'Roadmap and relay data',
  agents: 'Session list',
  github: 'GitHub data',
  coordinator: 'Coordinator data',
} as const;

export const asArray = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const rec = (v: unknown): Record<string, unknown> =>
  v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null);
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/** `owner/name` when GitHub knows it, else the folder name. */
export const repoLabel = (r: RepoState): string => r.github?.repo ?? r.name;

const normPath = (p: string): string => p.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();
/** The agent of a session when it is not Claude Code (`agy`). Old state has no `agent`: Claude, so null. */
export const otherAgent = (s: SessionEntry): string | null => (s.agent && s.agent !== 'claude' ? s.agent : null);

export const samePath = (a: string | null | undefined, b: string | null | undefined): boolean =>
  !!a && !!b && normPath(a) === normPath(b);

export interface Relay {
  name: string;
  status: string;
  statusArg: string;
  updatedAt: string | null;
  nextStep: string | null;
}

/** The relays of a repo. A slot with an error or no list gives none. */
export function relaysOf(repo: RepoState): Relay[] {
  const out: Relay[] = [];
  for (const raw of asArray(repo.relays?.relays)) {
    const r = rec(raw);
    const name = str(r.name);
    const status = str(r.status);
    if (!name || !status) continue;
    out.push({ name, status, statusArg: str(r.status_arg) ?? '', updatedAt: str(r.updated_at), nextStep: str(r.next_step) });
  }
  return out;
}

/**
 * The open owner-only items of a repo (R37). The server joins them into `owner_items`; a state with no such list
 * (an older hub) falls back to the relay OWNER-GATE lines, with no recommendation.
 */
export function ownerItemsOf(repo: RepoState): OwnerItem[] {
  if (Array.isArray(repo.owner_items)) return repo.owner_items;
  return relaysOf(repo)
    .filter((r) => r.status === 'OWNER-GATE' && r.statusArg)
    .map((r) => ({
      id: `gate:${r.name}:${r.statusArg}`,
      what: `owner gate ${r.statusArg} (${r.name})`,
      pr: null,
      head_sha: null,
      source: 'relay' as const,
      recommendation: null,
      from: r.name,
      since: r.updatedAt,
      relay: r.name,
    }));
}

export interface QueueEntry {
  pr: number;
  headSha: string;
  title: string;
  state: string;
  whyWaiting: string;
  waitsOn: { repo: string; pr: number }[];
  hotfix: boolean;
  held: boolean;
  since: string | null;
}

export function queueOf(repo: RepoState): QueueEntry[] {
  const out: QueueEntry[] = [];
  for (const raw of asArray(repo.coordinator?.queue)) {
    const q = rec(raw);
    const pr = num(q.pr);
    if (pr === null) continue;
    const waitsOn: QueueEntry['waitsOn'] = [];
    for (const w of asArray(q.waits_on)) {
      const o = rec(w);
      const wpr = num(o.pr);
      if (wpr !== null) waitsOn.push({ repo: str(o.repo) ?? '', pr: wpr });
    }
    out.push({
      pr,
      headSha: str(q.head_sha) ?? '',
      title: str(q.title) ?? '',
      state: str(q.state) ?? 'waiting',
      whyWaiting: str(q.why_waiting) ?? '',
      waitsOn,
      hotfix: q.hotfix === true,
      held: q.held === true,
      since: str(q.entered_ready_at),
    });
  }
  return out;
}

/** The PR number a coordinator is merging, from `merging_now` (a number or an object with `pr`). */
export function mergingPr(repo: RepoState): number | null {
  const m = repo.coordinator?.merging_now;
  return num(m) ?? num(rec(m).pr);
}

function ownerSessions(sessions: SessionEntry[]): SessionEntry[] {
  const seen = new Set<string>();
  const out: SessionEntry[] = [];
  for (const s of sessions) {
    // Only a server-confirmed (debounced) owner wait counts. One item per session id.
    if (s.waiting_class !== 'owner' || seen.has(s.session_id)) continue;
    seen.add(s.session_id);
    out.push(s);
  }
  return out;
}

function lastDeploy(state: HubState, now: number): Tiles['lastDeploy'] {
  let best: { at: number; label: string; ok: boolean | null; how: string } | null = null;
  for (const r of state.repos) {
    const label = repoLabel(r);
    for (const raw of asArray(r.coordinator?.deploy_checks)) {
      const d = rec(raw);
      const at = Date.parse(str(d.at) ?? '');
      const pr = num(d.pr);
      if (Number.isNaN(at) || pr === null) continue;
      const health = str(d.health);
      if (!best || at > best.at) {
        best = {
          at,
          label: `${label} #${pr}`,
          ok: health === 'ok' ? true : health === 'failed' ? false : null,
          how: `health ${health ?? 'unknown'}`,
        };
      }
    }
    for (const m of r.github?.merges ?? []) {
      const at = Date.parse(m.merged_at);
      if (Number.isNaN(at) || (best && best.at >= at)) continue;
      const runs = m.runs ?? [];
      const failed = runs.some((x) => x.conclusion === 'failure');
      const done = runs.length > 0 && runs.every((x) => x.conclusion === 'success');
      best = {
        at,
        label: `${label} #${m.number}`,
        ok: failed ? false : done ? true : null,
        how: failed ? 'deploy failed' : done ? 'deploy pass' : 'merged',
      };
    }
  }
  if (!best) return null;
  const mins = Math.max(0, Math.round((now - best.at) / 60_000));
  const age = mins < 60 ? `${mins} min ago` : mins < 1440 ? `${Math.floor(mins / 60)} h ago` : `${Math.floor(mins / 1440)} d ago`;
  return { label: best.label, sub: `${age} · ${best.how}`, ok: best.ok };
}

function deriveTiles(state: HubState, now: number, items: InboxItem[]): Tiles {
  let inQueue = 0;
  // A down coordinator's queue is frozen, so it is not counted.
  for (const r of state.repos) if (r.coordinator?.responding) inQueue += queueOf(r).filter((q) => q.state !== 'blocked').length;
  const working = state.sessions.filter((s) => !['idle', 'done', 'unknown'].includes(s.status)).length;
  return {
    waitingOnYou: items.filter((i) => i.folder === 'needs').length,
    blockedMerges: items.filter((i) => i.kind === 'blocked-merge').length,
    inQueue,
    workingSessions: working,
    lastDeploy: lastDeploy(state, now),
  };
}

/** Local clock "HH:MM" for display, or "unknown". */
function clock(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? 'unknown' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

const prChecksCmd = (repo: RepoState, pr: number): string =>
  repo.github?.repo ? `gh pr checks ${pr} -R ${repo.github.repo}` : `gh pr checks ${pr}`;

export function deriveInbox(state: HubState, now: number): InboxModel {
  const items: InboxItem[] = [];
  const seen = new Set<string>();
  const add = (i: InboxItem): void => {
    if (seen.has(i.id)) return;
    seen.add(i.id);
    items.push(i);
  };
  const repoByPath = (p: string | null): RepoState | undefined => state.repos.find((r) => samePath(r.path, p));

  // 1. Session waiting on the owner.
  for (const s of ownerSessions(state.sessions)) {
    const repo = repoByPath(s.repo_path);
    const name = s.name ?? s.session_id.slice(0, 8);
    const agent = otherAgent(s);
    add({
      id: `waiting:${s.session_id}`,
      kind: 'waiting',
      folder: 'needs',
      repo: repo ? repoLabel(repo) : 'no repo',
      title: `${name}${agent ? ` (${agent})` : ''} waits on ${s.waiting_for ?? 'you'}`,
      why: 'The session cannot continue until you answer.',
      next: 'Open the session and answer.',
      cmd: name,
      since: s.waiting_since,
      source: 'agents',
    });
  }

  for (const repo of state.repos) {
    const label = repoLabel(repo);
    // 2. Owner-only items: coordinator asks and relay owner gates (R37).
    const relayList = relaysOf(repo);
    for (const o of ownerItemsOf(repo)) {
      const relay = o.relay ? relayList.find((r) => r.name === o.relay) : undefined;
      const gate = o.source === 'relay' ? /^owner gate (\S+) /.exec(o.what)?.[1] : undefined;
      add({
        id: `owner:${repo.path}:${o.id}`,
        kind: 'owner-gate',
        folder: 'approvals',
        repo: label,
        repoPath: repo.path,
        title: gate ? `Gate ${gate}: owner approval needed` : `${o.pr !== null ? `PR #${o.pr}: ` : ''}${o.what}`,
        why:
          o.source === 'relay'
            ? 'The plan stops at this owner gate. The next phase cannot start without you.'
            : 'This is on the owner-only list. Only your click approves it.',
        next: relay?.nextStep ?? (o.source === 'relay' ? 'Read the relay, then decide.' : 'Read the recommendation, then decide.'),
        cmd: o.relay ? `.caddis/relay/${o.relay}.md` : o.what,
        since: o.since,
        owner: o,
        source: o.source === 'relay' ? 'collector' : 'coordinator',
      });
    }
    // 2b. Roadmap owner gates whose milestone dependencies are done (design P24). It resolves when the roadmap
    // no longer names the gate: the owner records it with a docs PR (/caddis:roadmap).
    for (const g of readyGates(repo)) {
      add({
        id: `rmgate:${repo.path}:${g.id}`,
        kind: 'owner-gate',
        folder: 'approvals',
        repo: label,
        repoPath: repo.path,
        title: `Roadmap ${g.roadmap}, gate ${g.milestone}: ${g.reason}`,
        why: `Milestone ${g.milestone} of roadmap ${g.roadmap} waits for you. Everything before it is done.`,
        next: 'Decide, then record the gate in the roadmap with /caddis:roadmap (a docs PR).',
        cmd: g.check || '/caddis:roadmap',
        since: null,
        source: 'collector',
      });
    }
    // 3. Blocked work: relay STATUS: BLOCKED owner.
    for (const r of relayList) {
      if (r.status === 'BLOCKED' && r.statusArg.toLowerCase().startsWith('owner')) {
        add({
          id: `blocked:${repo.path}:${r.name}`,
          kind: 'blocked',
          folder: 'needs',
          repo: label,
          repoPath: repo.path,
          title: `Relay ${r.name}: STATUS: BLOCKED owner`,
          why: 'The relay says the owner must decide before the next step.',
          next: r.nextStep ?? 'Read the relay and decide.',
          cmd: `.caddis/relay/${r.name}.md`,
          since: r.updatedAt,
          source: 'collector',
        });
      }
    }

    // 4. Blocked merge: a blocked queue entry, or an open PR whose required checks failed.
    const live = !!repo.coordinator && repo.coordinator.responding;
    for (const q of queueOf(repo)) {
      if (q.state !== 'blocked') continue;
      add({
        id: `merge:${repo.path}:${q.pr}`,
        kind: 'blocked-merge',
        folder: 'blocked',
        repo: label,
        repoPath: repo.path,
        title: `PR #${q.pr}${q.title ? ` ${q.title}` : ''}: blocked`,
        why: q.whyWaiting || 'The coordinator skips it until it is unblocked.',
        next: 'Ask the PR session to fix it, or hold the PR.',
        cmd: prChecksCmd(repo, q.pr),
        since: q.since,
        queue: { pr: q.pr, headSha: q.headSha, hotfix: q.hotfix, held: q.held },
        source: 'coordinator',
      });
    }
    const queued = new Map(queueOf(repo).map((q) => [q.pr, q]));
    for (const pr of repo.github?.prs ?? []) {
      if (pr.draft || pr.required_state !== 'fail') continue;
      const failed = pr.checks.filter((c) => c.required && c.conclusion === 'failure').map((c) => c.name);
      const q = queued.get(pr.number);
      add({
        id: `merge:${repo.path}:${pr.number}`,
        kind: 'blocked-merge',
        folder: 'blocked',
        repo: label,
        repoPath: repo.path,
        title: `PR #${pr.number}: required check ${failed.length > 0 ? `${failed.join(', ')} ` : ''}failed`,
        why: live
          ? 'The coordinator skips it until the check passes at the head.'
          : 'This repo has no live coordinator, so its session merges its own PRs.',
        next: 'Fix the check in the PR session.',
        cmd: prChecksCmd(repo, pr.number),
        since: pr.updated_at,
        ...(q ? { queue: { pr: q.pr, headSha: q.headSha, hotfix: q.hotfix, held: q.held } } : {}),
        source: 'github',
      });
    }

    // 5. Coordinator problem: it wrote a heartbeat once, but not within 3 minutes. A clean stop is not one (R36).
    const c = repo.coordinator;
    if (c && !c.responding && c.heartbeat_at && c.status !== 'stopped') {
      add({
        id: `coordinator:${repo.path}`,
        kind: 'coordinator',
        folder: 'needs',
        repo: label,
        repoPath: repo.path,
        title: `Coordinator not responding since ${clock(c.heartbeat_at)}`,
        why: 'No heartbeat for 3 min. Its queue is frozen; the lane shows GitHub data.',
        next: 'Check the coordinator session, then restart it.',
        cmd: '/caddis:coordinate',
        since: c.heartbeat_at,
        source: 'coordinator',
      });
    }
  }

  // 6. Hub problem: a source has been failing for 3 min (not ok and stale).
  for (const name of ['collector', 'agents', 'github', 'coordinator'] as const) {
    const s = state.sources[name];
    if (s.ok || !s.stale) continue;
    add({
      id: `hub:${name}`,
      kind: 'hub',
      folder: 'needs',
      repo: 'hub',
      title: `${SOURCE_LABEL[name]} has failed for over 3 min`,
      why: s.last_error ?? 'The source has not answered.',
      next: 'Read the error. The hub keeps the last good data.',
      cmd: 'caddis hub status',
      since: s.last_ok_at,
    });
  }

  return { items, tiles: deriveTiles(state, now, items) };
}

// ---- Resolved history (localStorage, R29) ----

export const RESOLVED_TTL_MS = 24 * 3_600_000;
export interface ResolvedItem {
  item: InboxItem;
  resolvedAt: number;
}
export interface History {
  /** Items seen open on the last poll. */
  open: Record<string, InboxItem>;
  resolved: ResolvedItem[];
}
export const emptyHistory = (): History => ({ open: {}, resolved: [] });

/** A source that fails or is stale gives no trustworthy "item is gone" signal. */
export const sourceDown = (state: HubState, name: SourceName): boolean => {
  const s = state.sources?.[name];
  return !!s && (!s.ok || s.stale);
};

/**
 * A source can be up while one repo fails: no `gh` account can see it, or the collector's first read of it failed.
 * That repo then has an error and no data, so its items would vanish. Treat it as down for that repo's items.
 * A repo that keeps its last good data (an error beside `prs` or `relays`) still derives its items, so it is not down.
 */
export function repoSourceDown(state: HubState, item: InboxItem): boolean {
  if (!item.repoPath) return false;
  const repo = state.repos?.find((r) => samePath(r.path, item.repoPath));
  if (!repo) return false;
  if (item.source === 'github') {
    const g = repo.github;
    return !!g && typeof g.error === 'string' && !Array.isArray(g.prs);
  }
  if (item.source === 'collector') {
    const relays = rec(repo.relays);
    return (typeof repo.error === 'string' || typeof relays.error === 'string') && !Array.isArray(relays.relays);
  }
  return false;
}

/**
 * Keep the open items of a failing or stale source as they were, marked stale, until the source is back.
 * Without this, a `claude agents` failure would empty the session list and move every waiting item to Resolved.
 * An item that the live data still shows is not touched. Order: live items first, then the frozen ones.
 */
export function withFrozen(prevOpen: Record<string, InboxItem>, items: InboxItem[], state: HubState): InboxItem[] {
  const current = new Set(items.map((i) => i.id));
  const out = items.map((i) => (i.stale ? { ...i, stale: false } : i));
  for (const [id, item] of Object.entries(prevOpen)) {
    if (current.has(id) || !item.source) continue;
    if (!sourceDown(state, item.source) && !repoSourceDown(state, item)) continue;
    out.push({ ...item, stale: true });
  }
  return out;
}

/**
 * Compare the current items with the last poll. A vanished item moves to `resolved`.
 * A resolved item drops after 24 h, and when it comes back it is open again.
 */
export function reconcile(prev: History, items: InboxItem[], now: number): History {
  const current = new Map(items.map((i) => [i.id, i]));
  const resolved = prev.resolved.filter((r) => now - r.resolvedAt < RESOLVED_TTL_MS && !current.has(r.item.id));
  for (const [id, item] of Object.entries(prev.open)) {
    if (!current.has(id) && !resolved.some((r) => r.item.id === id)) resolved.push({ item, resolvedAt: now });
  }
  resolved.sort((a, b) => b.resolvedAt - a.resolvedAt);
  return { open: Object.fromEntries(current), resolved };
}

function isItem(v: unknown): v is InboxItem {
  const o = rec(v);
  return typeof o.id === 'string' && typeof o.title === 'string' && typeof o.kind === 'string' && typeof o.folder === 'string';
}

export function sanitizeHistory(raw: unknown): History {
  const o = rec(raw);
  const open: Record<string, InboxItem> = {};
  for (const [k, v] of Object.entries(rec(o.open))) if (isItem(v)) open[k] = v;
  const resolved: ResolvedItem[] = [];
  for (const r of asArray(o.resolved)) {
    const x = rec(r);
    const at = num(x.resolvedAt);
    if (isItem(x.item) && at !== null) resolved.push({ item: x.item, resolvedAt: at });
  }
  return { open, resolved };
}
