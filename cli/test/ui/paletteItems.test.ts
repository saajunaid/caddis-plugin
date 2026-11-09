import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { deriveInbox } from '../../ui/src/inbox/derive';
import { buildPaletteItems, type PaletteGroup, type PaletteItem } from '../../ui/src/palette/items';
import { rankItems } from '../../ui/src/palette/match';
import type { HubState } from '../../ui/src/types';

const full = JSON.parse(readFileSync(new URL('../fixtures/hub-state/full.json', import.meta.url), 'utf8')) as HubState;
const now = Date.parse(full.generated_at);
const items = (): PaletteItem[] => buildPaletteItems(full, deriveInbox(full, now).items, now);
const byLabel = (list: PaletteItem[], label: string): PaletteItem => list.find((i) => i.label === label)!;
const count = (list: PaletteItem[], g: PaletteGroup): number => list.filter((i) => i.group === g).length;

describe('buildPaletteItems on the full fixture', () => {
  it('has exact counts per group, in group order', () => {
    const list = items();
    expect(count(list, 'Pages')).toBe(7);
    expect(count(list, 'Repos')).toBe(9);
    expect(count(list, 'Roadmaps')).toBe(3);
    expect(count(list, 'Pull requests')).toBe(7);
    expect(count(list, 'Sessions')).toBe(5);
    expect(count(list, 'Inbox')).toBe(deriveInbox(full, now).items.length);
    expect(count(list, 'Inbox')).toBe(7);
    expect([...new Set(list.map((i) => i.group))]).toEqual(['Pages', 'Repos', 'Roadmaps', 'Pull requests', 'Sessions', 'Inbox']);
    expect(new Set(list.map((i) => i.id)).size).toBe(list.length);
  });

  it('pages: the four main pages and the four guide pages', () => {
    const pages = items().filter((i) => i.group === 'Pages');
    expect(pages.map((i) => i.label)).toEqual(['Inbox', 'Overview', 'Activity', 'Guide · Poster', 'Guide · Details', 'Guide · Wall poster', 'Guide · Map']);
    expect(pages.map((i) => i.action)).toEqual([
      { kind: 'route', href: '#/inbox' },
      { kind: 'route', href: '#/overview' },
      { kind: 'route', href: '#/activity' },
      { kind: 'route', href: '#/guide' },
      { kind: 'route', href: '#/guide/details' },
      { kind: 'route', href: '#/guide/wall' },
      { kind: 'route', href: '#/guide/map' },
    ]);
  });

  it('repos: Flow, Roadmap and Sessions tabs per repo', () => {
    const list = items();
    expect(list.filter((i) => i.group === 'Repos').map((i) => i.label)).toEqual([
      'shop · Flow',
      'shop · Roadmap',
      'shop · Sessions',
      'billing · Flow',
      'billing · Roadmap',
      'billing · Sessions',
      'docs · Flow',
      'docs · Roadmap',
      'docs · Sessions',
    ]);
    expect(byLabel(list, 'shop · Flow').action).toEqual({ kind: 'route', href: '#/repo/acme__shop' });
    expect(byLabel(list, 'billing · Roadmap').action).toEqual({ kind: 'route', href: '#/repo/acme__billing/roadmap' });
    expect(byLabel(list, 'docs · Sessions').action).toEqual({ kind: 'route', href: '#/repo/acme__docs/sessions' });
  });

  it('roadmaps: one per readable roadmap, a read error is left out', () => {
    const rm = items().filter((i) => i.group === 'Roadmaps');
    expect(rm.map((i) => [i.label, i.hint])).toEqual([
      ['launch', 'shop'],
      ['hardening', 'shop'],
      ['ledger', 'billing'],
    ]);
    expect(rm[0]!.action).toEqual({ kind: 'route', href: '#/repo/acme__shop/roadmap/launch' });
  });

  it('pull requests open the PR page, drafts say so', () => {
    const list = items();
    const pr = byLabel(list, '#212 retry flaky upload');
    expect(pr.action).toEqual({ kind: 'url', url: 'https://example.invalid/pull/212' });
    expect(pr.hint).toBe('shop');
    expect(byLabel(list, '#216 wip draft').hint).toBe('shop · draft');
    expect(byLabel(list, '#88 new install page').hint).toBe('docs');
  });

  it('sessions copy the session name', () => {
    const s = byLabel(items(), 'demo-session-export');
    expect(s.hint).toBe('billing · waiting');
    expect(s.action).toEqual({ kind: 'copy', text: 'demo-session-export' });
  });

  it('inbox items open the Inbox with that item selected', () => {
    const inbox = items().filter((i) => i.group === 'Inbox');
    const derived = deriveInbox(full, now).items;
    expect(inbox).toHaveLength(derived.length);
    inbox.forEach((p, n) => {
      expect(p.action).toEqual({ kind: 'route', href: `#/inbox/${encodeURIComponent(derived[n]!.id)}` });
    });
    const first = derived[0]!;
    expect(inbox[0]!.label).toBe(first.title);
    expect(inbox[0]!.action).toEqual({ kind: 'route', href: '#/inbox/waiting%3Ademo-session-api' });
  });

  it('a state with no repos has only the pages', () => {
    const empty = { ...full, repos: [], sessions: [] } as HubState;
    expect(buildPaletteItems(empty, [], now).map((i) => i.group)).toEqual(Array(7).fill('Pages'));
  });
});

const item = (group: PaletteGroup, label: string, keywords: string[] = []): PaletteItem => ({
  id: `${group}:${label}`,
  group,
  label,
  hint: '',
  keywords,
  action: { kind: 'route', href: '#/' },
});

const FIXTURE: PaletteItem[] = [
  item('Pages', 'Overview'),
  item('Pages', 'Activity'),
  item('Repos', 'docs · Flow', ['acme/docs']),
  item('Repos', 'docs · Roadmap', ['acme/docs']),
  item('Repos', 'serve-sight · Flow', ['vmie/serve-sight']),
  item('Repos', 'serve-sight · Roadmap', ['vmie/serve-sight']),
  item('Repos', 'serve-sight · Sessions', ['vmie/serve-sight']),
  item('Roadmaps', 'roadmap-ux', ['serve-sight']),
  item('Pull requests', '#386 questions-first bar for drives', ['serve-sight']),
];
const labels = (list: PaletteItem[]): string[] => list.map((i) => i.label);

describe('rankItems', () => {
  it('"srv rd" ranks serve-sight · Roadmap first', () => {
    expect(rankItems(FIXTURE, 'srv rd')[0]!.label).toBe('serve-sight · Roadmap');
  });

  it('a query that matches nothing gives []', () => {
    expect(rankItems(FIXTURE, 'zzqx')).toEqual([]);
  });

  it('every token must match', () => {
    expect(rankItems(FIXTURE, 'docs zzqx')).toEqual([]);
    expect(labels(rankItems(FIXTURE, 'docs flow'))).toEqual(['docs · Flow']);
  });

  it('is case-insensitive', () => {
    expect(labels(rankItems(FIXTURE, 'OVERVIEW'))).toEqual(['Overview']);
  });

  it('prefers a word-start prefix, then the shorter label', () => {
    expect(labels(rankItems(FIXTURE, 'roadmap')).slice(0, 3)).toEqual(['roadmap-ux', 'docs · Roadmap', 'serve-sight · Roadmap']);
  });

  it('contiguous beats scattered', () => {
    // "flow" is contiguous in "docs · Flow"; in "#386 questions-first bar for drives" it is not there at all.
    expect(labels(rankItems(FIXTURE, 'flow'))).toEqual(['docs · Flow', 'serve-sight · Flow']);
    // "ses": contiguous in "Sessions", scattered in "serve-sight".
    expect(rankItems(FIXTURE, 'ses')[0]!.label).toBe('serve-sight · Sessions');
  });

  it('a keyword-only match ranks below a label match', () => {
    const got = labels(rankItems(FIXTURE, 'serve'));
    expect(got).toContain('roadmap-ux');
    expect(got.indexOf('roadmap-ux')).toBeGreaterThan(got.indexOf('serve-sight · Sessions'));
  });

  it('an empty query shows pages first, then repos, at most 50', () => {
    const shuffled = [FIXTURE[7]!, FIXTURE[3]!, FIXTURE[0]!, FIXTURE[8]!, FIXTURE[1]!];
    expect(labels(rankItems(shuffled, '  '))).toEqual(['Overview', 'Activity', 'docs · Roadmap', 'roadmap-ux', '#386 questions-first bar for drives']);
    const many = Array.from({ length: 80 }, (_, n) => item('Sessions', `s${n}`));
    expect(rankItems(many, '')).toHaveLength(50);
    expect(rankItems(many, 's')).toHaveLength(50);
  });
});
