/**
 * The data allow-list of the Pages export (R59). Pure: no file, no process, no clock.
 *
 * The export page gets ONLY what `exportData` builds. It copies named keys and nothing else, so a key that a Python
 * parser adds later does not reach the page. A deny-list would leak it.
 *
 * `derivedDeny` collects the private values in the raw collector output. The privacy scan (R62 a) then looks for
 * them in the built files.
 */

export interface ExportOptions {
  /** Free text for the banner, or null. */
  label: string | null;
  /** `<owner>/<repo>` of the public GitHub repo, or null. Used for the PR links. */
  github: string | null;
  /** The commit the page is built from. Cut to 7 hex. */
  commit: string | null;
  /** UTC time of the build, ISO text. */
  now: string;
}

export interface ExportBlocker {
  type: string;
  reason: string;
  check: string;
}
export interface ExportPhase {
  ref: string;
  state: string;
  plan: string;
  num: number;
  name: string;
  model: string;
  lane: string;
  risk: string;
  tracker: string;
  tile: string;
  prs: number[];
}
export interface ExportMilestone {
  id: string;
  status: string;
  owner: string;
  target: string | null;
  depends: string[];
  blockers: ExportBlocker[];
  phases: ExportPhase[];
}
export interface ExportRoadmap {
  roadmap: string;
  branch: string | null;
  origin_commit: string | null;
  done: number;
  total: number;
  next: { milestone: string; plan: string; phase: number } | null;
  lanes: string[];
  waiting: { milestone: string; reason: string; check: string }[];
  milestones: ExportMilestone[];
  detail_error?: string;
}
export interface ExportRoadmapError {
  roadmap: string;
  error: string;
}
export interface ExportPlan {
  path: string;
  title: string;
  status: string;
  tracker: { phase: string; status: string }[];
  open_rows: number;
}
export interface ExportData {
  schema: 1;
  generated_at: string;
  label: string | null;
  github: string | null;
  commit: string | null;
  roadmaps: (ExportRoadmap | ExportRoadmapError)[];
  plans: ExportPlan[];
}

export const GITHUB_RE = /^[A-Za-z0-9-]+\/[A-Za-z0-9._-]+$/;
/** The text that replaces any error message: a message can hold a path or a host name. */
export const ERROR_TEXT = 'could not be read';

const rec = (v: unknown): Record<string, unknown> => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string => (typeof v === 'string' ? v : '');
const strOrNull = (v: unknown): string | null => (typeof v === 'string' && v ? v : null);
const int = (v: unknown): number => (typeof v === 'number' && Number.isInteger(v) ? v : 0);

/** A full SHA is cut to 7 characters. The scan flags a 40-hex string. */
const shortSha = (v: unknown): string | null => {
  const s = str(v);
  return /^[0-9a-fA-F]{7,}$/.test(s) ? s.slice(0, 7) : null;
};

function blocker(raw: unknown): ExportBlocker {
  const b = rec(raw);
  return { type: str(b.type), reason: str(b.reason), check: str(b.check) };
}

function phase(raw: unknown): ExportPhase {
  const p = rec(raw);
  return {
    ref: str(p.ref),
    state: str(p.state),
    plan: str(p.plan),
    num: int(p.num),
    name: str(p.name),
    model: str(p.model),
    lane: str(p.lane),
    risk: str(p.risk),
    tracker: str(p.tracker),
    tile: str(p.tile),
    prs: arr(p.prs).filter((n): n is number => typeof n === 'number' && Number.isInteger(n) && n > 0),
  };
}

function milestone(raw: unknown): ExportMilestone {
  const m = rec(raw);
  return {
    id: str(m.id),
    status: str(m.status),
    owner: str(m.owner),
    target: strOrNull(m.target),
    depends: arr(m.depends).filter((d): d is string => typeof d === 'string'),
    blockers: arr(m.blockers).map(blocker),
    phases: arr(m.phases).map(phase),
  };
}

function roadmap(raw: unknown): ExportRoadmap | ExportRoadmapError {
  const r = rec(raw);
  if (r.error !== undefined) return { roadmap: str(r.roadmap), error: ERROR_TEXT };
  const next = rec(r.next);
  const out: ExportRoadmap = {
    roadmap: str(r.roadmap),
    branch: strOrNull(r.branch),
    origin_commit: shortSha(r.origin_commit),
    done: int(r.done),
    total: int(r.total),
    next: Object.keys(next).length ? { milestone: str(next.milestone), plan: str(next.plan), phase: int(next.phase) } : null,
    lanes: arr(r.lanes).filter((l): l is string => typeof l === 'string'),
    waiting: arr(r.waiting).map((w) => {
      const x = rec(w);
      return { milestone: str(x.milestone), reason: str(x.reason), check: str(x.check) };
    }),
    milestones: arr(r.milestones).map(milestone),
  };
  if (r.detail_error !== undefined) out.detail_error = ERROR_TEXT;
  return out;
}

/** A plan path must be relative and under `.caddis/`. Anything else drops the plan. */
export function safePlanPath(p: string): boolean {
  if (!p.startsWith('.caddis/') || p.includes('\\') || p.includes('..') || p.includes(':')) return false;
  return !p.startsWith('/');
}

function plan(raw: unknown): ExportPlan | null {
  const p = rec(raw);
  if (p.error !== undefined || !safePlanPath(str(p.path))) return null;
  return {
    path: str(p.path),
    title: str(p.title),
    status: str(p.status),
    tracker: arr(p.tracker).map((t) => ({ phase: str(rec(t).phase), status: str(rec(t).status) })),
    open_rows: int(p.open_rows),
  };
}

/** The slot of the one repo in the collector output, or throws. */
function repoOf(collect: unknown): Record<string, unknown> {
  const repos = arr(rec(collect).repos);
  if (repos.length !== 1) throw new Error('the collector output must hold exactly one repo');
  const repo = rec(repos[0]);
  if (repo.error !== undefined) throw new Error('the collector could not read the repo');
  return repo;
}

export function exportData(collect: unknown, opts: ExportOptions): ExportData {
  if (opts.github !== null && !GITHUB_RE.test(opts.github)) throw new Error('--github must look like <owner>/<repo>');
  let commit: string | null = null;
  if (opts.commit !== null) {
    if (!/^[0-9a-fA-F]{7,40}$/.test(opts.commit)) throw new Error('--commit must be 7 to 40 hex characters');
    commit = opts.commit.slice(0, 7);
  }
  const repo = repoOf(collect);
  const slot = rec(repo.roadmaps);
  if (slot.error !== undefined) throw new Error('the roadmaps of the repo could not be read');
  return {
    schema: 1,
    generated_at: opts.now,
    label: opts.label,
    github: opts.github,
    commit,
    roadmaps: arr(slot.roadmaps).map(roadmap),
    plans: arr(rec(repo.plans).plans)
      .map(plan)
      .filter((p): p is ExportPlan => p !== null),
  };
}

export interface Machine {
  repoPath: string;
  home: string;
  user: string;
  host: string;
}

/** Names that many machines share. They would hit the page text ("owner: runner"), so they are skipped. */
const GENERIC_NAMES = new Set(['runner', 'root', 'user', 'users', 'admin', 'administrator', 'ubuntu', 'localhost', 'github']);

/**
 * The private values to look for in the built files (R62 a): runner hosts and pids from the raw collector output, the
 * repo path in both slash forms, the fingerprint, the home folder, the user name and the host name. Values shorter than
 * 3 characters are skipped. A generic user name is skipped.
 */
export function derivedDeny(collect: unknown, machine: Machine): string[] {
  const out = new Set<string>();
  const add = (v: unknown): void => {
    const s = typeof v === 'number' ? String(v) : typeof v === 'string' ? v.trim() : '';
    if (s.length >= 3) out.add(s);
  };
  const addPath = (v: unknown): void => {
    const s = str(v).trim();
    if (!s) return;
    add(s);
    add(s.replace(/\\/g, '/'));
    add(s.replace(/\//g, '\\'));
  };
  for (const raw of arr(rec(collect).repos)) {
    const repo = rec(raw);
    addPath(repo.path);
    add(repo.fingerprint);
    for (const rm of arr(rec(repo.roadmaps).roadmaps)) {
      const r = rec(rm);
      add(r.runner_host);
      for (const key of ['lock', 'stale_lock']) {
        const lock = rec(rec(r.runner)[key]);
        add(lock.host);
        add(lock.pid);
      }
    }
  }
  addPath(machine.repoPath);
  addPath(machine.home);
  add(machine.host);
  if (!GENERIC_NAMES.has(machine.user.toLowerCase())) add(machine.user);
  return [...out];
}
