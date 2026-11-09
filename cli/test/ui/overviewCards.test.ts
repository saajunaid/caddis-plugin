import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { deriveLive, deriveRepoCards } from '../../ui/src/overview/cards';
import type { HubState, RepoState } from '../../ui/src/types';

const full = JSON.parse(readFileSync(new URL('../fixtures/hub-state/full.json', import.meta.url), 'utf8')) as HubState;
const now = Date.parse(full.generated_at);
const card = (state: HubState, name: string) => deriveRepoCards(state, now).find((c) => c.name === name)!;

describe('deriveRepoCards', () => {
  it('one card per repo, in repo order', () => {
    expect(deriveRepoCards(full, now).map((c) => c.name)).toEqual(['shop', 'billing', 'docs']);
  });

  it('shop: the gate first, the PR ring and the foot', () => {
    expect(card(full, 'shop')).toMatchObject({
      status: '1 gate',
      prsOpen: 5,
      prsPassing: 3,
      ringLabel: '3/5',
      foot: '5 open PRs · shipped 18 min ago',
      href: '#/repo/acme__shop',
    });
  });

  it('billing: a coordinator that does not answer is bad news', () => {
    const c = card(full, 'billing');
    expect(c.status).toBe('Coordinator down');
    expect(c.note).toMatch(/^Coordinator not responding since /);
    expect(c.statusTone).toBe('bad');
    expect(c.ringLabel).toBe('1/1');
    expect(c.foot).toBe('1 open PR · shipped 3 h ago');
    expect(c.note).toContain('last known queue');
  });

  it('docs: no coordinator', () => {
    const c = card(full, 'docs');
    expect(c.ringLabel).toBe('0/1');
    expect(c.foot).toBe('1 open PR · shipped 1 d ago');
    expect(c.note).toContain('No coordinator');
  });

  it('a repo with no GitHub data', () => {
    const shop = full.repos.find((r) => r.name === 'shop')!;
    const state = { ...full, repos: [{ ...shop, github: null } as RepoState] };
    expect(card(state, 'shop')).toMatchObject({ prsOpen: 0, ringLabel: '0', foot: 'No open PRs · never shipped' });
  });
});

describe('deriveLive', () => {
  it('splits the busy sessions from the others', () => {
    const live = deriveLive(full);
    expect(live.busy.map((r) => r.name)).toEqual(['demo-session-web']);
    expect(live.busy[0]!.repo).toBe('shop');
    expect(live.other.length).toBe(4);
  });
});
