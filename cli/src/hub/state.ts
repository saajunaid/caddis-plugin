/**
 * State assembly and the source timers (R23, design sections 4, 6 and 9).
 *
 * The hub owns one copy of each source. Timers refresh them: the collector every 60 s, the sessions
 * every 30 s, GitHub per its `nextDelayMs()` (60 s, or 5 min below the rate reserve) and the
 * coordinator files every 30 s. Each timer is a `setTimeout` chain, so a refresh never overlaps
 * itself. A refresh that throws is caught and recorded. `getState()` joins the sources per repo.
 */
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { readAudit, type AuditEntry } from './audit.js';
import { addRepos, normalizeRepoPath, readConfig, readRegistry, repoKey } from './config.js';
import { createAgentsSource, type AgentsSource, type SessionEntry } from './sources/agents.js';
import { createCollectorSource, type CollectorSource, type Slot } from './sources/collector.js';
import { createCoordinatorSource, type CoordinatorEntry, type CoordinatorSource } from './sources/coordinator.js';
import { createGithubSource, type GithubRepoSlot, type GithubSource, type RateInfo } from './sources/github.js';
import { withTimeout } from './bounded.js';
import { bundleManifest, packageInfo } from '../util/pkg.js';
import { caddisHome } from '../util/sessions.js';

export const STATE_SCHEMA = 1;
export const STALE_AFTER_MS = 3 * 60_000;
export const COLLECTOR_EVERY_MS = 60_000;
export const AGENTS_EVERY_MS = 30_000;
export const COORDINATOR_EVERY_MS = 30_000;
const VERSIONS_TTL_MS = 60_000;
/**
 * The longest one refresh may take before its timer moves on. Each source bounds its own waits; this is a last
 * guard that keeps the timer chain alive. The collector needs 60 s plus a 2 s kill grace. GitHub makes many
 * bounded calls in a row, so it gets more time.
 */
export const REFRESH_CEILING_MS: Record<SourceName, number> = {
  collector: 90_000,
  agents: 90_000,
  github: 300_000,
  coordinator: 90_000,
};

export type SourceName = 'collector' | 'agents' | 'github' | 'coordinator';
export interface SourceStatus {
  ok: boolean;
  last_ok_at: string | null;
  last_error: string | null;
  stale: boolean;
}
export interface Versions {
  hub: string;
  pool: string | null;
  plugin: string | null;
}
/** A recommendation shown with an owner-only item (D16). It is never the approval. */
export interface Recommendation {
  decision: 'approve' | 'hold';
  reason: string | null;
  evidence: string | null;
}
/** An open owner-only item (R37): a coordinator ask, or a relay owner gate. */
export interface OwnerItem {
  /** Stable across polls. */
  id: string;
  /** The text an approve or decline request carries in `args.what`. */
  what: string;
  pr: number | null;
  head_sha: string | null;
  source: 'coordinator' | 'relay';
  recommendation: Recommendation | null;
  /** Who recommends: the coordinator session name, or the relay's session. */
  from: string | null;
  since: string | null;
  /** The relay name, for a relay gate. */
  relay?: string;
}
/** Whether the queue and approval buttons of a repo work, and why not (R33, R36). */
export interface RepoActions {
  enabled: boolean;
  code: 'ok' | 'no_coordinator' | 'bad_repo_id';
  reason: string | null;
}
export interface RepoState {
  path: string;
  name: string;
  repo_id?: string;
  pinned: boolean;
  /** The collector's error for this repo, when its last read failed. */
  error?: string;
  roadmaps: Slot | null;
  plans: Slot | null;
  relays: Slot | null;
  github: GithubRepoSlot | null;
  coordinator: CoordinatorEntry | null;
  owner_items: OwnerItem[];
  actions: RepoActions;
}
export interface HubState {
  schema: number;
  generated_at: string;
  versions: Versions;
  sources: Record<SourceName, SourceStatus>;
  update_needed: boolean;
  repos: RepoState[];
  sessions: SessionEntry[];
  spend: Slot | null;
  guide: Slot | null;
  /** GitHub quota left per account (R40). Empty before the first GitHub call. */
  github_rate: Record<string, RateInfo>;
  /** The last audit lines: owner actions and refusals (R51). */
  audit: AuditEntry[];
}
export interface HubOptions {
  home?: string;
  now?: () => number;
  collector?: CollectorSource;
  agents?: AgentsSource;
  github?: GithubSource;
  coordinator?: CoordinatorSource;
  versions?: () => Versions;
}
export interface StateHub {
  start(): void;
  stop(): void;
  getState(): HubState;
  /** Refresh every source once, in timer order. For tests and a first fill. */
  refreshAll(): Promise<void>;
  /** The repos the sources read: pinned first, then the registry, without hidden ones. */
  repoPaths(): string[];
}

/** `owner/name` to the hub key, the rule of `repo_id()` in `caddis_coordinate.py`. */
export function repoIdFor(nameWithOwner: string): string {
  return nameWithOwner.trim().toLowerCase().replace(/\//g, '__');
}

/** The id `caddis_coordinate.py` gives a repo with no remote: `local__<folder>__<6 hex of the path>`. */
export function localRepoId(repoPath: string): string {
  // Python `os.path.normcase`: lower case and backslashes on Windows, unchanged elsewhere.
  const norm = process.platform === 'win32' ? repoPath.toLowerCase().replace(/\//g, '\\') : repoPath;
  const digest = createHash('sha256').update(norm, 'utf8').digest('hex').slice(0, 6);
  return `local__${path.basename(repoPath)}__${digest}`;
}

/** The installed caddis plugin version from Claude Code's plugin list, or null. */
export function readPluginVersion(home: string): string | null {
  try {
    const file = path.join(home, '.claude', 'plugins', 'installed_plugins.json');
    const parsed = JSON.parse(readFileSync(file, 'utf8')) as { plugins?: Record<string, unknown> };
    for (const [key, entries] of Object.entries(parsed.plugins ?? {})) {
      if (!key.startsWith('caddis@') || !Array.isArray(entries)) continue;
      for (const e of entries) {
        const v = (e as { version?: unknown })?.version;
        if (typeof v === 'string' && v) return v;
      }
    }
  } catch {
    /* not installed, or not readable */
  }
  return null;
}

function defaultVersions(home: string): Versions {
  const pool = bundleManifest().poolVersion;
  return { hub: packageInfo().version, pool: pool === 'unknown' ? null : pool, plugin: readPluginVersion(home) };
}

const message = (e: unknown): string => (e instanceof Error ? e.message : String(e));

export const NO_COORDINATOR_REASON = 'No coordinator: each session merges its own PRs. Start one with /caddis:coordinate.';
export const STOPPED_REASON = 'The coordinator stopped. Start it again with /caddis:coordinate.';
export const DOWN_REASON = 'The coordinator is not responding. Actions wait until it is back.';

const RESERVED_NAMES = new Set([
  'con', 'prn', 'aux', 'nul',
  ...Array.from({ length: 9 }, (_, i) => `com${i + 1}`),
  ...Array.from({ length: 9 }, (_, i) => `lpt${i + 1}`),
]);

/**
 * A repo id names a folder under `<hub>/repos`. This is exactly `_repo_dir` of `caddis_coordinate.py`: refuse an
 * empty id, `.`, any `..`, `/`, `\` or `:`, a trailing dot or space, and a Windows device name (with any extension).
 */
export function safeRepoId(id: string): boolean {
  if (!id || id === '.' || id.includes('..') || /[/\\:]/.test(id) || /[. ]$/.test(id)) return false;
  return !RESERVED_NAMES.has(id.split('.', 1)[0]!.toLowerCase());
}
export const BAD_REPO_ID_REASON = 'This repo id cannot name a hub folder, so the hub cannot send it actions.';

/** R33, R36: actions need a live coordinator. The reason is the sentence the UI and the server refusal show. */
export function repoActions(coordinator: CoordinatorEntry | null, repoId?: string): RepoActions {
  if (repoId !== undefined && !safeRepoId(repoId)) return { enabled: false, code: 'bad_repo_id', reason: BAD_REPO_ID_REASON };
  if (!coordinator) return { enabled: false, code: 'no_coordinator', reason: NO_COORDINATOR_REASON };
  if (coordinator.update_needed) {
    return { enabled: false, code: 'no_coordinator', reason: 'The coordinator file is newer than this hub. Update the hub.' };
  }
  if (coordinator.status === 'stopped') return { enabled: false, code: 'no_coordinator', reason: STOPPED_REASON };
  if (coordinator.status !== 'live') return { enabled: false, code: 'no_coordinator', reason: DOWN_REASON };
  return { enabled: true, code: 'ok', reason: null };
}

const recOf = (v: unknown): Record<string, unknown> =>
  v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
const textOf = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v.trim() : null);

/** The `what` of a relay owner gate (R37): `owner gate <P>-OG<n> (<relay>)`. */
export const gateWhat = (gate: string, relay: string): string => `owner gate ${gate} (${relay})`;

/**
 * Open owner-only items of a repo (R37): the coordinator's asks, then relay OWNER-GATE lines. A relay gate whose
 * `what` the ledger holds is decided and left out. The same `what` twice is shown once (the ask wins).
 */
export function ownerItems(
  coordinator: CoordinatorEntry | null,
  relays: Slot | null,
  sessions: SessionEntry[],
): OwnerItem[] {
  const out: OwnerItem[] = [];
  const whats = new Set<string>();
  const from = textOf(recOf(coordinator?.coordinator_session).name);
  for (const raw of coordinator?.owner_asks ?? []) {
    const a = recOf(raw);
    const id = textOf(a.id);
    const what = textOf(a.what);
    if (!id || !what || whats.has(what)) continue;
    const decision = a.recommendation === 'approve' || a.recommendation === 'hold' ? a.recommendation : null;
    whats.add(what);
    out.push({
      id: `ask:${id}`,
      what,
      pr: typeof a.pr === 'number' && Number.isInteger(a.pr) ? a.pr : null,
      head_sha: textOf(a.head_sha),
      source: 'coordinator',
      recommendation: decision ? { decision, reason: textOf(a.reason), evidence: textOf(a.evidence) } : null,
      from: textOf(a.from) ?? from,
      since: textOf(a.at),
    });
  }
  const decided = new Set(
    (coordinator?.ledger ?? []).map((e) => textOf(recOf(e).what)).filter((w): w is string => w !== null),
  );
  const list = Array.isArray(relays?.relays) ? (relays.relays as unknown[]) : [];
  for (const raw of list) {
    const r = recOf(raw);
    const name = textOf(r.name);
    const gate = textOf(r.status_arg);
    if (r.status !== 'OWNER-GATE' || !name || !gate) continue;
    const what = gateWhat(gate, name);
    if (whats.has(what) || decided.has(what)) continue;
    whats.add(what);
    const rec = recOf(r.recommendation);
    const decision = rec.decision === 'approve' || rec.decision === 'hold' ? rec.decision : null;
    const sid = textOf(r.session_id);
    const session = sid ? sessions.find((s) => s.session_id === sid) : undefined;
    out.push({
      id: `gate:${name}:${gate}`,
      what,
      pr: null,
      head_sha: null,
      source: 'relay',
      recommendation: decision ? { decision, reason: textOf(rec.reason), evidence: textOf(rec.evidence) } : null,
      from: session?.name ?? name,
      since: textOf(r.updated_at),
      relay: name,
    });
  }
  return out;
}

export function createHub(opts: HubOptions = {}): StateHub {
  const home = opts.home ?? caddisHome();
  const now = opts.now ?? Date.now;

  const repoPaths = (): string[] => {
    const cfg = readConfig(home).value;
    const hidden = new Set(cfg.hidden.map((p) => repoKey(normalizeRepoPath(p))));
    const seen = new Set<string>();
    const out: string[] = [];
    const add = (p: string): void => {
      const n = normalizeRepoPath(p);
      const k = repoKey(n);
      if (hidden.has(k) || seen.has(k)) return;
      seen.add(k);
      out.push(n);
    };
    cfg.pinned.forEach(add);
    readRegistry(home).value.repos.forEach((r) => add(r.path));
    return out;
  };

  const collector = opts.collector ?? createCollectorSource({ repos: repoPaths, now });
  const agents = opts.agents ?? createAgentsSource({ now, home });
  const github =
    opts.github ?? createGithubSource({ repos: repoPaths, accounts: () => readConfig(home).value.accounts, now });
  const coordinator = opts.coordinator ?? createCoordinatorSource({ home, now });

  let versionsCache: { at: number; value: Versions } | null = null;
  const versions = (): Versions => {
    if (opts.versions) return opts.versions();
    if (!versionsCache || now() - versionsCache.at > VERSIONS_TTL_MS) {
      versionsCache = { at: now(), value: defaultVersions(home) };
    }
    return versionsCache.value;
  };

  // An error thrown by a refresh. Sources catch their own errors, so this is a last guard.
  const thrown = new Map<SourceName, string>();
  let coordinatorOkAt: number | null = null;

  const guarded = async (name: SourceName, run: () => Promise<void> | void): Promise<void> => {
    try {
      await withTimeout(Promise.resolve().then(run), REFRESH_CEILING_MS[name], 'refresh');
      thrown.delete(name);
      if (name === 'coordinator') coordinatorOkAt = now();
    } catch (e) {
      thrown.set(name, message(e));
    }
  };

  /** Add the repo of every live session to the registry (design section 4). */
  const registerSessionRepos = (): void => {
    const sessions = agents.get().data ?? [];
    const paths = sessions.map((s) => s.repo_path).filter((p): p is string => typeof p === 'string' && p !== '');
    if (!paths.length) return;
    try {
      // A corrupt registry is not overwritten: addRepos returns its error and writes nothing.
      addRepos(paths, home);
    } catch {
      /* a failed write is retried on the next sessions read */
    }
  };

  const refreshers: Record<SourceName, () => Promise<void>> = {
    agents: () =>
      guarded('agents', async () => {
        await agents.refresh();
        registerSessionRepos();
      }),
    collector: () => guarded('collector', () => collector.refresh()),
    github: () => guarded('github', () => github.refresh()),
    coordinator: () => guarded('coordinator', () => coordinator.refresh()),
  };
  const delays: Record<SourceName, () => number> = {
    agents: () => AGENTS_EVERY_MS,
    collector: () => COLLECTOR_EVERY_MS,
    github: () => github.nextDelayMs(),
    coordinator: () => COORDINATOR_EVERY_MS,
  };

  let running = false;
  const timers = new Map<SourceName, NodeJS.Timeout>();

  const schedule = (name: SourceName, delay: number): void => {
    if (!running) return;
    const timer = setTimeout(() => {
      timers.delete(name);
      void refreshers[name]().finally(() => {
        let next = AGENTS_EVERY_MS;
        try {
          next = delays[name]();
        } catch {
          /* keep the default */
        }
        schedule(name, next);
      });
    }, delay);
    timer.unref();
    timers.set(name, timer);
  };

  const status = (name: SourceName, s: { ok: boolean; last_ok_at: string | null; last_error: string | null }): SourceStatus => {
    const err = thrown.get(name);
    const okAt = s.last_ok_at === null ? null : Date.parse(s.last_ok_at);
    return {
      ok: s.ok && err === undefined,
      last_ok_at: s.last_ok_at,
      last_error: err ?? s.last_error,
      stale: okAt === null || Number.isNaN(okAt) || now() - okAt > STALE_AFTER_MS,
    };
  };

  const getState = (): HubState => {
    const col = collector.get();
    const ag = agents.get();
    const gh = github.get();
    const coord = coordinator.get();
    const pinned = new Set(readConfig(home).value.pinned.map((p) => repoKey(normalizeRepoPath(p))));
    const colByPath = new Map((col.data?.repos ?? []).map((r) => [repoKey(r.path), r]));
    const ghByPath = new Map((gh.data?.repos ?? []).map((r) => [repoKey(r.path), r]));
    const coordById = new Map(coord.map((c) => [c.repo_id, c]));

    const repos: RepoState[] = repoPaths().map((p) => {
      const k = repoKey(p);
      const c = colByPath.get(k);
      const g = ghByPath.get(k) ?? null;
      const repoId = g?.repo ? repoIdFor(g.repo) : g?.reason === 'no github remote' ? localRepoId(p) : undefined;
      const coordinator = repoId ? (coordById.get(repoId) ?? null) : null;
      const relays = c?.relays ?? null;
      const out: RepoState = {
        path: p,
        name: path.basename(p),
        pinned: pinned.has(k),
        roadmaps: c?.roadmaps ?? null,
        plans: c?.plans ?? null,
        relays,
        github: g,
        coordinator,
        owner_items: ownerItems(coordinator, relays, ag.data ?? []),
        actions: repoActions(coordinator, repoId),
      };
      if (repoId) out.repo_id = repoId;
      if (c?.error !== undefined) out.error = c.error;
      return out;
    });

    const coordOkAt = coordinatorOkAt === null ? null : new Date(coordinatorOkAt).toISOString();
    return {
      schema: STATE_SCHEMA,
      generated_at: new Date(now()).toISOString(),
      versions: versions(),
      sources: {
        collector: status('collector', col),
        agents: status('agents', ag),
        github: status('github', gh),
        coordinator: status('coordinator', { ok: coordOkAt !== null, last_ok_at: coordOkAt, last_error: null }),
      },
      update_needed: col.update_needed || coord.some((c) => c.update_needed),
      repos,
      sessions: ag.data ?? [],
      spend: col.data?.spend ?? null,
      guide: col.data?.guide ?? null,
      github_rate: gh.data?.rate ?? {},
      audit: readAudit(home),
    };
  };
  return {
    start(): void {
      if (running) return;
      running = true;
      schedule('coordinator', 0);
      // The first sessions read adds their repos to the registry. The collector and GitHub start after it.
      const first = setTimeout(() => {
        timers.delete('agents');
        void refreshers.agents().finally(() => {
          schedule('agents', AGENTS_EVERY_MS);
          schedule('collector', 0);
          schedule('github', 0);
        });
      }, 0);
      first.unref();
      timers.set('agents', first);
    },
    stop(): void {
      running = false;
      for (const timer of timers.values()) clearTimeout(timer);
      timers.clear();
    },
    getState,
    async refreshAll(): Promise<void> {
      await refreshers.agents();
      await refreshers.coordinator();
      await refreshers.collector();
      await refreshers.github();
    },
    repoPaths,
  };
}
