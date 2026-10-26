import type { HubState, RepoState } from '../types';

const asArray = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);

/**
 * The repo Roadmap tab model (R45-R49). Pure, so vitest checks every row of the parity checklist.
 * The data is the collector's `roadmaps_json` and `plans_json` output (Python parsers, L7). The UI never reads a
 * roadmap, a plan or a Tracker file.
 */
export type Tile = 'todo' | 'in-progress' | 'done' | 'moved' | 'blocked';
export type Tone = 'good' | 'warn' | 'bad' | 'muted';

export const TILE_LABEL: Record<Tile, string> = {
  todo: 'to do',
  'in-progress': 'in progress',
  done: 'done',
  moved: 'moved',
  blocked: 'blocked',
};
const FINISHED = new Set(['done', 'not-needed']);

export const NO_ROADMAP_TEXT = 'No roadmap or plan';
export const NO_ROADMAP_HINT = '/caddis:roadmap';

export interface PrLink {
  number: number;
  /** Built from the repo's GitHub slot (R46). Null when the hub has no slot. */
  url: string | null;
  /** "in review" or "merged" from the slot, else null. */
  stage: 'in review' | 'merged' | null;
  /** The required-check state of an open PR. */
  detail: string | null;
}
export interface PhaseView {
  ref: string;
  plan: string;
  num: number;
  name: string;
  model: string;
  lane: string;
  risk: string;
  highRisk: boolean;
  tracker: string;
  tile: Tile;
  prs: PrLink[];
  /** The one-line stage: the PR stages, else the tile label (R46). */
  stage: string;
}
export interface Blocker {
  milestone: string;
  type: string;
  reason: string;
  check: string;
}
export interface MilestoneView {
  id: string;
  status: string;
  owner: string;
  target: string | null;
  depends: string[];
  phases: PhaseView[];
  blockers: Blocker[];
  done: number;
  total: number;
  tone: 'done' | 'wait' | 'block' | 'prog' | 'todo';
}
export interface PlanLane {
  plan: string;
  done: number;
  total: number;
}
export interface RunnerView {
  running: { batch: string; since: string | null; host: string | null; pid: string | null } | null;
  staleBatch: string | null;
  lastStop: string | null;
  /** UTC time of the last stop record, shown as local time (L22). */
  lastStopAt: string | null;
  /** The stop reason alone, for the list card. */
  stopReason: string | null;
  errors: string[];
  next: string | null;
}
export interface Kpis {
  phasesDone: number;
  phasesTotal: number;
  milestonesDone: number;
  milestonesTotal: number;
  inProgress: string[];
  highRisk: number;
  next: string;
}
export interface Board {
  now: MilestoneView[];
  next: MilestoneView[];
  later: MilestoneView[];
}
export interface RoadmapModel {
  slug: string;
  branch: string | null;
  originCommit: string | null;
  milestones: MilestoneView[];
  lanes: PlanLane[];
  /** Open owner gates (the `waiting` key, else the unfinished milestones' owner-gate blockers). */
  gates: Blocker[];
  blockers: Blocker[];
  kpis: Kpis;
  board: Board;
  runner: RunnerView;
  /** Why the detail keys are missing (the collector's `detail_error`), or null. */
  detailError: string | null;
}
export interface RoadmapError {
  slug: string;
  error: string;
}
export interface PlanRow {
  phase: string;
  status: string;
  /** The collector's state for the Status cell (caddis_status.py); `todo` when the data has none. */
  state: Tile;
}
export interface PlanView {
  path: string;
  title: string;
  rows: PlanRow[];
  open: number;
}
/** The kanban columns of a plan board. A `moved` row sits in Done, greyed. */
export type PlanColumn = 'todo' | 'in-progress' | 'blocked' | 'done';
export const PLAN_COLUMNS: { key: PlanColumn; label: string }[] = [
  { key: 'todo', label: 'To do' },
  { key: 'in-progress', label: 'In progress' },
  { key: 'blocked', label: 'Blocked' },
  { key: 'done', label: 'Done' },
];
export function planColumns(p: PlanView): Record<PlanColumn, PlanRow[]> {
  const cols: Record<PlanColumn, PlanRow[]> = { todo: [], 'in-progress': [], blocked: [], done: [] };
  for (const row of p.rows) cols[row.state === 'moved' ? 'done' : row.state].push(row);
  return cols;
}
export interface RepoRoadmaps {
  mode: 'roadmaps' | 'plans' | 'none' | 'error';
  roadmaps: RoadmapModel[];
  errors: RoadmapError[];
  plans: PlanView[];
  /** Open plans with Tracker rows that no roadmap names, shown as boards under the roadmaps. */
  otherPlans: PlanView[];
  /** The collector's error for this repo, shown instead of data. */
  repoError: string | null;
}

const rec = (v: unknown): Record<string, unknown> => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {});
const str = (v: unknown): string => (typeof v === 'string' ? v : '');
const strOrNull = (v: unknown): string | null => (typeof v === 'string' && v ? v : null);
const int = (v: unknown): number => (typeof v === 'number' && Number.isInteger(v) ? v : 0);

const TILES = new Set<string>(['todo', 'in-progress', 'done', 'moved', 'blocked']);

function prLinks(repo: RepoState, numbers: unknown): PrLink[] {
  const gh = repo.github;
  return [...new Set(asArray(numbers).filter((n): n is number => typeof n === 'number' && Number.isInteger(n)))].map((n) => {
    const open = gh?.prs?.find((p) => p.number === n);
    const merged = gh?.merges?.some((m) => m.number === n) ?? false;
    return {
      number: n,
      url: gh?.repo ? `https://github.com/${gh.repo}/pull/${n}` : null,
      stage: open ? 'in review' : merged ? 'merged' : null,
      detail: open ? `required checks ${open.required_state}` : null,
    };
  });
}

function phaseView(repo: RepoState, raw: unknown): PhaseView {
  const p = rec(raw);
  const ref = str(p.ref);
  const hash = ref.lastIndexOf('#');
  const state = str(p.state);
  const tile: Tile = TILES.has(str(p.tile)) ? (str(p.tile) as Tile) : state === 'done' ? 'done' : 'todo';
  const risk = str(p.risk);
  const prs = prLinks(repo, p.prs);
  const stages = prs.filter((l) => l.stage).map((l) => `#${l.number} ${l.stage}${l.detail ? ` (${l.detail})` : ''}`);
  return {
    ref,
    plan: str(p.plan) || (hash > 0 ? ref.slice(0, hash) : ''),
    num: int(p.num) || (hash > 0 ? Number(ref.slice(hash + 1)) || 0 : 0),
    name: str(p.name) || ref,
    model: str(p.model),
    lane: str(p.lane),
    risk,
    highRisk: risk.toLowerCase().includes('high'),
    tracker: str(p.tracker),
    tile,
    prs,
    stage: stages.length ? stages.join(', ') : TILE_LABEL[tile],
  };
}

const blockerOf = (milestone: string, raw: unknown): Blocker => {
  const b = rec(raw);
  return { milestone, type: str(b.type), reason: str(b.reason), check: str(b.check) };
};

function msTone(status: string, blockers: Blocker[]): MilestoneView['tone'] {
  if (FINISHED.has(status)) return 'done';
  if (blockers.some((b) => b.type === 'owner-gate')) return 'wait';
  if (blockers.length || status === 'blocked') return 'block';
  return status === 'in-progress' ? 'prog' : 'todo';
}

const isDone = (t: Tile): boolean => t === 'done' || t === 'moved';

function runnerView(raw: unknown, next: string | null): RunnerView {
  const r = rec(raw);
  const lock = rec(r.lock);
  const stale = rec(r.stale_lock);
  const stop = rec(r.last_stop);
  let lastStop: string | null = null;
  if (str(stop.reason) === 'running') lastStop = 'running now';
  else if (str(stop.reason)) lastStop = `${str(stop.reason)}${stop.exit !== undefined && stop.exit !== null ? ` (exit ${String(stop.exit)})` : ''}`;
  return {
    running: Object.keys(lock).length
      ? { batch: String(lock.batch ?? ''), since: strOrNull(lock.started_utc), host: strOrNull(lock.host), pid: lock.pid === undefined ? null : String(lock.pid) }
      : null,
    staleBatch: Object.keys(stale).length ? String(stale.batch ?? '') : null,
    lastStop,
    lastStopAt: strOrNull(stop.utc),
    stopReason: str(stop.reason) || null,
    errors: asArray(r.errors).map(String),
    next,
  };
}

function buildBoard(milestones: MilestoneView[]): Board {
  const status = new Map(milestones.map((m) => [m.id, m.status]));
  const board: Board = { now: [], next: [], later: [] };
  for (const m of milestones) {
    if (FINISHED.has(m.status)) continue;
    const ready = m.depends.every((d) => FINISHED.has(status.get(d) ?? ''));
    if (m.status === 'in-progress' || (ready && m.blockers.length === 0)) board.now.push(m);
    else if (m.depends.some((d) => board.now.some((n) => n.id === d))) board.next.push(m);
    else board.later.push(m);
  }
  return board;
}

export function roadmapModel(repo: RepoState, raw: unknown): RoadmapModel {
  const r = rec(raw);
  const milestones: MilestoneView[] = asArray(r.milestones).map((mRaw) => {
    const m = rec(mRaw);
    const id = str(m.id);
    const blockers = asArray(m.blockers).map((b) => blockerOf(id, b));
    const phases = asArray(m.phases).map((p) => phaseView(repo, p));
    const status = str(m.status);
    return {
      id,
      status,
      owner: str(m.owner) || 'runner',
      target: strOrNull(m.target),
      depends: asArray(m.depends).map(String),
      phases,
      blockers,
      done: phases.filter((p) => isDone(p.tile)).length,
      total: phases.length,
      tone: msTone(status, blockers),
    };
  });
  const phases = milestones.flatMap((m) => m.phases);
  const nxt = rec(r.next);
  const nextText = Object.keys(nxt).length ? `${str(nxt.milestone)} ${str(nxt.plan)}#${String(nxt.phase)}` : null;
  const lanes: PlanLane[] = (asArray(r.lanes).length ? asArray(r.lanes).map(String) : [...new Set(phases.map((p) => p.plan))]).map((plan) => ({
    plan,
    done: phases.filter((p) => p.plan === plan && isDone(p.tile)).length,
    total: phases.filter((p) => p.plan === plan).length,
  }));
  const blockers = milestones.flatMap((m) => m.blockers);
  const gates = Array.isArray(r.waiting)
    ? asArray(r.waiting).map((w) => blockerOf(str(rec(w).milestone), { ...rec(w), type: 'owner-gate' }))
    : milestones.filter((m) => !FINISHED.has(m.status)).flatMap((m) => m.blockers.filter((b) => b.type === 'owner-gate'));
  return {
    slug: str(r.roadmap),
    branch: strOrNull(r.branch),
    originCommit: strOrNull(r.origin_commit),
    milestones,
    lanes,
    gates,
    blockers,
    kpis: {
      phasesDone: phases.filter((p) => isDone(p.tile)).length,
      phasesTotal: phases.length,
      milestonesDone: int(r.done) || milestones.filter((m) => FINISHED.has(m.status)).length,
      milestonesTotal: int(r.total) || milestones.length,
      inProgress: phases.filter((p) => p.tile === 'in-progress').map((p) => p.ref),
      highRisk: phases.filter((p) => p.highRisk).length,
      next: nextText ?? 'none ready',
    },
    board: buildBoard(milestones),
    runner: runnerView(r.runner, nextText),
    detailError: strOrNull(r.detail_error),
  };
}

const tileOf = (v: unknown): Tile => (typeof v === 'string' && TILES.has(v) ? (v as Tile) : 'todo');

/** The file stem of a plan path: the name a roadmap lane uses. */
const planStem = (path: string): string => (path.split('/').pop() ?? '').replace(/\.md$/, '');

function planViews(raw: unknown): PlanView[] {
  return asArray(rec(raw).plans)
    .map((p) => rec(p))
    .filter((p) => !p.error && !['done', 'closed', 'archived'].includes(str(p.status).toLowerCase()))
    .map((p) => ({
      path: str(p.path),
      title: str(p.title) || str(p.path),
      rows: asArray(p.tracker).map((t) => ({ phase: str(rec(t).phase), status: str(rec(t).status), state: tileOf(rec(t).state) })),
      open: int(p.open_rows),
    }));
}

/** The Roadmap tab model of one repo (R48, R49). */
export function deriveRoadmaps(repo: RepoState): RepoRoadmaps {
  const slot = rec(repo.roadmaps);
  const repoError = strOrNull(repo.error) ?? strOrNull(slot.error);
  const roadmaps: RoadmapModel[] = [];
  const errors: RoadmapError[] = [];
  for (const raw of asArray(slot.roadmaps)) {
    const e = rec(raw);
    if (str(e.error)) errors.push({ slug: str(e.roadmap), error: str(e.error) });
    else if (str(e.roadmap)) roadmaps.push(roadmapModel(repo, e));
  }
  const plans = planViews(repo.plans);
  const named = new Set(roadmaps.flatMap((r) => r.lanes.map((l) => l.plan)));
  const otherPlans = plans.filter((p) => p.rows.length > 0 && p.open > 0 && !named.has(planStem(p.path)));
  const base = { roadmaps, errors, plans, otherPlans, repoError };
  if (roadmaps.length || errors.length) return { mode: 'roadmaps', ...base };
  if (repoError && !repo.roadmaps && !repo.plans) return { mode: 'error', ...base };
  if (plans.length) return { mode: 'plans', ...base };
  return { mode: repoError ? 'error' : 'none', ...base };
}

/** One roadmap opens directly; several, or any read error, show the list (R48). */
export const opensDirectly = (m: RepoRoadmaps): boolean => m.mode === 'roadmaps' && m.roadmaps.length === 1 && m.errors.length === 0;

export interface ListRow {
  slug: string;
  branch: string | null;
  milestonesDone: number;
  milestonesTotal: number;
  phasesDone: number;
  phasesTotal: number;
  pct: number;
  next: string;
  runner: string;
  gates: number;
  dots: { id: string; status: string }[];
  tone: 'wait' | 'block' | 'done' | 'prog' | 'todo';
}

/** The list card of one roadmap (parity P17). */
export function listRow(m: RoadmapModel): ListRow {
  const blocked = m.milestones.flatMap((x) => x.phases).filter((p) => p.tile === 'blocked').length;
  const { phasesDone, phasesTotal } = m.kpis;
  const tone = m.gates.length ? 'wait' : blocked ? 'block' : phasesTotal && phasesDone >= phasesTotal ? 'done' : m.kpis.inProgress.length || phasesDone ? 'prog' : 'todo';
  const run = m.runner;
  return {
    slug: m.slug,
    branch: m.branch,
    milestonesDone: m.kpis.milestonesDone,
    milestonesTotal: m.kpis.milestonesTotal,
    phasesDone,
    phasesTotal,
    pct: phasesTotal ? Math.round((100 * phasesDone) / phasesTotal) : 0,
    next: m.runner.next ?? 'none ready',
    runner: run.running || run.stopReason === 'running' ? 'running' : run.stopReason ? `stopped: ${run.stopReason}` : 'idle',
    gates: m.gates.length,
    dots: m.milestones.map((x) => ({ id: x.id, status: x.status })),
    tone,
  };
}

export interface ReadyGate {
  roadmap: string;
  milestone: string;
  reason: string;
  check: string;
  /** Stable across polls: roadmap, milestone and the gate's place among that milestone's gates. */
  id: string;
}

/**
 * Owner gates of unfinished milestones whose dependencies are all finished: the gates the owner can act on now (P24).
 * One that waits behind an open dependency is not an Inbox item yet. It leaves this list when the roadmap no longer
 * names it (the gate is recorded) or its milestone is finished.
 */
export function readyGates(repo: RepoState): ReadyGate[] {
  const out: ReadyGate[] = [];
  for (const r of deriveRoadmaps(repo).roadmaps) {
    const status = new Map(r.milestones.map((m) => [m.id, m.status]));
    for (const m of r.milestones) {
      if (FINISHED.has(m.status) || !m.depends.every((d) => FINISHED.has(status.get(d) ?? ''))) continue;
      m.blockers
        .filter((b) => b.type === 'owner-gate')
        .forEach((b, i) => out.push({ roadmap: r.slug, milestone: m.id, reason: b.reason, check: b.check, id: `${r.slug}:${m.id}:${i}` }));
    }
  }
  return out;
}

/** Open owner gates over every roadmap of a repo: the Roadmap tab label count (parity P3). */
export const gateCount = (m: RepoRoadmaps): number => m.roadmaps.reduce((n, r) => n + r.gates.length, 0);

export interface Match {
  /** Milestone ids to show, and to open. */
  milestones: Set<string>;
  /** Phase refs to show. */
  phases: Set<string>;
  count: number;
}

const has = (hay: string, q: string): boolean => hay.toLowerCase().includes(q);

/**
 * Search (parity P16). A phase matches on its ref, name, model, lane, risk, Tracker cell and PR numbers; a milestone on
 * its id, status, owner and target. A milestone that matches shows all its phases. Empty text gives null (no filter).
 */
export function filterRoadmap(m: RoadmapModel, text: string): Match | null {
  const q = text.trim().toLowerCase();
  if (!q) return null;
  const out: Match = { milestones: new Set(), phases: new Set(), count: 0 };
  for (const ms of m.milestones) {
    const own = has([ms.id, ms.status, ms.owner, ms.target ?? ''].join(' '), q);
    let hit = false;
    for (const p of ms.phases) {
      const match = has([p.ref, p.name, p.model, p.lane, p.risk, p.tracker, p.prs.map((x) => `#${x.number}`).join(' ')].join(' '), q);
      if (match || own) {
        out.phases.add(p.ref);
        hit = true;
      }
      if (match) out.count += 1;
    }
    if (own) out.count += 1;
    if (own || hit) out.milestones.add(ms.id);
  }
  return out;
}

/** The label of the Roadmap tab: the gate count joins it (parity P3). */
export function roadmapTabLabel(repo: RepoState): string {
  const n = gateCount(deriveRoadmaps(repo));
  return n > 0 ? `Roadmap · ${n} gate${n === 1 ? '' : 's'}` : 'Roadmap';
}

/** The data of the Roadmap tab is old when the collector source is down or stale (spec section 6). */
export const collectorStale = (state: HubState): boolean => !state.sources.collector.ok || state.sources.collector.stale;
