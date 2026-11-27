import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { postSync, TAB_KEY } from '../../ui/src/api';
import { SyncButton } from '../../ui/src/shell/SyncButton';

const mem = () => {
  const m = new Map<string, string>();
  return { m, getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) };
};

describe('SyncButton markup', () => {
  it('idle: a button with the label, the test id and no busy state', () => {
    const out = renderToStaticMarkup(createElement(SyncButton, { syncing: false, onSync: () => undefined }));
    expect(out).toContain('data-testid="hub-sync-now"');
    expect(out).toContain('type="button"');
    expect(out).toContain('aria-busy="false"');
    expect(out).toContain('Sync now');
    expect(out).not.toContain('disabled');
    expect(out).not.toContain('Syncing');
    // The icon is decoration.
    expect(out).toContain('aria-hidden="true"');
  });

  it('busy: disabled, aria-busy, the spinning class and the Syncing label', () => {
    const out = renderToStaticMarkup(createElement(SyncButton, { syncing: true, onSync: () => undefined }));
    expect(out).toContain('disabled=""');
    expect(out).toContain('aria-busy="true"');
    expect(out).toContain('syncing');
    expect(out).toContain('Syncing…');
    expect(out).not.toContain('Sync now');
  });
});

describe('postSync', () => {
  const origWindow = globalThis.window;
  const origFetch = globalThis.fetch;
  beforeEach(() => {
    const local = mem();
    local.setItem(TAB_KEY, 'tab1');
    globalThis.window = { localStorage: local, sessionStorage: mem() } as unknown as Window & typeof globalThis;
  });
  afterEach(() => {
    globalThis.window = origWindow;
    globalThis.fetch = origFetch;
  });

  const reply = (status: number, body: unknown = {}): Response =>
    ({ ok: status >= 200 && status < 300, status, json: async () => body }) as unknown as Response;

  it('posts to /api/hub/sync with the tab and CSRF headers, no body, and reports ok', async () => {
    const calls: { url: string; init: RequestInit }[] = [];
    globalThis.fetch = vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      return url === '/api/session' ? reply(200, { schema: 1, csrf_token: 'csrf-a', versions: {} }) : reply(200, { schema: 1, ok: true });
    }) as unknown as typeof fetch;
    await expect(postSync()).resolves.toEqual({ ok: true });
    const sync = calls.find((c) => c.url === '/api/hub/sync');
    expect(sync?.init.method).toBe('POST');
    expect(sync?.init.headers).toMatchObject({ 'X-Caddis-Hub-Tab': 'tab1', 'X-CSRF-Token': 'csrf-a' });
    expect(sync?.init.credentials).toBe('same-origin');
    expect(sync?.init.body).toBeUndefined();
  });

  it('a 403 reads a new CSRF token and tries once more', async () => {
    let posts = 0;
    let tokens = 0;
    globalThis.fetch = vi.fn(async (url: string) => {
      if (url === '/api/session') return reply(200, { schema: 1, csrf_token: `csrf-${++tokens}`, versions: {} });
      posts += 1;
      return posts === 1 ? reply(403, { error: 'bad_csrf' }) : reply(200, { schema: 1, ok: true });
    }) as unknown as typeof fetch;
    await expect(postSync()).resolves.toEqual({ ok: true });
    expect(posts).toBe(2);
  });

  it('a refusal or a network failure is a value, not a throw', async () => {
    globalThis.fetch = vi.fn(async (url: string) =>
      url === '/api/session' ? reply(200, { schema: 1, csrf_token: 'c', versions: {} }) : reply(500, { error: 'sync_failed' }),
    ) as unknown as typeof fetch;
    await expect(postSync()).resolves.toEqual({ ok: false, error: 'The hub answered 500.' });
    globalThis.fetch = vi.fn(async () => {
      throw new Error('offline');
    }) as unknown as typeof fetch;
    await expect(postSync()).resolves.toEqual({ ok: false, error: 'The hub did not answer.' });
  });

  it('without a tab token it does not call the hub', async () => {
    globalThis.window = { localStorage: mem(), sessionStorage: mem() } as unknown as Window & typeof globalThis;
    globalThis.fetch = vi.fn() as unknown as typeof fetch;
    const r = await postSync();
    expect(r.ok).toBe(false);
    expect(r.error).toContain('caddis hub open');
    expect(fetch).not.toHaveBeenCalled();
  });
});
