import { readFileSync } from 'node:fs';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import RoadmapTab, { collectorStale } from '../../ui/src/repo/RoadmapTab';
import type { RoadmapView } from '../../ui/src/repo/roadmap';
import { Sessions } from '../../ui/src/repo/SessionsTab';
import type { HubState, RepoState } from '../../ui/src/types';

/**
 * The H4 parity gate: the old roadmap page features against the hub (plan section "Phase H4", table P1-P28; P24 is checked in inbox.test.ts).
 * Each row with an element is rendered from the `full` fixture and its test id must be in the markup. A row that loses
 * its element fails here. Ruled-out rows (P4, P25-P28) have no element, by decision.
 */
const load = (name: string): HubState =>
  JSON.parse(readFileSync(new URL(`../fixtures/hub-state/${name}.json`, import.meta.url), 'utf8')) as HubState;
const repoOf = (s: HubState, name: string): RepoState => s.repos.find((r) => r.name === name)!;
const render = (s: HubState, repo: RepoState, slug: string | null, extra: { variant?: 'hub' | 'site'; initialView?: RoadmapView; initialOpenAll?: boolean } = {}): string =>
  renderToStaticMarkup(createElement(RoadmapTab, { repo, slug, stale: collectorStale(s), lastOkAt: s.sources.collector.last_ok_at, ...extra }));

/** Row of the checklist -> the test ids its element carries. */
const DETAIL_ROWS: Record<string, string[]> = {
  P1: ['rm-header'],
  P2: ['rm-chips'],
  P3: ['rm-waiting'],
  P5: ['rm-kpis'],
  P6: ['rm-flow'],

  P8: ['rm-timeline'],
  P9: ['rm-legend'],
  P10: ['rm-timeline-list'],
  P11: ['rm-gates'],
  P12: ['rm-milestones'],
  P13: ['rm-runner'],
  P16: ['rm-search', 'rm-match-count'],
  P19: ['rm-crumbs'],
  P23: ['rm-pr', 'rm-stage'],
};
const RULED_OUT = { P4: 'sessions come from claude agents', P25: 'D8', P26: 'D8', P27: 'D8', P28: 'H6 and L20' };

describe('parity checklist against the old roadmap page', () => {
  const s = load('full');
  const html = render(s, repoOf(s, 'shop'), 'launch');
  for (const [row, ids] of Object.entries(DETAIL_ROWS)) {
    it(`${row}: ${ids.join(', ')} is on the Roadmap detail`, () => {
      for (const id of ids) expect(html, `${row} lost data-testid="${id}"`).toContain(`data-testid="${id}"`);
    });
  }

  it('P7: the Board view carries rm-board', () => {
    const boardHtml = render(s, repoOf(s, 'shop'), 'launch', { initialView: 'board' });
    expect(boardHtml).toContain('data-testid="rm-board"');
    expect(html).not.toContain('data-testid="rm-board"');
    expect(html).toContain('data-testid="rm-timeline"');
  });

  it('P14, P17, P18: the list has cards and the read errors, and a stale source adds its note', () => {
    const list = render(s, repoOf(s, 'shop'), null);
    for (const id of ['rm-list', 'rm-card', 'rm-errors']) expect(list).toContain(`data-testid="${id}"`);
    expect(list).toContain('Could not read broken: line 4: not a table');
    expect(list).not.toContain('data-testid="rm-stale"');
    const old = load('full');
    old.sources.collector = { ok: true, last_ok_at: '2026-10-24T10:00:00Z', last_error: null, stale: true };
    const stale = render(old, repoOf(old, 'shop'), null);
    expect(stale).toContain('data-testid="rm-stale"');
    expect(stale).toContain('class="rm stale"');
  });

  it('P14: the runner read errors show in the detail', () => {
    const e = load('full');
    (repoOf(e, 'shop').roadmaps as { roadmaps: { runner: { errors: string[] } }[] }).roadmaps[0]!.runner.errors = ['runner.lock: not JSON'];
    expect(render(e, repoOf(e, 'shop'), 'launch')).toContain('Could not read runner.lock: not JSON.');
  });

  it('P15: text from the files is escaped, a script name shows as text', () => {
    const e = load('full');
    const rm = (repoOf(e, 'shop').roadmaps as { roadmaps: { milestones: { phases: { name: string }[] }[] }[] }).roadmaps[0]!;
    rm.milestones[0]!.phases[0]!.name = '<script>alert(1)</script>';
    const out = render(e, repoOf(e, 'shop'), 'launch');
    expect(out).not.toContain('<script>alert(1)</script>');
    expect(out).toContain('&lt;script&gt;alert(1)&lt;/script&gt;');
  });

  it('P17: one roadmap opens directly, with no list and no Back link', () => {
    const out = render(s, repoOf(s, 'billing'), null);
    expect(out).toContain('data-testid="rm-detail"');
    expect(out).not.toContain('data-testid="rm-list"');
    expect(out).not.toContain('href="#/repo/acme__billing/roadmap"');
  });

  it('with several roadmaps the crumbs link back to the list', () => {
    expect(html).toContain('href="#/repo/acme__shop/roadmap"');
  });

  it('empty states: a plan fallback, and no roadmap or plan with the command', () => {
    const plans = render(s, repoOf(s, 'docs'), null);
    expect(plans).toContain('data-testid="rm-plans"');
    for (const id of ['rm-timeline', 'rm-kpis', 'rm-milestones', 'rm-view']) {
      expect(plans).toContain(`data-testid="${id}"`);
    }
    for (const bad of ['rm-crumbs', 'rm-waiting', 'rm-flow', 'rm-gates', 'rm-runner', 'Next batch for the runner', 'Roadmap p-docs']) {
      expect(plans).not.toContain(bad);
    }
    for (const keep of ['rm-crumbs', 'rm-waiting', 'rm-flow', 'rm-gates', 'rm-runner', 'Next batch for the runner']) {
      expect(html).toContain(keep);
    }
    expect(plans).toContain('rm-plan-only');
    expect(plans).toContain('plan only, no runner');
    const board = render(s, repoOf(s, 'docs'), null, { initialView: 'board' });
    expect(board).toContain('data-testid="rm-plan-board"');
    expect(board).toContain('To do · 2');
    const emptyPlanState = load('full');
    const emptyDocs = repoOf(emptyPlanState, 'docs');
    (emptyDocs.plans as { plans: { tracker: unknown[]; open_rows: number }[] }).plans[0]!.tracker = [];
    (emptyDocs.plans as { plans: { tracker: unknown[]; open_rows: number }[] }).plans[0]!.open_rows = 0;
    const emptyBoard = render(emptyPlanState, emptyDocs, null, { initialView: 'board', initialOpenAll: true });
    expect(emptyBoard).toContain('This plan has no Tracker table.');
    const e = load('full');
    const docs = repoOf(e, 'docs');
    docs.roadmaps = null;
    docs.plans = null;
    const none = render(e, docs, null);
    expect(none).toContain('No roadmap or plan');
    expect(none).toContain('/caddis:roadmap');
  });

  it('plans: only the open plan builds its page', () => {
    const two = load('full');
    const docs = repoOf(two, 'docs');
    (docs.plans as { plans: unknown[] }).plans.push({
      path: '.caddis/plans/p-two.md',
      title: 'p-two',
      status: 'active',
      feature: null,
      tracker: [{ phase: '1', status: 'not started', state: 'todo' }],
      open_rows: 1,
    });
    const out = render(two, docs, null);
    expect(out).toContain('p-docs');
    expect(out).toContain('p-two');
    expect(out.match(/data-testid="rm-detail"/g)).toHaveLength(1);
    const all = render(two, docs, null, { initialOpenAll: true });
    expect(all.match(/data-testid="rm-detail"/g)).toHaveLength(2);
  });

  it('P20: the Sessions tab shows the table, the copy button and the empty text', () => {
    const out = renderToStaticMarkup(createElement(Sessions, { state: s, repo: repoOf(s, 'shop'), nowMs: Date.parse('2026-10-24T10:50:30Z') }));
    expect(out).toContain('data-testid="sessions-table"');
    expect(out).toContain('Copy name');
    const e = load('full');
    e.sessions = [];
    expect(renderToStaticMarkup(createElement(Sessions, { state: e, repo: repoOf(e, 'shop'), nowMs: 0 }))).toContain('No sessions running');
  });

  it('every ruled-out row has a reason', () => {
    for (const [row, why] of Object.entries(RULED_OUT)) expect(why.length, row).toBeGreaterThan(0);
  });
});

describe('site variant (H6.1, R64)', () => {
  const full = load('full');
  const planted = load('full');
  const rm = (repoOf(planted, 'shop').roadmaps as { roadmaps: { runner: { lock: Record<string, unknown> } }[] }).roadmaps[0]!;
  rm.runner.lock = { batch: 'S1', started_utc: '2026-10-24T09:00:00Z', host: 'sample-host-77', pid: 424242 };
  const site = (s: HubState, slug: string | null): string => render(s, repoOf(s, 'shop'), slug, { variant: 'site' });

  it('keeps every detail row except the runner', () => {
    const html = site(planted, 'launch');
    for (const [row, ids] of Object.entries(DETAIL_ROWS)) {
      if (row === 'P13') continue;
      for (const id of ids) expect(html, `${row} lost data-testid="${id}"`).toContain(`data-testid="${id}"`);
    }
    expect(html).not.toContain('data-testid="rm-runner"');
    expect(html).not.toContain('sample-host-77');
    expect(html).not.toContain('424242');
  });

  it('the hub variant still shows the runner and its host', () => {
    const html = render(planted, repoOf(planted, 'shop'), 'launch');
    expect(html).toContain('data-testid="rm-runner"');
    expect(html).toContain('sample-host-77');
  });

  it('the list card has no runner text and links to the site routes', () => {
    const html = site(full, null);
    expect(html).toContain('data-testid="rm-card"');
    expect(html).not.toContain('runner:');
    expect(html).toContain('href="#/roadmap/launch"');
    expect(site(full, 'launch')).toContain('href="#/"');
  });
});
