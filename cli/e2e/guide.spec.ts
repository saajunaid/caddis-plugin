import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import type { Page } from '@playwright/test';
import { cspViolations, expect, test, type State } from './fixtures';

const fixture = JSON.parse(readFileSync(fileURLToPath(new URL('../test/fixtures/hub-state/guide.json', import.meta.url)), 'utf8')) as { guide: State };
const withGuide = (s: State): void => {
  s.guide = structuredClone(fixture.guide);
};
const SECTIONS = ['commands', 'agents', 'skills', 'hooks', 'runtimes'] as const;
const EXPECTED = { commands: 9, agents: 3, skills: 5, hooks: 3, runtimes: 3 };

const sectionCount = async (page: Page, id: string): Promise<number> => Number(await page.getByTestId(`guide-count-${id}`).textContent());

test.describe('caddis guide page', () => {
  test('renders and each section count equals the guide data', async ({ page, openHub }) => {
    const { problems } = await openHub('full', withGuide, '#/guide/details');
    await expect(page.getByRole('heading', { name: 'caddis guide', level: 1 })).toBeVisible();
    await expect(page.getByTestId('guide-version')).toContainText('caddis 9.9.9');
    for (const id of SECTIONS) expect(await sectionCount(page, id), id).toBe(EXPECTED[id]);
    await expect(page.getByTestId('guide-entry')).toHaveCount(Object.values(EXPECTED).reduce((a, b) => a + b, 0));
    await expect(page.getByText('/caddis:feature-plan')).toBeVisible();
    expect(await cspViolations(page)).toEqual([]);
    expect(problems.console).toEqual([]);
  });

  test('the nav entry has no soon badge and is current on the page', async ({ page, openHub }) => {
    await openHub('full', withGuide, '#/guide');
    const link = page.getByRole('link', { name: /caddis guide/ });
    await expect(link).toHaveAttribute('aria-current', 'page');
    await expect(link).not.toContainText('soon');
  });

  test('the filter narrows, shows n of m, and clears', async ({ page, openHub }) => {
    await openHub('full', withGuide, '#/guide/details');
    const total = Object.values(EXPECTED).reduce((a, b) => a + b, 0);
    const box = page.getByTestId('guide-filter');
    await box.fill('HANDOFF');
    await expect(page.getByTestId('guide-entry')).toHaveCount(1);
    await expect(page.getByTestId('guide-shown-commands')).toHaveText('1 of 9');
    expect(await sectionCount(page, 'commands')).toBe(9);
    await box.fill('zzz-no-such-entry');
    await expect(page.getByTestId('guide-nomatch')).toContainText('zzz-no-such-entry');
    await box.fill('');
    await expect(page.getByTestId('guide-entry')).toHaveCount(total);
  });

  const stateCases: [string, unknown, string][] = [
    ['missing', null, 'not ready yet'],
    ['error', { error: 'relay read failed' }, 'relay read failed'],
    ['newer schema', { ...fixture.guide, schema: 99 }, 'npm i -g @caddis/cli@latest'],
  ];
  for (const [name, guide, text] of stateCases) {
    test(`${name} state shows its text and no entries`, async ({ page, openHub }) => {
      await openHub('full', (s) => {
        s.guide = guide;
      }, '#/guide/details');
      await expect(page.getByTestId('guide-state')).toContainText(text);
      await expect(page.getByTestId('guide-entry')).toHaveCount(0);
    });
  }

  test.describe('360 px', () => {
    test.use({ viewport: { width: 360, height: 740 } });
    test('no horizontal scroll, with data and with a filter', async ({ page, openHub }) => {
      await openHub('full', withGuide, '#/guide/details');
      await expect(page.getByTestId('guide-entry').first()).toBeVisible();
      const fits = (): Promise<boolean> =>
        page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
      expect(await fits()).toBe(true);
      await page.getByTestId('guide-filter').fill('a');
      expect(await fits()).toBe(true);
    });
    test('the states fit too', async ({ page, openHub }) => {
      await openHub('full', (s) => {
        s.guide = null;
      }, '#/guide/details');
      await expect(page.getByTestId('guide-state')).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    });
  });

  for (const theme of ['dark', 'light'] as const) {
    test(`${theme} theme renders the page`, async ({ page, openHub }) => {
      await openHub('full', withGuide, '#/guide/details');
      const other = theme === 'dark' ? 'light' : 'dark';
      await page.getByRole('button', { name: other, exact: true }).click();
      await expect(page.locator('html')).toHaveAttribute('data-theme', other);
      const otherBg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
      await page.getByRole('button', { name: theme, exact: true }).click();
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      await expect(page.getByTestId('guide-entry').first()).toBeVisible();
      const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
      expect(bg).not.toBe(otherBg);
    });
  }

  test('keyboard reaches the filter and a section button, each with a focus ring', async ({ page, openHub }) => {
    await openHub('full', withGuide, '#/guide/details');
    await page.getByRole('link', { name: /caddis guide/ }).focus();
    const seen = new Set<string>();
    for (let i = 0; i < 60 && seen.size < 2; i++) {
      await page.keyboard.press('Tab');
      const info = await page.evaluate(() => {
        const el = document.activeElement as HTMLElement | null;
        if (!el) return null;
        const kind = el.matches('[data-testid="guide-filter"]') ? 'filter' : el.matches('.guide-jump') ? 'jump' : '';
        if (!kind) return null;
        const cs = getComputedStyle(el);
        return { kind, ring: cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0 };
      });
      if (!info) continue;
      expect(info.ring, `no focus ring on ${info.kind}`).toBe(true);
      seen.add(info.kind);
    }
    expect([...seen].sort()).toEqual(['filter', 'jump']);
  });

  test('the poster prints on at most 2 A3 pages', async ({ page, openHub }) => {
    await openHub('full', withGuide, '#/guide');
    await expect(page.locator('.gp-print')).toBeVisible();
    await page.emulateMedia({ media: 'print' });
    await expect(page.locator('.gp-flow')).toBeVisible();
    await expect(page.locator('.gp-map')).toBeVisible();
    const pdf = await page.pdf({ format: 'A3', landscape: true });
    const pages = (pdf.toString('latin1').match(/\/Type\s*\/Page(?!s)/g) ?? []).length;
    expect(pages).toBeGreaterThanOrEqual(1);
    expect(pages).toBeLessThanOrEqual(2);
  });
});
