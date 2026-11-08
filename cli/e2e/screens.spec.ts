import { mkdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test, type State } from './fixtures';

/**
 * Screenshots for the hub UX audit (plan hub-done-plans, Phase 6). Runs only when CADDIS_SCREENS_DIR is set; it
 * writes `<dir>/<page>-<theme>-<width>.png` (full page) and asserts nothing about the look.
 */
const DIR = process.env.CADDIS_SCREENS_DIR;

const guide = JSON.parse(readFileSync(fileURLToPath(new URL('../test/fixtures/hub-state/guide.json', import.meta.url)), 'utf8')) as { guide: State };
const withGuide = (s: State): void => {
  s.guide = structuredClone(guide.guide);
};

// The plan names overview, a Roadmap tab, a Sessions tab, guide and activity; the Inbox (the start page), the
// roadmap detail and the guide details are added because the audit needs them too.
const PAGES = [
  { name: 'inbox', hash: '#/inbox', ready: 'inbox-item' },
  { name: 'overview', hash: '#/overview', ready: 'lanes' },
  { name: 'roadmap', hash: '#/repo/acme__shop/roadmap', ready: 'rm-list' },
  { name: 'roadmap-detail', hash: '#/repo/acme__shop/roadmap/launch', ready: 'rm-detail' },
  { name: 'sessions', hash: '#/repo/acme__shop/sessions', ready: 'sessions' },
  { name: 'guide', hash: '#/guide', ready: 'guide-version' },
  { name: 'guide-details', hash: '#/guide/details', ready: 'guide-version' },
  { name: 'activity', hash: '#/activity', ready: 'activity' },
] as const;
const THEMES = ['dark', 'light'] as const;
const VIEWPORTS = [
  { width: 1360, height: 900 },
  { width: 390, height: 844 },
] as const;

test.describe('hub screenshots', () => {
  test.skip(!DIR, 'set CADDIS_SCREENS_DIR to take the screenshots');

  for (const vp of VIEWPORTS) {
    test.describe(`${vp.width} px`, () => {
      test.use({ viewport: vp });
      for (const theme of THEMES) {
        test(`${theme}`, async ({ page, openHub }) => {
          test.setTimeout(120_000);
          mkdirSync(DIR as string, { recursive: true });
          await page.addInitScript((t) => window.localStorage.setItem('caddis-hub-theme', t), theme);
          await openHub('full', withGuide);
          await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
          for (const p of PAGES) {
            await page.evaluate((h) => {
              window.location.hash = h;
            }, p.hash);
            await expect(page.locator('main')).toBeVisible();
            if (p.ready) await expect(page.getByTestId(p.ready).first()).toBeVisible();
            await page.evaluate(() => document.fonts.ready);
            await page.mouse.move(0, 0);
            await page.screenshot({ path: join(DIR as string, `${p.name}-${theme}-${vp.width}.png`), fullPage: true, animations: 'disabled' });
          }
        });
      }
    });
  }
});
