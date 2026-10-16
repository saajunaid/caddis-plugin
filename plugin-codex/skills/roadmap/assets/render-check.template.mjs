// Render check template. Copy it into the app (for example frontend/render-check.mjs) so CI and prod checks can run it.
//
// Usage:
//   node render-check.mjs --base http://localhost:5173 --path /dashboard --expect kpi-total --expect chart-main
//   node render-check.mjs --prod https://app.example.com --path /dashboard --expect kpi-total --channel msedge \
//        --allow-auth app.example.com
//   node render-check.mjs --base http://localhost:5173 --path /dashboard --expect kpi-total --prove-it-can-fail
//
// Options:
//   --base <url> | --prod <url>   Origin to test (local or prod). One of them is required.
//   --path <path>                 Page path. Default "/".
//   --expect <testid>             A data-testid that must be visible. Repeat it.
//   --channel <name>              Browser channel, for example msedge. Default: bundled chromium.
//   --allow-auth <host>           Host that may use the current Windows login (NTLM). Repeat it.
//   --settle <ms>                 Wait after network idle. Default 3000.
//   --prove-it-can-fail           Add a test id that does not exist. The run must then exit 1.
// Exit codes: 0 all checks pass, 1 a check failed, 4 bad arguments.
import { chromium } from 'playwright'; // or: import { chromium } from '@playwright/test';

const args = process.argv.slice(2);
const opt = (name) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : undefined; };
const all = (name) => args.flatMap((a, i) => (a === name ? [args[i + 1]] : []));

const origin = opt('--prod') ?? opt('--base');
if (!origin) { console.error('give --base <url> or --prod <url>'); process.exit(4); }
const path = opt('--path') ?? '/';
const settle = Number(opt('--settle') ?? 3000);
const expected = all('--expect');
const allowAuth = all('--allow-auth');
if (args.includes('--prove-it-can-fail')) expected.push('testid-that-does-not-exist');
if (expected.length === 0) { console.error('give at least one --expect <testid>'); process.exit(4); }

const launch = { headless: true };
if (opt('--channel')) launch.channel = opt('--channel');
if (allowAuth.length) launch.args = [`--auth-server-allowlist=${allowAuth.join(',')}`];

const failures = [];
const browser = await chromium.launch(launch);
for (const width of [1440, 400]) {
  const context = await browser.newContext({ viewport: { width, height: 900 } });
  // Dark theme seeded before any page script runs. Change the key and value to match the app.
  await context.addInitScript(() => { try { localStorage.setItem('theme', 'dark'); } catch { /* ignore */ } });
  const page = await context.newPage();
  let consoleErrors = 0;
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors += 1; });
  page.on('pageerror', () => { consoleErrors += 1; });

  await page.goto(new URL(path, origin).toString());
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(settle);

  if (consoleErrors > 0) failures.push(`${width}px: ${consoleErrors} console error(s)`);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  if (overflow) failures.push(`${width}px: horizontal scroll`);
  for (const id of expected) {
    const visible = await page.getByTestId(id).first().isVisible().catch(() => false);
    if (!visible) failures.push(`${width}px: data-testid "${id}" is not visible`);
  }
  console.log(`${width}px: console errors ${consoleErrors}, horizontal scroll ${overflow ? 'yes' : 'no'}`);
  await context.close();
}
await browser.close();

if (failures.length) {
  for (const f of failures) console.error(`FAIL ${f}`);
  process.exit(1);
}
console.log('PASS render check');
