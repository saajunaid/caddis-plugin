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

  test('the side menu lists the four guide pages and marks the open one', async ({ page, openHub }) => {
    await openHub('full', withGuide, '#/guide');
    const sub = page.getByRole('list', { name: 'caddis guide pages' });
    await expect(sub.getByRole('link')).toHaveText(['Poster', 'Details', 'Wall poster', 'Map']);
    const poster = sub.getByRole('link', { name: 'Poster', exact: true });
    const map = sub.getByRole('link', { name: 'Map', exact: true });
    await expect(poster).toHaveAttribute('aria-current', 'true');
    await map.click();
    await expect(page).toHaveURL(/#\/guide\/map$/);
    await expect(page.getByTestId('guide-map')).toBeVisible();
    await expect(map).toHaveAttribute('aria-current', 'true');
    await expect(poster).not.toHaveAttribute('aria-current', 'true');
    await expect(page.getByRole('link', { name: /caddis guide/ })).toHaveAttribute('aria-current', 'page');
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
  test.describe('wall poster', () => {
    // A guide the size of the real one: 40 commands across the stages, 12 agents.
    const STAGES = ['plan', 'plan', 'plan', 'plan', 'plan', 'plan', 'build', 'build', 'build', 'review', 'review', 'review', 'review', 'ship', 'ship', 'ship', 'ship', 'continuity', 'continuity', 'continuity', 'continuity', 'continuity', 'continuity', 'continuity', 'knowledge', 'knowledge', 'knowledge', 'knowledge', 'knowledge', 'setup', 'setup', 'setup', 'setup', 'setup', 'setup', 'setup', 'setup', 'setup', 'setup', 'setup'];
    const big = (s: State): void => {
      withGuide(s);
      s.guide.commands = STAGES.map((stage, i) => ({
        name: `command-${i}`,
        description: 'Questions, then a requirements doc that is long enough to need a cut. Second sentence.',
        hint: i % 3 === 0 ? '<some argument>' : '',
        steps: [],
        scripts: [],
        noArgs: i % 3 !== 0,
        stage,
        daily: i % 5 === 0,
      }));
      s.guide.agents = Array.from({ length: 12 }, (_, i) => ({ name: `agent-${i}`, description: 'Find the root cause of a bug.', tools: ['Read'], model: 'sonnet', writes: i % 4 === 0 }));
    };

    test('renders a row per command and agent, and links to the details', async ({ page, openHub }) => {
      const { problems } = await openHub('full', big, '#/guide/wall');
      await expect(page.getByTestId('guide-wall-sheet')).toBeVisible();
      await expect(page.locator('.gw-row')).toHaveCount(STAGES.length + 12);
      await page.locator('.gw-name', { hasText: '/command-0' }).click();
      await expect(page).toHaveURL(/#\/guide\/details\/g-command-command-0/);
      expect(problems.console).toEqual([]);
    });

    test('the sheet is A4 landscape, nothing is cut off, and it prints on one page', async ({ page, openHub }) => {
      await openHub('full', big, '#/guide/wall');
      await expect(page.getByTestId('guide-wall-sheet')).toBeVisible();
      const clipped = await page.evaluate(() => {
        const cards = document.querySelector('.gw-cards') as HTMLElement;
        return { h: cards.scrollHeight - cards.clientHeight, w: cards.scrollWidth - cards.clientWidth };
      });
      expect(clipped.h, 'cards are cut off at the bottom').toBeLessThanOrEqual(1);
      expect(clipped.w, 'a fifth column is cut off at the right').toBeLessThanOrEqual(1);
      const scale = await page.evaluate(() => Number(getComputedStyle(document.querySelector('.gw-cards')!).getPropertyValue('--gw-scale')));
      expect(scale, 'text shrank below the readable minimum').toBeGreaterThanOrEqual(0.6);
      await page.emulateMedia({ media: 'print' });
      const pdf = await page.pdf({ preferCSSPageSize: true });
      const pages = (pdf.toString('latin1').match(/\/Type\s*\/Page(?!s)/g) ?? []).length;
      expect(pages).toBe(1);
      const box = /\/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]/.exec(pdf.toString('latin1'));
      expect(Number(box?.[1])).toBeGreaterThan(Number(box?.[2]));
    });

    test('missing guide data shows the state, not the sheet', async ({ page, openHub }) => {
      await openHub('full', (s) => { s.guide = null; }, '#/guide/wall');
      await expect(page.getByTestId('guide-state')).toBeVisible();
      await expect(page.getByTestId('guide-wall-sheet')).toHaveCount(0);
    });
  });

  test.describe('plugin map', () => {
    // A guide the size of the real one: 40 commands, 12 agents, 70 skills in 8 families, 11 hook events.
    const STAGES = ['plan', 'build', 'review', 'ship', 'continuity', 'knowledge', 'setup', 'plan', 'review', 'ship'];
    const EVENTS = ['SessionStart', 'UserPromptSubmit', 'PreToolUse', 'PermissionRequest', 'PostToolUse', 'PostToolUseFailure', 'Notification', 'SubagentStop', 'Stop', 'PreCompact', 'SessionEnd'];
    const COMMANDS = 40;
    const AGENTS = 12;
    const SKILLS = 70;
    const big = (s: State): void => {
      withGuide(s);
      s.guide.commands = Array.from({ length: COMMANDS }, (_, i) => ({
        name: `command-${i}`,
        description: 'Questions, then a requirements doc that is long enough to need a cut. Second sentence.',
        hint: '',
        steps: [],
        scripts: [],
        noArgs: true,
        stage: STAGES[i % STAGES.length]!,
        daily: i % 5 === 0,
      }));
      s.guide.agents = Array.from({ length: AGENTS }, (_, i) => ({ name: `agent-${i}`, description: 'Find the root cause of a bug.', tools: ['Read'], model: i % 3 === 0 ? 'opus' : 'sonnet', writes: i % 4 === 0 }));
      s.guide.skills = Array.from({ length: SKILLS }, (_, i) => ({ name: `skill-${i}`, category: `family-${i % 8}`, description: 'A skill.', core: i % 9 === 0 }));
      s.guide.hooks = EVENTS.map((event, i) => ({ event, matcher: i % 2 ? 'Bash|Edit' : '(every)', handler: `hooks/script_${i}.py` }));
    };

    test('shows every section, links to the details, and has no console problems', async ({ page, openHub }) => {
      const { problems } = await openHub('full', big, '#/guide/map');
      await expect(page.getByTestId('guide-map-sheet')).toBeVisible();
      await expect(page.getByRole('tab', { name: 'Map' })).toHaveAttribute('aria-selected', 'true');
      await expect(page.locator('.gm-item')).toHaveCount(COMMANDS);
      await expect(page.locator('.gm-agent')).toHaveCount(AGENTS);
      await expect(page.locator('.gm-chip')).toHaveCount(SKILLS);
      await expect(page.locator('.gm-event')).toHaveCount(EVENTS.length);
      await page.locator('.gm-name', { hasText: '/command-0' }).click();
      await expect(page).toHaveURL(/#\/guide\/details\/g-command-command-0/);
      expect(problems.console).toEqual([]);
    });

    test('the filter dims what does not match and shows the match count', async ({ page, openHub }) => {
      await openHub('full', big, '#/guide/map');
      await page.getByTestId('guide-map-filter').fill('agent-1');
      await expect(page.getByTestId('guide-map-matches')).toHaveText('3 matches');
      await expect(page.locator('.gm-agent:not(.gm-dim)')).toHaveCount(3);
      await expect(page.locator('.gm-item:not(.gm-dim)')).toHaveCount(0);
      await page.getByTestId('guide-map-filter').fill('');
      await expect(page.locator('.gm-dim')).toHaveCount(0);
    });

    test('prints on A3 landscape in at most two pages', async ({ page, openHub }) => {
      await openHub('full', big, '#/guide/map');
      await expect(page.getByTestId('guide-map-sheet')).toBeVisible();
      await page.emulateMedia({ media: 'print' });
      const pdf = (await page.pdf({ preferCSSPageSize: true })).toString('latin1');
      const pages = (pdf.match(/\/Type\s*\/Page(?!s)/g) ?? []).length;
      expect(pages).toBeGreaterThanOrEqual(1);
      expect(pages).toBeLessThanOrEqual(2);
      const box = /\/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]/.exec(pdf);
      expect(Number(box?.[1])).toBeGreaterThan(Number(box?.[2]));
      expect(Number(box?.[1]), 'wider than an A4 sheet').toBeGreaterThan(1180);
    });

    test('missing guide data shows the state, not the map', async ({ page, openHub }) => {
      await openHub('full', (s) => { s.guide = null; }, '#/guide/map');
      await expect(page.getByTestId('guide-state')).toBeVisible();
      await expect(page.getByTestId('guide-map-sheet')).toHaveCount(0);
    });

    test.describe('phone width', () => {
      test.use({ viewport: { width: 390, height: 800 } });
      test('no horizontal scroll, with data and with a filter', async ({ page, openHub }) => {
        await openHub('full', big, '#/guide/map');
        await expect(page.getByTestId('guide-map-sheet')).toBeVisible();
        const fits = (): Promise<boolean> =>
          page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
        expect(await fits()).toBe(true);
        await page.getByTestId('guide-map-filter').fill('skill');
        expect(await fits()).toBe(true);
      });
    });
  });
});
