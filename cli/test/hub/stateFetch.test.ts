import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { addRepos, normalizeRepoPath, resetHubCache } from '../../src/hub/config.js';
import { FETCH_CONCURRENCY, PERIODIC_FETCH_MS, type FetchResult, type GitFetcher } from '../../src/hub/gitFetch.js';
import { createHub, type HubOptions } from '../../src/hub/state.js';
import type { AgentsSource, AgentsState, SessionEntry } from '../../src/hub/sources/agents.js';
import type { CollectorSource, CollectorState } from '../../src/hub/sources/collector.js';
import type { CoordinatorEntry, CoordinatorSource } from '../../src/hub/sources/coordinator.js';
import type { GithubRepoSlot, GithubSource, GithubState, MergeEntry, PrEntry } from '../../src/hub/sources/github.js';

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
  resetHubCache();
  rmSync(home, { recursive: true, force: true });
});

function repo(name: string, remote?: string): string {
  const dir = path.join(home, 'src', name);
  mkdirSync(path.join(dir, '.git'), { recursive: true });
  writeFileSync(path.join(dir, '.git', 'HEAD'), 'ref: refs/heads/main\n');
  if (remote) writeFileSync(path.join(dir, '.git', 'config'), `[remote "origin"]\n\turl = ${remote}\n`);
  return normalizeRepoPath(dir);
}

interface Counted {
  calls: number;
}

function fakeCollector(over: Partial<CollectorState> = {}, onRefresh?: () => void): CollectorSource & Counted {
  const src = {
    calls: 0,
    refresh: async () => {
      src.calls += 1;
      onRefresh?.();
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

function fakeAgents(sessions: SessionEntry[] = [], onRefresh?: () => void): AgentsSource & Counted {
  const src = {
    calls: 0,
    refresh: async () => {
      src.calls += 1;
      onRefresh?.();
    },
    get: (): AgentsState => ({ ok: true, last_ok_at: iso(t), last_error: null, stale: false, data: sessions }),
  };
  return src;
}

function fakeGithub(
  getData: () => GithubState['data'],
  onRefresh?: () => void,
): GithubSource & Counted {
  const src = {
    calls: 0,
    refresh: async () => {
      src.calls += 1;
      onRefresh?.();
    },
    get: (): GithubState => ({ ok: true, last_ok_at: iso(t), last_error: null, stale: false, data: getData() }),
    nextDelayMs: () => 60_000,
  };
  return src;
}

function fakeCoordinator(entries: CoordinatorEntry[] = [], onRefresh?: () => void): CoordinatorSource & Counted {
  const src = {
    calls: 0,
    refresh: () => {
      src.calls += 1;
      onRefresh?.();
    },
    get: () => entries,
  };
  return src;
}

function fakeFetcher(
  impl: (repoPath: string) => Promise<FetchResult> | FetchResult = (p) => ({ path: p, status: 'fetched' }),
): GitFetcher & { fetches: string[] } {
  const fetches: string[] = [];
  return {
    fetches,
    fetchRepo(repoPath: string): Promise<FetchResult> {
      fetches.push(repoPath);
      return Promise.resolve(impl(repoPath));
    },
  };
}

const makeMerge = (sha: string, number = 1): MergeEntry => ({
  number,
  title: `Merge ${number}`,
  merge_sha: sha,
  merged_at: '2026-10-24T09:50:00Z',
  runs: [],
});

const makePr = (number: number, headSha: string, draft = false): PrEntry => ({
  number,
  title: `PR ${number}`,
  head_sha: headSha,
  head_ref: `feat-${number}`,
  fork: false,
  author: 'dev1',
  draft,
  updated_at: '2026-10-24T09:55:00Z',
  url: `https://github.com/acme/alpha/pull/${number}`,
  checks: [],
  required_state: 'pass',
});

function hub(over: Partial<HubOptions> = {}) {
  return createHub({
    home,
    now,
    collector: fakeCollector(),
    agents: fakeAgents(),
    github: fakeGithub(() => ({ repos: [], rate: {} })),
    coordinator: fakeCoordinator(),
    versions: () => ({ hub: '0.0.0-test', pool: '1.0.0', plugin: null }),
    gitFetch: fakeFetcher(),
    ...over,
  });
}

describe('hub gitFetch triggers and syncNow', () => {
  it('sets baseline on first github poll and fetches + refreshes collector when merge_sha or PRs change', async () => {
    const a = repo('alpha', 'https://github.com/acme/alpha.git');
    addRepos([a], home);

    let ghLoaded = false;
    const slot: GithubRepoSlot = {
      path: a,
      repo: 'acme/alpha',
      account: 'acme',
      prs: [makePr(10, 'head-1')],
      merges: [makeMerge('merge-1')],
    };
    const collector = fakeCollector();
    const github = fakeGithub(() => (ghLoaded ? { repos: [slot], rate: {} } : null));
    const fetcher = fakeFetcher();
    const h = hub({ collector, github, gitFetch: fetcher });

    // Poll 0 (github not loaded yet): only the periodic never-fetched fetch runs once.
    await h.refreshAll();
    expect(fetcher.fetches).toEqual([a]);

    // First github poll with slot data: sets baseline and triggers NO change fetch.
    t += 1_000;
    ghLoaded = true;
    const colBeforeBaseline = collector.calls;
    await h.refreshAll();
    expect(fetcher.fetches).toEqual([a]);
    expect(collector.calls - colBeforeBaseline).toBe(1);

    // merges[0].merge_sha changes => fetches repo and refreshes collector a second time.
    t += 1_000;
    slot.merges = [makeMerge('merge-2')];
    let colBefore = collector.calls;
    await h.refreshAll();
    expect(fetcher.fetches).toEqual([a, a]);
    expect(collector.calls - colBefore).toBe(2);

    // Open PR head_sha changes => fetches repo and refreshes collector again.
    t += 1_000;
    slot.prs = [makePr(10, 'head-2')];
    colBefore = collector.calls;
    await h.refreshAll();
    expect(fetcher.fetches).toHaveLength(3);
    expect(collector.calls - colBefore).toBe(2);

    // Open PR appears => fetches repo and refreshes collector again.
    t += 1_000;
    slot.prs = [makePr(10, 'head-2'), makePr(11, 'head-3')];
    colBefore = collector.calls;
    await h.refreshAll();
    expect(fetcher.fetches).toHaveLength(4);
    expect(collector.calls - colBefore).toBe(2);

    // Open PR disappears => fetches repo and refreshes collector again.
    t += 1_000;
    slot.prs = [makePr(10, 'head-2')];
    colBefore = collector.calls;
    await h.refreshAll();
    expect(fetcher.fetches).toHaveLength(5);
    expect(collector.calls - colBefore).toBe(2);
  });

  it('does not fetch unchanged repos inside PERIODIC_FETCH_MS (150000) and fetches once after advancing now by 150000', async () => {
    expect(PERIODIC_FETCH_MS).toBe(150_000);
    const a = repo('alpha', 'https://github.com/acme/alpha.git');
    addRepos([a], home);

    const slot: GithubRepoSlot = {
      path: a,
      repo: 'acme/alpha',
      account: 'acme',
      prs: [makePr(1, 'head-1')],
      merges: [makeMerge('merge-1')],
    };
    const collector = fakeCollector();
    const github = fakeGithub(() => ({ repos: [slot], rate: {} }));
    const fetcher = fakeFetcher();
    const h = hub({ collector, github, gitFetch: fetcher });

    // Initial refreshAll performs the never-fetched periodic fetch and sets baseline.
    await h.refreshAll();
    expect(fetcher.fetches).toEqual([a]);

    // Inside PERIODIC_FETCH_MS with unchanged sha and PRs: no new fetch.
    t = T0 + 60_000;
    await h.refreshAll();
    t = T0 + PERIODIC_FETCH_MS - 1;
    await h.refreshAll();
    expect(fetcher.fetches).toEqual([a]);

    // Advance now to T0 + 150000: periodic fetch fires once.
    t = T0 + PERIODIC_FETCH_MS;
    const colBefore = collector.calls;
    await h.refreshAll();
    expect(fetcher.fetches).toEqual([a, a]);
    expect(collector.calls - colBefore).toBe(2);

    // Another refresh right away does not fire again.
    t += 1_000;
    await h.refreshAll();
    expect(fetcher.fetches).toEqual([a, a]);
  });

  it('never periodically fetches a repo without a github origin', async () => {
    const localOnly = repo('alpha');
    const nonGithub = repo('beta', '/repos/origin-beta.git');
    addRepos([localOnly, nonGithub], home);

    const fetcher = fakeFetcher();
    const h = hub({ gitFetch: fetcher });

    await h.refreshAll();
    t += PERIODIC_FETCH_MS;
    await h.refreshAll();
    t += PERIODIC_FETCH_MS * 2;
    await h.refreshAll();

    expect(fetcher.fetches).toEqual([]);
  });

  it('keeps cached data, resolves refreshAll, and skips extra collector refresh when fetch fails, rejects, or throws', async () => {
    const a = repo('alpha', 'https://github.com/acme/alpha.git');
    addRepos([a], home);

    const slot: GithubRepoSlot = {
      path: a,
      repo: 'acme/alpha',
      account: 'acme',
      prs: [makePr(1, 'head-1')],
      merges: [makeMerge('merge-1')],
    };
    const collector = fakeCollector({
      data: {
        schema: 1,
        generated_at: iso(T0),
        repos: [{ path: a, fingerprint: 'fp-1', roadmaps: { items: 5 }, plans: { items: 2 } }],
        spend: { total: 3 },
        guide: { items: [] },
      },
    });
    const github = fakeGithub(() => ({ repos: [slot], rate: {} }));

    let mode: 'failed' | 'reject' | 'throw' = 'failed';
    const gitFetch: GitFetcher = {
      fetchRepo(p: string): Promise<FetchResult> {
        if (mode === 'failed') return Promise.resolve({ path: p, status: 'failed', error: 'offline' });
        if (mode === 'reject') return Promise.reject(new Error('rejected fetch'));
        throw new Error('sync thrown fetch');
      },
    };

    const h = hub({ collector, github, gitFetch });

    // 1. status: 'failed' on initial periodic fetch
    await expect(h.refreshAll()).resolves.toBeUndefined();
    expect(collector.calls).toBe(1);
    expect(h.getState().repos[0]).toMatchObject({
      path: a,
      roadmaps: { items: 5 },
      github: { repo: 'acme/alpha', merges: [{ merge_sha: 'merge-1' }] },
    });

    // 2. fetchRepo rejects on signature change
    t += 1_000;
    mode = 'reject';
    slot.merges = [makeMerge('merge-2')];
    await expect(h.refreshAll()).resolves.toBeUndefined();
    expect(collector.calls).toBe(2);
    expect(h.getState().repos[0]).toMatchObject({
      roadmaps: { items: 5 },
      github: { merges: [{ merge_sha: 'merge-2' }] },
    });

    // 3. fetchRepo throws synchronously on signature change
    t += 1_000;
    mode = 'throw';
    slot.merges = [makeMerge('merge-3')];
    await expect(h.refreshAll()).resolves.toBeUndefined();
    expect(collector.calls).toBe(3);
    expect(h.getState().repos[0]).toMatchObject({
      roadmaps: { items: 5 },
      github: { merges: [{ merge_sha: 'merge-3' }] },
    });
  });

  it('syncNow fetches all repoPaths (including non-github origins), then refreshes every source once', async () => {
    const a = repo('alpha', 'https://github.com/acme/alpha.git');
    const b = repo('beta', '/repos/origin-beta.git');
    addRepos([a, b], home);

    const events: string[] = [];
    const agents = fakeAgents([], () => events.push('agents'));
    const coordinator = fakeCoordinator([], () => events.push('coordinator'));
    const collector = fakeCollector({}, () => events.push('collector'));
    const github = fakeGithub(
      () => ({
        repos: [
          { path: a, repo: 'acme/alpha', account: 'acme', prs: [], merges: [] },
          { path: b, reason: 'no github remote' },
        ],
        rate: {},
      }),
      () => events.push('github'),
    );
    const fetcher = fakeFetcher((p) => {
      events.push(`fetch:${p}`);
      return { path: p, status: 'fetched' };
    });

    const h = hub({ agents, coordinator, collector, github, gitFetch: fetcher });
    await h.syncNow();

    expect(fetcher.fetches).toEqual([a, b]);
    expect(agents.calls).toBe(1);
    expect(coordinator.calls).toBe(1);
    expect(collector.calls).toBe(1);
    expect(github.calls).toBe(1);
    expect(events).toEqual([`fetch:${a}`, `fetch:${b}`, 'agents', 'coordinator', 'collector', 'github']);
  });

  it('syncNow with a fetcher that throws synchronously for one repo still fetches the others and refreshes every source', async () => {
    const a = repo('alpha', 'https://github.com/acme/alpha.git');
    const b = repo('beta', 'https://github.com/acme/beta.git');
    addRepos([a, b], home);
    const collector = fakeCollector();
    const agents = fakeAgents();
    const seen: string[] = [];
    const fetcher: GitFetcher = {
      fetchRepo(p: string): Promise<FetchResult> {
        seen.push(p);
        if (p === a) throw new Error('boom');
        return Promise.resolve({ path: p, status: 'fetched' });
      },
    };
    const h = hub({ collector, agents, gitFetch: fetcher });
    await expect(h.syncNow()).resolves.toBeUndefined();
    expect(seen).toEqual([a, b]);
    expect(agents.calls).toBe(1);
    expect(collector.calls).toBe(1);
  });

  it('shares one run across concurrent syncNow() calls and caps concurrency at 4 with 6 repos', async () => {
    const repos = Array.from({ length: 6 }, (_, i) =>
      repo(`repo-${i}`, `https://github.com/acme/repo-${i}.git`),
    );
    addRepos(repos, home);

    let active = 0;
    let peak = 0;
    const fetches: string[] = [];
    const agents = fakeAgents();
    const coordinator = fakeCoordinator();
    const collector = fakeCollector();
    const github = fakeGithub(() => ({ repos: [], rate: {} }));
    const gitFetch: GitFetcher = {
      async fetchRepo(p: string): Promise<FetchResult> {
        fetches.push(p);
        active += 1;
        peak = Math.max(peak, active);
        await new Promise((r) => setTimeout(r, 15));
        active -= 1;
        return { path: p, status: 'fetched' };
      },
    };

    const h = hub({ agents, coordinator, collector, github, gitFetch });
    await Promise.all([h.syncNow(), h.syncNow()]);

    expect(FETCH_CONCURRENCY).toBe(4);
    expect(peak).toBe(4);
    expect(fetches).toEqual(repos);
    expect(agents.calls).toBe(1);
    expect(coordinator.calls).toBe(1);
    expect(collector.calls).toBe(1);
    expect(github.calls).toBe(1);
  });

  it('syncNow still refreshes sources and never fetches when gitFetch is null', async () => {
    const a = repo('alpha', 'https://github.com/acme/alpha.git');
    addRepos([a], home);

    const agents = fakeAgents();
    const coordinator = fakeCoordinator();
    const collector = fakeCollector();
    const github = fakeGithub(() => ({ repos: [], rate: {} }));

    const h = hub({ agents, coordinator, collector, github, gitFetch: null });
    await h.syncNow();

    expect(agents.calls).toBe(1);
    expect(coordinator.calls).toBe(1);
    expect(collector.calls).toBe(1);
    expect(github.calls).toBe(1);
  });

  it('does not fetch a just-fetched repo again on the next github poll with a changed signature after syncNow', async () => {
    const a = repo('alpha', 'https://github.com/acme/alpha.git');
    addRepos([a], home);

    const slot: GithubRepoSlot = {
      path: a,
      repo: 'acme/alpha',
      account: 'acme',
      prs: [makePr(1, 'head-1')],
      merges: [makeMerge('merge-1')],
    };
    const collector = fakeCollector();
    const github = fakeGithub(() => ({ repos: [slot], rate: {} }));
    const fetcher = fakeFetcher();
    const h = hub({ collector, github, gitFetch: fetcher });

    // First poll sets baseline 'merge-1|1:ready:head-1' (plus the initial periodic fetch).
    await h.refreshAll();
    expect(fetcher.fetches).toEqual([a]);

    // Signature changes before/during syncNow: syncNow fetches `a`, then the next github poll sees 'merge-2'
    // and must NOT trigger a duplicate fetch for `a`.
    t += 1_000;
    slot.merges = [makeMerge('merge-2')];
    const colBeforeSync = collector.calls;
    await h.syncNow();
    expect(fetcher.fetches).toEqual([a, a]);
    expect(collector.calls - colBeforeSync).toBe(1);

    // Subsequent poll with the same 'merge-2' signature still does not fetch.
    t += 1_000;
    await h.refreshAll();
    expect(fetcher.fetches).toEqual([a, a]);

    // A later signature change ('merge-3') fetches normally again.
    t += 1_000;
    slot.merges = [makeMerge('merge-3')];
    await h.refreshAll();
    expect(fetcher.fetches).toEqual([a, a, a]);
  });
});
