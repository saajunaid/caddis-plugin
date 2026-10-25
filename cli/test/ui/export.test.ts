import { existsSync, readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { exportData, type ExportData } from '../../src/hub/export/data';
import { ExportApp } from '../../ui/src/export/ExportApp';
import { bannerText, exportSummary, NEEDS_EMPTY, routeExport } from '../../ui/src/export/summary';

/**
 * H6.4: the export page against the parity list S1-S17 (plan "Phase H6"). The page is rendered from `exportData` output,
 * the same data the command embeds. Names are samples.
 */
const phase = (plan: string, n: number, tile: string, name: string) => ({
  ref: `${plan}#${n}`,
  state: tile === 'done' ? 'done' : 'todo',
  plan,
  num: n,
  name,
  model: 'mid',
  lane: 'claude',
  risk: 'low',
  tracker: tile === 'done' ? `done #${n + 20}` : '',
  tile,
  prs: tile === 'done' ? [n + 20] : [],
});

function sample(opts: { gates: boolean }): ExportData {
  const ownerGate = opts.gates ? [{ type: 'owner-gate', reason: 'sign off the catalog', check: 'sample check' }] : [];
  const blocked = [{ type: 'external', reason: 'wait for the vendor', check: '' }, ...ownerGate];
  const collect = {
    schema: 1,
    repos: [
      {
        path: 'sample-path',
        fingerprint: 'sample-fingerprint',
        roadmaps: {
          roadmaps: [
            {
              roadmap: 'launch',
              branch: 'main',
              origin_commit: 'ABC1234',
              runner_host: 'sample-host-77',
              runner: { lock: { batch: 'S1', host: 'sample-host-77', pid: 424242, started_utc: '2026-10-24T09:00:00Z' } },
              done: 1,
              total: 3,
              next: { milestone: 'S2', plan: 'p-shop', phase: 3 },
              lanes: ['p-shop'],
              waiting: opts.gates ? [{ milestone: 'S2', reason: 'sign off the catalog', check: 'sample check' }] : [],
              milestones: [
                { id: 'S1', status: 'done', owner: 'runner', target: 'WD3', depends: [], blockers: [], phases: [phase('p-shop', 1, 'done', 'Load the catalog'), phase('p-shop', 2, 'done', 'Show the catalog')] },
                { id: 'S2', status: 'todo', owner: 'runner', target: null, depends: ['S1'], blockers: blocked, phases: [phase('p-shop', 3, 'blocked', 'Check out')] },
              ],
            },
            { roadmap: 'broken', error: 'line 4: not a table in sample-path' },
          ],
        },
        plans: { plans: [{ path: '.caddis/plans/p-shop.md', title: 'p-shop', status: 'active', tracker: [{ phase: '1', status: 'done' }], open_rows: 1 }] },
      },
    ],
  };
  return exportData(collect, { label: null, github: 'acme/shop', commit: 'ABCDEF1234567', now: '2026-10-24T10:05:00Z' });
}

const render = (data: ExportData, hash: string): string => renderToStaticMarkup(createElement(ExportApp, { data, hash }));
const has = (html: string, id: string): void => expect(html, `missing data-testid="${id}"`).toContain(`data-testid="${id}"`);

describe('export page: home (S1-S5, S7, S12, S13)', () => {
  const data = sample({ gates: true });
  const html = render(data, '#/');

  it('S1 banner, S2 KPIs, S3 summary, S4 needs, S12 nav, S13 note, S5 cards', () => {
    for (const id of ['ex-banner', 'ex-kpis', 'ex-summary', 'ex-needs', 'ex-nav', 'ex-note', 'rm-list', 'rm-card']) has(html, id);
    expect(html).toContain("Live sessions and runners show only on the owner&#x27;s machine.");
    expect(html).toContain('acme/shop at ABCDEF1');
    expect(html).toContain('2026-10-24 10:05 UTC');
    expect(html).toContain('Built from roadmap.md and the plan Trackers and headers on origin.');
  });

  it('S2: the counts equal the fixture', () => {
    const s = exportSummary(data);
    expect(s).toMatchObject({ roadmaps: 1, needsYou: 1, phasesDone: 2, phasesTotal: 3, blockedPhases: 1, pct: 67 });
    expect(html).toContain('<span class="kpi-label">Needs you</span><span class="kpi-num accent">1</span>');
    expect(html).toContain('2 / 3');
    expect(html).toContain('Blocked phases');
    expect(html).not.toContain('Runners live');
  });

  it('S3: the summary line', () => {
    expect(html).toContain('1 repo · 1 roadmap · 1 item needs you · generated 2026-10-24 10:05 UTC');
  });

  it('S4: the needs table shows repo roadmap, milestone and reason; the empty text', () => {
    expect(html).toContain('sign off the catalog');
    expect(html).toContain('href="#/roadmap/launch"');
    const none = render(sample({ gates: false }), '#/');
    expect(none).toContain(NEEDS_EMPTY);
    expect(NEEDS_EMPTY).toBe('Nothing is waiting for you.');
  });

  it('S5: the cards have no runner text, and the home lists even one roadmap', () => {
    expect(html).not.toContain('runner:');
    expect(html).not.toContain('data-testid="rm-detail"');
  });

  it('S6: a broken roadmap shows "Could not read", and the message is replaced', () => {
    has(html, 'rm-errors');
    expect(html).toContain('Could not read broken: could not be read');
    expect(html).not.toContain('not a table');
  });
});

describe('export page: gates (S7)', () => {
  it('lists owner gates first, then the other blockers', () => {
    const html = render(sample({ gates: true }), '#/gates');
    has(html, 'ex-gates');
    const owner = html.indexOf('owner-gate');
    const external = html.indexOf('wait for the vendor');
    expect(owner).toBeGreaterThan(-1);
    expect(external).toBeGreaterThan(owner);
    const rows = exportSummary(sample({ gates: true })).gates;
    expect(rows.map((g) => g.type)).toEqual(['owner-gate', 'external']);
  });
});

describe('export page: roadmap (S8-S10, S9 empty, S11, S14)', () => {
  const html = render(sample({ gates: true }), '#/roadmap/launch');

  it('S8-S10: the header, chips, waiting, KPIs, flow, board, timeline, gates and milestones', () => {
    for (const id of ['rm-header', 'rm-chips', 'rm-waiting', 'rm-kpis', 'rm-flow', 'rm-board', 'rm-timeline', 'rm-timeline-list', 'rm-gates', 'rm-milestones', 'rm-search', 'rm-crumbs']) has(html, id);
    expect(html).toContain('branch <code>main</code>');
    expect(html).toContain('origin <code>ABC1234</code>');
  });

  it('S9: the waiting section lists owner gates only; the empty text', () => {
    expect(html).toContain('sign off the catalog');
    expect(render(sample({ gates: false }), '#/roadmap/launch')).toContain('No owner gate is waiting.');
  });

  it('PR links name only the --github repo', () => {
    has(html, 'rm-pr');
    expect(html).toContain('href="https://github.com/acme/shop/pull/21"');
    const noGithub = render({ ...sample({ gates: true }), github: null }, '#/roadmap/launch');
    expect(noGithub).not.toContain('https://github.com');
  });

  it('S11: no runner, no sessions, no hub-only pages', () => {
    expect(html).not.toContain('data-testid="rm-runner"');
    for (const page of [html, render(sample({ gates: true }), '#/'), render(sample({ gates: true }), '#/gates')]) {
      expect(page).not.toContain('sample-host-77');
      expect(page).not.toContain('424242');
      for (const word of ['Sessions', 'Inbox', 'Overview', 'Activity', 'caddis guide', 'Runner']) expect(page, word).not.toContain(word);
    }
  });

  it('a roadmap that is not in the data shows the list and a note', () => {
    const missing = render(sample({ gates: true }), '#/roadmap/nope');
    has(missing, 'rm-missing');
    has(missing, 'rm-list');
  });

  it('text from the data is escaped', () => {
    const data = sample({ gates: true });
    (data.roadmaps[0] as { milestones: { phases: { name: string }[] }[] }).milestones[0]!.phases[0]!.name = '</script><script>x</script>';
    const out = render(data, '#/roadmap/launch');
    expect(out).not.toContain('</script><script>x</script>');
    expect(out).toContain('&lt;/script&gt;&lt;script&gt;x&lt;/script&gt;');
  });
});

describe('routeExport (S17, R63)', () => {
  it('maps the routes and the old hashes', () => {
    expect(routeExport('')).toEqual({ page: 'home' });
    expect(routeExport('#/')).toEqual({ page: 'home' });
    expect(routeExport('#/gates')).toEqual({ page: 'gates' });
    expect(routeExport('#/roadmap/launch')).toEqual({ page: 'roadmap', slug: 'launch' });
    expect(routeExport('#rm-1a2b3c-ui-unification')).toEqual({ page: 'roadmap', slug: 'ui-unification' });
    expect(routeExport('#/repo/x/roadmap/launch')).toEqual({ page: 'home' });
    expect(routeExport('#/roadmap/%E0%A4%A')).toEqual({ page: 'roadmap', slug: '%E0%A4%A' });
  });

  it('the banner text holds the label', () => {
    expect(bannerText({ ...sample({ gates: false }), label: 'built by CI' })).toContain('built by CI.');
  });
});

// The built page. Skipped when `npm run build:ui` has not run.
const BUILT = fileURLToPath(new URL('../../dist/export', import.meta.url));
describe.skipIf(!existsSync(path.join(BUILT, 'index.html')))('dist/export (R60)', () => {
  const index = existsSync(path.join(BUILT, 'index.html')) ? readFileSync(path.join(BUILT, 'index.html'), 'utf8') : '';

  it('has the exact CSP, one data placeholder, no inline script and no style tag', () => {
    expect(index).toContain(
      `content="default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'"`,
    );
    expect(index).toContain('<!--caddis-export-data-->');
    const inline = [...index.matchAll(/<script\b([^>]*)>/g)].filter((m) => !/\bsrc=/.test(m[1]!));
    expect(inline).toEqual([]);
    expect(index).not.toMatch(/<style\b/i);
    expect(index).not.toMatch(/\sstyle="/);
    expect(index).toContain('src="./assets/');
  });

  it('no asset can reach the network', () => {
    const dir = path.join(BUILT, 'assets');
    for (const f of readdirSync(dir).filter((n) => /\.(js|css)$/.test(n))) {
      const text = readFileSync(path.join(dir, f), 'utf8');
      for (const needle of ['/api/', 'fetch(', 'XMLHttpRequest', 'WebSocket', 'EventSource', 'sendBeacon']) expect(text, `${f} holds ${needle}`).not.toContain(needle);
    }
  });
});
