import { createHash } from 'node:crypto';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { addRepos, normalizeRepoPath, readRegistry, resetHubCache, writeJsonAtomic } from '../../src/hub/config.js';
import { configPath } from '../../src/hub/paths.js';
import { createHub, localRepoId, repoIdFor, type HubOptions } from '../../src/hub/state.js';
import { createCollectorSource, type CollectorSource, type CollectorState } from '../../src/hub/sources/collector.js';
import type { AgentsSource, AgentsState, SessionEntry } from '../../src/hub/sources/agents.js';
import type { GithubSource, GithubState } from '../../src/hub/sources/github.js';
import type { CoordinatorEntry, CoordinatorSource } from '../../src/hub/sources/coordinator.js';
import { packageInfo } from '../../src/util/pkg.js';

let home: string;
let t: number;
const T0 = Date.parse('2026-10-24T10:00:00Z');
const now = (): number => t;
const iso = (ms: number): string => new Date(ms).toISOString();

beforeEach(() => {
  home = mkdtempSync(path.join(tmpdir(), 'caddis-hub-'));
  resetHubCache();
  t = T0;
});
afterEach(() => {
  vi.useRealTimers();
  resetHubCache();
  rmSync(home, { recursive: true, force: true });
});

function repo(name: string, remote?: string): string {
  const dir = path.join(home, 'src', name);
  mkdirSync(path.join(dir, '.git'), { recursive: true });
  if (remote) writeFileSync(path.join(dir, '.git', 'config'), `[remote "origin"]\n\turl = ${remote}\n`);
  return normalizeRepoPath(dir);
}

interface Counted {
  calls: number;
}
function fakeCollector(over: Partial<CollectorState> = {}): CollectorSource & Counted {
  const src = {
    calls: 0,
    refresh: async () => {
      src.calls += 1;
    },
    get: (): CollectorState => ({
      ok: true,
      last_ok_at: iso(t),
      last_error: null,
      stale: false,
      update_needed: false,
      data: { schema: 1, generated_at: iso(t), repos: [], spend: { total: 1 }, guide: { items: [] } },
      ...over,
    }),
  };
  return src;
}
function fakeAgents(sessions: SessionEntry[] = []): AgentsSource & Counted {
  const src = {
    calls: 0,
    refresh: async () => {
      src.calls += 1;
    },
    get: (): AgentsState => ({ ok: true, last_ok_at: iso(t), last_error: null, stale: false, data: sessions }),
  };
  return src;
}
function fakeGithub(delay = 60_000, data: GithubState['data'] = { repos: [], rate: {} }): GithubSource & Counted {
  const src = {
    calls: 0,
    refresh: async () => {
      src.calls += 1;
    },
    get: (): GithubState => ({ ok: true, last_ok_at: iso(t), last_error: null, stale: false, data }),
    nextDelayMs: () => delay,
  };
  return src;
}
function fakeCoordinator(entries: CoordinatorEntry[] = []): CoordinatorSource & Counted {
  const src = {
    calls: 0,
    refresh: () => {
      src.calls += 1;
    },
    get: () => entries,
  };
  return src;
}
const session = (repoPath: string | null): SessionEntry => ({
  key: '1:s1',
  pid: 1,
  session_id: 's1',
  name: 'demo-session',
  kind: 'interactive',
  cwd: repoPath,
  repo_path: repoPath,
  status: 'idle',
  waiting_for: null,
  waiting_class: null,
  waiting_since: null,
  copies: 1,
});
const coord = (repoId: string, over: Partial<CoordinatorEntry> = {}): CoordinatorEntry => ({
  repo_id: repoId,
  schema: 1,
  coordinator_session: null,
  heartbeat_at: null,
  heartbeat_age_s: null,
  responding: false,
  status: 'down',
  stopped_at: null,
  queue: [],
  merging_now: null,
  deploy_checks: [],
  ledger: [],
  processed_requests: [],
  owner_asks: [],
  requests: [],
  error: null,
  update_needed: false,
  ...over,
});

function hub(over: Partial<HubOptions> = {}) {
  return createHub({
    home,
    now,
    collector: fakeCollector(),
    agents: fakeAgents(),
    github: fakeGithub(),
    coordinator: fakeCoordinator(),
    versions: () => ({ hub: '0.0.0-test', pool: '1.0.0', plugin: null }),
    ...over,
  });
}

describe('repo ids', () => {
  it('maps owner/name the way caddis_coordinate.py repo_id does', () => {
    expect(repoIdFor('Acme/Shop')).toBe('acme__shop');
  });
  it('maps a repo with no remote to local__<folder>__<hash6>', () => {
    const p = path.join(home, 'src', 'shop');
    const norm = process.platform === 'win32' ? p.toLowerCase().replace(/\//g, '\\') : p;
    const hash = createHash('sha256').update(norm, 'utf8').digest('hex').slice(0, 6);
    expect(localRepoId(p)).toBe(`local__shop__${hash}`);
  });
});

describe('getState', () => {
  it('has the documented shape', async () => {
    const a = repo('shop', 'https://github.com/acme/shop.git');
    addRepos([a], home);
    const gh = fakeGithub(60_000, { repos: [{ path: a, repo: 'acme/shop', account: 'acme', prs: [], merges: [] }], rate: {} });
    const collector = fakeCollector({
      data: {
        schema: 1,
        generated_at: iso(t),
        repos: [{ path: a, fingerprint: 'f1', roadmaps: { items: 1 }, plans: { items: 2 }, relays: { items: 3 } }],
        spend: { total: 5 },
        guide: { items: [] },
      },
    });
    const h = hub({ collector, github: gh, coordinator: fakeCoordinator([coord('acme__shop', { responding: true })]) });
    await h.refreshAll();
    const s = h.getState();
    expect(Object.keys(s).sort()).toEqual(
      ['generated_at', 'github_rate', 'guide', 'repos', 'schema', 'sessions', 'sources', 'spend', 'update_needed', 'versions'].sort(),
    );
    expect(s.schema).toBe(1);
    expect(s.generated_at).toBe('2026-10-24T10:00:00.000Z');
    expect(s.versions).toEqual({ hub: '0.0.0-test', pool: '1.0.0', plugin: null });
    expect(Object.keys(s.sources).sort()).toEqual(['agents', 'collector', 'coordinator', 'github']);
    for (const src of Object.values(s.sources)) {
      expect(Object.keys(src).sort()).toEqual(['last_error', 'last_ok_at', 'ok', 'stale']);
    }
    expect(s.update_needed).toBe(false);
    expect(s.spend).toEqual({ total: 5 });
    expect(s.guide).toEqual({ items: [] });
    expect(s.repos).toHaveLength(1);
    const r = s.repos[0]!;
    expect(r).toMatchObject({
      path: a,
      name: 'shop',
      repo_id: 'acme__shop',
      roadmaps: { items: 1 },
      plans: { items: 2 },
      relays: { items: 3 },
      github: { repo: 'acme/shop', prs: [] },
      coordinator: { repo_id: 'acme__shop', responding: true },
    });
  });

  it('leaves hidden repos out and puts pinned repos first', async () => {
    const a = repo('alpha');
    const b = repo('beta');
    const c = repo('gamma');
    addRepos([a, b, c], home);
    writeJsonAtomic(configPath(home), { schema: 1, port: 1, accounts: {}, pinned: [c], hidden: [b + path.sep] });
    const h = hub();
    await h.refreshAll();
    expect(h.getState().repos.map((r) => r.name)).toEqual(['gamma', 'alpha']);
    expect(h.repoPaths()).toEqual([c, a]);
  });

  it('adds the repo of every live session to the registry', async () => {
    const a = repo('shop');
    const h = hub({ agents: fakeAgents([session(a), session(null)]) });
    expect(readRegistry(home).value.repos).toHaveLength(0);
    await h.refreshAll();
    expect(readRegistry(home).value.repos.map((r) => r.path)).toEqual([a]);
    expect(h.getState().repos.map((r) => r.path)).toEqual([a]);
    expect(h.getState().sessions).toHaveLength(1 + 1);
  });

  it('sets update_needed when any source reports a newer schema', async () => {
    const h1 = hub({ collector: fakeCollector({ update_needed: true }) });
    await h1.refreshAll();
    expect(h1.getState().update_needed).toBe(true);
    const h2 = hub({ coordinator: fakeCoordinator([coord('x', { update_needed: true })]) });
    await h2.refreshAll();
    expect(h2.getState().update_needed).toBe(true);
    const h3 = hub();
    await h3.refreshAll();
    expect(h3.getState().update_needed).toBe(false);
  });

  it('shows a failing source as stale after 3 min and keeps its last good data', async () => {
    const a = repo('shop');
    addRepos([a], home);
    const good = JSON.stringify({
      schema: 1,
      generated_at: iso(T0),
      repos: [{ path: a, fingerprint: 'f1', roadmaps: { items: 7 } }],
      spend: { total: 9 },
      guide: {},
    });
    let fail = false;
    const collector = createCollectorSource({
      repos: () => [a],
      python: 'python',
      scriptPath: 'collect.py',
      now,
      spawn: async () =>
        fail
          ? { ok: false, code: 1, stdout: '', stderr: 'boom', timedOut: false }
          : { ok: true, code: 0, stdout: good, stderr: '', timedOut: false },
    });
    const h = hub({ collector });
    await h.refreshAll();
    expect(h.getState().sources.collector).toMatchObject({ ok: true, stale: false, last_error: null });
    fail = true;
    t = T0 + 2 * 60_000;
    await h.refreshAll();
    expect(h.getState().sources.collector).toMatchObject({ ok: false, stale: false, last_ok_at: iso(T0) });
    t = T0 + 3 * 60_000 + 1_000;
    await h.refreshAll();
    const s = h.getState();
    expect(s.sources.collector).toMatchObject({ ok: false, stale: true, last_ok_at: iso(T0) });
    expect(s.sources.collector.last_error).toMatch(/boom/);
    expect(s.repos[0]!.roadmaps).toEqual({ items: 7 });
    expect(s.spend).toEqual({ total: 9 });
  });

  it('records a refresh that throws and keeps going', async () => {
    const agents = fakeAgents();
    agents.refresh = async () => {
      throw new Error('agents broke');
    };
    const h = hub({ agents });
    await h.refreshAll();
    expect(h.getState().sources.agents).toMatchObject({ ok: false, last_error: 'agents broke' });
    expect(h.getState().sources.collector.ok).toBe(true);
  });

  it('reads the pool and plugin versions by default', async () => {
    const plugins = path.join(home, '.claude', 'plugins');
    mkdirSync(plugins, { recursive: true });
    writeFileSync(
      path.join(plugins, 'installed_plugins.json'),
      JSON.stringify({ version: 2, plugins: { 'caddis@caddis': [{ scope: 'user', version: '1.3.99' }] } }),
    );
    const h = hub({ versions: undefined });
    expect(h.getState().versions.hub).toBe(packageInfo().version);
    expect(h.getState().versions.plugin).toBe('1.3.99');
  });
});

describe('timers', () => {
  it('fire on the R23 intervals', async () => {
    vi.useFakeTimers();
    const collector = fakeCollector();
    const agents = fakeAgents();
    const github = fakeGithub();
    const coordinator = fakeCoordinator();
    const h = hub({ collector, agents, github, coordinator });
    h.start();
    await vi.advanceTimersByTimeAsync(125_000);
    h.stop();
    expect(agents.calls).toBe(5); // 0, 30, 60, 90, 120 s
    expect(coordinator.calls).toBe(5);
    expect(collector.calls).toBe(3); // 0, 60, 120 s
    expect(github.calls).toBe(3);
    await vi.advanceTimersByTimeAsync(300_000);
    expect(agents.calls).toBe(5); // stopped
  });

  it('slows github to its nextDelayMs', async () => {
    vi.useFakeTimers();
    const github = fakeGithub(5 * 60_000);
    const h = hub({ github });
    h.start();
    await vi.advanceTimersByTimeAsync(299_000);
    expect(github.calls).toBe(1);
    await vi.advanceTimersByTimeAsync(2_000);
    h.stop();
    expect(github.calls).toBe(2);
  });

  it('never overlaps a slow refresh', async () => {
    vi.useFakeTimers();
    let active = 0;
    let peak = 0;
    let calls = 0;
    const agents = fakeAgents();
    agents.refresh = () => {
      calls += 1;
      active += 1;
      peak = Math.max(peak, active);
      return new Promise<void>((r) =>
        setTimeout(() => {
          active -= 1;
          r();
        }, 50_000),
      );
    };
    const h = hub({ agents });
    h.start();
    await vi.advanceTimersByTimeAsync(200_000);
    h.stop();
    expect(peak).toBe(1);
    expect(calls).toBe(3); // 0, 80, 160 s: each run waits for the last one, then 30 s
  });

  it('keeps the timer chain alive when a refresh never settles', async () => {
    vi.useFakeTimers();
    const agents = fakeAgents();
    let agentCalls = 0;
    agents.refresh = () => {
      agentCalls += 1;
      return new Promise<void>(() => {}); // never settles
    };
    const collector = fakeCollector();
    const github = fakeGithub();
    const h = hub({ agents, collector, github });
    h.start();
    await vi.advanceTimersByTimeAsync(89_000);
    expect(collector.calls).toBe(0); // the collector and GitHub wait for the first sessions read
    await vi.advanceTimersByTimeAsync(2_000);
    expect(h.getState().sources.agents.last_error).toBe('refresh did not finish in 90 s');
    expect(collector.calls).toBe(1);
    expect(github.calls).toBe(1);
    await vi.advanceTimersByTimeAsync(130_000); // 91 s + 30 s wait + 90 s ceiling
    h.stop();
    expect(agentCalls).toBe(2);
  });

  it('starts once and stops cleanly', async () => {
    vi.useFakeTimers();
    const agents = fakeAgents();
    const h = hub({ agents });
    h.start();
    h.start();
    await vi.advanceTimersByTimeAsync(1_000);
    expect(agents.calls).toBe(1);
    h.stop();
    h.stop();
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe('H3 state: owner items, actions, quota (R36, R37, R40)', () => {
  const ghWith = (a: string) =>
    fakeGithub(60_000, {
      repos: [{ path: a, repo: 'acme/shop', account: 'acme', prs: [], merges: [] }],
      rate: { acme: { remaining: 4321, reset_at: '2026-10-24T11:00:00Z' } },
    });
  const relays = (a: string, rows: unknown[]) =>
    fakeCollector({
      data: {
        schema: 1,
        generated_at: iso(t),
        repos: [{ path: a, fingerprint: 'f', relays: { schema: 1, relays: rows } }],
        spend: {},
        guide: {},
      },
    });
  const gate = {
    name: 'shop-schema',
    status: 'OWNER-GATE',
    status_arg: 'P2-OG1',
    session_id: 's1',
    updated_at: '2026-10-24T09:00:00Z',
    recommendation: { decision: 'approve', reason: 'Additive change.', evidence: 'tests green' },
  };

  it('github_rate comes from the GitHub source', async () => {
    const a = repo('shop', 'https://github.com/acme/shop.git');
    addRepos([a], home);
    const h = hub({ github: ghWith(a) });
    await h.refreshAll();
    expect(h.getState().github_rate).toEqual({ acme: { remaining: 4321, reset_at: '2026-10-24T11:00:00Z' } });
  });

  it('joins coordinator asks and relay gates; a decided gate drops out; from names the session', async () => {
    const a = repo('shop', 'https://github.com/acme/shop.git');
    addRepos([a], home);
    const ask = {
      id: 'ask-1',
      what: 'overnight agy run',
      pr: null,
      head_sha: null,
      recommendation: 'hold',
      reason: 'Over the cap.',
      evidence: 'estimate EUR 80',
      from: 'demo-coordinator',
      at: '2026-10-24T09:30:00Z',
    };
    const c = coord('acme__shop', { responding: true, status: 'live', owner_asks: [ask] });
    const h = hub({
      github: ghWith(a),
      collector: relays(a, [gate, { ...gate, name: 'other', status_arg: 'P3-OG1', session_id: null }]),
      agents: fakeAgents([{ ...session(a), name: 'demo-session-api' }]),
      coordinator: fakeCoordinator([c]),
    });
    await h.refreshAll();
    const items = h.getState().repos[0]!.owner_items;
    expect(items.map((i) => [i.id, i.what, i.source, i.from])).toEqual([
      ['ask:ask-1', 'overnight agy run', 'coordinator', 'demo-coordinator'],
      ['gate:shop-schema:P2-OG1', 'owner gate P2-OG1 (shop-schema)', 'relay', 'demo-session-api'],
      ['gate:other:P3-OG1', 'owner gate P3-OG1 (other)', 'relay', 'other'],
    ]);
    expect(items[1]!.recommendation).toEqual({ decision: 'approve', reason: 'Additive change.', evidence: 'tests green' });

    c.ledger = [{ what: 'owner gate P2-OG1 (shop-schema)', decision: 'approve' }];
    expect(h.getState().repos[0]!.owner_items.map((i) => i.id)).toEqual(['ask:ask-1', 'gate:other:P3-OG1']);
  });

  it('actions are on only with a live coordinator, with the reason otherwise', async () => {
    const a = repo('shop', 'https://github.com/acme/shop.git');
    addRepos([a], home);
    const c = coord('acme__shop', { responding: true, status: 'live' });
    const h = hub({ github: ghWith(a), coordinator: fakeCoordinator([c]) });
    await h.refreshAll();
    expect(h.getState().repos[0]!.actions).toEqual({ enabled: true, code: 'ok', reason: null });
    c.status = 'stopped';
    expect(h.getState().repos[0]!.actions.reason).toContain('stopped');
    c.status = 'down';
    expect(h.getState().repos[0]!.actions.reason).toContain('not responding');
    const none = hub({ github: ghWith(a) });
    await none.refreshAll();
    expect(none.getState().repos[0]!.actions).toMatchObject({ enabled: false, code: 'no_coordinator' });
    expect(none.getState().repos[0]!.actions.reason).toContain('No coordinator');
  });
});
