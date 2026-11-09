import { randomBytes } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { startServer, type HubServer } from '../src/hub/server';
import { loadFixture, NOW } from './fixtures';

/**
 * Render budget (plan hub-done-plans, D11c). Runs only when CADDIS_PERF_OUT is set; it writes one JSON file with the
 * medians of 5 runs per page and theme. With CADDIS_PERF_BASE set to an earlier file, it also checks the budget.
 *
 * One page at a time, in headless Chromium on this machine (software drawing: the no-GPU worst case), fixture `full`,
 * 1360x900. Per run, measured in the page with `performance` and requestAnimationFrame:
 * - fcp_ms: first contentful paint of a fresh page load;
 * - scroll: frame times while the page scrolls top to bottom and back in 60 rAF steps (30 down, 30 up);
 * - hover: frame times while the pointer moves over 10 cards or tiles (6 mouse steps each).
 * A long frame is a frame over 50 ms.
 *
 * This spec does not use the `openHub` fixture: its page clock fakes requestAnimationFrame and `performance`. Only
 * `Date` is moved to the fixture time, so relative times read as in the other specs.
 */
const OUT = process.env.CADDIS_PERF_OUT;
const BASE = process.env.CADDIS_PERF_BASE;
const RUNS = 5;
const LONG_MS = 50;
const KEY_HEADER = 'x-caddis-hub-key';

const PAGES = [
  { name: 'inbox', hash: '#/inbox', ready: '[data-testid="inbox-list"]', hover: '[data-testid="inbox-item"]' },
  {
    name: 'overview',
    hash: '#/overview',
    ready: '[data-testid="lanes"], [data-testid="repo-cards"]',
    hover: '[data-testid="lane-card"], [data-testid="repo-card"]',
  },
  {
    name: 'roadmap-detail',
    hash: '#/repo/acme__shop/roadmap/launch',
    ready: '[data-testid="rm-detail"]',
    hover: '[data-testid="rm-kpis"] .kpi-tile, [data-testid="rm-timeline"] .rm-tile',
  },
] as const;
const THEMES = ['dark', 'light'] as const;

interface Run {
  fcp_ms: number;
  scroll_p95_ms: number;
  scroll_long: number;
  hover_p95_ms: number;
  hover_long: number;
}
type Medians = Run;
interface Report {
  schema: 1;
  measured_at: string;
  browser: string;
  viewport: { width: number; height: number };
  runs: number;
  long_frame_ms: number;
  results: Record<string, Record<string, Medians & { runs: Run[] }>>;
}

// Read the base once, before any write: OUT may be the same file as BASE.
const BASE_REPORT: Report | null = BASE && existsSync(BASE) ? (JSON.parse(readFileSync(BASE, 'utf8')) as Report) : null;

const report: Report = {
  schema: 1,
  measured_at: '',
  browser: '',
  viewport: { width: 1360, height: 900 },
  runs: RUNS,
  long_frame_ms: LONG_MS,
  results: {},
};

const median = (xs: number[]): number => {
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  const at = (i: number): number => s[i] ?? 0;
  return s.length % 2 ? at(m) : (at(m - 1) + at(m)) / 2;
};
const p95 = (xs: number[]): number => {
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.ceil(s.length * 0.95) - 1)] ?? 0;
};
const round = (n: number): number => Math.round(n * 10) / 10;

/** Wait n animation frames in the page. */
const frames = (page: Page, n: number): Promise<void> =>
  page.evaluate(
    (count) =>
      new Promise<void>((done) => {
        let i = 0;
        const tick = (): void => {
          if (++i >= count) done();
          else requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      }),
    n,
  );

/** Scroll top to bottom and back in 60 rAF steps; return the frame times. */
const scrollFrames = (page: Page): Promise<number[]> =>
  page.evaluate(
    () =>
      new Promise<number[]>((done) => {
        const el = document.scrollingElement ?? document.documentElement;
        const max = Math.max(0, el.scrollHeight - el.clientHeight);
        const half = 30;
        const ts: number[] = [];
        let i = 0;
        const step = (t: number): void => {
          ts.push(t);
          if (i > 2 * half) {
            done(ts.slice(1).map((x, k) => x - (ts[k] ?? x)));
            return;
          }
          const pos = i <= half ? i / half : (2 * half - i) / half;
          el.scrollTop = Math.round(max * pos);
          i++;
          requestAnimationFrame(step);
        };
        el.scrollTop = 0;
        requestAnimationFrame(step);
      }),
  );

/** Start a frame-time recorder in the page. */
const startRecorder = (page: Page): Promise<void> =>
  page.evaluate(() => {
    const w = window as unknown as { __rec: { ts: number[]; on: boolean } };
    w.__rec = { ts: [], on: true };
    const tick = (t: number): void => {
      w.__rec.ts.push(t);
      if (w.__rec.on) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });

const stopRecorder = (page: Page): Promise<number[]> =>
  page.evaluate(
    () =>
      new Promise<number[]>((done) => {
        const w = window as unknown as { __rec: { ts: number[]; on: boolean } };
        requestAnimationFrame(() => {
          w.__rec.on = false;
          const ts = w.__rec.ts;
          done(ts.slice(1).map((x, k) => x - (ts[k] ?? x)));
        });
      }),
  );

async function hoverFrames(page: Page, selector: string): Promise<number[]> {
  const all = page.locator(selector);
  const targets = [];
  for (let i = 0; i < (await all.count()) && targets.length < 10; i++) {
    if (await all.nth(i).isVisible()) targets.push(all.nth(i));
  }
  expect(targets.length, `hover targets for ${selector}`).toBeGreaterThan(0);
  const times: number[] = [];
  await page.mouse.move(1, 1);
  for (let i = 0; i < 10; i++) {
    const t = targets[i % targets.length];
    if (!t) continue;
    // Bring the target into view first, and leave that scroll out of the hover frames.
    await t.evaluate((el) => el.scrollIntoView({ block: 'center', behavior: 'instant' }));
    await frames(page, 3);
    const box = await t.boundingBox();
    if (!box) continue;
    await startRecorder(page);
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 6 });
    await frames(page, 3);
    times.push(...(await stopRecorder(page)));
  }
  return times;
}

async function signIn(page: Page, srv: HubServer, key: string): Promise<void> {
  const res = await fetch(`http://127.0.0.1:${srv.port}/api/hub/code`, { method: 'POST', headers: { [KEY_HEADER]: key } });
  const { code } = (await res.json()) as { code: string };
  await page.goto(`http://127.0.0.1:${srv.port}/login?code=${code}`);
  await expect(page.getByTestId('data-age')).toContainText('Updated');
}

function checkBudget(name: string, theme: string, now: Medians): void {
  if (!BASE_REPORT) return;
  const before = BASE_REPORT.results[name]?.[theme];
  if (!before) return;
  const where = `${name} ${theme}`;
  // FCP: x 1.10 OR + 8 ms (orchestrator, 8 Nov: the 16-40 ms base is inside timer noise; one frame step misses x 1.10).
  expect(now.fcp_ms, `${where} fcp`).toBeLessThanOrEqual(Math.max(before.fcp_ms * 1.1, before.fcp_ms + 8));
  expect(now.scroll_p95_ms, `${where} scroll p95`).toBeLessThanOrEqual(before.scroll_p95_ms * 1.15);
  expect(now.scroll_long, `${where} scroll long frames`).toBeLessThanOrEqual(before.scroll_long + 2);
  expect(now.hover_p95_ms, `${where} hover p95`).toBeLessThanOrEqual(before.hover_p95_ms * 1.15);
  expect(now.hover_long, `${where} hover long frames`).toBeLessThanOrEqual(before.hover_long + 2);
}

test.describe('hub render budget', () => {
  test.describe.configure({ mode: 'serial' });
  test.skip(!OUT, 'set CADDIS_PERF_OUT to measure');
  test.use({ viewport: { width: 1360, height: 900 } });

  for (const p of PAGES) {
    for (const theme of THEMES) {
      test(`${p.name} ${theme}`, async ({ page, browser }) => {
        test.setTimeout(180_000);
        const key = randomBytes(32).toString('hex');
        const state = loadFixture('full');
        const srv = await startServer({ port: 0, key, getState: () => state, versions: { hub: '0.0.0-e2e' } });
        try {
          await page.addInitScript(
            ({ now, t }) => {
              window.localStorage.setItem('caddis-hub-theme', t);
              const Real = Date;
              const offset = Real.parse(now) - Real.now();
              class Shifted extends Real {
                constructor(...a: unknown[]) {
                  if (a.length === 0) super(Real.now() + offset);
                  else super(...(a as [number]));
                }
                static override now(): number {
                  return Real.now() + offset;
                }
              }
              window.Date = Shifted as DateConstructor;
            },
            { now: NOW, t: theme },
          );
          await signIn(page, srv, key);
          await page.evaluate((h) => {
            window.location.hash = h;
          }, p.hash);

          const runs: Run[] = [];
          for (let r = 0; r < RUNS; r++) {
            await page.reload({ waitUntil: 'load' });
            await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
            await expect(page.locator(p.ready).first()).toBeVisible();
            const fcp = await page.evaluate(
              () =>
                new Promise<number>((done) => {
                  const e = performance.getEntriesByName('first-contentful-paint')[0];
                  if (e) return done(e.startTime);
                  const obs = new PerformanceObserver((l) => {
                    const f = l.getEntriesByName('first-contentful-paint')[0];
                    if (!f) return;
                    obs.disconnect();
                    done(f.startTime);
                  });
                  obs.observe({ type: 'paint', buffered: true });
                }),
            );
            await page.evaluate(() => document.fonts.ready);
            await frames(page, 45);
            const scroll = await scrollFrames(page);
            const hover = await hoverFrames(page, p.hover);
            runs.push({
              fcp_ms: round(fcp),
              scroll_p95_ms: round(p95(scroll)),
              scroll_long: scroll.filter((x) => x > LONG_MS).length,
              hover_p95_ms: round(p95(hover)),
              hover_long: hover.filter((x) => x > LONG_MS).length,
            });
          }
          const med: Medians = {
            fcp_ms: round(median(runs.map((x) => x.fcp_ms))),
            scroll_p95_ms: round(median(runs.map((x) => x.scroll_p95_ms))),
            scroll_long: median(runs.map((x) => x.scroll_long)),
            hover_p95_ms: round(median(runs.map((x) => x.hover_p95_ms))),
            hover_long: median(runs.map((x) => x.hover_long)),
          };
          report.measured_at = new Date(Date.now()).toISOString();
          report.browser = `chromium ${browser.version()}`;
          (report.results[p.name] ??= {})[theme] = { ...med, runs };
          mkdirSync(dirname(OUT as string), { recursive: true });
          writeFileSync(OUT as string, `${JSON.stringify(report, null, 2)}\n`);
          checkBudget(p.name, theme, med);
        } finally {
          await srv.close();
        }
      });
    }
  }
});
