import { readFileSync } from 'node:fs';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import RoadmapTab from '../../ui/src/repo/RoadmapTab';
import {
  deriveRoadmaps,
  planColumns,
  planKpis,
  initiallyOpenPlan,
  filterRoadmap,
  gateCount,
  listRow,
  opensDirectly,
  readyGates,
  roadmapModel,
  roadmapTabLabel,
  planStemOf,
  planRoadmapModel,
  phaseDetail,
  phaseMeta,
  planSourceText,
  stageOf,
  TILE_LABEL,
  type PlanView,
  type RoadmapModel,
} from '../../ui/src/repo/roadmap';
import type { HubState, RepoState } from '../../ui/src/types';

const load = (name: string): HubState =>
  JSON.parse(readFileSync(new URL(`../fixtures/hub-state/${name}.json`, import.meta.url), 'utf8')) as HubState;
const repoOf = (s: HubState, name: string): RepoState => s.repos.find((r) => r.name === name)!;
const launch = (s = load('full')): RoadmapModel => deriveRoadmaps(repoOf(s, 'shop')).roadmaps.find((r) => r.slug === 'launch')!;

describe('deriveRoadmaps: header, KPIs, plan chips (P1, P2, P5)', () => {
  it('counts milestones and phases and names the next item', () => {
    const m = launch();
    expect(m.branch).toBe('main');
    expect(m.originCommit).toBe('ABC1234');
    expect(m.kpis).toEqual({
      phasesDone: 2,
      phasesTotal: 5,
      milestonesDone: 1,
      milestonesTotal: 3,
      inProgress: ['p-shop#3'],
      highRisk: 1,
      next: 'S2 p-shop#3',
    });
  });
  it('has a plan chip with done and total per plan', () => {
    expect(launch().lanes).toEqual([{ plan: 'p-shop', done: 2, total: 5 }]);
  });
});

describe('flow, board, timeline data (P6, P7, P8, P9)', () => {
  it('keeps milestones in roadmap order with their dependencies', () => {
    expect(launch().milestones.map((m) => [m.id, m.depends, m.done, m.total])).toEqual([
      ['S1', [], 2, 2],
      ['S2', ['S1'], 0, 2],
      ['S3', ['S2'], 0, 1],
    ]);
  });
  it('buckets now, next and later like the old page', () => {
    const b = launch().board;
    expect(b.now.map((m) => m.id)).toEqual(['S2']);
    expect(b.next.map((m) => m.id)).toEqual(['S3']);
    expect(b.later).toEqual([]);
  });
  it('gives every phase a tile state, a risk flag and a model', () => {
    const phases = launch().milestones.flatMap((m) => m.phases);
    expect(phases.map((p) => p.tile)).toEqual(['done', 'done', 'in-progress', 'todo', 'todo']);
    expect(phases.filter((p) => p.highRisk).map((p) => p.ref)).toEqual(['p-shop#3']);
    expect(phases[0]).toMatchObject({ name: 'Catalog schema', model: 'Opus', lane: 'claude', plan: 'p-shop', num: 1 });
  });
  it('tones: done, prog, wait for an owner gate', () => {
    expect(launch().milestones.map((m) => m.tone)).toEqual(['done', 'prog', 'wait']);
  });
});

describe('gates and runner (P3, P11, P13)', () => {
  it('lists the open owner gate and the blocker table', () => {
    const m = launch();
    expect(m.gates).toEqual([{ milestone: 'S3', type: 'owner-gate', reason: 'owner signs off the checkout copy', check: '' }]);
    expect(m.blockers).toHaveLength(1);
  });
  it('falls back to the unfinished milestones owner gates when the data has no waiting key', () => {
    const s = load('full');
    const rm = (repoOf(s, 'shop').roadmaps as { roadmaps: Record<string, unknown>[] }).roadmaps[0]!;
    delete rm.waiting;
    expect(launch(s).gates.map((g) => g.milestone)).toEqual(['S3']);
  });
  it('shows a live runner, the last stop and the next batch', () => {
    expect(launch().runner).toMatchObject({
      running: { batch: 'B7', host: 'demo-host', pid: '1' },
      staleBatch: null,
      lastStop: 'done (exit 0)',
      lastStopAt: '2026-10-23T18:00:00Z',
      next: 'S2 p-shop#3',
    });
  });
  it('a stale lock and read errors show', () => {
    const s = load('full');
    const rm = (repoOf(s, 'shop').roadmaps as { roadmaps: Record<string, unknown>[] }).roadmaps[0]!;
    rm.runner = { lock: null, stale_lock: { batch: 'B1' }, last_stop: { reason: 'running' }, errors: ['runner.lock: not JSON'] };
    expect(launch(s).runner).toMatchObject({ running: null, staleBatch: 'B1', lastStop: 'running now', errors: ['runner.lock: not JSON'] });
    expect(listRow(launch(s)).runner).toBe('running');
  });
});

describe('PR and stage (P23, R46)', () => {
  it('links a PR only from the Tracker data and a GitHub slot', () => {
    const phases = launch().milestones.flatMap((m) => m.phases);
    expect(phases[0]!.prs).toEqual([{ number: 148, url: 'https://github.com/acme/shop/pull/148', stage: null, detail: null }]);
    expect(phases[3]!.prs).toEqual([]);
  });
  it('stage: an open PR is in review with its checks, a merged PR is merged, else the tile label', () => {
    const phases = launch().milestones.flatMap((m) => m.phases);
    expect(phases[2]!.stage).toMatch(/^#213 in review \(required checks /);
    expect(phases[1]!.prs[0]!.stage).toBe('merged');
    expect(phases[1]!.stage).toBe('#209 merged');
    expect(phases[0]!.stage).toBe('done');
    expect(phases[3]!.stage).toBe('to do');
  });
  it('no GitHub slot: the number stays, with no link', () => {
    const s = load('full');
    repoOf(s, 'shop').github = null;
    expect(launch(s).milestones[0]!.phases[0]!.prs).toEqual([{ number: 148, url: null, stage: null, detail: null }]);
  });
});

describe('list, one roadmap, errors, fallbacks (P14, P17, P18, R48, R49)', () => {
  it('several roadmaps and an error entry show the list', () => {
    const m = deriveRoadmaps(repoOf(load('full'), 'shop'));
    expect(m.mode).toBe('roadmaps');
    expect(m.roadmaps.map((r) => r.slug)).toEqual(['launch', 'hardening']);
    expect(m.errors).toEqual([{ slug: 'broken', error: 'line 4: not a table' }]);
    expect(opensDirectly(m)).toBe(false);
  });
  it('one roadmap and no error opens directly', () => {
    const m = deriveRoadmaps(repoOf(load('full'), 'billing'));
    expect(m.roadmaps.map((r) => r.slug)).toEqual(['ledger']);
    expect(opensDirectly(m)).toBe(true);
  });
  it('a list row has the bar, the counts, dots, next, runner and gate count', () => {
    const row = listRow(launch());
    expect(row).toMatchObject({
      slug: 'launch',
      milestonesDone: 1,
      milestonesTotal: 3,
      phasesDone: 2,
      phasesTotal: 5,
      pct: 40,
      next: 'S2 p-shop#3',
      runner: 'running',
      gates: 1,
      tone: 'wait',
    });
    expect(row.dots.map((d) => d.id)).toEqual(['S1', 'S2', 'S3']);
    expect(listRow(deriveRoadmaps(repoOf(load('full'), 'shop')).roadmaps[1]!)).toMatchObject({ runner: 'idle', gates: 0, tone: 'todo' });
  });
  it('the tab label counts open gates over the roadmaps', () => {
    const s = load('full');
    expect(gateCount(deriveRoadmaps(repoOf(s, 'shop')))).toBe(1);
    expect(roadmapTabLabel(repoOf(s, 'shop'))).toBe('Roadmap · 1 gate');
    expect(roadmapTabLabel(repoOf(s, 'billing'))).toBe('Roadmap');
  });
  it('no roadmap but an active plan shows the plan rows', () => {
    const m = deriveRoadmaps(repoOf(load('full'), 'docs'));
    expect(m.mode).toBe('plans');
    expect(m.plans).toEqual([
      {
        path: '.caddis/plans/p-docs.md',
        title: 'p-docs',
        rows: [
          { phase: '1', status: 'done', state: 'done', key: '1', milestone: null },
          { phase: '2', status: 'not started', state: 'todo', key: '2', milestone: null },
          { phase: '3', status: 'not started', state: 'todo', key: '3', milestone: null },
        ],
        phases: {},
        open: 2,
        changedAt: null,
      },
    ]);
  });
  it('a plan board puts each row in a column by its state; moved sits in Done', () => {
    const m = deriveRoadmaps(repoOf(load('full'), 'shop'));
    const side = m.plans.find((p) => p.path === '.caddis/plans/p-side.md')!;
    const cols = planColumns(side);
    expect(Object.fromEntries(Object.entries(cols).map(([k, rows]) => [k, rows.map((r) => r.phase)]))).toEqual({
      todo: ['A3'],
      'in-progress': [],
      blocked: ['A2'],
      done: ['A1', 'A4'],
    });
  });
  it('a plan KPI counts rows by column and the share done; moved counts as done', () => {
    const m = deriveRoadmaps(repoOf(load('full'), 'shop'));
    const side = m.plans.find((p) => p.path === '.caddis/plans/p-side.md')!;
    expect(planKpis(side)).toEqual({ total: 4, done: 2, inProgress: 0, blocked: 1, todo: 1, pct: 50 });
  });
  it('a plan with no Tracker rows has 0 % done, not NaN', () => {
    const plan = { path: 'a.md', title: 'a', rows: [], phases: {}, open: 0, changedAt: null };
    expect(planKpis(plan).pct).toBe(0);
  });
  it('the open plan that changed last starts open; finished or unknown-time plans do not win', () => {
    const row = (state: 'todo' | 'done') => ({ phase: 'x', status: state, state, key: 'x', milestone: null });
    const plans = [
      { path: 'old.md', title: 'old', rows: [row('todo')], phases: {}, open: 1, changedAt: 100 },
      { path: 'new.md', title: 'new', rows: [row('todo')], phases: {}, open: 1, changedAt: 300 },
      { path: 'all-done.md', title: 'd', rows: [row('done')], phases: {}, open: 0, changedAt: 900 },
      { path: 'no-time.md', title: 'n', rows: [row('todo')], phases: {}, open: 1, changedAt: null },
    ];
    expect(initiallyOpenPlan(plans)).toBe('new.md');
    expect(initiallyOpenPlan([plans[3]!, plans[2]!])).toBe('no-time.md');
    expect(initiallyOpenPlan([plans[2]!])).toBeNull();
  });
  it('the collector time reaches the plan view', () => {
    const s = load('full');
    const docs = repoOf(s, 'docs');
    (docs.plans as { plans: Record<string, unknown>[] }).plans[0]!.changed_at = 1_793_000_000;
    expect(deriveRoadmaps(docs).plans[0]!.changedAt).toBe(1_793_000_000);
  });
  it('plans that no roadmap names show under the roadmaps; a lane plan does not', () => {
    const m = deriveRoadmaps(repoOf(load('full'), 'shop'));
    expect(m.mode).toBe('roadmaps');
    expect(m.otherPlans.map((p) => p.path)).toEqual(['.caddis/plans/p-side.md']);
  });
  it('a row with no state (older collector) is to do', () => {
    const s = load('full');
    const docs = repoOf(s, 'docs');
    for (const row of (docs.plans as { plans: { tracker: Record<string, unknown>[] }[] }).plans[0]!.tracker) delete row.state;
    expect(deriveRoadmaps(docs).plans[0]!.rows.map((r) => r.state)).toEqual(['todo', 'todo', 'todo']);
  });
  it('a finished plan is not shown; with nothing the mode is none', () => {
    const s = load('full');
    const docs = repoOf(s, 'docs');
    (docs.plans as { plans: Record<string, unknown>[] }).plans[0]!.status = 'done';
    expect(deriveRoadmaps(docs).mode).toBe('none');
    docs.roadmaps = null;
    docs.plans = null;
    expect(deriveRoadmaps(docs).mode).toBe('none');
  });
  it('a collector error for the repo shows as an error', () => {
    const s = load('full');
    const docs = repoOf(s, 'docs');
    docs.roadmaps = null;
    docs.plans = null;
    docs.error = 'not a folder';
    expect(deriveRoadmaps(docs)).toMatchObject({ mode: 'error', repoError: 'not a folder' });
  });
  it('a slot error alone is an error', () => {
    const s = load('full');
    const docs = repoOf(s, 'docs');
    docs.roadmaps = { error: 'no origin' };
    docs.plans = { schema: 1, plans: [] };
    expect(deriveRoadmaps(docs)).toMatchObject({ mode: 'error', repoError: 'no origin' });
  });
  it('plain status data (no detail keys) still renders what it has', () => {
    const s = load('full');
    const docs = repoOf(s, 'docs');
    docs.roadmaps = {
      schema: 1,
      roadmaps: [
        {
          roadmap: 'old',
          branch: 'main',
          done: 0,
          total: 1,
          next: null,
          line: '',
          milestones: [{ id: 'A', status: 'todo', owner: 'runner', target: null, depends: [], phases: [{ ref: 'p-x#1', state: 'open' }], blockers: [] }],
        },
      ],
    };
    const m = deriveRoadmaps(docs).roadmaps[0]!;
    expect(m.detailError).toBeNull();
    expect(m.milestones[0]!.phases[0]).toMatchObject({ ref: 'p-x#1', plan: 'p-x', num: 1, name: 'p-x#1', tile: 'todo' });
    expect(m.kpis.next).toBe('none ready');
  });
});

describe('detail_error and ready gates (P24)', () => {
  it('shows the collector detail error', () => {
    const s = load('full');
    (repoOf(s, 'shop').roadmaps as { roadmaps: Record<string, unknown>[] }).roadmaps[0]!.detail_error = 'No module named x';
    expect(launch(s).detailError).toBe('No module named x');
  });
  it('a gate whose dependencies are done is ready; one behind an open dependency is not', () => {
    const s = load('full');
    expect(readyGates(repoOf(s, 'shop'))).toEqual([]); // S3 depends on S2, still in progress
    const rm = (repoOf(s, 'shop').roadmaps as { roadmaps: { milestones: { status: string }[] }[] }).roadmaps[0]!;
    rm.milestones[1]!.status = 'done';
    expect(readyGates(repoOf(s, 'shop'))).toEqual([
      { roadmap: 'launch', milestone: 'S3', reason: 'owner signs off the checkout copy', check: '', id: 'launch:S3:0' },
    ]);
  });
});

describe('search (P16)', () => {
  it('empty text is no filter', () => {
    expect(filterRoadmap(launch(), '  ')).toBeNull();
  });
  it('matches a phase name and shows its milestone', () => {
    const m = filterRoadmap(launch(), 'search')!;
    expect([...m.phases]).toEqual(['p-shop#3']);
    expect([...m.milestones]).toEqual(['S2']);
    expect(m.count).toBe(1);
  });
  it('matches a PR number in the Tracker cell and a milestone id with all its phases', () => {
    expect([...filterRoadmap(launch(), '#148')!.phases]).toEqual(['p-shop#1']);
    const s1 = filterRoadmap(launch(), 'S1')!;
    expect([...s1.phases].sort()).toEqual(['p-shop#1', 'p-shop#2']);
    expect(s1.count).toBeGreaterThanOrEqual(1);
  });
  it('no match gives an empty result with a zero count', () => {
    const m = filterRoadmap(launch(), 'zzz-nothing')!;
    expect(m.count).toBe(0);
    expect(m.milestones.size).toBe(0);
  });
});

describe('planSourceText', () => {
  const NOW = Date.parse('2026-10-28T12:00:00Z');

  it('formats plan provenance and marks fetches older than 24 h as old', () => {
    expect(planSourceText(null, NOW)).toBeNull();
    expect(planSourceText({}, NOW)).toBeNull();
    expect(planSourceText({ source: 'working-tree' }, NOW)).toEqual({
      text: 'Plans from the working tree (no origin branch found)',
      old: false,
    });
    expect(planSourceText({ source: 'origin/main' }, NOW)).toEqual({
      text: 'Plans from origin/main · fetch time unknown',
      old: false,
    });
    expect(
      planSourceText({ source: 'origin/main', commit: '78d7d82e1234', fetched_at: NOW / 1000 - 5 * 3600 }, NOW),
    ).toEqual({
      text: 'Plans from origin/main @ 78d7d82 · last fetch 5 h ago',
      old: false,
    });
    expect(
      planSourceText(
        {
          source: 'origin/main',
          commit: '78d7d82e1234',
          commit_at: NOW / 1000 - 2 * 86400,
          fetched_at: NOW / 1000 - 5 * 3600,
        },
        NOW,
      ),
    ).toEqual({
      text: 'Plans from origin/main @ 78d7d82 · commit 2 d ago · last fetch 5 h ago',
      old: false,
    });
    const stale = planSourceText(
      {
        source: 'origin/main',
        commit: '78d7d82e1234',
        commit_at: NOW / 1000 - 2 * 86400,
        fetched_at: NOW / 1000 - 3 * 86400,
      },
      NOW,
    );
    expect(stale?.text.endsWith('· last fetch 3 d ago')).toBe(true);
    expect(stale?.old).toBe(true);
  });

  it('renders rm-source on the hub RoadmapTab', () => {
    const repo = repoOf(load('full'), 'docs');
    const plans = repo.plans as Record<string, unknown>;
    plans.commit = '78d7d82e1234';
    plans.fetched_at = NOW / 1000 - 3600;
    const html = renderToStaticMarkup(createElement(RoadmapTab, { repo, slug: null, nowMs: NOW }));
    expect(html).toContain('data-testid="rm-source"');
    expect(html).toContain('Plans from origin/main @ 78d7d82 · last fetch 1 h ago');
  });

  it('omits rm-source in the site variant', () => {
    const repo = repoOf(load('full'), 'docs');
    const plans = repo.plans as Record<string, unknown>;
    plans.commit = '78d7d82e1234';
    plans.fetched_at = NOW / 1000 - 3600;
    const html = renderToStaticMarkup(createElement(RoadmapTab, { repo, slug: null, nowMs: NOW, variant: 'site' }));
    expect(html).not.toContain('rm-source');
  });
});

describe('plan roadmap view model (Phase 15)', () => {
  const repo = (): RepoState => repoOf(load('full'), 'shop');

  it('a plan with Tracker milestones M1, M1, M2 gives milestone ids M1 and M2', () => {
    const plan: PlanView = {
      path: '.caddis/plans/p-test.md',
      title: 'Test plan',
      rows: [
        { phase: 'C0 coordinator design', status: 'done', state: 'done', key: 'c0', milestone: 'M1' },
        { phase: '1 Login wiring', status: 'done: #171 merged', state: 'done', key: '1', milestone: 'M1' },
        { phase: '2 UI switch', status: 'in progress', state: 'in-progress', key: '2', milestone: 'M2' },
      ],
      phases: {
        c0: { title: 'Coordinator design', text: 'Section text for c0' },
      },
      open: 1,
      changedAt: null,
    };
    const m = planRoadmapModel(repo(), plan);
    expect(planStemOf(plan.path)).toBe('p-test');
    expect(m.kind).toBe('plan');
    expect(m.slug).toBe('p-test');
    expect(m.milestones.map((ms) => ms.id)).toEqual(['M1', 'M2']);
    expect(m.milestones.map((ms) => ms.depends)).toEqual([[], ['M1']]);
    expect(m.milestones.map((ms) => ms.status)).toEqual(['done', 'in-progress']);
    expect(m.milestones[0]!.phases[1]!.prs).toEqual([
      { number: 171, url: 'https://github.com/acme/shop/pull/171', stage: null, detail: null },
    ]);
    expect(phaseDetail(m, [plan], 'p-test#c0')).toEqual({
      title: 'Coordinator design',
      text: 'Section text for c0',
      hasSection: true,
      planPath: plan.path,
      key: 'c0',
      phase: m.milestones[0]!.phases[0]!,
    });
    expect(phaseDetail(m, [plan], 'p-test#1')).toEqual({
      title: '1 Login wiring',
      text: null,
      hasSection: false,
      planPath: plan.path,
      key: '1',
      phase: m.milestones[0]!.phases[1]!,
    });
    expect(phaseDetail(m, [plan], 'p-test#unknown')).toBeNull();
  });

  it('a plan whose phase entry is { title: "T" } (no text) gives hasSection: true, text: null', () => {
    const plan: PlanView = {
      path: '.caddis/plans/p-notext.md',
      title: 'No text plan',
      rows: [
        { phase: '1 First', status: 'not started', state: 'todo', key: '1', milestone: null },
      ],
      phases: { '1': { title: 'T' } },
      open: 1,
      changedAt: null,
    };
    const m = planRoadmapModel(repo(), plan);
    expect(phaseDetail(m, [plan], 'p-notext#1')).toEqual({
      title: 'T',
      text: null,
      hasSection: true,
      planPath: plan.path,
      key: '1',
      phase: m.milestones[0]!.phases[0]!,
    });
  });

  it('a plan without Tracker milestones gives Phases and roadmapModel has kind roadmap', () => {
    const plan: PlanView = {
      path: '.caddis/plans/p-plain.md',
      title: 'Plain plan',
      rows: [
        { phase: '1 First', status: 'not started', state: 'todo', key: '1', milestone: null },
      ],
      phases: {},
      open: 1,
      changedAt: null,
    };
    const m = planRoadmapModel(repo(), plan);
    expect(m.milestones.map((ms) => ms.id)).toEqual(['Phases']);
    expect(m.milestones[0]!.status).toBe('todo');
    expect(launch().kind).toBe('roadmap');
    expect(roadmapModel(repo(), { roadmap: 'r1', milestones: [] }).kind).toBe('roadmap');
  });
});

describe('stageOf and phaseMeta', () => {
  it('formats stageOf and phaseMeta', () => {
    expect(stageOf([], 'todo')).toBe(TILE_LABEL.todo);
    expect(
      stageOf(
        [
          { number: 7, url: null, stage: 'merged', detail: null },
          { number: 8, url: null, stage: null, detail: null },
        ],
        'done',
      ),
    ).toBe('#7 merged');
    expect(stageOf([{ number: 9, url: null, stage: 'in review', detail: 'required checks pending' }], 'todo')).toBe(
      '#9 in review (required checks pending)',
    );
    expect(phaseMeta({ model: 'sonnet', lane: 'agy foo', risk: 'high' })).toBe('model sonnet · lane agy · risk high');
    expect(phaseMeta({ model: '', lane: '', risk: '' })).toBe('');
  });
});
