import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiHeaders, captureTab, getState, getTab, TAB_KEY } from '../../ui/src/api';
import { bannersFor } from '../../ui/src/shell/bannerRules';
import { ageText, anySourceDown, dataAgeText, quotaLow, spendView, titleFor } from '../../ui/src/shell/format';
import { repoTone } from '../../ui/src/shell/Nav';
import { guideHref, parseRoute, repoTabHref } from '../../ui/src/shell/route';
import { loadTheme, resolveTheme, saveTheme, THEME_KEY } from '../../ui/src/shell/theme';
import type { HubState } from '../../ui/src/types';

const mem = () => {
  const m = new Map<string, string>();
  return { m, getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) };
};
const boom = {
  getItem: (): string | null => {
    throw new Error('blocked');
  },
  setItem: (): void => {
    throw new Error('blocked');
  },
};

describe('theme', () => {
  it('persists the choice', () => {
    const s = mem();
    expect(loadTheme(s)).toBe('system');
    saveTheme('light', s);
    expect(s.m.get(THEME_KEY)).toBe('light');
    expect(loadTheme(s)).toBe('light');
  });
  it('survives a throwing localStorage', () => {
    expect(() => saveTheme('dark', boom)).not.toThrow();
    expect(loadTheme(boom)).toBe('system');
    expect(loadTheme(null)).toBe('system');
  });
  it('ignores an odd saved value and resolves system by the OS', () => {
    const s = mem();
    s.setItem(THEME_KEY, 'purple');
    expect(loadTheme(s)).toBe('system');
    expect(resolveTheme('system', true)).toBe('dark');
    expect(resolveTheme('system', false)).toBe('light');
    expect(resolveTheme('dark', false)).toBe('dark');
  });
});

describe('title and data age', () => {
  it('puts the inbox count in the title', () => {
    expect(titleFor(0)).toBe('caddis hub');
    expect(titleFor(3)).toBe('(3) caddis hub');
  });
  it('words the data age', () => {
    const now = Date.parse('2026-10-24T12:00:00Z');
    expect(ageText('2026-10-24T11:59:59Z', now)).toBe('just now');
    expect(ageText('2026-10-24T11:59:30Z', now)).toBe('30 s ago');
    expect(ageText('2026-10-24T11:57:00Z', now)).toBe('3 min ago');
    expect(ageText('2026-10-24T10:00:00Z', now)).toBe('2 h ago');
    expect(ageText('2026-10-21T12:00:00Z', now)).toBe('3 d ago');
    expect(ageText('2026-10-24T12:00:30Z', now)).toBe('just now');
    expect(ageText(null, now)).toBe('unknown');
    expect(ageText('nonsense', now)).toBe('unknown');
    expect(dataAgeText('2026-10-24T11:57:00Z', now)).toBe('Updated 3 min ago');
  });
});

describe('spend', () => {
  it('reads the slot', () => {
    expect(spendView({ configured: true, cap_eur: 200, committed_eur: 50 })).toMatchObject({ configured: true, pct: 25 });
    expect(spendView({ configured: true, cap_eur: 200, committed_eur: 900 }).pct).toBe(100);
    expect(spendView({ configured: false, cap_eur: null, committed_eur: 0 }).configured).toBe(false);
    expect(spendView(null).pct).toBe(0);
  });
});

describe('routes', () => {
  it('parses hash routes', () => {
    expect(parseRoute('')).toEqual({ page: 'inbox' });
    expect(parseRoute('#/overview')).toEqual({ page: 'overview' });
    expect(parseRoute('#/repo/acme__shop')).toEqual({ page: 'repo', id: 'acme__shop', tab: 'flow', roadmap: null });
    expect(parseRoute('#/repo/acme__shop/roadmap')).toEqual({ page: 'repo', id: 'acme__shop', tab: 'roadmap', roadmap: null });
    expect(parseRoute('#/repo/acme__shop/roadmap/launch')).toEqual({ page: 'repo', id: 'acme__shop', tab: 'roadmap', roadmap: 'launch' });
    expect(parseRoute('#/repo/acme__shop/sessions')).toEqual({ page: 'repo', id: 'acme__shop', tab: 'sessions', roadmap: null });
    expect(parseRoute('#/repo/acme__shop/nope')).toMatchObject({ tab: 'flow' });
    expect(parseRoute('#/repo/')).toEqual({ page: 'inbox' });
    expect(parseRoute('#/nope')).toEqual({ page: 'inbox' });
    expect(parseRoute('#/guide')).toEqual({ page: 'guide', tab: 'poster', item: null });
    expect(parseRoute('#/guide/details')).toEqual({ page: 'guide', tab: 'details', item: null });
    expect(parseRoute('#/guide/details/g-command-handoff')).toEqual({ page: 'guide', tab: 'details', item: 'g-command-handoff' });
    expect(parseRoute('#/guide/bogus')).toEqual({ page: 'guide', tab: 'poster', item: null });
    expect(guideHref('details', 'g-agent-debug')).toBe('#/guide/details/g-agent-debug');
    expect(guideHref('poster')).toBe('#/guide');
  });

  it('round-trips repo tab links (R47)', () => {
    for (const [tab, slug] of [['flow', null], ['roadmap', null], ['roadmap', 'launch'], ['sessions', null]] as const) {
      const r = parseRoute(repoTabHref('acme__shop', tab, slug));
      expect(r).toEqual({ page: 'repo', id: 'acme__shop', tab, roadmap: slug });
    }
    expect(parseRoute(repoTabHref('/srv/x y', 'roadmap', 'a b'))).toMatchObject({ id: '/srv/x y', roadmap: 'a b' });
  });
});

describe('tab token (controller ruling)', () => {
  it('captures the token, stores it and removes the hash', () => {
    const s = mem();
    const calls: unknown[][] = [];
    captureTab({ hash: '#tab=abc123', pathname: '/', search: '' }, { replaceState: (...a) => void calls.push(a) }, s);
    expect(s.m.get(TAB_KEY)).toBe('abc123');
    expect(calls).toEqual([[null, '', '/']]);
    expect(getTab(s)).toBe('abc123');
  });
  it('does nothing without a token in the hash', () => {
    const s = mem();
    const calls: unknown[][] = [];
    captureTab({ hash: '#/overview', pathname: '/', search: '' }, { replaceState: (...a) => void calls.push(a) }, s);
    expect(calls).toEqual([]);
    expect(s.m.size).toBe(0);
  });
  it('ignores a malformed % in the token instead of throwing (review minor 9)', () => {
    const s = mem();
    expect(() => captureTab({ hash: '#tab=%E0%A4%A', pathname: '/', search: '' }, { replaceState: () => undefined }, s)).not.toThrow();
    expect(s.m.size).toBe(0);
  });
  it('still works with a throwing sessionStorage', () => {
    captureTab({ hash: '#tab=mem1', pathname: '/', search: '' }, { replaceState: () => undefined }, boom);
    expect(getTab(boom)).toBe('mem1');
  });
  it('sends the tab header, and the CSRF header when given', () => {
    expect(apiHeaders('t1')).toMatchObject({ 'X-Caddis-Hub-Tab': 't1' });
    expect(apiHeaders(null)).not.toHaveProperty('X-Caddis-Hub-Tab');
    expect(apiHeaders('t1', 'c1')).toMatchObject({ 'X-CSRF-Token': 'c1' });
  });
  const origWindow = globalThis.window;
  const origFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.window = origWindow;
    globalThis.fetch = origFetch;
  });
  it('safeStorage uses localStorage', () => {
    const local = mem();
    local.setItem(TAB_KEY, 'from-local');
    const session = mem();
    session.setItem(TAB_KEY, 'from-session');
    globalThis.window = { localStorage: local, sessionStorage: session } as unknown as Window & typeof globalThis;
    expect(getTab()).toBe('from-local');
  });
  it('a 401 after logout rejects with status 401 and does not retry', async () => {
    const local = mem();
    local.setItem(TAB_KEY, 't1');
    const session = mem();
    globalThis.window = { localStorage: local, sessionStorage: session } as unknown as Window & typeof globalThis;
    globalThis.fetch = vi.fn(async () => ({ ok: false, status: 401 })) as unknown as typeof fetch;
    await expect(getState()).rejects.toMatchObject({ status: 401 });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});

describe('banners', () => {
  const ok = { ok: true, last_ok_at: '2026-10-24T11:00:00Z', last_error: null, stale: false };
  const base = (over: Partial<HubState> = {}): HubState =>
    ({
      schema: 1,
      generated_at: '2026-10-24T12:00:00Z',
      versions: { hub: '1', pool: null, plugin: null },
      sources: { collector: ok, agents: ok, github: ok, coordinator: ok },
      update_needed: false,
      repos: [],
      sessions: [],
      spend: null,
      guide: null,
      ...over,
    }) as HubState;
  it('is empty for a healthy state', () => {
    expect(bannersFor(base())).toEqual([]);
  });
  it('shows a stale source with its last good time', () => {
    const b = bannersFor(base({ sources: { ...base().sources, github: { ...ok, stale: true } } }));
    expect(b).toHaveLength(1);
    expect(b[0]?.text).toMatch(/GitHub data is stale\. Last good read: /);
  });
  it('shows the update banner for a newer schema', () => {
    const b = bannersFor(base({ schema: 2 }));
    expect(b[0]?.command).toBe('npm i -g @caddis/cli@latest');
  });
  it('shows claude agents failing once, not also as stale', () => {
    const bad = { ok: false, last_ok_at: null, last_error: 'exit 1', stale: true };
    const b = bannersFor(base({ sources: { ...base().sources, agents: bad } }));
    expect(b.map((x) => x.id)).toEqual(['agents-failed']);
  });
});

describe('quota and degraded flags', () => {
  const base = { sources: { a: { ok: true, stale: false } } } as unknown as HubState;
  it('quotaLow shows the lowest account under the reserve and nothing without data', () => {
    expect(quotaLow(null)).toBeNull();
    expect(quotaLow(base)).toBeNull();
    const withRate = (rate: unknown) => ({ ...base, github_rate: rate }) as unknown as HubState;
    expect(quotaLow(withRate({ a: { remaining: 4000, reset_at: null } }))).toBeNull();
    expect(quotaLow(withRate({ a: { remaining: 400, reset_at: null }, b: { remaining: 90, reset_at: '2026-10-24T11:00:00Z' } }))).toEqual({
      account: 'b',
      remaining: 90,
      resetAt: '2026-10-24T11:00:00Z',
    });
    expect(quotaLow(withRate('junk'))).toBeNull();
    expect(quotaLow(withRate({ a: { remaining: 'x' } }))).toBeNull();
  });
  it('anySourceDown is true for a failing or a stale source', () => {
    expect(anySourceDown(base)).toBe(false);
    expect(anySourceDown({ sources: { a: { ok: false, stale: false } } } as unknown as HubState)).toBe(true);
    expect(anySourceDown({ sources: { a: { ok: true, stale: true } } } as unknown as HubState)).toBe(true);
  });
});

describe('nav repo dot (review minor 11)', () => {
  const base = (waiting_class: 'owner' | 'peer' | null): HubState =>
    ({
      sources: { coordinator: { ok: true, stale: false, last_ok_at: null, last_error: null } },
      sessions: [{ repo_path: '/srv/demo/shop', waiting_for: 'review', waiting_class }],
      repos: [],
    }) as unknown as HubState;
  const repo = { path: '/srv/demo/shop', name: 'shop', coordinator: null, github: null } as unknown as HubState['repos'][number];
  it('marks attention only for a debounced owner wait, like the lane', () => {
    expect(repoTone(repo, base('owner'))).toBe('attention');
    expect(repoTone(repo, base(null))).toBe('ok');
    expect(repoTone(repo, base('peer'))).toBe('ok');
  });
});
