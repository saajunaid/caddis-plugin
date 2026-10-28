import { spawnSync } from 'node:child_process';
import { createServer, type Server } from 'node:http';
import { existsSync, mkdtempSync, readFileSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test as base, type Locator, type Page } from '@playwright/test';
import { hubExport } from '../src/hub/export/export';
import { makeRepo, SHA40 } from '../test/fixtures/export/canary';

/**
 * H6.6 in the browser (R60, R63, R65, parity S1-S17): `caddis hub export` runs on the canary repo, and the folder it
 * writes is served by a static Node server under a sub-path, as GitHub Pages serves a project site. Every request must
 * go to that server. The page must run under its own CSP with no violation.
 */
const DIST = fileURLToPath(new URL('../dist/export', import.meta.url));
const PREFIX = '/serve-sight/';
const MIME: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.woff2': 'font/woff2',
  '.txt': 'text/plain; charset=utf-8',
};

interface Site {
  base: string;
  origin: string;
  requested: string[];
}

/** Serve `dir` under PREFIX. An unknown path gets `404.html` with status 404, as Pages does. */
async function serve(dir: string, requested: string[]): Promise<{ server: Server; origin: string }> {
  const server = createServer((req, res) => {
    const url = new URL(req.url ?? '/', 'http://x');
    requested.push(url.pathname);
    let file: string | null = null;
    if (url.pathname.startsWith(PREFIX)) {
      const rel = decodeURIComponent(url.pathname.slice(PREFIX.length)) || 'index.html';
      const full = path.join(dir, ...rel.split('/'));
      if (!rel.includes('..') && existsSync(full) && statSync(full).isFile()) file = full;
    }
    if (file) {
      res.writeHead(200, { 'content-type': MIME[path.extname(file)] ?? 'application/octet-stream' });
      res.end(readFileSync(file));
      return;
    }
    res.writeHead(404, { 'content-type': MIME['.html']! });
    res.end(readFileSync(path.join(dir, '404.html')));
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  const port = typeof address === 'object' && address ? address.port : 0;
  return { server, origin: `http://127.0.0.1:${port}` };
}

const HAVE_PYTHON = spawnSync('python', ['-c', 'print(1)'], { stdio: 'ignore' }).status === 0;

const test = base.extend<{ site: Site; problems: { console: string[]; foreign: string[]; csp: string[] } }>({
  site: async ({}, use) => {
    const tmp = mkdtempSync(path.join(tmpdir(), 'caddis-hub-export-e2e-'));
    const requested: string[] = [];
    let server: Server | undefined;
    try {
      const fx = makeRepo(tmp);
      const out = path.join(tmp, 'site');
      const code = await hubExport(
        { repo: fx.repo, out, github: 'acme/shop', commit: SHA40, label: 'built by CI' },
        { distDir: DIST, machine: { user: 'sample-user', host: 'sample-box-01' }, stdout: () => {}, stderr: (l) => console.error(l) },
      );
      expect(code).toBe(0);
      const s = await serve(out, requested);
      server = s.server;
      await use({ base: `${s.origin}${PREFIX}`, origin: s.origin, requested });
    } finally {
      server?.close();
      rmSync(tmp, { recursive: true, force: true });
    }
  },
  problems: async ({ page, site }, use) => {
    const problems = { console: [] as string[], foreign: [] as string[], csp: [] as string[] };
    page.on('console', (m) => {
      if (m.type() === 'error') problems.console.push(m.text());
    });
    page.on('pageerror', (e) => problems.console.push(String(e)));
    page.on('request', (r) => {
      const url = r.url();
      if (!url.startsWith(site.origin) && !url.startsWith('data:')) problems.foreign.push(url);
    });
    await page.addInitScript(() => {
      const w = window as unknown as { __csp?: string[] };
      document.addEventListener('securitypolicyviolation', (e) => {
        (w.__csp ??= []).push(`${e.violatedDirective} ${e.blockedURI}`);
      });
    });
    await use(problems);
    problems.csp.push(...(await page.evaluate(() => (window as unknown as { __csp?: string[] }).__csp ?? []).catch(() => [])));
  },
});

async function hasFocusRing(el: Locator): Promise<boolean> {
  return el.evaluate((node) => {
    const cs = getComputedStyle(node);
    return (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || cs.boxShadow !== 'none';
  });
}
const noHorizontalScroll = async (page: Page): Promise<void> => {
  const m = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
  expect(m.scroll, `scrollWidth ${m.scroll} > clientWidth ${m.client}`).toBeLessThanOrEqual(m.client);
};

test.skip(!HAVE_PYTHON || !existsSync(path.join(DIST, 'index.html')), 'needs python and `npm run build:ui`');

test.describe('Pages export', () => {
  test('home, Gates and a roadmap render, and no request leaves the static server', async ({ page, site, problems }) => {
    await page.goto(site.base);
    await expect(page.getByTestId('ex-banner')).toContainText('Live sessions and runners show only on the owner');
    await expect(page.getByTestId('ex-banner')).toContainText('built by CI');
    await expect(page.getByTestId('ex-kpis')).toBeVisible();
    await expect(page.getByTestId('ex-needs')).toBeVisible();
    await expect(page.getByTestId('rm-card')).toHaveCount(1);
    await expect(page.getByTestId('ex-note')).toBeVisible();
    await page.getByTestId('ex-nav').getByRole('link', { name: 'Gates' }).click();
    await expect(page).toHaveURL(`${site.base}#/gates`);
    await expect(page.getByTestId('ex-gates')).toContainText('owner signs off the catalog');
    await page.getByTestId('ex-nav').getByRole('link', { name: 'launch' }).click();
    await expect(page).toHaveURL(`${site.base}#/roadmap/launch`);
    for (const id of ['rm-header', 'rm-waiting', 'rm-kpis', 'rm-flow', 'rm-timeline', 'rm-gates', 'rm-milestones']) await expect(page.getByTestId(id)).toBeVisible();
    await expect(page.getByTestId('rm-runner')).toHaveCount(0);
    await expect(page.getByTestId('rm-pr').first()).toHaveAttribute('href', 'https://github.com/acme/shop/pull/11');
    // S14, S16: nothing left the server, nothing but its own files, and no API call.
    expect(problems.foreign).toEqual([]);
    expect(site.requested.every((p) => p.startsWith(PREFIX))).toBe(true);
    expect(site.requested.some((p) => p.includes('/api/'))).toBe(false);
    expect(problems.csp).toEqual([]);
    expect(problems.console).toEqual([]);
  });

  test('the page makes no request after it loads (no timer, no fetch)', async ({ page, site }) => {
    await page.goto(site.base);
    await expect(page.getByTestId('ex-kpis')).toBeVisible();
    await page.waitForLoadState('networkidle');
    const before = site.requested.length;
    await page.waitForTimeout(1500);
    expect(site.requested.length).toBe(before);
  });

  test('an old #rm-<hex>-<slug> hash opens the roadmap (S17)', async ({ page, site }) => {
    await page.goto(`${site.base}#rm-1a2b3c-launch`);
    await expect(page.getByTestId('rm-detail')).toBeVisible();
    await expect(page.getByTestId('rm-header')).toContainText('Roadmap launch');
  });

  test('an old <folder>/<slug>.html link goes through 404.html to the roadmap', async ({ page, site, problems }) => {
    await page.goto(`${site.base}launch-1a2b3c/launch.html`);
    await expect(page).toHaveURL(`${site.base}#/roadmap/launch`);
    await expect(page.getByTestId('rm-detail')).toBeVisible();
    expect(problems.csp).toEqual([]);
    expect(problems.foreign).toEqual([]);
  });

  test('theme: dark and light both render', async ({ page, site }) => {
    await page.goto(`${site.base}#/roadmap/launch`);
    for (const theme of ['dark', 'light'] as const) {
      await page.getByRole('button', { name: theme, exact: true }).click();
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      await expect(page.getByTestId('rm-kpis')).toBeVisible();
    }
  });

  test('keyboard reaches the nav, the search box and a milestone summary, each with a focus ring; / focuses the search', async ({ page, site }) => {
    await page.goto(`${site.base}#/roadmap/launch`);
    const targets: [string, Locator][] = [
      ['nav', page.getByTestId('ex-nav').getByRole('link', { name: 'Home' })],
      ['search', page.getByTestId('rm-search')],
      ['summary', page.getByTestId('rm-milestones').locator('summary').first()],
    ];
    for (const [name, loc] of targets) {
      await loc.focus();
      await expect(loc, name).toBeFocused();
      expect(await hasFocusRing(loc), `no focus ring on ${name}`).toBe(true);
    }
    await page.locator('body').click({ position: { x: 1, y: 1 } });
    await page.keyboard.press('/');
    await expect(page.getByTestId('rm-search')).toBeFocused();
    await page.keyboard.type('Check out');
    await expect(page.getByTestId('rm-match-count')).toContainText('match');
  });

  test('first load is under 1 s from a local server (R65)', async ({ page, site }) => {
    const t0 = Date.now();
    await page.goto(site.base);
    await expect(page.getByTestId('ex-kpis')).toBeVisible();
    const ms = Date.now() - t0;
    expect(ms, `first load took ${ms} ms`).toBeLessThan(1000);
  });

  test.describe('360 px', () => {
    test.use({ viewport: { width: 360, height: 740 } });

    test('no horizontal scroll on home, Gates and the roadmap, which shows the list form', async ({ page, site }) => {
      await page.goto(site.base);
      await expect(page.getByTestId('ex-kpis')).toBeVisible();
      await noHorizontalScroll(page);
      await page.goto(`${site.base}#/gates`);
      await expect(page.getByTestId('ex-gates')).toBeVisible();
      await noHorizontalScroll(page);
      await page.goto(`${site.base}#/roadmap/launch`);
      await expect(page.getByTestId('rm-timeline-list')).toBeVisible();
      await noHorizontalScroll(page);
    });
  });
});
