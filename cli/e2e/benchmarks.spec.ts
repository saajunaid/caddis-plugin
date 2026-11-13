import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import type { Page } from '@playwright/test';
import { cspViolations, expect, test } from './fixtures';

/** The Benchmarks page in the browser: the sidebar link, the table, the empty state, and 360 px. */
const BOARD: unknown = JSON.parse(readFileSync(fileURLToPath(new URL('../test/fixtures/review-scoreboard.json', import.meta.url)), 'utf8'));
const WITH_BOARD = { boards: [{ repo: 'caddis', path: 'evals/results/review-scoreboard.json', board: BOARD }], errors: [] };

async function noHorizontalScroll(page: Page): Promise<void> {
  const m = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
  expect(m.scroll, `scrollWidth ${m.scroll} > clientWidth ${m.client}`).toBeLessThanOrEqual(m.client);
}

test.describe('Benchmarks', () => {
  test('the sidebar link opens the page and the table is visible', async ({ page, openHub }) => {
    const { problems } = await openHub('full', undefined, '', WITH_BOARD);
    const link = page.locator('nav[aria-label="Main"] a.nav-link', { hasText: 'Benchmarks' });
    await link.click();
    await expect(page.getByRole('heading', { name: 'Benchmarks', level: 1 })).toBeVisible();
    await expect(page.getByTestId('bm-table')).toBeVisible();
    await expect(link).toHaveAttribute('aria-current', 'page');
    await expect(page.getByTestId('bm-row')).toHaveCount(3);
    await expect(page.getByTestId('bm-row').first()).toContainText('sonnet');
    await expect(page.getByTestId('bm-row').first()).toContainText('USD 0.21');
    await expect(page.getByTestId('bm-row').last()).toContainText('no result (10 of 10 runs not run)');
    await expect(page.getByTestId('bm-proposed')).toContainText('claude-sonnet (tier 2: claude-opus), deepseek, glm');
    expect(await cspViolations(page)).toEqual([]);
    expect(problems.console).toEqual([]);
  });

  test('a hub with no scoreboard shows the empty state', async ({ page, openHub }) => {
    await openHub('full', undefined, '#/benchmarks', { boards: [], errors: [] });
    await expect(page.getByTestId('bm-empty')).toHaveText('No benchmark yet. Run evals/review_eval.py score.');
  });

  for (const theme of ['dark', 'light'] as const) {
    test(`${theme} theme renders the table`, async ({ page, openHub }) => {
      await openHub('full', undefined, '#/benchmarks', WITH_BOARD);
      await page.getByRole('button', { name: theme, exact: true }).click();
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      await expect(page.getByTestId('bm-table')).toBeVisible();
    });
  }
});

test.describe('Benchmarks at 360 px', () => {
  test.use({ viewport: { width: 360, height: 740 } });
  test('no horizontal scroll', async ({ page, openHub }) => {
    await openHub('full', undefined, '#/benchmarks', WITH_BOARD);
    await expect(page.getByTestId('bm-table')).toBeVisible();
    await noHorizontalScroll(page);
  });
});
