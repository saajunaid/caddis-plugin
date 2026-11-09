import type { Page } from '@playwright/test';
import { cspViolations, expect, test } from './fixtures';

async function noHorizontalScroll(page: Page): Promise<void> {
  const m = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }));
  expect(m.scroll, `scrollWidth ${m.scroll} > clientWidth ${m.client}`).toBeLessThanOrEqual(m.client);
}

const dialog = (page: Page) => page.getByRole('dialog', { name: 'Jump to anything' });

test.describe('command palette (Ctrl K)', () => {
  test('Ctrl+K opens it, a repo name and Enter go to the repo, no CSP or console error', async ({ page, openHub }) => {
    const { problems } = await openHub('full', undefined, '#/inbox');
    await page.getByTestId('inbox-item').first().waitFor();
    await page.keyboard.press('Control+k');
    await expect(dialog(page)).toBeVisible();
    const input = page.getByRole('combobox', { name: 'Jump to anything' });
    await expect(input).toBeFocused();
    await input.fill('billing');
    await expect(page.getByTestId('palette-option').first()).toContainText('billing · Flow');
    await page.keyboard.press('Enter');
    await expect(dialog(page)).toHaveCount(0);
    await expect(page).toHaveURL(/#\/repo\/acme__billing$/);
    expect(await cspViolations(page)).toEqual([]);
    expect(problems.console).toEqual([]);
  });

  test('the sidebar button opens it; Escape closes it and focus goes back to the button', async ({ page, openHub }) => {
    await openHub('full', undefined, '#/overview');
    const btn = page.getByRole('button', { name: /Jump to anything/ });
    await btn.click();
    await expect(dialog(page)).toBeVisible();
    await expect(page.getByRole('combobox', { name: 'Jump to anything' })).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(dialog(page)).toHaveCount(0);
    await expect(btn).toBeFocused();
  });
});

test.describe('command palette at 360 px', () => {
  test.use({ viewport: { width: 360, height: 740 } });

  test('a full-width sheet with no horizontal scroll', async ({ page, openHub }) => {
    const { problems } = await openHub('full', undefined, '#/inbox');
    await page.getByTestId('inbox-item').first().waitFor();
    await page.keyboard.press('Control+k');
    await expect(page.getByRole('combobox', { name: 'Jump to anything' })).toBeFocused();
    await noHorizontalScroll(page);
    await page.getByRole('combobox', { name: 'Jump to anything' }).fill('#2');
    await expect(page.getByTestId('palette-option').first()).toBeVisible();
    await noHorizontalScroll(page);
    const box = await dialog(page).boundingBox();
    expect(box?.width).toBe(360);
    // From the phone drawer: the button closes the drawer and opens the palette.
    await page.keyboard.press('Escape');
    await page.getByRole('button', { name: 'Open navigation menu' }).click();
    await page.getByRole('button', { name: /Jump to anything/ }).click();
    await expect(dialog(page)).toBeVisible();
    await expect(page.locator('#app-sidebar')).not.toHaveAttribute('role', 'dialog');
    expect(await cspViolations(page)).toEqual([]);
    expect(problems.console).toEqual([]);
  });
});
