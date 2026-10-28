import { readFileSync } from 'node:fs';
import { type ComponentProps, createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
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
