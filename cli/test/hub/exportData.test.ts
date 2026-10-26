import { describe, expect, it } from 'vitest';
import { derivedDeny, ERROR_TEXT, exportData, type ExportRoadmap } from '../../src/hub/export/data.js';

/**
 * H6.2: the Pages export allow-list (R59). The fixture holds every allowed key and many private values.
 * Names are samples. Absolute paths and hashes are built in code so no tracked file holds one.
 */
const WIN_REPO = ['C:', 'Users', 'sample-user', 'work', 'shop'].join('\\');
const FULL_SHA = 'ABCDEF1234567890'.repeat(3).slice(0, 40).toLowerCase();

const phase = (n: number) => ({
  ref: `p-shop#${n}`,
  state: 'done',
  plan: 'p-shop',
  num: n,
  name: `Load the catalog ${n}`,
  model: 'mid',
  lane: 'claude',
  risk: 'low',
  tracker: `done #${n + 10}`,
  tile: 'done',
  prs: [n + 10],
  zz_private: 'phase-canary-zz',
});

function collector(): Record<string, unknown> {
  return {
    schema: 1,
    generated_at: '2026-10-24T10:00:00Z',
    spend: { cap_eur: 200, committed_eur: 12 },
    repos: [
      {
        path: WIN_REPO,
        fingerprint: 'fp-canary-0123456789',
        relays: { relays: [{ name: 'demo-session', session_id: 'sample-demo-session' }] },
        zz_private: 'repo-canary-zz',
        roadmaps: {
          schema: 1,
          roadmaps: [
            {
              roadmap: 'launch',
              branch: 'main',
              origin_commit: FULL_SHA,
              runner_host: 'sample-host-77',
              line: 'S1 waits for: owner-gate sample-line-canary',
              done: 1,
              total: 2,
              next: { milestone: 'S2', plan: 'p-shop', phase: 3, zz_private: 'next-canary-zz' },
              lanes: ['p-shop'],
              waiting: [{ milestone: 'S2', reason: 'owner signs off', check: 'sample check', extra: 'waiting-canary-zz' }],
              runner: { lock: { batch: 'S1', host: 'sample-lock-host', pid: 424242 }, stale_lock: { host: 'sample-stale-host', pid: 515151 } },
              zz_private: 'roadmap-canary-zz',
              milestones: [
                {
                  id: 'S1',
                  status: 'in-progress',
                  owner: 'runner',
                  target: 'WD3',
                  depends: [],
                  zz_private: 'ms-canary-zz',
                  blockers: [{ type: 'owner-gate', reason: 'sign off the catalog', check: 'sample check', zz_private: 'blocker-canary-zz' }],
                  phases: [phase(1), phase(2)],
                },
              ],
            },
            { roadmap: 'broken', error: `could not parse ${WIN_REPO}\\.caddis\\roadmaps\\broken\\roadmap.md` },
            { roadmap: 'nodetail', branch: 'main', done: 0, total: 0, milestones: [], detail_error: `failed in ${WIN_REPO}` },
          ],
        },
        plans: {
          schema: 1,
          plans: [
            { path: '.caddis/plans/p-shop.md', title: 'p-shop', status: 'active', tracker: [{ phase: '1', status: 'done', state: 'done', commit: 'x' }], open_rows: 1, feature: 'f' },
            { path: `${WIN_REPO}\\.caddis\\plans\\abs.md`, title: 'abs-canary', status: 'active', tracker: [], open_rows: 0 },
            { path: '../outside/plan.md', title: 'dots-canary', status: 'active', tracker: [], open_rows: 0 },
            { path: '.caddis/plans/bad.md', error: 'sample-plan-error' },
          ],
        },
      },
    ],
  };
}

const opts = { label: null, github: 'acme/shop', commit: FULL_SHA, now: '2026-10-24T10:05:00Z' };

describe('exportData (R59)', () => {
  const data = exportData(collector(), opts);
  const text = JSON.stringify(data);

  it('keeps every allowed key with its value', () => {
    expect(Object.keys(data)).toEqual(['schema', 'generated_at', 'label', 'github', 'commit', 'roadmaps', 'plans']);
    const rm = data.roadmaps[0] as ExportRoadmap;
    expect(rm).toMatchObject({ roadmap: 'launch', branch: 'main', done: 1, total: 2, lanes: ['p-shop'] });
    expect(rm.next).toEqual({ milestone: 'S2', plan: 'p-shop', phase: 3 });
    expect(rm.waiting).toEqual([{ milestone: 'S2', reason: 'owner signs off', check: 'sample check' }]);
    expect(rm.milestones[0]).toMatchObject({ id: 'S1', status: 'in-progress', owner: 'runner', target: 'WD3', depends: [] });
    expect(rm.milestones[0]!.blockers).toEqual([{ type: 'owner-gate', reason: 'sign off the catalog', check: 'sample check' }]);
    expect(Object.keys(rm.milestones[0]!.phases[0]!).sort()).toEqual(
      ['lane', 'model', 'name', 'num', 'plan', 'prs', 'ref', 'risk', 'state', 'tile', 'tracker'],
    );
    expect(rm.milestones[0]!.phases[1]).toMatchObject({ ref: 'p-shop#2', num: 2, model: 'mid', prs: [12], tracker: 'done #12' });
    expect(data.plans).toEqual([{ path: '.caddis/plans/p-shop.md', title: 'p-shop', status: 'active', tracker: [{ phase: '1', status: 'done', state: 'done' }], open_rows: 1 }]);
    expect(data).toMatchObject({ generated_at: '2026-10-24T10:05:00Z', github: 'acme/shop', label: null });
  });

  it('holds none of the planted private values', () => {
    for (const canary of [
      'sample-host-77', 'sample-lock-host', '424242', 'sample-stale-host', '515151', WIN_REPO, 'sample-user', 'fp-canary', 'sample-demo-session',
      'zz_private', 'canary-zz', 'sample-line-canary', 'cap_eur', 'committed_eur', 'relays', 'spend', 'fingerprint', 'runner_host',
      'abs-canary', 'dots-canary', 'sample-plan-error',
    ]) {
      expect(text, canary).not.toContain(canary);
    }
    expect(text).not.toContain('"line"');
    expect(text).not.toContain('"runner":{');
  });

  it('replaces an error message and a detail error with fixed text', () => {
    expect(data.roadmaps[1]).toEqual({ roadmap: 'broken', error: ERROR_TEXT });
    expect(data.roadmaps[2]).toMatchObject({ roadmap: 'nodetail', detail_error: ERROR_TEXT });
    expect(ERROR_TEXT).toBe('could not be read');
  });

  it('cuts the commit and the origin commit to 7 hex', () => {
    expect(data.commit).toBe(FULL_SHA.slice(0, 7));
    expect((data.roadmaps[0] as ExportRoadmap).origin_commit).toBe(FULL_SHA.slice(0, 7));
    expect(text).not.toContain(FULL_SHA);
  });

  it('rejects a bad github value and a bad commit', () => {
    expect(() => exportData(collector(), { ...opts, github: 'no-slash' })).toThrow(/--github/);
    expect(() => exportData(collector(), { ...opts, github: 'a/b c' })).toThrow(/--github/);
    expect(() => exportData(collector(), { ...opts, commit: 'not hex' })).toThrow(/--commit/);
  });

  it('accepts null github and commit', () => {
    expect(exportData(collector(), { ...opts, github: null, commit: null })).toMatchObject({ github: null, commit: null });
  });

  it('throws when the repo or its roadmaps could not be read, without the raw message', () => {
    const bad = { repos: [{ path: WIN_REPO, error: `boom at ${WIN_REPO}` }] };
    expect(() => exportData(bad, opts)).toThrow('the collector could not read the repo');
    const slot = { repos: [{ path: WIN_REPO, roadmaps: { error: `no origin in ${WIN_REPO}` }, plans: { plans: [] } }] };
    try {
      exportData(slot, opts);
      expect.unreachable();
    } catch (error) {
      expect(String(error)).not.toContain(WIN_REPO);
    }
    expect(() => exportData({ repos: [] }, opts)).toThrow(/exactly one repo/);
  });

  it('is deterministic and does not change its input', () => {
    const input = collector();
    const before = JSON.stringify(input);
    expect(JSON.stringify(exportData(input, opts))).toBe(text);
    expect(JSON.stringify(input)).toBe(before);
  });
});

describe('derivedDeny (R62 a)', () => {
  const machine = { repoPath: WIN_REPO, home: ['C:', 'Users', 'sample-user'].join('\\'), user: 'sample-user', host: 'sample-box-01' };
  const deny = derivedDeny(collector(), machine);

  it('lists hosts, pids, the path in both slash forms, the home, the user, the host and the fingerprint', () => {
    for (const value of [
      'sample-host-77', 'sample-lock-host', '424242', 'sample-stale-host', '515151', WIN_REPO, WIN_REPO.replace(/\\/g, '/'),
      machine.home, machine.home.replace(/\\/g, '/'), 'sample-user', 'sample-box-01', 'fp-canary-0123456789',
    ]) {
      expect(deny, value).toContain(value);
    }
  });

  it('has no duplicates and skips values shorter than 3 characters', () => {
    expect(new Set(deny).size).toBe(deny.length);
    const raw = collector();
    const repo = (raw.repos as Record<string, unknown>[])[0]!;
    (repo.roadmaps as { roadmaps: Record<string, unknown>[] }).roadmaps[0]!.runner = { lock: { host: 'ab', pid: 1 } };
    const small = derivedDeny(raw, { repoPath: '', home: '', user: 'x', host: 'y' });
    expect(small).not.toContain('1');
    expect(small).not.toContain('ab');
    expect(small.every((v) => v.length >= 3)).toBe(true);
  });

  it('skips a generic user name that the page text uses', () => {
    expect(derivedDeny({ repos: [] }, { repoPath: '', home: '', user: 'runner', host: 'sample-box-01' })).toEqual(['sample-box-01']);
  });
});
