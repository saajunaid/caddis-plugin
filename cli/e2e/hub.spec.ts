import type { Page } from '@playwright/test';
import { cspViolations, expect, test } from './fixtures';

const PAGES = ['#/inbox', '#/overview', '#/activity', '#/guide'] as const;

async function noHorizontalScroll(page: Page): Promise<void> {
  const m = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }));
  expect(m.scroll, `scrollWidth ${m.scroll} > clientWidth ${m.client}`).toBeLessThanOrEqual(m.client);
}

const go = (page: Page, hash: string): Promise<void> =>
  page.evaluate((x) => {
    window.location.hash = x;
  }, hash);

test.describe('sign in and render', () => {
  test('full: Inbox and Overview render with data, no CSP violation, no console error', async ({ page, openHub }) => {
    const { problems } = await openHub('full');
    await expect(page.getByRole('heading', { name: 'Inbox', level: 1 })).toBeVisible();
    await expect(page.getByTestId('inbox-item').first()).toBeVisible();
    await expect(page.getByTestId('tiles')).toBeVisible();
    await expect(page).toHaveTitle(/^\(\d+\) caddis hub$/);
    // The #tab token (when the server sends one) is removed from the URL by the page.
    expect(page.url()).not.toContain('tab=');

    await page.getByRole('link', { name: 'Overview' }).click();
    await expect(page.getByRole('heading', { name: 'Overview', level: 1 })).toBeVisible();
    await expect(page.getByTestId('lane')).toHaveCount(3);
    expect(await cspViolations(page)).toEqual([]);
    expect(problems.console).toEqual([]);
  });

  test('the CSP header comes with the page and fonts load from self', async ({ page, openHub }) => {
    const { port } = await openHub('full');
    const res = await page.request.get(`http://127.0.0.1:${port}/`);
    expect(res.headers()['content-security-policy']).toContain("default-src 'self'");
    const fonts = await page.evaluate(async () => {
      await document.fonts.ready;
      return [...document.fonts].filter((f) => f.status === 'loaded').length;
    });
    expect(fonts).toBeGreaterThan(0);
  });

  test('without a session the page asks for sign in and shows no data', async ({ page, openHub }) => {
    const { port } = await openHub('full');
    await page.context().clearCookies();
    await page.goto(`http://127.0.0.1:${port}/`);
    await expect(page.getByTestId('signin')).toContainText('caddis hub open');
    await expect(page.getByTestId('inbox-item')).toHaveCount(0);
  });
});

test.describe('360 px: no horizontal scroll', () => {
  test.use({ viewport: { width: 360, height: 740 } });

  for (const name of ['full', 'empty', 'no-coordinator', 'degraded'] as const) {
    test(`${name}: every page fits`, async ({ page, openHub }) => {
      await openHub(name);
      const repoLinks = await page.evaluate(() =>
        [...document.querySelectorAll<HTMLAnchorElement>('a[href^="#/repo/"]')].map((a) => a.getAttribute('href') ?? ''),
      );
      for (const h of [...PAGES, ...repoLinks]) {
        await go(page, h);
        await expect(page.locator('main')).toBeVisible();
        await noHorizontalScroll(page);
      }
    });
  }

  test('full: the Inbox detail view fits', async ({ page, openHub }) => {
    await openHub('full', undefined, '#/inbox');
    await page.getByTestId('inbox-item').first().click();
    await expect(page.getByTestId('inbox-detail')).toBeVisible();
    await noHorizontalScroll(page);
  });
});

test.describe('empty and degraded states (design section 6)', () => {
  test('first run: onboarding, add folder disabled with its reason', async ({ page, openHub }) => {
    await openHub('empty');
    const first = page.getByTestId('first-run');
    await expect(first).toContainText('Start a Claude Code session in a repo');
    await expect(page.getByTestId('add-folder')).toBeDisabled();
    await expect(first).toContainText('Start a session in the folder: the hub adds it.');
    // The same page shows the empty inbox with the last check time.
    await expect(page.getByTestId('inbox-empty')).toContainText('Nothing needs you');
    await expect(page.getByTestId('inbox-empty')).toContainText('Last check');
    await page.getByRole('link', { name: 'Overview' }).click();
    await expect(page.getByTestId('first-run')).toBeVisible();
  });

  test('repo with no coordinator: queue column text and the hint', async ({ page, openHub }) => {
    await openHub('no-coordinator', undefined, '#/overview');
    await expect(page.getByTestId('lane-note')).toContainText('No coordinator: each session merges its own PRs.');
    await expect(page.getByTestId('lane-note')).toContainText('/caddis:coordinate');
    await expect(page.getByTestId('col-waiting')).toContainText('No coordinator: each session merges its own PRs.');
  });

  test('coordinator down: the time, and the greyed last known queue', async ({ page, openHub }) => {
    await openHub('full', undefined, '#/overview');
    await expect(page.getByTestId('lane-summary').filter({ hasText: 'Coordinator not responding since' })).toHaveCount(1);
    await expect(page.getByTestId('lane-note').filter({ hasText: 'last known queue' })).toHaveCount(1);
    await expect(page.locator('.card.grey').first()).toBeVisible();
  });

  test('repo with no sessions says so', async ({ page, openHub }) => {
    await openHub(
      'no-coordinator',
      (s) => {
        s.sessions = [];
      },
      '#/overview',
    );
    await expect(page.getByTestId('col-sessions')).toContainText('No sessions running');
  });

  test('inbox with no items: Nothing needs you', async ({ page, openHub }) => {
    await openHub('no-coordinator', (s) => {
      s.sessions = [];
      for (const r of s.repos) {
        r.github.prs = [];
        r.relays = null;
      }
    });
    await expect(page.getByTestId('inbox-empty')).toContainText('Nothing needs you');
  });

  test('degraded: claude agents fails, gh fails for one repo, a stale source, a newer schema', async ({ page, openHub }) => {
    await openHub('degraded');
    await expect(page.getByText('Session list unavailable')).toContainText('claude agents');
    await expect(page.getByText('GitHub data is stale')).toContainText('Last good read');
    await expect(page.getByText('Update the hub')).toBeVisible();
    await expect(page.getByText('npm i -g @caddis/cli@latest')).toBeVisible();
    await page.getByRole('link', { name: 'Overview' }).click();
    const gh = page.getByTestId('gh-fail');
    await expect(gh).toContainText('account demo');
    await expect(gh).toContainText('gh auth login -h github.com');
    await expect(page.getByTestId('col-sessions')).toContainText('unknown');
    await expect(page.getByTestId('tiles')).toHaveAttribute('data-stale', 'true');
  });

  test('a schema newer than the hub: banner, and the page still renders', async ({ page, openHub }) => {
    await openHub('full', (s) => {
      s.schema = 99;
    });
    await expect(page.getByText('Update the hub')).toBeVisible();
    await expect(page.getByTestId('inbox-item').first()).toBeVisible();
  });

  test('low GitHub quota shows in the footer', async ({ page, openHub }) => {
    await openHub('full', (s) => {
      s.github_rate = { demo: { remaining: 120, reset_at: '2026-10-24T11:20:00Z' } };
    });
    await expect(page.getByTestId('quota-low')).toContainText('GitHub quota low: 120 left (demo)');
  });

  test('a failing source keeps its inbox items, marked stale, instead of resolving them', async ({ page, openHub }) => {
    const hub = await openHub('full');
    const waiting = page.getByTestId('inbox-item').filter({ hasText: 'demo-session-api waits on' });
    await expect(waiting).toHaveCount(1);
    await expect(page.getByTestId('stale-chip')).toHaveCount(0);

    hub.update((s) => {
      s.sessions = [];
      s.sources.agents = { ok: false, last_ok_at: s.generated_at, last_error: 'timed out', stale: false };
    });
    await page.clock.fastForward(11_000); // the next 10 s poll
    await expect(waiting).toHaveCount(1);
    await expect(waiting.getByTestId('stale-chip')).toBeVisible();

    // The source comes back and the sessions are really gone: the item resolves.
    hub.update((s) => {
      s.sources.agents = { ok: true, last_ok_at: s.generated_at, last_error: null, stale: false };
    });
    await page.clock.fastForward(11_000);
    await expect(waiting).toHaveCount(0);
    await page.getByTestId('folder-resolved').click();
    await expect(page.getByTestId('inbox-item').filter({ hasText: 'demo-session-api waits on' })).toHaveCount(1);
  });
});

test.describe('themes and keyboard', () => {
  for (const theme of ['dark', 'light'] as const) {
    test(`${theme} theme renders both pages`, async ({ page, openHub }) => {
      await openHub('full');
      await page.getByRole('button', { name: theme, exact: true }).click();
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      await expect(page.getByTestId('inbox-item').first()).toBeVisible();
      await page.getByRole('link', { name: 'Overview' }).click();
      await expect(page.getByTestId('lane').first()).toBeVisible();
    });
  }

  test('the two themes use different backgrounds', async ({ page, openHub }) => {
    await openHub('full');
    const bgOf = async (t: 'dark' | 'light'): Promise<string> => {
      await page.getByRole('button', { name: t, exact: true }).click();
      return page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    };
    expect(await bgOf('dark')).not.toBe(await bgOf('light'));
  });

  test('Tab reaches every nav entry with a visible focus ring', async ({ page, openHub }) => {
    await openHub('full');
    const navLinks = await page.locator('nav[aria-label="Main"] a.nav-link').count();
    expect(navLinks).toBeGreaterThan(3);
    const seen = new Set<string>();
    for (let i = 0; i < 40 && seen.size < navLinks; i++) {
      await page.keyboard.press('Tab');
      const info = await page.evaluate(() => {
        const el = document.activeElement as HTMLElement | null;
        if (!el || !el.matches('nav[aria-label="Main"] a.nav-link')) return null;
        const cs = getComputedStyle(el);
        const ring = (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || cs.boxShadow !== 'none';
        return { href: el.getAttribute('href') ?? '', ring };
      });
      if (!info) continue;
      expect(info.ring, `no focus ring on ${info.href}`).toBe(true);
      seen.add(info.href);
    }
    expect(seen.size).toBe(navLinks);
  });
});
