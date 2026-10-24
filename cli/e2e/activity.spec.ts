import type { Page } from '@playwright/test';
import { cspViolations, expect, test } from './fixtures';

/**
 * H4 Activity in the browser (R52, R53): all six kinds, the filters, local time with the zone, 360 px, both themes
 * and the keyboard. The zone is fixed by the Playwright context, so the expected text does not depend on the machine.
 */
const ACTIVITY = '#/activity';

async function noHorizontalScroll(page: Page): Promise<void> {
  const m = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
  expect(m.scroll, `scrollWidth ${m.scroll} > clientWidth ${m.client}`).toBeLessThanOrEqual(m.client);
}

test.describe('Activity', () => {
  test.use({ timezoneId: 'Europe/Berlin', locale: 'en-GB' });

  test('shows every kind, newest first, with local time and the zone', async ({ page, openHub }) => {
    const { problems } = await openHub('full', undefined, ACTIVITY);
    await expect(page.getByRole('heading', { name: 'Activity', level: 1 })).toBeVisible();
    const kinds = await page.getByTestId('activity-item').evaluateAll((els) => [...new Set(els.map((e) => e.getAttribute('data-kind')))]);
    expect(kinds.sort()).toEqual(['approval', 'coordinator', 'deploy', 'health', 'merge', 'owner']);
    // The newest event of the fixture is the rejected request at 10:41 UTC, shown in Berlin time (CEST, UTC+2).
    const first = page.getByTestId('activity-item').first();
    await expect(first).toContainText('Coordinator rejected: request req-b');
    await expect(first).toContainText('head moved');
    await expect(first.locator('time')).toHaveText(/24 Oct 2026, 12:41 (CEST|GMT\+2)/);
    await expect(first.locator('time')).toHaveAttribute('datetime', '2026-10-24T10:41:00Z');
    await expect(page.getByTestId('activity-item').filter({ hasText: 'Refused: you marked as hotfix #212' })).toContainText('head_moved');
    expect(await cspViolations(page)).toEqual([]);
    expect(problems.console).toEqual([]);
  });

  test('a routine approval shows the coordinator and its reason', async ({ page, openHub }) => {
    await openHub('full', undefined, ACTIVITY);
    await page.getByTestId('kind-approval').click();
    const items = page.getByTestId('activity-item');
    await expect(items).toHaveCount(1);
    await expect(items.first()).toContainText('Coordinator approved: start phase 4');
    await expect(items.first()).toContainText('phase 3 done, its exit gate passed');
  });

  test('filters by repo and by kind', async ({ page, openHub }) => {
    await openHub('full', undefined, ACTIVITY);
    await expect(page.getByTestId('activity-item').first()).toBeVisible();
    const total = await page.getByTestId('activity-item').count();
    await page.getByTestId('activity-repo').selectOption('acme__billing');
    await expect(page.getByTestId('activity-item').first()).toBeVisible();
    const billing = await page.getByTestId('activity-item').count();
    expect(billing).toBeGreaterThan(0);
    expect(billing).toBeLessThan(total);
    await page.getByTestId('kind-merge').click();
    await expect(page.getByTestId('activity-item')).toHaveCount(1);
    await expect(page.getByTestId('activity-item').first()).toContainText('Merged #75 tax rounding');
    await expect(page.getByTestId('kind-merge')).toHaveAttribute('aria-pressed', 'true');
    // A second kind widens the filter; clearing the kinds shows the repo again.
    await page.getByTestId('kind-owner').click();
    await expect(page.getByTestId('activity-item')).toHaveCount(2);
    await page.getByTestId('kind-merge').click();
    await page.getByTestId('kind-owner').click();
    await expect(page.getByTestId('activity-item')).toHaveCount(billing);
    await page.getByTestId('activity-repo').selectOption('acme__docs');
    await page.getByTestId('kind-owner').click();
    await expect(page.getByTestId('activity-empty')).toContainText('No event matches these filters');
  });

  test('a PR link goes to GitHub', async ({ page, openHub }) => {
    await openHub('full', undefined, ACTIVITY);
    await expect(page.getByTestId('activity-pr').first()).toHaveAttribute('href', /^https:\/\/github\.com\/acme\/(shop|billing|docs)\/pull\/\d+$/);
  });

  test('the nav entry is a live link now, with no soon badge', async ({ page, openHub }) => {
    await openHub('full');
    const link = page.locator('nav[aria-label="Main"] a.nav-link', { hasText: 'Activity' });
    await expect(link).not.toContainText('soon');
    await link.click();
    await expect(page.getByTestId('activity')).toBeVisible();
    await expect(link).toHaveAttribute('aria-current', 'page');
  });

  test('empty state', async ({ page, openHub }) => {
    await openHub('empty', undefined, ACTIVITY);
    await expect(page.getByTestId('activity-empty')).toContainText('No activity yet');
  });

  for (const theme of ['dark', 'light'] as const) {
    test(`${theme} theme renders the page`, async ({ page, openHub }) => {
      await openHub('full', undefined, ACTIVITY);
      await page.getByRole('button', { name: theme, exact: true }).click();
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      await expect(page.getByTestId('activity-item').first()).toBeVisible();
    });
  }

  test('keyboard reaches the repo filter and the kind buttons, each with a focus ring', async ({ page, openHub }) => {
    await openHub('full', undefined, ACTIVITY);
    const select = page.getByTestId('activity-repo');
    const merge = page.getByTestId('kind-merge');
    for (const el of [select, merge]) {
      await el.focus();
      await expect(el).toBeFocused();
      const ring = await el.evaluate((n) => {
        const cs = getComputedStyle(n);
        return (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || cs.boxShadow !== 'none';
      });
      expect(ring).toBe(true);
    }
    await page.keyboard.press('Space');
    await expect(merge).toHaveAttribute('aria-pressed', 'true');
    await select.focus();
    await page.keyboard.press('ArrowDown');
    await expect(select).not.toHaveValue('');
  });

  test('Show more adds the next page', async ({ page, openHub }) => {
    await openHub(
      'full',
      (s) => {
        s.audit = Array.from({ length: 150 }, (_, i) => ({
          at: new Date(Date.parse('2026-10-24T08:00:00Z') + i * 1000).toISOString(),
          request_id: `r${i}`,
          repo: 'acme__shop',
          pr: i + 1,
          action: 'hold',
          what: null,
          result: 'requested',
          reason: null,
        }));
      },
      ACTIVITY,
    );
    await expect(page.getByTestId('activity-item')).toHaveCount(100);
    await page.getByTestId('activity-more').click();
    await expect(page.getByTestId('activity-item').count()).resolves.toBeGreaterThan(100);
  });
});

test.describe('Activity at 360 px', () => {
  test.use({ viewport: { width: 360, height: 740 } });
  test('no horizontal scroll', async ({ page, openHub }) => {
    await openHub('full', undefined, ACTIVITY);
    await expect(page.getByTestId('activity-item').first()).toBeVisible();
    await noHorizontalScroll(page);
  });
});
