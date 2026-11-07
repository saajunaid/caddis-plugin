import { readFileSync } from 'node:fs';
import { type ComponentProps, createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { Plans } from '../../ui/src/repo/PlanList';
import RoadmapTab from '../../ui/src/repo/RoadmapTab';
import type { HubState, RepoState } from '../../ui/src/types';

// The runner times print in the machine's zone and locale: pin both, so the snapshots read the same on every machine.
vi.mock('../../ui/src/shell/time', async (orig) => {
  const real = await orig<typeof import('../../ui/src/shell/time')>();
  return { ...real, localTime: (iso: string | null | undefined) => real.localTime(iso, 'en-GB', 'UTC') };
});

const load = (name: string): HubState =>
  JSON.parse(readFileSync(new URL(`../fixtures/hub-state/${name}.json`, import.meta.url), 'utf8')) as HubState;
const repoOf = (s: HubState, name: string): RepoState => s.repos.find((r) => r.name === name)!;
const html = (props: ComponentProps<typeof RoadmapTab>): string => renderToStaticMarkup(createElement(RoadmapTab, props));

const NOW = Date.parse('2026-10-28T12:00:00Z');

describe('RoadmapTab markup snapshots', () => {
  const s = load('full');
  const shop = repoOf(s, 'shop');
  const docs = repoOf(s, 'docs');
  const billing = repoOf(s, 'billing');

  it('shop list', () => {
    expect(html({ repo: shop, slug: null, nowMs: NOW })).toMatchSnapshot();
  });

  it('shop launch hub', () => {
    expect(html({ repo: shop, slug: 'launch', nowMs: NOW })).toMatchSnapshot();
  });

  it('shop launch site', () => {
    expect(html({ repo: shop, slug: 'launch', variant: 'site', nowMs: NOW })).toMatchSnapshot();
  });

  it('shop launch board', () => {
    expect(html({ repo: shop, slug: 'launch', initialView: 'board', nowMs: NOW })).toMatchSnapshot();
  });

  it('docs plans', () => {
    expect(html({ repo: docs, slug: null, initialOpenAll: true, nowMs: NOW })).toMatchSnapshot();
  });

  it('docs plans board', () => {
    expect(html({ repo: docs, slug: null, initialOpenAll: true, initialView: 'board', nowMs: NOW })).toMatchSnapshot();
  });

  it('billing direct', () => {
    expect(html({ repo: billing, slug: null, nowMs: NOW })).toMatchSnapshot();
  });
});

describe('plan overlay badge', () => {
  const docs = repoOf(load('full'), 'docs');
  const planWith = (overlay: { pr: number; draft: boolean; also: number[] } | null) => ({
    path: '.caddis/plans/p.md',
    title: 'P',
    rows: [{ phase: '1', status: 'done #7', state: 'done' as const, key: '1', milestone: null }],
    phases: {},
    open: 0,
    changedAt: null,
    overlay,
  });
  it('a plan from a PR branch shows the badge', () => {
    const out = renderToStaticMarkup(createElement(Plans, { plans: [planWith({ pr: 540, draft: false, also: [] })], repo: docs, variant: 'hub' }));
    expect(out).toContain('<span class="rm-plan-branch" data-testid="rm-plan-branch">on branch (PR #540)</span>');
  });
  it('a plan with no overlay shows no badge', () => {
    const out = renderToStaticMarkup(createElement(Plans, { plans: [planWith(null)], repo: docs, variant: 'hub' }));
    expect(out).not.toContain('rm-plan-branch');
  });
});
