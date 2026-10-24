import type { Locator, Page } from '@playwright/test';
import { cspViolations, expect, test } from './fixtures';

/**
 * H4 in the browser (R47-R50, parity table P1-P28): the repo Roadmap and Sessions tabs. The server is real, the state
 * is a fixture. The parity checklist is also checked by test/ui/parity.test.ts on static markup.
 */
const SHOP = '#/repo/acme__shop';

async function noHorizontalScroll(page: Page): Promise<void> {
  const m = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
  expect(m.scroll, `scrollWidth ${m.scroll} > clientWidth ${m.client}`).toBeLessThanOrEqual(m.client);
}

async function hasFocusRing(el: Locator): Promise<boolean> {
  return el.evaluate((node) => {
    const cs = getComputedStyle(node);
    return (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || cs.boxShadow !== 'none';
  });
}

const SECTIONS = ['rm-header', 'rm-chips', 'rm-waiting', 'rm-kpis', 'rm-flow', 'rm-board', 'rm-timeline', 'rm-gates', 'rm-milestones', 'rm-runner'];

test.describe('Roadmap tab', () => {
  test('several roadmaps: a list with progress and next item, the read error, and a click opens one', async ({ page, openHub }) => {
    const { problems } = await openHub('full', undefined, `${SHOP}/roadmap`);
    await expect(page.getByTestId('tab-roadmap')).toContainText('Roadmap · 1 gate');
    await expect(page.getByTestId('rm-card')).toHaveCount(2);
    const launch = page.getByTestId('rm-card').filter({ hasText: 'launch' });
    await expect(launch).toContainText('1/3 milestones');
    await expect(launch).toContainText('next: S2 p-shop#3');
    await expect(launch).toContainText('runner: running');
    await expect(launch).toContainText('1 open gate');
    await expect(page.getByTestId('rm-errors')).toContainText('Could not read broken: line 4: not a table');

    await launch.click();
    await expect(page).toHaveURL(/#\/repo\/acme__shop\/roadmap\/launch$/);
    for (const id of SECTIONS) await expect(page.getByTestId(id)).toBeVisible();
    await expect(page.getByTestId('rm-header')).toContainText('1 of 3 milestones · 2 of 5 phases done');
    await expect(page.getByTestId('rm-crumbs')).toContainText('acme/shop');
    // Back to the list through the crumbs.
    await page.getByTestId('rm-crumbs').getByRole('link', { name: 'Roadmaps' }).click();
    await expect(page.getByTestId('rm-list')).toBeVisible();
    expect(await cspViolations(page)).toEqual([]);
    expect(problems.console).toEqual([]);
  });

  test('one roadmap opens directly', async ({ page, openHub }) => {
    await openHub('full', undefined, '#/repo/acme__billing/roadmap');
    await expect(page.getByTestId('rm-detail')).toBeVisible();
    await expect(page.getByTestId('rm-list')).toHaveCount(0);
    await expect(page.getByTestId('rm-crumbs').getByRole('link')).toHaveCount(0);
  });

  test('items link to their PR and show a stage', async ({ page, openHub }) => {
    await openHub('full', undefined, `${SHOP}/roadmap/launch`);
    const phase = page.getByTestId('rm-phase').filter({ hasText: 'p-shop#3' });
    await page.getByTestId('rm-milestones').locator('summary').nth(1).click();
    await expect(phase.getByTestId('rm-pr')).toHaveAttribute('href', 'https://github.com/acme/shop/pull/213');
    await expect(phase.getByTestId('rm-stage')).toContainText('in review');
    await page.getByTestId('rm-milestones').locator('summary').nth(0).click();
    await expect(page.getByTestId('rm-phase').filter({ hasText: 'p-shop#2' }).getByTestId('rm-stage')).toContainText('merged');
  });

  test('search filters the rows, counts matches, and / focuses the box', async ({ page, openHub }) => {
    await openHub('full', undefined, `${SHOP}/roadmap/launch`);
    await page.locator('main').click({ position: { x: 5, y: 5 } });
    await page.keyboard.press('/');
    await expect(page.getByTestId('rm-search')).toBeFocused();
    await page.keyboard.type('search');
    await expect(page.getByTestId('rm-match-count')).toHaveText('1 match');
    await expect(page.getByTestId('rm-phase')).toHaveCount(1);
    await expect(page.getByTestId('rm-phase')).toContainText('Search filters');
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('rm-match-count')).toHaveText('');
    await page.getByTestId('rm-search').fill('zzz-nothing');
    await expect(page.getByTestId('rm-match-count')).toHaveText('0 matches');
  });

  test('no roadmap: the active plans, then the empty text with the command', async ({ page, openHub }) => {
    await openHub('full', undefined, '#/repo/acme__docs/roadmap');
    await expect(page.getByTestId('rm-plans')).toContainText('p-docs');
    await expect(page.getByTestId('rm-plans')).toContainText('Phase 2');
    await openHub('full', (s) => {
      const docs = s.repos.find((r: { name: string }) => r.name === 'docs');
      docs.roadmaps = null;
      docs.plans = null;
    }, '#/repo/acme__docs/roadmap');
    await expect(page.getByTestId('rm-none')).toContainText('No roadmap or plan');
    await expect(page.getByTestId('rm-none')).toContainText('/caddis:roadmap');
  });

  test('a stale collector greys the numbers and says why', async ({ page, openHub }) => {
    await openHub(
      'full',
      (s) => {
        s.sources.collector = { ok: true, last_ok_at: '2026-10-24T10:00:00Z', last_error: null, stale: true };
      },
      `${SHOP}/roadmap`,
    );
    await expect(page.getByTestId('rm-stale')).toContainText('Roadmap data is old');
  });
});

test.describe('Sessions tab', () => {
  test('lists the repo sessions with status, waiting for, and a copy warning', async ({ page, openHub, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    await openHub(
      'full',
      (s) => {
        s.sessions[1].copies = 2;
      },
      `${SHOP}/sessions`,
    );
    await expect(page.getByTestId('session-row')).toHaveCount(3);
    await expect(page.getByTestId('session-row').first()).toContainText('demo-session-api');
    await expect(page.getByTestId('session-row').first()).toContainText('waiting for you: permission prompt');
    await expect(page.getByTestId('session-copies')).toHaveText('2 copies');
    await page.getByRole('button', { name: 'Copy session name demo-session-api' }).click();
    await expect(page.getByRole('button', { name: 'Copy session name demo-session-api' })).toContainText('Copied');
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('demo-session-api');
  });

  test('a repo with no sessions says so', async ({ page, openHub }) => {
    await openHub(
      'full',
      (s) => {
        s.sessions = [];
      },
      `${SHOP}/sessions`,
    );
    await expect(page.getByTestId('sessions-empty')).toContainText('No sessions running');
  });

  test('claude agents failing shows unknown with the error', async ({ page, openHub }) => {
    await openHub(
      'full',
      (s) => {
        s.sessions = [];
        s.sources.agents = { ok: false, last_ok_at: null, last_error: 'claude agents failed', stale: true };
      },
      `${SHOP}/sessions`,
    );
    await expect(page.getByTestId('sessions-error')).toContainText('Sessions unknown: claude agents failed');
  });
});

test.describe('tabs, themes and keyboard', () => {
  test('the tabs are links that change the route and mark the current tab', async ({ page, openHub }) => {
    await openHub('full', undefined, SHOP);
    await expect(page.getByTestId('tab-flow')).toHaveAttribute('aria-current', 'page');
    await page.getByTestId('tab-sessions').click();
    await expect(page).toHaveURL(/\/sessions$/);
    await expect(page.getByTestId('sessions')).toBeVisible();
    await page.getByTestId('tab-roadmap').click();
    await expect(page.getByTestId('roadmap-tab')).toBeVisible();
    await page.getByTestId('tab-flow').click();
    await expect(page.getByTestId('flow')).toBeVisible();
  });

  for (const theme of ['dark', 'light'] as const) {
    test(`${theme} theme renders the Roadmap detail`, async ({ page, openHub }) => {
      await openHub('full', undefined, `${SHOP}/roadmap/launch`);
      await page.getByRole('button', { name: theme, exact: true }).click();
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      for (const id of SECTIONS) await expect(page.getByTestId(id)).toBeVisible();
      const tile = page.getByTestId('rm-timeline').locator('.rm-tile[data-state="done"]').first();
      await expect(tile).toBeVisible();
    });
  }

  test('keyboard reaches the tabs, the search box, a milestone summary and the card links, each with a focus ring', async ({ page, openHub }) => {
    await openHub('full', undefined, `${SHOP}/roadmap/launch`);
    const targets: [string, Locator][] = [
      ['tab', page.getByTestId('tab-roadmap')],
      ['search', page.getByTestId('rm-search')],
      ['summary', page.getByTestId('rm-milestones').locator('summary').first()],
    ];
    for (const [name, loc] of targets) {
      await loc.focus();
      await expect(loc, name).toBeFocused();
      expect(await hasFocusRing(loc), `no focus ring on ${name}`).toBe(true);
    }
    // Enter on a summary opens it.
    await page.keyboard.press('Enter');
    await expect(page.getByTestId('rm-milestones').locator('details').first()).toHaveJSProperty('open', true);
    // Tab walks from the tab strip to the search box.
    await page.getByTestId('tab-sessions').focus();
    const seen: string[] = [];
    for (let i = 0; i < 6; i++) {
      await page.keyboard.press('Tab');
      seen.push(await page.evaluate(() => document.activeElement?.getAttribute('data-testid') ?? document.activeElement?.tagName ?? ''));
    }
    expect(seen).toContain('rm-search');
  });
});

test.describe('360 px', () => {
  test.use({ viewport: { width: 360, height: 740 } });

  for (const [name, hash] of [
    ['the roadmap list', `${SHOP}/roadmap`],
    ['the roadmap detail (list form of the timeline)', `${SHOP}/roadmap/launch`],
    ['a single roadmap', '#/repo/acme__billing/roadmap'],
    ['the plan fallback', '#/repo/acme__docs/roadmap'],
    ['Sessions', `${SHOP}/sessions`],
  ] as const) {
    test(`${name} has no horizontal scroll`, async ({ page, openHub }) => {
      await openHub('full', undefined, hash);
      await expect(page.locator('main')).toBeVisible();
      await noHorizontalScroll(page);
    });
  }

  test('the detail shows the list form, not the grid', async ({ page, openHub }) => {
    await openHub('full', undefined, `${SHOP}/roadmap/launch`);
    await expect(page.getByTestId('rm-timeline-list')).toBeVisible();
    await expect(page.locator('.rm-timeline-grid')).toBeHidden();
    await page.getByTestId('rm-milestones').locator('summary').first().click();
    await noHorizontalScroll(page);
  });
});
