import type { Page } from '@playwright/test';
import { cspViolations, expect, test } from './fixtures';

async function noHorizontalScroll(page: Page): Promise<void> {
  const m = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }));
  expect(m.scroll, `scrollWidth ${m.scroll} > clientWidth ${m.client}`).toBeLessThanOrEqual(m.client);
}

test.describe('Sync now', () => {
  test('renders, takes keyboard focus with a visible ring, and syncs on Enter, then reloads the state', async ({ page, openHub }) => {
    const hub = await openHub('full');
    const button = page.getByTestId('hub-sync-now');
    await expect(button).toBeVisible();
    await expect(button).toHaveAttribute('type', 'button');
    await expect(button).toContainText('Sync now');

    await button.focus();
    await expect(button).toBeFocused();
    const ring = await button.evaluate((el) => getComputedStyle(el).outlineStyle);
    expect(ring).not.toBe('none');

    const stateAfter = page.waitForResponse((r) => new URL(r.url()).pathname === '/api/state' && r.request().method() === 'GET');
    const sync = page.waitForRequest((r) => new URL(r.url()).pathname === '/api/hub/sync' && r.method() === 'POST');
    await page.keyboard.press('Enter');
    const req = await sync;
    expect(req.headers()['x-csrf-token']).toBeTruthy();
    expect(req.headers()['x-caddis-hub-tab']).toBeTruthy();
    await stateAfter;
    await expect(button).toBeEnabled();
    expect(hub.syncCount()).toBe(1);
  });

  test('busy: disabled with aria-busy and the Syncing label until the hub answers; a second click does nothing', async ({
    page,
    openHub,
  }) => {
    const hub = await openHub('full');
    let release!: () => void;
    hub.onSync(() => new Promise<void>((resolve) => (release = resolve)));
    const button = page.getByTestId('hub-sync-now');
    await button.click();
    await expect(button).toBeDisabled();
    await expect(button).toHaveAttribute('aria-busy', 'true');
    await expect(button).toContainText('Syncing…');
    await expect.poll(() => hub.syncCount()).toBe(1);
    // A click on the disabled button (and the Enter key) starts no second sync.
    await button.click({ force: true });
    await page.keyboard.press('Enter');
    release();
    await expect(button).toBeEnabled();
    await expect(button).toHaveAttribute('aria-busy', 'false');
    await expect(button).toContainText('Sync now');
    expect(hub.syncCount()).toBe(1);
  });

  test('a failed sync shows a notice and keeps the data on screen', async ({ page, openHub }) => {
    const hub = await openHub('full');
    hub.onSync(async () => {
      throw new Error('boom');
    });
    await page.getByTestId('hub-sync-now').click();
    await expect(page.getByTestId('hub-sync-error')).toContainText('Sync failed');
    await expect(page.getByTestId('inbox-item').first()).toBeVisible();
    await expect(page.getByTestId('hub-sync-now')).toBeEnabled();
  });

  test('light and dark themes both show the button, and there is no CSP violation or console error', async ({ page, openHub }) => {
    const { problems } = await openHub('full');
    for (const theme of ['dark', 'light']) {
      await page.evaluate((t) => {
        document.documentElement.dataset.theme = t;
      }, theme);
      const button = page.getByTestId('hub-sync-now');
      await expect(button).toBeVisible();
      const color = await button.evaluate((el) => getComputedStyle(el).color);
      expect(color).not.toBe('rgba(0, 0, 0, 0)');
    }
    expect(await cspViolations(page)).toEqual([]);
    expect(problems.console).toEqual([]);
  });

  test.describe('360 px', () => {
    test.use({ viewport: { width: 360, height: 740 } });

    test('the button fits: no horizontal scroll, busy state too', async ({ page, openHub }) => {
      const hub = await openHub('full');
      await noHorizontalScroll(page);
      let release!: () => void;
      hub.onSync(() => new Promise<void>((resolve) => (release = resolve)));
      const button = page.getByTestId('hub-sync-now');
      await expect(button).toBeVisible();
      await button.click();
      await expect(button).toContainText('Syncing…');
      await noHorizontalScroll(page);
      await expect.poll(() => hub.syncCount()).toBe(1);
      release();
      await expect(button).toBeEnabled();
    });
  });
});
